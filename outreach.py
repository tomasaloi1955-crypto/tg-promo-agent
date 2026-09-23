# -*- coding: utf-8 -*-
"""
Поиск клиентов для услуги «Telegram-канал ведётся сам» (автопостинг).

Раз в день ищет публичные КАНАЛЫ целевой аудитории — магазины и бренды, эксперты,
тренеры и преподаватели, онлайн-школы, мусульманские проекты — у которых:
  • в описании есть контакт владельца (@username или t.me/username);
  • канал живой, но постит нерегулярно (владельцу не хватает времени — это и есть клиент);
  • ниша не из запрещённых (казино, ставки, алкоголь, табак, кредиты, 18+ и т.п.).
Gemini проверяет, подходит ли канал, и пишет личное первое сообщение владельцу
(с конкретикой из его канала и предложением 3 бесплатных пробных постов).

По умолчанию агент НИЧЕГО не отправляет владельцам каналов сам: он присылает вам
в Telegram (бот-уведомитель) список «канал → контакт → готовый текст», а вы
пересылаете 5–10 сообщений в день вручную. Массовые сообщения незнакомым людям
с личного аккаунта — самый быстрый путь к спам-блоку аккаунта (а он же ведёт
промо-агента). Автоотправку можно включить OUTREACH_AUTO_SEND=1 — с жёстким
лимитом OUTREACH_MAX_SENDS_PER_RUN (по умолчанию 3) и остановкой при первом
предупреждении Telegram о спаме.

Каждый канал обрабатывается один раз навсегда (outreach_memory.json), каждому
контакту пишем не больше одного раза.

Приватность: репозиторий публичный, поэтому в outreach_memory.json лежат не @username-ы,
а их HMAC-отпечатки (ключ — секрет API_HASH): повтор агент узнаёт, а прочитать по файлу,
кого он нашёл, нельзя. В журнал Actions (он тоже публичный) не пишутся ни каналы,
ни контакты, ни тексты — они уходят только вам в Telegram.
"""
import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from telethon import TelegramClient, errors, functions, types
from telethon.sessions import StringSession

import gemini
from promo import API_HASH, API_ID, BOT_TOKEN, OWNER_ID, SESSION_STRING, StopRun, flood_safe

BASE = Path(__file__).parent
MEMORY_FILE = BASE / "outreach_memory.json"

# Где лежит ваш пост с предложением услуги — ссылка уходит в каждом сообщении.
OFFER_LINK = os.getenv("OUTREACH_OFFER_LINK") or "https://t.me/Halalaifreya"

LEADS_PER_RUN = int(os.getenv("OUTREACH_LEADS_PER_RUN", "7"))
MAX_CHANNELS_TO_CHECK = int(os.getenv("OUTREACH_MAX_CHANNELS_TO_CHECK", "30"))
# Бесплатный Gemini даёт немного запросов в сутки, а его же тратят promo.py и promo_sport.py.
MAX_GEMINI_CALLS = int(os.getenv("OUTREACH_MAX_GEMINI_CALLS", "10"))
MIN_SUBSCRIBERS = int(os.getenv("OUTREACH_MIN_SUBSCRIBERS", "300"))
MAX_SUBSCRIBERS = int(os.getenv("OUTREACH_MAX_SUBSCRIBERS", "30000"))
# «Живой» канал: последний пост не старше N дней (заброшенные не платят за ведение).
MAX_DAYS_SINCE_LAST_POST = int(os.getenv("OUTREACH_MAX_DAYS_SINCE_LAST_POST", "45"))
# Постит реже, чем N раз за 30 дней, — значит, времени на канал не хватает.
MAX_POSTS_30D = int(os.getenv("OUTREACH_MAX_POSTS_30D", "20"))

AUTO_SEND = os.getenv("OUTREACH_AUTO_SEND", "").lower() in ("1", "true", "yes", "on")
MAX_SENDS_PER_RUN = min(int(os.getenv("OUTREACH_MAX_SENDS_PER_RUN", "3")), 5)
SEND_MIN_DELAY = 90
SEND_MAX_DELAY = 240

SEARCH_KEYWORDS = [
    # магазины и бренды
    "магазин одежды", "интернет магазин", "магазин хиджабов", "мусульманская одежда",
    "скромная одежда", "абайи", "детская одежда магазин", "магазин косметики",
    "handmade изделия", "товары для дома", "халяль продукты", "исламские товары",
    "цветы доставка", "кондитер на заказ", "торты на заказ",
    # эксперты, тренеры, преподаватели
    "психолог", "нутрициолог", "фитнес тренер", "коуч", "стилист", "визажист",
    "репетитор", "логопед", "преподаватель арабского", "преподаватель английского",
    "таджвид", "мастер маникюра",
    # онлайн-школы и образование
    "онлайн школа", "онлайн курсы", "школа арабского языка", "школа английского",
    "курсы для мам", "обучение онлайн",
]

# Жёсткий отсев по названию/описанию — до Gemini, чтобы не тратить запросы.
STOP_WORDS = [
    "казино", "casino", "ставк", "букмекер", "беттинг", "betting", "слот", "покер",
    "форекс", "forex", "трейдинг", "крипт", "crypto", "p2p", "арбитраж",
    "алкогол", "пиво", "виски", "табак", "вейп", "vape", "кальян", "снюс",
    "кредит", "займ", "микрофинанс", "18+", "эрот", "интим", "onlyfans",
    "магия", "гадани", "таро", "приворот", "эзотерик", "астролог",
    "заработок без вложений", "пассивный доход", "схема заработка", "халтур",
    "новости", "news", "мемы", "приколы",
]

USERNAME_RE = re.compile(r"(?:@|(?:https?://)?(?:t|telegram)\.me/)([A-Za-z][A-Za-z0-9_]{3,31})\b")
_NOT_USERNAMES = {"joinchat", "addlist", "share", "proxy", "iv", "s", "c"}


class GeminiUnavailable(Exception):
    """Gemini не ответил — прекращаем проверку каналов до следующего прогона."""


# ---------------------------------------------------------------- память

def load_memory() -> dict:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    return {"channels": {}, "contacts": {}}


def save_memory(mem: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def fingerprint(name: str) -> str:
    """Отпечаток @username для памяти: сравнить можно, прочитать нельзя."""
    return hmac.new(API_HASH.encode(), name.lstrip("@").lower().encode(), hashlib.sha256).hexdigest()[:20]


def mark_channel(mem: dict, key: str, status: str) -> None:
    mem["channels"][fingerprint(key)] = {"date": date.today().isoformat(), "status": status}


def notify(text: str) -> None:
    """Только в Telegram владелице — без print: журнал Actions публичный."""
    if not BOT_TOKEN or not OWNER_ID:
        print("  ! BOT_TOKEN/OWNER_ID не заданы — отчёт некуда отправить")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_ID, "text": text},
            timeout=20,
        )
    except Exception as e:
        print(f"  ! не удалось отправить уведомление: {e.__class__.__name__}")


# ---------------------------------------------------------------- разбор канала

def find_stop_word(text: str) -> Optional[str]:
    low = text.lower()
    for w in STOP_WORDS:
        if w in low:
            return w
    return None


def extract_contacts(about: str, own_username: str) -> list[str]:
    """@username-ы из описания канала, кроме самого канала и ботов, в порядке появления."""
    out: list[str] = []
    for m in USERNAME_RE.finditer(about or ""):
        name = m.group(1)
        low = name.lower()
        if low in _NOT_USERNAMES or low == own_username.lower() or low.endswith("bot"):
            continue
        if low not in (c.lower() for c in out):
            out.append(name)
    return out


def activity(dates: list[datetime], now: datetime) -> tuple[Optional[int], int]:
    """(дней с последнего поста, постов за 30 дней)."""
    if not dates:
        return None, 0
    last = max(dates)
    month_ago = now - timedelta(days=30)
    return (now - last).days, sum(1 for d in dates if d >= month_ago)


def template_message(title: str) -> str:
    """Запасной текст, если Gemini недоступен."""
    return (
        f"Здравствуйте! Посмотрела ваш канал «{title}» — у вас хороший контент, "
        "но посты выходят нерегулярно. Могу настроить так, чтобы канал вёлся сам: "
        "посты каждый день в вашем стиле, а от вас — 10 минут в неделю на утверждение тем. "
        "Если интересно, бесплатно подготовлю 3 пробных поста в стиле вашего канала, "
        "чтобы вы оценили результат до оплаты.\n"
        f"Подробнее и цены: {OFFER_LINK}"
    )


async def _resolve_contact(client: TelegramClient, username: str) -> Optional[types.User]:
    """Контакт должен быть живым человеком, а не каналом/группой/ботом."""
    try:
        entity = await flood_safe(lambda: client.get_entity(username))
    except (ValueError, errors.RPCError):
        return None
    if isinstance(entity, types.User) and not entity.bot and not entity.deleted:
        return entity
    return None


# ---------------------------------------------------------------- поиск

async def search_channels(client: TelegramClient, mem: dict) -> list[types.Channel]:
    keywords = SEARCH_KEYWORDS[:]
    random.shuffle(keywords)
    found: dict[str, types.Channel] = {}
    for kw in keywords:
        try:
            res = await flood_safe(lambda: client(functions.contacts.SearchRequest(q=kw, limit=20)))
        except StopRun:
            raise
        except Exception as e:
            print(f"  ! поиск не удался: {e.__class__.__name__}")
            continue
        for chat in res.chats:
            if not isinstance(chat, types.Channel) or not chat.broadcast or not chat.username:
                continue
            key = f"@{chat.username.lower()}"
            if fingerprint(key) in mem["channels"] or key in found:
                continue
            if not MIN_SUBSCRIBERS <= (chat.participants_count or 0) <= MAX_SUBSCRIBERS:
                continue
            found[key] = chat
        if len(found) >= MAX_CHANNELS_TO_CHECK:
            break
        await asyncio.sleep(random.uniform(2, 5))
    return list(found.values())


async def check_channel(client: TelegramClient, chat: types.Channel, mem: dict, gemini_budget: list) -> Optional[dict]:
    """Проверяет канал; возвращает лида или None (причина — в памяти)."""
    key = f"@{chat.username.lower()}"

    if w := find_stop_word(chat.title):
        mark_channel(mem, key, "rejected")
        return None

    full = await flood_safe(lambda: client(functions.channels.GetFullChannelRequest(chat)))
    about = full.full_chat.about or ""
    if w := find_stop_word(about):
        mark_channel(mem, key, "rejected")
        return None

    contacts = [c for c in extract_contacts(about, chat.username) if fingerprint(c) not in mem["contacts"]]
    if not contacts:
        mark_channel(mem, key, "rejected")
        return None

    msgs = await flood_safe(lambda: client.get_messages(chat, limit=30))
    days_since, posts_30d = activity([m.date for m in msgs if m.date], datetime.now(timezone.utc))
    if days_since is None or days_since > MAX_DAYS_SINCE_LAST_POST:
        mark_channel(mem, key, "rejected")
        return None
    if posts_30d > MAX_POSTS_30D:
        mark_channel(mem, key, "rejected")
        return None

    contact = None
    for name in contacts[:2]:
        contact = await _resolve_contact(client, name)
        if contact:
            break
    if not contact:
        mark_channel(mem, key, "rejected")
        return None
    contact_name = contact.username or contacts[0]

    posts = [m.message for m in msgs if m.message][:4]
    verdict = None
    if gemini_budget[0] > 0:
        gemini_budget[0] -= 1
        verdict = gemini.evaluate_channel_lead(chat.title, about, posts, OFFER_LINK)
        await asyncio.sleep(8)  # минутный лимит бесплатного Gemini
        if verdict is None and gemini.GEMINI_API_KEY:
            # Скорее всего кончилась суточная квота (её делят promo.py и promo_sport.py).
            # Непроверенных лидов не шлём; канал не помечаем — проверим в другой день.
            raise GeminiUnavailable()
    if verdict is not None and not verdict.get("fit"):
        mark_channel(mem, key, "rejected")
        return None
    message = (verdict or {}).get("message", "").strip()
    if OFFER_LINK not in message:
        message = template_message(chat.title) if not message else f"{message}\nПодробнее и цены: {OFFER_LINK}"

    return {
        "key": key,
        "title": chat.title,
        "subscribers": chat.participants_count or 0,
        "days_since": days_since,
        "posts_30d": posts_30d,
        "niche": (verdict or {}).get("niche", "—"),
        "reason": (verdict or {}).get("reason", "Gemini не проверял — отобран по фильтрам"),
        "contact": contact_name,
        "contact_entity": contact,
        "message": message,
    }


# ---------------------------------------------------------------- отправка

async def send_to_owner(client: TelegramClient, lead: dict) -> tuple[bool, str]:
    try:
        await client.send_message(lead["contact_entity"], lead["message"])
        return True, ""
    except errors.PeerFloodError:
        raise StopRun("Telegram пометил аккаунт как рассылающий спам (PeerFlood) — автоотправка остановлена")
    except errors.FloodWaitError as e:
        raise StopRun(f"FloodWait {e.seconds}с при отправке — автоотправка остановлена")
    except errors.RPCError as e:
        return False, e.__class__.__name__


def report_lead(n: int, lead: dict, sent: Optional[bool]) -> None:
    status = {True: "✅ отправлено автоматически", False: "⚠️ автоотправка не удалась — отправьте вручную",
              None: "✉️ отправьте вручную (текст — следующим сообщением)"}[sent]
    notify(
        f"🎯 Клиент #{n}: {lead['title']}\n"
        f"Канал: https://t.me/{lead['key'][1:]} — {lead['subscribers']} подписчиков\n"
        f"Ниша: {lead['niche']}\n"
        f"Активность: последний пост {lead['days_since']} дн. назад, {lead['posts_30d']} постов за 30 дней\n"
        f"Почему подходит: {lead['reason']}\n"
        f"Написать: https://t.me/{lead['contact']}\n"
        f"{status}"
    )
    if sent is not True:
        notify(lead["message"])


# ---------------------------------------------------------------- прогон

async def run() -> None:
    mem = load_memory()
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    leads: list[dict] = []
    stop_reason = None
    sends_used = 0
    try:
        channels = await search_channels(client, mem)
        print(f"Найдено новых каналов для проверки: {len(channels)}")
        gemini_budget = [MAX_GEMINI_CALLS]
        for i, chat in enumerate(channels[:MAX_CHANNELS_TO_CHECK], 1):
            if len(leads) >= LEADS_PER_RUN:
                break
            if gemini.GEMINI_API_KEY and gemini_budget[0] <= 0:
                print("Лимит запросов Gemini на прогон исчерпан — без его проверки лидов не шлю")
                break
            print(f"Проверяю канал {i}/{len(channels)}...")
            try:
                lead = await check_channel(client, chat, mem, gemini_budget)
            except StopRun:
                raise
            except GeminiUnavailable:
                stop_reason = "Gemini не отвечает (вероятно, кончилась суточная квота) — остальные каналы проверю завтра"
                break
            except Exception as e:
                print(f"  ! ошибка проверки: {e.__class__.__name__}")
                continue
            await asyncio.sleep(random.uniform(3, 7))
            if not lead:
                continue

            sent = None
            if AUTO_SEND and sends_used < MAX_SENDS_PER_RUN:
                if sends_used:
                    await asyncio.sleep(random.uniform(SEND_MIN_DELAY, SEND_MAX_DELAY))
                sends_used += 1
                sent, err = await send_to_owner(client, lead)
                if err:
                    print(f"  ! не отправилось: {err}")

            mark_channel(mem, lead["key"], "sent" if sent else "lead")
            mem["contacts"][fingerprint(lead["contact"])] = {"date": date.today().isoformat()}
            leads.append(lead)
            print(f"  → клиент #{len(leads)} найден, отправлен вам в Telegram")
            report_lead(len(leads), lead, sent)
    except StopRun as e:
        stop_reason = str(e)
        print(f"СТОП: {stop_reason}")
    finally:
        await client.disconnect()
        save_memory(mem)

    if stop_reason:
        notify(f"⚠️ Поиск клиентов остановлен: {stop_reason}")
    if leads:
        notify(f"Поиск клиентов: сегодня {len(leads)} новых. Отмечайте ответы у себя — повторно этим контактам агент не напишет.")
    elif not stop_reason:
        notify("Поиск клиентов: сегодня подходящих каналов с контактом владельца не нашлось.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(run())

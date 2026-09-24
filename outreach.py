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
# Ручной режим: сколько каналов из списка владелицы обрабатываем за один запуск.
MANUAL_MAX_CHANNELS = 10
# Паузы после вступления в приватный канал — вступления Telegram отслеживает строже всего.
MIN_JOIN_DELAY = 20
MAX_JOIN_DELAY = 45
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


def notify(text: str) -> bool:
    """Только в Telegram владелице — без print текста: журнал Actions публичный.
    True — если Telegram принял сообщение."""
    if not BOT_TOKEN or not OWNER_ID:
        print("  ! BOT_TOKEN/OWNER_ID не заданы — отчёт некуда отправить")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_ID, "text": text},
            timeout=20,
        )
    except Exception as e:
        print(f"  ! не удалось отправить уведомление: {e.__class__.__name__}")
        return False
    if not resp.ok:
        try:
            why = resp.json().get("description", "")
        except ValueError:
            why = ""
        print(f"  ! Telegram не принял уведомление: HTTP {resp.status_code} {why}")
        return False
    return True


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


# Существительные на -л, которые могут стоять сразу после «я» («я канал смотрю»).
_NOT_VERBS = {"канал", "материал", "журнал", "персонал", "потенциал", "сериал", "финал", "идеал",
              "зал", "стол", "пол", "сигнал"}
_MASC_ADJ = r"(рад|готов|уверен|благодарен|знаком|заинтересован|свободен)"


def feminize(text: str) -> str:
    """Страховка к промпту: письмо пишет женщина. Правит типичные мужские формы о себе:
    «я посмотрел» → «я посмотрела», «буду рад» → «буду рада», «я готов» → «я готова»."""
    text = re.sub(r"\b([Яя])(\s+(?:внимательно|уже|тоже|также|недавно|специально|с интересом|давно)?\s*)(\w+л)(?=[\s,.!?:;]|$)",
                  lambda m: m.group(0) if m.group(3).lower() in _NOT_VERBS else f"{m.group(1)}{m.group(2)}{m.group(3)}а", text)
    text = re.sub(rf"\b([Яя]|[Бб]уду|[Бб]ыла бы|[Бб]ыл бы)(\s+(?:очень\s+|искренне\s+)?){_MASC_ADJ}(?=[\s,.!?:;]|$)",
                  lambda m: f"{m.group(1).replace('ыл бы', 'ыла бы')}{m.group(2)}{m.group(3)}а", text)
    return text


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


async def _contact_status(client: TelegramClient, username: str) -> tuple[Optional[types.User], str]:
    """(пользователь, статус): "ok" — живой человек, принимает сообщения от незнакомых;
    "closed" — пишут только контакты/Premium или сообщения платные; "not_person" —
    канал, группа, бот или не найден."""
    try:
        entity = await flood_safe(lambda: client.get_entity(username))
    except (ValueError, errors.RPCError):
        return None, "not_person"
    if not isinstance(entity, types.User) or entity.bot or entity.deleted:
        return None, "not_person"
    if entity.contact_require_premium or entity.send_paid_messages_stars:
        return entity, "closed"
    try:
        reqs = await flood_safe(lambda: client(functions.users.GetRequirementsToContactRequest(
            id=[types.InputUser(user_id=entity.id, access_hash=entity.access_hash)])))
    except errors.RPCError:
        return entity, "ok"  # проверка недоступна — остаются флаги выше
    if reqs and not isinstance(reqs[0], types.RequirementToContactEmpty):
        return entity, "closed"
    return entity, "ok"


async def _resolve_contact(client: TelegramClient, username: str) -> Optional[types.User]:
    """Контакт, которому реально можно написать: многие ставят «писать могут только
    контакты и Premium» или платные сообщения — такому владельцу не написать."""
    entity, status = await _contact_status(client, username)
    return entity if status == "ok" else None


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
    message = feminize((verdict or {}).get("message", "").strip())
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


def report_lead(n: int, lead: dict, sent: Optional[bool]) -> bool:
    status = {True: "✅ отправлено автоматически", False: "⚠️ автоотправка не удалась — отправьте вручную",
              None: "✉️ отправьте вручную (текст — следующим сообщением)"}[sent]
    ok = notify(
        f"🎯 Клиент #{n}: {lead['title']}\n"
        f"Канал: {lead.get('link') or 'https://t.me/' + lead['key'][1:]} — {lead['subscribers']} подписчиков\n"
        f"Ниша: {lead['niche']}\n"
        f"Активность: последний пост {lead['days_since']} дн. назад, {lead['posts_30d']} постов за 30 дней\n"
        f"Почему подходит: {lead['reason']}\n"
        + (f"Написать: https://t.me/{lead['contact']}\n" if lead.get("contact") else "")
        + (f"⚠️ {lead['contact_note']}\n" if lead.get("contact_note") else "")
        + status
    )
    if ok and sent is not True:
        ok = notify(lead["message"])
    return ok


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

            delivered = report_lead(len(leads) + 1, lead, sent)
            if not delivered and not sent:
                # Не помечаем канал: иначе клиент потеряется — найдём его снова в следующий раз.
                raise StopRun("Telegram не доставляет отчёты владелице — проверьте BOT_TOKEN/OWNER_ID и что боту нажат /start")
            mark_channel(mem, lead["key"], "sent" if sent else "lead")
            mem["contacts"][fingerprint(lead["contact"])] = {"date": date.today().isoformat()}
            leads.append(lead)
            print(f"  → клиент #{len(leads)} найден, отправлен вам в Telegram")
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


# ---------------------------------------------------------------- ручной список каналов

def channels_from_dispatch() -> list[str]:
    """Каналы, которые владелица вписала при ручном запуске (поле «Каналы» в Actions).
    Берём из файла события, а не из env: env печатается в публичном журнале."""
    path = os.getenv("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return []
    try:
        raw = (json.loads(Path(path).read_text(encoding="utf-8")).get("inputs") or {}).get("channels") or ""
    except (ValueError, OSError):
        return []
    return parse_channel_list(raw)


def parse_channel_list(raw: str) -> list[str]:
    """@name, t.me/name, https://t.me/name/123 или просто name — через пробел, запятую
    или с новой строки. Приватные приглашения t.me/+ХЕШ и t.me/joinchat/ХЕШ
    возвращаются как "+ХЕШ" — в такие каналы агент вступает."""
    out: list[str] = []
    for token in re.split(r"[\s,;]+", raw):
        inv = re.match(r"^(?:https?://)?(?:t|telegram)\.me/(?:\+|joinchat/)([A-Za-z0-9_-]{8,})", token.strip())
        if inv:
            if f"+{inv.group(1)}" not in out:
                out.append(f"+{inv.group(1)}")
            continue
        m = re.match(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z][A-Za-z0-9_]{3,31})|^@?([A-Za-z][A-Za-z0-9_]{3,31})$", token.strip())
        if not m:
            continue
        name = (m.group(1) or m.group(2)).lower()
        if name not in _NOT_USERNAMES and name not in out:
            out.append(name)
    return out[:MANUAL_MAX_CHANNELS]


async def _join_by_invite(client: TelegramClient, invite_hash: str) -> tuple[Optional[types.Channel], str]:
    """Вступает в приватный канал по приглашению (если уже участник — просто открывает)."""
    try:
        info = await flood_safe(lambda: client(functions.messages.CheckChatInviteRequest(hash=invite_hash)))
    except (errors.InviteHashExpiredError, errors.InviteHashInvalidError):
        return None, "приглашение недействительно или истекло"
    except errors.RPCError as e:
        return None, f"приглашение не открылось ({e.__class__.__name__})"
    if isinstance(info, types.ChatInviteAlready):
        return info.chat, ""
    if isinstance(info, types.ChatInvite) and info.request_needed:
        # Всё равно подаём заявку: вдруг админ примет — но прочитать канал сейчас нельзя.
        try:
            await flood_safe(lambda: client(functions.messages.ImportChatInviteRequest(hash=invite_hash)))
        except errors.InviteRequestSentError:
            pass
        except errors.RPCError:
            pass
        return None, f"«{info.title}» — вступление по заявке, заявку подала; когда примут, пришлите ссылку ещё раз"
    try:
        upd = await flood_safe(lambda: client(functions.messages.ImportChatInviteRequest(hash=invite_hash)))
    except errors.UserAlreadyParticipantError:
        return None, "уже участник, но канал не открылся — пришлите публичную ссылку"
    except errors.ChannelsTooMuchError:
        raise StopRun("достигнут лимит Telegram на количество каналов/групп у аккаунта")
    except errors.InviteRequestSentError:
        return None, "вступление по заявке — заявку подала; когда примут, пришлите ссылку ещё раз"
    except errors.RPCError as e:
        return None, f"не удалось вступить ({e.__class__.__name__})"
    chats = [c for c in getattr(upd, "chats", []) if isinstance(c, types.Channel)]
    await asyncio.sleep(random.uniform(MIN_JOIN_DELAY, MAX_JOIN_DELAY))
    return (chats[0], "") if chats else (None, "вступила, но канал не открылся")


async def write_for_channel(client: TelegramClient, name: str, mem: dict) -> tuple[Optional[dict], str]:
    """Письмо для канала из ручного списка. Фильтры частоты/размера не применяем —
    канал выбрала владелица; отсекаем только запрещённые ниши. (лид, пояснение)."""
    if name.startswith("+"):
        chat, why = await _join_by_invite(client, name[1:])
        if not chat:
            return None, why
    else:
        try:
            chat = await flood_safe(lambda: client.get_entity(name))
        except (ValueError, errors.RPCError):
            return None, "не нашёлся (проверьте ссылку)"
    if not isinstance(chat, types.Channel):
        return None, "это не канал и не группа"

    full = await flood_safe(lambda: client(functions.channels.GetFullChannelRequest(chat)))
    about = full.full_chat.about or ""
    if w := find_stop_word(f"{chat.title} {about}"):
        return None, f"запрещённая ниша («{w}»)"

    msgs = await flood_safe(lambda: client.get_messages(chat, limit=30))
    days_since, posts_30d = activity([m.date for m in msgs if m.date], datetime.now(timezone.utc))
    posts = [m.message for m in msgs if m.message][:4]

    # Контакт: первый, кому можно написать; иначе — подсказка, как достучаться.
    contact_name, contact_note = "", "в описании канала нет @контакта — ищите его в закрепе или пишите в комментарии"
    closed = []
    for c in extract_contacts(about, chat.username or "")[:3]:
        entity, status = await _contact_status(client, c)
        if status == "ok":
            contact_name, contact_note = entity.username or c, ""
            break
        if status == "closed":
            closed.append(entity.username or c)
    if not contact_name and closed:
        contact_name = closed[0]
        contact_note = ("пишут только контакты и Premium — отправьте письмо в комментарии "
                        "под постом или через другие контакты из описания")

    verdict = gemini.evaluate_channel_lead(chat.title, about, posts, OFFER_LINK)
    await asyncio.sleep(8)  # минутный лимит бесплатного Gemini
    if verdict is not None and not verdict.get("fit"):
        return None, f"Gemini: не подходит — {verdict.get('reason', '')}"
    message = feminize((verdict or {}).get("message", "").strip())
    if OFFER_LINK not in message:
        message = template_message(chat.title) if not message else f"{message}\nПодробнее и цены: {OFFER_LINK}"

    key = f"@{chat.username.lower()}" if chat.username else f"#{chat.id}"
    link = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/{name}"
    mark_channel(mem, key, "lead")
    if contact_name:
        mem["contacts"][fingerprint(contact_name)] = {"date": date.today().isoformat()}
    return {
        "key": key,
        "link": link,
        "title": chat.title,
        "subscribers": chat.participants_count or 0,
        "days_since": days_since if days_since is not None else "—",
        "posts_30d": posts_30d,
        "niche": (verdict or {}).get("niche", "—"),
        "reason": (verdict or {}).get("reason", "выбран вами"),
        "contact": contact_name,
        "contact_note": contact_note,
        "message": message,
    }, ""


async def run_manual(names: list[str]) -> None:
    mem = load_memory()
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    done, skipped = 0, []
    stop_reason = None
    try:
        for i, name in enumerate(names, 1):
            print(f"Пишу письмо для канала {i}/{len(names)}...")
            try:
                lead, why = await write_for_channel(client, name, mem)
            except StopRun:
                raise
            except Exception as e:
                lead, why = None, f"ошибка ({e.__class__.__name__})"
            if not lead:
                skipped.append(f"t.me/{name}: {why}")
                continue
            done += 1
            if not report_lead(done, lead, None):
                raise StopRun("Telegram не доставляет отчёты владелице — проверьте BOT_TOKEN/OWNER_ID")
            await asyncio.sleep(random.uniform(2, 4))
    except StopRun as e:
        stop_reason = str(e)
        print(f"СТОП: {stop_reason}")
    finally:
        await client.disconnect()
        save_memory(mem)

    summary = f"Письма по вашему списку: готово {done} из {len(names)}."
    if skipped:
        summary += "\nПропущены:\n" + "\n".join(f"• {s}" for s in skipped)
    if stop_reason:
        summary += f"\n⚠️ Остановлено: {stop_reason}"
    notify(summary)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    manual = channels_from_dispatch()
    asyncio.run(run_manual(manual) if manual else run())

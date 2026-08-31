# -*- coding: utf-8 -*-
"""
Промо-агент (облачная версия — GitHub Actions). Раз в день ищет тематический
ПУБЛИЧНЫЙ ЧАТ (супергруппу, не канал — в канал обычный участник писать не может)
под ОДИН из шести каналов, по кругу (спорт -> образование -> ИИ -> семья/ислам ->
арабский -> английский -> снова спорт...):
  sport     -> «Мусульманка на спорте» (t.me/ilikeislamandsport)
  education -> «Тамра» (t.me/tamra_school)
  ai        -> «Halal AI | Freya» (t.me/Halalaifreya)
  family    -> «Тамра» (t.me/tamra_school)
  arabic    -> «My Arabic» (t.me/myarabicl)
  english   -> «I Speak English» (t.me/i_speak_en)

Проверяет через Gemini, разрешён ли в найденном чате самопиар (по описанию и
закреплённому сообщению) — и публикует пост СРАЗУ, если Gemini дал вердикт
"allowed" ЛИБО "conditional" с безобидным условием, которое автопост в силах
соблюсти (определённый день/время/топик/формат). "conditional" с оплатой или
«только по согласованию с админом», а также "unclear"/"not_allowed" —
пропускаются (см. _promo_allowed). Владелец получает уведомление в Telegram
о результате в любом случае — что опубликовано или почему не опубликовано.

ВАЖНО: раньше (локальная версия, tg-channel-agent) каждый пост требовал подтверждения
владельцем перед отправкой. При переносе в GitHub Actions это отключено сознательно —
раннер работает разово по расписанию и не может слушать нажатия кнопок в Telegram
(некому). Владелец решил публиковать полностью автоматически, приняв более высокий
риск бана/спам-репорта в обмен на независимость от включённого компьютера.

Сессия аккаунта — НЕ файл (раннер одноразовый), а строка в секрете TELETHON_SESSION
(Telethon StringSession). Работает от имени личного Telegram-аккаунта.
"""
import asyncio
import json
import os
import random
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from telethon import TelegramClient, errors, functions, types
from telethon.sessions import StringSession

import gemini

BASE = Path(__file__).parent
POSTS_FILE = BASE / "promo_posts.json"
MEMORY_FILE = BASE / "promo_memory.json"
BANNERS_DIR = BASE / "banners"

POSTS: dict = json.loads(POSTS_FILE.read_text(encoding="utf-8"))

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["TELETHON_SESSION"]

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = os.getenv("OWNER_ID", "")

THEME_ORDER = ["sport", "education", "ai", "family", "arabic", "english"]
THEME_LABELS = {
    "sport": "спорт (Мусульманка на спорте)",
    "education": "образование (Тамра)",
    "ai": "ИИ / автоматизация (Halal AI | Freya)",
    "family": "семья / ислам (Тамра)",
    "arabic": "арабский язык (My Arabic)",
    "english": "английский язык (I Speak English)",
}

THEME_KEYWORDS = {
    "sport": [
        "фитнес для мусульманок", "спорт для сестёр", "пилатес для женщин",
        "тренировки дома для женщин", "аэробика для начинающих",
        "женский фитнес чат", "домашние тренировки", "похудение чат",
        "марафон стройности", "зож для женщин", "фитнес мама",
        "мусульманки чат", "сёстры по вере чат", "женский клуб ислам",
        "правильное питание чат", "фитнес без спортзала",
    ],
    "education": ["образование детей", "репетитор", "подготовка к ЕНТ", "подготовка к ЕГЭ", "развитие ребенка"],
    "ai": ["автоматизация бизнеса", "предприниматели чат", "малый бизнес автоматизация", "нейросети для бизнеса", "IT для предпринимателей"],
    "family": ["мусульманская семья", "воспитание детей ислам", "мусульманские мамы", "ислам для детей", "хадисы"],
    "arabic": ["арабский язык с нуля", "изучение арабского", "арабский для начинающих", "курсы арабского языка", "арабский язык онлайн"],
    "english": ["английский язык с нуля", "английский для начинающих", "разговорный английский", "курсы английского", "английский онлайн"],
}

# Дополнительный пул: чаты, где самопиар/взаимный пиар — сама их суть (выше шанс, что реально можно)
GENERIC_SELF_PROMO_KEYWORDS = [
    "чат для рекламы каналов", "взаимный пиар telegram", "биржа рекламы telegram", "самопиар чат",
    "взаимопиар каналов", "пиар чат телеграм", "реклама каналов бесплатно",
    "чат взаимного пиара", "продвижение телеграм канала чат", "флуд чат пиар",
    "раскрутка канала чат", "пиар админов",
]

MIN_MEMBERS = int(os.getenv("PROMO_MIN_MEMBERS", "300"))
POSTED_COOLDOWN_DAYS = int(os.getenv("PROMO_POSTED_COOLDOWN_DAYS", "35"))
SKIPPED_COOLDOWN_DAYS = int(os.getenv("PROMO_SKIPPED_COOLDOWN_DAYS", "14"))
# Сколько чатов-кандидатов проверяем через Gemini за прогон (проверка — только
# чтение описания/закрепа, без вступления, поэтому для Telegram безопасно).
MAX_CANDIDATES_TO_CHECK = int(os.getenv("PROMO_MAX_CANDIDATES_TO_CHECK", "12"))
# Жёсткий предел ВСТУПЛЕНИЙ в группы за один прогон — главный антибан-рычаг.
# Вступаем только в тот чат, где Gemini уже сказал «можно», прямо перед постом.
MAX_JOINS_PER_RUN = int(os.getenv("PROMO_MAX_JOINS_PER_RUN", "3"))
# Паузы между действиями (сек). Разнесены пошире, чтобы поведение было менее «ботовым».
MIN_DELAY = int(os.getenv("PROMO_MIN_DELAY", "12"))
MAX_DELAY = int(os.getenv("PROMO_MAX_DELAY", "30"))


class StopRun(Exception):
    """Прерываем весь прогон (крупный флуд-бан и т.п.)."""


async def flood_safe(coro_factory):
    try:
        return await coro_factory()
    except errors.FloodWaitError as e:
        if e.seconds <= 300:
            print(f"  FloodWait {e.seconds}с — жду и повторяю...")
            await asyncio.sleep(e.seconds + 5)
            return await coro_factory()
        raise StopRun(f"FloodWait {e.seconds}с — Telegram просит остановиться, прекращаю прогон")


def notify(text: str) -> None:
    print(text)
    if not BOT_TOKEN or not OWNER_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_ID, "text": text},
            timeout=20,
        )
    except Exception as e:
        print(f"  ! не удалось отправить уведомление: {e}")


def notify_photo(path: str, caption: str) -> None:
    if not BOT_TOKEN or not OWNER_ID:
        return
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": OWNER_ID, "caption": caption},
                files={"photo": f},
                timeout=60,
            )
    except Exception as e:
        print(f"  ! не удалось отправить фото-уведомление: {e}")


# ---------------------------------------------------------------- память

SPORT_MEMORY_FILE = BASE / "promo_memory_sport.json"


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        mem = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    else:
        mem = {"posted": {}, "skipped": {}, "daily": {}}

    # Подмешиваем posted/skipped из отдельной доп. рассылки спорт-канала
    # (promo_sport.py, 5x/неделю) — чтобы в свой день по ротации не постить
    # повторно в тот же чат, который та рассылка уже использовала недавно.
    if SPORT_MEMORY_FILE.exists():
        sport_mem = json.loads(SPORT_MEMORY_FILE.read_text(encoding="utf-8"))
        for key, v in sport_mem.get("posted", {}).items():
            mem["posted"].setdefault(key, v)
        for key, v in sport_mem.get("skipped", {}).items():
            mem["skipped"].setdefault(key, v)

    return mem


def save_memory(mem: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def _days_since(iso_date: str) -> int:
    try:
        return (date.today() - date.fromisoformat(iso_date)).days
    except ValueError:
        return 10 ** 6


def mark_posted(mem: dict, key: str, theme: str) -> None:
    today = date.today().isoformat()
    mem["posted"][key] = {"date": today, "theme": theme}
    mem["daily"][today] = {"theme": theme, "chat": key, "posted": True}


def mark_skipped(mem: dict, key: str, reason: str) -> None:
    mem["skipped"][key] = {"date": date.today().isoformat(), "reason": reason}


def already_done_today(mem: dict) -> Optional[dict]:
    return mem["daily"].get(date.today().isoformat())


def theme_for_today() -> str:
    return THEME_ORDER[date.today().toordinal() % len(THEME_ORDER)]


def banner_path(theme: str) -> Optional[str]:
    p = BANNERS_DIR / f"{theme}.png"
    return str(p) if p.exists() else None


# ---------------------------------------------------------------- поиск и проверка кандидата

async def _search_theme(client: TelegramClient, theme: str) -> list:
    """Глобальный поиск Telegram по ключевым словам темы. Возвращает список types.Channel
    (публичные супергруппы — только туда обычный участник может писать)."""
    found: dict[str, types.Channel] = {}
    keywords = THEME_KEYWORDS[theme] + GENERIC_SELF_PROMO_KEYWORDS
    # Перемешиваем, чтобы разные прогоны находили разные чаты, а не всегда
    # первые по одним и тем же словам — так пул кандидатов со временем шире.
    random.shuffle(keywords)
    for kw in keywords:
        try:
            res = await flood_safe(lambda: client(functions.contacts.SearchRequest(q=kw, limit=20)))
        except Exception as e:
            print(f"  ! поиск по «{kw}» не удался: {e}")
            continue
        for chat in res.chats:
            if not isinstance(chat, types.Channel) or not chat.megagroup or not chat.username:
                continue
            key = f"@{chat.username.lower()}"
            found.setdefault(key, chat)
        if len(found) >= MAX_CANDIDATES_TO_CHECK * 3:
            break
    return list(found.items())


def _filter_candidates(candidates: list, mem: dict) -> list:
    out = []
    for key, chat in candidates:
        if key in mem["posted"] and _days_since(mem["posted"][key]["date"]) < POSTED_COOLDOWN_DAYS:
            continue
        if key in mem["skipped"] and _days_since(mem["skipped"][key]["date"]) < SKIPPED_COOLDOWN_DAYS:
            continue
        banned = chat.default_banned_rights
        if banned is not None and banned.send_messages:
            continue
        if (chat.participants_count or 0) < MIN_MEMBERS:
            continue
        out.append((key, chat))
    return out


async def _join_group(client: TelegramClient, chat: types.Channel):
    try:
        await flood_safe(lambda: client(functions.channels.JoinChannelRequest(chat)))
        return True, ""
    except errors.UserAlreadyParticipantError:
        return True, "уже участник"
    except errors.ChannelsTooMuchError:
        raise StopRun("достигнут лимит Telegram на количество каналов/групп у аккаунта")
    except errors.ChannelPrivateError:
        return False, "группа закрыта для вступления"
    except errors.RPCError as e:
        return False, f"ошибка вступления: {e.__class__.__name__}"


async def _fetch_rules_context(client: TelegramClient, chat: types.Channel) -> tuple[str, str]:
    about = ""
    pinned_text = ""
    try:
        full = await flood_safe(lambda: client(functions.channels.GetFullChannelRequest(chat)))
        about = full.full_chat.about or ""
        pinned_id = full.full_chat.pinned_msg_id
        if pinned_id:
            msgs = await client.get_messages(chat, ids=pinned_id)
            if msgs is not None:
                pinned_text = getattr(msgs, "message", "") or ""
    except Exception as e:
        print(f"  ! не удалось прочитать описание/закреп: {e}")
    return about, pinned_text


# Слова-маркеры «условие небезобидное» — платно или только через личное согласование.
# Подстраховка на случай, если Gemini неверно проставит condition_type.
_UNSAFE_CONDITION_MARKERS = (
    "оплат", "платн", "прайс", "стоимост", "цена", "руб", "₽", "$", "донат",
    "купить", "заказать реклам", "реклама через бот", "по договорённост", "по договоренност",
    "согласова", "разрешение админ", "напишите админ", "напиши админ", "обратитесь к админ",
    "только для участников", "закрыт", "подписк", "vip", "премиум",
)


def _promo_allowed(verdict: dict) -> tuple[bool, str]:
    """Можно ли постить в чат по вердикту Gemini.
    Разрешаем: verdict == "allowed", ИЛИ "conditional" с безобидным условием
    (день/время/топик/формат), которое автопост в силах соблюсти. Платное
    размещение и «только по согласованию с админом» — не пропускаем."""
    v = verdict.get("verdict")
    if v == "allowed":
        return True, "allowed"
    if v == "conditional":
        ctype = verdict.get("condition_type", "other")
        cond_text = (verdict.get("condition") or "").lower()
        if any(m in cond_text for m in _UNSAFE_CONDITION_MARKERS):
            return False, "conditional (условие: оплата/согласование)"
        if ctype == "benign":
            return True, "conditional-benign"
        return False, f"conditional ({ctype})"
    return False, v or "unclear"


async def find_and_post(client: TelegramClient, theme: str, mem: dict) -> Optional[dict]:
    """Ищет кандидата и, при чётком разрешении Gemini, публикует пост СРАЗУ (без
    подтверждения человеком — см. docstring модуля). Возвращает результат или None."""
    raw = await _search_theme(client, theme)
    candidates = _filter_candidates(raw, mem)
    print(f"Тема: {THEME_LABELS[theme]}. Найдено кандидатов: {len(raw)}, после фильтра: {len(candidates)}.")

    checked = 0
    joins_used = 0
    for key, chat in candidates:
        if checked >= MAX_CANDIDATES_TO_CHECK:
            break
        checked += 1
        print(f"[{checked}/{min(len(candidates), MAX_CANDIDATES_TO_CHECK)}] Проверяю {key} ({chat.title})...")

        # 1) Читаем описание/закреп БЕЗ вступления (для публичных супергрупп это
        #    доступно). Вступление — самый рискованный по бану шаг, поэтому его
        #    делаем только когда уже знаем, что постить сюда можно.
        about, pinned = await _fetch_rules_context(client, chat)
        verdict = gemini.check_promo_allowed(chat.title, about, pinned)
        ok_to_post, why = _promo_allowed(verdict)
        if not ok_to_post:
            mark_skipped(mem, key, f"Gemini: {why} — {verdict.get('reason', '')}")
            continue

        # 2) Только теперь вступаем — прямо перед публикацией, с жёстким лимитом
        #    вступлений за один прогон (главный антибан-рычаг).
        if joins_used >= MAX_JOINS_PER_RUN:
            print(f"  лимит вступлений за прогон ({MAX_JOINS_PER_RUN}) исчерпан — останавливаюсь")
            break
        ok, note = await _join_group(client, chat)
        joins_used += 1
        if not ok:
            mark_skipped(mem, key, note)
            continue
        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        post_text = POSTS[theme]
        banner = banner_path(theme)
        target = types.InputPeerChannel(channel_id=chat.id, access_hash=chat.access_hash)
        try:
            if banner:
                await flood_safe(lambda: client.send_file(target, banner, caption=post_text))
            else:
                await flood_safe(lambda: client.send_message(target, post_text))
        except errors.RPCError as e:
            mark_skipped(mem, key, f"ошибка отправки: {e.__class__.__name__}")
            continue

        mark_posted(mem, key, theme)
        return {"key": key, "title": chat.title, "members": chat.participants_count or 0, "verdict": verdict}

    return None


async def run() -> None:
    mem = load_memory()
    done = already_done_today(mem)
    if done:
        notify(f"На сегодня уже обработано: тема «{THEME_LABELS.get(done['theme'], done['theme'])}».")
        return

    theme = theme_for_today()
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    result = None
    stop_reason = None
    try:
        result = await find_and_post(client, theme, mem)
    except StopRun as e:
        stop_reason = str(e)
        print(f"СТОП: {stop_reason}")
    finally:
        await client.disconnect()

    save_memory(mem)

    if stop_reason:
        notify(f"⚠️ СТОП: {stop_reason}\nТема дня «{THEME_LABELS[theme]}» осталась без поста сегодня.")
    elif result:
        v = result["verdict"]
        cond = f" [условие: {v.get('condition')}]" if v.get("verdict") == "conditional" else ""
        text = (
            f"✅ Опубликовано. Тема дня: {THEME_LABELS[theme]}\n"
            f"Чат: {result['title']} ({result['key']}), участников: {result['members']}\n"
            f"Оценка Gemini: {v.get('verdict')}{cond} — {v.get('reason', '')}"
        )
        notify(text)
    else:
        notify(
            f"За сегодня не нашлось подходящего чата для темы «{THEME_LABELS[theme]}» "
            f"(либо реклама явно не разрешена, либо обычным участникам нельзя писать, "
            f"либо чат уже использован недавно). Публикации не было."
        )


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(run())

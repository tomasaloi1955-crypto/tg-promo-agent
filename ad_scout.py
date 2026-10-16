# -*- coding: utf-8 -*-
"""
Разведчик рекламных площадок для школы «Мусульманка на спорте».

Раз в день ищет публичные Telegram-КАНАЛЫ для женщин — мусульманские и про
спорт/здоровье/фигуру — и присылает владелице в бот 2–3 карточки:
название и ссылка, подписчики, средние просмотры (видно, живая ли аудитория),
о чём канал, @контакт админа из описания, ссылка на статистику в Telemetr,
своя рекламная ссылка на бот воронки с меткой канала и готовый текст первого
сообщения админу (о рекламе или взаимопиаре).

Сам агент админам НЕ пишет: сообщения незнакомым людям с личного аккаунта —
главная причина спам-блока (24.09.2026 этот аккаунт уже ограничивали), а этот
же аккаунт ведёт промо-агента. Договаривается владелица.

Почему не Telemetr напрямую: у Telemetr нет бесплатного API, а страницы закрыты
от роботов. Каналы ищутся глобальным поиском самого Telegram — это те же
каналы, что в каталоге Telemetr; ссылка на их страницу в Telemetr есть в карточке.

Репозиторий публичный: в журнал Actions не пишутся ни каналы, ни контакты, а в
памяти (ad_scout_memory.json) хранятся только отпечатки @username (как в outreach.py).
"""
import asyncio
import json
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession

import gemini
from outreach import USERNAME_RE, activity, extract_contacts, find_stop_word, fingerprint, notify
from promo import API_HASH, API_ID, SESSION_STRING, StopRun, flood_safe  # noqa: F401  (API_HASH — для fingerprint)

BASE = Path(__file__).parent
MEMORY_FILE = BASE / "ad_scout_memory.json"

CARDS_PER_DAY = 3
MAX_CHANNELS_TO_CHECK = 40
MAX_GEMINI_CALLS = 15
MIN_SUBSCRIBERS = 1000
MAX_SUBSCRIBERS = 150_000
MAX_DAYS_SINCE_LAST_POST = 14
# Средние просмотры поста к подписчикам: ниже — подписчики, скорее всего, накручены
# или канал мёртвый, реклама там не окупится.
MIN_VIEW_RATE = 0.05

SEARCH_KEYWORDS = [
    # мусульманки, сёстры, мамы
    "мусульманка", "для сестер", "сестры в исламе", "мусульманская женщина",
    "хиджаб", "мусульманские мамы", "мама мусульманка", "никах", "жена мусульманка",
    "ислам для женщин", "халяль рецепты", "скромная одежда", "абайя",
    # спорт, здоровье, фигура для женщин
    "фитнес для женщин", "пилатес", "тренировки дома", "похудение", "стройность",
    "фитнес мама", "здоровье женщины", "женское здоровье", "правильное питание",
    "после родов", "осанка", "растяжка",
]

AUDIENCE = (
    "женщины, которым может быть интересна онлайн-школа домашних тренировок "
    "«Мусульманка на спорте»: русскоязычные мусульманки (сёстры), мусульманские мамы, "
    "а также женщины, которые следят за здоровьем, фигурой, питанием, занимаются "
    "или хотят заниматься фитнесом/пилатесом. Канал должен быть ДЛЯ ЖЕНЩИН или явно "
    "мусульманский семейный с женской аудиторией"
)

OUR_CHANNEL = "https://t.me/ilikeislamandsport"
BOT_AD_LINK = "https://t.me/pilatesmuslim_bot?start=ad_{name}"


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    return {"channels": {}}


def save_memory(mem: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def mark(mem: dict, key: str, status: str) -> None:
    mem["channels"][fingerprint(key)] = {"date": date.today().isoformat(), "status": status}


async def search(client: TelegramClient, mem: dict) -> list[types.Channel]:
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
            if key in found or fingerprint(key) in mem["channels"]:
                continue
            if not MIN_SUBSCRIBERS <= (chat.participants_count or 0) <= MAX_SUBSCRIBERS:
                continue
            found[key] = chat
        if len(found) >= MAX_CHANNELS_TO_CHECK:
            break
        await asyncio.sleep(random.uniform(2, 5))
    return list(found.values())


def first_message(title: str) -> str:
    return (
        "Ассаляму алейкум! Я веду канал «Мусульманка на спорте» — домашние тренировки "
        f"для сестёр ({OUR_CHANNEL}). Смотрю ваш канал «{title}», аудитория очень близкая. "
        "Подскажите, пожалуйста, есть ли у вас реклама или взаимопиар? Если удобно — "
        "можем обменяться постами."
    )


async def check(client: TelegramClient, chat: types.Channel, mem: dict, budget: list) -> dict | None:
    key = f"@{chat.username.lower()}"
    if find_stop_word(chat.title):
        mark(mem, key, "rejected")
        return None

    full = await flood_safe(lambda: client(functions.channels.GetFullChannelRequest(chat)))
    about = full.full_chat.about or ""
    if find_stop_word(about):
        mark(mem, key, "rejected")
        return None

    contacts = extract_contacts(about, chat.username)
    if not contacts:
        # Многие каналы принимают рекламу через бота обратной связи (@..._bot) —
        # extract_contacts ботов отбрасывает, здесь берём их запасным контактом.
        contacts = [
            m.group(1) for m in USERNAME_RE.finditer(about)
            if m.group(1).lower().endswith("bot") and m.group(1).lower() != chat.username.lower()
        ]
    if not contacts:
        # Без контакта договориться не с кем — в карточку не берём.
        mark(mem, key, "no_contact")
        return None

    msgs = await flood_safe(lambda: client.get_messages(chat, limit=20))
    days_since, posts_30d = activity([m.date for m in msgs if m.date], datetime.now(timezone.utc))
    if days_since is None or days_since > MAX_DAYS_SINCE_LAST_POST:
        mark(mem, key, "inactive")
        return None
    views = [m.views for m in msgs if m.views]
    avg_views = int(sum(views) / len(views)) if views else 0
    subs = chat.participants_count or 0
    if subs and avg_views / subs < MIN_VIEW_RATE:
        mark(mem, key, "low_views")
        return None

    if budget[0] <= 0:
        return None  # не помечаем — проверим в другой день
    budget[0] -= 1
    posts = "\n---\n".join((m.message or "")[:300] for m in msgs[:5] if m.message)
    fit = gemini.check_audience_fit(chat.title, about, posts, AUDIENCE)
    await asyncio.sleep(8)  # минутный лимит бесплатного Gemini
    if not fit["fit"]:
        mark(mem, key, "not_fit")
        return None

    mark(mem, key, "sent")
    return {
        "username": chat.username,
        "title": chat.title,
        "subs": subs,
        "avg_views": avg_views,
        "posts_30d": posts_30d,
        "about": about.strip(),
        "why": fit["reason"],
        "contacts": contacts[:2],
    }


def _num(x: int) -> str:
    return f"{x:,}".replace(",", " ")


def card(n: int, c: dict) -> str:
    rate = f"{c['avg_views'] / c['subs']:.0%}" if c["subs"] else "—"
    about = c["about"][:300] + ("…" if len(c["about"]) > 300 else "")
    admins = ", ".join(
        f"@{a}" + (" (бот для связи)" if a.lower().endswith("bot") else "") for a in c["contacts"]
    )
    return (
        f"📢 Площадка {n}: {c['title']}\n"
        f"https://t.me/{c['username']}\n"
        f"👥 {_num(c['subs'])} подписчиков · 👁 ~{_num(c['avg_views'])} просмотров на пост ({rate}) · "
        f"{c['posts_30d']} постов за месяц\n"
        f"О чём: {about or '—'}\n"
        f"Почему подходит: {c['why']}\n"
        f"✉️ Админ: {admins}\n"
        f"📊 Статистика: https://telemetr.me/content/{c['username']}\n"
        f"🔗 Ваша ссылка для рекламы здесь: {BOT_AD_LINK.format(name=c['username'].lower())}"
    )


async def run() -> None:
    mem = load_memory()
    if mem.get("last_run") == date.today().isoformat():
        print("Сегодня уже отправляли подборку.")
        return

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    cards: list[dict] = []
    stop = None
    try:
        candidates = await search(client, mem)
        print(f"Кандидатов после поиска: {len(candidates)}")
        budget = [MAX_GEMINI_CALLS]
        for chat in candidates:
            if len(cards) >= CARDS_PER_DAY:
                break
            try:
                c = await check(client, chat, mem, budget)
            except StopRun:
                raise
            except Exception as e:
                print(f"  ! канал не проверен: {e.__class__.__name__}")
                continue
            if c:
                cards.append(c)
            await asyncio.sleep(random.uniform(3, 8))
    except StopRun as e:
        stop = str(e)
    finally:
        await client.disconnect()

    mem["last_run"] = date.today().isoformat()
    save_memory(mem)
    print(f"Карточек: {len(cards)}")

    if stop:
        notify(f"⚠️ Разведчик площадок остановился: {stop}")
    if not cards:
        if not stop:
            notify("📢 Разведчик площадок: сегодня новых подходящих каналов не нашлось. Завтра поищу ещё.")
        return
    notify(
        f"📢 Площадки для рекламы «Мусульманка на спорте» на сегодня: {len(cards)}.\n"
        "Под каждой — готовое сообщение админу. Ссылка «для рекламы здесь» ведёт в ваш бот: "
        "лиды с неё придут с источником = имя канала."
    )
    for n, c in enumerate(cards, 1):
        notify(card(n, c))
        notify(first_message(c["title"]))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(run())

# -*- coding: utf-8 -*-
"""
Разовое приглашение подписчиц канала «Домашние тренировки» в бесплатную неделю.

Три раза в неделю (.github/workflows/invite.yml) пишет в личку следующим INVITE_PER_RUN
подписчицам (по умолчанию 10) короткое приглашение: «неделя бесплатных тренировок
в записи» + ссылка в бот воронки. Каждой — ОДИН раз за всё время, повторов нет.
Когда все подписчицы пройдены, присылает владелице «готово» и дальше ничего не
делает — workflow можно выключить.

Кого пропускаем:
  • боты, удалённые аккаунты, админы канала, сам аккаунт;
  • те, кто уже есть в базе бота воронки (нажимали /start): им бот сам может
    написать командой /reweek, а тех, кто в воронке, не беспокоим. Нужен секрет
    SISTER_DATABASE_URL (та же строка, что DATABASE_URL у sister-bot); без него
    или если база недоступна — не пишем никому.

Защита аккаунта (это основной аккаунт промо-агента, 24.09.2026 его ограничивали):
  • перед прогоном — вопрос @SpamBot; ограничен — ничего не шлём;
  • не больше INVITE_PER_RUN (потолок 20) за раз, 3 раза в неделю, паузы 3–8 минут;
  • при первом предупреждении Telegram (PeerFlood, долгий FloodWait) — стоп и
    пауза на 7 дней.

Аккаунт TELETHON_SESSION должен быть администратором канала: иначе Telegram не
отдаёт список подписчиков.

Репозиторий публичный: в памяти invite_memory.json — только зашифрованные
отпечатки id (ключ — API_HASH), в журнал Actions не пишутся ни имена, ни id.
"""
import asyncio
import json
import os
import random
from datetime import date, timedelta
from pathlib import Path

from telethon import TelegramClient, errors, types
from telethon.sessions import StringSession

from outreach import fingerprint, notify, spam_status
from promo import API_HASH, API_ID, SESSION_STRING

BASE = Path(__file__).parent
MEMORY_FILE = BASE / "invite_memory.json"

# Канал ищем по названию среди каналов, где аккаунт — администратор. Адрес
# (INVITE_CHANNEL: @name, t.me/name или -100…) — если названий-двойников несколько.
CHANNEL = (os.getenv("INVITE_CHANNEL") or "").strip()
CHANNEL_TITLE = os.getenv("INVITE_CHANNEL_TITLE") or "Домашние тренировки"
BOT_LINK = os.getenv("INVITE_BOT_LINK") or "https://t.me/pilatesmuslim_bot?start=src_dm_sport"
PER_RUN = min(int(os.getenv("INVITE_PER_RUN") or "10"), 20)
MIN_DELAY, MAX_DELAY = 180, 480   # 3–8 минут между сообщениями
PAUSE_DAYS = 7                 # после предупреждения Telegram о спаме — неделя тишины
SISTER_DB = os.getenv("SISTER_DATABASE_URL", "")

# Тон: спокойно, без давления и восклицаний про «скидки»; сразу сказать, почему
# пишем, и что второго сообщения не будет, — тогда реже жмут «Это спам».
# Два варианта, чтобы не слать всем одно и то же.
MESSAGES = [
    "Ассаляму алейкум{name} 🤍\n\n"
    "Пишу вам, потому что вы подписаны на наш канал «{channel}». "
    "Хотим сделать небольшой подарок: неделю бесплатных домашних тренировок в записи — "
    "3 спокойные тренировки, без зала и инвентаря, в удобное для вас время.\n\n"
    "Если интересно, начать можно здесь: {link}\n\n"
    "Если сейчас неактуально — просто не отвечайте, больше писать не буду. "
    "Пусть Аллах дарует вам здоровье и силы 🌿",

    "Ассаляму алейкум{name} 🌸\n\n"
    "Вы подписаны на наш канал «{channel}», и мне хотелось лично пригласить вас "
    "на неделю бесплатных тренировок в записи: 3 тренировки дома, через день, "
    "без зала — в своём темпе.\n\n"
    "Забрать можно по ссылке: {link}\n\n"
    "Это единственное сообщение — если не актуально, ничего делать не нужно. "
    "Хорошего вам дня 🤍",
]


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    return {"done": {}, "finished": None}


def save_memory(mem: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def message_for(user: types.User) -> str:
    name = (user.first_name or "").strip()
    # Имя только «человеческое»: без эмодзи-ников и длинных подписей вроде «Магазин платков».
    ok = name and len(name) <= 20 and name.replace("-", "").replace(" ", "").isalpha()
    return random.choice(MESSAGES).format(name=f", {name}" if ok else "", link=BOT_LINK, channel=CHANNEL_TITLE)


async def known_in_bot() -> set[int] | None:
    """id всех, кто есть в базе бота воронки. None — базу прочитать не удалось:
    тогда не пишем никому, чтобы не задеть тех, кто уже в воронке."""
    if not SISTER_DB:
        return None
    import asyncpg
    try:
        con = await asyncpg.connect(SISTER_DB, statement_cache_size=0, timeout=30)
        try:
            return {r["tg_id"] for r in await con.fetch("SELECT tg_id FROM users")}
        finally:
            await con.close()
    except Exception as e:
        print(f"  ! база бота воронки недоступна: {e.__class__.__name__}")
        return None


def _channel_ref(raw: str):
    """«@name», «t.me/name», «https://t.me/name» или числовой id (-100…)."""
    raw = raw.strip().rstrip("/")
    for prefix in ("https://", "http://", "t.me/", "telegram.me/", "@"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    raw = raw.removeprefix("t.me/")
    return int(raw) if raw.lstrip("-").isdigit() else raw


async def find_channel(client: TelegramClient) -> tuple[object, str]:
    """(канал, «») или (None, причина). По адресу, если задан; иначе — канал с
    этим названием среди тех, где аккаунт — администратор (ровно один)."""
    if CHANNEL:
        try:
            return await client.get_entity(_channel_ref(CHANNEL)), ""
        except (ValueError, errors.RPCError) as e:
            print(f"  канал по адресу не найден ({e.__class__.__name__})")
            return None, f"канал по адресу {CHANNEL} не найден"
    want = CHANNEL_TITLE.lower()
    found = []
    async for d in client.iter_dialogs():
        e = d.entity
        if isinstance(e, types.Channel) and e.broadcast and want in (e.title or "").lower() \
                and (e.creator or e.admin_rights):
            found.append(e)
    if len(found) == 1:
        return found[0], ""
    if not found:
        return None, (f"не нашла канал «{CHANNEL_TITLE}» среди каналов, где аккаунт — администратор. "
                      "Сделайте аккаунт администратором канала")
    return None, (f"каналов с названием «{CHANNEL_TITLE}» несколько ("
                  + ", ".join(f"«{c.title}»" for c in found[:5])
                  + "). Укажите адрес нужного в переменной INVITE_CHANNEL")


async def run() -> None:
    mem = load_memory()
    if mem.get("finished"):
        print("Все подписчицы уже приглашены — делать нечего")
        return
    if (mem.get("paused_until") or "") > date.today().isoformat():
        print("Пауза после предупреждения Telegram — сегодня не пишу")
        return
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    try:
        limit = await spam_status(client)
        if limit:
            notify("⛔ Приглашения в бесплатную неделю: Telegram сейчас ограничил аккаунт — "
                   "сегодня никому не пишу, попробую завтра.")
            print("Аккаунт ограничен — пропуск")
            return
        me = await client.get_me()
        channel, why = await find_channel(client)
        if channel is None:
            notify(f"⚠️ Приглашения: {why}. Никому не писала.")
            return
        admins = {u.id async for u in client.iter_participants(channel, filter=types.ChannelParticipantsAdmins)}
        try:
            members = [u async for u in client.iter_participants(channel)]
        except errors.ChatAdminRequiredError:
            notify(f"⚠️ Приглашения: аккаунт не администратор канала «{channel.title}» — Telegram не даёт "
                   "список подписчиц. Сделайте аккаунт админом канала.")
            return
        in_bot = await known_in_bot()
        if in_bot is None:
            notify("⚠️ Приглашения: не удалось проверить базу бота воронки (секрет SISTER_DATABASE_URL "
                   "не задан или база недоступна). Чтобы не написать тем, кто уже в воронке, "
                   "сегодня никому не пишу.")
            return
        todo, skipped_bot = [], 0
        for u in members:
            if u.bot or u.deleted or u.id == me.id or u.id in admins:
                continue
            fp = fingerprint(str(u.id))
            if fp in mem["done"]:
                continue
            if u.id in in_bot:
                mem["done"][fp] = "in_bot"
                skipped_bot += 1
                continue
            todo.append((fp, u))
        random.shuffle(todo)

        sent, failed, stop = 0, 0, ""
        for i, (fp, u) in enumerate(todo[:PER_RUN]):
            if i:
                await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            try:
                await client.send_message(u, message_for(u), link_preview=False)
                mem["done"][fp] = "sent"
                sent += 1
            except errors.PeerFloodError:
                stop = "Telegram предупредил о спаме (PeerFlood)"
                break
            except errors.FloodWaitError as e:
                stop = f"Telegram попросил подождать {e.seconds} с"
                break
            except errors.RPCError as e:          # закрыта личка, заблокировала и т.п. — больше не пробуем
                mem["done"][fp] = "skip"
                failed += 1
                print(f"  не доставлено: {e.__class__.__name__}")
            save_memory(mem)

        if stop:
            mem["paused_until"] = (date.today() + timedelta(days=PAUSE_DAYS)).isoformat()
        left = len(todo) - sent - failed
        if left <= 0 and not stop:
            mem["finished"] = date.today().isoformat()
        save_memory(mem)
        print(f"Отправлено {sent}, не доставлено {failed}, осталось {left}" + (f", стоп: {stop}" if stop else ""))
        report = (f"💌 Приглашения в бесплатную неделю («{channel.title}»): сегодня отправлено {sent}"
                  + (f", не доставлено {failed} (закрыта личка)" if failed else "")
                  + (f", уже были в боте {skipped_bot}" if skipped_bot else "")
                  + f". Осталось: {max(left, 0)}.")
        if stop:
            report += (f"\n⛔ Остановлено: {stop}. Беру паузу на {PAUSE_DAYS} дней, потом продолжу. "
                       "Если повторится — лучше выключить рассылку совсем.")
        elif mem["finished"]:
            report += "\n✅ Все подписчицы приглашены. Больше никому не пишу — workflow «Приглашения» можно выключить."
        notify(report)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())

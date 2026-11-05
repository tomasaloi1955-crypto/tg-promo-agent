# -*- coding: utf-8 -*-
"""
Разовое приглашение подписчиц канала «Мусульманка на спорте» в бесплатную неделю.

Каждый день (.github/workflows/invite.yml) пишет в личку следующим INVITE_PER_RUN
подписчицам (по умолчанию 20) короткое приглашение: «неделя бесплатных тренировок
в записи» + ссылка в бот воронки. Каждой — ОДИН раз за всё время, повторов нет.
Когда все подписчицы пройдены, присылает владелице «готово» и дальше ничего не
делает — workflow можно выключить.

Кого пропускаем:
  • боты, удалённые аккаунты, админы канала, сам аккаунт;
  • те, кто уже есть в базе бота воронки (нажимали /start), — если задан секрет
    SISTER_DATABASE_URL (та же строка, что DATABASE_URL у sister-bot). Им бот сам
    может написать командой /reweek, а прошедших анкету мы не беспокоим.

Защита аккаунта (это основной аккаунт промо-агента, 24.09.2026 его ограничивали):
  • перед прогоном — вопрос @SpamBot; ограничен — ничего не шлём;
  • не больше INVITE_PER_RUN (потолок 40) в день, паузы 1,5–4 минуты;
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

CHANNEL = os.getenv("INVITE_CHANNEL") or "ilikeislamandsport"
BOT_LINK = os.getenv("INVITE_BOT_LINK") or "https://t.me/pilatesmuslim_bot?start=src_dm_sport"
PER_RUN = min(int(os.getenv("INVITE_PER_RUN") or "20"), 40)
MIN_DELAY, MAX_DELAY = 90, 240
PAUSE_DAYS = 7                 # после предупреждения Telegram о спаме — неделя тишины
SISTER_DB = os.getenv("SISTER_DATABASE_URL", "")

# Несколько вариантов, чтобы не слать всем один и тот же текст (так меньше похоже на спам).
GREETINGS = ["Ассаляму алейкум", "Ассаляму алейкум ва рахматуллах", "Ас-саляму алейкум"]
MESSAGES = [
    "{hi}, {name}! 🤍\n\n"
    "Пишу вам как подписчице канала «Мусульманка на спорте». Дарю неделю бесплатных "
    "тренировок в записи: 3 тренировки дома, без зала и инвентаря, в удобное время.\n\n"
    "Забрать — по ссылке, бот задаст 3 коротких вопроса и сразу пришлёт первую тренировку:\n{link}",

    "{hi}, {name}! 🌸\n\n"
    "Вы подписаны на «Мусульманку на спорте» — хочу подарить вам неделю бесплатных "
    "домашних тренировок в записи (3 тренировки, через день).\n\n"
    "Начать можно здесь — первая тренировка придёт сразу после 3 вопросов:\n{link}",
]


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    return {"done": {}, "finished": None}


def save_memory(mem: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def message_for(user: types.User) -> str:
    name = (user.first_name or "").strip() or "сестра"
    return random.choice(MESSAGES).format(hi=random.choice(GREETINGS), name=name, link=BOT_LINK)


async def known_in_bot() -> set[int]:
    """id всех, кто есть в базе бота воронки (пусто, если база не подключена)."""
    if not SISTER_DB:
        return set()
    import asyncpg
    con = await asyncpg.connect(SISTER_DB, statement_cache_size=0)
    try:
        return {r["tg_id"] for r in await con.fetch("SELECT tg_id FROM users")}
    finally:
        await con.close()


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
        channel = await client.get_entity(CHANNEL)
        admins = {u.id async for u in client.iter_participants(channel, filter=types.ChannelParticipantsAdmins)}
        try:
            members = [u async for u in client.iter_participants(channel)]
        except errors.ChatAdminRequiredError:
            notify(f"⚠️ Приглашения: аккаунт не администратор канала @{CHANNEL} — Telegram не даёт "
                   "список подписчиц. Сделайте аккаунт админом канала.")
            return
        in_bot = await known_in_bot()
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
        report = (f"💌 Приглашения в бесплатную неделю (@{CHANNEL}): сегодня отправлено {sent}"
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

# -*- coding: utf-8 -*-
"""Ставит стартовые посты в канал ОТЛОЖЕННЫМИ сообщениями (Telegram → «Отложенные»).

Ничего не публикуется сразу: посты ждут своего времени, их можно открыть в Telegram,
поправить или удалить. Работает от вашего личного аккаунта (те же секреты, что у
промо-агента: API_ID, API_HASH, TELETHON_SESSION). Аккаунт должен быть админом канала
с правом публиковать сообщения.

Переменные:
  CHANNEL      @username или ссылка канала (обязательно)
  START_DATE   день 1 в формате 2026-11-05 (по умолчанию — завтра)
  TZ           часовой пояс расписания (по умолчанию Asia/Almaty)
  BOT_USERNAME username бота без @ — без него посты со ссылкой на бота (закреп, №12) пропускаются
  ONLY         номера постов через запятую (например 1,2,3) — по умолчанию все
  DRY_RUN      1 — только показать план, ничего не отправлять

Запуск: GitHub → Actions → «Нейропоток: посты в канал» → Run workflow.
"""
import asyncio
import inspect
import os
import random
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from posts import PINNED, POSTS  # noqa: E402

COVERS = Path(__file__).resolve().parent.parent / "covers"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def plan() -> list[tuple[datetime, dict]]:
    tz = ZoneInfo(env("TZ") or "Asia/Almaty")
    start = date.fromisoformat(env("START_DATE")) if env("START_DATE") else date.today() + timedelta(days=1)
    bot = env("BOT_USERNAME").lstrip("@")
    only = {x.strip() for x in env("ONLY").split(",") if x.strip()}
    now = datetime.now(timezone.utc)
    out = []
    for p in [PINNED] + POSTS:
        if only and str(p["id"]) not in only:
            continue
        if p.get("needs_bot") and not bot:
            print(f"— пост {p['id']}: пропущен (нет BOT_USERNAME, а в нём ссылка на бота)")
            continue
        when = datetime.combine(start + timedelta(days=p["day"] - 1), time(p["hour"]), tz)
        if when.astimezone(timezone.utc) < now + timedelta(minutes=5):
            print(f"— пост {p['id']}: время {when:%d.%m %H:%M} уже прошло — пропущен (сдвиньте START_DATE)")
            continue
        out.append((when, p))
    return sorted(out, key=lambda x: x[0])


def render(p: dict) -> str:
    bot = env("BOT_USERNAME").lstrip("@")
    channel = env("CHANNEL").rsplit("/", 1)[-1].lstrip("@")
    return p.get("text", "").replace("{bot}", bot).replace("{channel}", channel)


def make_poll(spec: dict):
    from telethon.tl import types

    def twe(s: str):
        if hasattr(types, "TextWithEntities"):
            return types.TextWithEntities(text=s, entities=[])
        return s

    answers = [types.PollAnswer(text=twe(a), option=bytes([i])) for i, a in enumerate(spec["answers"])]
    kwargs = {"id": random.randint(1, 2**62), "question": twe(spec["question"]), "answers": answers}
    if "hash" in inspect.signature(types.Poll.__init__).parameters:
        kwargs["hash"] = 0
    return types.InputMediaPoll(poll=types.Poll(**kwargs))


async def main() -> None:
    items = plan()
    if not env("CHANNEL"):
        sys.exit("Не задан CHANNEL (@username канала).")
    print(f"Канал: {env('CHANNEL')}. Постов к отложке: {len(items)}")
    for when, p in items:
        kind = "опрос" if p.get("poll") else ("картинка + текст" if p.get("image") else "текст")
        first = (p.get("text") or p.get("poll", {}).get("question", "")).split("\n")[0][:60]
        print(f"  {when:%d.%m %H:%M} · пост {p['id']} · {kind} · {first}")
    if env("DRY_RUN") == "1" or not items:
        print("DRY_RUN — ничего не отправлено." if items else "Отправлять нечего.")
        return

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(os.environ["TELETHON_SESSION"]),
                            int(os.environ["API_ID"]), os.environ["API_HASH"])
    await client.start()
    try:
        channel = await client.get_entity(env("CHANNEL"))
        print(f"Нашла канал: {getattr(channel, 'title', channel)}")
        done = 0
        for when, p in items:
            try:
                if p.get("poll"):
                    await client.send_file(channel, make_poll(p["poll"]), schedule=when)
                elif p.get("image") and (COVERS / p["image"]).exists():
                    await client.send_file(channel, COVERS / p["image"], caption=render(p),
                                           parse_mode="html", schedule=when)
                else:
                    await client.send_message(channel, render(p), parse_mode="html",
                                              link_preview=False, schedule=when)
                done += 1
                print(f"✅ пост {p['id']} → отложен на {when:%d.%m %H:%M}")
            except Exception as e:  # один сбой не должен ронять остальные
                print(f"⚠️ пост {p['id']}: {type(e).__name__}: {e}")
            await asyncio.sleep(2)
        print(f"Готово: {done} из {len(items)}. Проверьте в Telegram: канал → значок часов «Отложенные».")
        if any(p["id"] == "pin" for _, p in items):
            print("Закреп выйдет отложенным — когда опубликуется, закрепите его вручную.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

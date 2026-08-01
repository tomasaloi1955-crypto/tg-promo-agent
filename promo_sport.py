# -*- coding: utf-8 -*-
"""
Отдельная реклама канала «Мусульманка на спорте» — 5 раз в неделю (пн-пт),
ОТДЕЛЬНЫМ звеном от общей ротации 6 тем в promo.py. Основная ротация в
promo.py не трогается и продолжает работать как раньше (там спорт по-прежнему
получает свою обычную долю раз в 6 дней вместе с остальными 5 каналами) —
эта рассылка добавляется поверх, чтобы спорт-канал получал рекламу заметно
чаще остальных.

Использует поиск/публикацию из promo.py (find_and_post), но ведёт СВОЮ
ОТДЕЛЬНУЮ память (promo_memory_sport.json). Если бы обе рассылки писали в
один и тот же promo_memory.json, счётчик «уже опубликовано сегодня» был бы
общим, и вторая публикация в тот же день просто не выходила бы.
"""
import asyncio
import json
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

import promo
from promo import API_ID, API_HASH, SESSION_STRING, StopRun

MEMORY_FILE = Path(__file__).parent / "promo_memory_sport.json"


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    return {"posted": {}, "skipped": {}, "daily": {}}


def save_memory(mem: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


async def run() -> None:
    mem = load_memory()
    done = promo.already_done_today(mem)
    if done:
        promo.notify("Спорт-канал (доп. реклама 5x/неделю): на сегодня уже отправлено.")
        return

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    result = None
    stop_reason = None
    try:
        result = await promo.find_and_post(client, "sport", mem)
    except StopRun as e:
        stop_reason = str(e)
        print(f"СТОП: {stop_reason}")
    finally:
        await client.disconnect()

    save_memory(mem)

    if stop_reason:
        promo.notify(f"⚠️ СТОП (доп. реклама спорт-канала 5x/нед): {stop_reason}")
    elif result:
        v = result["verdict"]
        promo.notify(
            f"✅ [Доп. реклама 5x/нед] Опубликовано в спорт-канал.\n"
            f"Чат: {result['title']} ({result['key']}), участников: {result['members']}\n"
            f"Оценка Gemini: {v.get('verdict')} — {v.get('reason', '')}"
        )
    else:
        promo.notify(
            "[Доп. реклама 5x/нед] За сегодня не нашлось подходящего чата для "
            "спорт-канала (либо реклама явно не разрешена, либо уже использован "
            "недавно). Публикации не было."
        )


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(run())

# -*- coding: utf-8 -*-
"""
Отдельная реклама канала «Мусульманка на спорте» — ежедневно,
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
MAIN_MEMORY_FILE = Path(__file__).parent / "promo_memory.json"


def load_memory() -> dict:
    """Своя память (daily-отметка "уже сегодня" остаётся отдельной от основной
    ротации — иначе вторая рассылка в тот же день никогда бы не выходила).
    Но posted/skipped подмешиваем из основной ротации ПРИ ЧТЕНИИ, чтобы не
    постить второй раз в тот же чат, который уже использовала promo.py
    (иначе кулдаун 45/14 дней у двух независимых файлов не пересекается)."""
    if MEMORY_FILE.exists():
        mem = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    else:
        mem = {"posted": {}, "skipped": {}, "daily": {}}

    if MAIN_MEMORY_FILE.exists():
        main = json.loads(MAIN_MEMORY_FILE.read_text(encoding="utf-8"))
        for key, v in main.get("posted", {}).items():
            mem["posted"].setdefault(key, v)
        for key, v in main.get("skipped", {}).items():
            mem["skipped"].setdefault(key, v)

    return mem


def save_memory(mem: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


async def run() -> None:
    mem = load_memory()
    done = promo.already_done_today(mem)
    if done:
        promo.notify("Спорт-канал (доп. ежедневная реклама): на сегодня уже отправлено.")
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
        promo.notify(f"⚠️ СТОП (доп. ежедневная реклама спорт-канала): {stop_reason}")
    elif result:
        v = result["verdict"]
        cond = f" [условие: {v.get('condition')}]" if v.get("verdict") == "conditional" else ""
        promo.notify(
            f"✅ [Доп. реклама спорт-канала] Опубликовано.\n"
            f"Чат: {result['title']} ({result['key']}), участников: {result['members']}\n"
            f"Оценка Gemini: {v.get('verdict')}{cond} — {v.get('reason', '')}"
        )
    else:
        promo.notify(
            "[Доп. ежедневная реклама] За сегодня не нашлось подходящего чата для "
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

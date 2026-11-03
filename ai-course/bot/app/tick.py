"""Тик: GitHub Actions раз в час дёргает /tick, бот решает, кому что слать."""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone

from aiogram import Bot

from . import config, db, funnel, messages, sender, texts

log = logging.getLogger(__name__)
_lock = asyncio.Lock()


def person(u) -> funnel.Person:
    return funnel.Person(tg_id=u["tg_id"], started_at=u["started_at"], tz=u["tz"],
                         slot=u["slot"] or "evening", paid=u["paid_at"] is not None,
                         last_done_day=u["last_done_day"])


def missing_lesson(a: funnel.Action, loaded: dict[int, bool]) -> bool:
    """Урок ещё не загружен (ни видео, ни текста)."""
    return a.kind == "lesson" and a.day not in loaded


async def run(bot: Bot, now: datetime | None = None) -> dict:
    if _lock.locked():
        return {"status": "busy"}
    async with _lock:
        now = now or datetime.now(timezone.utc)
        users = await db.funnel_users()
        planned = [(u, a) for u in users for a in funnel.plan(person(u), now)]
        sent_before = await db.already_sent([(u["tg_id"], a.key) for u, a in planned])
        loaded = await db.lesson_numbers()
        result: Counter = Counter()
        blocked: set[int] = set()
        for u, a in planned:
            if (u["tg_id"], a.key) in sent_before or u["tg_id"] in blocked:
                continue
            if missing_lesson(a, loaded):
                # Урока нет — ключ урока не занимаем: он уйдёт, как только вы его загрузите
                # (сегодня или завтра). После MISSING_HOUR — один раз «урок задерживается».
                result["waiting_video"] += 1
                local_hour = now.astimezone(funnel.zone(u["tz"])).hour
                wait_key = f"lesson_wait:{a.day}"
                if local_hour >= config.MISSING_HOUR and (u["tg_id"], wait_key) not in sent_before \
                        and await db.claim_send(u["tg_id"], wait_key):
                    status = await messages.say(bot, u["tg_id"], texts.LESSON_MISSING.format(
                        n=a.day, channel=config.CHANNEL_LINK))
                    if status == sender.FAILED:
                        await db.release_send(u["tg_id"], wait_key)
                continue
            if not await db.claim_send(u["tg_id"], a.key):
                continue
            status = await messages.send_action(bot, u, a)
            if status == sender.FAILED:
                await db.release_send(u["tg_id"], a.key)      # повторим на следующем тике
            elif status == sender.BLOCKED:
                blocked.add(u["tg_id"])
            result[status] += 1
            result[a.kind] += 1
        await alert_missing(bot, users, loaded, now)
        log.info("Тик: участников %s, отправлено %s", len(users), dict(result))
        return {"status": "done", "users": len(users), **result}


async def alert_missing(bot: Bot, users, loaded: dict[int, bool], now: datetime) -> None:
    """Утром и вечером — напоминание вам, какие уроки нужно загрузить."""
    today: Counter = Counter()
    tomorrow: Counter = Counter()
    for u in users:
        d = funnel.funnel_day(u["started_at"], now, u["tz"])
        for day, bucket in ((d, today), (d + 1, tomorrow)):
            if day in funnel.LESSON_DAYS:
                bucket[funnel.LESSON_DAYS[day]] += 1
            if day in funnel.PRESENT_DAYS and u["paid_at"] is None:
                bucket[funnel.PRESENTATION] += 1
    need_today = sorted(n for n in today if n not in loaded)
    need_tomorrow = sorted(n for n in tomorrow if n not in loaded and n not in need_today)
    local = now.astimezone(funnel.zone(config.DEFAULT_TZ))
    if local.hour >= config.QUIET_HOUR:
        return
    part = "pm" if local.hour >= config.ADMIN_EVENING_HOUR else "am" if local.hour >= config.ADMIN_MORNING_HOUR else None
    if part is None:
        return

    def label(n: int) -> str:
        return "презентация курса" if n == funnel.PRESENTATION else f"урок {n}"
    lines = ([f"• {label(n)} — сегодня ({today[n]} чел.) → /upload {n}" for n in need_today]
             + [f"• {label(n)} — завтра ({tomorrow[n]} чел.) → /upload {n}" for n in need_tomorrow])
    if not lines or not await db.claim_alert(f"missing:{local.date()}:{part}"):
        return
    await messages.notify_admins(
        bot, "🎬 Нужно загрузить видео:\n" + "\n".join(lines)
        + f"\n\nПока урока нет, участники его ждут; в {config.MISSING_HOUR}:00 бот напишет им "
          "«урок задерживается», а сам урок пришлёт сразу после загрузки (до конца следующего дня).")

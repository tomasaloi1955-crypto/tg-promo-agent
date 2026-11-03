"""Расписание воронки: что положено отправить участнику прямо сейчас.

Только расчёт, без базы и Telegram — логику проверяют тесты (tests/test_funnel.py).
Отправляет tick.py.

У каждого сообщения ключ (lesson:2, sale:5 …). Ключ пишется в таблицу sends
перед отправкой, поэтому сообщение не уйдёт дважды, даже если тики пришли
подряд. Сообщение дня уходит, если сейчас этот день воронки и уже наступил его
час (по часовому поясу участника), но ещё не «тихий» час. Пропущенный целиком
день не догоняем — кроме урока: вчерашний урок, если не ушёл, придёт сегодня.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

# Бесплатный мини-интенсив: 3 урока, по одному в день.
LESSON_DAYS = {1: 1, 2: 2, 3: 3}         # день воронки → номер урока
LESSONS = len(LESSON_DAYS)
PRESENTATION = 4                         # номер «урока» с видео-презентацией курса (/upload 4)
CHECKIN_DAYS = (3,)                      # «Как вам интенсив?» вечером дня 3
NUDGE_DAYS = {3: 2}                      # день → к этому уроку пора было сделать задание
WARM_DAYS = {2: "warm_reviews"}          # 13:00
PRESENT_DAYS = (3,)                      # 21:00 — итоги + презентация курса
SALE_DAYS = (4, 5, 6, 7)                 # тарифы, возражения, «24 часа», последний день
POST_DAYS = (10, 14, 21)
PERIODIC_EVERY = 14                      # после 21-го дня — раз в 2 недели


@dataclass
class Person:
    tg_id: int
    started_at: datetime
    tz: str = config.DEFAULT_TZ
    slot: str = "evening"                # day (11:00) | evening (19:00)
    paid: bool = False
    last_done_day: int = 0               # номер последнего урока с выполненным заданием


@dataclass
class Action:
    key: str                             # уникальный ключ для таблицы sends
    kind: str                            # lesson | checkin | nudge | warm_reviews | present | sale | post
    day: int                             # день воронки; у lesson — номер урока
    extra: dict = field(default_factory=dict)


def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:
        return ZoneInfo(config.DEFAULT_TZ)


def funnel_day(started_at: datetime, now: datetime, tz: str) -> int:
    """День воронки: день анкеты = 1, следующий календарный день = 2 …"""
    z = zone(tz)
    return (now.astimezone(z).date() - started_at.astimezone(z).date()).days + 1


def slot_hour(slot: str | None) -> int:
    return config.DAY_HOUR if slot == "day" else config.EVENING_HOUR


def lessons_received(d: int) -> int:
    return sum(1 for day in LESSON_DAYS if day <= d)


def is_early(started_at: datetime | None, now: datetime, tz: str) -> bool:
    """Действует ли для человека ранняя цена (до конца дня EARLY_LAST_DAY)."""
    if started_at is None:
        return True
    return funnel_day(started_at, now, tz) <= config.EARLY_LAST_DAY


def plan(p: Person, now: datetime) -> list[Action]:
    """Все сообщения, которые участнику положены на текущий момент."""
    hour = now.astimezone(zone(p.tz)).hour
    if hour >= config.QUIET_HOUR:
        return []
    d = funnel_day(p.started_at, now, p.tz)
    out: list[Action] = []

    # Урок 1 бот шлёт сразу после анкеты (тот же ключ lesson:1), остальные — в час участника.
    # Вчерашний урок, который не ушёл, досылается сегодня (журнал sends не даст дубль).
    for wd in (d - 1, d):
        if wd in LESSON_DAYS and (wd < d or hour >= slot_hour(p.slot)):
            n = LESSON_DAYS[wd]
            out.append(Action(f"lesson:{n}", "lesson", n))
    if d in NUDGE_DAYS and p.last_done_day < NUDGE_DAYS[d] and hour >= config.NUDGE_HOUR:
        out.append(Action(f"nudge:{d}", "nudge", d))
    if d in CHECKIN_DAYS and hour >= config.CHECKIN_HOUR:
        out.append(Action(f"checkin:{d}", "checkin", d))

    if p.paid:
        return out
    if d in PRESENT_DAYS and hour >= config.PRESENT_HOUR:
        out.append(Action(f"present:{d}", "present", d))
    if hour < config.INFO_HOUR:
        return out
    if d in WARM_DAYS:
        out.append(Action(f"{WARM_DAYS[d]}:{d}", WARM_DAYS[d], d))
    elif d in SALE_DAYS:
        out.append(Action(f"sale:{d}", "sale", d))
    elif d in POST_DAYS or (d > POST_DAYS[-1] and (d - POST_DAYS[-1]) % PERIODIC_EVERY == 0):
        out.append(Action(f"post:{d}", "post", d))
    return out

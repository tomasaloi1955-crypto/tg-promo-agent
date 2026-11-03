"""Расписание воронки: python -m pytest tests  (из папки бота)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import funnel

ALMATY = ZoneInfo("Asia/Almaty")
START = datetime(2026, 11, 1, 9, 30, tzinfo=ALMATY)        # анкета пройдена 1 ноября


def at(day: int, hour: int, minute: int = 5) -> datetime:
    local = datetime(2026, 11, 1, hour, minute, tzinfo=ALMATY) + timedelta(days=day - 1)
    return local.astimezone(timezone.utc)


def keys(p: funnel.Person, now: datetime) -> set[str]:
    return {a.key for a in funnel.plan(p, now)}


def person(**kw) -> funnel.Person:
    base = dict(tg_id=1, started_at=START, tz="Asia/Almaty", slot="evening", last_done_day=0)
    base.update(kw)
    return funnel.Person(**base)


def test_lessons_one_per_day_with_catch_up():
    p = person(last_done_day=3)
    got = {d: sorted(a.day for a in funnel.plan(p, at(d, 19)) if a.kind == "lesson") for d in range(1, 6)}
    # каждый день — свой урок; вчерашний под тем же ключом (досылка, sends не даст дубль)
    assert got == {1: [1], 2: [1, 2], 3: [2, 3], 4: [3], 5: []}


def test_lesson_waits_for_slot_hour():
    assert "lesson:2" not in keys(person(slot="evening"), at(2, 18))
    assert "lesson:2" in keys(person(slot="evening"), at(2, 19))
    assert "lesson:2" in keys(person(slot="day"), at(2, 11))
    # урок 1 до часа слота не планируется (его шлёт анкета сразу)
    assert "lesson:1" not in keys(person(slot="evening"), at(1, 12))


def test_quiet_hour_sends_nothing():
    assert keys(person(), at(3, 22)) == set()


def test_day3_evening_nudge_checkin_presentation():
    p = person(last_done_day=1)
    assert "nudge:3" in keys(p, at(3, 17))
    assert "nudge:3" not in keys(person(last_done_day=2), at(3, 17))
    assert "checkin:3" in keys(p, at(3, 20))
    assert "present:3" not in keys(p, at(3, 20))
    assert "present:3" in keys(p, at(3, 21))


def test_warm_reviews_day2():
    assert "warm_reviews:2" in keys(person(), at(2, 13))
    assert "warm_reviews:2" not in keys(person(), at(2, 12))


def test_sales_days_4_to_7():
    for d in funnel.SALE_DAYS:
        assert f"sale:{d}" in keys(person(), at(d, 13))
    assert not any(k.startswith("sale") for k in keys(person(), at(8, 13)))


def test_paid_gets_no_sales_or_presentation():
    p = person(paid=True)
    assert not any(k.startswith(("sale", "present", "post")) for d in range(1, 40)
                   for k in keys(p, at(d, 21)))


def test_posts_and_periodic():
    assert "post:10" in keys(person(), at(10, 13))
    assert "post:21" in keys(person(), at(21, 13))
    assert "post:35" in keys(person(), at(35, 13))
    assert not any(k.startswith("post") for k in keys(person(), at(30, 13)))


def test_early_price_until_day_7():
    assert funnel.is_early(START, at(7, 23, 50), "Asia/Almaty")
    assert not funnel.is_early(START, at(8, 0, 10), "Asia/Almaty")
    assert funnel.is_early(None, at(1, 10), "Asia/Almaty")


def test_timezone_respected():
    p = person(tz="Europe/Moscow")
    # 19:05 в Алматы = 17:05 в Москве — урок 2 ещё рано
    assert "lesson:2" not in keys(p, at(2, 19))

"""Кнопки. Формат callback_data: короткие строки через «:»."""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram.types import InlineKeyboardButton as B
from aiogram.types import InlineKeyboardMarkup

from . import config, funnel, texts


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choices(prefix: str, options: dict) -> InlineKeyboardMarkup:
    return _kb([[B(text=label, callback_data=f"{prefix}:{key}")] for key, label in options.items()])


def done(n: int) -> InlineKeyboardMarkup:
    return _kb([[B(text=texts.DONE_BUTTON, callback_data=f"done:{n}")]])


def done_marked() -> InlineKeyboardMarkup:
    return _kb([[B(text=texts.DONE_ALREADY_BUTTON, callback_data="noop")]])


def checkin(day: int) -> InlineKeyboardMarkup:
    return _kb([[B(text=label, callback_data=f"fb:{day}:{key}")] for key, label in texts.MOODS.items()])


def checkin_skip() -> InlineKeyboardMarkup:
    return _kb([[B(text=texts.CHECKIN_SKIP_BUTTON, callback_data="fbskip")]])


def free_chat() -> InlineKeyboardMarkup | None:
    if not config.FREE_CHAT_LINK:
        return None
    return _kb([[B(text=texts.FREE_CHAT_BUTTON, url=config.FREE_CHAT_LINK)]])


def course(with_unsubscribe: bool = False) -> InlineKeyboardMarkup:
    rows = [[B(text=texts.COURSE_BUTTON, callback_data="course")],
            [B(text=texts.ASK_BUTTON, callback_data="ask")]]
    if with_unsubscribe:
        rows.append([B(text=texts.UNSUBSCRIBE_BUTTON, callback_data="unsub")])
    return _kb(rows)


def price(code: str, early: bool) -> str:
    p = config.PLANS[code]
    return p["price"] if early else p["price_late"]


def pay_link(code: str, early: bool) -> str:
    p = config.PLANS[code]
    return p["link"] if early else p["link_late"]


def _pay_rows(code: str, early: bool) -> list:
    p = config.PLANS[code]
    name = texts.PLAN_NAMES[code]
    rows = []
    link = pay_link(code, early)
    if link:
        rows.append([B(text=texts.PAY_TRIBUTE_BUTTON.format(plan=name, price=price(code, early)), url=link)])
    if p["stars"] > 0:
        rows.append([B(text=texts.PAY_STARS_BUTTON.format(plan=name, stars=p["stars"]),
                       callback_data=f"stars:{code}")])
    return rows


def tracks_on_sale() -> bool:
    """Продаём ли отдельные потоки: есть ссылка Tribute или цена в звёздах хоть у одного."""
    return any(config.PLANS[c]["link"] or config.PLANS[c]["stars"] for c in config.TRACK_PLANS)


def pay(early: bool) -> InlineKeyboardMarkup:
    """Целиком, с наставницей, «Один поток» (→ выбор потока, если продаются), «Я оплатила»."""
    rows = _pay_rows("full", early) + _pay_rows("mentor", early)
    if tracks_on_sale():
        rows.append([B(text=texts.ONE_TRACK_BUTTON.format(price=price("t1", early)), callback_data="tracks")])
    rows.append([B(text=texts.I_PAID_BUTTON, callback_data="ipaid")])
    rows.append([B(text=texts.ASK_BUTTON, callback_data="ask")])
    return _kb(rows)


def tracks(early: bool) -> InlineKeyboardMarkup:
    rows = []
    for code in config.TRACK_PLANS:
        rows += _pay_rows(code, early)
    rows.append([B(text=texts.I_PAID_BUTTON, callback_data="ipaid")])
    return _kb(rows)


def which_plan(prefix: str) -> InlineKeyboardMarkup:
    codes = [c for c in config.PLANS if c not in config.TRACK_PLANS or tracks_on_sale()]
    return _kb([[B(text=texts.PLAN_NAMES[code], callback_data=f"{prefix}:{code}")] for code in codes])


def settings(unsubscribed: bool) -> InlineKeyboardMarkup:
    return _kb([
        [B(text=texts.SET_SLOT_BUTTON, callback_data="set:slot")],
        [B(text=texts.SET_TZ_BUTTON, callback_data="set:tz")],
        [B(text=texts.RESUB_BUTTON, callback_data="resub") if unsubscribed
         else B(text=texts.UNSUB_BUTTON, callback_data="unsub")],
        [B(text=texts.COURSE_BUTTON, callback_data="course")],
    ])


def is_early(u, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return funnel.is_early(u["started_at"] if u else None, now, u["tz"] if u else config.DEFAULT_TZ)


# ─────────────────────────────── админка ───────────────────────────────

def moderate(fid: int) -> InlineKeyboardMarkup:
    return _kb([[B(text="✅ Одобрить", callback_data=f"adm:fb:1:{fid}"),
                 B(text="❌ Отклонить", callback_data=f"adm:fb:0:{fid}")]])


def payment_check(pid: int) -> InlineKeyboardMarkup:
    return _kb([[B(text="✅ Оплата есть — выдать доступ", callback_data=f"adm:pay:1:{pid}")],
                [B(text="❌ Оплаты нет", callback_data=f"adm:pay:0:{pid}")]])


SEGMENT_NAMES = {"all": "Всем", "notpaid": "Не купили", "paid": "Купили",
                 "inactive": "Прошли анкету, но ни одного задания"}


def segments() -> InlineKeyboardMarkup:
    return _kb([[B(text=name, callback_data=f"adm:seg:{key}")] for key, name in SEGMENT_NAMES.items()])


def confirm_broadcast() -> InlineKeyboardMarkup:
    return _kb([[B(text="🚀 Отправить", callback_data="adm:bc:go"),
                 B(text="Отмена", callback_data="adm:bc:cancel")]])

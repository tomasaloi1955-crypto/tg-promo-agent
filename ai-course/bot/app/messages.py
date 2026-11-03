"""Сборка и отправка сообщений воронки (общие для тика и обработчиков)."""
from __future__ import annotations

import html
import logging
import random
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from . import config, db, funnel, keyboards, sender, texts

log = logging.getLogger(__name__)
CAPTION_LIMIT = 1024


def name_of(u) -> str:
    return html.escape((u["first_name"] if u else None) or "сестра")


async def say(bot: Bot, tg_id: int, text: str,
              markup: InlineKeyboardMarkup | None = None, protect: bool = False) -> str:
    return await sender.call(tg_id, lambda: bot.send_message(
        tg_id, text, reply_markup=markup, disable_web_page_preview=True, protect_content=protect))


async def notify_admins(bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    for admin in config.ADMIN_IDS:
        try:
            await bot.send_message(admin, text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            log.exception("Не удалось уведомить админа %s", admin)


# ─────────────────────────────── уроки ───────────────────────────────

async def send_lesson(bot: Bot, tg_id: int, n: int, header: str | None = None,
                      markup: InlineKeyboardMarkup | None = None) -> str:
    """Урок n (видео + подпись) с кнопкой «Задание сделано». Видео защищено от
    пересылки (protect_content) — поэтому лучше грузить его файлом, а не ссылкой."""
    w = await db.get_lesson(n)
    if header is None:
        header = texts.LESSON_HEADER.format(n=n, total=funnel.LESSONS)
    if markup is None and n <= funnel.LESSONS:
        markup = keyboards.done(n)
    if w is None:
        return await say(bot, tg_id, texts.LESSON_MISSING.format(n=n, channel=config.CHANNEL_LINK), markup)
    body = header + (w["text"] or "")
    video = w["video"] or ""
    if not video:
        return await say(bot, tg_id, body, markup, protect=True)
    if video.startswith("http"):
        return await say(bot, tg_id, body + texts.LESSON_LINK.format(link=html.escape(video)), markup, protect=True)
    is_doc = video.startswith("doc:")
    file_id = video[4:] if is_doc else video
    method = bot.send_document if is_doc else bot.send_video
    if len(body) <= CAPTION_LIMIT:
        return await sender.call(tg_id, lambda: method(tg_id, file_id, caption=body, reply_markup=markup,
                                                       protect_content=True))
    result = await sender.call(tg_id, lambda: method(tg_id, file_id, caption=header, protect_content=True))
    if result != sender.OK:
        return result
    return await say(bot, tg_id, body, markup, protect=True)


# ─────────────────────────────── цены ───────────────────────────────

def price_vars(u, now: datetime | None = None) -> dict:
    """Подстановки цен для текстов продажи: p_* — цена сейчас, old_* — обычная."""
    now = now or datetime.now(timezone.utc)
    early = keyboards.is_early(u, now)
    out: dict = {"start": config.COURSE_START, "seats": config.MENTOR_SEATS,
                 "last_day": config.EARLY_LAST_DAY, "channel": config.CHANNEL_LINK}
    for code in config.PLANS:
        out[f"p_{code}"] = keyboards.price(code, early)
        out[f"old_{code}"] = config.PLANS[code]["price_late"]
    out["one_line"] = ((texts.ONE_LINE_EARLY if early else texts.ONE_LINE).format(**out)
                       if keyboards.tracks_on_sale() else "")
    out["price_block"] = (texts.PRICE_BLOCK_EARLY if early else texts.PRICE_BLOCK).format(**out)
    if early and u and u["started_at"]:
        left = config.EARLY_LAST_DAY - funnel.funnel_day(u["started_at"], now, u["tz"]) + 1
        out["deadline"] = texts.DEADLINE_EARLY.format(days_left=max(left, 1))
    else:
        out["deadline"] = texts.DEADLINE_NONE
    return out


async def send_course_offer(bot: Bot, u) -> str:
    v = price_vars(u)
    return await say(bot, u["tg_id"], texts.COURSE_OFFER.format(**v), keyboards.pay(keyboards.is_early(u)))


# ─────────────────────────────── плановые сообщения ───────────────────────────────

async def send_action(bot: Bot, u, a: funnel.Action) -> str:
    """Отправить одно плановое сообщение из funnel.plan()."""
    tg_id, name = u["tg_id"], name_of(u)

    if a.kind == "lesson":
        return await send_lesson(bot, tg_id, a.day)
    if a.kind == "checkin":
        return await say(bot, tg_id, texts.CHECKIN.format(name=name), keyboards.checkin(a.day))
    if a.kind == "nudge":
        return await say(bot, tg_id, texts.NUDGE.format(name=name), keyboards.free_chat())
    if a.kind == "warm_reviews":
        rows = await db.approved_reviews(tg_id)
        if not rows:
            return await say(bot, tg_id, texts.WARM_REVIEWS_EMPTY)
        reviews = "\n\n".join(texts.REVIEW_ITEM.format(
            text=html.escape(r["text"]), name=html.escape(r["first_name"] or "сестра")) for r in rows)
        return await say(bot, tg_id, texts.WARM_REVIEWS.format(reviews=reviews))
    if a.kind == "present":
        done = await db.done_count(tg_id)
        has_video = await db.get_lesson(funnel.PRESENTATION) is not None
        tail = texts.PRESENT_TAIL_VIDEO if has_video else texts.PRESENT_TAIL_TOMORROW
        text = (texts.PRESENT_STATS.format(done=done, tail=tail) if done
                else texts.PRESENT_STATS_ZERO.format(name=name, tail=tail))
        status = await say(bot, tg_id, text)
        if status != sender.OK or not has_video:
            return status
        return await send_lesson(bot, tg_id, funnel.PRESENTATION, header=texts.PRESENTATION_HEADER,
                                 markup=keyboards.course())
    if a.kind == "sale":
        v = price_vars(u)
        text = (texts.SALE_OFFER, texts.SALE_OBJECTIONS, texts.SALE_24H, texts.SALE_LAST)[
            funnel.SALE_DAYS.index(a.day)]
        if a.day == funnel.SALE_DAYS[0]:          # первое предложение — сразу с кнопками оплаты
            return await say(bot, tg_id, text.format(name=name, **v), keyboards.pay(keyboards.is_early(u)))
        return await say(bot, tg_id, text.format(name=name, **v), keyboards.course())
    if a.kind == "post":
        text = (texts.POST[funnel.POST_DAYS.index(a.day)] if a.day in funnel.POST_DAYS
                else random.choice(texts.PERIODIC))
        return await say(bot, tg_id, text.format(name=name, **price_vars(u)),
                         keyboards.course(with_unsubscribe=True))
    log.error("Неизвестный тип сообщения: %s", a.kind)
    return sender.FAILED

"""Сценарии участника: /start, анкета, задания, отзывы, настройки, курс и оплата, вопросы."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import config, db, funnel, keyboards, messages, payments, sender, texts

log = logging.getLogger(__name__)
router = Router(name="user")
router.message.filter(F.chat.type == "private")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _source(payload: str | None) -> str | None:
    """/start src_tgads_biz → tgads_biz. Любая другая метка сохраняется как есть."""
    if not payload:
        return None
    payload = payload.strip()[:64]
    if payload.startswith("src_"):
        payload = payload[4:]
    return payload or None


async def _user(fu):
    return await db.get_user(fu.id) or await db.upsert_user(fu.id, fu.username, fu.first_name, None)


# ─────────────────────────────── /start и анкета ───────────────────────────────

@router.message(CommandStart())
async def start(message: Message, command: CommandObject) -> None:
    fu = message.from_user
    u = await db.upsert_user(fu.id, fu.username, fu.first_name, _source(command.args))
    name = messages.name_of(u)
    if u["started_at"]:
        day = funnel.funnel_day(u["started_at"], _now(), u["tz"])
        await message.answer(texts.WELCOME_BACK.format(name=name, day=day), reply_markup=keyboards.free_chat())
        return
    await message.answer(texts.WELCOME.format(name=name))
    await message.answer(texts.Q_GOAL, reply_markup=keyboards.choices("q:goal", texts.GOALS))


@router.callback_query(F.data.startswith("q:"))
async def survey(cb: CallbackQuery, bot: Bot) -> None:
    _, field, value = cb.data.split(":", 2)
    await cb.answer()
    u = await _user(cb.from_user)
    options = {"goal": texts.GOALS, "level": texts.LEVELS, "slot": texts.SLOTS}
    if field not in options or value not in options[field]:
        return
    try:
        await cb.message.edit_text(f"{cb.message.html_text}\n\n<b>→ {options[field][value]}</b>")
    except Exception:
        pass
    if field == "goal":
        await db.set_field(u["tg_id"], "goal", value)
        await cb.message.answer(texts.Q_LEVEL, reply_markup=keyboards.choices("q:level", texts.LEVELS))
    elif field == "level":
        await db.set_field(u["tg_id"], "level", value)
        await cb.message.answer(texts.Q_SLOT, reply_markup=keyboards.choices("q:slot", texts.SLOTS))
    else:
        first_time = u["started_at"] is None
        u = await db.start_funnel(u["tg_id"], value)
        if not first_time:
            await cb.message.answer(texts.SAVED)
            return
        await messages.say(bot, u["tg_id"], texts.SURVEY_DONE.format(channel=config.CHANNEL_LINK))
        if config.FREE_CHAT_LINK:
            await messages.say(bot, u["tg_id"], texts.FREE_CHAT, keyboards.free_chat())
        # Урок 1 — сразу. Ключ тот же, что у тика: второй раз он его не пришлёт.
        if await db.claim_send(u["tg_id"], "lesson:1"):
            if await messages.send_lesson(bot, u["tg_id"], 1) == sender.FAILED:
                await db.release_send(u["tg_id"], "lesson:1")
        src = f", метка {html.escape(u['source'])}" if u["source"] else ""
        await messages.notify_admins(bot, f"👋 Новый участник интенсива: {messages.name_of(u)} "
                                          f"(id {u['tg_id']}){src}")


# ─────────────────────────────── задания ───────────────────────────────

@router.callback_query(F.data.startswith("done:"))
async def done(cb: CallbackQuery) -> None:
    n = int(cb.data.split(":")[1])
    u = await db.get_user(cb.from_user.id)
    if u is None or u["started_at"] is None:
        await cb.answer(texts.NOT_STARTED, show_alert=True)
        return
    if funnel.lessons_received(funnel.funnel_day(u["started_at"], _now(), u["tz"])) < n:
        await cb.answer(texts.DONE_TOO_EARLY, show_alert=True)
        return
    new, total = await db.mark_done(u["tg_id"], n)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=keyboards.done_marked())
    except Exception:
        pass
    await cb.message.answer((texts.DONE_REPLY if new else texts.DONE_REPLY_AGAIN).format(count=total))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


# ─────────────────────────────── «Как вам интенсив?» ───────────────────────────────

@router.callback_query(F.data.startswith("fb:"))
async def feedback_mood(cb: CallbackQuery) -> None:
    _, day, mood = cb.data.split(":")
    if mood not in texts.MOODS:
        return await cb.answer()
    await cb.answer()
    await db.add_feedback(cb.from_user.id, int(day), mood)
    await db.set_field(cb.from_user.id, "awaiting_feedback_day", int(day))
    try:
        await cb.message.edit_text(f"{cb.message.html_text}\n\n<b>→ {texts.MOODS[mood]}</b>")
    except Exception:
        pass
    await cb.message.answer(texts.CHECKIN_ASK_TEXT, reply_markup=keyboards.checkin_skip())


@router.callback_query(F.data == "fbskip")
async def feedback_skip(cb: CallbackQuery) -> None:
    await cb.answer()
    await db.set_field(cb.from_user.id, "awaiting_feedback_day", None)
    await cb.message.edit_text(texts.CHECKIN_SKIPPED)


# ─────────────────────────────── настройки ───────────────────────────────

@router.message(Command("settings"))
async def settings(message: Message) -> None:
    u = await db.get_user(message.from_user.id)
    if u is None or u["started_at"] is None:
        await message.answer(texts.NOT_STARTED)
        return
    await message.answer(texts.SETTINGS.format(
        slot=texts.SLOTS.get(u["slot"], "—"), tz=texts.TIMEZONES.get(u["tz"], u["tz"]),
        subscribed=texts.SUBSCRIBED_OFF if u["unsubscribed"] else texts.SUBSCRIBED_ON),
        reply_markup=keyboards.settings(u["unsubscribed"]))


@router.callback_query(F.data == "set:slot")
async def settings_slot(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(texts.Q_SLOT, reply_markup=keyboards.choices("q:slot", texts.SLOTS))


@router.callback_query(F.data == "set:tz")
async def settings_tz(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(texts.TZ_CHOOSE, reply_markup=keyboards.choices("tz", texts.TIMEZONES))


@router.callback_query(F.data.startswith("tz:"))
async def set_tz(cb: CallbackQuery) -> None:
    tz = cb.data[3:]
    if tz not in texts.TIMEZONES:
        return await cb.answer()
    await db.set_field(cb.from_user.id, "tz", tz)
    await cb.answer(texts.SAVED)
    await cb.message.edit_text(f"{texts.TZ_CHOOSE}\n\n<b>→ {texts.TIMEZONES[tz]}</b>")


@router.message(Command("stop"))
@router.callback_query(F.data == "unsub")
async def unsubscribe(event: Message | CallbackQuery) -> None:
    await db.set_field(event.from_user.id, "unsubscribed", True)
    if isinstance(event, CallbackQuery):
        await event.answer()
        event = event.message
    await event.answer(texts.UNSUBSCRIBED)


@router.callback_query(F.data == "resub")
async def resubscribe(cb: CallbackQuery) -> None:
    await db.set_field(cb.from_user.id, "unsubscribed", False)
    await cb.answer()
    await cb.message.answer(texts.RESUBSCRIBED)


# ─────────────────────────────── курс и оплата ───────────────────────────────

@router.message(Command("course"))
@router.callback_query(F.data == "course")
async def course(event: Message | CallbackQuery, bot: Bot) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer()
    u = await _user(event.from_user)
    if u["paid_at"]:                             # купившему — свежие ссылки; докупить тоже можно
        await payments.send_links(bot, u["tg_id"], None, again=True)
    await messages.send_course_offer(bot, u)


@router.callback_query(F.data == "tracks")
async def tracks(cb: CallbackQuery) -> None:
    await cb.answer()
    u = await _user(cb.from_user)
    early = keyboards.is_early(u)
    kb = keyboards.tracks(early)
    if not any(config.PLANS[c]["link"] for c in config.TRACK_PLANS) and \
            not any(config.PLANS[c]["stars"] for c in config.TRACK_PLANS):
        await cb.message.answer(texts.NO_PAY_LINK, reply_markup=kb)
        return
    await cb.message.answer(texts.CHOOSE_TRACK, reply_markup=kb)


@router.callback_query(F.data == "ask")
async def ask(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(texts.ASK_REPLY)


@router.callback_query(F.data.startswith("stars:"))
async def pay_stars(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    code = cb.data.split(":", 1)[1]
    plan = config.PLANS.get(code)
    if plan is None or plan["stars"] <= 0:
        return
    await bot.send_invoice(
        chat_id=cb.from_user.id, title=texts.STARS_TITLE,
        description=texts.STARS_DESCRIPTION.format(plan=texts.PLAN_NAMES[code]),
        payload=f"course:{code}", currency="XTR",
        prices=[LabeledPrice(label=texts.STARS_TITLE, amount=plan["stars"])])


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery) -> None:
    await q.answer(ok=q.invoice_payload.removeprefix("course:") in config.PLANS)


@router.message(F.successful_payment)
async def stars_paid(message: Message, bot: Bot) -> None:
    sp = message.successful_payment
    plan = sp.invoice_payload.removeprefix("course:")
    pid = await db.add_payment(message.from_user.id, "stars", "stars:" + sp.telegram_payment_charge_id,
                               sp.total_amount, sp.currency, "paid", {"payload": sp.invoice_payload, "plan": plan})
    if pid is not None:
        await payments.grant_access(bot, message.from_user.id, plan)


@router.callback_query(F.data == "ipaid")
async def i_paid(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(texts.I_PAID_WHICH, reply_markup=keyboards.which_plan("ipaid"))


@router.callback_query(F.data.startswith("ipaid:"))
async def i_paid_plan(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    code = cb.data.split(":", 1)[1]
    if code not in config.PLANS:
        return
    u = await _user(cb.from_user)
    await cb.message.answer(await payments.manual_claim(bot, u, code))


# ─────────────────────────────── свободный текст и файлы ───────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def free_text(message: Message, bot: Bot) -> None:
    u = await _user(message.from_user)
    day = u["awaiting_feedback_day"]
    who = messages.name_of(u) + (f" @{u['username']}" if u["username"] else "")
    if day is not None:
        fid = await db.add_feedback_text(u["tg_id"], day, message.text[:2000])
        await db.set_field(u["tg_id"], "awaiting_feedback_day", None)
        await message.answer(texts.CHECKIN_THANKS)
        await messages.notify_admins(
            bot, f"💬 Новый отзыв от {who}:\n\n«{html.escape(message.text[:2000])}»", keyboards.moderate(fid))
        return
    # Вопрос, ссылка на бота-домашку, скрин ошибки текстом — всё вам в личку.
    await message.answer(texts.MESSAGE_RECEIVED)
    await messages.notify_admins(
        bot, f"✉️ {who} (id {u['tg_id']}):\n\n{html.escape(message.text[:3500])}\n\n"
             f"Ответить: <code>/reply {u['tg_id']} текст</code>")


@router.message(F.photo | F.document | F.video | F.voice)
async def free_media(message: Message, bot: Bot) -> None:
    """Скрин ошибки или голосовое — пересылаем админам как есть."""
    u = await _user(message.from_user)
    await message.answer(texts.MESSAGE_RECEIVED)
    for admin in config.ADMIN_IDS:
        try:
            await message.forward(admin)
            await bot.send_message(admin, f"↑ от {messages.name_of(u)} (id {u['tg_id']}). "
                                          f"Ответить: <code>/reply {u['tg_id']} текст</code>")
        except Exception:
            log.exception("Не удалось переслать админу %s", admin)

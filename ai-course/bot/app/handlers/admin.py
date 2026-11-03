"""Админка — только для ADMIN_IDS."""
from __future__ import annotations

import asyncio
import csv
import html
import io
import json
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import config, db, funnel, keyboards, messages, payments, sender, texts

log = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(F.chat.type == "private", F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))
_background: set[asyncio.Task] = set()

PLAN_CODES = ", ".join(config.PLANS)
HELP = (
    "<b>Админка Нейропотока</b>\n\n"
    "/stats — статистика, источники, продажи\n"
    f"/upload 1 — загрузить урок 1 (1–{funnel.LESSONS}); /upload {funnel.PRESENTATION} — видео-презентация курса\n"
    "/lessons — что загружено\n"
    "/show 2 — посмотреть урок как участник\n"
    "/broadcast — рассылка по сегменту\n"
    "/reviews — модерация отзывов\n"
    "/reply 123456789 текст — ответить участнику от имени бота\n"
    "/list — последние 30 участников\n"
    "/who 123456789 — всё об участнике\n"
    f"/grant 123456789 full — выдать доступ вручную (тарифы: {PLAN_CODES})\n"
    "/links 123456789 — прислать участнику свежие ссылки на купленное\n"
    "/export — выгрузка в CSV\n"
    "/tick — прогнать рассылку по расписанию сейчас\n"
    "/cancel — отменить текущее действие"
)


class Upload(StatesGroup):
    content = State()
    text = State()


class Broadcast(StatesGroup):
    message = State()
    confirm = State()


@router.message(Command("admin"))
async def admin_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


# ─────────────────────────────── /stats ───────────────────────────────

def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "—"


@router.message(Command("stats"))
async def stats(message: Message) -> None:
    s = await db.stats()
    t = s["total"]
    now = datetime.now(timezone.utc)
    buckets = {"интенсив (1–3)": 0, "продажа (4–7)": 0, "после": 0}
    received = 0
    for r in s["started"]:
        d = funnel.funnel_day(r["started_at"], now, r["tz"])
        received += funnel.lessons_received(d)
        key = ("интенсив (1–3)" if d < funnel.SALE_DAYS[0]
               else "продажа (4–7)" if d <= funnel.SALE_DAYS[-1] else "после")
        buckets[key] += 1
    done_total = sum(r["n"] for r in s["by_day"])
    lines = [
        "<b>📊 Статистика</b>",
        f"Пришли в бота: <b>{t['users']}</b> (за сутки +{t['new_today']})",
        f"Прошли анкету: <b>{t['surveyed']}</b> ({_pct(t['surveyed'], t['users'])})",
        f"Купили: <b>{t['paid']}</b> — конверсия анкета → покупка <b>{_pct(t['paid'], t['surveyed'])}</b>",
        "По тарифам: " + (", ".join(f"{texts.PLAN_NAMES.get(r['plan'], r['plan'])}: {r['n']}"
                                    + (f" ({r['amount']:g})" if r["amount"] else "") for r in s["by_plan"]) or "—"),
        f"Отписались: {t['unsubscribed']} · заблокировали бота: {t['blocked']}",
        "",
        f"Задания: <b>{done_total}</b> из {received} выданных уроков ({_pct(done_total, received)})",
        "По урокам: " + (" ".join(f"{r['day']}:{r['n']}" for r in s["by_day"]) or "—"),
        "Где сейчас: " + ", ".join(f"{k}: {v}" for k, v in buckets.items()),
        "",
        "<b>Источники</b> (пришли / анкета / купили / конверсия):",
    ]
    for r in s["by_source"]:
        lines.append(f"• {html.escape(r['source'])}: {r['users']} / {r['surveyed']} / "
                     f"{r['paid']} / {_pct(r['paid'], r['users'])}")
    await message.answer("\n".join(lines))


# ─────────────────────────────── уроки ───────────────────────────────

def _lesson_label(n: int) -> str:
    return "Видео-презентация курса" if n == funnel.PRESENTATION else f"Урок {n}"


@router.message(Command("upload"))
async def upload(message: Message, command: CommandObject, state: FSMContext) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit() or not 1 <= int(arg) <= funnel.PRESENTATION:
        await message.answer(f"Формат: <code>/upload 1</code> — урок 1–{funnel.LESSONS}, "
                             f"<code>/upload {funnel.PRESENTATION}</code> — презентация курса.")
        return
    n = int(arg)
    await state.set_state(Upload.content)
    await state.update_data(n=n)
    await message.answer(f"{_lesson_label(n)}.\n\nПришлите <b>видео</b> (подпись = текст урока, задание)\n"
                         "или <b>текст</b>: если первая строка — ссылка, она станет видео.\n/cancel — отмена.")


@router.message(Upload.content, F.video | F.document)
async def upload_video(message: Message, state: FSMContext, bot: Bot) -> None:
    video = message.video.file_id if message.video else "doc:" + message.document.file_id
    if message.caption:
        await _save(message, state, bot, video, message.html_text)
        return
    await state.update_data(video=video)
    await state.set_state(Upload.text)
    await message.answer("Видео есть. Теперь пришлите текст урока (или «-» — без текста).")


@router.message(Upload.content, F.text)
async def upload_text_only(message: Message, state: FSMContext, bot: Bot) -> None:
    full = message.html_text
    first, _, _ = message.text.partition("\n")
    if first.strip().startswith("http"):
        rest = full.split("\n", 1)[1].strip() if "\n" in full else ""
        await _save(message, state, bot, first.strip(), rest)
    else:
        await _save(message, state, bot, None, full)


@router.message(Upload.text, F.text)
async def upload_text(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await _save(message, state, bot, data["video"], "" if message.text.strip() == "-" else message.html_text)


async def _save(message: Message, state: FSMContext, bot: Bot, video: str | None, text: str) -> None:
    n = (await state.get_data())["n"]
    await state.clear()
    await db.save_lesson(n, video, text.strip())
    await message.answer(f"✅ Сохранено: {_lesson_label(n).lower()}. Вот как увидит участник:")
    if n == funnel.PRESENTATION:
        await messages.send_lesson(bot, message.from_user.id, n, header=texts.PRESENTATION_HEADER,
                                   markup=keyboards.course())
    else:
        await messages.send_lesson(bot, message.from_user.id, n)


@router.message(Command("lessons"))
async def lessons(message: Message) -> None:
    have = await db.lesson_numbers()
    lines = [f"{_lesson_label(n)}: " + ("🎬 видео" if have.get(n) else "📝 только текст" if n in have else "· нет")
             for n in range(1, funnel.PRESENTATION + 1)]
    await message.answer("\n".join(lines) + "\n\nЗагрузить: /upload 1")


@router.message(Command("show"))
async def show(message: Message, command: CommandObject, bot: Bot) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Формат: <code>/show 2</code>")
        return
    n = int(arg)
    if n == funnel.PRESENTATION:
        await messages.send_lesson(bot, message.from_user.id, n, header=texts.PRESENTATION_HEADER,
                                   markup=keyboards.course())
    else:
        await messages.send_lesson(bot, message.from_user.id, n)


# ─────────────────────────────── рассылка ───────────────────────────────

@router.message(Command("broadcast"))
async def broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Кому отправить?", reply_markup=keyboards.segments())


@router.callback_query(F.data.startswith("adm:seg:"))
async def broadcast_segment(cb: CallbackQuery, state: FSMContext) -> None:
    segment = cb.data.split(":")[2]
    if segment not in keyboards.SEGMENT_NAMES:
        return await cb.answer()
    await cb.answer()
    await state.set_state(Broadcast.message)
    await state.update_data(segment=segment)
    await cb.message.answer(f"Сегмент: <b>{keyboards.SEGMENT_NAMES[segment]}</b>.\n"
                            "Пришлите сообщение для рассылки (текст, фото, видео). /cancel — отмена.")


@router.message(Broadcast.message)
async def broadcast_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids = await db.segment_ids(data["segment"])
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Broadcast.confirm)
    await message.answer(f"Получателей: <b>{len(ids)}</b>. Отправляем?", reply_markup=keyboards.confirm_broadcast())


@router.callback_query(Broadcast.confirm, F.data.startswith("adm:bc:"))
async def broadcast_confirm(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    await cb.answer()
    if cb.data.endswith("cancel"):
        await cb.message.edit_text("Рассылка отменена.")
        return
    await cb.message.edit_text("🚀 Рассылка пошла. Пришлю итог, когда закончу.")
    task = asyncio.create_task(_run_broadcast(bot, cb.from_user.id, data))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _run_broadcast(bot: Bot, admin_id: int, data: dict) -> None:
    ids = await db.segment_ids(data["segment"])
    counts = {sender.OK: 0, sender.BLOCKED: 0, sender.FAILED: 0}
    for tg_id in ids:
        status = await sender.call(tg_id, lambda t=tg_id: bot.copy_message(
            chat_id=t, from_chat_id=data["chat_id"], message_id=data["message_id"]))
        counts[status] += 1
    log.info("Рассылка %s: %s", data["segment"], counts)
    await bot.send_message(admin_id, f"✅ Рассылка готова: доставлено {counts['ok']}, "
                                     f"заблокировали бота {counts['blocked']}, ошибок {counts['failed']}.")


# ─────────────────────────────── отзывы и ответы ───────────────────────────────

async def _show_next_review(message: Message) -> None:
    f = await db.next_pending_feedback()
    if f is None:
        await message.answer("Новых отзывов нет 🎉")
        return
    who = html.escape(f["first_name"] or "—") + (f" @{f['username']}" if f["username"] else "")
    await message.answer(f"Отзыв #{f['id']} от {who}:\n\n«{html.escape(f['text'])}»",
                         reply_markup=keyboards.moderate(f["id"]))


@router.message(Command("reviews"))
async def reviews(message: Message) -> None:
    await _show_next_review(message)


@router.callback_query(F.data.startswith("adm:fb:"))
async def moderate(cb: CallbackQuery) -> None:
    _, _, ok, fid = cb.data.split(":")
    await db.moderate_feedback(int(fid), ok == "1")
    await cb.answer("Одобрен" if ok == "1" else "Отклонён")
    await cb.message.edit_text(cb.message.html_text + ("\n\n✅ Одобрен" if ok == "1" else "\n\n❌ Отклонён"))
    await _show_next_review(cb.message)


@router.message(Command("reply"))
async def reply(message: Message, command: CommandObject, bot: Bot) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer("Формат: <code>/reply 123456789 текст ответа</code>")
        return
    text = texts.ADMIN_REPLY_PREFIX.format(author=html.escape(config.AUTHOR_NAME)) + html.escape(parts[1])
    status = await messages.say(bot, int(parts[0]), text)
    await message.answer("✅ Отправлено" if status == sender.OK else f"⚠️ Не доставлено ({status})")


# ─────────────────────────────── оплаты ───────────────────────────────

@router.callback_query(F.data.startswith("adm:pay:"))
async def payment_decision(cb: CallbackQuery, bot: Bot) -> None:
    _, _, ok, pid = cb.data.split(":")
    p = await db.get_payment(int(pid))
    if p is None or not await db.set_payment_status(p["id"], "paid" if ok == "1" else "rejected"):
        await cb.answer("Уже обработано", show_alert=True)
        return
    await cb.answer()
    if ok == "1":
        await payments.grant_access(bot, p["tg_id"], json.loads(p["raw"] or "{}").get("plan"))
        verdict = "\n\n✅ Доступ выдан"
    else:
        await messages.say(bot, p["tg_id"], texts.PAYMENT_REJECTED)
        verdict = "\n\n❌ Отклонено"
    await cb.message.edit_text(cb.message.html_text + verdict)


@router.message(Command("grant"))
async def grant(message: Message, command: CommandObject, bot: Bot) -> None:
    args = (command.args or "").split()
    plan = args[1].lower() if len(args) > 1 else "full"
    if not args or not args[0].isdigit() or plan not in config.PLANS:
        await message.answer(f"Формат: <code>/grant 123456789 full</code>\nТарифы: {PLAN_CODES}")
        return
    tg_id = int(args[0])
    await db.add_payment(tg_id, "manual", None, None, None, "paid", {"by": message.from_user.id, "plan": plan})
    await payments.grant_access(bot, tg_id, plan)


@router.message(Command("links"))
async def links(message: Message, command: CommandObject, bot: Bot) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Формат: <code>/links 123456789</code>")
        return
    ok = await payments.send_links(bot, int(arg), None, again=True)
    await message.answer("✅ Ссылки отправлены" if ok else "⚠️ Ссылок нет: нет оплат или бот не админ в каналах.")


# ─────────────────────────────── люди ───────────────────────────────

def _when(dt: datetime | None, tz: str) -> str:
    return dt.astimezone(funnel.zone(tz)).strftime("%d.%m %H:%M") if dt else "—"


@router.message(Command("list"))
async def people(message: Message) -> None:
    rows = await db.recent_people()
    if not rows:
        await message.answer("Пока никого нет.")
        return
    now = datetime.now(timezone.utc)
    lines = ["<b>Последние участники</b> (новые сверху). Подробно: /who id\n"]
    for r in rows:
        name = messages.name_of(r) + (f" @{html.escape(r['username'])}" if r["username"] else "")
        where = ("анкету не закончил(а)" if r["started_at"] is None
                 else f"день {funnel.funnel_day(r['started_at'], now, r['tz'])}, заданий {r['done']}")
        marks = ("💰" if r["paid_at"] else "") + ("⛔" if r["blocked"] else "") + ("🔕" if r["unsubscribed"] else "")
        lines.append(f"• {name} — <code>{r['tg_id']}</code> — {where} {marks}".rstrip())
    await message.answer("\n".join(lines))


@router.message(Command("who"))
async def who(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Формат: <code>/who 123456789</code>")
        return
    card = await db.person_card(int(arg))
    if card is None:
        await message.answer("Такого участника в боте нет.")
        return
    u = card["user"]
    tz = u["tz"]
    lines = [f"<b>{messages.name_of(u)}</b>" + (f" @{html.escape(u['username'])}" if u["username"] else "")
             + f" (id {u['tg_id']})",
             f"Пришёл(шла): {_when(u['created_at'], tz)}, метка: {html.escape(u['source'] or '—')}"]
    if u["started_at"] is None:
        lines.append("❗ Анкету не закончил(а)")
    else:
        day = funnel.funnel_day(u["started_at"], datetime.now(timezone.utc), tz)
        lines.append(f"Анкета: {texts.GOALS.get(u['goal'], '—')}; {texts.LEVELS.get(u['level'], '—')}; "
                     f"{texts.SLOTS.get(u['slot'], '—')}")
        lines.append(f"Старт: {_when(u['started_at'], tz)} — сейчас <b>день {day}</b>")
    lines.append("Задания: " + (", ".join(f"№{d}" for d in card["done"]) or "ни одного"))
    for p in card["payments"]:
        lines.append(f"Оплата: {p['provider']}, {p['status']}, {texts.PLAN_NAMES.get(p['plan'] or '', p['plan'] or '—')}, "
                     f"{_when(p['created_at'], tz)}")
    if u["unsubscribed"]:
        lines.append("🔕 Отписан(а) от рассылки")
    if u["blocked"]:
        lines.append("⛔ Заблокировал(а) бота")
    if card["sends"]:
        lines.append("\nПоследнее отправленное:")
        lines += [f"• {_when(s['sent_at'], tz)} — {html.escape(s['key'])}" for s in card["sends"]]
    await message.answer("\n".join(lines))


# ─────────────────────────────── выгрузка и тик ───────────────────────────────

@router.message(Command("export"))
async def export(message: Message) -> None:
    rows = await db.export_rows()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if rows:
        w.writerow(rows[0].keys())
    for r in rows:
        w.writerow(["" if v is None else v for v in r.values()])
    data = buf.getvalue().encode("utf-8-sig")
    await message.answer_document(BufferedInputFile(data, filename=f"neuro_users_{datetime.now(timezone.utc):%Y-%m-%d}.csv"),
                                  caption=f"Участников: {len(rows)}")


@router.message(Command("tick"))
async def tick_now(message: Message, bot: Bot) -> None:
    from .. import tick
    result = await tick.run(bot)
    await message.answer(f"Тик: <code>{html.escape(json.dumps(result, ensure_ascii=False))}</code>")

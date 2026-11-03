"""Оплата курса: Tribute (вебхук), звёзды Telegram, ручная проверка «Я оплатил(а)».

Тарифы — config.PLANS (t1/t2/t3/full/mentor). Тариф пишется в payments.raw->>'plan';
по нему бот выдаёт одноразовые ссылки в закрытые каналы этого тарифа.

Если Tribute-аккаунт общий с sister-bot: у Tribute один адрес вебхука на аккаунт,
он указывает на sister-bot. Там командой `/route <id товара> https://<этот бот>/tribute`
направьте товары курса сюда — sister-bot перешлёт уведомление с той же подписью.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from . import config, db, keyboards, messages, texts

log = logging.getLogger(__name__)
PAID_EVENTS = ("new_digital_product", "new_subscription")


def plan_name(plan: str | None) -> str:
    return texts.PLAN_NAMES.get(plan or "", plan or "?")


def chats_of(plans: list[str]) -> list[str]:
    out: list[str] = []
    for code in plans:
        for chat in config.PLANS.get(code, {}).get("chats", []):
            if chat not in out:
                out.append(chat)
    return out


async def make_links(bot: Bot, tg_id: int, plans: list[str]) -> list[str]:
    """Одноразовые ссылки во все каналы тарифов (7 дней). Пустой список — не вышло."""
    lines = []
    for chat in chats_of(plans):
        try:
            title = (await bot.get_chat(int(chat))).title or "Курс"
            invite = await bot.create_chat_invite_link(
                chat_id=int(chat), name=f"neuro {tg_id}"[:32], member_limit=1,
                expire_date=datetime.now(timezone.utc) + timedelta(days=7))
            lines.append(texts.ACCESS_LINK_ITEM.format(title=html.escape(title), link=invite.invite_link))
        except Exception:
            log.exception("Нет ссылки в %s (бот — админ канала? id верный?)", chat)
    return lines


async def send_links(bot: Bot, tg_id: int, plan: str | None, again: bool = False) -> bool:
    plans = await db.paid_plans(tg_id) if again else [plan] if plan else []
    lines = await make_links(bot, tg_id, plans)
    if not lines:
        await messages.say(bot, tg_id, texts.ACCESS_GRANTED_NO_LINK.format(plan=plan_name(plan)))
        return False
    text = (texts.LINKS_AGAIN.format(links="\n".join(lines)) if again
            else texts.ACCESS_GRANTED.format(plan=plan_name(plan), links="\n".join(lines),
                                            start=config.COURSE_START))
    await messages.say(bot, tg_id, text)
    return True


async def grant_access(bot: Bot, tg_id: int, plan: str | None) -> None:
    """Покупка подтверждена: отметка + ссылки. После paid_at продажи этому человеку не идут."""
    await db.mark_paid(tg_id)
    ok = await send_links(bot, tg_id, plan)
    u = await db.get_user(tg_id)
    who = messages.name_of(u) + (f" @{u['username']}" if u and u["username"] else "")
    src = f", источник: {html.escape(u['source'])}" if u and u["source"] else ""
    await messages.notify_admins(
        bot, f"💰 Покупка: {who} (id {tg_id}), тариф: {plan_name(plan)}{src}"
             + ("" if plan in config.PLANS else "\n⚠️ Тариф не опознан.")
             + ("" if ok else "\n⚠️ Ссылки не созданы — добавьте человека в канал курса вручную "
                              "и проверьте COURSE_CHAT_* и права бота."))


# ─────────────────────────────── Tribute ───────────────────────────────

def tribute_signature_ok(body: bytes, signature: str) -> bool:
    """Tribute подписывает тело HMAC-SHA256 API-ключом (заголовок trbt-signature)."""
    if not config.TRIBUTE_API_KEY or not signature:
        return False
    expected = hmac.new(config.TRIBUTE_API_KEY.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def product_keys(p: dict) -> list[str]:
    return [str(p[k]) for k in ("product_id", "subscription_id", "period_id") if p.get(k) is not None]


def plan_of_product(keys: list[str]) -> str | None:
    for code, plan in config.PLANS.items():
        if any(k in plan["products"] for k in keys):
            return code
    return None


async def handle_tribute(bot: Bot, body: bytes) -> dict:
    event = json.loads(body or b"{}")
    name = event.get("name", "")
    p = event.get("payload") or {}
    if name not in PAID_EVENTS:
        return {"ok": True, "ignored": name}
    keys = product_keys(p)
    plan = plan_of_product(keys)
    tg_id = p.get("telegram_user_id")
    if plan is None:
        info = f"{p.get('amount') or p.get('price') or '?'} {p.get('currency') or ''}".strip()
        await messages.notify_admins(
            bot, f"🆕 Оплата незнакомого товара Tribute: id {', '.join(keys) or '—'}, сумма {info}, "
                 f"покупатель {tg_id}.\nДобавьте id в TRIBUTE_PRODUCT_IDS_&lt;тариф&gt; на Render "
                 f"и выдайте доступ: <code>/grant {tg_id} full</code>")
        return {"ok": True, "ignored": "unknown product"}
    if not tg_id:
        log.warning("Tribute: нет telegram_user_id в %s", p)
        return {"ok": True, "ignored": "нет telegram_user_id"}
    tg_id = int(tg_id)
    external = str(p.get("purchase_id") or p.get("transaction_id")
                   or f"{name}:{tg_id}:{event.get('created_at', '')}")
    pid = await db.add_payment(tg_id, "tribute", "tribute:" + external, p.get("amount") or p.get("price"),
                               p.get("currency"), "paid", {**event, "plan": plan})
    if pid is None:
        return {"ok": True, "duplicate": True}
    log.info("Tribute: %s %s от %s, тариф %s", name, external, tg_id, plan)
    await grant_access(bot, tg_id, plan)
    return {"ok": True}


# ─────────────────────────────── «Я оплатил(а)» ───────────────────────────────

async def manual_claim(bot: Bot, u, plan: str) -> str:
    if await db.pending_claim(u["tg_id"]):
        return texts.I_PAID_ALREADY
    pid = await db.add_payment(u["tg_id"], "manual", None, None, None, "pending", {"plan": plan})
    who = messages.name_of(u) + (f" @{u['username']}" if u["username"] else "")
    price = keyboards.price(plan, keyboards.is_early(u))
    await messages.notify_admins(
        bot, f"🧾 «Я оплатил(а)»: {who} (id {u['tg_id']}), тариф {plan_name(plan)} — {price}.\n"
             "Проверьте поступление в Tribute/банке:", keyboards.payment_check(pid))
    return texts.I_PAID_REPLY

# -*- coding: utf-8 -*-
"""Публикует стартовые посты в канал через бота (Bot API), сразу, по порядку.

Бот должен быть админом канала с правом «Публикация сообщений».
Канал: CHANNEL — @username/ссылка/-100id или название. По названию бот искать не умеет,
поэтому проверяем кандидатов: CANDIDATES (через запятую) + каналы из getUpdates.
Публикуем, только если ровно один кандидат подходит: бот там админ с правом постить
и название совпадает с CHANNEL (или, если совпадений нет, в названии есть «halal»).

Переменные: BOT_TOKEN, CHANNEL, CANDIDATES, BOT_USERNAME (для постов со ссылкой на бота),
ONLY (номера постов), DRY_RUN=1 — только проверить канал и показать план.
"""
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from posts import PINNED, POSTS  # noqa: E402

COVERS = Path(__file__).resolve().parent.parent / "covers"
TOKEN = os.environ["BOT_TOKEN"].strip()
API = f"https://api.telegram.org/bot{TOKEN}/"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def call(method: str, files=None, **params):
    r = requests.post(API + method, data=params, files=files, timeout=60)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('description')}")
    return data["result"]


def norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def candidates() -> list[str]:
    out = [c.strip() for c in env("CANDIDATES").split(",") if c.strip()]
    ch = env("CHANNEL")
    if ch.startswith("@") or "t.me/" in ch or ch.lstrip("-").isdigit():
        out.insert(0, ch)
    try:
        for u in call("getUpdates", limit=100, allowed_updates='["my_chat_member","channel_post"]'):
            chat = (u.get("my_chat_member") or u.get("channel_post") or {}).get("chat") or {}
            if chat.get("type") == "channel":
                out.append(str(chat["id"]))
    except Exception as e:  # у бота может стоять вебхук — тогда getUpdates недоступен
        print(f"getUpdates: {e}")
    seen, res = set(), []
    for c in out:
        c = "@" + c.rsplit("/", 1)[-1].lstrip("@") if "t.me/" in c else c
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res


def resolve() -> dict:
    me = call("getMe")
    print(f"Бот: @{me['username']}")
    query = norm(env("CHANNEL"))
    ok = []
    for c in candidates():
        try:
            chat = call("getChat", chat_id=c)
            member = call("getChatMember", chat_id=chat["id"], user_id=me["id"])
        except Exception as e:
            print(f"  {c}: недоступен ({e})")
            continue
        can = member.get("status") == "creator" or (member.get("status") == "administrator"
                                                    and member.get("can_post_messages"))
        print(f"  {c}: «{chat.get('title')}» @{chat.get('username') or '—'} — "
              f"{'может постить ✅' if can else 'нет права постить'}")
        if can and chat.get("type") == "channel":
            ok.append(chat)
    exact = [c for c in ok if query and (query in norm(c.get("title")) or query in norm(c.get("username")))]
    pick = exact or [c for c in ok if "halal" in norm(c.get("title")) + norm(c.get("username"))]
    if len(pick) != 1:
        sys.exit(f"Подходящих каналов: {len(pick)} — нужен ровно один. Ничего не отправлено.")
    return pick[0]


def render(p: dict, bot: str) -> str:
    return p.get("text", "").replace("{bot}", bot)


def main() -> None:
    bot = env("BOT_USERNAME").lstrip("@")
    only = {x.strip() for x in env("ONLY").split(",") if x.strip()}
    items = []
    for p in [PINNED] + POSTS:
        if only and str(p["id"]) not in only:
            continue
        if p.get("needs_bot") and not bot:
            print(f"— пост {p['id']}: пропущен (нет BOT_USERNAME, а в нём ссылка на бота)")
            continue
        items.append(p)
    chat = resolve()
    print(f"Канал: «{chat['title']}» (id {chat['id']}). Постов: {len(items)}")
    if env("DRY_RUN") == "1":
        print("DRY_RUN — ничего не отправлено.")
        return
    done = 0
    for p in items:
        try:
            if p.get("poll"):
                import json
                msg = call("sendPoll", chat_id=chat["id"], question=p["poll"]["question"],
                           options=json.dumps([{"text": a} for a in p["poll"]["answers"]], ensure_ascii=False),
                           is_anonymous="true")
            elif p.get("image") and (COVERS / p["image"]).exists():
                with open(COVERS / p["image"], "rb") as f:
                    msg = call("sendPhoto", files={"photo": f}, chat_id=chat["id"],
                               caption=render(p, bot), parse_mode="HTML")
            else:
                msg = call("sendMessage", chat_id=chat["id"], text=render(p, bot), parse_mode="HTML",
                           link_preview_options='{"is_disabled": true}')
            if p["id"] == "pin":
                call("pinChatMessage", chat_id=chat["id"], message_id=msg["message_id"],
                     disable_notification="true")
            done += 1
            print(f"✅ пост {p['id']} опубликован")
        except Exception as e:
            print(f"⚠️ пост {p['id']}: {e}")
        time.sleep(4)
    print(f"Готово: {done} из {len(items)}.")
    if done < len(items):
        sys.exit(1)


if __name__ == "__main__":
    main()

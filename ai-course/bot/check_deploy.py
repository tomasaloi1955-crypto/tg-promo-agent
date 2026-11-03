# -*- coding: utf-8 -*-
"""Проверка запуска бота (из GitHub Actions): вебхук, сервер Render, права в каналах."""
import os
import requests

T = os.environ["BOT_TOKEN"].strip()
API = f"https://api.telegram.org/bot{T}/"
COURSE = os.environ.get("COURSE_CHAT_ID", "").strip()
CHANNEL = os.environ.get("CHANNEL", "@Halalaifreya").strip()


def call(m, **p):
    return requests.post(API + m, data=p, timeout=30).json()


me = call("getMe")["result"]
print(f"Бот: @{me['username']} (id {me['id']})")
wh = call("getWebhookInfo")["result"]
url = wh.get("url") or ""
print(f"Вебхук: {url or '❌ не установлен (сервер не запустился или BOT_TOKEN на Render другой)'}")
print(f"  в очереди обновлений: {wh.get('pending_update_count')}")
if wh.get("last_error_message"):
    print(f"  ⚠️ последняя ошибка доставки: {wh['last_error_message']} (дата {wh.get('last_error_date')})")
base = url.rsplit("/webhook", 1)[0] if url else os.environ.get("BASE_URL", "https://neuropotok-bot.onrender.com")
for path in ("/health",):
    try:
        r = requests.get(base + path, timeout=120)
        print(f"Сервер {base}{path}: HTTP {r.status_code} {r.text[:60]!r}")
    except Exception as e:
        print(f"Сервер {base}{path}: ❌ {e}")
try:
    r = requests.get(base + "/tick?key=bad", timeout=60)
    print(f"Проверка /tick с неверным ключом: HTTP {r.status_code} (должно быть 403)")
except Exception as e:
    print(f"/tick: ❌ {e}")
for name, chat in (("Закрытый канал курса", COURSE), ("Канал", CHANNEL)):
    if not chat:
        continue
    c = call("getChat", chat_id=chat)
    if not c.get("ok"):
        print(f"{name} {chat}: ❌ {c.get('description')}")
        continue
    m = call("getChatMember", chat_id=chat, user_id=me["id"]).get("result", {})
    rights = [k for k in ("can_invite_users", "can_post_messages", "can_pin_messages") if m.get(k)]
    print(f"{name}: «{c['result'].get('title')}» — бот: {m.get('status')}, права: {', '.join(rights) or 'нет'}")

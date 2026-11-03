"""Получение YT_REFRESH_TOKEN для автопостинга на YouTube — прямо с телефона.

Запускается workflow «YouTube: авторизация» (Actions → Run workflow).
1. Бот пришлёт вам в Telegram ссылку google.com/device и код.
2. Откройте ссылку, войдите в Google, ВЫБЕРИТЕ КАНАЛ «Arabic for everyone», введите код, разрешите доступ.
3. Бот пришлёт refresh-токен — сохраните его в секрет YT_REFRESH_TOKEN (Settings → Secrets → Actions).

Нужны секреты YT_CLIENT_ID и YT_CLIENT_SECRET (OAuth-клиент типа «TVs and Limited Input devices»).
"""

import os
import sys
import time

import requests

cid, sec = os.environ.get("YT_CLIENT_ID"), os.environ.get("YT_CLIENT_SECRET")
token, owner = os.environ.get("BOT_TOKEN"), os.environ.get("OWNER_ID")
if not (cid and sec and token and owner):
    sys.exit("Нужны секреты YT_CLIENT_ID, YT_CLIENT_SECRET, BOT_TOKEN, OWNER_ID")


def tell(text):
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": owner, "text": text}, timeout=30)


r = requests.post("https://oauth2.googleapis.com/device/code",
                  data={"client_id": cid, "scope": "https://www.googleapis.com/auth/youtube"}, timeout=30)
r.raise_for_status()
dc = r.json()
tell(f"🔑 Авторизация YouTube\n\n1) Откройте: {dc['verification_url']}\n2) Введите код: {dc['user_code']}\n"
     f"3) Выберите канал «Arabic for everyone» и разрешите доступ.\n\nКод действует {dc['expires_in'] // 60} мин.")
print("Код отправлен в Telegram. Жду подтверждения…")

deadline = time.time() + dc["expires_in"]
interval = dc.get("interval", 5)
while time.time() < deadline:
    time.sleep(interval)
    t = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": sec, "device_code": dc["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=30).json()
    if "refresh_token" in t:
        print("::add-mask::" + t["refresh_token"])
        tell("✅ Готово! Скопируйте токен ниже и сохраните в GitHub → Settings → Secrets and variables → Actions → "
             "New repository secret с именем YT_REFRESH_TOKEN:")
        tell(t["refresh_token"])
        print("Токен отправлен в Telegram.")
        sys.exit(0)
    err = t.get("error")
    if err == "slow_down":
        interval += 5
    elif err not in ("authorization_pending",):
        tell(f"❌ Авторизация не удалась: {t}")
        sys.exit(f"Ошибка: {t}")
tell("⌛ Время на ввод кода истекло. Запустите workflow ещё раз.")
sys.exit(1)

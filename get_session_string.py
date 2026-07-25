# -*- coding: utf-8 -*-
"""
Разовая утилита: превращает файл сессии Telethon (userbot.session, из
tg-channel-agent) в строку (StringSession) — её кладут в секрет TELETHON_SESSION
на GitHub. Нужна, только если сессию нужно перевыпустить заново (например, она
слетела и пришлось логиниться в Telegram повторно).

Запуск (там, где лежит userbot.session — например, в Downloads/tg-channel-agent):
    python get_session_string.py

Выведет строку в консоль — скопируйте её и обновите секрет:
    gh secret set TELETHON_SESSION --repo <owner>/tg-promo-agent
(вставить строку и Enter, либо через --body "строка")

НЕ публикуйте эту строку нигде, кроме GitHub Secrets — она даёт полный доступ
к аккаунту Telegram, как и пароль.
"""
import os
import sys

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("API_ID") or input("API_ID: "))
API_HASH = os.environ.get("API_HASH") or input("API_HASH: ")
SESSION_NAME = sys.argv[1] if len(sys.argv) > 1 else "userbot"

with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
    print(StringSession.save(client.session))

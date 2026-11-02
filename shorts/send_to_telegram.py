"""Отправляет готовые ролики владельцу в Telegram (тот же бот, что и у промо-агента)."""

import os
import sys
from pathlib import Path

import requests

token, chat = os.environ.get("BOT_TOKEN"), os.environ.get("OWNER_ID")
if not token or not chat:
    print("BOT_TOKEN/OWNER_ID не заданы — пропускаю отправку в Telegram (видео есть в Artifacts).")
    sys.exit(0)

for path in sorted(Path(sys.argv[1] if len(sys.argv) > 1 else "out").glob("*.mp4")):
    with path.open("rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendVideo",
            data={"chat_id": chat, "caption": f"🎬 {path.stem} — готово для YouTube Shorts", "supports_streaming": "true"},
            files={"video": (path.name, f, "video/mp4")},
            timeout=300,
        )
    print(path.name, "→", "OK" if r.ok else r.text[:300])

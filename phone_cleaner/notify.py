# -*- coding: utf-8 -*-
"""
Куда отправить отчёт об уборке. Оба способа необязательные:
  * уведомление в шторке телефона — если установлен Termux:API (termux-notification);
  * сообщение в Telegram — если в ~/.phone_cleaner.env заданы BOT_TOKEN и OWNER_ID
    (тот же бот, что присылает отчёты промо-агента).
"""
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ENV_FILE = Path.home() / ".phone_cleaner.env"


def _env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
    env.update({k: os.environ[k] for k in ("BOT_TOKEN", "OWNER_ID") if os.environ.get(k)})
    return env


def send(text: str):
    if shutil.which("termux-notification"):
        first = text.splitlines()
        summary = next((l for l in first if l.startswith("Итого")), first[0])
        subprocess.run(["termux-notification", "--id", "phone-cleaner",
                        "--title", first[0], "--content", summary],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = _env()
    if env.get("BOT_TOKEN") and env.get("OWNER_ID"):
        data = urllib.parse.urlencode({"chat_id": env["OWNER_ID"], "text": text[:4000]}).encode()
        try:
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{env['BOT_TOKEN']}/sendMessage", data, timeout=20)
        except OSError:
            pass

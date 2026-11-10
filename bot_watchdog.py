"""Сторож бота бесплатной недели (@Sisters_training_bot, репозиторий sister-bot).

Раз в 2 часа (.github/workflows/bot_watchdog.yml) проверяет, что лиды из рекламы
попадают в живого бота, и пишет владелице в Telegram (BOT_TOKEN / OWNER_ID —
тот же бот, что присылает «Новый лид»), если что-то сломано:

  • сервис на Render не отвечает;
  • Telegram не принимает токен бота (как было 5–7.11: деплои падали);
  • база недоступна;
  • вебхук не задан, Telegram недавно не смог доставить сообщения, копится очередь;
  • на Render работает старая версия (последний деплой упал);
  • будильник «Бот тренировок: тик» в sister-bot падает;
  • реклама ведёт не в того бота.

Пока всё в порядке — молчит. Пока сломано — напоминает при каждой проверке.
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = os.getenv("OWNER_ID", "")

BOT_URL = os.getenv("SISTER_BOT_URL", "https://sister-bot-e5q4.onrender.com").rstrip("/")
REPO = "tomasaloi1955-crypto/sister-bot"
GH_TOKEN = os.getenv("GITHUB_TOKEN", "")
# Новый коммит в main должен оказаться на Render за это время, иначе деплой упал.
DEPLOY_GRACE_MIN = 40
WEBHOOK_ERROR_WINDOW_H = 3
PENDING_LIMIT = 30
TICK_STALE_MIN = 120
RESTART_GRACE_S = 600


def gh(path: str):
    headers = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"Bearer {GH_TOKEN}"
    r = requests.get(f"https://api.github.com/repos/{REPO}/{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def bot_status() -> tuple[dict | None, str | None]:
    """GET /status; первый запрос будит Render (до минуты-двух)."""
    last = ""
    for attempt in range(4):
        try:
            r = requests.get(f"{BOT_URL}/status", timeout=120)
            if r.status_code == 200:
                return r.json(), None
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(20)
    return None, last


def ad_bot_usernames() -> set[str]:
    """В какого бота ведут рекламные ссылки (promo.py / ad_scout.py: ?start=ad_…)."""
    names: set[str] = set()
    for f in ("promo.py", "ad_scout.py"):
        names |= {m.lower() for m in re.findall(r"t\.me/(\w+)\?start=ad_", (BASE / f).read_text(encoding="utf-8"))}
    return names


def notify(text: str) -> None:
    print(text)
    if not BOT_TOKEN or not OWNER_ID:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": OWNER_ID, "text": text, "disable_web_page_preview": True},
                      timeout=20)
    except Exception as e:
        print(f"  ! не удалось отправить уведомление: {e}")


def check() -> list[str]:
    problems: list[str] = []
    st, err = bot_status()
    if st is None:
        problems.append(f"Сервис на Render не отвечает ({err}). Лиды, которые нажмут /start, "
                        "не получат ответа. Render → sister-bot → Logs.")
    else:
        tg = st.get("telegram", "")
        if tg != "ok":
            hint = ("токен бота неверный — BotFather → @Sisters_training_bot → API Token → "
                    "Render → Environment → BOT_TOKEN" if "Unauthorized" in tg else tg)
            problems.append(f"Telegram не принимает бота: {hint}")
        else:
            if not st.get("webhook_set"):
                problems.append("У бота не задан вебхук — сообщения не доходят до сервера. "
                                "Render → Manual Deploy → Deploy latest commit.")
            at = st.get("webhook_error_at")
            # Ошибка в первые минуты после запуска — это переключение на новую версию
            # при деплое (Telegram стучался в старый процесс), не поломка.
            after_restart = at and st.get("started_at") and at <= st["started_at"] + RESTART_GRACE_S
            if at and not after_restart and time.time() - at < WEBHOOK_ERROR_WINDOW_H * 3600:
                when = datetime.fromtimestamp(at, timezone.utc).strftime("%d.%m %H:%M UTC")
                problems.append(f"Telegram не смог доставить сообщения боту ({when}): "
                                f"{st.get('webhook_error', '')}")
            if (st.get("pending") or 0) > PENDING_LIMIT:
                problems.append(f"У бота {st['pending']} необработанных сообщений — "
                                "сервер не успевает или падает.")
            username = (st.get("username") or "").lower()
            wrong = {u for u in ad_bot_usernames() if u != username}
            if username and wrong:
                problems.append(f"Реклама ведёт в @{', @'.join(sorted(wrong))}, а бот бесплатной "
                                f"недели — @{st['username']}.")
        if st.get("db") != "ok":
            problems.append(f"База бота недоступна: {st.get('db')}")
        else:
            # Будильник: с 10.11.2026 — GitHub (sister-bot/tick_loop.yml, «дежурный
            # будильник»): cron-job.org Render больше не пропускает. Ни одного тика 2 часа —
            # тренировки не уходят вовремя, бот спит и долго отвечает новеньким.
            ages = [st[k] for k in ("tick_cron_min_ago", "tick_github_min_ago") if k in st]
            print(f"  будильник: cron-job.org {st.get('tick_cron_min_ago', '—')} мин назад, "
                  f"GitHub {st.get('tick_github_min_ago', '—')} мин назад")
            if ages and min(ages) > TICK_STALE_MIN:
                problems.append(f"Будильник не будил бота уже {min(ages) // 60} ч: тренировки уходят не "
                                "вовремя. Claude перезапустит «дежурный будильник» на плановой проверке; "
                                "вручную: GitHub → sister-bot → Actions → «Бот тренировок: дежурный "
                                "будильник» → Run workflow.")

        # Версия на Render отстаёт от main → последний деплой упал.
        commit = st.get("commit") or ""
        try:
            head = gh("commits/main")
            sha = head["sha"]
            pushed = datetime.fromisoformat(head["commit"]["committer"]["date"].replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - pushed).total_seconds() / 60
            if commit and commit != sha and age_min > DEPLOY_GRACE_MIN:
                problems.append(f"На Render старая версия бота ({commit[:7]}), в GitHub — {sha[:7]} "
                                f"уже {int(age_min)} мин. Деплой упал: Render → sister-bot → "
                                "Events → нажмите на Failed и пришлите лог.")
        except Exception as e:
            print(f"  ! не проверил версию: {e}")

    # Будильник рассылки.
    try:
        runs = gh("actions/workflows/tick.yml/runs?per_page=3&status=completed")["workflow_runs"]
        if runs and runs[0]["conclusion"] not in ("success", "skipped", "cancelled"):
            problems.append(f"Будильник «Бот тренировок: тик» падает (последний запуск — "
                            f"{runs[0]['conclusion']}): тренировки уходят не вовремя. "
                            f"Лог: {runs[0]['html_url']}")
    except Exception as e:
        print(f"  ! не проверил будильник: {e}")
    return problems


def main() -> int:
    problems = check()
    if not problems:
        print("✅ Бот бесплатной недели в порядке.")
        return 0
    text = "🚨 Бот бесплатной недели (@Sisters_training_bot): что-то сломано\n\n" + \
           "\n\n".join(f"• {p}" for p in problems)
    notify(text)
    return 1


if __name__ == "__main__":
    sys.exit(main())

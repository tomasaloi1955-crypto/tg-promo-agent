"""Сторож всех сервисов на Render (кабинет My Workspace) — сам чинит, что может.

Запуск:
    python fleet_watchdog.py           # только проверить
    python fleet_watchdog.py --fix     # проверить и починить, что чинится само
    python fleet_watchdog.py --fix --wait   # …и дождаться, что починка сработала

Ключ Render берётся из RENDER_API_KEY; в облачной сессии Claude его подставляет
прокси сам (тогда переменная не нужна).

Список сервисов берётся из Render, поэтому новые сервисы попадают под присмотр
сами. Сторож не будит спящие бесплатные сервисы (в сами боты не стучится) —
смотрит только Render API, чтобы не тратить общие 750 бесплатных часов.

Что чинит сам:
  • деплой упал из-за сбоя Render/GitHub/сети (не смог скачать код, таймаут…) —
    запускает деплой заново (не больше 2 раз на один коммит);
  • деплой завис дольше 45 минут — отменяет и запускает заново;
  • бот упал во время работы и не поднялся — перезапускает (раз в 6 часов).

  (будильники cron-job.org — проверяет, что срабатывают)

Что только сообщает (нужен человек или Claude, чтобы поправить код):
  • деплой падает из-за ошибки в коде;
  • сервис приостановлен (кончились бесплатные часы и т. п.);
  • бот падает снова и снова после перезапуска;
  • свежие ошибки в логах — как подсказку.

Код выхода: 0 — всё в порядке (или всё починено), 1 — осталось, что чинить.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.render.com/v1"
# Пусто — проверять все кабинеты (workspaces), которые видит ключ.
OWNER_ID = os.getenv("RENDER_OWNER_ID", "")
KEY = os.getenv("RENDER_API_KEY", "")

IN_PROGRESS = {"created", "queued", "build_in_progress", "update_in_progress", "pre_deploy_in_progress"}
FAILED = {"build_failed", "update_failed", "pre_deploy_failed"}
STUCK_MIN = 45
MAX_RETRIES_PER_COMMIT = 2
CRASH_WINDOW_H = 6
ERROR_LOG_WINDOW_H = 3

# Признаки сбоя не в коде, а у Render / GitHub / сети — такое лечится повтором.
TRANSIENT = re.compile(
    r"Unable to clone|could not read Username|don't have access to your repo|"
    r"Could not resolve host|Temporary failure in name resolution|Connection reset|"
    r"Connection timed out|Read timed out|ReadTimeoutError|timed out|"
    r"502 Bad Gateway|503 Service Unavailable|504 Gateway|Internal Server Error|"
    r"HTTP error 5\d\d|rate limit|Too Many Requests|"
    r"Failed to download|unexpected EOF|TLS handshake|"
    r"exceeded the maximum time|build timed out|"
    r"No open ports detected|Port scan timeout",
    re.I,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def api(method: str, path: str, **kw):
    headers = {"Accept": "application/json"}
    if KEY:
        headers["Authorization"] = f"Bearer {KEY}"
    for attempt in range(3):
        try:
            r = requests.request(method, f"{API}{path}", headers=headers, timeout=40, **kw)
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json() if r.content else {}
    r.raise_for_status()


def services() -> list[dict]:
    owners = [OWNER_ID] if OWNER_ID else [o["owner"]["id"] for o in api("GET", "/owners?limit=100")]
    out = []
    for oid in owners:
        for item in api("GET", f"/services?limit=100&ownerId={oid}"):
            out.append(item["service"])
    return out


def deploys(sid: str, n: int = 8) -> list[dict]:
    return [d["deploy"] for d in api("GET", f"/services/{sid}/deploys?limit={n}")]


def events(sid: str, n: int = 60) -> list[dict]:
    return [e["event"] for e in api("GET", f"/services/{sid}/events?limit={n}")]


SERVICE_OWNER: dict[str, str] = {}


def logs(sid: str, start: datetime, end: datetime, kind: str | None = None,
         level: str | None = None, limit: int = 100) -> list[str]:
    params = {
        "ownerId": SERVICE_OWNER.get(sid, OWNER_ID), "resource": sid, "limit": limit, "direction": "backward",
        "startTime": start.isoformat().replace("+00:00", "Z"),
        "endTime": end.isoformat().replace("+00:00", "Z"),
    }
    if kind:
        params["type"] = kind
    if level:
        params["level"] = level
    data = api("GET", "/logs", params=params)
    return [re.sub(r"\x1b\[[0-9;]*m|\x1b\(B", "", l["message"]) for l in reversed(data.get("logs", []))]


def deploy_window(d: dict) -> tuple[datetime, datetime]:
    start = ts(d.get("startedAt")) or ts(d.get("createdAt")) or now() - timedelta(hours=1)
    end = (ts(d.get("finishedAt")) or now()) + timedelta(minutes=2)
    return start - timedelta(minutes=1), end


def tail(lines: list[str], n: int = 12) -> str:
    keep = [l for l in lines if l.strip()]
    return "\n".join(keep[-n:])


class Report:
    def __init__(self):
        self.fixed: list[str] = []
        self.problems: list[str] = []
        self.warnings: list[str] = []
        self.ok: list[str] = []
        self.to_wait: list[tuple[str, str, str]] = []  # (service id, name, deploy id)


def check_service(s: dict, fix: bool, rep: Report) -> None:
    sid, name = s["id"], s["name"]
    SERVICE_OWNER[sid] = s["ownerId"]
    repo = (s.get("repo") or "").replace("https://github.com/", "")
    where = f"{name} ({repo}, ветка {s.get('branch')})" if repo else name
    plan = (s.get("serviceDetails") or {}).get("plan", "")

    # 1. Приостановлен.
    if s.get("suspended") == "suspended":
        who = ", ".join(s.get("suspenders") or []) or "неизвестно кем"
        if "user" in who.lower() and len(s.get("suspenders") or []) == 1:
            rep.ok.append(f"{name}: выключен вручную (так и задумано)")
            return
        rep.problems.append(
            f"{where}: сервис ПРИОСТАНОВЛЕН Render ({who}). Если это «Free Tier Usage Exceeded» — "
            "кончились 750 бесплатных часов на месяц; бот оживёт 1-го числа или после перевода "
            "на платный план (Render → сервис → Settings → Instance Type).")
        return

    ds = deploys(sid)
    if not ds:
        rep.problems.append(f"{where}: ни одного деплоя.")
        return
    latest = ds[0]
    live = next((d for d in ds if d["status"] == "live"), None)
    status = latest["status"]
    commit = (latest.get("commit") or {}).get("id", "")[:7]

    # 2. Деплой идёт / завис.
    if status in IN_PROGRESS:
        started = ts(latest.get("startedAt")) or ts(latest.get("createdAt")) or now()
        mins = (now() - started).total_seconds() / 60
        if mins < STUCK_MIN:
            rep.ok.append(f"{name}: идёт деплой {commit} ({int(mins)} мин)")
            rep.to_wait.append((sid, name, latest["id"]))
            return
        if fix:
            try:
                api("POST", f"/services/{sid}/deploys/{latest['id']}/cancel")
            except Exception as e:
                print(f"  ! {name}: не отменил зависший деплой: {e}")
            new = api("POST", f"/services/{sid}/deploys", json={"clearCache": "do_not_clear"})
            rep.fixed.append(f"{name}: деплой {commit} завис на {int(mins)} мин — отменила и запустила заново")
            rep.to_wait.append((sid, name, new.get("id", "")))
        else:
            rep.problems.append(f"{where}: деплой {commit} висит уже {int(mins)} мин.")
        return

    # 3. Последний деплой упал.
    if status in FAILED:
        start, end = deploy_window(latest)
        lines = logs(sid, start, end, kind="build") or []
        if status != "build_failed":
            lines += logs(sid, start, end, kind="app")
        text = "\n".join(lines)
        same_commit_fails = sum(
            1 for d in ds
            if d["status"] in FAILED and (d.get("commit") or {}).get("id", "")[:7] == commit)
        transient = bool(TRANSIENT.search(text)) or not text.strip()
        old = f" (сейчас работает старая версия {(live.get('commit') or {}).get('id', '')[:7]})" if live else \
              " (живой версии нет — бот не работает!)"
        if transient and same_commit_fails <= MAX_RETRIES_PER_COMMIT and fix:
            new = api("POST", f"/services/{sid}/deploys", json={"clearCache": "do_not_clear"})
            rep.fixed.append(f"{name}: деплой {commit} упал из-за сбоя Render/GitHub — запустила заново{old}")
            rep.to_wait.append((sid, name, new.get("id", "")))
            return
        reason = "сбой Render/GitHub, повтор не помог" if transient else "ошибка в коде или настройках"
        rep.problems.append(
            f"{where}: деплой {commit} упал ({status}, {reason}){old}.\n"
            f"Конец лога сборки:\n{tail(lines, 15)}")
        return

    # 4. Работает, но падает.
    evs = events(sid)
    recent = [e for e in evs if ts(e["timestamp"]) > now() - timedelta(hours=CRASH_WINDOW_H)]
    last_state = next((e for e in evs if e["type"] in
                       ("server_failed", "server_available", "deploy_ended", "server_restarted",
                        "service_resumed")), None)
    crashes = [e for e in recent if e["type"] == "server_failed"]
    if last_state and last_state["type"] == "server_failed":
        when = ts(last_state["timestamp"])
        crash_logs = logs(sid, when - timedelta(minutes=5), when + timedelta(minutes=1), kind="app")
        restarted_recently = any(e["type"] in ("server_restarted",) for e in recent)
        if fix and not restarted_recently and when > now() - timedelta(hours=CRASH_WINDOW_H):
            api("POST", f"/services/{sid}/restart")
            rep.fixed.append(f"{name}: бот упал ({when:%d.%m %H:%M} UTC) и не поднялся — перезапустила")
            rep.warnings.append(f"{name}: перед падением в логе:\n{tail(crash_logs, 10)}")
            return
        rep.problems.append(
            f"{where}: бот упал {when:%d.%m %H:%M} UTC и не поднялся"
            f"{' (перезапуск уже был — не помог)' if restarted_recently else ''}.\n"
            f"Лог перед падением:\n{tail(crash_logs, 15)}")
        return
    if len(crashes) >= 3:
        rep.warnings.append(f"{name}: за {CRASH_WINDOW_H} ч падал {len(crashes)} раз(а), но поднимался сам.")

    # 5. Свежие ошибки в логах — подсказка.
    try:
        errs = logs(sid, now() - timedelta(hours=ERROR_LOG_WINDOW_H), now(), kind="app",
                    level="error", limit=50)
    except Exception:
        errs = []
    if errs:
        uniq: list[str] = []
        for line in errs:
            key = re.sub(r"^\S+ \S+ ", "", line)[:160]
            if key not in uniq:
                uniq.append(key)
        rep.warnings.append(f"{name}: {len(errs)} ошибок в логе за {ERROR_LOG_WINDOW_H} ч, например:\n"
                            + "\n".join(f"  {u}" for u in uniq[:4]))

    note = f", план {plan}" if plan and plan != "free" else ""
    rep.ok.append(f"{name}: работает, версия {(live or latest).get('commit', {}).get('id', '')[:7]}{note}")


def wait_deploys(rep: Report, minutes: int = 20) -> None:
    pending = {d for d in rep.to_wait if d[2]}
    deadline = time.time() + minutes * 60
    while pending and time.time() < deadline:
        time.sleep(30)
        for sid, name, did in list(pending):
            d = api("GET", f"/services/{sid}/deploys/{did}")
            st = d.get("status")
            if st in IN_PROGRESS:
                continue
            pending.discard((sid, name, did))
            if st == "live":
                rep.fixed.append(f"{name}: ✅ новая версия живая ({(d.get('commit') or {}).get('id', '')[:7]})")
            else:
                start, end = deploy_window(d)
                rep.problems.append(f"{name}: повторный деплой тоже не удался ({st}).\n"
                                    f"{tail(logs(sid, start, end, kind='build'), 15)}")
    for sid, name, did in pending:
        rep.problems.append(f"{name}: деплой {did} не закончился за {minutes} мин.")


def check_cron_jobs(rep: Report) -> None:
    """Будильники на cron-job.org (ключ подставляет прокси или CRONJOB_API_KEY)."""
    headers = {}
    if os.getenv("CRONJOB_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['CRONJOB_API_KEY']}"
    try:
        r = requests.get("https://api.cron-job.org/jobs", headers=headers, timeout=30)
        if r.status_code in (401, 403):
            print("  (cron-job.org: нет ключа — будильники не проверены)")
            return
        r.raise_for_status()
        jobs = r.json().get("jobs", [])
    except Exception as e:
        print(f"  ! cron-job.org не проверен: {e}")
        return
    for j in jobs:
        if not j.get("enabled"):
            continue  # выключен вручную
        title = j.get("title") or re.sub(r"key=[^&]+", "key=…", j["url"])
        try:
            hist = requests.get(f"https://api.cron-job.org/jobs/{j['jobId']}/history",
                                headers=headers, timeout=30).json().get("history", [])
        except Exception:
            hist = []
        recent = hist[:3]
        # status 1 = успех; остальное — ошибка (503, таймаут и т. п.)
        if len(recent) >= 2 and all(h.get("status") != 1 for h in recent):
            codes = ", ".join(str(h.get("httpStatus") or h.get("status")) for h in recent)
            rep.problems.append(f"Будильник cron-job.org «{title}» не срабатывает {len(recent)} раза подряд "
                                f"(ответы: {codes}).")
        else:
            rep.ok.append(f"будильник «{title}»: работает")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="чинить, что чинится само")
    ap.add_argument("--wait", action="store_true", help="дождаться окончания запущенных деплоев")
    ap.add_argument("--json", action="store_true", help="вывести итог в JSON")
    ap.add_argument("--notify", action="store_true",
                    help="прислать итог в Telegram (BOT_TOKEN/OWNER_ID), если что-то починено или сломано")
    ap.add_argument("--label", default="", help="подпись кабинета в уведомлении")
    ap.add_argument("--no-cron", action="store_true", help="не проверять cron-job.org")
    args = ap.parse_args()

    rep = Report()
    for s in services():
        try:
            check_service(s, args.fix, rep)
        except Exception as e:
            rep.problems.append(f"{s['name']}: сторож не смог проверить ({type(e).__name__}: {e})")
    if not args.no_cron:
        check_cron_jobs(rep)
    if args.wait:
        wait_deploys(rep)

    if args.json:
        print(json.dumps({"fixed": rep.fixed, "problems": rep.problems, "warnings": rep.warnings,
                          "ok": rep.ok}, ensure_ascii=False, indent=2))
    else:
        for title, items in (("🔧 Починила сама", rep.fixed), ("🚨 Нужно чинить", rep.problems),
                             ("⚠️ Обратить внимание", rep.warnings), ("✅ В порядке", rep.ok)):
            if items:
                print(f"\n{title}:")
                for i in items:
                    print("• " + i.replace("\n", "\n    "))
    if args.notify and (rep.fixed or rep.problems):
        notify_telegram(rep, args.label)
    return 1 if rep.problems else 0


def notify_telegram(rep: Report, label: str) -> None:
    token, chat = os.getenv("BOT_TOKEN", ""), os.getenv("OWNER_ID", "")
    if not token or not chat:
        return
    parts = [f"🛡 Сторож Render{(' — ' + label) if label else ''}"]
    if rep.fixed:
        parts.append("🔧 Починила сама:\n" + "\n".join("• " + i.split("\n")[0] for i in rep.fixed))
    if rep.problems:
        parts.append("🚨 Нужно чинить (Claude посмотрит на плановой проверке):\n"
                     + "\n".join("• " + i.split("\n")[0] for i in rep.problems))
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": "\n\n".join(parts)[:4000],
                            "disable_web_page_preview": True}, timeout=20)
    except Exception as e:
        print(f"  ! не отправила в Telegram: {e}")


if __name__ == "__main__":
    sys.exit(main())

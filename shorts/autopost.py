"""Автопостинг Shorts: YouTube («Arabic for everyone»), Telegram-канал и Instagram Reels.

Раз в день (GitHub Actions, .github/workflows/autopost.yml) публикует ОДИН ролик,
чередуя:
  • день A — «старый» шортс со словами из очереди (папка shorts/old/ и/или чат-хранилище в Telegram);
  • день B — новый мультик-диалог (shorts/episodes/dialog_NNN.json, собирается с озвучкой).
Если старые закончились — каждый день идут новые.

Что куда публикуется, решают секреты: нет секретов платформы — она пропускается.
  YouTube:   YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN  (получить: workflow «YouTube: авторизация»)
  Telegram:  API_ID, API_HASH, TELETHON_SESSION (уже есть у промо-агента) + TG_CHANNEL (например myarabicl)
  Instagram: IG_USER_ID, IG_ACCESS_TOKEN (+ IG_GRAPH_HOST, по умолчанию graph.instagram.com)
Отчёт о каждом запуске приходит владельцу от бота (BOT_TOKEN, OWNER_ID).

Память — shorts/autopost_state.json (какой ролик следующий, что уже опубликовано).

Запуск:  python shorts/autopost.py            (опубликовать ролик дня)
         python shorts/autopost.py --dry-run  (только показать, что было бы опубликовано)
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STATE = HERE / "autopost_state.json"
OLD_DIR = HERE / "old"
OUT = HERE.parent / "out"

HASHTAGS = "#арабский #арабскийязык #учимарабский #arabic #learnarabic #shorts"


# ─────────────────────────── память ───────────────────────────

def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"next_new": 1, "old_done": [], "last_kind": "new", "history": []}


def save_state(st: dict):
    st["history"] = st["history"][-200:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def notify(text: str):
    token, chat = os.getenv("BOT_TOKEN"), os.getenv("OWNER_ID")
    print(text)
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}, timeout=30)
        except Exception as e:  # noqa: BLE001
            print("notify failed:", e)


# ─────────────────────────── что публикуем сегодня ───────────────────────────

def old_queue_local(st) -> list[Path]:
    if not OLD_DIR.exists():
        return []
    files = sorted(p for p in OLD_DIR.iterdir() if p.suffix.lower() in (".mp4", ".mov"))
    return [p for p in files if f"file:{p.name}" not in st["old_done"]]


def old_titles() -> dict:
    f = OLD_DIR / "titles.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


async def _tg_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    c = TelegramClient(StringSession(os.environ["TELETHON_SESSION"]), int(os.environ["API_ID"]), os.environ["API_HASH"])
    await c.connect()
    return c


async def old_from_telegram(st, dest: Path) -> dict | None:
    """Следующее видео из чата-хранилища TG_OLD_SOURCE (по порядку, от старых к новым)."""
    src = os.getenv("TG_OLD_SOURCE")
    if not src or not os.getenv("TELETHON_SESSION"):
        return None
    c = await _tg_client()
    try:
        async for m in c.iter_messages(src, reverse=True):
            if not m.video:
                continue
            key = f"tg:{src}:{m.id}"
            if key in st["old_done"]:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            await c.download_media(m, file=str(dest))
            return {"key": key, "path": dest, "caption": (m.message or "").strip()}
    finally:
        await c.disconnect()
    return None


def pick_today(st, dry=False) -> dict:
    want_old = st.get("last_kind") == "new"
    if want_old:
        local = old_queue_local(st)
        if local:
            p = local[0]
            cap = old_titles().get(p.name, "")
            return {"kind": "old", "key": f"file:{p.name}", "path": p, "caption": cap}
        if not dry:
            item = asyncio.run(old_from_telegram(st, OUT / "old_today.mp4"))
            if item:
                item["kind"] = "old"
                return item
    n = st["next_new"]
    spec = HERE / "episodes" / f"dialog_{n:03d}.json"
    if not spec.exists():
        return {"kind": "none"}
    return {"kind": "new", "key": f"dialog:{n}", "n": n, "spec": spec}


# ─────────────────────────── тексты публикации ───────────────────────────

def texts_for(item) -> dict:
    tg_link = f"https://t.me/{os.getenv('TG_CHANNEL').lstrip('@')}" if os.getenv("TG_CHANNEL") else ""
    if item["kind"] == "new":
        spec = json.loads(Path(item["spec"]).read_text(encoding="utf-8"))
        topic = spec["title"].split(":", 1)[-1].replace("*", "").strip()
        lines = []
        for b in spec["beats"]:
            if "say" in b:
                who = spec["characters"][b["say"]]["name"]
                lines.append(f"{who}: {b['ar'].replace('*', '')}\n   {b['tr'].replace('*', '')} — {b['ru'].replace('*', '')}")
            if "quiz" in b:
                q = b["quiz"]
                lines.append(f"\n❓ Как сказать «{q['ru']}»? Ответ: {q['ar']} ({q['tr']})")
        body = "\n".join(lines)
        title = f"Урок {item['n']}: {topic} — арабский за 20 секунд"
    else:
        cap = item.get("caption") or ""
        title = (cap.splitlines()[0] if cap else "Арабские слова") [:80]
        body = cap
    yt_title = (title[:90] + " #shorts") if "#shorts" not in title else title[:100]
    yt_desc = f"{body}\n\nПовтори вслух и подпишись — арабский каждый день!\n{('Telegram: ' + tg_link) if tg_link else ''}\n\n{HASHTAGS}"
    social = f"🎬 {title}\n\n{body}\n\nПовтори вслух! 🔁\n\n{HASHTAGS}"
    return {"yt_title": yt_title.strip(), "yt_desc": yt_desc.strip()[:4900], "tg": social[:1000], "ig": social[:2100]}


# ─────────────────────────── YouTube ───────────────────────────

def youtube_upload(path: Path, title: str, desc: str) -> str:
    cid, sec, rt = os.getenv("YT_CLIENT_ID"), os.getenv("YT_CLIENT_SECRET"), os.getenv("YT_REFRESH_TOKEN")
    if not (cid and sec and rt):
        raise SkipPlatform("нет секретов YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN")
    tok = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": sec, "refresh_token": rt, "grant_type": "refresh_token"}, timeout=30)
    tok.raise_for_status()
    access = tok.json()["access_token"]
    meta = {
        "snippet": {"title": title, "description": desc, "categoryId": "27", "defaultLanguage": "ru",
                    "tags": ["арабский", "арабский язык", "учим арабский", "arabic", "learn arabic", "shorts"]},
        "status": {"privacyStatus": os.getenv("YT_PRIVACY", "public"),
                   "selfDeclaredMadeForKids": os.getenv("YT_MADE_FOR_KIDS", "false").lower() == "true"},
    }
    size = path.stat().st_size
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      data=json.dumps(meta), timeout=60)
    r.raise_for_status()
    with path.open("rb") as f:
        up = requests.put(r.headers["Location"], headers={"Authorization": f"Bearer {access}", "Content-Type": "video/mp4"},
                          data=f, timeout=600)
    up.raise_for_status()
    vid = up.json()["id"]
    return f"https://youtube.com/shorts/{vid}"


# ─────────────────────────── Telegram-канал ───────────────────────────

def telegram_post(path: Path, caption: str) -> str:
    ch = os.getenv("TG_CHANNEL")
    if not ch or not os.getenv("TELETHON_SESSION"):
        raise SkipPlatform("нет TG_CHANNEL или TELETHON_SESSION")

    async def run():
        from telethon.tl.types import DocumentAttributeVideo

        c = await _tg_client()
        try:
            dur = video_duration(path)
            msg = await c.send_file(ch, str(path), caption=caption, supports_streaming=True,
                                    attributes=[DocumentAttributeVideo(duration=int(dur), w=1080, h=1920, supports_streaming=True)])
            return f"https://t.me/{ch.lstrip('@')}/{msg.id}"
        finally:
            await c.disconnect()

    return asyncio.run(run())


# ─────────────────────────── Instagram Reels ───────────────────────────

def instagram_post(path: Path, caption: str) -> str:
    uid, token = os.getenv("IG_USER_ID"), os.getenv("IG_ACCESS_TOKEN")
    if not (uid and token):
        raise SkipPlatform("нет IG_USER_ID / IG_ACCESS_TOKEN")
    host = os.getenv("IG_GRAPH_HOST", "graph.instagram.com")
    ver = os.getenv("IG_API_VERSION", "v21.0")
    base = f"https://{host}/{ver}"
    r = requests.post(f"{base}/{uid}/media", data={"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                                                 "share_to_feed": "true", "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"создание контейнера: {r.status_code} {r.text[:300]}")
    cont = r.json()["id"]
    size = path.stat().st_size
    with path.open("rb") as f:
        up = requests.post(f"https://rupload.facebook.com/ig-api-upload/{ver}/{cont}",
                           headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}, data=f, timeout=600)
    if not up.ok:
        raise RuntimeError(f"загрузка видео: {up.status_code} {up.text[:300]}")
    for _ in range(60):  # ждём обработку до ~10 минут
        st = requests.get(f"{base}/{cont}", params={"fields": "status_code,status", "access_token": token}, timeout=30).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram не принял видео: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram слишком долго обрабатывает видео")
    pub = requests.post(f"{base}/{uid}/media_publish", data={"creation_id": cont, "access_token": token}, timeout=60)
    if not pub.ok:
        raise RuntimeError(f"публикация: {pub.status_code} {pub.text[:300]}")
    mid = pub.json().get("id")
    try:
        link = requests.get(f"{base}/{mid}", params={"fields": "permalink", "access_token": token}, timeout=30).json().get("permalink")
    except Exception:  # noqa: BLE001
        link = None
    return link or f"media {mid}"


# ─────────────────────────── общее ───────────────────────────

class SkipPlatform(Exception):
    pass


def video_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def render_new(item) -> Path:
    sys.path.insert(0, str(HERE))
    import make_short

    voice = make_short.Voice(True, HERE / ".tts_cache")
    # Проверяем, что озвучка работает, ДО сборки — немой ролик не публикуем
    if voice.say("مرحبا", "ar-SA-HamedNeural") is None:
        raise RuntimeError("озвучка недоступна — немой ролик публиковать не будем")
    return make_short.render(Path(item["spec"]), OUT, use_voice=True, strict_voice=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="опубликовать только на платформы: youtube,telegram,instagram")
    args = ap.parse_args()

    st = load_state()
    item = pick_today(st, args.dry_run)
    if item["kind"] == "none":
        notify("📭 Автопостинг: все 100 уроков и старые ролики уже опубликованы. Добавьте новые!")
        return
    print("Сегодня:", item["kind"], item.get("key"))
    if args.dry_run:
        print(json.dumps(texts_for(item), ensure_ascii=False, indent=1))
        return

    try:
        path = render_new(item) if item["kind"] == "new" else Path(item["path"])
    except Exception as e:  # noqa: BLE001
        notify(f"❌ Автопостинг: не удалось подготовить видео ({item.get('key')}): {e}")
        raise
    tx = texts_for(item)

    platforms = {
        "youtube": lambda: youtube_upload(path, tx["yt_title"], tx["yt_desc"]),
        "telegram": lambda: telegram_post(path, tx["tg"]),
        "instagram": lambda: instagram_post(path, tx["ig"]),
    }
    only = set(args.only.split(",")) if args.only else None
    results, ok = {}, 0
    for name, fn in platforms.items():
        if only and name not in only:
            continue
        try:
            results[name] = "✅ " + fn()
            ok += 1
        except SkipPlatform as e:
            results[name] = f"⏭ пропущено: {e}"
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            results[name] = f"❌ {type(e).__name__}: {str(e)[:300]}"

    if ok:  # двигаем очередь, только если опубликовали хотя бы куда-то
        if item["kind"] == "new":
            st["next_new"] = item["n"] + 1
        else:
            st["old_done"].append(item["key"])
        st["last_kind"] = item["kind"]
        st["history"].append({"date": dt.date.today().isoformat(), "key": item["key"],
                              "results": {k: v[:200] for k, v in results.items()}})
        save_state(st)

    kind = "новый урок" if item["kind"] == "new" else "старый шортс"
    notify(f"🎬 Автопостинг ({kind}): {tx['yt_title']}\n\n" + "\n".join(f"{k}: {v}" for k, v in results.items()))
    if not ok and any(v.startswith("❌") for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()

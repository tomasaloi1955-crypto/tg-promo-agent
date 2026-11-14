"""Автопостинг Shorts: YouTube («Arabic for everyone»), Telegram-канал и Instagram Reels.

Раз в день (GitHub Actions, .github/workflows/autopost.yml) публикует ОДИН ролик,
чередуя:
  • день A — «старый» шортс со словами из очереди (папка shorts/old/ и/или чат-хранилище в Telegram);
  • день B — новый мультик-диалог (shorts/episodes/dialog_NNN.json, собирается с озвучкой).
Если старые закончились — каждый день идут новые.

Что куда публикуется, решают секреты: нет секретов платформы — она пропускается.
  YouTube:   YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN  (получить: workflow «YouTube: авторизация»)
  Telegram:  API_ID, API_HASH, TELETHON_SESSION (уже есть у промо-агента) + TG_CHANNEL (например myarabicl)
             + TG_CHANNEL_2 — второй канал с тем же роликом (tamra_school)
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
KINDS = "both"  # both — через день слово/диалог; new — только диалоги
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


def bot_username() -> str:
    """Имя бота-уведомителя (из BOT_TOKEN) — чтобы владелица знала, кого назначить админом канала."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        return ""
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
        return "@" + r["result"]["username"] if r.get("ok") else ""
    except Exception:  # noqa: BLE001
        return ""


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


def promo_today(st) -> dict | None:
    """Раз в неделю (по умолчанию в субботу) — рекламный мультик «как записаться на курс»."""
    import courses

    today = dt.date.today()
    year, week, _ = today.isocalendar()
    key = f"promo:{year}-{week:02d}"
    if any(h.get("key") == key for h in st.get("history", [])):
        return None
    if KINDS != "promo" and today.weekday() != int(os.getenv("PROMO_WEEKDAY", "5")):
        return None
    course = courses.promo_course(week)
    if not course:
        return None
    return {"kind": "promo", "key": key, "n": week, "course": course}


def pick_today(st, dry=False) -> dict:
    promo = promo_today(st)
    if promo:
        return promo
    if KINDS == "promo":
        return {"kind": "none"}
    if KINDS == "new":  # только уроки-диалоги (например, для YouTube, где «Слово дня» уже есть)
        n = st.get("next_new", 1)
        spec = HERE / "episodes" / f"dialog_{n:03d}.json"
        return {"kind": "new", "key": f"dialog:{n}", "n": n, "spec": spec} if spec.exists() else {"kind": "none"}
    want_old = st.get("last_kind") == "new"  # вчера был диалог → сегодня старый ролик или «Слово дня»
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
        # день «Слова дня»
        w = st.get("next_word", 1)
        spec = HERE / "episodes" / f"word_{w:03d}.json"
        if spec.exists():
            return {"kind": "word", "key": f"word:{w}", "n": w, "spec": spec}
    n = st["next_new"]
    spec = HERE / "episodes" / f"dialog_{n:03d}.json"
    if spec.exists():
        return {"kind": "new", "key": f"dialog:{n}", "n": n, "spec": spec}
    w = st.get("next_word", 1)  # диалоги кончились — идут слова
    spec = HERE / "episodes" / f"word_{w:03d}.json"
    if spec.exists():
        return {"kind": "word", "key": f"word:{w}", "n": w, "spec": spec}
    return {"kind": "none"}


# ─────────────────────────── тексты публикации ───────────────────────────

def texts_for(item) -> dict:
    tg_link = f"https://t.me/{os.getenv('TG_CHANNEL').lstrip('@')}" if os.getenv("TG_CHANNEL") else ""
    if item["kind"] == "promo":
        import courses

        c = courses.COURSES[item["course"]]
        title = f"Как записаться на курс «{c['name']}» — 3 шага"
        body = ("1️⃣ На YouTube нажми на название канала внизу видео\n"
                "2️⃣ Открой ссылку в описании канала\n"
                f"3️⃣ {c['pay_text']}\n"
                "В Telegram — ссылка прямо под этим постом 👇\n\n"
                + "\n".join("✅ " + b for b in c["bullets"]))
    elif item["kind"] in ("new", "word"):
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
        if item["kind"] == "word":
            q = next(b["quiz"] for b in spec["beats"] if "quiz" in b)
            title = f"Слово дня: {q['ar']} — «{q['ru']}» | арабский за 15 секунд"
        else:
            title = f"Урок {item['n']}: {topic} — арабский за 20 секунд"
    else:
        cap = item.get("caption") or ""
        title = (cap.splitlines()[0] if cap else "Арабские слова") [:80]
        body = cap
    yt_title = (title[:90] + " #shorts") if "#shorts" not in title else title[:100]
    import courses

    if item["kind"] == "promo":
        ck = item["course"]
    else:
        ck = courses.course_for(item["kind"]) if item["kind"] in ("new", "word") else courses.course_for("word")
    block = courses.description_block(ck)
    yt_desc = (f"{block}\n{body}\n\nПовтори вслух и подпишись — арабский каждый день!\n"
               f"{('Telegram: ' + tg_link) if tg_link else ''}\n\n{HASHTAGS}")
    # Telegram: ссылки на курс кликаются прямо в подписи; подпись к видео — до 1024 символов
    tg_tail = f"\n\n{block}" if item["kind"] == "promo" else f"\n\nПовтори вслух! 🔁\n\n{block}"
    tg = f"🎬 {title}\n\n{body}"
    tg = (tg[: 1020 - len(tg_tail)] + tg_tail) if len(tg) + len(tg_tail) > 1020 else tg + tg_tail
    rep_line = "" if item["kind"] == "promo" else "\n\nПовтори вслух! 🔁"
    ig = f"🎬 {title}\n\n{body}{rep_line}\n\n{courses.social_line(ck)}\n\n{HASHTAGS}"
    return {"yt_title": yt_title.strip(), "yt_desc": yt_desc.strip()[:4900], "tg": tg.strip(), "ig": ig[:2100]}


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

def telegram_post(path: Path, caption: str, ch_env: str = "TG_CHANNEL", skip_env: str = "TG_SKIP_WEEKDAYS",
                  skip_default: str = "2,6", skip_why: str = "сегодня в канале текстовый пост, ролик — завтра") -> str:
    ch = os.getenv(ch_env)
    if not ch:
        raise SkipPlatform(f"нет {ch_env}")
    # В эти дни в канал пишет текстовый автопостинг (pilatesbot: ср и вс) — роликом не мешаем.
    skip = {int(x) for x in os.getenv(skip_env, skip_default).split(",") if x.strip()}
    if dt.date.today().weekday() in skip:
        raise SkipPlatform(skip_why)

    # 1) Бот (BOT_TOKEN) — должен быть админом канала с правом «Публикация сообщений».
    token = os.getenv("BOT_TOKEN")
    bot_err = None
    if token:
        chat = ch if ch.startswith("@") or ch.lstrip("-").isdigit() else "@" + ch
        with path.open("rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo",
                              data={"chat_id": chat, "caption": caption, "supports_streaming": "true",
                                    "width": 1080, "height": 1920, "duration": int(video_duration(path))},
                              files={"video": (path.name, f, "video/mp4")}, timeout=300).json()
        if r.get("ok"):
            return f"https://t.me/{ch.lstrip('@')}/{r['result']['message_id']} (бот)"
        bot_err = r.get("description", str(r))
    # 2) Запасной путь — личный аккаунт (сессия Telethon), если он админ канала.
    if not os.getenv("TELETHON_SESSION"):
        raise RuntimeError(f"бот не смог опубликовать: {bot_err}")

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

    try:
        return asyncio.run(run())
    except Exception as e:  # noqa: BLE001
        bot = bot_username() or "бот-уведомитель"
        raise RuntimeError(f"нет прав публиковать в канал. Назначьте {bot} администратором канала "
                           f"@{ch.lstrip('@')} с правом «Публикация сообщений». (бот: {bot_err}; аккаунт: {type(e).__name__})")


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
    import courses

    if item["kind"] == "promo":
        spec = courses.promo_spec(item["course"], item["n"])
        tmp = OUT / "spec" / f"promo_{item['key'].split(':')[1]}.json"
    else:
        spec = json.loads(Path(item["spec"]).read_text(encoding="utf-8"))
        spec = courses.apply_to_spec(spec, courses.course_for(item["kind"]), item["n"])
        tmp = OUT / "spec" / Path(item["spec"]).name  # то же имя файла → то же имя ролика
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return make_short.render(tmp, OUT, use_voice=True, strict_voice=True)


def _check_channel(token, me, ch) -> str:
    status = "не удалось проверить"
    if token and ch and me:
        try:
            bot_id = int(token.split(":")[0])
            r = requests.get(f"https://api.telegram.org/bot{token}/getChatMember",
                             params={"chat_id": "@" + ch, "user_id": bot_id}, timeout=20).json()
            m = r.get("result", {})
            if m.get("status") == "administrator" and m.get("can_post_messages", True):
                status = "✅ я админ канала и могу публиковать — всё готово"
            else:
                status = f"❌ я пока не админ канала ({r.get('description') or m.get('status')})"
        except Exception as e:  # noqa: BLE001
            status = f"ошибка проверки: {e}"
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="опубликовать только на платформы: youtube,telegram,telegram2,instagram")
    ap.add_argument("--state", help="свой файл очереди (например, для отдельного YouTube-автопостинга)")
    ap.add_argument("--kinds", choices=["both", "new", "promo"], default="both",
                    help="new — только уроки-диалоги; promo — только рекламный ролик недели")
    ap.add_argument("--check", action="store_true", help="ничего не публиковать: бот назовёт себя и проверит права в канале")
    args = ap.parse_args()

    if args.check:
        token, me = os.getenv("BOT_TOKEN"), bot_username()
        lines = []
        for ch in [(os.getenv(k) or "").lstrip("@") for k in ("TG_CHANNEL", "TG_CHANNEL_2")]:
            if ch:
                lines.append(f"Канал @{ch}: {_check_channel(token, me, ch)}")
        notify(f"👋 Я {me or 'бот-уведомитель'} — бот автопостинга мультиков.\n\n" + "\n".join(lines) + "\n\n"
               f"Если я не админ — не страшно: ролик опубликует ваш аккаунт (если он админ канала). "
               f"Чтобы публиковал бот: откройте канал → Управление каналом → Администраторы → "
               f"Добавить администратора → найдите {me} → включите «Публикация сообщений» → Сохранить.")
        return

    global STATE, KINDS
    if args.state:
        STATE = Path(args.state).resolve()
    KINDS = args.kinds
    st = load_state()
    st.setdefault("next_new", 1)
    item = pick_today(st, args.dry_run)
    if item["kind"] == "none":
        notify("📭 Автопостинг: все 100 уроков и 100 слов уже опубликованы. Добавьте новые!")
        return
    print("Сегодня:", item["kind"], item.get("key"))
    if args.dry_run:
        print(json.dumps(texts_for(item), ensure_ascii=False, indent=1))
        return

    try:
        path = render_new(item) if item["kind"] in ("new", "word", "promo") else Path(item["path"])
    except Exception as e:  # noqa: BLE001
        notify(f"❌ Автопостинг: не удалось подготовить видео ({item.get('key')}): {e}")
        raise
    tx = texts_for(item)

    platforms = {
        "youtube": lambda: youtube_upload(path, tx["yt_title"], tx["yt_desc"]),
        "telegram": lambda: telegram_post(path, tx["tg"]),
        # Второй канал (Тамра Скул) — тот же ролик и подпись, только пн и чт (как раньше текстовые
        # посты pilatesbot, которые там теперь выключены). Дни меняет переменная TG2_SKIP_WEEKDAYS.
        "telegram2": lambda: telegram_post(path, tx["tg"], "TG_CHANNEL_2", "TG2_SKIP_WEEKDAYS", "1,2,4,5,6",
                                           "в Тамру ролики выходят по пн и чт"),
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
        if item["kind"] == "promo":
            pass  # реклама не двигает очереди уроков
        elif item["kind"] == "new":
            st["next_new"] = item["n"] + 1
        elif item["kind"] == "word":
            st["next_word"] = item["n"] + 1
        else:
            st["old_done"].append(item["key"])
        if item["kind"] != "promo":
            st["last_kind"] = "new" if item["kind"] == "new" else "word"
        st["history"].append({"date": dt.date.today().isoformat(), "key": item["key"],
                              "results": {k: v[:200] for k, v in results.items()}})
        save_state(st)

    kind = {"new": "урок-диалог", "word": "слово дня", "promo": "реклама курса"}.get(item["kind"], "старый шортс")
    me = bot_username()
    notify(f"🎬 Автопостинг ({kind}): {tx['yt_title']}\n\n" + "\n".join(f"{k}: {v}" for k, v in results.items())
           + (f"\n\n(Пишет {me} — бот автопостинга мультиков)" if me else ""))
    if not ok and any(v.startswith("❌") for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()

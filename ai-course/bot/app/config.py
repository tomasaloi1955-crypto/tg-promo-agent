"""Все настройки — из переменных окружения (Render → Environment или .env)."""
import os
from pathlib import Path


def _load_dotenv() -> None:
    """Локально читаем .env рядом с папкой бота (на Render его нет — там Environment)."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    value = _str(name)
    return int(value) if value else default


def _ids(name: str) -> set[str]:
    return {x for x in _str(name).replace(" ", "").split(",") if x}


BOT_TOKEN = _str("BOT_TOKEN")
DATABASE_URL = _str("DATABASE_URL")
BASE_URL = (_str("BASE_URL") or _str("RENDER_EXTERNAL_URL")).rstrip("/")
WEBHOOK_SECRET = _str("WEBHOOK_SECRET")
TICK_KEY = _str("TICK_KEY")
PORT = _int("PORT", 10000)

ADMIN_IDS = {int(x) for x in _str("ADMIN_IDS").replace(" ", "").split(",") if x}
AUTHOR_NAME = _str("AUTHOR_NAME", "Freya")

DEFAULT_TZ = _str("DEFAULT_TZ", "Asia/Almaty")
DAY_HOUR = _int("DAY_HOUR", 11)              # урок «днём»
EVENING_HOUR = _int("EVENING_HOUR", 19)      # урок «вечером»
INFO_HOUR = _int("INFO_HOUR", 13)            # прогрев, продажа
NUDGE_HOUR = _int("NUDGE_HOUR", 17)          # напоминание, если задание 2 не сделано
CHECKIN_HOUR = _int("CHECKIN_HOUR", 20)      # «Как вам интенсив?»
PRESENT_HOUR = _int("PRESENT_HOUR", 21)      # итоги + видео-презентация курса (день 3)
QUIET_HOUR = _int("QUIET_HOUR", 22)          # после этого часа ничего не шлём
MISSING_HOUR = _int("MISSING_HOUR", 21)      # урок не загружен — ждём до этого часа
ADMIN_MORNING_HOUR = _int("ADMIN_MORNING_HOUR", 9)
ADMIN_EVENING_HOUR = _int("ADMIN_EVENING_HOUR", 20)

CHANNEL_LINK = _str("CHANNEL_LINK", "https://t.me/Halalaifreya")
FREE_CHAT_LINK = _str("FREE_CHAT_LINK")      # чат участников интенсива
COURSE_START = _str("COURSE_START", "ближайший понедельник")   # дата старта курса для текстов
MENTOR_SEATS = _str("MENTOR_SEATS", "10")    # «осталось мест с наставником»

# Ранняя цена действует для человека до конца этого дня его воронки (день 4 — старт продаж).
EARLY_LAST_DAY = _int("EARLY_LAST_DAY", 7)

# Закрытые каналы курса. Бот — админ с правом «Пригласительные ссылки».
# Пустой канал потока → берётся общий COURSE_CHAT_ID.
COURSE_CHAT_ID = _str("COURSE_CHAT_ID")
_T1 = _str("COURSE_CHAT_T1") or COURSE_CHAT_ID
_T2 = _str("COURSE_CHAT_T2") or COURSE_CHAT_ID
_T3 = _str("COURSE_CHAT_T3") or COURSE_CHAT_ID
_MENTOR = _str("COURSE_CHAT_MENTOR")


def _uniq(*chats: str) -> list[str]:
    out: list[str] = []
    for c in chats:
        if c and c not in out:
            out.append(c)
    return out


def _plan(code: str, early: str, late: str, chats: list[str]) -> dict:
    up = code.upper()
    link = _str(f"TRIBUTE_LINK_{up}")
    return {
        "price": _str(f"PRICE_{up}", early),                 # ранняя цена
        "price_late": _str(f"PRICE_{up}_LATE", late),        # обычная цена
        "link": link,
        "link_late": _str(f"TRIBUTE_LINK_{up}_LATE") or link,
        # id товаров Tribute этого тарифа (ранний и обычный — через запятую)
        "products": _ids(f"TRIBUTE_PRODUCT_IDS_{up}"),
        "stars": _int(f"STARS_PRICE_{up}", 0),
        "chats": chats,
    }


# Коды тарифов: t1/t2/t3 — один поток, full — всё, mentor — всё + наставник.
PLANS = {
    "t1": _plan("t1", "4 900 ₽", "6 900 ₽", _uniq(_T1)),
    "t2": _plan("t2", "4 900 ₽", "6 900 ₽", _uniq(_T2)),
    "t3": _plan("t3", "4 900 ₽", "6 900 ₽", _uniq(_T3)),
    "full": _plan("full", "9 900 ₽", "14 900 ₽", _uniq(_T1, _T2, _T3)),
    "mentor": _plan("mentor", "24 900 ₽", "34 900 ₽", _uniq(_T1, _T2, _T3, _MENTOR)),
}
TRACK_PLANS = ("t1", "t2", "t3")

TRIBUTE_API_KEY = _str("TRIBUTE_API_KEY").strip().strip('"\'').strip().replace("​", "").replace("﻿", "")

SEND_RATE = _int("SEND_RATE", 25)

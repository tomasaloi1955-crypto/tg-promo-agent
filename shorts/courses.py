"""Платные курсы, на которые ведут мультики.

Ссылки можно задать здесь или переменными окружения (секретами GitHub):
  TAJWEED_URL, TAJWEED_CHECK_URL   — курс «Алфавит + таджвид» (тарифы Tribute)
  SPEAKING_URL, SPEAKING_CHECK_URL — курс «Чтение + разговор по-арабски»
Курс без ссылки нигде не рекламируется (лучше без рекламы, чем «ссылка в описании», которой нет).

Какой курс в каком ролике:
  • уроки-диалоги  → «Чтение + разговор» (если есть ссылка), иначе «Алфавит + таджвид»;
  • «Слово дня»    → «Алфавит + таджвид».
В ролике: плашка внизу кадра всё время; в конце — голос зовёт на курс через раз
(в нечётных роликах), в остальных — «повтори вслух и подпишись».
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

COURSES = {
    "tajweed": {
        "name": "Алфавит + таджвид",
        "url": "https://web.tribute.tg/s/18rW",        # тариф «Самостоятельно»
        "check_url": "https://web.tribute.tg/s/18VF",  # тариф «С проверкой ДЗ»
        "pitch": "Научись читать Коран с нуля: курс «Алфавит + таджвид» по книге «Муаллим сани»",
        "screen": "Курс «Алфавит + таджвид» — ссылка в профиле",
        "voice": "Хочешь читать Коран правильно? Мой курс по алфавиту и таджвиду — ссылка в профиле канала.",
        "outro": "Курс *«Алфавит + таджвид»* — ссылка в профиле!",
        "bullets": ["Читаешь Коран с нуля — по книге «Муаллим сани»",
                    "Видеоуроки в записи — учись, когда удобно",
                    "С проверкой ДЗ — исправляю каждую ошибку"],
        "promo_voice": "Курс «Алфавит и таджвид». Научишься читать Коран с нуля. Уроки в записи — учись, когда удобно. "
                       "А с проверкой домашних заданий я исправлю каждую ошибку.",
    },
    "speaking": {
        "name": "Чтение + разговор по-арабски",
        "url": "",        # ← ссылка Tribute на новый курс (пока нет — курс не рекламируется)
        "check_url": "",
        "pitch": "Заговори по-арабски: курс «Чтение + разговор» — новые уроки 3 раза в неделю",
        "screen": "Курс «Чтение + разговор» — ссылка в профиле",
        "voice": "Хочешь читать и говорить на арабском? Мой курс «Чтение и разговор» — ссылка в профиле канала.",
        "outro": "Курс *«Чтение + разговор»* — ссылка в профиле!",
        "bullets": ["Читаешь и говоришь на арабском",
                    "Новые уроки 3 раза в неделю",
                    "С проверкой ДЗ — исправляю ошибки"],
        "promo_voice": "Курс «Чтение и разговор на арабском». Научишься читать и говорить. Новые уроки три раза в неделю, "
                       "а с проверкой домашних заданий я исправлю твои ошибки.",
    },
}


def _url(key: str, field: str) -> str:
    env = f"{key.upper()}_{'CHECK_URL' if field == 'check_url' else 'URL'}"
    return (os.environ.get(env) or COURSES[key][field]).strip()


def enabled(key: str) -> bool:
    return bool(_url(key, "url"))


def course_for(kind: str) -> str | None:
    """Ключ курса для ролика: kind = 'new' (диалог) или 'word'."""
    if kind == "new" and enabled("speaking"):
        return "speaking"
    return "tajweed" if enabled("tajweed") else None


def tariffs(key: str) -> str:
    url, check = _url(key, "url"), _url(key, "check_url")
    if check:
        return (f"✅ Самостоятельно — видеоуроки и материалы\n👉 {url}\n"
                f"✅ С проверкой ДЗ — присылаешь чтение, я исправляю каждую ошибку\n👉 {check}")
    return f"👉 {url}"


def description_block(key: str | None) -> str:
    """Первые строки описания YouTube / подписи Telegram."""
    if not key:
        return ""
    return f"📖 {COURSES[key]['pitch']}\n{tariffs(key)}\n"


def social_line(key: str | None) -> str:
    """Instagram: ссылки в подписи не кликаются — зовём в профиль."""
    if not key:
        return ""
    return f"📖 {COURSES[key]['pitch']}. Ссылка в шапке профиля"


def apply_to_spec(spec: dict, key: str | None, n: int) -> dict:
    """Плашка внизу кадра всегда; голос и финальная надпись про курс — в нечётных роликах."""
    if not key:
        return spec
    c = COURSES[key]
    spec = dict(spec)
    spec["footer"] = c["screen"]
    if n % 2 == 1:
        spec["outro"] = c["outro"]
        spec["outro_speak"] = c["voice"]
    return spec


PROMO_SCENES = ["classroom_day", "cafe_day", "park_day", "majlis_day", "courtyard_day", "kitchen_day"]


def promo_course(week: int) -> str | None:
    """Чей рекламный ролик на этой неделе: курсы чередуются, если у обоих есть ссылки."""
    keys = [k for k in ("tajweed", "speaking") if enabled(k)]
    return keys[week % len(keys)] if keys else None


def promo_spec(key: str, week: int) -> dict:
    """Еженедельный рекламный мультик: сценка → карточка курса → «куда нажать» → призыв."""
    from dialogs import CHARACTERS

    c = COURSES[key]
    scene = PROMO_SCENES[week % len(PROMO_SCENES)]
    a, b = ("ahmad", "maryam") if week % 2 == 0 else ("maryam", "ahmad")
    wants = {"tajweed": ("أريد أن أقرأ القرآن!", "urīdu an aqra'a l-qur'ān!", "Хочу читать Коран!"),
             "speaking": ("أريد أن أتكلم العربية!", "urīdu an atakallama l-'arabiyya!", "Хочу говорить по-арабски!")}[key]
    return {
        "title": f"Курс *«{c['name']}»*",
        "channel": "MY ARABIC",
        "footer": c["screen"],
        "narrator": {"ar": "ar-SA-HamedNeural", "ru": "ru-RU-SvetlanaNeural"},
        "characters": {k: CHARACTERS[k] for k in (a, b)},
        "beats": [
            {"scene": scene, "cast": {a: 0.3, b: 0.72}},
            {"say": a, "mood": "happy", "ar": wants[0], "tr": wants[1], "ru": wants[2]},
            # обращаемся к собеседнику: к мальчику — تعالَ, к девочке — تعالَي
            {"say": b, "mood": "happy",
             "ar": "تعال معي إلى الدرس!" if a == "ahmad" else "تعالي معي إلى الدرس!",
             "tr": "ta'āla ma'ī ilā d-dars!" if a == "ahmad" else "ta'ālay ma'ī ilā d-dars!",
             "ru": "Пойдём со мной на урок!"},
            {"course": {"name": c["name"], "bullets": c["bullets"], "speak": c["promo_voice"],
                        "note": "2 тарифа: *самостоятельно* или *с проверкой ДЗ*"}},
            {"steps": [
                {"title": "На YouTube: нажми на *название канала* внизу видео", "mock": "shorts",
                 "speak": "На ютубе нажми на название канала внизу видео."},
                {"title": "Открой *ссылку* в описании канала", "mock": "channel",
                 "speak": "Открой ссылку в описании канала."},
                {"title": "Выбери *тариф* и оплати", "mock": "tariffs",
                 "speak": "Выбери тариф: самостоятельно или с проверкой домашних заданий."},
                {"title": "В Telegram ещё проще: *ссылка прямо под видео*", "mock": "telegram",
                 "speak": "А в телеграме ссылка прямо под видео."},
            ]},
        ],
        "outro": "Жду тебя на курсе! *Ссылка в профиле*",
        "outro_speak": "Жду тебя на курсе! Ссылка в профиле канала.",
    }

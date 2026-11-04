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

COURSES = {
    "tajweed": {
        "name": "Алфавит + таджвид",
        "url": "https://web.tribute.tg/s/18rW",        # тариф «Самостоятельно»
        "check_url": "https://web.tribute.tg/s/18VF",  # тариф «С проверкой ДЗ»
        "pitch": "Научись читать Коран с нуля: курс «Алфавит + таджвид» по книге «Муаллим сани»",
        "screen": "Курс «Алфавит + таджвид» — ссылка в профиле",
        "voice": "Хочешь читать Коран правильно? Мой курс по алфавиту и таджвиду — ссылка в профиле канала.",
        "outro": "Курс *«Алфавит + таджвид»* — ссылка в профиле!",
    },
    "speaking": {
        "name": "Чтение + разговор по-арабски",
        "url": "",        # ← ссылка Tribute на новый курс (пока нет — курс не рекламируется)
        "check_url": "",
        "pitch": "Заговори по-арабски: курс «Чтение + разговор» — новые уроки 3 раза в неделю",
        "screen": "Курс «Чтение + разговор» — ссылка в профиле",
        "voice": "Хочешь читать и говорить на арабском? Мой курс «Чтение и разговор» — ссылка в профиле канала.",
        "outro": "Курс *«Чтение + разговор»* — ссылка в профиле!",
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

# -*- coding: utf-8 -*-
"""
Оценка через Gemini: можно ли опубликовать рекламный пост в найденном чате,
судя по его описанию и закреплённому сообщению. Используется promo.py.
"""
import json
import os

from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

PROMO_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "verdict": types.Schema(
            type=types.Type.STRING,
            enum=["allowed", "conditional", "not_allowed", "unclear"],
        ),
        "condition": types.Schema(type=types.Type.STRING),
        "reason": types.Schema(type=types.Type.STRING),
    },
    required=["verdict", "reason"],
)

PROMO_SYSTEM_INSTRUCTION = """Ты помогаешь решить, можно ли опубликовать один рекламный пост
(самопиар стороннего проекта) в этом Telegram-чате, не нарушая его правил.
Тебе дают: название чата, его описание (about) и текст закреплённого сообщения (может быть пустым).
Верни ТОЛЬКО JSON по схеме:
- verdict:
  - "allowed" — в описании/закрепе явно сказано, что самопиар/реклама разрешены (например,
    "чат для взаимного пиара", "реклама по согласованию не нужна", "постите свои каналы")
  - "conditional" — разрешено, но с условием (например, только по субботам, только с оплатой,
    только после согласования с админом, только в определённой теме/топике) — условие опиши в поле condition
  - "not_allowed" — явно запрещено ("без рекламы", "самопиар банится", "только контент по теме чата,
    посторонние ссылки удаляются")
  - "unclear" — в описании и закрепе нет никакой информации о рекламе/самопиаре
Поле reason — короткое обоснование на русском (1 предложение), на основе чего сделан вывод.
Будь консервативен: если сомневаешься между allowed и unclear — выбирай unclear. Здесь нет
человека, который перепроверит твой вывод перед публикацией — от твоей оценки зависит,
уйдёт ли пост, так что лучше недооценить (unclear), чем переоценить (allowed по ошибке)."""


def check_promo_allowed(title: str, about: str, pinned: str) -> dict:
    """Оценивает по описанию чата и закреплённому сообщению, разрешён ли там самопиар."""
    if not GEMINI_API_KEY:
        return {"verdict": "unclear", "reason": "GEMINI_API_KEY не задан."}

    prompt = f"Название чата: {title}\n\nОписание (about):\n{about or '(пусто)'}\n\nЗакреплённое сообщение:\n{pinned or '(пусто)'}"
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PROMO_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=PROMO_RESPONSE_SCHEMA,
            ),
        )
    except Exception as e:
        return {"verdict": "unclear", "reason": f"Gemini недоступен ({e.__class__.__name__})."}

    try:
        data = json.loads(resp.text)
    except (json.JSONDecodeError, TypeError):
        return {"verdict": "unclear", "reason": "не разобрал ответ модели."}
    data.setdefault("verdict", "unclear")
    data.setdefault("reason", "")
    return data

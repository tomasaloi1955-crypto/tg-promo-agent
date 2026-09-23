# -*- coding: utf-8 -*-
"""
Оценка через Gemini: можно ли опубликовать рекламный пост в найденном чате,
судя по его описанию и закреплённому сообщению. Используется promo.py.
А также: подходит ли канал в клиенты услуги автопостинга (outreach.py).
"""
import json
import os
from typing import Optional

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
        "condition_type": types.Schema(
            type=types.Type.STRING,
            enum=["benign", "paid_or_approval", "other"],
        ),
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
    только после согласования с админом, только в определённой теме/топике) — условие опиши в поле condition.
    Для "conditional" ОБЯЗАТЕЛЬНО заполни condition_type:
      - "benign" — условие безобидное и выполнимое автопостом: определённый день недели/время,
        определённый топик или формат сообщения, «сначала представьтесь», лимит частоты.
      - "paid_or_approval" — за размещение нужно ЗАПЛАТИТЬ, купить, заказать через бота/прайс,
        ИЛИ получить личное разрешение админа / согласовать заранее / только для платных
        участников закрытого чата.
      - "other" — условие есть, но непонятно, к какому типу отнести.
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
    data.setdefault("condition_type", "other")
    return data


# ---------------------------------------------------------------- поиск клиентов (outreach.py)

LEAD_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "fit": types.Schema(type=types.Type.BOOLEAN),
        "niche": types.Schema(type=types.Type.STRING),
        "muslim": types.Schema(type=types.Type.BOOLEAN),
        "reason": types.Schema(type=types.Type.STRING),
        "message": types.Schema(type=types.Type.STRING),
    },
    required=["fit", "niche", "muslim", "reason", "message"],
)

LEAD_SYSTEM_INSTRUCTION = """Ты помогаешь найти клиентов для услуги «Telegram-канал ведётся сам»:
ежедневные посты в стиле канала без участия владельца, владелец раз в неделю утверждает темы.
Цены: настройка 15 000 ₽, сопровождение 5 000 ₽/мес, первым трём клиентам −50% за отзыв.
Бесплатный тест: 3 пробных поста в стиле канала до оплаты.

Тебе дают название публичного канала, описание и несколько последних постов.
Верни ТОЛЬКО JSON по схеме:
- fit — true, если это канал магазина/бренда, эксперта/тренера/преподавателя, онлайн-школы
  или другого проекта, которому регулярные посты приносят клиентов. false — если это новостной/
  агрегаторский/развлекательный канал, канал крупной компании со своей редакцией, личный дневник
  без продаж, ИЛИ запрещённая ниша: азартные игры, ставки, алкоголь, табак/вейпы, кредиты/займы/
  микрофинансы, форекс/крипто-сигналы, контент 18+, магия/гадания, сомнительные схемы заработка.
- niche — ниша канала в 2–4 словах.
- muslim — true, если канал явно мусульманский (исламский контент, халяль-товары, скромная одежда).
- reason — одно предложение, почему подходит или нет.
- message — если fit=true: личное первое сообщение владельцу канала на русском, 4–6 предложений,
  на «Вы». Начни с «Ассаляму алейкум!», если muslim=true, иначе с «Здравствуйте!».
  Упомяни одну конкретную деталь именно этого канала (что продают/чему учат), чтобы было видно,
  что канал смотрели. Коротко: могу настроить так, чтобы канал вёлся сам — посты каждый день
  в вашем стиле, от вас 10 минут в неделю на утверждение тем. Предложи бесплатно подготовить
  3 пробных поста в стиле канала. Заверши строкой «Подробнее и цены: {OFFER_LINK}».
  Без давления, без обещаний продаж в цифрах, без выдуманных фактов, без подписи и без эмодзи
  в начале. Если fit=false — пустая строка."""


def evaluate_channel_lead(title: str, about: str, posts: list[str], offer_link: str) -> Optional[dict]:
    """Подходит ли канал под услугу автопостинга, и черновик первого сообщения владельцу.
    None — если Gemini недоступен (тогда outreach.py обходится шаблоном)."""
    if not GEMINI_API_KEY:
        return None

    posts_text = "\n---\n".join(p[:500] for p in posts if p) or "(постов нет)"
    prompt = f"Название канала: {title}\n\nОписание:\n{about or '(пусто)'}\n\nПоследние посты:\n{posts_text}"
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=LEAD_SYSTEM_INSTRUCTION.replace("{OFFER_LINK}", offer_link),
                response_mime_type="application/json",
                response_schema=LEAD_RESPONSE_SCHEMA,
            ),
        )
        data = json.loads(resp.text)
    except Exception as e:
        print(f"  ! Gemini: {e.__class__.__name__}: {e}")
        return None
    if not isinstance(data, dict) or "fit" not in data:
        return None
    return data

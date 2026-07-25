# -*- coding: utf-8 -*-
"""
Генерирует рекламные баннеры (banners/<тема>.png) — по одному под каждую тему из
promo.THEME_ORDER. Каждая тема продвигает СВОЙ канал (см. promo.py docstring), поэтому
у каждой свой бренд: своё название, цвет, значок, ссылка — не только «Тамра».
Палитра/мотив «Тамра» (зелёный/золотой/кремовый, финиковая пальма) — из брендинга
дашборда школы (files/tamra_dashboard_parent.html), для остальных каналов — отдельные
цвета, чтобы баннеры не путались между собой. Запускать один раз (или заново — после
правки текстов/цветов ниже):

    venv\\Scripts\\python make_banners.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).parent
OUT_DIR = BASE / "banners"
OUT_DIR.mkdir(exist_ok=True)

FONTS = Path(r"C:\Windows\Fonts")
F_BLACK = FONTS / "seguibl.ttf"
F_BOLD = FONTS / "segoeuib.ttf"
F_REGULAR = FONTS / "segoeui.ttf"

PAPER = "#F9F8F3"
INK = "#1C1B18"
INK2 = "#3A3830"
CREAM = "#FAEEDA"
GOLD = "#BA7517"  # мотив-пальма (Тамра) всегда цвета ствола, независимо от акцента

W, H = 1280, 720
LEFT_W = 760

THEMES = {
    "sport": {
        "accent": "#C1443A",
        "icon": "dumbbell",
        "wordmark": "На спорте",
        "tagline": "Мусульманка на спорте",
        "eyebrow": "Ф И Т Н Е С   Д Л Я   С Е С Т Ё Р",
        "headline": ["Тренировки дома —", "без спортзала и лишних глаз"],
        "subline": "Пилатес и аэробика: каждый день и через день, онлайн",
        "cta": "t.me/ilikeislamandsport",
    },
    "education": {
        "accent": "#0F6E56",
        "icon": "palm",
        "wordmark": "Тамра",
        "tagline": "AI-школа · تَمْرَة",
        "eyebrow": "О Б Р А З О В А Н И Е",
        "headline": ["Не репетиторы наугад —", "адресный разбор пробелов"],
        "subline": "Диагностика + ИИ-учитель + подготовка к ЕНТ/ЕГЭ",
        "cta": "t.me/tamra_school",
    },
    "ai": {
        "accent": "#3B3E8C",
        "icon": "network",
        "wordmark": "Halal AI",
        "tagline": "Freya · автоматизация бизнеса",
        "eyebrow": "А В Т О М А Т И З А Ц И Я   Д Л Я   Б И З Н Е С А",
        "headline": ["Рутина, которую давно", "пора отдать ИИ"],
        "subline": "Автоматизация процессов и вайбкодинг под задачи компании",
        "cta": "t.me/Halalaifreya",
    },
    "family": {
        "accent": "#BA7517",
        "icon": "palm",
        "wordmark": "Тамра",
        "tagline": "AI-школа · تَمْرَة",
        "eyebrow": "С Е М Ь Я   И   Ц Е Н Н О С Т И",
        "headline": ["Академика — и Коран с Сунной", "в каждом предмете"],
        "subline": "Хадисы только из проверенной базы, без сомнительного контента",
        "cta": "t.me/tamra_school",
    },
    "arabic": {
        "accent": "#2E6F6E",
        "icon": "book",
        "wordmark": "My Arabic",
        "tagline": "Арабский язык с нуля",
        "eyebrow": "А Р А Б С К И Й   Я З Ы К",
        "headline": ["Арабский с нуля —", "просто и по шагам"],
        "subline": "Буквы, чтение, грамматика и слова на русском языке",
        "cta": "t.me/myarabicl",
    },
    "english": {
        "accent": "#1F3A5F",
        "icon": "book",
        "wordmark": "I Speak English",
        "tagline": "Английский язык с нуля",
        "eyebrow": "А Н Г Л И Й С К И Й   Я З Ы К",
        "headline": ["Английский откладываете", "«на потом»? Начните сейчас"],
        "subline": "Грамматика и фразы для жизни — понятно, на русском",
        "cta": "t.me/i_speak_en",
    },
}


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def draw_palm(draw: ImageDraw.ImageDraw, cx: int, top_y: int, color: str) -> None:
    """Мотив финиковой пальмы (тамра) — ствол + расходящиеся листья."""
    trunk_h = 130
    draw.rounded_rectangle([cx - 9, top_y + 40, cx + 9, top_y + 40 + trunk_h], radius=8, fill=GOLD)
    fronds = [(-150, -60, 200, 90), (-120, -95, 130, 35), (-40, -110, 40, 20), (40, -110, 120, 35), (110, -95, 250, 90)]
    for (dx0, dy0, dx1, dy1) in fronds:
        draw.arc([cx + dx0, top_y + dy0, cx + dx1, top_y + dy1], start=0, end=180, fill=color, width=10)
    draw.ellipse([cx - 12, top_y + 30, cx + 12, top_y + 54], fill=color)


def draw_dumbbell(draw: ImageDraw.ImageDraw, cx: int, top_y: int, color: str) -> None:
    bar_y = top_y + 100
    draw.rounded_rectangle([cx - 90, bar_y - 10, cx + 90, bar_y + 10], radius=8, fill=color)
    for dx in (-100, 100):
        draw.rounded_rectangle([cx + dx - 22, bar_y - 55, cx + dx + 22, bar_y + 55], radius=16, fill=color)
        draw.rounded_rectangle([cx + dx - 14, bar_y - 38, cx + dx + 14, bar_y + 38], radius=10, fill=color)


def draw_network(draw: ImageDraw.ImageDraw, cx: int, top_y: int, color: str) -> None:
    center = (cx, top_y + 90)
    nodes = [(-120, -40), (120, -40), (-90, 90), (90, 90), (0, -110)]
    r = 14
    for dx, dy in nodes:
        draw.line([center, (cx + dx, top_y + 90 + dy)], fill=color, width=5)
    draw.ellipse([center[0] - 20, center[1] - 20, center[0] + 20, center[1] + 20], fill=color)
    for dx, dy in nodes:
        p = (cx + dx, top_y + 90 + dy)
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)


def draw_book(draw: ImageDraw.ImageDraw, cx: int, top_y: int, color: str) -> None:
    y0, y1 = top_y + 30, top_y + 160
    draw.polygon([(cx, y0 + 12), (cx - 110, y0), (cx - 110, y1), (cx, y1 + 12)], fill=color)
    draw.polygon([(cx, y0 + 12), (cx + 110, y0), (cx + 110, y1), (cx, y1 + 12)], fill=color)
    draw.line([(cx, y0 + 12), (cx, y1 + 12)], fill=PAPER, width=4)


ICONS = {"palm": draw_palm, "dumbbell": draw_dumbbell, "network": draw_network, "book": draw_book}


def make_banner(theme: str, cfg: dict) -> Path:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)

    draw.rectangle([LEFT_W, 0, W, H], fill=cfg["accent"])
    panel_cx = LEFT_W + (W - LEFT_W) // 2
    ICONS[cfg["icon"]](draw, panel_cx, 130, CREAM)

    f_word = font(F_BLACK, 44)
    draw.text((panel_cx, 400), cfg["wordmark"], font=f_word, fill=PAPER, anchor="mm")
    f_tag = font(F_REGULAR, 22)
    draw.text((panel_cx, 452), cfg["tagline"], font=f_tag, fill=CREAM, anchor="mm")

    x = 70
    f_eyebrow = font(F_BOLD, 24)
    draw.text((x, 90), cfg["eyebrow"], font=f_eyebrow, fill=cfg["accent"])

    max_text_w = LEFT_W - x - 30  # не залезать на правую цветную панель
    size = 52
    while size > 28:
        f_head = font(F_BOLD, size)
        widest = max(draw.textbbox((0, 0), line, font=f_head)[2] for line in cfg["headline"])
        if widest <= max_text_w:
            break
        size -= 2
    line_h = int(size * 1.28)
    y = 160
    for line in cfg["headline"]:
        draw.text((x, y), line, font=f_head, fill=INK)
        y += line_h

    sub_size = 28
    while sub_size > 18:
        f_sub = font(F_REGULAR, sub_size)
        if draw.textbbox((0, 0), cfg["subline"], font=f_sub)[2] <= max_text_w:
            break
        sub_size -= 2
    y += 24
    draw.text((x, y), cfg["subline"], font=f_sub, fill=INK2)

    cta_text = cfg["cta"]
    f_cta = font(F_BOLD, 32)
    pad_x, pad_y = 34, 20
    tb = draw.textbbox((0, 0), cta_text, font=f_cta)
    cta_w, cta_h = tb[2] - tb[0], tb[3] - tb[1]
    cta_x0, cta_y0 = x, H - 130
    cta_x1, cta_y1 = cta_x0 + cta_w + pad_x * 2, cta_y0 + cta_h + pad_y * 2
    draw.rounded_rectangle([cta_x0, cta_y0, cta_x1, cta_y1], radius=(cta_y1 - cta_y0) // 2, fill=cfg["accent"])
    draw.text((cta_x0 + pad_x, cta_y0 + pad_y - tb[1]), cta_text, font=f_cta, fill=PAPER)

    out = OUT_DIR / f"{theme}.png"
    img.save(out, "PNG")
    return out


if __name__ == "__main__":
    for theme, cfg in THEMES.items():
        path = make_banner(theme, cfg)
        print(f"OK: {path}")

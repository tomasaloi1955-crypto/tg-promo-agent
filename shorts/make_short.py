"""Генератор коротких обучающих мультиков (YouTube Shorts) для канала «My Arabic».

Сценарий эпизода — JSON-файл в shorts/episodes/. На выходе — вертикальное видео
1080x1920 (MP4, H.264 + AAC): 2D-персонажи, сцены, субтитры
(арабский + транслитерация + русский), карточки слов, «диалект vs фусха»,
перемотка времени, музыка и озвучка.

Озвучка — Microsoft Edge TTS (пакет edge-tts, бесплатно, без ключа). Если голос
недоступен (нет сети) — ролик собирается без голоса, только с музыкой и звуками.

Запуск:
    python shorts/make_short.py shorts/episodes/ep01_where_were_you.json
    python shorts/make_short.py shorts/episodes/*.json --out out --no-voice
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"

W, H = 1080, 1920
FPS = 30
SR = 24000  # частота дискретизации звука
SS = 2  # суперсэмплинг для гладких краёв спрайтов и фонов

# Раскладка кадра
HEADER_H = 250
SCENE_Y, SCENE_H = 250, 1120
SUB_Y = 1395
FOOTER_Y = 1800

PAGE_BG = (16, 58, 60)
GOLD = (242, 177, 52)
INK = (38, 32, 40)
WHITE = (255, 255, 255)

RAQM = features.check("raqm")


# ─────────────────────────── шрифты и текст ───────────────────────────

@functools.lru_cache(None)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    engine = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(str(FONTS / f"{name}.ttf"), size, layout_engine=engine)


AR_RE = re.compile(r"[؀-ۿ]")


def is_ar(s: str) -> bool:
    return bool(AR_RE.search(s))


def prep_ar(s: str) -> str:
    """Без libraqm Pillow не умеет соединять арабские буквы — тогда делаем это сами."""
    if RAQM:
        return s
    import arabic_reshaper  # noqa: WPS433
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(s))


def text_kw(s: str) -> dict:
    if RAQM and is_ar(s):
        return {"direction": "rtl", "language": "ar"}
    return {}


def tlen(f: ImageFont.FreeTypeFont, s: str) -> float:
    return f.getlength(prep_ar(s) if is_ar(s) else s, **text_kw(s))


def draw_text(d: ImageDraw.ImageDraw, xy, s: str, f, fill, anchor="la", **kw):
    d.text(xy, prep_ar(s) if is_ar(s) else s, font=f, fill=fill, anchor=anchor, **text_kw(s), **kw)


def tokens(s: str):
    """'هلا *يا ولدي*!' -> [('هلا', False), ('يا', True), ('ولدي', True), ('!', False, glued)].
    *...* — подсветка. Знак препинания сразу после слова «приклеивается» к нему (без пробела)."""
    out, hl, cur, glue = [], False, "", False
    for ch in s + " ":
        if ch == "*":
            if cur:
                out.append((cur, hl, glue))
                cur, glue = "", True
            hl = not hl
        elif ch.isspace():
            if cur:
                out.append((cur, hl, glue))
            cur, glue = "", False
        else:
            cur += ch
    return out


def wrap(tok, f, maxw, space):
    lines, cur, cw = [], [], 0.0
    for t in tok:
        w = tlen(f, t[0])
        if cur and not t[2] and cw + space + w > maxw:
            lines.append(cur)
            cur, cw = [], 0.0
        cw += (space if cur and not t[2] else 0) + w
        cur.append(t)
    if cur:
        lines.append(cur)
    return lines


def rich_text(d, cx, y, s, f, color, hl_color, maxw, rtl=False, line_gap=0.95, stroke=0, stroke_fill=None):
    """Текст по центру, с переносом и подсветкой слов в *звёздочках*. Возвращает нижний y."""
    tok = tokens(s)
    if not tok:
        return y
    space = tlen(f, " ") or f.size * 0.28
    asc, desc = f.getmetrics()
    lh = (asc + desc) * line_gap
    for line in wrap(tok, f, maxw, space):
        widths = [tlen(f, t[0]) for t in line]
        gaps = [0 if (i == 0 or t[2]) else space for i, t in enumerate(line)]
        total = sum(widths) + sum(gaps)
        x = cx + total / 2 if rtl else cx - total / 2
        for (w, hl, _), ww, g in zip(line, widths, gaps):
            if rtl:  # арабский: первое слово справа
                x -= g + ww
                draw_text(d, (x, y), w, f, hl_color if hl else color, stroke_width=stroke, stroke_fill=stroke_fill)
            else:
                x += g
                draw_text(d, (x, y), w, f, hl_color if hl else color, stroke_width=stroke, stroke_fill=stroke_fill)
                x += ww
        y += lh
    return y


def plain(s: str) -> str:
    return s.replace("*", "")


# ─────────────────────────── сцены (фоны) ───────────────────────────

def sadu_band(d, x0, y0, x1, h, base, dark, light):
    """Полоса с геометрическим орнаментом в духе бедуинского ткачества садо."""
    d.rectangle([x0, y0, x1, y0 + h], fill=base)
    s = h * 0.16
    d.rectangle([x0, y0, x1, y0 + s], fill=dark)
    d.rectangle([x0, y0 + h - s, x1, y0 + h], fill=dark)
    step = h * 0.9
    cy = y0 + h / 2
    r = h * 0.32
    i = 0
    x = x0
    while x < x1 + step:
        c = light if i % 2 == 0 else dark
        d.polygon([(x, cy - r), (x + r, cy), (x, cy + r), (x - r, cy)], fill=c)
        d.polygon([(x, cy - r * 0.4), (x + r * 0.4, cy), (x, cy + r * 0.4), (x - r * 0.4, cy)], fill=base)
        # зубчики по краям
        tx = x + step / 2
        d.polygon([(tx - s, y0 + s), (tx + s, y0 + s), (tx, y0 + s * 2.2)], fill=light)
        d.polygon([(tx - s, y0 + h - s), (tx + s, y0 + h - s), (tx, y0 + h - s * 2.2)], fill=light)
        x += step
        i += 1


SCENES = {
    "kitchen_day": dict(wall=(250, 235, 205), wall2=(240, 218, 178), floor=(214, 170, 120), floor2=(198, 152, 102),
                        sadu=((196, 52, 48), (52, 38, 44), (250, 240, 225)), night=False, props="kitchen"),
    "majlis_night": dict(wall=(48, 62, 128), wall2=(40, 50, 104), floor=(120, 44, 58), floor2=(100, 34, 48),
                         sadu=((160, 40, 50), (30, 24, 40), (230, 210, 180)), night=True, props="majlis"),
    "majlis_day": dict(wall=(232, 220, 196), wall2=(214, 196, 164), floor=(150, 58, 66), floor2=(128, 46, 56),
                       sadu=((180, 46, 50), (48, 36, 44), (245, 235, 215)), night=False, props="majlis"),
}


def draw_window(d, x, y, w, h, night):
    d.rounded_rectangle([x - 14, y - 14, x + w + 14, y + h + 14], 18, fill=(120, 78, 50))
    sky = (24, 30, 70) if night else (140, 200, 245)
    d.rectangle([x, y, x + w, y + h], fill=sky)
    if night:
        d.ellipse([x + w * 0.55, y + h * 0.15, x + w * 0.85, y + h * 0.45], fill=(250, 240, 200))
        d.ellipse([x + w * 0.62, y + h * 0.1, x + w * 0.92, y + h * 0.4], fill=sky)  # полумесяц
        rnd = random.Random(7)
        for _ in range(14):
            sx, sy = x + rnd.random() * w, y + rnd.random() * h
            r = rnd.choice([3, 4, 6])
            d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 255, 230))
    else:
        d.ellipse([x + w * 0.5, y + h * 0.15, x + w * 0.85, y + h * 0.5], fill=(255, 214, 80))
        d.ellipse([x + w * 0.08, y + h * 0.6, x + w * 0.5, y + h * 0.8], fill=WHITE)
        d.ellipse([x + w * 0.22, y + h * 0.52, x + w * 0.45, y + h * 0.75], fill=WHITE)
    d.rectangle([x + w / 2 - 6, y, x + w / 2 + 6, y + h], fill=(120, 78, 50))
    d.rectangle([x, y + h / 2 - 6, x + w, y + h / 2 + 6], fill=(120, 78, 50))


def draw_dallah(d, x, y, s, color=(222, 170, 60)):
    """Арабский кофейник даллa (x, y — низ по центру)."""
    d.ellipse([x - 40 * s, y - 70 * s, x + 40 * s, y], fill=color, outline=INK, width=int(4 * s))
    d.polygon([(x - 22 * s, y - 64 * s), (x + 22 * s, y - 64 * s), (x + 14 * s, y - 120 * s), (x - 14 * s, y - 120 * s)],
              fill=color, outline=INK, width=int(4 * s))
    d.ellipse([x - 22 * s, y - 140 * s, x + 22 * s, y - 112 * s], fill=color, outline=INK, width=int(4 * s))
    d.polygon([(x + 30 * s, y - 50 * s), (x + 80 * s, y - 120 * s), (x + 88 * s, y - 112 * s), (x + 40 * s, y - 36 * s)],
              fill=color, outline=INK, width=int(4 * s))


@functools.lru_cache(None)
def scene_bg(name: str) -> Image.Image:
    c = SCENES[name]
    w, h = W * SS, SCENE_H * SS
    im = Image.new("RGB", (w, h), c["wall"])
    d = ImageDraw.Draw(im)
    s = SS
    band_y = int(h * 0.52)
    floor_y = int(h * 0.80)
    d.rectangle([0, band_y, w, floor_y], fill=c["wall2"])
    sadu_band(d, 0, band_y - 30 * s, w, 70 * s, *c["sadu"])
    d.rectangle([0, floor_y, w, h], fill=c["floor"])
    for i in range(0, w, 160 * s):  # доски / узор пола
        d.line([(i, floor_y), (i - 120 * s, h)], fill=c["floor2"], width=4 * s)
    d.rectangle([0, floor_y, w, floor_y + 10 * s], fill=c["floor2"])

    draw_window(d, int(w * 0.66), int(h * 0.12), int(w * 0.24), int(h * 0.26), c["night"])

    # подвесная лампа
    lx = int(w * 0.42)
    d.line([(lx, 0), (lx, 110 * s)], fill=INK, width=4 * s)
    d.pieslice([lx - 50 * s, 90 * s, lx + 50 * s, 190 * s], 180, 360, fill=(230, 160, 60), outline=INK, width=4 * s)
    if c["night"]:
        glow = Image.new("L", (w, h), 0)
        ImageDraw.Draw(glow).ellipse([lx - 260 * s, 0, lx + 260 * s, 480 * s], fill=70)
        glow = glow.filter(ImageFilter.GaussianBlur(60 * s))
        im = Image.composite(Image.new("RGB", (w, h), (255, 210, 130)), im, glow)
        d = ImageDraw.Draw(im)

    if c["props"] == "kitchen":
        # полка с кувшинами
        sx, sy = int(w * 0.05), int(h * 0.2)
        d.rectangle([sx, sy, sx + 330 * s, sy + 14 * s], fill=(130, 84, 52))
        for i, col in enumerate([(84, 160, 120), (232, 180, 70), (210, 90, 70), (110, 140, 200)]):
            px = sx + 30 * s + i * 78 * s
            d.ellipse([px, sy - 62 * s, px + 58 * s, sy + 2 * s], fill=col, outline=INK, width=3 * s)
            d.rectangle([px + 18 * s, sy - 76 * s, px + 40 * s, sy - 56 * s], fill=col, outline=INK, width=3 * s)
        # стол-стойка
        ty = int(h * 0.60)
        d.rounded_rectangle([int(w * 0.30), ty, int(w * 0.98), ty + 40 * s], 10 * s, fill=(150, 98, 60), outline=INK, width=4 * s)
        d.rectangle([int(w * 0.32), ty + 40 * s, int(w * 0.96), floor_y + 30 * s], fill=(176, 120, 76), outline=INK, width=4 * s)
        for k in range(3):
            fx = int(w * 0.36) + k * int(w * 0.2)
            d.rounded_rectangle([fx, ty + 70 * s, fx + int(w * 0.16), floor_y], 8 * s, outline=(130, 84, 52), width=3 * s)
        draw_dallah(d, int(w * 0.85), ty, s)
        for k, col in enumerate([(240, 240, 240), (240, 200, 120)]):
            px = int(w * 0.5) + k * 130 * s
            d.ellipse([px, ty - 22 * s, px + 110 * s, ty + 6 * s], fill=col, outline=INK, width=3 * s)
    else:
        # подушки маджлиса вдоль стены и низкий столик
        cy0 = floor_y - 120 * s
        d.rounded_rectangle([0, cy0 + 40 * s, w, floor_y + 20 * s], 20 * s, fill=(170, 50, 60) if not c["night"] else (120, 36, 50),
                            outline=INK, width=4 * s)
        for i in range(5):
            px = 20 * s + i * 215 * s
            d.rounded_rectangle([px, cy0 - 30 * s, px + 190 * s, cy0 + 70 * s], 26 * s,
                                fill=(214, 160, 70) if i % 2 else (60, 110, 120), outline=INK, width=4 * s)
        tx = int(w * 0.5)
        d.rounded_rectangle([tx - 150 * s, floor_y + 60 * s, tx + 150 * s, floor_y + 90 * s], 8 * s, fill=(120, 76, 46), outline=INK, width=4 * s)
        draw_dallah(d, tx - 50 * s, floor_y + 60 * s, s * 0.8)
        for k in range(2):
            px = tx + 40 * s + k * 50 * s
            d.polygon([(px, floor_y + 60 * s), (px + 30 * s, floor_y + 60 * s), (px + 36 * s, floor_y + 30 * s), (px - 6 * s, floor_y + 30 * s)],
                      fill=WHITE, outline=INK)
    return im.resize((W, SCENE_H), Image.LANCZOS)


# ─────────────────────────── персонажи ───────────────────────────

CHAR_TYPES = {
    # тип: цвета и детали. Высота спрайта берётся из scale.
    "man": dict(skin=(232, 184, 140), cloth=(246, 246, 242), head="ghutra", beard=True, scale=1.0),
    "grandpa": dict(skin=(226, 176, 132), cloth=(240, 236, 226), head="ghutra", beard=True, gray=True, scale=0.97),
    "boy": dict(skin=(236, 190, 146), cloth=(246, 246, 242), head="hair", beard=False, scale=0.82),
    "woman": dict(skin=(238, 192, 150), cloth=(70, 74, 96), head="hijab", hijab=(66, 112, 186), beard=False, scale=0.95),
    "girl": dict(skin=(240, 196, 154), cloth=(232, 120, 150), head="hijab", hijab=(250, 196, 70), beard=False, scale=0.78),
}

SPR_W, SPR_H = 340, 600  # размер спрайта в 1x


@functools.lru_cache(None)
def sprite(kind: str, blink: bool, mouth: str, mood: str, colors: tuple = ()) -> Image.Image:
    """Рисует персонажа (в 2x, потом уменьшает). mouth: closed|open|wide, mood: neutral|happy|angry|sad|surprised."""
    t = dict(CHAR_TYPES[kind])
    for k, v in colors:
        t[k] = tuple(v) if isinstance(v, list) else v
    s = SS
    im = Image.new("RGBA", (SPR_W * s, SPR_H * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ow = 5 * s  # толщина контура

    def P(*xy):
        return [v * s for v in xy]

    skin, cloth = t["skin"], t["cloth"]
    # тень
    d.ellipse(P(60, 572, 280, 598), fill=(0, 0, 0, 60))
    # руки (за телом)
    d.rounded_rectangle(P(52, 330, 100, 480), 22 * s, fill=cloth, outline=INK, width=ow)
    d.rounded_rectangle(P(240, 330, 288, 480), 22 * s, fill=cloth, outline=INK, width=ow)
    d.ellipse(P(54, 462, 98, 506), fill=skin, outline=INK, width=ow)
    d.ellipse(P(242, 462, 286, 506), fill=skin, outline=INK, width=ow)
    # тело (тоб / платье)
    d.polygon(P(100, 310, 240, 310, 262, 572, 78, 572), fill=cloth, outline=INK, width=ow)
    d.rounded_rectangle(P(96, 300, 244, 380), 40 * s, fill=cloth, outline=INK, width=ow)
    d.rectangle(P(102, 340, 238, 400), fill=cloth)
    if t["head"] != "hijab":
        d.line(P(170, 330, 170, 420), fill=(200, 200, 196), width=3 * s)
        for by in (350, 380):
            d.ellipse(P(165, by, 175, by + 10), fill=(190, 190, 186))
    # ступни
    d.ellipse(P(104, 562, 160, 586), fill=(90, 60, 40), outline=INK, width=3 * s)
    d.ellipse(P(180, 562, 236, 586), fill=(90, 60, 40), outline=INK, width=3 * s)

    # голова
    hx0, hy0, hx1, hy1 = 40, 40, 300, 300
    if t["head"] == "ghutra":
        d.polygon(P(52, 150, 288, 150, 300, 370, 40, 370), fill=WHITE, outline=INK, width=ow)  # спадающая ткань
        d.ellipse(P(hx0, hy0, hx1, hy1), fill=WHITE, outline=INK, width=ow)
        d.ellipse(P(78, 96, 262, 296), fill=skin, outline=INK, width=ow)
        d.rounded_rectangle(P(62, 52, 278, 84), 16 * s, fill=(30, 28, 34))  # игаль
        d.rounded_rectangle(P(70, 78, 270, 100), 12 * s, fill=(30, 28, 34))
    elif t["head"] == "hijab":
        hc = t["hijab"]
        d.polygon(P(50, 160, 290, 160, 312, 400, 28, 400), fill=hc, outline=INK, width=ow)
        d.ellipse(P(hx0, hy0, hx1, hy1), fill=hc, outline=INK, width=ow)
        d.ellipse(P(82, 92, 258, 292), fill=skin, outline=INK, width=ow)
    else:  # волосы
        d.ellipse(P(56, 60, 284, 300), fill=skin, outline=INK, width=ow)
        hair = (40, 30, 30)
        for cx, cy, r in [(90, 110, 46), (130, 80, 50), (175, 70, 52), (220, 84, 48), (256, 118, 42), (70, 150, 34), (272, 156, 32)]:
            d.ellipse(P(cx - r, cy - r, cx + r, cy + r), fill=hair)
        d.ellipse(P(64, 54, 278, 150), fill=hair)

    # лицо
    ey = 196
    ex = (128, 212)
    brow_col = (180, 180, 180) if t.get("gray") else (50, 36, 30)
    for i, x in enumerate(ex):
        if blink:
            d.arc(P(x - 16, ey - 8, x + 16, ey + 14), 200, 340, fill=INK, width=5 * s)
        else:
            rx, ry = (13, 20) if mood != "surprised" else (15, 23)
            d.ellipse(P(x - rx, ey - ry, x + rx, ey + ry), fill=INK)
            d.ellipse(P(x - 6, ey - 13, x + 2, ey - 5), fill=WHITE)
        # брови
        side = -1 if i == 0 else 1
        if mood == "angry":
            d.line(P(x - 20, ey - 40 - 8 * side, x + 20, ey - 40 + 8 * side), fill=brow_col, width=7 * s)
        elif mood == "sad":
            d.line(P(x - 20, ey - 38 + 8 * side, x + 20, ey - 38 - 8 * side), fill=brow_col, width=7 * s)
        elif mood == "surprised":
            d.arc(P(x - 20, ey - 58, x + 20, ey - 30), 200, 340, fill=brow_col, width=7 * s)
        else:
            d.arc(P(x - 20, ey - 50, x + 20, ey - 30), 210, 330, fill=brow_col, width=6 * s)
    # щёчки
    blush = Image.new("RGBA", im.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(blush)
    bd.ellipse(P(92, 222, 126, 244), fill=(240, 120, 120, 110))
    bd.ellipse(P(214, 222, 248, 244), fill=(240, 120, 120, 110))
    im.alpha_composite(blush)
    d = ImageDraw.Draw(im)

    my = 252
    if t.get("beard"):
        bc = (200, 200, 200) if t.get("gray") else (60, 42, 34)
        d.chord(P(104, 190, 236, 296), 20, 160, fill=bc)
        d.rounded_rectangle(P(136, 234, 204, 248), 7 * s, fill=bc)  # усы
        my = 258
    if mouth == "closed":
        if mood == "sad" or mood == "angry":
            d.arc(P(150, my, 190, my + 22), 200, 340, fill=INK, width=5 * s)
        else:
            d.arc(P(146, my - 14, 194, my + 10), 20, 160, fill=INK, width=5 * s)
    else:
        mh = 24 if mouth == "open" else 34
        mw = 22 if mouth == "open" else 26
        if mood == "surprised":
            mw = 16
        d.ellipse(P(170 - mw, my - 8, 170 + mw, my - 8 + mh), fill=(110, 30, 40), outline=INK, width=4 * s)
        d.ellipse(P(170 - mw * 0.55, my - 8 + mh * 0.5, 170 + mw * 0.55, my - 8 + mh - 2), fill=(230, 110, 110))
    return im.resize((SPR_W, SPR_H), Image.LANCZOS)


# ─────────────────────────── карточки ───────────────────────────

def rounded_card(size, fill, radius=36, outline=None, width=0, shadow=True):
    w, h = size
    pad = 24 if shadow else 0
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 10, pad + w, pad + h + 10], radius, fill=(0, 0, 0, 110))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
    ImageDraw.Draw(im).rounded_rectangle([pad, pad, pad + w, pad + h], radius, fill=fill, outline=outline, width=width)
    return im, pad


def subtitle_card(name: str, name_color, ar: str, tr: str, ru: str) -> Image.Image:
    cw, ch = 1010, 390
    im, p = rounded_card((cw, ch), (28, 26, 40, 240), 38)
    d = ImageDraw.Draw(im)
    if name:
        f = font("Nunito-Black", 34)
        nw = tlen(f, name) + 44
        d.rounded_rectangle([p + 30, p - 22, p + 30 + nw, p + 30], 26, fill=name_color, outline=INK, width=3)
        draw_text(d, (p + 30 + nw / 2, p + 4), name, f, WHITE, anchor="mm")
    cx = p + cw / 2
    y = p + 34
    y = rich_text(d, cx, y, ar, font("Cairo-Bold", 82), WHITE, GOLD, cw - 80, rtl=True, line_gap=0.8)
    if tr:
        y = rich_text(d, cx, y + 6, tr, font("Nunito-SemiBold", 38), (180, 180, 196), (250, 210, 140), cw - 80)
    if ru:
        rich_text(d, cx, y + 8, ru, font("Nunito-ExtraBold", 46), (255, 236, 200), GOLD, cw - 80)
    return im


def word_card(label: str, ar: str, tr: str, ru: str) -> Image.Image:
    cw, ch = 820, 560
    im, p = rounded_card((cw, ch), (255, 252, 244, 255), 44, outline=INK, width=6)
    d = ImageDraw.Draw(im)
    f = font("Nunito-Black", 36)
    lw = tlen(f, label) + 60
    d.rounded_rectangle([p + cw / 2 - lw / 2, p - 30, p + cw / 2 + lw / 2, p + 34], 32, fill=(240, 140, 40), outline=INK, width=4)
    draw_text(d, (p + cw / 2, p + 2), label, f, WHITE, anchor="mm")
    cx = p + cw / 2
    y = rich_text(d, cx, p + 50, ar, font("Cairo-Black", 150), INK, (220, 90, 40), cw - 80, rtl=True, line_gap=0.78)
    y = rich_text(d, cx, y + 4, tr, font("Nunito-ExtraBold", 46), (120, 110, 130), (220, 90, 40), cw - 80)
    rich_text(d, cx, y + 14, ru, font("Nunito-Black", 54), (220, 90, 40), (30, 120, 110), cw - 80)
    return im


def compare_card(left: dict, right: dict, active: int) -> Image.Image:
    """Две колонки: слева диалект, справа фусха. active: -1 никто, 0 левая, 1 правая."""
    cw, ch = 1010, 640
    im = Image.new("RGBA", (cw + 48, ch + 48), (0, 0, 0, 0))
    colw = (cw - 30) // 2
    for i, item in enumerate((left, right)):
        x = 24 + i * (colw + 30)
        on = active in (i, 2)
        fill = (255, 252, 244, 255) if on else (230, 226, 216, 235)
        card, p = rounded_card((colw, ch), fill, 36, outline=GOLD if on else INK, width=8 if on else 4)
        cd = ImageDraw.Draw(card)
        f = font("Nunito-Black", 40)
        lab = item.get("label", "")
        col = (40, 130, 120) if i == 0 else (180, 70, 50)
        lw = tlen(f, lab) + 50
        cd.rounded_rectangle([p + colw / 2 - lw / 2, p + 22, p + colw / 2 + lw / 2, p + 84], 30, fill=col)
        draw_text(cd, (p + colw / 2, p + 52), lab, f, WHITE, anchor="mm")
        cx = p + colw / 2
        y = rich_text(cd, cx, p + 120, item["ar"], font("Cairo-Black", 92), INK, (220, 90, 40), colw - 40, rtl=True, line_gap=0.78)
        y = rich_text(cd, cx, y + 10, item.get("tr", ""), font("Nunito-ExtraBold", 40), (110, 100, 120), (220, 90, 40), colw - 40)
        if item.get("ru"):
            rich_text(cd, cx, y + 16, item["ru"], font("Nunito-ExtraBold", 40), col, col, colw - 40)
        im.alpha_composite(card, (x - p, 24 - p) if x - p >= 0 else (0, 0))
    vs = font("Nunito-Black", 54)
    d = ImageDraw.Draw(im)
    vx, vy = (cw + 48) / 2, 24 + ch / 2
    d.ellipse([vx - 52, vy - 52, vx + 52, vy + 52], fill=GOLD, outline=INK, width=5)
    draw_text(d, (vx, vy - 4), "vs", vs, INK, anchor="mm")
    return im


def big_caption(text: str, size=78, maxw=960) -> Image.Image:
    """Крупная надпись с обводкой (хук в начале, финальная фраза)."""
    im = Image.new("RGBA", (W, 700), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = rich_text(d, W / 2, 20, text, font("Nunito-Black", size), WHITE, GOLD, maxw, line_gap=0.9, stroke=10, stroke_fill=INK)
    return im.crop((0, 0, W, int(y + 30)))


def clock_chip(text: str, night: bool) -> Image.Image:
    f = font("Nunito-Black", 44)
    w = int(tlen(f, text)) + 110
    im, p = rounded_card((w, 76), (255, 255, 255, 235), 38)
    d = ImageDraw.Draw(im)
    cx, cy = p + 42, p + 38
    if night:
        d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(250, 220, 90))
        d.ellipse([cx - 10, cy - 26, cx + 26, cy + 12], fill=(255, 255, 255))
    else:
        for a in range(0, 360, 45):
            r = math.radians(a)
            d.line([cx + 16 * math.cos(r), cy + 16 * math.sin(r), cx + 26 * math.cos(r), cy + 26 * math.sin(r)], fill=(240, 160, 30), width=5)
        d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=(250, 190, 40))
    draw_text(d, (p + 76, cy - 2), text, f, INK, anchor="lm")
    return im


def rewind_icon(d, cx, cy, s, color):
    for k in (0, 1):
        x = cx - k * s * 0.9
        d.polygon([(x, cy - s / 2), (x, cy + s / 2), (x - s * 0.9, cy)], fill=color)


# ─────────────────────────── звук ───────────────────────────

def env(n, attack=0.005, decay=0.25):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t / decay)


def pluck(freq, dur, vol=0.3):
    n = int(dur * SR)
    t = np.arange(n) / SR
    wave = sum(np.sin(2 * np.pi * freq * k * t) / k ** 1.6 for k in range(1, 7))
    return vol * wave * env(n, 0.004, dur * 0.35)


def drum(kind, vol=0.5):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    if kind == "dum":
        f = 110 * np.exp(-t * 18) + 55
        return vol * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14)
    rng = np.random.default_rng(1)
    return vol * 0.5 * rng.standard_normal(n) * np.exp(-t * 60)


def music(seconds: float, seed: int = 3) -> np.ndarray:
    """Лёгкий восточный луп: макам хиджаз + дарбука (дум-тек-тек-дум-тек)."""
    rng = random.Random(seed)
    bpm = 104
    beat = 60 / bpm
    n = int(seconds * SR) + SR
    out = np.zeros(n)
    base = 293.66  # ре
    scale = [0, 1, 4, 5, 7, 8, 10, 12]  # хиджаз
    pattern = ["dum", None, "tak", "tak", "dum", None, "tak", None]
    phrase = [rng.choice(scale) for _ in range(16)]
    i = 0
    t = 0.0
    while t < seconds:
        pos = int(t * SR)
        p = pattern[i % 8]
        if p:
            s = drum(p, 0.35 if p == "dum" else 0.25)
            out[pos:pos + len(s)] += s[: n - pos]
        if i % 2 == 0:
            step = phrase[(i // 2) % 16]
            f = base * 2 ** (step / 12)
            s = pluck(f, beat * 1.8, 0.12)
            out[pos:pos + len(s)] += s[: n - pos]
        if i % 8 == 0:
            s = pluck(base / 2, beat * 4, 0.14)
            out[pos:pos + len(s)] += s[: n - pos]
        t += beat / 2
        i += 1
    return out[: int(seconds * SR)]


def sfx(kind: str) -> np.ndarray:
    if kind == "pop":
        n = int(0.18 * SR)
        t = np.arange(n) / SR
        f = 500 + 1400 * t / t[-1]
        return 0.35 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 18)
    if kind == "rewind":
        n = int(1.2 * SR)
        t = np.arange(n) / SR
        f = 2400 - 1600 * np.sin(np.pi * t / t[-1])
        saw = 2 * ((np.cumsum(f) / SR) % 1) - 1
        noise = np.random.default_rng(0).standard_normal(n) * 0.3
        return 0.12 * (saw + noise) * np.minimum(1, t * 8) * np.minimum(1, (t[-1] - t) * 8)
    if kind == "whoosh":
        n = int(0.4 * SR)
        t = np.arange(n) / SR
        noise = np.random.default_rng(2).standard_normal(n)
        return 0.18 * noise * np.sin(np.pi * t / t[-1]) ** 2
    if kind == "blip":
        n = int(0.06 * SR)
        t = np.arange(n) / SR
        return 0.05 * np.sin(2 * np.pi * 420 * t) * np.exp(-t * 40)
    return np.zeros(1)


def decode_audio(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


class Voice:
    """Озвучка через edge-tts; кэширует файлы, при отсутствии сети отключается."""

    def __init__(self, enabled: bool, cache: Path):
        self.enabled = enabled
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.warned = False

    def say(self, text: str, voice: str, rate="+0%", pitch="+0Hz") -> np.ndarray | None:
        if not self.enabled or not text.strip():
            return None
        import hashlib

        key = hashlib.md5(f"{voice}|{rate}|{pitch}|{text}".encode()).hexdigest()
        mp3 = self.cache / f"{key}.mp3"
        if not mp3.exists() or mp3.stat().st_size == 0:
            try:
                import edge_tts

                async def run():
                    kw = {"rate": rate, "pitch": pitch}
                    if os.environ.get("HTTPS_PROXY"):
                        kw["proxy"] = os.environ["HTTPS_PROXY"]
                    await edge_tts.Communicate(text, voice, **kw).save(str(mp3))

                asyncio.run(run())
            except Exception as e:  # noqa: BLE001
                if not self.warned:
                    print(f"[!] Озвучка недоступна ({type(e).__name__}: {e}). Собираю без голоса.", file=sys.stderr)
                    self.warned = True
                self.enabled = False
                mp3.unlink(missing_ok=True)
                return None
        a = decode_audio(str(mp3))
        nz = np.nonzero(np.abs(a) > 0.01)[0]  # срезаем тишину по краям
        if len(nz):
            a = a[max(0, nz[0] - 600): nz[-1] + 1200]
        return a


def mouth_track(audio: np.ndarray | None, text: str, frames: int, seed: int) -> list[str]:
    """Для каждого кадра — форма рта. С голосом — по громкости, без — по слогам."""
    if audio is not None and len(audio):
        hop = SR // FPS
        rms = np.array([np.sqrt(np.mean(audio[i * hop:(i + 1) * hop] ** 2) + 1e-9) for i in range(frames)])
        top = np.percentile(rms[rms > 0.005], 90) if np.any(rms > 0.005) else 1
        out = []
        for r in rms:
            v = r / top
            out.append("wide" if v > 0.75 else "open" if v > 0.3 else "closed")
        return out
    rng = random.Random(seed)
    out = []
    words = plain(text).split()
    for w in words:
        syl = max(1, len(w) // 2)
        for _ in range(syl):
            out += [rng.choice(["open", "wide"])] * 3 + ["closed"] * 2
        out += ["closed"] * 3
    return (out + ["closed"] * frames)[:frames]


# ─────────────────────────── таймлайн ───────────────────────────

@dataclass
class Actor:
    key: str
    kind: str
    name: str
    color: tuple
    voice: str
    pitch: str = "+0Hz"
    rate: str = "+0%"
    colors: tuple = ()
    x: float = 0.5  # доля ширины
    visible: bool = False
    mood: str = "neutral"
    flip: bool = False


@dataclass
class Segment:
    kind: str
    start: int  # кадр
    frames: int
    data: dict = field(default_factory=dict)


LIGHT_VOICES = {"man": "ar-SA-HamedNeural", "boy": "ar-SA-HamedNeural", "grandpa": "ar-SA-HamedNeural",
                "woman": "ar-SA-ZariyahNeural", "girl": "ar-SA-ZariyahNeural"}


class Episode:
    def __init__(self, spec: dict, voice: Voice):
        self.spec = spec
        self.voice = voice
        self.title = spec.get("title", "")
        self.narrator = spec.get("narrator", {"ar": "ar-SA-HamedNeural", "ru": "ru-RU-DmitryNeural"})
        self.actors: dict[str, Actor] = {}
        for k, c in spec["characters"].items():
            self.actors[k] = Actor(
                key=k, kind=c["type"], name=c.get("name", ""), color=tuple(c.get("color", (60, 120, 180))),
                voice=c.get("voice", LIGHT_VOICES[c["type"]]), pitch=c.get("pitch", "+0Hz"), rate=c.get("rate", "+0%"),
                colors=tuple(sorted((kk, tuple(v) if isinstance(v, list) else v) for kk, v in c.get("colors", {}).items())),
            )
        self.audio_events: list[tuple[int, np.ndarray]] = []  # (кадр, сэмплы)
        self.timeline: list[dict] = []  # на каждый кадр: состояние
        self.build()

    # --- построение покадрового состояния ---
    def build(self):
        st = {"scene": None, "clock": None, "caption": None, "fx": None}
        rng = random.Random(11)

        def actors_snapshot():
            return {k: (a.x, a.visible, a.mood, a.flip) for k, a in self.actors.items()}

        def push(n, **per_frame):
            base = len(self.timeline)
            for i in range(n):
                fr = {"scene": st["scene"], "clock": st["clock"], "caption": st["caption"], "actors": actors_snapshot(),
                      "talk": {}, "overlay": None, "fx": None}
                for k, fn in per_frame.items():
                    fr[k] = fn(i, n, base + i) if callable(fn) else fn
                self.timeline.append(fr)

        def at(frame_offset_s=0.0):
            return len(self.timeline) + int(frame_offset_s * FPS)

        def tts(text, voice, pitch="+0Hz", rate="+0%"):
            return self.voice.say(text, voice, rate, pitch)

        for b in self.spec["beats"]:
            if "scene" in b:
                prev = st["scene"]
                st["scene"] = b["scene"]
                st["clock"] = b.get("clock")
                st["caption"] = None
                for k, a in self.actors.items():
                    a.visible = k in b.get("cast", {})
                    if a.visible:
                        a.x = b["cast"][k]
                        a.mood = "neutral"
                        a.flip = a.x > 0.5
                if prev and not b.get("cut"):
                    push(int(0.35 * FPS), fx=lambda i, n, f: ("fadein", i / n))
                continue

            if "hook" in b:  # крупный текст поверх сцены (+ голос диктора)
                text = b["hook"]
                audio = tts(plain(b.get("speak", text)), self.narrator["ru"])
                dur = max(b.get("hold", 2.4), (len(audio) / SR + 0.6) if audio is not None else 0)
                self.audio_events.append((at(0), sfx("whoosh")))
                if audio is not None:
                    self.audio_events.append((at(0.2), audio))
                cap = big_caption(text, b.get("size", 78))
                push(int(dur * FPS), overlay=lambda i, n, f, cap=cap: ("caption", cap, min(1, i / 8)))
                continue

            if "enter" in b or "exit" in b:
                a = self.actors[b.get("enter") or b.get("exit")]
                entering = "enter" in b
                to = b.get("to", a.x)
                fr0 = -0.25 if to < 0.5 else 1.25
                start, end = (fr0, to) if entering else (a.x, fr0)
                a.visible = True
                a.flip = (end < start)
                n = int(b.get("time", 1.2) * FPS)
                self.audio_events.append((at(0), sfx("whoosh") * 0.6))
                for i in range(n):
                    t = (i + 1) / n
                    e = 1 - (1 - t) ** 2
                    a.x = start + (end - start) * e
                    push(1, walk={a.key: i})
                a.x = end
                if not entering:
                    a.visible = False
                else:
                    a.flip = a.x > 0.5
                continue

            if "mood" in b and "say" not in b:
                for k, m in b["mood"].items():
                    self.actors[k].mood = m
                continue

            if "say" in b:
                a = self.actors[b["say"]]
                if "mood" in b:
                    a.mood = b["mood"]
                audio = tts(b.get("speak", plain(b["ar"])), a.voice, a.pitch, a.rate)
                if audio is not None:
                    dur = len(audio) / SR + b.get("pause", 0.7)
                else:
                    dur = max(2.0, 0.07 * len(plain(b["ar"])) + 0.05 * len(b.get("ru", "")) + 1.2)
                dur = max(dur, b.get("hold", 0))
                n = int(dur * FPS)
                lead = int(0.15 * FPS)
                mt = mouth_track(audio, b["ar"], n - lead, rng.randint(0, 999))
                mt = ["closed"] * lead + mt
                if audio is not None:
                    self.audio_events.append((at(0.15), audio))
                else:
                    for i, m in enumerate(mt):
                        if m != "closed" and (i == 0 or mt[i - 1] == "closed"):
                            self.audio_events.append((at(0) + i, sfx("blip")))
                card = subtitle_card(a.name, a.color, b["ar"], b.get("tr", ""), b.get("ru", ""))
                push(n, talk=lambda i, n_, f, k=a.key, mt=mt: {k: mt[i]},
                     overlay=lambda i, n_, f, card=card: ("sub", card, min(1, i / 5)))
                continue

            if "card" in b:
                c = b["card"]
                img = word_card(c.get("label", "СЛОВО"), c["ar"], c.get("tr", ""), c.get("ru", ""))
                audio = tts(c.get("speak", plain(c["ar"])), self.narrator["ar"])
                dur = max(b.get("hold", 2.8), (len(audio) / SR + 1.6) if audio is not None else 0)
                self.audio_events.append((at(0), sfx("pop")))
                if audio is not None:
                    self.audio_events.append((at(0.4), audio))
                push(int(dur * FPS), overlay=lambda i, n, f, img=img: ("card", img, i))
                continue

            if "compare" in b:
                c = b["compare"]
                L, R = c["left"], c["right"]
                aL = tts(L.get("speak", plain(L["ar"])), self.narrator["ar"])
                aR = tts(R.get("speak", plain(R["ar"])), self.narrator["ar"])
                tL = (len(aL) / SR + 0.8) if aL is not None else 1.8
                tR = (len(aR) / SR + 1.4) if aR is not None else 2.4
                imgs = {k: compare_card(L, R, k) for k in (-1, 0, 1, 2)}
                self.audio_events.append((at(0), sfx("pop")))
                if aL is not None:
                    self.audio_events.append((at(0.4), aL))
                if aR is not None:
                    self.audio_events.append((at(0.4 + tL), aR))
                nL, nR = int((0.4 + tL) * FPS), int(tR * FPS)
                hold = int(b.get("hold", 1.2) * FPS)
                push(nL, overlay=lambda i, n, f: ("compare", imgs[0 if i > 10 else -1], i))
                push(nR, overlay=lambda i, n, f: ("compare", imgs[1], 99))
                push(hold, overlay=lambda i, n, f: ("compare", imgs[2], 99))
                continue

            if "rewind" in b:
                label = b["rewind"]
                self.audio_events.append((at(0), sfx("rewind")))
                push(int(1.3 * FPS), fx=lambda i, n, f, label=label: ("rewind", i / n, label))
                continue

            if "wait" in b:
                push(int(b["wait"] * FPS))
                continue

            raise ValueError(f"Непонятный шаг сценария: {b}")

        # финальная плашка «подпишись»
        outro = self.spec.get("outro", "Подпишись — арабский каждый день!")
        cap = big_caption(outro, 70)
        self.audio_events.append((at(0), sfx("pop")))
        audio = self.voice.say(plain(self.spec.get("outro_speak", outro)), self.narrator["ru"])
        if audio is not None:
            self.audio_events.append((at(0.2), audio))
        dur = max(2.6, (len(audio) / SR + 0.8) if audio is not None else 0)
        push(int(dur * FPS), overlay=lambda i, n, f: ("outro", cap, min(1, i / 8)))

    # --- отрисовка ---
    @functools.cached_property
    def header(self) -> Image.Image:
        im = Image.new("RGB", (W, HEADER_H), PAGE_BG)
        d = ImageDraw.Draw(im)
        f = font("Nunito-Black", 34)
        badge = self.spec.get("channel", "MY ARABIC")
        bw = tlen(f, badge) + 50
        d.rounded_rectangle([W / 2 - bw / 2, 26, W / 2 + bw / 2, 80], 27, fill=GOLD)
        draw_text(d, (W / 2, 52), badge, f, INK, anchor="mm")
        rich_text(d, W / 2, 98, self.title, font("Nunito-Black", 56), WHITE, GOLD, W - 80, line_gap=0.85)
        return im

    @functools.cached_property
    def footer(self) -> Image.Image:
        im = Image.new("RGB", (W, H - FOOTER_Y), PAGE_BG)
        d = ImageDraw.Draw(im)
        sub = self.spec.get("footer", "Учим арабский по мультикам")
        draw_text(d, (W / 2, 70), sub, font("Nunito-ExtraBold", 36), (170, 210, 205), anchor="mm")
        return im

    def render_frame(self, idx: int) -> Image.Image:
        fr = self.timeline[idx]
        frame = Image.new("RGB", (W, H), PAGE_BG)
        frame.paste(self.header, (0, 0))
        frame.paste(self.footer, (0, FOOTER_Y))

        scene = scene_bg(fr["scene"]).copy().convert("RGBA")
        t = idx / FPS
        if fr["clock"]:
            chip = clock_chip(fr["clock"], SCENES[fr["scene"]]["night"])
            scene.alpha_composite(chip, (10, 16))

        # персонажи — по возрастанию x, чтобы не было хаоса со слоями
        floor_y = int(SCENE_H * 0.80) + 120
        order = sorted(fr["actors"].items(), key=lambda kv: kv[1][0])
        for k, (x, vis, mood, flip) in order:
            if not vis:
                continue
            a = self.actors[k]
            mouth = fr["talk"].get(k, "closed")
            phase = (hash(k) % 100) / 100
            blink = ((t + phase * 3) % 3.4) < 0.12
            spr = sprite(a.kind, blink, mouth, mood, a.colors)
            sc = CHAR_TYPES[a.kind]["scale"] * 1.05
            if mouth != "closed":
                bob = math.sin(t * 14) * 3
            else:
                bob = math.sin(t * 2 * math.pi * 0.7 + phase * 6) * 4
            walk = fr.get("walk", {}) or {}
            if k in walk:
                bob = -abs(math.sin(walk[k] * 0.45)) * 22
            sw, sh = int(SPR_W * sc), int(SPR_H * sc)
            sq = 1 + (0.012 * math.sin(t * 2 * math.pi * 0.7 + phase * 6) if k not in walk else 0)
            img = spr.resize((sw, int(sh * sq)), Image.BILINEAR)
            if flip:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            px = int(x * W - sw / 2)
            py = int(floor_y - img.height + bob)
            scene.alpha_composite(img, (px, py)) if 0 <= px and px + sw <= W else _paste_clip(scene, img, px, py)

        ov = fr["overlay"]
        if ov and ov[0] in ("card", "compare"):
            # затемняем сцену под карточкой
            scene = Image.alpha_composite(scene, Image.new("RGBA", scene.size, (10, 10, 20, 110)))
            img, i = ov[1], ov[2]
            sc = pop_scale(i)
            if sc != 1:
                img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.BILINEAR)
            scene.alpha_composite(img, (int((W - img.width) / 2), int((SCENE_H - img.height) / 2)))
        if ov and ov[0] in ("caption", "outro"):
            img, alpha = ov[1], ov[2]
            if ov[0] == "outro":
                scene = Image.alpha_composite(scene, Image.new("RGBA", scene.size, (10, 10, 20, int(120 * alpha))))
            lay = Image.new("RGBA", scene.size, (0, 0, 0, 0))
            y = int(SCENE_H * 0.08) if ov[0] == "caption" else int((SCENE_H - img.height) / 2)
            lay.alpha_composite(img, (0, y + int((1 - alpha) * 40)))
            if alpha < 1:
                lay.putalpha(lay.getchannel("A").point(lambda v: int(v * alpha)))
            scene.alpha_composite(lay)

        scene = scene.convert("RGB")
        fx = fr["fx"]
        if fx and fx[0] == "rewind":
            scene = rewind_fx(scene, fx[1], fx[2], idx)
        if fx and fx[0] == "fadein":
            scene = Image.blend(Image.new("RGB", scene.size, (0, 0, 0)), scene, fx[1])

        # рамка сцены
        frame.paste(scene, (0, SCENE_Y))
        d = ImageDraw.Draw(frame)
        d.rectangle([0, SCENE_Y, W, SCENE_Y + 6], fill=GOLD)
        d.rectangle([0, SCENE_Y + SCENE_H - 6, W, SCENE_Y + SCENE_H], fill=GOLD)

        if ov and ov[0] == "sub":
            img, a = ov[1], ov[2]
            y = SUB_Y + int((1 - a) * 30) - 24
            frame.paste(img, (int((W - img.width) / 2), y), img)
        # прогресс-бар
        prog = (idx + 1) / len(self.timeline)
        d.rounded_rectangle([60, FOOTER_Y + 4, W - 60, FOOTER_Y + 16], 6, fill=(30, 80, 82))
        d.rounded_rectangle([60, FOOTER_Y + 4, 60 + (W - 120) * prog, FOOTER_Y + 16], 6, fill=GOLD)
        return frame

    # --- звук ---
    def mix(self) -> np.ndarray:
        n = int(len(self.timeline) / FPS * SR) + SR
        out = np.zeros(n, np.float32)
        bgm = music(n / SR, self.spec.get("music_seed", 3)) * self.spec.get("music_volume", 0.55)
        voice_mask = np.zeros(n, np.float32)
        for fr, a in self.audio_events:
            pos = int(fr / FPS * SR)
            a = a[: max(0, n - pos)]
            out[pos:pos + len(a)] += a
            if len(a) > SR * 0.3:  # это речь — приглушаем музыку
                voice_mask[pos:pos + len(a)] = 1
        k = int(0.25 * SR)
        voice_mask = np.convolve(voice_mask, np.ones(k) / k, mode="same")
        out += bgm[:n] * (1 - 0.6 * voice_mask)
        fade = int(0.8 * SR)
        out[-fade:] *= np.linspace(1, 0, fade)
        peak = np.max(np.abs(out)) or 1
        return (out / peak * 0.9).astype(np.float32)


def _paste_clip(dst, img, px, py):
    x0, y0 = max(0, -px), max(0, -py)
    x1, y1 = min(img.width, dst.width - px), min(img.height, dst.height - py)
    if x1 > x0 and y1 > y0:
        dst.alpha_composite(img.crop((x0, y0, x1, y1)), (px + x0, py + y0))


def pop_scale(i: int) -> float:
    if i >= 9:
        return 1.0
    t = i / 9
    return 0.55 + 0.45 * (1 - (1 - t) ** 3) + 0.08 * math.sin(t * math.pi)


def rewind_fx(img: Image.Image, p: float, label: str, idx: int) -> Image.Image:
    g = img.convert("L").convert("RGB")
    g = Image.blend(img, g, min(1, p * 3))
    arr = np.asarray(g).copy()
    rng = np.random.default_rng(idx)
    for _ in range(5):  # «дрожание» VHS
        y = rng.integers(0, arr.shape[0] - 40)
        arr[y:y + 30] = np.roll(arr[y:y + 30], rng.integers(-40, 40), axis=1)
    arr[::6] = (arr[::6] * 0.6).astype(np.uint8)
    out = Image.fromarray(arr)
    d = ImageDraw.Draw(out)
    cx, cy = W / 2, SCENE_H / 2
    d.rounded_rectangle([cx - 330, cy - 90, cx + 330, cy + 90], 30, fill=(20, 20, 30))
    rewind_icon(d, cx - 190, cy, 70, GOLD)
    draw_text(d, (cx - 120, cy - 2), label, font("Nunito-Black", 60), WHITE, anchor="lm")
    return out


# ─────────────────────────── сборка видео ───────────────────────────

def render(spec_path: Path, out_dir: Path, use_voice: bool, preview: bool = False) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    voice = Voice(use_voice, HERE / ".tts_cache")
    ep = Episode(spec, voice)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{spec_path.stem}.mp4"
    nframes = len(ep.timeline)
    print(f"→ {spec_path.name}: {nframes / FPS:.1f} c, {nframes} кадров, голос: {'да' if voice.enabled else 'нет'}")

    if preview:  # просто несколько кадров-картинок
        for i in range(0, nframes, max(1, nframes // 12)):
            ep.render_frame(i).save(out_dir / f"{spec_path.stem}_{i:04d}.jpg", quality=85)
        return out_dir

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        import wave

        pcm = (ep.mix() * 32767).astype(np.int16)
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(nframes):
            proc.stdin.write(ep.render_frame(i).tobytes())
            if i % 150 == 0:
                print(f"   кадр {i}/{nframes}")
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg завершился с ошибкой")
    print(f"✓ {out}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episodes", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--no-voice", action="store_true", help="не озвучивать (только музыка и звуки)")
    ap.add_argument("--preview", action="store_true", help="сохранить несколько кадров JPG вместо видео")
    args = ap.parse_args()
    for ep in args.episodes:
        render(ep, args.out, not args.no_voice, args.preview)


if __name__ == "__main__":
    main()

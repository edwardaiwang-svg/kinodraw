"""Plain sans text for the stick look: labels, titles, big numbers, captions (English and Chinese).

Arimo Bold for Latin text and Noto Sans SC Bold for Chinese (both OFL, bundled in assets/fonts); a line mixing
the two switches font per character. Text is black, or red with a white outline for emphasis.
"""
from __future__ import annotations

import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .. import ink

LATIN, CJK = ink.EN_CAPTION[0], ink.ZH_CAPTION[0]


@lru_cache(maxsize=64)
def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, int(size), layout_engine=ImageFont.Layout.BASIC)      # as ink.font


@lru_cache(maxsize=1)
def _latin_cmap():
    from fontTools.ttLib import TTFont
    return frozenset(TTFont(LATIN).getBestCmap())


def runs(text: str, size: int, lang: str):
    """[(substring, font)]: Chinese text is set in Noto Sans SC throughout; English in Arimo, with any character
    Arimo lacks (CJK) in Noto Sans SC."""
    if lang == 'zh':
        return [(text, font(CJK, size))]
    out = []
    for ch in text:
        path = LATIN if (ord(ch) in _latin_cmap() or ch.isspace()) else CJK
        if out and out[-1][1] == path:
            out[-1][0] += ch
        else:
            out.append([ch, path])
    return [(t, font(p, size)) for t, p in out]


def width(text: str, size: int, lang: str) -> float:
    return sum(f.getlength(t) for t, f in runs(text, size, lang))


def wrap(text: str, size: int, lang: str, max_w: float) -> list[str]:
    """Greedy wrap: whole words in English, characters in Chinese (no line starts with closing punctuation)."""
    units = re.findall(r'\S+\s*', text) if lang != 'zh' else re.findall(r"[A-Za-z0-9$.,%×\-–/+']+\s*|.", text)
    lines, cur = [], ''
    for u in units:
        trial = cur + u
        if cur and width(trial.rstrip(), size, lang) > max_w:
            if lang == 'zh' and re.match(r'[，。！？；：、）」』”’%]', u):
                cur = trial
                continue
            lines.append(cur.rstrip())
            cur = u.lstrip() if lang != 'zh' else u
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or ['']


def fit(text: str, lang: str, max_w: float, max_lines: int, size: int, min_size: int = 24):
    """(lines, size): the largest size <= ``size`` at which ``text`` wraps into ``max_lines`` lines."""
    while True:
        lines = wrap(text, size, lang, max_w)
        if (len(lines) <= max_lines and max(width(ln, size, lang) for ln in lines) <= max_w) or size <= min_size:
            return lines[:max_lines] if size <= min_size else lines, size
        size -= 2


@lru_cache(maxsize=1024)
def block(text: str, lang: str, size: int, max_w: float = 1e9, max_lines: int = 3, color=(0, 0, 0),
          outline: int = 0, outline_color=(255, 255, 255), align: str = 'center', line_gap: float = 1.16,
          min_size: int = 24, upper: bool = False) -> Image.Image:
    """Text set as an RGBA image (wrapped and shrunk to fit ``max_w`` x ``max_lines``)."""
    if upper and lang != 'zh':
        text = text.upper()
    lines, size = fit(text, lang, max_w, max_lines, size, min_size)
    asc, desc = font(LATIN if lang != 'zh' else CJK, size).getmetrics()
    lh = int(size * line_gap)
    pad = outline + 4
    widths = [width(ln, size, lang) for ln in lines]
    w = int(max(widths)) + 2 * pad + 2
    h = lh * (len(lines) - 1) + asc + desc + 2 * pad
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        x = pad + {'left': 0, 'center': (w - 2 * pad - widths[i]) / 2, 'right': w - 2 * pad - widths[i]}[align]
        y = pad + i * lh
        for part, f in runs(ln, size, lang):
            d.text((x, y), part, font=f, fill=tuple(color) + (255,),
                   stroke_width=outline, stroke_fill=tuple(outline_color) + (255,) if outline else None)
            x += f.getlength(part)
    return img


def caption(text: str, lang: str) -> Image.Image:
    """A burned-in caption: black on a white outline, at most two lines across 1500 px."""
    return block(text, lang, 46 if lang != 'zh' else 48, max_w=1500, max_lines=2, outline=6, min_size=34)

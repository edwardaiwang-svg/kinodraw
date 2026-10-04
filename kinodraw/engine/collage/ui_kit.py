"""Interface pieces for promo scenes, drawn by code: phone, chat bubbles, badge, form, link chip, button, stamp,
traffic light, seat slots, avatars and paper labels.

Each piece is an SVG sized from its text (measured with the same font file resvg uses), rasterized with the bundled
fonts only, so it looks the same on every computer. The words on a piece come from the script, the storyboard's
brand, or the fixed labels below; decorative chat lines come from a fixed bank, never from a model.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

import resvg_py
from PIL import Image, ImageFont

from . import puppet

FONTS = Path(__file__).resolve().parents[2] / 'assets' / 'fonts'
SANS, HAND, ZH_SANS, ZH_HAND = 'Arimo', 'Playpen Sans', 'Noto Sans SC', 'Doodle Kai Medium'
FILES = {SANS: 'Arimo-Bold.ttf', HAND: 'PlaypenSans-Bold.ttf', ZH_SANS: 'NotoSansSC-Bold.otf', ZH_HAND: 'DoodleKai-Medium.ttf'}
INK, PAPER, NAVY, TEAL, ORANGE, GREEN = '#1B1B1B', '#FBF7EE', '#2F3A6B', '#3E8E8C', '#EF7B3A', '#3FA36B'

LABELS = {  # fixed interface words, per language
    'en': {'continue': 'Continue →', 'in': "I'm in!", 'out': "Can't make it", 'going': '{n} of {m} going',
           'min': 'min. {n}', 'free': 'FREE', 'on': "IT'S ON!", 'you_in': '✓ You\'re in!', 'script': 'Script',
           'title': 'Title'},
    'zh': {'continue': '继续 →', 'in': '我参加！', 'out': '去不了', 'going': '{m}人中{n}人参加', 'min': '至少{n}人',
           'free': '免费', 'on': '成了！', 'you_in': '✓ 已报名', 'script': '脚本'},
}
NAMES = ['Max', 'Lara', 'Tim', 'Aisha', 'Sem']   # who writes in the chat scenes (the same in every language)
CHATTER = {  # decorative group-chat lines for problem scenes (a fixed bank, picked by seed)
    'en': ['Saturday?', 'Hello...??', 'who else is coming?', 'maybe', 'can I bring someone?', 'could we do Sunday?',
           "can't do Saturday", 'what are we doing?', 'sorry, only just saw this!', 'wait, what\'s the plan?',
           'who is even organising this', 'depends on who\'s coming', 'I\'ll ask Tim', 'haha yes!', 'am I still in?'],
    'zh': ['周六？', '有人吗…？？', '还有谁来？', '也许吧', '能带朋友吗？', '周日行不行？', '周六我不行', '我们到底干嘛？',
           '抱歉，刚看到！', '等等，计划是什么？', '到底谁在组织啊', '看谁来吧', '我问问小林', '哈哈好啊！', '我还算在内吗？'],
}


def _family(lang, hand=False):
    return (ZH_HAND if hand else ZH_SANS) if lang == 'zh' else (HAND if hand else SANS)


@lru_cache(maxsize=16)
def _font(family, size):
    return ImageFont.truetype(str(FONTS / FILES[family]), size)


def text_width(text, family, size):
    return _font(family, size).getlength(text)


def _wrap(text, family, size, width):
    words, lines, line = (list(text) if family in (ZH_SANS, ZH_HAND) else text.split()), [], ''
    sep = '' if family in (ZH_SANS, ZH_HAND) else ' '
    for w in words:
        trial = f'{line}{sep}{w}' if line else w
        if line and text_width(trial, family, size) > width:
            lines.append(line)
            line = w
        else:
            line = trial
    return lines + ([line] if line else [])


def _text(x, y, text, family, size, fill=INK, anchor='start', weight=700):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{escape(text)}</text>')


def _doc(w, h, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}">{body}</svg>'


@lru_cache(maxsize=1024)
def raster(doc: str, scale: float = 1.0) -> Image.Image:
    """Rasterize one of this module's SVGs with the bundled fonts only (no system fonts: same pixels everywhere)."""
    files = [str(FONTS / f) for f in FILES.values()]
    png = resvg_py.svg_to_bytes(svg_string=doc, zoom=scale, skip_system_fonts=True, font_files=files,
                                sans_serif_family=SANS, font_family=SANS)
    return Image.open(io.BytesIO(png)).convert('RGBA')


# --------------------------------------------------------------------- pieces
def chat_bubble(text, lang='en', side='left', name=None, name_color=TEAL, width=300) -> str:
    fam, size = _family(lang), 22
    lines = _wrap(text, fam, size, width - 36)
    tw = max(text_width(line, fam, size) for line in lines)
    top = 30 if name else 16
    w, h = tw + 40, top + 30 * len(lines) + 20
    fill = '#DCF4C9' if side == 'right' else '#FFFFFF'
    tail = (f'<path d="M{w - 26} {h - 2} l18 12 l-6 -18 Z"' if side == 'right' else f'<path d="M26 {h - 2} l-18 12 l6 -18 Z"')
    body = (f'<rect x="4" y="4" width="{w - 8:.1f}" height="{h - 8:.1f}" rx="18" fill="{fill}" stroke="{INK}" '
            f'stroke-width="3"/>{tail} fill="{fill}" stroke="{INK}" stroke-width="3" stroke-linejoin="round"/>')
    if name:
        body += _text(20, 26, name, fam, 16, fill=name_color)
    for k, line in enumerate(lines):
        body += _text(20, top + 22 + 30 * k, line, fam, size)
    return _doc(w, h + 14, body)


def badge(n) -> str:
    label = str(n)
    w = max(52, 22 + 16 * len(label))
    return _doc(w + 8, 60, f'<rect x="4" y="4" width="{w}" height="52" rx="26" fill="#E5484D" stroke="#FFFFFF" '
                           f'stroke-width="5"/>' + _text(4 + w / 2, 40, label, SANS, 28, fill='#FFFFFF', anchor='middle'))


def phone(title='Friends', subtitle='', lang='en', w=380, h=700, screen='#F3EFE6') -> str:
    """An empty phone with a group-chat header; bubbles are composited onto its screen box ``screen_box(w, h)``."""
    fam = _family(lang)
    body = (f'<rect x="6" y="6" width="{w - 12}" height="{h - 12}" rx="54" fill="{NAVY}" stroke="{INK}" stroke-width="5"/>'
            f'<rect x="24" y="24" width="{w - 48}" height="{h - 48}" rx="38" fill="{screen}"/>'
            f'<path d="M24 118 V62 Q24 24 62 24 H{w - 62} Q{w - 24} 24 {w - 24} 62 V118 Z" fill="{TEAL}"/>'
            f'<circle cx="70" cy="80" r="22" fill="#F4CBA6" stroke="#FFFFFF" stroke-width="3"/>'
            + _text(104, 78, title, fam, 22, fill='#FFFFFF')
            + (_text(104, 102, subtitle, fam, 14, fill='#E6F2F1', weight=400) if subtitle else ''))
    return _doc(w, h, body)


def screen_box(w=380, h=700):
    """Where messages go inside ``phone``: (left, top, right, bottom)."""
    return 36, 132, w - 36, h - 40


def form_card(question, fields, lang='en', w=620) -> str:
    """A paper card with a question and fields; ``fields`` = [(label, text shown so far, show caret)]."""
    fam, hand = _family(lang), _family(lang, hand=True)
    h = 150 + 92 * len(fields)
    body = (f'<rect x="6" y="6" width="{w - 12}" height="{h - 12}" rx="10" fill="{PAPER}" stroke="#D9D0BF" stroke-width="3"/>'
            + _text(40, 66, question, fam, 30))
    for k, (label, value, caret) in enumerate(fields):
        y = 96 + 92 * k
        body += _text(40, y + 16, label, fam, 16, fill='#6A6A6A', weight=400)
        body += f'<rect x="40" y="{y + 26}" width="{w - 80}" height="48" rx="8" fill="#FFFFFF" stroke="#CFC6B4" stroke-width="3"/>'
        body += _text(56, y + 60, value, hand, 26)
        if caret:
            cx = 58 + text_width(value, hand, 26)
            body += f'<rect x="{cx:.1f}" y="{y + 36}" width="3" height="30" fill="{INK}"/>'
    return _doc(w, h, body)


def button(text, lang='en', style='primary', pressed=False) -> str:
    fam, size = _family(lang), 28
    w, h = text_width(text, fam, size) + 72, 72
    fill, fg, border = {'primary': (ORANGE, '#FFFFFF', INK), 'secondary': ('#FFFFFF', '#555555', '#9A9A9A'),
                        'done': (GREEN, '#FFFFFF', INK)}[style]
    dy = 4 if pressed else 0
    body = ('' if pressed else f'<rect x="6" y="12" width="{w - 12}" height="{h - 12}" rx="{(h - 12) / 2}" fill="{INK}" opacity="0.25"/>')
    body += (f'<rect x="6" y="{6 + dy}" width="{w - 12}" height="{h - 18}" rx="{(h - 18) / 2}" fill="{fill}" '
             f'stroke="{border}" stroke-width="3"/>' + _text(w / 2, 46 + dy, text, fam, size, fill=fg, anchor='middle'))
    return _doc(w, h, body)


def link_chip(text, lang='en') -> str:
    fam, size = _family(lang), 30
    w, h = text_width(text, fam, size) + 96, 76
    icon = (f'<g transform="translate(26 26)" fill="none" stroke="{ORANGE}" stroke-width="5" stroke-linecap="round">'
            f'<path d="M10 16 l8 -8 a8 8 0 0 1 11 11 l-5 5"/><path d="M16 10 l-5 5 a8 8 0 0 0 11 11 l8 -8"/></g>')
    return _doc(w, h, f'<rect x="4" y="4" width="{w - 8}" height="{h - 8}" rx="10" fill="#FFFFFF" stroke="#D9D0BF" '
                      f'stroke-width="3"/>{icon}' + _text(76, 50, text, fam, size))


def app_window(title, lang='en', w=1240, h=760) -> str:
    """A desktop app's window on paper: a title bar with three dots and the app's name, an empty body."""
    dots = ''.join(f'<circle cx="{44 + 32 * k}" cy="37" r="11" fill="{c}" stroke="{INK}" stroke-width="2.5"/>'
                   for k, c in enumerate(('#E5484D', '#F2C14E', '#46B96E')))
    body = (f'<rect x="6" y="6" width="{w - 12}" height="{h - 12}" rx="20" fill="{PAPER}" stroke="{INK}" stroke-width="5"/>'
            f'<path d="M6 70 V26 Q6 6 26 6 H{w - 26} Q{w - 6} 6 {w - 6} 26 V70 Z" fill="#E6DFCF" stroke="{INK}" '
            f'stroke-width="5"/>{dots}' + _text(w / 2, 48, title, _family(lang), 28, anchor='middle'))
    return _doc(w, h, body)


def text_area(lines, lang='en', w=540, h=560, size=22, title='') -> str:
    """A text box with a small label above it, showing ``lines`` (empty: just the box)."""
    fam = _family(lang)
    top = 40 if title else 0
    body = (_text(8, 26, title, fam, 22, fill='#6A6A6A') if title else '')
    body += (f'<rect x="4" y="{top + 4}" width="{w - 8}" height="{h - top - 8}" rx="12" fill="#FFFFFF" stroke="#CFC6B4" '
             f'stroke-width="3"/>')
    for k, line in enumerate(lines):
        body += _text(26, top + 46 + size * 1.5 * k, line, fam, size, fill='#2B2B2B', weight=400)
    return _doc(w, h, body)


def wrap(text, lang='en', size=22, width=480, hand=False) -> list[str]:
    """``text`` broken into lines no wider than ``width`` in the kit's font."""
    return _wrap(text, _family(lang, hand), size, width)


def script_page(lines, lang='en', w=600, h=780, size=30) -> str:
    """A sheet of lined paper with handwritten ``lines`` (something the viewer wrote)."""
    fam, gap = _family(lang, hand=True), round(size * 1.55)
    body = f'<rect x="6" y="6" width="{w - 12}" height="{h - 12}" rx="6" fill="#FFFDF7" stroke="#D9D0BF" stroke-width="3"/>'
    body += ''.join(f'<path d="M24 {y} H{w - 24}" stroke="#BCD3EA" stroke-width="2"/>' for y in range(96, h - 30, gap))
    body += f'<path d="M86 20 V{h - 20}" stroke="#F0A3A3" stroke-width="3"/>'
    for k, line in enumerate(lines):
        body += _text(104, 96 - 8 + gap * k, line, fam, size, fill='#24324F')
    return _doc(w, h, body)


def page_line_box(lines, k, a, b, lang='en', size=30) -> tuple[float, float, float]:
    """Where characters a..b of line ``k`` of ``script_page`` sit: (x0, x1, baseline y), in the page's pixels."""
    fam, gap = _family(lang, hand=True), round(size * 1.55)
    x0 = 104 + text_width(lines[k][:a], fam, size)
    return x0, x0 + text_width(lines[k][a:b], fam, size), 96 - 8 + gap * k


def label(text, lang='en', hand=True, size=30, color=INK, paper='#FFFFFF') -> str:
    """A torn paper label (handwriting by default), for sticker names and feature chips."""
    fam = _family(lang, hand)
    w, h = text_width(text, fam, size) + 48, size + 36
    edge = ' '.join(f'{x:.0f},{(4 if k % 2 else 0) + h - 6:.0f}' for k, x in enumerate(range(int(w) - 6, 4, -14)))
    body = (f'<polygon points="4,6 {w - 6:.0f},4 {edge} 6,{h - 4:.0f}" fill="{paper}" stroke="#D4CBB8" stroke-width="2"/>'
            + _text(24, h / 2 + size * 0.36, text, fam, size, fill=color))
    return _doc(w, h, body)


def credit_slip(line, url, lang='en', color='#55606A') -> str:
    """The video's end credit on a small torn paper slip: "Made with ..." in handwriting, the address under it."""
    fam = _family(lang, hand=True)
    w, h = max(text_width(line, fam, 34), text_width(url, SANS, 22)) + 56, 104
    edge = ' '.join(f'{x:.0f},{(4 if k % 2 else 0) + h - 6:.0f}' for k, x in enumerate(range(int(w) - 6, 4, -14)))
    body = (f'<polygon points="4,6 {w - 6:.0f},4 {edge} 6,{h - 4:.0f}" fill="{PAPER}" stroke="#D4CBB8" stroke-width="2"/>'
            + _text(w / 2, 48, line, fam, 34, fill=color, anchor='middle')
            + _text(w / 2, 82, url, SANS, 22, fill=color, anchor='middle'))
    return _doc(w, h, body)


def stamp(text, lang='en', color=GREEN) -> str:
    fam, size = _family(lang), 58
    w, h = text_width(text, fam, size) + 72, 112
    body = (f'<rect x="8" y="8" width="{w - 16}" height="{h - 16}" rx="12" fill="none" stroke="{color}" stroke-width="7"/>'
            f'<rect x="18" y="18" width="{w - 36}" height="{h - 36}" rx="8" fill="none" stroke="{color}" stroke-width="3"/>'
            + _text(w / 2, h / 2 + size * 0.35, text, fam, size, fill=color, anchor='middle'))
    return _doc(w, h, f'<g opacity="0.92">{body}</g>')


def traffic_light(state='red') -> str:
    lit = {'red': '#E5484D', 'yellow': '#F2C14E', 'green': '#46B96E'}
    body = f'<rect x="10" y="10" width="160" height="400" rx="42" fill="{NAVY}" stroke="{INK}" stroke-width="5"/>'
    for k, name in enumerate(('red', 'yellow', 'green')):
        on = name == state
        body += (f'<circle cx="90" cy="{86 + 124 * k}" r="48" fill="{lit[name] if on else "#4A4F63"}" stroke="{INK}" '
                 f'stroke-width="4"/>')
        if on:
            body += f'<circle cx="74" cy="{70 + 124 * k}" r="12" fill="#FFFFFF" opacity="0.55"/>'
    return _doc(180, 420, body)


def slots(total, filled, minimum, lang='en') -> str:
    """Seats in a row with a minimum marker; avatars are composited onto the filled seats (``seat_centers``)."""
    w, h = 90 * total + 60, 190
    body = ''
    for k in range(total):
        x = 60 + 90 * k
        dash = '' if k < filled else ' stroke-dasharray="7 7"'
        body += f'<circle cx="{x}" cy="70" r="36" fill="{"#FFFFFF" if k < filled else "none"}" stroke="#9A9486" stroke-width="3"{dash}/>'
    mx = 60 + 90 * minimum - 45
    body += f'<path d="M{mx} 16 V132" stroke="{ORANGE}" stroke-width="5" stroke-linecap="round"/>'
    body += _text(mx - 10, 172, LABELS[lang]['min'].format(n=minimum), _family(lang, hand=True), 28, fill=ORANGE, anchor='end')
    return _doc(w, h, body)


def seat_centers(total):
    return [(60 + 90 * k, 70) for k in range(total)]


def mark(ok=True) -> str:
    color, path = (GREEN, 'M16 29 l8 8 l16 -18') if ok else ('#8F8F8F', 'M18 18 l20 20 M38 18 l-20 20')
    return _doc(56, 56, f'<circle cx="28" cy="28" r="24" fill="{color}" stroke="#FFFFFF" stroke-width="4"/>'
                        f'<path d="{path}" fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round" '
                        f'stroke-linejoin="round"/>')


def avatar(k: int, height=150) -> Image.Image:
    """A friend's face: the puppet's head in one of several looks (varied, never a real person), cropped square."""
    looks = [('breeze', {}), ('reader', {'glasses': False}), ('sunny', {'style': 'bob', 'hair': '#3B2A20'}),
             ('breeze', {'skin': '#8D5A3B', 'style': 'bun', 'hair': '#1E1612'}), ('reader', {'skin': '#E9B48F'}),
             ('sunny', {'skin': '#B97B55', 'hat': '#4C7BD9', 'pompom': '#9DB8F0'})]
    preset, colors = looks[k % len(looks)]
    full = puppet.raster('stand', ('smile', 'happy', 'smile', 'wonder')[k % 4], 0, preset, tuple(colors.items()),
                         height=height * 3)
    return full.crop((int(full.width * .2), int(full.height * .1), int(full.width * .8), int(full.height * .56)))


def chatter(lang, seed: int, n: int) -> list[str]:
    bank = CHATTER[lang]
    return [bank[(seed * 7 + 3 * k) % len(bank)] for k in range(n)]

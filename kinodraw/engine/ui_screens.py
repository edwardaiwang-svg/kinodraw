"""Drawing device screens and message threads (kinodraw/ui_screens.py reads them from the script).

``timed(prod)`` turns the script's screen moments into timed ones for a hybrid production (the time each element is
named), ``overlay(prod, image, t)`` draws the live one over the frame: a phone (portrait) or a laptop or tablet
(landscape) on the paper, its app bar naming the app, each element drawn on the word that names it and lit for a
moment (a finger or a cursor taps buttons and rows), or a messages screen (the thread's name, bubbles left for others
and right for the phone's owner, small timestamps, emoji drawn in colour inside the bubble). The caption is drawn
again on top, so the words being read stay readable. A screen comes and goes by a cut.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .. import ui_screens

FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'
UI_FONT = FONT_DIR / 'Arimo-Bold.ttf'
CODE_FONT = FONT_DIR / 'JetBrainsMono-Medium.ttf'
EMOJI_FONTS = ('/System/Library/Fonts/Apple Color Emoji.ttc', '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
               '/usr/share/fonts/noto/NotoColorEmoji.ttf', 'C:/Windows/Fonts/seguiemj.ttf')
LIT = 1.4                 # seconds an element stays lit after its word
MIN_HOLD = 2.2            # a screen stays at least this long
TAIL = .6                 # and this long after its last word
BRIDGE = 2.5              # a gap this short between two screens of one device keeps the device on screen
SWAP = .6                 # nor this short a gap before another device: a cut, never a flash of the board
PHONE_FIRST = 1.8         # a chat log's message shows on the phone this long before the cut to its sender
CUT_MIN = 1.0             # when the sender is heard at least this much longer
INK = (34, 38, 46)
GLASS = (250, 251, 253)
SOFT = (232, 236, 242)
GREEN = (46, 160, 90)
DOT = {'green': (52, 168, 83), 'yellow': (240, 190, 30), 'red': (219, 68, 55), 'orange': (245, 140, 30),
       'blue': (66, 133, 244), 'purple': (150, 80, 200), 'grey': (150, 150, 150), 'gray': (150, 150, 150),
       'pink': (236, 110, 160), 'white': (245, 245, 245), 'black': (30, 30, 30)}


@lru_cache(maxsize=64)
def _font(size: int, code: bool = False):
    return ImageFont.truetype(str(CODE_FONT if code else UI_FONT), max(6, int(size)))


@lru_cache(maxsize=1)
def _emoji_font():
    for path in EMOJI_FONTS:
        try:
            return ImageFont.truetype(path, 109 if 'seguiemj' in path or 'Noto' in path else 160)
        except OSError:
            continue
    return None


@lru_cache(maxsize=256)
def _emoji(char: str, size: int):
    """An emoji as a colour picture ``size`` px tall: from a colour emoji font, else a drawn smiley disc (never a
    missing-glyph box)."""
    font = _emoji_font()
    if font is not None:
        try:
            box = font.getbbox(char)
            w, h = box[2] - box[0], box[3] - box[1]
            if w > 4 and h > 4:
                tile = Image.new('RGBA', (w + 8, h + 8), (0, 0, 0, 0))
                ImageDraw.Draw(tile).text((4 - box[0], 4 - box[1]), char, font=font, embedded_color=True)
                if tile.getbbox():
                    return tile.resize((max(1, round(size * tile.width / tile.height)), size), Image.LANCZOS)
        except (OSError, ValueError):
            pass
    tile = Image.new('RGBA', (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    seed = int(hashlib.md5(char.encode()).hexdigest()[:6], 16)
    hue = ((seed % 5) * 47 + 30) % 360
    fill = ImageColor.getrgb(f'hsl({hue}, 80%, 60%)')
    d.ellipse((8, 8, size * 4 - 8, size * 4 - 8), fill=fill, outline=INK, width=8)
    d.ellipse((size * 1.2, size * 1.3, size * 1.6, size * 1.8), fill=INK)
    d.ellipse((size * 2.4, size * 1.3, size * 2.8, size * 1.8), fill=INK)
    d.arc((size, size * 1.6, size * 3, size * 3.1), 20, 160, fill=INK, width=10)
    return tile.resize((size, size), Image.LANCZOS)


def _runs(text: str):
    """(is emoji, piece) runs of ``text``; variation selectors dropped."""
    out, last = [], 0
    for m in ui_screens.EMOJI.finditer(text):
        if m.start() > last:
            out.append((False, text[last:m.start()]))
        piece = m.group().replace('\ufe0f', '')
        if piece.strip('\u200d'):
            out.append((True, piece))
        last = m.end()
    if last < len(text):
        out.append((False, text[last:]))
    return out


def _width(text: str, size: int, code=False) -> float:
    font = _font(size, code)
    return sum(_emoji(p, round(size * 1.35)).width + size * .12 if e else font.getlength(p) for e, p in _runs(text))


def _text(layer, xy, text, size, fill, code=False, anchor_right=False):
    """Text with emoji pictures inline, top-left at ``xy`` (or ending at x when ``anchor_right``)."""
    x, y = xy
    if anchor_right:
        x -= _width(text, size, code)
    draw = ImageDraw.Draw(layer)
    font = _font(size, code)
    for emoji, piece in _runs(text):
        if emoji:
            pic = _emoji(piece, round(size * 1.35))
            layer.alpha_composite(pic, (round(x + size * .06), round(y - size * .1)))
            x += pic.width + size * .12
        else:
            draw.text((x, y), piece, font=font, fill=fill)
            x += font.getlength(piece)


def _wrap(text: str, size: int, width: float, code=False) -> list[str]:
    rows, row = [], ''
    for word in text.split():
        trial = (row + ' ' + word).strip()
        if row and _width(trial, size, code) > width:
            rows.append(row)
            row = word
        else:
            row = trial
    if row:
        rows.append(row)
    return rows or ['']


# ------------------------------------------------------------------ timing
def moments_for(episode, tl, lang, project_dir) -> list[dict]:
    """The script's screen moments with times ('start', 'end', and 't' on each element: when it is named), for any
    renderer (the whiteboard's Production or the HybridProduction); written to build/ui-screens.json. English word
    lists: other languages get none."""
    if lang not in ('en', None) or not any(b.get('char_times') for b in (tl.get('beats') or {}).values()):
        return []
    from ..director.v3.semantics import beats as read_beats
    from .. import speech
    from ..numbers import normalize
    from ..director.v3 import arc
    config = Path(project_dir) / 'project.json'
    plan = (json.loads(config.read_text(encoding='utf-8')).get('plan_v3') or {}) if config.is_file() else {}
    by_id = {b['id']: b for b in read_beats(episode, lang)}
    order = [b for b in tl['beat_order'] if b in by_id]
    labels = speech.screenplay_labels(by_id[b]['text'] for b in order)
    found = ui_screens.read([(b, by_id[b]['text']) for b in order], plan.get('cast') or [], labels)
    stop = tl['end_card']['start']

    def at(bid, pos):
        timing = tl['beats'][bid]
        ct = timing.get('char_times')
        if not ct:
            return timing['start']
        display, spoken = by_id[bid]['text'], by_id[bid]['spoken']
        reading = normalize(display, lang)
        off = min(reading.to_spoken(pos), max(0, len(spoken) - 1)) if reading.spoken == spoken else \
            arc.spoken_offset(display, spoken, pos)
        return timing['start'] + ct[min(off, len(ct) - 1)]
    out = []
    for m in found:
        bid = m['beat']
        start = max(tl['beats'][bid]['start'], at(bid, m['at']) - .15)
        end = at(bid, max(m['at'], m['until'] - 1)) + TAIL
        if m.get('until_beat'):
            end = max(end, tl['beats'][m['until_beat']]['end'] + .2)
            m['status_t'] = tl['beats'][m['until_beat']]['start']
        end = max(end, start + MIN_HOLD)
        for e in m['elements']:
            e['t'] = at(bid, e['at']) + (.6 if e.get('after') else 0.)
        m['start'], m['end'] = start, min(end, stop)
        out.append(m)
    for a, b in zip(out, out[1:]):
        a['end'] = min(a['end'], b['start'])                 # the next screen takes over
        gap = b['start'] - a['end']
        if not a.get('chat_log') and 0 < gap <= (BRIDGE if a['device'] == b['device'] else SWAP):
            a['end'] = b['start']                            # the same device stays: only what it shows changes;
                                                             # another device cuts straight in
    for m in out:                                            # a chat log cuts away to its sender (Storybook):
        said = tl['beats'][m['beat']]['end'] - m['start']     # the bubble first, then them, while they are heard
        if m.get('chat_log') and m.get('sender') and said >= PHONE_FIRST + CUT_MIN:
            m['end'] = min(m['end'], m['start'] + PHONE_FIRST)
    out = [m for m in out if m['end'] - m['start'] > .3]
    if out:
        rows = [{'start': round(m['start'], 3), 'end': round(m['end'], 3), 'kind': m['kind'], 'device': m['device'],
                 'beat': m['beat'], 'text': m.get('text') or '', 'strings': ui_screens.drawn_strings(m)} for m in out]
        build = Path(project_dir) / 'build'
        build.mkdir(parents=True, exist_ok=True)
        (build / 'ui-screens.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def live(moments, t):
    return next((m for m in moments if m['start'] <= t < m['end']), None)


def cover(prod, image, t, caption=False):
    """The frame with the screen moment live at ``t`` drawn over it on the renderer's paper: ``prod`` has
    ui_moments, size and the whiteboard skin (``prod.skin``, or a hybrid's ``prod.whiteboard.skin``). With
    ``caption`` the hybrid's caption is drawn again on top (the whiteboard draws its own after this)."""
    moment = live(getattr(prod, 'ui_moments', None) or (), t)
    if moment is None:
        return image
    board_of = getattr(prod, 'whiteboard', prod)
    w, h = prod.size
    style = getattr(prod, 'style', None) or {}
    palette = {k: ImageColor.getrgb(v)[:3] for k, v in (style.get('palette') or {}).items()}
    paper = board_of.skin.background(w, h).convert('RGBA').copy()
    paper.alpha_composite(draw(prod.size, moment, t, palette))
    base = image.convert('RGBA')
    base.alpha_composite(paper)                  # a cut in and out: never half a screen over half a face
    if caption:
        prod.whiteboard._caption(base, t, prod.caption_look, prod.caption_accent)
    return base.convert(image.mode)


# ------------------------------------------------------------------ drawing
def draw(size, moment, t, palette=None, paper=None) -> Image.Image:
    """The device and its screen for a moment at ``t`` (RGBA, clear around it; on ``paper`` when given)."""
    w, h = size
    k = 2                                                     # drawn at twice the size, then smoothed down
    layer = Image.new('RGBA', (w * k, h * k), (tuple(_rgb(paper)) + (255,)) if paper is not None else (0, 0, 0, 0))
    accent = _accent(palette)
    device = moment.get('device') or 'phone'
    d = ImageDraw.Draw(layer)
    if device == 'phone':
        sh = .74 * h * k                                     # clear of the caption band below
        sw = sh * .58
        x0, y0 = (w * k - sw) / 2, .025 * h * k
        d.rounded_rectangle((x0 + 10 * k, y0 + 12 * k, x0 + sw + 10 * k, y0 + sh + 12 * k), sw * .1, fill=(0, 0, 0, 40))
        d.rounded_rectangle((x0, y0, x0 + sw, y0 + sh), sw * .1, fill=(36, 38, 44, 255), outline=INK, width=3 * k)
        screen = (x0 + sw * .05, y0 + sw * .05, x0 + sw * .95, y0 + sh - sw * .05)
        d.rounded_rectangle(screen, sw * .07, fill=GLASS + (255,))
        d.rounded_rectangle(((x0 + sw * .38), y0 + sw * .07, (x0 + sw * .62), y0 + sw * .12), sw * .03,
                            fill=(36, 38, 44, 255))                        # the camera notch
    else:
        sw = (.62 if device == 'laptop' else .5) * w * k
        sh = sw * (.6 if device == 'laptop' else .7)
        x0, y0 = (w * k - sw) / 2, .05 * h * k
        bezel = sw * .025
        d.rounded_rectangle((x0 - bezel + 10 * k, y0 - bezel + 12 * k, x0 + sw + bezel + 10 * k,
                             y0 + sh + bezel + 12 * k), bezel * 1.5, fill=(0, 0, 0, 40))
        d.rounded_rectangle((x0 - bezel, y0 - bezel, x0 + sw + bezel, y0 + sh + bezel), bezel * 1.5,
                            fill=(36, 38, 44, 255), outline=INK, width=3 * k)
        if device == 'laptop':                                 # the keyboard deck under the screen
            d.polygon([(x0 - sw * .1, y0 + sh + bezel * 1.2), (x0 + sw * 1.1, y0 + sh + bezel * 1.2),
                       (x0 + sw * 1.16, y0 + sh + bezel * 2.6), (x0 - sw * .16, y0 + sh + bezel * 2.6)],
                      fill=(196, 200, 208, 255), outline=INK)
        screen = (x0, y0, x0 + sw, y0 + sh)
        d.rectangle(screen, fill=GLASS + (255,))
    if moment['kind'] == 'message':
        _thread(layer, screen, moment, t, accent, device)
    else:
        _screen(layer, screen, moment, t, accent, device)
    return layer.resize((w, h), Image.LANCZOS)


def _rgb(c):
    return tuple(ImageColor.getrgb(c)[:3]) if isinstance(c, str) else tuple(c[:3])


def _accent(palette):
    """A UI colour from the plan's palette that reads with white letters, else a calm blue."""
    for key in ('accent', 'accent2', 'ink'):
        c = (palette or {}).get(key)
        if c is not None and sum(c) / 3 < 170 and max(c) - min(c) > 40:
            return tuple(c)
    return (52, 110, 220)


def _bar(layer, screen, title, accent, unit, avatar=None):
    """The app bar across the screen's top with the app's name; returns its bottom."""
    x0, y0, x1, _ = screen
    d = ImageDraw.Draw(layer)
    top = y0 + unit * 2.2
    bottom = top + unit * 7
    d.rectangle((x0, y0, x1, bottom), fill=accent + (255,))
    if title:
        size = round(unit * 3.2)
        while size > unit * 1.6 and _width(title, size) > (x1 - x0) - unit * 14:
            size -= 2
        _text(layer, (x0 + unit * 3, top + (bottom - top - size * 1.15) / 2), title, size, (255, 255, 255))
    if avatar is not None:
        r = unit * 2.6
        cx, cy = x1 - unit * 4.5, (top + bottom) / 2
        lit = avatar
        if lit:
            d.ellipse((cx - r * 1.5, cy - r * 1.5, cx + r * 1.5, cy + r * 1.5), outline=(255, 214, 0, 255),
                      width=round(unit * .6))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255), outline=INK, width=round(unit * .3))
        d.ellipse((cx - r * .38, cy - r * .62, cx + r * .38, cy + r * .1), fill=accent + (255,))
        d.chord((cx - r * .7, cy + r * .05, cx + r * .7, cy + r * 1.2), 180, 360, fill=accent + (255,))
    return bottom


def _screen(layer, screen, moment, t, accent, device):
    x0, y0, x1, y1 = screen
    unit = (y1 - y0) / 78 if device == 'phone' else (y1 - y0) / 60
    d = ImageDraw.Draw(layer)
    shown = [e for e in moment['elements'] if e.get('t', 0) <= t + 1e-6]
    avatar = next((e for e in shown if e['kind'] == 'avatar'), None)
    bar = _bar(layer, screen, moment.get('app') or '', accent, unit,
               avatar=None if avatar is None else (t - avatar['t'] < LIT))
    pad = unit * 4
    col0, col1 = (x0 + pad, x1 - pad) if device == 'phone' else (x0 + (x1 - x0) * .2, x1 - (x1 - x0) * .2)
    y = bar + unit * 4
    taps = []
    lit_any = None
    for e in shown:
        lit = t - e['t'] < LIT
        kind = e['kind']
        size = round(unit * 3.0)
        if kind == 'notification':
            _banner(layer, screen, e, moment.get('app'), t, accent, unit)
            continue
        if kind == 'avatar':
            if lit:
                taps.append((x1 - unit * 4.5, bar - unit * 3.5, e['t']))
            continue
        if kind in ('row', 'legend', 'toggle', 'tab'):
            hh = unit * 8
            fill = (255, 248, 214, 255) if lit else (255, 255, 255, 255)
            d.rounded_rectangle((col0, y, col1, y + hh), unit * 1.6, fill=fill,
                                outline=(accent + (255,)) if lit else (205, 210, 218, 255),
                                width=round(unit * (.7 if lit else .3)))
            tx = col0 + unit * 3
            if kind == 'legend':
                r = unit * 2
                c = DOT.get(e.get('colour'), accent)
                d.ellipse((tx, y + hh / 2 - r, tx + 2 * r, y + hh / 2 + r), fill=c + (255,))
                tx += 2 * r + unit * 2
            label = e['label']
            while size > unit * 1.8 and _width(label, size) > col1 - tx - unit * (3 if kind == 'legend' else 9):
                size -= 2
            _text(layer, (tx, y + (hh - size * 1.15) / 2), label, size, INK)
            if kind == 'toggle':
                on = lit or t - e['t'] > 0
                sx = col1 - unit * 11
                d.rounded_rectangle((sx, y + hh * .25, sx + unit * 8, y + hh * .75), hh * .25,
                                    fill=(GREEN if on else (190, 194, 200)) + (255,))
                kx = sx + (unit * 5.6 if on else unit * 1.2)
                d.ellipse((kx, y + hh * .29, kx + hh * .42, y + hh * .71), fill=(255, 255, 255, 255))
            elif kind != 'legend':
                cx = col1 - unit * 4
                d.line([(cx - unit, y + hh * .35), (cx + unit * .4, y + hh / 2), (cx - unit, y + hh * .65)],
                       fill=(150, 156, 166, 255), width=round(unit * .6))
            if lit and kind == 'toggle':
                taps.append((col1 - unit * 6, y + hh * .7, e['t']))
            y += hh + unit * 2
        elif kind == 'button':
            hh = unit * 9
            label = e['label'] or ''
            bw = max(unit * 9, min(col1 - col0, _width(label, size) + unit * 10))
            bx = (col0 + col1 - bw) / 2
            pressed = lit and t - e['t'] < .5
            fill = tuple(max(0, c - 40) for c in accent) if pressed else accent
            if lit:
                d.rounded_rectangle((bx - unit * 1.2, y - unit * 1.2, bx + bw + unit * 1.2, y + hh + unit * 1.2),
                                    hh / 2 + unit, outline=(255, 214, 0, 255), width=round(unit * .8))
            d.rounded_rectangle((bx, y, bx + bw, y + hh), hh / 2, fill=fill + (255,))
            label_size = size if label != '+' else round(unit * 6)
            _text(layer, (bx + (bw - _width(label, label_size)) / 2, y + (hh - label_size * 1.15) / 2), label,
                  label_size, (255, 255, 255))
            if lit:
                taps.append((bx + bw - unit * 1.5, y + hh * .75, e['t']))
            y += hh + unit * 3
        elif kind == 'input':
            label = e['label'] or ''
            if label:
                _text(layer, (col0, y), label, round(unit * 2.4), (110, 116, 126))
                y += unit * 3.4
            hh = unit * 8.5
            d.rounded_rectangle((col0, y, col1, y + hh), unit * 1.2, fill=(255, 255, 255, 255),
                                outline=(accent + (255,)) if lit else (170, 176, 186, 255),
                                width=round(unit * (.7 if lit else .4)))
            value = e.get('value') or ''
            secret = not value and re.match(r'pass|pin', label, re.I)
            typed = 1. if not lit else min(1., (t - e['t']) / .9)
            if value:
                part = value[:max(0, round(len(value) * typed))]
                _text(layer, (col0 + unit * 2.5, y + (hh - size * 1.3) / 2), part, round(size * 1.1), INK, code=True)
            elif secret:
                for i in range(round(8 * typed)):
                    cx = col0 + unit * (3.5 + i * 3)
                    d.ellipse((cx - unit, y + hh / 2 - unit, cx + unit, y + hh / 2 + unit), fill=INK + (255,))
            y += hh + unit * 3
        elif kind == 'code':
            value = e['label']
            if value:
                big = round(unit * 7.5)
                while big > unit * 3 and _width(value, big, code=True) > col1 - col0 - unit * 4:
                    big -= 2
                cw = _width(value, big, code=True)
                hh = big * 1.6
                d.rounded_rectangle(((col0 + col1 - cw) / 2 - unit * 3, y, (col0 + col1 + cw) / 2 + unit * 3, y + hh),
                                    unit * 1.6, fill=(240, 244, 255, 255),
                                    outline=(accent + (255,)) if lit else (205, 210, 218, 255),
                                    width=round(unit * (.8 if lit else .3)))
                _text(layer, ((col0 + col1 - cw) / 2, y + (hh - big * 1.25) / 2), value, big, accent, code=True)
                y += hh + unit * 3
            else:
                n = e.get('digits') or 6
                bw = min(unit * 7, (col1 - col0) / (n + 1))
                gx = (col0 + col1 - n * bw - (n - 1) * unit) / 2
                for i in range(n):
                    bx = gx + i * (bw + unit)
                    d.rounded_rectangle((bx, y, bx + bw, y + bw * 1.25), unit, fill=(255, 255, 255, 255),
                                        outline=(accent + (255,)) if lit else (170, 176, 186, 255),
                                        width=round(unit * .5))
                y += bw * 1.25 + unit * 3
        elif kind == 'qr':
            side = min(col1 - col0, (y1 - y) * .8, unit * 34)
            qx = (col0 + col1 - side) / 2
            _qr(d, qx, y, side, unit)
            if lit or True:                                   # the scanning line sweeps the square
                phase = ((t - e['t']) % 1.6) / 1.6
                ly = y + side * phase
                d.line((qx - unit * 2, ly, qx + side + unit * 2, ly), fill=(230, 40, 40, 230), width=round(unit * .8))
            y += side + unit * 3
        elif kind == 'check':
            r = unit * 5.5
            grow = min(1., (t - e['t']) / .35)
            cx, cy = (col0 + col1) / 2, y + r
            rr = r * grow
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=GREEN + (255,))
            if grow >= 1:
                d.line([(cx - r * .45, cy), (cx - r * .1, cy + r * .38), (cx + r * .5, cy - r * .35)],
                       fill=(255, 255, 255, 255), width=round(unit * 1.2), joint='curve')
            y += 2 * r + unit * 3
        lit_any = lit_any or lit
    for x, y_, at in taps[-1:]:
        _pointer(layer, x, y_, t - at, unit, device)


def _qr(d, x, y, side, unit):
    """A square code: three finder squares and a fixed scatter of modules (no real data)."""
    n = 21
    m = side / n
    d.rectangle((x - unit, y - unit, x + side + unit, y + side + unit), fill=(255, 255, 255, 255))
    for i in range(n):
        for j in range(n):
            if (i < 8 and j < 8) or (i < 8 and j > n - 9) or (i > n - 9 and j < 8):
                continue
            if (i * 7 + j * 13 + i * j) % 5 < 2:
                d.rectangle((x + j * m, y + i * m, x + (j + 1) * m, y + (i + 1) * m), fill=INK + (255,))
    for fx, fy in ((0, 0), (n - 7, 0), (0, n - 7)):
        d.rectangle((x + fx * m, y + fy * m, x + (fx + 7) * m, y + (fy + 7) * m), fill=INK + (255,))
        d.rectangle((x + (fx + 1) * m, y + (fy + 1) * m, x + (fx + 6) * m, y + (fy + 6) * m), fill=(255, 255, 255, 255))
        d.rectangle((x + (fx + 2) * m, y + (fy + 2) * m, x + (fx + 5) * m, y + (fy + 5) * m), fill=INK + (255,))


def _pointer(layer, x, y, since, unit, device):
    """A fingertip pressing (phone, tablet) or a cursor clicking (laptop) at (x, y); a ring spreads on the press."""
    d = ImageDraw.Draw(layer)
    ring = min(1., max(0., since) / .5)
    if ring < 1:
        r = unit * (2 + 5 * ring)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 214, 0, round(255 * (1 - ring))), width=round(unit * .8))
    if device == 'laptop':
        s = unit * 1.1
        pts = [(0, 0), (0, 14), (3.5, 10.5), (6, 16), (8, 15), (5.6, 9.6), (10, 9.6)]
        d.polygon([(x + px * s, y + py * s) for px, py in pts], fill=(255, 255, 255, 255), outline=INK + (255,))
        return
    s = unit * 1.6
    d.rounded_rectangle((x - 2.2 * s, y - .6 * s, x + 2.2 * s, y + 9 * s), 2.2 * s, fill=(236, 190, 150, 255),
                        outline=INK + (255,), width=round(unit * .4))
    d.rounded_rectangle((x - 1.4 * s, y - .2 * s, x + 1.4 * s, y + 2 * s), s, fill=(250, 226, 210, 255))


def _banner(layer, screen, e, app, t, accent, unit):
    """A notification sliding down from the top of the screen: the app's icon and name, then its words."""
    x0, y0, x1, y1 = screen
    d = ImageDraw.Draw(layer)
    slide = min(1., max(0., t - e['t']) / .35)
    pad = unit * 3
    text = e['label'] or ''
    size = round(unit * 3.0)
    rows = _wrap(text, size, x1 - x0 - pad * 4) if text else []
    hh = unit * 7 + len(rows) * size * 1.3 + unit * 2
    top = y0 + unit * 12 - (1 - slide) * (hh + unit * 12)
    d.rounded_rectangle((x0 + pad + unit * .6, top + unit, x1 - pad + unit * .6, top + hh + unit), unit * 2.4,
                        fill=(0, 0, 0, 50))
    d.rounded_rectangle((x0 + pad, top, x1 - pad, top + hh), unit * 2.4, fill=(255, 255, 255, 255),
                        outline=(255, 214, 0, 255) if t - e['t'] < LIT else (205, 210, 218, 255),
                        width=round(unit * .6))
    ix = x0 + pad * 2
    d.rounded_rectangle((ix, top + unit * 2, ix + unit * 4.4, top + unit * 6.4), unit, fill=accent + (255,))
    if app:
        _text(layer, (ix + unit * 6, top + unit * 2.4), app, round(unit * 2.6), (90, 96, 106))
    y = top + unit * 8
    for r in rows:
        _text(layer, (x0 + pad * 2, y), r, size, INK)
        y += size * 1.3


def _thread(layer, screen, moment, t, accent, device):
    """A messages screen: the thread's name, its bubbles (others left, the owner right), timestamps, emoji."""
    x0, y0, x1, y1 = screen
    unit = (y1 - y0) / 80
    d = ImageDraw.Draw(layer)
    top = y0 + unit * 2.2
    bottom = top + unit * 9
    d.rectangle((x0, y0, x1, bottom), fill=(244, 245, 248, 255))
    d.line((x0, bottom, x1, bottom), fill=(214, 218, 224, 255), width=round(unit * .3))
    name = moment.get('thread') or ''
    r = unit * 3
    cx = (x0 + x1) / 2
    d.ellipse((cx - r, top + unit * .2, cx + r, top + unit * .2 + 2 * r), fill=(170, 176, 190, 255))
    if name:
        initial = name[0].upper()
        f = round(unit * 3.2)
        _text(layer, (cx - _font(f).getlength(initial) / 2, top + unit * .2 + r - f * .62), initial, f,
              (255, 255, 255))
        size = round(unit * 2.4)
        _text(layer, (cx - _width(name, size) / 2, top + unit * 6.4), name, size, INK)
    # The compose bar at the bottom.
    cb = y1 - unit * 8
    d.rounded_rectangle((x0 + unit * 3, cb, x1 - unit * 11, y1 - unit * 2.5), unit * 2.6, fill=(255, 255, 255, 255),
                        outline=(200, 204, 212, 255), width=round(unit * .3))
    d.ellipse((x1 - unit * 9, cb, x1 - unit * 3.5, cb + unit * 5.5), fill=accent + (255,))
    messages = list(moment.get('history') or ())[-6:]
    current = {k: moment.get(k) for k in ('sender', 'outgoing', 'time', 'text', 'system', 'voice')}
    if moment.get('header_only'):
        current = None
    typing = current is not None and current['outgoing'] and not moment.get('replay') and not current.get('voice') \
        and current['text']
    since = t - moment['start']
    size = round(unit * 3.5)                                  # bubbles read at a glance, emoji with them
    maxw = (x1 - x0) * .78
    if typing and since < 1.2:                                # typed into the compose box first, then sent
        part = current['text'][:max(0, round(len(current['text']) * min(1., since / 1.0)))]
        room = (x1 - unit * 12) - (x0 + unit * 5)
        while part and _width(part, round(size * .9)) > room:
            part = part[1:]                                   # the box scrolls: its newest letters show
        _text(layer, (x0 + unit * 5, cb + unit * 1.3), part, round(size * .9), INK)
    elif current is not None:
        messages.append(current)
    # Lay out bottom-up from the compose bar; older bubbles that don't fit scroll off the top.
    blocks = []
    small = round(unit * 2.0)
    for m in messages:
        if m.get('system'):                                   # the app's notice: centred grey words, no bubble
            rows = _wrap(m['text'] or '', small, maxw)
            bw = max(_width(r, small) for r in rows) + unit * 4
            blocks.append((m, rows, bw, len(rows) * small * 1.3 + unit * 1.6, 0))
            continue
        if m.get('voice') is not None:                        # a voice note: play button, waveform, its length
            rows, bw, bh = [], maxw * .8, unit * 8.5
        else:
            rows = _wrap(m['text'] or '', size, maxw - unit * 5)
            bw = max(_width(r, size) for r in rows) + unit * 5
            bh = len(rows) * size * 1.32 + unit * 3.2
        label = (not m['outgoing'] and moment.get('group') and m.get('sender')) or m.get('time')
        extra = unit * 2.8 if label else 0
        blocks.append((m, rows, bw, bh, extra))
    status = moment.get('status') if moment.get('status_t') is not None and t >= moment['status_t'] else None
    y = cb - unit * 2.5 - (unit * 3.4 if status else 0)
    placed = []
    for m, rows, bw, bh, extra in reversed(blocks):
        if y - bh - extra < bottom + unit * 1.5:
            break
        placed.append((m, rows, bw, bh, extra, y - bh))
        y -= bh + extra + unit * 2
    for i, (m, rows, bw, bh, extra, by) in enumerate(placed):
        newest = i == 0 and m is current
        pop = min(1., (t - moment['start']) / .25) if newest else 1.
        if pop < 1:
            by += (1 - pop) * unit * 4
        if m.get('system'):
            d.rounded_rectangle(((x0 + x1 - bw) / 2, by, (x0 + x1 + bw) / 2, by + bh), unit * 1.6,
                                fill=(238, 239, 243, 255))
            ty = by + unit * .8
            for r in rows:
                _text(layer, ((x0 + x1) / 2 - _width(r, small) / 2, ty), r, small, (128, 133, 143))
                ty += small * 1.3
            continue
        right = m['outgoing']
        bx = x1 - unit * 3 - bw if right else x0 + unit * 3
        fill = accent if right else (229, 231, 236)
        ink_c = (255, 255, 255) if right else INK
        d.rounded_rectangle((bx, by, bx + bw, by + bh), unit * 2.6, fill=fill + (255,))
        if m.get('voice') is not None:
            _voice_note(d, layer, (bx, by, bx + bw, by + bh), m.get('voice') or '', ink_c, accent if not right
                        else (255, 255, 255), unit, t - moment['start'] if newest else 99.)
        ty = by + unit * 1.5
        for r in rows:
            _text(layer, (bx + unit * 2.5, ty), r, size, ink_c)
            ty += size * 1.32
        name = m.get('sender') if not right and moment.get('group') else None
        label = '  '.join(s for s in (name, m.get('time')) if s)
        if label:                                             # the sender's name and the small time above it
            if right:
                _text(layer, (bx + bw - unit, by - unit * 2.8), label, small, (140, 146, 156), anchor_right=True)
            else:
                _text(layer, (bx + unit * 1.5, by - unit * 2.8), name or '', small, (110, 116, 126))
                if m.get('time'):
                    _text(layer, (bx + unit * 1.5 + (_width(name + '  ', small) if name else 0), by - unit * 2.8),
                          m['time'], small, (150, 156, 166))
    if status and placed:
        ss = round(unit * 2.1)
        _text(layer, (x1 - unit * 3, cb - unit * 2.5 - unit * 2.9), status, ss, (120, 126, 136), anchor_right=True)


def _voice_note(d, layer, box, length, ink, button, unit, since):
    """A voice message bubble: a round play button, a waveform that fills as it plays, its length."""
    x0, y0, x1, y1 = box
    cy = (y0 + y1) / 2
    r = (y1 - y0) * .3
    cx = x0 + unit * 2 + r
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(button) + (255,))
    tri = (255, 255, 255) if tuple(button) != (255, 255, 255) else INK
    d.polygon([(cx - r * .3, cy - r * .5), (cx - r * .3, cy + r * .5), (cx + r * .55, cy)], fill=tuple(tri) + (255,))
    wx0, wx1 = cx + r + unit * 1.5, x1 - unit * (9 if length else 3)
    n = max(8, int((wx1 - wx0) / (unit * 1.1)))
    played = min(1., max(0., since) / 3.)
    for i in range(n):
        h = (y1 - y0) * (.12 + .3 * abs(math.sin(i * 1.7) * math.cos(i * .45)))
        x = wx0 + i * (wx1 - wx0) / n
        c = ink if i / n <= played else (160, 166, 176)
        d.line((x, cy - h, x, cy + h), fill=tuple(c) + (255,), width=max(1, round(unit * .5)))
    if length:
        _text(layer, (x1 - unit * 8, cy - unit * 1.2), length, round(unit * 2.0), ink)

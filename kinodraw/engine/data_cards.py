"""Data cards: the figures a script states (kinodraw/figures.py), drawn over the picture while they are said.

A card shows the script's own text ("$4.2M", "2,300 cars", "7 a.m."): a big number (always the stated value, never a
count-up through numbers nobody says), a price tag, an A->B change as two bars with the stated change and the text's
own periods, a bar comparison, a short stat list, or a when/where card. Growth gets "+" and an up arrow; an overrun, a
loss or a delay gets an amber warning sign. On a whiteboard or storybook page it is hand-lettered on paper; on a motion
page it is a clean card. Either fades in whole, inside the safe margins, and leaves with its sentence. It goes where the
picture has the least ink while it is up, with air around it (never against a picture it is not about, never over the
caption band below CAPTION_TOP or the title strip above TOP), measured once per card on the frames the viewer sees.
"""
from __future__ import annotations

import bisect
import copy
import math
import re
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .. import figures
from . import ink

TOP = .09                 # cards stay below this share of the frame height (the chapter tag)
CAPTION_TOP = .76         # ... and above this one (the caption band)
SIDE = .05                # side margin
LEFT_RAIL = .075          # the left side starts after the step indicator
MAX_W = .36               # a card is at most this share of the frame width
SHRINK = (.72, .56)       # ... and shrinks to these where every spot has a picture or words
GROW = 4                  # measured ink grows by this many quarter-resolution pixels (16 px at 1080p)
MIN_HOLD, MAX_HOLD, TAIL = 2.6, 7., .9   # seconds a card stays: at least, at most, after its sentence ends
INK = 48
CLEAN = {'card': (252, 252, 250), 'ink': (26, 30, 38), 'soft': (96, 104, 116), 'accent': (52, 110, 200),
         'shadow': (0, 0, 0)}
WARN = (214, 134, 18)     # amber: an overrun, a loss or a delay (figures.Card.tone 'warn'), never the growth colour
CLEAR = 12                # cards keep this many more quarter-resolution cells (48 px at 1080p) of air around them ...
CLEAR_WEIGHT = .35        # ... weighed at this share of covered ink: a card never hugs a picture it is not about
ENTER = .35               # seconds a card takes to fade in whole (never wiped in through its own edge)
BOLD = ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf'


@lru_cache(maxsize=64)
def _clean_font(size):
    return ImageFont.truetype(str(BOLD), max(8, int(size)), layout_engine=ImageFont.Layout.BASIC)


class _Look:
    """Fonts and colours of one look: 'board' (hand-lettered on the skin's paper) or 'clean'."""

    def __init__(self, look, skin, lang, unit):
        self.board = look == 'board'
        self.lang, self.unit = lang, unit
        self.fonts = skin.fonts
        if self.board:
            self.fill = tuple(skin.base[:3]) + (255,)
            self.ink = tuple(skin.ink[:3]) + (255,)
            self.soft = tuple(round(c * .6 + b * .4) for c, b in zip(skin.ink[:3], skin.base[:3])) + (255,)
            self.accent = tuple(skin.caption_accent[:3]) + (255,)
        else:
            self.fill = CLEAN['card'] + (246,)
            self.ink = CLEAN['ink'] + (255,)
            self.soft = CLEAN['soft'] + (255,)
            self.accent = CLEAN['accent'] + (255,)

    def font(self, size):
        size = max(10, round(size * self.unit))
        return ink.hand_font(self.lang, size, self.fonts) if self.board else _clean_font(size)

    def fit(self, text, size, width, min_size=24):
        """The largest font (up to ``size``) at which ``text`` fits ``width`` on one line."""
        f = self.font(size)
        while f.getlength(text) > width and size > min_size:
            size *= .92
            f = self.font(size)
        return f

    def wrap(self, text, size, width, lines=2):
        f = self.font(size)
        words, rows = text.split(), []
        for w in words:
            if rows and f.getlength(rows[-1] + ' ' + w) <= width:
                rows[-1] += ' ' + w
            else:
                rows.append(w)
        if len(rows) > lines:
            return self.wrap(text, size * .88, width, lines) if size > 22 else (rows[:lines], f)
        return rows, f


def _text(d, xy, text, f, fill, anchor='la'):
    d.text(xy, text, font=f, fill=fill, anchor=anchor)


def _frame_box(d, box, look, unit):
    x0, y0, x1, y1 = box
    r = 22 * unit
    if look.board:
        d.rounded_rectangle(box, r, fill=look.fill)
        w = max(3, round(4 * unit))
        d.rounded_rectangle(box, r, outline=look.ink, width=w)
        # a second, slightly offset stroke: drawn with a marker, not a ruler
        d.rounded_rectangle((x0 + 3 * unit, y0 - 2 * unit, x1 - 2 * unit, y1 + 3 * unit), r, outline=look.ink[:3] + (90,),
                            width=max(2, round(2 * unit)))
    else:
        d.rounded_rectangle((x0 + 6 * unit, y0 + 9 * unit, x1 + 6 * unit, y1 + 9 * unit), r, fill=(0, 0, 0, 46))
        d.rounded_rectangle(box, r, fill=look.fill)
        d.rounded_rectangle((x0, y0, x0 + 12 * unit, y1), r, fill=look.accent)
        d.rectangle((x0 + 6 * unit, y0, x0 + 12 * unit, y1), fill=look.fill)


def _arrow(d, cx, cy, size, direction, fill, tone=''):
    if tone == 'warn':
        # a warning sign, never the growth arrow: a triangle with an exclamation mark
        pts = [(cx - size * .55, cy + size * .45), (cx + size * .55, cy + size * .45), (cx, cy - size * .55)]
        d.polygon(pts, fill=fill)
        d.rounded_rectangle((cx - size * .06, cy - size * .25, cx + size * .06, cy + size * .12), size * .05,
                            fill=(255, 255, 255, 255))
        d.ellipse((cx - size * .07, cy + size * .2, cx + size * .07, cy + size * .34), fill=(255, 255, 255, 255))
        return
    if direction == 'down':
        pts = [(cx - size * .5, cy - size * .35), (cx + size * .5, cy - size * .35), (cx, cy + size * .45)]
    else:
        pts = [(cx - size * .5, cy + size * .35), (cx + size * .5, cy + size * .35), (cx, cy - size * .45)]
    d.polygon(pts, fill=fill)


def _counted(text, progress):
    """The text a counter shows at ``progress``: always the stated value, exactly as written. A count-up would show
    numbers the narration never says while it says the real one, so the counter only pops in (its card fades in)."""
    return text



# ------------------------------------------------------------------ one card as an image
def card_image(card, look, W, H, progress=1., fit=None):
    """The card drawn at ``progress`` (0..1: a counter's count, the bars' growth); RGBA, sized to its content and
    at most MAX_W of the frame wide (``fit``: the box width of the finished card, kept while a counter counts)."""
    u = look.unit
    if card.tone == 'warn':
        look = copy.copy(look)
        look.accent = WARN + (255,)
    pad = 30 * u
    width = round(min(MAX_W * W, 640 * u))
    if card.kind in ('change', 'bars'):
        width = round(min(width, (len(card.items) * 210 + 100) * u))        # two bars need no more room
    inner = width - 2 * pad - (0 if look.board else 12 * u)
    left = pad + (0 if look.board else 12 * u)
    kind = card.kind
    ops = []                      # (callable(d, y0)) drawn after the box size is known
    y = pad

    def line(text, size, fill, min_size=24, centre=False):
        nonlocal y
        f = look.fit(text, size, inner, min_size)
        top = y
        ops.append(lambda d, f=f, top=top: _text(d, (left + inner / 2 if centre else left, top), text, f, fill,
                                                  'ma' if centre else 'la'))
        y += f.size * 1.18
        return f

    if kind in ('number', 'counter', 'price'):
        if card.qualifier:
            line(card.qualifier, 40, look.soft)
            y += 8 * u
        shown = figures.signed(card.value, card.direction, card.tone)      # growth: "+18%"
        value = _counted(shown, progress) if kind == 'counter' else shown
        mark = card.direction or card.tone
        f = look.fit(shown, 120, inner - (70 * u if mark else 0), 40)
        top = y
        if mark:
            ops.append(lambda d, top=top, f=f: _arrow(d, left + 26 * u, top + f.size * .55, 52 * u, card.direction,
                                                      look.accent, card.tone))
        x = left + (70 * u if mark else 0)
        if kind == 'price':
            # a price tag: a pointed end and a hole, the price inside
            tag_w, tag_h = min(inner, f.getlength(card.value) + 120 * u), f.size * 1.5
            def tag(d, top=top, tag_w=tag_w, tag_h=tag_h, f=f):
                x0, x1, y0, y1 = left, left + tag_w, top, top + tag_h
                pts = [(x0 + tag_h * .42, y0), (x1, y0), (x1, y1), (x0 + tag_h * .42, y1), (x0, (y0 + y1) / 2)]
                d.polygon(pts, fill=look.accent[:3] + (40,), outline=look.ink)
                d.line(pts + [pts[0]], fill=look.ink, width=max(3, round(4 * u)))
                r = 9 * u
                hx, hy = x0 + tag_h * .36, (y0 + y1) / 2
                d.ellipse((hx - r, hy - r, hx + r, hy + r), outline=look.ink, width=max(2, round(3 * u)))
                _text(d, (x0 + tag_h * .55 + (tag_w - tag_h * .55) / 2, (y0 + y1) / 2), card.value, f, look.ink, 'mm')
            ops.append(tag)
            y += tag_h + 14 * u
        else:
            ops.append(lambda d, top=top, f=f, x=x, value=value: _text(d, (x, top), value, f, look.ink))
            y += f.size * (1.24 if look.board else 1.12)
        if card.label:
            rows, lf = look.wrap(card.label, 46, inner)
            for r in rows:
                top = y
                ops.append(lambda d, top=top, r=r, lf=lf: _text(d, (left, top), r, lf, look.soft))
                y += lf.size * 1.2
    elif kind in ('change', 'bars'):
        if card.label and kind == 'change':
            line(card.label, 44, look.soft)
        n = len(card.items)
        chart_h = 210 * u
        if kind == 'change' and card.delta:
            df = look.font(46)
            label, badge_top = figures.signed(card.delta, card.direction, card.tone), y
            def delta(d, label=label, df=df, badge_top=badge_top):
                w = df.getlength(label) + 70 * u
                x1 = left + inner
                d.rounded_rectangle((x1 - w, badge_top, x1, badge_top + df.size * 1.35), 14 * u, outline=look.ink,
                                    width=max(2, round(3 * u)), fill=look.fill)
                _arrow(d, x1 - w + 28 * u, badge_top + df.size * .68, 30 * u, card.direction, look.accent, card.tone)
                _text(d, (x1 - 14 * u, badge_top + df.size * .68), label, df, look.ink, 'rm')
            ops.append(delta)
            y += df.size * 1.35 + 6 * u
        top = y + 66 * u
        values = [v for _, _, v in card.items if v is not None]
        biggest = max(values) if values else 1
        gap = inner / n
        bar_w = min(120 * u, gap * .62)
        vf = look.fit(max((t for t, _, _ in card.items), key=len), 48, gap * .98, 22)
        lf = look.font(30)
        grow = 1 - (1 - min(1., max(0., progress))) ** 2
        tops = []
        for k, (text, label, v) in enumerate(card.items):
            share = .3 + .7 * (v / biggest if biggest else 1) if v is not None else .6
            hgt = chart_h * share * grow
            cx = left + gap * (k + .5)
            colour = look.accent if k == n - 1 else look.soft
            tops.append((cx, top + chart_h - hgt))
            def bar(d, cx=cx, hgt=hgt, colour=colour, text=text, label=label):
                base = top + chart_h
                if hgt > 1:
                    d.rectangle((cx - bar_w / 2, base - hgt, cx + bar_w / 2, base),
                                fill=colour[:3] + (200 if look.board else 255,), outline=look.ink if look.board else None,
                                width=max(2, round(3 * u)))
                _text(d, (cx, base - hgt - 8 * u), text, vf, look.ink, 'md')
                if label:
                    _text(d, (cx, base + 10 * u), label, look.fit(label, 30, gap * .96, 14), look.soft, 'ma')
            ops.append(bar)
        ops.append(lambda d: d.line((left, top + chart_h, left + inner, top + chart_h), fill=look.ink,
                                    width=max(2, round(3 * u))))
        y = top + chart_h + 50 * u
    elif kind == 'stat':
        for r in card.rows:
            rows, f = look.wrap(r, 56, inner - 34 * u)
            for k, piece in enumerate(rows):
                top = y
                if k == 0:
                    ops.append(lambda d, top=top, f=f: d.ellipse((left, top + f.size * .38, left + 16 * u,
                                                                  top + f.size * .38 + 16 * u), fill=look.accent))
                ops.append(lambda d, top=top, f=f, piece=piece: _text(d, (left + 34 * u, top), piece, f, look.ink))
                y += f.size * 1.2
            y += 10 * u
    elif kind == 'event':
        icon = 92 * u
        text_x = left + icon + 28 * u
        avail = inner - icon - 28 * u
        top0 = y
        def calendar(d, top0=top0):
            x0, y0 = left, top0 + 4 * u
            d.rounded_rectangle((x0, y0, x0 + icon, y0 + icon), 12 * u, fill=(255, 255, 255, 255) if not look.board
                                else look.fill, outline=look.ink, width=max(3, round(4 * u)))
            d.rectangle((x0 + 2 * u, y0 + 2 * u, x0 + icon - 2 * u, y0 + icon * .3), fill=look.accent)
            for k in (.3, .7):
                d.line((x0 + icon * k, y0 - 10 * u, x0 + icon * k, y0 + 12 * u), fill=look.ink, width=max(3, round(5 * u)))
            for gx in range(3):
                for gy in range(2):
                    cx, cy = x0 + icon * (.25 + gx * .25), y0 + icon * (.52 + gy * .24)
                    d.ellipse((cx - 5 * u, cy - 5 * u, cx + 5 * u, cy + 5 * u), fill=look.soft)
        ops.append(calendar)
        for k, r in enumerate(card.rows):
            f = look.fit(r, 64 if k == 0 else 56, avail, 26)
            top = y
            ops.append(lambda d, top=top, f=f, r=r: _text(d, (text_x, top), r, f, look.ink))
            y += f.size * 1.25
        y = max(y, top0 + icon + 16 * u)
        if card.where:
            f = look.fit(card.where, 44, inner - 44 * u, 22)
            top = y + 6 * u
            def pin(d, top=top, f=f):
                cx, cy, r = left + 14 * u, top + f.size * .42, 13 * u
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=look.accent)
                d.polygon([(cx - r * .8, cy + r * .5), (cx + r * .8, cy + r * .5), (cx, cy + r * 2.3)], fill=look.accent)
                d.ellipse((cx - r * .4, cy - r * .4, cx + r * .4, cy + r * .4), fill=look.fill)
                _text(d, (left + 44 * u, top), card.where, f, look.ink)
            ops.append(pin)
            y = top + f.size * 1.3
    height = round(y + pad - 6 * u)
    layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    for op in ops:
        op(ImageDraw.Draw(layer))
    if fit is not None:
        width = fit
    elif kind not in ('change', 'bars'):               # left-aligned content: the card is only as wide as it
        box = layer.getbbox()
        width = min(width, max(round(.16 * W), (box[2] if box else width) + round(pad)))
    img = Image.new('RGBA', (width + round(10 * u), height + round(12 * u)), (0, 0, 0, 0))
    _frame_box(ImageDraw.Draw(img), (2, 2, width, height), look, u)
    img.alpha_composite(layer.crop((0, 0, width, height)), (0, 0))
    if img.height > (CAPTION_TOP - TOP) * H:
        scale = (CAPTION_TOP - TOP) * H / img.height
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    return img


def _dilate(mask, steps):
    """``mask`` grown by ``steps`` cells each way: thin letter strokes become the solid block a line of words reads
    as, so a card never sits over writing because its strokes are thin."""
    out = mask.copy()
    for _ in range(steps):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


# ------------------------------------------------------------------ the cards of a video, on the clock
class DataCards:
    """Every data card of an episode with its time window; ``paint`` draws the live one over a finished frame."""

    def __init__(self, entries, skin, lang, frame_size, written=(), cuts=()):
        self.entries = entries                 # [(start, end, card, beat id)], sorted, never overlapping
        # cards whose figures the board page on screen already writes: not repeated over that page
        self.on_board = {k for k, e in enumerate(entries) if _written(e, written, cuts)}
        self.skin, self.lang = skin, lang
        self.W, self.H = frame_size
        self.unit = min(self.W, self.H) / 1080
        self._places = {}
        self._images = {}
        self._measuring = False

    def at(self, t):
        for k, (start, end, card, _) in enumerate(self.entries):
            if start <= t < end:
                return k
        return None

    def image(self, k, look, progress=1.):
        card = self.entries[k][2]
        animated = progress < 1 and card.kind in ('counter', 'change', 'bars')
        key = (k, look, round(progress, 3) if animated else 1.)
        if key not in self._images:
            if len(self._images) > 64:
                self._images.clear()
            fit = self.image(k, look).width - round(10 * self.unit) if animated else None
            self._images[key] = card_image(card, _Look(look, self.skin, self.lang, self.unit), self.W, self.H,
                                           progress if animated else 1., fit)
        return self._images[key]

    def _candidates(self, w, h):
        W, H = self.W, self.H
        top, bottom = TOP * H, CAPTION_TOP * H
        mid = min(max(top, (top + bottom) / 2 - h / 2), bottom - h)
        spots = [(W * (1 - SIDE) - w, mid), (W * LEFT_RAIL, mid), ((W - w) / 2, top), ((W - w) / 2, bottom - h)]
        # then every spot of a grid over the safe area, so a card finds the gap beside any picture
        x0, x1, y1 = W * LEFT_RAIL, W * (1 - SIDE) - w, max(top, bottom - h)
        spots += [(x0 + (x1 - x0) * i / 6, top + (y1 - top) * j / 4) for j in range(5) for i in range(6, -1, -1)]
        return spots

    def place(self, k, size, measures=()):
        """(top-left, scale) of card ``k``: the candidate spot with the least ink on ``measures`` (the frames the
        viewer sees while the card is up, without cards), right side first on a tie; where every spot is inked the
        card shrinks (to SHRINK) before it covers more."""
        if k not in self._places:
            w, h = size
            best = (self._candidates(w, h)[0], 1.)
            if measures:
                inked = None
                for frame in measures:
                    a = np.asarray(frame.convert('RGB').resize((self.W // 4, self.H // 4)), dtype=np.int16)
                    paper = np.median(a.reshape(-1, 3), axis=0)
                    mask = np.abs(a - paper).max(axis=2) > INK
                    inked = mask if inked is None else inked | mask
                near = _dilate(inked, GROW + CLEAR)
                inked = _dilate(inked, GROW)
                total = np.pad(inked.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
                ring = np.pad(near.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
                scores = []
                for scale in (1.,) + SHRINK:
                    sw, sh = w * scale, h * scale
                    for i, (x, y) in enumerate(self._candidates(sw, sh)):
                        x0, y0 = max(0, int(x / 4)), max(0, int(y / 4))
                        x1, y1 = min(inked.shape[1], x0 + int(sw / 4) + 1), min(inked.shape[0], y0 + int(sh / 4) + 1)
                        count = total[y1, x1] - total[y0, x1] - total[y1, x0] + total[y0, x0]
                        close = ring[y1, x1] - ring[y0, x1] - ring[y1, x0] + ring[y0, x0] - count
                        # inked share of the full-size card, plus the pictures it would sit right against
                        covered = float(count + CLEAR_WEIGHT * close) / max(1., w * h / 16)
                        scores.append((round(covered + .12 * (1 - scale), 2), -scale, i, (x, y), scale))
                _, _, _, spot, scale = min(scores)
                best = (spot, scale)
            self._places[k] = best
        return self._places[k]

    def _on_device(self, k, t, host) -> bool:
        """A device screen (engine/ui_screens) takes the page: no card while one is live, and none at all for a card
        whose figures a screen during its window draws (the phone's code box already shows "482 913"). The host's
        ``ui_moments`` are the ones it draws (a hybrid takes them over from its whiteboard); a portrait frame draws
        no device, so its cards stay."""
        moments = getattr(host, 'ui_moments', None)
        if not moments or getattr(host, 'vertical', False):
            return False
        from .ui_screens import live
        if live(moments, t) is not None:
            return True
        from ..ui_screens import drawn_strings
        start, end, card, _ = self.entries[k]
        keys = [_squash(key) for key in _keys(card)]
        return any(m['start'] < end and start < m['end'] and
                   all(key in _squash(' '.join(drawn_strings(m))) for key in keys) for m in moments)

    def paint(self, frame, t, clean=False, host=None):
        """Draw the card live at ``t`` over ``frame`` (RGBA, modified in place). ``host`` renders the frame the viewer
        sees (its ``frame(t)``), measured once per card to place it."""
        if self._measuring:
            return
        k = self.at(t)
        if k is None or (k in self.on_board and _board_on_screen(self, host, t)):
            return                          # the whiteboard page on screen already writes these figures
        if self._on_device(k, t, host):
            return
        start, end, card, _ = self.entries[k]
        look = 'clean' if clean else 'board'
        final = self.image(k, look)
        if k not in self._places:
            measures = []
            if host is not None:
                self._measuring = True
                try:
                    # every picture the card is up over, from its first frame to its last
                    measures = [host.frame(start + (end - start) * f) for f in (.05, .3, .55, .8, .97)]
                finally:
                    self._measuring = False
            self.place(k, final.size, measures)
        (x, y), scale = self._places[k]
        local = t - start
        img = self.image(k, look, min(1., local / 1.1))
        if scale < 1:
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        # whole from its first frame (a fade, never wiped in through its own edge), inside the safe margins
        fade = min(1., (end - t) / .25, local / ENTER)
        if clean:
            y -= (1 - min(1., local / ENTER)) * 18 * self.unit
        x, y = self.inside(x, y, img.width, img.height)
        if fade < 1:
            img = img.copy()
            img.putalpha(img.getchannel('A').point(lambda v: int(v * max(0., fade))))
        ink.paste(frame, img, x, y)

    def inside(self, x, y, w, h):
        """(x, y) moved so a ``w`` x ``h`` card sits wholly inside the safe area (SIDE margins, TOP, CAPTION_TOP)."""
        W, H = self.W, self.H
        x = min(max(x, W * SIDE), W * (1 - SIDE) - w)
        y = min(max(y, H * TOP), H * CAPTION_TOP - h)
        return round(x), round(y)


def _board_on_screen(cards, host, t) -> bool:
    """The whiteboard page is the picture at ``t``: the host is the whiteboard that owns these cards, or a host (a
    hybrid) whose ``board_on_screen(t)`` says its scene shows that page."""
    if getattr(host, 'data_cards', None) is cards:
        return True
    check = getattr(host, 'board_on_screen', None)
    return bool(check and check(t))


def _keys(card) -> list[str]:
    """The figures a card shows, as written."""
    if card.kind in ('change', 'bars'):
        texts = [t for t, _, _ in card.items]
    elif card.kind in ('stat', 'event'):
        texts = card.rows
    else:
        texts = [card.value]
    return [m.group() for t in texts for m in re.finditer(r'[$€£¥₹]?\d[\d,.:]*\s?%?', t)] or texts


def _squash(text):
    return re.sub(r'\s+', '', text).lower()


def _written(entry, written, cuts=()) -> bool:
    """The board page on screen while the card is up writes every figure of the card (``written``: (time, camera
    stop, text) of the board's written words; ``cuts``: the times the camera moves to each stop)."""
    start, end, card, _ = entry
    stop = max(0, bisect.bisect_right(list(cuts), start + .3) - 1) if cuts else None
    board = _squash(' '.join(text for at, k, text in written
                             if at <= end and (k == stop if stop is not None else start - 1.5 <= at)))
    return bool(board) and all(_squash(k) in board for k in _keys(card))


def entries(episode, tline, lang) -> list:
    """(start, end, card, beat id) of every card: from the first figure's word to its sentence's end plus TAIL (at
    least MIN_HOLD, at most MAX_HOLD), never past the start of the next sentence (of its beat, else the next beat),
    the next card or the end card."""
    found = []
    timed = sorted((t['start'], bid) for bid, t in tline['beats'].items() if t.get('start') is not None)
    next_beat = {bid: timed[k + 1][0] for k, (_, bid) in enumerate(timed[:-1])}
    for beat in episode['beats']:
        timing = tline['beats'].get(beat['id'])
        if not timing or not timing.get('char_times'):
            continue
        display = beat.get('display')
        text = display.get(lang, '') if isinstance(display, dict) else str(display or '')
        spoken = beat['spoken'][lang] if isinstance(beat.get('spoken'), dict) else str(beat.get('spoken') or '')
        ct = timing['char_times']
        starts = [a for a, _ in figures.sentences(text)]
        for card in figures.beat_cards(beat, lang):
            a = figures.spoken_offset(text, spoken, card.start, lang)
            b = figures.spoken_offset(text, spoken, max(card.start, card.end - 1), lang)
            start = timing['start'] + ct[min(a, len(ct) - 1)] - .1
            said = timing['start'] + ct[min(b, len(ct) - 1)]
            # it leaves with its sentence: never over the next sentence of its beat, or the next beat's picture
            following = next((x for x in starts if x >= card.end), None)
            if following is not None:
                n = figures.spoken_offset(text, spoken, following, lang)
                leave = timing['start'] + ct[min(n, len(ct) - 1)] - .05
            else:
                leave = next_beat.get(beat['id'], math.inf) - .05
            hold = min(start + MAX_HOLD, max(said + TAIL, start + MIN_HOLD))
            found.append([start, min(hold, leave), card, beat['id']])
    found.sort(key=lambda e: e[0])
    stop = (tline.get('end_card') or {}).get('start', math.inf)
    for k, e in enumerate(found):
        following = found[k + 1][0] - .05 if k + 1 < len(found) else math.inf
        e[1] = min(e[1], following, stop)
    return [tuple(e) for e in found if e[1] - e[0] > .5]


def build(episode, tline, lang, skin, frame_size, elements=(), cuts=()):
    """The DataCards of an episode, or None when its script states no figures. ``elements``: the whiteboard's
    drawn elements, whose written words show some figures already."""
    found = entries(episode, tline, lang)
    if not found:
        return None
    written = [(el.trigger if getattr(el, 'start', None) is None else el.start, getattr(el, 'stretch', 0),
                ' '.join(el.drawing.lines)) for el in elements
               if isinstance(el.drawing, ink.TextDrawing) and isinstance(el.trigger, (int, float))
               and not getattr(el, 'skipped', False)]
    return DataCards(found, skin, lang, frame_size, written, [c[0] for c in cuts])

"""Boards for markup a script carries (kinodraw/markup.py): a code editor typing the code line by line, a typeset
formula, a warning card with the callout's own words, keycaps for a key combo, and the step indicator that stays on
screen while a numbered list is read.

Each is a drawable (``duration``, ``size``, ``state(elapsed) -> (RGBA, pen, down)``, as engine/ink.py) placed on its
own page by ``draw`` (render.Production._visuals), or painted over the frame (``StepRail``). Code is typed, never
handwritten: the hand stays away while it types. Nothing here runs the customer's code; an output panel shows only
output the script itself contains (a fenced block tagged output, console, terminal or text).
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import ink

MONO = ink.ASSETS / 'fonts' / 'JetBrainsMono-Medium.ttf'
MATH = ink.ASSETS / 'fonts' / 'STIXTwoText-Regular.ttf'
MATH_ITALIC = ink.ASSETS / 'fonts' / 'STIXTwoText-Italic.ttf'
MIN_LINE = .032                 # a code line is at least this share of the frame height (readable at 1080p)
OUTPUT_TAGS = {'output', 'console', 'terminal', 'text', 'stdout', 'shell-session', 'out'}
EDITOR = {'panel': (30, 34, 44, 255), 'bar': (44, 49, 62, 255), 'gutter': (98, 106, 122, 255),
          'text': (230, 225, 214, 255), 'keyword': (198, 146, 234, 255), 'string': (166, 218, 149, 255),
          'number': (247, 168, 108, 255), 'comment': (124, 132, 150, 255), 'call': (122, 182, 245, 255),
          'cursor': (240, 196, 92, 255), 'line': (50, 56, 72, 255)}
KEYWORDS = set('''and as assert async await break case catch class const continue def del do elif else except export
extends false False final finally fn for from func function if import in interface is lambda let match new nil None
not null or pass print private protected public raise return self static struct switch this throw true True try type
var void while with yield'''.split())
TOKEN = re.compile(r'(#.*$|//.*$|--.*$)|("(?:\\.|[^"\\])*"?|\'(?:\\.|[^\'\\])*\'?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)'
                   r'|(\s+|.)')


@lru_cache(maxsize=32)
def _font(path, size):
    return ImageFont.truetype(str(path), max(1, int(size)), layout_engine=ImageFont.Layout.BASIC)


def _colour_runs(line: str, lang: str):
    """(text, colour) runs of one code line: keywords, strings, numbers, comments and calls in their own colours."""
    runs = []
    for m in TOKEN.finditer(line):
        comment, string, num, word, other = m.groups()
        if comment and not (comment.startswith('#') and lang in ('c', 'cpp', 'css')) and \
                not (comment.startswith('--') and lang not in ('sql', 'lua', 'haskell')):
            colour = 'comment'
        elif comment:
            colour = 'text'
        elif string:
            colour = 'string'
        elif num:
            colour = 'number'
        elif word:
            following = line[m.end():m.end() + 1]
            colour = 'keyword' if word in KEYWORDS else 'call' if following == '(' else 'text'
        else:
            colour = 'text'
        runs.append((m.group(), EDITOR[colour]))
    return runs


BLINK = .53                 # seconds the finished code's cursor is shown, then hidden, like an editor's


class CodeDrawing:
    """A code editor panel (line numbers, monospace, the code's own indentation, syntax colours) whose code types in
    line by line over ``duration`` seconds, a cursor at the typing point. Typed, so no pen: the hand stays away."""

    dressed = True

    def __init__(self, code: str, lang: str, max_w: int, max_h: int, frame_h: int, duration: float):
        self.lines = code.expandtabs(4).split('\n')
        self.lang, self.terminal = lang, lang in OUTPUT_TAGS
        n = max(1, len(self.lines))
        bar = .085 * frame_h
        size = min(.05 * frame_h, (max_h - bar - .05 * frame_h) / (n * 1.42))
        size = max(MIN_LINE * frame_h, size)                    # a line is never smaller than MIN_LINE
        font = _font(MONO, size)
        advance = font.getlength('M')
        longest = max(len(line) for line in self.lines) if self.lines else 1
        gutter = 0 if self.terminal else advance * (len(str(n)) + 2)
        pad = .9 * advance
        width = min(max_w, max(.42 * max_w, gutter + pad * 2 + advance * (longest + 1)))
        columns = max(8, int((width - gutter - pad * 2) / advance))
        if longest > columns and size > MIN_LINE * frame_h:   # shrink to fit before wrapping
            size = max(MIN_LINE * frame_h, size * columns / longest)
            font, advance = _font(MONO, size), _font(MONO, size).getlength('M')
            gutter = 0 if self.terminal else advance * (len(str(n)) + 2)
            columns = max(8, int((width - gutter - pad * 2) / advance))
        rows = []                                           # (line number or None, indent, text)
        for k, line in enumerate(self.lines, 1):
            indent = len(line) - len(line.lstrip(' '))
            body = line[indent:]
            first = True
            while True:
                room = columns - indent - (0 if first else 2)
                rows.append((k if first else None, indent + (0 if first else 2), body[:max(1, room)]))
                body, first = body[max(1, room):], False
                if not body:
                    break
        pitch = size * 1.42
        height = min(max_h, bar + pad + pitch * len(rows) + pad)
        self.size = (int(math.ceil(width)), int(math.ceil(height)))
        self.font, self.advance, self.pitch, self.rows = font, advance, pitch, rows
        self.origin = (gutter + pad, bar + pad)
        self.duration = max(.1, duration)
        self.line_px = pitch
        self._base = self._panel(bar, gutter, pad, frame_h)
        self._typed = [sum(len(r[2]) for r in rows[:i]) for i in range(len(rows) + 1)]
        self._cache = (None, None)

    def _panel(self, bar, gutter, pad, frame_h):
        w, h = self.size
        img = Image.new('RGBA', self.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        r = .022 * frame_h
        d.rounded_rectangle((0, 0, w - 1, h - 1), r, fill=EDITOR['panel'])
        d.rounded_rectangle((0, 0, w - 1, bar), r, fill=EDITOR['bar'])
        d.rectangle((0, bar - r, w - 1, bar), fill=EDITOR['bar'])
        for k, colour in enumerate(((237, 106, 94), (245, 191, 79), (98, 197, 84))):
            cx, cy, dot = bar * .55 + k * bar * .42, bar / 2, bar * .13
            d.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=colour + (255,))
        tab = _font(ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf', bar * .36)
        label = 'Terminal' if self.terminal else (self.lang or 'code')
        d.text((bar * 1.9, bar / 2), label, font=tab, fill=EDITOR['gutter'], anchor='lm')
        if not self.terminal:
            for i, (number, _, _) in enumerate(self.rows):
                if number is not None:
                    y = self.origin[1] + i * self.pitch
                    d.text((gutter - self.advance, y), str(number), font=self.font, fill=EDITOR['gutter'], anchor='ra')
        return img

    def _image(self, shown: int):
        img = self._base.copy()
        d = ImageDraw.Draw(img)
        x0, y0 = self.origin
        # the line being typed is highlighted, as an editor does; the highlight steps down line by line
        row = len(self.rows) - 1 if shown >= self._typed[-1] else \
            max(i for i in range(len(self.rows)) if self._typed[i] <= shown)
        d.rectangle((x0 - self.advance * .45, y0 + row * self.pitch - self.pitch * .1, img.width - 1,
                     y0 + (row + 1) * self.pitch - self.pitch * .1), fill=EDITOR['line'])
        cursor = None
        for i, (_, indent, text) in enumerate(self.rows):
            room = shown - self._typed[i]
            if room <= 0:
                cursor = cursor or (x0 + indent * self.advance, y0 + i * self.pitch)
                break
            visible = text[:room]
            x = x0 + indent * self.advance
            for part, colour in _colour_runs(visible, self.lang):
                d.text((x, y0 + i * self.pitch), part, font=self.font, fill=colour)
                x += self.advance * len(part)
            if room < len(text) or (room == len(text) and i == len(self.rows) - 1):
                cursor = (x, y0 + i * self.pitch)
        if cursor is not None and shown < self._typed[-1] + 1:
            cx, cy = cursor
            d.rectangle((cx + 2, cy + self.pitch * .08, cx + 2 + self.advance * .55, cy + self.pitch * .78),
                        fill=EDITOR['cursor'])
        return img

    def shown(self, elapsed) -> int:
        total = self._typed[-1]
        return total if elapsed >= self.duration else max(0, int(total * elapsed / self.duration))

    def state(self, elapsed):
        if elapsed < 0:
            return None, None, False
        k = self.shown(elapsed)
        if k >= self._typed[-1] and elapsed >= self.duration and int((elapsed - self.duration) / BLINK) % 2:
            k = self._typed[-1] + 1                          # finished: the cursor blinks at the end of the code
        if self._cache[0] != k:
            self._cache = (k, self._image(k))
        return self._cache[1], None, False


# ------------------------------------------------------------------ typeset maths
MATH_TOKEN = re.compile(r'\\[A-Za-z]+|\d+(?:\.\d+)?|[A-Za-z]+|[²³¹⁰⁴⁵⁶⁷⁸⁹]+|\S')
SYMBOL = {'*': '·', '-': '−', '\\cdot': '·', '\\times': '×', '\\div': '÷', '\\approx': '≈', '\\le': '≤',
          '\\leq': '≤', '\\ge': '≥', '\\geq': '≥', '\\pi': 'π', '\\theta': 'θ', '\\alpha': 'α', '\\beta': 'β',
          '\\Delta': 'Δ', '\\sqrt': '√', '\\pm': '±'}
SPACED = set('=≈≤≥<>+−×÷±')
SUPERSCRIPT = dict(zip('²³¹⁰⁴⁵⁶⁷⁸⁹', '2310456789'))


def _boxes(tokens, size, out, x=0., rise=0.):
    """Lay ``tokens`` out from x as (text, font path, size, x, rise) glyph runs; returns the end x. Single letters
    are italic, digits and operators upright, ^ and _ groups set small and raised or lowered."""
    i, prev = 0, None
    while i < len(tokens):
        tok = SYMBOL.get(tokens[i], tokens[i])
        if tok in ('^', '_') and i + 1 < len(tokens):
            group, i = _group(tokens, i + 1)
            x = _boxes(group, size * .62, out, x + size * .04, rise + (size * .42 if tok == '^' else -size * .22))
            prev = 'x'
            continue
        if tok[0] in SUPERSCRIPT:
            x = _boxes([''.join(SUPERSCRIPT[c] for c in tok)], size * .62, out, x + size * .04, rise + size * .42)
            i += 1
            continue
        if tok == '-' or tok == '−':
            tok = '−'
        if tok.startswith('\\'):
            tok = tok[1:]
        italic = bool(re.fullmatch(r'[A-Za-zα-ωΔθπ]', tok)) and tok not in 'π'
        path = MATH_ITALIC if italic else MATH
        f = _font(path, size)
        gap = size * .22 if tok in SPACED and prev is not None else 0.
        x += gap
        out.append((tok, path, size, x, rise))
        x += f.getlength(tok) + (size * .03 if italic else 0.)
        x += size * .22 if tok in SPACED and i + 1 < len(tokens) else 0.
        prev = tok
        i += 1
    return x


def _group(tokens, i):
    if i < len(tokens) and tokens[i] in '{(':
        close, depth, j = ('}' if tokens[i] == '{' else ')'), 0, i
        while j < len(tokens):
            depth += tokens[j] in '{('
            depth -= tokens[j] in '})'
            if depth == 0:
                break
            j += 1
        inner = tokens[i + 1:j] if tokens[i] == '{' else tokens[i:j + 1]
        return inner, j + 1
    return tokens[i:i + 1], i + 1


def math_image(formula: str, size: float, colour) -> Image.Image:
    """``formula`` typeset: italic variables, upright numbers and operators, real superscripts (no caret)."""
    from ..markup import FUNCS
    tokens = []
    for tok in MATH_TOKEN.findall(formula):            # "mc" is m times c: each letter its own italic quantity
        tokens += list(tok) if re.fullmatch(r'[A-Za-z]{2,}', tok) and tok.lower() not in FUNCS else [tok]
    runs = []
    width = _boxes(tokens, size, runs)
    asc = size * 1.05
    top = max([asc + r for _, _, s, _, r in runs] + [asc]) + size * .1
    bottom = max([size * .35 - r for _, _, _, _, r in runs] + [size * .35]) + size * .1
    img = Image.new('RGBA', (int(math.ceil(width + size * .3)), int(math.ceil(top + bottom))), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for tok, path, s, x, rise in runs:
        d.text((x + size * .15, top - rise), tok, font=_font(path, s), fill=colour, anchor='ls')
    return img


# ------------------------------------------------------------------ cards
def warning_image(text: str, width: int, lang: str, fonts, frame_h: int) -> Image.Image:
    """A cream card with a drawn warning triangle and the callout's own words (no emoji)."""
    from ..speech import drawn
    words = drawn(text).strip()
    tri = .16 * frame_h
    pad = .045 * frame_h
    size = round(.05 * frame_h)
    lines, size = ink.fit_text(words, lang, width - tri - pad * 3, 4, size, min_size=round(.034 * frame_h),
                               fonts=fonts)
    f = ink.hand_font(lang, size, fonts)
    pitch = size * 1.25
    height = int(max(tri + pad * 2, pitch * len(lines) + pad * 2))
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    border = (196, 98, 30, 255)
    d.rounded_rectangle((3, 3, width - 4, height - 4), .02 * frame_h, fill=(255, 246, 220, 255), outline=border,
                        width=max(3, round(.004 * frame_h)))
    cx, cy = pad + tri / 2, height / 2
    pts = [(cx, cy - tri * .48), (cx + tri * .52, cy + tri * .42), (cx - tri * .52, cy + tri * .42)]
    d.polygon(pts, fill=(245, 186, 60, 255), outline=(40, 34, 30, 255), width=max(3, round(.005 * frame_h)))
    bang = _font(ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf', tri * .5)
    d.text((cx, cy + tri * .12), '!', font=bang, fill=(40, 34, 30, 255), anchor='mm')
    y = (height - pitch * len(lines)) / 2
    for line in lines:
        x = pad * 2 + tri
        for part, pf in ink.font_runs(line, lang, size, fonts):
            d.text((x, y), part, font=pf, fill=(46, 34, 26, 255))
            x += pf.getlength(part)
        y += pitch
    return img


def keycaps_image(keys: list[str], frame_h: int) -> Image.Image:
    """A row of keycaps with + between them ("Ctrl", "Shift", "N")."""
    size = .05 * frame_h
    f = _font(ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf', size)
    plus = _font(ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf', size * 1.1)
    cap_h, pad, gap = size * 2.1, size * .7, size * .55
    widths = [max(cap_h, f.getlength(k) + pad * 2) for k in keys]
    pw = plus.getlength('+')
    width = sum(widths) + (len(keys) - 1) * (pw + gap * 2) + 8
    img = Image.new('RGBA', (int(math.ceil(width)), int(math.ceil(cap_h + size * .3 + 8))), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 4.
    for k, (key, w) in enumerate(zip(keys, widths)):
        r = size * .35
        d.rounded_rectangle((x, 4 + size * .3, x + w, 4 + cap_h + size * .3), r, fill=(150, 156, 168, 255))
        d.rounded_rectangle((x, 4, x + w, 4 + cap_h), r, fill=(248, 248, 246, 255), outline=(60, 64, 72, 255),
                            width=max(2, round(size * .07)))
        d.text((x + w / 2, 4 + cap_h / 2), key, font=f, fill=(32, 36, 44, 255), anchor='mm')
        x += w
        if k < len(keys) - 1:
            d.text((x + gap + pw / 2, 4 + cap_h / 2), '+', font=plus, fill=(60, 64, 72, 255), anchor='mm')
            x += pw + gap * 2
    return img


# ------------------------------------------------------------------ the step indicator
class StepRail:
    """"STEP" over a column of numbered circles at the left edge, while a numbered list is read: steps done are
    ticked, the step being read is filled, the ones to come are outlined. ``steps`` = [(start, end, n, of)]."""

    def __init__(self, steps, accent, frame_size):
        self.steps = sorted(steps)
        self.accent = tuple(accent[:3]) + (255,)
        self.W, self.H = frame_size
        self.window = (self.steps[0][0], self.steps[-1][1]) if self.steps else (0., -1.)
        self._cache = {}

    def current(self, t):
        if not self.steps or not self.window[0] <= t < self.window[1] + .6:
            return None
        n, of = self.steps[0][2], self.steps[0][3]
        for start, _, k, total in self.steps:
            if start <= t:
                n, of = k, total
        return n, of

    def image(self, n, of):
        key = (n, of)
        if key not in self._cache:
            H = self.H
            r = .023 * H
            pitch = min(.085 * H, .62 * H / max(1, of))
            label = _font(ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf', .019 * H)
            num = _font(ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf', .024 * H)
            w = int(r * 2 + 12)
            h = int(.04 * H + pitch * (of - 1) + r * 2 + 12)
            img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            cx = w / 2
            d.text((cx, .012 * H), 'STEP', font=label, fill=(96, 104, 116, 255), anchor='mm')
            line = (180, 186, 194, 255)
            top = .04 * H + r + 4
            d.line((cx, top, cx, top + pitch * (of - 1)), fill=line, width=max(2, round(.003 * H)))
            for k in range(1, of + 1):
                cy = top + pitch * (k - 1)
                box = (cx - r, cy - r, cx + r, cy + r)
                if k < n:
                    d.ellipse(box, fill=self.accent)
                    d.line([(cx - r * .45, cy), (cx - r * .1, cy + r * .38), (cx + r * .5, cy - r * .4)],
                           fill=(255, 255, 255, 255), width=max(3, round(r * .2)), joint='curve')
                elif k == n:
                    d.ellipse((cx - r * 1.12, cy - r * 1.12, cx + r * 1.12, cy + r * 1.12), fill=self.accent)
                    d.text((cx, cy), str(k), font=num, fill=(255, 255, 255, 255), anchor='mm')
                else:
                    d.ellipse(box, fill=(255, 255, 255, 255), outline=line, width=max(2, round(.003 * H)))
                    d.text((cx, cy), str(k), font=num, fill=(150, 156, 166, 255), anchor='mm')
            self._cache[key] = img
        return self._cache[key]

    def paint(self, frame, t):
        found = self.current(t)
        if found is None:
            return
        img = self.image(*found)
        start = self.steps[0][0]
        fade = min(1., (t - start) / .3, (self.window[1] + .6 - t) / .3)
        if fade < 1:
            img = img.copy()
            img.putalpha(img.getchannel('A').point(lambda a: int(a * max(0., fade))))
        ink.paste(frame, img, .012 * self.W, (self.H - img.height) / 2 - .02 * self.H)


def step_rail(episode, tline, lang, accent, frame_size):
    """The StepRail for an episode's numbered steps (beats marked {'kind': 'step'}), or None."""
    steps = [(tline['beats'][b['id']]['start'], tline['beats'][b['id']]['end'], b['markup']['n'], b['markup']['of'])
             for b in episode['beats'] if (b.get('markup') or {}).get('kind') == 'step' and b['id'] in tline['beats']]
    return StepRail(steps, accent, frame_size) if steps else None


# ------------------------------------------------------------------ placing a markup board
def make(prod, beat, mark, w, h):
    """(drawing, drawn by the hand) of a beat's markup board fitted in w x h page pixels. Code types in during the
    beat's pause; a formula, a warning card and keycaps are drawn by the hand while the beat is said."""
    bt = prod.tl['beats'][beat['id']]
    start, end = bt['start'], bt['end']
    H = prod.size[1]
    if mark['kind'] == 'code':
        drawing = CodeDrawing(mark['code'], mark['lang'], round(w * .92), round(h), H, max(.6, (end - start) * .92))
        hand = False
    elif mark['kind'] == 'math':
        size = min(.115 * H, h * .6)
        img = math_image(mark['formula'], size, ink.rgba(prod.skin.ink))
        if img.width > w * .94:
            img = math_image(mark['formula'], size * w * .94 / img.width, ink.rgba(prod.skin.ink))
        drawing = ink.RevealDrawing(img, min_dur=.8, max_dur=max(.8, min(2.4, (bt['speech_end'] - start) * .8)))
        hand = True
    else:
        img = warning_image(mark['text'], round(min(w * .86, 1500)), prod.lang, prod.skin.fonts, H)
        drawing = ink.RevealDrawing(img, min_dur=.8, max_dur=max(.8, min(2.6, (bt['speech_end'] - start) * .7)))
        hand = True
    drawing.dressed = True
    drawing.words = mark.get('code') or mark.get('formula') or mark.get('text')
    return drawing, hand


def draw(prod, beat, mark):
    """Put a beat's markup board (markup.board) on a page of the whiteboard Production ``prod``: the camera cuts to it
    when the beat starts and it stays until the next page. The page is its own, or the top of one whose lower part
    carries the scene's later board items (process_diagrams.Boards.share)."""
    bt = prod.tl['beats'][beat['id']]
    start, end = bt['start'], bt['end']
    shared = getattr(prod, 'markup_pages', {}).pop(beat['id'], None)
    if shared is not None:
        (x0, y0, w, h), col, (drawing, hand) = shared
    else:
        (x0, y0, w, h), (col, _) = prod.layout.page()
        drawing, hand = make(prod, beat, mark, w, h)
    prod.cut(start, col * prod.g.col, 'cut')
    x = x0 + (w - drawing.size[0]) / 2
    y = y0 + (h - drawing.size[1]) / 2
    el = prod.ctx.add(drawing, x, y, start + .05, essential=True, group=f"markup:{beat['id']}", beat=beat['id'],
                      deadline=max(start + drawing.duration + .1, end - .05), hand=hand, fixed=not hand)
    prod._visual_triggers[id(el)] = (el, start + .05)
    return el


def keycaps_drawing(keys, frame_h):
    """Keycaps as a drawing the hand draws."""
    drawing = ink.RevealDrawing(keycaps_image(keys, frame_h), min_dur=.6, max_dur=1.2)
    drawing.dressed = True
    drawing.words = ' + '.join(keys)
    return drawing

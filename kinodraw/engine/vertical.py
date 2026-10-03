"""The vertical 9:16 layout for Shorts, TikTok and Reels: a letterbox, not a crop and not a reflow.

Every frame is 1080 x 1920 on the look's paper colour. The look's own 16:9 frame (board, hand, transitions; no chrome
and no captions) is scaled to 1080 x 608 in the middle; the section's title is written above it in the look's
handwriting and the captions are set below it, larger than they could be on the scaled board (normally at most 3
lines, 960 px wide). At the end card the title above is the video's and the "Made with ..." credit is set below at a
readable size.

Vertical wraps any production (whiteboard, its skins, collage) and answers what they answer (frame, warnings,
ctx.elements, cues), so pacing, parallel rendering, stills, the mix and packaging treat it like the others.
"""
from __future__ import annotations

import bisect
from functools import lru_cache

from PIL import Image, ImageDraw

from . import captions as cap
from . import ink

W, H = 1080, 1920
BOARD = (0, 656, 1080, 608)            # x, y, w, h: the 16:9 frame, scaled 0.5625, in the middle
TEXT_W = 960                           # captions and titles keep 60 px from either side
TITLE_GAP = 40                         # between the title block and the board
TITLE_H = BOARD[1] - TITLE_GAP - 200   # the title block stays under the app's top bar
CAP_GAP = 44                           # between the board and the captions
CAP_SIZE, CAP_MIN, CAP_LINES = 64, 44, 3
FADE_IN, FADE_OUT = .4, .3             # titles fade like the 16:9 chrome does; nothing pops


class Vertical:
    vertical = True
    size = (W, H)

    def __init__(self, prod):
        self.prod = prod
        prod.vertical = True                 # its frame is now the board alone: no chrome, no captions
        self.ep, self.tl, self.lang = prod.ep, prod.tl, prod.lang
        self.skin = getattr(prod, 'skin', None)
        from .skin import WHITEBOARD
        self.fonts = (self.skin or WHITEBOARD).fonts
        self.collage = self.skin is None
        self._base = self._background()
        self.cap_starts = [c['start'] for c in self.tl.get('captions', [])]
        self.tops = self._title_spans()
        self.top_starts = [s[0] for s in self.tops]

    def __getattr__(self, name):             # warnings, ctx, els, cues(), crowded() ... are the production's
        return getattr(self.prod, name)

    # ------------------------------------------------------------ layout
    def _background(self):
        if self.collage:
            from . import motion
            return motion.paper_texture((W, H), 'cream').convert('RGBA')
        return Image.new('RGBA', (W, H), tuple(self.skin.base[:3]) + (255,))

    def _ink(self):
        return (40, 40, 40) if self.collage else tuple(self.skin.ink[:3])

    def _soft(self):
        return (85, 96, 106) if self.collage else tuple(self.skin.soft[:3])

    def _title_spans(self):
        """[(start, end, key)]: what is written above the board when; key ('chapter', id) or ('title',) (the video's).
        Neighbouring stretches with the same key are one stretch, so the video's title never blinks."""
        chapters = {c['id']: c for c in self.ep['chapters']}
        spans, t = [], 0.
        for c in sorted(self.tl['chapters'], key=lambda c: c['start']):
            if c['start'] > t:
                spans.append([t, c['start'], ('title',)])
            kind = chapters.get(c['id'], {}).get('kind')
            spans.append([c['start'], c['end'], ('chapter', c['id']) if kind in ('section', 'agenda') else ('title',)])
            t = c['end']
        end = self.tl['duration']
        if t < end:
            spans.append([t, end, ('title',)])
        merged = []
        for s in spans:
            if merged and merged[-1][2] == s[2] and abs(merged[-1][1] - s[0]) < 1e-6:
                merged[-1][1] = s[1]
            else:
                merged.append(s)
        return [tuple(s) for s in merged]

    def title_at(self, t):
        """(image, alpha) of the title block above the board at time t, or (None, 0)."""
        i = bisect.bisect_right(self.top_starts, t) - 1
        if i < 0:
            return None, 0.
        a, b, key = self.tops[i]
        if not a <= t < b:
            return None, 0.
        fade_in = 1. if a <= 0 else (t - a) / FADE_IN
        fade_out = 1. if b >= self.tl['duration'] - 1e-6 else (b - t) / FADE_OUT
        return self._title_image(key), max(0., min(1., fade_in, fade_out))

    @lru_cache(maxsize=64)
    def _title_image(self, key):
        lang, fonts = self.lang, self.fonts
        if key[0] == 'title':
            label, title, color = None, (self.ep.get('title') or {}).get(lang, ''), None
            source = None
            size, lines_max = 92, 3
        else:
            ch = next(c for c in self.ep['chapters'] if c['id'] == key[1])
            label = (ch.get('label') or {}).get(lang) if ch['kind'] == 'section' else None
            title = (ch.get('title') or {}).get(lang) or (ch.get('label') or {}).get(lang, '')
            color = ink.SECTION_COLORS.get(ch.get('color'))
            from .render import source_line
            source = source_line(ch, lang)
            size, lines_max = 80, 2
        parts = []                                       # (image, gap above)
        if label and label.strip().lower() != title.strip().lower():
            label = label.upper() if lang == 'en' else label
            parts.append((_ui_line(_fit_ui(label, 38, fonts), 38, self._label_color(color), fonts), 0))
        room = TITLE_H - 6 * bool(parts) - sum(img.height for img, _ in parts) - (18 if color else 0) \
            - (56 if source else 0)                     # what the title lines may use, beside label, bar and source
        lines, size = ink.fit_text(title, lang, TEXT_W, lines_max, size, min_size=48, fonts=fonts)
        tall = lambda: int(size * 1.2) * len(lines) + 16 > room
        if any(ink.text_width(l, lang, size, fonts) > TEXT_W for l in lines) or tall():
            while True:
                lines = _wrap(title, lang, TEXT_W, lambda t: ink.text_width(t, lang, size, fonts))
                if size <= 8 or (len(lines) <= lines_max or size <= 40) and not tall():
                    break                                # below 40 px only when the title would not fit otherwise
                size = max(8, size - 2)
        lh = int(size * 1.2)
        block = Image.new('RGBA', (W, lh * len(lines) + 16), (0, 0, 0, 0))
        d = ImageDraw.Draw(block)
        for k, line in enumerate(lines):
            x = (W - ink.text_width(line, lang, size, fonts)) / 2
            for part, f in ink.font_runs(line, lang, size, fonts):
                d.text((x, 4 + k * lh), part, font=f, fill=self._ink() + (255,))
                x += f.getlength(part)
        parts.append((block, 6 if parts else 0))
        if color:                                        # the section's colour, as a short underline
            bar = Image.new('RGBA', (W, 12), (0, 0, 0, 0))
            ImageDraw.Draw(bar).rounded_rectangle(((W - 140) / 2, 0, (W + 140) / 2, 9), 5,
                                                  fill=self._label_color(color) + (255,))
            parts.append((bar, 6))
        if source:
            parts.append((_ui_line(_fit_ui(source, 30, fonts), 30, self._soft(), fonts), 12))
        h = sum(img.height + gap for img, gap in parts)
        out = Image.new('RGBA', (W, h), (0, 0, 0, 0))
        y = 0
        for img, gap in parts:
            y += gap
            out.alpha_composite(img, ((W - img.width) // 2, y))
            y += img.height
        return out

    def _label_color(self, color):
        if not color:
            return self._soft()
        return tuple(color) if self.collage else tuple(self.skin.color(color))

    def caption_at(self, t):
        i = bisect.bisect_right(self.cap_starts, t) - 1
        if i < 0:
            return None
        c = self.tl['captions'][i]
        return c['text'] if c['start'] <= t < c['end'] else None

    def caption_image(self, text):
        color = (18, 18, 18) if self.collage else tuple(self.skin.caption)
        edge = (255, 255, 255) if self.collage else tuple(self.skin.caption_edge)
        return caption_image(text, self.lang, self.fonts, color, edge)

    def caption_box(self, text):
        """Where a caption goes: (x, y, w, h), its top CAP_GAP below the board, centred."""
        img = self.caption_image(text)
        return (W - img.width) // 2, BOARD[1] + BOARD[3] + CAP_GAP, img.width, img.height

    def _credit(self, t):
        cr = self.tl.get('credit')
        if not cr or t < cr['start'] - .8:
            return None, 0.
        from .. import PRODUCT
        from .auto_scenes import CREDIT_LINE
        return _credit_image(CREDIT_LINE[self.lang].format(**PRODUCT), PRODUCT['url'], self.lang, self.fonts,
                             self._soft()), min(1., (t - cr['start'] + .8) / FADE_IN)

    # ------------------------------------------------------------ frame
    def frame(self, t):
        board = self.prod.frame(t)
        out = self._base.copy()
        out.paste(board.convert('RGB').resize(BOARD[2:], Image.LANCZOS), BOARD[:2])
        img, alpha = self.title_at(t)
        if img is not None and alpha > 0:
            ink.paste(out, _faded(img, alpha), 0, BOARD[1] - TITLE_GAP - img.height)
        text = self.caption_at(t)
        if text:
            x, y, _, _ = self.caption_box(text)
            ink.paste(out, self.caption_image(text), x, y)
        else:
            img, alpha = self._credit(t)
            if img is not None:
                ink.paste(out, _faded(img, alpha), (W - img.width) // 2, BOARD[1] + BOARD[3] + CAP_GAP + 20)
        return out


def _faded(img, alpha):
    if alpha >= 1:
        return img
    out = img.copy()
    out.putalpha(out.getchannel('A').point(lambda a: int(a * alpha)))
    return out


def _ui_line(text, size, color, fonts):
    f = ink.font('ui' if all(ord(c) < 0x2e80 for c in text) else 'zh_caption', size, fonts)
    img = Image.new('RGBA', (int(f.getlength(text)) + 6, size + 14), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((3, 3), text, font=f, fill=tuple(color) + (255,))
    return img


def _fit_ui(text, size, fonts):
    """Shorten a one-line label to TEXT_W with an ellipsis."""
    f = ink.font('ui' if all(ord(c) < 0x2e80 for c in text) else 'zh_caption', size, fonts)
    if f.getlength(text) <= TEXT_W:
        return text
    while text and f.getlength(text + '…') > TEXT_W:
        text = text[:-1]
    return text.rstrip() + '…'


def wrap(text, lang, size, fonts=ink.FONTS, width=TEXT_W):
    """Balanced lines of ``text`` no wider than ``width`` in the caption font at ``size``: the fewest lines, then the
    narrowest widest line, so a two-line caption is two even lines rather than a full one and a stub."""
    f = ink.font('en_caption' if lang == 'en' else 'zh_caption', size, fonts)
    return _wrap(text, lang, width, f.getlength)


def _break_unit(unit, width, measure):
    """Keep fitting words intact; split wide ones after URL separators, then between characters."""
    if measure(unit.strip()) <= width:
        return [unit]
    pieces, start = [], 0
    for k, ch in enumerate(unit):
        if ch in '/.-_?&=#:':
            pieces.append(unit[start:k + 1])
            start = k + 1
    if start < len(unit):
        pieces.append(unit[start:])
    return [part for piece in pieces for part in
            ([piece] if measure(piece.strip()) <= width else _chunks(piece, width, measure))]


def _chunks(piece, width, measure):
    """The longest runs of characters that fit ``width``, so a very long word wraps in one pass."""
    out, cur = [], ''
    for ch in piece:
        if cur and measure(cur + ch) > width:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    return out + [cur] if cur else out


def _wrap(text, lang, width, measure):
    """Balance intact words and fragments using the supplied caption or title measurement."""
    us = [piece for unit in cap.units(text.strip(), lang) for piece in _break_unit(unit, width, measure)]
    closing = '，。！？；：、）」』”’%'

    def greedy(limit):
        lines, cur = [], ''
        for u in us:
            if cur and measure((cur + u).strip()) > limit:
                lines.append(cur.strip())
                cur = u
            else:
                cur += u
        if cur.strip():
            lines.append(cur.strip())
        if lang == 'zh':                                 # no line starts with closing punctuation
            for k in range(1, len(lines)):
                while lines[k][:1] and lines[k][0] in closing and len(lines[k]) > 1:
                    lines[k - 1] += lines[k][0]
                    lines[k] = lines[k][1:]
        return lines

    lines = greedy(width)
    if lang == 'zh' and (any(measure(line) > width for line in lines) or
                         any(line[:1] in closing for line in lines[1:])):
        # Reserve room for punctuation without discarding the word and URL break opportunities.
        grouped = []
        for unit in us:
            if unit[:1] in closing and grouped:
                tail = grouped.pop()
                while tail.isspace() and grouped:
                    tail = grouped.pop() + tail
                grouped.append(tail + unit)
            else:
                grouped.append(unit)
        us = []
        for unit in grouped:
            for piece in _break_unit(unit, width, measure):
                if piece[:1] in closing and us:
                    tail = us.pop()
                    while tail.isspace() and us:
                        tail = us.pop() + tail
                    us.append(tail + piece)
                else:
                    us.append(piece)
        lines = greedy(width)
    n = len(lines)
    lo, hi = 1., float(width)
    for _ in range(14):                                  # the narrowest limit that keeps the same number of lines
        mid = (lo + hi) / 2
        trial = greedy(mid)
        if len(trial) <= n and all(measure(l) <= width for l in trial):
            hi = mid
        else:
            lo = mid
    best = greedy(hi)
    if lang == 'zh' and any(line[:1] in closing for line in best[1:]):
        return lines
    return best if len(best) <= n and all(measure(l) <= width for l in best) else lines


@lru_cache(maxsize=1024)
def caption_lines(text, lang, fonts=ink.FONTS):
    """Prefer CAP_LINES at CAP_MIN or larger; then the largest size whose lines fit the height above the buttons."""
    for size in range(CAP_SIZE, CAP_MIN - 1, -2):
        lines = wrap(text, lang, size, fonts)
        if len(lines) <= CAP_LINES:
            return lines, size
    available = H - 240 - (BOARD[1] + BOARD[3] + CAP_GAP)
    for size in range(CAP_MIN, 7, -2):
        lines = wrap(text, lang, size, fonts)
        if _caption_height(len(lines), size) <= available or size == 8:
            return lines, size                       # below 36 px only for one enormous word: smaller, never cut off


def _caption_height(line_count, size):
    return int(size * 1.18) * line_count + 2 * max(5, round(size / 10)) + 10


@lru_cache(maxsize=1024)
def caption_image(text, lang, fonts=ink.FONTS, color=(18, 18, 18), edge=(255, 255, 255)):
    """The caption below the board: ``color`` letters in an ``edge`` outline, like the 16:9 captions, larger."""
    lines, size = caption_lines(text, lang, fonts)
    f = ink.font('en_caption' if lang == 'en' else 'zh_caption', size, fonts)
    stroke = max(5, round(size / 10))
    lh = int(size * 1.18)
    widths = [f.getlength(l) for l in lines]
    w = int(max(widths)) + 2 * stroke + 8
    h = _caption_height(len(lines), size)
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text(((w - widths[i]) / 2, stroke + i * lh), line, font=f, fill=tuple(color) + (255,), stroke_width=stroke,
               stroke_fill=tuple(edge) + (255,))
    return img


@lru_cache(maxsize=8)
def _credit_image(made, url, lang, fonts, color):
    a = _ui_line(made, 48, color, fonts)
    b = _ui_line(url, 36, color, fonts)
    out = Image.new('RGBA', (max(a.width, b.width), a.height + b.height + 4), (0, 0, 0, 0))
    out.alpha_composite(a, ((out.width - a.width) // 2, 0))
    out.alpha_composite(b, ((out.width - b.width) // 2, a.height + 4))
    return out

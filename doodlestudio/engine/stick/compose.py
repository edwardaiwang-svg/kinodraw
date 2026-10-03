"""Storyboard + timeline -> shots for the stick look.

A shot is a fixed picture cut in hard (no pans, no zooms): a ground strip, a header tab, a figure or a crowd and
up to two "cards" (a doodle with its label, a big number, a quote bubble, a term), plus red marks. Cards and marks
appear when their words are said; everything else is there at the cut. Shots follow sentence ends: each is at
least MIN_SHOT long and a long one is cut again at its second card. Layouts alternate so two shots in a row never
share one, and every item has a fixed screen rectangle so tests can check that nothing overlaps.

Screen regions (1920x1080): header tab 28..98, stage 130..GROUND_Y (900), ground strip below it, captions on top
of the ground strip (955..1050).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Callable

from PIL import Image, ImageDraw

from ... import numbers, script
from .. import ink
from . import cues, marks, paint, palette, rig, text
from .rig import DRAW_FPS

W, H = 1920, 1080
GROUND_Y = 900
STAGE_TOP = 130
MIN_SHOT, MAX_SHOT = 2.2, 8.0
POP = 1 / DRAW_FPS                         # a card is drawn 8% larger for one drawing frame when it appears
FIG_H = 600.
UI = {'en': {'take': 'Key takeaway', 'thanks': 'Thanks for watching!', 'part': 'Part {n}'},
      'zh': {'take': '本节要点', 'thanks': '感谢收看！', 'part': '第{n}部分'}}


# ------------------------------------------------------------------ items
@dataclass(eq=False)
class Item:
    kind: str                              # figure crowd doodle label text number bubble panel tab mark ground
    rect: tuple                            # finished screen rectangle (x0, y0, x1, y1)
    t0: float
    paint: Callable                        # paint(frame, t, k, variant)
    layer: int = 1
    collide: bool = True                   # counted in overlap checks
    group: str = ''                        # a card's parts may touch each other
    moving: Callable | None = None         # moving(t): must be redrawn every frame (motion, mouth, a mark)
    boil: bool = False                     # changes with the boil drawing (cached per drawing)
    t1: float = math.inf

    def visible(self, t):
        return self.t0 <= t < self.t1

    def animated(self, t):
        return t < self.t0 + POP or (self.moving is not None and self.moving(t))


@dataclass(eq=False)
class Shot:
    start: float
    end: float
    layout: str
    chapter: str
    beats: tuple
    ground: str | None
    items: list = field(default_factory=list)
    words: str = ''
    pose: str = ''


def _paste_pop(frame, img, x, y, t, t0):
    if t < t0 + POP:
        s = 1.08
        big = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BICUBIC)
        ink.paste(frame, big, x - (big.width - img.width) / 2, y - (big.height - img.height) / 2)
    else:
        ink.paste(frame, img, x, y)


def image_item(kind, get, x, y, t0, group='', boil=False, layer=1, collide=True, pop=True):
    """An image that appears at ``t0``: ``get(variant)`` returns it (the same image for every drawing unless
    ``boil``)."""
    img = get(0)
    rect = (float(x), float(y), float(x + img.width), float(y + img.height))

    def draw(frame, t, k, variant):
        im = get(variant) if boil else img
        if pop:
            _paste_pop(frame, im, x, y, t, t0)
        else:
            ink.paste(frame, im, x, y)
    return Item(kind, rect, t0, draw, layer=layer, collide=collide, group=group, boil=boil)


def text_item(s, lang, cx, y, size, t0, max_w=1600, max_lines=2, color=(0, 0, 0), outline=0, group='',
              align='center', upper=False, min_size=26, kind='label', anchor='top'):
    img = text.block(s, lang, size, max_w=max_w, max_lines=max_lines, color=tuple(color), outline=outline,
                     align=align, upper=upper, min_size=min_size)
    x = cx - img.width / 2 if align == 'center' else (cx if align == 'left' else cx - img.width)
    yy = y - img.height / 2 if anchor == 'middle' else (y - img.height if anchor == 'bottom' else y)
    return image_item(kind, lambda v: img, x, yy, t0, group=group)


def mark_item(mark: marks.Mark, t1=math.inf):
    def draw(frame, t, k, variant):
        mark.paint(frame, t, variant)
    return Item('mark', mark.extent(), mark.start, draw, layer=3, collide=False,
                moving=lambda t: t < mark.start + mark.dur + POP * 2, t1=t1)


def _bbox_of(drawn: rig.Drawn):
    """Inked bounding box relative to the feet point."""
    ox, oy = drawn.origin
    box = drawn.image.getchannel('A').getbbox() or (0, 0, 1, 1)
    return (box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy)


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def figure_extent(fig, crop=None):
    """Bounding box of every frame of the figure's motion, relative to its feet."""
    box = None
    frames = range(rig.cycle_len(fig.pose))
    for k in frames:
        for mo in ((None,) if fig.mouth_open is None else (True, False)):
            f = fig if mo is None else replace(fig, mouth_open=mo)
            b = _bbox_of(rig.draw(f, k, 0, crop))
            box = b if box is None else _union(box, b)
    return box


def fit_figure(fig, lane, travel=0.):
    """Scale the figure down until its whole motion (plus ``travel`` px of walking) fits ``lane``; return the
    fitted figure and its feet position (standing on the lane's bottom edge, centred)."""
    x0, y0, x1, y1 = lane
    for _ in range(4):
        bx0, by0, bx1, by1 = figure_extent(fig)
        s = min(1., (x1 - x0 - abs(travel)) / max(1., bx1 - bx0), (y1 - y0) / max(1., by1 - by0))
        if s >= .995:
            break
        fig = replace(fig, height=fig.height * s * .98)
    bx0, by0, bx1, by1 = figure_extent(fig)
    feet = ((x0 + x1) / 2 - (bx0 + bx1) / 2 - travel / 2, y1 - by1)
    return fig, feet


def figure_item(fig, feet, t0, talk=None, walk=None, crop=None, group='figure', kind='figure', collide=True):
    """The figure standing with its feet at ``feet``. ``talk(t)``: mouth open now; ``walk`` = (dx, t_a, t_b): walk
    ``dx`` px between those times (stepping at 15 fps), then stand still."""
    ext = figure_extent(fig, crop)
    fx, fy = feet
    rect = (fx + ext[0], fy + ext[1], fx + ext[2], fy + ext[3])
    if walk:
        rect = _union(rect, (rect[0] + walk[0], rect[1], rect[2] + walk[0], rect[3]))
    still = replace(fig, pose='stand') if walk and fig.pose in ('walk', 'run') else fig

    def draw(frame, t, k, variant):
        f, x = fig, fx
        kk = k
        if walk:
            dx, ta, tb = walk
            if t < tb:
                u = max(0., (math.floor(t * DRAW_FPS) / DRAW_FPS - ta) / max(.01, tb - ta))
                x = fx + dx * min(1., u)
            else:
                f, x = still, fx + dx
        if f.pose == 'fall':
            kk = int((t - t0) * DRAW_FPS)
        if talk is not None and f.pose != 'fall':
            f = replace(f, mouth_open=bool(talk(t)))
        dr = rig.draw(f, kk, variant, crop)
        ink.paste(frame, dr.image, x - dr.origin[0], fy - dr.origin[1])

    animated = rig.cycle_len(fig.pose) > 1 or talk is not None or walk is not None

    def moving(t):
        if fig.pose == 'fall':
            return t < t0 + rig.cycle_len('fall') / DRAW_FPS
        if walk and t >= walk[2] and talk is None:
            return False
        return animated
    return Item(kind, rect, t0, draw, layer=2, group=group, moving=moving, boil=True, collide=collide)


def crowd_item(crowd, feet, t0, group='crowd'):
    probe = [rig.draw_crowd(crowd, k, 0) for k in range(4)]
    box = None
    for dr in probe:
        b = _bbox_of(dr)
        box = b if box is None else _union(box, b)
    fx, fy = feet
    rect = (fx + box[0], fy + box[1], fx + box[2], fy + box[3])

    def draw(frame, t, k, variant):
        dr = rig.draw_crowd(crowd, k, variant)
        ink.paste(frame, dr.image, fx - dr.origin[0], fy - dr.origin[1])
    return Item('crowd', rect, t0, draw, layer=2, group=group, moving=lambda t: True, boil=True)


def fit_crowd(crowd, lane):
    x0, y0, x1, y1 = lane
    for _ in range(4):
        b = _bbox_of(rig.draw_crowd(crowd, 0, 0))
        s = min(1., (x1 - x0) / max(1., b[2] - b[0]) * .97, (y1 - y0) / max(1., b[3] - b[1]) * .9)
        if s >= .99:
            break
        crowd = replace(crowd, height=crowd.height * s)
    b = _bbox_of(rig.draw_crowd(crowd, 0, 0))
    return crowd, ((x0 + x1) / 2 - (b[0] + b[2]) / 2, y1 - 2)


# ------------------------------------------------------------------ cards
@dataclass
class Card:
    kind: str                              # doodle number quote term title grid timeline
    t: float
    data: dict
    vid: str = ''


def _clean_label(label, display, lang):
    """A label is shown only if it is whole words of the sentence (the director sometimes cuts a word short)."""
    label = (label or '').strip()
    if not label:
        return ''
    if lang == 'en':
        words = re.findall(r"[A-Za-z0-9'’-]+", label)
        if len(label) < 3 or not words:
            return ''
        if not all(re.search(r'(?<![A-Za-z0-9])' + re.escape(w) + r'(?![A-Za-z0-9])', display, re.I) for w in words):
            return ''
        while words and words[-1].lower() in ('the', 'a', 'an', 'of', 'to', 'and', 'in', 'on'):
            label = label[:label.lower().rfind(words[-1].lower())].strip()
            words = words[:-1]
        return label
    return label if len(label) >= 2 and label in display else ''


def sentence_with(value, display, lang):
    """The sentence of ``display`` that says ``value`` (the whole text when none does)."""
    for sent in script.sentences(display, lang) or [display]:
        if value and value in sent:
            return sent
    return display


def _name_only(term, lang):
    """An English term that starts with a capital is a name: keep its capitalised words ("Odoacer removed" ->
    "Odoacer")."""
    if lang != 'en' or not term[:1].isupper():
        return term
    words = term.split()
    keep = words
    for i, w in enumerate(words[1:], 1):
        if not (w[:1].isupper() or w.lower() in ('of', 'the', 'de', 'von', 'van', 'al')):
            keep = words[:i]
            break
    return ' '.join(keep).rstrip(',;:')


def number_text(value, display):
    """The number as the sentence says it: a decade keeps its "s" ("the 270s"), a range keeps both ends
    ("between 235 and 284" -> 235–284)."""
    v = value.strip()
    if not re.fullmatch(r'[\d,.]+', v):
        return v
    m = re.search(re.escape(v) + r'\s*(?:and|to|-|–)\s*(\d(?:[\d,.]*\d)?)', display)
    if m and re.search(r'\b(?:between|from)\s+' + re.escape(v), display, re.I):
        return f'{v}–{m.group(1)}'
    if re.search(re.escape(v) + r's\b', display):
        return v + 's'
    return v


NUMBER = {'en': re.compile(r'(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d{2,})(%?)(?![\w])'),
          'zh': re.compile(r'(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{2,})(%|年|倍|亿|万|岁|度|公里|米)?')}
POINTER = re.compile(r'^\s*(?:(?:this|that|these|those|it)\b|这|那|它)', re.I)
NOT_LABELS = {'and', 'the', 'was', 'were', 'when', 'until', 'after', 'before', 'with', 'for', 'had', 'has', 'have',
              'that', 'this', 'its', 'his', 'her', 'their', 'from', 'into', 'but', 'then', 'they', 'are', 'all'}


def doodle_block(did, label, lang, box, t, gid, project_dir, size=56):
    """Doodle with its label under it, centred in ``box``; returns (items, doodle rect)."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    lab = text.block(label, lang, size, max_w=bw, max_lines=2, min_size=34) if label else None
    lh = lab.height + 10 if lab else 0
    first = paint.doodle(did, (int(bw), int(bh - lh)), 0, project_dir)
    total = first.height + lh
    top = y0 + (bh - total) / 2
    dx = x0 + (bw - first.width) / 2
    items = [image_item('doodle', lambda v: paint.doodle(did, (int(bw), int(bh - lh)), v, project_dir), dx, top, t,
                        group=gid, boil=True)]
    if lab:
        items.append(image_item('label', lambda v: lab, x0 + (bw - lab.width) / 2, top + first.height + 10, t,
                                group=gid))
        return items, _union(items[0].rect, items[1].rect)
    return items, items[0].rect


def number_block(value, label, lang, box, t, gid, people=None):
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    num = text.block(value, lang, 200 if bh > 380 else 150, max_w=bw, max_lines=1, min_size=80)
    lab = text.block(label, lang, 52, max_w=bw, max_lines=2, min_size=34) if label else None
    grid = None
    if people is not None and bh - num.height - (lab.height if lab else 0) > 300:
        grid = people_grid(int(people), int(min(bw, bh - num.height - (lab.height if lab else 0) - 40)))
    parts = [num] + ([grid] if grid else []) + ([lab] if lab else [])
    total = sum(p.height for p in parts) + 16 * (len(parts) - 1)
    y = y0 + (bh - total) / 2
    items, num_rect = [], None
    for p in parts:
        it = image_item('number' if p is num else 'label', lambda v, p=p: p, x0 + (bw - p.width) / 2, y, t, group=gid)
        items.append(it)
        if p is num:
            num_rect = it.rect
        y += p.height + 16
    # the drawn glyphs sit inside the image's padding: underline the ink, not the box
    nx0, ny0, nx1, ny1 = num_rect
    items.append(mark_item(marks.Mark('underline', (nx0 + 8, ny0, nx1 - 8, ny1 - num.height * .12), t + .35,
                                      seed=int(t * 100))))
    return items, num_rect


def people_grid(filled, side):
    """10x10 tiny stick people; the first ``filled`` in red."""
    cell = side / 10
    img = Image.new('RGBA', (int(side), int(side)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(100):
        r, c = divmod(i, 10)
        cx, cy = c * cell + cell / 2, r * cell + cell * .3
        col = palette.RED if i < filled else (0, 0, 0)
        hr = cell * .17
        lw = max(2, int(cell * .06))
        d.ellipse((cx - hr, cy - hr, cx + hr, cy + hr), outline=col + (255,), width=lw, fill=(255, 255, 255, 255))
        d.line((cx, cy + hr, cx, cy + cell * .45), fill=col + (255,), width=lw)
        d.line((cx - cell * .18, cy + cell * .3, cx, cy + cell * .45), fill=col + (255,), width=lw)
        d.line((cx + cell * .18, cy + cell * .3, cx, cy + cell * .45), fill=col + (255,), width=lw)
    return img


def bubble_block(quote, who, lang, box, t, gid, tail='left'):
    x0, y0, x1, y1 = box
    bw = x1 - x0
    body = text.block(quote, lang, 54 if lang == 'en' else 56, max_w=bw - 90, max_lines=5, min_size=34)
    sig = text.block('— ' + who, lang, 40, max_w=bw - 90, max_lines=1, color=palette.PALETTE['grey'],
                     min_size=28) if who else None
    iw = max(body.width, sig.width if sig else 0) + 80
    ih = body.height + (sig.height + 6 if sig else 0) + 60
    img = Image.new('RGBA', (int(iw) + 60, int(ih) + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ox = 50 if tail == 'left' else 4
    d.rounded_rectangle((ox, 4, ox + iw, 4 + ih), 40, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=4)
    ty = 4 + ih * .62
    if tail == 'left':
        d.polygon([(ox + 2, ty - 26), (2, ty + 20), (ox + 2, ty + 8)], fill=(255, 255, 255, 255))
        d.line([(ox + 1, ty - 26), (2, ty + 20), (ox + 1, ty + 8)], fill=(0, 0, 0, 255), width=4, joint='curve')
    img.alpha_composite(body, (int(ox + 40), 34))
    if sig:
        img.alpha_composite(sig, (int(ox + 40), 34 + body.height + 6))
    x, y = x0, y0 + ((y1 - y0) - img.height) / 2
    it = image_item('bubble', lambda v: img, x, y, t, group=gid)
    return [it], it.rect


def term_block(term, definition, lang, box, t, gid):
    x0, y0, x1, y1 = box
    bw = x1 - x0
    head = text.block(term, lang, 96, max_w=bw, max_lines=2, min_size=50)
    body = text.block(definition, lang, 50, max_w=bw, max_lines=3, color=palette.PALETTE['grey'], min_size=32) \
        if definition else None
    total = head.height + (body.height + 30 if body else 0)
    y = y0 + ((y1 - y0) - total) / 2
    hi = image_item('text', lambda v: head, x0 + (bw - head.width) / 2, y, t, group=gid)
    items = [hi]
    if body:
        items.append(image_item('label', lambda v: body, x0 + (bw - body.width) / 2, y + head.height + 30, t + .2,
                                group=gid))
    hx0, hy0, hx1, hy1 = hi.rect
    items.append(mark_item(marks.Mark('underline', (hx0 + 8, hy0, hx1 - 8, hy1 - head.height * .1), t + .35,
                                      seed=int(t * 100) + 1)))
    return items, hi.rect


def card_items(card, lang, box, gid, project_dir, tail='left'):
    d = card.data
    if card.kind == 'doodle':
        return doodle_block(d['doodle'], d.get('label', ''), lang, box, card.t, gid, project_dir)
    if card.kind == 'number':
        return number_block(d['value'], d.get('label', ''), lang, box, card.t, gid, d.get('people'))
    if card.kind == 'quote':
        return bubble_block(d['text'], d.get('who', ''), lang, box, card.t, gid, tail)
    if card.kind == 'term':
        return term_block(d['term'], d.get('text', ''), lang, box, card.t, gid)
    it = text_item(d.get('text', ''), lang, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, 72, card.t,
                   max_w=box[2] - box[0], max_lines=3, group=gid, anchor='middle', kind='text')
    return [it], it.rect


# ------------------------------------------------------------------ composer
class Composer:
    def __init__(self, board, tl, lang, project_dir=None, seed=0, envelope=None):
        self.board, self.tl, self.lang = board, tl, lang
        self.project_dir = project_dir
        self.seed = seed
        self.envelope = envelope                  # 15 fps speech activity (0..1) or None
        self.chapters = {c['id']: c for c in board['chapters']}
        self.beats = board['beats']
        self.bt = tl['beats']
        self.numbers = {}
        n = 0
        for c in board['chapters']:
            if c['kind'] == 'section':
                n += 1
                self.numbers[c['id']] = n
        texts = [self.T(board.get('title'))] + [b['display'][lang] for b in self.beats]
        self.ground = cues.ground(texts)
        self.era = cues.era(texts, lang)
        self.warnings = []
        self.last_layout = ''
        self.side = 1
        self.solo_toggle = 0
        self.hero = self._hero()

    # ---- helpers
    def T(self, pair, default=''):
        if pair is None:
            return default
        if isinstance(pair, str):
            return pair
        return pair.get(self.lang) or pair.get('en') or default

    def time_at(self, beat, display_pos):
        """When the narrator reaches display position ``display_pos`` of ``beat``."""
        info = self.bt[beat['id']]
        ct = info.get('char_times') or []
        if not ct:
            return info['start']
        norm = numbers.normalize(beat['display'][self.lang], self.lang)
        sp = norm.to_spoken(max(0, display_pos))
        return info['start'] + ct[min(sp, len(ct) - 1)]

    def time_of(self, beat, trigger, default=.15):
        if isinstance(trigger, dict) and trigger.get('beat'):
            beat = next(b for b in self.beats if b['id'] == trigger['beat'])
        info = self.bt[beat['id']]
        if trigger:
            phrase = trigger.get(self.lang) if isinstance(trigger, dict) else trigger
            if phrase:
                pos = beat['spoken'][self.lang].find(phrase)
                ct = info.get('char_times')
                if pos >= 0 and ct:
                    return info['start'] + ct[min(pos, len(ct) - 1)]
        return info['start'] + default

    def talking(self, t):
        if self.envelope is None:
            return False
        i = int(t * DRAW_FPS)
        return 0 <= i < len(self.envelope) and self.envelope[i] > .5 and (i // 2) % 2 == 0

    def _hero(self):
        count, first = {}, {}
        for b in self.beats:
            for v in b.get('visuals', []):
                if v.get('type') == 'cluster' and v.get('size') != 'margin':
                    for it in v.get('items', []):
                        did = it.get('doodle', '')
                        if did and not did.startswith('narrator'):
                            count[did] = count.get(did, 0) + 1
                            first.setdefault(did, len(first))
        return max(count, key=lambda d: (count[d], -first[d])) if count else None

    def accent(self, chapter_id):
        return palette.accent(self.numbers.get(chapter_id, 0))

    def gid(self, *parts):
        return ':'.join(map(str, parts))

    # ---- shots
    def shots(self) -> list[Shot]:
        out = []
        chapters = self.board['chapters']
        for ch in chapters:
            beats = [b for b in self.beats if b['chapter'] == ch['id']]
            if not beats:
                continue
            kind = ch['kind']
            if kind == 'intro':
                for b in beats:
                    out.append(self.title_shot(b))
                continue
            if kind == 'agenda':
                out.append(self.agenda_shot(beats))
                continue
            run = []
            for b in beats:
                if b['kind'] in ('narration',):
                    run.append(b)
                    continue
                if run:
                    out += self.narration_shots(ch, run)
                    run = []
                if b['kind'] == 'opener':
                    out.append(self.opener_shot(ch, b))
                elif b['kind'] == 'take':
                    out += self.take_shots(ch, b)
                elif b['kind'] == 'closing':
                    out.append(self.closing_shot(ch, b))
                else:
                    run.append(b)
            if run:
                out += self.narration_shots(ch, run)
        if not out or out[-1].layout != 'closing':
            a = out[-1].end if out else 0.
            out.append(self.closing_shot(None, None, a))
        out[-1].end = self.tl['duration']
        for a, b in zip(out, out[1:]):                 # contiguous, whatever rounding did
            a.end = b.start
        return out

    # ---- background pieces
    def tab(self, ch, t0):
        if ch is None or ch['kind'] in ('intro', 'agenda'):
            return []
        num = self.numbers.get(ch['id'])
        col = palette.rgb(self.accent(ch['id']))
        label = self.T(ch.get('title')) if num else self.T(ch.get('label'))
        img = tab_image(num, label, col, self.lang)
        return [image_item('tab', lambda v: img, 30, 28, t0, layer=0, pop=False)]

    def ground_item(self, t0):
        col = palette.rgb(self.ground)

        def draw(frame, t, k, variant):
            d = ImageDraw.Draw(frame)
            d.rectangle((0, GROUND_Y, W, H), fill=col + (255,))
            d.line((0, GROUND_Y, W, GROUND_Y), fill=(0, 0, 0, 255), width=3)
        return Item('ground', (0, GROUND_Y, W, H), t0, draw, layer=0, collide=False)

    def base(self, start, end, layout, ch, beats, ground=True, tab=True, words=''):
        shot = Shot(start, end, layout, ch['id'] if ch else '', tuple(b['id'] for b in beats),
                    self.ground if ground else None, words=words)
        if ground:
            shot.items.append(self.ground_item(start))
        if tab:
            shot.items += self.tab(ch, start)
        return shot

    # ---- title, agenda, opener, take, closing
    def title_shot(self, beat):
        info = self.bt[beat['id']]
        title = self.T(self.board.get('title'))
        shot = self.base(info['start'], info['end'], 'title', None, [beat], tab=False, words=title)
        t0 = info['start']
        shot.items.append(text_item(title, self.lang, W / 2, 150, 104, t0, max_w=1640, max_lines=2, kind='text',
                                    group='title'))
        question = bool(cues.QUESTION.search(title))
        hat = cues.costume(title, self.lang, self.era)
        fig = rig.Figure(pose='think' if question else 'wave', height=430, facing=1, hat=hat,
                         seed=rig.seed_of(self.seed, 'title'))
        fig, feet = fit_figure(fig, (300, 470, 860, GROUND_Y))
        fi = figure_item(fig, feet, t0)
        shot.items.append(fi)
        shot.pose = fig.pose
        if question:
            shot.items += self.head_marks(fig, feet, 'question', t0 + .6)
        if self.hero:
            items, rect = doodle_block(self.hero, '', self.lang, (1000, 460, 1600, 860), t0 + .3, 'hero',
                                       self.project_dir)
            shot.items += items
            shot.items.append(mark_item(marks.Mark('circle', rect, t0 + 1.2, seed=5)))
        return shot

    def agenda_rows(self, n):
        top, bottom = 210, 860
        row = min(140, (bottom - top) / max(1, n))
        y0 = top + ((bottom - top) - row * n) / 2
        return [(y0 + i * row, row) for i in range(n)]

    def agenda_list(self, shot, sections, times, done=None, nxt=None, t0=0.):
        rows = self.agenda_rows(len(sections))
        for i, ((y, row), ch, t) in enumerate(zip(rows, sections, times)):
            col = palette.rgb(self.accent(ch['id']))
            side = min(88, row - 24)
            grey = done is not None and i <= done
            sq = square_image(i + 1, side, palette.rgb('silver') if grey else col)
            shot.items.append(image_item('panel', lambda v, sq=sq: sq, 640, y + (row - side) / 2, t, group=f'row{i}'))
            ttl = text.block(self.T(ch.get('title')), self.lang, 60, max_w=1080, max_lines=1, min_size=34,
                             color=palette.rgb('grey') if grey else (0, 0, 0), align='left')
            ti = image_item('label', lambda v, ttl=ttl: ttl, 640 + side + 30, y + (row - ttl.height) / 2, t,
                            group=f'row{i}')
            shot.items.append(ti)
            if done is not None and i <= done:
                start = t0 + .25 if i == done else t0 - 1.
                shot.items.append(mark_item(marks.Mark('check', (640 + 6, y + (row - side) / 2 + 6, 640 + side - 6,
                                                                 y + (row + side) / 2 - 6), start, seed=i,
                                                       color=palette.rgb('green'), dur=.35)))
            if nxt is not None and i == nxt:
                x0, y0_, x1, y1 = ti.rect
                shot.items.append(mark_item(marks.Mark('circle', (640, y0_ + 8, x1 - 4, y1 - 8), t0 + 1.0, seed=i)))

    def agenda_shot(self, beats):
        a, b = self.bt[beats[0]['id']]['start'], self.bt[beats[-1]['id']]['end']
        ch = self.chapters[beats[0]['chapter']]
        shot = self.base(a, b, 'agenda', ch, beats, tab=False, words=' '.join(x['display'][self.lang] for x in beats))
        sections = [c for c in self.board['chapters'] if c['kind'] == 'section']
        times = [self.bt[beats[min(i, len(beats) - 1)]['id']]['start'] + (.9 if i == 0 else .15)
                 for i in range(len(sections))]
        fig = rig.Figure(pose='point', height=470, facing=1, seed=rig.seed_of(self.seed, 'agenda'))
        fig, feet = fit_figure(fig, (60, 260, 600, GROUND_Y))
        shot.items.append(figure_item(fig, feet, a))
        shot.pose = 'point'
        self.agenda_list(shot, sections, times)
        return shot

    def opener_shot(self, ch, beat):
        info = self.bt[beat['id']]
        t0, t1 = info['start'], info['end']
        shot = self.base(t0, t1, 'opener', ch, [beat], tab=False, words=self.T(ch.get('title')))
        num = self.numbers.get(ch['id'], 0)
        col = palette.rgb(self.accent(ch['id']))
        sq = square_image(num, 230, col)
        shot.items.append(image_item('panel', lambda v: sq, 190, 200, t0, group='head'))
        part = UI[self.lang]['part'].format(n=num)
        shot.items.append(text_item(part, self.lang, 470, 206, 46, t0, max_w=1300, max_lines=1, color=col,
                                    align='left', upper=True, group='head'))
        ttl = text.block(self.T(ch.get('title')), self.lang, 104, max_w=1300, max_lines=2, min_size=56, align='left')
        shot.items.append(image_item('text', lambda v: ttl, 470, 268, t0, group='head'))
        dur = t1 - t0
        walk = min(1500., 430. * dur)
        hat = cues.costume(self.T(ch.get('title')), self.lang, self.era)
        fig = rig.Figure(pose='walk', height=320, facing=1, shirt=self.accent(ch['id']), hat=hat,
                         seed=rig.seed_of(self.seed, ch['id']))
        fig, feet = fit_figure(fig, (80, 560, 1840, GROUND_Y), travel=walk)
        shot.items.append(figure_item(fig, feet, t0, walk=(walk, t0, t0 + dur * .92)))
        shot.pose = 'walk'
        return shot

    def take_shots(self, ch, beat):
        info = self.bt[beat['id']]
        prep = info.get('prep', info['start'])
        tr = next((x for x in self.tl['transitions'] if x['take_beat'] == beat['id']), None)
        hold_end = tr['hold_end'] if tr else info['end']
        shot = self.base(prep, hold_end, 'take', ch, [beat], words=beat['display'][self.lang])
        col = palette.rgb(self.accent(ch['id']))
        shot.items.append(text_item(UI[self.lang]['take'], self.lang, 1110, 175, 48, prep, max_w=1200, max_lines=1,
                                    color=col, upper=True, group='take'))
        head = ((beat.get('take') or {}).get('headline') or {}).get(self.lang) or beat['display'][self.lang]
        spoken = beat['display'][self.lang]
        prefix = script.take_text('', self.lang)
        t_head = self.time_at(beat, len(prefix)) if spoken.startswith(prefix) else info['start']
        img = text.block(head, self.lang, 80, max_w=1240, max_lines=3, min_size=44)
        hi = image_item('text', lambda v: img, 1110 - img.width / 2, 250 + (420 - img.height) / 2, t_head,
                        group='take')
        shot.items.append(hi)
        x0, y0, x1, y1 = hi.rect
        shot.items.append(mark_item(marks.Mark('underline', (x0 + 10, y0, x1 - 10, y1 - 14), t_head + 1.2, seed=9,
                                               dur=.6)))
        fig = rig.Figure(pose='point', height=560, facing=1, shirt=self.accent(ch['id']),
                         hat=cues.costume(head, self.lang, self.era), seed=rig.seed_of(self.seed, ch['id'], 'take'))
        fig, feet = fit_figure(fig, (50, 300, 480, GROUND_Y))
        shot.items.append(figure_item(fig, feet, prep, talk=self.talking))
        shot.pose = 'point'
        shots = [shot]
        if tr:
            prog = self.base(hold_end, tr['end'], 'progress', ch, [beat], tab=False)
            sections = [c for c in self.board['chapters'] if c['kind'] == 'section']
            idx = next(i for i, c in enumerate(sections) if c['id'] == ch['id'])
            nxt = idx + 1 if idx + 1 < len(sections) else None
            self.agenda_list(prog, sections, [hold_end] * len(sections), done=idx, nxt=nxt, t0=hold_end)
            f2 = rig.Figure(pose='cheer', height=470, facing=1, seed=rig.seed_of(self.seed, 'progress'))
            f2, feet2 = fit_figure(f2, (60, 260, 600, GROUND_Y))
            prog.items.append(figure_item(f2, feet2, hold_end))
            prog.pose = 'cheer'
            shots.append(prog)
        return shots

    def closing_shot(self, ch, beat, start=None):
        t0 = self.bt[beat['id']]['start'] if beat else start
        shot = self.base(t0, self.tl['duration'], 'closing', ch, [beat] if beat else [], tab=False,
                         words=UI[self.lang]['thanks'])
        fig = rig.Figure(pose='wave', height=470, facing=1, seed=rig.seed_of(self.seed, 'closing'))
        fig, feet = fit_figure(fig, (260, 330, 760, GROUND_Y))
        shot.items.append(figure_item(fig, feet, t0))
        shot.pose = 'wave'
        thanks = beat['display'][self.lang] if beat else UI[self.lang]['thanks']
        ti = text_item(thanks, self.lang, 1290, 250, 100, t0, max_w=1100, max_lines=2, kind='text', group='end')
        shot.items.append(ti)
        end = self.tl.get('end_card') or {}
        if end:
            shot.items.append(text_item(self.T(self.board.get('title')), self.lang, 1290, ti.rect[3] + 50, 58,
                                        end['start'], max_w=1000, max_lines=2, color=palette.rgb('grey'),
                                        group='end2'))
        credit = self.tl.get('credit')
        if credit:
            from ... import PRODUCT
            line = {'en': 'Made with {name}', 'zh': '由 {name} 制作'}[self.lang].format(**PRODUCT)
            shot.items.append(text_item(line, self.lang, 1290, 690, 40, credit['start'], max_w=1000, max_lines=1,
                                        color=palette.rgb('grey'), group='credit'))
            shot.items.append(text_item(PRODUCT['url'], 'en', 1290, 750, 30, credit['start'] + .3, max_w=1000,
                                        max_lines=1, color=palette.rgb('grey'), group='credit'))
        return shot

    # ---- narration
    def sentence_times(self, beat):
        disp = beat['display'][self.lang]
        out, cursor = [], 0
        for s in script.sentences(disp, self.lang) or [disp]:
            pos = disp.find(s, cursor)
            if pos < 0:
                pos = cursor
            cursor = pos + len(s)
            out.append((self.time_at(beat, pos), pos, s))
        info = self.bt[beat['id']]
        if out:
            out[0] = (info['start'], out[0][1], out[0][2])
        return out

    def cards_of(self, beat):
        """[(time, Card | hint)] for a beat's visuals."""
        lang, disp = self.lang, beat['display'][self.lang]
        out = []
        for k, v in enumerate(beat.get('visuals', [])):
            vt, vid = v.get('type'), v.get('id') or f"{beat['id']}#{k}"
            t = self.time_of(beat, v.get('trigger'))
            if v.get('size') == 'margin':
                continue
            if vt == 'cluster':
                items = v.get('items', [])
                real = [it for it in items if not it.get('doodle', '').startswith('narrator')]
                for it in items:
                    did = it.get('doodle', '')
                    if did.startswith('narrator'):
                        pose = cues.NARRATOR_POSES.get(did.split('_', 1)[-1])
                        tt = self.time_of(beat, it.get('trigger')) if it.get('trigger') else t
                        out.append((tt, Card('hint', tt, {'pose': pose}, vid)))
                if len(real) >= 3:
                    data = {'items': [{'doodle': it['doodle'], 'label': _clean_label(self.T(it.get('label')), disp, lang)}
                                      for it in real]}
                    out.append((t, Card('grid', t, data, vid)))
                    continue
                for j, it in enumerate(real):
                    tt = self.time_of(beat, it.get('trigger')) if it.get('trigger') else t
                    data = {'doodle': it['doodle'], 'label': _clean_label(self.T(it.get('label')), disp, lang)}
                    if j == 1 and v.get('relation', 'none') != 'none':
                        data['relation'] = v['relation']
                    out.append((tt, Card('doodle', tt, data, vid)))
            elif vt == 'stat':
                label = _clean_label(self.T(v.get('label')), sentence_with(self.T(v.get('value')), disp, lang), lang)
                out.append((t, Card('number', t, {'value': number_text(self.T(v.get('value')), disp),
                                                  'label': label}, vid)))
            elif vt == 'grid100':
                filled = int(v.get('filled', 0))
                out.append((t, Card('number', t, {'value': f'{filled}%', 'label': self.T(v.get('title')),
                                                  'people': filled}, vid)))
            elif vt == 'quote':
                out.append((t, Card('quote', t, {'text': self.T(v.get('text')), 'who': self.T(v.get('who'))}, vid)))
            elif vt == 'glossary':
                term = _name_only(_clean_label(self.T(v.get('term')), disp, lang) or self.T(v.get('term')), lang)
                gloss = self.T(v.get('text'))
                if POINTER.match(gloss):                  # "this phenomenon" defines nothing
                    gloss = ''
                out.append((t, Card('term', t, {'term': term, 'text': gloss}, vid)))
            elif vt == 'lanes':
                evs = []
                for lane in v.get('lanes', []):
                    for ev in lane.get('events', []):
                        te = self.time_of(beat, ev.get('trigger')) if ev.get('trigger') else t
                        evs.append({'t': te, 'pos': float(ev.get('pos', 0)), 'year': self.T(ev.get('display')),
                                    'label': self.T(ev.get('label'))})
                out.append((t, Card('timeline', t, {'events': evs}, vid)))
            elif vt == 'emphasis':
                out.append((t, Card('emphasis', t, {'target': str(v.get('target', '')), 'kind': v.get('kind')}, vid)))
            elif vt == 'stock':
                continue
            else:
                title = self.T(v.get('title')) or self.T(v.get('text'))
                if title:
                    out.append((t, Card('title', t, {'text': title}, vid)))
                self.warnings.append(f"{beat['id']}: {vt} drawn as a title card in the stick look")
        return out

    def narration_shots(self, ch, beats):
        lang = self.lang
        a, b = self.bt[beats[0]['id']]['start'], self.bt[beats[-1]['id']]['end']
        cuts = []                                             # (time, beat, display pos)
        for beat in beats:
            for t, pos, _ in self.sentence_times(beat):
                cuts.append((t, beat, pos))
        cards = []
        for beat in beats:
            cards += self.cards_of(beat)
        cards.sort(key=lambda tc: tc[0])
        holds = []
        for t, c in cards:
            if c.kind == 'timeline' and c.data['events']:
                last = max(e['t'] for e in c.data['events'])
                holds.append((min(t, min(e['t'] for e in c.data['events'])) - .05, min(b, last + 2.5)))
        bounds = sorted({round(t, 3) for t, _, _ in cuts if not any(h0 < t < h1 for h0, h1 in holds)}
                        | {round(max(a, h0), 3) for h0, _ in holds} | {round(h1, 3) for _, h1 in holds if h1 < b})
        bounds = [x for x in bounds if a <= x < b] or [a]
        if bounds[0] > a:
            bounds[0] = a
        segs = [[x, y] for x, y in zip(bounds, bounds[1:] + [b])]
        merged = []                                           # every shot at least MIN_SHOT long
        for s in segs:
            if merged and (s[1] - s[0] < MIN_SHOT or merged[-1][1] - merged[-1][0] < MIN_SHOT) \
                    and not any(h0 - .1 <= s[0] < h1 for h0, h1 in holds) \
                    and not any(h0 - .1 <= merged[-1][0] < h1 for h0, h1 in holds):
                merged[-1][1] = s[1]
            else:
                merged.append(s)
        segs = merged

        def in_seg(t, s):
            return s[0] <= t < s[1] or (s is segs[-1] and t >= s[1]) or (s is segs[0] and t < s[0])
        groups = [[c for t, c in cards if in_seg(t, s)] for s in segs]
        # cut a long shot again at its second card (or in two when it has none to cut at)
        out_segs, out_groups = [], []
        for s, g in zip(segs, groups):
            pending = [(s, g)]
            while pending:
                s1, g1 = pending.pop(0)
                main = [c for c in g1 if c.kind in ('doodle', 'number', 'quote', 'term', 'title', 'grid')]
                cut = None
                if s1[1] - s1[0] > MAX_SHOT or len(main) > 2:
                    for c in main[1:]:
                        if c.t - s1[0] >= 2.0 and s1[1] - c.t >= 2.0:
                            cut = c.t
                            break
                    if cut is None and not main and s1[1] - s1[0] > MAX_SHOT * 1.25:
                        cut = (s1[0] + s1[1]) / 2
                if cut is None:
                    out_segs.append(s1)
                    out_groups.append(g1)
                    continue
                left = [c for c in g1 if c.t < cut]
                right = [c for c in g1 if c.t >= cut]
                pending[:0] = [([s1[0], cut], left), ([cut, s1[1]], right)]
        shots = []
        for s, g in zip(out_segs, out_groups):
            sb = [bt for bt in beats if self.bt[bt['id']]['start'] < s[1] and self.bt[bt['id']]['end'] > s[0]]
            words = ' '.join(sent for bt in sb for tt, pos, sent in self.sentence_times(bt)
                             if s[0] - .3 <= tt < s[1] - .3) or ' '.join(bt['display'][lang] for bt in sb)
            shots.append(self.narration_shot(ch, sb, s[0], s[1], g, words))
        return shots

    def narration_shot(self, ch, beats, a, b, cards, words):
        lang = self.lang
        pose, cue_pos = cues.pose_for(words, lang)
        hints = [c.data['pose'] for c in cards if c.kind == 'hint' and c.data.get('pose')]
        if hints:
            pose = hints[0]
        timeline = next((c for c in cards if c.kind == 'timeline'), None)
        grid = next((c for c in cards if c.kind == 'grid'), None)
        main = [c for c in cards if c.kind in ('doodle', 'number', 'quote', 'term', 'title')][:2]
        emph = [c for c in cards if c.kind == 'emphasis']
        crowd = cues.crowd(words, lang)
        if not (main or timeline or grid or crowd):
            num = self.spoken_number(beats, a, b)
            main = [num] if num else []
        doodles = [c for c in main if c.kind == 'doodle']
        if timeline:
            layout = 'timeline'
        elif grid:
            layout = 'grid'
        elif not main:
            if crowd:
                layout = 'crowd'
            elif pose in ('walk', 'run', 'fall'):
                layout = 'solo'
            else:
                layout = 'close' if self.last_layout == 'solo' else 'solo'
                if self.last_layout not in ('solo', 'close'):
                    layout = 'close' if self.solo_toggle % 2 else 'solo'
                    self.solo_toggle += 1
        elif crowd and len(main) == 1:
            layout = 'crowd'
        elif len(main) == 1 and main[0].kind in ('number', 'quote', 'term', 'title') and self.last_layout != 'close' \
                and pose not in ('walk', 'run', 'fall'):
            layout = 'close'
        else:
            self.side = -self.side
            layout = 'left' if self.side > 0 else 'right'
        if layout == self.last_layout and layout in ('crowd', 'close') and main:
            self.side = -self.side
            layout = 'left' if self.side > 0 else 'right'
        if layout == self.last_layout == 'solo':
            layout = 'close'
        self.last_layout = layout
        shot = self.base(a, b, layout, ch, beats, words=words)
        if pose is None:
            pose = 'point' if doodles else ('talk' if layout in ('close', 'solo') else 'stand')
        if pose == 'hold' and len(doodles) != 1:
            pose = 'point' if doodles else 'talk'
        if layout in ('close',) and pose in ('walk', 'run', 'sit', 'fall', 'hold'):
            pose = 'talk'
        if layout == 'grid' and pose not in ('point', 'think', 'talk'):
            pose = 'point'
        hat = cues.costume(words, lang, self.era)
        shirt = self.accent(ch['id']) if ch and ch['kind'] == 'section' else None
        shocked = cues.shock(words, lang)
        face = None
        if shocked >= 0 and pose in ('stand', 'talk', 'point', 'hold', 'walk'):
            face = ('wide', 'raised', 'o')
        seed = rig.seed_of(self.seed, ch['id'] if ch else '', round(a, 2))
        shot.pose = pose
        t_shock = a + .5
        if shocked >= 0:
            beat = next((bt for bt in beats if bt['display'][lang].find(words[shocked:shocked + 6]) >= 0), None)
            if beat:
                t_shock = max(a + .2, min(b - .6, self.time_at(beat, beat['display'][lang].find(words[shocked:shocked + 6]))))
        builder = getattr(self, f'lay_{layout}')
        builder(shot, ch, main, grid, timeline, pose, face, hat, shirt, seed, crowd, words)
        # marks
        fig = next((i for i in shot.items if i.kind == 'figure'), None)
        if fig is not None and layout != 'timeline' and pose != 'fall':
            head = getattr(fig, 'head', None)
            if head:
                if pose == 'think':
                    shot.items += self.marks_at(head, 'question', a + .35, seed)
                elif shocked >= 0:
                    shot.items += self.marks_at(head, 'exclaim', t_shock, seed)
        strong = cues.strong(words, lang)
        targets = getattr(shot, 'targets', {})
        if strong >= 0 and doodles and doodles[0].vid in targets and not any(c.kind == 'emphasis' for c in emph):
            r = targets[doodles[0].vid]
            shot.items.append(mark_item(marks.Mark('circle', r, max(doodles[0].t + .45, a + .4), seed=seed % 97)))
        for c in emph:
            vid = c.data['target'].split('.')[0]
            if vid in targets:
                kind = {'circle': 'circle', 'underline': 'underline', 'highlight': 'underline',
                        'strike': 'cross'}.get(c.data.get('kind'), 'circle')
                shot.items.append(mark_item(marks.Mark(kind, targets[vid], max(c.t, a + .3), seed=seed % 89)))
        return shot

    def spoken_number(self, beats, a, b):
        """A number the narrator says in [a, b) as a big plain-text card (a year, a count, a percentage), so a
        shot with nothing else to show still shows the fact. Needs two digits or more."""
        for beat in beats:
            disp = beat['display'][self.lang]
            for m in NUMBER[self.lang].finditer(disp):
                t = self.time_at(beat, m.start())
                if not (a - .3 <= t < b - 1.):
                    continue
                value = number_text(m.group(1), disp) + (m.group(2) or '')
                label = ''
                if self.lang == 'en':
                    nxt = re.match(r'\s+([A-Za-z]{3,})\b', disp[m.end():])
                    if nxt and nxt.group(1).lower() not in NOT_LABELS:
                        label = nxt.group(1)
                return Card('number', max(t, a + .2), {'value': value, 'label': label},
                            f"{beat['id']}@n{m.start()}")
        return None

    # ---- marks next to a head
    def marks_at(self, head, kind, t, seed):
        hx, hy, hr = head
        size = max(70, min(130, hr * 1.1))
        out = []
        side = 1 if hx < W / 2 else -1
        for j, (dx, dy, s) in enumerate(((1.45, -1.0, 1.), (2.15, -.35, .7))):
            cx, cy = hx + side * dx * hr, hy + dy * hr
            sz = size * s
            box = (cx - sz * .35, cy - sz / 2, cx + sz * .35, cy + sz / 2)
            out.append(mark_item(marks.Mark(kind, box, t + .12 * j, seed=seed + j)))
        return out

    def head_marks(self, fig, feet, kind, t):
        dr = rig.draw(fig, 0, 0)
        hx, hy, hr = dr.head
        head = (feet[0] - dr.origin[0] + hx, feet[1] - dr.origin[1] + hy, hr)
        return self.marks_at(head, kind, t, 3)

    def _figure(self, shot, fig, lane, t0, travel=0., talk=False, walk=None, crop=None):
        fig, feet = fit_figure(fig, lane, travel) if crop is None else (fig, lane)
        it = figure_item(fig, feet, t0, talk=self.talking if talk else None, walk=walk, crop=crop)
        dr = rig.draw(fig, 0, 0, crop)
        hx, hy, hr = dr.head
        it.head = (feet[0] - dr.origin[0] + hx, feet[1] - dr.origin[1] + hy, hr)
        if walk:
            it.head = (it.head[0] + walk[0], it.head[1], hr)
        it.fig, it.feet = fig, feet
        shot.items.append(it)
        return it

    def _held(self, shot, it, card):
        """A holding figure carries the shot's picture in its hands (drawn over them), instead of on the stage."""
        fig, feet = it.fig, it.feet
        dr = rig.draw(fig, 0, 0)
        hx, hy = dr.hands[0]
        x, y = feet[0] - dr.origin[0] + hx, feet[1] - dr.origin[1] + hy
        side = int(fig.height * .3)
        did = card.data['doodle']
        first = paint.doodle(did, (side, side), 0, self.project_dir)
        px = x - first.width / 2 + fig.facing * first.width * .15
        py = y - first.height * .7
        prop = image_item('doodle', lambda v: paint.doodle(did, (side, side), v, self.project_dir), px, py,
                          shot.start, group=it.group, boil=True, layer=3, pop=False)
        shot.items.append(prop)
        shot.targets = getattr(shot, 'targets', {})
        shot.targets[card.vid] = prop.rect

    def _cards(self, shot, cards, region, tail='left'):
        """Place up to two cards side by side in ``region``; a relation glyph or arrow between two doodles."""
        x0, y0, x1, y1 = region
        shot.targets = getattr(shot, 'targets', {})
        n = len(cards)
        if not n:
            return
        gap = 140 if n == 2 else 0
        cw = (x1 - x0 - gap * (n - 1)) / n
        rects = []
        for i, c in enumerate(cards):
            box = (x0 + i * (cw + gap), y0, x0 + i * (cw + gap) + cw, y1)
            items, rect = card_items(c, self.lang, box, f'card{i}', self.project_dir, tail)
            shot.items += items
            shot.targets[c.vid] = rect
            rects.append(rect)
        if n == 2 and cards[1].data.get('relation'):
            rel = cards[1].data['relation']
            gx = x0 + cw + gap / 2
            gy = (max(rects[0][1], rects[1][1]) + min(rects[0][3], rects[1][3])) / 2
            if rel == 'arrow':
                shot.items.append(mark_item(marks.Mark('arrow', (gx - 55, gy, gx + 55, gy), cards[1].t + .1, seed=2)))
            else:
                glyph = {'plus': '+', 'vs': 'VS', 'equals': '='}.get(rel, '+')
                shot.items.append(text_item(glyph, 'en', gx, gy, 90 if glyph != 'VS' else 64, cards[1].t,
                                            color=palette.RED if glyph == 'VS' else (0, 0, 0), max_w=gap - 10,
                                            max_lines=1, anchor='middle', kind='label', group='rel'))

    # ---- layouts
    def lay_left(self, shot, ch, cards, grid, timeline, pose, face, hat, shirt, seed, crowd, words, side=1):
        lane = (90, 170, 640, GROUND_Y) if side > 0 else (W - 640, 170, W - 90, GROUND_Y)
        region = (720, 170, 1830, 860) if side > 0 else (90, 170, W - 720, 860)
        fig = rig.Figure(pose=pose, height=FIG_H, facing=side, face=face, hat=hat, shirt=shirt, seed=seed,
                         look=(1., 0.))
        walk = None
        if pose in ('walk', 'run'):
            walk = (side * 220., shot.start, shot.start + .9)
            lane = (lane[0] + (0 if side > 0 else 220), lane[1], lane[2] - (220 if side > 0 else 0), lane[3])
        it = self._figure(shot, fig, lane, shot.start, walk=walk,
                          talk=pose in ('talk', 'point') and (face is None or face[2] not in ('o',)))
        held = next((c for c in cards if c.kind == 'doodle'), None) if pose == 'hold' else None
        if held:
            self._held(shot, it, held)
            cards = [c for c in cards if c is not held]
        self._cards(shot, cards, region, tail='left' if side > 0 else 'right')
        return it

    def lay_right(self, *args):
        return self.lay_left(*args, side=-1)

    def lay_solo(self, shot, ch, cards, grid, timeline, pose, face, hat, shirt, seed, crowd, words):
        fig = rig.Figure(pose=pose, height=FIG_H + 40, facing=1 if (seed % 2) else -1, face=face, hat=hat,
                         shirt=shirt, seed=seed)
        if pose in ('walk', 'run'):
            dur = shot.end - shot.start
            speed = 380. if pose == 'walk' else 720.
            travel = min(1300., speed * dur)
            f = fig.facing
            lane = (120, 170, W - 120, GROUND_Y)
            fig, feet = fit_figure(fig, lane, travel)
            if f < 0:
                feet = (feet[0] + travel, feet[1])
            it = figure_item(fig, feet, shot.start, walk=(travel * f, shot.start, shot.end + 5.))
            dr = rig.draw(fig, 0, 0)
            it.head = (feet[0] - dr.origin[0] + dr.head[0], feet[1] - dr.origin[1] + dr.head[1], dr.head[2])
            shot.items.append(it)
            return it
        return self._figure(shot, fig, (560, 170, 1360, GROUND_Y), shot.start, talk=pose in ('talk',))

    def lay_close(self, shot, ch, cards, grid, timeline, pose, face, hat, shirt, seed, crowd, words):
        Hc = 1150.
        feet_y = 560. + .865 * Hc
        crop = ((feet_y - GROUND_Y) / Hc, 1.4)          # the body ends at the ground strip, clear of the captions
        if pose not in ('think', 'shrug', 'point', 'talk', 'angry', 'sad', 'cheer', 'wave', 'stand'):
            pose = 'talk'
        if cards:
            fig = rig.Figure(pose=pose, height=Hc, facing=1, face=face, hat=hat, shirt=shirt, seed=seed, look=(1., 0.))
            feet = (470., feet_y)
            it = self._figure(shot, fig, feet, shot.start, crop=crop,
                              talk=pose in ('talk', 'point') and (face is None or face[2] != 'o'))
            it.rect = (it.rect[0], it.rect[1], it.rect[2], min(it.rect[3], GROUND_Y))
            self._cards(shot, cards, (900, 180, 1830, 900), tail='left')
            return it
        fig = rig.Figure(pose=pose, height=Hc, facing=1 if seed % 2 else -1, face=face, hat=hat, shirt=shirt,
                         seed=seed)
        feet = (W / 2, feet_y)
        it = self._figure(shot, fig, feet, shot.start, crop=crop, talk=pose in ('talk', 'point'))
        it.rect = (it.rect[0], it.rect[1], it.rect[2], min(it.rect[3], GROUND_Y))
        return it

    def lay_crowd(self, shot, ch, cards, grid, timeline, pose, face, hat, shirt, seed, crowd, words):
        mood = cues.MOOD.get(pose, 'calm')
        n = 3 + seed % 5
        top = 520 if cards else 260
        c = rig.Crowd(n=n, height=GROUND_Y - top - 40, mood=mood, facing=1, hat=hat, seed=seed)
        c, feet = fit_crowd(c, (140, top, W - 140, GROUND_Y))
        shot.items.append(crowd_item(c, feet, shot.start))
        if cards:
            self._cards(shot, cards[:1], (360, 150, W - 360, 500))
        return None

    def lay_grid(self, shot, ch, cards, grid, timeline, pose, face, hat, shirt, seed, crowd, words):
        fig = rig.Figure(pose=pose, height=420, facing=1, face=face, hat=hat, shirt=shirt, seed=seed, look=(1., 0.))
        it = self._figure(shot, fig, (50, 400, 330, GROUND_Y), shot.start, talk=pose in ('talk', 'point'))
        items = grid.data['items'][:4]
        n = len(items)
        x0, x1 = 380, 1850
        gap = 36
        pw = min(420, (x1 - x0 - gap * (n - 1)) / n)
        ph = pw * .82
        left = x0 + ((x1 - x0) - (pw * n + gap * (n - 1))) / 2
        top = 250
        shot.targets = {}
        for i, entry in enumerate(items):
            t = grid.t + .45 * i
            px = left + i * (pw + gap)
            frame = panel_image(int(pw), int(ph))
            shot.items.append(image_item('panel', lambda v, f=frame: f, px, top, t, group=f'p{i}'))
            img = paint.doodle(entry['doodle'], (int(pw - 40), int(ph - 40)), 0, self.project_dir)
            shot.items.append(image_item(
                'doodle', lambda v, e=entry: paint.doodle(e['doodle'], (int(pw - 40), int(ph - 40)), v,
                                                          self.project_dir),
                px + (pw - img.width) / 2, top + (ph - img.height) / 2, t, group=f'p{i}', boil=True))
            if entry.get('label'):
                shot.items.append(text_item(entry['label'], self.lang, px + pw / 2, top + ph + 14, 44, t,
                                            max_w=pw, max_lines=2, group=f'p{i}'))
        shot.targets[grid.vid] = (left, top, left + n * pw + (n - 1) * gap, top + ph)
        return it

    def lay_timeline(self, shot, ch, cards, grid, timeline, pose, face, hat, shirt, seed, crowd, words):
        fig = rig.Figure(pose='point', height=420, facing=1, hat=hat, shirt=shirt, seed=seed, look=(1., 0.))
        self._figure(shot, fig, (40, 400, 360, GROUND_Y), shot.start)
        evs = sorted(timeline.data['events'], key=lambda e: e['pos'])
        ax0, ax1, ay = 430, 1850, 560
        line = marks.arrow_lines(ax0, ay, ax1, ay, bend=0, head=30)

        def draw_axis(frame, t, k, variant):
            d = ImageDraw.Draw(frame)
            for pts in line:
                d.line([tuple(p) for p in pts], fill=(0, 0, 0, 255), width=5)
        shot.items.append(Item('panel', (ax0, ay - 18, ax1, ay + 18), shot.start, draw_axis, group='axis'))
        n = len(evs)
        span = ax1 - 80 - (ax0 + 60)
        xs = [ax0 + 60 + span * (i / max(1, n - 1)) for i in range(n)]
        slot = span / max(1, n - 1) if n > 1 else 600
        for i, (e, x) in enumerate(zip(evs, xs)):
            t = max(shot.start, e['t'])

            def tick(frame, tt, k, variant, x=x):
                ImageDraw.Draw(frame).line((x, ay - 22, x, ay + 22), fill=(0, 0, 0, 255), width=5)
            shot.items.append(Item('panel', (x - 4, ay - 22, x + 4, ay + 22), t, tick, group=f'e{i}'))
            yr = text_item(e['year'], self.lang, x, ay - 36, 64, t, max_w=slot - 10, max_lines=1, anchor='bottom',
                           kind='number', group=f'e{i}')
            shot.items.append(yr)
            if e.get('label'):
                shot.items.append(text_item(e['label'], self.lang, x, ay + 40, 36, t, max_w=min(330, slot - 16),
                                            max_lines=3, group=f'e{i}'))
            shot.items.append(mark_item(marks.Mark('circle', yr.rect, t + .25, seed=i), t1=evs[i + 1]['t']
                                        if i + 1 < n and evs[i + 1]['t'] > t else math.inf))
        return None


# ------------------------------------------------------------------ small images
def tab_image(num, label, color, lang):
    """Header tab: the part's number in its accent square, then its title (a chapter without a number: the
    title alone)."""
    side = 64
    lab = text.block(label, lang, 36, max_w=1100, max_lines=1, min_size=24, upper=True, align='left')
    sq_w = side + 14 if num else 0
    img = Image.new('RGBA', (int(sq_w + lab.width), side), (0, 0, 0, 0))
    if num:
        img.alpha_composite(square_image(num, side, color), (0, 0))
    img.alpha_composite(lab, (sq_w, (side - lab.height) // 2))
    return img


def square_image(num, side, color):
    side = int(side)
    img = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((1, 1, side - 2, side - 2), fill=tuple(color) + (255,), outline=(0, 0, 0, 255), width=max(3, side // 28))
    if num:
        t = text.block(str(num), 'en', int(side * .72), color=(255, 255, 255), outline=max(2, side // 30),
                       outline_color=(0, 0, 0), line_gap=1.)
        img.alpha_composite(t, ((side - t.width) // 2, (side - t.height) // 2 - side // 40))
    return img


def panel_image(w, h):
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((2, 2, w - 3, h - 3), fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=4)
    return img


def overlaps(shot: Shot, tolerance: float = 4.) -> list:
    """Pairs of colliding items from different groups (labels, cards, figures, tabs) in a shot."""
    items = [i for i in shot.items if i.collide and i.kind not in ('ground', 'mark')]
    bad = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.group and a.group == b.group:
                continue
            ax0, ay0, ax1, ay1 = a.rect
            bx0, by0, bx1, by1 = b.rect
            if min(ax1, bx1) - max(ax0, bx0) > tolerance and min(ay1, by1) - max(ay0, by0) > tolerance:
                bad.append((a.kind, a.group, b.kind, b.group))
    return bad

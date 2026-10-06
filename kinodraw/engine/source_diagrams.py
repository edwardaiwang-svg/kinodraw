"""Closed, source-bound diagrams. No provider payload can supply geometry or facts.

English equal-group imperatives / equations and named organizing cards only. The
resolver uses preceding beats in the same section; unknown or inconsistent claims
fail closed. Drawings and motion are evaluated from the saved source clock.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw

from . import ink

_WORDS = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen '
          'sixteen seventeen eighteen nineteen twenty').split()
NUMBERS = {w: i for i, w in enumerate(_WORDS)}
for tens, n in (('thirty', 30), ('forty', 40), ('fifty', 50), ('sixty', 60)):
    NUMBERS[tens] = n
for tens, n in list(NUMBERS.items()):
    if n >= 20:
        for unit in range(1, 10):
            NUMBERS[f'{tens}-{_WORDS[unit]}'] = n + unit
NUMBER = r'(?:\d{1,3}|' + '|'.join(sorted(NUMBERS, key=len, reverse=True)) + r')'
ARRAY = re.compile(r'\b(?:place|draw|build|arrange)\s+(' + NUMBER + r')\s+rows?\s+of\s+(' + NUMBER + r')\s+dots?\b', re.I)
ROTATE_CUE = re.compile(r'\brotate\s+(?:the\s+)?same\s+dots\b', re.I)
# These words are boundaries, not an expanded number parser.
NUMBER_PARTS = ('|'.join(sorted(NUMBERS, key=len, reverse=True))
                + r'|seventy|eighty|ninety|hundred|thousand|[a-z]+illion'
                  r'|point|half|halves|quarter|quarters|percent|dozen|score'
                  r'|minus|negative|plus|positive')
NUMBER_PREFIX = re.compile(r'\b(?:' + NUMBER_PARTS + r'|\d+)(?:\s+and)?\s+$', re.I)
# A number token must be the whole value on both sides.
NUMBER_END = (r'(?![\w/%+-]|[.,]\d|\s*(?:/|%|\.)\s*\d|\s+\d|\s+(?:'
              + NUMBER_PARTS + r'|and)\b)')
NUMBER_SUFFIX = re.compile(NUMBER_END, re.I)
ROTATE = re.compile(r'\brotate\s+(?:the\s+)?same\s+dots\s+to\s+make\s+(' + NUMBER + r')\s+rows?\s+of\s+(' + NUMBER + r')' + NUMBER_END, re.I)
EQUATION_CUE = re.compile(r'\b(?:times|multiplied by|equals)\b|[×=]', re.I)
EQUATION = re.compile(r'\b(' + NUMBER + r')\s+(?:times|multiplied by|×)\s+(' + NUMBER + r')\s+(?:equals|=)\s+(' + NUMBER + r')' + NUMBER_END, re.I)
COUNT = re.compile(r'\bcount(?:ing)?\s+(?:(?:the\s+)?(?:same\s+)?dots\b[^.!?]*|again\b[^.!?]*)', re.I)
PANELS = re.compile(r'\b(?:panels|cards)\s+(?:glide|slide)\b[^.!?]*?\b(?:organize|arrange)\s+([^.!?]+)', re.I)
LABELS = {'notes', 'tasks', 'drawings', 'files', 'sketches', 'ideas', 'calendars'}
UNCERTAIN = re.compile(r"\b(?:not|never|maybe|perhaps|might|instead|without)\b|n't\b", re.I)


@dataclass(frozen=True)
class Diagram:
    kind: str
    ref: str
    base: str
    rows: int = 0
    cols: int = 0
    equation: str = ''
    build: tuple | None = None
    write: tuple | None = None
    rotate: tuple | None = None
    counts: tuple = ()
    labels: tuple = ()
    glide: tuple | None = None

    @property
    def total(self):
        return self.rows * self.cols


def _number(word):
    return int(word) if word.isdigit() else NUMBERS[word.lower()]


def _whole_values(match):
    text = match.string
    for group in range(1, len(match.groups()) + 1):
        start, end = match.span(group)
        if (start and text[start-1] in '/.,%+-') or NUMBER_PREFIX.search(text[:start]):
            return False
        if NUMBER_SUFFIX.match(text, end) is None:
            return False
    return True


def _valid(rows, cols):
    return 1 <= rows <= 10 and 1 <= cols <= 10 and rows * cols <= 64


def _beats(board):
    # Keep this leaf module independent of v3 schema/import cycles.
    lang = board.get('lang', 'en') if isinstance(board, dict) else 'en'
    items = board['beats'] if isinstance(board, dict) else board
    def text(value):
        return value.get(lang, '') if isinstance(value, dict) else value
    return [(b.get('id', b.get('beat_id')), b.get('section', b.get('section_id', b.get('chapter', 'main'))),
             text(b.get('spoken', b.get('text', b.get('display', ''))))) for b in items]


def resolve(board, ref):
    """Resolve a requested beat id, never an arbitrary label/number or future fact.

    Language coverage is deliberately English only. Chinese and unsupported
    grammar return None; generic icons remain available to other source genres.
    """
    if isinstance(board, dict) and board.get('lang', 'en') != 'en':
        return None
    context = None
    for bid, section, text in _beats(board):
        if context and context[0] != section:
            context = None
        value = None
        a = next((m for m in ARRAY.finditer(text) if _whole_values(m)), None)
        r = next((m for m in ROTATE.finditer(text) if _whole_values(m)), None)
        counts = tuple(m.span() for m in COUNT.finditer(text))
        equations = [m for m in EQUATION.finditer(text) if _whole_values(m)]
        q = equations[0] if equations else None
        partial_equation = any(not any(e.start() <= m.start() < e.end() for e in equations)
                               for m in EQUATION_CUE.finditer(text))
        if partial_equation or (ROTATE_CUE.search(text) and not r):
            context = None
        elif (a or r or q or counts or PANELS.search(text)) and UNCERTAIN.search(text):
            context = None
        elif a or (context and (r or q or counts)):
            if a:
                rows, cols = _number(a[1]), _number(a[2])
                context = (section, bid, rows, cols, False, '') if _valid(rows, cols) else None
            if context:
                _, base, rows, cols, rotated, equation = context
                if r and (_number(r[1]), _number(r[2])) != (cols, rows):
                    context = None
                elif any(tuple(_number(e[i]) for i in (1, 2, 3)) != (rows, cols, rows * cols)
                         for e in equations):
                    context = None
                else:
                    equation = f'{rows} × {cols} = {rows * cols}' if q else equation
                    value = Diagram('dots', bid, base, rows, cols, equation,
                                    a.span() if a else None, q.span() if q else None,
                                    r.span() if r else None, counts)
                    context = (section, base, rows, cols, rotated or bool(r), equation)
        else:
            p = PANELS.search(text)
            if p:
                phrase = re.sub(r'\s+together\s*$', '', p[1], flags=re.I)
                labels = tuple(s.strip() for s in re.split(r'\s*,\s*|\s+and\s+', phrase))
                if 2 <= len(labels) <= 4 and len(set(labels)) == len(labels) and all(s.lower() in LABELS for s in labels):
                    value = Diagram('panels', bid, bid, labels=labels, glide=p.span())
        if bid == ref:
            return value
    return None


def cue(timing, offset):
    ct = timing.get('char_times', [])
    return timing['start'] + (ct[min(offset, len(ct)-1)] if ct else 0.)


def window(timing, span):
    a, b = (cue(timing, n) for n in span)
    return a, max(a + .05, min(timing['speech_end'], b))


def ease(u):
    u = min(1., max(0., u))
    return u*u*(3-2*u)


class ProofDrawing:
    """One scheduled hand constructs the array and writes the equation.

    Later source actions reuse those dot identities. bind() translates Element's
    elapsed/rate back to source time; no frame-history-dependent drawing cache.
    """
    dressed = True

    def __new__(cls, specs, timing, size, lang, skin):
        if specs[0].kind == 'panels':
            return PanelDrawing(specs, timing, size, lang, skin)
        return super().__new__(cls)

    def __init__(self, specs, timing, size, lang, skin):
        self.specs, self.timing = tuple(specs), timing
        self.size = tuple(round(v) for v in size)
        self.lang, self.skin = lang, skin
        self.spec = specs[0]
        self.events = {'count': []}
        self.equation = ''
        for spec in specs:
            bt = timing['beats'][spec.ref]
            for name, span in (('build', spec.build), ('write', spec.write), ('rotate', spec.rotate)):
                if span:
                    if name == 'write':
                        self.events.setdefault(name, window(bt, span))
                    else:
                        self.events[name] = window(bt, span)
            self.events['count'].extend(window(bt, s) for s in spec.counts)
            if spec.equation:
                self.equation = spec.equation
        self.origin = self.events['build'][0]
        self.duration = max(.1, self.events['build'][1] - self.origin)
        self.start, self.rate = self.origin, 1.
        w,h = self.size
        self.spacing = min(w*.65/max(self.spec.cols, self.spec.rows), h*.72/max(self.spec.rows,self.spec.cols))
        # The farthest corner sweeps its full radial distance during rotation.
        # Include the count ring and stroke/nib margin before allocating paths.
        rx, ry = (self.spec.cols-1)/2, (self.spec.rows-1)/2
        corner = math.hypot(rx, ry)
        bx, by = (corner, corner) if 'rotate' in self.events else (rx, ry)
        margin = max(3., round(h/100)) + 2.
        hand = ink.Hand(skin.hand)
        scale = h / (680 if w/h < 2 else 738)
        bounds = hand.img.getbbox()
        shadow = hand.shadow.getbbox()
        left = min(bounds[0], shadow[0]+14) - hand.tip[0]
        top = min(bounds[1], shadow[1]+18) - hand.tip[1] - 6
        right = max(bounds[2], shadow[2]+14) - hand.tip[0]
        bottom = max(bounds[3], shadow[3]+18) - hand.tip[1]
        left, top, right, bottom = (v*scale for v in (left, top, right, bottom))
        # Shift vertically when that preserves the earlier mark size; shrink
        # only if neither the rotated rings nor the construction hand can fit.
        self.spacing = min(self.spacing,
            (w/2-margin)/(bx+.23*1.8),
            (w/2+left-margin)/(rx+.23), (w/2-right-margin)/(rx+.23),
            (h-2*margin)/(2*(by+.23*1.8)),
            (h+top-bottom-2*margin)/(2*(ry+.23)))
        self.radius = max(5., self.spacing*.23)
        low = max((by+.23*1.8)*self.spacing+margin,
                  (ry+.23)*self.spacing-top+margin)
        high = min(h-(by+.23*1.8)*self.spacing-margin,
                   h-(ry+.23)*self.spacing-bottom-margin)
        self.center_y = min(high, max(low, h*.43))
        positions = self.positions(0.)
        paths = [[(x+self.radius*math.cos(j*math.tau/32), y+self.radius*math.sin(j*math.tau/32)) for j in range(33)] for x,y in positions]
        self.array = ink.stroke_drawing(self.size, paths, color=skin.ink, width=max(3.,h/160), min_dur=1., max_dur=1., pop=0.)
        # This route fills dots at stroke completion; reserve no detached pop
        # interval after the nib has finished the source construction.
        self.array.pop = 0.
        self.array.duration = self.array.draw_time
        self.array._mask = self.array._native_mask
        lines, font_size = ink.fit_text(self.equation or ' ', lang, w*.8, 1, round(min(72,h*.12)), min_size=24, fonts=skin.fonts)
        self.text = ink.TextDrawing(lines, lang, font_size, color=skin.ink, fonts=skin.fonts, min_dur=1., max_dur=1.)
        self.native_recipe = ('diagram', (self.specs, self.timing, self.size, lang), {})

    def bind(self, start, rate):
        self.start, self.rate = start, rate
        # Follow the scheduler's actual hand window, finishing inside the
        # narrated construction clause even when strokes are compressed.
        self.events['build'] = (start, start + self.duration / rate)

    def positions(self, u):
        # Rigid quarter turn keeps every dot distinct even halfway through.
        w,h = self.size
        angle = -math.pi/2*ease(u)
        c,s = math.cos(angle), math.sin(angle)
        return tuple((w/2+(x*c-y*s), self.center_y+(x*s+y*c))
                     for row in range(self.spec.rows) for col in range(self.spec.cols)
                     for x,y in [((col-(self.spec.cols-1)/2)*self.spacing,
                                  (row-(self.spec.rows-1)/2)*self.spacing)])

    def snapshot(self, t):
        a,b = self.events['build']
        visible = min(self.spec.total, max(0, math.ceil((t-a)/(b-a)*self.spec.total)))
        r = self.events.get('rotate', (math.inf, math.inf))
        u = 0. if t <= r[0] else min(1., (t-r[0])/(r[1]-r[0]))
        highlight = None
        for ca,cb in self.events['count']:
            if ca <= t <= cb:
                highlight = min(self.spec.total-1, int((t-ca)/(cb-ca)*self.spec.total))
        write = self.events.get('write', (math.inf, math.inf))
        return dict(dots=self.positions(u)[:visible], highlight=highlight,
                    equation=self.equation if t >= write[1] else '', rotation=u)

    def state(self, elapsed):
        t = self.start + elapsed/self.rate
        image = Image.new('RGBA', self.size)
        a,b = self.events['build']
        pen, down = None, False
        if t < b:
            fraction = min(1., max(0., (t-a)/(b-a)))
            layer, pen, down = self.array.state(fraction*self.array.duration)
            ink.paste(image, layer, 0, 0)
        else:
            state = self.snapshot(t)
            draw = ImageDraw.Draw(image)
            for i,(x,y) in enumerate(state['dots']):
                radius = self.radius
                draw.ellipse((x-radius,y-radius,x+radius,y+radius), fill=ink.rgba(self.skin.ink))
                if i == state['highlight']:
                    draw.ellipse((x-radius*1.8,y-radius*1.8,x+radius*1.8,y+radius*1.8), outline=ink.rgba(self.skin.color((40,127,163))), width=max(3,round(self.size[1]/100)))
        return image,pen,down


class PanelMotion:
    def __init__(self, spec, timing, size, skin, palette, floor='still', *, speech_end=None):
        self.spec, self.size, self.skin, self.palette = spec, size, skin, palette
        self.window = window(timing['beats'][spec.ref], spec.glide)
        self.floor = floor
        self.speech_end = timing['beats'][spec.ref]['speech_end'] if speech_end is None else speech_end
        self.holds = [(h['start'], h['end']) for h in timing.get('holds', [])]
        self.holds += [(h['speech_end'], h['hold_end']) for h in timing.get('transitions', [])]
        self.holds += [(timing['beats'][bid]['speech_end'], timing['beats'][bid]['speech_end'] + pause)
                       for bid, pause in timing.get('pauses', {}).items() if pause > 0]
        self.labels = []
        w,h = size
        card_width = self.boxes(self.window[1])[0][2]
        for label in spec.labels:
            lines, font_size = ink.fit_text(label, 'en', card_width*.82, 1, round(h*.052), min_size=24, fonts=skin.fonts)
            drawing = ink.TextDrawing(lines, 'en', font_size, fonts=skin.fonts, color=palette['ink'])
            self.labels.append(drawing.state(drawing.duration)[0])

    def _ambient(self, t, phase=0.):
        # The cards ease into place before the spoken glide clause ends. Carry
        # the bounded ambient arc through that glide instead of leaving a
        # motionless gap between their arrival and the final source word.
        a, end = self.window[0], self.speech_end
        if self.floor == 'still' or not a < t < end:
            return 0.
        before, after = a, end
        for start, stop in self.holds:
            if start <= t <= stop:
                return 0.
            if stop < t:
                before = max(before, stop)
            elif start > t:
                after = min(after, start)
        envelope = ease((t-before)/.4) * ease((after-t)/.4)
        amplitude = self.size[1] * {'breathing': .03, 'drifting': .045, 'lively': .06}[self.floor]
        return amplitude * math.sin((t-a)*1.1 + phase) * envelope

    def boxes(self,t):
        w,h = self.size
        n = len(self.spec.labels)
        square = w == h
        gap = w*.025
        cw,ch = (w*.65,h*min(.14,.52/n)) if square else ((w*.76-gap*(n-1))/n,h*.33)
        a,b = self.window
        out=[]
        for i in range(n):
            u=ease((t-a)/(b-a)*1.3-i*.1)
            x,y = ((w-cw)/2,h*.17+i*h*.60/n) if square else (w*.10+i*(cw+gap),h*.28)
            out.append((x+(1-u)*w*.04+self._ambient(t),
                        y-(1-u)*h*(.1 if square else .15)+self._ambient(t, math.pi/2)*.7,cw,ch))
        return tuple(out)

    def paint(self,image,t):
        if t < self.window[0]:
            return image
        draw=ImageDraw.Draw(image)
        scale=self.size[1]/1080
        for (x,y,w,h),label in zip(self.boxes(t),self.labels):
            draw.rounded_rectangle((x,y,x+w,y+h), radius=round(18*scale), fill=self.palette['background'], outline=self.palette['accent'], width=max(2,round(5*scale)))
            image.paste(label,(round(x+(w-label.width)/2),round(y+(h-label.height)/2)),label)
        return image


class PanelDrawing:
    """Source-clock panel foreground shared by pure and native whiteboards.

    Uses the existing diagram recipe so native reconstruction regenerates labels
    at the target size without adding an export format or resizing a bitmap.
    """
    dressed = True

    def __init__(self, specs, timing, size, lang, skin):
        self.size = tuple(round(v) for v in size)
        self.spec = specs[0]
        self.motion = PanelMotion(self.spec, timing, self.size, skin,
                                  timing['_diagram_palette'], timing['_diagram_floor'],
                                  speech_end=timing.get('_diagram_speech_end'))
        self.origin = self.motion.window[0]
        self.duration = max(.05, self.motion.window[1] - self.origin)
        self.start, self.rate = self.origin, 1.
        self.native_recipe = ('diagram', (tuple(specs), timing, self.size, lang), {})

    def bind(self, start, rate):
        self.start, self.rate = start, rate

    def state(self, elapsed):
        t = self.start + elapsed/self.rate
        image = Image.new('RGBA', self.size)
        return self.motion.paint(image, t), None, False

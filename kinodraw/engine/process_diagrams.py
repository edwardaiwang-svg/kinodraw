"""Process boards: a labelled diagram that builds up across a scene's beats, the way a teacher draws on a board.

The plan's ``scene.boards`` (director/v3/schema.py) choose structure only: a layout (parts, flow or compare), which
offered pictures, how items connect and on which words each one appears. Every word written here is copied from
the beat it appears in; spoken math is typeset by the rules below ("A plus B equals B plus A" -> "a + b = b + a",
"about five times hotter" -> "≈ 5× hotter"), and every position comes from the layout grammar in this module,
never from a model. Items appear on their cue words, stay for the scene, and later items can light them up, ring
them, dim them (a restarted hop) or turn them (a dot array's quarter turn). The camera stays locked on the board.
"""
from __future__ import annotations

import math
import re

from PIL import Image, ImageDraw

from .. import markup
from . import ink
from .source_diagrams import NUMBERS

# ------------------------------------------------------------------ spoken math and named terms (English)
_NUM = r'(?:\d+(?:[.,]\d+)*|' + '|'.join(sorted(NUMBERS, key=len, reverse=True)) + r')'
TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[A-Za-z]+(?:['’][A-Za-z]+)?|[^\sA-Za-z\d]")
BINARY = {'plus': '+', 'minus': '−', 'times': '×', 'x': '×'}
PAIRED = {('multiplied', 'by'): '×', ('divided', 'by'): '÷', ('divide', 'by'): '÷', ('over', None): None}
EQUALS = {'equals', 'is', 'equal', 'makes', 'gives'}
APPROX = {'about', 'roughly', 'approximately', 'around', 'nearly'}
VARIABLES = set('abcmnpqrstuvwxyz')


def number(word: str) -> int | float | None:
    """The value of a digit string or an English number word (zero..sixty-nine), else None."""
    word = word.lower()
    if re.fullmatch(r'\d+(?:,\d{3})*', word):
        return int(word.replace(',', ''))
    if re.fullmatch(r'\d+\.\d+', word):
        return float(word)
    return NUMBERS.get(word)


def _tokens(text: str):
    return [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)]


def _kind(tokens, i):
    """'num', 'var', 'op', 'pair' (a two-word operator starting here), 'eq', 'approx' or None for token i."""
    word = tokens[i][0].lower()
    following = tokens[i + 1][0].lower() if i + 1 < len(tokens) else ''
    if number(word) is not None:
        return 'num'
    if (word, following) in PAIRED:
        return 'pair'
    if word in ('plus', 'minus', 'times'):
        return 'op'
    if word in EQUALS:
        return 'eq'
    if word in APPROX:
        return 'approx'
    if len(word) == 1 and word in VARIABLES | {'x'}:
        return 'var'
    return None


def math_runs(text: str) -> list[tuple[int, int]]:
    """Character spans of the spoken math in ``text``: operands joined by plus/minus/times/multiplied by/divided by
    and equals/is (3 times 5 is 15; A plus B equals B plus A), a lone 'divide by five', or a ratio ('five times
    hotter'), each with a leading 'about'. A sentence without an operator has none ("Jump 3, then jump 5")."""
    toks, runs, i = _tokens(text), [], 0
    while i < len(toks):
        start, j, ops, operands, last = i, i, 0, 0, None
        if _kind(toks, j) == 'approx':
            j += 1
        while j < len(toks):
            kind = _kind(toks, j)
            if kind in ('num', 'var') and last not in ('num', 'var'):
                operands, last, j = operands + 1, 'num', j + 1
            elif kind == 'op' and last in ('num', None) or kind == 'pair':
                ops, last = ops + 1, 'op'
                j += 2 if kind == 'pair' else 1
            elif kind == 'op' and last == 'op':
                break
            elif kind == 'op':
                ops, last, j = ops + 1, 'op', j + 1
            elif kind == 'eq' and last == 'num':
                k = j + (2 if toks[j][0].lower() == 'is' and j + 1 < len(toks) and toks[j + 1][0].lower() == 'equal' else 1)
                k += 1 if k < len(toks) and toks[k][0].lower() == 'to' else 0
                k += 1 if k < len(toks) and toks[k][0].lower() == 'still' else 0
                if k < len(toks) and _kind(toks, k) in ('num', 'var', 'approx'):
                    ops, last, j = ops + 1, 'op', k
                    if _kind(toks, j) == 'approx':
                        j += 1
                else:
                    break
            else:
                break
        end = j
        ratio = (last == 'op' and ops == 1 and operands == 1 and end < len(toks) and toks[end - 1][0].lower() == 'times'
                 and re.fullmatch(r'[A-Za-z]{3,}', toks[end][0]) is not None)
        if ratio:
            end += 1                                      # "five times hotter": a ratio of one quantity
        while end > start and _kind(toks, end - 1) in ('op', 'eq', 'approx') and not ratio:
            end -= 1                                      # a dangling operator ("x times") is not an equation
        lone = ops == 1 and operands == 1 and _kind(toks, start + (_kind(toks, start) == 'approx')) == 'pair'
        if end > start and ops and operands and (operands >= 2 or ratio or lone):
            if any(_kind(toks, k) == 'var' for k in range(start, end)) and not any(
                    _kind(toks, k) == 'num' for k in range(start, end)) and operands < 2:
                i = end
                continue
            runs.append((toks[start][1], toks[end - 1][2]))
            i = end
        else:
            i = start + 1
    return runs


def typeset(words: str) -> str:
    """Spoken math written as math; other words kept as spoken. Fragments joined by ' ... ' are typeset one by one
    and joined by a space ("seconds ... divide by five ... roughly ... miles away" -> "seconds ÷ 5 ≈ miles away")."""
    parts = [p.strip(' ,.;:!?') for p in re.split(r'\s*(?:\.\.\.|…)\s*', words.strip()) if p.strip(' ,.;:!?')]
    out = ' '.join(_typeset(p) for p in parts)
    bare = lambda s: re.sub(r'[\s.,;:!?]', '', s)
    # Nothing spoken to write as math: the text is already written ("Mon. & Tue.", "8 a.m.–2 p.m."), keep it as is.
    return re.sub(r'\s*(?:\.\.\.|…)\s*', ' ', words.strip()).strip() if bare(out) == bare(words) else out


DETERMINERS = {'a', 'an', 'the', 'this', 'that', 'each', 'every', 'any', 'which', 'another', 'no'}


def _typeset(text: str) -> str:
    toks, out, i = _tokens(text), [], 0
    letters = any(_kind(toks, k) == 'var' for k in range(len(toks)))
    spoken = any(_kind(toks, k) in ('op', 'pair', 'eq') for k in range(len(toks)))    # "A plus B", not "A = P(1 + r)"
    while i < len(toks):
        word, kind = toks[i][0], _kind(toks, i)
        lower = word.lower()
        nxt = _kind(toks, i + 1) if i + 1 < len(toks) else None
        prev = out[-1] if out else ''
        joined = i and toks[i][1] == toks[i - 1][2]          # written with no space before it
        if joined and kind in (None, 'var') and out and re.fullmatch(r'[^\w\s]', toks[i - 1][0]) and \
                out[-1].endswith(toks[i - 1][0]) and not re.fullmatch(r'[^\w\s]', word):
            out[-1] += word                                     # a word after its symbol: "$1,000", "Ctrl+Shift", "6-digit"
            i += 1
            continue
        if kind == 'num' and joined and out and re.fullmatch(r'[$€£¥#(+\-−]', toks[i - 1][0]) and \
                out[-1].endswith(toks[i - 1][0]):
            out[-1] += word if word[0].isdigit() else str(number(word))
            i += 1
            continue
        if kind == 'num' and lower == 'one' and any(t[0].lower() in DETERMINERS for t in toks[max(0, i - 2):i]) \
                and toks[i - 1][0].isalpha():
            out.append(word)                              # a pronoun ("a full one", "the one"), not the number 1
        elif kind == 'num':
            value = number(word)
            out.append(word if word[0].isdigit() else str(value))
        elif kind == 'var' and spoken and (nxt in ('op', 'pair', 'eq') or prev in ('+', '−', '×', '·', '÷', '=')):
            out.append(lower)
        elif kind == 'pair':
            out.append(PAIRED[(lower, toks[i + 1][0].lower())])
            i += 1
        elif kind == 'op' and lower == 'times' and prev[:1].isdigit() and nxt is None and i + 1 < len(toks):
            out[-1] = prev + '×'                                  # five times hotter -> 5× hotter
        elif kind == 'op' and (prev[:1].isdigit() or len(prev) == 1) and nxt in ('num', 'var'):
            sym = BINARY[lower]
            out.append('·' if sym == '×' and letters and not (prev[:1].isdigit() and number(toks[i + 1][0]) is not None)
                       else sym)
        elif kind == 'eq' and prev and (prev[-1:].isdigit() or len(prev) == 1) and i + 1 < len(toks):
            k = i + 1
            while k < len(toks) and toks[k][0].lower() in ('equal', 'to', 'still'):
                k += 1
            if k < len(toks) and _kind(toks, k) in ('num', 'var', 'approx'):
                out.append('=')
                i = k
                continue
            out.append(word)
        elif kind == 'approx' and (nxt == 'num' or i == len(toks) - 1 or len(toks) == 1):
            out.append('≈')
        elif re.fullmatch(r'[^\w\s]', word):
            spaced_after = i + 1 >= len(toks) or toks[i + 1][1] > toks[i][2]
            if out and (joined or spaced_after and not (i + 1 < len(toks) and toks[i][1] > toks[i - 1][2])):
                out[-1] += word                                 # punctuation that closes a word ("15,", "hotter.")
            else:
                out.append(word)                                # a symbol opening the next word ("$", "(") or
                                                                # standing alone between spaces ("Ctrl + Shift")
        else:
            out.append(word)
        i += 1
    return re.sub(r'\s+', ' ', ' '.join(out)).strip(' ,;:')


STOP = set('''a an the and or but so then that which who when where while because if as than is are was were be been
it its this these those there here to from at in on into onto by for with up down out over under through after before
until he she they we you i his her their our your my reaches rises falls forms flows moves travels carries comes goes
starts runs jumps spreads grows shows means makes takes gets heats happens'''.split())
TERM_CUES = (
    re.compile(r"\b(?:called|known\s+as|call(?:s|ed)?\s+(?:it|this|that|them))\s+(?:an?\s+|the\s+)?"
               r"([A-Za-z][\w'-]*(?:\s+[A-Za-z][\w'-]*){0,5})", re.I),
    re.compile(r"\b(?:this|that|it)(?:\s+\w+){0,3}?\s+is\s+(?:called\s+)?(?:the|an?)\s+"
               r"([A-Za-z][\w'-]*(?:\s+[A-Za-z][\w'-]*){0,5})", re.I),
    re.compile(r"\bthat(?:'|’)s\s+(?:an?\s+|the\s+)?([A-Za-z][\w'-]*(?:\s+[A-Za-z][\w'-]*)?)\s*[.!]", re.I),
)


RULE_WORDS = re.compile(r'\b(?:property|law|rule|principle|theorem|formula|identity|equation)\b', re.I)


def is_rule(term: str) -> bool:
    """A named rule ("the commutative property of addition") goes in a rule box with its equation."""
    return RULE_WORDS.search(term) is not None


def terms(text: str) -> list[str]:
    """Terms a sentence names ("called graupel", "Scientists call it a stepped leader", "This is the commutative
    property of addition", "That's thunder."), verbatim, at most 5 words, stopping at function words and verbs."""
    found = []
    for pattern in TERM_CUES:
        for m in pattern.finditer(text):
            words = m.group(1).split()
            kept = []
            for k, w in enumerate(words):
                if w.lower() in STOP and not (w.lower() == 'of' and kept and k + 1 < len(words)):
                    break
                kept.append(w)
            while kept and kept[-1].lower() in STOP | {'of'}:
                kept.pop()
            if kept:
                term = ' '.join(kept)
                if term.lower() not in (f.lower() for f in found):
                    found.append(term)
    return found


ROWS = re.compile(r'\b(' + _NUM + r')\s+rows?\s+of\s+(' + _NUM + r')\b', re.I)
HOP = re.compile(r'\b(back\s+|minus\s+|subtract\s+)?(' + _NUM + r')\b', re.I)


def dots_of(text: str):
    """(rows, cols) for '3 rows of 5 (dots)', else None."""
    m = ROWS.search(text)
    if not m:
        return None
    rows, cols = number(m[1]), number(m[2])
    return (int(rows), int(cols)) if isinstance(rows, int) and isinstance(cols, int) and 1 <= rows <= 12 \
        and 1 <= cols <= 12 and rows * cols <= 100 else None


def hop_of(text: str):
    """The signed size of a spoken hop ('jump 3', 'then 5', 'jump back 2'), else None."""
    m = HOP.search(text)
    if not m or not isinstance(number(m[2]), int) or not 0 < number(m[2]) <= 50:
        return None
    return -number(m[2]) if m[1] or re.search(r'\bback\b', text, re.I) else number(m[2])


def start_of(text: str) -> int:
    m = re.search(_NUM, text, re.I)
    value = number(m.group()) if m else None
    return value if isinstance(value, int) and 0 <= value <= 100 else 0


# ------------------------------------------------------------------ plan helpers shared with the renderer
def board_beats(plan) -> set:
    """Beat ids of scenes that carry a board: the board draws them (no icons, no source sentences)."""
    if not plan:
        return set()
    return {bid for scene in plan['scenes'] if scene.get('boards') for bid in scene['beat_ids']}


def find(spoken: str, words: str) -> int | None:
    """Character offset of ``words`` in ``spoken`` ignoring case, punctuation and spacing; None if absent."""
    if not words.strip():
        return None
    key = [w for w in re.findall(r"\w+(?:['’]\w+)?", words.casefold())]
    if not key:
        return None
    found = list(re.finditer(r"\w+(?:['’]\w+)?", spoken.casefold()))
    for i in range(len(found) - len(key) + 1):
        if [m.group() for m in found[i:i + len(key)]] == key:
            return found[i].start()
    return None


def cue_time(timing: dict, beat: dict, cue: str, lang: str) -> float:
    """When the cue words are heard (the beat start for no cue)."""
    info = timing['beats'][beat['id']]
    spoken = beat['spoken'][lang] if isinstance(beat['spoken'], dict) else beat['spoken']
    times = info.get('char_times') or []
    at = find(spoken, cue)
    if at is None:
        display = beat.get('display', {})
        display = display.get(lang, '') if isinstance(display, dict) else str(display or '')
        shown = find(display, cue)
        at = round(shown / max(1, len(display)) * len(spoken)) if shown is not None else None
    if at is None or not times:
        return info['start'] + .15
    return info['start'] + times[min(at, len(times) - 1)]


# ------------------------------------------------------------------ layout grammar
STEP_KINDS = ('picture', 'dots', 'number_line')
GROUND_WORDS = re.compile(r'tree|house|home|building|tower|mountain|hill|barn|church|school|tent|plant|flower|'
                          r'castle|rooftop|roof|lighthouse|skyscraper|cabin|hut|car\b|bus\b|truck|fence|pole', re.I)


class Rect:
    __slots__ = ('x', 'y', 'w', 'h')

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = float(x), float(y), float(w), float(h)

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def hits(self, other, pad=0.):
        return not (self.x + self.w + pad <= other.x or other.x + other.w + pad <= self.x or
                    self.y + self.h + pad <= other.y or other.y + other.h + pad <= self.y)

    def inside(self, W, H, mx=0., my=0.):
        return self.x >= mx and self.y >= my and self.x + self.w <= W - mx and self.y + self.h <= H - my

    def tuple(self):
        return (self.x, self.y, self.w, self.h)


def edge_point(rect: Rect, toward):
    """Where the line from the rect's centre toward ``toward`` leaves the rect."""
    dx, dy = toward[0] - rect.cx, toward[1] - rect.cy
    if dx == dy == 0:
        return rect.cx, rect.cy
    sx = (rect.w / 2) / abs(dx) if dx else math.inf
    sy = (rect.h / 2) / abs(dy) if dy else math.inf
    s = min(sx, sy)
    return rect.cx + dx * s, rect.cy + dy * s


def region(rect: Rect, where: str) -> Rect:
    """A part of a picture: its top, bottom, left or right third, or all of it."""
    x, y, w, h = rect.tuple()
    return {'top': Rect(x + w * .1, y + h * .08, w * .8, h * .32), 'bottom': Rect(x + w * .1, y + h * .6, w * .8, h * .32),
            'left': Rect(x + w * .05, y + h * .2, w * .35, h * .6), 'right': Rect(x + w * .6, y + h * .2, w * .35, h * .6),
            'top_left': Rect(x, y, w * .45, h * .45), 'top_right': Rect(x + w * .55, y, w * .45, h * .45),
            'bottom_left': Rect(x, y + h * .55, w * .45, h * .45),
            'bottom_right': Rect(x + w * .55, y + h * .55, w * .45, h * .45)}.get(
        where, Rect(x + w * .15, y + h * .2, w * .7, h * .6))


def charge_radius(area: Rect, H) -> float:
    """A charge sign's radius: big enough to read at a glance, whatever it marks."""
    return min(H * .032, max(H * .022, min(area.w, area.h) * .14))


def beside(rect: Rect, where: str, r: float) -> Rect:
    """A band of charge signs just outside a picture too small to hold them, on the side the plan names."""
    band, gap = r * 2.8, r * .6
    w = max(rect.w, band * 3)
    side = {'left': Rect(rect.x - gap - band * 2, rect.cy - band, band * 2, band * 2),
            'right': Rect(rect.x + rect.w + gap, rect.cy - band, band * 2, band * 2),
            'bottom': Rect(rect.cx - w / 2, rect.y + rect.h + gap, w, band)}
    return side.get(where.split('_')[0] if where.startswith('bottom') else where,
                    Rect(rect.cx - w / 2, rect.y - gap - band, w, band))


class Layout:
    """Places one board's items on a page W x H (page pixels) so text stays inside the page and off pictures.

    ``measure(item, text_kind) -> (w, h)`` gives a text item's size. Pictures take slots of the board's layout;
    texts take the first free position from an ordered list of candidates for their kind; links and rings are
    lines and need no room of their own (their labels do)."""

    def __init__(self, board, W, H, measure, picture_box=None, ground_ids=None, margin=(0., 0.)):
        self.board, self.W, self.H, self.measure = board, W, H, measure
        self.mx, self.my = margin            # how far in from the page edges text must stay to be on screen
        self.ground_ids = ground_ids
        self.picture_box = picture_box or (lambda item, rect: rect)   # content bbox of a picture fitted in rect
        self.items = {it['id']: it for it in board['items']}
        self.place: dict[str, Rect] = {}
        self.extra: dict[str, object] = {}
        self.taken: list[Rect] = []
        self.pad = H * .02
        self._lay()

    # -- helpers
    def free(self, rect, pad=None):
        return rect.inside(self.W, self.H, self.mx, self.my) and not any(rect.hits(r, self.pad if pad is None else pad) for r in self.taken)

    def take(self, iid, rect):
        self.place[iid] = rect
        self.taken.append(rect)
        return rect

    def clamp(self, rect):
        rect.x = min(max(self.mx, rect.x), self.W - self.mx - rect.w)
        rect.y = min(max(self.my, rect.y), self.H - self.my - rect.h)
        return rect

    def _first_free(self, candidates, size, pad=None):
        w, h = size
        for x, y in candidates:
            rect = Rect(x, y, w, h)
            if self.free(rect, pad):
                return rect
        for x, y in candidates:                       # nothing free: slide down then up from each candidate
            for step in range(1, 12):
                for sign in (1, -1):
                    rect = self.clamp(Rect(x, y + sign * step * h * .55, w, h))
                    if self.free(rect, pad):
                        return rect
        return self.clamp(Rect(*candidates[0], w, h))

    def problems(self) -> list[str]:
        """Text outside the page, on a picture or on other text (an empty list is a clean board)."""
        kinds = {it['id']: it['kind'] for it in self.board['items']}
        texts = {k: r for k, r in self.place.items() if k.endswith(':label') or kinds.get(k) in ('label', 'equation')}
        pictures = {k: r for k, r in self.place.items() if kinds.get(k) == 'picture'}
        out = [f'{k} leaves the page' for k, r in texts.items() if not r.inside(self.W, self.H, self.mx, self.my)]
        names = sorted(texts)
        for i, a in enumerate(names):
            out += [f'{a} covers picture {b}' for b, r in pictures.items() if texts[a].hits(r)]
            out += [f'{a} overlaps {b}' for b in names[i + 1:] if texts[a].hits(texts[b])
                    and not (self.boxed(a) and self.boxed(b))]
        return out

    def boxed(self, key):
        return any(key == e['id'] and e['to'] in self.items and self.items[e['to']]['style'] == 'box' or
                   key == e['id'] and e['style'] == 'box' for e in self.board['items'])

    # -- the grammar
    def _lay(self):
        W, H, items = self.W, self.H, self.board['items']
        layout = self.board['layout']
        steps = [it for it in items if it['kind'] in STEP_KINDS or (
            layout == 'flow' and it['kind'] in ('label', 'equation') and not it['to'] and it['style'] != 'box')]
        ground = layout == 'parts' and any(it['kind'] == 'picture' and self._slot(it) == 'ground' for it in items)
        self.extra['ground_y'] = H * .96 if ground else None
        # 1. pictures and other steps
        if layout == 'flow':
            n = max(1, len(steps))
            gap = W * .06
            # as many to a row as fit side by side (words wider than their share would run into each other)
            widest = max((self.measure(it, it['kind'])[0] for it in steps if it['kind'] in ('label', 'equation')),
                         default=0)
            fit = int((W * .94 + gap) / (widest + gap)) if widest else 4
            per_row = min(n, 4, max(fit, math.ceil(n / 2)))
            rows = math.ceil(n / per_row)
            bw = min(W * .26, (W * .94 - gap * (per_row - 1)) / per_row)
            bh = min(H * (.40 if rows == 1 else .26), bw)
            for k, it in enumerate(steps):
                r, c = divmod(k, per_row)
                count = min(per_row, n - r * per_row)
                x0 = (W - (count * bw + (count - 1) * gap)) / 2
                y = H * (.28 if rows == 1 else .14 + r * .44)
                self._step(it, Rect(x0 + c * (bw + gap), y, bw, bh))
        else:
            sides = {'compare': {'left': (W * .26, H * .40), 'right': (W * .74, H * .40), 'center': (W * .5, H * .40)},
                     'parts': {'center': (W * .5, H * (.33 if ground else .45)), 'left': (W * .13, H * .45),
                               'right': (W * .87, H * .45), 'top': (W * .5, H * .12), 'bottom': (W * .5, H * .82),
                               'top_left': (W * .13, H * .16), 'top_right': (W * .87, H * .16),
                               'bottom_left': (W * .13, H * .78), 'bottom_right': (W * .87, H * .78)}}[layout]
            order = (['left', 'right', 'center'] if layout == 'compare' else
                     ['center', 'right', 'left', 'top_right', 'top_left', 'bottom_right', 'bottom_left'])
            used: dict[str, int] = {}
            ground_x = [.30, .70, .15, .85, .50]
            for it in steps:
                slot = self._slot(it)
                if it['kind'] in ('number_line', 'dots'):
                    self._step(it, None)
                    continue
                if slot == 'ground' and ground:
                    k = used.get('ground', 0)
                    used['ground'] = k + 1
                    bh = H * .2
                    x = W * ground_x[k % len(ground_x)]
                    self.extra.setdefault('on_ground', set()).add(it['id'])
                    if self.ground_ids is not None:
                        self.ground_ids.add(it['id'])
                    self._step(it, Rect(x - bh * .6, self.extra['ground_y'] - bh, bh * 1.2, bh))
                    continue
                if slot not in sides:
                    slot = next((s for s in order if s not in used), order[-1])
                k = used.get(slot, 0)
                used[slot] = k + 1
                big = slot == 'center' and layout != 'compare' or layout == 'compare' and slot != 'center'
                bw, bh = (W * (.30 if layout == 'compare' else .34), H * (.44 if ground else .5)) if big else (H * .26, H * .26)
                cx, cy = sides[slot]
                shift = k * (bh * 1.05 if slot in ('left', 'right') else bw * 1.05)
                rect = Rect(cx - bw / 2 + (0 if slot in ('left', 'right') else shift),
                            cy - bh / 2 + (shift if slot in ('left', 'right') else 0), bw, bh)
                self._step(it, self.clamp(rect))
        self._dots_and_lines()
        # 2. rule boxes and the equation stack (in order of appearance), then labels and link labels
        stack_x, stack_y = W * .01, H * .02
        if layout == 'compare':
            stack_x, stack_y = None, H * .70
        for it in items:
            if it['kind'] == 'label' and it['style'] == 'box':
                inside = [e for e in items if e['kind'] in ('equation', 'label') and e['to'] == it['id']]
                sizes = [self.measure(it, 'title')] + [self.measure(e, e['kind']) for e in inside]
                bw = max(w for w, _ in sizes) + H * .06
                bh = sum(h for _, h in sizes) + H * .04 + H * .015 * len(inside)
                slot = it['at'] if it['at'] in ('top_left', 'top_right', 'bottom_left', 'bottom_right') else 'top_right'
                x = W - bw - W * .01 if slot.endswith('right') else W * .01
                y = H * .02 if slot.startswith('top') else H * .98 - bh
                box = self._first_free([(x, y), (x, y + H * .1)], (bw, bh))
                self.taken.append(box)
                self.extra[it['id'] + ':box'] = box
                y = box.y + H * .02
                for e, (w, h) in zip([it] + inside, sizes):
                    self.place[e['id']] = Rect(box.x + H * .03, y, w, h)
                    y += h + H * .015
        for it in items:
            if it['id'] in self.place or it['kind'] not in ('equation', 'label'):
                continue
            w, h = self.measure(it, it['kind'])
            target = self.anchor(it['to']) if it['to'] else None
            if target is None and it['kind'] == 'equation' or (target is None and it['kind'] == 'label'):
                if layout == 'flow' and it in steps:
                    continue
                if it['at'] not in ('auto', 'top_left') and layout != 'compare':
                    self.take(it['id'], self._first_free(self._slot_xy(it['at'], w, h), (w, h)))
                elif stack_x is None:
                    cands = [((W - w) / 2, stack_y + k * h * 1.1) for k in range(6)] + [((W - w) / 2, H * .03)]
                    self.take(it['id'], self._first_free(cands, (w, h)))
                else:
                    cands = [(stack_x, stack_y + k * h * .25) for k in range(40)]
                    rect = self._first_free(cands, (w, h), pad=H * .006)
                    self.take(it['id'], rect)
                    stack_y = rect.y + rect.h + H * .01
                continue
            self.take(it['id'], self._callout(it, target, (w, h)))
        for it in items:
            if it['kind'] in ('link', 'charges', 'rings', 'picture') and it['text']:
                self._side_label(it)

    def anchor(self, iid):
        """The area a label about item ``iid`` points at: a link's middle, the room rings spread over, else the
        item's own place."""
        it = self.items.get(iid)
        if it is None:
            return None
        if it['kind'] == 'link':
            a, b = self.place.get(it['ref']), self.place.get(it['to'])
            if a is None or b is None:
                return None
            mx, my = (a.cx + b.cx) / 2, (a.cy + b.cy) / 2
            return Rect(mx - 2, my - 2, 4, 4)
        if it['kind'] == 'rings':
            area = self.place.get(it['to'])
            return area and Rect(area.x - self.H * .12, area.y, area.w + self.H * .24, area.h)
        return self.place.get(iid)

    def _slot(self, it):
        if it['at'] != 'auto':
            return it['at']
        if self.board['layout'] == 'parts' and it['kind'] == 'picture' and GROUND_WORDS.search(it['ref']) and any(
                o['kind'] == 'picture' for o in self.board['items'] if o is not it and o['at'] != 'ground'):
            return 'ground'
        return 'auto'

    def _slot_xy(self, at, w, h):
        W, H = self.W, self.H
        x = {'left': W * .01, 'top_left': W * .01, 'bottom_left': W * .01, 'right': W * .99 - w,
             'top_right': W * .99 - w, 'bottom_right': W * .99 - w}.get(at, (W - w) / 2)
        y = {'top': H * .02, 'top_left': H * .02, 'top_right': H * .02, 'bottom': H * .8 - h,
             'bottom_left': H * .8 - h, 'bottom_right': H * .8 - h, 'ground': H * .8 - h}.get(at, (H - h) / 2)
        return [(x, y)]

    def _step(self, it, rect):
        if it['kind'] == 'picture':
            self.take(it['id'], self.picture_box(it, rect))
        elif it['kind'] in ('label', 'equation'):
            w, h = self.measure(it, it['kind'])
            self.take(it['id'], self.clamp(Rect(rect.cx - w / 2, rect.cy - h / 2, w, h)))
        else:
            self.extra.setdefault('pending', []).append((it, rect))

    def _callout(self, it, target: Rect, size):
        """A label beside what it names: the side the plan asks for first, then left, right, above, below."""
        W, H = self.W, self.H
        w, h = size
        gap = W * .035
        aim = target
        source = self.items.get(it['to'])
        if source and source['kind'] == 'charges':
            aim = self.place[source['id']]
        if source and source['kind'] == 'dots':                # clear of the whole turn, over the array
            aim = self.extra[source['id']]['box']
        sides = {'left': (aim.x - gap - w, aim.cy - h / 2), 'right': (aim.x + aim.w + gap, aim.cy - h / 2),
                 'top': (aim.cx - w / 2, aim.y - gap * .6 - h), 'bottom': (aim.cx - w / 2, aim.y + aim.h + gap * .6)}
        order = ['left', 'right', 'top', 'bottom'] if aim.cx >= W / 2 else ['right', 'left', 'top', 'bottom']
        if source and source['kind'] == 'dots':
            order = ['top', 'right', 'left', 'bottom']
        want = {'top_left': 'left', 'bottom_left': 'left', 'top_right': 'right', 'bottom_right': 'right'}.get(
            it['at'], it['at'])
        if want in sides:
            order.remove(want)
            order.insert(0, want)
        cands = [sides[s] for s in order]
        rect = self._first_free(cands, size)
        self.extra.setdefault('leaders', {})[it['id']] = aim
        return rect

    def _side_label(self, it):
        w, h = self.measure(it, 'label')
        if it['kind'] in ('charges', 'rings', 'picture'):
            area = self.anchor(it['id'])
            if area is None:
                return
            rect = self._callout(dict(it, to=''), area, (w, h))
            self.extra.setdefault('leaders', {})[it['id'] + ':label'] = area
        else:
            mid = self.anchor(it['id'])
            if mid is None:
                return
            mx, my = mid.cx, mid.cy
            gap = self.W * .03
            rect = self._first_free([(mx + gap, my - h / 2), (mx - gap - w, my - h / 2), (mx + gap, my - h * 1.8),
                                     (mx - gap - w, my + h)], (w, h))
            self.extra.setdefault('leaders', {})[it['id'] + ':label'] = Rect(mx - 2, my - 2, 4, 4)
        self.take(it['id'] + ':label', rect)

    def _dots_and_lines(self):
        """Charge regions, number lines and dot arrays: their room is fixed by what they hold."""
        W, H = self.W, self.H
        for it, rect in self.extra.pop('pending', []):
            if it['kind'] == 'number_line':
                hops = [e for e in self.board['items'] if e['kind'] == 'hop' and e['to'] == it['id']]
                start = start_of(it['text'])
                pos, top, spans, restarted = start, start, [], False
                for e in hops:
                    size = hop_of(e['text']) or 0
                    restarted = restarted or e['style'] == 'restart'
                    pos0 = start if e['style'] == 'restart' else pos
                    pos = pos0 + size
                    top = max(top, pos)
                    spans.append((abs(size), restarted))
                ticks = max(8, min(20, top - start + 2))
                y = H * (.70 if self.board['layout'] != 'flow' else .80)
                step = W * .84 / ticks
                rise = max([hop_height(n * step, H, lifted) for n, lifted in spans] + [0.]) + H * .1
                band = Rect(W * .06, y - rise, W * .88, rise + H * .1)
                self.place[it['id']] = Rect(W * .06, y - H * .02, W * .88, H * .12)
                self.taken.append(Rect(band.x, band.y, band.w, band.h))
                self.extra[it['id']] = dict(start=start, ticks=ticks, x0=W * .08, x1=W * .92, y=y)
            elif it['kind'] == 'dots':
                rows, cols = dots_of(it['text']) or (1, 1)
                side = H * .5 if rect is None else min(rect.w, rect.h)
                spacing = side / (max(rows, cols) + .5)
                center = (W / 2, H * .47) if rect is None else (rect.cx, rect.cy)
                diag = math.hypot(cols - 1, rows - 1) * spacing + spacing
                box = Rect(center[0] - diag / 2, center[1] - diag / 2, diag, diag)
                self.place[it['id']] = Rect(center[0] - cols * spacing / 2, center[1] - rows * spacing / 2,
                                            cols * spacing, rows * spacing)
                self.taken.append(box)
                self.extra[it['id']] = dict(rows=rows, cols=cols, spacing=spacing, center=center, box=box)
        for it in self.board['items']:
            if it['kind'] == 'charges' and it['to'] in self.place:
                where = it['at'] if it['at'] != 'auto' else 'center'
                target = self.place[it['to']]
                area = region(target, where)
                r = charge_radius(area, H)
                # signs go inside a big picture (a cloud); on a small or busy doodle they would not read: beside it
                if target.w < H * .35 or area.w < r * 2.8 * 2 or area.h < r * 2.8:
                    area = self.clamp(beside(target, where, r))
                    self.taken.append(area)
                self.place[it['id']] = area


# ------------------------------------------------------------------ drawings
class Timed:
    """A drawing that knows the source clock (bind) so later beats can dim, turn or ring it."""
    dressed = True

    def __init__(self, inner, dim_at=None):
        self.inner, self.size, self.duration = inner, inner.size, inner.duration
        if hasattr(inner, 'draw_time'):
            self.draw_time = inner.draw_time
        self.dim_at = dim_at
        self.start, self.rate = 0., 1.

    def bind(self, start, rate):
        self.start, self.rate = start, rate

    def clock(self, elapsed):
        return self.start + elapsed / self.rate

    def state(self, elapsed):
        img, pen, down = self.inner.state(elapsed)
        if img is not None and self.dim_at is not None and self.clock(elapsed) >= self.dim_at:
            u = min(1., (self.clock(elapsed) - self.dim_at) / .4)
            img = img.copy()
            img.putalpha(img.getchannel('A').point(lambda a: int(a * (1 - .68 * u))))
        return img, pen, down


def dot_positions(rows, cols, spacing, center, u):
    """Dot centres after ``u`` (0..1, eased) of a rigid quarter turn about the array's centre."""
    angle = -math.pi / 2 * (u * u * (3 - 2 * u))
    c, s = math.cos(angle), math.sin(angle)
    cx, cy = center
    out = []
    for r in range(rows):
        for k in range(cols):
            x, y = (k - (cols - 1) / 2) * spacing, (r - (rows - 1) / 2) * spacing
            out.append((cx + x * c - y * s, cy + x * s + y * c))
    return out


class Dots(Timed):
    """A rows x cols array the hand draws; it can turn a quarter turn as one rigid group at ``turn_at``."""

    def __init__(self, inner, rows, cols, spacing, center, colour, turn_at=None):
        super().__init__(inner)
        self.rows, self.cols, self.spacing, self.center, self.colour = rows, cols, spacing, center, colour
        self.turn_at = turn_at
        self.radius = spacing * .28

    def positions(self, u):
        return dot_positions(self.rows, self.cols, self.spacing, self.center, u)

    def state(self, elapsed):
        if elapsed < getattr(self.inner, 'draw_time', self.duration):
            return self.inner.state(elapsed)
        t = self.clock(elapsed)
        u = 0. if self.turn_at is None or t <= self.turn_at else min(1., (t - self.turn_at) / 1.2)
        image = Image.new('RGBA', self.size)
        draw = ImageDraw.Draw(image)
        r = self.radius
        for x, y in self.positions(u):
            draw.ellipse((x - r, y - r, x + r, y + r), fill=ink.rgba(self.colour))
        return image, None, False


class Rings:
    """Rings that spread from a point (a shock wave, a sound), then stay faintly; no hand."""
    dressed = True

    def __init__(self, size, center, r0, r1, colour, width):
        self.size, self.center, self.r0, self.r1 = size, center, r0, r1
        self.colour, self.width = colour, width
        self.duration = .3

    def state(self, elapsed):
        if elapsed < 0:
            return None, None, False
        image = Image.new('RGBA', self.size)
        draw = ImageDraw.Draw(image)
        cx, cy = self.center
        for k in range(3):
            u = min(1., max(0., (elapsed - k * .45) / 1.8))
            if u <= 0:
                continue
            r = self.r0 + (self.r1 - self.r0) * (k + 1) / 3 * (u * (2 - u))
            alpha = int(255 * (1 - .55 * u))
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink.rgba(self.colour, alpha), width=self.width)
        return image, None, False


def hop_height(span, H, lifted):
    """How high a hop of ``span`` pixels arcs; hops after a restart arc higher, over the dimmed first ones."""
    return min(H * .18, span * .45 + H * .05) * (1.4 if lifted else 1.)


def zigzag(a, b, steps, amplitude):
    (x0, y0), (x1, y1) = a, b
    length = math.hypot(x1 - x0, y1 - y0) or 1.
    nx, ny = -(y1 - y0) / length, (x1 - x0) / length
    out = [a]
    for k in range(1, steps):
        u = k / steps
        side = amplitude * (1 if k % 2 else -1)
        out.append((x0 + (x1 - x0) * u + nx * side, y0 + (y1 - y0) * u + ny * side))
    out.append(b)
    return out


def arrow_head(a, b, size):
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    return [(b[0] - size * math.cos(angle - .45), b[1] - size * math.sin(angle - .45)), b,
            (b[0] - size * math.cos(angle + .45), b[1] - size * math.sin(angle + .45))]


def cut(path, u0, u1):
    """The part of a polyline between fractions u0 and u1 of its length."""
    d = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:])]
    total = sum(d) or 1.
    out, run = [], 0.
    for (a, b), seg in zip(zip(path, path[1:]), d):
        s0, s1 = run / total, (run + seg) / total
        if s1 >= u0 and s0 <= u1 and seg:
            fa = max(0., (u0 - s0) * total / seg)
            fb = min(1., (u1 - s0) * total / seg)
            p = (a[0] + (b[0] - a[0]) * fa, a[1] + (b[1] - a[1]) * fa)
            q = (a[0] + (b[0] - a[0]) * fb, a[1] + (b[1] - a[1]) * fb)
            if not out:
                out.append(p)
            out.append(q)
        run += seg
    return out


# ------------------------------------------------------------------ the whiteboard hook
class Boards:
    """Draws every scene board of a plan on the whiteboard Production ``prod`` (render.Production)."""

    def __init__(self, prod, plan):
        self.prod, self.plan = prod, plan
        self.scene_of = {bid: i for i, scene in enumerate(plan['scenes']) if scene.get('boards')
                         for bid in scene['beat_ids']}
        palette = plan['style']['palette']
        self.colours = {k: ink.rgba(v)[:3] for k, v in palette.items()}
        self.built: dict[int, list] = {}

    def beats(self):
        return set(self.scene_of)

    # -- per beat
    def prepare(self, beat, not_before=0.):
        """Lay out the scene of ``beat`` (once), before any of its boards or markup boards is drawn."""
        index = self.scene_of.get(beat['id'])
        if index is not None and index not in self.built:
            self.built[index] = self._build(index, not_before)
        return index

    def draw(self, beat, not_before=0.):
        index = self.prepare(beat, not_before)
        prod = self.prod
        for page in self.built[index]:
            for k, (bid, start, add) in enumerate(page['adds']):
                if bid != beat['id']:
                    continue
                if k == 0 and not page.get('shared'):
                    prod.cut(page['start'], page['col'] * prod.g.col, 'cut')
                add()

    # -- per scene
    def _build(self, index, not_before):
        prod = self.prod
        scene = self.plan['scenes'][index]
        by_id = {b['id']: b for b in prod.ep['beats']}
        lang, tl = prod.lang, prod.tl
        scene_start = max(not_before, tl['beats'][scene['beat_ids'][0]]['start'])
        scene_end = max(tl['beats'][bid]['end'] for bid in scene['beat_ids'])
        pages = []
        boards = [self.sums(b, by_id, lang) for b in scene['boards'] if b['items']]
        marked = [k for k, bid in enumerate(scene['beat_ids']) if markup.board(by_id[bid], lang)]
        later = []
        if marked:
            # From a code, formula or warning beat on, its own board (markup_boards) stays on screen for the rest of
            # the scene: no labels restating the code, no camera trip back to this board. The items of the beats
            # after it (up to the next markup beat) go under it on its page (share).
            ids = scene['beat_ids']
            keep = set(ids[:marked[0]])
            after = set(ids[marked[0] + 1:marked[1] if len(marked) > 1 else len(ids)])
            later = [it for b in boards for it in b['items'] if it['beat_id'] in after]
            boards = [dict(b, items=[it for it in b['items'] if it['beat_id'] in keep]) for b in boards]
            boards = [b for b in boards if b['items']]
        times = []
        for board in boards:
            times.append([max(scene_start, cue_time(tl, by_id[it['beat_id']], it['cue'], lang)) for it in board['items']])
        for n, board in enumerate(boards):
            start = scene_start if n == 0 else times[n][0]
            end = times[n + 1][0] if n + 1 < len(boards) else scene_end
            box, (col, _) = prod.layout.page()
            pages.append(self._page(board, [max(start, t) for t in times[n]], start, end, box, col, by_id))
        if marked:
            ids = scene['beat_ids']
            until = tl['beats'][ids[marked[1]]]['start'] if len(marked) > 1 else scene_end
            pages += self.share(by_id[ids[marked[0]]], later, until, by_id)
        return pages

    def share(self, beat, items, end, by_id):
        """Give a markup beat's board (markup_boards) the top of a fresh page and lay ``items`` (the scene's later
        board items) out under it: what the narration says next is drawn while the code, formula or warning stays
        on screen. Without such items, or room for them, the board gets the whole page."""
        from .markup_boards import make
        prod, lang = self.prod, self.prod.lang
        ids = {it['id'] for it in items}
        items = [dict(it, to=it['to'] if it['to'] in ids else '') for it in items
                 if it['kind'] != 'link' or (it['ref'] in ids and it['to'] in ids)]
        box, (col, _) = prod.layout.page()
        x0, y0, w, h = box
        mark = markup.board(beat, lang)
        made = make(prod, beat, mark, w, h * .6) if items else None
        room = h - made[0].size[1] - .08 * h if made else 0
        if not items or room < .3 * h:
            prod.markup_pages = {**getattr(prod, 'markup_pages', {}),
                                 beat['id']: (box, col, made or make(prod, beat, mark, w, h))}
            return []
        top = h - room
        prod.markup_pages = {**getattr(prod, 'markup_pages', {}), beat['id']: ((x0, y0, w, top), col, made)}
        tl = prod.tl
        times = [max(tl['beats'][beat['id']]['end'], cue_time(tl, by_id[it['beat_id']], it['cue'], lang))
                 for it in items]
        board = {'layout': 'flow', 'items': items}
        page = self._page(board, times, times[0], end, (x0, y0 + top, w, room), col, by_id, scale=h / 738)
        page['shared'] = True
        return [page]

    def _text(self, words, size, colour, max_w, lines=3, quick=False):
        prod = self.prod
        fitted, size = ink.fit_text(words, prod.lang, max_w, lines, size, min_size=max(18, size * .6),
                                    fonts=prod.skin.fonts)
        return ink.TextDrawing(fitted, prod.lang, size, color=colour, fonts=prod.skin.fonts,
                               min_dur=.08 if quick else .5, max_dur=.12 if quick else 1.6)

    @staticmethod
    def sums(board, by_id, lang):
        """After a run of hops, the sum they make ('3 + 5 = 8'), written when the narration says the total it lands
        on ("You land on 8", "8 again"); every number in it is a number the script says."""
        out, run, starts, items = [], [], {}, board['items']
        for k, it in enumerate(items):
            out.append(it)
            if it['kind'] == 'number_line':
                starts[it['id']] = start_of(it['text'])
            size = hop_of(it['text']) if it['kind'] == 'hop' else None
            if size is None:
                continue
            run = [size] if it['style'] == 'restart' else run + [size]
            following = next((o for o in items[k + 1:] if o['kind'] == 'hop' and o['to'] == it['to']), None)
            if (following is not None and following['style'] != 'restart') or len(run) < 2 or starts.get(it['to']):
                continue
            total = sum(run)
            beat = by_id[it['beat_id']]
            text = beat['display'][lang] if isinstance(beat.get('display'), dict) else beat['spoken'][lang]
            after = text[(find(text, it['cue']) or 0) + len(it['cue']):]
            said = [w for w, v in NUMBERS.items() if v == total] + [str(total)]
            m = re.search(r'\b(?:' + '|'.join(map(re.escape, said)) + r')\b', after, re.I)
            if m:
                sign = lambda v: f'− {-v}' if v < 0 else f'+ {v}'
                written = f'{run[0]} ' + ' '.join(sign(v) for v in run[1:]) + f' = {total}'
                out.append({'id': it['id'] + '_sum', 'beat_id': it['beat_id'], 'cue': m.group(), 'kind': 'equation',
                            'ref': '', 'to': '', 'at': 'auto', 'text': written, 'style': 'none', 'raw': True})
        return dict(board, items=out)

    def _page(self, board, times, start, end, box, col, by_id, scale=None):
        prod = self.prod
        x0, y0, W, H = box
        s = scale or H / 738
        ink_c, accent, accent2 = self.colours['ink'], self.colours['accent'], self.colours['accent2']
        texts = {}

        def words(it):
            if it.get('raw'):
                return it['text']
            if it['kind'] == 'equation':
                return typeset(it['text']) if prod.lang in ('en', 'es') else it['text']
            return it['text']

        def measure(it, kind):
            key = (it['id'], kind)
            if key not in texts:
                size = {'equation': 54, 'title': 40}.get(kind, 36) * s
                if kind == 'equation' and it['to'] and any(o['id'] == it['to'] and o['style'] == 'box'
                                                           for o in board['items']):
                    size = 46 * s
                colour = accent if kind == 'title' else ink_c
                keys = markup.combos(it['text'].strip(' .,;:!?'))
                if keys and keys[0][0] == 0 and keys[0][1] == len(it['text'].strip(' .,;:!?')):
                    from .markup_boards import keycaps_drawing      # a key combo is drawn as its keys
                    texts[key] = keycaps_drawing(keys[0][2], min(prod.size[1], H * 1.46))
                    return texts[key].size
                texts[key] = self._text(words(it), round(size), colour, W * (.42 if kind != 'label' else .26))
            return texts[key].size

        doodles, lay_ground = {}, set()

        def picture_box(it, rect):
            drawing = prod.ctx.doodle(it['ref'], (round(rect.w), round(rect.h)))
            doodles[it['id']] = drawing
            bbox = (getattr(drawing, 'color', None) or Image.new('RGBA', (1, 1))).getbbox() or (0, 0, *drawing.size)
            ox = rect.x + (rect.w - drawing.size[0]) / 2
            oy = rect.y + rect.h - drawing.size[1] if it['id'] in lay_ground else rect.y + (rect.h - drawing.size[1]) / 2
            doodles[it['id'] + ':at'] = (ox, oy)
            return Rect(ox + bbox[0], oy + bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])

        # The renderer hides a text that comes closer than 4% of the frame to its edge (Production.text_visible);
        # the camera stands at the page's column, give or take its 12 px idle drift (Production._drift), so that
        # edge is this far inside the page.
        fw, fh = prod.size
        px = x0 - col * prod.layout.g.col
        margin = (max(0., fw * .04 - px, px + W - fw * .96) + 14, max(0., fh * .04 - y0, y0 + H - fh * .96) + 2)
        lay = Layout(board, W, H, measure, picture_box, lay_ground, margin)
        adds, width = [], max(3., 5 * s)
        deadline = end - .2
        items = board['items']
        first = {}
        hops_seen = []
        dots_drawings = {}
        link_paths = {}
        links = [it for it in items if it['kind'] == 'link']

        def add(drawing, x, y, at, it, hand=True, fixed=False, dress=True):
            def go(drawing=drawing):
                d = prod.skin.dress(drawing, x0 + x, y0 + y) if dress else drawing
                el = prod.ctx.add(d, x0 + x, y0 + y, at, essential=True, group=f'board:{col}:{it["id"]}',
                                  beat=it['beat_id'], deadline=max(at + .4, deadline), hand=hand, fixed=fixed)
                prod._visual_triggers[id(el)] = (el, at)
                return el
            adds.append((it['beat_id'], at, go))

        ground_drawn = False
        for k, (it, at) in enumerate(zip(items, times)):
            at = start if k == 0 else at
            kind = it['kind']
            if kind == 'picture' and it['id'] in doodles:
                rect = lay.place[it['id']]
                ox, oy = doodles[it['id'] + ':at']
                if lay.extra.get('ground_y') and not ground_drawn and it['id'] in lay_ground:
                    ground_drawn = True
                    gy = lay.extra['ground_y']
                    line = ink.stroke_drawing((W, H), [[(W * .01, gy), (W * .99, gy)]], color=ink_c, width=width,
                                              min_dur=.4, max_dur=.8)
                    add(line, 0, 0, at, it)
                add(doodles[it['id']], ox, oy, at, it)
                if it['text']:
                    self._label(add, lay, it, at, texts, measure, ink_c, width, key=it['id'] + ':label')
            elif kind in ('label', 'equation'):
                rect = lay.place.get(it['id'])
                if rect is None:
                    continue
                kind_key = 'title' if (kind == 'label' and it['style'] == 'box') else kind
                if kind_key == 'title':
                    outer = lay.extra[it['id'] + ':box']
                    corners = rounded(outer.x, outer.y, outer.w, outer.h, H * .03)
                    add(ink.stroke_drawing((W, H), [corners], color=accent, width=width * .8, min_dur=.5, max_dur=.9),
                        0, 0, at, it)
                measure(it, kind_key)
                drawing = texts[(it['id'], kind_key)]
                add(drawing, rect.x, rect.y, at, it)
                leader = lay.extra.get('leaders', {}).get(it['id'])
                if leader is not None:
                    a = edge_point(rect, (leader.cx, leader.cy))
                    b = edge_point(leader, (rect.cx, rect.cy))
                    add(ink.stroke_drawing((W, H), [[a, b]], color=ink_c, width=width * .6, min_dur=.25, max_dur=.5),
                        0, 0, at, it)
            elif kind == 'charges':
                area = lay.place.get(it['id'])
                if area is None:
                    continue
                sign = '+' if it['style'] == 'plus' else '−'
                colour = (205, 62, 62) if sign == '+' else (44, 104, 196)
                add(self._charges(area, sign, colour, W, H, width), 0, 0, at, it)
                if it['text']:
                    self._label(add, lay, it, at, texts, measure, ink_c, width, key=it['id'] + ':label')
            elif kind == 'link':
                a, b = lay.place.get(it['ref']), lay.place.get(it['to'])
                if a is None or b is None:
                    continue
                p, q = edge_point(a, (b.cx, b.cy)), edge_point(b, (a.cx, a.cy))
                back = next((o for o in links if o['ref'] == it['to'] and o['to'] == it['ref']), None)
                path = self._path(p, q, it['style'], H)
                u = 1.
                if back is not None:
                    u = .62 if items.index(it) < items.index(back) else .38
                    whole = link_paths.get(back['id'] + ':whole')
                    path = (cut(list(reversed(whole)), 0., u) if whole else cut(path, 0., u))
                link_paths[it['id']] = path
                link_paths[it['id'] + ':whole'] = self._path(p, q, it['style'], H)
                colour = accent2 if it['style'] == 'zigzag' else ink_c
                polys = self._dashes(path) if it['style'] == 'dashed' else [path]
                if it['style'] in ('straight', 'curved', 'dashed', 'none') and u == 1.:
                    polys.append(arrow_head(path[-2], path[-1], H * .03))
                add(ink.stroke_drawing((W, H), polys, color=colour, width=width, min_dur=.6, max_dur=1.6), 0, 0, at, it)
                if it['text']:
                    self._label(add, lay, it, at, texts, measure, ink_c, width, key=it['id'] + ':label')
            elif kind == 'rings':
                target = lay.place.get(it['to'])
                if target is None:
                    continue
                path = link_paths.get(it['to'] + ':whole')
                centre = (target.cx, target.cy)
                if path:
                    centre = path[len(path) // 2]
                add(Rings((W, H), centre, H * .06, H * .48, accent, max(3, round(width))), 0, 0, at, it,
                    hand=False, fixed=True, dress=False)
                if it['text']:
                    self._label(add, lay, it, at, texts, measure, ink_c, width, key=it['id'] + ':label')
            elif kind == 'highlight':
                target = it['to']
                path = link_paths.get(target + ':whole')
                if path:
                    drawing = ink.stroke_drawing((W, H), [path], color=accent, width=width * 1.8, min_dur=.3, max_dur=.6)
                elif target in lay.place:
                    r = lay.place[target]
                    drawing = ink.stroke_drawing((W, H), [ink.circle_points(r.cx, r.cy, r.w * .62, r.h * .66)],
                                                 color=accent, width=width, min_dur=.4, max_dur=.8)
                else:
                    continue
                add(drawing, 0, 0, at, it)
            elif kind == 'number_line':
                geo = lay.extra.get(it['id'])
                if not geo:
                    continue
                xs = [geo['x0'] + (geo['x1'] - geo['x0']) * k / geo['ticks'] for k in range(geo['ticks'] + 1)]
                polys = [[(geo['x0'] - H * .02, geo['y']), (geo['x1'] + H * .02, geo['y'])]]
                polys += [[(x, geo['y'] - H * .02), (x, geo['y'] + H * .02)] for x in xs]
                add(ink.stroke_drawing((W, H), polys, color=ink_c, width=width, min_dur=.6, max_dur=1.2), 0, 0, at, it)
                for k, x in enumerate(xs):
                    digit = self._text(str(geo['start'] + k), round(30 * s), ink_c, W, quick=True)
                    add(digit, x - digit.size[0] / 2, geo['y'] + H * .03, at, it)
            elif kind == 'hop':
                line = next((o for o in items if o['id'] == it['to']), None)
                geo = lay.extra.get(it['to'])
                size = hop_of(it['text'])
                if not geo or size is None or line is None:
                    continue
                if it['style'] == 'restart':
                    for previous in hops_seen:
                        previous.dim_at = at
                    pos = geo['start']
                    hops_seen.append('restart')
                else:
                    pos = geo.get('pos', geo['start'])
                geo['pos'] = pos + size
                magnitudes = geo.setdefault('magnitudes', [])
                if abs(size) not in magnitudes:
                    magnitudes.append(abs(size))
                colour = (accent2, accent)[magnitudes.index(abs(size)) % 2]
                step = (geo['x1'] - geo['x0']) / geo['ticks']
                a = geo['x0'] + (pos - geo['start']) * step
                b = geo['x0'] + (geo['pos'] - geo['start']) * step
                height = hop_height(abs(b - a), H, 'restart' in hops_seen)
                arc = [(a + (b - a) * u, geo['y'] - H * .02 - height * math.sin(math.pi * u)) for u in
                       [k / 24 for k in range(25)]]
                polys = [arc, arrow_head(arc[-3], arc[-1], H * .028)]
                timed = Timed(prod.skin.dress(ink.stroke_drawing((W, H), polys, color=colour, width=width * 1.1,
                                                                 min_dur=.6, max_dur=1.1), x0, y0))
                hops_seen.append(timed)
                add(timed, 0, 0, at, it, dress=False)
                tag = self._text(f'{size:+d}', round(34 * s), colour, W)
                tag_t = Timed(prod.skin.dress(tag, x0, y0))
                hops_seen.append(tag_t)
                add(tag_t, (a + b) / 2 - tag.size[0] / 2, geo['y'] - H * .02 - height - tag.size[1] * 1.05, at, it,
                    dress=False)
                landing = ink.stroke_drawing((W, H), [[(b, geo['y'])]], color=colour, width=H * .03, min_dur=.2,
                                             max_dur=.3)
                land_t = Timed(prod.skin.dress(landing, x0, y0))
                hops_seen.append(land_t)
                add(land_t, 0, 0, at + .05, it, dress=False)
            elif kind == 'dots':
                geo = lay.extra.get(it['id'])
                if not geo:
                    continue
                box_ = geo['box']
                local = (geo['center'][0] - box_.x, geo['center'][1] - box_.y)
                radius = geo['spacing'] * .28
                outlines = [ink.circle_points(x, y, radius, radius, n=20)
                            for x, y in dot_positions(geo['rows'], geo['cols'], geo['spacing'], local, 0.)]
                inner = ink.stroke_drawing((round(box_.w), round(box_.h)), outlines, color=accent, width=width * .8,
                                           min_dur=.8, max_dur=2.0)
                dots = Dots(inner, geo['rows'], geo['cols'], geo['spacing'], local, accent)
                dots_drawings[it['id']] = dots
                add(dots, box_.x, box_.y, at, it, dress=False)
            elif kind == 'rotate':
                dots = dots_drawings.get(it['to'])
                if dots is not None:
                    dots.turn_at = at
            first.setdefault(it['id'], at)
        adds.sort(key=lambda entry: entry[1])
        return {'adds': adds, 'start': start, 'col': col}

    def _label(self, add, lay, it, at, texts, measure, colour, width, key=None):
        key = key or it['id']
        rect = lay.place.get(key)
        if rect is None:
            rect = lay.take(key, lay._callout(dict(it, at='auto'), lay.place[it['id']], measure(it, 'label')))
        measure(it, 'label')
        add(texts[(it['id'], 'label')], rect.x, rect.y, at, it)
        leader = lay.extra.get('leaders', {}).get(key)
        if leader is not None:
            a, b = edge_point(rect, (leader.cx, leader.cy)), edge_point(leader, (rect.cx, rect.cy))
            add(ink.stroke_drawing((lay.W, lay.H), [[a, b]], color=colour, width=width * .6, min_dur=.25, max_dur=.5),
                0, 0, at, it)

    @staticmethod
    def _charges(area, sign, colour, W, H, width):
        r = charge_radius(area, H)
        cols = max(1, min(5, int(area.w // (r * 2.8))))
        rows = max(1, min(3, int(area.h // (r * 2.8))))
        n = max(2, min(9, cols * rows))
        rows = math.ceil(n / cols)
        polys = []
        for k in range(n):
            row, c = divmod(k, cols)
            x = area.x + area.w * (c + .5 + (.25 if row % 2 else 0)) / (cols + .25)
            y = area.y + area.h * (row + .5) / rows
            polys.append(ink.circle_points(x, y, r, r, n=24))
            polys.append([(x - r * .55, y), (x + r * .55, y)])
            if sign == '+':
                polys.append([(x, y - r * .55), (x, y + r * .55)])
        return ink.stroke_drawing((W, H), polys, color=colour, width=max(2.5, width * .7), min_dur=.6, max_dur=1.4)

    @staticmethod
    def _path(p, q, style, H):
        if style == 'zigzag':
            length = math.hypot(q[0] - p[0], q[1] - p[1])
            return zigzag(p, q, max(4, round(length / (H * .06))), H * .025)
        if style == 'curved':
            mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            dx, dy = q[0] - p[0], q[1] - p[1]
            c = (mx - dy * .25, my + dx * .25)
            return [((1 - u) ** 2 * p[0] + 2 * (1 - u) * u * c[0] + u * u * q[0],
                     (1 - u) ** 2 * p[1] + 2 * (1 - u) * u * c[1] + u * u * q[1]) for u in [k / 20 for k in range(21)]]
        return [p, q]

    @staticmethod
    def _dashes(path):
        out, total = [], sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
        n = max(3, round(total / 40))
        for k in range(n):
            if k % 2 == 0:
                part = cut(path, k / n, (k + 1) / n)
                if len(part) > 1:
                    out.append(part)
        return out


def rounded(x, y, w, h, r):
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for k in range(7):
            a = math.radians(a0 + 15 * k)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return pts

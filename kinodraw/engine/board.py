"""Board model: elements on a continuous world strip, layout, one-hand scheduling, camera.

World coordinates: x grows to the right along one long strip; y is screen y.
The screen shows 3 columns of 640 px; the camera's left edge ``L`` is always a
column boundary at rest, so no item is ever cut by the frame edge.

Scheduling rules (every video, whatever the director planned):
- nothing appears without the hand: each drawing starts at or after its trigger
  and plays in full on screen;
- the camera moves only by smooth pans from where it is (hard cuts happen only
  under a zoom or fade), leaves a page only after the hand has finished there,
  and never goes back to a page it has left;
- a drawing that could not start within ``STALE`` seconds of its words, or would
  hold the next page up by more than ``CUT_GRACE``, is skipped rather than drawn
  late; so is anything optional that would miss its deadline, and anything left of
  the screen once the camera has moved on (the camera never pans back).
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

COL = 640
COLS_ON_SCREEN = 3
CELL_X0, CELL_W = 50, 540          # cell inside a column: x 50..590
ROW_Y = [(84, 440), (466, 822)]    # two rows; captions start below ~865
PAGE_BOX = (60, 84, 1800, 738)     # page scene box within a 3-column screen
PAN_SECONDS = .9
STALE = 3.0                        # max seconds between a visual's words and its first stroke
CUT_GRACE = 1.5                    # max seconds a page change waits for unfinished drawing
SETTLE = .35                       # the camera leaves a page this long after its last stroke


@dataclass(eq=False)
class Element:
    drawing: object
    x: float
    y: float
    trigger: float
    hand: bool = True
    layer: int = 0
    group: str = ''
    fixed: bool = False            # start exactly at trigger (transitions)
    after: 'Element | None' = None  # start no earlier than this one's end
    start: float | None = None
    hidden_after: float | None = None
    rate: float = 1.0               # >1 plays the drawing faster (hand catching up)
    hold: float = 1.2               # seconds it should stay on screen after finishing
    stretch: int = 0                # camera stop (page) the element is drawn on; see Production.cut
    essential: bool = False         # titles, agenda, openers, takeaway notes: never skipped
    optional: bool = False          # decoration: skipped first when time is short
    deadline: float | None = None   # must be finished by then (a transition follows)
    skipped: bool = False           # not drawn at all (too late to be useful)
    beat: str = ''                  # the beat whose visual this is (pacing), '' for automatic scenes

    @property
    def duration(self):
        return self.drawing.duration / self.rate

    @property
    def end(self):
        return (self.start or 0) + self.duration

    @property
    def w(self):
        return self.drawing.size[0]

    @property
    def h(self):
        return self.drawing.size[1]

    def bbox(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def state(self, t):
        if self.start is None or t < self.start:
            return None, None, False
        if self.hidden_after is not None and t >= self.hidden_after:
            return None, None, False
        return self.drawing.state((t - self.start) * self.rate)


class Layout:
    """Column-major slot allocator on the world strip (2 rows per column)."""

    def __init__(self):
        self.used = {}            # column -> set(rows)
        self.cursor = 0           # first column that may still take items
        self.page_start = 0

    def _free(self, col, row):
        return row not in self.used.get(col, set())

    def _take(self, col, row):
        self.used.setdefault(col, set()).add(row)

    def next_fresh_column(self):
        """First column after everything used so far."""
        return max([self.cursor] + [c + 1 for c, rows in self.used.items() if rows])

    def new_page(self):
        col = self.next_fresh_column()
        self.cursor = col
        self.page_start = col
        return col

    def slot(self, rows_needed=1):
        col = self.cursor
        while True:
            if rows_needed == 2:
                if self._free(col, 0) and self._free(col, 1):
                    self._take(col, 0), self._take(col, 1)
                    self.cursor = col
                    return self.cell_box(col, 0, rows=2), (col, col)
            else:
                for row in (0, 1):
                    if self._free(col, row):
                        self._take(col, row)
                        self.cursor = col
                        return self.cell_box(col, row), (col, col)
            col += 1

    def wide(self):
        col = self.cursor
        while True:
            for row in (0, 1):
                if self._free(col, row) and self._free(col + 1, row):
                    self._take(col, row), self._take(col + 1, row)
                    self.cursor = col
                    x0 = col * COL + CELL_X0
                    y0, y1 = ROW_Y[row]
                    return (x0, y0, COL + CELL_W, y1 - y0), (col, col + 1)
            col += 1

    def page(self):
        col = self.next_fresh_column()
        for c in range(col, col + COLS_ON_SCREEN):
            self._take(c, 0), self._take(c, 1)
        self.cursor = col + COLS_ON_SCREEN
        x, y, w, h = PAGE_BOX
        return (col * COL + x, y, w, h), (col, col + COLS_ON_SCREEN - 1)

    def reserve(self, col_from, col_to):
        for c in range(col_from, col_to + 1):
            self._take(c, 0), self._take(c, 1)
        self.cursor = col_to + 1

    @staticmethod
    def cell_box(col, row, rows=1):
        x0 = col * COL + CELL_X0
        y0 = ROW_Y[row][0]
        y1 = ROW_Y[row + rows - 1][1]
        return (x0, y0, CELL_W, y1 - y0)


class Camera:
    """Piecewise camera: left edge L(t) in world px; pans ease over PAN_SECONDS.

    A pan always starts from wherever the camera actually is at that moment (even
    mid-pan), so the camera never jumps, whatever order the moves were added in.
    """

    def __init__(self):
        self.keys = [(0.0, 0.0, 'cut')]   # (t_start, to_L, 'cut' | 'pan')
        self._segs = None

    def _segments(self):
        """[(t_start, from_L, to_L, kind)] in time order, each pan chained from the real position."""
        if self._segs is None:
            segs = []
            for t0, L, kind in sorted(self.keys, key=lambda k: k[0]):
                a = L if kind == 'cut' or not segs else self._eval(segs[-1], t0)
                segs.append((t0, a, L, kind))
            self._segs, self._starts = segs, [s[0] for s in segs]
        return self._segs

    @staticmethod
    def _eval(seg, t):
        t0, a, b, _ = seg
        if a == b:
            return b
        f = min(1., max(0., (t - t0) / PAN_SECONDS))
        return a + (b - a) * f * f * (3 - 2 * f)

    def at(self, t):
        segs = self._segments()
        i = bisect.bisect_right(self._starts, t) - 1
        return self._eval(segs[max(i, 0)], t)

    def target_at(self, t):
        cur = self.keys[0][1]
        for t0, L, _ in sorted(self.keys, key=lambda k: k[0]):
            if t < t0:
                break
            cur = L
        return cur

    def cut(self, t, L):
        self.keys.append((t, L, 'cut'))
        self._segs = None

    def pan(self, t, L):
        if self.target_at(t) != L:
            self.keys.append((t, L, 'pan'))
            self._segs = None


def column_span(el):
    return int(el.x // COL), int(max(el.x, el.x + el.w - 1) // COL)


class Scheduler:
    """One hand: drawings happen one at a time, never before their trigger (rules: module docstring)."""

    def __init__(self, camera: Camera):
        self.camera = camera

    def run(self, elements, cuts, max_rate=2.0, stale=STALE, cut_grace=CUT_GRACE):
        """Place every element in time and move the camera.

        ``cuts[k] = (t, L, 'cut' | 'pan')`` brings the camera to stretch k (a page, or a run of
        columns the board scrolls through); ``element.stretch`` is the stretch it is drawn on.
        Drawings are scheduled as units (elements of one stretch sharing a trigger), one hand at
        a time. A unit plays at natural speed when it can finish before the next unit's trigger
        and the next page change; otherwise the whole unit speeds up just enough (<= max_rate),
        so the board keeps pace with the narration without scribbling. (Pacing measures with
        ``max_rate=1`` and no skipping: how long every drawing would really take.)
        """
        cam = self.camera
        for _ in range(3):                                  # a drawing that follows another is never due before it
            for e in elements:
                if e.after is not None and not e.fixed:
                    e.trigger = max(e.trigger, e.after.trigger + .01)
        fixed = [e for e in elements if e.fixed]
        for e in fixed:
            e.start = e.trigger
        fixed_busy = sorted((e.start, e.end) for e in fixed if e.hand)
        order = sorted((i for i, e in enumerate(elements) if not e.fixed),
                       key=lambda i: (elements[i].stretch, round(elements[i].trigger, 2), i))
        units = []
        for i in order:
            e = elements[i]
            key = (e.stretch, round(e.trigger, 2))
            if units and units[-1][0] == key:
                units[-1][1].append(e)
            else:
                units.append((key, [e]))
        planned = [t for t, _, _ in cuts]
        # The next trigger that is a real moment in the narration: units that only follow another
        # drawing (``after``: a note's face, its margin doodles) do not hurry the unit before them.
        next_trig, upcoming = [0.] * len(units), math.inf
        for k in range(len(units) - 1, -1, -1):
            next_trig[k] = upcoming
            if not all(e.after is not None for e in units[k][1]):
                upcoming = units[k][0][1]
        hand_free, last_pen = -1e9, None
        placed, started, dropped = [], set(), set()
        state = {'stretch': -1, 'arrive': 0., 'base': 0}

        def enter(s):
            """Move the camera on to stretch ``s`` (and any empty ones before it)."""
            while state['stretch'] < s:
                state['stretch'] += 1
                t, L, mode = cuts[state['stretch']]
                if mode == 'pan':
                    t = max(t, hand_free + SETTLE)          # never leave a page mid-stroke
                    cam.pan(t, L)
                    state['arrive'] = t + PAN_SECONDS
                else:
                    cam.cut(t, L)
                    state['arrive'] = t
                state['base'] = int(round(L / COL))

        for k, ((s, trig), els) in enumerate(units):
            enter(s)
            arrive, base = state['arrive'], state['base']
            page_change = planned[s + 1] if s + 1 < len(planned) else math.inf
            if s + 1 < len(cuts) and cuts[s + 1][2] == 'cut':   # a zoom/fade takes this page away: finish first
                for e in els:
                    e.deadline = min(page_change - SETTLE, e.deadline if e.deadline is not None else math.inf)
            nxt = max(trig, min(next_trig[k], trig + 60))
            deadline = min([e.deadline for e in els if e.deadline is not None] or [math.inf])
            start = max(trig, hand_free + .15, arrive)
            natural, pos = 0., last_pen                     # natural length of the unit
            for e in els:
                if e.hand and not self._gone(e, dropped):
                    d = .12 if pos is None else min(.3, .08 + math.dist(pos, (e.x, e.y)) / 5000)
                    natural += d + e.drawing.duration
                    pos = (e.x + e.w, e.y + e.h / 2)
            window = max(.1, min(nxt, page_change, deadline) - start - .1)
            rate = 1.0 if natural <= window else min(max_rate, natural / window)
            if all(e.optional for e in els) and start + natural / rate > deadline:
                for e in els:                               # decoration that cannot all fit: none of it
                    dropped.add(e.group or id(e))
                    e.skipped = True
                continue
            cursor = start
            for e in els:
                key = e.group or id(e)
                c0, c1 = column_span(e)
                if self._gone(e, dropped) or c1 < base:     # its page is behind the camera: never go back
                    dropped.add(key)
                    e.skipped = True
                    continue
                earliest = max(cursor, e.trigger, arrive)
                due = e.trigger                             # when it becomes relevant
                if e.after is not None and e.after.start is not None:
                    earliest = max(earliest, e.after.end)
                    due = max(due, e.after.end)
                for a, b in fixed_busy:                     # never overlap a fixed transition drawing
                    if e.hand and a - .05 < earliest < b:
                        earliest = b + .1
                pan_at, new_col = None, None
                L_cols = int(round(cam.target_at(earliest) / COL))
                if c0 < L_cols and not e.essential:
                    dropped.add(key)                        # the camera has moved past it: never pan back
                    e.skipped = True
                    continue
                if c0 < L_cols or c1 > L_cols + COLS_ON_SCREEN - 1:
                    # a page shows whole; a slot scrolls into view (never left of the page's start)
                    new_col = base if c1 <= base + COLS_ON_SCREEN - 1 else max(c0, c1 - COLS_ON_SCREEN + 1)
                    # Dwell: let what is on screen be read before panning away
                    # (charts ~2.5 s, glossary notes ~5 s after they finish).
                    lo_col, hi_col = L_cols, L_cols + COLS_ON_SCREEN - 1
                    dwell = [x.end + x.hold for x in placed[-40:]
                             if column_span(x)[1] >= lo_col and column_span(x)[0] <= hi_col]
                    pan_at = max(earliest, min(max(dwell), earliest + 3.5)) if dwell else earliest
                    earliest = pan_at + PAN_SECONDS
                e_rate = rate if e.hand else 1.0
                if e.hand:
                    travel = .12 if last_pen is None else min(.3, .08 + math.dist(last_pen, (e.x, e.y)) / 5000)
                    earliest = max(earliest, hand_free + travel / e_rate)
                end = earliest + e.drawing.duration / e_rate
                late = earliest - due > stale
                holds_page = end > page_change + cut_grace
                misses = e.deadline is not None and end > e.deadline
                fresh = key not in started                  # a visual is judged when it would start
                if not e.essential and ((fresh and (late or holds_page or misses)) or (e.optional and misses)):
                    dropped.add(key)                        # too late to help: skip it, never pop it in
                    e.skipped = True
                    continue
                if misses:                                  # essential (or already half drawn): hurry
                    e_rate = max(e_rate, min(4.0, e.drawing.duration / max(.05, e.deadline - earliest)))
                if pan_at is not None:
                    cam.pan(pan_at, new_col * COL)
                e.rate, e.start = e_rate, earliest
                started.add(key)
                placed.append(e)
                if e.hand:
                    hand_free = e.end
                    last_pen = (e.x + e.w, e.y + e.h / 2)
                    cursor = e.end
                else:
                    cursor = max(cursor, earliest)
        enter(len(cuts) - 1)
        return elements

    @staticmethod
    def _gone(e, dropped):
        return (e.group or id(e)) in dropped or (e.after is not None and e.after.skipped)


@dataclass
class HandTrack:
    """Where the hand is at time t (screen coords resolved by the caller)."""
    events: list = field(default_factory=list)  # (start, end, element)

    @classmethod
    def build(cls, elements):
        ev = sorted(((e.start, e.end, e) for e in elements if e.hand and e.start is not None), key=lambda x: x[0])
        return cls(ev)

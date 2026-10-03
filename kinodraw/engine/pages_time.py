"""Time-shaped page builders: ``lanes`` (two-lane timeline), ``range`` (number
line between a stated low and high) and ``calendar`` (dated day cards plus an
open-ended rail).

Emphasis keys registered (``<visual id>.<key>``):
- lanes: ``<n>`` = n-th event in reading order (lane 0 events, then lane 1 ...),
  ``lane<i>`` = a whole lane, ``all``.
- range: ``<n>`` = n-th mark, ``min``, ``max``, ``callout``, ``all``.
- calendar: ``<i>`` = i-th day card, ``<i>-<j>`` = item j of day i,
  ``open`` = the open rail, ``open<j>`` = open item j, ``all``.
Only display strings from the visual are written; no numbers are computed.
"""
from __future__ import annotations

import math
import re

import numpy as np

from . import ink
from .scenes import SOFT_INK, arrow_polys, dot, footnote, mix, page_title, sticky

CARD = (255, 255, 252)
GUIDE = (150, 150, 150)
LANE_ACCENTS = [None, (120, 144, 156), (142, 36, 170)]   # None = chapter colour
_GLUE_AFTER = ('→', '(', '（', '≥', '≤', '<', '>', '~', '≈', '“', '「')
_GLUE_BEFORE = ('→', ')', '）', '，', '。', '、', '：', '；', '！', '？', '%', '”', '」')
_UNIT = re.compile(r'[亿万年月日倍个%％比至到]')
_NUM_PREFIX = tuple('年月近约超逾仅达至到比第')


# ------------------------------------------------------------------ helpers
def _block_h(lang, size, n):
    asc, desc = ink.hand_font(lang, size).getmetrics()
    return int(size * 1.18) * (n - 1) + asc + desc + 12


def _atoms(s, lang):
    """Wrap units that never split across lines: '$80 → $150', '280 亿', '30 年期', '（≥ 40 亿'."""
    units = re.findall(r'\S+\s*', s) if lang == 'en' else re.findall(r"[A-Za-z0-9$.,%×\-–/+']+\s*|.", s)
    atoms, glue = [], False
    for u in units:
        st = u.strip()
        if not st:
            if atoms:
                atoms[-1] += u
            continue
        prev = atoms[-1].rstrip() if atoms else ''
        if atoms and (glue or st.startswith(_GLUE_BEFORE) or (_UNIT.match(st) and prev[-1:].isdigit())
                      or (st[0] == '期' and prev.endswith('年'))
                      or (lang == 'zh' and st[0] in '0123456789$' and prev.endswith(_NUM_PREFIX))):
            atoms[-1] += u
        else:
            atoms.append(u)
        glue = st.endswith(_GLUE_AFTER)
    return atoms


def _wrap(s, lang, size, max_w):
    lines, cur = [], ''
    for a in _atoms(s, lang):
        if cur and ink.text_width((cur + a).rstrip(), lang, size) > max_w:
            lines.append(cur.rstrip())
            cur = a
        else:
            cur += a
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or ['']


def _cjk_splits(lines):
    """Line breaks that cut a run of Chinese characters (not at punctuation)."""
    return sum(1 for a, b in zip(lines, lines[1:])
               if a and b and ink.is_cjk(a[-1]) and ink.is_cjk(b[0])
               and a[-1] not in '，。、：；！？）」”' and b[0] not in '（「“')


def fit(ctx, s, size, max_w, max_h=None, max_lines=3, min_size=30, color=None, align='left', pace=1.0):
    """Handwritten block: largest size (>= min_size) whose unsplittable-unit wrap fits
    max_w x max_h in max_lines, balanced (narrowest width, same line count). For
    Chinese, up to two sizes smaller are tried to avoid cutting a word mid-run."""
    lang = ctx.lang

    def fits(lines, sz):       # an unsplittable unit wider than max_w also means "smaller"
        return (len(lines) <= max_lines and (max_h is None or _block_h(lang, sz, len(lines)) <= max_h)
                and max(ink.text_width(ln, lang, sz) for ln in lines) <= max_w)

    choice, rank = None, 0
    for sz in range(int(size), int(min_size) - 1, -2):
        lines = _wrap(s, lang, sz, max_w)
        ok = fits(lines, sz)
        if not ok and sz - 2 >= min_size:
            continue
        cands = [lines]
        for frac in np.linspace(.95, .45, 11):
            cand = _wrap(s, lang, sz, max_w * frac)
            if len(cand) != len(lines):
                break
            cands.append(cand)
        for cand in cands:                      # later = narrower; ties keep the narrower
            key = (_cjk_splits(cand), rank)
            if choice is None or key <= choice[0]:
                choice = (key, cand, sz)
        rank += 1
        if choice[0][0] == 0 or rank >= 3 or not ok:
            break
    _, lines, sz = choice
    grow = 1.1
    while len(lines) > max_lines and grow < 4:   # nothing fits: keep the line count, run wider
        lines, grow = _wrap(s, lang, sz, max_w * grow), grow + .1
    td = ink.TextDrawing(lines, lang, sz, color=color or ink.INK, align=align, pace=pace)
    td.fsize = sz
    return td


def rrect(w, h, r=22, inset=4, top_only=False):
    """Closed rounded-rectangle polyline in a (w, h) frame."""
    a, b, c, d = inset, inset, w - inset, h - inset
    r = min(r, (c - a) / 2, (d - b) / 2)
    pts = []

    def arc(cx, cy, a0, a1):
        for k in range(9):
            t = a0 + (a1 - a0) * k / 8
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    arc(a + r, b + r, math.pi, 1.5 * math.pi)
    arc(c - r, b + r, 1.5 * math.pi, 2 * math.pi)
    if top_only:
        pts += [(c, d), (a, d)]
    else:
        arc(c - r, d - r, 0, .5 * math.pi)
        arc(a + r, d - r, .5 * math.pi, math.pi)
    pts.append(pts[0])
    return pts


def dashes(x0, y0, x1, y1, on=16, off=12):
    length = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(length // (on + off)))
    out = []
    for k in range(n + 1):
        a = k * (on + off) / length
        b = min(1., (k * (on + off) + on) / length)
        if a >= 1:
            break
        out.append([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)])
    return out


def _time(ctx, beat, item, fallback):
    return ctx.time_of(beat, item.get('trigger')) if item.get('trigger') else fallback


def _spread(centers, widths, lo, hi, gap=36):
    """1-D label repel: left edges near their centres, no overlap, inside [lo, hi]."""
    order = sorted(range(len(centers)), key=lambda i: centers[i])
    left = {i: min(max(centers[i] - widths[i] / 2, lo), hi - widths[i]) for i in order}
    for a, b in zip(order, order[1:]):
        left[b] = max(left[b], left[a] + widths[a] + gap)
    if order and left[order[-1]] + widths[order[-1]] > hi:
        left[order[-1]] = hi - widths[order[-1]]
        for a, b in zip(reversed(order[:-1]), reversed(order[1:])):
            left[a] = min(left[a], left[b] - gap - widths[a])
    return [max(lo, left[i]) for i in range(len(centers))]


def _on_color(c):
    """Ink or white text on a filled colour, whichever contrasts more."""
    def lum(col):
        v = [x / 255 for x in col[:3]]
        v = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in v]
        return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]
    L = lum(c)
    return (255, 255, 255) if 1.05 / (L + .05) >= (L + .05) / (lum(ink.INK) + .05) else ink.INK


# ------------------------------------------------------------------ lanes
def build_lanes(v, beat, box, ctx):
    """Swim-lane timeline: stated events on ordinal positions, no path between them."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    lanes = (v.get('lanes') or [])[:3]
    bottom = y0 + h - (56 if v.get('footnote') else 0) - 6
    nl = max(1, len(lanes))
    gap = 20 if nl < 3 else 12
    lane_h = (bottom - top - gap * (nl - 1)) / nl
    labelled = any(ctx.T(ln.get('label')).strip() for ln in lanes)
    lab_w = 340 if labelled else 0                    # unlabelled lanes: the line runs the whole card
    lx0, lx1 = x0 + lab_w + 44, x0 + w - 24          # arrow span
    px0, px1 = lx0 + 70, lx1 - 90                     # where pos 0..1 lands
    date_size = 52 if lane_h >= 250 else 44
    date_h = _block_h(ctx.lang, date_size, 1)
    everything, events, line_y, blocks, below, lane_t, tints = [], [], {}, {}, {}, {}, {}
    # Event times first (untriggered events follow the previous one); never before the title.
    lane_evs, lane_ts, t_prev = [], [], t0 + .2
    for lane in lanes:
        evs = sorted(lane.get('events') or [], key=lambda e: float(e.get('pos', 0)))
        ts = []
        for ev in evs:
            ts.append(max(t0, _time(ctx, beat, ev, t_prev + .5)))
            t_prev = max(t_prev, ts[-1])
        lane_evs.append(evs)
        lane_ts.append(ts)
    # Lanes appear top to bottom, each by its own first event (or its lane trigger, else once
    # the lane above has its first event), so no lane or event is drawn before the title.
    t_lane = t0
    for i, lane in enumerate(lanes):
        tl = t0 + .2 * i
        if i and lane_ts[i - 1]:
            tl = max(tl, min(lane_ts[i - 1]) + .05)
        if lane.get('trigger'):
            tl = ctx.time_of(beat, lane['trigger'])
        if lane_ts[i]:
            tl = min(tl, min(lane_ts[i]) - .01)
        t_lane = lane_t[i] = max(t_lane, tl)
        lane_ts[i] = [max(te, t_lane) for te in lane_ts[i]]
    # Every event of every lane gets the room between its neighbours, so a label sits over its
    # own dot; one date size and one label size for the whole page.
    lane_xs = [[px0 + min(1., max(0., float(e.get('pos', 0)))) * (px1 - px0) for e in evs] for evs in lane_evs]
    room = []
    for xs in lane_xs:
        rr = []
        for j, x in enumerate(xs):
            left = x - xs[j - 1] - 24 if j else 2 * (x - (lx0 - 10))
            right = xs[j + 1] - x - 24 if j + 1 < len(xs) else 2 * (lx1 - 30 - x)
            rr.append(max(220, min(660, left, right)))
        room.append(rr)
    body_max_h = lane_h - date_h - 44

    def uniform(key, size, **kw):
        def one(ev, r, sz, lo):
            d = fit(ctx, ctx.T(ev.get(key)), sz, r, min_size=lo, **kw)
            if kw.get('max_h') and d.size[1] > kw['max_h']:   # too tall even at 40 px: run wider instead
                d = fit(ctx, ctx.T(ev.get(key)), sz, r * 1.6, min_size=lo, **kw)
            return d
        first = [[one(ev, r, size, 40) for ev, r in zip(evs, rr)] for evs, rr in zip(lane_evs, room)]
        sz = min([d.fsize for row in first for d in row] or [size])
        return [[one(ev, r, sz, sz) for ev, r in zip(evs, rr)] for evs, rr in zip(lane_evs, room)]
    all_dates = uniform('display', date_size, max_lines=1, color=ctx.color, align='center')
    all_bodies = uniform('label', 44, max_h=body_max_h, max_lines=3, align='center', pace=1.2)
    heads = [fit(ctx, ctx.T(ln.get('label')), 50, lab_w - 50, max_h=lane_h - 30, max_lines=3, min_size=40)
             for ln in lanes] if labelled else []
    head_sz = min([hd.fsize for hd in heads] or [50])
    k = 0
    for i, lane in enumerate(lanes):
        by = top + i * (lane_h + gap)
        accent = LANE_ACCENTS[i % len(LANE_ACCENTS)] or ctx.color
        tl = lane_t[i]
        tints[i] = mix(accent, .86)
        band_pts = rrect(w - 8, lane_h, r=26)
        band = ctx.add(ctx.strokes((w - 8, lane_h), [band_pts], color=mix(accent, .45), width=4,
                                   fills=[(band_pts[:-1], tints[i])], max_dur=.6), x0 + 4, by, tl)
        lane_els = [band]
        if labelled:
            lab = fit(ctx, ctx.T(lane.get('label')), head_sz, lab_w - 50, max_h=lane_h - 30, max_lines=3,
                      min_size=head_sz, pace=1.4)
            lane_els.append(ctx.add(lab, x0 + 34, by + (lane_h - lab.size[1]) / 2, tl))
        evs, xs, dates, bodies = lane_evs[i], lane_xs[i], all_dates[i], all_bodies[i]
        # date above the line, label below: the stack is centred in the band
        dh = max([d.size[1] for d in dates] or [date_h])
        bh = max([b.size[1] for b in bodies] or [0])
        ly = by + (lane_h + dh + 4 - bh) / 2
        ly = min(max(ly, by + dh + 20), by + lane_h - bh - 20)
        line_y[i] = ly
        arrow = ctx.strokes((lx1 - lx0 + 20, 44), arrow_polys(8, 22, lx1 - lx0 + 4, 22, head=24), width=6, max_dur=.5)
        lane_els.append(ctx.add(arrow, lx0, ly - 22, tl))
        lab_top = ly + 18
        widths = [max(dd.size[0], bb.size[0]) for dd, bb in zip(dates, bodies)]
        lefts = _spread(xs, widths, lx0 - 10, lx1 - 30, gap=24)   # crowded events slide apart
        for j, ev in enumerate(evs):
            x, date, body = xs[j], dates[j], bodies[j]
            cx = lefts[j] + widths[j] / 2
            te = lane_ts[i][j]
            d = ctx.add(dot(ctx, 20, ctx.color), x - 24, ly - 24, te)
            dx = cx - date.size[0] / 2
            del_ = ctx.add(date, dx, ly - 22 - date.size[1], te)
            bx = cx - body.size[0] / 2
            bel = ctx.add(body, bx, lab_top, te)
            parts = [d, del_, bel]
            if not bx + 24 <= x <= bx + body.size[0] - 24:   # label pushed off its dot: tie it back
                y1, y2 = ly + 22, lab_top + 12
                x2 = min(max(x, bx + 30), bx + body.size[0] - 30)
                bx0 = min(x, x2) - 6
                parts.append(ctx.add(ctx.strokes((abs(x2 - x) + 12, y2 - y1 + 12),
                                                 [[(x - bx0, 6), (x2 - bx0, y2 - y1 + 6)]], color=ctx.color,
                                                 width=4, max_dur=.3), bx0, y1 - 6, te))
            blocks.setdefault(i, []).append((bx, bx + body.size[0]))
            blocks[i].append((dx, dx + date.size[0]))
            below.setdefault(i, []).append((bx, bx + body.size[0], bel.y + bel.h))
            events.append((i, x, te))
            ctx.register(v.get('id'), k, parts)
            lane_els += parts
            k += 1
        ctx.register(v.get('id'), f'lane{i}', lane_els)
        everything += lane_els
    # Time-alignment guides, downward only: from an event to the lane below, ending in an
    # empty ring on that lane's line where it has nothing at that moment (the "gap").
    ring = 16
    for i, x, te in events:
        q = i + 1
        if q not in line_y or any(a - 8 - ring <= x <= b + 8 + ring for a, b in blocks.get(q, [])):
            continue
        # start clear of every label of this lane that the guide would cross
        ya = max([b for a0, a1, b in below[i] if a0 - 8 <= x <= a1 + 8] + [line_y[i] + 24]) + 4
        yb = line_y[q] - ring - 2
        if yb - ya < 30:
            continue
        gl = dashes(16, 4, 16, yb - ya + 4, on=14, off=12)
        tg = max(te, lane_t[q]) + .05
        g = ctx.add(ctx.strokes((32, yb - ya + 8), gl, color=GUIDE, width=4, max_dur=.5), x - 16, ya - 4, tg)
        rp = ink.circle_points(ring + 4, ring + 4, ring, ring, n=32)
        rg = ctx.add(ctx.strokes((2 * ring + 8, 2 * ring + 8), [rp], color=GUIDE, width=4,
                                 fills=[(rp, tints[q])], max_dur=.3), x - ring - 4, line_y[q] - ring - 4, tg)
        everything += [g, rg]
    ctx.register(v.get('id'), 'all', everything)
    footnote(ctx, v, box, t_prev + .5)


# ------------------------------------------------------------------ range
def build_range(v, beat, box, ctx):
    """Number line between a stated low and high, stated marks only (linear)."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    mn, mxx = v.get('min') or {}, v.get('max') or {}
    lo, hi = float(mn.get('value', 0)), float(mxx.get('value', 1))
    if hi <= lo:
        hi = lo + 1
    bottom = y0 + h - (56 if v.get('footnote') else 0) - 6
    end_w = 300
    ends = {}
    for key, side in (('min', mn), ('max', mxx)):
        align = 'right' if key == 'min' else 'left'
        disp = fit(ctx, ctx.T(side.get('display')), 66, end_w, max_lines=1, min_size=40, align=align)
        lab = fit(ctx, ctx.T(side.get('label')), 40, end_w, max_lines=2, min_size=40, color=SOFT_INK,
                  align=align, pace=1.3)
        ends[key] = (disp, lab)
    wl = max(d.size[0] for d in ends['min'])
    wr = max(d.size[0] for d in ends['max'])
    lx0, lx1 = x0 + 16 + wl + 40, x0 + w - 16 - wr - 40

    def X(val):
        return lx0 + min(1., max(0., (float(val) - lo) / (hi - lo))) * (lx1 - lx0)

    marks = v.get('marks') or []
    mblocks = []
    for m in marks:
        disp = fit(ctx, ctx.T(m.get('display')), 64, 420, max_lines=1, min_size=40, color=ctx.color, align='center')
        lab = fit(ctx, ctx.T(m.get('label')), 42, 420, max_lines=2, min_size=40, align='center', pace=1.3)
        mblocks.append((disp, lab, max(disp.size[0], lab.size[0]), disp.size[1] + lab.size[1] - 8))
    block_h = max([b[3] for b in mblocks] or [0])
    # callout (below the line)
    co = v.get('callout')
    co_text, co_from, co_to, co_trig = None, 'max', 0, None
    if co:
        if isinstance(co, dict) and 'text' in co:
            co_text, co_trig = co.get('text'), co.get('trigger')
            co_from, co_to = co.get('from', 'max'), co.get('to', 0)
        else:
            co_text = co
    co_draw = fit(ctx, ctx.T(co_text), 68, 900, max_lines=1, min_size=40, color=ctx.color, align='center') if co_text else None
    thick = 60
    leader = 120
    comp_h = block_h + leader + thick + (40 + 44 + co_draw.size[1] if co_draw else 90)
    slack = max(0, (bottom - top) - comp_h)
    btop = top + slack * .45
    ly = btop + block_h + leader + thick / 2
    # the range bar
    L = lx1 - lx0
    cap = rrect(L + 12, thick + 12, r=thick / 2, inset=6)
    bar = ctx.add(ctx.strokes((L + 12, thick + 12), [cap], width=6, fills=[(cap[:-1], mix(ctx.color, .72))], max_dur=1.2),
                  lx0 - 6, ly - thick / 2 - 6, t0 + .1)
    allels = [bar]
    for n_, (key, xe, align) in enumerate((('min', lx0, 'right'), ('max', lx1, 'left'))):
        te = t0 + .2 + .3 * n_
        endbar = ctx.add(ctx.strokes((24, thick + 70), [[(12, 6), (12, thick + 64)]], width=9, max_dur=.3),
                         xe - 12, ly - thick / 2 - 35, te, layer=1)
        disp, lab = ends[key]
        stack = disp.size[1] + lab.size[1] - 8
        yy = ly - stack / 2
        if key == 'min':
            ex = xe - 30
            de = ctx.add(disp, ex - disp.size[0], yy, te)
            le = ctx.add(lab, ex - lab.size[0], yy + disp.size[1] - 8, te)
        else:
            ex = xe + 30
            de = ctx.add(disp, ex, yy, te)
            le = ctx.add(lab, ex, yy + disp.size[1] - 8, te)
        ctx.register(v.get('id'), key, [endbar, de, le])
        allels += [endbar, de, le]
    # Footnote = part of the frame: written in the hand's idle time before the first narrated
    # mark when there is such a gap, otherwise last; never ahead of a narrated item.
    fn = footnote(ctx, v, box, t0 + .7)
    said = []
    # marks: blocks above, repelled sideways, with a leader arrow to the exact spot
    xs = [X(m.get('value', lo)) for m in marks]
    t_prev = t0 + .8
    lefts = _spread(xs, [b[2] for b in mblocks], x0 + 10, x0 + w - 10)
    for i, m in enumerate(marks):
        disp, lab, bw, bh = mblocks[i]
        ti = _time(ctx, beat, m, t_prev + .5)
        t_prev = max(t_prev, ti)
        said.append(ti)
        cx = lefts[i] + bw / 2
        yb = btop                                   # values share one baseline row
        de = ctx.add(disp, cx - disp.size[0] / 2, yb, ti)
        le = ctx.add(lab, cx - lab.size[0] / 2, yb + disp.size[1] - 8, ti)
        ax0, ay0 = cx, btop + bh + 8
        ax1, ay1 = xs[i], ly - thick / 2 - 26
        bx0, by0 = min(ax0, ax1) - 30, ay0 - 10
        bend = 0 if abs(ax1 - ax0) < 40 else (18 if ax1 < ax0 else -18)
        polys = arrow_polys(ax0 - bx0, ay0 - by0, ax1 - bx0, ay1 - by0, head=20, bend=bend)
        ar = ctx.add(ctx.strokes((abs(ax1 - ax0) + 60, ay1 - ay0 + 30), polys, color=ctx.color, width=6, max_dur=.5),
                     bx0, by0, ti)
        tick = ctx.add(ctx.strokes((20, thick + 44), [[(10, 4), (10, thick + 40)]], width=6, max_dur=.3),
                       xs[i] - 10, ly - thick / 2 - 22, ti, layer=1)
        ctx.register(v.get('id'), i, [de, le, tick, ar])
        allels += [tick, de, le, ar]
    if co_draw:
        def ref_x(r):
            if r == 'min':
                return lx0
            if r == 'max':
                return lx1
            try:
                return xs[int(r)]
            except (ValueError, IndexError, TypeError):
                return lx0
        xa, xb = ref_x(co_from), ref_x(co_to)
        tc = ctx.time_of(beat, co_trig) if co_trig else t_prev + .5
        said.append(tc)
        ay = ly + thick / 2 + 40
        sag = 44
        bx0, by0 = min(xa, xb) - 30, ay - 30
        polys = arrow_polys(xa - bx0, ay - by0, xb - bx0, ay - by0, head=26, bend=-sag if xb < xa else sag)
        ar = ctx.add(ctx.strokes((abs(xb - xa) + 60, sag + 80), polys, color=ctx.color, width=7, max_dur=.9),
                     bx0, by0, tc)
        # the stretch the callout talks about fills solid on the bar once the arrow lands
        # (no hand time; ticks and end bars stay on top)
        s0, s1 = max(min(xa, xb), lx0 + 8), min(max(xa, xb), lx1 - 8)
        hl = []
        if s1 - s0 > 24:
            sh = thick - 16
            seg = rrect(s1 - s0 + 8, sh + 8, r=sh / 2, inset=4)
            hl = [ctx.add(ctx.strokes((s1 - s0 + 8, sh + 8), [seg], color=ctx.color, width=4,
                                      fills=[(seg[:-1], mix(ctx.color, .3))], max_dur=.5),
                          s0 - 4, ly - sh / 2 - 4, tc, hand=False, after=ar)]
        tx = min(max((xa + xb) / 2 - co_draw.size[0] / 2, x0 + 10), x0 + w - 10 - co_draw.size[0])
        te = ctx.add(co_draw, tx, ay + sag / 2 + 30, tc)
        ctx.register(v.get('id'), 'callout', hl + [ar, te])
        allels += hl + [ar, te]
    if fn is not None and said and min(said) < t0 + 7.5:   # title+bar+ends+footnote ~ 7 s of hand
        fn.trigger = max(said) + .5
    ctx.register(v.get('id'), 'all', allels)


# ------------------------------------------------------------------ calendar
def build_calendar(v, beat, box, ctx):
    """Tear-off day cards with the stated events, plus an open-ended rail."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    days = (v.get('days') or [])[:3]
    opens = (v.get('open') or [])[:5]
    bottom = y0 + h - (56 if v.get('footnote') else 0) - 4
    gap = 40
    rail_w = 540 if opens else 0
    area_w = w - 20 - (rail_w + gap if opens else 0)
    nd = max(1, len(days))
    cw = min(660, (area_w - gap * (nd - 1)) / nd)
    total = nd * cw + gap * (nd - 1)
    cx0 = x0 + 10 + (area_w - total) / 2
    card_top = top + 26
    ch = bottom - card_top
    head_h = 104
    head_col = ctx.color
    head_ink = _on_color(head_col)
    dmax = 1.8 if sum(len(d.get('items') or []) for d in days) <= 3 else 1.3   # keep busy boards brisk
    allels = []
    t_last = t0
    # Untriggered cards (and the rail) follow the previous card's leading run of items, not
    # items that wait for a later phrase, so the board fills while the narration is elsewhere
    # instead of after it; a card with a triggered item is started early enough (~2.4 s of
    # drawing) for that item to land on its phrase.
    t_chain = t0
    for i, day in enumerate(days):
        items = (day.get('items') or [])[:3]
        trig = [ctx.time_of(beat, it['trigger']) for it in items if it.get('trigger')]
        td = _time(ctx, beat, day, max(t_chain + .6, min(trig) - 2.4) if trig else t_chain + .6)
        t_item = t_chain = td
        cx = cx0 + i * (cw + gap)
        frame_pts = rrect(cw, ch, r=20)
        frame = ctx.add(ctx.strokes((cw, ch), [frame_pts], width=6, fills=[(frame_pts[:-1], CARD)], max_dur=.7),
                        cx, card_top, td)
        head_pts = rrect(cw, head_h, r=20, top_only=True)
        head = ctx.add(ctx.strokes((cw, head_h), [head_pts], width=6, fills=[(head_pts[:-1], head_col)], max_dur=.5),
                       cx, card_top, td)
        rings = []
        for f in (.27, .73):
            rp = rrect(26, 58, r=13, inset=4)
            rings.append(ctx.add(ctx.strokes((26, 58), [rp], width=5, fills=[(rp[:-1], (66, 66, 66))], max_dur=.3),
                                 cx + cw * f - 13, card_top - 26, td, hand=False, after=head))
        date = fit(ctx, ctx.T(day.get('date')), 58, cw - 60, max_lines=1, min_size=40, color=head_ink, align='center',
                   pace=1.3)
        de = ctx.add(date, cx + (cw - date.size[0]) / 2, card_top + (head_h - date.size[1]) / 2 + 4, td)
        card_els = [frame, head, *rings, de]
        a_top, a_bot = card_top + head_h + 18, card_top + ch - 18
        n = max(1, len(items))
        row_h = (a_bot - a_top) / n
        if n > 1:     # one text column per card; long labels take room from the doodles, not size
            dh = min(row_h - 30, 180)
            for frac in (.38, .31, .25):
                dw = min(220, cw * frac)
                tw = cw - 24 - (26 + dw + 26)
                labs = [fit(ctx, ctx.T(it.get('label')), 46, tw, max_h=row_h - 16, max_lines=3, min_size=40,
                            pace=1.4) for it in items]
                if all(lb.size[1] <= row_h - 16 and lb.size[0] <= tw + 12 for lb in labs):
                    break
        leading = True
        for j, it in enumerate(items):
            ti = max(td, _time(ctx, beat, it, t_item + .5))
            t_item = max(t_item, ti)
            leading = leading and (j == 0 or not it.get('trigger'))
            if leading:
                t_chain = ti
            ry = a_top + j * row_h
            if n == 1:
                lab = fit(ctx, ctx.T(it.get('label')), 52, cw - 60, max_lines=2, min_size=40, align='center', pace=1.3)
                ds = min(cw - 120, row_h - lab.size[1] - 40, 300)
                dd = ctx.doodle(it.get('doodle'), (ds * 1.35, ds), max_dur=dmax)
                block = dd.size[1] + 24 + lab.size[1]
                yy = ry + (row_h - block) / 2
                del_ = ctx.add(dd, cx + (cw - dd.size[0]) / 2, yy, ti)
                lel = ctx.add(lab, cx + (cw - lab.size[0]) / 2, yy + dd.size[1] + 24, ti)
            else:
                lab, tx = labs[j], cx + 26 + dw + 26
                dd = ctx.doodle(it.get('doodle'), (dw, dh), max_dur=dmax)
                del_ = ctx.add(dd, cx + 26 + (dw - dd.size[0]) / 2, ry + (row_h - dd.size[1]) / 2, ti)
                lel = ctx.add(lab, tx, ry + (row_h - lab.size[1]) / 2, ti)
                if j < n - 1:
                    sep = ctx.strokes((cw - 60, 10), dashes(4, 5, cw - 64, 5, on=18, off=12), color=(190, 190, 190),
                                      width=3, max_dur=.4)
                    card_els.append(ctx.add(sep, cx + 30, ry + row_h - 5, ti, hand=False, after=lel))
            ctx.register(v.get('id'), f'{i}-{j}', [del_, lel])
            card_els += [del_, lel]
            t_last = max(t_last, ti)
        ctx.register(v.get('id'), i, card_els)
        allels += card_els
    if opens:
        trig = [ctx.time_of(beat, o['trigger']) for o in opens if o.get('trigger')]
        tr = max(t_chain + .6, min(trig) - 1.) if trig else t_chain + .6
        t_open = tr
        rx, ry = x0 + w - 10 - rail_w, top + 10
        rh = bottom - ry
        note = ctx.add(sticky(ctx, rail_w, rh - 6, tape=ctx.color), rx, ry, tr)
        head_txt = v.get('open_title') or {'en': 'Also on my list', 'zh': '也在关注'}
        hd = fit(ctx, ctx.T(head_txt), 54, rail_w - 80, max_lines=1, min_size=40, color=ctx.color, pace=1.3)
        he = ctx.add(hd, rx + 40, ry + 46, tr)
        rail = [note, he]
        i_top = ry + 46 + hd.size[1] + 22
        n = len(opens)
        row_h = min(170, (ry + rh - 30 - i_top) / n)
        for j, o in enumerate(opens):
            to = max(tr, _time(ctx, beat, o, t_open + .5))
            t_open = max(t_open, to)
            t_last = max(t_last, to)
            yy = i_top + j * row_h
            bs = 46
            lab = fit(ctx, ctx.T(o.get('label')), 46, rail_w - 60 - bs - 40, max_h=row_h - 10, max_lines=2,
                      min_size=40, pace=1.4)
            ly_ = yy + (row_h - lab.size[1]) / 2
            sq = [(4, 6), (bs - 3, 4), (bs - 5, bs - 3), (5, bs - 5), (4, 6)]
            bx = ctx.add(ctx.strokes((bs + 4, bs + 4), [sq], width=5, fills=[(sq[:-1], CARD)], max_dur=.35),
                         rx + 40, ly_ + min(lab.size[1], 70) / 2 - bs / 2, to)
            le = ctx.add(lab, rx + 40 + bs + 24, ly_, to)
            ctx.register(v.get('id'), f'open{j}', [bx, le])
            rail += [bx, le]
        ctx.register(v.get('id'), 'open', rail)
        allels += rail
    ctx.register(v.get('id'), 'all', allels)
    footnote(ctx, v, box, t_last + .5)


BUILDERS = {'lanes': build_lanes, 'range': build_range, 'calendar': build_calendar}

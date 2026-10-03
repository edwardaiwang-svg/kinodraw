"""Visual builders: turn episode visuals into scheduled board Elements.

Each builder receives the visual dict ``v``, the beat, a world ``box``
(x, y, w, h) and the build context ``ctx``; it adds Elements via ``ctx.add``.
Page-type builders live here and in ``pages_*.py`` (registered in PAGE_BUILDERS).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import ink
from .board import COL, Element, Layout
from ..library import MISSING, resolve

HERE = Path(__file__).resolve().parent
PAPER_NOTE = (255, 241, 118)
SOFT_INK = (85, 96, 106)


def mix(c, k=.5, base=(255, 255, 255)):
    return tuple(int(c[i] * (1 - k) + base[i] * k) for i in range(3))


class Ctx:
    def __init__(self, episode, lang, timing, layout: Layout, project_dir=None):
        self.ep, self.lang, self.timing, self.layout = episode, lang, timing, layout
        self.project_dir = Path(project_dir) if project_dir else None
        self.elements: list[Element] = []
        self.registry: dict = {}
        self.color = ink.NEUTRAL
        self.chapter = None
        self.beat = None

    # ---- language + time helpers
    def T(self, pair, default=''):
        if pair is None:
            return default
        if isinstance(pair, str):
            return pair
        return pair.get(self.lang) or pair.get('en') or default

    def time_of(self, beat, trigger=None, default=None):
        """Absolute time when ``trigger`` (substring of spoken text) is heard."""
        if isinstance(trigger, dict) and trigger.get('beat'):
            beat = next(b for b in self.ep['beats'] if b['id'] == trigger['beat'])
        info = self.timing['beats'][beat['id']]
        if trigger:
            phrase = trigger.get(self.lang) if isinstance(trigger, dict) else trigger
            if phrase:
                spoken = beat['spoken'][self.lang]
                pos = spoken.find(phrase)
                if pos >= 0 and info.get('char_times'):
                    ct = info['char_times']
                    return info['start'] + ct[min(pos, len(ct) - 1)]
        return info['start'] + (default if default is not None else .15)

    # ---- drawable factories
    def text(self, s, size, color=None, max_w=None, max_lines=3, align='left', pace=1.0, min_size=28):
        if max_w:
            lines, size = ink.fit_text(s, self.lang, max_w, max_lines, size, min_size=min_size)
        else:
            lines = [s]
        return ink.TextDrawing(lines, self.lang, size, color=color or ink.INK, align=align, pace=pace)

    def doodle(self, did, box, **kw):
        return ink.svg_drawing(resolve(did, self.project_dir) or MISSING, box, **kw)

    def strokes(self, size, polylines, color=None, width=6, fills=None, **kw):
        return ink.stroke_drawing(size, polylines, color=color or ink.INK, width=width, closed_fill=fills, **kw)

    def add(self, drawing, x, y, trigger, **kw) -> Element:
        el = Element(drawing, x, y, trigger, **kw)
        self.elements.append(el)
        return el

    def register(self, vid, key, elements):
        if not vid:
            return
        els = elements if isinstance(elements, list) else [elements]
        self.registry.setdefault(vid, {})[key] = els


def union_bbox(els):
    xs0, ys0, xs1, ys1 = zip(*(e.bbox() for e in els))
    return min(xs0), min(ys0), max(xs1), max(ys1)


# ============================================================ slot builders
def arrow_polys(x0, y0, x1, y1, head=18, bend=0.):
    n = 24
    pts = []
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    nx, ny = -(y1 - y0), (x1 - x0)
    ln = math.hypot(nx, ny) or 1
    cx, cy = mx + nx / ln * bend, my + ny / ln * bend
    for i in range(n + 1):
        t = i / n
        pts.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1,
                    (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1))
    ex, ey = pts[-1]
    px, py = pts[-3]
    ang = math.atan2(ey - py, ex - px)
    left = (ex - head * math.cos(ang - .45), ey - head * math.sin(ang - .45))
    right = (ex - head * math.cos(ang + .45), ey - head * math.sin(ang + .45))
    return [pts, [left, (ex, ey), right]]


def build_cluster(v, beat, box, ctx):
    """1-3 doodles, each in its own equal share of the box; labels never leave their share."""
    x0, y0, w, h = box
    items = v.get('items', [])[:3]
    n = max(1, len(items))
    rel = v.get('relation', 'none')
    share = w / n
    has_label = any(it.get('label') for it in items)
    label_h = (116 if share < 400 else 70) if has_label else 0
    gap = 70 if rel != 'none' and n > 1 else 16
    d = min(share - gap, h - label_h - 8, 320 if w <= 560 else 360)
    base = ctx.time_of(beat, v.get('trigger'))
    made = []
    for i, it in enumerate(items):
        t = ctx.time_of(beat, it.get('trigger')) if it.get('trigger') else base
        cx = x0 + share * (i + .5)
        dr = ctx.doodle(it['doodle'], (d, d))
        el = ctx.add(dr, cx - dr.size[0] / 2, y0 + (h - label_h - dr.size[1]) / 2 + 4, t, group=v.get('id', ''))
        parts = [el]
        if it.get('label'):
            lw = share - 24
            lab = ctx.text(ctx.T(it['label']), 44, max_w=lw, max_lines=2, align='center', min_size=30)
            lel = ctx.add(lab, cx - lab.size[0] / 2, y0 + h - label_h + 4, t, group=v.get('id', ''))
            parts.append(lel)
        ctx.register(v.get('id'), i, parts)
        made.extend(parts)
        if i < n - 1 and rel != 'none':
            gx = x0 + share * (i + 1)          # boundary between the two shares
            gy = y0 + (h - label_h) / 2
            if rel == 'arrow':
                aw = min(110, share - d + 30)
                dr2 = ctx.strokes((aw, 60), arrow_polys(6, 34, aw - 10, 30, bend=-10), color=ctx.color, width=7)
                ctx.add(dr2, gx - aw / 2, gy - 30, t)
            else:
                glyph = {'plus': '+', 'vs': 'VS', 'equals': '='}.get(rel, '→')
                g = ctx.text(glyph, 60 if glyph != 'VS' else 48, color=ctx.color)
                ctx.add(g, gx - g.size[0] / 2, gy - g.size[1] / 2, t)
    ctx.register(v.get('id'), 'all', made)


def build_quote(v, beat, box, ctx):
    x0, y0, w, h = box
    t = ctx.time_of(beat, v.get('trigger'))
    mark = ctx.text('“', 150, color=ctx.color)
    ctx.add(mark, x0 - 6, y0 - 34, t)
    body = ctx.text(ctx.T(v.get('text')), 46 if ctx.lang == 'en' else 48, max_w=w - 110, max_lines=4, pace=1.25)
    bel = ctx.add(body, x0 + 90, y0 + 20, t)
    who = ctx.text('— ' + ctx.T(v.get('who')), 38, color=ctx.color, max_w=w - 110, max_lines=1)
    wel = ctx.add(who, x0 + 90, y0 + 30 + body.size[1], t)
    ctx.register(v.get('id'), 'all', [bel, wel])
    ctx.register(v.get('id'), 0, [bel])


def sticky(ctx, w, h, fill=PAPER_NOTE, tape=None):
    poly = [(8, 12), (w - 10, 8), (w - 6, h - 14), (12, h - 8), (8, 12)]
    fills = [(poly[:-1], fill)]
    lines = [poly]
    if tape:
        tw = w * .32
        tp = [(w / 2 - tw / 2, -2), (w / 2 + tw / 2, 4), (w / 2 + tw / 2 - 4, 30), (w / 2 - tw / 2 - 2, 26), (w / 2 - tw / 2, -2)]
        fills.append((tp[:-1], mix(tape, .25)))
        lines.append(tp)
    return ctx.strokes((w, h + 6), lines, width=5, fills=fills, max_dur=1.1)


def build_glossary(v, beat, box, ctx):
    x0, y0, w, h = box
    t = ctx.time_of(beat, v.get('trigger'))
    nw, nh = min(w, 520), min(h, 330)
    nx, ny = x0 + (w - nw) / 2, y0 + (h - nh) / 2
    note = ctx.add(sticky(ctx, nw, nh, tape=ctx.color), nx, ny, t)
    term = ctx.text(ctx.T(v.get('term')), 46, max_w=nw - 60, max_lines=1, color=ctx.color, min_size=34)
    tel = ctx.add(term, nx + 28, ny + 34, t)
    body = ctx.text(ctx.T(v.get('text')), 36 if ctx.lang == 'en' else 38, max_w=nw - 60, max_lines=4, pace=1.4, min_size=28)
    bel = ctx.add(body, nx + 28, ny + 40 + term.size[1], t)
    ctx.register(v.get('id'), 'all', [note, tel, bel])
    ctx.register(v.get('id'), 0, [note])


def build_stat(v, beat, box, ctx):
    x0, y0, w, h = box
    t = ctx.time_of(beat, v.get('trigger'))
    made = []
    tx = x0
    if v.get('doodle'):
        dd = ctx.doodle(v['doodle'], (200, 200))
        made.append(ctx.add(dd, x0, y0 + (h - dd.size[1]) / 2 - 20, t))
        tx = x0 + 215
    # A wordy value ("more than a year") gets two smaller lines; value and label are centred together so the
    # block never rises out of its cell into the drawings above.
    val = ctx.text(ctx.T(v.get('value')), 110, color=ctx.color, max_w=x0 + w - tx, max_lines=1, min_size=64)
    if len(val.lines) > 1:
        val = ctx.text(ctx.T(v.get('value')), 72, color=ctx.color, max_w=x0 + w - tx, max_lines=2, min_size=40)
    lab = ctx.text(ctx.T(v.get('label')), 42, max_w=x0 + w - tx, max_lines=2, min_size=30)
    top = y0 + max(0, (h - val.size[1] - 8 - lab.size[1]) / 2)
    vel = ctx.add(val, tx, top, t)
    lel = ctx.add(lab, tx, top + val.size[1] + 8, t)
    made += [vel, lel]
    ctx.register(v.get('id'), 0, [vel])
    ctx.register(v.get('id'), 'all', made)


# ============================================================ emphasis / stamp
def build_emphasis(v, beat, ctx):
    target = str(v.get('target', ''))
    vid, _, key = target.partition('.')
    reg = ctx.registry.get(vid, {})
    els = reg.get(int(key) if key.isdigit() else (key or 'all')) or reg.get('all') or next(iter(reg.values()), None)
    if not els:
        return
    x0, y0, x1, y1 = union_bbox(els)
    t = ctx.time_of(beat, v.get('trigger'))
    t = max(t, max(e.trigger for e in els) + .2)
    kind = v.get('kind', 'circle')
    pad = 16
    if kind == 'circle':
        W, H = x1 - x0 + 2 * pad + 20, y1 - y0 + 2 * pad + 20
        pts = ink.circle_points(W / 2, H / 2, W / 2 - 8, H / 2 - 8, start=-2.4, turns=1.08, n=110, wobble=.02)
        dr = ctx.strokes((W, H), [pts], color=ctx.color, width=7, max_dur=.9)
        ctx.add(dr, x0 - pad - 10, y0 - pad - 10, t, layer=1, after=els[-1])
    elif kind == 'underline':
        W = x1 - x0 + 20
        pts = [(6 + i * (W - 12) / 30, 10 + 4 * math.sin(i / 3)) for i in range(31)]
        dr = ctx.strokes((W, 26), [pts], color=ctx.color, width=7, max_dur=.7)
        ctx.add(dr, x0 - 10, y1 - 2, t, layer=1, after=els[-1])
    elif kind == 'strike':
        W = x1 - x0 + 24
        dr = ctx.strokes((W, 30), [[(4, 20), (W - 4, 8)]], color=(229, 57, 53), width=8, max_dur=.6)
        ctx.add(dr, x0 - 12, (y0 + y1) / 2 - 15, t, layer=1, after=els[-1])
    elif kind == 'highlight':
        W, H = x1 - x0 + 20, (y1 - y0) * .78
        pts = [(H / 2, H / 2), (W - H / 2, H / 2 - 2)]
        dr = ctx.strokes((W, H), [pts], color=(253, 216, 53, 120), width=H * .92, max_dur=.7)
        ctx.add(dr, x0 - 10, y0 + (y1 - y0 - H) / 2 + 4, t, layer=1, hand=True, after=els[-1])


# ============================================================ page builders
def page_title(ctx, v, box, t, key='title'):
    x0, y0, w, h = box
    if not v.get(key):
        return None, y0
    ttl = ctx.text(ctx.T(v[key]), 60, color=ctx.color, max_w=w - 40, max_lines=1, min_size=40)
    el = ctx.add(ttl, x0 + 10, y0, t)
    return el, y0 + ttl.size[1] + 18


def footnote(ctx, v, box, t, key='footnote'):
    x0, y0, w, h = box
    if not v.get(key):
        return None
    fn = ctx.text(ctx.T(v[key]), 32, color=SOFT_INK, max_w=w - 20, max_lines=1, pace=1.6, min_size=26)
    return ctx.add(fn, x0 + 10, y0 + h - fn.size[1], t)


def dot(ctx, r, color):
    pts = ink.circle_points(r + 4, r + 4, r, r, n=40)
    return ctx.strokes((2 * r + 8, 2 * r + 8), [pts], width=5, fills=[(pts, color)], max_dur=.5, pop=.12)


def build_ladder(v, beat, box, ctx):
    """Discrete log-scale stops (no path between stated points)."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    stops = v.get('stops', [])
    vals = [max(1e-9, float(s['value'])) for s in stops]
    lo, hi = math.log10(min(vals)), math.log10(max(vals))
    if hi - lo < 1e-6:
        hi = lo + 1
    plot_top, plot_bot = top + 70, y0 + h - 150
    left, right = x0 + 90, x0 + w - 60
    n = len(stops)
    xs = [left + (right - left) * (i + .5) / n for i in range(n)]
    ys = [plot_bot - (math.log10(v_) - lo) / (hi - lo) * (plot_bot - plot_top) for v_ in vals]
    axis = ctx.strokes((40, plot_bot - plot_top + 40), [[(20, 10), (20, plot_bot - plot_top + 30)]], color=SOFT_INK, width=4)
    ctx.add(axis, left - 70, plot_top - 20, t0)
    note = ctx.text('log scale' if ctx.lang == 'en' else '对数刻度', 28, color=SOFT_INK)
    ctx.add(note, left - 88, plot_bot + 22, t0)
    prev = None
    for i, s in enumerate(stops):
        ti = ctx.time_of(beat, s.get('trigger')) if s.get('trigger') else t0 + .3 * i
        if prev is not None:
            px, py = prev
            dash = []
            steps = 14
            for k in range(steps):
                if k % 2 == 0:
                    a, b = k / steps, (k + 1) / steps
                    dash.append([(px + (xs[i] - px) * a, py + (ys[i] - py) * a), (px + (xs[i] - px) * b, py + (ys[i] - py) * b)])
            bx0, by0 = min(px, xs[i]) - 6, min(py, ys[i]) - 6
            polys = [[(x - bx0, y - by0) for x, y in seg] for seg in dash]
            dr = ctx.strokes((abs(xs[i] - px) + 12, abs(ys[i] - py) + 12), polys, color=(150, 150, 150), width=4, max_dur=.6)
            ctx.add(dr, bx0, by0, ti)
        d = dot(ctx, 17, ctx.color)
        de = ctx.add(d, xs[i] - 21, ys[i] - 21, ti)
        val = ctx.text(ctx.T(s.get('display')), 50, color=ink.INK, max_w=(right - left) / n + 40, max_lines=1, align='center', min_size=34)
        vy = ys[i] - 30 - val.size[1] if ys[i] - 30 - val.size[1] > plot_top - 60 else ys[i] + 28
        ve = ctx.add(val, xs[i] - val.size[0] / 2, vy, ti)
        lab = ctx.text(ctx.T(s.get('label')), 32, color=SOFT_INK, max_w=(right - left) / n - 6, max_lines=3, align='center', min_size=24, pace=1.5)
        le = ctx.add(lab, xs[i] - lab.size[0] / 2, plot_bot + 14 + (36 if i % 2 else 0), ti)
        ctx.register(v.get('id'), i, [de, ve])
        prev = (xs[i], ys[i])
        t_last = max(locals().get('t_last', t0), ti)
    tops = {}
    for i in range(n):
        els = ctx.registry.get(v.get('id'), {}).get(i, [])
        tops[i] = min((e.y for e in els), default=ys[i] - 60)
    for c in v.get('callouts', []) or []:
        i, j = sorted(c.get('stops', [0, 1])[:2])
        tc = ctx.time_of(beat, c.get('trigger')) if c.get('trigger') else t0 + .3 * n
        peak = min(tops[k] for k in range(i, j + 1)) - 40
        ax, bx = xs[i], xs[j]
        ay, by = tops[i] - 10, tops[j] - 10
        top_y = max(plot_top - 40, peak - 40)
        bx0, by0 = ax - 30, top_y - 20
        W, H = bx - ax + 60, max(ay, by) - by0 + 30
        pts = []
        for k in range(31):
            u = k / 30
            x = ax + (bx - ax) * u
            base = ay + (by - ay) * u
            y = base - (base - top_y) * math.sin(math.pi * u) ** .6
            pts.append((x - bx0, y - by0))
        ex, ey = pts[-1]
        px, py = pts[-3]
        ang = math.atan2(ey - py, ex - px)
        head = [(ex - 20 * math.cos(ang - .45), ey - 20 * math.sin(ang - .45)), (ex, ey),
                (ex - 20 * math.cos(ang + .45), ey - 20 * math.sin(ang + .45))]
        ctx.add(ctx.strokes((W, H), [pts, head], color=ctx.color, width=6), bx0, by0, tc)
        txt = ctx.text(ctx.T(c.get('text')), 38, color=ctx.color, max_w=abs(bx - ax) + 120, max_lines=2, align='center')
        ctx.add(txt, (ax + bx) / 2 - txt.size[0] / 2, top_y - txt.size[1] - 4, tc)
    footnote(ctx, v, box, locals().get('t_last', t0) + .3)


def build_table(v, beat, box, ctx):
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    cols = v.get('columns', [])
    rows = v.get('rows', [])
    ncol = len(cols) + 1  # + mark column
    fw = w - 30
    mark_w = 110
    col_w = (fw - mark_w) / max(1, len(cols))
    row_h = min(88, (y0 + h - 70 - top - 70) / max(1, len(rows)))
    # notepad frame + ruled lines
    fh = 70 + row_h * len(rows) + 20
    frame = [[(0, 0), (fw, 0), (fw, fh), (0, fh), (0, 0)]]
    fills = [([(0, 0), (fw, 0), (fw, fh), (0, fh)], (255, 255, 252))]
    rules = [[(10, 70 + row_h * r), (fw - 10, 70 + row_h * r)] for r in range(len(rows) + 1)]
    fr = ctx.strokes((fw + 8, fh + 8), frame, width=5, fills=fills, max_dur=1.0)
    ctx.add(fr, x0 + 10, top, t0)
    rl = ctx.strokes((fw + 8, fh + 8), rules, color=(160, 190, 220), width=3, max_dur=.8)
    ctx.add(rl, x0 + 10, top, t0)
    for c, name in enumerate(cols):
        hd = ctx.text(ctx.T(name), 36, color=ctx.color, max_w=col_w - 20, max_lines=1, min_size=26)
        ctx.add(hd, x0 + 30 + c * col_w, top + 14, t0)
    for r, row in enumerate(rows):
        tr = ctx.time_of(beat, row.get('trigger')) if row.get('trigger') else t0 + .4 * (r + 1)
        cells = []
        for c, cell in enumerate(row.get('cells', [])[:len(cols)]):
            txt = ctx.text(ctx.T(cell), 38 if c else 40, max_w=col_w - 20, max_lines=1, min_size=24, pace=1.3)
            cells.append(ctx.add(txt, x0 + 30 + c * col_w, top + 70 + row_h * r + (row_h - txt.size[1]) / 2, tr))
        mark = row.get('mark', 'none')
        if mark in ('check', 'cross'):
            mx, my = x0 + 10 + fw - mark_w + 20, top + 70 + row_h * r + 10
            if mark == 'check':
                polys = [[(8, 34), (28, 56), (70, 8)]]
                col = (46, 157, 79)
            else:
                polys = [[(10, 10), (62, 58)], [(62, 10), (10, 58)]]
                col = (229, 57, 53)
            cells.append(ctx.add(ctx.strokes((80, 66), polys, color=col, width=8, max_dur=.5), mx, my, tr))
        ctx.register(v.get('id'), r, cells)
        t_last = max(locals().get('t_last', t0), tr)
    st = v.get('stamp')
    if st:
        ts = ctx.time_of(beat, st.get('trigger')) if st.get('trigger') else t0 + 1
        r = int(st.get('row', len(rows) - 1))
        text = ctx.text(ctx.T(st.get('text')).upper() if ctx.lang == 'en' else ctx.T(st.get('text')), 36,
                        color=(229, 57, 53), max_w=520, max_lines=2, align='center')
        sw, sh = text.size[0] + 40, text.size[1] + 24
        box_pts = [(4, 4), (sw - 4, 4), (sw - 4, sh - 4), (4, sh - 4), (4, 4)]
        sx = x0 + 10 + fw - mark_w - sw - 10
        sy = top + 70 + row_h * r + (row_h - sh) / 2
        ctx.add(ctx.strokes((sw, sh), [box_pts], color=(229, 57, 53), width=5, max_dur=.6), sx, sy, ts, layer=1)
        ctx.add(text, sx + 20, sy + 12, ts, layer=1)
    footnote(ctx, v, box, locals().get('t_last', t0) + .3)


def build_levels(v, beat, box, ctx):
    """Vertical level ladder (e.g. yields): linear scale, stated levels only."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    levels = v.get('levels', [])
    vals = [float(l['value']) for l in levels]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * .15 or 1
    lo, hi = lo - pad, hi + pad
    ptop, pbot = top + 40, y0 + h - 90
    ax = x0 + 330
    axis = ctx.strokes((30, pbot - ptop + 20), [[(15, 5), (15, pbot - ptop + 10)]], color=SOFT_INK, width=4)
    ctx.add(axis, ax - 15, ptop - 5, t0)
    ypos = {}
    for i, l in enumerate(levels):
        ti = ctx.time_of(beat, l.get('trigger')) if l.get('trigger') else t0 + .4 * i
        y = pbot - (float(l['value']) - lo) / (hi - lo) * (pbot - ptop)
        ypos[i] = y
        style = l.get('style', 'solid')
        col = ctx.color if style == 'solid' else ((150, 150, 150) if style == 'faded' else ink.INK)
        L = w - 420
        if style == 'dashed':
            polys = [[(10 + k * 40, 10), (10 + k * 40 + 22, 10)] for k in range(int(L / 40))]
        else:
            polys = [[(10, 10), (L, 10)]]
        line = ctx.add(ctx.strokes((L + 20, 20), polys, color=col, width=6, max_dur=.8), ax, y - 10, ti)
        val = ctx.text(ctx.T(l.get('display')), 56, color=col if style != 'faded' else (140, 140, 140), max_w=300, max_lines=1, align='right')
        ve = ctx.add(val, ax - 30 - val.size[0], y - val.size[1] / 2, ti)
        lab = ctx.text(ctx.T(l.get('label')), 38, color=ink.INK if style != 'faded' else (140, 140, 140), max_w=L - 60, max_lines=2, min_size=28)
        le = ctx.add(lab, ax + 40, y - lab.size[1] - 8, ti)
        ctx.register(v.get('id'), i, [line, ve, le])
        t_last = max(locals().get('t_last', t0), ti)
    for a in v.get('arrows', []) or []:
        fi, ti_ = int(a.get('from', 0)), int(a.get('to', 1))
        tt = ctx.time_of(beat, a.get('trigger')) if a.get('trigger') else t0 + 1
        ya, yb = ypos.get(fi), ypos.get(ti_)
        if ya is None or yb is None:
            continue
        axx = x0 + w - 110
        polys = arrow_polys(20, ya - min(ya, yb) + 10, 20, yb - min(ya, yb) + 10, bend=30, head=22)
        ctx.add(ctx.strokes((80, abs(yb - ya) + 30), polys, color=ctx.color, width=7), axx - 20, min(ya, yb) - 10, tt)
        lab = ctx.text(ctx.T(a.get('label')), 36, color=ctx.color, max_w=260, max_lines=2, align='right')
        ctx.add(lab, axx - 40 - lab.size[0], (ya + yb) / 2 - lab.size[1] / 2, tt)
        t_last = max(locals().get('t_last', t0), tt)
    footnote(ctx, v, box, locals().get('t_last', t0) + .3)


ZONE_COLORS = {'green': (67, 160, 71), 'red': (229, 57, 53), 'orange': (251, 140, 0), 'blue': (30, 111, 217),
               'gray': (158, 158, 158), 'yellow': (253, 216, 53), 'purple': (142, 36, 170)}


def build_zones(v, beat, box, ctx):
    """Horizontal zone map on a number line (e.g. 0% .. -20% downside)."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    axis = v.get('axis', {})
    a_from, a_to = float(axis.get('from', 0)), float(axis.get('to', -20))
    left, right = x0 + 60, x0 + w - 60
    ay = y0 + h - 170

    def X(val):
        return left + (val - a_from) / (a_to - a_from) * (right - left)
    ax_el = ctx.add(ctx.strokes((right - left + 40, 30), arrow_polys(10, 15, right - left + 30, 15, head=20), width=6), left - 10, ay - 15, t0)
    for tk in axis.get('ticks', []) or []:
        xx = X(float(tk['value']))
        ctx.add(ctx.strokes((20, 36), [[(10, 4), (10, 32)]], width=5, max_dur=.3), xx - 10, ay - 18, t0)
        lab = ctx.text(ctx.T(tk.get('display')), 40, align='center')
        ctx.add(lab, xx - lab.size[0] / 2, ay + 26, t0)
    band_top, band_bot = top + 150, ay - 26
    for i, z in enumerate(v.get('zones', [])):
        ti = ctx.time_of(beat, z.get('trigger')) if z.get('trigger') else t0 + .5 * (i + 1)
        xa, xb = X(float(z['from'])), X(float(z['to']))
        xa, xb = min(xa, xb), max(xa, xb)
        col = ZONE_COLORS.get(z.get('color', 'gray'), (158, 158, 158))
        bw, bh = xb - xa - 8, band_bot - band_top
        rect = [(4, 4), (bw, 4), (bw, bh), (4, bh), (4, 4)]
        band = ctx.add(ctx.strokes((bw + 6, bh + 6), [rect], color=col, width=5,
                                   fills=[(rect[:-1], mix(col, .62))], max_dur=.9), xa + 4, band_top, ti)
        parts = [band]
        if z.get('doodle'):
            dd = ctx.doodle(z['doodle'], (min(170, bw - 20), 150))
            parts.append(ctx.add(dd, xa + (xb - xa - dd.size[0]) / 2, band_top + 18, ti))
        lab = ctx.text(ctx.T(z.get('label')), 36, max_w=bw - 24, max_lines=4, align='center', min_size=24, pace=1.3)
        parts.append(ctx.add(lab, xa + (xb - xa - lab.size[0]) / 2, band_bot - lab.size[1] - 16, ti))
        ctx.register(v.get('id'), i, parts)
        t_last = max(locals().get('t_last', t0), ti)
    footnote(ctx, v, box, locals().get('t_last', t0) + .3)


PAGE_BUILDERS = {'ladder': build_ladder, 'table': build_table, 'levels': build_levels, 'zones': build_zones}
SLOT_BUILDERS = {'cluster': build_cluster, 'quote': build_quote, 'glossary': build_glossary, 'stat': build_stat}


def load_page_plugins():
    """pages_*.py modules each define BUILDERS = {type: fn} (listed explicitly: frozen apps cannot glob .py files)."""
    from . import pages_logic, pages_quant, pages_time
    for mod in (pages_quant, pages_time, pages_logic):
        PAGE_BUILDERS.update(getattr(mod, 'BUILDERS', {}))
    return PAGE_BUILDERS

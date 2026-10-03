"""Quantity page builders: bars, coins, grid100 (full-board charts).

Schemas (CONTRACT.md, plus the optional fields marked *):
- bars    {title, rows: [{label, value, display, trigger, highlight?}], unit, footnote,
           *groups: [{label, rows: [...]}], *trend: bool, *doodle}
          ``groups`` draws one card per group, each on its OWN zero-based scale (for
          quantities that must not share an axis, e.g. EBITDA vs market cap), with a
          green up / red down arrow per card (``trend`` defaults to true with groups)
          and an "each card has its own scale" note. With plain ``rows`` everything
          shares one zero-based scale; ``doodle`` stands to the right of the bars.
          The last row of each group is highlighted unless a row sets ``highlight``.
          Up to 6 rows per group; with groups keep it to 2 cards x <= 3 rows
          (or 3 cards x 2 rows with short labels AND displays -- ZH <= ~5 glyphs)
          so values stay >= 40 px on one line.
- coins   {title, groups: [{label, count (<= 60), display, trigger}], footnote, *unit}
          exactly ``count`` gold coins per group in stacks of 10; ``display`` written big.
- grid100 {title, filled, hatched, legend: [{text, *swatch: filled|hatched|both|empty,
           *trigger}], trigger, *fill_trigger, *doodle, *footnote}
          10x10 squares; the first ``filled`` are coloured, the next ``hatched`` hatched
          (the uncertain part of a range). ``fill_trigger`` = when they are coloured in.
Every number on the board is an author display string; ``value``/``count`` only size marks.
Doodles, footnotes and scale notes are drawn after the last item so numbers track the voice.
Emphasis keys: bars -> row index (flattened across groups), 'g<i>' per group;
coins -> group index; grid100 -> legend index, 'grid', 'filled', 'hatched'; all -> 'all'.
"""
from __future__ import annotations

import math

from . import ink
from .scenes import SOFT_INK, footnote, mix, page_title

UP_GREEN = (67, 160, 71)
DOWN_RED = (229, 57, 53)
GOLD_SIDE = (249, 168, 37)
GOLD_FACE = (253, 216, 53)
CARD = (255, 255, 252)


def _when(ctx, beat, item, fallback):
    return ctx.time_of(beat, item.get('trigger')) if item.get('trigger') else fallback


def _fits(ctx, s, size, max_w, max_lines):
    lines = ink.wrap_words(s, ctx.lang, size, max_w)
    return len(lines) <= max_lines and all(ink.text_width(ln, ctx.lang, size) <= max_w for ln in lines)


def _fit_all(ctx, strings, size, max_ws, max_lines=1, min_size=40, colors=None, floor=32, **kw):
    """Sibling texts (one chart's values or labels) at ONE shared size: the largest that
    fits every string, also shrinking a single long word (fit_text only counts lines).
    Below ``min_size`` (the 40 px board floor) only down to ``floor`` and only when the
    alternative is a word or number broken across lines (over-dense specs)."""
    ss = [ctx.T(s) for s in strings]
    ws = max_ws if isinstance(max_ws, (list, tuple)) else [max_ws] * len(ss)
    while size > min(min_size, floor) and not all(_fits(ctx, s, size, mw, max_lines) for s, mw in zip(ss, ws) if s):
        size -= 2
    cs = colors or [kw.pop('color', None)] * len(ss)
    return [ctx.text(s, size, max_w=mw, max_lines=max_lines, min_size=size, color=c, **kw)
            for s, mw, c in zip(ss, ws, cs)]


def _fit(ctx, s, size, max_w, max_lines=1, min_size=40, **kw):
    return _fit_all(ctx, [s], size, max_w, max_lines, min_size, **kw)[0]


def _content_bottom(fn, box):
    x0, y0, w, h = box
    return (fn.y - 16) if fn is not None else y0 + h


def _rect_drawing(ctx, w, h, fill, color=None, width=5, open_bottom=False, max_dur=1.0):
    """Rectangle traced from the bottom-left corner upward; fill pops after."""
    p = width
    pts = [(p, h + p), (p, p), (w + p, p), (w + p, h + p)]
    if not open_bottom:
        pts.append((p, h + p))
    poly = [(p, h + p), (p, p), (w + p, p), (w + p, h + p)]
    return ctx.strokes((w + 2 * p, h + 2 * p), [pts], color=color, width=width,
                       fills=[(poly, fill)] if fill else None, max_dur=max_dur)


def _block_arrow(ctx, aw, ah, up, color):
    """Bold filled arrow (shaft + head), traced from the shaft end."""
    p = 7
    sw, hh, cx = aw * .46, min(ah * .45, aw * .95), aw / 2 + p
    pts = [(cx - sw / 2, ah + p), (cx - sw / 2, hh + p), (p, hh + p), (cx, p),
           (aw + p, hh + p), (cx + sw / 2, hh + p), (cx + sw / 2, ah + p), (cx - sw / 2, ah + p)]
    if not up:
        pts = [(x, ah + 2 * p - y) for x, y in pts]
    return ctx.strokes((aw + 2 * p, ah + 2 * p), [pts], width=6, fills=[(pts[:-1], color)], max_dur=.9)


# ================================================================== bars
def build_bars(v, beat, box, ctx):
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    multi = bool(v.get('groups'))
    groups = [g for g in (v.get('groups') or [{'rows': v.get('rows') or []}]) if g.get('rows')]
    if not groups:
        return
    times = [[_when(ctx, beat, r, t0 + .5 + .4 * i) for i, r in enumerate(g['rows'][:6])] for g in groups]
    t_end = max(max(ts) for ts in times) + .3
    trend = v.get('trend', multi)
    _, top = page_title(ctx, v, box, t0)
    fn = footnote(ctx, v, box, t_end)
    bottom = _content_bottom(fn, box)
    made, flat = [], 0

    if v.get('unit'):                 # value-axis caption under the title
        u = ctx.text(ctx.T(v['unit']), 42, color=SOFT_INK, max_w=w * .55, max_lines=1, pace=1.5, min_size=40)
        ctx.add(u, x0 + 10, top - 6, t0)
        top += u.size[1] - 2
    if multi and len(groups) > 1:     # say the scales differ: footnote line when it fits
        s = 'each card has its own scale' if ctx.lang == 'en' else '每张卡片刻度各自独立'
        note = ctx.text(s, 40, color=SOFT_INK, pace=1.6)
        nx = x0 + w - 10 - note.size[0]
        if fn is not None and fn.x + fn.w + 50 > nx:
            ctx.add(note, x0 + 10, bottom - note.size[1], t_end)
            bottom -= note.size[1] + 10
        else:
            ctx.add(note, nx, y0 + h - note.size[1], t_end)
            if fn is None:
                bottom -= note.size[1] + 16

    area_x0, area_x1 = x0 + 10, x0 + w - 10
    dd = None
    if v.get('doodle') and not multi:
        ds = min(400, bottom - top - 120)
        dd = ctx.doodle(v['doodle'], (int(ds * 1.25), ds))
        area_x1 = x0 + w - 20 - dd.size[0] - 50

    G = len(groups)
    gap = 60
    pw = (area_x1 - area_x0 - gap * (G - 1)) / G
    for gi, g in enumerate(groups):
        rows, ts = g['rows'][:6], times[gi]
        tg = min(ts) if multi else t0
        px0 = area_x0 + gi * (pw + gap)
        gparts = []
        ptop, pbot = top, bottom
        if multi:
            ptop, pbot = top + 8, bottom - 4
            card = _rect_drawing(ctx, pw - 10, pbot - ptop - 10, CARD, width=5, max_dur=.8)
            gparts.append(ctx.add(card, px0, ptop, tg))
            if g.get('label'):
                gl = _fit(ctx, g['label'], 52, pw - 80)
                gparts.append(ctx.add(gl, px0 + 34, ptop + 18, tg))
                ptop += 18 + gl.size[1]
            pbot -= 16
        n = len(rows)
        arrow_w = int(min(150, max(90, pw * .17))) if trend and n >= 2 else 0
        bx0 = px0 + (30 if multi else 0)
        bx1 = px0 + pw - (30 if multi else 0) - (arrow_w + 40 if arrow_w else 0)
        slot = min((bx1 - bx0) / n, 440)
        gx0 = bx0 + (bx1 - bx0 - slot * n) / 2
        bw = min(230, slot * .6)
        lab_s = [ctx.T(r.get('label')) for r in rows]        # one line at >= 40 px beats two lines
        one = all(_fits(ctx, s, 40, slot - 24, 1) for s in lab_s if s)
        labels = _fit_all(ctx, lab_s, 44, slot - 24, max_lines=1 if one else 2, align='center', pace=1.4)
        baseline = pbot - max(lb.size[1] for lb in labels) - 12
        val_size = 72 if n <= 3 else 60 if n == 4 else 50
        hl = [bool(r.get('highlight')) for r in rows]
        if not any(hl):
            hl[-1] = True
        values = _fit_all(ctx, [r.get('display') for r in rows], val_size, slot - 20, align='center',
                          colors=[ctx.color if k else ink.INK for k in hl])
        hmax = baseline - (ptop + max(vl.size[1] for vl in values) + 22)   # room for the tallest bar's value
        vals = [max(0., float(r.get('value', 0))) for r in rows]
        vmax = max(vals) or 1.
        ax0 = max(gx0 - 30, px0 + 22) if multi else gx0 - 30     # never run into the card border
        ax1 = gx0 + slot * n + 30
        axis = ctx.strokes((ax1 - ax0, 16), [[(6, 8), (ax1 - ax0 - 6, 8)]], width=5, max_dur=.5)
        gparts.append(ctx.add(axis, ax0, baseline - 8, tg))
        for i, r in enumerate(rows):
            cx = gx0 + slot * (i + .5)
            bh = 0 if vals[i] <= 0 else max(10., vals[i] / vmax * hmax)
            parts = []
            if bh:
                bar = _rect_drawing(ctx, bw, bh, ctx.color if hl[i] else mix(ctx.color, .6), open_bottom=True)
                parts.append(ctx.add(bar, cx - bw / 2 - 5, baseline - bh - 5, ts[i]))
            val = values[i]
            parts.append(ctx.add(val, cx - val.size[0] / 2, baseline - bh - 10 - val.size[1], ts[i]))
            lab = labels[i]
            parts.append(ctx.add(lab, cx - lab.size[0] / 2, baseline + 10, ts[i]))
            ctx.register(v.get('id'), flat, parts)
            gparts += parts
            flat += 1
        if arrow_w and vals[-1] != vals[0]:
            up = vals[-1] > vals[0]
            ah = min(300, baseline - ptop - 40)
            ar = _block_arrow(ctx, arrow_w - 14, ah, up, UP_GREEN if up else DOWN_RED)
            gparts.append(ctx.add(ar, gx0 + slot * n + 40, ptop + (baseline - ptop - ah) / 2, max(ts) + .1))
        ctx.register(v.get('id'), f'g{gi}', gparts)
        made += gparts
        if dd is not None:   # drawn after the numbers, centred right of the bars on the baseline
            free0 = gx0 + slot * n + 30
            made.append(ctx.add(dd, free0 + (x0 + w - 10 - free0 - dd.size[0]) / 2, baseline - dd.size[1], t_end - .1))
    ctx.register(v.get('id'), 'all', made)


# ================================================================== coins
def _coin_stack(ctx, n, rx, ry, ct):
    """``n`` gold coins traced bottom-up; the top face pops in pale gold."""
    p = 6
    W, H = 2 * rx + 2 * p, n * ct + 2 * ry + 2 * p
    cx, base = rx + p, H - p - ry
    arc = [math.pi - math.pi * k / 20 for k in range(21)]      # left -> bottom -> right

    def lower(yc, rev=False):
        pts = [(cx + rx * math.cos(a), yc + ry * math.sin(a)) for a in arc]
        return pts[::-1] if rev else pts
    lines, fills = [], []
    for k in range(n):
        yb, yt = base - k * ct, base - (k + 1) * ct
        lines.append([(cx - rx, yt), *lower(yb), (cx + rx, yt)])
        fills.append(([(cx - rx, yt), *lower(yb), *lower(yt, rev=True)], GOLD_SIDE))
    ytop = base - n * ct
    face = ink.circle_points(cx, ytop, rx, ry, start=math.pi, n=48)
    ring = ink.circle_points(cx, ytop, rx * .62, ry * .5, start=math.pi, n=36)
    lines += [face, ring]
    fills.append((face, GOLD_FACE))
    return ctx.strokes((W, H), lines, width=5, fills=fills, max_dur=.35 + .06 * n)


def build_coins(v, beat, box, ctx):
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    groups = (v.get('groups') or [])[:3]
    if not groups:
        return
    times = [_when(ctx, beat, g, t0 + .5 + 1.5 * i) for i, g in enumerate(groups)]
    title, top = page_title(ctx, v, box, t0)
    bottom = _content_bottom(footnote(ctx, v, box, max(times) + .3), box)
    if v.get('unit'):                 # key on the title line when it fits
        u = ctx.text(ctx.T(v['unit']), 42, color=SOFT_INK, max_w=w * .5, max_lines=1, pace=1.5, min_size=40)
        ux = x0 + w - 10 - u.size[0]
        if title is not None and title.x + title.w + 60 < ux:
            ctx.add(u, ux, title.y + title.h - u.size[1] - 4, t0 + .2)
        else:
            ctx.add(u, ux, top - 6, t0 + .2)
            top += u.size[1]
    counts = [max(0, min(60, int(g.get('count', 0)))) for g in groups]
    stacks = [[10] * (c // 10) + ([c % 10] if c % 10 else []) for c in counts]
    total = max(1, sum(len(s) for s in stacks))
    ggap = 220
    pitch = min(200, (w - 120 - ggap * (len(groups) - 1)) / total)
    widths = [pitch * max(1, len(s)) for s in stacks]
    labels = _fit_all(ctx, [g.get('label') for g in groups], 46, [max(gw, 380) for gw in widths], max_lines=2,
                      align='center', pace=1.3)
    values = _fit_all(ctx, [g.get('display') for g in groups], 100, [max(gw, 380) for gw in widths], min_size=56,
                      color=ctx.color, align='center')
    lab_h = max(lb.size[1] for lb in labels)
    val_h = max(vl.size[1] for vl in values)
    # coin size from the width, then shrink until a 10-high stack fits under the values
    rx = pitch / 2 - 14
    while True:
        ry, ct = rx * .32, rx * .3
        baseline = bottom - lab_h - ry - 20      # centre line of the bottom coins' lower rims
        if rx <= 30 or 10 * ct + 2 * ry + 12 <= baseline - top - val_h - 10:
            break
        rx -= 2
    cursor = x0 + (w - sum(widths) - ggap * (len(groups) - 1)) / 2
    made = []
    for gi, sts in enumerate(stacks):
        ti, gw, cx = times[gi], widths[gi], cursor + widths[gi] / 2
        tallest = max([n * ct + ry + 6 for n in sts] or [0])
        # the number is written as it is spoken, its label under it, then the coins pile up between
        val, lab = values[gi], labels[gi]
        parts = [ctx.add(val, cx - val.size[0] / 2, baseline - tallest - 14 - val.size[1], ti),
                 ctx.add(lab, cx - lab.size[0] / 2, baseline + ry + 14, ti)]
        for si, n in enumerate(sts):
            st = _coin_stack(ctx, n, rx, ry, ct)
            parts.append(ctx.add(st, cursor + pitch * (si + .5) - st.size[0] / 2,
                                 baseline - st.size[1] + ry + 6, ti))
        ctx.register(v.get('id'), gi, parts)
        made += parts
        cursor += gw + ggap
    ctx.register(v.get('id'), 'all', made)


# ================================================================== grid100
def _square_marks(ctx, cells, cell, hatch):
    """Coloured (or hatched) squares for grid cell indices; one drawing in grid coords."""
    side = cell * 10
    inset = 5
    lines, fills = [], []
    for k in cells:
        r, c = divmod(k, 10)
        a, b = c * cell + inset, r * cell + inset
        s = cell - 2 * inset
        sq = [(a, b), (a + s, b), (a + s, b + s), (a, b + s)]
        lines.append(sq + [sq[0]])
        if hatch:
            fills.append((sq, mix(ctx.color, .72)))
            for j in (.3, .65, 1.0, 1.35, 1.7):
                d = s * j
                lines.append([(a + max(0, d - s), b + min(s, d)), (a + min(s, d), b + max(0, d - s))])
        else:
            fills.append((sq, ctx.color))
    return ctx.strokes((side + 8, side + 8), lines, color=ctx.color, width=4, fills=fills,
                       max_dur=min(2.0, .5 + .08 * len(cells)))


def _swatch(ctx, kind, s):
    p = 5
    sq = [(p, p), (s + p, p), (s + p, s + p), (p, s + p)]
    if kind == 'filled':
        return ctx.strokes((s + 2 * p, s + 2 * p), [sq + [sq[0]]], color=ctx.color, width=4,
                           fills=[(sq, ctx.color)], max_dur=.4)
    lines, fills = [sq + [sq[0]]], [(sq, mix(ctx.color, .72) if kind == 'hatched' else CARD)]
    if kind == 'hatched':
        for j in (.35, .7, 1.05, 1.4, 1.75):
            d = s * j
            lines.append([(p + max(0, d - s), p + min(s, d)), (p + min(s, d), p + max(0, d - s))])
    return ctx.strokes((s + 2 * p, s + 2 * p), lines, color=ctx.color if kind != 'empty' else ink.INK,
                       width=4, fills=fills, max_dur=.5)


def build_grid100(v, beat, box, ctx):
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    legend = v.get('legend') or []
    times = [_when(ctx, beat, it, t0 + 1 + .5 * i) for i, it in enumerate(legend)]
    tf = ctx.time_of(beat, v.get('fill_trigger')) if v.get('fill_trigger') else t0 + .3
    _, top = page_title(ctx, v, box, t0)
    bottom = _content_bottom(footnote(ctx, v, box, max(times + [tf]) + .3), box)
    filled = max(0, min(100, int(v.get('filled', 0))))
    hatched = max(0, min(100 - filled, int(v.get('hatched', 0))))
    side = int(min(bottom - top - 16, 640) // 10 * 10)
    cell = side / 10
    gx, gy = x0 + 50, top + (bottom - top - side) / 2
    frame = [(4, 4), (side + 4, 4), (side + 4, side + 4), (4, side + 4), (4, 4)]
    fr = ctx.add(ctx.strokes((side + 8, side + 8), [frame], width=5, fills=[(frame[:-1], CARD)], max_dur=.8),
                 gx - 4, gy - 4, t0)
    inner = [[(cell * k + 4, 4), (cell * k + 4, side + 4)] for k in range(1, 10)]
    inner += [[(4, cell * k + 4), (side + 4, cell * k + 4)] for k in range(1, 10)]
    gl = ctx.add(ctx.strokes((side + 8, side + 8), inner, color=(150, 150, 150), width=3, max_dur=1.0),
                 gx - 4, gy - 4, t0)
    made = [fr, gl]
    ctx.register(v.get('id'), 'grid', [fr])
    # legend column: optional doodle, then one line per legend item (swatch + text)
    lx0, lx1 = gx + side + 100, x0 + w - 20
    items = []                                   # (height, [(drawing, dx, dy)], trigger, key)
    if v.get('doodle'):
        dd = ctx.doodle(v['doodle'], (min(420, lx1 - lx0), 270))
        items.append((dd.size[1], [(dd, 0, 0)], max(times + [tf]) + .1, None))   # illustration last
    sw_s = 60
    for i, it in enumerate(legend):
        kind = it.get('swatch')
        pieces, tx = [], 0
        if kind in ('filled', 'hatched', 'empty'):
            pieces.append((_swatch(ctx, kind, sw_s), 0))
            tx = sw_s + 34
        elif kind == 'both':
            pieces += [(_swatch(ctx, 'filled', sw_s), 0), (_swatch(ctx, 'hatched', sw_s), sw_s + 14)]
            tx = 2 * sw_s + 48
        txt = _fit(ctx, it.get('text'), 56, lx1 - lx0 - tx, max_lines=2, min_size=40, pace=1.2)
        hh = max(txt.size[1], sw_s + 10)
        placed = [(d, dx, (hh - d.size[1]) / 2) for d, dx in pieces + [(txt, tx)]]
        items.append((hh, placed, times[i], i))
    gap = 46
    total = sum(it[0] for it in items) + gap * max(0, len(items) - 1)
    cy = top + max(0, (bottom - top - total) / 2)
    for hh, placed, ti, key in items:
        els = [ctx.add(d, lx0 + dx, cy + dy, ti) for d, dx, dy in placed]
        if key is not None:
            ctx.register(v.get('id'), key, els)
        made += els
        cy += hh + gap
    # squares colour in after any legend line due at the same moment: the number is
    # written as it is spoken, then the grid fills (as coins pile up under their number)
    if filled:
        fe = ctx.add(_square_marks(ctx, range(filled), cell, False), gx, gy, tf, layer=1)
        ctx.register(v.get('id'), 'filled', [fe])
        made.append(fe)
    if hatched:
        he = ctx.add(_square_marks(ctx, range(filled, filled + hatched), cell, True), gx, gy, tf, layer=1)
        ctx.register(v.get('id'), 'hatched', [he])
        made.append(he)
    ctx.register(v.get('id'), 'all', made)


BUILDERS = {'bars': build_bars, 'coins': build_coins, 'grid100': build_grid100}

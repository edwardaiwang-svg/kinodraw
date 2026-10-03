"""Logic-diagram page builders: dial, flow (chain | loop), split.

Full-board pages (box = (x, y, w, h), world coords). Everything is drawn by the
hand: ink outlines traced first, tints pop after; text is glyph-traced.
"""
from __future__ import annotations

import math
import re

from . import ink
from .scenes import SOFT_INK, arrow_polys, footnote, mix, page_title

GREEN, LIME, YELLOW, ORANGE, RED = (67, 160, 71), (156, 204, 101), (253, 216, 53), (251, 140, 0), (229, 57, 53)
SCALE = [GREEN, LIME, YELLOW, ORANGE, RED]
GHOST = (160, 160, 160)


def _strokes(ctx, polys, color=None, width=6, fills=None, pad=10, **kw):
    """Ink strokes given in world coordinates -> (drawing, x, y)."""
    pts = [p for poly in polys for p in poly] + [p for poly, _ in (fills or []) for p in poly]
    bx = min(p[0] for p in pts) - pad - width
    by = min(p[1] for p in pts) - pad - width
    bw = max(p[0] for p in pts) - bx + pad + width
    bh = max(p[1] for p in pts) - by + pad + width

    def loc(poly):
        return [(x - bx, y - by) for x, y in poly]
    dr = ctx.strokes((bw, bh), [loc(p) for p in polys], color=color, width=width,
                     fills=[(loc(p), c) for p, c in fills] if fills else None, **kw)
    return dr, bx, by


def _put(ctx, polys, t, color=None, width=6, fills=None, layer=0, after=None, **kw):
    dr, x, y = _strokes(ctx, polys, color=color, width=width, fills=fills, **kw)
    return ctx.add(dr, x, y, t, layer=layer, after=after)


def _head(pts, head):
    (px, py), (ex, ey) = pts[-3], pts[-1]
    a = math.atan2(ey - py, ex - px)
    return [(ex - head * math.cos(a - .45), ey - head * math.sin(a - .45)), (ex, ey),
            (ex - head * math.cos(a + .45), ey - head * math.sin(a + .45))]


def _trig(ctx, beat, item, fallback):
    return ctx.time_of(beat, item.get('trigger')) if item.get('trigger') else fallback


def _clause_break(s, lang, size, max_w):
    """Two lines split after a clause mark (，：, · …) when both fit and neither is under 40% of the other."""
    best = None
    for m in re.finditer(r'[，；：、]|[,;:·](?=\s)', s):
        a, b = s[:m.end()].strip(), s[m.end():].strip()
        if not b:
            continue
        wa, wb = ink.text_width(a, lang, size), ink.text_width(b, lang, size)
        if max(wa, wb) <= max_w and min(wa, wb) >= .4 * max(wa, wb) and (best is None or abs(wa - wb) < best[0]):
            best = (abs(wa - wb), [a, b])
    return best[1] if best else None


def _text(ctx, s, size, max_w, max_lines=3, color=None, align='left', pace=1.0, min_size=40):
    """ctx.text with balanced line breaks (same line count, narrowest width) - no orphan words.

    Two-line text breaks at a clause mark when one is near the middle, and an EN line never
    starts with a bare '/'. Board text stays >= 40 px (contract)."""
    lines, size = ink.fit_text(s, ctx.lang, max_w, max_lines, size, min_size=min_size)
    if len(lines) > 1:
        lo, hi = max_w * .4, max_w
        for _ in range(12):
            mid = (lo + hi) / 2
            if len(ink.wrap_words(s, ctx.lang, size, mid)) <= len(lines):
                hi = mid
            else:
                lo = mid
        lines = ink.wrap_words(s, ctx.lang, size, hi)
    if len(lines) == 2:
        lines = _clause_break(s, ctx.lang, size, max_w) or lines
    for i in range(1, len(lines)):
        if lines[i].startswith('/ ') and ink.text_width(lines[i - 1] + ' /', ctx.lang, size) <= max_w:
            lines[i - 1], lines[i] = lines[i - 1] + ' /', lines[i][2:]
    return ink.TextDrawing(lines, ctx.lang, size, color=color or ink.INK, align=align, pace=pace)


# ================================================================== dial
def _gp(cx, cy, r, val):
    """Point on the gauge at value 0 (left) .. 1 (right), over the top."""
    a = math.pi * (1 - val)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def _arc(cx, cy, r, v0, v1):
    n = max(6, int(abs(v1 - v0) * 70))
    return [_gp(cx, cy, r, v0 + (v1 - v0) * k / n) for k in range(n + 1)]


def _needle(cx, cy, val, length, base=15, tail=14):
    a = math.pi * (1 - val)
    ux, uy = math.cos(a), -math.sin(a)
    px, py = -uy, ux
    tip = (cx + ux * length, cy + uy * length)
    bl = (cx + px * base - ux * tail, cy + py * base - uy * tail)
    br = (cx - px * base - ux * tail, cy - py * base - uy * tail)
    return [bl, tip, br, bl]


def build_dial(v, beat, box, ctx):
    """Semicircle gauge with N labelled zones; ghost needle -> new needle."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    labels = [ctx.T(s) for s in (v.get('labels') or [])] or ['']
    n = len(labels)
    mids = [(i + .5) / n for i in range(n)]
    sides = []
    for m in mids:
        c = math.cos(math.pi * (1 - m))
        sides.append('left' if c < -.35 else ('right' if c > .35 else 'top'))
    labs = [_text(ctx, s, 52, max_w=400, max_lines=2, pace=1.3,
                  align={'left': 'right', 'right': 'left', 'top': 'center'}[sd])
            for s, sd in zip(labels, sides)]
    cap = None
    if v.get('caption'):
        cap = ctx.text(ctx.T(v['caption']), 56, color=ctx.color, max_w=w - 240, max_lines=1,
                       align='center', min_size=40)
    cap_h = cap.size[1] if cap else 0
    hub_r = 26
    cy = y0 + h - cap_h - hub_r - 12
    top_h = max([l.size[1] for l, sd in zip(labs, sides) if sd == 'top'] or [0])
    side_w = max([l.size[0] for l, sd in zip(labs, sides) if sd != 'top'] or [0])
    R = min(470, cy - top - top_h - 14, (w / 2 - 20 - side_w - 40) / .87)
    cx = x0 + w / 2
    B = R * .28
    Ri = R - B
    nv = v.get('needle') or {}
    v_from = min(1., max(0., float(nv.get('from', nv.get('to', .5)))))
    v_to = min(1., max(0., float(nv.get('to', v_from))))
    tn = _trig(ctx, beat, nv, t0 + 2)
    made = []
    for i in range(n):
        ti = t0 + .3 * i
        col = SCALE[round(i * (len(SCALE) - 1) / max(1, n - 1))] if n > 1 else YELLOW
        va, vb = i / n, (i + 1) / n
        poly = _arc(cx, cy, R, va, vb) + _arc(cx, cy, Ri, vb, va)
        poly.append(poly[0])
        seg = _put(ctx, [poly], ti, width=6, fills=[(poly[:-1], mix(col, .15))], max_dur=.6)
        lab = labs[i]
        if sides[i] == 'top':
            ax, ay = _gp(cx, cy, R + 10, mids[i])
            lx, ly = ax - lab.size[0] / 2, ay - lab.size[1]
        else:
            ax, ay = _gp(cx, cy, R + 34, mids[i])
            lx = ax - lab.size[0] if sides[i] == 'left' else ax
            ly = ay - lab.size[1] / 2
        lel = ctx.add(lab, lx, ly, ti)
        ctx.register(v.get('id'), i, [seg, lel])
        made += [seg, lel]
    ticks = []
    for k in range(11):
        r1 = Ri - (30 if k % 5 == 0 else 16)
        ticks.append([_gp(cx, cy, Ri - 6, k / 10), _gp(cx, cy, r1, k / 10)])
    made.append(_put(ctx, ticks, t0 + .3 * n, color=SOFT_INK, width=4, max_dur=.4))
    length = R - B * .42
    if abs(v_to - v_from) > 1e-3:
        g = _needle(cx, cy, v_from, length)
        made.append(_put(ctx, [g], t0 + .3 * n, color=GHOST, width=4, fills=[(g[:-1], (214, 214, 212))], max_dur=.4))
    hub = ink.circle_points(cx, cy, hub_r, hub_r, n=40)
    made.append(_put(ctx, [hub], t0 + .3 * n, width=5, fills=[(hub, ink.INK)], layer=1, max_dur=.3))
    parts = []
    ra = Ri - 50                      # just inside the ticks: the longest arc that clears them
    dv = 24 / (math.pi * ra)          # ~24 px clear of each needle
    if abs(v_to - v_from) > 2 * dv + .02:
        s = 1 if v_to > v_from else -1
        pts = _arc(cx, cy, ra, v_from + s * dv, v_to - s * dv)
        parts.append(_put(ctx, [pts, _head(pts, 28)], tn, color=ctx.color, width=12, max_dur=.6))
    nd = _needle(cx, cy, v_to, length)
    nel = _put(ctx, [nd], tn, width=5, fills=[(nd[:-1], ink.INK)], max_dur=.6)
    parts.append(nel)
    ctx.register(v.get('id'), 'needle', parts)
    made += parts
    if cap:
        cel = ctx.add(cap, cx - cap.size[0] / 2, y0 + h - cap_h, tn, after=nel)
        ctx.register(v.get('id'), 'caption', [cel])
        made.append(cel)
    ctx.register(v.get('id'), 'all', made)


# ================================================================== flow
def _exit(size, ux, uy, pad=16):
    """Distance from a box centre to its edge along (ux, uy), plus a gap."""
    hw, hh = size[0] / 2, size[1] / 2
    return min(hw / abs(ux) if abs(ux) > 1e-6 else 1e9, hh / abs(uy) if abs(uy) > 1e-6 else 1e9) + pad


def _overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


NEGATED = re.compile(r"^\s*(?:(?:does|do|did|is|are|was|were)\s+not|doesn't|don't|didn't|isn't|aren't|not|never)\b"
                     r"|^\s*[不没未]")
OPERATORS = {'÷', '×', '+', '−', '-', '=', '≈'}


def _edge(ctx, pa, pb, sa, sb, center, t, box, avoid, label=None, k=.16, width=9, head=26, label_in=True,
          max_bend=1e9, blocked=False):
    """Arrow from node a to node b (centres pa, pb; drawing sizes sa, sb), bowed away from centre.

    A blocked edge (label "does not accrue") is a grey arrow struck through with a red X, so a
    glance reads "no flow" instead of "flows"."""
    dx, dy = pb[0] - pa[0], pb[1] - pa[1]
    d = math.hypot(dx, dy) or 1
    ux, uy = dx / d, dy / d
    ra, rb = _exit(sa, ux, uy), _exit(sb, ux, uy)
    if d - ra - rb < 70:
        # crowded nodes: pull the ends into the doodles' padding rather than let the arrow flip backwards
        f = max(0., d - 70) / (ra + rb)
        ra, rb = ra * f, rb * f
    sx, sy = pa[0] + ux * ra, pa[1] + uy * ra
    ex, ey = pb[0] - ux * rb, pb[1] - uy * rb
    L = math.hypot(ex - sx, ey - sy)
    nx, ny = -uy, ux
    mx, my = (sx + ex) / 2, (sy + ey) / 2
    out = 1 if (mx - center[0]) * nx + (my - center[1]) * ny > 0 else -1
    bend = out * max(0., min(k * L, max_bend))
    polys = arrow_polys(sx, sy, ex, ey, head=head, bend=bend)
    els = [_put(ctx, polys, t, color=SOFT_INK if blocked else ctx.color, width=width, max_dur=.8)]
    px, py = mx + nx * bend / 2, my + ny * bend / 2
    gap = 14 + width
    if blocked:
        s = 22
        els.append(_put(ctx, [[(px - s, py - s), (px + s, py + s)], [(px + s, py - s), (px - s, py + s)]], t,
                        color=RED, width=11, max_dur=.4, after=els[0]))
        avoid.append((px - s, py - s, px + s, py + s))
        gap = 14 + s + 6
    if label:
        sym = len(label.strip()) == 1 and not label.strip().isalnum()   # a lone symbol reads only when big
        lab = _text(ctx, label, 64 if sym else 44, color=RED if blocked else ctx.color,
                    max_w=300, max_lines=2, align='center', pace=1.3)
        lw, lh = lab.size
        ext = abs(nx) * lw / 2 + abs(ny) * lh / 2
        x0, y0, w, h = box
        best = None
        for side in ((-out, out) if label_in else (out, -out)):
            cx_, cy_ = px + nx * side * (gap + ext), py + ny * side * (gap + ext)
            bx = min(max(cx_ - lw / 2, x0), x0 + w - lw)
            by = min(max(cy_ - lh / 2, y0), y0 + h - lh)
            bb = (bx, by, bx + lw, by + lh)
            cost = sum(_overlap(bb, o) for o in avoid)
            if best is None or cost < best[0]:
                best = (cost, bb)
            if cost == 0:
                break
        avoid.append(best[1])
        els.append(ctx.add(lab, best[1][0], best[1][1], t, after=els[-1]))
    return els


def _doodles(ctx, nodes, D, dmax):
    return [ctx.doodle(nd['doodle'], (D, D), max_dur=dm) if nd.get('doodle') else None
            for nd, dm in zip(nodes, dmax)]


def _chain_layout(ctx, nodes, box, top, dmax):
    x0, y0, w, h = box
    n = len(nodes)
    pitch = (w - 20) / n
    D = min(300, pitch - max(110, .3 * pitch))
    size = 46 if n <= 4 else 40
    labs = [_text(ctx, ctx.T(nd.get('label')), size, max_w=pitch - 24, max_lines=3, align='center', pace=1.3)
            if nd.get('label') else None for nd in nodes]
    lab_h = max([l.size[1] for l in labs if l] or [0])
    avail = y0 + h - top
    D = max(120, min(D, avail - 20 - lab_h))
    block = D + 20 + lab_h
    yd = top + max(0, (avail - block) / 2 - 10)
    dds = _doodles(ctx, nodes, D, dmax)
    pos = []
    for i, lab in enumerate(labs):
        cx = x0 + 10 + pitch * (i + .5)
        lp = (cx - lab.size[0] / 2, yd + D + 20) if lab else None
        pos.append(((cx, yd + D / 2), lp))
    return dds, labs, pos, (x0 + w / 2, y0 + h + 400)


def _loop_layout(ctx, nodes, box, top, dmax):
    x0, y0, w, h = box
    n = len(nodes)
    D = 260 if n <= 4 else 180
    size = 46 if n <= 4 else 40
    th = [-math.pi / 2 - math.pi / n + 2 * math.pi * i / n for i in range(n)]
    cs, ss = [math.cos(a) for a in th], [math.sin(a) for a in th]
    side = ['left' if c < -.45 else ('right' if c > .45 else ('top' if s < 0 else 'bottom')) for c, s in zip(cs, ss)]
    labs = []
    for nd, sd in zip(nodes, side):
        if not nd.get('label'):
            labs.append(None)
            continue
        horiz = sd in ('left', 'right')
        labs.append(_text(ctx, ctx.T(nd['label']), size, max_w=390 if horiz else 460, max_lines=3,
                          align={'left': 'right', 'right': 'left'}.get(sd, 'center'), pace=1.3))
    dds = _doodles(ctx, nodes, D, dmax)
    sizes = [dd.size if dd else (60, 60) for dd in dds]
    ext_top = max([l.size[1] + 14 - (D - sz[1]) / 2 for l, sd, sz in zip(labs, side, sizes) if l and sd == 'top'] or [0])
    ext_bot = max([l.size[1] + 14 - (D - sz[1]) / 2 for l, sd, sz in zip(labs, side, sizes) if l and sd == 'bottom'] or [0])
    ext_x = max([l.size[0] + 24 for l, sd in zip(labs, side) if l and sd in ('left', 'right')] or [0])
    ya, yb = top + max(0, ext_top) + D / 2 + 8, y0 + h - max(0, ext_bot) - D / 2 - 8
    s0, s1 = min(ss), max(ss)
    cmax = max(abs(c) for c in cs) or 1
    half = min(w / 2 - 20 - D / 2 - ext_x, (yb - ya) * 1.6)
    cxl = x0 + w / 2
    pos = []
    for i, lab in enumerate(labs):
        px = cxl + cs[i] / cmax * half
        py = ya + (ss[i] - s0) / (s1 - s0) * (yb - ya)
        dw, dh = sizes[i]
        lp = None
        if lab:
            if side[i] == 'left':
                lp = (px - dw / 2 - 24 - lab.size[0], py - lab.size[1] / 2)
            elif side[i] == 'right':
                lp = (px + dw / 2 + 24, py - lab.size[1] / 2)
            elif side[i] == 'top':
                lp = (px - lab.size[0] / 2, py - dh / 2 - 14 - lab.size[1])
            else:
                lp = (px - lab.size[0] / 2, py + dh / 2 + 14)
        pos.append(((px, py), lp))
    return dds, labs, pos, (cxl, (ya + yb) / 2)


def build_flow(v, beat, box, ctx):
    """Cause-and-effect diagram: doodle nodes joined by arrows; chain (row) or loop (cycle)."""
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    nodes = (v.get('nodes') or [])[:6]
    n = len(nodes)
    if not n:
        return
    loop = v.get('layout') == 'loop' and n >= 3
    ids = {str(nd.get('id', i)): i for i, nd in enumerate(nodes)}
    edges = []
    for e in v.get('edges') or []:
        a, b = ids.get(str(e.get('from'))), ids.get(str(e.get('to')))
        if a is not None and b is not None and a != b:
            raw = e.get('label')
            lab = ctx.T(raw) if raw else None
            key = (raw.get('en') if isinstance(raw, dict) else raw) or lab or ''   # EN decides, so both videos match
            edges.append((a, b, lab, bool(lab) and bool(NEGATED.match(key))))
    if not v.get('edges'):
        edges = [(i, i + 1, None, False) for i in range(n - 1)] + ([(n - 1, 0, None, False)] if loop else [])
    times = [_trig(ctx, beat, nd, t0 + .4 * i) for i, nd in enumerate(nodes)]
    order = sorted(range(n), key=lambda i: (times[i], i))
    info = ctx.timing['beats'][beat['id']]
    end = info.get('speech_end', info.get('end', times[order[-1]] + 4.))
    nxt = {i: (times[order[j + 1]] if j + 1 < n else max(end, times[i] + 2.)) for j, i in enumerate(order)}
    # One hand: a doodle gets what is left of the gap to the next node after its arrow and label
    # (~1.8 s), so the picture lands while its phrase is heard instead of queueing seconds behind.
    dmax = [min(2.4, max(.9, nxt[i] - times[i] - 1.8)) for i in range(n)]
    fh = 56 if v.get('footnote') else 0
    lbox = (box[0], box[1], box[2], box[3] - fh)
    dds, labs, pos, center = (_loop_layout if loop else _chain_layout)(ctx, nodes, lbox, top, dmax)
    sizes = [dd.size if dd else (60, 60) for dd in dds]
    avoid = []
    for i in range(n):
        (px, py), lp = pos[i]
        avoid.append((px - sizes[i][0] / 2, py - sizes[i][1] / 2, px + sizes[i][0] / 2, py + sizes[i][1] / 2))
        if labs[i]:
            avoid.append((lp[0], lp[1], lp[0] + labs[i].size[0], lp[1] + labs[i].size[1]))
    ebox = (box[0], top, box[2], lbox[1] + lbox[3] - top)
    drawn, done, made = set(), set(), []

    def draw_edge(k, t):
        a, b, lab, neg = edges[k]
        (pa, _), (pb, _) = pos[a], pos[b]
        if not loop and abs(a - b) > 1:
            # chain skip-edge: from the top of a, arching over the row, into the top of b
            pa, pb = (pa[0], pa[1] - sizes[a][1] / 2 - 6), (pb[0], pb[1] - sizes[b][1] / 2 - 6)
            room = min(pa[1], pb[1]) - top - (80 if lab else 14)
            els = _edge(ctx, pa, pb, (0, 0), (0, 0), center, t, ebox, avoid, lab, k=.28, label_in=False,
                        max_bend=2 * room, blocked=neg)
        elif not loop and lab and lab.strip() in OPERATORS:
            # a lone operator label makes the link an equation sign (Debt ÷ GDP = ...), not a causal arrow
            lft, rgt = (a, b) if pa[0] < pb[0] else (b, a)
            gx = (pos[lft][0][0] + sizes[lft][0] / 2 + pos[rgt][0][0] - sizes[rgt][0] / 2) / 2
            op = ctx.text(lab.strip(), 110, color=ctx.color)
            els = [ctx.add(op, gx - op.size[0] / 2, pa[1] - op.size[1] / 2, t)]
        else:
            els = _edge(ctx, pa, pb, sizes[a], sizes[b], center, t, ebox, avoid, lab,
                        k=.16 if loop else .04, label_in=loop, blocked=neg)
        done.add(k)
        made.extend(els)

    for i in order:
        t = times[i]
        (px, py), lp = pos[i]
        for k, (a, b, _, _) in enumerate(edges):
            if b == i and a in drawn and k not in done:
                draw_edge(k, t)
        parts = []
        if dds[i]:
            parts.append(ctx.add(dds[i], px - sizes[i][0] / 2, py - sizes[i][1] / 2, t))
        else:
            ring = ink.circle_points(px, py, 26, 26, n=40)
            parts.append(_put(ctx, [ring], t, width=6, fills=[(ring, mix(ctx.color, .4))], max_dur=.5))
        if labs[i]:
            parts.append(ctx.add(labs[i], lp[0], lp[1], t))
        ctx.register(v.get('id'), i, parts)
        made += parts
        drawn.add(i)
        for k, (a, b, _, _) in enumerate(edges):
            if a == i and b in drawn and k not in done:
                draw_edge(k, t)
    fn = footnote(ctx, v, box, times[order[-1]] + .5)
    if fn:
        made.append(fn)
    ctx.register(v.get('id'), 'all', made)


# ================================================================== split
def _bubble(x, y, w, h, tail_x, r=30, tail=36):
    """Rounded speech bubble (body top at y + tail) with a tail pointing up at tail_x."""
    pts = []

    def corner(cx, cy, a0, a1):
        for k in range(8):
            a = a0 + (a1 - a0) * k / 7
            pts.append((x + cx + r * math.cos(a), y + cy + r * math.sin(a)))
    top = tail
    corner(r, top + r, math.pi, 1.5 * math.pi)
    tx = min(max(tail_x - x, r + 30), w - r - 30)
    pts += [(x + tx - 28, y + top), (x + tx - 6, y), (x + tx + 28, y + top)]
    corner(w - r, top + r, 1.5 * math.pi, 2 * math.pi)
    corner(w - r, top + h - r, 0, .5 * math.pi)
    corner(r, top + h - r, .5 * math.pi, math.pi)
    pts.append(pts[0])
    return pts


def build_split(v, beat, box, ctx):
    """Two views side by side (who + doodle + speech bubble), optional verdict banner."""
    x0, y0, w, h = box
    t0 = ctx.time_of(beat, v.get('trigger'))
    _, top = page_title(ctx, v, box, t0)
    made = []
    bottom = y0 + h
    ver = v.get('verdict') or {}
    vtext = None
    if ver.get('text'):
        vtext = _text(ctx, ctx.T(ver['text']), 52, max_w=w - 220, max_lines=2, align='center')
        bottom = y0 + h - vtext.size[1] - 36 - 34
    half = w / 2
    sw = half - 90
    sides = []
    for key in ('left', 'right'):
        s = v.get(key) or {}
        who = ctx.text(ctx.T(s.get('who')), 50, color=ctx.color, max_w=sw, max_lines=1, align='center',
                       min_size=40, pace=1.4) if s.get('who') else None
        body = _text(ctx, ctx.T(s.get('text')), 50, max_w=sw - 90, max_lines=3, align='center', pace=1.3) \
            if s.get('text') else None
        sides.append((s, who, body))
    who_h = max([sd[1].size[1] for sd in sides if sd[1]] or [0])
    body_h = max([sd[2].size[1] for sd in sides if sd[2]] or [0])
    bub_h = body_h + 40 if body_h else 0
    avail = bottom - top
    Dd = max(120, min(280, avail - who_h - 10 - (bub_h + 36 + 6 if bub_h else 0) - 10))
    block = who_h + 10 + Dd + (6 + 36 + bub_h if bub_h else 0)
    ys = top + max(0, (avail - block) / 2)
    div_x = x0 + half
    dashes = []
    ya, yb = top + 6, bottom - 6
    k = 0
    while ya + k * 44 < yb:
        dashes.append([(div_x, ya + k * 44), (div_x + 2, min(yb, ya + k * 44 + 24))])
        k += 1
    made.append(_put(ctx, dashes, t0, color=SOFT_INK, width=5, max_dur=.7))
    for idx, (s, who, body) in enumerate(sides):
        ti = _trig(ctx, beat, s, t0 + .5 + 3 * idx)
        scx = x0 + half / 2 + 10 if idx == 0 else x0 + half + half / 2 - 10
        parts = []
        y = ys
        if who:
            parts.append(ctx.add(who, scx - who.size[0] / 2, y + (who_h - who.size[1]), ti))
        y += who_h + 10
        if s.get('doodle'):
            dd = ctx.doodle(s['doodle'], (Dd * 1.4, Dd), max_dur=1.6)   # wide doodles keep their height
            parts.append(ctx.add(dd, scx - dd.size[0] / 2, y + (Dd - dd.size[1]), ti))
        y += Dd + 6
        if body:
            bw = min(sw, body.size[0] + 80)
            bx = scx - bw / 2
            poly = _bubble(bx, y, bw, bub_h, scx)
            parts.append(_put(ctx, [poly], ti, width=6, fills=[(poly[:-1], (255, 255, 255))], max_dur=.7))
            parts.append(ctx.add(body, scx - body.size[0] / 2, y + 36 + (bub_h - body.size[1]) / 2, ti))
        ctx.register(v.get('id'), idx, parts)
        ctx.register(v.get('id'), ('left', 'right')[idx], parts)
        made += parts
    if vtext:
        tv = _trig(ctx, beat, ver, t0 + 7)
        bw, bh = vtext.size[0] + 90, vtext.size[1] + 36
        bx, by = x0 + (w - bw) / 2, y0 + h - bh - 4
        rect = [(bx, by + 4), (bx + bw, by), (bx + bw - 3, by + bh), (bx + 2, by + bh - 2), (bx, by + 4)]
        banner = _put(ctx, [rect], tv, color=ctx.color, width=6, fills=[(rect[:-1], mix(ctx.color, .8))], max_dur=.9,
                      after=made[-1] if made else None)
        vel = ctx.add(vtext, bx + (bw - vtext.size[0]) / 2, by + (bh - vtext.size[1]) / 2, tv, after=banner)
        ctx.register(v.get('id'), 2, [banner, vel])
        ctx.register(v.get('id'), 'verdict', [banner, vel])
        made += [banner, vel]
    ctx.register(v.get('id'), 'all', made)


BUILDERS = {'dial': build_dial, 'flow': build_flow, 'split': build_split}

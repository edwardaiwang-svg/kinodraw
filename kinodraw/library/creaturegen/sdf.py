"""2-D signed distance shapes, soft unions, contour tracing and compact SVG path text.

Every body part is a distance field (negative inside). Parts of one smooth group are merged with a
polynomial smooth minimum, so a torso, neck and head become one silhouette with filleted joins
(the method procedural-pixel-creatures uses for its pixel groups, here traced to vector outlines).
"""
from __future__ import annotations

import math

import numpy as np


# ------------------------------------------------------------------ primitives (world units, y up)
class Shape:
    def bounds(self):                      # (x0, y0, x1, y1) in world units
        raise NotImplementedError

    def sdf(self, x, y):                   # distance arrays, negative inside
        raise NotImplementedError


class Circle(Shape):
    def __init__(self, c, r):
        self.c, self.r = (float(c[0]), float(c[1])), float(r)

    def bounds(self):
        (x, y), r = self.c, self.r
        return x - r, y - r, x + r, y + r

    def sdf(self, x, y):
        return np.hypot(x - self.c[0], y - self.c[1]) - self.r


class Ellipse(Shape):
    def __init__(self, c, rx, ry, angle=0.0):
        self.c, self.rx, self.ry, self.a = (float(c[0]), float(c[1])), float(rx), float(ry), float(angle)

    def bounds(self):
        ca, sa = math.cos(self.a), math.sin(self.a)
        hx = math.hypot(self.rx * ca, self.ry * sa)
        hy = math.hypot(self.rx * sa, self.ry * ca)
        return self.c[0] - hx, self.c[1] - hy, self.c[0] + hx, self.c[1] + hy

    def sdf(self, x, y):
        ca, sa = math.cos(self.a), math.sin(self.a)
        dx, dy = x - self.c[0], y - self.c[1]
        u, v = dx * ca + dy * sa, -dx * sa + dy * ca
        k0 = np.hypot(u / self.rx, v / self.ry)
        k1 = np.hypot(u / self.rx ** 2, v / self.ry ** 2)
        return np.where(k1 > 1e-9, k0 * (k0 - 1) / np.maximum(k1, 1e-9), -min(self.rx, self.ry))


class Cone(Shape):
    """Round cone (uneven capsule) from a (radius ra) to b (radius rb)."""

    def __init__(self, a, b, ra, rb=None):
        self.a, self.b = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
        self.ra = float(ra)
        self.rb = float(ra if rb is None else rb)

    def bounds(self):
        (ax, ay), (bx, by) = self.a, self.b
        return (min(ax - self.ra, bx - self.rb), min(ay - self.ra, by - self.rb),
                max(ax + self.ra, bx + self.rb), max(ay + self.ra, by + self.rb))

    def sdf(self, x, y):
        (ax, ay), (bx, by) = self.a, self.b
        dx, dy = bx - ax, by - ay
        h = math.hypot(dx, dy)
        r1, r2 = self.ra, self.rb
        if h < 1e-6 or abs(r1 - r2) >= h:
            big = Circle(self.a, r1) if r1 >= r2 else Circle(self.b, r2)
            return big.sdf(x, y)
        ex, ey = dx / h, dy / h
        px, py = x - ax, y - ay
        qy = px * ex + py * ey
        qx = np.abs(px * ey - py * ex)
        bb = (r1 - r2) / h
        aa = math.sqrt(1 - bb * bb)
        k = -bb * qx + aa * qy
        return np.where(k < 0, np.hypot(qx, qy) - r1,
                        np.where(k > aa * h, np.hypot(qx, qy - h) - r2, qx * aa + qy * bb - r1))


class Poly(Shape):
    """Polygon (any winding), optionally rounded by ``r``."""

    def __init__(self, pts, r=0.0):
        self.p = np.asarray(pts, float)
        self.r = float(r)

    def bounds(self):
        x0, y0 = self.p.min(axis=0)
        x1, y1 = self.p.max(axis=0)
        return x0 - self.r, y0 - self.r, x1 + self.r, y1 + self.r

    def sdf(self, x, y):
        v = self.p
        d = np.full(x.shape, np.inf)
        s = np.ones(x.shape)
        n = len(v)
        for i in range(n):
            (ax, ay), (bx, by) = v[i - 1], v[i]
            ex, ey = ax - bx, ay - by
            wx, wy = x - bx, y - by
            t = np.clip((wx * ex + wy * ey) / max(ex * ex + ey * ey, 1e-12), 0, 1)
            d = np.minimum(d, (wx - ex * t) ** 2 + (wy - ey * t) ** 2)
            c1 = y >= by
            c2 = y < ay
            c3 = ex * wy > ey * wx
            flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
            s = np.where(flip, -s, s)
        return s * np.sqrt(d) - self.r


class Tube(Shape):
    """A tapering tube along a polyline (tails, trunks, necks, snakes): a chain of round cones."""

    def __init__(self, pts, radii):
        self.parts = [Cone(pts[i], pts[i + 1], radii[i], radii[i + 1]) for i in range(len(pts) - 1)]

    def bounds(self):
        bs = [p.bounds() for p in self.parts]
        return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)

    def sdf(self, x, y):
        d = self.parts[0].sdf(x, y)
        for p in self.parts[1:]:
            d = np.minimum(d, p.sdf(x, y))
        return d


# ------------------------------------------------------------------ combinations
def smin(a, b, k):
    if k <= 0:
        return np.minimum(a, b)
    h = np.maximum(k - np.abs(a - b), 0) / k
    return np.minimum(a, b) - h * h * k * 0.25


class Union(Shape):
    def __init__(self, parts, k=0.0):
        self.parts = [p for p in parts if p is not None]
        self.k = float(k)

    def bounds(self):
        bs = [p.bounds() for p in self.parts]
        return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)

    def sdf(self, x, y):
        d = self.parts[0].sdf(x, y)
        for p in self.parts[1:]:
            d = smin(d, p.sdf(x, y), self.k)
        return d


class Inter(Shape):
    def __init__(self, a, b):
        self.a, self.b = a, b

    def bounds(self):
        a, b = self.a.bounds(), self.b.bounds()
        return max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])

    def sdf(self, x, y):
        return np.maximum(self.a.sdf(x, y), self.b.sdf(x, y))


class Diff(Shape):
    def __init__(self, a, b):
        self.a, self.b = a, b

    def bounds(self):
        return self.a.bounds()

    def sdf(self, x, y):
        return np.maximum(self.a.sdf(x, y), -self.b.sdf(x, y))


class Offset(Shape):
    def __init__(self, a, d):
        self.a, self.d = a, float(d)

    def bounds(self):
        b = self.a.bounds()
        return b[0] - self.d, b[1] - self.d, b[2] + self.d, b[3] + self.d

    def sdf(self, x, y):
        return self.a.sdf(x, y) - self.d


class HalfPlane(Shape):
    """Points on the left of the directed line p -> q (y up) are inside."""

    def __init__(self, p, q, extent=1e3):
        self.p, self.q, self.e = p, q, extent

    def bounds(self):
        return -self.e, -self.e, self.e, self.e

    def sdf(self, x, y):
        (px, py), (qx, qy) = self.p, self.q
        dx, dy = qx - px, qy - py
        h = math.hypot(dx, dy) or 1.0
        return ((x - px) * dy - (y - py) * dx) / h


# ------------------------------------------------------------------ contour tracing
def contours(f: np.ndarray):
    """Closed zero-level loops of grid ``f`` (negative inside) as float (row, col) arrays."""
    pad = np.pad(f, 1, constant_values=1.0)
    inside = pad < 0
    rows, cols = pad.shape

    def point(key):
        kind, i, j = key
        if kind == 0:                       # horizontal edge (i, j) - (i, j + 1)
            a, b = pad[i, j], pad[i, j + 1]
            return i, j + a / (a - b)
        a, b = pad[i, j], pad[i + 1, j]     # vertical edge (i, j) - (i + 1, j)
        return i + a / (a - b), j

    ci = inside[:-1, :-1].astype(np.uint8) * 8 + inside[:-1, 1:] * 4 + inside[1:, 1:] * 2 + inside[1:, :-1] * 1
    cells = np.argwhere((ci > 0) & (ci < 15))
    nbr: dict = {}

    def link(p, q):
        nbr.setdefault(p, []).append(q)
        nbr.setdefault(q, []).append(p)

    for i, j in cells:
        i, j = int(i), int(j)
        c = int(ci[i, j])
        top, right, bottom, left = (0, i, j), (1, i, j + 1), (0, i + 1, j), (1, i, j)
        if c in (5, 10):                    # saddle: decide by the cell centre
            centre = (pad[i, j] + pad[i, j + 1] + pad[i + 1, j] + pad[i + 1, j + 1]) < 0
            if (c == 10) == centre:         # TL+BR inside and joined, or TR+BL inside and split
                link(top, right); link(bottom, left)
            else:
                link(top, left); link(bottom, right)
            continue
        edges = []
        tl, tr, br, bl = (c >> 3) & 1, (c >> 2) & 1, (c >> 1) & 1, c & 1
        if tl != tr:
            edges.append(top)
        if tr != br:
            edges.append(right)
        if bl != br:
            edges.append(bottom)
        if tl != bl:
            edges.append(left)
        if len(edges) == 2:
            link(edges[0], edges[1])
    loops, seen = [], set()
    for start in nbr:
        if start in seen:
            continue
        loop, prev, cur = [], None, start
        while cur not in seen:
            seen.add(cur)
            loop.append(point(cur))
            nxt = [n for n in nbr[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
        if len(loop) >= 6:
            loops.append(np.asarray(loop, float) - 1.0)    # undo the padding
    return loops


def rdp(points: np.ndarray, tol: float) -> np.ndarray:
    """Ramer-Douglas-Peucker on an open polyline (keeps both ends)."""
    keep = np.zeros(len(points), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = points[b] - points[a]
        n = math.hypot(*seg)
        rel = points[a + 1:b] - points[a]
        d = (np.abs(rel[:, 0] * seg[1] - rel[:, 1] * seg[0]) / n) if n > 1e-9 else np.hypot(rel[:, 0], rel[:, 1])
        k = int(np.argmax(d))
        if d[k] > tol:
            m = a + 1 + k
            keep[m] = True
            stack += [(a, m), (m, b)]
    return points[keep]


def simplify_loop(loop: np.ndarray, tol: float) -> np.ndarray:
    far = int(np.argmax(np.hypot(*(loop - loop[0]).T)))
    a = rdp(loop[:far + 1], tol)
    b = rdp(np.vstack([loop[far:], loop[:1]]), tol)
    return np.vstack([a[:-1], b[:-1]])


def area(loop: np.ndarray) -> float:
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def fmt(v: float) -> str:
    s = f'{v:.1f}'
    if s.endswith('.0'):
        s = s[:-2]
    if s.startswith('0.'):
        s = s[1:]
    elif s.startswith('-0.'):
        s = '-' + s[2:]
    return '0' if s in ('-0', '') else s


def pair(x, y) -> str:
    b = fmt(y)
    return f'{fmt(x)}{"" if b.startswith("-") else " "}{b}'


def smooth_d(loop: np.ndarray, corner_deg: float = 62.0, max_seg: float = 14.0) -> str:
    """Closed loop -> quadratic B-spline through edge midpoints ("M Q T T ... Z").

    Sharp vertices are doubled (the curve then passes through them), long edges are split so
    the curve hugs straight runs.
    """
    pts = []
    n = len(loop)
    for i in range(n):
        p, q = loop[i], loop[(i + 1) % n]
        pts.append(p)
        seg = math.hypot(*(q - p))
        k = int(seg // max_seg)
        for s in range(1, k + 1):
            pts.append(p + (q - p) * s / (k + 1))
    pts = np.asarray(pts)
    out = []
    m = len(pts)
    for i in range(m):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % m]
        u, v = b - a, c - b
        nu, nv = math.hypot(*u), math.hypot(*v)
        out.append(b)
        if nu > 1e-9 and nv > 1e-9:
            turn = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(u, v) / (nu * nv))))))
            if turn > corner_deg:
                out.append(b)
    pts = np.asarray(out)
    m = len(pts)
    mids = (pts + np.roll(pts, -1, axis=0)) / 2
    start = np.round(mids[-1], 1)
    ctrl = np.round(pts[0], 1)
    cur = np.round(mids[0], 1)
    d = [f'M{pair(*start)}Q{pair(*ctrl)} {pair(*cur)}']
    for i in range(1, m):            # relative steps from the rounded pen position: no drift
        nxt = np.round(mids[i], 1)
        if i % 12 == 0:              # re-anchor the reflected control point so rounding cannot accumulate
            c = np.round(pts[i], 1)
            d.append(f'q{pair(*(c - cur))} {pair(*(nxt - cur))}')
        else:
            d.append(f't{pair(*(nxt - cur))}')
        cur = nxt
    return ''.join(d) + 'Z'


def trace(shape: Shape, to_px, scale: float, offset_px: float = 0.0, tol: float = 0.6, step: float = 1.0,
          min_area: float = 6.0):
    """Simplified outline loops of ``shape`` in pixel space (list of (n, 2) arrays).

    ``to_px`` maps world to pixels with uniform ``scale``; ``offset_px`` grows (+) or shrinks (-) the
    shape in pixels.
    """
    x0, y0, x1, y1 = shape.bounds()
    if x1 <= x0 or y1 <= y0:
        return []
    (ax, ay), (bx, by) = to_px(x0, y0), to_px(x1, y1)
    grow = max(offset_px, 0) + 3
    px0, px1 = math.floor(min(ax, bx) - grow), math.ceil(max(ax, bx) + grow)
    py0, py1 = math.floor(min(ay, by) - grow), math.ceil(max(ay, by) + grow)
    gx = np.arange(px0, px1 + step, step)
    gy = np.arange(py0, py1 + step, step)
    X, Y = np.meshgrid(gx, gy)
    wx, wy = to_px.inverse(X, Y)
    f = shape.sdf(wx, wy) * scale - offset_px
    out = []
    for loop in contours(f):
        pts = np.stack([px0 + loop[:, 1] * step, py0 + loop[:, 0] * step], axis=1)
        if abs(area(pts)) < min_area:
            continue
        pts = simplify_loop(pts, tol)
        if len(pts) >= 3:
            out.append(pts)
    return out


def open_d(pts) -> str:
    """Open polyline -> smooth quadratic B-spline that starts and ends on the end points."""
    pts = np.asarray(pts, float)
    if len(pts) == 2:
        return f'M{pair(*pts[0])}L{pair(*pts[1])}'
    mids = (pts[:-1] + pts[1:]) / 2
    d = f'M{pair(*pts[0])}L{pair(*mids[0])}'
    if len(pts) > 2:
        d += f'Q{pair(*pts[1])} {pair(*mids[1])}'
        d += ''.join(f'T{pair(*mids[i])}' for i in range(2, len(mids)))
    return d + f'L{pair(*pts[-1])}'

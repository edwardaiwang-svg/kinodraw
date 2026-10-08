"""A posed figure as ordered drawing layers, fitted to a canvas and written as an outlined doodle SVG.

Layers draw back to front: far limbs, body groups, flat shade patches (clipped inside their parent and
left out of the hand-drawn ink), near limbs, face details. The same figure writes both facings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import sdf

INK = '#1B1B1B'
WHITE = '#FFFFFF'
SW = 6.0            # main outline width on a ~320 px canvas, as in the Fluent doodles
SW_DETAIL = 4.0
SW_FINE = 3.0       # the library minimum


@dataclass
class Layer:
    kind: str                      # 'fill' | 'patch' | 'line' | 'dot' | 'spot'
    shape: object = None           # sdf.Shape for fill / patch
    fill: str = 'none'
    sw: float = SW
    clip: object = None            # parent shape a patch stays inside
    pts: list = None               # world points for lines
    closed: bool = False
    c: tuple = None                # dot centre (world)
    r: float = 0.0                 # dot radius (world)
    color: str = INK
    name: str = ''
    opacity: float = 1.0           # spots only: a soft see-through light (a firefly's glow)


@dataclass
class Figure:
    layers: list = field(default_factory=list)
    anchors: dict = field(default_factory=dict)      # name -> world point (carry points, eyes ...)

    def add(self, layer: Layer):
        self.layers.append(layer)
        return layer

    def fill(self, shape, color, sw=SW, name=''):
        return self.add(Layer('fill', shape=shape, fill=color, sw=sw, name=name))

    def patch(self, shape, color, clip, name=''):
        return self.add(Layer('patch', shape=shape, fill=color, clip=clip, name=name))

    def line(self, pts, sw=SW_DETAIL, color=INK, name='', closed=False):
        return self.add(Layer('line', pts=[tuple(map(float, p)) for p in pts], sw=sw, color=color, name=name,
                              closed=closed))

    def dot(self, c, r, color=INK, name='', sw=SW_FINE):
        return self.add(Layer('dot', c=(float(c[0]), float(c[1])), r=float(r), fill=color, sw=sw, name=name))

    def spot(self, c, r, color=WHITE, name='', opacity=1.0):
        """Unoutlined small dot (eye highlight), or a see-through disc of light when ``opacity`` < 1."""
        return self.add(Layer('spot', c=(float(c[0]), float(c[1])), r=float(r), fill=color, name=name,
                              opacity=float(opacity)))

    def bounds(self):
        xs, ys = [], []
        for L in self.layers:
            if L.kind == 'fill':
                b = L.shape.bounds()
                xs += [b[0], b[2]]
                ys += [b[1], b[3]]
            elif L.kind == 'line':
                xs += [p[0] for p in L.pts]
                ys += [p[1] for p in L.pts]
            elif L.kind in ('dot', 'spot'):
                xs += [L.c[0] - L.r, L.c[0] + L.r]
                ys += [L.c[1] - L.r, L.c[1] + L.r]
        return min(xs), min(ys), max(xs), max(ys)


class Canvas:
    """World (y up) -> pixel (y down) with uniform scale; shared by every pose of one character."""

    def __init__(self, bounds, long_side=300.0, pad=12.0, min_side=200.0, max_side=600.0, ground=True):
        x0, y0, x1, y1 = bounds
        w, h = x1 - x0, y1 - y0
        s = long_side / max(w, h)
        if min(w, h) * s + 2 * pad > max_side:
            s = (max_side - 2 * pad) / min(w, h)
        if max(w, h) * s + 2 * pad > max_side:
            s = (max_side - 2 * pad) / max(w, h)
        self.s = s
        W, H = w * s + 2 * pad, h * s + 2 * pad
        self.W, self.H = max(min_side, math.ceil(W)), max(min_side, math.ceil(H))
        self.ox = (self.W - w * s) / 2 - x0 * s
        # content sits on the bottom padding (shared ground line); extra height goes above
        self.oy = self.H - pad + y0 * s if ground else (self.H + h * s) / 2 + y0 * s

    def __call__(self, x, y):
        return self.ox + x * self.s, self.oy - y * self.s

    def inverse(self, X, Y):
        return (X - self.ox) / self.s, (self.oy - Y) / self.s

    def px(self, length):
        return length * self.s


def _attrs(**kw):
    return ''.join(f' {k.replace("_", "-")}="{v}"' for k, v in kw.items() if v is not None)


class Rendered:
    """Pixel-space geometry of a figure on a canvas, writable in either facing."""

    def __init__(self, fig: Figure, canvas: Canvas):
        self.canvas = canvas
        self.items = []
        s = canvas.s
        for L in fig.layers:
            if L.kind == 'fill':
                loops = sdf.trace(L.shape, canvas, s)
                if loops:
                    self.items.append(('fill', loops, L))
            elif L.kind == 'patch':
                inset = -(SW / 2 - 0.4) if L.clip is not None else 0.0
                shape = sdf.Inter(L.shape, sdf.Offset(L.clip, inset / s)) if L.clip is not None else L.shape
                loops = sdf.trace(shape, canvas, s, min_area=10.0)
                if loops:
                    self.items.append(('patch', loops, L))
            elif L.kind == 'line':
                pts = np.array([canvas(*p) for p in L.pts])
                self.items.append(('line', [pts], L))
            elif L.kind in ('dot', 'spot'):
                c = np.array([canvas(*L.c)])
                self.items.append((L.kind, [c], L))
        self.anchors = {k: canvas(*v) for k, v in fig.anchors.items()}

    def bbox(self):
        xs, ys = [], []
        for kind, loops, L in self.items:
            for lp in loops:
                pad = L.sw / 2 if kind in ('fill', 'line') else (L.r * self.canvas.s + (L.sw / 2 if kind == 'dot' else 0))
                xs += [lp[:, 0].min() - pad, lp[:, 0].max() + pad]
                ys += [lp[:, 1].min() - pad, lp[:, 1].max() + pad]
        return min(xs), min(ys), max(xs), max(ys)

    def svg(self, facing='r') -> str:
        W, H = self.canvas.W, self.canvas.H
        flip = facing == 'l'

        def tx(lp):
            if not flip:
                return lp
            out = lp.copy()
            out[:, 0] = W - out[:, 0]
            return out

        body = []
        for kind, loops, L in self.items:
            if kind in ('fill', 'patch'):
                d = ''.join(sdf.smooth_d(tx(lp)) for lp in loops)
                rule = 'evenodd' if len(loops) > 1 else None
                if kind == 'fill':
                    body.append(f'<path d="{d}"{_attrs(fill=L.fill, fill_rule=rule, stroke_width=sdf.fmt(L.sw))}/>')
                else:
                    body.append(f'<path d="{d}"{_attrs(fill=L.fill, fill_rule=rule, stroke="none", data_noink="1")}/>')
            elif kind == 'line':
                pts = tx(loops[0])
                d = sdf.open_d(pts) + ('Z' if L.closed else '')
                color = None if L.color == INK else L.color
                body.append(f'<path d="{d}"{_attrs(fill="none", stroke=color, stroke_width=sdf.fmt(L.sw))}/>')
            else:
                (cx, cy), = tx(loops[0])
                r = sdf.fmt(L.r * self.canvas.s)
                if kind == 'dot':
                    body.append(f'<circle cx="{sdf.fmt(cx)}" cy="{sdf.fmt(cy)}" r="{r}"'
                                f'{_attrs(fill=L.fill, stroke_width=sdf.fmt(L.sw))}/>')
                else:
                    see = f"{L.opacity:.2f}" if L.opacity < 1 else None
                    body.append(f'<circle cx="{sdf.fmt(cx)}" cy="{sdf.fmt(cy)}" r="{r}"'
                                f'{_attrs(fill=L.fill, fill_opacity=see, stroke="none", data_noink="1")}/>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
                f'<g stroke="{INK}" stroke-linecap="round" stroke-linejoin="round">\n' + '\n'.join(body) +
                '\n</g>\n</svg>\n')

    def anchor(self, name, facing='r'):
        x, y = self.anchors[name]
        return (round(self.canvas.W - x if facing == 'l' else x, 1), round(y, 1))

"""Red emphasis in the Paint idiom, drawn on camera by a small pencil cursor: a wobbly circle, an arrow, an
underline, a cross-out, a check; plus "?" and "!" marks that pop in on twos."""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from .. import ink
from . import palette, text

RED = palette.RED
WIDTH = 7.


def _wobbly_ellipse(cx, cy, rx, ry, rng, turns=1.12, n=90):
    start = -2.3 + rng.uniform(-.2, .2)
    ts = np.linspace(0, 2 * math.pi * turns, n)
    wob = 1 + .035 * np.sin(ts * 2 + rng.uniform(0, 6)) + np.linspace(0, .06, n)
    return np.stack([cx + rx * wob * np.cos(start + ts), cy + ry * wob * np.sin(start + ts)], 1)


def arrow_lines(x0, y0, x1, y1, bend=.18, head=34):
    """Curved shaft from (x0, y0) to (x1, y1) and a two-stroke head."""
    n = 26
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1
    cx, cy = mx - dy / L * L * bend, my + dx / L * L * bend
    ts = np.linspace(0, 1, n)[:, None]
    a, c, b = np.array([x0, y0]), np.array([cx, cy]), np.array([x1, y1])
    shaft = (1 - ts) ** 2 * a + 2 * (1 - ts) * ts * c + ts ** 2 * b
    ang = math.atan2(*(shaft[-1] - shaft[-3])[::-1])
    tip = shaft[-1]
    left = tip - head * np.array([math.cos(ang - .5), math.sin(ang - .5)])
    right = tip - head * np.array([math.cos(ang + .5), math.sin(ang + .5)])
    return [shaft, np.array([left, tip]), np.array([tip, right])]


@dataclass
class Mark:
    """One emphasis mark. ``box`` is the target (x0, y0, x1, y1) on screen, or the arrow's (from, to) points."""
    kind: str                    # circle | underline | cross | arrow | check | question | exclaim
    box: tuple
    start: float
    seed: int = 0
    dur: float = .45
    color: tuple = RED

    def lines(self):
        rng = np.random.default_rng([self.seed, 3])
        x0, y0, x1, y1 = self.box
        if self.kind == 'circle':
            return [_wobbly_ellipse((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 + 22, (y1 - y0) / 2 + 20, rng)]
        if self.kind == 'underline':
            xs = np.linspace(x0 - 8, x1 + 8, 24)
            return [np.stack([xs, y1 + 12 + 3 * np.sin(xs / 37 + rng.uniform(0, 6)) + np.linspace(0, -6, 24)], 1)]
        if self.kind == 'cross':
            return [np.array([[x0, y0], [x1, y1]]), np.array([[x1, y0], [x0, y1]])]
        if self.kind == 'arrow':
            return arrow_lines(x0, y0, x1, y1, bend=.18 if self.seed % 2 else -.18)
        if self.kind == 'check':
            w, h = x1 - x0, y1 - y0
            return [np.array([[x0, y0 + h * .55], [x0 + w * .38, y1], [x1, y0]])]
        return []

    def extent(self):
        """Screen rectangle the finished mark covers (for layout checks)."""
        if self.kind in ('question', 'exclaim'):
            return self.box
        pts = np.vstack(self.lines())
        return (float(pts[:, 0].min() - WIDTH), float(pts[:, 1].min() - WIDTH),
                float(pts[:, 0].max() + WIDTH), float(pts[:, 1].max() + WIDTH))

    def busy(self, t):
        return self.start <= t < self.start + self.dur

    def paint(self, frame: Image.Image, t: float, variant: int = 0):
        if t < self.start:
            return
        if self.kind in ('question', 'exclaim'):
            _glyph_mark(frame, self, t, variant)
            return
        f = min(1., (t - self.start) / self.dur)
        lines = self.lines()
        lens = [float(np.sum(np.hypot(*np.diff(p, axis=0).T))) for p in lines]
        budget = f * sum(lens)
        d = ImageDraw.Draw(frame)
        tip = None
        jitter = np.random.default_rng([self.seed, variant]).normal(0, .6, 2)
        for pts, length in zip(lines, lens):
            if budget <= 0:
                break
            pts = pts + jitter
            if budget >= length:
                part = pts
            else:
                seg = np.hypot(*np.diff(pts, axis=0).T)
                cum = np.concatenate([[0], np.cumsum(seg)])
                j = int(np.searchsorted(cum, budget)) - 1
                j = max(0, min(j, len(pts) - 2))
                u = (budget - cum[j]) / (seg[j] or 1)
                part = np.vstack([pts[:j + 1], pts[j] + (pts[j + 1] - pts[j]) * u])
            budget -= length
            q = [tuple(map(float, p)) for p in part]
            if len(q) >= 2:
                d.line(q, fill=self.color + (255,), width=int(WIDTH), joint='curve')
            r = WIDTH / 2
            for x, y in (q[0], q[-1]):
                d.ellipse((x - r, y - r, x + r, y + r), fill=self.color + (255,))
            tip = q[-1]
        if f < 1 and tip is not None:
            cur = pencil()
            ink.paste(frame, cur, tip[0] - 4, tip[1] - cur.height + 4)


def _glyph_mark(frame, mark, t, variant):
    x0, y0, x1, y1 = mark.box
    glyph = '?' if mark.kind == 'question' else '!'
    age = int((t - mark.start) * 15)
    scale = 1.3 if age == 0 else (1.12 if age == 1 else 1.)
    img = glyph_image(glyph, int(y1 - y0), mark.color)
    img = img.rotate((-8, 6, -2)[variant % 3] + (mark.seed % 3 - 1) * 5, resample=Image.BICUBIC, expand=True)
    if scale != 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.BICUBIC)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ink.paste(frame, img, cx - img.width / 2, cy - img.height / 2)


@lru_cache(maxsize=64)
def glyph_image(glyph: str, height: int, color=RED) -> Image.Image:
    return text.block(glyph, 'en', max(20, int(height * .95)), color=color, outline=5, line_gap=1.)


@lru_cache(maxsize=1)
def pencil() -> Image.Image:
    """A small yellow pencil cursor, tip at its bottom-left corner (code-drawn)."""
    S = 4
    w = h = 64 * S
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(u, v):            # along the pencil (u: 0 tip .. 1 end), across (v: -1..1)
        ang = math.radians(-45)
        ax, ay = math.cos(ang), math.sin(ang)
        L, Wd = 60 * S, 7 * S
        return (4 * S + u * L * ax - v * Wd * ay, h - 4 * S + u * L * ay + v * Wd * ax)
    ink = (0, 0, 0, 255)
    d.polygon([P(.24, -1), P(.82, -1), P(.82, 1), P(.24, 1)], fill=palette.PALETTE['yellow'] + (255,), outline=ink,
              width=2 * S)
    d.polygon([P(.82, -1), P(.97, -1), P(.97, 1), P(.82, 1)], fill=palette.PALETTE['pink'] + (255,), outline=ink,
              width=2 * S)
    d.polygon([P(0, 0), P(.24, -1), P(.24, 1)], fill=palette.PALETTE['tan'] + (255,), outline=ink, width=2 * S)
    d.polygon([P(0, 0), P(.08, -.35), P(.08, .35)], fill=ink)
    return img.resize((w // S, h // S), Image.LANCZOS)

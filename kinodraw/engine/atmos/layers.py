"""Low resolution atmosphere fields. All raster work is NumPy/SciPy, with no pixel loops."""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy.ndimage import gaussian_filter, zoom

from .noise import fbm, seeded

KINDS = ('fog', 'night_sky', 'starfield', 'shooting_star', 'light_rays', 'dust', 'rain', 'embers', 'snow', 'dawn')
DEFAULT_PALETTE = {
    'background': '#071225', 'fog': '#52647d', 'stars': '#e3efff', 'glow': '#c3e5ff',
    'light_rays': '#ffe6ac', 'dust': '#ffedbe', 'rain': '#a6c8e4', 'embers': '#ff9b39',
    'snow': '#e4f1ff', 'dawn_top': '#465979', 'dawn_horizon': '#f2ac79',
}


@lru_cache(maxsize=8)
def coordinates(w, h):
    return np.linspace(0, 1, w, dtype=np.float32)[None, :], np.linspace(0, 1, h, dtype=np.float32)[:, None]


def rgba(colour, alpha):
    out = np.empty((*alpha.shape, 4), np.float32)
    out[..., :3] = np.asarray(colour, np.float32) * alpha[..., None]
    out[..., 3] = alpha
    return out


def over(back, front):
    """Porter-Duff over; both arguments and the result have premultiplied RGB."""
    return front + back * (1 - front[..., 3:4])


@lru_cache(maxsize=64)
def _particles(seed, kind):
    return seeded(seed, kind).random((400, 8), dtype=np.float32)


def _splat(w, h, x, y, weights, sigma):
    """Bilinear point deposition followed by a depth blur; edge wrapping retains particle loops."""
    plane = np.zeros((h, w), np.float32)
    ix, iy = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    fx, fy = x - ix, y - iy
    for dx, dy, weight in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                           (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        np.add.at(plane, ((iy + dy) % h, (ix + dx) % w), weights * weight)
    return gaussian_filter(plane, sigma, mode='wrap') * (2 * math.pi * sigma ** 2)


def _points(kind, t, w, h, density, seed, period):
    count = min(400, int({'starfield': 190, 'dust': 90, 'embers': 100, 'snow': 160}[kind] * density))
    p = _particles(seed, kind)[:count]
    phase = 2 * math.pi * t / period
    x, y = p[:, 0] * w, p[:, 1] * h
    if kind == 'starfield':
        weight = (.16 + .55 * p[:, 3]) * (.7 + .3 * np.sin(phase * (1 + (p[:, 4] * 3).astype(int)) + p[:, 5] * 6.28))
        weight[:min(6, count)] *= 4
    elif kind == 'dust':
        x = (p[:, 0] + .065 * np.sin(phase + p[:, 4] * 6.28)) * w
        y = (p[:, 1] + .055 * np.cos(phase + p[:, 5] * 6.28)) * h
        weight = (.12 + .38 * p[:, 3]) * (.8 + .2 * np.sin(phase + p[:, 6] * 6.28))
    elif kind == 'embers':
        travel = (p[:, 1] + t / period * (1 + (p[:, 4] * 2).astype(int))) % 1
        x = (p[:, 0] + .035 * np.sin(phase * 2 + p[:, 5] * 6.28)) * w
        y = (1 - travel) * h
        weight = (1 + p[:, 3]) * np.sin(math.pi * travel) ** 2
        weight *= .6 + .4 * np.sin(phase * 9 + p[:, 6] * 6.28) ** 2
    else:
        x = (p[:, 0] + .045 * np.sin(phase + p[:, 5] * 6.28)) * w
        y = ((p[:, 1] + t / period * (1 + (p[:, 4] * 2).astype(int))) % 1) * h
        weight = .25 + .55 * p[:, 3]
    field = np.zeros((h, w), np.float32)
    for depth, sigma in enumerate((.5, 1., 2.1)):
        mask = (p[:, 2] * 3).astype(int) == depth
        field += _splat(w, h, x[mask], y[mask], weight[mask], sigma * w / 480)
    if kind == 'starfield' and count:
        # A few brighter stars have broader halos.
        n = min(6, count)
        field += _splat(w, h, x[:n], y[:n], weight[:n] * .35, 2.6 * w / 480)
    return -np.expm1(-field)


def render(kind, t, w, h, palette, density, seed, period, options):
    x, y = coordinates(w, h)
    phase = 2 * math.pi * t / period
    colour = options.get('colour', palette.get(kind, palette['glow']))
    if kind == 'fog':
        # Fog has no sharp edges: sample its billows at one third size, then interpolate optical depth.
        fw, fh = max(2, w // 3), max(2, h // 3)
        fx, fy = coordinates(fw, fh)
        depth = np.zeros((fh, fw), np.float32)
        falloff = .22 + .78 * y ** options.get('height_falloff', 1.4)
        for i in range(3):
            field = fbm(fx * (3 + i), fy * (2 + i), t * (i + 1), (seed, i),
                        period=period, drift=(.35 + .2 * i, .1 + .06 * i))
            depth += .1 + .9 * field ** 1.7
        depth = zoom(depth, (h / fh, w / fw), order=1, prefilter=False)
        return rgba(colour, -np.expm1(-density * depth * falloff))
    if kind in ('night_sky', 'dawn'):
        if kind == 'night_sky':
            top, bottom = palette['background'], palette['fog'] * .42
            blend = y ** 1.7
        else:
            top, bottom = palette['dawn_top'], palette['dawn_horizon']
            blend = np.clip(y + .025 * math.sin(phase), 0, 1) ** .7
        rgb = top * (1 - blend[..., None]) + bottom * blend[..., None]
        out = np.ones((h, w, 4), np.float32)
        out[..., :3] = rgb
        return out
    if kind in ('starfield', 'dust', 'embers', 'snow'):
        colour = palette['stars'] if kind == 'starfield' and 'colour' not in options else colour
        return rgba(colour, _points(kind, t, w, h, density, seed, period))
    if kind == 'shooting_star':
        start, end = options.get('window', (2., 3.5))
        if t <= start or t >= end:
            return np.zeros((h, w, 4), np.float32)
        u = (t - start) / (end - start)
        head_x, head_y = .18 + .64 * u, .17 + .38 * u
        dx, dy = (x - head_x) * w, (y - head_y) * h
        angle = math.atan2(.38 * h, .64 * w)
        along = dx * math.cos(angle) + dy * math.sin(angle)
        across = -dx * math.sin(angle) + dy * math.cos(angle)
        scale = w / 480
        tail = np.exp(np.minimum(along, 0) / (43 * scale)) * np.exp(-.5 * (across / (.65 * scale)) ** 2)
        tail *= (along <= 0) & (along > -150 * scale)
        glow = np.exp(-.5 * (across / (3.3 * scale)) ** 2) * np.exp(-np.abs(along) / (25 * scale))
        head = np.exp(-.5 * (dx ** 2 + dy ** 2) / (1.25 * scale) ** 2)
        envelope = min(1., u * 10, (1 - u) * 10)
        alpha = -np.expm1(-density * envelope * (2.5 * tail + .65 * glow + 4 * head))
        return rgba(colour, alpha)
    if kind == 'light_rays':
        ox, oy = options.get('origin', (.18, -.12))
        dx, dy = (x - ox) * w / h, y - oy
        angle = np.arctan2(dx, dy) + .09 * math.sin(phase)
        beams = np.maximum(0, np.cos(angle * 19 + .2 * math.sin(phase))) ** 12
        alpha = -np.expm1(-density * .35 * beams * np.exp(-np.hypot(dx, dy) * .8))
        return rgba(colour, alpha)
    if kind == 'rain':
        p = _particles(seed, kind)[:min(400, int(240 * density))]
        travel = (p[:, 1] + t / period * (4 + (p[:, 4] * 4).astype(int))) % 1
        px = (p[:, 0] + .025 * math.sin(phase)) * w
        py = travel * h
        length = (8 + p[:, 2] * 15) * w / 480
        steps = np.linspace(0, 1, 12, dtype=np.float32)
        streak_x, streak_y = px[:, None] - length[:, None] * steps * .32, py[:, None] - length[:, None] * steps
        weights = np.broadcast_to((.06 + .16 * p[:, 3])[:, None], streak_x.shape)
        splash = np.maximum(0, 1 - np.abs(travel - .94) / .035) * .3
        spread = np.array([-4, -2, 2, 4], np.float32) * w / 480
        sx = px[:, None] + spread
        sy = np.broadcast_to(.94 * h - np.abs(spread)[None, :] * .3, sx.shape)
        field = _splat(w, h, np.concatenate((streak_x.ravel(), sx.ravel())),
                       np.concatenate((streak_y.ravel(), sy.ravel())),
                       np.concatenate((weights.ravel(), np.repeat(splash, 4))), .55 * w / 480)
        return rgba(colour, -np.expm1(-field))
    raise ValueError(f'unknown atmosphere: {kind}')

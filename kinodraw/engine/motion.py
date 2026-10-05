"""Motion kit for the collage and bold looks: easing, keyframes, a 2-D camera, paper sprites and effects,
particles and text kinetics.

Nothing here uses global randomness: whatever is random takes an explicit seed key (hashed with blake2b), so
parallel render workers produce identical frames. Key random choices by frame numbers (``on_twos``), never by
raw float times. Units: seconds, pixels at 1920 x 1080, angles in degrees clockwise on screen (like CSS).
"""
from __future__ import annotations

import bisect
import hashlib
import math
from collections import OrderedDict
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

from . import ink


# ------------------------------------------------------------------ easing and timing
def clamp01(u):
    return min(1., max(0., u))


def lerp(a, b, u):
    return a + (b - a) * u


def cubic_bezier(x1, y1, x2, y2):
    """CSS ``cubic-bezier(x1, y1, x2, y2)`` as u -> v: x(s) = u is solved by Newton, falling back to bisection."""
    cx, cy = 3 * x1, 3 * y1
    bx, by = 3 * (x2 - x1) - cx, 3 * (y2 - y1) - cy
    ax, ay = 1 - cx - bx, 1 - cy - by

    def x_of(s):
        return ((ax * s + bx) * s + cx) * s

    def curve(u):
        if u <= 0 or u >= 1:
            return float(u >= 1)
        s = u
        for _ in range(8):
            err, slope = x_of(s) - u, (3 * ax * s + 2 * bx) * s + cx
            if abs(err) < 1e-9 or abs(slope) < 1e-6:
                break
            s -= err / slope
        if not 0 <= s <= 1 or abs(x_of(s) - u) > 1e-7:
            lo, hi = 0., 1.
            for _ in range(50):
                s = (lo + hi) / 2
                lo, hi = (s, hi) if x_of(s) < u else (lo, s)
        return ((ay * s + by) * s + cy) * s
    return curve


EMPHASIZED = cubic_bezier(.05, .7, .1, 1.)          # Material 3 emphasized decelerate


def back_out(u, s=1.70158):
    """Overshoots and settles (s = 1.70158: 10% past the end)."""
    u = clamp01(u) - 1
    return u * u * ((s + 1) * u + s) + 1 if u > -1 else 0.


def expo_out(u):
    """Fast start, long settle; exactly 0 and 1 at the ends."""
    return (1 - 2 ** (-10 * clamp01(u))) / (1 - 2 ** -10)


def expo_in(u):
    return (2 ** (10 * clamp01(u)) - 1) / (2 ** 10 - 1)


def cubic_in_out(u):
    u = clamp01(u)
    return 4 * u ** 3 if u < .5 else 1 - (2 - 2 * u) ** 3 / 2


def spring(u, damping=.55, freq=2.2):
    """A damped spring from 0 to exactly 1. ``damping`` is the damping ratio (< 1); the swing peaks at u = 1/freq.
    The defaults overshoot once, by about 12%, then settle from below."""
    u = clamp01(u)
    wd = math.pi * freq
    wn = wd / math.sqrt(1 - damping * damping)
    rest = math.exp(-damping * wn * u) * (math.cos(wd * u) + damping * wn / wd * math.sin(wd * u))
    return 1 - rest * (1 - u ** 8)                    # what is left of the swing is gone at u = 1


EASING = {'linear': clamp01, 'emphasized': EMPHASIZED, 'back_out': back_out, 'expo_out': expo_out,
          'expo_in': expo_in, 'cubic_in_out': cubic_in_out, 'spring': spring}


def stagger(n, gap=.07, cap=.5):
    """Start delays for n items ``gap`` apart, squeezed evenly so the last starts no later than ``cap``."""
    if n > 1 and (n - 1) * gap > cap:
        gap = cap / (n - 1)
    return [i * gap for i in range(n)]


def on_twos(t, fps=30):
    """``t`` held on even frames: stop-motion poses change every 2 frames."""
    f = math.floor(t * fps + 1e-6)
    return (f - f % 2) / fps


def snap_to_beat(t, bpm, subdivision=1, origin=0.):
    """Nearest beat (or subdivision), with ties going to the later beat."""
    if bpm <= 0 or subdivision <= 0:
        raise ValueError('BPM and subdivision must be positive')
    step = 60. / bpm / subdivision
    return origin + math.floor((t - origin) / step + .5) * step


def speed_kick(t, speed, decay=.7, fps=30):
    """Closed-form displacement of a px/frame kick, whose speed decays every frame.

    Continuous between frame times, so sub-frame rendering and arbitrary seeks agree.
    """
    if not 0 < decay < 1 or fps <= 0:
        raise ValueError('Decay must be between 0 and 1; FPS must be positive')
    return speed * (1 - decay ** (max(0., t) * fps)) / (1 - decay)


def seeded(seed, *keys):
    """A random generator determined by its arguments alone (blake2b of their repr), never by global state."""
    digest = hashlib.blake2b(repr((seed,) + keys).encode(), digest_size=16).digest()
    return np.random.default_rng(int.from_bytes(digest, 'little'))


class Track:
    """A keyframed value: keys ``(t, value, easing)``, where the easing (a name in EASING, or a function) shapes the
    move into its key. Values are floats or tuples of floats; the first and last values hold outside the keys."""

    def __init__(self, keys):
        self.keys = sorted(((k[0], k[1], k[2] if len(k) > 2 else 'linear') for k in keys), key=lambda k: k[0])
        self.times = [k[0] for k in self.keys]

    def value(self, t):
        i = bisect.bisect_right(self.times, t)
        if i == 0 or i == len(self.keys):
            return self.keys[max(0, i - 1)][1]
        (t0, a, _), (t1, b, easing) = self.keys[i - 1], self.keys[i]
        u = (EASING[easing] if isinstance(easing, str) else easing)((t - t0) / (t1 - t0))
        if isinstance(a, (tuple, list)):
            return tuple(lerp(p, q, u) for p, q in zip(a, b))
        return lerp(a, b, u)


# ------------------------------------------------------------------ camera
class Camera2D:
    """Keys ``(t, x, y, zoom[, easing])``: (x, y) is the world point at the centre of the screen and zoom its
    magnification, so (960, 540, 1) shows the world as it is. Zoom moves in log space, so a steady zoom looks
    steady; moves ease with cubic_in_out unless a key names its own easing."""

    def __init__(self, keys, size=(1920, 1080)):
        self.size = size
        self.track = Track([(k[0], (k[1], k[2], math.log(k[3])), k[4] if len(k) > 4 else 'cubic_in_out')
                            for k in keys])

    def at(self, t):
        x, y, log_zoom = self.track.value(t)
        return x, y, math.exp(log_zoom)

    def apply(self, point, t, parallax=1.):
        """Screen position of a world point on a layer that moves ``parallax`` times as much as the camera
        (< 1 background, > 1 foreground, 0 fixed to the screen); zoom acts on it as zoom ** parallax."""
        x, y, zoom = self.at(t)
        cx, cy = self.size[0] / 2, self.size[1] / 2
        z = zoom ** parallax
        return cx + (point[0] - cx - (x - cx) * parallax) * z, cy + (point[1] - cy - (y - cy) * parallax) * z


# ------------------------------------------------------------------ paper
PAPERS = {'cream': (241, 233, 214), 'kraft': (184, 145, 102), 'grid': (246, 244, 238), 'lined': (247, 245, 239),
          'blue_wash': (243, 237, 224)}
WASH = [(86, 131, 196), (64, 112, 184), (110, 152, 206)]
GRID_STEP, RULE_STEP, RULE_TOP, MARGIN_X = 40, 44, 132, 150


def _noise(rng, shape, sigma):
    """Smooth noise with unit spread and features about ``sigma`` px across (big features computed small)."""
    k = max(1, int(sigma // 4))
    small = rng.standard_normal((shape[0] // k + 2, shape[1] // k + 2))
    field = ndimage.zoom(ndimage.gaussian_filter(small, sigma / k, mode='wrap'), k, order=1)[:shape[0], :shape[1]]
    return field / (field.std() + 1e-9)


def _deform(rng, pts, depth, spread):
    """Midpoint displacement (Tyler Hobbs' watercolour): every edge gets a new vertex pushed off by about
    ``spread`` x its length, ``depth`` times over."""
    for _ in range(depth):
        nxt = np.roll(pts, -1, axis=0)
        length = np.hypot(*(nxt - pts).T)[:, None]
        mid = (pts + nxt) / 2 + rng.standard_normal(pts.shape) * length * spread
        pts = np.stack([pts, mid], 1).reshape(-1, 2)
    return pts


def _fibres(rng, size):
    """Kraft fibres: short straight strands in every direction, darker and lighter than the paper."""
    w, h = size
    layer = Image.new('L', size, 128)
    d = ImageDraw.Draw(layer)
    n = w * h // 500
    x, y, a = rng.uniform(0, w, n), rng.uniform(0, h, n), rng.uniform(0, math.pi, n)
    length, tone = rng.uniform(4, 20, n), rng.choice([70, 80, 175, 190], n)
    for i in range(n):
        dx, dy = math.cos(a[i]) * length[i] / 2, math.sin(a[i]) * length[i] / 2
        d.line([(x[i] - dx, y[i] - dy), (x[i] + dx, y[i] + dy)], fill=int(tone[i]), width=1)
    return (np.asarray(layer.filter(ImageFilter.GaussianBlur(.6)), np.float32) - 128) * .3


def _wash(rng, size, blobs=5, layers=30, holes=40):
    """Watercolour washes (one alpha plane per blob): a deformed polygon, re-deformed for each of ``layers`` layers
    laid at 2.5% opacity, every layer pocked with a few round holes so the pigment looks mottled."""
    w, h = size
    s = 2                                             # the layers are filled at half size
    W, H = w // s + 1, h // s + 1
    count = np.zeros((blobs, H, W), np.float32)
    for b in range(blobs):
        c = rng.uniform((0, 0), (w, h)) / s
        r = rng.uniform(.2, .34) * math.hypot(w, h) / s / 2
        ang = np.linspace(0, 2 * math.pi, 10, endpoint=False) + rng.uniform(0, 1)
        base = _deform(rng, np.stack([c[0] + r * np.cos(ang), c[1] + r * np.sin(ang) * .75], 1), 4, .2)
        for _ in range(layers):
            layer = Image.new('L', (W, H), 0)
            d = ImageDraw.Draw(layer)
            d.polygon([tuple(p) for p in _deform(rng, base, 3, .13)], fill=1)
            xs, ys = rng.uniform(c[0] - 1.3 * r, c[0] + 1.3 * r, holes), rng.uniform(c[1] - r, c[1] + r, holes)
            for x, y, q in zip(xs, ys, rng.uniform(.02, .12, holes) * r):
                d.ellipse((x - q, y - q, x + q, y + q), fill=0)
            count[b] += np.asarray(layer, np.float32)
    return [ndimage.zoom(1 - .975 ** a, s, order=1)[:h, :w] for a in count]


@lru_cache(maxsize=8)
def paper_texture(size, kind='cream', seed_key=0):
    """A paper background (RGB; cached, so copy it before drawing on it): 'cream', 'kraft' (with fibres), 'grid',
    'lined' (notebook rules and a red margin) or 'blue_wash' (watercolour washes on cream)."""
    w, h = size
    rng = seeded(seed_key, 'paper', kind, tuple(size))
    kraft = kind == 'kraft'
    grain = ndimage.gaussian_filter(rng.standard_normal((h, w)), .7)
    tone = grain / grain.std() * (5 if kraft else 2.6) + _noise(rng, (h, w), 80) * (4.5 if kraft else 3)
    if kraft:
        tone += _fibres(rng, size)
    img = np.empty((h, w, 3), np.float32)
    img[:] = PAPERS[kind]
    img += tone[..., None]
    if kind in ('grid', 'lined'):
        lines = np.zeros((h, w), np.float32)
        if kind == 'grid':
            x0, y0 = (w % GRID_STEP) // 2, (h % GRID_STEP) // 2
            lines[:, x0::GRID_STEP] = lines[y0::GRID_STEP, :] = .42
            lines[:, x0::GRID_STEP * 5] = lines[y0::GRID_STEP * 5, :] = .7
            img += (np.array((112, 164, 204)) - img) * lines[..., None]
        else:
            lines[RULE_TOP::RULE_STEP, :] = .55
            img += (np.array((128, 166, 216)) - img) * lines[..., None]
            img[:, MARGIN_X:MARGIN_X + 2] += (np.array((222, 104, 104)) - img[:, MARGIN_X:MARGIN_X + 2]) * .75
    if kind == 'blue_wash':
        for k, alpha in enumerate(_wash(rng, size)):              # multiplied, as glazes of pigment are
            img *= 1 - alpha[..., None] * (1 - np.array(WASH[k % len(WASH)]) / 255)
    return Image.fromarray(np.clip(img + .5, 0, 255).astype(np.uint8), 'RGB')


# ------------------------------------------------------------------ stickers and effects
def die_cut(img, border=14, color=(255, 255, 255, 255)):
    """``img`` as a paper sticker: a ``border`` px margin of ``color`` grown around its shape (holes filled, inner
    corners rounded like a die-cut path) with an anti-aliased cut. The canvas grows by border + 2 on every side."""
    r = border                                        # radius that rounds the cut's inner corners
    m = border + r + 2
    src = Image.new('RGBA', (img.width + 2 * m, img.height + 2 * m), (0, 0, 0, 0))
    src.paste(img.convert('RGBA'), (m, m))
    shape = np.asarray(src.getchannel('A')) > 127
    grown = ndimage.binary_fill_holes(ndimage.distance_transform_edt(~shape) <= border + r)
    cut = np.clip(ndimage.distance_transform_edt(grown) - r, 0, 1)
    out = Image.new('RGBA', src.size, color)
    out.putalpha(Image.fromarray((cut * color[3] + .5).astype(np.uint8)))
    out.alpha_composite(src)
    return out.crop((r, r, out.width - r, out.height - r))


def shadow_only(img, blur=10, opacity=.35):
    """The soft black shadow of ``img``'s shape alone, on a canvas grown by 3 x blur on every side (still centred)."""
    m = math.ceil(3 * blur)
    a = Image.new('L', (img.width + 2 * m, img.height + 2 * m), 0)
    a.paste(img.getchannel('A').point(lambda v: int(v * opacity + .5)), (m, m))
    out = Image.new('RGBA', a.size, (0, 0, 0, 0))
    out.putalpha(a.filter(ImageFilter.GaussianBlur(blur)) if blur > 0 else a)
    return out


def drop_shadow(img, offset=(6, 8), blur=10, opacity=.35):
    """``img`` over its soft shadow ``offset`` px away, on a canvas grown equally on every side so the picture stays
    centred (draw it with a centre anchor)."""
    shadow = shadow_only(img, blur, opacity)
    pad = max(abs(offset[0]), abs(offset[1]))
    m = (shadow.width - img.width) // 2 + pad
    out = Image.new('RGBA', (img.width + 2 * m, img.height + 2 * m), (0, 0, 0, 0))
    out.alpha_composite(shadow, (pad + offset[0], pad + offset[1]))
    out.alpha_composite(img.convert('RGBA'), (m, m))
    return out


FIBRE = (252, 249, 242)


def torn_edge(mask_or_img, seed_key, amplitude=6, scale=18):
    """Tear the edge of an 'L' mask (returns a mask) or of a picture (returns RGBA): the outline moves inwards by
    0..2 x ``amplitude`` px of smooth noise (features ``scale`` px across, plus a finer ragged octave), and a
    picture gets the pale 2-3 px fibre rim of torn paper. The image's own border counts as an edge."""
    is_mask = mask_or_img.mode == 'L'
    img = mask_or_img if is_mask else mask_or_img.convert('RGBA')
    alpha = np.pad(np.asarray(img if is_mask else img.getchannel('A'), np.float32) / 255, 1)
    inside = alpha > .5
    depth = np.where(inside, ndimage.distance_transform_edt(inside) - .5, .5 - ndimage.distance_transform_edt(~inside))
    rng = seeded(seed_key, 'torn_edge')
    n = _noise(rng, alpha.shape, scale) + .45 * _noise(rng, alpha.shape, max(1., scale / 6))
    depth -= amplitude * (1 + np.clip(n / 1.6, -1, 1))
    torn = (np.clip(depth + .5, 0, 1) * alpha)[1:-1, 1:-1]
    if is_mask:
        return Image.fromarray((torn * 255 + .5).astype(np.uint8), 'L')
    width = 2.5 + .6 * np.clip(_noise(rng, torn.shape, scale / 2), -1.5, 1.5)          # the rim is 1.6..3.4 px
    rim = np.clip(1 - (depth[1:-1, 1:-1] - .5) / width, 0, 1) * np.clip(.75 + .35 * _noise(rng, torn.shape, .8), 0, 1)
    px = np.asarray(img, np.float32).copy()
    px[..., :3] += (np.array(FIBRE) - px[..., :3]) * (rim * .9)[..., None]
    px[..., 3] = torn * 255
    return Image.fromarray(np.clip(px + .5, 0, 255).astype(np.uint8), 'RGBA')


def _fade(img, alpha):
    out = img.copy()
    out.putalpha(img.getchannel('A').point([round(v * alpha) for v in range(256)]))
    return out


class Sprite:
    """A pre-rendered picture (sticker, word, photo) drawn at any pose. Poses are quantized (scale to 1/64, rotation
    to 0.5 degrees, alpha to 1/32) and the last POSES of them are cached, so a jitter that repeats is cheap."""
    POSES = 16

    def __init__(self, img, anchor=(.5, .5)):
        self.img = img if img.mode == 'RGBA' else img.convert('RGBA')
        self.anchor = anchor
        self._poses = OrderedDict()

    def pose(self, scale=1., rotation=0., alpha=1.):
        """(image, anchor x, anchor y) of the quantized pose, or None when it would not show."""
        key = (round(scale * 64) / 64, round(rotation * 2) / 2 % 360, round(alpha * 32) / 32)
        if key[0] <= 0 or key[2] <= 0:
            return None
        if key in self._poses:
            self._poses.move_to_end(key)
            return self._poses[key]
        self._poses[key] = pose = self._render(*key)
        if len(self._poses) > self.POSES:
            self._poses.popitem(last=False)
        return pose

    def _render(self, scale, rotation, alpha):
        if alpha < 1:                                 # a fade reuses the opaque pose
            img, ax, ay = self.pose(scale, rotation)
            return _fade(img, alpha), ax, ay
        img = self.img
        if scale != 1:
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.BICUBIC)
        ax, ay = self.anchor[0] * img.width, self.anchor[1] * img.height
        if rotation:
            vx, vy = ax - img.width / 2, ay - img.height / 2
            img = img.rotate(-rotation, Image.BICUBIC, expand=True)
            c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
            ax, ay = img.width / 2 + vx * c - vy * s, img.height / 2 + vx * s + vy * c
        return img, ax, ay

    def draw(self, canvas, x, y, scale=1., rotation=0., alpha=1.):
        """Composite onto the RGBA ``canvas`` with the anchor at (x, y), turned ``rotation`` degrees clockwise."""
        pose = self.pose(scale, rotation, alpha)
        if pose is not None:
            img, ax, ay = pose
            ink.paste(canvas, img, x - ax, y - ay)


def motion_blur(img, dx, dy, samples=5):
    """``img`` smeared along its motion during the frame (dx, dy px): the average of ``samples`` shifted copies, on a
    canvas grown equally on both sides (still centred). Under 1 px of motion it returns ``img`` itself."""
    if math.hypot(dx, dy) < 1:
        return img
    mx, my = math.ceil(abs(dx) / 2), math.ceil(abs(dy) / 2)
    px = np.asarray(img.convert('RGBA'), np.float32)
    px[..., :3] *= px[..., 3:] / 255                  # premultiplied, so the smeared edges do not darken
    h, w = px.shape[:2]
    acc = np.zeros((h + 2 * my, w + 2 * mx, 4), np.float32)
    for f in np.linspace(-.5, .5, samples):
        x, y = round(mx + f * dx), round(my + f * dy)
        acc[y:y + h, x:x + w] += px
    acc /= samples
    acc[..., :3] /= np.maximum(acc[..., 3:], 1e-3) / 255
    return Image.fromarray(np.clip(acc + .5, 0, 255).astype(np.uint8), 'RGBA')


# ------------------------------------------------------------------ masks ('L': 255 shows the new picture)
def iris_mask(size, center, radius):
    """A circle of ``radius`` px about ``center``, anti-aliased."""
    dx =(np.arange(size[0], dtype=np.float32) + .5 - center[0]) ** 2
    dy = (np.arange(size[1], dtype=np.float32) + .5 - center[1]) ** 2
    cover = np.clip(radius + .5 - np.sqrt(dy[:, None] + dx[None, :]), 0, 1)
    return Image.fromarray((cover * 255 + .5).astype(np.uint8), 'L')


def wipe_mask(size, progress, angle_deg=0, soft=24):
    """A straight wipe travelling towards ``angle_deg`` (0: left to right, 90: top to bottom) with a ``soft`` px
    edge: nothing shows at progress 0, everything at 1."""
    a = math.radians(angle_deg)
    xs, ys = np.arange(size[0], dtype=np.float32) + .5, np.arange(size[1], dtype=np.float32) + .5
    along = xs[None, :] * math.cos(a) + ys[:, None] * math.sin(a)
    lo, hi = float(along.min()), float(along.max())
    front = lo + clamp01(progress) * (hi - lo + soft)
    cover = np.clip((front - along) / max(soft, 1e-6), 0, 1)
    return Image.fromarray((cover * 255 + .5).astype(np.uint8), 'L')


def _span(n, a, b):
    """How much of each pixel 0..n-1 lies inside [a, b]."""
    x = np.arange(n, dtype=np.float32)
    return np.clip(np.minimum(x + 1, b) - np.maximum(x, a), 0, 1)


def rect_reveal(size, box, progress):
    """The box ``(x, y, w, h)`` opening from its centre: nothing at progress 0, the whole box at 1."""
    x, y, w, h = box
    p = clamp01(progress)
    cx, cy = x + w / 2, y + h / 2
    cover = np.outer(_span(size[1], cy - h * p / 2, cy + h * p / 2), _span(size[0], cx - w * p / 2, cx + w * p / 2))
    return Image.fromarray((cover * 255 + .5).astype(np.uint8), 'L')


# ------------------------------------------------------------------ particles
CONFETTI = list(ink.SECTION_COLORS.values()) + [(250, 196, 30)]


def confetti(seed_key, n, origin, t, spread=900, gravity=1600, colors=None):
    """``n`` paper bits ``t`` seconds after a burst at ``origin``: [(x, y, angle, w, h, colour, alpha)].
    They fly up and out about ``spread`` px, slowed by air drag, then flutter down, spinning and flipping (h shrinks
    as a bit turns edge-on) and fading at the end of their life. Closed form, so any frame stands on its own."""
    colors = colors or CONFETTI
    rng = seeded(seed_key, 'confetti', n)
    drag = rng.uniform(4.5, 7., n)                    # 1/s; falling speed tops out at gravity / drag
    heading = np.radians(rng.uniform(-155, -25, n))
    speed = spread * drag * rng.uniform(.25, 1., n)
    angle0, spin = rng.uniform(0, 360, n), rng.uniform(-540, 540, n)
    flip0, flip = rng.uniform(0, math.pi, n), rng.uniform(5, 13, n)
    sway, sway_f, sway0 = rng.uniform(8, 26, n), rng.uniform(2.5, 5, n), rng.uniform(0, 2 * math.pi, n)
    w, h, life = rng.uniform(10, 20, n), rng.uniform(6, 11, n), rng.uniform(1.8, 3., n)
    tint = rng.integers(len(colors), size=n)
    tt = max(0., t)
    gone = (1 - np.exp(-drag * tt)) / drag            # integral of exp(-drag * s) over [0, t]
    x = origin[0] + speed * np.cos(heading) * gone + sway * np.sin(sway_f * tt + sway0) * (1 - np.exp(-3 * tt))
    y = origin[1] + speed * np.sin(heading) * gone + gravity / drag * (tt - gone)
    alpha = np.clip((life - tt) / .5, 0, 1) if t >= 0 else np.zeros(n)
    return [(float(x[i]), float(y[i]), float((angle0[i] + spin[i] * tt) % 360), float(w[i]),
             float(h[i] * abs(math.cos(flip0[i] + flip[i] * tt))), tuple(colors[tint[i]]), float(alpha[i]))
            for i in range(n)]


def sample_points(mask, n, seed_key):
    """``n`` random points (x, y) inside a mask (bool array, or 'L' image where > 127), each within its pixel."""
    inside = np.asarray(mask) > 127 if isinstance(mask, Image.Image) else np.asarray(mask, bool)
    cells = np.argwhere(inside)
    rng = seeded(seed_key, 'sample_points', n)
    pick = cells[rng.choice(len(cells), n, replace=len(cells) < n)]
    return pick[:, ::-1] + rng.uniform(0, 1, (n, 2))


def assemble(src, dst, t, dur=.9, stagger=.25, seed_key=0):
    """Positions of particles flying from ``src`` to ``dst`` (both (n, 2)): each leaves after its own delay of up to
    ``stagger`` s and arrives with expo_out ``dur`` s later."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    delay = seeded(seed_key, 'assemble', len(src)).uniform(0, stagger, len(src))
    e = np.array([expo_out((t - d) / dur) for d in delay])[:, None]
    return src + (dst - src) * e


# ------------------------------------------------------------------ text kinetics (the caller draws)
def slam(t, t0, dur=.18):
    """A word slammed onto the screen: scale 1.35 -> 1 (expo_out), alpha in over the first 40%, and a blur that
    starts at 28 px and is nearly gone two frames in."""
    u = clamp01((t - t0) / dur)
    rest = 1 - expo_out(u)
    return {'scale': 1 + .35 * rest, 'alpha': clamp01(u / .4), 'blur_px': 28 * rest}


@lru_cache(maxsize=64)
def _back_s(overshoot):
    """The back_out ``s`` that peaks ``overshoot`` past the end (the peak is 4 s^3 / (27 (s + 1)^2))."""
    lo, hi = 0., 20.
    for _ in range(60):
        s = (lo + hi) / 2
        lo, hi = (s, hi) if 4 * s ** 3 / (27 * (s + 1) ** 2) < overshoot else (lo, s)
    return s


def pop(t, t0, dur=.28, overshoot=.08):
    """A sticker popping on: scale 0 -> 1 peaking ``overshoot`` past 1 (back_out), alpha in over the first 30%,
    and ``lift`` (0..1..0) for the shadow while it is in the air."""
    u = clamp01((t - t0) / dur)
    return {'scale': back_out(u, _back_s(overshoot)), 'alpha': clamp01(u / .3), 'lift': 4 * u * (1 - u)}


def letter_cascade(n, t, t0, gap=.035, dur=.22):
    """Per letter, ``gap`` s apart: it rises 40 px into place while it grows from 0.6 (with a little overshoot) and
    untilts from 8 degrees, alternately left and right."""
    out = []
    for i in range(n):
        u = clamp01((t - t0 - i * gap) / dur)
        settle = 1 - expo_out(u)
        out.append({'scale': 1 - .4 * (1 - back_out(u)), 'alpha': clamp01(u / .35), 'dy': 40 * settle,
                    'rotation': (8 if i % 2 else -8) * settle})
    return out


def typewriter(text, t, t0, cps=28):
    """How many characters of ``text`` show ``t - t0`` s into typing at ``cps`` characters a second."""
    return min(len(text), max(0, math.floor((t - t0) * cps + 1e-6)))


def ring_layout(text, center, radius, t, speed_deg_s, start_deg=0):
    """Characters spaced evenly round a circle (repeat the text to fill it), reading clockwise and turning at
    ``speed_deg_s``: [(char, x, y, angle_deg)], where angle_deg turns each glyph so its top faces outwards
    (0 at the top of the circle)."""
    out = []
    for i, ch in enumerate(text):
        a = start_deg + speed_deg_s * t + 360 * i / len(text) - 90          # 0 degrees = the top of the circle
        r = math.radians(a)
        out.append((ch, center[0] + radius * math.cos(r), center[1] + radius * math.sin(r), (a + 90) % 360))
    return out

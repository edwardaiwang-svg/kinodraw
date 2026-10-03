"""The stick figure: skeleton, pose library, faces, hats and crowds, drawn as black strokes.

Figure units: the feet are at (0, 0), x points the way the figure faces, y points up, and the standing figure is
1.0 tall (head top). ``draw(fig, k, variant)`` returns the figure as an RGBA image plus where its feet, hands and
head landed. ``k`` is the drawing frame (15 per second: motion on twos at 30 fps) and ``variant`` the boil
drawing (0-2): every limb is a slightly bowed stroke whose bow and joints are jittered by a seeded generator, so
the same figure, frame and variant always give the same pixels, and the three variants differ by about a pixel.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field, replace
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from .palette import PALETTE

HIP, TORSO, HEAD_R = .43, .30, .135
UPPER_ARM, FOREARM, THIGH, SHIN = .17, .155, .22, .215
SS = 2                                     # supersampling
DRAW_FPS = 15                              # motion on twos at 30 fps

# Pose library: angles in degrees. Arms (a, b): upper arm from straight down (+ = forward), forearm bend relative
# to the upper arm. Legs (t, s): thigh from straight down, shin relative to the thigh. lean: torso tilt forward.
# tilt: head tilt forward. rot: whole body rotation backwards (falling). frontal: face turned to the viewer.
BASE = {'lean': 0., 'tilt': 0., 'rot': 0., 'lift': 0., 'arm_f': (12., -6.), 'arm_b': (-12., 6.),
        'leg_f': (7., -3.), 'leg_b': (-7., 3.), 'frontal': True, 'seat': False}
POSE_TABLE = {
    'stand': {},
    'point': {'arm_f': (96., -4.), 'arm_b': (-10., 6.), 'frontal': False},
    'talk': {'arm_f': (40., 62.), 'arm_b': (-14., 10.)},
    'think': {'arm_f': (62., 146.), 'arm_b': (30., 84.), 'tilt': -6., 'frontal': False},
    'shrug': {'arm_f': (52., 72.), 'arm_b': (-52., -72.), 'tilt': 8.},
    'wave': {'arm_f': (128., 30.), 'arm_b': (-12., 6.)},
    'sit': {'arm_f': (38., 42.), 'arm_b': (30., 48.), 'leg_f': (86., -84.), 'leg_b': (80., -80.), 'lift': -.165,
            'seat': True, 'lean': -4.},
    'fall': {'rot': 80., 'arm_f': (165., 25.), 'arm_b': (140., -25.), 'leg_f': (30., -12.), 'leg_b': (6., 0.)},
    'cheer': {'arm_f': (124., 26.), 'arm_b': (-124., -26.)},
    'sad': {'lean': 7., 'tilt': 9., 'arm_f': (4., 2.), 'arm_b': (-4., -2.), 'leg_f': (3., 0.), 'leg_b': (-3., 0.)},
    'angry': {'lean': 6., 'arm_f': (118., 48.), 'arm_b': (-24., -36.), 'leg_f': (14., -4.), 'leg_b': (-14., 4.),
              'frontal': False},
    'walk': {'frontal': False},
    'run': {'frontal': False, 'lean': 14.},
    'hold': {'arm_f': (62., 44.), 'arm_b': (48., 56.), 'frontal': False},
}
POSES = tuple(POSE_TABLE) + ('crowd',)
CYCLES = {'walk': 8, 'run': 6, 'wave': 4, 'talk': 4, 'cheer': 4, 'fall': 6, 'angry': 2}
# eyes, brows, mouth
FACES = {
    'stand': ('open', 'flat', 'smile'), 'point': ('open', 'raised', 'grin'), 'talk': ('open', 'flat', 'smile'),
    'think': ('up', 'worried', 'flat'), 'shrug': ('open', 'raised', 'wavy'), 'wave': ('happy', 'flat', 'grin'),
    'sit': ('open', 'flat', 'smile'), 'fall': ('x', 'none', 'wavy'), 'cheer': ('happy', 'raised', 'grin'),
    'sad': ('down', 'worried', 'frown'), 'angry': ('open', 'angry', 'shout'), 'walk': ('open', 'flat', 'smile'),
    'run': ('wide', 'worried', 'o'), 'hold': ('open', 'raised', 'smile'),
}
EYES = ('open', 'up', 'down', 'wide', 'happy', 'x', 'dot', 'half', 'shades')
BROWS = ('none', 'flat', 'raised', 'worried', 'angry')
MOUTHS = ('smile', 'grin', 'flat', 'o', 'frown', 'shout', 'wavy', 'teeth')
HATS = ('helmet', 'crown', 'strawhat', 'cap', 'tophat')


@dataclass(frozen=True)
class Figure:
    pose: str = 'stand'
    height: float = 520.                   # px from the feet to the top of the head (standing)
    facing: int = 1                        # 1: faces right, -1: faces left
    face: tuple | None = None              # (eyes, brows, mouth) instead of the pose's own
    look: tuple = (0., 0.)                 # where the pupils point (-1..1, -1..1; y up)
    hat: str | None = None
    shirt: str | None = None               # palette colour name of a tunic
    extra: tuple = ()                      # 'tear', 'sweat'
    seed: int = 0
    mouth_open: bool | None = None         # talking: alternate open / closed mouth


@dataclass
class Drawn:
    image: Image.Image
    origin: tuple                          # pixel of the feet point (0, 0) in ``image``
    hands: list = field(default_factory=list)   # pixel positions of [front hand, back hand]
    head: tuple = (0., 0., 0.)             # head centre x, y and radius in pixels


def seed_of(*parts) -> int:
    return zlib.crc32('|'.join(map(str, parts)).encode()) & 0x7FFFFFFF


def line_width(height: float) -> float:
    """Stroke width in px for a figure ``height`` px tall: 3 px for a full-height figure (600 px) on a 1080p
    frame, never under 2.2 px, scaling up to 5.5 px in close-ups."""
    return float(min(5.5, max(2.2, height * .005)))


def cycle_len(pose: str) -> int:
    return CYCLES.get(pose, 1)


def pose_at(pose: str, k: int) -> dict:
    """Joint angles of ``pose`` at drawing frame ``k``."""
    p = {**BASE, **POSE_TABLE.get(pose, {})}
    n = cycle_len(pose)
    phi = 2 * math.pi * (k % n) / n
    if pose == 'walk':
        for side, ph in (('leg_f', phi), ('leg_b', phi + math.pi)):
            p[side] = (24 * math.sin(ph), -32 * max(0., math.cos(ph)))
        p['arm_f'] = (-22 * math.sin(phi), 14.)
        p['arm_b'] = (22 * math.sin(phi), 14.)
        p['lift'] = .012 * abs(math.cos(phi))
    elif pose == 'run':
        for side, ph in (('leg_f', phi), ('leg_b', phi + math.pi)):
            p[side] = (42 * math.sin(ph), -20 - 46 * max(0., math.cos(ph)))
        p['arm_f'] = (-48 * math.sin(phi), 86.)
        p['arm_b'] = (48 * math.sin(phi), 86.)
        p['lift'] = .035 * abs(math.sin(phi))
    elif pose == 'wave':
        p['arm_f'] = (128., 30 + 26 * math.sin(phi))
    elif pose == 'talk':
        a, b = p['arm_f']
        p['arm_f'] = (a + 8 * math.sin(phi), b + 16 * math.sin(phi))
    elif pose == 'cheer':
        p['lift'] = .03 * abs(math.sin(phi))
    elif pose == 'fall':                  # tips over in one cycle, then lies still
        u = min(1., k / max(1, n - 1)) if k >= 0 else 1.
        p['rot'] = 80 * u * u
    elif pose == 'angry':
        p['lean'] += 2 * (k % 2)
    return p


def _dir(theta):
    r = math.radians(theta)
    return np.array([math.sin(r), -math.cos(r)])


def skeleton(p: dict) -> dict:
    """Joint positions (figure units) for pose angles ``p``."""
    hip = np.array([0., HIP + p['lift']])
    lean = p['lean']
    up = np.array([math.sin(math.radians(lean)), math.cos(math.radians(lean))])
    neck = hip + TORSO * up
    shoulder = hip + .9 * TORSO * up
    tilt = lean + p['tilt']
    head = neck + HEAD_R * np.array([math.sin(math.radians(tilt)), math.cos(math.radians(tilt))])
    j = {'hip': hip, 'neck': neck, 'shoulder': shoulder, 'head': head}
    for side in ('f', 'b'):
        a, b = p[f'arm_{side}']
        elbow = shoulder + UPPER_ARM * _dir(a + lean)
        j[f'elbow_{side}'], j[f'hand_{side}'] = elbow, elbow + FOREARM * _dir(a + lean + b)
        t, s = p[f'leg_{side}']
        knee = hip + THIGH * _dir(t)
        j[f'knee_{side}'], j[f'foot_{side}'] = knee, knee + SHIN * _dir(t + s)
    if p['rot']:
        r = math.radians(p['rot'])
        rot = np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])
        j = {k: rot @ v for k, v in j.items()}
    if p['seat']:
        pass                                           # sitting: hips rest on the seat, feet on the ground
    low = min(j['foot_f'][1], j['foot_b'][1])
    if p['rot']:
        low = min(low, min(v[1] for v in j.values()), j['head'][1] - HEAD_R)
    lift = p['lift'] if p.get('pose_lift') else 0.
    shift = -low + lift
    if p['seat']:
        shift = -min(j['foot_f'][1], j['foot_b'][1])
    return {k: v + np.array([0., shift]) for k, v in j.items()}


def _bow(a, b, amount, n=12):
    """Points of a slightly bowed stroke from a to b (bow ``amount`` px to the left of a->b)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    length = float(np.hypot(*d)) or 1.
    normal = np.array([-d[1], d[0]]) / length
    ctrl = (a + b) / 2 + normal * amount
    ts = np.linspace(0, 1, n)[:, None]
    return (1 - ts) ** 2 * a + 2 * (1 - ts) * ts * ctrl + ts ** 2 * b


def _stroke(draw, pts, width, color=(0, 0, 0, 255)):
    pts = [tuple(map(float, q)) for q in pts]
    draw.line(pts, fill=color, width=max(1, int(round(width))), joint='curve')
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def _poly(draw, pts, fill, width, outline=(0, 0, 0, 255)):
    pts = [tuple(map(float, q)) for q in pts]
    draw.polygon(pts, fill=fill)
    _stroke(draw, pts + [pts[0]], width, outline)


@lru_cache(maxsize=2048)
def _draw_cached(fig: Figure, k: int, variant: int, crop: tuple | None) -> Drawn:
    H = fig.height
    p = pose_at(fig.pose, k)
    p['pose_lift'] = fig.pose in ('walk', 'run', 'cheer')
    rng = np.random.default_rng([fig.seed, variant, 7])
    j = skeleton(p)
    w = line_width(H)
    sigma = .75 / H                                    # boil: joints move by about a pixel between drawings
    j = {key: v + rng.normal(0, sigma, 2) for key, v in j.items()}
    xs = [v[0] for v in j.values()]
    ys = [v[1] for v in j.values()]
    x0, x1 = min(xs) - .55, max(xs) + .55
    y0, y1 = min(ys) - .1, max(ys) + .5
    if crop:
        y0, y1 = max(y0, crop[0]), min(y1, crop[1])
    S = H * SS
    wpx, hpx = int(math.ceil((x1 - x0) * S)) + 4, int(math.ceil((y1 - y0) * S)) + 4
    img = Image.new('RGBA', (wpx, hpx), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = fig.facing

    def P(v):                                          # figure units -> supersampled pixels
        x = v[0] * f if f == 1 else -v[0]
        X = (x - (x0 if f == 1 else -x1)) * S + 2
        return np.array([X, (y1 - v[1]) * S + 2])
    lw = w * SS
    bows = rng.normal(0, .9, 8) * SS * H / 520

    def limb(a, b, c, bow1, bow2):
        _stroke(d, np.vstack([_bow(P(a), P(b), bow1), _bow(P(b), P(c), bow2)[1:]]), lw)
    ink = (0, 0, 0, 255)
    if p['seat']:
        hy = j['hip'][1] - .02
        seat = [P(np.array([-.17, hy])), P(np.array([.17, hy])), P(np.array([.17, 0.])), P(np.array([-.17, 0.]))]
        _poly(d, seat, PALETTE['brown'] + (255,), lw)
    limb(j['shoulder'], j['elbow_b'], j['hand_b'], bows[0], bows[1])
    limb(j['hip'], j['knee_b'], j['foot_b'], bows[2], bows[3])
    limb(j['hip'], j['knee_f'], j['foot_f'], bows[4], bows[5])
    if fig.shirt:
        up = (j['neck'] - j['hip']) / (np.hypot(*(j['neck'] - j['hip'])) or 1)
        side = np.array([up[1], -up[0]])
        top, bottom = j['neck'] - .004 * up, j['hip'] - .015 * up
        tunic = [top + .05 * side, bottom + .08 * side, bottom - .08 * side, top - .05 * side]
        _poly(d, [P(q) for q in tunic], PALETTE[fig.shirt] + (255,), lw)
    else:
        _stroke(d, _bow(P(j['hip']), P(j['neck']), bows[6] * .5), lw)
    limb(j['shoulder'], j['elbow_f'], j['hand_f'], -bows[1], bows[7])
    # head
    hc = P(j['head'])
    R = HEAD_R * S * (1 + rng.normal(0, .004))
    d.ellipse((hc[0] - R, hc[1] - R, hc[0] + R, hc[1] + R), fill=(255, 255, 255, 255), outline=ink, width=int(round(lw)))
    tilt = p['lean'] + p['tilt'] - p['rot']          # rot turns the body backwards (counter-clockwise)
    _face(d, fig, p, hc, R, lw, f, tilt, rng)
    if fig.hat:
        _hat(d, fig.hat, hc, R, lw, f, tilt)
    out = img.resize((max(1, wpx // SS), max(1, hpx // SS)), Image.LANCZOS)
    o = P(np.array([0., 0.])) / SS
    hands = [tuple(P(j['hand_f']) / SS), tuple(P(j['hand_b']) / SS)]
    return Drawn(out, (float(o[0]), float(o[1])), hands, (float(hc[0] / SS), float(hc[1] / SS), float(R / SS)))


def draw(fig: Figure, k: int = 0, variant: int = 0, crop: tuple | None = None) -> Drawn:
    """The figure at drawing frame ``k`` in boil drawing ``variant``; ``crop`` = (low, high) figure-unit rows."""
    if fig.pose not in POSE_TABLE:
        raise ValueError(f'unknown pose {fig.pose!r}')
    n = cycle_len(fig.pose)
    k = min(k, n - 1) if fig.pose == 'fall' else k % n
    return _draw_cached(fig, int(k), int(variant) % 3, crop)


def _rot(v, deg):
    r = math.radians(deg)
    return np.array([v[0] * math.cos(r) - v[1] * math.sin(r), v[0] * math.sin(r) + v[1] * math.cos(r)])


def _face(d, fig, p, hc, R, lw, f, tilt, rng):
    eyes, brows, mouth = fig.face or FACES.get(fig.pose, FACES['stand'])
    if fig.mouth_open is not None and mouth in ('smile', 'flat', 'grin', 'o', 'frown'):
        mouth = 'grin' if fig.mouth_open else ('flat' if mouth in ('o', 'grin') else mouth)
    frontal = p['frontal'] or fig.pose in ('fall',)
    ink, white = (0, 0, 0, 255), (255, 255, 255, 255)
    fw = lw * .85
    shift = 0. if frontal else .26
    jit = rng.normal(0, .012, 6)

    def H(x, y):                                       # head units (x toward the facing side, y up) -> pixels
        v = _rot(np.array([x, y]), -tilt)
        return hc + np.array([v[0] * R * f, -v[1] * R])
    spots = [(shift - .33 + jit[0], .1 + jit[1]), (shift + .33 + jit[2], .1 + jit[3])]
    if not frontal:
        spots = [(shift - .24 + jit[0], .1 + jit[1]), (shift + .38 + jit[2], .1 + jit[3])]
    lx, ly = fig.look
    if eyes == 'up':
        lx, ly = lx * .5 + .2, 1.
    elif eyes == 'down':
        lx, ly = lx * .5, -1.
    for ex, ey in spots:
        c = H(ex, ey)
        if eyes in ('open', 'up', 'down', 'wide', 'half'):
            rx, ry = (.2, .25) if eyes == 'wide' else (.15, .19)
            d.ellipse((c[0] - rx * R, c[1] - ry * R, c[0] + rx * R, c[1] + ry * R), fill=white, outline=ink,
                      width=max(1, int(round(fw * .8))))
            pr = (.06 if eyes == 'wide' else .085) * R
            px, py = c[0] + lx * .07 * R * f, c[1] - ly * .08 * R
            d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=ink)
            if eyes == 'half':
                d.chord((c[0] - rx * R - 1, c[1] - ry * R - 1, c[0] + rx * R + 1, c[1] + ry * R + 1), 180, 360,
                        fill=white, outline=ink, width=max(1, int(round(fw * .8))))
        elif eyes == 'dot':
            r = .075 * R
            d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=ink)
        elif eyes == 'happy':
            pts = [H(ex + .14 * math.cos(a), ey - .02 + .12 * math.sin(a)) for a in np.linspace(0.2, math.pi - .2, 8)]
            _stroke(d, pts, fw)
        elif eyes == 'x':
            r = .12
            _stroke(d, [H(ex - r, ey - r), H(ex + r, ey + r)], fw)
            _stroke(d, [H(ex - r, ey + r), H(ex + r, ey - r)], fw)
        elif eyes == 'shades':
            pts = [H(ex - .2, ey + .1), H(ex + .2, ey + .1), H(ex + .16, ey - .12), H(ex - .16, ey - .12)]
            _poly(d, pts, ink, fw)
    if eyes == 'shades':
        _stroke(d, [H(spots[0][0] + .2, spots[0][1] + .08), H(spots[1][0] - .2, spots[1][1] + .08)], fw)
    by = .42
    for i, (ex, ey) in enumerate(spots):
        inner = 1 if i == 0 else -1                    # +: toward the other eye
        if brows == 'none':
            continue
        if brows == 'flat':
            a, b = (ex - .15, by), (ex + .15, by)
        elif brows == 'raised':
            a, b = (ex - .15, by + .08), (ex + .15, by + .1)
        elif brows == 'worried':
            a, b = (ex - .15 * inner, by), (ex + .14 * inner, by + .11)
        else:                                          # angry
            a, b = (ex - .15 * inner, by + .1), (ex + .14 * inner, by - .04)
        _stroke(d, [H(*a), H(*b)], fw)
    mx, my = (shift * .9, -.46)
    m = lambda x, y: H(mx + x, my + y)                 # noqa: E731
    if mouth == 'smile':
        _stroke(d, [m(.22 * math.cos(a), .1 * math.sin(a) + .06) for a in np.linspace(math.pi + .35, 2 * math.pi - .35, 10)], fw)
    elif mouth == 'frown':
        _stroke(d, [m(.2 * math.cos(a), .1 * math.sin(a) - .08) for a in np.linspace(.35, math.pi - .35, 10)], fw)
    elif mouth == 'flat':
        _stroke(d, [m(-.15, 0), m(.15, .01)], fw)
    elif mouth == 'wavy':
        _stroke(d, [m(-.2 + .4 * i / 8, .035 * (-1) ** i) for i in range(9)], fw)
    elif mouth in ('grin', 'shout', 'o', 'teeth'):
        if mouth == 'grin':
            pts = [m(.24 * math.cos(a), .2 * math.sin(a) + .05) for a in np.linspace(math.pi, 2 * math.pi, 14)]
        elif mouth == 'shout':
            pts = [m(.2 * math.cos(a), .2 * math.sin(a) - .02) for a in np.linspace(0, 2 * math.pi, 18)[:-1]]
        elif mouth == 'o':
            pts = [m(.1 * math.cos(a), .13 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 14)[:-1]]
        else:
            pts = [m(-.2, .07), m(.2, .07), m(.2, -.09), m(-.2, -.09)]
        fill = (255, 255, 255, 255) if mouth == 'teeth' else PALETTE['maroon'] + (255,)
        _poly(d, pts, fill, fw)
        if mouth in ('grin', 'shout'):                 # tongue
            t = [m(-.1, -.12 if mouth == 'grin' else -.16), m(.1, -.12 if mouth == 'grin' else -.16),
                 m(.06, -.08 if mouth == 'grin' else -.1), m(-.06, -.08 if mouth == 'grin' else -.1)]
            d.polygon([tuple(q) for q in t], fill=PALETTE['pink'] + (255,))
        if mouth == 'teeth':
            for x in (-.1, 0, .1):
                _stroke(d, [m(x, .07), m(x, -.09)], fw * .6)
    if 'tear' in fig.extra:
        ex, ey = spots[0]
        c = H(ex - .02, ey - .3)
        r = .07 * R
        d.polygon([(c[0], c[1] - 2.2 * r), (c[0] - r, c[1]), (c[0] + r, c[1])], fill=PALETTE['sky'] + (255,))
        d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=PALETTE['sky'] + (255,))
    if 'sweat' in fig.extra:
        c = H(-.95 if frontal else -.85, .45)
        r = .08 * R
        d.polygon([(c[0], c[1] - 2.4 * r), (c[0] - r, c[1]), (c[0] + r, c[1])], fill=PALETTE['sky'] + (255,),
                  outline=ink)
        d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=PALETTE['sky'] + (255,))


def _hat(d, hat, hc, R, lw, f, tilt):
    def H(x, y):
        v = _rot(np.array([x, y]), -tilt)
        return tuple(hc + np.array([v[0] * R * f, -v[1] * R]))
    if hat == 'helmet':
        dome = [H(1.07 * math.cos(a), 1.07 * math.sin(a)) for a in np.linspace(.32, math.pi - .32, 22)]
        _poly(d, dome, PALETTE['silver'] + (255,), lw)
        crest = [H(.8 * math.cos(a) - .08, .98 + .62 * math.sin(a)) for a in np.linspace(0, math.pi, 16)]
        _poly(d, crest, PALETTE['maroon'] + (255,), lw)
        for a in np.linspace(.5, math.pi - .5, 5):           # brush bristles
            _stroke(d, [H(.42 * math.cos(a) - .08, 1.02 + .3 * math.sin(a)), H(.7 * math.cos(a) - .08, 1.0 + .52 * math.sin(a))], lw * .6)
    elif hat == 'crown':
        pts = [H(-.75, .62), H(-.82, 1.32), H(-.42, 1.02), H(0, 1.42), H(.42, 1.02), H(.82, 1.32), H(.75, .62)]
        _poly(d, pts, PALETTE['yellow'] + (255,), lw)
    elif hat == 'strawhat':
        brim = [H(1.55 * math.cos(a), .62 + .26 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 28)[:-1]]
        _poly(d, brim, PALETTE['tan'] + (255,), lw)
        top = [H(.7 * math.cos(a), .66 + .62 * math.sin(a)) for a in np.linspace(0, math.pi, 16)]
        _poly(d, top, PALETTE['yellow'] + (255,), lw)
    elif hat == 'cap':
        dome = [H(1.02 * math.cos(a), .2 + .92 * math.sin(a)) for a in np.linspace(-.05, math.pi + .05, 20)]
        _poly(d, dome, PALETTE['blue'] + (255,), lw)
        _poly(d, [H(.9, .3), H(1.65, .26), H(1.6, .14), H(.9, .16)], PALETTE['blue'] + (255,), lw)
    elif hat == 'tophat':
        _poly(d, [H(-1.25, .72), H(1.25, .72), H(1.25, .58), H(-1.25, .58)], (0, 0, 0, 255), lw)
        _poly(d, [H(-.72, .72), H(.72, .72), H(.66, 1.9), H(-.66, 1.9)], (0, 0, 0, 255), lw)
        _poly(d, [H(-.7, .8), H(.7, .8), H(.69, .98), H(-.69, .98)], PALETTE['maroon'] + (255,), lw * .5)


# -------------------------------------------------------------------- crowds
CROWD_POSES = {'calm': ('stand', 'talk', 'stand', 'point', 'stand'), 'happy': ('cheer', 'wave', 'cheer', 'stand'),
               'upset': ('angry', 'stand', 'angry', 'shrug'), 'sad': ('sad', 'stand', 'sad'),
               'scared': ('run', 'shrug', 'stand')}


@dataclass(frozen=True)
class Crowd:
    n: int = 5
    height: float = 380.
    mood: str = 'calm'
    facing: int = 1
    hat: str | None = None
    seed: int = 0


def crowd_members(c: Crowd) -> list:
    """[(Figure, x offset in px)] for a crowd of ``c.n`` (3-7) people, left to right, deterministic."""
    n = max(3, min(7, c.n))
    rng = np.random.default_rng([c.seed, n, 11])
    poses = CROWD_POSES.get(c.mood, CROWD_POSES['calm'])
    gap = c.height * .5
    out = []
    shirts = list(rng.permutation(len(SHIRT_ORDER)))
    for i in range(n):
        h = c.height * float(rng.uniform(.88, 1.04))
        pose = poses[int(rng.integers(len(poses)))]
        facing = c.facing if rng.random() < .75 else -c.facing
        fig = Figure(pose=pose, height=h, facing=facing, shirt=SHIRT_ORDER[shirts[i % len(shirts)]],
                     hat=c.hat if c.hat and rng.random() < .7 else None, seed=seed_of(c.seed, i))
        out.append((fig, (i - (n - 1) / 2) * gap + float(rng.normal(0, gap * .06))))
    return out


SHIRT_ORDER = ['blue', 'orange', 'green', 'purple', 'yellow', 'sky', 'brown', 'pink', 'grey', 'lime']


def draw_crowd(c: Crowd, k: int = 0, variant: int = 0) -> Drawn:
    """All members on one image; origin = the crowd's centre on the ground."""
    parts = [(draw(fig, k + i, variant), dx) for i, (fig, dx) in enumerate(crowd_members(c))]
    lefts = [dx - dr.origin[0] for dr, dx in parts]
    tops = [-dr.origin[1] for dr, _ in parts]
    rights = [dx - dr.origin[0] + dr.image.width for dr, dx in parts]
    bottoms = [-dr.origin[1] + dr.image.height for dr, _ in parts]
    x0, y0 = math.floor(min(lefts)), math.floor(min(tops))
    img = Image.new('RGBA', (int(math.ceil(max(rights) - x0)) + 1, int(math.ceil(max(bottoms) - y0)) + 1), (0, 0, 0, 0))
    order = sorted(range(len(parts)), key=lambda i: -parts[i][0].image.height)   # taller ones behind
    for i in order:
        dr, dx = parts[i]
        img.alpha_composite(dr.image, (int(round(dx - dr.origin[0] - x0)), int(round(-dr.origin[1] - y0))))
    return Drawn(img, (-x0, -y0), [], (0., 0., 0.))


def with_pose(fig: Figure, pose: str) -> Figure:
    return replace(fig, pose=pose)

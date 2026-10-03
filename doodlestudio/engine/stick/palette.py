"""The look's 16 flat colours, nearest-colour snapping (CIE Lab), part accents and ground colours."""
from __future__ import annotations

from functools import lru_cache

PALETTE = {
    'black': (0, 0, 0), 'white': (255, 255, 255), 'grey': (127, 127, 127), 'silver': (195, 195, 195),
    'red': (232, 38, 45), 'maroon': (139, 26, 26), 'orange': (255, 138, 31), 'yellow': (255, 225, 26),
    'tan': (239, 221, 176), 'brown': (168, 107, 69), 'green': (46, 168, 79), 'lime': (184, 224, 74),
    'sky': (154, 215, 238), 'blue': (47, 111, 219), 'purple': (142, 75, 176), 'pink': (247, 168, 196),
}
RED = PALETTE['red']
INK = PALETTE['black']
# Part accents (header square, shirts, number underlines). Red is kept for emphasis only.
ACCENTS = ['blue', 'orange', 'green', 'purple', 'maroon', 'sky', 'brown', 'pink']
# Ground strip colours by topic (cues.ground picks one per video).
GROUNDS = {'history': 'tan', 'nature': 'lime', 'sky': 'sky', 'plain': 'silver'}
# Shirts for crowds: never red (emphasis), never white (heads), never black (lines).
SHIRTS = ['blue', 'orange', 'green', 'purple', 'yellow', 'sky', 'brown', 'pink', 'grey', 'lime']


def rgb(name: str) -> tuple:
    return PALETTE[name]


def hexcode(name: str) -> str:
    return '#%02X%02X%02X' % PALETTE[name]


def accent(number: int) -> str:
    """Accent colour name of part ``number`` (1-based); 0 or None = no part (grey)."""
    return ACCENTS[(number - 1) % len(ACCENTS)] if number else 'grey'


def _lab(c):
    def lin(v):
        v /= 255.
        return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
    r, g, b = (lin(float(v)) for v in c[:3])
    x = (r * .4124 + g * .3576 + b * .1805) / .95047
    y = r * .2126 + g * .7152 + b * .0722
    z = (r * .0193 + g * .1192 + b * .9505) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > .008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


_LAB = {name: _lab(c) for name, c in PALETTE.items()}


@lru_cache(maxsize=4096)
def nearest(color: tuple) -> str:
    """Name of the palette colour closest to ``color`` (RGB) in CIE Lab."""
    L, a, b = _lab(color)
    return min(_LAB, key=lambda n: (_LAB[n][0] - L) ** 2 + (_LAB[n][1] - a) ** 2 + (_LAB[n][2] - b) ** 2)


def parse_hex(text: str) -> tuple | None:
    t = text.strip().lstrip('#')
    if len(t) == 3:
        t = ''.join(ch * 2 for ch in t)
    if len(t) != 6:
        return None
    try:
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None

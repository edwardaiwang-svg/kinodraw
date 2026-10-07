"""Flat colour helpers: coats are one base colour plus derived shade and light tones."""
from __future__ import annotations


def rgb(h: str):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(c) -> str:
    return '#' + ''.join(f'{max(0, min(255, round(v))):02X}' for v in c)


def mix(a: str, b: str, t: float) -> str:
    ca, cb = rgb(a), rgb(b)
    return hexc([x + (y - x) * t for x, y in zip(ca, cb)])


def shade(c: str, t: float = 0.2) -> str:
    """Darker tone for far limbs and shadow patches (slightly warm, like the Fluent far legs)."""
    return mix(c, '#3A2418', t)


def light(c: str, t: float = 0.45) -> str:
    return mix(c, '#FFF6E6', t)


INK = '#1B1B1B'
WHITE = '#FFFFFF'
MOUTH = '#8E2A2A'
TONGUE = '#E86A6A'
PINK = '#F2A0A0'
NOSE = '#3A2A26'

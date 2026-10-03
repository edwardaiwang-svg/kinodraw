"""The paper puppet: a cut-out character drawn by code, so every video can have a recurring actor without artwork.

The puppet is an SVG built from pieces that turn at their joints (shoulders, elbows, hips), like a paper doll held
together with split pins. Poses are joint angles; expressions are a handful of face features. Colours come from a
preset or the storyboard's `puppet` settings. Rasters are cached, so a pose costs one resvg call per size.
"""
from __future__ import annotations

import io
import math
from functools import lru_cache

import resvg_py
from PIL import Image

INK = '#1B1B1B'
W, H = 400, 600                     # the SVG's own units; the ground line is at y = 588

PRESETS = {
    'sunny': dict(skin='#F6D3B8', cheek='#F29C9C', hair='#7A4A2A', top='#F2B33D', pants='#2F8F9D', shoes='#2F4858',
                  hat='#E4574B', pompom='#F07A6E', style='beanie', glasses=False),
    'reader': dict(skin='#F4CBA6', cheek='#F2A0A0', hair='#9C4A2F', top='#E9A23B', pants='#3A8C8C', shoes='#F4F1EA',
                   hat=None, pompom=None, style='bun', glasses=True),
    'breeze': dict(skin='#C98D63', cheek='#E08A7A', hair='#2B1F1A', top='#5B8DEF', pants='#34405A', shoes='#F2C14E',
                   hat=None, pompom=None, style='bob', glasses=False),
}

# Joint angles in degrees, clockwise on screen, 0 = hanging straight down.
# arms: (left shoulder, left elbow, right shoulder, right elbow); legs: (left hip, right hip); lift: body y offset
POSES = {
    'stand':      dict(arms=(12, 6, -12, -6), legs=(0, 0), tilt=0, lift=0),
    'look_up':    dict(arms=(10, 4, -10, -4), legs=(0, 0), tilt=-8, lift=0),
    'wave':       dict(arms=(12, 6, -150, -25), legs=(0, 0), tilt=3, lift=0),
    'point':      dict(arms=(12, 6, -92, 0), legs=(0, 0), tilt=2, lift=0),
    'hold_phone': dict(arms=(12, 6, -35, -105), legs=(0, 0), tilt=0, lift=0),
    'think':      dict(arms=(12, 6, -45, -140), legs=(0, 0), tilt=6, lift=0),
    'worried':    dict(arms=(168, -38, -168, 38), legs=(4, -4), tilt=0, lift=0),
    'cheer':      dict(arms=(140, -12, -140, 12), legs=(16, -16), tilt=0, lift=-38),
    'walk':       dict(arms=(18, 8, -18, -8), legs=(0, 0), tilt=0, lift=0),
}
EXPRESSIONS = ('smile', 'happy', 'surprised', 'worried', 'neutral', 'wonder')
WALK = [(-20, 20, -3), (-8, 8, 0), (20, -20, -3), (8, -8, 0)]     # (left hip, right hip, lift) per pose on twos


def _limb(x, y, angle, length, width, color):
    """A rounded limb piece hanging from (x, y), turned by ``angle``; returns (svg, end point)."""
    a = math.radians(angle)
    ex, ey = x - math.sin(a) * length, y + math.cos(a) * length
    shape = (f'<rect x="{x - width / 2:.1f}" y="{y:.1f}" width="{width}" height="{length:.1f}" rx="{width / 2}" '
             f'fill="{color}" stroke="{INK}" stroke-width="5" transform="rotate({angle} {x} {y})"/>')
    return shape, (ex, ey)


def _arm(x, y, shoulder, elbow, c, phone=False):
    upper, (ex, ey) = _limb(x, y, shoulder, 72, 32, c['top'])
    lower, (hx, hy) = _limb(ex, ey, shoulder + elbow, 64, 28, c['top'])
    hand = f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="17" fill="{c["skin"]}" stroke="{INK}" stroke-width="5"/>'
    extra = ''
    if phone:
        extra = (f'<g transform="rotate({shoulder + elbow + 180} {hx:.1f} {hy:.1f})">'
                 f'<rect x="{hx - 17:.1f}" y="{hy - 58:.1f}" width="34" height="58" rx="7" fill="#2E3440" '
                 f'stroke="{INK}" stroke-width="4"/><rect x="{hx - 12:.1f}" y="{hy - 52:.1f}" width="24" height="42" '
                 f'rx="3" fill="#9FD8E8"/></g>')
    return upper + lower + extra + hand


def _face(expression, c, glasses):
    ey = 196
    brows, mouth = '', ''
    if expression == 'happy':
        eyes = (f'<path d="M150 {ey} q14 -16 28 0" fill="none" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>'
                f'<path d="M222 {ey} q14 -16 28 0" fill="none" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>')
    elif expression == 'wonder':
        eyes = f'<circle cx="164" cy="{ey - 6}" r="9" fill="{INK}"/><circle cx="236" cy="{ey - 6}" r="9" fill="{INK}"/>'
    else:
        eyes = f'<circle cx="164" cy="{ey}" r="9" fill="{INK}"/><circle cx="236" cy="{ey}" r="9" fill="{INK}"/>'
    if expression == 'surprised':
        brows = (f'<path d="M148 {ey - 34} q16 -10 32 0" fill="none" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>'
                 f'<path d="M220 {ey - 34} q16 -10 32 0" fill="none" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
        mouth = f'<ellipse cx="200" cy="{ey + 50}" rx="13" ry="16" fill="#8C3B3B" stroke="{INK}" stroke-width="5"/>'
    elif expression == 'worried':
        brows = (f'<path d="M150 {ey - 26} l28 -10" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>'
                 f'<path d="M250 {ey - 26} l-28 -10" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
        mouth = (f'<path d="M178 {ey + 52} q7 -8 14 0 q7 8 14 0 q7 -8 14 0" fill="none" stroke="{INK}" '
                 f'stroke-width="5" stroke-linecap="round"/>')
    elif expression == 'neutral':
        mouth = f'<path d="M186 {ey + 50} h28" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>'
    elif expression == 'wonder':
        mouth = f'<ellipse cx="200" cy="{ey + 48}" rx="9" ry="11" fill="#8C3B3B" stroke="{INK}" stroke-width="4"/>'
    else:                                              # smile, happy
        mouth = (f'<path d="M176 {ey + 40} q24 26 48 0" fill="#8C3B3B" stroke="{INK}" stroke-width="5" '
                 f'stroke-linejoin="round"/>')
    cheeks = (f'<ellipse cx="140" cy="{ey + 28}" rx="20" ry="13" fill="{c["cheek"]}" opacity="0.65"/>'
              f'<ellipse cx="260" cy="{ey + 28}" rx="20" ry="13" fill="{c["cheek"]}" opacity="0.65"/>')
    specs = ''
    if glasses:
        specs = (f'<circle cx="164" cy="{ey}" r="25" fill="none" stroke="{INK}" stroke-width="5"/>'
                 f'<circle cx="236" cy="{ey}" r="25" fill="none" stroke="{INK}" stroke-width="5"/>'
                 f'<path d="M189 {ey} h22" stroke="{INK}" stroke-width="5"/>')
    return cheeks + eyes + specs + brows + mouth


def _head(expression, c):
    back, front = '', ''
    if c['style'] == 'bun':
        back = (f'<circle cx="200" cy="72" r="44" fill="{c["hair"]}" stroke="{INK}" stroke-width="5"/>'
                f'<path d="M92 190 Q92 70 200 70 Q308 70 308 190 Q300 130 200 118 Q100 130 92 190 Z" '
                f'fill="{c["hair"]}" stroke="{INK}" stroke-width="5"/>')
    elif c['style'] == 'bob':
        back = (f'<path d="M84 250 Q70 80 200 72 Q330 80 316 250 Q300 270 290 250 L290 160 L110 160 L110 250 '
                f'Q100 270 84 250 Z" fill="{c["hair"]}" stroke="{INK}" stroke-width="5"/>')
    face = f'<circle cx="200" cy="190" r="112" fill="{c["skin"]}" stroke="{INK}" stroke-width="5"/>'
    if c['style'] == 'beanie':
        front = (f'<path d="M88 158 Q90 56 200 54 Q310 56 312 158 Z" fill="{c["hat"]}" stroke="{INK}" stroke-width="5"/>'
                 f'<rect x="82" y="136" width="236" height="36" rx="17" fill="{c["hat"]}" stroke="{INK}" '
                 f'stroke-width="5"/>'
                 + ''.join(f'<path d="M{x} 142 v24" stroke="{INK}" stroke-width="3" opacity="0.35"/>'
                           for x in range(100, 310, 16))
                 + f'<circle cx="200" cy="48" r="26" fill="{c["pompom"]}" stroke="{INK}" stroke-width="5"/>')
    elif c['style'] == 'bob':
        front = f'<path d="M104 150 Q150 92 200 96 Q250 92 296 150 Q250 128 200 132 Q150 128 104 150 Z" ' \
                f'fill="{c["hair"]}" stroke="{INK}" stroke-width="4"/>'
    return back + face + front + _face(expression, c, c['glasses'])


def svg(pose='stand', expression='smile', frame=0, preset='sunny', colors: dict | None = None, phone=False) -> str:
    """The puppet as an SVG document; ``frame`` counts poses on twos (walk cycle, waving hand)."""
    c = {**PRESETS[preset], **(colors or {})}
    p = POSES[pose]
    la, le, ra, re_ = p['arms']
    lh, rh, lift = p['legs'][0], p['legs'][1], p['lift']
    if pose == 'walk':
        lh, rh, lift = WALK[frame % len(WALK)]
        la, ra = -lh * 0.8 + 12, -rh * 0.8 - 12
    if pose == 'wave':
        re_ = -25 + (18 if frame % 2 else -12)
    legs = ''
    for hx, angle in ((180, lh), (220, rh)):
        piece, (fx, fy) = _limb(hx, 440 + lift, angle, 118, 36, c['pants'])
        shoe = f'<ellipse cx="{fx + (-10 if hx < 200 else 10):.1f}" cy="{fy + 6:.1f}" rx="30" ry="16" ' \
               f'fill="{c["shoes"]}" stroke="{INK}" stroke-width="5"/>'
        legs += piece + shoe
    torso = (f'<path d="M142 {292 + lift} Q200 {276 + lift} 258 {292 + lift} L272 {452 + lift} Q200 {470 + lift} '
             f'128 {452 + lift} Z" fill="{c["top"]}" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
             + ''.join(f'<circle cx="200" cy="{y + lift}" r="5" fill="{INK}" opacity="0.55"/>' for y in (330, 370, 410)))
    arms = _arm(146, 310 + lift, la, le, c) + _arm(254, 310 + lift, ra, re_, c, phone=phone or pose == 'hold_phone')
    head = f'<g transform="rotate({p["tilt"]} 200 {300 + lift}) translate(0 {lift})">{_head(expression, c)}</g>'
    body = legs + torso + head + arms if pose in ('cheer', 'worried', 'wave', 'think') else legs + arms + torso + head
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-40 -60 {W + 80} {H + 80}" width="{W + 80}" '
            f'height="{H + 80}">{body}</svg>')


@lru_cache(maxsize=512)
def raster(pose='stand', expression='smile', frame=0, preset='sunny', colors: tuple = (), height=460,
           phone=False) -> Image.Image:
    """The puppet as an RGBA image ``height`` pixels tall (colours as a tuple of (name, value) pairs)."""
    doc = svg(pose, expression, frame, preset, dict(colors), phone)
    width = round(height * (W + 80) / (H + 80))
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=doc, width=width, height=height))).convert('RGBA')

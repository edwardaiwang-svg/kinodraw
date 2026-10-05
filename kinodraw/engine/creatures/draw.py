"""Readable vector faces and coats, with ink and shaded flat-colour surfaces."""
from __future__ import annotations

import io
import math
from html import escape

import resvg_py
from PIL import Image

from .actions import Action, Pose, squash_scale
from .genes import Genome
from .life import pose_at
from .rig import Ellipse, Rig, build

W, H, GROUND = 600, 400, 336
INK = '#292321'


def _shade(color, amount):
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(c * (1 - amount)):02X}' for c in rgb)


class _Brush:
    def __init__(self, genome, style, t):
        self.line = style == 'line_art'
        self.rng = genome.stream(f'pattern:ink:{int(t * 7.5)}')
        self.body = 'white' if self.line else 'url(#body_shade)'
        self.far = 'white' if self.line else _shade(genome.palette.body, .26)
        self.accent = 'white' if self.line else genome.palette.accent
        self.pattern = INK if self.line else '#382920'

    def path(self, d, fill='none', stroke=INK, width=2., opacity=1., part=''):
        jitter = f' transform="translate({self.rng.uniform(-.3, .3):.2f} {self.rng.uniform(-.3, .3):.2f})"' if self.line else ''
        return (f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width:.2f}" '
                f'opacity="{opacity:.3f}" stroke-linecap="round" stroke-linejoin="round" data-part="{part}"{jitter}/>')

    def ellipse(self, e, fill=None, stroke=INK, width=2., part='', opacity=1.):
        jitter = self.rng.uniform(-.3, .3) if self.line else 0.
        return (f'<ellipse cx="{e.x + jitter:.3f}" cy="{e.y:.3f}" rx="{e.rx:.3f}" ry="{e.ry:.3f}" '
                f'fill="{fill if fill is not None else self.body}" stroke="{stroke}" stroke-width="{width}" '
                f'data-part="{part}" opacity="{opacity:.3f}"/>')

    def polygon(self, points, fill, width=2., part=''):
        d = 'M' + ' L'.join(f'{x:.2f} {y:.2f}' for x, y in points) + ' Z'
        return self.path(d, fill, width=width, part=part)


def _limb(b, limb, part, far=False, human=False):
    a, j, end = limb.root, limb.joint, limb.end
    d = f'M{a[0]:.2f} {a[1]:.2f} Q{j[0]:.2f} {j[1]:.2f} {j[0]:.2f} {j[1]:.2f} L{end[0]:.2f} {end[1]:.2f}'
    color = b.far if far else b.body
    shape = b.path(d, stroke=INK, width=limb.width + 3., part=part)
    shape += b.path(d, stroke=color, width=limb.width)
    shape += b.ellipse(Ellipse(end[0] + 3, end[1], limb.width * .75, limb.width * .39), color, part=part + '_paw')
    if not human:
        for x in (-3, 3, 8):
            shape += b.path(f'M{end[0] + x:.2f} {end[1] - 1:.2f} l0 4', width=1.)
    return shape


def _coat(b, rig):
    g, body = rig.genome, rig.body
    shapes = []
    if 'stripes' in g.marks:
        for i in range(9):
            x = body.x + body.rx * (-.87 + i * .20)
            top = body.y - body.ry * math.sqrt(max(0., 1 - ((x - body.x) / body.rx) ** 2)) - 4
            bottom = body.y + body.ry * (.22 if i % 2 else .53)
            shapes.append(b.path(f'M{x - 4:.2f} {top:.2f} Q{x + 3:.2f} {body.y - 6:.2f} {x + 13:.2f} {bottom:.2f} '
                                 f'Q{x + 13:.2f} {body.y - 15:.2f} {x + 6:.2f} {top:.2f} Z', b.pattern, width=0.))
        for i in range(5):
            x = body.x + body.rx * (-.65 + i * .31)
            bottom = body.y + body.ry + 4
            shapes.append(b.path(f'M{x:.2f} {bottom:.2f} l8 -26 l3 26 Z', b.pattern, width=0.))
        x, y = rig.chest.x, rig.chest.y
        shapes.append(b.path(f'M{x + 7} {y - 50} q-14 25 15 52 q-4 -29 -5 -52 Z', b.pattern, width=0.))
    if 'spots' in g.marks:
        rng = g.stream('pattern:spots')
        for _ in range(32):
            x, y = rng.uniform(body.x - body.rx, body.x + body.rx), rng.uniform(body.y - body.ry, body.y + body.ry)
            radius = rng.uniform(2.7, 4.8)
            shapes.append(b.ellipse(Ellipse(x, y, radius, radius * .75), b.pattern, stroke='none', width=0.))
    return '<g clip-path="url(#coat)">' + ''.join(shapes) + '</g>'


def _mane(b, rig):
    if not rig.mane:
        return ''
    head, radius = rig.head, rig.mane_radius
    black = 'mane_black' in rig.genome.marks
    color = 'white' if b.line else '#242125' if black else '#9A612B'
    points = []
    for i, chain in enumerate(rig.mane):
        angle = 2 * math.pi * (i - .5) / len(rig.mane)
        points.append((head.x + radius * .89 * math.cos(angle), head.y + radius * .89 * math.sin(angle)))
        points.append(chain[-1])
    # Rounded fur lobes with short pointed tips, rather than a regular star collar.
    d = f'M{points[0][0]:.2f} {points[0][1]:.2f}'
    for i in range(1, len(points) + 1):
        a, end = points[i - 1], points[i % len(points)]
        if i % 2:
            control = (a[0] * .25 + end[0] * .75, a[1] * .25 + end[1] * .75)
        else:
            control = (end[0] + (a[0] - end[0]) * .35, end[1] + (a[1] - end[1]) * .70)
        d += f' Q{control[0]:.2f} {control[1]:.2f} {end[0]:.2f} {end[1]:.2f}'
    shape = b.path(d + ' Z', color, part='mane')
    for i, chain in enumerate(rig.mane):
        a, j, tip = chain
        color = INK if b.line else '#484047' if black else '#B88042'
        shape += b.path(f'M{a[0]:.2f} {a[1]:.2f} Q{j[0]:.2f} {j[1]:.2f} {tip[0]:.2f} {tip[1]:.2f}',
                        stroke=color, width=1.3)
        if black and b.line:
            angle = 2 * math.pi * (i + .18) / len(rig.mane)
            shape += b.path(f'M{head.x + radius * .62 * math.cos(angle):.2f} {head.y + radius * .62 * math.sin(angle):.2f} '
                            f'L{head.x + radius * .92 * math.cos(angle):.2f} {head.y + radius * .92 * math.sin(angle):.2f}', width=2.)
    return shape


def _eyes(b, rig):
    g, p, r = rig.genome, rig.pose, rig.head.rx
    shape = ''
    for i, x in enumerate((-.24 * r, .55 * r)):
        y, radius = -.13 * r, rig.eye_radius
        openness = max(.02, 1. - min(1., p.blink))
        if openness < .08:
            shape += b.path(f'M{x - radius * 1.4:.2f} {y:.2f} q{radius * 1.4:.2f} 3 {radius * 2.8:.2f} 0', part='eye')
        else:
            shape += f'<g transform="translate({x:.3f} {y:.3f}) scale(1 {openness:.4f})">'
            shape += b.ellipse(Ellipse(0, 0, radius * 1.45, radius * 1.55), 'white', width=1.4, part='eye')
            shape += b.ellipse(Ellipse(radius * .15 + p.look * .22, 0, radius, radius * 1.18), INK if b.line else g.palette.eye, width=.8)
            shape += b.ellipse(Ellipse(radius * .23 + p.look * .22, 0, radius * (.5 if g.age == 'baby' else .32), radius * .9), INK, stroke='none')
            shape += b.ellipse(Ellipse(-radius * .15, -radius * .48, radius * .25, radius * .25), 'white', stroke='none')
            shape += '</g>'
        inner = (-1 if i == 0 else 1) * p.worry * 5
        shape += b.path(f'M{x - radius * 1.45:.2f} {y - radius * 2.05 + inner:.2f} '
                        f'q{radius * 1.4:.2f} {-2 - p.worry * 3:.2f} {radius * 2.8:.2f} {-inner:.2f}', width=1.7)
    return shape


def _face(b, rig):
    g, p, r = rig.genome, rig.pose, rig.head.rx
    h = rig.head
    shape = f'<g transform="translate({h.x:.3f} {h.y:.3f}) rotate({p.head_pitch:.3f})" data-part="head">'
    if g.kind != 'blob':
        for i, x in enumerate((-.67 * r, .66 * r)):
            y, angle = -.82 * r, (1 if i == 0 else -1) * p.ears
            shape += f'<g transform="rotate({angle:.2f} {x:.2f} {y:.2f})" data-part="ear">'
            if g.kind == 'humanoid':
                shape += b.ellipse(Ellipse((-1 if i == 0 else 1) * r, 0, .19 * r, .3 * r))
            elif g.family == 'canine':
                shape += b.polygon(((x - r * .3, y + r * .15), (x, y - r * .63), (x + r * .3, y + r * .15)), b.body)
            else:
                ry = r * (.45 if g.species == 'hyena' else .31)
                shape += b.ellipse(Ellipse(x, y, r * .31, ry), INK if g.species == 'tiger' else b.body)
                shape += b.ellipse(Ellipse(x, y - 1, r * .17, ry * .59), b.accent, width=1.)
            shape += '</g>'
    shape += b.ellipse(Ellipse(0, 0, h.rx, h.ry), part='skull')
    if g.kind == 'humanoid':
        shape += b.path(f'M{-r} {-r * .2} Q{-r * 1.2} {-r * 1.45} {r * .4} {-r * 1.06} '
                        f'Q{r * 1.05} {-r} {r} {-r * .15} Q{r * .5} {-r * .75} {-r} {-r * .2} Z',
                        'white' if b.line else '#493B30')
        shape += _eyes(b, rig)
        shape += b.path(f'M{r * .26} 0 l-3 {r * .32} l6 0', width=1.4, part='nose')
        shape += b.path(f'M{-r * .10} {r * .56} q{r * .35} {r * (.10 + p.jaw * .4)} {r * .62} 0', part='mouth')
    else:
        if 'stripes' in g.marks:
            for x in (-.50 * r, -.12 * r, .25 * r, .58 * r):
                shape += b.path(f'M{x - 4:.2f} {-r:.2f} Q{x + 7:.2f} {-r * .64:.2f} {x + 2:.2f} {-r * .40:.2f} '
                                f'L{x + 7:.2f} {-r:.2f} Z', b.pattern, width=0.)
            for sign in (-1, 1):
                x = sign * r * .95
                shape += b.path(f'M{x} 1 l{-sign * r * .30} {r * .15} l{sign * r * .30} {r * .05} Z', b.pattern, width=0.)
        muzzle_rx = r * (.40 if g.species == 'hyena' or g.family == 'canine' else .31)
        snout = r * .43 if g.species == 'hyena' or g.family == 'canine' else 0.
        shape += f'<g transform="translate({snout:.3f} 0)">'
        if p.jaw > .035:
            shape += b.ellipse(Ellipse(r * .38, r * (.75 + p.jaw * .27), r * .52, r * (.12 + p.jaw * .31)), b.accent, part='jaw')
            shape += b.ellipse(Ellipse(r * .38, r * (.57 + p.jaw * .27), r * .45, r * (.055 + p.jaw * .30)),
                               '#482526', width=1.5, part='mouth')
            shape += b.ellipse(Ellipse(r * .40, r * (.62 + p.jaw * .41), r * .23, r * .10 * p.jaw),
                               'white' if b.line else '#CB797A', stroke='none')
        shape += b.ellipse(Ellipse(r * .03, r * .38, muzzle_rx, r * .23), b.accent, width=1.1, part='muzzle')
        shape += b.ellipse(Ellipse(r * .64, r * .38, muzzle_rx, r * .23), b.accent, width=1.1)
        shape += '</g>'
        shape += _eyes(b, rig)
        shape += f'<g transform="translate({snout:.3f} 0)">'
        shape += b.polygon(((r * .17, r * .19), (r * .62, r * .19), (r * .39, r * .40)), INK, width=1., part='nose')
        shape += b.ellipse(Ellipse(r * .31, r * .23, r * .085, r * .035), 'white' if b.line else '#B29384', stroke='none')
        if p.jaw > .24:
            for x in (.06 * r, .68 * r):
                shape += b.path(f'M{x - r * .07:.2f} {r * .58:.2f} L{x + r * .07:.2f} {r * .58:.2f} '
                                f'Q{x + r * .06:.2f} {r * (.67 + .29 * p.jaw):.2f} {x:.2f} {r * (.67 + .30 * p.jaw):.2f} Z',
                                'white', width=.9, part='canine')
        else:
            shape += b.path(f'M{r * .39} {r * .40} v{r * .13} m0 0 q{-r * .17} {r * .14} {-r * .35} 0 '
                            f'm{r * .35} 0 q{r * .17} {r * .14} {r * .35} 0', width=1.5, part='mouth_line')
        if g.family == 'feline':
            for side in (-1, 1):
                for j in range(3):
                    x = r * (.03 if side == -1 else .67)
                    y = r * (.34 + j * .10)
                    shape += b.path(f'M{x:.2f} {y:.2f} q{side * r * .42:.2f} {-4 + j * 3} {side * r * .73:.2f} {-7 + j * 6}',
                                    width=.85, part='whisker')
        for mark, x, y in (('scar_nose', r * .39, r * .28), ('scar_eye', r * .55, -r * .12)):
            if mark in g.marks:
                shape += b.path(f'M{x - r * .27} {y - r * .12} l{r * .54} {r * .24}',
                                stroke=INK if b.line else '#99534F', width=2.2, part=mark)
                for offset in (-.1, .1):
                    shape += b.path(f'M{x + r * offset} {y - r * .07} l-2 {r * .16}', width=1.)
        shape += '</g>'
    return shape + '</g>'


def _effects(b, rig, t):
    p, parts = rig.pose, rig.parts
    mx, my = parts['mouth']
    shape = ''
    if p.sound > 0:
        if p.sound > 1.05:
            for i in range(3):
                x, y = mx + 29 + i * 15, my - 19 - (i % 2) * 10
                shape += b.path(f'M{x} {y} q7 -11 12 0 m-7 8 q8 -12 13 0', width=2., opacity=min(1., p.sound), part='cackle')
        else:
            for i in range(3):
                x, radius = mx + 25 + i * 14, 11 + i * 8
                shape += b.path(f'M{x:.2f} {my - radius:.2f} q{radius:.2f} {radius:.2f} 0 {2 * radius:.2f}',
                                width=2.2, opacity=p.sound, part='sound_arc')
    elif p.sound < 0:
        for i in range(2):
            x = mx + 17 + i * 10
            shape += b.path(f'M{x:.2f} {my - 3:.2f} q4 4 0 8', width=1.4, opacity=-p.sound, part='whimper_mark')
    if p.puffs > .02:
        for i in range(3):
            u = (t * .85 + i / 3) % 1.
            shape += b.ellipse(Ellipse(mx + 12 + u * 49, my - u * 15, 4 + 12 * u, 3 + 6 * u),
                               'white' if b.line else '#DCEBF0', stroke=INK if b.line else '#A0BEC8',
                               width=1., opacity=p.puffs * (1 - u) * .8, part='breath_puff')
    if p.swipe > .08 and 'front_near' in rig.legs:
        limb = rig.legs['front_near']
        x, y = limb.end
        rx, ry = limb.root
        shape += b.path(f'M{rx + 5:.2f} {-2:.2f} Q{rx + 110:.2f} {ry + 35:.2f} {x + 6:.2f} {y - 10:.2f}',
                        stroke=INK if b.line else rig.genome.palette.accent, width=9., opacity=.23 * p.swipe, part='swipe_smear')
        for i in range(2):
            shape += b.path(f'M{rx + 17 + i * 11:.2f} {-2 - i * 7:.2f} '
                            f'Q{rx + 103 + i * 8:.2f} {ry + 48:.2f} {x + 9 + i * 9:.2f} {y - 8 - i * 7:.2f}',
                            width=1.5, opacity=p.swipe, part='motion_line')
    return shape


def svg(genome: Genome, action: Action | str | Pose | list[Action] = 'idle', t: float = 0., style='flat') -> str:
    if style not in ('flat', 'line_art'):
        raise ValueError(f'Unknown creature style: {style}')
    g = genome.repair()
    p = pose_at(g, action, t)
    rig = build(g, p, t)
    b = _Brush(g, style, t)
    sx, sy = squash_scale(p.squash)
    shapes = []
    if rig.tail:
        d = 'M' + ' L'.join(f'{x:.2f} {y:.2f}' for x, y in rig.tail)
        width = 7. if g.age == 'baby' else 9.
        shapes += [b.path(d, stroke=INK, width=width + 3., part='tail'), b.path(d, stroke=b.body, width=width)]
        if g.species == 'lion':
            x, y = rig.tail[-1]
            shapes.append(b.ellipse(Ellipse(x, y, 8., 11.), 'white' if b.line else '#80522C', part='tail_tuft'))
        elif 'stripes' in g.marks:
            for x, y in rig.tail[1::2]:
                shapes.append(b.path(f'M{x - 2:.2f} {y - 4:.2f} l3 8', stroke=b.pattern, width=4.))
    for name, limb in rig.legs.items():
        if 'far' in name:
            shapes.append(_limb(b, limb, name, far=True, human=g.kind == 'humanoid'))
    shapes += [b.ellipse(rig.body, part='body'), b.ellipse(rig.chest, part='chest')]
    if g.kind == 'quadruped':
        shapes.append(b.path(f'M{rig.chest.x:.2f} {rig.chest.y:.2f} '
                             f'Q{rig.head.x - 18:.2f} {rig.chest.y - 12:.2f} {rig.head.x:.2f} {rig.head.y + 12:.2f}',
                             stroke=INK, width=28., part='neck'))
        shapes.append(b.path(f'M{rig.chest.x:.2f} {rig.chest.y:.2f} '
                             f'Q{rig.head.x - 18:.2f} {rig.chest.y - 12:.2f} {rig.head.x:.2f} {rig.head.y + 12:.2f}',
                             stroke=b.body, width=25.))
    if g.kind == 'humanoid':
        shapes.append(b.ellipse(rig.body, 'white' if b.line else g.palette.accent, part='shirt'))
    shapes.append(_coat(b, rig))
    if g.species == 'hyena' or 'fluffy' in g.marks:
        x, y = rig.body.x, rig.body.y - rig.body.ry
        shapes.append(b.path(f'M{x - 38} {y + 10} l8 -15 l7 10 l10 -17 l8 10 l12 -14 l9 13',
                             'white' if b.line else '#4B4037', part='back_fringe'))
    for name, limb in rig.legs.items():
        if 'near' in name:
            shapes.append(_limb(b, limb, name, human=g.kind == 'humanoid'))
    for name, limb in rig.arms.items():
        shapes.append(_limb(b, limb, 'arm_' + name, human=True))
    shapes += [_mane(b, rig), _face(b, rig), _effects(b, rig, t)]
    body, chest = rig.body, rig.chest
    clip = ''.join(f'<ellipse cx="{e.x:.3f}" cy="{e.y:.3f}" rx="{e.rx:.3f}" ry="{e.ry:.3f}"/>' for e in (body, chest))
    defs = (f'<defs><linearGradient id="body_shade" x1="0" y1="0" x2=".3" y2="1">'
            f'<stop stop-color="{g.palette.body}"/><stop offset="1" stop-color="{_shade(g.palette.body, .17)}"/>'
            f'</linearGradient><clipPath id="coat">{clip}</clipPath></defs>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<title>{escape(g.name or g.species)}</title>{defs}'
            f'<g transform="translate({W / 2 + p.dx * g.size:.3f} {GROUND + p.dy * g.size:.3f}) '
            f'scale({g.size * sx:.5f} {g.size * sy:.5f})">' + ''.join(shapes) + '</g></svg>')


def raster(genome: Genome, action: Action | str | Pose | list[Action] = 'idle', t: float = 0.,
           style='flat', height=300) -> Image.Image:
    doc = svg(genome, action, t, style)
    width = round(height * W / H)
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=doc, width=width, height=height))).convert('RGBA')

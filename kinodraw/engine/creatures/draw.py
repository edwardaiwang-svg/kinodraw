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

W, H, GROUND = 600, 400, 358
INK = '#292321'


def _shade(color, amount):
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(c * (1 - amount)):02X}' for c in rgb)


class _Brush:
    def __init__(self, genome, style, t):
        self.genome = genome
        self.line = style == 'line_art'
        self.rng = genome.stream(f'pattern:ink:{int(t * 7.5)}')
        self.body = 'white' if self.line else 'url(#body_shade)'
        self.far = 'white' if self.line else _shade(genome.palette.body, .26)
        self.accent = 'white' if self.line else genome.palette.accent
        self.pattern = INK if self.line else '#382920'
        self.outer = 3.2 if self.line else 2.4

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
    color = b.far if far else b.body
    points = (a, j, (end[0] - 3, end[1] - 8))
    normals = []
    for start, finish in ((a, j), (a, end), (j, end)):
        dx, dy = finish[0] - start[0], finish[1] - start[1]
        length = math.hypot(dx, dy)
        normals.append((dy / length, -dx / length))
    edges = []
    for sign in (1, -1):
        edges.append([(p[0] + sign * n[0] * limb.width * taper,
                       p[1] + sign * n[1] * limb.width * taper)
                      for p, n, taper in zip(points, normals, (.52, .31, .20))])
    def xy(p):
        return f'{p[0]:.2f} {p[1]:.2f}'
    l, r = edges
    d = (f'M{xy(l[0])} Q{xy(l[1])} {xy(l[2])} Q{end[0] + 3:.2f} {end[1]:.2f} {xy(r[2])} '
         f'Q{xy(r[1])} {xy(r[0])} Q{a[0]:.2f} {a[1] - limb.width * .65:.2f} {xy(l[0])} Z')
    shape = b.path(d, color, width=b.outer, part=part)
    shape += b.path(f'M{a[0] - limb.width * .38:.2f} {a[1] + 2:.2f} '
                    f'q{-limb.width * .1:.2f} {-limb.width * .7:.2f} {limb.width * .50:.2f} {-limb.width * .45:.2f}',
                    width=1.1, opacity=.65, part=part + '_mass')
    shape += b.path(f'M{j[0] - 4:.2f} {j[1] - 3:.2f} q5 2 7 7', width=.9, opacity=.55, part=part + '_joint')
    if 'stripes' in b.genome.marks and not human:
        bands = ''
        for u in (.32, .60, .79):
            start, finish = (a, j) if u < .5 else (j, points[2])
            v = u * 2 if u < .5 else (u - .5) * 2
            x, y = start[0] + (finish[0] - start[0]) * v, start[1] + (finish[1] - start[1]) * v
            nx, ny = normals[0 if u < .5 else 2]
            w = limb.width * .5
            bands += b.path(f'M{x - nx * w:.2f} {y - ny * w:.2f} '
                            f'q{nx * w:.2f} {ny * w + 6:.2f} {nx * w * 2:.2f} {ny * w * 2:.2f} '
                            f'l{-nx * w * .2:.2f} {-ny * w * .2 + 5:.2f} '
                            f'q{-nx * w:.2f} {-ny * w - 3:.2f} {-nx * w * 1.8:.2f} {-ny * w * 1.8 - 5:.2f} Z',
                            b.pattern, width=0., part='leg_stripe')
        shape += f'<defs><clipPath id="{part}_clip"><path d="{d}"/></clipPath></defs><g clip-path="url(#{part}_clip)">{bands}</g>'
    paw_rx = limb.width * (.90 if b.genome.age == 'baby' else .72)
    shape += b.ellipse(Ellipse(end[0] + 5, end[1] + 1, paw_rx, limb.width * .40), color,
                       width=b.outer, part=part + '_paw')
    if not human:
        for x in (-.15, .18, .48):
            shape += b.path(f'M{end[0] + 5 + paw_rx * x:.2f} {end[1] + 1:.2f} q-2 2 -1 5', width=.9, part='toe')
    return shape


def _coat(b, rig):
    g, body = rig.genome, rig.body
    shapes = []
    if 'stripes' in g.marks:
        for i in range(7):
            x = body.x + body.rx * (-.84 + i * .27)
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
    h, radius, p = rig.head, rig.mane_radius, rig.pose
    black = 'mane_black' in rig.genome.marks
    colors = ('#443D40', '#30292D', '#201D22') if black else ('#C58A46', '#A56C32', '#784927')
    cx, cy = h.x + p.mane_lag, h.y - p.mane_lag * .5
    flare = 1 + max(0., p.mane) * .003
    shape = ''
    # Overlapping scalloped rings keep a soft silhouette and a dark face frame.
    for ring, scale in enumerate((1., .84, .66)):
        count = 15 - ring * 2
        rng = rig.genome.stream(f'pattern:mane_lobes:{ring}')
        points = []
        for i in range(count):
            chain = rig.mane[i % len(rig.mane)]
            angle = 2 * math.pi * (i + ring * .31) / count
            sway = (chain[-1][0] - chain[0][0]) * .06
            reach = radius * scale * flare * rng.uniform(.94, 1.05)
            valley = reach * .89
            start = (cx + valley * math.cos(angle - math.pi / count),
                     cy + valley * math.sin(angle - math.pi / count))
            end = (cx + valley * math.cos(angle + math.pi / count),
                   cy + valley * math.sin(angle + math.pi / count))
            tip = (cx + reach * math.cos(angle) + sway, cy + reach * math.sin(angle))
            tangent = (-math.sin(angle) * reach * .12, math.cos(angle) * reach * .12)
            start = start[0], min(-7., start[1])
            end = end[0], min(-7., end[1])
            tip = tip[0], min(-7., tip[1])
            points.append((start, end, tip, tangent))
        d = f'M{points[0][0][0]:.2f} {points[0][0][1]:.2f}'
        for start, end, tip, tangent in points:
            d += (f'L{start[0]:.2f} {start[1]:.2f} '
                  f'C{tip[0] - tangent[0]:.2f} {tip[1] - tangent[1]:.2f} '
                  f'{tip[0] + tangent[0]:.2f} {tip[1] + tangent[1]:.2f} {end[0]:.2f} {end[1]:.2f}')
        shape += b.path(d + ' Z', 'white' if b.line else colors[ring],
                        width=b.outer if ring == 0 else 1., part='mane' if ring == 0 else 'mane_layer')
        for i in range(count):
            angle = 2 * math.pi * (i + .2 + ring * .31) / count
            inner, outer = radius * scale * .76, radius * scale * .94 * flare
            x, y = cx + inner * math.cos(angle), cy + inner * math.sin(angle)
            shape += b.path(f'M{x:.2f} {y:.2f} Q{x + 5:.2f} {y + 2:.2f} '
                            f'{cx + outer * math.cos(angle):.2f} {cy + outer * math.sin(angle):.2f}',
                            stroke=INK if b.line else colors[max(0, ring - 1)], width=.9, opacity=.6)
    x, y = cx - radius * .12, cy + radius * .40
    length = max(0., min(63., -8 - y))
    chest = b.path(f'M{x - 31:.2f} {y:.2f} Q{x - 43:.2f} {y + length * .60:.2f} {x - 27:.2f} {y + length * .85:.2f} '
                    f'Q{x - 17:.2f} {y + length * 1.06:.2f} {x - 10:.2f} {y + length * .88:.2f} '
                    f'Q{x + 2:.2f} {y + length * 1.15:.2f} {x + 12:.2f} {y + length * .91:.2f} '
                    f'Q{x + 35:.2f} {y + length * 1.02:.2f} {x + 30:.2f} {y + length * .70:.2f} '
                    f'Q{x + 40:.2f} {y + length * .36:.2f} {x + 28:.2f} {y:.2f} Z',
                    'white' if b.line else colors[1], width=b.outer, part='chest_mane')
    for offset in (-12, 3, 17):
        chest += b.path(f'M{x + offset:.2f} {y + length * .15:.2f} q-8 {length * .4:.2f} 0 {length * .65:.2f}',
                        stroke=INK if b.line else colors[0], width=1., opacity=.7)
    return chest + shape


def _eyes(b, rig):
    g, p, r = rig.genome, rig.pose, rig.head.rx
    shape = ''
    for i, x in enumerate((-.24 * r, .55 * r)):
        y, radius = -.13 * r, rig.eye_radius
        openness = max(.02, (1. - min(1., p.blink)) * (1 - .62 * min(1., p.fierce)))
        if openness < .08:
            shape += b.path(f'M{x - radius * 1.4:.2f} {y:.2f} q{radius * 1.4:.2f} 3 {radius * 2.8:.2f} 0', part='eye')
        else:
            shape += f'<g transform="translate({x:.3f} {y:.3f}) scale(1 {openness:.4f})">'
            shape += b.ellipse(Ellipse(0, 0, radius * 1.42, radius * 1.45), 'white', width=1.4, part='eye')
            shape += b.ellipse(Ellipse(radius * .15 + p.look * .22, 0, radius * .88, radius * 1.12),
                               INK if b.line else g.palette.eye, width=.8, part='iris')
            shape += b.ellipse(Ellipse(radius * .23 + p.look * .22, 0, radius * (.48 if g.age == 'baby' else .34), radius * .85),
                               INK, stroke='none', part='pupil')
            shape += b.ellipse(Ellipse(-radius * .12, -radius * .45, radius * .29, radius * .29), 'white', stroke='none', part='eye_highlight')
            shape += b.ellipse(Ellipse(radius * .44, radius * .46, radius * .12, radius * .12), 'white', stroke='none')
            shape += '</g>'
        outer_y = y - radius * 1.9 + p.worry * 3 - p.fierce * 3
        inner_y = y - radius * 1.9 - p.worry * 5 + p.fierce * 7
        left_y, right_y = (outer_y, inner_y) if i == 0 else (inner_y, outer_y)
        shape += b.path(f'M{x - radius * 1.45:.2f} {left_y:.2f} '
                        f'Q{x:.2f} {min(left_y, right_y) - 3:.2f} {x + radius * 1.45:.2f} {right_y:.2f}',
                        width=2.6 if p.fierce > .2 else 1.7, part='brow')
        if g.species == 'tiger' and g.sex == 'female':
            sign = -1 if i == 0 else 1
            shape += b.path(f'M{x + sign * radius * 1.3:.2f} {y - radius * .6:.2f} '
                            f'l{sign * 4} -3 m{-sign * 2} 4 l{sign * 4} -1', width=1.2, part='lash')
    return shape


def _mouth(b, rig, snout):
    p, r = rig.pose, rig.head.rx
    shape = f'<g transform="translate({snout:.3f} 0)">'
    if p.jaw > .035:
        angle = min(65., max(0., p.jaw) * 48.)
        hinge = (-r * .13, r * .43)
        def lowered(x, y):
            theta = math.radians(angle)
            dx, dy = x - hinge[0], y - hinge[1]
            return hinge[0] + dx * math.cos(theta) - dy * math.sin(theta), hinge[1] + dx * math.sin(theta) + dy * math.cos(theta)
        bottom = lowered(r * .90, r * .69)
        back = lowered(-r * .12, r * .69)
        shape += b.path(f'M{hinge[0]:.2f} {hinge[1]:.2f} Q{r * .42:.2f} {r * .34:.2f} {r * .94:.2f} {r * .48:.2f} '
                        f'L{bottom[0]:.2f} {bottom[1]:.2f} Q{back[0] + r * .3:.2f} {back[1] + r * .1:.2f} {back[0]:.2f} {back[1]:.2f} Z',
                        '#44252B', width=1.3, part='mouth')
        shape += f'<g transform="rotate({angle:.3f} {hinge[0]:.3f} {hinge[1]:.3f})" data-part="jaw_hinge" data-angle="{angle:.3f}">'
        shape += b.path(f'M{-r * .15:.2f} {r * .63:.2f} Q{r * .38:.2f} {r * .76:.2f} {r * .94:.2f} {r * .61:.2f} '
                        f'Q{r * .94:.2f} {r * .95:.2f} {r * .38:.2f} {r * .92:.2f} Q{-r * .15:.2f} {r * .87:.2f} {-r * .15:.2f} {r * .63:.2f} Z',
                        b.accent, width=b.outer, part='jaw')
        shape += b.ellipse(Ellipse(r * .44, r * .65, r * .27, r * .11),
                           'white' if b.line else '#D58C91', width=.8, part='tongue')
        shape += b.path(f'M{r * .40:.2f} {r * .59:.2f} l0 {r * .08:.2f}', width=.8)
        if p.jaw > .24:
            for x in (.04 * r, .76 * r):
                shape += b.path(f'M{x - r * .065:.2f} {r * .69:.2f} L{x + r * .065:.2f} {r * .69:.2f} '
                                f'Q{x + r * .035:.2f} {r * .49:.2f} {x:.2f} {r * .46:.2f} Z', 'white', width=.9, part='canine')
        shape += '</g>'
        if p.jaw > .24:
            for x in (-.01 * r, .79 * r):
                shape += b.path(f'M{x - r * .075:.2f} {r * .49:.2f} L{x + r * .075:.2f} {r * .49:.2f} '
                                f'Q{x + r * .06:.2f} {r * .75:.2f} {x:.2f} {r * .80:.2f} '
                                f'Q{x - r * .07:.2f} {r * .70:.2f} {x - r * .075:.2f} {r * .49:.2f} Z', 'white', width=.9, part='canine')
    else:
        shape += b.ellipse(Ellipse(r * .34, r * .65, r * .34, r * .19), b.accent, width=1.1, part='chin')
    return shape + '</g>'


def _face(b, rig):
    g, p, r = rig.genome, rig.pose, rig.head.rx
    h, baby = rig.head, g.age == 'baby'
    shape = f'<g transform="translate({h.x:.3f} {h.y:.3f}) rotate({p.head_pitch:.3f})" data-part="head">'
    if g.kind != 'blob':
        for i, x in enumerate((-.67 * r, .66 * r)):
            y, angle = -.82 * r, (1 if i == 0 else -1) * p.ears
            flat = min(1., max(0., p.ears) / 72.)
            if g.kind == 'quadruped':
                x += (-1 if i == 0 else 1) * r * .23 * flat
                y += r * .42 * flat
            shape += f'<g transform="rotate({angle:.2f} {x:.2f} {y:.2f})" data-part="ear">'
            if g.kind == 'humanoid':
                shape += b.ellipse(Ellipse((-1 if i == 0 else 1) * r, 0, .19 * r, .3 * r), width=b.outer)
            elif g.family == 'canine':
                shape += b.polygon(((x - r * .3, y + r * .15), (x, y - r * .63), (x + r * .3, y + r * .15)), b.body, width=b.outer)
                shape += b.polygon(((x - r * .17, y + r * .05), (x, y - r * .40), (x + r * .17, y + r * .05)), b.accent, width=1., part='inner_ear')
            else:
                ry = r * (.28 if g.species == 'hyena' else .31)
                rx = r * (.25 if g.species == 'hyena' else .31)
                ry *= 1 - .55 * flat
                shape += b.ellipse(Ellipse(x, y, rx, ry), INK if g.species == 'tiger' else b.body,
                                   width=b.outer, part='ear_shell')
                shape += b.ellipse(Ellipse(x, y - 1, rx * .58, ry * .62),
                                   'white' if b.line else '#C79278', width=1., part='inner_ear')
            shape += '</g>'
    if g.species == 'tiger':
        for sign in (-1, 1):
            shape += b.path(f'M{sign * r * .72:.2f} {-r * .06:.2f} '
                            f'Q{sign * r * 1.20:.2f} {r * .05:.2f} {sign * r * 1.04:.2f} {r * .29:.2f} '
                            f'Q{sign * r * 1.31:.2f} {r * .34:.2f} {sign * r * 1.07:.2f} {r * .52:.2f} '
                            f'Q{sign * r * 1.18:.2f} {r * .73:.2f} {sign * r * .76:.2f} {r * .70:.2f} Z',
                            'white' if b.line else '#FFF1D8', width=b.outer, part='cheek_ruff')
    shape += b.ellipse(Ellipse(0, 0, h.rx, h.ry), width=b.outer, part='skull')
    if not b.line:
        shape += b.path(f'M{-r * .83:.2f} {-r * .20:.2f} Q{-r * .75:.2f} {-r * .95:.2f} {r * .10:.2f} {-r * .90:.2f}',
                        stroke='#FFF0C9', width=2.7, opacity=.38, part='head_rim')
    if g.kind == 'humanoid':
        shape += b.path(f'M{-r} {-r * .2} Q{-r * 1.2} {-r * 1.45} {r * .4} {-r * 1.06} '
                        f'Q{r * 1.05} {-r} {r} {-r * .15} Q{r * .5} {-r * .75} {-r} {-r * .2} Z',
                        'white' if b.line else '#493B30')
        shape += _eyes(b, rig)
        shape += b.path(f'M{r * .26} 0 l-3 {r * .32} l6 0', width=1.4, part='nose')
        shape += b.path(f'M{-r * .10} {r * .56} q{r * .35} {r * (.10 + p.jaw * .4)} {r * .62} 0', part='mouth')
    else:
        if baby:
            shape += b.path(f'M{-r * .27:.2f} {-r * .89:.2f} '
                            f'Q{-r * .45:.2f} {-r * 1.17:.2f} {-r * .12:.2f} {-r * 1.08:.2f} '
                            f'Q{-r * .05:.2f} {-r * 1.28:.2f} {r * .16:.2f} {-r * 1.10:.2f} '
                            f'Q{r * .38:.2f} {-r * 1.13:.2f} {r * .34:.2f} {-r * .88:.2f}',
                            b.body, width=b.outer, part='forehead_tuft')
        if 'stripes' in g.marks:
            for x, tilt in ((-.43 * r, .12 * r), (0., 0.), (.43 * r, -.10 * r)):
                shape += b.path(f'M{x - 4:.2f} {-r * .94:.2f} Q{x + tilt:.2f} {-r * .66:.2f} {x + tilt:.2f} {-r * .42:.2f} '
                                f'Q{x + tilt + 6:.2f} {-r * .69:.2f} {x + 5:.2f} {-r * .94:.2f} Z', b.pattern, width=0., part='face_stripe')
            for sign in (-1, 1):
                for y in (.12, .35):
                    shape += b.path(f'M{sign * r * .94:.2f} {r * y:.2f} '
                                    f'Q{sign * r * .70:.2f} {r * (y + .09):.2f} {sign * r * .63:.2f} {r * (y + .18):.2f} '
                                    f'Q{sign * r * .87:.2f} {r * (y + .17):.2f} {sign * r * 1.04:.2f} {r * (y + .12):.2f} Z',
                                    b.pattern, width=0., part='face_stripe')
        dark = g.species == 'hyena'
        snout = r * (.27 if dark else .43 if g.family == 'canine' else 0.)
        shape += _mouth(b, rig, snout)
        shape += f'<g transform="translate({snout:.3f} 0)">'
        muzzle_rx = r * (.29 if baby else .35)
        muzzle_fill = 'white' if b.line else '#493F38' if dark else b.accent
        for x in (.02 * r, .65 * r):
            shape += b.ellipse(Ellipse(x, r * .42, muzzle_rx, r * (.20 if baby else .25)),
                               muzzle_fill, width=1.2, part='muzzle')
        nose_width = r * (.18 if baby else .29 if rig.mane else .24)
        nx, ny = r * .35, r * .22
        shape += b.path(f'M{nx - nose_width:.2f} {ny:.2f} Q{nx:.2f} {ny - r * .09:.2f} {nx + nose_width:.2f} {ny:.2f} '
                        f'Q{nx + nose_width * .75:.2f} {ny + r * .21:.2f} {nx:.2f} {ny + r * .23:.2f} '
                        f'Q{nx - nose_width * .75:.2f} {ny + r * .20:.2f} {nx - nose_width:.2f} {ny:.2f} Z',
                        INK, width=1., part='nose')
        shape += b.path(f'M{nx - nose_width * .55:.2f} {ny + 1:.2f} q{nose_width * .55:.2f} -2 {nose_width * 1.1:.2f} 0',
                        stroke='white' if b.line else '#BC9B91', width=1.4, part='nose_top')
        if p.jaw <= .24:
            shape += b.path(f'M{nx:.2f} {ny + r * .23:.2f} v{r * .14:.2f}', width=1.2)
            if p.worry > .15:
                shape += b.path(f'M{nx - r * .12:.2f} {r * .67:.2f} q{r * .12:.2f} {-r * .07:.2f} {r * .24:.2f} 0', width=1.2, part='mouth_line')
            else:
                shape += b.path(f'M{nx:.2f} {r * .59:.2f} q{-r * .17:.2f} {r * .13:.2f} {-r * .31:.2f} 0 '
                                f'm{r * .31:.2f} 0 q{r * .17:.2f} {r * .13:.2f} {r * .31:.2f} 0', width=1.2, part='mouth_line')
        if g.family == 'feline':
            for side in (-1, 1):
                for j in range(3):
                    x = r * (.03 if side == -1 else .67)
                    y = r * (.40 + j * .08)
                    shape += b.ellipse(Ellipse(x, y, .7, .7), INK, stroke='none')
                    shape += b.path(f'M{x:.2f} {y:.2f} q{side * r * .28:.2f} {-3 + j * 2} {side * r * .49:.2f} {-6 + j * 5}',
                                    width=.8, opacity=.8, part='whisker')
        shape += '</g>'
        shape += _eyes(b, rig)
        if 'scar_nose' in g.marks or 'scar_eye' in g.marks:
            full = 'scar_nose' in g.marks and bool(rig.mane)
            x1, y1 = r * .69, -r * .53 if full or 'scar_eye' in g.marks else r * .17
            x2, y2 = (r * .19, r * .48) if 'scar_nose' in g.marks else (r * .48, r * .13)
            shape += b.path(f'M{x1:.2f} {y1:.2f} L{x2:.2f} {y2:.2f}',
                            stroke=INK if b.line else '#713F3B', width=3.7, part='scar_nose' if 'scar_nose' in g.marks else 'scar_eye')
            shape += b.path(f'M{x1 - 1.7:.2f} {y1:.2f} L{x2 - 1.7:.2f} {y2:.2f}',
                            stroke='white' if b.line else '#DFAB8A', width=1.2)
            for u in (.22, .48, .76):
                x, y = x1 + (x2 - x1) * u, y1 + (y2 - y1) * u
                shape += b.path(f'M{x - 3:.2f} {y - 2:.2f} l6 4', width=1.1)
    return shape + '</g>'


def _effects(b, rig, t):
    p, parts = rig.pose, rig.parts
    mx, my = parts['mouth']
    shape = ''
    if p.sound > 0:
        for i in range(3):
            expansion = p.sound_expand
            x, radius = mx + 18 + i * 21 + expansion * 6, 20 + i * 16 + expansion * 6
            shape += b.path(f'M{x:.2f} {my - radius:.2f} q{radius * .90:.2f} {radius:.2f} 0 {2 * radius:.2f}',
                            stroke=INK if b.line or i == 2 else '#C9954E' if i == 0 else '#9F774B',
                            width=3.1 - i * .35, opacity=min(1., p.sound) * (1 - i * .16), part='sound_arc')
    elif p.sound < 0:
        for i in range(2):
            x = mx + 17 + i * 10
            shape += b.path(f'M{x:.2f} {my - 3:.2f} q4 4 0 8', width=1.4, opacity=-p.sound, part='whimper_mark')
    if p.cackle > .02:
        for i in range(3):
            x, y = mx + 30 + i * 18, my - 40 - (i % 2) * 14
            shape += b.path(f'M{x} {y} l-3 -10 m8 12 l4 -13 m3 15 l9 -8',
                            width=2., opacity=min(1., p.cackle), part='cackle')
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


def _body_outline(rig):
    body, chest = rig.body, rig.chest
    x, y, rx, ry = body.x, body.y, body.rx, body.ry
    cx, cy = chest.x, chest.y
    slope = .65 if rig.genome.species == 'hyena' else 1.12
    return (f'M{x - rx:.2f} {y:.2f} '
            f'C{x - rx:.2f} {y - ry * slope:.2f} {x - rx * .45:.2f} {y - ry * slope:.2f} {cx:.2f} {cy - chest.ry:.2f} '
            f'C{cx + chest.rx:.2f} {cy - chest.ry:.2f} {cx + chest.rx * 1.12:.2f} {cy + chest.ry * .36:.2f} {cx + chest.rx * .25:.2f} {cy + chest.ry * .80:.2f} '
            f'C{x + rx * .25:.2f} {y + ry * 1.10:.2f} {x - rx:.2f} {y + ry:.2f} {x - rx:.2f} {y:.2f} Z')


def _torso(b, rig):
    body, chest, g = rig.body, rig.chest, rig.genome
    if g.kind != 'quadruped':
        return b.ellipse(body, width=b.outer, part='body') + b.ellipse(chest, part='chest')
    d = _body_outline(rig)
    shape = '<g clip-path="url(#coat)">'
    shape += b.path(d, b.body, width=0.)
    shape += b.ellipse(body, stroke='none', width=0., part='body')
    shape += b.ellipse(chest, stroke='none', width=0., part='chest')
    shape += _coat(b, rig)
    x, y, rx, ry = body.x, body.y, body.rx, body.ry
    shape += b.path(f'M{x - rx * .74:.2f} {y + ry * .38:.2f} '
                    f'Q{x:.2f} {y + ry * .60:.2f} {chest.x + chest.rx * .48:.2f} {chest.y + chest.ry * .35:.2f} '
                    f'L{chest.x + chest.rx * .30:.2f} {chest.y + chest.ry:.2f} '
                    f'Q{x:.2f} {y + ry * 1.2:.2f} {x - rx * .74:.2f} {y + ry * .38:.2f} Z',
                    b.accent, stroke='none', part='belly')
    if not b.line:
        shape += b.path(f'M{x - rx:.2f} {y + 4:.2f} Q{x - rx * .30:.2f} {y + ry * .80:.2f} {chest.x + 8:.2f} {chest.y + chest.ry * .65:.2f} '
                        f'L{chest.x + 8:.2f} {chest.y + chest.ry:.2f} Q{x - rx:.2f} {y + ry * 1.1:.2f} {x - rx:.2f} {y + 4:.2f} Z',
                        '#5B3524', stroke='none', opacity=.12, part='underside_shade')
    shape += '</g>' + b.path(d, width=b.outer, part='body_outline')
    if not b.line:
        shape += b.path(f'M{x - rx * .85:.2f} {y - ry * .20:.2f} Q{x - rx * .55:.2f} {y - ry * .97:.2f} {x + rx * .35:.2f} {y - ry * .90:.2f}',
                        stroke='#FFF0C9', width=2.5, opacity=.38, part='rim_highlight')
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
    if g.kind == 'quadruped':
        neck = (f'M{rig.chest.x:.2f} {rig.chest.y:.2f} '
                f'Q{rig.head.x - 18:.2f} {rig.chest.y - 12:.2f} {rig.head.x:.2f} {rig.head.y + 12:.2f}')
        width = 48. if g.species == 'hyena' else 34. if g.age == 'baby' else 32.
        shapes += [b.path(neck, width=width + b.outer * 2, part='neck'), b.path(neck, stroke=b.body, width=width)]
    shapes.append(_torso(b, rig))
    if g.kind == 'humanoid':
        shapes.append(b.ellipse(rig.body, 'white' if b.line else g.palette.accent, part='shirt'))
    if g.species == 'hyena':
        body, chest = rig.body, rig.chest
        controls = ((body.x - body.rx, body.y), (body.x - body.rx, body.y - body.ry * .65),
                    (body.x - body.rx * .45, body.y - body.ry * .65), (chest.x, chest.y - chest.ry))
        ridge = []
        for i in range(13):
            u = .62 + .38 * i / 12
            weights = ((1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u * u, u ** 3)
            x, y = (sum(point[axis] * weight for point, weight in zip(controls, weights)) for axis in (0, 1))
            ridge.append((x, y - (7 + i % 3 if i % 2 else 0)))
        d = 'M' + ' L'.join(f'{x:.2f} {y:.2f}' for x, y in ridge)
        d += (f'Q{rig.head.x - 32:.2f} {rig.head.y - 28:.2f} {rig.head.x - 23:.2f} {rig.head.y - 12:.2f} '
              f'L{chest.x:.2f} {chest.y - chest.ry + 9:.2f}')
        d += ' L' + ' L'.join(f'{x:.2f} {y + 7:.2f}' for x, y in reversed(ridge[::2])) + ' Z'
        shapes.append(b.path(d,
                             'white' if b.line else '#3E3531', width=b.outer, part='back_fringe'))
    elif 'fluffy' in g.marks:
        x, y = rig.body.x, rig.body.y - rig.body.ry
        shapes.append(b.path(f'M{x - 28} {y + 6} q6 -12 12 -4 q8 -13 16 -4 q8 -12 16 0',
                             b.body, width=1.2, part='back_fringe'))
    for name, limb in rig.legs.items():
        if 'near' in name:
            shapes.append(_limb(b, limb, name, human=g.kind == 'humanoid'))
    for name, limb in rig.arms.items():
        shapes.append(_limb(b, limb, 'arm_' + name, human=True))
    shapes += [_mane(b, rig), _face(b, rig), _effects(b, rig, t)]
    body, chest = rig.body, rig.chest
    clip = (f'<path d="{_body_outline(rig)}"/>' if g.kind == 'quadruped' else
            ''.join(f'<ellipse cx="{e.x:.3f}" cy="{e.y:.3f}" rx="{e.rx:.3f}" ry="{e.ry:.3f}"/>' for e in (body, chest)))
    defs = (f'<defs><linearGradient id="body_shade" x1="0" y1="0" x2=".3" y2="1">'
            f'<stop stop-color="{g.palette.body}"/><stop offset=".6" stop-color="{g.palette.body}"/>'
            f'<stop offset="1" stop-color="{_shade(g.palette.body, .14)}"/>'
            f'</linearGradient><clipPath id="coat">{clip}</clipPath></defs>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<title>{escape(g.name or g.species)}</title>{defs}'
            f'<metadata data-screen-shake="{p.screen_shake:.3f}"/>'
            f'<g transform="translate({W / 2 + p.dx * g.size:.3f} {GROUND + p.dy * g.size:.3f}) '
            f'scale({g.size * sx:.5f} {g.size * sy:.5f})">' + ''.join(shapes) + '</g></svg>')


def raster(genome: Genome, action: Action | str | Pose | list[Action] = 'idle', t: float = 0.,
           style='flat', height=300) -> Image.Image:
    doc = svg(genome, action, t, style)
    width = round(height * W / H)
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=doc, width=width, height=height))).convert('RGBA')

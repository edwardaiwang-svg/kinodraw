"""Fish body plan (side view): lens body, tail fin by kind, dorsal and side fins, gill line, round eye."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, deg, rot, unit
from .sdf import Circle, Cone, Ellipse, Poly, Tube, Union


@dataclass
class Fish:
    kind: str = 'goldfish'      # goldfish clownfish tang shark
    coat: str = '#F28C28'
    belly: str = ''
    fin: str = ''
    bands: str = ''             # vertical bands (clownfish)
    tail_c: str = ''
    body_rx: float = .4
    body_ry: float = .25
    tail: str = 'fan'           # fan fork moon
    dorsal: str = 'round'       # round tall shark
    young: bool = False
    seed: int = 0


POSES = ('swim1', 'swim2', 'jump', 'sleep', 'roar', 'look_up', 'scared')


def build(g: Fish, pose: str) -> Figure:
    f = Figure()
    bend = {'swim1': 12, 'swim2': -12, 'jump': 8, 'scared': -6}.get(pose, 0)
    tilt = deg({'jump': 32, 'look_up': 22, 'sleep': -4}.get(pose, 0))
    c = V(0, .45 if pose != 'jump' else .6)
    rx, ry = g.body_rx, g.body_ry
    shark = g.kind == 'shark'

    def P(x, y):
        return c + rot(V(x, y), tilt)
    if shark:
        body = Union([Ellipse(P(0, 0), rx, ry, tilt), Poly([P(rx * .55, ry * .45), P(rx * 1.25, -ry * .05),
                                                             P(rx * .55, -ry * .6)], r=.03)], k=.08)
    else:
        body = Ellipse(P(0, 0), rx, ry, tilt)
    # tail
    root = P(-rx * .9, 0)
    ta = tilt + math.pi + deg(bend)
    d, n = unit(ta), unit(ta + math.pi / 2)
    tl = ry * (1.15 if g.tail != 'moon' else 1.3)
    stalk = Cone(P(-rx * .55, 0), root + d * .05, ry * .45, ry * .18)
    if g.tail == 'fork' or g.tail == 'moon':
        fin = Poly([root, root + d * tl * .9 + n * tl * .75, root + d * tl * .55, root + d * tl * .9 - n * tl * .75],
                   r=.02)
    else:                                       # fan: rounded, flowing
        fin = Union([Ellipse(root + d * tl * .5 + n * tl * .28, tl * .5, tl * .28, ta + deg(28)),
                     Ellipse(root + d * tl * .5 - n * tl * .28, tl * .5, tl * .28, ta - deg(28))], k=.05)
    fin_c = g.fin or C.shade(g.coat, .1)
    f.fill(Union([fin, stalk], k=.03), g.tail_c or fin_c, SW_DETAIL + 1, 'tail')
    # far pectoral fin and dorsal fin behind the body
    if g.dorsal == 'shark':
        dorsal = Poly([P(-rx * .25, ry * .7), P(-rx * .05, ry * 2.0), P(rx * .2, ry * .7)], r=.02)
    elif g.dorsal == 'tall':
        dorsal = Poly([P(-rx * .6, ry * .6), P(-rx * .2, ry * 1.5), P(rx * .35, ry * .75)], r=.04)
    else:
        dorsal = Ellipse(P(-rx * .1, ry * .85), rx * .45, ry * .4, tilt - deg(10))
    if pose == 'scared':
        dorsal = Union([dorsal, Ellipse(P(-rx * .1, ry * 1.0), rx * .4, ry * .45, tilt)], k=.03)
    f.fill(dorsal, fin_c, SW_DETAIL + 1, 'dorsal')
    belly_fin = Ellipse(P(-rx * .25, -ry * .9), rx * .2, ry * .25, tilt + deg(25))
    f.fill(belly_fin, fin_c, SW_DETAIL, 'fin_low')
    f.fill(body, g.coat, SW, 'body')
    if g.belly:
        f.patch(Ellipse(P(rx * .1, -ry * .75), rx * 1.0, ry * .5, tilt), g.belly, body, 'belly')
    if g.bands:
        bands = [Ellipse(P(x * rx, 0), rx * .11, ry * 1.2, tilt + deg(8)) for x in (.42, -.05, -.55)]
        f.patch(Union(bands), C.WHITE, body, 'bands')
        f.patch(Union([Ellipse(P(x * rx, 0), rx * .16, ry * 1.25, tilt + deg(8)) for x in (.42, -.05, -.55)]),
                g.bands, body, 'band_edges')
        f.patch(Union(bands), C.WHITE, body, 'bands_in')
    # gill and pectoral fin
    if shark:
        for i in range(3):
            x = rx * (.42 - i * .1)
            f.line([P(x, ry * .2), P(x - rx * .04, -ry * .25)], SW_FINE, name='gill')
        pect = Poly([P(rx * .15, -ry * .45), P(-rx * .25, -ry * 1.35), P(-rx * .05, -ry * .5)], r=.02)
    else:
        f.line([P(rx * .45, ry * .55), P(rx * .36, 0), P(rx * .45, -ry * .55)], SW_FINE, name='gill')
        pa = tilt + deg(-140 if pose != 'scared' else -100)
        pect = Ellipse(P(rx * .18, -ry * .2) + unit(pa) * ry * .3, ry * .38, ry * .18, pa)
    f.fill(pect, fin_c, SW_DETAIL, 'fin')
    # eye and mouth
    eye_c = P(rx * .58, ry * .25) if not shark else P(rx * .72, ry * .2)
    er = ry * (.24 if not shark else .14)
    if pose == 'sleep':
        f.line([eye_c + V(-er, 0), eye_c + V(0, -er * .6), eye_c + V(er, 0)], SW_DETAIL, name='eye_closed')
    elif pose == 'scared':
        f.dot(eye_c, er * 1.3, C.WHITE, 'eye_white', SW_DETAIL)
        f.dot(eye_c + V(er * .2, 0), er * .5, C.INK, 'pupil')
    else:
        f.dot(eye_c, er, C.WHITE, 'eye_white', SW_FINE)
        f.dot(eye_c + V(er * .25, 0), er * .6, C.INK, 'pupil', SW_FINE)
        f.spot(eye_c + V(er * .45, er * .3), er * .2)
    if shark:
        mouth_pts = [P(rx * .95, -ry * .35), P(rx * .7, -ry * .5), P(rx * .45, -ry * .38)]
        if pose == 'roar':
            jaw = Poly([P(rx * 1.0, -ry * .3), P(rx * .45, -ry * .35), P(rx * .6, -ry * .85)], r=.02)
            f.fill(jaw, C.MOUTH, SW_DETAIL, 'mouth')
            teeth = [Poly([P(rx * x - .02, -ry * .32), P(rx * x + .02, -ry * .32), P(rx * x, -ry * .5)], r=.004)
                     for x in (.6, .72, .84)]
            f.fill(Union(teeth), C.WHITE, SW_FINE, 'teeth')
        else:
            f.line(mouth_pts, SW_DETAIL, name='mouth')
    else:
        m = P(rx * .98, -ry * .1)
        if pose in ('roar', 'scared'):
            f.fill(Ellipse(m + V(-.01, 0), ry * .14, ry * .18), C.MOUTH, SW_DETAIL, 'mouth')
        else:
            f.line([m + V(-ry * .1, ry * .08), m, m + V(-ry * .1, -ry * .06)], SW_DETAIL, name='mouth')
    if pose == 'roar' or pose == 'sleep':                  # bubbles
        b0 = P(rx * 1.15, ry * .4)
        for i, r in enumerate((.035, .05)):
            f.dot(b0 + V(.04 * i, .1 + .12 * i), r, '#DFF1FB', 'bubble', SW_FINE)
    f.anchors['head'] = P(rx * .5, 0)
    f.anchors['eye'] = eye_c
    f.anchors['mouth'] = P(rx, -ry * .1)
    f.anchors['ground'] = V(0, 0)
    return f

"""Snail body plan: a soft foot gliding on the ground, a round spiral shell on its back and two eye stalks."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, deg, rot, unit
from .sdf import Circle, Cone, Ellipse, Tube, Union


@dataclass
class Snail:
    body: str = '#E6CFA0'
    shell: str = '#E0904A'
    band: str = '#F2C27A'
    spiral: str = '#7A3E1E'
    cheek: str = '#F2A0A0'
    young: bool = False
    seed: int = 0


POSES = ('stand', 'walk1', 'walk2', 'lie', 'sleep', 'shout', 'look_up', 'scared')


def _spiral(c, r, turns=2.2, start=0.0, n=90):
    """Points of an Archimedean spiral from the shell's centre out to its rim, ending low at the front."""
    pts = []
    total = turns * 2 * math.pi
    for i in range(n + 1):
        t = i / n
        a = start - t * total
        pts.append(c + unit(a) * (r * (.06 + .94 * t)))
    return pts


def build(g: Snail, pose: str) -> Figure:
    f = Figure()
    k = .9 if g.young else 1.0
    hidden = pose == 'scared'
    stretch = {'walk1': .06, 'walk2': -.05, 'lie': .02}.get(pose, 0)
    reach = {'walk1': .04, 'walk2': -.02, 'sleep': -.12, 'lie': .02, 'scared': -.2}.get(pose, 0)
    rise = {'sleep': -.1, 'lie': -.07, 'shout': .03, 'look_up': .02, 'scared': -.14}.get(pose, 0)
    sc = V(-.08, .27) * k if not g.young else V(-.07, .25)
    sr = (.21 if g.young else .22) * k
    head_c = V(.34 + reach, .25 + rise) * k
    hr = (.11 if g.young else .085) * k
    # the foot: a soft tapering slug body along the ground, rising into the neck and head
    tail = V((-.36 if g.young else -.44) - stretch, .022) * k
    foot = Tube([tail, V(-.3 - stretch * .6, .04) * k, V(0, .05) * k, V(.2 + reach * .6, .06) * k],
                [.012 * k, .036 * k, .052 * k, .06 * k])
    neck = Tube([V(.16, .06) * k + V(reach * .5, 0), V(.27 + reach, .11 + rise * .4) * k, head_c],
                [.06 * k, .066 * k, hr * .9])
    body = Union([foot, neck, Circle(head_c, hr)], k=.04)
    # eye stalks: far one first, then the body, then the near one
    up = deg({'look_up': 112, 'shout': 82, 'lie': 48, 'sleep': 60, 'scared': 70}.get(pose, 76))
    length = {'sleep': .07, 'scared': .07, 'lie': .14}.get(pose, .19 if g.young else .21) * k
    stalks = []
    for far, dx, da in ((True, -.04, 14), (False, .02, 0)):
        base = head_c + V(dx, hr * .7)
        bend = deg(-12 if pose in ('stand', 'walk1', 'walk2', 'shout') else 0)
        mid = base + unit(up + deg(da)) * length * .55
        tip = mid + unit(up + deg(da) + bend) * length * .45
        stalks.append((far, Tube([base, mid, tip], [.024 * k, .018 * k, .015 * k]), tip))
    er = (.045 if g.young else .038) * k
    for far, stalk, tip in stalks:
        if far:
            f.fill(Union([stalk, Circle(tip, er)], k=.01), C.shade(g.body, .15), SW_DETAIL, 'stalk_far')
    f.fill(body, g.body, SW, 'body')
    f.patch(Ellipse(V(-.12, .02) * k, .32 * k, .02 * k), C.shade(g.body, .12), body, 'sole')
    # the shell sits on the back
    shell = Circle(sc, sr)
    f.fill(shell, g.shell, SW, 'shell')
    f.patch(Circle(sc + V(-.05, .06) * k, sr * .55), C.light(g.shell, .25), shell, 'shell_light')
    f.line(_spiral(sc + V(.012, -.006) * k, sr * .93, start=deg(-70)), SW_DETAIL, color=g.spiral, name='spiral')
    # front feelers, near stalk, face
    if not hidden:
        nub = head_c + V(hr * .7, hr * .45)
        f.fill(Cone(nub, nub + V(.045, .03) * k, .017 * k, .013 * k), g.body, SW_FINE, 'feeler')
    for far, stalk, tip in stalks:
        if not far:
            f.fill(Union([stalk, Circle(tip, er)], k=.01), g.body, SW_DETAIL, 'stalk')
    eyes = [tip for _, _, tip in stalks]
    for i, tip in enumerate(eyes):
        if pose == 'sleep':
            f.line([tip + V(-er * .7, 0), tip + V(0, -er * .5), tip + V(er * .7, 0)], SW_FINE, name='eye_closed')
        elif pose == 'scared':
            f.dot(tip, er * .95, C.WHITE, 'eye_white', SW_FINE)
            f.dot(tip + V(er * .2, 0), er * .4, C.INK, 'pupil', SW_FINE)
        else:
            f.dot(tip + V(er * .2, 0), er * .55, C.INK, 'eye')
            f.spot(tip + V(er * .38, er * .2), er * .2)
    f.patch(Circle(head_c + V(hr * .3, -hr * .35), hr * .28), g.cheek, Circle(head_c, hr), 'cheek')
    m0 = head_c + V(hr * .35, -hr * .45)
    if pose == 'shout':
        f.fill(Ellipse(m0 + V(.02, 0) * k, .03 * k, .026 * k), C.MOUTH, SW_FINE, 'mouth')
    elif not hidden:
        f.line([m0, m0 + V(.03, -.015) * k, m0 + V(.06, .0) * k], SW_FINE, name='mouth')
    f.anchors['head'] = head_c
    f.anchors['eye'] = eyes[1]
    f.anchors['mouth'] = m0 + V(.04, -.01) * k
    f.anchors['ground'] = V(0, 0)
    return f

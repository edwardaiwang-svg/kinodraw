"""Frog body plan: squat body, bulging eyes, folded jumping legs with toe pads (tree frog colours)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, deg, rot, two_bone, unit
from .sdf import Circle, Cone, Ellipse, Poly, Union


@dataclass
class Frog:
    coat: str = '#5DBB3F'
    belly: str = '#F3F0C8'
    flank: str = '#3A7BD5'
    bars: str = '#F4D03F'
    toes: str = '#F28C28'
    eye_c: str = '#E53935'
    pads: bool = True
    young: bool = False
    seed: int = 0


POSES = ('stand', 'walk1', 'walk2', 'jump', 'sit', 'lie', 'sleep', 'roar', 'look_up', 'scared')


def _toes(foot, direction, n=3, length=.09, spread=22, pad=.024):
    parts, pads = [], []
    for i in range(n):
        a = direction + deg((i - (n - 1) / 2) * spread)
        tip = foot + unit(a) * length
        parts.append(Cone(foot, tip, .016, .014))
        pads.append(Circle(tip, pad))
    return parts, pads


def build(g: Frog, pose: str) -> Figure:
    f = Figure()
    shade = C.shade(g.coat, .25)
    tilt = {'stand': 22, 'walk1': 16, 'walk2': 18, 'jump': -8, 'sit': 40, 'lie': 4, 'sleep': 2, 'roar': 26,
            'look_up': 34, 'scared': 6}[pose]
    lift = {'jump': .32}.get(pose, 0)
    low = pose in ('lie', 'sleep', 'scared')
    t = deg(tilt)
    bc = V(0, (.2 if low else .3) + lift)
    body = Ellipse(bc, .4, .25 if not low else .21, t)
    head_c = bc + rot(V(.3, .1), t) + (V(0, .04) if pose == 'look_up' else V(0, 0))
    head_a = t + deg(15 if pose == 'look_up' else -6)
    head = Ellipse(head_c, .26, .19, head_a)
    eye_c = head_c + rot(V(-.02, .16), head_a)
    bump = Circle(eye_c, .11)
    shape = Union([body, head, bump], k=.08)
    hip = bc + rot(V(-.28, -.02), t)
    sh = bc + rot(V(.2, -.12), t)
    # hind legs: folded (thigh forward along the body, shin back, long foot forward) or stretched (jump)
    legs = {}
    for far in (True, False):
        dx = .05 if far else 0
        if pose == 'jump':
            knee = hip + V(-.18, -.12)
            ankle = knee + V(-.2, -.02)
            foot = ankle + V(-.16, -.06)
            fdir = deg(195)
        else:
            stretch = {'walk1': -.06 if far else .05, 'walk2': .05 if far else -.06}.get(pose, 0)
            knee = hip + V(.16 + dx + stretch, -.04 if not low else .0)
            ankle = V(hip[0] - .04 + dx + stretch, .05)
            foot = V(ankle[0] + .2, .03)
            fdir = deg(0)
            if pose == 'sit':
                knee = hip + V(.18 + dx, .02)
                ankle = V(hip[0] - .02 + dx, .05)
                foot = V(ankle[0] + .2, .03)
        toes, pads = _toes(foot, fdir, 3, .08, 24)
        parts = [Cone(hip + V(dx, 0), knee, .1, .06), Cone(knee, ankle, .06, .04), Cone(ankle, foot, .04, .03)] + toes
        legs['h' + ('f' if far else 'n')] = (Union(parts, k=.02), Union(pads))
    for far in (True, False):
        dx = -.05 if far else 0
        if pose == 'jump':
            hand = sh + V(.2 + dx, -.08)
            hdir = deg(-20)
        elif pose in ('lie', 'sleep', 'scared'):
            hand = V(sh[0] + .16 + dx, .03)
            hdir = deg(0)
        else:
            step = {'walk1': .06 if not far else -.04, 'walk2': -.04 if not far else .06}.get(pose, 0)
            hand = V(sh[0] + .06 + dx + step, .03)
            hdir = deg(10)
        elbow, wrist = two_bone(sh + V(dx, 0), hand + V(0, .02), .14, .14, -1)
        toes, pads = _toes(wrist, hdir, 3, .06, 28, .02)
        legs['f' + ('f' if far else 'n')] = (Union([Cone(sh + V(dx, 0), elbow, .055, .04), Cone(elbow, wrist, .04, .03)]
                                                   + toes, k=.015), Union(pads))
    for k in ('hf', 'ff'):
        f.fill(legs[k][0], shade, SW_DETAIL + 1, 'leg_far')
        if g.pads:
            f.fill(legs[k][1], C.shade(g.toes, .2), SW_FINE, 'pads_far')
    if pose == 'roar':
        sac = Circle(head_c + rot(V(.08, -.2), head_a), .17)
        f.fill(sac, C.mix(g.belly, '#F6B9A8', .45), SW, 'vocal_sac')
    f.fill(shape, g.coat, SW, 'body')
    f.patch(Ellipse(bc + rot(V(.05, -.2), t), .42, .13, t), g.belly, shape, 'belly')
    if g.flank:
        flank = Ellipse(bc + rot(V(-.06, -.07), t), .3, .08, t)
        f.patch(flank, g.flank, shape, 'flank')
        f.patch(Union([Cone(bc + rot(V(x, -.02), t), bc + rot(V(x - .03, -.13), t), .018, .014)
                       for x in (-.24, -.12, 0, .12)]), g.bars, flank, 'bars')
    for k in ('hn', 'fn'):
        f.fill(legs[k][0], g.coat, SW_DETAIL + 1, 'leg_near')
        if g.pads:
            f.fill(legs[k][1], g.toes, SW_FINE, 'pads')
    # eye
    if pose == 'sleep':
        f.dot(eye_c, .085, g.coat, 'lid', SW_DETAIL)
        f.line([eye_c + V(-.07, 0), eye_c + V(0, -.04), eye_c + V(.07, 0)], SW_DETAIL, name='eye_closed')
    elif pose == 'scared':
        f.dot(eye_c, .095, C.WHITE, 'eye', SW_DETAIL)
        f.dot(eye_c + V(.02, 0), .035, C.INK, 'pupil')
    else:
        f.dot(eye_c, .085, g.eye_c, 'eye', SW_DETAIL)
        f.add(type(f.layers[0])('fill', shape=Ellipse(eye_c + V(.01, 0), .025, .06), fill=C.INK, sw=SW_FINE, name='pupil'))
        f.spot(eye_c + V(.035, .035), .02)
    mouth_a = head_c + rot(V(.25, -.04), head_a)
    mouth_b = head_c + rot(V(-.02, -.08), head_a)
    if pose in ('roar', 'scared'):
        f.line([mouth_a, mouth_b + V(.04, -.02)], SW_DETAIL, name='mouth')
    else:
        f.line([mouth_a, (mouth_a + mouth_b) / 2 + rot(V(0, -.03), head_a), mouth_b], SW_DETAIL, name='mouth')
    f.dot(head_c + rot(V(.2, .08), head_a), .012, C.INK, 'nostril', SW_FINE)
    f.anchors['eye'] = eye_c
    f.anchors['head'] = head_c
    f.anchors['ground'] = V(0, 0)
    return f

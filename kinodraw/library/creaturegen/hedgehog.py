"""Hedgehog body plan: a small round bun of short dense spines over a cream face with a pointed snout and a
button nose, tiny round ears and stubby legs. Asleep or scared it curls into a spiky ball."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .genes import stream
from .rig import V, deg, rot, unit
from .sdf import Circle, Cone, Diff, Ellipse, Poly, Union


@dataclass
class Hedgehog:
    spines: str = '#7A5A40'
    spine_line: str = '#4A3426'
    tips: str = '#EAD8B8'
    face: str = '#EBCB9E'
    feet: str = '#B98C66'
    nose: str = '#2A201C'
    cheek: str = '#F0A8A0'
    young: bool = False
    seed: int = 0


POSES = ('stand', 'walk1', 'walk2', 'run', 'lie', 'sleep', 'shout', 'look_up', 'scared')


def _spikes(c, rx, ry, start, end, step, length, sweep, width=.034):
    """Short triangular spines standing out of an ellipse's rim between two angles (deg), swept back."""
    out, tips = [], []
    a = start
    while a <= end + 1e-6:
        t = deg(a)
        p = c + V(rx * math.cos(t), ry * math.sin(t))
        n = V(math.cos(t) / rx, math.sin(t) / ry)
        n = n / math.hypot(*n)
        tip = p + rot(n, deg(sweep)) * length
        side = V(-n[1], n[0]) * width
        out.append(Poly([p + side - n * .02, tip, p - side - n * .02], r=.007))
        tips.append(tip)
        a += step
    return out, tips


def _ball(g, pose):
    """Curled up: a spiky ball with the face tucked in at the front (asleep) or one wide eye peeking (scared)."""
    f = Figure()
    k = .86 if g.young else 1.0
    c, r = V(0, .19 * k), .19 * k
    scared = pose == 'scared'
    spikes, tips = _spikes(c, r, r, -50, 230, 10 if g.young else 9, (.085 if scared else .06) * k, 18, .03 * k)
    # tucked face and front feet peeking under the ball
    snout = Union([Ellipse(c + V(.13, -.1) * k, .12 * k, .08 * k), Cone(c + V(.18, -.11) * k, c + V(.28, -.14) * k,
                                                                        .055 * k, .024 * k)], k=.03)
    f.fill(Union([Ellipse(V(x * k, .025), .045 * k, .025) for x in (.08, -.1)]), g.feet, SW_FINE, 'feet')
    f.fill(snout, g.face, SW_DETAIL, 'face')
    ball = Union([Circle(c, r)] + spikes, k=.012)
    f.fill(ball, g.spines, SW, 'spines')
    f.patch(Union([Circle(t, .022 * k) for t in tips]), g.tips, ball, 'spine_tips')
    _texture(f, g, c, r * .78, r * .72, k)
    nose = c + V(.285, -.14) * k
    f.dot(nose, .022 * k, g.nose, 'nose')
    eye = c + V(.15, -.07) * k
    if scared:
        f.dot(eye, .03 * k, C.WHITE, 'eye_white', SW_FINE)
        f.dot(eye + V(.008, 0), .015 * k, C.INK, 'pupil', SW_FINE)
    else:
        f.line([eye + V(-.025, 0) * k, eye + V(0, -.015) * k, eye + V(.025, 0) * k], SW_FINE, name='eye_closed')
    f.anchors['head'] = c + V(.12, -.08) * k
    f.anchors['eye'] = eye
    f.anchors['mouth'] = nose + V(-.02, -.02)
    f.anchors['ground'] = V(0, 0)
    return f


def _texture(f, g, c, rx, ry, k):
    """Short dark strokes inside the spine coat so it reads as dense spines, not fur."""
    rnd = stream('hedgehog', g.seed)
    for i in range(16):
        u, v = rnd() * 2 - 1, rnd() * 2 - 1
        if u * u + v * v > .8:
            continue
        p = c + V(u * rx, v * ry)
        a = deg(115 + 30 * u)
        f.line([p, p + unit(a) * .05 * k], SW_FINE, color=g.spine_line, name='spine_stroke')


def build(g: Hedgehog, pose: str) -> Figure:
    if pose in ('sleep', 'scared'):
        return _ball(g, pose)
    f = Figure()
    k = .86 if g.young else 1.0
    tilt = deg({'run': -4}.get(pose, 0))
    pivot = V(-.24, .04) * k
    low = .035 * k if pose == 'lie' else 0

    def T(p):
        return pivot + rot(V(p) * k - pivot, tilt) - V(0, low)

    head_a = deg({'look_up': 26, 'shout': 8, 'lie': -6}.get(pose, 0))
    neck = V(.18, .15)

    def H(p):                       # face points turn about the neck with the head
        return T(neck + rot(V(p) - neck, head_a))

    mc, mrx, mry = (V(-.02, .21), .31, .19) if not g.young else (V(-.03, .2), .28, .18)
    face_c = H(V(.26, .16) if not g.young else V(.25, .17))
    face = Union([Ellipse(face_c, (.15 if g.young else .14) * k, (.12 if g.young else .11) * k, tilt + head_a),
                  Cone(H(V(.3, .15)), H(V(.46, .12)), .075 * k, .03 * k)], k=.04)
    # legs: short stubs under the spine skirt, far pair first
    stride = {'walk1': .05, 'walk2': -.05, 'run': .09}.get(pose, 0)
    legs = []
    for far, x, sgn in ((True, .13, -1), (True, -.25, 1), (False, .2, 1), (False, -.18, -1)):
        if pose == 'lie':
            foot = T(V(x + .05, .045))
            legs.append((far, Ellipse(foot, .05 * k, .025 * k)))
            continue
        top = T(V(x, .1))
        foot = V(T(V(x, 0))[0] + stride * sgn * k, 0)
        legs.append((far, Union([Cone(top, foot + V(0, .03 * k), .042 * k, .036 * k),
                                 Ellipse(foot + V(.02 * k, .022 * k), .05 * k, .024 * k)], k=.015)))
    for far, shape in legs:
        if far:
            f.fill(shape, C.shade(g.feet, .2), SW_FINE, 'leg_far')
    f.fill(Ellipse(T(V(.04, .1)), .25 * k, .075 * k, tilt), g.face, SW_DETAIL, 'belly')
    for far, shape in legs:
        if not far:
            f.fill(shape, g.feet, SW_FINE, 'leg')
    f.fill(face, g.face, SW, 'face')
    # the spine coat: a round bun from the forehead over the back, cut along the hairline
    c = T(mc)
    spikes, tips = _spikes(c, mrx * k, mry * k, 32, 205, 10 if g.young else 8.5, (.062 if g.young else .07) * k,
                           22, (.032 if g.young else .034) * k)
    hair = Ellipse(H(V(.31, .09)), .15 * k, .14 * k, tilt + head_a)
    coat = Diff(Union([Ellipse(c, mrx * k, mry * k, tilt)] + [Poly([rot(p - c, tilt) + c for p in s.p], r=.007)
                                                                    for s in spikes], k=.012), hair)
    f.fill(coat, g.spines, SW, 'spines')
    f.patch(Union([Circle(rot(t - c, tilt) + c, .02 * k) for t in tips]), g.tips, coat, 'spine_tips')
    _texture(f, g, c + V(-.03, .03) * k, mrx * .7 * k, mry * .6 * k, k)
    # ear at the hairline, eye, cheek, nose and mouth
    ear = H(V(.2, .26) if not g.young else V(.19, .27))
    f.fill(Circle(ear, (.042 if g.young else .036) * k), g.face, SW_DETAIL, 'ear')
    f.dot(ear + V(.004, -.004), .018 * k, g.cheek, 'ear_in', SW_FINE)
    eye = H(V(.3, .175) if not g.young else V(.295, .185))
    er = (.034 if g.young else .028) * k
    f.dot(eye, er, C.INK, 'eye')
    f.spot(eye + V(er * .35, er * .35), er * .38)
    f.patch(Circle(H(V(.29, .115)), .026 * k), g.cheek, face, 'cheek')
    nose = H(V(.465, .122))
    f.dot(nose, .03 * k, g.nose, 'nose')
    f.spot(nose + V(-.008, .01) * k, .008 * k)
    if pose == 'shout':
        f.fill(Ellipse(H(V(.39, .085)), .035 * k, .028 * k, tilt + head_a), C.MOUTH, SW_FINE, 'mouth')
        mouth = H(V(.4, .08))
    else:
        f.line([H(V(.35, .095)), H(V(.39, .085)), H(V(.425, .095))], SW_FINE, name='mouth')
        mouth = H(V(.4, .09))
    f.anchors['head'] = face_c
    f.anchors['eye'] = eye
    f.anchors['mouth'] = mouth
    f.anchors['ground'] = V(0, 0)
    return f

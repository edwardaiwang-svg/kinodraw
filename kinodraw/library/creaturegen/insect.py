"""Arthropod body plans: ant, bee, beetle (side view, six legs) and butterfly (wings)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, deg, rot, unit
from .sdf import Circle, Cone, Ellipse, Poly, Tube, Union


@dataclass
class Bug:
    kind: str = 'ant'           # ant | bee | beetle | butterfly
    coat: str = '#3C3533'
    accent: str = '#F2C230'
    wing: str = '#DDEFFC'
    spots: str = '#1B1B1B'
    young: bool = False
    seed: int = 0


POSES = {
    'ant': ('stand', 'walk1', 'walk2', 'run', 'carry', 'look_up', 'scared', 'sleep', 'roar'),
    'bee': ('stand', 'walk1', 'walk2', 'fly', 'fly2', 'carry', 'look_up', 'scared', 'sleep'),
    'beetle': ('stand', 'walk1', 'walk2', 'run', 'look_up', 'scared', 'sleep', 'fly'),
    'butterfly': ('stand', 'fly', 'fly2', 'sleep', 'look_up', 'scared'),
}


def _legs(f, anchors, body_y, pose, colour, far, thin=.017):
    """Six legs from three thorax points; walking phases alternate tripods."""
    out = []
    phase = {'walk1': (1, -1, 1), 'walk2': (-1, 1, -1), 'run': (1.6, -1.6, 1.6)}.get(pose, (0, 0, 0))
    spread = (.17, .02, -.15)
    for i, a in enumerate(anchors):
        step = phase[i] * (.05 if not far else -.05)
        foot = V(a[0] + spread[i] * (1.25 if far else 1.4) + step, .015)
        lifted = step > 0 and pose in ('walk1', 'walk2', 'run')
        if lifted:
            foot = foot + V(0, .05)
        knee = V((a[0] + foot[0]) / 2 + spread[i] * .3, body_y + .045 + (.015 if far else 0))
        if pose == 'scared':
            knee = knee + V(0, -.04)
        out.append(Union([Cone(a, knee, thin * 1.15, thin), Cone(knee, foot, thin, thin * .8)], k=.005))
    return Union(out)


def build(g: Bug, pose: str) -> Figure:
    return {'ant': _ant, 'bee': _bee, 'beetle': _beetle, 'butterfly': _butterfly}[g.kind](g, pose)


def _eye(f, c, r, pose, scared_scale=1.4, white=False):
    if pose == 'sleep':
        f.line([c + V(-r, 0), c + V(0, -r * .7), c + V(r, 0)], SW_DETAIL, name='eye_closed')
    elif pose == 'scared':
        f.dot(c, r * scared_scale, C.WHITE, 'eye_white', SW_DETAIL)
        f.dot(c + V(r * .2, 0), r * .55, C.INK, 'pupil')
    elif white:
        f.dot(c, r * 1.15, C.WHITE, 'eye_white', SW_FINE)
        f.dot(c + V(r * .3, 0), r * .6, C.INK, 'pupil', SW_FINE)
    else:
        f.dot(c, r, C.INK, 'eye')
        f.spot(c + V(r * .35, r * .35), r * .38)


def _antenna(f, base, up, pose, colour, length=.22):
    if pose == 'scared':
        pts = [base, base + V(-.06, .1), base + V(-.18, .14)]
    elif pose == 'look_up':
        pts = [base, base + V(.02, .14), base + V(.08, .26)]
    else:
        pts = [base, base + rot(V(.03, .11), up), base + rot(V(.15, .15), up)]
    f.fill(Tube(pts, [.014, .012, .011]), colour, SW_FINE, 'antenna')
    f.fill(Circle(pts[-1], .02), colour, SW_FINE, 'antenna_tip')


def _ant(g, pose):
    f = Figure()
    shade = C.shade(g.coat, .25) if g.coat != '#3C3533' else '#5A504C'
    y = .2 if pose != 'scared' else .15
    if pose == 'sleep':
        y = .1
    tilt = deg(18 if pose == 'look_up' else 0)
    gaster = Ellipse(V(-.29, y + .05), .17, .13, deg(-12))
    petiole = Circle(V(-.11, y + .01), .045)
    thorax = Ellipse(V(.04, y + .02), .14, .075, deg(10))
    head_c = V(.25, y + .07) + rot(V(.0, .0), tilt) + (V(0, .05) if pose == 'look_up' else V(0, 0))
    head = Ellipse(head_c, .12, .105, tilt)
    anchors = [V(.12, y - .02), V(.04, y - .03), V(-.03, y - .02)]
    if pose != 'sleep':
        f.fill(_legs(f, [a + V(-.02, .01) for a in anchors], y, pose, shade, True), shade, SW_FINE, 'legs_far')
    _antenna(f, head_c + V(-.02, .07), tilt, pose, shade)
    body = Union([gaster, petiole, thorax, head], k=.03)
    f.fill(body, g.coat, SW_DETAIL + 1, 'body')
    f.patch(Ellipse(V(-.34, y + .1), .08, .04, deg(-12)), C.light(g.coat, .25), body, 'shine')
    jaw = deg(30 if pose == 'roar' else 8)
    m0 = head_c + rot(V(.08, -.04), tilt)
    for s, a in ((1, jaw), (-1, -jaw * .6)):
        f.fill(Tube([m0, m0 + rot(V(.06, .0), a * s), m0 + rot(V(.08, -.03), a * s)], [.016, .014, .01]), g.coat,
               SW_FINE, 'mandible')
    if pose != 'sleep':
        f.fill(_legs(f, anchors, y, pose, g.coat, False), g.coat, SW_FINE, 'legs')
    else:
        f.fill(Union([Cone(a, V(a[0] + .06 - i * .05, .02), .017, .014) for i, a in enumerate(anchors)]), g.coat, SW_FINE,
               'legs')
    _eye(f, head_c + rot(V(.04, .025), tilt), .032, pose, white=True)
    _antenna(f, head_c + V(.0, .09), tilt, pose, g.coat)
    if pose == 'carry':
        f.anchors['carry'] = m0 + V(.1, .02)
    f.anchors['head'] = head_c
    f.anchors['ground'] = V(0, 0)
    return f


def _bee(g, pose):
    f = Figure()
    flying = pose in ('fly', 'fly2')
    y = .26 if flying else .2
    if pose == 'sleep':
        y = .14
    abd = Ellipse(V(-.2, y), .2, .15, deg(-10))
    thorax = Circle(V(.04, y + .02), .1)
    head_c = V(.2, y + .04) + (V(0, .04) if pose == 'look_up' else V(0, 0))
    head = Circle(head_c, .085)
    wing_up = pose != 'fly2'
    wing_a = deg(115 if wing_up else 165) if flying else deg(150)
    wings = [Ellipse(V(.0, y + .1) + unit(wing_a) * .13, .15, .07, wing_a),
             Ellipse(V(-.04, y + .08) + unit(wing_a + deg(-15)) * .1, .11, .05, wing_a - deg(15))]
    f.fill(wings[1], C.shade(g.wing, .08), SW_FINE, 'wing_far')
    anchors = [V(.08, y - .06), V(.03, y - .07), V(-.03, y - .06)]
    if not flying and pose != 'sleep':
        f.fill(_legs(f, [a + V(-.02, .01) for a in anchors], y - .06, pose, C.INK, True, .014), '#3A3430', SW_FINE,
               'legs_far')
    stinger = Poly([V(-.38, y - .02), V(-.47, y - .06), V(-.37, y - .08)], r=.005)
    body = Union([abd, thorax, head, stinger], k=.03)
    f.fill(body, g.accent, SW_DETAIL + 1, 'body')
    f.patch(Union([Cone(V(x, y + .2), V(x - .02, y - .2), .035, .035) for x in (-.13, -.25, -.36)] +
                  [Circle(V(.04, y + .02), .1)]), '#2E2A27', body, 'stripes')
    _antenna(f, head_c + V(.0, .07), 0, pose, '#2E2A27', .16)
    if flying:
        f.fill(Union([Cone(a, a + V(-.04 + i * .02, -.1), .014, .011) for i, a in enumerate(anchors)]), '#2E2A27',
               SW_FINE, 'legs')
    elif pose != 'sleep':
        f.fill(_legs(f, anchors, y - .06, pose, C.INK, False, .014), '#2E2A27', SW_FINE, 'legs')
    f.fill(wings[0], g.wing, SW_DETAIL, 'wing')
    _eye(f, head_c + V(.03, .015), .026, pose)
    if pose not in ('sleep', 'scared'):
        f.line([head_c + V(.02, -.045), head_c + V(.05, -.055), head_c + V(.075, -.04)], SW_FINE, name='smile')
    if pose == 'carry':
        f.anchors['carry'] = V(.06, y - .12)
    f.anchors['head'] = head_c
    f.anchors['ground'] = V(0, 0)
    return f


def _beetle(g, pose):
    f = Figure()
    flying = pose == 'fly'
    y = .17 if not flying else .3
    if pose == 'sleep':
        y = .12
    head_c = V(.24, y - .02) + (V(0, .05) if pose == 'look_up' else V(0, 0))
    shell = Union([Ellipse(V(-.02, y + .02), .26, .2), Poly([V(-.28, y - .02), V(.24, y - .02), V(.24, y - .1),
                                                             V(-.28, y - .1)])], k=.02)
    anchors = [V(.12, y - .06), V(.0, y - .07), V(-.12, y - .06)]
    if not flying and pose != 'sleep':
        f.fill(_legs(f, [a + V(-.03, .01) for a in anchors], y - .08, pose, C.INK, True, .018), '#3A3430', SW_FINE,
               'legs_far')
    if flying:
        f.fill(Ellipse(V(-.12, y + .2), .16, .07, deg(130)), g.wing, SW_FINE, 'wing')
    f.fill(Circle(head_c, .085), '#2E2A27', SW_DETAIL, 'head')
    _antenna(f, head_c + V(.03, .05), 0, pose, '#2E2A27', .12)
    f.fill(shell, g.coat, SW_DETAIL + 1, 'shell')
    f.patch(Union([Circle(V(x, y + yy), .045) for x, yy in ((-.12, .08), (.04, .12), (-.05, -.02), (.13, .0))]),
            g.spots, shell, 'spots')
    f.line([V(.2, y + .19), V(.17, y - .06)], SW_FINE, name='shell_line')
    if not flying and pose != 'sleep':
        f.fill(_legs(f, anchors, y - .08, pose, C.INK, False, .018), '#2E2A27', SW_FINE, 'legs')
    _eye(f, head_c + V(.035, .01), .022, pose)
    f.anchors['head'] = head_c
    f.anchors['ground'] = V(0, 0)
    return f


def _butterfly(g, pose):
    f = Figure()
    y = .4
    if pose in ('stand', 'sleep', 'look_up'):   # resting, wings closed upright (side view)
        body = Union([Ellipse(V(0, .14), .16, .035, deg(5)), Circle(V(.17, .16), .04)], k=.02)
        wing = Union([Ellipse(V(-.02, .36), .14, .2, deg(-8)), Ellipse(V(-.08, .22), .1, .1)], k=.03)
        f.fill(Union([Cone(V(a, .12), V(a + .03, .02), .01, .008) for a in (.08, .02, -.04)]), '#2E2A27', SW_FINE, 'legs')
        f.fill(wing, g.coat, SW_DETAIL, 'wing')
        f.patch(Union([Circle(V(-.02, .42), .05), Circle(V(-.1, .26), .035)]), g.accent, wing, 'wing_spots')
        f.patch(Ellipse(V(-.02, .52), .12, .06), g.spots, wing, 'wing_edge')
        f.fill(body, '#3A3430', SW_DETAIL, 'body')
        _antenna(f, V(.18, .19), 0, pose, '#3A3430', .12)
        _eye(f, V(.19, .165), .015, 'sleep' if pose == 'sleep' else 'stand')
        f.anchors['ground'] = V(0, 0)
        return f
    # flying: front view with spread wings
    span = 1.0 if pose == 'fly' else .7
    wings = []
    for s in (-1, 1):
        up = Ellipse(V(s * .2 * span, y + .12), .2 * span, .16, s * deg(25))
        lo = Ellipse(V(s * .14 * span, y - .1), .13 * span, .12, -s * deg(20))
        wings.append(Union([up, lo], k=.03))
    for w in wings:
        f.fill(w, g.coat, SW_DETAIL, 'wing')
        f.patch(Union([Circle(V(x, y + .14), .045) for x in (-.24 * span, .24 * span)] +
                      [Circle(V(x, y - .12), .03) for x in (-.15 * span, .15 * span)]), g.accent, w, 'wing_spots')
        f.patch(Union([Ellipse(V(x, y + .22), .1 * span, .05) for x in (-.3 * span, .3 * span)]), g.spots, w, 'wing_tip')
    f.fill(Union([Ellipse(V(0, y), .035, .17), Circle(V(0, y + .19), .045)], k=.02), '#3A3430', SW_DETAIL, 'body')
    for s in (-1, 1):
        f.fill(Tube([V(s * .02, y + .22), V(s * .06, y + .3), V(s * .1, y + .34)], [.01, .009, .008]), '#3A3430',
               SW_FINE, 'antenna')
    for s in (-1, 1):
        c = V(s * .022, y + .2)
        if pose == 'scared':
            f.dot(c, .016, C.WHITE, 'eye', SW_FINE)
        else:
            f.dot(c, .012, C.INK, 'eye', SW_FINE)
    f.anchors['ground'] = V(0, 0)
    return f

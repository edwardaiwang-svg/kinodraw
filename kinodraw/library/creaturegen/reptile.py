"""Reptile body plans (side view): turtle (low shell), tortoise (high domed patterned shell on stumpy legs), snake
(curving tube) and crocodile (long low body)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, deg, rot, unit
from .sdf import Circle, Cone, Diff, Ellipse, Poly, Tube, Union


@dataclass
class Reptile:
    kind: str = 'turtle'        # turtle tortoise snake crocodile
    coat: str = '#8DBB5A'       # skin
    shell: str = '#6D8B3A'
    scute: str = '#9DB85A'
    belly: str = '#E6DFA0'
    mark: str = ''              # snake bands / diamonds
    length: float = 1.0
    young: bool = False
    old: bool = False           # tortoise: heavy lids, a wrinkled neck, a faded shell
    seed: int = 0


POSES = {
    'turtle': ('stand', 'walk1', 'walk2', 'swim1', 'swim2', 'sleep', 'roar', 'look_up', 'scared'),
    'tortoise': ('stand', 'walk1', 'walk2', 'lie', 'sleep', 'shout', 'look_up', 'scared'),
    'snake': ('stand', 'walk1', 'walk2', 'sleep', 'roar', 'look_up', 'scared'),
    'crocodile': ('stand', 'walk1', 'walk2', 'run', 'lie', 'sleep', 'roar', 'look_up', 'swim1', 'swim2'),
}


def _eye(f, c, r, pose, lid=None):
    if pose == 'sleep':
        f.line([c + V(-r, 0), c + V(0, -r * .6), c + V(r, 0)], SW_DETAIL, name='eye_closed')
    elif pose == 'scared':
        f.dot(c, r * 1.35, C.WHITE, 'eye_white', SW_DETAIL)
        f.dot(c + V(r * .25, 0), r * .55, C.INK, 'pupil')
    else:
        f.dot(c, r, C.INK, 'eye')
        f.spot(c + V(r * .35, r * .35), r * .35)
    if pose == 'roar' and lid:
        f.line([c + V(-r * 1.3, r * 1.5), c + V(r * 1.3, r * .8)], SW_DETAIL, name='brow')


# ---------------------------------------------------------------------------------------------- turtle
def _turtle(g, pose):
    f = Figure()
    swim = pose.startswith('swim')
    hide = pose == 'scared'
    y0 = .2 if swim else .08
    shell = Union([Ellipse(V(0, y0 + .02), .42, .3), Ellipse(V(0, y0 - .02), .46, .07)], k=.04)
    cut = Poly([V(-.6, y0 - .1), V(.6, y0 - .1), V(.6, y0 - .5), V(-.6, y0 - .5)])
    from .sdf import Diff
    dome = Diff(shell, cut)
    rim = Ellipse(V(0, y0 - .03), .47, .06)
    # legs (far first)
    legs = []
    for far, x in ((True, .22), (True, -.26), (False, .26), (False, -.22)):
        dx = {'walk1': (.06 if (x > 0) != far else -.05), 'walk2': (-.05 if (x > 0) != far else .06)}.get(pose, 0)
        top = V(x + (-.03 if far else 0), y0 - .02)
        if swim:
            a = deg(200 if x < 0 else -30) + deg(25 if pose == 'swim1' else -15) * (1 if x > 0 else -1)
            foot = top + unit(a) * .22
            legs.append((far, Union([Cone(top, foot, .075, .06), Ellipse(foot, .09, .045, a)], k=.03)))
        elif hide:
            legs.append((far, Ellipse(V(x * 1.05, y0 - .04), .07, .045)))
        else:
            foot = V(x + dx + (-.03 if far else 0), .0)
            legs.append((far, Union([Cone(top, foot + V(0, .06), .085, .075), Ellipse(foot + V(.02, .04), .09, .045)],
                                    k=.03)))
    for far, shape in legs:
        if far:
            f.fill(shape, C.shade(g.coat, .2), SW_DETAIL + 1, 'leg_far')
    # tail
    f.fill(Cone(V(-.4, y0 + .0), V(-.56, y0 - .04), .05, .015), g.coat, SW_DETAIL, 'tail')
    # neck and head
    if hide:
        head_c = V(.42, y0 + .02)
        neck = None
    else:
        reach = {'look_up': V(.12, .3), 'roar': V(.26, .14), 'sleep': V(.22, .02), 'swim1': V(.3, .06),
                 'swim2': V(.3, .06)}.get(pose, V(.24, .12))
        base = V(.32, y0 + .02)
        head_c = base + reach
        neck = Cone(base, head_c, .09, .085)
    head_a = deg({'look_up': 45, 'roar': 10, 'sleep': -10}.get(pose, 0))
    head = Ellipse(head_c, .14, .1, head_a)
    if neck is not None:
        f.fill(Union([neck, head], k=.04), g.coat, SW, 'head')
    else:
        f.fill(head, g.coat, SW, 'head')
    # shell over the neck root
    f.fill(dome, g.shell, SW, 'shell')
    scutes = [Poly([V(x - .09, y0 + .08), V(x, y0 + .2 - abs(x) * .3), V(x + .09, y0 + .08), V(x + .07, y0 + .0),
                    V(x - .07, y0 + .0)], r=.025) for x in (-.21, 0, .21)]
    f.patch(Union(scutes), g.scute, dome, 'scutes')
    f.fill(rim, C.shade(g.shell, .15), SW_DETAIL, 'shell_rim')
    for far, shape in legs:
        if not far:
            f.fill(shape, g.coat, SW_DETAIL + 1, 'leg')
    # face
    fwd, up = unit(head_a), unit(head_a + math.pi / 2)
    eye_c = head_c + fwd * .045 + up * .03
    if hide:
        eye_c = head_c + V(-.0, .0)
        f.dot(eye_c + V(.0, .0), .03, C.WHITE, 'eye_white', SW_FINE)
        f.dot(eye_c + V(.01, 0), .014, C.INK, 'pupil')
    else:
        _eye(f, eye_c, .026, pose)
    if pose == 'roar':
        f.fill(Poly([head_c + fwd * .06 - up * .02, head_c + fwd * .15 - up * .01, head_c + fwd * .12 - up * .07],
                    r=.01), C.MOUTH, SW_FINE, 'mouth')
    elif not hide:
        f.line([head_c + fwd * .14 - up * .02, head_c + fwd * .06 - up * .04], SW_FINE, name='mouth')
    f.anchors['head'] = head_c
    f.anchors['eye'] = eye_c
    f.anchors['ground'] = V(0, 0)
    return f


# ---------------------------------------------------------------------------------------------- tortoise
def _hexagon(c, r, squash=.8):
    return Poly([c + V(r * math.cos(a), r * squash * math.sin(a)) for a in (deg(30 + 60 * i) for i in range(6))],
                r=r * .22)


def _tortoise(g, pose):
    """A land tortoise: a high dome of hexagonal scutes on four elephant-like legs, never flippers."""
    f = Figure()
    k = .9 if g.young else 1.0
    low = pose in ('lie', 'sleep', 'scared')
    y0 = (.05 if low else .13) * k
    rx, ry = (.38 if g.young else .4) * k, (.36 if g.young else .37) * k
    dome = Diff(Ellipse(V(0, y0), rx, ry), Poly([V(-1, y0), V(1, y0), V(1, y0 - 1), V(-1, y0 - 1)]))
    rim = Ellipse(V(0, y0 + .01 * k), rx + .03 * k, .055 * k)
    skin, shade = g.coat, C.shade(g.coat, .22)
    # legs: thick columns with flat feet and toenails (far pair first)
    stride = {'walk1': .06, 'walk2': -.06}.get(pose, 0)
    legs = []
    for far, x, sgn in ((True, .15, -1), (True, -.27, 1), (False, .23, 1), (False, -.19, -1)):
        x *= k
        if low:
            if pose == 'scared':
                legs.append((far, None, Ellipse(V(x * 1.1, y0 - .005), .055 * k, .03 * k)))
            else:
                foot = V(x * 1.1 + .03 * k, .04 * k)
                legs.append((far, foot, Ellipse(foot, .065 * k, .045 * k)))
            continue
        foot = V(x + stride * sgn * k, 0)
        legs.append((far, foot, Union([Cone(V(x, y0 + .03 * k), foot + V(0, .05 * k), .078 * k, .074 * k),
                                    Ellipse(foot + V(.018 * k, .032 * k), .09 * k, .036 * k)], k=.02)))
    for far, _, shape in legs:
        if far:
            f.fill(shape, shade, SW_DETAIL, 'leg_far')
    f.fill(Cone(V(-.36, y0 + .03) * V(k, 1), V(-.46 * k, y0 - .01), .035 * k, .012 * k), skin, SW_DETAIL, 'tail')
    # neck and head
    reach = {'look_up': V(.1, .3), 'shout': V(.2, .17), 'sleep': V(.06, .02), 'lie': V(.17, .02),
             'scared': V(-.04, .02)}.get(pose, V(.17, .12)) * k
    base = V(.3 * k, y0 + .06 * k)
    head_c = base + reach + V(.05 * k, 0)
    head_a = deg({'look_up': 40, 'shout': 12, 'sleep': -8, 'lie': -6}.get(pose, 0))
    hr = (.12 if g.young else .105) * k
    head = Ellipse(head_c, hr, hr * .8, head_a)
    neck = Cone(base, head_c - unit(head_a) * hr * .4, .08 * k, .075 * k)
    f.fill(Union([neck, head], k=.04), skin, SW, 'head')
    fwd, up = unit(head_a), unit(head_a + math.pi / 2)
    if g.old and pose != 'scared':
        for t in (.3, .55):
            p = base + (head_c - base) * t
            f.line([p + up * .05 * k, p + fwd * .015 * k, p - up * .05 * k], SW_FINE, color=shade, name='wrinkle')
    # the shell: dark seams between raised hexagonal scutes, a ridged rim
    f.fill(rim, C.shade(g.shell, .1), SW_DETAIL, 'shell_rim')
    f.fill(dome, g.shell, SW, 'shell')
    top = [(-.17, .2), (0, .27), (.17, .2)] if not g.young else [(-.12, .22), (.12, .22)]
    side = [(-.29, .07), (-.1, .1), (.1, .1), (.29, .07)] if not g.young else [(-.25, .08), (0, .1), (.25, .08)]
    r = (.1 if g.young else .085) * k
    cells = [V(x * k, y0 + y * k) for x, y in top + side]
    f.patch(Union([_hexagon(c, r) for c in cells]), g.scute, dome, 'scutes')
    f.patch(Union([_hexagon(c + V(0, .008 * k), r * .5) for c in cells]), C.light(g.scute, .35), dome, 'scute_rings')
    ticks = []
    for x in (-.32, -.2, -.07, .07, .2, .32):
        ticks.append([V(x * k, y0 + .045 * k), V(x * k * 1.04, y0 - .03 * k)])
    for pts in ticks:
        f.line(pts, SW_FINE, name='rim_seam')
    for far, foot, shape in legs:
        if not far:
            f.fill(shape, skin, SW_DETAIL, 'leg')
            if foot is not None:
                for i in range(3):
                    f.dot(foot + V((.085 - i * .028) * k, .014 * k), .011 * k, '#F2E8D0', 'toenail', SW_FINE)
    # face
    eye_c = head_c + fwd * hr * .35 + up * hr * .25
    er = (.03 if g.young else .024) * k
    if pose == 'sleep':
        f.line([eye_c - fwd * er, eye_c - up * er * .6, eye_c + fwd * er], SW_FINE, name='eye_closed')
    elif pose == 'scared':
        f.dot(eye_c, er * 1.35, C.WHITE, 'eye_white', SW_FINE)
        f.dot(eye_c + fwd * er * .3, er * .6, C.INK, 'pupil', SW_FINE)
    else:
        f.dot(eye_c, er, C.INK, 'eye')
        f.spot(eye_c + V(er * .35, er * .35), er * .38)
        if g.old:
            f.line([eye_c - fwd * er * 1.6 + up * er * .6, eye_c + up * er * 1.3, eye_c + fwd * er * 1.6 + up * er * .5],
                   SW_FINE, name='lid')
    m0 = head_c + fwd * hr * .55 - up * hr * .3
    if pose == 'shout':
        f.fill(Poly([m0 - fwd * .03 * k, head_c + fwd * hr * .98 - up * hr * .2, m0 + fwd * .02 * k - up * .05 * k],
                    r=.01), C.MOUTH, SW_FINE, 'mouth')
    elif pose != 'scared':
        f.line([m0 - fwd * .03 * k, m0 + fwd * .03 * k, head_c + fwd * hr * .95 - up * hr * .15], SW_FINE, name='mouth')
    f.anchors['head'] = head_c
    f.anchors['eye'] = eye_c
    f.anchors['mouth'] = head_c + fwd * hr * .9 - up * hr * .3
    f.anchors['ground'] = V(0, 0)
    return f


# ---------------------------------------------------------------------------------------------- snake
def _snake(g, pose):
    f = Figure()
    r0 = .055
    if pose in ('walk1', 'walk2'):
        ph = 0 if pose == 'walk1' else math.pi
        pts = [V(-.7 + i * .1, r0 + .0) + V(0, 0) for i in range(12)]
        pts = [V(p[0], r0) + V(0, 0) for p in pts]
        body = [V(-.7 + i * .1, r0 + .0) for i in range(12)]
        ground = [V(p[0], r0 + .07 * (1 + math.sin(p[0] * 7 + ph)) * .5) for p in body]
        head_base = ground[-1]
        neck = [head_base, head_base + V(.08, .08), head_base + V(.18, .12)]
        pts = ground + neck[1:]
    else:
        lift = {'look_up': .48, 'roar': .38, 'scared': .26, 'sleep': .0}.get(pose, .34)
        coil = []
        for i in range(16):                    # coil: an ellipse loop on the ground
            t = math.pi * .9 - i * 2 * math.pi / 15 * .95
            coil.append(V(.0 + .32 * math.cos(t), r0 + .08 + .07 * math.sin(t)))
        if pose == 'sleep':
            pts = coil + [coil[-1] + V(.12, -.03), coil[-1] + V(.24, -.05)]
        else:
            start = coil[-1]
            lean = -.08 if pose == 'scared' else (.06 if pose == 'look_up' else 0)
            pts = coil + [start + V(.06, .06), start + V(.06 + lean, lift * .5), start + V(.1 + lean, lift * .85),
                          start + V(.2 + lean, lift)]
    n = len(pts)
    radii = [r0 * (.35 + .65 * min(1, i / 4)) for i in range(n)]
    radii[-1] = r0 * 1.05
    body = Tube(pts, radii)
    tip_dir = pts[-1] - pts[-2]
    a = math.atan2(tip_dir[1], tip_dir[0])
    if pose not in ('walk1', 'walk2', 'sleep'):
        a = deg({'look_up': 35, 'roar': 5, 'scared': -15}.get(pose, -5))
    head_c = pts[-1] + unit(a) * .06
    head = Ellipse(head_c, .11, .075, a)
    shape = Union([body, head], k=.03)
    fwd, up = unit(a), unit(a + math.pi / 2)
    if pose == 'roar':
        f.fill(Union([Cone(head_c + fwd * .1, head_c + fwd * .2 - up * .02, .008, .006),
                      Cone(head_c + fwd * .2 - up * .02, head_c + fwd * .25, .006, .004),
                      Cone(head_c + fwd * .2 - up * .02, head_c + fwd * .24 - up * .05, .006, .004)], k=.004),
               C.MOUTH, SW_FINE, 'tongue')
    f.fill(shape, g.coat, SW, 'body')
    if g.mark:
        bands = []
        for i in range(2, n - 2, 2):
            p, q = pts[i], pts[i + 1]
            d = q - p
            nrm = V(-d[1], d[0]) / (math.hypot(*d) + 1e-9)
            bands.append(Cone(p + nrm * r0 * 1.4, p - nrm * r0 * 1.4, .022, .022))
        f.patch(Union(bands), g.mark, body, 'bands')
    eye_c = head_c + fwd * .03 + up * .025
    _eye(f, eye_c, .024, pose, lid=True)
    if pose == 'roar':
        f.fill(Poly([head_c + fwd * .02 - up * .01, head_c + fwd * .11 - up * .0, head_c + fwd * .1 - up * .06],
                    r=.008), C.MOUTH, SW_FINE, 'mouth')
        f.fill(Cone(head_c + fwd * .08 - up * .005, head_c + fwd * .075 - up * .03, .008, .002), C.WHITE, SW_FINE,
               'fang')
    elif pose != 'sleep':
        f.line([head_c + fwd * .1 - up * .02, head_c + fwd * .02 - up * .025], SW_FINE, name='mouth')
    f.dot(head_c + fwd * .095 + up * .01, .006, C.INK, 'nostril', SW_FINE)
    f.anchors['head'] = head_c
    f.anchors['eye'] = eye_c
    f.anchors['ground'] = V(0, 0)
    return f


# ---------------------------------------------------------------------------------------------- crocodile
def _crocodile(g, pose):
    f = Figure()
    swim = pose.startswith('swim')
    low = pose in ('lie', 'sleep') or swim
    leg_h = 0 if low else (.17 if pose == 'run' else .11)
    y = .13 + leg_h
    body = Ellipse(V(0, y), .42, .145)
    # tail: thick tube sweeping back
    sway = {'walk1': .05, 'walk2': -.05, 'swim1': .08, 'swim2': -.08}.get(pose, 0)
    tail_pts = [V(-.34, y + .01), V(-.56, y - .02 + sway * .5), V(-.76, y - .04 + sway), V(-.94, y - .05)]
    if low and not swim:
        tail_pts = [V(-.34, y), V(-.56, y - .05), V(-.74, y - .07), V(-.9, y - .05 + .04)]
    tail = Tube(tail_pts, [.13, .1, .065, .02])
    # head: long snout, jaws open for the roar
    hb = V(.36, y + .02)
    lift = deg({'look_up': 28, 'roar': 6, 'sleep': -4}.get(pose, 0))
    fwd, up = unit(lift), unit(lift + math.pi / 2)
    open_ = pose == 'roar'
    skull = Ellipse(hb + fwd * .12 + up * .04, .17, .11, lift)
    upper_a = lift + (deg(26) if open_ else 0)
    ufwd, uup = unit(upper_a), unit(upper_a + math.pi / 2)
    upper = Poly([hb + up * .08, hb + ufwd * .5 + uup * .03, hb + ufwd * .54 - uup * .03, hb - up * .0], r=.035)
    lower_a = lift - (deg(14) if open_ else 0)
    lfwd, lup = unit(lower_a), unit(lower_a + math.pi / 2)
    lower = Poly([hb - up * .02, hb + lfwd * .48 - lup * .0, hb + lfwd * .5 - lup * .06, hb - up * .08], r=.03)
    # legs: sprawled, short; far side first
    legs = []
    for far, x in ((True, .24), (True, -.22), (False, .28), (False, -.18)):
        if swim:
            top = V(x, y - .04)
            legs.append((far, Union([Cone(top, top + V(-.12, -.02), .045, .035)], k=.02)))
            continue
        dx = {'walk1': (.07 if (x > 0) != far else -.06), 'walk2': (-.06 if (x > 0) != far else .07),
              'run': (.1 if (x > 0) != far else -.1)}.get(pose, 0)
        top = V(x + (-.04 if far else 0), y - .05)
        if low:
            foot = V(x + .1 + (-.04 if far else 0), .02)
            legs.append((far, Union([Cone(top, foot, .05, .04), Ellipse(foot + V(.04, 0), .07, .028)], k=.02)))
        else:
            knee = V(x + dx * .5 + (-.04 if far else 0) - .02, y - .02 - leg_h * .25)
            foot = V(x + dx + (-.04 if far else 0) + .03, .025)
            legs.append((far, Union([Cone(top, knee, .07, .055), Cone(knee, foot, .055, .045),
                                     Ellipse(foot + V(.04, -.005), .08, .032)], k=.02)))
    shade = C.shade(g.coat, .2)
    for far, shape in legs:
        if far:
            f.fill(shape, shade, SW_DETAIL + 1, 'leg_far')
    if open_:
        f.fill(Poly([hb + up * .02, hb + ufwd * .48, hb + lfwd * .46 - lup * .03, hb - up * .03], r=.02), C.MOUTH,
               SW_DETAIL, 'mouth')
    shape = Union([body, tail, skull, upper, lower], k=.05) if not open_ else Union([body, tail, skull], k=.05)
    if open_:
        f.fill(lower, g.coat, SW, 'jaw_lower')
    f.fill(shape, g.coat, SW, 'body')
    if open_:
        f.fill(Union([upper, skull], k=.04), g.coat, SW, 'jaw_upper')
        teeth = []
        for i in range(4):
            t = .2 + i * .08
            p = hb + ufwd * t - uup * .0
            teeth.append(Poly([p - ufwd * .02, p + ufwd * .02, p - uup * .05], r=.004))
            q = hb + lfwd * (t - .02) - lup * .02
            teeth.append(Poly([q - lfwd * .018, q + lfwd * .018, q + lup * .045], r=.004))
        f.fill(Union(teeth), C.WHITE, SW_FINE, 'teeth')
    f.patch(Union([Ellipse(V(-.02, y - .09), .4, .05), Tube([V(-.36, y - .07), V(-.6, y - .1 + sway * .5),
                                                               V(-.8, y - .11 + sway)], [.035, .025, .015])]),
            g.belly, shape, 'belly')
    # back ridges
    bumps = [Circle(V(x, y + .135 - abs(x) * .08), .035) for x in (-.26, -.14, -.02, .1, .22)]
    bumps += [Circle(p + V(0, r), .026) for p, r in ((tail_pts[1], .09), ((tail_pts[1] + tail_pts[2]) / 2, .075),
                                                      (tail_pts[2], .055))]
    f.fill(Union(bumps, k=.01), C.shade(g.coat, .12), SW_FINE, 'ridges')
    if not open_:
        f.line([hb + fwd * .06 - up * .015, hb + fwd * .3 - up * .01, hb + fwd * .5], SW_FINE, name='mouth')
        for i in range(4):
            p = hb + fwd * (.16 + i * .09) - up * .012
            f.fill(Poly([p - fwd * .014, p + fwd * .014, p - up * .035], r=.003), C.WHITE, SW_FINE, 'tooth')
    for far, shape_ in legs:
        if not far:
            f.fill(shape_, g.coat, SW_DETAIL + 1, 'leg')
    eye_c = hb + fwd * .1 + up * .13
    f.fill(Circle(eye_c, .055), g.coat, SW_DETAIL, 'eye_bump')
    _eye(f, eye_c + V(.005, .005), .028, pose, lid=True)
    f.dot(hb + ufwd * .5 + uup * .035, .01, C.INK, 'nostril', SW_FINE)
    f.anchors['head'] = hb + fwd * .2
    f.anchors['eye'] = eye_c
    f.anchors['ground'] = V(0, 0)
    return f


def build(g: Reptile, pose: str) -> Figure:
    return {'turtle': _turtle, 'tortoise': _tortoise, 'snake': _snake, 'crocodile': _crocodile}[g.kind](g, pose)

"""Primate body plan (gorilla, chimpanzee, monkey): knuckle-walking or upright skeleton, long arms."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import Frame, V, chain, deg, rot, two_bone, unit
from .sdf import Circle, Cone, Ellipse, Poly, Tube, Union


@dataclass
class Ape:
    L: float = .5               # hip -> shoulder
    chest_r: float = .3
    hip_r: float = .2
    head_r: float = .2
    muzzle: float = .55         # muzzle length (head radii)
    crest: float = 0.0          # gorilla sagittal crest
    arm: float = .74            # upper + fore arm
    arm_r: float = .1
    leg: float = .5             # thigh + shin
    leg_r: float = .1
    hand_r: float = .075
    foot: float = .16
    tail_len: float = 0.0
    tail_r: float = .03
    eye_r: float = .12
    ear_r: float = .22
    coat: str = '#55575C'
    face_c: str = '#3E3F44'
    under: str = '#6B6E74'
    hand_c: str = '#3E3F44'
    back_c: str = ''
    young: bool = False
    seed: int = 0


POSES = ('stand', 'walk1', 'walk2', 'run', 'sit', 'lie', 'sleep', 'roar', 'look_up', 'scared', 'carry')


def build(a: Ape, pose: str) -> Figure:
    f = Figure()
    shade = C.shade(a.coat, .22)
    upright = pose in ('roar', 'carry')
    ground_leg = a.leg * .95
    # ---------------------------------------------------------------- skeleton
    if pose == 'sit' or pose == 'look_up' or (pose == 'sleep'):
        hip = V(0, a.hip_r * .9)
        tilt = deg(98 if pose != 'sleep' else 80)
        sh = hip + unit(tilt) * a.L
    elif pose == 'lie':
        hip = V(-a.L / 2, a.hip_r * .85)
        sh = V(a.L / 2, a.chest_r * .9)
    elif upright:
        hip = V(0, ground_leg * .93)
        sh = hip + unit(deg(84)) * a.L
    else:
        drop = .18 if pose == 'scared' else 0
        sh_h = (a.arm * .93 + a.chest_r * .1) * (1 - drop)
        hip_h = ground_leg * .9 * (1 - drop * 1.3)
        dx = math.sqrt(max(.01, a.L ** 2 - (sh_h - hip_h) ** 2))
        hip = V(-dx / 2, hip_h)
        sh = V(dx / 2, sh_h)
    ang = math.atan2(sh[1] - hip[1], sh[0] - hip[0])
    torso = Union([Ellipse(hip + rot(V(.02, 0), ang), a.hip_r * 1.15, a.hip_r, ang),
                   Ellipse(sh + rot(V(-.04, .02), ang), a.chest_r * 1.05, a.chest_r * 1.0, ang),
                   Cone(hip, sh, a.hip_r, a.chest_r * .9)], k=.08)
    # head position: forward of the shoulders, low for apes on all fours
    if upright or pose in ('sit', 'look_up'):
        hc = sh + rot(V(.02, a.chest_r * .55 + a.head_r * .55), 0) + V(a.head_r * .35, 0)
        pitch = deg(40 if pose == 'look_up' else 8 if pose == 'roar' else 0)
    elif pose == 'sleep':
        hc = sh + V(a.head_r * .9, -a.head_r * .2)
        pitch = deg(-35)
    elif pose == 'lie':
        hc = V(sh[0] + a.chest_r + a.head_r * .5, a.head_r * 1.05)
        pitch = 0
    else:
        hc = sh + rot(V(a.chest_r * .75 + a.head_r * .35, a.chest_r * .25), ang * .3)
        pitch = deg(-8 if pose == 'scared' else 0)
    H = Frame(hc, pitch, a.head_r)
    # ---------------------------------------------------------------- limbs
    limbs = {}
    up_a, lo_a = a.arm * .5, a.arm * .5
    th, sn = a.leg * .52, a.leg * .48
    sh_j = sh + rot(V(.04, -.02), ang)
    hip_j = hip + rot(V(.02, -.02), ang)

    def arm(target, far=False, bend=-1):
        root = sh_j + V(-.05 if far else 0, 0)
        elbow, wrist = two_bone(root, target, up_a, lo_a, bend)
        hand = Ellipse(wrist + V(.01, -.01), a.hand_r * 1.2, a.hand_r * .95)
        return Union([Circle(root + V(.01, .02), a.arm_r * 1.45), Cone(root, elbow, a.arm_r * 1.25, a.arm_r * .9),
                      Cone(elbow, wrist, a.arm_r * .9, a.arm_r * .85), hand], k=.04), wrist

    def leg(target, far=False, bend=1):
        root = hip_j + V(.04 if far else 0, 0)
        knee, ankle = two_bone(root, target, th, sn, bend)
        foot = Ellipse(ankle + V(a.foot * .35, -.02), a.foot * .62, a.leg_r * .62)
        return Union([Cone(root, knee, a.leg_r * 1.15, a.leg_r * .9), Cone(knee, ankle, a.leg_r * .9, a.leg_r * .75),
                      foot], k=.03), ankle

    fy = a.leg_r * .6
    hy = a.hand_r * .95
    if upright:
        if pose == 'roar':
            limbs['fa'] = arm(sh_j + V(-.02, a.arm * .88), True, 1)
            limbs['na'] = arm(sh_j + V(-a.chest_r * .2, a.arm * .85), False, -1)
        else:  # carry: both hands in front holding something
            limbs['fa'] = arm(sh_j + V(a.chest_r + .14, -a.arm * .35), True, -1)
            limbs['na'] = arm(sh_j + V(a.chest_r + .16, -a.arm * .38), False, -1)
            f.anchors['carry'] = sh_j + V(a.chest_r + .2, -a.arm * .3)
        limbs['fl'] = leg(V(hip[0] + .08, fy), True)
        limbs['nl'] = leg(V(hip[0] - .04, fy))
    elif pose in ('sit', 'look_up'):
        knee_pt = hip + V(a.leg * .5, a.leg * .32)
        limbs['fl'] = leg(V(hip[0] + a.leg * .62, fy), True, 1)
        limbs['nl'] = leg(V(hip[0] + a.leg * .55, fy), False, 1)
        limbs['fa'] = arm(V(hip[0] + a.leg * .75, hy), True, -1)
        limbs['na'] = arm(knee_pt + V(.06, -.02), False, -1)
    elif pose == 'sleep':
        limbs['fl'] = leg(V(hip[0] + a.leg * .6, fy), True, 1)
        limbs['nl'] = leg(V(hip[0] + a.leg * .55, fy), False, 1)
        limbs['fa'] = arm(hc + V(.0, -a.head_r * .7), True, -1)
        limbs['na'] = arm(hc + V(-.02, -a.head_r * .9), False, -1)
    elif pose == 'lie':
        limbs['fl'] = leg(V(hip[0] - a.leg * .7, fy), True, -1)
        limbs['nl'] = leg(V(hip[0] - a.leg * .75, fy), False, -1)
        limbs['fa'] = arm(V(sh[0] + a.arm * .55, hy), True, 1)
        limbs['na'] = arm(V(sh[0] + a.arm * .6, hy), False, 1)
    else:
        off = {'stand': (0, 0, 0, 0), 'walk1': (.14, -.1, -.1, .12), 'walk2': (-.1, .14, .12, -.1),
               'run': (.28, .14, -.24, -.12), 'scared': (.06, -.02, .0, .06)}[pose]
        lift = {'walk1': (0, .06, 0, 0), 'walk2': (.06, 0, 0, 0), 'run': (.12, .02, .1, 0)}.get(pose, (0, 0, 0, 0))
        limbs['fa'] = arm(V(sh[0] + .06 + off[1], hy + lift[1]), True, -1)
        limbs['na'] = arm(V(sh[0] + .1 + off[0], hy + lift[0]), False, -1)
        limbs['fl'] = leg(V(hip[0] + .06 + off[3], fy + lift[3]), True, 1)
        limbs['nl'] = leg(V(hip[0] - .02 + off[2], fy + lift[2]), False, 1)
    # ---------------------------------------------------------------- draw
    for k in ('fl', 'fa'):
        f.fill(limbs[k][0], shade, SW, 'limb_' + k)
    if a.tail_len:
        base = hip + rot(V(-a.hip_r * .9, -a.hip_r * .2), ang)
        a0, curl = (128, 30) if pose not in ('run', 'lie') else (165, -12)
        if pose in ('sit', 'look_up', 'sleep'):
            a0, curl = 205, -24
        pts = chain(base, deg(a0), a.tail_len / 8, 8, deg(curl))
        pts = [V(p[0], max(p[1], a.tail_r * 1.2)) for p in pts]
        f.fill(Tube(pts, [a.tail_r * (1.2 - .4 * i / 8) for i in range(9)]), a.coat, SW_DETAIL + 1, 'tail')
    f.fill(torso, a.coat, SW, 'torso')
    f.patch(Ellipse(sh + rot(V(.06, -a.chest_r * .25), ang), a.chest_r * .7, a.chest_r * .6, ang), a.under, torso,
            'chest')
    if a.back_c:
        f.patch(Ellipse((hip + sh) / 2 + rot(V(-.05, a.chest_r * .75), ang), a.L * .55, a.chest_r * .45, ang),
                a.back_c, torso, 'silver_back')
    f.fill(limbs['nl'][0], a.coat, SW, 'limb_nl')
    f.patch(Ellipse(limbs['nl'][1] + V(a.foot * .35, -.02), a.foot * .5, a.leg_r * .45), a.hand_c, limbs['nl'][0], 'sole')
    # head (a raised arm goes behind it so the open mouth stays visible)
    if pose != 'roar':
        head(f, a, H, pose)
    f.fill(limbs['na'][0], a.coat, SW, 'limb_na')
    f.patch(Ellipse(limbs['na'][1] + V(.01, -.01), a.hand_r * 1.05, a.hand_r * .8), a.hand_c, limbs['na'][0], 'hand')
    if pose == 'roar':
        head(f, a, H, pose)
    f.anchors['ground'] = V(0, 0)
    return f


def head(f, a, H, pose):
    jaw = 1.0 if pose == 'roar' else 0.0
    skull = Ellipse(H(-.05, .05), H.r(1.0), H.r(.92), H.a)
    parts = [skull]
    if a.crest:
        parts.append(Cone(H(-.2, .3), H(-.45, .95 + a.crest * .2), H.r(.55), H.r(.3)))
    m0 = V(.45, -.35)
    muzzle = Ellipse(H(*(m0 + V(a.muzzle * .4, 0))), H.r(.38 + a.muzzle * .45), H.r(.42), H.a - deg(10))
    jaw_c = V(.4, -.62) + rot(V(.3, 0), -deg(30) * jaw)
    lower = Ellipse(H(*jaw_c), H.r(.42), H.r(.25), H.a - deg(30) * jaw)
    parts += [muzzle, lower]
    if jaw:
        f.fill(Poly([H(.25, -.45), H(*(m0 + V(a.muzzle * .8 + .2, -.3))), H(*(jaw_c + V(.35, -.05)))], r=H.r(.06)),
               C.MOUTH, SW_DETAIL, 'mouth')
    ear = Circle(H(-.45, .05), H.r(a.ear_r))
    head_shape = Union(parts, k=H.r(.2))
    f.fill(Union([head_shape, ear], k=H.r(.05)), a.coat, SW, 'head')
    face = Union([Circle(H(.35, .2), H.r(.42)), Ellipse(H(*(m0 + V(a.muzzle * .4, -.05))), H.r(.36 + a.muzzle * .45),
                                                         H.r(.45), H.a - deg(10)),
                  Ellipse(H(*jaw_c), H.r(.4), H.r(.24), H.a - deg(30) * jaw)], k=H.r(.15))
    f.patch(face, a.face_c, head_shape, 'face')
    f.patch(Circle(H(-.45, .05), H.r(a.ear_r * .5)), a.face_c, ear, 'ear_in')
    # brow, eye, nostril, mouth
    f.line([H(.12, .48), H(.42, .55), H(.7, .42)], SW_DETAIL, name='brow')
    eye = V(.42, .25)
    er = a.eye_r * (1.2 if a.young else 1)
    if pose == 'sleep':
        f.line([H(*(eye + V(-er, 0))), H(*(eye + V(0, -er * .6))), H(*(eye + V(er, 0)))], SW_DETAIL, name='eye')
    elif pose == 'scared':
        f.dot(H(*eye), H.r(er * 1.45), C.WHITE, 'eye_white')
        f.dot(H(*(eye + V(.04, 0))), H.r(er * .6), C.INK, 'pupil')
    else:
        f.dot(H(*eye), H.r(er), C.INK, 'eye')
        f.spot(H(*(eye + V(.04, .05))), H.r(er * .35))
        if pose == 'roar':
            f.line([H(*(eye + V(-.18, .2))), H(*(eye + V(.18, .1)))], SW_DETAIL, name='brow_angry')
    tip = m0 + V(a.muzzle * .8 + .3, .02)
    f.dot(H(*(tip + V(-.08, .08))), H.r(.06), C.INK, 'nostril')
    if not jaw:
        f.line([H(*(tip + V(-.02, -.2))), H(*(tip + V(-.3, -.26)))], SW_FINE, name='mouth_line')
    else:
        f.fill(Poly([H(*(m0 + V(a.muzzle * .8, -.32))), H(*(m0 + V(a.muzzle * .8 + .14, -.33))),
                     H(*(m0 + V(a.muzzle * .8 + .06, -.52)))], r=H.r(.02)), C.WHITE, SW_FINE, 'fang')
    f.anchors['eye'] = H(*eye)
    f.anchors['head'] = H(0, 0)
    f.anchors['mouth'] = H(*tip)

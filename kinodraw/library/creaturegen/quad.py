"""Quadruped body plan: genes -> skeleton (pose) -> layered outlined doodle.

Skeleton: hip and shoulder joints carry the torso masses (rump, barrel, chest as one smooth group);
a neck chain carries the head; legs are two-bone IK chains to paw targets with a fixed distal segment
for toe-walkers and hoofed animals; the tail is a curling chain. Poses only move the skeleton and
face, so every pose keeps the species' anatomy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import Frame, V, ang, chain, deg, rot, two_bone, unit
from .sdf import Circle, Cone, Ellipse, Inter, Poly, Tube, Union


@dataclass
class Quad:
    # proportions (world units; a standing adult's shoulder joint ~0.75)
    L: float = 1.0
    hip_h: float = 0.70
    sh_h: float = 0.74
    chest_r: float = 0.33
    hip_r: float = 0.28
    belly: float = 0.03
    back: float = 0.0           # >0 hump over the shoulders
    neck_len: float = 0.30
    neck_r: float = 0.16
    neck_ang: float = 45.0
    head_r: float = 0.23
    head_ry: float = 0.9        # cranium height / length
    snout: float = 0.6          # snout length (head radii)
    snout_r: float = 0.46
    snout_drop: float = 0.28
    jaw_r: float = 0.28
    head_pitch: float = 0.0     # rest pitch (deg); grazers look down
    ears: str = 'round'         # round | pointed | floppy | long | small | none
    ear_size: float = 0.42
    ear_ang: float = 100.0      # where on the skull the ear sits (deg from forward)
    eye_r: float = 0.13
    eye_at: tuple = (0.42, 0.2)
    leg_r: float = 0.11
    thigh_r: float = 0.19
    knee_r: float = 0.085
    foot_r: float = 0.065
    paw_r: float = 0.08
    stance: str = 'digi'        # digi | hoof | plant
    meta: float = 0.26          # distal segment / hip height
    tail_len: float = 0.75
    tail_r: float = 0.045
    tail_tip: str = 'tuft'      # tuft | plain | fluffy | bob | none
    tail_seg: int = 7
    tail_rest: float = 235.0    # deg, world direction at the base when standing
    tail_curl: float = -9.0     # deg per segment
    whiskers: bool = False
    nose: str = 'cat'           # cat | dog | pad | hoof | pig | none
    # colours
    coat: str = '#E0A54B'
    under: str = '#F6DDB0'
    muzzle: str = ''
    tip: str = '#6B4226'
    nose_c: str = C.NOSE
    ear_in: str = '#C98B6B'
    # features
    mane: float = 0.0
    mane_c: str = '#8A4F21'
    mane_kind: str = 'lion'     # lion | ridge (horse/zebra)
    pattern: str = 'none'       # none | stripes | spots | rosettes | patches | zebra | giraffe | saddle
    mark_c: str = '#2A2A2A'
    scar: bool = False
    horns: str = 'none'         # none | cow | goat | ram | antlers | ossicones | antelope
    horn_c: str = '#EFE3C8'
    trunk: float = 0.0
    tusks: float = 0.0
    big_ears: float = 0.0       # elephant ears
    hooves_c: str = '#4A3A30'
    socks: str = ''
    cub: bool = False
    fluffy: float = 0.0         # sheep wool
    quills: float = 0.0         # porcupine / hedgehog spines
    quill_c: str = '#4E3B2C'
    chin_tuft: float = 0.0      # goat beard
    blaze: str = ''             # face blaze colour
    leg_c: str = ''             # legs in another colour (fox socks, panda)
    tail_tip_c: str = ''        # light tail tip (fox)
    tail_c: str = ''            # tail colour when not the coat (horse hair)
    tail_hang: bool = False     # tail keeps hanging in standing poses (horse, cow, zebra)
    ear_c: str = ''             # ears in another colour (panda)
    eye_patch: str = ''         # dark patch around the eye (panda)
    seed: int = 0


@dataclass
class Pose:
    name: str = 'stand'
    mode: str = 'stand'         # stand | sit | lie
    pitch: float = 0.0          # torso pitch (deg, + front up)
    drop_f: float = 0.0         # crouch: fraction of shoulder height lowered
    drop_h: float = 0.0
    neck: float = 0.0           # extra neck carriage (deg)
    head: float = 0.0           # extra head pitch (deg)
    jaw: float = 0.0            # 0 closed .. 1 roar
    feet: dict = field(default_factory=dict)   # leg -> (dx, lift)
    tail: tuple = None          # (base deg, curl deg/segment)
    eyes: str = 'open'          # open | closed | wide | angry | happy | sad
    ears_back: bool = False
    tongue: bool = False
    carry: bool = False
    stretch: float = 0.0        # run: longer stride, flatter body


LEGS = ('nf', 'ff', 'nh', 'fh')    # near front, far front, near hind, far hind

POSES = {
    'stand': Pose('stand'),
    'walk1': Pose('walk1', feet={'nf': (.17, 0), 'fh': (.13, .07), 'ff': (-.13, 0), 'nh': (-.15, 0)},
                  tail=(222, -11)),
    'walk2': Pose('walk2', feet={'nf': (-.11, .07), 'fh': (-.15, 0), 'ff': (.16, 0), 'nh': (.13, 0)},
                  tail=(226, -9)),
    'run': Pose('run', pitch=-2, drop_f=.08, drop_h=.04, head=-6, neck=-16, stretch=.1,
                feet={'nf': (.42, .1), 'ff': (.3, .03), 'nh': (-.44, .09), 'fh': (-.3, .02)},
                tail=(172, -4), ears_back=True),
    'sit': Pose('sit', mode='sit', tail=(200, 16)),
    'lie': Pose('lie', mode='lie', tail=(195, 14)),
    'sleep': Pose('sleep', mode='lie', head=-34, neck=-48, eyes='closed', tail=(195, 16)),
    'roar': Pose('roar', head=12, neck=-6, jaw=1.0, eyes='angry', ears_back=True, tail=(205, -14),
                 feet={'nf': (.1, 0), 'ff': (-.04, 0)}),
    'look_up': Pose('look_up', neck=32, head=55, tail=(228, -10)),
    'scared': Pose('scared', drop_f=.22, drop_h=.34, pitch=0, head=-10, neck=-26, eyes='wide', ears_back=True,
                   tail=(292, 12), feet={'nf': (.12, 0), 'ff': (.02, 0), 'nh': (-.04, 0), 'fh': (.06, 0)}),
    'carry': Pose('carry', head=4, neck=4, jaw=.22, carry=True, tail=(224, -10)),
}


def _legs_base(q: Quad, hip, sh):
    return {'nf': V(sh[0] + .04, 0), 'ff': V(sh[0] - .14, 0), 'nh': V(hip[0] - .04, 0), 'fh': V(hip[0] + .12, 0)}


class Builder:
    """Builds one posed figure of a quadruped gene set."""

    def __init__(self, q: Quad, pose: Pose):
        self.q, self.p = q, pose
        self.fig = Figure()
        self.shade = C.shade(q.coat, .22)
        self.muzzle = q.muzzle or q.under

    # -------------------------------------------------------------- skeleton
    def skeleton(self):
        q, p = self.q, self.p
        L = q.L * (1 + p.stretch)
        if p.mode == 'stand':
            hip = V(-L / 2, q.hip_h * (1 - p.drop_h))
            sh = V(L / 2, q.sh_h * (1 - p.drop_f))
            a = math.atan2(sh[1] - hip[1], sh[0] - hip[0]) + deg(p.pitch)
            sh = hip + unit(a) * L
        elif p.mode == 'sit':
            hip = V(-L * .22, q.hip_r * .95)
            reach = (q.sh_h - q.paw_r) * .98
            s = max(-.2, min(.95, (reach + q.paw_r * .8 - hip[1]) / L))
            a = math.asin(s)
            sh = hip + unit(a) * L
        else:  # lie
            hip = V(-L / 2, q.hip_r * .92)
            sh = V(L / 2, q.chest_r * .95)
            a = math.atan2(sh[1] - hip[1], sh[0] - hip[0])
        self.hip, self.sh, self.a, self.Ln = hip, sh, a, L

    # -------------------------------------------------------------- torso
    def torso(self):
        q, a = self.q, self.a
        hip, sh, L = self.hip, self.sh, self.Ln
        mid = (hip + sh) / 2
        parts = [
            Ellipse(hip + rot(V(-.04, .05), a), q.hip_r * 1.18, q.hip_r, a),
            Ellipse(sh + rot(V(.05, .03), a), q.chest_r * 1.1, q.chest_r, a),
            Ellipse(mid + rot(V(0, -q.belly), a), L * .5, (q.hip_r + q.chest_r) * .47, a),
        ]
        if q.back > 0:
            parts.append(Ellipse(sh + rot(V(-.05, q.chest_r * .55), a), q.chest_r * .9, q.chest_r * (.35 + q.back), a))
        self.torso_shape = Union(parts, k=.12)
        n0 = sh + rot(V(q.chest_r * .45, q.chest_r * .45), a)
        na = a + deg(q.neck_ang + self.p.neck)
        if self.p.mode == 'sit':
            na = deg(q.neck_ang + 30 + self.p.neck)
        elif self.p.mode == 'lie':
            na = deg(q.neck_ang + 8 + self.p.neck)
            if q.neck_len > .5 and self.p.eyes == 'closed':
                na = deg(q.neck_ang - 4)
        n1 = n0 + unit(na) * q.neck_len
        self.neck0, self.neck1, self.neck_a = n0, n1, na
        self.neck_shape = Cone(n0, n1, q.neck_r, q.neck_r * .9)
        self.body = Union([self.torso_shape, self.neck_shape], k=.1)

    # -------------------------------------------------------------- head
    def head_frame(self):
        q, p = self.q, self.p
        pitch = deg(q.head_pitch + p.head) + (self.a * .35 if p.mode == 'stand' else 0)
        centre = self.neck1 + unit(self.neck_a) * q.head_r * .35 + unit(pitch) * q.head_r * .25
        if p.mode == 'lie' and p.eyes == 'closed' and q.neck_len <= .5:
            centre = V(self.sh[0] + q.chest_r * 1.1 + q.head_r * .6, q.head_r * .95)
            pitch = deg(-8)
        self.H = Frame(centre, pitch, q.head_r)

    def head_parts(self):
        q, p, H = self.q, self.p, self.H
        R = 1.0
        S, sr = q.snout, q.snout_r
        tip = V(.32 + S, -q.snout_drop)
        skull = Ellipse(H(0, 0), H.r(1.0), H.r(q.head_ry), H.a)
        upper = Cone(H(.25, -q.snout_drop * .5), H(*tip), H.r(sr), H.r(sr * .82))
        hinge = V(-.05, -.42)
        ja = -deg(48) * p.jaw
        jaw_tip = hinge + rot(V(tip[0] - .05 - hinge[0], -q.snout_drop - sr * .55 - hinge[1]), ja)
        jaw_mid = hinge + rot(V(.25, -.22), ja * .6)
        jaw = Cone(H(*jaw_mid), H(*jaw_tip), H.r(q.jaw_r * 1.1), H.r(q.jaw_r * .7))
        self.tip, self.jaw_tip, self.hinge = tip, jaw_tip, hinge
        self.snout_shape = Union([upper, jaw], k=H.r(.12))
        shapes = [skull, upper, jaw]
        if q.chin_tuft:
            shapes.append(Cone(H(*(jaw_tip + V(-.2, -.1))), H(*(jaw_tip + V(-.3, -.1 - q.chin_tuft))), H.r(.12), H.r(.05)))
        self.head_shape = Union(shapes, k=H.r(.28))
        return R

    def ear_shape(self, far=False):
        q, p, H = self.q, self.p, self.H
        e = q.ear_size
        base_a = deg(q.ear_ang + (8 if far else 0))
        base = V(math.cos(base_a) * .78, math.sin(base_a) * q.head_ry * .82) + V(-.12 if far else 0, 0)
        back = deg(35) if p.ears_back else 0
        if q.ears == 'round':
            c = base + rot(V(0, e * .7), back)
            return Circle(H(*c), H.r(e * .62)), c
        if q.ears in ('pointed', 'small'):
            up = rot(V(-.12, 1), back * 1.4)
            tipp = base + up * e * (1.6 if q.ears == 'pointed' else 1.0)
            w = e * .55
            side = rot(V(1, .1), back)
            pts = [base - side * w, tipp, base + side * w * .9]
            return Poly([H(*pt) for pt in pts], r=H.r(.07)), (base + tipp) / 2
        if q.ears == 'floppy':
            a0 = base + V(.05, .0)
            pts = [a0, a0 + V(-.45 * e, -.1), a0 + V(-.5 * e, -1.1 * e), a0 + V(-.05, -.95 * e)]
            return Union([Cone(H(*pts[0]), H(*pts[2]), H.r(.28 * e), H.r(.32 * e)),
                          Cone(H(*pts[0]), H(*pts[3]), H.r(.26 * e), H.r(.3 * e))], k=H.r(.1)), (pts[0] + pts[2]) / 2
        if q.ears == 'long':
            up = rot(V(-.25, 1), back * 1.6 + deg(8))
            tipp = base + up * e * 2.6
            return Cone(H(*base), H(*tipp), H.r(e * .3), H.r(e * .36)), (base + tipp) / 2
        return None, None

    def head(self, layer_far_ear=True):
        """Far ear, mouth interior, head group, muzzle patch, near-ear inner, face details."""
        q, p, H, f = self.q, self.p, self.H, self.fig
        self.head_parts()
        if q.ears != 'none' and layer_far_ear and not q.big_ears:
            far, _ = self.ear_shape(far=True)
            if far is not None:
                f.fill(far, self.shade, SW_DETAIL, 'ear_far')
        if p.jaw > .05:
            hinge = self.hinge
            mouth = Poly([H(*(hinge + V(.05, .02))), H(*(self.tip + V(.05, -.1))),
                          H(*(self.jaw_tip + V(.05, .05)))], r=H.r(.08))
            f.fill(mouth, C.MOUTH, SW_DETAIL, 'mouth')
            if p.jaw > .5:
                f.patch(Ellipse(H(*(self.jaw_tip * .55 + hinge * .45 + V(.05, .12))), H.r(.32), H.r(.14),
                                H.a + ang(self.jaw_tip - hinge)), C.TONGUE, mouth, 'tongue')
        shapes = [self.head_shape]
        ear, ear_c = (None, None)
        if q.ears != 'none' and not q.big_ears:
            ear, ear_c = self.ear_shape()
            if ear is not None:
                shapes.append(ear)
        if q.ear_c and ear is not None:
            shapes = shapes[:-1]
            f.fill(ear, q.ear_c, SW, 'ear')
        head = Union(shapes, k=H.r(.06))
        self.head_full = head
        f.fill(head, q.coat, SW, 'head')
        if q.eye_patch:
            ex, ey = q.eye_at
            f.patch(Ellipse(H(ex - .02, ey - .02), H.r(.3), H.r(.22), H.a + deg(-25)), q.eye_patch, head, 'eye_patch')
        if q.ears in ('round', 'pointed', 'long') and ear is not None and not q.big_ears and not q.ear_c:
            inner = {'round': Circle(H(*ear_c), H.r(q.ear_size * .3)),
                     'pointed': Circle(H(*ear_c), H.r(q.ear_size * .22)),
                     'long': Cone(H(*(ear_c - (ear_c - self._ear_base()) * .5)), H(*(ear_c + (ear_c - self._ear_base()) * .7)),
                                  H.r(q.ear_size * .14), H.r(q.ear_size * .18))}[q.ears]
            f.patch(inner, q.ear_in, ear, 'ear_in')
        if self.muzzle != q.coat:
            f.patch(Union([Ellipse(H(*(self.tip + V(-.25, -.12))), H.r(q.snout * .62 + .1), H.r(q.snout_r * 1.05), H.a),
                           Circle(H(*(self.jaw_tip * .6 + self.hinge * .4)), H.r(q.jaw_r * 1.25))], k=H.r(.2)),
                    self.muzzle, head, 'muzzle')
        if q.blaze:
            f.patch(Cone(H(.1, .75), H(*(self.tip + V(-.1, .1))), H.r(.16), H.r(.22)), q.blaze, head, 'blaze')
        if q.pattern in ('stripes', 'zebra'):
            self.head_stripes(head)
        if q.pattern in ('spots', 'rosettes', 'giraffe'):
            for (x, y, r) in ((-.35, .35, .12), (-.1, .62, .1), (-.55, -.05, .11)):
                f.patch(Circle(H(x, y), H.r(r)), q.mark_c, head, 'head_spot')
        self.face()

    def _ear_base(self):
        q = self.q
        base_a = deg(q.ear_ang)
        return V(math.cos(base_a) * .78, math.sin(base_a) * q.head_ry * .82)

    def head_stripes(self, head):
        q, H, f = self.q, self.H, self.fig
        strokes = []
        for x, top in ((-.5, .8), (-.2, .95), (.12, .9)):
            strokes.append(Cone(H(x, top + .2), H(x + .1, top - .35), H.r(.09), H.r(.03)))
        strokes.append(Cone(H(-.95, .05), H(-.45, .1), H.r(.08), H.r(.02)))
        strokes.append(Cone(H(-.95, -.3), H(-.5, -.2), H.r(.08), H.r(.02)))
        f.patch(Union(strokes), q.mark_c, head, 'head_stripes')

    def face(self):
        q, p, H, f = self.q, self.p, self.H, self.fig
        ex, ey = q.eye_at
        e = V(ex, ey)
        er = q.eye_r
        if q.cub:
            er *= 1.25
        if p.eyes == 'closed':
            f.line([H(ex - er * 1.1, ey + er * .1), H(ex, ey - er * .55), H(ex + er * 1.1, ey + er * .1)], SW_DETAIL,
                   name='eye')
        elif p.eyes == 'wide':
            f.dot(H(*e), H.r(er * 1.45), C.WHITE, 'eye_white')
            f.dot(H(*(e + V(.05, 0))), H.r(er * .62), C.INK, 'pupil')
            f.spot(H(*(e + V(.08, .05))), H.r(er * .22))
        elif p.eyes == 'happy':
            f.line([H(ex - er * 1.1, ey - er * .2), H(ex, ey + er * .7), H(ex + er * 1.1, ey - er * .2)], SW_DETAIL,
                   name='eye')
        else:
            f.dot(H(*e), H.r(er), C.INK, 'eye')
            f.spot(H(*(e + V(.04, .05))), H.r(er * .35))
            if p.eyes == 'angry':
                f.line([H(ex - er * 1.6, ey + er * 2.0), H(ex + er * 1.5, ey + er * .9)], SW_DETAIL, name='brow')
            elif p.eyes == 'sad':
                f.line([H(ex - er * 1.5, ey + er * 1.0), H(ex + er * 1.4, ey + er * 2.0)], SW_DETAIL, name='brow')
        tip = self.tip
        sr = q.snout_r
        if q.nose in ('cat', 'dog', 'pad'):
            nr = {'cat': .19, 'dog': .22, 'pad': .2}[q.nose]
            n = tip + V(sr * .62, sr * .4)
            f.fill(Ellipse(H(*n), H.r(nr), H.r(nr * .72), H.a + deg(-15)), q.nose_c, SW_FINE, 'nose')
        elif q.nose == 'pig':
            n = tip + V(sr * .75, 0)
            f.fill(Ellipse(H(*n), H.r(.14), H.r(sr * .8), H.a), C.mix(q.coat, '#C0505A', .35), SW_DETAIL, 'snout_disc')
            f.dot(H(*(n + V(0, .14))), H.r(.04), C.INK, 'nostril')
            f.dot(H(*(n + V(0, -.14))), H.r(.04), C.INK, 'nostril')
        elif q.nose == 'hoof':
            n = tip + V(sr * .45, sr * .2)
            f.dot(H(*n), H.r(.07), C.INK, 'nostril')
        if p.jaw <= .05 and q.nose in ('cat', 'dog', 'pad'):
            m0 = tip + V(sr * .55, sr * .1)
            f.line([H(*m0), H(*(m0 + V(-.05, -.25))), H(*(m0 + V(-.4, -.32)))], SW_FINE, name='mouth_line')
        if p.jaw > .5 and q.nose in ('cat', 'dog', 'pad'):
            for base, sgn in ((tip + V(sr * .2, -sr * .75), -1), (self.jaw_tip + V(.02, q.jaw_r * .55), 1)):
                fang = Poly([H(*(base + V(-.1, 0))), H(*(base + V(.08, 0))), H(*(base + V(-.02, .2 * sgn)))], r=H.r(.02))
                f.fill(fang, C.WHITE, SW_FINE, 'fang')
        if q.whiskers and p.jaw <= .05:
            w0 = tip + V(.05, -.05)
            for dy in (.0, -.12):
                f.line([H(*(w0 + V(0, dy))), H(*(w0 + V(.45, dy + .05)))], SW_FINE, name='whisker')
        if q.scar:
            s0, s1 = V(ex + .32, ey + .32), tip + V(-.12, sr * .05)
            f.line([H(*s0), H(*s1)], SW_DETAIL + .5, '#A8473A', 'scar')
            mid = (s0 + s1) / 2
            dirn = (s1 - s0) / math.hypot(*(s1 - s0))
            nrm = V(-dirn[1], dirn[0])
            for t in (-.35, 0, .35):
                c = s0 + (s1 - s0) * (.5 + t * .9)
                f.line([H(*(c - nrm * .14)), H(*(c + nrm * .14))], SW_FINE, name='scar_stitch')
            _ = mid
        self.fig.anchors['eye'] = H(*e)
        mouth_pt = (tip + self.jaw_tip) / 2 + V(.15, -.1)
        self.fig.anchors['mouth'] = H(*mouth_pt)
        self.fig.anchors['head'] = H(0, 0)

    # -------------------------------------------------------------- legs
    def leg_shapes(self, leg):
        q, p = self.q, self.p
        front = leg[1] == 'f'
        hip, sh, a = self.hip, self.sh, self.a
        if p.mode == 'sit' and not front:
            return self.sit_hind(leg)
        if p.mode == 'lie':
            return self.lie_leg(leg)
        root = sh + rot(V(.02, -.06), a) if front else hip + rot(V(.02, -.05), a)
        base = _legs_base(q, hip, sh)[leg]
        if p.mode == 'sit':
            base = V(sh[0] + (.04 if leg == 'nf' else -.06), 0)
        dx, lift = p.feet.get(leg, (0, 0))
        paw = V(base[0] + dx, q.paw_r * .75 + lift)
        top_r = q.leg_r * (1.15 if front else 1.0)
        if q.stance == 'plant':
            l1 = l2 = ((q.sh_h if front else q.hip_h) - .06 - q.paw_r * 1.05) * .505
            joint, end = two_bone(root, paw + V(0, q.paw_r * .3), l1, l2, -1 if front else 1)
            parts = [Cone(root, joint, top_r * (1.0 if front else q.thigh_r / q.leg_r), q.knee_r),
                     Cone(joint, end, q.knee_r, q.foot_r),
                     Ellipse(paw + V(.02, 0), q.paw_r * 1.15, q.paw_r * .75)]
            return Union(parts, k=.03), paw
        meta_len = (q.sh_h if front else q.hip_h) * (q.meta * (.45 if front and q.stance == 'digi' else .9 if front else 1))
        meta_dir = unit(deg(96 if front else 106))
        if lift > 0:
            meta_dir = unit(deg(70 if front else 128))
        ankle = paw + meta_dir * meta_len
        h_total = (q.sh_h if front else q.hip_h) - q.paw_r * .75 - meta_len * .99
        l1, l2 = h_total * (.55 if front else .52) * 1.03, h_total * (.45 if front else .48) * 1.03
        if not front:
            l1, l2 = l1 * 1.06, l2 * 1.06
        joint, end = two_bone(root, ankle, l1, l2, -1 if front else 1)
        if front:
            parts = [Cone(root, joint, top_r, q.knee_r * 1.05), Cone(joint, end, q.knee_r, q.foot_r)]
        else:
            parts = [Cone(root, joint, q.thigh_r, q.knee_r), Cone(joint, end, q.knee_r * .95, q.foot_r)]
        parts.append(Cone(end, paw, q.foot_r, q.foot_r * .95))
        if q.stance == 'hoof':
            parts.append(Ellipse(paw + V(.0, -.005), q.foot_r * 1.15, q.paw_r * .7))
        else:
            parts.append(Ellipse(paw + V(.03, -.01), q.paw_r * 1.3, q.paw_r * .72))
        return Union(parts, k=.025), paw

    def sit_hind(self, leg):
        q, hip = self.q, self.hip
        far = leg == 'fh'
        haunch_c = hip + V(.08 + (.05 if far else 0), -.02)
        paw = V(hip[0] + q.hip_r * 1.35 + (.08 if far else 0), q.paw_r * .75)
        parts = [Ellipse(haunch_c, q.hip_r * .88, q.hip_r * .82, deg(20)),
                 Cone(haunch_c + V(-.05, -q.hip_r * .55), paw, q.foot_r * 1.2, q.foot_r),
                 Ellipse(paw + V(.02, 0), q.paw_r * 1.3, q.paw_r * .72)]
        return Union(parts, k=.04), paw

    def lie_leg(self, leg):
        q, hip, sh = self.q, self.hip, self.sh
        front = leg[1] == 'f'
        far = leg[0] == 'f'
        if front:
            root = sh + V(.04, -.04)
            paw = V(sh[0] + q.chest_r + q.sh_h * .42 + (-.06 if far else 0), q.paw_r * .75)
            elbow = V(sh[0] + q.chest_r * .3 + (-.04 if far else 0), q.foot_r * 1.1)
            parts = [Cone(root, elbow, q.leg_r * 1.1, q.knee_r), Cone(elbow, paw, q.knee_r, q.foot_r),
                     Ellipse(paw + V(.03, -.01), q.paw_r * 1.3, q.paw_r * .72)]
            return Union(parts, k=.03), paw
        haunch_c = hip + V(.12 + (.06 if far else 0), .0)
        paw = V(hip[0] + q.hip_r * 1.5 + (.1 if far else 0), q.paw_r * .75)
        parts = [Ellipse(haunch_c, q.hip_r * .95, q.hip_r * .85, deg(15)),
                 Cone(haunch_c + V(-.08, -q.hip_r * .5), paw, q.foot_r * 1.25, q.foot_r),
                 Ellipse(paw + V(.02, 0), q.paw_r * 1.3, q.paw_r * .72)]
        return Union(parts, k=.04), paw

    # -------------------------------------------------------------- tail
    def tail(self):
        q, p = self.q, self.p
        if q.tail_tip == 'none' or q.tail_len <= 0:
            return None, None
        base = self.hip + rot(V(-q.hip_r * 1.05, q.hip_r * .4), self.a)
        a0, curl = p.tail if p.tail else (q.tail_rest, q.tail_curl)
        if q.tail_hang and p.mode == 'stand':
            a0, curl = q.tail_rest + {'run': -45, 'scared': 14, 'roar': -12}.get(p.name, 0), q.tail_curl
        if q.tail_tip == 'bob':
            a0, curl = 150, -10
        n = q.tail_seg
        seg = q.tail_len / n
        pts = chain(base, deg(a0), seg, n, deg(curl))
        if p.mode in ('sit', 'lie'):
            pts = [V(pt[0], max(pt[1], q.tail_r * 1.1)) for pt in pts]
        radii = [q.tail_r * (1.25 - .45 * i / n) for i in range(n + 1)]
        if q.tail_tip == 'fluffy':
            radii = [q.tail_r * (1.0 + 1.2 * math.sin(math.pi * min(1, (i + 1) / (n + 1)))) for i in range(n + 1)]
        elif q.tail_tip == 'flow':
            radii = [q.tail_r * (.75 + .9 * (i / n) ** .8) for i in range(n + 1)]
        return Tube(pts, radii), pts

    # -------------------------------------------------------------- patterns
    def body_marks(self, clip, where='body'):
        q, f = self.q, self.fig
        hip, sh, a = self.hip, self.sh, self.a
        if q.pattern == 'stripes' or q.pattern == 'zebra':
            n = 7 if q.pattern == 'stripes' else 9
            strokes = []
            for i in range(n):
                t = (i + .5) / n
                c = hip + (sh - hip) * (t * 1.2 - .1)
                top = c + rot(V(.03, q.chest_r * 1.1), a)
                bot = c + rot(V(-.06, -q.chest_r * (.35 if q.pattern == 'stripes' else .85)), a)
                w = .045 if q.pattern == 'stripes' else .05
                strokes.append(Cone(top, bot, w, w * .35))
            if q.pattern == 'zebra':
                d = self.neck1 - self.neck0
                across = unit(self.neck_a + math.pi / 2)
                for i in range(4):
                    c = self.neck0 + d * (.15 + .22 * i)
                    strokes.append(Cone(c + across * q.neck_r * 1.1 - d * .04, c - across * q.neck_r * .6, .045, .016))
            f.patch(Union(strokes), q.mark_c, clip, where + '_stripes')
        elif q.pattern == 'saddle':
            f.patch(Ellipse((hip + sh) / 2 + rot(V(-.06, q.chest_r * .7), a), self.Ln * .42, q.chest_r * .5, a),
                    q.mark_c, clip, where + '_saddle')
        elif q.pattern in ('spots', 'rosettes', 'giraffe', 'patches', 'dalmatian'):
            rnd = _rng(q.seed + 7)
            spots = []
            count = {'spots': 16, 'rosettes': 13, 'giraffe': 11, 'patches': 4, 'dalmatian': 14}[q.pattern]
            size = {'spots': .045, 'rosettes': .06, 'giraffe': .1, 'patches': .2, 'dalmatian': .04}[q.pattern]
            for i in range(count):
                t = (i + rnd()) / count
                c = hip + (sh - hip) * (t * 1.25 - .12) + rot(V(0, (rnd() - .45) * q.chest_r * 1.4), a)
                r = size * (.7 + .6 * rnd())
                if q.pattern == 'giraffe':
                    spots.append(Poly([c + rot(V(r, 0), k * 1.2566 + rnd() * .3) for k in range(5)], r=.015))
                else:
                    spots.append(Circle(c, r))
            f.patch(Union(spots), q.mark_c, clip, where + '_spots')

    # -------------------------------------------------------------- assemble
    def build(self) -> Figure:
        q, p, f = self.q, self.p, self.fig
        self.skeleton()
        self.torso()
        self.head_frame()
        legs = {leg: self.leg_shapes(leg) for leg in LEGS}
        tail, tail_pts = self.tail()
        # far side
        leg_c = q.leg_c or q.coat
        for leg in ('ff', 'fh'):
            f.fill(legs[leg][0], C.shade(leg_c, .22), SW, 'leg_' + leg)
        if tail is not None:
            f.fill(tail, q.tail_c or q.coat, SW_DETAIL + 1, 'tail')
            if q.tail_tip_c:
                end, prev = tail_pts[-1], tail_pts[-3]
                f.patch(Circle(end, q.tail_r * 2.2 + .02), q.tail_tip_c, tail, 'tail_tip')
            if q.tail_tip == 'tuft':
                end, prev = tail_pts[-1], tail_pts[-2]
                d = end - prev
                tuft = Ellipse(end + d * .9, q.tail_r * 2.3, q.tail_r * 1.6, ang(d))
                f.fill(tuft, q.tip, SW_DETAIL, 'tail_tuft')
        if q.mane and q.mane_kind in ('ridge', 'horse'):
            self.head_frame()
            self.ridge_mane()
        body = self.body
        if q.fluffy:
            body = self.wool(body)
        f.fill(body, q.coat if not q.fluffy else q.under, SW, 'body')
        if q.under != q.coat and not q.fluffy:
            belly = Ellipse((self.hip + self.sh) / 2 + rot(V(.05, -(q.hip_r + q.chest_r) * .52), self.a),
                            self.Ln * .62, (q.hip_r + q.chest_r) * .26, self.a)
            chest = Ellipse(self.sh + rot(V(q.chest_r * .75, -q.chest_r * .1), self.a), q.chest_r * .45,
                            q.chest_r * .75, self.a + deg(20))
            f.patch(Union([belly, chest], k=.08), q.under, body, 'belly')
        if not q.fluffy:
            self.body_marks(body)
        if q.quills:
            self.spines()
        if q.pattern == 'band':
            f.patch(Ellipse(self.sh + rot(V(-.02, .02), self.a), q.chest_r * .75, q.chest_r * 1.3, self.a), q.mark_c,
                    body, 'band')
        for leg in ('nh', 'nf'):
            shape = legs[leg][0]
            f.fill(shape, leg_c, SW, 'leg_' + leg)
            if q.pattern in ('stripes', 'zebra'):
                self.leg_stripes(shape, legs[leg][1], leg)
            if q.socks:
                f.patch(Ellipse(legs[leg][1] + V(0, .06), .12, .1), q.socks, shape, 'sock')
        if q.mane and q.mane_kind == 'lion':
            self.lion_mane()
        if q.big_ears:
            self.elephant_far_ear()
        self.head()
        if q.mane and q.mane_kind == 'horse':
            self.forelock()
        if q.horns != 'none':
            self.horns()
        if q.trunk:
            self.elephant_trunk()
        if q.big_ears:
            self.elephant_ear()
        if p.carry and 'carry' not in f.anchors:
            f.anchors['carry'] = self.fig.anchors['mouth']
        # where a parent's mouth holds this animal (the loose skin behind the head)
        along, across = unit(self.neck_a), unit(self.neck_a + math.pi / 2)
        f.anchors['scruff'] = self.neck1 - along * q.neck_len * .3 + across * q.neck_r * .9
        f.anchors['ground'] = V(0, 0)
        return f

    def leg_stripes(self, shape, paw, leg):
        q = self.q
        strokes = []
        base = paw + V(0, q.sh_h * (.12 if q.pattern == 'zebra' else .2))
        for k in range(5 if q.pattern == 'zebra' else 3):
            c = base + V(0, k * q.sh_h * (.12 if q.pattern == 'zebra' else .14))
            strokes.append(Cone(c + V(-.12, .02), c + V(.04, -.01), .03, .012))
        self.fig.patch(Union(strokes), q.mark_c, shape, 'leg_stripes')

    # -------------------------------------------------------------- family features
    def lion_mane(self):
        q, H = self.q, self.H
        R = 1.0
        rnd = _rng(q.seed + 3)
        size = q.mane
        centre = V(-.35, -.15)
        parts = [Ellipse(H(*centre), H.r(1.35 * size), H.r(1.5 * size), H.a + deg(10))]
        n = 13
        for i in range(n):
            t = i / n * 2 * math.pi
            r = 1.35 * size
            c = centre + V(math.cos(t) * r * .95, math.sin(t) * r * 1.05)
            parts.append(Circle(H(*c), H.r(.42 * size * (.85 + .3 * rnd()))))
        neck_down = self.neck0 + rot(V(-.02, -.05), self.a)
        parts.append(Cone(H(*centre), neck_down, H.r(1.15 * size), q.chest_r * .85))
        self.mane_shape = Union(parts, k=H.r(.12))
        self.fig.fill(self.mane_shape, q.mane_c, SW, 'mane')
        _ = R

    def ridge_mane(self):
        """Crest along the top of the neck, drawn behind the neck so only its spiky edge shows."""
        q, f, H = self.q, self.fig, self.H
        n0 = self.neck0
        top0 = n0 + rot(V(-q.chest_r * .35, q.neck_r * .55), self.neck_a)
        top1 = H(-.55, .62)
        d = top1 - top0
        nrm = V(-d[1], d[0]) / math.hypot(*d)
        if nrm[1] < 0:
            nrm = -nrm
        parts = [Tube([top0, top1], [q.neck_r * .45, q.neck_r * .4])]
        n = 7
        for i in range(n):
            t = (i + .5) / n
            c = top0 + d * t
            parts.append(Poly([c - d * .07, c + nrm * q.neck_r * (.75 if q.mane_kind == 'ridge' else .95) - d * .1,
                               c + d * .07], r=.012))
        self.ridge = Union(parts, k=.02)
        f.fill(self.ridge, q.mane_c, SW_DETAIL, 'mane_ridge')

    def forelock(self):
        q, H = self.q, self.H
        self.fig.fill(Cone(H(-.15, .85), H(.3, .62), H.r(.2), H.r(.08)), q.mane_c, SW_DETAIL, 'forelock')

    def horns(self):
        q, H, f = self.q, self.H, self.fig
        kind = q.horns
        if kind == 'cow':
            for far in (True, False):
                b = V(-.15 + (-.12 if far else 0), .78)
                pts = [b, b + V(.12, .4), b + V(.42, .55)]
                f.fill(Tube([H(*pt) for pt in pts], [H.r(.16), H.r(.11), H.r(.05)]),
                       C.shade(q.horn_c, .15) if far else q.horn_c, SW_DETAIL, 'horn')
        elif kind in ('goat', 'antelope'):
            b = V(-.05, .82)
            length = 1.1 if kind == 'goat' else 1.8
            pts = [b + rot(V(0, 1), deg(28 + 18 * t)) * length * t for t in (0, .35, .7, 1.0)]
            f.fill(Tube([H(*pt) for pt in pts], [H.r(.14), H.r(.11), H.r(.07), H.r(.03)]), q.horn_c, SW_DETAIL, 'horn')
        elif kind == 'ram':
            c = V(-.2, .35)
            pts = [c + rot(V(.05, .55), deg(i * 50)) * (1 - i * .08) for i in range(7)]
            f.fill(Tube([H(*pt) for pt in pts], [H.r(.22 - i * .02) for i in range(7)]), q.horn_c, SW_DETAIL, 'horn')
        elif kind == 'antlers':
            for far in (True, False):
                b = V(-.1 - (.18 if far else 0), .82)
                main = [b, b + V(-.25, .8), b + V(-.15, 1.6), b + V(.25, 2.25)]
                tines = [Tube([H(*main[1]), H(*(main[1] + V(.55, .45)))], [H.r(.09), H.r(.06)]),
                         Tube([H(*main[2]), H(*(main[2] + V(.6, .35)))], [H.r(.08), H.r(.05)]),
                         Tube([H(*main[2]), H(*(main[2] + V(-.5, .45)))], [H.r(.07), H.r(.05)]),
                         Tube([H(*(main[0] + V(0, .25))), H(*(main[0] + V(.4, .5)))], [H.r(.08), H.r(.05)])]
                f.fill(Union([Tube([H(*pt) for pt in main], [H.r(.12), H.r(.1), H.r(.08), H.r(.05)])] + tines,
                             k=H.r(.05)), C.shade(q.horn_c, .15) if far else q.horn_c, SW_DETAIL, 'antlers')
        elif kind == 'ossicones':
            for far in (True, False):
                b = V(-.2 + (-.15 if far else 0), .8)
                f.fill(Union([Cone(H(*b), H(*(b + V(-.05, .45))), H.r(.09), H.r(.08)),
                              Circle(H(*(b + V(-.05, .5))), H.r(.13))]),
                       C.shade(q.coat, .1) if far else q.coat, SW_DETAIL, 'ossicone')
                f.patch(Circle(H(*(b + V(-.05, .52))), H.r(.12)), q.mark_c,
                        Circle(H(*(b + V(-.05, .5))), H.r(.13)), 'ossicone_tip')

    def elephant_trunk(self):
        q, H, f = self.q, self.H, self.fig
        p = self.p
        base = V(.55, -.25)
        if p.name == 'roar':
            pts = chain(base, deg(40), .32, 6, deg(12))
        elif p.carry:
            pts = chain(base, deg(-60), .3, 6, deg(18))
        elif p.mode == 'lie' and p.eyes == 'closed':
            pts = chain(base, deg(-80), .28, 5, deg(14))
        else:
            pts = chain(base, deg(-84), .4 * q.trunk, 6, deg(3), .9)
        n = len(pts)
        tube = Tube([H(*pt) for pt in pts], [H.r(.36 - .2 * i / (n - 1)) for i in range(n)])
        f.fill(Union([tube, Circle(H(.35, -.1), H.r(.5))], k=H.r(.2)), q.coat, SW, 'trunk')
        for i in range(1, n - 1, 1):
            a = pts[i]
            d = pts[i + 1] - pts[i - 1]
            nrm = V(-d[1], d[0]) / math.hypot(*d)
            w = .36 - .2 * i / (n - 1)
            f.line([H(*(a + nrm * w * .55)), H(*(a + nrm * w * .1))], SW_FINE, name='trunk_ring')
        if q.tusks:
            t0 = V(.45, -.55)
            f.fill(Tube([H(*t0), H(*(t0 + V(.35, -.15))), H(*(t0 + V(.6, .05)))], [H.r(.1), H.r(.08), H.r(.035)]),
                   '#FFF8E8', SW_DETAIL, 'tusk')
        if p.carry:
            f.anchors['carry'] = H(*pts[-1])
        # the face goes back on top of the trunk root
        ex, ey = q.eye_at
        if p.eyes == 'closed':
            f.line([H(ex - .12, ey), H(ex, ey - .07), H(ex + .12, ey)], SW_DETAIL, name='eye')
        elif p.eyes == 'wide':
            f.dot(H(ex, ey), H.r(.15), C.WHITE, 'eye_white')
            f.dot(H(ex + .03, ey), H.r(.07), C.INK, 'pupil')
        else:
            f.dot(H(ex, ey), H.r(.09), C.INK, 'eye')
            f.spot(H(ex + .03, ey + .03), H.r(.03))
            if p.eyes == 'angry':
                f.line([H(ex - .18, ey + .22), H(ex + .16, ey + .1)], SW_DETAIL, name='brow')

    def elephant_far_ear(self):
        q, H, f = self.q, self.H, self.fig
        self.head_frame()
        c = V(-.45, .25)
        f.fill(Ellipse(H(*(c + V(.25, .25))), H.r(.75 * q.big_ears), H.r(.95 * q.big_ears), H.a), self.shade, SW_DETAIL,
               'ear_far')

    def elephant_ear(self):
        q, H, f = self.q, self.H, self.fig
        flap = deg(-25) if self.p.ears_back else 0
        c = V(-.35, .05)
        shape = Union([Ellipse(H(*(c + rot(V(-.25, -.05), flap))), H.r(.78 * q.big_ears), H.r(1.0 * q.big_ears),
                               H.a + flap + deg(8)),
                       Cone(H(*(c + V(-.2, -.5))), H(*(c + rot(V(-.1, -1.15), flap) * q.big_ears)), H.r(.35), H.r(.12))],
                      k=H.r(.2))
        f.fill(shape, q.coat, SW, 'ear')
        f.patch(Ellipse(H(*(c + rot(V(-.3, -.05), flap))), H.r(.5 * q.big_ears), H.r(.72 * q.big_ears), H.a + flap),
                q.ear_in, shape, 'ear_in')

    def wool(self, body):
        q = self.q
        rnd = _rng(q.seed + 11)
        hip, sh, a = self.hip, self.sh, self.a
        puffs = [body]
        for i in range(16):
            t = i / 16 * 2 * math.pi
            c = (hip + sh) / 2 + rot(V(math.cos(t) * self.Ln * .62, math.sin(t) * (q.chest_r + .05)), a)
            if c[1] < .25 and self.p.mode == 'stand':
                continue
            puffs.append(Circle(c, .1 + .03 * rnd()))
        return Union(puffs, k=.03)

    def spines(self):
        q, f = self.q, self.fig
        hip, sh, a = self.hip, self.sh, self.a
        rnd = _rng(q.seed + 13)
        quills = []
        n = 15
        for i in range(n):
            t = i / (n - 1)
            c = hip + (sh - hip) * (t * 1.15 - .1) + rot(V(0, q.chest_r * .55), a)
            direction = a + deg(165 - 80 * t + rnd() * 16)
            length = q.quills * (.75 + .5 * rnd()) * (1.0 if .1 < t < .9 else .7)
            tipp = c + unit(direction) * (length + q.chest_r * .6)
            quills.append(Poly([c + unit(direction + deg(90)) * .05, tipp, c - unit(direction + deg(90)) * .05], r=.008))
        coat = Union([Ellipse((hip + sh) / 2 + rot(V(-.02, q.chest_r * .25), a), self.Ln * .62, q.chest_r * .95, a)] +
                     quills, k=.02)
        f.fill(coat, q.quill_c, SW_DETAIL, 'quills')
        tips = [Circle(qp.p[1], .025) for qp in quills]
        f.patch(Union(tips), '#F3E6CF', coat, 'quill_tips')


def _rng(seed):
    """Tiny deterministic generator (xorshift) so outputs never depend on Python's hash seed."""
    state = [(seed * 2654435761 + 12345) & 0xFFFFFFFF or 1]

    def nxt():
        x = state[0]
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        state[0] = x & 0xFFFFFFFF
        return state[0] / 0xFFFFFFFF
    return nxt


def build(q: Quad, pose: Pose) -> Figure:
    return Builder(q, pose).build()


def with_(q: Quad, **kw) -> Quad:
    return replace(q, **kw)

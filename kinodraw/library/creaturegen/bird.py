"""Bird body plan (side view): egg body, round head, a beak by kind, folded or spread wings, thin legs.

One plan covers songbirds, owls, eagles, parrots, chickens, ducks, penguins and flamingos; the kind only
switches the beak, tail, feet and a few extras (comb, crest, ear tufts, face disc, long neck, flippers).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, deg, rot, unit
from .sdf import Circle, Cone, Ellipse, Poly, Tube, Union


@dataclass
class Bird:
    kind: str = 'songbird'      # songbird owl eagle parrot chicken duck penguin flamingo
    body_rx: float = .3
    body_ry: float = .21
    tilt: float = 25.0          # deg, body axis above horizontal when standing
    head_r: float = .16
    head_at: tuple = (.27, .16)  # head centre from the body centre, in the body frame
    neck: float = 0.0           # visible neck (duck, chicken) or long S neck (flamingo, > .3)
    beak: str = 'cone'          # cone hook flat bent
    beak_len: float = .1
    beak_c: str = '#F2B33D'
    beak_lo: str = ''           # lower beak colour when different
    beak_tip: str = ''          # dark beak tip (flamingo)
    eye_r: float = .032
    iris: str = ''
    coat: str = '#8B6B4E'
    belly: str = ''
    wing_c: str = ''
    head_c: str = ''
    tail_c: str = ''
    tail: str = 'wedge'         # wedge fan long rooster short none
    tail_len: float = .2
    tail_up: float = 20.0       # deg above the body axis
    span: float = 1.0           # spread wing length relative to the body
    leg_len: float = .16
    leg_c: str = '#C98A4B'
    feet: str = 'toes'          # toes webbed talons
    comb: str = ''              # comb + wattle colour (chicken)
    crest: str = ''             # head crest colour (cardinal)
    tufts: bool = False         # owl ear tufts
    disc: str = ''              # owl face disc colour
    mask: str = ''              # dark mask around the eye (cardinal)
    cheek: str = ''             # bare cheek patch (macaw)
    eye_ring: str = ''          # ring around the eye (penguin)
    bands: tuple = ()           # colour bands across the folded wing (macaw)
    flippers: bool = False      # penguin
    brow: bool = False          # fierce brow ridge (eagle)
    young: bool = False
    seed: int = 0


POSES = ('stand', 'walk1', 'walk2', 'fly', 'fly2', 'sit', 'sleep', 'roar', 'look_up', 'scared', 'carry')
FLIGHTLESS_POSES = ('stand', 'walk1', 'walk2', 'sit', 'sleep', 'roar', 'look_up', 'scared', 'carry')


def _rounded(points, r=.01):
    return Poly(points, r=r)


class _Build:
    def __init__(self, g: Bird, pose: str):
        self.g, self.pose, self.f = g, pose, Figure()

    # ------------------------------------------------------------------ layout
    def layout(self):
        g, pose = self.g, self.pose
        self.flying = pose in ('fly', 'fly2')
        self.down = pose in ('sit', 'sleep')
        tilt = g.tilt
        if self.flying:
            tilt = min(g.tilt, 12) if g.kind != 'owl' else 18
        elif pose == 'look_up':
            tilt = g.tilt + 8
        elif pose == 'scared':
            tilt = g.tilt + 6
        self.t = deg(tilt)
        puff = 1.08 if pose == 'scared' else 1.0
        self.rx, self.ry = g.body_rx * puff, g.body_ry * puff * (1.04 if pose == 'scared' else 1.0)
        low = math.hypot(self.rx * math.sin(self.t), self.ry * math.cos(self.t))
        self.low = low
        leg = g.leg_len * (.72 if pose == 'scared' else 1.0)
        if self.flying:
            cy = low + max(g.leg_len, .12) + .18
        elif self.down:
            cy = low * .92
        else:
            cy = leg + low * .86
        bob = {'walk1': .012, 'walk2': -.004}.get(pose, 0)
        self.c = V(0, cy + bob)
        self.leg = leg
        # head
        hx, hy = g.head_at
        if pose == 'sleep':
            hx, hy = hx * .8, hy * .82
        elif pose == 'scared':
            hx, hy = hx * .9, hy * .92
        self.hp = deg({'look_up': 48, 'roar': 18, 'sleep': -14, 'carry': -12, 'scared': 6}.get(pose, 0))
        if self.flying:
            self.hp = deg(-4)
        if g.neck > .3:
            self.neck_pts = self.long_neck()
            self.H = self.neck_pts[-1] + unit(self.hp) * g.head_r * .4
        else:
            self.H = self.c + rot(V(hx, hy), self.t)
            if self.flying and g.kind != 'owl':      # stretched forward in flight
                self.H = self.c + rot(V(hx + .04, hy * .55), self.t)
            self.neck_pts = None

    def long_neck(self):
        g, pose = self.g, self.pose
        base = self.c + rot(V(self.rx * .7, self.ry * .45), self.t)
        n = g.neck
        if self.flying:
            return [base, base + V(n * .35, .02), base + V(n * .7, .03), base + V(n * 1.0, .04)]
        if pose == 'sleep':          # head tucked back onto the back
            return [base, base + V(.02, n * .35), base + V(-.1, n * .5), base + V(-.2, n * .42)]
        if pose == 'scared':
            return [base, base + V(-.06, n * .3), base + V(.02, n * .55), base + V(.08, n * .62)]
        lean = .14 if pose == 'look_up' else 0
        drop = -.12 if pose == 'carry' else 0
        return [base, base + V(-.05, n * .35), base + V(.06 + lean * .3, n * .68), base + V(.1 + lean, n * .95 + drop)]

    # ------------------------------------------------------------------ parts
    def P(self, x, y):
        """Head-frame point: x along the beak direction, y up from it."""
        return self.H + rot(V(x, y), self.hp)

    def beak_shapes(self):
        g, r, L = self.g, self.g.head_r, self.g.beak_len
        k = g.beak
        x0 = r * .72
        if k == 'hook':
            upper = [V(x0 - r * .1, r * .42), V(x0 + L * .6, r * .32), V(x0 + L, r * .02), V(x0 + L * .92, -r * .42),
                     V(x0 + L * .7, -r * .12), V(x0, -r * .12)]
            lower = [V(x0, -r * .12), V(x0 + L * .55, -r * .16), V(x0 + L * .35, -r * .42), V(x0 - r * .05, -r * .38)]
            rr = r * .06
        elif k == 'flat':
            upper = [V(x0 - r * .05, r * .2), V(x0 + L, r * .1), V(x0 + L * 1.02, -r * .08), V(x0, -r * .06)]
            lower = [V(x0, -r * .06), V(x0 + L * .95, -r * .1), V(x0 + L * .9, -r * .24), V(x0, -r * .22)]
            rr = r * .1
        elif k == 'bent':
            upper = [V(x0 - r * .05, r * .32), V(x0 + L * .5, r * .18), V(x0 + L * .85, -r * .3), V(x0 + L * .78, -r * .62),
                     V(x0 + L * .45, -r * .2), V(x0, -r * .1)]
            lower = [V(x0, -r * .1), V(x0 + L * .4, -r * .22), V(x0 + L * .66, -r * .62), V(x0 + L * .3, -r * .45),
                     V(x0, -r * .32)]
            rr = r * .06
        else:                                   # cone
            upper = [V(x0 - r * .05, r * .3), V(x0 + L, -r * .02), V(x0, -r * .08)]
            lower = [V(x0, -r * .08), V(x0 + L * .82, -r * .08), V(x0 - r * .05, -r * .3)]
            rr = r * .04
        opening = {'roar': 1.0, 'scared': .45}.get(self.pose, 0)
        if g.kind == 'eagle' and self.pose == 'roar':
            opening = .8
        pivot = V(x0, -r * .08)

        def place(pts, a):
            return [self.P(*(pivot + rot(p - pivot, a))) for p in pts]
        up = place(upper, deg(14 * opening))
        lo = place(lower, deg(-24 * opening))
        mouth = None
        if opening:
            mouth = Poly([self.P(*pivot), self.P(*(pivot + rot(V(L * .7, 0), deg(10 * opening)))),
                          self.P(*(pivot + rot(V(L * .6, 0), deg(-20 * opening))))], r=r * .05)
        return _rounded(up, rr), _rounded(lo, rr), mouth

    def head_shape(self):
        g = self.g
        r = g.head_r
        parts = [Circle(self.H, r)]
        if self.neck_pts:
            parts.append(Tube(self.neck_pts, [g.head_r * .62, g.head_r * .55, g.head_r * .5, g.head_r * .55]))
        elif g.neck:
            base = self.c + rot(V(self.rx * .6, self.ry * .3), self.t)
            parts.append(Cone(base, self.H, r * .9, r * .75))
        return Union(parts, k=r * .4)

    def body_shape(self):
        g = self.g
        body = Ellipse(self.c, self.rx, self.ry, self.t)
        if g.kind == 'penguin':     # a broader base
            body = Union([body, Ellipse(self.c + rot(V(-self.rx * .35, -self.ry * .1), self.t), self.rx * .7,
                                        self.ry * 1.02, self.t)], k=.05)
        return body

    def tail_shape(self):
        g = self.g
        if g.tail == 'none':
            return None
        base = self.c + rot(V(-self.rx * .78, self.ry * .05), self.t)
        up = g.tail_up + {'scared': -18, 'look_up': -8}.get(self.pose, 0)
        if self.flying:
            up = 6
        a = self.t + math.pi - deg(up)
        d, n = unit(a), unit(a + math.pi / 2)
        L = g.tail_len
        if g.tail == 'fan':
            pts = [base + n * .05, base + d * L + n * L * .38, base + d * L * 1.05, base + d * L - n * L * .38,
                   base - n * .05]
            return _rounded(pts, .015)
        if g.tail == 'long':
            pts = [base + n * .045, base + d * L + n * .02, base + d * L * 1.04, base + d * L - n * .02, base - n * .045]
            return _rounded(pts, .012)
        if g.tail == 'rooster':
            feathers = []
            for i, (sweep, ln) in enumerate(((60, 1.0), (40, .95), (20, .8), (0, .7))):
                pts = [base + n * (.02 * i), ]
                aa = self.t + math.pi - deg(sweep + 40)
                p = pts[0]
                for j in range(4):
                    p = p + unit(aa) * L * ln / 4
                    pts.append(p)
                    aa += deg(-28)
                feathers.append(Tube(pts, [.05, .045, .04, .03, .015]))
            return Union(feathers, k=.02)
        if g.tail == 'short':
            pts = [base + n * .05, base + d * L, base - n * .05]
            return _rounded(pts, .02)
        pts = [base + n * .05, base + d * L + n * L * .2, base + d * L - n * L * .1, base - n * .05]   # wedge
        return _rounded(pts, .012)

    def legs(self):
        """(far leg, near leg) shapes, or (None, None) when hidden."""
        g, pose = self.g, self.pose
        if self.down:
            return None, None
        r = .02 if g.kind not in ('eagle', 'penguin', 'duck') else .026
        if g.kind == 'flamingo':
            r = .017
        top_y = self.c[1] - self.low * .6
        out = []
        for far in (True, False):
            hx = self.c[0] + (-.05 if far else .02) + (-.02 if g.kind == 'penguin' else 0)
            hip = V(hx, top_y)
            if self.flying:
                if g.kind in ('songbird', 'parrot', 'owl', 'penguin'):
                    out.append(None)
                    continue
                foot = hip + V(-.16, -.06)
                parts = [Cone(hip, foot, r, r * .8)] + self.foot(foot, deg(190), small=True)
                out.append(Union(parts, k=.01))
                continue
            if g.kind == 'flamingo' and far and pose in ('stand', 'sleep', 'look_up', 'roar', 'carry'):
                knee = hip + V(-.02, -self.leg * .45)
                foot = knee + V(.12, .1)
                out.append(Union([Cone(hip, knee, r, r), Cone(knee, foot, r, r * .8), Circle(knee, r * 1.4)], k=.01))
                continue
            step = {'walk1': (.1, -.08), 'walk2': (-.08, .1)}.get(pose, (0, 0))[0 if far else 1]
            foot = V(hx + step + .02, .0 + (.02 if step < -.05 else 0))
            bottom = foot + V(0, .025)
            parts = []
            if g.kind == 'flamingo':
                knee = (hip + bottom) / 2 + V(-.03, 0)
                parts += [Cone(hip, knee, r, r), Cone(knee, bottom, r, r), Circle(knee, r * 1.45)]
            else:
                parts.append(Cone(hip, bottom, r * 1.15, r))
            if g.kind in ('eagle', 'owl', 'chicken'):          # feathered "trousers"
                pass
            parts += self.foot(bottom, 0.0)
            out.append(Union(parts, k=.008))
        return out[0], out[1]

    def foot(self, at, a, small=False):
        g = self.g
        s = .7 if small else 1.0
        if g.feet == 'webbed':
            d = unit(a)
            n = unit(a + math.pi / 2)
            return [_rounded([at + n * .02 * s, at + d * .11 * s + n * .04 * s, at + d * .12 * s - n * .01 * s,
                              at - n * .015 * s], .01)]
        toe = .07 * s if g.feet != 'talons' else .065 * s
        rr = .011 if g.feet != 'talons' else .014
        parts = [Cone(at, at + rot(V(toe, 0), a + deg(k)), rr, rr * .8) for k in (-8, 6)]
        parts.append(Cone(at, at + rot(V(-toe * .55, 0), a + deg(-6)), rr, rr * .8))
        if g.feet == 'talons':
            for k in (-8, 6):
                tip = at + rot(V(toe, 0), a + deg(k))
                parts.append(Cone(tip, tip + V(.018, -.02), rr * .7, .004))
        return parts

    def wing_folded(self):
        g = self.g
        c = self.c + rot(V(-self.rx * .12, self.ry * .12), self.t)
        a = self.t - deg(10)
        main = Ellipse(c, self.rx * .72, self.ry * .62, a)
        tip = c + rot(V(-self.rx * 1.05, -self.ry * .15), a)
        poly = _rounded([c + rot(V(-self.rx * .3, self.ry * .45), a), tip, c + rot(V(-self.rx * .25, -self.ry * .5), a)],
                        .015)
        if g.flippers:
            c2 = self.c + rot(V(-self.rx * .12, self.ry * .4), self.t)
            fl = Ellipse(c2, self.rx * .58, self.ry * .24, self.t + deg(10))
            if self.pose in ('scared', 'roar'):
                fl = Ellipse(c2 + V(-.08, .0), self.rx * .58, self.ry * .24, self.t + deg(48))
            return fl
        return Union([main, poly], k=.04)

    def wing_spread(self, far=False):
        g = self.g
        up = self.pose == 'fly'
        S = self.c + rot(V(self.rx * .2, self.ry * .55), self.t)
        W = (self.rx * 2.2) * g.span * (.82 if far else 1.0) * (1.0 if up else .9)
        D = self.rx * .95 * g.span
        a = deg(100 if up else 152) + (deg(14) if far else deg(0))
        out_d = unit(a)
        cands = (unit(a + math.pi / 2), unit(a - math.pi / 2))
        back = min(cands, key=lambda v: v[0])

        def W2(x, y):
            return S + out_d * x + back * y
        edge = [W2(0, -D * .1), W2(W * .55, -D * .12), W2(W * 1.0, D * .25), W2(W * .86, D * .55), W2(W * .66, D * .72),
                W2(W * .44, D * .82), W2(W * .2, D * .85), W2(0, D * .7)]
        shape = [_rounded(edge, .02)]
        for x, y in ((W * .86, D * .55), (W * .66, D * .72), (W * .44, D * .82), (W * .2, D * .85)):
            shape.append(Circle(W2(x, y), D * .16))
        return Union(shape, k=.02), (W2, W, D)

    # ------------------------------------------------------------------ eyes and face
    def eye(self):
        g, f, pose = self.g, self.f, self.pose
        r = g.head_r
        if g.kind == 'owl':
            centres = [self.P(r * .02, r * .2), self.P(r * .5, r * .2)]
            er = r * .3
        else:
            centres = [self.P(r * .22, r * .26)]
            er = g.eye_r
        if g.eye_ring:
            for c in centres:
                f.dot(c, er * 1.9, g.eye_ring, 'eye_ring', SW_FINE)
        for c in centres:
            if pose == 'sleep':
                f.line([c + V(-er, 0), c + V(0, -er * .6), c + V(er, 0)], SW_DETAIL, name='eye_closed')
            elif pose == 'scared':
                f.dot(c, er * 1.35, C.WHITE, 'eye_white', SW_DETAIL)
                f.dot(c + V(er * .2, 0), er * .55, C.INK, 'pupil')
            elif g.iris or g.kind == 'owl':
                f.dot(c, er, g.iris or '#F6C343', 'iris', SW_DETAIL)
                f.dot(c + V(er * .15, 0), er * .5, C.INK, 'pupil')
                f.spot(c + V(er * .4, er * .35), er * .22)
            else:
                f.dot(c, er, C.INK, 'eye')
                f.spot(c + V(er * .35, er * .35), er * .35)
        if g.brow and pose not in ('sleep', 'scared'):
            c = centres[-1]
            f.line([c + V(-er * 1.6, er * 1.6), c + V(er * 1.6, er * .7)], SW_DETAIL, name='brow')
        elif pose == 'scared':
            c = centres[-1]
            f.line([c + V(-er * 1.2, er * 2.2), c + V(er * 1.2, er * 2.4)], SW_FINE, name='brow')
        if g.kind == 'owl':
            self.f.anchors['eye'] = centres[-1]
        else:
            self.f.anchors['eye'] = centres[0]

    # ------------------------------------------------------------------ assemble
    def build(self) -> Figure:
        g, f = self.g, self.f
        self.layout()
        shade = C.shade(g.coat, .22)
        wing_c = g.wing_c or g.coat
        far_leg, near_leg = self.legs()
        if self.flying:
            far_wing, _ = self.wing_spread(far=True)
            f.fill(far_wing, C.shade(wing_c, .2), SW, 'wing_far')
        tail = self.tail_shape()
        if tail is not None:
            f.fill(tail, g.tail_c or g.coat, SW_DETAIL + 1, 'tail')
        if far_leg is not None:
            f.fill(far_leg, C.shade(g.leg_c, .2), SW_DETAIL, 'leg_far')
        if near_leg is not None:
            f.fill(near_leg, g.leg_c, SW_DETAIL, 'leg')
        if g.comb:
            r = g.head_r
            comb = Union([Circle(self.P(-r * .45 + i * r * .32, r * (.92 + .1 * (i == 1))), r * .26) for i in range(3)],
                         k=r * .1)
            f.fill(comb, g.comb, SW_DETAIL, 'comb')
        if g.crest:
            r = g.head_r
            f.fill(_rounded([self.P(-r * .1, r * .7), self.P(-r * .95, r * 1.35), self.P(-r * .55, r * .55)], r * .1),
                   g.crest, SW_DETAIL, 'crest')
        if g.tufts:
            r = g.head_r
            for x in (-.05, .45):
                f.fill(_rounded([self.P(r * (x - .25), r * .7), self.P(r * (x - .05), r * 1.25),
                                 self.P(r * (x + .15), r * .75)], r * .06), shade, SW_DETAIL, 'ear_tuft')
        body = self.body_shape()
        head = self.head_shape()
        shape = Union([body, head], k=g.head_r * .55)
        f.fill(shape, g.coat, SW, 'body')
        if g.belly:
            if g.kind == 'penguin':
                belly = Ellipse(self.c + rot(V(-self.rx * .05, -self.ry * .6), self.t), self.rx * .9, self.ry * .9, self.t)
            elif g.kind == 'owl':
                belly = Ellipse(self.c + rot(V(.02, -self.ry * .45), self.t), self.rx * .8, self.ry * .7, self.t)
            else:
                belly = Ellipse(self.c + rot(V(self.rx * .22, -self.ry * .5), self.t), self.rx * .78, self.ry * .62,
                                self.t + deg(8))
            f.patch(belly, g.belly, shape, 'belly')
        if g.head_c:
            hc = [Circle(self.H, g.head_r * 1.03)]
            if self.neck_pts:
                hc.append(Tube(self.neck_pts, [g.head_r * .7] * 4))
            elif g.neck:
                base = self.c + rot(V(self.rx * .6, self.ry * .3), self.t)
                hc.append(Cone((base + self.H) / 2, self.H, g.head_r * .95, g.head_r))
            f.patch(Union(hc, k=.02), g.head_c, shape, 'head_colour')
        r = g.head_r
        if g.disc:
            f.patch(Union([Circle(self.P(r * .02, r * .15), r * .52), Circle(self.P(r * .5, r * .15), r * .48)], k=r * .2),
                    g.disc, shape, 'face_disc')
        if g.mask:
            f.patch(Ellipse(self.P(r * .45, r * .05), r * .5, r * .32, self.hp - deg(10)), g.mask, shape, 'mask')
        if g.cheek:
            f.patch(Ellipse(self.P(r * .3, r * .02), r * .45, r * .36), g.cheek, shape, 'cheek')
        # wings
        if self.flying:
            near, (W2, W, D) = self.wing_spread()
            f.fill(near, wing_c, SW, 'wing')
            if g.bands:
                for i, col in enumerate(g.bands):
                    band = Ellipse(W2(W * (.45 + .25 * i), D * .45), W * .14, D * .7)
                    f.patch(band, col, near, 'wing_band')
            f.line([W2(W * .6, D * .3), W2(W * .4, D * .62)], SW_FINE, name='feather')
            f.line([W2(W * .8, D * .2), W2(W * .7, D * .5)], SW_FINE, name='feather')
        else:
            wing = self.wing_folded()
            f.fill(wing, wing_c if not g.flippers else g.coat, SW_DETAIL + 1, 'wing')
            if g.bands and not g.flippers:
                for i, col in enumerate(g.bands):
                    c = self.c + rot(V(-self.rx * (.15 + .35 * i), self.ry * .1), self.t)
                    f.patch(Ellipse(c, self.rx * .2, self.ry, self.t + deg(20)), col, wing, 'wing_band')
            if not g.flippers:
                c = self.c + rot(V(-self.rx * .35, -self.ry * .05), self.t - deg(10))
                f.line([c + rot(V(.06, .04), self.t), c + rot(V(-.06, -.03), self.t)], SW_FINE, name='feather')
        # beak, wattle, eye
        upper, lower, mouth = self.beak_shapes()
        if mouth is not None:
            f.fill(mouth, C.MOUTH, SW_FINE, 'mouth')
        f.fill(lower, g.beak_lo or C.shade(g.beak_c, .12), SW_DETAIL, 'beak_lower')
        f.fill(upper, g.beak_c, SW_DETAIL, 'beak')
        if g.beak_tip:
            L = g.beak_len
            f.patch(Circle(self.P(r * .72 + L * .82, -r * .45), r * .32), g.beak_tip, upper, 'beak_tip')
            f.patch(Circle(self.P(r * .72 + L * .62, -r * .5), r * .3), g.beak_tip, lower, 'beak_tip_lower')
        if g.comb:
            f.fill(Ellipse(self.P(r * .78, -r * .5), r * .16, r * .26), g.comb, SW_FINE, 'wattle')
        self.eye()
        L = g.beak_len
        f.anchors['head'] = self.H
        f.anchors['mouth'] = self.P(r * .72 + L * .6, -r * .2)
        if self.pose == 'carry':
            f.anchors['carry'] = self.P(r * .72 + L * .55, -r * .35)
        f.anchors['ground'] = V(0, 0)
        return f


def build(g: Bird, pose: str) -> Figure:
    return _Build(g, pose).build()

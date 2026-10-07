"""People (front view, face turned a little toward the facing side): big round head, rounded torso,
tube limbs, mitten hands and an outfit by role (king, queen, villager, teacher, explorer, casual).

The skeleton is posed in a standing frame and passed through ``T`` so lying poses reuse it rotated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, deg, rot, two_bone, unit
from .sdf import Circle, Cone, Ellipse, Poly, Tube, Union

GOLD = '#F2C230'


@dataclass
class Person:
    age: str = 'adult'          # child adult elder
    sex: str = 'male'
    skin: str = '#E8B48F'
    hair: str = '#3B2B24'
    hair_style: str = 'short'   # short long bun bald curly ponytail
    outfit: str = 'villager'    # king queen villager teacher explorer casual princess
    top: str = '#5B8DD6'
    bottom: str = '#3D4A5C'
    shoes: str = '#4A3A30'
    accent: str = ''            # trim, sash, scarf
    dress: bool = False         # skirt or gown instead of trousers
    glasses: bool = False
    beard: bool = False
    cane: bool = False
    seed: int = 0


POSES = ('stand', 'walk1', 'walk2', 'run', 'sit', 'lie', 'sleep', 'shout', 'wave', 'look_up', 'scared', 'carry')

PROPORTIONS = {   # head_r, torso, leg, shoulder half-width, hip half-width, upper arm, forearm, limb radius
    'adult': (.2, .27, .34, .13, .075, .13, .12, .045),
    'child': (.19, .18, .2, .1, .065, .09, .09, .04),
    'elder': (.19, .26, .32, .125, .075, .13, .12, .044),
}


class _Build:
    def __init__(self, g: Person, pose: str):
        self.g, self.pose, self.f = g, pose, Figure()
        (self.hr, self.torso, self.leg, self.sw, self.hw, self.ua, self.fa,
         self.lr) = PROPORTIONS[g.age]
        self.lying = pose in ('lie', 'sleep')

    # ------------------------------------------------------------------ frame
    def T(self, p):
        p = V(p)
        if self.lying:        # rotate the standing figure onto its back, head toward the facing side
            return V(p[1] - .5, -p[0] + self.sw + .04)
        return p

    def A(self, a):
        return a - math.pi / 2 if self.lying else a

    def circle(self, c, r):
        return Circle(self.T(c), r)

    def cone(self, a, b, ra, rb):
        return Cone(self.T(a), self.T(b), ra, rb)

    def ellipse(self, c, rx, ry, a=0.0):
        return Ellipse(self.T(c), rx, ry, self.A(a))

    def poly(self, pts, r=.01):
        return Poly([self.T(p) for p in pts], r=r)

    def tube(self, pts, radii):
        return Tube([self.T(p) for p in pts], radii)

    # ------------------------------------------------------------------ skeleton
    def skeleton(self):
        g, pose = self.g, self.pose
        crouch = {'scared': .07, 'sit': 0}.get(pose, 0)
        hip_y = self.leg - crouch
        if pose == 'sit':
            hip_y = self.leg * .28
        if pose == 'run':
            hip_y = self.leg * .94
        self.lean = deg({'run': -10, 'scared': 4}.get(pose, 0))
        if g.age == 'elder' and pose not in ('lie', 'sleep', 'sit'):
            self.lean += deg(-6)
        self.hip = V(0, hip_y)
        up = unit(math.pi / 2 + self.lean)
        self.up = up
        self.chest = self.hip + up * self.torso
        self.sh = {s: self.chest + rot(V(s * self.sw, -.03), self.lean) for s in (-1, 1)}
        tilt = {'look_up': .04, 'shout': .015}.get(pose, 0)
        self.head = self.chest + up * (self.hr * 1.02 + .02) + V(0, tilt * .2)
        self.look = 1.0      # face turned toward +x
        # legs
        self.feet, self.knees = {}, {}
        l1, l2 = self.leg * .52, self.leg * .5
        for s in (-1, 1):
            hipj = self.hip + rot(V(s * self.hw, 0), self.lean)
            if pose == 'sit':          # cross-legged: knees out, feet tucked in
                knee = V(s * (self.hw + self.leg * .42), self.leg * .14)
                foot = V(s * self.hw * .4, .035)
            elif pose == 'walk1' or pose == 'walk2':
                fwd = (s == 1) == (pose == 'walk1')
                foot = V(s * self.hw * .9 + (.07 if fwd else -.05), .0 if fwd else .045)
                knee, foot = two_bone(hipj, foot, l1, l2, 1)
            elif pose == 'run':
                if s == 1:
                    foot = hipj + V(.17, -self.leg * .5)
                else:
                    foot = V(-self.hw - .12, .07)
                knee, foot = two_bone(hipj, foot, l1, l2, 1)
            elif pose == 'scared':
                foot = V(s * (self.hw + .05), 0)
                knee, foot = two_bone(hipj, foot, l1, l2, s)
            else:
                foot = V(s * self.hw * 1.05, 0)
                knee, foot = two_bone(hipj, foot, l1, l2, 1)
            self.knees[s], self.feet[s] = knee, foot
            self.__dict__.setdefault('hipj', {})[s] = hipj
        # arms (+1 is the arm on the facing side)
        self.elbows, self.hands = {}, {}
        hc = self.head
        for s in (-1, 1):
            root = self.sh[s]
            if pose == 'wave' and s == 1:
                target = root + V(.17, self.ua + self.fa * .7)
                bend = 1
            elif pose == 'shout':
                target = hc + V(s * self.hr * .95, -self.hr * .35)
                bend = -s
            elif pose == 'scared':
                target = hc + V(s * self.hr * 1.15, -self.hr * .15)
                bend = -s
            elif pose == 'carry':
                target = self.hip + up * self.torso * .42 + V(s * .05 + .02, 0)
                bend = s
            elif pose == 'run':
                target = root + (V(.12, -.08) if s == 1 else V(-.1, -.2))
                bend = 1 if s == 1 else -1
            elif pose in ('walk1', 'walk2'):
                fwd = (s == 1) != (pose == 'walk1')
                target = root + V(s * .05 + (.07 if fwd else -.06), -(self.ua + self.fa) * .9)
                bend = s
            elif pose == 'sit':
                target = V(s * (self.hw + self.leg * .3), self.leg * .2)
                bend = s
            else:
                target = root + V(s * .04, -(self.ua + self.fa) * .95)
                bend = s
            elbow, hand = two_bone(root, target, self.ua, self.fa, bend)
            self.elbows[s], self.hands[s] = elbow, hand

    # ------------------------------------------------------------------ clothes and body
    def legs(self):
        g, f = self.g, self.f
        long_gown = g.dress and g.outfit in ('queen', 'princess', 'king') or (g.dress and g.age == 'elder')
        leg_c = g.bottom if not g.dress else g.skin
        if g.outfit in ('explorer', 'casual') and not g.dress:
            leg_c = g.skin                  # shorts
        for s in (-1, 1):
            hipj, knee, foot = self.hipj[s], self.knees[s], self.feet[s]
            if long_gown and self.pose not in ('run', 'sit'):
                parts = [self.ellipse(foot + V(.03, .02), .065, .038)]
                f.fill(Union(parts), g.shoes, SW_DETAIL, 'shoe')
                continue
            shape = Union([self.cone(hipj, knee, self.lr * 1.15, self.lr), self.cone(knee, foot + V(0, .03), self.lr,
                                                                                      self.lr * .9)], k=.02)
            f.fill(shape, leg_c, SW_DETAIL + 1, 'leg')
            if leg_c == g.skin and not g.dress:          # shorts cuffs
                f.patch(self.ellipse(hipj + (knee - hipj) * .45, self.lr * 1.6, self.lr * 1.8), g.bottom, shape,
                        'shorts')
            f.fill(self.ellipse(foot + V(.035, .02), .065, .036), g.shoes, SW_DETAIL, 'shoe')

    def torso_shape(self):
        g = self.g
        h, c, up = self.hip, self.chest, self.up
        side = unit(self.lean)
        w_sh, w_h = self.sw + .01, self.hw + .045
        pts = [h - side * w_h - up * .02, h + side * w_h - up * .02, c + side * w_sh, c - side * w_sh]
        return pts

    def body(self):
        g, f = self.g, self.f
        pts = self.torso_shape()
        long_gown = g.dress and g.outfit in ('queen', 'princess') or (g.dress and g.age == 'elder')
        torso = self.poly(pts, r=.055)
        skirt = None
        if g.dress:
            h = self.hip
            side = unit(self.lean)
            hem = 0.035 if long_gown and self.pose not in ('run', 'sit') else self.leg * .45
            if self.pose == 'sit':
                hem = .03
            flare = .1 + (.06 if long_gown else 0)
            sk = [h - side * (self.hw + .05) + self.up * .06, h + side * (self.hw + .05) + self.up * .06,
                  V(h[0] + self.hw + flare, hem), V(h[0] - self.hw - flare, hem)]
            if self.pose == 'sit':
                sk = [sk[0], sk[1], V(self.hw + self.leg * .5, .03), V(-self.hw - self.leg * .5, .03)]
            skirt = self.poly(sk, r=.035)
        return torso, skirt

    def cape(self):
        g, f = self.g, self.f
        if g.outfit != 'king' or self.pose == 'sit':
            return
        c = self.chest
        bottom = .04 if self.pose not in ('run',) else self.leg * .4
        sway = -.08 if self.pose in ('run', 'walk1', 'walk2') else 0
        pts = [c + V(-self.sw - .02, .0), c + V(self.sw + .02, 0), V(self.sw + .12 + sway * .3, bottom),
               V(-self.sw - .14 + sway, bottom)]
        shape = self.poly(pts, r=.04)
        f.fill(shape, g.accent or '#C62828', SW, 'cape')
        f.patch(self.poly([V(-self.sw - .3, bottom - .05), V(self.sw + .3, bottom - .05), V(self.sw + .3, bottom + .045),
                           V(-self.sw - .3, bottom + .045)], r=0), '#FAFAF7', shape, 'cape_trim')

    def arms(self, sleeve):
        g, f = self.g, self.f
        out = []
        for s in (-1, 1):
            root, elbow, hand = self.sh[s], self.elbows[s], self.hands[s]
            short = g.outfit in ('explorer', 'casual')
            arm = Union([self.cone(root, elbow, self.lr * 1.1, self.lr), self.cone(elbow, hand, self.lr, self.lr * .9)],
                        k=.02)
            out.append((s, arm, root, elbow, hand, short))
        return out

    def draw_arm(self, item, sleeve):
        g, f = self.g, self.f
        s, arm, root, elbow, hand, short = item
        if short:
            f.fill(arm, g.skin, SW_DETAIL + 1, 'arm')
            f.patch(self.cone(root, root + (elbow - root) * .6, self.lr * 1.8, self.lr * 1.7), sleeve, arm, 'sleeve')
        else:
            f.fill(arm, sleeve, SW_DETAIL + 1, 'arm')
        f.fill(self.circle(hand, self.lr * 1.05), g.skin, SW_DETAIL, 'hand')

    # ------------------------------------------------------------------ head
    def hair_back(self):
        g, f = self.g, self.f
        hc, r = self.head, self.hr
        if g.hair_style in ('long', 'ponytail'):
            if g.hair_style == 'long':
                shape = Union([self.ellipse(hc + V(0, -r * .2), r * 1.12, r * 1.25),
                               self.ellipse(hc + V(0, -r * 1.0), r * 1.0, r * .6)], k=.04)
            else:
                shape = Union([self.circle(hc, r * 1.06), self.tube([hc + V(-r * .8, r * .3), hc + V(-r * 1.35, -r * .2),
                                                                    hc + V(-r * 1.25, -r * .9)],
                                                                   [r * .3, r * .28, r * .18])], k=.03)
            f.fill(shape, g.hair, SW, 'hair_back')
        if g.hair_style == 'bun':
            f.fill(self.circle(hc + V(-r * .2, r * 1.0), r * .38), g.hair, SW_DETAIL, 'bun')

    def head_draw(self):
        g, f = self.g, self.f
        hc, r = self.head, self.hr
        lx = self.look * r * .16
        for s in (-1, 1):     # ears
            f.fill(self.circle(hc + V(s * r * .97, -r * .08), r * .2), g.skin, SW_DETAIL, 'ear')
        head = self.circle(hc, r)
        f.fill(head, g.skin, SW, 'head')
        # hair front
        hs = g.hair_style
        if hs in ('short', 'long', 'ponytail', 'bun', 'curly'):
            cap = Union([self.ellipse(hc + V(0, r * .7), r * 1.05, r * .5),
                         self.ellipse(hc + V(-r * .72, r * .35), r * .35, r * .5, deg(-10))], k=.04)
            if hs == 'curly':
                cap = Union([cap] + [self.circle(hc + rot(V(0, r * .95), deg(a)), r * .3) for a in (-70, -35, 0, 35, 70)],
                            k=.03)
            if hs == 'short':
                cap = Union([cap, self.ellipse(hc + V(-r * .9, r * .1), r * .22, r * .4)], k=.04)
            f.patch(Union([cap]), g.hair, head, 'hair')
            if hs == 'curly':
                f.fill(Union([self.circle(hc + rot(V(0, r * .98), deg(a)), r * .3) for a in (-70, -35, 0, 35, 70)],
                             k=.03), g.hair, SW_DETAIL, 'curls')
        elif hs == 'bald':
            f.patch(Union([self.ellipse(hc + V(s * r * .95, r * .05), r * .25, r * .35) for s in (-1, 1)]), g.hair, head,
                    'hair_sides')
        if g.beard:
            beard = Union([self.ellipse(hc + V(lx * .5, -r * .8), r * .66, r * .36),
                           self.circle(hc + V(lx * .5, -r * 1.06), r * .26)], k=.06)
            f.fill(beard, g.hair, SW_DETAIL, 'beard')
        self.face(hc, r, lx)
        # headwear
        if g.outfit in ('king', 'queen', 'princess'):
            w = r * (.85 if g.outfit != 'princess' else .6)
            base = hc[1] + r * .72
            pts = [V(hc[0] - w, base), V(hc[0] - w, base + r * .32), V(hc[0] - w * .6, base + r * .62),
                   V(hc[0] - w * .3, base + r * .3), V(hc[0], base + r * .7), V(hc[0] + w * .3, base + r * .3),
                   V(hc[0] + w * .6, base + r * .62), V(hc[0] + w, base + r * .32), V(hc[0] + w, base)]
            crown = self.poly(pts, r=.008)
            f.fill(crown, GOLD, SW_DETAIL, 'crown')
            f.dot(self.T(V(hc[0], base + r * .18)), r * .1, '#E53935', 'jewel', SW_FINE)
        elif g.outfit == 'explorer':
            dome = self.ellipse(hc + V(0, r * .9), r * .95, r * .5)
            brim = self.ellipse(hc + V(0, r * .66), r * 1.35, r * .16)
            f.fill(brim, C.shade(g.accent or '#C9A66B', .12), SW_DETAIL, 'hat_brim')
            f.fill(dome, g.accent or '#C9A66B', SW_DETAIL, 'hat')
            f.patch(self.ellipse(hc + V(0, r * .74), r * 1.0, r * .08), C.shade(g.accent or '#C9A66B', .35), dome,
                    'hat_band')

    def face(self, hc, r, lx):
        g, f, pose = self.g, self.f, self.pose
        ey = -r * .02 + (r * .05 if pose == 'look_up' else 0)
        er = r * .11
        eyes = [hc + V(lx + s * r * .36, ey) for s in (-1, 1)]
        for c in eyes:
            if pose == 'sleep':
                f.line([self.T(c + V(-er, 0)), self.T(c + V(0, -er * .7)), self.T(c + V(er, 0))], SW_DETAIL,
                       name='eye_closed')
            elif pose == 'scared':
                f.dot(self.T(c), er * 1.5, C.WHITE, 'eye_white', SW_DETAIL)
                f.dot(self.T(c + V(0, -er * .1)), er * .65, C.INK, 'pupil')
            elif pose == 'wave':
                f.line([self.T(c + V(-er, -er * .2)), self.T(c + V(0, er * .7)), self.T(c + V(er, -er * .2))], SW_DETAIL,
                       name='eye_happy')
            else:
                up = er * .45 if pose == 'look_up' else 0
                f.dot(self.T(c + V(r * .03, up)), er, C.INK, 'eye')
                f.spot(self.T(c + V(r * .03 + er * .35, up + er * .35)), er * .35)
        # brows
        for s, c in zip((-1, 1), eyes):
            if pose == 'shout':
                pts = [c + V(-s * er * 1.4, er * 2.0), c + V(s * er * 1.3, er * 2.8)]
            elif pose == 'scared':
                pts = [c + V(-er * 1.3, er * 2.4), c + V(er * 1.3, er * 2.6)]
            else:
                pts = [c + V(-er * 1.2, er * 2.1), c + V(er * 1.2, er * 2.2)]
            f.line([self.T(p) for p in pts], SW_FINE, color=C.shade(g.hair, .1) if g.hair_style != 'bald' else C.INK,
                   name='brow')
        if g.glasses:
            for c in eyes:
                f.line([self.T(c + rot(V(er * 2.1, 0), deg(a))) for a in range(0, 361, 30)], SW_FINE, name='glasses',
                       closed=True)
            f.line([self.T(eyes[0] + V(er * 2.1, 0)), self.T(eyes[1] - V(er * 2.1, 0))], SW_FINE, name='glasses_bridge')
        # nose and cheeks
        n = hc + V(lx * 1.5, -r * .14)
        f.line([self.T(n + V(-r * .02, r * .06)), self.T(n + V(r * .06, -r * .02)), self.T(n + V(-r * .02, -r * .05))],
               SW_FINE, name='nose')
        for s in (-1, 1):
            f.spot(self.T(hc + V(lx + s * r * .58, -r * .25)), r * .13, C.mix(g.skin, '#F08080', .45), 'cheek')
        # mouth
        m = hc + V(lx, -r * .45)
        if pose in ('shout', 'scared'):
            ry = r * (.2 if pose == 'shout' else .14)
            f.fill(self.ellipse(m + V(0, -ry * .3), r * (.2 if pose == 'shout' else .12), ry), C.MOUTH, SW_DETAIL,
                   'mouth')
        elif pose == 'look_up':
            f.fill(self.ellipse(m, r * .07, r * .08), C.MOUTH, SW_FINE, 'mouth')
        elif pose in ('wave', 'carry', 'stand', 'walk1', 'walk2', 'sit'):
            f.line([self.T(m + V(-r * .2, r * .06)), self.T(m + V(0, -r * .08)), self.T(m + V(r * .2, r * .06))],
                   SW_DETAIL, name='smile')
        elif pose == 'sleep':
            f.line([self.T(m + V(-r * .08, 0)), self.T(m + V(r * .08, 0))], SW_FINE, name='mouth')
        else:
            f.line([self.T(m + V(-r * .16, 0)), self.T(m + V(0, -r * .04)), self.T(m + V(r * .16, 0))], SW_DETAIL,
                   name='mouth')
        if pose == 'scared':
            d = hc + V(lx + r * .95, r * .55)
            f.fill(Union([Circle(self.T(d), r * .1), Poly([self.T(d + V(-r * .08, r * .04)), self.T(d + V(0, r * .25)),
                                                            self.T(d + V(r * .08, r * .04))])]), '#8EC9F0', SW_FINE,
                   'sweat')
        f.anchors['eye'] = self.T(eyes[1])
        f.anchors['mouth'] = self.T(m)

    # ------------------------------------------------------------------ assemble
    def build(self) -> Figure:
        g, f = self.g, self.f
        self.skeleton()
        sleeve = g.top
        self.cape()
        self.hair_back()
        arms = self.arms(sleeve)
        front = self.pose in ('carry', 'scared', 'shout')
        if g.cane and self.pose not in ('lie', 'sleep', 'sit', 'run', 'wave', 'shout', 'scared', 'carry'):
            h = self.hands[1]
            f.fill(Union([self.cone(h + V(.0, .03), V(h[0] + .06, 0), .016, .014),
                          self.tube([h + V(0, .03), h + V(-.02, .07), h + V(-.06, .06)], [.016, .016, .014])], k=.005),
                   '#7A5230', SW_FINE, 'cane')
        if not front:
            for item in arms:
                self.draw_arm(item, sleeve)
        self.legs()
        torso, skirt = self.body()
        if skirt is not None:
            f.fill(skirt, g.bottom if g.outfit not in ('queen', 'princess') else g.top, SW, 'skirt')
        f.fill(torso, g.top, SW, 'torso')
        self.trim(torso)
        if front and self.pose != 'shout':
            for item in arms:
                self.draw_arm(item, sleeve)
        self.head_draw()
        if self.pose == 'shout':
            for item in arms:
                self.draw_arm(item, sleeve)
        if self.pose == 'wave':
            h = self.hands[1]
            for k in (0, 1):
                a0 = deg(20 + k * 0)
                rr = self.lr * (2.2 + k * 1.1)
                f.line([self.T(h + rot(V(rr, 0), a0 + deg(t))) for t in (-30, 0, 30)], SW_FINE, name='wave_line')
        if self.pose == 'carry':
            f.anchors['carry'] = self.T((self.hands[-1] + self.hands[1]) / 2 + V(0, .04))
        f.anchors['head'] = self.T(self.head)
        f.anchors['hand'] = self.T(self.hands[1])
        f.anchors['ground'] = V(0, 0)
        return f

    def trim(self, torso):
        g, f = self.g, self.f
        h, c, up = self.hip, self.chest, self.up
        o = g.outfit
        if o == 'king':
            f.patch(self.ellipse(c + V(0, -.01), self.sw * 1.2, .05), '#FAFAF7', torso, 'collar')
            f.patch(self.cone(h + up * .02, c, .03, .03), GOLD, torso, 'robe_band')
        elif o in ('queen', 'princess'):
            f.patch(self.ellipse(c + V(0, .0), self.sw * .7, .05), '#FAFAF7', torso, 'neckline')
            f.patch(self.ellipse(h + up * .04, self.hw * 2, .02), GOLD, torso, 'belt')
        elif o == 'teacher':
            f.patch(self.poly([c + V(-.035, .01), c + V(.035, .01), c + V(0, -.07)], r=.003), '#FAFAF7', torso,
                    'collar')
            f.patch(self.poly([c + V(-.012, -.03), c + V(.012, -.03), c + V(.016, -self.torso * .6),
                               c + V(0, -self.torso * .7), c + V(-.016, -self.torso * .6)], r=.004),
                    g.accent or '#C62828', torso, 'tie')
        elif o == 'explorer':
            f.patch(self.cone(c + V(-self.sw * .8, 0), h + V(self.hw, up[1] * .04), .018, .018), '#7A5230', torso,
                    'strap')
            f.patch(self.ellipse(h + up * .03, self.hw * 2, .022), '#7A5230', torso, 'belt')
        elif o == 'villager' and not g.dress:
            f.patch(self.ellipse(h + up * .04, self.hw * 2, .025), g.accent or '#7A5230', torso, 'belt')
        elif g.accent:
            f.patch(self.ellipse(c + V(0, -.02), self.sw * 1.1, .04), g.accent, torso, 'scarf')


def build(g: Person, pose: str) -> Figure:
    return _Build(g, pose).build()

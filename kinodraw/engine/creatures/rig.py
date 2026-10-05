"""Semantic body parts and two-bone limbs in local SVG units (feet at y=0, facing right)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .actions import Pose
from .genes import Genome

Point = tuple[float, float]


@dataclass(frozen=True)
class Ellipse:
    x: float
    y: float
    rx: float
    ry: float


@dataclass(frozen=True)
class Limb:
    root: Point
    joint: Point
    end: Point
    width: float


@dataclass
class Rig:
    genome: Genome
    pose: Pose
    body: Ellipse
    chest: Ellipse
    head: Ellipse
    parts: dict[str, Point]
    legs: dict[str, Limb] = field(default_factory=dict)
    arms: dict[str, Limb] = field(default_factory=dict)
    tail: tuple[Point, ...] = ()
    mane: tuple[tuple[Point, ...], ...] = ()
    mane_radius: float = 0.
    eye_radius: float = 4.

    @property
    def head_body_ratio(self):
        return self.head.rx / self.body.rx


def two_bone(root: Point, target: Point, upper: float, lower: float, bend=1) -> tuple[Point, Point]:
    """Analytic IK; clamp unreachable targets rather than stretching either segment."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    raw = math.hypot(dx, dy)
    distance = min(upper + lower - .001, max(abs(upper - lower) + .001, raw))
    angle = math.atan2(dy, dx)
    offset = math.acos(min(1., max(-1., (upper * upper + distance * distance - lower * lower) / (2 * upper * distance))))
    joint = root[0] + upper * math.cos(angle + bend * offset), root[1] + upper * math.sin(angle + bend * offset)
    end = root[0] + distance * math.cos(angle), root[1] + distance * math.sin(angle)
    return joint, end


def spring_chain(root: Point, lengths: tuple[float, ...], angle: float, t: float,
                 drive=0., frequency=.3) -> tuple[Point, ...]:
    """Steady-state driven springs, with increasing lag down the chain; random access in time.

    Each link's damped oscillator has a lower natural frequency than its parent. The transfer function
    supplies gain and phase, so the tip trails the root without integration order affecting frames.
    """
    points, theta, phase = [root], math.radians(angle), 0.
    omega = 2 * math.pi * frequency
    for i, length in enumerate(lengths):
        natural = 2 * math.pi * (1.25 - .12 * min(i, 5))
        damping = .62
        phase += math.atan2(2 * damping * natural * omega, natural * natural - omega * omega)
        gain = natural * natural / math.hypot(natural * natural - omega * omega, 2 * damping * natural * omega)
        theta += math.radians(drive) * .28 * gain * math.sin(omega * t - phase)
        points.append((points[-1][0] + length * math.cos(theta), points[-1][1] + length * math.sin(theta)))
    return tuple(points)


def build(genome: Genome, pose: Pose = Pose(), t: float = 0.) -> Rig:
    g = genome.repair()
    if g.kind == 'humanoid':
        return _human(g, pose, t)
    if g.kind == 'blob':
        body = Ellipse(0., -65 + pose.crouch, 65., 65. * (1 + pose.breath))
        head = Ellipse(12 + pose.head_x, -83 + pose.head_y, 32., 30.)
        return Rig(g, pose, body, body, head, _face_parts(head, pose), eye_radius=5.)
    baby, young = g.age == 'baby', g.age == 'young'
    hyena, canine = g.species == 'hyena', g.family == 'canine'
    variation = g.stream('anatomy').uniform(.98, 1.02)
    body_rx = (62. if baby else 76. if young else 88.) * variation
    body_y = -56. if baby else -78. if young else -91.
    slender = g.sex == 'female' and not baby
    body_ry = 39. if baby else 38. if slender else 42. if young else 45.
    head_r = (50. if baby else 42. if young else 39.) * variation
    head_x = 35. if baby else 58. if young else 73.
    head_y = -95. if baby else -123. if young else -134.
    if hyena:
        body_rx *= .86
        head_r *= .91
        head_y += 4
        body_ry = 37. if young else 40.
    body = Ellipse(-35. + pose.lean * .6, body_y + pose.crouch, body_rx, body_ry * (1 + pose.breath))
    chest = Ellipse(body.x + body.rx * .67 + pose.lean * .60,
                    body.y - (18 if hyena else 1) + pose.lean * .38,
                    35. if not baby else 29., (49. if hyena else body_ry) * (1 + pose.breath * 1.5))
    head = Ellipse(head_x + pose.head_x, head_y + pose.head_y + pose.crouch * .65,
                   head_r * (1.06 if canine else 1.), head_r * (1. if baby or slender else 1.08))
    parts = _face_parts(head, pose, head.rx * (.27 if hyena else .43 if canine else 0.))
    parts['tail_root'] = body.x - body.rx * .94, body.y - 2
    legs = {}
    for i, name in enumerate(('hind_far', 'hind_near', 'front_far', 'front_near')):
        front, far = i >= 2, i % 2 == 0
        x = body.x + body.rx * (.70 if front else -.70) + (-13 if far else 4)
        rest_y = body_y + (-12 if front and hyena else 20 if hyena else 5 if front else 12)
        root = x + pose.lean * .25, rest_y + pose.crouch + pose.lean * (.28 if front else -.12)
        length = -rest_y + 5
        stride = math.sin(math.radians(pose.legs[i])) * length * .55
        width = 23. if baby else 25. if front else 31.
        target = x + (-7 if front else -10) + stride, -1 - width * .40 - pose.dy - max(0., -pose.knees[i]) * .65
        if name == 'front_near' and abs(pose.swipe) > .001:
            angle = math.radians(105 * pose.swipe)
            target = x + length * math.sin(angle), root[1] + length * math.cos(angle)
        joint, end = two_bone(root, target, length * .54, length * .50, 1 if front else -1)
        legs[name] = Limb(root, joint, end, width)
        parts[name + '_paw'] = end
    tail_length = 13. if baby else 12. if hyena or canine else 16.5
    tail = spring_chain(parts['tail_root'], (tail_length,) * 5, -155 if baby else -150, t, 14 + pose.tail)
    mane_radius, mane = 0., ()
    if g.species == 'lion' and g.sex == 'male' and g.age in ('adult', 'old') and 'mane_none' not in g.marks:
        mane_radius = head_r * (2.08 if 'mane_black' in g.marks else 1.85)
        rng = g.stream('pattern:mane')
        chains = []
        for i in range(16):
            angle = 2 * math.pi * i / 16
            root = (head.x + pose.mane_lag + mane_radius * .66 * math.cos(angle),
                    head.y - pose.mane_lag * .5 + mane_radius * .66 * math.sin(angle))
            length = mane_radius * rng.uniform(.25, .35) * (1 + max(0., pose.mane) * .007)
            chains.append(spring_chain(root, (length * .5, length * .5), math.degrees(angle), t,
                                       7 + pose.mane + pose.head_pitch * .5, frequency=1.8))
        mane = tuple(chains)
    return Rig(g, pose, body, chest, head, parts, legs, tail=tail, mane=mane,
               mane_radius=mane_radius, eye_radius=head_r * (.205 if baby else .14))


def _face_parts(head, pose, snout=0.):
    r = head.rx
    angle = math.radians(pose.head_pitch)
    def point(x, y):
        return head.x + x * math.cos(angle) - y * math.sin(angle), head.y + x * math.sin(angle) + y * math.cos(angle)
    return {'head': (head.x, head.y), 'jaw': point(r * .36 + snout, r * (.76 + pose.jaw * .65)),
            'mouth': point(r * .38 + snout, r * (.60 + pose.jaw * .35)), 'nose': point(r * .38 + snout, r * .28),
            'ear_left': point(-r * .65, -r * .8), 'ear_right': point(r * .64, -r * .81),
            'eye_left': point(-r * .24, -r * .13), 'eye_right': point(r * .55, -r * .14)}


def _human(g, p, t):
    baby = g.age == 'baby'
    leg_length = 47. if baby else 98.
    torso = 52. if baby else 81.
    hip_y = -leg_length + p.crouch
    body = Ellipse(0., hip_y - torso / 2, 24. if baby else 31., torso / 2 * (1 + p.breath))
    chest = Ellipse(0., hip_y - torso * .73, body.rx, torso * .28 * (1 + p.breath))
    head = Ellipse(p.head_x, hip_y - torso - (29 if baby else 31) + p.head_y,
                   32. if baby else 27., 33. if baby else 34.)
    parts, legs, arms = _face_parts(head, p), {}, {}
    for i, side in enumerate(('far', 'near')):
        x = -14. if i == 0 else 14.
        root = (x, hip_y)
        target = (x + math.sin(math.radians(p.legs[i])) * leg_length * .65,
                  -max(0., -p.knees[i]) * .6)
        joint, end = two_bone(root, target, leg_length * .53, leg_length * .53)
        legs[side] = Limb(root, joint, end, 13.)
        shoulder = (-body.rx if i == 0 else body.rx, chest.y - 8)
        arm_length = torso * .85
        angle = math.radians(p.arms[i] + (-10 if i == 0 else 10))
        hand = (shoulder[0] + arm_length * math.sin(angle), shoulder[1] + arm_length * math.cos(angle))
        joint, end = two_bone(shoulder, hand, arm_length * .52, arm_length * .52, -1 if i else 1)
        arms[side] = Limb(shoulder, joint, end, 11.)
        parts['hand_' + side] = end
    return Rig(g, p, body, chest, head, parts, legs, arms, eye_radius=5. if baby else 3.7)

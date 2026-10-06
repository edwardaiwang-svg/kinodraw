"""Continuous pose channels and finite anticipation / strike / settle cues (seconds)."""
from __future__ import annotations

import math
from dataclasses import dataclass, fields

DURATIONS = {'roar': 2.4, 'whimper': 2.2, 'tremble': 2.2, 'nudge': 1.8, 'laugh': 2.4,
             'swipe': 1.4, 'walk': 3., 'run': 2.5, 'sit': 2.4, 'look': 2., 'pounce': 1.8,
             'hide': 2.4, 'breathe_heavy': 3.5, 'sleep': 2.8}
ACTIONS = tuple(DURATIONS)
TREMBLE_CYCLES = 16.
# Whole-cue horizontal travel, in the rig's 600-unit drawing space before genome size; the pose cycle itself stays in
# place (Pose.dx is never used for walk/run), so a scene or preview moves the character exactly once, by travel_x.
TRAVEL = {'walk': 190., 'run': 330.}


@dataclass(frozen=True)
class Action:
    name: str
    start: float = 0.
    duration: float | None = None
    intensity: float = 1.

    @property
    def seconds(self):
        return max(.1, self.duration if self.duration is not None else DURATIONS.get(self.name, 2.))


@dataclass(frozen=True)
class Pose:
    dx: float = 0.
    dy: float = 0.
    squash: float = 0.
    breath: float = 0.
    head_x: float = 0.
    head_y: float = 0.
    head_pitch: float = 0.
    jaw: float = 0.
    blink: float = 0.
    ears: float = 0.
    tail: float = 0.
    mane: float = 0.
    legs: tuple[float, ...] = (0., 0., 0., 0.)
    knees: tuple[float, ...] = (0., 0., 0., 0.)
    arms: tuple[float, ...] = (0., 0.)
    swipe: float = 0.
    sound: float = 0.
    worry: float = 0.
    puffs: float = 0.
    crouch: float = 0.
    look: float = 0.
    lean: float = 0.
    fierce: float = 0.
    cackle: float = 0.
    mane_lag: float = 0.
    screen_shake: float = 0.
    sound_expand: float = 0.
    sleep: float = 0.


def blend(a: Pose, b: Pose, amount: float) -> Pose:
    amount = min(1., max(0., amount))
    values = {}
    for f in fields(Pose):
        x, y = getattr(a, f.name), getattr(b, f.name)
        values[f.name] = tuple(i + (j - i) * amount for i, j in zip(x, y)) if isinstance(x, tuple) else x + (y - x) * amount
    return Pose(**values)


def add(a: Pose, b: Pose) -> Pose:
    values = {}
    for f in fields(Pose):
        x, y = getattr(a, f.name), getattr(b, f.name)
        values[f.name] = tuple(i + j for i, j in zip(x, y)) if isinstance(x, tuple) else x + y
    return Pose(**values)


def squash_scale(amount: float) -> tuple[float, float]:
    """Preserve projected area in 2D: the horizontal scale is the reciprocal of the vertical scale."""
    sy = 1. - min(.45, max(-.45, amount))
    return 1. / sy, sy


def smooth(u):
    u = min(1., max(0., u))
    return u * u * (3. - 2. * u)


def window(u, attack=.18, release=.72):
    return smooth(u / attack) * (1. - smooth((u - release) / (1. - release))) if 0. < u < 1. else 0.


def strike(u):
    if not 0. < u < 1.:
        return 0.
    if u < .2:
        return -.22 * math.sin(math.pi * u / .2)
    if u < .38:
        return smooth((u - .2) / .18)
    return math.exp(-6. * (u - .38)) * (1. - smooth((u - .75) / .25))


def shake(u, cycles=9.):
    return math.sin(2. * math.pi * cycles * u) * window(u)


def action_pose(action: Action | str, t: float, *, until: float | None = None) -> Pose:
    action = Action(action) if isinstance(action, str) else action
    if action.name in ('idle', 'rest'):
        return Pose()
    if action.name not in ACTIONS:
        raise ValueError(f'Unknown creature action: {action.name}')
    u = (t - action.start) / action.seconds
    if action.name == 'sleep':
        # Sleep is a held state, with a short, continuous wake when another cue
        # starts. Its posture is categorical; intensity scales breathing only.
        settled = smooth(u / .75)
        if until is not None:
            settled *= 1. - smooth((t - until) / .6)
        breath = math.sin(math.tau * .20 * (t - action.start))
        return Pose(sleep=settled, blink=settled, ears=18 * settled,
                    head_pitch=12 * settled, breath=.045 * breath * settled * min(1., max(.5, action.intensity)))
    if not 0. < u < 1.:
        return Pose()
    w, hit = window(u), strike(u)
    p = Pose()
    name = action.name
    if name == 'roar':
        down = math.sin(math.pi * u / .20) if u < .20 else 0.
        back = window((u - .12) / .24, .35, .55)
        roar = window((u - .25) / .75, .22, .47)
        delayed = window((u - .29) / .71, .22, .47)
        bounce = shake((u - .35) / .65, 3) * 6
        impact = window((u - .38) / .16, .12, .25)
        p = Pose(jaw=.98 * roar, head_x=26 * roar - 15 * back, head_y=20 * down - 18 * back - 10 * roar,
                 head_pitch=12 * down - 20 * back - 12 * roar, dx=6 * roar, lean=18 * roar,
                 squash=-.045 * roar, mane=18 * roar + bounce, mane_lag=12 * (delayed - roar) + bounce,
                 sound=roar, sound_expand=u * w, fierce=roar, ears=-12 * roar, screen_shake=5 * impact)
    elif name == 'tremble':
        # A whole-body shiver. 16 cycles per cue is ~7 Hz (about four video frames a cycle at 30 fps), and the
        # preview's eight samples (0.14 of the cue apart) advance 0.24 of a cycle each, so no sample pair aliases.
        shiver = math.sin(2. * math.pi * TREMBLE_CYCLES * u)
        p = Pose(dx=13. * shiver * w, dy=-3.5 * abs(shiver) * w, squash=.05 * math.sin(2. * math.pi * TREMBLE_CYCLES * u + 1.2) * w,
                 head_x=-4 * w, head_y=7 * w, head_pitch=6 * w, ears=60 * w + 14 * shiver * w,
                 worry=w, crouch=14 * w, lean=-3 * w, legs=(4 * shiver * w, -4 * shiver * w, -4 * shiver * w, 4 * shiver * w))
    elif name == 'whimper':
        # Head dips and the ears go back; the closed-mouth whimper marks pulse (about 2.3 Hz) over a small shiver.
        pulse = .5 + .5 * math.sin(2. * math.pi * 5. * u - math.pi / 2)
        p = Pose(dx=3.6 * math.sin(2. * math.pi * 11. * u) * w, head_y=22 * w - 10 * pulse * w, head_pitch=20 * w + 12 * pulse * w,
                 head_x=-5 * w, squash=.1 * w, ears=80 * w, sound=-w * (.25 + .75 * pulse),
                 worry=w, crouch=16 * w)
    elif name == 'nudge':
        lower = window(u, .30, .58)
        push = window((u - .28) / .72, .35, .45)
        p = Pose(head_x=13 * lower + 16 * push, head_y=68 * lower, head_pitch=30 * lower,
                 dx=3 * push, lean=5 * push, mane_lag=5 * shake(u, 3), crouch=9 * lower)
    elif name == 'laugh':
        bounce = abs(math.sin(2 * math.pi * 4 * u)) * w
        p = Pose(dy=-11 * bounce, squash=.07 * shake(u, 8), head_pitch=-38 * w,
                 head_x=-9 * w, head_y=-16 * w, jaw=.84 * w * (.75 + .25 * bounce),
                 cackle=w, ears=-12 * w)
    elif name == 'swipe':
        p = Pose(legs=(0., 0., 0., -95 * hit), knees=(0., 0., 0., -25 * w),
                 head_x=5 * hit, squash=.04 * hit, swipe=hit, mane=4 * shake(u, 5))
    elif name in ('walk', 'run'):
        phi = 2 * math.pi * (t - action.start) * (1.3 if name == 'walk' else 2.2)
        phases = (0., math.pi, math.pi, 0.)
        amplitude = 36 if name == 'walk' else 48
        legs = tuple(amplitude * math.sin(phi + ph) * w for ph in phases)
        knees = tuple(-(46 if name == 'walk' else 58) * max(0., math.cos(phi + ph)) * w for ph in phases)
        p = Pose(legs=legs, knees=knees, arms=(-legs[0], -legs[1]),
                 dy=-(7 if name == 'walk' else 11) * (.5 + .5 * math.cos(2 * phi)) * w,
                 head_y=(4 if name == 'walk' else 2) * math.sin(phi) * w, head_pitch=3 * math.sin(phi) * w,
                 lean=(3 if name == 'walk' else 9) * w, squash=.025 * math.sin(2 * phi) * w)
    elif name == 'sit':
        p = Pose(crouch=30 * w, head_y=-7 * w, legs=(65 * w, 65 * w, -8 * w, -8 * w),
                 knees=(-65 * w, -65 * w, 0., 0.))
    elif name == 'look':
        p = Pose(head_pitch=-18 * w, head_y=-5 * w, look=7 * w, ears=-12 * w)
    elif name == 'pounce':
        p = Pose(dx=30 * hit, dy=-28 * max(0., hit), squash=.18 * min(0., -hit),
                 crouch=12 * w * (1 - max(0., hit)), legs=(35 * hit, 30 * hit, -45 * hit, -35 * hit),
                 head_pitch=-10 * hit, tail=15 * hit)
    elif name == 'hide':
        # Drop fast (first quarter), hold flat with a faint shiver, then rise. The head turns in and down, the ears
        # lie flat and the body folds low and back.
        hold = window(u, .24, .80)
        p = Pose(crouch=34 * hold, squash=.11 * hold, head_y=30 * hold, head_x=-26 * hold, head_pitch=34 * hold,
                 ears=85 * hold, worry=hold, lean=-9 * hold, dx=-1.6 * math.sin(2. * math.pi * 9. * u) * hold,
                 legs=(34 * hold, 34 * hold, -26 * hold, -26 * hold), knees=(-30 * hold, -30 * hold, -20 * hold, -20 * hold))
    elif name == 'breathe_heavy':
        breath = math.sin(2 * math.pi * .85 * (t - action.start))
        p = Pose(breath=.10 * breath * w, head_y=4 * breath * w, jaw=.25 * w,
                 puffs=max(0., -breath) * w, ears=5 * w)
    strength = min(2., max(0., action.intensity))
    return add(blend(Pose(), p, min(1., strength)), blend(Pose(), p, max(0., strength - 1.)))


def cue_pose(action: Action, cues: list[Action], t: float) -> Pose:
    """Evaluate a cue against its actor's following cues, independent of frame order."""
    following = [a.start for a in cues if a.start > action.start]
    return action_pose(action, t, until=min(following) if following else None)


def travel_x(action: Action | str, t: float) -> float:
    """Distance a walk/run cue has carried the character by time t (rig units; multiply by genome size).

    Eases in and out with the gait envelope and then holds, so the character does not snap back at the cue's end.
    """
    action = Action(action) if isinstance(action, str) else action
    if action.name not in TRAVEL:
        return 0.
    u = (t - action.start) / action.seconds
    return TRAVEL[action.name] * smooth(u) * min(2., max(0., action.intensity))


def target_response(action: Action | str, t: float) -> Pose:
    """A nudge receiver recoils and settles; apply to the target, not the nudging actor."""
    action = Action(action) if isinstance(action, str) else action
    u = (t - action.start) / action.seconds
    if action.name != 'nudge' or not .40 < u < 1.:
        return Pose()
    elapsed = (u - .40) * action.seconds
    spring = math.exp(-3.8 * elapsed) * math.sin(12. * elapsed) * window(u, .05, .72)
    return Pose(dx=13 * spring * action.intensity, lean=9 * spring * action.intensity,
                head_pitch=18 * spring * action.intensity, squash=.04 * spring, tail=8 * spring)

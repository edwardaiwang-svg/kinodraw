"""Seeded life evaluated from shot time; no mutable simulation state or worker seams."""
import math

from .actions import Action, Pose, action_pose, add
from .genes import Genome


def blink_times(genome: Genome, until: float) -> list[float]:
    rng = genome.stream('motion:blinks')
    times, t = [], rng.uniform(3., 6.)
    while t <= until + .25:
        times.append(t)
        t += rng.uniform(3., 6.)
    return times


def idle_pose(genome: Genome, t: float) -> Pose:
    t = max(0., t)
    rng = genome.stream('motion')
    phase, twitch_phase = rng.uniform(0., 2 * math.pi), rng.uniform(0., 2 * math.pi)
    breath = .025 * math.sin(2 * math.pi * .25 * t + phase)
    blink = 0.
    for start in blink_times(genome, t):
        u = t - start
        if 0. <= u < .06:
            blink = u / .06
        elif .06 <= u < .1:
            blink = 1.
        elif .1 <= u < .2:
            blink = 1. - (u - .1) / .1
    fidget = math.sin(2 * math.pi * t / 7.5 + phase)
    twitch = max(0., math.sin(2 * math.pi * t / 4.7 + twitch_phase)) ** 18
    energy = .6 if genome.temperament == 'shy' else 1.4 if genome.temperament == 'playful' else 1.
    return Pose(breath=breath, blink=blink, dx=1.4 * fidget * energy, head_pitch=1.2 * fidget,
                ears=7 * twitch, tail=9 * math.sin(2 * math.pi * .3 * t + phase),
                legs=(1.4 * fidget, -1.4 * fidget, .8 * fidget, -.8 * fidget))


def pose_at(genome: Genome, action: Action | str | Pose | list[Action], t: float) -> Pose:
    p = idle_pose(genome, t)
    if isinstance(action, Pose):
        return add(p, action)
    # Overlapping cues add their continuous envelope channels, never swap geometry.
    for cue in action if isinstance(action, (list, tuple)) else [action]:
        p = add(p, action_pose(cue, t))
    return p

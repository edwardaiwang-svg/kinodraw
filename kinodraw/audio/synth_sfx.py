"""Deterministic procedural creature, weather, animation and everyday (foley) effects.

KINDS maps each effect to its preview duration in seconds. render returns a mono
float32 signal, fitted to an existing SFX kind's loudest-100-ms level and .7 peak.
The everyday kinds (audio.foley cues them from the narration's words and the plan's actions) are drawn to sound like
the thing itself, quiet and short, never a cartoon: weather, household, commerce, kitchen, crowd, vehicle and a
human laugh (hyena_cackle stays an animal's).
"""
from __future__ import annotations

import numpy as np
from scipy.signal import sawtooth

from .sfx import _band, _fit, _pink, _tone


KINDS = {'roar': 1.4, 'cub_roar': .55, 'whimper': .6, 'nudge': .18, 'hyena_cackle': .85,
         'swipe': .22, 'breath_puff': .3, 'wind': 3., 'rain': 3.,
         'fog_drone': 3., 'shooting_star': .8, 'type_tick': .07,
         'transition_whoosh': .6,
         'thunder': 2.8, 'lightning_crack': 1.1, 'door': .7, 'knock': .7, 'footsteps': 1.8, 'phone_buzz': .9,
         'notification': .6, 'typing': 1.4, 'drawer': .8, 'cash_register': 1.1, 'bell': 1.4, 'sizzle': 2.5,
         'pour': 1.4, 'whisk': 1.5, 'cheer': 2.4, 'applause': 3., 'murmur': 3., 'car': 2.2, 'bus': 3.,
         'laugh': 1.1, 'clock_tick': 3.}
# The action sounds' levels put each one's loudest 400 ms about 12 LU under the narration's once the mix ducks it
# (measured on a real narration): short sounds need a louder 100 ms level than long ones.
LEVEL_KIND = {'roar': 'stamp', 'cub_roar': 'pop', 'whimper': 'pop', 'nudge': 'impact',
              'hyena_cackle': 'pop', 'swipe': 'impact', 'breath_puff': 'impact',
              'wind': 'write', 'rain': 'write', 'fog_drone': 'write',
              'shooting_star': 'confetti', 'type_tick': 'type',
              'transition_whoosh': 'whoosh',
              # The everyday sounds sit quieter, 12-18 LU under the narration (measured the same way): heard, subtle.
              'thunder': 'cut', 'lightning_crack': 'stamp', 'door': 'tape', 'knock': 'paper',
              'footsteps': 'pop', 'phone_buzz': 'paper', 'notification': 'paper', 'typing': 'paper',
              'drawer': 'paper', 'cash_register': 'paper', 'bell': 'paper', 'sizzle': 'write', 'pour': 'letter',
              'whisk': 'letter', 'cheer': 'paper', 'applause': 'paper', 'murmur': 'write', 'car': 'paper',
              'bus': 'letter', 'laugh': 'paper', 'clock_tick': 'paper'}
# Played from t for their length (a texture or a sequence), with 40 ms fades at both ends.
BEDS = ('wind', 'rain', 'fog_drone', 'footsteps', 'typing', 'sizzle', 'pour', 'whisk', 'cheer', 'applause', 'murmur',
        'car', 'bus', 'laugh', 'drawer', 'cash_register', 'clock_tick')


def _filtered(x, lo, hi, sr):
    """Keep the noise bands below Nyquist when previewing at a lower rate."""
    hi = min(hi, .45 * sr)
    return _band(x, min(lo, hi / 2), hi, sr)


def _unit(x):
    peak = np.abs(x).max()
    return x / peak if peak else x


def _whoosh(rng, u, sr, fast=False):
    noise = _pink(rng, len(u))
    low = _unit(_filtered(noise, 160, 1000, sr))
    high = _unit(_filtered(noise, 1400, 7000, sr))
    if fast:
        env = np.minimum(1, u / .045) * (1 - u) ** 2
        bright = np.exp(-u * 3)
    else:
        env = np.sin(np.pi * u) ** 2
        bright = np.sin(np.pi * u) ** 2
    return ((1 - bright) * low + bright * high) * env


def _recipe(kind, rng, t, u, sr):
    n = len(t)
    if kind == 'roar':
        freq = (55 + 110 * (1 - u) ** 2) * (1 + .045 * np.sin(2 * np.pi * 23 * t))
        growl = _unit(_filtered(sawtooth(2 * np.pi * np.cumsum(freq) / sr), 35, 1800, sr))
        noise = _unit(_filtered(rng.standard_normal(n), 160, 2800, sr))
        env = np.minimum(1, u / .07) * (1 - u) ** .7
        return (growl + .65 * noise) * env * (1 + .18 * np.sin(2 * np.pi * 31 * t))
    if kind == 'cub_roar':
        # A cub's try at a roar: a short, high growl that cracks into a squeak.
        crack = np.clip((u - .4) / .12, 0, 1)
        freq = (280 + 110 * np.sin(np.pi * u)) * (1 + .035 * np.sin(2 * np.pi * 19 * t))
        growl = _unit(_filtered(sawtooth(2 * np.pi * np.cumsum(freq) / sr), 260, 4200, sr))
        squeak = _tone(np.minimum(950 + 650 * u, .4 * sr), sr) + .3 * _tone(np.minimum(1900 + 1300 * u, .4 * sr), sr)
        breath = _unit(_filtered(rng.standard_normal(n), 700, 4500, sr))
        env = np.minimum(1, u / .05) * (1 - u) ** .9
        return ((1 - .75 * crack) * growl + .8 * crack * squeak + .25 * breath) * env
    if kind == 'whimper':
        freq = (520 + 240 * np.sin(np.pi * u) - 170 * u) * (1 + .045 * np.sin(2 * np.pi * 7 * t))
        tone = _tone(freq, sr) + .22 * _tone(2 * freq, sr)
        return tone * np.sin(np.pi * u) ** .8
    if kind == 'nudge':
        tone = _tone(65 + 70 * np.exp(-u * 16), sr)
        noise = _unit(_filtered(rng.standard_normal(n), 80, 700, sr))
        return (tone + .25 * noise) * np.exp(-u * 8)
    if kind == 'hyena_cackle':
        x = np.zeros(n)
        # Uneven, ascending/descending yelps with audible gaps between bursts.
        for start in np.arange(.02, .92, .115):
            local = (u - start) / .085
            env = np.where((local >= 0) & (local <= 1), np.sin(np.pi * np.clip(local, 0, 1)) ** 2, 0)
            base = rng.uniform(390, 700)
            freq = base * (1.15 - .35 * np.clip(local, 0, 1))
            x += (_tone(freq, sr) + .4 * _tone(2 * freq, sr) + .18 * _tone(3 * freq, sr)) * env
        return x
    if kind in ('swipe', 'transition_whoosh'):
        return _whoosh(rng, u, sr, fast=kind == 'swipe')
    if kind == 'breath_puff':
        noise = _unit(_filtered(rng.standard_normal(n), 250, 3300, sr))
        return noise * np.minimum(1, u / .08) * np.exp(-u * 5) * (1 - u)
    if kind == 'wind':
        noise = _unit(_filtered(_pink(rng, n), 55, 1800, sr))
        gust = .55 + .25 * np.sin(2 * np.pi * .43 * t + rng.uniform(0, 2 * np.pi))
        gust += .15 * np.sin(2 * np.pi * .17 * t)
        return noise * gust
    if kind == 'rain':
        bed = _unit(_filtered(rng.standard_normal(n), 800, 10000, sr))
        drops = rng.standard_normal(n) * (rng.random(n) < min(1, 65 / sr))
        drops = _unit(_filtered(drops, 1800, 11000, sr))
        return bed + .35 * drops
    if kind == 'fog_drone':
        base = rng.uniform(57, 64)
        x = _tone(np.full(n, base), sr) + .45 * _tone(np.full(n, base * 1.007), sr)
        x += .25 * _tone(np.full(n, base * 2.003), sr)
        return x * (.8 + .2 * np.sin(2 * np.pi * .23 * t))
    if kind == 'shooting_star':
        freq = 1100 * 3 ** u
        x = np.zeros(n)
        for harmonic, amplitude in ((1, 1), (1.5, .5), (2, .35), (2.73, .22)):
            # Omit partials above the usable band at lower sample rates.
            partial = _tone(np.minimum(freq * harmonic, .4 * sr), sr)
            x += amplitude * partial * (.65 + .35 * np.sin(2 * np.pi * (9 + harmonic * 3) * t))
        return x * np.minimum(1, u / .08) * (1 - u) ** 1.5
    if kind == 'type_tick':
        click = _unit(_filtered(rng.standard_normal(n), 1800, 8000, sr))
        body = _tone(np.full(n, rng.uniform(170, 260)), sr)
        ping = _tone(np.full(n, min(2900, .35 * sr)), sr)
        return click * np.exp(-u * 38) + .45 * body * np.exp(-u * 6) + .2 * ping * np.exp(-u * 9)
    if kind in FOLEY:
        return FOLEY[kind](rng, t, u, sr)
    raise ValueError(f'Unknown SFX kind: {kind!r}')


# ------------------------------------------------------------------ everyday sounds (foley)
def _decay(t, tau, at=0.):
    """0 before at, then exp(-(t - at) / tau)."""
    return np.where(t >= at, np.exp(-np.maximum(t - at, 0) / tau), 0.)


def _burst(rng, t, at, tau, lo, hi, sr):
    """A band of noise struck at ``at`` seconds, dying away over tau."""
    return _unit(_filtered(rng.standard_normal(len(t)), lo, hi, sr)) * _decay(t, tau, at)


def _strikes(rng, n, sr, times, length, lo, hi, amps=None):
    """Short noise grains (length seconds, sharp attack) at the given times, band-passed together."""
    x = np.zeros(n)
    m = max(8, int(length * sr))
    shape = np.exp(-np.arange(m) / (m / 5))
    for k, at in enumerate(times):
        i = int(at * sr)
        if 0 <= i < n:
            seg = min(m, n - i)
            x[i:i + seg] += rng.standard_normal(seg) * shape[:seg] * (1 if amps is None else amps[k])
    return _filtered(x, lo, hi, sr)


def _voices(rng, t, sr, count, lo, hi, formants, syllable=None):
    """count voiced buzzes (pitch lo..hi Hz, a little vibrato) through vowel formants; with syllable (Hz) each
    voice comes and goes in syllables, as chatter does."""
    n, out = len(t), np.zeros(len(t))
    for v in range(count):
        f0 = rng.uniform(lo, hi) * (1 + .02 * np.sin(2 * np.pi * rng.uniform(4, 6) * t + rng.uniform(0, 6)))
        buzz = sawtooth(2 * np.pi * np.cumsum(f0) / sr)
        if syllable:
            rate = rng.uniform(.7, 1.3) * syllable
            buzz *= np.clip(np.sin(2 * np.pi * rate * t + rng.uniform(0, 6)), 0, 1) ** 2
        out += buzz * rng.uniform(.5, 1)
    return sum(_unit(_filtered(out, f / 1.25, f * 1.25, sr)) * g for f, g in formants)


def _thunder(rng, t, u, sr):
    """A near crack, then a low rolling rumble that swells two or three times and fades."""
    rumble = _unit(_filtered(np.cumsum(rng.standard_normal(len(t))), 28, 240, sr))
    roll = .45 + sum(rng.uniform(.4, 1) * np.exp(-.5 * ((t - rng.uniform(.15, .55) * t[-1]) / rng.uniform(.12, .3)) ** 2)
                     for _ in range(3))
    crack = _burst(rng, t, 0, .05, 250, 5000, sr)
    return .55 * crack + rumble * roll * np.minimum(1, u / .03) * (1 - u) ** 1.6


def _lightning_crack(rng, t, u, sr):
    """A sharp electric snap tearing for 200 ms, over a short low boom."""
    snap = _burst(rng, t, 0, .006, 900, 9000, sr)
    tear = _strikes(rng, len(t), sr, np.sort(rng.uniform(0, .22, 70) ** 1.5 / .22 ** .5), .004, 1500, 9000,
                    rng.uniform(.3, 1, 70)) * _decay(t, .12)
    boom = _unit(_filtered(np.cumsum(rng.standard_normal(len(t))), 30, 260, sr)) * np.minimum(1, u / .02) * _decay(t, .3)
    return snap + .8 * _unit(tear) + .7 * boom


def _door(rng, t, u, sr):
    """A latch click, the door closing on its frame (a woody thud) and the latch settling."""
    latch = _burst(rng, t, 0, .004, 1800, 7000, sr)
    thud = _tone(70 + 50 * np.exp(-np.maximum(t - .05, 0) / .03), sr) * _decay(t, .09, .05)
    wood = _burst(rng, t, .05, .05, 90, 900, sr)
    return latch + .9 * thud + .6 * wood + .3 * _burst(rng, t, .14, .003, 2000, 6000, sr)


def _knock(rng, t, u, sr):
    """Three knuckle knocks on a wooden door."""
    x = np.zeros(len(t))
    for k, at in enumerate((0, .17 + rng.uniform(-.02, .02), .34 + rng.uniform(-.02, .02))):
        x += (1 - .15 * k) * (_tone(np.full(len(t), rng.uniform(170, 230)), sr) * _decay(t, .03, at)
                              + .7 * _burst(rng, t, at, .012, 300, 2500, sr))
    return x


def _footsteps(rng, t, u, sr):
    """Steps about every half second: a heel thump, then the sole's soft scuff."""
    x, at, k = np.zeros(len(t)), .02, 0
    while at < t[-1] - .1:
        g = (1 if k % 2 else .8) * rng.uniform(.8, 1)
        x += g * (_burst(rng, t, at, .025, 60, 500, sr) + .35 * _burst(rng, t, at + .05, .03, 900, 4000, sr))
        at, k = at + rng.uniform(.46, .56), k + 1
    return x


def _phone_buzz(rng, t, u, sr):
    """A phone vibrating on a table: two buzzes with a rattle."""
    f = rng.uniform(150, 190)
    gate = ((t < .32) | ((t > .47) & (t < .79))).astype(float)
    gate = np.convolve(gate, np.ones(int(.008 * sr)) / int(.008 * sr), 'same')
    buzz = _unit(_filtered(sawtooth(2 * np.pi * f * t), 100, 1600, sr))
    return buzz * gate * (1 + .3 * np.sin(2 * np.pi * 2 * f * t))


def _notification(rng, t, u, sr):
    """A soft two-note chime: the phone's message sound."""
    base = rng.choice([880., 988., 1047.])
    x = np.zeros(len(t))
    for at, f in ((0, base), (.12, base * 1.5)):
        x += (_tone(np.full(len(t), f), sr) + .2 * _tone(np.full(len(t), 2 * f), sr)) * _decay(t, .16, at) * \
            np.minimum(1, np.maximum(t - at, 0) / .004)
    return x


def _typing(rng, t, u, sr):
    """Keys pressed at an uneven typing pace, now and then the space bar."""
    times = .01 + np.r_[0, np.cumsum(rng.uniform(.07, .17, int(t[-1] / .07) + 1))]
    times = times[times < t[-1] - .03]
    space = rng.random(len(times)) < .18
    x = _strikes(rng, len(t), sr, times, .012, 1800, 7000, rng.uniform(.6, 1, len(times)))
    return _unit(x) + .35 * _unit(_strikes(rng, len(t), sr, times[space], .02, 200, 1500))


def _drawer(rng, t, u, sr):
    """A drawer sliding on its runners, then stopping with a thunk."""
    slide = _unit(_filtered(rng.standard_normal(len(t)), 300, 2500, sr))
    rough = .6 + .4 * np.abs(np.sin(2 * np.pi * rng.uniform(25, 40) * t))
    swell = np.clip(t / .08, 0, 1) * (t < .45) + (t >= .45) * np.exp(-np.maximum(t - .45, 0) / .01)
    thunk = _tone(np.full(len(t), rng.uniform(100, 130)), sr) * _decay(t, .05, .45) + _burst(rng, t, .45, .03, 200, 1600, sr)
    return .5 * slide * rough * swell + thunk


def _cash_register(rng, t, u, sr):
    """A till: the key's clunk, the drawer rolling out and the bell's 'ching'."""
    clunk = _burst(rng, t, 0, .02, 150, 2000, sr) + .5 * _burst(rng, t, 0, .003, 2500, 8000, sr)
    roll = _unit(_filtered(rng.standard_normal(len(t)), 400, 3000, sr)) * ((t > .05) & (t < .3)) * .25
    f = rng.uniform(2000, 2300)
    ching = sum(a * _tone(np.full(len(t), f * h), sr) for h, a in ((1, 1), (2.41, .5), (3.89, .3), (5.2, .15)))
    return clunk + roll + .8 * ching * _decay(t, .35, .22) * np.minimum(1, np.maximum(t - .22, 0) / .002)


def _bell(rng, t, u, sr):
    """A small shop bell (or a kitchen timer's ding): bright inharmonic partials ringing out."""
    f = rng.uniform(1300, 1700)
    x = sum(a * _tone(np.full(len(t), min(f * h, .45 * sr)), sr) * np.exp(-t / (.5 / h ** .5))
            for h, a in ((1, 1), (2.76, .45), (5.4, .2), (8.93, .08)))
    return x * np.minimum(1, t / .002) * (1 + .1 * np.sin(2 * np.pi * 4 * t))


def _sizzle(rng, t, u, sr):
    """Something frying: a high hiss with fat popping in it."""
    hiss = _unit(_filtered(rng.standard_normal(len(t)), 3500, 11000, sr)) * (.6 + .2 * np.sin(2 * np.pi * .7 * t))
    pops = np.sort(rng.uniform(0, t[-1], int(70 * t[-1])))
    return .5 * hiss + _unit(_strikes(rng, len(t), sr, pops, .004, 2500, 10000, rng.uniform(.2, 1, len(pops))))


def _pour(rng, t, u, sr):
    """Liquid poured into a cup: a stream and bubbles whose pitch rises as it fills."""
    stream = _unit(_filtered(rng.standard_normal(len(t)), 300, 2500, sr)) * .35
    x = np.zeros(len(t))
    for at in np.sort(rng.uniform(.03, t[-1] - .05, int(45 * t[-1]))):
        m = int(rng.uniform(.01, .025) * sr)
        i = int(at * sr)
        seg = min(m, len(t) - i)
        f0 = rng.uniform(350, 650) * (1 + 1.2 * at / t[-1])
        k = np.arange(seg) / sr
        x[i:i + seg] += np.sin(2 * np.pi * f0 * (k + 2 * k * k / .025)) * np.exp(-k / .006) * rng.uniform(.3, 1)
    return (stream + _unit(x)) * np.minimum(1, u / .05)


def _whisk(rng, t, u, sr):
    """A whisk beating in a bowl: quick scrapes with small metal ticks."""
    rate = rng.uniform(5, 6.5)
    stroke = np.sin(np.pi * ((t * rate) % 1)) ** 4
    scrape = _unit(_filtered(rng.standard_normal(len(t)), 2000, 8000, sr)) * stroke
    ticks = np.arange(0, t[-1], 1 / rate) + rng.uniform(0, .02)
    return scrape + .5 * _unit(_strikes(rng, len(t), sr, ticks, .003, 3500, 9000))


def _crowd(rng, t, sr, count, lo, hi, syllable):
    return _voices(rng, t, sr, count, lo, hi, ((rng.uniform(550, 750), 1), (rng.uniform(1100, 1500), .5),
                                                (rng.uniform(2300, 2800), .2)), syllable)


def _cheer(rng, t, u, sr):
    """A small crowd cheering: many voices rising together, a breath of noise under them, fading out."""
    voices = _unit(_crowd(rng, t, sr, 18, 170, 380, None))
    air = _unit(_filtered(rng.standard_normal(len(t)), 600, 4000, sr))
    return (voices + .4 * air) * np.minimum(1, u / .15) * (1 - u) ** 1.2


def _applause(rng, t, u, sr):
    """Applause: many hands clapping out of step, swelling in and dying away."""
    count = int(90 * t[-1])
    times = np.sort(rng.uniform(0, t[-1], count))
    x = _strikes(rng, len(t), sr, times, .012, 700, 5000, rng.uniform(.3, 1, count))
    return _unit(x) * np.minimum(1, u / .1) * np.where(u > .6, ((1 - u) / .4) ** 1.5, 1)


def _murmur(rng, t, u, sr):
    """A room of people talking low: voices in syllables, too blurred to understand."""
    return _unit(_filtered(_crowd(rng, t, sr, 10, 110, 240, 4.5), 150, 3000, sr))


def _engine(rng, t, sr, f0, harmonics, top):
    phase = 2 * np.pi * np.cumsum(f0) / sr
    tone = sum(np.sin(h * phase + rng.uniform(0, 6)) / h for h in range(1, harmonics + 1))
    return _unit(_filtered(tone + .3 * rng.standard_normal(len(t)), 25, top, sr))


def _car(rng, t, u, sr):
    """A car passing by: engine and tyres rising, pitch dropping as it passes, then gone."""
    mid, w = rng.uniform(.4, .6) * t[-1], rng.uniform(.25, .4)
    f0 = rng.uniform(38, 48) * (1 + .06 * -np.tanh((t - mid) / w))
    tyres = _unit(_filtered(_pink(rng, len(t)), 200, 2500, sr))
    return (_engine(rng, t, sr, f0, 8, 1400) + .6 * tyres) / (1 + ((t - mid) / w) ** 2)


def _bus(rng, t, u, sr):
    """A bus pulling in: a heavy diesel rumble and the air brakes' hiss."""
    f0 = rng.uniform(26, 32) * (1 - .15 * u)
    engine = _engine(rng, t, sr, f0, 10, 900) * np.minimum(1, u / .15) * (1 - .4 * u)
    at = .55 * t[-1]
    hiss = _unit(_filtered(rng.standard_normal(len(t)), 2000, 8000, sr)) * np.minimum(1, np.maximum(t - at, 0) / .02) * \
        _decay(t, .25, at)
    return engine + .6 * hiss


def _laugh(rng, t, u, sr):
    """A person laughing softly: four to six breathy 'ha's, falling in pitch and fading (a human voice, never a
    cartoon yelp)."""
    x, at, k = np.zeros(len(t)), .02, 0
    f_start = rng.uniform(150, 240)
    f1, f2 = rng.uniform(650, 800), rng.uniform(1100, 1300)
    while at < t[-1] - .15 and k < 6:
        length = rng.uniform(.09, .14)
        local = np.clip((t - at) / length, 0, 1)
        env = np.where((t >= at) & (t <= at + length), np.sin(np.pi * local) ** 1.5, 0) * (1 - .12 * k)
        f0 = f_start * (1 - .05 * k) * (1.04 - .08 * local)
        voiced = sawtooth(2 * np.pi * np.cumsum(f0) / sr)
        breath = rng.standard_normal(len(t)) * np.where((t >= at) & (t < at + .03), 1, .25)
        x += (voiced + .5 * breath) * env
        at, k = at + length + rng.uniform(.05, .08), k + 1
    return _unit(_filtered(x, f1 / 1.4, f1 * 1.4, sr)) + .5 * _unit(_filtered(x, f2 / 1.25, f2 * 1.25, sr))


def _clock_tick(rng, t, u, sr):
    """A clock (or a stopwatch) ticking: a tick, then half a second later a slightly lower tock."""
    x = np.zeros(len(t))
    for k, at in enumerate(np.arange(.02, t[-1] - .05, .5)):
        f = 3200 if k % 2 == 0 else 2600
        x += (_tone(np.full(len(t), f), sr) * _decay(t, .006, at) + _burst(rng, t, at, .003, 1500, 7000, sr)) * \
            (1 if k % 2 == 0 else .7)
    return x


FOLEY = {'clock_tick': _clock_tick, 'thunder': _thunder, 'lightning_crack': _lightning_crack, 'door': _door, 'knock': _knock,
         'footsteps': _footsteps, 'phone_buzz': _phone_buzz, 'notification': _notification, 'typing': _typing,
         'drawer': _drawer, 'cash_register': _cash_register, 'bell': _bell, 'sizzle': _sizzle, 'pour': _pour,
         'whisk': _whisk, 'cheer': _cheer, 'applause': _applause, 'murmur': _murmur, 'car': _car, 'bus': _bus,
         'laugh': _laugh}


def render(kind, duration=None, sr=48000, seed=20260927) -> np.ndarray:
    """Render one effect; duration overrides its default without changing pitch.

    Duration must contain at least two samples. Beds fade for 40 ms at each end;
    discrete hits fade for 1 ms on entry and 10 ms on exit, before level fitting.
    """
    if kind not in KINDS:
        raise ValueError(f'Unknown SFX kind: {kind!r}')
    if not isinstance(sr, (int, np.integer)) or sr < 1000:
        raise ValueError('sr must be an integer of at least 1000 Hz')
    seconds = KINDS[kind] if duration is None else float(duration)
    if not np.isfinite(seconds) or seconds * sr < 2:
        raise ValueError('duration must be finite and contain at least two samples')
    n = int(seconds * sr)
    t = np.arange(n) / sr
    u = np.linspace(0, 1, n)
    x = _recipe(kind, np.random.default_rng(seed), t, u, sr)
    bed = kind in BEDS
    attack = min(n // 2, max(2, int((.04 if bed else .001) * sr)))
    release = min(n // 2, max(2, int((.04 if bed else .01) * sr)))
    x[:attack] *= np.linspace(0, 1, attack)
    x[-release:] *= np.linspace(1, 0, release)
    x[0] = x[-1] = 0
    return _fit(x, LEVEL_KIND[kind], sr) if np.any(x) else x.astype(np.float32)

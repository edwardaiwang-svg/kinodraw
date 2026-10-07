"""Sound effects for the animated looks: the renderer's cue list as one stereo bus.

A cue is {t, kind, strength (0..1, default 1), id, dur (write and riser), x (0..1 across the screen)}. It plays one
hit from its kind's bank, NumPy recipes plus the bundled CC0 samples (assets/sfx/<kind>_<n>.wav), or a creature or
animation sound made by synth_sfx (roar, whimper, ...: its KINDS) with a seed drawn per cue. The variant,
±3 semitones of pitch and ±3 dB of gain come from (seed, id) alone, so a video always sounds the same.
Contact frames: a hit's transient peak lands on round(t * sr); a whoosh peaks on t and a riser builds up to t over
dur (1.2 s by default); write scribbles from t for dur. A hit less than 60 ms (35 ms for letter and type) after the
last one of its kind is dropped.
"""
from __future__ import annotations

import hashlib
import wave
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.signal import butter, firwin, lfilter, resample_poly, sosfilt

from .master import kweighting

SAMPLES = Path(__file__).resolve().parents[1] / 'assets' / 'sfx'
SAMPLE_RATE = 48000       # the bundled samples
LEVEL = {'pop': -21, 'slam': -18, 'letter': -27, 'type': -25, 'tape': -22, 'stamp': -19, 'whoosh': -23,
         'riser': -23, 'impact': -17, 'cut': -22, 'confetti': -23, 'tap': -23, 'paper': -24, 'write': -30,
         'kick': -18}     # loudness of a full-strength hit's loudest 100 ms (K-weighted), LUFS
SPACING = {'letter': .035, 'type': .035}
MIN_SPACING = .06
SPREAD = .6               # x = 0 (or 1) pans 60% of the way to the left (or right)
ATTACK = .05              # a hit's transient peak is in its first 50 ms
VARIANTS = 3              # synthesized per kind


# ------------------------------------------------------------------ recipes
def _time(seconds, sr):
    return np.arange(int(seconds * sr)) / sr


def _band(x, lo, hi, sr):
    return sosfilt(butter(2, [lo, min(hi, .45 * sr)], 'bandpass', fs=sr, output='sos'), x)


def _tone(freq, sr):
    """A sine that follows freq (Hz, one value per sample)."""
    return np.sin(2 * np.pi * np.cumsum(freq) / sr)


def _unit(x):
    return x / np.abs(x).max()


def _pink(rng, n):
    return lfilter([.049922035, -.095993537, .050612699, -.004408786], [1, -2.494956002, 2.017265875, -.5221894],
                   rng.standard_normal(n))


def _sweep(noise, centre, sr):
    """Noise through a band-pass whose centre follows centre (Hz per sample): overlapping bands, crossfaded."""
    out = np.zeros(len(noise))
    for fc in np.geomspace(250, 6000, 10):
        out += np.exp(-.5 * (np.log(centre / fc) / .35) ** 2) * _band(noise, fc / 1.3, fc * 1.3, sr)
    return out


def _crackle(rng, sr, seconds, count, lo, hi, short=.002, long=.01):
    """Randomly spaced noise bursts (paper, tape, confetti), denser early; the first one is at the start."""
    x = np.zeros(int(seconds * sr))
    for s in (np.r_[0, rng.uniform(0, 1, count - 1) ** 2] * (len(x) - 1)).astype(int):
        m = min(max(8, int(rng.uniform(short, long) * sr)), len(x) - s)
        x[s:s + m] += rng.standard_normal(m) * np.hanning(m) * (1 if s == 0 else rng.uniform(.2, .8))
    return _band(x, lo, hi, sr)


def pop(rng, sr):
    """500-900 Hz sine, pitch falling, gone in about 40 ms, over a 2 ms noise click."""
    t = _time(.09, sr)
    body = _tone(rng.uniform(500, 900) * (.55 + .45 * np.exp(-t / .015)), sr) * np.exp(-t / .013)
    return body + .35 * _unit(_band(rng.standard_normal(len(t)), 1500, 9000, sr) * np.exp(-t / .0007))


def kick(rng, sr):
    """Sine falling exponentially from about 150 Hz to 45 Hz over 250 ms."""
    t = _time(.25, sr)
    body = _tone(45 + (rng.uniform(135, 165) - 45) * np.exp(-t / .035), sr) * np.exp(-t / .08)
    return body + .15 * _unit(_band(rng.standard_normal(len(t)), 1000, 5000, sr) * np.exp(-t / .0008))


def impact(rng, sr):
    """Low sine thump under a noise burst."""
    t = _time(.5, sr)
    thump = _tone(45 + rng.uniform(55, 80) * np.exp(-t / .05), sr) * np.exp(-t / .14)
    return thump + .7 * _unit(_band(rng.standard_normal(len(t)), 150, 5000, sr) * np.exp(-t / .03))


def slam(rng, sr):
    """A card slapped down: broadband slap over a short low body."""
    t = _time(.35, sr)
    body = _tone(65 + rng.uniform(40, 70) * np.exp(-t / .03), sr) * np.exp(-t / .07)
    return _unit(_band(rng.standard_normal(len(t)), 300, 7000, sr) * np.exp(-t / .012)) + .8 * body


def stamp(rng, sr):
    """A rubber stamp: dull thud, a little tone, a paper click."""
    t = _time(.25, sr)
    noise = rng.standard_normal(len(t))
    thud = _unit(_band(noise, 80, 900, sr) * np.exp(-t / .025))
    tone = _tone(rng.uniform(95, 130) * (1 + .3 * np.exp(-t / .02)), sr) * np.exp(-t / .05)
    return .8 * thud + tone + .3 * _unit(_band(noise, 2000, 8000, sr) * np.exp(-t / .002))


def tap(rng, sr):
    """A fingertip on the board: short woody tone and click."""
    t = _time(.12, sr)
    tone = _tone(rng.uniform(500, 900) * (1 + .1 * np.exp(-t / .005)), sr) * np.exp(-t / .018)
    return .6 * tone + .6 * _unit(_band(rng.standard_normal(len(t)), 1200, 6000, sr) * np.exp(-t / .0015))


def type_(rng, sr):
    """A typewriter key: bright click, a low body and a small metal ping."""
    t = _time(.07, sr)
    click = _unit(_band(rng.standard_normal(len(t)), 1800, 8000, sr) * np.exp(-t / .0018))
    body = .45 * _tone(np.full(len(t), rng.uniform(170, 260)), sr) * np.exp(-t / .012)
    return click + body + .2 * _tone(np.full(len(t), rng.uniform(2500, 3500)), sr) * np.exp(-t / .008)


def letter(rng, sr):
    """A soft tick as a letter lands."""
    t = _time(.05, sr)
    click = _unit(_band(rng.standard_normal(len(t)), 900, 5000, sr) * np.exp(-t / .0025))
    return click + .3 * _tone(np.full(len(t), rng.uniform(1100, 1800)), sr) * np.exp(-t / .006)


def paper(rng, sr):
    """A rustle: randomly spaced 2-10 ms noise bursts, band-passed 2-8 kHz."""
    return _crackle(rng, sr, rng.uniform(.25, .4), int(rng.integers(10, 20)), 2000, 8000)


def tape(rng, sr):
    """A strip of tape torn off: dense short bursts fading out."""
    x = _crackle(rng, sr, rng.uniform(.3, .45), 120, 800, 9000, .001, .004)
    return x * np.linspace(1, .2, len(x))


def confetti(rng, sr):
    """A pop, then a spray of tiny bright ticks."""
    x = _crackle(rng, sr, .6, 45, 3000, 11000, .001, .003)
    p = pop(rng, sr)
    x[:len(p)] += .5 * _unit(p) * np.abs(x).max()
    return x


def whoosh(rng, sr):
    """Pink noise through a band-pass swept 300 Hz -> 3 kHz as it swells (300-600 ms), then back."""
    u = np.linspace(0, 1, int(rng.uniform(.3, .6) * sr))
    top = rng.uniform(.55, .7)
    env = np.where(u < top, u / top, (1 - u) / (1 - top)) ** 2
    return _sweep(_pink(rng, len(u)), 300 * 10 ** env, sr) * env


def cut(rng, sr):
    """A quick bright swish for a scene cut."""
    u = np.linspace(0, 1, int(rng.uniform(.18, .26) * sr))
    env = np.minimum(1, u / .08) * (1 - u) ** 2
    return _sweep(_pink(rng, len(u)), 800 * 7.5 ** env, sr) * env


def riser(rng, sr, seconds):
    """Filtered noise and a sine, both rising (two octaves) and swelling to the end."""
    u = np.linspace(0, 1, max(2, int(seconds * sr)))
    x = (_unit(_sweep(_pink(rng, len(u)), 400 * 10 ** u, sr)) + .35 * _tone(220 * 4 ** u, sr)) * u ** 2
    f = min(len(x), int(.005 * sr))
    x[-f:] *= np.linspace(1, 0, f)
    return x


def write(rng, sr, seconds):
    """A marker scribbling: strokes of band-passed noise with a slight squeak, pen lifts between them."""
    n = max(2, int(seconds * sr))
    env, pos = np.zeros(n), 0
    while pos < n:
        m = int(rng.uniform(.08, .25) * sr)
        env[pos:pos + m] = (np.sin(np.linspace(0, np.pi, m)) ** 2 * rng.uniform(.5, 1))[:n - pos]
        pos += m + int(rng.uniform(0, .06) * sr)
    noise = rng.standard_normal(n)
    squeak = rng.uniform(2500, 4000)
    return (_unit(_band(noise, 1500, 6000, sr)) + .4 * _unit(_band(noise, squeak / 1.05, squeak * 1.05, sr))) * env


RECIPES = {'pop': pop, 'slam': slam, 'letter': letter, 'type': type_, 'tape': tape, 'stamp': stamp,
           'whoosh': whoosh, 'impact': impact, 'cut': cut, 'confetti': confetti, 'tap': tap, 'paper': paper,
           'kick': kick}
LONG = {'riser': (riser, 1.2), 'write': (write, .5)}    # made for each cue, dur seconds long (default)


# ------------------------------------------------------------------ banks
def _fit(x, kind, sr) -> np.ndarray:
    """Scaled to the kind's LEVEL (its loudest 100 ms), peaks kept under -3 dBFS."""
    y = sosfilt(kweighting(sr), x)
    w = int(.1 * sr)
    energy = np.concatenate([[0.], np.cumsum(y * y)])
    loudest = (energy[w:] - energy[:-w]).max() if len(y) > w else energy[-1]
    gain = min(10 ** ((LEVEL[kind] + .691) / 20) / np.sqrt(loudest / w), .7 / np.abs(x).max())
    return (x * gain).astype(np.float32)


def _sample(path, sr) -> np.ndarray:
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float32) / 32768
    return x if sr == SAMPLE_RATE else resample_poly(x, sr, SAMPLE_RATE)


@lru_cache(maxsize=None)
def _bank(kind, sr) -> tuple:
    """VARIANTS synthesized (fixed seeds) plus the bundled samples of the kind, each at the kind's level."""
    made = [RECIPES[kind](np.random.default_rng([i, *kind.encode()]), sr) for i in range(VARIANTS)]
    made += [_sample(p, sr) for p in sorted(SAMPLES.glob(f'{kind}_*.wav'))]
    return tuple(_fit(x, kind, sr) for x in made)


@lru_cache(maxsize=None)
def _fir(up, down) -> np.ndarray:
    return firwin(20 * max(up, down) + 1, 1 / max(up, down), window=('kaiser', 5.0))   # as resample_poly designs it


def _repitch(x, semitones) -> np.ndarray:
    """Played faster or slower: semitones up (or down), shorter (or longer)."""
    r = Fraction(2 ** (-semitones / 12)).limit_denominator(64)
    return resample_poly(x, r.numerator, r.denominator, window=_fir(r.numerator, r.denominator)) if r != 1 else x


# ------------------------------------------------------------------ bus
def _rng(seed, cue_id):
    return np.random.default_rng(list(hashlib.sha256(f'{seed}:{cue_id}'.encode()).digest()))


def _hit(cue, rng, sr) -> tuple[np.ndarray, int]:
    """One cue's sound and the index of its sample that lands on t."""
    from . import synth_sfx                           # it builds on the recipes above
    kind = cue['kind']
    bank = _bank(kind, sr) if kind in RECIPES else None
    variant = int(rng.integers(len(bank))) if bank else 0
    semitones, db = rng.uniform(-3, 3), rng.uniform(-3, 3)
    if bank:
        x = bank[variant]
    elif kind in synth_sfx.KINDS:                     # a creature or animation sound, already at its level
        x = synth_sfx.render(kind, sr=sr, seed=int(rng.integers(1 << 32)))
    else:
        make, default = LONG[kind]
        x = _fit(make(rng, sr, float(cue.get('dur') or default) * 2 ** (semitones / 12)), kind, sr)
    x = _repitch(x, semitones) * (10 ** (db / 20) * min(1., max(0., float(cue.get('strength', 1)))))
    if kind == 'write':
        return x, 0
    head = x if kind in ('whoosh', 'riser') else x[:int(ATTACK * sr)]
    return x, int(np.argmax(np.abs(head)))


def render(cues, duration, sr=48000, seed=20260927) -> np.ndarray:
    """The cues as a stereo bus: float32, shape (round(duration * sr), 2). Unknown kinds are ignored."""
    from . import synth_sfx
    out = np.zeros((round(duration * sr), 2), np.float32)
    last = {}
    for cue in sorted(cues, key=lambda c: (float(c['t']), str(c.get('id', '')))):
        kind, t = cue['kind'], float(cue['t'])
        if (kind not in LEVEL and kind not in synth_sfx.KINDS
                or t - last.get(kind, -np.inf) < SPACING.get(kind, MIN_SPACING)):
            continue
        last[kind] = t
        x, anchor = _hit(cue, _rng(seed, cue.get('id', f'{kind}@{t}')), sr)
        start = round(t * sr) - anchor
        a, b = max(0, start), min(len(out), start + len(x))
        if a < b:
            pan = (.5 + (min(1., max(0., float(cue.get('x', .5)))) - .5) * SPREAD) * np.pi / 2
            out[a:b] += x[a - start:b - start, None] * np.array([np.cos(pan), np.sin(pan)], np.float32)
    return out

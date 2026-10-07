"""Procedural score: a deterministic, sample-free arrangement for a mood, a tempo and the story's shape.

Five synthesized parts play one chord per bar (two at fast tempos, which take a half-time feel):
- a struck lead (marimba, kalimba, celesta or vibraphone) by modal synthesis: decaying partials at the bar's or
  tine's mode ratios, the upper ones shorter and louder for harder strikes, playing a per-mood arpeggio pattern;
- a pad: two detuned band-limited wavetable voices per note (left and right), voice-led from chord to chord with
  attack/release envelopes, crossfaded from dark to bright with the energy;
- a round bass (four harmonics, attack/decay/sustain/release) on the chord roots;
- soft hand percussion: shaker, hand drum, woodblock tick, kick;
- a celesta guide line on the pad's top voice when the energy is high.
An energy curve (the mood's level) sets density, velocity and brightness. It rises into each intensity mark (a noise
riser, a hand-drum roll, a boom, a crash and a chord stab on the mark) and falls under tender lines. Each section
moves to the next progression and swaps the lead's timbre, entered by a short upward run. The last bars resolve to
the home chord. A synthetic stereo room (decaying, decorrelated noise, convolved) widens the mix.

compose() returns 48 kHz stereo float32 at an arbitrary level; score.render levels it like a recording. Every
random choice comes from a PCG64 generator seeded by the inputs, so equal inputs give equal bytes. No partial is
synthesized above 16 kHz (5 kHz in the 12 kHz pad), so nothing folds back.
"""
from __future__ import annotations

import re
import zlib
from functools import lru_cache

import numpy as np
from scipy.signal import butter, oaconvolve, resample_poly, sosfilt

SR = 48000
PAD_SR = 12000              # the pad is synthesized at a quarter rate (it is low-passed below 3 kHz), then upsampled
TABLE = 4096
TOP = 16000.                # no partial above this

DEGREES = {'I': 0, 'II': 2, 'III': 4, 'IV': 5, 'V': 7, 'VI': 9, 'VII': 11}
QUALITIES = {'': (0, 4, 7), 'm': (0, 3, 7), 'maj7': (0, 4, 7, 11), 'm7': (0, 3, 7, 10), '7': (0, 4, 7, 10),
             'add9': (0, 4, 7, 14), 'madd9': (0, 3, 7, 14), 'sus2': (0, 2, 7), 'sus4': (0, 5, 7)}

# Moods: score.py's, the recordings' tags and the v3 director's. Unknown moods play 'warm'.
MOODS = {'bright': 'bright', 'uplifting': 'bright', 'upbeat': 'bright', 'warm': 'warm', 'neutral': 'warm',
         'calm': 'calm', 'playful': 'playful', 'discovery': 'curious', 'curious': 'curious', 'adventure': 'curious',
         'mysterious': 'mysterious', 'tense': 'tense', 'somber': 'somber', 'dramatic': 'dramatic'}
# keys: tonic pitch classes the seed picks from; progressions: one chord per bar, a section takes the next one;
# lead: the section timbres in turn; pattern/bass: names below; shaker..kick: part levels (0 = absent); crash:
# the cymbal on a new section's downbeat (gentle moods mark sections with the run and the new chords alone);
# energy: the resting level 0..1; room: reverb time in seconds; home: the closing chord.
STYLES = {
    'bright': dict(keys=(2, 4, 0), progressions=('Iadd9 V vi7 IVmaj7', 'vi7 IVmaj7 Iadd9 V', 'IVmaj7 Iadd9 V vi7'),
                   lead=('marimba', 'celesta'), pattern='arp', bass='walk', shaker=.6, drum=0, tick=0, kick=.5,
                   crash=.4, energy=.65, room=1.6, home='Iadd9'),
    'warm': dict(keys=(5, 3, 7), progressions=('I vi IVmaj7 V', 'IVmaj7 I ii7 V', 'vi IV I Vsus4'),
                 lead=('kalimba', 'marimba'), pattern='lullaby', bass='half', shaker=.4, drum=.55, tick=0, kick=.25,
                 crash=0, energy=.5, room=2.0, home='I'),
    'calm': dict(keys=(0, 2, 5), progressions=('Imaj7 vi7 IVmaj7 Vsus4', 'IVmaj7 iii7 ii7 Imaj7'),
                 lead=('vibes', 'kalimba'), pattern='sparse', bass='whole', shaker=.15, drum=0, tick=0, kick=0,
                 crash=0, energy=.3, room=2.6, home='Imaj7'),
    'playful': dict(keys=(7, 5, 9), progressions=('I IV V I', 'I vi ii7 V', 'IV V iii vi'),
                    lead=('marimba', 'kalimba'), pattern='bounce', bass='bounce', shaker=.5, drum=.3, tick=.5,
                    kick=.4, crash=.35, energy=.65, room=1.4, home='I'),
    'curious': dict(keys=(2, 4, 0), progressions=('Iadd9 II IVmaj7 Iadd9', 'vi7 II IVmaj7 Vsus4'),
                    lead=('celesta', 'marimba'), pattern='rising', bass='half', shaker=.45, drum=.2, tick=.25,
                    kick=.35, crash=.3, energy=.55, room=2.0, home='Iadd9'),
    'mysterious': dict(keys=(2, 1, 4), progressions=('iadd9 bVImaj7 iadd9 iv7', 'bVImaj7 bVII iadd9 Vsus4'),
                       lead=('celesta', 'vibes'), pattern='sparse', bass='whole', shaker=0, drum=.2, tick=.35,
                       kick=0, crash=0, energy=.35, room=2.8, home='iadd9'),
    'tense': dict(keys=(9, 11, 8), progressions=('i bII i v', 'iv v i bII', 'i bVI bII v'),
                  lead=('marimba', 'celesta'), pattern='pulse', bass='drive', shaker=.3, drum=.3, tick=.5, kick=.5,
                  crash=.3, energy=.6, room=1.6, home='i'),
    'somber': dict(keys=(0, 9, 2), progressions=('i bVI bIII bVII', 'iv i bVI v'),
                   lead=('vibes', 'kalimba'), pattern='sparse', bass='whole', shaker=0, drum=0, tick=0, kick=0,
                   crash=0, energy=.25, room=2.8, home='i'),
    # Picture-book drama: the minor progression (Am F C G) under kalimba and hand drum, resolving to the
    # relative major, so a children's story swells at its big moments and still ends warm.
    'dramatic': dict(keys=(9, 7, 11), progressions=('i bVI bIII bVII', 'bVI bIII bVII i', 'iv bVI bVII i'),
                     lead=('kalimba', 'marimba'), pattern='lullaby', bass='half', shaker=.35, drum=.6, tick=0,
                     kick=.3, crash=0, energy=.5, room=2.2, home='bIII'),
}
# Sixteenth-note steps of one bar: (step, chord tone counted up from the root, velocity, lowest energy that plays it).
PATTERNS = {
    'arp': ((0, 0, 1, 0), (2, 2, .55, 0), (4, 1, .75, 0), (6, 3, .55, 0), (8, 2, .85, 0), (10, 4, .55, 0),
            (12, 3, .75, 0), (14, 5, .55, .45), (7, 4, .35, .7), (15, 6, .4, .75)),
    'lullaby': ((0, 0, 1, 0), (3, 2, .7, 0), (6, 4, .8, 0), (8, 3, .8, .3), (10, 2, .55, .45), (12, 5, .7, .2),
                (14, 4, .55, .55)),
    'sparse': ((0, 2, .9, 0), (6, 4, .6, .25), (8, 3, .75, 0), (12, 5, .55, .35), (14, 4, .45, .6)),
    'bounce': ((0, 0, 1, 0), (2, 4, .6, 0), (3, 5, .45, .55), (6, 2, .8, 0), (8, 3, .9, 0), (10, 4, .6, .3),
               (11, 5, .45, .6), (14, 2, .7, .4)),
    'rising': ((0, 0, .9, 0), (1, 1, .45, .5), (2, 2, .6, 0), (3, 3, .45, .5), (4, 4, .8, 0), (6, 5, .6, .3),
               (8, 6, .8, 0), (10, 5, .55, .4), (12, 4, .7, 0), (14, 3, .55, .45)),
    'pulse': ((0, 0, 1, 0), (2, 0, .45, 0), (4, 0, .55, 0), (6, 1, .9, 0), (8, 0, .55, 0), (10, 0, .45, .35),
              (12, 2, .9, 0), (14, 0, .45, .35)),
}
# (step, root 'r' / fifth '5' / octave 'o', velocity, lowest energy, length in steps)
BASS = {'whole': ((0, 'r', 1, 0, 16),),
        'half': ((0, 'r', 1, 0, 8), (8, '5', .8, .3, 8)),
        'walk': ((0, 'r', 1, 0, 6), (6, 'r', .55, .5, 2), (8, '5', .85, 0, 6), (14, 'o', .5, .6, 2)),
        'bounce': ((0, 'r', 1, 0, 3), (6, 'o', .7, 0, 2), (8, '5', .9, 0, 3), (14, 'r', .6, .4, 2)),
        'drive': tuple((s, 'r', .9 if s % 8 == 0 else .55, 0 if s % 4 == 0 else .3, 2) for s in range(0, 16, 2))}
DRUM = ((0, 'low', 1, 0), (6, 'high', .6, 0), (10, 'low', .7, 0), (12, 'high', .5, .6), (15, 'high', .35, .75))
# Modal mallets: (frequency ratio, amplitude, decay relative to the fundamental's); tau = fundamental decay at
# 440 Hz (lower notes ring longer); trem = vibraphone motor (rate Hz, depth).
MALLETS = {'marimba': dict(modes=((1, 1, 1), (3.93, .3, .18), (9.2, .08, .06)), tau=.55, trem=None),
           'kalimba': dict(modes=((1, 1, 1), (5.95, .22, .1), (14.9, .05, .035)), tau=1.1, trem=None),
           'celesta': dict(modes=((1, 1, 1), (2.76, .12, .4), (5.4, .045, .15)), tau=.9, trem=None),
           'vibes': dict(modes=((1, 1, 1), (4.0, .16, .3), (10.0, .04, .1)), tau=2.0, trem=(5.2, .2))}
LEVELS = {'lead': .3, 'bell': .13, 'pad': .055, 'bass': .22, 'shaker': .45, 'drum': .3, 'tick': .25, 'kick': .4,
          'riser': .16, 'crash': .05, 'boom': .5}
SENDS = {'lead': .3, 'bell': .5, 'pad': .3, 'bass': .03, 'shaker': .15, 'drum': .15, 'tick': .2, 'kick': .03,
         'riser': .3, 'crash': .4, 'boom': .1}
WET = .55


def chord(symbol) -> tuple[int, tuple[int, ...]]:
    """'bVImaj7' -> (8, (0, 4, 7, 11)): the root in semitones above the tonic and the chord's intervals. Lower-case
    numerals are minor ('vi7' is a minor seventh)."""
    flat, numeral, suffix = re.fullmatch(r'(b?)([IViv]+)(.*)', symbol).groups()
    minor = numeral.islower()
    quality = ('m' if minor and suffix in ('', '7', 'add9') else '') + suffix
    return (DEGREES[numeral.upper()] - bool(flat)) % 12, QUALITIES[quality]


def midi_hz(m):
    return 440. * 2 ** ((np.asarray(m, np.float64) - 69) / 12)


def _smooth(x, a, b):
    u = np.clip((np.asarray(x, np.float64) - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


def _ramp(n):
    """Raised-cosine 0 -> 1 over n samples."""
    return (.5 - .5 * np.cos(np.pi * np.arange(n) / max(n, 1))).astype(np.float32)


def _taper(x, ms=20.):
    """Ends a one-shot at exactly zero."""
    k = min(len(x), round(ms * SR / 1000))
    if k:
        x[-k:] *= _ramp(k)[::-1]
    return x


def _noise(n, seed):
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _band(x, lo, hi, sr=SR, order=2):
    if lo:
        x = sosfilt(butter(order, [lo, hi], 'bandpass', fs=sr, output='sos'), x)
    else:
        x = sosfilt(butter(order, hi, fs=sr, output='sos'), x)
    return x.astype(np.float32)


# ------------------------------------------------------------------ one-shots (cached: they depend only on arguments)

@lru_cache(maxsize=None)
def mallet(kind, midi) -> tuple[np.ndarray, np.ndarray]:
    """A struck note as (body, upper partials); play body + upper * (.35 + .65 velocity) for harder, brighter hits."""
    spec, f0 = MALLETS[kind], float(midi_hz(midi))
    tau = float(np.clip(spec['tau'] * (440 / f0) ** .5, .15, 4.))
    n = round(min(5 * tau + .05, 4.) * SR)
    t = np.arange(n) / SR
    body, upper = np.zeros(n, np.float32), np.zeros(n, np.float32)
    for i, (ratio, amp, decay) in enumerate(spec['modes']):
        if f0 * ratio > TOP:
            continue
        m = min(n, round(7 * tau * decay * SR) + 1)
        partial = amp * np.sin(2 * np.pi * f0 * ratio * t[:m]) * np.exp(-t[:m] / (tau * decay))
        (body if i == 0 else upper)[:m] += partial.astype(np.float32)
    if spec['trem']:
        rate, depth = spec['trem']
        body *= (1 - depth * (.5 - .5 * np.cos(2 * np.pi * rate * t))).astype(np.float32)
    attack = _ramp(round(.0015 * SR))                     # a felt mallet: 1.5 ms onset, no step
    for x in (body, upper):
        x[:len(attack)] *= attack
        _taper(x, 30)
    return body, upper


@lru_cache(maxsize=256)                  # n varies with tempo and length: bounded
def bass_note(midi, n) -> np.ndarray:
    """A round bass: four harmonics, 6 ms attack, decay to a 55% sustain, 80 ms release ending at n samples."""
    f0 = float(midi_hz(midi))
    t = np.arange(n) / SR
    x = sum(a * np.sin(2 * np.pi * f0 * k * t) for k, a in ((1, 1), (2, .35), (3, .12), (4, .05)) if f0 * k < TOP)
    env = .55 + .45 * np.exp(-t / .25)
    a, r = min(n // 4, round(.006 * SR)), min(n // 3, round(.08 * SR))
    env[:a] *= _ramp(a)
    env[n - r:] *= _ramp(r)[::-1]
    return (x * env).astype(np.float32)


@lru_cache(maxsize=None)
def hit(kind, variant=0) -> np.ndarray:
    """Percussion and effects one-shots."""
    if kind in ('kick', 'boom'):
        n = round((.7 if kind == 'kick' else 2.4) * SR)
        t = np.arange(n) / SR
        lo, sweep, fall, decay = (46, 64, .03, .25) if kind == 'kick' else (38, 46, .06, .8)
        phase = 2 * np.pi * np.cumsum(lo + sweep * np.exp(-t / fall)) / SR
        x = (np.sin(phase) + .15 * np.sin(2 * phase)) * np.exp(-t / decay)
        x = _band(x, 0, 900 if kind == 'kick' else 300)
    elif kind in ('low', 'high'):                         # hand drum: a pitched membrane and a soft slap
        n = round(.6 * SR)
        t = np.arange(n) / SR
        f, decay, slap = (140, .16, .2) if kind == 'low' else (235, .09, .35)
        f *= 1 + .02 * (variant - 1)
        phase = 2 * np.pi * np.cumsum(f * (1 + .25 * np.exp(-t / .02))) / SR
        x = np.sin(phase) * np.exp(-t / decay)
        x += slap * _band(_noise(n, 11 + variant), 700, 2500) * np.exp(-t / .012)
    elif kind == 'tick':                                  # woodblock
        n = round(.15 * SR)
        t = np.arange(n) / SR
        f = 1100 * (1 + .015 * (variant - 1))
        x = np.sin(2 * np.pi * f * t) * np.exp(-t / .03) + .35 * np.sin(2 * np.pi * 2.57 * f * t) * np.exp(-t / .012)
    elif kind == 'shaker':
        n = round(.15 * SR)
        t = np.arange(n) / SR
        env = np.minimum(1, t / .006) ** 2 * np.exp(-np.maximum(0, t - .006) / .04)
        x = _band(_noise(n, 21 + variant), 3500, 8000) * env
    elif kind == 'crash':                                 # a soft cymbal, decayed to -63 dB by its end
        n = round(4 * SR)
        t = np.arange(n) / SR
        x = _band(_noise(n, 31), 2500, 9000) * np.exp(-t / .55)
    else:
        raise ValueError(kind)
    x = np.asarray(x, np.float32)
    a = round(.001 * SR)
    x[:a] *= _ramp(a)
    return _taper(x / np.abs(x).max(), 30)


@lru_cache(maxsize=16)
def riser(n) -> np.ndarray:
    """Filtered noise rising into a mark: darker and quieter first, brightest at the end."""
    u = np.arange(n) / max(n, 1)
    x = _noise(n, 41)
    x = (_band(x, 0, 1800) * (1 - u) + _band(x, 2500, 11000) * u) * u ** 3
    x = np.asarray(x, np.float32) / max(np.abs(x).max(), 1e-9)
    return _taper(x, 25)


@lru_cache(maxsize=None)
def _wave(harmonics) -> np.ndarray:
    """One band-limited cycle (harmonic k at 1/k^1.3), between a saw and a triangle; one wrap sample appended."""
    k = np.arange(1, harmonics + 1)[:, None]
    x = (np.sin(2 * np.pi * k * np.arange(TABLE) / TABLE) / k ** 1.3).sum(0)
    x /= np.abs(x).max()
    return np.r_[x, x[0]].astype(np.float32)


def _osc(f, n, phase):
    table = _wave(max(1, min(48, int(5000 // f))))       # PAD_SR: every harmonic under 5 kHz
    x = (phase + f / PAD_SR * np.arange(n)) % 1. * TABLE
    i = x.astype(np.int32)
    frac = (x - i).astype(np.float32)
    return table[i] + (table[i + 1] - table[i]) * frac


@lru_cache(maxsize=None)
def room(rt60, seed=0) -> np.ndarray:
    """Stereo impulse response: 18 ms pre-delay, then decorrelated noise in each channel whose bright part dies
    twice as fast as its dark part, so the tail darkens as it decays. Unit energy per channel."""
    n = round(rt60 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(2):
        bright = _band(rng.standard_normal(n), 0, 7000) * np.exp(-6.9 * t / (.5 * rt60))
        dark = _band(rng.standard_normal(n), 0, 1600) * np.exp(-6.9 * t / rt60)
        ir = np.r_[np.zeros(round(.018 * SR)), .6 * bright + dark]
        ir[:round(.03 * SR)] *= _ramp(round(.03 * SR))
        out.append(ir / np.sqrt((ir ** 2).sum()))
    return np.stack(out, 1).astype(np.float32)


# ------------------------------------------------------------------ arrangement

def _voicing(pcs, previous, lo=52, hi=76):
    """Four pad voices in [lo, hi] closest to the previous four: any inversion of the chord in close position,
    a triad's lowest note doubled an octave up."""
    pcs = list(dict.fromkeys(pcs))[:4]
    best = None
    for r in range(len(pcs)):
        order = pcs[r:] + pcs[:r]
        for first in range(lo, lo + 12):
            if first % 12 != order[0]:
                continue
            notes = [first]
            for pc in order[1:]:
                notes.append(notes[-1] + ((pc - notes[-1]) % 12 or 12))
            notes += [first + 12] * (4 - len(notes))
            if max(notes) > hi:
                continue
            cost = sum(abs(a - b) for a, b in zip(sorted(notes), previous))
            if best is None or cost < best[0]:
                best = (cost, tuple(sorted(notes)))
    return best[1]


def energy_curve(duration, base, bar, marks, hz=100):
    """Energy 0..1 at hz: the mood's base, easing in over the first bar; rising (quadratically, over up to two
    bars) to base + strength * (1 - base) at a positive mark, held through its span, then falling back over two
    bars; scaled down by up to 70% across a negative (tender) mark's span with 0.75 s ramps."""
    t = np.arange(int(duration * hz) + 2) / hz
    e = base * (.7 + .3 * np.clip(t / bar, 0, 1))
    lift, hush = np.zeros(len(t)), np.ones(len(t))
    for t0, strength, span in marks:
        if strength > 0:
            pre = min(2 * bar, 5.)
            up = np.clip((t - t0 + pre) / pre, 0, 1) ** 2
            down = np.clip(1 - (t - t0 - span) / (2 * bar), 0, 1)
            lift = np.maximum(lift, strength * np.where(t <= t0, up, np.where(t <= t0 + span, 1, down)))
        elif strength < 0:
            w = np.clip(np.minimum(t - t0 + .75, t0 + span + .75 - t) / .75, 0, 1)
            hush = np.minimum(hush, 1 + strength * .7 * w)
    return t, np.clip((e + lift * (1 - e)) * hush, 0, 1)


def _marks(marks):
    out = []
    for m in marks:
        t0, strength, *rest = m
        span = float(rest[0]) if rest else 0.
        if not all(np.isfinite([t0, strength, span])) or span < 0:
            raise ValueError('marks need finite (time, strength[, span >= 0])')
        out.append((float(t0), float(np.clip(strength, -1, 1)), span))
    return sorted(out)


class _Bus:
    def __init__(self, n):
        self.l, self.r, self.send = (np.zeros(n, np.float32) for _ in range(3))

    def add(self, t, x, gain, pan, part):
        i = round(t * SR)
        if i >= len(self.l) or gain <= 0:
            return
        x = x[:len(self.l) - max(i, 0)][max(0, -i):]
        i = max(i, 0)
        a = (np.clip(pan, -1, 1) + 1) * np.pi / 4
        g = gain * LEVELS[part]
        self.l[i:i + len(x)] += x * np.float32(g * np.cos(a))
        self.r[i:i + len(x)] += x * np.float32(g * np.sin(a))
        self.send[i:i + len(x)] += x * np.float32(g * SENDS[part])


def compose(duration, mood='warm', bpm=96., seed=0, sections=(), marks=()) -> np.ndarray:
    """(n, 2) float32 at 48 kHz. sections: times where a new section starts (moved to the nearest bar line);
    marks: (time, strength[, span]) with strength 0..1 swelling into the time and holding through span, or -1..0
    hushing from the time through span (tender lines)."""
    if not np.isfinite(bpm) or bpm <= 0 or not np.isfinite(duration) or duration < 0:
        raise ValueError('duration must be nonnegative and bpm positive')
    n = round(duration * SR)
    if not n:
        return np.zeros((0, 2), np.float32)
    name = MOODS.get(str(mood).strip().lower(), 'warm')
    style = STYLES[name]
    marks = _marks(marks)
    rng = np.random.default_rng([int(seed) % 2 ** 32, zlib.crc32(name.encode())])
    key = style['keys'][int(rng.integers(len(style['keys'])))]
    first = int(rng.integers(len(style['progressions'])))
    leads = style['lead'] if rng.random() < .75 else style['lead'][::-1]
    progressions = [[chord(s) for s in p.split()] for p in style['progressions']]
    home = chord(style['home'])

    beat = 60 / bpm
    step = beat / 4 * (2 if bpm > 150 else 1)        # fast tempos: half-time feel, one chord per two bars
    bar = 16 * step
    bars = int(np.ceil(duration / bar))
    starts = sorted({b for b in (round(s / bar) for s in sections if np.isfinite(s)) if 0 < b < bars})
    end_bar = max(1, int((duration - 1.5) // bar))     # the closing bars play the home chord
    ct, ce = energy_curve(duration, style['energy'], bar, marks)
    energy = lambda t: float(np.interp(t, ct, ce))  # noqa: E731
    variation = rng.integers(3, size=bars + 1)
    bus = _Bus(n)

    def jitter(scale=.004):
        return float(np.clip(rng.normal(0, scale), -2 * scale, 2 * scale))

    # Harmony per bar.
    plan, previous, low = [], (57, 60, 64, 67), 40
    for b in range(bars):
        section = sum(s <= b for s in starts)
        local = b - max([0] + [s for s in starts if s <= b])
        prog = progressions[(first + section) % len(progressions)]
        root, quality = home if b >= end_bar else prog[local % len(prog)]
        pcs = [(key + root + q) % 12 for q in quality]
        voicing = _voicing(pcs, previous)
        low = min((m for m in range(33, 51) if m % 12 == pcs[0]), key=lambda m: (abs(m - low), m))
        base = 62 + (pcs[0] - 62) % 12
        arp = sorted({base + (q % 12) for q in quality} | {base})
        plan.append(dict(t=b * bar, pcs=pcs, voicing=voicing, bass=low, arp=arp, local=local,
                         lead=leads[section % len(leads)], ending=b >= end_bar))
        previous = voicing

    def tone(p, k):
        arp = p['arp']
        return arp[k % len(arp)] + 12 * (k // len(arp))

    # Lead, guide line, bass and percussion, bar by bar.
    for b, p in enumerate(plan):
        t0 = p['t']
        if p['ending']:
            if b == end_bar:
                for k in range(4):
                    m = tone(p, k)
                    bus.add(t0 + .035 * k, *_strike(p['lead'], m, .75 - .1 * k), (m - 66) / 30, 'lead')
                bus.add(t0, bass_note(p['bass'], round(min(4 * bar, duration - t0 + .5) * SR)), .8, 0, 'bass')
            continue
        notes = list(PATTERNS[style['pattern']])
        if p['local'] % 4 == 3 and variation[b] == 1:     # the phrase's answer: the second half mirrored
            top = max(k for _, k, _, _ in notes) + min(k for _, k, _, _ in notes)
            notes = [(s, top - k if s >= 8 else k, v, lo) for s, k, v, lo in notes]
        elif p['local'] % 4 == 3 and variation[b] == 2:   # a pickup run into the next phrase
            notes = [x for x in notes if x[0] < 12] + [(12 + i, 3 + i, .45 + .08 * i, 0) for i in range(4)]
        if b + 1 in starts:                               # a run up into the next section
            notes = [x for x in notes if x[0] < 12] + [(12 + i, 3 + i, .35 + .12 * i, 0) for i in range(4)]
        for s, k, v, lo in sorted(notes):
            t = t0 + s * step
            e = energy(t)
            if e < lo:
                continue
            m = tone(p, k)
            bus.add(t + jitter(), *_strike(p['lead'], m, v * (.4 + .6 * e) * (1 + jitter(.04))), (m - 66) / 30,
                    'lead')
        for s in (0, 8):                                  # the guide line: the pad's top voice, an octave up
            t = t0 + s * step
            e = energy(t)
            if e >= .55:
                m = p['voicing'][-1] + 12
                bus.add(t + jitter(), *_strike('celesta', m, .3 + .6 * (e - .55)), .25, 'bell')
        for s, which, v, lo, length in BASS[style['bass']]:
            t = t0 + s * step
            e = energy(t)
            if e < max(lo, .12):
                continue
            m = p['bass'] + {'r': 0, '5': 7, 'o': 12}[which]
            bus.add(t + jitter(.002), bass_note(m, round(length * step * SR)), v * (.45 + .55 * e), 0, 'bass')
        for s in range(16):
            t = t0 + s * step
            e = energy(t)
            if style['shaker'] and s % (1 if e > .7 else 2) == 0:
                accent = (.9 if s % 4 == 2 else .55 if s % 2 == 0 else .35)
                bus.add(t + jitter(.003), hit('shaker', s % 4), style['shaker'] * accent * _smooth(e, .3, .55),
                        .45, 'shaker')
            if style['tick'] and s % 4 == 2:
                bus.add(t + jitter(.003), hit('tick', s // 4 % 3), style['tick'] * .8 * _smooth(e, .2, .45), -.35,
                        'tick')
            if style['kick'] and s in (0, 8):
                bus.add(t, hit('kick'), style['kick'] * (1 if s == 0 else .7) * _smooth(e, .45, .7), 0, 'kick')
        if style['drum']:
            for s, kind, v, lo in DRUM:
                t = t0 + s * step
                e = energy(t)
                if e >= lo:
                    bus.add(t + jitter(.003), hit(kind, s % 3), style['drum'] * v * _smooth(e, .25, .5),
                            -.3 if kind == 'low' else -.15, 'drum')

    # Sections: a soft crash on the new downbeat in the livelier moods (unless a mark lands within a bar of it).
    for s in starts:
        t = s * bar
        if style['crash'] and not any(m[1] > 0 and abs(m[0] - t) < bar for m in marks):
            bus.add(t, hit('crash'), style['crash'], .2, 'crash')
    # Marks: a riser and, for strong ones, a hand-drum roll into the mark; a boom, a crash and a chord stab on it.
    for t0, strength, _ in marks:
        if strength < .5 or t0 >= duration:
            continue
        p = plan[min(max(0, int(t0 // bar)), bars - 1)]
        pre = min(bar, 3.)
        if t0 - pre >= 0:
            bus.add(t0 - pre, riser(round(pre * SR)), strength, 0, 'riser')
        bus.add(t0, hit('crash'), strength, -.1, 'crash')
        for k in range(4):
            m = tone(p, k)
            bus.add(t0 + .012 * k, *_strike(p['lead'], m, .85 * strength), (m - 66) / 30, 'lead')
        if strength >= .7:
            bus.add(t0, hit('boom'), strength, 0, 'boom')
            for k in range(8, 0, -1):
                t = t0 - k * step
                if t >= 0:
                    bus.add(t, hit('low', k % 3), .25 + .75 * (1 - k / 8), -.25, 'drum')

    _pad(bus, plan, bar, ct, ce, n)
    wet = room(style['room'])
    out = np.stack([bus.l + WET * oaconvolve(bus.send, wet[:, 0])[:n],
                    bus.r + WET * oaconvolve(bus.send, wet[:, 1])[:n]], 1)
    out = sosfilt(butter(2, 35, 'highpass', fs=SR, output='sos'), out, axis=0)
    out = sosfilt(butter(2, 11000, fs=SR, output='sos'), out, axis=0)
    return out.astype(np.float32)


def _strike(kind, midi, velocity):
    body, upper = mallet(kind, int(midi))
    v = float(np.clip(velocity, 0, 1))
    return body + upper * np.float32(.35 + .65 * v), v ** 1.5


def _pad(bus, plan, bar, ct, ce, n):
    """Each run of bars on one chord: four voices, each two wavetable oscillators 7 cents apart (one per side),
    with a raised-cosine attack that starts just before the bar line and a release after the run ends; then the
    dark (600 Hz) and bright (2.4 kHz) low-passes crossfaded, and the level following the energy."""
    m = round(n * PAD_SR / SR) + 1
    left, right = np.zeros(m, np.float32), np.zeros(m, np.float32)
    attack, release = min(.45 * bar, 1.), min(.6 * bar, 1.2)
    runs = []
    for p in plan:
        if runs and runs[-1][2] == p['voicing']:
            runs[-1][1] = p['t'] + bar
        else:
            runs.append([p['t'], p['t'] + bar, p['voicing']])
    for start, end, voicing in runs:
        a = round(max(0., start - .3 * attack) * PAD_SR)
        b = min(m, round((end + release) * PAD_SR))
        if a >= b:
            continue
        length = b - a
        env = np.ones(length, np.float32)
        k = min(length, round(attack * PAD_SR))
        env[:k] = _ramp(k)
        r0 = min(length, round((end - a / PAD_SR) * PAD_SR))
        env[r0:] *= _ramp(length - r0)[::-1]
        for i, note in enumerate(voicing):
            f = float(midi_hz(note))
            for side, cents in ((left, -3.5), (right, 3.5)):
                side[a:b] += _osc(f * 2 ** (cents / 1200), length, (.37 * i + (cents > 0) * .5) % 1) * env
    e = np.interp(np.arange(m) / PAD_SR, ct, ce).astype(np.float32)
    bright = _smooth(e, .3, .9).astype(np.float32)
    level = (.4 + .6 * e).astype(np.float32)
    dark_sos = butter(2, 600, fs=PAD_SR, output='sos')
    bright_sos = butter(2, 2400, fs=PAD_SR, output='sos')
    for side, out in ((left, bus.l), (right, bus.r)):
        x = (sosfilt(dark_sos, side) * (1 - bright) + sosfilt(bright_sos, side) * bright) * level
        up = resample_poly(x.astype(np.float32), SR // PAD_SR, 1)[:n].astype(np.float32) * LEVELS['pad']
        out[:len(up)] += up
        bus.send[:len(up)] += up * np.float32(SENDS['pad'] / 2)

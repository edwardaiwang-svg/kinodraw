"""Deterministic procedural creature, weather and animation effects.

KINDS maps each effect to its preview duration in seconds. render returns a mono
float32 signal, fitted to an existing SFX kind's loudest-100-ms level and .7 peak.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import sawtooth

from .sfx import _band, _fit, _pink, _tone


KINDS = {'roar': 1.4, 'whimper': .6, 'nudge': .18, 'hyena_cackle': .85,
         'swipe': .22, 'breath_puff': .3, 'wind': 3., 'rain': 3.,
         'fog_drone': 3., 'shooting_star': .8, 'type_tick': .07,
         'transition_whoosh': .6}
# The action sounds' levels put each one's loudest 400 ms about 12 LU under the narration's once the mix ducks it
# (measured on a real narration): short sounds need a louder 100 ms level than long ones.
LEVEL_KIND = {'roar': 'stamp', 'whimper': 'pop', 'nudge': 'impact',
              'hyena_cackle': 'pop', 'swipe': 'impact', 'breath_puff': 'impact',
              'wind': 'write', 'rain': 'write', 'fog_drone': 'write',
              'shooting_star': 'confetti', 'type_tick': 'type',
              'transition_whoosh': 'whoosh'}


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
    raise ValueError(f'Unknown SFX kind: {kind!r}')


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
    bed = kind in ('wind', 'rain', 'fog_drone')
    attack = min(n // 2, max(2, int((.04 if bed else .001) * sr)))
    release = min(n // 2, max(2, int((.04 if bed else .01) * sr)))
    x[:attack] *= np.linspace(0, 1, attack)
    x[-release:] *= np.linspace(1, 0, release)
    x[0] = x[-1] = 0
    return _fit(x, LEVEL_KIND[kind], sr) if np.any(x) else x.astype(np.float32)

"""Seeded, vectorised value noise. Circular advection makes time periodic without a crossfade."""
from __future__ import annotations

import hashlib
import math
from functools import lru_cache

import numpy as np


def seeded(seed, *keys):
    digest = hashlib.blake2b(repr((seed,) + keys).encode(), digest_size=16).digest()
    return np.random.default_rng(int.from_bytes(digest, 'little'))


@lru_cache(maxsize=128)
def _lattice(seed, octave):
    return seeded(seed, 'noise', octave).random((32, 32), dtype=np.float32)


def value_noise(x, y, seed=0, octave=0):
    """Smooth [0, 1] noise at broadcastable coordinates, tiled every 32 lattice cells."""
    x, y = np.asarray(x, np.float32), np.asarray(y, np.float32)
    ix, iy = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    u, v = x - ix, y - iy
    u, v = u.astype(np.float32), v.astype(np.float32)
    u, v = u * u * (3 - 2 * u), v * v * (3 - 2 * v)
    grid = _lattice(seed, octave)
    a, b = grid[iy % 32, ix % 32], grid[iy % 32, (ix + 1) % 32]
    c, d = grid[(iy + 1) % 32, ix % 32], grid[(iy + 1) % 32, (ix + 1) % 32]
    top, bottom = a + (b - a) * u, c + (d - c) * u
    return top + (bottom - top) * v


def fbm(x, y, t=0., seed=0, octaves=4, period=6., drift=(.8, .35)):
    """Normalised fractal Brownian motion; ``t`` and ``t + period`` have identical fields.

    Coordinates are lattice cells; drift is the radius of a closed advection path. Each octave has
    twice the spatial frequency and half the amplitude. Integer temporal harmonics retain the loop.
    """
    if not math.isfinite(period) or period <= 0 or not 1 <= octaves <= 8:
        raise ValueError('period must be positive and octaves must be in 1..8')
    x, y = np.asarray(x, np.float32), np.asarray(y, np.float32)
    phase = 2 * math.pi * (t % period) / period
    out = np.zeros(np.broadcast_shapes(x.shape, y.shape), np.float32)
    weight, total = 1., 0.
    for i in range(octaves):
        scale = 2 ** i
        dx = drift[0] * math.sin(phase) * scale
        dy = drift[1] * (math.cos(phase) - 1) * scale
        out += weight * value_noise(x * scale + dx, y * scale + dy, seed, i)
        total += weight
        weight *= .5
    return out / total

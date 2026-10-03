"""Loudness, true peak and a look-ahead limiter for the final mix (ITU-R BS.1770-4).

loudness(): integrated LUFS. true_peak(): dBTP, 4x oversampled. limit(): the Chrome extension's limiter, run on
the 4x-oversampled peaks of every channel. master(): gain to the target loudness, then limit.
Mixes are processed CHUNK samples at a time, so the oversampled and filtered copies stay small for any length.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import resample_poly, sosfilt

CHUNK = 1 << 20
PAD = 16                  # input samples each side of a chunk: the 4x filter reaches 10


def kweighting(sr) -> np.ndarray:
    """K-weighting (the high shelf, then the RLB high-pass) as second-order sections, derived from the analog
    prototypes as libebur128 does; at 48 kHz these are the coefficients printed in the standard."""
    k = np.tan(np.pi * 1681.974450955533 / sr)
    q = .7071752369554196
    vh = 10 ** (3.999843853973347 / 20)
    vb = vh ** .4996667741545416
    a0 = 1 + k / q + k * k
    shelf = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0,
             1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    k = np.tan(np.pi * 38.13547087602444 / sr)
    q = .5003270373238773
    a0 = 1 + k / q + k * k
    return np.array([shelf, [1, -2, 1, 1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]])


def _frames(x) -> np.ndarray:
    return np.asarray(x, np.float32).reshape(len(x), -1)


def loudness(x, sr) -> float:
    """Integrated loudness in LUFS: K-weighted, 400 ms blocks every 100 ms, a -70 LUFS absolute gate and a gate
    10 LU below the loudness of the blocks above it. -inf for silence."""
    x = _frames(x)
    step = round(sr / 10)
    steps = len(x) // step
    power = np.zeros(steps)                      # K-weighted energy of each 100 ms, all channels
    sos, zi = kweighting(sr), np.zeros((2, 2, x.shape[1]))
    for s in range(0, steps, CHUNK // step):
        y, zi = sosfilt(sos, x[s * step:min(steps, s + CHUNK // step) * step], axis=0, zi=zi)
        power[s:s + len(y) // step] = (y.reshape(-1, step, x.shape[1]) ** 2).sum((1, 2))
    blocks = (power[:-3] + power[1:-2] + power[2:-1] + power[3:]) / (4 * step)
    with np.errstate(divide='ignore'):
        lufs = -.691 + 10 * np.log10(blocks)
        loud = blocks[lufs > -70]
        if not len(loud):
            return -np.inf
        gated = loud[lufs[lufs > -70] > -.691 + 10 * np.log10(loud.mean()) - 10]
        return float(-.691 + 10 * np.log10(gated.mean()))


def _peaks(x, s, e) -> np.ndarray:
    """For each sample in [s, e): the highest level from it to the next sample, 4x oversampled, over all channels."""
    a = max(0, s - PAD)
    up = np.abs(resample_poly(x[a:min(len(x), e + PAD)], 4, 1, axis=0)).max(1)
    return up[4 * (s - a):4 * (e - a)].reshape(-1, 4).max(1)


def true_peak(x, sr) -> float:
    """Peak level in dBTP, including the peaks between samples (4x oversampled)."""
    x = _frames(x)
    top = max((float(_peaks(x, s, min(len(x), s + CHUNK)).max()) for s in range(0, len(x), CHUNK)), default=0.)
    with np.errstate(divide='ignore'):
        return float(20 * np.log10(top))


def _release(depth, decay, carry) -> np.ndarray:
    """d[i] = max(depth[i], decay * d[i - 1]), d[-1] = carry: every gain reduction fades out over the release
    (in logs the recursion is a running maximum)."""
    k = np.arange(len(depth)) * np.log(decay)
    with np.errstate(divide='ignore'):
        u = np.maximum.accumulate(np.log(depth.astype(np.float64)) - k)
        u = np.maximum(u, np.log(carry * decay))
    return np.exp(u + k)


def limit(x, sr, ceiling_dbtp=-1.0, lookahead_ms=5, release_ms=50) -> np.ndarray:
    """Look-ahead peak limiter, as the Chrome extension's: before any peak above the ceiling (between samples too,
    on any channel) the gain dips smoothly over the look-ahead, reaching what the peak needs exactly at the peak,
    and recovers over the release; everything else is untouched. The channels share one gain."""
    x = np.asarray(x, np.float32)
    frames = _frames(x)
    out = np.empty_like(frames)
    ceiling = 10 ** (ceiling_dbtp / 20)
    la = max(1, round(lookahead_ms * sr / 1000))
    decay = np.exp(-1000 / (release_ms * sr))
    tail, carry = None, 0.
    for s in range(0, len(frames), CHUNK):
        e = min(len(frames), s + CHUNK)
        need = np.ones(e - s + la, np.float32)                  # the gain each sample's peak allows
        level = _peaks(frames, s, min(len(frames), e + la))
        need[:len(level)] = np.minimum(1, ceiling / np.maximum(level, 1e-12))
        held = minimum_filter1d(need, la + 1, origin=-((la + 1) // 2))[:e - s]      # ...or a peak just after it
        depth = _release(1 - held, decay, carry)
        carry, held = depth[-1], 1 - depth
        tail = np.full(la, held[0]) if tail is None else tail  # before the start it is as at the start
        run = np.concatenate([[0.], np.cumsum(np.concatenate([tail, held]))])
        gain = (run[la + 1:] - run[:-la - 1]) / (la + 1)       # held, averaged over the look-ahead window
        out[s:e] = frames[s:e] * np.minimum(1, gain)[:, None].astype(np.float32)
        tail = np.concatenate([tail, held])[-la:]
    out = out.reshape(x.shape)
    over = true_peak(out, sr) - ceiling_dbtp
    return out * np.float32(10 ** (-over / 20)) if over > 0 else out      # rare, and a fraction of a dB


def master(x, sr, target_lufs=-14.0, ceiling_dbtp=-1.0) -> np.ndarray:
    """Gain to the target loudness, then limit to the ceiling; if the limiter took more than 0.3 LU, once more
    with that much extra gain."""
    x = np.asarray(x, np.float32)
    now = loudness(x, sr)
    if not np.isfinite(now):
        return x
    y = limit(x * np.float32(10 ** ((target_lufs - now) / 20)), sr, ceiling_dbtp)
    lost = target_lufs - loudness(y, sr)
    if lost > .3:
        y = limit(x * np.float32(10 ** ((target_lufs - now + lost) / 20)), sr, ceiling_dbtp)
    return y

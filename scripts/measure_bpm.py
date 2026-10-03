"""Measure each bundled track's tempo and first downbeat for tracks.json, without ears.

  python scripts/measure_bpm.py        (prints bpm, downbeat and the evidence for every track)

Onsets: the spectral flux of a log-magnitude spectrogram, 100 frames a second. Tempo: the beat period between
60 and 200 BPM whose multiples (1-4 beats) the onset envelope's autocorrelation likes best, weighted by a gentle
prior around 120 BPM, then refined to the period whose beat grid gathers the most onset strength (interpolated,
so whole-frame periods are not favoured). Downbeat: of the 16 sixteenths of a bar on that grid, the one where the
bass hits hardest and the harmony changes most, bar after bar (a syncopated accent can outshout the one).
Times count from the start of the decoded file; mix.py's bed starts at the first audible sample, `lead` seconds
in. Deterministic: no randomness anywhere.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from doodlestudio.audio.mix import MUSIC, SR, decode  # noqa: E402

HOP, SIZE, FPS = 480, 2048, 100
DELAY = .75 * SIZE / SR           # the flux peaks as an onset gets 3/4 into the window (a click track: 30-35 ms)


def features(x):
    """Per 10 ms frame: onset strength (all bands; below 200 Hz) and the pitch-class profile (200-2000 Hz)."""
    window = np.hanning(SIZE).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(x, SIZE)[::HOP]
    mag = np.concatenate([np.abs(np.fft.rfft(frames[i:i + 1024] * window)) for i in range(0, len(frames), 1024)])
    spec = np.log1p(1000 * mag)
    rise = np.maximum(0, np.diff(spec, axis=0, prepend=spec[:1]))
    onsets = []
    for flux in (rise.sum(1), rise[:, :int(200 / (SR / SIZE)) + 1].sum(1)):
        flux = flux - np.convolve(flux, np.ones(FPS) / FPS, 'same')       # minus the local mean (1 s)
        onsets.append(np.convolve(np.maximum(0, flux), [.25, .5, .25], 'same'))
    f = np.fft.rfftfreq(SIZE, 1 / SR)
    band = (f > 200) & (f < 2000)
    pc = np.round(12 * np.log2(f[band] / 440)).astype(int) % 12
    chroma = np.stack([mag[:, band][:, pc == k].sum(1) for k in range(12)], 1)
    return *onsets, chroma / (chroma.sum(1, keepdims=True) + 1e-9)


def autocorrelation(env):
    ac = np.fft.irfft(np.abs(np.fft.rfft(env - env.mean(), 2 * len(env))) ** 2)[:len(env)]
    return ac / ac[0]


def comb(ac, period):
    """How well the autocorrelation repeats at 1-4 beats of this period, times a prior around 120 BPM."""
    beats = np.interp(period * np.arange(1, 5), np.arange(len(ac)), ac).mean()
    return beats * np.exp(-.5 * np.log2(60 * FPS / period / 120) ** 2)


def grid(env, period):
    """The mean onset strength on a beat grid at this period, at its best phase (to a quarter frame)."""
    phases = np.arange(0, period, .25)
    at = phases[:, None] + period * np.arange(int((len(env) - 1 - period) / period))
    score = np.interp(at, np.arange(len(env)), env).mean(1)
    return score.max(), phases[np.argmax(score)], score.max() / score.mean()


def measure(env, low, chroma):
    ac = autocorrelation(env)
    periods = np.arange(60 * FPS / 200, 60 * FPS / 60, .05)
    rough = periods[np.argmax([comb(ac, p) for p in periods])]
    fine = np.arange(rough - 1, rough + 1, .005)
    period = fine[np.argmax([grid(env, p)[0] for p in fine])]
    _, phase, contrast = grid(env, period)
    kick, change = np.zeros(16), np.zeros(16)
    beat = int(round(period))
    for p in range(16):                        # every bar line candidate, one sixteenth apart
        at = np.round(phase + period * (p / 4 + 4 * np.arange(1, int(len(env) / period / 4) - 1))).astype(int)
        kick[p] = low[np.clip(at[:, None] + np.arange(-2, 3), 0, len(low) - 1)].max(1).mean()
        change[p] = np.mean([np.abs(chroma[t:t + beat].mean(0) - chroma[t - beat:t].mean(0)).sum() for t in at])
    score = kick / kick.max() + change / change.max()
    one = int(np.argmax(score))
    half = len(env) // 2
    return {'bpm': 60 * FPS / period, 'downbeat': (phase + period * one / 4) / FPS % (240 / (60 * FPS / period)),
            'contrast': contrast, 'acf': ac[int(round(period))],
            'alternatives': {f: comb(ac, period / f) / comb(ac, period) for f in (.5, 2, 4 / 3, 3 / 4)},
            'halves': [60 * FPS / fine[np.argmax([grid(e, p)[0] for p in fine])] for e in (env[:half], env[half:])],
            'one': one, 'runner_up': sorted(score)[-2] / score[one], 'kick': kick / kick.max(),
            'change': change / change.max()}


def main():
    tracks = json.loads((MUSIC / 'tracks.json').read_text(encoding='utf-8'))
    for slug in tracks:
        x = decode(MUSIC / f'{slug}.mp3', 1)[:, 0]
        lead = np.flatnonzero(np.abs(x) > 1e-3)[0] / SR
        m = measure(*features(x))
        alt = ', '.join(f'x{f:.2g}: {r:.2f}' for f, r in m['alternatives'].items())
        print(f"{slug}: bpm {m['bpm']:.2f}  downbeat {m['downbeat'] + DELAY:.3f} s  (lead {lead:.3f} s)")
        print(f"  autocorrelation at the beat {m['acf']:.2f}; other tempos score, relative to this one: {alt}")
        print(f"  beat grid {m['contrast']:.1f}x the onset strength of an off-grid phase; each half alone: "
              f"{m['halves'][0]:.2f} and {m['halves'][1]:.2f} BPM")
        print(f"  bar line at sixteenth {m['one']} of the loudest grid (runner-up scores {m['runner_up']:.2f} of it); "
              f"bass by sixteenth: {' '.join(f'{v:.1f}' for v in m['kick'])}; "
              f"harmony change: {' '.join(f'{v:.1f}' for v in m['change'])}")


if __name__ == '__main__':
    main()

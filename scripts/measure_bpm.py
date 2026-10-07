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
from kinodraw.audio.mix import MUSIC, SR, decode  # noqa: E402
from kinodraw.audio.tempo import DELAY, features, measure  # noqa: E402


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

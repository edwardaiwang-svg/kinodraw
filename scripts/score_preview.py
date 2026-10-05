"""Write four 30 s score/ducking previews and the procedural SFX kit under /tmp/kd1005/a7-audio."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinodraw.audio import master, mix, score, sfx, synth_sfx  # noqa: E402

OUT = Path('/tmp/kd1005/a7-audio')


def measured_lufs(path):
    """Integrated LUFS from ffmpeg's independent EBU R128 meter."""
    result = subprocess.run([mix.FFMPEG, '-v', 'error', '-nostats', '-i', str(path), '-af',
                             'ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.I:file=-',
                             '-f', 'null', '-'], capture_output=True, encoding='utf-8', check=True)
    return float(re.findall(r'lavfi\.r128\.I=(-?[\d.]+)', result.stdout)[-1])


def fake_narration(duration=30):
    """Voiced syllables with breath noise, in three phrases separated by open music."""
    sr = mix.SR
    t = np.arange(round(duration * sr)) / sr
    rng = np.random.default_rng(7)
    phrases = ((t >= 5) & (t < 9)) | ((t >= 14) & (t < 18)) | ((t >= 23) & (t < 27))
    syllables = .25 + .75 * np.maximum(0, np.sin(2 * np.pi * 3.7 * t))
    voiced = np.sin(2 * np.pi * 180 * t) + .45 * np.sin(2 * np.pi * 360 * t)
    voice = (.18 * voiced + .025 * rng.standard_normal(len(t))) * phrases * syllables
    return master.master(voice.astype(np.float32), sr, target_lufs=-18)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    narration = fake_narration()
    mix.write_wav(OUT / 'fake_narration.wav', narration)
    lines = ['Score preview: 48 kHz stereo, 30 s; master target -14 LUFS / -1 dBTP.',
             'Narration bursts: 5-9, 14-18, 23-27 s. Duck: -10 dB, 80 ms attack, 400 ms release.',
             'Requested tempo selects a recording; grids use its measured tempo (no retiming).', '',
             'Bundled CC0 beds (cached scripts/measure_bpm.py measurement):']
    for slug, tag in score.tags().items():
        lines.append(f"  {slug}: {tag['bpm']:.3f} BPM; source downbeat {tag['downbeat']:.3f} s; "
                     f"moods {', '.join(tag['moods'])}")
    lines += ['', 'Previews (music stem saved separately to inspect the actual duck):']
    for mood in ('bright', 'neutral', 'discovery', 'mysterious'):
        result = score.render(30, mood, 129, narration, ambient=True)
        path = OUT / f'{mood}.wav'
        mix.write_wav(path, result.audio)
        mix.write_wav(OUT / f'{mood}_music.wav', result.music)
        (OUT / f'{mood}_beats.txt').write_text('\n'.join(f'{t:.6f}' for t in result.beats) + '\n', encoding='utf-8')
        # Identical source samples before/after applying gain isolate ducking from changes in the recording.
        speech = slice(6 * mix.SR, 8 * mix.SR)
        ducked = result.music[speech].astype(np.float64)
        unducked = ducked / result.duck_gain[speech, None]
        depth = -10 * np.log10((ducked ** 2).sum() / (unducked ** 2).sum())
        lines.append(f'  {mood}: {result.track or "procedural pad"}; {result.bpm:.3f} BPM; '
                     f'{measured_lufs(path):.2f} LUFS (ffmpeg ebur128); duck depth {depth:.2f} dB; '
                     f'{master.true_peak(result.audio, mix.SR):.2f} dBTP')
    lines += ['', 'SFX (existing loudest-100-ms levels, peak <= 0.7):']
    for kind in synth_sfx.KINDS:
        samples = synth_sfx.render(kind)
        mix.write_wav(OUT / f'sfx_{kind}.wav', samples)
        lines.append(f'  {kind}: {len(samples) / mix.SR:.3f} s; peak {np.abs(samples).max():.4f}; '
                     f'level {synth_sfx.LEVEL_KIND[kind]} = {sfx.LEVEL[synth_sfx.LEVEL_KIND[kind]]} LUFS')
    report = '\n'.join(lines) + '\n'
    (OUT / 'report.txt').write_text(report, encoding='utf-8')
    print(report, end='')
    print(f'Wrote previews to {OUT}')


if __name__ == '__main__':
    main()

"""The narration master (audio.mix.assemble) lands the voice at its body level from the first word.

Measured 10/8 on rounds/r03f: after a music-only intro the narration started about 8 LU quiet and climbed for 15-20 s,
because FFmpeg's two-pass loudnorm refuses linear mode when the needed gain would push the peaks past its TP target,
falls back to dynamic mode, and dynamic mode starts at 0 dB gain after a silent lead-in and rises 0.5 dB/s."""
from types import SimpleNamespace

import numpy as np
from scipy.signal import sosfilt

from kinodraw.audio import master, mix

SR = mix.SR
LEAD, SPEECH = 6.0, 30.0


def _speech(seconds, seed=7) -> np.ndarray:
    """Speech-like: a voiced buzz (150 Hz with harmonics, two formants) in 4 Hz syllables, with short pauses between
    sentences and a few stressed syllables; at -26 LUFS its true peak is about -9 dBTP, as TTS narration's is."""
    rng = np.random.default_rng(seed)
    t = np.arange(round(seconds * SR)) / SR
    f0 = 150 * (1 + .08 * np.sin(2 * np.pi * .7 * t))
    phase = 2 * np.pi * np.cumsum(f0) / SR
    buzz = sum(np.sin(k * phase + rng.random() * 2 * np.pi) / k
               * (1 + 2 * np.exp(-((k * 150 - 700) / 250) ** 2) + 1.5 * np.exp(-((k * 150 - 1800) / 400) ** 2))
               for k in range(1, 30))
    syll = np.clip(np.sin(2 * np.pi * 4 * t), 0, None) ** 2
    stress = 1 + .3 * (rng.random(len(t) // (SR // 4) + 1) > .85)[np.arange(len(t)) // (SR // 4)]
    sentence = (t % 4) < 3.4                                  # 0.6 s pause every 4 s
    return (buzz * syll * stress * sentence).astype(np.float32)


def _short_term(x, start, seconds=3.0) -> float:
    """EBU short-term loudness (3 s, ungated) of the window starting at ``start`` seconds."""
    y = sosfilt(master.kweighting(SR), x[round(start * SR):round((start + seconds) * SR)].astype(np.float64))
    return float(-.691 + 10 * np.log10((y ** 2).mean()))


def test_a_silent_lead_in_does_not_start_the_narration_quiet(tmp_path, monkeypatch):
    speech = _speech(SPEECH)
    speech *= np.float32(10 ** ((-26 - master.loudness(speech, SR)) / 20))      # TTS narration measures about -26
    # The case FFmpeg cannot do linearly: +8 dB would put the peaks above its -1.5 dBTP target.
    assert master.true_peak(speech, SR) + 8 > -1.5
    pcm = np.concatenate([np.zeros(round(LEAD * SR), np.float32), speech])
    mix.write_wav(tmp_path / 'clip.wav', pcm)
    clip = SimpleNamespace(wav=tmp_path / 'clip.wav', duration=len(pcm) / SR, char_times=[])
    tl = {'duration': len(pcm) / SR, 'beats': {'b1': {'start': 0.0}}, 'captions': []}
    monkeypatch.setattr(mix.timeline, 'layout', lambda *a, **kw: dict(tl))

    mix.assemble({'beats': [{'id': 'b1'}]}, 'en', {'b1': clip}, tmp_path / 'build')
    out, rate = mix.read_wav(tmp_path / 'build' / 'narration.wav')
    out = out[:, 0]

    assert rate == SR and len(out) == len(pcm)
    body = float(np.median([_short_term(out, s) for s in np.arange(LEAD + 10, LEAD + SPEECH - 3, 1.0)]))
    first = _short_term(out, LEAD)
    assert abs(first - body) <= 1.5, f'first 3 s of speech {first:.1f} LUFS vs body {body:.1f}'
    assert abs(master.loudness(out, SR) + 18) <= .5
    assert master.true_peak(out, SR) <= -1.5 + 1e-3

"""Every voice meets the mix at one speech level (voice.level, applied where clips are made).

Measured 10/8 after the narration master became one static gain: Kokoro's voices differ by up to 8 LU (script 16:
the narrator about -26 LUFS, a second voice about -21), so a news package's speakers spread 5.8 LU in the video.
Each clip's speech is now set to voice.SPEECH_LUFS: gated (BS.1770) when long enough, else by its short-term level."""
from types import SimpleNamespace

import numpy as np
from scipy.signal import sosfilt

from kinodraw import voice, voice_server
from kinodraw.audio import master

SR = voice.SR


def _speech(seconds, seed) -> np.ndarray:
    """Speech-like: a voiced buzz with two formants in 4 Hz syllables and a short pause every 2 s."""
    rng = np.random.default_rng(seed)
    t = np.arange(round(seconds * SR)) / SR
    phase = 2 * np.pi * np.cumsum(150 * (1 + .08 * np.sin(2 * np.pi * .7 * t))) / SR
    buzz = sum(np.sin(k * phase + rng.random() * 2 * np.pi) / k
               * (1 + 2 * np.exp(-((k * 150 - 700) / 250) ** 2) + 1.5 * np.exp(-((k * 150 - 1800) / 400) ** 2))
               for k in range(1, 30))
    syll = np.clip(np.sin(2 * np.pi * 4 * t), 0, None) ** 2
    pad = np.zeros(round(.1 * SR))
    return np.concatenate([pad, buzz * syll * ((t % 2) < 1.7), pad]).astype(np.float32)


def _measured(path) -> float:
    """The clip's speech as a listener hears it: gated loudness, or for a word or two the K-weighted mean power."""
    x = voice._read_wav(path)
    a, b = voice._voiced(x, SR)
    if b - a >= SR:
        return master.loudness(x[a:b], SR)
    k = sosfilt(master.kweighting(SR), x[a:b].astype(np.float64))
    return float(-.691 + 10 * np.log10((k ** 2).mean()))


# What each fake voice says, and how loud: the spread Kokoro's voices showed (8 LU), plus a one-word line.
TAKES = {'af_quiet': (6.0, -12.0), 'am_loud': (6.0, -4.0), 'af_child': (4.0, -7.0), 'af_terse': (.45, -16.0),
         'af_silent': (2.0, None)}


def _fake_kokoro(monkeypatch):
    class Engine:
        def create_timed(self, text, voice_id, **kwargs):
            seconds, gain_db = TAKES[voice_id]
            audio = np.zeros(round(seconds * SR), np.float32) if gain_db is None else \
                _speech(seconds, len(voice_id)) * np.float32(10 ** (gain_db / 20))
            return audio, SR, None
    monkeypatch.setattr(voice, 'phonemes', lambda text, lang: text)
    monkeypatch.setattr(voice, 'align', lambda text, timings, lang: [0.] * len(text))
    monkeypatch.setattr(voice, '_engine', lambda lang: Engine())


def test_voices_at_different_levels_come_out_level(tmp_path, monkeypatch):
    _fake_kokoro(monkeypatch)
    levels = {v: _measured(voice.synthesize(f'Line by {v}.', 'en', tmp_path, v).wav)
              for v in ('af_quiet', 'am_loud', 'af_child+4')}
    assert max(levels.values()) - min(levels.values()) <= 1.5, levels
    assert all(abs(lv - voice.SPEECH_LUFS) <= .75 for lv in levels.values()), levels
    for v in levels:                                    # and no clipping on the way up
        assert master.true_peak(voice._read_wav(voice.synthesize(f'Line by {v}.', 'en', tmp_path, v).wav), SR) \
            <= voice.SPEECH_DBTP + .1


def test_a_one_word_line_is_matched_by_its_short_term_level(tmp_path, monkeypatch):
    _fake_kokoro(monkeypatch)
    long = _measured(voice.synthesize('A whole sentence of narration.', 'en', tmp_path, 'am_loud').wav)
    short = _measured(voice.synthesize('Fine.', 'en', tmp_path, 'af_terse').wav)
    assert abs(short - long) <= 1.5, (short, long)


def test_a_clip_with_no_speech_is_left_alone(tmp_path, monkeypatch):
    _fake_kokoro(monkeypatch)
    clip = voice.synthesize('...', 'en', tmp_path, 'af_silent')
    x = voice._read_wav(clip.wav)
    assert len(x) == 2 * SR and not np.any(x)
    assert voice.level(np.zeros(SR, np.float32), SR).tolist() == [0.] * SR


def test_two_voices_in_one_beat_meet_at_one_level(tmp_path, monkeypatch):
    """speak() joins each speaker's synthesize() clip: a quiet narrator and a loud character end level."""
    _fake_kokoro(monkeypatch)
    parts = [(SimpleNamespace(said='She said,', index=[0] * 9, speaker=None, cut_off=False), 'af_quiet', 1.),
             (SimpleNamespace(said='Go now.', index=[0] * 7, speaker='kid', cut_off=False), 'am_loud', 1.)]
    monkeypatch.setattr('kinodraw.speech.spoken_times', lambda spoken, index, times: [0.] * len(spoken))
    clip = voice.speak('She said, "Go now."', parts, 'en', tmp_path)
    x = voice._read_wav(clip.wav)
    half = round(6.1 * SR)                               # the first part's 6.2 s, trimmed to its voice
    first, second = master.loudness(x[:half - SR // 4], SR), master.loudness(x[half + SR // 2:], SR)
    assert abs(first - second) <= 1.5, (first, second)


def test_a_voice_server_clip_is_level_matched_too(tmp_path, monkeypatch):
    quiet = _speech(5.0, 3) * np.float32(10 ** (-14 / 20))
    monkeypatch.setattr(voice_server, 'speech', lambda server, said, speed: b'audio')
    monkeypatch.setattr(voice_server, 'decode', lambda data: quiet.copy())
    server = voice_server.Server('http://127.0.0.1:9', 'tts-1', 'alloy')
    clip = voice_server.synthesize('A line from the server.', 'en', tmp_path, server)
    assert abs(_measured(clip.wav) - voice.SPEECH_LUFS) <= .75

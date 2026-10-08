"""The music bed against the voice, measured as the gauntlet's tools/bedlevel.py measures a render: the bed is the mix
minus the best-fitting narration; in speech gaps its loudest tenth of 50 ms windows sits at least 12 dB under the
voice's median, a music-only end card at least 12 LU under the speech, and a calm story fades out at the end."""
import numpy as np
import pytest

from kinodraw import pipeline
from kinodraw.audio import master, mix

SR = mix.SR


def _narration(seconds=20., speaking=14., seed=1):
    """Sentences of voiced syllables with real pauses between them (0.6-0.9 s), silent after ``speaking`` s."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    syllables = np.sin(2 * np.pi * 4 * t) > -.3
    sentences = (t % 3.4) < 2.6
    voice = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((150, 1), (300, .6), (450, .4), (900, .2), (1800, .1)))
    x = (voice + .1 * rng.standard_normal(len(t))) * syllables * sentences * (t < speaking - .2)
    x = x.astype(np.float32)
    return x * np.float32(10 ** ((-18 - master.loudness(x, SR)) / 20))


def _project(tmp_path, mood=None, **board):
    mix.write_wav(tmp_path / 'narration.wav', _narration())
    board = {'look': 'whiteboard', 'title': {'en': 'Bed level'}, 'chapters': [{'id': 'main', 'kind': 'section'}],
             **board}
    tl = {'duration': 20.0, 'audio': 'narration.wav', 'language': 'en', 'captions': [],
          'chapters': [{'id': 'main', 'start': 0, 'end': 14.3}], 'beat_order': ['b1'],
          'beats': {'b1': {'start': 0., 'speech_end': 14., 'end': 14.3}}, 'end_card': {'start': 14.3, 'end': 20.}}
    cfg = {'lang': 'en', 'director_v3': True,
           'plan_v3': {'style': {'mode': 'whiteboard', 'music_mood': mood or 'warm', 'tempo_bpm': 96},
                       'scenes': [{'treatment': 'whiteboard', 'beat_ids': ['b1'], 'actions': []}], 'cast': []}}
    return board, tl, cfg


def _measure(x, voice, tl):
    """(gap margin dB, tail margin LU, fade-out dB) as tools/bedlevel.py computes them."""
    mono = x.mean(1).astype(np.float64)
    voice = voice.astype(np.float64)
    last = max(b['speech_end'] for b in tl['beats'].values())
    inside = slice(0, int(last * SR))
    gain = np.dot(mono[inside], voice[inside]) / np.dot(voice[inside], voice[inside])
    said, bed = gain * voice, mono - gain * voice
    w = SR // 20
    db = lambda y: 10 * np.log10((y[:len(y) // w * w].reshape(-1, w) ** 2).mean(1) + 1e-12)
    v, b = db(said), db(bed)
    t = (np.arange(len(v)) + .5) * .05
    within = t <= last
    gap = np.median(v[within & (v > -45)]) - np.percentile(b[within & (v < -50)], 90)
    tail = mono[int((last + .3) * SR):]
    tail_margin = master.loudness(said[inside], SR) - master.loudness(tail, SR)
    body = 10 * np.log10((tail[:len(tail) // (SR * 4 // 10) * (SR * 4 // 10)].reshape(-1, SR * 4 // 10) ** 2).mean(1))
    fade = 20 * np.log10(np.sqrt((mono[-SR // 4:] ** 2).mean()) + 1e-12) - np.median(body)
    return gap, tail_margin, fade


@pytest.mark.parametrize('mood', ['warm', 'playful', 'dramatic', 'calm'])
def test_the_planned_score_stays_12_db_under_the_voice_in_gaps_and_on_the_end_card(tmp_path, mood):
    board, tl, cfg = _project(tmp_path, mood)
    x = mix.read_wav(pipeline._hybrid_audio(board, tl, tmp_path, cfg))[0]
    gap, tail, fade = _measure(x, mix.read_wav(tmp_path / 'narration.wav')[0][:, 0], tl)
    assert gap >= 12 and tail >= 12, (mood, round(gap, 1), round(tail, 1))
    assert abs(master.loudness(x, SR) + 14) < .5
    if mood == 'calm':
        assert fade <= -20, fade                                   # a calm story fades out


@pytest.mark.parametrize('look', ['whiteboard', 'collage'])
def test_the_bundled_bed_stays_12_db_under_the_voice_in_gaps_and_on_the_end_card(tmp_path, look):
    board, tl, _ = _project(tmp_path, look=look)
    x = mix.read_wav(mix.mix(board, tl, tmp_path))[0]
    gap, tail, _ = _measure(x, mix.read_wav(tmp_path / 'narration.wav')[0][:, 0], tl)
    assert gap >= 12 and tail >= 12, (look, round(gap, 1), round(tail, 1))


def test_a_bed_already_quiet_enough_is_left_alone():
    voice = _narration()
    tl = {'beats': {'b1': {'start': 0., 'speech_end': 14., 'end': 14.3}}, 'duration': 20.}
    quiet = np.full((len(voice), 2), 1e-4, np.float32)
    assert np.array_equal(mix.fit_bed(voice, quiet, tl), quiet)

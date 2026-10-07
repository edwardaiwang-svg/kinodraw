"""The procedural score: determinism, the beat-grid contract, swells and hushes at marks, sections, the saved
recording choice and the time budget."""
import json
import time

import numpy as np
import pytest
from scipy.signal import sosfilt, butter

from kinodraw import pipeline
from kinodraw.audio import master, mix, procedural, score
from scripts.score_preview import fake_narration

SR = mix.SR


def _cold():
    for cached in (procedural.mallet, procedural.bass_note, procedural.hit, procedural.riser, procedural.room,
                   procedural._wave):
        cached.cache_clear()


def _db(x):
    return 10 * np.log10((np.asarray(x, np.float64) ** 2).mean() + 1e-20)


def test_the_procedural_score_is_byte_identical_for_equal_inputs():
    args = dict(duration=20, music_mood='dramatic', tempo_bpm=96, narration=fake_narration(20), seed=7,
                track='procedural', sections=[8.], marks=[(12., 1.), (16., -.7, 2.)])
    a = score.render(**args)
    _cold()                                          # caches only save time: a cold render is the same bytes
    b = score.render(**args)
    assert a.track == 'procedural' and a.music.dtype == np.float32 and a.music.shape == (20 * SR, 2)
    assert a.music.tobytes() == b.music.tobytes() and a.audio.tobytes() == b.audio.tobytes()
    assert np.array_equal(a.beats, b.beats) and np.array_equal(a.duck_gain, b.duck_gain)
    assert not np.array_equal(a.music, score.render(**{**args, 'seed': 8}).music)
    assert not np.array_equal(a.music, score.render(**{**args, 'music_mood': 'bright'}).music)


@pytest.mark.parametrize('bpm', [72., 96., 120., 133., 180.])
def test_the_procedural_beat_grid_starts_at_zero_and_the_notes_follow_it(bpm):
    result = score.render(16, 'bright', bpm, track='procedural', seed=3)
    assert result.bpm == bpm and result.beats[0] == 0
    assert np.allclose(np.diff(result.beats), 60 / bpm) and result.beats[-1] < 16
    assert np.array_equal(result.beats, score.beat_grid(16, bpm))
    # The attacks land on that grid's sixteenths (eighths at a half-time feel): folded at the step, the rises of
    # the 2-8 kHz amplitude (strikes and shakes) peak within a few ms after the grid line.
    step = 60 / bpm / 4 * (2 if bpm > 150 else 1)
    band = sosfilt(butter(4, [2000, 8000], 'bandpass', fs=SR, output='sos'), result.music.mean(1))
    hop = SR // 1000
    amp = np.sqrt((band[:len(band) // hop * hop].reshape(-1, hop) ** 2).mean(1))
    rise = np.maximum(0, np.diff(amp, prepend=0))
    t = np.arange(len(rise)) * hop / SR
    keep = (t > 1.6) & (t < 14)                       # past the fade-in
    bins = np.linspace(-step / 2, step / 2, int(step / .002) + 1)
    hist = np.histogram((t[keep] + step / 2) % step - step / 2, bins, weights=rise[keep])[0]
    peak = bins[np.argmax(hist)] + .001
    assert -.004 <= peak <= .012 and hist.max() > 2 * hist.mean()


@pytest.mark.parametrize('mood', ['dramatic', 'bright', 'calm', 'mysterious', 'somber', 'warm', 'playful',
                                  'tense', 'uplifting', 'curious', 'neutral', 'discovery', 'unknown'])
def test_every_mood_is_mastered_with_the_music_under_the_narration(mood):
    voice = fake_narration(30)
    result = score.render(30, mood, 110, voice, track='procedural', seed=1)
    assert np.isfinite(result.music).all() and np.max(np.abs(result.music[[0, -1]])) == 0
    assert abs(master.loudness(result.audio, SR) - mix.MASTER_LUFS) <= 1
    assert master.true_peak(result.audio, SR) <= mix.CEILING_DBTP + .05
    speech = slice(6 * SR, 8 * SR)                    # inside a narration phrase
    assert _db(voice[speech]) - _db(result.music[speech]) > 12


def test_marks_swell_into_climaxes_and_hush_tender_lines():
    plain = procedural.compose(40, 'dramatic', 96, seed=5)
    marked = procedural.compose(40, 'dramatic', 96, seed=5, marks=[(20., 1.), (30., -1., 5.)])
    before, at = slice(round(19 * SR), round(20 * SR)), slice(round(20 * SR), round(21 * SR))
    assert _db(marked[before]) - _db(plain[before]) > 3       # the riser and drum roll build into the mark
    assert _db(marked[at]) - _db(plain[at]) > 6               # the boom, crash and stab land on it
    assert abs(_db(marked[4 * SR:12 * SR]) - _db(plain[4 * SR:12 * SR])) < .01   # well before: unchanged
    tender = slice(round(30.8 * SR), round(34.5 * SR))
    assert _db(plain[tender]) - _db(marked[tender]) > 4       # thinner and softer under the tender line
    t, e = procedural.energy_curve(40, .5, 2.5, [(20., 1., 0.), (30., -1., 5.)])
    assert e[np.searchsorted(t, 20.)] == pytest.approx(1) and e[np.searchsorted(t, 32.)] < .2


def test_a_section_start_changes_the_music_from_its_bar_on():
    plain = procedural.compose(30, 'warm', 96, seed=2)
    sectioned = procedural.compose(30, 'warm', 96, seed=2, sections=[15.2])   # the bar line at 15 s
    run = round((15 - 2.5) * SR - SR // 50)           # the bar before it runs up into the section (notes move <= 8 ms)
    # Unchanged before that bar (to float rounding: the FFT reverb spreads ulp-sized differences over the stem).
    assert np.abs(plain[:run] - sectioned[:run]).max() < 1e-6
    assert not np.allclose(plain[15 * SR:20 * SR], sectioned[15 * SR:20 * SR], atol=1e-3)


def test_story_marks_come_from_chapters_cues_and_tender_narration():
    tl = {'duration': 30., 'language': 'en', 'beat_order': ['a', 'b', 'c'], 'end_card': {'start': 28.},
          'chapters': [{'id': 'intro', 'start': 0.}, {'id': 's1', 'start': 9.5}],
          'beats': {'a': {'start': 0.}, 'b': {'start': 10.}, 'c': {'start': 20.}}}
    board = {'beats': [{'id': 'a', 'spoken': {'en': 'Kojo roared.'}},
                       {'id': 'b', 'spoken': {'en': 'Mara laid her paw gently on his.'}},
                       {'id': 'c', 'spoken': {'en': 'Pendo slept.'}}]}
    cues = [{'t': 2.5, 'kind': 'roar'}, {'t': 21., 'kind': 'whimper'}, {'t': 5., 'kind': 'whoosh'}]
    sections, marks = score.story_marks(board, tl, cues)
    assert sections == [9.5]
    assert marks == [(2.5, 1., 0.), (10., -.7, 10.), (20., -.8, 8.)]


def test_projects_play_the_procedural_score_unless_they_saved_a_recording(tmp_path):
    assert score.source(True, 'warm', 96) == ('procedural', 96.)
    assert score.source(None, 'bright', 129) == ('procedural', 129.)
    assert score.source({'secondary': 'natural_vibes'}, 'calm', 80) == ('procedural', 80.)
    assert score.source({'primary': 'natural_vibes'}, 'bright', 129) == ('natural_vibes', 100.)
    with pytest.raises(ValueError):
        score.source({'primary': 'missing'}, 'bright', 129)
    # finish's hybrid audio: the saved recording plays at its measured grid; otherwise the procedural score.
    build = tmp_path / 'build'
    build.mkdir()
    mix.write_wav(build / 'narration.wav', fake_narration(12)[:, None])
    tl = {'duration': 12., 'audio': 'narration.wav', 'language': 'en', 'beat_order': ['a'],
          'beats': {'a': {'start': 0.}}, 'chapters': [{'id': 'intro', 'start': 0.}, {'id': 's1', 'start': 6.}]}
    cfg = {'lang': 'en', 'plan_v3': {'style': {'music_mood': 'bright', 'tempo_bpm': 129}}}
    for music, track, bpm in (({'primary': 'natural_vibes'}, 'natural_vibes', 100.),
                              (True, 'procedural', 129.)):
        board = {'title': {'en': 'A story'}, 'music': music, 'beats': [{'id': 'a', 'spoken': {'en': 'Hello.'}}]}
        path = pipeline._hybrid_audio(board, tl, build, cfg)
        saved = json.loads((build / 'score.json').read_text(encoding='utf-8'))
        assert saved['track'] == track and saved['bpm'] == bpm and saved['beats'][0] == 0
        assert np.allclose(np.diff(saved['beats']), 60 / bpm) and saved['sections'] == [6.]
        assert abs(master.loudness(mix.read_wav(path)[0], SR) - mix.MASTER_LUFS) <= 1


def test_a_minute_of_procedural_score_takes_under_two_cpu_seconds():
    _cold()
    started = time.process_time()
    music = procedural.compose(60, 'bright', 120, seed=9, sections=[20., 40.], marks=[(30., 1.), (50., -.7, 4.)])
    used = time.process_time() - started
    assert music.shape == (60 * SR, 2)
    assert used < 2., f'{used:.2f} s of CPU for 60 s of music'

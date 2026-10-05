"""Mood score timing, sidechain, independent loudness measurement and procedural effects."""
import hashlib

import numpy as np
import pytest
from scipy.signal import sosfilt

from kinodraw.audio import master, mix, score, sfx, synth_sfx
from scripts.score_preview import fake_narration, measured_lufs

SR = mix.SR


def test_cached_measurements_match_the_bundled_recordings():
    assert set(score.tags()) == {p.stem for p in mix.MUSIC.glob('*.mp3')}
    for slug, tag in score.tags().items():
        assert tag['sha256'] == hashlib.sha256((mix.MUSIC / f'{slug}.mp3').read_bytes()).hexdigest()
        assert tag['moods'] and 60 <= tag['bpm'] <= 200
        assert 0 <= tag['downbeat'] < 240 / tag['bpm']
        assert max(abs(bpm / tag['bpm'] - 1) for bpm in tag['halves_bpm']) < .01


def test_mood_then_tempo_select_the_recording():
    assert score.choose('bright', 130) == 'fresh_focus'
    assert score.choose('discovery', 120) == 'inventing_flight'
    assert score.choose('calm', 100) == 'natural_vibes'
    assert score.choose('calm', 104) == 'fresh_focus'
    assert score.choose('unmatched', 145) == 'inventing_flight'


@pytest.mark.parametrize('bpm', [100., 120., 129., 133., 144.997583])
def test_beat_grid_spacing_matches_tempo(bpm):
    grid = score.beat_grid(30, bpm, phase=.142)
    assert grid[0] == pytest.approx(.142)
    assert np.all((grid >= 0) & (grid < 30))
    assert np.all(np.abs(np.diff(grid) / (60 / bpm) - 1) < .01)


def test_bar_loops_are_exact_continuous_and_keep_the_grid():
    bpm, duration = 120., 13.12345
    t = np.arange(7 * SR) / SR
    # Three audible bars plus a tail, with clicks on the source beats.
    source = (.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    for pos in np.arange(0, 6.5, .5):
        source[round(pos * SR):round(pos * SR) + 96] += .3 * np.hanning(96)
    out = score.loop(source, duration, bpm)
    assert len(out) == round(duration * SR) and out.dtype == np.float32
    assert np.array_equal(out, score.loop(source, duration, bpm))
    assert np.max(np.abs(np.diff(out))) < .02
    for pos in (4., 6., 8., 10., 12.):
        window = out[round(pos * SR):round(pos * SR) + 96]
        assert window.max() > .35                  # the repeated accents stay on the beat


@pytest.mark.parametrize('slug', ['fresh_focus', 'natural_vibes', 'inventing_flight'])
def test_real_beds_extend_past_their_ends_without_silent_seams(slug):
    tag = score.tags()[slug]
    audio = score._track(slug)
    duration = tag['duration'] + 10.123
    out = score.loop(audio, duration, tag['bpm'], tag['downbeat'])
    assert out.shape == (round(duration * SR), 2)
    bar = 240 / tag['bpm']
    # The loop's overlap starts on an integer bar and remains audible on both sides.
    end = (np.flatnonzero(np.abs(audio).max(1) > 1e-3)[-1] + 1) / SR
    seam = round((int((end - tag['downbeat']) / bar) - 1) * bar * SR)
    source_seam = round(tag['downbeat'] * SR) + seam
    assert np.array_equal(out[seam - 1:seam + 1], audio[source_seam - 1:source_seam + 1])
    for start in (seam - SR // 4, seam, seam + SR // 4):
        assert np.sqrt(np.mean(out[start:start + SR // 4] ** 2)) > .001


def test_ducking_lowers_music_under_speech_and_recovers():
    voice = np.zeros(8 * SR, np.float32)
    voice[2 * SR:4 * SR] = .2
    gain = score.ducking(voice)
    music = np.full((len(voice), 2), .1, np.float32)
    ducked = music * gain[:, None]
    depth = 20 * np.log10(np.sqrt(np.mean(music[3 * SR:4 * SR] ** 2)) /
                         np.sqrt(np.mean(ducked[3 * SR:4 * SR] ** 2)))
    assert depth >= 6 and depth == pytest.approx(10, abs=.1)
    assert gain[SR] == 1 and gain[7 * SR] > .99
    db = -20 * np.log10(gain)
    assert db[round(2.08 * SR)] == pytest.approx(10 * (1 - np.exp(-1)), abs=.5)
    assert db[round(4.4 * SR)] == pytest.approx(10 * np.exp(-1), abs=.2)
    # Stereo RMS measures energy, including opposite-polarity channels, rather than cancelling them.
    assert np.array_equal(gain, score.ducking(np.stack([voice, -voice], 1)))


def test_render_is_deterministic_and_applies_the_sidechain():
    voice = fake_narration(10)
    a = score.render(10, 'bright', 129, voice)
    b = score.render(10, 'bright', 129, voice)
    assert np.array_equal(a.music, b.music) and np.array_equal(a.audio, b.audio)
    assert np.array_equal(a.beats, b.beats)
    assert a.music.shape == a.audio.shape == (10 * SR, 2)
    assert a.bpm == score.tags()[a.track]['bpm']
    assert np.allclose(np.diff(a.beats), 60 / a.bpm)
    plain = score.render(10, 'bright', 129)
    expected = plain.music * a.duck_gain[:, None]
    assert np.array_equal(a.music, expected)
    energy_ratio = (a.music[6 * SR:8 * SR].astype(float) ** 2).sum() / (plain.music[6 * SR:8 * SR].astype(float) ** 2).sum()
    assert -10 * np.log10(energy_ratio) >= 6
    assert np.max(np.abs(a.music[[0, -1]])) == 0


@pytest.mark.parametrize('mood', ['bright', 'neutral', 'discovery', 'mysterious'])
def test_preview_loudness_matches_the_existing_master_target(tmp_path, mood):
    result = score.render(30, mood, 129, fake_narration(), ambient=True)
    path = tmp_path / f'{mood}.wav'
    mix.write_wav(path, result.audio)
    assert abs(measured_lufs(path) - mix.MASTER_LUFS) <= 1
    assert master.true_peak(result.audio, SR) <= mix.CEILING_DBTP + .05
    assert (result.track is None) == (mood == 'mysterious')


def test_ambient_pad_is_quiet_deterministic_and_mood_specific():
    a = score.ambient_pad(6, 'mysterious')
    assert a.shape == (6 * SR, 2) and a.dtype == np.float32
    assert np.array_equal(a, score.ambient_pad(6, 'mysterious'))
    assert not np.array_equal(a, score.ambient_pad(6, 'bright'))
    assert not np.array_equal(a, score.ambient_pad(6, 'mysterious', seed=1))
    assert master.loudness(a, SR) <= -29
    assert np.abs(a).max() < .15 and np.max(np.abs(a[[0, -1]])) == 0


@pytest.mark.parametrize('kind', synth_sfx.KINDS)
def test_each_sfx_is_deterministic_non_silent_and_at_approved_levels(kind):
    x = synth_sfx.render(kind)
    assert x.dtype == np.float32 and x.shape == (round(synth_sfx.KINDS[kind] * SR),)
    assert np.array_equal(x, synth_sfx.render(kind))
    assert np.isfinite(x).all() and .001 < np.abs(x).max() <= .7
    assert x[0] == x[-1] == 0
    y = sosfilt(master.kweighting(SR), x)
    w = round(.1 * SR)
    energy = np.r_[0., np.cumsum(y * y)]
    loudest = (energy[w:] - energy[:-w]).max() if len(y) > w else energy[-1]
    lufs = -.691 + 10 * np.log10(loudest / w)
    assert lufs == pytest.approx(sfx.LEVEL[synth_sfx.LEVEL_KIND[kind]], abs=.1)


def test_empty_scores_and_invalid_timing():
    assert score.render(0).audio.shape == (0, 2)
    assert score.ducking(np.empty(0)).shape == (0,)
    assert np.array_equal(score.ducking(np.zeros(SR)), np.ones(SR))
    short = score.render(.1, 'mysterious', ambient=True, narration=np.ones(round(.1 * SR)))
    assert master.true_peak(short.audio, SR) <= mix.CEILING_DBTP + .05
    assert np.abs(short.music).max() < .15
    for bpm in (0, -120, np.nan, np.inf):
        with pytest.raises(ValueError):
            score.render(1, tempo_bpm=bpm)
    with pytest.raises(ValueError):
        score.render(-1)
    with pytest.raises(ValueError):
        score.loop(np.ones(SR), 10, 120)
    with pytest.raises(ValueError):
        score.render(1, narration=np.zeros((SR, 3)))

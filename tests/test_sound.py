"""The sound kit: sound effects on their contact frames, BS.1770 loudness, the limiter, and the mix per look."""
import json
import re
import subprocess
from functools import lru_cache

import numpy as np
import pytest
from scipy.signal import sosfilt

from kinodraw.audio import master, mix, sfx

SR = mix.SR
PERCUSSIVE = ['pop', 'slam', 'letter', 'type', 'stamp', 'impact', 'tap', 'kick']


@pytest.fixture(scope='module', autouse=True)
def tracks_once():
    """Decode and measure each bundled track once for the whole module (the mixes below reuse them)."""
    patch = pytest.MonkeyPatch()
    patch.setattr(mix, 'decode', lru_cache(None)(mix.decode))
    patch.setattr(mix, 'loudness', lru_cache(None)(mix.loudness))
    yield
    patch.undo()


def _pink(seconds, seed=0):
    rng = np.random.default_rng(seed)
    x = np.stack([sfx._pink(rng, int(seconds * SR)) for _ in range(2)], 1)
    return (x / np.abs(x).max()).astype(np.float32)


def _speech(seconds, seed=1):
    """Speech-like: a voiced buzz in syllables and phrases, with pauses."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    words = (np.sin(2 * np.pi * 4 * t) > .2) * (np.sin(2 * np.pi * .3 * t) > -.5)
    voice = np.sin(2 * np.pi * 180 * t) + .5 * np.sin(2 * np.pi * 360 * t) + .2 * rng.standard_normal(len(t))
    return (.2 * voice * words).astype(np.float32)


def _project(tmp_path, **board):
    """A 20 s narration with chapters and music windows, as build_audio leaves it."""
    mix.write_wav(tmp_path / 'narration.wav', _speech(20))
    board = {'chapters': [{'id': 'intro', 'kind': 'intro'}, {'id': 's1', 'kind': 'section'},
                          {'id': 'outro', 'kind': 'outro'}], **board}
    tl = {'duration': 20.0, 'audio': str(tmp_path / 'narration.wav'),
          'chapters': [{'id': 'intro', 'start': 0, 'end': 4}, {'id': 's1', 'start': 4, 'end': 14},
                       {'id': 'outro', 'start': 14, 'end': 15}],
          'music': [{'start': 0, 'end': 4}, {'start': 8, 'end': 11}, {'start': 15, 'end': 20}]}
    return board, tl


def _cues(n=40):
    kinds = list(sfx.LEVEL)
    return [{'t': .4 + .45 * i, 'kind': kinds[i % len(kinds)], 'id': f'c{i}', 'x': (i % 5) / 4, 'dur': .6}
            for i in range(n)]


# ------------------------------------------------------------------ sound effects
def test_the_same_cues_always_sound_the_same():
    cues = _cues()
    a, b = sfx.render(cues, 20), sfx.render(list(reversed(cues)), 20)
    assert a.dtype == np.float32 and a.shape == (20 * SR, 2)
    assert np.array_equal(a, b) and np.abs(a).max() > .01
    assert not np.array_equal(a, sfx.render(cues, 20, seed=1))
    moved = [dict(c, t=c['t'] + 1) for c in cues[:1]]           # a hit depends on its own id, not on its neighbours
    alone = sfx.render(cues[:1], 20)
    assert np.array_equal(np.roll(alone, SR, axis=0), sfx.render(moved, 20))


@pytest.mark.parametrize('kind', sorted(sfx.LEVEL))
def test_each_hit_lands_on_its_cue(kind):
    at = round(1.0 * SR)
    for i in range(12):                                          # several ids: several variants
        y = np.abs(sfx.render([{'t': 1.0, 'kind': kind, 'id': f'{kind}{i}', 'dur': .7}], 2.5)).max(1)
        first = np.flatnonzero(y)[0]
        if kind == 'write':                                      # scribbles from t for dur
            assert abs(first - at) <= SR // 1000 and np.flatnonzero(y)[-1] <= at + .7 * SR + SR // 1000
        elif kind in ('whoosh', 'riser'):                        # swells into t
            assert abs(int(np.argmax(y)) - at) <= SR // 1000
            assert kind == 'whoosh' or at - first > .6 * SR      # the riser builds over dur
        else:                                                    # the transient peak is the contact frame
            assert abs(first + int(np.argmax(y[first:first + int(sfx.ATTACK * SR)])) - at) <= SR // 1000
            assert kind not in PERCUSSIVE or abs(int(np.argmax(y)) - at) <= SR // 1000


@pytest.mark.parametrize('kind', ['roar', 'whimper', 'nudge', 'hyena_cackle', 'swipe', 'breath_puff'])
def test_creature_sounds_play_from_their_cue(kind):
    cue = {'t': 1.0, 'kind': kind, 'id': f'{kind}.0'}
    y = sfx.render([cue], 3)
    heard = np.flatnonzero(np.abs(y).max(1) > 1e-4)
    assert len(heard) and 0 <= SR - heard[0] <= sfx.ATTACK * SR + SR // 1000      # from (just before) t
    assert np.array_equal(y, sfx.render([cue], 3))                                # the same id sounds the same
    assert not np.array_equal(y, sfx.render([dict(cue, id=f'{kind}.1')], 3))
    assert np.abs(y).max() <= .71 * 10 ** (3 / 20)                                 # synth_sfx's .7 peak, +3 dB at most


def test_action_sounds_sit_8_to_14_lu_under_the_narration():
    """Dropped mid-word into a -18 LUFS narration and ducked as the mix ducks them, each action sound's loudest 400 ms
    sits 8-14 LU (median of 13 drops) under the narration's loudest 400 ms around it: heard, never louder than speech."""
    def momentary(x):
        y = sosfilt(master.kweighting(SR), x.reshape(len(x), -1).astype(np.float64), axis=0)
        p = (y[:len(y) // (SR // 10) * (SR // 10)].reshape(-1, SR // 10, y.shape[1]) ** 2).sum((1, 2)) / (SR // 10)
        return -.691 + 10 * np.log10(((p[:-3] + p[1:-2] + p[2:-1] + p[3:]) / 4).max())
    speech = _speech(20)
    speech *= 10 ** ((-18 - master.loudness(speech, SR)) / 20)
    duck = (1 + (10 ** (mix.SFX_DUCK_DB / 20) - 1) * mix.envelope(speech))[:, None]
    for kind in ('roar', 'whimper', 'nudge', 'hyena_cackle', 'swipe', 'breath_puff', 'impact'):
        under = []
        for n, t in enumerate(np.arange(1, 18, 1.37)):
            w = slice(round(t * SR) - SR // 10, round(t * SR) + round(1.5 * SR))
            fx = sfx.render([{'t': t, 'kind': kind, 'id': f'{kind}.{n}'}], 20) * duck
            under.append(momentary(speech[w]) - momentary(fx[w]))
        assert 8 <= np.median(under) <= 14, (kind, np.median(under))


@pytest.mark.parametrize('kind,dur', [('rain', 4.5), ('wind', 4.5), ('fog_drone', 4.5), ('transition_whoosh', .65)])
def test_beds_and_transition_whooshes_play_from_their_cue_for_dur(kind, dur):
    y = np.abs(sfx.render([{'t': 1.0, 'kind': kind, 'dur': dur, 'id': f'{kind}.0'}], 7)).max(1)
    heard = np.flatnonzero(y)
    assert abs(heard[0] - SR) <= SR // 1000 and abs(heard[-1] - (1 + dur) * SR) <= .01 * dur * SR


def test_hits_of_a_kind_keep_their_distance():
    pops = [{'t': 1 + .04 * i, 'kind': 'pop', 'id': f'p{i}'} for i in range(10)]            # 60 ms apart at least
    letters = [{'t': 1 + .03 * i, 'kind': 'letter', 'id': f'l{i}'} for i in range(10)]      # 35 ms for letters
    kept = [c for i, c in enumerate(pops + letters) if i % 2 == 0]
    assert np.array_equal(sfx.render(pops + letters, 3), sfx.render(kept, 3))
    typed = [{'t': 1 + .04 * i, 'kind': 'type', 'id': f't{i}'} for i in range(10)]            # all kept
    assert np.allclose(sfx.render(typed, 3), sum(sfx.render([c], 3) for c in typed), atol=1e-6)


def test_screen_position_pans_at_constant_power():
    def energy(x):
        y = sfx.render([{'t': .5, 'kind': 'impact', 'id': 'boom', 'x': x}], 1.5).astype(np.float64)
        return (y ** 2).sum(0)
    left, centre, right = energy(0), energy(.5), energy(1)
    assert left[0] > 4 * left[1] and right[1] > 4 * right[0]
    assert np.allclose(left, right[::-1]) and np.isclose(centre[0], centre[1])
    assert np.allclose([left.sum(), right.sum()], centre.sum(), rtol=1e-4)


# ------------------------------------------------------------------ master
def _ffmpeg_lufs(path):
    out = subprocess.run([mix.FFMPEG, '-v', 'error', '-nostats', '-i', str(path), '-af',
                          'ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.I:file=-', '-f', 'null', '-'],
                         capture_output=True, encoding='utf-8', check=True).stdout
    return float(re.findall(r'lavfi\.r128\.I=(-?[\d.]+)', out)[-1])


def test_loudness_agrees_with_ffmpeg(tmp_path):
    x = .4 * _pink(30)
    x[int(10 * SR):int(15 * SR)] *= .02                          # a quiet passage: below the relative gate
    x[int(20 * SR):int(23 * SR)] = 0                              # silence: below the absolute gate
    path = tmp_path / 'pink.wav'
    mix.write_wav(path, x)
    ours = master.loudness(mix.read_wav(path)[0], SR)
    assert abs(ours - _ffmpeg_lufs(path)) < .3
    assert abs(ours - float(mix.loudness(path)['input_i'])) < .3
    tone = (10 ** (-23 / 20) * np.sin(2 * np.pi * 1000 * np.arange(10 * SR) / SR)).astype(np.float32)
    assert abs(master.loudness(np.stack([tone, tone], 1), SR) + 23) < .05      # EBU Tech 3341: -23 dBFS reads -23
    assert master.loudness(np.zeros((SR, 2), np.float32), SR) == -np.inf


def test_true_peak_sees_between_the_samples():
    between = (.5 * np.sin(np.pi / 2 * np.arange(SR) + np.pi / 4)).astype(np.float32)   # samples at 0.35, peaks 0.5
    assert abs(master.true_peak(between, SR) - 20 * np.log10(.5)) < .2


def test_master_reaches_the_target_under_the_ceiling():
    x = .5 * _pink(20, seed=3)
    x[::SR // 2] = .9                                             # clicks
    x[5 * SR:6 * SR] += (.6 * np.sin(np.pi / 2 * np.arange(SR) + np.pi / 4))[:, None]   # peaks between the samples
    y = master.master(x, SR)
    assert y.shape == x.shape and y.dtype == np.float32
    assert abs(master.loudness(y, SR) + 14) < .5 and master.true_peak(y, SR) <= -.95
    quiet = .01 * x
    assert np.array_equal(master.limit(quiet, SR), quiet)         # below the ceiling nothing changes


# ------------------------------------------------------------------ mix per look
BED_RANGE = (15, 24)   # dB of voice over bed on the synthetic buzz; never closer than 15 dB, never buried


def _bed_levels(x, speech):
    """The mix minus its narration (least squares), in 50 ms RMS as the reviewers measure a video: (dB the voice is over
    the bed while it speaks, dB the bed rises in the pauses, quietest 100 ms of the bed inside the video in dBFS)."""
    mono = x.mean(1).astype(np.float64)
    voice = speech.astype(np.float64)
    gain = np.dot(mono, voice) / np.dot(voice, voice)
    bed = mono - gain * voice
    w = SR // 20
    db = lambda y: 10 * np.log10((y[:len(y) // w * w].reshape(-1, w) ** 2).mean(1) + 1e-12)
    said, music = db(gain * voice), db(bed)
    held = mix.envelope(speech)[w // 2::w][:len(said)]                          # phrases, not the gaps between words
    speaking, pause = (said > said.max() - 30) & (held > .9), held < .5
    inside = bed[int(.3 * SR):len(bed) - int(mix.FADE * SR)]                  # past the fade in, before the fade out
    win = inside[:len(inside) // (SR // 10) * (SR // 10)].reshape(-1, SR // 10)
    floor = 20 * np.log10(np.sqrt((win ** 2).mean(1)).min() + 1e-12)
    under = np.median(music[speaking])
    return np.median(said[speaking]) - under, np.median(music[pause]) - under, floor


@pytest.mark.parametrize('look', ['whiteboard', 'collage'])
def test_every_look_has_a_bed_under_the_whole_narration_and_is_mastered(tmp_path, look):
    """Music from the first word to the end, clearly under the voice and rising in the pauses; mastered. (On real
    narrations this bed measures 17.6-17.8 dB under the voice; this buzz reads a few dB more, hence BED_RANGE.)"""
    board, tl = _project(tmp_path, look=look)
    x = mix.read_wav(mix.mix(board, tl, tmp_path))[0]
    over, lift, floor = _bed_levels(x, mix.read_wav(tl['audio'])[0][:, 0])
    assert BED_RANGE[0] <= over <= BED_RANGE[1] and lift >= 4 and floor > -60, (over, lift, floor)
    assert abs(master.loudness(x, SR) + 14) < .5 and master.true_peak(x, SR) <= mix.CEILING_DBTP + .05
    silent = mix.read_wav(mix.mix(dict(board, music=False), tl, tmp_path))[0]     # your choice: no music
    assert _bed_levels(silent, mix.read_wav(tl['audio'])[0][:, 0])[2] < -80


@pytest.mark.parametrize('slug', ['fresh_focus', 'natural_vibes'])
def test_a_looped_track_never_drops_out(slug):
    """The bundled tracks end in a 2 s fade; looped over a long video that fade was a silent gap in the bed."""
    audio, _ = mix.track(slug)
    bed = mix.loop(audio, len(audio) * 2 + 10 * SR).mean(1)
    win = bed[:len(bed) // (SR // 10) * (SR // 10)].reshape(-1, SR // 10)
    assert 20 * np.log10(np.sqrt((win ** 2).mean(1)).min()) > -60


def test_the_bed_is_there_from_the_first_word():
    open_bed = mix.bed(np.zeros(6 * SR, np.float32), [], 'fresh_focus')
    rms = lambda a, b: 20 * np.log10(np.sqrt((open_bed[int(a * SR):int(b * SR)] ** 2).mean()))
    assert rms(.3, .6) > rms(3, 3.3) - 4


def test_the_words_sound_effects_play_in_the_mix(tmp_path):
    board, tl = _project(tmp_path, master=False)
    tl['captions'] = [{'start': 4., 'end': 6., 'text': 'Then the thunder came.', 'words': [4., 4.3, 4.6, 5.2]}]
    x = mix.read_wav(mix.mix(board, tl, tmp_path))[0]
    plain = mix.read_wav(mix.mix(dict(board, sfx=False), tl, tmp_path))[0]
    diff = np.abs(x - plain).max(1)
    assert diff[:int(4.5 * SR)].max() < 1e-3 < diff[int(4.6 * SR):int(5.5 * SR)].max()   # thunder from its word


def _ffmpeg_true_peak(path):
    err = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-map', '0:a:0', '-af',
                          'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr
    return float(re.search(r'True peak:\s+Peak:\s+(-?[\d.]+) dBFS', err[err.rfind('Summary:'):])[1])


def test_the_encoded_video_keeps_the_true_peak_ceiling(tmp_path):
    """AAC adds about half a dB of peaks to a mix limited to -1 dBTP; the mp4 people get still reads -1.0 or lower."""
    from kinodraw import package
    rng = np.random.default_rng(0)
    cues = [{'t': .2 + .13 * i, 'kind': ['impact', 'slam', 'kick', 'pop', 'stamp', 'tap', 'confetti'][i % 7],
             'id': f'c{i}'} for i in range(40)]
    x = master.master(sfx.render(cues, 6) * 30 + .05 * rng.standard_normal((6 * SR, 2)).astype(np.float32), SR)
    mix.write_wav(tmp_path / 'mix.wav', x)
    subprocess.run([package.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=white:s=64x64:r=30:d=6',
                    '-c:v', 'libx264', str(tmp_path / 'silent.mp4')], check=True)
    tl = {'duration': 6.0, 'chapters': [{'start': 0, 'end': 6, 'title': 'One'}]}
    out = tmp_path / 'video.mp4'
    package.mux(tl, tmp_path / 'silent.mp4', tmp_path / 'mix.wav', out, 'en', 'Peaks', tmp_path)
    assert _ffmpeg_true_peak(out) <= -1.0
    assert master.loudness(x, SR) - master.loudness(mix.read_wav(tmp_path / 'mix.wav')[0], SR) < .5  # about as loud
    assert np.corrcoef(x[:, 0], mix.read_wav(tmp_path / 'mix.wav')[0][:, 0])[0, 1] > .99   # the same mix


def test_a_whiteboard_v3_plan_gets_the_score_even_when_it_asks_for_no_music(tmp_path):
    """An all-whiteboard plan used to play music only on the end card, and a plan's music_mood 'none' none at all;
    only your own choice of no music (storyboard music false) leaves the bed out."""
    from kinodraw import pipeline
    board, tl = _project(tmp_path, look='whiteboard', title={'en': 'Bed test'})
    tl.update(beat_order=['b1'], beats={'b1': {'start': 0, 'speech_end': 19, 'end': 20}}, end_card={'start': 20},
              captions=[], language='en')
    cfg = {'lang': 'en', 'director_v3': True,
           'plan_v3': {'style': {'mode': 'whiteboard', 'music_mood': 'none', 'tempo_bpm': 96},
                       'scenes': [{'treatment': 'whiteboard', 'beat_ids': ['b1'], 'actions': []}], 'cast': []}}
    assert pipeline._scored(cfg, board)
    speech = mix.read_wav(tl['audio'])[0][:, 0]
    x = mix.read_wav(pipeline._hybrid_audio(board, tl, tmp_path, cfg))[0]
    over, lift, floor = _bed_levels(x, speech)
    assert BED_RANGE[0] <= over <= BED_RANGE[1] and lift >= 4 and floor > -60, (over, lift, floor)
    assert abs(master.loudness(x, SR) + 14) < .5
    off = mix.read_wav(pipeline._hybrid_audio(dict(board, music=False), tl, tmp_path, cfg))[0]
    assert _bed_levels(off, speech)[2] < -80


def test_animated_looks_are_mastered_with_their_sound_effects(tmp_path):
    board, tl = _project(tmp_path, look='collage')
    cues = _cues() + [{'t': 6.0, 'kind': 'cut', 'id': 'cut-a'}]
    (tmp_path / 'cues.json').write_text(json.dumps({'cues': cues}), encoding='utf-8')
    x = mix.read_wav(mix.mix(board, tl, tmp_path))[0]
    assert abs(master.loudness(x, SR) + 14) < 1 and master.true_peak(x, SR) <= -.95
    plain = mix.read_wav(mix.mix(dict(board, sfx=False), tl, tmp_path))[0]
    assert not np.allclose(x, plain, atol=1e-3)                   # the effects are in the mix
    env = mix.envelope(mix.read_wav(tl['audio'])[0][:, 0])
    bed = mix.bed(env, cues, 'fresh_focus')[int(1.5 * SR):int(18.5 * SR)]           # past the fades
    assert np.sqrt((bed.reshape(-1, SR // 10, 2) ** 2).mean((1, 2))).min() > 1e-4    # under the whole video
    lift = mix.swell(cues, len(env))
    assert np.isclose(20 * np.log10(lift.max()), mix.SWELL_DB, atol=.01) and lift[round(7.6 * SR)] == 1

"""The sound kit: sound effects on their contact frames, BS.1770 loudness, the limiter, and the mix per look."""
import json
import re
import subprocess
from functools import lru_cache

import numpy as np
import pytest

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
def _mix_before(storyboard, tl, out_dir):
    """mix.mix() as it was before the animated looks (the whiteboard must still sound exactly like this)."""
    speech = mix.read_wav(tl['audio'])[0][:, 0]
    total = len(speech)
    music = np.zeros((total, 2), np.float32)
    setting = storyboard.get('music', True)
    if setting:
        tracks = {**mix.DEFAULT_TRACKS, **(setting if isinstance(setting, dict) else {})}
        kinds = {c['id']: c['kind'] for c in storyboard['chapters']}
        spans = {kinds[c['id']]: c for c in tl['chapters']}
        intro_end = spans['intro']['end'] if 'intro' in spans else 0
        outro_start = spans['outro']['start'] if 'outro' in spans else tl['duration']
        env, cache = mix.envelope(speech), {}
        for win in tl['music']:
            a, b = win['start'], min(win['end'], total / SR)
            slug = tracks['primary'] if (a < intro_end + 1 or b > outro_start - 1) else tracks['secondary']
            if slug not in cache:
                path = mix.MUSIC / f'{slug}.mp3'
                audio = mix.decode(path, 2)
                nz = np.flatnonzero(np.abs(audio).max(1) > 1e-3)
                cache[slug] = (audio[nz[0]:nz[-1] + 1] if len(nz) else audio, float(mix.loudness(path)['input_i']))
            audio, lufs = cache[slug]
            n = int((b - a) * SR)
            if n <= 0:
                continue
            seg, pos, xf = np.zeros((n, 2), np.float32), 0, SR
            while pos < n:
                take = min(len(audio), n - pos)
                piece = audio[:take].copy()
                if pos > 0:
                    ramp = np.linspace(0, 1, min(xf, take))[:, None]
                    piece[:len(ramp)] *= ramp
                    seg[pos:pos + len(ramp)] *= (1 - ramp)
                seg[pos:pos + take] += piece
                pos += take - (xf if take == len(audio) else 0)
            g_under, g_open = 10 ** ((mix.UNDER_SPEECH_LUFS - lufs) / 20), 10 ** ((mix.OPEN_LUFS - lufs) / 20)
            i0 = int(a * SR)
            gain = g_open + (g_under - g_open) * env[i0:i0 + n]
            fade = np.ones(n, np.float32)
            f = min(int(mix.FADE * SR), n // 2)
            fade[:f] = np.linspace(0, 1, f) ** 1.5
            fade[n - f:] = np.linspace(1, 0, f) ** 1.5
            music[i0:i0 + n] += seg * (gain * fade)[:, None]
    out = out_dir / 'mix-before.wav'
    mix.write_wav(out, speech[:, None].repeat(2, axis=1) + music)
    return out


@pytest.mark.parametrize('music', [True, False, {'primary': 'inventing_flight'}], ids=['music', 'silent', 'own-track'])
def test_the_whiteboard_mix_is_unchanged(tmp_path, music):
    board, tl = _project(tmp_path, music=music)
    (tmp_path / 'cues.json').write_text(json.dumps({'cues': _cues()}), encoding='utf-8')   # cues alone do not change the whiteboard
    assert mix.mix(board, tl, tmp_path).read_bytes() == _mix_before(board, tl, tmp_path).read_bytes()


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

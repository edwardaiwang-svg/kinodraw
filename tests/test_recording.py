"""Narration from your own recording: the alignment, checked against a take whose timing is known."""
import json
import re
import wave

from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, resample_poly, sosfilt

from doodlestudio import cli, pipeline, voice

needs_models = pytest.mark.skipif(bool(voice.missing_files('en')),
                                  reason='Kokoro models not downloaded (doodle setup --lang en)')
BEATS = [('b001', 'You wrote something worth explaining. A lesson, a story, a big idea. But turning it into a video '
                  'takes days of drawing, recording and editing.'),
         ('b002', "There's a much easier way. Meet Doodle Studio."),
         ('b003', 'Paste your script. Press Make video. A hand draws every idea while the voice reads it.'),
         ('b004', 'Captions, chapters and a thumbnail come with it. No editing. No account. It all runs on your own '
                  'computer.')]
OTHER = ['Bananas are a good source of potassium. They ripen faster in a paper bag, and the peel turns brown in the '
         'fridge.',
         'The council met on Tuesday about parking.',
         'Most cats sleep twelve to sixteen hours a day, mostly in short naps near a warm window.',
         'Water boils at a lower temperature on a mountain, so pasta takes longer to cook up there than at the beach.']
WORD = re.compile(r"(?<![\w'’])\w")
NOISE = .002


def test_a_project_is_narrated_from_its_recording_once_it_has_one(tmp_path, monkeypatch, capsys):
    project = tmp_path / 'video'
    board = pipeline.new_project(Path(__file__).parent / 'fixtures' / 'tiny.md', project)
    calls = []

    def cut(*args):
        calls.append(args)
        (project / 'voice' / 'recording-align.json').write_text(json.dumps(
            {'match': .6, 'beats': [{'id': 'b002', 'match': .3, 'check': True}]}))
        return {}
    monkeypatch.setattr(voice, 'synthesize', lambda text, *a: voice.Clip(Path('guide.wav'), 1., [0.] * len(text)))
    monkeypatch.setattr(voice, 'from_recording', cut)
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: {'duration': 1, 'captions': []})
    (project / 'voice').mkdir()
    (tmp_path / 'Take 1.M4A').write_bytes(b'audio')
    cli.main(['voice', str(project), '--recording', str(tmp_path / 'Take 1.M4A')])
    assert pipeline.settings(project)['recording'] == 'recording.m4a'
    assert (project / 'recording.m4a').read_bytes() == b'audio'
    beats = [(beat['id'], beat['spoken']['en']) for beat in board['beats']]
    assert calls == [(project / 'recording.m4a', beats, 'en', project / 'voice', 'af_heart', 1.0)]
    assert '! b002 matches its text poorly (0.30)' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(['voice', str(project), '--recording', str(tmp_path / 'missing.wav')])
    cli.main(['voice', str(project), '--recording', 'none'])
    assert 'recording' not in pipeline.settings(project) and len(calls) == 1


def test_the_warp_follows_a_known_stretch():
    """Each guide frame held for 1 to 3 frames in the take: the path enters every frame at its first copy."""
    rng = np.random.default_rng(0)
    G = rng.normal(size=(300, 8))
    G /= np.linalg.norm(G, axis=1, keepdims=True)
    hold = rng.integers(1, 4, len(G))
    R = np.repeat(G, hold, axis=0)
    path = voice._dtw(G, R, np.zeros(len(G), int), np.full(len(G), len(R)))
    _, at = np.unique(path[:, 0], return_index=True)
    assert (path[at, 1] == np.r_[0, np.cumsum(hold)[:-1]]).all()


@pytest.fixture(scope='module')
def take(tmp_path_factory):
    """The beats read by another voice, slower (am_michael at 0.85), with uneven pauses between them over low noise,
    as 44.1 kHz stereo: the file, and where each beat is heard and each of its characters starts."""
    tmp = tmp_path_factory.mktemp('take')
    rng = np.random.default_rng(0)
    highpass = butter(2, 80, 'highpass', fs=voice.SR, output='sos')
    parts, truth, t = [np.zeros(round(.4 * voice.SR), np.float32)], [], .4
    for k, (_, text) in enumerate(BEATS):
        clip = voice.synthesize(text, 'en', tmp / 'voice', 'am_michael', .85)
        audio = voice._read_wav(clip.wav)
        n = len(audio) // 240
        level = 10 * np.log10((sosfilt(highpass, audio)[:n * 240].reshape(n, 240) ** 2).mean(1) + 1e-10)
        heard = np.flatnonzero(level > 20 * np.log10(NOISE) + 6)          # what the high-passed take lets you hear
        truth.append({'start': t + heard[0] / 100, 'end': t + (heard[-1] + 1) / 100,
                      'chars': [t + c for c in clip.char_times]})
        gap = round((rng.uniform(.3, 1.2) if k + 1 < len(BEATS) else .6) * voice.SR)
        parts += [audio, np.zeros(gap, np.float32)]
        t += (len(audio) + gap) / voice.SR
    x = np.concatenate(parts)
    x = resample_poly(x + rng.normal(0, NOISE, len(x)).astype(np.float32), 147, 80)
    path = tmp / 'take.wav'
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes((np.clip(np.stack([x, .9 * x], 1), -1, 1) * 32767).astype('<i2').tobytes())
    return path, truth


@pytest.fixture(scope='module')
def aligned(take, tmp_path_factory):
    cache = tmp_path_factory.mktemp('project') / 'voice'
    clips = voice.from_recording(take[0], BEATS, 'en', cache)
    return clips, json.loads((cache / 'recording-align.json').read_text()), cache


@needs_models
def test_a_take_in_another_voice_is_cut_in_its_pauses_and_timed_to_its_words(take, aligned):
    truth, (clips, report, cache) = take[1], aligned
    errors = []
    for k, ((bid, text), row) in enumerate(zip(BEATS, report['beats'])):
        before = truth[k - 1]['end'] if k else 0.
        after = truth[k + 1]['start'] if k + 1 < len(truth) else np.inf
        assert before <= row['start'] <= truth[k]['start'] and truth[k]['end'] <= row['end'] <= after, (row, truth[k])
        clip, times = clips[bid], clips[bid].char_times
        assert clip.duration == pytest.approx(row['end'] - row['start'], abs=.011)
        assert 0 <= times[0] and np.all(np.diff(times) >= 0) and times[-1] <= clip.duration
        errors += [row['start'] + times[m.start()] - truth[k]['chars'][m.start()] for m in WORD.finditer(text)]
        guide = voice.synthesize(text, 'en', cache)
        loud = [np.percentile(voice._spectrum(voice._read_wav(w))[0], 95) for w in (clip.wav, guide.wav)]
        assert loud[0] == pytest.approx(loud[1], abs=3)             # at the guide's speech level
    errors = np.abs(errors)
    assert np.median(errors) <= .06 and np.percentile(errors, 95) <= .15, (np.median(errors), np.percentile(errors, 95))
    assert not any(row['check'] for row in report['beats']) and report['match'] > voice.MATCH


@needs_models
def test_a_second_run_reuses_the_cut(take, aligned, monkeypatch):
    clips, _, cache = aligned
    monkeypatch.setattr(voice, '_decode', lambda path: pytest.fail('decoded again'))
    assert voice.from_recording(take[0], BEATS, 'en', cache) == clips


@needs_models
def test_a_reading_of_another_script_is_refused(take, aligned):
    other = [(bid, text) for (bid, _), text in zip(BEATS, OTHER)]
    with pytest.raises(ValueError, match='does not sound like a reading of this script'):
        voice.from_recording(take[0], other, 'en', aligned[2])


@needs_models
def test_a_take_of_part_of_the_script_is_refused(take, aligned, tmp_path):
    with wave.open(str(take[0])) as w:
        head = w.readframes(5 * w.getframerate())
        params = w.getparams()
    part = tmp_path / 'part.wav'
    with wave.open(str(part), 'wb') as w:
        w.setparams(params)
        w.writeframes(head)
    with pytest.raises(ValueError, match='record the whole script'):
        voice.from_recording(part, BEATS, 'en', aligned[2])


@needs_models
def test_the_cut_keeps_the_top_of_a_real_voice(take, tmp_path):
    """The guide stops at 12 kHz, a real voice does not: clips are cut from the take at the mix's rate."""
    with wave.open(str(take[0])) as w:
        rate, x = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, 2) / 32768
    x = x + .03 * np.sin(2 * np.pi * 15000 * np.arange(len(x)) / rate)[:, None]            # a voice's air
    bright = tmp_path / 'bright.wav'
    with wave.open(str(bright), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())
    clip = voice.from_recording(bright, BEATS, 'en', tmp_path / 'voice')[BEATS[0][0]]
    with wave.open(str(clip.wav)) as w:
        rate, y = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), '<i2') / 32768
    spectrum, hz = np.abs(np.fft.rfft(y * np.hanning(len(y)))), np.fft.rfftfreq(len(y), 1 / rate)
    assert hz[-1] > 15000, f'the clip stops at {hz[-1]:.0f} Hz'
    assert spectrum[np.abs(hz - 15000) < 20].max() > 30 * np.median(spectrum[(hz > 13000) & (hz < 17000)])


ZH = [('b001', '人的一生大约有三分之一的时间在睡觉。很多人觉得睡觉是在浪费时间，但科学家发现，睡眠其实是大脑和身体最忙碌的维修时间。'),
      ('b002', '白天，大脑工作时会产生很多代谢废物。研究发现，人在深度睡眠时，脑细胞之间的空隙会变大。'),
      ('b003', '实验显示，学完新内容后睡一觉的人，第二天的考试成绩往往比熬夜复习的人更好。'),
      ('b004', '今晚早点睡，就是对明天的自己最好的投资。')]


@pytest.mark.skipif(bool(voice.missing_files('zh')), reason='Kokoro zh models not downloaded (doodle setup --lang zh)')
def test_a_chinese_take_is_cut_and_timed_as_well_as_an_english_one(tmp_path):
    """Own voice is offered for Chinese scripts too: a take in another voice (zm_010, slower) is cut in its pauses
    and every character is drawn when it is said."""
    rng = np.random.default_rng(0)
    highpass = butter(2, 80, 'highpass', fs=voice.SR, output='sos')
    parts, truth, t = [np.zeros(round(.4 * voice.SR), np.float32)], [], .4
    for _, text in ZH:
        clip = voice.synthesize(text, 'zh', tmp_path / 'take', 'zm_010', .85)
        audio = voice._read_wav(clip.wav)
        n = len(audio) // 240
        level = 10 * np.log10((sosfilt(highpass, audio)[:n * 240].reshape(n, 240) ** 2).mean(1) + 1e-10)
        heard = np.flatnonzero(level > 20 * np.log10(NOISE) + 6)
        truth.append({'start': t + heard[0] / 100, 'end': t + (heard[-1] + 1) / 100, 'chars': [t + c for c in clip.char_times]})
        gap = round(rng.uniform(.3, 1.2) * voice.SR)
        parts += [audio, np.zeros(gap, np.float32)]
        t += (len(audio) + gap) / voice.SR
    x = np.concatenate(parts)
    path = tmp_path / 'take.wav'
    voice._write_wav(path, x + rng.normal(0, NOISE, len(x)).astype(np.float32))
    clips = voice.from_recording(path, ZH, 'zh', tmp_path / 'voice')
    report = json.loads((tmp_path / 'voice' / 'recording-align.json').read_text())
    errors = []
    for k, ((bid, text), row) in enumerate(zip(ZH, report['beats'])):
        before = truth[k - 1]['end'] if k else 0.
        after = truth[k + 1]['start'] if k + 1 < len(ZH) else np.inf
        assert before <= row['start'] <= truth[k]['start'] and truth[k]['end'] <= row['end'] <= after, (row, truth[k])
        errors += [row['start'] + clips[bid].char_times[i] - truth[k]['chars'][i]
                   for i, ch in enumerate(text) if re.match('[一-鿿]', ch)]
    errors = np.abs(errors)
    assert np.median(errors) <= .06 and np.percentile(errors, 95) <= .15, (np.median(errors), np.percentile(errors, 95))
    assert not any(row['check'] for row in report['beats']) and report['match'] > voice.MATCH

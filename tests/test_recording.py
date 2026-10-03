"""Narration from your own recording: the alignment, checked against a take whose timing is known."""
import json
import re
import wave

from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, resample_poly, sosfilt

from kinodraw import cli, pipeline, voice

needs_models = pytest.mark.skipif(bool(voice.missing_files('en')),
                                  reason='Kokoro models not downloaded (kinodraw setup --lang en)')
BEATS = [('b001', 'You wrote something worth explaining. A lesson, a story, a big idea. But turning it into a video '
                  'takes days of drawing, recording and editing.'),
         ('b002', "There's a much easier way. Meet KinoDraw."),
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
    with pytest.raises(voice.RecordingError, match='does not sound like a reading of this script'):
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
    with pytest.raises(voice.RecordingError, match='Record the whole script'):
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


def _skipping_take(tmp_path, beats, skip):
    """``beats`` read by another voice with the beats at ``skip`` left out, as a mono wav."""
    parts = [np.zeros(9600, np.float32)]
    for k, (_, text) in enumerate(beats):
        if k not in skip:
            clip = voice.synthesize(text, 'en', tmp_path / 'reader', 'am_michael', .9)
            parts += [voice._read_wav(clip.wav), np.zeros(14400, np.float32)]
    x = np.concatenate(parts)
    x = x + np.random.default_rng(0).normal(0, NOISE, len(x)).astype(np.float32)
    path = tmp_path / 'take.wav'
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(voice.SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())
    return path


@needs_models
def test_a_take_that_skips_sentences_says_what_to_do_instead_of_a_traceback(tmp_path, capsys):
    """Two sentences left out of the reading: the CLI ends with a plain message (the part, re-record, or go back
    to the AI voice), not a Python traceback, and the project keeps working with --recording none."""
    project = tmp_path / 'video'
    board = pipeline.new_project(Path(__file__).parent / 'fixtures' / 'tiny.md', project)
    beats = [(beat['id'], beat['spoken']['en']) for beat in board['beats']]
    take = _skipping_take(tmp_path, beats, {2, 3})
    with pytest.raises(SystemExit) as end:
        cli.main(['voice', str(project), '--recording', str(take)])
    message = str(end.value.code)
    assert 'Traceback' not in message and 'ValueError' not in message
    assert 'Your recording skips or changes the part that says "And finally: Bees work hard." (b004)' in message
    assert 'Read the whole script once through' in message
    assert f'kinodraw voice "{project}" --recording none' in message
    cli.main(['voice', str(project), '--recording', 'none'])
    assert 'captions' in capsys.readouterr().out


def test_the_studio_shows_a_recording_problem_as_a_plain_sentence(monkeypatch):
    from kinodraw.studio import server
    monkeypatch.setattr(server.traceback, 'print_exc', lambda: None)
    jobs = server.Jobs()

    def wait(fn):
        jid = jobs.start('voice', 'P', fn)
        for _ in range(200):
            if jobs.get(jid)['state'] == 'failed':
                return jobs.get(jid)['error']
            import time
            time.sleep(.01)
    plain = 'Your recording skips or changes the part that says "Hi" (b002). Read the whole script once through.'

    def wrong_take(progress):
        raise voice.RecordingError(plain)

    def bug(progress):
        raise KeyError('beats')
    assert wait(wrong_take) == plain
    assert wait(bug) == "KeyError: 'beats'"            # anything else keeps its type, for a bug report


def test_a_recording_problem_names_the_way_back_to_the_ai_voice(tmp_path, monkeypatch):
    project = tmp_path / 'video'
    pipeline.new_project(Path(__file__).parent / 'fixtures' / 'tiny.md', project)
    pipeline.set_recording(project, Path(__file__))
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: None)
    monkeypatch.setattr(voice, 'synthesize', lambda text, *a: voice.Clip(Path('guide.wav'), 1., [0.] * len(text)))

    def refuse(*args):
        raise voice.RecordingError('Your recording has 3 s of speech, but this script takes about 30 s to read.')
    monkeypatch.setattr(voice, 'from_recording', refuse)
    with pytest.raises(voice.RecordingError, match=r'30 s to read\. To narrate with the AI voice instead, run: '
                                                   r'kinodraw voice ".*video" --recording none'):
        pipeline.narrate(project)

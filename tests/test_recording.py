"""Narration from your own recording: the alignment, checked against a take whose timing is known."""
import json
import re
import wave

from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, resample_poly, sosfilt

from kinodraw import cli, pipeline, script, voice
from test_finish_worker import cached_project

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
            {'match': .6, 'beats': [{'id': 'b002', 'match': .3, 'check': True}]}), encoding='utf-8')
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
    assert calls == [(project / 'recording.m4a', beats, 'en', project / 'voice', 'af_heart', 1.0, {})]
    out = capsys.readouterr().out                         # which part, and what to do about it
    assert '! b002 ("Honey is one of the oldest foods people still eat.") sounds unlike its text (0.30). Watch that ' \
           'part of the video: if the pictures are out of step with your voice there, record the script again' in out
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
    return clips, json.loads((cache / 'recording-align.json').read_text(encoding='utf-8')), cache


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
    assert not any(row['check'] or row['missing'] for row in report['beats']) and report['match'] > voice.MATCH
    assert [row['text'] for row in report['sentences']] == [s for _, text in BEATS for s in script.sentences(text, 'en')]
    assert not any(row['check'] for row in report['sentences'])


def _sentence_take(path, replace=None, skip=()):
    """The script read sentence by sentence by another voice (am_michael at 0.85), with short pauses inside a beat and
    longer ones between beats; ``replace`` reads other words instead of some sentences, ``skip`` leaves some out
    (numbered from 1, as the Studio shows them)."""
    rng = np.random.default_rng(0)
    parts, n = [np.zeros(round(.4 * voice.SR), np.float32)], 0
    for _, text in BEATS:
        for sentence in script.sentences(text, 'en'):
            n += 1
            if n not in skip:
                clip = voice.synthesize((replace or {}).get(n, sentence), 'en', path.parent / 'take', 'am_michael', .85)
                parts += [voice._read_wav(clip.wav), np.zeros(round(rng.uniform(.25, .45) * voice.SR), np.float32)]
        parts.append(np.zeros(round(rng.uniform(.3, .8) * voice.SR), np.float32))
    x = np.concatenate(parts)
    voice._write_wav(path, x + rng.normal(0, NOISE, len(x)).astype(np.float32))
    return path


@needs_models
def test_one_wrong_sentence_is_marked_and_its_beat_mates_are_not(tmp_path):
    """Sentence 2 of a three-sentence beat read as other words: only sentence 2 is marked (a beat-by-beat check passes
    this beat, and would mark sentences 1 and 3 with it if it did not)."""
    take = _sentence_take(tmp_path / 'take.wav', replace={2: 'The council met on Tuesday.'})
    voice.from_recording(take, BEATS, 'en', tmp_path / 'voice')
    report = json.loads((tmp_path / 'voice' / 'recording-align.json').read_text(encoding='utf-8'))
    assert [n for n, row in enumerate(report['sentences'], 1) if row['check']] == [2]


@needs_models
def test_a_skipped_sentence_is_marked_itself_not_the_next_beat(tmp_path):
    """Sentence 7 left out: it is marked, and no sentence of another beat is. The sentence just before it is
    sometimes marked too (the alignment lends it some of the missing sentence's time; Kokoro's guide varies a little
    from run to run, so that one is allowed either way)."""
    take = _sentence_take(tmp_path / 'take.wav', skip=(7,))
    voice.from_recording(take, BEATS, 'en', tmp_path / 'voice')
    report = json.loads((tmp_path / 'voice' / 'recording-align.json').read_text(encoding='utf-8'))
    marked = {n for n, row in enumerate(report['sentences'], 1) if row['check']}
    assert 7 in marked and marked <= {6, 7, 8}, marked             # 6 to 8 are beat b003


@needs_models
def test_a_second_run_reuses_the_cut(take, aligned, monkeypatch):
    clips, _, cache = aligned
    monkeypatch.setattr(voice, '_decode', lambda path: pytest.fail('decoded again'))
    assert voice.from_recording(take[0], BEATS, 'en', cache) == clips


@needs_models
def test_a_reading_of_another_script_is_refused(take, aligned):
    other = [(bid, text) for (bid, _), text in zip(BEATS, OTHER)]
    with pytest.raises(voice.RecordingError, match='does not sound like a reading of this script') as refused:
        voice.from_recording(take[0], other, 'en', aligned[2])
    assert 'match' not in refused.value.plain and '.json' not in refused.value.plain     # the Studio's words


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


def _skipping_take(tmp_path, beats, skip, speed=.9):
    """``beats`` read by another voice with the beats at ``skip`` left out, as a mono wav."""
    parts = [np.zeros(9600, np.float32)]
    for k, (_, text) in enumerate(beats):
        if k not in skip:
            clip = voice.synthesize(text, 'en', tmp_path / 'reader', 'am_michael', speed)
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
    assert 'Part of the script seems to be missing from your recording, around the part that says "Here\'s what ' \
           'we\'ll cover. First: It never spoils." Read the whole script once through' in message
    assert f'kinodraw voice "{project}" --recording none' in message
    cli.main(['voice', str(project), '--recording', 'none'])
    assert 'captions' in capsys.readouterr().out


@needs_models
def test_a_take_that_leaves_out_one_part_is_refused_and_names_it(tmp_path):
    """One whole beat left out: the cut used to squeeze its neighbours into its place, so every step went on to a video
    whose pictures ran ahead of the voice, with only a warning that blamed the wrong part."""
    project = tmp_path / 'video'
    board = pipeline.new_project(Path(__file__).parent / 'fixtures' / 'tiny.md', project)
    beats = [(beat['id'], beat['spoken']['en']) for beat in board['beats']]
    take = _skipping_take(tmp_path, beats, {1})
    with pytest.raises(SystemExit) as end:
        cli.main(['voice', str(project), '--recording', str(take)])
    message = str(end.value.code)
    assert 'Part of the script seems to be missing from your recording, around the part that says "Honey is one of ' \
           'the oldest foods people still eat." Read the whole script once through' in message
    assert f'kinodraw voice "{project}" --recording none' in message and 'Traceback' not in message
    report = json.loads((project / 'voice' / 'recording-align.json').read_text(encoding='utf-8'))
    assert next(row for row in report['beats'] if row['id'] == 'b002')['missing']
    assert not (project / 'build' / 'timeline.json').exists()                  # nothing goes on to render


@needs_models
@pytest.mark.parametrize('skip, part', [({1}, '"Honey is one of the oldest foods people still eat."'),
                                        ({2, 3}, '"Here\'s what we\'ll cover. First: It never spoils."')])
def test_a_take_read_a_little_faster_names_the_same_left_out_part_in_the_same_words(tmp_path, skip, part):
    """Whether the alignment gives a left-out part no time at all or a sliver of the pause next to it turns on tiny
    differences between takes (Kokoro's graph draws fresh noise on every run, and computers round differently), so the
    same take was refused in two different sentences, naming either of two parts left out together. A left-out part is
    found the same way either way, and the first one is named."""
    project = tmp_path / 'video'
    board = pipeline.new_project(Path(__file__).parent / 'fixtures' / 'tiny.md', project)
    beats = [(beat['id'], beat['spoken']['en']) for beat in board['beats']]
    take = _skipping_take(tmp_path, beats, skip, .92)
    with pytest.raises(SystemExit) as end:
        cli.main(['voice', str(project), '--recording', str(take)])
    assert f'Part of the script seems to be missing from your recording, around the part that says {part} Read the ' \
           'whole script once through' in str(end.value.code)


@needs_models
def test_a_voice_clip_that_comes_out_as_noise_is_made_again(tmp_path, monkeypatch):
    """Kokoro's graph draws random noise on every run; a run that came out with one non-finite sample was trimmed by
    kokoro-onnx to no audio at all, and the voice step stopped with numpy's "zero-size array to reduction operation
    maximum which has no identity"."""
    import onnxruntime
    run, runs = onnxruntime.InferenceSession.run, []

    def once_not_a_number(self, *args, **kwargs):
        out = run(self, *args, **kwargs)
        runs.append(len(out[0]))
        if len(runs) == 1:
            out[0].reshape(-1)[100] = np.nan
        return out
    monkeypatch.setattr(onnxruntime.InferenceSession, 'run', once_not_a_number)
    clip = voice.synthesize('Honey is one of the oldest foods people still eat.', 'en', tmp_path, 'af_heart')
    audio = voice._read_wav(clip.wav)
    assert len(runs) == 2 and clip.duration > 1 and len(audio) > voice.SR and np.abs(audio).max() > .05


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
    assert "KeyError: 'beats'" in wait(bug)            # anything else keeps its type, for a bug report


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


def test_a_video_in_your_own_voice_does_not_credit_the_ai_voice(tmp_path, cached_project):
    """The description of a video narrated with the creator's own recording said "Narration: Kokoro AI voice", and
    so did the Studio under the finished video."""
    from kinodraw.studio import server
    project = cached_project

    def description():
        assert pipeline.finish(project)['ok']
        return next(project.glob('*-description.txt')).read_text(encoding='utf-8')
    assert 'Narration: Kokoro AI voice.' in description()
    (tmp_path / 'take.wav').write_bytes(b'audio')
    pipeline.set_recording(project, tmp_path / 'take.wav')
    text = description()
    assert 'Kokoro' not in text and "Narration: the creator's own voice." in text
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert "p.settings.recording ? 'Narration: your own voice.' : 'Narration: Kokoro AI voice.'" in js


@needs_models
def test_your_own_voice_works_where_text_files_are_not_utf8_by_default(tmp_path):
    """On Windows a text file is written in the computer's code page unless the app says UTF-8: recording-align.json
    and the recording cache were, then read back as UTF-8, so a project folder named in another language stopped the
    voice step. Here the text-file default is Latin-1 (macOS) or the Windows code page."""
    import os
    import shutil
    import subprocess
    import sys
    from kinodraw.director import match
    env = {name: value for name, value in os.environ.items() if not name.startswith('TTS_')}
    env.update(PYTHONUTF8='0', PYTHONCOERCECLOCALE='0', PYTHONIOENCODING='utf-8',
               LC_ALL='en_US.ISO8859-1', LANG='en_US.ISO8859-1',
               PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring')
    probe = subprocess.run([sys.executable, '-c', 'import locale, sys; print(locale.getpreferredencoding(False), '
                            'sys.getfilesystemencoding())'], env=env, capture_output=True, text=True, encoding='utf-8').stdout.split()
    if probe[0].lower().replace('-', '') == 'utf8' or probe[1].lower().replace('-', '') != 'utf8':
        pytest.skip(f'no non-UTF-8 text default with UTF-8 file names here: {probe}')
    # Fresh CLI children do not inherit conftest's path/keychain patches. Give migration
    # temporary app folders and copies of the cached models, with no inherited voice server.
    models = tmp_path / 'models'
    models.mkdir()
    for name in (voice.LANGS['en']['model'], voice.LANGS['en']['voices']):
        shutil.copyfile(voice.MODEL_DIR / name, models / name)
    if match.CACHE.is_dir():
        shutil.copytree(match.CACHE, models / 'embed')
    env['KINODRAW_MODELS'] = str(models)
    isolated_cli = '''import os, sys
from pathlib import Path
import platformdirs
root = Path(sys.argv[1])
platformdirs.user_data_dir = lambda app: str(root / 'data' / app)
platformdirs.user_config_dir = lambda app: str(root / 'config' / app)
platformdirs.user_cache_dir = lambda app: str(root / 'cache' / app)
platformdirs.user_videos_dir = lambda: str(root / 'Videos')
from kinodraw import cli, paths
assert all(old.is_relative_to(root) and new.is_relative_to(root) for old, new in paths.legacy_moves())
assert not any(name.startswith('TTS_') for name in os.environ)
assert os.environ['PYTHON_KEYRING_BACKEND'] == 'keyring.backends.null.Keyring'
cli.main(sys.argv[2:])
'''
    project, script = tmp_path / 'Vidéo 我的', tmp_path / 'honey.md'
    script.write_text('# Honey\n\nHoney is one of the oldest foods people still eat.\n\nBees visit about two million '
                      'flowers to make one jar.\n', encoding='utf-8')

    def kinodraw(*args):
        done = subprocess.run([sys.executable, '-c', isolated_cli, str(tmp_path / 'app'), *map(str, args)], env=env, capture_output=True,
                              text=True, encoding='utf-8')
        assert done.returncode == 0, done.stderr[-2000:]
        return done.stdout
    kinodraw('new', script, '-o', project)
    kinodraw('voice', project)
    shutil.copyfile(project / 'build' / 'narration.wav', tmp_path / 'take.wav')
    assert 'your recording: match' in kinodraw('voice', project, '--recording', tmp_path / 'take.wav')
    assert 'your recording: match' in kinodraw('voice', project)                     # again, from the cache
    report = json.loads((project / 'voice' / 'recording-align.json').read_text(encoding='utf-8'))
    assert report['recording'] == str(project / 'recording.wav')


ZH = [('b001', '人的一生大约有三分之一的时间在睡觉。很多人觉得睡觉是在浪费时间，但科学家发现，睡眠其实是大脑和身体最忙碌的维修时间。'),
      ('b002', '白天，大脑工作时会产生很多代谢废物。研究发现，人在深度睡眠时，脑细胞之间的空隙会变大。'),
      ('b003', '实验显示，学完新内容后睡一觉的人，第二天的考试成绩往往比熬夜复习的人更好。'),
      ('b004', '今晚早点睡，就是对明天的自己最好的投资。')]


@pytest.mark.skipif(bool(voice.missing_files('zh')), reason='Kokoro zh models not downloaded (kinodraw setup --lang zh)')
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
    report = json.loads((tmp_path / 'voice' / 'recording-align.json').read_text(encoding='utf-8'))
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
    assert len(report['sentences']) == 6 and not any(row['check'] for row in report['sentences'])

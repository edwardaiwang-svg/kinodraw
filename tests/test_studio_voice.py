"""Your own voice in the Studio: the Narrator choice, a read-aloud script, phone recordings uploaded as they are,
the check of how the recording matched each sentence, and going back to the built-in voice."""
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest

from kinodraw import cli, pipeline, script, voice
from kinodraw.director.llm import providers
from kinodraw.studio import server

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """The real local server with a projects folder holding one English and one Chinese storyboard."""
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    root = tmp_path / 'videos'
    server._save_config({'projects': str(root)})
    monkeypatch.setattr(providers, 'saved', lambda: set())
    pipeline.new_project(FIXTURES / 'tiny.md', root / 'Honey')
    pipeline.new_project(FIXTURES / 'sleep_zh.md', root / 'Sleep')
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None, method=None, raw=None):
        data = raw if raw is not None else None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url + path.lstrip('/'), data=data, method=method or ('GET' if data is None else 'POST'),
                                     headers={'X-Studio-Token': server.Handler.token})
        try:
            with opener.open(req, timeout=30) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
    call.root = root
    yield call
    httpd.shutdown()


def _wait(call, job, seconds=10):
    for _ in range(round(seconds / .05)):
        state = call(f'/api/jobs/{job}')[1]
        if state['state'] in ('done', 'failed'):
            return state
        time.sleep(.05)
    raise AssertionError('job never finished')


def _sound(tmp_path, name, *args):
    """Two seconds of a hum, encoded the way a phone would save it."""
    out = tmp_path / name
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=220:duration=2',
                    *args, '-y', str(out)], check=True)
    return out.read_bytes()


def _amr():
    """AMR-NB (old Android voice recorders): no encoder ships with ffmpeg, so frames of the 12.2 kbit/s mode."""
    rng = np.random.default_rng(0)
    return b'#!AMR\n' + b''.join(b'\x3c' + rng.bytes(31) for _ in range(100))


PHONE = {                                     # file name: how to make it
    'New Recording 3.m4a': ('-c:a', 'aac'),              # iPhone Voice Memos
    'Voice 001.M4A': ('-c:a', 'aac', '-f', 'mp4'),        # Samsung Voice Recorder
    'memo.mp3': ('-c:a', 'libmp3lame'),
    'take.wav': ('-c:a', 'pcm_s16le'),
    'recording.ogg': ('-c:a', 'libopus'),                # Android apps, WhatsApp voice notes (.opus too)
    'note.opus': ('-c:a', 'libopus', '-f', 'ogg'),
    'Recorded in the browser.webm': ('-c:a', 'libopus'),
    'Voice 002.3gp': ('-c:a', 'aac', '-f', '3gp'),
    'take.aiff': ('-c:a', 'pcm_s16be'),
    'take.flac': ('-c:a', 'flac'),
}


def test_the_studio_offers_a_narrator_choice():
    page = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    new = re.search(r'<template id="tpl-new">.*?</template>', page, re.S).group(0)
    project = re.search(r'<template id="tpl-project">.*?</template>', page, re.S).group(0)
    assert 'Narrator' in new and 'Built-in voice' in new and 'My own voice' in new
    assert 'data-tab="narrator"' in project
    for words in ('Upload a recording', 'Use it for this video', 'Read it naturally'):
        assert words in page or words in js, words


def test_the_script_is_shown_as_numbered_sentences_to_read_aloud(studio):
    status, info = studio('/api/projects/Honey/narrator')
    assert status == 200 and info['narrator'] == 'builtin' and info['take'] is None and info['check'] is None
    board = pipeline.storyboard(studio.root / 'Honey')
    lines = [line['text'] for line in info['lines']]
    assert ' '.join(lines) == ' '.join(b['spoken']['en'] for b in board['beats'])      # every word, in order
    assert lines[0] == 'Today: Three Facts About Honey.'
    assert lines[2:4] == ["Here's what we'll cover.", 'First: It never spoils.']                # one sentence a line
    assert {line['beat'] for line in info['lines']} == {b['id'] for b in board['beats']}


def test_chinese_scripts_can_be_read_aloud_too(studio):
    """The alignment works for Chinese (test_recording.py), so own voice is offered for both languages."""
    status, info = studio('/api/projects/Sleep/narrator')
    assert status == 200 and info['lang'] == 'zh'
    assert info['lines'][1]['text'] == '人的一生大约有三分之一的时间在睡觉。'
    assert all(len(re.findall('[。！？]', line['text'])) <= 1 for line in info['lines'])


@pytest.mark.parametrize('name', PHONE)
def test_phone_recordings_are_kept_as_they_are(studio, tmp_path, name):
    data = _sound(tmp_path, re.sub(r'\.\w+$', lambda m: m.group(0).lower(), name), *PHONE[name])
    status, info = studio(f'/api/projects/Honey/recording?filename={urllib.request.quote(name)}', raw=data)
    assert status == 200, info
    suffix = Path(name).suffix.lower()
    assert info['narrator'] == 'own' and info['take'] == f'recording{suffix}' and info['check'] is None
    assert info['changed'] == []
    assert (studio.root / 'Honey' / f'recording{suffix}').read_bytes() == data
    assert pipeline.settings(studio.root / 'Honey')['recording'] == f'recording{suffix}'


def test_old_android_amr_recordings_are_accepted(studio):
    status, info = studio('/api/projects/Honey/recording?filename=Voice%20003.amr', raw=_amr())
    assert status == 200 and info['take'] == 'recording.amr'


@pytest.mark.parametrize('name, data', [('Lesson plan.pdf', b'%PDF-1.7 not a recording'), ('empty.m4a', b'')])
def test_a_file_that_is_not_a_recording_is_refused_in_plain_words(studio, name, data):
    status, info = studio(f'/api/projects/Honey/recording?filename={urllib.request.quote(name)}', raw=data)
    assert status == 400
    assert re.search(r"isn.t a recording|could not be read|is empty", info['error']), info['error']
    assert not re.search(r'Error|Traceback|ffmpeg|\[in#', info['error']), info['error']
    assert not list((studio.root / 'Honey').glob('recording.*'))            # nothing kept
    assert 'recording' not in pipeline.settings(studio.root / 'Honey')


def test_a_new_take_replaces_the_old_one(studio, tmp_path):
    studio('/api/projects/Honey/recording?filename=first.wav', raw=_sound(tmp_path, 'a.wav'))
    status, info = studio('/api/projects/Honey/recording?filename=second.m4a', raw=_sound(tmp_path, 'b.m4a', '-c:a', 'aac'))
    assert status == 200 and info['take'] == 'recording.m4a'
    assert [p.name for p in (studio.root / 'Honey').glob('recording.*')] == ['recording.m4a']


def test_switching_back_to_the_built_in_voice_and_again_to_your_own(studio, tmp_path):
    assert studio('/api/projects/Honey/narrator', {'narrator': 'own'})[0] == 400       # nothing recorded yet
    studio('/api/projects/Honey/recording?filename=take.wav', raw=_sound(tmp_path, 'a.wav'))
    status, info = studio('/api/projects/Honey/narrator', {'narrator': 'builtin'})
    assert status == 200 and info['narrator'] == 'builtin' and info['take'] == 'recording.wav'   # the take is kept
    assert 'recording' not in pipeline.settings(studio.root / 'Honey')
    status, info = studio('/api/projects/Honey/narrator', {'narrator': 'own'})
    assert info['narrator'] == 'own' and pipeline.settings(studio.root / 'Honey')['recording'] == 'recording.wav'


def _fake_alignment(monkeypatch, project, poor=(), match=.6, missing=None):
    """voice.from_recording without Kokoro: writes the report the real one writes (``poor``: the sentences, numbered
    from 1, that it marks), or refuses like it."""
    calls = []
    monkeypatch.setattr(voice, 'synthesize', lambda text, *a: voice.Clip(Path('guide.wav'), 1., [0.] * len(text)))
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: None)

    def cut(recording, beats, lang, *args):
        calls.append(recording)
        if missing:
            error = ValueError(f'take.wav: beat {missing} was not found in the recording')
            error.beat = missing
            raise error
        (project / 'voice').mkdir(exist_ok=True)
        lines = [(bid, s) for bid, text in beats for s in script.sentences(text, lang)]
        (project / 'voice' / 'recording-align.json').write_text(json.dumps({
            'sha256': server.sha(recording), 'match': match,
            'beats': [{'id': bid, 'match': .6, 'check': False} for bid, _ in beats],
            'sentences': [{'beat': bid, 'text': s, 'fit': .8 if n in poor else .9, 'check': n in poor}
                          for n, (bid, s) in enumerate(lines, 1)]}), encoding='utf-8')
        if match < voice.MATCH:
            raise ValueError('take.wav does not sound like a reading of this script')
        return {bid: voice.Clip(Path('clip.wav'), 1., [0.] * len(text)) for bid, text in beats}
    monkeypatch.setattr(voice, 'from_recording', cut)
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: {})
    return calls


def test_use_it_for_this_video_matches_every_sentence(studio, tmp_path, monkeypatch):
    """Each sentence is judged on its own: one wrong sentence of a two-sentence beat (b003: lines 3 and 4) is marked,
    the other is not."""
    project = studio.root / 'Honey'
    calls = _fake_alignment(monkeypatch, project, poor=(4,))
    stages = []
    start = server.JOBS.start

    def spy(kind, name, fn):
        return start(kind, name, lambda progress: fn(lambda *a: (stages.append(a[0]), progress(*a))))
    monkeypatch.setattr(server.JOBS, 'start', spy)
    studio('/api/projects/Honey/recording?filename=take.wav', raw=_sound(tmp_path, 'a.wav'))
    job = _wait(studio, studio('/api/projects/Honey/align', {})[1]['job'])
    assert job['state'] == 'done' and calls == [project / 'recording.wav']
    assert 'align' in stages                                # the stage bar says it is listening to the take
    check = job['result']['check']
    assert check == {'ok': True, 'poor': [4], 'missing': [], 'problem': None}
    assert studio('/api/projects/Honey/narrator')[1]['check'] == check                  # and it is remembered


def test_a_recording_of_something_else_says_which_sentences_were_not_found(studio, tmp_path, monkeypatch):
    project = studio.root / 'Honey'
    _fake_alignment(monkeypatch, project, missing='b005')
    studio('/api/projects/Honey/recording?filename=take.wav', raw=_sound(tmp_path, 'a.wav'))
    job = _wait(studio, studio('/api/projects/Honey/align', {})[1]['job'])
    assert job['state'] == 'done'                            # a take that does not fit is an answer, not a crash
    check = job['result']['check']
    assert check['ok'] is False and check['missing'] == [6] and 'was not found' in check['problem']     # b005's line
    assert 'Traceback' not in json.dumps(job)
    assert studio('/api/projects/Honey/narrator')[1]['check'] == check        # still shown when opened again

    _fake_alignment(monkeypatch, project, match=.33, poor=(2, 3, 4))
    job = _wait(studio, studio('/api/projects/Honey/align', {})[1]['job'])
    check = job['result']['check']
    assert check['ok'] is False and check['poor'] == [2, 3, 4] and 'does not sound like' in check['problem']
    assert check['missing'] == []                                             # the earlier take's problem is gone


def test_a_failed_video_explains_itself_without_python_words(studio, monkeypatch):
    def narrate(*a, **k):
        raise ValueError('Your recording skips the part that says "Bees work hard". Read the whole script.')
    monkeypatch.setattr(pipeline, 'narrate', narrate)
    job = _wait(studio, studio('/api/projects/Honey/make', {})[1]['job'])
    assert job['state'] == 'failed'
    assert job['error'] == 'Your recording skips the part that says "Bees work hard". Read the whole script.'


def test_an_edited_takeaway_is_shown_as_it_will_be_said_and_marked_changed(studio, tmp_path, monkeypatch):
    """A takeaway note edited after recording changes what is narrated: the read-aloud page shows the new sentence,
    the old check no longer counts, and the sentence is marked as changed since the recording until it is put back."""
    project = studio.root / 'Honey'
    _fake_alignment(monkeypatch, project)
    studio('/api/projects/Honey/recording?filename=take.wav', raw=_sound(tmp_path, 'a.wav'))
    _wait(studio, studio('/api/projects/Honey/align', {})[1]['job'])
    before = studio('/api/projects/Honey/narrator')[1]
    assert before['lines'][7]['text'] == 'Key takeaway: It never spoils.' and before['check']['ok']
    assert before['changed'] == []

    board = pipeline.storyboard(project)
    take = next(b for b in board['beats'] if b['kind'] == 'take')
    take['take']['headline'] = {'en': 'Honey keeps for thousands of years'}
    assert studio('/api/projects/Honey/storyboard', board, method='PUT')[1]['ok']
    info = studio('/api/projects/Honey/narrator')[1]
    assert info['lines'][7] == {'beat': take['id'], 'text': 'Key takeaway: Honey keeps for thousands of years.'}
    assert info['check'] is None and info['changed'] == [8]          # numbered from 1, as on the page

    take['take']['headline'] = {'en': 'It never spoils.'}
    studio('/api/projects/Honey/storyboard', board, method='PUT')
    info = studio('/api/projects/Honey/narrator')[1]
    assert info['changed'] == [] and info['check'] == before['check']


def test_the_page_warns_before_making_a_video_from_sentences_that_dont_fit():
    """Make video, from any tab, stops on the Narrator tab when sentences didn't match or changed since recording;
    only Make the video anyway goes ahead."""
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    make = re.search(r'async function makeVideo\(name, anyway = false\) \{.*?\n\}', js, re.S).group(0)
    assert make.index("didn’t match your recording") < make.index('/make`')
    assert make.index('changed after you recorded') < make.index('/make`')
    assert "addEventListener('click', () => makeVideo(name, true))" in js


def _reading(tmp_path, beats, skip=()):
    """``beats`` read aloud by another voice (am_michael at 0.9), the beats at ``skip`` left out, as a wav."""
    parts = [np.zeros(9600, np.float32)]
    for k, (_, text) in enumerate(beats):
        if k not in skip:
            clip = voice.synthesize(text, 'en', tmp_path / 'reader', 'am_michael', .9)
            parts += [voice._read_wav(clip.wav), np.zeros(14400, np.float32)]
    x = np.concatenate(parts)
    path = tmp_path / 'take.wav'
    voice._write_wav(path, x + np.random.default_rng(0).normal(0, .002, len(x)).astype(np.float32))
    return path


@pytest.mark.skipif(bool(voice.missing_files('en')), reason='Kokoro models not downloaded (kinodraw setup --lang en)')
def test_a_take_that_leaves_out_a_part_is_refused_on_the_narrator_tab_naming_it(studio, tmp_path):
    """A take without one whole part is refused at the voice step (a video cut from it would run ahead of the voice).
    In the Studio the Narrator tab says so in the refusal's own words, naming the part, without the command line's
    advice, and marks that part's sentences as not found; Make video refuses it too, so nothing goes past it."""
    project = studio.root / 'Honey'
    beats = [(b['id'], b['spoken']['en']) for b in pipeline.storyboard(project)['beats']]
    status, _ = studio('/api/projects/Honey/recording?filename=take.wav', raw=_reading(tmp_path, beats, {1}).read_bytes())
    assert status == 200
    job = _wait(studio, studio('/api/projects/Honey/align', {})[1]['job'], 600)
    assert job['state'] == 'done', job
    info = job['result']
    check = info['check']
    assert check['ok'] is False
    assert check['problem'].startswith('Part of the script seems to be missing from your recording, around the part '
                                       'that says "Honey is one of the oldest foods people still eat."')
    assert 'kinodraw voice' not in check['problem'] and 'b002' not in check['problem']    # no internal part ids
    assert check['missing'] == [n for n, line in enumerate(info['lines'], 1) if line['beat'] == 'b002'] == [2]
    assert studio('/api/projects/Honey/narrator')[1]['check'] == check             # still shown when opened again

    job = _wait(studio, studio('/api/projects/Honey/make', {})[1]['job'], 600)
    assert job['state'] == 'failed' and job['error'] == check['problem']


def _read_aloud_page(studio, name):
    """The Studio's read-aloud page as text: its numbered sentences, one a line."""
    return ''.join(f'{n}. {line["text"]}\n' for n, line in enumerate(studio(f'/api/projects/{name}/narrator')[1]['lines'], 1))


@pytest.mark.skipif(bool(voice.missing_files('en')), reason='Kokoro models not downloaded (kinodraw setup --lang en)')
def test_the_command_line_names_the_text_to_read_when_a_take_misses_a_line_kinodraw_added(studio, tmp_path):
    """Someone narrating from the command line read their own script file, which has no "Key takeaway: ..." line:
    the refusal named a part they had never seen. The voice step writes read-aloud.txt, the script as it is narrated
    (the Studio's read-aloud page, sentence for sentence), and the refusal names it."""
    project = studio.root / 'Honey'
    beats = [(b['id'], b['spoken']['en']) for b in pipeline.storyboard(project)['beats']]
    assert beats[6] == ('b007', 'Key takeaway: It never spoils.')
    with pytest.raises(SystemExit) as end:
        cli.main(['voice', str(project), '--recording', str(_reading(tmp_path, beats, {6}))])
    message = str(end.value.code)
    assert '"Key takeaway: It never spoils."' in message and 'b007' not in message
    assert f'The script to read, as it is narrated (one numbered sentence a line, with the lines KinoDraw adds to ' \
           f'yours), is in "{project / "read-aloud.txt"}".' in message
    assert (project / 'read-aloud.txt').read_text(encoding='utf-8') == _read_aloud_page(studio, 'Honey')
    assert '8. Key takeaway: It never spoils.\n' in _read_aloud_page(studio, 'Honey')


def test_a_generated_line_that_did_not_match_is_named_with_the_text_to_read(studio, monkeypatch, capsys):
    """A take that reads "Part one: It never spoils." differently: the command line says which sentence of
    read-aloud.txt did not match, and to record again from that file."""
    project = studio.root / 'Honey'
    _fake_alignment(monkeypatch, project, poor=(6,))
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: {'duration': 1, 'captions': []})
    (project / 'take.wav').write_bytes(b'audio')
    cli.main(['voice', str(project), '--recording', str(project / 'take.wav')])
    out = capsys.readouterr().out
    assert '! sentence 6 of read-aloud.txt ("Part one: It never spoils.") didn\'t match your recording' in out
    assert f'every sentence as written in {project / "read-aloud.txt"}' in out
    assert (project / 'read-aloud.txt').read_text(encoding='utf-8') == _read_aloud_page(studio, 'Honey')

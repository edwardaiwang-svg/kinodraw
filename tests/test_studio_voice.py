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

from doodlestudio import pipeline, voice
from doodlestudio.director.llm import providers
from doodlestudio.studio import server

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


def _wait(call, job):
    for _ in range(200):
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
    """voice.from_recording without Kokoro: writes the report the real one writes, or refuses like it."""
    calls = []
    monkeypatch.setattr(voice, 'synthesize', lambda text, *a: voice.Clip(Path('guide.wav'), 1., [0.] * len(text)))
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: None)

    def cut(recording, beats, *args):
        calls.append(recording)
        if missing:
            error = ValueError(f'take.wav: beat {missing} was not found in the recording')
            error.beat = missing
            raise error
        (project / 'voice').mkdir(exist_ok=True)
        (project / 'voice' / 'recording-align.json').write_text(json.dumps({
            'sha256': server.sha(recording), 'match': match,
            'beats': [{'id': bid, 'match': .3 if bid in poor else .6, 'check': bid in poor} for bid, _ in beats]}))
        if match < voice.MATCH:
            raise ValueError('take.wav does not sound like a reading of this script')
        return {bid: voice.Clip(Path('clip.wav'), 1., [0.] * len(text)) for bid, text in beats}
    monkeypatch.setattr(voice, 'from_recording', cut)
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: {})
    return calls


def test_use_it_for_this_video_matches_every_sentence(studio, tmp_path, monkeypatch):
    project = studio.root / 'Honey'
    calls = _fake_alignment(monkeypatch, project, poor=('b004',))
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
    assert check == {'ok': True, 'poor': ['b004'], 'missing': None, 'problem': None}
    assert studio('/api/projects/Honey/narrator')[1]['check'] == check                  # and it is remembered


def test_a_recording_of_something_else_says_which_sentences_were_not_found(studio, tmp_path, monkeypatch):
    project = studio.root / 'Honey'
    _fake_alignment(monkeypatch, project, missing='b005')
    studio('/api/projects/Honey/recording?filename=take.wav', raw=_sound(tmp_path, 'a.wav'))
    job = _wait(studio, studio('/api/projects/Honey/align', {})[1]['job'])
    assert job['state'] == 'done'                            # a take that does not fit is an answer, not a crash
    check = job['result']['check']
    assert check['ok'] is False and check['missing'] == 'b005' and 'was not found' in check['problem']
    assert 'Traceback' not in json.dumps(job)

    _fake_alignment(monkeypatch, project, match=.33, poor=('b002', 'b003'))
    job = _wait(studio, studio('/api/projects/Honey/align', {})[1]['job'])
    check = job['result']['check']
    assert check['ok'] is False and check['poor'] == ['b002', 'b003'] and 'does not sound like' in check['problem']


def test_a_failed_video_explains_itself_without_python_words(studio, monkeypatch):
    def narrate(*a):
        raise ValueError('Your recording skips the part that says "Bees work hard". Read the whole script.')
    monkeypatch.setattr(pipeline, 'narrate', narrate)
    job = _wait(studio, studio('/api/projects/Honey/make', {})[1]['job'])
    assert job['state'] == 'failed'
    assert job['error'] == 'Your recording skips the part that says "Bees work hard". Read the whole script.'

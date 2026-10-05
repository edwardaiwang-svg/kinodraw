"""Named voices, offline samples, speed and pronunciations that leave captions alone."""
import json
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kinodraw import cli, net, pipeline, voice
from kinodraw.director.llm import providers
from kinodraw.studio import server

FIXTURES = Path(__file__).parent / 'fixtures'
MODELS = pytest.mark.skipif(bool(voice.missing_files('en')), reason='English voices are not installed')


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    monkeypatch.setattr(voice.paths, 'cache_dir', lambda: tmp_path / 'cache')
    monkeypatch.setattr(providers, 'saved', lambda: set())
    root = tmp_path / 'videos'
    server._save_config({'projects': str(root)})
    pipeline.new_project(FIXTURES / 'tiny.md', root / 'Honey')
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None, method=None, token=True):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url + path.lstrip('/'), data=data,
                                     method=method or ('GET' if data is None else 'POST'),
                                     headers={'X-Studio-Token': server.Handler.token} if token else {})
        try:
            reply = opener.open(req, timeout=60)
        except urllib.error.HTTPError as error:
            reply = error
        with reply:
            raw = reply.read()
            return reply.status, raw if reply.headers.get_content_type() == 'audio/wav' else json.loads(raw)
    call.root = root
    yield call
    httpd.shutdown()
    httpd.server_close()


def test_pronunciations_match_words_and_strip_clause_marks(tmp_path):
    path = tmp_path / 'pronounce.txt'
    assert voice.read_lexicon(path) == {}
    path.write_text('# Spoken spelling only\n\n honey = huh, nee。！…\n honey pot = jar\n GIF = jif\n', encoding='utf-8')
    lexicon = voice.read_lexicon(path)
    assert lexicon['honey'] == 'huh nee'
    assert voice.respell('HONEY honeybee Honey pot. GIF gift.', lexicon, 'en') == 'huh nee honeybee jar. jif gift.'
    assert voice.respell('蜂蜜水和蜂蜜', {'蜂蜜': '甜蜜', '蜂蜜水': '糖水'}, 'zh') == '糖水和甜蜜'
    assert voice.respell('a+b aab', {'a+b': 'sum'}, 'en') == 'sum aab'
    assert voice.respell('GIF', {'GIF': 'honey', 'honey': 'sweet'}, 'en') == 'honey'
    acronyms = voice.parse_lexicon('IT = eye tee\nWHO = double you aitch oh\nus = uss\nUS = you ess')
    assert (voice.respell('The IT team said it works, but who knows what WHO said. Join us, Us, US.', acronyms, 'en')
            == 'The eye tee team said it works, but who knows what double you aitch oh said. Join uss, uss, you ess.')
    symbols = voice.parse_lexicon('C# = see sharp\nC++ = see plus plus\n.NET = dot net\nDr. = doctor')
    assert (voice.respell('I write C# and C++ for .NET, said Dr. Smith; c#d stays.', symbols, 'en')
            == 'I write see sharp and see plus plus for dot net, said doctor Smith; c#d stays.')
    sentence_case = voice.parse_lexicon('Quinoa = keen wah\niPhone = eye phone')
    assert (voice.respell('Quinoa is a seed. Cook the quinoa on an iPhone, not an IPHONE.', sentence_case, 'en')
            == 'keen wah is a seed. Cook the keen wah on an eye phone, not an IPHONE.')
    marks = ''.join(voice.CLAUSE.values()) + voice.PHONE_MARKS
    path.write_text(f'GIF = {marks}jif{marks}', encoding='utf-8')
    assert voice.read_lexicon(path) == {'GIF': 'jif'}


@pytest.mark.parametrize('line', ['no equals', '= jif', 'GIF =', 'GIF = ！？'])
def test_bad_pronunciation_names_the_line(tmp_path, line):
    path = tmp_path / 'pronounce.txt'
    path.write_text('# comment\n\n' + line, encoding='utf-8')
    with pytest.raises(ValueError, match='Line 3 of pronounce.txt should look like "word = how to say it"'):
        voice.read_lexicon(path)


@MODELS
def test_pronunciations_change_only_matching_clips_and_keep_caption_spelling(tmp_path):
    project = tmp_path / 'Honey'
    board = pipeline.new_project(FIXTURES / 'tiny.md', project)
    before = pipeline.narrate(project)
    pipeline.build_audio(project, before)
    old_names = {p.name for p in (project / 'voice').glob('*.wav')}
    original_reading = (project / pipeline.READ_ALOUD).read_text(encoding='utf-8')
    original_board = (project / 'storyboard.json').read_bytes()
    (project / pipeline.PRONOUNCE).write_text('honey = huh nee', encoding='utf-8')
    after = pipeline.narrate(project)
    pipeline.build_audio(project, after)
    matched, unchanged = [], []
    for beat in board['beats']:
        clip, old = after[beat['id']], before[beat['id']]
        if 'honey' in beat['spoken']['en'].lower():
            matched.append(beat['id'])
            assert clip.wav != old.wav and clip.wav.name not in old_names
            meta = json.loads(clip.wav.with_suffix('.json').read_text(encoding='utf-8'))
            assert 'huh nee' in meta['said'] and meta['text'] == beat['spoken']['en']
        else:
            unchanged.append(beat['id'])
            assert clip.wav == old.wav and clip.wav.name in old_names
        assert len(clip.char_times) == len(beat['spoken']['en'])
    assert matched and unchanged
    assert {p.name for p in (project / 'voice').glob('*.wav')} - old_names == {after[b].wav.name for b in matched}
    captions = (project / 'build/captions.srt').read_text(encoding='utf-8')
    assert 'honey' in captions.lower() and 'huh nee' not in captions
    assert 'huh nee' not in (project / 'build/captions.vtt').read_text(encoding='utf-8')
    assert (project / pipeline.READ_ALOUD).read_text(encoding='utf-8') == original_reading
    assert (project / 'storyboard.json').read_bytes() == original_board
    first = board['beats'][0]
    assert voice.synthesize(first['spoken']['en'], 'en', project / 'voice', lexicon={'absentword': 'sound'}).wav == before[first['id']].wav


@MODELS
def test_voice_sample_uses_no_network_and_reuses_the_cache(studio, monkeypatch):
    seen = []
    def guard(fn):
        def call(sock, address, *args, **kwargs):
            if address[0] not in ('127.0.0.1', 'localhost'):
                seen.append(address)
                raise AssertionError('sample tried the network')
            return fn(sock, address, *args, **kwargs)
        return call
    monkeypatch.setattr(socket.socket, 'connect', guard(socket.socket.connect))
    monkeypatch.setattr(socket.socket, 'connect_ex', guard(socket.socket.connect_ex))
    connect = socket.create_connection
    def create(address, *args, **kwargs):
        if address[0] not in ('127.0.0.1', 'localhost'):
            seen.append(address)
            raise AssertionError('sample tried the network')
        return connect(address, *args, **kwargs)
    monkeypatch.setattr(socket, 'create_connection', create)
    resolve = socket.getaddrinfo
    def lookup(host, *args, **kwargs):
        if host not in ('127.0.0.1', 'localhost'):
            seen.append(host)
            raise AssertionError('sample tried a network lookup')
        return resolve(host, *args, **kwargs)
    monkeypatch.setattr(socket, 'getaddrinfo', lookup)
    path = '/api/voices/en/am_michael/sample?speed=1.0'
    assert studio(path, token=False)[0] == 403
    status, data = studio(path + '&token=' + server.Handler.token, token=False)
    assert status == 200 and data.startswith(b'RIFF') and not seen
    def fail(*args, **kwargs):
        raise AssertionError('cached sample synthesized again')
    monkeypatch.setattr(voice, '_engine', fail)
    assert studio(path) == (200, data)
    assert not seen


@pytest.mark.parametrize('lang,size', [('en', 190), ('zh', 220)])
def test_missing_sample_models_explain_first_video_without_loading_or_downloading(studio, monkeypatch, lang, size):
    monkeypatch.setattr(voice, 'missing_files', lambda lang: ['missing.onnx'])
    def fail(*args, **kwargs):
        raise AssertionError('preview loaded or downloaded a model')
    monkeypatch.setattr(voice, '_engine', fail)
    monkeypatch.setattr(voice, 'download', fail)
    monkeypatch.setattr(net, 'download', fail)
    status, data = studio(f'/api/voices/{lang}/{voice.VOICES[lang][0][0]}/sample')
    assert status == 400
    assert data['error'] == (f'The voices download with your first video (about {size} MB). '
                             'Make a video once, then you can hear every voice here.')


@MODELS
def test_cached_respelling_keeps_times_for_each_original_text(tmp_path):
    """The same sound under two caption spellings gets two clips, each timed to its own text."""
    original = voice.synthesize('Say win.', 'en', tmp_path)
    respelled = voice.synthesize('Say Nguyen.', 'en', tmp_path, lexicon={'Nguyen': 'win'})
    assert respelled.wav != original.wav
    assert len(respelled.char_times) == len('Say Nguyen.')
    again = voice.synthesize('Say win.', 'en', tmp_path)
    assert again.wav == original.wav and len(again.char_times) == len('Say win.')


@MODELS
def test_faster_voice_has_shorter_audio_and_times_for_every_original_character(tmp_path):
    text = 'Honey lasts for years. Bees visit flowers to make it.'
    normal = voice.synthesize(text, 'en', tmp_path / 'normal', 'am_michael', 1.0)
    faster = voice.synthesize(text, 'en', tmp_path / 'faster', 'am_michael', 1.1)
    assert faster.duration < normal.duration
    assert len(normal.char_times) == len(faster.char_times) == len(text)


def test_voice_settings_round_trip_and_validate_before_writing(studio):
    assert studio('/api/projects/Honey/voice') == (200, {'lang': 'en', 'voice': 'af_heart', 'speed': 1.0, 'pronounce': ''})
    body = {'voice': 'bm_george', 'speed': .9, 'pronounce': '# names\nGIF = jif\nNguyen = win\n'}
    status, settings = studio('/api/projects/Honey/voice', body, 'PUT')
    assert status == 200 and settings == {'lang': 'en', **body}
    assert studio('/api/projects/Honey/voice') == (200, settings)
    project = studio.root / 'Honey'
    cfg = pipeline.settings(project)
    assert cfg['voice'] == 'bm_george' and cfg['speed'] == .9 and cfg['script'] == 'script.md'
    assert (project / 'pronounce.txt').read_text(encoding='utf-8') == body['pronounce']
    for change in ({'speed': 1.3}, {'speed': .8}, {'speed': 'fast'}, {'voice': 'zf_001'}, {'pronounce': '# comment\n\nbad line'}):
        status, error = studio('/api/projects/Honey/voice', {**body, **change}, 'PUT')
        assert status == 400
        if 'pronounce' in change:
            assert 'Line 3 of pronounce.txt should look like "word = how to say it"' in error['error']
        assert studio('/api/projects/Honey/voice') == (200, settings)
    assert server.state()['voices']['en'][0] == {'id': 'af_heart', 'name': 'Heart, US woman (default)'}
    assert voice.voice_name('bm_george') == 'George, UK man'
    assert voice.voice_name('cli_voice') == 'cli_voice'
    assert studio('/api/voices/en/zf_001/sample')[0] == 400
    assert studio('/api/voices/en/am_michael/sample?speed=1.3')[0] == 400
    assert studio('/api/projects/Honey/voice', {**body, 'pronounce': '  \n'}, 'PUT')[1]['pronounce'] == ''
    assert not (project / 'pronounce.txt').exists()


def test_new_project_saves_speed_and_rejects_bad_settings(studio, monkeypatch):
    monkeypatch.setattr(server.director, 'direct', lambda *a: {})
    body = {'text': '# Speed\n\nA short script.', 'voice': 'am_michael', 'speed': 1.1}
    status, created = studio('/api/projects', body)
    assert status == 200
    for _ in range(100):
        job = studio('/api/jobs/' + created['job'])[1]
        if job['state'] in ('done', 'failed'):
            break
        time.sleep(.01)
    assert job['state'] == 'done', job
    assert pipeline.settings(studio.root / created['project'])['speed'] == 1.1
    assert studio('/api/projects', {**body, 'speed': 1.3})[0] == 400


def test_command_line_keeps_pronunciations_with_the_project_and_refuses_a_bad_file_first(tmp_path):
    words = tmp_path / 'words.txt'
    words.write_text('honey = huh nee\nGIF\n', encoding='utf-8')
    with pytest.raises(SystemExit) as end:
        cli.main(['new', str(FIXTURES / 'tiny.md'), '-o', str(tmp_path / 'Bad'), '--pronounce', str(words)])
    assert 'Line 2 of pronounce.txt should look like "word = how to say it"' in str(end.value.code)
    assert not (tmp_path / 'Bad').exists()
    words.write_text('honey = huh nee\n', encoding='utf-8')
    cli.main(['new', str(FIXTURES / 'tiny.md'), '-o', str(tmp_path / 'Good'), '--pronounce', str(words),
              '--voice', 'am_michael', '--speed', '1.1'])
    assert (tmp_path / 'Good' / 'pronounce.txt').read_text(encoding='utf-8') == 'honey = huh nee\n'
    assert pipeline.settings(tmp_path / 'Good')['speed'] == 1.1


def test_the_studio_picks_voices_for_the_language_the_script_will_be_read_in():
    import shutil
    import subprocess
    from kinodraw import ingest
    from kinodraw.studio import server
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    source = re.search(r'^function scriptLang\(.*?^}', js, re.S | re.M)[0]
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    texts = ['Today we learn the Mandarin greeting 你好 and when to use it.', '今天我们学习蜂蜜。', 'Bees make honey.',
             '', '蜂蜜 honey bees work hard all day', '¿Cómo comen las plantas? Las plantas usan la luz del sol.',
             'El Niño warms the Pacific and changes the weather.']
    out = subprocess.run([node, '-e', source + f'\nconsole.log(JSON.stringify({json.dumps(texts)}.map(scriptLang)))'],
                         capture_output=True, text=True, check=True, encoding='utf-8').stdout
    assert json.loads(out) == [ingest.detect_lang(t) for t in texts]

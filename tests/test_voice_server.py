"""Opt-in speech servers: actual HTTP/audio, project routing, and Studio/CLI settings."""
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest

from kinodraw import cli, package, paths, pipeline, voice, voice_server
from kinodraw.director.llm import providers
from kinodraw.studio import server as studio_server

TEXT = '# Small steps\n\nPlants need sunlight. Roots drink water. Leaves make food.'
API_KEY = voice_server.api_key


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(('KINODRAW_VOICE_', 'KINODRAW_SERVER_', 'DOODLE_VOICE_', 'DOODLE_SERVER_', 'TTS_')):
            monkeypatch.delenv(name)
    monkeypatch.setattr(paths, 'migrate', lambda *a, **k: [])
    monkeypatch.setattr(paths, 'cache_dir', lambda: tmp_path / 'cache')
    monkeypatch.setattr(paths, 'config_dir', lambda: tmp_path / 'config')
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(providers, 'SAVED', tmp_path / 'saved-keys.json')
    monkeypatch.setattr(studio_server, 'CONFIG', tmp_path / 'studio.json')
    monkeypatch.setattr(voice_server, 'api_key', lambda *a, **k: None)


@pytest.fixture
def audio_bytes(tmp_path):
    """Non-24k audio, with long enough silences to test pause-aware timing."""
    rate = 22050
    tone = .3 * np.sin(2 * np.pi * 220 * np.arange(round(rate * .6)) / rate)
    quiet = np.zeros(round(rate * .25))
    samples = np.concatenate((quiet, tone, quiet, tone, quiet, tone, quiet))
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((samples * 32767).astype('<i2').tobytes())
    source = tmp_path / 'source.wav'
    source.write_bytes(buf.getvalue())
    mp3 = tmp_path / 'source.mp3'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(source),
                    '-c:a', 'libmp3lame', '-y', str(mp3)], check=True, capture_output=True)
    return {'wav': buf.getvalue(), 'mp3': mp3.read_bytes(), 'garbage': b'this is not audio'}


@pytest.fixture
def speech_servers(audio_bytes):
    active = []

    def start(fmt='wav', status=200):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append({'path': self.path, 'headers': dict(self.headers), 'body': body,
                                 'authorization': self.headers.get('Authorization')})
                data = audio_bytes[fmt] if status == 200 else b'test server failure'
                self.send_response(status)
                self.send_header('Content-Type', 'audio/mpeg' if fmt == 'mp3' else 'audio/wav')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        active.append(httpd)
        return f'http://127.0.0.1:{httpd.server_port}', requests

    yield start
    for httpd in active:
        httpd.shutdown()
        httpd.server_close()


def no_kokoro(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('a server request tried to download or synthesize with Kokoro')
    monkeypatch.setattr(voice, 'ensure_models', forbidden)
    monkeypatch.setattr(voice, 'synthesize', forbidden)


def project(tmp_path, **cfg):
    folder = tmp_path / 'Video'
    pipeline.new_project(TEXT, folder, lang='en', **cfg)
    return folder


@pytest.mark.parametrize('fmt,suffix', [('wav', ''), ('mp3', '/v1/')])
def test_pipeline_decodes_real_server_audio_and_times_every_caption(tmp_path, monkeypatch, speech_servers, fmt, suffix):
    url, requests = speech_servers(fmt)
    no_kokoro(monkeypatch)
    folder = project(tmp_path, speed=1.07)
    server = voice_server.Server(url + suffix, 'test-model', 'test-voice')
    clips = pipeline.narrate(folder, server=server)
    assert pipeline.settings(folder)['voice_server'] == {'model': 'test-model', 'voice': 'test-voice'}   # no address
    board = pipeline.storyboard(folder)
    assert set(clips) == {beat['id'] for beat in board['beats']}
    assert len(requests) == len(clips)
    for beat in board['beats']:
        clip = clips[beat['id']]
        with wave.open(str(clip.wav), 'rb') as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
            assert abs(wav.getnframes() / 24000 - clip.duration) < .002
        times = clip.char_times
        assert len(times) == len(beat['spoken']['en'])
        assert all(0 <= time <= clip.duration for time in times)
        assert all(a <= b for a, b in zip(times, times[1:]))
        assert times[-1] > times[0]
    assert (folder / pipeline.READ_ALOUD).is_file()
    for request in requests:
        assert request['path'] == '/v1/audio/speech'
        assert request['headers']['Content-Type'] == 'application/json'
        assert request['body']['model'] == 'test-model'
        assert request['body']['voice'] == 'test-voice'
        assert request['body']['response_format'] == 'wav'
        assert request['body']['speed'] == 1.07
        assert request['body']['input'] in [beat['spoken']['en'] for beat in board['beats']]
    count = len(requests)
    repeated = pipeline.narrate(folder, server=server)
    assert len(requests) == count
    assert {key: clip.wav for key, clip in repeated.items()} == {key: clip.wav for key, clip in clips.items()}


def test_cache_excludes_credentials_but_tracks_endpoint_model_voice_and_speed(tmp_path, speech_servers):
    url, calls = speech_servers()
    cache = tmp_path / 'voice'
    text = 'Plants need sunlight. Roots drink water.'
    a = voice_server.synthesize(text, 'en', cache, voice_server.Server(url, 'model-a', 'voice-a', 'test-token-a'))
    b = voice_server.synthesize(text, 'en', cache, voice_server.Server(url + '/v1/', 'model-a', 'voice-a', 'test-token-b'))
    assert a.wav == b.wav and len(calls) == 1
    assert calls[0]['authorization'] == 'Bearer test-token-a'
    for model, speaker, speed in [('model-b', 'voice-a', 1), ('model-a', 'voice-b', 1), ('model-a', 'voice-a', 1.1)]:
        clip = voice_server.synthesize(text, 'en', cache, voice_server.Server(url, model, speaker), speed)
        assert clip.wav != a.wav
    assert len(calls) == 4
    other, more = speech_servers()
    assert voice_server.synthesize(text, 'en', cache, voice_server.Server(other, 'model-a', 'voice-a')).wav != a.wav
    assert len(more) == 1
    assert all('test-token' not in file.read_text() for file in cache.glob('*.json'))


def test_server_timings_skip_measured_sentence_pauses_and_keep_caption_spelling(tmp_path, speech_servers):
    url, calls = speech_servers()
    text = 'KinoDraw draws. Roots drink. Leaves grow.'
    clip = voice_server.synthesize(text, 'en', tmp_path / 'voice', voice_server.Server(url, 'test-model'),
                                   lexicon={'KinoDraw': 'Kee no draw'})
    assert calls[0]['body']['input'] == 'Kee no draw draws. Roots drink. Leaves grow.'
    assert len(clip.char_times) == len(text)
    for pos in [i for i, char in enumerate(text) if char == '.'][:-1]:
        assert clip.char_times[pos + 2] - clip.char_times[pos] >= .2


def test_environment_requires_explicit_backend_and_valid_model():
    assert voice_server.from_env({}) is None
    assert voice_server.from_env({'TTS_BACKEND': 'kokoro', 'TTS_API_BASE': 'http://localhost:1'}) is None
    assert voice_server.from_env({'TTS_BACKEND': 'openai_compatible', 'TTS_API_BASE': 'http://localhost:1/v1/',
                                  'TTS_MODEL': ' test-model ', 'TTS_VOICE': 'test-voice'}) == {
        'url': 'http://localhost:1/v1', 'model': 'test-model', 'voice': 'test-voice'}
    for env in ({'TTS_BACKEND': 'bogus'}, {'TTS_BACKEND': 'openai_compatible'},
                {'TTS_BACKEND': 'openai_compatible', 'TTS_API_BASE': 'http://localhost:1'}):
        with pytest.raises(voice_server.VoiceServerError):
            voice_server.from_env(env)


def test_cli_rejects_bad_backend_and_missing_model_before_creating_project(tmp_path, monkeypatch):
    monkeypatch.setenv('TTS_BACKEND', 'bogus')
    with pytest.raises(SystemExit, match='TTS_BACKEND accepts only kokoro or openai_compatible'):
        cli.main(['new', TEXT, '-o', str(tmp_path / 'Bad'), '--director', 'rules'])
    assert not (tmp_path / 'Bad').exists()
    monkeypatch.delenv('TTS_BACKEND')
    with pytest.raises(SystemExit, match='model name'):
        cli.main(['new', TEXT, '-o', str(tmp_path / 'Missing'), '--director', 'rules',
                  '--voice-server', 'http://localhost:1234'])
    assert not (tmp_path / 'Missing').exists()


@pytest.mark.parametrize('cfg', [{}, None])
def test_invalid_saved_server_config_never_uses_kokoro(tmp_path, monkeypatch, cfg):
    no_kokoro(monkeypatch)
    folder = project(tmp_path, voice_server=cfg)
    with pytest.raises(voice_server.VoiceServerError):
        pipeline.narrate(folder)


@pytest.mark.parametrize('status,fmt', [(401, 'wav'), (500, 'wav'), (200, 'garbage')])
def test_failed_server_never_falls_back_to_kokoro(tmp_path, monkeypatch, speech_servers, status, fmt):
    url, calls = speech_servers(fmt, status)
    no_kokoro(monkeypatch)
    folder = project(tmp_path)
    with pytest.raises(voice_server.VoiceServerError) as exc:
        pipeline.narrate(folder, server=voice_server.Server(url, 'test-model'))
    assert calls
    message = str(exc.value)
    assert 'Settings' in message and 'Voice server' in message
    assert '--voice-server' in message and 'TTS_' in message
    if status == 401:
        assert 'key' in message.lower()
    elif status == 500:
        assert 'HTTP 500' in message
    else:
        assert 'audio' in message and 'can play' in message


def test_refused_connection_is_actionable_and_does_not_fall_back(tmp_path, monkeypatch):
    no_kokoro(monkeypatch)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        url = f'http://127.0.0.1:{sock.getsockname()[1]}'
    folder = project(tmp_path)
    with pytest.raises(voice_server.VoiceServerError, match='Voice server'):
        pipeline.narrate(folder, server=voice_server.Server(url, 'test-model'))


@pytest.mark.parametrize('reply', [lambda auth: b'XYZ ' + auth + b'\r\n\r\n',
                                   lambda auth: b'HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\nRIFF',
                                   lambda auth: b'HTTP/1.1 500 Oops\r\nContent-Length: 100000\r\n\r\nfail'],
                         ids=['bad-status-line-echoing-key', 'cut-off-body', 'cut-off-error-body'])
def test_broken_server_response_is_a_clear_error_without_the_key(reply):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)

    def answer():
        conn, _ = sock.accept()
        with conn:
            data = b''
            while b'\r\n\r\n' not in data:
                data += conn.recv(65536)
            head, _, body = data.partition(b'\r\n\r\n')
            lines = head.split(b'\r\n')
            length = int(next(l for l in lines if l.lower().startswith(b'content-length')).split(b':')[1])
            while len(body) < length:
                body += conn.recv(65536)
            auth = next(l for l in lines if l.lower().startswith(b'authorization')).split(b': ', 1)[1]
            conn.sendall(reply(auth))
        sock.close()

    threading.Thread(target=answer, daemon=True).start()
    server = voice_server.Server(f'http://127.0.0.1:{sock.getsockname()[1]}/v1', 'test-model', key='test-secret')
    with pytest.raises(voice_server.VoiceServerError) as exc:
        voice_server.speech(server, 'hello', 1.0)
    message = str(exc.value)
    assert 'test-secret' not in message and 'voice server' in message and 'Voice server' in message


@pytest.mark.parametrize('url', ['', 'ftp://x', 'file:///etc/passwd', 'localhost:8880', 'http://', 'http://user:password@localhost',
                                'http://localhost?secret=value', 'http://localhost#fragment'])
def test_invalid_base_urls_are_rejected_before_any_network(url, monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('network for invalid URL'))
    with pytest.raises(voice_server.VoiceServerError):
        voice_server.check_url(url)


def test_default_pipeline_stays_offline_and_keeps_positional_synthesize_contract(tmp_path, monkeypatch):
    folder = project(tmp_path)
    monkeypatch.setenv('TTS_BACKEND', 'openai_compatible')
    monkeypatch.setenv('TTS_API_BASE', 'http://127.0.0.1:1')
    monkeypatch.setenv('TTS_MODEL', 'test-model')
    monkeypatch.setattr(voice_server, 'api_key', lambda: pytest.fail('default voice read server key'))
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('default voice used network'))
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('default voice opened socket'))
    monkeypatch.setattr(voice_server, 'synthesize', lambda *a, **k: pytest.fail('default voice used speech server'))
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: None)
    calls = []

    def synthesize(text, lang, cache, speaker, speed, lexicon):
        calls.append((text, lang, cache, speaker, speed, lexicon))
        return voice.Clip(cache / 'local.wav', 1, [0] * len(text))
    monkeypatch.setattr(voice, 'synthesize', synthesize)
    clips = pipeline.narrate(folder)
    assert len(calls) == len(clips) and calls
    assert all(call[1] == 'en' and call[3] == voice.LANGS['en']['voice'] for call in calls)


def test_recording_uses_local_guides_even_with_server_config(tmp_path, monkeypatch):
    folder = project(tmp_path, voice_server={'model': 'test-model', 'voice': ''}, recording='recording.wav')
    seen = []
    monkeypatch.setattr(voice_server, 'synthesize', lambda *a, **k: pytest.fail('recording used server'))
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: seen.append('models'))
    monkeypatch.setattr(voice, 'synthesize', lambda text, *a: voice.Clip(Path('local.wav'), 1, [0] * len(text)))
    expected = {'recorded': voice.Clip(Path('recording.wav'), 1, [0])}
    monkeypatch.setattr(voice, 'from_recording', lambda *a: expected)
    assert pipeline.narrate(folder) is expected and seen == ['models']
    assert pipeline.narrate(folder, server=voice_server.Server('http://127.0.0.1:1', 'test-model')) is expected


@pytest.fixture
def studio_http(tmp_path, monkeypatch):
    root = tmp_path / 'videos'
    studio_server._save_config({'projects': str(root)})
    monkeypatch.setattr(providers, 'saved', lambda: set())
    httpd, url = studio_server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None, token=True, method=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Studio-Token'] = studio_server.Handler.token
        req = urllib.request.Request(url + path.lstrip('/'),
                                     data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        try:
            response = opener.open(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = response.read()
            return response.code, json.loads(data) if 'json' in response.headers['Content-Type'] else data
    call.root = root
    yield call
    httpd.shutdown()
    httpd.server_close()


def test_startup_lists_saved_key_names_without_keychain_reads(monkeypatch):
    import keyring
    monkeypatch.setattr(keyring, 'get_password', lambda *a, **k: pytest.fail('startup read keychain'))
    monkeypatch.setattr(providers, 'api_key', lambda *a: pytest.fail('startup read provider key'))
    monkeypatch.setattr(voice_server, 'api_key', lambda *a, **k: pytest.fail('startup read speech key'))
    studio_server._save_config({'voice_server': {'on': True, 'url': 'http://127.0.0.1:1234/v1', 'model': 'm', 'voice': ''}})
    monkeypatch.setattr(providers, 'saved', lambda: {'voice-server:http://127.0.0.1:1234'})
    state = studio_server.state()
    assert state['voice_server'] == {'on': True, 'url': 'http://127.0.0.1:1234/v1', 'model': 'm', 'voice': '',
                                     'key_saved': True}
    monkeypatch.setattr(providers, 'saved', lambda: {'voice-server:http://127.0.0.1:4321', 'voice-server'})
    assert studio_server.state()['voice_server']['key_saved'] is False      # a key for another address is not this one's
    studio_server._save_config({})
    assert studio_server.state()['voice_server'] == {'on': False, 'url': '', 'model': '', 'voice': '', 'key_saved': False}


def test_api_key_is_read_only_when_requested_and_env_is_the_fallback(monkeypatch):
    import keyring
    calls = []
    monkeypatch.setenv('TTS_API_KEY', 'test-env-token')
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: (calls.append((service, name)), None)[1])
    assert calls == []
    assert API_KEY('http://127.0.0.1:1234/v1') == 'test-env-token'           # TTS_API_BASE unset: the CLI's own pair
    assert calls == [(paths.APP, 'voice-server:http://127.0.0.1:1234')]
    monkeypatch.setenv('TTS_API_BASE', 'http://127.0.0.1:1234/v1')
    assert API_KEY('http://127.0.0.1:1234') == 'test-env-token'
    assert API_KEY('http://127.0.0.1:4321/v1') is None                        # TTS_API_KEY belongs to TTS_API_BASE
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: 'test-saved-token'
                        if name == 'voice-server:http://127.0.0.1:4321' else None)
    assert API_KEY('http://127.0.0.1:4321/v1') == 'test-saved-token'


def test_studio_saves_only_valid_config_and_keys_stay_private(studio_http, speech_servers, monkeypatch):
    url, calls = speech_servers()
    saved = []
    monkeypatch.setattr(voice_server, 'save_key', lambda *a: saved.append(a))
    body = {'on': True, 'url': url, 'model': 'test-model', 'voice': 'test-voice', 'key': 'test-token'}
    status, info = studio_http('/api/voice-server', body)
    assert status == 200, info
    cfg = studio_server._config()
    assert cfg['voice_server']['url'] == url and cfg['voice_server']['model'] == 'test-model'
    assert cfg['voice_server']['voice'] == 'test-voice' and cfg['voice_server']['on'] is True
    assert saved == [(url, 'test-token')] and not calls
    assert 'test-token' not in studio_server.CONFIG.read_text()
    assert 'test-token' not in json.dumps(info)
    for update in ({**body, 'url': 'file:///tmp/speech'}, {**body, 'model': ''},
                   {**body, 'on': False, 'url': 'ftp://x'}, {**body, 'on': False, 'url': ''}):
        assert studio_http('/api/voice-server', update)[0] == 400
        assert studio_server._config() == cfg and saved == [(url, 'test-token')]


def test_studio_test_plays_real_audio_without_saving_settings(studio_http, speech_servers, monkeypatch):
    url, calls = speech_servers('mp3')
    no_kokoro(monkeypatch)
    monkeypatch.setattr(voice_server, 'save_key', lambda *a: pytest.fail('test saved a key'))
    before = studio_server.CONFIG.read_bytes()
    status, result = studio_http('/api/voice-server/test',
                                 {'url': url, 'model': 'test-model', 'voice': 'test-voice', 'key': 'test-token'})
    assert status == 200, result
    assert result['ok'] and result['seconds'] > 0 and len(calls) == 1
    assert studio_server.CONFIG.read_bytes() == before
    assert calls[0]['authorization'] == 'Bearer test-token'
    assert studio_http('/api/voice-server/test.wav', token=False)[0] == 403
    status, data = studio_http('/api/voice-server/test.wav')
    assert status == 200
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
    assert studio_http('/api/voice-server/test.wav?token=' + studio_server.Handler.token, token=False)[0] == 200
    assert studio_http('/api/voice-server/test',
                       {'url': url, 'model': 'test-model', 'key': 'changed-test-token'})[0] == 200
    assert len(calls) == 2 and calls[-1]['authorization'] == 'Bearer changed-test-token'
    assert studio_http('/api/voice-server/test', {'url': 'file:///tmp', 'model': 'test-model'})[0] == 400
    assert studio_server.CONFIG.read_bytes() == before


def test_studio_settings_apply_credit_server_voice_and_off_to_existing_project(tmp_path):
    folder = project(tmp_path)
    studio_server._save_config({'credit': False, 'voice_server': {
        'on': True, 'url': 'http://127.0.0.1:1234', 'model': 'test-model', 'voice': 'server-choice'}})
    server = studio_server.apply_video_settings(folder)
    cfg = pipeline.settings(folder)
    assert cfg['credit'] is False
    assert cfg['voice_server'] == {'model': 'test-model', 'voice': 'server-choice'}
    assert (server.url, server.model, server.voice) == ('http://127.0.0.1:1234', 'test-model', 'server-choice')
    assert cfg['voice'] == voice.LANGS['en']['voice']
    studio_server._save_config({'credit': True, 'voice_server': {'on': False}})
    assert studio_server.apply_video_settings(folder) is None
    cfg = pipeline.settings(folder)
    assert cfg['credit'] is True and 'voice_server' not in cfg


def test_project_server_voice_is_saved_through_http_and_builtin_choices_stay_valid(studio_http):
    folder = studio_http.root / 'Video'
    pipeline.new_project(TEXT, folder, lang='en')
    cfg = studio_server._config()
    cfg['voice_server'] = {'on': True, 'url': 'http://127.0.0.1:1234', 'model': 'test-model', 'voice': 'default-choice'}
    studio_server._save_config(cfg)
    body = {'voice': voice.LANGS['en']['voice'], 'speed': 1, 'server_voice': 'project-choice'}
    status, result = studio_http('/api/projects/Video/voice', body, method='PUT')
    assert status == 200, result
    assert result['server_voice'] == 'project-choice'
    studio_server.apply_video_settings(folder)
    saved = pipeline.settings(folder)
    assert saved['voice_server']['voice'] == 'project-choice' and saved['voice'] == voice.LANGS['en']['voice']
    for update in ({**body, 'server_voice': ['wrong']}, {**body, 'voice': 'arbitrary-server-choice'}):
        assert studio_http('/api/projects/Video/voice', update, method='PUT')[0] == 400
        assert pipeline.settings(folder) == saved



def test_new_video_takes_a_server_voice_only_while_the_server_is_on(studio_http, monkeypatch):
    monkeypatch.setattr(studio_server.director, 'direct', lambda *a, **k: {'notes': [], 'usage': None})
    cfg = studio_server._config()
    cfg['voice_server'] = {'on': True, 'url': 'http://127.0.0.1:1234', 'model': 'test-model', 'voice': 'default-choice'}
    studio_server._save_config(cfg)

    def create(title, **body):
        status, created = studio_http('/api/projects', {'text': TEXT, 'title': title, **body})
        assert status == 200, created
        job = studio_server.JOBS.get(created['job'])
        deadline = time.monotonic() + 10
        while job['state'] not in ('done', 'failed') and time.monotonic() < deadline:
            time.sleep(.02)
        assert job['state'] == 'done', job['error']
        return pipeline.settings(studio_http.root / created['project'])

    chosen = create('Chosen', server_voice=' project-choice ')
    assert chosen['server_voice'] == 'project-choice' and chosen['voice'] == voice.LANGS['en']['voice']
    assert 'server_voice' not in create('Blank', server_voice='')           # blank = the Settings voice
    for wrong in ('x' * 81, ['wrong']):
        assert studio_http('/api/projects', {'text': TEXT, 'title': 'Wrong', 'server_voice': wrong})[0] == 400
    cfg['voice_server']['on'] = False
    studio_server._save_config(cfg)
    assert 'server_voice' not in create('Off', server_voice='project-choice')

@pytest.mark.parametrize('lang,own,kokoro', [('en', "creator's own", 'Kokoro'), ('zh', '作者本人', 'Kokoro'),
                                          ('es', 'creador', 'Kokoro')])
def test_published_credits_describe_server_and_preserve_local_and_own_voice(tmp_path, monkeypatch, lang, own, kokoro):
    folder = tmp_path / 'Video'
    board = pipeline.new_project(TEXT, folder, lang=lang, voice_server={'model': 'test-model', 'voice': 'test-voice'})
    build = folder / 'build'
    build.mkdir()
    for ext in ('srt', 'vtt'):
        (build / f'captions.{ext}').write_text('captions')
    tl = {'duration': 1, 'chapters': [{'id': c['id'], 'title': c['title'].get(lang, ''), 'start': 0}
                                     for c in board['chapters']]}
    pipeline._save(build / 'timeline.json', tl)
    monkeypatch.setattr(pipeline.audio, 'mix', lambda *a: build / 'mix.wav')
    monkeypatch.setattr(pipeline, 'mux', lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'encoded_qa', lambda *a, **k: {'ok': True, 'problems': []})
    monkeypatch.setattr(pipeline, 'contact_sheet', lambda *a, **k: None)
    monkeypatch.setattr(package, 'thumbnail', lambda *a, **k: None)
    pipeline.finish(folder)
    description = next(folder.glob('*-description.txt'))
    credit = description.read_text()
    assert 'test-model' in credit and 'test-voice' in credit and 'Kokoro' not in credit
    cfg = pipeline.settings(folder)
    cfg['recording'] = 'recording.wav'
    pipeline._save(folder / 'project.json', cfg)
    pipeline.finish(folder)
    assert own in description.read_text() and 'test-model' not in description.read_text()
    cfg.pop('recording')
    cfg.pop('voice_server')
    pipeline._save(folder / 'project.json', cfg)
    pipeline.finish(folder)
    assert kokoro in description.read_text()


def test_cli_new_uses_env_defaults_and_explicit_server_overrides(tmp_path, monkeypatch):
    from kinodraw import director
    monkeypatch.setattr(director, 'direct', lambda *a, **k: {})
    monkeypatch.setattr(cli, '_report', lambda *a: None)
    monkeypatch.setenv('TTS_BACKEND', 'openai_compatible')
    monkeypatch.setenv('TTS_API_BASE', 'http://127.0.0.1:1234/v1')
    monkeypatch.setenv('TTS_MODEL', 'env-model')
    monkeypatch.setenv('TTS_VOICE', 'env-voice')
    a, b = tmp_path / 'A', tmp_path / 'B'
    cli.main(['new', TEXT, '-o', str(a), '--director', 'rules'])
    assert pipeline.settings(a)['voice_server'] == {'model': 'env-model', 'voice': 'env-voice'}   # never the address
    cli.main(['new', TEXT, '-o', str(b), '--director', 'rules', '--voice-server', 'http://127.0.0.1:4321',
              '--server-model', 'explicit-model', '--server-voice', 'explicit-voice'])
    assert pipeline.settings(b)['voice_server'] == {'model': 'explicit-model', 'voice': 'explicit-voice'}
    with pytest.raises(SystemExit):
        cli.main(['new', TEXT, '-o', str(tmp_path / 'Bad'), '--director', 'rules',
                  '--voice-server', 'file:///tmp/speech', '--server-model', 'test-model'])


def test_cli_voice_none_removes_saved_server_and_key_provider_is_available(tmp_path, monkeypatch):
    folder = project(tmp_path, voice_server={'model': 'test-model', 'voice': ''})
    seen = []
    monkeypatch.setattr(pipeline, 'narrate', lambda path, *a, **k: (seen.append(pipeline.settings(path)), {})[1])
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: {'duration': 1, 'captions': []})
    cli.main(['voice', str(folder), '--voice-server', 'none'])
    assert 'voice_server' not in pipeline.settings(folder) and 'voice_server' not in seen[0]
    monkeypatch.setattr(cli, 'cmd_key', lambda args: seen.append(args.provider))
    cli.main(['key', 'set', 'voice-server'])
    assert seen[-1] == 'voice-server'


# ------------------------------------------------------------------ security: only this computer chooses the server
def fake_keychain(monkeypatch, url, key):
    """A keychain holding ``key`` for the server at ``url`` (under the old single name and the per-address one)."""
    import keyring
    store = {(paths.APP, 'voice-server'): key, (paths.APP, f'voice-server:{url}'): key}
    monkeypatch.setattr(keyring, 'set_password', lambda service, name, value: store.__setitem__((service, name), value))
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: store.get((service, name)))
    monkeypatch.setattr(voice_server, 'api_key', API_KEY)
    return store


def socket_guard(monkeypatch):
    attempts = []

    def connect(sock, address):
        attempts.append(address)
        raise ConnectionRefusedError('test guard: no network')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    return attempts


def test_a_project_that_names_a_server_contacts_nothing_while_this_computers_setting_is_off(tmp_path, monkeypatch,
                                                                                            speech_servers):
    """A project from someone else whose project.json names a server (with a key saved on this computer for that very
    server) never sends the script or the key anywhere: only this computer's setting chooses the server."""
    url, requests = speech_servers()
    fake_keychain(monkeypatch, url, 'test-token-saved-here')
    folder = project(tmp_path, voice_server={'url': url, 'model': 'test-model', 'voice': 'test-voice'})
    attempts = socket_guard(monkeypatch)
    with pytest.raises(voice_server.VoiceServerError) as exc:
        pipeline.narrate(folder)
    with pytest.raises(SystemExit) as cli_exit:
        cli.main(['voice', str(folder)])
    assert attempts == [] and requests == []
    for message in (str(exc.value), str(cli_exit.value)):
        assert 'nothing was sent' in message and 'Settings > Voice server' in message and '--voice-server none' in message
    studio_server._save_config({'voice_server': {'on': False, 'url': url, 'model': 'test-model'}})
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: None)
    monkeypatch.setattr(voice, 'synthesize', lambda text, *a: voice.Clip(Path('local.wav'), 1., [0.] * len(text)))
    server = studio_server.apply_video_settings(folder)           # what Make video does first: Settings decide
    assert server is None and 'voice_server' not in pipeline.settings(folder)
    assert pipeline.narrate(folder, server=server)
    assert attempts == [] and requests == []


def _wait_job(call, job, seconds=20):
    import time
    for _ in range(int(seconds / .05)):
        info = call(f'/api/jobs/{job}')[1]
        if info['state'] in ('done', 'failed'):
            return info
        time.sleep(.05)
    raise AssertionError(f'job {job} did not finish')


def test_a_key_saved_for_one_server_is_never_sent_to_another(studio_http, speech_servers, monkeypatch):
    a, calls_a = speech_servers()
    b, calls_b = speech_servers()
    fake_keychain(monkeypatch, 'http://127.0.0.1:1', 'unused')
    status, info = studio_http('/api/voice-server', {'on': True, 'url': a, 'model': 'test-model', 'key': 'test-token-a'})
    assert status == 200, info
    assert studio_http('/api/voice-server/test', {'url': a, 'model': 'test-model'})[0] == 200
    assert calls_a[-1]['authorization'] == 'Bearer test-token-a'
    assert studio_http('/api/voice-server/test', {'url': b, 'model': 'test-model'})[0] == 200     # Test with another address
    assert calls_b[-1]['authorization'] is None
    assert studio_http('/api/voice-server', {'on': True, 'url': b, 'model': 'test-model'})[0] == 200   # address changed
    pipeline.new_project(TEXT, studio_http.root / 'Video', lang='en')
    no_kokoro(monkeypatch)
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: (_ for _ in ()).throw(RuntimeError('stop after the voice')))
    before = len(calls_b)
    job = _wait_job(studio_http, studio_http('/api/projects/Video/make', {})[1]['job'])
    assert 'stop after the voice' in job['error']
    assert len(calls_b) > before and all(call['authorization'] is None for call in calls_b)
    assert len(calls_a) == 1


@pytest.mark.parametrize('code', [301, 302, 303, 307, 308])
def test_a_redirecting_server_never_gets_the_key_carried_to_another_address(code):
    seen, elsewhere = [], []

    class Elsewhere(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            elsewhere.append((self.command, self.headers.get('Authorization')))
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()
        do_POST = do_GET

    class Redirect(Elsewhere):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            seen.append(self.headers.get('Authorization'))
            self.send_response(code)
            self.send_header('Location', f'http://localhost:{other.server_port}/steal')
            self.send_header('Content-Length', '0')
            self.end_headers()

    other = ThreadingHTTPServer(('127.0.0.1', 0), Elsewhere)
    first = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
    for httpd in (other, first):
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        server = voice_server.Server(f'http://127.0.0.1:{first.server_port}/v1', 'test-model', key='test-secret')
        with pytest.raises(voice_server.VoiceServerError) as error:
            voice_server.speech(server, 'Hello.', 1.0)
    finally:
        for httpd in (other, first):
            httpd.shutdown()
            httpd.server_close()
    assert seen == ['Bearer test-secret']
    assert elsewhere == []
    assert 'redirect' in str(error.value) and 'test-secret' not in str(error.value)


@pytest.mark.parametrize('key', ['test-secret\ninvalid', 'test-secret\r\nX-Evil: 1', 'test-secret\u2019'])
def test_a_malformed_key_is_refused_without_showing_it_or_sending_anything(speech_servers, key):
    url, calls = speech_servers()
    with pytest.raises(voice_server.VoiceServerError) as error:
        voice_server.speech(voice_server.Server(url, 'test-model', key=key), 'Hello.', 1.0)
    assert calls == []
    assert 'test-s' not in str(error.value) and 'API key' in str(error.value)


# ------------------------------------------------------------------ the server's own voice list (Settings, New video, Narrator)
@pytest.fixture
def voice_lists():
    """A local server answering GET with each route's (status, JSON); anything else is a 404."""
    active = []

    def start(routes):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append({'path': self.path, 'authorization': self.headers.get('Authorization')})
                status, body = routes.get(self.path) or routes.get(self.path.split('?')[0]) or (404, {'detail': 'Not Found'})
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        active.append(httpd)
        return f'http://127.0.0.1:{httpd.server_port}', requests

    yield start
    for httpd in active:
        httpd.shutdown()
        httpd.server_close()


VOICES = '/v1/audio/voices'
SHAPES = {   # each server's answer as its own code builds it (research: voicepicker/voice-list-research.md)
    'kokoro-fastapi': ({VOICES: (200, {'voices': [{'id': 'af_bella', 'name': 'af_bella', 'overall_grade': 'A'},
                                                  {'id': 'am_adam', 'name': 'am_adam'}], 'default_voice': 'af_heart'})},
                       VOICES, [('af_bella', 'af_bella'), ('am_adam', 'am_adam')]),
    'kokoro-legacy': ({VOICES: (200, {'voices': ['af_bella', 'am_adam']})}, VOICES,
                      [('af_bella', 'af_bella'), ('am_adam', 'am_adam')]),
    'qwentts.cpp': ({VOICES: (200, {'voices': [{'name': 'Vivian', 'kind': 'speaker'}, {'name': 'mine', 'kind': 'registered'}]})},
                    VOICES, [('mine', 'mine'), ('Vivian', 'Vivian')]),
    'voicestudio': ({VOICES: (200, {'voices': [{'voice_id': 'alloy', 'name': 'Alloy', 'type': 'openai_alias'},
                                               {'voice_id': 'p-7', 'name': 'Grandpa', 'type': 'profile', 'language': 'en'}],
                                    'engines': ['kokoro', 'chatterbox']})},
                    VOICES, [('alloy', 'Alloy'), ('p-7', 'Grandpa')]),
    'localai': ({VOICES: (200, {'data': [{'model': 'test-model', 'voices': [{'name': 'x', 'language': 'en'}]},
                                         {'model': 'other', 'voices': [{'name': 'y', 'gender': 'female'}]}]})},
                VOICES, [('x', 'x'), ('y', 'y')]),
    'orpheus': ({VOICES: (200, {'status': 'ok', 'voices': ['tara', 'leah']})}, VOICES, [('leah', 'leah'), ('tara', 'tara')]),
    'chatterbox-travisvn': ({'/v1/voices': (200, {'voices': [{'name': 'Emily', 'aliases': ['em'], 'language': 'en'}], 'count': 1})},
                            '/v1/voices', [('Emily', 'Emily')]),
    'chatterbox-devnen': ({VOICES: (200, {'status': 'ok', 'voices': ['x.wav']})}, VOICES, [('x.wav', 'x.wav')]),
    'speaches': ({VOICES: (200, {'voices': [{'name': 'af_heart', 'language': 'en', 'id': 'af_heart'}], 'object': 'list'})},
                 VOICES, [('af_heart', 'af_heart')]),
    'alltalk': ({'/api/voices': (200, {'status': 'success', 'voices': ['female_01.wav', 'male_01.wav']})},
                '/api/voices', [('female_01.wav', 'female_01.wav'), ('male_01.wav', 'male_01.wav')]),
    'openai-edge-tts': ({VOICES: (200, {'voices': [{'id': 'alloy', 'name': 'en-US-AvaNeural'}]})}, VOICES,
                        [('alloy', 'en-US-AvaNeural')]),
    'mlx-audio': ({VOICES + '?model=test-model': (200, {'object': 'list', 'model': 'test-model',
                                                        'data': [{'id': 'af_heart', 'name': 'af_heart'}]}),
                   VOICES: (400, {'detail': 'model is required'})}, VOICES, [('af_heart', 'af_heart')]),
    'vllm-omni': ({VOICES: (200, {'voices': ['b', 'a'], 'uploaded_voices': [{'name': 'u', 'consent': True}]})}, VOICES,
                  [('a', 'a'), ('b', 'b')]),
    'koboldcpp': ({VOICES: (200, {'status': 'ok', 'voices': ['kobo']})}, VOICES, [('kobo', 'kobo')]),
    'mistral': ({VOICES: (200, {'items': [{'id': 'v1', 'name': 'Voice One'}], 'page': 1})}, VOICES, [('v1', 'Voice One')]),
    'bare-list': ({'/audio/voices': (200, ['one', 'two', 'one'])}, '/audio/voices', [('one', 'one'), ('two', 'two')]),
}


@pytest.mark.parametrize('shape', SHAPES)
def test_voice_list_reads_each_known_server_shape(voice_lists, shape):
    routes, path, expected = SHAPES[shape]
    url, requests = voice_lists(routes)
    found = voice_server.list_voices(voice_server.Server(url + '/v1', 'test-model', key='test-token'))
    assert [(v['id'], v['name']) for v in found['voices']] == expected
    assert found['source'] == path
    assert requests[0]['path'] == '/v1/audio/voices?model=test-model'           # the common endpoint first, with the model
    assert requests[-1]['path'].split('?')[0] == path                            # stops at the first list
    assert all(r['authorization'] == ('Bearer test-token' if r['path'].startswith('/v1/') else None) for r in requests)


@pytest.mark.parametrize('routes,hint', [
    ({}, 'did not list'),                                                         # openedai-speech: no list endpoint
    ({'/api/voices': (200, {'status': 'error', 'message': 'not multivoice'})}, 'did not list'),   # AllTalk, one voice
    ({VOICES: (200, b'<html>nope</html>'), '/v1/voices': (200, {'voices': []})}, 'did not list'),
    ({VOICES: (200, {'voices': [{'id': 'x\nbad'}, {'language': 'en'}, 'y' * 81, 7]})}, 'did not list'),
    ({VOICES: (401, {'detail': 'no key'})}, 'API key'),
    ({VOICES: (500, {'detail': 'broken'}), '/v1/voices': (403, {'detail': 'no key'})}, 'API key'),
])
def test_a_server_without_a_usable_list_leaves_typing_the_name(voice_lists, routes, hint):
    url, requests = voice_lists(routes)
    found = voice_server.list_voices(voice_server.Server(url, 'test-model'))
    assert found['voices'] == [] and found['source'] is None and hint in found['message']
    if hint == 'API key':                                                        # no guessing past a refusal
        assert requests[-1]['path'].split('?')[0] in (VOICES, '/v1/voices') and len(requests) <= 2
    else:
        assert [r['path'].split('?')[0] for r in requests] == [VOICES, '/v1/voices', '/audio/voices', '/api/voices']


def test_an_unreachable_server_gives_a_reason_not_an_error(monkeypatch):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    found = voice_server.list_voices(voice_server.Server(f'http://127.0.0.1:{port}', 'test-model'))
    assert found['voices'] == [] and found['source'] is None and "couldn't reach" in found['message']


TTS1 = ['alloy', 'ash', 'coral', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer']


@pytest.mark.parametrize('model,voices', [('gpt-4o-mini-tts', sorted(TTS1 + ['ballad', 'verse', 'marin', 'cedar'])),
                                          ('tts-1', TTS1), ('tts-1-hd', TTS1)])   # OpenAI's TTS guide, "Voice options"
def test_openai_has_no_list_endpoint_so_its_documented_voices_are_offered_without_asking(monkeypatch, model, voices):
    attempts = socket_guard(monkeypatch)
    found = voice_server.list_voices(voice_server.Server('https://api.openai.com/v1', model, key='test-token'))
    assert [v['id'] for v in found['voices']] == voices
    assert found['source'] == 'known list' and attempts == []


def test_the_key_goes_only_to_voice_list_paths_under_the_address_entered(voice_lists):
    url, requests = voice_lists({'/api/voices': (200, {'voices': ['kobo']})})
    found = voice_server.list_voices(voice_server.Server(url + '/v1', 'test-model', key='test-token'))
    assert [v['id'] for v in found['voices']] == ['kobo']
    assert [(r['path'].split('?')[0], r['authorization']) for r in requests] == [(VOICES, 'Bearer test-token'),
        ('/v1/voices', 'Bearer test-token'), ('/audio/voices', None), ('/api/voices', None)]
    url, requests = voice_lists({'/audio/voices': (401, {'detail': 'no key'})})    # keyless outside /v1: not a refusal
    found = voice_server.list_voices(voice_server.Server(url + '/v1', 'test-model', key='test-token'))
    assert found['message'] == voice_server.NO_LIST and len(requests) == 4
    url, requests = voice_lists({'/api/voices': (200, {'voices': ['kobo']})})     # entered without /v1: all under it
    voice_server.list_voices(voice_server.Server(url, 'test-model', key='test-token'))
    assert all(r['authorization'] == 'Bearer test-token' for r in requests)


def test_the_studio_never_sends_an_unbound_tts_api_key_to_a_typed_address(studio_http, voice_lists, monkeypatch):
    import keyring
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: None)
    monkeypatch.setattr(voice_server, 'api_key', API_KEY)
    monkeypatch.setenv('TTS_API_KEY', 'test-env-token')                         # TTS_API_BASE unset
    assert API_KEY('http://127.0.0.1:1234/v1') == 'test-env-token'              # the CLI's own pair still works
    assert API_KEY('http://127.0.0.1:1234/v1', env_without_base=False) is None
    url, requests = voice_lists({VOICES: (200, {'voices': ['tara']})})
    assert studio_http('/api/voice-server/voices', {'url': url + '/v1', 'model': 'test-model'})[0] == 200
    assert requests and all(r['authorization'] is None for r in requests)
    monkeypatch.setenv('TTS_API_BASE', url + '/v1')                            # bound to this address: it goes there
    assert studio_http('/api/voice-server/voices', {'url': url + '/v1', 'model': 'test-model'})[0] == 200
    assert requests[-1]['authorization'] == 'Bearer test-env-token'


def test_the_voice_list_route_never_saves_and_sends_a_key_only_to_its_own_address(studio_http, voice_lists, monkeypatch):
    routes = {VOICES: (200, {'voices': ['tara']})}
    a, calls_a = voice_lists(routes)
    b, calls_b = voice_lists(routes)
    fake_keychain(monkeypatch, a, 'test-token-a')
    monkeypatch.setattr(voice_server, 'save_key', lambda *a: pytest.fail('listing voices saved a key'))
    before = studio_server.CONFIG.read_bytes()
    status, found = studio_http('/api/voice-server/voices', {'url': a + '/v1', 'model': 'test-model'})
    assert status == 200, found
    assert found['voices'] == [{'id': 'tara', 'name': 'tara'}] and found['source'] == VOICES and found['message']
    assert calls_a[-1]['authorization'] == 'Bearer test-token-a'
    assert studio_http('/api/voice-server/voices', {'url': b, 'model': 'test-model'})[0] == 200
    assert calls_b and all(call['authorization'] is None for call in calls_b)      # a's key never goes to b
    assert studio_http('/api/voice-server/voices', {'url': b, 'model': 'test-model', 'key': 'typed-token'})[0] == 200
    assert calls_b[-1]['authorization'] == 'Bearer typed-token'                     # a key typed in Settings, unsaved
    assert studio_http('/api/voice-server/voices', {'url': a, 'model': 'test-model'}, token=False)[0] == 403
    for wrong in ({'url': 'file:///tmp', 'model': 'test-model'}, {'url': a, 'model': ''}):
        assert studio_http('/api/voice-server/voices', wrong)[0] == 400
    assert studio_server.CONFIG.read_bytes() == before and len(calls_a) == 1


def test_a_redirect_from_the_voice_list_never_carries_the_key_elsewhere(voice_lists):
    other, elsewhere = voice_lists({VOICES: (200, {'voices': ['stolen']})})

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header('Location', other + self.path)
            self.send_header('Content-Length', '0')
            self.end_headers()

    first = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
    threading.Thread(target=first.serve_forever, daemon=True).start()
    try:
        found = voice_server.list_voices(voice_server.Server(f'http://127.0.0.1:{first.server_port}', 'm', key='test-secret'))
    finally:
        first.shutdown()
        first.server_close()
    assert elsewhere == [] and found['voices'] == []

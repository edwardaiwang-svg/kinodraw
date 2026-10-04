"""Opt-in speech servers: actual HTTP/audio, project routing, and Studio/CLI settings."""
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
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
    monkeypatch.setattr(voice_server, 'api_key', lambda: None)


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
    folder = project(tmp_path, voice_server={'url': url + suffix, 'model': 'test-model', 'voice': 'test-voice'}, speed=1.07)
    clips = pipeline.narrate(folder)
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
    repeated = pipeline.narrate(folder)
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
    folder = project(tmp_path, voice_server={'url': url, 'model': 'test-model'})
    with pytest.raises(voice_server.VoiceServerError) as exc:
        pipeline.narrate(folder)
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
    folder = project(tmp_path, voice_server={'url': url, 'model': 'test-model'})
    with pytest.raises(voice_server.VoiceServerError, match='Voice server'):
        pipeline.narrate(folder)


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
    folder = project(tmp_path, voice_server={'url': 'http://127.0.0.1:1', 'model': 'test-model'}, recording='recording.wav')
    seen = []
    monkeypatch.setattr(voice_server, 'synthesize', lambda *a, **k: pytest.fail('recording used server'))
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: seen.append('models'))
    monkeypatch.setattr(voice, 'synthesize', lambda text, *a: voice.Clip(Path('local.wav'), 1, [0] * len(text)))
    expected = {'recorded': voice.Clip(Path('recording.wav'), 1, [0])}
    monkeypatch.setattr(voice, 'from_recording', lambda *a: expected)
    assert pipeline.narrate(folder) is expected and seen == ['models']


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
    monkeypatch.setattr(voice_server, 'api_key', lambda *a: pytest.fail('startup read speech key'))
    monkeypatch.setattr(providers, 'saved', lambda: {'voice-server'})
    state = studio_server.state()
    assert state['voice_server'] == {'on': False, 'url': '', 'model': '', 'voice': '', 'key_saved': True}
    monkeypatch.setattr(providers, 'saved', lambda: set())
    assert studio_server.state()['voice_server']['key_saved'] is False


def test_api_key_is_read_only_when_requested_and_env_is_the_fallback(monkeypatch):
    import keyring
    calls = []
    monkeypatch.setenv('TTS_API_KEY', 'test-env-token')
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: (calls.append((service, name)), None)[1])
    assert calls == []
    assert API_KEY() == 'test-env-token'
    assert calls == [(paths.APP, 'voice-server')]
    monkeypatch.setattr(keyring, 'get_password', lambda *a: 'test-saved-token')
    assert API_KEY() == 'test-saved-token'


def test_studio_saves_only_valid_config_and_keys_stay_private(studio_http, speech_servers, monkeypatch):
    url, calls = speech_servers()
    saved = []
    monkeypatch.setattr(voice_server, 'save_key', lambda key: saved.append(key))
    body = {'on': True, 'url': url, 'model': 'test-model', 'voice': 'test-voice', 'key': 'test-token'}
    status, info = studio_http('/api/voice-server', body)
    assert status == 200, info
    cfg = studio_server._config()
    assert cfg['voice_server']['url'] == url and cfg['voice_server']['model'] == 'test-model'
    assert cfg['voice_server']['voice'] == 'test-voice' and cfg['voice_server']['on'] is True
    assert saved == ['test-token'] and not calls
    assert 'test-token' not in studio_server.CONFIG.read_text()
    assert 'test-token' not in json.dumps(info)
    for update in ({**body, 'url': 'file:///tmp/speech'}, {**body, 'model': ''},
                   {**body, 'on': False, 'url': 'ftp://x'}):
        assert studio_http('/api/voice-server', update)[0] == 400
        assert studio_server._config() == cfg and saved == ['test-token']


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
    studio_server.apply_video_settings(folder)
    cfg = pipeline.settings(folder)
    assert cfg['credit'] is False
    assert cfg['voice_server']['voice'] == 'server-choice'
    assert cfg['voice'] == voice.LANGS['en']['voice']
    studio_server._save_config({'credit': True, 'voice_server': {'on': False}})
    studio_server.apply_video_settings(folder)
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


@pytest.mark.parametrize('lang,own,kokoro', [('en', "creator's own", 'Kokoro'), ('zh', '作者本人', 'Kokoro'),
                                          ('es', 'creador', 'Kokoro')])
def test_published_credits_describe_server_and_preserve_local_and_own_voice(tmp_path, monkeypatch, lang, own, kokoro):
    folder = tmp_path / 'Video'
    board = pipeline.new_project(TEXT, folder, lang=lang, voice_server={
        'url': 'http://127.0.0.1:1234', 'model': 'test-model', 'voice': 'test-voice'})
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
    assert pipeline.settings(a)['voice_server'] == {
        'url': 'http://127.0.0.1:1234/v1', 'model': 'env-model', 'voice': 'env-voice'}
    cli.main(['new', TEXT, '-o', str(b), '--director', 'rules', '--voice-server', 'http://127.0.0.1:4321',
              '--server-model', 'explicit-model', '--server-voice', 'explicit-voice'])
    cfg = pipeline.settings(b)['voice_server']
    assert cfg['url'] == 'http://127.0.0.1:4321' and cfg['model'] == 'explicit-model' and cfg['voice'] == 'explicit-voice'
    with pytest.raises(SystemExit):
        cli.main(['new', TEXT, '-o', str(tmp_path / 'Bad'), '--director', 'rules',
                  '--voice-server', 'file:///tmp/speech', '--server-model', 'test-model'])


def test_cli_voice_none_removes_saved_server_and_key_provider_is_available(tmp_path, monkeypatch):
    folder = project(tmp_path, voice_server={'url': 'http://127.0.0.1:1', 'model': 'test-model'})
    seen = []
    monkeypatch.setattr(pipeline, 'narrate', lambda path, *a: (seen.append(pipeline.settings(path)), {})[1])
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: {'duration': 1, 'captions': []})
    cli.main(['voice', str(folder), '--voice-server', 'none'])
    assert 'voice_server' not in pipeline.settings(folder) and 'voice_server' not in seen[0]
    monkeypatch.setattr(cli, 'cmd_key', lambda args: seen.append(args.provider))
    cli.main(['key', 'set', 'voice-server'])
    assert seen[-1] == 'voice-server'

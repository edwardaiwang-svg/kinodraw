"""Product auth semantics, using only synthetic keys and a loopback Cloud."""
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import keyring
import pytest

from kinodraw import paths, pipeline
from kinodraw.director.llm import cloud, providers
from kinodraw.director.llm.director import LLMDirector
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.studio import integration, server


class V3Cloud:
    """The anonymous and v3 contract on loopback, with no real account."""
    def __init__(self):
        self.plan, self.seen = None, []
        fake = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fake.seen.append({'path': self.path, 'body': body, 'auth': self.headers.get('Authorization')})
                if self.path == '/v1/anonymous':
                    out = {'token': 'synthetic-anonymous-token', 'anonymous': True, 'plan': 'free'}
                elif self.path == '/v3/videos':
                    out = {'video_id': 'synthetic-video'}
                elif self.path == '/v3/plan':
                    assert body['video_id'] == 'synthetic-video'
                    out = {'plan': fake.plan, 'contract_version': 3,
                           'usage': {'model': 'gpt-6-luna', 'input_tokens': 30, 'output_tokens': 20}}
                else:
                    self.send_error(404)
                    return
                data = json.dumps(out).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()


@pytest.fixture(autouse=True)
def synthetic_auth(monkeypatch, tmp_path):
    for name in (*providers.KEY_ENV.values(), 'KINODRAW_CLOUD_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(providers, 'SAVED', tmp_path / 'saved-keys.json')
    monkeypatch.setattr(cloud, 'INSTALL_ID', tmp_path / 'install-id')
    monkeypatch.setattr(cloud, '_anon_token', None)


@pytest.mark.parametrize('kind,env', [('openai', 'OPENAI_API_KEY'), ('anthropic', 'ANTHROPIC_API_KEY'),
                                      ('compat', 'KINODRAW_COMPAT_API_KEY')])
def test_saved_key_then_environment_auth(kind, env, monkeypatch):
    body = {'director': kind, 'model': 'chosen-model'}
    if kind != 'anthropic':
        body['base_url'] = 'http://127.0.0.1:1/v1'
    monkeypatch.setenv(env, 'synthetic-env-key')
    keyring.set_password(paths.APP, kind, 'synthetic-saved-key')
    selected = integration.provider_for(body)
    assert selected.client.api_key == 'synthetic-saved-key'
    assert selected.model == 'chosen-model'
    if kind != 'anthropic':
        assert str(selected.client.base_url).rstrip('/') == body['base_url']
    keyring.delete_password(paths.APP, kind)
    assert integration.provider_for(body).client.api_key == 'synthetic-env-key'


@pytest.mark.parametrize('kind', ['openai', 'anthropic', 'compat', 'cloud'])
def test_explicit_credentials_do_not_read_keychain(kind, monkeypatch):
    reads = []
    monkeypatch.setattr(keyring, 'get_password', lambda *args: reads.append(args))
    body = {'director': kind, 'key': 'synthetic-request-key', 'token': 'synthetic-request-token'}
    if kind == 'compat':
        body.update(model='chosen-model', base_url='http://127.0.0.1:1/v1')
    selected = integration.provider_for(body)
    assert not reads
    assert (selected.token if kind == 'cloud' else selected.client.api_key) == (
        'synthetic-request-token' if kind == 'cloud' else 'synthetic-request-key')


def test_anthropic_new_default_and_explicit_model():
    assert integration.provider_for({'director': 'anthropic', 'key': 'synthetic'}).model == 'claude-opus-5-5'
    assert integration.provider_for({'director': 'anthropic', 'key': 'synthetic', 'model': 'chosen'}).model == 'chosen'


def test_command_explicit_environment_saved_precedence(monkeypatch):
    keyring.set_password(paths.APP, 'command', 'saved-command')
    monkeypatch.setenv('KINODRAW_DIRECTOR_COMMAND', 'env-command')
    assert integration.provider_for({'director': 'command', 'model': 'chosen'}).argv == ['env-command']
    assert integration.provider_for({'director': 'command', 'command': 'explicit-command'}).argv == ['explicit-command']
    monkeypatch.delenv('KINODRAW_DIRECTOR_COMMAND')
    selected = integration.provider_for({'director': 'command', 'model': 'chosen'})
    assert selected.argv == ['saved-command'] and selected.model == 'chosen'


@pytest.fixture
def local_cloud(monkeypatch, tmp_path):
    fake = V3Cloud()
    monkeypatch.setattr(cloud, 'URL', fake.url)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    monkeypatch.setattr(server, 'projects_root', lambda: tmp_path / 'projects')
    monkeypatch.setattr(server, 'JOBS', server.Jobs())
    monkeypatch.setattr(server, 'STUDIO_HOOKS', integration.hooks())
    monkeypatch.setattr(RulesDirector, '__init__', lambda self, lang: setattr(self, 'lang', lang))
    monkeypatch.setattr(RulesDirector, 'direct', lambda self, board: board)
    def payload(self, board, chapter, beats, count):
        fake.plan = from_rules(board)
        return {'beats': [{'beat_id': b['id'], 'text': b['display'][board['lang']], 'candidates': []} for b in beats]}
    monkeypatch.setattr(LLMDirector, '_payload', payload)
    yield fake
    fake.httpd.shutdown()
    fake.httpd.server_close()
    fake.thread.join(timeout=5)


def _created(body):
    made = server.create_project({'text': '# Test\n\nA small idea.', **body})
    job = server.JOBS.get(made['job'])
    deadline = time.monotonic() + 10
    while job['state'] not in ('done', 'failed', 'cancelled') and time.monotonic() < deadline:
        time.sleep(.02)
    assert job['state'] == 'done', job
    return server.projects_root() / made['project']


def test_studio_default_full_v3_anonymous_cloud_and_cached_plan(local_cloud, monkeypatch):
    assert server.state()['cloud_signed_in'] is False
    path = _created({})
    cfg = pipeline.settings(path)
    assert cfg['director'] == 'cloud' and cfg['director_v3'] and not cfg['plan_v3_report']['fallback']
    assert [(c['path'], c['auth']) for c in local_cloud.seen] == [
        ('/v1/anonymous', None), ('/v3/videos', 'Bearer synthetic-anonymous-token'),
        ('/v3/plan', 'Bearer synthetic-anonymous-token')]
    assert keyring.get_password(paths.APP, 'cloud-token') is None
    assert server.state()['cloud_signed_in'] is False
    assert keyring.get_password(paths.APP, 'cloud-anon-token') == 'synthetic-anonymous-token'
    from kinodraw import director
    monkeypatch.setattr(director, 'provider_for', lambda *a: pytest.fail('cached provider'))
    pipeline.direct_v3(path)
    assert len(local_cloud.seen) == 3
    assert 'synthetic-anonymous-token' not in json.dumps(cfg)


def test_studio_spanish_rules_do_not_request_cloud_auth(local_cloud):
    path = _created({'text': '# Las abejas\n\nLas abejas visitan flores.', 'lang': 'es', 'director': 'cloud'})
    assert pipeline.settings(path)['director'] == 'rules'
    assert local_cloud.seen == [] and not cloud.INSTALL_ID.exists()


def test_explicit_cloud_token_is_transient_in_full_v3(local_cloud, monkeypatch):
    reads = []
    monkeypatch.setattr(keyring, 'get_password', lambda *args: reads.append(args))
    path = _created({'token': 'synthetic-request-token'})
    assert not reads and not cloud.INSTALL_ID.exists()
    assert [(c['path'], c['auth']) for c in local_cloud.seen] == [
        ('/v3/videos', 'Bearer synthetic-request-token'), ('/v3/plan', 'Bearer synthetic-request-token')]
    assert not pipeline.settings(path)['plan_v3_report']['fallback']
    assert 'synthetic-request-token' not in (path / 'project.json').read_text(encoding='utf-8')


def test_cloud_environment_then_saved_auth_precedence(monkeypatch):
    keyring.set_password(paths.APP, 'cloud-token', 'synthetic-saved-token')
    monkeypatch.setenv('KINODRAW_CLOUD_TOKEN', 'synthetic-env-token')
    assert integration.provider_for({'director': 'cloud'}).token == 'synthetic-env-token'
    monkeypatch.delenv('KINODRAW_CLOUD_TOKEN')
    assert integration.provider_for({'director': 'cloud'}).token == 'synthetic-saved-token'

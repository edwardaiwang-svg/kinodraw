"""The Studio as a new user first opens it: no projects yet, not signed in to Doodle Cloud."""
import json
import urllib.request

import pytest

from doodlestudio.director.llm import cloud, providers
from doodlestudio.studio import server


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """The real local server, with its own settings file and an empty projects folder."""
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    monkeypatch.setattr(cloud, 'URL', 'https://api.example.org')     # Doodle Cloud is offered on every install
    monkeypatch.delenv('DOODLE_CLOUD_TOKEN', raising=False)
    monkeypatch.setattr(providers, 'saved', lambda: set())           # nobody signed in
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path, **headers):
        req = urllib.request.Request(url + path.lstrip('/'), headers={'X-Studio-Token': server.Handler.token, **headers})
        with opener.open(req, timeout=10) as reply:
            return reply.status, dict(reply.headers), reply.read()
    yield get
    httpd.shutdown()


def test_signed_out_users_start_with_the_offline_director(studio, monkeypatch):
    """v0.1.6 preselected Doodle Cloud on every install, so a first Create sent a new user to the sign-in."""
    assert json.loads(studio('/api/state')[2])['default_director'] == 'rules'
    monkeypatch.setattr(providers, 'saved', lambda: {'cloud-token'})
    assert json.loads(studio('/api/state')[2])['default_director'] == 'cloud'
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert 'directorOptions(STATE.default_director)' in js           # the New video page follows it

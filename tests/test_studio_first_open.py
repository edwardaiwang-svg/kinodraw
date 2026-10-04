"""The Studio as a new user first opens it: no projects yet, not signed in to KinoDraw Cloud."""
import json
import re
import urllib.request

import pytest

from kinodraw.director.llm import cloud, providers
from kinodraw.studio import server


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """The real local server, with its own settings file and an empty projects folder."""
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    monkeypatch.setattr(cloud, 'URL', 'https://api.example.org')     # KinoDraw Cloud is offered on every install
    monkeypatch.delenv('KINODRAW_CLOUD_TOKEN', raising=False)
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


def test_first_open_shows_a_finished_example_with_nothing_to_download(studio):
    """A new user's first video takes about a minute plus a 260 MB download; the example that ships with the
    app plays at once, offline."""
    assert json.loads(studio('/api/projects')[2]) == []             # first open: nothing made yet
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert re.search(r'openProject\(items\[0\]\.name\);\s*else showSample\(\)', js)   # ...so the example opens
    page = studio('/')[2].decode()
    sample = re.search(r'<template id="tpl-sample">.*?</template>', page, re.S).group(0)
    video, poster = re.search(r'<video[^>]* src="([^"]+)"', sample).group(1), re.search(r'poster="([^"]+)"', sample).group(1)
    status, headers, head = studio(video, Range='bytes=0-1023')    # how <video> asks for it
    assert status == 206 and headers['Content-Type'] == 'video/mp4' and head[4:8] == b'ftyp'
    assert 1e6 < int(headers['Content-Range'].split('/')[1]) < 6e6   # a finished video, small enough to ship
    assert studio(poster)[1]['Content-Type'] == 'image/jpeg'
    assert 'id="btn-sample"' in page and 'btn-sample' in js          # and it can be watched again later


def test_opening_the_studio_looks_up_no_host_names(monkeypatch):
    """http.server's server_bind() looks up 127.0.0.1's name (socket.getfqdn); on macOS that reverse lookup made
    KinoDraw 0.2.0 ask "Allow KinoDraw to find devices on local networks?" before its window opened."""
    import socket
    asked = []
    for name in ('getfqdn', 'gethostbyaddr', 'gethostname'):
        monkeypatch.setattr(socket, name, lambda *args, name=name: asked.append(name) or '')
    httpd, url = server.serve(0)
    httpd.shutdown()
    assert url.startswith('http://127.0.0.1:') and asked == []

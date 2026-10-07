from pathlib import Path

import pytest

from kinodraw import pipeline, starters
from kinodraw.director.validate import validate


def test_eight_editable_en_zh_starters_build_real_boards(tmp_path):
    entries = starters.list_starters()
    assert len(entries) >= 8
    assert {entry['lang'] for entry in entries} == {'en', 'zh'}
    for entry in entries:
        text = starters.read(entry['id'])
        assert 'Invented example' in text or '虚构示例' in text
        assert Path(entry['path']).suffix == '.md'
        board = pipeline.new_project(text, tmp_path / entry['id'], lang=entry['lang'])
        assert validate(board, tmp_path / entry['id'])['ok']


@pytest.mark.parametrize('name', ['../bad', '/tmp/bad', 'unknown', 'explainer-en.md'])
def test_unknown_starter_is_refused(name):
    with pytest.raises(ValueError):
        starters.read(name)


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """The real local server with its own settings file and projects folder."""
    import json
    import urllib.error
    import urllib.request
    from kinodraw.studio import server
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path):
        req = urllib.request.Request(url + path.lstrip('/'), headers={'X-Studio-Token': server.Handler.token})
        try:
            with opener.open(req, timeout=10) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as reply:
            return reply.code, json.loads(reply.read())
    yield get
    httpd.shutdown(); httpd.server_close()


def test_the_studio_lists_starters_without_file_paths(studio):
    """New video offers the examples from /api/state; neither list gives away where the app is installed."""
    for listed in (studio('/api/starters')[1], studio('/api/state')[1]['starters']):
        assert len(listed) == 8
        assert all(set(entry) == {'id', 'lang', 'title', 'example_data'} for entry in listed)
        assert {entry['lang'] for entry in listed} == {'en', 'zh'}


def test_the_studio_serves_each_starter_text(studio):
    status, entry = studio('/api/starters/explainer-zh')
    assert status == 200
    assert entry == {'id': 'explainer-zh', 'lang': 'zh', 'title': '图书角怎样运转', 'text': starters.read('explainer-zh')}


@pytest.mark.parametrize('name', ['unknown', 'explainer-en.md', '..%2Fbad'])
def test_the_studio_refuses_an_unknown_starter(studio, name):
    status, body = studio('/api/starters/' + name)
    assert status == 400 and 'unknown starter' in body['error']

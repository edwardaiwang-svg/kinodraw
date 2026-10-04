"""Videos end with a short "Made with KinoDraw" credit, on by default, with one switch to turn it off
(the Studio Make panel, or `kinodraw make --no-credit`), remembered."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

import pytest

import kinodraw
from kinodraw import cli, pipeline
from kinodraw.engine import timeline
from kinodraw.studio import server

TINY = Path(__file__).parent / 'fixtures' / 'tiny.md'


def _board(tmp_path):
    return pipeline.new_project(TINY, tmp_path / 'Honey')


def test_a_video_ends_with_the_credit_unless_it_is_switched_off(tmp_path):
    board = _board(tmp_path)
    clips = timeline.synthetic_clips(board, 'en')
    on, off = timeline.layout(board, 'en', clips), timeline.layout(board, 'en', clips, credit=False)
    assert on['credit'] == {'start': round(on['duration'] - timeline.CREDIT, 4), 'end': on['duration']}
    assert off['credit'] is None and round(on['duration'] - off['duration'], 3) == timeline.CREDIT
    assert on['end_card']['start'] == off['end_card']['start'] and on['end_card']['end'] == on['duration']
    assert 1.5 <= timeline.CREDIT <= 2.5                                         # short


def test_the_cli_switch_is_remembered_in_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'cmd_new', lambda args: pipeline.new_project(Path(args.script), Path(args.out),
                                                                          **cli._settings(args)))
    cli.main(['new', str(TINY), '-o', str(tmp_path / 'A'), '--no-credit'])
    cli.main(['new', str(TINY), '-o', str(tmp_path / 'B')])
    assert pipeline.settings(tmp_path / 'A')['credit'] is False and 'credit' not in pipeline.settings(tmp_path / 'B')
    seen = {}
    monkeypatch.setattr(pipeline.audio, 'assemble', lambda *a, credit=True, **k: (seen.update(credit=credit), {})[1])
    monkeypatch.setattr(pipeline.renderer, 'pacing', lambda *a: {})
    monkeypatch.setattr(pipeline.audio, 'timing', lambda clips: {})
    monkeypatch.setattr(pipeline, '_save', lambda *a: None)
    pipeline.build_audio(tmp_path / 'A', {})
    assert seen['credit'] is False                                             # voice / render / finish follow it


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    root = tmp_path / 'videos'
    server._save_config({'projects': str(root)})
    pipeline.new_project(TINY, root / 'Honey')
    pipeline.new_project(TINY, root / 'Bees')
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(name, body=None):
        req = urllib.request.Request(url + 'api/projects/' + name,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={'X-Studio-Token': server.Handler.token, 'Content-Type': 'application/json'})
        with opener.open(req, timeout=10) as response:
            return json.load(response)
    try:
        yield root, api
    finally:
        httpd.shutdown()
        httpd.server_close()


def _make_credit(name, monkeypatch):
    seen = {}

    def narrate(path, progress=None):
        seen['credit'] = pipeline.settings(path)['credit']
        raise RuntimeError('stop here')
    monkeypatch.setattr(pipeline, 'narrate', narrate)
    job = server.JOBS.get(server.make_video(name)['job'])
    deadline = time.monotonic() + 5
    while job['state'] not in ('done', 'failed') and time.monotonic() < deadline:
        time.sleep(.05)
    assert job['state'] == 'failed' and 'stop here' in job['error']
    return seen['credit']


def test_the_make_panel_box_is_on_by_default_and_saved_per_project(studio):
    root, api = studio
    assert api('Honey')['credit'] is True
    assert api('Honey/credit', {'credit': False})['credit'] is False
    assert api('Honey')['credit'] is False and api('Bees')['credit'] is True
    assert pipeline.settings(root / 'Honey')['credit'] is False
    assert 'credit' not in pipeline.settings(root / 'Bees')
    before = (root / 'Honey' / 'project.json').read_bytes()
    with pytest.raises(urllib.error.HTTPError) as error:
        api('Honey/credit', {'credit': 'no'})
    assert error.value.code == 400
    assert json.load(error.value)['error'] == 'credit must be true or false'
    assert (root / 'Honey' / 'project.json').read_bytes() == before
    assert api('Honey')['credit'] is False and api('Bees')['credit'] is True
    assert 'credit' not in pipeline.settings(root / 'Bees')
    assert 'credit' not in server._config() and 'credit' not in server.state()
    assert server.state()['product'] == kinodraw.PRODUCT['name']


def test_the_next_make_follows_the_box_and_re_ticking_restores_the_card(studio, monkeypatch):
    root, api = studio
    api('Honey/credit', {'credit': False})
    board = pipeline.storyboard(root / 'Honey')
    clips = timeline.synthetic_clips(board, 'en')
    captured = _make_credit('Honey', monkeypatch)
    assert captured is False
    assert timeline.layout(board, 'en', clips, credit=captured)['credit'] is None
    api('Honey/credit', {'credit': True})
    captured = _make_credit('Honey', monkeypatch)
    assert captured is True and api('Honey')['credit'] is True
    layout = timeline.layout(board, 'en', clips, credit=captured)
    assert layout['credit']['end'] == layout['duration']
    assert _make_credit('Bees', monkeypatch) is True


def test_an_old_settings_switch_still_applies_to_projects_that_never_chose(studio, monkeypatch):
    root, api = studio
    server._save_config({'projects': str(root), 'credit': False})
    assert 'credit' not in pipeline.settings(root / 'Honey')
    assert api('Honey')['credit'] is False
    assert _make_credit('Honey', monkeypatch) is False
    api('Honey/credit', {'credit': True})
    assert api('Honey')['credit'] is True
    assert _make_credit('Honey', monkeypatch) is True
    assert server._config()['credit'] is False
    assert api('Bees')['credit'] is False


def test_the_end_card_control_is_on_the_make_panel_only():
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    html = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    assert 'p-credit' in js and '/credit' in js and 's-credit' not in js
    assert 'p-credit' in html


def test_the_product_name_and_address_live_in_one_place():
    assert kinodraw.PRODUCT == {'name': 'KinoDraw', 'url': 'edwardaiwang-svg.github.io/kinodraw'}
    from kinodraw import package
    from kinodraw.engine import auto_scenes
    src = Path(auto_scenes.__file__).read_text(encoding='utf-8')
    assert 'KinoDraw' not in src.split('def build_credit')[1].split('\ndef ')[0]        # the credit reads PRODUCT
    from kinodraw.engine.collage import promo
    src = Path(promo.__file__).read_text(encoding='utf-8')
    assert 'KinoDraw' not in src.split('def credit')[1].split('\ndef ')[0]                # so does the collage's
    assert 'KinoDraw' not in Path(package.__file__).read_text(encoding='utf-8')         # so do the metadata and description

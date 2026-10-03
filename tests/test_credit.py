"""Videos end with a short "Made with KinoDraw" credit, on by default, with one switch to turn it off
(Studio Settings, or `kinodraw make --no-credit`), remembered."""
import json
from pathlib import Path

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


def test_the_studio_switch_is_remembered_and_applies_to_the_next_video(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    assert server.state()['credit'] is True and server.state()['product'] == kinodraw.PRODUCT['name']
    httpd, url = server.serve(0)
    try:
        import urllib.request
        req = urllib.request.Request(url + 'api/settings', data=json.dumps({'credit': False}).encode(), method='POST',
                                     headers={'X-Studio-Token': server.Handler.token, 'Content-Type': 'application/json'})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10).read()
    finally:
        httpd.shutdown()
    assert server.state()['credit'] is False and json.loads((tmp_path / 'studio.json').read_text())['credit'] is False
    pipeline.new_project(TINY, tmp_path / 'videos' / 'Honey')
    seen = {}

    def narrate(path, progress=None):
        seen['credit'] = pipeline.settings(path)['credit']
        raise RuntimeError('stop here')
    monkeypatch.setattr(pipeline, 'narrate', narrate)
    job = server.JOBS.get(server.make_video('Honey')['job'])
    for _ in range(100):
        if job['state'] in ('done', 'failed'):
            break
        __import__('time').sleep(.05)
    assert seen['credit'] is False
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert 's-credit' in js and 'credit: e.target.checked' in js


def test_the_product_name_and_address_live_in_one_place():
    assert kinodraw.PRODUCT == {'name': 'KinoDraw', 'url': 'edwardaiwang-svg.github.io/kinodraw'}
    from kinodraw import package
    from kinodraw.engine import auto_scenes
    src = Path(auto_scenes.__file__).read_text(encoding='utf-8')
    assert 'KinoDraw' not in src.split('def build_credit')[1].split('\ndef ')[0]        # the credit reads PRODUCT
    assert 'KinoDraw' not in Path(package.__file__).read_text(encoding='utf-8')         # so do the metadata and description

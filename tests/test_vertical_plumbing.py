"""Project formats reach rendering and packaging without synthesizing or encoding anything."""
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from kinodraw import cli, director, package, pipeline, styles
from kinodraw.director.llm import providers
from kinodraw.studio import server

TINY = Path(__file__).parent / 'fixtures' / 'tiny.md'


def test_cli_saves_format_and_rejects_bad_values(tmp_path, monkeypatch):
    monkeypatch.setattr(director, 'direct', lambda *a, **k: {'warnings': [], 'notes': [], 'usage': None})
    project = tmp_path / 'short'
    cli.main(['new', str(TINY), '-o', str(project), '--aspect', '9:16'])
    assert pipeline.settings(project)['aspect'] == '9:16'
    with pytest.raises(SystemExit) as error:
        cli.main(['new', str(TINY), '-o', str(tmp_path / 'bad'), '--aspect', '4:3'])
    assert error.value.code == 2
    assert not (tmp_path / 'bad').exists()


def test_cli_render_saves_format_before_render_and_rejects_bad_values(tmp_path, monkeypatch):
    pipeline.new_project(TINY, tmp_path)
    calls = []
    def render(project, *args):
        calls.append(pipeline.settings(project)['aspect'])
        build = project / 'build'
        build.mkdir(exist_ok=True)
        pipeline._save(build / 'render-warnings.json', [])
        return build / 'silent.mp4'
    monkeypatch.setattr(pipeline, 'render', render)
    cli.main(['render', str(tmp_path), '--aspect', '9:16'])
    assert calls == ['9:16']
    assert pipeline.settings(tmp_path)['aspect'] == '9:16'
    before = (tmp_path / 'project.json').read_bytes()
    with pytest.raises(SystemExit) as error:
        cli.main(['render', str(tmp_path), '--aspect', '4:3'])
    assert error.value.code == 2
    assert (tmp_path / 'project.json').read_bytes() == before
    assert calls == ['9:16']

    entries = [dict(e, aspect=['16:9']) if e['id'] == 'whiteboard' else e for e in styles.looks()]
    monkeypatch.setattr(styles, '_looks', lambda: tuple(entries))
    with pytest.raises(SystemExit, match='does not support'):
        cli.main(['render', str(tmp_path), '--aspect', '9:16'])
    assert (tmp_path / 'project.json').read_bytes() == before
    assert calls == ['9:16']


def test_studio_creates_and_changes_format(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'projects_root', lambda: tmp_path)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    monkeypatch.setattr(providers, 'saved', lambda: set())
    monkeypatch.setattr(director, 'direct', lambda *a, **k: {'notes': [], 'usage': None})
    assert [f['value'] for f in server.state()['formats']] == list(pipeline.ASPECTS)
    created = server.create_project({'text': TINY.read_text(encoding='utf-8'), 'aspect': '9:16'})
    deadline = time.monotonic() + 10
    while server.JOBS.get(created['job'])['state'] not in ('done', 'failed') and time.monotonic() < deadline:
        time.sleep(.02)
    job = server.JOBS.get(created['job'])
    assert job['state'] == 'done', job['error']
    project = tmp_path / created['project']
    assert pipeline.settings(project)['aspect'] == '9:16'
    with pytest.raises(ValueError, match='aspect must'):
        server.create_project({'text': TINY.read_text(encoding='utf-8'), 'aspect': '4:3'})

    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for aspect, status in [('16:9', 200), ('9:16', 200), ('1:1', 200), ('4:3', 400)]:
            req = urllib.request.Request(url + 'api/projects/' + urllib.parse.quote(created['project']) + '/format',
                                         data=json.dumps({'aspect': aspect}).encode(),
                                         headers={'X-Studio-Token': server.Handler.token})
            try:
                reply = opener.open(req, timeout=10)
            except urllib.error.HTTPError as error:
                reply = error
            with reply:
                assert reply.code == status
                result = json.loads(reply.read())
            assert pipeline.settings(project)['aspect'] == (aspect if status == 200 else '1:1')
            if status == 400:
                assert 'aspect must' in result['error']
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_registry_restrictions_and_default(tmp_path, monkeypatch):
    project = tmp_path / 'default'
    pipeline.new_project(TINY, project)
    assert pipeline.settings(project)['aspect'] == '16:9'
    entries = [dict(e, aspect=['16:9']) if e['id'] == 'whiteboard' else e for e in styles.looks()]
    monkeypatch.setattr(styles, '_looks', lambda: tuple(entries))
    monkeypatch.setattr(server, 'projects_root', lambda: tmp_path)
    with pytest.raises(ValueError, match='does not support'):
        cli.main(['new', str(TINY), '-o', str(tmp_path / 'bad'), '--aspect', '9:16'])
    with pytest.raises(ValueError, match='does not support'):
        server.create_project({'text': TINY.read_text(encoding='utf-8'), 'aspect': '9:16'})
    with pytest.raises(ValueError, match='does not support'):
        server.set_format('default', {'aspect': '9:16'})
    assert pipeline.settings(project)['aspect'] == '16:9'
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('look', ['whiteboard', 'chalkboard', 'notebook', 'collage'])
def test_thumbnail_sizes_and_landscape_bytes(tmp_path, look):
    board = pipeline.new_project(TINY, tmp_path / 'project', direction={'look': look})
    portrait, default, explicit = [tmp_path / f'{name}.png' for name in ('portrait', 'default', 'explicit')]
    package.thumbnail(board, 'en', portrait, tmp_path, size=(720, 1280))
    package.thumbnail(board, 'en', default, tmp_path)
    package.thumbnail(board, 'en', explicit, tmp_path, size=(1280, 720))
    with Image.open(portrait) as img:
        assert img.size == (720, 1280)
    with Image.open(default) as img:
        assert img.size == (1280, 720)
    assert default.read_bytes() == explicit.read_bytes()
    if look != 'collage':
        square = tmp_path / 'square.png'
        package.thumbnail(board, 'en', square, tmp_path, size=(720, 720))
        with Image.open(square) as img:
            assert img.size == (720, 720)


def test_encoded_qa_checks_requested_size(tmp_path, monkeypatch):
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'fake video')
    from kinodraw.qa import probes
    monkeypatch.setattr(probes, 'probe', lambda *args, **kwargs: probes.QAReport(str(video), 1))
    monkeypatch.setattr(package, '_probe', lambda p: {
        'size': re.match(r'(\d+)x(\d+)', '1080x1920'), 'frames': 30, 'audio': True, 'errors': [], 'chapters': []})
    monkeypatch.setattr(package, 'read_wav', lambda p: (np.zeros((package.SR, 2)), package.SR))
    monkeypatch.setattr(package, '_run', lambda *a, **k: SimpleNamespace(stdout=b'\0\0' * 100))
    tl = {'duration': 1, 'chapters': []}
    assert package.encoded_qa(tl, video, tmp_path / 'mix.wav', size=(1080, 1920))['ok']
    assert any(p.startswith('streams:') for p in package.encoded_qa(tl, video, tmp_path / 'mix.wav')['problems'])


@pytest.mark.parametrize('workers', [1, 2])
@pytest.mark.parametrize('aspect', pipeline.ASPECTS)
def test_render_passes_format_to_production_and_segments(tmp_path, monkeypatch, workers, aspect):
    # Native square is a whiteboard target; collage retains its letterboxed
    # landscape/portrait contract (pipeline.validate_size).
    look = 'whiteboard' if aspect == '1:1' else 'collage'
    pipeline.new_project(TINY, tmp_path, aspect=aspect, direction={'look': look})
    build = tmp_path / 'build'
    build.mkdir()
    pipeline._save(build / 'timeline.json', {'duration': 1})
    calls = []
    prod = SimpleNamespace(warnings=[], cues=lambda: ['cue'])
    monkeypatch.setattr(pipeline.renderer, 'make_production', lambda *a, **k: calls.append(('production', k)) or prod)
    monkeypatch.setattr(pipeline.renderer, 'render_segments', lambda *a, **k: calls.append(('segments', k)) or [])
    encoded = []
    monkeypatch.setattr(pipeline.renderer, 'encode', lambda *a, **k: encoded.append(k))
    pipeline.render(tmp_path, workers=workers)
    assert calls == ([('segments', {'aspect': aspect, 'context': None})] if workers == 2 else []) + (
        [('production', {'aspect': aspect})] if workers == 1 or look == 'collage' else [])
    assert encoded == ([{'context': None}] if workers == 1 else [])
    if look == 'collage':
        assert json.loads((build / 'cues.json').read_text(encoding='utf-8')) == {'cues': ['cue']}
    else:
        assert not (build / 'cues.json').exists()


@pytest.mark.parametrize('aspect', pipeline.ASPECTS)
def test_finish_uses_format_sizes_and_unwrapped_collage(tmp_path, monkeypatch, aspect):
    look = 'whiteboard' if aspect == '1:1' else 'collage'
    pipeline.new_project(TINY, tmp_path, aspect=aspect, direction={'look': look})
    build = tmp_path / 'build'
    build.mkdir()
    pipeline._save(build / 'timeline.json', {'duration': 1})
    calls = {}
    monkeypatch.setattr(pipeline.audio, 'mix', lambda *a: build / 'mix.wav')
    monkeypatch.setattr(pipeline, 'mux', lambda *a: calls.update(video=a[3], title=a[5]))
    def qa(*args, **kw):
        calls['qa'] = kw
        return {'ok': True, 'problems': []}
    monkeypatch.setattr(pipeline, 'encoded_qa', qa)
    monkeypatch.setattr(pipeline, 'publish', lambda *a, **k: calls.update(publish=k, stem=a[5]))
    monkeypatch.setattr(pipeline, 'contact_sheet', lambda *a, **k: calls.update(sheet=k))
    monkeypatch.setattr(pipeline.renderer, 'make_production', lambda *a, **k:
                        calls.update(production=k) or SimpleNamespace(crowded=lambda: [(0, 'a', 'b')]))
    size = {'16:9': (1920, 1080), '9:16': (1080, 1920), '1:1': (1080, 1080)}[aspect]
    monkeypatch.setattr(pipeline, 'video_size', lambda video: size)
    monkeypatch.setattr(pipeline.subprocess, 'run', lambda args, **k:
                        calls.update(decode=args) or SimpleNamespace(returncode=0, stderr=b''))
    # Stub the worker's implementation; real process/staging/full-decode
    # acceptance lives in test_finish_worker and test_native_pipeline.
    report = pipeline._finish(tmp_path)
    assert calls['qa']['size'] == calls['sheet']['size'] == size
    assert calls['publish']['size'] == {'16:9': (1280, 720), '9:16': (720, 1280), '1:1': (720, 720)}[aspect]
    assert '-xerror' in calls['decode'] and '0:v:0' in calls['decode'] and '0:a:0' in calls['decode']
    if look == 'collage':
        assert calls['production'].get('aspect', '16:9') == '16:9'
    else:
        assert 'production' not in calls
    title = pipeline.storyboard(tmp_path)['title']['en']
    stem = title + (' (vertical)' if aspect == '9:16' else '')
    assert calls['stem'] == stem
    assert calls['video'].name == f'{stem}.mp4'
    assert calls['title'] == title
    if look == 'collage':
        assert not report['ok'] and 'written on top' in report['problems'][0]
    else:
        assert report['ok'] and report['problems'] == []


@pytest.mark.parametrize('entrypoint', ['render', 'finish'])
def test_square_collage_is_rejected_before_outputs_are_touched(tmp_path, monkeypatch, entrypoint):
    with pytest.raises(ValueError, match='collage does not support 1:1'):
        pipeline.new_project(TINY, tmp_path / 'invalid', aspect='1:1', direction={'look': 'collage'})
    assert not (tmp_path / 'invalid').exists()
    pipeline.new_project(TINY, tmp_path, direction={'look': 'collage'})
    cfg = pipeline.settings(tmp_path)
    pipeline._save(tmp_path / 'project.json', {**cfg, 'aspect': '1:1'})
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(pipeline.subprocess, 'Popen', lambda *a, **k: pytest.fail('unsupported target reached worker'))
    with pytest.raises(ValueError, match='collage does not support 1:1'):
        getattr(pipeline, entrypoint)(tmp_path)
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_portrait_contact_sheet_tiles(tmp_path, monkeypatch):
    calls = []
    def run(cmd):
        calls.append(cmd)
        return SimpleNamespace(stdout=b'\xff' * (180 * 320 * 3))
    monkeypatch.setattr(package, '_run', run)
    path = tmp_path / 'sheet.jpg'
    package.contact_sheet({'duration': 1, 'chapters': []}, tmp_path / 'video', path, size=(1080, 1920))
    assert 'scale=180:320' in calls[0]
    with Image.open(path) as img:
        assert img.size == (1080, 346)


def test_cli_stills_use_project_format(tmp_path, monkeypatch):
    pipeline.new_project(TINY, tmp_path, aspect='9:16')
    build = tmp_path / 'build'
    build.mkdir()
    pipeline._save(build / 'timeline.json', {'duration': 1})
    calls = []
    prod = SimpleNamespace(frame=lambda t: Image.new('RGB', (1080, 1920)))
    monkeypatch.setattr(pipeline.renderer, 'make_production', lambda *a, **k: calls.append(k) or prod)
    cli.main(['render', str(tmp_path), '--stills', '0'])
    assert calls == [{'aspect': '9:16'}]
    with Image.open(build / 'stills' / '0000.00.png') as img:
        assert img.size == (1080, 1920)


@pytest.mark.parametrize('aspect', pipeline.ASPECTS)
def test_cli_stills_switch_and_save_project_format(tmp_path, monkeypatch, aspect):
    pipeline.new_project(TINY, tmp_path, aspect='9:16' if aspect == '16:9' else '16:9')
    build = tmp_path / 'build'
    build.mkdir()
    pipeline._save(build / 'timeline.json', {'duration': 1})
    calls = []
    size = (1080, 1920) if aspect == '9:16' else (1920, 1080)
    prod = SimpleNamespace(frame=lambda t: Image.new('RGB', size))
    def production(*args, **kwargs):
        calls.append(kwargs)
        assert pipeline.settings(tmp_path)['aspect'] == aspect
        return prod
    monkeypatch.setattr(pipeline.renderer, 'make_production', production)
    cli.main(['render', str(tmp_path), '--aspect', aspect, '--stills', '0'])
    assert pipeline.settings(tmp_path)['aspect'] == aspect
    assert calls == [{'aspect': aspect}]
    with Image.open(build / 'stills' / '0000.00.png') as img:
        assert img.size == size

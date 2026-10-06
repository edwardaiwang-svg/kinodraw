"""Targeted review regressions; runtime verification remains held for J."""
from argparse import Namespace

import pytest

from kinodraw import director, mcp_server, pipeline, voice
from kinodraw.project_store import ProjectStore
from test_mcp_narrated import cache_tones, save_plan, source_bytes


@pytest.mark.parametrize('slug', ['/tmp/outside', '../outside', r'..\outside', 'https://example.invalid/track'])
def test_narrated_music_rejects_nonbundled_paths_before_job(tmp_path, slug):
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    saved = ProjectStore(project).load()
    saved['storyboard']['music'] = {'primary': slug}
    ProjectStore(project).save(saved['storyboard'], saved['settings'], saved['revision'])
    before = source_bytes(project)
    with pytest.raises(ValueError, match='bundled track'):
        service.render('demo', mode='cached')
    assert not service.jobs and source_bytes(project) == before


def test_square_cached_project_keeps_landscape_measured_narration(tmp_path):
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    save_plan(project)
    pipeline.set_format(project, aspect='1:1', size=(1080, 1080))
    timeline = cache_tones(project)
    before = source_bytes(project)
    path, cfg, board = service._narrated_project('demo', 'cached')
    assert path == project and cfg['aspect'] == '1:1'
    assert timeline['layout'] == 'landscape'
    assert source_bytes(project) == before


@pytest.mark.parametrize('saved_plan', [False, True])
def test_cached_worker_never_looks_up_saved_provider(tmp_path, monkeypatch, saved_plan):
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    if saved_plan:
        save_plan(project)
    saved = ProjectStore(project).load()
    saved['settings'].update(director='openai', director_v3=True)
    ProjectStore(project).save(saved['storyboard'], saved['settings'], saved['revision'])
    cache_tones(project)
    before = source_bytes(project)
    monkeypatch.setattr(director, 'provider_for', lambda *a, **k: pytest.fail('offline provider lookup'))
    def inspect(stage, *, context):
        cfg = pipeline.settings(stage)
        assert cfg['director'] == 'rules'
        assert cfg['director_v3'] == saved_plan
        assert bool(cfg.get('plan_v3')) == saved_plan
        pipeline.direct_v3(stage) if cfg['director_v3'] else None
        raise ValueError('captured cached renderer dispatch; no fake completion')
    monkeypatch.setattr(pipeline, 'render', inspect)
    (project / 'build/developer').mkdir(parents=True)
    args = Namespace(narrated_child='demo', mode='cached', receipt='demo/build/developer/check.json',
                     progress='demo/build/developer/check-progress.json',
                     cancel_file='demo/build/developer/check.cancel',
                     revision=ProjectStore(project).load()['revision'])
    ensure_models = voice.ensure_models
    with pytest.raises(ValueError, match='captured cached renderer dispatch'):
        mcp_server._narrated_worker(service, args)
    assert voice.ensure_models is ensure_models
    assert source_bytes(project) == before and not list(project.glob('*.mp4'))


@pytest.mark.parametrize('name', ['/tmp/outside.wav', '../outside.wav', r'..\outside.wav'])
def test_recording_cache_clips_cannot_escape_before_launch(tmp_path, name):
    import json
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    saved = ProjectStore(project).load()
    saved['settings']['recording'] = 'recording.wav'
    ProjectStore(project).save(saved['storyboard'], saved['settings'], saved['revision'])
    (project / 'recording.wav').write_bytes(b'confined recording fixture')
    cache = project / 'voice/recording'
    cache.mkdir(parents=True)
    (cache / 'fixture.json').write_text(json.dumps({'clips': [{'wav': name}]}))
    before = source_bytes(project)
    with pytest.raises(ValueError, match='recording clip'):
        service.render('demo', mode='make')
    assert not service.jobs and source_bytes(project) == before


def test_square_preview_keeps_native_aspect(tmp_path):
    from PIL import Image
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    pipeline.set_format(project, aspect='1:1', size=(1080, 1080))
    result = service.preview_png('demo', time=.2)
    with Image.open(result['path']) as image:
        assert image.size == (540, 540)
    assert (result['width'], result['height']) == (540, 540)

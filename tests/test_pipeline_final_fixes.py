import os, sys, json, shutil
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, str(Path.cwd() / 'tests'))
import numpy as np
import pytest
from kinodraw import pipeline, voice, director
from kinodraw.audio import mix
from kinodraw.project_store import ProjectStore, RevisionConflict
from kinodraw.studio import server, integration
from kinodraw.progress import RenderContext, Cancelled
from test_finish_worker import cached_project


def test_source_change_during_narration_refuses_stale_clips(tmp_path, monkeypatch):
    pipeline.new_project('# Tone\n\nThe small idea stays.', tmp_path)
    build = tmp_path / 'build'
    build.mkdir()
    (build / 'narration.wav').write_bytes(b'previous narration')
    (build / 'timeline.json').write_bytes(b'previous timeline')
    monkeypatch.setattr(voice, 'ensure_models', lambda *a, **kw: None)
    monkeypatch.setattr(pipeline.renderer, 'pacing', lambda *a, **kw: {})
    calls = []
    def synth(text, lang, folder, *a, **kw):
        folder.mkdir(exist_ok=True)
        path = folder / f'{len(calls)}.wav'
        mix.write_wav(path, .12 * np.sin(2 * np.pi * 440 * np.arange(voice.SR // 4) / voice.SR), voice.SR)
        calls.append(text)
        if len(calls) == 1:
            saved = ProjectStore(tmp_path).load()
            beat = saved['storyboard']['beats'][-1]
            beat['spoken']['en'] = 'The fresh idea grows.'
            beat['display']['en'] = 'The fresh idea grows.'
            ProjectStore(tmp_path).save(saved['storyboard'], saved['settings'], saved['revision'])
        return voice.Clip(path, .25, np.linspace(0, .2, len(text)).tolist())
    monkeypatch.setattr(voice, 'synthesize', synth)
    with pytest.raises(RevisionConflict):
        pipeline.build_audio(tmp_path, pipeline.narrate(tmp_path))
    assert (build / 'narration.wav').read_bytes() == b'previous narration'
    assert (build / 'timeline.json').read_bytes() == b'previous timeline'


def test_finished_recording_title_names_new_deliverable(cached_project):
    store = ProjectStore(cached_project)
    saved = store.load()
    saved['storyboard']['title']['en'] = 'recording'
    saved['settings']['recording'] = 'recording.mp4'
    source = cached_project / 'recording.mp4'
    shutil.copyfile(cached_project / 'build/silent.mp4', source)
    before = source.read_bytes()
    store.save(saved['storyboard'], saved['settings'], saved['revision'])
    qa = pipeline.finish(cached_project, context=RenderContext())
    assert qa['ok'] and source.read_bytes() == before
    assert Path(qa['video']) != source, 'source recording was reported as finished deliverable'
    assert Path(qa['video']).is_file()


def test_create_cancel_at_asset_transfer_does_not_initialize(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'projects_root', lambda: tmp_path)
    monkeypatch.setattr(server, '_config', lambda: {})
    jobs = []
    monkeypatch.setattr(server.JOBS, 'start', lambda kind, name, fn: jobs.append(fn) or 'test-job')
    monkeypatch.setattr(director, 'direct', lambda *a, **kw: {'notes': []})
    monkeypatch.setattr(integration, 'validate_references', lambda *a: None)
    progress = server.JobContext({})
    transfer = integration.transfer_assets
    def cancel_transfer(source, destination):
        transfer(source, destination)
        progress.cancel()
    monkeypatch.setattr(integration, 'transfer_assets', cancel_transfer)
    response = server.create_project({'text': '# Creation\n\nA small idea.', 'director': 'rules', 'director_v3': False})
    with pytest.raises((Cancelled, server.JobCancelled)):
        jobs[0](progress)
    project = tmp_path / response['project']
    assert not (project / 'storyboard.json').exists()
    assert not (project / 'project.json').exists()


def test_direct_v3_provider_switch_resets_previous_options(tmp_path, monkeypatch):
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path, director_v3=True,
                         director='compat', model='old-model', base_url='http://127.0.0.1:1/v1', command='old-command')
    class Selected(Exception):
        pass
    def inspect(settings):
        assert settings['director'] == 'anthropic'
        assert settings.get('model') is None and settings.get('base_url') is None
        assert settings.get('command') is None
        raise Selected()
    monkeypatch.setattr(director, 'provider_for', inspect)
    with pytest.raises(Selected):
        pipeline.direct_v3(tmp_path, provider='anthropic')


@pytest.mark.parametrize('changed', ['storyboard', 'settings'])
@pytest.mark.parametrize('direct_json', [False, True])
@pytest.mark.parametrize('when', ['during', 'after'])
@pytest.mark.parametrize('entrypoint', ['pipeline', 'cli'])
def test_narration_revision_spans_synthesis_and_assembly(tmp_path, monkeypatch, changed, direct_json, when, entrypoint):
    from kinodraw import cli
    pipeline.new_project('# Tone\n\nThe small idea stays.', tmp_path, credit=False)
    build = tmp_path / 'build'
    build.mkdir()
    previous = {'narration.wav': b'old narration', 'timeline.json': b'old timeline',
                'captions.srt': b'old captions', 'captions.vtt': b'old web captions'}
    for name, data in previous.items():
        (build / name).write_bytes(data)
    monkeypatch.setattr(voice, 'ensure_models', lambda *a, **kw: None)
    monkeypatch.setattr(cli, '_server_settings', lambda *a: None)
    monkeypatch.setattr(pipeline.renderer, 'pacing', lambda *a, **kw: {})
    calls, edits = [], []
    def edit():
        store = ProjectStore(tmp_path)
        saved = store.load()
        ids = [b['id'] for b in saved['storyboard']['beats']]
        if changed == 'storyboard':
            saved['storyboard']['beats'][-1]['spoken']['en'] = 'The fresh idea grows.'
            saved['storyboard']['beats'][-1]['display']['en'] = 'The fresh idea grows.'
        else:
            saved['settings']['speed'] = 1.3
        if direct_json:
            pipeline._save(tmp_path / ('storyboard.json' if changed == 'storyboard' else 'project.json'), saved[changed])
        else:
            store.save(saved['storyboard'], saved['settings'], saved['revision'])
        current = store.load()
        assert current['revision'] != saved['revision']
        assert [b['id'] for b in current['storyboard']['beats']] == ids
        edits.append(current['revision'])
    def synth(text, lang, folder, *a, **kw):
        folder.mkdir(exist_ok=True)
        path = folder / f'{len(calls)}.wav'
        wave = .12 * np.sin(2 * np.pi * 440 * np.arange(voice.SR // 4) / voice.SR)
        assert np.max(np.abs(wave)) > .1
        mix.write_wav(path, wave, voice.SR)
        calls.append(text)
        if when == 'during' and len(calls) == 1:
            edit()
        return voice.Clip(path, .25, np.linspace(0, .2, len(text)).tolist())
    monkeypatch.setattr(voice, 'synthesize', synth)
    narrate = pipeline.narrate
    def narrate_then_edit(*args, **kwargs):
        clips = narrate(*args, **kwargs)
        if when == 'after':
            edit()
        return clips
    monkeypatch.setattr(pipeline, 'narrate', narrate_then_edit)
    with pytest.raises(RevisionConflict):
        if entrypoint == 'cli':
            cli.main(['voice', str(tmp_path)])
        else:
            pipeline.build_audio(tmp_path, pipeline.narrate(tmp_path))
    assert calls and len(edits) == 1
    assert all((build / name).read_bytes() == data for name, data in previous.items())
    assert not list(build.glob('.audio-*')) and not list(tmp_path.glob('.publish-*'))
    print(json.dumps({'flow': entrypoint + '_narration_race', 'when': when,
                      'changed': changed, 'direct_json': direct_json, 'previous_preserved': True}))


def test_unchanged_narration_dict_and_hash(tmp_path, monkeypatch):
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path, credit=False)
    monkeypatch.setattr(voice, 'ensure_models', lambda *a, **kw: None)
    monkeypatch.setattr(pipeline.renderer, 'pacing', lambda *a, **kw: {})
    def synth(text, lang, folder, *a, **kw):
        folder.mkdir(exist_ok=True)
        path = folder / (str(len(list(folder.iterdir()))) + '.wav')
        mix.write_wav(path, .12 * np.sin(2 * np.pi * 440 * np.arange(voice.SR // 4) / voice.SR), voice.SR)
        return voice.Clip(path, .25, np.linspace(0, .2, len(text)).tolist())
    monkeypatch.setattr(voice, 'synthesize', synth)
    clips = pipeline.narrate(tmp_path)
    assert isinstance(clips, dict)
    assert set(clips) == {b['id'] for b in pipeline.storyboard(tmp_path)['beats']}
    tl = pipeline.build_audio(tmp_path, clips)
    assert tl['storyboard_sha256'] == pipeline.sha(tmp_path / 'storyboard.json')
    assert np.max(np.abs(mix.read_wav(tmp_path / 'build/narration.wav')[0])) > .05
    assert (tmp_path / 'build/captions.srt').read_text().strip()


@pytest.mark.parametrize('script_source', ['script.md', 'recording (video).srt'])
def test_collision_deliverable_decode_sidecars_and_manifest(cached_project, script_source):
    import subprocess
    from kinodraw.engine import render
    from kinodraw.progress import encoded_frames
    from kinodraw.project_zip import export_project
    store = ProjectStore(cached_project)
    saved = store.load()
    saved['storyboard']['title']['en'] = 'recording'
    saved['settings'].update(recording='recording.mp4', script=script_source)
    source = cached_project / 'recording.mp4'
    shutil.copyfile(cached_project / 'build/silent.mp4', source)
    script_path = cached_project / script_source
    script_path.write_text('retained script source')
    previous = {p: p.read_bytes() for p in (source, script_path)}
    store.save(saved['storyboard'], saved['settings'], saved['revision'])
    context = RenderContext()
    qa = pipeline.finish(cached_project, context=context)
    video = Path(qa['video'])
    assert qa['ok'] and video.is_file() and video != source
    assert all(p.read_bytes() == data for p, data in previous.items())
    assert pipeline._load(cached_project / 'build/qa.json')['video'] == str(video)
    progress = cached_project.parent / 'finished.decode'
    decoded = subprocess.run([render.FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode',
                              '-i', str(video), '-map', '0:v:0', '-map', '0:a:0', '-vsync', '0',
                              '-progress', str(progress), '-f', 'null', '-'], capture_output=True, timeout=20)
    assert decoded.returncode == 0 and not decoded.stderr, decoded.stderr
    assert encoded_frames(progress) == qa['frames'] > 0
    names = {video.stem + suffix for suffix in ('.mp4', '.srt', '.vtt', '-chapters.txt',
                                               '-transcript.md', '-description.txt', '-thumbnail.png')}
    assert all((cached_project / name).is_file() for name in names)
    assert '-->' in video.with_suffix('.srt').read_text()
    assert video.with_suffix('.vtt').read_text().startswith('WEBVTT')
    manifest = export_project(cached_project, cached_project.parent / 'finished.zip')
    assert names <= set(manifest['files'])
    assert manifest['files'][video.name]['sha256'] == pipeline.sha(video)
    assert not context.token.owned_pids
    print(json.dumps({'flow': 'finish_collision', 'source': source.name, 'deliverable': video.name,
                      'script': script_source, 'decode_exit': decoded.returncode,
                      'decoded_frames': encoded_frames(progress), 'manifest_files': sorted(names)}))


@pytest.mark.parametrize('cancel_at', ['validation', None, 'after_commit'])
def test_create_final_commit_cancellation_and_completion(tmp_path, monkeypatch, cancel_at):
    monkeypatch.setattr(server, 'projects_root', lambda: tmp_path)
    monkeypatch.setattr(server, '_config', lambda: {})
    jobs = []
    monkeypatch.setattr(server.JOBS, 'start', lambda kind, name, fn: jobs.append(fn) or 'test-job')
    monkeypatch.setattr(director, 'direct', lambda *a, **kw: {'notes': []})
    context = server.JobContext({})
    checks, commits = [], []
    def validate(board, cfg, path):
        checks.append(path)
        if len(checks) == 2 and cancel_at == 'validation':
            context.cancel()
    monkeypatch.setattr(integration, 'validate_references', validate)
    initialize = ProjectStore.initialize
    def initialize_locked(store, board, cfg):
        if store.path == tmp_path / 'Creation':
            assert context.token._lock._is_owned()
            commits.append(store.path)
            result = initialize(store, board, cfg)
            if cancel_at == 'after_commit':
                context.cancel()
            return result
        return initialize(store, board, cfg)
    monkeypatch.setattr(ProjectStore, 'initialize', initialize_locked)
    response = server.create_project({'text': '# Creation\n\nA small idea.', 'director': 'rules', 'director_v3': False})
    project = tmp_path / response['project']
    if cancel_at == 'validation':
        with pytest.raises((Cancelled, server.JobCancelled)):
            jobs[0](context)
        assert not commits and not getattr(context.render_context, 'published', False)
        assert not (project / 'storyboard.json').exists() and not (project / 'project.json').exists()
    else:
        result = jobs[0](context)
        assert result['project'] == response['project']
        assert commits == [project]
        assert context.render_context.published
        assert ProjectStore(project).load()['storyboard']['title']['en'] == 'Creation'


@pytest.mark.parametrize('provider', [None, 'compat', 'object'])
def test_direct_v3_same_provider_options_and_objects_preserved(tmp_path, monkeypatch, provider):
    from kinodraw.director.v3 import llm
    options = {'model': 'saved-model', 'base_url': 'http://127.0.0.1:1/v1', 'command': 'saved-command'}
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path, director_v3=True, director='compat', **options)
    selected = object()
    class Selected(Exception):
        pass
    def inspect(cfg):
        assert cfg['director'] == 'compat' and cfg['model'] == options['model']
        # Saved endpoints and commands are never provider inputs (tests/test_project_provider_trust.py).
        assert not cfg.keys() & {'base_url', 'command'}
        assert provider != 'object'
        return selected
    def plan(board, provider=None):
        assert provider is selected
        raise Selected()
    monkeypatch.setattr(director, 'provider_for', inspect)
    monkeypatch.setattr(llm, 'plan_v3', plan)
    with pytest.raises(Selected):
        pipeline.direct_v3(tmp_path, provider=selected if provider == 'object' else provider)

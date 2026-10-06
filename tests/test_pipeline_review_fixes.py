import copy
from pathlib import Path
import pytest
from kinodraw import pipeline, director
from kinodraw.project_store import ProjectStore, RevisionConflict
from kinodraw.progress import RenderContext, Cancelled
from kinodraw.studio import server, integration


def test_publication_does_not_restore_recording_source(tmp_path):
    live, stage = tmp_path / 'live', tmp_path / 'stage'
    pipeline.new_project('# Tone\n\nA small idea.', live, recording='recording.mp4')
    pipeline.new_project('# Tone\n\nA small idea.', stage, recording='recording.mp4')
    (stage / 'recording.mp4').write_bytes(b'original recording')
    (live / 'recording.mp4').write_bytes(b'replacement recording')
    before = ProjectStore(live).load()['revision']
    pipeline.set_recording(live, live / 'recording.mp4')
    assert ProjectStore(live).load()['revision'] == before
    pipeline._commit_outputs(stage, live, RenderContext())
    assert (live / 'recording.mp4').read_bytes() == b'replacement recording'


def test_script_title_deliverables_are_published(tmp_path):
    live, stage = tmp_path / 'live', tmp_path / 'stage'
    pipeline.new_project('# script\n\nA small idea.', live)
    pipeline.new_project('# script\n\nA small idea.', stage)
    before = (live / 'script.md').read_bytes()
    for extension in ('.mp4', '.srt', '.vtt'):
        (stage / ('script' + extension)).write_bytes(b'finished' + extension.encode())
    pipeline._commit_outputs(stage, live, RenderContext())
    for extension in ('.mp4', '.srt', '.vtt'):
        assert (live / ('script' + extension)).read_bytes() == b'finished' + extension.encode()
    assert (live / 'script.md').read_bytes() == before


def test_audio_rejects_intervening_source_edit(tmp_path, monkeypatch):
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path)
    build = tmp_path / 'build'
    build.mkdir()
    (build / 'narration.wav').write_bytes(b'previous narration')
    (build / 'timeline.json').write_bytes(b'previous timeline')
    monkeypatch.setattr(pipeline.renderer, 'pacing', lambda *a, **kw: {})
    def assemble(board, lang, clips, stage, *args, **kwargs):
        store = ProjectStore(tmp_path)
        state = store.load()
        state['storyboard']['title']['en'] = 'New manual title'
        store.save(state['storyboard'], state['settings'], state['revision'])
        (stage / 'narration.wav').write_bytes(b'old source narration')
        return {'duration': 1., 'captions': []}
    monkeypatch.setattr(pipeline.audio, 'assemble', assemble)
    with pytest.raises(RevisionConflict):
        pipeline.build_audio(tmp_path, {})
    assert (build / 'narration.wav').read_bytes() == b'previous narration'
    assert (build / 'timeline.json').read_bytes() == b'previous timeline'


def test_replan_cancelled_after_asset_transfer_preserves_source(tmp_path, monkeypatch):
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path, director_v3=True)
    monkeypatch.setattr(server, '_project', lambda name: tmp_path)
    store = ProjectStore(tmp_path)
    original = store.load()
    jobs = []
    monkeypatch.setattr(server.JOBS, 'start', lambda kind, name, fn: jobs.append(fn) or 'test-job')
    monkeypatch.setitem(server.STUDIO_HOOKS, 'provider', lambda body: 'rules')
    monkeypatch.setattr(integration, 'validate_references', lambda *a: None)
    def plan(path, **kw):
        local = ProjectStore(path)
        state = local.load()
        state['storyboard']['title']['en'] = 'New planned title'
        local.save(state['storyboard'], state['settings'], state['revision'])
        return {'notes': []}
    monkeypatch.setattr(pipeline, 'direct_v3', plan)
    progress = server.JobContext({})
    real = integration.transfer_assets
    def transfer(source, destination):
        real(source, destination)
        if Path(destination) == tmp_path:
            progress.cancel()
    monkeypatch.setattr(integration, 'transfer_assets', transfer)
    server.redirect('p', {'revision': original['revision'], 'director': 'rules'})
    with pytest.raises((Cancelled, server.JobCancelled)):
        jobs[0](progress)
    assert store.load()['storyboard'] == original['storyboard']
    assert store.load()['settings'] == original['settings']


def test_provider_switch_clears_incompatible_model_and_base(tmp_path, monkeypatch):
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path, director_v3=True,
                         director='compat', model='compat-only-model', base_url='http://127.0.0.1:1/v1')
    monkeypatch.setattr(server, '_project', lambda name: tmp_path)
    original = ProjectStore(tmp_path).load()
    jobs, requests = [], []
    monkeypatch.setattr(server.JOBS, 'start', lambda kind, name, fn: jobs.append(fn) or 'test-job')
    def selected(body):
        requests.append(copy.deepcopy(body))
        return 'rules'
    monkeypatch.setitem(server.STUDIO_HOOKS, 'provider', selected)
    monkeypatch.setattr(integration, 'validate_references', lambda *a: None)
    monkeypatch.setattr(pipeline, 'direct_v3', lambda *a, **kw: {'notes': []})
    server.redirect('p', {'revision': original['revision'], 'director': 'anthropic'})
    jobs[0](server.JobContext({}))
    assert requests and requests[0].get('model') is None and requests[0].get('base_url') is None


def test_explicit_legacy_replan_replaces_untouched_generated_visuals(tmp_path, monkeypatch):
    from kinodraw.director import match, rules
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path)
    old = {'id': 'generated-old', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'book_stack'}]}
    new = {'id': 'generated-new', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'smartphone'}]}
    monkeypatch.setattr(match, 'ensure_model', lambda *a: None)
    monkeypatch.setattr(rules.RulesDirector, '__init__', lambda self, lang: None)
    # Establish actual generated ownership rather than labeling a manual save.
    monkeypatch.setattr(rules.RulesDirector, 'direct',
                        lambda self, board: board['beats'][0].update(visuals=[old]))
    director.direct(tmp_path)
    assert pipeline.storyboard(tmp_path)['beats'][0]['visuals'] == [old]
    def draw(self, board):
        board['beats'][0]['visuals'] = [new]
        return board
    monkeypatch.setattr(rules.RulesDirector, 'direct', draw)
    director.direct(tmp_path)
    assert pipeline.storyboard(tmp_path)['beats'][0]['visuals'] == [new]


@pytest.mark.parametrize('replacement', ['manual', 'local', 'empty'])
def test_cli_legacy_replan_replaces_generated_and_preserves_edits(tmp_path, monkeypatch, replacement):
    from kinodraw import cli
    from kinodraw.director import match, rules
    from PIL import Image
    monkeypatch.setattr(cli, '_server_settings', lambda *a: None)
    monkeypatch.setattr(match, 'ensure_model', lambda *a: None)
    monkeypatch.setattr(rules.RulesDirector, '__init__', lambda self, lang: None)
    old = {'id': 'old', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'book_stack'}]}
    new = {'id': 'new', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'smartphone'}]}
    old_second = {**old, 'id': 'old-second'}
    chosen = [old]
    def draw(self, board):
        board['beats'][0]['visuals'] = copy.deepcopy(chosen)
        board['beats'][1]['visuals'] = [{**copy.deepcopy(chosen[0]), 'id': chosen[0]['id'] + '-second'}]
    monkeypatch.setattr(rules.RulesDirector, 'direct', draw)
    cli.main(['new', '# Tone\n\nA small idea.', '-o', str(tmp_path)])
    original = ProjectStore(tmp_path).load()
    assert original['storyboard']['beats'][0]['visuals'] == [old]
    assert original['storyboard']['beats'][1]['visuals'] == [old_second]
    assert original['settings']['generated_visuals']
    manual = {'id': 'edit', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'lightbulb_idea'}]}
    if replacement == 'local':
        (tmp_path / 'pictures').mkdir()
        Image.new('RGB', (20, 20), (80, 90, 100)).save(tmp_path / 'pictures/manual.png')
        manual['items'][0]['doodle'] = 'own:manual.png'
    edited = [] if replacement == 'empty' else [manual]
    original['storyboard']['beats'][1]['visuals'] = edited
    ProjectStore(tmp_path).save(original['storyboard'], original['settings'], original['revision'])
    chosen[:] = [new]
    for _ in range(2):
        cli.main(['direct', str(tmp_path)])
        current = ProjectStore(tmp_path).load()
        assert current['storyboard']['beats'][0]['visuals'] == [new]
        assert current['storyboard']['beats'][1]['visuals'] == edited
    if replacement == 'local':
        assert (tmp_path / 'pictures/manual.png').is_file()


def test_publication_only_copies_generated_root_artifacts(tmp_path):
    live, stage = tmp_path / 'live', tmp_path / 'stage'
    pipeline.new_project('# Tone\n\nA small idea.', live)
    pipeline.new_project('# Tone\n\nA small idea.', stage)
    for name in ('reference.mp4', 'notes.txt', 'art.png', 'other.json', 'essay.md'):
        (stage / name).write_bytes(b'stale source')
        (live / name).write_bytes(b'current source')
    (stage / 'script.md').write_bytes(b'stale scratch script')
    source = (live / 'script.md').read_bytes()
    for suffix in ('.mp4', '.srt', '.vtt', '-chapters.txt', '-transcript.md', '-description.txt', '-thumbnail.png'):
        (stage / ('Tone' + suffix)).write_bytes(b'generated')
    pipeline._commit_outputs(stage, live, RenderContext())
    assert (live / 'script.md').read_bytes() == source
    for name in ('reference.mp4', 'notes.txt', 'art.png', 'other.json', 'essay.md'):
        assert (live / name).read_bytes() == b'current source'
    for suffix in ('.mp4', '.srt', '.vtt', '-chapters.txt', '-transcript.md', '-description.txt', '-thumbnail.png'):
        assert (live / ('Tone' + suffix)).read_bytes() == b'generated'


@pytest.mark.parametrize('kind, overrides', [
    ('anthropic', {}), ('command', {'command': 'new-command', 'model': 'new-model'}),
    ('compat', {'model': 'explicit-model', 'base_url': 'http://127.0.0.1:1/v1'}),
])
def test_provider_settings_switch_and_same_provider(kind, overrides):
    previous = {'director': 'compat', 'model': 'old-model', 'base_url': 'old-base',
                'command': 'old-command', 'voice': 'saved-voice'}
    switched = director.provider_settings(previous, kind, **overrides)
    assert switched['voice'] == 'saved-voice'
    assert switched['director'] == kind
    for key in ('model', 'base_url', 'command'):
        expected = overrides.get(key) if kind != 'compat' else overrides.get(key, previous[key])
        assert switched.get(key) == expected
    assert previous['model'] == 'old-model'
    assert director.provider_settings(previous, 'compat') == previous


@pytest.mark.parametrize('changed', ['storyboard', 'settings'])
@pytest.mark.parametrize('entrypoint', ['pipeline', 'cli'])
def test_audio_pair_race_preserves_every_old_output_and_hash(tmp_path, monkeypatch, changed, entrypoint):
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path)
    build = tmp_path / 'build'
    build.mkdir()
    previous = {'narration.wav': b'old narration', 'captions.srt': b'old captions',
                'timeline.json': b'{"storyboard_sha256": "old hash"}'}
    for name, content in previous.items():
        (build / name).write_bytes(content)
    monkeypatch.setattr(pipeline.renderer, 'pacing', lambda *a, **kw: {})
    def assemble(board, lang, clips, stage, *args, **kwargs):
        state = ProjectStore(tmp_path).load()
        if changed == 'storyboard':
            state['storyboard']['title']['en'] = 'New source'
        else:
            state['settings']['speed'] = 1.5
        ProjectStore(tmp_path).save(state['storyboard'], state['settings'], state['revision'])
        for name in previous:
            if name != 'timeline.json':
                (stage / name).write_bytes(b'new staged bytes')
        return {'duration': 1., 'captions': []}
    monkeypatch.setattr(pipeline.audio, 'assemble', assemble)
    with pytest.raises(RevisionConflict):
        if entrypoint == 'cli':
            from kinodraw import cli
            monkeypatch.setattr(cli, '_server_settings', lambda *a: None)
            monkeypatch.setattr(pipeline, 'narrate', lambda *a, **kw: {})
            cli.main(['voice', str(tmp_path)])
        else:
            pipeline.build_audio(tmp_path, {})
    for name, content in previous.items():
        assert (build / name).read_bytes() == content
    assert not list(build.glob('.audio-*'))
    assert not list(tmp_path.glob('.publish-*'))


# Uses the existing loopback fixture and real routes; blocked in this sandbox.
from test_studio_integration import http_studio, wait_job


def test_http_legacy_generated_replan_and_manual_visual_preservation(http_studio, monkeypatch):
    from kinodraw.director import match, rules
    http = http_studio
    monkeypatch.setattr(match, 'ensure_model', lambda *a: None)
    old = {'id': 'old', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'book_stack'}]}
    new = {'id': 'new', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'smartphone'}]}
    old_second = {**old, 'id': 'old-second'}
    chosen = [old]
    def draw(self, board):
        board['beats'][0]['visuals'] = copy.deepcopy(chosen)
        board['beats'][1]['visuals'] = [{**copy.deepcopy(chosen[0]), 'id': chosen[0]['id'] + '-second'}]
    monkeypatch.setattr(rules.RulesDirector, 'direct', draw)
    code, made = http('/api/projects', {'text': '# Tone\n\nA small idea.', 'director': 'rules', 'director_v3': False})
    assert code == 200
    assert wait_job(http, made['job'])['state'] == 'done'
    route = '/api/projects/' + made['project']
    state = http(route)[1]
    assert state['storyboard']['beats'][0]['visuals'] == [old]
    assert state['storyboard']['beats'][1]['visuals'] == [old_second]
    manual = {'id': 'manual', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'lightbulb_idea'}]}
    state['storyboard']['beats'][1]['visuals'] = [manual]
    code, state = http(route + '/storyboard', {'revision': state['revision'], 'storyboard': state['storyboard']}, 'PUT')
    assert code == 200
    chosen[:] = [new]
    code, replanned = http(route + '/direct', {'revision': state['revision'], 'director': 'rules'})
    assert code == 200
    result = wait_job(http, replanned['job'])
    assert result['state'] == 'done', result
    current = http(route)[1]
    assert current['storyboard']['beats'][0]['visuals'] == [new]
    assert current['storyboard']['beats'][1]['visuals'] == [manual]


from test_finish_worker import cached_project


def test_actual_script_title_finish_publishes_video_and_both_captions(cached_project):
    import json
    import subprocess
    from kinodraw.engine import render
    store = ProjectStore(cached_project)
    state = store.load()
    state['storyboard']['title']['en'] = 'script'
    store.save(state['storyboard'], state['settings'], state['revision'])
    source = (cached_project / state['settings']['script']).read_bytes()
    context = RenderContext()
    qa = pipeline.finish(cached_project, context=context)
    assert qa['ok'] and context.published and not context.token.owned_pids
    assert Path(qa['video']).name == 'script.mp4'
    for suffix in ('.mp4', '.srt', '.vtt'):
        assert (cached_project / ('script' + suffix)).stat().st_size > 0
    assert '-->' in (cached_project / 'script.srt').read_text(encoding='utf-8')
    assert (cached_project / 'script.vtt').read_text(encoding='utf-8').startswith('WEBVTT')
    assert (cached_project / state['settings']['script']).read_bytes() == source
    decoded = subprocess.run([render.FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode',
                              '-i', str(cached_project / 'script.mp4'), '-f', 'null', '-'],
                             capture_output=True, timeout=20)
    assert decoded.returncode == 0, decoded.stderr
    print(json.dumps({'flow': 'script_title_finish', 'qa_ok': qa['ok'], 'decode_exit': decoded.returncode,
                      'source_unchanged': True, 'deliverables': ['script.mp4', 'script.srt', 'script.vtt']}))


@pytest.mark.parametrize('source_name', ['Tone.mp4', 'build/source.mp4'])
def test_configured_recording_is_excluded_even_in_generated_output_slots(tmp_path, source_name):
    live, stage = tmp_path / 'live', tmp_path / 'stage'
    pipeline.new_project('# Tone\n\nA small idea.', live, recording=source_name)
    pipeline.new_project('# Tone\n\nA small idea.', stage, recording=source_name)
    for root, content in ((stage, b'old recording'), (live, b'current recording')):
        source = root / source_name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
    (stage / 'Tone.srt').write_bytes(b'generated captions')
    pipeline._commit_outputs(stage, live, RenderContext())
    assert (live / source_name).read_bytes() == b'current recording'
    assert (live / 'Tone.srt').read_bytes() == b'generated captions'

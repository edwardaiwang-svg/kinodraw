"""Offline narrated MCP acceptance; tones are a labeled synthetic fixture, not speech."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pytest

from kinodraw import mcp_server, pipeline, voice
from kinodraw.audio import mix
from kinodraw.director.v3.rules import from_rules
from kinodraw.project_store import ProjectStore
from test_mcp_server import Client

EVIDENCE = Path(__file__).resolve().parents[1] / 'docs/overnight-2026-10-05/evidence/sol-mcp-narrated'
MODELS = voice.MODEL_DIR


@pytest.fixture(autouse=True)
def offline_children(tmp_path, monkeypatch):
    """Every Python child fails on network, secret access or app migration."""
    guard = tmp_path / 'offline-guard'
    guard.mkdir()
    audit = guard / 'denied.txt'
    (guard / 'sitecustomize.py').write_text('''
import socket
from pathlib import Path
import keyring
from keyring.backends.null import Keyring
def denied(*args, **kwargs):
    Path(__file__).with_name('denied.txt').write_text('forbidden offline operation')
    raise RuntimeError('OFFLINE_ACCEPTANCE_BLOCK: network, keyring or migration')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
class MemoryOnly(Keyring):
    get_password = denied
    set_password = denied
    delete_password = denied
keyring.set_keyring(MemoryOnly())
keyring.get_password = denied
from kinodraw import paths
paths.migrate = denied
from kinodraw import director, voice
director.provider_for = denied
if __import__('os').environ.get('KINODRAW_ACCEPTANCE_TTS') != '1':
    voice.synthesize = denied
    voice._engine = denied
''')
    monkeypatch.setenv('PYTHONPATH', str(guard) + os.pathsep + str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv('PYTHON_KEYRING_BACKEND', 'keyring.backends.null.Keyring')
    yield
    assert not audit.exists(), audit.read_text() if audit.exists() else ''


def save_plan(project):
    store = ProjectStore(project)
    saved = store.load()
    plan = from_rules(saved['storyboard'])
    plan['style'].update(mode='hybrid', music_mood='none', motion_floor='lively')
    for scene in plan['scenes']:
        scene['treatment'] = 'kinetic_type'
        scene['camera'] = 'slow_push'
        scene['atmosphere'] = {'kind': 'rain', 'density': 1.0}
    saved['settings'].update(credit=False, workers=1, director_v3=True,
                             plan_v3=plan, scene_treatments=plan['scenes'])
    store.save(saved['storyboard'], saved['settings'], saved['revision'])


def cache_tones(project):
    clips = {}
    board = pipeline.storyboard(project)
    for index, beat in enumerate(board['beats']):
        t = np.arange(int(.55 * voice.SR), dtype=np.float32) / voice.SR
        wav = project / 'voice' / f'fixture-{index}.wav'
        wav.parent.mkdir(exist_ok=True)
        mix.write_wav(wav, .16 * np.sin(2 * np.pi * (330 + index * 20) * t), voice.SR)
        clips[beat['id']] = voice.Clip(wav, .55, np.linspace(0, .55, len(beat['spoken']['en'])).tolist())
    return pipeline.build_audio(project, clips)


def source_bytes(project):
    cfg = pipeline.settings(project)
    names = ['project.json', 'storyboard.json', cfg['script']]
    if cfg.get('recording'):
        names.append(cfg['recording'])
    return {name: (project / name).read_bytes() for name in names}


def test_render_advertises_opt_in_modes_without_new_tools():
    assert {t['name'] for t in mcp_server.TOOLS} == {
        'create_project', 'validate_project', 'chart_add', 'preview_png', 'render', 'status', 'cancel',
        'list_projects', 'get_project', 'list_voices', 'export_video'}
    render = next(t for t in mcp_server.TOOLS if t['name'] == 'render')
    assert render['inputSchema']['properties']['mode']['enum'] == ['synthetic', 'make', 'cached']
    assert 'Kokoro' in render['description'] and 'cost' in render['description']


def test_missing_models_refused_before_job_creation(tmp_path, monkeypatch):
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nThis is fictional.', lang='en')
    monkeypatch.setattr(voice, 'MODEL_DIR', tmp_path / 'absent-models')
    monkeypatch.setattr(voice, 'download', lambda *a, **k: pytest.fail('implicit download'))
    with pytest.raises(ValueError, match='cached.*model|model.*cached'):
        service.render('demo', mode='make')
    assert not service.jobs and not (tmp_path / 'demo/build/developer').exists()


@pytest.mark.parametrize('key,value', [('script', '../outside.md'), ('recording', '/tmp/outside.wav'),
                                     ('voice_file', '../outside.bin'), ('config', 'https://example.invalid/config'),
                                     ('voice', 'https://example.invalid/voice'), ('command', 'echo unsafe'),
                                     ('voice_server', {'url': 'http://127.0.0.1:1'}), ('key', 'fixture-not-a-secret')])
def test_narrated_indirect_references_refused_before_launch(tmp_path, key, value):
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nThis is fictional.', lang='en')
    store = ProjectStore(tmp_path / 'demo')
    saved = store.load()
    saved['settings'][key] = value
    store.save(saved['storyboard'], saved['settings'], saved['revision'])
    with pytest.raises(ValueError):
        service.render('demo', mode='make')
    assert not service.jobs


def test_frozen_worker_command_has_explicit_dispatch(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    command = mcp_server._worker_command(tmp_path, ['--render-child', 'demo'])
    assert command == [sys.executable, '--mcp-worker', '--root', str(tmp_path), '--render-child', 'demo']
    launch = Path(__file__).resolve().parents[1] / 'packaging/launch.py'
    assert "'--mcp-worker'" in launch.read_text() and "'--finish-worker'" in launch.read_text()


def test_actual_python_launcher_mcp_worker_dispatch(tmp_path):
    launch = Path(__file__).resolve().parents[1] / 'packaging/launch.py'
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'protocolVersion': '2024-11-05'}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
    child = subprocess.Popen([sys.executable, str(launch), '--mcp-worker', '--root', str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        output, errors = child.communicate(('\n'.join(json.dumps(m) for m in messages) + '\n').encode(), timeout=15)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
    assert child.returncode == 0, errors
    replies = [json.loads(line) for line in output.splitlines()]
    assert replies[-1]['id'] == 2 and len(replies[-1]['result']['tools']) == 11


def test_skeleton_default_does_not_call_voice_or_provider(tmp_path, monkeypatch):
    from kinodraw import director
    monkeypatch.setattr(pipeline, 'narrate', lambda *a, **k: pytest.fail('skeleton narration'))
    monkeypatch.setattr(director, 'provider_for', lambda *a, **k: pytest.fail('skeleton provider'))
    service = mcp_server.Developer(tmp_path)
    made = service.create_project('demo', script='# Example\n\nThis is fictional.', lang='en')
    assert made['director'] == 'rules'
    assert not (tmp_path / 'demo/voice').exists()


@pytest.mark.parametrize('saved_plan', [False, True])
def test_make_dispatches_shared_produce_with_rules_or_saved_plan(tmp_path, monkeypatch, saved_plan):
    from argparse import Namespace
    from kinodraw import director
    from kinodraw.progress import RenderContext
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    if saved_plan:
        save_plan(project)
        store = ProjectStore(project)
        state = store.load()
        state['settings']['director_v3'] = False
        store.save(state['storyboard'], state['settings'], state['revision'])
    before = source_bytes(project)
    original_plan = pipeline.settings(project).get('plan_v3')
    monkeypatch.setattr(director, 'provider_for', lambda *a, **k: pytest.fail('provider lookup'))
    def inspect(stage, progress=None, context=None):
        cfg = pipeline.settings(stage)
        assert cfg['director_v3'] and cfg['plan_v3']
        assert isinstance(context, RenderContext) and callable(progress.check_cancelled)
        if saved_plan:
            assert cfg['plan_v3'] == original_plan
        else:
            assert cfg['director'] == 'rules'
        raise ValueError('captured shared pipeline dispatch; no fake completion')
    monkeypatch.setattr(pipeline, 'produce', inspect)
    (project / 'build/developer').mkdir(parents=True)
    state = ProjectStore(project).load()
    args = Namespace(narrated_child='demo', mode='make', receipt='demo/build/developer/dispatch.json',
                     progress='demo/build/developer/dispatch-progress.json',
                     cancel_file='demo/build/developer/dispatch.cancel', revision=state['revision'])
    with pytest.raises(ValueError, match='captured shared pipeline'):
        mcp_server._narrated_worker(service, args)
    assert source_bytes(project) == before and not list(project.glob('*.mp4'))


def test_real_stdio_cached_full_movie_and_owned_cancellation(tmp_path):
    client = Client(tmp_path)
    progress = []
    try:
        client.initialize()
        client.call('create_project', project='demo', script='# Example\n\nA fictional idea moves.', lang='en')
        project = tmp_path / 'demo'
        save_plan(project)
        # Both an MP4 source slot and a caption source slot collide with the title.
        store = ProjectStore(project)
        saved = store.load()
        (project / 'Example.mp4').write_bytes(b'synthetic recording source; cached mode never opens it')
        (project / 'Example (video).srt').write_bytes((project / 'script.md').read_bytes())
        saved['settings'].update(recording='Example.mp4', script='Example (video).srt')
        store.save(saved['storyboard'], saved['settings'], saved['revision'])
        tl = cache_tones(project)
        assert 6 <= tl['duration'] <= 10
        before = source_bytes(project)
        cached_before = {name: (project / 'build' / name).read_bytes() for name in ('timeline.json', 'narration.wav')}
        job = client.call('render', project='demo', mode='cached')
        assert 'job' in job, job
        deadline = time.monotonic() + 120
        while True:
            state = client.call('status', job=job['job'])
            progress.append(state)
            if state['state'] != 'running':
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert state['state'] == 'succeeded' and state['exit_code'] == 0, state
        assert state['synthetic_timing'] is False
        assert state['validation']['frames'] == round(tl['duration'] * 30)
        assert state['validation']['audio_peak'] > .001 and state['validation']['decode_exit'] == 0
        assert source_bytes(project) == before
        assert all((project / 'build' / name).read_bytes() == content for name, content in cached_before.items())
        assert any(s.get('progress', {}).get('frames', 0) > 0 for s in progress)
        assert any((s.get('progress', {}).get('eta') or 0) > 0 for s in progress)
        assert Path(state['path']).is_file()
        assert Path(state['path']).name == 'Example (video 2).mp4'
        assert json.loads((project / 'build/qa.json').read_text())['video'] == state['path']
        assert len(state['sidecars']) >= 6 and all(Path(p).is_file() for p in state['sidecars'])
        movie = Path(state['path']).read_bytes()
        second = client.call('render', project='demo', mode='cached')
        while True:
            current = client.call('status', job=second['job'])
            assert current['state'] == 'running', current
            if current.get('progress', {}).get('frames', 0) > 0:
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        cancelled = client.call('cancel', job=second['job'])
        assert cancelled['state'] == 'cancelled' and cancelled['exit_code'] is not None
        assert Path(state['path']).read_bytes() == movie
        assert client.call('status', job='not-owned')['isError']
        assert client.call('cancel', job='not-owned')['isError']
        assert not list(project.rglob('*.partial.mp4'))
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / 'cached-flow.json').write_text(json.dumps({'fixture': 'synthetic tone clips; not real user narration',
            'utc': datetime.now(timezone.utc).isoformat(),
            'offline_guard': 'network, keyring, migration, provider and TTS blocked; no attempted calls',
            'progress': progress, 'cancel': cancelled, 'source_unchanged': True,
            'video_sha256': hashlib.sha256(movie).hexdigest()}, indent=2))
    finally:
        client.close()
        if (EVIDENCE / 'cached-flow.json').exists():
            data = json.loads((EVIDENCE / 'cached-flow.json').read_text())
            data['stdio_server_exit'] = client.proc.returncode
            (EVIDENCE / 'cached-flow.json').write_text(json.dumps(data, indent=2))


def test_real_stdio_local_kokoro_make(tmp_path, monkeypatch):
    monkeypatch.setenv('KINODRAW_MODELS', str(MODELS))
    monkeypatch.setenv('KINODRAW_ACCEPTANCE_TTS', '1')
    monkeypatch.setenv('PYTHON_KEYRING_BACKEND', 'keyring.backends.null.Keyring')
    assert (MODELS / 'kokoro-v1.0.fp16.onnx').stat().st_size == 163527961
    assert (MODELS / 'voices-v1.0.bin').stat().st_size == 28214398
    client = Client(tmp_path)
    progress = []
    try:
        client.initialize()
        client.call('create_project', project='spoken', script='# Idea\n\nA fictional idea moves.', lang='en')
        project = tmp_path / 'spoken'
        save_plan(project)
        job = client.call('render', project='spoken', mode='make')
        assert 'job' in job, job
        deadline = time.monotonic() + 150
        while True:
            state = client.call('status', job=job['job'])
            progress.append(state)
            if state['state'] != 'running':
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert state['state'] == 'succeeded' and state['exit_code'] == 0, state
        assert state['synthetic_timing'] is False and state['validation']['audio_peak'] > .001
        assert any((s.get('progress', {}).get('eta') or 0) > 0 for s in progress)
        assert json.loads((project / 'build/qa.json').read_text())['video'] == state['path']
        assert list((project / 'voice').glob('*.wav'))
        meta = [json.loads(p.read_text()) for p in (project / 'voice').glob('*.json')]
        assert any(m.get('voice') == 'af_heart' and m.get('char_times') for m in meta)
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / 'kokoro-flow.json').write_text(json.dumps({'fixture': 'fictional script; actual local Kokoro speech',
                                                            'utc': datetime.now(timezone.utc).isoformat(),
                                                            'offline_guard': 'network, keyring, migration and provider blocked; no attempted calls',
                                                            'progress': progress, 'voice_metadata': meta}, indent=2))
    finally:
        client.close()
        if (EVIDENCE / 'kokoro-flow.json').exists():
            data = json.loads((EVIDENCE / 'kokoro-flow.json').read_text())
            data['stdio_server_exit'] = client.proc.returncode
            (EVIDENCE / 'kokoro-flow.json').write_text(json.dumps(data, indent=2))


def test_stale_timeline_and_silent_cache_refused_before_launch(tmp_path):
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    save_plan(project)
    tl = cache_tones(project)
    wav = project / 'build/narration.wav'
    raw = wav.read_bytes()
    mix.write_wav(wav, np.zeros(round(tl['duration'] * mix.SR)), mix.SR)
    with pytest.raises(ValueError, match='nonzero'):
        service.render('demo', mode='cached')
    wav.write_bytes(raw)
    store = ProjectStore(project)
    saved = store.load()
    saved['storyboard']['title']['en'] = 'Changed source'
    store.save(saved['storyboard'], saved['settings'], saved['revision'])
    with pytest.raises(ValueError, match='storyboard'):
        service.render('demo', mode='cached')
    assert not service.jobs


def test_real_revision_change_during_encode_preserves_movie(tmp_path):
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Example\n\nA fictional idea moves.', lang='en')
    project = tmp_path / 'demo'
    save_plan(project)
    cache_tones(project)
    previous = project / 'Example.mp4'
    previous.write_bytes(b'previous-good-movie-fixture')
    job = service.render('demo', mode='cached')
    deadline = time.monotonic() + 90
    try:
        while True:
            state = service.status(job['job'])
            assert state['state'] == 'running', state
            if state.get('progress', {}).get('frames', 0) > 0:
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        store = ProjectStore(project)
        saved = store.load()
        saved['settings']['speed'] = 1.1
        store.save(saved['storyboard'], saved['settings'], saved['revision'])
        while state['state'] == 'running':
            assert time.monotonic() < deadline
            time.sleep(.1)
            state = service.status(job['job'])
        assert state['state'] == 'failed' and state['exit_code'] == 1, state
        assert previous.read_bytes() == b'previous-good-movie-fixture'
        assert 'changed elsewhere' in Path(state['diagnostics']).read_text()
        assert not list(project.rglob('*.partial.mp4'))
        (EVIDENCE / 'revision-conflict.json').write_text(json.dumps({'utc': datetime.now(timezone.utc).isoformat(),
            'status': state, 'previous_movie_preserved': True}, indent=2))
    finally:
        service.close()

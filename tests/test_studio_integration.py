from kinodraw.studio import server
from kinodraw.progress import Cancelled
import pytest


def test_installed_real_hooks():
    assert {'provider', 'writer', 'make', 'export', 'projectzip'} <= set(server.STUDIO_HOOKS)


def test_job_context_owns_render_token():
    context = server.JobContext({})
    assert context.render_context.token is context.token
    context.cancel()
    with pytest.raises((Cancelled, server.JobCancelled)):
        context.check_cancelled()

import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy as np

from kinodraw import pipeline, voice
from kinodraw.audio import mix
from kinodraw.director.llm import providers
from kinodraw.director.llm.director import LLMDirector
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render
from kinodraw.package import _probe
from kinodraw.project_store import ProjectStore
from kinodraw.project_zip import import_project
from kinodraw.studio import integration


@pytest.fixture
def http_studio(tmp_path, monkeypatch):
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, 'JOBS', server.Jobs())
    monkeypatch.setattr(server, 'STUDIO_HOOKS', integration.hooks())
    monkeypatch.setattr(RulesDirector, '__init__', lambda self, lang: setattr(self, 'lang', lang))
    monkeypatch.setattr(RulesDirector, 'direct', lambda self, board: board)
    boards = []
    def payload(self, board, chapter, beats, count):
        boards.append(copy.deepcopy(board))
        return {'beats': [{'beat_id': b['id'], 'text': b['display'][board['lang']], 'candidates': []} for b in beats]}
    monkeypatch.setattr(LLMDirector, '_payload', payload)
    class MockProvider:
        name = 'loopback-mock'
        calls = 0
        def direct_plan(self, payload, usage):
            self.calls += 1
            usage.add('synthetic', 10, 20, cost=0)
            plan = from_rules(boards[-1])
            plan['style'].update(mode='hybrid', music_mood='none')
            for scene in plan['scenes']:
                scene.update(treatment='kinetic_type', transition_in='cut')
                scene['text']['kind'] = 'kinetic'
            return plan
    provider = MockProvider()
    server.STUDIO_HOOKS['provider'] = lambda body: provider
    monkeypatch.setattr(voice, 'ensure_models', lambda *a: None)
    def tone(text, lang, cache, *args):
        cache = Path(cache)
        cache.mkdir(parents=True, exist_ok=True)
        t = np.arange(voice.SR, dtype=np.float32) / voice.SR
        wav = cache / (str(len(list(cache.glob('*.wav')))) + '.wav')
        mix.write_wav(wav, .12 * np.sin(2 * np.pi * 440 * t), voice.SR)
        return voice.Clip(wav, 1.0, np.linspace(0, 1, len(text) + 1).tolist())
    monkeypatch.setattr(voice, 'synthesize', tone)
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, body=None, method=None, raw=False):
        req = urllib.request.Request(url + path.lstrip('/'),
            data=json.dumps(body).encode('utf-8') if body is not None else None,
            method=method or ('POST' if body is not None else 'GET'),
            headers={'X-Studio-Token': server.Handler.token, 'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=30) as response:
                data = response.read()
                return response.status, data if raw else json.loads(data)
        except urllib.error.HTTPError as response:
            return response.code, json.loads(response.read())
    request.root, request.provider = root, provider
    yield request
    for jid, job in server.JOBS.jobs.items():
        if job['state'] not in ('done', 'failed', 'cancelled'):
            server.JOBS.cancel(jid)
    deadline = time.monotonic() + 10
    while any(j['state'] not in ('done', 'failed', 'cancelled') for j in server.JOBS.jobs.values()) and time.monotonic() < deadline:
        time.sleep(.03)
    httpd.shutdown()
    httpd.server_close()


def wait_job(http, jid, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = http('/api/jobs/' + jid)[1]
        if job['state'] in ('done', 'failed', 'cancelled'):
            return job
        time.sleep(.03)
    server.JOBS.cancel(jid)
    pytest.fail('job timed out')


def create_http(http):
    code, made = http('/api/projects', {'text': '# Tone\n\nA small idea.', 'director': 'command', 'workers': 1})
    assert code == 200
    job = wait_job(http, made['job'])
    assert job['state'] == 'done', job
    return made['project'], http('/api/projects/' + made['project'])[1]


def test_http_create_make_decode_exports_and_lossless_zip(http_studio, tmp_path):
    http = http_studio
    name, state = create_http(http)
    path = http.root / name
    assert ProjectStore(path).load()['revision'] == state['revision']
    # Preserve every actual source second; the timeline adds its documented gaps.
    state['settings'].update(credit=False, credit_chosen=True)
    ProjectStore(path).save(state['storyboard'], state['settings'], state['revision'])
    made = http('/api/projects/' + name + '/make', {})[1]
    job = wait_job(http, made['job'])
    assert job['state'] == 'done', job
    assert http.provider.calls == 1
    video = path / job['result']['video']
    info = _probe(video)
    timeline = pipeline._load(path / 'build/timeline.json')
    assert info['frames'] == round(timeline['duration'] * render.FPS)
    assert info['audio'] and not info['errors']
    assert all(b['speech_end'] - b['start'] >= 1.0 for b in timeline['beats'].values())
    progress = http('/api/jobs/' + made['job'])[1]
    assert progress['frames'] == progress['total'] and progress['eta'] == 0
    revision = http('/api/projects/' + name)[1]['revision']
    assert http('/api/projects/' + name + '/format', {'aspect': '9:16', 'revision': state['revision']})[0] == 409
    exports = {}
    for fmt in ('webm', 'gif'):
        reply = http('/api/projects/' + name + '/export', {'revision': revision, 'format': fmt})[1]
        exported = wait_job(http, reply['job'])
        assert exported['state'] == 'done', exported
        file = exported['result']['file']
        code, data = http('/files/' + name + '/' + file, raw=True)
        assert code == 200 and data
        exported_path = tmp_path / ('download.' + fmt)
        exported_path.write_bytes(data)
        decoded = subprocess.run([render.FFMPEG, '-v', 'error', '-xerror', '-i', str(exported_path), '-f', 'null', '-'], capture_output=True)
        assert decoded.returncode == 0, decoded.stderr
        if fmt == 'gif':
            audio_file = exported['result']['audio_file']
            assert http('/files/' + name + '/' + audio_file, raw=True)[1] == (path / 'build/mix.wav').read_bytes()
        else:
            decoded_audio = subprocess.run([render.FFMPEG, '-v', 'error', '-i', str(exported_path), '-map', '0:a:0', '-f', 'null', '-'], capture_output=True)
            assert decoded_audio.returncode == 0, decoded_audio.stderr
        exports[fmt] = {'download_bytes': len(data), 'decode_exit': decoded.returncode}
    packed = http('/api/projects/' + name + '/projectzip', {'revision': revision})[1]
    archived = wait_job(http, packed['job'])
    assert archived['state'] == 'done', archived
    file = archived['result']['file']
    assert not integration.DOWNLOADS[(name, file)].is_relative_to(path)
    downloaded = tmp_path / 'download.zip'
    downloaded.write_bytes(http('/files/' + name + '/' + file, raw=True)[1])
    restored = tmp_path / 'restored'
    manifest = import_project(downloaded, restored)
    assert manifest['files']
    for rel in manifest['files']:
        assert (path / rel).read_bytes() == (restored / rel).read_bytes()
    print(json.dumps({'http_make': job['state'], 'decoded_frames': info['frames'], 'duration': timeline['duration'],
                      'provider_calls': http.provider.calls, 'exports': exports, 'zip_files': len(manifest['files'])}))


def test_http_cancel_owned_render_preserves_outputs_and_unrelated_process(http_studio, monkeypatch):
    http = http_studio
    name, state = create_http(http)
    path = http.root / name
    build = path / 'build'
    build.mkdir()
    good = build / 'silent.mp4'
    render.encode(_SlowFrames(), 0, 4, good, 20)
    prior = good.read_bytes()
    final = path / 'Tone.mp4'
    final.write_bytes(b'previous-finished')
    original = pipeline.render
    def long_render(path, *args, **kwargs):
        return original(path, duration=200, *args, **kwargs)
    monkeypatch.setattr(pipeline, 'render', long_render)
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        made = http('/api/projects/' + name + '/make', {})[1]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            job = http('/api/jobs/' + made['job'])[1]
            if job.get('frames', 0) > 0:
                break
            assert job['state'] not in ('failed', 'done'), job
            time.sleep(.03)
        assert job.get('frames', 0) > 0 and job['eta'] is not None
        context = server.JOBS.contexts[made['job']]
        owned = context.token.owned_pids
        assert owned
        assert http('/api/jobs/' + made['job'] + '/cancel', {})[0] == 200
        cancelled = wait_job(http, made['job'])
        assert cancelled['state'] == 'cancelled', cancelled
        assert good.read_bytes() == prior and final.read_bytes() == b'previous-finished'
        assert unrelated.poll() is None and not context.token.owned_pids
        print(json.dumps({'cancel_state': cancelled['state'], 'owned_pids': owned,
                          'prior_outputs_preserved': True, 'unrelated_survived': True, 'frames': job['frames']}))
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


class _SlowFrames:
    size = (160, 90)
    def frame(self, t):
        from PIL import Image
        return Image.new('RGB', self.size, (80, 90, 100))


def test_http_writer_honors_command_model_and_usage(http_studio, tmp_path, monkeypatch):
    command = tmp_path / 'synthetic_writer.py'
    request_file = tmp_path / 'request.json'
    command.write_text("import json,sys\nfrom pathlib import Path\n"
        "request=json.load(sys.stdin)\nPath(sys.argv[1]).write_text(json.dumps(request),encoding='utf-8')\n"
        "print(json.dumps({'title':'Source draft','sections':[{'heading':'Idea','paragraphs':['A small idea.'], 'source_notes':[0]}]}))\n", encoding='utf-8')
    import shlex
    server.STUDIO_HOOKS['provider'] = integration.provider_for
    code, result = http_studio('/api/writer', {'topic': 'An idea', 'notes': ['A small idea.'],
        'director': 'command', 'model': 'synthetic-model',
        'command': ' '.join(map(shlex.quote, [sys.executable, str(command), str(request_file)]))})
    assert code == 200 and result['ok']
    assert result['text'].startswith('# Source draft') and result['usage']['calls'] == 1
    assert result['usage']['cost_usd'] is None
    assert json.loads(request_file.read_text(encoding='utf-8'))['model'] == 'synthetic-model'
    assert http_studio('/api/writer', {'topic': 'An idea', 'notes': ['A small idea.'], 'director': 'command'})[0] == 400


def test_http_replan_conflict_and_manual_assets_and_cast_bible(http_studio):
    http = http_studio
    name, state = create_http(http)
    path = http.root / name
    pictures = path / 'pictures'
    pictures.mkdir()
    from PIL import Image
    Image.new('RGB', (20, 20), (80, 90, 100)).save(pictures / 'manual.png')
    manual = {'id': 'manual-art', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'own:manual.png'}]}
    state['storyboard']['beats'][0]['visuals'] = [manual]
    code, saved = http('/api/projects/' + name + '/storyboard',
        {'revision': state['revision'], 'storyboard': state['storyboard']}, 'PUT')
    assert code == 200
    # Cast edits in the persisted plan are the bible used for the next replan.
    cast_board = copy.deepcopy(saved['storyboard'])
    cast_board['beats'][0]['spoken']['en'] = 'Mara, a tigress, watched.'
    cast_board['beats'][0]['display']['en'] = 'Mara, a tigress, watched.'
    cast_plan = from_rules(cast_board)
    assert cast_plan['cast'], 'synthetic script must contain a required cast member'
    code, cast_saved = http('/api/projects/' + name + '/storyboard',
        {'revision': saved['revision'], 'storyboard': cast_board, 'plan_v3': cast_plan}, 'PUT')
    assert code == 200, cast_saved
    assert cast_saved['settings']['series_bible']['cast'] == cast_saved['settings']['plan_v3']['cast']
    saved = cast_saved
    original_provider = server.STUDIO_HOOKS['provider']
    entered, release = threading.Event(), threading.Event()
    class Slow:
        name = 'slow-mock'
        def direct_plan(self, payload, usage):
            entered.set()
            assert release.wait(10)
            return http.provider.direct_plan(payload, usage)
    server.STUDIO_HOOKS['provider'] = lambda body: Slow()
    pending = http('/api/projects/' + name + '/direct', {'revision': saved['revision'], 'director': 'command'})[1]
    assert entered.wait(10)
    saved['storyboard']['title']['en'] = 'Intervening manual title'
    code, edited = http('/api/projects/' + name + '/storyboard',
        {'revision': saved['revision'], 'storyboard': saved['storyboard']}, 'PUT')
    assert code == 200
    release.set()
    result = wait_job(http, pending['job'])
    assert result['state'] == 'failed' and 'changed elsewhere' in result['error']
    current = http('/api/projects/' + name)[1]
    assert current['storyboard']['title']['en'] == 'Intervening manual title'
    assert current['storyboard']['beats'][0]['visuals'] == [manual]
    assert (pictures / 'manual.png').is_file()
    server.STUDIO_HOOKS['provider'] = original_provider
    pending = http('/api/projects/' + name + '/direct', {'revision': current['revision'], 'director': 'command'})[1]
    result = wait_job(http, pending['job'])
    assert result['state'] == 'done', result
    current = http('/api/projects/' + name)[1]
    assert current['storyboard']['beats'][0]['visuals'] == [manual]
    assert current['settings']['series_bible']['cast'] == current['settings']['plan_v3']['cast']


def test_http_generated_assets_and_provenance_transfer(http_studio, monkeypatch):
    original = pipeline.direct_v3
    def generate(path, *args, **kwargs):
        report = original(path, *args, **kwargs)
        path = Path(path)
        doodles = path / 'doodles'
        doodles.mkdir()
        (doodles / 'gen-synthetic.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>', encoding='utf-8')
        (doodles / 'gen-synthetic.json').write_text('{"model":"synthetic","source":"test"}', encoding='utf-8')
        store = ProjectStore(path)
        saved = store.load()
        board, cfg = saved['storyboard'], saved['settings']
        board['beats'][0]['visuals'].append({'id': 'generated', 'type': 'cluster', 'relation': 'none',
                                           'items': [{'doodle': 'gen-synthetic'}]})
        cfg['plan_v3']['scenes'][0]['elements'].append({'kind': 'picture', 'ref': 'gen-synthetic'})
        cfg['scene_treatments'] = copy.deepcopy(cfg['plan_v3']['scenes'])
        store.save(board, cfg, saved['revision'])
        return report
    monkeypatch.setattr(pipeline, 'direct_v3', generate)
    name, state = create_http(http_studio)
    path = http_studio.root / name
    assert (path / 'doodles/gen-synthetic.svg').is_file()
    assert json.loads((path / 'doodles/gen-synthetic.json').read_text(encoding='utf-8'))['model'] == 'synthetic'
    integration.validate_references(state['storyboard'], state['settings'], path)
    assert state['settings']['scene_treatments'] == state['settings']['plan_v3']['scenes']


def test_provider_uses_explicit_model_and_base_without_keychain(monkeypatch):
    from kinodraw.director.llm import providers
    seen = []
    monkeypatch.setattr(providers, 'OpenAIProvider', lambda *a, **kw: seen.append((a, kw)) or object())
    integration.provider_for({'director': 'compat', 'model': 'explicit-model', 'base_url': 'http://127.0.0.1:1/v1', 'key': 'none'})
    assert seen == [(('explicit-model',), {'key': 'none', 'base_url': 'http://127.0.0.1:1/v1', 'name': 'compat', 'strict_schema': False})]


def test_http_finish_mux_cancel_preserves_prior_video(http_studio, tmp_path, monkeypatch):
    http = http_studio
    name, state = create_http(http)
    path = http.root / name
    # Seed a real, duration-matched cached render. The full Make/render path is
    # covered above; this check starts directly at the finish/mux seam so render
    # contention cannot consume the mux-start acceptance window.
    clips = pipeline.narrate(path)
    timeline = pipeline.build_audio(path, clips)
    from PIL import Image
    class CachedFrames:
        size = (1920, 1080)
        image = Image.new('RGB', size, (80, 90, 100))
        def frame(self, t):
            return self.image
    render.encode(CachedFrames(), 0, round(timeline['duration'] * render.FPS), path / 'build/silent.mp4', 20)
    def finish_only(path, body, context):
        context('finish', 0, 1)
        return pipeline.finish(path, context=context.render_context)
    server.STUDIO_HOOKS['make'] = finish_only
    prior = path / 'Tone.mp4'
    prior.write_bytes(b'prior-finished-video')
    ready = tmp_path / 'mux-started'
    proxy = tmp_path / 'synthetic_ffmpeg_proxy'
    proxy.write_text(f'#!{sys.executable}\nimport os,sys\nfrom pathlib import Path\n'
        f'args=sys.argv[1:]\nif "ffmetadata" in args:\n Path({str(ready)!r}).write_text("mux",encoding="utf-8")\n args.insert(args.index("-i"),"-re")\n'
        f'os.execv({render.FFMPEG!r},[{render.FFMPEG!r}]+args)\n', encoding='utf-8')
    proxy.chmod(0o700)
    original_popen = subprocess.Popen
    def owned_finish(args, *a, **kw):
        if isinstance(args, list) and '--finish-worker' in args:
            env = dict(kw.get('env') or __import__('os').environ)
            env['IMAGEIO_FFMPEG_EXE'] = str(proxy)
            kw['env'] = env
        return original_popen(args, *a, **kw)
    monkeypatch.setattr(subprocess, 'Popen', owned_finish)
    made = http('/api/projects/' + name + '/make', {})[1]
    deadline = time.monotonic() + 50
    while not ready.exists() and time.monotonic() < deadline:
        job = http('/api/jobs/' + made['job'])[1]
        assert job['state'] not in ('done', 'failed'), job
        time.sleep(.03)
    assert ready.exists(), 'actual mux did not start'
    context = server.JOBS.contexts[made['job']]
    owned = context.token.owned_pids
    assert owned
    assert http('/api/jobs/' + made['job'] + '/cancel', {})[0] == 200
    job = wait_job(http, made['job'])
    assert job['state'] == 'cancelled', job
    assert not context.token.owned_pids
    import os
    for pid in owned:
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
    assert prior.read_bytes() == b'prior-finished-video'
    print(json.dumps({'finish_mux_cancelled': True, 'owned_groups': owned,
                      'prior_video_preserved': True, 'state': job['state']}))

"""Real loopback HTTP and executed Studio editing JS; no accounts or render engine."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from kinodraw import pipeline
from kinodraw.director.llm import cloud, providers
from kinodraw.director.llm.director import LLMDirector
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.studio import server

EVIDENCE = Path(__file__).resolve().parents[1] / 'docs/overnight-2026-10-05/evidence/studio/review-fix'


@pytest.fixture
def studio(tmp_path, monkeypatch):
    home = tmp_path / 'synthetic-home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setattr(server, 'CONFIG', home / 'studio.json')
    monkeypatch.setattr(server.paths, 'projects_dir', lambda: home / 'projects')
    monkeypatch.setattr(server, 'JOBS', server.Jobs())
    monkeypatch.setattr(server, 'STUDIO_HOOKS', {})
    monkeypatch.setattr(cloud, 'URL', 'https://unused.invalid')
    monkeypatch.setattr(cloud, 'kept_install_id', lambda: None)
    monkeypatch.setattr(providers, 'saved', lambda: set())
    monkeypatch.setattr(providers, 'api_key', lambda *a, **k: pytest.fail('keychain access'))
    monkeypatch.setattr(server.voice, 'missing_files', lambda lang: [])
    monkeypatch.setattr(RulesDirector, '__init__', lambda self, lang: setattr(self, 'lang', lang))
    monkeypatch.setattr(RulesDirector, 'direct', lambda self, board: {'ok': True})
    # Isolate candidate generation, retain actual provider call, v3 validation and adaptation.
    def payload(self, board, chapter, beats, count):
        self.test_board = copy.deepcopy(board)
        return {'beats': [{'beat_id': b['id'], 'text': b['display'][board['lang']], 'candidates': []} for b in beats]}
    monkeypatch.setattr(LLMDirector, '_payload', payload)
    class Injected:
        name = 'synthetic-provider'
        def direct_plan(self, body, usage):
            assert all('spoken' in b for b in body['beats'])
            # Reconstructing a plan from the exact board is a deterministic provider fixture.
            plan = from_rules(boards[-1])
            plan['storyboard']['audience'] = 'synthetic viewers'
            return plan
    boards = []
    original = LLMDirector._payload
    def capture(self, board, *args):
        boards.append(copy.deepcopy(board))
        return original(self, board, *args)
    monkeypatch.setattr(LLMDirector, '_payload', capture)
    server.STUDIO_HOOKS['provider'] = lambda body: Injected()
    httpd, url = server.serve(0)
    token = server.Handler.token
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, body=None, method=None):
        req = urllib.request.Request(url + path.lstrip('/'),
              data=json.dumps(body).encode() if body is not None else None,
              method=method or ('POST' if body is not None else 'GET'),
              headers={'X-Studio-Token': token, 'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as response:
            return response.code, json.loads(response.read())
    request.url, request.token, request.home = url, token, home
    yield request
    httpd.shutdown(); httpd.server_close()


def wait(studio, job):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status, body = studio('/api/jobs/' + job)
        assert status == 200
        if body['state'] in ('done', 'failed', 'cancelled'):
            return body
        time.sleep(.02)
    pytest.fail('job did not terminate within 10 seconds')


def create(studio, **kwargs):
    status, body = studio('/api/projects', {'text': '# Lesson\n\nA book holds an idea.', 'look': 'whiteboard', **kwargs})
    assert status == 200
    result = wait(studio, body['job'])
    assert result['state'] == 'done', result
    name = body['project']
    return name, studio('/api/projects/' + name)[1]


def test_http_first_open_autosave_undo_reload_restore_conflict_cancel_retry(studio, monkeypatch):
    assert studio('/api/projects') == (200, [])
    assert studio('/api/state')[1]['default_director'] == 'cloud'
    name, initial = create(studio)
    assert initial['settings']['director_v3']
    assert initial['settings']['plan_v3_report']['provider'] == 'synthetic-provider'
    assert initial['settings']['plan_v3']['storyboard']['audience'] == 'synthetic viewers'
    assert initial['settings']['scene_treatments'] == initial['settings']['plan_v3']['scenes']
    node = shutil.which('node')
    assert node, 'Node is required to verify the actual front-end autosave and undo flow'
    script = r'''
const fs = require('fs'), vm = require('vm');
const initial = JSON.parse(process.argv[1]), url = process.argv[2], token = process.argv[3];
const elements = {}, storage = new Map();
function element(id) { return elements[id] ||= { disabled: false, textContent: '', value: '', classList: { toggle() {}, add() {}, remove() {} } }; }
const context = vm.createContext({ window: { STUDIO_TOKEN: token, addEventListener() {} },
 document: { querySelector: element, addEventListener() {}, querySelectorAll() { return []; } },
 localStorage: {setItem(k,v) {storage.set(k,v)}, getItem(k) {return storage.get(k)}, removeItem(k) {storage.delete(k)}},
 fetch: (path, opts) => fetch(new URL(path,url), opts), Blob, setTimeout, clearTimeout, console });
vm.runInContext(fs.readFileSync('kinodraw/studio/static/app.js', 'utf8'), context);
vm.runInContext(`STATE = {projects_root: 'synthetic'}; current = ${JSON.stringify(initial.name)};
 board = ${JSON.stringify(initial.storyboard)}; plan = ${JSON.stringify(initial.settings.plan_v3)};
 revision = ${JSON.stringify(initial.revision)}; lastEdit = editState(); renderBoard = () => {}; renderPlan = () => {}; loadNarrator = () => {};`, context);
(async () => {
 vm.runInContext(`board.title.en = 'Edited by autosave'; markDirty();`, context);
 await new Promise(r => setTimeout(r, 1300));
 const edited = await (await fetch(new URL('/api/projects/' + initial.name,url), {headers: {'X-Studio-Token':token}})).json();
 if (edited.storyboard.title.en !== 'Edited by autosave') throw Error('debounced autosave failed');
 if (vm.runInContext('dirty', context)) throw Error('dirty stayed set');
 vm.runInContext('travelHistory(false)', context);
 await vm.runInContext('saveBoard()', context);
 const undone = await (await fetch(new URL('/api/projects/' + initial.name,url), {headers: {'X-Studio-Token':token}})).json();
 if (undone.storyboard.title.en !== initial.storyboard.title.en) throw Error('undo was not persisted');
 vm.runInContext('travelHistory(true)', context);
 await vm.runInContext('saveBoard()', context);
 if (element('#dirty').textContent !== 'Saved') throw Error('missing saved status');
 // Edit while the first save is in flight: the serialized follow-up must win.
 vm.runInContext(`board.title.en = 'First in flight'; markDirty();`, context);
 const inflight = vm.runInContext('saveBoard()', context);
 vm.runInContext(`board.title.en = 'Edited by autosave'; markDirty();`, context);
 if (!(await inflight)) throw Error('in-flight follow-up failed');
 const latest = await (await fetch(new URL('/api/projects/' + initial.name,url), {headers: {'X-Studio-Token':token}})).json();
 if (latest.storyboard.title.en !== 'Edited by autosave') throw Error('late save overwrote latest edits');
 const changed = await fetch(new URL('/api/projects/' + initial.name + '/format',url), {
   method:'POST', headers:{'X-Studio-Token':token,'Content-Type':'application/json'},
   body:JSON.stringify({aspect:'9:16', revision:latest.revision}) });
 if (!changed.ok) throw Error('external edit fixture failed');
 vm.runInContext(`board.title.en = 'Conflict kept as draft'; markDirty();`, context);
 if (await vm.runInContext('saveBoard()',context)) throw Error('stale save succeeded');
 if (!element('#dirty').textContent.startsWith('Not saved:')) throw Error('persistent error missing');
 const draft = JSON.parse([...storage.values()][0]);
 if (draft.board.title.en !== 'Conflict kept as draft' || !draft.revision) throw Error('failed draft lost');
 console.log(JSON.stringify({autosave:true, undoReload:true, redo:true, inFlight:true, conflict:true, draftReload:true, savedStatus:'Saved', errorStatus:element('#dirty').textContent}));
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
    result = subprocess.run([node, '-e', script, json.dumps(initial), studio.url, studio.token], text=True,
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    after = studio('/api/projects/' + name)[1]
    assert after['storyboard']['title']['en'] == 'Edited by autosave'
    versions = studio('/api/projects/' + name + '/versions')[1]
    original_version = next(v for v in versions if v['label'] == 'Initial plan')
    status, restored = studio('/api/projects/' + name + '/restore', {'revision': after['revision'], 'version': original_version['id']})
    assert status == 200 and restored['storyboard'] == initial['storyboard']
    status, conflict = studio('/api/projects/' + name + '/storyboard', {'revision': after['revision'], 'storyboard': after['storyboard']}, 'PUT')
    assert status == 409 and conflict['code'] == 'revision_conflict'
    assert studio('/api/projects/' + name)[1]['storyboard'] == initial['storyboard']
    assert studio('/api/projects/' + name + '/reorder', {'revision': after['revision'], 'storyboard': after['storyboard'], 'beat': 'not-a-beat', 'visual': 0, 'to': 0})[0] == 400
    assert studio('/api/projects/' + name + '/storyboard', initial['storyboard'], 'PUT')[0] == 428
    calls = []
    def export(path, body, context):
        context('render', 0, 1)
        delay = 8 if not calls else .01
        calls.append(delay)
        context.run_process([sys.executable, '-c', f'import time; time.sleep({delay})'])
        return {'video': 'synthetic.mp4', 'ok': True, 'problems': [], 'length': 1}
    monkeypatch.setattr(server, 'apply_video_settings', lambda path: None)
    monkeypatch.setattr(pipeline, 'narrate', lambda *a, **k: {})
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: None)
    # An exported make hook uses the same Studio context as optional export modules.
    server.STUDIO_HOOKS['make'] = export
    status, made = studio('/api/projects/' + name + '/make', {})
    assert status == 200
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(.01)
    assert calls
    assert studio('/api/jobs/' + made['job'] + '/cancel', {})[0] == 200
    assert wait(studio, made['job'])['state'] == 'cancelled'
    retry = studio('/api/projects/' + name + '/make', {})[1]
    assert wait(studio, retry['job'])['state'] == 'done'
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / 'http-flow.json').write_text(json.dumps({'http_flow': 'passed', 'js': json.loads(result.stdout),
         'restore': status, 'stale_save': 409, 'make_cancel': 'cancelled', 'make_retry': 'done',
         'provider': 'synthetic-provider', 'external_network': False}, indent=2) + '\n', encoding='utf-8')


def test_versions_plan_edits_replan_and_project_manager(studio):
    name, state = create(studio)
    url = '/api/projects/' + name
    plan = copy.deepcopy(state['settings']['plan_v3'])
    plan['style']['energy'] = 4
    plan['scenes'][0]['camera'] = 'slow_push'
    status, saved = studio(url + '/storyboard', {'revision': state['revision'], 'storyboard': state['storyboard'], 'plan_v3': plan}, 'PUT')
    assert status == 200, saved
    assert saved['settings']['scene_treatments'][0]['camera'] == 'slow_push'
    assert saved['settings']['plan_v3']['style']['energy'] == 4
    bad = copy.deepcopy(plan); bad['style']['energy'] = 999
    assert studio(url + '/storyboard', {'revision': saved['revision'], 'storyboard': saved['storyboard'], 'plan_v3': bad}, 'PUT')[0] == 400
    replan = studio(url + '/direct', {'revision': saved['revision'], 'director': 'rules'})
    assert wait(studio, replan[1]['job'])['state'] == 'done'
    assert any(v['label'] == 'Before replan' for v in studio(url + '/versions')[1])
    assert studio(url + '/direct', {'revision': saved['revision'], 'director': 'rules'})[0] == 409
    state = studio(url)[1]
    status, duplicated = studio(url + '/duplicate', {'revision': state['revision']})
    assert status == 200 and duplicated['project'] != name
    assert studio('/api/projects/' + urllib.request.quote(duplicated['project']))[1]['storyboard'] == state['storyboard']
    renamed = studio(url + '/rename', {'revision': state['revision'], 'title': 'New title'})[1]
    trashed = studio(url + '/trash', {'revision': renamed['revision']})[1]
    assert all(p['name'] != name for p in studio('/api/projects')[1])
    assert any(p['name'] == name for p in studio('/api/projects?trash=1')[1])
    assert (studio.home / 'projects' / name / 'script.md').exists()
    assert studio(url + '/untrash', {'revision': trashed['revision']})[0] == 200
    assert any(p['name'] == name for p in studio('/api/projects')[1])


def test_legacy_off_and_unavailable_routes(studio, monkeypatch):
    monkeypatch.setattr(server.director, 'direct', lambda *a, **k: {'notes': []})
    name, state = create(studio, director='rules', director_v3=False)
    assert not state['settings']['director_v3'] and 'plan_v3' not in state['settings']
    for route in ['/api/writer', '/api/projects/' + name + '/export', '/api/projects/' + name + '/projectzip']:
        status, response = studio(route, {})
        assert status == 503 and 'unavailable' in response['error']
    assert studio('/api/starters')[0] == 503


def test_queued_cancel_never_executes_and_failure_is_truthful():
    jobs = server.Jobs()
    gate = __import__('threading').Event()
    first = jobs.start('test', 'synthetic', lambda context: gate.wait(3))
    ran = []
    second = jobs.start('test', 'synthetic', lambda context: ran.append(True))
    jobs.cancel(second); gate.set()
    deadline = time.monotonic() + 4
    while jobs.get(second)['state'] != 'cancelled' and time.monotonic() < deadline:
        time.sleep(.01)
    assert jobs.get(second)['state'] == 'cancelled' and not ran


def test_job_subprocess_failure_preserves_actual_exit():
    context = server.JobContext({})
    with pytest.raises(subprocess.CalledProcessError) as failed:
        context.run_process([sys.executable, '-c', 'raise SystemExit(7)'])
    assert failed.value.returncode == 7


def test_cancel_does_not_overwrite_worker_terminal_state(monkeypatch):
    """Force the worker to finish between the cancel signal and cancel's return."""
    jobs = server.Jobs()
    started = threading.Event()
    threads = []
    thread_type = threading.Thread

    def track_thread(*args, **kwargs):
        thread = thread_type(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(server.threading, 'Thread', track_thread)

    def work(context):
        started.set()
        assert context.cancelled.wait(3), 'cancel signal never reached worker'
        context.check_cancelled()

    jid = jobs.start('test', 'synthetic', work)
    assert started.wait(2)
    event = jobs.contexts[jid].cancelled
    signal = event.set

    def signal_and_join():
        signal()
        threads[0].join(2)
        assert not threads[0].is_alive(), 'worker did not finish at cancel barrier'

    monkeypatch.setattr(event, 'set', signal_and_join)
    response = jobs.cancel(jid)
    assert response['state'] == 'cancelled'
    assert jobs.get(jid)['state'] == 'cancelled'
    assert jobs.cancel(jid)['state'] == 'cancelled'

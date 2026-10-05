"""The dev command bridge, offline recovery, and saved plans through the real CLI renderer."""
import copy
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from kinodraw import cli, ingest, pipeline, script
from kinodraw.director.llm import providers
from kinodraw.director.v3 import llm
from kinodraw.director.v3.prompt import SYSTEM
from kinodraw.director.v3.schema import PLAN_SCHEMA
from kinodraw.engine import render, timeline

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'scripts' / 'dev_director_codex.py'


@pytest.fixture
def scratch():
    root = Path('/tmp/kd1005/a2-dev/tests')
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as path:
        yield Path(path)


@pytest.fixture
def fake_codex(scratch, monkeypatch):
    executable = scratch / 'codex'
    executable.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
schema = json.loads(Path(args[args.index('--output-schema') + 1]).read_text())
Path(os.environ['FAKE_LOG']).write_text(json.dumps({'args': args, 'schema': schema,
                                                  'has_api_key': 'OPENAI_API_KEY' in os.environ}))
print('codex progress, deliberately not JSON')
Path(args[args.index('-o') + 1]).write_text(Path(os.environ['FAKE_PLAN']).read_text())
''')
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(scratch) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-test-key')
    monkeypatch.setenv('FAKE_LOG', str(scratch / 'call.json'))
    monkeypatch.setenv('FAKE_PLAN', str(scratch / 'plan.json'))
    monkeypatch.setenv('KINODRAW_DIRECTOR_COMMAND', shlex.join([sys.executable, str(BRIDGE)]))
    monkeypatch.setattr(providers, 'api_key', lambda *a: pytest.fail('dev route read the keychain'))
    return scratch


def test_command_round_trip_through_fake_codex(fake_codex, monkeypatch):
    board = script.build(ingest.read('# Lesson\n\nA book holds an idea.'), story='story')
    before = copy.deepcopy(board)
    expected, _ = llm.plan_v3(board)
    (fake_codex / 'plan.json').write_text(json.dumps(expected))
    monkeypatch.setenv('DEV_DIRECTOR_MODEL', 'gpt-6-luna')
    monkeypatch.setenv('DEV_DIRECTOR_EFFORT', 'high')
    plan, report = llm.plan_v3(board, 'command')
    assert board == before and plan == expected
    assert not report['fallback'] and report['provider'] == 'command'
    assert report['usage'].calls == 1 and report['usage'].cost_usd is None
    call = json.loads((fake_codex / 'call.json').read_text())
    assert not call['has_api_key'] and call['schema'] == PLAN_SCHEMA
    args = call['args']
    assert args[:5] == ['exec', '-m', 'gpt-6-luna', '-c', 'model_reasoning_effort=high']
    assert args[5:9] == ['--sandbox', 'read-only', '--ephemeral', '--skip-git-repo-check']
    assert args[-1].startswith(SYSTEM)
    payload = json.loads(args[-1][len(SYSTEM):].strip())
    assert payload['beats'][0]['beat_id'] == board['beats'][0]['id']
    assert payload['beats'][0]['text'] == board['beats'][0]['display']['en']
    assert payload['beats'][0]['candidates'] and 'whiteboard' in payload['look_ids']
    assert payload['section_ids'] == ['main']


def test_bad_json_falls_back(fake_codex):
    (fake_codex / 'plan.json').write_text('not JSON')
    text = '# Lesson\n\nA book holds an idea.'
    expected, _ = llm.plan_v3(text, 'rules')
    plan, report = llm.plan_v3(text, 'command')
    assert plan == expected and report['fallback']
    assert 'JSON' in report['fallback_reason'] and report['notes']


def test_eval_command_explicit_env_and_model_subprocess(tmp_path):
    tool = tmp_path / 'command.py'
    log = tmp_path / 'requests.jsonl'
    plans = tmp_path / 'plans.json'
    fixtures = sorted((ROOT / 'tests' / 'fixtures' / 'genre').glob('*.md')) + [
        ROOT / 'tests' / 'fixtures' / 'lion_story.md']
    plans.write_text(json.dumps([llm.plan_v3(path)[0] for path in fixtures]), encoding='utf-8')
    tool.write_text('''import json, sys
from pathlib import Path
request = json.load(sys.stdin)
log, plans = map(Path, sys.argv[1:])
index = len(log.read_text(encoding='utf-8').splitlines()) if log.exists() else 0
with log.open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(request) + '\\n')
print(json.dumps(json.loads(plans.read_text(encoding='utf-8'))[index]))
''', encoding='utf-8')
    runner = tmp_path / 'eval_runner.py'
    runner.write_text('''import os, runpy, sys
sys.path.insert(0, sys.argv.pop(1))
from kinodraw.director.llm import providers
def forbidden(*args):
    raise AssertionError('explicit command route read api_key')
providers.api_key = forbidden
os.environ['KINODRAW_DIRECTOR_COMMAND'] = sys.argv.pop(1)
sys.argv[0] = sys.argv.pop(1)
runpy.run_path(sys.argv[0], run_name='__main__')
''', encoding='utf-8')
    out = tmp_path / 'eval'
    done = subprocess.run([sys.executable, str(runner), str(ROOT),
                           shlex.join([sys.executable, str(tool), str(log), str(plans)]),
                           str(ROOT / 'scripts' / 'eval_director_v3.py'),
                           '--provider', 'command', '--model', 'eval-test', '--out', str(out)],
                          capture_output=True, encoding='utf-8', timeout=30)
    assert done.returncode == 0, done.stderr
    reports = [json.loads(line) for line in done.stdout.splitlines()]
    requests = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert len(reports) == len(requests) == len(fixtures)
    assert all(r['model'] == 'eval-test' and r['schema'] == PLAN_SCHEMA for r in requests)
    assert all(not r['fallback'] and r['usage']['calls'] == 1 and
               r['usage']['cost_usd'] is None for r in reports)
    for path, report in zip(fixtures, reports):
        assert json.loads((out / f'{path.stem}.json').read_text(encoding='utf-8')) == report


def test_command_array_root_is_rejected(monkeypatch):
    from types import SimpleNamespace
    provider = providers.CommandProvider(command='unused-test-command')
    monkeypatch.setattr(providers.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout='[{"style":{"energy":99}}]', stderr=''))
    with pytest.raises(providers.ProviderError, match='JSON object'):
        provider.direct_plan({}, providers.Usage())


def test_provider_answer_is_repaired():
    class Broken:
        name = 'broken'

        def direct_plan(self, payload, usage):
            return {'style': {'energy': 99}}

    plan, report = llm.plan_v3('# Lesson\n\nCount three dots.', Broken())
    assert not report['fallback'] and report['repairs']
    assert plan['style']['energy'] == 5 and plan['scenes']


def test_injected_provider_does_not_need_a_name():
    expected, _ = llm.plan_v3('# Lesson\n\nCount three dots.')

    class Director:
        def direct_plan(self, payload, usage):
            return {**expected, 'storyboard': {**expected['storyboard'], 'audience': 'young students'}}

    plan, report = llm.plan_v3('# Lesson\n\nCount three dots.', Director())
    assert plan['storyboard']['audience'] == 'young students'
    assert report['provider'] == 'Director' and not report['fallback']


def test_named_byok_provider_routes_through_factory(monkeypatch):
    expected, _ = llm.plan_v3('# Lesson\n\nCount three dots.')
    class Provider:
        def direct_plan(self, payload, usage):
            return expected
    seen = []
    def factory(kind, **kwargs):
        seen.append((kind, kwargs))
        return Provider()
    monkeypatch.setattr(llm, 'make_provider', factory)
    _, report = llm.plan_v3('# Lesson\n\nCount three dots.', 'openai')
    assert not report['fallback'] and seen == [('openai', {'lang': 'en'})]


def test_missing_command_fails_offline_without_keys(monkeypatch):
    monkeypatch.delenv('KINODRAW_DIRECTOR_COMMAND', raising=False)
    monkeypatch.setattr(providers, 'api_key', lambda *a: pytest.fail('read a key'))
    _, report = llm.plan_v3('# Lesson\n\nCount three dots.', 'command')
    assert report['fallback'] and 'KINODRAW_DIRECTOR_COMMAND' in report['fallback_reason']


def test_bridge_timeout_is_clear(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location('dev_director_codex', BRIDGE)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    import io
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'schema': PLAN_SCHEMA, 'system': SYSTEM, 'user': '{}'})))

    def timeout(argv, **kwargs):
        assert kwargs['timeout'] == 600
        raise subprocess.TimeoutExpired(argv, 600)

    monkeypatch.setattr(bridge.subprocess, 'run', timeout)
    with pytest.raises(SystemExit, match='timed out after 600 seconds'):
        bridge.main()


def test_cli_saves_reuses_and_renders_whiteboard_frames(scratch, monkeypatch):
    project = scratch / 'project'
    cli.main(['new', '# Lesson\n\nA book holds an idea.', '-o', str(project),
              '--director-v3', '--director', 'rules', '--story', 'story', '--no-credit'])
    cfg = pipeline.settings(project)
    assert cfg['director_v3'] and cfg['plan_v3']['style']['whiteboard_skin'] == 'chalkboard'
    assert cfg['scene_treatments'] == cfg['plan_v3']['scenes']
    assert not cfg['plan_v3_report']['fallback']
    saved = (project / 'project.json').read_bytes()
    board = pipeline.storyboard(project)
    clips = timeline.synthetic_clips(board, 'en')
    timing = timeline.layout(board, 'en', clips, render.pacing(board, 'en', clips, project))
    (project / 'build').mkdir()
    pipeline._save(project / 'build' / 'timeline.json', timing)
    production = render.make_production(board, timing, 'en', project)
    assert isinstance(production, render.Production)
    t = max(e.end for e in production.ctx.elements) + .1
    monkeypatch.setattr(llm, 'plan_v3', lambda *a, **k: pytest.fail('saved plan was called again'))
    cli.main(['render', str(project), '--director-v3', '--stills', str(t)])
    from PIL import Image
    frame = Image.open(project / 'build' / 'stills' / f'{t:07.2f}.png')
    assert frame.size == render.SIZE and np.asarray(frame).std() > 10
    assert (project / 'project.json').read_bytes() == saved
    assert pipeline.direct_v3(project) == cfg['plan_v3_report']


def test_v3_defaults_off(scratch):
    pipeline.new_project('# Lesson\n\nCount three dots.', scratch / 'off')
    cfg = pipeline.settings(scratch / 'off')
    assert cfg['director_v3'] is False and 'plan_v3' not in cfg

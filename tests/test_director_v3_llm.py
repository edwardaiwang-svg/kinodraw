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


def test_unsupported_provider_fails_offline_before_loading_credentials(monkeypatch):
    monkeypatch.setattr(providers, 'make_provider', lambda *a, **k: pytest.fail('loaded a legacy provider'))
    _, report = llm.plan_v3('# Lesson\n\nCount three dots.', 'openai')
    assert report['fallback'] and 'contract v3 requires the command provider' in report['fallback_reason']


def test_missing_command_and_cloud_fail_offline_without_keys(monkeypatch):
    monkeypatch.delenv('KINODRAW_DIRECTOR_COMMAND', raising=False)
    monkeypatch.setattr(providers, 'api_key', lambda *a: pytest.fail('read a key'))
    for name, reason in [('command', 'KINODRAW_DIRECTOR_COMMAND'), ('cloud', 'contract v3 not deployed yet')]:
        _, report = llm.plan_v3('# Lesson\n\nCount three dots.', name)
        assert report['fallback'] and reason in report['fallback_reason']
    from kinodraw.director.llm import cloud
    monkeypatch.setattr(cloud.CloudProvider, '__init__', lambda *a: None)
    with pytest.raises(providers.ProviderError, match='contract v3 not deployed yet'):
        providers.make_provider('cloud').direct_plan({}, providers.Usage())


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

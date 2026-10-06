"""Project data cannot authorize director executables, endpoints or credentials."""
import hashlib
import io
import json
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace
import zipfile

import keyring
import pytest

from kinodraw import director, paths, pipeline
from kinodraw.director.llm import providers
from kinodraw.director.llm.director import LLMDirector
from kinodraw.director.rules import RulesDirector
from kinodraw.project_zip import MANIFEST, export_project
from kinodraw.studio import integration, server


@pytest.fixture(autouse=True)
def isolated_providers(monkeypatch, tmp_path):
    for name in (*providers.KEY_ENV.values(), 'KINODRAW_CLOUD_TOKEN', 'OPENAI_BASE_URL',
                 'DOODLE_DIRECTOR_COMMAND', 'DOODLE_COMPAT_API_KEY', 'DOODLE_CLOUD_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    monkeypatch.setattr(providers, 'SAVED', tmp_path / 'saved-keys.json')
    # Avoid search downloads and prop generation; retain real provider construction,
    # plan requests, subprocess execution, project saves and Studio validation.
    monkeypatch.setattr(RulesDirector, '__init__', lambda self, lang: setattr(self, 'lang', lang))
    monkeypatch.setattr(RulesDirector, 'direct', lambda self, board: board)
    from kinodraw.director import match
    from kinodraw.engine import hybrid
    monkeypatch.setattr(match, 'ensure_model', lambda *args: None)
    monkeypatch.setattr(hybrid, 'prepare_props', lambda *args: [])
    monkeypatch.setattr(LLMDirector, '_payload', lambda self, board, chapter, beats, count: {
        'beats': [{'beat_id': b['id'], 'candidates': []} for b in beats]})


def project(tmp_path, **settings):
    path = tmp_path / 'project'
    pipeline.new_project('# Trust\n\nA small idea is ready.', path, lang='en', **settings)
    return path


def command(sentinel):
    code = f"from pathlib import Path; Path({str(sentinel)!r}).write_text('ran'); print('{{}}')"
    return shlex.join([sys.executable, '-c', code])


def studio_jobs(monkeypatch):
    # Run the actual server job synchronously, without binding HTTP sockets.
    monkeypatch.setattr(server.JOBS, 'start', lambda kind, name, fn: fn(server.JobContext({})))
    monkeypatch.setattr(server, 'STUDIO_HOOKS', integration.hooks())


@pytest.mark.parametrize('entry', ['pipeline', 'render', 'legacy', 'studio-v3', 'studio-legacy'])
def test_project_command_requires_user_configuration(tmp_path, monkeypatch, entry):
    sentinel = tmp_path / 'project-command-ran'
    path = project(tmp_path, director='command', command=command(sentinel),
                   director_v3=entry != 'studio-legacy')
    if entry == 'render':
        build = path / 'build'
        build.mkdir()
        pipeline._save(build / 'timeline.json', {'duration': 1, 'layout': 'landscape'})
        monkeypatch.setattr(pipeline.renderer, 'pace_layout', lambda *args: 'landscape')
        monkeypatch.setattr(pipeline.renderer, 'render_segments', lambda *args, **kwargs: [])
        monkeypatch.setattr(pipeline, '_hybrid', lambda cfg: False)
        invoke = lambda: pipeline.render(path)
    elif entry == 'legacy':
        monkeypatch.setattr(LLMDirector, 'direct', lambda self, board, progress: (
            self.provider._ask('', {}, {}, providers.Usage()) and {'notes': [], 'usage': None}))
        invoke = lambda: director.direct(path, 'command')
    elif entry.startswith('studio'):
        studio_jobs(monkeypatch)
        monkeypatch.setattr(server, 'projects_root', lambda: tmp_path)
        if entry == 'studio-legacy':
            monkeypatch.setattr(LLMDirector, 'direct', lambda self, board, progress: (
                self.provider._ask('', {}, {}, providers.Usage()) and {'notes': [], 'usage': None}))
        invoke = lambda: server.redirect(path.name, {'director': 'command'})
    else:
        invoke = lambda: pipeline.direct_v3(path)
    try:
        with pytest.raises(ValueError, match='save the command first'):
            invoke()
    finally:
        assert not sentinel.exists(), 'the project executable ran'


def test_user_environment_command_wins_over_project_command(tmp_path, monkeypatch):
    untrusted, trusted = tmp_path / 'project-command-ran', tmp_path / 'user-command-ran'
    path = project(tmp_path, director='command', command=command(untrusted))
    monkeypatch.setenv('KINODRAW_DIRECTOR_COMMAND', command(trusted))
    report = pipeline.direct_v3(path)
    assert trusted.exists() and not untrusted.exists()
    assert report['provider'] == 'command'


class DirectionStopped(Exception):
    pass


@pytest.mark.parametrize('kind', ['openai', 'compat'])
@pytest.mark.parametrize('entry', ['pipeline', 'legacy', 'studio-v3', 'studio-legacy'])
def test_project_endpoint_and_key_are_not_provider_inputs(tmp_path, monkeypatch, kind, entry):
    path = project(tmp_path, director=kind, model='chosen-model',
                   base_url='https://project-attacker.invalid/v1', key='project-key',
                   director_v3=entry != 'studio-legacy')
    keyring.set_password(paths.APP, kind, 'synthetic-user-key')
    selected = []

    def stop(provider):
        selected.append(provider)
        raise DirectionStopped

    from kinodraw.director.v3 import llm
    monkeypatch.setattr(llm, 'plan_v3', lambda board, provider: stop(provider))
    monkeypatch.setattr(LLMDirector, 'direct', lambda self, *args: stop(self.provider))
    if entry == 'pipeline':
        invoke = lambda: pipeline.direct_v3(path)
    elif entry == 'legacy':
        invoke = lambda: director.direct(path, kind)
    else:
        studio_jobs(monkeypatch)
        monkeypatch.setattr(server, 'projects_root', lambda: tmp_path)
        invoke = lambda: server.redirect(path.name, {'director': kind})
    if kind == 'compat':
        with pytest.raises(ValueError, match='needs --base-url and --model'):
            invoke()
        assert not selected
    else:
        with pytest.raises(DirectionStopped):
            invoke()
        assert str(selected[-1].client.base_url).rstrip('/') == 'https://api.openai.com/v1'
        assert selected[-1].client.api_key == 'synthetic-user-key'
    # A current explicit endpoint remains usable, including for locally created compat projects.
    with pytest.raises(DirectionStopped):
        director.direct(path, kind, model='request-model', base_url='https://user-chosen.invalid/v1')
    assert str(selected[-1].client.base_url).rstrip('/') == 'https://user-chosen.invalid/v1'
    assert selected[-1].client.api_key == 'synthetic-user-key'
    assert selected[-1].model == 'request-model'


def test_project_cloud_token_is_not_provider_input(tmp_path, monkeypatch):
    path = project(tmp_path, director='cloud', token='project-token')
    from kinodraw.director.llm import cloud
    from kinodraw.director.v3 import llm
    selected = []
    monkeypatch.setattr(cloud, 'CloudProvider', lambda lang, token=None: SimpleNamespace(token=token))

    def stop(board, provider):
        selected.append(provider)
        raise DirectionStopped

    monkeypatch.setattr(llm, 'plan_v3', stop)
    with pytest.raises(DirectionStopped):
        pipeline.direct_v3(path)
    assert selected[0].token is None


def archive_bytes(path, settings):
    files = {'project.json': json.dumps(settings).encode('utf-8'),
             'storyboard.json': (path / 'storyboard.json').read_bytes()}
    manifest = {'format': 'kinodraw-project', 'version': 1, 'files': {
        name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in files.items()}}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr(MANIFEST, json.dumps(manifest))
    return stream.getvalue()


@pytest.mark.parametrize('field', ['command', 'base_url', 'key', 'token'])
@pytest.mark.parametrize('value', ['untrusted', '', None])
def test_import_rejects_provider_input_before_publication(tmp_path, monkeypatch, field, value):
    path = project(tmp_path)
    cfg = pipeline.settings(path)
    cfg[field] = value
    data = archive_bytes(path, cfg)
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    try:
        with pytest.raises(ValueError, match=field):
            integration.importzip(io.BytesIO(data), len(data))
    finally:
        assert not list(root.iterdir()), 'an Imported-* destination or staging folder was published'


@pytest.mark.parametrize('field', ['command', 'base_url', 'key', 'token'])
def test_export_omits_provider_input_and_still_imports(tmp_path, monkeypatch, field):
    path = project(tmp_path, **{field: 'untrusted'})
    before = (path / 'project.json').read_bytes()
    output = tmp_path / 'project.zip'
    manifest = export_project(path, output)
    with zipfile.ZipFile(output) as z:
        data = z.read('project.json')
        assert field not in json.loads(data)
        assert manifest['files']['project.json'] == {
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    uploaded = output.read_bytes()
    result = integration.importzip(io.BytesIO(uploaded), len(uploaded))
    restored = root / result['project']
    assert field not in pipeline.settings(restored)
    assert pipeline.storyboard(restored) == pipeline.storyboard(path)
    assert (path / 'project.json').read_bytes() == before


def test_cli_new_v3_passes_current_compat_arguments(tmp_path, monkeypatch):
    from kinodraw import cli
    selected = []
    monkeypatch.setattr(pipeline, 'direct_v3', lambda path, provider=None: (
        selected.append(provider) or {'notes': [], 'usage': None}))
    cli.main(['new', '# Local\n\nA small idea.', '--out', str(tmp_path / 'local'),
              '--director-v3', '--director', 'compat', '--model', 'request-model',
              '--base-url', 'https://user-chosen.invalid/v1'])
    assert isinstance(selected[0], providers.OpenAIProvider)
    assert str(selected[0].client.base_url).rstrip('/') == 'https://user-chosen.invalid/v1'
    assert selected[0].model == 'request-model'

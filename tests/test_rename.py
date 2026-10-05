"""Doodle Studio became KinoDraw in 0.2.0: an existing user keeps their models, settings and projects (the old
folders are renamed once), their scripts' DOODLE_* variables still work, and the old keychain entries are never read
(reading another app's entry makes macOS ask the user)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import platformdirs
import pytest

ROOT = Path(__file__).parents[1]
try:
    from kinodraw.paths import migrate as REAL_MIGRATE    # imported before conftest.py stubs it
except ImportError:                                       # Doodle Studio had no migration
    REAL_MIGRATE = None


def _fake_dirs(monkeypatch, base: Path):
    """platformdirs in a temporary folder, laid out like Windows: config and cache inside the data folder."""
    monkeypatch.setattr(platformdirs, 'user_data_dir', lambda app: str(base / 'Local' / app / app))
    monkeypatch.setattr(platformdirs, 'user_config_dir', lambda app: str(base / 'Local' / app / app))
    monkeypatch.setattr(platformdirs, 'user_cache_dir', lambda app: str(base / 'Local' / app / app / 'Cache'))
    monkeypatch.setattr(platformdirs, 'user_videos_dir', lambda: str(base / 'Videos'))
    from kinodraw import paths
    monkeypatch.setattr(paths, 'projects_dir', lambda: base / 'Videos' / 'KinoDraw')    # conftest.py stubs it too


def _old_install(base: Path):
    old = base / 'Local' / 'DoodleStudio' / 'DoodleStudio'
    (old / 'models').mkdir(parents=True)
    (old / 'models' / 'voices-v1.0.bin').write_bytes(b'voice')
    (old / 'Cache' / 'embed').mkdir(parents=True)
    (old / 'Cache' / 'embed' / 'model.onnx').write_bytes(b'embed')
    (base / 'Videos' / 'Doodle Studio' / 'My Video').mkdir(parents=True)
    (base / 'Videos' / 'Doodle Studio' / 'My Video' / 'project.json').write_text('{}', encoding='utf-8')
    (old / 'studio.json').write_text(json.dumps({'projects': str(base / 'Videos' / 'Doodle Studio'), 'credit': False}),
                                     encoding='utf-8')
    return old


def test_the_first_run_moves_doodle_studios_folders(tmp_path, monkeypatch):
    from kinodraw import cli, paths
    monkeypatch.setattr(paths, 'migrate', REAL_MIGRATE)        # conftest.py stubs it for every other test
    _fake_dirs(monkeypatch, tmp_path)
    _old_install(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(['--help'])
    new = tmp_path / 'Local' / 'KinoDraw' / 'KinoDraw'
    assert (new / 'models' / 'voices-v1.0.bin').read_bytes() == b'voice'          # no 192 MB download again
    assert (new / 'Cache' / 'embed' / 'model.onnx').read_bytes() == b'embed'
    assert (tmp_path / 'Videos' / 'KinoDraw' / 'My Video' / 'project.json').exists()
    assert not (tmp_path / 'Local' / 'DoodleStudio').exists() and not (tmp_path / 'Videos' / 'Doodle Studio').exists()
    settings = json.loads((new / 'studio.json').read_text(encoding='utf-8'))
    assert settings == {'projects': str(tmp_path / 'Videos' / 'KinoDraw'), 'credit': False}   # the saved folder follows


def test_migration_runs_once_and_never_overwrites(tmp_path, monkeypatch):
    from kinodraw.paths import legacy_moves
    migrate = REAL_MIGRATE
    _fake_dirs(monkeypatch, tmp_path)
    _old_install(tmp_path)
    assert len(migrate(legacy_moves(), tmp_path / 'none.json')) == 2       # data (with config and cache), projects
    assert migrate(legacy_moves(), tmp_path / 'none.json') == []
    for new in (tmp_path / 'Local' / 'KinoDraw' / 'KinoDraw', tmp_path / 'Videos' / 'KinoDraw'):   # a non-empty new
        (new / 'keep.txt').write_text('mine', encoding='utf-8')                                   # folder is never replaced
    again = _old_install(tmp_path)                                          # an old copy reappears: it stays put
    assert migrate(legacy_moves(), tmp_path / 'none.json') == [] and (again / 'models').is_dir()
    assert (tmp_path / 'Local' / 'KinoDraw' / 'KinoDraw' / 'models' / 'voices-v1.0.bin').exists()


def test_an_empty_new_folder_does_not_block_the_move(tmp_path, monkeypatch):
    from kinodraw.paths import legacy_moves
    _fake_dirs(monkeypatch, tmp_path)
    _old_install(tmp_path)
    (tmp_path / 'Videos' / 'KinoDraw').mkdir(parents=True)                 # e.g. made by an earlier test run
    assert len(REAL_MIGRATE(legacy_moves(), tmp_path / 'none.json')) == 2
    assert (tmp_path / 'Videos' / 'KinoDraw' / 'My Video' / 'project.json').exists()


def test_a_folder_that_cannot_be_renamed_is_left_where_it_is(tmp_path, monkeypatch):
    from kinodraw.paths import legacy_moves
    migrate = REAL_MIGRATE
    _fake_dirs(monkeypatch, tmp_path)
    old = _old_install(tmp_path)

    def refuse(self, target):
        raise OSError(18, 'Invalid cross-device link')
    monkeypatch.setattr(Path, 'rename', refuse)
    assert migrate(legacy_moves(), tmp_path / 'none.json') == []
    assert (old / 'models' / 'voices-v1.0.bin').exists()


def test_a_doodle_studio_sign_in_is_not_shown_as_a_kinodraw_one(tmp_path, monkeypatch):
    """The keychain entries keep Doodle Studio's name and are never read, so their list (saved-keys.json, in the
    settings folder) must not move either: the Studio would say "signed in", preselect KinoDraw Cloud, skip the
    sign-in prompt and fail the first Create, and list API keys that are not there."""
    from kinodraw.director.llm import cloud, providers
    from kinodraw.paths import legacy_moves
    from kinodraw.studio import server
    _fake_dirs(monkeypatch, tmp_path)
    old = _old_install(tmp_path)
    (old / 'saved-keys.json').write_text(json.dumps(['cloud-token', 'openai']), encoding='utf-8')
    new = tmp_path / 'Local' / 'KinoDraw' / 'KinoDraw'
    monkeypatch.setattr(providers, 'SAVED', new / 'saved-keys.json')
    monkeypatch.setattr(server, 'CONFIG', new / 'studio.json')
    monkeypatch.setattr(cloud, 'URL', 'https://api.example.org')
    for var in ('KINODRAW_CLOUD_TOKEN', 'DOODLE_CLOUD_TOKEN', *providers.KEY_ENV.values()):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.replace('KINODRAW_', 'DOODLE_'), raising=False)
    assert len(REAL_MIGRATE(legacy_moves(), new / 'studio.json')) == 2
    state = server.state()
    assert not state['cloud_signed_in'] and state['default_director'] == 'rules'     # the sign-in prompt shows
    assert not any(state['keys'].values())                                           # "re-enter any saved keys"
    assert (new / 'models' / 'voices-v1.0.bin').exists()
    assert json.loads((new / 'studio.json').read_text(encoding='utf-8'))['credit'] is False
    providers.remember('openai')                          # KinoDraw's own list is never touched by a later run
    assert REAL_MIGRATE(legacy_moves(), new / 'studio.json') == [] and providers.saved() == {'openai'}


def _env_probe(env: dict) -> list:
    code = ('import json; from kinodraw import voice; from kinodraw.director import match; '
            'from kinodraw.director.llm import cloud; '
            'print(json.dumps([str(voice.MODEL_DIR), str(match.CACHE), cloud.URL, cloud._token()]))')
    clean = {k: v for k, v in os.environ.items() if not k.startswith(('KINODRAW_', 'DOODLE_'))}
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=clean | env, capture_output=True, text=True,
                         check=True, encoding='utf-8').stdout
    return json.loads(out.strip().splitlines()[-1])


def test_kinodraw_variables_and_the_old_doodle_names(tmp_path):
    new = {'KINODRAW_MODELS': str(tmp_path / 'new'), 'KINODRAW_CLOUD_URL': 'https://new.example.org',
           'KINODRAW_CLOUD_TOKEN': 'new-token'}
    old = {'DOODLE_MODELS': str(tmp_path / 'old'), 'DOODLE_CLOUD_URL': 'https://old.example.org',
           'DOODLE_CLOUD_TOKEN': 'old-token'}
    assert _env_probe(new) == [str(tmp_path / 'new'), str(tmp_path / 'new' / 'embed'), 'https://new.example.org',
                               'new-token']
    assert _env_probe(old) == [str(tmp_path / 'old'), str(tmp_path / 'old' / 'embed'), 'https://old.example.org',
                               'old-token']
    assert _env_probe(old | new) == _env_probe(new)                         # the new name wins


def test_keys_use_the_kinodraw_keychain_entry_and_never_read_the_old_one(tmp_path, monkeypatch):
    import keyring
    from kinodraw.director.llm import cloud, providers
    calls = []
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: calls.append(('get', service, name)))
    monkeypatch.setattr(keyring, 'set_password', lambda service, name, value: calls.append(('set', service, name)))
    monkeypatch.setattr(providers, 'SAVED', tmp_path / 'saved-keys.json')
    for var in ('KINODRAW_CLOUD_TOKEN', 'DOODLE_CLOUD_TOKEN', 'OPENAI_API_KEY'):
        monkeypatch.delenv(var, raising=False)
    providers.save_key('openai', 'sk-test')
    providers.api_key('openai')
    cloud._token()
    assert calls == [('set', 'KinoDraw', 'openai'), ('get', 'KinoDraw', 'openai'), ('get', 'KinoDraw', 'cloud-token')]


def test_own_key_variables_accept_both_names(tmp_path, monkeypatch):
    from kinodraw.director.llm import providers
    monkeypatch.setattr(providers, 'SAVED', tmp_path / 'saved-keys.json')
    for var in ('KINODRAW_COMPAT_API_KEY', 'DOODLE_COMPAT_API_KEY', 'KINODRAW_DIRECTOR_COMMAND', 'DOODLE_DIRECTOR_COMMAND'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('KINODRAW_COMPAT_API_KEY', 'k')
    monkeypatch.setenv('DOODLE_DIRECTOR_COMMAND', 'my-director')
    assert {'compat', 'command'} <= providers.saved()


def _lock(monkeypatch, *folders) -> set:
    """Renaming these folders fails, as on Windows while Doodle Studio (or an antivirus scan) has a file in them
    open. Empty the returned set to "close Doodle Studio"."""
    locked, rename = {Path(f) for f in folders}, os.rename

    def refuse(src, dst, *args, **kwargs):
        if Path(src) in locked:
            raise PermissionError(13, 'The process cannot access the file because it is being used by another process',
                                  str(src))
        return rename(src, dst, *args, **kwargs)
    monkeypatch.setattr(os, 'rename', refuse)
    return locked


def test_nothing_moves_out_of_a_folder_that_could_not_move(tmp_path, monkeypatch):
    """Windows keeps the cache and settings inside the data folder. When the data folder could not be renamed, the
    cache inside it was moved on its own, which made KinoDraw's data folder exist, so the data folder (models,
    settings) was never moved on any later launch."""
    from kinodraw.paths import legacy_moves
    _fake_dirs(monkeypatch, tmp_path)
    old = _old_install(tmp_path)
    _lock(monkeypatch, old)
    new = tmp_path / 'Local' / 'KinoDraw' / 'KinoDraw'
    assert REAL_MIGRATE(legacy_moves(), new / 'studio.json') == [(tmp_path / 'Videos' / 'Doodle Studio',
                                                                  tmp_path / 'Videos' / 'KinoDraw')]
    assert (old / 'Cache' / 'embed' / 'model.onnx').exists() and not (new / 'Cache').exists()
    assert (old / 'models' / 'voices-v1.0.bin').exists() and (old / 'studio.json').exists()


def test_a_folder_that_could_not_move_comes_over_on_a_later_launch(tmp_path, monkeypatch):
    """...even after the user carried on in KinoDraw in the meantime: KinoDraw's own files stay, everything else of
    Doodle Studio's comes over, and a project with the same name as a KinoDraw one comes over renamed."""
    from kinodraw import paths
    from kinodraw.paths import legacy_moves
    _fake_dirs(monkeypatch, tmp_path)
    old = _old_install(tmp_path)
    (old / 'models' / 'kokoro-zh.onnx').write_bytes(b'zh')
    videos, new = tmp_path / 'Videos', tmp_path / 'Local' / 'KinoDraw' / 'KinoDraw'
    locked = _lock(monkeypatch, old, old / 'models' / 'kokoro-zh.onnx', videos / 'Doodle Studio')
    assert REAL_MIGRATE(legacy_moves(), new / 'studio.json') == []
    assert set(paths.left_behind) == {old, videos / 'Doodle Studio'}
    (new / 'models').mkdir(parents=True)                       # KinoDraw downloads the English voice again,
    (new / 'models' / 'voices-v1.0.bin').write_bytes(b'new voice')
    (new / 'studio.json').write_text(json.dumps({'credit': True}), encoding='utf-8')   # saves a setting, makes the sample video
    (videos / 'KinoDraw' / 'My Video').mkdir(parents=True)
    (videos / 'KinoDraw' / 'My Video' / 'project.json').write_text('{"kinodraw": 1}', encoding='utf-8')
    locked.discard(old)                                        # next launch, a model file is still in use
    assert REAL_MIGRATE(legacy_moves(), new / 'studio.json') == [(videos / 'Doodle Studio', videos / 'KinoDraw')]
    assert paths.left_behind == [old] and (new / 'Cache' / 'embed' / 'model.onnx').read_bytes() == b'embed'
    locked.clear()                                             # Doodle Studio closed: the rest comes over
    assert REAL_MIGRATE(legacy_moves(), new / 'studio.json') == [(old, new)] and paths.left_behind == []
    assert (new / 'models' / 'kokoro-zh.onnx').read_bytes() == b'zh'
    assert (new / 'models' / 'voices-v1.0.bin').read_bytes() == b'new voice'        # KinoDraw's own file stays
    assert (old / 'models' / 'voices-v1.0.bin').read_bytes() == b'voice'            # nothing is deleted
    assert (videos / 'KinoDraw' / 'My Video' / 'project.json').read_text(encoding='utf-8') == '{"kinodraw": 1}'
    assert (videos / 'KinoDraw' / 'My Video (Doodle Studio)' / 'project.json').read_text(encoding='utf-8') == '{}'
    assert json.loads((new / 'studio.json').read_text(encoding='utf-8')) == {'projects': str(videos / 'KinoDraw'), 'credit': True}
    assert REAL_MIGRATE(legacy_moves(), new / 'studio.json') == [] and paths.left_behind == []   # done for good
    assert not (paths.config_dir() / paths.PENDING).exists()


def test_the_user_is_told_when_their_doodle_studio_folder_could_not_move(tmp_path, monkeypatch, capsys):
    import re
    from kinodraw import cli, paths
    from kinodraw.studio import server
    monkeypatch.setattr(paths, 'migrate', REAL_MIGRATE)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    _fake_dirs(monkeypatch, tmp_path)
    old = _old_install(tmp_path)
    locked = _lock(monkeypatch, old)
    with pytest.raises(SystemExit):
        cli.main(['--help'])
    err = capsys.readouterr().err
    assert 'Close Doodle Studio' in err and str(old) in err
    assert 'Close Doodle Studio' in server.state()['notice']
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert re.search(r'await refreshState\(\);\s*if \(STATE\.notice\) toast\(STATE\.notice, \d{5}\)', js)
    locked.clear()
    with pytest.raises(SystemExit):
        cli.main(['--help'])
    assert 'Doodle Studio' not in capsys.readouterr().err and server.state()['notice'] is None


def test_a_projects_folder_inside_doodle_studios_follows_it(tmp_path, monkeypatch):
    """Settings -> Projects folder can be a folder inside the old one, e.g. Videos/Doodle Studio/Class."""
    from kinodraw.paths import legacy_moves
    _fake_dirs(monkeypatch, tmp_path)
    old = _old_install(tmp_path)
    videos, new = tmp_path / 'Videos', tmp_path / 'Local' / 'KinoDraw' / 'KinoDraw'
    (videos / 'Doodle Studio' / 'Class' / 'Lesson 1').mkdir(parents=True)
    (videos / 'Doodle Studio' / 'Class' / 'Lesson 1' / 'project.json').write_text('{}', encoding='utf-8')
    (old / 'studio.json').write_text(json.dumps({'projects': str(videos / 'Doodle Studio' / 'Class')}), encoding='utf-8')
    assert len(REAL_MIGRATE(legacy_moves(), new / 'studio.json')) == 2
    assert json.loads((new / 'studio.json').read_text(encoding='utf-8')) == {'projects': str(videos / 'KinoDraw' / 'Class')}
    assert (videos / 'KinoDraw' / 'Class' / 'Lesson 1' / 'project.json').exists()



def test_a_video_made_in_doodle_studio_still_finishes_after_its_folder_moved(tmp_path):
    """build/timeline.json named the narration by its absolute path, so `kinodraw finish` failed once the projects
    folder had moved. It is now stored next to the timeline, and an old absolute path falls back to the same file
    in the project's build folder."""
    import numpy as np
    from kinodraw import pipeline, voice
    from kinodraw.audio import mix
    old = tmp_path / 'Videos' / 'Doodle Studio' / 'Honey'
    board = pipeline.new_project(Path(__file__).parent / 'fixtures' / 'tiny.md', old)
    board['music'] = False
    (old / 'voice').mkdir(exist_ok=True)
    clips = {}
    for beat in board['beats']:
        wav = old / 'voice' / f"{beat['id']}.wav"
        mix.write_wav(wav, .1 * np.sin(np.linspace(0, 400 * np.pi, 12000, dtype=np.float32)), 24000)
        clips[beat['id']] = voice.Clip(wav, .5, [0.0] * len(beat['spoken']['en']))
    mix.assemble(board, 'en', clips, old / 'build')
    new = tmp_path / 'Videos' / 'KinoDraw' / 'Honey'
    new.parent.mkdir(parents=True)
    old.rename(new)                                            # the projects folder moved
    tl = json.loads((new / 'build' / 'timeline.json').read_text(encoding='utf-8'))
    assert mix.mix(board, tl, new / 'build').exists()
    tl['audio'] = str(old / 'build' / 'narration.wav')         # as Doodle Studio 0.1.x wrote it
    assert mix.mix(board, tl, new / 'build').exists()
    tl['audio'] = 'C:\\Users\\Ann\\Videos\\Doodle Studio\\Honey\\build\\narration.wav'   # made on Windows
    assert mix.mix(board, tl, new / 'build').exists()

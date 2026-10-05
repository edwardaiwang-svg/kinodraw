import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from kinodraw import project_store as store


@pytest.fixture
def project(tmp_path):
    path = tmp_path / 'project'
    store.atomic_save_json(path / 'project.json', {'lang': 'en'})
    store.atomic_save_json(path / 'storyboard.json', {'title': 'one'})
    return path


def test_atomic_interruption_and_validation_keep_old_json(project, monkeypatch):
    target = project / 'storyboard.json'
    before = target.read_bytes()
    with pytest.raises(ValueError):
        store.atomic_save_json(target, {'value': float('nan')})
    with pytest.raises(ValueError):
        store.atomic_save_json(target, {}, lambda _: {'ok': False, 'errors': ['invalid']})
    monkeypatch.setattr(store.os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError, match='interrupted'):
        store.atomic_save_json(target, {'title': 'two'})
    assert target.read_bytes() == before
    assert json.loads(before) == {'title': 'one'}
    assert not list(project.glob('.storyboard.json-*'))


def test_pair_recovers_after_second_file_interruption(project, monkeypatch):
    api = store.ProjectStore(project)
    old = api.load()
    real = store.atomic_save_json
    def fail(path, data, validator=None):
        if path == project / 'project.json':
            raise OSError('power loss')
        return real(path, data, validator)
    monkeypatch.setattr(store, 'atomic_save_json', fail)
    with pytest.raises(OSError):
        api.save({'title': 'two'}, {'lang': 'zh'}, old['revision'])
    assert json.loads((project / 'storyboard.json').read_text()) == {'title': 'two'}
    assert json.loads((project / 'project.json').read_text()) == {'lang': 'en'}
    monkeypatch.setattr(store, 'atomic_save_json', real)
    recovered = store.ProjectStore(project).load()
    assert recovered['settings'] == {'lang': 'zh'}
    assert recovered['storyboard'] == {'title': 'two'}
    assert not (project / '.studio/pending.json').exists()
    version = api.versions()[0]
    restored = api.restore(version['id'], recovered['revision'])
    assert restored['storyboard'] == old['storyboard'] and restored['settings'] == old['settings']


def test_stale_and_concurrent_saves_cannot_overwrite(project):
    api = store.ProjectStore(project)
    before = api.load()
    def save(title):
        try:
            api.save({'title': title}, expected_revision=before['revision'])
            return 'ok'
        except store.RevisionConflict:
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(save, ['two', 'three'])) == ['conflict', 'ok']
    with pytest.raises(store.RevisionConflict):
        api.restore(api.versions()[0]['id'], before['revision'])


def test_external_pipeline_edit_changes_revision(project):
    api = store.ProjectStore(project)
    before = api.load()
    store.atomic_save_json(project / 'project.json', {'lang': 'zh'})
    with pytest.raises(store.RevisionConflict):
        api.save({'title': 'stale'}, expected_revision=before['revision'])
    assert api.load()['storyboard'] == before['storyboard']


def test_snapshot_is_immutable_and_validated_save_does_not_create_version(project):
    api = store.ProjectStore(project, lambda x: {'ok': bool(x.get('title')), 'errors': ['title required']})
    before = api.load()
    version = api.snapshot('Before replan', before['revision'])
    with pytest.raises(ValueError, match='title required'):
        api.save({}, expected_revision=before['revision'])
    assert api.load() == before and len(api.versions()) == 1
    with pytest.raises(ValueError):
        api.restore('../project', before['revision'])
    assert api.versions()[0] == version


def test_restore_does_not_reuse_old_revision(project):
    api = store.ProjectStore(project)
    old = api.load()
    version = api.snapshot('old')
    edited = api.save({'title': 'two'}, expected_revision=old['revision'])
    restored = api.restore(version['id'], edited['revision'])
    assert restored['storyboard'] == old['storyboard']
    assert restored['revision'] != old['revision']
    with pytest.raises(store.RevisionConflict):
        api.save({'title': 'stale'}, expected_revision=old['revision'])


def test_atomic_initialization_recovers_complete_pair(tmp_path, monkeypatch):
    path = tmp_path / 'new'
    api = store.ProjectStore(path)
    real = store.atomic_save_json
    def interrupt(target, value, validator=None):
        if target == path / 'project.json':
            raise OSError('interrupted initialization')
        real(target, value, validator)
    monkeypatch.setattr(store, 'atomic_save_json', interrupt)
    with pytest.raises(OSError):
        api.initialize({'title': 'new'}, {'lang': 'en'})
    monkeypatch.setattr(store, 'atomic_save_json', real)
    saved = api.load()
    assert saved['storyboard'] == {'title': 'new'} and saved['settings'] == {'lang': 'en'}
    with pytest.raises(FileExistsError):
        api.initialize({'title': 'overwrite'}, {'lang': 'en'})

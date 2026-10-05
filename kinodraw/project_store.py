"""Crash-safe project JSON, revision checks and restorable snapshots.

Pipeline callers may reuse atomic_save_json, snapshot and ProjectStore. A journal
commits both editable files: readers recover an interrupted mirror update under
an advisory process lock. Snapshots are immutable; no versions are deleted here.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid
from datetime import datetime, timezone

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class RevisionConflict(ValueError):
    def __init__(self, revision):
        self.revision = revision
        super().__init__('This project changed elsewhere. Reload before saving; your draft is kept.')


def atomic_save_json(path, data, validator=None):
    """Validate and serialize before touching the destination, fsync then replace.

    validator may raise or return a report with ok=False. NaN/Infinity are rejected.
    An interruption before replace leaves the previous JSON intact.
    """
    if validator:
        result = validator(data)
        if isinstance(result, dict) and not result.get('ok', True):
            raise ValueError('; '.join(result.get('errors', ['Invalid JSON state'])))
    encoded = (json.dumps(data, ensure_ascii=False, allow_nan=False, indent=1) + '\n').encode('utf-8')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


save_json = atomic_save_json


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _revision(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class ProjectStore:
    def __init__(self, path, validator=None):
        self.path = Path(path).resolve()
        self.meta = self.path / '.studio'
        self.validator = validator

    @contextmanager
    def locked(self):
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(str(self.path), threading.RLock())
        with lock:
            self.meta.mkdir(parents=True, exist_ok=True)
            with (self.meta / 'lock').open('a+b') as handle:
                if os.name == 'nt':
                    import msvcrt
                    handle.write(b'0'); handle.flush(); handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    self._recover()
                    yield
                finally:
                    if os.name == 'nt':
                        handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def _recover(self):
        journal = self.meta / 'pending.json'
        if journal.exists():
            state = _read(journal)
            self._validate(state)
            atomic_save_json(self.path / 'storyboard.json', state['storyboard'])
            atomic_save_json(self.path / 'project.json', state['settings'])
            if state.get('_generation'):
                atomic_save_json(self.meta / 'generation.json', {'id': state['_generation']})
            journal.unlink()
            if os.name != 'nt':
                directory = os.open(self.meta, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)

    def _state(self):
        generation = self.meta / 'generation.json'
        return {'storyboard': _read(self.path / 'storyboard.json'), 'settings': _read(self.path / 'project.json'),
                '_generation': _read(generation)['id'] if generation.exists() else ''}

    def _validate(self, state):
        if not isinstance(state.get('settings'), dict) or not isinstance(state.get('storyboard'), dict):
            raise ValueError('Project settings and storyboard must be objects')
        if self.validator:
            report = self.validator(state['storyboard'])
            if not report['ok']:
                raise ValueError('; '.join(report['errors'][:20]))
        json.dumps(state, allow_nan=False)

    def initialize(self, storyboard, settings):
        """Commit a new project only after the whole plan is validated."""
        with self.locked():
            if (self.path / 'project.json').exists():
                raise FileExistsError('Project already exists')
            state = {'storyboard': deepcopy(storyboard), 'settings': deepcopy(settings), '_generation': uuid.uuid4().hex}
            self._validate(state)
            atomic_save_json(self.meta / 'pending.json', state)
            self._recover()
            self._snapshot(state, 'Initial plan')
            return {**state, 'revision': _revision(state)}

    def load(self):
        with self.locked():
            state = self._state()
            return {**state, 'revision': _revision(state)}

    def _snapshot(self, state, label):
        vid = uuid.uuid4().hex
        item = {'id': vid, 'label': str(label)[:120], 'created': datetime.now(timezone.utc).isoformat(),
                'revision': _revision(state), **deepcopy(state)}
        atomic_save_json(self.meta / 'versions' / (vid + '.json'), item)
        return {k: item[k] for k in ('id', 'label', 'created', 'revision')}

    def snapshot(self, label='Saved version', expected_revision=None):
        with self.locked():
            state = self._state()
            self._check(state, expected_revision)
            return self._snapshot(state, label)

    def _check(self, state, expected):
        if expected is not None and expected != _revision(state):
            raise RevisionConflict(_revision(state))

    def save(self, storyboard, settings=None, expected_revision=None, label='Before edit'):
        with self.locked():
            old = self._state()
            self._check(old, expected_revision)
            state = {'storyboard': deepcopy(storyboard), 'settings': deepcopy(settings if settings is not None else old['settings']),
                     '_generation': old['_generation']}
            self._validate(state)
            if old != state:
                self._snapshot(old, label)
                state['_generation'] = uuid.uuid4().hex
                atomic_save_json(self.meta / 'pending.json', state)
                self._recover()
            return {**state, 'revision': _revision(state)}

    def versions(self):
        with self.locked():
            items = [_read(p) for p in (self.meta / 'versions').glob('*.json')]
            return sorted([{k: x[k] for k in ('id', 'label', 'created', 'revision')} for x in items],
                          key=lambda x: x['created'], reverse=True)

    def restore(self, version, expected_revision):
        if not isinstance(version, str) or len(version) != 32 or any(c not in '0123456789abcdef' for c in version):
            raise ValueError('Invalid version')
        state = _read(self.meta / 'versions' / (version + '.json'))
        return self.save(state['storyboard'], state['settings'], expected_revision, label='Before restore')


def snapshot(project_dir, label='Before replan', expected_revision=None):
    return ProjectStore(project_dir).snapshot(label, expected_revision)

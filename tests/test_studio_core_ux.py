"""New Studio UX acceptance: direct adapters and actual JS handlers; no sockets/accounts."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import uuid
import zipfile

import pytest

from kinodraw import pipeline
from kinodraw.director.llm.providers import ProviderError
from kinodraw.project_store import ProjectStore
from kinodraw.project_zip import export_project, MANIFEST
from kinodraw.studio import integration, server

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/overnight-2026-10-05/evidence/studio-core-ux' / os.environ.get('STUDIO_CORE_UX_RUN', 'checks')
EVIDENCE.mkdir(parents=True, exist_ok=True)


def hashes(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


@pytest.fixture
def saved_archive(tmp_path, monkeypatch):
    from test_native_pipeline import saved_native_project
    root = tmp_path / 'projects'; root.mkdir()
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'isolated-config.json')
    original = saved_native_project(tmp_path / 'original')
    saved = ProjectStore(original).load()
    saved['settings'].update(recording='recording.wav', speed=1.1,
                             plan_v3_report={'provider': 'injected', 'fallback': False})
    ProjectStore(original).save(saved['storyboard'], saved['settings'], saved['revision'])
    (original / 'recording.wav').write_bytes((original / 'build/narration.wav').read_bytes())
    (original / 'doodles/gen-worker.json').write_text('{"source":"local acceptance","license":"fixture"}\n')
    archive = tmp_path / 'saved.zip'; export_project(original, archive)
    return root, original, archive


@pytest.mark.parametrize('scenario', ['eta', 'writer', 'writer-conflict', 'writer-late-edit',
                                     'writer-error', 'writer-unavailable', 'import', 'starters', 'thumbnails'])
def test_actual_studio_handlers(scenario, saved_archive):
    node = shutil.which('node'); assert node, 'Node required for actual-handler acceptance'
    result = subprocess.run([node, str(ROOT / 'tests/studio_core_ux_harness.js'), scenario,
                             str(saved_archive[2])], cwd=ROOT, capture_output=True, text=True, timeout=15)
    (EVIDENCE / ('node-' + scenario + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr


def test_writer_real_integration_grounding_and_usage(monkeypatch):
    seen = []
    class Provider:
        name = 'injected'
        def write_draft(self, payload, usage):
            seen.append(payload); usage.add('injected-model', 10, 5)
            return {'title': 'Sales', 'sections': [{'heading': 'Change',
                    'paragraphs': ['Sales rose 12%.'], 'source_notes': [0]}]}
    monkeypatch.setitem(server.STUDIO_HOOKS, 'provider', lambda body: Provider())
    result = integration.writer({'topic': 'Sales', 'notes': ' Sales rose 12%.\n', 'voice': 'Short sentences.'})
    assert result['ok'] and result['usage']['calls'] == 1
    assert result['text'] == '# Sales\n\n## Change\n\nSales rose 12%.\n'
    assert seen == [{'topic': 'Sales', 'notes': ['Sales rose 12%.'], 'voice': 'Short sentences.'}]
    with pytest.raises(ValueError, match='source notes'):
        integration.writer({'topic': 'Sales', 'notes': ''})
    class Invented(Provider):
        def write_draft(self, payload, usage):
            answer = super().write_draft(payload, usage)
            answer['sections'][0]['paragraphs'] = ['Sales rose 99%.']
            return answer
    monkeypatch.setitem(server.STUDIO_HOOKS, 'provider', lambda body: Invented())
    rejected = integration.writer({'topic': 'Sales', 'notes': 'Sales rose 12%.'})
    assert not rejected['ok'] and 'number' in rejected['error'] and rejected['usage']['calls'] == 1
    monkeypatch.setitem(server.STUDIO_HOOKS, 'provider', lambda body: 'rules')
    with pytest.raises(ValueError, match='support'):
        integration.writer({'topic': 'Sales', 'notes': 'Sales rose 12%.'})


def test_import_lossless_then_actual_project_reopen(saved_archive):
    root, original, archive = saved_archive
    before = hashes(original)
    result = integration.importzip(io.BytesIO(archive.read_bytes()), archive.stat().st_size)
    restored = root / result['project']
    assert restored.parent == root and restored.name.startswith('Imported-')
    assert hashes(restored) == before and hashes(original) == before
    assert server._project(restored.name) == restored
    reopened = server._store(restored).load()
    original_state = ProjectStore(original).load()
    assert reopened == original_state
    assert reopened['settings']['plan_v3']['cast']
    assert reopened['settings']['recording'] == 'recording.wav'
    assert reopened['settings']['plan_v3_report']['provider'] == 'injected'
    assert not server._summary(restored).get('broken')
    assert server._summary(restored)['title'] == original_state['storyboard']['title']['en']
    (EVIDENCE / 'saved-project.zip').write_bytes(archive.read_bytes())
    (EVIDENCE / 'zip-roundtrip.json').write_text(json.dumps({'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'archive_bytes': archive.stat().st_size, 'file_hashes': before, 'imported': result, 'reopened_revision': reopened['revision']}, indent=2) + '\n')


def rewritten(archive, change):
    output = io.BytesIO()
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(output, 'w') as dst:
        for info in src.infolist():
            value = change(info.filename, src.read(info))
            if value is not None: dst.writestr(info, value)
    return output.getvalue()


@pytest.mark.parametrize('kind', ['traversal', 'symlink', 'special', 'duplicate', 'tampered',
    'missing', 'missing-manifest', 'invalid-state', 'pending', 'bad-recording', 'invalid-plan', 'oversized', 'truncated', 'bad-zip'])
def test_import_rejections_leave_projects_untouched(saved_archive, kind, tmp_path, monkeypatch):
    root, original, archive = saved_archive
    keep = root / 'unrelated'; keep.mkdir(); (keep / 'keep').write_bytes(b'unrelated bytes')
    before = hashes(root); source_before = hashes(original)
    data = archive.read_bytes(); length = len(data)
    if kind in ('pending', 'bad-recording', 'invalid-plan', 'invalid-state'):
        if kind == 'pending':
            (original / '.studio/pending.json').write_text('{"settings":{"lang":"zh"},"storyboard":{}}')
        else:
            state = json.loads((original / 'project.json').read_text())
            if kind == 'bad-recording': state['recording'] = '../outside.wav'
            if kind == 'invalid-plan': state['plan_v3'] = {'cast': 'invalid'}
            if kind == 'invalid-state': state = []
            (original / 'project.json').write_text(json.dumps(state))
        changed = tmp_path / 'changed.zip'; export_project(original, changed)
        data = changed.read_bytes(); length = len(data); source_before = hashes(original)
    elif kind in ('traversal', 'symlink', 'special', 'duplicate'):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as z:
            info = zipfile.ZipInfo('../escape' if kind == 'traversal' else 'entry')
            if kind in ('symlink', 'special'): info.external_attr = (stat.S_IFLNK if kind == 'symlink' else stat.S_IFIFO) << 16
            z.writestr(info, b'bad')
            if kind == 'duplicate': z.writestr(info, b'bad')
        data = output.getvalue(); length = len(data)
    elif kind == 'tampered': data = rewritten(archive, lambda n, b: b'changed' if n == 'recording.wav' else b); length = len(data)
    elif kind in ('missing', 'missing-manifest'):
        data = rewritten(archive, lambda n, b: None if n == ('project.json' if kind == 'missing' else MANIFEST) else b); length = len(data)
    elif kind == 'oversized': length = integration.IMPORT_MAX_BYTES + 1
    elif kind == 'truncated': data = data[:-7]
    elif kind == 'bad-zip': data = b'not a zip'; length = len(data)
    class Stream(io.BytesIO):
        reads = 0
        def read(self, n=-1):
            self.reads += 1
            assert 0 <= n <= 1024 * 1024, 'unbounded request read'
            return super().read(n)
    stream = Stream(data)
    with pytest.raises(ValueError): integration.importzip(stream, length)
    if kind == 'oversized': assert stream.reads == 0
    assert hashes(root) == before and hashes(original) == source_before
    assert sorted(p.name for p in root.iterdir()) == ['unrelated']


@pytest.mark.parametrize('length', [None, '', 'garbage', -1, 0])
def test_import_invalid_length_does_not_read(saved_archive, length):
    class Unread:
        def read(self, *args): pytest.fail('invalid length read body')
    with pytest.raises(ValueError): integration.importzip(Unread(), length)


def test_import_raced_destination_is_never_replaced(saved_archive, monkeypatch):
    import kinodraw.project_zip as library
    root, original, archive = saved_archive
    fixed = uuid.UUID('f9a7e2ee-5ee9-4018-bfc1-9e181d64a301')
    monkeypatch.setattr(integration.uuid, 'uuid4', lambda: fixed)
    destination = root / ('Imported-' + fixed.hex)
    rename = library._rename_noreplace
    def race(source, target):
        if target == destination:
            target.mkdir(); (target / 'keep').write_bytes(b'raced directory preserved')
        return rename(source, target)
    monkeypatch.setattr(library, '_rename_noreplace', race)
    with pytest.raises(ValueError, match='destination appeared'):
        integration.importzip(io.BytesIO(archive.read_bytes()), archive.stat().st_size)
    assert hashes(destination) == {'keep': hashlib.sha256(b'raced directory preserved').hexdigest()}
    assert sorted(p.name for p in root.iterdir()) == [destination.name]

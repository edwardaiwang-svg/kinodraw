import hashlib
import json
from pathlib import Path
import stat
import zipfile

import pytest
from kinodraw.project_zip import export_project, import_project, MANIFEST


def project(root):
    root.mkdir()
    (root/'project.json').write_text(json.dumps({'plan_v3': {'scenes': [1,2]}, 'bible': {'actor':'Ada'}, 'speed':1.2}), encoding='utf-8')
    (root/'storyboard.json').write_text('{"saved":true}', encoding='utf-8')
    (root/'doodles').mkdir()
    (root/'doodles'/'own.svg').write_text('<svg/>', encoding='utf-8')
    (root/'recording.wav').write_bytes(b'original narration')
    return root


def test_lossless_saved_v3_roundtrip(tmp_path):
    original = project(tmp_path/'original')
    archive = tmp_path/'project.zip'
    manifest = export_project(original, archive)
    restored = tmp_path/'restored'
    assert import_project(archive, restored) == manifest
    for path in original.rglob('*'):
        if path.is_file():
            assert (restored/path.relative_to(original)).read_bytes() == path.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        import_project(archive, restored)
    for path in original.rglob('*'):
        if path.is_file():
            assert (restored/path.relative_to(original)).read_bytes() == path.read_bytes()


@pytest.mark.parametrize('kind', ['empty-directory', 'directory', 'file', 'symlink', 'dangling-symlink'])
def test_pre_publication_race_preserves_destination(tmp_path, monkeypatch, kind):
    original = project(tmp_path/'original')
    archive = tmp_path/'project.zip'
    export_project(original, archive)
    archive_bytes = archive.read_bytes()
    destination = tmp_path/'out'
    unrelated = tmp_path/'unrelated'
    unrelated.write_bytes(b'keep unrelated file')
    is_symlink = Path.is_symlink
    checks = 0
    identity = None

    def race(path):
        nonlocal checks, identity
        result = is_symlink(path)
        if path == destination:
            checks += 1
            if checks == 2:
                # Create the target after the final pre-publication check.
                assert not result and not path.exists()
                if kind in ('empty-directory', 'directory'):
                    path.mkdir()
                    if kind == 'directory':
                        (path/'keep').write_bytes(b'keep directory contents')
                elif kind == 'file':
                    path.write_bytes(b'keep target file')
                else:
                    path.symlink_to(unrelated if kind == 'symlink' else tmp_path/'missing')
                info = path.lstat()
                identity = (info.st_dev, info.st_ino)
        return result

    monkeypatch.setattr(Path, 'is_symlink', race)
    try:
        with pytest.raises(ValueError, match='destination appeared'):
            import_project(archive, destination)
    finally:
        assert identity is not None, 'race was not injected'
        info = destination.lstat()
        assert (info.st_dev, info.st_ino) == identity
        if kind in ('empty-directory', 'directory'):
            assert sorted(p.name for p in destination.iterdir()) == ([] if kind == 'empty-directory' else ['keep'])
            if kind == 'directory':
                assert (destination/'keep').read_bytes() == b'keep directory contents'
        elif kind == 'file':
            assert destination.read_bytes() == b'keep target file'
        else:
            assert destination.readlink() == (unrelated if kind == 'symlink' else tmp_path/'missing')
        assert unrelated.read_bytes() == b'keep unrelated file'
        assert archive.read_bytes() == archive_bytes
        assert not list(tmp_path.glob('.zip-import-*'))


@pytest.mark.parametrize('entries', [
    ('Readme', 'readme/child'),
    ('Assets/one', 'assets/two'),
    ('caf\u00e9/one', 'cafe\u0301/two'),
    ('assets/Icons/one', 'assets/icons/two'),
])
@pytest.mark.parametrize('reverse', [False, True])
def test_normalized_path_aliases_rejected_before_extraction(tmp_path, monkeypatch, entries, reverse):
    archive = tmp_path/'aliases.zip'
    files = {'project.json': b'{}', 'storyboard.json': b'{}'}
    files.update((name, b'original bytes') for name in (reversed(entries) if reverse else entries))
    manifest = {'format': 'kinodraw-project', 'version': 1, 'files': {
        name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in files.items()}}
    with zipfile.ZipFile(archive, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr(MANIFEST, json.dumps(manifest).encode('utf-8'))
    archive_bytes = archive.read_bytes()
    opened = []
    zip_open = zipfile.ZipFile.open

    def record_open(z, *args, **kwargs):
        opened.append(args[0])
        return zip_open(z, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'open', record_open)
    with pytest.raises(ValueError, match='alias|conflict'):
        import_project(archive, tmp_path/'out')
    assert opened == [], 'validation must reject aliases before reading/extracting entries'
    assert not (tmp_path/'out').exists()
    assert not list(tmp_path.glob('.zip-import-*'))
    assert archive.read_bytes() == archive_bytes


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/../../escape', 'a\\evil', 'C:evil', 'a/./b'])
def test_traversal(tmp_path, name):
    archive = tmp_path/'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(name, 'bad')
    with pytest.raises(ValueError, match='unsafe'):
        import_project(archive, tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_symlink_duplicate_bomb_and_limits(tmp_path):
    for kind in ('symlink','duplicate','bomb','limit'):
        archive = tmp_path/f'{kind}.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            if kind == 'symlink':
                i = zipfile.ZipInfo('link')
                i.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(i, 'target')
            elif kind == 'duplicate':
                z.writestr('same', 'a')
                z.writestr('same', 'b')
            else:
                z.writestr('huge', b'0'*100000)
        with pytest.raises(ValueError):
            import_project(archive, tmp_path/kind, max_bytes=10 if kind=='limit' else 1000000)
        assert not (tmp_path/kind).exists()


def test_hash_tamper_and_project_symlink(tmp_path):
    original = project(tmp_path/'original')
    archive = tmp_path/'good.zip'
    export_project(original, archive)
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(tmp_path/'tamper.zip','w') as dst:
        for i in src.infolist():
            dst.writestr(i, b'changed' if i.filename=='recording.wav' else src.read(i))
    with pytest.raises(ValueError, match='size|hash'):
        import_project(tmp_path/'tamper.zip', tmp_path/'out')
    (original/'link').symlink_to(original/'project.json')
    with pytest.raises(ValueError, match='symlink'):
        export_project(original, tmp_path/'bad.zip')

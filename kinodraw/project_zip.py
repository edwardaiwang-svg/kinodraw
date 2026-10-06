"""Project archives with bounded, verified, transactional import."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import unicodedata
import zipfile

from .director import PROVIDER_INPUTS

MANIFEST = 'kinodraw-manifest.json'
MAX_FILES = 10000
MAX_BYTES = 2 * 1024 ** 3
MAX_RATIO = 200


def _name(name):
    p = PurePosixPath(name)
    if (not name or '\\' in name or '\x00' in name or ':' in name or p.is_absolute()
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError(f'unsafe archive path: {name!r}')
    return p


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _rename_noreplace(source, destination):
    """Publish atomically without replacing even a raced empty directory."""
    if os.name == 'nt':
        os.rename(source, destination)
        return
    if sys.platform not in ('darwin', 'linux'):
        raise RuntimeError('atomic no-replace rename is unsupported')
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = getattr(libc, 'renamex_np', None)
        if rename is None:
            raise RuntimeError('atomic no-replace rename is unavailable')
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    else:
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise RuntimeError('atomic no-replace rename is unavailable')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def export_project(project, output, *, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    """Include all regular project files, including saved v3 state and recordings.

    No regeneration; omit executable, endpoint and auth settings. Output must be outside the project.
    """
    project, output = Path(project).resolve(), Path(output).absolute()
    if output.resolve().is_relative_to(project):
        raise ValueError('archive output must be outside project')
    files, total = [], 0
    for root, dirs, names in os.walk(project, followlinks=False):
        for name in dirs + names:
            if (Path(root) / name).is_symlink():
                raise ValueError('project symlinks are not supported')
        for name in names:
            path = Path(root) / name
            if not path.is_file():
                raise ValueError('project contains a special file')
            rel = path.relative_to(project).as_posix()
            _name(rel)
            if rel == MANIFEST:
                raise ValueError('reserved manifest name')
            total += path.stat().st_size
            files.append((rel, path))
            if len(files) > max_files or total > max_bytes:
                raise ValueError('project exceeds archive limits')
    if not {'project.json', 'storyboard.json'} <= {name for name, _ in files}:
        raise ValueError('project.json and storyboard.json required')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.zip-export-', dir=output.parent) as work:
        temp = Path(work) / 'project.zip'
        manifest = {'format': 'kinodraw-project', 'version': 1, 'files': {}}
        # Stored entries avoid producing an archive rejected by our bomb ratio bound.
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED) as z:
            for rel, path in sorted(files):
                if rel == 'project.json':
                    cfg = json.loads(path.read_text(encoding='utf-8'))
                    if isinstance(cfg, dict) and any(key in cfg for key in PROVIDER_INPUTS):
                        data = (json.dumps({k: v for k, v in cfg.items() if k not in PROVIDER_INPUTS},
                                           ensure_ascii=False, indent=2) + '\n').encode('utf-8')
                        z.writestr(rel, data)
                        manifest['files'][rel] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                        total += len(data) - path.stat().st_size
                        continue
                z.write(path, rel)
                manifest['files'][rel] = {'size': path.stat().st_size, 'sha256': _hash(path)}
            metadata = json.dumps(manifest, sort_keys=True).encode('utf-8')
            if len(files) + 1 > max_files or total + len(metadata) > max_bytes or len(metadata) > 1024 * 1024:
                raise ValueError('project and manifest exceed archive limits')
            z.writestr(MANIFEST, metadata)
        # Validate the snapshot too: concurrent edits cannot produce a false manifest.
        import_project(temp, Path(work) / 'verify', max_files=max_files, max_bytes=max_bytes)
        temp.replace(output)
    return manifest


def import_project(archive, destination, *, max_files=MAX_FILES, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO):
    """Reject hostile paths/types/duplicates/bombs/hashes before installing.

    Destination must not exist. Extraction is staged in a sibling directory.
    """
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > max_files or sum(i.file_size for i in infos) > max_bytes:
            raise ValueError('archive exceeds limits')
        names = set()
        folded = set()
        prefixes = {}
        for info in infos:
            parts = _name(info.filename).parts
            # Case-insensitive filesystems must not alias entries.
            key = unicodedata.normalize('NFC', info.filename).casefold()
            if key in folded:
                raise ValueError('duplicate archive entry')
            folded.add(key)
            names.add(info.filename)
            for i in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:i])
                key = unicodedata.normalize('NFC', prefix).casefold()
                if prefixes.setdefault(key, prefix) != prefix:
                    raise ValueError('archive path component alias')
            mode = info.external_attr >> 16
            if info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError('archive contains non-regular entry')
            if info.flag_bits & 1 or info.file_size > max_ratio * max(1, info.compress_size):
                raise ValueError('encrypted entry or compression bomb')
        for name in names:
            if any('/'.join(name.split('/')[:i]) in names for i in range(1, len(name.split('/')))):
                raise ValueError('archive file conflicts with directory')
        if MANIFEST not in names or z.getinfo(MANIFEST).file_size > 1024 * 1024:
            raise ValueError('missing or oversized manifest')
        try:
            manifest = json.loads(z.read(MANIFEST))
            if manifest['format'] != 'kinodraw-project' or manifest['version'] != 1:
                raise ValueError('unsupported project archive')
            expected = manifest['files']
            if not isinstance(expected, dict) or set(expected) != names - {MANIFEST}:
                raise ValueError('manifest entries differ')
            if not {'project.json', 'storyboard.json'} <= set(expected):
                raise ValueError('missing project state')
            for info in infos:
                if info.filename != MANIFEST and expected[info.filename]['size'] != info.file_size:
                    raise ValueError('manifest size differs')
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('invalid manifest') from exc
        with tempfile.TemporaryDirectory(prefix='.zip-import-', dir=destination.parent) as work:
            stage = Path(work) / 'project'
            stage.mkdir()
            count = 0
            for info in infos:
                if info.filename == MANIFEST:
                    continue
                path = stage / info.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with z.open(info) as src, path.open('xb') as dst:
                    for chunk in iter(lambda: src.read(1024 * 1024), b''):
                        count += len(chunk)
                        if count > max_bytes:
                            raise ValueError('extracted bytes exceed limits')
                        dst.write(chunk)
                        h.update(chunk)
                if h.hexdigest() != expected[info.filename]['sha256']:
                    raise ValueError('manifest hash differs')
            if destination.exists() or destination.is_symlink():
                raise ValueError('destination appeared during import')
            try:
                _rename_noreplace(stage, destination)
            except FileExistsError as exc:
                raise ValueError('destination appeared during import') from exc
    return manifest

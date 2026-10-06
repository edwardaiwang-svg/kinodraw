"""Actual local pack flow and the helper's file/action boundaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import pytest
from kinodraw.mcp_server import Developer
from kinodraw.project_zip import export_project

SPEC = importlib.util.spec_from_file_location('package_gallery', Path(__file__).resolve().parents[1] / 'scripts/package_gallery.py')
gallery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gallery)


def input_pack(root):
    service = Developer(str(root))
    service.create_project('project', script='# Illustrative preview\n\nThe sun warms the Earth.', lang='en')
    try:
        job = service.render('project', duration=.1)
        deadline = time.monotonic() + 90
        while True:
            status = service.status(job['job'])
            if status['state'] != 'running':
                break
            assert time.monotonic() < deadline, status
            time.sleep(.02)
        assert status['state'] == 'succeeded', status
        assert status['exit_code'] == 0
        video = Path(status['path']).relative_to(root).as_posix()
    finally:
        service.close()
    (root / 'script.md').write_text('# Illustrative preview\n\nThe sun warms the Earth.\n', encoding='utf-8')
    (root / 'captions.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:00.100\nIllustrative synthetic preview, not measured narration.\n', encoding='utf-8')
    (root / 'description.md').write_text('Short synthetic preview for package integrity checks.\n', encoding='utf-8')
    export_project(root / 'project', root / 'project.zip')
    data = {'version': 1, 'entries': [dict(id='explainer', video=video, script='script.md', project='project.zip', captions='captions.vtt', description='description.md')]}
    manifest = root / 'input.json'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    return manifest, data


def test_real_synthetic_video_pack_has_exact_hashes_and_local_links(tmp_path):
    manifest, _ = input_pack(tmp_path)
    output = tmp_path / 'delivery'
    result = gallery.package(manifest, tmp_path, output, partial=True)
    assert result['partial'] is True
    assert result['entries'][0]['title'] == 'Illustrative preview'
    assert result['entries'][0]['verification']['decoded_frames'] == 3
    assert result['entries'][0]['verification']['decode_exit'] == 0
    for rel, record in result['files'].items():
        path = output / rel
        assert path.is_file() and path.stat().st_size == record['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
    page = (output / 'index.html').read_text(encoding='utf-8')
    assert 'Partial verification pack' in page
    import re
    for link in re.findall(r'(?:href|src|poster)="([^"]+)"', page):
        if not link.startswith('#'):
            assert (output / link).is_file(), link
    assert '<video controls' in page and '<track kind="captions"' in page
    with pytest.raises(ValueError, match='already exists'):
        gallery.package(manifest, tmp_path, output, partial=True)


def test_final_pack_requires_all_five_not_placeholder_entries(tmp_path):
    manifest = tmp_path / 'input.json'
    manifest.write_text(json.dumps({'version': 1, 'entries': [{'id': 'lion'}]}), encoding='utf-8')
    with pytest.raises(ValueError, match='requires exactly'):
        gallery.package(manifest, tmp_path, tmp_path / 'delivery')
    assert not (tmp_path / 'delivery').exists()


@pytest.mark.parametrize('name', ['../escape.mp4', '/tmp/movie.mp4', '.env', 'a/../movie.mp4', 'a\\movie.mp4', 'a//movie.mp4'])
def test_unsafe_source_paths_are_refused(tmp_path, name):
    with pytest.raises(ValueError):
        gallery.source_path(tmp_path, name)


def test_missing_and_symlink_files_are_refused(tmp_path):
    with pytest.raises(ValueError, match='missing'):
        gallery.source_path(tmp_path, 'absent.mp4')
    (tmp_path / 'video.mp4').write_bytes(b'x')
    (tmp_path / 'alias.mp4').symlink_to(tmp_path / 'video.mp4')
    with pytest.raises(ValueError, match='symlink'):
        gallery.source_path(tmp_path, 'alias.mp4')


def test_mismatched_source_does_not_publish_a_pack(tmp_path):
    manifest, _ = input_pack(tmp_path)
    (tmp_path / 'script.md').write_text('A different source.', encoding='utf-8')
    with pytest.raises(ValueError, match='differs from the project ZIP'):
        gallery.package(manifest, tmp_path, tmp_path / 'delivery', partial=True)
    assert not (tmp_path / 'delivery').exists()

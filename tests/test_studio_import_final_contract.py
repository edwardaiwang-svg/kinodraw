"""Actual import/reopen/render failures for final Studio review; no sockets/encoding."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from kinodraw import ingest, script
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline
from kinodraw.library import resolve
from kinodraw.project_store import ProjectStore
from kinodraw.project_zip import export_project
from kinodraw.studio import integration, server
from test_studio_import_contract import hashes, reopen

OUT = Path(__file__).resolve().parents[1] / 'docs/overnight-2026-10-05/evidence/studio-core-ux/import-final-contract-repair/regressions'
OUT.mkdir(parents=True, exist_ok=True)


def actual_video_ui(payload):
    node = shutil.which('node')
    assert node
    product = Path(integration.__file__).parent / 'static/app.js'
    code = """const fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();
const doc={querySelector:sel=>{if(!nodes.has(sel))nodes.set(sel,{innerHTML:''});return nodes.get(sel)},querySelectorAll:()=>[],addEventListener(){}};
const c=vm.createContext({window:{STUDIO_TOKEN:'test-token',addEventListener(){}},document:doc,console});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);
const input=JSON.parse(fs.readFileSync(0,'utf8'));
vm.runInContext('renderVideo('+JSON.stringify(input)+');',c);
"""
    return subprocess.run([node, '-e', code, str(product)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize('kind', ['qa-shape', 'missing-scene-picture', 'empty-storyboard'])
def test_incompatible_zip_is_rejected_before_publication(tmp_path, monkeypatch, kind):
    root = tmp_path / 'projects'
    root.mkdir()
    keep = root / 'unrelated'
    keep.mkdir()
    (keep / 'keep.txt').write_text('Existing project stays intact.')
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'config.json')
    board = script.build(ingest.read('# Import\n\nA clear idea is ready.'), story='story')
    cfg = {'lang': 'en', 'voice': 'am_michael', 'aspect': '16:9'}
    if kind == 'missing-scene-picture':
        plan = from_rules(board)
        plan['style'].update(mode='hybrid', music_mood='none')
        for scene in plan['scenes']:
            scene.update(treatment='motion', camera='static', actions=[],
                         elements=[{'kind': 'picture', 'ref': 'missing-prop'}],
                         text={'kind': 'none', 'ref': ''})
        cfg.update(director_v3=True, plan_v3=plan)
    elif kind == 'empty-storyboard':
        board = {'lang': 'en', 'title': {'en': 'Import'}, 'chapters': [], 'beats': []}
    source = tmp_path / 'source'
    ProjectStore(source).initialize(board, cfg)
    if kind == 'qa-shape':
        (source / 'build').mkdir()
        (source / 'build/qa.json').write_text('{"ok":false,"problems":null}\n')
        # Existing UI chooses the video by its filename, before any playback/decoding.
        (source / 'Import.mp4').write_bytes(b'filename-only UI fixture; not a decoded video')
    archive = tmp_path / 'project.zip'
    export_project(source, archive)
    data, root_before, source_before = archive.read_bytes(), hashes(root), hashes(source)
    report = {'scenario': kind, 'archive_sha256': hashlib.sha256(data).hexdigest(),
              'source_before': source_before}
    try:
        result = integration.importzip(io.BytesIO(data), len(data))
    except ValueError as error:
        report.update(rejected=True, error=str(error), projects_unchanged=hashes(root) == root_before,
                      source_unchanged=hashes(source) == source_before)
        (OUT / (kind + '.json')).write_text(json.dumps(report, indent=2) + '\n')
        assert hashes(root) == root_before and hashes(source) == source_before
        assert archive.read_bytes() == data
        return
    response = reopen(result['project'])
    report.update(rejected=False, imported=result, reopen_code=response['code'])
    if kind == 'qa-shape':
        ui = actual_video_ui(response['data'])
        report.update(ui_exit=ui.returncode, ui_stdout=ui.stdout, ui_stderr=ui.stderr)
        assert ui.returncode != 0 and 'join' in ui.stderr and 'null' in ui.stderr
    elif kind == 'missing-scene-picture':
        imported = root / result['project']
        assert resolve('missing-prop', imported) is None
        timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
        prod = render.make_production(board, timing, 'en', imported)
        at = prod.spans[0].start + .7
        image = prod.frame(at)
        image.save(OUT / 'missing-picture.png')
        report.update(warnings=prod.warnings, element_kinds=[e.kind for e in prod.spans[0].motion.elements],
                      actual_frame_size=image.size)
        assert any('missing prop missing-prop' in w for w in prod.warnings)
        assert not any(e.kind == 'picture' for s in prod.spans for e in s.motion.elements)
    else:
        state = response['data']['storyboard']
        report.update(chapter_count=len(state['chapters']), beat_count=len(state['beats']))
        assert state['chapters'] == state['beats'] == []
    report.update(source_unchanged=hashes(source) == source_before, archive_unchanged=archive.read_bytes() == data)
    (OUT / (kind + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    pytest.fail('Incompatible ' + kind + ' archive published; reject before destination creation')


@pytest.mark.parametrize('ref', ['book_stack', 'custom-prop', 'gen-worker', 'own:chosen.svg'])
def test_saved_scene_assets_and_warning_qa_remain_lossless(tmp_path, monkeypatch, ref):
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'config.json')
    board = script.build(ingest.read('# Import\n\nA clear idea is ready.'), story='story')
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', music_mood='none')
    for scene in plan['scenes']:
        scene.update(treatment='motion', camera='static', actions=[],
                     elements=[{'kind': 'picture', 'ref': ref}],
                     text={'kind': 'none', 'ref': ''})
    cfg = {'lang': 'en', 'voice': 'am_michael', 'aspect': '16:9',
           'director_v3': True, 'plan_v3': plan}
    source = tmp_path / 'source'
    ProjectStore(source).initialize(board, cfg)
    fixture = Path(__file__).parent / 'fixtures/native_saved_project/doodles/gen-worker.svg'
    if ref != 'book_stack':
        asset = source / ('pictures/chosen.svg' if ref.startswith('own:') else f'doodles/{ref}.svg')
        asset.parent.mkdir()
        asset.write_bytes(fixture.read_bytes())
        if ref.startswith('gen-'):
            asset.with_suffix('.json').write_bytes(b'{ "source": "local fixture", "license": "fixture" }\n')
    (source / 'build').mkdir()
    qa_bytes = b'{ "ok": false, "problems": ["Retained fixture warning"], "extra": "retained" }\n'
    (source / 'build/qa.json').write_bytes(qa_bytes)
    (source / 'Import.mp4').write_bytes(b'filename-only UI fixture; not a decoded video')
    archive = tmp_path / 'project.zip'
    export_project(source, archive)
    data, before = archive.read_bytes(), hashes(source)
    result = integration.importzip(io.BytesIO(data), len(data))
    imported = root / result['project']
    assert hashes(imported) == before and hashes(source) == before
    assert archive.read_bytes() == data
    assert (imported / 'build/qa.json').read_bytes() == qa_bytes
    response = reopen(result['project'])
    assert response['code'] == 200 and response['data']['settings'] == cfg
    ui = actual_video_ui(response['data'])
    assert ui.returncode == 0, ui.stdout + ui.stderr
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    prod = render.make_production(board, timing, 'en', imported)
    assert not any('missing prop' in warning for warning in prod.warnings)
    assert all(any(element.kind == 'picture' for element in span.motion.elements) for span in prod.spans)


@pytest.mark.parametrize('qa', [None, [], {}, {'ok': 'false', 'problems': []},
    {'ok': False, 'problems': 'warning'}, {'ok': False, 'problems': [None]}])
def test_invalid_saved_qa_shapes_stay_private(tmp_path, monkeypatch, qa):
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    board = script.build(ingest.read('# Import\n\nA clear idea is ready.'), story='story')
    source = tmp_path / 'source'
    ProjectStore(source).initialize(board, {'lang': 'en', 'voice': 'am_michael', 'aspect': '16:9'})
    (source / 'build').mkdir()
    (source / 'build/qa.json').write_text(json.dumps(qa))
    archive = tmp_path / 'project.zip'
    export_project(source, archive)
    data, before = archive.read_bytes(), hashes(source)
    with pytest.raises(ValueError, match='Saved QA'):
        integration.importzip(io.BytesIO(data), len(data))
    assert list(root.iterdir()) == [] and hashes(source) == before
    assert archive.read_bytes() == data


@pytest.mark.parametrize('field', ['chapters', 'beats'])
def test_either_empty_storyboard_array_stays_private(tmp_path, monkeypatch, field):
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    board = script.build(ingest.read('# Import\n\nA clear idea is ready.'), story='story')
    board[field] = []
    source = tmp_path / 'source'
    ProjectStore(source).initialize(board, {'lang': 'en', 'voice': 'am_michael', 'aspect': '16:9'})
    archive = tmp_path / 'project.zip'
    export_project(source, archive)
    data, before = archive.read_bytes(), hashes(source)
    with pytest.raises(ValueError, match='nonempty'):
        integration.importzip(io.BytesIO(data), len(data))
    assert list(root.iterdir()) == [] and hashes(source) == before
    assert archive.read_bytes() == data

"""Actual ZIP import/reopen contracts, without sockets, providers or user accounts."""
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
from kinodraw.project_store import ProjectStore
from kinodraw.project_zip import export_project
from kinodraw.studio import integration, server

OUT = Path(__file__).resolve().parents[1] / 'docs/overnight-2026-10-05/evidence/studio-core-ux/import-contract-repair/regressions'
OUT.mkdir(parents=True, exist_ok=True)


def hashes(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


def reopen(name):
    class Response:
        def _json(self, data, code=200):
            return {'code': code, 'data': data}
    return server.Handler._api(Response(), 'GET', ['projects', name], {})


def actual_board_ui(board):
    node = shutil.which('node')
    assert node, 'Actual Studio JavaScript requires Node'
    product = Path(integration.__file__).parent / 'static/app.js'
    code = """const fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(){this.innerHTML='';this.dataset={};this.children=[];this.nodes=new Map()}
  appendChild(child){this.children.push(child)}
  querySelector(sel){if(!this.nodes.has(sel))this.nodes.set(sel,new Element());return this.nodes.get(sel)}
  querySelectorAll(){return [new Element(),new Element()]}
  addEventListener(){}
  insertAdjacentHTML(where,html){this.innerHTML+=html}
}
const root=new Element();
const doc={querySelector:sel=>root.querySelector(sel),querySelectorAll:()=>[],addEventListener(){},createElement:()=>new Element()};
const c=vm.createContext({window:{STUDIO_TOKEN:'test-token',addEventListener(){}},document:doc,console});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);
const input=JSON.parse(fs.readFileSync(0,'utf8'));
vm.runInContext('board = '+JSON.stringify(input)+'; renderBoard();',c);
"""
    return subprocess.run([node, '-e', code, str(product)], input=json.dumps(board),
                          capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize('kind', ['missing-chapters', 'malformed-qa', 'invalid-v3-reference'])
def test_incompatible_archive_rejected_before_publication(tmp_path, monkeypatch, kind):
    root = tmp_path / 'projects'
    root.mkdir()
    keep = root / 'unrelated'
    keep.mkdir()
    (keep / 'keep.txt').write_text('Retain this existing project.')
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'isolated-config.json')
    source = tmp_path / 'source'
    board = script.build(ingest.read('# Import\n\nA clear idea is ready.'), story='story')
    cfg = {'lang': 'en', 'voice': 'am_michael', 'aspect': '16:9'}
    if kind == 'missing-chapters':
        board = {'lang': 'en', 'title': {'en': 'Import'}, 'beats': []}
    elif kind == 'invalid-v3-reference':
        plan = from_rules(board)
        plan['scenes'][0]['beat_ids'] = ['missing-beat']
        cfg.update(director_v3=True, plan_v3=plan)
    ProjectStore(source).initialize(board, cfg)
    if kind == 'malformed-qa':
        (source / 'build').mkdir()
        (source / 'build/qa.json').write_text('{not valid JSON\n')
    archive = tmp_path / 'project.zip'
    export_project(source, archive)
    source_before, root_before = hashes(source), hashes(root)
    data = archive.read_bytes()
    report = {'scenario': kind, 'archive_sha256': hashlib.sha256(data).hexdigest(),
              'archive_bytes': len(data), 'source_before': source_before}
    try:
        imported = integration.importzip(io.BytesIO(data), len(data))
    except ValueError as error:
        report.update(rejected=True, error=str(error), projects_unchanged=hashes(root) == root_before,
                      source_unchanged=hashes(source) == source_before)
        (OUT / (kind + '.json')).write_text(json.dumps(report, indent=2) + '\n')
        assert hashes(root) == root_before and hashes(source) == source_before
        assert archive.read_bytes() == data
        assert sorted(p.name for p in root.iterdir()) == ['unrelated']
        return
    report.update(rejected=False, imported=imported, published_files=hashes(root / imported['project']))
    if kind == 'missing-chapters':
        response = reopen(imported['project'])
        result = actual_board_ui(response['data']['storyboard'])
        report.update(reopen_code=response['code'], ui_exit=result.returncode,
                      ui_stdout=result.stdout, ui_stderr=result.stderr)
        assert result.returncode != 0 and 'board.chapters is not iterable' in result.stderr
    elif kind == 'malformed-qa':
        with pytest.raises(json.JSONDecodeError) as raised:
            reopen(imported['project'])
        report['reopen_error'] = str(raised.value)
    else:
        response = reopen(imported['project'])
        state = response['data']
        edit = copy.deepcopy(state['settings']['plan_v3'])
        edit['style']['reason'] += ' An ordinary editable explanation.'
        with pytest.raises(ValueError, match='Invalid plan') as raised:
            server.save_storyboard(imported['project'], state['storyboard'], state['revision'], edit)
        report.update(reopen_code=response['code'], ordinary_plan_save_error=str(raised.value))
    report['source_unchanged'] = hashes(source) == source_before
    (OUT / (kind + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    pytest.fail('Incompatible ' + kind + ' ZIP was published; actual reopen/edit failure retained. Reject privately before publication.')


@pytest.mark.parametrize('kind', ['null-chapters', 'object-chapters', 'missing-beats', 'null-beats',
    'object-beats', 'scalar-chapter', 'scalar-beat', 'duplicate-coverage', 'missing-coverage',
    'unknown-section', 'unknown-text', 'unknown-cast', 'unknown-action-beat'])
def test_unusable_containers_and_semantic_references_stay_private(tmp_path, monkeypatch, kind):
    root = tmp_path / 'projects'
    root.mkdir()
    (root / 'keep').mkdir()
    (root / 'keep/file').write_bytes(b'Existing bytes')
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'config.json')
    board = script.build(ingest.read('# Import\n\nMara, a lioness, nudged Pendo, a lion cub.'), story='story')
    cfg = {'lang': 'en', 'voice': 'am_michael', 'aspect': '16:9'}
    if kind in ('null-chapters', 'object-chapters', 'scalar-chapter'):
        board['chapters'] = {'null-chapters': None, 'object-chapters': {}, 'scalar-chapter': ['chapter']}[kind]
    elif kind == 'missing-beats':
        del board['beats']
    elif kind in ('null-beats', 'object-beats', 'scalar-beat'):
        board['beats'] = {'null-beats': None, 'object-beats': {}, 'scalar-beat': ['beat']}[kind]
    else:
        plan = from_rules(board)
        scene = plan['scenes'][0]
        if kind == 'duplicate-coverage':
            scene['beat_ids'] *= 2
        elif kind == 'missing-coverage':
            plan['scenes'] = []
        elif kind == 'unknown-section':
            plan['storyboard']['sections'][0]['section_id'] = 'missing-section'
        elif kind == 'unknown-text':
            scene['text'] = {'kind': 'caption_only', 'ref': 'missing-beat'}
        elif kind == 'unknown-cast':
            scene['elements'].append({'kind': 'cast', 'ref': 'missing-cast'})
        elif kind == 'unknown-action-beat':
            scene['actions'].append({'actor': 'mara', 'verb': 'nudge', 'at_beat': 'missing-beat', 'intensity': 1})
        cfg.update(director_v3=True, plan_v3=plan)
    source = tmp_path / 'source'
    ProjectStore(source).initialize(board, cfg)
    archive = tmp_path / 'project.zip'
    export_project(source, archive)
    data, root_before, source_before = archive.read_bytes(), hashes(root), hashes(source)
    with pytest.raises(ValueError):
        integration.importzip(io.BytesIO(data), len(data))
    assert hashes(root) == root_before and hashes(source) == source_before
    assert archive.read_bytes() == data
    assert sorted(p.name for p in root.iterdir()) == ['keep']


@pytest.mark.parametrize('kind', ['legacy-no-qa', 'v3-cached-prop', 'v3-cast-override'])
def test_valid_lossless_roundtrip_renders_reopens_and_edits(tmp_path, monkeypatch, kind):
    from kinodraw.director.validate import _doodles
    from kinodraw.director.v3.validate import validate as validate_plan
    root = tmp_path / 'projects'
    root.mkdir()
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'config.json')
    source = tmp_path / 'source'
    board = script.build(ingest.read('# Import\n\nMara, a lioness, watched Pendo, a lion cub.\n\nMara nudged Pendo.'), story='story')
    cfg = {'lang': 'en', 'voice': 'am_michael', 'speed': 1.1, 'aspect': '1:1', 'size': [1080, 1080]}
    if kind != 'legacy-no-qa':
        plan = from_rules(board)
        # A cached prop offered by saved scenes remains valid even without a board picture.
        plan['scenes'][-1]['elements'].append({'kind': 'picture', 'ref': 'gen-worker'})
        if kind == 'v3-cast-override':
            mara = next(c for c in plan['cast'] if c['name'] == 'Mara')
            assert mara['species'] == 'lioness'
            mara.update(species='tigress', marks=['stripes'])
        cfg.update(director_v3=True, plan_v3=plan, scene_treatments=copy.deepcopy(plan['scenes']),
                   series_bible={'cast': copy.deepcopy(plan['cast'])}, recording='recording.wav')
        # Prove the control exercises the validator path and a real phenotype repair.
        candidates = {b['id']: list(_doodles(b.get('visuals', []))) for b in board['beats']}
        for scene in plan['scenes']:
            for bid in scene['beat_ids']:
                candidates[bid].extend(e['ref'] for e in scene['elements'] if e['kind'] == 'picture')
        checked, repairs = validate_plan(plan, board, candidates)
        if kind == 'v3-cast-override':
            assert repairs and checked['cast'] != plan['cast']
        else:
            assert repairs == []
    ProjectStore(source).initialize(board, cfg)
    # Keep a manual picture and saved versions alongside the plan and native settings.
    state = ProjectStore(source).load()
    state['storyboard']['beats'][-1]['visuals'] = [{'id': 'manual-picture', 'type': 'cluster',
        'items': [{'doodle': 'book_stack'}], 'relation': 'none'}]
    ProjectStore(source).save(state['storyboard'], cfg, state['revision'])
    if kind != 'legacy-no-qa':
        fixture = Path(__file__).parent / 'fixtures/native_saved_project'
        (source / 'doodles').mkdir()
        (source / 'doodles/gen-worker.svg').write_bytes((fixture / 'doodles/gen-worker.svg').read_bytes())
        (source / 'doodles/gen-worker.json').write_text('{"source":"local fixture","license":"fixture"}\n')
        (source / 'recording.wav').write_bytes(b'retained cached recording bytes')
        (source / 'build').mkdir()
        (source / 'build/timeline.json').write_bytes((fixture / 'timeline.json').read_bytes())
        (source / 'build/qa.json').write_text('{ "ok": true, "problems": [], "retained": "exact QA bytes" }\n')
    archive = tmp_path / 'project.zip'
    export_project(source, archive)
    data, before = archive.read_bytes(), hashes(source)
    result = integration.importzip(io.BytesIO(data), len(data))
    restored = root / result['project']
    assert hashes(restored) == before and hashes(source) == before and archive.read_bytes() == data
    response = reopen(result['project'])
    assert response['code'] == 200
    state = response['data']
    assert state['storyboard'] == ProjectStore(source).load()['storyboard'] and state['settings'] == cfg
    ui = actual_board_ui(state['storyboard'])
    assert ui.returncode == 0, ui.stdout + ui.stderr
    edit = copy.deepcopy(state['storyboard'])
    edit['title']['en'] += ' edited'
    saved = server.save_storyboard(result['project'], edit, state['revision'], cfg.get('plan_v3'))
    assert saved['ok'] and saved['storyboard']['title']['en'].endswith(' edited')
    assert saved['settings'] == cfg
    if kind == 'v3-cached-prop':
        plan_edit = copy.deepcopy(cfg['plan_v3'])
        plan_edit['style']['reason'] += ' An ordinary editable explanation.'
        saved = server.save_storyboard(result['project'], saved['storyboard'], saved['revision'], plan_edit)
        assert saved['ok'] and saved['settings']['plan_v3'] == plan_edit
    reopened = reopen(result['project'])
    assert reopened['code'] == 200 and reopened['data']['storyboard'] == saved['storyboard']
    assert hashes(source) == before and archive.read_bytes() == data
    if kind == 'legacy-no-qa':
        assert reopened['data']['qa'] is None and not (restored / 'build/qa.json').exists()
    else:
        for name in ('doodles/gen-worker.svg', 'doodles/gen-worker.json', 'recording.wav', 'build/timeline.json', 'build/qa.json'):
            assert (restored / name).read_bytes() == (source / name).read_bytes()
    (OUT / (kind + '.json')).write_text(json.dumps({'archive_sha256': hashlib.sha256(data).hexdigest(),
        'file_hashes': before, 'imported': result, 'reopen_code': reopened['code'], 'ui_exit': ui.returncode,
        'source_unchanged': True, 'archive_unchanged': True, 'edit_ok': saved['ok']}, indent=2) + '\n')

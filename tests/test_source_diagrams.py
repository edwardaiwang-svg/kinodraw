"""Source instructions must cause literal diagrams, through the public v3 route."""
import copy
import hashlib
import json
import random
import subprocess
import sys

import numpy as np
import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.adapter import adapt
from kinodraw.director.v3.validate import validate
from kinodraw.engine import render, timeline

LESSON = '# A multiplication lesson\n\nPlace three rows of five dots on the board. Count the dots in each row.\n\nWrite the equation: three times five equals fifteen. Rotate the same dots to make five rows of three.\n\nPractice problem: does changing the order change the answer? Check your answer by counting again.'
LAUNCH = '# Introducing a simpler workspace\n\nIntroducing our new app: one workspace for ideas.\n\nPanels glide into place as you organize notes, tasks and drawings together.\n\nStart your next project today.'


def prepared(tmp_path, source, size=None, aspect='16:9'):
    board = script.build(ingest.read(source), story='showcase')
    board['beats'].insert(0, {'id': 'b000', 'chapter': 'main', 'kind': 'title',
        'display': {'en': board['title']['en'] + '.'}, 'spoken': {'en': board['title']['en'] + '.'}, 'visuals': []})
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    board, _ = adapt(plan, board)
    config = json.dumps({'director_v3': True, 'plan_v3': plan})
    (tmp_path / 'project.json').write_text(config)
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    original = copy.deepcopy((board, tl, plan))
    prod = render.make_production(board, tl, 'en', tmp_path, size=size, aspect=aspect)
    assert (board, tl, plan) == original
    assert (tmp_path / 'project.json').read_text() == config
    return board, plan, tl, prod


@pytest.mark.parametrize('source,count', [(LESSON, 15),
    (LESSON.replace('three', 'two').replace('five', 'four').replace('fifteen', 'eight'), 8),
    (LESSON.replace('three', 'four').replace('five', 'six').replace('fifteen', 'twenty-four'), 24)])
def test_rules_literal_proof(tmp_path, source, count):
    board, plan, tl, prod = prepared(tmp_path, source)
    refs = [e['ref'] for s in plan['scenes'] for e in s['elements'] if e['kind'] == 'diagram']
    assert refs == [b['id'] for b in board['beats'][1:]], 'icons cannot prove equal groups'
    from kinodraw.engine.source_diagrams import resolve
    specs = [resolve(board, ref) for ref in refs]
    assert all(s.total == count for s in specs)
    assert specs[1].equation == f'{specs[0].rows} × {specs[0].cols} = {count}'
    drawing = next(e.drawing for e in prod.els if e.group.startswith('diagram:'))
    rotate = drawing.events['rotate']
    states = [drawing.snapshot(t) for t in (rotate[0], sum(rotate)/2, rotate[1])]
    assert all(len(s['dots']) == count for s in states)
    assert len(set(states[0]['dots'])) == len(set(states[2]['dots'])) == count
    assert states[0]['dots'] != states[1]['dots'] != states[2]['dots']
    first = drawing.events['build']
    assert len(drawing.snapshot(first[0]-.01)['dots']) == 0
    assert 0 < len(drawing.snapshot(sum(first)/2)['dots']) < count
    assert len(drawing.snapshot(first[1])['dots']) == count
    array_element = next(e for e in prod.els if e.group.startswith('diagram:'))
    assert first == (array_element.start, array_element.end)
    assert array_element.state(array_element.end-.02)[1] is not None
    assert first[1] <= tl['beats'][array_element.beat]['speech_end']
    assert drawing.snapshot(drawing.events['count'][-1][0]-.01)['highlight'] is None
    assert drawing.snapshot(sum(drawing.events['count'][-1])/2)['highlight'] is not None
    assert drawing.snapshot(rotate[1])['equation'] == specs[1].equation
    times = [first[0]+.4, sum(first)/2, rotate[0], sum(rotate)/2, rotate[1], sum(drawing.events['count'][-1])/2]
    hashes = {t: hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in times}
    assert len(set(hashes.values())) == len(times)
    random.Random(9).shuffle(times)
    assert all(hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == hashes[t] for t in times)
    assert all(hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == hashes[t] for t in reversed(times))


@pytest.mark.parametrize('source,labels', [(LAUNCH, ('notes', 'tasks', 'drawings')),
    (LAUNCH.replace('notes, tasks and drawings', 'files, sketches and tasks'), ('files', 'sketches', 'tasks'))])
def test_panels_translate_source_labels(tmp_path, source, labels):
    board, plan, tl, prod = prepared(tmp_path, source)
    refs = [e['ref'] for s in plan['scenes'] for e in s['elements'] if e['kind'] == 'diagram']
    assert len(refs) == 1, 'organizing panels must not be a drifting pen'
    span = next(s for s in prod.spans if any(e['kind']=='diagram' for e in s.spec['elements']))
    diagram = span.diagram
    assert diagram.spec.labels == labels
    a, b = diagram.window
    boxes = [diagram.boxes(t) for t in (a, (a+b)/2, b)]
    assert boxes[0] != boxes[1] != boxes[2]
    assert all(abs(x[0]-y[0])+abs(x[1]-y[1]) > 100 for x,y in zip(boxes[0],boxes[2]))
    assert prod.frame(a+.1).tobytes() != prod.frame(b).tobytes()
    times = [a+.1, (a+b)/2, b]
    hashes = {t: hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in times}
    random.Random(13).shuffle(times)
    assert all(hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == hashes[t] for t in times)
    assert all(hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == hashes[t] for t in reversed(times))



@pytest.mark.parametrize('source', ['Draw twenty rows of twenty dots.', 'Draw two rows of four cats.',
    'Do not place three rows of five dots.', 'Panels glide as you organize unicorns and dragons.',
    'Place two rows of four dots. Write the equation: two times four equals nine.',
    'Place two rows of four dots. Rotate the same dots to make five rows of three.'])
def test_unsupported_references_rejected(source):
    board = script.build(ingest.read('# Lesson\n\n' + source), story='showcase')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['scenes'][-1]['elements'] = [{'kind': 'diagram', 'ref': board['beats'][-1]['id']}]
    fixed, repairs = validate(plan, board, {})
    assert not any(e['kind']=='diagram' for s in fixed['scenes'] for e in s['elements'])
    assert any('diagram' in r for r in repairs)


@pytest.mark.parametrize('size,aspect', [((1080,1080),'1:1'), ((3840,2160),'16:9')])
@pytest.mark.parametrize('source', [LESSON, LAUNCH])
def test_native_and_fresh_reconstruction(tmp_path, size, aspect, source):
    board, plan, tl, prod = prepared(tmp_path, source, size, aspect)
    if source == LESSON:
        drawing = next(e.drawing for e in prod.els if e.group.startswith('diagram:'))
        times = [sum(drawing.events['rotate'])/2, drawing.events['rotate'][1]]
    else:
        diagram = next(s.diagram for s in prod.spans if s.diagram)
        times = [sum(diagram.window)/2, diagram.window[1]]
    hashes = []
    for t in times:
        f = prod.frame(t)
        assert f.size == size
        hashes.append(hashlib.sha256(f.tobytes()).hexdigest())
        f.save(tmp_path / f'{size[0]}-{t:.2f}.png')
        if source == LESSON:
            from scipy import ndimage
            whiteboard = getattr(prod, 'whiteboard', prod)
            element = next(e for e in whiteboard.els if e.group.startswith('diagram:'))
            points = np.array(drawing.snapshot(t)['dots'])
            points[:, 0] += element.x - whiteboard.camera.at(t) - whiteboard._drift(t)
            points[:, 1] += element.y
            radius = drawing.radius
            left, top = np.floor(points.min(axis=0) - radius*1.1).astype(int)
            right, bottom = np.ceil(points.max(axis=0) + radius*1.1).astype(int)
            assert size[0]*.04 < left < right < size[0]*.96
            assert size[1]*.04 < top < bottom < size[1]*.8
            pixels = np.asarray(f.convert('RGB'))[top:bottom+1,left:right+1]
            mask = np.linalg.norm(pixels.astype(float) - np.array(whiteboard.skin.ink[:3]), axis=2) < 40
            components, n = ndimage.label(mask)
            slices = [b for b in ndimage.find_objects(components)
                      if b and (b[0].stop-b[0].start)*(b[1].stop-b[1].start) > radius**2]
            assert len(slices) == 15, 'actual native frame must contain every separate source dot'
            for sy,sx in slices:
                assert abs((sy.stop-sy.start)-(sx.stop-sx.start)) <= 2, 'native dots must stay round'
        else:
            # Actual card borders and glyph pixels occupy the native organized boxes.
            a = np.asarray(f.convert('RGB'))
            for x,y,w,h in diagram.boxes(t):
                assert 0 <= x < x+w <= size[0] and 0 <= y < y+h < size[1]*.8
                region = a[round(y):round(y+h),round(x):round(x+w)]
                accent = np.array(tuple(int(diagram.palette['accent'][k:k+2],16) for k in (1,3,5)))
                foreground = np.array(tuple(int(diagram.palette['ink'][k:k+2],16) for k in (1,3,5)))
                assert (np.linalg.norm(region.astype(float)-accent,axis=2) < 25).sum() > 100
                assert (np.linalg.norm(region.astype(float)-foreground,axis=2) < 25).sum() > 100

    payload = tmp_path / 'source.json'
    payload.write_text(json.dumps(dict(board=board, tl=tl, size=size, aspect=aspect, times=times)))
    code = "import json,hashlib,sys; from pathlib import Path; from kinodraw.engine.render import make_production; p=Path(sys.argv[1]); d=json.loads(p.read_text()); r=make_production(d['board'],d['tl'],'en',p.parent,size=d['size'],aspect=d['aspect']); print(json.dumps([hashlib.sha256(r.frame(t).tobytes()).hexdigest() for t in d['times']]))"
    result = subprocess.run([sys.executable, '-c', code, str(payload)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == hashes


def test_chinese_and_foreign_context_fail_closed():
    from kinodraw.engine.source_diagrams import resolve
    board = {'lang': 'zh', 'beats': [{'id': 'a', 'chapter': 'main', 'spoken': {'zh': '画三行，每行五个点。'}}]}
    assert resolve(board, 'a') is None
    foreign = [{'id': 'a', 'section': 'first', 'spoken': 'Place two rows of four dots.'},
               {'id': 'b', 'section': 'second', 'spoken': 'Count the dots again.'}]
    assert resolve(foreign, 'b') is None
    assert resolve(foreign, 'unknown') is None


def test_source_equation_and_one_hand_schedule(tmp_path):
    board, plan, tl, prod = prepared(tmp_path, LESSON)
    equation = next(e for e in prod.els if e.group.startswith('diagram-equation:'))
    assert equation.drawing.lines == ['3 × 5 = 15']
    assert equation.beat == board['beats'][2]['id']
    assert tl['beats'][equation.beat]['start'] <= equation.start < equation.end <= tl['beats'][equation.beat]['speech_end']
    for previous, following in zip(prod.hand_els, prod.hand_els[1:]):
        assert previous.end <= following.start + 1e-6


def test_caps_raw_refs_and_unsupported_count_objects():
    from kinodraw.engine.source_diagrams import resolve
    def board(text):
        return {'lang': 'en', 'beats': [{'id': 'a', 'chapter': 'main', 'spoken': {'en': text}}]}
    assert resolve(board('Place eight rows of eight dots.'),'a').total == 64
    assert resolve(board('Place nine rows of eight dots.'),'a') is None
    assert resolve(board('Place 99999 rows of two dots.'),'a') is None
    context = [{'id': 'a', 'section': 'main', 'spoken': 'Place two rows of four dots.'},
               {'id': 'b', 'section': 'main', 'spoken': 'Count the rabbits.'}]
    assert resolve(context,'b') is None
    b = script.build(ingest.read(LESSON), story='showcase')
    RulesDirector('en').direct(b)
    p = from_rules(b)
    for ref in ('<svg><text>99</text></svg>', '3x5=99', b['beats'][-1]['id']):
        draft = copy.deepcopy(p)
        draft['scenes'][0]['elements'] = [{'kind': 'diagram', 'ref': ref}]
        fixed, repairs = validate(draft, b, {})
        assert fixed['scenes'][0]['elements'] == []
        assert any('diagram' in repair for repair in repairs)


def test_four_panel_square_safe_slots(tmp_path):
    source = LAUNCH.replace('notes, tasks and drawings', 'notes, tasks, files and sketches')
    board, plan, tl, prod = prepared(tmp_path, source, (1080,1080), '1:1')
    diagram = next(s.diagram for s in prod.spans if s.diagram)
    for t in (diagram.window[0], sum(diagram.window)/2, diagram.window[1]):
        for x,y,w,h in diagram.boxes(t):
            assert 54 <= x < x+w <= 1026 and 54 <= y < y+h <= 820
        assert prod.frame(t).size == (1080,1080)


@pytest.mark.parametrize('size,aspect', [((1920,1080),'16:9'), ((3840,2160),'16:9'), ((1080,1080),'1:1')])
def test_four_panel_all_times_safe_and_readable(tmp_path, size, aspect):
    source = LAUNCH.replace('notes, tasks and drawings', 'notes, tasks, files and sketches')
    _, _, _, prod = prepared(tmp_path, source, size, aspect)
    diagram = next(s.diagram for s in prod.spans if s.diagram)
    for t in np.linspace(*diagram.window, 9):
        for x,y,w,h in diagram.boxes(t):
            assert size[0]*.05 <= x < x+w <= size[0]*.95
            assert size[1]*.05 <= y < y+h <= size[1]*.76
    for t in np.linspace(*diagram.window, 9):
        frame = np.asarray(prod.frame(float(t)).convert('RGB'))
        for (x,y,w,h), label in zip(diagram.boxes(t), diagram.labels):
            assert size[0]*.05 <= x < x+w <= size[0]*.95
            assert size[1]*.05 <= y < y+h <= size[1]*.76
            assert label.width < w*.9 and label.height < h*.8
            region = frame[round(y):round(y+h),round(x):round(x+w)]
            foreground = np.array(tuple(int(diagram.palette['ink'][k:k+2],16) for k in (1,3,5)))
            assert (np.linalg.norm(region.astype(float)-foreground,axis=2) < 25).sum() > 100


@pytest.mark.parametrize('mode', ['hybrid', 'motion'])
@pytest.mark.parametrize('size,aspect', [((1920,1080),'16:9'), ((3840,2160),'16:9'), ((1080,1080),'1:1')])
def test_provider_dots_motion_scene_keeps_literal_proof(tmp_path, mode, size, aspect):
    board, plan, tl, _ = prepared(tmp_path, LESSON, size, aspect)
    plan['style']['mode'] = mode
    for scene in plan['scenes']:
        scene['treatment'] = 'motion'
    fixed, repairs = validate(plan, board, {})
    board, _ = adapt(fixed, board)
    (tmp_path/'project.json').write_text(json.dumps({'director_v3':True,'plan_v3':fixed}))
    prod = render.make_production(board, tl, 'en', tmp_path, size=size, aspect=aspect)
    whiteboard = prod.whiteboard
    drawing = next(e.drawing for e in whiteboard.els if e.group.startswith('diagram:'))
    for t in (drawing.events['build'][1]+.1, sum(drawing.events['rotate'])/2,
              drawing.events['rotate'][1], sum(drawing.events['count'][-1])/2):
        assert prod.frame(t).convert('RGB').tobytes() == whiteboard.frame(t).convert('RGB').tobytes(), 'accepted source proof must survive scene dispatch'


def test_rules_character_does_not_overwrite_source_diagram():
    source = '# Once upon a time\n\nLeo, a lion, said: Place three rows of five dots.\n\nLeo walked away.'
    board = script.build(ingest.read(source), story='showcase')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    scene = plan['scenes'][0]
    assert scene['treatment'] == 'whiteboard'
    assert {'kind':'diagram','ref':board['beats'][0]['id']} in scene['elements']

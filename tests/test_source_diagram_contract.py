"""Correctness contracts for accepted source diagrams through public rendering."""
import copy
import hashlib
import json
import random

import numpy as np
import pytest
from PIL import Image

from kinodraw import ingest, script
from kinodraw.director.v3.adapter import adapt
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.validate import validate
from kinodraw.engine import render, timeline
from kinodraw.engine.source_diagrams import PanelMotion, resolve

TARGETS = [((1920, 1080), '16:9'), ((3840, 2160), '16:9'), ((1080, 1080), '1:1')]
PANELS = '# Workspace\n\nPanels glide as you organize notes and tasks. The notes remain organized while this continuous narration explains the workspace and its separate readable categories through the rest of this spoken paragraph.'


def build(tmp_path, source, *, kind=None, mode=None, floor='still', merged=False,
          size=None, aspect='16:9'):
    board = script.build(ingest.read(source), story='showcase')
    if kind in ('intro', 'agenda'):
        board['chapters'][0]['kind'] = kind
        board['beats'][0]['kind'] = 'title' if kind == 'intro' else 'agenda'
        if kind == 'agenda':
            chapter = copy.deepcopy(board['chapters'][0])
            chapter.update(id='next', kind='section', title={'en': 'Equal groups'}, label={'en': 'Part 1'})
            board['chapters'].append(chapter)
            beat = copy.deepcopy(board['beats'][0])
            beat.update(id='next-beat', chapter='next', kind='body',
                        spoken={'en': 'Here is the grouping method.'},
                        display={'en': 'Here is the grouping method.'}, visuals=[])
            board['beats'].append(beat)
    elif kind in ('take', 'opener'):
        board['chapters'][0].update(kind='section', title={'en': 'Equal groups'}, label={'en': 'Part 1'})
        if kind == 'take':
            board['beats'][-1].update(kind='take', take={'headline': board['beats'][-1]['display']})
    plan = from_rules(board)
    plan['style']['motion_floor'] = floor
    if mode:
        plan['style']['mode'] = mode
    if merged:
        combined = copy.deepcopy(plan['scenes'][0])
        combined.update(beat_ids=[b['id'] for b in board['beats']],
                        elements=[e for s in plan['scenes'] for e in s['elements']],
                        text={'kind': 'caption_only', 'ref': board['beats'][0]['id']},
                        treatment='motion', camera='static', transition_in='cut')
        plan['scenes'] = [combined]
    plan, _ = validate(plan, board, {})
    board, _ = adapt(plan, board)
    settings = json.dumps({'director_v3': True, 'plan_v3': plan})
    (tmp_path / 'project.json').write_text(settings)
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    original = copy.deepcopy((board, timing, plan))
    prod = render.make_production(board, timing, 'en', tmp_path, size=size, aspect=aspect)
    assert (board, timing, plan) == original
    assert (tmp_path / 'project.json').read_text() == settings
    return board, plan, timing, prod


@pytest.mark.parametrize('number', ['eight hundred', 'eight thousand', 'eight point five',
    'eight and a half', 'eight-thousand', '8.5', '8/2', '8,000', '8k', '8 thousand'])
def test_whole_number_fail_closed(tmp_path, number):
    source = '# Lesson\n\nPlace two rows of four dots. Two times four equals ' + number + '.'
    board, plan, _, _ = build(tmp_path, source)
    ref = board['beats'][0]['id']
    assert resolve(board, ref) is None, 'unsupported whole value must not become eight'
    forced = copy.deepcopy(plan)
    forced['scenes'][0]['elements'] = [{'kind': 'diagram', 'ref': ref}]
    fixed, repairs = validate(forced, board, {})
    assert not any(e['kind'] == 'diagram' for s in fixed['scenes'] for e in s['elements'])
    assert any('diagram' in r for r in repairs)


@pytest.mark.parametrize('size,aspect', TARGETS)
def test_maximum_rotation_and_highlight_fit_actual_raster(tmp_path, size, aspect):
    _, _, _, prod = build(tmp_path, '# Lesson\n\nPlace eight rows of eight dots.\n\nRotate the same dots to make eight rows of eight. Count the dots again.', size=size, aspect=aspect)
    wb = getattr(prod, 'whiteboard', prod)
    element = next(e for e in wb.els if e.group.startswith('diagram:'))
    proof = element.drawing
    for u in np.linspace(0, 1, 17):
        points = np.array(proof.positions(float(u)))
        extent = proof.radius * 1.8 + max(3, round(proof.size[1] / 100))
        assert (points.min(axis=0) - extent > 0).all(), 'rotated highlighted dot crops the proof raster'
        assert (points.max(axis=0) + extent < proof.size).all()
    for t in (sum(proof.events['rotate']) / 2, sum(proof.events['count'][-1]) / 2):
        image, _, _ = proof.state((t - proof.start) * proof.rate)
        bbox = image.getbbox()
        assert bbox and 0 < bbox[0] < bbox[2] < image.width and 0 < bbox[1] < bbox[3] < image.height
        frame = prod.frame(t)
        assert frame.size == size
        frame.save(tmp_path / ('rotation.png' if t == sum(proof.events['rotate']) / 2 else 'highlight.png'))
        points = np.array(proof.snapshot(t)['dots']) + (element.x - wb.camera.at(t) - wb._drift(t), element.y)
        assert (points.min(axis=0) - extent > np.array(size) * .04).all()
        assert points[:, 0].max() + extent < size[0] * .96
        assert points[:, 1].max() + extent < size[1] * .8
    # The construction nib and its actual stroke never hit a raster edge.
    for _, stroke_start, stroke_end in proof.array.table[::13]:
        t = proof.events['build'][0] + (stroke_start+stroke_end)/2 / proof.array.duration * (proof.events['build'][1]-proof.events['build'][0])
        image, pen, down = proof.state((t - proof.start) * proof.rate)
        assert down and pen is not None
        assert 0 < pen[0] < proof.size[0] and 0 < pen[1] < proof.size[1]
        assert image.getbbox()[0] > 0 and image.getbbox()[1] > 0


@pytest.mark.parametrize('kind', ['intro', 'take', 'agenda', 'opener'])
def test_special_recipe_dispatches_accepted_proof(tmp_path, kind):
    source = '# Lesson\n\nPlace two rows of four dots.'
    if kind == 'take':
        source = '# Lesson\n\nHere is the equal grouping method.\n\nPlace two rows of four dots.'
    board, plan, timing, prod = build(tmp_path, source, kind=kind)
    ref = board['beats'][0 if kind == 'agenda' else -1]['id']
    assert any(e == {'kind': 'diagram', 'ref': ref} for s in plan['scenes'] for e in s['elements'])
    elements = [e for e in prod.els if e.group.startswith('diagram:')]
    assert elements, 'accepted proof was bypassed by a special recipe'
    proof = elements[0].drawing
    assert timing['beats'][ref]['start'] <= proof.events['build'][0] < proof.events['build'][1] <= timing['beats'][ref]['speech_end']
    assert len(proof.snapshot(proof.events['build'][1])['dots']) == 8
    frame = np.asarray(prod.frame(proof.events['build'][1] + .01).convert('RGB'))
    e = elements[0]
    for x, y in proof.snapshot(proof.events['build'][1])['dots']:
        px = round(x + e.x - prod.camera.at(proof.events['build'][1] + .01))
        py = round(y + e.y)
        assert np.linalg.norm(frame[py, px].astype(float) - np.array(prod.skin.ink[:3])) < 40


def assert_labels_in_frame(prod, diagram, t):
    frame = np.asarray(prod.frame(t).convert('RGB'))
    color = np.array(tuple(int(diagram.palette['ink'][k:k + 2], 16) for k in (1, 3, 5)))
    for (x, y, w, h), label in zip(diagram.boxes(t), diagram.labels):
        assert prod.size[0] * .05 <= x < x + w <= prod.size[0] * .95
        assert prod.size[1] * .05 <= y < y + h <= prod.size[1] * .76
        assert label.width < w * .9 and label.height < h * .8
        cx, cy = round(x + (w - label.width) / 2), round(y + (h - label.height) / 2)
        region = frame[cy:cy + label.height, cx:cx + label.width]
        assert (np.linalg.norm(region.astype(float) - color, axis=2) < 25).sum() > 100


@pytest.mark.parametrize('size,aspect', TARGETS)
def test_pure_whiteboard_panels_render_labels(tmp_path, size, aspect, monkeypatch):
    board, plan, timing, prod = build(tmp_path, PANELS, mode='whiteboard', size=size, aspect=aspect)
    assert plan['style']['mode'] == 'whiteboard' and not hasattr(prod, 'whiteboard')
    seen = []
    original = PanelMotion.paint
    def record(self, image, t):
        seen.append(self)
        return original(self, image, t)
    monkeypatch.setattr(PanelMotion, 'paint', record)
    t = timing['beats'][board['beats'][0]['id']]['speech_end'] - .1
    prod.frame(t).save(tmp_path / 'whiteboard-panels.png')
    assert seen, 'accepted panels vanished from pure whiteboard rendering'
    assert seen[-1].spec.labels == ('notes', 'tasks')
    assert_labels_in_frame(prod, seen[-1], t)
    forward = hashlib.sha256(prod.frame(t).tobytes()).hexdigest()
    prod.frame(t - 2)
    assert hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == forward


def test_merged_refs_use_chronological_absolute_cues(tmp_path, monkeypatch):
    source = '# Workspace\n\nPanels glide as you organize notes and tasks.\n\nPanels glide as you organize files and sketches.'
    board, _, timing, prod = build(tmp_path, source, mode='motion', merged=True)
    seen = []
    original = PanelMotion.paint
    def record(self, image, t):
        seen.append((self, t))
        return original(self, image, t)
    monkeypatch.setattr(PanelMotion, 'paint', record)
    times = [timing['beats'][b['id']]['start'] + .1 for b in board['beats']]
    expected = [('notes', 'tasks'), ('files', 'sketches')]
    hashes = {}
    for t, labels in zip(times, expected):
        seen.clear()
        hashes[t] = hashlib.sha256(prod.frame(t).tobytes()).hexdigest()
        assert seen and seen[-1][0].spec.labels == labels, 'one ref overwrote the chronological source'
        assert all(at >= diagram.window[0] for diagram, at in seen), 'future labels painted early'
        assert_labels_in_frame(prod, seen[-1][0], t)
    random.Random(4).shuffle(times)
    assert all(hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == hashes[t] for t in times + list(reversed(times)))


@pytest.mark.parametrize('floor', ['breathing', 'drifting', 'lively'])
@pytest.mark.parametrize('size,aspect', TARGETS)
def test_post_glide_foreground_moves_and_holds_suppress(tmp_path, floor, size, aspect):
    _, _, _, prod = build(tmp_path, PANELS, mode='motion', floor=floor, size=size, aspect=aspect)
    span = prod.spans[0]
    diagram = span.diagram
    a = diagram.window[1] + .5
    b = min(a + 1., span.end - .1)
    assert b > a
    boxes = (diagram.boxes(a), diagram.boxes(b))
    assert max(abs(x[0] - y[0]) + abs(x[1] - y[1]) for x, y in zip(*boxes)) > size[1] * .004
    images = [Image.new('RGB', prod.size, '#000000') for _ in range(2)]
    diagram.paint(images[0], a)
    diagram.paint(images[1], b)
    assert images[0].tobytes() != images[1].tobytes(), 'actual card foreground froze after its glide'
    for t in (a, b):
        assert_labels_in_frame(prod, diagram, t)
    # Timeline holds preserve authored final positions throughout the stop.
    held_timing = copy.deepcopy(prod.tl)
    held_timing['holds'] = [{'start': a, 'end': b}]
    held = render.make_production(prod.ep, held_timing, 'en', tmp_path, size=size, aspect=aspect)
    held_diagram = held.spans[0].diagram
    assert held_diagram.boxes(a + .1) == held_diagram.boxes(b - .1)
    settings = json.loads((tmp_path / 'project.json').read_text())
    settings['plan_v3']['style']['motion_floor'] = 'still'
    (tmp_path / 'project.json').write_text(json.dumps(settings))
    still = render.make_production(prod.ep, prod.tl, 'en', tmp_path, size=size, aspect=aspect)
    assert still.spans[0].diagram.boxes(a) == still.spans[0].diagram.boxes(b)

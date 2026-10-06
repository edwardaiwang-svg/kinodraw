"""Main causal reproductions of the final source review; no movie repair cycle."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw.director.v3.validate import validate
from kinodraw.engine.source_diagrams import resolve
from source_diagram_helpers import build

OUT = Path(__file__).resolve().parents[1] / 'docs/overnight-2026-10-05/evidence/source-diagrams/final-contract-repair/own-rawframes'
OUT.mkdir(parents=True, exist_ok=True)


def record(name, data):
    (OUT / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')


@pytest.mark.parametrize('claim', [
    'One hundred two times four equals eight.',
    'Rotate the same dots to make four rows of two million.',
])
def test_unsupported_whole_value_cannot_be_a_supported_suffix(tmp_path, claim):
    board, plan, _, _ = build(tmp_path, '# Lesson\n\nPlace two rows of four dots.\n\n' + claim)
    ref = board['beats'][-1]['id']
    spec = resolve(board, ref)
    draft = copy.deepcopy(plan)
    draft['scenes'][-1]['elements'] = [{'kind': 'diagram', 'ref': ref}]
    fixed, repairs = validate(draft, board, {})
    record('whole-value-' + ('equation' if 'times' in claim else 'rotation'), {
        'spoken': board['beats'][-1]['spoken'],
        'resolved': vars(spec) if spec else None,
        'forced_plan': draft, 'checked_plan': fixed, 'repairs': repairs,
    })
    assert spec is None, 'Unsupported source value was rewritten as a small supported suffix'
    assert not any(e['kind'] == 'diagram' and e['ref'] == ref
                   for s in fixed['scenes'] for e in s['elements'])


def test_recount_restores_visible_array_after_panel_page(tmp_path):
    source = '# Lesson\n\nPlace two rows of four dots.\n\nPanels glide as you organize notes and tasks.\n\nCount the dots again.'
    board, plan, timing, prod = build(tmp_path, source, mode='whiteboard')
    refs = [b['id'] for b in board['beats']]
    assert all(any(e == {'kind': 'diagram', 'ref': ref}
                   for s in plan['scenes'] for e in s['elements']) for ref in refs)
    element = next(e for e in prod.els if e.group.startswith('diagram:')
                   and hasattr(e.drawing, 'snapshot'))
    proof = element.drawing
    t = sum(proof.events['count'][-1]) / 2
    frame = prod.frame(t).convert('RGB')
    frame.save(OUT / 'recount-after-panels.png')
    positions = np.array(proof.snapshot(t)['dots'])
    positions += (element.x - prod.camera.at(t) - prod._drift(t), element.y)
    inside = ((positions[:, 0] > prod.size[0] * .04)
              & (positions[:, 0] < prod.size[0] * .96)
              & (positions[:, 1] > prod.size[1] * .04)
              & (positions[:, 1] < prod.size[1] * .8))
    record('recount-page', {'source': source, 'plan': plan, 'time': t,
                           'camera': prod.camera.at(t), 'element_x': element.x,
                           'points': positions.tolist(), 'inside': inside.tolist(),
                           'groups': [e.group for e in prod.els]})
    assert inside.all(), 'Accepted recount highlights dots on an off-screen page'
    pixels = np.array(frame)
    for x, y in positions:
        assert np.linalg.norm(pixels[round(y), round(x)].astype(float)
                              - np.array(prod.skin.ink[:3])) < 40, 'Narrated source dots not visible'


def test_first_equation_is_visible_before_later_equation_ref(tmp_path):
    source = '# Lesson\n\nPlace two rows of four dots.\n\nTwo times four equals eight.\n\nTwo times four equals eight.'
    board, plan, timing, prod = build(tmp_path, source, mode='whiteboard')
    first_ref = board['beats'][1]['id']
    assert any(e == {'kind': 'diagram', 'ref': first_ref}
               for s in plan['scenes'] for e in s['elements'])
    proof = next(e.drawing for e in prod.els if e.group.startswith('diagram:')
                 and hasattr(e.drawing, 'snapshot'))
    equations = [e for e in prod.els if e.group.startswith('diagram-equation:')]
    t = timing['beats'][first_ref]['speech_end'] - .01
    prod.frame(t).save(OUT / 'first-equation.png')
    state = proof.snapshot(t)
    record('equation-source-clock', {'source': source, 'plan': plan, 'time': t,
           'first_ref': first_ref, 'first_timing': timing['beats'][first_ref],
           'proof_events': proof.events, 'snapshot': state,
           'equation_elements': [{'beat': e.beat, 'start': e.start, 'end': e.end,
                                 'lines': e.drawing.lines} for e in equations]})
    assert state['equation'] == '2 × 4 = 8', 'Later source ref erased the first equation window'
    assert any(e.beat == first_ref and e.start < t and e.end <= timing['beats'][first_ref]['speech_end']
               for e in equations), 'Actual first narrated equation writing never scheduled'


@pytest.mark.parametrize('floor', ['breathing', 'drifting', 'lively'])
def test_panel_foreground_moves_during_following_narration_in_same_scene(tmp_path, floor):
    source = ('# Workspace\n\nPanels glide as you organize notes and tasks.\n\n'
              'These separate categories keep the workspace clear while this continuing explanation '
              'describes how each category remains readable and useful during the rest of the narration.')
    board, plan, timing, prod = build(tmp_path, source, mode='motion', floor=floor, merged=True)
    assert len(prod.spans) == 1 and len(board['beats']) == 2
    diagram = prod.spans[0].diagram
    bt = timing['beats'][board['beats'][1]['id']]
    a, b = bt['start'] + .6, bt['start'] + 1.4
    assert diagram.window[1] < a < b < bt['speech_end']
    images = [Image.new('RGB', prod.size, '#000000') for _ in range(2)]
    for i, t in enumerate((a, b)):
        diagram.paint(images[i], t)
        prod.frame(t).save(OUT / (floor + '-following-' + str(i) + '.png'))
    boxes = [diagram.boxes(t) for t in (a, b)]
    record('following-floor-' + floor, {'source': source, 'plan': plan,
           'times': [a, b], 'diagram_speech_end': diagram.speech_end,
           'later_timing': bt, 'boxes': boxes,
           'same_foreground': images[0].tobytes() == images[1].tobytes()})
    assert images[0].tobytes() != images[1].tobytes(), 'Cards freeze through later narration in their saved scene'
    assert boxes[0] != boxes[1]


@pytest.mark.parametrize('claim', [
    'Fifty two times four equals eight.',
    'Seventy-two times four equals eight.',
    '102 times four equals eight.',
    '-2 times four equals eight.',
    '2/2 times four equals eight.',
    'Rotate the same dots to make four rows of two billion.',
    'Rotate the same dots to make four rows of two and a half.',
])
def test_closed_value_boundaries_reject_other_prefixes_and_suffixes(tmp_path, claim):
    board, plan, _, _ = build(tmp_path, '# Lesson\n\nPlace two rows of four dots.\n\n' + claim)
    ref = board['beats'][-1]['id']
    assert resolve(board, ref) is None
    forced = copy.deepcopy(plan)
    forced['scenes'][-1]['elements'] = [{'kind': 'diagram', 'ref': ref}]
    checked, _ = validate(forced, board, {})
    assert not any(e == {'kind': 'diagram', 'ref': ref}
                   for scene in checked['scenes'] for e in scene['elements'])


@pytest.mark.parametrize('size,aspect', [((1080, 1080), '1:1'), ((3840, 2160), '16:9')])
def test_native_return_and_each_equation_keep_source_identity(tmp_path, size, aspect):
    from test_source_diagram_contract import build as build_target
    import hashlib
    from kinodraw.engine import render
    source = ('# Lesson\n\nPlace two rows of four dots.\n\nTwo times four equals eight.\n\n'
              'Panels glide as you organize notes and tasks.\n\nCount the dots again.\n\n'
              'Two times four equals eight.')
    board, plan, timing, prod = build_target(tmp_path, source, mode='whiteboard', size=size, aspect=aspect)
    proof_elements = [e for e in prod.els if e.group.startswith('diagram:') and hasattr(e.drawing, 'snapshot')]
    assert len(proof_elements) == 1
    element = proof_elements[0]
    proof = element.drawing
    equations = [e for e in prod.els if e.group.startswith('diagram-equation:')]
    refs = [board['beats'][i]['id'] for i in (1, 4)]
    assert [e.beat for e in equations] == refs
    for e in equations:
        bt = timing['beats'][e.beat]
        assert bt['start'] <= e.start < e.end <= bt['speech_end']
    assert equations[0].hidden_after == equations[1].trigger
    count_t = sum(proof.events['count'][-1]) / 2
    points = np.array(proof.snapshot(count_t)['dots']) + (element.x - prod.camera.at(count_t) - prod._drift(count_t), element.y)
    frame = prod.frame(count_t).convert('RGB')
    pixels = np.asarray(frame)
    assert (points.min(axis=0) > np.array(size) * .04).all()
    assert points[:, 0].max() < size[0] * .96 and points[:, 1].max() < size[1] * .8
    for x, y in points:
        assert np.linalg.norm(pixels[round(y), round(x)].astype(float) - np.array(prod.skin.ink[:3])) < 40
    panels = [e for e in prod.els if hasattr(e.drawing, 'motion') and e.group.startswith('diagram:')]
    assert panels and all(e.state(count_t)[0] is None for e in panels)
    for previous, following in zip(prod.hand_els, prod.hand_els[1:]):
        assert previous.end <= following.start + 1e-6
    times = [timing['beats'][ref]['speech_end'] - .01 for ref in refs] + [count_t]
    hashes = {t: hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in times}
    for t in reversed(times):
        assert hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == hashes[t]
    fresh = render.make_production(board, timing, 'en', tmp_path, size=size, aspect=aspect)
    assert all(hashlib.sha256(fresh.frame(t).tobytes()).hexdigest() == hashes[t] for t in times)
    frame.save(OUT / f'native-return-{size[0]}x{size[1]}.png')
    record(f'native-return-{size[0]}x{size[1]}', {'hashes': hashes, 'equations': refs, 'points': points.tolist()})


@pytest.mark.parametrize('mode,size,aspect', [('whiteboard', (1920, 1080), '16:9'),
    ('motion', (1080, 1080), '1:1'), ('whiteboard', (3840, 2160), '16:9')])
def test_continuing_panel_scene_respects_still_holds_and_pause(tmp_path, mode, size, aspect):
    from test_source_diagram_contract import build as build_target
    from kinodraw.engine import render
    source = ('# Workspace\n\nPanels glide as you organize notes, tasks, files and sketches.\n\n'
              'These separate categories remain readable during this continuing explanation of the workspace.')
    board, _, timing, prod = build_target(tmp_path, source, mode=mode, floor='drifting', merged=True, size=size, aspect=aspect)
    def diagram(p):
        return p.spans[0].diagram if hasattr(p, 'spans') else next(e.drawing.motion for e in p.els if e.group.startswith('diagram:'))
    active = diagram(prod)
    later = timing['beats'][board['beats'][1]['id']]
    a, b = later['start'] + .6, later['start'] + 1.4
    assert active.boxes(a) != active.boxes(b)
    for stop in ('holds', 'pauses'):
        held_timing = copy.deepcopy(timing)
        if stop == 'holds':
            held_timing[stop] = [{'start': a, 'end': b}]
        elif stop == 'pauses':
            held_timing[stop] = {board['beats'][0]['id']: b - timing['beats'][board['beats'][0]['id']]['speech_end']}
        if held_timing is not None:
            held = diagram(render.make_production(board, held_timing, 'en', tmp_path, size=size, aspect=aspect))
            assert held.boxes(a + .1) == held.boxes(b - .1)
    settings = json.loads((tmp_path / 'project.json').read_text())
    settings['plan_v3']['style']['motion_floor'] = 'still'
    (tmp_path / 'project.json').write_text(json.dumps(settings))
    still = diagram(render.make_production(board, timing, 'en', tmp_path, size=size, aspect=aspect))
    assert still.boxes(a) == still.boxes(b)


@pytest.mark.parametrize('claim', [
    'One quadrillion two times four equals eight.',
    'Rotate the same dots to make four rows of two quadrillion.',
    'Two times four equals 8%.',
    'Two times four equals eight percent.',
    'Two times four equals 8+1.',
])
def test_numeric_lexical_boundaries_without_extending_value_parser(claim):
    board = {'lang': 'en', 'beats': [
        {'id': 'a', 'chapter': 'main', 'spoken': 'Place two rows of four dots.'},
        {'id': 'b', 'chapter': 'main', 'spoken': claim}]}
    assert resolve(board, 'b') is None

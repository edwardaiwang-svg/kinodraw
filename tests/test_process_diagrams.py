"""Process boards: an explainer's process drawn as a labelled diagram that builds up across beats."""
import copy
import json

import numpy as np
import pytest

from kinodraw import ingest, script
from kinodraw.director.v3.adapter import adapt
from kinodraw.director.v3.offer import board_hints
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.validate import validate
from kinodraw.engine import process_diagrams as pd
from kinodraw.engine import render, timeline

WEATHER = ('# How Hail Forms\n\nA tall storm cloud lifts raindrops high into freezing air. Each drop freezes into a '
           'small ball of ice called a hailstone.\n\nThe hailstone falls, picks up a coat of water, and rises again. '
           'Every trip adds a layer, so a big hailstone is about three times heavier than a small one.\n\n'
           'When the stone is too heavy for the wind, it drops to the ground. That\'s a hailstorm.')
LESSON = ('# Swapping Factors\n\nStart at 0. Jump 4, then jump 2. You land on 6.\n\nNow swap the order. Jump 2 first, '
          'then 4. 6 again.\n\nThis is the commutative property of addition. M plus N equals N plus M.\n\n'
          'Multiplication works the same way. Here are 2 rows of 6 dots. 2 times 6 is 12.\n\nNow give the picture a '
          'quarter turn. It shows 6 rows of 2. 6 times 2 is 12.')


@pytest.mark.parametrize('said,written', [
    ('A plus B equals B plus A', 'a + b = b + a'),
    ('3 times 5 is 15', '3 × 5 = 15'),
    ('x times y equals y times x', 'x · y = y · x'),
    ('about five times hotter', '≈ 5× hotter'),
    ('seconds ... divide by five ... roughly ... miles away', 'seconds ÷ 5 ≈ miles away'),
    ('twelve minus four is eight', '12 − 4 = 8'),
])
def test_spoken_math_is_typeset(said, written):
    assert pd.typeset(said) == written


@pytest.mark.parametrize('sentence,runs', [
    ('Here are 3 rows of 5 dots. 3 times 5 is 15.', ['3 times 5 is 15']),
    ('Count the seconds, divide by five, and you know the distance.', ['divide by five']),
    ('It heats the air to about five times hotter than the sun.', ['about five times hotter']),
    ('Jump 3, then jump 5. You land on 8.', []),
    ('So the answer is still 15.', []),
    ('In algebra, a raised dot means times.', []),
    ('Add 2 cups of flour and bake at 350 degrees.', []),
])
def test_math_runs_find_only_spoken_operations(sentence, runs):
    assert [sentence[a:b] for a, b in pd.math_runs(sentence)] == runs


@pytest.mark.parametrize('sentence,found', [
    ('Pellets of soft hail, called graupel, fall back down.', ['graupel']),
    ('Scientists call it a stepped leader.', ['stepped leader']),
    ('A spark called a streamer reaches up from a tree.', ['streamer']),
    ('That bright flash is the return stroke, and it heats the air.', ['return stroke']),
    ("That's thunder.", ['thunder']),
    ('This is the commutative property of addition.', ['commutative property of addition']),
    ('The fox ran home.', []),
])
def test_named_terms(sentence, found):
    assert pd.terms(sentence) == found


def test_offer_tells_the_planner_what_a_board_can_write():
    assert board_hints('Scientists call it a stepped leader. 3 times 5 is 15.') == [
        'term: stepped leader', 'math: 3 times 5 is 15 -> 3 × 5 = 15']
    assert board_hints('The fox ran home.') == []


def _board(source):
    return script.build(ingest.read(source), story='showcase')


def _item(iid, beat, kind, cue='', ref='', to='', at='auto', text='', style='none'):
    return dict(id=iid, beat_id=beat, cue=cue, kind=kind, ref=ref, to=to, at=at, text=text, style=style)


def _offered(board, ids):
    return {b['id']: [{'id': i, 'desc': i} for i in ids] for b in board['beats']}


def test_valid_board_is_kept_and_bad_items_are_repaired_or_dropped_with_notes():
    board = _board(WEATHER)
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    plan['style']['mode'] = 'motion'
    scene = copy.deepcopy(plan['scenes'][0])
    scene.update(beat_ids=bids, treatment='motion', elements=[], shots=[], boards=[{'layout': 'parts', 'items': [
        _item('cloud', bids[0], 'picture', 'storm cloud', ref='storm_cloud', at='center'),
        _item('ice', bids[0], 'charges', 'freezing air', to='cloud', at='top', style='plus', text='freezing air'),
        _item('stone', bids[0], 'label', 'called a hailstone', to='cloud', text='hailstone'),
        _item('made_up', bids[0], 'label', text='ice nucleation'),                    # not in the beat
        _item('ufo', bids[0], 'picture', ref='flying_saucer'),                         # not offered
        _item('loop', bids[1], 'link', 'rises again', ref='cloud', to='nowhere', style='curved'),
        _item('heavy', bids[1], 'equation', 'three times heavier', text='about three times heavier'),
        _item('ground', bids[2], 'picture', 'ground', ref='fl_house', at='ground'),
        _item('drop', bids[2], 'link', 'drops to the ground', ref='cloud', to='ground', style='dashed'),
        _item('late', bids[2], 'label', 'not said anywhere', to='ground', text='hailstorm'),
    ]}])
    plan['scenes'] = [scene]
    out, repairs = validate(plan, board, _offered(board, ['storm_cloud', 'fl_house']))
    kept = {it['id']: it for it in out['scenes'][0]['boards'][0]['items']}
    assert set(kept) >= {'cloud', 'ice', 'stone', 'heavy', 'ground', 'drop', 'late'}
    assert 'made_up' not in kept and 'ufo' not in kept and 'loop' not in kept
    assert kept['late']['cue'] == 'hailstorm'        # unheard cue: it appears as its own words are said
    assert kept['ground']['cue'] == 'drops to the ground'   # a step said before its target brings the target along
    assert kept['ice']['cue'] == 'freezing air'
    assert out['scenes'][0]['treatment'] == 'whiteboard' and out['style']['mode'] == 'hybrid'
    notes = '\n'.join(repairs)
    for needle in ("dropped label 'ice nucleation'", "dropped picture 'flying_saucer'", 'dropped link loop',
                   "'not said anywhere' is not in", 'motion -> hybrid', 'ground now appears with drop'):
        assert needle in notes


LEADER = ('# Lightning\n\nWhen the difference gets big enough, a faint path of negative charge zigzags down from the '
          'cloud in short steps. Scientists call it a stepped leader. At the same time, a spark called a streamer '
          'reaches up from a tree or a rooftop.\n\nCount the seconds between the flash and the thunder, divide by '
          'five, and you\'ll know roughly how many miles away the strike was.')


def test_each_step_is_drawn_when_its_words_are_said_and_brings_what_it_points_at():
    board = _board(LEADER)
    bid = board['beats'][0]['id']
    plan = from_rules(board)
    late = 'from a tree or a rooftop'                  # a planner cued every step at the end of the beat
    scene = copy.deepcopy(plan['scenes'][0])
    scene.update(beat_ids=[bid], treatment='whiteboard', elements=[], shots=[], boards=[{'layout': 'parts', 'items': [
        _item('cloud', bid, 'picture', 'When the difference gets big enough', ref='storm_cloud', at='center'),
        _item('tree', bid, 'picture', late, ref='fl_house', at='ground'),
        _item('streamer', bid, 'link', late, ref='tree', to='cloud', style='zigzag', text='streamer'),
        _item('leader', bid, 'link', late, ref='cloud', to='tree', style='zigzag', text='negative charge'),
        _item('leader_term', bid, 'label', late, to='leader', text='stepped leader')]}])
    plan['scenes'] = [scene] + [s for s in plan['scenes'] if bid not in s['beat_ids']]
    out, repairs = validate(plan, board, _offered(board, ['storm_cloud', 'fl_house']))
    items = out['scenes'][0]['boards'][0]['items']
    cues = {it['id']: it['cue'] for it in items}
    assert cues['leader'] == 'negative charge' and cues['leader_term'] == 'stepped leader'
    assert cues['streamer'] == 'streamer' and cues['tree'] == 'negative charge'    # the tree comes with the leader
    assert [it['id'] for it in items] == ['cloud', 'tree', 'leader', 'leader_term', 'streamer']


def test_a_planner_number_line_gets_every_hop_the_narration_says():
    board = _board(LESSON)
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    scene = copy.deepcopy(plan['scenes'][0])
    scene.update(beat_ids=bids[:2], treatment='whiteboard', elements=[], shots=[], boards=[{'layout': 'flow', 'items': [
        _item('line', bids[0], 'number_line', 'Start at 0', text='Start at 0'),
        _item('four', bids[0], 'hop', 'Jump 4', to='line', text='Jump 4'),
        _item('two', bids[1], 'hop', 'Jump 2 first', to='line', text='Jump 2')]}])   # "then 4" left out
    plan['scenes'] = [scene] + [s for s in plan['scenes'] if not set(s['beat_ids']) & set(bids[:2])]
    out, repairs = validate(plan, board, _offered(board, []))
    hops = [(it['beat_id'], it['text'], it['style']) for it in out['scenes'][0]['boards'][0]['items']
            if it['kind'] == 'hop']
    assert hops == [(bids[0], 'Jump 4', 'none'), (bids[0], 'jump 2', 'none'),
                    (bids[1], 'Jump 2', 'restart'), (bids[1], 'then 4', 'none')]   # the swap starts over
    assert any("added hop 'then 4'" in r for r in repairs)


def test_board_text_stays_where_the_renderer_shows_it(tmp_path):
    def edit(board, plan):
        bids = [b['id'] for b in board['beats']]
        scene = copy.deepcopy(plan['scenes'][-1])
        scene.update(beat_ids=[bids[-1]], treatment='whiteboard', elements=[], shots=[], boards=[{
            'layout': 'flow', 'items': [
                _item('light', bids[-1], 'picture', 'Count the seconds', ref='storm_cloud'),
                _item('sound', bids[-1], 'picture', 'Count the seconds', ref='fl_house'),
                _item('rule', bids[-1], 'equation', 'divide by five',              # third step: the right edge
                      text='seconds ... divide by five ... roughly ... miles away')]}])
        plan['scenes'] = [s for s in plan['scenes'] if bids[-1] not in s['beat_ids']] + [scene]
        plan['style']['mode'] = 'whiteboard'
    board, plan, timing, prod = _render(tmp_path, LEADER, edit)
    wb = getattr(prod, 'whiteboard', prod)
    texts = [e for e in wb.ctx.elements if e.group.startswith('board:') and isinstance(e.drawing, render.ink.TextDrawing)]
    assert any(e.group.endswith(':rule') for e in texts)
    for e in texts:
        t = e.start + e.drawing.duration + .1
        for drift in (-12, 0, 12):                     # wherever the idle drift takes the camera
            assert wb.text_visible(e, t, wb.camera.at(t) + drift), e.group


def test_an_unresolvable_diagram_ref_becomes_a_board_instead_of_being_dropped():
    """r01: Luna asked for diagrams of process beats and the validator dropped them; icons were drawn instead."""
    board = _board(WEATHER)
    plan = from_rules(board)
    first = plan['scenes'][0]
    first['elements'] = [{'kind': 'diagram', 'ref': first['beat_ids'][0]}, {'kind': 'picture', 'ref': 'storm_cloud'}]
    out, repairs = validate(plan, board, _offered(board, ['storm_cloud']))
    scene = out['scenes'][0]
    items = [it for b in scene['boards'] for it in b['items']]
    assert any(it['kind'] == 'picture' and it['ref'] == 'storm_cloud' for it in items)
    assert any(it['kind'] == 'label' and it['text'] == 'hailstone' for it in items)      # "called a hailstone"
    assert scene['treatment'] == 'whiteboard'
    assert any('drawn as a board' in note for note in repairs)
    assert not any("dropped unknown or out-of-scene diagram" in note for note in repairs)


def test_a_board_gets_each_named_term_and_spoken_equation_of_its_beats():
    board = _board(WEATHER)
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    scene = copy.deepcopy(plan['scenes'][0])
    scene.update(beat_ids=bids, treatment='whiteboard', elements=[], shots=[], boards=[{'layout': 'parts', 'items': [
        _item('cloud', bids[0], 'picture', ref='storm_cloud', at='center')]}])
    plan['scenes'] = [scene]
    out, _ = validate(plan, board, _offered(board, ['storm_cloud']))
    items = out['scenes'][0]['boards'][0]['items']
    assert {it['text'] for it in items if it['kind'] == 'label'} >= {'hailstone', 'hailstorm'}
    assert [pd.typeset(it['text']) for it in items if it['kind'] == 'equation'] == ['≈ 3× heavier']


def _lesson_plan():
    board = _board(LESSON)
    plan = from_rules(board)
    for scene in plan['scenes']:
        scene['elements'] = [{'kind': 'diagram', 'ref': bid} for bid in scene['beat_ids']]
    return board, plan


def test_a_lesson_draws_a_number_line_with_hops_and_an_array_that_turns():
    board, plan = _lesson_plan()
    out, repairs = validate(plan, board, {})
    boards = [b for s in out['scenes'] for b in s['boards']]
    assert len(boards) == 2                                           # one board per idea: addition, multiplication
    first, second = ([(it['kind'], it['text'], it['style']) for it in b['items']] for b in boards)
    assert ('number_line', 'Start at 0', 'none') in first
    assert [h for h in first if h[0] == 'hop'] == [('hop', 'Jump 4', 'none'), ('hop', 'jump 2', 'none'),
                                                    ('hop', 'Jump 2', 'restart'), ('hop', 'then 4', 'none')]
    assert ('label', 'commutative property of addition', 'box') in first
    assert ('equation', 'M plus N equals N plus M', 'none') in first
    assert ('dots', '2 rows of 6', 'none') in second
    assert any(k == 'rotate' for k, _, _ in second) and ('label', '6 rows of 2', 'none') in second
    assert [pd.typeset(t) for k, t, _ in second if k == 'equation'] == ['2 × 6 = 12', '6 × 2 = 12']
    assert any('scenes: merged' in note for note in repairs)


def test_plans_without_boards_are_unchanged():
    board = _board(WEATHER)
    plan = from_rules(board)
    for scene in plan['scenes']:
        scene.pop('boards', None)
    out, repairs = validate(plan, board, {})
    assert all(scene['boards'] == [] for scene in out['scenes'])
    assert not any('board' in note for note in repairs)


def _measure(it, kind):
    text = pd.typeset(it['text']) if kind == 'equation' else it['text']
    return (len(text) * 19 + 12, 95 if kind == 'equation' else 68)


@pytest.mark.parametrize('layout,items', [
    ('parts', [_item('cloud', 'b', 'picture', ref='storm_cloud', at='center'),
               _item('plus', 'b', 'charges', to='cloud', at='top', style='plus', text='ice crystals'),
               _item('minus', 'b', 'charges', to='cloud', at='bottom', style='minus', text='graupel'),
               _item('battery', 'b', 'picture', ref='fl_battery', at='right', text='giant battery'),
               _item('tree', 'b', 'picture', ref='fl_evergreen_tree', at='ground'),
               _item('leader', 'b', 'link', ref='cloud', to='tree', style='zigzag', text='stepped leader'),
               _item('streamer', 'b', 'link', ref='tree', to='cloud', style='zigzag', text='streamer'),
               _item('rs', 'b', 'label', to='leader', text='return stroke'),
               _item('rule', 'b', 'equation', text='about five times hotter')]),
    ('compare', [_item('light', 'b', 'picture', ref='lightbulb_idea', at='left', text='Light'),
                 _item('sound', 'b', 'picture', ref='tb_volume', at='right', text='sound is slower'),
                 _item('clock', 'b', 'picture', ref='clock_fast', at='center'),
                 _item('ratio', 'b', 'equation', text='divide by five')]),
    ('flow', [_item('a', 'b', 'picture', ref='fl_seedling'), _item('b', 'b', 'picture', ref='fl_tree'),
              _item('c', 'b', 'label', text='a forest'), _item('d', 'b', 'equation', text='3 times 5 is 15')]),
])
def test_layout_keeps_text_on_the_page_and_off_pictures(layout, items):
    def picture(it, rect):
        side = min(rect.w, rect.h)
        return pd.Rect(rect.cx - side / 2, rect.cy - side / 2, side, side)
    lay = pd.Layout({'layout': layout, 'items': items}, 1800, 738, _measure, picture)
    assert lay.problems() == []
    assert all(r.inside(1800, 738) for r in lay.place.values())


def test_charges_on_a_small_picture_sit_beside_it_big_enough_to_read():
    def small(it, rect):                                     # a little ice-cube doodle
        return pd.Rect(rect.cx - 75, rect.cy - 75, 150, 150)
    items = [_item('cube', 'b', 'picture', ref='ice_cube', at='center'),
             _item('plus', 'b', 'charges', to='cube', at='top', style='plus'),
             _item('minus', 'b', 'charges', to='cube', at='bottom', style='minus')]
    lay = pd.Layout({'layout': 'parts', 'items': items}, 1800, 738, _measure, small)
    cube = lay.place['cube']
    for key, above in (('plus', True), ('minus', False)):
        area = lay.place[key]
        assert not area.hits(cube)
        assert (area.y + area.h <= cube.y) if above else (area.y >= cube.y + cube.h)
        assert pd.charge_radius(area, 738) >= 738 * .022 and area.h >= pd.charge_radius(area, 738) * 2.8


def _render(tmp_path, source, plan_edit):
    board = _board(source)
    plan = from_rules(board)
    plan_edit(board, plan)
    plan, _ = validate(plan, board, {b['id']: [{'id': i, 'desc': i} for i in ('storm_cloud', 'fl_house')]
                                       for b in board['beats']})
    board, _ = adapt(plan, board)
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    return board, plan, timing, render.make_production(board, timing, 'en', tmp_path)


def test_a_lesson_board_is_drawn_and_its_array_turns_on_its_words(tmp_path):
    def edit(board, plan):
        for scene in plan['scenes']:
            scene['elements'] = [{'kind': 'diagram', 'ref': bid} for bid in scene['beat_ids']]
    board, plan, timing, prod = _render(tmp_path, LESSON, edit)
    wb = getattr(prod, 'whiteboard', prod)
    groups = [e for e in wb.ctx.elements if e.group.startswith('board:')]
    assert groups and not any(e.skipped for e in groups)
    turn = next(it for s in plan['scenes'] for b in s['boards'] for it in b['items'] if it['kind'] == 'rotate')
    beat = next(b for b in board['beats'] if b['id'] == turn['beat_id'])
    at = pd.cue_time(timing, beat, turn['cue'], 'en')
    dots = next(e for e in groups if isinstance(e.drawing, pd.Dots))
    assert dots.drawing.turn_at == pytest.approx(at)
    before = np.asarray(prod.frame(at - .05).convert('L'), np.int16)
    after = np.asarray(prod.frame(at + 1.5).convert('L'), np.int16)
    assert np.abs(after - before).mean() > .5                         # the same dots turned a quarter turn
    hops = [e for e in groups if isinstance(e.drawing, pd.Timed) and e.drawing.dim_at is not None]
    assert hops                                                       # the first hops dim when the order is swapped


def test_board_beats_draw_no_keyword_icons_and_never_an_empty_page(tmp_path):
    def edit(board, plan):
        bids = [b['id'] for b in board['beats']]
        scene = copy.deepcopy(plan['scenes'][0])
        scene.update(beat_ids=bids, treatment='whiteboard', elements=[], shots=[], boards=[{'layout': 'parts', 'items': [
            _item('cloud', bids[0], 'picture', ref='storm_cloud', at='center'),
            _item('home', bids[2], 'picture', 'ground', ref='fl_house', at='ground'),
            _item('fall', bids[2], 'link', 'drops to the ground', ref='cloud', to='home', style='zigzag'),
            _item('rings', bids[2], 'rings', "That's a hailstorm", to='home', text='hailstorm')]}])
        plan['scenes'] = [scene]
        plan['style']['mode'] = 'whiteboard'
    board, plan, timing, prod = _render(tmp_path, WEATHER, edit)
    wb = getattr(prod, 'whiteboard', prod)
    beat_ids = {b['id'] for b in board['beats']}
    drawn = [e for e in wb.ctx.elements if e.beat in beat_ids]
    assert drawn and all(e.group.startswith('board:') for e in drawn)
    for b in board['beats']:
        info = timing['beats'][b['id']]
        for t in np.linspace(info['start'] + .8, info['speech_end'] - .1, 4):
            frame = np.asarray(prod.frame(float(t)).convert('L'), np.int16)
            ink_px = (frame[84:822] < 150).sum()
            assert ink_px > 2000, (b['id'], t)

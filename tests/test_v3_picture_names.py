"""A saved plan keeps a library picture when the scene's words name it the way a person would say they do (its
name, a library keyword, a word form or a common synonym), never in another sense; a picture that must go gives
way to the offered picture of the same noun; a shot never borrows an earlier scene's held thing (gauntlet r4)."""
import copy

import pytest

from kinodraw import ingest, script
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.validate import validate


def _validate(text, pictures, offered=('fl_cloud',), shot=None):
    board = script.build(ingest.read('# Pictures\n\n' + text), story='showcase')
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    scene = copy.deepcopy(plan['scenes'][0])
    scene.update(beat_ids=bids, treatment='whiteboard', shots=[], boards=[],
                 elements=[{'kind': 'picture', 'ref': p} for p in pictures])
    if shot:
        scene['shots'] = [{'beat_id': bids[0], 'starts_at': '', 'shot': shot[0],
                           'setting': {'place': 'none', 'time': 'unknown', 'set_refs': []}, 'cast': [], 'lines': [],
                           'props': [], 'focus_ref': shot[1], 'writing': ''}]
    plan['scenes'] = [scene]
    kept = []
    out, repairs = validate(plan, board, {bid: [{'id': i, 'desc': i} for i in offered] for bid in bids}, kept)
    return out['scenes'][0], repairs + kept


def _pictures(scene):
    return [e['ref'] for e in scene['elements'] if e['kind'] == 'picture']


@pytest.mark.parametrize('text,picture', [
    ('He read the list twice before he folded it.', 'tb_clipboard_list'),
    ('Her checklist was taped inside the cupboard door.', 'tb_clipboard_list'),
    ('She ran downstairs to answer the door.', 'tb_stairs_down'),
    ('He climbed back upstairs without a word.', 'tb_stairs_up'),
    ('A letter was waiting on the mat.', 'tb_mail_opened'),
    ('He opened it slowly at the kitchen table.', 'tb_mail_opened'),
    ('Fuel for the vans cost more this spring.', 'fl_fuel_pump'),
    ('The library now serves four thousand households.', 'house'),
    ('The library now serves four thousand households.', 'family_group'),
    ('The kids were already asleep upstairs.', 'family_group'),
    ('The arrow on the sign pointed north.', 'compass_rose'),
    ('She carried the groceries to the car.', 'shopping_cart'),
    ('A truck rolled past the gate.', 'fl_delivery_truck'),
])
def test_a_picture_the_words_name_is_kept_and_says_why(text, picture):
    scene, repairs = _validate(text, [picture])
    assert _pictures(scene) == [picture], repairs
    assert any(f'kept {picture}, not offered: the words say' in r or f'kept {picture}, not offered: a word names'
               in r for r in repairs), repairs


@pytest.mark.parametrize('text,picture', [
    ('Find the drip under the sink. A faucet leaking one drop a second wastes water.', 'hi_intravenous_drip'),
    ('Strong winds carry tiny ice crystals up high.', 'ice_cube'),
    ('The headlights lit up a fence, a field, and nothing else.', 'fl_field_hockey'),
    ('The high school band is playing at noon.', 'tb_guitar_pick'),
])
def test_a_picture_named_only_in_another_sense_is_dropped_with_its_reason(text, picture):
    scene, repairs = _validate(text, [picture])
    assert _pictures(scene) == [], repairs
    assert any(f'{picture} is not named by the scene' in r for r in repairs), repairs


def test_a_dropped_picture_gives_way_to_the_offered_picture_of_the_same_noun():
    scene, repairs = _validate('Strong winds carry tiny ice crystals up high.', ['ice_cube'], ('fl_cloud', 'fl_ice'))
    assert _pictures(scene) == ['fl_ice'], repairs
    assert any("drew the offered fl_ice, also a 'ice'" in r for r in repairs), repairs


def test_a_look_at_a_dropped_picture_never_borrows_another_scenes_held_thing():
    text = 'Find the drip under the sink. A faucet leaking one drop a second wastes water.'
    scene, repairs = _validate(text, [], shot=('first_person', 'hi_intravenous_drip'))
    shot, = scene['shots']
    assert shot['focus_ref'] == '' and shot['shot'] == 'medium', repairs     # no focus left: no reading insert
    assert any('drawn as a medium shot' in r for r in repairs), repairs


def test_a_picture_the_story_already_holds_stays_in_later_scenes():
    board = script.build(ingest.read('# List\n\nIt was a list, in a hand he did not know.\n\n'
                                     'Every line was a moment he had been fully there.'), story='showcase')
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    first = copy.deepcopy(plan['scenes'][0])
    first.update(beat_ids=[bids[0]], shots=[], boards=[], elements=[{'kind': 'picture', 'ref': 'tb_clipboard_list'}])
    later = copy.deepcopy(first)
    later.update(beat_ids=[bids[1]])
    plan['scenes'] = [first, later]
    kept = []
    out, repairs = validate(plan, board, {bid: [{'id': 'fl_cloud', 'desc': 'cloud'}] for bid in bids}, kept)
    assert [_pictures(s) for s in out['scenes']] == [['tb_clipboard_list'], ['tb_clipboard_list']], repairs
    assert any(k.startswith('scenes[1]: kept tb_clipboard_list') and 'already in the story' in k for k in kept), kept
    assert not [r for r in repairs if 'tb_clipboard_list' in r], repairs       # keeping is no change to repair


def test_kept_pictures_are_no_repairs_so_a_saved_plan_rechecks_clean():
    board = script.build(ingest.read('# List\n\nHe read the list twice before he folded it.'), story='showcase')
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    plan['scenes'][0].update(beat_ids=bids, elements=[{'kind': 'picture', 'ref': 'tb_clipboard_list'}])
    plan['scenes'] = plan['scenes'][:1]
    offered = {bid: [{'id': 'fl_cloud', 'desc': 'cloud'}] for bid in bids}
    fixed, _ = validate(plan, board, offered)
    kept = []
    assert validate(fixed, board, offered, kept) == (fixed, [])
    assert kept == ["scenes[0]: kept tb_clipboard_list, not offered: the words say 'list'"]

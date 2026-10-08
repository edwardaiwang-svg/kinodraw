"""A planned picture never silently disappears (gauntlet round 3): a saved plan keeps every library picture when a
later matcher offers others, a ref that names no library picture becomes the offered picture its words name, and a
board scene draws its scene's pictures beside the board's words."""
import copy

from kinodraw import ingest, script
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.validate import validate
from kinodraw.library import catalog

HEAT = ('# Heat\n\nThe return stroke heats the air to about five times hotter than the sun.\n\n'
        'Watch the clock and count the seconds between the flash and the thunder.')
LOGIN = ("# Two-Step Login\n\nTwo-step login means a stolen password isn't enough to get into your account. "
         "Lock it with a key only you hold.\n\nHere's how to set it up.")


def _board(text):
    return script.build(ingest.read(text), story='showcase')


def _offered(board, ids):
    return {b['id']: [{'id': i, 'desc': i} for i in ids] for b in board['beats']}


def _item(iid, beat, kind, cue='', ref='', to='', at='auto', text='', style='none'):
    return dict(id=iid, beat_id=beat, cue=cue, kind=kind, ref=ref, to=to, at=at, text=text, style=style)


def _one_scene(plan, bids, **fields):
    scene = copy.deepcopy(plan['scenes'][0])
    scene.update(beat_ids=bids, shots=[], boards=[], **fields)
    plan['scenes'] = [scene]
    return scene


def test_a_saved_plan_keeps_library_pictures_its_matcher_no_longer_offers():
    board = _board(HEAT)
    bids = [b['id'] for b in board['beats']]
    assert {'thermometer_hot', 'clock_fast'} <= set(catalog())
    plan = from_rules(board)
    _one_scene(plan, bids, treatment='whiteboard', elements=[{'kind': 'picture', 'ref': 'thermometer_hot'},
                                                             {'kind': 'picture', 'ref': 'clock_fast'},
                                                             {'kind': 'picture', 'ref': 'fl_field_hockey'}])
    out, repairs = validate(plan, board, _offered(board, ['fl_cloud']))      # today's offer names none of them
    refs = [e['ref'] for e in out['scenes'][0]['elements'] if e['kind'] == 'picture']
    # "heats ... hotter" names the hot thermometer, "the clock" the clock; nothing in the scene names field hockey
    assert refs == ['thermometer_hot', 'clock_fast'], repairs
    assert not [r for r in repairs if 'thermometer_hot' in r or 'clock_fast' in r], repairs
    assert any("out-of-scene picture ref 'fl_field_hockey'" in r for r in repairs), repairs


def test_shot_props_focus_and_board_pictures_keep_library_pictures_too():
    board = _board(HEAT)
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    scene = _one_scene(plan, bids, treatment='whiteboard', elements=[])
    scene['shots'] = [{'beat_id': bids[0], 'starts_at': '', 'shot': 'medium', 'setting': {
        'place': 'none', 'time': 'unknown', 'set_refs': []}, 'cast': [], 'lines': [],
        'props': [{'ref': 'thermometer_hot', 'relation': 'none', 'to': '', 'motion': 'none'}],
        'focus_ref': 'thermometer_hot', 'writing': ''}]
    scene['boards'] = [{'layout': 'parts', 'items': [
        _item('heat', bids[0], 'picture', 'heats the air', ref='thermometer_hot', at='center'),
        _item('word', bids[0], 'label', 'return stroke', to='heat', text='return stroke')]}]
    out, repairs = validate(plan, board, _offered(board, ['fl_cloud']))
    s = out['scenes'][0]
    assert [it['ref'] for b in s['boards'] for it in b['items'] if it['kind'] == 'picture'] == ['thermometer_hot']
    assert s['shots'][0]['focus_ref'] == 'thermometer_hot'
    assert [p['ref'] for p in s['shots'][0]['props']] == ['thermometer_hot']
    assert not [r for r in repairs if 'dropped picture' in r], repairs


def test_a_ref_no_library_picture_has_becomes_the_offered_picture_its_words_name():
    board = _board(HEAT)
    bids = [b['id'] for b in board['beats']]
    plan = from_rules(board)
    _one_scene(plan, bids, treatment='whiteboard', elements=[{'kind': 'picture', 'ref': 'hot_thermometer_icon'},
                                                             {'kind': 'picture', 'ref': 'zxq_blorp'}])
    out, repairs = validate(plan, board, _offered(board, ['fl_cloud', 'thermometer_hot']))
    refs = [e['ref'] for e in out['scenes'][0]['elements'] if e['kind'] == 'picture']
    assert refs == ['thermometer_hot'], repairs
    notes = '\n'.join(repairs)
    assert "read 'hot_thermometer_icon' as the offered picture thermometer_hot" in notes
    assert "dropped unknown or out-of-scene picture ref 'zxq_blorp'" in notes   # no picture is called that


def test_a_board_scene_draws_its_pictures_beside_the_boards_words():
    board = _board(LOGIN)
    bid = board['beats'][0]['id']
    plan = from_rules(board)
    scene = _one_scene(plan, [bid], treatment='whiteboard', elements=[{'kind': 'picture', 'ref': 'key_lock'},
                                                                      {'kind': 'picture', 'ref': 'fl_locked'}])
    plan['scenes'] += [s for s in from_rules(board)['scenes'] if bid not in s['beat_ids']]
    scene['boards'] = [{'layout': 'flow', 'items': [
        _item('password', bid, 'label', 'Two-step login means', at='left', text='stolen password'),
        _item('not_enough', bid, 'label', "isn't enough", at='right', text="isn't enough to get into your account"),
        _item('link', bid, 'link', 'Lock it', ref='password', to='not_enough', style='straight')]}]
    out, repairs = validate(plan, board, _offered(board, ['key_lock', 'fl_locked']))
    s = next(s for s in out['scenes'] if bid in s['beat_ids'])
    items = s['boards'][0]['items']
    pictures = [it for it in items if it['kind'] == 'picture']
    assert sorted(it['ref'] for it in pictures) == ['fl_locked', 'key_lock'], repairs
    assert next(it for it in pictures if it['ref'] == 'key_lock')['cue'] == 'Lock'  # when its beat names it
    assert next(it for it in pictures if it['ref'] == 'fl_locked')['cue'] == ''     # else from the scene start
    assert {it['id'] for it in items} >= {'password', 'not_enough', 'link'}         # the board's own words stay
    assert len({it['id'] for it in items}) == len(items)

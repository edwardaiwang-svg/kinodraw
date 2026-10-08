"""What the whole-video planner is offered (pictures per beat) and the optional per-shot staging it returns."""
import copy
import json

import pytest

from kinodraw import ingest, script
from kinodraw.director.llm.providers import StructuredResponseError, validate_structure
from kinodraw.director.llm.providers import ProviderError
from kinodraw.director.v3.llm import plan_v3
from kinodraw.director.v3.offer import CAP, fit
from kinodraw.director.v3.prompt import SYSTEM
from kinodraw.director.v3.schema import PLAN_SCHEMA, SCENE
from kinodraw.director.v3.validate import validate
from kinodraw.library import catalog

# An everyday human story (no animals) with places, furniture, objects and unnamed people.
STORY = """The Bakery

Maya lived in a small house at the end of a quiet street. Every morning she walked past the bakery on the corner.

One evening she went downstairs, where her grandfather was dozing in front of the television.

"Did you buy bread?" he asked. "I forgot," she said, and put her phone on the little table.

A stranger dropped a bag of apples on the sidewalk, and one rolled into the road.
"""


def _payload(text):
    seen = {}

    class Capture:
        name = 'capture'

        def direct_plan(self, payload, usage):
            seen.update(payload)
            raise ProviderError('captured')
    plan_v3(script.build(ingest.read(text), story='story'), provider=Capture())
    return seen


@pytest.fixture(scope='module')
def offered():
    payload = _payload(STORY)
    return payload, {b['beat_id']: [c['id'] for c in b['candidates']] for b in payload['beats']}


def _words(ids):
    return ' '.join(catalog()[i].get('desc', '') + ' ' + ' '.join(catalog()[i].get('en', [])) for i in ids).lower()


def test_each_beat_is_offered_its_places_furniture_objects_and_people(offered):
    payload, ids = offered
    beats = {b['beat_id']: b for b in payload['beats']}
    by_text = lambda words: next(bid for bid, b in beats.items() if words in b['text'])
    street, home, talk, drop = (ids[by_text('quiet street')], ids[by_text('went downstairs')],
                                ids[by_text('Did you buy')], ids[by_text('stranger dropped')])
    assert all(len(v) <= CAP for v in ids.values())
    assert 'house' in _words(street) and 'bakery' in _words(street) or 'shop' in _words(street)
    living = _words(home)
    assert 'couch' in living and 'television' in living and 'lamp' in living
    # the dozing grandfather can be drawn asleep and old (a people preset of that age and pose)
    assert any(i.startswith('cr_human_') and '_elder_' in i and i.endswith('_sleep_r') for i in home)
    # the story stays in the living room for the next beat, which also names a phone and a table
    assert 'couch' in _words(talk) and 'phone' in _words(talk) and 'table' in _words(talk)
    assert 'apple' in _words(drop) and ('road' in _words(drop) or 'street' in _words(drop))
    assert any(i.startswith('cr_human_') for i in drop)       # the stranger


def test_offer_has_no_interface_icons_and_few_faces(offered):
    _, ids = offered
    for bid, pictures in ids.items():
        cats = [catalog()[i].get('category') for i in pictures]
        assert not {'Arrows', 'Shapes', 'Charts'} & set(cats), bid
        assert sum(c in ('Smileys & Emotion', 'Mood', 'emotions') for c in cats) <= 2, bid


def test_fit_keeps_the_cloud_request_under_its_size_limit(offered):
    payload, _ = offered
    big = copy.deepcopy(payload)
    big['beats'] = [dict(copy.deepcopy(b), beat_id=f'{b["beat_id"]}_{n}') for n in range(6) for b in payload['beats']]
    before = sum(len(b['candidates']) for b in big['beats'])
    fit(big, 30_000)
    assert len(json.dumps({'video_id': 'x' * 36, 'storyboard': big})) <= 30_000
    assert 0 < sum(len(b['candidates']) for b in big['beats']) < before
    counts = [len(b['candidates']) for b in big['beats']]
    assert max(counts) - min(counts) <= max(1, max(counts) // 2) or min(counts) == 0


# ------------------------------------------------------------------ shots
def _board():
    return script.build(ingest.read(STORY), story='story')


def _plan(board):
    """A minimal valid plan: one scene per beat, cast Maya and her grandfather."""
    from kinodraw.director.v3.rules import from_rules
    plan = from_rules(board)
    plan['cast'] = [
        {'id': 'maya', 'name': 'Maya', 'kind': 'human', 'species': 'human', 'family': 'human', 'age': 'young',
         'sex': 'female', 'size': 1, 'palette': {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'},
         'marks': ['none'], 'temperament': 'gentle'},
        {'id': 'grandfather', 'name': 'her grandfather', 'kind': 'human', 'species': 'human', 'family': 'human',
         'age': 'old', 'sex': 'male', 'size': 1, 'palette': {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'},
         'marks': ['none'], 'temperament': 'wise'}]
    return plan


def _shot(bid, **kw):
    shot = {'beat_id': bid, 'starts_at': '', 'shot': 'wide',
            'setting': {'place': 'living_room', 'time': 'night', 'set_refs': []},
            'cast': [], 'lines': [], 'props': [], 'focus_ref': '', 'writing': ''}
    shot.update(kw)
    return shot


def test_old_plans_without_shots_still_validate_without_repairs():
    board = _board()
    plan = _plan(board)
    fixed, _ = validate(plan, board, {})
    for scene in fixed['scenes']:
        scene.pop('shots')
    validate_structure(fixed, PLAN_SCHEMA)                    # a Cloud or saved plan from before shots
    again, repairs = validate(fixed, board, {})
    assert not [r for r in repairs if 'shots' in r] and all(s['shots'] == [] for s in again['scenes'])
    broken = copy.deepcopy(fixed)
    broken['scenes'][0].pop('camera')                         # other fields stay required
    with pytest.raises(StructuredResponseError):
        validate_structure(broken, PLAN_SCHEMA)


def test_shots_keep_offered_pictures_real_cast_and_the_beats_own_words():
    board = _board()
    plan = _plan(board)
    beats = [b for b in board['beats']]
    talk = next(b for b in beats if 'Did you buy' in b['display']['en'])
    scene = next(s for s in plan['scenes'] if talk['id'] in s['beat_ids'])
    scene['elements'] = []
    scene['shots'] = [_shot(
        talk['id'], shot='two_shot', starts_at='Did you buy bread',
        setting={'place': 'living_room', 'time': 'night', 'set_refs': ['fl_couch_and_lamp', 'not_offered', 'TV']},
        cast=[{'id': 'maya', 'age': 'teen', 'pose': 'stand', 'speaking': 'yes'},
              {'id': 'ghost', 'age': 'adult', 'pose': 'stand', 'speaking': 'no'}],
        lines=[{'quote': 'Did you buy bread?', 'speaker': 'grandfather'},
               {'quote': 'I forgot', 'speaker': 'maya'},
               {'quote': 'invented words', 'speaker': 'maya'}],
        props=[{'ref': 'fl_mobile_phone', 'relation': 'on', 'to': 'tb_table', 'motion': 'none'},
               {'ref': 'fl_television', 'relation': 'held_by', 'to': 'fl_couch_and_lamp', 'motion': 'none'}],
        focus_ref='fl_mobile_phone', writing='not in the beat'),
        _shot('b999')]
    offered = {talk['id']: ['fl_couch_and_lamp', 'fl_mobile_phone', 'tb_table', 'fl_television']}
    fixed, repairs = validate(plan, board, offered)
    out = next(s for s in fixed['scenes'] if talk['id'] in s['beat_ids'])
    shot, = out['shots']
    assert shot['setting']['set_refs'] == ['fl_couch_and_lamp', 'fl_television']   # "TV" read as the offered TV
    assert [c['id'] for c in shot['cast']] == ['maya', 'grandfather']          # the speaker joins the shot
    assert shot['cast'][1] == {'id': 'grandfather', 'age': 'old', 'pose': 'talk', 'speaking': 'yes'}
    assert [line['speaker'] for line in shot['lines']] == ['grandfather', 'maya']
    # the phone stays on the table (not in this shot: the relation is dropped); a TV is not "held by" a couch
    assert [(p['ref'], p['relation'], p['to']) for p in shot['props']] == [
        ('fl_mobile_phone', 'none', ''), ('fl_television', 'none', '')]
    assert shot['focus_ref'] == 'fl_mobile_phone' and shot['writing'] == '' and shot['starts_at'] == 'Did you buy bread'
    assert {e['ref'] for e in out['elements'] if e['kind'] == 'picture'} == {
        'fl_couch_and_lamp', 'fl_mobile_phone', 'fl_television'}
    # everyone on screen in a shot is staged in the scene too (the renderer stages scene cast elements)
    assert {e['ref'] for e in out['elements'] if e['kind'] == 'cast'} == {'maya', 'grandfather'}
    assert any('not offered' in r for r in repairs) and any('beats outside the scene' in r for r in repairs)
    again, more = validate(fixed, board, offered)                 # repairs are stable: a saved plan re-checks clean
    assert again == fixed and more == []


def test_schema_and_prompt_ask_for_staging():
    shot = SCENE['properties']['shots']['items']['properties']
    assert set(shot) == {'beat_id', 'starts_at', 'shot', 'setting', 'cast', 'lines', 'props', 'focus_ref', 'writing'}
    assert {'insert', 'first_person', 'two_shot', 'wide'} <= set(shot['shot']['enum'])
    assert set(shot['cast']['items']['properties']) == {'id', 'age', 'pose', 'speaking'}
    assert 'off_screen' in shot['cast']['items']['properties']['speaking']['enum']
    for rule in ('insert', 'first_person', 'off_screen', 'real speaker', 'age the story gives at that moment',
                 'camera static unless', 'picture ids copied exactly from the candidates'):
        assert rule in SYSTEM

"""Plans put on screen what the text names: its people (with the ages it gives), one time of day, each shot's named
focus, and the places and gear its nouns imply (director/v3 literal repairs and the per-beat offer)."""
from __future__ import annotations

import copy

import pytest

from kinodraw import ingest, script
from kinodraw.director.llm.providers import ProviderError
from kinodraw.director.v3.llm import plan_v3
from kinodraw.director.v3.rules import from_rules
from kinodraw.library import catalog

PALETTE = {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'}


def _board(text):
    return script.build(ingest.read(text), story='story')


def _human(cid, name, age):
    return {'id': cid, 'name': name, 'kind': 'human', 'species': 'human', 'family': 'human', 'age': age,
            'sex': 'unknown', 'size': 1, 'palette': dict(PALETTE), 'marks': ['none'], 'temperament': 'gentle'}


def _shot(bid, **kw):
    shot = {'beat_id': bid, 'starts_at': '', 'shot': 'wide', 'setting': {'place': 'car', 'time': 'unknown',
                                                                          'set_refs': []},
            'cast': [], 'lines': [], 'props': [], 'focus_ref': '', 'writing': ''}
    shot.update(kw)
    return shot


class Answer:
    """A provider that answers with a fixed plan (and records the offer)."""
    name = 'answer'

    def __init__(self, plan):
        self.plan, self.payload = plan, None

    def direct_plan(self, payload, usage):
        self.payload = payload
        return copy.deepcopy(self.plan)


def _ids(board):
    return [b['id'] for b in board['beats'] if b.get('kind') != 'title']


def _plan(board, offered, edit):
    """from_rules as a valid template, every beat offered ``offered``, then ``edit(plan, beat ids)``."""
    plan = from_rules(board)
    plan['storyboard']['genre'] = 'story'
    edit(plan, [bid for s in plan['scenes'] for bid in s['beat_ids']])

    class Offering(Answer):
        def direct_plan(self, payload, usage):
            for b in payload['beats']:
                b['candidates'] += [{'id': p, 'desc': p} for p in offered
                                    if p not in {c['id'] for c in b['candidates']}]
            return Answer.direct_plan(self, payload, usage)
    return plan_v3(board, provider=Offering(plan))     # the validator checks pictures against these same lists


def test_a_story_keeps_one_time_of_day_until_the_text_says_otherwise():
    board = _board('The car had been quiet for miles.\n\nThe headlights lit up a fence.\n\nA truck went by.\n')

    def edit(plan, bids):
        for scene, time in zip(plan['scenes'], ('unknown', 'night', 'unknown')):
            scene['shots'] = [_shot(scene['beat_ids'][0], setting={'place': 'car', 'time': time, 'set_refs': []})]
    plan, report = _plan(board, [], edit)
    assert not report['fallback'], report['fallback_reason']
    times = [shot['setting']['time'] for s in plan['scenes'] for shot in s['shots']]
    assert times == ['night', 'night', 'night']                # no daylight sky at the start of a night drive


def test_a_stated_adult_age_is_never_drawn_old():
    board = _board('Dev turns 50!!\n\nDev ran the store for years.\n')

    def edit(plan, bids):
        plan['cast'] = [_human('dev', 'Dev', 'old')]
        plan['scenes'][0]['shots'] = [_shot(bids[0], cast=[{'id': 'dev', 'age': 'old', 'pose': 'stand',
                                                              'speaking': 'no'}])]
    plan, _ = _plan(board, [], edit)
    dev = next(c for c in plan['cast'] if c['id'] == 'dev')
    assert dev['age'] == 'adult'
    assert all(m['age'] != 'old' for s in plan['scenes'] for shot in s['shots'] for m in shot['cast'])


def test_an_elderly_person_stays_old():
    board = _board('Grandma Rose turns 60 today.\n')

    def edit(plan, bids):
        plan['cast'] = [_human('rose', 'Grandma Rose', 'old')]
    plan, _ = _plan(board, [], edit)
    assert next(c for c in plan['cast'] if c['id'] == 'rose')['age'] == 'old'


def test_a_shots_named_focus_is_drawn():
    board = _board('A goat stood in the road. "Look," she said.\n')

    def edit(plan, bids):
        plan['scenes'][0]['shots'] = [_shot(bids[0], shot='two_shot', focus_ref='fl_goat'),
                                      _shot(bids[0], shot='insert', starts_at='', focus_ref='fl_goat')]
    plan, _ = _plan(board, ['fl_goat'], edit)
    two, insert = plan['scenes'][0]['shots']
    assert [p['ref'] for p in two['props']] == ['fl_goat']       # a two_shot does not look at its focus: a prop
    assert insert['props'] == []                                # an insert draws its focus itself


def test_a_thing_only_talked_about_gets_an_insert_while_the_line_goes_on():
    board = _board('"There was a goat. I remember the goat."\n')

    def edit(plan, bids):
        plan['scenes'][0]['shots'] = [_shot(bids[0], shot='close', focus_ref='fl_goat')]
    plan, _ = _plan(board, ['fl_goat'], edit)
    close, insert = plan['scenes'][0]['shots']
    assert close['props'] == []                                 # a goat in the car would be dropped as talked about
    assert (insert['shot'], insert['focus_ref'], insert['starts_at']) == ('insert', 'fl_goat', 'I remember the goat.')
    again, _ = plan_v3(board, provider=Answer(plan))           # a saved plan re-checks to the same shots
    assert again['scenes'][0]['shots'] == plan['scenes'][0]['shots']


def test_the_person_a_greeting_addresses_and_its_writer_are_on_screen():
    board = _board("Happy 25th Jo, twenty-five years and you're still stealing my fries.\n")

    def edit(plan, bids):
        plan['cast'] = []
        for scene in plan['scenes']:
            scene.update(treatment='motion', elements=[], shots=[_shot(scene['beat_ids'][0], shot='wide'),
                                                                 _shot(scene['beat_ids'][0], shot='insert')])
    plan, report = _plan(board, [], edit)
    assert [c['name'] for c in plan['cast']] == ['Jo', 'Speaker']
    scene, = plan['scenes']
    ids = [c['id'] for c in plan['cast']]
    assert [e['ref'] for e in scene['elements'] if e['kind'] == 'cast'] == ids and scene['treatment'] == 'character'
    wide, insert = scene['shots']
    assert [m['id'] for m in wide['cast']] == ids and insert['cast'] == []


# ------------------------------------------------------------------ the offer
BULLETS = """Aunt Mae turns 60!

- grew up in Cedar Springs
- ran Lark Hardware for years
- terrible fisherman
- 4 grandkids
"""


@pytest.fixture(scope='module')
def offer():
    class Capture:
        name = 'capture'

        def direct_plan(self, payload, usage):
            self.payload = payload
            raise ProviderError('captured')
    cap = Capture()
    plan_v3(_board(BULLETS), provider=cap)
    return {b['spoken']: [c['id'] for c in b['candidates']] for b in cap.payload['beats']}


def _words(ids):
    return ' '.join(catalog()[i].get('desc', '') for i in ids).lower()


def _beat(offer, words):
    return next(ids for spoken, ids in offer.items() if words in spoken)


def test_named_places_activities_and_counted_people_bring_their_pictures(offer):
    assert 'house' in _words(_beat(offer, 'Cedar Springs'))                 # a named town: its houses
    shop = _words(_beat(offer, 'Lark Hardware'))
    assert 'shop' in shop and ('hammer' in shop or 'wrench' in shop)       # a hardware store, not a memory chip
    fishing = _words(_beat(offer, 'fisherman'))
    assert 'fishing pole' in fishing and ('canoe' in fishing or 'boat' in fishing) and 'lake' in fishing
    assert any(i.startswith('cr_human_') and '_child_' in i for i in _beat(offer, 'grandkids'))
    assert 'birthday cake' in _words(_beat(offer, 'turns'))

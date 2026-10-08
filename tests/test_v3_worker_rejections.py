"""The round-0 rejections of whole Luna plans (hold too short, a colour that is not #rrggbb, an action by an actor
the beat never names, a picture ref that was never offered) are small faults: the client repairs them with a note
and the plan is used, never replaced by the offline plan."""
import copy
import json

import pytest

from kinodraw import ingest, script
from kinodraw.director.llm import providers
from kinodraw.director.v3.llm import plan_v3

TEXT = '# Night Walk\n\nMara walked to the lake.\n\nThe moon rose over the water.'


class Answer:
    name = 'luna'

    def __init__(self, change):
        self.change, self.calls = change, 0

    def direct_plan(self, payload, usage):
        self.calls += 1
        plan, _ = plan_v3(TEXT)                     # a well-formed plan for this script
        self.change(plan, payload)
        return providers.validate_structure(json.loads(json.dumps(plan)), __import__(
            'kinodraw.director.v3.schema', fromlist=['PLAN_SCHEMA']).PLAN_SCHEMA)


def _hold(plan, payload):
    plan['scenes'][0]['hold_s'] = 0.1


def _colour(plan, payload):
    plan['style']['palette']['accent'] = 'orange'


def _actor(plan, payload):
    plan['cast'].append({**copy.deepcopy(plan['cast'][0] if plan['cast'] else {
        'kind': 'human', 'species': 'human', 'family': 'human', 'age': 'adult', 'sex': 'female', 'size': 1,
        'palette': {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'}, 'marks': ['none'],
        'temperament': 'gentle'}), 'id': 'young_mara', 'name': 'Mara as a little girl'})
    plan['scenes'][-1]['actions'] = [{'actor': 'young_mara', 'verb': 'run', 'at_beat': plan['scenes'][-1]['beat_ids'][0],
                                      'intensity': 2}]


def _picture(plan, payload):
    plan['scenes'][0]['elements'].append({'kind': 'picture', 'ref': plan['scenes'][0]['beat_ids'][0]})


def _colours(plan, payload):
    plan['style']['palette'].update(accent2='abc', background='rgb(255, 250, 240)')
    if plan['cast']:
        plan['cast'][0]['palette'].update(eye='cream', accent='warm gold')


@pytest.mark.parametrize('change,note', [(_hold, 'hold_s: extended'), (_colour, "read colour 'orange' as #FFA500"),
                                         (_colours, "accent2: read colour 'abc' as #AABBCC"),
                                         (_colours, "background: read colour 'rgb(255, 250, 240)' as #FFFAF0"),
                                         (_colours, "accent: read colour 'warm gold' as #FFD700"),
                                         (_colours, "eye: replaced invalid hex colour 'cream'"),
                                         (_actor, 'dropped action run by'), (_picture, 'dropped unknown or out-of-scene picture')])
def test_small_faults_are_repaired_not_fallen_back(change, note):
    provider = Answer(change)
    plan, report = plan_v3(TEXT, provider)
    assert provider.calls == 1 and not report['fallback'], report['fallback_reason']
    assert any(note in r for r in report['repairs']), report['repairs']


GROWN = ('# Home Video\n\nDana laughed at the screen.\n\n'
         'The TV showed a little girl in a yellow raincoat jumping in puddles.\n\nNobody remembered the rain.')


def _young_dana(actor, beat):
    def change(plan, payload):
        cast = plan['cast'][0] if plan['cast'] else None
        base = copy.deepcopy(cast) if cast else {
            'kind': 'human', 'species': 'human', 'family': 'human', 'age': 'adult', 'sex': 'female', 'size': 1,
            'palette': {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'}, 'marks': ['none'],
            'temperament': 'gentle'}
        plan['cast'] = [dict(base, id='dana', name='Dana', age='adult'),
                        dict(base, id='young_dana', name='Dana as a little girl', age='baby')]
        bid = payload['beats'][beat]['beat_id']
        for scene in plan['scenes']:
            scene['actions'] = []
        scene = next(s for s in plan['scenes'] if bid in s['beat_ids'])
        scene['actions'] = [{'actor': actor, 'verb': 'run', 'at_beat': bid, 'intensity': 2}]
    return change


@pytest.mark.parametrize('actor,beat,kept,note', [
    # round 0 (Movie Night): the action used the display name, and the beat shows "a little girl", not "Dana"
    ('Dana as a little girl', 1, 'young_dana', "read as cast id 'young_dana'"),
    ('young_dana', 1, 'young_dana', None),
    ('young Dana', 0, 'young_dana', "read as cast id 'young_dana'"),   # an alias picks the younger variant
    ('Dana', 0, 'dana', "read as cast id 'dana'"),
    ('Dana as a little girl', 2, None, 'dropped action run by'),       # not on screen: only that action goes
])
def test_actor_display_names_map_to_cast_ids(actor, beat, kept, note):
    provider = type('P', (Answer,), {'direct_plan': lambda self, payload, usage: _direct(self, payload, usage)})(
        _young_dana(actor, beat))
    plan, report = plan_v3(GROWN, provider)
    assert not report['fallback'], report['fallback_reason']
    actions = [a for s in plan['scenes'] for a in s['actions']]
    assert [a['actor'] for a in actions] == ([kept] if kept else [])
    assert note is None or any(note in r for r in report['repairs']), report['repairs']
    assert {c['id'] for c in plan['cast']} >= {'dana', 'young_dana'}


def _direct(self, payload, usage):
    self.calls += 1
    plan, _ = plan_v3(GROWN)
    self.change(plan, payload)
    from kinodraw.director.v3.schema import PLAN_SCHEMA
    return providers.validate_structure(json.loads(json.dumps(plan)), PLAN_SCHEMA)


def _staged(actor, text_beat, staged):
    def change(plan, payload):
        base = plan['cast'][0] if plan['cast'] else {
            'kind': 'human', 'species': 'human', 'family': 'human', 'age': 'adult', 'sex': 'female', 'size': 1,
            'palette': {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'}, 'marks': ['none'],
            'temperament': 'gentle'}
        plan['cast'] = [dict(copy.deepcopy(base), id='nainai', name='奶奶', age='old')]
        for scene in plan['scenes']:
            scene['actions'] = []
            scene['elements'] = [e for e in scene['elements'] if e['kind'] != 'cast']
        bid = payload['beats'][text_beat]['beat_id']
        scene = next(s for s in plan['scenes'] if bid in s['beat_ids'])
        if staged:
            scene['elements'].append({'kind': 'cast', 'ref': 'nainai'})
        scene['actions'] = [{'actor': actor, 'verb': 'point', 'at_beat': bid, 'intensity': 1}]
    return change


VOICE = '# 第一条语音\n\n奶奶拿起手机。\n\n她笑着按下了按钮，说了第一句话。\n\n大家都听见了。'


@pytest.mark.parametrize('actor,staged,kept', [
    ('奶奶', True, True),          # round 0 (08): a Chinese display name, and the beat says only "她" (she)
    ('nainai', True, True),        # staged in the scene: a pronoun or "you" beat keeps the action
    ('nainai', False, False),      # neither named nor staged: only that action is dropped, with a note
])
def test_actions_by_cast_staged_in_the_scene_are_kept(actor, staged, kept):
    class P(Answer):
        def direct_plan(self, payload, usage):
            self.calls += 1
            plan, _ = plan_v3(VOICE)
            self.change(plan, payload)
            from kinodraw.director.v3.schema import PLAN_SCHEMA
            return providers.validate_structure(json.loads(json.dumps(plan)), PLAN_SCHEMA)
    plan, report = plan_v3(VOICE, P(_staged(actor, 1, staged)))
    assert not report['fallback'], report['fallback_reason']
    actions = [a for s in plan['scenes'] for a in s['actions']]
    assert [a['actor'] for a in actions] == (['nainai'] if kept else [])
    assert kept or any('not named or staged in the scene' in r for r in report['repairs'])

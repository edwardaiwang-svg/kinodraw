"""Contract, repair, offline genre grammar and the real legacy renderer bridge."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from kinodraw import ingest, script, styles
from kinodraw.director.rules import RulesDirector as PictureDirector
from kinodraw.director.v3.adapter import adapt
from kinodraw.director.v3.prompt import SYSTEM
from kinodraw.director.v3.rules import RulesDirector, detect_genre, from_rules, offline_candidates
from kinodraw.director.v3.schema import PLAN_SCHEMA, SKINS, schema_json
from kinodraw.director.v3.validate import contrast, validate
from kinodraw.director.validate import _doodles, validate as validate_legacy
from kinodraw.engine import render, timeline

FIX = Path(__file__).parent / 'fixtures' / 'genre'
SCRATCH = Path('/tmp/kd1005/a2-schema-fix1')


def _assert_shape(value, schema):
    kind = schema['type']
    if kind == 'object':
        assert set(value) == set(schema['properties'])
        for key, sub in schema['properties'].items():
            _assert_shape(value[key], sub)
    elif kind == 'array':
        assert isinstance(value, list)
        for v in value:
            _assert_shape(v, schema['items'])
    elif kind == 'string':
        assert isinstance(value, str)
    elif kind == 'integer':
        assert isinstance(value, int) and not isinstance(value, bool)
    elif kind == 'number':
        assert isinstance(value, (float, int)) and not isinstance(value, bool)
    if 'enum' in schema:
        assert value in schema['enum']


@pytest.fixture(scope='module')
def drafts():
    return {p.stem: PictureDirector('en').direct(script.build(ingest.read(p), story='story'))
            for p in sorted(FIX.glob('*.md'))}


@pytest.fixture(scope='module')
def plans(drafts):
    return {name: from_rules(board) for name, board in drafts.items()}


def _candidates(board):
    """What the offline director offers: the rules draft's pictures and the things each sentence names."""
    return {bid: [{'id': p, 'desc': 'offered'} for p in offered] for bid, offered in offline_candidates(board).items()}


def test_schema_is_strict_and_storyboard_first():
    def walk(schema):
        assert not set(schema) & {'minimum', 'maximum', 'minItems', 'maxItems', 'pattern', 'format'}
        if schema['type'] == 'object':
            assert schema['additionalProperties'] is False
            assert schema['required'] == list(schema['properties'])
            for sub in schema['properties'].values():
                walk(sub)
        elif schema['type'] == 'array':
            walk(schema['items'])
    walk(PLAN_SCHEMA)
    assert next(iter(PLAN_SCHEMA['properties'])) == 'storyboard'
    assert json.loads(schema_json()) == PLAN_SCHEMA
    assert set(SKINS) == {e['id'] for e in styles.looks() if e['renderer'] == 'whiteboard'}
    assert PLAN_SCHEMA['properties']['style']['properties']['whiteboard_skin']['enum'] == list(SKINS)


@pytest.mark.parametrize('genre', ['story', 'explainer', 'launch', 'lesson', 'news', 'poem'])
def test_valid_plans_round_trip_unchanged(genre, plans, drafts):
    plan = plans[genre]
    before = copy.deepcopy(plan)
    fixed, repairs = validate(plan, drafts[genre], _candidates(drafts[genre]))
    _assert_shape(plan, PLAN_SCHEMA)
    assert fixed == before == plan
    assert repairs == []
    assert [b for s in plan['scenes'] for b in s['beat_ids']] == [b['id'] for b in drafts[genre]['beats']]


def test_rules_use_distinct_grammars(plans):
    expected = {'story': ('story', 'hybrid', {'atmosphere', 'character'}),
                'explainer': ('explainer', 'hybrid', {'whiteboard', 'kinetic_type'}),
                'launch': ('launch/promo', 'motion', {'motion', 'kinetic_type'}),
                'lesson': ('lesson', 'whiteboard', {'whiteboard'}),
                'news': ('news/data', 'motion', {'motion', 'chart'}),
                'poem': ('poem', 'motion', {'atmosphere'})}
    mixes = set()
    for name, (genre, mode, treatments) in expected.items():
        plan = plans[name]
        assert plan['storyboard']['genre'] == genre
        assert plan['style']['mode'] == mode
        chosen = {s['treatment'] for s in plan['scenes']}
        assert treatments <= chosen
        mixes.add((mode, frozenset(chosen)))
    assert len(mixes) >= 4


def test_cast_comes_from_the_story_and_is_distinct(plans):
    cast = {c['name']: c for c in plans['story']['cast']}
    assert set(cast) == {'Pendo', 'Mara', 'Kojo'}
    assert cast['Pendo']['species'] == 'lion' and cast['Pendo']['age'] == 'baby'
    assert 'mane_none' in cast['Pendo']['marks']
    assert 'stripes' not in cast['Pendo']['marks']
    assert cast['Mara']['species'] == 'tigress' and cast['Mara']['sex'] == 'female'
    assert 'stripes' in cast['Mara']['marks']
    assert cast['Kojo']['size'] == 1.4 and cast['Kojo']['age'] == 'adult'
    assert {'mane_black', 'scar_nose', 'crown'} <= set(cast['Kojo']['marks'])
    assert len({c['palette']['body'] for c in cast.values()}) == 3
    scenes = plans['story']['scenes']
    fog = next(s for s in scenes if s['atmosphere']['kind'] == 'fog_with_shooting_star')
    assert fog['treatment'] == 'atmosphere'
    verbs = {a['verb'] for s in scenes for a in s['actions']}
    assert {'roar', 'nudge', 'whimper', 'walk', 'laugh'} <= verbs


def test_broken_plan_repairs_are_listed_and_input_is_untouched(plans, drafts):
    board = drafts['story']
    plan = copy.deepcopy(plans['story'])
    ids = [b['id'] for b in board['beats']]
    plan['style']['energy'] = 99
    plan['style']['tempo_bpm'] = 0
    plan['style']['palette']['ink'] = plan['style']['palette']['background']
    plan['cast'][0]['size'] = 9
    plan['cast'][0]['palette']['body'] = 'orange'
    mara = next(c for c in plan['cast'] if c['name'] == 'Mara')
    kojo = next(c for c in plan['cast'] if c['name'] == 'Kojo')
    plan['cast'].remove(mara)
    plan['scenes'][0]['beat_ids'] = [ids[-1], ids[0], ids[0], 'unknown']
    plan['scenes'] = plan['scenes'][:-1]
    plan['scenes'][0]['elements'] += [{'kind': 'picture', 'ref': 'not_offered'}, {'kind': 'cast', 'ref': 'ghost'}]
    plan['scenes'][0]['actions'] = [{'actor': kojo['id'], 'verb': 'roar', 'at_beat': ids[0], 'intensity': 9}]
    plan['scenes'][0]['atmosphere']['density'] = 8
    for scene in plan['scenes']:
        scene['hold_s'] = 0
    del plan['scenes'][1]
    plan['unexpected'] = True
    before = copy.deepcopy(plan)
    fixed, repairs = validate(plan, board, _candidates(board))
    assert plan == before
    _assert_shape(fixed, PLAN_SCHEMA)
    assert [b for s in fixed['scenes'] for b in s['beat_ids']] == ids
    assert fixed['style']['energy'] == 5 and fixed['style']['tempo_bpm'] == 40
    assert fixed['cast'][0]['size'] == 2
    assert contrast(fixed['style']['palette']['background'], fixed['style']['palette']['ink']) >= 4.5
    assert 'Mara' in {c['name'] for c in fixed['cast']}
    assert all('ghost' != e['ref'] != 'not_offered' for s in fixed['scenes'] for e in s['elements'])
    assert not any(a['at_beat'] == ids[0] for s in fixed['scenes'] for a in s['actions'])
    for phrase in ('clamped', 'contrast', 'Mara', 'duplicate beat', 'reordered', 'missing beat', 'split',
                   'not_offered', 'ghost', 'dropped action', 'reading', 'unknown property', "read colour 'orange'"):
        assert any(phrase in r for r in repairs), (phrase, repairs)
    assert all(isinstance(r, str) and r for r in repairs)
    assert validate(fixed, board, _candidates(board)) == (fixed, [])


@pytest.mark.parametrize('mode', ['whiteboard', 'motion'])
def test_mode_forces_compatible_treatments(mode, plans, drafts):
    plan = copy.deepcopy(plans['explainer'])
    plan['style']['mode'] = mode
    fixed, repairs = validate(plan, drafts['explainer'], _candidates(drafts['explainer']))
    assert repairs
    if mode == 'whiteboard':
        assert {s['treatment'] for s in fixed['scenes']} == {'whiteboard'}
    else:
        assert all(s['treatment'] != 'whiteboard' for s in fixed['scenes'])


@pytest.mark.parametrize('background', ['#FFFFFF', '#000000', '#777777'])
def test_contrast_darkens_or_lightens_ink(background, plans, drafts):
    plan = copy.deepcopy(plans['explainer'])
    plan['style']['palette'].update(background=background, ink=background)
    fixed, repairs = validate(plan, drafts['explainer'], _candidates(drafts['explainer']))
    assert contrast(background, fixed['style']['palette']['ink']) >= 4.5
    assert any('darkened' in r or 'lightened' in r for r in repairs)


def test_actions_need_a_mentioned_actor_and_correct_beat(plans, drafts):
    plan = copy.deepcopy(plans['story'])
    scene = next(s for s in plan['scenes'] if s['actions'])
    good = copy.deepcopy(scene['actions'][0])
    scene['actions'] = [{**good, 'intensity': -4}, {**good, 'actor': 'ghost'},
                        {**good, 'at_beat': 'unknown'}, {**good, 'actor': 'kojo'}]
    fixed, repairs = validate(plan, drafts['story'], _candidates(drafts['story']))
    actions = next(s for s in fixed['scenes'] if s['beat_ids'] == scene['beat_ids'])['actions']
    assert actions == [{**good, 'intensity': 1}]
    assert sum('dropped action' in r for r in repairs) == 3


def test_text_refs_are_scoped_and_multibeat_reading_is_summed(plans, drafts):
    board = drafts['explainer']
    plan = copy.deepcopy(plans['explainer'])
    scene = copy.deepcopy(plan['scenes'][0])
    ids = [b['id'] for b in board['beats']]
    scene['beat_ids'] = ids
    scene['elements'] = [{'kind': 'text', 'ref': ids[-1]}, {'kind': 'text', 'ref': 'unknown'}]
    scene['text'] = {'kind': 'caption_only', 'ref': ids[0]}
    scene['hold_s'] = 0
    plan['scenes'] = [scene]
    fixed, repairs = validate(plan, board, _candidates(board))
    assert fixed['scenes'][0]['hold_s'] == sum(len(b['display']['en']) for b in board['beats']) / 27
    assert fixed['scenes'][0]['elements'] == [{'kind': 'text', 'ref': ids[-1]}]
    assert any('unknown' in r for r in repairs)
    plan['scenes'][0]['text'] = {'kind': 'quote', 'ref': 'unknown'}
    assert validate(plan, board, _candidates(board))[0]['scenes'][0]['text'] == {'kind': 'none', 'ref': ''}


def test_candidate_offers_are_per_scene_and_use_word_boundaries(plans, drafts):
    board = drafts['story']
    plan = copy.deepcopy(plans['story'])
    scene = plan['scenes'][0]
    scene['elements'] = [{'kind': 'picture', 'ref': 'book_stack'}]
    first, last = board['beats'][0]['id'], board['beats'][-1]['id']
    fixed, repairs = validate(plan, board, {first: [], last: ['book_stack']})
    assert not fixed['scenes'][0]['elements'] and any('book_stack' in r for r in repairs)
    from kinodraw.director.v3.semantics import mentions
    assert not mentions('Ann', 'A banner waves.')
    assert mentions('King Kojo', "Kojo's mane moves.")


@pytest.mark.parametrize('text', ['Pendo, a lion cub, walked beside Mara, an adult tigress.',
                                 'The lion cub Pendo watched the adult tigress Mara.'])
def test_adjacent_names_do_not_share_species_or_marks(text):
    from kinodraw.director.v3.semantics import beats, detect_cast
    cast = {c['name']: c for c in detect_cast(beats([{'id': 'b1', 'text': text}]))}
    assert cast['Pendo']['species'] == 'lion' and cast['Pendo']['age'] == 'baby'
    assert 'stripes' not in cast['Pendo']['marks']
    assert cast['Mara']['species'] == 'tigress' and cast['Mara']['age'] == 'adult'
    assert cast['Mara']['marks'] == ['stripes']


def test_once_named_speaker_is_added_to_the_cast(plans):
    fixed, repairs = validate(plans['story'], [{'id': 'b1', 'text': 'Ada said hello.'}], [])
    assert 'Ada' in {c['name'] for c in fixed['cast']}
    assert any('added named character Ada' in r for r in repairs)


def test_adapter_keeps_multibeat_pictures_on_their_original_beat(drafts, plans):
    board = copy.deepcopy(drafts['explainer'])
    first, second = board['beats'][:2]
    first['visuals'] = [{'id': 'old1', 'type': 'cluster', 'items': [{'doodle': 'book_stack'}]}]
    second['visuals'] = [{'id': 'old2', 'type': 'cluster', 'items': [{'doodle': 'lightbulb_idea'}]}]
    plan = copy.deepcopy(plans['explainer'])
    plan['scenes'][0]['beat_ids'].append(second['id'])
    del plan['scenes'][1]
    plan['scenes'][0]['elements'] = [{'kind': 'picture', 'ref': p} for p in ('book_stack', 'lightbulb_idea')]
    legacy, _ = adapt(plan, board)
    assert set(_doodles(legacy['beats'][0]['visuals'])) == {'book_stack'}
    assert set(_doodles(legacy['beats'][1]['visuals'])) == {'lightbulb_idea'}


def test_shape_damage_and_nonfinite_ranges_are_repaired(plans, drafts):
    plan = copy.deepcopy(plans['explainer'])
    del plan['storyboard']['arc']
    plan['style']['mode'] = 'cinema'
    plan['style']['tempo_bpm'] = float('inf')
    plan['style']['energy'] = True
    plan['scenes'][0]['hold_s'] = float('nan')
    plan['scenes'][0]['actions'] = 'bad'
    fixed, repairs = validate(plan, drafts['explainer'], _candidates(drafts['explainer']))
    _assert_shape(fixed, PLAN_SCHEMA)
    assert repairs and fixed['style']['energy'] == 1
    assert validate(fixed, drafts['explainer'], _candidates(drafts['explainer'])) == (fixed, [])


def test_empty_answer_gains_cast_and_full_coverage(drafts):
    board = drafts['story']
    fixed, repairs = validate({}, board, _candidates(board))
    _assert_shape(fixed, PLAN_SCHEMA)
    assert [bid for s in fixed['scenes'] for bid in s['beat_ids']] == [b['id'] for b in board['beats']]
    assert {c['name'] for c in fixed['cast']} == {'Pendo', 'Mara', 'Kojo'}
    assert repairs


def test_duplicate_script_ids_are_an_input_error(plans):
    with pytest.raises(ValueError, match='unique'):
        validate(plans['story'], [{'id': 'x', 'text': 'a'}, {'id': 'x', 'text': 'b'}], [])


def test_director_builds_a_plan_without_mutating_the_board():
    board = script.build(ingest.read('# A lesson\n\nDraw three dots. Count each dot.'), story='story')
    before = copy.deepcopy(board)
    plan = RulesDirector('en').direct(board)
    assert board == before
    _assert_shape(plan, PLAN_SCHEMA)
    assert plan['style']['mode'] == 'whiteboard'


def test_adapter_selects_new_pictures_and_preserves_richer_visuals(drafts, plans):
    board = drafts['news']
    before = copy.deepcopy(board)
    plan = copy.deepcopy(plans['news'])
    plan['scenes'][0]['elements'] = [{'kind': 'picture', 'ref': 'book_stack'}]
    legacy, treatments = adapt(plan, board)
    assert board == before
    assert 'book_stack' in set(_doodles(legacy['beats'][0]['visuals']))
    for original, adapted in zip(board['beats'], legacy['beats']):
        assert all(v in adapted['visuals'] for v in original['visuals'] if v['type'] != 'cluster')
    assert validate_legacy(legacy)['ok']
    assert treatments == plan['scenes']
    treatments[0]['actions'].append({})
    assert treatments != plan['scenes']


def test_adapter_obeys_selected_items_inside_a_rules_cluster(drafts, plans):
    board = copy.deepcopy(drafts['explainer'])
    beat = board['beats'][0]
    beat['visuals'] = [{'id': 'cluster', 'type': 'cluster', 'relation': 'plus',
                        'trigger': {'en': 'battery'}, 'items': [
                            {'doodle': 'lightbulb_idea', 'trigger': {'en': 'battery'}},
                            {'doodle': 'book_stack', 'trigger': {'en': 'energy'}, 'label': {'en': 'Energy'}}]}]
    plan = copy.deepcopy(plans['explainer'])
    plan['scenes'][0]['elements'] = [{'kind': 'picture', 'ref': 'book_stack'}]
    legacy, _ = adapt(plan, board)
    selected = legacy['beats'][0]['visuals'][0]
    assert set(_doodles(selected)) == {'book_stack'}
    assert selected['trigger'] == {'en': 'energy'} and selected['relation'] == 'none'
    assert selected['items'][0]['label'] == {'en': 'Energy'}
    assert validate_legacy(legacy)['ok']


def test_adapter_renders_through_the_existing_whiteboard_path():
    board = script.build(ingest.read('# Tiny lesson\n\nA book holds an idea.'), story='story')
    PictureDirector('en').direct(board)
    plan = from_rules(board)
    plan['scenes'][0]['elements'] = [{'kind': 'picture', 'ref': 'book_stack'}]
    plan, repairs = validate(plan, board, ['book_stack'])
    assert repairs == []
    legacy, treatments = adapt(plan, board)
    assert validate_legacy(legacy)['ok']
    assert set(_doodles(legacy['beats'][0]['visuals'])) == {'book_stack'}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    project = SCRATCH / 'smoke'
    project.mkdir(exist_ok=True)
    clips = timeline.synthetic_clips(legacy, 'en')
    timing = timeline.layout(legacy, 'en', clips, render.pacing(legacy, 'en', clips, project))
    production = render.make_production(legacy, timing, 'en', project)
    assert isinstance(production, render.Production)
    assert treatments[0]['treatment'] == 'whiteboard'
    elements = [e for e in production.ctx.elements if e.group.startswith(legacy['beats'][0]['id'])]
    assert elements and all(not e.skipped for e in elements)
    t = max(e.end for e in elements) + .1
    image = production.frame(t)
    assert image.size == render.SIZE
    pixels = np.asarray(image)
    assert pixels.std() > 10
    image.save(project / 'frame.png')


def test_prompt_covers_reference_grammar_and_cast_constraints():
    for phrase in ('storyboard', 'whiteboard', 'motion', 'kinetic_type', 'atmosphere', 'chart', 'character',
                   '27', 'mane_black', '1.4', 'baby', '4.5:1', 'bar lines', 'recurring', 'fog_with_shooting_star'):
        assert phrase in SYSTEM
    assert detect_genre('Introducing our new app') == 'launch/promo'


def test_explainer_adapter_preserves_notebook_skin_and_frames():
    board = script.build(ingest.read('# How ideas connect\n\nA book holds an idea.'), story='story')
    PictureDirector('en').direct(board)
    board['look'] = 'notebook'
    plan = from_rules(board)
    assert plan['storyboard']['genre'] == 'explainer'
    assert plan['style']['whiteboard_skin'] == 'notebook'
    legacy, _ = adapt(plan, board)
    assert legacy == board
    project = SCRATCH / 'notebook'
    project.mkdir(parents=True, exist_ok=True)
    clips = timeline.synthetic_clips(board, 'en')
    timing = timeline.layout(board, 'en', clips, render.pacing(board, 'en', clips, project))
    original = render.make_production(board, timing, 'en', project)
    adapted = render.make_production(legacy, timing, 'en', project)
    end = max(e.end for e in original.ctx.elements)
    for t in (0, end / 2, end + .1):
        assert np.array_equal(np.asarray(original.frame(t)), np.asarray(adapted.frame(t)))


@pytest.mark.parametrize('treatment', ['whiteboard', 'motion', 'kinetic_type', 'chart', 'character', 'atmosphere'])
def test_adapter_honors_empty_picture_selection(treatment, drafts, plans):
    board = copy.deepcopy(drafts['explainer'])
    cluster = {'id': 'old', 'type': 'cluster', 'items': [{'doodle': 'book_stack'}], 'relation': 'none'}
    quote = {'id': 'quote', 'type': 'quote', 'text': {'en': 'An idea'}, 'speaker': {'en': ''}}
    board['beats'][0]['visuals'] = [cluster, quote]
    plan = copy.deepcopy(plans['explainer'])
    plan['scenes'][0].update(treatment=treatment, elements=[])
    fixed, repairs = validate(plan, board, _candidates(board))
    assert repairs == []
    legacy, _ = adapt(fixed, board)
    assert legacy['beats'][0]['visuals'] == ([cluster, quote] if treatment in ('character', 'atmosphere') else [quote])
    assert board['beats'][0]['visuals'] == [cluster, quote]


@pytest.mark.parametrize('text, expected', [
    ('Pendo, a lion cub, did not roar.', set()),
    ("Pendo, a lion cub, didn't roar.", set()),
    ('Pendo, a lion cub, never roared.', set()),
    ('Pendo, a lion cub, waited. The engine roared.', set()),
    ('Pendo, a lion cub, waited! The engine roared.', set()),
    ('Pendo, a lion cub, did not roar, but laughed.', {'laugh'}),
    ('Pendo, a lion cub, waited. Pendo roared.', {'roar'}),
    ('Pendo, a lion cub, roared.', {'roar'}),
])
def test_actions_follow_the_named_subject_and_negation(text, expected):
    from kinodraw.director.v3.semantics import actions, beats, detect_cast
    board = {'beats': [{'id': 'b1', 'text': text}]}
    normalized = beats(board)
    cast = detect_cast(normalized)
    assert {a['verb'] for a in actions(normalized[0], cast) if a['actor'] == 'pendo'} == expected
    plan = from_rules(board, [])
    assert {a['verb'] for s in plan['scenes'] for a in s['actions'] if a['actor'] == 'pendo'} == expected
    assert validate(plan, board, []) == (plan, [])


def test_once_mentioned_object_is_detected_and_repaired():
    from kinodraw.director.v3.semantics import beats, detect_cast
    board = {'beats': [{'id': 'b1', 'text': 'Alice hugged Bob.'}]}
    assert {c['name'] for c in detect_cast(beats(board))} == {'Alice', 'Bob'}
    plan = from_rules(board, [])
    assert {c['name'] for c in plan['cast']} == {'Alice', 'Bob'}
    plan['cast'] = [c for c in plan['cast'] if c['name'] == 'Alice']
    fixed, repairs = validate(plan, board, [])
    assert {c['name'] for c in fixed['cast']} == {'Alice', 'Bob'}
    assert any('added named character Bob' in r for r in repairs)
    assert validate(fixed, board, []) == (fixed, [])


def test_cast_repair_keeps_overlapping_full_names_distinct():
    from kinodraw.director.v3.semantics import beats, detect_cast
    board = {'beats': [{'id': 'b1', 'text': 'Mary Ann, a woman, hugged Ann, a girl.'}]}
    detected = detect_cast(beats(board))
    assert {c['name'] for c in detected} == {'Mary Ann', 'Ann'}
    plan = from_rules(board, [])
    plan['cast'] = []
    fixed, repairs = validate(plan, board, [])
    assert {c['name'] for c in fixed['cast']} == {'Mary Ann', 'Ann'}
    assert sum('added named character' in r for r in repairs) == 2
    assert validate(fixed, board, []) == (fixed, [])


@pytest.mark.parametrize('text, expected', [
    ('Pendo, a lion cub, did not, in fact, roar.', set()),
    ('Pendo, a lion cub, waited while the engine roared.', set()),
    ('Mary Ann, a woman, roared. Ann, a girl, slept.', {('mary_ann', 'roar'), ('ann', 'sleep')}),
])
def test_remaining_action_boundaries(text, expected):
    board = {'beats': [{'id': 'b1', 'text': text}]}
    plan = from_rules(board, [])
    assert {(a['actor'], a['verb']) for s in plan['scenes'] for a in s['actions']} == expected
    assert validate(plan, board, []) == (plan, [])


@pytest.mark.parametrize('text', ['Books hold ideas.', 'Leaders help families. Leaders support children.',
                                 'In Serengeti, the lions rested. Terrified by the noise, the hyenas fled.'])
def test_common_nouns_and_locations_are_not_cast(text):
    plan = from_rules({'beats': [{'id': 'b1', 'text': text}]}, [])
    assert plan['cast'] == []


def test_lion_story_introductions_and_species():
    text = ("In the golden Serengeti, a tiny lion cub named Pendo lived with his pride. "
            "Pendo loved his mother, Mara, more than anyone else. "
            "Pendo was terrified of his father, the great King Kojo. "
            "Kojo had a massive black mane, a scar over his left eye, and a roar. "
            "Mara and the other lionesses had gone out to hunt. "
            "Terrified by the sheer force of the king, the remaining hyenas scattered. "
            "Kojo stood breathing heavily.")
    board = {'beats': [{'id': 'b1', 'text': text}]}
    plan = from_rules(board, [])
    cast = {c['name']: c for c in plan['cast']}
    assert set(cast) == {'Pendo', 'Mara', 'Kojo'}
    assert (cast['Pendo']['species'], cast['Pendo']['age']) == ('lion', 'baby')
    assert (cast['Mara']['species'], cast['Mara']['sex'], cast['Mara']['age']) == ('lioness', 'female', 'adult')
    assert (cast['Kojo']['species'], cast['Kojo']['age'], cast['Kojo']['size']) == ('lion', 'adult', 1.4)
    assert {'mane_black', 'scar_eye', 'crown'} <= set(cast['Kojo']['marks'])
    assert validate(plan, board, []) == (plan, [])


@pytest.mark.parametrize('rename', [False, True])
def test_full_lion_narration_has_only_actor_owned_traits(rename):
    source = Path(__file__).parent / 'fixtures/lion_full.md'
    text = source.read_text(encoding='utf-8')
    names = ('Pendo', 'Mara', 'Kojo')
    if rename:
        replacements = ('Tavi', 'Nala', 'Roko')
        for old, new in zip(names, replacements):
            text = text.replace(old, new)
        names = replacements
    board = script.build(ingest.read(text), story='story')
    plan = RulesDirector('en').direct(board, [])
    cast = {c['name']: c for c in plan['cast']}
    assert set(cast) == set(names)
    baby, mother, father = (cast[name] for name in names)
    assert (baby['species'], baby['age'], baby['size']) == ('lion', 'baby', .55)
    assert baby['sex'] != 'female'
    assert baby['marks'] == ['mane_none']
    assert (mother['species'], mother['sex'], mother['age']) == ('lioness', 'female', 'adult')
    assert (father['species'], father['age'], father['size']) == ('lion', 'adult', 1.4)
    assert {'mane_black', 'scar_eye'} <= set(father['marks'])
    assert validate(plan, board, []) == (plan, [])
    acting = {(a['actor'], a['verb']) for s in plan['scenes'] for a in s['actions']}
    assert (father['id'], 'walk') in acting
    assert (baby['id'], 'hide') in acting
    assert (baby['id'], 'roar') not in acting


@pytest.mark.parametrize('genre', ['story', 'explainer', 'launch', 'lesson', 'news', 'poem'])
def test_genre_fixtures_have_no_unexpected_cast(genre, plans):
    assert {c['name'] for c in plans[genre]['cast']} == ({'Pendo', 'Mara', 'Kojo'} if genre == 'story' else set())

"""The offline v3 director stages every sentence: its place, its people and its objects (gauntlet r1, 2026-10-08)."""
from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import detect_genre, from_rules, offline_candidates
from kinodraw.director.v3.staging import read_text, tie
from kinodraw.director.v3.validate import validate
from kinodraw.engine import captions

HUMAN = ('# The Bus Home\n\n'
         'Once upon a time, a girl named Ana lived in a quiet town by the sea.\n\n'
         'Every morning Ana rode the bus to school with her grandpa. He always carried a paper bag of warm bread.\n\n'
         'One day the bag tore, and an apple rolled down the street. Ana ran after it.\n\n'
         'Later, her mother sat on the couch in front of the TV. "You were brave today," she said.\n\n'
         '"It was only an apple," Ana said, and she laughed.')


def _plan(text):
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    return from_rules(board), board


def _refs(scene, kind):
    return [e['ref'] for e in scene['elements'] if e['kind'] == kind]


def test_a_human_story_casts_its_named_people_and_roles():
    plan, _ = _plan(HUMAN)
    cast = {c['name']: c for c in plan['cast']}
    assert {'Ana', 'Grandpa', 'Mother'} <= set(cast)
    assert all(c['kind'] == 'human' for c in cast.values())
    assert cast['Grandpa']['age'] == 'old' and cast['Grandpa']['sex'] == 'male'
    assert cast['Mother']['sex'] == 'female'
    assert cast['Ana']['sex'] == 'female'
    staged = {cid for s in plan['scenes'] for cid in _refs(s, 'cast')}
    assert {cast['Ana']['id'], cast['Grandpa']['id'], cast['Mother']['id']} <= staged


def test_every_story_beat_shows_the_place_and_things_its_sentences_name():
    plan, board = _plan(HUMAN)
    pictures = {bid: _refs(s, 'picture') for s in plan['scenes'] for bid in s['beat_ids']}
    text = {b['id']: b['spoken']['en'] for b in board['beats']}
    beat = lambda words: next(bid for bid, t in text.items() if words in t)
    assert 'fl_houses' in pictures[beat('quiet town')]
    assert {'fl_bus', 'fl_bread'} <= set(pictures[beat('rode the bus')])
    assert {'fl_red_apple', 'city_block'} <= set(pictures[beat('apple rolled')])
    assert {'fl_couch_and_lamp', 'fl_television'} <= set(pictures[beat('couch')])
    assert all(_refs(s, 'picture') or _refs(s, 'cast') for s in plan['scenes'])
    # The offline plan is valid against what the offline director offers.
    assert validate(plan, board, offline_candidates(board)) == (plan, [])


def test_a_set_carries_until_another_place_is_named():
    readings = read_text('They walked into the kitchen. Mom poured milk. Then they went out to the park.')
    assert [r.place for r in readings] == ['tb_fridge', 'tb_fridge', 'fl_national_park']
    assert readings[1].objects == ['fl_glass_of_milk']
    assert read_text('There was no moon anywhere.')[0].objects == []


def test_pictures_are_tied_to_the_sentence_that_names_them():
    texts = ['Ana lived in a quiet town.', 'She baked bread every morning.', 'It was a good life.']
    assert tie(texts, ['fl_houses', 'fl_bread', 'fl_sun']) == [
        ['fl_houses', 'fl_sun'], ['fl_houses', 'fl_bread', 'fl_sun'], ['fl_houses', 'fl_sun']]


def test_a_screenplay_is_a_story_with_its_speakers_cast():
    text = ('# Pizza Night\n\nIt is Saturday at the Okoro flat.\n\n'
            'TAYO: I want pineapple on it.\n\nGRACE: Absolutely not.\n\nTAYO: Then I am ordering two pizzas.')
    assert detect_genre(text) == 'story'
    plan, _ = _plan(text)
    assert {'Tayo', 'Grace'} <= {c['name'] for c in plan['cast']}
    speakers = [(s['beat_ids'][0], _refs(s, 'cast')) for s in plan['scenes'] if _refs(s, 'cast')]
    assert len(speakers) >= 3


def test_an_animal_story_keeps_kin_words_for_its_animals():
    text = ('# Owl Night\n\nOnce upon a time a little owl named Hoot lived in an old oak with his mother.\n\n'
            'Hoot looked at the moon. "Can I fly there?" he said.')
    plan, _ = _plan(text)
    assert [c['name'] for c in plan['cast']] == ['Hoot']
    assert plan['cast'][0]['species'] == 'owl'


def test_captions_never_run_on_into_the_next_sentence():
    text = 'Theo read it twice. Then he went downstairs to the kitchen.'
    times = lambda char: char * .05
    cues = captions.cues_for_beat(text, text, 'en', times, len(text) * .05)
    assert [c[2] for c in cues] == ['Theo read it twice.', 'Then he went downstairs to the kitchen.']


def test_the_storybook_shows_each_picture_on_the_sentence_that_names_it(tmp_path):
    import json
    from kinodraw.engine import render, timeline
    text = ('# Bread\n\nOnce upon a time, a girl named Ana lived in a quiet little town near the sea. '
            'Every single morning she carried a warm loaf of bread to her neighbours.')
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    shots = [shot for span in prod.spans if span.story for shot in span.story]
    drawn = [[p[0] for p in shot.props] + [piece.doodle for piece in shot.set] for shot in shots]
    assert len(shots) == 2
    assert 'fl_bread' not in drawn[0]
    assert 'fl_bread' in drawn[1]


def test_a_thing_the_words_say_is_not_there_is_never_drawn():
    from kinodraw.director.v3.story import Reader
    for text in ('No moon anywhere.', 'The moon is gone.', 'By morning the key was missing.'):
        assert [s.sky for s in Reader([]).read('b', text)] in ([[]], [['fl_sun']]), text
        assert read_text(text)[0].objects == [], text
    assert [s.sky for s in Reader([]).read('b', 'The moon rose over the hill.')] == [['fl_crescent_moon']]
    assert read_text('No moon anywhere.')[0].sky is False
    # A planner's moon on a beat that says it is gone shows on none of its sentences.
    assert tie(['"Mama," he whispered.', '"The moon is gone."'], ['fl_full_moon']) == [[], []]


def test_a_screenplay_speaker_called_grandpa_to_his_face_is_old():
    text = ('# Remote\n\nIt is Friday night at the Ruiz house.\n\n'
            'WALT: Whatever happened to a movie where a man rides a horse?\n\n'
            'JULES: Grandpa, that is a screensaver.\n\nMAYA: Mom, can I pick?\n\nDANA: No.')
    cast = {c['name']: c for c in _plan(text)[0]['cast']}
    assert (cast['Walt']['age'], cast['Walt']['sex']) == ('old', 'male')
    assert cast['Jules']['age'] != 'old'
    assert cast['Dana']['sex'] == 'unknown'          # "Mom" was said to Jules, the speaker just before Maya

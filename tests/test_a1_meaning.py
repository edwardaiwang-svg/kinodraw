"""Meaning gates beat attractive keyword/embedding hits in both director paths."""
import copy

import numpy as np
import pytest

from kinodraw.director.llm.director import LLMDirector
from kinodraw.director.match import Hit
from kinodraw.director.rules import RulesDirector
from kinodraw.engine.storyboard import normalize


CASES = [
    ('The lion was breathing heavily.', {'lungs', 'fl_lungs'}),
    ('The lion had a scarred nose.', {'fl_nose'}),
    ('The hyenas bared their sharp teeth.', {'tooth', 'fl_tooth'}),
    ('The cub had rattling teeth.', {'tooth', 'fl_tooth'}),
    ('The lion made a massive paw swipe.', {'fl_paw_prints'}),
    ('The hyenas were laughing menacingly.', {'fl_face_with_tears_of_joy'}),
    ('The lion wore his courage like armor.', {'fl_military_helmet'}),
    ('The pride lived in the heart of the savanna.', {'heart_organ', 'fl_anatomical_heart'}),
    ('The lion had blazing eyes.', {'fl_fire'}),
    ('The lion spoke in a voice like thunder.', {'fl_cloud_with_lightning_and_rain'}),
    ('The lion cub gave a tiny squeak.', {'warning_triangle', 'fl_warning'}),
    ('The cub watched his father.', {'fl_santa_claus'}),
    ('Thick fog covered the savanna.', {'fl_fog', 'fl_foggy'}),
    ('The lionesses left to hunt while the cubs stayed.', {'cub_group', 'family_pride'}),
]


def board_for(*sentences):
    return {'lang': 'en', 'title': {'en': 'The pride'},
            'chapters': [{'id': 's1', 'kind': 'board', 'title': {'en': 'The savanna'}}],
            'beats': [{'id': f'b{k}', 'chapter': 's1', 'kind': 'narration',
                       'display': {'en': s}, 'spoken': {'en': s}, 'visuals': []}
                      for k, s in enumerate(sentences)]}


@pytest.fixture
def rules(monkeypatch):
    director = RulesDirector('en')
    director.matcher.entries.update({
        'cub_group': {'set': 'bespoke', 'category': 'animals', 'desc': 'lion cubs resting'},
        'family_pride': {'set': 'bespoke', 'category': 'animals', 'desc': 'lionesses and cubs together'},
    })
    director.ids += ['cub_group', 'family_pride']
    director.pos = {did: k for k, did in enumerate(director.ids)}
    # Make every offered wrong picture attractive. Rejection must come from meaning.
    director.vecs = director.pics = np.ones((len(director.ids), 1), np.float32)
    monkeypatch.setattr(director, '_sentence_vectors', lambda sentences: np.ones((len(sentences), 1), np.float32))
    monkeypatch.setattr(director, '_topic_ranks', lambda board: {'s1': np.ones(len(director.ids), int)})
    return director


def doodles(beat):
    return {i['doodle'] for v in beat['visuals'] for i in v.get('items', [])} | {
        v['doodle'] for v in beat['visuals'] if 'doodle' in v}


@pytest.mark.parametrize('sentence,banned', CASES)
def test_wrong_high_scoring_pictures_are_filtered_offline_and_cloud(rules, monkeypatch, sentence, banned):
    assert banned <= rules.matcher.entries.keys()
    forced = [Hit(did, 1., sentence, 0) for did in sorted(banned)]
    monkeypatch.setattr(rules.matcher, 'lexical', lambda text, every_phrase=False: forced)
    monkeypatch.setattr(rules.matcher, 'semantic', lambda text, k=5: [Hit(h.id, 1., None, 0) for h in forced])
    board = rules.direct(board_for(sentence))
    beat = board['beats'][0]
    assert not doodles(beat) & banned
    assert not {h.id for h in rules._concepts(sentence, [], 's1')} & banned
    cloud = LLMDirector.__new__(LLMDirector)
    cloud.lang, cloud.k, cloud.rules = 'en', 12, rules
    payload = cloud._payload(board, board['chapters'][0], board['beats'], 1)
    offered = {c['id'] for c in payload['beats'][0]['candidates']}
    assert not offered & banned
    assert offered == {h.id for h in rules.candidates(sentence, 's1', 12)}


def test_names_get_traits_and_never_share_stock_faces(rules, monkeypatch):
    sentences = ('Pendo, a lion cub, was afraid.', 'Mara, a tigress, was afraid.',
                 'King Kojo, a lion with a black mane, watched Pendo.',
                 'Mara protected Pendo.', 'Kojo was breathing heavily.',
                 'The king had a scarred nose.', 'He nudged the cub.')
    bad = {'fl_lion', 'fl_tiger_face', 'fl_fearful_face', 'fl_boy', 'crown', 'fl_crown', 'lungs', 'fl_nose'}
    forced = [Hit(did, 1., 'afraid', 0) for did in bad]
    monkeypatch.setattr(rules.matcher, 'lexical', lambda text, every_phrase=False: forced)
    monkeypatch.setattr(rules.matcher, 'semantic', lambda text, k=5: [Hit(did, 1., None, 0) for did in bad])
    board = rules.direct(board_for(*sentences))
    assert set(rules.characters) == {'Pendo', 'Mara', 'Kojo'}
    assert 'lion cub' in rules.characters['Pendo']['traits']
    assert 'tigress' in rules.characters['Mara']['traits']
    assert 'black mane' in rules.characters['Kojo']['traits']
    assert all(not doodles(b) & bad for b in board['beats'])
    assert board['beats'][5]['character'][0]['name'] == 'Kojo'
    assert board['beats'][6]['character'][0]['name'] == 'Kojo'
    assert all(not doodles(b) for b in board['beats'])
    cloud = LLMDirector.__new__(LLMDirector)
    cloud.lang, cloud.k, cloud.rules = 'en', 12, rules
    payload = cloud._payload(board, board['chapters'][0], board['beats'], 1)
    assert all(not {c['id'] for c in b['candidates']} & bad for b in payload['beats'])
    assert payload['beats'][0]['character'] == board['beats'][0]['character']
    assert normalize(board)['beats'][0]['character'] == board['beats'][0]['character']


def test_atmosphere_beats_share_one_scene_and_reset_at_a_gap(rules):
    board = rules.direct(board_for('Thick fog covered the savanna.', 'A shooting star crossed the mist.',
                                   'The cub slept.', 'Rain fell at dawn under the night stars and dust.'))
    a, b, _, d = board['beats']
    assert a['atmosphere'] == {'words': ['fog'], 'scene': 'b0'}
    assert b['atmosphere'] == {'words': ['shooting star', 'mist'], 'scene': 'b0'}
    assert d['atmosphere']['scene'] == 'b3'
    assert d['atmosphere']['words'] == ['rain', 'dawn', 'night', 'stars', 'dust']
    assert normalize(board)['beats'][1]['atmosphere'] == b['atmosphere']
    again = rules.direct(copy.deepcopy(board))
    assert [b.get('atmosphere') for b in again['beats']] == [b.get('atmosphere') for b in board['beats']]


def test_literal_objects_and_human_anatomy_still_allowed(rules):
    rules.direct(board_for('The doctor examined a lion.', 'The doctor explained the lungs.'))
    assert rules._meaning_allows('lungs', 'lungs', 'The doctor explained the lungs.')
    assert rules._meaning_allows('fl_military_helmet', 'helmet', 'The soldier wore a military helmet.')
    assert rules._meaning_allows('fl_fire', 'fire', 'A fire blazed near the lions.')
    assert rules._meaning_allows('fl_paw_prints', 'paw prints', 'The cub left paw prints in the mud.')
    assert rules._meaning_allows('cub_group', 'cubs', 'The lionesses and the cubs rested together.')


def test_real_catalog_and_recorded_cloud_preserve_meaning():
    class Offered:
        name, model = 'recorded', 'gpt-6-luna'

        def __init__(self):
            self.payload = None

        def direct_section(self, payload, usage):
            self.payload = payload
            return {'beats': [{'beat_id': b['beat_id'], 'visuals': [
                {'type': 'cluster', 'relation': 'none', 'items': [
                    {'doodle': c['id'], 'label': '', 'trigger': ''} for c in b['candidates'][:3]]}]
                if b['candidates'] else []} for b in payload['beats']]}

    sentences = [s for s, _ in CASES[:-1]] + [
        'Pendo, a lion cub, was afraid.', 'Mara, a tigress, was afraid.',
        'King Kojo had a black mane.', 'Pendo hid beside Mara.', 'Kojo watched the cub.',
        'The lionesses left to hunt while the cubs stayed.',
        'Thick fog covered the ground.', 'A shooting star crossed the mist.']
    provider = Offered()
    director = LLMDirector(provider, 'en')
    board = board_for(*sentences)
    director.direct(board)
    all_bad = set().union(*(bad for _, bad in CASES[:-1])) | {'fl_lion', 'fl_tiger_face', 'crown', 'fl_crown'}
    for beat, payload in zip(board['beats'], provider.payload['beats']):
        banned = all_bad if beat.get('character') else next((bad for s, bad in CASES if s == beat['display']['en']), set())
        assert not doodles(beat) & banned
        assert not {c['id'] for c in payload['candidates']} & banned
    assert board['beats'][-2]['atmosphere']['scene'] == board['beats'][-1]['atmosphere']['scene']


def cloud_for(rules):
    cloud = LLMDirector.__new__(LLMDirector)
    cloud.lang, cloud.k, cloud.rules, cloud.notes = 'en', 12, rules, []
    return cloud


def test_named_characters_reject_faces_without_face_in_description(rules, monkeypatch):
    monkeypatch.setattr(rules.matcher, 'semantic', lambda text, k=5: [Hit('fl_exploding_head', 1.)])
    board = rules.direct(board_for('Pendo was shocked.', 'Mara was shocked.',
                                   'Pendo watched Mara.'))
    cloud = cloud_for(rules)
    payload = cloud._payload(board, board['chapters'][0], board['beats'], 1)
    answer = {'beats': [{'beat_id': b['id'], 'visuals': [{'type': 'cluster', 'items': [
        {'doodle': 'fl_exploding_head', 'trigger': 'shocked'}]}]} for b in board['beats'][:2]]}
    cloud._apply(board, board['chapters'][0], board['beats'], answer, payload)
    assert len(cloud.notes) == 2
    assert all('fl_exploding_head' not in doodles(b) for b in board['beats'])
    assert all('fl_exploding_head' not in {c['id'] for c in b['candidates']} for b in payload['beats'])
    assert rules._meaning_allows('fl_blue_heart', None, 'Pendo watched Mara.')


@pytest.mark.parametrize('adjective', ['tired', 'sleeping', 'tired sleeping'])
def test_participial_adjectives_preserve_animal_subject(rules, adjective):
    sentence = f'The {adjective} cub rubbed his scarred nose.'
    board = rules.direct(board_for(sentence))
    assert rules._animal_subject(sentence)
    assert 'fl_nose' not in doodles(board['beats'][0])
    assert 'fl_nose' not in {h.id for h in rules.candidates(sentence, 's1', 12)}
    assert not rules._animal_subject('The doctor examined the tired cub.')
    assert not rules._animal_subject('The doctor touched the sleeping cub.')


def test_such_as_examples_keep_literal_pictures(rules):
    sentence = 'Tools such as microscopes let us see tiny cells.'
    board = rules.direct(board_for(sentence))
    assert {'microscope', 'cell'} <= doodles(board['beats'][0])
    assert {'microscope', 'cell'} <= {h.id for h in rules.candidates(sentence, 's1', 12)}


def test_repeated_initial_common_nouns_keep_pictures_and_narrator(rules, monkeypatch):
    sentences = ('Teachers help students learn.', 'Teachers read stories to children.')
    board = rules.direct(board_for(*sentences))
    assert not rules.characters
    assert all('character' not in b for b in board['beats'])
    assert 'family_group' in doodles(board['beats'][1])
    cloud = cloud_for(rules)
    payload = cloud._payload(board, board['chapters'][0], board['beats'], 1)
    cloud._apply(board, board['chapters'][0], board['beats'], {'beats': [
        {'beat_id': 'b1', 'visuals': [{'type': 'cluster', 'items': [
            {'doodle': 'narrator_explain', 'trigger': 'Teachers read'}]}]}]}, payload)
    assert not cloud.notes
    monkeypatch.setattr(rules, '_concepts', lambda *args, **kwargs: [])
    board = rules.direct(board_for(*sentences))
    assert 'narrator_explain' in doodles(board['beats'][0])


def test_cloud_picture_permission_is_scoped_to_trigger_sentence(rules):
    sentence = 'The doctor touched his nose. The lion rubbed his scarred nose.'
    board = rules.direct(board_for(sentence))
    cloud = cloud_for(rules)
    payload = cloud._payload(board, board['chapters'][0], board['beats'], 1)
    assert 'fl_nose' in {c['id'] for c in payload['beats'][0]['candidates']}
    for trigger in ('scarred nose', '', 'invented words', 'nose'):
        trial = copy.deepcopy(board)
        cloud.notes.clear()
        cloud._apply(trial, trial['chapters'][0], trial['beats'], {'beats': [
            {'beat_id': 'b0', 'visuals': [{'type': 'cluster', 'items': [
                {'doodle': 'fl_nose', 'trigger': trigger}]}]}]}, payload)
        if trigger == 'nose':
            assert not cloud.notes
        else:
            assert len(cloud.notes) == 1
            assert trial['beats'][0]['visuals'] == board['beats'][0]['visuals']


@pytest.mark.parametrize('species', ['dog', 'puppy', 'fox', 'cat', 'kitten', 'rabbit', 'horse', 'bird'])
def test_recurring_animals_keep_supported_species_traits(rules, species):
    board = rules.direct(board_for(f'Rex, a {species}, guarded the house.', 'Rex was breathing heavily.'))
    assert species in rules.characters['Rex']['traits']
    assert species in board['beats'][1]['character'][0]['traits']
    assert not {'lungs', 'fl_lungs'} & doodles(board['beats'][1])
    assert not {'lungs', 'fl_lungs'} & {h.id for h in rules.candidates('Rex was breathing heavily.', 's1', 12)}


@pytest.mark.parametrize('sentence,banned', [
    ('The lion was brave like thick armor.', {'knight_helmet', 'fl_military_helmet'}),
    ('The lion spoke in a voice like rolling thunder.', {'lightning_bolt', 'fl_cloud_with_lightning_and_rain'}),
    ('The lion stood like stone and spoke in a voice like rolling thunder.',
     {'lightning_bolt', 'fl_cloud_with_lightning_and_rain'}),
])
def test_modified_similes_reject_literal_noun_pictures(rules, sentence, banned):
    board = rules.direct(board_for(sentence))
    assert all(not rules._meaning_allows(did, None, sentence) for did in banned)
    assert not banned & doodles(board['beats'][0])
    assert not banned & {h.id for h in rules.candidates(sentence, 's1', 12)}



def test_common_noun_exclusion_does_not_need_picture_index(rules):
    assert 'leader' not in rules.matcher.index
    board = rules.direct(board_for('Leaders help families.', 'Leaders support children.'))
    assert not rules.characters
    assert all('character' not in b for b in board['beats'])
    assert any('family_group' in doodles(b) for b in board['beats'])
    assert rules._meaning_allows('family_group', None, 'Leaders help families.')
    cloud = cloud_for(rules)
    payload = cloud._payload(board, board['chapters'][0], board['beats'], 1)
    assert any('family_group' in {c['id'] for c in b['candidates']} for b in payload['beats'])

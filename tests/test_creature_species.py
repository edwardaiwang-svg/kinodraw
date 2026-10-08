"""Hedgehogs, tortoises, fireflies and snails are drawn as themselves, and a bug the library has no picture of is
drawn as its nearest drawn bug, never as an unrelated icon."""
from __future__ import annotations

import json

import pytest

from kinodraw.director.v3.semantics import SPECIES
from kinodraw.director.v3.story import Reader
from kinodraw.engine import storybook
from kinodraw.library import ASSETS, catalog, creatures

TAGS = json.loads((ASSETS / 'tags' / 'creatures.json').read_text(encoding='utf-8'))
NEW = ('hedgehog', 'tortoise', 'firefly', 'snail')
# what a story asks for -> the canonical poses that must exist (talking is the open-mouth 'shout')
POSES = {'stand': ('stand',), 'walk': ('walk1', 'walk2'), 'rest': ('lie', 'sit'), 'sleep': ('sleep',),
         'talk': ('shout',)}


def _have(species):
    out = {}
    for entry in TAGS.values():
        c = entry['creature']
        if c['species'] == species:
            out.setdefault(c['age'], set()).add((c['pose'], c['facing']))
    return out


@pytest.mark.parametrize('species', NEW)
def test_each_new_species_has_story_poses_both_ways_young_and_adult(species):
    have = _have(species)
    assert {'young', 'adult'} <= set(have), species
    for age, poses in have.items():
        for need, options in POSES.items():
            for facing in 'rl':
                assert any((p, facing) in poses for p in options), (species, age, need, facing)


def test_the_old_tortoise_has_an_elder_look_and_no_flippers():
    assert 'elder' in _have('tortoise')
    assert not any(p.startswith('swim') for poses in _have('tortoise').values() for p, _ in poses)
    assert storybook.preset('tortoise', 'old', 'female', 'stand', 'l')[0] == 'cr_tortoise_any_elder_stand_l'
    assert storybook.preset('tortoise', 'adult', None, 'swim', 'r')[0].startswith('cr_tortoise_')


@pytest.mark.parametrize('species,age,pose', [('hedgehog', 'baby', 'stand'), ('hedgehog', 'adult', 'sleep'),
                                              ('tortoise', 'old', 'talk'), ('firefly', 'young', 'stand'),
                                              ('snail', 'adult', 'walk'), ('snail', 'young', 'sleep')])
def test_storybook_draws_each_species_as_itself(species, age, pose):
    doodle, _ = storybook.preset(species, age, None, pose, 'r')
    assert creatures.presets()[doodle]['species'] == species
    assert storybook.meta(doodle)['anchors'].get('mouth'), 'speech bubbles start at the mouth'


@pytest.mark.parametrize('word', ['firefly', 'lightning bug', 'glowworm', 'cricket', 'grasshopper',
                                  'dragonfly', 'mosquito', 'bug', 'slug'])
def test_a_small_crawler_or_light_bug_is_drawn_as_a_bug_never_an_icon(word):
    doodle, _ = storybook.preset(word, 'adult', None, 'stand', 'r')
    family = (creatures.presets().get(doodle) or {}).get('family')
    assert family in ('insect', 'mollusc'), (word, doodle)


def test_light_bugs_are_fireflies_and_a_hedgehog_is_not_a_porcupine():
    for word in ('lightning bug', 'glowworm'):
        assert creatures.presets()[creatures.best_preset(word)]['species'] == 'firefly'
    assert creatures.presets()[creatures.best_preset('hedgehog')]['species'] == 'hedgehog'
    assert creatures.presets()[creatures.best_preset('tortoise')]['species'] == 'tortoise'


def test_a_firefly_glows():
    svg = (ASSETS / 'creatures' / 'cr_firefly_any_young_stand_r.svg').read_text(encoding='utf-8')
    assert 'fill-opacity' in svg
    asleep = (ASSETS / 'creatures' / 'cr_firefly_any_young_sleep_r.svg').read_text(encoding='utf-8')
    assert 'fill-opacity' not in asleep          # the light dims while she sleeps


def test_species_words_in_three_languages():
    for word, zh in (('hedgehog', '刺猬'), ('tortoise', '陆龟'), ('firefly', '萤火虫'), ('snail', '蜗牛')):
        search = [e for e in catalog().values() if e.get('set') == 'creatures' and e.get('search', True)
                  and e['creature']['species'] == word]
        assert any(word in e['en'] for e in search) and any(zh in e['zh'] for e in search), word
        assert word in SPECIES
    from kinodraw.director.match import es_gloss
    assert es_gloss('el erizo, la tortuga terrestre, las luciérnagas y el caracol').split() == [
        'hedgehog', 'tortoise', 'firefly', 'snail']


def _cast(*members):
    return [{'id': i, 'name': n, 'kind': 'quadruped', 'species': sp, 'family': 'other', 'age': 'adult',
             'sex': 'female', 'size': 1., 'palette': {}, 'marks': []} for i, n, sp in members]


def test_a_cast_tortoise_named_by_her_species_gets_no_second_tortoise_beside_her():
    reader = Reader(_cast(('moss', 'Grandma Moss', 'tortoise'), ('pip', 'Pip', 'hedgehog')))
    line = reader.read('b1', 'By the pond he found Grandma Moss, the oldest tortoise in the wood.')[0]
    assert line.crowd == []
    line = reader.read('b2', 'Lupita had a jar full of fireflies and two snails.')[0]
    assert dict(line.crowd) == {'firefly': 3, 'snail': 2}


@pytest.mark.parametrize('word,species', [('frogs', 'frog'), ('fireflies', 'firefly'), ('panda', 'bear'),
                                          ('lightning bug', 'firefly'), ('hedgehogs', 'hedgehog')])
def test_a_plural_or_look_word_from_the_planner_draws_that_animal(word, species):
    """Luna writes cast species such as "frogs" (the pond frogs) or "panda"; they used to fall to paw prints."""
    doodle, _ = storybook.preset(word, 'adult', None, 'stand', 'r')
    assert creatures.presets().get(doodle, {}).get('species') == species, (word, doodle)

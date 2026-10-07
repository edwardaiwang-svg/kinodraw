"""Generated creature presets: deterministic output, library integration and the resolver's fallbacks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kinodraw.library import ASSETS, catalog, creatures
from kinodraw.library.creaturegen import build, species

TAGS = json.loads((ASSETS / 'tags' / 'creatures.json').read_text(encoding='utf-8'))


def _variant(key):
    return next(v for v in species.catalogue() if v.key == key)


@pytest.mark.parametrize('key', ['lion_male_adult_blackmane_scar', 'ant_any_adult_red'])
def test_generation_is_deterministic_and_matches_the_shipped_files(key):
    first = list(build.render_variant(_variant(key)))
    second = list(build.render_variant(_variant(key)))
    assert [(i, s) for i, s, _ in first] == [(i, s) for i, s, _ in second]
    for pid, svg, meta in first:
        assert (ASSETS / 'creatures' / f'{pid}.svg').read_text(encoding='utf-8') == svg, pid
        assert TAGS[pid] == build.tag_entry(_variant(key), meta)


def test_tags_and_files_agree_and_only_canonical_pictures_are_searchable():
    files = {p.stem for p in (ASSETS / 'creatures').glob('*.svg')}
    assert files == set(TAGS)
    assert len(files) >= 400
    for pid, entry in TAGS.items():
        c = entry['creature']
        assert pid.startswith('cr_') and pid.endswith('_' + c['facing'])
        assert entry.get('search', True) == (c['pose'] == 'stand' and c['facing'] == 'r'), pid
        assert entry['category'] in ('animals', 'characters')
    shipped = {i for i, e in catalog().items() if e['set'] == 'creatures'}
    assert shipped == files


def test_matcher_indexes_only_searchable_creatures():
    from kinodraw.director.match import searchable
    found = {i for i, e in searchable().items() if e['set'] == 'creatures'}
    assert found and all(TAGS[i].get('search', True) for i in found)
    assert 'cr_lion_male_adult_roar_r' not in found


def test_story_cast_resolves_exactly():
    best = creatures.best_preset
    assert best('lion', pose='roar', marks=('mane_black', 'scar_nose')) == 'cr_lion_male_adult_blackmane_scar_roar_r'
    assert best('lion', sex='male', pose='walk', facing='left', marks=['mane_black', 'scar_nose']) == \
        'cr_lion_male_adult_blackmane_scar_walk1_l'
    assert best('lion') == 'cr_lion_male_adult_stand_r'
    assert best('lioness', pose='carry') == 'cr_lion_female_adult_carry_r'
    assert best('lion', age='cub', pose='look_up') == 'cr_lion_any_young_look_up_r'
    assert best('lion cub', pose='scared', facing='left') == 'cr_lion_any_young_scared_l'
    assert best('lion', pose='face', expression='scared', marks=('mane_black', 'scar_nose')) == \
        'cr_lion_male_adult_blackmane_scar_face_scared_f'
    assert best('elephant', age='baby', pose='walk') == 'cr_elephant_any_young_walk1_r'
    assert best('gorilla', pose='roar') == 'cr_gorilla_any_adult_roar_r'
    assert best('tree frog', pose='croak') == 'cr_frog_any_adult_tree_roar_r'
    assert best('ants', pose='carry', variant='red') == 'cr_ant_any_adult_red_carry_r'
    assert best('hyena', pose='run', facing='l') == 'cr_hyena_any_adult_run_l'
    assert best('porcupine', pose='scared') == 'cr_porcupine_any_adult_scared_r'


def test_fallbacks_nearest_pose_then_facing_then_family():
    best = creatures.best_preset
    assert best('lion', pose='fly') == 'cr_lion_male_adult_run_r'           # no flying lion: nearest motion
    assert best('frog', pose='run') == 'cr_frog_any_adult_tree_jump_r'
    assert best('ant', pose='sit').startswith('cr_ant_') and best('ant', pose='sit').endswith('_stand_r')
    assert best('lion', pose='stand', facing='front') == 'cr_lion_male_adult_stand_r'
    assert best('monkey', pose='face_sad') == 'cr_monkey_any_adult_face_sad_f'
    panther = best('panther', pose='run')                                  # related big cat when not drawn
    assert panther and creatures.presets()[panther]['family'] == 'big_cat'
    assert best('dragon') is None and best('') is None


def test_an_animal_never_resolves_to_a_person():
    people = {i for i, m in creatures.presets().items() if m['family'] == 'human'}
    poses = ('stand', 'walk', 'run', 'sit', 'sleep', 'roar', 'shout', 'wave', 'carry', 'face_happy', 'fly', 'swim')
    for sp in creatures.species_list():
        if sp == 'human':
            continue
        for pose in poses:
            for age in ('adult', 'child', 'old', 'baby'):
                got = creatures.best_preset(sp, age=age, pose=pose)
                assert got is not None and got not in people, (sp, pose, age, got)
    for word in ('jaguar', 'hedgehog', 'toad', 'crow', 'puppy', 'chimp'):
        got = creatures.best_preset(word, pose='wave')
        assert got is None or got not in people


def test_carry_presets_record_an_anchor_inside_the_picture():
    for pid, m in creatures.presets().items():
        if m['pose'] != 'carry':
            continue
        point = creatures.anchor(pid)
        assert point is not None, pid
        w, h = m['size']
        assert 0 <= point[0] <= w and 0 <= point[1] <= h, (pid, point)

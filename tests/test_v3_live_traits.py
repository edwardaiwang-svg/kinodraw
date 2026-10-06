"""Replay supplied cast traits against actor-owned narration, without a live provider."""
import copy
import json
from pathlib import Path

import pytest

from kinodraw import ingest, pipeline, script
from kinodraw.director.v3 import llm
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.validate import validate

LION = Path(__file__).parent / 'fixtures' / 'lion_full.md'


@pytest.mark.parametrize('names', [('Pendo', 'Mara', 'Kojo'), ('Tavi', 'Nala', 'Roko')])
def test_supplied_lion_cast_scrubs_actual_borrowed_nose_scar(names):
    text = LION.read_text()
    for old, new in zip(('Pendo', 'Mara', 'Kojo'), names):
        text = text.replace(old, new)
    board = script.build(ingest.read(text), story='story')
    supplied = from_rules(board, [])
    baby, mother, father = (next(c for c in supplied['cast'] if c['name'] == name) for name in names)
    baby['marks'] = ['mane_none', 'scar_nose']
    father['marks'] = ['mane_black', 'scar_eye']
    baby['palette']['body'] = '#AABBCC'
    supplied['storyboard']['recurring_motif'] = 'A protective embrace'
    before = copy.deepcopy(supplied)

    class Replay:
        def direct_plan(self, payload, usage):
            return supplied

    fixed, report = llm.plan_v3(board, Replay())
    assert not report['fallback']
    cast = {c['name']: c for c in fixed['cast']}
    assert cast[names[0]]['marks'] == ['mane_none']
    assert {'mane_black', 'scar_eye', 'scar_nose'} <= set(cast[names[2]]['marks'])
    assert cast[names[0]]['palette']['body'] == '#AABBCC'
    assert fixed['storyboard'] == supplied['storyboard']
    assert supplied == before
    assert any('scar_nose' in repair and baby['id'] in repair for repair in report['repairs'])
    assert validate(fixed, board, []) == (fixed, [])


def _supplied(text):
    board = {'beats': [{'id': 'b1', 'text': text}]}
    plan = from_rules(board, [])
    return board, plan, {c['name']: c for c in plan['cast']}


@pytest.mark.parametrize('names', [('Doran', 'Luma'), ('Senka', 'Beri')])
def test_embedded_pronoun_does_not_transfer_supplied_scar(names):
    adult, cub = names
    board, plan, cast = _supplied(
        f'King {adult} walked. {cub}, a female lion cub, slept. '
        f'{adult} walked past {cub} while she scratched her scarred nose.')
    cast[adult]['marks'] = ['crown']
    cast[cub]['marks'] = ['mane_none', 'scar_nose', 'freckles']
    before = copy.deepcopy(plan)
    fixed, _ = validate(plan, board, [])
    actual = {c['name']: c for c in fixed['cast']}
    assert 'scar_nose' not in actual[adult]['marks']
    assert actual[cub]['marks'] == ['mane_none', 'scar_nose', 'freckles']
    assert plan == before
    assert validate(fixed, board, []) == (fixed, [])


@pytest.mark.parametrize('name', ['Doran', 'Senka'])
def test_negative_state_does_not_negate_fresh_positive_mark_predicate(name):
    board, plan, cast = _supplied(
        f'{name}, an adult lion, was not frightened and had a scar on his nose.')
    cast[name]['marks'] = ['scar_nose', 'freckles']
    before = copy.deepcopy(plan)
    fixed, _ = validate(plan, board, [])
    assert fixed['cast'][0]['marks'] == ['scar_nose', 'freckles']
    assert plan == before
    assert validate(fixed, board, []) == (fixed, [])


@pytest.mark.parametrize('name', ['Doran', 'Senka'])
def test_alternative_traits_preserve_supplied_age_sex_and_size(name):
    board, plan, cast = _supplied(
        f'{name}, a lion, walked. {name} was an adult or a cub, '
        'male or female, massive or small.')
    cast[name].update(age='old', sex='unknown', size=1.1, marks=['freckles'])
    before = copy.deepcopy(plan)
    assert validate(plan, board, []) == (before, [])


def test_explicit_baby_scar_is_preserved_even_when_an_adult_has_it():
    board, plan, cast = _supplied('Tavi, a lion cub, had a scar on his nose. '
                                  'King Roko had scars across his nose and a black mane.')
    cast['Tavi']['marks'] = ['mane_none', 'scar_nose', 'freckles']
    fixed, _ = validate(plan, board, [])
    assert next(c for c in fixed['cast'] if c['name'] == 'Tavi')['marks'] == [
        'mane_none', 'scar_nose', 'freckles']
    assert 'scar_nose' in next(c for c in fixed['cast'] if c['name'] == 'Roko')['marks']
    assert validate(fixed, board, []) == (fixed, [])


def test_unspecified_creative_baby_mark_palette_and_intent_survive():
    board, plan, cast = _supplied('Tavi, a lion cub, slept. King Roko had a black mane.')
    cast['Tavi']['marks'] = ['mane_none', 'scar_nose', 'spots', 'glasses']
    cast['Tavi']['palette'] = {'body': '#123456', 'accent': '#654321', 'eye': '#ABCDEF'}
    plan['storyboard']['sections'][0]['intent'] = 'A dream told through warm silhouettes'
    before = copy.deepcopy(plan)
    assert validate(plan, board, []) == (before, [])


def test_baby_does_not_inherit_parent_mane_scar_sex_age_or_size():
    board, plan, cast = _supplied('Tavi, a lion cub, slept. '
                                  'King Roko had a massive black mane and a scar over his left eye.')
    cast['Tavi'].update(age='adult', sex='male', size=1.4, marks=['mane_gold', 'scar_eye', 'fluffy'])
    before = copy.deepcopy(plan)
    fixed, repairs = validate(plan, board, [])
    baby = next(c for c in fixed['cast'] if c['name'] == 'Tavi')
    assert (baby['age'], baby['sex'], baby['size']) == ('baby', 'unknown', .55)
    assert baby['marks'] == ['fluffy', 'mane_none']
    assert {'age', 'sex', 'size', 'marks'} <= {
        field for field in ('age', 'sex', 'size', 'marks') if any(f'.{field}:' in r for r in repairs)}
    assert plan == before
    assert validate(fixed, board, []) == (fixed, [])


@pytest.mark.parametrize('description', [
    'King Roko had no scar on his nose.',
    'King Roko did not have a scar on his nose.',
    'King Roko might have a scar on his nose.',
    'King Roko had perhaps a scar on his nose.',
    'Cubs had scars across their noses. Lions had black manes.',
    'Tavi and Roko had scars across their noses.',
    'King Roko had a spotless nose.',
    'King Roko walked. She waved her scarred nose at Tavi.',
    'King Roko had a scar on his nose or his eye.',
    'Tavi and Roko had a scar on his nose.',
])
def test_negative_plural_or_ambiguous_other_traits_are_not_borrowed(description):
    board, plan, cast = _supplied('Tavi, a lion cub, slept. King Roko walked. ' + description)
    cast['Tavi']['marks'] = ['mane_none', 'scar_nose', 'spots']
    fixed, _ = validate(plan, board, [])
    baby = next(c for c in fixed['cast'] if c['name'] == 'Tavi')
    assert baby['marks'] == ['mane_none', 'scar_nose', 'spots']
    father = next(c for c in fixed['cast'] if c['name'] == 'Roko')
    assert 'scar_nose' not in father['marks']
    assert 'spots' not in father['marks']
    assert validate(fixed, board, []) == (fixed, [])


def test_explicit_negative_traits_scrub_supplied_cast_without_a_competing_owner():
    board, plan, cast = _supplied('Roko, an adult lion, had no black mane, no scar on his nose, '
                                  'and no scar over his left eye.')
    cast['Roko']['marks'] = ['mane_black', 'scar_nose', 'scar_eye', 'freckles']
    fixed, repairs = validate(plan, board, [])
    assert fixed['cast'][0]['marks'] == ['freckles']
    assert sum('removed' in r for r in repairs) == 3
    assert validate(fixed, board, []) == (fixed, [])


def test_negative_species_and_age_do_not_become_positive_evidence():
    board, plan, cast = _supplied('Roko walked. Roko was not a tiger and not a cub.')
    cast['Roko'].update(kind='quadruped', species='lion', family='feline', age='adult', marks=['scar_nose'])
    assert validate(plan, board, []) == (plan, [])


def test_negated_scar_does_not_erase_an_explicit_cub_introduction():
    board, plan, cast = _supplied('Tavi, a lion cub, had no scar on his nose.')
    assert (cast['Tavi']['species'], cast['Tavi']['age'], cast['Tavi']['size']) == ('lion', 'baby', .55)
    cast['Tavi']['marks'].append('scar_nose')
    fixed, _ = validate(plan, board, [])
    assert fixed['cast'][0]['marks'] == ['mane_none']
    assert validate(fixed, board, []) == (fixed, [])


def test_titles_and_cast_ids_do_not_change_actor_ownership():
    board, plan, cast = _supplied('Tavi, a lion cub, slept. King Roko had a scar on his nose.')
    cast['Roko'].update(name='King Roko', id='father')
    cast['Tavi'].update(id='child', marks=['mane_none', 'scar_nose'])
    fixed, _ = validate(plan, board, [])
    assert next(c for c in fixed['cast'] if c['id'] == 'child')['marks'] == ['mane_none']
    assert 'scar_nose' in next(c for c in fixed['cast'] if c['id'] == 'father')['marks']
    assert validate(fixed, board, []) == (fixed, [])


def test_saved_series_bible_art_override_after_validation_is_reused(tmp_path, monkeypatch):
    board, plan, _ = _supplied('Tavi, a lion cub, slept. King Roko had a scar on his nose.')
    fixed, _ = validate(plan, board, [])
    next(c for c in fixed['cast'] if c['name'] == 'Tavi')['marks'].append('scar_nose')
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'storyboard.json').write_text(json.dumps(board))
    config = project / 'project.json'
    config.write_text(json.dumps({'plan_v3': fixed, 'plan_v3_report': {'fallback': False}}))
    before = config.read_bytes()
    monkeypatch.setattr(llm, 'plan_v3', lambda *a, **k: pytest.fail('revalidated an intentional saved override'))
    assert pipeline.direct_v3(project) == {'fallback': False}
    assert pipeline.settings(project)['plan_v3'] == fixed
    assert config.read_bytes() == before

"""Sleepers, couches, kin and species words on story pages.

A lion story drew paw prints for "lion cubs" and "lionesses", froze its last 12 s on a lion lying awake under the
words "fast asleep", and lost the mother in "hide behind his mother's paws"; a story's mother "half-asleep in front of
the TV" lay crammed into an armchair while the TV left the frame in the next shot. These are the general rules."""
from types import SimpleNamespace

import numpy as np
import pytest

from kinodraw.director.v3.semantics import _detect_cast
from kinodraw.director.v3.story import Reader
from kinodraw.engine import storybook
from kinodraw.engine.storybook import Storybook, meta, preset
from kinodraw.library import creatures

from test_story_shots import pages, shot, staged, visible

PRIDE = [{'id': 'pendo', 'name': 'Pendo', 'kind': 'quadruped', 'species': 'lion', 'family': 'feline', 'age': 'baby',
          'sex': 'male', 'size': .45, 'marks': []},
         {'id': 'mara', 'name': 'Mara', 'kind': 'quadruped', 'species': 'lioness', 'family': 'feline', 'age': 'adult',
          'sex': 'female', 'size': 1., 'marks': []},
         {'id': 'kojo', 'name': 'King Kojo', 'kind': 'quadruped', 'species': 'lion', 'family': 'feline', 'age': 'adult',
          'sex': 'male', 'size': 1.4, 'marks': ['crown']},
         {'id': 'lionesses', 'name': 'Other lionesses', 'kind': 'quadruped', 'species': 'lionesses',
          'family': 'feline', 'age': 'adult', 'sex': 'female', 'size': .95, 'marks': []},
         {'id': 'cubs', 'name': 'Other cubs', 'kind': 'quadruped', 'species': 'lion cubs', 'family': 'feline',
          'age': 'baby', 'sex': 'unknown', 'size': .42, 'marks': []}]


@pytest.mark.parametrize('word, want', [
    ('lion cubs', ('lion', None, 'young')), ('lionesses', ('lion', 'female', None)),
    ('kittens', ('cat', None, 'young')), ('puppies', ('dog', None, 'young')), ('wolves', ('wolf', None, None)),
    ('mice', ('mouse', None, None)), ('elephant calves', ('elephant', None, 'young')),
    ('ducklings', ('duck', None, 'young')), ('foals', ('horse', None, 'young')), ('hens', ('chicken', 'female', None)),
    ('mares', ('horse', 'female', None)), ('ewes', ('sheep', 'female', None)), ('does', ('deer', 'female', None)),
    ('elephant cows', ('elephant', 'female', None)), ('cows', ('cow', None, None)), ('bear cubs', ('bear', None, 'young')),
    ('spotted hyenas', ('spotted hyena', None, None)), ('sheep', ('sheep', None, None))])
def test_species_words_in_the_plural_young_or_female_name_the_animal(word, want):
    assert creatures.species_word(word) == want


@pytest.mark.parametrize('species, age, sex, drawn, band', [
    ('lion cubs', 'adult', None, 'lion', 'young'), ('lion cubs', 'baby', None, 'lion', 'young'),
    ('lionesses', 'adult', None, 'lion', 'adult'), ('spotted hyenas', 'adult', None, 'hyena', 'adult'),
    ('kittens', 'adult', None, 'cat', 'young'), ('wolves', 'adult', None, 'wolf', 'adult')])
def test_a_herd_or_litter_draws_its_animal_never_paw_prints(species, age, sex, drawn, band):
    doodle, _ = preset(species, age, sex)
    assert meta(doodle).get('species') == drawn and meta(doodle).get('age') == band, doodle
    if species == 'lionesses':
        assert meta(doodle).get('sex') == 'female'


def test_a_creature_the_library_cannot_name_is_still_a_creature():
    """"Zorblaxes" of the cat family, "cubs" with no species: never an icon that is not an animal."""
    cast = {'z': {'id': 'z', 'species': 'zorblaxes', 'family': 'feline', 'kind': 'quadruped', 'age': 'adult'},
            'c': {'id': 'c', 'species': 'cubs', 'family': 'other', 'kind': 'quadruped', 'age': 'adult'},
            'b': {'id': 'b', 'species': 'glimmerwings', 'family': 'other', 'kind': 'bird', 'age': 'adult'}}
    book = SimpleNamespace(cast=cast)
    for cid in cast:
        doodle, _ = preset(Storybook._species(book, cid))
        assert doodle != 'fl_paw_prints' and (meta(doodle).get('species') or doodle in storybook.FALLBACK.values()), cid


def test_a_cub_species_word_is_drawn_at_a_cubs_size():
    book = SimpleNamespace(cast={c['id']: c for c in PRIDE}, _human=lambda cid: False, reader=None)
    book._species = lambda cid: Storybook._species(book, cid)
    cubs = Storybook._cast_figure(book, 'cubs')
    grown = dict(PRIDE[4], age='adult', size=1.)
    book.cast['grown'] = dict(grown, id='grown')
    still_cubs = Storybook._cast_figure(book, 'grown')
    adult = Storybook._cast_figure(book, 'mara')
    assert still_cubs.age == 'baby' and still_cubs.height < .6 * adult.height and cubs.age == 'baby'


@pytest.mark.parametrize('text, who', [
    ("Whenever Kojo walked by, Pendo would hide behind his mother's paws.", 'mara'),
    ('Pendo hid behind his mother.', 'mara'),
    ("The cub's mother was gone.", 'mara'),
    ("Pendo curled up against his father's belly.", 'kojo')])
def test_possessive_kin_finds_the_one_parent_even_beside_a_group(text, who):
    """"Other lionesses" are a group, nobody's mother: "his mother's paws" is Mara."""
    (line,) = Reader(PRIDE).read('b', text)
    assert who in line.present


@pytest.mark.parametrize('text, species', [
    ('Mara the lioness loved her cub. Mara walked home.', 'lioness'),
    ('Mara, the lioness, watched the hills. Mara walked.', 'lioness'),
    ('Moss the old tortoise slept in the sun. Moss smiled.', 'tortoise'),
    ('Pip the cub chased a moth. Pip laughed.', 'lion')])
def test_a_name_followed_by_its_species_is_that_animal(text, species):
    cast, _ = _detect_cast([{'spoken': text}])
    assert cast and cast[0]['species'] == species and cast[0]['kind'] != 'human'


SLEEPY = 'Sam came home late. Ada lay on the couch, fast asleep.'


def test_words_that_say_asleep_put_a_lying_figure_to_sleep_and_it_breathes(tmp_path):
    """The plan lays Ada down ('lie'); the words say she is fast asleep: she sleeps, and sleeping is motion (a slow
    breath, Z marks drifting up), not a frozen page. Sam, awake and standing, keeps still."""
    prod = staged(tmp_path, SLEEPY, [shot('b001', 'Ada lay', 'wide', [('ada', 'adult', 'lie', 'no'),
                                                                       ('sam', 'adult', 'stand', 'no')])])
    book = prod.storybook
    _, pages_ = pages(prod, 'b001')
    page = next(p for p in pages_ if 'ada' in [f.key for f in p.figures])
    figures = {f.key: f for f in page.figures}
    assert figures['ada'].pose == 'sleep' and figures['sam'].pose == 'stand'
    book._blinking = lambda f, t: False
    a, b = (np.asarray(book._draw(page, page.start + t), np.int16) for t in (.3, 1.7))
    w = a.shape[1]
    moved = np.abs(a - b).max(axis=2) > 40

    def motion(f):
        x, half = int(f.x * w), int(book._half(f) * w)
        return moved[:, max(0, x - half):x + half].sum()
    assert motion(figures['ada']) > 2000                          # the sleeper's breath and Zs move
    assert motion(figures['ada']) > 2.5 * motion(figures['sam'])   # the awake one holds still (a faint breath at most)


def test_a_sleeper_lies_along_a_real_sofa_with_the_tv_in_every_shot_of_her(tmp_path):
    text = ('Then Sam went downstairs, where Ada was asleep in front of the TV.\n\n'
            '"Mine is broken," Sam said.\n\n"It is not broken," Ada said.')
    refs = ['fl_couch_and_lamp', 'fl_television']
    prod = staged(tmp_path, text, [
        shot('b001', 'Then Sam', 'wide', [('sam', 'adult', 'walk', 'no'), ('ada', 'adult', 'sleep', 'no')],
             set_refs=refs),
        shot('b002', 'Mine is', 'two_shot', [('sam', 'adult', 'talk', 'yes'), ('ada', 'adult', 'sit', 'no')],
             lines=[('Mine is broken,', 'sam')], set_refs=refs),
        shot('b003', 'It is', 'two_shot', [('ada', 'adult', 'talk', 'yes'), ('sam', 'adult', 'look', 'no')],
             lines=[('It is not broken,', 'ada')], set_refs=refs)])
    book = prod.storybook
    _, (asleep,) = pages(prod, 'b001')
    ada = next(f for f in asleep.figures if f.key == 'ada')
    sofa = next(p for p in asleep.set if p.doodle == 'fl_couch_and_lamp')
    sx0, _, sx1, _ = book.stager.frame(sofa.doodle, sofa.x, sofa.ground, sofa.height, sofa.mirror)[2]
    bx0, _, bx1, _ = book._shape(ada, 'sleep', ada.x)[0]
    assert ada.pose == 'sleep' and sx0 - .01 <= bx0 and bx1 <= sx1 + .01   # she lies along it, not over its arms
    assert (sx1 - sx0) > 1.8 * (sofa.height * book.size[1] / book.size[0])  # a long seat, not an armchair
    for bid in ('b001', 'b002', 'b003'):
        _, shots_ = pages(prod, bid)
        for page in shots_:
            if 'ada' not in [f.key for f in page.figures]:
                continue
            tv = next(p for p in page.set if p.doodle == 'fl_television')
            box = book.stager.frame(tv.doodle, tv.x, tv.ground, tv.height, tv.mirror)[2]
            assert visible(book, page, box) > .95, (bid, page.framing)

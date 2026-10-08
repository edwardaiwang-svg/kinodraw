"""A story staged from plan shots (engine.shots) draws its place and its sky, keeps its cast readable and acts out
its roars and eyes, as a page read from the text does."""
import pytest

from kinodraw.engine import sets
from kinodraw.engine.storybook import _sky_kind
from test_story_shots import local, pages, prop, shot, staged

LIONS = [{'id': 'leo', 'name': 'Leo', 'kind': 'quadruped', 'species': 'lion', 'age': 'adult', 'sex': 'male'},
         {'id': 'nia', 'name': 'Nia', 'kind': 'quadruped', 'species': 'lion', 'age': 'adult', 'sex': 'female'},
         {'id': 'kit', 'name': 'Kit', 'kind': 'quadruped', 'species': 'lion', 'age': 'baby', 'sex': 'male'},
         {'id': 'zed', 'name': 'Zed', 'kind': 'quadruped', 'species': 'hyena', 'age': 'adult', 'sex': 'male'}]
MICE = [{'id': 'pip', 'name': 'Pip', 'kind': 'quadruped', 'species': 'mouse', 'age': 'young', 'sex': 'male'},
        {'id': 'gran', 'name': 'Gran', 'kind': 'quadruped', 'species': 'mouse', 'age': 'old', 'sex': 'female'}]


def sky(page):
    return [d for d, *_ in page.sky]


def kinds(page):
    return {_sky_kind(d) for d in sky(page)}


def test_a_night_scene_outdoors_shows_a_moon_and_stars_and_a_dawn_one_a_sun(tmp_path):
    text = 'Pip sat by the old tree and listened to the owls.'
    prod = staged(tmp_path, text, [shot('b001', 'Pip sat', 'wide', [('pip', 'young', 'sit', 'no')], place='forest')],
                  cast=MICE, sky='night_stars')
    _, (page,) = pages(prod, 'b001')
    assert 'moon' in kinds(page) and 'fl_star' in sky(page)
    prod = staged(tmp_path, text, [shot('b001', 'Pip sat', 'wide', [('pip', 'young', 'sit', 'no')], place='forest')],
                  cast=MICE, sky='dawn')
    _, (page,) = pages(prod, 'b001')
    assert 'sun' in kinds(page) and 'moon' not in kinds(page) and 'fl_star' not in sky(page)


def test_a_night_room_shows_its_dark_window_and_no_stars_across_the_wall(tmp_path):
    text = 'Pip lay awake in his room.'
    prod = staged(tmp_path, text, [shot('b001', 'Pip lay', 'wide', [('pip', 'young', 'lie', 'no')], place='bedroom')],
                  cast=MICE, sky='night_stars')
    _, (page,) = pages(prod, 'b001')
    window = next(p for p in page.set if p.doodle in sets.WINDOWS)
    assert window.doodle == 'set_window_night' and 'fl_star' not in sky(page)
    x0, y0, x1, y1 = prod.storybook.planned._box(window)
    assert all(x0 <= x <= x1 and y0 <= y <= y1 for _, x, y, _ in page.sky)     # the moon is in the window


def test_the_sky_never_shows_what_the_words_took_away_until_they_bring_it_back(tmp_path):
    text = ('"Gran, somebody took the moon," said Pip.\n\nThe sky was dark and empty. No moon anywhere.\n\n'
            'Then the cloud slid away, and there was the moon.')
    walk = [('pip', 'young', 'stand', 'no')]
    prod = staged(tmp_path, text, [shot('b001', 'Gran,', 'wide', walk, place='forest',
                                        props=[prop('fl_crescent_moon')], focus='fl_crescent_moon'),
                                   shot('b002', 'The sky', 'wide', walk, place='forest'),
                                   shot('b003', 'Then the cloud', 'wide', walk, place='forest')],
                  cast=MICE, sky='night_stars')
    (_, (took,)), (_, (empty,)), (_, (back,)) = pages(prod, 'b001'), pages(prod, 'b002'), pages(prod, 'b003')
    for page in (took, empty):
        assert 'moon' not in kinds(page) and 'fl_star' in sky(page)
        assert not any('moon' in p.doodle for p in page.set)      # nor as a picture on the ground
    assert 'moon' in kinds(back)


def test_a_nature_place_is_drawn_with_its_cast_on_it(tmp_path):
    text = 'Pip ran through the forest to find his gran.'
    cast = [('pip', 'young', 'run', 'no'), ('gran', 'old', 'stand', 'no')]
    prod = staged(tmp_path, text, [shot('b001', 'Pip ran', 'wide', cast, place='forest')], cast=MICE)
    _, (page,) = pages(prod, 'b001')
    assert len(page.figures) == 2 and page.place == 'forest'
    assert {spec[0] for spec in sets.SETS['forest']} <= {p.doodle if p.kind != 'strip' else 'strip:' + p.doodle
                                                          for p in page.set}


def test_a_story_set_on_grassland_is_drawn_as_the_savanna_whatever_nature_place_the_plan_names(tmp_path):
    text = 'Leo walked across the golden grasslands.\n\nNia waited by the rocks.'
    prod = staged(tmp_path, text, [shot('b001', 'Leo walked', 'wide', [('leo', 'adult', 'walk', 'no')],
                                        place='jungle'),
                                   shot('b002', 'Nia waited', 'wide', [('nia', 'adult', 'stand', 'no')],
                                        place='forest')], cast=LIONS)
    for bid in ('b001', 'b002'):
        _, (page,) = pages(prod, bid)
        assert page.place == 'savanna' and 'set_acacia' in [p.doodle for p in page.set]


def test_a_roar_the_words_give_opens_the_mouth_when_it_is_spoken(tmp_path):
    text = 'Leo stood over the cubs and let out a mighty roar.'
    prod = staged(tmp_path, text, [shot('b001', 'Leo stood', 'wide', [('leo', 'adult', 'stand', 'no')],
                                        place='field')], cast=LIONS)
    span, (page,) = pages(prod, 'b001')
    leo = page.figures[0]
    assert leo.pose == 'roar' and leo.cue == pytest.approx(local(prod, 'b001', 'roar'), abs=.05)
    assert prod.storybook.roar_cues([page], span.start)


def test_a_crowded_page_shows_each_sentence_s_cast_at_a_readable_size(tmp_path):
    text = ('The hyena crept toward the cubs. Leo jumped up. His eyes blazed with fire. '
            'Nia and Kit watched from the rocks.')
    everyone = [('zed', 'adult', 'walk', 'no'), ('leo', 'adult', 'stand', 'no'), ('nia', 'adult', 'stand', 'no'),
                ('kit', 'baby', 'stand', 'no')]
    prod = staged(tmp_path, text, [shot('b001', 'The hyena', 'medium', everyone, place='field')], cast=LIONS)
    book = prod.storybook
    _, story = pages(prod, 'b001')
    at = lambda words: next(p for p in reversed(story) if p.start <= local(prod, 'b001', words) + .01)
    leo = next(f for f in at('Leo jumped').figures if f.key == 'leo')
    assert [f.key for f in at('Leo jumped').figures] == ['leo']
    assert leo.height == pytest.approx(book._cast_figure('leo').height)          # full size, not shrunk to fit four
    blazing = at('His eyes')
    assert blazing.eyes is not None and blazing.eyes.key == 'leo'
    assert {f.key for f in at('Nia and Kit').figures} == {'nia', 'kit'} and at('Nia and Kit').eyes is None


def test_a_page_with_room_for_its_cast_stays_whole_and_pushes_into_eyes_only_while_they_are_spoken_of(tmp_path):
    text = 'Pip and Gran sat by the pond for a long while. Gran looked at Pip, her eyes kind and warm. Then they rested.'
    both = [('pip', 'young', 'sit', 'no'), ('gran', 'old', 'sit', 'no')]
    prod = staged(tmp_path, text, [shot('b001', 'Pip and Gran', 'wide', both, place='lake')], cast=MICE)
    _, story = pages(prod, 'b001')
    assert all({f.key for f in p.figures} == {'pip', 'gran'} and p.view == story[0].view for p in story)
    assert [p.eyes is not None for p in story] == [False, True, False]
    assert story[1].start == pytest.approx(local(prod, 'b001', 'Gran looked'), abs=.05)
    assert story[2].start == pytest.approx(local(prod, 'b001', 'Then they'), abs=.05)


def test_a_story_staged_from_shots_shows_its_title_on_the_first_page(tmp_path):
    text = '# The Brave Cub\n\nLeo walked across the field. Nia followed him.'
    prod = staged(tmp_path, text, [shot('b001', 'Leo walked', 'wide', [('leo', 'adult', 'walk', 'no')],
                                        place='field')], cast=LIONS)
    titled = [p for span in prod.spans if span.story for p in span.story if p.title]
    assert len(titled) == 1 and titled[0].title == 'The Brave Cub' and titled[0].start == 0

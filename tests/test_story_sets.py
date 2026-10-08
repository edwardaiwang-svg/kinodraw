"""Story pages take place somewhere: a set read from the text, with the everyday things a line names in it
(J, 2026-10-08: houses for a town, the letter propped against the lamp on the desk, a couch and a TV, the orange
rolling into the street)."""
import json

import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.story import Reader, _things, story_picture
from kinodraw.engine import render, sets, timeline

PEOPLE = [{'id': 'mia', 'name': 'Mia', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female'},
          {'id': 'sam', 'name': 'Sam', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male'}]


def places(text):
    return [s.place for s in Reader(PEOPLE).read('b1', text)]


def test_a_line_takes_place_where_its_text_says():
    assert places('In the village of Brookfield, the bakers woke early.') == ['town']
    assert places('Then Sam went downstairs, where Mia was dozing in front of the TV.') == ['living_room']
    assert places('Sam went back upstairs.') == ['bedroom']
    assert places('Mia sat in the kitchen. The rain drummed on the bus roof.') == ['kitchen', 'bus']
    assert places('She left the shop and crossed the street.') == ['street']        # where the line ends up
    assert places('"Meet me at the park," Mia said.') == [None]                      # speech names no place
    assert places('Sam walked home under the trees.') == [None]


def test_everyday_things_and_furniture_can_stand_in_a_story():
    for doodle in ('office_desk', 'fl_couch_and_lamp', 'fl_television', 'fl_love_letter', 'fl_envelope', 'fl_bed',
                   'fl_house', 'fl_tangerine', 'newspaper', 'fl_chair'):
        assert story_picture(doodle), doodle
    for doodle in ('fl_person_standing', 'fl_bar_chart', 'tb_sofa', 'question_big', 'fl_envelope_with_arrow',
                   'fl_money_with_wings', 'red_herring', 'sleep_bed'):
        assert not story_picture(doodle), doodle


def test_things_rest_lean_and_move_as_the_line_says():
    kept = _things('He kept his on his desk, propped against the lamp.')
    unnamed = next(t for t in kept if t['doodle'] is None)
    assert unnamed['on'] == ('against', 'set_desk_lamp')            # "his" envelope, against the lamp
    assert {t['doodle'] for t in kept if t['target']} == {'set_desk', 'set_desk_lamp'}
    assert [(t['doodle'], t['motion'][0]) for t in _things('The apple that rolled under the bench.')
            if t['motion']] == [('fl_red_apple', 'roll')]
    assert [t['motion'][0] for t in _things("The stranger's dropped grocery bag.")] == ['fall']
    assert [t['motion'][0] for t in _things('Then she dropped the cup.')] == ['fall']
    assert _things('Add half a cup of rolled oats.') == []           # a measure, and "rolled" describes the oats
    assert [t['doodle'] for t in _things('The sky turned orange at dusk.')] == []     # a colour, not the fruit


def book(tmp_path, text, cast=()):
    """A story's storybook production, planned as a story page per beat with this cast (as a cloud plan would)."""
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['storyboard']['genre'] = 'story'
    plan['cast'] = [dict(c, family='human', size=1, palette={}, marks=[], temperament='calm') for c in cast]
    for scene in plan['scenes']:
        scene.update(treatment='character', composition='stage', text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]},
                     elements=[{'kind': 'cast', 'ref': c['id']} for c in cast])
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    return prod


def page(prod, words):
    """The shot narrating these words."""
    for span in prod.spans:
        for bid in span.spec['beat_ids']:
            spoken = prod.by_id[bid]['spoken']
            if words in spoken:
                timing = prod.tl['beats'][bid]
                at = timing['start'] - span.start + timing['char_times'][spoken.index(words)]
                return next(s for s in reversed(span.story) if s.start <= at + 1e-6), span
    raise AssertionError(words)


STORY = ('# The Letter\n\n'
         'In the town of Brookfield, every child got a letter on the day they were born.\n\n'
         'Mia kept hers on her desk, propped against the lamp, and one night she read it.\n\n'
         "The stranger's dropped grocery bag. The orange that rolled into the street.\n\n"
         'Then she went downstairs, where her father was asleep in front of the TV. The rain did not stop.')


@pytest.fixture(scope='module')
def letter(tmp_path_factory):
    return book(tmp_path_factory.mktemp('letter'), STORY, PEOPLE[:1])


def test_a_town_is_houses_along_a_street_never_a_palm_tree(letter):
    shot, _ = page(letter, 'In the town of Brookfield')
    drawn = [p.doodle for p in shot.set]
    assert shot.place == 'town'
    assert 'road' in drawn and sum('house' in d for d in drawn) >= 3, drawn
    assert not any('palm' in d for d in drawn + [d for d, *_ in shot.props])


def test_the_letter_leans_against_the_lamp_on_the_desk(letter):
    shot, _ = page(letter, 'propped against the lamp')
    desk = next(s for s in shot.supports if s.doodle == 'set_desk')
    lamp = next(p for p in shot.set if p.doodle == 'set_desk_lamp')
    paper = next(p for p in shot.set if p.doodle == 'fl_page_facing_up')       # "hers": the letter
    assert shot.place == 'study'
    for p in (lamp, paper):
        assert abs(p.ground - desk.y) < .01 and desk.x0 <= p.x <= desk.x1          # standing on the desk top
    stager = letter.storybook.stager
    lamp_box = stager.frame(lamp.doodle, lamp.x, lamp.ground, lamp.height)[2]
    paper_box = stager.frame(paper.doodle, paper.x, paper.ground, paper.height)[2]
    assert min(abs(paper_box[2] - lamp_box[0]), abs(lamp_box[2] - paper_box[0])) < .015    # touching it
    assert paper.rotate != 0                                                                  # leaning on it


def test_the_orange_from_the_dropped_bag_rolls_into_the_street(letter):
    shot, _ = page(letter, 'The orange that rolled')
    orange = next(p for p in shot.set if p.doodle == 'fl_tangerine')
    road = next(p for p in shot.set if p.doodle == 'road')
    assert shot.place == 'street' and orange.motion == 'roll'
    assert any(p.doodle == 'set_grocery_bag' for p in shot.set)          # the bag from the line before is still there
    before = letter.storybook._moving(orange, orange.cue - .5)
    after = letter.storybook._moving(orange, orange.cue + 3)
    assert abs(after[0] - before[0]) > .2 and after[2] != before[2]        # it travels, turning as it goes
    assert road.top < after[1] < road.ground                               # and ends up in the road


def test_the_living_room_has_a_couch_and_a_tv_and_a_sleeper_can_lie_on_the_couch(letter):
    shot, span = page(letter, 'asleep in front of the TV')
    drawn = [p.doodle for p in shot.set]
    assert shot.place == 'living_room'
    assert 'fl_couch_and_lamp' in drawn and 'fl_television' in drawn and 'set_tv_stand' in drawn
    couch = letter.storybook.support(shot, 'sleep')
    assert couch.doodle == 'fl_couch_and_lamp' and couch.x0 < couch.x1 and .5 < couch.y < sets.FLOOR
    assert letter.storybook.support(shot, 'sit') is couch


def test_indoors_the_sky_is_in_the_window_and_the_rain_is_not_drawn_across_the_room(letter, monkeypatch):
    shot, span = page(letter, 'The rain did not stop')
    assert shot.place == 'living_room'                       # the line names no place: the room continues
    window = next(p for p in shot.set if p.doodle in sets.WINDOWS)
    x0, y0, x1, y1 = letter.storybook.stager.frame(window.doodle, window.x, window.ground, window.height)[2]
    assert all(x0 < x < x1 and y0 < y < y1 for _, x, y, _ in shot.sky)
    drawn = []
    monkeypatch.setattr(type(letter.storybook), '_rain', lambda self, overlay, local: drawn.append(local))
    letter.storybook._draw(shot, shot.start + .5)
    assert not drawn


def test_a_page_with_nothing_named_is_never_a_palm_tree(tmp_path):
    prod = book(tmp_path, '# Quiet\n\nIt was quiet for a long while.\n\nNothing happened at all.')
    for span in prod.spans:
        for shot in span.story:
            drawn = [p.doodle for p in shot.set] + [d for d, *_ in shot.props]
            assert drawn and not any('palm' in d for d in drawn), drawn


def test_every_set_draws_and_its_pictures_exist():
    from kinodraw import library
    from kinodraw.engine.storybook import _svg
    for place, pieces in sets.SETS.items():
        for spec in pieces:
            if spec[0].startswith('strip:'):
                assert sets.strip(spec[0][6:], 400).startswith('<svg')
            else:
                assert sets.svg(spec[0]) or library.resolve(spec[0]), (place, spec[0])
                assert _svg(spec[0])[1] > 0
    from kinodraw.director.v3.story import THINGS
    for _, doodle, _, _ in THINGS:
        assert sets.svg(doodle) or library.resolve(doodle), doodle


def test_a_kitchen_has_its_counter_stove_fridge_and_table_and_the_pan_goes_on_the_stove(tmp_path):
    prod = book(tmp_path, '# Breakfast\n\nMia cracked two eggs into a bowl in the kitchen.\n\n'
                          'Then she heated a pan with a little oil.', PEOPLE[:1])
    shot, _ = page(prod, 'heated a pan')
    drawn = [p.doodle for p in shot.set]
    assert shot.place == 'kitchen'
    assert {'set_counter', 'set_stove', 'set_fridge', 'set_table'} <= set(drawn)
    stove = next(s for s in shot.supports if s.doodle == 'set_stove')
    pan = next(p for p in shot.set if p.doodle == 'fl_shallow_pan_of_food')
    assert abs(pan.ground - stove.y) < .01 and stove.x0 <= pan.x <= stove.x1

"""A plan's shots stage the storybook's pages (director/v3/schema.py ``scene.shots``): each shot starts at its
starts_at words, shows its own cast at the age and pose it gives, in its place's set, framed as its type says, with
speech bubbles from the plan's speaker on that person (or in from the frame's edge when they are heard off screen).
With no shots a scene keeps the text reading."""
import json

import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, sets, timeline
from kinodraw.engine.storybook import Bubble, Figure, Storybook

PEOPLE = [{'id': 'mia', 'name': 'Mia', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female'},
          {'id': 'sam', 'name': 'Sam', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male'},
          {'id': 'ada', 'name': 'Ada', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'female'}]


def shot(bid, starts_at, kind, cast, place='living_room', props=(), focus='', writing='', lines=(), set_refs=()):
    """A plan shot; cast entries are (id, age, pose, speaking)."""
    return {'beat_id': bid, 'starts_at': starts_at, 'shot': kind,
            'setting': {'place': place, 'time': 'day', 'set_refs': list(set_refs)},
            'cast': [{'id': c, 'age': a, 'pose': p, 'speaking': s} for c, a, p, s in cast],
            'lines': [{'quote': q, 'speaker': who} for q, who in lines], 'props': list(props),
            'focus_ref': focus, 'writing': writing}


def prop(ref, relation='none', to='', motion='none'):
    return {'ref': ref, 'relation': relation, 'to': to, 'motion': motion}


def staged(tmp_path, text, shots, cast=PEOPLE):
    """A story's storybook production with these plan shots on its scenes (a scene with none reads its text)."""
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['storyboard']['genre'] = 'story'
    plan['cast'] = [dict(c, family='human', size=1, palette={}, marks=[], temperament='calm') for c in cast]
    for scene in plan['scenes']:
        scene.update(treatment='character', composition='stage', text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]},
                     elements=[{'kind': 'cast', 'ref': c['id']} for c in cast])
        mine = [s for s in shots if s['beat_id'] in scene['beat_ids']]
        if mine:
            scene['shots'] = mine
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    return prod


def pages(prod, bid):
    """(span, story shots) of the scene holding this beat."""
    span = next(s for s in prod.spans if bid in s.spec['beat_ids'])
    return span, span.story


def local(prod, bid, words):
    """Span-local seconds these words of the beat are spoken."""
    span = next(s for s in prod.spans if bid in s.spec['beat_ids'])
    spoken = prod.by_id[bid]['spoken']
    timing = prod.tl['beats'][bid]
    return timing['start'] - span.start + timing['char_times'][spoken.index(words)]


def keys(page):
    return [f.key for f in page.figures if not f.crowd]


def visible(book, page, box):
    """Share of a frame-share box that the shot's locked framing shows."""
    w, h = book.size
    (a, b, _), (c, d, _) = book._to_screen(box[0], box[1], list(page.view)), book._to_screen(box[2], box[3], list(page.view))
    inside = max(0, min(c, w) - max(a, 0)) * max(0, min(d, h) - max(b, 0))
    return inside / max(1e-9, (c - a) * (d - b))


# ------------------------------------------------------------------ staging, place and timing
def test_a_scene_with_shots_stages_each_from_its_shot_and_a_scene_without_reads_its_text(tmp_path):
    prod = staged(tmp_path, 'Sam walked through the town square.\n\nIn the village of Brookfield, the bakers woke early.',
                  [shot('b001', 'Sam walked', 'wide', [('mia', 'teen', 'sit', 'no')], place='kitchen')])
    _, (page,) = pages(prod, 'b001')
    assert page.place == 'kitchen' and keys(page) == ['mia']          # the shot's place and cast, not the text's
    mia = page.figures[0]
    assert mia.age == 'teen' and mia.pose == 'sit'
    _, read = pages(prod, 'b002')
    assert read[0].place == 'town' and not read[0].framing             # no shots: the text reading


def test_plan_places_map_onto_the_storybook_sets():
    from kinodraw.engine.shots import place_for
    assert place_for('kitchen') == 'kitchen' and place_for('living_room') == 'living_room'
    assert place_for('home_exterior') == 'house' and place_for('dining_room') == 'dining'
    assert place_for('field') == 'countryside' and place_for('village') == 'town'
    assert place_for('none', 'kitchen') == 'kitchen' and place_for('other', 'bus') == 'bus'
    assert place_for('storage_room') in sets.SETS and place_for('storage_room') in sets.INTERIOR
    assert place_for('volcano_rim') in sets.SETS                        # unknown: a neutral set, never nothing


def test_each_shot_starts_at_its_words(tmp_path):
    text = 'Sam stood by the window. Mia came in with a cup. Then Sam turned around.'
    prod = staged(tmp_path, text, [shot('b001', 'Sam stood', 'wide', [('sam', 'adult', 'stand', 'no')]),
                                   shot('b001', 'Mia came in', 'medium', [('mia', 'young', 'walk', 'no')]),
                                   shot('b001', 'Then Sam turned', 'close', [('sam', 'adult', 'look', 'no')])])
    _, story = pages(prod, 'b001')
    assert [p.framing for p in story] == ['wide', 'medium', 'close']
    assert story[1].start == pytest.approx(local(prod, 'b001', 'Mia came in'), abs=.02)
    assert story[2].start == pytest.approx(local(prod, 'b001', 'Then Sam turned'), abs=.02)


# ------------------------------------------------------------------ framing
def test_framing_follows_the_shot_type_and_never_zooms_within_a_shot(tmp_path):
    text = 'Sam stood by the window. Mia stood by the door. Sam smiled. They looked at each other.'
    both = [('sam', 'adult', 'stand', 'no'), ('mia', 'young', 'stand', 'no')]
    prod = staged(tmp_path, text, [shot('b001', 'Sam stood', 'wide', both), shot('b001', 'Mia stood', 'medium', both),
                                   shot('b001', 'Sam smiled', 'close', [('sam', 'adult', 'look', 'no')]),
                                   shot('b001', 'They looked', 'two_shot', both)])
    book = prod.storybook
    _, (wide, medium, close, two) = pages(prod, 'b001')
    assert wide.view[2] == 1. and 1. < medium.view[2] < close.view[2]
    sam = close.figures[0]
    top, (x0, _, x1, _) = book._shape(sam, 'stand', sam.x)[0][1], book._shape(sam, 'stand', sam.x)[0]
    assert visible(book, close, (x0, top, x1, top + .1)) > .9               # the head is in the close-up
    assert visible(book, close, book._shape(sam, 'stand', sam.x)[0]) < .7   # ... and not the whole body
    for f in two.figures:
        x0, y0, x1, y1 = book._shape(f, book._pose_name(f.pose), f.x)[0]
        assert visible(book, two, (x0, y0, x1, y0 + (y1 - y0) * .6)) > .9   # both people, from the knees up
    for page in (wide, medium, close, two):
        assert book._camera(page, page.start + .1) == pytest.approx(book._camera(page, page.end - .1))


def test_an_insert_frames_the_thing_and_what_it_leans_against(tmp_path):
    prod = staged(tmp_path, 'On the desk was an envelope, propped against the lamp.',
                  [shot('b001', 'On the desk', 'insert', [], place='bedroom', focus='fl_envelope',
                        props=[prop('fl_envelope', 'against', 'set_desk_lamp')])])
    book = prod.storybook
    _, (page,) = pages(prod, 'b001')
    envelope = next(p for p in page.set if p.doodle == 'fl_envelope')
    lamp = next(p for p in page.set if p.doodle == 'set_desk_lamp')
    assert page.view[2] > 2.
    for piece in (envelope, lamp):
        assert visible(book, page, book.stager.frame(piece.doodle, piece.x, piece.ground, piece.height)[2]) > .9


def test_a_first_person_shot_fills_the_frame_with_the_words_read(tmp_path):
    text = ('Mia unfolded the note and read: Feed the cat. Water the plants. Call Gran.\n\n'
            'She folded it again.')
    prod = staged(tmp_path, text, [shot('b001', 'Mia unfolded', 'first_person', [('mia', 'young', 'read', 'no')],
                                        focus='fl_scroll'),
                                   shot('b002', 'She folded', 'first_person', [('mia', 'young', 'read', 'no')],
                                        focus='fl_scroll', writing='Back by six.')])
    _, (page,) = pages(prod, 'b001')
    assert page.page['kind'] == 'paper' and page.page['lines'] == ['Feed the cat.', 'Water the plants.', 'Call Gran.']
    assert not page.figures and not page.bubbles
    _, (planned,) = pages(prod, 'b002')
    assert planned.page['lines'] == ['Back by six.']                     # the plan's writing wins


# ------------------------------------------------------------------ speakers and bubbles
def test_a_voice_heard_off_screen_is_not_drawn_and_its_bubble_comes_in_from_the_edge(tmp_path):
    prod = staged(tmp_path, '"Dinner is ready!" Sam called from the kitchen.',
                  [shot('b001', 'Dinner is ready', 'medium', [('mia', 'young', 'look', 'no'),
                                                              ('sam', 'adult', 'talk', 'off_screen')],
                        lines=[('Dinner is ready!', 'sam')])])
    book = prod.storybook
    _, (page,) = pages(prod, 'b001')
    assert keys(page) == ['mia']
    (bubble,) = page.bubbles
    assert bubble.speaker == 'sam' and bubble.side in ('l', 'r')
    mouth, box, tip, *_ = book._bubble_plan(page, bubble)
    assert mouth is None and tip[0] in (3., book.size[0] - 3.)


def test_the_plan_speaker_wins_unless_the_text_says_otherwise(tmp_path):
    both = [('sam', 'adult', 'talk', 'yes'), ('mia', 'young', 'look', 'no')]
    prod = staged(tmp_path, '"We should go home now."\n\n"Hurry up, Mia," Sam said.',
                  [shot('b001', 'We should', 'two_shot', both, lines=[('We should go home now.', 'sam')]),
                   shot('b002', 'Hurry up', 'two_shot', [('mia', 'young', 'talk', 'yes'), ('sam', 'adult', 'look', 'no')],
                        lines=[('Hurry up, Mia,', 'mia')])])
    _, (first,) = pages(prod, 'b001')
    assert [b.speaker for b in first.bubbles] == ['sam']                 # untagged: the plan's speaker
    _, (second,) = pages(prod, 'b002')
    assert [b.speaker for b in second.bubbles] == ['sam']                # tagged "Sam said" and addressed to Mia


def test_a_bubble_is_never_empty_and_finishes_with_its_speech():
    times = tuple(1. + .05 * i for i in range(len('Hello there, friend.')))
    bubble = Bubble('mia', 'Hello there, friend.', 1., times[-1] + .6, times=times)
    assert Storybook.shown(bubble, 1.) >= len('Hello')                    # it pops in with its first word
    assert Storybook.shown(bubble, times[-1]) == len(bubble.text)         # whole when the line is spoken
    assert Storybook.shown(bubble, bubble.end - .1) == len(bubble.text)   # ... and held whole a moment


def test_a_long_line_is_bubbled_in_chunks_and_each_bubble_is_recorded_for_the_captions(tmp_path):
    quote = ("It's not an answer to anything. It's just a list of things that happened to you, "
             "one after another, all of them.")
    prod = staged(tmp_path, f'"{quote}" Sam said.',
                  [shot('b001', "It's not an", 'two_shot', [('sam', 'adult', 'talk', 'yes'), ('mia', 'young', 'look', 'no')],
                        lines=[(quote, 'sam')])])
    book = prod.storybook
    _, (page,) = pages(prod, 'b001')
    assert len(page.bubbles) >= 2 and all(len(b.text.split()) <= 12 for b in page.bubbles)
    assert all(b.speaker == 'sam' for b in page.bubbles)
    spoken = prod.by_id['b001']['spoken']
    rows = [r for r in book.bubbled if r['beat'] == 'b001']
    assert rows and all(spoken[r['start']:r['end']] == r['text'] and r['speaker'] == 'sam' for r in rows)


def test_a_bubble_never_covers_a_face(tmp_path):
    text = '"Is that the one?" Sam asked. "Yes, that is the one," Mia said. "Then take it," said Ada.'
    three = [('sam', 'adult', 'talk', 'yes'), ('mia', 'young', 'talk', 'yes'), ('ada', 'adult', 'talk', 'yes')]
    prod = staged(tmp_path, text, [shot('b001', 'Is that', 'wide', three, lines=[('Is that the one?', 'sam')]),
                                   shot('b001', 'Yes, that', 'two_shot', three[:2], lines=[('Yes, that is the one,', 'mia')]),
                                   shot('b001', 'Then take', 'medium', three, lines=[('Then take it,', 'ada')])])
    book = prod.storybook
    _, story = pages(prod, 'b001')
    checked = 0
    for page in story:
        heads = []
        for g in page.figures:
            for _, head in book._shapes(g):
                (a, b, _), (c, d, _) = book._to_screen(head[0], head[1], list(page.view)), \
                    book._to_screen(head[2], head[3], list(page.view))
                heads.append((a, b, c, d))
        for bubble in page.bubbles:
            plan = book._bubble_plan(page, bubble)
            assert plan is not None, bubble.text
            x0, y0, x1, y1 = plan[1]
            for a, b, c, d in heads:
                assert min(x1, c) <= max(x0, a) or min(y1, d) <= max(y0, b), (bubble.text, page.framing)
            checked += 1
    assert checked >= 3


# ------------------------------------------------------------------ people on the page
def test_age_variants_of_one_person_are_that_person_once_at_the_shots_age(tmp_path):
    cast = PEOPLE + [{'id': 'sam_old', 'name': 'Old Sam', 'kind': 'human', 'species': 'human', 'age': 'old',
                      'sex': 'male'}]
    prod = staged(tmp_path, 'Sixty years later, Sam sat by the window.',
                  [shot('b001', 'Sixty years', 'wide', [('sam_old', 'old', 'sit', 'no'), ('sam', 'old', 'sit', 'no')])],
                  cast=cast)
    _, (page,) = pages(prod, 'b001')
    assert keys(page) == ['sam'] and page.figures[0].age == 'elder'


def test_seated_people_keep_their_own_seat_and_never_overlap(tmp_path):
    sitting = [('sam', 'old', 'sit', 'no'), ('mia', 'teen', 'sit', 'no'), ('ada', 'adult', 'sit', 'no')]
    prod = staged(tmp_path, 'Sam sat in the armchair. Mia and Ada sat down too. They all watched the TV.',
                  [shot('b001', 'Sam sat', 'wide', sitting[:1], set_refs=['set_armchair']),
                   shot('b001', 'Mia and Ada', 'wide', sitting, set_refs=['set_armchair']),
                   shot('b001', 'They all', 'wide', sitting[::-1], set_refs=['set_armchair'])])
    book = prod.storybook
    _, (first, second, third) = pages(prod, 'b001')
    sam = next(f for f in first.figures if f.key == 'sam')
    assert any(s.doodle == 'set_armchair' and s.x0 <= sam.x <= s.x1 for s in first.supports)
    for page in (second, third):
        bodies = sorted((book._shape(f, 'sit', f.x)[0][0], book._shape(f, 'sit', f.x)[0][2]) for f in page.figures)
        assert all(a[1] <= b[0] + .01 for a, b in zip(bodies, bodies[1:])), bodies
        assert all(f.pose == 'sit' and f.ground < sets.FLOOR - .02 for f in page.figures)   # on a seat, not the floor
    assert {f.key: f.x for f in second.figures} == {f.key: f.x for f in third.figures}


def test_a_sleeper_lies_on_the_couch_and_sits_up_to_speak(tmp_path):
    prod = staged(tmp_path, 'Ada was asleep on the couch.\n\n"Is that you?" Ada asked.',
                  [shot('b001', 'Ada was', 'wide', [('ada', 'adult', 'sleep', 'no')]),
                   shot('b002', 'Is that', 'medium', [('ada', 'adult', 'sleep', 'yes')], lines=[('Is that you?', 'ada')])])
    _, (asleep,) = pages(prod, 'b001')
    ada = asleep.figures[0]
    couch = next(s for s in asleep.supports if s.kind == 'seat' and 'couch' in s.doodle)
    assert ada.pose == 'sleep' and ada.ground == pytest.approx(couch.y) and couch.x0 <= ada.x <= couch.x1
    _, (awake,) = pages(prod, 'b002')
    assert awake.figures[0].pose == 'sit' and awake.bubbles[0].speaker == 'ada'


def test_a_held_thing_stays_below_the_chin(tmp_path):
    prod = staged(tmp_path, 'Sam held up the envelope.',
                  [shot('b001', 'Sam held', 'medium', [('sam', 'adult', 'hold', 'no')],
                        props=[prop('fl_envelope', 'held_by', 'sam')])])
    book = prod.storybook
    _, (page,) = pages(prod, 'b001')
    held = next(p for p in page.set if p.doodle == 'fl_envelope')
    sam = page.figures[0]
    x, ground, anchor_y = book.held_at(held, page, page.start + .5)
    doodle, mirror, _ = book._pose_doodle(sam, page.start + .5)
    _, mouth = book._point(doodle, mirror, 'mouth', sam.x, sam.ground, sam.height, book._reference(sam))
    top = ground - held.height * anchor_y
    assert top > mouth


def test_things_never_stand_on_or_inside_a_person(tmp_path):
    from kinodraw.engine.storybook import Shot
    book = staged(tmp_path, 'Sam stood by the pond.', []).storybook
    sam = Figure('sam', 'human', 'adult', 'male', x=.5)
    pond = sets.Piece('fl_potted_plant', .5, sets.FLOOR, .14, kind='thing')
    held = sets.Piece('fl_tangerine', .5, sets.FLOOR, .06, kind='hand', holder='sam')
    page = Shot(0., 2., figures=[sam], set=[pond, held], props=[('fl_red_apple', .52, sets.FLOOR, .1)])
    book.props_clear(page, [sam])
    body = book._shape(sam, 'stand', sam.x)[0]
    for doodle, x, ground, height in [(pond.doodle, pond.x, pond.ground, pond.height)] + page.props:
        x0, _, x1, _ = book.stager.frame(doodle, x, ground, height)[2]
        assert min(x1, body[2]) - max(x0, body[0]) <= .15 * min(x1 - x0, body[2] - body[0]), doodle
    assert held.x == .5                                                  # a thing in a hand stays in it


def test_an_animal_in_the_cast_is_not_also_drawn_as_a_picture(tmp_path):
    cast = PEOPLE + [{'id': 'tom', 'name': 'Tom', 'kind': 'animal', 'species': 'cat', 'age': 'adult', 'sex': 'male'}]
    prod = staged(tmp_path, 'Tom the cat sat by the window.',
                  [shot('b001', 'Tom the cat', 'wide', [('tom', 'adult', 'sit', 'no')], props=[prop('fl_cat')])],
                  cast=cast)
    _, (page,) = pages(prod, 'b001')
    assert keys(page) == ['tom'] and 'fl_cat' not in [p.doodle for p in page.set]


def test_nobody_walks_on_the_spot_and_seated_people_cast_no_floating_shadow(tmp_path):
    from PIL import Image
    from kinodraw.engine.storybook import Shot
    book = staged(tmp_path, 'Sam waited by the door.', []).storybook
    sam = Figure('sam', 'human', 'adult', 'male', pose='walk', travel=0.)
    assert book._pose_doodle(sam, 1.0)[2] == 'stand' and book._pose_doodle(sam, 1.0) == book._pose_doodle(sam, 1.13)
    sam.travel = .3
    assert book._pose_doodle(sam, 1.0)[2] == 'walk'                       # walking somewhere still strides
    mia = Figure('mia', 'human', 'child', 'female', pose='sit', ground=sets.FLOOR - .12)
    overlay = Image.new('RGBA', tuple(book.size), (0, 0, 0, 0))
    book._shadows(overlay, Shot(0., 2., figures=[mia]), .5, [.5, .5, 1.])
    assert overlay.getbbox() is None                                      # sitting on a couch, not on the floor
    book._shadows(overlay, Shot(0., 2., figures=[Figure('sam', 'human', 'adult', 'male')]), .5, [.5, .5, 1.])
    assert overlay.getbbox() is not None

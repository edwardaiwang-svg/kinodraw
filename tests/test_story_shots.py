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
    gap = box[0] if tip[0] < book.size[0] / 2 else book.size[0] - box[2]
    assert gap < .1 * book.size[0]                                        # it hugs the edge it is heard from


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
    assert [r.get('plan_speaker') for r in prod.storybook.bubbled if r['beat'] == 'b002'] == ['mia']   # reported


def test_a_speech_tag_naming_the_speaker_beats_the_plan(tmp_path):
    prod = staged(tmp_path, '"This part is my favorite," Ada says, flipping the pancake.',
                  [shot('b001', 'This part', 'two_shot', [('sam', 'adult', 'talk', 'yes'), ('ada', 'adult', 'look', 'no')],
                        lines=[('This part is my favorite,', 'sam')])])
    _, (page,) = pages(prod, 'b001')
    assert [b.speaker for b in page.bubbles] == ['ada']


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


def test_a_thing_put_in_an_age_variant_is_in_that_persons_hands(tmp_path):
    cast = PEOPLE + [{'id': 'sam_old', 'name': 'Old Sam', 'kind': 'human', 'species': 'human', 'age': 'old',
                      'sex': 'male'}]
    prod = staged(tmp_path, 'Sixty years later, Sam found the envelope.',
                  [shot('b001', 'Sixty years', 'medium', [('sam_old', 'old', 'stand', 'no')], place='bedroom',
                        props=[prop('fl_envelope', 'in', 'sam_old')], set_refs=['office_desk'])],
                  cast=cast)
    _, (page,) = pages(prod, 'b001')
    held = next(p for p in page.set if p.doodle == 'fl_envelope')
    assert keys(page) == ['sam'] and held.kind == 'hand' and held.holder == 'sam'


def test_a_thing_beside_someone_off_the_page_is_still_drawn(tmp_path):
    prod = staged(tmp_path, 'Sam found the envelope.',
                  [shot('b001', 'Sam found', 'medium', [('sam', 'adult', 'stand', 'no')], place='bedroom',
                        props=[prop('fl_envelope', 'beside', 'ada')])])
    _, (page,) = pages(prod, 'b001')
    assert 'fl_envelope' in [p.doodle for p in page.set] and 'ada' not in [p.doodle for p in page.set]


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
    chin = max(head[3] for _, head in book._shapes(sam))
    assert top > mouth and top >= chin - 1e-6                           # under the whole face, not just the mouth


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


def test_a_thing_only_talked_about_is_not_in_the_room_and_a_home_video_shows_its_contents_and_year(tmp_path):
    from kinodraw.engine.shots import year_in
    assert year_in('Nineteen eighty-nine.') == '1989' and year_in('in 2004, then') == '2004'
    assert year_in('two thousand and five') == '2005' and year_in('nineteen oh six') == '1906'
    assert year_in('She was nineteen.') is None
    text = ('"Whatever happened to a movie where a man just rides a horse?" Sam asked.\n\n'
            'On the TV, a little girl was jumping in puddles. "That is your mother, nineteen eighty-nine," Sam said.')
    prod = staged(tmp_path, text, [
        shot('b001', 'Whatever', 'two_shot', [('sam', 'old', 'talk', 'yes'), ('mia', 'teen', 'look', 'no')],
             props=[prop('fl_horse'), prop('fl_man')], focus='fl_horse', lines=[('Whatever happened', 'sam')]),
        shot('b002', 'On the TV', 'medium', [('sam', 'old', 'sit', 'no'), ('mia', 'teen', 'look', 'no')],
             props=[prop('fl_girl', 'in', 'fl_television'), prop('puddle')], focus='fl_television')])
    _, (talk,) = pages(prod, 'b001')
    assert not {'fl_horse', 'fl_man'} & {p.doodle for p in talk.set}       # spoken of, not in the room
    _, (video,) = pages(prod, 'b002')
    (host, shown), = video.screen
    assert 'fl_girl' in shown and 'puddle' in shown and 'stamp:1989' in shown
    assert 'puddle' not in [p.doodle for p in video.set]                    # the puddles are on the video


def test_a_framing_never_cuts_a_person_in_half_at_its_side(tmp_path):
    from kinodraw.engine.storybook import Shot
    book = staged(tmp_path, 'Sam watched the TV.', []).storybook
    tv = (.75, .45, .9, .62)                                              # what the shot looks at
    for x in (.62, .5, .3):
        sam = Figure('sam', 'human', 'elder', 'male', pose='sit', x=x, ground=sets.FLOOR - .1)
        page = Shot(0., 2., figures=[sam], view=(.79, .63, 2.4))
        book.planned._uncut(page, [sam], tv)
        cx, _, zoom = page.view
        left, right = cx - .5 / zoom, cx + .5 / zoom
        x0, _, x1, _ = book._shape(sam, 'sit', sam.x)[0]
        assert x1 <= left + .002 or x0 >= right - .002 or (x0 >= left - .002 and x1 <= right + .002), x
        assert left <= tv[0] + .002 and tv[2] - .002 <= right                # the TV stays in the shot


def test_a_bubble_finds_room_between_close_faces(tmp_path):
    from kinodraw.engine.storybook import Shot
    book = staged(tmp_path, 'Sam talked to Ada.', []).storybook
    sam = Figure('sam', 'human', 'teen', 'male', pose='stand', x=.412, ground=.8, height=.39, facing='l')
    ada = Figure('ada', 'human', 'adult', 'female', pose='sit', x=.183, ground=.711, height=.42, facing='r')
    page = Shot(0., 3., figures=[sam, ada], view=(.292, .58, 1.9))
    text = "It's just a bunch of random stuff."
    bubble = Bubble('sam', text, .2, 2.5, times=tuple(.2 + .05 * i for i in range(len(text))))
    plan = book._bubble_plan(page, bubble)
    assert plan is not None
    x0, y0, x1, y1 = plan[1]
    for a, b, c, d in book.faces(page):
        assert min(x1, c) <= max(x0, a) or min(y1, d) <= max(y0, b)


# ------------------------------------------------------------------ a car, its phone and its map
CAR = [{'id': 'mia', 'name': 'Mia', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'female'},
       {'id': 'sam', 'name': 'Sam', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male'},
       {'id': 'cow', 'name': 'cow', 'kind': 'animal', 'species': 'cow', 'age': 'adult', 'sex': None}]
CAR_TEXT = ('The car had been quiet for miles.\n\n"We passed it."\n\n"We did not pass it," Sam said.\n\n'
            '"There was a cow."\n\n"Cows don\'t wear hats."\n\n"No bars. Check yours."\n\n'
            '"There is a map in the glove box."\n\nShe unfolded it across the dashboard.\n\n'
            'He pulled over by a field and nothing else.')


def car_shots():
    two = [('mia', 'adult', 'look', 'no'), ('sam', 'adult', 'look', 'no')]
    talk = lambda who: [(c, a, 'talk' if c == who else 'look', 'yes' if c == who else 'no') for c, a, _, _ in two]
    return [shot('b001', 'The car', 'wide', two, place='car', set_refs=['fl_motorway']),
            shot('b002', 'We passed', 'two_shot', talk('mia'), place='car', lines=[('We passed it.', 'mia')]),
            shot('b003', 'We did not', 'two_shot', talk('sam'), place='car', lines=[('We did not pass it,', 'sam')]),
            shot('b004', 'There was', 'medium', [('sam', 'adult', 'point', 'yes')], place='car',   # the plan's slip
                 lines=[('There was a cow.', 'sam')]),
            shot('b005', 'Cows', 'two_shot', talk('mia'), place='car', lines=[("Cows don't wear hats.", 'mia')]),
            shot('b006', 'No bars', 'two_shot', talk('mia'), place='car', focus='fl_antenna_bars',
                 lines=[('No bars. Check yours.', 'mia')]),
            shot('b007', 'There is a map', 'two_shot', talk('mia'), place='car', focus='map_route',
                 props=[prop('map_route', 'held_by', 'mia')], lines=[('There is a map in the glove box.', 'mia')]),
            shot('b008', 'She unfolded', 'insert', two, place='car'),
            shot('b009', 'He pulled', 'wide', [('mia', 'adult', 'sit', 'no'), ('sam', 'adult', 'look', 'no')],
                 place='field')]


def test_people_in_a_car_sit_inside_it_and_pulled_over_they_are_still_in_it(tmp_path):
    prod = staged(tmp_path, CAR_TEXT, car_shots(), cast=CAR)
    _, (wide,) = pages(prod, 'b001')
    assert wide.place == 'car_inside' and {f.pose for f in wide.figures} == {'sit'}
    seats = [s for s in wide.supports if s.doodle == 'set_car_seat']
    assert all(any(s.x0 <= f.x <= s.x1 and abs(f.ground - s.y) < 1e-6 for s in seats) for f in wide.figures)
    for f in wide.figures:                                                 # one each, in the middle of the seat
        seat = next(s for s in seats if s.x0 <= f.x <= s.x1)
        assert abs(f.x - (seat.x0 + seat.x1) / 2) < .03
    assert 'fl_motorway' not in [p.doodle for p in wide.set]              # the road is the place, not a picture
    assert any(p.front and p.doodle == 'set_dashboard' for p in wide.set)
    _, (field,) = pages(prod, 'b009')
    assert not field.figures and 'fl_automobile' in [p.doodle for p in field.set]


def test_turns_alternate_between_the_two_talking_and_the_shot_shows_who_speaks(tmp_path):
    prod = staged(tmp_path, CAR_TEXT, car_shots(), cast=CAR)
    said = {r['beat']: r['speaker'] for r in prod.storybook.bubbled}
    assert [said.get(b) for b in ('b002', 'b003', 'b004', 'b005')] == ['mia', 'sam', 'mia', 'sam']
    _, (single,) = pages(prod, 'b004')
    assert keys(single) == ['mia'] and [b.speaker for b in single.bubbles] == ['mia']


def test_a_phone_with_no_signal_and_the_map_she_unfolds_fill_the_frame(tmp_path):
    prod = staged(tmp_path, CAR_TEXT, car_shots(), cast=CAR)
    _, (phone,) = pages(prod, 'b006')
    assert phone.page['kind'] == 'phone' and phone.page['signal'] == 'none' and not phone.bubbles
    assert 'b006' not in [r['beat'] for r in prod.storybook.bubbled]     # the caption carries the line
    _, (unfolded,) = pages(prod, 'b008')
    assert unfolded.page['kind'] == 'map'


# ------------------------------------------------------------------ who gets the bed, and where a placeless shot is
def test_the_person_the_text_puts_in_bed_gets_the_bed_and_keeps_it(tmp_path):
    from kinodraw.engine.sets import settles
    assert settles('Nana was sitting up in bed, tired.') == ('sit', 9)          # no "the" needed: "in bed"
    assert settles('Dad lay in bed all morning.')[0] == 'lie'
    both = lambda: [('mia', 'young', 'sit', 'no'), ('ada', 'old', 'sit', 'no')]  # the plan lists Mia first
    prod = staged(tmp_path, 'Years later, Mia came to the hospital. Ada was sitting up in bed, tired, with a phone on '
                            'her blanket.\n\n"You came," Ada said.\n\nMia held her hand for a long time.',
                  [shot('b001', 'Years later', 'wide', both(), place='hospital', set_refs=['fl_bed']),
                   shot('b001', 'Ada was', 'medium', both(), place='hospital', set_refs=['fl_bed']),
                   shot('b002', 'You came', 'two_shot', [('ada', 'old', 'talk', 'yes'), ('mia', 'young', 'sit', 'no')],
                        place='hospital', set_refs=['fl_bed'], lines=[('You came,', 'ada')]),
                   shot('b003', 'Mia held', 'wide', both(), place='hospital', set_refs=['fl_bed'])])
    _, story = pages(prod, 'b001')
    assert len(story) == 2                                                # before the words name her, too
    for page in story + [pages(prod, 'b002')[1][0], pages(prod, 'b003')[1][0]]:
        bid = page.framing
        bed = next(s for s in page.supports if s.kind == 'bed')
        on = {f.key: bed.x0 <= f.x <= bed.x1 and abs(f.ground - bed.y) < 1e-6 for f in page.figures}
        assert on == {'ada': True, 'mia': False}, (bid, on)


def test_a_pronoun_never_hands_the_bed_to_the_wrong_person(tmp_path):
    both = [('mia', 'young', 'sit', 'no'), ('ada', 'old', 'sit', 'no')]
    prod = staged(tmp_path, 'Ada smiled at Mia. She was sitting in bed.',
                  [shot('b001', 'Ada smiled', 'wide', both, place='hospital', set_refs=['fl_bed'])])
    _, (page,) = pages(prod, 'b001')
    bed = next(s for s in page.supports if s.kind == 'bed')
    # "She" could be either: nobody is chosen by the pronoun, so the plan's order stands (Mia first)
    assert [f.key for f in page.figures if bed.x0 <= f.x <= bed.x1 and abs(f.ground - bed.y) < 1e-6] == ['mia']


def test_a_shot_with_no_place_does_not_borrow_a_set_its_people_were_never_in(tmp_path):
    text = ('Ada made tea in the kitchen.\n\nMia rode the bus to school.\n\n'
            'Ada never forgot to send it.\n\nMia read it on the bus.\n\nShe smiled.')
    prod = staged(tmp_path, text, [
        shot('b001', 'Ada made', 'wide', [('ada', 'old', 'stand', 'no')], place='kitchen'),
        shot('b002', 'Mia rode', 'wide', [('mia', 'young', 'sit', 'no')], place='bus'),
        shot('b003', 'Ada never', 'close', [('ada', 'old', 'look', 'no')], place='none', focus='fl_mobile_phone'),
        shot('b004', 'Mia read', 'wide', [('mia', 'young', 'sit', 'no')], place='bus'),
        shot('b005', 'She smiled', 'close', [('mia', 'young', 'look', 'no')], place='none')])
    _, (ada,) = pages(prod, 'b003')
    assert ada.place == 'kitchen'                                         # where Ada was last seen, not the bus
    _, (mia,) = pages(prod, 'b005')
    assert mia.place == 'bus'                                             # the same person goes on: the set stays
    cast = PEOPLE + [{'id': 'kim', 'name': 'Kim', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'female'}]
    prod = staged(tmp_path, 'Mia rode the bus to school.\n\nKim never forgot.', [
        shot('b001', 'Mia rode', 'wide', [('mia', 'young', 'sit', 'no')], place='bus'),
        shot('b002', 'Kim never', 'close', [('kim', 'adult', 'look', 'no')], place='none')], cast=cast)
    _, (kim,) = pages(prod, 'b002')
    assert kim.place is None and not [p for p in kim.set if p.kind != 'strip']   # never seen anywhere: a plain page


def test_a_seat_somewhere_else_does_not_put_someone_first_in_line_for_the_bed(tmp_path):
    prod = staged(tmp_path, 'Mia sat on the bus.\n\nYears later, Mia came to the hospital. Ada was sitting up in bed.',
                  [shot('b001', 'Mia sat', 'wide', [('mia', 'young', 'sit', 'no')], place='bus'),
                   shot('b002', 'Years later', 'wide', [('mia', 'young', 'sit', 'no'), ('ada', 'old', 'sit', 'no')],
                        place='hospital', set_refs=['fl_bed'])])
    _, (page,) = pages(prod, 'b002')
    bed = next(s for s in page.supports if s.kind == 'bed')
    assert [f.key for f in page.figures if bed.x0 <= f.x <= bed.x1 and abs(f.ground - bed.y) < 1e-6] == ['ada']

"""Reference-video techniques in the offline v3 explainer path (Papermorph, Hovercast, What's the Point).

Each check builds a real starter/fixture project through the rules director, the v3 adapter and the hybrid
renderer, on the synthetic narration clock, and reads the plan, the motion scene and rendered pixels.
"""
import math
from pathlib import Path

import numpy as np
from PIL import ImageColor
import pytest

from kinodraw import pipeline
from kinodraw.director.v3.semantics import beats
from kinodraw.engine import render, timeline
from kinodraw.project_store import ProjectStore

GENRE = Path(__file__).parent / 'fixtures' / 'genre'


def project(tmp_path, script, story=None):
    root = tmp_path / 'project'
    pipeline.new_project(Path(script), root, direction={'story': story} if story else None)
    store = ProjectStore(root)
    state = store.load()
    state['settings']['director_v3'] = True
    store.save(state['storyboard'], state['settings'], state['revision'], 'v3')
    pipeline.direct_v3(root)
    state = store.load()
    board, cfg = state['storyboard'], state['settings']
    tl = timeline.layout(board, cfg['lang'], timeline.synthetic_clips(board, cfg['lang']))
    return board, cfg['plan_v3'], tl, render.make_production(board, tl, cfg['lang'], root)


def spoken_time(tl, board, bid, word):
    spoken = next(b for b in beats(board) if b['id'] == bid)['spoken']
    timing = tl['beats'][bid]
    return timing['start'] + timing['char_times'][spoken.index(word)]


def span_of(prod, bid):
    return next(s for s in prod.spans if bid in s.spec['beat_ids'])


@pytest.fixture(scope='module')
def launch(tmp_path_factory):
    return project(tmp_path_factory.mktemp('launch'), GENRE / 'launch.md')


# ------------------------------------------------------------ 1. Papermorph: build clause by clause
def test_pictures_enter_on_their_spoken_words_in_fixed_slots(launch):
    board, plan, tl, prod = launch
    bid = next(b['id'] for b in beats(board) if b['text'].startswith('Introducing our new app'))
    span = span_of(prod, bid)
    pictures = [e for e in span.motion.elements if e.kind == 'picture']
    assert len(pictures) == 2
    app, ideas = (spoken_time(tl, board, bid, w) - span.start for w in ('app', 'ideas'))
    assert [round(e.start, 3) for e in pictures] == [round(app, 3), round(ideas, 3)]
    # Fixed, separate slots in spoken order: the second picture never covers or moves the first.
    assert pictures[0].x is not None and pictures[1].x - pictures[0].x > .2
    assert abs(pictures[0].width - pictures[1].width) < 1e-9
    # Before "ideas" is said, the right slot is empty; once it is said, the lightbulb is drawn there.
    w, h = prod.size
    right = (slice(round(h * .4), round(h * .8)), slice(round(w * pictures[1].x - 150), round(w * pictures[1].x + 150)))
    before = np.asarray(prod.frame(span.start + ideas - .2))[right].astype(int)
    after = np.asarray(prod.frame(span.start + ideas + .8))[right].astype(int)
    assert np.abs(after - before).mean() > 8


def test_kinetic_headline_builds_one_clause_at_a_time_with_the_voice(launch):
    board, plan, tl, prod = launch
    bid = next(b['id'] for b in beats(board) if b['text'].startswith('Part 1: Introducing'))
    span = span_of(prod, bid)
    headline = next(e for e in span.motion.elements if e.kind == 'text' and e.preset != 'corner_caption')
    assert headline.preset == 'clauses'
    assert len(headline.cues) == 3                        # "Part 1:" / "Introducing our new app:" / "one workspace ..."
    assert headline.cues[0] == pytest.approx(0, abs=.05)
    assert headline.cues[1] == pytest.approx(spoken_time(tl, board, bid, 'Introducing') - span.start, abs=.05)
    assert headline.cues[2] == pytest.approx(spoken_time(tl, board, bid, 'one workspace') - span.start, abs=.05)


def test_clause_preset_reveals_in_place_without_reflow():
    from kinodraw.engine.bold import MotionElement, MotionScene, render_frame
    text = 'Part 1: one workspace for ideas.'
    scene = MotionScene([MotionElement(text=text, preset='clauses', cues=(0., 2.), size=96, width=1500)],
                        duration=4, motion_floor=0, palette={'background': '#000000', 'foreground': '#ffffff'})
    early, late = (render_frame(scene, t, 960, 540).astype(int).sum(axis=2) for t in (1.5, 3.5))
    ink = lambda a: np.flatnonzero((a > 300).any(axis=0))
    first, full = ink(early), ink(late)
    assert len(first) and len(full)
    assert full[-1] - first[-1] > 150                     # the second clause appears only at its cue
    assert abs(full[0] - first[0]) <= 1                   # the first clause keeps its place: no reflow


# ------------------------------------------------------------ 2. Hovercast: problem, product, proof, call to action
@pytest.fixture(scope='module')
def news(tmp_path_factory):
    return project(tmp_path_factory.mktemp('news'), GENRE / 'news.md')


def scene_for(plan, board, prefix):
    bid = next(b['id'] for b in beats(board) if b['text'].startswith(prefix))
    return bid, next(s for s in plan['scenes'] if bid in s['beat_ids'])


def test_launch_arc_reads_a_real_promo_proof_and_ask():
    from kinodraw.director.v3.arc import cta_phrase, proof_number
    from kinodraw.director.v3.rules import detect_genre
    # "Meet KinoDraw." reveals a product and "Download it for free." asks: a launch, though it mentions lessons.
    assert detect_genre((Path(__file__).parent / 'fixtures' / 'promo_kinodraw.md').read_text()) == 'launch/promo'
    assert proof_number('Part 2: These figures describe the measured trips.') is None
    proof = proof_number('Bus trips rose from 20 percent to 25 percent this quarter.')
    assert (proof['from'], proof['to'], proof['suffix']) == (20, 25, '%')
    text = 'Start your next project today. Sign up and try it with your team.'
    a, b = cta_phrase(text)
    assert text[a:b] == 'Sign up'


def test_rules_give_spoken_quantities_counters_and_the_ask_a_button(news, launch):
    from kinodraw.director.v3.arc import proof_number
    board, plan, tl, prod = news
    texts = {b['id']: b['text'] for b in beats(board)}
    counters = [s for s in plan['scenes'] if s['text']['kind'] == 'counter']
    assert counters and all(proof_number(texts[s['text']['ref']]) for s in counters)
    _, part = scene_for(plan, board, 'Part 2: These figures')
    assert part['treatment'] != 'chart' and part['text']['kind'] != 'counter'      # "Part 2" is not a quantity
    board, plan, tl, prod = launch
    _, ask = scene_for(plan, board, 'Start your next project today. Sign up')
    assert ask['text']['kind'] == 'cta'


def test_validation_turns_unsupported_counters_and_buttons_into_kinetic_text(launch):
    import copy
    from kinodraw.director.v3.validate import validate
    from kinodraw.director.validate import _doodles
    board, plan, tl, prod = launch
    plan = copy.deepcopy(plan)
    _, plain = scene_for(plan, board, 'Introducing our new app')
    _, ask = scene_for(plan, board, 'Start your next project today. Sign up')
    plain['text'] = {'kind': 'counter', 'ref': plain['beat_ids'][0]}
    ask['text']['kind'] = 'cta'
    title = plan['scenes'][0]
    title['text'] = {'kind': 'cta', 'ref': title['beat_ids'][0]}
    candidates = {b['id']: list(_doodles(b['visuals'])) for b in board['beats']}
    fixed, repairs = validate(plan, board, candidates)
    by = {s['beat_ids'][0]: s for s in fixed['scenes']}
    assert by[plain['beat_ids'][0]]['text']['kind'] == 'kinetic'
    assert by[title['beat_ids'][0]]['text']['kind'] == 'kinetic'
    assert by[ask['beat_ids'][0]]['text']['kind'] == 'cta'
    assert sum('counter needs a spoken quantity' in r for r in repairs) == 1
    assert sum('call to action needs' in r for r in repairs) == 1


def test_proof_counter_rolls_ease_out_from_a_to_b_and_lands_on_a_beat_with_a_hit(news):
    board, plan, tl, prod = news
    bid, _ = scene_for(plan, board, 'Key takeaway: The report shows')
    span = span_of(prod, bid)
    counter = next(e for e in span.motion.elements if e.preset == 'counter')
    assert (counter.value_from, counter.value_to, counter.suffix) == (20, 25, '%')
    landing = span.start + counter.start + counter.duration
    assert len(prod.score_beats) and np.min(np.abs(prod.score_beats - landing)) < 1e-6
    from kinodraw.engine.bold.charts import counter_value
    third = counter.start + counter.duration / 3
    assert counter_value(counter, third) > 20 + 5 * .5                       # ease-out: most of the roll early
    assert counter.start == pytest.approx(spoken_time(tl, board, bid, 'twenty') - span.start, abs=.15)
    hit = next(c for c in prod.cues() if c['kind'] == 'pop' and abs(c['t'] - landing) < 1e-6)
    assert 0 < hit['strength'] < 1
    # The landing draws a burst around the number that is not there just before it.
    w, h = prod.size
    box = (slice(round(h * .35), round(h * .8)), slice(round(w * .2), round(w * .8)))
    before = np.asarray(prod.frame(landing - .05))[box].astype(int)
    after = np.asarray(prod.frame(landing + .12))[box].astype(int)
    assert np.abs(after - before).mean() > 2


def test_call_to_action_button_is_pressed_on_a_beat(launch):
    board, plan, tl, prod = launch
    bid, _ = scene_for(plan, board, 'Start your next project today. Sign up')
    span = span_of(prod, bid)
    button = next(e for e in span.motion.elements if e.kind == 'button')
    assert button.text == 'Sign up'
    assert button.start == pytest.approx(spoken_time(tl, board, bid, 'Sign up') - span.start, abs=.05)
    press = span.start + button.cues[0]
    assert button.cues[0] > button.start and np.min(np.abs(prod.score_beats - press)) < 1e-6
    assert any(c['kind'] == 'tap' and abs(c['t'] - press) < 1e-6 for c in prod.cues())
    accent = np.array(ImageColor.getrgb(plan['style']['palette']['accent']))
    frame = np.asarray(prod.frame(press + .3)).astype(int)
    w, h = prod.size
    pill = frame[round(h * .5):round(h * .82), round(w * .35):round(w * .65)]
    assert (np.abs(pill - accent).sum(axis=2) < 60).mean() > .08          # an accent pill holds the label


# ------------------------------------------------------------ 3. What's the Point: one recurring anchor point
def test_anchor_point_rests_over_what_the_narration_names(launch, news):
    board, plan, tl, prod = launch
    bid = next(b['id'] for b in beats(board) if b['text'].startswith('Introducing our new app'))
    span = span_of(prod, bid)
    from kinodraw.engine.bold.render import H, W, layout_position
    pictures = [(j, e) for j, e in enumerate(span.motion.elements) if e.kind == 'picture']
    w, h = prod.size
    for (j, picture), word in zip(pictures, ('app', 'ideas')):
        at = spoken_time(tl, board, bid, word) + .6
        anchor = prod._anchor(at)
        x, y = layout_position(span.motion, picture, j)
        assert anchor['alpha'] == pytest.approx(1)
        assert abs(anchor['x'] - x * w / W) < .04 * w                    # over the picture just named
        assert anchor['y'] < (y - picture.height / 2) * h / H             # just above it
        assert anchor['bar'] < .05 and anchor['ring'] < .05               # as a dot
    # A headline takes an accent rule above it; a proof number takes a ring.
    board, plan, tl, prod = news
    bid, _ = scene_for(plan, board, 'Key takeaway: The report shows')
    span = span_of(prod, bid)
    headline = next(e for e in span.motion.elements if e.preset == 'clauses')
    counter = next(e for e in span.motion.elements if e.preset == 'counter')
    assert prod._anchor(span.start + headline.start + .6)['bar'] == pytest.approx(1)
    ring = prod._anchor(span.start + counter.start + .6)
    assert ring['ring'] == pytest.approx(1) and ring['y'] < counter.y * prod.size[1]       # over the number


def test_anchor_glides_across_scene_joins_without_a_jump(launch):
    board, plan, tl, prod = launch
    w, h = prod.size
    joins = [s for i, s in enumerate(prod.spans[1:], 1) if s.spec['transition_in'] != 'cut'
             and prod._anchored(s) and prod._anchored(prod.spans[i - 1])]
    assert joins
    moved = 0.
    for span in joins:
        times = np.arange(span.start - .3, span.join + 1.2, 1 / 30)
        points = [prod._anchor(t) for t in times]
        assert all(p is not None and p['alpha'] == pytest.approx(1) for p in points)   # it persists, never re-enters
        steps = [math.hypot(b['x'] - a['x'], b['y'] - a['y']) for a, b in zip(points, points[1:])]
        assert max(steps) < .035 * w                                                # glides, never jumps
        moved = max(moved, math.hypot(points[-1]['x'] - points[0]['x'], points[-1]['y'] - points[0]['y']))
    assert moved > .02 * w


def test_anchor_holds_the_centre_until_a_scene_brings_something_in(launch):
    from kinodraw.engine.hybrid import ANCHOR_GLIDE
    board, plan, tl, prod = launch
    bid = next(b['id'] for b in beats(board) if b['text'].startswith('Introducing our new app'))
    span = span_of(prod, bid)
    at = span.join + ANCHOR_GLIDE + .1
    assert min(e.start for e in span.motion.elements if e.kind == 'picture') > at - span.start
    anchor = prod._anchor(at)
    w, h = prod.size
    assert abs(anchor['x'] - w / 2) < .03 * w and abs(anchor['y'] - h / 2) < .05 * h   # the lone point
    x, y = round(anchor['x']), round(anchor['y'])
    accent = np.array(ImageColor.getrgb(plan['style']['palette']['accent']))
    patch = np.asarray(prod.frame(at)).astype(int)[y - 6:y + 7, x - 6:x + 7]
    assert (np.abs(patch - accent).sum(axis=2) < 90).mean() > .3


def test_anchor_never_touches_whiteboard_scenes(tmp_path):
    board, plan, tl, prod = project(tmp_path, GENRE / 'explainer.md')
    boards = [s for s in prod.spans if s.spec['treatment'] == 'whiteboard']
    kinetic = [s for s in prod.spans if s.spec['treatment'] == 'kinetic_type']
    assert boards and kinetic
    for span in boards:
        for t in np.linspace(span.start, span.end - .05, 5):
            assert prod._anchor(t) is None
    assert prod._anchor(prod.starts[0] - .5) is None if prod.starts[0] > .5 else True
    assert any(prod._anchor((s.join + s.end) / 2) is not None for s in kinetic)


def test_rules_never_leave_a_motion_scene_empty(launch, news):
    # An empty motion scene is a still frame behind its caption (4.7 s frozen in the launch fixture): its own
    # words build clause by clause instead, under the anchor point.
    for board, plan, tl, prod in (launch, news):
        for scene in plan['scenes']:
            if scene['treatment'] == 'motion':
                assert scene['elements'] or scene['actions'], scene['beat_ids']
    board, plan, tl, prod = launch
    bid, scene = scene_for(plan, board, "Here's what we'll cover")
    assert (scene['treatment'], scene['text']['kind']) == ('kinetic_type', 'kinetic')
    assert any(e.preset == 'clauses' for e in span_of(prod, bid).motion.elements)

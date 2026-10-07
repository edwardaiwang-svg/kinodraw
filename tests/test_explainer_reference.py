"""Reference-video techniques in the offline v3 explainer path (Papermorph, Hovercast, What's the Point).

Each check builds a real starter/fixture project through the rules director, the v3 adapter and the hybrid
renderer, on the synthetic narration clock, and reads the plan, the motion scene and rendered pixels.
"""
from pathlib import Path

import numpy as np
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

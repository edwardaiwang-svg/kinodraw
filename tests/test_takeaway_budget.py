"""Targeted preparation buys actual drawing time without lengthening every take."""
from pathlib import Path

import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.engine import render, timeline
from kinodraw.engine.board import Camera, Element, Scheduler


def test_compressed_measurement_keeps_the_unfinished_dependency_at_two_times():
    class Drawing:
        duration = 2.
        size = (100, 100)
    parent = Element(Drawing(), 100, 100, 0., essential=True, deadline=.5, catch_up=True)
    child = Element(Drawing(), 250, 100, .01, after=parent, optional=True, deadline=.8,
                    catch_up=True)
    Scheduler(Camera()).run([parent, child], [(0., 0., 'cut')], measure=True)
    assert not parent.skipped and not child.skipped
    assert parent.rate == child.rate == 2.
    assert child.start >= parent.end
    assert child.end > child.deadline  # report the deficit; do not hide it by speeding or dropping


def test_only_explicit_takeaway_preparation_changes_the_speech_clock():
    board = RulesDirector('en').direct(script.build(ingest.read(Path(__file__).parent / 'fixtures/tiny.md')))
    clips = timeline.synthetic_clips(board, 'en')
    original = timeline.layout(board, 'en', clips)
    assert timeline.layout(board, 'en', clips, timeline.Pacing()) == original
    bid = original['transitions'][0]['take_beat']
    pauses = timeline.Pacing()
    pauses[bid] = .08
    pauses.takeaways[bid] = .23
    actual = timeline.layout(board, 'en', clips, pauses)
    assert actual['beats'][bid]['start'] - original['beats'][bid]['start'] == pytest.approx(.23)
    assert actual['beats'][bid]['prep'] == original['beats'][bid]['prep']
    assert actual['pauses'][bid] == .08
    assert actual['beats'][bid]['takeaway_delay'] == .23
    assert all('takeaway_delay' not in bt for key, bt in actual['beats'].items() if key != bid)


def test_deficient_takes_use_a_measured_budget_and_real_two_times_strokes(tmp_path):
    board = RulesDirector('en').direct(script.build(ingest.read(Path(__file__).parent / 'fixtures/printing_press.md')))
    clips = timeline.synthetic_clips(board, 'en')
    pauses = render.pacing(board, 'en', clips, tmp_path)
    timing = timeline.layout(board, 'en', clips, pauses)
    prod = render.Production(board, timing, 'en', tmp_path)
    first = timing['transitions'][0]['take_beat']
    assert first not in pauses.takeaways  # this long take fits after correcting parent reservation
    assert pauses.takeaways
    assert not any(e.skipped for e in prod.ctx.elements)
    for tr in timing['transitions']:
        elements = [e for e in prod.ctx.elements if e.beat == tr['take_beat'] and not e.fixed]
        assert all(e.rate <= 2. + 1e-6 for e in elements)
        assert max(e.end for e in elements) <= tr['hold_end'] - render.NOTE_READ + 1e-6
        if tr['take_beat'] in pauses.takeaways:
            face = prod.notes[tr['section']]['els'][3]
            assert face.start < timing['beats'][tr['take_beat']]['start']
            assert face.after is prod.notes[tr['section']]['els'][0]
    order = timing['beat_order']
    assert max(timing['beats'][b]['start'] - timing['beats'][a]['speech_end']
               for a, b in zip(order, order[1:])) < 1.

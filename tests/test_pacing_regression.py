"""A note's dependent face and pictures share its real two-times drawing budget."""
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageChops

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.engine import render, timeline
from kinodraw.engine.board import Camera, Element, Scheduler
from test_render_rules import SKY


class Drawing:
    duration = 2.
    size = (100, 100)


def test_dependent_units_reserve_time_before_their_parent_finishes():
    parent = Element(Drawing(), 100, 100, 0., essential=True, deadline=3.3)
    face = Element(Drawing(), 250, 100, .01, after=parent, optional=True, deadline=4.)
    margin = Element(Drawing(), 400, 100, .01, after=parent, optional=True, deadline=4.)
    Scheduler(Camera()).run([parent, face, margin], [(0., 0., 'cut'), (4.35, 1920., 'cut')])
    assert all(not e.skipped and e.start is not None for e in (parent, face, margin))
    assert face.start >= parent.end and margin.start >= face.end
    assert max(face.end, margin.end) <= 4.
    assert face.rate <= 2. and margin.rate <= 2.


@pytest.mark.parametrize('source,speed', [('printing_press', 1.), ('sky', .82)])
def test_source_faces_are_composited_before_pin_without_added_dead_time(tmp_path, source, speed):
    text = Path(__file__).parent / 'fixtures' / 'printing_press.md' if source == 'printing_press' else SKY
    board = RulesDirector('en').direct(script.build(ingest.read(text)))
    clips = timeline.synthetic_clips(board, 'en')
    for clip in clips.values():
        clip['speech'] *= speed
        clip['char_times'] = [t * speed for t in clip['char_times']]
    pauses = render.pacing(board, 'en', clips, tmp_path)
    timing = timeline.layout(board, 'en', clips, pauses)
    prod = render.Production(board, timing, 'en', tmp_path)
    assert render.PAUSE_MAX == .1
    assert all(0 < pause <= .1 for pause in pauses.values())
    assert not {e.group for e in prod.ctx.elements if e.skipped}
    order = timing['beat_order']
    assert max(timing['beats'][b]['start'] - timing['beats'][a]['speech_end']
               for a, b in zip(order, order[1:])) < 1.
    for tr in timing['transitions']:
        face = prod.notes[tr['section']]['els'][3]
        at = tr['hold_end'] - .01
        assert face.end <= at
        assert face.rate <= 2.
        visible = prod.frame(at)
        original = face.hidden_after
        face.hidden_after = 0.
        without_face = prod.frame(at)
        face.hidden_after = original
        assert np.asarray(ImageChops.difference(visible.convert('RGB'), without_face.convert('RGB'))).max() > 0

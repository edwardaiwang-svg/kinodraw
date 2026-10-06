"""Supplementary source writing must preserve narration work and saved motion policy."""
import copy
import json

import numpy as np
import pytest

from kinodraw import ingest, script
from kinodraw.engine import auto_scenes, ink, render, timeline
from test_hybrid import fixture


@pytest.mark.parametrize('look', ['whiteboard', 'mosaic'])
def test_agenda_hook_uses_spare_hand_time_without_changing_primary_work(tmp_path, monkeypatch, look):
    facts = ['Seeds need water.', 'Leaves catch sunlight.']
    board = script.build(ingest.Document('A garden', 'en', [], [
        ingest.Section('Water', [facts[0]]), ingest.Section('Sunlight', [facts[1]])]))
    board['look'] = look
    # Narrated agenda time supplies real spare hand budget; the hooks remain
    # source excerpts, not additional speech or pauses on the master clock.
    for beat in board['beats']:
        if beat['kind'] == 'agenda':
            text = beat['spoken']['en'] + ' We will look at this part of the garden and see how it grows.'
            beat['spoken']['en'] = beat['display']['en'] = text
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    before_board, before_timing = copy.deepcopy(board), copy.deepcopy(timing)
    agenda = auto_scenes.SCENES['landscape']['agenda']

    def primary_only(ctx, chapters, beats, x0):
        chapters = copy.deepcopy(chapters)
        for chapter in chapters:
            chapter.pop('hook', None)
        return agenda(ctx, chapters, beats, x0)

    with monkeypatch.context() as patch:
        patch.setitem(auto_scenes.SCENES['landscape'], 'agenda', primary_only)
        baseline = render.Production(board, timing, 'en', tmp_path)
    actual = render.Production(board, timing, 'en', tmp_path)
    hooks = [e for card in actual.cards.values() for e in card['els']
             if isinstance(e.drawing, ink.TextDrawing) and ' '.join(e.drawing.lines) in facts]
    assert len(hooks) == 2

    def primary(prod):
        return [(e.bbox(), getattr(e.drawing, 'lines', None), e.trigger, e.start, e.end, e.rate, e.skipped)
                for e in prod.ctx.elements if e.group == 'agenda' and e not in hooks]

    assert primary(actual) == primary(baseline)
    assert actual.camera.keys == baseline.camera.keys
    assert board == before_board and timing == before_timing
    assert [c['hook']['en'] for c in board['chapters'] if c['kind'] == 'section'] == facts
    assert all(e.start is not None and not e.skipped and e.rate <= 2 for e in hooks)
    hand = sorted(actual.hand_els, key=lambda e: e.start)
    assert all(a.end <= b.start + 1e-8 for a, b in zip(hand, hand[1:]))
    for hook in hooks:
        card = next(c for c in actual.cards.values() if hook in c['els'])
        assert hook.start >= max(e.end for e in card['els'] if e is not hook)
        at = hook.end + .01
        image = actual.frame(at)
        with monkeypatch.context() as patch:
            patch.setattr(actual, 'els', [e for e in actual.els if e is not hook])
            without = actual.frame(at)
        assert np.count_nonzero(np.any(np.asarray(image) != np.asarray(without), axis=2)) > 100


def test_saved_motion_floor_reaches_endcard_but_explicit_hold_keeps_its_phase(tmp_path):
    board, plan, timing = fixture(tmp_path)
    prod = render.make_production(board, timing, 'en', tmp_path)
    whiteboard = prod.whiteboard
    at = timing['end_card']['end'] - .3
    moving = whiteboard._drift(at)
    assert moving != 0
    assert whiteboard.tl == timing and prod.plan == plan

    # An explicit reading hold takes precedence over a nonzero saved floor.
    held_timing = copy.deepcopy(timing)
    held_timing['holds'] = [{'start': at - 1., 'end': at - .5}]
    held = render.make_production(board, held_timing, 'en', tmp_path).whiteboard
    assert held._drift(at - .75) == 0
    assert abs(held._drift(at - 1. - 1e-6)) < .001
    assert abs(held._drift(at - .2 + 1e-6)) < .001
    later = at + .2
    assert held._drift(later) == pytest.approx(whiteboard._drift(later))

    plan['style']['motion_floor'] = 'still'
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    still = render.make_production(board, timing, 'en', tmp_path)
    assert still.whiteboard._drift(at) == 0
    assert render.Production(board, timing, 'en', tmp_path)._drift(at) == 0

"""Source hook candidates are admitted only into actual spare one-hand time."""
import copy
from pathlib import Path

import numpy as np
import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.engine import auto_scenes, ink, render, timeline
from kinodraw.engine.board import Camera, Element, Scheduler
from test_render_rules import SKY


@pytest.mark.parametrize('source,speed', [('printing_press', 1.), ('sky', .82)])
def test_rejected_hooks_remain_source_candidates_with_measured_reasons(tmp_path, monkeypatch, source, speed):
    text = Path(__file__).parent / 'fixtures/printing_press.md' if source == 'printing_press' else SKY
    board = RulesDirector('en').direct(script.build(ingest.read(text)))
    clips = timeline.synthetic_clips(board, 'en')
    for clip in clips.values():
        clip['speech'] *= speed
        clip['char_times'] = [t * speed for t in clip['char_times']]
    timing = timeline.layout(board, 'en', clips, render.pacing(board, 'en', clips, tmp_path))
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
    hooks = [e for card in actual.cards.values() for e in card['hooks']]
    rejected = [e for e in hooks if e.start is None]
    assert rejected
    # A never-admitted candidate must not masquerade as a lost production drawing.
    assert all(not e.skipped for e in rejected)
    assert all(e not in actual.ctx.elements and e not in actual.els for e in rejected)
    assert all(e not in card['els'] for card in actual.cards.values() for e in rejected)
    reasons = [w for w in actual.warnings if 'hook not admitted' in w]
    assert len(reasons) == len(rejected)
    assert all('available=' in w and 'required=' in w and '2x' in w for w in reasons)

    def primary(prod):
        return [(e.bbox(), getattr(e.drawing, 'lines', None), e.trigger, e.start,
                 e.end, e.rate, e.skipped) for e in prod.ctx.elements if e not in hooks]

    assert primary(actual) == primary(baseline)
    assert actual.camera.keys == baseline.camera.keys
    assert board == before_board and timing == before_timing
    assert not any(e.skipped for e in actual.ctx.elements)
    hand = sorted(actual.hand_els, key=lambda e: e.start)
    assert all(a.end <= b.start + 1e-8 for a, b in zip(hand, hand[1:]))
    assert all(e.rate <= 2 + 1e-6 for e in actual.els if not e.fixed and not e.essential)

    # Rejecting the extra agenda copy must preserve source ink at its section opener.
    for chapter in (c for c in board['chapters'] if c['kind'] == 'section'):
        opener = [e for e in actual.els if e.group == f"opener:{chapter['id']}"
                  and isinstance(e.drawing, ink.TextDrawing)]
        source_ink = opener[-1]
        words = ' '.join(source_ink.drawing.lines).rstrip('…')
        assert chapter['hook']['en'].startswith(words)
        at = source_ink.end + .01
        visible = actual.frame(at)
        drift = actual._drift(at)
        with monkeypatch.context() as patch:
            patch.setattr(actual, '_drift', lambda t: drift)
            patch.setattr(actual, 'els', [e for e in actual.els if e is not source_ink])
            without = actual.frame(at)
        assert np.count_nonzero(np.any(np.asarray(visible) != np.asarray(without), axis=2)) > 100


def test_later_free_gap_admits_hook_without_moving_primary_or_camera():
    class Drawing:
        duration = 1.
        size = (100, 100)

    parent = Element(Drawing(), 100, 100, 0., start=0., deadline=5.)
    busy = Element(Drawing(), 250, 100, 1.1, start=1.1)
    hook = Element(Drawing(), 400, 100, 0., after=parent, optional=True, deadline=5.)
    camera = Camera()
    camera.keys.append((5.35, 1920., 'cut'))
    before = [(e.start, e.end, e.rate, e.trigger) for e in (parent, busy)]
    keys = list(camera.keys)
    admitted = Scheduler(camera).supplementary([hook], [parent, busy],
                                              [(0., 0., 'cut'), (5.35, 1920., 'cut')])
    assert admitted == [hook]
    assert hook.start >= busy.end + .15
    assert hook.end <= 5. and not hook.skipped and hook.rate <= 2.
    assert [(e.start, e.end, e.rate, e.trigger) for e in (parent, busy)] == before
    assert camera.keys == keys

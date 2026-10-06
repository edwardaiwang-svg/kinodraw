"""Source pages must not clear completed content long before their first stroke."""
import json
from pathlib import Path

import pytest

from kinodraw.engine import ink, render

SOURCE = Path(__file__).parent / 'fixtures/idle_sources'


@pytest.fixture(scope='module', params=['fraction-en', 'seasons-en', 'sky-zh'])
def source_production(request):
    src = SOURCE / request.param
    board = json.loads((src / 'storyboard.json').read_text())
    timing = json.loads((src / 'build/timeline.json').read_text())
    return render.Production(board, timing, timing['language'], src)


def test_source_completed_board_remains_until_outro_drawing(source_production):
    p = source_production
    outro = next(c for c in p.ep['chapters'] if c['kind'] == 'outro')
    start = next(c['start'] for c in p.tl['chapters'] if c['id'] == outro['id'])
    left = p.pages[outro['id']]
    first = min(e.start for e in p.els if left <= e.x < left + p.size[0])
    at = (start + first - p.g.pan_seconds) / 2
    assert p.camera.at(at) < left
    assert any(e.start <= at and e.x < p.camera.at(at) + p.size[0]
               and e.x + e.w > p.camera.at(at) and e.state(at)[0] is not None
               for e in p.els)


def test_source_outro_strokes_and_one_hand_stay_on_screen(source_production):
    p = source_production
    outro = next(c for c in p.ep['chapters'] if c['kind'] == 'outro')
    left = p.pages[outro['id']]
    elements = [e for e in p.els if left <= e.x < left + p.size[0]]
    for e in elements:
        at = e.start + min(.03, (e.end - e.start) / 2)
        L = p.camera.at(at)
        assert L <= e.x and e.x + e.w <= L + p.size[0]
        if isinstance(e.drawing, ink.TextDrawing):
            assert p.text_visible(e, at, L)
    hands = [e for e in p.els if e.hand]
    assert all(a.end <= b.start + 1e-8 for a, b in zip(hands, hands[1:]))
    keys = sorted(p.camera.keys)
    assert all(a[1] <= b[1] for a, b in zip(keys, keys[1:]))


def test_source_frame_view_dimensions_and_random_access(source_production):
    p = source_production
    at = next(c['start'] for c in p.tl['chapters'] if c['id'] == 'outro') + .4
    L = p.camera.at(at)
    expected = p.view(at, L, hand=False).tobytes()
    assert p.board_frame(at).size == p.size
    assert p.frame(at).size == p.size
    p.frame(at + 1.)
    p.frame(at - 1.)
    assert p.view(at, L, hand=False).tobytes() == expected


def test_source_sentence_words_and_cached_timing_are_preserved(source_production):
    p = source_production
    written = [e for e in p.els if e.group.startswith('source:')]
    assert written
    for e in written:
        _, bid, offset = e.group.split(':')
        beat = next(b for b in p.ep['beats'] if b['id'] == bid)
        sentence = next(s for s in beat['direction'] if s['span'][0] == int(offset))
        a, b = sentence['span']
        expected = beat['spoken'][p.lang][a:b]
        assert ''.join(''.join(e.drawing.lines).split()) == ''.join(expected.split())
        timing = p.tl['beats'][bid]
        assert e.trigger == pytest.approx(timing['start'] + timing['char_times'][a])
        assert e.end <= timing['speech_end'] + 1e-8

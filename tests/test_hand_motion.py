"""The drawing hand slides in from the frame edge before a board's first stroke and out after its last; it can be a
left hand or no hand at all (storyboard "hand")."""
from pathlib import Path

import numpy as np
import pytest

from kinodraw import pipeline
from kinodraw.engine import ink, render as renderer, timeline

FIX = Path(__file__).parent / 'fixtures'


def production(tmp_path, **board):
    folder = tmp_path / ('p-' + '-'.join(f'{k}{v}' for k, v in board.items()))
    story = pipeline.new_project(FIX / 'tiny.md', folder)
    story.update(board)
    tl = timeline.layout(story, 'en', timeline.synthetic_clips(story, 'en'))
    return renderer.make_production(story, tl, 'en', folder)


def sessions(prod):
    """(first, last) hand element of every board session (the hand travels between drawings inside one)."""
    out, first = [], prod.hand_els[0]
    for prev, nxt in zip(prod.hand_els, prod.hand_els[1:]):
        if nxt.start - prev.end > 1.4 and prev.stretch != nxt.stretch:          # a new board
            out.append((first, prev))
            first = nxt
    return out + [(first, prod.hand_els[-1])]


def hand_box(prod, t):
    """The hand's own pixels (not its faint shadow) at t, as (left, top, right, bottom), or None."""
    L = prod.camera.at(t) + prod._drift(t)
    a = np.asarray(prod.view(t, L).convert('RGB'), np.int16)
    b = np.asarray(prod.view(t, L, hand=False).convert('RGB'), np.int16)
    ys, xs = np.nonzero(np.abs(a - b).max(-1) > 60)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else None


def pen_at(prod, e, first=True):
    L = prod.camera.at(e.start) + prod._drift(e.start)
    pen = prod._first_pen(e) if first else prod._last_pen(e)
    return e.x - L + pen[0], e.y + pen[1]


@pytest.fixture(scope='module')
def right(tmp_path_factory):
    return production(tmp_path_factory.mktemp('right'))


def test_the_hand_slides_in_from_the_edge_and_out_again(right):
    prod = right
    W, H = prod.size
    checked = 0
    for first, last in sessions(prod):
        x, y = pen_at(prod, first)
        if not (0 <= x < W and 0 <= y < H) or prod.mode_at(first.start - .45)[0] != 'board':
            continue
        t0, t1 = first.start, last.end
        assert hand_box(prod, t0 - .45) is None and hand_box(prod, t0 - .5) is None           # off-frame
        box = hand_box(prod, t0 - .2)
        assert box is not None and (box[2] == W or box[3] == H), box                          # crossing the edge
        assert not (box[0] <= 0 or box[1] <= 0), box                                          # wrist side only
        seen, at = [], t0 - 1e-4                                                                # as the stroke starts
        prod.hand.paste, paste = (lambda frame, point, lifted=False: seen.append(point)), prod.hand.paste
        try:
            prod._hand(prod.view(at, prod.camera.at(at) + prod._drift(at), hand=False), at,
                       prod.camera.at(at) + prod._drift(at))
        finally:
            prod.hand.paste = paste
        assert np.allclose(seen, [(x, y)], atol=1.5), (seen, (x, y))                            # on the pen point
        assert hand_box(prod, t1 + .1) is not None                                             # on its way out
        assert hand_box(prod, t1 + .35) is None                                                # gone
        checked += 1
    assert checked >= 2


def test_a_left_hand_is_the_right_one_mirrored_about_the_pen(tmp_path, right):
    left = production(tmp_path, hand='left')
    e = next(e for e in right.hand_els if e.drawing.duration > 1 and isinstance(e.drawing, ink.TextDrawing))
    t = e.start + e.drawing.duration * .5
    L = right.camera.at(t) + right._drift(t)
    _, pen, _ = e.state(t)
    px = e.x - L + pen[0]
    a, b = hand_box(right, t), hand_box(left, t)
    assert a is not None and b is not None
    assert abs((2 * px - a[2]) - b[0]) <= 3 and abs((2 * px - a[0]) - b[2]) <= 3, (px, a, b)
    assert abs(a[1] - b[1]) <= 3 and abs(a[3] - b[3]) <= 3
    img = ink.Hand('marker', 'left')
    assert np.array_equal(np.asarray(img.img)[:, ::-1], np.asarray(ink.Hand('marker').img))
    assert img.tip == (img.img.width - ink.Hand('marker').tip[0], ink.Hand('marker').tip[1])


def test_no_hand_draws_without_a_hand(tmp_path, right):
    none = production(tmp_path, hand='none')
    assert none.hand is None
    e = right.hand_els[3]
    for t in (e.start + .1, e.start - .2, e.end + .1):
        assert hand_box(none, t) is None
    assert hand_box(right, e.start + .1) is not None


def test_an_unknown_hand_is_refused(tmp_path):
    from kinodraw.director.validate import validate
    with pytest.raises(ValueError, match='hand must be'):
        production(tmp_path, hand='both')
    report = validate({'lang': 'en', 'chapters': [], 'beats': [], 'hand': 'both'})
    assert not report['ok'] and any('hand must be' in e for e in report['errors'])
    assert validate({'lang': 'en', 'chapters': [], 'beats': [], 'hand': 'left'})['ok']

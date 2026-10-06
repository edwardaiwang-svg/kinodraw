"""Portrait framing supplies one readable caption outside the source board."""
import numpy as np
import pytest

from kinodraw.engine import render
from test_hybrid import fixture


@pytest.mark.parametrize('scene_index', [0, 2])
def test_portrait_hybrid_board_never_draws_an_inner_caption(tmp_path, monkeypatch, scene_index):
    board, plan, tl = fixture(tmp_path)
    portrait = render.make_production(board, tl, 'en', tmp_path, aspect='9:16')
    span = portrait.prod.spans[scene_index]
    caption = next(c for c in tl['captions'] if span.start <= c['start'] < span.end)
    at = (caption['start'] + caption['end']) / 2
    actual = np.asarray(portrait.frame(at))
    monkeypatch.setattr(portrait.prod.whiteboard, '_caption', lambda *args: None)
    expected = np.asarray(portrait.frame(at))
    assert np.array_equal(actual, expected), 'hybrid board drew a second caption inside the portrait'
    assert portrait.caption_at(at) is not None

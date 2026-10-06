"""Idle motion must follow visible activity and return to authorial coordinates."""
from types import SimpleNamespace

import pytest
from PIL import Image

from kinodraw.engine import ink, render, skin
from kinodraw.engine.board import Camera, Element, Layout


def production(elements=(), timeline=None):
    p = object.__new__(render.Production)
    p.skin, p.g, p.camera = skin.for_look('whiteboard'), Layout().g, Camera()
    p.els = list(elements)
    p.hand_els = [e for e in elements if e.hand]
    p.hand_starts = [e.start for e in p.hand_els]
    p.tl, p.modes = timeline or {}, []
    p.ctx = SimpleNamespace(registry={})
    return p


def photo(start, x=200, y=200):
    return Element(ink.StaticDrawing(Image.new('RGBA', (100, 100), 'black')),
                   x, y, start, start=start)


def test_missing_pen_endpoints_do_not_reserve_a_hand_trip():
    p = production([photo(0), photo(5, x=800)])
    assert p._first_pen(p.els[1]) is None
    assert p._last_pen(p.els[0]) is None
    assert p._drift(2) != 0


def test_offscreen_drawing_does_not_freeze_visible_board():
    p = production([photo(2, y=1200)])
    assert p._drift(2.1) != 0


@pytest.mark.parametrize('timing', [
    {'holds': [{'start': 2., 'end': 4.}]},
    {'end_card': {'start': 2., 'end': 4.}},
    {'transitions': [{'speech_end': 2., 'hold_end': 4.}]},
    {'beats': {'b': {'speech_end': 2.}}, 'pauses': {'b': 2.}},
])
def test_authorial_holds_and_their_boundaries_remain_still(timing):
    p = production(timeline=timing)
    for t in (2., 2.5, 3.9, 4., 4.3):
        assert p._drift(t) == 0
    assert abs(p._drift(2.-1e-6)) < .001
    assert abs(p._drift(4.3+1e-6)) < .001


def test_drawing_and_settle_endpoints_are_exact_and_order_independent():
    p = production([photo(0), photo(4)])
    times = [0., .1, .35, .5, p.els[0].end + .3, 4., 4.1, 4.35, p.els[1].end + .3]
    assert [p._drift(t) for t in times] == [0.] * len(times)
    idle = [1., 1.7, 2.3, 3.5]
    forward = [p._drift(t) for t in idle]
    assert forward == list(reversed([p._drift(t) for t in reversed(idle)]))
    assert abs(p._drift(4.-1e-6)) < .001


def test_a_real_visible_hand_trip_still_owns_motion():
    drawing = ink.stroke_drawing((100, 100), [[(10, 10), (80, 80)]])
    a = Element(drawing, 200, 200, 0, start=0)
    b = Element(drawing, 700, 200, 5, start=5)
    p = production([a, b])
    assert p._first_pen(b) is not None and p._last_pen(a) is not None
    assert p._drift((a.end+b.start)/2) == 0


def test_locked_material_camera_does_not_gain_drift():
    p = production()
    p.camera.locked = True
    assert all(p._drift(t) == 0 for t in (0., 1., 2., 20.))

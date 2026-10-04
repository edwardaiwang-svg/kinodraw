"""Material boards stay fixed; only cuts and cell-aligned wipes change boards."""
import bisect
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw import pipeline
from kinodraw.engine import board, ink, render as renderer, skin as skins, timeline

FIX = Path(__file__).parent / 'fixtures'
MATERIALS = ('pixel_quest', 'mosaic')
CASES = [(look, lang) for look in MATERIALS for lang in ('en', 'zh')]


def production(tmp_path, look, lang='en', aspect='16:9'):
    project = tmp_path / f'{look}-{lang}-{aspect.replace(":", "-")}'
    episode = pipeline.new_project(FIX / ('tiny.md' if lang == 'en' else 'sleep_zh.md'), project,
                                   direction={'look': look})
    tl = timeline.layout(episode, lang, timeline.synthetic_clips(episode, lang))
    return renderer.make_production(episode, tl, lang, project, aspect=aspect), tl


@pytest.fixture(scope='module', params=CASES, ids=lambda p: '-'.join(p))
def material(request, tmp_path_factory):
    look, lang = request.param
    return production(tmp_path_factory.mktemp('locked-camera'), look, lang)


def test_material_camera_keys_are_cuts_or_wipes(material):
    prod, _ = material
    assert {kind for _, _, kind in prod.camera.keys} <= {'cut', 'wipe'}
    assert any(kind == 'wipe' for _, _, kind in prod.camera.keys)


def _board_positions(prod, t):
    """Expected whole-board positions, derived from key destinations rather than Camera.at."""
    keys = sorted(prod.camera.keys, key=lambda k: k[0])
    i = max(0, bisect.bisect_right([k[0] for k in keys], t) - 1)
    t0, dest, kind = keys[i]
    positions = {dest}
    if kind == 'wipe' and t < t0 + board.PAN_SECONDS:
        positions.add(keys[max(0, i - 1)][1])
    return positions


def _shown_positions(prod, t):
    kind, p, _, _ = prod.mode_at(t)
    if kind == 'stock':
        return set()
    if kind in ('fly', 'agenda'):
        return {prod.agenda_x}
    if kind == 'pullback':
        return {prod.notes[p['section']]['x'], prod.agenda_x}
    positions = _board_positions(prod, t)
    if kind in ('zoom', 'fade_in'):
        positions.add(prod.agenda_x)
    return positions


def test_material_frame_records_only_stationary_boards(material, monkeypatch):
    prod, tl = material
    recorded = []
    original = prod.view

    def record(t, L, hand=True):
        recorded.append(L)
        return original(t, L, hand=hand)

    monkeypatch.setattr(prod, 'view', record)
    boundaries = sorted({0., tl['duration'],
                         *(t for t, _, _ in prod.camera.keys),
                         *(t + board.PAN_SECONDS for t, _, k in prod.camera.keys if k == 'wipe'),
                         *(t for a, b, _, _ in prod.modes for t in (a, b))})
    intervals = {}
    # Render the actual frame path at 10 fps, and also sample either side of every boundary.
    times = sorted({*(i / 10 for i in range(math.ceil(tl['duration'] * 10))),
                    *(max(0., t + dt) for t in boundaries for dt in (-.001, 0., .001)
                      if 0 <= t + dt < tl['duration'])})
    for t in times:
        recorded.clear()
        prod.frame(t)
        shown = set(recorded)
        expected = _shown_positions(prod, t)
        assert shown == expected, (prod.skin.id, prod.lang, t, shown, expected)
        assert len(shown) <= 2, (t, shown)
        interval = bisect.bisect_right(boundaries, t) - 1
        if interval in intervals:
            assert shown == intervals[interval], (t, shown, intervals[interval])
        intervals[interval] = shown


def test_material_section_openers_never_use_zoom(material, monkeypatch):
    prod, _ = material

    def forbidden(*args):
        pytest.fail('a material frame used the zoom path')

    monkeypatch.setattr(prod, '_zoom', forbidden)
    openers = [(a, b) for a, b, k, _ in prod.modes if k == 'zoom']
    assert openers
    for a, b in openers:
        prod.frame((a + b) / 2)


def test_board_wipe_pixels_are_whole_views(material):
    prod, _ = material
    t0, dest, _ = next(k for k in prod.camera.keys if k[2] == 'wipe')
    t = t0 + board.WIPE_SECONDS * .37
    old_L, new_L, u = prod.camera.wipe_at(t)
    assert new_L == dest
    old = np.asarray(prod.view(t, old_L, hand=False))
    new = np.asarray(prod.view(t, new_L, hand=False))
    actual = np.asarray(prod.board_frame(t))
    cell = prod.skin.margs['cell']
    edge = round(actual.shape[1] * renderer.ease(u) / cell) * cell
    assert 0 < edge < actual.shape[1]
    assert not np.array_equal(old, new)
    assert np.array_equal(actual[:, :edge], new[:, :edge])
    assert np.array_equal(actual[:, edge:], old[:, edge:])


@pytest.mark.parametrize('kind', ['zoom', 'fade_in', 'pullback'])
def test_material_mode_wipes_preserve_board_pixels(material, monkeypatch, kind):
    prod, _ = material
    a, b, _, p = next(m for m in prod.modes if m[2] == kind)
    t = a + .37 * (b - a)
    if kind == 'zoom':
        old = prod.view(a - .01, prod.agenda_x, hand=False)
        new = prod.board_frame(t)
    elif kind == 'fade_in':
        old = prod.view(t, prod.agenda_x, hand=False)
        new = prod.board_frame(t)
    else:
        note = prod.notes[p['section']]
        tr = next(tr for tr in prod.tl['transitions'] if tr['section'] == p['section'])
        old = prod.view(tr['hold_end'] - .01, note['x'], hand=False)
        new = prod.view(t, prod.agenda_x, hand=False)
    edge = round(old.width * renderer.ease(.37) / prod.skin.margs['cell']) * prod.skin.margs['cell']
    expected = old.copy()
    expected.paste(new.crop((0, 0, edge, new.height)), (0, 0))
    if kind == 'pullback':
        nx, ny, _, _ = note['bbox']
        ink.paste(expected, prod._note_image(note, old, nx - note['x'], ny), nx - note['x'], ny)
    monkeypatch.setattr(prod, 'vertical', True)  # inspect the transition before chrome and captions
    assert np.array_equal(np.asarray(prod.frame(t)), np.asarray(expected))


@pytest.mark.parametrize('look,lang', CASES)
def test_material_vertical_frames_add_no_warnings(tmp_path, look, lang):
    landscape, tl = production(tmp_path, look, lang)
    portrait, _ = production(tmp_path, look, lang, aspect='9:16')
    assert portrait.warnings == landscape.warnings
    for t in np.linspace(0, tl['duration'] - .01, 6):
        assert portrait.frame(float(t)).size == (1080, 1920)
    assert portrait.warnings == landscape.warnings


@pytest.mark.parametrize('look', ['whiteboard', 'chalkboard', 'notebook'])
def test_existing_looks_keep_pans_and_zoom_modes(tmp_path, look):
    prod, _ = production(tmp_path, look)
    assert any(k == 'pan' for _, _, k in prod.camera.keys)
    assert any(k == 'zoom' for _, _, k, _ in prod.modes)


@pytest.mark.parametrize('material', ['none', 'pixel', 'tile', 'future'])
def test_lock_tracks_material_exactly(material):
    skin = skins.Skin(material=material)
    assert skin.locked_camera == skin.textured == (material != 'none')


def test_locked_camera_wipe_bounds_targets_and_interruptions():
    cam = board.Camera(locked=True)
    cam.pan(1., 640.)
    cam.pan(1.1, 640.)                    # the target did not change
    assert cam.keys == [(0., 0., 'cut'), (1., 640., 'wipe')]
    assert cam.at(.999) == 0.
    assert cam.at(1.) == cam.at(1.4) == cam.target_at(1.4) == 640.
    assert cam.wipe_at(.999) is None
    assert cam.wipe_at(1.) == (0., 640., 0.)
    assert cam.wipe_at(1.45) == pytest.approx((0., 640., .5))
    assert cam.wipe_at(1. + board.WIPE_SECONDS) is None
    cam.pan(1.5, 1920.)                  # a new wipe starts from the previous destination
    assert cam.wipe_at(1.5) == (640., 1920., 0.)
    assert cam.at(1.5) == 1920.
    cam.cut(1.6, 3200.)                  # a cut interrupts the wipe
    assert cam.at(1.6) == 3200. and cam.wipe_at(1.6) is None
    assert board.WIPE_SECONDS == board.PAN_SECONDS


def test_default_camera_keeps_its_eased_pan():
    cam = board.Camera()
    cam.pan(1., 640.)
    assert cam.keys[-1] == (1., 640., 'pan')
    assert cam.at(1.45) == pytest.approx(320.)
    assert cam.wipe_at(1.45) is None


@pytest.mark.parametrize('locked,first_col', [(False, 4), (True, 3)])
def test_scheduler_starts_locked_boards_at_the_visuals_first_column(locked, first_col):
    cam = board.Camera(locked=locked)
    drawing = ink.StaticDrawing(Image.new('RGBA', (4 * board.COL - 4, 1)), pop=.01)
    el = board.Element(drawing, 3 * board.COL + 2, 100, 1., hand=False)
    board.Scheduler(cam).run([el], [(0., 0., 'cut')])
    assert cam.keys[-1] == (1., first_col * board.COL, 'wipe' if locked else 'pan')
    assert el.start == 1. + board.PAN_SECONDS


@pytest.mark.parametrize('locked', [False, True])
def test_scheduler_keeps_the_whole_page_at_its_base(locked):
    cam = board.Camera(locked=locked)
    cam.pan(.5, 9 * board.COL)
    drawing = ink.StaticDrawing(Image.new('RGBA', (3 * board.COL - 4, 1)), pop=.01)
    el = board.Element(drawing, 5 * board.COL + 2, 100, 2., hand=False, essential=True)
    board.Scheduler(cam).run([el], [(0., 5 * board.COL, 'cut')])
    assert cam.keys[-1] == (2., 5 * board.COL, 'wipe' if locked else 'pan')


@pytest.mark.parametrize('look', MATERIALS)
@pytest.mark.parametrize('u', [-1., 0., .37, .5, 1., 2.])
def test_wipe_helper_snaps_cells_and_finishes_at_the_frame_edge(look, u):
    skin = skins.for_look(look)
    # Width deliberately not divisible by the cell size: the last partial cell must finish too.
    old = Image.new('RGBA', (101, 33), 'red')
    new = Image.new('RGBA', old.size, 'blue')
    before = old.tobytes(), new.tobytes()
    actual = np.asarray(skins.wipe(old, new, u, skin))
    cell = skin.margs['cell']
    edge = min(old.width, max(0, round(old.width * renderer.ease(u) / cell) * cell))
    if u >= 1:
        edge = old.width
    assert np.array_equal(actual[:, :edge], np.asarray(new)[:, :edge])
    assert np.array_equal(actual[:, edge:], np.asarray(old)[:, edge:])
    assert (old.tobytes(), new.tobytes()) == before

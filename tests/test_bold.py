"""Pixel-level acceptance for the smooth renderer and its hybrid joins."""
import hashlib
import multiprocessing
from dataclasses import asdict

import numpy as np
import pytest

from kinodraw.engine import motion as m
from kinodraw.engine.bold import BoldProduction, MotionElement as E, MotionScene, render_frame, render_transition
from kinodraw.engine.bold.charts import chart_svg, counter_text, counter_value
from kinodraw.engine.bold.demo import demo_scenes
from kinodraw.engine.bold.model import PANEL_ENTER, TEXT_ENTER, HOLD_MIN, HOLD_MAX, TYPE_CPS, TRANSITIONS
from kinodraw.engine.bold.render import _raster, glow_layer, needs_motion_blur, scene_svg

SIZE = 320, 180


def digest(frame):
    return hashlib.sha256(frame.tobytes()).hexdigest()


def luma(frame):
    return (frame @ np.array([.2126, .7152, .0722])).mean() / 255


def swings(values):
    """Count excursions of >=20% full-scale, including gradual ramps across several frames."""
    low = high = values[0]
    direction = count = 0
    for value in values[1:]:
        low, high = min(low, value), max(high, value)
        if direction <= 0 and value - low >= .2:
            count, direction, high = count + 1, 1, value
        elif direction >= 0 and high - value >= .2:
            count, direction, low = count + 1, -1, value
    return count


def test_flash_probe_detects_repeated_flashes_but_counts_a_ramp_once():
    assert swings([0, .1, .3, .5, .8, 1]) == 1
    assert swings([0, 1, 0, 1, 0, 1, 0]) == 6


def test_reference_easing_and_timing():
    assert (TEXT_ENTER, PANEL_ENTER, HOLD_MIN, HOLD_MAX, TYPE_CPS) == (.4, .65, .5, 1.1, 30)
    values = [m.expo_out(i / 100) for i in range(101)]
    assert values[0] == 0 and values[-1] == 1
    assert np.all(np.diff(values) > 0) and max(values) == 1
    assert m.expo_out(.5) == pytest.approx(.9696969697)
    assert m.typewriter('x' * 100, 1, 0, TYPE_CPS) == 30
    assert E().entrance == .4 and E(kind='ring').entrance == .65
    assert m.snap_to_beat(.72, 120) == .5
    assert m.snap_to_beat(.75, 120) == 1.
    assert m.snap_to_beat(.34, 120, 2, origin=.1) == .35
    for decay in (.6, .7, .75):
        positions = [m.speed_kick(i / 30, 10, decay) for i in range(5)]
        assert np.diff(positions)[1:] / np.diff(positions)[:-1] == pytest.approx([decay] * 3)


def test_scene_roundtrip_and_validation():
    scene = demo_scenes()[0]
    restored = MotionScene(**asdict(scene))
    assert digest(render_frame(scene, 1.2, *SIZE)) == digest(render_frame(restored, 1.2, *SIZE))
    with pytest.raises(ValueError):
        MotionScene(energy=0)
    with pytest.raises(ValueError):
        MotionScene(hold=2)
    assert MotionScene(elements=[E(text='x' * 30)], hold=.8).duration == pytest.approx(1.8)
    assert MotionScene(elements=[E(kind='ring')], hold=.5).duration == pytest.approx(1.15)
    assert MotionScene(elements=[E(kind='particle_field')], hold=.5).duration == pytest.approx(1.4)


def test_deterministic_pixels_after_seeking_and_random_activity():
    scene = MotionScene(elements=[E(kind='particle_field', emissive=True), E(text='FRAME = f(t)')], grain=.5)
    original = render_frame(scene, 1.2, *SIZE)
    np.random.default_rng().random(100)
    render_frame(scene, .1, *SIZE)
    render_frame(scene, 2.8, *SIZE)
    assert original.dtype == np.uint8 and original.shape == (180, 320, 3)
    assert digest(original) == digest(render_frame(scene, 1.2, *SIZE))


@pytest.mark.parametrize('kind', ['text', 'picture', 'dot', 'line', 'ring', 'particle_field', 'chart'])
def test_every_element_has_life_during_a_hold(kind):
    element = E(kind=kind, text='Hold', preset='slam', svg_id='fl_rocket', values=(2, 4, 3), emissive=True)
    scene = MotionScene(elements=[element], glow=0, motion_floor=1)
    frames = [render_frame(scene, 2 + i / 30, *SIZE) for i in range(31)]
    hashes = [digest(f) for f in frames]
    assert all(a != b for a, b in zip(hashes, hashes[1:]))
    assert all(len(set(hashes[i:i + 16])) > 1 for i in range(16))
    # Isolate the element: background drift alone cannot satisfy the floor.
    layer = 'text' if kind == 'text' else 'emissive'
    isolated = [digest(_raster(scene_svg(scene, 2 + i / 30, layer), *SIZE, text=kind == 'text'))
                for i in range(31)]
    assert all(len(set(isolated[i:i + 16])) > 1 for i in range(16))
    still = MotionScene(elements=[element], glow=0, motion_floor=0)
    assert np.array_equal(render_frame(still, 2, *SIZE), render_frame(still, 2.5, *SIZE))


def test_counter_ticks_each_frame_and_charts_draw_data():
    counter = E(preset='counter', value_to=4160, duration=1.8)
    numbers = [counter_value(counter, i / 30) for i in range(55)]
    assert np.all(np.diff(numbers) > 0)
    assert numbers[0] == 0 and numbers[-1] == 4160
    small = E(preset='counter', value_to=1, duration=1.8)
    assert len({counter_text(small, i / 30) for i in range(55)}) == 55
    for kind in ('bar', 'line', 'number'):
        scene = MotionScene(elements=[E(kind='chart', chart=kind, values=(2, 4, 3), labels=('A', 'B', 'C'))])
        assert not np.array_equal(render_frame(scene, 0, *SIZE), render_frame(scene, 1, *SIZE))
    signed = E(kind='chart', values=(-2, 2), width=100, height=100)
    art, _ = chart_svg(signed, 2, '#ffb454', '#d7d6d2')
    assert 'y="0.0"' in art and 'y="-50.0"' in art


@pytest.mark.parametrize('preset', ['type_on', 'word_pop', 'slam', 'cascade', 'counter', 'corner_caption'])
def test_text_presets_are_rendered_without_glow_or_grain(preset):
    scene = MotionScene(elements=[E(text='Smooth motion', preset=preset)])
    text = scene_svg(scene, .3, 'text')
    assert '<text' in text
    assert '<text' not in scene_svg(scene, .3, 'emissive')
    assert 'filter=' not in text
    assert not np.array_equal(render_frame(scene, 0, *SIZE), render_frame(scene, .8, *SIZE))


def test_raw_and_library_svg_are_real_artwork_and_external_resources_are_rejected():
    raw = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 100 L50 0 L100 100Z" fill="red"/></svg>'
    scene = MotionScene(elements=[E(kind='picture', svg=raw, accent=True)], motion_floor=0)
    doc = scene_svg(scene, 1)
    assert 'red' not in doc and scene.palette.accent in doc
    assert render_frame(scene, 1, *SIZE).max() > 150
    unsafe = '<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///private/example"/></svg>'
    with pytest.raises(ValueError, match='Unsupported SVG'):
        render_frame(MotionScene(elements=[E(kind='picture', svg=unsafe)]), 1, *SIZE)


def test_svg_labels_stay_on_the_sharp_layer_and_full_bleed_covers_the_stage():
    raw = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
           '<rect width="100" height="100"/><g transform="translate(10 20)">'
           '<text font-size="15">LABEL</text></g></svg>')
    scene = MotionScene(elements=[E(kind='picture', svg=raw)], composition='full_bleed', glow=0, motion_floor=0)
    assert '<ns0:text' not in scene_svg(scene, 1, 'art')
    assert 'LABEL' in scene_svg(scene, 1, 'text')
    frame = render_frame(scene, 1, *SIZE)
    assert min(frame[0, 0]) > 150 and min(frame[-1, -1]) > 150


def test_repeated_svg_ids_keep_each_picture_in_its_own_palette():
    raw = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<defs><linearGradient id="tone"><stop stop-color="red"/>'
           '<stop offset="1" stop-color="red"/></linearGradient></defs>'
           '<rect width="100" height="100" fill="url(#tone)"/></svg>')
    scene = MotionScene(elements=[E(kind='picture', svg=raw, x=.25, width=200, height=200, accent=True),
                                 E(kind='picture', svg=raw, x=.75, width=200, height=200)], motion_floor=0, glow=0)
    frame = render_frame(scene, 1, *SIZE)
    left, right = frame[90, 80].astype(int), frame[90, 240].astype(int)
    assert left[0] - left[1] > 50
    assert right.max() - right.min() < 10


def test_glow_half_distance_and_blur_threshold():
    impulse = np.zeros((501, 501, 1), np.float32)
    impulse[250, 250] = 1
    glow = glow_layer(impulse, 100)
    assert glow[250, 350, 0] / glow[250, 250, 0] == pytest.approx(.5, rel=.002)
    scene = MotionScene(elements=[E(kind='picture', svg_id='fl_rocket', kick=50)])
    assert needs_motion_blur(scene, .04)
    assert not needs_motion_blur(scene, 2)
    text = MotionScene(elements=[E(text='SLAM', preset='slam', kick=50)])
    assert not needs_motion_blur(text, .04)
    sharp = MotionScene(elements=scene.elements, blur_samples=1)
    assert not np.array_equal(render_frame(scene, .04, *SIZE), render_frame(sharp, .04, *SIZE))
    assert np.array_equal(render_frame(scene, 2, *SIZE), render_frame(sharp, 2, *SIZE))
    for kind in ('chart', 'particle_field'):
        tiny = MotionScene(elements=[E(kind=kind, width=10, height=10, values=(1, 2))], motion_floor=0)
        assert not needs_motion_blur(tiny, .55)
    dot = MotionScene(elements=[E(kind='dot')], motion_floor=0)
    assert not needs_motion_blur(dot, .01)    # 468 px/s; unused panel dimensions do not count


@pytest.mark.parametrize('camera', ['static', 'slow_push', 'pull_back', 'pan', 'shake'])
@pytest.mark.parametrize('composition', ['center', 'left_third', 'right_third', 'split', 'grid', 'full_bleed'])
def test_camera_and_compositions(camera, composition):
    scene = MotionScene(elements=[E(kind='ring')], camera=camera, composition=composition)
    assert render_frame(scene, 1, *SIZE).shape == (180, 320, 3)


@pytest.mark.parametrize('kind', sorted(TRANSITIONS))
def test_each_transition_for_scenes_and_hybrid_rgb_endpoints(kind):
    before, after = demo_scenes()[:2]
    rgb = np.full((180, 320, 3), 240, np.uint8)
    for old, new in ((before, after), (rgb, after), (before, rgb)):
        start = render_transition(old, new, 0, *SIZE, kind=kind)
        middle = render_transition(old, new, .325, *SIZE, kind=kind)
        end = render_transition(old, new, .65, *SIZE, kind=kind)
        assert middle.dtype == np.uint8 and middle.shape == rgb.shape
        target = render_frame(new, .65, *SIZE) if isinstance(new, MotionScene) else rgb
        assert np.array_equal(end, target)
        if kind != 'cut':
            source = render_frame(old, old.duration, *SIZE) if isinstance(old, MotionScene) else rgb
            assert np.array_equal(start, source)
            assert not np.array_equal(middle, start) and not np.array_equal(middle, end)
    # A full contrast handoff must make at most three full-scale luma excursions in any second.
    levels = [luma(render_transition(np.zeros_like(rgb), rgb, i / 30, *SIZE, kind=kind)) for i in range(31)]
    assert swings(levels) <= 3


def test_morph_moves_one_motif_instead_of_dissolving_two_static_shapes():
    before = MotionScene(elements=[E(kind='dot', motif='idea', x=.2, size=40)], motion_floor=0, glow=0)
    after = MotionScene(elements=[E(kind='ring', motif='idea', x=.8, size=80, start=-1)], motion_floor=0, glow=0)
    middle = render_transition(before, after, .325, *SIZE, kind='morph', old_t=1, new_t=1)
    foreground = middle.max(axis=2) > 80
    xs = np.where(foreground)[1]
    assert 140 < xs.mean() < 180
    assert xs.max() - xs.min() < 30


@pytest.fixture(scope='module')
def demo_frames():
    production = BoldProduction(demo_scenes(), size=SIZE)
    return production, [production.frame_array(i / 30) for i in range(360)]


def test_demo_no_jumps_except_declared_cuts_and_no_static_half_second(demo_frames):
    production, frames = demo_frames
    differences = [np.abs(b.astype(float) - a).mean() for a, b in zip(frames, frames[1:])]
    for i, difference in enumerate(differences):
        if not any(i / 30 < cut <= (i + 1) / 30 for cut in production.cuts):
            assert difference < 8, (i, difference)
    hashes = [digest(f) for f in frames]
    assert all(len(set(hashes[i:i + 16])) > 1 for i in range(len(frames) - 15))
    levels = [luma(f) for f in frames]
    assert all(swings(levels[i:i + 31]) <= 3 for i in range(len(levels) - 30))
    assert production.frame(1).mode == 'RGB'
    assert production.ctx.elements and production.cues() and production.warnings == []
    assert production.duration == 12


def test_declared_cut_is_exact():
    scenes = demo_scenes()[:2]
    scenes[1].transition_in = 'cut'
    production = BoldProduction(scenes, size=SIZE)
    assert production.cuts == [2.5]
    assert np.array_equal(production.frame_array(2.5), render_frame(scenes[1], 0, *SIZE))


def test_static_appearance_is_cached_across_motion_and_invalidated_on_edits(monkeypatch):
    from kinodraw.engine.bold import render as renderer
    renderer._LAYERS.clear()
    calls = []
    raster = renderer._raster
    monkeypatch.setattr(renderer, '_raster', lambda *a, **k: calls.append(a[0]) or raster(*a, **k))
    scene = MotionScene(elements=[E(kind='picture', svg_id='fl_rocket'), E(text='CACHED', preset='slam')], glow=0)
    a = render_frame(scene, 2, *SIZE)
    count = len(calls)
    b = render_frame(scene, 2.2, *SIZE)
    assert count == 2 and len(calls) == count
    assert not np.array_equal(a, b)
    scene.elements[1].text = 'EDITED'
    edited = render_frame(scene, 2.2, *SIZE)
    assert len(calls) == count + 1 and not np.array_equal(b, edited)
    scene.elements[0].accent = True
    render_frame(scene, 2.2, *SIZE)
    assert len(calls) == count + 2


def test_blur_reuses_rasters_and_leaves_stationary_art_sharp(monkeypatch):
    from kinodraw.engine.bold import render as renderer
    renderer._LAYERS.clear()
    scene = MotionScene(elements=[E(kind='dot', kick=50, x=.3, size=40),
                                 E(kind='ring', start=-1, x=.8, size=150)], motion_floor=0, glow=0, blur_samples=1)
    sharp = render_frame(scene, .04, *SIZE)
    monkeypatch.setattr(renderer, '_raster', lambda *a, **k: pytest.fail('unchanged geometry was rasterised again'))
    scene.blur_samples = 3
    blurred = render_frame(scene, .04, *SIZE)
    assert np.array_equal(sharp[:, 220:], blurred[:, 220:])
    assert not np.array_equal(sharp[:, :200], blurred[:, :200])


def test_glow_uses_quarter_resolution_and_the_cached_art(monkeypatch):
    from kinodraw.engine.bold import render as renderer
    renderer._LAYERS.clear()
    shapes = []
    original = renderer.glow_layer
    monkeypatch.setattr(renderer, 'glow_layer', lambda a, d: shapes.append(a.shape) or original(a, d))
    scene = MotionScene(elements=[E(kind='ring', emissive=True)], motion_floor=0)
    render_frame(scene, 2, *SIZE)
    monkeypatch.setattr(renderer, '_raster', lambda *a, **k: pytest.fail('glow rasterised a second copy of the artwork'))
    render_frame(scene, 2.1, *SIZE)
    assert shapes == [(45, 80, 3)] * 2


@pytest.mark.parametrize('size', [(1920, 1080), (1280, 720), (1080, 1920)])
def test_corner_captions_have_readable_cap_height(size):
    scene = MotionScene(elements=[E(text='H', preset='corner_caption', size=19)], motion_floor=0, glow=0)
    frame = render_frame(scene, 2, *size)
    rows = np.flatnonzero((frame.max(axis=2) > 100).any(axis=1))
    assert len(rows) >= 18 * size[1] / 1080
    long = E(text='CORNER CAPTIONS MUST STAY READABLE', preset='corner_caption', size=19, width=180)
    doc = scene_svg(MotionScene(elements=[long]), 2, 'text')
    assert doc.count('<text') > 1 and 'font-size="28.000000"' in doc


def test_counter_subtitle_has_a_gap_outside_the_ring():
    from kinodraw.engine.bold.render import element_pose
    scene = demo_scenes()[1]
    ring, subtitle = scene.elements[0], scene.elements[2]
    for t in np.linspace(.6, scene.duration, 30):
        _, ry, rs, _ = element_pose(scene, ring, 0, t)
        _, ty, ts, _ = element_pose(scene, subtitle, 2, t)
        assert ty - subtitle.size * ts / 2 - (ry + (ring.size / 2 + 2) * rs) >= 24


def _bold_segment(bounds):
    from kinodraw.engine.bold import render as renderer
    renderer._LAYERS.clear()
    scenes = demo_scenes()
    for scene in scenes:
        scene.grain = .4
    production = BoldProduction(scenes, size=(160, 90))
    assert production.els is production.ctx.elements    # engine.render.build's worker interface
    start, n = bounds
    return np.stack([production.frame_array(start + i / 30) for i in range(n)])


def test_two_worker_splits_equal_single_process_with_cold_caches():
    expected = _bold_segment((0, 360))
    with multiprocessing.get_context('spawn').Pool(2) as pool:
        for split in (75, 91, 251):    # scene boundary, inside a morph, and inside kinetic type
            pieces = pool.map(_bold_segment, [(0, split), (split / 30, 360 - split)])
            assert np.array_equal(expected, np.concatenate(pieces))

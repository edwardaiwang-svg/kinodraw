"""Atmosphere frame contracts, fog/star composition and the local Mac timing gate."""
import hashlib
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw.engine.atmos import Atmosphere, compose
from kinodraw.engine.atmos.layers import KINDS
from kinodraw.engine.atmos.noise import fbm


@pytest.mark.parametrize('kind', KINDS)
def test_deterministic_premultiplied_frames(kind):
    a, b = Atmosphere(kind, seed='lion'), Atmosphere(kind, seed='lion')
    frame = a.rgba(2.7, 192, 108)
    a.rgba(4.1, 192, 108)                 # seeking or worker order must not change a frame
    assert np.array_equal(frame, a.rgba(2.7, 192, 108))
    assert np.array_equal(frame, b.rgba(2.7, 192, 108))
    assert frame.shape == (108, 192, 4) and frame.dtype == np.float32
    assert np.isfinite(frame).all() and frame.min() >= 0 and frame.max() <= 1
    assert (frame[..., :3] <= frame[..., 3:4] + 1e-7).all()


def test_seed_is_stable_in_a_fresh_process_and_changes_the_scene():
    kinds = ['night_sky', 'starfield', 'shooting_star', 'fog', 'dust']
    frame = Atmosphere(kinds, seed='lion').rgba(2.7, 192, 108)
    code = """import hashlib
from kinodraw.engine.atmos import Atmosphere
f = Atmosphere(['night_sky', 'starfield', 'shooting_star', 'fog', 'dust'], seed='lion').rgba(2.7, 192, 108)
print(hashlib.sha256(f.tobytes()).hexdigest())
"""
    digest = subprocess.check_output([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], text=True).strip()
    assert digest == hashlib.sha256(frame.tobytes()).hexdigest()
    assert not np.array_equal(frame, Atmosphere(kinds, seed='cub').rgba(2.7, 192, 108))


@pytest.mark.parametrize('kind', [k for k in KINDS if k != 'shooting_star'])
def test_declared_loops_are_seamless_and_move(kind):
    scene = Atmosphere(kind, seed=17)
    assert scene.loop_period == 6.
    for t in (0., .731, -1.5):
        assert np.allclose(scene.rgba(t, 192, 108), scene.rgba(t + 6, 192, 108), atol=2e-6)
    before, after = scene.rgba(6 - 1e-4, 192, 108), scene.rgba(1e-4, 192, 108)
    assert np.abs(before - after).max() < .01
    if kind != 'night_sky':
        assert not np.allclose(scene.rgba(.2, 192, 108), scene.rgba(1.7, 192, 108))


def test_fbm_is_multiscale_seeded_and_periodic():
    x, y = np.linspace(0, 5, 180, dtype=np.float32)[None, :], np.linspace(0, 3, 100, dtype=np.float32)[:, None]
    field = fbm(x, y, .7, seed=22)
    assert field.shape == (100, 180) and field.dtype == np.float32
    assert field.min() >= 0 and field.max() <= 1 and field.std() > .08
    assert np.allclose(field, fbm(x, y, 6.7, seed=22), atol=2e-6)
    assert not np.allclose(field, fbm(x, y, .7, seed=23))
    assert not np.allclose(field, fbm(x, y, .7, seed=22, octaves=1))


def test_fog_density_is_pointwise_monotonic_with_height_falloff():
    frames = [Atmosphere('fog', density=d, seed=31).rgba(1.2, 480, 270) for d in (0, .4, 1, 2.5)]
    assert not frames[0].any()
    for lower, upper in zip(frames, frames[1:]):
        assert (upper[..., 3] >= lower[..., 3]).all()
        assert upper[..., 3].mean() > lower[..., 3].mean()
    assert frames[2][-20:, :, 3].mean() > frames[2][:20, :, 3].mean()


def test_shooting_star_is_visible_through_fog_only_in_its_window():
    fog = {'kind': 'fog', 'density': 1.8}
    star = {'kind': 'shooting_star', 'window': (1.5, 3.)}
    base = Atmosphere(['night_sky', 'starfield', fog], seed='lion')
    veiled = Atmosphere(['night_sky', 'starfield', star, fog], seed='lion')
    clear = Atmosphere(['night_sky', 'starfield', star], seed='lion')
    sky = Atmosphere(['night_sky', 'starfield'], seed='lion')
    assert veiled.loop_period is None
    for t in (0, 1.5, 3., 4., 8.25):
        assert np.array_equal(base.rgba(t, 480, 270), veiled.rgba(t, 480, 270))
    for t in (1.7, 2.25, 2.8):
        delta = (veiled.rgba(t, 480, 270)[..., :3] - base.rgba(t, 480, 270)[..., :3]).mean(axis=-1)
        u = (t - 1.5) / 1.5
        hx, hy = round((.18 + .64 * u) * 479), round((.17 + .38 * u) * 269)
        assert delta[hy - 4:hy + 5, hx - 4:hx + 5].max() > .15
        assert delta[20:60, 350:450].max() < .01
        unmasked = (clear.rgba(t, 480, 270)[..., :3] - sky.rgba(t, 480, 270)[..., :3]).mean(axis=-1)
        assert 0 < delta[hy, hx] < unmasked[hy, hx]     # foreground fog really attenuates the star
    assert not Atmosphere(star).rgba(3.1, 192, 108).any()


def test_palette_and_smooth_upscale():
    fog = Atmosphere('fog', palette={'fog': '#ff0000'}, seed=1)
    frame = fog.rgba(.3, 1280, 720)
    assert frame.shape == (720, 1280, 4) and frame.dtype == np.float32
    assert not frame[..., 1:3].any()
    assert np.array_equal(frame[..., 0], frame[..., 3])
    assert np.abs(np.diff(frame[..., 3], axis=1)).max() < .02
    warm = Atmosphere(['dawn', 'dust'], palette=['#24304b', '#e5a275', '#ffe5aa'])
    cool = Atmosphere(['dawn', 'dust'], palette=['#122235', '#639cb0', '#bad7ef'])
    assert not np.allclose(warm.rgba(1, 192, 108), cool.rgba(1, 192, 108))


def test_composition_over_and_under_renderer_content():
    background = Image.new('RGB', (192, 108), (255, 255, 255))
    fog = Atmosphere('fog', seed=5)
    front = fog.rgba(.5, 192, 108)
    result = compose(background, fog, .5)
    assert result.dtype == np.float32
    assert np.allclose(result, front[..., :3] + 1 - front[..., 3:4])
    assert np.array_equal(np.asarray(background), np.full((108, 192, 3), 255, np.uint8))
    content = np.zeros((108, 192, 4), np.float32)
    content[40:60, 80:110] = (1, 0, 0, 1)
    sky = Atmosphere(['night_sky', 'starfield'], seed=5)
    under = compose(np.zeros((108, 192, 3), np.float32), [sky, content], .5)
    both = compose(np.zeros((108, 192, 3), np.float32), [sky, content, fog], .5)
    assert np.array_equal(under[50, 90], [1, 0, 0])
    assert not np.array_equal(both[50, 90], under[50, 90])
    assert np.allclose(compose(result, [], .5), result)


@pytest.mark.parametrize('look', ['whiteboard', 'collage'])
def test_overlay_on_real_renderer_frames(look, tmp_path):
    from kinodraw import ingest, script
    from kinodraw.engine import render, timeline

    fixture = Path(__file__).parent / 'fixtures' / 'promo_tiny.md'
    board = script.build(ingest.read(fixture), 'promo')
    board.update({'look': look, 'story': 'promo', 'motion': 'lively', 'brand': {'name': 'Friendr', 'url': 'friendr.nl'}})
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    production = render.make_production(board, timing, 'en', tmp_path)
    frame = production.frame(2.)
    original = np.asarray(frame).copy()
    fog = Atmosphere('fog', seed='renderer')
    result = compose(frame, fog, 2.)
    assert result.shape == (*original.shape[:2], 3) and np.isfinite(result).all()
    assert np.abs(result - original[..., :3] / 255).mean() > .03
    assert np.array_equal(original, np.asarray(frame))


@pytest.mark.parametrize('kwargs', [dict(kinds='smoke'), dict(kinds='fog', density=-1),
                                  dict(kinds='dust', density=float('nan')), dict(kinds='rain', period=0),
                                  dict(kinds={'kind': 'shooting_star', 'window': (3, 2)}),
                                  dict(kinds={'kind': 'fog', 'height_falloff': -1}),
                                  dict(kinds={'kind': 'fog', 'bogus': 1})])
def test_invalid_scene_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Atmosphere(**kwargs)


@pytest.mark.parametrize('kind', KINDS)
def test_per_layer_timing_budget(kind):
    scene = Atmosphere(kind, density=1.6, seed='timing')
    for _ in range(3):
        scene.rgba(2.6, 480, 270)
    start = time.perf_counter()
    for i in range(30):
        scene.rgba(2.4 + i / 100, 480, 270)
    ms = (time.perf_counter() - start) * 1000 / 30
    print(f'\n{kind}: {ms:.2f} ms/frame at 480x270')
    assert ms <= 20, f'{kind}: {ms:.2f} ms/frame, budget 20 ms'

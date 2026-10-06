"""Structural budgets: animated particle placement must reuse raster primitives."""
import hashlib

import numpy as np
from kinodraw.engine.bold import BoldProduction, MotionElement as E, MotionScene, render_frame
from kinodraw.engine.bold.demo import demo_scenes
from kinodraw.engine.bold import render as renderer


def test_particles_reuse_raster_primitives_during_motion_and_glow(monkeypatch):
    renderer._LAYERS.clear()
    calls = []
    raster = renderer._raster
    monkeypatch.setattr(renderer, '_raster', lambda *a, **k: calls.append(a[1:3]) or raster(*a, **k))
    scene = MotionScene(elements=[E(kind='particle_field', emissive=True)], motion_floor=1)
    frames = [render_frame(scene, i / 30, 320, 180) for i in range(60)]
    assert len(calls) <= 2, f'{len(calls)} SVG rasters for reusable circles'
    assert not np.array_equal(frames[30], frames[59])


def test_particle_cache_is_seek_deterministic_and_tracks_mutation():
    scene = MotionScene(elements=[E(kind='particle_field', emissive=True)], motion_floor=1)
    expected = render_frame(scene, 1.2, 320, 180)
    render_frame(scene, .1, 320, 180)
    assert np.array_equal(expected, render_frame(scene, 1.2, 320, 180))
    scene.elements[0].count = 8
    assert not np.array_equal(expected, render_frame(scene, 1.2, 320, 180))


def test_counter_batches_exact_reusable_tokens(monkeypatch):
    renderer._LAYERS.clear()
    calls = []
    raster = renderer._raster
    monkeypatch.setattr(renderer, '_raster', lambda *a, **k: calls.append(a[1:3]) or raster(*a, **k))
    scene = MotionScene(elements=[E(preset='counter', value_to=4160, duration=1.8)], glow=0)
    for i in range(60):
        render_frame(scene, i / 30, 320, 180)
    assert len(calls) <= 10, f'{len(calls)} SVG rasters for counter tokens'


def test_glow_reuses_particle_sprite_at_the_same_time(monkeypatch):
    renderer._LAYERS.clear()
    calls = []
    sprite = renderer._particle_sprite
    monkeypatch.setattr(renderer, '_particle_sprite', lambda *a, **k: calls.append(a[3]) or sprite(*a, **k))
    scene = MotionScene(elements=[E(kind='particle_field', emissive=True)], blur_samples=1)
    for i in range(10):
        render_frame(scene, 1 + i / 30, 320, 180)
    assert len(calls) == 10, f'{len(calls)} identical-time particle composites for 10 frames'


def test_warp_avoids_stacking_four_full_channel_intermediates(monkeypatch):
    pixels = np.zeros((20, 30, 4), np.float32)
    pixels[2:18, 3:27] = (255, 127, 63, 180)
    sprite = renderer._sprite_pixels(pixels, -15, -10, 1, 1)
    pose = (960, 540, 1.1, .75)
    expected = renderer._warp(sprite, pose, 1920, 1080)
    stack = np.stack
    calls = []
    monkeypatch.setattr(np, 'stack', lambda *a, **k: calls.append(True) or stack(*a, **k))
    actual = renderer._warp(sprite, pose, 1920, 1080)
    assert actual[:2] == expected[:2] and np.array_equal(actual[2], expected[2])
    assert not calls, 'Warp allocated four channel arrays and stacked another full RGBA copy'


def test_production_seeks_match_fresh_reference_for_python_and_numpy_times():
    # These are the five exact mismatches in the retained 1080p30 shuffle.
    indices = (266, 88, 241, 86, 276)
    expected = {}
    for i in indices:
        renderer._LAYERS.clear()
        reference = BoldProduction(demo_scenes(), size=(1920, 1080))
        expected[i] = hashlib.sha256(reference.frame_array(i / 30).tobytes()).hexdigest()
    shuffled = np.random.default_rng(20261005).permutation(360)
    orders = (sorted(indices), sorted(indices, reverse=True),
              shuffled[np.isin(shuffled, indices)])
    mismatches = []
    for order_index, order in enumerate(orders):
        renderer._LAYERS.clear()
        seek = BoldProduction(demo_scenes(), size=(1920, 1080))
        for i in order:
            actual = hashlib.sha256(seek.frame_array(i / 30).tobytes()).hexdigest()
            if actual != expected[i]:
                mismatches.append((order_index, int(i)))
    assert not mismatches, f'Seek order/time scalar changed frame pixels: {mismatches}'


def test_counter_tokens_match_fresh_production_through_all_seek_orders():
    indices = range(60)
    expected = {}
    def production():
        return BoldProduction([MotionScene(elements=[E(preset='counter', value_to=4160, duration=1.8)])],
                              size=(320, 180))
    for i in indices:
        renderer._LAYERS.clear()
        expected[i] = production().frame_array(i / 30)
    orders = (indices, reversed(indices), np.random.default_rng(20261005).permutation(60))
    for order in orders:
        renderer._LAYERS.clear()
        seek = production()
        for i in order:
            assert np.array_equal(seek.frame_array(i / 30), expected[i]), f'Counter seek changed frame {i}'


def test_glow_cached_spectrum_matches_full_convolution_exactly(monkeypatch):
    from scipy.signal import fftconvolve
    renderer._glow_spectrum.cache_clear()
    calls = []
    transform = renderer.fft.rfftn
    def record(array, *args, **kwargs):
        calls.append(array.shape)
        return transform(array, *args, **kwargs)
    monkeypatch.setattr(renderer.fft, 'rfftn', record)
    for shape, half_distance in (((45, 80, 3), 4.2), ((270, 480, 3), 25), ((27, 19, 1), 2.5)):
        kernel = renderer._glow_kernel(half_distance / np.sqrt(2 * np.log(2)))
        kernel_calls = calls.count(kernel.shape)
        for seed in (3, 8):
            light = np.random.default_rng(seed).uniform(0, 255, shape).astype(np.float32)
            expected = fftconvolve(light, kernel, mode='same', axes=(0, 1))
            # The reference above transforms its kernel on every invocation.
            assert np.array_equal(renderer.glow_layer(light, half_distance), expected)
        assert calls.count(kernel.shape) - kernel_calls == 3


def test_benchmark_decodes_real_video_and_rejects_wrong_frame_count(tmp_path):
    import imageio_ffmpeg
    import subprocess
    from scripts.bold_benchmark import validate_video
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    video = tmp_path / 'validation.mp4'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=32x32:rate=30',
                    '-frames:v', '2', '-c:v', 'libx264', '-threads', '1', str(video)],
                   check=True, timeout=30)
    valid = validate_video(ffmpeg, video, 2)
    assert valid['validation_exit'] == 0 and valid['validated_frames'] == 2
    assert valid['validation_error'] is None and valid['validation_wall_s'] > 0
    invalid = validate_video(ffmpeg, video, 3)
    assert invalid['validation_exit'] == 0 and invalid['validated_frames'] == 2
    assert 'encoded frames 2 != expected 3' in invalid['validation_error']


def test_channel_compositing_preserves_cropped_rgb_and_rgba_pixels():
    rng = np.random.default_rng(24)
    pixels = rng.uniform(0, 1, (17, 23, 4)).astype(np.float32)
    pixels[..., :3] *= 255 * pixels[..., 3:]
    for channels in (3, 4):
        actual = rng.uniform(0, 255, (31, 49, channels)).astype(np.float32)
        expected = actual.copy()
        region = expected[7:24, 11:34]
        region *= 1 - pixels[..., 3:]
        region += pixels[..., :channels]
        renderer._over(actual, (11, 7, pixels))
        assert np.array_equal(actual, expected)


def test_grained_blurred_art_and_sharp_text_preserve_selected_pixels():
    # Captured from the retained attempt1 before this optimization. The demo
    # gate covers all 360 frames but has no grain, so cover that effect here.
    scene = MotionScene(elements=[
        E(kind='particle_field', emissive=True, count=13, width=700, height=240),
        E(text='SHARP TEXT', preset='slam', x=.5, y=.3)], grain=.7, seed=31)
    expected = {
        .08: '94149a6cc9c98c450ae2be3eef291a09e71f4f740e859df96ea54717178bb49a',
        1.2: '3a3c189fb538c8d0c29e46b216b4233612272ecd4954bf12ab1901f7cda987b9',
    }
    for t in (1.2, .08, 1.2):
        actual = render_frame(scene, t, 319, 181)
        assert actual.flags.c_contiguous and actual.dtype == np.uint8
        assert hashlib.sha256(actual.tobytes()).hexdigest() == expected[t]


def test_numeric_counter_extents_preserve_selected_pixels_at_fractional_scale():
    # Selected-renderer references include numeric fits, decimals, multiline
    # suffixes, Unicode and transformed chart numbers on a fractional grid.
    cases = [
        ({'preset': 'counter', 'value_from': -4300, 'value_to': 4160, 'decimals': 2, 'suffix': '%', 'size': 132, 'width': 700},
         {0.6: '50ceb702a710c370b7ae68fab5a2dfa2bd3dc90d01c055e6210631eac71589ae', 1.8: 'fb267db54bd951a37350f80f0d35ee27f4d2e1c1acf04d61504ea66829fa3eb3'}),
        ({'preset': 'counter', 'value_from': -0.003, 'value_to': 0.013, 'decimals': 6, 'size': 37, 'width': 89},
         {0.6: 'd15f3c05d3092214cc4967b33d1c76449c94374007b9a8337928722f7b47d8c7', 1.8: '9b579b10ac8235b482e5d84f9b10472ea903bb2443087ec45e4604e122156139'}),
        ({'kind': 'chart', 'chart': 'number', 'value_from': -12, 'value_to': 84, 'suffix': '%', 'size': 100, 'width': 400},
         {0.6: '40dddc8e1278e5ea009a94518df71cbca85092854e29bb2459be0060ad26ed13', 1.8: '4f4c0602fc2a81ca0c1a9fe92ca327379226bac234fb487e6cc470938b4e3157'}),
        ({'preset': 'counter', 'value_from': -12, 'value_to': 84, 'suffix': ' points\nTOTAL', 'size': 100, 'width': 400},
         {0.6: 'ed977bd0c72c4ebe0af739a3da73e7fc3376c92eae53ff30ec3d401e06c1a00f', 1.8: '0e242ba7e2d78cbe23aa747c1ea1ec829b7007a4a5df15a10dd5fe0c7f931555'}),
        ({'kind': 'chart', 'chart': 'number', 'preset': 'slam', 'value_to': 84, 'size': 100, 'width': 140},
         {0.6: '57c687e72059424ae8d0d7217a1f82a54e5b8caabdc671822bc193a855381a23', 1.8: 'fa3f2c77cc00a22ef60f92828b4db58a8317202a65fd19d24ae33d87e383efca'}),
        ({'preset': 'counter', 'value_to': 4160, 'suffix': '周', 'size': 100, 'width': 400},
         {0.6: '452825df9e9eeed3f8885fb46c9dd162456bb3e55ffd0fdf18a7f71faba964f5', 1.8: '54ffe91224b768ec4b6063c10d280a9ee55b548d6050c1c1191574d187897231'}),
    ]
    for fields, expected in cases:
        scene = MotionScene(elements=[E(**fields)], glow=0, grain=.2, seed=27)
        for t in (1.8, .6, 1.8):
            actual = renderer.render_frame(scene, t, 321, 181)
            assert hashlib.sha256(actual.tobytes()).hexdigest() == expected[t]


def test_native_numeric_counter_raster_area_budget(monkeypatch):
    calls = []
    raster = renderer._raster
    def record(doc, w, h, **kwargs):
        calls.append((w, h))
        return raster(doc, w, h, **kwargs)
    monkeypatch.setattr(renderer, '_raster', record)
    scene = MotionScene(elements=[E(preset='counter', value_to=4160, duration=1.8)], glow=0)
    layers = renderer._SceneLayers(scene, 1920, 1080)
    for i in range(60):
        layers.sprite(0, i / 30, 'text')
    assert len(calls) <= 10
    assert sum(w * h for w, h in calls) <= 6_000_000


def test_affine_warp_preserves_pixels_without_full_float64_rgb_temporary():
    import tracemalloc
    from PIL import Image

    rng = np.random.default_rng(730)
    coverage = rng.uniform(0, 1, (240, 400)).astype(np.float32)
    solid = ((Image.fromarray(coverage), (255, 180, 84)), -200, -120, 1, 1)
    pixels = rng.uniform(0, 255, (240, 400, 4)).astype(np.float32)
    rgba = renderer._sprite_pixels(pixels, -200, -120, 1, 1)
    # Captured from the complete renderer selected at task entry. Exercise
    # both the integer-colour promotion and the float32 channel/alpha path.
    cases = (
        (solid, '7e8d2136427b389bd108d3a22b0797c1054966f163b5fbb06d797f5793af653f'),
        (rgba, '04cdf00f0404dd5f424c4ad8884fb071f66730cd1f69c48ee54b1409362abd69'),
    )
    for sprite, expected in cases:
        pose = (960, 540, 1.05, .71329)
        renderer._warp(sprite, pose, 1920, 1080)
        owned_trace = not tracemalloc.is_tracing()
        if owned_trace:
            tracemalloc.start()
        try:
            baseline, _ = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            moved = renderer._warp(sprite, pose, 1920, 1080)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            if owned_trace:
                tracemalloc.stop()
        assert moved[2].dtype == np.float32
        assert hashlib.sha256(moved[2].tobytes()).hexdigest() == expected
        # Allow conversion buffers and overhead, but not another H×W×3
        # float64 image in addition to the required float32 RGBA destination.
        assert peak - baseline <= moved[2].nbytes * 1.75 + 128_000


def test_sparse_sprite_crops_before_expanding_full_rgba_raster():
    import tracemalloc

    doc = ('<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1200">'
           '<rect x="911.25" y="551.5" width="177" height="97" '
           'fill="#ffb454" opacity=".71329"/></svg>')
    renderer._raster(doc, 2000, 1200)
    owned_trace = not tracemalloc.is_tracing()
    if owned_trace:
        tracemalloc.start()
    try:
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        sprite = renderer._sprite_pixels(renderer._raster(doc, 2000, 1200), -1000, -600, 1, 1)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if owned_trace:
            tracemalloc.stop()
    # Entry-renderer reference: preserve subpixel coverage and float32
    # premultiplication while bounding allocations for transparent margins.
    assert sprite[1:] == (-90, -50, 1, 1)
    assert sprite[0][0].size == (180, 100)
    digest = hashlib.sha256(b''.join(np.asarray(channel).tobytes() for channel in sprite[0])).hexdigest()
    assert digest == 'a21d693f8d67afb94566476790122c4a82556cbf17e60d787a2c93b752b645b4'
    assert peak - baseline <= 2000 * 1200 * 8 + 3_000_000


def test_fixed_grid_background_preserves_pixels_without_pillow_resize(monkeypatch):
    from PIL import Image

    calls = []
    resize = Image.Image.resize
    monkeypatch.setattr(Image.Image, 'resize', lambda self, *a, **k: calls.append(a[0]) or resize(self, *a, **k))
    pixels = renderer._background(MotionScene(), .731, 320, 180)
    assert hashlib.sha256(pixels.tobytes()).hexdigest() == 'f1498f27afd9726a919373075b33c9c672d98b89cf12453524e434c1bb07266e'
    assert not calls, 'Quarter-resolution RGB background still uses the general Pillow resize'


def test_integer_rgb_upsampling_matches_pillow_two_pass_rounding():
    from PIL import Image

    rng = np.random.default_rng(20261005)
    for h, w in ((1, 1), (1, 3), (3, 1), (3, 7), (45, 80), (270, 480)):
        for _ in range(3):
            pixels = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
            for size in ((w * 4, h * 4), (w * 4 + 1, h * 4 + 1)):
                expected = np.asarray(Image.fromarray(pixels).resize(size, Image.BILINEAR))
                actual = renderer._resize_rgb(pixels, *size)
                assert actual.dtype == np.uint8 and actual.flags.c_contiguous
                assert np.array_equal(actual, expected), f'RGB resize changed pixels at {pixels.shape} -> {size}'


def test_counter_keeps_saved_nonrounded_font_pixels():
    expected = {
        'hand': 'f5cadb7007faae45002e3376940c1d8d7bfe14395b68152d361f34a4da2342a9',
        'serif': '313cecef4308d0acdc271cf25496e0e1d03a13acd513966a69b34ab90ed627cd',
        'mono': '97b0f0e76b133ec912678e02c84721f9cd90d75d130f594620b3a42a46d5a54b',
        'display': '313cecef4308d0acdc271cf25496e0e1d03a13acd513966a69b34ab90ed627cd',
    }
    for family, digest in expected.items():
        scene = MotionScene(elements=[E(kind='text', preset='counter', value_to=88,
            suffix='%', font=family, size=104, width=640, duration=1.8)], duration=3,
            motion_floor=0, foreground_drift=0, glow=0, grain=0, blur_samples=1)
        pixels = render_frame(scene, 2.1, 640, 360)
        assert hashlib.sha256(pixels.tobytes()).hexdigest() == digest

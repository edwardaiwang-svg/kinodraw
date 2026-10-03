"""The motion kit: easing and timing, keyframes, the 2-D camera, paper effects, particles and text kinetics.

Every frame must come out the same whichever render worker draws it, so determinism is tested across processes.
"""
import hashlib
import math
import multiprocessing
import os
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

from kinodraw.engine import motion as m

U = np.linspace(0, 1, 1001)


def curve(f, u=U):
    return np.array([f(x) for x in u])


# ------------------------------------------------------------------ easing and timing
def test_easings_start_at_0_end_at_1_and_clamp():
    for name, f in m.EASING.items():
        assert f(0.) == 0. and f(1.) == 1., name
        assert f(-3.) == 0. and f(7.) == 1., name
    for name in ('linear', 'emphasized', 'expo_out', 'expo_in', 'cubic_in_out'):
        assert (np.diff(curve(m.EASING[name])) >= 0).all(), f'{name} goes backwards'
    assert m.clamp01(-1) == 0 and m.clamp01(2) == 1 and m.lerp(10, 20, .25) == 12.5


def test_emphasized_matches_the_bezier_curve():
    """Against the curve sampled densely; CSS 'ease' (whose midpoint is 0.8024) checks the solver too."""
    s = np.linspace(0, 1, 200001)

    def reference(x1, y1, x2, y2, u):
        bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s ** 2 * x2 + s ** 3
        by = 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s ** 2 * y2 + s ** 3
        return np.interp(u, bx, by)
    u = np.linspace(0, 1, 41)
    assert np.allclose(curve(m.EMPHASIZED, u), reference(.05, .7, .1, 1., u), atol=1e-5)
    assert [round(m.EMPHASIZED(x), 4) for x in (.1, .25, .5, .75)] == [.6214, .8315, .9502, .9905]
    assert m.cubic_bezier(.25, .1, .25, 1.)(.5) == pytest.approx(.8024034, abs=1e-6)


def test_back_out_and_spring_overshoot_once_and_land_exactly():
    assert curve(m.back_out).max() == pytest.approx(1.1, abs=1e-3)         # s = 1.70158 goes 10% past
    sp = curve(m.spring)
    above = sp[1:-1] > 1
    assert np.count_nonzero(above[1:] != above[:-1]) == 2                  # up past 1 once, then back below
    assert 1.08 < sp.max() < 1.16 and U[sp.argmax()] == pytest.approx(1 / 2.2, abs=.01)
    assert m.spring(1.) == 1. and m.spring(.999) != 1.


def test_stagger_squeezes_long_runs_into_the_cap():
    assert m.stagger(4) == pytest.approx([0, .07, .14, .21])
    d = m.stagger(30, gap=.07, cap=.5)
    assert d[-1] == pytest.approx(.5) and np.allclose(np.diff(d), .5 / 29)
    assert m.stagger(1) == [0.] and m.stagger(0) == []


def test_on_twos_holds_every_other_frame():
    assert [round(m.on_twos(i / 30) * 30, 9) for i in range(9)] == [0, 0, 2, 2, 4, 4, 6, 6, 8]
    assert m.on_twos(4 / 30 - 1e-12) == m.on_twos(5 / 30) == 4 / 30        # float noise in t changes nothing
    assert m.on_twos(.5, fps=24) == .5


def test_seeded_depends_on_its_keys_only():
    a = m.seeded('scene', 3, .5).random(4)
    assert np.array_equal(a, m.seeded('scene', 3, .5).random(4))
    assert not np.array_equal(a, m.seeded('scene', 3, .6).random(4))
    assert not np.array_equal(a, m.seeded('scene', 4, .5).random(4))


def _fingerprint(key):
    """What a render worker would make: confetti, and a torn, die-cut, shadowed sprite on seeded paper."""
    art = Image.new('RGBA', (120, 90), (0, 0, 0, 0))
    ImageDraw.Draw(art).ellipse((5, 5, 115, 85), fill=(30, 111, 217, 255))
    sprite = m.Sprite(m.drop_shadow(m.die_cut(m.torn_edge(art, key))))
    canvas = m.paper_texture((320, 180), 'blue_wash', key).convert('RGBA')
    sprite.draw(canvas, 160, 90, scale=1.1, rotation=7.3, alpha=.8)
    return m.confetti(key, 40, (160, 170), .7), hashlib.sha256(canvas.tobytes()).hexdigest()


def test_two_processes_render_identical_frames():
    with multiprocessing.get_context('spawn').Pool(2) as pool:        # fresh interpreters, each its own hash seed
        a, b = pool.map(_fingerprint, ['burst', 'burst'])
    here = _fingerprint('burst')
    assert a == b == here
    assert _fingerprint('other') != here


def test_track_holds_outside_its_keys_and_eases_into_each():
    tr = m.Track([(1, (0., 10.)), (2, (10., 30.), 'expo_out'), (3, (20., 30.), m.cubic_bezier(.5, 0, .5, 1))])
    assert tr.value(0) == (0., 10.) and tr.value(9) == (20., 30.)
    e = m.expo_out(.5)
    assert tr.value(1.5) == pytest.approx((10 * e, 10 + 20 * e))
    assert tr.value(2) == (10., 30.) and tr.value(2.5) == pytest.approx((15., 30.))
    assert m.Track([(0, 5.), (1, 7., 'spring')]).value(1) == 7.


# ------------------------------------------------------------------ camera
def test_camera_moves_layers_by_their_parallax():
    cam = m.Camera2D([(0, 960, 540, 1), (1, 1160, 490, 1, 'linear')])
    assert cam.at(0) == (960, 540, 1) and cam.at(.5) == pytest.approx((1060, 515, 1))
    p = (700, 300)
    assert cam.apply(p, 0) == pytest.approx(p)                              # at rest the world is the screen
    for k in (0, .5, 1, 1.5):                                               # a layer moves k times the camera
        x, y = cam.apply(p, 1, parallax=k)
        assert (x - p[0], y - p[1]) == pytest.approx((-200 * k, 50 * k)), k
    zoom = m.Camera2D([(0, 960, 540, 1), (1, 960, 540, 4)])
    assert zoom.at(.5)[2] == pytest.approx(2)                               # zoom is steady in log space
    assert zoom.apply((1060, 540), 1) == pytest.approx((1360, 540))
    assert zoom.apply((1060, 540), 1, parallax=.5) == pytest.approx((1160, 540))


# ------------------------------------------------------------------ paper, stickers and effects
def test_paper_kinds():
    size = (240, 160)
    for kind in ('cream', 'kraft', 'grid', 'lined', 'blue_wash'):
        img = m.paper_texture(size, kind, 3)
        assert img.mode == 'RGB' and img.size == size, kind
        assert img is m.paper_texture(size, kind, 3), 'not cached'
        assert np.asarray(img, float).std() > 1, f'{kind} is a flat fill'
    px = {k: np.asarray(m.paper_texture(size, k, 3), float) for k in ('cream', 'kraft', 'grid', 'lined', 'blue_wash')}
    assert px['kraft'][..., 2].mean() < px['cream'][..., 2].mean() - 60     # brown, not cream
    assert (px['grid'][:, 40, 2] - px['grid'][:, 40, 0]).mean() > 20        # blue rules
    assert (px['lined'][m.RULE_TOP, :, 2] - px['lined'][m.RULE_TOP, :, 0]).mean() > 20
    assert (px['lined'][:, m.MARGIN_X, 0] - px['lined'][:, m.MARGIN_X, 2]).mean() > 40      # the red margin
    assert (px['blue_wash'][..., 2] - px['blue_wash'][..., 0]).max() > 30
    assert m.paper_texture(size, 'cream', 3).tobytes() != m.paper_texture(size, 'cream', 4).tobytes()


def test_die_cut_grows_a_white_border_of_the_given_width():
    art = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(art).rectangle((20, 20, 79, 79), fill=(211, 47, 47, 255))
    out = m.die_cut(art, border=14)
    assert out.size == (132, 132)                                           # border + 2 on every side
    px = np.asarray(out)
    solid = np.nonzero(px[66, :, 3] > 127)[0]                               # across the middle of the square
    assert solid[0] == pytest.approx(16 + 20 - 14, abs=1) and solid[-1] == pytest.approx(16 + 79 + 14, abs=1)
    assert (px[66, 16 + 20 - 10, :3] == 255).all() and tuple(px[66, 66]) == (211, 47, 47, 255)
    edge = px[..., 3][(px[..., 3] > 0) & (px[..., 3] < 255)]
    assert len(edge) > 20, 'the cut is not anti-aliased'
    ring = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((5, 5, 94, 94), outline=(46, 157, 79, 255), width=12)
    assert tuple(np.asarray(m.die_cut(ring))[66, 66]) == (255, 255, 255, 255)      # one piece: the hole is filled


def test_drop_shadow_keeps_the_picture_centred_and_the_shadow_inside():
    art = Image.new('RGBA', (80, 60), (46, 157, 79, 255))
    out = m.drop_shadow(art, offset=(6, 8), blur=10, opacity=.35)
    k = 30 + 8                                                              # 3 x blur, plus the offset
    assert out.size == (80 + 2 * k, 60 + 2 * k)
    assert np.array_equal(np.asarray(out.crop((k, k, k + 80, k + 60))), np.asarray(art))
    a = np.asarray(out.getchannel('A')).astype(int)
    assert max(a[0].max(), a[-1].max(), a[:, 0].max(), a[:, -1].max()) <= 1, 'the shadow is cut off'
    assert a[k + 30, k + 80 + 6] > a[k + 30, k - 7] + 10 and a[k + 60 + 6, k + 40] > a[k - 7, k + 40] + 10
    alone = np.asarray(m.shadow_only(art, 10, .35).getchannel('A'))
    assert alone.shape == (60 + 60, 80 + 60) and alone.max() <= round(.35 * 255)


def test_torn_edge_is_deterministic_and_frays_inwards():
    art = Image.new('RGBA', (200, 120), (30, 111, 217, 255))
    torn = m.torn_edge(art, 'strip')
    assert torn.tobytes() == m.torn_edge(art, 'strip').tobytes()
    assert torn.tobytes() != m.torn_edge(art, 'other').tobytes()
    px = np.asarray(torn).astype(int)
    assert px[60, 100, 3] == 255 and tuple(px[60, 100, :3]) == (30, 111, 217)
    assert px[0, :, 3].mean() < 100 and px[:, 0, 3].mean() < 100           # the image border is torn too
    near = (px[..., 3] == 255) & (px[..., 0] > 120)                         # pale fibres just inside the tear
    assert near.sum() > 100
    mask = m.torn_edge(Image.new('L', (200, 120), 255), 'strip', amplitude=4)
    a = np.asarray(mask)
    assert mask.mode == 'L' and a[60, 100] == 255 and a[0].mean() < 100


def test_sprite_draws_quantized_cached_poses_about_its_anchor():
    art = Image.new('RGBA', (100, 60), (30, 111, 217, 255))
    sp = m.Sprite(art)

    def drawn(sprite, **pose):
        canvas = Image.new('RGBA', (400, 300), (255, 255, 255, 255))
        sprite.draw(canvas, 200, 150, **pose)
        ys, xs = np.nonzero(np.asarray(canvas)[..., 0] < 128)
        return xs.min(), xs.max(), ys.min(), ys.max()
    assert drawn(sp) == (150, 249, 120, 179)
    assert drawn(sp, rotation=90) == (170, 229, 100, 199)
    assert drawn(m.Sprite(art, anchor=(0, 0)), rotation=90) == (140, 199, 150, 249)     # turned about its corner
    assert sp.pose(1.004, .2, .99) is sp.pose(1., 0., 1.)                   # the same quantized pose
    assert sp.pose(0., 0., 1.) is None and sp.pose(1., 0., 0.) is None
    for k in range(40):
        sp.pose(1., k, 1.)
    assert len(sp._poses) == m.Sprite.POSES


def test_motion_blur_smears_along_the_motion():
    art = Image.new('RGBA', (40, 40), (211, 47, 47, 255))
    assert m.motion_blur(art, .3, .4) is art
    out = m.motion_blur(art, 20, 0)
    assert out.size == (60, 40)
    px = np.asarray(out).astype(int)
    assert px[20, 30, 3] == 255 and 0 < px[20, 2, 3] < 255
    assert (px[..., :3][px[..., 3] > 0] == (211, 47, 47)).all()             # the smeared edges keep their colour


def test_masks():
    size = (192, 108)
    iris = np.asarray(m.iris_mask(size, (96, 54), 30), float) / 255
    assert iris[54, 96] == 1 and iris[54, 96 + 32] == 0 and iris[0, 0] == 0
    assert iris.sum() == pytest.approx(math.pi * 30 ** 2, rel=.01) and ((iris > 0) & (iris < 1)).any()
    wipe = lambda p, **k: np.asarray(m.wipe_mask(size, p, **k))            # noqa: E731
    assert (wipe(0) == 0).all() and (wipe(1) == 255).all()
    half = wipe(.5, soft=1)
    assert (half[:, :96] == 255).all() and (half[:, 96:] == 0).all()        # left to right
    down = wipe(.5, angle_deg=90, soft=1)
    assert (down[:54] == 255).all() and (down[54:] == 0).all()              # top to bottom
    soft = wipe(.5)
    assert ((soft > 0) & (soft < 255)).sum(axis=1).min() >= 20              # a soft edge ~24 px wide
    box = (40, 20, 100, 60)
    assert (np.asarray(m.rect_reveal(size, box, 0)) == 0).all()
    ys, xs = np.nonzero(np.asarray(m.rect_reveal(size, box, .5)) > 127)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (65, 114, 35, 64)    # opening from the box's centre
    full = np.asarray(m.rect_reveal(size, box, 1), int)
    assert full[20:80, 40:140].min() == 255 and full.sum() == 255 * 100 * 60


# ------------------------------------------------------------------ particles
def test_confetti_bursts_up_then_flutters_down_and_fades():
    burst = lambda t: m.confetti('pop', 60, (960, 900), t)                  # noqa: E731
    assert len(burst(0)) == 60 and all(len(p) == 7 for p in burst(0))
    assert all(p[6] == 0 for p in burst(-.1))                               # nothing before the burst
    assert all(p[:2] == pytest.approx((960, 900)) and p[6] == 1 for p in burst(0))
    up, down = np.mean([p[1] for p in burst(.25)]), np.mean([p[1] for p in burst(1.5)])
    assert up < 900 - 150 and down > up
    assert all(p[6] == 0 for p in burst(3.5))
    assert burst(.8) == burst(.8) and burst(.8) != m.confetti('pop2', 60, (960, 900), .8)
    colors = [(1, 2, 3), (4, 5, 6)]
    assert {p[5] for p in m.confetti('pop', 60, (0, 0), 1, colors=colors)} <= set(colors)


def test_sample_points_fall_inside_the_mask():
    mask = Image.new('L', (200, 100), 0)
    ImageDraw.Draw(mask).ellipse((20, 10, 180, 90), fill=255)
    pts = m.sample_points(mask, 500, 'glyph')
    assert pts.shape == (500, 2)
    assert (np.asarray(mask)[pts[:, 1].astype(int), pts[:, 0].astype(int)] > 127).all()
    assert np.array_equal(pts, m.sample_points(np.asarray(mask) > 127, 500, 'glyph'))


def test_assemble_leaves_the_source_and_lands_on_the_target():
    src, dst = m.seeded('src').uniform(0, 500, (50, 2)), m.seeded('dst').uniform(0, 500, (50, 2))
    assert np.array_equal(m.assemble(src, dst, 0, seed_key='g'), src)
    assert np.array_equal(m.assemble(src, dst, -1, seed_key='g'), src)
    assert np.allclose(m.assemble(src, dst, .9 + .25, seed_key='g'), dst)
    mid = m.assemble(src, dst, .4, seed_key='g')
    assert np.array_equal(mid, m.assemble(src, dst, .4, seed_key='g'))
    done = np.hypot(*(mid - src).T) / np.hypot(*(dst - src).T)
    assert 0 < done.min() < done.max() < 1                                  # staggered: each at its own point


# ------------------------------------------------------------------ text kinetics
def test_slam_pop_and_cascade_land_exactly():
    assert m.slam(0, 0) == {'scale': 1.35, 'alpha': 0., 'blur_px': 28.}
    assert m.slam(.18, 0) == {'scale': 1., 'alpha': 1., 'blur_px': 0.}
    two = m.slam(2 / 30, 0)
    assert two['blur_px'] < 3 and two['alpha'] > .9                        # the smear is gone two frames in
    assert m.pop(0, 0) == {'scale': 0., 'alpha': 0., 'lift': 0.}
    assert m.pop(1, 0) == {'scale': 1., 'alpha': 1., 'lift': 0.}
    for overshoot in (.08, .15):
        peak = max(m.pop(t / 1000, 0, overshoot=overshoot)['scale'] for t in range(281))
        assert peak == pytest.approx(1 + overshoot, abs=2e-3)
    assert max(m.pop(t / 1000, 0)['lift'] for t in range(281)) == pytest.approx(1)
    early, late = m.letter_cascade(5, .05, 0), m.letter_cascade(5, 1, 0)
    assert early[0]['alpha'] > 0 and early[4]['alpha'] == 0                 # letter 4 starts 0.14 s in
    assert early[0]['rotation'] * early[1]['rotation'] < 0 or early[1]['alpha'] == 0
    assert all(p == {'scale': 1., 'alpha': 1., 'dy': 0., 'rotation': 0.} for p in late)


def test_typewriter_counts_characters():
    text = 'Hello, world'
    assert [m.typewriter(text, t, 1., cps=10) for t in (0, 1, 1.05, 1.1, 1.55, 9)] == [0, 0, 0, 1, 5, 12]
    assert m.typewriter(text, 1 + 3 / 28, 1.) == 3


def test_ring_layout_puts_the_text_round_a_turning_circle():
    ring = m.ring_layout('ABCDEFGH', (500, 400), 200, 0, 30)
    assert [c for c, *_ in ring] == list('ABCDEFGH')
    assert ring[0][1:] == pytest.approx((500, 200, 0))                      # upright at the top
    assert ring[2][1:] == pytest.approx((700, 400, 90))                     # a quarter round: top faces out
    assert all(math.hypot(x - 500, y - 400) == pytest.approx(200) for _, x, y, _ in ring)
    later = m.ring_layout('ABCDEFGH', (500, 400), 200, 3, 30)               # 3 s at 30 degrees a second
    assert later[0][1:] == pytest.approx((700, 400, 90))
    assert m.ring_layout('AB', (0, 0), 10, 0, 0, start_deg=180)[0][1:] == pytest.approx((0, 10, 180))


# ------------------------------------------------------------------ speed
def test_twenty_boiling_stickers_composite_within_budget():
    """20 die-cut, shadowed ~300 px stickers on a 1080p page, boiling through three poses on twos while they drift:
    under 30 ms a frame on the M4 (not asserted on slower CI runners)."""
    stickers = []
    for k in range(20):
        rng = m.seeded('bench', k)
        art = Image.new('RGBA', (300, 300), (0, 0, 0, 0))
        corners = [(150 + r * math.cos(a), 150 + r * math.sin(a))
                   for a, r in zip(np.linspace(0, 2 * math.pi, 9)[:-1], rng.uniform(90, 148, 8))]
        ImageDraw.Draw(art).polygon(corners, fill=tuple(int(c) for c in rng.integers(40, 220, 3)) + (255,))
        stickers.append((m.Sprite(m.drop_shadow(m.die_cut(art))), rng.uniform((160, 160), (1700, 920))))
    paper = m.paper_texture((1920, 1080), 'kraft', 'bench').convert('RGBA')
    t0 = time.perf_counter()
    for i in range(60):
        frame = paper.copy()
        pose = round(m.on_twos(i / 30) * 15) % 3
        for k, (sprite, (x, y)) in enumerate(stickers):
            j = m.seeded('boil', k, pose)
            dx, dy = j.uniform(-3, 3, 2)
            sprite.draw(frame, x + dx + i, y + dy, scale=1 + j.uniform(-.03, .03), rotation=j.uniform(-4, 4))
    ms = (time.perf_counter() - t0) / 60 * 1000
    print(f'\n20 stickers: {ms:.1f} ms a frame')
    if not os.environ.get('CI'):
        assert ms < 30, f'{ms:.1f} ms a frame'

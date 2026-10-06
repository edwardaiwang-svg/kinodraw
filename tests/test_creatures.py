"""The procedural cast is distinct, readable, and moves continuously in random-access frames."""
from dataclasses import replace
from itertools import combinations
import math
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
import pytest

from kinodraw.engine.creatures import Action, Genome, Palette, from_text_hint, raster, svg
from kinodraw.engine.creatures.actions import ACTIONS, Pose, action_pose, blend, squash_scale, target_response
from kinodraw.engine.creatures.genes import schema
from kinodraw.engine.creatures.life import blink_times, idle_pose
from kinodraw.engine.creatures.rig import build, two_bone


@pytest.fixture
def heroes():
    return (from_text_hint('Pendo', 'golden lion cub playful'),
            from_text_hint('Mara', 'adult tigress orange with black stripes'),
            from_text_hint('King Kojo', 'adult lion father massive black mane scar across the nose'))


def pixels(g, action='idle', t=0, style='flat'):
    return np.asarray(raster(g, action, t, style, height=300))


def part(doc, name):
    return next(e for e in ET.fromstring(doc).iter() if e.attrib.get('data-part') == name)


def test_genes_text_repair_and_director_round_trip(heroes):
    pendo, mara, kojo = heroes
    assert pendo.age == 'baby' and pendo.species == 'lion'
    assert mara.family == 'feline' and mara.species == 'tiger' and mara.sex == 'female'
    assert mara.palette.body == '#E88B32' and 'stripes' in mara.marks
    assert kojo.size == 1.4 and set(kojo.marks) == {'mane_black', 'scar_nose'}
    assert kojo.age == 'adult' and from_text_hint('Lioness', 'golden adult lioness').age == 'adult'
    assert from_text_hint('Wolf', 'adult wolf').species == 'wolf'
    for g in heroes:
        assert Genome.from_dict(g.to_dict()) == g
    repaired = Genome.from_dict({'species': 'tigress', 'size': float('nan'), 'age': 'invalid',
                                 'palette': {'body': '<bad>'}, 'marks': ['mane_black', 'bad']})
    assert repaired.sex == 'female' and repaired.size == 1. and repaired.age == 'adult'
    assert repaired.palette.body == Palette().body and repaired.marks == ('stripes',)
    assert Genome(size=99).repair().size == 1.6
    assert Genome(size=-99).repair().size == .45
    assert 'mane_black' not in replace(kojo, age='baby').repair().marks
    assert 'mane_black' not in replace(kojo, sex='female').repair().marks
    assert set(schema()['required']) <= set(kojo.to_dict())


@pytest.mark.parametrize('style', ['flat', 'line_art'])
def test_determinism_including_out_of_order_frames_and_palette_independence(heroes, style):
    for g in heroes:
        a = pixels(g, 'roar', .8, style)
        pixels(g, 'walk', 7., style)
        b = pixels(g, 'roar', .8, style)
        assert np.array_equal(a, b)
        assert svg(g, 'roar', .8, style) == svg(g, 'roar', .8, style)
        recolored = replace(g, palette=Palette('#BB1234', '#EFEFEF', '#112233'))
        assert build(g).body == build(recolored).body
        assert build(g).tail == build(recolored).tail
        assert idle_pose(g, 4.1) == idle_pose(recolored, 4.1)


def test_squash_preserves_area_in_math_and_actual_render(heroes):
    for amount in np.linspace(-.7, .7, 31):
        sx, sy = squash_scale(float(amount))
        assert abs(sx * sy - 1) < .05
    g = replace(heroes[1], size=.75)
    normal = (pixels(g, Pose())[:, :, 3] > 127).sum()
    for amount in (-.2, .2, .35):
        squashed = (pixels(g, Pose(squash=amount))[:, :, 3] > 127).sum()
        assert abs(squashed / normal - 1) < .05


def test_heroes_have_pairwise_distinct_silhouettes_at_same_scale_and_baby_proportions(heroes):
    # Remove the size advantage: compare actual filled outlines at one fixed origin and scale.
    masks = [pixels(replace(g, size=1.))[:, :, 3] > 127 for g in heroes]
    for a, b in combinations(masks, 2):
        iou = (a & b).sum() / (a | b).sum()
        assert iou < .8, f'silhouette IoU={iou:.3f}'
    cub, tiger, lion = [build(g) for g in heroes]
    assert cub.head_body_ratio > 1.5 * tiger.head_body_ratio
    assert cub.head_body_ratio > 1.5 * lion.head_body_ratio
    assert cub.eye_radius / cub.head.rx > tiger.eye_radius / tiger.head.rx
    assert cub.legs['front_near'].root[1] > tiger.legs['front_near'].root[1]
    assert not cub.mane and not tiger.mane and lion.mane_radius > 2 * lion.head.rx


@pytest.mark.parametrize('name', ACTIONS)
def test_every_action_moves_then_returns_to_the_current_idle_pose(heroes, name):
    g = heroes[0] if name in ('whimper', 'walk', 'hide', 'tremble') else heroes[2]
    if name == 'laugh':
        g = from_text_hint('Hyena', 'adult spotted hyena')
    cue = Action(name, start=.4)
    changed = []
    for fraction in (.15, .35, .55, .78):
        t = cue.start + fraction * cue.seconds
        changed.append(np.count_nonzero(pixels(g, cue, t) != pixels(g, 'idle', t)))
    assert min(changed) > 60
    for t in (0., cue.start, cue.start + cue.seconds, cue.start + cue.seconds + .1):
        assert action_pose(cue, t) == Pose()
        assert np.array_equal(pixels(g, cue, t), pixels(g, 'idle', t))
    # The closing envelope is continuous; the life layer keeps running after the cue.
    t = cue.start + cue.seconds - .001
    assert abs(action_pose(cue, t).head_x) < .05
    assert abs(action_pose(cue, t).squash) < .001


def test_breathing_changes_the_chest_and_heavy_breath_comes_from_the_mouth(heroes):
    g = heroes[2]
    times = np.linspace(0, 4., 33)
    values = [float(part(svg(g, t=float(t)), 'chest').attrib['ry']) for t in times]
    assert (max(values) - min(values)) / np.mean(values) > .045
    heavy = Action('breathe_heavy')
    t = .9
    p = action_pose(heavy, t)
    assert p.puffs > .2 and abs(p.breath) > .025
    doc = svg(g, heavy, t)
    mouth = build(g, p, t).parts['mouth']
    puff = part(doc, 'breath_puff')
    assert float(puff.attrib['cx']) > mouth[0]
    assert abs(float(puff.attrib['cy']) - mouth[1]) < 20
    assert 'lungs' not in doc


def test_semantic_face_coat_and_action_details_render(heroes):
    for g in heroes:
        doc = svg(g)
        for name in ('body', 'chest', 'head', 'nose', 'eye', 'muzzle', 'whisker'):
            assert part(doc, name) is not None
        assert 'clip-path="url(#coat)"' in doc
    roar = svg(heroes[2], 'roar', .9)
    assert len([e for e in ET.fromstring(roar).iter() if e.attrib.get('data-part') == 'canine']) == 4
    for name in ('jaw', 'mouth', 'sound_arc', 'scar_nose'):
        assert part(roar, name) is not None
    swipe = svg(heroes[2], 'swipe', .55)
    assert part(swipe, 'motion_line') is not None and part(swipe, 'swipe_smear') is not None
    laugh = svg(from_text_hint('Hyena', 'hyena'), 'laugh', 1.)
    assert part(laugh, 'cackle') is not None


def test_life_blinks_fidgets_and_spring_chains_are_seeded(heroes):
    g = heroes[0]
    times = blink_times(g, 30)
    assert times == blink_times(g, 30) and 3 <= times[0] <= 6
    assert all(3 <= b - a <= 6 for a, b in zip(times, times[1:]))
    assert idle_pose(g, times[0] + .08).blink == 1.
    assert idle_pose(g, times[0] - .01).blink == 0.
    assert not np.array_equal(pixels(g, t=times[0] - .01), pixels(g, t=times[0] + .08))
    a, b = build(g, idle_pose(g, 0), 0), build(g, idle_pose(g, 1), 1)
    assert a.tail != b.tail and len(a.tail) == 6
    for x, y in zip(a.tail, a.tail[1:]):
        assert math.hypot(y[0] - x[0], y[1] - x[1]) == pytest.approx(13.)
    lion_a, lion_b = build(heroes[2], t=0), build(heroes[2], action_pose('roar', .9), .9)
    assert lion_a.mane != lion_b.mane


def test_nudge_receiver_blending_and_two_bone_ik(heroes):
    cue = Action('nudge')
    assert target_response(cue, .8) != Pose()
    assert target_response(cue, cue.seconds) == Pose()
    assert not np.array_equal(pixels(heroes[0], target_response(cue, .8), .8), pixels(heroes[0], t=.8))
    a, b = Pose(head_x=-10, legs=(1., 2., 3., 4.)), Pose(head_x=10, legs=(3., 4., 5., 6.))
    assert blend(a, b, .5) == Pose(head_x=0, legs=(2., 3., 4., 5.))
    joint, end = two_bone((0, 0), (25, 10), 20, 20)
    assert end == pytest.approx((25, 10))
    assert math.hypot(*joint) == pytest.approx(20)
    assert math.hypot(end[0] - joint[0], end[1] - joint[1]) == pytest.approx(20)


@pytest.mark.parametrize('hint,kind', [('adult human woman', 'humanoid'), ('baby human boy', 'humanoid'),
                                     ('adult wolf', 'quadruped'), ('blob', 'blob')])
def test_other_semantic_families_share_the_motion_contract(hint, kind):
    g = from_text_hint('Actor', hint)
    rig = build(g)
    assert g.kind == kind
    assert {'head', 'jaw', 'mouth', 'nose', 'ear_left', 'eye_left'} <= set(rig.parts)
    if kind == 'humanoid':
        assert len(rig.legs) == 2 and len(rig.arms) == 2
    elif kind == 'quadruped':
        assert len(rig.legs) == 4
    assert not np.array_equal(pixels(g, 'look', .8), pixels(g, t=.8))
    with pytest.raises(ValueError):
        svg(g, 'unknown')


def test_tapered_limbs_have_masses_bent_joints_and_cub_paws(heroes):
    for g in heroes:
        rig = build(g)
        assert rig.legs['front_near'].joint[0] < rig.legs['front_near'].root[0]
        assert rig.legs['hind_near'].joint[0] > rig.legs['hind_near'].root[0]
        assert rig.legs['front_near'].end[0] < rig.legs['front_near'].root[0]
        for leg in rig.legs.values():
            assert leg.end[1] + 1 + leg.width * .40 == pytest.approx(0.)
        doc = svg(g, style='line_art')
        assert part(doc, 'front_near').attrib['fill'] == 'white'
        assert part(doc, 'front_near_mass') is not None
        assert part(doc, 'front_near_joint') is not None
        assert float(part(doc, 'front_near').attrib['stroke-width']) > 3 * float(part(doc, 'toe').attrib['stroke-width'])
    paw = part(svg(heroes[0]), 'front_near_paw')
    assert float(paw.attrib['rx']) > build(heroes[0]).legs['front_near'].width * .85
    assert part(svg(heroes[1]), 'leg_stripe') is not None


@pytest.mark.parametrize('name', ['walk', 'run'])
def test_gait_lifts_diagonal_paws_and_bobs_the_body(heroes, name):
    poses = [action_pose(name, t) for t in (.55, .65, .80, .95)]
    lifts = []
    for p in poses:
        assert p.legs[0] == pytest.approx(p.legs[3])
        assert p.legs[1] == pytest.approx(p.legs[2])
        assert p.legs[0] == pytest.approx(-p.legs[1])
        assert p.knees[0] == pytest.approx(p.knees[3])
        assert p.knees[1] == pytest.approx(p.knees[2])
        assert sum(k < -1 for k in p.knees) == 2
        rig = build(heroes[1], p)
        heights = [leg.end[1] + p.dy + 1 + leg.width * .40 for leg in rig.legs.values()]
        lifts.append(max(heights) - min(heights))
        assert max(heights) == pytest.approx(0., abs=.01)
    assert max(lifts) > (18 if name == 'walk' else 30)
    assert max(p.dy for p in poses) - min(p.dy for p in poses) > 2
    cue = Action(name, start=5.)
    shifted = action_pose(cue, 5.65)
    assert shifted.legs == pytest.approx(poses[1].legs)
    assert shifted.knees == pytest.approx(poses[1].knees)
    assert shifted.dy == pytest.approx(poses[1].dy)


def test_storybook_faces_and_species_surfaces(heroes):
    cub, tiger, lion = heroes
    for g in heroes:
        doc = svg(g)
        for name in ('inner_ear', 'iris', 'pupil', 'eye_highlight', 'nose_top', 'chin', 'belly', 'underside_shade', 'rim_highlight'):
            assert part(doc, name) is not None
    assert 37 < build(tiger).head.rx < 41
    assert part(svg(cub), 'forehead_tuft') is not None
    assert part(svg(tiger), 'cheek_ruff').attrib['fill'] == '#FFF1D8'
    assert part(svg(tiger), 'lash') is not None
    lioness = from_text_hint('Lioness', 'adult female lioness')
    assert not build(lioness).mane and build(lioness).body.ry < build(lion).body.ry
    mane = ET.fromstring(svg(lion))
    assert sum(e.attrib.get('data-part') == 'mane_layer' for e in mane.iter()) == 2
    assert part(svg(lion), 'chest_mane') is not None
    scar = part(svg(lion), 'scar_nose').attrib['d'].replace('M', '').replace('L', ' ').split()
    x1, y1, x2, y2 = map(float, scar)
    assert x1 > x2 and y1 < build(lion).head.rx * -.4 and y2 > build(lion).head.rx * .4


def test_roar_anticipation_hinged_jaw_fierce_eyes_and_brief_shake(heroes):
    cue = Action('roar')
    down, back, hit = [action_pose(cue, u * cue.seconds) for u in (.10, .24, .48)]
    assert down.head_y > 15 and down.jaw == 0
    assert back.head_x < -5 and back.head_y < -10
    assert hit.head_x > 20 and hit.head_y < -9 and hit.lean > 15
    assert hit.fierce > .9 and hit.mane > 10 and abs(hit.mane_lag) > .1
    doc = svg(heroes[2], cue, .48 * cue.seconds)
    hinge = part(doc, 'jaw_hinge')
    assert float(hinge.attrib['data-angle']) >= 40
    assert sum(e.attrib.get('data-part') == 'canine' for e in hinge.iter()) == 2
    assert part(doc, 'tongue') is not None
    assert sum(e.attrib.get('data-part') == 'sound_arc' for e in ET.fromstring(doc).iter()) == 3
    early = part(svg(heroes[2], cue, .44 * cue.seconds), 'sound_arc').attrib['d']
    later = part(svg(heroes[2], cue, .60 * cue.seconds), 'sound_arc').attrib['d']
    assert early != later
    shake = action_pose(cue, .43 * cue.seconds)
    assert shake.screen_shake > 3 and action_pose(cue, .70 * cue.seconds).screen_shake == 0
    metadata = next(e for e in ET.fromstring(svg(heroes[2], cue, .43 * cue.seconds)).iter() if e.tag.endswith('metadata'))
    assert float(metadata.attrib['data-screen-shake']) == pytest.approx(shake.screen_shake, abs=.001)
    assert abs(action_pose(cue, cue.seconds - .0001).mane_lag) < .001
    for t in (0., 1., 1.5):
        alpha = pixels(heroes[2], cue, t)[:, :, 3]
        assert not any(edge.any() for edge in (alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]))


def test_hyena_slope_thick_neck_dark_muzzle_and_cackle():
    g = from_text_hint('Hyena', 'adult spotted hyena')
    rig = build(g)
    assert rig.legs['front_near'].root[1] < rig.legs['hind_near'].root[1] - 25
    doc = svg(g)
    assert part(doc, 'muzzle').attrib['fill'] == '#493F38'
    assert float(part(doc, 'neck').attrib['stroke-width']) > 50
    assert part(doc, 'back_fringe').attrib['fill'] == '#3E3531'
    p = action_pose('laugh', .85)
    assert p.head_pitch < -30 and p.jaw > .5 and p.dy < -2
    assert part(svg(g, 'laugh', .9), 'cackle') is not None


def test_whimper_stays_closed_and_nudge_reaches_cub_then_springs_back(heroes):
    cub, _, lion = heroes
    p = action_pose('whimper', .8)
    assert p.jaw == 0 and p.worry > .9 and p.ears > 60 and p.crouch > 15
    assert p.dx != 0
    doc = svg(cub, 'whimper', .8)
    assert part(doc, 'mouth_line') is not None and 'data-part="tear"' not in doc
    ear, upright = part(doc, 'ear_shell'), part(svg(cub), 'ear_shell')
    assert float(ear.attrib['ry']) < float(upright.attrib['ry']) * .6
    assert float(ear.attrib['cy']) > float(upright.attrib['cy']) + 10
    nudge = Action('nudge')
    p = action_pose(nudge, .5 * nudge.seconds)
    nose = build(lion, p).parts['nose'][1] * lion.size
    cub_nose = build(cub).parts['nose'][1] * cub.size
    assert abs(nose - cub_nose) < 10
    reactions = [target_response(nudge, u * nudge.seconds) for u in (.48, .65, .85)]
    assert reactions[0].dx > 0 and reactions[1].dx < 0
    assert abs(reactions[-1].dx) < abs(reactions[0].dx)
    assert reactions[0].lean != 0 and reactions[0].head_pitch != 0


# --- A5 action strips: Pendo's small-cub actions must read, and gait travel is added once, by the scene ---
PREVIEW_FRACTIONS = (0., .14, .28, .42, .56, .70, .84, 1.)  # scripts/creature_preview.py samples the cue at these


def changed_percent_per_step(g, name):
    """Percent of the 450x300 frame whose gray level changes by >24 between consecutive preview samples."""
    cue = Action(name)
    frames = []
    for u in PREVIEW_FRACTIONS:
        image = raster(g, cue, u * cue.seconds, height=300)
        paper = Image.new('RGBA', image.size, '#FAF7EF')
        paper.alpha_composite(image)
        frames.append(np.asarray(paper.convert('L'), np.float32))
    return [float((np.abs(a - b) > 24).mean() * 100) for a, b in zip(frames, frames[1:])]


def test_tremble_and_whimper_are_different_poses_and_only_whimper_whimpers(heroes):
    tremble, whimper = Action('tremble'), Action('whimper')
    times = [u * tremble.seconds for u in PREVIEW_FRACTIONS[1:-1]]
    assert any(action_pose(tremble, t) != action_pose(whimper, t) for t in times)
    assert all(action_pose(tremble, t).sound == 0 for t in np.linspace(0, tremble.seconds, 60))
    assert min(action_pose(whimper, t).sound for t in np.linspace(0, whimper.seconds, 60)) < -.8
    assert 'whimper_mark' not in svg(heroes[0], tremble, .5 * tremble.seconds)
    assert 'whimper_mark' in svg(heroes[0], whimper, .5 * whimper.seconds)
    # The shiver is whole-body and beats at video rates: seen at 30 fps a full cycle takes about four frames (two sign flips).
    shiver = [action_pose(tremble, k / 30 + .3).dx for k in range(60)]
    flips = sum(1 for a, b in zip(shiver, shiver[1:]) if a * b < 0)
    assert 24 <= flips <= 34
    assert max(abs(x) for x in shiver) > 7


def test_tremble_shiver_shows_at_every_preview_sample_and_scales_with_size(heroes):
    cue = Action('tremble')
    shown = [action_pose(cue, u * cue.seconds).dx for u in PREVIEW_FRACTIONS[1:-1]]
    assert min(abs(x) for x in shown) > 1., shown  # the old 14-cycle shake aliased to 0.04 of a cycle per sample
    assert max(shown) > 8 and min(shown) < -8  # and the samples reach both sides
    cub = heroes[0]
    big = replace(cub, size=1.4)
    t = .3 * cue.seconds
    def x_of(genome):
        return float(ET.fromstring(svg(genome, cue, t)).find('.//{*}g').attrib['transform'].split('(')[1].split()[0])
    assert abs(x_of(big) - 300) > 1.5 * abs(x_of(cub) - 300) > 0


@pytest.mark.parametrize('name, floor', [('whimper', 2.2), ('tremble', 2.6), ('walk', 2.9)])
def test_cub_actions_show_frame_to_frame_motion_at_every_step(heroes, name, floor):
    # metrics-before.json: Pendo strips changed 1.7-1.9% a step (cells with label text) against 5-11% for
    # Kojo; rendered without labels the old whimper/tremble middle steps changed 0.4-0.7%. Every step between
    # the first and last sample must now exceed the floor, set above the old minimum and below the new one.
    steps = changed_percent_per_step(heroes[0], name)[1:-1]
    assert min(steps) > floor - 1., steps
    assert sum(steps) / len(steps) > floor, steps


def test_hide_drops_in_holds_low_and_reads_as_hiding(heroes):
    cue = Action('hide')
    idle = action_pose('idle', 0.)
    early, hold = [action_pose(cue, u * cue.seconds) for u in (.12, .5)]
    assert 0 < early.crouch < hold.crouch  # a clear transition in
    held = [action_pose(cue, u * cue.seconds) for u in (.4, .5, .6)]
    assert max(p.crouch for p in held) - min(p.crouch for p in held) < 1  # then a hold
    assert hold.crouch > 30 and hold.ears > 80 and hold.head_pitch > 30 and hold.head_x < -20
    assert hold.worry > .9 and hold.squash < .15 and hold.lean < 0 and idle.crouch == 0
    steps = changed_percent_per_step(heroes[0], 'hide')[1:-1]
    assert max(steps) > 3., steps  # the drop is visible at cub scale (old maximum 2.3)


@pytest.mark.parametrize('name', ['walk', 'run'])
def test_gait_travels_once_through_travel_x_and_never_through_the_pose(name):
    from kinodraw.engine.creatures.actions import travel_x
    cue = Action(name, start=2.)
    assert all(action_pose(cue, 2. + f * cue.seconds).dx == 0 for f in np.linspace(.05, .95, 19))
    path = [travel_x(cue, 2. + f * cue.seconds) for f in np.linspace(-.1, 1.2, 27)]
    assert path[0] == 0 and all(b >= a for a, b in zip(path, path[1:]))
    assert path[-1] == path[-2] > (150 if name == 'walk' else 280)  # carried, then held: nothing snaps back
    assert travel_x(Action('roar'), 1.) == 0 and travel_x(Action(name, intensity=0.), 1.) == 0


def test_scene_composer_moves_a_walking_actor_by_travel_x(tmp_path, monkeypatch):
    import dataclasses
    from kinodraw.engine import hybrid
    from test_hybrid import fixture, save_production
    board, plan, tl = fixture(tmp_path)
    plan['scenes'][1].update(composition='left_third', treatment='character', elements=[], camera='static',
                             text={'kind': 'none', 'ref': ''})
    prod = save_production(tmp_path, board, plan, tl)
    span = prod.spans[1]
    key = span.actors[0]
    cue = Action('walk', 0., duration=span.end - span.start)
    prod.spans[1] = span = dataclasses.replace(span, actors=(key,), actions=((key, cue, None),))
    heights = []

    def block(g, pose, t, height=300, **k):
        heights.append(height)
        return Image.new('RGBA', (60, 40), (255, 0, 255, 255))
    monkeypatch.setattr(hybrid, 'raster', block)

    def center_x(local):
        frame = np.asarray(prod._frame(span, span.start + local))
        columns = np.nonzero((frame == (255, 0, 255)).all(axis=2).any(axis=0))[0]
        return (columns.min() + columns.max()) / 2

    moved = center_x(span.end - span.start - .01) - center_x(.01)
    expected = prod._travel(span, key, span.end - span.start - .01, heights[-1]) - prod._travel(span, key, .01, heights[0])
    assert heights[0] == heights[-1] and expected > 0 and moved == pytest.approx(expected, abs=2)


@pytest.mark.parametrize('composition,names,intensity', [
    ('center', ('kojo',), 1.),
    ('right_third', ('kojo',), 1 / 3),
    ('center', ('kojo', 'pendo'), 1.),
])
@pytest.mark.parametrize('verb', ['walk', 'run'])
@pytest.mark.parametrize('camera', ['static', 'pan_left'])      # pan_left moves the whole picture right
def test_scene_travel_keeps_the_sprite_inside_the_frame(tmp_path, monkeypatch, composition, names, intensity, verb,
                                                        camera):
    import dataclasses
    from kinodraw.engine import hybrid
    from test_hybrid import fixture, save_production
    board, plan, tl = fixture(tmp_path)
    plan['scenes'][1].update(composition=composition, treatment='character', elements=[], camera=camera,
                             text={'kind': 'none', 'ref': ''})
    prod = save_production(tmp_path, board, plan, tl)
    span = prod.spans[1]
    duration = span.end - span.start
    keys = tuple(next(k for k in prod.cast if name in k) for name in names)
    cues = tuple((key, Action(verb, 0., duration=duration, intensity=intensity), None) for key in keys)
    span = dataclasses.replace(span, actors=keys, actions=cues)
    w = prod.size[0]
    real = hybrid.raster

    def sprite_columns(local):
        monkeypatch.setattr(hybrid, 'raster', real)
        frame = np.asarray(prod._frame(span, span.start + local)).astype(int)
        monkeypatch.setattr(hybrid, 'raster', lambda g, pose, t, height=300, **k: Image.new('RGBA', (4, 4), (0, 0, 0, 0)))
        empty = np.asarray(prod._frame(span, span.start + local)).astype(int)
        columns = np.nonzero((np.abs(frame - empty).sum(axis=2) > 30).any(axis=0))[0]
        return columns.min(), columns.max()

    start_left, _ = sprite_columns(.01)
    for local in (.01, duration * .5, duration * .9, duration - .01):
        left, right = sprite_columns(local)
        # Travel only carries actors rightward and must stop short of the frame edge; the slot layout is not its concern.
        assert right <= w - 1 - .02 * w and left >= min(start_left, .02 * w) - 1, (local, left, right)

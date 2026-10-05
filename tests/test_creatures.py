"""The procedural cast is distinct, readable, and moves continuously in random-access frames."""
from dataclasses import replace
from itertools import combinations
import math
import xml.etree.ElementTree as ET

import numpy as np
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
    assert len([e for e in ET.fromstring(roar).iter() if e.attrib.get('data-part') == 'canine']) == 2
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

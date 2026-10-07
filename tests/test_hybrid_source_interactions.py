"""Source participants and actual composed bodies, independent of showcase names."""
import json

import numpy as np
import pytest

from kinodraw.engine import render
from kinodraw.engine.creatures import Action
from kinodraw.engine.creatures.actions import action_pose
from test_hybrid_character_motion import Canvas, production

# Story characters are preset doodles now; these checks cover the procedural rig path.
pytestmark = pytest.mark.usefixtures('procedural_rig')


def saved_scene(tmp_path, text, verbs, names=('Nia', 'Sora', 'Taro')):
    prod, board, plan, tl = production(tmp_path, [text], names, floor='still')
    child, mother, father = [n.casefold() for n in names]
    scene = plan['scenes'][-1]
    bid = scene['beat_ids'][0]
    scene['elements'] = [{'kind': 'cast', 'ref': father}, {'kind': 'cast', 'ref': child}]
    scene['actions'] = [{'actor': actor, 'verb': verb, 'at_beat': bid, 'intensity': 3}
                        for actor, verb in verbs]
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    return render.make_production(board, tl, 'en', tmp_path), tl


@pytest.mark.parametrize('names', [('Nia', 'Sora', 'Taro'), ('Ayo', 'Luma', 'Beko')])
def test_swipe_uses_source_intruder_and_actual_grounded_response(tmp_path, names):
    child, _, father = names
    text = (f'{father} made one massive swipe of his paw, sending the lead hyena away. '
            f'He stood over {child}, unleashing a roar.')
    prod, tl = saved_scene(tmp_path, text, [(father.casefold(), 'swipe')], names)
    span = prod.spans[-1]
    actor, action, target = next(e for e in span.actions if e[1].name == 'swipe')
    assert prod.cast[target].species == 'hyena'
    assert target != child.casefold()
    assert target in span.actor_layout
    assert span.actor_layout[actor][1] == span.actor_layout[target][1]
    assert span.actor_layout[actor][4] == span.actor_layout[target][4]
    timing = tl['beats'][span.spec['beat_ids'][0]]
    assert span.start + action.start == timing['start'] + timing['char_times'][text.index('swipe')]
    before, after = Canvas(prod.size), Canvas(prod.size)
    prod._actors(span, action.start, before)
    prod._actors(span, action.start + action.seconds * .9, after)
    # Interaction group is drawn before the independent cub's group.
    assert after.boxes[1][0] > before.boxes[1][0] + 60
    assert not np.array_equal(np.asarray(before.image), np.asarray(after.image))


def test_swipe_does_not_borrow_a_later_sentence_target(tmp_path):
    prod, _ = saved_scene(tmp_path, 'Taro swiped at the air. Nia watched.', [('taro', 'swipe')])
    assert next(t for _, a, t in prod.spans[-1].actions if a.name == 'swipe') is None


def test_source_swipe_adds_its_named_receiver_when_saved_stage_omits_it(tmp_path):
    prod, _ = saved_scene(tmp_path, 'Taro swiped at Sora. Nia watched.', [('taro', 'swipe')])
    span = prod.spans[-1]
    assert next(t for _, a, t in span.actions if a.name == 'swipe') == 'sora'
    assert 'sora' in span.actor_layout


@pytest.mark.parametrize('names', [('Nia', 'Sora', 'Taro'), ('Ayo', 'Luma', 'Beko')])
def test_hide_adds_established_mother_and_moves_behind_her_paws(tmp_path, names):
    child, mother, father = names
    text = f'{father} walked by. {child} hid behind her mother\'s paws.'
    prod, _ = saved_scene(tmp_path, text, [(child.casefold(), 'hide')], names)
    span = prod.spans[-1]
    actor, action, target = span.actions[0]
    assert target == mother.casefold()
    assert target in span.actors and prod.cast[target].species == 'tiger'
    assert span.actor_layout[actor][4] == span.actor_layout[target][4]
    before, hidden = Canvas(prod.size), Canvas(prod.size)
    prod._actors(span, action.start, before)
    prod._actors(span, action.start + action.seconds * .55, hidden)
    # The mother is composed last as real foreground cover, with the crouched cub still visible.
    cub, parent = hidden.boxes[-2:]
    assert max(cub[0], parent[0]) < min(cub[2], parent[2])
    assert hidden.boxes[-2] != before.boxes[-2]


@pytest.mark.parametrize('text, verb', [
    ('The two spotted hyenas laughed at Nia.', 'laugh'),
    ('The two hyenas drew closer, baring their sharp teeth.', 'bare_teeth'),
])
def test_source_group_gets_legible_grounded_body_actions(tmp_path, text, verb):
    prod, _ = saved_scene(tmp_path, text, [])
    span = prod.spans[-1]
    hyenas = [key for key in span.actors if prod.cast[key].species == 'hyena']
    assert len(hyenas) == 2
    assert all(key in span.actor_layout for key in hyenas)
    assert len({slot[1] for slot in span.actor_layout.values()}) == 1
    assert {key for key, a, _ in span.actions if a.name == verb} == set(hyenas)
    action = next(a for _, a, _ in span.actions if a.name == verb)
    before, peak = Canvas(prod.size), Canvas(prod.size)
    prod._actors(span, action.start, before)
    prod._actors(span, action.start + action.seconds * .55, peak)
    assert min(b[3] - b[1] for b in peak.boxes[-2:]) >= 150
    assert not np.array_equal(np.asarray(before.image), np.asarray(peak.image))


def test_negated_group_actions_stay_absent(tmp_path):
    prod, _ = saved_scene(tmp_path, 'The two hyenas never laughed or bared their teeth.', [])
    assert not any(a.name in ('laugh', 'bare_teeth') for _, a, _ in prod.spans[-1].actions)


def test_group_does_not_borrow_another_subjects_actions(tmp_path):
    prod, _ = saved_scene(tmp_path, 'Two hyenas watched Nia laugh and bare her teeth.', [])
    assert not any(a.name in ('laugh', 'bare_teeth') for _, a, _ in prod.spans[-1].actions)


def test_continued_source_threat_keeps_the_cub_as_approach_destination(tmp_path):
    prod, board, plan, tl = production(tmp_path, [
        'Nia watched two hyenas, their eyes locked onto the unprotected cub.',
        'The hyenas drew closer, baring their sharp teeth. Taro burst through the fog.'], floor='still')
    scene = plan['scenes'][-1]
    scene['elements'] = [{'kind': 'cast', 'ref': 'taro'}]
    scene['actions'] = []
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = prod.spans[-1]
    assert 'nia' in span.actors
    walkers = [(key, a, target) for key, a, target in span.actions if a.name == 'walk']
    assert len(walkers) == 2 and all(target == 'nia' for _, _, target in walkers)
    before, approached = Canvas(prod.size), Canvas(prod.size)
    action = walkers[0][1]
    prod._actors(span, action.start, before)
    prod._actors(span, action.start + action.seconds, approached)
    assert approached.boxes[1][0] > before.boxes[1][0] + 30
    assert approached.boxes[1][2] < approached.boxes[-1][0]


def test_source_threat_faces_the_child_and_stops_before_hiding_its_face(tmp_path):
    prod, _ = saved_scene(tmp_path, 'Two hyenas emerged, watching the unprotected cub Nia.', [])
    span = prod.spans[-1]
    walkers = [(key, a, target) for key, a, target in span.actions if a.name == 'walk']
    child_x = span.actor_layout['nia'][0]
    leftward = [(key, a) for key, a, target in walkers if span.actor_layout[key][0] > child_x]
    assert leftward and all(span.actor_layout[key][3] for key, _ in leftward)
    canvas = Canvas(prod.size)
    action = leftward[0][1]
    prod._actors(span, action.start + action.seconds, canvas)
    # Separate groups are drawn in stage order: father, cub, representatives.
    child, *hyenas = canvas.boxes[1:]
    assert all(box[0] > child[2] for box in hyenas)


def test_low_intensity_fear_remains_a_shiver_rather_than_a_whimper_crouch():
    tremble, whimper = Action('tremble', intensity=1/3), Action('whimper', intensity=1/3)
    times = np.linspace(.25 * tremble.seconds, .7 * tremble.seconds, 32)
    shaking = [action_pose(tremble, float(t)) for t in times]
    crying = [action_pose(whimper, float(t)) for t in times]
    assert np.ptp([p.dx for p in shaking]) > 30
    assert max(p.crouch for p in shaking) < 6
    assert min(p.crouch for p in crying) > 10
    assert min(p.ears for p in crying) > 50
    assert all(p.sound == 0 for p in shaking)
    assert all(p.sound < -.15 and p.jaw == 0 for p in crying)

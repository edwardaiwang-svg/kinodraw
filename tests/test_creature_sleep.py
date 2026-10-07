"""Sleep must look asleep after its cue and wake continuously in random-access frames."""
import copy
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline
from kinodraw.engine.creatures import Action, from_text_hint, raster, svg
from kinodraw.engine.creatures.actions import Pose, action_pose, cue_pose
from kinodraw.engine.creatures.life import pose_at
from kinodraw.engine.creatures.rig import build

# Story characters are preset doodles now; these checks cover the procedural rig path.
pytestmark = pytest.mark.usefixtures('procedural_rig')


@pytest.mark.parametrize('hint', ['baby lion cub', 'adult tigress', 'adult wolf', 'adult person'])
def test_sleep_raster_has_closed_eyes_resting_body_and_visible_breathing(hint):
    g = from_text_hint('Resting', hint)
    cue = Action('sleep', start=.4, intensity=1/3)
    assert action_pose(cue, .4) == Pose()
    assert np.array_equal(np.asarray(raster(g, cue, .4)), np.asarray(raster(g, 'idle', .4)))
    t = cue.start + 6.25
    p = pose_at(g, cue, t)
    assert p.sleep == p.blink == 1.
    doc = ET.fromstring(svg(g, cue, t))
    eyes = [e for e in doc.iter() if e.attrib.get('data-part') == 'eye']
    assert len(eyes) == 2 and all(e.tag.endswith('path') for e in eyes)
    assert not any(e.attrib.get('data-part') == 'pupil' for e in doc.iter())
    resting, standing = build(g, p, t), build(g)
    assert resting.head.y > standing.head.y + 15
    if g.kind == 'humanoid':
        assert resting.body.rx > resting.body.ry
        assert resting.head.x > resting.body.x + resting.body.rx
    else:
        assert resting.body.y > standing.body.y or g.age == 'baby'
        assert all(leg.root[1] > standing.legs[name].root[1] for name, leg in resting.legs.items())
        assert max(point[1] for point in resting.tail) > max(point[1] for point in standing.tail)
        for a, b, awake_a, awake_b in zip(resting.tail, resting.tail[1:], standing.tail, standing.tail[1:]):
            assert np.linalg.norm(np.subtract(a, b)) == pytest.approx(np.linalg.norm(np.subtract(awake_a, awake_b)))
    a = np.asarray(raster(g, cue, t, height=400))
    b = np.asarray(raster(g, cue, t + 2.5, height=400))
    assert np.count_nonzero(a != b) > 80
    for sample in (t + 2.5, .7, 3., t):
        first = raster(g, cue, sample).tobytes()
        raster(g, cue, 11.)
        assert raster(g, cue, sample).tobytes() == first


def test_sleep_holds_without_cue_end_pop_and_wakes_on_next_actor_cue():
    g = from_text_hint('Resting', 'adult wolf')
    sleep, wake = Action('sleep', 1.), Action('walk', 7.)
    cues = [sleep, wake]
    end = sleep.start + sleep.seconds
    a, b = [pose_at(g, sleep, t) for t in (end - .0001, end + .0001)]
    assert a.sleep == b.sleep == 1.
    assert abs(a.breath - b.breath) < .0001
    assert cue_pose(sleep, cues, 7.).sleep == 1.
    assert .4 < cue_pose(sleep, cues, 7.3).sleep < .6
    assert cue_pose(sleep, cues, 7.6).sleep == 0.
    assert cue_pose(sleep, cues, 7.0001).sleep > .999
    assert np.array_equal(np.asarray(raster(g, cues, 8.)), np.asarray(raster(g, wake, 8.)))


def sleeping_story(tmp_path, closing='Lumi curled up tightly against her father\'s warm belly, fast asleep.'):
    source = '# Rest\n\nLumi, a tiny lion cub, lived with her father, the great King Orion.\n\n' + closing
    board = script.build(ingest.read(source), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    child = next(c for c in plan['cast'] if c['name'] == 'Lumi')
    parent = next(c for c in plan['cast'] if c['name'] == 'Orion')
    child.update(age='baby', size=.55)
    parent.update(age='adult', size=1.3)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    scene = plan['scenes'][-1]
    scene.update(treatment='character', elements=[{'kind': 'cast', 'ref': child['id']},
                                                {'kind': 'cast', 'ref': parent['id']}],
                 actions=[{'actor': child['id'], 'verb': 'sleep', 'at_beat': board['beats'][-1]['id'], 'intensity': 1}])
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    return render.make_production(board, tl, 'en', tmp_path), child['id'], parent['id']


def test_sleep_source_parent_contact_and_closing_scene_random_access(tmp_path):
    prod, child, parent = sleeping_story(tmp_path)
    span = prod.spans[-1]
    actor, action, target = span.actions[0]
    assert (actor, action.name, target) == (child, 'sleep', parent)
    assert len(prod._cast_groups(span)) == 1
    assert prod.cast[child].size < prod.cast[parent].size
    assert not any('sleep uses' in warning for warning in prod.warnings)
    text = prod.by_id[span.spec['beat_ids'][-1]]['spoken']
    beat = prod.tl['beats'][span.spec['beat_ids'][-1]]
    assert action.start == pytest.approx(beat['start'] - span.start + beat['char_times'][text.index('curled')])
    times = (span.start + action.start + .1, span.end - .2, span.start + action.start + 1.)
    frames = [prod.frame(t).tobytes() for t in times]
    assert len(set(frames)) == 3
    for t, frame in reversed(list(zip(times, frames))):
        assert prod.frame(t).tobytes() == frame


@pytest.mark.parametrize('closing', ['Lumi fell asleep. Orion stood nearby.',
    'Lumi curled up tightly against her father\'s belly, asleep.'])
def test_sleep_contact_requires_explicit_against_phrase_and_established_parent(tmp_path, closing):
    prod, child, _ = sleeping_story(tmp_path, closing)
    beat = copy.deepcopy(prod.by_id[prod.spans[-1].spec['beat_ids'][-1]])
    if 'against' in closing:
        prod.by_id = {beat['id']: beat}  # No established parent relation remains.
    assert prod._sleep_contact(beat, child) is None


@pytest.mark.parametrize('closing', [
    "Lumi curled up against her father's belly, but was not asleep.",
    "Lumi never curled up against her father's belly, fast asleep.",
    "Lumi curled up against Orion's belly while Orion fell asleep.",
    "Lumi curled up against Orion's belly, while Orion was fast asleep.",
    "Lumi curled up against Orion's belly, not fast asleep.",
])
def test_sleep_contact_never_borrows_a_negated_or_other_actors_sleep(tmp_path, closing):
    prod, child, _ = sleeping_story(tmp_path, closing)
    beat = prod.by_id[prod.spans[-1].spec['beat_ids'][-1]]
    assert prod._sleep_contact(beat, child) is None
    assert not any(actor == child and action.name == 'sleep' for actor, action, _ in prod.spans[-1].actions)

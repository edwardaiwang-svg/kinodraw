"""Generated launch props and their readable, continuously moving foreground."""
import json
import math
import pickle

import numpy as np

import pytest

from kinodraw import ingest, script
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline
from kinodraw.engine.skin import for_look
from kinodraw.engine.source_diagrams import Diagram, PanelMotion
from kinodraw.engine.bold import MotionElement, MotionScene
from kinodraw.engine.bold.render import _raster, element_pose, scene_svg


ART = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
       '<rect width="100" height="100" fill="#147d78" stroke="#18313b"/>'
       '<rect x="10" y="10" width="80" height="80" style="fill:#f7f5ef;stroke:#f4b942"/></svg>')


def test_generated_art_preserves_authored_fill_and_stroke_contrast():
    scene = MotionScene(elements=[MotionElement(kind='picture', svg=ART, preserve_svg_palette=True)],
                        motion_floor=0, glow=0)
    doc = scene_svg(scene, 1)
    for color in ('#147d78', '#18313b', '#f7f5ef', '#f4b942'):
        assert color in doc
    # Existing silhouette/library styling remains opt-in through the default.
    scene.elements[0].preserve_svg_palette = False
    assert '#f7f5ef' not in scene_svg(scene, 1)


def test_palette_preservation_does_not_admit_external_resources():
    art = ART.replace('fill="#147d78"', 'fill="url(https://example.com/paint)"')
    scene = MotionScene(elements=[MotionElement(kind='picture', svg=art, preserve_svg_palette=True)])
    with pytest.raises(ValueError, match='external resources'):
        scene_svg(scene, 1)


def test_generated_palette_survives_native_worker_pickle():
    scene = MotionScene(elements=[MotionElement(kind='picture', svg=ART, preserve_svg_palette=True)])
    assert scene_svg(pickle.loads(pickle.dumps(scene)), 1) == scene_svg(scene, 1)


@pytest.mark.parametrize('preset', ['word_pop', 'cascade'])
def test_multiline_kinetic_copy_keeps_both_lines_inside_its_width(preset):
    scene = MotionScene(elements=[MotionElement(text='Introducing our new app: one\nworkspace for your team\'s ideas.',
                        preset=preset, width=1400, size=96)], motion_floor=0, glow=0)
    alpha = _raster(scene_svg(scene, 5, 'text'), 1920, 1080, text=True)[..., 3]
    columns = np.flatnonzero(alpha.max(axis=0))
    assert columns[-1]-columns[0] < 1400
    assert alpha[:540].any() and alpha[540:].any()
    assert not alpha[540].any(), 'line breaks were collapsed into one overflowing row'


def test_source_copy_and_generated_prop_have_separate_vertical_space(tmp_path):
    board = script.build(ingest.read('# Workspace\n\nIntroducing our new app: one workspace for your team\'s ideas.'), story='showcase')
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='drifting')
    scene = plan['scenes'][-1]
    scene.update(treatment='motion', composition='center',
                 elements=[{'kind': 'text', 'ref': scene['beat_ids'][0]}, {'kind': 'picture', 'ref': 'gen-workspace'}],
                 text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    (tmp_path/'doodles').mkdir()
    (tmp_path/'doodles/gen-workspace.svg').write_text(ART)
    (tmp_path/'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    prod = render.make_production(board, timing, 'en', tmp_path)
    elements = prod.spans[-1].motion.elements
    assert prod.spans[-1].motion.continuous_drift
    picture = next(e for e in elements if e.kind == 'picture')
    copy = next(e for e in elements if e.kind == 'text')
    assert picture.preserve_svg_palette
    assert ' '.join(copy.text.split()) == board['beats'][-1]['spoken']['en']
    assert '\n' in copy.text and copy.size >= 96
    assert copy.y*1080 + len(copy.text.splitlines())*copy.size*.575 + 50 < picture.y*1080 - picture.height/2


def test_motion_has_a_vertical_component_when_horizontal_drift_turns():
    scene = MotionScene(elements=[MotionElement(text='Workspace')], motion_floor=.7,
                        foreground_drift=84, continuous_drift=True)
    # Every short settled interval has visible travel, including horizontal
    # turning points; unrelated horizontal/vertical sine periods can both stall.
    for i in range(20, 160):
        before, after = [element_pose(scene, scene.elements[0], 0, i/10+delta) for delta in (-.1, .1)]
        assert math.hypot(after[0]-before[0], after[1]-before[1]) > 8
    scene.motion_floor = 0
    assert element_pose(scene, scene.elements[0], 0, 2) == element_pose(scene, scene.elements[0], 0, 3)


def test_settled_panels_keep_labels_attached_and_do_not_stall_at_turns():
    spec = Diagram('panels', 'b000', 'b000', labels=('notes', 'tasks', 'drawings'), glide=(0, 1))
    timing = {'beats': {'b000': {'start': 0., 'speech_end': 8., 'char_times': [0., 1.]}}}
    panels = PanelMotion(spec, timing, (1920, 1080), for_look('notebook'),
                         {'background': '#f7f5ef', 'ink': '#18313b', 'accent': '#147d78'}, 'drifting')
    for i in range(15, 75):
        before, after = [panels.boxes(i/10+delta) for delta in (-.1, .1)]
        assert math.hypot(after[0][0]-before[0][0], after[0][1]-before[0][1]) > 4
        # Each card and its label keep the same rigid translation and spacing.
        assert after[1][0]-after[0][0] == pytest.approx(before[1][0]-before[0][0])
        assert after[1][1]-after[0][1] == pytest.approx(before[1][1]-before[0][1])
    panels.holds = [(3., 4.)]
    assert panels.boxes(3.1) == panels.boxes(3.9)

"""Saved all-whiteboard plans must keep the same ambient policy as hybrid plans."""
import json

import pytest
from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline


@pytest.mark.parametrize('floor', ['still', 'breathing', 'drifting', 'lively'])
def test_saved_all_whiteboard_plan_keeps_motion_floor(tmp_path, floor):
    board = script.build(ingest.read('# An example\n\nAn idea grows.'))
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='whiteboard', motion_floor=floor)
    for scene in plan['scenes']:
        scene['treatment'] = 'whiteboard'
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, timing, 'en', tmp_path)
    assert type(prod) is render.Production
    assert prod.motion_floor == floor
    assert prod.tl == timing

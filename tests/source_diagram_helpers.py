"""The unchanged source-to-frame setup used by the main causal reproductions."""
import copy
import json

from kinodraw import ingest, script
from kinodraw.director.v3.adapter import adapt
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.validate import validate
from kinodraw.engine import render, timeline


def build(tmp_path, source, *, kind=None, mode=None, floor=None, merged=False, size=None):
    board = script.build(ingest.read(source), story='showcase')
    if kind == 'intro':
        board['chapters'][0]['kind'] = 'intro'
        board['beats'][0]['kind'] = 'title'
    elif kind == 'take':
        chapter = board['chapters'][0]
        chapter.update(kind='section', title={'en': 'Equal groups'}, label={'en': 'Part 1'})
        board['beats'][-1].update(kind='take', take={'headline': {'en': board['beats'][-1]['display']['en']}})
    plan = from_rules(board)
    if mode:
        plan['style']['mode'] = mode
    if floor:
        plan['style']['motion_floor'] = floor
    if merged:
        combined = copy.deepcopy(plan['scenes'][0])
        combined['beat_ids'] = [b['id'] for b in board['beats']]
        combined['elements'] = [e for s in plan['scenes'] for e in s['elements']]
        combined['text'] = {'kind': 'caption_only', 'ref': board['beats'][0]['id']}
        combined['treatment'] = 'motion'
        combined['camera'] = 'static'
        combined['transition_in'] = 'cut'
        plan['scenes'] = [combined]
    plan, repairs = validate(plan, board, {})
    board, _ = adapt(plan, board)
    (tmp_path/'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    prod = render.make_production(board, timing, 'en', tmp_path, size=size)
    return board, plan, timing, prod

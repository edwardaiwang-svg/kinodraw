"""The stage is never empty while narration plays (gauntlet round 3: blank paper under "A huge current rushes
through it" until "bright flash" brought the pictures 6 s later)."""
import json

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline

TEXT = ('# Lightning\n\nThe cloud is like a giant battery.\n\n'
        'A huge current rushes through it in a fraction of a second. That bright flash is the return stroke, '
        'and it heats the air to about five times hotter than the surface of the sun.')


def _production(tmp_path, elements):
    board = script.build(ingest.read(TEXT), story='showcase')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', music_mood='none')
    beat = next(b for b in board['beats'] if 'current' in b['spoken']['en'])['id']
    scene = next(s for s in plan['scenes'] if beat in s['beat_ids'])
    scene.update(beat_ids=[beat], treatment='motion', elements=elements, actions=[], camera='static',
                 transition_in='cut', text={'kind': 'caption_only', 'ref': beat}, shots=[], boards=[])
    plan['scenes'] = [s if s is scene else dict(s, beat_ids=[b for b in s['beat_ids'] if b != beat])
                      for s in plan['scenes']]
    plan['scenes'] = [s for s in plan['scenes'] if s['beat_ids']]
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    return board, prod, next(span for span in prod.spans if beat in span.spec['beat_ids'])


def test_a_scene_whose_pictures_are_named_late_shows_its_first_picture_from_the_start(tmp_path):
    _, prod, span = _production(tmp_path, [{'kind': 'picture', 'ref': 'lightning_bolt'},
                                           {'kind': 'picture', 'ref': 'sun_bright'}])
    pictures = [e for e in span.motion.elements if e.kind == 'picture']
    assert len(pictures) == 2
    assert min(e.start for e in pictures) <= 1.0, [e.start for e in pictures]
    assert max(e.start for e in pictures) > 1.0          # the other picture still arrives with its own words
    assert any('first picture brought in' in w for w in prod.warnings)


def test_a_scene_with_no_pictures_draws_its_sentences_own_items(tmp_path):
    board, prod, span = _production(tmp_path, [])
    drafted = {item['doodle'] for b in board['beats'] if b['id'] in span.spec['beat_ids']
               for v in b['visuals'] if v.get('type') == 'cluster' for item in v['items']}
    assert drafted, 'the picture director drafts items for this beat'
    pictures = [e for e in span.motion.elements if e.kind == 'picture']
    assert pictures and min(e.start for e in pictures) <= 1.0

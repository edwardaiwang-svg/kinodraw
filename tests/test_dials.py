"""The direction dials (look, story, motion) reach the storyboard, and every renderer comes from one factory."""
import json
from pathlib import Path

from kinodraw import pipeline
from kinodraw.engine import render as renderer
from kinodraw.engine import timeline

FIX = Path(__file__).parent / 'fixtures'


def test_new_project_writes_the_dials_into_the_storyboard(tmp_path):
    pipeline.new_project(FIX / 'tiny.md', tmp_path / 'p', direction={'look': 'collage', 'story': 'promo', 'motion': None})
    board = json.loads((tmp_path / 'p' / 'storyboard.json').read_text())
    assert board['look'] == 'collage' and board['story'] == 'promo'
    assert board.get('motion') in (None, 'lively')                              # an unset dial keeps its default


def test_the_factory_builds_the_whiteboard_renderer_by_default(tmp_path):
    board = pipeline.new_project(FIX / 'tiny.md', tmp_path / 'p')
    tl = timeline.layout(board, board['lang'], timeline.synthetic_clips(board, board['lang']))
    prod = renderer.make_production(board, tl, board['lang'], tmp_path / 'p')
    assert type(prod) is renderer.Production and prod.cues() == []
    assert prod.frame(1.0).size == (1920, 1080)


def test_a_promo_is_told_straight_without_whiteboard_narration(tmp_path):
    board = pipeline.new_project(FIX / 'promo_tiny.md', tmp_path / 'p', direction={'look': 'collage', 'story': 'promo'})
    spoken = ' '.join(b['spoken']['en'] for b in board['beats'])
    assert {b['kind'] for b in board['beats']} == {'narration'} and [c['id'] for c in board['chapters']] == ['main']
    assert 'Part 1' not in spoken and 'Key takeaway' not in spoken and 'Thanks for watching' not in spoken
    assert spoken.startswith('You want to do something fun') and 'friendr' in spoken.lower()
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    assert tl['end_card']['end'] == tl['duration']                                   # the silent end card stays
    assert renderer.make_production(board, tl, 'en', tmp_path / 'p').frame(2.0).size == (1920, 1080)

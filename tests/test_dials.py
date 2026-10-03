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


KHAN = ('# Learn anything\n\nStuck on a math problem at eleven at night? Your teacher is asleep and the textbook makes '
        'no sense.\n\nThere\'s a better way. Meet Khan Academy.\n\nPick a topic. Watch a short video. Practice until it '
        'clicks.\n\nKhan Academy. Learn at your own pace. Try it free today.\n')


def test_a_product_name_of_several_words_is_shown_whole(tmp_path):
    """With the product name left blank, "Meet Khan Academy." slammed in "Academy" (and put it in the corner tag)."""
    from kinodraw.director.annotate import annotate
    from kinodraw.engine.collage import promo
    board = pipeline.new_project(KHAN, tmp_path / 'p', direction={'look': 'collage', 'story': 'promo'})
    annotate(board)
    prod = renderer.make_production(board, timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en')), 'en',
                                    tmp_path / 'p')
    assert any(s.role == 'brand' and s.text == 'Meet Khan Academy.' for s in prod.said)
    assert prod.brand['name'] == 'Khan Academy'
    for said, name in [('Introducing Notion Calendar.', 'Notion Calendar'), ('Meet Google Docs.', 'Google Docs'),
                       ('With Friendr, you set a minimum.', 'Friendr'), ("Now there's KinoDraw.", 'KinoDraw'),
                       ('Meet the Tidepool app.', 'Tidepool')]:
        assert promo.name_in(said) == name
    for size, fit in ((150, 1200), (170, 1640)):                      # a long name is smaller, never off the screen
        assert promo._hero(prod, 'Google Workspace for Education', size=size, fit=fit).width <= fit + 2 * 14


def test_the_command_line_can_name_the_brand(tmp_path, monkeypatch):
    from kinodraw import cli, director
    monkeypatch.setattr(director, 'direct', lambda *a: {})
    (tmp_path / 'khan.md').write_text(KHAN, encoding='utf-8')
    script = str(tmp_path / 'khan.md')
    cli.main(['new', script, '-o', str(tmp_path / 'p'), '--look', 'collage', '--story', 'promo', '--brand', 'Khan Academy',
              '--brand-url', 'khanacademy.org', '--brand-cta', 'Start learning'])
    cli.main(['new', script, '-o', str(tmp_path / 'q'), '--look', 'collage', '--story', 'promo'])
    assert json.loads((tmp_path / 'p' / 'storyboard.json').read_text())['brand'] == \
        {'name': 'Khan Academy', 'url': 'khanacademy.org', 'cta': 'Start learning'}
    assert 'brand' not in json.loads((tmp_path / 'q' / 'storyboard.json').read_text())     # left to the script


def test_a_revealed_name_of_several_words_wins_over_the_website(tmp_path):
    """"Meet Khan Academy." never matched the reveal (it only knew "meet"), so with khanacademy.org in the script the
    brand became "khanacademy": the reveal showed the title and the sign-off fell into the use-case stage."""
    from kinodraw.director.annotate import annotate
    for k, (reveal, site, name) in enumerate([('Meet Khan Academy.', 'khanacademy.org', 'Khan Academy'),
                                              ('Introducing Google Docs.', 'docs.google.com', 'Google Docs')]):
        text = (f'# Learn anything\n\nStuck on a problem at eleven at night? Nobody is awake to help.\n\nThere\'s a '
                f'better way. {reveal}\n\nPick a topic. Watch a short video. Practice until it clicks.\n\nMath, science, '
                f'history and coding. All in one place.\n\n{name}. Learn at your own pace. It\'s free for everyone. '
                f'Visit {site}.\n')
        board = pipeline.new_project(text, tmp_path / str(k), direction={'look': 'collage', 'story': 'promo'})
        assert annotate(board)['brand'] == {'name': name, 'url': site}
        prod = renderer.make_production(board, timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en')), 'en',
                                        tmp_path / str(k))
        assert prod.brand['name'] == name and any(s.role == 'brand' and s.text == reveal for s in prod.said)
        end = [s.text for s in prod.stages[-1].sentences]
        assert prod.stages[-1].kind == 'end' and end == [f'{name}.', 'Learn at your own pace.', "It's free for everyone.",
                                                         f'Visit {site}.']


def test_a_look_that_cannot_be_drawn_yet_is_refused_in_plain_words(tmp_path, monkeypatch):
    """--look bold was accepted and the video silently came out as a whiteboard."""
    import pytest
    from kinodraw import cli, director
    from kinodraw.studio import server
    monkeypatch.setattr(director, 'direct', lambda *a: {})
    with pytest.raises(SystemExit) as refused:
        cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'cli'), '--look', 'bold'])
    assert refused.value.code == 2 and not (tmp_path / 'cli').exists()
    with pytest.raises(ValueError, match=r'^The "bold" look is not available yet\. Choose whiteboard, chalkboard, notebook or collage\.$'):
        pipeline.new_project(FIX / 'tiny.md', tmp_path / 'api', direction={'look': 'bold'})
    board = pipeline.new_project(FIX / 'tiny.md', tmp_path / 'p')
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    with pytest.raises(ValueError, match='not available yet'):                     # a hand-edited storyboard
        renderer.make_production({**board, 'look': 'bold'}, tl, 'en', tmp_path / 'p')
    page = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert 'bold' not in page.lower().replace('font-weight', '')
    assert '<label id="motion-wrap" class="hidden">Motion' in page             # the whiteboard ignores Motion
    assert "$('#motion-wrap').classList.toggle('hidden', !collage)" in js and \
        "motion: look === 'collage' ? $('#motion').value : null" in js

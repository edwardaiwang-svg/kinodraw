"""A script's top heading is the video's silent title card in every genre; "The End" closes only stories; words the
scene already writes on screen are not captioned again."""
import json

import pytest

from kinodraw import ingest, script, speech
from kinodraw.engine import timeline


def board_of(text, story='story', title=None):
    return script.build(ingest.read(text, title=title), story, title_card=True)      # as a new project builds it


# ------------------------------------------------------------------ 5. title card and end card
def test_a_top_heading_opens_every_genre_with_a_silent_title_card():
    for story in ('story', 'promo', 'showcase'):
        board = board_of('# Where Does Lightning Come From?\n\nA storm cloud is not just a puff of water.', story)
        first = board['beats'][0]
        assert first['kind'] == 'title' and first['silent'] and first['chapter'] == 'intro'
        assert first['display']['en'] == 'Where Does Lightning Come From?'
        assert board['chapters'][0]['kind'] == 'intro'
    assert [b['id'] for b in board['beats']] == ['b000', 'b001']      # the script's lines keep their ids
    parts = speech.voice_parts(board, None, 'af_heart')
    assert parts['b000'] == {'parts': [], 'hold': speech.TITLE_HOLD}
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    assert all(c['start'] >= tl['beats']['b000']['end'] - 1e-6 for c in tl['captions'])
    # No heading, no title card: the script's first line opens the video.
    assert board_of('A storm cloud is not just a puff of water.')['beats'][0]['kind'] == 'narration'


def test_heading_lines_are_never_said():
    board = script.build(ingest.read('# Where Lightning Comes From\n\nA storm cloud is not just a puff of water.'),
                         'story', title_card=True)
    assert board['beats'][0]['silent'] and board['beats'][0]['kind'] == 'title'
    assert 'Where Lightning' not in ' '.join(s for b in board['beats'] if not b.get('silent')
                                             for s in script.sentences(speech.said_text(b['spoken']['en'], 'en')[0], 'en'))


@pytest.mark.parametrize('genre,story,heading', [('story', 'story', 'The End'), ('explainer', 'story', 'Lightning'),
                                                  ('launch/promo', 'story', 'Lightning'), (None, 'story', 'The End'),
                                                  (None, 'explain', 'Lightning')])
def test_the_end_closes_only_stories(genre, story, heading):
    from kinodraw.engine.auto_scenes import end_heading
    ep = {'story': story, 'title': {'en': 'Lightning'}, **({'genre': genre} if genre else {})}
    ctx = type('Ctx', (), {'ep': ep, 'lang': 'en', 'T': staticmethod(lambda v: v['en'] if isinstance(v, dict) else v)})
    assert end_heading(ctx) == heading


def test_make_production_tells_the_end_card_the_planned_genre(tmp_path):
    from kinodraw.engine import render
    from kinodraw.director.rules import RulesDirector
    from kinodraw.director.v3.rules import from_rules
    board = board_of('Lightning starts inside a storm cloud.\n\nCount the seconds, divide by five.')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['storyboard']['genre'] = 'explainer'
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    assert prod.ep['genre'] == 'explainer'


# ------------------------------------------------------------------ 6. no duplicate caption
@pytest.mark.usefixtures('procedural_rig')
def test_words_the_scene_writes_on_screen_are_not_captioned_again(tmp_path):
    from kinodraw.engine import render
    from kinodraw.director.rules import RulesDirector
    from kinodraw.director.v3.rules import from_rules
    board = board_of('Pendo, a lion cub, watched Mara.\n\nAnd remember: when thunder roars, go indoors.\n\n'
                     'Mara nudged Pendo.')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for scene in plan['scenes']:
        scene.update(treatment='motion', elements=[], actions=[], text={'kind': 'caption_only',
                                                                         'ref': scene['beat_ids'][0]})
    plan['scenes'][1].update(treatment='kinetic_type', text={'kind': 'kinetic', 'ref': plan['scenes'][1]['beat_ids'][0]})
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    kinetic, plain = prod.spans[1], prod.spans[0]
    assert kinetic.on_screen == (plan['scenes'][1]['beat_ids'][0],) and plain.on_screen == ()
    t_kinetic = tl['beats'][kinetic.spec['beat_ids'][0]]['start'] + 1.
    t_plain = tl['beats'][plain.spec['beat_ids'][0]]['start'] + 1.
    assert prod._written(kinetic, t_kinetic) and not prod._written(plain, t_plain)
    drawn = []
    prod.whiteboard._caption = lambda image, t, *a, **k: drawn.append(round(t, 3))
    prod.frame(t_kinetic)
    prod.frame(t_plain)
    assert drawn == [round(t_plain, 3)]


@pytest.mark.usefixtures('procedural_rig')
def test_a_captioned_scene_never_writes_its_narration_out_again(tmp_path):
    # Script 02 (r01): the plan gave every caption_only scene a text element for its own beat, and the scene wrote
    # the narration out as a growing headline over the pictures while the caption showed the same words.
    from kinodraw.engine import render
    from kinodraw.director.rules import RulesDirector
    from kinodraw.director.v3.rules import from_rules
    board = board_of('A storm cloud is not just a puff of water. Strong winds push air up and down inside it.\n\n'
                     'And remember: when thunder roars, go indoors.')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    first, second = plan['scenes'][0], plan['scenes'][1]
    first.update(treatment='motion', actions=[], elements=[{'kind': 'text', 'ref': first['beat_ids'][0]}],
                 text={'kind': 'caption_only', 'ref': first['beat_ids'][0]})
    second.update(treatment='kinetic_type', actions=[], elements=[], text={'kind': 'kinetic', 'ref': second['beat_ids'][0]})
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    captioned, kinetic = prod.spans[0], prod.spans[1]
    said = {b['display']['en'] for b in board['beats']}
    written = [' '.join(e.text.split()) for e in captioned.motion.elements if e.kind == 'text']
    assert not [w for w in written if w and any(w in s or s in w for s in said)], written
    assert captioned.on_screen == ()                                  # so the caption still carries the words
    t = tl['beats'][first['beat_ids'][0]]['start'] + 1.
    assert not prod._written(captioned, t)
    assert [e for e in kinetic.motion.elements if e.kind == 'text']    # kinetic type is the one written copy


@pytest.mark.usefixtures('procedural_rig')
def test_a_quote_card_shows_one_pair_of_quote_marks(tmp_path):
    # Script 10 (r01): the script's own "Hi!" came out as “"Hi!"” on the quote card.
    from kinodraw.engine import render
    from kinodraw.director.rules import RulesDirector
    from kinodraw.director.v3.rules import from_rules
    board = board_of('Ava waved at the coach.\n\n"Hi!"')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for scene in plan['scenes']:
        scene.update(treatment='motion', actions=[], elements=[], text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    quoted = next(sc for sc in plan['scenes'] if board['beats'][-1]['id'] in sc['beat_ids'])
    quoted['text'] = {'kind': 'quote', 'ref': board['beats'][-1]['id']}
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = next(sp for sp in prod.spans if board['beats'][-1]['id'] in sp.spec['beat_ids'])
    cards = [e.text for e in span.motion.elements if e.kind == 'text' and e.preset == 'corner_caption']
    assert cards == ['“Hi!”'], cards


def test_the_word_being_said_stays_lit_when_the_accent_is_close_to_the_ink(tmp_path):
    # Script 12 (r01): the plan's accent #2E7D5B next to #263238 letters had no usable shade, so no word was lit.
    from PIL import ImageColor
    from kinodraw.engine import render
    from kinodraw.engine.captions import highlight_color
    from kinodraw.director.rules import RulesDirector
    from kinodraw.director.v3.rules import from_rules
    board = board_of('Nana typed with one finger, very slowly.\n\nLena smiled at the screen.')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing',
                         palette={'background': '#F7F3E9', 'ink': '#263238', 'accent': '#2E7D5B', 'accent2': '#D58B45'})
    for scene in plan['scenes']:
        scene.update(treatment='motion', actions=[], elements=[], text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    ink, paper = ImageColor.getrgb('#263238'), ImageColor.getrgb('#F7F3E9')
    assert highlight_color(prod.caption_accent, ink, paper) != ink


def test_a_line_in_a_speech_bubble_is_not_captioned_again(tmp_path):
    # The Envelope / Nana (r01): every bubbled line also ran in the bottom caption. The caption keeps the narrator.
    from kinodraw.engine import render
    from kinodraw.director.rules import RulesDirector
    from kinodraw.director.v3.rules import from_rules
    board = board_of('Theo, a boy, sat by his mother.\n\n"Mine\'s broken," he said. "It\'s just random stuff."')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['storyboard']['genre'] = 'story'
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for scene in plan['scenes']:
        scene.update(treatment='character', actions=[], text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    if prod.storybook is None:
        pytest.skip('story pages are off in this build')
    quote = board['beats'][-1]
    spoken = quote['spoken']['en']
    prod.storybook.bubbled = [{'beat': quote['id'], 'start': spoken.index('Mine'), 'end': spoken.index(','),
                               'speaker': 'theo', 'text': "Mine's broken"}]
    prod._leave_bubbled_lines_to_the_bubbles()
    shown = ' '.join(c['text'] for c in prod.whiteboard.tl['captions'])
    assert "Mine's broken" not in shown and 'he said.' in shown and "It's just random stuff." in shown
    assert prod.whiteboard.cap_starts == [c['start'] for c in prod.whiteboard.tl['captions']]
    assert 'Theo, a boy, sat by his mother.' in shown                       # narration elsewhere is unchanged

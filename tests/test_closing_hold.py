"""The closing card is read, not watched being written (engine/closing.py card_timing): once its words and credit
are complete it stays for its reading time (about 0.3 s a word, at least 2.5 s; 1.8 s in a piece under 20 s); the
old scene clears before the card's words appear; an ad's card carries the day, time and price its closing paragraph
states; and a script that ends on its call to action gets one narrated card, not a silent outro after it."""
import json
import re

import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline

AD = """# Two Ovens Saturday Rolls

Warm cinnamon rolls, fresh out of the oven every Saturday at 7 a.m. Just $3.50 each, until they're gone. Two Ovens Bakery, corner of Elm and Fifth. Come early!
"""
PROMO = """# Pantrypal

Every week the same thing happens. The lettuce wilts, the yogurt expires, and the bread grows a blue coat.

Pantrypal reads your receipt and lists what you bought. Each item gets a timer, so you know what to cook first.

When something is about to turn, you get a gentle reminder on your phone, with a recipe that uses it up.

Pantrypal. Cook what you have. Download it free today. Link below.
"""
GREETING = "Happy 25th Jo, twenty-five years and you're still stealing my fries.\n"
STORY = """# The Lantern

Mila carried the lantern up the hill. The wind tugged at her scarf.

"Come home before dark," her mother had said.

She watched the valley lights blink on, one by one, and smiled.
"""


def board_of(text, genre=None):
    board = script.build(ingest.read(text), story='story')
    if genre:
        board['genre'] = genre
    return board


def layout(board):
    return timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))


def card(board, tl, tmp_path):
    """The whiteboard production's closing-card elements, when they are all complete, and the words they show."""
    prod = render.make_production(board, tl, 'en', tmp_path)
    wb = getattr(prod, 'whiteboard', prod)
    els = [e for e in wb.ctx.elements if getattr(e, 'group', None) in ('endcard', 'credit')]
    done = max(e.start + e.drawing.duration / e.rate for e in els)
    lines = [' '.join(getattr(e.drawing, 'lines', None) or []) for e in els if e.group == 'endcard']
    return prod, els, done, lines


def reading(lines, body):
    words = len(re.findall(r'\w+', ' '.join(lines)))
    return max(1.8 if body < 20 else 2.5, .3 * words)


@pytest.mark.parametrize('paragraphs', [1, 12, 30])
def test_the_finished_card_stays_for_its_reading_time(tmp_path, paragraphs):
    text = '# Notes\n\n' + '\n\n'.join(f'The river carried paper boat number {k} past the old mill and the bridge.'
                                       for k in range(paragraphs)) + '\n'
    board = board_of(text)
    tl = layout(board)
    _, els, done, lines = card(board, tl, tmp_path)
    body = tl['end_card']['start']
    assert any('Made with' in ' '.join(e.drawing.lines) for e in els if e.group == 'credit')
    # Reading time starts once the card (its credit too) is complete; the drawing time does not count.
    assert tl['duration'] - done >= reading(lines, body) - 1 / 30


def test_an_ad_card_lists_the_day_time_and_price_its_script_states(tmp_path):
    board = board_of(AD, 'launch/promo')
    tl = layout(board)
    _, _, done, lines = card(board, tl, tmp_path)
    said = ' | '.join(lines)
    for fact in ('Every Saturday at 7 a.m.', 'Just $3.50 each', 'Two Ovens Bakery, corner of Elm and Fifth',
                 'Come early!'):
        assert fact in said, (fact, lines)
    assert 'The End' not in said and 'Thanks for watching' not in said
    assert tl['duration'] - done >= reading(lines, 0) - 1 / 30          # 20 words: about 6 s to read, not 1.5 s


def test_a_script_that_ends_on_its_call_to_action_gets_one_narrated_card(tmp_path):
    board = board_of(PROMO, 'launch/promo')
    tl = layout(board)
    last = tl['beats'][tl['beat_order'][-1]]
    end = tl['end_card']
    # The card starts while the voice says its lines ("Download it free today. Link below."), after the beat's own
    # first words, so the voice reads the card ...
    assert last['start'] < end['start'] < last['speech_end']
    # ... and no silent outro follows: after the last word the card stays only as long as reading it needs.
    _, _, done, lines = card(board, tl, tmp_path)
    assert 'Download it free today' in lines and 'Link below' in lines
    assert tl['duration'] - last['end'] <= max(1., done + reading(lines, 30) - last['end']) + 1 / 30
    assert tl['duration'] - done >= reading(lines, 30) - 1 / 30


def test_the_old_scene_is_gone_before_the_card_words_appear(tmp_path):
    board = board_of(AD, 'launch/promo')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for scene in plan['scenes']:
        scene['treatment'] = 'motion'
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = layout(board)
    prod = render.make_production(board, tl, 'en', tmp_path)
    assert type(prod).__name__ == 'HybridProduction'
    els = [e for e in prod.whiteboard.ctx.elements if getattr(e, 'group', None) in ('endcard', 'credit')]
    first = min(e.start for e in els)                    # the card's first words are on the page
    assert first > tl['end_card']['start']
    # From that moment on the frame is the card page alone: no dissolve still layering the old scene's text under it.
    for t in (first + .001, first + 1 / 30):
        assert prod.frame(t).tobytes() == prod.whiteboard.frame(t).tobytes(), t


def test_a_short_card_with_three_words_stays_short(tmp_path):
    board = board_of(GREETING, 'story')
    tl = layout(board)
    end = tl['end_card']
    _, els, done, lines = card(board, tl, tmp_path)
    assert lines == ['Happy 25th Jo']
    assert all(not e.hand for e in els)                                  # shown at once, not written
    assert tl['duration'] - done >= 1.8 - 1 / 30                         # its reading time ...
    assert end['end'] - end['start'] <= 2.5                              # ... and no more: a short piece stays short


def test_a_story_still_ends_on_the_end_with_the_credit(tmp_path):
    board = board_of(STORY, 'story')
    tl = layout(board)
    _, els, done, lines = card(board, tl, tmp_path)
    assert 'The End' in lines
    assert any('Made with' in ' '.join(e.drawing.lines) for e in els if e.group == 'credit')
    assert not any('Come home' in line for line in lines)                # a story's quote is not a call to action
    assert tl['duration'] - done >= reading(lines, tl['end_card']['start']) - 1 / 30

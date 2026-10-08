"""How a video closes (engine/closing.py): the closing card holds about a tenth of the video (1.5-4 s, only the short
tail under 20 s) with the "Made with ..." credit on the same card; an ad, notice or invitation closes on its own call
to action and key information, a greeting on its wish, and only a story on "The End"."""
import pytest

from kinodraw import ingest, script
from kinodraw.engine import render, timeline

AD = """# Two Ovens Saturday Rolls

Warm cinnamon rolls, fresh out of the oven every Saturday at 7 a.m. Just $3.50 each, until they're gone. Two Ovens Bakery, corner of Elm and Fifth. Come early!
"""
CONTACTS = """# Five Ways to Save Water

Find the drip first. A faucet leaking one drop a second wastes over 3,000 gallons a year.

And if that drip turns out to be bigger than a washer, you know who to call.

[SHOW: end card with logo]
www.pipewisebayside.com
hello@pipewisebayside.com
(555) 018-7720
"""
INVITE = """# Uncle Dev Turns 50

- grew up in Kestrel Falls
- 3 kids 2 grandkids
- party sat 6pm, our back yard
"""
GREETING = "Happy 25th Jo, twenty-five years and you're still stealing my fries.\n"
STORY = """# The Lantern

Mila carried the lantern up the hill. The wind tugged at her scarf.

"Come home before dark," her mother had said.

She watched the valley lights blink on, one by one, and smiled.
"""


def closing():
    from kinodraw.engine import closing as module
    return module


def board_of(text, genre=None):
    board = script.build(ingest.read(text), story='story')
    if genre:
        board['genre'] = genre                    # what the plan read it as (make_production sets it from the plan)
    return board


def layout(board):
    return timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))


def card_text(board, tl, tmp_path):
    prod = render.make_production(board, tl, 'en', tmp_path)
    els = [e for e in prod.ctx.elements if getattr(e, 'group', None) in ('endcard', 'credit')]
    return prod, els, [' '.join(getattr(e.drawing, 'lines', None) or []) for e in els]


def test_the_tail_is_about_a_tenth_of_the_video_and_short_for_a_short_piece():
    assert closing().tail_seconds(6) == closing().tail_seconds(19.9) == 1.5
    assert closing().tail_seconds(30) == pytest.approx(3.0)
    assert closing().tail_seconds(74) == closing().tail_seconds(600) == 4.0


@pytest.mark.parametrize('paragraphs', [1, 5, 12, 30])
def test_the_closing_card_scales_with_the_video_and_the_credit_is_on_it(paragraphs):
    text = '# Notes\n\n' + '\n\n'.join(f'The river carried paper boat number {k} past the old mill and the bridge.'
                                       for k in range(paragraphs)) + '\n'
    board = board_of(text)
    tl = layout(board)
    end = tl['end_card']
    body = end['start']
    want = 1.5 if body < 20 else min(4., max(1.5, body * .1))
    assert end['end'] - end['start'] == pytest.approx(want, abs=.04)
    assert tl['credit'] == end                                    # one card, the credit merged in
    off = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    assert off['credit'] is None and off['duration'] == tl['duration']


def test_an_ad_closes_on_its_own_call_to_action_not_the_end(tmp_path):
    board = board_of(AD, 'launch/promo')
    tl = layout(board)
    prod, els, texts = card_text(board, tl, tmp_path)
    said = ' | '.join(texts)
    assert 'Come early!' in said and 'corner of Elm and Fifth' in said
    assert 'The End' not in said and 'Thanks for watching' not in said
    assert any('Made with' in t for t in texts)                   # the credit line stays, on the same card
    # A short piece's card is shown at once, not written slowly by the hand, and is up in time to be read.
    end = tl['end_card']
    assert end['end'] - end['start'] == pytest.approx(1.5, abs=.04)
    assert all(not e.hand for e in els)
    assert max(e.start + e.drawing.duration / e.rate for e in els) <= end['start'] + .7
    assert closing().closing(board, 'en') == {'kind': 'info',
                                              'items': ['Two Ovens Bakery, corner of Elm and Fifth', 'Come early!']}


def test_a_contact_card_shows_every_contact_as_written(tmp_path):
    board = board_of(CONTACTS, 'launch/promo')
    tl = layout(board)
    _, _, texts = card_text(board, tl, tmp_path)
    assert 'Thanks for watching' not in ' '.join(texts) and '(555) 018-7720' in texts
    close = closing().closing(board, 'en')
    assert close['items'] == ['www.pipewisebayside.com', 'hello@pipewisebayside.com', '(555) 018-7720']


def test_an_invitation_read_as_a_story_still_closes_on_its_time_and_place():
    assert closing().closing(board_of(INVITE, 'story'), 'en') == {'kind': 'info',
                                                               'items': ['Party sat 6pm, our back yard']}


def test_a_greeting_closes_on_its_wish():
    assert closing().closing(board_of(GREETING, 'story'), 'en') == {'kind': 'wish', 'items': ['Happy 25th Jo']}


def test_a_story_still_ends_on_the_end(tmp_path):
    board = board_of(STORY, 'story')
    assert closing().closing(board, 'en') == {'kind': 'story', 'items': []}
    _, _, texts = card_text(board, layout(board), tmp_path)
    assert 'The End' in texts


def test_a_long_card_is_written_with_time_left_to_read_it(tmp_path):
    tips = '\n\n'.join(f'Tip {k}: check the pipe under sink number {k} for a slow drip every single month.'
                       for k in range(1, 9))
    board = board_of(CONTACTS.replace('Find the drip first.', tips + '\n\nFind the drip first.'), 'launch/promo')
    tl = layout(board)
    end = tl['end_card']
    span = end['end'] - end['start']
    assert span == pytest.approx(4.0, abs=.04)
    _, els, texts = card_text(board, tl, tmp_path)
    done = {e.group: max(x.start + x.drawing.duration / x.rate for x in els if x.group == e.group) for e in els}
    assert all(e.hand for e in els)                                        # a long card is written by the hand
    assert done['endcard'] <= end['start'] + .6 * span + .05               # its words are up with time to read them
    assert done['credit'] <= end['end'] - .25

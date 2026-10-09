"""How a video closes (engine/closing.py): the finished closing card holds for its reading time (card_timing; see
test_closing_hold.py) with the "Made with ..." credit on the same card; an ad, notice or invitation closes on its own
call to action and key information, a greeting on its wish, and only a story on "The End"."""
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


def test_the_reading_time_is_a_rate_a_word_with_a_floor_and_a_short_floor_for_a_short_piece():
    c = closing()
    assert c.reading_seconds(3, 6) == 1.8 and c.reading_seconds(3, 74) == 2.5
    assert c.reading_seconds(20, 13) == c.reading_seconds(20, 74) == pytest.approx(6.0)
    short, long_ = c.card_timing(3, 6), c.card_timing(6, 74)
    assert short['quick'] and short['draw'] == 0 and not long_['quick'] and long_['draw'] >= c.DRAW_MIN


@pytest.mark.parametrize('paragraphs', [1, 5, 12, 30])
def test_the_closing_card_scales_with_the_video_and_the_credit_is_on_it(paragraphs):
    text = '# Notes\n\n' + '\n\n'.join(f'The river carried paper boat number {k} past the old mill and the bridge.'
                                       for k in range(paragraphs)) + '\n'
    board = board_of(text)
    tl = layout(board)
    end = tl['end_card']
    body = end['start']
    assert end['end'] - end['ready'] >= closing().reading_seconds(5, body) - 1 / 30   # "The End" + "Thanks ..."
    assert tl['credit'] == {'start': end['start'], 'end': end['end']}   # one card, the credit merged in
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
    # A short piece's card is shown at once, not written slowly by the hand, as soon as the old scene has cleared.
    end = tl['end_card']
    assert all(not e.hand for e in els)
    assert max(e.start + e.drawing.duration / e.rate for e in els) <= end['appear'] + .2
    assert closing().closing(board, 'en')['items'] == ['Every Saturday at 7 a.m.', 'Just $3.50 each',
                                                       'Two Ovens Bakery, corner of Elm and Fifth', 'Come early!']


def test_a_contact_card_shows_every_contact_as_written(tmp_path):
    board = board_of(CONTACTS, 'launch/promo')
    tl = layout(board)
    _, _, texts = card_text(board, tl, tmp_path)
    assert 'Thanks for watching' not in ' '.join(texts) and '(555) 018-7720' in texts
    close = closing().closing(board, 'en')
    assert close['items'] == ['www.pipewisebayside.com', 'hello@pipewisebayside.com', '(555) 018-7720']


def test_an_invitation_read_as_a_story_still_closes_on_its_time_and_place():
    close = closing().closing(board_of(INVITE, 'story'), 'en')
    assert (close['kind'], close['items']) == ('info', ['Party sat 6pm, our back yard'])


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
    _, els, texts = card_text(board, tl, tmp_path)
    done = {e.group: max(x.start + x.drawing.duration / x.rate for x in els if x.group == e.group) for e in els}
    assert all(e.hand for e in els if e.group == 'endcard')                # a long card is written by the hand
    assert max(done.values()) <= end['ready'] + 1 / 30                     # complete, credit too, by its ready time
    assert end['end'] - end['ready'] >= end['read'] >= 2.5                 # and then read


def test_the_closing_card_waits_for_the_last_picture_of_a_short_piece(tmp_path):
    # One short sentence ends before its picture can be drawn: the card cuts in late enough for the hand to finish it
    # (never skipping it on a blank page), and the wait counts as the card's own hold for QA.
    from kinodraw.qa import probes
    board = board_of('A.')
    board['beats'][0]['visuals'] = [{'id': 'b001v0', 'type': 'cluster', 'items': [{'doodle': 'narrator_explain'}],
                                     'relation': 'none'}]
    clips = {'b001': {'speech': 1.11, 'char_times': [.32, .32]}}        # one word, said in about a second
    tl = timeline.layout(board, 'en', clips, render.pacing(board, 'en', clips, tmp_path))
    prod = render.make_production(board, tl, 'en', tmp_path)
    pictures = [e for e in prod.ctx.elements if e.beat and e.hand]
    assert pictures and not any(e.skipped for e in pictures)
    card = tl['end_card']
    assert max(e.end for e in pictures) <= card['start']
    assert 0 < card['wait'] <= 1.5 and card['start'] - card['wait'] >= tl['beats'][tl['beat_order'][-1]]['speech_end'] - 1e-3
    assert any(abs(s.start - (card['start'] - card['wait'])) < 1e-3 for s in probes.declared_holds(tl))

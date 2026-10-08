"""Codes, key names and labelled numbers (gauntlet round 6, fixer AB3; every sentence here is invented).

1. A number the text introduces as a code, PIN, passcode, one-time or verification code, flight, order, ticket,
   confirmation or tracking number is said digit by digit in its written groups ("four eight two, nine one three"),
   zero as "zero"; on screen it stays as written. Ordinary quantities, years, prices and times keep their readings.
2. Key names written as keys (joined by "+" or "plus", or after press/hold/hit) are said as words ("control",
   "command", "escape"); on screen they stay as written.
3. A number card for an extension or another labelled number keeps its label ("ext. 352"), never a bare number.
"""
import pytest

from kinodraw import numbers, speech


def said(text):
    return speech.said_text(numbers.normalize(text, 'en').spoken, 'en')[0]


# ------------------------------------------------------------------ 1. codes, digit by digit in their groups
@pytest.mark.parametrize('text,voice', [
    ('The app shows a 6-digit code, like 517 204.',
     'The app shows a six-digit code, like five one seven, two zero four.'),
    ('Your one-time code is 830 615, and it lasts a minute.',
     'Your one-time code is eight three zero, six one five, and it lasts a minute.'),
    ('Read the verification code: 271-904.', 'Read the verification code: two seven one, nine zero four.'),
    ('Your confirmation number is 7731 4410.',
     'Your confirmation number is seven seven three one, four four one zero.'),
    ('Your order #10023 ships on Friday.', 'Your order number one zero zero two three ships on Friday.'),
    ('Keep your ticket number, 5521 8830, until the show ends.',
     'Keep your ticket number, five five two one, eight eight three zero, until the show ends.'),
    ('The tracking number is 9405 5118 2300.',
     'The tracking number is nine four zero five, five one one eight, two three zero zero.'),
    ('Set a PIN such as 4096 on the lock.', 'Set a PIN such as four zero nine six on the lock.'),
])
def test_a_code_is_read_digit_by_digit_in_its_written_groups(text, voice):
    assert said(text) == voice
    assert speech.caption_text(text) == text                    # shown exactly as written


@pytest.mark.parametrize('text,voice', [
    ('We planted 482 trees and 913 shrubs in 2019.',
     'We planted four hundred eighty-two trees and nine hundred thirteen shrubs in twenty nineteen.'),
    ('The kit costs $214 and ships at 3:15 PM.', 'The kit costs two hundred fourteen dollars and ships at three fifteen PM.'),
    ('The code has 120 lines.', 'The code has one hundred twenty lines.'),
    ('Call ext. 214 for help.', 'Call extension two one four for help.'),
    ('Order 300 pizzas for the party.', 'Order three hundred pizzas for the party.'),     # a verb and a count
    ('I pin 120 photos a week.', 'I pin one hundred twenty photos a week.'),
])
def test_ordinary_numbers_keep_their_readings(text, voice):
    assert said(text) == voice


# ------------------------------------------------------------------ 2. key names said as words
@pytest.mark.parametrize('text,voice', [
    ('On a shared laptop, press Ctrl + Alt + T to open a terminal.',
     'On a shared laptop, press control plus alt plus T to open a terminal.'),
    ('On a Mac, press Cmd+Opt+Esc to quit an app.', 'On a Mac, press command plus option plus escape to quit an app.'),
    ('Hit Esc to close the menu, then hold Fn and press Del.',
     'Hit escape to close the menu, then hold function and press delete.'),
    ('Press PgUp or PgDn to turn the page.', 'Press page up or page down to turn the page.'),
    ('Copy it with Ctrl plus C.', 'Copy it with control plus C.'),
    ('Press Ctrl + 1 to zoom in.', 'Press control plus one to zoom in.'),
    ('Press Shift + Enter for a new line.', 'Press Shift plus Enter for a new line.'),
])
def test_key_names_are_said_as_words(text, voice):
    assert said(text) == voice
    assert speech.caption_text(text) == text                    # the keys stay as written on screen


@pytest.mark.parametrize('text', [
    'We drove down to Del Mar for lunch.',
    'You can opt in at the front desk.',
    'Alt rock filled the room.',
])
def test_words_that_only_look_like_keys_are_left_alone(text):
    assert said(text) == text


@pytest.mark.parametrize('text,voice', [
    ('Mix salt + pepper.', 'Mix salt and pepper.'),
    ('Use up + down to scroll.', 'Use up and down to scroll.'),
    ('So 2 + 2 is 4.', 'So two plus two is four.'),
])
def test_a_plus_without_a_modifier_key_keeps_its_reading(text, voice):
    assert said(text) == voice


# ------------------------------------------------------------------ 3. a labelled number's card keeps its label
@pytest.fixture(scope='module')
def director():
    from kinodraw.director.rules import RulesDirector
    return RulesDirector('en')


@pytest.mark.parametrize('sentence,shown', [
    ('Questions? Call the front desk at ext. 352.', 'ext. 352'),
    ('Board Flight 2231 at the far end.', 'Flight 2231'),
    ('The app shows a 6-digit code, like 517 204.', '517 204'),
])
def test_a_labelled_number_card_keeps_its_label(director, sentence, shown):
    v, _ = director._number({'id': 'b001', 'chapter': 'b1'}, sentence, numbers.normalize(sentence, 'en'), set())
    assert v['type'] == 'stat' and v['value']['en'] == shown

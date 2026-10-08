"""Data cards read from the script (kinodraw/figures.py): which sentences state a figure, and what the card says."""
import pytest

from kinodraw import figures


def _one(sentence):
    found = figures.cards(sentence)
    assert len(found) == 1, found
    return found[0]


def test_a_change_from_one_value_to_another_keeps_the_script_text():
    card = _one('The headline: revenue hit $4.2M for the quarter, up 18% from $3.56M last year.')
    assert card.kind == 'change'
    assert [text for text, _, _ in card.items] == ['$3.56M', '$4.2M']
    assert card.items[0][1] == 'last year' and card.delta == '18%' and card.direction == 'up'
    card = _one('We now pick up from 12,400 households, up from 9,800 at this time last year.')
    assert card.kind == 'change' and [t for t, _, _ in card.items] == ['9,800', '12,400 households']
    card = _one('Sales went from 40 units to 95 units in a year.')
    assert card.kind == 'change' and [t for t, _, _ in card.items] == ['40 units', '95 units']
    assert _one('Our cafe went from 95 seats to 40 seats.').direction == 'down'


def test_values_compared_are_bars():
    card = _one('Our new plan costs $12 a month vs $20 for the old one.')
    assert card.kind == 'bars' and [t for t, _, _ in card.items] == ['$12', '$20']


def test_a_price_a_headline_number_and_a_counter():
    found = figures.cards('Warm rolls every Saturday at 7 a.m. 🔥 Just $3.50 each, until they are gone.')
    assert [c.kind for c in found] == ['event', 'price']
    assert found[0].rows == ['Every Saturday', '7 a.m.']
    assert (found[1].value, found[1].label) == ('$3.50', 'each')
    card = _one('All together, members kept 3,100 tons of food scraps out of the landfill.')
    assert (card.kind, card.value, card.label) == ('counter', '3,100 tons', 'food scraps')
    card = _one('Fuel cost us 9% more than we planned.')
    assert (card.kind, card.value, card.label, card.direction) == ('number', '9%', 'more than we planned', 'up')
    card = _one('The bridge cost $4.2 million.')
    assert (card.kind, card.value) == ('number', '$4.2 million')         # a big sum is a headline, not a price tag
    card = _one('The new chip is 3 times faster than the last one.')
    assert (card.kind, card.value, card.label) == ('number', '3 times', 'faster')
    card = _one('A new entry appears with a 6-digit code, like 482 913.')
    assert (card.kind, card.value, card.label) == ('number', '482 913', 'code')
    assert _one('You could save up to 20%.').qualifier == 'up to'


def test_when_and_where():
    card = _one('Crews will pull the last barrels at 6 a.m. Tues., Oct. 14.')
    assert card.kind == 'event' and card.rows == ['Tues. · Oct. 14', '6 a.m.']
    card = _one('Open the doors at 9:30 a.m. on June 3rd at the Riverside Library.')
    assert card.rows == ['June 3rd', '9:30 a.m.'] and card.where == 'Riverside Library'
    assert _one('party sat 6pm, our back yard').rows == ['Sat', '6pm']
    assert _one('See you at the member meeting in November.').rows == ['November']


def test_several_figures_are_a_stat_list_of_exact_text():
    card = _one("Say you put $1,000 in a savings account that pays 5% a year, and you don't touch it for 10 years.")
    assert card.kind == 'stat' and card.rows == ['$1,000', '5% a year', '10 years']
    assert _one('3 kids 2 grandkids').rows == ['3 kids', '2 grandkids']
    assert _one('If you said $1,500, you are wrong: 5% of $1,000 is $50.').rows == ['$1,500', '5% of $1,000 is $50']


@pytest.mark.parametrize('sentence', [
    'One day the fox found a river. She was one of a kind, and a couple of birds watched.',
    'She graduated with the Class of 2031 and drove a Windows 11 laptop down Route 66.',
    'The old bridge, built in 1958, failed a state inspection.',
    'Questions? Email helpdesk@harborlight.org or call ext. 214.',
    'Call us at (555) 018-7720 or visit www.example.com today.',
    "Here's what's next for Q4:",
    'Turn on two-step login and enter the 6-digit code.',
    'Tip 1: check the drip first.',
    'I sat down with 2 friends.',
    'May I come in?',
])
def test_never_a_figure(sentence):
    assert figures.cards(sentence) == []


def test_code_formulas_and_titles_get_no_cards():
    code = {'id': 'b1', 'kind': 'narration', 'display': {'en': '```python\nbalance = 1000 * 1.05\n```'},
            'markup': {'kind': 'code'}}
    math = {'id': 'b2', 'kind': 'narration', 'display': {'en': 'A = 1000(1 + 0.05)^10'}, 'markup': {'kind': 'math'}}
    title = {'id': 'b3', 'kind': 'title', 'display': {'en': 'Why $1,000 Turns Into $1,628.89'}}
    said = {'id': 'b4', 'kind': 'narration', 'display': {'en': 'Plug in our numbers and you get $1,628.89.'}}
    assert [figures.beat_cards(b, 'en') for b in (code, math, title)] == [[], [], []]
    assert figures.beat_cards(said, 'en')[0].value == '$1,628.89'
    assert figures.cards('Ganaron $4.2M este año.', 'es') == []


def test_a_figure_is_timed_from_its_spoken_words():
    display = 'Revenue hit $4.2M this year.'
    spoken = 'Revenue hit four point two million dollars this year.'
    at = figures.spoken_offset(display, spoken, display.index('$'), 'en')
    assert spoken[at:].startswith('four point two')

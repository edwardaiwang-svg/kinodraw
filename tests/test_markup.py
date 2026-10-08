"""Markup that is a picture, never a voice or a caption (kinodraw/markup.py): fenced code, display formulas,
numbered steps, warning callouts and key combos."""
from kinodraw import ingest, markup, script, speech
from kinodraw.engine import timeline

CODE = """# Compound interest

Here's the same thing in Python:

```python
balance = 1000
for year in range(10):
    balance = balance * 1.05
    print(year + 1, round(balance, 2))
```

Every time through the loop, `balance` grows by 5%.

The formula looks like this:

A = P(1 + r)^n

P is what you start with.
"""

STEPS = """Here's how to set it up.

1. On your laptop, open **Harbor Mail**.
2. Choose **Security**, then **Two-step login**.
3. Type that code into the box and click **Verify**.

That's it.

> ⚠️ Never share this code, not even with IT. We will never ask for it.

Tip: press **Ctrl + Shift + N** to open a private window first.
"""


def board_of(text, story='story'):
    return script.build(ingest.read(text), story)


def beat_with(board, words):
    return next(b for b in board['beats'] if words in b['display']['en'])


def said(beat):
    return speech.said_text(beat['spoken']['en'], 'en')[0]


def caption(beat):
    return speech.captions(beat['spoken']['en'], beat['display']['en'])[1]


def test_a_fenced_code_block_is_one_beat_shown_exactly_and_never_said_or_captioned():
    board = board_of(CODE)
    code = beat_with(board, 'balance = 1000')
    assert code['markup'] == {'kind': 'code'}
    assert markup.board(code, 'en') == {'kind': 'code', 'lang': 'python', 'code': (
        'balance = 1000\nfor year in range(10):\n    balance = balance * 1.05\n    print(year + 1, round(balance, 2))')}
    assert said(code) == '' and caption(code) == ''
    # the voice pauses while the code types in, longer than a stage direction's hold
    parts = speech.voice_parts(board, None, 'af_heart')[code['id']]
    assert parts['parts'] == [] and parts['hold'] >= 1.5
    # no other beat carries a scrap of the code, the fence or its language tag
    for b in board['beats']:
        if b is not code:
            assert '`' not in b['display']['en'] and 'range' not in said(b) and 'python ' not in said(b).lower()


def test_inline_code_is_said_as_a_plain_word():
    b = beat_with(board_of(CODE), 'Every time')
    assert said(b) == 'Every time through the loop, balance grows by five percent.'


def test_a_display_formula_is_said_in_words_and_left_to_the_board():
    board = board_of(CODE)
    b = beat_with(board, 'A = P')
    assert b['markup'] == {'kind': 'math'}
    assert said(b) == 'A equals P times one plus r to the power of n'
    assert '^' not in said(b) and caption(b) == ''
    assert markup.board(b, 'en') == {'kind': 'math', 'formula': 'A = P(1 + r)^n'}


def test_spoken_formulas_in_words():
    assert markup.say_math('E = mc^2') == 'E equals m c squared.'
    assert markup.say_math('a² + b² = c²') == 'A squared plus b squared equals c squared.'
    assert markup.say_math('$$x = \\frac{a}{b}$$') == 'X equals a over b.'
    assert not markup.math_line('Total = $50 a month')
    assert not markup.math_line('The answer is x = 5, so we stop.')


def test_numbered_steps_are_marked_and_lose_their_numbers_to_the_indicator():
    board = board_of(STEPS)
    steps = [b for b in board['beats'] if (b.get('markup') or {}).get('kind') == 'step']
    assert [(b['markup']['n'], b['markup']['of']) for b in steps] == [(1, 3), (2, 3), (3, 3)]
    assert steps[0]['display']['en'] == 'On your laptop, open Harbor Mail.'
    assert not any(b['display']['en'][:2] in ('1.', '2.', '3.') for b in board['beats'])
    assert said(steps[0]) == 'On your laptop, open Harbor Mail.'


def test_a_warning_callout_is_marked_with_its_own_words():
    b = beat_with(board_of(STEPS), 'Never share')
    assert b['markup'] == {'kind': 'warning'}
    assert markup.board(b, 'en')['text'].startswith('⚠️ Never share this code')
    assert said(b) == 'Never share this code, not even with IT. We will never ask for it.'


def test_key_combos():
    assert markup.combos('press Ctrl + Shift + N to open, or Cmd+K.') == [
        (6, 22, ['Ctrl', 'Shift', 'N']), (35, 40, ['Cmd', 'K'])]
    assert markup.combos('A + B is not a key combo') == []


def test_markup_beats_pass_the_storyboard_checks():
    from kinodraw.director.validate import validate as validate_storyboard
    board = board_of(CODE)
    report = validate_storyboard(board)
    assert not [e for e in report['errors'] if any(b['id'] in e for b in board['beats'] if b.get('markup'))]


def test_code_beats_keep_their_ids_and_the_timeline_has_no_caption_for_them():
    board = board_of(CODE)
    ids = [b['id'] for b in board['beats']]
    assert ids == [f'b{k:03d}' for k in range(1, len(ids) + 1)]
    code = beat_with(board, 'balance = 1000')
    cues = timeline._cues(code, 'en', lambda pos: 0., 1., set(), {})
    assert cues == []

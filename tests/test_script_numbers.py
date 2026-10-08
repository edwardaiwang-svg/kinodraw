"""How a script's numbers, prices, times, fractions and units are said, and that saying them never breaks the
match between the spoken and the written clause marks (script 05: "4:17 p.m. Eastern" failed the whole make)."""
import re

import pytest

from kinodraw import ingest, numbers, script
from kinodraw.director.validate import validate


def board_of(text, story='story', title=None):
    return script.build(ingest.read(text, title=title), story)


@pytest.mark.parametrize('display,spoken', [
    ('Just $3.50 each.', 'Just three fifty each.'),
    ('It costs $12.', 'It costs twelve dollars.'),
    ('A $1.05 stamp and $0.99 gum.', 'A one oh five stamp and ninety-nine cents gum.'),
    ('They raised $1.2 million.', 'They raised one point two million dollars.'),
    ('Every Saturday at 7 a.m. sharp.', 'Every Saturday at seven AM sharp.'),
    ('Doors at 10:05 PM, show at 9:30.', 'Doors at ten oh five PM, show at nine thirty.'),
    ('In 1969, 1969 people watched.', 'In nineteen sixty-nine, one thousand nine hundred sixty-nine people watched.'),
    ('Add 1/2 cup of milk and 1 1/2 cups flour.', 'Add half a cup of milk and one and a half cups flour.'),
    ('Add ½ tsp salt and 2 ¼ cups sugar.', 'Add half a teaspoon salt and two and a quarter cups sugar.'),
    ('Bake at 350°F for 3-4 minutes.', 'Bake at three hundred fifty degrees Fahrenheit for three to four minutes.'),
    ('Use 2 tbsp butter, walk 5 km.', 'Use two tablespoons butter, walk five kilometers.'),
    ('The 3rd try was 5x faster and 50% cheaper.', 'The third try was five times faster and fifty percent cheaper.'),
    # Script 09 (r01b): "$4.2M" was "four point two dollars M" and "$3.56M" "three dollars and fifty-six cents M".
    ('Revenue hit $4.2M, costs $3.56M.', 'Revenue hit four point two million dollars, costs three point five six million dollars.'),
    ('We raised $12K, then $1.5B.', 'We raised twelve thousand dollars, then one point five billion dollars.'),
    ('It cost $4.2 M, or €3M, or £2 bn.', 'It cost four point two million dollars, or three million euros, or two billion pounds.'),
    ('Margins rose 9%.', 'Margins rose nine percent.'),
])
def test_spoken_respelling(display, spoken):
    n = numbers.normalize(display, 'en')
    assert n.spoken == spoken
    assert not re.search(r'\d', n.spoken)


def test_a_m_and_p_m_mid_sentence_keep_spoken_and_display_clause_marks_equal():
    # Script 05: "At 4:17 p.m. Eastern time, ..." failed the whole make (clause punctuation differs).
    board = board_of('At 4:17 p.m. Eastern time, a voice crackled: the Eagle had landed.\n\n'
                     'At 10:56 p.m., a picture appeared. Dr. Lee and Mr. Smith watched in the U.S. that night.')
    report = validate(board)
    assert not [e for e in report['errors'] if 'punctuation' in e], report['errors']


def test_money_with_a_scale_keeps_its_written_form_in_the_captions():
    board = board_of('Q3 revenue hit $4.2M. Costs were $3.56M.')
    from kinodraw.engine import timeline
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    assert ' '.join(c['text'] for c in tl['captions']) == 'Q3 revenue hit $4.2M. Costs were $3.56M.'
    assert not [e for e in validate(board)['errors'] if 'punctuation' in e]


NEWS = ('ANCHOR: Good evening. The Elm Street Bridge reopens tomorrow.\n\n'
        'REPORTER (V/O): Drivers took a detour down Route 9. The old bridge, built in 1958, failed.\n\n'
        'REPORTER (V/O): The new bridge cost $4.2 million, most of it paid by the state Dept. of Transportation. '
        'Crews will pull the last barrels at 6 a.m. Tues., Oct. 14.\n\n'
        'SOT (Sam Okafor): About 2,300 cars a day used it, so the signals on Elm St. and River Rd. have been retimed.'
        '\n\nREPORTER (STAND-UP): The ribbon cutting is at 10 a.m. Saturday. Mail it by Sept. 3, or Jan. 5, 2027.')


def test_abbreviations_the_voice_expands_never_fail_the_make():
    # Script 28: "6 a.m. Tues., Oct. 14." is said "six AM Tues., October fourteenth." and the whole make failed on
    # "b006: clause punctuation differs between spoken and display text".
    report = validate(board_of(NEWS))
    assert not [e for e in report['errors'] if 'punctuation' in e], report['errors']


@pytest.mark.parametrize('text', ['the state Dept. of Transportation', 'on Elm St. and River Rd. today',
                                  'at 6 a.m. Tues., Oct. 14 sharp', 'on Mon. Feb. 2 we left'])
def test_an_abbreviation_period_is_no_clause_break(text):
    from kinodraw.engine.captions import clause_marks
    assert [m.group() for m in clause_marks(text, 'en')] == [','] * text.count(',')

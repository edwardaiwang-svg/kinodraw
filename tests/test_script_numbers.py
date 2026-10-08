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

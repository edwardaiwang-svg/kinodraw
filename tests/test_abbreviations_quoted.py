"""Shorthand right after an opening quotation mark, bracket or dash means what it means without one, and a mismatch
between the spoken and the written clause marks never stops a make (round 5: a quoted line starting with a month
abbreviation failed the whole render with "clause punctuation differs"). Every case is invented."""
import logging
import re

import pytest

from kinodraw import ingest, numbers, script, speech
from kinodraw.director.validate import validate
from kinodraw.engine import captions


def said(text):
    return speech.said_text(numbers.normalize(text, 'en').spoken, 'en')[0]


def marks(text):
    return [m.group() for m in captions.clause_marks(text, 'en')]


def words(text):
    return re.sub(r'[^\w\s-]', ' ', text).lower().split()


SENTENCES = [
    'Jan. 3rd, 1903, a storm came.', 'Sept. 9, we left port.', 'Mon. 5th, rain all day.', 'Tues. at noon, we met.',
    'Dr. Lee came in.', 'Mt. Hood rose up.', 'St. Louis was far.', 'Capt. Reyes waved.', 'Prof. Hale spoke.',
    '5 ft. away, it stopped.', '3 lbs. of flour, then salt.', '40 min. later, it rained.', 'Elm St. was quiet.',
    'No. 5 won.', 'Vol. 3 is out.', 'Apt. 4 was empty.', 'Acme Corp. hired him.', 'The Water Dept. closed it.',
    'Approx. 40 came.', 'Incl. tax, it was ten.', 'E.g. bread, milk.', 'Etc. and so on.', 'c. 1900, a mill stood.',
    'Est. 1985, the shop grew.']
# (opening mark, closing mark, clause marks it adds besides the colon): a straight single quote is no clause closer.
OPENERS = [('“', '”', 0), ('"', '"', 0), ('‘', '’', 0), ("'", "'", -1), ('(', ')', 0), ('[', ']', 0), ('—', '', 1),
           ('\n', '', 0)]


def quoted(sentence, opener, closer):
    if not closer:
        return 'He wrote: ' + opener + sentence
    if closer in ')]':
        return 'He wrote: ' + opener + sentence[:-1] + closer + '.'
    return 'He wrote: ' + opener + sentence + closer


@pytest.mark.parametrize('opener,closer,extra', OPENERS)
@pytest.mark.parametrize('sentence', SENTENCES)
def test_an_abbreviation_after_an_opening_mark_keeps_its_sense(sentence, opener, closer, extra):
    display = quoted(sentence, opener, closer)
    spoken = numbers.normalize(display, 'en').spoken
    assert marks(display) == marks(spoken), (display, spoken)
    assert len(marks(display)) == 1 + len(marks(sentence)) + extra, marks(display)
    if opener != '[':                   # a bracketed line is a stage direction: never said
        assert words(said(display)) == ['he', 'wrote'] + words(said(sentence)), said(display)


def test_a_quoted_logbook_date_keeps_the_same_clause_marks():
    display = 'He wrote: “Jan. 3rd, 1888.”'
    assert marks(display) == [':', ',', '.']
    assert marks(display) == marks(numbers.normalize(display, 'en').spoken)
    assert said(display) == 'He wrote: “January third, eighteen eighty-eight.'


def board_of(text):
    return script.build(ingest.read(text), 'story')


def test_a_quoted_month_abbreviation_validates_and_lays_out():
    board = board_of('The keeper wrote one line.\n\nIt reads: “Jan. 3rd, 1903. Fog all night, Capt. Reyes ashore.”')
    report = validate(board)
    assert report['ok'], report['errors']
    assert not [w for w in report['warnings'] if 'punctuation' in w], report['warnings']
    from kinodraw.engine import timeline
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    shown = ' '.join(c['text'] for c in tl['captions'])
    assert '“Jan. 3rd, 1903.' in shown and 'Capt. Reyes' in shown


# ------------------------------------------------------------------ a mismatch the lexicon does not explain
def test_a_clause_mark_mismatch_is_a_warning_never_an_error():
    board = board_of('First we wait; then we go. After that, we rest.')
    beat = board['beats'][0]
    beat['spoken']['en'] = 'First we wait then we go. After that we rest.'      # marks the written text lacks
    report = validate(board)
    assert report['ok'], report['errors']
    assert any('clause punctuation differs' in w for w in report['warnings'])


def test_captions_pair_the_marks_both_texts_share(caplog):
    display = 'First we wait; then we go. After that, we rest.'
    spoken = 'First we wait for a long, long while then we go. After that we rest.'     # a voice text edited by hand
    char_time = lambda pos: pos * .1                    # noqa: E731 - one tenth of a second per spoken character
    with caplog.at_level(logging.WARNING, logger='kinodraw.engine.captions'):
        cues = captions.cues_for_beat(spoken, display, 'en', char_time, len(spoken) * .1,
                                      fits=lambda t, lang: len(t) <= 30)
    assert 'clause marks differ' in caplog.text
    assert ' '.join(c[2] for c in cues).split() == display.split()           # captions keep the writing
    after = next(c for c in cues if c[2].startswith('After'))
    assert after[0] == pytest.approx(spoken.index('After') * .1 - .05, abs=.11)  # in step with the voice
    starts = [c[0] for c in cues]
    assert starts == sorted(starts)


def test_shared_marks_drops_only_the_unpaired_mark():
    md, ms = captions.shared_marks('He wrote: “Jan. 3rd.” Then, rain.', 'He wrote: “January third.” Then rain.', 'en')
    assert [m.group() for m in md] == [m.group() for m in ms] == [':', '.', '.']


# ------------------------------------------------------------------ circa
@pytest.mark.parametrize('display,spoken', [
    ('The mill was built c. 1900.', 'The mill was built circa nineteen hundred.'),
    ('A photo from ca. 1850s Ohio.', 'A photo from circa eighteen fifties Ohio.'),
    ('C. 1900, the mill opened.', 'Circa nineteen hundred, the mill opened.'),
    ('Ca. 1850, a road came.', 'Circa eighteen fifty, a road came.'),
    ('Built c.1900 of brick.', 'Built circa nineteen hundred of brick.'),
    ('Built ca.1850s of stone.', 'Built circa eighteen fifties of stone.'),
    ('The house (c. 1910) stood.', 'The house (circa nineteen ten) stood.'),
    ('Add 2 c. flour.', 'Add two cups flour.'),
    ('Arthur C. Clarke wrote it.', 'Arthur C. Clarke wrote it.'),
])
def test_circa_before_a_year_is_said_circa(display, spoken):
    assert said(display) == spoken
    assert marks(display) == marks(numbers.normalize(display, 'en').spoken)


def test_circa_captions_keep_the_writing():
    board = board_of('The mill was built c. 1900. C. 1850s maps show a road.')
    from kinodraw.engine import timeline
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    assert ' '.join(c['text'] for c in tl['captions']) == 'The mill was built c. 1900. C. 1850s maps show a road.'


# ------------------------------------------------------------------ listings, organisations, versions, list lines
@pytest.mark.parametrize('display,spoken', [
    ('1st mo. & sec. dep. req.', 'first month and security deposit required.'),
    ('Sec. dep. is due.', 'Security deposit is due.'),
    ('Rent $900/mo., utilities extra.', 'Rent nine hundred dollars a month, utilities extra.'),
    ('Acme Corp. Headquarters moved.', 'Acme Corporation Headquarters moved.'),
    ('The Water Dept. Office closed.', 'The Water Department Office closed.'),
    ('She joined Acme Corp. That year it grew.', 'She joined Acme Corporation. That year it grew.'),
    ('She works at Acme Corp. Bob does too.', 'She works at Acme Corporation. Bob does too.'),
    ('Update to v7 today.', 'Update to version seven today.'),
    ('Version v2.1 shipped.', 'Version two point one shipped.'),
    ('Run v2.1.3 now.', 'Run version two point one point three now.'),
    ('A V8 engine.', 'A V eight engine.'),
    ('Stops:\nElm St.\nOak Ave.\nPine Rd.', 'Stops: Elm Street. Oak Avenue. Pine Road.'),
    ('Venue:\nGrace Hall\nSt. Mary Church', 'Venue: Grace Hall, Saint Mary Church'),
    ('Detour via Main St.\nDr. Patel will guide you.', 'Detour via Main Street. Doctor Patel will guide you.'),
    ('In 1903, a storm.', 'In nineteen oh-three, a storm.'),
])
def test_leftover_shorthand_is_said_in_full(display, spoken):
    assert said(display) == spoken
    assert marks(display) == marks(numbers.normalize(display, 'en').spoken)


@pytest.mark.parametrize('display,expected', [
    ('Acme Corp. Headquarters moved.', ['.']),
    ('The Water Dept. Office closed.', ['.']),
    ('She joined Acme Corp. That year it grew.', ['.', '.']),
    ('1st mo. & sec. dep. req.', ['.']),
    ('Venue:\nGrace Hall\nSt. Mary Church', [':']),
])
def test_an_organisation_or_listing_period_breaks_a_caption_only_at_a_sentence_end(display, expected):
    assert marks(display) == expected

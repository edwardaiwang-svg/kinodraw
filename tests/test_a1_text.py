from pathlib import Path

import pytest

from kinodraw import ingest, script
from kinodraw.engine import captions, timeline

FIX = Path(__file__).parent / 'fixtures' / 'a1_text_story.md'


@pytest.mark.parametrize('text, title', [
    ('Pendo found his brave voice beside the winding river today.',
     'Pendo found his brave voice beside the winding river today'),
    ('Once upon a time, in the heart of the savanna lived a cub.',
     'Once upon a time'),
    ('Pendo watched Mara cross the river; King Kojo waited patiently on the bank.',
     'Pendo watched Mara cross the river'),
    ('Pendo watched Mara cross the river: King Kojo waited patiently on the bank.',
     'Pendo watched Mara cross the river'),
    ('Pendo watched Mara cross the river — King Kojo waited patiently on the bank.',
     'Pendo watched Mara cross the river'),
    ('Pendo watched Mara cross the river – King Kojo waited patiently on the bank.',
     'Pendo watched Mara cross the river'),
    ('Pendo walked beside Mara and looked up at the enormous black mane above him.',
     'Pendo walked beside Mara and looked up…'),
    ('Pendo walked beside Mara through tall grass toward the river where Kojo waited.',
     'Pendo walked beside Mara through tall grass toward…'),
    ('Pendo  walks beside Mara and looks up at the enormous mane over him.',
     'Pendo walks beside Mara and looks up…'),
])
def test_titles_and_agenda_use_complete_clauses(text, title):
    doc = ingest.read(text)
    assert doc.title == title
    assert script._short_title(text, 'en') == title
    board = script.build(ingest.read(text + '\n\nMara stayed near her friend.'))
    assert board['beats'][0]['display']['en'] == 'Today: ' + script.sentence_of(title, 'en')
    assert any('First: ' + script.sentence_of(title, 'en') in b['display']['en']
               for b in board['beats'] if b['kind'] == 'agenda')


def test_heading_precedes_filename_and_generated_title(tmp_path):
    assert ingest.read(FIX).title == 'Pendo and the Black Mane'
    path = tmp_path / 'unhelpful_filename.md'
    path.write_text(FIX.read_text().split('\n', 1)[1])
    doc = ingest.read(path)
    assert doc.title == 'Once upon a time, in the heart of the savanna'
    board = script.build(ingest.read('Pendo found his courage beside the river.'))
    chapter = next(c for c in board['chapters'] if c['kind'] == 'board')
    assert chapter['label']['en'] == ''
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    assert not any(c['title'].startswith('Part ') for c in tl['chapters'])


def test_quoted_heading_punctuation_survives_ingestion_and_title_build():
    title = 'Pendo said, “Come here.”'
    heading = 'Mara asked, “Why is Baba so scary?”'
    doc = ingest.read('# ' + title + '\n\n## ' + heading + '\n\nPendo waited.')
    assert doc.title == title and doc.preamble[0] == heading
    board = script.build(doc)
    assert board['beats'][0]['display']['en'] == 'Today: ' + title
    assert all('”.' not in b['display']['en'] for b in board['beats'])


@pytest.mark.parametrize('opening, closing', [('“', '”'), ('"', '"'), ('‘', '’'), ('「', '」'), ('『', '』')])
def test_english_sentence_split_keeps_whole_quote(opening, closing):
    quote = opening + 'Come here. Now.' + closing
    text = 'Pendo heard, ' + quote + ' Mara followed.'
    assert script.sentences(text, 'en') == ['Pendo heard, ' + quote, 'Mara followed.']


@pytest.mark.parametrize('opening, closing', [('“', '”'), ('"', '"'), ('‘', '’'), ('「', '」'), ('『', '』')])
def test_chinese_sentence_split_keeps_whole_quote(opening, closing):
    quote = opening + '过来。现在！' + closing
    text = '科乔说：' + quote + '彭多跑了过来。'
    assert script.sentences(text, 'zh') == ['科乔说：' + quote, '彭多跑了过来。']


@pytest.mark.parametrize('lang, quote, prefix, suffix, limit', [
    ('en', '“' + 'Come here, now; ' * 35 + 'stay with me.”', 'Kojo spoke: ', ' Mara listened.', 55),
    ('zh', '「' + '过来，现在；' * 35 + '留在这里。」', '科乔说：', '玛拉在听。', 110),
])
def test_long_quotes_remain_atomic_in_sentences_and_beats(lang, quote, prefix, suffix, limit):
    text = prefix + quote + suffix
    pieces = script._split_long(prefix + quote, lang, limit)
    assert any(quote in p for p in pieces)
    beats = script.beats_of([text], lang)
    assert any(quote in b for b in beats)
    assert not any(b.startswith(('”', '」')) for b in beats)


@pytest.mark.parametrize('lang, text, first', [
    ('en', 'Pendo said, “Come here.” Mara followed.', ' “Come here.”'),
    ('en', 'Pendo said, "Come here!" Mara followed.', ' "Come here!"'),
    ('zh', '彭多说：「过来！」玛拉跟着走。', '「过来！」'),
    ('zh', '彭多说：『过来。』玛拉跟着走。', '『过来。』'),
])
def test_caption_cues_attach_closing_quotes(lang, text, first):
    cues = captions.cues_for_beat(text, text, lang, lambda p: p / 10, 10,
                                 fits=lambda t, lang: len(t.strip()) <= len(first.strip()))
    assert any(first.strip() in c[2] for c in cues)
    assert not any(c[2].startswith(('”', '」', '』')) for c in cues)


@pytest.mark.parametrize('lang, text, expected', [
    ('en', 'Pendo said “Stay.” Next!', ['Pendo ', 'said ', '“Stay.” ', 'Next!']),
    ('zh', '彭多「来。」走', ['彭', '多', '「', '来。」', '走']),
])
def test_caption_units_never_leave_punctuation_or_quotes_alone(lang, text, expected):
    # Force punctuation to be separately tokenized in Latin text too.
    if lang == 'en':
        text = 'Pendo said “Stay . ” Next !'
    assert captions.units(text, lang) == expected
    pieces = captions.split_long(text, lang, fits=lambda t, lang: len(t) <= 4)
    assert not any(p.strip().startswith(('.', '!', '。', '”', '」')) for p in pieces)


@pytest.mark.parametrize('text', [
    'Pendo joined the pride.Pendo smiled.',
    'Pendo joined the pride.she smiled.',
    'Pendo stopped!Mara waited?Kojo nodded…Pendo smiled.',
    'Pendo said, “Come here.”Mara followed.',
    'Pendo called Mara “brave”Mara smiled.',
    'Pendo called Mara ‘brave’Mara smiled.',
    'Pendo called Mara ‘brave’mara smiled.',
    'Pendo joined the pride."Come here."',
])
def test_latin_display_beats_and_captions_repair_sentence_spacing(text):
    expected = text.replace('.Pendo', '. Pendo').replace('.she', '. she')
    expected = expected.replace('!Mara', '! Mara').replace('?Kojo', '? Kojo')
    expected = expected.replace('…Pendo', '… Pendo').replace('”Mara', '” Mara').replace('’Mara', '’ Mara')
    expected = expected.replace('’mara', '’ mara')
    expected = expected.replace('pride."', 'pride. "')
    board = script.build(ingest.read(text), story='story')
    assert board['beats'][0]['display']['en'] == expected
    cues = captions.cues_for_beat(text, text, 'en', lambda p: p / 10, 10, fits=lambda t, lang: True)
    # One cue per sentence (a caption never runs on into the next sentence); the spacing between them is repaired.
    assert ' '.join(c[2] for c in cues) == expected
    assert ' '.join(captions.balanced_lines(text, 'en')) == expected
    assert ingest._sentence_spacing('Dr. Kojo paid 3.14 dollars at friendr.nl at 5 p.m. Pendo waited.', 'en') == \
        'Dr. Kojo paid 3.14 dollars at friendr.nl at 5 p.m. Pendo waited.'


def test_chinese_beats_and_captions_keep_quotes_and_have_no_spaces():
    text = '科乔说：“过来。现在！”彭多走进狮群。玛拉笑了。'
    assert script.sentences(text, 'zh') == ['科乔说：“过来。现在！”', '彭多走进狮群。', '玛拉笑了。']
    assert script.beats_of([text], 'zh') == [text]
    cues = captions.cues_for_beat(text, text, 'zh', lambda p: p / 10, 10, fits=lambda t, lang: True)
    assert [c[2] for c in cues] == ['科乔说：“过来。现在！”', '彭多走进狮群。', '玛拉笑了。']


def test_caption_split_inside_straight_quote_preserves_spacing_and_speech_offsets():
    text = 'Pendo said "Come here. Now."Mara followed.'
    cues = captions.cues_for_beat(text, text, 'en', lambda p: p / 10, 10,
                                 fits=lambda t, lang: len(t.strip()) <= 12)
    assert [c[2] for c in cues] == ['Pendo said', '"Come here.', 'Now."', 'Mara', 'followed.']
    assert ' '.join(c[2] for c in cues) == 'Pendo said "Come here. Now." Mara followed.'
    assert captions.balanced_lines(cues[2][2], 'en') == ['Now."']
    assert cues[2][0] == pytest.approx(text.index(' Now.') / 10 - .05)


@pytest.mark.parametrize('name', ['Kojo', 'O’Neill'])
def test_single_quoted_dialogue_keeps_contractions_and_nested_quotes(name):
    text = 'Mara said, ‘Don’t wait. ' + name + ' said “Come here. Now.”’ Pendo followed.'
    assert script.sentences(text, 'en') == [
        'Mara said, ‘Don’t wait. ' + name + ' said “Come here. Now.”’', 'Pendo followed.']


@pytest.mark.parametrize('lang, text, limit', [('en', 'Pendo ' * 60 + '—', 55),
                                             ('zh', '彭多' * 60 + '：', 110)])
def test_long_sentence_with_trailing_clause_mark_stays_intact(lang, text, limit):
    assert script._split_long(text, lang, limit) == [text]


@pytest.mark.parametrize('lang, text', [
    ('en', 'Pendo said, “Come here.”'), ('en', 'Pendo asked, “Why is Baba so scary?”'),
    ('en', 'Pendo called, "Wait!"'), ('zh', '彭多说：「过来。」'), ('zh', '彭多问：『爸爸为什么这么吓人？』'),
    ('en', 'Pendo found courage…'),
])
def test_takeaway_and_titles_do_not_add_period_after_quote_or_ellipsis(lang, text):
    assert script.sentence_of(text, lang) == text
    board = {'lang': lang, 'beats': [{'kind': 'take', 'display': {lang: ''}, 'spoken': {lang: ''},
                                    'take': {'headline': {lang: text}}}]}
    script.sync_takes(board)
    assert board['beats'][0]['display'][lang] == script.take_text(text, lang)


def test_story_build_and_timeline_keep_dialogue_attached():
    board = script.build(ingest.read(FIX), story='story')
    text = ' '.join(b['display']['en'] for b in board['beats'])
    assert text == ' '.join(ingest.read(FIX).preamble)
    assert script.sentences('“Come here. Now.” His voice rolled across the river.', 'en') == \
        ['“Come here. Now.”', 'His voice rolled across the river.']
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    assert '“Why is Baba so scary?”' in text and '“Come here. Now.”' in text
    assert not any(c['text'].startswith('”') for c in tl['captions'])
    assert not any('.”.' in b['display']['en'] or 'pride.Pendo' in b['display']['en'] for b in board['beats'])

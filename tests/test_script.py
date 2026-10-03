import re
from pathlib import Path

import pytest

from kinodraw import ingest, script
from kinodraw.engine import timeline

FIX = Path(__file__).parent / 'fixtures'
EN_PUNCT = re.compile(r'[,.;:?!](?=\s|$|["”’)])|—')
ZH_PUNCT = re.compile(r'[，。；：？！、—]')


@pytest.fixture(params=['printing_press.md', 'photosynthesis.txt', 'sleep_zh.md'])
def board(request):
    return script.build(ingest.read(FIX / request.param))


def test_structure(board):
    kinds = [c['kind'] for c in board['chapters']]
    assert kinds[0] == 'intro' and kinds[-1] == 'outro'
    sections = [c for c in board['chapters'] if c['kind'] == 'section']
    assert 2 <= len(sections) <= script.MAX_SECTIONS and 'agenda' in kinds
    agenda_beats = [b for b in board['beats'] if b['chapter'] == 'agenda']
    assert len(agenda_beats) == len(sections)
    lang = board['lang']
    for s in sections:                          # each section says its title card, then its takeaway note
        beats = [b for b in board['beats'] if b['chapter'] == s['id']]
        assert beats[0]['kind'] == 'opener' and s['title'][lang].rstrip('.。?？') in beats[0]['display'][lang]
        assert beats[0]['display'][lang].startswith(s['label'][lang])
        head = beats[-1]['take']['headline'][lang]
        assert beats[-1]['kind'] == 'take' and beats[-1]['display'][lang] == script.take_text(head, lang)
        assert all(b['kind'] == 'narration' for b in beats[1:-1])
        assert not script.CONTEXT[lang].match(head), head          # a takeaway stands on its own
    ids = [b['id'] for b in board['beats']]
    assert len(ids) == len(set(ids))
    order = [b['chapter'] for b in board['beats']]
    assert [c['id'] for c in board['chapters']] == list(dict.fromkeys(order))


def test_spoken_text(board):
    lang = board['lang']
    punct = EN_PUNCT if lang == 'en' else ZH_PUNCT
    hi = (script.EN_BEAT if lang == 'en' else script.ZH_BEAT)[2]
    for b in board['beats']:
        spoken, display = b['spoken'][lang], b['display'][lang]
        assert not re.search(r'\d', spoken), spoken
        assert punct.findall(spoken) == punct.findall(display)
        assert script.size(display, lang) <= hi
        assert not re.search(r'[?？!！][.。]', display), display


def test_timeline_accepts_skeleton(board):
    tl = timeline.layout(board, board['lang'], timeline.synthetic_clips(board, board['lang']))
    assert len(tl['transitions']) == sum(c['kind'] == 'section' for c in board['chapters'])
    assert tl['captions'] and tl['duration'] > 30


def test_markdown_and_plain_text_parsing():
    doc = ingest.read('# Title\n\nIntro text here.\n\n## A\n\nFirst **bold** [link](http://x) para.\n\n- item one\n- item two\n\n## B\n\nSecond.')
    assert doc.title == 'Title' and doc.preamble == ['Intro text here.']
    assert [s.heading for s in doc.sections] == ['A', 'B']
    assert doc.sections[0].paragraphs == ['First bold link para.', 'item one', 'item two']
    assert ingest.read('只有一段中文文本，没有标题。').lang == 'zh'


def test_an_edited_takeaway_is_what_the_narrator_says():
    board = script.build(ingest.read(FIX / 'printing_press.md'))
    take = next(b for b in board['beats'] if b['kind'] == 'take')
    take['take']['headline'] = {'en': 'Gutenberg made 180 Bibles'}
    script.sync_takes(board)
    assert take['display']['en'] == 'Key takeaway: Gutenberg made 180 Bibles.'
    assert take['spoken']['en'] == 'Key takeaway: Gutenberg made one hundred eighty Bibles.'


def test_a_takeaway_never_leans_on_the_sentence_before_it():
    # "We call this ..." names something the previous sentence described: skipped like "This is called ...".
    assert script.headline(['The sun heats the water in the ocean. We call this evaporation.'], 'Evaporation', 'en') \
        == 'The sun heats the water in the ocean.'
    # Nothing short enough stands alone: a longer sentence that still fits the note's three lines beats the title.
    text = 'When the drops in a cloud get too big and heavy, they fall to the ground. We call this precipitation.'
    assert script.headline([text], 'Precipitation', 'en') == 'When the drops in a cloud get too big and heavy, they fall to the ground.'
    assert script.headline(['Rain falls. ' + 'Tiny drops of water float high above us in very cold clouds, then join into much bigger and heavier drops.'],
                           'Precipitation', 'en') == 'Precipitation.'          # over 18 words: the title

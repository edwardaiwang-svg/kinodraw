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


def test_a_long_script_pasted_on_the_command_line_is_the_script_not_a_file_name(tmp_path, monkeypatch):
    """kinodraw new "<a whole script>" crashed with OSError [Errno 63] File name too long."""
    from kinodraw import cli, director
    monkeypatch.setattr(director, 'direct', lambda *a: {})
    text = ' '.join(['Honey never spoils because it holds so little water.'] * 100)[:5000].strip()
    assert len(text) >= 4990
    cli.main(['new', text, '-o', str(tmp_path / 'p')])
    assert (tmp_path / 'p' / 'script.md').read_text(encoding='utf-8') == text


SKY = '''# Why the Sky Is Blue

Look up on a clear afternoon and the sky is a deep, bright blue. But sunlight itself looks white. So where does the blue come from?

## Sunlight is a mix of colors

White sunlight is really every color of the rainbow traveling together. A prism splits it apart into red, orange, yellow, green, blue and violet. Each color is a wave, and blue waves are much shorter than red ones.

## Air scatters short waves

When sunlight hits the tiny molecules of nitrogen and oxygen in the air, the short blue waves bounce off in every direction. Red and yellow light mostly passes straight through. That scattered blue light reaches your eyes from all over the sky, so the whole sky glows blue.

## Sunsets turn red

At sunset, the light travels through much more air to reach you. Almost all the blue is scattered away before it arrives, and the reds and oranges are what is left. That is why evenings glow orange and pink.

## Key idea

The sky is blue because air scatters short blue light far more than long red light.
'''


def test_a_key_idea_heading_closes_the_video_instead_of_being_a_part():
    """The first offline video of a stranger's script said "And finally: Key idea." and "Part four: Key idea.":
    a closing "Key idea" (or "Bottom line", "In short", ...) is the wrap-up, said once before the sign-off."""
    board = script.build(ingest.read(SKY))
    said = [b['display']['en'] for b in board['beats']]
    assert not any('Key idea' in line for line in said), said
    assert [c['title']['en'] for c in board['chapters'] if c['kind'] == 'section'] == [
        'Sunlight is a mix of colors', 'Air scatters short waves', 'Sunsets turn red']
    outro = [b for b in board['beats'] if b['chapter'] == 'outro']
    assert [b['display']['en'] for b in outro] == [
        'The sky is blue because air scatters short blue light far more than long red light.', 'Thanks for watching!']
    assert said[4] == 'And finally: Sunsets turn red.'
    for heading in ('Key idea', 'Key ideas', 'The big idea', 'Main point', 'Bottom line', 'In short', 'To sum up', 'Recap'):
        assert script.CONCLUSION.match(heading), heading
    for heading in ('Shortcuts', 'Recapture the flag', 'Mainframes'):
        assert not script.CONCLUSION.match(heading), heading


def _said(board):
    lang = board['lang']
    return [b['display'][lang] for b in board['beats']]


def test_a_takeaway_is_never_the_sentence_said_just_before_it():
    """A one-sentence section read its sentence, then "Key takeaway: <the same sentence>" straight after."""
    for name, take in (('tiny.md', 'Key takeaway: Bees work hard.'),
                       ('sky_blue.md', 'Key takeaway: Scattering in the air.')):
        board = script.build(ingest.read(FIX / name))
        said = _said(board)
        assert take in said, said
        for k, b in enumerate(board['beats']):
            if b['kind'] == 'take':
                head = b['take']['headline']['en']
                assert script.sentences(said[k - 1], 'en')[-1] != head, (name, head)


def test_a_closing_summary_line_is_said_once_as_the_takeaway():
    """bicycle.md ends each part with a one-line summary paragraph: it is the takeaway, said once, not twice."""
    board = script.build(ingest.read(FIX / 'bicycle.md'))
    said = ' '.join(_said(board))
    for line in ('Even without pedals, the first bicycle beat walking.',
                 'Chains and air-filled tyres made cycling safe and comfortable.',
                 'A cheap machine gave millions of people the freedom to travel.'):
        assert said.count(line) == 1 and f'Key takeaway: {line}' in said, line


def test_a_section_title_that_makes_a_claim_is_its_main_point():
    """The takeaways of a stranger's first video were side remarks ("Red and yellow light mostly passes straight
    through."): a sentence must say what the writer's title says, or the title is the takeaway."""
    board = script.build(ingest.read(SKY))
    takes = [b['take']['headline']['en'] for b in board['beats'] if b['kind'] == 'take']
    assert takes == ['White sunlight is really every color of the rainbow traveling together.',
                     'Air scatters short waves.', 'Sunsets turn red.']


def test_a_chinese_agenda_counts_two_things_as_liang():
    """A two-part Chinese script opened its agenda with "本期我们聊二件事", which no Chinese speaker says."""
    board = script.build(ingest.read('# 关于蜂蜜的两件事\n\n蜂蜜是人类至今还在吃的最古老的食物之一。\n\n## 它不会变质\n\n'
                                     '考古学家发现过三千多年前的蜂蜜罐，里面的蜂蜜仍然可以吃。\n\n## 蜜蜂很辛苦\n\n'
                                     '为了酿一罐蜂蜜，蜜蜂要拜访大约两百万朵花。'))
    agenda = [b['display']['zh'] for b in board['beats'] if b['kind'] == 'agenda']
    assert agenda[0] == '本期我们聊两件事。第一，它不会变质。', agenda

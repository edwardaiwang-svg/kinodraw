from kinodraw import ingest, script
from kinodraw.engine import captions


def test_inches_do_not_open_a_quotation():
    text = 'The class measured a 12" ruler. ' + 'The lesson continued with another ordinary example. ' * 10
    assert len(script.sentences(text.strip(), 'en')) == 11
    assert len(script.beats_of([text], 'en')) > 1


def test_urls_and_abbreviations_survive_spacing():
    text = 'A Ph.D. student visits https://example.ai/data.json. Pendo smiled.'
    assert ingest._sentence_spacing(text, 'en') == text
    assert ingest._sentence_spacing('pride.Pendo smiled.', 'en') == 'pride. Pendo smiled.'


def test_url_scheme_is_not_a_title_clause_boundary():
    title = ingest.read('Today we explore https://example.com and explain how this useful website works.').title
    assert 'https://example.com' in title
    assert not title.endswith('https')
    for url in ('https://example.ai:8080/data.json', 'https://example.ai/a,b'):
        assert url in ingest.read(f'Today we explore {url} and explain how this useful website works.').title
    assert ingest.read('# Learn at https://example.ai/search?q=lion now\n\nPendo smiled.').title == \
        'Learn at https://example.ai/search?q=lion now'


def test_straight_opening_quote_stays_with_chinese_dialogue():
    text = '科乔认真地看着彭多和玛拉，然后压低自己粗重的声音说："过来。现在！"彭多跑了过来。'
    cues = captions.cues_for_beat(text, text, 'zh', lambda p: p / 10, 10)
    assert not any(cue[2].endswith(':"') or cue[2].endswith('："') for cue in cues)
    assert any('"过来' in cue[2] for cue in cues)


def test_authored_headings_receive_sentence_spacing():
    board = script.build(ingest.read('# Pendo joined the pride.Pendo smiled.\n\n'
                                   '## River.Mara waited.\n\nPendo walked.\n\n'
                                   '## Grass.Kojo watched.\n\nMara smiled.'))
    assert board['title']['en'] == 'Pendo joined the pride. Pendo smiled.'
    assert all('pride.Pendo' not in b['display']['en'] and 'River.Mara' not in b['display']['en']
               and 'Grass.Kojo' not in b['display']['en'] for b in board['beats'])

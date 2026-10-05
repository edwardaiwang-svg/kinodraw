"""Offline audit failures: preserve literal objects while rejecting misleading senses."""
import numpy as np
import pytest
from kinodraw import ingest, numbers, script
from kinodraw.director.rules import RulesDirector

@pytest.fixture(scope='module', params=['en', 'zh'])
def rules(request):
    return RulesDirector(request.param)


def test_of_is_part_of_the_emoji_object_name():
    r = RulesDirector('en')
    assert not r._is_head('fl_cut_of_meat', 'cut')
    assert r._is_head('fl_cut_of_meat', 'cut of meat')
    assert not r._is_head('fl_hot_springs', 'spring')

@pytest.mark.parametrize('lang,did,phrase,text', [
    ('en', 'leaf_sun', 'sunlight', 'Sunlight hits the ground more directly.'),
    ('en', 'solar_panel', 'sunlight', 'The sunlight comes in at a low angle.'),
    ('en', 'buyback_arrow', 'share', 'Now you can share a pizza fairly.'),
    ('en', 'debt_fraction', None, 'A fraction tells us how many equal parts we have.'),
    ('en', 'crossroads_sign', 'directions', 'The arrows point in opposite directions.'),
    ('zh', 'leaf_sun', '阳光', '阳光要穿过更长的一段空气。'),
    ('zh', 'fl_optical_disk', '蓝光', '蓝光的波长比较短，最容易被空气散开。'),
])
def test_wrong_senses_fail_even_for_margins(lang, did, phrase, text):
    assert not RulesDirector(lang)._meaning_allows(did, phrase, text)

@pytest.mark.parametrize('lang,text,term,gloss', [
    ('en', 'The bottom number is called the denominator. It tells you how many equal pieces the whole is cut into.',
     'Denominator', 'It tells you how many equal pieces the whole is cut into.'),
    ('en', 'The top number is called the numerator. It tells you how many of those pieces you are talking about.',
     'Numerator', 'It tells you how many of those pieces you are talking about.'),
    ('zh', '光被撞到以后，会向四面八方散开，这就叫做散射。', '散射', '光被撞到以后，会向四面八方散开'),
])
def test_complete_definition(lang, text, term, gloss):
    r = RulesDirector(lang)
    v, _ = r._definition({'id': 'b'}, text, numbers.normalize(text, lang), [])
    assert v['term'][lang] == term
    assert v['text'][lang] == gloss
    assert v['trigger'][lang] in numbers.normalize(text, lang).spoken


def test_rainbow_and_coat_can_survive_low_topic_rank():
    for lang, did, phrase, text in [('zh','fl_rainbow','彩虹','下雨以后出现的彩虹，就是这些颜色被分开了。'),
                                    ('en','fl_coat','coat','They took his bag, his coat and his money.')]:
        r = RulesDirector(lang)
        r.topic = {'s': np.full(len(r.ids), 350)}
        assert did in {h.id for h in r._concepts(text, [], 's')}


def test_questions_and_story_connectors_are_not_takeaways():
    text = 'Soon a priest came down the road. He crossed to the other side and kept walking. The man was all alone and very sad.'
    assert script.headline([text], 'Two Who Walked Past', 'en') == 'The man was all alone and very sad.'
    text = '到了傍晚，太阳在地平线附近，阳光要穿过更长的一段空气才能到达我们的眼睛。蓝光在路上差不多都被散走了。'
    assert '?' not in script.headline([text], '为什么傍晚是红色的？', 'zh')
    assert '？' not in script.headline([text], '为什么傍晚是红色的？', 'zh')


def test_hooks_preserve_source_words_and_picture_cache_resets(monkeypatch):
    board = script.build(ingest.read('# Seasons\n\n## Summer\nSunlight warms the land. The days grow longer.\n\n## Winter\nThe nights grow longer. The land gets cold.'))
    assert all(c.get('hook', {}).get('en') for c in board['chapters'] if c['kind'] == 'section')
    r = RulesDirector('en')
    seen = []
    original = r._concepts
    def concepts(text, recent, chapter, listing=False):
        if chapter == 's1':
            r.pictures['test'] = 'fl_coat'
        if chapter == 's2':
            seen.append('test' in r.pictures)
        return original(text, recent, chapter, listing)
    monkeypatch.setattr(r, '_concepts', concepts)
    r.direct(board)
    assert seen and not any(seen)


def test_hooks_belong_only_to_section_cards():
    board = script.build(ingest.read('# Honey\n\nHoney keeps well in a sealed jar.'))
    assert any(c['kind'] == 'board' for c in board['chapters'])
    assert all('hook' not in c for c in board['chapters'] if c['kind'] != 'section')


@pytest.mark.parametrize('text', [
    'There are 30 books on the shelf.',
    'Ana said: “Books help us understand the world.”',
    'The tube is called a stem. It carries water up the plant.',
    'Ana said: “Books help us understand the world.” There are 30 books on the shelf.',
])
def test_single_detectors_preserve_their_original_ids(text):
    r = RulesDirector('en')
    norm = numbers.normalize(text, 'en')
    beat = {'id': 'b001', 'chapter': 's1', 'kind': 'narration',
            'display': {'en': text}, 'spoken': {'en': norm.spoken}, 'visuals': []}
    board = {'lang': 'en', 'title': {'en': 'Objects'},
             'chapters': [{'id': 's1', 'kind': 'board', 'title': {'en': 'Objects'}}], 'beats': [beat]}
    r.topic = r._topic_ranks(board)
    expected = [found[0] for detect in (r._quote, r._definition, r._number)
                if (found := detect(beat, text, norm, []))]
    r.direct(board)
    actual = [v for v in beat['visuals'] if v['type'] in {'quote', 'glossary', 'stat', 'grid100'}]
    assert actual == expected


def test_multiple_definitions_only_suffix_the_additional_notes():
    text = ('The bottom number is called the denominator. It counts the equal pieces in the whole. '
            'The top number is called the numerator. It counts the pieces we have.')
    board = script.build(ingest.read('# Fractions\n\n' + text))
    RulesDirector('en').direct(board)
    notes = [(b, v) for b in board['beats'] for v in b['visuals'] if v['type'] == 'glossary']
    assert [v['term']['en'] for _, v in notes] == ['Denominator', 'Numerator']
    assert [v['id'] for b, v in notes] == [notes[0][0]['id'] + 'g', notes[1][0]['id'] + 'g1']
    ids = [v['id'] for b in board['beats'] for v in b['visuals']]
    assert len(ids) == len(set(ids))


def test_a_long_final_list_is_not_moved_to_an_oversized_takeaway():
    text = ('# Rest\n\n## Memory\n睡眠也在帮我们整理记忆。新知识会在夜里被大脑重新播放。\n\n'
            '## 睡多久才够？\n成年人需要足够的睡眠。调查显示，许多人经常睡不够。\n\n'
            '想要睡得好，可以试试这几个方法：每天固定时间起床，睡前一小时少看手机，下午以后少喝咖啡。')
    board = script.build(ingest.read(text))
    final = [b for b in board['beats'] if b['chapter'] == 's2']
    assert final[-2]['kind'] == 'narration' and '少喝咖啡' in final[-2]['display']['zh']
    assert script.size(final[-1]['take']['headline']['zh'], 'zh') <= 28


def test_named_curated_drawings_keep_their_score_at_low_topic_rank():
    r = RulesDirector('en')
    text = 'The Sun warms the Earth.'
    r.topic = {'s1': np.ones(len(r.ids), int)}
    before = {h.id: h.score for h in r._concepts(text, [], 's1') if r._names(h.id, h.phrase or '')}
    assert before
    r.topic = {'s1': np.full(len(r.ids), 350)}
    after = {h.id: h.score for h in r._concepts(text, [], 's1') if r._names(h.id, h.phrase or '')}
    assert after == before


def test_road_signs_still_illustrate_road_directions():
    assert RulesDirector('en')._meaning_allows('crossroads_sign', 'directions',
                                              'The road sign points toward two different streets.')


@pytest.mark.parametrize('texts,lang,expected', [
    (['Archaeologists have found pots of honey more than 3,000 years old.'],
     'en', 'Archaeologists have found pots…'),
    (['白天，大脑工作时会产生很多代谢废物。'], 'zh', '白天，大脑工作时会产生很多代谢…'),
    (['睡眠也在帮我们整理记忆。'], 'zh', '睡眠也在帮我们整理记忆。'),
    (['White sunlight is a mix. Why is the sky blue?'], 'en', 'Why is the sky blue?'),
])
def test_section_hooks_are_exact_source_excerpts(texts, lang, expected):
    assert script.hook(texts, lang) == expected
    assert expected.removesuffix('…') in ' '.join(texts)


def test_sleep_source_repairs_keep_literal_objects_and_synced_takeaway():
    from pathlib import Path
    from kinodraw.director.annotate import annotate

    board = script.build(ingest.read(Path(__file__).parent / 'fixtures' / 'sleep_zh.md'))
    RulesDirector('zh').direct(board)
    annotate(board)
    beats = {b['id']: b for b in board['beats']}
    assert beats['b008']['visuals'] == [
        {'id': 'b008v0', 'type': 'cluster', 'items': [{'doodle': 'narrator_explain'}],
         'relation': 'none'}]
    assert beats['b016']['visuals'][1] == {
        'id': 'b016v1', 'type': 'cluster',
        'items': [{'doodle': 'smartphone', 'label': {'zh': '手机'}, 'trigger': {'zh': '手机'}}],
        'relation': 'none', 'trigger': {'zh': '手机'}}
    take = beats['b009']
    assert take['take'] == {'headline': {'zh': '白天，大脑工作时会产生很多代谢废物。'}}
    assert take['display'] == take['spoken'] == {'zh': '本节要点：白天，大脑工作时会产生很多代谢废物。'}
    assert take['direction'] == [
        {'i': 0, 'span': [0, 23], 'role': 'tagline', 'energy': 1, 'scene': 'board',
         'emphasis': '代谢废物',
         'options': {'scene': ['board'], 'emphasis': ['代谢废物', '白天'], 'energy': [0, 1]},
         'source': 'rules'}]


def test_review_spanish_context_keeps_literal_buyback():
    text = 'La empresa realiza una recompra de acciones.'
    r = RulesDirector('es')
    assert r._meaning_allows('buyback_arrow', 'recompra', text)
    board = script.build(ingest.Document('Recompra', 'es', [text], []))
    r.direct(board)
    assert 'buyback_arrow' in {i['doodle'] for b in board['beats']
                              for v in b['visuals'] for i in v.get('items', [])}
    assert not r._meaning_allows('buyback_arrow', 'compartir', 'Podemos compartir una pizza.')
    assert r._meaning_allows('leaf_sun', 'hoja', 'La hoja permite la fotosíntesis.')
    assert not r._meaning_allows('leaf_sun', 'luz', 'La luz llega al suelo.')


def test_review_chinese_hot_springs_keep_literal_head():
    text = '温泉中含有丰富的矿物质。'
    r = RulesDirector('zh')
    assert r._is_head('fl_hot_springs', '温泉')
    board = script.build(ingest.Document('温泉', 'zh', [text], []))
    r.direct(board)
    assert 'fl_hot_springs' in {i['doodle'] for b in board['beats']
                               for v in b['visuals'] for i in v.get('items', [])}
    en = RulesDirector('en')
    assert not en._is_head('fl_hot_springs', 'spring')
    en.topic = {'s1': np.ones(len(en.ids), int)}
    assert 'fl_hot_springs' not in {h.id for h in en._concepts('Spring and autumn bring milder weather.', [], 's1')}
    es = RulesDirector('es')
    assert es._is_head('fl_hot_springs', 'aguas termales')
    assert not es._is_head('fl_hot_springs', 'primavera')


def test_review_definitions_keep_first_source_note_and_id():
    text = 'Molten rock called magma. The tube is called a stem. It carries water up the plant.'
    board = script.build(ingest.Document('Definitions', 'en', [text], []))
    RulesDirector('en').direct(board)
    notes = [v for b in board['beats'] for v in b['visuals'] if v['type'] == 'glossary']
    assert notes[0] == {'id': 'b002g', 'type': 'glossary', 'term': {'en': 'Magma'},
                        'text': {'en': 'Rock'}, 'trigger': {'en': 'magma'}}
    assert [(v['id'], v['term']['en']) for v in notes] == [('b002g', 'Magma'), ('b002g1', 'Stem')]
    assert notes[1]['text']['en'] == 'It carries water up the plant.'
    r = RulesDirector('en')
    invalid_first = 'This process is called cooling. Molten rock called magma.'
    note, _ = r._definition({'id': 'b003'}, invalid_first, numbers.normalize(invalid_first, 'en'), [])
    assert note['id'] == 'b003g' and note['term']['en'] == 'Magma'


def test_review_takeaway_fallbacks_keep_complete_facts_and_exclusions():
    fact = ('The injured traveler remained alone beside the road for many hours without food or water '
            'until a stranger finally stopped to help him.')
    text = 'Soon a priest came down the road. ' + fact
    assert script.headline([text], 'Who helped the traveler?', 'en') == fact
    for excluded in ('Then a traveler came down the road.', 'Think about the traveler.',
                     'Imagine a traveler beside the road.', 'Long ago, a traveler left home.',
                     'He waited for help beside the road.', 'We call this kindness.',
                     'The traveler is called a stranger.', 'Who would help the traveler?'):
        assert script.headline([excluded + ' ' + fact], 'Who helped the traveler?', 'en') == fact
    assert script.headline(['Why did the traveler need help?'], 'Who helped the traveler?', 'en') == ''
    assert script.headline(['Think about the traveler.'], 'Imagine the journey', 'en') == ''
    doc = ingest.Document('Questions', 'en', [], [
        ingest.Section('Who helped the traveler?', ['Why did the traveler need help?']),
        ingest.Section('What happened next?', ['Where did the traveler go?'])])
    board = script.build(doc)
    assert not any(b['kind'] == 'take' for b in board['beats'])
    assert [b['display']['en'] for b in board['beats'] if b['kind'] == 'narration'] == [
        'Why did the traveler need help?', 'Where did the traveler go?']

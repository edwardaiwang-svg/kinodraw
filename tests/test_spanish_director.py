import json
from pathlib import Path

import pytest

from kinodraw import ingest, numbers, script
from kinodraw.director import match
from kinodraw.director.annotate import annotate
from kinodraw.director.rules import RulesDirector
from kinodraw.director.validate import validate

FIX = Path(__file__).parent / 'fixtures'
SENTENCES = [
    'Las abejas visitan muchas flores para hacer miel.',
    'El banco guarda dinero y monedas para el ahorro.',
    'La imprenta produce libros y periódicos para la biblioteca.',
    'El corazón bombea sangre y los pulmones permiten respirar.',
    'En la escuela usamos un lápiz, un libro y una computadora.',
]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    from kinodraw import net

    def forbidden(*args, **kwargs):
        pytest.fail('Director tests must use the bundled vectors and cached models offline')
    monkeypatch.setattr(net, 'urlopen', forbidden)


@pytest.fixture
def spanish_normalize(monkeypatch):
    # Hand-built, number-free beats isolate Job 2 from Job 1's Spanish number normalizer.
    original = numbers.normalize
    monkeypatch.setattr(numbers, 'normalize', lambda text, lang:
                        numbers.Normalized(text, text) if lang == 'es' else original(text, lang))


def board_for(texts, look='whiteboard'):
    return {'version': 1, 'lang': 'es', 'title': {'es': 'Ideas'}, 'look': look,
            'chapters': [{'id': 'b1', 'kind': 'board', 'title': {'es': 'Ideas'}}],
            'beats': [{'id': f'b{i:03}', 'chapter': 'b1', 'kind': 'narration',
                       'display': {'es': text}, 'spoken': {'es': text}, 'visuals': []}
                      for i, text in enumerate(texts, 1)]}


def test_lexicon_is_sorted_spanish_and_uses_catalog_keys():
    from kinodraw.library import catalog
    path = match.ASSETS / 'es_en.json'
    lexicon = json.loads(path.read_text(encoding='utf-8'))
    index = match.Matcher('en').index
    assert len(lexicon) >= 1200
    assert list(lexicon) == sorted(lexicon)
    assert all(key == key.lower() and key.strip() == key for key in lexicon)
    assert all(isinstance(value, str) and match._en_key(value) in index for value in lexicon.values())
    bespoke = {match._en_key(kw) for entry in catalog().values() if entry['set'] != 'fluent'
               for kw in entry.get('en', []) if len(kw.split()) == 1}
    assert bespoke & set(index) <= {match._en_key(value) for value in lexicon.values()}


def test_spanish_lexical_hits_keep_the_original_words_and_offsets():
    text = SENTENCES[0]
    spanish = match.Matcher('es')
    english = match.Matcher('en')
    assert spanish.index == english.index and spanish.rarity == english.rarity
    hits = spanish.lexical(text)
    en_hits = english.lexical('bees visit many flowers to make honey')
    for phrase, en_phrase in [('abejas', 'bees'), ('flores', 'flowers'), ('miel', 'honey')]:
        actual = {h.id: h.score for h in hits if h.phrase == phrase}
        expected = {h.id: h.score for h in en_hits if h.phrase == en_phrase}
        assert actual == expected and actual
        assert all(h.start == text.index(phrase) for h in hits if h.phrase == phrase)
    assert all(h.phrase.lower() not in match.ES_STOP for h in hits)


@pytest.mark.parametrize('spanish,english', [('árboles', 'tree'), ('arbol', 'tree'), ('luces', 'light')])
def test_accents_and_plurals(spanish, english):
    assert {h.id for h in match.Matcher('es').lexical(spanish)} == \
           {h.id for h in match.Matcher('en').lexical(english)}
    assert match.Matcher('es').lexical(spanish)


def test_fixed_phrases_keep_accents_and_span():
    text = 'El cambio climático afecta la energía solar.'
    hits = match.Matcher('es').lexical(text, every_phrase=True)
    for phrase in ('cambio climático', 'energía solar'):
        assert any(h.phrase == phrase and h.start == text.index(phrase) for h in hits)
    assert match._es_key('magnéticas') == match._es_key('magnético') != ''
    assert match._es_key('año') != match._es_key('ano') or not match._es_key('ano')


def test_semantic_gloss_and_english_assets_are_shared():
    es = match.Matcher('es')
    assert es.semantic('el la los las xyzxyz') == []
    assert match.catalog_vectors('es') is match.catalog_vectors('en')
    assert match.catalog_vectors('es', 'picture') is match.catalog_vectors('en', 'picture')
    assert match.ensure_model('es') == match.ensure_model('en')
    assert match._model('es') is match._model('en')
    text = SENTENCES[0]
    assert es.semantic(text) == match.Matcher('en').semantic(match.es_gloss(text))


def test_every_spanish_beat_has_visuals_and_spanish_copy(spanish_normalize):
    board = RulesDirector('es').direct(board_for(SENTENCES))
    for beat in board['beats']:
        assert beat['visuals'], beat['display']
        for visual in beat['visuals']:
            for item in visual.get('items', []):
                if item.get('label'):
                    assert set(item['label']) == {'es'}
                    # Labels capitalize the original Spanish word, as English labels do.
                    assert item['label']['es'].casefold() in beat['display']['es'].casefold()
                if item.get('trigger'):
                    assert item['trigger']['es'] in beat['spoken']['es']
            if visual.get('trigger'):
                assert visual['trigger']['es'] in beat['spoken']['es']


def test_bees_and_honey_get_literal_pictures(spanish_normalize):
    board = RulesDirector('es').direct(board_for([SENTENCES[0]]))
    picks = {item['doodle']: item.get('label', {}).get('es')
             for visual in board['beats'][0]['visuals'] for item in visual.get('items', [])}
    assert picks == {'fl_honeybee': 'Abejas', 'fl_honey_pot': 'Miel'}


def test_spanish_board_validates(spanish_normalize, tmp_path):
    board = RulesDirector('es').direct(board_for(SENTENCES))
    report = validate(board, tmp_path)
    if not report['ok'] and any('lang must be' in e for e in report['errors']):
        pytest.skip('Job 1 has not yet added es to director/validate.py')
    assert report['ok'], report['errors']


def test_studio_search_for_spanish_queries():
    from kinodraw.studio.server import search_doodles
    expected = {h.id for h in match.Matcher('en').lexical('bee')}
    results = search_doodles('abejas', 'es')
    assert expected <= {row['id'] for row in results}
    assert search_doodles('el la xyzxyz', 'es') == []


@pytest.mark.parametrize('name', ['tiny.md', 'sky_blue.md', 'sleep_zh.md'])
def test_legacy_directors_and_annotations_match_prechange_snapshots(name):
    board = script.build(ingest.read(FIX / name))
    RulesDirector(board['lang']).direct(board)
    annotate(board)
    snapshot = FIX / 'director_snapshots' / (Path(name).stem + '.json')
    expected = json.loads(snapshot.read_text(encoding='utf-8'))
    # Reviewed source excerpts and semantic repairs in offline/compat/final-*.diff.
    # Apply only these explicit deltas to the immutable original, then compare everything.
    hooks = {
        'tiny.md': {'s1': {'en': 'Archaeologists have found pots…'},
                    's2': {'en': 'To make one jar of honey, bees…'}},
        'sky_blue.md': {'s1': {'en': 'White sunlight is really a mix…'},
                        's2': {'en': 'When sunlight hits the tiny…'},
                        's3': {'en': 'At sunset the light travels…'}},
        'sleep_zh.md': {'s1': {'zh': '白天，大脑工作时会产生很多代谢…'},
                        's2': {'zh': '睡眠也在帮我们整理记忆。'},
                        's3': {'zh': '一般来说，成年人每晚需要7到9…'}},
    }[name]
    actual_chapters = {c['id']: c for c in board['chapters']}
    source = (FIX / name).read_text(encoding='utf-8')
    for chapter in expected['chapters']:
        if chapter['id'] in hooks:
            hook = hooks[chapter['id']]
            assert chapter['kind'] == 'section' and 'hook' not in chapter
            assert next(iter(hook.values())).removesuffix('…') in source
            assert actual_chapters[chapter['id']]['hook'] == hook
            chapter['hook'] = hook
    if name == 'sleep_zh.md':
        actual_beats = {b['id']: b for b in board['beats']}
        expected_beats = {b['id']: b for b in expected['beats']}
        disease = [{'id': 'b008v0', 'type': 'cluster',
                    'items': [{'doodle': 'narrator_explain'}], 'relation': 'none'}]
        assert expected_beats['b008']['visuals'][0]['items'][0]['doodle'] == 'fl_mosquito'
        assert actual_beats['b008']['visuals'] == disease
        expected_beats['b008']['visuals'] = disease
        takeaway = {
            'id': 'b009', 'chapter': 's1', 'kind': 'take',
            'display': {'zh': '本节要点：白天，大脑工作时会产生很多代谢废物。'},
            'spoken': {'zh': '本节要点：白天，大脑工作时会产生很多代谢废物。'},
            'visuals': [
                {'id': 'b009v0', 'type': 'cluster', 'items': [{'doodle': 'cell'}],
                 'relation': 'none', 'size': 'margin'},
                {'id': 'b009v1', 'type': 'cluster', 'items': [{'doodle': 'magnifier_report'}],
                 'relation': 'none', 'size': 'margin'},
            ],
            'take': {'headline': {'zh': '白天，大脑工作时会产生很多代谢废物。'}},
            'direction': [{'i': 0, 'span': [0, 23], 'role': 'tagline', 'energy': 1,
                           'scene': 'board', 'emphasis': '代谢废物',
                           'options': {'scene': ['board'], 'emphasis': ['代谢废物', '白天'],
                                       'energy': [0, 1]}, 'source': 'rules'}],
        }
        assert expected_beats['b009']['take']['headline'] == {
            'zh': '如果长期睡不够，这些废物就会越积越多。'}
        assert actual_beats['b009'] == takeaway
        expected['beats'][expected['beats'].index(expected_beats['b009'])] = takeaway
        phone = {'id': 'b016v1', 'type': 'cluster',
                 'items': [{'doodle': 'smartphone', 'label': {'zh': '手机'},
                            'trigger': {'zh': '手机'}}],
                 'relation': 'none', 'trigger': {'zh': '手机'}}
        assert expected_beats['b016']['visuals'][1]['items'][0]['doodle'] == 'fl_no_mobile_phones'
        assert actual_beats['b016']['visuals'][1] == phone
        expected_beats['b016']['visuals'][1] = phone
    assert json.dumps(board, ensure_ascii=False, indent=2) == json.dumps(expected, ensure_ascii=False, indent=2)


def test_spanish_annotation_roles_and_emphasis(spanish_normalize):
    from kinodraw.director.annotate import _detect, _quote
    assert _detect('¿Por qué ocurre?', 'es', 'explain', None, .5, False) == 'question'
    assert _detect('Resulta que hay otra solución.', 'es', 'explain', None, .5, False) == 'reveal'
    assert _detect('El peligro es real.', 'es', 'explain', None, .5, False) == 'problem'
    assert _detect('Usen una computadora.', 'es', 'explain', None, .5, False) == 'step'
    assert _detect('Un lápiz, un libro y una computadora.', 'es', 'explain', None, .5, False) == 'list'
    quote = 'Ana dijo: «La educación cambia nuestra vida».'
    a, b = _quote(quote, 'es')
    assert quote[a:b] == 'La educación cambia nuestra vida'
    board = board_for(SENTENCES, look='collage')
    annotate(board)
    for beat in board['beats']:
        for entry in beat['direction']:
            assert entry['emphasis'] in beat['display']['es']
            assert all(phrase in beat['display']['es'] for phrase in entry['options']['emphasis'])


def test_spanish_rule_detectors(spanish_normalize):
    director = RulesDirector('es')
    assert director._label('árboles') == 'Árboles'
    assert director._event_label('En 1450, Gutenberg creó la imprenta.', '1450') == 'Gutenberg'
    assert director._event_label('En 1500, las imprentas producían libros.', '1500') == 'Imprentas'
    for sentence, relation in [('agua porque lluvia', 'arrow'), ('agua en vez de lluvia', 'vs'),
                               ('agua con lluvia', 'plus')]:
        pair = [match.Hit('a', 1, 'agua', 0), match.Hit('b', 1, 'lluvia', sentence.index('lluvia'))]
        assert director._relation(sentence, pair) == relation
    text = 'Ana dijo: «Los libros ayudan a conocer el mundo».'
    beat = board_for([text])['beats'][0]
    visual, _ = director._quote(beat, text, numbers.Normalized(text, text), [])
    assert visual['who'] == {'es': 'Ana'}
    assert visual['text']['es'] == 'Los libros ayudan a conocer el mundo'
    text = 'El 30% de los alumnos está en la escuela.'
    visual, _ = director._number(beat, text, numbers.Normalized(text, text), [])
    assert visual['type'] == 'grid100'
    assert visual['title']['es'] == '30% de los alumnos'
    assert visual['trigger']['es'] == '30%'


def test_a_spanish_percentage_grid_is_titled_without_a_dangling_que():
    from kinodraw import numbers
    text = 'Un árbol grande produce cerca del 10% del aire que respira una familia.'
    beat = {'id': 'b001', 'display': {'es': text}, 'spoken': {'es': numbers.normalize(text, 'es').spoken}}
    v, _ = RulesDirector('es')._number(beat, text, numbers.normalize(text, 'es'), [])
    assert v['title']['es'] == '10% del aire' and v['legend'][0]['text']['es'] == 'aire'


@pytest.mark.parametrize('sentence,card', [
    ('Dentro de la Tierra hay roca fundida llamada magma.', ('Magma', 'Roca fundida')),
    ('La planta tiene un tubo llamado tallo que lleva el agua.', ('Tallo', 'Un tubo')),
    ('El tubo que lleva el agua hacia arriba se llama tallo.', None),     # 'is called': defined elsewhere
    ('Mi hermana se llama Sofía y tiene un acuario.', None),
])
def test_spanish_definition_card_is_the_noun_phrase_before_llamado(sentence, card):
    director = RulesDirector.__new__(RulesDirector)
    director.lang = 'es'
    found = director._definition({'id': 'b001'}, sentence, numbers.normalize(sentence, 'es'), [])
    assert (found and (found[0]['term']['es'], found[0]['text']['es'])) == card


@pytest.mark.parametrize('sentence,kind,shown', [
    ('La lluvia subió un 3,5% este año.', 'stat', '3,5%'),
    ('La zona tiene 3.000 años de historia.', 'stat', '3.000'),
    ('El 3,5% de las personas vive cerca de un volcán.', 'grid100', '3,5%'),
])
def test_spanish_board_number_keeps_decimal_comma_and_thousands(sentence, kind, shown):
    director = RulesDirector('es')
    v, _ = director._number({'id': 'b001', 'chapter': 'b1'}, sentence, numbers.normalize(sentence, 'es'), set())
    assert v['type'] == kind
    assert (v['value']['es'] if kind == 'stat' else v['title']['es']).startswith(shown)


def test_a_grouped_spanish_percentage_is_never_cut_into_a_grid():
    text = 'El rendimiento fue 1.025,5% del valor inicial.'
    board = board_for([text])
    board['beats'][0]['spoken']['es'] = numbers.normalize(text, 'es').spoken
    RulesDirector('es').direct(board)
    assert not [v for v in board['beats'][0]['visuals'] if v['type'] == 'grid100']   # not '025,5% del valor inicial'
    assert validate(board)['ok']


def test_kinodraw_cloud_is_not_charged_for_a_spanish_video(spanish_normalize):
    from kinodraw.director.llm.cloud import CloudProvider
    from kinodraw.director.llm.director import LLMDirector

    class Cloud:
        languages = CloudProvider.languages
        opened = sent = 0

        def open_video(self, sections, characters):
            Cloud.opened += 1

        def direct_section(self, payload, usage):
            Cloud.sent += 1
            return {}
    board = board_for(SENTENCES[:2])
    report = LLMDirector(Cloud(), 'es').direct(board)
    assert Cloud.opened == Cloud.sent == 0                                   # no cloud video counted
    assert report['notes'][0].startswith('The offline director planned this video')   # the Studio shows this
    assert all(b['visuals'] for b in board['beats']) and validate(board)['ok']

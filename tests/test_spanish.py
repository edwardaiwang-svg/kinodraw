"""Spanish narration and the Latin rendering path, without downloads or synthesis."""
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinodraw import cli, ingest, numbers, package, pipeline, styles, voice
from kinodraw import script
from kinodraw.audio.mix import write_captions
from kinodraw.director.validate import validate
from kinodraw.engine import captions, ink, render, skin, timeline
from kinodraw.studio import server

FIX = Path(__file__).parent / 'fixtures'


def test_detection_and_all_existing_fixtures():
    assert ingest.read(FIX / 'miel_es.md').lang == 'es'
    assert ingest.detect_lang('Las abejas hacen la miel de las flores del campo.') == 'es'
    assert ingest.detect_lang('¿Hola?') == 'es'
    assert ingest.detect_lang('Hello world.') == 'en'
    assert ingest.detect_lang('KinoDraw') == 'en'
    for path in FIX.iterdir():
        if path.suffix in ('.md', '.txt') and path.name != 'miel_es.md':
            assert ingest.read(path).lang == ('zh' if path.name.endswith('_zh.md') else 'en'), path.name


ENGLISH_WITH_SPANISH_NAMES = [
    'El Niño and La Niña: why California gets wet winters.',
    'Día de los Muertos: how families in Mexico remember loved ones.',
    'How to grow jalapeño peppers on a balcony.',
    'Plan a piñata party for a class of 25.',
    'José and María went to México.',
]
SPANISH_SHORT = ['¿Cómo comen las plantas?', '¡Hola!', 'Cómo funciona un volcán',
                 'Las abejas hacen la miel de las flores del campo.']


def test_english_with_spanish_names_stays_english():
    assert [ingest.detect_lang(t) for t in ENGLISH_WITH_SPANISH_NAMES] == ['en'] * 5
    assert [ingest.detect_lang(t) for t in SPANISH_SHORT] == ['es'] * 4


@pytest.mark.skipif(not shutil.which('node'), reason='node not installed')
def test_studio_detect_matches_the_server(tmp_path):
    app = (Path(ingest.__file__).parent / 'studio' / 'static' / 'app.js').read_text(encoding='utf-8')
    source = re.search(r'^function scriptLang\(.*?^}', app, re.S | re.M)[0]
    texts = ENGLISH_WITH_SPANISH_NAMES + SPANISH_SHORT + [(FIX / 'miel_es.md').read_text(encoding='utf-8')]
    (tmp_path / 'detect.js').write_text(source + f'\nconsole.log(JSON.stringify({json.dumps(texts)}.map(scriptLang)));',
                                        encoding='utf-8')
    out = subprocess.run(['node', str(tmp_path / 'detect.js')], capture_output=True, text=True, check=True,
                         encoding='utf-8').stdout
    assert json.loads(out) == [ingest.detect_lang(t) for t in texts]


def test_spanish_storyboard_lines():
    board = script.build(ingest.read(FIX / 'miel_es.md'))
    beats = board['beats']
    assert board['lang'] == 'es'
    assert beats[0]['display']['es'] == 'Hoy: Tres datos sobre la miel.'
    opener = next(b for b in beats if b['kind'] == 'opener')
    assert opener['display']['es'].startswith('Parte 1: ')
    assert opener['spoken']['es'].startswith('Parte uno: ')
    assert next(b for b in beats if b['kind'] == 'take')['display']['es'].startswith('Idea clave: ')
    assert next(b for b in beats if b['kind'] == 'agenda')['display']['es'].startswith('Esto es lo que veremos. Primero: ')
    assert beats[-1]['display']['es'] == '¡Gracias por ver!'
    assert any('tres mil años' in b['spoken']['es'] for b in beats)
    assert all(not re.search(r'\d', b['spoken']['es']) for b in beats)
    assert validate(board)['ok']


@pytest.mark.parametrize('text,expected', [
    ('¿Qué es la miel? ¡Es comida! El Dr. Pérez lo explica.',
     ['¿Qué es la miel?', '¡Es comida!', 'El Dr. Pérez lo explica.']),
    ('La Sra. Álvarez vive en EE.UU. con el Sr. Pérez. Él trabaja.',
     ['La Sra. Álvarez vive en EE.UU. con el Sr. Pérez.', 'Él trabaja.']),
    ('Aquí termina. «Ángeles y abejas». ¡Únanse!', ['Aquí termina.', '«Ángeles y abejas».', '¡Únanse!']),
])
def test_sentences(text, expected):
    assert script.sentences(text, 'es') == expected


@pytest.mark.parametrize('display,spoken', [
    ('Parte 1: Miel.', 'Parte uno: Miel.'),
    ('Hace 3,000 años, en 1450.', 'Hace tres mil años, en mil cuatrocientos cincuenta.'),
    ('El 3.4% y el -0.5%.', 'El tres punto cuatro por ciento y el menos cero punto cinco por ciento.'),
    ('Entre 10-15%.', 'Entre diez a quince por ciento.'),
    ('Cuesta $5.', 'Cuesta cinco dólares.'),
    ('Cuesta $1.', 'Cuesta un dólar.'),
    ('$21 y $1,000.', 'veintiún dólares y mil dólares.'),
    ('$1k y $1 million.', 'mil dólares y un millón de dólares.'),
    ('$1.01.', 'un dólar con un centavo.'),
    ('$2 million y $3.8bn.', 'dos millones de dólares y tres punto ocho mil millones de dólares.'),
    ('Son $19.99.', 'Son diecinueve dólares con noventa y nueve centavos.'),
    ('Hay 2 millones de flores.', 'Hay dos millones de flores.'),
    ('Un valor de 0.05.', 'Un valor de cero punto cero cinco.'),
    ('una ola de 30 m', 'una ola de treinta metros'),
    ('10 mm de lluvia', 'diez milímetros de lluvia'),
    ('Caen 10 mm de lluvia.', 'Caen diez milímetros de lluvia.'),
    ('una torre de 100 m de altura', 'una torre de cien metros de altura'),
    ('5 t de carbón', 'cinco toneladas de carbón'),
    ('30 m de altura', 'treinta metros de altura'),
    ('3 manzanas', 'tres manzanas'),
    ('3 árboles y 3 mmás', 'tres árboles y tres mmás'),
    ('5m', 'cinco millones'),
    ('Gana 5m al año.', 'Gana cinco millones al año.'),
    ('Son 30 mil personas.', 'Son treinta mil personas.'),
    ('2 millones', 'dos millones'),
    ('$3.8bn', 'tres punto ocho mil millones de dólares'),
    ('$1k', 'mil dólares'),
    ('$1 million', 'un millón de dólares'),
    ('Subió un 3,5% este año', 'Subió un tres coma cinco por ciento este año'),
    ('3,5%', 'tres coma cinco por ciento'),
    ('Mide 2,5 metros', 'Mide dos coma cinco metros'),
    ('2,5 metros', 'dos coma cinco metros'),
    ('Hace 3.000 años', 'Hace tres mil años'),
    ('3,000', 'tres mil'),
    ('3.000', 'tres mil'),
    ('1.500.000', 'un millón quinientos mil'),
    ('$1.500', 'mil quinientos dólares'),
    ('3.4%', 'tres punto cuatro por ciento'),
    ('1.234,5', 'mil doscientos treinta y cuatro coma cinco'),
    ('3,50 y 3,5000', 'tres coma cinco cero y tres coma cinco cero cero cero'),
    ('3.0000', 'tres punto cero cero cero cero'),
    ('1,500,000 y 1,234.5', 'un millón quinientos mil y mil doscientos treinta y cuatro punto cinco'),
    ('Entre -3,5% y 1,5-2,5%.', 'Entre menos tres coma cinco por ciento y uno coma cinco a dos coma cinco por ciento.'),
    ('Cuesta $2.50', 'Cuesta dos dólares con cincuenta centavos'),
    ('$2.50', 'dos dólares con cincuenta centavos'),
    ('$19.99', 'diecinueve dólares con noventa y nueve centavos'),
    ('$1.01', 'un dólar con un centavo'),
    ('€2,50', 'dos euros con cincuenta céntimos'),
    ('$5.00', 'cinco dólares'),
    ('US$1,01 y £2.50', 'un dólar con un centavo y dos libras con cincuenta peniques'),
    ('€1,01 y £1.01', 'un euro con un céntimo y una libra con un penique'),
    ('¥2.50 y ₹2,50', 'dos punto cinco cero yenes y dos coma cinco cero rupias'),
    ('$1.00 y €1,00', 'un dólar y un euro'),
    ('$1,500.01 y €1.500,50', 'mil quinientos dólares con un centavo y mil quinientos euros con cincuenta céntimos'),
    ('$3.80bn', 'tres punto ocho cero mil millones de dólares'),
    ('¿Mide 2,5 m? ¡Sí, cuesta $2.50!', '¿Mide dos coma cinco metros? ¡Sí, cuesta dos dólares con cincuenta centavos!'),
    ('1 m', 'un metro'), ('1 kg', 'un kilogramo'), ('1 t', 'una tonelada'),
    ('2 km/h', 'dos kilómetros por hora'), ('1 km/h', 'un kilómetro por hora'),
    ('2 km', 'dos kilómetros'), ('1 km', 'un kilómetro'),
    ('2 cm', 'dos centímetros'), ('1 cm', 'un centímetro'),
    ('2 mm', 'dos milímetros'), ('1 mm', 'un milímetro'),
    ('2 kg', 'dos kilogramos'), ('2 g', 'dos gramos'), ('1 g', 'un gramo'),
    ('2 l', 'dos litros'), ('1 l', 'un litro'),
    ('2 ml', 'dos mililitros'), ('1 ml', 'un mililitro'),
    ('2 °C', 'dos grados Celsius'), ('1°C', 'un grado Celsius'),
    ('2 °F', 'dos grados Fahrenheit'), ('1°F', 'un grado Fahrenheit'),
    ('2°', 'dos grados'), ('1°', 'un grado'),
    ('2 mph', 'dos millas por hora'), ('1 mph', 'una milla por hora'),
    ('2 GB', 'dos gigabytes'), ('1 GB', 'un gigabyte'),
    ('2 MB', 'dos megabytes'), ('1 MB', 'un megabyte'),
    ('5MM y 5MN', 'cinco millones y cinco millones'),
    ('5K y 5M', 'cinco mil y cinco millones'),
    ('5B y 5BN', 'cinco mil millones y cinco mil millones'),
    ('5T y 5TN', 'cinco billones y cinco billones'),
    ('$5 MM y $5 m', 'cinco millones de dólares y cinco millones de dólares'),
    ('$5T y $5TN', 'cinco billones de dólares y cinco billones de dólares'),
    ('1 mil y 1 millón', 'mil y un millón'),
    ('2 million y 2 billion', 'dos millones y dos mil millones'),
    ('2 trillion y 2 thousand', 'dos billones y dos mil'),
    ('Caen 10mm de lluvia.', 'Caen diez milímetros de lluvia.'),
    ('Tengo 1 perro y 1 gata.', 'Tengo un perro y una gata.'),
    ('Tiene 21 años y come 1 vez al día.', 'Tiene veintiún años y come una vez al día.'),
    ('Dura 31 minutos.', 'Dura treinta y un minutos.'),
    ('Son 101 dálmatas y 21 casas.', 'Son ciento un dálmatas y veintiuna casas.'),
    ('Hay 1 ave y 1 canción.', 'Hay un ave y una canción.'),
    ('Viven 21.000 personas.', 'Viven veintiún mil personas.'),
    ('1 de cada 4', 'uno de cada cuatro'),
    ('Capítulo 1.', 'Capítulo uno.'),
])
def test_numbers(display, spoken):
    n = numbers.normalize(display, 'es')
    assert n.display == display and n.spoken == spoken
    assert captions.ES_PUNCT.findall(n.spoken) == captions.ES_PUNCT.findall(display)
    assert n.spans


def test_number_span_mapping():
    n = numbers.normalize('La miel dura 3,000 años y cuesta $5.', 'es')
    assert n.find('3,000 años') == 'tres mil años'
    assert n.find('$5') == 'cinco dólares'
    assert n.find('La miel') == 'La miel'


def test_spanish_separator_and_unit_span_mapping():
    n = numbers.normalize('¿Mide 1.234,5 m y cuesta $2.50? ¡Sí!', 'es')
    assert n.find('1.234,5 m') == 'mil doscientos treinta y cuatro coma cinco metros'
    assert n.find('$2.50') == 'dos dólares con cincuenta centavos'
    assert n.find('y cuesta $2.50') == 'y cuesta dos dólares con cincuenta centavos'
    assert n.find('¡Sí!') == '¡Sí!'


@pytest.mark.skipif(bool(voice.missing_files('es')), reason='Kokoro models not downloaded')
def test_latin_american_phonemes_and_shared_engine(monkeypatch):
    monkeypatch.setattr(voice, 'download', lambda *a: None)
    phones = voice.phonemes('Hacer ciencia', 'es')
    assert phones and 'θ' not in phones
    assert voice._engine('es') is voice._engine('en')
    assert {'ef_dora', 'em_alex'} <= set(voice._engine('es').get_voices())
    assert voice.missing_files('es') == voice.missing_files('en')


def test_clause_marks_and_alignment():
    text = '¿Qué es? ¡Miel!'
    marks = [i for i in range(len(text)) if voice._is_clause_mark(text, i, 'es')]
    assert [text[i] for i in marks] == ['?', '!']
    assert voice._is_clause_mark('miel?»', 4, 'es')
    assert not voice._is_clause_mark('miel?»', 4, 'en')
    timings = [SimpleNamespace(phoneme=p, start=t) for p, t in
               [('k', 0.), ('e', .1), ('?', .2), ('m', 1.), ('i', 1.1), ('e', 1.2), ('l', 1.3), ('!', 1.4)]]
    times = voice.align(text, timings, 'es')
    assert len(times) == len(text) and times == sorted(times)
    assert times[text.index('M')] >= 1.
    assert captions.clause_spans('¿Miel?» ¡Sí!', 'es') == [(0, 6), (6, 12)]


def test_validate_minimal_spanish_storyboard():
    board = {'version': 1, 'lang': 'es', 'title': {'es': 'Miel'},
             'chapters': [{'id': 'main', 'kind': 'board'}],
             'beats': [{'id': 'b001', 'chapter': 'main', 'display': {'es': '¿Hay 3 abejas?'},
                        'spoken': {'es': '¿Hay tres abejas?'}, 'visuals': []}]}
    assert validate(board)['ok']
    board['beats'][0]['spoken']['es'] = '¿Hay tres abejas!'
    assert not validate(board)['ok']


@pytest.mark.parametrize('look', ['whiteboard', 'chalkboard', 'notebook'])
def test_preview_renders_spanish_in_every_supported_look(tmp_path, look):
    board = pipeline.new_project(FIX / 'miel_es.md', tmp_path / look, direction={'look': look})
    tl = timeline.layout(board, 'es', timeline.synthetic_clips(board, 'es'))
    prod = render.make_production(board, tl, 'es', tmp_path / look)
    assert prod.frame(tl['captions'][0]['start'] + .1).size == (1920, 1080)
    assert 'es' in styles.get(look)['languages']
    text = 'ÁÉÍÓÚÑÜ áéíóúñü ¿Qué? ¡Sí!'
    assert ink.hand_font('es', 60) is ink.hand_font('en', 60)
    assert captions.cap_font('es') is captions.cap_font('en')
    assert all(f is ink.hand_font('en', 60) for _, f in ink.font_runs(text, 'es', 60))
    assert ''.join(c['text'] for c in tl['captions']).count('¿') > 0


def test_highlighter_uses_accented_word_boundaries():
    td = ink.TextDrawing(['La piña y la miel'], 'es', 60)
    assert skin.phrase_boxes(td, 'piña')
    assert not skin.phrase_boxes(td, 'ña')
    assert skin.phrase_boxes(td, 'la pi')


def test_studio_and_read_aloud(tmp_path, monkeypatch):
    root = tmp_path / 'projects'
    project = root / 'Miel'
    pipeline.new_project(FIX / 'miel_es.md', project)
    monkeypatch.setattr(server, 'projects_root', lambda: root)
    monkeypatch.setattr(server, '_config', lambda: {})
    from kinodraw.director.llm import providers
    monkeypatch.setattr(providers, 'saved', lambda: set())
    state = server.state()
    assert [v['id'] for v in state['voices']['es']] == ['ef_dora', 'em_alex', 'em_santa']
    assert 'es' in state['models_ready']
    info = server.narrator('Miel')
    assert info['lang'] == 'es' and info['voice'] == 'ef_dora'
    assert any(line['text'] == 'Parte uno: Nunca se echa a perder.' for line in info['lines'])
    assert pipeline.settings(project)['voice'] == 'ef_dora'


def test_cli_accepts_spanish_without_directing(tmp_path, monkeypatch):
    from kinodraw import director
    monkeypatch.setattr(director, 'direct', lambda *a, **kw: {})
    project = tmp_path / 'video'
    cli.main(['new', str(FIX / 'miel_es.md'), '-o', str(project), '--lang', 'es'])
    assert pipeline.settings(project)['lang'] == 'es'


def test_spanish_sources_and_published_metadata(tmp_path, monkeypatch):
    board = script.build(ingest.read(FIX / 'miel_es.md'))
    tl = timeline.layout(board, 'es', timeline.synthetic_clips(board, 'es'))
    output = tmp_path / 'miel.mp4'
    calls = []

    def run(args):
        calls.append(args)
        Path(args[-1]).write_bytes(b'video')

    monkeypatch.setattr(package, '_run', run)
    package.mux(tl, tmp_path / 'silent.mp4', tmp_path / 'mix.wav', output, 'es', board['title']['es'], tmp_path)
    assert 'language=spa' in (tmp_path / 'chapters.ffmetadata').read_text(encoding='utf-8')
    assert calls and output.exists()
    write_captions(tl['captions'], tmp_path)
    package.publish(board, tl, 'es', tmp_path, tmp_path, 'miel', tmp_path)
    description = (tmp_path / 'miel-description.txt').read_text(encoding='utf-8')
    assert 'Capítulos' in description and 'Hecho con KinoDraw.' in description
    assert '¡Gracias por ver!' in (tmp_path / 'miel-transcript.md').read_text(encoding='utf-8')
    assert (tmp_path / 'miel-thumbnail.png').is_file()
    assert '¿Sabías' in (tmp_path / 'miel.srt').read_text(encoding='utf-8')
    assert '¡Gracias por ver!' in (tmp_path / 'miel.vtt').read_text(encoding='utf-8')
    ch = {'kind': 'section', 'speaker': {'name': {'es': 'Ana'}, 'show': {'es': 'Ciencia'}, 'date': {'es': '2026'}}}
    assert render.source_line(ch, 'es') == 'Fuente: Ana · Ciencia, 2026'

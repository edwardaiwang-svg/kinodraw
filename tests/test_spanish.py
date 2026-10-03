"""Spanish narration and the Latin rendering path, without downloads or synthesis."""
import re
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
            assert ingest.read(path).lang == ('zh' if path.name == 'sleep_zh.md' else 'en'), path.name


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
    ('$1.01.', 'uno punto cero uno dólares.'),
    ('$2 million y $3.8bn.', 'dos millones de dólares y tres punto ocho mil millones de dólares.'),
    ('Son $19.99.', 'Son diecinueve punto nueve nueve dólares.'),
    ('Hay 2 millones de flores.', 'Hay dos millones de flores.'),
    ('Un valor de 0.05.', 'Un valor de cero punto cero cinco.'),
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
    assert state['voices']['es'] == ['ef_dora', 'em_alex']
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
    assert 'language=spa' in (tmp_path / 'chapters.ffmetadata').read_text()
    assert calls and output.exists()
    write_captions(tl['captions'], tmp_path)
    package.publish(board, tl, 'es', tmp_path, tmp_path, 'miel', tmp_path)
    description = (tmp_path / 'miel-description.txt').read_text()
    assert 'Capítulos' in description and 'Hecho con KinoDraw.' in description
    assert '¡Gracias por ver!' in (tmp_path / 'miel-transcript.md').read_text()
    assert (tmp_path / 'miel-thumbnail.png').is_file()
    assert '¿Sabías' in (tmp_path / 'miel.srt').read_text() and '¡Gracias por ver!' in (tmp_path / 'miel.vtt').read_text()
    ch = {'kind': 'section', 'speaker': {'name': {'es': 'Ana'}, 'show': {'es': 'Ciencia'}, 'date': {'es': '2026'}}}
    assert render.source_line(ch, 'es') == 'Fuente: Ana · Ciencia, 2026'

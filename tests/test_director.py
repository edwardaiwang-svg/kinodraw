from pathlib import Path

import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.validate import validate

FIX = Path(__file__).parent / 'fixtures'


@pytest.fixture(scope='module', params=['printing_press.md', 'photosynthesis.txt', 'sleep_zh.md'])
def directed(request):
    board = script.build(ingest.read(FIX / request.param))
    return RulesDirector(board['lang']).direct(board)


def test_rules_output_validates(directed):
    report = validate(directed)
    assert report['ok'], report['errors']


def test_every_content_beat_has_a_visual(directed):
    kinds = {c['id']: c['kind'] for c in directed['chapters']}
    content = [b for b in directed['beats'] if b['kind'] in ('narration', 'closing') and kinds[b['chapter']] != 'intro']
    bare = [b['id'] for b in content if not b['visuals']]
    assert len(bare) <= len(content) // 4, bare


def test_validator_catches_bad_triggers_and_doodles():
    board = script.build(ingest.read(FIX / 'photosynthesis.txt'))
    beat = next(b for b in board['beats'] if b['kind'] == 'narration')
    beat['visuals'] = [{'id': 'x1', 'type': 'cluster', 'items': [{'doodle': 'no_such_doodle'}],
                        'trigger': {'en': 'words nobody says'}}]
    errors = validate(board)['errors']
    assert any('not in the spoken text' in e for e in errors) and any('not found' in e for e in errors)


# ---------------------------------------------------------------- meaning rules
def _picks(name):
    board = script.build(ingest.read(FIX / name))
    board = RulesDirector(board['lang']).direct(board)
    return board, [((it.get('label') or {}).get(board['lang']), it['doodle'])
                   for b in board['beats'] for v in b['visuals'] if v['type'] == 'cluster' for it in v['items']]


def test_words_are_drawn_in_the_sense_the_script_uses():
    _, picks = _picks('printing_press.md')
    assert ('Press', 'newspaper') not in picks                 # a press from wine making is not a newspaper
    assert all(d != 'candlestick_phone' for _, d in picks)     # "older inventions" is not a 1900s telephone
    assert all(d != 'brainstorm_board' for _, d in picks)      # a 1450s workshop is not a sticky-note meeting
    _, picks = _picks('sky_blue.md')
    wrong = {'fl_waving_hand', 'fl_candle', 'fl_light_blue_heart', 'fl_horizontal_traffic_light', 'airplane',
             'fl_police_car_light', 'fl_cityscape_at_dusk', 'ocean'}           # light waves are not the sea
    assert not wrong & {d for _, d in picks}, picks            # light waves, not hands, lamps or planes
    _, picks = _picks('photosynthesis.txt')
    assert all(d != 'thought_bubble' for _, d in picks)        # leaves reflect light; they don't think


def test_a_word_keeps_its_first_picture():
    _, picks = _picks('sky_blue.md')
    seen = {}
    for label, d in picks:
        if label:
            assert seen.setdefault(label.lower(), d) == d, (label, seen[label.lower()], d)


def test_idioms_generic_words_and_numbers_get_no_picture():
    director = RulesDirector('en')
    board = script.build(ingest.read(FIX / 'printing_press.md'))
    director.direct(board)
    chapter = next(c['id'] for c in board['chapters'] if c['kind'] == 'section')
    hits = director._concepts("Luther's pamphlets spread in a matter of weeks, and several older inventions helped.",
                              [], chapter)
    assert not {h.phrase.lower() for h in hits if h.phrase} & {'matter', 'inventions', 'invention'}


def test_timeline_labels_say_who_or_what():
    board, _ = _picks('bicycle.md')
    lanes = next(v for b in board['beats'] for v in b['visuals'] if v['type'] == 'lanes')
    labels = {e['display']['en']: e['label']['en'] for e in lanes['lanes'][0]['events']}
    assert labels == {'1860s': 'French makers', '1870s': 'Front wheel', '1885': 'John Kemp Starley',
                      '1888': 'John Boyd Dunlop'}


def test_timelines_only_show_dates_their_section_says_when_it_says_them():
    board, _ = _picks('printing_press.md')                    # 1450, 1500 and 1517 are in three sections
    assert not any(v['type'] == 'lanes' for b in board['beats'] for v in b['visuals'])
    board, _ = _picks('bicycle.md')
    by_id = {b['id']: b for b in board['beats']}
    owner = next(b for b in board['beats'] for v in b['visuals'] if v['type'] == 'lanes')
    lanes = next(v for v in owner['visuals'] if v['type'] == 'lanes')
    for ev in lanes['lanes'][0]['events']:
        said = by_id[ev['trigger'].get('beat', owner['id'])]
        assert said['chapter'] == owner['chapter'] and ev['trigger']['en'] in said['spoken']['en'], ev
    held = [b for b in board['beats'] if b['chapter'] == owner['chapter'] and b['kind'] == 'narration']
    between = held[held.index(owner) + 1:held.index(by_id['b012'])]
    assert all(not b['visuals'] for b in between)             # the page holds the board between its dates


# ---------------------------------------------------------- more pictures, said as drawn
def _visual_doodles(board, beat_id):
    beat = next(b for b in board['beats'] if b['id'] == beat_id)
    return [[(it['doodle'], (it.get('trigger') or {}).get('en')) for it in v.get('items', [])] for v in beat['visuals']]


def test_listed_things_are_all_drawn_together():
    board, _ = _picks('printing_press.md')
    outro = next(b['id'] for b in board['beats'] if b['chapter'] == 'outro' and b['kind'] == 'narration')
    assert [('book_stack', 'book'), ('newspaper', 'newspaper'), ('web_page', 'website')] in _visual_doodles(board, outro)


def test_snow_is_drawn_as_a_snowflake_but_a_wheel_is_still_not_a_ferris_wheel():
    board, _ = _picks('water_cycle.md')
    beat = next(b['id'] for b in board['beats'] if 'sleet' in b['display']['en'])
    assert [('rain_cloud', 'rain'), ('fl_snowflake', 'snow')] in _visual_doodles(board, beat)   # "rain, snow, sleet or hail"
    director = RulesDirector('en')
    director.direct(script.build(ingest.read(FIX / 'water_cycle.md')))
    assert not director._is_head('fl_ferris_wheel', 'wheels') and not director._is_head('fl_snowman', 'snow')


def test_takeaway_paragraphs_are_illustrated_before_the_takeaway():
    board, _ = _picks('printing_press.md')
    s2 = [b for b in board['beats'] if b['chapter'] == 's2']
    assert [b['kind'] for b in s2] == ['opener', 'narration', 'narration', 'take']
    doodles = {d for v in _visual_doodles(board, s2[2]['id']) for d, _ in v}
    assert {'read_aloud', 'fl_school'} <= doodles, doodles        # "Schools taught reading to more children"


def test_a_describing_word_is_not_a_thing_and_ink_is_drawn():
    _, picks = _picks('printing_press.md')
    assert ('Ink', 'quill_ink') in picks                           # "oil-based ink"
    assert all(d != 'oil_barrel' for _, d in picks)


def test_a_team_of_printers_are_people_not_machines():
    _, picks = _picks('printing_press.md')
    assert all(d != 'fl_printer' for _, d in picks), picks            # "A team of printers could now do in weeks"
    director = RulesDirector('en')
    board = script.build(ingest.read(FIX / 'printing_press.md'))
    director.direct(board)
    hits = director._concepts('A class of students listened while a team of printers worked.', [], 's2')
    assert ('students', 'teacher_whiteboard') in {(h.phrase, h.id) for h in hits if h.phrase}  # a picture of people may


def test_an_emoji_with_a_longer_name_needs_its_whole_name():
    _, picks = _picks('bicycle.md')
    doodles = {d for _, d in picks}
    assert 'fl_ferris_wheel' not in doodles and 'fl_slot_machine' not in doodles, picks
    assert ('Wheels', 'fl_wheel') in picks


def test_banned_pictures_and_words_are_never_drawn():
    from kinodraw.library import banned, catalog
    assert not banned()['doodles'] & set(catalog())
    for name in ('printing_press.md', 'bicycle.md', 'sky_blue.md', 'photosynthesis.txt'):
        _, picks = _picks(name)
        assert not banned()['doodles'] & {d for _, d in picks}
    director = RulesDirector('en')
    board = script.build(ingest.read('# Cells\n\n## Tiny building blocks\n\nEvery living thing is made of cells. '
                                     'Scientists look at cells with a microscope in the lab.\n\n## Inside a cell\n\n'
                                     'A cell has a nucleus. Scientists in Germany found it with a microscope.'))
    director.direct(board)
    chapter = next(b['chapter'] for b in board['beats'] if b['kind'] == 'narration')
    hits = director._concepts('Scientists and astronomers in Germany look at tiny cells with a microscope.', [], chapter)
    words = {h.phrase.lower() for h in hits if h.phrase}
    assert not words & {'scientists', 'astronomers', 'germany'}, words     # "scientists" would be a microscope
    assert 'microscope' in words


@pytest.mark.parametrize('sentence, date, label', [
    ('Around 1450, Johannes Gutenberg, a goldsmith in Mainz, combined older inventions.', '1450', 'Johannes Gutenberg'),
    ('By 1500, printing presses were running in more than 250 European cities.', '1500', 'Printing presses'),
    ("In 1517, Martin Luther's arguments spread across Germany in a matter of weeks.", '1517', 'Martin Luther'),
    ('Before the 1450s, every book in Europe was copied by hand.', '1450s', 'Books copied by hand'),
    ('In the 1860s, French makers added pedals to the front wheel.', '1860s', 'French makers'),
    ('The fix came in 1885, when John Kemp Starley sold the Rover.', '1885', 'John Kemp Starley'),
])
def test_event_label(sentence, date, label):
    assert RulesDirector('en')._event_label(sentence, date) == label


def test_event_label_zh():
    label = RulesDirector('zh')._event_label('1911年，辛亥革命推翻了清朝。', '1911')
    assert label and '1911' not in label and '年' not in label, label


def test_negated_words_and_defined_terms_get_no_picture():
    board, picks = _picks('bicycle.md')
    doodles = {d for _, d in picks}
    assert 'gears_meshing' not in doodles and not any(label == 'Engine' for label, _ in picks)   # "no engine"
    assert 'fl_horse' not in doodles                                   # "the dandy horse" is on its note
    glossary = [v for b in board['beats'] for v in b['visuals'] if v['type'] == 'glossary']
    assert glossary and glossary[0]['term']['en'] == 'Dandy horse'
    grid = next(v for b in board['beats'] for v in b['visuals'] if v['type'] == 'grid100')
    assert grid['title']['en'] == '27% of trips'

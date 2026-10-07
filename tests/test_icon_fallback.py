"""Ink line icons (library.PACKS) reach a video only as a fallback: in a beat that no coloured or bespoke doodle can
show, for a thing the beat names as a noun that is the icon's own name; never for an action, a figure of speech, a
story character or anything that would draw a person or an animal."""
from pathlib import Path

import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.library import catalog, imported

FIX = Path(__file__).parent / 'fixtures'


@pytest.fixture(scope='module')
def director():
    return RulesDirector('en')


def picks(director, text):
    board = script.build(ingest.read(text), story='story')     # one beat a paragraph, no spoken takeaways
    director.direct(board)
    return [[it['doodle'] for v in b['visuals'] for it in v.get('items', [])] for b in board['beats']]


def icons_in(rows):
    return [d for row in rows for d in row if imported(catalog().get(d, {}))]


def test_an_icon_is_drawn_only_for_a_beat_no_doodle_can_show(director):
    assert picks(director, 'The old kayak sat by the shore.') == [['tb_kayak']]
    assert picks(director, 'A kayak and a canoe sat by the shore.') == [['fl_canoe']]    # a coloured canoe: no icon
    board = script.build(ingest.read(FIX / 'tiny.md'))
    director.direct(board)
    drawn = {b['id']: [it['doodle'] for v in b['visuals'] for it in v.get('items', [])] for b in board['beats']}
    assert drawn['b009'] == ['tb_flower']                    # "bees visit about two million flowers"
    assert icons_in(v for k, v in drawn.items() if k != 'b009') == []


def test_the_sense_guard_keeps_icons_to_things_the_words_name(director):
    assert picks(director, 'Please note it down.') == [['narrator_explain']]       # an action: no note icon
    assert picks(director, 'Leave a note on the fridge.') != [['narrator_explain']]
    named = {s: [h.id for h in director._icons(s, [])] for s in (
        'In autumn the leaves began to fall.',     # tb_fall is a person slipping, and "fall" is said as an action
        'The rivers flood the valley every spring.', 'It all runs on your own computer.',
        'Place five dots on the board.', 'We can help them.', 'A bridge between cultures takes time.',
        'Anything else in the world.')}
    assert named == {s: [] for s in named}
    assert [h.id for h in director._icons('The flood covered the valley.', [])] == ['tb_flood']
    assert [h.id for h in director._icons('The old bridge did not collapse.', [])] == ['tb_building_bridge']


def test_no_icon_stands_for_a_story_character(director):
    story = ('Pendo found an old kayak by the shore.\n\nThe young cub licked his paws.\n\n'
             'Pendo pushed the kayak into the water.\n\nMara watched from the rocks as Pendo paddled away.\n')
    assert icons_in(picks(director, story)) == []
    for sentence in ('A cow grazed beside the old barn.', 'The young cub licked his paws.',
                     'A runner crossed the old bridge.'):
        shown = [catalog()[h.id] for h in director._icons(sentence, [])]
        assert all(e['category'] not in ('Animals', 'zoonoses', 'people') and 'runner' not in e['en'] for e in shown)


def test_spanish_and_chinese_scripts_get_no_icons():
    for name, lang in (('miel_es.md', 'es'), ('sleep_zh.md', 'zh')):
        board = script.build(ingest.read(FIX / name))
        RulesDirector(lang).direct(board)
        assert icons_in([it['doodle'] for v in b['visuals'] for it in v.get('items', [])] for b in board['beats']) == []

"""Determiners must not become characters during rules planning or repair."""
from copy import deepcopy

from kinodraw import ingest, script
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.semantics import detect_cast
from kinodraw.director.v3.validate import validate


def test_each_point_does_not_create_a_character_in_rules_or_repair():
    board = script.build(ingest.read('# Annual observations\n\nEach point is one annual mean.'))
    plan = from_rules(board)
    assert not plan['cast']
    raw = deepcopy(plan)
    raw['cast'] = []
    repaired, notes = validate(raw, board, None)
    assert not repaired['cast']
    assert not any('named character Each' in note for note in notes)


def test_each_can_still_be_an_explicitly_introduced_name():
    spoken = 'Each, a lion cub, points at Pendo. The lion cub Pendo trembles. Mara, a tigress, nudges Pendo.'
    cast = detect_cast([{'id': 'b1', 'text': spoken, 'spoken': spoken}])
    assert {'Each', 'Pendo', 'Mara'} <= {c['name'] for c in cast}
    assert next(c for c in cast if c['name'] == 'Each')['species'] == 'lion'

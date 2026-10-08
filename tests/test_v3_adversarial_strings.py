"""Script text can steer the planner's strings, so very long names, actors, refs and colours (runs of spaces,
"a a a", "as as", " , ,") must be repaired quickly instead of backtracking in a regular expression."""
import time

import pytest

from kinodraw import ingest, script
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.semantics import actor_named, core_name, resolve_actor
from kinodraw.director.v3.validate import colour_hex, validate

N = 50_000
FILLS = {'spaces': 'x' + ' ' * (N - 2) + 'y', 'a_a_a': 'a ' * (N // 2) + 'z', 'as_as': 'as ' * (N // 3) + 'z',
         'commas': 'x' + ' ,' * (N // 2)}
TEXT = '# Walk\n\nMara walked to the lake with her lamp.\n\nThe moon rose over the water.'


def _timed(fn):
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


@pytest.mark.parametrize('kind', FILLS)
def test_name_helpers_are_linear(kind):
    v = FILLS[kind]
    cast = {'mara': {'name': 'Mara', 'age': 'adult'}, 'young_mara': {'name': 'Mara as a little girl', 'age': 'baby'}}
    for fn in (lambda: core_name(v), lambda: actor_named(v, 'Mara walked.'), lambda: resolve_actor(v, cast),
               lambda: colour_hex(v)):
        assert _timed(fn) < 100


@pytest.mark.parametrize('field', ['name', 'actor', 'ref', 'colour'])
@pytest.mark.parametrize('kind', FILLS)
def test_long_model_strings_are_repaired_quickly(kind, field):
    board = script.build(ingest.read(TEXT), story='story')
    plan = from_rules(board)
    v = FILLS[kind]
    bid = plan['scenes'][0]['beat_ids'][0]
    if field == 'name':
        plan['cast'][0]['name'] = v
    if field == 'actor':
        plan['scenes'][0]['actions'] = [{'actor': v, 'verb': 'walk', 'at_beat': bid, 'intensity': 1}]
    if field == 'ref':
        plan['scenes'][0]['elements'].append({'kind': 'picture', 'ref': v})
    if field == 'colour':
        plan['style']['palette']['accent'] = v
    out = {}
    ms = _timed(lambda: out.update(zip(('plan', 'repairs'), validate(plan, board, {bid: ['fl_lamp']}))))
    assert ms < 100, f'{field} {kind}: {ms:.0f} ms'
    assert out['repairs'] and all(len(r) < 400 for r in out['repairs'])

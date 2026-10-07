"""Named animals in an offline v3 plan stay animals even without a species noun beside the name."""
from kinodraw import ingest, script
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.semantics import detect_cast

# The 10/6 jungle project: no "lion" anywhere, only manes, paws, a cub and a roar.
JUNGLE = """Deep in the green heart of the Ombasi Jungle, where the trees grew so tall their tops brushed the clouds, lived King Kojo. His mane was dark as wet bark and his roar could shake fruit from branches three valleys away.

Beside him ruled Queen Mara, sleek and golden-eyed, who spoke softly but was never ignored. Where Kojo was thunder, Mara was the steady rain that came after.

And then there was Pendo, their only cub.

Pendo was small for his age, with oversized paws he hadn't grown into and a roar that came out more like a squeak.

Kojo began to answer, but Mara laid her paw gently on his. "Kojo," she said quietly.

Kojo nuzzled his son's small, damp mane. Pendo grinned and tried a roar of his own.
"""


def _cast(text):
    board = script.build(ingest.read(text), story='story')
    return {c['name']: c for c in from_rules(board, [])['cast']}


def test_offline_plan_casts_maned_king_queen_and_cub_as_lions():
    cast = _cast(JUNGLE)
    assert set(cast) == {'Kojo', 'Mara', 'Pendo'}
    for c in cast.values():
        assert (c['kind'], c['family']) == ('quadruped', 'feline'), c
    assert (cast['Kojo']['species'], cast['Kojo']['sex']) == ('lion', 'male')
    assert 'mane_black' in cast['Kojo']['marks']
    assert (cast['Mara']['species'], cast['Mara']['sex']) == ('lioness', 'female')
    assert (cast['Pendo']['species'], cast['Pendo']['age']) == ('lion', 'baby')
    assert cast['Pendo']['size'] < cast['Kojo']['size']


def test_animal_named_by_species_is_never_a_human():
    cast = _cast('Tembo, an old elephant, led the herd. Tembo walked to the river. '
                 'Kojo, a lion with a dark mane, watched. His cub Pendo watched too.')
    assert cast['Tembo']['species'] == 'elephant' and cast['Tembo']['kind'] == 'quadruped'
    assert (cast['Kojo']['species'], cast['Kojo']['kind']) == ('lion', 'quadruped')
    assert 'mane_black' in cast['Kojo']['marks']
    assert (cast['Pendo']['species'], cast['Pendo']['age']) == ('lion', 'baby')


def test_people_stay_people():
    spoken = ('Ada wore a fur coat and walked her dog Rex. Ada said hello. '
              'Doctor Lee examined the lion. Lee said it was well.')
    cast = {c['name']: c for c in detect_cast([{'id': 'b1', 'text': spoken, 'spoken': spoken}])}
    assert cast['Ada']['kind'] == 'human'
    assert cast['Lee']['kind'] == 'human'
    assert cast['Rex']['species'] == 'dog'

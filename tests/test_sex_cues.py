"""A person's sex reads at every age and in every outfit (gauntlet r6, 2026-10-08): a woman keeps a woman's hair and
never wears a tie, an old man is never drawn with an old woman's curls, two people the story never sexes are told
apart, and the same person at another age keeps their look."""
from PIL import Image

from kinodraw import speech
from kinodraw.director.v3.semantics import beats
from kinodraw.director.v3.story import Reader
from kinodraw.engine import people, storybook
from kinodraw.library.creaturegen import human

AGES = ('child', 'teen', 'adult', 'middle', 'elder')
NAMES = ('Ada', 'Bea', 'Cleo', 'Dana', 'Eve', 'Fay', 'Gwen', 'Hana', 'Iris', 'Jade', 'Kira', 'Lia', 'Mona', 'Nell',
         'Opal', 'Pia', 'Rae', 'Sia', 'Tess', 'Uma', 'Vera', 'Wren', 'Yara', 'Zoe')


def distance(a, b):
    x, y = ([int(c.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)] for c in (a, b))
    return sum((p - q) ** 2 for p, q in zip(x, y)) ** .5


def person(cid, name, sex='unknown', age='adult', marks=('none',)):
    return {'id': cid, 'name': name, 'kind': 'human', 'species': 'human', 'family': 'human', 'age': age, 'sex': sex,
            'size': 1., 'palette': {'body': '#C98A62', 'accent': '#38566D', 'eye': '#30251F'}, 'marks': list(marks),
            'temperament': 'gentle'}


def book(cast, *texts):
    plan = {'cast': cast, 'storyboard': {'genre': 'story'}, 'scenes': []}
    by_id = {b['id']: b for b in beats([{'id': f'b{i}', 'spoken': t} for i, t in enumerate(texts)])}
    return storybook.Storybook(plan, by_id, {'beats': {}}, (640, 360), Image.new('RGB', (8, 8)))


def drawn(b, cid, age):
    """(sex, hair style, outfit, flags) of the sprite a cast member is drawn with at an age."""
    look = b.looks[cid]
    did = storybook.preset('human', age, look['sex'], 'stand', 'r', tuple(f'{k}:{v}' for k, v in look.items() if v))[0]
    m = people.LOOK_RE.match(did)
    assert m, did
    return m['sex'], m['style'], m['outfit'], m['flags']


def test_a_woman_keeps_a_womans_hair_at_every_age_and_an_old_one_wears_a_bun():
    cast = [person(n.lower(), n, 'female') for n in NAMES]
    b = book(cast, ' '.join(f'{n} waved.' for n in NAMES))
    for c in cast:
        styles = {age: drawn(b, c['id'], age)[1] for age in AGES}
        assert set(styles.values()) <= {'long', 'bun', 'ponytail'}, (c['id'], styles)
        assert styles['elder'] == 'bun'


def test_an_old_man_reads_as_a_man_and_middle_age_keeps_his_style():
    names = ('Abe', 'Ben', 'Cal', 'Dov', 'Eli', 'Fin', 'Gus', 'Hal', 'Ian', 'Jon', 'Ken', 'Lev', 'Max', 'Ned')
    cast = [person(n.lower(), n, 'male') for n in names]
    b = book(cast, ' '.join(f'{n} waved.' for n in names))
    for c in cast:
        own = b.looks[c['id']]['style']
        assert drawn(b, c['id'], 'middle')[1] == own                 # greying changes the colour, not the style
        assert drawn(b, c['id'], 'elder')[1] == 'bald', c['id']       # receding, white at the sides: never curls


def test_a_woman_never_wears_a_tie_in_any_outfit():
    for outfit in people.OUTFITS:
        for sex in ('female', 'male'):
            names = [layer.name for layer in human.build(human.Person(sex=sex, outfit=outfit), 'stand').layers]
            if sex == 'female':
                assert 'tie' not in names, outfit
            elif outfit in ('teacher', 'suit'):
                assert 'tie' in names, outfit


def test_a_womans_work_clothes_never_put_a_tie_over_a_skirt():
    cast = [person('anchor', 'Anchor', 'female'), person('mia', 'Mia', 'female')]
    b = book(cast, 'Anchor read the news. Mia, the principal, smiled.')
    for cid in ('anchor', 'mia'):
        for age in ('adult', 'middle', 'elder'):
            sex, _, outfit, _ = drawn(b, cid, age)
            look = people.LOOK_RE.match(storybook.preset('human', age, sex, 'stand', 'r', tuple(
                f'{k}:{v}' for k, v in b.looks[cid].items() if v))[0])
            g = human.Person(age=age, sex=sex, outfit=outfit, dress='d' in look['flags'])
            names = [layer.name for layer in human.build(g, 'stand').layers]
            assert 'tie' not in names, (cid, age, outfit)


def test_two_people_the_story_never_sexes_are_told_apart():
    for a, b_ in (('alex', 'robin'), ('kit', 'casey'), ('jo', 'speaker')):
        cast = [person(a, a.title()), person(b_, b_.title())]
        text = f"Happy 25th {a.title()}, twenty-five years and you're still stealing my fries."
        b = book(cast, text)
        assert b.looks[a]['sex'] != b.looks[b_]['sex'], (a, b_)
        reader = Reader(cast)
        reader.prime([text])
        # The voice and the drawing agree.
        assert [speech.person_sex(c, c['id'], reader, [text]) for c in cast] == [b.looks[a]['sex'],
                                                                                 b.looks[b_]['sex']]


def test_a_cue_in_the_text_still_wins_over_the_pair_rule():
    cast = [person('alex', 'Alex'), person('robin', 'Robin')]
    b = book(cast, 'Alex took her coat. Robin smiled at her.')
    assert b.looks['alex']['sex'] == 'female'


def test_the_same_person_at_another_age_keeps_their_skin_clothes_and_hair():
    cast = [person('theo', 'Theo', 'male', 'young'), person('theo_old', 'Theo, very old', 'male', 'old'),
            person('mara', 'Mara', 'female'), person('old_mara', 'Old Mara', 'female', 'old')]
    b = book(cast, 'Theo opened the letter. Mara laughed.')
    for young, old in (('theo', 'theo_old'), ('mara', 'old_mara')):
        for key in ('tone', 'top', 'hair', 'style', 'sex'):
            assert b.looks[young][key] == b.looks[old][key], (young, key)


def test_hair_stands_out_from_the_skin():
    cast = [person(n.lower(), n, 'female', marks=('dark',)) for n in NAMES[:8]]
    b = book(cast, ' '.join(f'{n} waved.' for n in NAMES[:8]))
    for c in cast:
        look = b.looks[c['id']]
        assert look['tone'] == 'brown'
        assert distance(look['hair'], people.SKIN['brown']) >= 60, (c['id'], look['hair'])


def test_middle_age_greys_inside_the_hair_never_over_the_ears():
    for style in ('short', 'curly', 'long', 'bun', 'ponytail'):
        g = human.Person(age='middle', sex='female' if style in ('long', 'bun', 'ponytail') else 'male',
                         hair_style=style)
        grey = [layer for layer in human.build(g, 'stand').layers if layer.name == 'grey_temples']
        assert grey and all(layer.kind == 'patch' and layer.clip is not None for layer in grey), style


def test_a_presenter_who_names_a_grown_ups_role_is_a_grown_up_dressed_for_it():
    texts = ["Hi, I'm Dana, the owner of Juniper Lane Bakery.", 'Every morning we bake forty loaves before seven.']
    for age in ('young', 'baby', 'adult'):
        b = book([person('dana', 'Dana', 'female', age)], *texts)
        assert b.reader.look_age('dana') == 'adult', age
        sex, style, outfit, _ = drawn(b, 'dana', b.reader.look_age('dana'))
        assert (sex, outfit) == ('female', 'apron') and style in ('long', 'bun', 'ponytail')
    b = book([person('rowan', 'Rowan', 'female', 'young')], "Hello, I'm Rowan, founder of Kestrel Labs.",
             'We build quiet fans.')
    assert b.reader.look_age('rowan') == 'adult'
    sex, _, outfit, flags = drawn(b, 'rowan', 'adult')
    assert outfit == 'suit' and 'tie' not in [
        layer.name for layer in human.build(human.Person(sex=sex, outfit=outfit, dress='d' in flags), 'stand').layers]
    b = book([person('kim', 'Kim', 'male', 'young')], 'Kim is the store manager.', 'We open at nine.')
    assert b.reader.look_age('kim') == 'adult'


def test_a_role_said_about_someone_else_leaves_a_child_a_child():
    b = book([person('lee', 'Lee', 'male', 'young')], 'Lee, a boy whose mother was a nurse, ran home.')
    assert b.reader.look_age('lee') == 'child'


def test_a_time_of_day_is_not_an_age_and_an_age_still_is():
    b = book([person('kim', 'Kim', 'male', 'adult')], 'Kim waved.', 'We open at nine.', 'Doors close at ten tonight.')
    assert 'kim' not in b.reader.first_years and b.reader.look_age('kim') == 'adult'
    b = book([person('ana', 'Ana', 'female', 'adult')], 'Ana moved from Lima to Ohio at nine.')
    assert b.reader.first_years.get('ana') == 9

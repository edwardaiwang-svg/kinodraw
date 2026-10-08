"""Ages and identity of the people a story draws: ages from the text, a build per age band, no twins, vocatives that
name somebody already there, and work clothes from role words (gauntlet r5, 2026-10-08)."""
from PIL import Image

from kinodraw.director.v3.semantics import beats, detect_cast
from kinodraw.director.v3.story import Reader
from kinodraw.director.v3 import validate
from kinodraw.engine import storybook
from kinodraw.library.creaturegen import human


def _people():
    from kinodraw.engine import people
    return people


def person(cid, name, sex='unknown', age='adult'):
    return {'id': cid, 'name': name, 'kind': 'human', 'species': 'human', 'family': 'human', 'age': age, 'sex': sex,
            'size': 1., 'palette': {'body': '#C98A62', 'accent': '#38566D', 'eye': '#30251F'}, 'marks': ['none'],
            'temperament': 'gentle'}


def read(cast, *texts):
    reader = Reader(cast)
    reader.prime(texts)
    return reader, [line for i, text in enumerate(texts) for line in reader.read(f'b{i}', text)]


def looks(lines, cid):
    return [line.looks.get(cid) for line in lines if cid in line.looks]


# ------------------------------------------------------------------ ages from the text
def test_turning_fifty_is_middle_aged_and_a_look_back_is_a_child():
    reader, lines = read([person('uncle_dev', 'Uncle Dev', 'male', 'old')], 'Uncle Dev turns 50!!',
                         'grew up in Kestrel Falls', 'ran the hardware store 22 years')
    assert reader.first_years == {'uncle_dev': 50}
    assert [line.looks.get('uncle_dev') for line in lines] == ['middle', 'child', 'middle']
    assert reader.look_age('uncle_dev') == 'middle'


def test_a_birthday_in_present_tense_states_an_age():
    reader, lines = read([person('ruth', 'Grandma Ruth', 'female', 'adult')], 'Grandma Ruth is turning 80 today.')
    assert reader.first_years == {'ruth': 80} and lines[0].ages['ruth'] == 'elder'


def test_stated_ages_move_one_person_on_and_never_the_grandmother():
    cast = [person('lena', 'Lena', 'female', 'young'), person('nana', 'Nana', 'female', 'old')]
    reader, lines = read(cast, 'When Lena was nine, Nana got a phone.', 'At sixteen, Lena rode the bus.',
                         'At nineteen, in a lecture hall on her first day of college, Lena felt small.',
                         "At twenty-five, the text didn't come one morning.", 'Lena drove to the hospital.',
                         'Nana was sitting up in bed.')
    assert 'nana' not in reader.first_years
    assert set(looks(lines, 'nana')) == {'elder'}
    assert [lines[i].looks['lena'] for i in (0, 1, 2, 4)] == ['child', 'teen', 'teen', 'adult']
    assert reader.years['lena'] == 25


def test_an_age_after_a_name_in_commas_is_theirs_and_the_role_before_it_is_them():
    cast = [person('maya', 'Maya', 'female', 'adult'), person('kai', 'Kai', 'male', 'baby')]
    reader, lines = read(cast, 'Maya sat on a bench while her son Kai, four, chased a pigeon.')
    assert reader.first_years.get('kai') == 4 and lines[0].ages['kai'] == 'child'
    assert lines[0].extras == []                         # "her son Kai" is Kai, not a new person


def test_six_eggs_is_not_an_age():
    reader, lines = read([person('sam', 'Sam', 'male')], 'Sam bought six eggs, then went home.')
    assert reader.first_years == {} and lines[0].ages['sam'] == 'adult'


def test_a_young_married_man_stays_a_grown_up():
    reader, lines = read([person('ben', 'Ben', 'male')], 'Ben came home. He was young and married then.')
    assert set(looks(lines, 'ben')) == {'adult'}


def test_years_together_make_a_couple_middle_aged():
    cast = [person('jo', 'Jo'), person('speaker', 'Speaker')]
    _, lines = read(cast, "Happy 25th Jo, twenty-five years and you're still stealing my fries.")
    assert lines[0].looks['jo'] == 'middle'
    reader, _ = read([person('ruth', 'Ruth', 'female'), person('al', 'Al', 'male')],
                     'Forty years of marriage, and Ruth still laughs at his jokes.')
    assert reader.age_band('ruth') == 'elder'


def test_middle_aged_words_and_adult_titles():
    reader, lines = read([person('tom', 'Tom', 'male')], 'Tom, a middle-aged plumber, fixed the sink.')
    assert lines[0].looks['tom'] == 'middle'
    reader = Reader([person('dev', 'Uncle Dev', 'male', 'young'), person('kid', 'Pip', 'male', 'young')])
    assert reader.age_band('dev') == 'adult' and reader.age_band('kid') == 'child'
    assert reader.told('dev') and not reader.told('kid')


# ------------------------------------------------------------------ a build per age band
def heads_tall(age):
    fig = human.build(human.Person(age=age), 'stand')
    box = fig.bounds()
    return (box[3] - box[1]) / (2 * human.PROPORTIONS[age][0])


def test_each_age_band_has_its_own_build_and_grown_ups_are_never_child_shaped():
    tall = {age: heads_tall(age) for age in ('child', 'teen', 'adult', 'middle', 'elder')}
    assert tall['child'] < 2.4 < tall['teen'] < tall['adult']
    assert min(tall['adult'], tall['middle'], tall['elder']) >= 3.0


def test_the_storybook_draws_teen_and_middle_aged_people_in_their_own_look():
    look = ('sex:female', 'everyday:villager', 'top:#5B8DD6', 'bottom:#3D4A5C', 'hair:#3B2B24',
            'elder_hair:#E6E2DA', 'style:long', 'tone:tan', 'accent:#C0504D')
    people = _people()
    ids = {age: storybook.preset('human', age, 'female', 'stand', 'r', look)[0]
           for age in ('child', 'teen', 'adult', 'middle', 'elder')}
    assert all(people.is_person(i) for i in ids.values())
    assert [i.split('_')[3] for i in ids.values()] == ['child', 'teen', 'adult', 'middle', 'elder']
    assert storybook.meta(ids['teen'])['anchors']['mouth']
    assert '_middle_' in storybook.face('human', 'middle', 'female', look)
    svg = people.svg(ids['middle'])
    assert svg and '#B8B4AC' in svg.upper()              # grey temples


# ------------------------------------------------------------------ identity and costume
def book(cast, *texts):
    plan = {'cast': cast, 'storyboard': {'genre': 'story'}, 'scenes': []}
    by_id = {b['id']: b for b in beats([{'id': f'b{i}', 'spoken': t} for i, t in enumerate(texts)])}
    return storybook.Storybook(plan, by_id, {'beats': {}}, (640, 360), Image.new('RGB', (8, 8)))


def test_no_two_people_share_clothes_and_hair():
    cast = [person(f'p{i}', name, 'female') for i, name in enumerate(('Anchor', 'Jenna Ruiz', 'Maria Chen', 'Ada',
                                                                      'Bea', 'Cleo'))]
    b = book(cast, 'Jenna Ruiz has the story.')
    seen = [(l['top'], l['hair'], l['style']) for l in b.looks.values()]
    assert len({top for top, _, _ in seen}) == len(seen)


def test_role_words_dress_people_for_their_work():
    cast = [person('anchor', 'Anchor'), person('tom', 'Tom', 'male'), person('ana', 'Ana', 'female'),
            person('lee', 'Lee', 'male'), person('jo', 'Jo', 'female'), person('sam', 'Sam Okafor', 'male')]
    b = book(cast, 'Tom, the plumber, waved. Chef Ana tasted the soup. Dr. Lee frowned.', 'Jo met the baker.',
             'LOWER THIRD: Sam Okafor - Town Engineer')
    people = _people()
    roles = {cid: l.get('role') for cid, l in b.looks.items()}
    assert roles == {'anchor': 'suit', 'tom': 'worker', 'ana': 'apron', 'lee': '', 'jo': '', 'sam': 'worker'}
    assert b.looks['anchor']['top'] in people.ROLE_TOPS['suit']
    doodle = storybook.preset('human', 'adult', 'male', 'stand', 'r',
                              tuple(f'{k}:{v}' for k, v in b.looks['tom'].items() if v))[0]
    assert '_worker_' in doodle


# ------------------------------------------------------------------ vocatives
def test_a_kin_word_said_to_someone_is_not_a_new_cast_member():
    text = ('At thirty-two, Lena sat on a bench while her daughter Rosie fed the ducks.\n\n'
            '"Mom, what\'s that turtle on your phone?"\n\n"Thanks, Nana," Lena said.')
    names = [c['name'] for c in detect_cast([{'id': 'b1', 'spoken': text, 'section': 'main'}])]
    assert 'Mom' not in names and 'Nana' not in names and 'Lena' in names
    told = [c['name'] for c in detect_cast([{'id': 'b1', 'spoken': 'Mom came home late. Mom said hi.', 'section': 'm'}])]
    assert told == ['Mom']                               # Mom who acts outside quotes is a person


def test_a_mom_already_in_the_cast_is_reused():
    cast = [person('theo', 'Theo', 'male', 'young'), person('theos_mother', "Theo's mother", 'female')]
    assert validate._role_taken({'name': 'Mom', 'id': 'mom'}, cast)
    assert validate._role_taken({'name': 'Dad', 'id': 'dad'}, cast) is False
    assert not validate._role_taken({'name': 'Mom', 'id': 'mom'}, cast[:1])


def test_voice_and_drawing_agree_on_a_grown_up_title():
    from kinodraw import speech
    cast = [person('dev', 'Uncle Dev', 'male', 'young'), person('anchor', 'Anchor', 'unknown', 'young')]
    reader, lines = read(cast, 'Uncle Dev waved.', 'Anchor smiled.')
    assert speech._person(cast[0], 'dev', reader, ['Uncle Dev waved.'])[1] == 'adult'
    assert speech._person(cast[1], 'anchor', reader, ['Anchor smiled.'])[1] == 'adult'
    assert [line.ages for line in lines] == [{'dev': 'adult'}, {'anchor': 'adult'}]

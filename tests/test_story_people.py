"""People in story pages: who is on the page, at what age, in what pose, and who speaks (gauntlet r1, 2026-10-08)."""
import json

import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.story import Reader
from kinodraw.engine import render, storybook, timeline


def person(cid, name, sex, age='adult'):
    return {'id': cid, 'name': name, 'kind': 'human', 'species': 'human', 'family': 'human', 'age': age, 'sex': sex,
            'size': 1., 'palette': {'body': '#49677A', 'accent': '#A64B00', 'eye': '#182536'}, 'marks': ['none'],
            'temperament': 'gentle'}


ROOM = [person('noor', 'Noor', 'female', 'old'), person('noors_father', "Noor's father", 'male'),
        person('sam', 'Sam', 'unknown', 'young')]


def read(cast, *beats):
    reader = Reader(cast)
    reader.prime(beats)
    return [line for i, text in enumerate(beats) for line in reader.read(f'b{i}', text)]


def test_a_relative_takes_the_pose_and_the_lines_never_the_protagonist():
    lines = read(ROOM, 'Noor came home. Her father was fast asleep on the sofa.',
                 '"Wake up," she said.', '"Five more minutes," he said.', '"Now!"', 'Her father laughed.',
                 '"Fine."')
    asleep, wake, five, now, laughed, fine = lines[1:]
    assert asleep.poses == {'noors_father': ('sleep', asleep.poses['noors_father'][1])}
    assert set(asleep.present) == {'noor', 'noors_father'}
    assert wake.speaker == 'noor' and five.speaker == 'noors_father'
    assert now.speaker == 'noor'                       # a bare reply alternates in a two-person exchange
    assert laughed.subject == 'noors_father'           # "Her father laughed": the father, not "her"
    assert fine.speaker == 'noors_father'              # a bare quote after narration is its subject's


def test_kin_words_resolve_to_the_one_person_they_can_mean_and_strangers_are_extras():
    cast = [person('mia', 'Mia', 'female', 'young'), person('rosa', 'Rosa', 'female')]
    [smiled] = read(cast, 'Mia ran in. Her mother smiled.')[1:]
    assert smiled.subject == 'rosa' and 'mia' in smiled.present
    [waved] = read(cast, 'A stranger waved at Mia.')
    assert waved.extras == ['+stranger'] and waved.present == ['mia']
    [crowd] = read(cast, 'Every child in town had one.')
    assert crowd.extras == [] and crowd.present == []


def test_pronouns_tell_the_sex_the_plan_left_unknown():
    lines = read(ROOM, "Noor's father taught Sam to whistle and she laughed.", 'Sam waved.', '"Again!" she said.')
    assert lines[-1].speaker == 'sam'


def test_ages_follow_the_story():
    cast = [person('maya', 'Maya', 'female', 'old')]
    lines = read(cast, 'Maya loved kites.', 'Maya was seven when she built her first one.',
                 'At seventeen, she flew it over the bay.', "She'd learned it at nine, it turned out.",
                 'Forty years later, Maya still had it.', 'When she was very old, she gave it away.')
    assert [line.ages['maya'] for line in lines] == ['child', 'child', 'teen', 'child', 'adult', 'elder']


def test_a_note_to_a_teenager_recalls_them_as_a_child():
    cast = [person('ben', 'Ben', 'male'), person('ada', 'Ada', 'female', 'young')]
    lines = read(cast, 'At sixteen, Ben found the note. He read it twice.',
                 'The day you carried Ada home in the rain.')
    assert lines[-1].ages == {'ben': 'child', 'ada': 'child'} and set(lines[-1].present) == {'ben', 'ada'}


def test_month_names_are_not_poses():
    [line] = read(ROOM, 'Noor came back on the fourth of March.')
    assert line.poses == {}


STORY = ('# The Porch\n\n'
         'Noor ran home through the rain. Her father was asleep on the porch.\n\n'
         '"Wake up," she said.\n\n'
         '"Five more minutes," he said.\n\n'
         'When she was very old, Noor told her granddaughter about that porch.')


def production(tmp_path, cast, text=STORY, staged=None):
    """A story production whose plan has this human cast (the offline director casts animals only)."""
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['cast'] = cast
    plan['storyboard']['genre'], plan['style']['mode'] = 'story', 'hybrid'
    for scene in plan['scenes']:
        scene['treatment'] = 'character'
        scene['elements'] = [e for e in scene['elements'] if e['kind'] != 'cast']
        scene['elements'] += [{'kind': 'cast', 'ref': cid} for cid in (staged or {}).get(scene['beat_ids'][0], ())]
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    return prod


def shot_saying(prod, words):
    for span in prod.spans:
        for bid in span.spec['beat_ids']:
            spoken = prod.by_id[bid]['spoken']
            if words in spoken:
                timing = prod.tl['beats'][bid]
                at = timing['start'] - span.start + timing['char_times'][spoken.index(words)]
                return next(s for s in reversed(span.story) if s.start <= at + 1e-6)
    raise AssertionError(words)


def drawn(book, f):
    return storybook.meta(book._pose_doodle(f, 1e6)[0])


def test_people_are_presets_of_their_age_sex_and_pose_in_one_look(tmp_path):
    cast = [person('noor', 'Noor', 'female', 'young'), person('noors_father', "Noor's father", 'male'),
            person('granddaughter', "Noor's granddaughter", 'female', 'young')]
    prod = production(tmp_path, cast)
    book = prod.storybook
    porch = shot_saying(prod, 'asleep on the porch')
    figures = {f.key: f for f in porch.figures}
    assert set(figures) == {'noor', 'noors_father'}
    father = drawn(book, figures['noors_father'])
    assert (father['species'], father['sex'], father['age'], father['pose']) == ('human', 'male', 'adult', 'sleep')
    noor = drawn(book, figures['noor'])
    assert (noor['sex'], noor['age']) == ('female', 'child')
    old = shot_saying(prod, 'When she was very old')
    figures = {f.key: f for f in old.figures}
    later = drawn(book, figures['noor'])
    assert later['age'] == 'elder' and later['variant'].rsplit('_', 1)[1] == noor['variant'].rsplit('_', 1)[1]
    assert drawn(book, figures['granddaughter'])['age'] == 'child'
    assert len({book._look(cid)['tone'] for cid in ('noor', 'granddaughter')}) == 2     # two girls look different


def test_the_bubble_sits_on_the_speaker_and_listeners_face_them(tmp_path):
    cast = [person('noor', 'Noor', 'female', 'young'), person('noors_father', "Noor's father", 'male')]
    prod = production(tmp_path, cast)
    for words, speaker in (('Wake up', 'noor'), ('Five more minutes', 'noors_father')):
        shot = shot_saying(prod, words)
        assert [b.speaker for b in shot.bubbles] == [speaker]
        talker = next(f for f in shot.figures if f.key == speaker)
        for f in shot.figures:
            if f is not talker:
                assert (f.facing == 'r') == (talker.x > f.x)


def test_people_the_plan_stages_are_on_the_page(tmp_path):
    cast = [person('noor', 'Noor', 'female', 'young'), person('noors_father', "Noor's father", 'male')]
    text = '# Rain\n\nNoor ran home through the rain.\n\nThe porch light was on.'
    prod = production(tmp_path, cast, text, staged={'b001': ['noor', 'noors_father']})
    ran = shot_saying(prod, 'Noor ran home')
    assert {f.key for f in ran.figures} == {'noor', 'noors_father'}


@pytest.mark.parametrize('prop, pose, seated', [('tb_sofa', 'sit', True), ('fl_bed', 'sleep', True),
                                                ('fl_deciduous_tree', 'lie', False)])
def test_a_resting_person_sits_or_lies_on_a_support_the_page_shows(prop, pose, seated):
    f = storybook.Figure('noor', 'human', pose=pose, x=.3)
    shot = storybook.Shot(0., 1., figures=[f], props=[(prop, .7, .78, .3)])
    assert (storybook.Storybook.seat(f, shot) == prop) == seated
    assert (f.x, f.ground < storybook.GROUND) == ((.7, True) if seated else (.3, False))

"""Pictures follow the sense of a word, not the word (gauntlet critics, 10/8): what the planner is offered, and what
content QA counts as shown."""
import copy
from functools import lru_cache

import imageio_ffmpeg
import numpy as np
import pytest

from kinodraw import ingest, script
from kinodraw.director.llm.providers import ProviderError
from kinodraw.director.v3.llm import plan_v3
from kinodraw.engine import timeline
from kinodraw.qa import content

# Customer-style scripts the critics measured (pool scripts reduced to the sentences that drew a wrong picture).
BIRTHDAY = 'Uncle Dev turns fifty!!\n\ngrew up in Kestrel Falls\n\nran Bramwell Hardware twenty-two yrs\n'
PLUMBER = ('Find the drip. A faucet leaking one drop a second wastes over three thousand gallons a year.\n\n'
           'Do all five and you could save up to twenty percent. And if that drip turns out to be bigger than a '
           'washer, you know who to call.\n')
LESSON = ('Start at 0. Jump 3, then jump 5. You land on 8.\n\n'
          'Now swap the order. Jump 5 first, then 3. 8 again.\n\n'
          'When you add, the order does not matter. This is the commutative property of addition. '
          'A plus B equals B plus A.\n\n'
          'Multiplication works the same way. Here are 3 rows of 5 dots. 3 times 5 is 15.\n\n'
          'Now give the picture a quarter turn. It shows 5 rows of 3. 5 times 3. No dot was added or taken away. '
          'So the answer is still 15.\n\n'
          'This is the commutative property of multiplication. x times y equals y times x.\n\n'
          'Quick check. Decide whether each statement is true or false.\n')
LIONS = ('Once upon a time, a tiny lion cub named Pendo lived with his pride. Pendo loved his mother, Mara, more than '
         'anyone else.\n\n'
         'But Pendo was terrified of his father, the great King Kojo. Kojo had a massive black mane.\n\n'
         'With one massive swipe of his heavy paw, Kojo sent the lead hyena flying into the bushes.\n\n'
         'Then, the giant king turned around and nudged Pendo with his nose.\n')
PORCH = ('Ruth made lemonade for the whole street. She set out a pitcher on the porch with a sign that said "Free. '
         'From Eddie."\n\nHe pulled over. The headlights lit up a fence, a field, and nothing else.\n')
LETTER = 'The Envelope\n\nTheo found an old envelope in the drawer with a letter inside.\n'

# (script, words of the beat, the word, pictures that share only the word and must never be offered for it)
WRONG = [
    (BIRTHDAY, 'Kestrel Falls', 'Falls', {'fl_maple_leaf', 'chart_down', 'fl_eagle', 'fl_fallen_leaf'}),
    (BIRTHDAY, 'Bramwell Hardware', 'Hardware', {'memory_chip', 'circuit_board', 'gpu_rack', 'chip_semis',
                                                 'fl_floppy_disk'}),
    (PLUMBER, 'Find the drip', 'drip', {'hi_intravenous_drip', 'hi_intravenous_bag'}),
    (PLUMBER, 'that drip turns out', 'drip', {'hi_intravenous_drip', 'hi_intravenous_bag'}),
    (LESSON, 'Jump 3', 'jump', {'fl_kangaroo'}),
    (LESSON, 'swap the order', 'order', {'tb_menu_order'}),
    (LESSON, 'quarter turn', 'picture', {'fl_framed_picture', 'camera'}),
    (LESSON, 'Quick check', 'check', {'fl_check_box_with_check', 'fl_check_mark', 'check_big', 'tb_check'}),
    (LESSON, 'A plus B', 'plus', {'fl_plus', 'fl_heavy_equals_sign'}),
    (LIONS, 'King Kojo', 'King', {'crown', 'fl_crown', 'tb_crown', 'tb_chess_king'}),
    (LIONS, 'giant king', 'king', {'crown', 'fl_crown', 'tb_crown', 'tb_chess_king'}),
    (LIONS, 'heavy paw', 'paw', {'fl_paw_prints', 'tb_paw'}),
    (PORCH, 'sign that said', 'sign', {'fl_stop_sign'}),
    (PORCH, 'a fence, a field', 'field', {'fl_field_hockey'}),
    (LETTER, 'old envelope', 'envelope', {'fl_red_envelope'}),
]
# (sentence, a picture that the sentence plainly names and must still be offered)
RIGHT = [
    ('A stop sign stood at the corner of the street.', 'fl_stop_sign'),
    ('A maple leaf fell from the tree.', 'fl_maple_leaf'),
    ('The kangaroo jumped over the fence.', 'fl_kangaroo'),
    ('The nurse checked the IV drip in the hospital.', 'hi_intravenous_drip'),
    ('She placed a crown on the queen\'s head.', 'crown'),
    ('Theo found an old envelope in the drawer with a letter inside.', 'fl_envelope'),
    ('Grandma gave him a red envelope of lucky money for the new year.', 'fl_red_envelope'),
    ('An orange rolled into the street.', 'fl_tangerine'),
    ('His mother was half-asleep in front of the TV.', 'fl_television'),
]


@lru_cache(maxsize=None)
def _offered(text):
    seen = {}

    class Capture:
        name = 'capture'

        def direct_plan(self, payload, usage):
            seen.update(payload)
            raise ProviderError('captured')
    plan_v3(script.build(ingest.read(text), story='story'), provider=Capture())
    return {b['text']: [c['id'] for c in b['candidates']] for b in seen['beats']}


def _beat(text, words):
    beats = _offered(text)
    return next(ids for spoken, ids in beats.items() if words.lower() in spoken.lower())


@pytest.mark.parametrize('text,where,word,wrong', WRONG, ids=[f'{w[2]}:{sorted(w[3])[0]}' for w in WRONG])
def test_a_picture_that_only_shares_the_word_is_never_offered(text, where, word, wrong):
    assert not wrong & set(_beat(text, where)), (word, sorted(wrong & set(_beat(text, where))))


@pytest.mark.parametrize('sentence,right', RIGHT, ids=[r[1] for r in RIGHT])
def test_a_picture_the_sentence_plainly_names_is_still_offered(sentence, right):
    assert right in _beat(sentence + '\n', sentence[:12])


def test_a_story_of_animals_is_offered_no_people_for_its_kin_words():
    ids = _beat(LIONS, 'his mother')
    assert not [i for i in ids if i.startswith('cr_human_')], ids


def test_a_math_lesson_is_offered_only_what_its_numbers_count():
    ids = _beat(LESSON, '3 rows of 5 dots')
    assert ids and all('dot' in i for i in ids), ids          # the counted dots, nothing by look-alike meaning
    assert _beat(LESSON, 'Quick check') == []


def test_names_are_read_as_places_of_their_kind():
    from kinodraw.director.match import Matcher, proper_names, unname
    found = {LESSON[a:b] for a, b, _ in proper_names(LESSON)}
    assert not found                                           # "A plus B", "Jump 3": no names
    assert [(BIRTHDAY[a:b], k) for a, b, k in proper_names(BIRTHDAY)] == [
        ('Uncle Dev', None), ('Kestrel Falls', 'town'), ('Bramwell Hardware', 'shop')]
    assert unname('They crossed the Elm Street Bridge.') == 'They crossed the bridge.'
    assert proper_names('He looked at the Moon.') == []
    assert proper_names('Pip and the Missing Moon') == []       # a Title Case heading
    hits = {h.id for h in Matcher('en').lexical('ran Bramwell Hardware twenty-two yrs')}
    assert not hits & {'memory_chip', 'circuit_board', 'gpu_rack'}, hits


# ------------------------------------------------------------------ content QA
def _lesson(scenes):
    board = script.build(ingest.read('# Order Does Not Matter\n\n' + LESSON), story='story')
    plan = {'storyboard': {'genre': 'lesson'}, 'cast': [], 'scenes': []}
    for beat, (pictures, items) in zip(board['beats'], scenes):
        plan['scenes'].append({
            'beat_ids': [beat['id']], 'treatment': 'whiteboard', 'text': {'kind': 'caption_only', 'ref': beat['id']},
            'elements': [{'kind': 'picture', 'ref': p} for p in pictures],
            'boards': [{'layout': 'flow', 'items': [dict(id=f'{beat["id"]}i{k}', beat_id=beat['id'], cue=cue, kind=kind,
                                                          ref='', to='', at='auto', text=cue, style='none')
                                                     for k, (kind, cue) in enumerate(items)]}] if items else []})
    return plan, board


# The saved plan the critic scored 0 for imagery (icons picked by a shared word) and the fresh plan that drew the
# number line, the hops and the dot arrays on a board (its picture-less scenes are not empty).
ICONS = [(['fl_kangaroo'], []), (['tb_menu_order'], []), (['fl_plus', 'fl_heavy_equals_sign'], []),
         (['tb_freeze_row_column'], []), (['fl_framed_picture'], []), (['fl_heavy_equals_sign'], []),
         (['fl_check_box_with_check'], [])]
BOARDS = [([], [('number_line', 'Start at 0.'), ('hop', 'Jump 3')]), ([], [('hop', 'Jump 5 first')]),
          (['seesaw_balance'], [('equation', 'A plus B equals B plus A.')]), ([], [('dots', 'Here are 3 rows')]),
          ([], [('dots', 'It shows 5 rows of 3.')]), (['fl_multiply'], [('equation', 'x times y')]),
          ([], [('label', 'Quick check.')])]


def test_content_qa_is_no_longer_inverted_on_the_commutative_lesson():
    icons = content.check(*_lesson(ICONS))
    boards = content.check(*_lesson(BOARDS))
    assert [f['check'] for f in icons['findings']] == ['unshown']
    assert icons['stats']['unshown'] >= .9 * icons['stats']['concrete']
    assert 'unshown' not in [f['check'] for f in boards['findings']], boards['problems']


def test_a_number_sentence_shown_only_by_an_icon_is_a_finding():
    board = script.build(ingest.read('# Q3 Update\n\nRevenue grew to 4.2 million dollars, up 18 percent from last '
                                     'year.\n\nOur trucks carried 3,100 tons of food scraps.\n\n'
                                     'Thank you to every driver.\n'), story='story')
    beats = board['beats']
    plan = {'storyboard': {'genre': 'explainer'}, 'cast': [], 'scenes': [
        {'beat_ids': [beats[0]['id']], 'treatment': 'whiteboard', 'text': {'kind': 'kinetic', 'ref': beats[0]['id']},
         'elements': [{'kind': 'picture', 'ref': 'fl_newspaper'}]},
        {'beat_ids': [beats[1]['id']], 'treatment': 'chart', 'text': {'kind': 'counter', 'ref': beats[1]['id']},
         'elements': []},
        {'beat_ids': [b['id'] for b in beats[2:]], 'treatment': 'whiteboard',
         'text': {'kind': 'caption_only', 'ref': beats[2]['id']}, 'elements': [{'kind': 'picture', 'ref': 'fl_truck'}]}]}
    report = content.check(plan, board)
    found = [f for f in report['findings'] if f['check'] == 'numbers_as_icons']
    assert found and found[0]['count'] == 1 and 'Revenue' in found[0]['problem'], report['findings']


HOWTO = ('# Banana Pancakes\n\nYou need two ripe bananas.\n\nCrack two eggs into a bowl.\n\n'
         'Heat a pan on the stove.\n\nStack the pancakes on a plate.\n')
PICTURES = ['fl_banana', 'fl_egg', 'fl_cooking', 'fl_pancakes']


def _icon_video(path, tl, side, size=(320, 180)):
    """Paper with one dark square icon of ``side`` pixels per beat, each beat's in its own place (and a caption band
    that never counts)."""
    starts = sorted(beat['start'] for beat in tl['beats'].values())
    writer = imageio_ffmpeg.write_frames(str(path), size, fps=10, macro_block_size=1)
    writer.send(None)
    for f in range(int(10 * tl['duration']) + 10):
        frame = np.full((size[1], size[0], 3), 236, np.uint8)
        x = 20 + (sum(f / 10 >= s for s in starts) % 4) * 70
        frame[40:40 + side, x:x + side] = (60, 40, 30)
        frame[-20:, 20:300] = 0
        writer.send(frame.tobytes())
    writer.close()


@pytest.mark.parametrize('side,shown', [(28, False), (60, True)])   # 1.4% and 6.3% of the frame
def test_an_icon_too_small_to_read_does_not_show_its_sentence(tmp_path, side, shown):
    board = script.build(ingest.read(HOWTO), story='story')
    plan = {'storyboard': {'genre': 'how-to'}, 'cast': [], 'scenes': [
        {'beat_ids': [b['id']], 'treatment': 'whiteboard', 'text': {'kind': 'caption_only', 'ref': b['id']},
         'elements': [{'kind': 'picture', 'ref': p}]} for b, p in zip(board['beats'], PICTURES)]}
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    assert content.check(copy.deepcopy(plan), board)['stats']['unshown'] == 0     # the plan names each one
    video = tmp_path / 'v.mp4'
    _icon_video(video, tl, side)
    report = content.check(plan, board, tl, video)
    lines = [line for line in report['lines'] if line['at'] is not None]
    assert lines and all(line['shown'] is shown for line in lines), [(line['text'], line['size']) for line in lines]
    assert ('unshown' in [f['check'] for f in report['findings']]) is not shown

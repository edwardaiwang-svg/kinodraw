"""Who says each quoted line (kinodraw/speakers.py): one attribution, made before the voices are read, that the
voices, the speech bubbles and the talking figures all follow; and the QA net that fails a render whose bubble is
voiced by somebody else."""
import json

from kinodraw import ingest, script, speech

from test_story_shots import shot, staged

MOTHER_AND_SON = [{'id': 'marisol', 'name': 'Marisol', 'kind': 'human', 'species': 'human', 'age': 'adult',
                   'sex': 'female'},
                  {'id': 'kip', 'name': 'Kip', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'unknown'},
                  {'id': 'dad', 'name': 'Dad', 'kind': 'human', 'species': 'human', 'age': 'old', 'sex': 'male'}]
LIONS = [{'id': 'pendo', 'name': 'Pendo', 'kind': 'animal', 'species': 'lion', 'age': 'baby', 'sex': 'male'},
         {'id': 'mara', 'name': 'Mara', 'kind': 'animal', 'species': 'lion', 'age': 'adult', 'sex': 'female'},
         {'id': 'kojo', 'name': 'King Kojo', 'kind': 'animal', 'species': 'lion', 'age': 'adult', 'sex': 'male'}]


def beats_of(text):
    board = script.build(ingest.read(text), 'story')
    return [{'id': b['id'], 'spoken': b['spoken'][board['lang']], 'section': b.get('chapter', 'main')}
            for b in board['beats']]


def plan_of(cast, lines=(), talk=()):
    """A plan whose shots give these (beat id, quote, speaker) lines and whose 'talk' actions these (beat, actor)."""
    return {'cast': cast, 'scenes': [{'beat_ids': [bid], 'actions': [], 'shots': [
        {'beat_id': bid, 'lines': [{'quote': q, 'speaker': who}]}]} for bid, q, who in lines] +
        [{'beat_ids': [bid], 'actions': [{'verb': 'talk', 'actor': who, 'at_beat': bid}]} for bid, who in talk]}


def said(text, cast, **plan):
    """[(quoted words, speaker)] in reading order, as the voices read them."""
    beats = beats_of(text)
    spans, _, _ = speech.quote_speakers(beats, plan_of(cast, **plan))
    spoken = {b['id']: b['spoken'] for b in beats}
    return [(spoken[bid][a:z].strip(' "“”,'), who) for b in beats for bid in [b['id']]
            for a, z, who in spans.get(bid, ())]


def bid_of(text, words):
    return next(b['id'] for b in beats_of(text) if words in b['spoken'])


# ------------------------------------------------------------------ tags
def test_a_tag_after_the_line_or_before_it_names_its_speaker_over_the_plan():
    text = ('Pendo hid whenever his father walked by. "Why is Baba so scary?" Pendo whimpered one afternoon. '
            '"He never plays with me."\n\n'
            'Mara nudged her cub gently. "Your father has a different job, little one."')
    wrong = [(bid_of(text, 'Baba'), 'Why is Baba so scary?', 'kojo')]
    assert said(text, LIONS, lines=wrong, talk=[(bid_of(text, 'Baba'), 'kojo')]) == [
        ('Why is Baba so scary?', 'pendo'), ('He never plays with me.', 'pendo'),
        ('Your father has a different job, little one.', 'mara')]


def test_said_mom_and_a_paragraph_that_introduces_the_line_name_its_speaker():
    text = ('The car had been quiet for eleven miles when Marisol finally said it.\n\n"We passed it."\n\n'
            '"We did not pass it," Kip sighed.\n\n"There was a cow," said Mom.')
    talk = [(bid_of(text, 'We passed'), 'kip')]                         # the plan's talker is wrong
    assert said(text, MOTHER_AND_SON, talk=talk) == [('We passed it.', 'marisol'), ('We did not pass it', 'kip'),
                                          ('There was a cow', 'marisol')]


# ------------------------------------------------------------------ turns between two people
WRONG_EXIT = ('The car had been quiet for eleven miles when Marisol finally said it.\n\n'
              '"We passed it."\n\n"We did not pass it," Kip said.\n\n"There was a cow. I remember the cow."\n\n'
              '"There are a thousand cows, Mom."\n\n"That one had a hat."\n\n"Cows don\'t wear hats."\n\n'
              '"This one was wearing a hat, Kip. I\'m not crazy."\n\n"Fine. Check your phone."\n\n'
              '"No bars. Check yours."\n\n"I\'m driving."\n\n"So pull over."\n\n'
              'He pulled over. The headlights lit up a fence, a field, and nothing else.\n\n'
              '"Okay. There\'s a map in the glove box. Dad\'s map."\n\n"Your father never once used that map."\n\n'
              '"Well, somebody has to."\n\nShe unfolded it across the dashboard.\n\n"It\'s upside down."\n\n'
              '"It\'s not upside down, the north is just... on the bottom."\n\n"Mom."\n\n"Fine."\n\n'
              'They sat there with the engine ticking.\n\n"You know what your father would say right now?"\n\n'
              '"\'Told you so\'?"\n\n"He\'d say, \'Let\'s go look at that cow.\'"')
TRUTH = ['marisol', 'kip', 'marisol', 'kip', 'marisol', 'kip', 'marisol', 'kip', 'marisol', 'kip', 'marisol',
         'kip', 'marisol', 'kip', 'kip', 'marisol', 'kip', 'marisol', 'marisol', 'kip', 'marisol']


def wrong_exit_plan():
    """The plan's slip from the 10/8 render: from the cow on, every line is given to the other person."""
    lines = []
    for b in beats_of(WRONG_EXIT):
        if b['spoken'].startswith('"'):
            lines.append((b['id'], b['spoken'].strip('"'), None))
    for k, (bid, quote, _) in enumerate(lines):
        right = TRUTH[k]
        lines[k] = (bid, quote, right if k < 2 else ('kip' if right == 'marisol' else 'marisol'))
    return lines


def test_untagged_lines_take_turns_from_the_lines_the_text_decides_even_against_the_plan():
    got = said(WRONG_EXIT, MOTHER_AND_SON, lines=wrong_exit_plan())
    assert [who for _, who in got] == TRUTH, [(w[:20], who, truth) for (w, who), truth in zip(got, TRUTH)]


def test_a_line_said_to_someone_by_name_or_title_is_not_theirs():
    text = '"There are a thousand cows, Mom."\n\n"This one was wearing a hat, Kip."'
    plan = dict(lines=[(bid_of(text, 'cows'), 'There are a thousand cows, Mom.', 'marisol'),
                       (bid_of(text, 'hat'), 'This one was wearing a hat, Kip.', 'kip')])
    assert [who for _, who in said(text, MOTHER_AND_SON, **plan)] == ['kip', 'marisol']


def test_a_child_says_dads_map_and_your_father_is_said_to_the_child():
    text = ('Marisol and Kip drove on.\n\n"Mom."\n\n"Fine."\n\nHe pulled over by a field.\n\n'
            '"Okay. There\'s a map in the glove box. Dad\'s map."\n\n"Your father never once used that map."')
    plan = dict(lines=[(bid_of(text, 'glove'), "Okay. There's a map in the glove box. Dad's map.", 'marisol'),
                       (bid_of(text, 'never once'), 'Your father never once used that map.', 'kip')])
    assert [who for _, who in said(text, MOTHER_AND_SON, **plan)] == ['kip', 'marisol', 'kip', 'marisol']


def test_narration_between_lines_ends_the_turns_and_the_plan_stands_where_the_text_says_nothing():
    text = 'Kip looked out at the dark field.\n\n"We should go home now."'
    for planned in ('kip', 'marisol'):
        plan = dict(lines=[(bid_of(text, 'home'), 'We should go home now.', planned)])
        assert said(text, MOTHER_AND_SON, **plan) == [('We should go home now.', planned)]


def test_screenplay_labels_still_name_their_speakers():
    text = 'MARISOL: We passed it.\n\nKIP: We did not pass it.'
    plan = dict(lines=[(bid_of(text, 'passed'), 'We passed it.', 'kip')])
    parts = speech.voice_parts(script.build(ingest.read(text), 'story'), plan_of(MOTHER_AND_SON, **plan), 'af_heart')
    assert [(seg.speaker, seg.said) for todo in parts.values() for seg, _, _ in todo['parts']] == [
        ('marisol', 'We passed it.'), ('kip', 'We did not pass it.')]


# ------------------------------------------------------------------ the bubbles follow the voices
def test_every_bubble_is_on_the_person_whose_voice_says_it(tmp_path):
    two = [('marisol', 'adult', 'look', 'no'), ('kip', 'adult', 'look', 'no')]
    plan = wrong_exit_plan()
    prod = staged(tmp_path, WRONG_EXIT, [shot(bid, quote[:12], 'two_shot', two, place='car', lines=[(quote, who)])
                                         for bid, quote, who in plan], cast=MOTHER_AND_SON)
    saved = json.loads((tmp_path / 'project.json').read_text())['plan_v3']
    beats = [{'id': bid, 'spoken': b['spoken'], 'section': b.get('section')} for bid, b in prod.by_id.items()]
    voiced, _, _ = speech.quote_speakers(beats, saved)
    voice = {(bid, a): who for bid, spans in voiced.items() for a, _, who in spans}
    rows = prod.storybook.bubbled
    assert len(rows) >= 15
    for row in rows:
        start = max(a for (bid, a) in voice if bid == row['beat'] and a <= row['start'])
        assert voice[(row['beat'], start)] == row['speaker'], row
    first = {}
    for row in rows:
        first.setdefault(row['beat'], row['speaker'])
    lines = [b['id'] for b in beats_of(WRONG_EXIT) if b['spoken'].startswith('"')]
    assert [first.get(bid) for bid in lines[:8]] == TRUTH[:8]


# ------------------------------------------------------------------ the QA net
def test_qa_fails_a_bubble_that_another_voice_says_and_names_both():
    from kinodraw.speakers import mismatches
    said_ = {'b005': [[0, 1, 'marisol'], [1, 32, 'marisol']], 'b006': [[0, 20, 'marisol']],
             'b007': [[0, 5, None]]}
    rows = [{'beat': 'b005', 'start': 1, 'end': 32, 'speaker': 'kip', 'text': 'There are a thousand cows, Mom.'},
            {'beat': 'b006', 'start': 1, 'end': 20, 'speaker': 'marisol', 'text': 'That one had a hat.'},
            {'beat': 'b007', 'start': 1, 'end': 4, 'speaker': 'kip', 'text': 'Hm.'},
            {'beat': 'b009', 'start': 1, 'end': 4, 'speaker': 'kip', 'text': 'Ok.'},
            {'beat': 'b006', 'start': 1, 'end': 20, 'speaker': 'theo', 'role': 'marisol', 'text': 'That one had a hat.'}]
    problems = mismatches(rows, said_, {'kip': 'Kip', 'marisol': 'Marisol'})
    assert problems == [
        'The speech bubble "There are a thousand cows, Mom." (beat b005) is Kip\'s line, but Marisol says it.',
        'The speech bubble "Hm." (beat b007) is Kip\'s line, but the narrator says it.',
        'The speech bubble "Ok." (beat b009) is Kip\'s line, but nobody says it.']
    assert mismatches(rows[1:2], said_) == []


def test_the_voices_record_who_reads_each_part_for_the_qa():
    from kinodraw.speakers import voiced
    board = script.build(ingest.read('"We passed it," Marisol said.'), 'story')
    parts = speech.voice_parts(board, plan_of(MOTHER_AND_SON), 'af_heart')
    (bid,) = [b['id'] for b in board['beats'] if '"' in b['spoken']['en']]
    assert voiced(parts)[bid] == [[0, 14, 'marisol'], [14, 29, None]]


# ------------------------------------------------------------------ a narrator who is one of the cast
COACH = [{'id': 'ben', 'name': 'Coach Ben', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male'},
         {'id': 'ava', 'name': 'Ava', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female'}]
PANCAKES = ('Morning, runners! Coach Ben here, with my favorite pre-race breakfast. My helper today is Ava.\n\n'
            '"Hi!"\n\n1. Peel the bananas and mash them in a bowl with a fork.\n\n"This part is my favorite."\n\n'
            '2. Crack in the eggs and stir.\n\n"Can we have them before practice every day?"\n\n'
            'Only on race days, Ava. Only on race days.')


def test_a_first_person_narrator_reads_in_their_own_voice_and_a_bare_quote_is_the_other_persons():
    plan = dict(lines=[(bid_of(PANCAKES, 'favorite.'), 'This part is my favorite.', 'ben')],
                talk=[(bid_of(PANCAKES, 'Hi!'), 'ben')])
    parts = speech.voice_parts(script.build(ingest.read(PANCAKES), 'story'), plan_of(COACH, **plan), 'af_heart')
    said_by = [(seg.speaker, voice, seg.said) for todo in parts.values() for seg, voice, _ in todo['parts']]
    assert {s for s, _, _ in said_by} == {'ben', 'ava'}                     # nobody is left to the default narrator
    assert [s for s, _, said in said_by if said in ('Hi!', 'This part is my favorite.',
                                                    'Can we have them before practice every day?')] == ['ava'] * 3
    voices = {s: v for s, v, _ in said_by}
    assert voices['ben'].startswith('am_') and voices['ava'].startswith('af_')
    assert speech.cast_of(parts) == voices


def test_a_line_i_say_is_the_narrators():
    text = 'Coach Ben here, and my helper is Ava.\n\n"Ready?" I asked.\n\n"Ready!"'
    talk = [(bid_of(text, 'Ready?'), 'ava')]                            # the plan's talker is wrong
    assert said(text, COACH, talk=talk) == [('Ready?', 'ben'), ('Ready!', 'ava')]

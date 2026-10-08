"""What KinoDraw says and captions for any script format: screenplay labels, stage directions, emoji, Markdown,
spoken respellings, per-speaker voices and interruptions (numbers: test_script_numbers.py; title and end cards:
test_script_titles.py)."""
import json
import re
import wave

import pytest

from kinodraw import ingest, numbers, script, speech, voice
from kinodraw.engine import timeline

SCREENPLAY = """It's Friday night at the Alvarez house, and there is exactly one remote.

[Living room. JULES is sprawled on the couch holding the remote. WALT sits in the armchair.]

JULES: Okay, I'm picking. Something with a twist ending.

WALT: Every movie has a twist ending now.

DANA: [from the kitchen] Nobody picks anything until I get there!

WALT: Give me that. [He takes the remote.] I'll show you a real classic.

DANA: (quietly) Dad, turn it off—

JULES: No way. Turn it up.

They never did pick a movie."""


def board_of(text, story='story', title=None):
    return script.build(ingest.read(text, title=title), story)


def texts(board, key):
    return [b[key][board['lang']] for b in board['beats']]


# ------------------------------------------------------------------ 1. spoken vs caption text
def test_screenplay_labels_and_directions_are_neither_said_nor_captioned():
    board = board_of(SCREENPLAY)
    labels = speech.screenplay_labels(texts(board, 'display'))
    assert labels == {'jules', 'walt', 'dana'}
    said = [speech.said_text(t, 'en', labels)[0] for t in texts(board, 'spoken')]
    shown = [speech.caption_text(t, labels) for t in texts(board, 'display')]
    for text in said + shown:
        assert not re.search(r'\b(?:JULES|WALT|DANA)\s*:', text), text
        assert not re.search(r'[\[\]()]', text), text
    assert said[1] == '' and shown[1] == ''                  # a line that is only a direction says nothing
    assert "Give me that. I'll show you a real classic." in shown
    assert 'Nobody picks anything until I get there!' in said
    assert 'Dad, turn it off—' in said


def test_screenplay_lines_pasted_without_blank_lines_stay_separate_lines():
    board = board_of('WALT: Hello there.\nDANA: Hi, Dad.\n[She sits.]\nWALT: Popcorn?')
    assert texts(board, 'display') == ['WALT: Hello there.', 'DANA: Hi, Dad.', '[She sits.]', 'WALT: Popcorn?']


@pytest.mark.parametrize('text', ['Note: the oven is hot.', 'Then a voice: the Eagle had landed.',
                                  'Step 1: preheat the oven.', 'Warning: sharp knife.'])
def test_a_colon_after_ordinary_words_is_not_a_speaker(text):
    board = board_of(text + '\n\nAnd then we ate.')
    labels = speech.screenplay_labels(texts(board, 'display'))
    assert labels == set()
    assert speech.said_text(board['beats'][0]['spoken']['en'], 'en', labels)[0].split()[0] == \
        board['beats'][0]['spoken']['en'].split()[0]


def test_mixed_case_labels_count_when_they_recur():
    board = board_of('Jules: Hi.\n\nWalt: Hello.\n\nJules: Bye.')
    assert speech.screenplay_labels(texts(board, 'display')) == {'jules'}


def test_emoji_and_markdown_marks_are_neither_said_nor_captioned():
    board = board_of('Fresh rolls every Saturday at 7 a.m. 🔥 Just $3.50 each! "good morning sunshine 🐢"\n\n'
                     '> Come *early* and bring a friend ✨.')
    spoken, display = texts(board, 'spoken'), texts(board, 'display')
    said = [speech.said_text(t, 'en')[0] for t in spoken]
    shown = [speech.caption_text(t) for t in display]
    for text in said + shown:
        assert not speech.EMOJI.search(text) and not re.search(r'[*>`#]', text), text
    assert shown[0] == 'Fresh rolls every Saturday at 7 a.m. Just $3.50 each! "good morning sunshine"'
    assert said[1] == 'Come early and bring a friend.'


# ------------------------------------------------------------------ 2. speech respelling
@pytest.mark.parametrize('text,said', [
    ('Mr. Smith met Dr. Lee on Main St. today.', 'Mister Smith met Doctor Lee on Main Street today.'),
    ('St. Louis vs. Oak Dr. and so on, etc.', 'Saint Louis versus Oak Drive and so on, et cetera'),
    ('Every Saturday at 7 a.m. 🔥 Just $3.50 each.', 'Every Saturday at seven AM. Just three fifty each.'),
    ('At 4:17 p.m. Eastern time, it landed.', 'At four seventeen PM Eastern time, it landed.'),
])
def test_abbreviations_are_spelled_out_for_the_voice_only(text, said):
    assert speech.said_text(numbers.normalize(text, 'en').spoken, 'en')[0] == said
    assert speech.caption_text(text) == speech.EMOJI.sub('', text).replace('  ', ' ')


def test_chinese_passes_through_unharmed():
    text = '奶奶今年七十二岁，刚学会用手机。\n\n"小宇啊，奶奶包了三十个饺子。你什么时候回来？"\n\n他马上按住按钮：'
    board = board_of(text)
    for b in board['beats']:
        spoken = b['spoken']['zh']
        segs = speech.segments(spoken, 'zh')
        assert ''.join(s.said for s in segs) == spoken.strip('"“”')
        assert speech.caption_text(b['display']['zh']) == b['display']['zh']


# ------------------------------------------------------------------ 3. per-speaker voices
def test_each_screenplay_speaker_has_their_own_voice_and_the_narrator_keeps_the_project_voice():
    board = board_of(SCREENPLAY)
    plan = {'cast': [
        {'id': 'jules', 'name': 'Jules', 'kind': 'human', 'species': 'human', 'sex': 'female', 'age': 'young'},
        {'id': 'walt', 'name': 'Walt', 'kind': 'human', 'species': 'human', 'sex': 'male', 'age': 'old'},
        {'id': 'dana', 'name': 'Dana', 'kind': 'human', 'species': 'human', 'sex': 'female', 'age': 'adult'}],
        'scenes': []}
    parts = speech.voice_parts(board, plan, 'af_heart')
    who = {}
    for todo in parts.values():
        for seg, name, _ in todo['parts']:
            who.setdefault(seg.speaker, set()).add(name)
    assert who[None] == {'af_heart'}
    assert {k: v for k, v in who.items() if k} == {'jules': {'af_jessica'}, 'walt': {'am_onyx'},
                                                    'dana': {'af_kore'}}
    # Without a cast every label still gets its own voice, never the narrator's.
    loose = speech.voice_parts(board, None, 'af_heart')
    names = {seg.speaker: name for todo in loose.values() for seg, name, _ in todo['parts']}
    assert len({names['label:jules'], names['label:walt'], names['label:dana']}) == 3
    assert 'af_heart' not in {names['label:jules'], names['label:walt'], names['label:dana']}


def test_label_words_tell_sex_and_age():
    assert speech.guess_person('GRANDPA') == ('male', 'elder')
    assert speech.guess_person('Little Girl') == ('female', 'young')
    voices = speech.cast_voices([('a', 'male', 'elder'), ('b', 'female', 'young'), ('c', None, 'adult'),
                                 ('d', None, 'adult')], 'am_michael', 'en')
    assert len({v for v, _ in voices.values()}) == 4 and 'am_michael' not in {v for v, _ in voices.values()}


def test_a_prose_quote_is_said_by_the_person_the_reader_bubbles():
    board = board_of('Theo went downstairs, where his mother was half-asleep in front of the TV.\n\n'
                     '"Mine\'s broken," he said. "It\'s just a bunch of random stuff."\n\n'
                     '"It\'s not broken," she said. "It writes itself as you go."')
    plan = {'cast': [{'id': 'theo', 'name': 'Theo', 'kind': 'human', 'species': 'human', 'sex': 'male',
                      'age': 'young'},
                     {'id': 'theos_mother', 'name': "Theo's mother", 'kind': 'human', 'species': 'human',
                      'sex': 'female', 'age': 'adult'}], 'scenes': []}
    parts = speech.voice_parts(board, plan, 'af_heart')
    lines = [(seg.speaker, name, seg.said) for todo in parts.values() for seg, name, _ in todo['parts']]
    assert ('theo', 'am_puck', "Mine's broken,") in lines
    assert (None, 'af_heart', 'he said.') in lines
    assert ('theos_mother', 'af_kore', "It's not broken,") in lines
    assert (None, 'af_heart', 'she said.') in lines
    assert lines[0][:2] == (None, 'af_heart')


def test_a_quote_span_inside_prose_can_carry_any_speaker():
    spoken = '"Mine\'s broken," he said.'
    segs = speech.segments(spoken, 'en', speakers=[(1, 15, 'theo')])
    assert [(s.speaker, s.said) for s in segs] == [('theo', "Mine's broken,"), (None, 'he said.')]
    assert spoken[segs[0].index[0]] == 'M' and spoken[segs[1].index[0]] == 'h'


def test_speak_joins_each_speakers_voice_and_times_every_spoken_character(tmp_path):
    spoken = 'JULES: Okay. [She points.] Look!'
    segs = speech.segments(spoken, 'en', {'jules'})
    assert [s.said for s in segs] == ['Okay. Look!']
    parts = [(speech.Segment(0, 5, None, 'Hello there.', list(range(12))), 'af_heart', 1.),
             (speech.Segment(5, 10, 'x', 'Good night.', list(range(12, 23))), 'am_onyx', 1.)]
    clip = voice.speak('Hello there.Good night.', parts, 'en', tmp_path)
    assert len(clip.char_times) == len('Hello there.Good night.')
    assert clip.char_times == sorted(clip.char_times) and clip.char_times[12] > clip.char_times[0]
    assert clip.speakers == (None, 'x')
    meta = json.loads(next(p for p in tmp_path.glob('*.json') if 'parts' in p.read_text()).read_text())
    assert [p['voice'] for p in meta['parts']] == ['af_heart', 'am_onyx']
    with wave.open(str(clip.wav)) as w:
        assert abs(w.getnframes() / w.getframerate() - clip.duration) < .01


# ------------------------------------------------------------------ 4. interruptions
def _clips(board, cut_beat=None, speakers=None):
    clips = timeline.synthetic_clips(board, 'en')
    for bid, who in (speakers or {}).items():
        clips[bid].update(speakers=list(who), cut_off=bid == cut_beat, duration=clips[bid]['speech'] - voice.GAP)
    return clips


def test_a_line_that_breaks_off_is_overlapped_by_the_next_speaker():
    board = board_of('DANA: Dad, turn it off—\n\nJULES: No way. Turn it up.')
    clips = _clips(board, 'b001', {'b001': ('dana', 'dana'), 'b002': ('jules', 'jules')})
    tl = timeline.layout(board, 'en', clips)
    a, b = tl['beats']['b001'], tl['beats']['b002']
    assert b['start'] == pytest.approx(a['start'] + clips['b001']['duration'] - timeline.OVERLAP, abs=1e-3)
    assert a['end'] == b['start']
    assert all(c['end'] <= b['start'] + 1e-6 for c in tl['captions'] if c['start'] < b['start'])
    # The same speaker carrying on, or a line that does not break off, leaves the usual gap.
    same = timeline.layout(board, 'en', _clips(board, 'b001', {'b001': ('dana', 'dana'), 'b002': ('dana', 'dana')}))
    plain = timeline.layout(board, 'en', _clips(board, None, {'b001': ('dana', 'dana'), 'b002': ('jules', 'jules')}))
    for tl2 in (same, plain):
        assert tl2['beats']['b002']['start'] == pytest.approx(tl2['beats']['b001']['end'])
        assert tl2['beats']['b002']['start'] >= tl2['beats']['b001']['speech_end'] - 1e-6


def test_cut_off_is_a_dash_at_the_end_of_the_line():
    assert speech.segments('DANA: Dad, turn it off—', 'en', {'dana'})[0].cut_off
    assert speech.segments('DANA: Dad, turn it off--', 'en', {'dana'})[0].cut_off
    assert not speech.segments('DANA: Dad—turn it off.', 'en', {'dana'})[0].cut_off


# ------------------------------------------------------------------ captions on the timeline
def test_timeline_captions_have_no_labels_directions_or_emoji_and_keep_word_times():
    board = board_of(SCREENPLAY + '\n\nWALT: Popcorn 🍿 anyone?')
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    text = ' '.join(c['text'] for c in tl['captions'])
    assert not re.search(r'JULES|WALT|DANA|\[|\]|\(|\)|🍿', text), text
    assert 'Okay, I\'m picking.' in text and 'Popcorn anyone?' in text
    assert not any(c['start'] < tl['beats']['b002']['end'] and c['end'] > tl['beats']['b002']['start']
                   for c in tl['captions'])                    # the direction-only line has no caption
    for c in tl['captions']:
        assert len(c['words']) == len(c['text'].split())

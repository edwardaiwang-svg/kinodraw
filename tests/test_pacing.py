"""Timing between and inside sentences: written pauses become silence of their length, counts keep a calm pace,
sentences and dramatic beats get room (speech.pace, voice.paced, pipeline._hold_pauses)."""
import numpy as np
import pytest

from kinodraw import pipeline, speech, voice


def _stop(text, word):
    """The stop speech.pace puts before the first ``word`` of ``text`` (None if there is none)."""
    pos = text.index(word) if word != 'END' else len(text)
    return next(((g, a, s) for p, g, a, s in speech.pace(text) if p == pos), None)


@pytest.mark.parametrize('note, seconds', [
    ('[pause 3 seconds]', 3.), ('[pause three seconds]', 3.), ('(pause)', 3.),
    ('[3 s pause]', 3.), ('(pause for 4 seconds)', 4.), ('(hold for four)', 4.), ('(beat)', 1.2),
    ('[long pause]', 5.), ('[10-second silence]', 10.)])
def test_a_written_pause_asks_for_its_length(note, seconds):
    assert speech.pause_seconds(note) == seconds


@pytest.mark.parametrize('note', ['(laughs)', '[She points.]', '(hold)', '[Show: a pause button]'])
def test_other_directions_are_no_pause(note):
    assert speech.pause_seconds(note) is None


def test_a_pause_inside_a_line_is_silence_never_said_or_shown():
    text = 'Breathe in. (pause for 4 seconds) And out.'
    assert [s.said for s in speech.segments(text, 'en')] == ['Breathe in. And out.']
    assert speech.caption_text(text) == 'Breathe in. And out.'
    assert _stop(text, 'And') == (4., None, 0.)


def test_sentences_get_a_natural_gap_and_counts_a_calm_pace():
    assert _stop('Find a comfortable seat. Let your hands rest.', 'Let')[0] == speech.SENTENCE_GAP
    count = 'Breathe in through your nose... two... three... four.'
    for word, anchor in (('two', 'nose'), ('three', 'two'), ('four', 'three')):
        gap, at, step = _stop(count, word)
        assert count[at:].startswith(anchor) and step == speech.COUNT_STEP
    assert _stop('"The north is just... on the bottom."', 'on')[0] == speech.TRAIL_GAP


def test_a_line_that_trails_or_breaks_off_leaves_a_dramatic_beat_and_a_spoken_hold_waits():
    assert _stop('One more time, on your own. In...', 'END')[0] == speech.BEAT_GAP
    assert _stop('And then the lights went out—', 'END')[0] == speech.BEAT_GAP
    assert _stop('Inhale for four. Hold for four. Exhale for six.', 'Exhale')[0] == 4.
    assert _stop('Inhale for four. Hold for four. Exhale for six.', 'END')[0] == 6.
    assert speech.pace('We waited for four hours. Then we left.') == [(26, speech.SENTENCE_GAP, None, 0.)]


def test_a_beat_that_is_only_a_pause_holds_for_it():
    board = {'lang': 'en', 'beats': [
        {'id': 'b1', 'spoken': {'en': 'Close your eyes.'}, 'display': {'en': 'Close your eyes.'}},
        {'id': 'b2', 'spoken': {'en': '[pause four seconds]'}, 'display': {'en': '[pause 4 seconds]'}}]}
    parts = speech.voice_parts(board, None, 'af_heart')
    assert parts['b2'] == {'parts': [], 'hold': 4., 'pause': 4.}


def _tone(seconds):
    return .3 * np.sin(2 * np.pi * 220 * np.arange(round(seconds * voice.SR)) / voice.SR).astype(np.float32)


def _quiet_runs(wav):
    q = voice._quiet_frames(voice._read_wav(wav))
    runs, k = [], 0
    while k < len(q):
        j = k
        while j < len(q) and q[j] == q[k]:
            j += 1
        if q[k]:
            runs.append((j - k) / 100)
        k = j
    return runs


def test_paced_widens_a_short_sentence_gap_and_moves_the_later_words(tmp_path):
    text = 'One two. Three four.'
    audio = np.concatenate([_tone(.6), np.zeros(round(.1 * voice.SR), np.float32), _tone(.6)])
    voice._write_wav(tmp_path / 'raw.wav', audio)
    times = [round(.6 * i / 8, 3) if i < 9 else round(.7 + .6 * (i - 9) / 11, 3) for i in range(len(text))]
    clip = voice.paced(voice.Clip(tmp_path / 'raw.wav', 1.3, times), text, speech.pace(text), tmp_path)
    assert abs(clip.duration - (1.3 + speech.SENTENCE_GAP - .1)) < .02
    assert max(_quiet_runs(clip.wav)) == pytest.approx(speech.SENTENCE_GAP, abs=.02)
    assert clip.char_times[9] == pytest.approx(.7 + speech.SENTENCE_GAP - .1, abs=.01)
    assert clip.char_times[:9] == times[:9]


def test_a_written_pause_beat_leaves_exactly_its_length_of_voice_free_time(tmp_path):
    before = np.concatenate([_tone(1.), np.zeros(round(.28 * voice.SR), np.float32)])
    after = np.concatenate([np.zeros(round(.08 * voice.SR), np.float32), _tone(1.)])
    voice._write_wav(tmp_path / 'a.wav', before)
    voice._write_wav(tmp_path / 'c.wav', after)
    clips = {'b1': voice.Clip(tmp_path / 'a.wav', 1.28, [0.] * 5), 'b2': voice.silence(.2, 5, tmp_path),
             'b3': voice.Clip(tmp_path / 'c.wav', 1.08, [0.] * 5)}
    board = {'beats': [{'id': 'b1'}, {'id': 'b2'}, {'id': 'b3'}]}
    parts = {'b1': {'parts': [1]}, 'b2': {'parts': [], 'pause': 3.}, 'b3': {'parts': [1]}}
    pipeline._hold_pauses(board, parts, clips, tmp_path)
    voice_free = .28 + voice.GAP + clips['b2'].duration + voice.GAP + .08     # as the timeline lays them out
    assert voice_free == pytest.approx(3., abs=.01)


def test_an_ellipsis_is_one_clause_mark_so_each_count_is_timed_from_the_voice():
    from types import SimpleNamespace as T
    tokens = [('ɪ', 0.), ('n', .1), ('.', .2), ('.', .2), ('.', .2), (' ', .2), ('t', 1.), ('u', 1.1), ('.', 1.3),
              (' ', 1.3), ('θ', 2.), ('i', 2.1), ('.', 2.3)]
    text = 'In... two... three.'
    times = voice.align(text, [T(phoneme=p, start=s) for p, s in tokens], 'en')
    assert times[text.index('two')] == 1. and times[text.index('three')] == 2.


def test_a_scene_waiting_for_its_music_beat_keeps_the_old_scene_moving():
    """A pause that opens a scene: until the join lands on a beat the picture is the old scene still living, never
    a still of its last frame (the 27 guided-breathing freeze inside a pause)."""
    from PIL import Image
    from kinodraw.engine.hybrid import HybridProduction
    seen = []
    prod = HybridProduction.__new__(HybridProduction)
    spec = {'treatment': 'atmosphere', 'transition_in': 'match'}
    old = type('S', (), {'start': 0., 'end': 10., 'join': 0., 'join_length': .5, 'spec': spec, 'story': None,
                         'scientific': None, 'diagram': None, 'source_proof': False})()
    new = type('S', (), {'start': 10., 'end': 20., 'join': 11.5, 'join_length': .5, 'spec': spec, 'story': None,
                         'scientific': None, 'diagram': None, 'source_proof': False})()
    prod.whiteboard = type('W', (), {'vertical': True})()
    prod.spans, prod.starts, prod.size = [old, new], [0., 10.], (8, 8)
    prod.tl = {'end_card': {'start': 30.}}
    prod._frame = lambda span, t, quotes=True: seen.append((span, t)) or Image.new('RGB', (8, 8))
    prod._draw_anchor = lambda image, t: image
    for t in (10.5, 11.0, 11.6):
        prod._frame_at(t)
    assert (old, 10.5) in seen and (old, 11.0) in seen and (old, 11.6) in seen


POEM = """The river does not hurry.
It has never once been late.

It carries leaves it did not ask for,
and sets them down
in places they did not know to want.

Nothing here is lost.
It is only on its way.
"""


def test_verse_rests_at_the_end_of_each_stanza_and_prose_does_not():
    from kinodraw import ingest, script
    assert ingest.is_verse(POEM)
    assert not ingest.is_verse('Preheat the oven.\nMix the flour.\n\nPour the batter.\nBake it for twenty minutes.\n')
    assert not ingest.is_verse('A long paragraph of prose that someone wrapped by hand at about seventy\n'
                               'characters, as email clients and old editors still do for their users.\n\n'
                               'And a second one, wrapped the same way, with a sentence that runs on\n'
                               'across its line break before it finally ends somewhere down here.\n')
    board = script.build(ingest.read(POEM), 'story')
    ends = [b['display']['en'] for b in board['beats'] if b.get('stanza_end')]
    assert ends == ['The river does not hurry. It has never once been late.',
                    'It carries leaves it did not ask for, and sets them down in places they did not know to want.',
                    'Nothing here is lost. It is only on its way.']
    assert not any(b.get('stanza_end') for b in script.build(ingest.read(POEM.replace('\n\n', '\n\n\n').replace(
        'for,\nand sets them down\nin', 'for, and sets them down in').replace('lost.\nIt', 'lost. It')
        .replace('hurry.\nIt', 'hurry. It')), 'story')['beats'])

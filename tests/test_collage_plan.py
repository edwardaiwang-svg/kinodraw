"""Collage shots: sentence times follow the narration, and sentences group into stages with the right entrances."""
from pathlib import Path

from doodlestudio import ingest, script
from doodlestudio.engine import timeline
from doodlestudio.engine.collage import plan

FIX = Path(__file__).parent / 'fixtures'


def _note(i, span, scene, role='none', energy=1):
    return {'i': i, 'span': list(span), 'role': role, 'scene': scene, 'energy': energy, 'emphasis': ''}


def _board():
    board = script.build(ingest.read(FIX / 'promo_tiny.md'), 'promo')
    scenes = ['chat_pileup', 'brand_reveal', 'threshold', 'brand_endcard']
    for beat, scene in zip(board['beats'], scenes * 3):
        text = beat['display']['en']
        cut = text.find('. ') + 1 or len(text)
        beat['direction'] = [_note(0, (0, cut), scene, energy=2 if scene == 'brand_reveal' else 1)]
        if cut < len(text):
            follow = 'feature_chips' if scene == 'brand_reveal' else scene
            beat['direction'].append(_note(1, (cut + 1, len(text)), follow))
    return board


def test_sentences_follow_the_voice_and_cover_the_video():
    board = _board()
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    said = plan.sentences(board, tl, 'en')
    assert [s.start for s in said] == sorted(s.start for s in said)
    assert said[-1].end == tl['duration'] and all(s.end >= s.start for s in said)
    first = board['beats'][0]
    assert said[0].text == first['display']['en'][:len(said[0].text)] and said[0].start >= tl['beats'][first['id']]['start']


def test_stages_group_sentences_and_loud_scenes_enter_with_a_tear():
    board = _board()
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    shots = plan.stages(plan.sentences(board, tl, 'en'), tl)
    kinds = [s.kind for s in shots]
    assert kinds[0] == 'chat' and shots[0].transition == 'none' and shots[0].start == 0
    brand = next(s for s in shots if s.kind == 'brand')
    assert brand.transition == 'torn' and any(x.scene == 'feature_chips' for x in brand.sentences)  # chips join the stage
    assert shots[-1].end == tl['duration'] and all(a.end == b.start for a, b in zip(shots, shots[1:]))


def test_a_beat_without_annotations_is_one_sticker_sentence():
    board = script.build(ingest.read(FIX / 'tiny.md'))
    tl = timeline.layout(board, board['lang'], timeline.synthetic_clips(board, board['lang']))
    said = plan.sentences(board, tl, board['lang'])
    assert len(said) == len(board['beats']) and {s.scene for s in said} == {'sticker_row'}

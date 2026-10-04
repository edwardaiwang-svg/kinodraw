"""Rules every rendered video must keep, whatever the director planned.

Built on synthetic (reading-rate) timing, so no voice model is needed.
"""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.engine import auto_scenes as auto
from kinodraw.engine import ink, render
from kinodraw.engine import timeline as tl
from kinodraw.engine.board import COL, STALE

FIX = Path(__file__).parent / 'fixtures'


@pytest.fixture(scope='module', params=['printing_press.md', 'photosynthesis.txt', 'sleep_zh.md'])
def prod(request, tmp_path_factory):
    board = script.build(ingest.read(FIX / request.param))
    lang = board['lang']
    board = RulesDirector(lang).direct(board)
    project = tmp_path_factory.mktemp('project')
    clips = tl.synthetic_clips(board, lang)
    timing = tl.layout(board, lang, clips, render.pacing(board, lang, clips, project))    # as the pipeline does
    return render.Production(board, timing, lang, project)


def board_frames(prod):
    for i in range(int(prod.tl['duration'] * render.FPS)):
        t = i / render.FPS
        if prod.mode_at(t)[0] == 'board':
            yield t


def test_camera_never_jumps_or_goes_back(prod):
    cam = prod.camera
    prev = None
    for t in board_frames(prod):
        L = cam.at(t)
        if prev is not None and t - prev[0] < 1.5 / render.FPS:
            assert abs(L - prev[1]) < 200, f'camera jumps {prev[1] / COL:.2f} -> {L / COL:.2f} columns at {t:.2f}s'
        prev = (t, L)
    backwards = [(round(t0, 2), a / COL, b / COL) for t0, a, b, kind in cam._segments() if kind == 'pan' and b < a]
    assert not backwards, backwards


def test_every_stroke_is_drawn_on_screen(prod):
    for e in prod.els:
        if e.fixed or not e.hand:
            continue
        for t in (e.start + .01, e.end - .01):
            if prod.mode_at(t)[0] != 'board':
                continue
            L = prod.camera.at(t)
            assert L - 2 <= e.x and e.x + e.w <= L + render.SIZE[0] + 2, \
                f'{e.group} drawn off screen at {t:.2f}s (x {e.x:.0f}..{e.x + e.w:.0f}, view {L:.0f})'


def test_drawings_start_near_their_words(prod):
    for e in prod.els:
        if e.fixed or e.essential or e.after is not None:
            continue
        first = min(x.start for x in prod.els if x.group == e.group)
        if e.start == first:
            assert e.start - e.trigger <= STALE + 1e-6, f'{e.group} starts {e.start - e.trigger:.1f}s after its words'


def test_takeaway_notes_are_finished_before_they_fly(prod):
    for tr in prod.tl['transitions']:
        note = prod.notes[tr['section']]
        for e in note['els']:
            if not e.skipped:
                assert e.end <= tr['hold_end'] - render.NOTE_READ + 1e-6, (tr['section'], e.end, tr['hold_end'])
        assert all(not e.skipped for e in note['els'] if e.essential)


def test_check_marks_avoid_card_text(prod):
    checks = [e for e in prod.ctx.elements if e.fixed and e.hand and e.drawing.size[0] == e.drawing.size[1]
              and e.drawing.size[0] in (150, 120, 96, 90, 72, 60)]
    assert len(checks) == len(prod.tl['transitions'])
    text = [b for card in prod.cards.values() for b in map(auto.ink_bbox, card['els']) if b]
    for c in checks:
        x0, y0, x1, y1 = c.bbox()
        assert not any(x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1 for b in text), c.bbox()


def test_end_card_is_written_in_time(prod):
    end = prod.tl['end_card']
    card = [e for e in prod.els if e.group == 'endcard']
    assert card and all(isinstance(e.drawing, (ink.TextDrawing, ink.PathDrawing)) for e in card)
    assert all(end['start'] <= e.start and e.end <= end['end'] - .4 for e in card)


def test_numbers_are_written_stroke_by_stroke():
    td = ink.TextDrawing(['in 1455 the press'], 'en', 76)
    f = ink.hand_font('en', 76)
    pad = 6

    def arrivals(a, b):
        x0, x1 = int(pad + f.getlength('in 1455 the press'[:a])), int(pad + f.getlength('in 1455 the press'[:b]))
        region = td.arrival[:, x0:x1][td.alpha[:, x0:x1] > 64]
        return region[np.isfinite(region)]
    word, digits, after = arrivals(0, 2), arrivals(3, 7), arrivals(8, 17)
    assert digits.min() > word.max(), 'the number appears before the words in front of it'
    assert digits.max() < after.min(), 'the number is finished after the words behind it'
    assert digits.max() - digits.min() > .15 * td.duration, 'the number appears all at once'


def test_the_drawing_hand_is_a_hand_without_a_forearm():
    """A viewer asked to lose "that little thin arm when it's scribbling": the hand fades out at the wrist. With the
    nib in the middle of the frame, nothing of it (or of its shadow) reaches an edge of the frame."""
    hand = ink.Hand()
    frame = Image.new('RGBA', render.SIZE, (255, 255, 255, 255))
    hand.paste(frame, (render.SIZE[0] / 2, render.SIZE[1] / 2))
    px = np.asarray(frame.convert('RGB'))
    for name, edge in (('bottom', px[-1]), ('right', px[:, -1]), ('top', px[0]), ('left', px[:, 0])):
        assert (edge == 255).all(), f'the hand runs off the {name} of the frame: an arm, not a hand'
    ys, xs = np.nonzero(np.asarray(hand.img.getchannel('A')) > 8)
    reach = np.hypot(xs - hand.tip[0], ys - hand.tip[1]).max()
    assert reach < 560, f'something is drawn {reach:.0f} px from the nib: a forearm, not a hand'


def test_unlabelled_timeline_runs_the_whole_card(tmp_path):
    board = script.build(ingest.read(FIX / 'printing_press.md'))
    beat = next(b for b in board['beats'] if b['kind'] == 'narration')
    beat['visuals'] = [{'id': 'tl1', 'type': 'lanes', 'title': {'en': 'Timeline'}, 'lanes': [{'label': {'en': ''},
                        'events': [{'pos': 0, 'display': {'en': '1450'}, 'label': {'en': 'Gutenberg'}},
                                   {'pos': 1, 'display': {'en': '1517'}, 'label': {'en': 'Luther'}}]}]}]
    timing = tl.layout(board, 'en', tl.synthetic_clips(board, 'en'))
    prod = render.Production(board, timing, 'en', tmp_path)
    page = [e for e in prod.ctx.elements if e.group == 'tl1']
    band = next(e for e in page if e.w > 1500 and e.h > 200)     # the lane's card
    arrow = next(e for e in page if e.w > 1000 and e.h == 44)     # the time line
    assert arrow.x - band.x < 60, (band.x, arrow.x)
    assert arrow.x + arrow.w > band.x + band.w - 60


# ------------------------------------------------ nothing is written before it is said
def _beat(prod, beat_id):
    return next(b for b in prod.ep['beats'] if b['id'] == beat_id)


def test_takeaway_notes_are_written_as_they_are_said(prod):
    lang = prod.lang
    prefix = script.take_text('', lang)
    for tr in prod.tl['transitions']:
        beat = _beat(prod, tr['take_beat'])
        sticky, label, head = prod.notes[tr['section']]['els'][:3]
        spoken = beat['spoken'][lang]
        said = prod.ctx.time_of(beat, {lang: spoken[len(prefix):len(prefix) + 24]})
        assert spoken.startswith(prefix) and said > prod.tl['beats'][beat['id']]['start']
        assert head.trigger >= said - 1e-6 and head.start >= said - 1e-6, (tr['section'], head.start, said)
        assert head.start - said <= STALE, (tr['section'], head.start, said)           # and not far behind the words
        assert label.trigger >= prod.tl['beats'][beat['id']]['start'] - 1e-6          # "Key takeaway" is said first
        assert sticky.end <= label.start + 1e-6                                        # the note is down before


def test_section_title_cards_are_written_while_they_are_said(prod):
    for ch in (c for c in prod.ep['chapters'] if c['kind'] == 'section'):
        opener = next(b for b in prod.ep['beats'] if b['chapter'] == ch['id'])
        assert opener['kind'] == 'opener'
        info = prod.tl['beats'][opener['id']]
        card = [e for e in prod.els if e.group == f"opener:{ch['id']}"]
        assert card and info['start'] <= min(e.start for e in card) < info['speech_end'], ch['id']


def test_timeline_dates_are_written_when_they_are_said(tmp_path):
    board = script.build(ingest.read(FIX / 'bicycle.md'))
    board = RulesDirector('en').direct(board)
    timing = tl.layout(board, 'en', tl.synthetic_clips(board, 'en'))
    prod = render.Production(board, timing, 'en', tmp_path)
    owner = next(b for b in board['beats'] for v in b['visuals'] if v['type'] == 'lanes')
    lanes = next(v for v in owner['visuals'] if v['type'] == 'lanes')
    for k, ev in enumerate(lanes['lanes'][0]['events']):
        said = prod.ctx.time_of(owner, ev['trigger'])
        parts = prod.ctx.registry[lanes['id']][k]
        assert all(not e.skipped for e in parts), ev['display']
        assert min(e.start for e in parts) >= said - 1e-6, (ev['display'], said)
    assert not any(pan for pan in prod.camera._segments() if pan[3] == 'pan' and pan[2] < pan[1])


def test_pacing_lets_the_hand_finish_instead_of_skipping(tmp_path):
    board = script.build(ingest.read(FIX / 'printing_press.md'))
    board = RulesDirector('en').direct(board)
    clips = tl.synthetic_clips(board, 'en')
    rushed = render.Production(board, tl.layout(board, 'en', clips), 'en', tmp_path)
    pauses = render.pacing(board, 'en', clips, tmp_path)
    paced = render.Production(board, tl.layout(board, 'en', clips, pauses), 'en', tmp_path)
    skipped = lambda p: {e.group for e in p.ctx.elements if e.skipped and e.beat}     # noqa: E731
    assert pauses and all(0 < s <= render.PAUSE_MAX for s in pauses.values())
    assert len(skipped(paced)) < max(1, len(skipped(rushed))), (skipped(rushed), skipped(paced))
    assert not skipped(paced), skipped(paced)


class _Stub:
    """A drawing that only has a size and a length."""
    def __init__(self, seconds, size=(200, 200)):
        self.duration, self.size = seconds, size


def test_a_picture_queued_behind_another_keeps_up_with_its_words():
    """A stranger's first video drew "sunlight hits the tiny molecules" as sun, label, molecule, label at natural
    speed with nothing else due for 14 s: the molecule's label started 5.8 s after its word."""
    from kinodraw.engine.board import KEEP_UP, Camera, Element, Scheduler
    els = [Element(_Stub(2.28), 100 + 220 * k, 300, 10.0, group='cluster') for k in range(2)]
    els = [x for e in els for x in (e, Element(_Stub(.85, (200, 40)), e.x, 520, 10.0, group='cluster'))]
    later = Element(_Stub(1.0), 900, 300, 24.0, group='next')            # the next picture is 14 s away
    Scheduler(Camera()).run(els + [later], [(0.0, 0.0, 'cut')])
    lag = [e.start - e.trigger for e in els]
    assert max(lag) <= KEEP_UP + .5, lag                                 # within the 2x speed limit
    assert all(e.rate <= 2.0 for e in els)
    assert els[2].start - els[2].trigger <= KEEP_UP, lag                 # the second picture itself is in time


SKY = '''# Why the Sky Is Blue

Look up on a clear afternoon and the sky is a deep, bright blue. But sunlight itself looks white. So where does the blue come from?

## Sunlight is a mix of colors

White sunlight is really every color of the rainbow traveling together. A prism splits it apart into red, orange, yellow, green, blue and violet. Each color is a wave, and blue waves are much shorter than red ones.

## Air scatters short waves

When sunlight hits the tiny molecules of nitrogen and oxygen in the air, the short blue waves bounce off in every direction. Red and yellow light mostly passes straight through. That scattered blue light reaches your eyes from all over the sky, so the whole sky glows blue.

## Sunsets turn red

At sunset, the light travels through much more air to reach you. Almost all the blue is scattered away before it arrives, and the reds and oranges are what is left. That is why evenings glow orange and pink.
'''


def test_takeaway_notes_keep_their_face_and_pictures(tmp_path):
    """With the built-in voice (faster than reading rate) every takeaway note of a stranger's first video lost the
    narrator's face and the section's pictures beside it ("skipped 4 visual(s) ... margins:s1, note:s1:3")."""
    board = RulesDirector('en').direct(script.build(ingest.read(SKY)))
    clips = tl.synthetic_clips(board, 'en')
    for c in clips.values():                         # the built-in voice reads at about 2.9 words a second
        c['speech'] *= .82
        c['char_times'] = [t * .82 for t in c['char_times']]
    timing = tl.layout(board, 'en', clips, render.pacing(board, 'en', clips, tmp_path))
    prod = render.Production(board, timing, 'en', tmp_path)
    dropped = sorted({e.group for e in prod.ctx.elements if e.skipped})
    assert not dropped, dropped
    for tr in timing['transitions']:
        note = prod.notes[tr['section']]
        assert len(note['els']) == 4 and all(e.end <= tr['hold_end'] - render.NOTE_READ + 1e-6 for e in note['els'])
        assert tr['hold_end'] - tr['speech_end'] <= render.PAUSE_MAX + tl.take_hold(
            next(b for b in board['beats'] if b['id'] == tr['take_beat']), 'en') + 1e-6

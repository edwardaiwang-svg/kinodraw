"""Boards for markup (engine/markup_boards.py): code typed in a monospace editor, typeset formulas, warning cards,
keycaps, the step indicator; board text keeps its symbols attached; the hand leaves the words it wrote; the QA
probe fails clipped or overlapping text (qa/text_layout.py)."""
import json

import pytest
from PIL import Image

from kinodraw import ingest, script
from kinodraw.director.v3.adapter import adapt
from kinodraw.director.v3.rules import from_rules
from kinodraw.director.v3.validate import validate
from kinodraw.engine import board as wb_board, ink, markup_boards as mb, process_diagrams as pd, render, timeline
from kinodraw.engine.bold import MotionElement, MotionScene, Palette
from kinodraw.qa import text_layout

SCRIPT = """# Money and code

Say you put $1,000 in a savings account. The formula looks like this:

A = P(1 + r)^n

Here's the same thing in Python:

```python
balance = 1000
for year in range(10):
    balance = balance * 1.05
    print(year + 1, round(balance, 2))
```

Every time through the loop, balance grows by 5%. Now set up two-step login.

1. On your laptop, open Harbor Mail.
2. Choose Security, then Two-step login.
3. Type that code into the box and click Verify.

That's it.

> ⚠️ Never share this code, not even with IT. We will never ask for it.

Tip: press Ctrl + Shift + N to open a private window first.
"""
CODE = 'balance = 1000\nfor year in range(10):\n    balance = balance * 1.05\n    print(year + 1, round(balance, 2))'


@pytest.mark.parametrize('written', ['5% of $1,000 is $50', '6-digit code', 'Ctrl+Shift+N', 'Ctrl + Shift + N',
                                     'A = P(1 + r)^n', 'balance * 1.05'])
def test_board_text_keeps_symbols_with_their_words(written):
    assert pd.typeset(written) == written


def test_code_types_in_monospace_with_its_indentation_readable_at_1080p():
    d = mb.CodeDrawing(CODE, 'python', 1656, 738, 1080, 2.)
    assert d.pitch >= .032 * 1080 and str(d.font.path).endswith('JetBrainsMono-Medium.ttf')
    assert d.font.getlength('i') == d.font.getlength('M')                     # monospace
    assert [indent for _, indent, _ in d.rows] == [0, 0, 4, 4]                 # the code's own indentation
    assert [text for _, _, text in d.rows] == [line.strip() for line in CODE.split('\n')]
    total = sum(len(t) for _, _, t in d.rows)
    assert 0 < d.shown(.5) < d.shown(1.5) < total == d.shown(2.)               # typed in over its duration
    img, pen, down = d.state(1.)
    assert img.size == d.size and pen is None and not down                     # typed: no hand on it


def test_a_formula_is_typeset_with_a_real_superscript():
    runs = []
    mb._boxes(mb.MATH_TOKEN.findall('A = P(1 + r)^n'), 100, runs)
    assert '^' not in [tok for tok, *_ in runs]
    n = next(r for r in runs if r[0] == 'n')
    assert n[2] < 100 and n[4] > 0                                           # smaller and raised
    assert str(n[1]).endswith('STIXTwoText-Italic.ttf')                      # a variable is italic
    assert str(next(r for r in runs if r[0] == '1')[1]).endswith('STIXTwoText-Regular.ttf')


def _production(tmp_path, edit=None):
    board = script.build(ingest.read(SCRIPT), story='story')
    plan = from_rules(board)
    if edit:
        edit(board, plan)
    plan, _ = validate(plan, board, {b['id']: [] for b in board['beats']})
    board, _ = adapt(plan, board)
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    return board, plan, timing, render.make_production(board, timing, 'en', tmp_path)


def _beat(board, words):
    return next(b for b in board['beats'] if words in b['display']['en'])


def test_code_formula_and_warning_get_their_own_boards_on_screen_while_said(tmp_path):
    board, plan, timing, prod = _production(tmp_path)
    wb = getattr(prod, 'whiteboard', prod)
    found = {}
    for words, kind in (('balance = 1000', mb.CodeDrawing), ('A = P', ink.RevealDrawing),
                        ('Never share', ink.RevealDrawing)):
        beat = _beat(board, words)
        el = next(e for e in wb.els if e.group == f"markup:{beat['id']}")
        assert isinstance(el.drawing, kind) and not el.skipped
        t = timing['beats'][beat['id']]['end'] - .05
        L = wb.camera.at(t)
        assert L - 1 <= el.x and el.x + el.w <= L + wb.size[0] + 1               # on screen as it is said
        found[words] = el.drawing.words
    assert found['balance = 1000'] == CODE and found['A = P'] == 'A = P(1 + r)^n'
    assert found['Never share'].startswith('⚠️ Never share this code, not even with IT.')
    code = next(e for e in wb.els if e.group == f"markup:{_beat(board, 'balance = 1000')['id']}")
    assert not code.hand


def test_numbered_steps_get_an_indicator_that_stays_while_they_are_read(tmp_path):
    board, plan, timing, prod = _production(tmp_path)
    wb = getattr(prod, 'whiteboard', prod)
    steps = [b for b in board['beats'] if (b.get('markup') or {}).get('kind') == 'step']
    for k, b in enumerate(steps, 1):
        info = timing['beats'][b['id']]
        assert wb.steps.current((info['start'] + info['end']) / 2) == (k, 3)
    assert wb.steps.current(timing['beats'][steps[0]['id']]['start'] - 1) is None
    t = (timing['beats'][steps[1]['id']]['start'] + timing['beats'][steps[1]['id']]['end']) / 2
    with_rail = prod.frame(t).crop((0, 300, 90, 780))
    wb.steps = None
    without = prod.frame(t).crop((0, 300, 90, 780))
    assert with_rail.tobytes() != without.tobytes()


def test_a_key_combo_on_a_board_is_drawn_as_keycaps(tmp_path):
    def edit(board, plan):
        bid = _beat(board, 'Ctrl + Shift')['id']
        scene = next(s for s in plan['scenes'] if bid in s['beat_ids'])
        scene.update(treatment='whiteboard', elements=[], boards=[{'layout': 'flow', 'items': [dict(
            id='keys', beat_id=bid, cue='Ctrl + Shift + N', kind='equation', ref='', to='', at='center',
            text='Ctrl + Shift + N', style='none')]}])
    board, plan, timing, prod = _production(tmp_path, edit)
    wb = getattr(prod, 'whiteboard', prod)
    keys = [e for e in wb.els if e.group.endswith(':keys')]
    assert keys and keys[0].drawing.words == 'Ctrl + Shift + N'


def test_a_markup_scene_planned_as_motion_is_drawn_on_the_whiteboard(tmp_path):
    def edit(board, plan):
        plan['style']['mode'] = 'hybrid'
        bid = _beat(board, 'balance = 1000')['id']
        for scene in plan['scenes']:
            if bid in scene['beat_ids']:
                scene.update(treatment='kinetic_type', text={'kind': 'kinetic', 'ref': bid})
    board, plan, timing, prod = _production(tmp_path, edit)
    bid = _beat(board, 'balance = 1000')['id']
    span = next(s for s in prod.spans if bid in s.spec['beat_ids'])
    assert span.source_proof and span.motion is None


class _Pen:
    """A drawing whose pen ends at (10, 10)."""
    size, duration = (40, 40), 1.

    def state(self, elapsed):
        return Image.new('RGBA', self.size), (10., 10.), True


def test_after_writing_the_hand_leaves_the_words_during_a_long_pause():
    a = wb_board.Element(_Pen(), 500, 400, 0., start=0.)
    b = wb_board.Element(_Pen(), 900, 400, 6., start=6.)
    pasted = []

    class Hand:
        img, tip, side = Image.new('RGBA', (200, 300)), (20, 20), 'right'

        def paste(self, frame, point, lifted=False):
            pasted.append(point)

    prod = render.Production.__new__(render.Production)
    prod.hand, prod.hand_els, prod.hand_starts, prod.size = Hand(), [a, b], [0., 6.], (1920, 1080)
    frame = Image.new('RGBA', (1920, 1080))
    prod._hand(frame, 3.5, 0)                       # mid pause, same page: nowhere near the words
    assert pasted == []
    prod._hand(frame, 1.1, 0)                       # sliding away right after writing
    assert pasted and (pasted[-1][0] > 510 or pasted[-1][1] > 410)


def test_the_probe_fails_clipped_and_overlapping_text():
    found, seen = [], set()
    text_layout._check(1., [((100, -40, 900, 60), 'Find the drip.'), ((300, 500, 900, 560), 'over 3,000 gallons'),
                            ((320, 510, 880, 570), 'a year'), ((1000, 900, 1200, 960), 'fine')],
                       (1920, 1080), found, seen)
    assert [(f['defect'], f['text']) for f in found] == [('text_clipped', 'Find the drip.'),
                                                         ('text_overlap', 'over 3,000 gallons')]


def test_a_long_kinetic_headline_over_pictures_is_measured_inside_the_frame():
    long = MotionElement(text='Find the drip. A faucet leaking one drop a second\nwastes over 3,000 gallons a year.\n'
                              'Fix it with a washer that costs\nunder five dollars at the store.', size=96,
                         width=1400, y=.03, preset='word_pop')
    scene = MotionScene([long], duration=4., composition='center', camera='static', transition_in='cut',
                        palette=Palette('#FFFFFF', '#222222', '#3366CC'), energy=3, motion_floor=.4)
    boxes = text_layout.motion_boxes(scene, 2., (1920, 1080))
    assert boxes and boxes[0][0][1] < 0                                        # the probe sees the clipping


def test_a_long_kinetic_headline_over_pictures_stays_inside_the_frame(tmp_path):
    long = ('Say you put $1,000 in a savings account and leave it there for ten long years without touching it once, '
            'and watch what the interest does to it while you sleep, work, travel and forget all about the bank.')

    def edit(board, plan):
        plan['style']['mode'] = 'hybrid'
        b = board['beats'][0]
        b['display']['en'] = b['spoken']['en'] = long
        scene = next(s for s in plan['scenes'] if b['id'] in s['beat_ids'])
        scene.update(treatment='kinetic_type', composition='center', text={'kind': 'kinetic', 'ref': b['id']},
                     elements=[{'kind': 'picture', 'ref': 'storm_cloud'}, {'kind': 'picture', 'ref': 'fl_house'}],
                     boards=[], shots=[])
        plan['_offer'] = b['id']

    board = script.build(ingest.read(SCRIPT), story='story')
    plan = from_rules(board)
    edit(board, plan)
    offer = {b['id']: [{'id': i, 'desc': i} for i in ('storm_cloud', 'fl_house')] for b in board['beats']}
    plan.pop('_offer')
    plan, _ = validate(plan, board, offer)
    board, _ = adapt(plan, board)
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    prod = render.make_production(board, timing, 'en', tmp_path)
    span = next(s for s in prod.spans if board['beats'][0]['id'] in s.spec['beat_ids'])
    assert span.motion is not None and any(e.kind == 'text' for e in span.motion.elements)
    clipped = [f for f in text_layout.problems(prod) if f['defect'] == 'text_clipped' and f['t'] < span.end]
    assert clipped == []

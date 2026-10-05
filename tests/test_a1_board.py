"""Quote-heavy boards: complete cards, safe text and short moving transitions."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.engine import ink, render, scenes, timeline
from kinodraw.engine.board import Camera, Layout, Scheduler

FIXTURE = Path(__file__).parent / 'fixtures' / 'a1_board_story.md'


@pytest.fixture(scope='module')
def prod(tmp_path_factory):
    board = RulesDirector('en').direct(script.build(ingest.read(FIXTURE)))
    clips = timeline.synthetic_clips(board, 'en')
    timing = timeline.layout(board, 'en', clips)
    return render.Production(board, timing, 'en', tmp_path_factory.mktemp('a1'))


def test_quote_cards_share_one_camera_stop(prod):
    cards = [v for b in prod.ep['beats'] for v in b['visuals'] if v['type'] == 'quote']
    assert len(cards) >= 8
    for card in cards:
        els = [e for e in prod.ctx.elements if e.group == card['id']]
        assert els and all(not e.skipped and e.start is not None for e in els), card['id']
        assert els[0].drawing.lines == ['“']
        assert els[0].start == pytest.approx(els[0].trigger), card['id']
        beat = next(b for b in prod.ep['beats'] if card in b['visuals'])
        assert els[0].start == pytest.approx(prod.ctx.time_of(beat, card.get('trigger'))), card['id']
        stops = {prod.camera.target_at(e.start) for e in els}
        assert len(stops) == 1, (card['id'], stops)
        assert all(a.end <= b.start for a, b in zip(els, els[1:]))
        read_at = els[-1].end + .01
        assert all(e.state(read_at)[0] is not None for e in els), card['id']
        assert prod.text_visible(els[0], read_at, prod.camera.at(read_at) + prod._drift(read_at)), card['id']
        if not card.get('who'):
            assert len(els) == 2


def test_quote_pan_finishes_before_the_mark():
    beat = {'id': 'b', 'spoken': {'en': 'A quiet voice can carry a brave idea.'}}
    ctx = scenes.Ctx({'beats': [beat]}, 'en', {'beats': {'b': {'start': 10.}}}, Layout())
    scenes.build_quote({'id': 'q', 'text': {'en': beat['spoken']['en']}}, beat, (1330, 100, 1180, 356), ctx)
    cam = Camera()
    Scheduler(cam).run(ctx.elements, [(0., 0., 'cut')])
    assert len({cam.target_at(e.start) for e in ctx.elements}) == 1
    assert ctx.elements[0].start == pytest.approx(ctx.elements[0].trigger)
    assert cam.at(ctx.elements[0].start) == cam.target_at(ctx.elements[0].start)


def test_backlogged_quotes_compress_instead_of_disappearing():
    beat = {'id': 'b', 'spoken': {'en': 'Every quiet question deserves a patient answer.'}}
    ctx = scenes.Ctx({'beats': [beat]}, 'en', {'beats': {'b': {'start': 5.}}}, Layout())
    for k in range(4):
        scenes.build_quote({'id': f'q{k}', 'text': {'en': beat['spoken']['en']}}, beat,
                           (100, 100, 1180, 356), ctx)
        for e in ctx.elements[-2:]:
            e.trigger += k * .5
            e.drawing.duration = 20.
    cam = Camera()
    Scheduler(cam).run(ctx.elements, [(0., 0., 'cut'), (8., 3840., 'cut')], stale=.01)
    assert all(e.start is not None and not e.skipped and e.end <= 8. for e in ctx.elements)
    assert any(e.rate > 4. for e in ctx.elements)


def test_long_words_and_default_slot_wrap():
    word = 'extraordinarilylongunbrokenword' * 6
    lines, size = ink.fit_text(word, 'en', 180, 4, 46)
    assert len(lines) > 1 and ''.join(lines) == word
    assert all(ink.text_width(line, 'en', size) <= 180 for line in lines)
    ctx = scenes.Ctx({}, 'en', {}, Layout())
    text = ctx.text('The quiet cub ' * 25, 46)
    assert len(text.lines) > 1 and text.size[0] <= ctx.layout.g.cell_w
    e = ctx.add(text, 1330, 100, 0.)
    assert e.x + e.w + 12 <= 1920 * .96


def test_visible_text_stays_safe_during_pans(prod, monkeypatch):
    images = {id(e.drawing.ink): e for e in prod.els if isinstance(e.drawing, ink.TextDrawing)}
    shown = []
    # Record actual compositing, including every pan frame; stroke masks do not change the bbox.
    monkeypatch.setattr(ink.TextDrawing, 'state', lambda self, elapsed: (self.ink, None, False))
    def paste(frame, image, x, y):
        if image is None or id(image) not in images:
            return
        e = images[id(image)]
        assert .04 * prod.size[0] <= x <= x + image.width <= .96 * prod.size[0], (t, e.group, x)
        assert .04 * prod.size[1] <= y <= y + image.height <= .96 * prod.size[1], (t, e.group, y)
        shown.append(e.group)
    monkeypatch.setattr(ink, 'paste', paste)
    for t in np.arange(0, prod.tl['duration'], 1 / render.FPS):
        prod.board_frame(t)
    assert len(shown) > 100
    assert {e.group for e in prod.els if e.atomic} <= set(shown)


def test_long_chrome_and_caption_stay_inside_the_safe_area(prod, monkeypatch):
    from copy import deepcopy
    ch = deepcopy(next(c for c in prod.ep['chapters'] if c['kind'] == 'section'))
    ch['title'] = {'en': 'A very long chapter title ' * 30}
    ch.pop('speaker', None)
    ch['source'] = {'en': 'A very long source name ' * 30}
    monkeypatch.setattr(prod, '_chapter_span', lambda t: (ch, 0., 10.))
    monkeypatch.setitem(prod.ep, 'footer', {'en': 'An unusually long footer ' * 30})
    monkeypatch.setattr(prod, 'cap_starts', [0.])
    monkeypatch.setitem(prod.tl, 'captions', [{'start': 0., 'end': 10., 'text': 'longunbrokenword' * 25}])
    boxes = []
    monkeypatch.setattr(ink, 'paste', lambda frame, image, x, y: boxes.append((x, y, x + image.width, y + image.height)))
    frame = Image.new('RGBA', prod.size)
    prod._chrome(frame, 1.)
    prod._caption(frame, 1.)
    assert len(boxes) == 4
    for x0, y0, x1, y1 in boxes:
        assert .04 * prod.size[0] <= x0 <= x1 <= .96 * prod.size[0]
        assert .04 * prod.size[1] <= y0 <= y1 <= .96 * prod.size[1]


def test_quotes_expire_at_board_changes(prod):
    quotes = [e for e in prod.ctx.elements if e.group.endswith('q')]
    assert quotes
    for e in quotes:
        changes = [t for t, _, _ in prod.cuts[e.stretch + 1:]]
        changes += [tr['hold_end'] for tr in prod.tl['transitions'] if tr['hold_end'] > e.trigger]
        if changes:
            clear = min(changes)
            assert e.hidden_after is not None and e.hidden_after <= clear
            assert e.state(clear)[0] is None


def test_transitions_and_catchup_silence_are_bounded(prod):
    assert render.PAUSE_MAX <= .3
    for tr in prod.tl['transitions']:
        assert tr['end'] - tr['speech_end'] <= .8 + 1e-6
    for bid, info in prod.tl['beats'].items():
        if 'prep' in info:
            assert info['start'] - info['prep'] <= .3 + 1e-6


def test_board_holds_keep_moving(prod):
    e = next(e for e in prod.els if isinstance(e.drawing, ink.TextDrawing) and e.group.endswith('q'))
    t = e.end + .15
    a, b = prod.board_frame(t), prod.board_frame(t + .2)
    assert np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)).mean() > .01


def test_camera_drift_moves_the_paper_through_a_sparse_hold(prod, monkeypatch):
    monkeypatch.setattr(prod, 'els', [])
    a = prod.view(64.43, 0., hand=False)
    b = prod.view(65.43, 0., hand=False)
    assert not np.array_equal(np.asarray(a), np.asarray(b))


def test_hand_travels_through_sparse_narration_gap(prod, monkeypatch):
    from types import SimpleNamespace
    prev = SimpleNamespace(start=0., end=1., x=200., y=300.)
    nxt = SimpleNamespace(start=3., end=4., x=800., y=300.)
    monkeypatch.setattr(prod, 'hand_els', [prev, nxt])
    monkeypatch.setattr(prod, 'hand_starts', [0., 3.])
    monkeypatch.setattr(prod, '_last_pen', lambda e: (0., 0.))
    monkeypatch.setattr(prod, '_first_pen', lambda e: (0., 0.))
    positions = []
    monkeypatch.setattr(prod.hand, 'paste', lambda frame, pos, lifted: positions.append(pos))
    frame = Image.new('RGBA', prod.size)
    prod._hand(frame, 1.5, 0.)
    prod._hand(frame, 2.5, 0.)
    assert len(positions) == 2 and positions[0] != positions[1]


def test_section_entry_keeps_the_agenda_text_whole(prod, monkeypatch):
    a, b, _, params = next(m for m in prod.modes if m[2] == 'zoom')
    agenda = Image.new('RGBA', prod.size, 'white')
    text = ink.TextDrawing(['Agenda lettering must stay whole'], 'en', 46)
    ink.paste(agenda, text.ink, 100, 100)
    blank = Image.new('RGBA', prod.size, 'white')
    monkeypatch.setattr(prod, 'view', lambda *args, **kwargs: agenda)
    monkeypatch.setattr(prod, 'board_frame', lambda t: blank)
    frame = np.asarray(prod._zoom(a + (b - a) * .4, params, a, b))
    shown = np.any(frame[:, :, :3] < 240, axis=2)
    original = np.any(np.asarray(agenda)[:, :, :3] < 240, axis=2)
    solid = np.any(np.asarray(agenda)[:, :, :3] < 128, axis=2)
    assert shown.any() and shown[solid].all() and not (shown & ~original).any()


def test_failed_builder_leaves_no_partial_visual(prod, monkeypatch):
    def fail(v, beat, box, ctx):
        e = ctx.add(ctx.text('Unfinished', 40), box[0], box[1], 0.)
        ctx.register(v['id'], 'all', [e])
        raise ValueError('broken visual')
    monkeypatch.setitem(scenes.SLOT_BUILDERS, 'quote', fail)
    p = render.Production(prod.ep, prod.tl, 'en', prod.project_dir)
    assert not any(e.group.endswith('q') for e in p.ctx.elements)
    assert not any(key.endswith('q') for key in p.ctx.registry)
    assert any('broken visual' in warning for warning in p.warnings)


def test_single_part_chrome_omits_part_label(prod, monkeypatch):
    from copy import deepcopy
    single = deepcopy(prod.ep)
    single['chapters'] = [{'id': 's1', 'kind': 'board', 'label': {'en': 'Part 1'}, 'title': {'en': 'Quiet questions'}}]
    single['beats'] = [b for b in single['beats'] if b['chapter'] == 's1' and b['kind'] == 'narration']
    timing = timeline.layout(single, 'en', timeline.synthetic_clips(single, 'en'))
    p = render.Production(single, timing, 'en', prod.project_dir)
    seen = []
    def chip(ch, lang, fonts):
        seen.append(render.chip_text(ch, lang))
        return Image.new('RGBA', (1, 1))
    monkeypatch.setattr(render, 'chip_image', chip)
    p._chrome(Image.new('RGBA', p.size), .5)
    assert seen == ['Quiet questions']

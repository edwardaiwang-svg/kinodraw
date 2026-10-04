"""Geometry regression and native portrait rendering."""
import random
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kinodraw import pipeline
from kinodraw.engine import auto_scenes as auto
from kinodraw.engine import board, ink, render, scenes, timeline
from kinodraw.engine.board import COL, COLS_ON_SCREEN, CELL_X0, CELL_W, ROW_Y, PAGE_BOX
from kinodraw.engine.geometry import LANDSCAPE, PORTRAIT


FIX = Path(__file__).parent / 'fixtures'


class _OldLayout:
    """Column-major slot allocator on the world strip (2 rows per column)."""

    def __init__(self):
        self.used = {}            # column -> set(rows)
        self.cursor = 0           # first column that may still take items
        self.page_start = 0

    def _free(self, col, row):
        return row not in self.used.get(col, set())

    def _take(self, col, row):
        self.used.setdefault(col, set()).add(row)

    def next_fresh_column(self):
        """First column after everything used so far."""
        return max([self.cursor] + [c + 1 for c, rows in self.used.items() if rows])

    def new_page(self):
        col = self.next_fresh_column()
        self.cursor = col
        self.page_start = col
        return col

    def slot(self, rows_needed=1):
        col = self.cursor
        while True:
            if rows_needed == 2:
                if self._free(col, 0) and self._free(col, 1):
                    self._take(col, 0), self._take(col, 1)
                    self.cursor = col
                    return self.cell_box(col, 0, rows=2), (col, col)
            else:
                for row in (0, 1):
                    if self._free(col, row):
                        self._take(col, row)
                        self.cursor = col
                        return self.cell_box(col, row), (col, col)
            col += 1

    def wide(self):
        col = self.cursor
        while True:
            for row in (0, 1):
                if self._free(col, row) and self._free(col + 1, row):
                    self._take(col, row), self._take(col + 1, row)
                    self.cursor = col
                    x0 = col * COL + CELL_X0
                    y0, y1 = ROW_Y[row]
                    return (x0, y0, COL + CELL_W, y1 - y0), (col, col + 1)
            col += 1

    def page(self):
        col = self.next_fresh_column()
        for c in range(col, col + COLS_ON_SCREEN):
            self._take(c, 0), self._take(c, 1)
        self.cursor = col + COLS_ON_SCREEN
        x, y, w, h = PAGE_BOX
        return (col * COL + x, y, w, h), (col, col + COLS_ON_SCREEN - 1)

    def reserve(self, col_from, col_to):
        for c in range(col_from, col_to + 1):
            self._take(c, 0), self._take(c, 1)
        self.cursor = col_to + 1

    @staticmethod
    def cell_box(col, row, rows=1):
        x0 = col * COL + CELL_X0
        y0 = ROW_Y[row][0]
        y1 = ROW_Y[row + rows - 1][1]
        return (x0, y0, CELL_W, y1 - y0)





def test_landscape_constants():
    assert (LANDSCAPE.size, LANDSCAPE.col, LANDSCAPE.cols_on_screen, LANDSCAPE.cell_x0, LANDSCAPE.cell_w,
            LANDSCAPE.rows, LANDSCAPE.page_box, LANDSCAPE.pan_seconds, LANDSCAPE.dwell_max, LANDSCAPE.opener_cols) == (
                (1920, 1080), 640, 3, 50, 540, ((84, 440), (466, 822)), (60, 84, 1800, 738), .9, 3.5, 2)
    assert (COL, COLS_ON_SCREEN, CELL_X0, CELL_W, ROW_Y, PAGE_BOX, board.PAN_SECONDS) == (
        640, 3, 50, 540, [(84, 440), (466, 822)], (60, 84, 1800, 738), .9)
    assert isinstance(ROW_Y, list)
    assert board.STALE == 3.0 and board.CUT_GRACE == 1.5 and board.SETTLE == .35
    assert render.SIZE == render.Production.size == LANDSCAPE.size
    assert all(getattr(LANDSCAPE, field) is None for field in
               ('title_band', 'board_band', 'caption_band', 'rail', 'bottom_ui', 'top_ui', 'text_safe'))
    assert LANDSCAPE.text_safe_ok((0, 0, 1920, 1080))
    assert not LANDSCAPE.text_safe_ok((-1, 0, 1920, 1080))
    with pytest.raises(FrozenInstanceError):
        PORTRAIT.col = 640


def test_landscape_scripted_layout():
    requests = [('new_page', ()), ('slot', ()), ('slot', ()), ('wide', ()), ('slot', (2,)), ('page', ()),
                ('reserve', (8, 9)), ('slot', ()), ('wide', ()), ('page', ())]
    expected = [0, ((50, 84, 540, 356), (0, 0)), ((50, 466, 540, 356), (0, 0)),
                ((690, 84, 1180, 356), (1, 2)), ((1970, 84, 540, 738), (3, 3)),
                ((2620, 84, 1800, 738), (4, 6)), None, ((6450, 84, 540, 356), (10, 10)),
                ((6450, 466, 1180, 356), (10, 11)), ((7740, 84, 1800, 738), (12, 14))]
    old, new = _OldLayout(), board.Layout(LANDSCAPE)
    for (name, args), result in zip(requests, expected):
        assert getattr(old, name)(*args) == result
        assert getattr(new, name)(*args) == result
        assert (new.used, new.cursor, new.page_start) == (old.used, old.cursor, old.page_start)


def test_landscape_random_layout_matches_original():
    rng = random.Random(1042026)
    for _ in range(20):
        old, new = _OldLayout(), board.Layout(LANDSCAPE)
        for _ in range(100):
            name = rng.choice(('new_page', 'slot', 'slot', 'wide', 'page', 'reserve'))
            if name == 'reserve':
                col = old.next_fresh_column() + rng.randrange(3)
                args = (col, col + rng.randrange(3))
            else:
                args = (rng.choice((1, 2)),) if name == 'slot' else ()
            assert getattr(new, name)(*args) == getattr(old, name)(*args)
            assert (new.used, new.cursor, new.page_start) == (old.used, old.cursor, old.page_start)


def test_portrait_layout():
    lay = board.Layout(PORTRAIT)
    assert lay.slot() == ((88, 590, 800, 315), (0, 0))
    assert lay.slot() == ((88, 935, 800, 315), (0, 0))
    assert lay.slot() == ((1168, 590, 800, 315), (1, 1))
    assert lay.wide() == ((1168, 935, 800, 315), (1, 1))
    assert lay.slot(rows_needed=2) == ((2248, 590, 800, 660), (2, 2))
    assert lay.page() == ((3328, 590, 800, 660), (3, 3))
    assert lay.cursor == 4
    a, b = board.Layout(PORTRAIT), board.Layout(PORTRAIT)
    assert [a.wide() for _ in range(8)] == [b.slot() for _ in range(8)]
    for request in ('slot', 'wide', 'page', 'slot', 'wide'):
        (x, y, w, h), (col, last) = getattr(lay, request)()
        assert col == last
        assert PORTRAIT.board_band[0] <= x - col * PORTRAIT.col
        assert x - col * PORTRAIT.col + w <= PORTRAIT.rail[0]
        assert PORTRAIT.board_band[1] <= y and y + h <= PORTRAIT.board_band[3]


def test_portrait_bands_and_text_safety():
    assert (PORTRAIT.size, PORTRAIT.col, PORTRAIT.cols_on_screen, PORTRAIT.opener_cols,
            PORTRAIT.pan_seconds, PORTRAIT.dwell_max) == ((1080, 1920), 1080, 1, 1, .9, 3.5)
    assert PORTRAIT.text_safe == ((88, 288, 992, 600), (88, 600, 888, 1250))
    for field in ('title_band', 'board_band', 'caption_band', 'rail', 'bottom_ui', 'top_ui'):
        x0, y0, x1, y1 = getattr(PORTRAIT, field)
        assert 0 <= x0 < x1 <= 1080 and 0 <= y0 < y1 <= 1920
    assert PORTRAIT.top_ui[3] <= PORTRAIT.title_band[1]
    assert PORTRAIT.title_band[3] < PORTRAIT.board_band[1]
    assert PORTRAIT.board_band[3] < PORTRAIT.caption_band[1]
    assert PORTRAIT.caption_band[3] <= PORTRAIT.bottom_ui[1]
    assert PORTRAIT.caption_band[2] <= PORTRAIT.rail[0]
    assert PORTRAIT.text_safe[1][2] <= PORTRAIT.rail[0]
    for box in ((88, 288, 992, 590), (88, 600, 888, 1250)):
        assert PORTRAIT.text_safe_ok(box)
    for box in ((88, 600, 900, 700), (80, 300, 500, 400), (100, 1200, 500, 1260)):
        assert not PORTRAIT.text_safe_ok(box)


@pytest.fixture(scope='module')
def productions(tmp_path_factory):
    project = tmp_path_factory.mktemp('portrait')
    ep = pipeline.new_project(FIX / 'tiny.md', project, lang='en')
    timing = timeline.layout(ep, 'en', timeline.synthetic_clips(ep, 'en'))
    return (render.Production(ep, timing, 'en', project, geometry=PORTRAIT),
            render.Production(ep, timing, 'en', project))


def _visible_at_rest(prod, t):
    if prod.mode_at(t)[0] in ('zoom', 'fly', 'pullback', 'stock'):
        return []
    L = prod.camera.at(t)
    if abs(L - prod.camera.target_at(t)) > 1e-6:
        return []
    return [e for e in prod.els if e.start <= t and not e.skipped and
            (e.hidden_after is None or t < e.hidden_after) and
            e.x < L + prod.size[0] and e.x + e.w > L]


def test_portrait_production_smoke(productions):
    portrait, landscape = productions
    assert portrait.vertical and portrait.size == (1080, 1920)
    assert portrait.scene_at(.3) == landscape.scene_at(.3) == 'title'
    assert portrait.scene_at(portrait.tl['duration'] - .5) == 'end'
    assert not portrait.warnings
    checked = 0
    for i in range(8):
        t = i * (portrait.tl['duration'] - .01) / 7
        assert portrait.frame(t).size == (1080, 1920)
        L = portrait.camera.at(t)
        for e in _visible_at_rest(portrait, t):
            if not isinstance(e.drawing, ink.TextDrawing):
                continue
            box = (e.x - L, e.y, e.x - L + e.w, e.y + e.h)
            if e.group == 'credit':
                # The specified closing credit uses the caption band, below the board text region.
                x0, y0, x1, y1 = PORTRAIT.caption_band
                assert x0 <= box[0] <= box[2] <= x1 and y0 <= box[1] <= box[3] <= y1
            else:
                assert PORTRAIT.text_safe_ok(box), (t, e.group, e.drawing.lines, box)
            checked += 1
    assert checked > 10


def test_portrait_elements_clear_frame_edges_at_rest(productions):
    prod = productions[0]
    # Check all resting board times cheaply; frame rendering is covered by the smoke test.
    for i in range(int(prod.tl['duration'] * render.FPS)):
        t = i / render.FPS
        L = prod.camera.at(t)
        for e in _visible_at_rest(prod, t):
            assert 0 <= e.x - L and e.x - L + e.w <= prod.size[0], (t, e.group, e.bbox(), L)
            assert 0 <= e.y and e.y + e.h <= prod.size[1], (t, e.group, e.bbox())


@pytest.mark.parametrize('n', range(1, 9))
def test_portrait_agenda_cards_and_contract(n, tmp_path):
    ep = pipeline.new_project(FIX / 'tiny.md', tmp_path, lang='en')
    ep = render.normalize(ep)
    sections = [c for c in ep['chapters'] if c['kind'] == 'section']
    chapters = [{**sections[k % len(sections)], 'id': f's{k}', 'number': k + 1,
                 'label': {'en': f'Part {k + 1}'}} for k in range(n)]
    beats = [b for b in ep['beats'] if b['chapter'] == 'agenda']
    timing = timeline.layout(ep, 'en', timeline.synthetic_clips(ep, 'en'))
    ctx = scenes.Ctx(ep, 'en', timing, board.Layout(PORTRAIT), tmp_path)
    cards = auto.SCENES['portrait']['agenda'](ctx, chapters, beats, 2160)
    assert len(cards) == n
    for k, ch in enumerate(chapters):
        card = cards[ch['id']]
        x, y, w, h = card['box']
        assert w == (800 if n <= 3 else 380)
        assert 288 <= y and y + h <= 1250
        assert h > 150                             # transitions need room for the pinned miniature
        beat = beats[min(k, len(beats) - 1)]
        expected = ctx.time_of(beat, None) + (.2 if k else 1.4)
        assert all(e.trigger == expected for e in card['els'])
        assert card['els'] and card['color'] == ink.SECTION_COLORS[ch['color']]
        for e in card['els']:
            assert x <= e.x and e.x + e.w <= x + w and y <= e.y and e.y + e.h <= y + h
    for e in ctx.elements:
        if isinstance(e.drawing, ink.TextDrawing):
            assert PORTRAIT.text_safe_ok((e.x - 2160, e.y, e.x - 2160 + e.w, e.y + e.h))


def test_scene_at_modes_and_marks(productions):
    prod = productions[0]
    assert set(auto.SCENES['landscape']) == set(auto.SCENES['portrait']) == {
        'title_board', 'agenda', 'section_opener', 'take_note', 'end_card', 'credit'}
    assert auto.SCENES['landscape']['title_board'] is auto.build_title_board
    for a, b, kind, params in prod.modes:
        if kind in ('pullback', 'fly', 'agenda', 'zoom'):
            assert prod.scene_at((a + b) / 2) == ('opener' if kind == 'zoom' else 'agenda')
    for x, kind in prod.scene_marks:
        assert kind in ('title', 'agenda', 'opener', 'take', 'end')
        assert x % PORTRAIT.col == 0


def test_portrait_stock_fallback_and_scene_kind(tmp_path):
    ep = pipeline.new_project(FIX / 'tiny.md', tmp_path, lang='en')
    intro = next(c['id'] for c in ep['chapters'] if c['kind'] == 'intro')
    outro = next(c['id'] for c in ep['chapters'] if c['kind'] == 'outro')
    for beat in ep['beats']:
        if beat['chapter'] in (intro, outro):
            beat['visuals'] = [{'type': 'stock', 'clip': 'custom_clip'}]
    timing = timeline.layout(ep, 'en', timeline.synthetic_clips(ep, 'en'))
    prod = render.Production(ep, timing, 'en', tmp_path, geometry=PORTRAIT)
    for cid, kind in ((intro, 'title'), (outro, 'end')):
        span = next(c for c in timing['chapters'] if c['id'] == cid)
        t = (span['start'] + span['end']) / 2
        assert prod.mode_at(t)[0] == 'stock'
        assert prod.scene_at(t) == kind
        assert prod.frame(t).size == PORTRAIT.size
        assert prod.frame(t).tobytes() == prod.skin.background(*PORTRAIT.size).tobytes()


def test_portrait_long_text_stays_within_its_box(tmp_path):
    ep = pipeline.new_project(FIX / 'tiny.md', tmp_path, lang='en')
    timing = timeline.layout(ep, 'en', timeline.synthetic_clips(ep, 'en'))
    ctx = scenes.Ctx(ep, 'en', timing, board.Layout(PORTRAIT), tmp_path)
    for text in ('A long title with many words ' * 20, 'VeryLongUnbrokenName' * 10):
        drawing = auto._portrait_text(ctx, text, 110, 800, lines=3, min_size=72)
        assert len(drawing.lines) <= 3 and drawing.size[0] <= 800
        assert drawing.lines[-1].endswith('…')

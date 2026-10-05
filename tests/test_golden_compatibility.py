"""Legacy short text keeps its geometry; safety fitting is for overflow."""
import pytest
from PIL import Image

from kinodraw.engine import ink, render, scenes, skin, timeline
from kinodraw.engine.board import Layout


@pytest.mark.parametrize('look', ['whiteboard', 'chalkboard', 'notebook', 'pixel_quest', 'mosaic'])
def test_short_chrome_and_captions_keep_legacy_positions(look, monkeypatch):
    p = object.__new__(render.Production)
    p.lang, p.skin = 'en', skin.for_look(look)
    p.ep = {'chapters': [{'kind': 'section'}, {'kind': 'section'}], 'footer': {'en': 'Short footer'}}
    p.ctx = scenes.Ctx(p.ep, 'en', {}, Layout(), skin=p.skin)
    ch = {'kind': 'section', 'label': {'en': 'Part 2'}, 'title': {'en': 'Short title'}, 'source': {'en': 'Short source'}}
    monkeypatch.setattr(p, '_chapter_span', lambda t: (ch, 0., 10.))
    p.cap_starts = [0.]
    p.tl = {'captions': [{'start': 0., 'end': 10., 'text': 'Short caption.'}]}
    boxes = []
    monkeypatch.setattr(ink, 'paste', lambda frame, img, x, y: boxes.append((x, y, img.width, img.height)))
    frame = Image.new('RGBA', p.size)
    p._chrome(frame, 1.)
    p._caption(frame, 1.)
    assert len(boxes) == 4
    assert boxes[0][:2] == (36, 22)
    assert boxes[1][0] + boxes[1][2] == 1880 and boxes[1][1] == 26
    assert boxes[2][:2] == (40, 1046)
    assert boxes[3][0] == (1920 - boxes[3][2]) / 2
    assert boxes[3][1] + boxes[3][3] == 1046


def test_interior_column_text_is_not_shifted_like_a_screen_edge():
    ctx = scenes.Ctx({}, 'zh', {}, Layout(), skin=skin.for_look('pixel_quest'))
    e = ctx.add(ctx.text('2', 160), 2634, 210, 0.)
    assert (e.x, e.y) == (2634, 210)


def test_chinese_title_keeps_closing_punctuation_on_its_line():
    fonts = skin.for_look('pixel_quest').fonts
    lines = ink.wrap_words('为什么我们需要睡觉？', 'zh', 118, 1150, fonts=fonts)
    assert lines == ['为什么我们需要睡觉？']


def test_sparse_hand_waits_for_finished_picture_settle(monkeypatch):
    from types import SimpleNamespace
    p = object.__new__(render.Production)
    p.hand_els = [SimpleNamespace(start=0., end=1., x=200., y=300.),
                  SimpleNamespace(start=3., end=4., x=800., y=300.)]
    p.hand_starts = [0., 3.]
    p._last_pen = p._first_pen = lambda e: (0., 0.)
    positions = []
    p.hand = SimpleNamespace(paste=lambda frame, pos, lifted: positions.append(pos))
    frame = Image.new('RGBA', p.size)
    p._hand(frame, 1.1, 0.)
    assert positions == []
    p._hand(frame, 1.5, 0.)
    p._hand(frame, 2.5, 0.)
    assert len(positions) == 2 and positions[0] != positions[1]


def test_drawing_and_short_settle_keep_paper_exact():
    from types import SimpleNamespace
    from kinodraw.engine.board import Camera
    p = object.__new__(render.Production)
    p.skin = skin.for_look('whiteboard')
    p.g = Layout().g
    p.camera = Camera()
    p.hand_starts, p.hand_els = [], []
    p.els = [SimpleNamespace(start=0., end=1., x=100., w=100., layer=0,
                            y=100., drawing=None, state=lambda t: (None, None, False))]
    expected = p.skin.background(*p.size).tobytes()
    for t in (.5, 1.1, 1.3):
        assert p._drift(t) == 0.
        assert p.view(t, 0., hand=False).tobytes() == expected
    assert abs(p._drift(1.300001)) < .001
    assert p.view(1.8, 0., hand=False).tobytes() != expected


def _board_production(tmp_path, look, visual_lists):
    chapters, beats = [], []
    for i, visuals in enumerate(visual_lists):
        cid = f'c{i}'
        chapters.append({'id': cid, 'kind': 'board', 'title': {'en': 'A board'}})
        for j, visual in enumerate(visuals):
            beats.append({'id': f'b{i}_{j}', 'chapter': cid, 'spoken': {'en': 'Read the board.'},
                          'display': {'en': 'Read the board.'}, 'visuals': [visual]})
    episode = {'title': {'en': 'Boards'}, 'look': look, 'chapters': chapters, 'beats': beats}
    clips = {b['id']: {'speech': 12., 'char_times': []} for b in beats}
    timing = timeline.layout(episode, 'en', clips, credit=False)
    return render.Production(episode, timing, 'en', tmp_path)


def _composited_text(prod, elements, at, monkeypatch):
    images = {id(e.drawing.ink) for e in elements}
    shown = set()
    paste = ink.paste
    def record(frame, image, x, y):
        if id(image) in images:
            shown.add(id(image))
        paste(frame, image, x, y)
    monkeypatch.setattr(ink, 'paste', record)
    frame = prod.frame(at)
    assert frame.getbbox()
    return shown, images


@pytest.mark.parametrize('look', ['whiteboard', 'pixel_quest', 'mosaic'])
def test_consecutive_board_chapters_composite_the_second_stat(tmp_path, look, monkeypatch):
    visuals = [[{'type': 'stat', 'id': f's{i}', 'value': {'en': str(i + 1)},
                 'label': {'en': 'A value'}}] for i in range(2)]
    prod = _board_production(tmp_path, look, visuals)
    assert prod.pages['c1'] == prod.g.col
    elements = [e for e in prod.els if e.group == 's1']
    assert len(elements) == 2 and all(e.start is not None and not e.skipped for e in elements)
    at = max(e.end for e in elements) + .1
    assert prod.camera.at(at) == prod.pages['c1']
    shown, images = _composited_text(prod, elements, at, monkeypatch)
    assert shown == images
    assert all(e.x - prod.camera.at(at) >= prod.size[0] * .04 for e in elements)


def test_allocated_page_uses_its_camera_origin(tmp_path, monkeypatch):
    visuals = [{'type': 'stat', 'id': 's', 'value': {'en': '1'}, 'label': {'en': 'A value'}},
               {'type': 'levels', 'id': 'levels', 'title': {'en': 'Two levels'},
                'footnote': {'en': 'Read both levels.'},
                'levels': [{'value': 1, 'display': {'en': '1'}, 'label': {'en': 'Low'}},
                           {'value': 2, 'display': {'en': '2'}, 'label': {'en': 'High'}}]},
               {'type': 'stat', 'id': 'after-page', 'value': {'en': '3'}, 'label': {'en': 'A value'}}]
    prod = _board_production(tmp_path, 'whiteboard', [visuals])
    elements = [e for e in prod.els if e.group == 'levels' and isinstance(e.drawing, ink.TextDrawing)]
    assert len(elements) == 6 and all(e.start is not None and not e.skipped for e in elements)
    at = max(e.end for e in elements) + .1
    assert prod.camera.at(at) == prod.g.col
    shown, images = _composited_text(prod, elements, at, monkeypatch)
    assert shown == images
    with monkeypatch.context() as later_patch:
        elements = [e for e in prod.els if e.group == 'after-page']
        assert len(elements) == 2 and all(e.start is not None and not e.skipped for e in elements)
        at = max(e.end for e in elements) + .1
        shown, images = _composited_text(prod, elements, at, later_patch)
        assert shown == images


@pytest.mark.parametrize('text,width', [('你好，', 100), ('你好。', 100), ('你好？', 100)])
def test_closing_punctuation_fits_padded_slot_and_is_composited(text, width, monkeypatch):
    from kinodraw.engine.board import Camera
    prod = object.__new__(render.Production)
    prod.skin, prod.g = skin.for_look('whiteboard'), Layout().g
    prod.ctx = scenes.Ctx({}, 'zh', {}, Layout(), skin=prod.skin)
    prod.camera = Camera()
    prod.hand_starts, prod.hand_els = [], []
    drawing = prod.ctx.text(text, 48, max_w=width)
    element = prod.ctx.add(drawing, 1740, 100, 0.)
    element.start = 0.
    prod.els = [element]
    shown = []
    paste = ink.paste
    def record(frame, image, x, y):
        if image is drawing.ink:
            shown.append((x, y))
        paste(frame, image, x, y)
    monkeypatch.setattr(ink, 'paste', record)
    prod.view(element.end + .1, 0., hand=False)
    assert shown == [(1740., 100)]
    assert drawing.size[0] <= width
    assert ''.join(drawing.lines) == text
    assert all(not line.startswith(('，', '。', '？')) for line in drawing.lines)

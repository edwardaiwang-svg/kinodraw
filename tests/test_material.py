"""Material skins retain the board's timing and coordinates, with their own visual language."""
import os
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np
import pytest
from PIL import Image

from kinodraw import pipeline, styles
from kinodraw.engine import ink, render as renderer, skin as skins, timeline
from kinodraw.engine.storyboard import DIALS

FIX = Path(__file__).parent / 'fixtures'
GOLDEN = Path(__file__).parent / 'golden'
MATERIALS = ('pixel_quest', 'mosaic')
CASES = [('whiteboard', 'en'), ('chalkboard', 'en'), ('notebook', 'en'),
         ('pixel_quest', 'en'), ('pixel_quest', 'zh'), ('mosaic', 'en'), ('mosaic', 'zh')]


def production(tmp_path, look, lang='en'):
    project = tmp_path / f'{look}-{lang}'
    board = pipeline.new_project(FIX / ('tiny.md' if lang == 'en' else 'sleep_zh.md'), project,
                                 direction={'look': look})
    tl = timeline.layout(board, lang, timeline.synthetic_clips(board, lang))
    return renderer.make_production(board, tl, lang, project), tl


def test_material_looks_are_offered_with_their_fonts_languages_and_cursor(tmp_path, monkeypatch, capsys):
    from kinodraw import cli, director
    from kinodraw.studio import server
    with pytest.raises(SystemExit):
        cli.main(['make', '--help'])
    offered = capsys.readouterr().out.split('--look {', 1)[1].split('}', 1)[0].split(',')
    studio = [e['value'] for e in server.state()['styles']]
    for look, face in (('pixel_quest', 'Silkscreen-Regular.ttf'), ('mosaic', 'Cinzel-Bold.ttf')):
        entry, skin = styles.get(look), skins.for_look(look)
        assert look in offered and look in DIALS['look'] and f'{look}/explain' in studio
        assert entry['languages'] == ['en', 'zh'] and entry['status'] == 'skin' and entry['render_ready']
        assert look in styles.ids(ready=True) and skin.textured
        assert not skin.plain and skin.material in ('pixel', 'tile')
        for kind in ('en_hand', 'en_caption', 'ui'):
            assert Path(getattr(skin.fonts, kind)[0]).name == face
        assert Path(skin.fonts.zh_hand[0]).name == 'DoodleKai-Medium.ttf'
        assert Path(skin.fonts.zh_caption[0]).name == 'NotoSansSC-Bold.otf'
    cursor, tip = skins.cursor_image()
    assert isinstance(cursor, Image.Image) and cursor.getpixel(tip)[3] == 255                  # the arrow's point
    assert cursor.getpixel((tip[0] - 1, tip[1] - 1))[3] == 0 and cursor.getpixel((tip[0] + 1, tip[1] - 1))[3] == 0
    assert cursor.getchannel('A').getextrema() == (0, 255)
    assert skins.for_look('pixel_quest').hand == 'cursor'
    assert skins.for_look('mosaic').hand == 'marker'
    monkeypatch.setattr(director, 'direct', lambda *a, **k: {'warnings': [], 'notes': [], 'usage': None})
    cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'cli'), '--look', 'mosaic'])
    assert pipeline.storyboard(tmp_path / 'cli')['look'] == 'mosaic'


@pytest.mark.parametrize('look,lang', CASES)
def test_material_and_existing_skin_golden_frames(tmp_path, look, lang):
    prod, tl = production(tmp_path, look, lang)
    frame = prod.frame(tl['captions'][3]['start'] + .1).convert('RGB').reduce(3)
    expected_path = GOLDEN / f'{look}_{lang}.png'
    if os.environ.get('KINODRAW_UPDATE_GOLDEN') == '1':
        GOLDEN.mkdir(exist_ok=True)
        frame.save(expected_path)
    assert expected_path.exists(), f'Missing {expected_path}; set KINODRAW_UPDATE_GOLDEN=1 to create it'
    expected = np.asarray(Image.open(expected_path).convert('RGB'))
    actual = np.asarray(frame)
    if expected.shape != actual.shape or not np.array_equal(expected, actual):
        path = tmp_path / f'{look}_{lang}_actual.png'
        frame.save(path)
        changed = np.count_nonzero(np.any(expected != actual, axis=-1)) if expected.shape == actual.shape else actual.shape
        pytest.fail(f'{look}/{lang}: {changed} differing pixels; actual frame: {path}')


@pytest.mark.parametrize('look', MATERIALS)
def test_material_frames_are_deterministic_at_three_times(tmp_path, look):
    prod, tl = production(tmp_path, look)
    times = (0.7, tl['captions'][3]['start'] + .1, tl['captions'][-1]['start'] + .1)
    first = [np.asarray(prod.frame(t).convert('RGB')).copy() for t in times]
    separate, _ = production(tmp_path / 'separate', look)
    second = [np.asarray(separate.frame(t).convert('RGB')) for t in reversed(times)]
    for a, b in zip(first, reversed(second)):
        assert np.array_equal(a, b), look


@pytest.mark.parametrize('look,margin', [('pixel_quest', 64), ('mosaic', 0)])
def test_material_grid_moves_with_the_board_during_a_pan(tmp_path, look, margin):
    prod, tl = production(tmp_path, look)
    t = tl['captions'][-1]['start'] + .1
    left = int((min(e.x for e in prod.els) + max(e.x + e.w for e in prod.els)) / 2 - 960)
    a = np.asarray(prod.view(t, left, hand=False).convert('RGB'))
    b = np.asarray(prod.view(t, left + 37, hand=False).convert('RGB'))
    assert np.array_equal(a[:, 37 + margin:1920 - margin], b[:, margin:1920 - 37 - margin]), look
    assert not np.array_equal(a, b), 'a world-anchored grid must visibly move'
    period = 3840 if look == 'pixel_quest' else 3836
    backdrop_a = np.asarray(prod.skin.background(x=period - 20))
    backdrop_b = np.asarray(prod.skin.background(x=period + 17))
    assert np.array_equal(backdrop_a[:, 37:], backdrop_b[:, :-37]), 'background remains seamless across its period'
    assert not np.array_equal(backdrop_a, backdrop_b), 'the background itself moves with the camera'


def _solid(size=(96, 96), color=(31, 111, 217, 255)):
    return Image.new('RGBA', size, color)


def _interiors(array, x, y, cell, inset=0):
    """Yield whole absolute cells, excluding clipped edge cells and optional grout."""
    h, w = array.shape[:2]
    for cy in range((-y) % cell, h - cell + 1, cell):
        for cx in range((-x) % cell, w - cell + 1, cell):
            yield array[cy + inset:cy + cell - inset, cx + inset:cx + cell - inset]


def test_pixel_cells_use_the_fixed_palette_and_absolute_coordinates():
    skin = skins.for_look('pixel_quest')
    yy, xx = np.mgrid[:96, :96]
    source = np.dstack([xx * 2, yy * 2, np.full_like(xx, 177), np.full_like(xx, 255)]).astype(np.uint8)
    a = np.asarray(skins.material_image(Image.fromarray(source, 'RGBA'), skin, 3, 5, .5))
    palette = {tuple(rgb) for rgb in skins.QUEST32}
    assert set(map(tuple, a[a[..., 3] > 0, :3])) <= palette
    assert set(np.unique(a[..., 3])) <= {0, 255}
    for block in _interiors(a, 3, 5, 8):
        assert np.all(block == block[0, 0]), 'one colour per world cell'
    shifted = np.asarray(skins.material_image(Image.fromarray(source, 'RGBA'), skin, 11, 13, .5))
    assert np.array_equal(a, shifted), 'pixel palette has no position-dependent jitter'
    moved = np.asarray(skins.material_image(Image.fromarray(source, 'RGBA'), skin, 4, 5, .5))
    assert not np.array_equal(a, moved), 'cell boundaries must follow world coordinates'


def test_mosaic_tiles_have_flat_interiors_and_darker_world_aligned_grout():
    skin = skins.for_look('mosaic')
    a = np.asarray(skins.material_image(_solid(), skin, 3, 5, .5))
    assert (a[14:84, 14:84, 3] == 255).all()
    for block in _interiors(a, 3, 5, 14, inset=2):
        assert np.all(block == block[0, 0])
    yy, xx = np.mgrid[:96, :96]
    grout = ((xx + 3) % 14 < 2) | ((yy + 5) % 14 < 2)
    assert a[grout, :3].mean() < a[~grout, :3].mean(), 'grout darkens the tile colour'
    b = np.asarray(skins.material_image(_solid(), skin, 17, 19, .5))
    # Jitter may change colour in each world cell; its grout geometry does not change.
    assert np.array_equal(a[..., 3], b[..., 3])
    assert b[grout, :3].mean() < b[~grout, :3].mean()


@pytest.mark.parametrize('look', MATERIALS)
def test_dressed_fills_and_static_art_use_the_material(look):
    skin = skins.for_look(look)
    square = [(0, 0), (111, 0), (111, 111), (0, 111), (0, 0)]
    drawing = skin.dress(ink.stroke_drawing((112, 112), [square],
                                          closed_fill=[(square, (31, 111, 217))]), 0, 0)
    assert isinstance(drawing, skins.MaterialDrawing)
    final = np.asarray(drawing.color)
    assert (final[28:84, 28:84, 3] == 255).all()
    if look == 'pixel_quest':
        assert set(map(tuple, final[final[..., 3] > 0, :3])) <= {tuple(c) for c in skins.QUEST32}
    else:
        assert not np.array_equal(final[28, 28, :3], final[32, 32, :3]), 'fill tiles retain grout'
    static = ink.StaticDrawing(_solid((112, 112)))
    dressed = skin.dress(static, 3, 5)
    expected = skins.material_image(_solid((112, 112)), skin, 3, 5, skin.margs['fill_cover'])
    assert np.array_equal(np.asarray(dressed.image), np.asarray(expected))


@pytest.mark.parametrize('look', MATERIALS)
def test_material_reveal_is_monotone_on_whole_cells_and_leaves_text_sharp(look):
    skin = skins.for_look(look)
    path = [(12, 20), (250, 20), (250, 170), (12, 170), (12, 20)]
    drawing = skin.dress(ink.stroke_drawing((270, 190), [path], width=9), 3, 5)
    alphas = [np.asarray(drawing.state(drawing.duration * fraction)[0].getchannel('A'))
              for fraction in (.2, .5, 1.)]
    assert all((before <= after).all() for before, after in zip(alphas, alphas[1:]))
    assert 0 < np.count_nonzero(alphas[0]) < np.count_nonzero(alphas[-1])
    cell = skin.margs['cell']
    for alpha in alphas:
        for block in _interiors(alpha, 3, 5, cell):
            assert np.all(block == block[0, 0]), 'reveal covers complete material cells'
    text = ink.TextDrawing(['Text 中文 42%'], 'en', 60, fonts=skin.fonts)
    before = np.asarray(text.ink).copy()
    skin.dress(text, 3, 5)
    assert np.array_equal(before, np.asarray(text.ink)), 'identity text stays sharp and unchanged'


@pytest.mark.parametrize('look', MATERIALS)
@pytest.mark.parametrize('lang,text', [('en', 'A complete caption about café — 42% of players finish the quest.'),
                                       ('zh', '完整字幕保留中文、café — 42% 和所有数字，不遗漏任何内容。')])
def test_material_captions_keep_complete_text_and_fallback_glyphs(look, lang, text):
    skin = skins.for_look(look)
    lines, size = skins.caption_layout(text, lang, skin)
    assert 1 <= len(lines) <= 2 and 36 <= size <= (56 if lang == 'en' else 60)
    assert ''.join(''.join(lines).split()) == ''.join(text.split())
    kind = f'{lang}_caption'
    if lang == 'zh':
        assert all(not line.startswith(tuple('，。！？；：、）」』”’%')) for line in lines[1:])
    for line in lines:
        runs = skins.glyph_runs(line, kind, size, skin.fonts)
        assert ''.join(ch for ch, font in runs) == line
        assert sum(font.getlength(ch) for ch, font in runs) <= 1640
        for ch, font in runs:
            assert ch.isspace() or ord(ch) in ink._cmap(font.path, font.index), (look, ch)
    panel = skin.caption_image(text, lang)
    assert panel.width <= 1720
    runs = skins.glyph_runs('café — 42%', 'en_caption', 70, skin.fonts)
    assert ''.join(ch for ch, font in runs) == 'café — 42%'
    for ch, font in runs:
        assert ch.isspace() or ord(ch) in ink._cmap(font.path, font.index), (look, ch)
    [(ch, fallback)] = skins.glyph_runs('中', 'en_caption', 56, skin.fonts)
    assert ch == '中' and fallback.path == skin.fonts.zh_caption[0]


@pytest.mark.parametrize('look', MATERIALS)
def test_material_frame_cost_under_250_ms(tmp_path, look):
    prod, tl = production(tmp_path, look)
    t = tl['captions'][3]['start'] + .1
    prod.frame(t)                         # populate reusable caption/background caches
    costs = []
    for frame_t in np.linspace(t, t + .9, 10):
        start = perf_counter()
        prod.frame(float(frame_t))
        costs.append((perf_counter() - start) * 1000)
    ms = median(costs)
    print(f'{look} frame median: {ms:.1f} ms')
    assert ms < 250, f'{look}: {ms:.1f} ms median over 10 frames'

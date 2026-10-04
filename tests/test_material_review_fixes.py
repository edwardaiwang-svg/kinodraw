"""Pixel Quest and Mosaic: Spanish captions, pinned notes, the takeaway pull-back, own pictures, vertical captions."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw import pipeline
from kinodraw.engine import ink, render as renderer, skin as skins, timeline, vertical

FIX = Path(__file__).parent / 'fixtures'
MATERIALS = ('pixel_quest', 'mosaic')
CASES = [(look, lang) for look in MATERIALS for lang in ('en', 'zh')]
ES = 'Los arqueólogos han encontrado vasijas de miel de más de 3,000 años que todavía se podían comer.'


def production(tmp_path, look, lang='en', aspect='16:9', script=None):
    project = tmp_path / f'{look}-{lang}-{aspect.replace(":", "-")}'
    script = script or ('tiny.md' if lang == 'en' else 'sleep_zh.md')
    episode = pipeline.new_project(FIX / script, project, direction={'look': look})
    tl = timeline.layout(episode, lang, timeline.synthetic_clips(episode, lang))
    return renderer.make_production(episode, tl, lang, project, aspect=aspect), tl


@pytest.fixture(scope='module', params=CASES, ids=lambda p: '-'.join(p))
def material(request, tmp_path_factory):
    look, lang = request.param
    return production(tmp_path_factory.mktemp('review-fixes'), look, lang)


@pytest.mark.parametrize('look', MATERIALS)
def test_spanish_material_captions_break_between_words(look):
    sk = skins.for_look(look)
    lines, size = skins.caption_layout(ES, 'es', sk)
    assert ' '.join(lines) == ES
    assert len(lines) <= 2
    assert all(skins._run_width(line, 'en_caption', size, sk.fonts) <= 1640 for line in lines)


@pytest.mark.parametrize('look', MATERIALS)
def test_spanish_material_cues_fit_two_lines(tmp_path, look):
    prod, tl = production(tmp_path, look, 'es', script='miel_es.md')
    for c in tl['captions']:
        lines, size = skins.caption_layout(c['text'], 'es', prod.skin)
        assert len(lines) <= 2, c['text']


def test_pinned_note_keeps_its_words(material):
    """The note pinned onto the agenda is the note itself, shrunk; it is not turned into cells a second time."""
    prod, _ = material
    pinned = 0
    for note in prod.notes.values():
        if 'mini' not in note:
            continue
        px, py = (int(round(v)) for v in note['pin_xy'])
        el = next(e for e in prod.ctx.elements
                  if isinstance(e.drawing, ink.StaticDrawing) and (e.x, e.y) == (px, py)
                  and e.drawing.image.size == note['mini'].size)
        assert np.array_equal(np.asarray(el.drawing.image), np.asarray(note['mini']))
        pinned += 1
    assert pinned


def test_pullback_starts_with_the_note_as_the_board_showed_it(material):
    """No one-frame change of the takeaway card when the pull-back starts (Pixel Quest's glow included)."""
    prod, _ = material
    checked = 0
    for a, b, kind, p in prod.modes:
        if kind != 'pullback':
            continue
        note = prod.notes[p['section']]
        tr = next(x for x in prod.tl['transitions'] if x['section'] == p['section'])
        board = np.asarray(prod.view(tr['hold_end'] - .01, note['x'], hand=False))
        first = np.asarray(prod._transition(a, 'pullback', p, a, b))
        nx, ny, _, _ = note['bbox']
        x, y = int(round(nx - note['x'])), int(round(ny))
        solid = np.asarray(note['image'].getchannel('A')) == 255
        h, w = solid.shape
        assert np.array_equal(first[y:y + h, x:x + w][solid], board[y:y + h, x:x + w][solid])
        checked += 1
    assert checked


@pytest.mark.parametrize('look', MATERIALS)
def test_own_raster_picture_takes_the_material(look):
    sk = skins.for_look(look)
    yy, xx = np.mgrid[0:96, 0:128]
    a = np.dstack([xx * 2, yy * 2, 255 - xx, np.full_like(xx, 255)]).astype(np.uint8)
    picture = Image.fromarray(a, 'RGBA')
    drawing = sk.dress(ink.RevealDrawing(picture), 0, 0)
    final = np.asarray(drawing.state(drawing.duration + 1)[0])
    expected = np.asarray(skins.material_image(picture, sk, 0, 0, sk.margs.get('fill_cover', .5)))
    assert np.array_equal(final, expected)
    assert not np.array_equal(final, a)
    if look == 'pixel_quest':
        colours = {tuple(c) for c in final[final[..., 3] > 0][:, :3]}
        assert colours <= {tuple(c) for c in skins.QUEST32}


@pytest.mark.parametrize('look', MATERIALS + ('whiteboard', 'chalkboard', 'notebook'))
def test_vertical_caption_letters_stand_out_from_the_letterbox(tmp_path, monkeypatch, look):
    """The 9:16 caption sits on the plain paper band: its letters, not only their outline, must read on it."""
    prod, _ = production(tmp_path, look, aspect='9:16')
    seen = []
    original = vertical.caption_image

    def record(text, lang, fonts, color, edge):
        seen.append(color)
        return original(text, lang, fonts, color, edge)

    monkeypatch.setattr(vertical, 'caption_image', record)
    assert prod.caption_image('On top they laid big flat stones.').width
    assert skins.contrast(seen[0], prod.skin.base[:3]) >= 4.5

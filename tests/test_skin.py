"""The style registry and the skin layer: every look is described once, and a skin reaches every mark, text, font,
paper, hand and caption the whiteboard renderer draws."""
import dataclasses
from pathlib import Path

import numpy as np
from PIL import Image

from kinodraw import pipeline, styles
from kinodraw.engine import ink, render as renderer, skin as skins, timeline
from kinodraw.engine.storyboard import DIALS

FIX = Path(__file__).parent / 'fixtures'
MOTIONS = ('calm', 'lively', 'showreel')


def test_every_look_is_described_once_with_what_the_app_needs():
    entries = styles.looks()
    assert [e['id'] for e in entries][0] == 'whiteboard' == DIALS['look'][0]        # the default comes first
    assert len({e['id'] for e in entries}) == len(entries)
    for e in entries:
        assert set(e['name']) == {'en', 'zh'} and all(e['name'].values()), e['id']
        assert e['status'] in styles.STATUSES and isinstance(e['render_ready'], bool)
        assert e['render_ready'] == (e['status'] != 'planned'), e['id']           # planned looks are never offered
        assert e['languages'] and set(e['languages']) <= {'en', 'zh'}
        assert e['stories'] and set(e['stories']) <= set(DIALS['story'])
        m = e['motion']
        assert {m['min'], m['max'], m['default']} <= set(MOTIONS)
        assert MOTIONS.index(m['min']) <= MOTIONS.index(m['default']) <= MOTIONS.index(m['max'])
        assert e['aspect'] == (['16:9', '9:16'] if e['render_ready'] else ['16:9'])
        low, high = e['length_s']
        assert 0 < low < high
        assert {'topic', 'audience', 'tone', 'structure'} <= set(e['fit'])
        assert (e['status'] == 'skin') == (e['renderer'] == 'whiteboard' and e['id'] != 'whiteboard')
    assert set(DIALS['look']) == set(styles.ids())
    assert styles.renderer('whiteboard') == 'whiteboard' and styles.renderer('collage') == 'collage'
    assert styles.renderer(None) == 'whiteboard'


def test_the_whiteboard_skin_is_the_renderer_unchanged():
    wb = skins.for_look('whiteboard')
    assert wb == skins.WHITEBOARD and wb.plain and wb.fonts == ink.FONTS
    assert skins.for_look(None) == skins.for_look('collage') == skins.WHITEBOARD   # not drawn by the whiteboard
    td = ink.TextDrawing(['Hello'], 'en', 60)
    before = td.ink
    assert wb.dress(td) is td and td.ink is before


class _Probe(skins.Skin):
    """A skin that records what passes through it and paints its paper one flat colour."""

    def background(self, width=1920, height=1080):
        return Image.new('RGBA', (width, height), (10, 120, 200, 255))

    def dress(self, drawing, x=0, y=0):
        _Probe.seen.append(type(drawing).__name__)
        return drawing


def test_a_skin_reaches_every_drawing_the_paper_the_fonts_the_hand_and_the_captions(tmp_path, monkeypatch):
    board = pipeline.new_project(FIX / 'tiny.md', tmp_path / 'p')
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    arimo = ink.Fonts(*([ink.EN_CAPTION] * 5))                                     # every text in a sans
    probe = _Probe(id='probe', fonts=arimo, hand='chalk', caption=(200, 0, 0), caption_edge=(0, 0, 0))
    _Probe.seen, hands, used = [], [], set()
    real_hand, real_font = ink.Hand, ink.font
    monkeypatch.setattr(ink, 'Hand', lambda tool='marker': hands.append(tool) or real_hand())
    monkeypatch.setattr(ink, 'font', lambda kind, size, fonts=ink.FONTS: used.add(fonts) or real_font(kind, size, fonts))
    monkeypatch.setattr(skins, 'for_look', lambda look: probe)
    prod = renderer.make_production(board, tl, 'en', tmp_path / 'p')
    assert prod.skin is probe and hands == ['chalk']
    assert len(_Probe.seen) == len(prod.ctx.elements) and {'TextDrawing', 'PathDrawing'} <= set(_Probe.seen)
    t = tl['captions'][3]['start'] + .1
    frame = np.asarray(prod.frame(t).convert('RGB'))
    assert used == {arimo}                                                         # writing, measuring, chrome
    assert tuple(frame[2, 2]) == (10, 120, 200)                                    # the skin's paper
    assert ((frame[880:1046, :, 0] > 180) & (frame[880:1046, :, 1] < 40)).sum() > 500   # red caption letters


def test_the_cli_offers_exactly_the_looks_that_render(capsys):
    import pytest
    from kinodraw import cli
    with pytest.raises(SystemExit):
        cli.main(['make', '--help'])
    offered = capsys.readouterr().out.split('--look {', 1)[1].split('}', 1)[0].split(',')
    assert offered == styles.ids(ready=True) and 'bold' not in offered       # planned looks are not offered


# ------------------------------------------------------------------ chalkboard and notebook
SKINS = ('chalkboard', 'notebook')


def test_the_chalkboard_and_notebook_looks_are_offered_in_both_languages():
    ready = styles.ids(ready=True)
    for look in SKINS:
        e = styles.get(look)
        assert look in ready and look in DIALS['look'], look
        assert e['status'] == 'skin' and e['renderer'] == 'whiteboard' and e['languages'] == ['en', 'zh']
        skin = skins.for_look(look)
        assert skin.id == look and not skin.plain and skin.hand != 'marker'
    chalk, note = skins.for_look('chalkboard'), skins.for_look('notebook')
    assert chalk.paper == 'slate' and chalk.emphasis == 'none' and note.paper == 'lined' and note.emphasis == 'highlighter'


def _inked(img):
    a = np.asarray(img, np.float32)
    return a[..., :3][a[..., 3] > 200], a[..., 3]


def test_a_skin_redraws_the_whiteboard_ink_as_chalk_or_pencil_with_grain_anchored_to_the_board():
    for look, near in (('chalkboard', (243, 241, 232)), ('notebook', (58, 60, 68))):
        skin = skins.for_look(look)
        td = ink.TextDrawing(['Chalk 粉笔'], 'en', 90)
        before = np.asarray(td.ink.getchannel('A'), np.float32)
        skin.dress(td, 0, 0)
        rgb, alpha = _inked(td.ink)
        assert np.abs(rgb.mean(0) - near).max() < 12, (look, rgb.mean(0))
        assert (alpha <= before + .5).all() and (alpha < before - 20).sum() > .03 * (before > 200).sum()  # grain
        assert np.array_equal(td.alpha, np.asarray(td.ink.getchannel('A')))
        shifted = [np.asarray(skin.dress(ink.TextDrawing(['Chalk'], 'en', 90), x, 0).ink.getchannel('A'))
                   for x in (0, skins.TILE, 1)]
        assert np.array_equal(shifted[0], shifted[1]) and not np.array_equal(shifted[0], shifted[2])
    orange = (240, 120, 20)
    box = [[(10, 10), (190, 10), (190, 190), (10, 190), (10, 10)]]
    chalk_line, _ = _inked(skins.for_look('chalkboard').dress(ink.stroke_drawing((200, 200), box, color=orange)).line)
    pencil_line, _ = _inked(skins.for_look('notebook').dress(ink.stroke_drawing((200, 200), box, color=orange)).line)
    assert chalk_line.mean(0).min() > 120 and chalk_line.mean(0)[0] > chalk_line.mean(0)[2]   # pastel orange chalk
    assert np.abs(pencil_line.mean(0) - orange).max() < 4                                    # colour pencil keeps it


def test_a_filled_shape_turns_from_lines_to_its_colour_without_a_grey_wash():
    box = [(10, 10), (190, 10), (190, 190), (10, 190), (10, 10)]
    for look in SKINS:
        d = skins.for_look(look).dress(ink.stroke_drawing((200, 200), [box], closed_fill=[(box, (255, 236, 140))]))
        img, _, _ = d.state(d.draw_time + d.pop / 2)                           # halfway from lines to colour
        final = np.asarray(d.color, np.float32)[100, 100]
        mid = np.asarray(img, np.float32)[100, 100]
        assert np.abs(mid[:3] - final[:3]).max() < 2 and 60 < mid[3] < 200, (look, mid, final)


def test_the_hand_holds_a_chalk_marker_or_a_pencil_made_from_the_same_photo():
    marker = np.asarray(ink.Hand().img, np.float32)
    for tool in ('chalk', 'pencil'):
        held = np.asarray(ink.Hand(tool).img, np.float32)
        assert np.array_equal(held[..., 3], marker[..., 3])                     # the same hand, the same matte
        changed = np.abs(held[..., :3] - marker[..., :3]).max(-1) > 30
        tip, cap = np.array(skins.TIP_TO_CAP[0]), np.array(skins.TIP_TO_CAP[1])
        ys, xs = np.nonzero(changed)
        u = (cap - tip) / np.linalg.norm(cap - tip)
        across = np.abs(-(xs - tip[0]) * u[1] + (ys - tip[1]) * u[0])
        assert changed.sum() > 4000 and (across < 24).all(), tool               # only the tool, along its axis
        rgb = held[changed][:, :3].mean(0)
        if tool == 'chalk':
            assert rgb.min() > 170                                              # white
        else:
            assert rgb[0] > rgb[1] > rgb[2] + 40                                # yellow


def test_the_highlighter_finds_the_key_phrase_where_it_is_written_in_english_and_chinese():
    td = ink.TextDrawing(['The sun warms up', 'oceans and lakes'], 'en', 60)
    one, two = skins.phrase_boxes(td, 'warms'), skins.phrase_boxes(td, 'UP  oceans')
    assert len(one) == 1 and len(two) == 2 and skins.phrase_boxes(td, 'rivers') == []
    x0, y0, x1, y1, start = one[0]
    assert 0 < x0 < x1 < td.size[0] and 0 <= y0 < y1 <= td.size[1] and 0 < start <= td.duration + .2
    assert two[0][1] < two[1][1] and two[0][4] < two[1][4]                       # line by line, as written
    zh = ink.TextDrawing(['如果长期睡不够'], 'zh', 60)
    (bx0, _, bx1, _, _), = skins.phrase_boxes(zh, '睡不够')
    assert zh.size[0] * .45 < bx0 < bx1 <= zh.size[0]

    lit = skins.Highlighted(td, one)
    def yellow(img):
        a = np.asarray(img.convert('RGBA'), np.int16)[int(y0):int(y1), int(x0):int(x1)]
        return ((a[..., 0] > 200) & (a[..., 2] < 150) & (a[..., 3] > 100)).sum()
    assert yellow(lit.state(start - .05)[0]) == 0 and yellow(lit.state(td.duration + 1)[0]) > 500
    assert lit.size == td.size and lit.duration == td.duration


def test_a_highlight_on_a_yellow_note_is_pink_on_paper_yellow_and_never_behind_coloured_words():
    from types import SimpleNamespace as NS
    note_box = [(0, 0), (600, 0), (600, 300), (0, 300), (0, 0)]
    note = ink.stroke_drawing((600, 300), [note_box], closed_fill=[(note_box, (255, 236, 140))])
    on_note, on_paper = ink.TextDrawing(['Keep warm'], 'en', 60), ink.TextDrawing(['Keep cool'], 'en', 60)
    orange = ink.TextDrawing(['Stay dry'], 'en', 60, color=(245, 124, 0))
    elements = [NS(drawing=note, x=0, y=0, trigger=0.), NS(drawing=on_note, x=40, y=60, trigger=1.),
                NS(drawing=on_paper, x=900, y=60, trigger=1.5), NS(drawing=orange, x=40, y=160, trigger=2.)]
    episode = {'beats': [{'id': 'b1', 'direction': [{'emphasis': 'keep warm'}, {'emphasis': 'cool'},
                                                     {'emphasis': 'dry'}]}]}
    skins.highlight_phrases(episode, {'beats': {'b1': {'start': .5, 'end': 3.}}}, elements)
    assert elements[1].drawing.color == skins.ON_YELLOW and elements[2].drawing.color == skins.HIGHLIGHTER
    assert elements[3].drawing is orange                      # coloured words are left as they are


def test_the_cli_and_the_studio_make_chalkboard_and_notebook_videos(tmp_path, monkeypatch, capsys):
    from kinodraw import cli, director
    from kinodraw.studio import server
    monkeypatch.setattr(director, 'direct', lambda *a, **k: {'warnings': [], 'notes': [], 'usage': None})
    cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'cli'), '--look', 'chalkboard'])
    assert pipeline.storyboard(tmp_path / 'cli')['look'] == 'chalkboard'

    offered = [s['value'] for s in server.state()['styles']]
    for look in SKINS:
        assert f'{look}/explain' in offered
    monkeypatch.setattr(server, 'projects_root', lambda: tmp_path)
    jid = server.create_project({'text': (FIX / 'tiny.md').read_text(), 'title': 'Notes', 'look': 'notebook',
                                 'story': 'explain'})['job']
    import time
    for _ in range(500):
        if server.JOBS.get(jid)['state'] in ('done', 'failed'):
            break
        time.sleep(.02)
    assert server.JOBS.get(jid)['state'] == 'done', server.JOBS.get(jid)['error']
    assert pipeline.storyboard(tmp_path / server.JOBS.get(jid)['project'])['look'] == 'notebook'


def test_each_skin_renders_its_paper_ink_and_captions(tmp_path):
    for look in SKINS:
        board = pipeline.new_project(FIX / 'tiny.md', tmp_path / look, direction={'look': look})
        tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
        prod = renderer.make_production(board, tl, 'en', tmp_path / look)
        skin = prod.skin
        assert skin.id == look and prod.hand.img.size == ink.Hand().img.size
        frame = np.asarray(prod.frame(tl['captions'][3]['start'] + .1).convert('RGB'), np.int16)
        assert frame.shape == (1080, 1920, 3)
        assert np.abs(frame[600, 1880] - skin.base).max() < 25, (look, frame[600, 1880])      # its paper
        board_px = frame[120:860].reshape(-1, 3)
        assert (np.abs(board_px - skin.ink).max(-1) < 40).sum() > 2000, look                  # its ink
        caps = frame[880:1046].reshape(-1, 3)
        assert (np.abs(caps - skin.caption).max(-1) < 30).sum() > 1500, look                 # its captions


def test_every_key_phrase_in_one_text_is_highlighted_in_english_and_chinese():
    from types import SimpleNamespace as NS
    for lang, text, phrases in (('en', 'Sun warms oceans. Rain fills lakes.', ('Sun', 'Rain')),
                                ('zh', '太阳温暖海洋。雨水注入湖泊。', ('太阳', '雨水'))):
        td = ink.TextDrawing([text], lang, 60)
        elements = [NS(drawing=td, x=40, y=60, trigger=1.)]
        episode = {'beats': [{'id': 'b1', 'direction': [{'emphasis': p} for p in phrases]}]}
        skins.highlight_phrases(episode, {'beats': {'b1': {'start': .5, 'end': 3.}}}, elements)
        lit = elements[0].drawing
        assert isinstance(lit, skins.Highlighted) and len(lit.boxes) == 2, lang
        assert lit.boxes[0][2] < lit.boxes[1][0], lang                  # the first phrase, then the second


def test_an_english_key_phrase_is_highlighted_as_a_word_not_inside_another_word():
    td = ink.TextDrawing(['Sunday brings sun.'], 'en', 60)
    (x0, _, x1, _, _), = skins.phrase_boxes(td, 'sun')
    assert x0 > td.size[0] * .6                                         # the word "sun", not the "Sun" of Sunday
    (w0, _, _, _, _), = skins.phrase_boxes(ink.TextDrawing(['It warms up'], 'en', 60), 'warm')
    assert w0 > 0                                                       # a word's start still matches its stem


def test_the_studio_offers_its_styles_from_the_registry(monkeypatch):
    from kinodraw.studio import server
    static = Path(server.__file__).parent / 'static'
    assert '<option value="chalkboard' not in (static / 'index.html').read_text()   # no second list in the page
    assert 'STATE.styles' in (static / 'app.js').read_text()
    styles_offered = server.state()['styles']
    assert [s['value'].split('/')[0] for s in styles_offered] == styles.ids(ready=True)
    assert {'value': 'collage/promo', 'label': styles.get('collage')['name']['en']} in styles_offered
    entries = [dict(e, render_ready=False) if e['id'] == 'chalkboard' else e for e in styles.looks()]
    monkeypatch.setattr(styles, '_looks', lambda: tuple(entries))
    assert 'chalkboard' not in [s['value'].split('/')[0] for s in server.state()['styles']]

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
        assert set(e['name']) == ({'en', 'zh', 'es'} if e['renderer'] == 'whiteboard' else {'en', 'zh'}) and all(e['name'].values()), e['id']
        assert e['status'] in styles.STATUSES and isinstance(e['render_ready'], bool)
        assert e['render_ready'] == (e['status'] != 'planned'), e['id']           # planned looks are never offered
        assert e['languages'] and set(e['languages']) <= {'en', 'zh', 'es'}
        assert e['stories'] and set(e['stories']) <= set(DIALS['story'])
        m = e['motion']
        assert {m['min'], m['max'], m['default']} <= set(MOTIONS)
        assert MOTIONS.index(m['min']) <= MOTIONS.index(m['default']) <= MOTIONS.index(m['max'])
        assert e['aspect'] == (list(pipeline.ASPECTS) if e['renderer'] == 'whiteboard'
                               else ['16:9', '9:16'] if e['render_ready'] else ['16:9'])
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
        _Probe.seen.append(drawing)
        return drawing


def test_a_skin_reaches_every_drawing_the_paper_the_fonts_the_hand_and_the_captions(tmp_path, monkeypatch):
    board = pipeline.new_project(FIX / 'tiny.md', tmp_path / 'p')
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    arimo = ink.Fonts(*([ink.EN_CAPTION] * 5))                                     # every text in a sans
    probe = _Probe(id='probe', fonts=arimo, hand='chalk', caption=(200, 0, 0), caption_edge=(0, 0, 0))
    _Probe.seen, hands, used = [], [], set()
    real_hand, real_font = ink.Hand, ink.font
    monkeypatch.setattr(ink, 'Hand', lambda tool='marker', side='right': hands.append(tool) or real_hand())
    monkeypatch.setattr(ink, 'font', lambda kind, size, fonts=ink.FONTS: used.add(fonts) or real_font(kind, size, fonts))
    monkeypatch.setattr(skins, 'for_look', lambda look: probe)
    prod = renderer.make_production(board, tl, 'en', tmp_path / 'p')
    assert prod.skin is probe and hands == ['chalk']
    # Agenda hooks are dressed before admission; rejected candidates never
    # enter ctx.elements. Every retained drawing and candidate is dressed once.
    drawings = {id(e.drawing) for e in prod.ctx.elements}
    drawings.update(id(e.drawing) for card in prod.cards.values() for e in card.get('hooks', []))
    assert len(_Probe.seen) == len(drawings)
    assert {id(d) for d in _Probe.seen} == drawings
    assert {'TextDrawing', 'PathDrawing'} <= {type(d).__name__ for d in _Probe.seen}
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


def test_the_chalkboard_and_notebook_looks_are_offered_in_all_languages():
    ready = styles.ids(ready=True)
    for look in SKINS:
        e = styles.get(look)
        assert look in ready and look in DIALS['look'], look
        assert e['status'] == 'skin' and e['renderer'] == 'whiteboard' and e['languages'] == ['en', 'zh', 'es']
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
    # The v3 plan is stubbed too, and no cloud provider is made for it: no live cloud call, no anonymous token.
    monkeypatch.setitem(server.STUDIO_HOOKS, 'provider', lambda body: 'rules')
    monkeypatch.setattr(server.pipeline, 'direct_v3', lambda *a, **k: {'notes': [], 'usage': None})
    jid = server.create_project({'text': (FIX / 'tiny.md').read_text(encoding='utf-8'), 'title': 'Notes',
                                 'look': 'notebook', 'story': 'explain'})['job']
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
    # no second list in the page
    assert '<option value="chalkboard' not in (static / 'index.html').read_text(encoding='utf-8')
    assert 'STATE.styles' in (static / 'app.js').read_text(encoding='utf-8')
    styles_offered = server.state()['styles']
    assert [s['value'].split('/')[0] for s in styles_offered] == styles.ids(ready=True)
    assert {'value': 'collage/promo', 'label': styles.get('collage')['name']['en']} in styles_offered
    entries = [dict(e, render_ready=False) if e['id'] == 'chalkboard' else e for e in styles.looks()]
    monkeypatch.setattr(styles, '_looks', lambda: tuple(entries))
    assert 'chalkboard' not in [s['value'].split('/')[0] for s in server.state()['styles']]


# ------------------------------------------------------------------ papers (storyboard "paper", "paper_color")
def _lab(rgb):
    c = np.asarray(rgb, np.float64) / 255
    lin = np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)
    xyz = lin @ np.array([[.4124564, .2126729, .0193339], [.3575761, .7151522, .1191920],
                          [.1804375, .0721750, .9503041]]) / (.95047, 1., 1.08883)
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def _ciede2000(lab1, lab2):
    (l1, a1, b1), (l2, a2, b2) = lab1, lab2
    cb = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = .5 * (1 - np.sqrt(cb ** 7 / (cb ** 7 + 25 ** 7)))
    a1, a2 = a1 * (1 + g), a2 * (1 + g)
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    h1, h2 = np.degrees(np.arctan2(b1, a1)) % 360, np.degrees(np.arctan2(b2, a2)) % 360
    dh = 0 if c1 * c2 == 0 else (h2 - h1 + 180) % 360 - 180
    dl, dc, dhh = l2 - l1, c2 - c1, 2 * np.sqrt(c1 * c2) * np.sin(np.radians(dh / 2))
    lm, cm = (l1 + l2) / 2, (c1 + c2) / 2
    hm = h1 + h2 if c1 * c2 == 0 else (h1 + h2) / 2 if abs(h1 - h2) <= 180 else (h1 + h2 + 360 * (1 if h1 + h2 < 360 else -1)) / 2
    t = (1 - .17 * np.cos(np.radians(hm - 30)) + .24 * np.cos(np.radians(2 * hm)) + .32 * np.cos(np.radians(3 * hm + 6))
         - .2 * np.cos(np.radians(4 * hm - 63)))
    sl = 1 + .015 * (lm - 50) ** 2 / np.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + .045 * cm, 1 + .015 * cm * t
    rt = -np.sin(np.radians(60 * np.exp(-((hm - 275) / 25) ** 2))) * 2 * np.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7))
    return float(np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * dc / sc * dhh / sh))


def _paper(**board):
    return np.asarray(skins.for_board({'look': 'whiteboard', **board}).background(1920, 1080), np.float32)[..., :3]


def test_ciede2000_matches_the_published_test_data():
    assert abs(_ciede2000((50, 2.6772, -79.7751), (50, 0, -82.7485)) - 2.0425) < 1e-3       # Sharma et al., pair 1
    assert abs(_ciede2000((50, 2.5, 0), (73, 25, -18)) - 27.1492) < 1e-3                    # pair 18


def test_grid_paper_lines_repeat_at_the_grid_spacing():
    from scipy import ndimage
    step = skins.grid_spacing(1920, 1080)
    assert step == 48 and 1920 % step == 0                       # whole cells across: the idle drift wraps it
    cols = _paper(paper='grid').mean(-1).mean(0)
    spectrum = np.abs(np.fft.rfft(cols - ndimage.gaussian_filter1d(cols, 96, mode='wrap')))     # minus the vignette
    assert np.argmax(spectrum[5:]) + 5 == 1920 / step


def test_dot_paper_has_a_darker_dot_on_every_crossing():
    img, step = _paper(paper='dots').mean(-1), 48
    base = np.mean(ink.PAPER_RGB)
    centres = [(y, x) for y in np.arange(1080 % step // 2, 1080, step) for x in np.arange(0, 1920, step)]
    darker = sum(img[y, x] < base - 20 for y, x in centres)
    assert darker >= .9 * len(centres)
    assert abs(img[24 + 1080 % step // 2, 24] - base) < 15                   # paper between the dots


def test_kraft_and_your_own_paper_colour_look_as_chosen():
    mean = lambda img: img.reshape(-1, 3).mean(0)
    assert _ciede2000(_lab(mean(_paper(paper='kraft'))), _lab(ink.rgba('#d8bf98')[:3])) < 5
    for kind in ('plain', 'grid', 'dots'):
        own = _ciede2000(_lab(mean(_paper(paper=kind, paper_color='#fdf6e3')[200:880, 300:1620])),
                         _lab(ink.rgba('#fdf6e3')[:3]))
        assert own < (2 if kind == 'plain' else 6), (kind, own)


def test_a_paper_colour_the_writing_cannot_be_read_on_is_refused():
    import pytest
    for board, words in (({'paper': 'plain', 'paper_color': '#303030'}, 'hard to read'),
                         ({'paper': 'kraft', 'paper_color': '#fdf6e3'}, 'paper_color'),
                         ({'paper': 'grid', 'paper_color': 'blue'}, 'paper_color'),
                         ({'paper': 'cork'}, 'paper must be')):
        with pytest.raises(ValueError, match=words):
            skins.for_board({'look': 'whiteboard', **board})
    for kind in skins.PAPERS:
        sk = skins.for_board({'look': 'whiteboard', 'paper': kind})
        assert skins.contrast(sk.ink, sk.base) >= 4.5 and skins.contrast(sk.caption, sk.caption_edge) >= 4.5
    assert skins.for_board({'look': 'whiteboard'}) is skins.for_look('whiteboard')            # the default is untouched
    assert skins.for_board({'look': 'chalkboard', 'paper': 'grid'}) is skins.for_look('chalkboard')   # its own board


def test_each_paper_is_drawn_under_the_board_and_its_captions(tmp_path):
    for kind in skins.PAPERS:
        board = pipeline.new_project(FIX / 'tiny.md', tmp_path / kind, direction={'look': 'whiteboard'})
        board['paper'] = kind
        tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
        prod = renderer.make_production(board, tl, 'en', tmp_path / kind)
        assert prod.skin.paper == ('whiteboard' if kind == 'plain' else kind)        # plain: the whiteboard's own
        frame = np.asarray(prod.frame(tl['captions'][3]['start'] + .1).convert('RGB'), np.int16)
        paper = np.asarray(prod.skin.background(1920, 1080).convert('RGB'), np.int16)
        assert np.abs(frame[560:640, 1840:1900] - paper[560:640, 1840:1900]).max() <= 2, kind     # its paper
        caps = frame[880:1046].reshape(-1, 3)
        assert (np.abs(caps - prod.skin.caption).max(-1) < 30).sum() > 1500, kind               # its captions


def test_a_storyboard_check_refuses_an_unknown_paper_or_an_unreadable_colour():
    from kinodraw.director.validate import validate
    base = {'lang': 'en', 'chapters': [], 'beats': []}
    assert validate({**base, 'paper': 'dots', 'paper_color': '#fdf6e3'})['ok']
    for bad in ({'paper': 'cork'}, {'paper': 'plain', 'paper_color': '#202020'}):
        report = validate({**base, **bad})
        assert not report['ok'] and any('paper' in e or 'read' in e for e in report['errors']), report

"""The style registry and the skin layer: every look is described once, and a skin reaches every mark, text, font,
paper, hand and caption the whiteboard renderer draws."""
import dataclasses
from pathlib import Path

import numpy as np
from PIL import Image

from doodlestudio import pipeline, styles
from doodlestudio.engine import ink, render as renderer, skin as skins, timeline
from doodlestudio.engine.storyboard import DIALS

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
        assert e['aspect'] == ['16:9']                                            # the engine renders 1920x1080
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
    from doodlestudio import cli
    with pytest.raises(SystemExit):
        cli.main(['make', '--help'])
    offered = capsys.readouterr().out.split('--look {', 1)[1].split('}', 1)[0].split(',')
    assert offered == styles.ids(ready=True) and 'bold' not in offered       # planned looks are not offered

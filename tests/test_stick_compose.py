"""The stick look's scene composer on rules-director storyboards (synthetic reading-rate timing, no voice model):
every beat is acted out, shots cut cleanly end to end, nothing on screen overlaps, and Chinese renders."""
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageFont

from doodlestudio import ingest, script
from doodlestudio.director.rules import RulesDirector
from doodlestudio.engine import timeline as tl
from doodlestudio.engine.stick import compose, cues, text
from doodlestudio.engine.stick.render import StickProduction

FIX = Path(__file__).parent / 'fixtures'


def build(name, seed=0):
    board = script.build(ingest.read(FIX / name))
    lang = board['lang']
    board = RulesDirector(lang).direct(board)
    timing = tl.layout(board, lang, tl.synthetic_clips(board, lang), pauses={})
    return StickProduction(board, timing, lang, None, seed=seed)


@pytest.fixture(scope='module', params=['printing_press.md', 'sky_blue.md', 'sleep_zh.md'])
def prod(request):
    return build(request.param)


def test_shots_cut_end_to_end(prod):
    shots = prod.shots
    assert shots[0].start == pytest.approx(0, abs=1e-6)
    for a, b in zip(shots, shots[1:]):
        assert b.start == pytest.approx(a.end, abs=1e-3), f'gap or overlap between {a.layout} and {b.layout}'
        assert a.end > a.start
    assert shots[-1].end == pytest.approx(prod.tl['duration'], abs=1e-3)


def test_every_beat_is_acted(prod):
    shown = {b for s in prod.shots for b in s.beats}
    assert {b['id'] for b in prod.board['beats']} <= shown
    for s in prod.shots:
        assert any(i.kind in ('figure', 'crowd') for i in s.items), f'{s.layout} shot at {s.start:.1f}s has nobody'


def test_nothing_overlaps(prod):
    bad = [(round(s.start, 2), s.layout, compose.overlaps(s)) for s in prod.shots if compose.overlaps(s)]
    assert not bad, bad


def test_everything_stays_on_screen(prod):
    for s in prod.shots:
        for it in s.items:
            if it.kind in ('ground',):
                continue
            x0, y0, x1, y1 = it.rect
            assert x0 >= -2 and y0 >= -2 and x1 <= compose.W + 2 and y1 <= compose.H + 2, \
                f'{it.kind} off screen in the {s.layout} shot at {s.start:.1f}s: {it.rect}'


def test_frames_render(prod):
    for s in prod.shots:
        img = prod.frame((s.start + s.end) / 2)
        assert img.size == (compose.W, compose.H)
        assert np.asarray(img.convert('L')).min() < 60          # something black was drawn


def test_same_seed_same_frames():
    a, b = build('printing_press.md', seed=5), build('printing_press.md', seed=5)
    for t in (1., 12.3, a.tl['duration'] * .5, a.tl['duration'] - 1):
        assert np.array_equal(np.asarray(a.frame(t)), np.asarray(b.frame(t)))


def test_chinese_labels_use_real_glyphs():
    face = ImageFont.truetype(text.CJK, 60)
    tofu = face.getmask('').getbbox()
    for ch in '为什么天空是蓝色的倍年':
        assert face.getmask(ch).getbbox() != tofu, ch
    img = text.block('为什么天空是蓝色的？', 'zh', 80, max_w=900)
    assert np.asarray(img)[..., 3].any() and img.width > 400


def test_number_and_cue_rules():
    assert compose.number_text('235', 'Between 235 and 284, more than twenty emperors ruled.') == '235–284'
    assert compose.number_text('270', 'By the 270s, a coin was mostly copper.') == '270s'
    assert compose._name_only('Odoacer removed', 'en') == 'Odoacer'
    assert compose._name_only('Battle of Adrianople', 'en') == 'Battle of Adrianople'
    assert cues.pose_for('Rome did not fall in a day.', 'en')[0] is None
    assert cues.pose_for('So there was no single cause. Rome fell.', 'en')[0] == 'shrug'
    assert cues.pose_for('Why is the sky blue?', 'en')[0] == 'think'
    assert cues.pose_for('我们没看到紫色', 'zh')[0] is None


def test_a_holding_figure_carries_its_picture():
    p = build('printing_press.md')
    comp = p.composer
    shot = comp.base(0., 4., 'left', None, [], words='')
    card = compose.Card('doodle', .5, {'doodle': 'coin_stack', 'label': 'Coins'}, 'v1')
    comp.lay_left(shot, None, [card], None, None, 'hold', None, None, None, 7, False, '')
    fig = next(i for i in shot.items if i.kind == 'figure')
    held = [i for i in shot.items if i.kind == 'doodle']
    assert len(held) == 1 and held[0].group == fig.group, 'the picture should be in the hands, not on the stage'
    hx0, hy0, hx1, hy1 = held[0].rect
    fx0, fy0, fx1, fy1 = fig.rect
    assert fx0 - 60 < (hx0 + hx1) / 2 < fx1 + 120 and fy0 < (hy0 + hy1) / 2 < fy1
    assert not compose.overlaps(shot)

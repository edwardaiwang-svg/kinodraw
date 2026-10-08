"""Every text surface draws every character customers type with a real glyph, never a missing-glyph box ("tofu"),
and a character no bundled font has fails QA by name instead of passing silently."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from kinodraw import ingest, pipeline, script, styles
from kinodraw.engine import captions, data_cards, ink, markup_boards, render, shots, skin, timeline, ui_screens
from kinodraw.engine.bold import render as bold
from kinodraw.engine.collage import ui_kit
from kinodraw.engine.stick import text as stick_text

CHARS = ('₀₁₂₃₄₅₆₇₈₉₊₋⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻×÷≈±≤≥√π°‰½¼¾⅓→←↑↓€£¥₹¢‘’“”–—éñüçøåÉÑ中文')
UNCOVERED = ''          # private use: no bundled font has it


def _missing():
    return getattr(ink, 'MISSING', {})


@pytest.fixture(autouse=True)
def _clean_missing():
    _missing().clear()
    yield
    _missing().clear()


def _mask(font, text):
    img = Image.new('L', (int(font.size * 3 * max(1, len(text))) + 20, int(font.size * 3)), 0)
    ImageDraw.Draw(img).text((10, font.size), text, font=font, fill=255)
    return np.asarray(img)


def _tofu(font, ch):
    """True when ``font`` draws ``ch`` as nothing or as the same shape it draws for a code point no font has."""
    drawn, box = _mask(font, ch), _mask(font, UNCOVERED)
    for key in [k for k in _missing() if k[0] == UNCOVERED]:      # the reference box itself is not a finding
        del _missing()[key]
    return not drawn.any() or np.array_equal(drawn, box)


def _surfaces():
    """{surface name: a function returning the font it draws a line with} for every text surface."""
    out = {}
    for look in [l['id'] for l in styles.looks()]:
        for lang in ('en', 'zh'):
            out[f'{look} board label {lang}'] = lambda look=look, lang=lang: ink.font_runs(
                'x', lang, 48, skin.for_look(look).fonts)[0][1]
            out[f'{look} caption {lang}'] = lambda look=look, lang=lang: captions.cap_font(lang, skin.for_look(look).fonts)
        out[f'{look} on-screen label'] = lambda look=look: ink.font('ui', 40, skin.for_look(look).fonts)
    out.update({'data card': lambda: data_cards._clean_font(40), 'device screen': lambda: ui_screens._font(40),
                'device screen code': lambda: ui_screens._font(40, True), 'shot label': lambda: shots._font(40),
                'story title': lambda: ink.truetype(ink.EN_HAND[0], 48, 'story title'),
                'stick text latin': lambda: stick_text.font(stick_text.LATIN, 40),
                'stick text cjk': lambda: stick_text.font(stick_text.CJK, 40)})
    for name in ('MONO', 'MATH', 'MATH_ITALIC'):
        out[f'markup board {name}'] = lambda name=name: markup_boards._font(getattr(markup_boards, name), 40)
    for family in ('SANS', 'HAND', 'ZH_SANS', 'ZH_HAND'):
        out[f'collage {family}'] = lambda family=family: ui_kit._font(getattr(ui_kit, family), 40)
    for family in bold.TYPE_FONTS:
        out[f'kinetic type {family}'] = lambda family=family: bold._text_metrics('Ab', 40, 800, False, family)[1]
    return out


SURFACES = _surfaces()


@pytest.mark.parametrize('name', sorted(SURFACES))
def test_every_surface_draws_every_listed_character(name):
    font = SURFACES[name]()
    boxes = [ch for ch in CHARS if _tofu(font, ch)]
    assert not boxes, f'{name} draws {"".join(boxes)} as a missing-glyph box'
    assert not _missing()


@pytest.mark.parametrize('lang', ['en', 'zh'])
def test_handwritten_board_label_runs_draw_every_character(lang):
    boxes = [ch for ch in CHARS for part, f in ink.font_runs(ch, lang, 48) if _tofu(f, part)]
    assert not boxes, f'board label ({lang}) boxes: {"".join(boxes)}'


def test_kinetic_type_raster_draws_every_character():
    fonts = [str(ink.ASSETS / 'fonts' / name) for _, name in dict.fromkeys(bold.TYPE_FONTS.values())]
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="2600" height="120"><text x="10" y="80" font-size="40" '
           f'font-family="Cinzel">{CHARS}</text></svg>')
    bold._raster(doc, 2600, 120, text=True)
    assert not _missing()
    bold._raster(doc.replace(CHARS, CHARS + UNCOVERED), 2600, 120, text=True)
    assert ('', 'kinetic type') in _missing()
    assert fonts


def test_covered_text_is_drawn_exactly_as_before():
    """Same fonts for characters a font already covers: pixel-identical to plain Pillow, width unchanged."""
    for path in (ink.EN_HAND[0], ink.EN_CAPTION[0], ink.ZH_CAPTION[0], ink.ZH_HAND[0]):
        plain = ImageFont.truetype(path, 52, layout_engine=ImageFont.Layout.BASIC)
        ours = ink.truetype(path, 52, 'test', layout_engine=ImageFont.Layout.BASIC)
        for text in ('Water boils at 100 degrees.', '水在一百度沸腾'):
            if all(ord(c) in ink._cmap(path, 0) or c == ' ' for c in text):
                assert np.array_equal(_mask(plain, text), _mask(ours, text))
                assert plain.getlength(text) == ours.getlength(text)


def test_fallback_layout_measures_what_it_draws():
    """A caption with fallback glyphs is as wide as its letters: nothing clipped, no gap left at the right."""
    for lang, text in (('en', 'Water is H₂O, about ⅓ of ₹90 中文'), ('zh', '水是H₂O，约⅓，价格₹90')):
        img = captions.caption_image(text, lang)
        box = img.getchannel('A').getbbox()
        assert box[0] <= 12 and img.width - box[2] <= 12, (lang, box, img.size)
        f = captions.cap_font(lang)
        assert f.getbbox(text)[2] == pytest.approx(f.getlength(text), abs=f.size * .3)
    td = ink.TextDrawing(['H₂O + CO₂ → ⅓ ₹'], 'en', 60)
    alpha = np.asarray(td.ink.getchannel('A')) > 64
    assert td.ink.getchannel('A').getbbox()[2] >= td.size[0] - 6 - 60 * .5
    (chars, _, _), = td.placed
    cols = {ch: alpha[:, int(x0):int(x1) + 1] for ch, x0, x1 in chars[:3]}       # H, ₂, O as the board writes them
    rows = {ch: np.nonzero(c.any(1))[0] for ch, c in cols.items()}
    assert rows['₂'][-1] > rows['H'][-1] + 60 * .06           # the subscript hangs below the H's baseline
    assert rows['₂'][0] > rows['H'][0] + 60 * .25             # and starts well below its top: a small digit
    assert cols['₂'].sum() < .7 * cols['O'].sum()
    assert not _missing()


def test_sub_and_superscripts_are_the_surface_font_digits_shifted():
    hand = ink.font('en_hand', 100)                   # Playpen Sans has no ⁸ or ₂: drawn from its own 8 and 2
    digit = -hand.getbbox('8', anchor='ls')[1]
    sup = hand.getbbox('⁸', anchor='ls')
    sub = hand.getbbox('₂', anchor='ls')
    assert .5 * digit < sup[3] - sup[1] < .75 * digit, sup      # smaller than a digit
    assert sup[3] < -.3 * digit                                  # sits above the baseline
    assert sub[3] > .08 * digit and sub[1] > -.75 * digit        # hangs below the baseline, top below a digit's
    small = ImageFont.truetype(ink.EN_HAND[0], round(100 * .62), layout_engine=ImageFont.Layout.BASIC)
    assert hand.getlength('10⁸') == pytest.approx(hand.getlength('10') + small.getlength('8'))
    assert not _tofu(hand, '⁸') and not _tofu(hand, '₂')
    assert not _missing()


def test_a_character_no_font_has_is_named_with_its_surface():
    captions.caption_image(f'Total {UNCOVERED} today', 'en')
    ink.font_runs(f'Board {UNCOVERED} label', 'en', 40)
    ui_screens._font(30).getlength(f'Screen {UNCOVERED}')
    problems = ink.glyph_problems()
    assert any('U+E000' in p and 'caption' in p and 'Total' in p for p in problems), problems
    assert any('U+E000' in p and 'handwritten board text' in p and 'Board' in p for p in problems), problems
    assert any('U+E000' in p and 'device screen' in p for p in problems), problems


def test_render_reports_and_qa_fails_on_an_uncovered_character(tmp_path):
    """The render manifest carries the missing glyph and finish's QA turns it into a failed problem."""
    board = script.build(ingest.read(f'Water is H₂O {UNCOVERED} today.\n\nLight moves at 3.0 × 10⁸ m/s.'))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    episode, out = tmp_path / 'storyboard.json', tmp_path / 'build' / 'silent.mp4'
    episode.write_text(json.dumps(board, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'timeline.json').write_text(json.dumps(tl), encoding='utf-8')
    at = next(c['start'] for c in tl['captions'] if UNCOVERED in c['text']) + .3
    render.main(['--project', str(tmp_path), '--episode', str(episode), '--lang', 'en', '--timeline',
                 str(tmp_path / 'timeline.json'), '--start', str(at), '--frames', '2', '--output', str(out)])
    warnings = json.loads(Path(f'{out}.json').read_text(encoding='utf-8'))['warnings']
    assert any(w.startswith('Missing glyph:') and 'U+E000' in w for w in warnings), warnings
    qa = {'ok': True, 'problems': []}
    pipeline._save(out.parent / 'render-warnings.json', warnings)
    pipeline._glyph_qa(qa, out.parent)
    assert not qa['ok'] and any('U+E000' in p and 'caption' in p for p in qa['problems'])
    clean = {'ok': True, 'problems': []}
    pipeline._save(out.parent / 'render-warnings.json', ['skipped 1 visual(s)'])
    pipeline._glyph_qa(clean, out.parent)
    assert clean == {'ok': True, 'problems': []}

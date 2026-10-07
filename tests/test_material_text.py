"""Material letterbox glyph coverage and look-aware two-line caption cues."""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from kinodraw import ingest, pipeline, script
from kinodraw.engine import captions, ink, render, skin, timeline, vertical

FIX = Path(__file__).parent / 'fixtures'
TEXT = 'CO₂ emissions → 2050 Café crème'
CASES = [(look, lang) for look in ('pixel_quest', 'mosaic') for lang in ('en', 'zh')]


@pytest.fixture(scope='module', params=CASES, ids=lambda case: '-'.join(case))
def material(request, tmp_path_factory):
    look, lang = request.param
    project = tmp_path_factory.mktemp(f'{look}-{lang}')
    ep = pipeline.new_project(FIX / ('tiny.md' if lang == 'en' else 'sleep_zh.md'), project,
                              direction={'look': look}, aspect='9:16')
    tl = timeline.layout(ep, lang, timeline.synthetic_clips(ep, lang))
    return render.make_production(ep, tl, lang, project, aspect='9:16'), tl


def _record_text(monkeypatch):
    calls = []
    original = ImageDraw.ImageDraw.text

    def record(draw, xy, text, *args, **kwargs):
        calls.append((xy, text, kwargs['font'], kwargs.get('anchor')))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', record)
    return calls


@pytest.mark.parametrize('path', ['caption', 'title', 'label/source', 'credit'])
def test_vertical_material_paths_draw_supported_glyphs(material, monkeypatch, path):
    prod, _ = material
    prod._title_image.cache_clear()
    vertical.caption_image.cache_clear()
    vertical._credit_image.cache_clear()
    calls = _record_text(monkeypatch)
    text = TEXT if prod.lang == 'en' else '气候 ' + TEXT
    if path == 'caption':
        prod.caption_image(text)
    elif path == 'title':
        monkeypatch.setitem(prod.ep, 'title', {prod.lang: text})
        prod._title_image(('title',))
    elif path == 'label/source':
        ch = next(c for c in prod.ep['chapters'] if c['kind'] == 'section')
        monkeypatch.setitem(ch, 'label', {prod.lang: text})
        monkeypatch.setitem(ch, 'title', {prod.lang: 'Chapter'})
        monkeypatch.setitem(ch, 'speaker', None)
        monkeypatch.setitem(ch, 'source', {prod.lang: text})
        prod._title_image(('chapter', ch['id']))
    else:
        vertical._credit_image(text, text, prod.lang, prod.fonts, prod._soft())
    assert calls
    assert any('₂' in text for _, text, _, _ in calls), 'the test must reach the missing glyph'
    for _, text, font, _ in calls:
        missing = ''.join(ch for ch in text if not ch.isspace() and ord(ch) not in ink._cmap(font.path, font.index))
        assert not missing, f'{path}: {missing!r} missing in {Path(font.path).name}'
    # Mixed fonts on a line share the same baseline.
    mixed = [(xy, font, anchor) for xy, text, font, anchor in calls if '₂' in text]
    assert all(anchor == 'ls' for _, _, anchor in mixed)
    for (x, y), _, _ in mixed:
        assert any(xy[1] == y and font.path in (prod.fonts.en_caption[0], prod.fonts.zh_caption[0],
                                               prod.fonts.en_hand[0], prod.fonts.zh_hand[0], prod.fonts.ui[0])
                   and anchor == 'ls' for xy, _, font, anchor in calls)


def _single_font_caption(text, lang, fonts, color=(18, 18, 18), edge=(255, 255, 255)):
    """The original caption fast path, including its single-font measurement."""
    kind = 'en_caption' if lang != 'zh' else 'zh_caption'
    measure = lambda size: ink.font(kind, size, fonts).getlength
    for size in range(vertical.CAP_SIZE, vertical.CAP_MIN - 1, -2):
        lines = vertical._wrap(text, lang, vertical.TEXT_W, measure(size))
        if len(lines) <= vertical.CAP_LINES:
            break
    else:
        available = vertical.H - 240 - (vertical.BOARD[1] + vertical.BOARD[3] + vertical.CAP_GAP)
        for size in range(vertical.CAP_MIN, 7, -2):
            lines = vertical._wrap(text, lang, vertical.TEXT_W, measure(size))
            if vertical._caption_height(len(lines), size) <= available or size == 8:
                break
    f = ink.font(kind, size, fonts)
    stroke, lh = max(5, round(size / 10)), int(size * 1.18)
    widths = [f.getlength(line) for line in lines]
    w = int(max(widths)) + 2 * stroke + 8
    img = Image.new('RGBA', (w, vertical._caption_height(len(lines), size)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text(((w - widths[i]) / 2, stroke + i * lh), line, font=f, fill=tuple(color) + (255,),
               stroke_width=stroke, stroke_fill=tuple(edge) + (255,))
    return img


def test_material_caption_image_removes_the_missing_glyph_box(material):
    prod, _ = material
    actual = prod.caption_image(TEXT)
    boxed = _single_font_caption(TEXT, prod.lang, prod.fonts, prod.skin.caption, prod.skin.caption_edge)
    assert actual.size != boxed.size or actual.tobytes() != boxed.tobytes()
    lines, size = vertical.caption_lines(TEXT, prod.lang, prod.fonts)
    kind = 'en_caption' if prod.lang == 'en' else 'zh_caption'
    assert all(skin._run_width(line, kind, size, prod.fonts) <= vertical.TEXT_W for line in lines)


@pytest.mark.parametrize('look', ['whiteboard', 'chalkboard', 'notebook'])
@pytest.mark.parametrize('lang,text', [('en', 'Café crème and CO₂ emissions → 2050'),
                                      ('zh', '植物利用阳光、水和空气制造养分。'),
                                      ('es', 'Los pingüinos caminan por la Antártida más fría.')])
def test_existing_caption_fast_path_is_byte_identical(look, lang, text):
    fonts = skin.for_look(look).fonts
    kind = 'zh_caption' if lang == 'zh' else 'en_caption'
    assert all(ch.isspace() or ord(ch) in ink._cmap(*getattr(fonts, kind)) for ch in text)
    actual, original = vertical.caption_image(text, lang, fonts), _single_font_caption(text, lang, fonts)
    assert actual.size == original.size and actual.tobytes() == original.tobytes()


def _assert_two_lines(text, lang, look_skin):
    lines, size = skin.caption_layout(text, lang, look_skin)
    assert len(lines) <= 2, (text, lines, size)
    kind = 'en_caption' if lang == 'en' else 'zh_caption'
    assert all(skin._run_width(line, kind, size, look_skin.fonts) <= 1640 for line in lines)


def test_pixel_quest_pathological_cue_is_split():
    ep = script.build(ingest.read(FIX / 'tiny.md'))
    ep['look'] = 'pixel_quest'
    look_skin = skin.for_look('pixel_quest')
    text = ('ill ' * 44).strip()
    # The original default-font splitter regards the whole clause as one valid cue.
    default = captions.cues_for_beat(text, text, 'en', lambda p: p / 10, 18)
    assert len(default) == 1
    assert len(skin.caption_layout(text, 'en', look_skin)[0]) == 3
    ep['beats'][0]['spoken']['en'] = ep['beats'][0]['display']['en'] = text
    tl = timeline.layout(ep, 'en', timeline.synthetic_clips(ep, 'en'))
    assert ''.join(c['text'] for c in tl['captions'] if c['start'] < tl['beats'][ep['beats'][0]['id']]['speech_end']).replace(' ', '') == text.replace(' ', '')
    for cue in tl['captions']:
        _assert_two_lines(cue['text'], 'en', look_skin)


def test_all_material_fixture_cues_fit_two_lines(material):
    prod, tl = material
    for cue in tl['captions']:
        _assert_two_lines(cue['text'], prod.lang, prod.skin)


@pytest.mark.parametrize('look,lang', [(look, lang) for look in ('whiteboard', 'chalkboard', 'notebook', 'collage')
                                      for lang in ('en', 'es')] + [('pixel_quest', 'es'), ('mosaic', 'es')])
def test_nonmaterial_and_spanish_timelines_keep_the_default_cues(look, lang, monkeypatch):
    ep = script.build(ingest.read(FIX / ('miel_es.md' if lang == 'es' else 'tiny.md')))
    ep['look'] = look
    clips = timeline.synthetic_clips(ep, lang)
    actual = timeline.layout(ep, lang, clips)
    original_cues = captions.cues_for_beat

    def default_cues(spoken, display, language, char_time, speech_end, fits=None, **kwargs):
        return original_cues(spoken, display, language, char_time, speech_end, **kwargs)

    monkeypatch.setattr(captions, 'cues_for_beat', default_cues)
    expected = timeline.layout(ep, lang, clips)
    assert actual == expected


def test_custom_fit_check_controls_splitting_grouping_and_trailing_merge():
    text = 'Alpha beta, gamma delta, end.'
    fits = lambda text, lang: len(text.split()) <= 2
    pieces = captions.split_long(text, 'en', fits=fits)
    cues = captions.cues_for_beat(text, text, 'en', lambda p: p / 10, 3, fits=fits)
    assert ''.join(pieces) == text
    assert all(fits(piece, 'en') for piece in pieces)
    assert all(fits(cue[2], 'en') for cue in cues)
    assert ' '.join(cue[2] for cue in cues) == text


def test_material_label_fitting_measures_fallback_and_ellipsis(material):
    prod, _ = material
    text = (TEXT + ' ') * 10
    fitted = vertical._fit_ui(text, 38, prod.fonts)
    assert fitted.endswith('…')
    img = vertical._ui_line(fitted, 38, prod._soft(), prod.fonts)
    assert img.width <= vertical.TEXT_W + 6

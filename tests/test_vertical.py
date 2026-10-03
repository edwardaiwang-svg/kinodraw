"""The vertical 9:16 layout: the 16:9 board letterboxed in the middle, the section title above, big captions below."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw import pipeline, styles
from kinodraw.engine import render as renderer, timeline, vertical

FIX = Path(__file__).parent / 'fixtures'


def _prod(tmp_path, look, lang, aspect='9:16'):
    fx = 'promo_tiny.md' if look == 'collage' else ('sleep_zh.md' if lang == 'zh' else 'tiny.md')
    board = pipeline.new_project(FIX / fx, tmp_path / f'{look}-{lang}',
                                 direction={'look': look, 'story': 'promo' if look == 'collage' else None})
    tl = timeline.layout(board, lang, timeline.synthetic_clips(board, lang))
    return renderer.make_production(board, tl, lang, tmp_path / f'{look}-{lang}', aspect=aspect), tl


def _cases():
    for e in styles.looks(ready=True):
        for lang in e['languages']:
            yield e['id'], lang


def test_every_ready_look_renders_vertical():
    assert {look for look, _ in _cases()} >= {'whiteboard', 'chalkboard', 'notebook', 'collage'}
    for e in styles.looks(ready=True):
        assert '9:16' in e['aspect'], e['id']


@pytest.mark.parametrize('look,lang', list(_cases()))
def test_no_caption_ever_crosses_the_board(tmp_path, look, lang):
    prod, tl = _prod(tmp_path, look, lang)
    bx, by, bw, bh = vertical.BOARD
    assert prod.size == (1080, 1920) and (bx, bw) == (0, 1080) and abs(bh - bw * 9 / 16) < 1
    assert tl['captions']
    for c in tl['captions']:
        x, y, w, h = prod.caption_box(c['text'])
        assert y >= by + bh, (c['text'], y)                          # below the board, never over it
        assert 0 <= x and x + w <= 1080 and y + h <= 1920 - 240, c['text']   # clear of the app's buttons at the foot
        lines, size = vertical.caption_lines(c['text'], lang, prod.fonts)
        assert len(lines) <= 3 and size > 70 * bw / 1920, c['text']     # bigger than a caption on the scaled board


@pytest.mark.parametrize('look,lang', [('whiteboard', 'en'), ('chalkboard', 'zh'), ('notebook', 'en'),
                                       ('collage', 'en')])
def test_a_vertical_frame_is_the_board_with_its_title_above_and_its_caption_below(tmp_path, look, lang):
    prod, tl = _prod(tmp_path, look, lang)
    c = next(c for c in tl['captions'][2:] if c['end'] - c['start'] > .3)
    t = c['start'] + .1
    frame = np.asarray(prod.frame(t).convert('RGB'), np.int16)
    assert frame.shape == (1920, 1080, 3)
    bx, by, bw, bh = vertical.BOARD
    board = prod.prod.frame(t).convert('RGB').resize((bw, bh), Image.LANCZOS)  # the look's frame, no captions
    assert np.abs(frame[by:by + bh] - np.asarray(board, np.int16)).max() == 0
    x, y, w, h = prod.caption_box(c['text'])
    under = frame[y:y + h, x:x + w].reshape(-1, 3)
    letters = prod.caption_image(c['text'])
    assert letters.getchannel('A').getbbox()
    paper = frame[1900, 10]
    assert (np.abs(under - paper).max(-1) > 60).sum() > 2000                  # the caption is written there
    assert np.abs(frame[1900, 540] - paper).max() < 20                        # nothing else below it (paper grain)
    if look != 'collage':
        assert tuple(frame[5, 5]) == tuple(prod.skin.base)                    # on the look's paper colour


def test_the_title_above_is_the_sections_and_the_videos_at_the_ends(tmp_path):
    prod, tl = _prod(tmp_path, 'whiteboard', 'en')
    chapters = {c['id']: c for c in prod.ep['chapters']}
    sec = next(c for c in tl['chapters'] if chapters[c['id']]['kind'] == 'section')
    mid = (sec['start'] + sec['end']) / 2
    assert prod.title_at(mid)[0] is prod._title_image(('chapter', sec['id'])) and prod.title_at(mid)[1] == 1
    assert prod.title_at(.05)[0] is prod._title_image(('title',)) and prod.title_at(.05)[1] == 1   # no fade at 0
    end = tl['duration'] - .1
    assert prod.title_at(end)[0] is prod._title_image(('title',)) and prod.title_at(end)[1] == 1
    for key in (('title',), ('chapter', sec['id'])):
        img = prod._title_image(key)
        assert img.width <= 1080 and img.height <= vertical.BOARD[1] - vertical.TITLE_GAP - 200   # under the app's top bar


def test_landscape_is_the_production_itself_and_other_aspects_are_refused(tmp_path):
    prod, _ = _prod(tmp_path, 'whiteboard', 'en', aspect='16:9')
    assert isinstance(prod, renderer.Production) and not prod.vertical and prod.size == (1920, 1080)
    with pytest.raises(ValueError):
        _prod(tmp_path, 'notebook', 'en', aspect='4:3')


def test_captions_wrap_into_even_lines():
    text = 'Plants turn sunlight, water and air into the sugar they live on, and give us oxygen'
    lines, size = vertical.caption_lines(text, 'en')
    assert 1 < len(lines) <= 3
    widths = [vertical.ink.font('en_caption', size).getlength(l) for l in lines]
    assert max(widths) <= vertical.TEXT_W and max(widths) - min(widths) < 400
    zh, _ = vertical.caption_lines('植物利用阳光、水和空气制造养分，同时释放出我们呼吸的氧气，这个过程叫做光合作用。', 'zh')
    assert all(not l[:1] in '，。、' for l in zh)


URL_LINE = 'Visit https://www.example.com/products/documentation/ for details.'


def _ink_columns(img):
    """(left, right) of the drawn pixels of an RGBA image."""
    box = img.getchannel('A').getbbox()
    return box[0], box[2]


def test_a_caption_with_a_long_web_address_fits_the_width_and_keeps_every_word(tmp_path):
    script = tmp_path / 'url.md'
    script.write_text(f'# Docs\n\n{URL_LINE} The guide has every step.\n', encoding='utf-8')
    board = pipeline.new_project(script, tmp_path / 'p', direction={'look': 'whiteboard'})
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = renderer.make_production(board, tl, 'en', tmp_path / 'p', aspect='9:16')
    assert any('example.com' in c['text'] for c in tl['captions'])
    for c in tl['captions']:
        lines, size = vertical.caption_lines(c['text'], 'en', prod.fonts)
        f = vertical.ink.font('en_caption', size, prod.fonts)
        assert all(f.getlength(l) <= vertical.TEXT_W for l in lines), (c['text'], lines)
        assert ''.join(lines).replace(' ', '') == c['text'].replace(' ', ''), lines     # no word lost
        x, y, w, h = prod.caption_box(c['text'])
        assert 0 <= x and x + w <= 1080 and y + h <= 1920 - 240, (c['text'], (x, y, w, h))
        left, right = _ink_columns(prod.caption_image(c['text']))
        assert x + left >= 40 and x + right <= 1040, c['text']


@pytest.mark.parametrize('lang,text', [
    ('en', URL_LINE),
    ('en', ' '.join(['Plants turn sunlight, water and air into sugar.'] * 6)),
    ('zh', '请访问 https://www.example.com/products/documentation/ 了解详情，' * 3),
])
def test_no_caption_ever_loses_words_or_runs_past_the_side_margins(lang, text):
    lines, size = vertical.caption_lines(text, lang)
    f = vertical.ink.font('en_caption' if lang == 'en' else 'zh_caption', size)
    assert ''.join(lines).replace(' ', '') == text.replace(' ', ''), lines
    assert all(f.getlength(l) <= vertical.TEXT_W for l in lines), lines
    assert size >= 36                                                     # still easy to read on a phone
    img = vertical.caption_image(text, lang)
    assert img.width <= vertical.TEXT_W + 40
    assert vertical.BOARD[1] + vertical.BOARD[3] + vertical.CAP_GAP + img.height <= 1920 - 240   # clear of the buttons


@pytest.mark.parametrize('key', ['title', 'chapter'])
def test_a_long_title_never_runs_off_the_frame(tmp_path, key):
    prod, tl = _prod(tmp_path, 'notebook', 'en')
    long = 'https://www.example.com/products/enterprise-collaboration-platform'
    if key == 'title':
        prod.ep['title'] = {'en': long}
        img = prod._title_image(('title',))
    else:
        ch = next(c for c in prod.ep['chapters'] if c['kind'] == 'section')
        ch['title'] = {'en': long}
        ch['label'] = {'en': 'Part one of the internationalization and telecommunications onboarding walkthrough'}
        img = prod._title_image(('chapter', ch['id']))
    left, right = _ink_columns(img)
    assert img.width <= 1080 and left >= 40 and right <= 1040, (left, right)
    assert img.height <= vertical.BOARD[1] - vertical.TITLE_GAP - 200


def test_a_caption_with_one_enormous_word_shrinks_until_it_fits_above_the_buttons():
    text = 'https://example.com/' + 'a' * 700
    lines, size = vertical.caption_lines(text, 'en')
    f = vertical.ink.font('en_caption', size)
    assert ''.join(lines) == text, lines                                  # nothing cut off
    assert all(f.getlength(l) <= vertical.TEXT_W for l in lines), lines
    img = vertical.caption_image(text, 'en')
    assert vertical.BOARD[1] + vertical.BOARD[3] + vertical.CAP_GAP + img.height <= 1920 - 240


@pytest.mark.parametrize('key', ['title', 'chapter'])
def test_a_title_with_one_enormous_word_stays_under_the_top_bar(tmp_path, key):
    prod, tl = _prod(tmp_path, 'notebook', 'en')
    long = 'https://example.com/' + 'a' * 500
    if key == 'title':
        prod.ep['title'] = {'en': long}
        img = prod._title_image(('title',))
    else:
        ch = next(c for c in prod.ep['chapters'] if c['kind'] == 'section')
        ch['title'] = {'en': long}
        img = prod._title_image(('chapter', ch['id']))
    left, right = _ink_columns(img)
    assert left >= 40 and right <= 1040, (left, right)
    assert img.height <= vertical.BOARD[1] - vertical.TITLE_GAP - 200

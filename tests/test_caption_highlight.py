"""The caption on screen colours the word being said, timed by the narration's character times."""
import json

import numpy as np
from PIL import Image

from kinodraw import pipeline
from kinodraw.engine import captions, ink, render, scenes, skin, timeline, vertical
from kinodraw.engine.board import Layout
from pathlib import Path

FIX = Path(__file__).parent / 'fixtures'
TEXT = 'It was mostly just to keep the honey safe.'


def _accent_columns(image, accent, plain=None):
    """Columns holding the accent colour (only where the image differs from ``plain``, when given)."""
    a = np.asarray(image.convert('RGBA'), np.int16)
    hit = (np.abs(a[..., :3] - np.array(accent)).sum(-1) < 30) & (a[..., 3] > 200)
    if plain is not None:
        hit &= (a != np.asarray(plain.convert('RGBA'), np.int16)).any(-1)
    return np.nonzero(hit.any(0))[0]


def test_word_times_follow_the_narration_character_times():
    # char_time(pos) = pos / 10 s: each word is said when its first letter is heard
    (start, end, text, words), = captions.cues_for_beat(TEXT, TEXT, 'en', lambda p: p / 10, 5, words=True)
    starts = [a for a, _ in captions.word_spans(text, 'en')]
    assert words == [max(start, p / 10) for p in starts]
    cue = {'start': start, 'end': end, 'text': text, 'words': words}
    said = [text[slice(*captions.word_spans(text, 'en')[captions.word_at(words, t)])] for t in (0., .8, 1.5, 2., 4.)]
    assert said == ['It', 'mostly', 'just', 'to', 'safe.']
    assert captions.cues_for_beat(TEXT, TEXT, 'en', lambda p: p / 10, 5) == [(start, end, text)]


def test_chinese_and_spanish_words():
    zh = '我们每天晚上睡觉，大脑在整理 DNA 数据。'
    assert [zh[a:b] for a, b in captions.word_spans(zh, 'zh')][:6] == ['我', '们', '每', '天', '晚', '上']
    assert [zh[a:b] for a, b in captions.word_spans(zh, 'zh')][6:8] == ['睡', '觉，']
    assert 'DNA' in [zh[a:b] for a, b in captions.word_spans(zh, 'zh')]
    es = '¿Sabías que la miel — bien guardada — dura siglos?'
    assert [es[a:b] for a, b in captions.word_spans(es, 'es')] == [
        '¿Sabías', 'que', 'la', 'miel —', 'bien', 'guardada —', 'dura', 'siglos?']


def test_layout_stores_word_times_and_old_timelines_get_the_same(tmp_path):
    board = pipeline.new_project(FIX / 'tiny.md', tmp_path / 'p')
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    for c in tl['captions']:
        assert len(c['words']) == len(captions.word_spans(c['text'], 'en'))
        assert c['words'] == sorted(c['words']) and c['start'] <= c['words'][0] and c['words'][-1] < c['end']
    old = json.loads(json.dumps(tl))
    for c in old['captions']:
        del c['words']
    saved = json.dumps(old)
    assert timeline.word_times(board, old, 'en') == [c['words'] for c in tl['captions']]
    assert json.dumps(old) == saved                                   # the saved timeline is left as it was


def _drawn_caption(look, cue, t, monkeypatch):
    p = object.__new__(render.Production)
    p.lang, p.skin = 'en', skin.for_look(look)
    p.ep = {'chapters': []}
    p.ctx = scenes.Ctx(p.ep, 'en', {}, Layout(), skin=p.skin)
    p.cap_starts, p.tl = [cue['start']], {'captions': [cue]}
    pasted = []
    monkeypatch.setattr(ink, 'paste', lambda frame, img, x, y: pasted.append(img))
    p._caption(Image.new('RGBA', p.size), t)
    return pasted[0]


def test_the_word_being_said_changes_colour_inside_one_phrase(monkeypatch):
    (start, end, text, words), = captions.cues_for_beat(TEXT, TEXT, 'en', lambda p: p / 10, 5, words=True)
    cue = {'start': start, 'end': end, 'text': text, 'words': words}
    for look in ('whiteboard', 'chalkboard', 'pixel_quest', 'mosaic'):
        sk = skin.for_look(look)
        accent = captions.highlight_color(tuple(sk.caption_accent), tuple(sk.caption), tuple(sk.caption_edge))
        mostly, just = (_drawn_caption(look, cue, t, monkeypatch) for t in (.8, 1.5))
        plain = sk.caption_image(text, 'en')
        assert mostly.size == just.size == plain.size, look  # same layout: only the colour changes
        a, b = _accent_columns(mostly, accent, plain), _accent_columns(just, accent, plain)
        assert len(a) and len(b), look
        assert a.max() < b.min(), look                     # "mostly" is lit first, then "just" to its right
    no_words = _drawn_caption('whiteboard', {k: v for k, v in cue.items() if k != 'words'}, .8, monkeypatch)
    assert not len(_accent_columns(no_words, skin.for_look('whiteboard').caption_accent))


def test_portrait_and_hybrid_palette_captions_highlight():
    lit = vertical.caption_image(TEXT, 'en')
    accent = captions.highlight_color((228, 171, 85), (18, 18, 18), (255, 255, 255))
    frame = type('F', (), {'collage': True, 'skin': None, 'native': False, 'lang': 'en', 'fonts': ink.FONTS,
                           'prod': type('P', (), {'caption_accent': (228, 171, 85)})()})()
    image = vertical.PortraitFrame.caption_image(frame, TEXT, 2)
    assert image.size == lit.size and len(_accent_columns(image, accent))
    # a dark palette: its light ink in a thin outline of its background, the word in its own accent
    dark = skin.WHITEBOARD.caption_image(TEXT, 'en', 2, (228, 171, 85), ((231, 229, 216), (12, 12, 12), 4))
    assert len(_accent_columns(dark, (228, 171, 85)))
    assert captions.highlight_color((228, 171, 85), (231, 229, 216), (12, 12, 12)) == (228, 171, 85)
    assert skin.contrast(accent, (255, 255, 255)) >= 4.5

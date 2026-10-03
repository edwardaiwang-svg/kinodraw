"""The stick look's scene composer on rules-director storyboards (synthetic reading-rate timing, no voice model):
every beat is acted out, shots cut cleanly end to end, nothing on screen overlaps, and Chinese renders."""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageFont

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.engine import timeline as tl
from kinodraw.engine.stick import compose, cues, rig, text
from kinodraw.engine.stick.render import StickProduction

FIX = Path(__file__).parent / 'fixtures'


def build(name, seed=0):
    board = script.build(ingest.read(FIX / name))
    lang = board['lang']
    board = RulesDirector(lang).direct(board)
    timing = tl.layout(board, lang, tl.synthetic_clips(board, lang), pauses={})
    return StickProduction(board, timing, lang, None, seed=seed)


@lru_cache(maxsize=None)
def built(name):
    """A production shared by tests that only read it."""
    return build(name)


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


def test_a_true_crime_narrator_never_grins():
    """Grim words ("a bomb", "the ransom") make the narrator look worried or shocked, and a video that keeps talking
    about crime is told with a straight face: no smile or grin on a figure that stands, talks, points or holds."""
    p = built('stick_hijack.md')
    assert p.composer.tone == 'grim'
    faces = {}
    for s in p.shots:
        for it in s.items:
            fig = getattr(it, 'fig', None)
            if fig is not None and fig.pose in rig.CALM_POSES:
                eyes, brows, mouth = fig.face or rig.FACES[fig.pose]
                assert mouth not in ('smile', 'grin'), f'{fig.pose} grins at "{s.words}"'
                faces[s.words] = fig.face
    bomb = next(f for w, f in faces.items() if w.startswith('It said he had a bomb'))
    assert bomb == compose.SHOCKED
    assert any(f == compose.WORRIED for w, f in faces.items() if 'unsolved hijacking' in w)


def test_a_cheerful_topic_keeps_its_smile():
    p = build('printing_press.md')
    assert p.composer.tone == 'bright'
    assert p.composer.calm_face('Printing let new ideas move faster.') is None


def test_big_numbers_keep_their_currency_and_dates_stay_whole():
    p = built('stick_hijack.md')
    c = p.composer
    said = {}
    for b in c.beats:
        if b['kind'] == 'narration':
            for t, _, sent in c.sentence_times(b):
                card = c.spoken_number([b], t, t + 6)
                if card:
                    said[sent] = card.data
    money = next(d for s, d in said.items() if s.startswith('A few hours later'))
    assert money['value'] == '$200,000'
    assert next(d for s, d in said.items() if s.startswith('On November'))['value'] == 'November 24, 1971'
    # a director's stat on the day of a date shows the date, not "24" over an unrelated noun
    disp = 'On November 24, 1971, a quiet man in a dark suit bought a plane ticket.'
    assert compose.stat_label('24', 'quiet man', disp, 'en') == ('November 24, 1971', '')
    assert compose.stat_label('476', 'last emperor', 'Then, in the year 476, the last emperor was pushed off his '
                                                     'throne.', 'en') == ('476', 'last emperor')
    assert compose.stat_label('24', 'rotting bills', 'In 1980 he found 24 bags and 9 rotting bills.', 'en') == \
        ('24', '')                                           # read past another number: not this number's label
    found = [m.group(0) for m in compose.NUMBER['en'].finditer('found $5,800 and about $2.5 million in gold')]
    assert found == ['$5,800', '$2.5 million']


@pytest.mark.parametrize('value,label,disp,lang,shown', [
    ('300', '米', '这座塔高300米。', 'zh', ('300米', '')),
    ('102', '岁', '他一直活到了102岁。', 'zh', ('102岁', '')),
    ('80', '元', '这本书卖了80元。', 'zh', ('80元', '')),
    ('50', '元钱', '一张票当时要50元钱。', 'zh', ('50元', '')),
    ('250', '万美元', '这座城市花了250万美元修新的大门。', 'zh', ('250万美元', '')),
    ('500', 'dollars', 'The new gate cost 500 dollars.', 'en', ('$500', '')),
    ('20', 'dollar bills', 'He found 20 dollar bills in the sand.', 'en', ('$20', 'bills')),
])
def test_a_directors_stat_keeps_its_unit(value, label, disp, lang, shown):
    assert compose.stat_label(value, label, disp, lang) == shown


def test_a_spoken_dollar_amount_gets_its_sign():
    p = build('stick_hijack.md')
    c = p.composer
    beat = dict(c.beats[0], display={'en': 'He found 20 dollar bills in the sand.'}, id=c.beats[0]['id'])
    c.bt = dict(c.bt)
    card = c.spoken_number([beat], c.bt[beat['id']]['start'] - 1, c.bt[beat['id']]['start'] + 30)
    assert card.data == {'value': '$20', 'label': 'bills'}


def test_pictures_are_there_at_the_cut(prod):
    """The Paint way: a shot's pictures, numbers and words are on screen from its first frame, so the figure
    never points at empty space; only the red marks are drawn as their words are said."""
    for s in prod.shots:
        if s.layout not in ('left', 'right', 'close', 'crowd', 'grid'):
            continue
        late = [(i.kind, round(i.t0 - s.start, 2)) for i in s.items if i.kind != 'mark' and i.t0 > s.start + 1e-6]
        assert not late, f'{s.layout} shot at {s.start:.1f}s: {late}'


def test_list_and_takeaway_are_there_at_the_cut(prod):
    """The figure points at the agenda's first row and at the takeaway's words from the first frame."""
    for s in prod.shots:
        if s.layout == 'agenda':
            assert min(i.t0 for i in s.items if i.kind in ('panel', 'label')) <= s.start + 1e-6
        if s.layout == 'take':
            assert all(i.t0 <= s.start + 1e-6 for i in s.items if i.kind == 'text'), f'take at {s.start:.1f}s'


def figure_only_share(p):
    """Share of narration time that shows the figure and nothing else (no picture, number or words)."""
    total = bare = 0
    for t in np.arange(0, p.tl['duration'], .1):
        _, s = p.shot_at(t)
        if s.layout not in ('left', 'right', 'solo', 'close', 'crowd', 'grid', 'timeline'):
            continue
        total += 1
        bare += not any(i.visible(t) and i.kind not in ('ground', 'tab', 'mark', 'figure') for i in s.items)
    return bare / total


@pytest.mark.parametrize('name', ['stick_hijack.md', 'stick_bias.md', 'stick_wall.md', 'stick_wall_zh.md'])
def test_a_figure_is_rarely_alone_on_white(name):
    """The Paint grammar is a figure plus a prop: a sentence the storyboard left bare gets the name it gives, a
    number it says, a picture for its words or the picture still in play."""
    assert figure_only_share(built(name)) <= .1


def test_what_fills_a_bare_sentence():
    from kinodraw.engine.stick import fill
    assert fill.term('Psychologists call this the negativity bias.', 'en') == 'Negativity bias'
    assert fill.term('Finally, a general named Odoacer removed the boy emperor.', 'en') == 'Odoacer'
    assert fill.term('They called it a day.', 'en') is None
    assert fill.term('这叫做散射。', 'zh') == '散射'
    assert fill.number_word('Imagine you get ten compliments and one insult today.', 'en')[1:] == ('10', 'compliments')
    assert fill.number_word('Two of them left.', 'en') is None
    p = built('stick_bias.md')
    ch = next(c['id'] for c in p.board['chapters'] if c['kind'] == 'section')
    assert p.composer.pictures.find('They are just tuned for a world with lions.', ch)[0] == 'fl_lion'


@pytest.mark.parametrize('disp,value', [('那家公司亏了12.5亿美元。', '12.5亿美元'), ('大约有12.5万人参加了抗议。', '12.5万'),
                                        ('最终确定下来的结果是12.5%。', '12.5%'), ('湖里有400亿立方米的水。', '400亿立方米')])
def test_a_spoken_chinese_number_keeps_its_decimal_and_unit(disp, value):
    c = build('sleep_zh.md').composer
    beat = dict(c.beats[0], display={'zh': disp})
    card = c.spoken_number([beat], c.bt[beat['id']]['start'] - 1, c.bt[beat['id']]['start'] + 30)
    assert card.data['value'] == value


def test_a_spoken_english_unit_keeps_both_words():
    c = build('stick_hijack.md').composer
    beat = dict(c.beats[0], display={'en': 'Its lake holds 40 cubic kilometers of water.'})
    card = c.spoken_number([beat], c.bt[beat['id']]['start'] - 1, c.bt[beat['id']]['start'] + 30)
    assert card.data == {'value': '40', 'label': 'cubic kilometers'}


@pytest.mark.parametrize('name', ['printing_press.md', 'sky_blue.md', 'sleep_zh.md', 'stick_hijack.md', 'bicycle.md',
                                  'stick_bridge.md'])
def test_two_crowd_shots_never_follow_each_other(name):
    shots = built(name).shots
    assert not [s.start for s, n in zip(shots, shots[1:]) if s.layout == n.layout == 'crowd']

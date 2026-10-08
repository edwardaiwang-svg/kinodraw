"""Data cards on screen (engine/data_cards.py): the exact text, the clock, the safe area; content QA counts them."""
import numpy as np
from PIL import Image, ImageDraw

from kinodraw import figures, ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import data_cards
from kinodraw.engine.skin import Skin
from kinodraw.qa import content

W, H = 1920, 1080


def _drawn(monkeypatch, sentence, look='board'):
    texts = []
    real = data_cards._text

    def spy(d, xy, text, f, fill, anchor='la'):
        texts.append(text)
        real(d, xy, text, f, fill, anchor)
    monkeypatch.setattr(data_cards, '_text', spy)
    card = figures.cards(sentence)[0]
    img = data_cards.card_image(card, data_cards._Look(look, Skin(), 'en', 1.), W, H)
    return texts, img


def test_each_card_draws_the_script_text_exactly(monkeypatch):
    for sentence, wanted in [
            ('Revenue hit $4.2M, up 18% from $3.56M last year.', {'$4.2M', '$3.56M', '18%', 'last year'}),
            ('Just $3.50 each, until they are gone.', {'$3.50', 'each'}),
            ('About 2,300 cars a day used the old bridge.', {'2,300 cars', 'About'}),
            ('Fresh rolls every Saturday at 7 a.m.', {'Every Saturday', '7 a.m.'}),
            ('A new entry appears with a 6-digit code, like 482 913.', {'482 913'}),
            ('Our plan costs $12 a month vs $20 for the old one.', {'$12', '$20'}),
            ('3 kids 2 grandkids', {'3 kids', '2 grandkids'})]:
        for look in ('board', 'clean'):
            texts, img = _drawn(monkeypatch, sentence, look)
            assert wanted <= set(texts), (sentence, texts)
            assert img.width <= data_cards.MAX_W * W + 12 and img.height <= (data_cards.CAPTION_TOP -
                                                                             data_cards.TOP) * H


def test_a_counter_counts_up_in_the_script_format_and_ends_exact():
    assert data_cards._counted('3,100 tons', 1.) == '3,100 tons'
    assert data_cards._counted('3,100 tons', 0.) == '0 tons'
    half = data_cards._counted('3,100 tons', .5)
    assert half.endswith(' tons') and ',' in half
    assert data_cards._counted('$4.2M', .5).startswith('$') and data_cards._counted('$4.2M', .5).endswith('M')


def _episode(text, spoken):
    beat = {'id': 'b001', 'kind': 'narration', 'chapter': 'c1', 'display': {'en': text}, 'spoken': {'en': spoken}}
    tline = {'beats': {'b001': {'start': 10., 'end': 16., 'char_times': [i * .05 for i in range(len(spoken))]}},
             'end_card': {'start': 30.}}
    return {'beats': [beat]}, tline


def test_a_card_comes_on_with_its_words_and_stays_until_its_sentence_ends():
    text = 'Hello there friends. Revenue hit $4.2M this year.'
    spoken = 'Hello there friends. Revenue hit four point two million dollars this year.'
    ep, tline = _episode(text, spoken)
    [(start, end, card, bid)] = data_cards.entries(ep, tline, 'en')
    assert card.kind == 'number' and bid == 'b001'
    assert abs(start - (10 + spoken.index('four') * .05 - .1)) < 1e-6
    assert end >= 10 + (len(spoken) - 1) * .05 and end - start >= data_cards.MIN_HOLD


class _Host:
    """The frame the viewer sees: a picture on the right half of the page."""

    def __init__(self):
        self.calls = 0

    def frame(self, t):
        self.calls += 1
        img = Image.new('RGBA', (W, H), (246, 244, 238, 255))
        ImageDraw.Draw(img).rectangle((W * .6, H * .15, W * .97, H * .7), fill=(200, 60, 40, 255))
        return img


def test_the_card_stays_in_the_safe_area_beside_the_picture():
    ep, tline = _episode('Members kept 3,100 tons of food scraps out of the landfill.',
                         'Members kept three thousand one hundred tons of food scraps out of the landfill.')
    cards = data_cards.build(ep, tline, 'en', Skin(), (W, H))
    start, end, _, _ = cards.entries[0]
    host = _Host()
    for clean in (False, True):
        cards._places.clear()
        blank = Image.new('RGBA', (W, H), (246, 244, 238, 255))
        frame = blank.copy()
        cards.paint(frame, start + 1.5, clean, host)
        diff = np.abs(np.asarray(frame, dtype=int) - np.asarray(blank, dtype=int)).max(axis=2) > 0
        ys, xs = np.nonzero(diff)
        assert len(xs)
        assert ys.min() >= data_cards.TOP * H - 1 and ys.max() <= data_cards.CAPTION_TOP * H + 1
        assert xs.max() < W * .6, 'the card covers the picture'
        assert xs.min() >= 0 and xs.max() < W
    assert host.calls == 6                         # measured once per card (three moments), never per frame
    frame = Image.new('RGBA', (W, H), (246, 244, 238, 255))
    cards.paint(frame, end + .1, False, host)
    assert frame.getextrema()[0] == (246, 246)    # gone after its window


def test_content_qa_counts_a_sentence_with_a_card_as_shown_by_it():
    board = script.build(ingest.read('# Our Year\n\nRevenue hit $4.2M this year, up from $3.1M last year. '
                                     'We planted trees in the park.'), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    assert plan['storyboard']['genre'] != 'story'
    for scene in plan['scenes']:
        scene.update(treatment='motion', text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]},
                     elements=[{'kind': 'picture', 'ref': 'fl_deciduous_tree'}])
    found = content.lines(plan, board)
    revenue = next(line for line in found if 'Revenue' in line.text)
    assert revenue.numeric and revenue.by == 'card' and revenue.shown
    assert content.check(plan, board)['stats']['numbers_as_icons'] == 0


def test_a_whiteboard_page_that_writes_the_figure_gets_no_card_over_it():
    from types import SimpleNamespace

    from kinodraw.engine import ink
    ep, tline = _episode('Members kept 3,100 tons of food scraps out of the landfill.',
                         'Members kept three thousand one hundred tons of food scraps out of the landfill.')
    text = ink.TextDrawing.__new__(ink.TextDrawing)
    text.lines = ['3,100 tons of', 'food scraps']
    written = [SimpleNamespace(drawing=text, trigger=10.5)]
    cards = data_cards.build(ep, tline, 'en', Skin(), (W, H), written)
    assert cards.on_board == {0}
    start = cards.entries[0][0]
    board = SimpleNamespace(data_cards=cards, frame=_Host().frame)     # the whiteboard production itself
    frame = Image.new('RGBA', (W, H), (246, 244, 238, 255))
    cards.paint(frame, start + 1.5, False, board)
    assert frame.getextrema()[0] == (246, 246)
    cards.paint(frame, start + 1.5, True, _Host())                     # a motion page over the same beat
    assert frame.getextrema()[0] != (246, 246)
    assert not data_cards.build(ep, tline, 'en', Skin(), (W, H)).on_board


class _DeviceHost(_Host):
    """A production that draws device screens (engine/ui_screens moments) over its page."""

    def __init__(self, moments, vertical=False):
        super().__init__()
        self.ui_moments, self.vertical = moments, vertical


def _painted(cards, t, host):
    blank = Image.new('RGBA', (W, H), (246, 244, 238, 255))
    frame = blank.copy()
    cards.paint(frame, t, False, host)
    return frame.getextrema()[0] != (246, 246)


def test_no_card_for_a_figure_a_device_screen_draws_and_none_over_a_live_device():
    ep, tline = _episode('A new entry appears with a code, like 482 913.',
                         'A new entry appears with a code, like four eight two, nine one three.')
    cards = data_cards.build(ep, tline, 'en', Skin(), (W, H))
    start, end, card, _ = cards.entries[0]
    assert card.value == '482 913'
    t = start + .5
    phone = {'start': end - .5, 'end': end + 3, 'kind': 'app', 'app': 'Authenticator',
             'elements': [{'label': 'Harbor Mail', 'value': '482 913'}]}
    assert not _painted(cards, t, _DeviceHost([phone])), 'the phone already shows the code: no second copy'
    other = {'start': t - 1, 'end': t + .5, 'kind': 'app', 'app': 'Mail', 'elements': [{'label': 'Inbox'}]}
    assert not _painted(cards, t, _DeviceHost([other])), 'a card over a live device screen'
    assert _painted(cards, t + 1, _DeviceHost([other]))           # after that screen, the card comes back
    assert _painted(cards, t, _DeviceHost([phone, other], vertical=True))   # a portrait frame draws no device
    assert _painted(cards, t, _Host())

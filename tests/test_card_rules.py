"""Data card rules (engine/data_cards.py, figures.py): whole and inside the frame, clear of other pictures, gone with
their sentence, toned by their words, never counting through unsaid numbers, quoting the script exactly; content QA
flags a card that shows words the script does not say. Every example is invented."""
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from kinodraw import figures, ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import data_cards, timeline
from kinodraw.engine.skin import Skin
from kinodraw.qa import content

W, H = 1920, 1080
PAPER = (246, 244, 238, 255)


def _episode(*beats):
    """Beats of (display, spoken), one after another with a .4 s pause; 50 ms per spoken character."""
    ep, tl, t = [], {'beats': {}, 'end_card': {'start': 300.}}, 10.
    for k, (text, spoken) in enumerate(beats, 1):
        bid = f'b{k:03d}'
        ep.append({'id': bid, 'kind': 'narration', 'chapter': 'c1', 'display': {'en': text}, 'spoken': {'en': spoken}})
        end = t + len(spoken) * .05
        tl['beats'][bid] = {'start': t, 'end': end, 'char_times': [i * .05 for i in range(len(spoken))]}
        t = end + .4
    return {'beats': ep}, tl


class _Host:
    """The frame the viewer sees: paper with pictures at the given boxes (shares of the frame)."""

    def __init__(self, *boxes):
        self.boxes = boxes

    def frame(self, t):
        img = Image.new('RGBA', (W, H), PAPER)
        for x0, y0, x1, y1 in self.boxes:
            ImageDraw.Draw(img).rectangle((W * x0, H * y0, W * x1, H * y1), fill=(200, 60, 40, 255))
        return img


def _painted_box(cards, t, host, clean=False):
    frame = Image.new('RGBA', (W, H), PAPER)
    cards.paint(frame, t, clean, host)
    diff = np.abs(np.asarray(frame, dtype=int) - np.array(PAPER)).max(axis=2) > 0
    ys, xs = np.nonzero(diff)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


def test_a_card_is_whole_and_inside_the_safe_area_from_its_first_frame():
    ep, tl = _episode(('Our garden grew 3,400 pounds of squash.', 'Our garden grew three thousand four hundred pounds '
                                                                   'of squash.'))
    cards = data_cards.build(ep, tl, 'en', Skin(), (W, H))
    start, end, _, _ = cards.entries[0]
    host = _Host((.08, .15, .45, .7))
    for clean in (False, True):
        cards._places.clear()
        held = _painted_box(cards, start + 1.6, host, clean)
        entry = _painted_box(cards, start + .12, host, clean)
        assert entry is not None and held is not None
        # on entry the whole card is there (faint), never a slice wiped in through its own edge
        assert entry[2] - entry[0] >= (held[2] - held[0]) * .97, (entry, held)
        for box in (entry, held):
            assert box[0] >= data_cards.SIDE * W - 1 and box[2] <= (1 - data_cards.SIDE) * W + 1
            assert box[1] >= data_cards.TOP * H - 1 and box[3] <= data_cards.CAPTION_TOP * H + 1
    # a spot partly off the frame (a stale or shrunk placement) is moved inside before it is drawn
    cards._places = {0: ((W - 120, H * .5), 1.)}
    box = _painted_box(cards, start + 1.6, host)
    assert box[2] <= (1 - data_cards.SIDE) * W + 1


def test_a_card_leaves_with_its_sentence():
    # the next sentence of the same beat
    text = 'Warm rolls are just $3.50 each. The shop is on the corner of Elm and Fifth.'
    spoken = 'Warm rolls are just three dollars fifty each. The shop is on the corner of Elm and Fifth.'
    ep, tl = _episode((text, spoken))
    [(start, end, card, _)] = data_cards.entries(ep, tl, 'en')
    assert card.kind == 'price'
    assert end <= 10 + spoken.index('The shop') * .05, 'the price tag stays over the next sentence'
    # the next beat's picture
    ep, tl = _episode(('Our uncle turns 60!', 'Our uncle turns sixty!'), ('He grew up by the sea.', 'He grew up by '
                                                                                              'the sea.'))
    [(start, end, card, _)] = data_cards.entries(ep, tl, 'en')
    assert end <= tl['beats']['b002']['start'], 'the card stays over the next beat'
    assert end > 10 + len('Our uncle turns sixty') * .05      # ... but it is up until its own sentence is said


def test_a_card_keeps_clear_of_pictures_it_is_not_about():
    ep, tl = _episode(('That is about the weight of 1,200 bikes.', 'That is about the weight of one thousand two '
                                                                     'hundred bikes.'))
    cards = data_cards.build(ep, tl, 'en', Skin(), (W, H))
    start = cards.entries[0][0]
    # one icon a little right of centre: the card has room on either side, and takes the side with air
    icons = ((.45, .3, .62, .7),)
    box = _painted_box(cards, start + 1.6, _Host(*icons))
    gap = min(max(icon[0] * W - box[2], box[0] - icon[2] * W, icon[1] * H - box[3], box[1] - icon[3] * H)
              for icon in icons)
    assert gap >= 40, f'the card sits against an icon ({gap} px): it reads as that icon\'s label'


def test_bad_news_is_a_warning_and_growth_gets_a_plus():
    over = figures.cards('Fuel cost us 9% more than we planned.')[0]
    assert over.tone == 'warn' and figures.shown(over)[0] == '9%'
    assert figures.cards('The parts arrived late by 6 days.')[0].tone == 'warn'
    grew = figures.cards('Sign-ups grew 12% this spring.')[0]
    assert grew.tone == '' and grew.direction == 'up' and '+12%' in figures.shown(grew)
    change = figures.cards('Visits rose to 5,000, up 25% from 4,000 last spring.')[0]
    assert change.kind == 'change' and '+25%' in figures.shown(change)
    fell = figures.cards('Sales fell 7% this month.')[0]
    assert fell.direction == 'down' and '7%' in figures.shown(fell)

    def amber(card):
        img = np.asarray(data_cards.card_image(card, data_cards._Look('clean', Skin(), 'en', 1.), W, H))
        return int((np.abs(img[..., :3].astype(int) - np.array(data_cards.WARN)).max(axis=2) < 30).sum())
    assert amber(over) > 400 and amber(grew) == 0


def test_a_counter_shows_only_the_stated_value():
    assert data_cards._counted('3,100 tons', 0.) == data_cards._counted('3,100 tons', .4) == '3,100 tons'
    card = figures.cards('Volunteers planted 1,800 trees.')[0]
    assert card.kind == 'counter'
    look = data_cards._Look('board', Skin(), 'en', 1.)
    assert data_cards.card_image(card, look, W, H, .3).tobytes() == data_cards.card_image(card, look, W, H).tobytes()


def test_period_labels_come_from_the_text():
    card = figures.cards('Members went from 900 in 2024 to 1,300 in 2025.')[0]
    assert [(t, label) for t, label, _ in card.items] == [('900', '2024'), ('1,300', '2025')]
    card = figures.cards('Dues hit $8,400 for the quarter, up 5% from $8,000 last year.')[0]
    assert [label for _, label, _ in card.items] == ['last year', 'the quarter']
    card = figures.cards('Sales went from 40 units to 95 units in a year.')[0]
    assert all(label in ('', 'a year') for _, label, _ in card.items) and not figures.unquoted(
        card, 'Sales went from 40 units to 95 units in a year.')


@pytest.mark.parametrize('sentence,rows,where', [
    ('Open house Sat 10–2 PM.', ['Sat', '10–2 PM'], ''),
    ('Doors open at 4 PM. Bring a chair.', ['4 PM'], ''),
    ('Pickup is at 9 a.m. at 14 Birch Rd.', ['9 a.m.'], '14 Birch Rd.'),
])
def test_event_cards_quote_times_and_addresses_exactly(sentence, rows, where):
    card = figures.cards(sentence)[0]
    assert card.kind == 'event' and card.rows == rows and card.where == where
    assert not figures.unquoted(card, sentence)


def test_cards_quote_the_script_exactly():
    card = figures.cards('The late fee is $0.')[0]
    assert (card.value, card.label) == ('$0', 'late fee')
    assert figures.cards('Entry is $5 and parking is $0.')[0].rows == ['Entry is $5', 'parking is $0']
    card = figures.cards('2 cups · 350°F · 25 min · serves 6')[0]
    assert card.kind == 'stat' and card.rows == ['2 cups', '350°F', '25 min', 'serves 6']
    assert figures.cards('Bake 1 hr / 400°F / 8 slices.')[0].rows == ['Bake 1 hr', '400°F', '8 slices']
    # a number that counts nothing the sentence names is no chip ("kids 6 and up")
    card = figures.cards('Swim lessons run 2–3 days a week for kids 6 and up.')[0]
    assert '6' not in figures.shown(card) and card.value == '2–3 days'
    # a label never carries a bracket of the source
    assert figures.shown(figures.cards('Save up to 15%] today.')[0]) == ['up to', '15%']
    for sentence in ('Open house Sat 10–2 PM.', '2 cups · 350°F · 25 min · serves 6', 'The late fee is $0.',
                     'Swim lessons run 2–3 days a week for kids 6 and up.', 'Save up to 15%] today.'):
        assert all(not figures.unquoted(c, sentence) for c in figures.cards(sentence)), sentence


def test_an_id_is_a_label_never_a_figure():
    for sentence in ('Ticket TK-4471 was closed.', 'Ticket 4471 was closed yesterday.', 'Your order 58213 ships today.',
                     'Invoice #3017 is paid.', 'Case no. 99812 is now open.', 'Use promo code SPRING-2040 at checkout.'):
        assert figures.cards(sentence) == [], sentence
    card = figures.cards('Order 7781 shipped 3,000 units.')[0]
    assert figures.shown(card) == ['3,000 units']
    # a record word before a percentage or a rate is no ID
    assert figures.shown(figures.cards('Members claim 40% savings.')[0]) == ['40%', 'savings']
    card = figures.cards('Plans start at $12 / month.')[0]
    assert card.kind == 'price' and not figures.unquoted(card, 'Plans start at $12 / month.')


def test_content_qa_flags_card_text_the_script_does_not_say():
    said = 'Doors open at 4 PM. Members went from 900 to 1,300.'
    assert figures.unquoted(figures.Card('event', 0, 0, rows=['4 PM.']), said) == ['4 PM.']
    assert figures.unquoted(figures.Card('change', 0, 0, items=[('900', 'before', 900.), ('1,300', 'now', 1300.)]),
                            said) == ['before', 'now']
    assert figures.unquoted(figures.Card('stat', 0, 0, rows=['350 °F ·']), '350 °F · 25 min') == ['350 °F ·']
    assert figures.unquoted(figures.Card('number', 0, 0, value='20%', label=']'), 'SAVE UP TO 20%]') == [']']
    # a plus sign, a thousands separator and a unit symbol are the card's own formatting
    assert not figures.unquoted(figures.Card('number', 0, 0, value='12%', direction='up'), 'grew 12 percent')
    board = script.build(ingest.read('# Fees\n\nThe late fee is $0. Open house Sat 10–2 PM.'), story='explainer')
    assert content.card_text(board) == []
    bad = [figures.Card('number', 0, 0, value='$0', label='before')]
    import kinodraw.figures as module
    real = module.beat_cards
    try:
        module.beat_cards = lambda beat, lang: bad
        found = content.card_text(board)
    finally:
        module.beat_cards = real
    assert found and found[0]['check'] == 'card_text' and found[0]['missing'] == ['before']


def test_a_hybrid_paints_each_card_once_and_none_over_a_board_that_writes_it(tmp_path, monkeypatch):
    from kinodraw.engine import render
    board = script.build(ingest.read('# Our Year\n\nMembers kept 3,100 tons of food scraps out of the landfill.\n\n'
                                     'We planted trees in the park.\n\nThe kids painted the fence.'), story='explainer')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for scene in plan['scenes']:
        scene['treatment'] = 'chart'
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    assert type(prod).__name__ == 'HybridProduction'
    cards = prod.whiteboard.data_cards
    assert cards is not None
    start, end, _, _ = cards.entries[0]
    pastes = []                                   # every card drawn (DataCards.paint places it right before)
    real = cards.inside
    monkeypatch.setattr(cards, 'inside', lambda x, y, w, h: (pastes.append((w, h)), real(x, y, w, h))[1])
    t = (start + end) / 2
    prod.frame(t)
    assert len(pastes) == 1, f'the card was painted {len(pastes)} times on one frame'
    # where the scene shows the whiteboard page and that page writes the figure, no card at all
    for scene_span in prod.spans:
        scene_span.spec['treatment'] = 'character'
        scene_span.actors = []
    assert prod.board_on_screen(t)
    cards.on_board = {0}
    pastes.clear()
    prod.frame(t)
    assert pastes == [], 'a card over a board page that already writes its figure'


def test_a_stage_direction_never_yields_a_card():
    for text in ('[pause 3 seconds]', 'Breathe in. [pause 4 seconds] Breathe out.', '(pause 5 seconds)', '(beat)',
                 '(music swells for 10 seconds)', '[SFX: 3 chimes]', '[ON SCREEN: SAVE UP TO 15%]',
                 'Rest here. (long pause, 6 seconds)'):
        assert figures.cards(text) == [], text
    # a figure beside a direction is still a figure, and a parenthesis that is no direction keeps its numbers
    assert figures.shown(figures.cards('[pause] We raised $2,400 this spring.')[0]) == ['$2,400']
    assert figures.cards('The trail (about 12 miles) opens Monday.')


def test_a_card_with_an_unmatched_bracket_is_dropped(monkeypatch):
    monkeypatch.setattr(figures, '_sentence_card', lambda text, a, b: figures.Card('number', a, b, value='4 seconds',
                                                                                  label=']'))
    assert figures.cards('Hold for 4 seconds.') == []

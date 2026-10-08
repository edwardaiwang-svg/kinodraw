"""What a customer pastes is said the way a careful announcer says it and shown as written: phone numbers,
extensions, web and email addresses, hashtags, codes, arrows, chat shorthand, a time before a day, broadcast labels
and directions (gauntlet scripts 10, 14, 15, 28 and 34)."""
import re
from types import SimpleNamespace

import pytest

from kinodraw import ingest, numbers, script, speech
from kinodraw.engine import captions, timeline


def said(text):
    return speech.said_text(numbers.normalize(text, 'en').spoken, 'en')[0]


def board_of(text, story='story'):
    return script.build(ingest.read(text), story)


# ------------------------------------------------------------------ 1. phones, addresses, hashtags, codes, arrows
@pytest.mark.parametrize('text,voice', [
    ('Call (707) 555-0147, Ext. 3, today.',
     'Call seven oh seven, five five five, oh one four seven, extension three, today.'),
    ('Call (555) 018-7720 ext. 214.', 'Call five five five, oh one eight, seven seven two oh extension two one four.'),
    ('Call 1-800-555-0199 now.', 'Call eight oh oh, five five five, oh one nine nine now.'),
    ('Email leaves@millbrook.example, or visit millbrook.example/leaves.',
     'Email leaves at millbrook dot example, or visit millbrook dot example slash leaves.'),
    ('www.pipewisebayside.com', 'pipe wise bayside dot com'),
    ('Share it with #MillbrookLeafWeek', 'Share it with hashtag Millbrook Leaf Week'),
    ('Your code 482913 expires soon.', 'Your code four eight two nine one three expires soon.'),
    ('Enter the verification code: 0420.', 'Enter the verification code: zero four two zero.'),
    ('Tap Settings → Security → Two-step login.', 'Tap Settings, then Security, then Two-step login.'),
])
def test_contact_details_are_read_like_an_announcer(text, voice):
    assert said(text) == voice
    assert speech.caption_text(text) == text                                    # shown exactly as written


def test_two_addresses_and_a_phone_on_one_end_card_are_three_items():
    text = 'www.pipewisebayside.com hello@pipewisebayside.com (555) 018-7720'
    assert said(text) == ('pipe wise bayside dot com, hello at pipe wise bayside dot com, '
                          'five five five, oh one eight, seven seven two oh')


def test_an_arrow_is_shown_as_a_chevron():
    assert speech.shown('Settings → Security')[0] == 'Settings › Security'


def test_addresses_keep_their_dots_and_abbreviations_before_a_number_end_no_sentence():
    board = board_of('Questions? Call (707) 555-0147, Ext. 3, email leaves@millbrook.example, or visit '
                     'millbrook.example/leaves.\n\nPickup is Mon., Nov. 3 through Fri., Nov. 7.')
    shown = [b['display']['en'] for b in board['beats']]
    assert 'leaves@millbrook.example,' in shown[0] and 'millbrook.example/leaves.' in shown[0]
    assert script.sentences(shown[0], 'en') == ['Questions?', shown[0][len('Questions? '):]]
    assert script.sentences(shown[1], 'en') == [shown[1]]
    assert not [e for b in board['beats'] for e in [b['spoken']['en']] if re.search(r'\d', e)]


def test_a_caption_line_never_breaks_between_an_abbreviation_and_its_number():
    text = 'down on Quarry Road on Saturday Nov. 8 from eight in the morning until two'
    lines = captions.balanced_lines(text, 'en')
    assert len(lines) == 2 and not lines[0].endswith('Nov.')
    assert captions._needs_next('Call (707)', '555-0147') and not captions._needs_next('Call me', 'today')


def test_phone_and_address_captions_keep_their_word_times():
    board = board_of('Questions? Call (707) 555-0147, Ext. 3, or email leaves@millbrook.example today.')
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    text = ' '.join(c['text'] for c in tl['captions'])
    assert '(707) 555-0147, Ext. 3,' in text and 'leaves@millbrook.example' in text
    beat = tl['beats'][board['beats'][0]['id']]
    for c in tl['captions']:
        assert len(c['words']) == len(c['text'].split()) and c['words'] == sorted(c['words'])
        assert beat['start'] <= c['words'][0] and c['words'][-1] <= beat['speech_end'] + 1e-6


# ------------------------------------------------------------------ 2. chat shorthand
@pytest.mark.parametrize('text,voice', [
    ('ran Bramwell Hardware 22 yrs', 'ran Bramwell Hardware twenty-two years'),
    ('worst fisherman alive lol', 'worst fisherman alive'),
    ('party sat 6pm, our back yard', 'party Saturday at six PM, our back yard'),
    ('Uncle Dev turns 50!!', 'Uncle Dev turns fifty!'),
    ('see u there w/ ur kids b/c it is fun & free', 'see you there with your kids because it is fun and free'),
])
def test_chat_shorthand_is_said_in_words_and_shown_as_typed(text, voice):
    assert said(text) == voice
    assert speech.caption_text(text) == text


def test_shorthand_words_stay_when_they_are_ordinary_words():
    assert said('She sat down. The sun rose.') == 'She sat down. The sun rose.'
    assert said('Grade U is a fail.') == 'Grade U is a fail.'


# ------------------------------------------------------------------ 3. a time before a day is one phrase
@pytest.mark.parametrize('text,voice', [
    ('Crews pull the barrels at 6 a.m. Tues., Oct. 14.', 'Crews pull the barrels at six AM Tuesday, October fourteenth.'),
    ('The ribbon cutting is at 10 a.m. Saturday, and the band plays.',
     'The ribbon cutting is at ten AM Saturday, and the band plays.'),
    ('Leaf Pickup Week is Mon., Nov. 3–7. Zone A is Mon. & Tue. Zone B is Fri.',
     'Leaf Pickup Week is Monday, November third to seventh. Zone A is Monday and Tuesday. Zone B is Friday.'),
    ('Open from 8 a.m.–2 p.m. Bring proof.', 'Open from eight AM to two PM. Bring proof.'),
    ('Keep piles 3–4 ft. away, and no branches over 2 in. thick.',
     'Keep piles three to four feet away, and no branches over two inches thick.'),
    ('Drop off at 1450 Quarry Rd. Bring proof of address.',
     'Drop off at fourteen fifty Quarry Road. Bring proof of address.'),
    ('Every Saturday at 7 a.m. Just $3.50 each.', 'Every Saturday at seven AM. Just three fifty each.'),
])
def test_dates_days_and_units_read_as_one_phrase(text, voice):
    assert said(text) == voice
    spoken = numbers.normalize(text, 'en').spoken
    assert [m.group() for m in captions.clause_marks(spoken, 'en')] == \
        [m.group() for m in captions.clause_marks(text, 'en')]                  # the captions keep their timing


# ------------------------------------------------------------------ 4. broadcast labels
NEWS = """ANCHOR: Good evening. Jenna Ruiz has the story.

REPORTER (V/O): The old bridge was built in 1958.

LOWER THIRD: Maria Chen - Owner, Chen's Hardware

SOT (Maria Chen): We lost about a third of our walk-in customers.

LOWER THIRD: Sam Okafor - Town Engineer

SOT (Sam Okafor): About 2,300 cars a day used the old bridge."""


def test_a_lower_third_is_shown_as_a_strap_and_never_said():
    board = board_of(NEWS, 'news')
    labels = speech.screenplay_labels(b['display']['en'] for b in board['beats'])
    strap = board['beats'][2]
    assert speech.segments(strap['spoken']['en'], 'en', labels) == []
    assert speech.caption_text(strap['display']['en'], labels) == ''
    assert speech.screen_text(strap['display']['en'], labels) == [(0, 'strap', "Maria Chen - Owner, Chen's Hardware")]
    read = ' '.join(speech.said_text(b['spoken']['en'], 'en', labels)[0] for b in board['beats'])
    assert 'Owner' not in read and 'Town Engineer' not in read and 'LOWER' not in read


def test_a_soundbite_is_said_by_the_person_named_in_its_own_voice():
    board = board_of(NEWS, 'news')
    plan = {'cast': [
        {'id': 'jenna', 'name': 'Jenna Ruiz', 'kind': 'human', 'species': 'human', 'sex': 'female', 'age': 'adult'},
        {'id': 'maria', 'name': 'Maria Chen', 'kind': 'human', 'species': 'human', 'sex': 'female', 'age': 'adult'},
        {'id': 'sam', 'name': 'Sam Okafor', 'kind': 'human', 'species': 'human', 'sex': 'male', 'age': 'adult'}],
        'scenes': []}
    parts = speech.voice_parts(board, plan, 'af_heart')
    by = {seg.said.split()[0]: (seg.speaker, v) for todo in parts.values() for seg, v, _ in todo['parts']}
    assert by['We'][0] == 'maria' and by['About'][0] == 'sam'
    assert by['We'][1] != by['About'][1] and 'label:sot' not in {s for s, _ in by.values()}
    assert by['Good'][0] == 'label:anchor' and by['The'][0] == 'label:reporter'      # a tag names no one
    loose = speech.voice_parts(board, None, 'af_heart')
    assert {seg.speaker for todo in loose.values() for seg, _, _ in todo['parts']} >= {
        'label:maria chen', 'label:sam okafor'}


# ------------------------------------------------------------------ 5. directions and on-screen text
@pytest.mark.parametrize('direction', ['(cut to close up of a dripping kitchen faucet)', '(cut to sprinkler at sunrise)',
                                       '(slow motion)', '(CLOSE UP on the washer)', '[B-ROLL: a crew at work]',
                                       '(beat)', '(pan across the lawn)'])
def test_directions_are_never_said_or_captioned_in_any_script(direction):
    text = f'Find the drip. {direction} A faucet leaking one drop a second wastes water.'
    assert said(text) == 'Find the drip. A faucet leaking one drop a second wastes water.'
    assert speech.caption_text(text) == 'Find the drip. A faucet leaking one drop a second wastes water.'
    assert speech.shown(text)[0] == 'Find the drip. A faucet leaking one drop a second wastes water.'


def test_a_writers_own_parenthesis_is_still_said():
    text = 'Run full loads (dishwasher and washer) only.'
    assert said(text) == text and speech.caption_text(text) == text


def test_text_on_screen_shows_its_words_and_says_nothing():
    for text in ('[TEXT ON SCREEN: SAVE UP TO 20%]', '[ON SCREEN: "SAVE UP TO 20%"]', 'TEXT ON SCREEN: SAVE UP TO 20%'):
        assert said(text) == '' and speech.caption_text(text) == ''
        assert speech.shown(text)[0] == 'SAVE UP TO 20%'
        assert speech.screen_text(text) == [(0, 'text', 'SAVE UP TO 20%')]
    line = 'Do all five. [TEXT ON SCREEN: SAVE UP TO 20%] You could save up to 20%.'
    assert speech.shown(line)[0] == 'Do all five. You could save up to 20%.'
    shown, index = speech.shown(line)
    assert ''.join(line[i] for i in index) == shown


def _fake_production(texts, said):
    """The parts of a HybridProduction the on-screen text uses: beats, their times and a palette."""
    from kinodraw.director.v3.semantics import beats as beat_list
    board = [{'id': f'b{k:03d}', 'display': t, 'spoken': numbers.normalize(t, 'en').spoken} for k, t in enumerate(texts)]
    by_id = {b['id']: b for b in beat_list(board)}
    tl = {'beat_order': list(by_id), 'end_card': {'start': 3. * len(texts)},
          'beats': {bid: {'start': 3. * k, 'end': 3. * (k + 1), 'speech_end': 3. * (k + 1) - .2,
                          'char_times': [3. * k + i * .01 for i in range(len(by_id[bid]['spoken']))] if said[k] else []}
                    for k, bid in enumerate(by_id)}}
    fake = SimpleNamespace(by_id=by_id, tl=tl, labels=speech.screenplay_labels(texts), size=(1920, 1080),
                           vertical=False, style={'palette': {'background': '#FFF8EC', 'ink': '#1E2A38',
                                                             'accent': '#E07A2E', 'accent2': '#2E8B83'}})
    fake._spoken_at = lambda bid, char: tl['beats'][bid]['start'] + char * .01
    return fake


def test_a_strap_shows_under_the_next_speaker_and_a_text_card_with_its_line():
    from kinodraw.engine.hybrid import HybridProduction
    texts = ['ANCHOR: Good evening.', 'LOWER THIRD: Maria Chen - Owner, Chen\'s Hardware',
             'SOT (Maria Chen): We lost a third of our customers.', '[TEXT ON SCREEN: SAVE UP TO 20%]',
             'Do all five and you could save up to 20%.']
    fake = _fake_production(texts, [True, False, True, False, True])
    fake.lang = 'en'
    fake._spoken_offset = lambda bid, pos: HybridProduction._spoken_offset(fake, bid, pos)
    notes = HybridProduction._screen_notes(fake)
    assert notes == [(6., 9., 'strap', "Maria Chen - Owner, Chen's Hardware"), (12., 15., 'text', 'SAVE UP TO 20%')]
    fake.screen_notes = notes
    from PIL import Image
    blank = Image.new('RGB', fake.size, (255, 248, 236))
    assert HybridProduction._draw_screen_text(fake, blank, 1.).tobytes() == blank.tobytes()
    strap = HybridProduction._draw_screen_text(fake, blank, 7.5)
    box = Image.eval(strap, lambda v: v).convert('L').point(lambda v: 255 if v < 120 else 0).getbbox()
    assert box and box[0] < 1920 * .1 and box[3] < 1080 * .82 and box[1] > 1080 * .6       # low left, above captions
    card = HybridProduction._draw_screen_text(fake, blank, 13.5)
    diff = Image.eval(Image.blend(card, blank, 0), lambda v: v)
    changed = [y for y in range(0, 1080, 20) if card.crop((0, y, 1920, y + 20)).tobytes() != blank.crop((0, y, 1920, y + 20)).tobytes()]
    assert changed and max(changed) < 1080 * .3                                           # across the top


def test_hybrid_draws_the_shown_text_and_times_each_clause_from_it():
    from kinodraw.engine.bold.model import MotionElement
    from kinodraw.engine.hybrid import HybridProduction
    text = 'Find the drip. (cut to close up of a dripping kitchen faucet) It wastes 3,000 gallons a year.'
    fake = _fake_production([text], [True])
    fake._shown_text = {}
    fake._shown = lambda bid: HybridProduction._shown(fake, bid)
    fake._shown_offset = lambda bid, pos: HybridProduction._shown_offset(fake, bid, pos)
    fake._spoken_offset = lambda bid, pos: HybridProduction._spoken_offset(fake, bid, pos)
    fake.lang = 'en'
    shown = fake._shown('b000')[0]
    assert shown == 'Find the drip. It wastes 3,000 gallons a year.'
    element = MotionElement(text=shown, width=1450, size=72)
    HybridProduction._clause_build(fake, SimpleNamespace(start=0.), element, 'b000')
    spoken = fake.by_id['b000']['spoken']
    assert element.cues == pytest.approx((0., spoken.index('It wastes') * .01))


# ------------------------------------------------------------------ 6. labels beside the cast are whole clauses
@pytest.mark.usefixtures('procedural_rig')
def test_a_crowded_label_shows_whole_clauses_and_leaves_the_words_to_the_caption(tmp_path):
    # Script 10 (r02): "Heat a nonstick pan over", "Scoop about two", "Flip gently, and cook 1": each label beside
    # the cook was cut to its first line, before the quantity, and the caption that carried the words was off.
    import json
    from kinodraw.director.rules import RulesDirector
    from kinodraw.director.v3.rules import from_rules
    from kinodraw.engine import render
    board = board_of('# Pancakes\n\nNia, a tiny lion cub, loved her mother, Sora.\n\n'
                     'Nia flipped it gently, and she cooked it 1 more minute until both sides were golden brown.')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', music_mood='none')
    for scene in plan['scenes']:
        bid = scene['beat_ids'][0]
        scene.update(treatment='character', composition='split', camera='static', transition_in='cut',
                     elements=[{'kind': 'cast', 'ref': c['id']} for c in plan['cast'][:1]] +
                     [{'kind': 'text', 'ref': bid}] + [{'kind': 'picture', 'ref': r} for r in (
                         'fl_banana', 'fl_egg', 'fl_bowl_with_spoon', 'fl_spoon', 'fl_cooking')],
                     text={'kind': 'caption_only', 'ref': bid})
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = prod.spans[-1]
    labels = [' '.join(e.text.split()) for e in span.motion.elements if e.kind == 'text']
    assert span.source_character and labels in ([], ['Nia flipped it gently']), labels
    beat = span.spec['beat_ids'][0]
    assert beat not in span.on_screen
    middle = (tl['beats'][beat]['start'] + tl['beats'][beat]['speech_end']) / 2
    assert not prod._written(span, middle)                        # the caption shows the whole line


def test_a_phone_in_a_screenplay_line_keeps_its_area_code():
    text = 'MARIA: Call (707) 555-0147 (smiling) today.'
    assert speech.caption_text(text, {'maria'}) == 'Call (707) 555-0147 today.'
    assert speech.said_text(numbers.normalize(text, 'en').spoken, 'en', {'maria'})[0] == \
        'Call seven oh seven, five five five, oh one four seven today.'


def test_written_board_text_keeps_its_abbreviations():
    from kinodraw.engine import process_diagrams as pd
    assert pd.typeset('Mon. & Tue.') == 'Mon. & Tue.'
    assert pd.typeset("by 6 a.m. on your zone's first day") == "by 6 a.m. on your zone's first day"
    assert pd.typeset('Sat., Nov. 8, from 8 a.m.–2 p.m.') == 'Sat., Nov. 8, from 8 a.m.–2 p.m.'
    assert pd.typeset('twelve minus four is eight') == '12 − 4 = 8'


def test_on_screen_wrap_keeps_ext_and_dates_with_their_numbers():
    from kinodraw.engine.captions import wrap
    lines = wrap('Questions? Call (707) 555-0147, Ext. 3, email leaves@millbrook.example, '
                 'or visit millbrook.example/leaves.', 36)
    assert not any(re.search(r'(?:Ext\.|Nov\.|\(\d{3}\))$', line) for line in lines), lines
    assert ' '.join(lines) == ('Questions? Call (707) 555-0147, Ext. 3, email leaves@millbrook.example, '
                               'or visit millbrook.example/leaves.')
    assert not any(line.endswith('Nov.') for line in wrap('Leaf Pickup Week is Mon., Nov. 3 through Fri., Nov. 7.', 30))


def test_board_text_keeps_one_as_a_pronoun():
    from kinodraw.engine import process_diagrams as pd
    assert pd.typeset('Half a load uses almost the same water as a full one') == \
        'Half a load uses almost the same water as a full one'
    assert pd.typeset('one drop a second over 3,000 gallons a year') == '1 drop a second over 3,000 gallons a year'
    assert pd.typeset('twelve minus one is eleven') == '12 − 1 = 11'


def test_two_counts_in_a_row_are_said_as_a_list():
    said = speech.said_text(numbers.normalize('3 kids 2 grandkids', 'en').spoken, 'en')[0]
    assert said == 'three kids, two grandkids'
    said = speech.said_text(numbers.normalize('3 times 2 is 6', 'en').spoken, 'en')[0]
    assert ',' not in said


def test_board_fragments_join_with_a_space_when_nothing_is_typeset():
    from kinodraw.engine import process_diagrams as pd
    assert pd.typeset('Half a load ... almost the same water as a full one') == \
        'Half a load almost the same water as a full one'
    assert pd.typeset('Mon. & Tue.') == 'Mon. & Tue.'

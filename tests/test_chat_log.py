"""A pasted chat log (kinodraw/chatlog.py): every common line shape is a message with its sender and time, the app's
notices are notices, the thread grows on a phone, each sender is heard in their own voice and seen alone in their
own place, and no time, sender label or notice is ever said. Invented example lines only."""
from PIL import Image

from kinodraw import chatlog, ingest, script, speech, ui_screens
from kinodraw.director.v3.semantics import beats as read_beats
from kinodraw.engine import storybook
from kinodraw.engine import ui_screens as screens

LOG = '\n'.join((
    'Group chat: Lakeside Swim Team 🏊 (Ruby\'s phone)',
    '6:58 AM — Coach Okoye: pool opens at 7:30, lane four is ours',
    '[7:01] Ruby: running late, brb 😅',
    'Felix (7:02 PM): who has my goggles?',
    '7:03 PM - Grandpa Abe: Is this the swimming group??',
    '7:04 PM - Grandpa Abe joined using this group\'s invite link',
    'This message was deleted',
    '[7:05] Felix: [Voice note 0:09]',
    'Ruby: 😂😂',
    'Missed voice call',
    'Ruby: omg felix they are in ur bag lol'))
CAST = [{'id': 'okoye', 'name': 'Coach Okoye', 'kind': 'human', 'species': 'human', 'sex': 'female', 'age': 'adult'},
        {'id': 'ruby', 'name': 'Ruby', 'kind': 'human', 'species': 'human', 'sex': 'female', 'age': 'young'},
        {'id': 'felix', 'name': 'Felix', 'kind': 'human', 'species': 'human', 'sex': 'male', 'age': 'young'},
        {'id': 'abe', 'name': 'Grandpa Abe', 'kind': 'human', 'species': 'human', 'sex': 'male', 'age': 'old'}]


def board():
    return script.build(ingest.read(LOG), 'story')


def texts(b, key):
    return [x[key][b['lang']] for x in b['beats']]


def thread():
    b = board()
    shown = texts(b, 'display')
    return ui_screens.read([(x['id'], t) for x, t in zip(b['beats'], shown)], CAST, speech.screenplay_labels(shown))


def test_each_pasted_line_shape_is_a_message_with_its_sender_and_time():
    assert chatlog.stamp_end('[7:01] Ruby: hi', 0) == (7, '7:01')
    assert chatlog.stamp_end('6:58 AM — Coach Okoye: hi', 0)[1] == '6:58 AM'
    assert chatlog.stamp_end('10/8/26, 7:03 PM - Abe: hi', 0)[1] == '10/8/26, 7:03 PM'
    assert chatlog.stamp_end('[Voice note 0:09]', 0) is None            # a bracket that is no time
    b = board()
    shown = texts(b, 'display')
    assert len(shown) == 11                                             # one beat per line, notices too
    labels = speech.screenplay_labels(shown)
    assert labels.chat and labels == {'coach okoye', 'ruby', 'felix', 'grandpa abe'}
    rows = [(m['sender'], m['time'], m['text'], bool(m['outgoing'])) for m in thread()
            if m.get('sender') and m.get('voice') is None]
    assert rows == [('Coach Okoye', '6:58 AM', 'pool opens at 7:30, lane four is ours', False),
                    ('Ruby', '7:01', 'running late, brb 😅', True),
                    ('Felix', '7:02 PM', 'who has my goggles?', False),
                    ('Grandpa Abe', '7:03 PM', 'Is this the swimming group??', False),
                    ('Ruby', None, '😂😂', True),                     # emoji only: a message all the same
                    ('Ruby', None, 'omg felix they are in ur bag lol', True)]


def test_plain_name_lines_are_a_chat_only_when_people_are_texting():
    texting = ['Mo: u up?', 'Kai: ya lol', 'Mo: omg same 😴', 'Kai: brb']
    assert speech.screenplay_labels(texting).chat
    play = ['MO: Where were you last night?', 'KAI: Out.', 'MO: Out where?', 'KAI: Just out, Mo.']
    assert not speech.screenplay_labels(play).chat                     # a screenplay stays a screenplay
    story = ['Dad (6:12 PM): dinner is ready', 'Nobody answered. The house was quiet for a long time after that.',
             'She put the phone down and went to the window, where the rain had started again.']
    assert not speech.screenplay_labels(story).chat                    # one text inside a narrated story


def test_notices_voice_notes_and_the_header_are_shown_on_the_thread():
    assert chatlog.system('Grandpa Abe joined using this group\'s invite link')
    assert chatlog.system('7:10 PM - Coach Okoye added Felix') and chatlog.system('Felix left')
    assert chatlog.system('This message was deleted') and chatlog.system('Missed voice call')
    assert not chatlog.system('Ruby: I left my towel')
    assert chatlog.voice_note('[Voice note 0:09]') == '0:09' and chatlog.voice_note('🎤 Voice message (0:12)') == '0:12'
    assert chatlog.header('Group chat: Lakeside Swim Team 🏊 (Ruby\'s phone)') == 'Lakeside Swim Team 🏊'
    found = thread()
    assert found[0].get('header_only') and {m['thread'] for m in found} == {'Lakeside Swim Team 🏊'}
    notices = [(m['text'], m['time']) for m in found if m.get('system')]
    assert notices == [("Grandpa Abe joined using this group's invite link", '7:04 PM'),
                       ('This message was deleted', None), ('Missed voice call', None)]
    note = next(m for m in found if m.get('voice') is not None)
    assert (note['sender'], note['voice'], note['time']) == ('Felix', '0:09', '7:05')
    assert [len(m['history']) for m in found[1:]] == list(range(len(found) - 1))      # it grows message by message
    # Drawn: the notice centred in grey, the voice note with a play button; different pictures for each.
    for m in found:
        m['start'], m['end'] = 0., 9.
    pics = [screens.draw((640, 360), m, 3.).tobytes() for m in found]
    assert len(set(pics)) == len(pics)


def test_each_sender_speaks_in_their_own_voice_and_no_time_label_or_notice_is_said():
    b = board()
    parts = speech.voice_parts(b, {'cast': CAST, 'scenes': []}, 'af_heart')
    who, said = {}, []
    for todo in parts.values():
        for seg, voice, _ in todo['parts']:
            who.setdefault(seg.speaker, set()).add(voice)
            said.append(seg.said)
    assert set(who) == {'okoye', 'ruby', 'felix', 'abe'}                # nobody is read by the narrator
    assert all(len(v) == 1 for v in who.values()) and len({v for vs in who.values() for v in vs}) == 4
    assert 'af_heart' not in {v for vs in who.values() for v in vs}
    words = ' '.join(said).lower()
    for gone in ('seven oh', 'six fifty', 'am ', 'pm', 'okoye:', 'grandpa abe', 'joined', 'deleted', 'voice note',
                 'missed', 'lakeside', 'group chat'):
        assert gone not in words, gone
    assert 'pool opens at seven thirty' in words                        # a time inside a message is still said
    # A silent line (a notice, a voice note, an emoji) holds long enough to read on the phone.
    assert all(todo['hold'] == speech.CHAT_HOLD for todo in parts.values() if not todo['parts'])


def test_the_senders_are_seen_alone_in_their_own_places_with_their_phones():
    b = board()
    by_id = {x['id']: x for x in read_beats({'lang': 'en', 'beats': b['beats']}, 'en')}
    tl = {'beats': {bid: {'start': i * 3., 'end': i * 3. + 3., 'char_times': [k * .04 for k in range(400)]}
                    for i, bid in enumerate(by_id)}}
    plan = {'cast': CAST, 'storyboard': {'genre': 'story'}, 'scenes': [{'beat_ids': list(by_id)}]}
    book = storybook.Storybook(plan, by_id, tl, (640, 360), Image.new('RGB', (8, 8)))
    spec = {'beat_ids': list(by_id), 'elements': [{'kind': 'cast', 'ref': c['id']} for c in CAST],
            'atmosphere': {'kind': 'none'}}
    shots = book.prepare(spec, 0., len(by_id) * 3.)
    assert all(len(s.figures) == 1 for s in shots)                      # remote senders are never together
    seen = {s.figures[0].key: s.place for s in shots}
    assert set(seen) == {'okoye', 'ruby', 'felix', 'abe'} and len(set(seen.values())) == 4
    assert all(any(p.doodle == 'fl_mobile_phone' and p.holder == s.figures[0].key for p in s.set) for s in shots)
    assert not any(s.bubbles for s in shots)


def test_a_chat_lines_time_gets_no_data_card_and_wordless_messages_pass_the_screen_check(tmp_path):
    import json
    from kinodraw.engine import data_cards
    from kinodraw.qa import screens as screens_qa
    b = board()
    tl = {'beats': {x['id']: {'start': i * 3., 'end': i * 3. + 3., 'char_times': [k * .04 for k in range(400)]}
                    for i, x in enumerate(b['beats'])}}
    cards = data_cards.entries(b, tl, 'en')
    times = {'6:58', '7:01', '7:02', '7:03', '7:04', '7:05'}
    assert not any(t in json.dumps([str(c) for _, _, c, _ in cards]) for t in times)
    # A voice note, the header and an emoji-only message have no words to find on a screen.
    video = tmp_path / 'v.mp4'
    (tmp_path / 'build').mkdir()
    rows = [{'beat': m['beat'], 'strings': ui_screens.drawn_strings(m), 'start': 0, 'end': 1, 'kind': 'message'}
            for m in thread()]
    (tmp_path / 'build' / 'ui-screens.json').write_text(json.dumps(rows))
    assert screens_qa.check(b, video) == []


def test_a_screen_cuts_in_and_never_crossfades_over_the_picture():
    from types import SimpleNamespace
    m = thread()[1]
    m['start'], m['end'] = 1., 4.
    paper = Image.new('RGB', (640, 360), (250, 250, 245))
    prod = SimpleNamespace(ui_moments=[m], size=(640, 360), style={},
                           skin=SimpleNamespace(background=lambda w, h: paper))
    face = Image.new('RGB', (640, 360), (200, 30, 30))
    for t in (1.02, 1.1, 3.9, 3.98):                    # right after it starts and right before it ends
        assert screens.cover(prod, face, t).getpixel((8, 8)) == (250, 250, 245)
    assert screens.cover(prod, face, 4.01).getpixel((8, 8)) == (200, 30, 30)

"""Device screens and text messages (kinodraw/ui_screens.py reads them, kinodraw/engine/ui_screens.py draws them):
text the script shows on a screen is read by the narrator and drawn on its device, never a figure's speech bubble;
a how-to's steps draw the app's screen with the element each step names; a texting scene draws the thread."""
import json

from PIL import Image

from kinodraw import speech, ui_screens
from kinodraw.engine import ui_screens as screens
from kinodraw.qa import screens as screens_qa


FAMILY = [{'id': 'ivy', 'name': 'Ivy', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female'},
          {'id': 'gran', 'name': 'Gran', 'kind': 'human', 'species': 'human', 'age': 'old', 'sex': 'female'},
          {'id': 'otto', 'name': 'Otto', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male'}]


def moments(*paragraphs, cast=FAMILY):
    return ui_screens.read([(f'b{i:03d}', p) for i, p in enumerate(paragraphs)], cast)


def kinds(found):
    return [(e['kind'], e['label']) for m in found for e in m['elements']]


# ------------------------------------------------------------------ which quotations are shown, not said
def test_texts_notifications_and_button_labels_are_shown_text():
    assert ui_screens.quote_kind('Her phone buzzed: "running late, save me a seat"', 17) == 'message'
    assert ui_screens.quote_kind('His first text said, "is this thing on?"', 20) == 'message'
    assert ui_screens.quote_kind('When the bread is ready, you get a nudge: "Time to bake."', 41) == 'notification'
    assert ui_screens.quote_kind('Tap "Start timer" and the clock begins.', 4) == 'label'
    assert ui_screens.quote_kind('The sign on the door said "Back in 5 minutes."', 25) == 'shown'
    # A quotation on its own line takes what the line before says it is.
    assert ui_screens.quote_kind('"see you at noon 🌮"', 0, 'Her phone buzzed under the table.') == 'message'
    assert ui_screens.quote_kind('"see you at noon"', 0, 'Then she opened Gran\'s name and typed:') == 'message'


def test_lines_people_say_aloud_stay_dialogue():
    assert ui_screens.quote_kind('"Tap the red button," Otto said.', 0) is None
    assert ui_screens.quote_kind('Gran said, "Because I type slow, but I get there."', 11) is None
    assert ui_screens.quote_kind('She read the text out loud: "come home now"', 28) is None
    assert ui_screens.quote_kind('"Who left the phone on the stairs?"', 0, 'Otto climbed the stairs.') is None
    assert ui_screens.quote_kind('"Every day," Ivy said.', 0, 'Her phone buzzed.') is None


# ------------------------------------------------------------------ app screens
def test_app_steps_name_their_device_app_and_elements():
    found = moments('On your laptop, open Tidewater Bank and click your initials in the top-right corner → Profile.',
                    'Choose Alerts, then Text alerts → Turn on.',
                    'On your phone, open the Keyring app and tap the + button.',
                    'Scan the QR code on your laptop screen. A new entry called Tidewater appears with a code, '
                    'like 305 771.',
                    'Type that code into the box on your laptop and click Confirm.')
    assert [(m['device'], m['app']) for m in found] == [('laptop', 'Tidewater Bank'), ('laptop', 'Tidewater Bank'),
                                                        ('phone', 'Keyring'), ('laptop', 'Tidewater Bank'),
                                                        ('phone', 'Keyring'), ('laptop', 'Tidewater Bank')]
    assert kinds(found) == [('avatar', ''), ('row', 'Profile'), ('row', 'Alerts'), ('row', 'Text alerts'),
                            ('button', 'Turn on'), ('button', '+'), ('qr', ''), ('row', 'Tidewater'),
                            ('code', '305 771'), ('input', 'code'), ('button', 'Confirm'), ('check', '')]
    assert found[-1]['elements'][0]['value'] == '305 771'           # the code typed is the code shown
    text = 'Choose Alerts, then Text alerts → Turn on.'
    assert [text[e['at']:].startswith(w) for e, w in zip(found[1]['elements'], ('Choose', 'then', '→'))]


def test_an_apps_list_legend_button_and_notification():
    found = moments('Snap your shelf and Pantrypal builds your list for you. Rice, lentils, olive oil, that basil.',
                    'Blue means fresh. Orange means use it soon.',
                    'When something runs low, you get a nudge: "Lentils are almost gone."',
                    'Tap "Plan my week" and Pantrypal shows meals from what you have.', cast=[])
    assert [m['app'] for m in found] == ['Pantrypal'] * 4
    assert kinds(found) == [('row', 'Rice'), ('row', 'lentils'), ('row', 'olive oil'), ('row', 'basil'),
                            ('legend', 'fresh'), ('legend', 'use it soon'),
                            ('notification', 'Lentils are almost gone.'), ('button', 'Plan my week')]
    assert found[2]['kind'] == 'notification'


def test_phones_movie_screens_and_titles_alone_are_no_app_screen():
    assert moments('He put his phone on the table and smiled.') == []
    assert moments('The movie screen went dark and everyone cheered.') == []
    assert moments('Turn On Two-Factor Sign In') == []
    assert moments('"Tap the red button," Otto said.') == []
    assert moments('She typed slowly with one finger, and the old phone had big buttons.') == []


# ------------------------------------------------------------------ messages
def test_a_texting_scene_is_one_thread_in_order_with_senders_times_and_emoji():
    found = moments("Ivy's phone buzzed at the bus stop. It was the group chat called Lunch Crew.",
                    'Otto (12:01 PM): tacos or ramen? 🌮\nGran (12:02 PM): ramen, obviously 🍜\n'
                    'Ivy (12:03 PM): ramen!!',
                    'Then Otto sent one more message: "booked for 1:00 👍"',
                    'Ivy typed back: "see you there"',
                    'Delivered.')
    assert [(m['thread'], m['sender'], m['outgoing'], m['time'], m['text']) for m in found] == [
        ('Lunch Crew', 'Otto', False, '12:01 PM', 'tacos or ramen? 🌮'),
        ('Lunch Crew', 'Gran', False, '12:02 PM', 'ramen, obviously 🍜'),
        ('Lunch Crew', 'Ivy', True, '12:03 PM', 'ramen!!'),
        ('Lunch Crew', 'Otto', False, None, 'booked for 1:00 👍'),
        ('Lunch Crew', None, True, None, 'see you there')]
    assert [len(m['history']) for m in found] == [0, 1, 2, 3, 4]
    assert found[-1]['status'] == 'Delivered'


def test_texts_from_a_named_sender_and_the_old_messages_shown_again():
    found = moments('Gran got her first phone. Her first text said:', '"HELLO IVY ITS GRAN"',
                    'Ivy showed her friend the old messages, years of them.',
                    "Then she opened Gran's name and typed:", '"hi gran 🐢"')
    assert [(m['beat'], m['thread'], m['outgoing'], m['text'], bool(m.get('replay'))) for m in found] == [
        ('b001', 'Gran', False, 'HELLO IVY ITS GRAN', False), ('b002', 'Gran', False, 'HELLO IVY ITS GRAN', True),
        ('b004', 'Gran', True, 'hi gran 🐢', False)]


# ------------------------------------------------------------------ drawing
def _drawn(moment, t=5.):
    for i, e in enumerate(moment['elements']):
        e.setdefault('t', i * .3)
    moment.setdefault('start', 0.)
    moment.setdefault('end', 99.)
    return screens.draw((1280, 720), moment, t)


def test_a_screen_is_drawn_inside_its_device_with_the_scripts_own_strings():
    phone, laptop = moments('On your phone, open the Keyring app and tap the + button.',
                            'On your laptop, open Tidewater Bank and click Confirm.')
    for m, (x0, x1) in ((phone, (.3, .7)), (laptop, (.08, .92))):
        box = _drawn(m).getbbox()
        assert box is not None and box[0] >= 1280 * x0 and box[2] <= 1280 * x1 and box[3] <= 720 * .8
    assert 'Keyring' in ui_screens.drawn_strings(phone) and '+' in ui_screens.drawn_strings(phone)
    assert ui_screens.drawn_strings(laptop) == ['Tidewater Bank', 'Confirm']
    # An element is drawn on its word: before it the screen shows only the app bar.
    early, late = _drawn(dict(laptop, elements=[dict(laptop['elements'][0], t=3.)]), 1.), _drawn(laptop, 4.)
    assert early.tobytes() != late.tobytes()


def test_emoji_are_colour_pictures_not_missing_glyph_boxes():
    pic = screens._emoji('🐢', 48).convert('RGB')
    colours = {px for px in pic.getdata() if max(px) - min(px) > 60}
    assert len(colours) > 20                                  # a coloured drawing, never a hollow tofu box
    assert screens._runs('sunshine 🐢️') == [(False, 'sunshine '), (True, '🐢')]


def test_a_message_thread_draws_its_bubbles_on_the_phone():
    found = moments("Ivy's phone buzzed.", 'Otto (12:01 PM): tacos or ramen? 🌮\nIvy (12:03 PM): ramen!!')
    img = _drawn(found[-1], 1.)
    box = img.getbbox()
    assert box[0] >= 1280 * .3 and box[2] <= 1280 * .7
    right = img.crop((640, 0, 1280, 720)).convert('RGBA')
    assert right.getbbox() is not None


# ------------------------------------------------------------------ QA
def test_qa_fails_a_message_read_over_a_blank_device(tmp_path):
    board = {'lang': 'en', 'beats': [{'id': 'b001', 'display': {'en': 'Her phone buzzed.'}},
                                     {'id': 'b002', 'display': {'en': '"running late 🚌"'}}]}
    video = tmp_path / 'v.mp4'
    found = screens_qa.check(board, video)
    assert [f['check'] for f in found] == ['blank_screen'] and 'running late' in found[0]['problem']
    (tmp_path / 'build').mkdir()
    (tmp_path / 'build' / 'ui-screens.json').write_text(json.dumps(
        [{'beat': 'b002', 'strings': ['running late 🚌'], 'start': 1, 'end': 3, 'kind': 'message'}]))
    assert screens_qa.check(board, video) == []
    assert screens_qa.check(board, None) == []


def test_typing_stays_inside_the_compose_box():
    found = moments("Ivy's phone buzzed.", 'Ivy typed back: "can mine be the big one with extra cheese and olives please"')
    img = _drawn(found[-1], .9)                               # still typing: the words are in the compose box
    body = [x for x in range(1280) if img.getpixel((x, 300))[3]]
    assert img.getbbox()[2] <= max(body) + 2                  # nothing spills past the phone's side

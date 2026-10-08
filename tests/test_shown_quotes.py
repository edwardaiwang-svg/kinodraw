"""Text a script shows on a screen (a text message, a notification, a chat transcript line) is read by the narrator,
never voiced or bubbled as a character's line; words someone says aloud keep their speaker (speakers.attribute,
speech.segments; the reading is kinodraw/ui_screens.quote_kind)."""
from kinodraw import speech

from test_speakers import said

FAMILY = [{'id': 'ivy', 'name': 'Ivy', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female'},
          {'id': 'gran', 'name': 'Gran', 'kind': 'human', 'species': 'human', 'age': 'old', 'sex': 'female'},
          {'id': 'otto', 'name': 'Otto', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male'}]


def test_shown_quotes_get_the_narrators_voice_and_said_ones_keep_the_speaker():
    text = ('Ivy sat on the bus. Her phone buzzed.\n\n"good luck today 🍀"\n\n'
            'Gran called that evening. "How did it go?" Gran asked.')
    assert said(text, FAMILY) == [('How did it go?', 'gran')]


def test_a_chat_line_with_a_time_is_read_by_the_narrator_and_its_time_never_said():
    text = 'Otto (7:02 AM): Who took my charger? 🔌'
    labels = speech.screenplay_labels([text])
    assert labels == {'otto'}
    parts = speech.segments(text, 'en', labels, label_speaker=lambda name: 'otto')
    assert [(p.speaker, p.said) for p in parts] == [(None, 'Who took my charger?')]
    assert '7:02' not in speech.caption_text(text, labels)
    # Without a time it is still a screenplay line, in the speaker's own voice.
    assert speech.segments('Otto: Who took it?\nOtto: Me.', 'en', {'otto'}, label_speaker=lambda n: 'otto')[0].speaker \
        == 'otto'


def test_a_notification_and_a_typed_message_are_the_narrators():
    text = ('Otto opened the oven app. When the bread is ready, you get a nudge: "Time to bake, Otto."\n\n'
            '"Smells great," Gran said.\n\nThen Ivy opened Gran\'s name and typed:\n\n"save me a slice 🍞"')
    assert said(text, FAMILY) == [('Smells great', 'gran')]

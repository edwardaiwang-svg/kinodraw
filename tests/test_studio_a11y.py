"""Dialogs a keyboard and a screen reader can use: labelled, focus inside and back, Escape, and a ? shortcut list."""
import re

from kinodraw.studio import server
from studio_browser import make_project, studio_page  # noqa: F401 - the fixture


def test_the_dialog_is_marked_up_for_screen_readers():
    page = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    box = re.search(r'<div id="modal"[^>]*>\s*<div ([^>]*)>\s*<button ([^>]*)>', page)
    assert 'role="dialog"' in box.group(1) and 'aria-modal="true"' in box.group(1)
    assert 'aria-label="Close"' in box.group(2)


def test_keyboard_dialogs_and_the_shortcut_list_in_a_real_browser(studio_page):
    """Settings opens from the keyboard with focus inside; Tab wraps; Escape closes and returns focus; ? lists the
    real shortcuts, but typing ? in a text box does not open it."""
    assert '"passed":true' in studio_page('a11y')


def test_an_ai_failure_shows_a_plain_card_and_the_noise_clean_up_is_a_checkbox(studio_page, monkeypatch):
    """A refused key: the card names the service and what to try, opens Settings, and never shows the key. The
    Narrator's own-voice view turns the recording's noise clean-up off, and the project keeps that."""
    from kinodraw import starters
    from kinodraw.director.llm.providers import ProviderError
    name = make_project(starters.read('explainer-en'), 'en')

    def refused(*args, **kwargs):
        error = ProviderError('Error code: 401 - invalid x-api-key sk-ant-api03-abcdefghijklmnop')
        error.kind, error.provider = 'key', 'anthropic'
        raise error
    monkeypatch.setattr(server.director, 'direct', refused)
    assert '"passed":true' in studio_page('problems')
    assert server.narrator(name)['clean'] is False


def test_music_paper_and_hand_are_chosen_from_the_project_header_in_a_real_browser(studio_page, tmp_path, monkeypatch):
    """Grid paper, a left hand and the user's own music file, then no music: each saved to the storyboard by the
    real controls."""
    import json
    from kinodraw import starters
    from test_music_upload import two_tones
    name = make_project(starters.read('explainer-en'), 'en')
    monkeypatch.setenv('KINODRAW_TEST_MUSIC', str(two_tones(tmp_path / 'riff.wav', seconds=12.)))
    assert '"passed":true' in studio_page('options')
    board = json.loads((server.projects_root() / name / 'storyboard.json').read_text())
    assert (board['paper'], board['hand'], board['music']) == ('grid', 'left', False)
    assert list((server.projects_root() / name / 'music').glob('riff*.wav'))

"""Dialogs a keyboard and a screen reader can use: labelled, focus inside and back, Escape, and a ? shortcut list."""
import re

from kinodraw.studio import server
from studio_browser import studio_page  # noqa: F401 - the fixture


def test_the_dialog_is_marked_up_for_screen_readers():
    page = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    box = re.search(r'<div id="modal"[^>]*>\s*<div ([^>]*)>\s*<button ([^>]*)>', page)
    assert 'role="dialog"' in box.group(1) and 'aria-modal="true"' in box.group(1)
    assert 'aria-label="Close"' in box.group(2)


def test_keyboard_dialogs_and_the_shortcut_list_in_a_real_browser(studio_page):
    """Settings opens from the keyboard with focus inside; Tab wraps; Escape closes and returns focus; ? lists the
    real shortcuts, but typing ? in a text box does not open it."""
    assert '"passed":true' in studio_page('a11y')

"""The download page (docs/index.html) as a stranger reads it right after downloading."""
import html
import re
from pathlib import Path

SITE = Path(__file__).parents[1] / 'docs' / 'index.html'


def test_the_first_mac_open_is_a_numbered_box_with_apples_steps():
    """v0.1.6 had one small-print sentence; a tester installed the app and could not find Open Anyway."""
    raw = SITE.read_text(encoding='utf-8')
    box = re.search(r'<section id="first-open".*?</section>', raw, re.S)
    assert box, 'no first-open box'
    text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', box.group(0))).split())
    assert 'First time opening on a Mac' in text and '<ol' in box.group(0)
    for words in ('Privacy & Security', 'Open Anyway', 'about an hour', 'login password'):   # Apple's own wording
        assert words in text, words
    for words in ('More info', 'Run anyway', 'Smart App Control'):                          # and Windows
        assert words in text, words
    assert 'href="#first-open"' in raw                                   # the Download area points to it
    for img in re.findall(r'<img[^>]*>', re.sub(r'<!--.*?-->', '', box.group(0), flags=re.S)):   # real screenshots only
        assert Path(SITE.parent, re.search(r'src="([^"]+)"', img).group(1)).is_file()

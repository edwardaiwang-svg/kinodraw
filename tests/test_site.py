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


def test_link_previews_and_search_engines_get_a_title_description_and_image():
    """v0.1.6's page had only <title>Doodle Studio</title>: shared links showed a bare URL."""
    raw = SITE.read_text(encoding='utf-8')
    home = 'https://edwardaiwang-svg.github.io/kinodraw/'
    assert f'<link rel="canonical" href="{home}">' in raw
    for name in ('og:title', 'og:description', 'og:image', 'og:url', 'twitter:card', 'twitter:image'):
        assert re.search(rf'(property|name)="{name}" content="[^"]+"', raw), name
    image = re.search(rf'property="og:image" content="{home}([^"]+)"', raw).group(1)
    from PIL import Image
    assert Image.open(SITE.parent / image).size == (1200, 630)
    sitemap = (SITE.parent / 'sitemap.xml').read_text(encoding='utf-8')
    assert f'<loc>{home}</loc>' in sitemap and home + 'sitemap.xml' in (SITE.parent / 'robots.txt').read_text()


def test_the_download_offers_every_computer_and_finds_the_installers_ci_publishes():
    """Most visitors use Windows: without JavaScript the platforms read Windows first; with it, the visitor's own
    computer gets the button. The button picks the release asset whose name has "-<os>.", as CI names them."""
    raw = SITE.read_text(encoding='utf-8')
    assert re.findall(r'<a data-os="(\w+)"', raw) == ['windows', 'macos', 'linux']
    assert re.findall(r'<(?:div|p) class="[^"]*" data-os="(\w+)"', raw) == ['windows', 'macos', 'linux']   # first-open
    assert "a.name.includes('-' + k + '.')" in raw
    ci = (SITE.parents[1] / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    assets = re.findall(r'"\.\./(KinoDraw-\$\{\{ github\.ref_name \}\}-\w+\.[\w.]+)"', ci)
    assert sorted(re.search(r'-(\w+)\.', a.split('}}')[1]).group(1) for a in assets) == ['linux', 'macos', 'windows']

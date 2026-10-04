"""The download page (docs/index.html) as a stranger reads it right after downloading."""
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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



def test_every_mac_first_open_step_shows_its_screenshot():
    """0.2.0's page was ready to go out with two dashed "TODO (J): screenshot" boxes where the Open Anyway pictures belong."""
    raw = SITE.read_text(encoding='utf-8')
    assert 'class="shot todo"' not in raw
    mac = re.search(r'<div class="first-open" data-os="macos">.*?</ol>', raw, re.S).group(0)
    steps = re.findall(r'<li>.*?</li>', mac, re.S)
    assert len(steps) == 6
    for n, step in enumerate(steps, 1):
        img = re.search(r'<img class="shot" src="([^"]+)"[^>]*alt="([^"]+)"', step, re.S)
        assert img and img.group(1) == f'media/mac-open-{n}.jpg', n
        assert Path(SITE.parent, img.group(1)).stat().st_size < 300_000      # light enough for a phone


def test_the_licence_file_is_plain_mit_so_github_names_it():
    """GitHub showed the licence as "Other" while the art's CC BY terms sat in the same file."""
    root = SITE.parents[1]
    licence = (root / 'LICENSE').read_text(encoding='utf-8')
    assert licence.startswith('MIT License') and licence.rstrip().endswith('SOFTWARE.')
    assets = (root / 'LICENSES' / 'ASSETS.md').read_text(encoding='utf-8')
    assert 'CC BY 4.0' in assets and 'without attribution' in assets
    assert "ROOT / 'LICENSES'" in (root / 'packaging' / 'kinodraw.spec').read_text(encoding='utf-8')   # it ships in the apps

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


def test_a_mac_visitor_is_told_the_mac_app_needs_apple_silicon():
    """The Mac app is arm64 only and every Mac browser reports "Intel Mac OS X". The script removes the visitor's own
    platform link, which held the page's only "Apple silicon", and labelled the button "Download for macOS": an
    Intel Mac got a one-click download of an app that cannot run, with no warning."""
    raw = SITE.read_text(encoding='utf-8')
    assert re.search(r'<a data-os="macos"[^>]*>macOS \(Apple silicon, M1 or newer\)</a>', raw)    # without JavaScript
    script = re.search(r'<script>(.*?)</script>', re.sub(r'<!--.*?-->', '', raw, flags=re.S), re.S).group(1)
    mac = re.search(r"const mac = key === 'macos';(.*?)\n\s*try \{", script, re.S)               # with it, on a Mac,
    assert mac, 'no Mac branch before the release lookup (it must not depend on GitHub answering)'
    assert "'Needs a Mac with Apple silicon (M1 or newer), not an Intel Mac. Also for'" in mac.group(1)  # next to
    assert "'Download for ' + os + (mac ? ' (Apple silicon)' : '')" in mac.group(1)                      # the button
    box = raw[raw.index('<div class="first-open" data-os="macos">'):raw.index('<p class="small" data-os="linux">')]
    text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', box)).split())
    for words in ('Apple silicon (M1 or newer)', 'About This Mac', 'Chip', 'Processor'):    # Apple's own check
        assert words in text, words


def _check_platform_rows(rows, prelude=''):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    raw = SITE.read_text(encoding='utf-8')
    function = re.search(r'function kinodrawPlatform\(ua, uaData, touchPoints\) \{.*?^\}', raw, re.S | re.M)
    assert function, 'no pure platform detector'
    program = prelude + function.group(0) + '\nconst rows = ' + json.dumps(rows) + ';\n'
    program += 'console.log(JSON.stringify(rows.map(([ua, data, touch]) => kinodrawPlatform(ua, data ?? undefined, touch))));'
    run = subprocess.run([node, '-e', program], capture_output=True, text=True, check=True)
    results = json.loads(run.stdout)
    assert len(results) == len(rows)
    for row, result in zip(rows, results):
        assert result == row[3], row


def test_the_visitors_own_computer_is_detected():
    """Phones and Chromebooks need a computer; desktop UA overrides still win over conflicting desktop data."""
    mac = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
    windows = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    linux = 'Mozilla/5.0 (X11; Linux x86_64)'
    android = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36'
    rows = [
        (mac + ' AppleWebKit/537.36 Chrome/131.0 Safari/537.36', None, 0, 'macos'),
        (mac + ' AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15', None, 0, 'macos'),
        (mac + ' Version/18.0 Safari/605.1.15', None, 5, 'other'),
        ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', None, 5, 'other'),
        ('Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)', None, 5, 'other'),
        (windows + ' Chrome/131.0 Safari/537.36', None, 0, 'windows'),
        (windows + ' Chrome/131.0 Safari/537.36 Edg/131.0', None, 0, 'windows'),
        (windows + ' Gecko/20100101 Firefox/131.0', None, 0, 'windows'),
        ('Mozilla/5.0 (X11; Ubuntu; Linux x86_64) Gecko/20100101 Firefox/131.0', None, 0, 'linux'),
        (linux + ' Chrome/131.0 Safari/537.36', None, 0, 'linux'),
        ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36',
         {'platform': 'Android', 'mobile': False}, 5, 'other'),
        (mac, {'platform': 'iOS'}, 5, 'other'),
        (windows, {'platform': 'Windows', 'mobile': True}, 0, 'other'),
        (linux + ' Chrome/141.0 Safari/537.36', None, 0, 'linux'),
        (android, None, 5, 'other'),
        ('Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) Chrome/131.0', None, 0, 'other'),
        ('unknown browser', None, 0, None),
        (mac, {'platform': 'macOS', 'mobile': False}, 0, 'macos'),
        (linux, {'platform': 'Chrome OS'}, 0, 'other'),  # non-desktop uaData wins over a desktop-looking UA
        (android, {'platform': 'macOS'}, 5, 'other'),
        ('', {'platform': 'Windows'}, 0, 'windows'),
        (android, {'mobile': True, 'platform': 'Android'}, 5, 'other'),
        ('X11', None, 0, 'linux'),
        ('', {'platform': 'Linux'}, 0, 'linux'),
        ('', {'platform': 'macOS'}, 0, 'macos'),
        ('', {'platform': 'Chrome OS'}, 0, 'other'),
        ('', {'platform': 'Chromium OS'}, 0, 'other'),
        ('', {'platform': 'Android'}, 0, 'other'),
        ('', {'platform': 'iOS'}, 0, 'other'),
        ('', {'platform': 'unknown'}, 0, None),
        ('', {'platform': ''}, 0, None),
        ('', {'platform': 'constructor'}, 0, None),
        ('', {'mobile': True}, 0, 'other'),
        (windows, {'platform': 'macOS'}, 0, 'windows'),
    ]
    _check_platform_rows(rows)


def test_old_browsers_without_object_hasown_still_get_their_computer_first():
    """Older browsers detect computers without Object.hasOwn, including safe handling of inherited keys."""
    mac = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
    windows = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    linux = 'Mozilla/5.0 (X11; Linux x86_64)'
    rows = [
        (mac + ' AppleWebKit/605.1.15 Version/14.1 Safari/605.1.15', None, 0, 'macos'),
        (windows + ' Chrome/90.0 Safari/537.36', {'platform': 'Windows', 'mobile': False}, 0, 'windows'),
        (linux + ' Firefox/90.0', None, 0, 'linux'),
        ('', {'platform': 'constructor'}, 0, None),
    ]
    _check_platform_rows(rows, 'delete Object.hasOwn;\n')
    script = re.search(r'<script>(.*?)</script>', SITE.read_text(encoding='utf-8'), re.S).group(1)
    assert 'Object.hasOwn' not in script


def test_other_devices_are_told_to_open_the_page_on_a_computer():
    """A phone visitor should know why there is no installer for their device."""
    raw = SITE.read_text(encoding='utf-8')
    line = re.search(r'<p\b(?=[^>]*id="other-device")[^>]*>(.*?)</p>', raw, re.S)
    assert line and re.search(r'\bhidden(?:\s|>)', line.group(0))
    text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', line.group(1))).split())
    assert text.startswith('KinoDraw runs on Mac, Windows and Linux computers.')
    assert raw.index('id="other-device"') < raw.index('id="download"')


def test_visits_are_counted_only_by_cloudflares_cookieless_beacon_and_search_verification_waits_for_its_code():
    """The page loads one outside script, Cloudflare Web Analytics, and a placeholder code never makes a request."""
    raw = SITE.read_text(encoding='utf-8')
    live = re.sub(r'<!--.*?-->', '', raw, flags=re.S)
    assert re.findall(r'<script\b[^>]*\bsrc\s*=\s*"([^"]+)"', live) == ['https://static.cloudflareinsights.com/beacon.min.js']
    assert re.search(r"""data-cf-beacon='\{"token": "[0-9a-f]{32}"\}'""", live)
    assert 'YOUR_CLOUDFLARE_TOKEN' not in raw
    comments = re.findall(r'<!--(.*?)-->', raw, re.S)
    assert 'google-site-verification' in raw and 'google-site-verification' not in live
    assert any('google-site-verification' in comment and comment.lstrip().startswith('TODO(J):') for comment in comments)


def test_website_privacy_names_the_cookieless_counter_and_server_logs():
    """Visitors need to know that visit counts and hosting logs exist even without cookies."""
    raw = (SITE.parent / 'privacy.html').read_text(encoding='utf-8')
    text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', raw)).split())
    sentences = re.split(r'(?<=[.!?])\s+', text)
    assert any(all(words in sentence for words in ('Cloudflare Web Analytics', 'cookie', 'GitHub Pages', 'IP address'))
               for sentence in sentences)
    assert 'The app, the site and KinoDraw Cloud have no ads, no analytics' not in text
    assert not any('no analytics' in clause and re.search(r'\b(?:site|website)\b', clause)
                   for sentence in sentences for clause in sentence.split(';'))
    assert 'Last updated October 4, 2026' in text
    assert "GitHub's API for the latest release" in text
    assert 'cloudflareinsights' not in raw and 'google-site-verification' not in raw


def test_the_end_credit_is_disclosed_and_can_be_switched_off():
    """A video maker should know about the default closing card before downloading."""
    raw = SITE.read_text(encoding='utf-8')
    text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', raw)).split())
    for words in ('Made with KinoDraw', 'on by default', 'one click in the Studio turns it off', '--no-credit'):
        assert words in text
    sentence = next(sentence for sentence in re.split(r'(?<=[.!?])\s+', text) if 'Made with KinoDraw' in sentence)
    assert 'Settings' not in sentence
    root = SITE.parents[1]
    assert 'id="s-credit"' in (root / 'kinodraw/studio/static/app.js').read_text(encoding='utf-8')
    assert '--no-credit' in (root / 'kinodraw/cli.py').read_text(encoding='utf-8')


def test_the_download_script_stores_nothing_on_the_visitors_device():
    """Choosing a download must not leave cookies or persistent browser data behind."""
    raw = re.sub(r'<!--.*?-->', '', SITE.read_text(encoding='utf-8'), flags=re.S)
    scripts = '\n'.join(re.findall(r'<script\b[^>]*>(.*?)</script>', raw, re.S))
    assert scripts
    for storage in ('localStorage', 'sessionStorage', 'indexedDB', 'document.cookie'):
        assert storage not in scripts

"""The user guide (docs/user-guide.md, docs/user-guide.zh.md) says what KinoDraw really does: every button it names is
in the Studio, every command exists, every error message it explains is one KinoDraw shows, every link resolves, and
the Studio's Help page shows it in both languages."""
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kinodraw import cli, paths
from kinodraw.studio import guide, server
from studio_browser import studio_page  # noqa: F401 - the fixture

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
GUIDES = {'en': DOCS / 'user-guide.md', 'zh': DOCS / 'user-guide.zh.md'}
STUDIO_UI = ''.join(path.read_text(encoding='utf-8') for path in            # the page, and the names the server sends
                    (server.STATIC / 'index.html', server.STATIC / 'app.js', Path(server.__file__)))
SOURCE = ''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'kinodraw').rglob('*'))
                 if p.suffix in ('.py', '.js', '.html') and p.is_file())


def text(lang):
    return GUIDES[lang].read_text(encoding='utf-8')


@pytest.mark.parametrize('lang', GUIDES)
def test_every_button_and_label_the_guide_names_is_in_the_studio(lang):
    """Bold text in the guide is always a Studio label, written exactly as the Studio shows it (in English)."""
    labels = re.findall(r'\*\*(.+?)\*\*', text(lang))
    assert len(labels) >= 30
    assert [label for label in labels if label not in STUDIO_UI] == []


@pytest.mark.parametrize('lang', GUIDES)
def test_every_command_the_guide_names_exists(lang, monkeypatch, capsys):
    monkeypatch.setattr(paths, 'migrate', lambda *args, **kwargs: [])
    commands = set(re.findall(r'`kinodraw ([a-z][\w-]*)', text(lang)))
    assert commands
    for command in commands:
        with pytest.raises(SystemExit) as done:
            cli.main([command, '--help'])
        assert done.value.code == 0, command


@pytest.mark.parametrize('lang', GUIDES)
def test_every_message_in_troubleshooting_is_one_kinodraw_shows(lang):
    """Each > line (only Troubleshooting has them) is a message as KinoDraw writes it (the Studio's are in English);
    a leading … stands for a file name."""
    messages = [re.sub(r'^… ', '', m) for m in re.findall(r'^> (.+)$', text(lang), re.M)]
    assert len(messages) >= 8
    assert [m for m in messages if m not in SOURCE] == []


@pytest.mark.parametrize('lang', GUIDES)
def test_every_relative_link_and_picture_resolves(lang):
    targets = re.findall(r'\]\(([^)\s]+)\)', text(lang))
    local = [t for t in targets if not re.match(r'(https?|mailto):', t)]
    assert local
    assert [t for t in local if not (DOCS / t.split('#')[0]).is_file()] == []


def test_both_languages_have_the_same_sections_and_pictures():
    sections = {lang: re.findall(r'^## ', text(lang), re.M) for lang in GUIDES}
    assert len(sections['en']) == len(sections['zh']) >= 8
    pictures = {lang: re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text(lang)) for lang in GUIDES}
    assert pictures['en'] == pictures['zh'] and len(pictures['en']) >= 3


@pytest.mark.parametrize('lang', GUIDES)
def test_the_help_page_shows_all_of_the_guide(lang):
    page = guide.page(lang)
    assert page['html'].count('<h2') == len(re.findall(r'^## ', text(lang), re.M))
    for leftover in ('**', '](', '`', '<script'):
        assert leftover not in page['html']
    for src in re.findall(r'<img [^>]*src="([^"]+)"', page['html']):
        assert src.startswith('/guide/media/guide/') and (DOCS / src.removeprefix('/guide/')).is_file()


def test_the_help_page_is_served_and_its_pictures_need_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path, token=True):
        req = urllib.request.Request(url + path.lstrip('/'), headers={'X-Studio-Token': server.Handler.token} if token else {})
        try:
            with opener.open(req, timeout=10) as reply:
                return reply.status, reply.headers['Content-Type'], reply.read()
        except urllib.error.HTTPError as reply:
            return reply.code, reply.headers['Content-Type'], reply.read()
    try:
        status, _, body = get('/api/guide?lang=zh')
        assert status == 200 and 'KinoDraw 使用指南' in json.loads(body)['html']
        assert get('/api/guide?lang=fr')[0] == 400
        picture = re.search(r'<img [^>]*src="([^"]+)"', json.loads(body)['html']).group(1)
        status, kind, data = get(picture, token=False)
        assert status == 200 and kind == 'image/jpeg' and data[:2] == b'\xff\xd8'
        assert get('/guide/../user-guide.md', token=False)[0] == 404             # pictures only
        assert get('/guide/media/guide/../../user-guide.md', token=False)[0] == 404
        assert get('/api/guide?lang=en', token=False)[0] == 403
    finally:
        httpd.shutdown(); httpd.server_close()


def test_the_studio_and_the_website_link_to_the_guide():
    page = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    assert re.search(r'<button id="btn-help"[^>]*>Help</button>', page)
    site = (DOCS / 'index.html').read_text(encoding='utf-8')
    assert 'docs/user-guide.md' in site and 'docs/user-guide.zh.md' in site


def test_help_opens_the_guide_in_both_languages_in_a_real_browser(studio_page):
    assert '"passed":true' in studio_page('help')

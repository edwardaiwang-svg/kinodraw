"""Feedback from the Studio, with no sign-in: the form goes to KinoDraw Cloud (POST /v1/feedback) only when the user
presses Send, whichever director is chosen, with no cloud token. The email goes only when "I am 13 or older" is ticked,
and a failure keeps a plain sentence for the form to show (the page keeps what was typed)."""
import json
import re
import socket
import threading
import tomllib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import keyring
import pytest

from kinodraw import VERSION
from kinodraw.director.llm import cloud, providers
from kinodraw.studio import server

ROOT = Path(__file__).parents[1]
FORM = {'text': '  The doodles were great, the voice a bit fast.  ', 'rating': 4, 'use': 'school',
        'video_url': 'https://youtu.be/abc', 'quote_ok': True, 'age_13_plus': True, 'email': 'me@example.com'}


@pytest.fixture
def fake_cloud(monkeypatch, tmp_path):
    """A KinoDraw Cloud on 127.0.0.1 that records every request; ``reply[0]`` is the (status, body) it answers."""
    seen, reply = [], [(200, {'ok': True})]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            seen.append((self.path, self.headers.get('Authorization'), json.loads(body)))
            status, data = reply[0]
            if status is None:                                  # hangs up without an answer
                self.close_connection = True
                return
            out = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json' if isinstance(data, dict) else 'text/html')
            self.send_header('Content-Length', str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(cloud, 'URL', f'http://127.0.0.1:{httpd.server_address[1]}')
    monkeypatch.setattr(cloud, 'INSTALL_ID', tmp_path / 'install-id')
    monkeypatch.setattr(cloud, '_anon_token', None, raising=False)
    monkeypatch.setattr(providers, 'SAVED', tmp_path / 'saved-keys.json')
    for var in ('KINODRAW_CLOUD_TOKEN', 'DOODLE_CLOUD_TOKEN'):
        monkeypatch.delenv(var, raising=False)
    yield seen, reply
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def keychain(monkeypatch):
    """A keychain in memory: nothing reaches the real one, and the test sees anything written to it."""
    saved = {}
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: saved.get((service, name)))
    monkeypatch.setattr(keyring, 'set_password', lambda service, name, value: saved.__setitem__((service, name), value))
    return saved


@pytest.fixture
def studio(fake_cloud, keychain, tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    monkeypatch.setattr(providers, 'saved', lambda: set())                # nobody signed in, no key saved
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None):
        req = urllib.request.Request(url + path.lstrip('/'), method='GET' if body is None else 'POST',
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={'X-Studio-Token': server.Handler.token})
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
    yield call
    httpd.shutdown()


def test_send_goes_to_kinodraw_cloud_with_no_token_and_says_what_the_app_added(studio, fake_cloud, keychain):
    seen, _ = fake_cloud
    assert studio('/api/state')[1]['feedback_sent'] is False
    assert studio('/api/feedback', {**FORM, 'lang': 'zh', 'name': 'not a field'}) == (200, {'ok': True})
    path, auth, sent = seen[0]
    assert len(seen) == 1 and path == '/v1/feedback' and auth is None           # no /v1/anonymous, no Authorization
    assert sent == {**FORM, 'text': FORM['text'].strip(), 'install_id': cloud.install_id(), 'app_version': VERSION,
                    'os': server._computer(), 'lang': 'zh'}
    assert re.fullmatch(r'[0-9a-f]{32}', sent['install_id']) and sent['os'] in ('mac', 'windows', 'linux')
    assert keychain == {}                                                       # no cloud token made or kept
    assert json.loads(server.CONFIG.read_text(encoding='utf-8'))['feedback_sent'] is True     # studio.json
    assert studio('/api/state')[1]['feedback_sent'] is True


def test_the_email_is_dropped_unless_13_or_older_is_ticked(studio, fake_cloud):
    seen, _ = fake_cloud
    assert studio('/api/feedback', {**FORM, 'age_13_plus': False, 'email': 'kid@example.com'})[0] == 200
    assert 'email' not in seen[0][2] and seen[0][2]['age_13_plus'] is False
    assert studio('/api/feedback', {'text': 'Hi', 'quote_ok': False, 'age_13_plus': True, 'email': ' '})[0] == 200
    assert seen[1][2] == {'text': 'Hi', 'quote_ok': False, 'age_13_plus': True, 'install_id': cloud.install_id(),
                          'app_version': VERSION, 'os': server._computer(), 'lang': 'en'}   # the Studio's language


@pytest.mark.parametrize('change, words', [
    ({'text': '   '}, 'Write what you’d like to tell us first.'),
    ({'text': 'x' * 2001}, 'under 2,000 characters'),
    ({'rating': 6}, 'from 1 to 5'),
    ({'rating': '4'}, 'from 1 to 5'),
    ({'use': 'fun'}, 'from the list'),
    ({'video_url': 'ftp://example.com/v'}, 'http:// or https://'),
    ({'video_url': 'https://example.com/' + 'v' * 300}, 'up to 300 characters'),
    ({'email': 'not an email'}, 'email address doesn’t look right'),
    ({'email': 'a@b.c'}, 'email address doesn’t look right'),                  # as the cloud checks it
    ({'email': 'x:y@example.com'}, 'email address doesn’t look right'),
    ({'email': 'x' * 65 + '@example.com'}, 'email address doesn’t look right'),
    ({'video_url': 'https://example.com/a\tb'}, 'http:// or https://'),
    ({'video_url': 'https://'}, 'http:// or https://'),
    ({'quote_ok': None}, 'Tick or untick the boxes'),
    ({'age_13_plus': 'yes'}, 'Tick or untick the boxes'),
])
def test_a_mistake_is_said_plainly_and_nothing_is_sent(studio, fake_cloud, change, words):
    seen, _ = fake_cloud
    status, reply = studio('/api/feedback', {**FORM, **change})
    assert status == 400 and words in reply['error'] and seen == []
    assert 'feedback_sent' not in json.loads(server.CONFIG.read_text(encoding='utf-8'))


@pytest.mark.parametrize('answer, words', [
    ((429, {'error': 'You have sent a lot of feedback this hour. Please try again later.'}),
     'Your feedback wasn’t sent. You have sent a lot of feedback this hour. Please try again later.'),
    ((400, {'error': 'Write what you would like to tell us.'}), 'Your feedback wasn’t sent. Write what you would like'),
    ((500, {'error': 'D1_ERROR: no such table'}), 'Your feedback wasn’t sent. KinoDraw Cloud had a problem.'),
    ((404, {'error': 'not found'}), 'Your feedback wasn’t sent. KinoDraw Cloud can’t take feedback yet.'),
])
def test_a_refusal_from_the_cloud_is_a_plain_sentence(studio, fake_cloud, answer, words):
    seen, reply = fake_cloud
    reply[0] = answer
    status, out = studio('/api/feedback', FORM)
    assert status == 502 and out['error'].startswith(words) and len(seen) == 1
    assert 'D1_ERROR' not in out['error'] and '500' not in out['error']
    assert studio('/api/state')[1]['feedback_sent'] is False                 # the card still asks after the next video


def test_no_internet_is_a_plain_sentence_and_send_again_works(studio, fake_cloud, monkeypatch):
    seen, _ = fake_cloud
    working = cloud.URL
    with socket.socket() as closed:                                          # a port nothing listens on
        closed.bind(('127.0.0.1', 0))
        monkeypatch.setattr(cloud, 'URL', f'http://127.0.0.1:{closed.getsockname()[1]}')
    status, out = studio('/api/feedback', FORM)
    assert status == 502 and out['error'] == ('Your feedback wasn’t sent. KinoDraw Cloud can’t be reached. Check your '
                                              'internet connection and press Send again.')
    monkeypatch.setattr(cloud, 'URL', working)
    assert studio('/api/feedback', FORM) == (200, {'ok': True}) and len(seen) == 1


UNREACHABLE = 'Your feedback wasn’t sent. KinoDraw Cloud can’t be reached. Check your internet connection and press Send again.'


@pytest.mark.parametrize('answer', [(200, b'<html>Sign in to the school Wi-Fi</html>'), (None, None)])
def test_a_wifi_sign_in_page_or_a_hang_up_is_the_no_internet_sentence(studio, fake_cloud, answer):
    seen, reply = fake_cloud
    reply[0] = answer
    assert studio('/api/feedback', FORM) == (502, {'error': UNREACHABLE}) and len(seen) == 1
    assert studio('/api/state')[1]['feedback_sent'] is False


def test_a_cloud_that_never_answers_is_given_up_on_soon_with_the_same_sentence(studio, monkeypatch):
    waited = []

    def no_answer(request, timeout):
        waited.append(timeout)
        raise TimeoutError('timed out')
    monkeypatch.setattr(cloud, 'urlopen', no_answer)
    assert studio('/api/feedback', FORM) == (502, {'error': UNREACHABLE}) and waited[0] <= 30


def test_feedback_is_sent_with_an_offline_project_and_no_keychain(studio, fake_cloud, monkeypatch, tmp_path):
    """Cloud is offered by default but nobody signed in; sending feedback still makes no token, even when the
    keychain is missing (as CI's fail backend)."""
    from keyring.backends import fail
    seen, _ = fake_cloud
    broken = fail.Keyring()
    for name in ('get_password', 'set_password'):
        monkeypatch.setattr(keyring, name, getattr(broken, name))
    state = studio('/api/state')[1]
    assert state['default_director'] == 'cloud' and not state['cloud_signed_in']
    assert state['cloud'] is None and cloud._anon_token is None and seen == []
    assert studio('/api/feedback', FORM)[0] == 200
    assert [(path, auth) for path, auth, _ in seen] == [('/v1/feedback', None)] and cloud._anon_token is None
    assert studio('/api/state')[1]['install_id'] == cloud.install_id()        # Settings shows it, to ask for deletion


def test_the_version_feedback_names_is_the_packages():
    assert tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version'] == VERSION
    assert f"version='{VERSION}'" in (ROOT / 'packaging' / 'kinodraw.spec').read_text(encoding='utf-8')


def test_the_form_says_what_is_sent_and_keeps_github_as_a_choice():
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    page = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    assert '<button id="feedback" type="button">Feedback or a problem? Tell us</button>' in page
    assert 'Feedback or a problem?' in server._plain(RuntimeError('x'))        # a bug's message still points to it
    for words in ("Email, if you'd like a reply (optional)", 'I am 13 or older', 'Prefer GitHub?', 'Open an issue',
                  'KinoDraw may quote what I wrote, without my name, on its site and in reports about KinoDraw',
                  'How well did KinoDraw work for this video?', 'Link to your video, if you posted it',
                  'How did this video go? Tell us in 30 seconds', 'Send more feedback',
                  'what you typed and ticked, plus the app version, your computer type, language and install ID'):
        assert words in js, words
    assert 'https://github.com/edwardaiwang-svg/kinodraw/issues/new/choose' in js
    assert "email: f.age_13_plus ? f.email : undefined" in js                   # never sent unless 13+ is ticked


def test_readme_and_privacy_page_say_what_feedback_sends():
    for page in (ROOT / 'README.md', ROOT / 'docs' / 'privacy.html'):
        text = ' '.join(re.sub(r'<[^>]+>', ' ', page.read_text(encoding='utf-8')).split())
        for words in ('Feedback', 'api.doodlecloud.org', 'app version', 'computer type', 'install ID',
                      '13 or older', 'never with your name', 'privacy@doodlecloud.org', 'kinodraw cloud-id'):
            assert words in text, (page.name, words)

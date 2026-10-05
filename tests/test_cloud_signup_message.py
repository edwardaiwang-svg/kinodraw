"""When KinoDraw Cloud can't send the sign-in email (its email provider's limit, for example), the Studio and the command
line say so in one plain sentence, with the way to go on offline, instead of "KinoDraw Cloud 502: ..."."""
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kinodraw.director.llm import cloud, providers
from kinodraw.studio import server

SENTENCE = ("sign-in emails can't go out right now (today's limit is used up); try again in about 5 hours, "
            "or choose Offline to keep making videos without an account")


@pytest.fixture
def fake_cloud():
    """A KinoDraw Cloud that answers /v1/signup the way the updated worker does, or the way the first release's worker did."""
    reply = {'status': 502, 'body': {'error': SENTENCE, 'code': 'email_unavailable'}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length') or 0))
            data = json.dumps(reply['body']).encode()
            self.send_response(reply['status'])
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield reply, f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()


@pytest.fixture
def studio(tmp_path, monkeypatch, fake_cloud):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    monkeypatch.setattr(cloud, 'URL', fake_cloud[1])
    monkeypatch.setattr(providers, 'saved', lambda: set())
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def signup(email='someone@example.org'):
        req = urllib.request.Request(url + 'api/cloud/signup', data=json.dumps({'email': email}).encode(), method='POST',
                                     headers={'X-Studio-Token': server.Handler.token})
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
    yield signup
    httpd.shutdown()


def test_the_studio_gets_one_plain_sentence_without_the_status_prefix(studio):
    status, reply = studio()
    assert reply == {'error': SENTENCE[0].upper() + SENTENCE[1:] + '.', 'code': 'email_unavailable'}
    assert status == 503
    assert not re.search(r'KinoDraw Cloud \d|ProviderError|502', reply['error'])
    assert 'Offline' in reply['error']


def test_the_command_line_says_the_same_sentence(fake_cloud, monkeypatch):
    monkeypatch.setattr(cloud, 'URL', fake_cloud[1])
    with pytest.raises(cloud.EmailUnavailable) as raised:
        cloud.signup('someone@example.org')
    assert str(raised.value) == SENTENCE[0].upper() + SENTENCE[1:] + '.'


def test_login_prints_the_sentence_and_nothing_else(fake_cloud, monkeypatch, capsys):
    from kinodraw import cli
    monkeypatch.setattr(cloud, 'URL', fake_cloud[1])
    with pytest.raises(SystemExit) as raised:
        cli.cmd_login(type('Args', (), {'email': 'someone@example.org', 'code': None})())
    assert raised.value.code == '\n' + SENTENCE[0].upper() + SENTENCE[1:] + '.'


def test_any_other_cloud_refusal_still_names_its_status(studio, fake_cloud):
    fake_cloud[0].update(status=429, body={'error': 'too many codes requested; try again in an hour'})
    status, reply = studio()
    assert status == 500 and 'KinoDraw Cloud 429: too many codes requested; try again in an hour' in reply['error']


def _page_js():
    return (server.STATIC / 'app.js').read_text(encoding='utf-8')


def test_the_page_keeps_the_server_code_and_shows_the_sentence_in_settings():
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = _page_js()
    api = re.search(r'^async function api\(.*?^}', js, re.S | re.M)[0]
    handler = re.search(r"\$\('#c-send', body\)\?\.addEventListener\('click', async \(\) => \{\n(.*?)\n  \}\);", js, re.S)[1]
    stage = '''
const T = 't', toasts = [], els = {};
const $ = (sel) => (els[sel] = els[sel] || { textContent: '', value: 'someone@example.org', focus() {}, hidden: false,
  classList: { add: () => { els[sel].hidden = true; }, remove: () => { els[sel].hidden = false; } } });
const body = {};
const toast = (msg) => toasts.push(msg);
const fetch = async () => ({ ok: false, statusText: 'Service Unavailable',
  json: async () => ({ error: 'Sign-in emails can\\'t go out right now; try again later.', code: 'email_unavailable' }) });
'''
    run = stage + api + '\n(async () => {\n' + handler + '\nconsole.log(JSON.stringify({ toasts, note: els["#c-note"] }));\n})();'
    out = json.loads(subprocess.run([node, '-e', run], capture_output=True, text=True, check=True, encoding='utf-8').stdout)
    assert out['toasts'] == []                                    # no passing toast: the sentence stays in Settings
    assert out['note']['textContent'] == "Sign-in emails can't go out right now; try again later." and not out['note']['hidden']

"""KinoDraw Cloud with no account: while the cloud's open access is on, the app asks once for an anonymous token for this
installation and uses it like a sign-in. A 401 for a kept token (another cloud's, a revoked one, or open access ended)
makes the app forget it and ask once for a new one; when the cloud says no (403, or a 404 from a server before open
access), the app asks for an email sign-in as 0.2.0 did, in the cloud's words."""
import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import keyring
import pytest
from keyring.backends import fail

from kinodraw import ingest, script
from kinodraw.director.llm import cloud, providers
from kinodraw.director.llm.director import LLMDirector
from kinodraw.studio import server

FIX = Path(__file__).parent / 'fixtures'
SENTENCE = 'KinoDraw Cloud needs you to sign in again. Sign in with your email in Settings, or choose Offline.'
ISSUED = {'token': 'anon-token-1', 'plan': 'free', 'remaining': None, 'opus_remaining': 0, 'allowance_used': 0,
          'period_end': 1, 'anonymous': True}


@pytest.fixture
def fake_cloud(monkeypatch, tmp_path):
    """A KinoDraw Cloud on 127.0.0.1 that records every request; ``replies[path]`` is (status, body), or a function of
    the Authorization header that returns one."""
    seen, replies = [], {
        '/v1/anonymous': (200, ISSUED),
        '/v1/me': (200, {'plan': 'free', 'remaining': None}),
        '/v1/videos': (200, {'video_id': 'v1', 'model': 'gpt-6-luna'}),
        '/v1/direct': (502, {'error': 'the AI director is unavailable right now; this section keeps its offline plan'}),
    }

    class Handler(BaseHTTPRequestHandler):
        def _reply(self):
            body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            seen.append((self.path, self.headers.get('Authorization'), json.loads(body) if body else None))
            reply = replies.get(self.path, (404, {'error': 'not found'}))
            status, data = reply(self.headers.get('Authorization')) if callable(reply) else reply
            out = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = _reply

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
    yield seen, replies
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def keychain(monkeypatch):
    """A keychain in memory: nothing reaches the real one."""
    saved = {}
    monkeypatch.setattr(keyring, 'get_password', lambda service, name: saved.get((service, name)))
    monkeypatch.setattr(keyring, 'set_password', lambda service, name, value: saved.__setitem__((service, name), value))

    def delete(service, name):
        if (service, name) not in saved:
            raise keyring.errors.PasswordDeleteError(name)
        del saved[(service, name)]
    monkeypatch.setattr(keyring, 'delete_password', delete)
    return saved


def _paths(seen):
    return [path for path, *_ in seen]


def _new_process(monkeypatch):
    monkeypatch.setattr(cloud, '_anon_token', None, raising=False)


def test_no_sign_in_gets_one_anonymous_token_and_keeps_using_it(fake_cloud, keychain, monkeypatch):
    seen, _ = fake_cloud
    provider = providers.make_provider('cloud')
    provider.open_video(2, 100)
    assert seen[0] == ('/v1/anonymous', None, {'install_id': cloud.install_id()})
    assert re.fullmatch(r'[0-9a-f]{32}', cloud.install_id())                       # a random ID, no email
    assert seen[1][:2] == ('/v1/videos', 'Bearer anon-token-1')
    assert keychain == {('KinoDraw', 'cloud-anon-token'): 'anon-token-1'}           # never the sign-in's entry
    _new_process(monkeypatch)
    providers.make_provider('cloud').open_video(2, 100)
    assert _paths(seen) == ['/v1/anonymous', '/v1/videos', '/v1/videos']             # asked for once
    assert seen[2][1] == 'Bearer anon-token-1'
    assert not server.state()['cloud_signed_in']                                     # "Signed in" is for email sign-ins


def test_an_email_sign_in_always_wins(fake_cloud, keychain, monkeypatch):
    seen, _ = fake_cloud
    keychain[('KinoDraw', 'cloud-anon-token')] = 'anon-token-1'
    keychain[('KinoDraw', 'cloud-token')] = 'email-token'
    providers.make_provider('cloud').open_video(2, 100)
    monkeypatch.setenv('KINODRAW_CLOUD_TOKEN', 'ci-token')
    providers.make_provider('cloud').open_video(2, 100)
    assert seen == [('/v1/videos', 'Bearer email-token', {'sections': 2, 'characters': 100}),
                    ('/v1/videos', 'Bearer ci-token', {'sections': 2, 'characters': 100})]


def test_open_access_off_asks_for_a_sign_in_in_the_clouds_words(fake_cloud, keychain):
    seen, replies = fake_cloud
    replies['/v1/anonymous'] = (403, {'error': SENTENCE})
    with pytest.raises(cloud.SignInNeeded) as raised:
        providers.make_provider('cloud')
    assert str(raised.value) == SENTENCE and keychain == {}
    assert _paths(seen) == ['/v1/anonymous']


def test_a_server_from_before_open_access_gets_0_2_0s_sign_in_message(fake_cloud, keychain):
    """The cloud live before the owner deploys answers 404 {"error": "not found"} for /v1/anonymous."""
    seen, replies = fake_cloud
    del replies['/v1/anonymous']
    with pytest.raises(cloud.SignInNeeded) as raised:
        providers.make_provider('cloud')
    assert str(raised.value) == 'sign in to KinoDraw Cloud first (Studio > KinoDraw Cloud, or `kinodraw login`)'
    assert keychain == {} and _paths(seen) == ['/v1/anonymous']


def test_a_refused_anonymous_token_is_forgotten_and_the_video_finishes_offline(fake_cloud, keychain, monkeypatch):
    """Open access ended after the token was issued: the app asks once for a new token, gets the sign-in sentence,
    plans this video offline (as 0.2.0 does when the cloud refuses a video), and the next video asks once again."""
    seen, replies = fake_cloud
    keychain[('KinoDraw', 'cloud-anon-token')] = 'anon-token-1'
    replies['/v1/videos'] = (401, {'error': SENTENCE})
    replies['/v1/anonymous'] = (403, {'error': SENTENCE})
    board = script.build(ingest.read(FIX / 'printing_press.md'))
    report = LLMDirector(providers.make_provider('cloud'), 'en').direct(board)
    assert report['notes'] == [f'The offline director planned this video ({SENTENCE})']
    assert keychain == {} and _paths(seen) == ['/v1/videos', '/v1/anonymous']
    _new_process(monkeypatch)
    with pytest.raises(cloud.SignInNeeded, match='needs you to sign in again'):
        providers.make_provider('cloud')
    assert _paths(seen) == ['/v1/videos', '/v1/anonymous', '/v1/anonymous']          # no loop of new tokens


def _stale(replies, *paths):
    """The cloud doesn't know the token 'stale' (another cloud's, or revoked): 401 "sign in again", as authed() says."""
    for path in paths:
        ok = replies[path]
        replies[path] = lambda auth, ok=ok: (401, {'error': 'sign in again'}) if auth == 'Bearer stale' else ok


def test_a_kept_token_this_cloud_does_not_know_is_replaced_once_while_open_access_is_on(fake_cloud, keychain, tmp_path,
                                                                                         capsys, monkeypatch):
    from kinodraw import cli
    seen, replies = fake_cloud
    keychain[('KinoDraw', 'cloud-anon-token')] = 'stale'
    _stale(replies, '/v1/videos', '/v1/direct')
    cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'p'), '--director', 'cloud'])
    assert _paths(seen)[:3] == ['/v1/videos', '/v1/anonymous', '/v1/videos'] and '/v1/direct' in _paths(seen)
    assert seen[0][1] == 'Bearer stale' and all(auth == 'Bearer anon-token-1' for path, auth, _ in seen[2:])
    assert keychain == {('KinoDraw', 'cloud-anon-token'): 'anon-token-1'}
    assert 'sign in' not in capsys.readouterr().out.lower()


def test_a_new_token_the_cloud_also_refuses_is_not_replaced_again(fake_cloud, keychain):
    seen, replies = fake_cloud
    keychain[('KinoDraw', 'cloud-anon-token')] = 'stale'
    replies['/v1/videos'] = (401, {'error': SENTENCE})
    with pytest.raises(cloud.SignInNeeded, match='needs you to sign in again'):
        providers.make_provider('cloud').open_video(2, 100)
    assert _paths(seen) == ['/v1/videos', '/v1/anonymous', '/v1/videos'] and keychain == {}


def test_a_401_mid_video_keeps_the_other_sections_offline_without_asking_again(fake_cloud, keychain):
    seen, replies = fake_cloud
    replies['/v1/direct'] = (401, {'error': SENTENCE})
    board = script.build(ingest.read(FIX / 'printing_press.md'))
    report = LLMDirector(providers.make_provider('cloud'), 'en').direct(board)
    assert len(report['notes']) > 1 and all(n.endswith(f': kept the offline plan ({SENTENCE})') for n in report['notes'])
    assert _paths(seen) == ['/v1/anonymous', '/v1/videos', '/v1/direct'] and keychain == {}


SPANISH = ('# Las abejas\n\nLas abejas visitan muchas flores para hacer miel.\n\n## El banco\n\n'
           'El banco guarda dinero y monedas para el ahorro. La imprenta produce libros.\n')


@pytest.mark.parametrize('open_access', [True, False])
def test_a_language_the_cloud_does_not_plan_never_asks_it_for_a_token(fake_cloud, keychain, tmp_path, open_access):
    """A Spanish video with KinoDraw Cloud and no sign-in is planned offline, open access on or off: nothing is sent,
    no installation ID is made and no sign-in is asked for."""
    from kinodraw import director
    seen, replies = fake_cloud
    if not open_access:
        replies['/v1/anonymous'] = (403, {'error': SENTENCE})
    project = tmp_path / 'p'
    project.mkdir()
    (project / 'storyboard.json').write_text(json.dumps(script.build(ingest.read(SPANISH))), encoding='utf-8')
    report = director.direct(project, 'cloud')
    assert report['notes'] == ['The offline director planned this video (KinoDraw Cloud plans English and Chinese '
                               'videos only; no cloud video was used)']
    assert seen == [] and keychain == {} and not cloud.INSTALL_ID.exists()


def test_without_a_keychain_the_token_lasts_for_the_process(fake_cloud, monkeypatch):
    seen, _ = fake_cloud
    broken = fail.Keyring()
    for name in ('get_password', 'set_password', 'delete_password'):
        monkeypatch.setattr(keyring, name, getattr(broken, name))
    providers.make_provider('cloud').open_video(2, 100)
    providers.make_provider('cloud').open_video(2, 100)
    assert _paths(seen) == ['/v1/anonymous', '/v1/videos', '/v1/videos']
    assert seen[2][1] == 'Bearer anon-token-1'


def test_the_cli_makes_a_cloud_directed_storyboard_without_kinodraw_login(fake_cloud, keychain, tmp_path, capsys):
    from kinodraw import cli
    seen, _ = fake_cloud
    cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'p'), '--director', 'cloud'])
    assert _paths(seen)[:2] == ['/v1/anonymous', '/v1/videos'] and '/v1/direct' in _paths(seen)
    assert all(auth == 'Bearer anon-token-1' for path, auth, _ in seen[1:])
    assert 'sign in' not in capsys.readouterr().out.lower()


def test_kinodraw_cloud_id_prints_the_id_to_ask_for_its_data_to_be_deleted(fake_cloud, keychain, capsys):
    from kinodraw import cli
    cli.main(['cloud-id'])
    assert 'no KinoDraw Cloud ID on this computer' in capsys.readouterr().out and not cloud.INSTALL_ID.exists()
    providers.make_provider('cloud')
    cli.main(['cloud-id'])
    out = capsys.readouterr().out
    assert cloud.install_id() in out and 'privacy@doodlecloud.org' in out


# ------------------------------------------------------------------ Studio
@pytest.fixture
def studio(fake_cloud, keychain, tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    monkeypatch.setattr(providers, 'saved', lambda: set())                # nobody signed in
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, method='GET'):
        req = urllib.request.Request(url + path.lstrip('/'), method=method, data=b'{}' if method == 'POST' else None,
                                     headers={'X-Studio-Token': server.Handler.token})
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
    yield call
    httpd.shutdown()


def test_the_studio_offers_cloud_with_no_sign_in_and_still_starts_offline(studio, fake_cloud, keychain):
    seen, _ = fake_cloud
    state = studio('/api/state')[1]
    assert state['cloud_available'] and not state['cloud_signed_in'] and state['default_director'] == 'rules'
    assert seen == []                                                     # nothing leaves before Cloud is chosen
    assert state['install_id'] is None                                   # no ID is made before Cloud is chosen
    status, reply = studio('/api/cloud/anonymous', 'POST')
    assert status == 200 and reply == {k: v for k, v in ISSUED.items() if k != 'token'} | {'install_id': cloud.install_id()}
    assert 'anon-token-1' not in json.dumps(reply)
    status, reply = studio('/api/cloud/anonymous', 'POST')               # the kept token, checked with the cloud
    assert status == 200 and reply['anonymous'] and _paths(seen) == ['/v1/anonymous', '/v1/me']
    state = studio('/api/state')[1]
    assert not state['cloud_signed_in'] and state['install_id'] == cloud.install_id()      # Settings shows it


def test_the_studio_shows_the_sign_in_when_the_cloud_asks_for_it(studio, fake_cloud, keychain):
    _, replies = fake_cloud
    replies['/v1/anonymous'] = (403, {'error': SENTENCE})
    assert studio('/api/cloud/anonymous', 'POST') == (403, {'error': SENTENCE, 'code': 'sign_in'})
    del replies['/v1/anonymous']
    assert studio('/api/cloud/anonymous', 'POST') == (403, {'error': server.SIGN_IN, 'code': 'sign_in'})
    keychain[('KinoDraw', 'cloud-anon-token')] = 'anon-token-1'
    replies['/v1/me'] = (401, {'error': SENTENCE})
    replies['/v1/anonymous'] = (403, {'error': SENTENCE})                  # open access ended: asked once, then no
    assert studio('/api/cloud/anonymous', 'POST') == (403, {'error': SENTENCE, 'code': 'sign_in'})
    assert keychain == {}


def test_the_studio_replaces_a_kept_token_this_cloud_does_not_know(studio, fake_cloud, keychain):
    seen, replies = fake_cloud
    keychain[('KinoDraw', 'cloud-anon-token')] = 'stale'
    _stale(replies, '/v1/me')
    status, reply = studio('/api/cloud/anonymous', 'POST')
    assert status == 200 and reply == {k: v for k, v in ISSUED.items() if k != 'token'} | {'install_id': cloud.install_id()}
    assert _paths(seen) == ['/v1/me', '/v1/anonymous'] and keychain == {('KinoDraw', 'cloud-anon-token'): 'anon-token-1'}


def _js():
    return (server.STATIC / 'app.js').read_text(encoding='utf-8')


def test_the_page_no_longer_says_cloud_needs_a_sign_in():
    js = _js()
    assert '5 free videos a month' not in js and 'sign in with an email code first' not in js.lower()
    assert 'no account or API key' in js


def test_create_goes_ahead_without_a_sign_in_and_opens_it_only_when_the_cloud_asks():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = _js()
    api = re.search(r'^async function api\(.*?^}', js, re.S | re.M)[0]
    gate = re.search(r'^async function needsCloudSignIn\(.*?^}', js, re.S | re.M)[0]
    stage = '''
const T = 't', toasts = [], opened = [];
const toast = (msg) => toasts.push(msg);
const showSettings = () => opened.push('settings');
let STATE = { cloud_signed_in: false, cloud: null, cloud_languages: ['en', 'zh'] }, cloudAsks = '';
let reply;
const fetch = async () => reply;
'''
    run = stage + api + '\n' + gate + '''
(async () => {
  const out = [];
  reply = { ok: true, json: async () => ({ plan: 'free', remaining: null, anonymous: true }) };
  out.push([await needsCloudSignIn('cloud', 'en'), toasts.length, opened.length, STATE.cloud?.anonymous]);
  reply = { ok: false, statusText: 'Forbidden', json: async () => ({ error: 'Sign in, please.', code: 'sign_in' }) };
  out.push([await needsCloudSignIn('cloud', 'en'), toasts.slice(), opened.length, STATE.cloud, cloudAsks]);
  out.push([await needsCloudSignIn('rules', 'en')]);
  console.log(JSON.stringify(out));
})();'''
    out = json.loads(subprocess.run([node, '-e', run], capture_output=True, text=True, check=True, encoding='utf-8').stdout)
    assert out == [[False, 0, 0, True], [True, ['Sign in, please.'], 1, None, 'Sign in, please.'], [False]]


def test_create_never_asks_for_a_sign_in_for_a_language_the_cloud_does_not_plan():
    assert server.state()['cloud_languages'] == ['en', 'zh']
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = _js()
    api = re.search(r'^async function api\(.*?^}', js, re.S | re.M)[0]
    gate = re.search(r'^async function needsCloudSignIn\(.*?^}', js, re.S | re.M)[0]
    stage = '''
const T = 't', toasts = [], opened = [], asked = [];
const toast = (msg) => toasts.push(msg);
const showSettings = () => opened.push('settings');
let STATE = { cloud_signed_in: false, cloud: null, cloud_languages: ['en', 'zh'] }, cloudAsks = '';
const fetch = async (url) => (asked.push(url), { ok: false, statusText: 'Forbidden',
                                                 json: async () => ({ error: 'Sign in, please.', code: 'sign_in' }) });
'''
    run = stage + api + '\n' + gate + '''
(async () => {
  const out = [];
  out.push([await needsCloudSignIn('cloud', 'es'), toasts.length, opened.length, asked.length, cloudAsks]);
  out.push([await needsCloudSignIn('cloud', 'en'), toasts.length, opened.length, asked.length, cloudAsks]);
  console.log(JSON.stringify(out));
})();'''
    out = json.loads(subprocess.run([node, '-e', run], capture_output=True, text=True, check=True, encoding='utf-8').stdout)
    assert out == [[False, 0, 0, 0, ''], [True, 1, 1, 1, 'Sign in, please.']]


def test_choosing_cloud_in_the_menu_when_it_asks_for_a_sign_in_never_says_no_account_is_needed():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = _js()
    api = re.search(r'^async function api\(.*?^}', js, re.S | re.M)[0]
    note = re.search(r'^  const note = \(\) => \{\n.*?^  \};', js, re.S | re.M)[0]
    pick = re.search(r'^  dirSel\.onchange = async \(\) => \{\n.*?^  \};', js, re.S | re.M)[0]
    settings = re.search(r"^  const cloud = STATE\.cloud_available \? `.*?` : '';", js, re.S | re.M)[0]
    stage = '''
const T = 't', els = {};
const $ = (sel) => (els[sel] = els[sel] || { textContent: '', placeholder: '', classList: { toggle() {} } });
const esc = (s) => String(s ?? '');
const dirSel = { value: 'cloud' }, cloudEmail = '', asked = [];
let STATE = { cloud_available: true, cloud_signed_in: false, cloud: null, cloud_languages: ['en', 'zh'], models: {}, keys: {} }, cloudAsks = '';
let reply, lang = 'en';
const voiceLang = () => lang;
const fetch = async (url) => (asked.push(url), reply);
const syncStyle = () => {};     // 0.3.0's Style menu follows the director; not under test here
const settingsText = () => { ''' + settings + ''' return cloud.match(/<p class="muted">([^<]*)/)[1].trim(); };
'''
    run = stage + api + '\n' + note + '\n' + pick + '''
(async () => {
  const out = [settingsText()];
  for (const [status, body] of [[403, { error: 'Sign in with your email in Settings, or choose Offline.', code: 'sign_in' }],
                                [200, { plan: 'free', remaining: null, anonymous: true }]]) {
    reply = { ok: status === 200, statusText: 'x', json: async () => body };
    STATE.cloud = null;
    await dirSel.onchange();
    out.push([els['#director-note'].textContent, settingsText()]);
  }
  lang = 'es'; STATE.cloud = null; asked.length = 0;      // a Spanish video: the cloud never plans it, so is never asked
  await dirSel.onchange();
  out.push([asked, STATE.cloud]);
  console.log(JSON.stringify(out));
})();'''
    out = json.loads(subprocess.run([node, '-e', run], capture_output=True, text=True, check=True, encoding='utf-8').stdout)
    unknown, asks, allowed, spanish = out
    assert 'while KinoDraw Cloud allows it' in unknown                 # Settings before the cloud was asked: no promise
    assert asks == ['Sign in with your email in Settings, or choose Offline.'] * 2
    assert allowed == ['KinoDraw Cloud, free plan: unlimited videos (fair use).',
                       'Free, with no account or API key. Signing in with your email is optional.']
    assert spanish == [[], None]


def test_settings_shows_the_installation_id_once_kinodraw_cloud_was_used():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    settings = re.search(r"^  const cloud = STATE\.cloud_available \? `.*?` : '';", _js(), re.S | re.M)[0]
    run = """
const esc = (s) => String(s ?? ''), cloudEmail = '', cloudAsks = '', out = [];
for (const STATE of [{ cloud_available: true, cloud: null, install_id: null },
                     { cloud_available: true, cloud: { plan: 'free', remaining: null, install_id: 'a1' }, install_id: null },
                     { cloud_available: true, cloud: null, install_id: 'b2' }]) {
  """ + settings + """
  out.push((cloud.match(/This installation's ID: <code>(\\w+)<\\/code>.*?privacy@doodlecloud\\.org/) || [null, null])[1]);
}
console.log(JSON.stringify(out));"""
    out = json.loads(subprocess.run([node, '-e', run], capture_output=True, text=True, check=True, encoding='utf-8').stdout)
    assert out == [None, 'a1', 'b2']

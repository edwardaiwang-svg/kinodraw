""""Choose for me" on the Style menu: the video's director picks a style that works for this video (director/style.py).
KinoDraw Cloud is a local fake here; nothing reaches the real service."""
import json
import socket
import sys
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from kinodraw import ingest, pipeline, styles
from kinodraw.director import style
from kinodraw.director.llm import cloud, providers
from kinodraw.studio import server

MATH = ('# Fractions made easy\n\nA fraction is part of a whole, and math teachers love fractions.\n\n'
        '## Adding fractions\n\nTo add fractions, find a common denominator. The formula is short.\n\n'
        '## Equations\n\nAn equation with fractions is still an equation.\n')
ROME = ('# The Roman Empire\n\nAncient Rome grew from a village into an empire.\n\n## Emperors\n\n'
        'Every emperor built a temple.\n\n## The fall\n\nThe empire split in two.\n')
PLAIN = '# Why we sleep\n\nSleep helps the body rest.\n\n## Dreams\n\nDreams come at night.\n\n## Habits\n\nGo to bed on time.\n'


class FakeCloud:
    """KinoDraw Cloud on 127.0.0.1: answers /v1/style with ``self.pick`` and records every request."""

    def __init__(self):
        self.pick, self.seen = {'style': 'chalkboard/explain', 'reason': 'A math lesson suits a chalkboard'}, []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fake.seen.append({'path': self.path, 'body': body, 'auth': self.headers.get('Authorization')})
                if self.path == '/v1/style':
                    out = {'pick': fake.pick, 'usage': {'model': 'gpt-6-luna', 'input_tokens': 300, 'output_tokens': 20}}
                elif self.path.endswith('/chat/completions'):      # an OpenAI-compatible server (own-key path)
                    out = {'id': 'x', 'object': 'chat.completion', 'created': 0, 'model': body['model'],
                           'choices': [{'index': 0, 'finish_reason': 'stop',
                                        'message': {'role': 'assistant', 'content': json.dumps(fake.pick)}}],
                           'usage': {'prompt_tokens': 300, 'completion_tokens': 20, 'total_tokens': 320}}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def fake_cloud(monkeypatch):
    fake = FakeCloud()
    monkeypatch.setattr(cloud, 'URL', fake.url)
    monkeypatch.setenv('KINODRAW_CLOUD_TOKEN', 'test-token')
    yield fake
    fake.httpd.shutdown()


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """create_project as the Studio runs it; planning the visuals is stubbed (it is tested elsewhere)."""
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    monkeypatch.setattr(server.director, 'direct', lambda *a, **k: {'notes': [], 'usage': None})

    def create(**body):
        created = server.create_project({'text': MATH, 'title': 'Fractions', 'look': 'auto', **body})
        job = server.JOBS.get(created['job'])
        deadline = time.monotonic() + 20
        while job['state'] not in ('done', 'failed') and time.monotonic() < deadline:
            time.sleep(.02)
        assert job['state'] == 'done', job['error']
        path = tmp_path / 'videos' / created['project']
        return job['result'], pipeline.storyboard(path), pipeline.settings(path), created['project']
    return create


def _no_network(monkeypatch):
    def connect(*args, **kwargs):
        raise AssertionError('Choose for me used the network')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(socket, 'create_connection', connect)


def test_kinodraw_cloud_picks_and_the_pick_is_saved_and_shown(studio, fake_cloud):
    result, board, cfg, _ = studio(director='cloud')
    assert (board['look'], board['story']) == ('chalkboard', 'explain')
    pick = cfg['style_pick']
    assert pick['by'] == 'cloud' and pick['style'] == 'chalkboard/explain' and pick['label'] == 'Chalkboard'
    assert pick['reason'] == 'A math lesson suits a chalkboard' and result['style'] == pick
    [call] = fake_cloud.seen                                    # one request, before the storyboard; never a video
    assert call['path'] == '/v1/style' and call['auth'] == 'Bearer test-token'
    sent = call['body']
    assert sent['title'] == 'Fractions' and sent['headings'] == ['Adding fractions', 'Equations']
    assert sent['format'] == '16:9' and sent['language'] == 'en' and len(sent['excerpt']) <= style.EXCERPT
    assert set(sent) == {'language', 'title', 'headings', 'excerpt', 'format', 'options'}   # nothing else goes


def test_a_pick_outside_the_offer_is_not_used(studio, fake_cloud, monkeypatch):
    for wrong in ('bold/promo', 'collage/promo', 'whiteboard/promo', 'comic/explain'):   # not ready, no product, made up
        fake_cloud.pick = {'style': wrong, 'reason': 'x'}
        _, board, cfg, _ = studio(director='cloud', title=f'Fractions {wrong}')
        pick = cfg['style_pick']
        assert pick['by'] == 'rules' and pick['style'] == 'chalkboard/explain', pick       # the offline word rules
        assert board['look'] == 'chalkboard' and 'cannot use' in pick['note'] and 'KinoDraw Cloud AI' in pick['note']
    monkeypatch.delenv('KINODRAW_CLOUD_TOKEN')                  # signed out: the offline rules pick, and say why
    monkeypatch.setattr(cloud, '_token', lambda: None)
    _, _, cfg, _ = studio(director='cloud', title='Signed out')
    assert cfg['style_pick']['by'] == 'rules' and 'sign in' in cfg['style_pick']['note']


def test_only_styles_that_render_the_format_and_language_are_offered(studio, fake_cloud, monkeypatch):
    looks = tuple({**e, 'aspect': ['16:9']} if e['id'] == 'mosaic' else e for e in styles._looks())
    monkeypatch.setattr(styles, '_looks', lambda: looks)        # a landscape-only look
    assert 'mosaic/explain' in [o['id'] for o in style.options('16:9', 'en', None)]
    assert 'mosaic/explain' not in [o['id'] for o in style.options('9:16', 'en', None)]
    assert 'pixel_quest/explain' not in [o['id'] for o in style.options('16:9', 'es', None)]   # en and zh only
    fake_cloud.pick = {'style': 'mosaic/explain', 'reason': 'Ancient'}
    _, board, cfg, _ = studio(director='cloud', text=ROME, title='Rome tall', aspect='9:16')
    assert board['look'] != 'mosaic' and cfg['style_pick']['by'] == 'rules' and cfg['aspect'] == '9:16'
    assert 'mosaic/explain' not in [o['id'] for o in fake_cloud.seen[-1]['body']['options']]
    _, board, cfg, _ = studio(director='cloud', text=ROME, title='Rome wide', aspect='16:9')
    assert board['look'] == 'mosaic' and cfg['style_pick']['by'] == 'cloud'
    assert style.offline(ingest.read(ROME), [o['id'] for o in style.options('9:16', 'en', None)], 'en')['style'] \
        == 'whiteboard/explain'                                 # the offline rules keep to the offer too


def test_the_promo_is_picked_only_for_a_named_product(studio, fake_cloud):
    assert 'collage/promo' not in [o['id'] for o in style.options('16:9', 'en', None)]
    assert 'collage/promo' not in [o['id'] for o in style.options('16:9', 'en', {'url': 'example.com'})]
    assert 'collage/promo' in [o['id'] for o in style.options('16:9', 'en', {'name': 'Fizz'})]
    brand = {'name': 'Fizz', 'url': 'fizz.example', 'cta': 'Try it'}
    fake_cloud.pick = {'style': 'collage/promo', 'reason': 'A product launch'}
    _, board, cfg, _ = studio(director='cloud', title='Fizz promo', brand=brand)
    assert (board['look'], board['story'], board['brand']) == ('collage', 'promo', brand)
    fake_cloud.pick = {'style': 'chalkboard/explain', 'reason': 'Math'}
    _, board, _, _ = studio(director='cloud', title='Fizz lesson', brand=brand)
    assert board['look'] == 'chalkboard' and 'brand' not in board        # no promo, so no product on the board
    _, board, cfg, _ = studio(director='rules', title='Fizz offline', brand=brand)
    assert board['look'] == 'collage' and cfg['style_pick']['by'] == 'rules'


def test_offline_choose_for_me_never_uses_the_network(studio, monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(providers, 'make_provider', lambda *a, **k: pytest.fail('Offline asked an AI'))
    picks = {}
    for name, text in (('Math', MATH), ('Rome', ROME), ('Sleep', PLAIN)):
        _, board, cfg, _ = studio(director='rules', text=text, title=name)
        assert cfg['style_pick']['by'] == 'rules' and 'note' not in cfg['style_pick']
        picks[name] = board['look']
    assert picks == {'Math': 'chalkboard', 'Rome': 'mosaic', 'Sleep': 'whiteboard'}


def test_own_key_directors_pick_through_the_same_call(studio, fake_cloud, tmp_path, monkeypatch):
    program = tmp_path / 'pick.py'                              # "My own command": gets the schema, prints the pick
    program.write_text('import json, sys\nreq = json.load(sys.stdin)\n'
                       'json.dump({"seen": req}, open(sys.argv[1], "w"))\n'
                       'print(json.dumps({"style": "notebook/explain", "reason": "Study notes"}))\n')
    log = tmp_path / 'seen.json'
    monkeypatch.setenv('KINODRAW_DIRECTOR_COMMAND', f'"{sys.executable}" "{program}" "{log}"')
    monkeypatch.setattr(providers, 'api_key', lambda name: providers.paths.getenv(providers.KEY_ENV[name]))
    _, board, cfg, _ = studio(director='command', title='By command')
    assert board['look'] == 'notebook' and cfg['style_pick']['by'] == 'command'
    seen = json.loads(log.read_text())['seen']
    assert seen['schema']['properties']['style']['enum'] == [o['id'] for o in json.loads(seen['user'])['options']]
    fake_cloud.pick = {'style': 'pixel_quest/explain', 'reason': 'Playful'}   # an OpenAI-compatible server
    _, board, cfg, _ = studio(director='compat', title='By server', model='local-model', base_url=fake_cloud.url + '/v1')
    assert board['look'] == 'pixel_quest' and cfg['style_pick']['by'] == 'compat'
    assert fake_cloud.seen[-1]['path'] == '/v1/chat/completions' and fake_cloud.seen[-1]['body']['model'] == 'local-model'


def test_re_planning_keeps_the_pick(studio, fake_cloud, monkeypatch):
    _, _, cfg, name = studio(director='cloud')
    monkeypatch.setattr(style, 'choose', lambda *a, **k: pytest.fail('re-plan picked a style again'))
    job = server.JOBS.get(server.redirect(name, {'director': 'cloud'})['job'])
    while job['state'] not in ('done', 'failed'):
        time.sleep(.02)
    assert job['state'] == 'done', job['error']
    path = server.projects_root() / name
    assert pipeline.storyboard(path)['look'] == 'chalkboard' and pipeline.settings(path)['style_pick'] == cfg['style_pick']
    assert len(fake_cloud.seen) == 1


def test_the_style_menu_offers_choose_for_me_named_by_its_director():
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    html = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    assert 'id="style-auto" value="auto"' in js and 'Choose for me (${' in js
    for mode, who in style.BY.items():                         # the menu names who decides, as the pick does
        assert f"{mode}: '{who.removeprefix('the ')}'" in js, mode
    assert f'first {style.EXCERPT} characters' in js            # what the AI sees, as the page says
    assert 'id="style-note"' in html and 'id="p-style"' in html


def test_readme_and_privacy_page_say_what_choose_for_me_sends():
    root = Path(__file__).parents[1]
    for page in (root / 'README.md', root / 'docs' / 'privacy.html'):
        text = ' '.join(page.read_text(encoding='utf-8').split())
        assert 'Choose for me' in text and f'first {style.EXCERPT} characters' in text, page.name


def test_kinodraw_cloud_does_not_choose_for_a_spanish_script(studio, fake_cloud):
    es = ('# Las fracciones\n\nUna fracción es parte de un todo.\n\n## Sumar\n\n'
          'Para sumar fracciones, busca un denominador común.\n\n## Fin\n\nYa está.\n')
    _, _, cfg, _ = studio(director='cloud', text=es, title='Fracciones', lang='es')
    assert fake_cloud.seen == []                                # nothing sent, nothing metered, as the visuals director
    pick = cfg['style_pick']
    assert pick['by'] == 'rules' and 'English and Chinese videos only' in pick['note'], pick


def test_emoji_text_fits_the_cloud_limits_and_a_split_emoji_in_the_reason_saves():
    long = 'We ship the new app today 🎉 ' * 40                 # KinoDraw Cloud counts an emoji as 2 (JavaScript)
    doc = SimpleNamespace(title=long, preamble=[long], sections=[SimpleNamespace(heading=long, paragraphs=[long])])
    sent = style.request(doc, 'en', '16:9', [])
    units = lambda s: len(s.encode('utf-16-le')) // 2
    assert units(sent['excerpt']) <= style.EXCERPT and units(sent['title']) <= 120 and units(sent['headings'][0]) <= 120
    assert units(sent['excerpt']) >= style.EXCERPT - 1 and sent['excerpt'].startswith('We ship')   # cut, not dropped
    reason = style._clip('A launch party \ud83c')               # a reason the server cut through an emoji
    assert reason == 'A launch party' and reason.encode('utf-8')

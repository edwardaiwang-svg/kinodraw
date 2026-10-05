"""Check the Studio's feedback form in a real (headless) browser, against a fake KinoDraw Cloud on 127.0.0.1.

  KINODRAW_PYTHON=.venv/bin/python python scripts/check_feedback_ui.py --shot form.png [--make]

The Python running this needs Playwright (pip install playwright; playwright install chromium); KINODRAW_PYTHON is the
one that runs the Studio (default: this one); CHROMIUM, if set, is the browser to use (a Playwright headless shell from
another version, say). The Studio gets a scratch home folder, no keychain and no cloud token.
It opens the form from the sidebar and from the card a finished video shows, ticks "I am 13 or older" (the email field
appears), half types an email and unticks it, sends once into a cloud failure (Send still goes, with no email; the form
keeps everything and says why), ticks 13+ again, sends again and sees the thank-you.
With --make it first makes a real video from tests/fixtures/tiny.md and checks the card appears after it (needs the
voice and doodle-search models, e.g. KINODRAW_MODELS). Exit 0 when every check holds.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STUDIO = """
import sys, time
from kinodraw.studio.server import serve
server, url = serve(0)
print(url, flush=True)
time.sleep(3600)
"""


def fake_cloud(replies):
    """KinoDraw Cloud on 127.0.0.1: answers each request with the next of ``replies`` (the last one repeats)."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            seen.append((self.path, self.headers.get('Authorization'), json.loads(body)))
            status, data = replies.pop(0) if len(replies) > 1 else replies[0]
            out = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--shot', type=Path, required=True, help='where to save the screenshot of the filled form')
    parser.add_argument('--make', action='store_true', help='make a real video first and check the card after it')
    args = parser.parse_args()
    cloud, seen = fake_cloud([(503, {'error': 'busy'}), (200, {'ok': True})])
    home = Path(tempfile.mkdtemp(prefix='kinodraw-feedback-home-'))
    env = {**os.environ, 'HOME': str(home), 'CI': '1', 'PYTHON_KEYRING_BACKEND': 'keyring.backends.fail.Keyring',
           'KINODRAW_CLOUD_URL': f'http://127.0.0.1:{cloud.server_address[1]}', 'XDG_CONFIG_HOME': str(home / '.config'),
           'XDG_DATA_HOME': str(home / '.local/share'), 'APPDATA': str(home), 'LOCALAPPDATA': str(home)}
    for var in ('KINODRAW_CLOUD_TOKEN', 'DOODLE_CLOUD_TOKEN', 'NO_PROXY', 'no_proxy'):
        env.pop(var, None)
    env['NO_PROXY'] = '127.0.0.1,localhost'
    studio = subprocess.Popen([os.environ.get('KINODRAW_PYTHON', sys.executable), '-c', STUDIO], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, text=True, encoding='utf-8')
    try:
        url = studio.stdout.readline().strip()
        assert url.startswith('http://127.0.0.1:'), url
        print(f'studio {url}  cloud {env["KINODRAW_CLOUD_URL"]}  home {home}')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM') or None)
            page = browser.new_page(viewport={'width': 1320, 'height': 880})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.locator('#feedback')).to_have_text('Feedback or a problem? Tell us')
            if args.make:
                page.click('#btn-new')
                page.fill('#script', (ROOT / 'tests/fixtures/tiny.md').read_text(encoding='utf-8'))
                page.click('#create')
                expect(page.locator('#p-make')).to_be_visible(timeout=300_000)
                page.click('#p-make')
                card = page.locator('#tab-video .feedback-card')
                expect(card).to_be_visible(timeout=900_000)
                assert page.locator('#tab-video video').count() == 1             # the video is there, card or not
                print('after a made video: the card appears')
            else:                                    # the card as makeVideo() adds it, on an empty Video tab
                page.evaluate("""() => { const box = document.createElement('div'); box.id = 'tab-video';
                  document.querySelector('#main').prepend(box); feedbackCard(box); }""")
                card = page.locator('#tab-video .feedback-card')
            expect(card).to_contain_text('How did this video go? Tell us in 30 seconds')
            args.shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.shot.with_name('card.png')))
            card.locator('a').click()                                           # the card opens the same form
            expect(page.locator('#f-form')).to_be_visible()
            page.click('#modal .close')
            card.locator('button.x').click()                                    # and the X dismisses it
            expect(card).to_have_count(0)

            page.click('#feedback')                                            # the sidebar button
            form = page.locator('#f-form')
            expect(form).to_be_visible()
            expect(page.locator('#f-email-wrap')).to_be_hidden()               # no email field before 13+
            expect(page.locator('.feedback .github a')).to_have_attribute(
                'href', 'https://github.com/edwardaiwang-svg/kinodraw/issues/new/choose')
            page.fill('#f-text', 'The doodles were lovely. The voice read a bit fast for my class.')
            page.select_option('#f-rating', '4')
            page.select_option('#f-use', 'school')
            page.fill('#f-url', 'https://example.com/my-video')
            page.check('#f-quote')
            page.check('#f-age')
            expect(page.locator('#f-email-wrap')).to_be_visible()              # appears once 13+ is ticked
            expect(page.locator('#f-email-wrap')).to_contain_text("Email, if you'd like a reply (optional)")
            page.fill('#f-email', 'teacher@example.com')
            args.shot.parent.mkdir(parents=True, exist_ok=True)
            page.locator('#modal .modal-box').screenshot(path=str(args.shot))
            print(f'screenshot {args.shot}')

            page.fill('#f-email', 'me@')                                       # half typed, then 13+ unticked:
            page.uncheck('#f-age')
            expect(page.locator('#f-email-wrap')).to_be_hidden()
            page.click('#f-send')                                              # Send still goes (the cloud is busy)
            expect(page.locator('#f-result')).to_contain_text('Your feedback wasn’t sent. KinoDraw Cloud had a problem.')
            assert len(seen) == 1 and 'email' not in seen[0][2] and seen[0][2]['age_13_plus'] is False, seen
            assert page.input_value('#f-text').startswith('The doodles were lovely.')   # nothing typed is lost
            page.screenshot(path=str(args.shot.with_name('retry.png')))
            page.check('#f-age')
            assert page.input_value('#f-email') == 'me@'                       # kept for when 13+ is ticked again
            page.fill('#f-email', 'teacher@example.com')
            page.click('#f-send')
            expect(page.locator('#modal-body h2')).to_have_text('Thank you!')
            page.screenshot(path=str(args.shot.with_name('thanks.png')))
            assert len(seen) == 2 and all(path == '/v1/feedback' and auth is None for path, auth, _ in seen), seen
            sent = seen[-1][2]
            assert sent['email'] == 'teacher@example.com' and sent['rating'] == 4 and sent['use'] == 'school', sent
            assert sent['quote_ok'] is True and sent['age_13_plus'] is True and len(sent['install_id']) == 32, sent
            print('sent', json.dumps({k: v for k, v in sent.items() if k != 'install_id'}))

            page.click('#f-done')
            page.evaluate("feedbackCard(document.querySelector('#tab-video'))")    # the next finished video
            expect(page.locator('#tab-video .feedback-card')).to_have_count(0)
            expect(page.locator('#tab-video .feedback-more')).to_have_text('Send more feedback')
            assert page.evaluate("fetch('/api/state', { headers: { 'X-Studio-Token': T } }).then((r) => r.json())"
                                 )['feedback_sent'] is True                          # kept in studio.json
            page.reload()                                                           # and after the app reopens
            assert page.evaluate("fetch('/api/state', { headers: { 'X-Studio-Token': T } }).then((r) => r.json())"
                                 )['feedback_sent'] is True
            assert not errors, errors
            browser.close()
        config = next(home.rglob('studio.json'))
        assert json.loads(config.read_text(encoding='utf-8'))['feedback_sent'] is True, config
        print(f'ok: {config.relative_to(home)} says feedback_sent')
    finally:
        studio.kill()
        cloud.shutdown()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == '__main__':
    main()

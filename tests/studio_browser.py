"""The real Studio page in headless Chromium: tests/studio_browser.mjs run against the real local server, with its
own settings file and projects folder. Skipped where Node or Playwright is not installed (npm install in edu/, or
point KINODRAW_PLAYWRIGHT at a folder whose node_modules has Playwright). KINODRAW_STUDIO_SHOTS=folder keeps
screenshots."""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from kinodraw.studio import server

ROOT = Path(__file__).resolve().parents[1]


def playwright_home() -> Path | None:
    home = Path(os.environ.get('KINODRAW_PLAYWRIGHT') or ROOT / 'edu')
    return home if (home / 'node_modules' / 'playwright').is_dir() else None


def make_project(text: str, lang: str) -> str:
    """A storyboard planned by the offline director, as New video makes it."""
    job = server.create_project({'text': text, 'lang': lang, 'director': 'rules', 'director_v3': False,
                                 'look': 'whiteboard', 'story': 'explain'})
    deadline = time.monotonic() + 120
    while server.JOBS.get(job['job'])['state'] not in ('done', 'failed', 'cancelled'):
        assert time.monotonic() < deadline, 'the storyboard took too long'
        time.sleep(.1)
    assert server.JOBS.get(job['job'])['state'] == 'done', server.JOBS.get(job['job'])
    return job['project']


@pytest.fixture
def studio_page(tmp_path, monkeypatch):
    if not shutil.which('node'):
        pytest.skip('Node is not installed')
    if not playwright_home():
        pytest.skip('Playwright is not installed (npm install in edu/, or set KINODRAW_PLAYWRIGHT)')
    from kinodraw.director.llm import cloud, providers
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    monkeypatch.setattr(cloud, 'INSTALL_ID', tmp_path / 'install-id')      # nobody signed in, nothing of this computer's
    monkeypatch.setattr(providers, 'saved', lambda: set())
    monkeypatch.delenv('KINODRAW_CLOUD_TOKEN', raising=False)
    monkeypatch.delenv('DOODLE_CLOUD_TOKEN', raising=False)
    server._save_config({'projects': str(tmp_path / 'videos')})
    httpd, url = server.serve(0)

    def run(scenario: str):
        result = subprocess.run(['node', str(ROOT / 'tests' / 'studio_browser.mjs'), scenario, url,
                                 os.environ.get('KINODRAW_STUDIO_SHOTS', '')],
                                cwd=ROOT, capture_output=True, text=True, timeout=180,
                                env={**os.environ, 'KINODRAW_PLAYWRIGHT': str(playwright_home())})
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout
    yield run
    httpd.shutdown()
    httpd.server_close()

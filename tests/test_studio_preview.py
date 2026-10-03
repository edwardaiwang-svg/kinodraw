"""The Studio's beat Preview shows the frame in the project's own format: 16:9 or a scaled-down vertical 9:16."""
import io
from pathlib import Path

import pytest
from PIL import Image

from kinodraw import pipeline
from kinodraw.engine import render as renderer, timeline
from kinodraw.studio import server

FIX = Path(__file__).parent / 'fixtures'


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'projects')})
    return tmp_path / 'projects'


def _beat(path):
    return pipeline.storyboard(path)['beats'][1]['id']


def test_a_vertical_project_previews_as_a_vertical_frame(root):
    pipeline.new_project(FIX / 'tiny.md', root / 'tall', direction={'look': 'whiteboard'}, aspect='9:16')
    img = Image.open(io.BytesIO(server.still('tall', _beat(root / 'tall'), 4)))
    assert img.size == (540, 960)


def test_a_landscape_project_previews_exactly_as_before(root):
    pipeline.new_project(FIX / 'tiny.md', root / 'wide', direction={'look': 'whiteboard'})
    beat = _beat(root / 'wide')
    data = server.still('wide', beat, 4)
    assert Image.open(io.BytesIO(data)).size == (960, 540)
    board = pipeline.storyboard(root / 'wide')                     # the same bytes the Preview always sent
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    t = min(tl['beats'][beat]['start'] + 4, tl['beats'][beat]['end'] - .1)
    buf = io.BytesIO()
    renderer.make_production(board, tl, 'en', root / 'wide').frame(min(t, tl['duration'] - .05)).convert('RGB') \
        .resize((960, 540)).save(buf, 'JPEG', quality=85)
    assert data == buf.getvalue()

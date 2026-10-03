"""The stick preview finds the narration next to the timeline it came with, wherever it is run from."""
import json

import numpy as np

from kinodraw.audio import mix as audio
from kinodraw.engine.stick import preview


def test_keep_pacing_resolves_the_narration_next_to_the_whiteboard_timeline(tmp_path):
    (tmp_path / 'build').mkdir()
    (tmp_path / 'project.json').write_text(json.dumps({'lang': 'en'}))
    (tmp_path / 'storyboard.json').write_text(json.dumps({'chapters': []}))
    (tmp_path / 'build' / 'timeline.json').write_text(json.dumps({'audio': 'narration.wav', 'duration': 1.}))
    audio.write_wav(tmp_path / 'build' / 'narration.wav', np.zeros((audio.SR, 2), np.float32))
    _, tl, _, out = preview.prepare(tmp_path, keep_pacing=True)
    assert audio.narration(tl, out) == (tmp_path / 'build' / 'narration.wav').resolve()

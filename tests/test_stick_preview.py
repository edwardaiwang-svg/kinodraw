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


def test_the_talking_mouth_reads_the_narration_in_the_build_folder(tmp_path, monkeypatch):
    out = tmp_path / 'build' / 'stick'
    out.mkdir(parents=True)
    audio.write_wav(out / 'narration.wav', np.full((audio.SR, 2), .3, np.float32))
    monkeypatch.setattr(preview, 'prepare', lambda *a, **k: ({}, {'audio': 'narration.wav', 'duration': 1.}, 'en', out))
    seen = {}

    class Prod:
        shots, warnings = [], []

        def __init__(self, *a, envelope=None, **k):
            seen['envelope'] = envelope

        def frame(self, t):
            from PIL import Image
            return Image.new('RGB', (4, 4))
    monkeypatch.setattr(preview, 'StickProduction', Prod)
    monkeypatch.chdir(tmp_path)
    preview.main([str(tmp_path), '--stills', '0'])
    assert seen['envelope'] is not None and seen['envelope'].max() == 1


def test_a_spanish_project_is_told_to_use_a_whiteboard_look(tmp_path, monkeypatch):
    import pytest
    from kinodraw import pipeline
    monkeypatch.setattr(pipeline, 'settings', lambda project: {'lang': 'es'})
    with pytest.raises(SystemExit, match='English and Chinese'):
        preview.main([str(tmp_path), '--stills', '1'])


def test_stick_text_keeps_spanish_words_whole():
    from kinodraw.engine.stick import text
    lines = text.wrap('Los pingüinos emperador caminan juntos por el hielo', 40, 'es', 300)
    assert all(w in 'Los pingüinos emperador caminan juntos por el hielo'.split() for l in lines for w in l.split())

"""A saved whiteboard span must not silently become an empty caption-only board."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from kinodraw.engine import render


@pytest.mark.parametrize('aspect,size,source_text', [
    ('16:9', None, True), ('1:1', (1080, 1080), False), ('1:1', (1080, 1080), True)])
def test_empty_saved_whiteboard_span_writes_its_source(tmp_path, aspect, size, source_text):
    fixture = Path(__file__).parent / 'fixtures/native_saved_project'
    board = json.loads((fixture / 'storyboard.json').read_text())
    timing = json.loads((fixture / 'timeline.json').read_text())
    config = json.loads((fixture / 'project.json').read_text())
    if source_text:
        config['plan_v3']['scenes'][0]['elements'].append({'kind': 'text', 'ref': 'b001'})
    settings = json.dumps(config).encode()
    (tmp_path / 'project.json').write_bytes(settings)
    original = copy.deepcopy((board, timing))
    prod = render.make_production(board, timing, 'en', tmp_path, aspect=aspect, size=size)
    whiteboard = prod.whiteboard
    source = [e for e in whiteboard.els if e.group == 'source:b001:0']
    assert len(source) == 1, 'saved whiteboard beat without art lost its source drawing'
    text = source[0]
    assert ' '.join(text.drawing.lines) == board['beats'][0]['spoken']['en']
    assert text.start >= timing['beats']['b001']['start']
    assert text.end <= timing['beats']['b001']['speech_end']
    assert text.essential and text.hand and not text.skipped
    assert whiteboard.text_visible(text, 1., whiteboard.camera.at(1.))
    times = (.8, 1.2, 1.8, 2.4)
    forward = [hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in times]
    assert len(set(forward)) == len(times), 'source handwriting must advance during narration'
    assert forward == list(reversed([
        hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in reversed(times)]))
    assert (board, timing) == original
    assert (tmp_path / 'project.json').read_bytes() == settings

"""Supplementary source writing must leave the scheduled artwork intact."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from kinodraw.engine import render


def test_cached_source_sentences_preserve_existing_artwork():
    project = Path(__file__).parent / 'fixtures/idle_sources/fraction-en'
    board = json.loads((project / 'storyboard.json').read_text())
    timing = json.loads((project / 'build/timeline.json').read_text())
    original = deepcopy(board)
    for beat in original['beats']:
        beat.pop('direction', None)
    baseline = render.Production(original, timing, timing['language'], project)
    actual = render.Production(board, timing, timing['language'], project)
    expected = Counter(e.group for e in baseline.els)
    retained = Counter(e.group for e in actual.els if not e.group.startswith('source:'))
    assert retained == expected
    assert actual.tl == timing
    for tr in timing['transitions']:
        face = actual.notes[tr['section']]['els'][3]
        previous = baseline.notes[tr['section']]['els'][3]
        if previous.skipped:
            continue
        assert not face.skipped and face.end <= tr['hold_end'] - render.NOTE_READ + 1e-8
        at = tr['hold_end'] - .01
        visible = np.asarray(actual.frame(at))
        hidden_after = face.hidden_after
        face.hidden_after = 0.
        hidden = np.asarray(actual.frame(at))
        face.hidden_after = hidden_after
        assert np.any(visible != hidden)

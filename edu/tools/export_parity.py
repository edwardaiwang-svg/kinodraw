#!/usr/bin/env python3
"""Parity fixtures for the JavaScript port: what the Python app makes from each test script.

For every script: the storyboard skeleton, the rules-directed storyboard, every text the director
embedded (so the JS director can run on the same vectors), and the timeline from synthetic clips.

    ../.venv/bin/python tools/export_parity.py        (from edu/)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent))
from kinodraw import ingest, script                        # noqa: E402
from kinodraw.director import match, rules                  # noqa: E402
from kinodraw.engine import timeline as tl                  # noqa: E402

FIXTURES = HERE.parent / 'tests' / 'fixtures'
OUT = HERE / 'tests' / 'parity'
NAMES = ['printing_press.md', 'bicycle.md', 'sky_blue.md', 'photosynthesis.txt', 'tiny.md', 'water_cycle.md']


class Recorder:
    """Wraps the embedding model and keeps every text it embeds (raw model output, as fastembed returns it)."""

    def __init__(self, model):
        self.model, self.seen = model, {}

    def embed(self, texts):
        texts = list(texts)
        out = list(self.model.embed(texts))
        for t, v in zip(texts, out):
            self.seen[t] = np.asarray(v, np.float32)
        return iter(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    real = match._model('en')
    for name in NAMES:
        rec = Recorder(real)
        rules._model = match._model = lambda lang, rec=rec: rec           # the director calls _model(lang).embed(...)
        text = (FIXTURES / name).read_text(encoding='utf-8')
        doc = ingest.read(FIXTURES / name)
        skeleton = script.build(doc)
        directed = rules.RulesDirector('en').direct(json.loads(json.dumps(skeleton)))
        timing = tl.layout(directed, 'en', tl.synthetic_clips(directed, 'en'))
        data = {'name': name, 'text': text, 'title_fallback': Path(name).stem.replace('_', ' ').capitalize(),
                'document': {'title': doc.title, 'lang': doc.lang, 'preamble': doc.preamble,
                             'sections': [{'heading': s.heading, 'paragraphs': s.paragraphs} for s in doc.sections]},
                'skeleton': skeleton, 'directed': directed, 'timeline': timing,
                'embeddings': {t: [round(float(x), 7) for x in v] for t, v in rec.seen.items()}}
        (OUT / f'{Path(name).stem}.json').write_text(json.dumps(data, ensure_ascii=False))
        print(f'{name}: {len(directed["beats"])} beats, {len(rec.seen)} embedded texts')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Copy what the extension needs from the Python app into edu/extension/assets (English only).

The Python package stays the single source of truth for the doodle library, its tags, the
banned list, the search vectors, fonts, the drawing hand, the paper and the music.

    ../.venv/bin/python tools/export_assets.py        (from edu/)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]                    # edu/
sys.path.insert(0, str(HERE.parent))
from kinodraw.director.match import catalog_vectors       # noqa: E402
from kinodraw.engine import ink                            # noqa: E402
from kinodraw.library import ASSETS as DOODLES, banned, catalog, resolve   # noqa: E402

OUT = HERE / 'extension' / 'assets'
APP = DOODLES.parent                                           # kinodraw/assets
MUSIC = ('fresh_focus', 'natural_vibes')                       # the two tracks the default mix uses


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / 'doodles').mkdir(parents=True)
    entries = catalog()
    ids = sorted(entries)
    lean = {i: {'desc': e.get('desc', ''), 'category': e.get('category', ''), 'en': e.get('en') or [],
                'set': e['set']} for i, e in entries.items()}
    (OUT / 'catalog.json').write_text(json.dumps({'ids': ids, 'entries': lean}, ensure_ascii=False))
    for kind in ('embed', 'picture'):                          # same table order as match._table: sorted ids
        vec_ids, vecs = catalog_vectors('en', kind)
        assert list(vec_ids) == ids, kind
        (OUT / f'{kind}-en.f32').write_bytes(vecs.astype('<f4').tobytes())
    data = banned()
    (OUT / 'banned.json').write_text(json.dumps({'doodles': sorted(data['doodles']),
                                                 'words': {'en': sorted(data['words']['en'])}}, ensure_ascii=False))
    for did in ids:
        shutil.copyfile(resolve(did), OUT / 'doodles' / f'{did}.svg')
    shutil.copyfile(DOODLES / 'missing.svg', OUT / 'doodles' / 'missing.svg')
    for name, to in (('LICENSE', 'LICENSE-fluent-emoji.txt'), ('NOTICE.md', 'NOTICE-fluent-emoji.md')):
        shutil.copyfile(DOODLES / 'fluent' / name, OUT / 'doodles' / to)     # the fl_* doodles: Microsoft, MIT
    (OUT / 'fonts').mkdir()
    for name in ('PlaypenSans-Bold.ttf', 'Arimo-Bold.ttf', 'OFL-PlaypenSans.txt', 'OFL-Arimo.txt'):
        shutil.copyfile(APP / 'fonts' / name, OUT / 'fonts' / name)
    (OUT / 'hand').mkdir()
    for name in ('hand.png', 'hand.json'):
        shutil.copyfile(APP / 'hand' / name, OUT / 'hand' / name)
    (OUT / 'music').mkdir()
    for slug in MUSIC:
        shutil.copyfile(APP / 'music' / f'{slug}.mp3', OUT / 'music' / f'{slug}.mp3')
    shutil.copyfile(APP / 'music' / 'NOTICE.md', OUT / 'music' / 'NOTICE.md')
    ink.paper().convert('RGB').save(OUT / 'paper.png', optimize=True)
    size = sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())
    print(f'{len(ids)} doodles, {size / 1e6:.1f} MB -> {OUT}')


if __name__ == '__main__':
    main()

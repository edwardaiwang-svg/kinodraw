"""Doodle library: resolve a doodle id to its SVG file, and the tagged catalog.

Search order: the project's own ``doodles/`` folder (user or private presets),
then the bundled bespoke set, then the converted Fluent Emoji set.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'doodles'
SETS = ('bespoke', 'fluent')
MISSING = ASSETS / 'missing.svg'


@lru_cache(maxsize=1)
def banned() -> dict:
    """{'doodles': set of ids no director may pick, 'words': {lang: set of words never drawn}} (banned.json)."""
    data = json.loads((ASSETS / 'banned.json').read_text(encoding='utf-8'))
    return {'doodles': set(data['doodles']), 'words': {lang: set(ws) for lang, ws in data['words'].items()}}


def resolve(doodle_id: str, project_dir: Path | None = None) -> Path | None:
    dirs = ([Path(project_dir) / 'doodles'] if project_dir else []) + [ASSETS / s for s in SETS]
    for d in dirs:
        path = d / f'{doodle_id}.svg'
        if path.exists():
            return path
    return None


@lru_cache(maxsize=1)
def catalog() -> dict:
    """id -> {desc, category, en: [...], zh: [...], set} for every shipped doodle that has an SVG and is not banned."""
    out, skip = {}, banned()['doodles']
    for path in sorted((ASSETS / 'tags').glob('*.json')):
        doodle_set = 'fluent' if path.stem == 'fluent' else 'bespoke'
        for did, entry in json.loads(path.read_text(encoding='utf-8')).items():
            if did not in skip and (ASSETS / doodle_set / f'{did}.svg').exists():
                out[did] = {**entry, 'set': doodle_set}
    return out

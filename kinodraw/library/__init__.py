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
OWN = 'own:'
PICTURE_TYPES = ('.png', '.jpg', '.jpeg', '.svg')
PICTURE_MAX = 10 * 1024 * 1024
PICTURES = 'pictures'


def own_path(doodle_id: str, project_dir: Path | None) -> Path:
    """Resolve a manually chosen picture, keeping names and symlinks inside its folder."""
    if project_dir is None:
        raise ValueError('Your own pictures need a project folder. Upload a picture in the Studio '
                         '(Choose a doodle → Upload a picture).')
    name = doodle_id.removeprefix(OWN)
    folder = (Path(project_dir) / PICTURES).resolve()
    message = (f'“{name}” isn’t a picture in this project’s pictures folder. '
               'Upload it in the Studio (Choose a doodle → Upload a picture).')
    if (not doodle_id.startswith(OWN) or not name or '/' in name or '\\' in name
            or name.startswith('.') or '\x00' in name or Path(name).suffix.lower() not in PICTURE_TYPES):
        raise ValueError(message)
    try:
        path = folder / name
        if not path.resolve().is_relative_to(folder):
            raise ValueError(message)
    except (OSError, RuntimeError):
        raise ValueError(message) from None
    return path


def _missing_picture(path: Path) -> str:
    return (f'The picture “{path.name}” is missing from the project’s pictures folder ({path.parent}). '
            'Put it back or upload it again in the Studio.')


def missing_pictures(board: dict, project_dir: Path | None) -> list[str]:
    """Plain errors for invalid or missing own pictures in visual order, once per id."""
    from ..director.validate import _doodles
    seen, messages = set(), []
    for beat in board.get('beats') or []:
        for visual in beat.get('visuals') or []:
            for did in _doodles(visual):
                if not did.startswith(OWN) or did in seen:
                    continue
                seen.add(did)
                try:
                    path = own_path(did, project_dir)
                    if not path.is_file():
                        messages.append(_missing_picture(path))
                except ValueError as error:
                    messages.append(str(error))
    return messages


@lru_cache(maxsize=1)
def banned() -> dict:
    """{'doodles': set of ids no director may pick, 'words': {lang: set of words never drawn}} (banned.json)."""
    data = json.loads((ASSETS / 'banned.json').read_text(encoding='utf-8'))
    return {'doodles': set(data['doodles']), 'words': {lang: set(ws) for lang, ws in data['words'].items()}}


def resolve(doodle_id: str, project_dir: Path | None = None) -> Path | None:
    if doodle_id.startswith(OWN):
        try:
            path = own_path(doodle_id, project_dir)
            return path if path.is_file() else None
        except ValueError:
            return None
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

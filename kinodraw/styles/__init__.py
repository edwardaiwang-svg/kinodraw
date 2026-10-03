"""The style registry (registry.json): every look a video can have, what it is called in each language, whether it
renders yet, what it fits, and which renderer draws it (and with which skin, for looks over the whiteboard)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REGISTRY = Path(__file__).with_name('registry.json')
STATUSES = ('built', 'skin', 'planned')


@lru_cache(maxsize=1)
def _looks() -> tuple:
    return tuple(json.loads(REGISTRY.read_text(encoding='utf-8'))['looks'])


def looks(ready: bool = False) -> list[dict]:
    """Every registered look in registry order (``ready``: only those the app can render now)."""
    return [entry for entry in _looks() if entry['render_ready'] or not ready]


def ids(ready: bool = False) -> list[str]:
    return [entry['id'] for entry in looks(ready)]


def get(look: str) -> dict | None:
    return next((entry for entry in _looks() if entry['id'] == look), None)


def renderer(look: str | None) -> str:
    """Which renderer draws ``look``: 'whiteboard' (the default, and every skin), 'collage', 'bold' ..."""
    entry = get(look or 'whiteboard')
    return entry['renderer'] if entry else 'whiteboard'

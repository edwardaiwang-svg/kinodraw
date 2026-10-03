"""Storyboard defaults: fill in what the renderer derives (numbers, colours, narrator, direction dials).

Chapter kinds: intro · agenda · section (numbered, has an agenda card) · board · outro.
Direction dials (director/annotate.py): look · story · motion; the whiteboard renderer ignores them.
"""
from __future__ import annotations

import copy

from . import ink
from .. import styles

KINDS = {'intro', 'agenda', 'section', 'board', 'outro'}
DIALS = {'look': tuple(styles.ids()),                            # the first value is the default (the registry's order)
         'story': ('explain', 'promo', 'story', 'showcase'),
         'motion': ('lively', 'calm', 'showreel')}
LOOKS = tuple(styles.ids(ready=True))   # the looks KinoDraw can draw (render_ready in styles/registry.json)


def drawable(look: str) -> str:
    """``look`` if KinoDraw can draw it, else a ValueError that says what to choose."""
    if look not in LOOKS:
        raise ValueError(f'The "{look}" look is not available yet. Choose {", ".join(LOOKS[:-1])} or {LOOKS[-1]}.')
    return look


def normalize(episode: dict) -> dict:
    ep = copy.deepcopy(episode)
    ep.setdefault('narrator', 'narrator')
    for dial, values in DIALS.items():
        ep.setdefault(dial, values[0])
    number = 0
    for ch in ep['chapters']:
        if ch['kind'] not in KINDS:
            raise ValueError(f"chapter {ch['id']}: kind {ch['kind']!r} not in {sorted(KINDS)}")
        if ch['kind'] == 'section':
            number += 1
            ch.setdefault('number', number)
            ch.setdefault('color', ink.COLOR_CYCLE[(number - 1) % len(ink.COLOR_CYCLE)])
    return ep

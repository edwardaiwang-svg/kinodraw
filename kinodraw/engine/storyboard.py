"""Storyboard defaults: fill in what the renderer derives (numbers, colours, narrator, direction dials).

Chapter kinds: intro · agenda · section (numbered, has an agenda card) · board · outro.
Direction dials (director/annotate.py): look · story · motion; the whiteboard renderer ignores them.
"""
from __future__ import annotations

import copy

from . import ink

KINDS = {'intro', 'agenda', 'section', 'board', 'outro'}
DIALS = {'look': ('whiteboard', 'collage', 'bold'),              # the first value is the default
         'story': ('explain', 'promo', 'story', 'showcase'),
         'motion': ('lively', 'calm', 'showreel')}
LOOKS = ('whiteboard', 'collage')   # the looks KinoDraw can draw; bold is only planned (director/annotate.py)


def drawable(look: str) -> str:
    """``look`` if KinoDraw can draw it, else a ValueError that says what to choose."""
    if look not in LOOKS:
        raise ValueError(f'The "{look}" look is not available yet. Choose {" or ".join(LOOKS)}.')
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

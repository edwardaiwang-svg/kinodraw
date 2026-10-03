"""Storyboard defaults: fill in what the renderer derives (numbers, colours, narrator).

Chapter kinds: intro · agenda · section (numbered, has an agenda card) · board · outro.
"""
from __future__ import annotations

import copy

from . import ink

KINDS = {'intro', 'agenda', 'section', 'board', 'outro'}


def normalize(episode: dict) -> dict:
    ep = copy.deepcopy(episode)
    ep.setdefault('narrator', 'narrator')
    number = 0
    for ch in ep['chapters']:
        if ch['kind'] not in KINDS:
            raise ValueError(f"chapter {ch['id']}: kind {ch['kind']!r} not in {sorted(KINDS)}")
        if ch['kind'] == 'section':
            number += 1
            ch.setdefault('number', number)
            ch.setdefault('color', ink.COLOR_CYCLE[(number - 1) % len(ink.COLOR_CYCLE)])
    return ep

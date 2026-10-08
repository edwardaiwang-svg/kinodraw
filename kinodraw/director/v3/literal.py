"""Client repairs that keep a validated plan literal to its text, whatever the planner answered.

- One time of day: a shot the planner left at "unknown" takes the time of the shot before it (the first shots take
  the first stated time), so a night drive is night from its first frame.
- Stated ages: someone the text gives an adult age ("Dev turns 50", "a 40-year-old") is never drawn old, unless the
  text also calls them old (grandma, elderly).
- Named focus: a shot's focus_ref is drawn. Outside an insert or first_person shot the camera does not look at it,
  so a focus that is a thing (not a person, face, symbol or place) becomes a prop of the shot.
- Named people: in a story, a cast member the beat names is on screen in that beat's scene.
"""
from __future__ import annotations

import re

from ...library import catalog
from .offer import FACES, UI_CATEGORIES
from .semantics import beats, mentions

STATED_AGE = re.compile(r'\bturn(?:s|ed|ing)?\s+(\d{1,3})\b|\b(\d{1,3})(?:\s+|-)years?(?:\s+|-)old\b|'
                        r'\b(\d{1,3})(?:st|nd|rd|th)\s+birthday\b|\bin\s+(?:his|her|their)\s+(\d)0s\b', re.I)
ELDERLY = re.compile(r'\b(?:grand(?:ma|pa|mother|father|mum|dad)|granny|nana|elderly|old\s+(?:man|woman|lady)|'
                     r'very\s+old|aged)\b', re.I)
LOOKING = ('insert', 'first_person')
# Pictures that are not a thing to put in a scene: people, body parts, faces, symbols and places.
NOT_PROPS = UI_CATEGORIES | FACES | {'People & Body', 'people', 'Health', 'Travel & Places', 'places'}


def repair(plan: dict, script_beats) -> list[str]:
    """Repair ``plan`` in place; return the notes."""
    script = beats(script_beats)
    repairs: list[str] = []
    _carry_time(plan, repairs)
    _stated_ages(plan, script, repairs)
    _focus_drawn(plan, repairs)
    _named_on_screen(plan, script, repairs)
    return repairs


def _shots(plan):
    return [shot for scene in plan['scenes'] for shot in scene.get('shots') or []]


def _carry_time(plan, repairs):
    shots = _shots(plan)
    known = [shot['setting']['time'] for shot in shots if shot['setting']['time'] != 'unknown']
    if not known:
        return
    last, filled = known[0], 0
    for shot in shots:
        if shot['setting']['time'] == 'unknown':
            shot['setting']['time'] = last
            filled += 1
        else:
            last = shot['setting']['time']
    if filled:
        repairs.append(f'shots: {filled} shot(s) without a time of day carry the story\'s time')


def _stated_ages(plan, script, repairs):
    text = '\n'.join(b['text'] for b in script)
    sentences = re.split(r'(?<=[.!?\n])\s+', text)
    for c in plan['cast']:
        if c.get('kind') != 'human':
            continue
        ages, elderly = [], False
        for sentence in sentences:
            if not mentions(c['name'], sentence):
                continue
            elderly |= bool(ELDERLY.search(sentence))
            for m in STATED_AGE.finditer(sentence):
                n = next(int(g) for g in m.groups() if g)
                ages.append(n * 10 if m.group(4) else n)
        if elderly or not ages or not all(20 <= n < 65 for n in ages):
            continue
        changed = c['age'] == 'old'
        if changed:
            c['age'] = 'adult'
        for shot in _shots(plan):
            for member in shot['cast']:
                if member['id'] == c['id'] and member['age'] == 'old':
                    member['age'] = 'adult'
                    changed = True
        if changed:
            repairs.append(f'cast.{c["id"]}: the text gives age {ages[0]}; drawn as an adult, not old')


def _focus_drawn(plan, repairs):
    for i, scene in enumerate(plan['scenes']):
        pictures = {e['ref'] for e in scene['elements'] if e['kind'] == 'picture'}
        for shot in scene.get('shots') or []:
            focus = shot['focus_ref']
            if not focus or shot['shot'] in LOOKING:
                continue
            if focus in shot['setting']['set_refs'] or any(p['ref'] == focus for p in shot['props']):
                continue
            if (catalog().get(focus) or {}).get('category') in NOT_PROPS:
                continue                               # a person or symbol picked as a focus is no prop
            shot['props'].append({'ref': focus, 'relation': 'none', 'to': '', 'motion': 'none'})
            if focus not in pictures:
                scene['elements'].append({'kind': 'picture', 'ref': focus})
                pictures.add(focus)
            repairs.append(f'scenes[{i}]: {shot["beat_id"]} {shot["shot"]} shot draws its focus {focus} as a prop')


def _named_on_screen(plan, script, repairs):
    if plan['storyboard']['genre'] != 'story':
        return
    humans = [c for c in plan['cast'] if c.get('kind') == 'human']
    by_id = {b['id']: b for b in script}
    for i, scene in enumerate(plan['scenes']):
        if scene.get('boards') or scene['treatment'] in ('chart', 'whiteboard'):
            continue
        staged = {e['ref'] for e in scene['elements'] if e['kind'] == 'cast'}
        if staged or any(shot['cast'] for shot in scene.get('shots') or []):
            continue                                   # the planner chose who is on screen here
        named = [c['id'] for c in humans
                 if any(mentions(c['name'], by_id[bid]['spoken']) for bid in scene['beat_ids'] if bid in by_id)]
        for cid in named:
            scene['elements'].append({'kind': 'cast', 'ref': cid})
        if named:
            if scene['treatment'] in ('motion', 'atmosphere'):
                scene['treatment'], scene['composition'] = 'character', 'stage'
            repairs.append(f'scenes[{i}]: {", ".join(named)} named in the scene and now on screen')

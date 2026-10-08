"""Client repairs that keep a validated plan literal to its text, whatever the planner answered.

- One time of day: a shot the planner left at "unknown" takes the time of the shot before it (the first shots take
  the first stated time), so a night drive is night from its first frame.
- Stated ages: someone the text gives an adult age ("Dev turns 50", "a 40-year-old") is never drawn old, unless the
  text also calls them old (grandma, elderly).
- Named focus: a shot's focus_ref is drawn. Outside an insert or first_person shot the camera does not look at it,
  so a focus that is a thing (not a person, face, symbol or place) becomes a prop of the shot; a thing the beat
  names only inside its quotes is not in the room, so the camera cuts to an insert of it at a later sentence.
- Named people: in a story, a cast member the beat names is on screen in that beat's scene.
"""
from __future__ import annotations

import re

from ...library import catalog
from ..match import singular
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
    _focus_drawn(plan, script, repairs)
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


def _focus_drawn(plan, script, repairs):
    by_id = {b['id']: b for b in script}
    for i, scene in enumerate(plan['scenes']):
        pictures = {e['ref'] for e in scene['elements'] if e['kind'] == 'picture'}
        shots = scene.get('shots') or []
        for shot in list(shots):
            focus = shot['focus_ref']
            if not focus or shot['shot'] in LOOKING:
                continue
            if focus in shot['setting']['set_refs'] or any(p['ref'] == focus for p in shot['props']):
                continue
            if (catalog().get(focus) or {}).get('category') in NOT_PROPS:
                continue                               # a person or symbol picked as a focus is no prop
            if _talked_about(by_id.get(shot['beat_id']), focus) and any(
                    o['beat_id'] == shot['beat_id'] and o['shot'] in LOOKING and o['focus_ref'] == focus for o in shots):
                continue                               # not in the room, and the beat already cuts to it
            if focus not in pictures:
                scene['elements'].append({'kind': 'picture', 'ref': focus})
                pictures.add(focus)
            cut = _insert_at(shot, shots, by_id.get(shot['beat_id']), focus)
            if cut:
                # a thing only talked about is not in the room: the camera cuts to it while the line goes on
                insert = {'beat_id': shot['beat_id'], 'starts_at': cut, 'shot': 'insert',
                          'setting': dict(shot['setting'], set_refs=[]), 'cast': [], 'lines': [], 'props': [],
                          'focus_ref': focus, 'writing': ''}
                shots.insert(shots.index(shot) + 1, insert)
                repairs.append(f'scenes[{i}]: {shot["beat_id"]} cuts to an insert of {focus} at {cut!r}')
                continue
            shot['props'].append({'ref': focus, 'relation': 'none', 'to': '', 'motion': 'none'})
            repairs.append(f'scenes[{i}]: {shot["beat_id"]} {shot["shot"]} shot draws its focus {focus} as a prop')


QUOTED = re.compile(r'["\u201c]([^"\u201d]*)["\u201d]')


def _names(ref):
    """The words that name a picture: its first keywords and the last word of its description."""
    entry = catalog().get(ref) or {}
    words = list(entry.get('en') or [])[:3] + (entry.get('desc') or '').split()[-1:]
    return {singular(w) for word in words for w in re.findall(r'[a-z]+', word.lower()) if len(w) > 2}


def _talked_about(beat, focus):
    """Does the beat name this picture inside its quotes and nowhere in its narration?"""
    if beat is None:
        return False
    names = _names(focus)
    said = lambda part: bool(names & {singular(w) for w in re.findall(r'[a-z]+', part.lower())})
    return said(' '.join(QUOTED.findall(beat['text']))) and not said(QUOTED.sub(' ', beat['text']))


def _insert_at(shot, shots, beat, focus):
    """Where an insert of ``focus`` starts, when the beat names it only inside its quotes: the first sentence after
    the shot's own first sentence that names it, else the shot's second sentence; '' when there is none (one
    short line) or the planner already cuts there."""
    if not _talked_about(beat, focus):
        return ''
    text, names = beat['text'], _names(focus)
    said = lambda part: bool(names & {singular(w) for w in re.findall(r'[a-z]+', part.lower())})
    start = _find(text, shot['starts_at'])
    sentences = [(q.start(1) + m.start(), m.group()) for q in QUOTED.finditer(text) if q.end(1) > start
                 for m in re.finditer(r'[^.!?]+[.!?]*', q.group(1)) if re.search(r'\w', m.group())]
    sentences = [(at, part) for at, part in sentences if at + len(part) > start]       # the quoted sentences spoken
    if len(sentences) < 2:
        return ''
    later = next((at for at, part in sentences[1:] if said(part)), None)
    if later is None and said(sentences[0][1]):
        later = sentences[1][0]
    if later is None:
        return ''
    at = later + len(text[later:]) - len(text[later:].lstrip())
    if any(other is not shot and other['beat_id'] == shot['beat_id'] and _find(text, other['starts_at']) >= at
           for other in shots):
        return ''
    return ' '.join(re.findall(r"\S+", text[at:])[:4]).strip(' "\u201c\u201d')


def _find(text, words):
    if not words:
        return 0
    m = re.search(r'\W+'.join(re.escape(w) for w in re.findall(r"\w+(?:['\u2019]\w+)?", words)), text, re.I)
    return m.start() if m else 0


FIRST_PERSON = re.compile(r"\b(?:I|I'm|I've|my|me|mine)\b")
SPEAKER = {'id': 'speaker', 'name': 'Speaker', 'kind': 'human', 'species': 'human', 'family': 'human', 'age': 'adult',
           'sex': 'unknown', 'size': 1, 'palette': {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'},
           'marks': ['none'], 'temperament': 'gentle'}
BIBLE_AGE = {'baby': 'baby', 'young': 'child', 'adult': 'adult', 'old': 'old'}


def _named_on_screen(plan, script, repairs):
    """In a story, a scene the planner left without people shows the people its beats name; a first-person message
    to one person ("Happy 25th Jo, ... my fries") shows its writer beside them."""
    if plan['storyboard']['genre'] != 'story':
        return
    humans = [c for c in plan['cast'] if c.get('kind') == 'human']
    by_id = {b['id']: b for b in script}
    narration = QUOTED.sub(' ', ' '.join(b['text'] for b in script))
    if len(humans) == 1 and FIRST_PERSON.search(narration) and not any(c['id'] == SPEAKER['id'] for c in plan['cast']):
        writer = dict(SPEAKER, palette=dict(SPEAKER['palette']), marks=['none'])
        plan['cast'].append(writer)
        repairs.append('cast: added the first-person speaker of the message')
    else:
        writer = None
    for i, scene in enumerate(plan['scenes']):
        if scene.get('boards') or scene['treatment'] in ('chart', 'whiteboard'):
            continue
        staged = {e['ref'] for e in scene['elements'] if e['kind'] == 'cast'}
        shots = scene.get('shots') or []
        if writer is None and (staged or any(shot['cast'] for shot in shots)):
            continue                                   # the planner chose who is on screen here
        named = [c for c in humans
                 if any(mentions(c['name'], by_id[bid]['spoken']) for bid in scene['beat_ids'] if bid in by_id)]
        if writer is not None and named:
            named.append(writer)
        added = [c for c in named if c['id'] not in staged]
        for c in added:
            scene['elements'].append({'kind': 'cast', 'ref': c['id']})
        for shot in shots:
            if shot['shot'] in LOOKING or shot['cast'] and writer is None:
                continue
            here = {m['id'] for m in shot['cast']}
            shot['cast'] += [{'id': c['id'], 'age': BIBLE_AGE[c['age']], 'pose': 'stand', 'speaking': 'no'}
                             for c in named if c['id'] not in here]
        if added:
            if scene['treatment'] in ('motion', 'atmosphere'):
                scene['treatment'], scene['composition'] = 'character', 'stage'
            repairs.append(f'scenes[{i}]: {", ".join(c["id"] for c in added)} named in the scene and now on screen')

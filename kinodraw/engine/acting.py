"""Story characters act out what the narration says (engine.storybook pages, both the text reading and plan shots).

Each narrated sentence is read for action verbs, each with its actor (the cast reference before it, else the
sentence's subject), a target (the one after it), a direction and its character offset; the act starts when its
word is spoken (the beat's character times). The plan's ``actions`` fill in for an actor the text gives none.

What each act does on the page (frame shares; the camera stays locked, nothing moves while idle):

- locomotion: walk / run / tiptoe in from off the frame, out of it, toward someone or something, past, or a stretch
  across; leap (an arc; "burst through" leaps in), fly up to a speck, fly down, fly past, roll, fall, back away,
  turn around; a target hit by a swipe or "sent flying" is knocked off the frame in a spinning arc.
- gestures: wave, raise a hand, point, cover the face, cross the arms (pose presets, else the nearest one), nod,
  shake the head, lean in, grab or pick up a thing (it goes to the hand and stays there), hand or pass it over.
- contact: hug, curl up next to / sleep against someone (ending touching, lying or asleep), nudge (head lowered
  to them; they rock back).
- animals: swipe a paw (a lunge with motion arcs; the target is knocked back), heavy breathing (the flank heaves,
  breath puffs), lower the head.

An action the page cannot draw falls back to the nearest one it can (``FALLBACK``); every movement verb read is
recorded with whether its actor visibly moved (``Storybook.acted``, the content QA's motion findings).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..director.v3.story import NEGATED, _inside
from .creatures.actions import smooth, strike

# Verbs, most specific first: (kind, cue). A later cue never re-reads words an earlier one took.
VERBS = (
    ('knock', r'sent\s+(?:[\w\'’-]+\s+){1,4}?(?:flying|sprawling|tumbling|spinning)|'
              r'knock(?:ed|s|ing)?\s+(?:[\w\'’-]+\s+){0,3}?(?:over|down|back|away|flying)|flung|hurl(?:ed|s)|'
              r'toss(?:ed|es)\s+(?:the|a|an|him|her|them)|threw\s+(?:the|a|an|him|her|them)'),
    ('curl', r'curl(?:ed|s|ing)?\s+up|snuggl\w*|nestl(?:ed|es|ing)|huddl(?:ed|es|ing)|cuddl(?:ed|es|ing)\s+up'),
    ('sleep', r'(?:fell|falls|falling)\s+asleep|slept\s+(?:against|on|beside|next\s+to)|'
              r'asleep\s+(?:against|on|beside|next\s+to)'),
    ('hug', r'hug(?:s|ged|ging)?|embrac(?:ed|es|ing)|cuddl(?:ed|es|ing)'),
    ('nudge', r'nudg(?:ed|es|ing|e)|nuzzl(?:ed|es|ing|e)'),
    ('lower', r'lower(?:ed|s|ing)?\s+(?:his|her|its|their)\s+(?:[\w-]+,?\s+){0,2}heads?|'
              r'bow(?:ed|s)?\s+(?:his|her|its|their)\s+heads?|bent\s+down|bends\s+down'),
    ('swipe', r'swip(?:e|es|ed|ing)|swat(?:s|ted|ting)?|claw(?:ed|s)|struck|smack(?:ed|s)|whack(?:ed|s)|'
              r'kick(?:ed|s)|punch(?:ed|es)|shov(?:ed|es)'),
    ('breathe', r'breath(?:ing|ed|es)\s+(?:hard|heavily|deeply|fast)|pant(?:ed|ing|s)|heav(?:ing|ed)\s+'
                r'(?:for\s+breath|with)|gasp(?:ed|ing|s)?\s+for\s+(?:air|breath)|huff(?:ed|ing)\s+and\s+puff\w*'),
    ('grab', r'grab(?:s|bed|bing)?|snatch(?:ed|es|ing)?|pick(?:ed|s)?\s+up|picking\s+up|seiz(?:ed|es)|'
             r'(?:took|takes|taking)\s+(?:the|a|an|it|his|her|back)\b'),
    ('hand', r'hand(?:ed|s|ing)\s+(?:it|them|the|a|an|him|her|over)|pass(?:ed|es|ing)\s+(?:it|them|the|a|an|him|her)|'
             r'gave|gives|giving'),
    ('wave', r'wav(?:ed|es|ing)'),
    ('point', r'point(?:ed|s|ing)'),
    ('cover', r'cover(?:ed|s|ing)?\s+(?:his|her|their|its)\s+(?:face|eyes|mouth)|'
              r'hid(?:es)?\s+(?:his|her|their)\s+face|(?:face|head)\s+in\s+(?:his|her|their)\s+hands'),
    ('cross', r'(?:cross|fold)(?:ed|es|s|ing)?\s+(?:his|her|their)\s+arms'),
    ('raise', r'rais(?:ed|es|ing)\s+(?:his|her|their|a|one)\s+(?:hand|paw|arm)|'
              r'(?:put|puts|shot)\s+(?:his|her|their|a)\s+hand\s+up'),
    ('nod', r'nod(?:s|ded|ding)'),
    ('shake', r'sh(?:ook|akes|ake|aking)\s+(?:his|her|their|its)\s+heads?'),
    ('lean', r'lean(?:s|ed|t|ing)\s+(?:in|forward|over|closer|toward|towards)'),
    ('turn', r'turn(?:ed|s|ing)?\s+(?:a)?round|spun\s+(?:a)?round|wheeled\s+around'),
    ('back', r'shr[au]nk\s+back|shrinks\s+back|back(?:ed|s)?\s+(?:away|off)|stepp?(?:ed|s)\s+back|'
             r'recoil(?:ed|s)?|flinch(?:ed|es)?'),
    ('fly', r'fl(?:ew|ies|ying)|fly|flutter(?:ed|s|ing)|zoom(?:ed|s|ing)?|zipp(?:ed|ing)|zips|soar(?:ed|s|ing)|'
            r'swoop(?:ed|s|ing)|whizz(?:ed|es)'),
    ('leap', r'lea(?:p|ps|ped|pt|ping)|jump(?:ed|s|ing)?|pounc(?:ed|es|ing|e)|sprang|bound(?:ed|s)|'
             r'hopp(?:ed|ing)|hops|burst|lung(?:ed|es)'),
    ('roll', r'roll(?:ed|s|ing)'),
    ('fall', r'fell|fall(?:s|ing)?|tumbl(?:ed|es|ing)|toppl(?:ed|es)|collaps(?:ed|es)|slipp(?:ed)|tripp(?:ed)'),
    ('run', r'ran|runs?|running|rac(?:ed|es|ing)|dash(?:ed|es)|rush(?:ed|es)|bolt(?:ed|s)|sprint(?:ed|s|ing)|'
            r'charg(?:ed|es|ing)|hurri(?:ed|es)|scurri(?:ed|es)|scamper(?:ed|s)|scatter(?:ed|s|ing)|fled|flee(?:s|ing)?|'
            r'chas(?:ed|es|ing)'),
    ('tiptoe', r'tip-?to(?:e|es|ed|eing)|sneak(?:ed|s|ing)?|snuck|crept|creep(?:s|ing)'),
    ('walk', r'walk(?:ed|s|ing)?|stroll(?:ed|s)|wander(?:ed|s)|march(?:ed|es)|trott(?:ed|s)|padd(?:ed|s)\s+'
             r'(?:over|across|in|out|off|away|to|toward)|strode|stepp?(?:ed|s)\s+(?:in|out|into|forward|outside|'
             r'inside|away|toward|towards|up|over)|(?:went|goes|came|comes|headed|heads)\s+(?:back\s+)?(?:up|down|in|'
             r'out|off|away|home|to|toward|towards|into|inside|outside|over|across|upstairs|downstairs|through|closer|'
             r'near|back)|return(?:ed|s)|arriv(?:ed|es)|enter(?:ed|s)|emerg(?:ed|es|ing)|appear(?:ed|s)|'
             r'left\s+(?:the|for|home|without)|approach(?:ed|es)|drew\s+(?:closer|near)|clos(?:ed|ing)\s+in|'
             r'crawl(?:ed|s|ing)|waddl(?:ed|es)|climb(?:ed|s|ing)|follow(?:ed|s)'),
)
VERB_RE = [(kind, re.compile(r'\b(?:' + cue + r')\b', re.I)) for kind, cue in VERBS]
MOVES = {'walk', 'run', 'tiptoe', 'leap', 'fly', 'roll', 'fall', 'curl', 'hug', 'back'}   # QA: must visibly move
# The plan's verbs (schema VERBS) that act something out; the rest are poses the pages already draw.
PLAN = {'walk': 'walk', 'run': 'run', 'pounce': 'leap', 'swipe': 'swipe', 'nudge': 'nudge', 'hug': 'hug',
        'point': 'point', 'breathe_heavy': 'breathe'}
# An act the actor's pictures cannot show falls back to the nearest one they can (pose names of the presets).
GESTURE_POSES = {'wave': ('wave', 'shout'), 'raise': ('wave', 'shout'), 'point': ('point', 'wave'),
                 'cover': ('cover', 'scared'), 'cross': ('cross',), 'grab': ('carry', 'wave'),
                 'hand': ('carry', 'wave')}
SECONDS = {'walk': 1.8, 'run': 1.1, 'tiptoe': 2.6, 'leap': .9, 'fly': 1.4, 'roll': 1.2, 'fall': .6, 'knocked': 1.1,
           'turn': .25, 'back': .6, 'wave': 1.8, 'raise': 1.8, 'point': 2.2, 'cover': 99., 'cross': 99., 'grab': .5,
           'hand': 1.2, 'nod': .9, 'shake': 1., 'lean': 99., 'curl': 1.6, 'sleep': 1.6, 'hug': 1.3, 'nudge': 1.8,
           'lower': .8, 'swipe': 1., 'breathe': 99.}
STRIKE = .38                       # share of a swipe when the paw lands (creatures.actions.strike)
STATE = re.compile(r'\b(?:found|finds|find|saw|sees|see|was|were|is|are|lay|lies|lying|sat|been|being)\s+'
                   r'(?:[\w\'’-]+\s+){0,3}$', re.I)
SPECK = re.compile(r'\bspeck\b|\bdot\b|out\s+of\s+sight|disappear\w*|vanish\w*|tiny\s+(?:point|spot)', re.I)
FLIERS = ('fly',)                  # a species with a flying picture flies when it goes up or down
STOP_WORDS = {'the', 'a', 'an', 'other', 'little', 'big', 'old', 'young', 'great', 'spotted', 'tiny', 'grandma',
              'grandpa', 'mr', 'mrs', 'ms', 'dr', 'mama', 'papa'}
YOUNG = re.compile(r'\b(?:cub|kit|pup|puppy|kitten|chick|calf|foal|baby|little\s+one)s?\b', re.I)


@dataclass
class Act:
    kind: str
    actor: str
    start: float                    # span-local seconds its word is spoken
    target: str | None = None       # who it goes to, touches or hits (a cast key on the page)
    way: str = ''                   # in / out / to / across / up / down / past / home
    word: str = ''
    beat: str = ''
    char: int = 0
    state: bool = False             # "she found Pendo curled up against him": already so when the page opens
    speck: bool = False
    seconds: float = 1.
    thing: object = None            # the sets.Piece a grab or hand-over moves
    # Where it goes, worked out on its page:
    x0: float | None = None
    x1: float | None = None
    lift: float = 0.
    end_pose: str | None = None
    pose: str | None = None         # the picture it shows while it acts (a gesture's pose)
    hold: bool = False              # the act's end state stays for the rest of the page


@dataclass
class Motion:
    dx: float = 0.
    dy: float = 0.
    rotate: float = 0.
    scale: float = 1.
    squash: float = 0.
    pose: str | None = None
    facing: str | None = None
    moving: str | None = None       # 'walk' / 'run' / 'tiptoe' / 'fly': the stride pictures alternate
    gone: bool = False
    pivot: str | None = None        # 'rear': rotate about the back feet (a lowered head)
    effects: list = field(default_factory=list)   # ('arcs', u) ('puff', u)
    x: float | None = None
    placed: bool = False            # an act decides where it is (else its own travel does)


# ------------------------------------------------------------------ reading
def _words(c):
    """Head nouns that point at a cast member: the last word of its name and of its species, singular or plural."""
    out = set()
    for text in (c.get('name') or '', c.get('species') or ''):
        tokens = [t for t in re.findall(r'[a-z]+', text.lower()) if t not in STOP_WORDS]
        if tokens:
            out.add(tokens[-1])
        out.update(t for t in tokens if t in ('king', 'queen'))
    singular = set()
    for t in out:
        for end in ('es', 's'):
            if t.endswith(end) and len(t) > len(end) + 2:
                singular.add(t[:-len(end)])
        if t.endswith('ies'):
            singular.add(t[:-3] + 'y')
    return out | singular


def _noun_refs(book, body, keys, quotes):
    """(offset, cast id, 'noun', end) for 'the hyenas', 'the giant king', 'the cub': a cast member's head noun.
    Only cast members on this page; a noun two of them share means neither."""
    refs = []
    owners = {}
    for cid in keys:
        c = book.cast.get(cid) or {}
        for w in _words(c):
            owners.setdefault(w, set()).add(cid)
    for w, ids in owners.items():
        if len(ids) != 1:
            continue
        cid = next(iter(ids))
        for m in re.finditer(r'\b' + re.escape(w) + r'(?:e?s)?\b', body, re.I):
            if not _inside(quotes, m.start()):
                refs.append((m.start(), cid, 'noun', m.end()))
    young = [cid for cid in keys if (book.cast.get(cid) or {}).get('age') in ('baby', 'young')
             and not book._human(cid)]
    if len(young) == 1:
        for m in YOUNG.finditer(body):
            if not _inside(quotes, m.start()):
                refs.append((m.start(), young[0], 'noun', m.end()))
    return refs


def read(book, sentence, keys, things=()):
    """Acts of one Reader sentence (story.Sentence with .refs): [(kind, actor, target, way, char in beat, word,
    state, speck)]. ``keys``: the cast on its page, ``things``: names of things that can be grabbed or run for."""
    body = sentence.text
    quotes = [(a - sentence.start - 1, b - sentence.start) for a, b in sentence.quotes]
    refs = [r for r in getattr(sentence, 'refs', []) if r[2] != 'of' and not _inside(quotes, r[0])]
    refs = sorted(refs + _noun_refs(book, body, keys, quotes))
    taken, found = [], []
    for kind, pattern in VERB_RE:
        for m in pattern.finditer(body):
            if _inside(quotes, m.start()) or any(a < m.end() and m.start() < b for a, b in taken):
                continue
            if m.group()[0].isupper() and body[:m.start()].rstrip()[-1:].isalnum():
                continue                                   # a name, not a verb
            clause = re.split(r'[,;:]|\b(?:but|while|when)\b', body[:m.start()], flags=re.I)[-1]
            if NEGATED.search(clause):
                continue
            taken.append(m.span())
            found.append((m, kind))
    out = []
    # "With one massive swipe of his heavy paw, he sent the lead hyena flying": one swipe, its paw landing on the
    # one sent flying.
    swipes = [m for m, kind in found if kind == 'swipe']
    for m, kind in sorted(found, key=lambda t: t[0].start()):
        at = m.start()
        before = [r for r in refs if r[3] <= at]
        actor = None
        if before and not re.search(r'\b(?:it|this|that|which|there)\b', body[before[-1][3]:at], re.I):
            actor = before[-1][1]      # not "He tried to roar, but it came out as a squeak": the roar came out
        elif not before and not re.match(r'\s*(?:a|an|the|this|that|some|one)\b', body[:at], re.I) or re.match(
                r'\s*(?:with|without|in|on|at|after|before)\b', body[:at], re.I):
            # "With one massive swipe of his heavy paw, he ...": the sentence's subject. "A tiny green light zipped
            # past": a subject that is not one of the cast, so nobody here.
            actor = sentence.subject
        span_end = m.end()
        stop = re.search(r'[,;:.!?]|\b(?:and|but|while|when|until)\b', body[span_end:])
        tail = body[span_end:span_end + (stop.start() if stop else len(body))]
        inner = [r for r in refs if m.start() <= r[0] < m.end() and r[1] != actor]
        after = [r for r in refs if span_end <= r[0] < span_end + len(tail) + 1 and r[1] != actor]
        target = (inner or after or [(None, None)])[0][1]
        if kind == 'knock':
            if target is None:
                continue
            hit = next((i for i, o in enumerate(out) if o[0] == 'swipe' and o[1] in (actor, None)), None)
            if hit is not None:
                kept = out[hit]
                # The paw lands as the one it hits is "sent flying": cue the swipe from those words.
                out[hit] = ('swipe', kept[1] or actor, target, 'land', sentence.start + at) + kept[5:]
            elif actor is not None:
                out.append(('swipe', actor, target, '', sentence.start + at, m.group(), False, False))
            continue
        if kind == 'swipe' and actor is None and swipes:
            actor = sentence.subject
        if actor is None and kind not in ('walk', 'run', 'tiptoe', 'leap', 'fly'):
            continue
        if kind == 'grab' and m.group().lower().startswith(('tak', 'took')) and not any(
                re.search(r'\b' + re.escape(n) + r'\b', tail, re.I) for n in things):
            continue                                       # "took a deep breath", "takes a while"
        way = _way(kind, m.group(), tail, target, things)
        state = bool(STATE.search(body[:at])) and kind in ('curl', 'sleep', 'hug', 'lean', 'cross', 'cover')
        speck = bool(SPECK.search(body[span_end:]))
        out.append((kind, actor, target, way, sentence.start + at, m.group(), state, speck))
    return out


def _way(kind, verb, tail, target, things):
    v, t = verb.lower(), tail.lower()
    if re.search(r'\bdown\b', v) or re.match(r'\s*(?:back\s+)?down\b', t):
        return 'down'
    if re.search(r'\bup\b', v) or re.match(r'\s*up\b', t):
        return 'up'
    if re.search(r'\b(?:downstairs|upstairs|inside|outside)\b', v) or re.match(
            r'\s*(?:back\s+)?(?:downstairs|upstairs|inside|outside)\b', t):
        return 'there'                                     # out of this room, or into the one on the page
    if re.search(r'\b(?:emerg|appear|return|arriv|enter)', v) or re.match(r'\s*(?:in|inside|through)\b', t) \
            or re.search(r'\b(?:came|comes)\s+(?:back|in|into|inside|through)\b', v) or v.startswith('burst'):
        return 'in'
    if re.search(r'\b(?:scatter|fled|flee|left)', v) or re.search(r'\b(?:away|off|outside|downstairs|upstairs)\b', v) \
            or re.match(r'\s*(?:away|off|outside|downstairs|upstairs|out\b(?!\s+of)|into\s+the\s+(?:dark|night|'
                        r'bush|distance|wood|forest|shadow|fog|trees|grass))', t):
        return 'out'
    if re.match(r'\s*(?:past|by)\b', t) or re.search(r'\b(?:past|by)\b', v):
        return 'past'
    if re.search(r'\bhome\b', v) or re.match(r'\s*(?:back\s+)?home\b', t):
        return 'home'
    if target is not None or re.match(r'\s*(?:to|toward|towards|over\s+to|up\s+to|after|at)\b', t) \
            or re.search(r'\b(?:closer|near|approach|follow|chas|clos)', v + ' ' + t[:12]):
        return 'to'
    if re.match(r'\s*for\s+(?:it|them|the|a|an)\b', t) or any(re.search(r'\b' + re.escape(n) + r'\b', t)
                                                             for n in things):
        return 'to'
    return 'across'


# ------------------------------------------------------------------ staging
def direct(book, shot, lines, at, plan_acts=(), beat=None, window=None):
    """Attach the acts of these Reader sentences (``[(beat id, Sentence)]``) to the shot's figures. ``at(char)``
    turns a character offset of ``beat`` into span-local seconds; ``plan_acts`` are the plan's actions for the
    shot's beat (``{actor, verb}``), used for an actor whose sentences give it no act and for a verb whose doer the
    text does not name ("A tiny green light zipped past his nose"); ``window``: the (start, end) characters of the
    beat this page shows, when it shows only part of a sentence."""
    figures = {f.key: f for f in shot.figures if not f.crowd}
    keys = list(figures)
    things = _thing_names(shot)
    acted = []
    satisfied = book.__dict__.setdefault('_acted_beats', set())
    movers = [p.get('actor') for p in plan_acts if PLAN.get(p.get('verb')) in ('walk', 'run', 'leap')
              and p.get('actor') in figures]
    for bid, sentence in lines:
        timer = at if callable(at) else at[bid]
        for kind, actor, target, way, char, word, state, speck in read(book, sentence, keys, things):
            satisfied.add((bid, actor))
            if window is not None and not window[0] <= char < window[1]:
                continue                                   # its word is spoken on the page before or after
            if actor is None and kind in ('walk', 'run', 'tiptoe', 'leap', 'fly') and movers:
                actor = movers[0]                          # the plan names who moves
            if actor is None:
                continue
            if way == 'there':
                others = [g for g in shot.figures if g.key != actor and not g.crowd]
                way = 'in' if others else 'out'            # "went downstairs, where his mother was": he comes in
            satisfied.add((bid, actor))
            start = timer(char)
            a = Act(kind, actor, start, target, way, word, bid, char, state, speck)
            shown = actor in figures and _attach(book, shot, figures, a)
            if kind in MOVES or kind == 'swipe':
                acted.append(a)
                book.acted.append({'beat': bid, 'char': char, 'word': word, 'actor': actor, 'kind': kind,
                                   'at': round(start, 2), 'shown': bool(shown and _moves(a))})
    mine = {a.actor for a in acted} | {k for k, f in figures.items() if getattr(f, 'acts', None)}
    done = book.__dict__.setdefault('_planned_acts', set())
    for p in plan_acts:
        kind = PLAN.get(p.get('verb'))
        actor = p.get('actor')
        if kind is None or actor not in figures or actor in mine or (beat, actor, kind) in done \
                or (beat, actor) in satisfied:
            continue
        done.add((beat, actor, kind))
        if kind == 'swipe' and book._human(actor):
            continue                                       # a person does not swipe a paw
        if figures[actor].pose in ('sleep', 'lie', 'sit') and kind in ('walk', 'run', 'leap', 'breathe'):
            continue                                       # the plan's walk or pant for someone the page lays down
        named = _first_mention(actor, lines, at)
        start = (named if named is not None else shot.start) + .25
        a = Act(kind, actor, start, None, 'across' if kind in ('walk', 'run') else '', p.get('verb'), beat or '', 0)
        _attach(book, shot, figures, a)
        mine.add(actor)
    _settle(book, shot)


def _first_mention(cid, lines, at):
    """Span-local seconds the actor is first named in these sentences, or None."""
    for bid, s in lines:
        for r in getattr(s, 'refs', []):
            if r[1] == cid:
                return (at if callable(at) else at[bid])(s.start + r[0])
    return None


def _thing_names(shot):
    names = []
    for p in shot.set:
        if p.kind in ('hand', 'thing'):
            names += [t for t in re.split(r'[_\W\d]+', re.sub(r'^(?:fl|tb|set|kd)_', '', p.doodle)) if len(t) > 2]
    return names


def _moves(a):
    if a.kind in ('fly', 'leap', 'swipe') or a.lift:
        return True
    return a.x0 is not None and a.x1 is not None and abs(a.x1 - a.x0) > .015


def _view(shot):
    cx, _, zoom = shot.view
    return cx - .5 / zoom, cx + .5 / zoom


def _can(book, f, pose):
    from .storybook import meta, preset
    doodle = preset(f.species, f.age, f.sex, pose, f.facing, f.marks)[0]
    return meta(doodle).get('pose') == pose


def _attach(book, shot, figures, a):
    """Work out where the act goes on this page and give it to its actor; False when the page cannot show it."""
    f = figures[a.actor]
    t = figures.get(a.target) if a.target else None
    lo, hi = _view(shot)
    half = book._half(f)
    acts = f.__dict__.setdefault('acts', [])
    a.seconds = SECONDS.get(a.kind, 1.)
    kind = a.kind
    if kind in ('walk', 'run', 'tiptoe', 'leap', 'fly', 'roll'):
        flier = _can(book, f, 'fly')
        if kind in ('walk', 'run', 'leap') and a.way in ('up', 'down') and flier:
            kind = a.kind = 'fly'
        if kind == 'run' and flier:
            kind = a.kind = 'fly'                          # a firefly or a bird darts by on its wings
        if kind == 'fly' and not flier and a.way not in ('up', 'down'):
            kind = a.kind = 'run'                          # an animal that cannot fly "zooms" off running
        x, face = _here(f), _face(f)
        if a.way == 'in':
            side = -1 if face == 'r' else 1
            a.x0, a.x1 = (lo - half - .02) if side < 0 else (hi + half + .02), x
        elif a.way == 'out':
            side = 1 if face == 'r' else -1
            if t is None and abs(x - lo) < abs(hi - x) and not acts:
                side = -1
            a.x0, a.x1 = x, (hi + half + .03) if side > 0 else (lo - half - .03)
        elif a.way == 'past' and not lo < x < hi:
            side = 1 if face == 'r' else -1
            a.x0, a.x1 = (lo - half - .02, hi + half + .02) if side > 0 else (hi + half + .02, lo - half - .02)
        elif a.way == 'past':                              # on the page already: it goes on by, out of the frame
            side = 1 if face == 'r' else -1
            a.x0, a.x1 = x, (hi + half + .03) if side > 0 else (lo - half - .03)
        elif a.way in ('to', 'home') and (t is not None or _goal(shot, f) is not None):
            goal = t.x if t is not None else _goal(shot, f)
            reach = (half + (book._half(t) if t is not None else .03)) * (.85 if t is not None else .5)
            side = 1 if goal > x else -1
            a.x0, a.x1 = x, goal - side * reach
            if abs(a.x1 - a.x0) < .06:                     # already beside them: come in from further back
                a.x0 = min(hi - half, max(lo + half, a.x1 - side * .18))
        elif a.way == 'up' and kind == 'fly':
            a.x0, a.x1 = x, x + (.06 if face == 'r' else -.06)
            a.lift = .55
            a.seconds = 2.2
        elif a.way == 'down' and kind == 'fly':
            a.x0, a.x1, a.lift = x - (.06 if face == 'r' else -.06), x, -.55
            a.seconds = 1.8
        else:
            side = 1 if face == 'r' else -1
            room = (hi - half - .02 - x) if side > 0 else (x - lo - half - .02)
            if room < .12:
                side, room = -side, (x - lo - half - .02) if side > 0 else (hi - half - .02 - x)
            step = max(0., min(.28 if kind in ('run', 'fly', 'roll') else .2, room))
            a.x0, a.x1 = x, x + side * step
            if kind == 'leap' and step < .05:
                a.x1 = x
        if a.way in ('in', 'across') or (a.way in ('to', 'home') and t is None):
            a.x1 = _clear(book, shot, f, a.x0, a.x1, lo, hi)
        if kind == 'leap':
            a.lift = .12
        if kind == 'fly' and a.way not in ('up', 'down'):
            a.lift = .0
        dist = abs(a.x1 - a.x0)
        if kind in ('walk', 'tiptoe'):
            a.seconds = max(1., min(3.2, dist / (.14 if kind == 'walk' else .08)))
        elif kind == 'run':
            a.seconds = max(.6, min(2., dist / .3))
        f.travel = 0.
    elif kind in ('curl', 'sleep', 'hug', 'nudge'):
        if t is None:
            t = _partner(shot, f)
        if t is None:
            if kind in ('curl', 'sleep'):
                a.end_pose = 'sleep' if kind == 'sleep' or f.pose == 'sleep' else 'lie'
                a.x0 = a.x1 = f.x
                acts.append(a)
                return True
            return False
        a.target = t.key
        here = _here(f)
        side = 1 if t.x > here else -1
        if kind in ('curl', 'sleep'):
            a.end_pose = 'sleep' if kind == 'sleep' or t.pose == 'sleep' or f.pose == 'sleep' else 'lie'
            reach = (_half_in(book, f, a.end_pose) + book._half(t)) * .55
            f.depth = max(f.depth, t.depth + 1)
        elif kind == 'hug':
            reach = (half + book._half(t)) * .55
            a.end_pose = 'carry' if _can(book, f, 'carry') else None
        else:
            reach = (half + book._half(t)) * .6
        goal = _here(t)
        a.x0, a.x1 = here, goal - side * reach
        if abs(goal - here) <= reach:
            a.x1 = here                                    # already against them: only the pose changes
        if a.state:
            a.start = -99.
        f.travel = 0.
        if not acts:
            f.facing = 'r' if side > 0 else 'l'
    elif kind == 'swipe':
        if a.way == 'land':                                # cued by the words that say it lands
            a.start -= STRIKE * a.seconds
        if t is None:
            t = _partner(shot, f, ahead=True)
        a.target = t.key if t is not None else None
        a.x0 = a.x1 = f.x
        if t is not None:
            side = 1 if t.x > f.x else -1
            if not acts:
                f.facing = 'r' if side > 0 else 'l'
            hit = Act('knocked', t.key, a.start + STRIKE * a.seconds, f.key, 'out', a.word, a.beat, a.char)
            hit.seconds = SECONDS['knocked']
            hit.x0 = t.x
            hit.x1 = (hi + book._half(t) + .05) if side > 0 else (lo - book._half(t) - .05)
            hit.lift = .2
            t.__dict__.setdefault('acts', []).append(hit)
            t.travel = 0.
    elif kind == 'back':
        other = _partner(shot, f)
        side = -1 if other is None or other.x > f.x else 1
        here = _here(f)
        a.x0, a.x1 = here, min(hi - half, max(lo + half, here + side * .05))
        a.end_pose = 'scared' if _can(book, f, 'scared') else None
    elif kind in GESTURE_POSES:
        a.pose = next((p for p in GESTURE_POSES[kind] if _can(book, f, p)), None)
        if kind in ('grab', 'hand'):
            a.thing = _thing(shot, f, a)
            if kind == 'hand' and a.target is None:
                other = _partner(shot, f)
                a.target = other.key if other is not None else None
            if a.thing is not None:
                if kind == 'grab':
                    a.thing.__dict__['taken'] = (a.start + .25, f.key)
                elif a.target is not None:
                    a.thing.__dict__['passed'] = (a.start, a.start + .7, f.key, a.target)
            a.hold = kind == 'grab' or a.thing is not None
        if a.pose is None:
            a.kind, a.pose = 'nod', None                   # a gesture the pictures cannot draw: at least a nod
        a.hold = a.hold or kind in ('cover', 'cross')
    elif kind == 'lean':
        other = t or _partner(shot, f)
        if other is not None:
            f.facing = 'r' if other.x > f.x else 'l'
        a.hold = True
    elif kind == 'lower':
        a.hold = True
    elif kind == 'turn':
        # "The giant king turned around": to face the one behind him. Before it he has his back to them.
        other = t or _partner(shot, f)
        if other is not None and not acts:
            a.way = 'r' if other.x > f.x else 'l'
            f.facing = 'l' if a.way == 'r' else 'r'
        else:
            a.way = 'l' if _face(f) == 'r' else 'r'
    elif kind == 'fall':
        a.end_pose = 'lie' if _can(book, f, 'lie') else None
    acts.append(a)
    return True


def _face(f):
    """The way the figure faces once its acts so far are done: where it last went, or turned to."""
    face = f.facing
    for a in getattr(f, 'acts', ()):
        if a.kind == 'turn':
            face = 'l' if face == 'r' else 'r'
        elif a.x0 is not None and a.x1 is not None and abs(a.x1 - a.x0) > .005 and a.kind not in ('back', 'knocked'):
            face = 'r' if a.x1 > a.x0 else 'l'
    return face


def _clear(book, shot, f, x0, x1, lo, hi):
    """Where a figure coming in or going across stops: its spot, else just past whoever stands there."""
    half = book._half(f)
    for g in shot.figures:
        if g is f or g.crowd:
            continue
        gx, room = _here(g), half + book._half(g) + .01
        if abs(x1 - gx) < room:
            side = 1 if x1 >= gx else -1
            far = gx + side * room
            x1 = far if lo + half <= far <= hi - half else gx - side * room
    return x1


def _here(f):
    """Where the figure stands once its acts so far are done."""
    ends = [a.x1 for a in getattr(f, 'acts', ()) if a.x1 is not None]
    return ends[-1] if ends else f.x


def _half_in(book, f, pose):
    return max(body[2] - body[0] for body, _ in [book._shape(f, pose, 0.)]) / 2


def _goal(shot, f):
    """Where someone running for something goes: a moving thing's end (the orange that rolled into the street),
    else the nearest small thing on the page nobody holds."""
    for p in shot.set:
        if getattr(p, 'motion', None) in ('roll', 'fall', 'slide', 'fly', 'bounce') and p.kind != 'hand':
            return p.x + p.to[0]
    loose = [p for p in shot.set if p.kind == 'thing' and not p.lone and p.height < .15 and not p.holder]
    return min(loose, key=lambda p: abs(p.x - f.x)).x if loose else None


def _partner(shot, f, ahead=False):
    others = [g for g in shot.figures if g is not f and not g.crowd]
    if ahead:
        side = 1 if f.facing == 'r' else -1
        front = [g for g in others if (g.x - f.x) * side > 0]
        others = front or others
    return min(others, key=lambda g: abs(g.x - f.x)) if others else None


def _thing(shot, f, a):
    """The thing a grab takes or a hand-over passes: one already in their hands, else the nearest small thing."""
    held = [p for p in shot.set if p.kind == 'hand' and p.holder == f.key]
    if held:
        return held[0]
    loose = [p for p in shot.set if p.kind in ('hand', 'thing') and not p.lone and p.height < .25]
    return min(loose, key=lambda p: abs(p.x - f.x)) if loose else None


def _settle(book, shot):
    """Order each figure's acts and let a figure that enters stay out of sight until its cue."""
    for f in shot.figures:
        acts = getattr(f, 'acts', None)
        if acts:
            acts.sort(key=lambda a: a.start)


# ------------------------------------------------------------------ drawing
def motion(book, f, shot, local) -> Motion:
    """Where the figure is and what it shows at this time, from its acts (none: exactly where it was laid out)."""
    acts = getattr(f, 'acts', None)
    m = Motion()
    if not acts:
        return m
    x = f.x
    facing = f.facing                                     # turns and journeys change it for the acts after them
    lowered = 0.                                          # a head lowered earlier stays down
    first = next((a for a in acts if a.x0 is not None), None)
    m.placed = first is not None
    if first is not None and local < first.start:
        x = first.x0
    for a in acts:
        if a.start > local:
            break
        u = (local - a.start) / max(.05, a.seconds)
        e = smooth(u)
        if a.x0 is not None and a.x1 is not None and a.kind != 'swipe':
            x = a.x0 + (a.x1 - a.x0) * (e if a.kind not in ('run', 'knocked', 'fly') else min(1., u) ** .9)
        side = 1 if (a.x1 or 0) >= (a.x0 or 0) else -1
        travels = a.x0 is not None and a.x1 is not None and abs(a.x1 - a.x0) > .005
        active = u < 1
        k = a.kind
        ahead = 1 if facing == 'r' else -1               # the way the figure faces now
        if k in ('walk', 'run', 'tiptoe'):
            if travels and k != 'back':
                facing = 'r' if side > 0 else 'l'
            if active:
                m.moving, m.pose = k, ('run' if k == 'run' else 'walk')
                if k == 'tiptoe':
                    m.dy = -.006 * f.height / .42
        elif k == 'fly':
            if active or a.lift > 0:
                m.moving = 'fly' if _can(book, f, 'fly') else None
                m.pose = 'fly' if m.moving else None
            if travels:
                facing = 'r' if side > 0 else 'l'
            if a.lift > 0:                                # up, up, up: smaller and smaller until a speck
                rise = smooth(min(1., u))
                m.dy = -a.lift * rise
                m.scale = 1. - (.9 if a.speck else .6) * rise
            elif a.lift < 0:
                fall = 1. - smooth(min(1., u))
                m.dy = a.lift * fall
                m.scale = 1. - .6 * fall
            else:
                m.dy = -.04 * math.sin(math.pi * min(1., u))
        elif k == 'leap':
            if travels:
                facing = 'r' if side > 0 else 'l'
            if active:
                ahead = 1 if facing == 'r' else -1
                m.dy = -a.lift * math.sin(math.pi * u)
                m.rotate = ahead * 12 * math.cos(math.pi * u)
                m.pose = 'run'
        elif k == 'roll' and active:
            m.rotate = -side * 360 * e
        elif k == 'fall':
            if a.end_pose and u >= .5:
                m.pose = a.end_pose
            else:
                m.rotate = -ahead * (60 if a.end_pose else 80) * smooth(u / (.5 if a.end_pose else .7))
        elif k == 'knocked':
            m.dy = -a.lift * math.sin(math.pi * min(1., u))
            m.rotate = side * -400 * min(1., u)
            m.pose = 'scared' if _can(book, f, 'scared') else None
            if u >= 1:
                m.gone = True
        elif k == 'turn':
            if u >= .5:
                facing = a.way or ('l' if f.facing == 'r' else 'r')
        elif k == 'back':
            if a.end_pose:
                m.pose = a.end_pose
        elif k in ('curl', 'sleep', 'hug', 'nudge'):
            if travels:
                facing = 'r' if side > 0 else 'l'
                ahead = 1 if facing == 'r' else -1
            if active and travels and u < .8:
                m.moving, m.pose = 'walk', 'walk'
            elif a.end_pose and (u >= .8 or not active):
                m.pose = a.end_pose
            if k == 'nudge' and active:
                low = max(lowered, math.sin(math.pi * min(1., max(0., (u - .25) / .75))))
                m.rotate, m.squash = -ahead * 14 * low, .06 * low
                m.pivot = 'rear'
            elif lowered:
                m.rotate, m.squash, m.pivot = -ahead * 14 * lowered, .06 * lowered, 'rear'
        elif k == 'lower':
            lowered = smooth(min(1., u))
            m.rotate, m.squash = -ahead * 14 * lowered, .06 * lowered
            m.pivot = 'rear'
        elif k == 'swipe' and active:
            hit = strike(u)
            m.dx += ahead * .03 * max(0., hit)
            m.rotate = ahead * 12 * max(0., hit)
            m.pivot = 'rear'
            if .3 < u < .75:
                m.effects.append(('arcs', (u - .3) / .45))
        elif k == 'breathe':
            heave = math.sin(math.tau * .9 * (local - a.start))
            m.squash = .07 * heave * smooth(min(1., (local - a.start) / .6))
            if heave < -.2:
                m.effects.append(('puff', (local * .9) % 1.))
        elif k == 'nod' and active:
            m.rotate = -ahead * 6 * abs(math.sin(math.tau * u))
        elif k == 'shake' and active:
            if int(u * 4) % 2 == 1:
                m.facing = 'l' if facing == 'r' else 'r'
        elif k == 'lean':
            m.rotate = -ahead * 8 * smooth(min(1., u / .5))
            m.pivot = 'feet'
        elif a.pose and (active or a.hold):
            m.pose = a.pose
    m.x = x
    if m.facing is None and facing != f.facing:
        m.facing = facing
    return m


def held(piece, local):
    """Who holds a thing at this time when an act moved it: (holder, share of a hand-over done) or None."""
    taken = piece.__dict__.get('taken')
    passed = piece.__dict__.get('passed')
    if passed:
        a, b, giver, taker = passed
        if local < a:
            return giver, 0.
        return (taker, 1.) if local >= b else (giver, (local - a) / (b - a))
    if taken:
        when, who = taken
        return (who, 1.) if local >= when else None
    return None

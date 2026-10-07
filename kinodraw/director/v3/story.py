"""Picture-book reading of a story: who is on stage in each sentence, what they do, and what is around them.

Shared by the offline planner (which characters a scene stages) and the storybook renderer (one shot per
sentence). Conservative English cues only; everything comes from the spoken text, nothing is invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .semantics import mentions, name_key

NEGATED = re.compile(r"\b(?:not|never|no|nobody|cannot|without)\b|\b\w+n['’]t\b", re.I)
QUOTE_OPEN, QUOTE_CLOSE = '"“', '"”'

# Story poses, most specific first. A pose belongs to the cast reference that precedes it in its clause.
POSES = (
    ('roar', r'roar(?:s|ed|ing)?'),
    ('carry', r'carr(?:y|ies|ied|ying)'),
    ('bow', r'bow(?:s|ed|ing)?'),
    ('run', r'ran|runs?|running|raced|racing|dashed|rushed|bolted|sprinted'),
    ('walk', r'walk\w*|led|leads?|leading|guided|guiding|climb\w*|march\w*|stepped|followed|crept'),
    ('sleep', r'slept|sleep\w*|asleep'),
    ('lie', r'lie|lies|lay|lying|rested|resting'),
    ('sit', r'sat|sits?|sitting'),
    ('look_up', r'looked\s+up|lifted\s+(?:his|her|its)\s+(?:heavy\s+)?head'),
    ('look', r'look(?:s|ed|ing)?|watch\w*|noticed|stared?|staring|gaz\w*|saw|listen\w*'),
    ('scared', r'trembl\w*|shiver\w*|afraid|scared|frighten\w*|cower\w*'),
    ('nuzzle', r'nuzzl\w*|nudg\w*|laid\s+(?:his|her)\s+paw'),
    ('happy', r'grinn\w*|grin|smil\w*|laugh\w*'),
)
POSE_RE = [(pose, re.compile(r'\b(?:' + cue + r')\b', re.I)) for pose, cue in POSES]
# "Roar louder, son": an imperative roar inside a parent's quotation.
IMPERATIVE_ROAR = re.compile(r'(?:^|["“!.?]\s*|,\s*)roar\b', re.I)
PRONOUNS = {'he': 'male', 'him': 'male', 'his': 'male', 'she': 'female', 'her': 'female'}

# Group and kin words that point at cast members without naming them.
RELATIONS = (
    (r'\b(?:son|daughter|cub)\b', 'baby'),
    (r'\b(?:father|dad|papa)\b', 'father'),
    (r'\bthe\s+king\b', 'king'),
    (r'\b(?:mother|mum|mom|mama)\b', 'mother'),
    (r'\bthe\s+queen\b', 'queen'),
    (r'\bparents\b', 'parents'),
    (r'\broyal\s+family\b', 'family'),
)

# Plural/singular animal nouns that become small species doodles in the scene (never stand-ins).
CROWD = (
    ('monkey', r'monkeys?'), ('gorilla', r'gorillas?'), ('frog', r'(?:tree\s+)?frogs?'), ('ant', r'ants?'),
    ('elephant', r'elephants?'), ('antelope', r'antelopes?'), ('warthog', r'warthogs?'),
    ('porcupine', r'porcupines?'), ('bird', r'(?:weaver)?birds?'), ('snake', r'pythons?|snakes?'),
    ('hyena', r'hyenas?'), ('zebra', r'zebras?'), ('giraffe', r'giraffes?'), ('parrot', r'parrots?'),
    ('rabbit', r'rabbits?|hares?'), ('mouse', r'mice|mouse'), ('fish', r'fish(?:es)?'),
    ('crocodile', r'crocodiles?'), ('turtle', r'turtles?|tortoises?'), ('owl', r'owls?'),
    ('deer', r'deer'), ('wolf', r'wolf|wolves'), ('fox', r'fox(?:es)?'), ('bear', r'bears?'),
    ('animal', r'animals|creatures|every\s+creature'),
)
CROWD_RE = [(sp, re.compile(r'\b(?:(?P<n>two|three|four|five|six|\d)\s+)?(?:\w+\s+)?(?:' + cue + r')\b', re.I))
            for sp, cue in CROWD]
NOT_CROWD = re.compile(r'\s+(?:path|paths|trail|trails|tracks?)\b', re.I)
NUMBERS = {'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}
LARGE = {'elephant', 'giraffe', 'gorilla', 'zebra', 'crocodile', 'bear'}
# Concrete setting nouns -> library doodles. Sky doodles sit high; the rest stand on the ground.
PROPS = (
    (r'fig\s+tree|trees?|branch(?:es)?|trunks?', 'fl_deciduous_tree'),
    (r'jungle|forest', 'fl_palm_tree'),
    (r'river|stream', 'river'),
    (r'lake|flood\w*|water', 'lake'),
    (r'ridge|hills?|valley|mountains?|path', 'fl_mountain'),
    (r'fruit', 'fl_mango'),
    (r'seed\s+pods?|seeds?|nuts?', 'fl_chestnut'),
    (r'rocks?|stones?', 'fl_rock'),
)
SKY = (
    (r'storm|thunder|lightning', 'fl_cloud_with_lightning_and_rain'),
    (r'rain\w*', 'fl_cloud_with_rain'),
    (r'sun\b|sunlight|dawn|sunrise|morning', 'fl_sun'),
    (r'night|evening|moon\w*', 'fl_crescent_moon'),
    (r'clouds?', 'fl_cloud'),
)
SKY_IDS = {doodle for _, doodle in SKY}


# The whiteboard paper (engine.ink.PAPER_RGB) with dark ink: a picture book, not a night sky.
STORY_PALETTE = {'background': '#ECEBE6', 'ink': '#1B1B1B', 'accent': '#E4AB55', 'accent2': '#287FA3'}
# Library categories that can stand in a story's world; people, faces, symbols and concepts cannot.
STORY_CATEGORIES = {'Animals & Nature', 'nature', 'Travel & Places', 'places', 'Food & Drink', 'food'}


def story_picture(doodle_id) -> bool:
    """A scene doodle a picture book can show: concrete nature, places and food from the library."""
    from ...library import catalog
    entry = catalog().get(doodle_id)
    return bool(entry) and entry.get('category') in STORY_CATEGORIES


@dataclass
class Sentence:
    start: int                      # character offset in the beat's spoken text
    end: int
    text: str
    present: list[str] = field(default_factory=list)   # cast ids on stage, subject first
    subject: str | None = None
    speaker: str | None = None
    poses: dict = field(default_factory=dict)          # cast id -> (pose, char offset in the beat)
    crowd: list = field(default_factory=list)          # [(species, count)]
    props: list = field(default_factory=list)          # ground doodle ids
    sky: list = field(default_factory=list)            # sky doodle ids
    eyes: str | None = None                            # cast id whose eyes the line is about
    eyes_at: int = 0
    roar_lesson: bool = False                          # a parent roars for a watching cub
    crowd_pose: str | None = None                      # "The ants were marching": the crowd's own action


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans; a quotation stays with the sentence that introduces it."""
    spans, start, depth, i = [], 0, False, 0
    while i < len(text):
        ch = text[i]
        if ch in '"“”':
            depth = (not depth) if ch == '"' else ch == '“'
            if not depth and i > 0 and text[i - 1] in '.!?' and _ends_after_quote(text, i + 1):
                spans.append((start, i + 1))
                start = i + 1
        elif ch in '.!?\n' and not depth:
            j = i + 1
            while j < len(text) and text[j] in '.!?':
                j += 1
            if j >= len(text) or text[j].isspace():
                spans.append((start, j))
                start = j
                i = j
                continue
        i += 1
    if text[start:].strip():
        spans.append((start, len(text)))
    out = []
    for a, b in spans:
        while a < b and text[a].isspace():
            a += 1
        if a < b:
            out.append((a, b))
    return out


def _ends_after_quote(text, j):
    """'..." they'd shriek' continues the sentence; '..." Kojo said' too; a capitalised word starts anew."""
    rest = text[j:].lstrip()
    if not rest:
        return True
    word = re.match(r"[\w’']+", rest)
    return bool(word and rest[0].isupper() and word.group().lower() not in ('he', 'she', 'they', 'i', 'we'))


def _quoted(text):
    """Character ranges inside quotation marks."""
    ranges, open_at = [], None
    for i, ch in enumerate(text):
        if ch in '"“”':
            if open_at is None and ch != '”':
                open_at = i
            elif open_at is not None and ch != '“':
                ranges.append((open_at, i))
                open_at = None
    if open_at is not None:
        ranges.append((open_at, len(text)))
    return ranges


def _inside(ranges, at):
    return any(a < at < b for a, b in ranges)


class Reader:
    """Reads a story's beats in order, carrying who is on stage across sentences and beats."""

    def __init__(self, cast: list[dict]):
        self.cast = [c for c in cast if c.get('name')]
        self.by_id = {c['id']: c for c in self.cast}
        self.last = {}            # 'male'/'female' -> last singular referent of that sex
        self.stage = []           # cast ids on stage after the previous sentence
        self.quote = None         # (speaker, addressee, tagged) of the previous sentence's quotation
        self.crowd = []           # the previous sentence's animals

    def _kin(self, kind):
        adults = [c['id'] for c in self.cast if c['age'] != 'baby' and c['kind'] != 'human']
        babies = [c['id'] for c in self.cast if c['age'] == 'baby']
        crowned = [c['id'] for c in self.cast if 'crown' in c.get('marks', [])]
        if kind == 'baby':
            return babies[:1] if len(babies) == 1 else []
        if kind in ('father', 'king', 'mother', 'queen'):
            sex = 'male' if kind in ('father', 'king') else 'female'
            pick = [i for i in adults if self.by_id[i]['sex'] == sex]
            return pick[:1] if len(pick) == 1 else [i for i in pick if i in crowned][:1]
        if kind == 'parents':
            return adults[:2]
        if kind == 'family':
            return adults[:2] + babies[:1]
        return []

    def references(self, text, quotes):
        """[(char offset, cast id, how, end)] in reading order; how is name / pronoun / kin."""
        refs = []
        for c in self.cast:
            key = re.escape(name_key(c['name']))
            for hit in re.finditer(r'(?<!\w)(?:(?:King|Queen)\s+)?' + key + r'(?!\w)', text, re.I):
                refs.append((hit.start(), c['id'], 'name', hit.end()))
        for pattern, kind in RELATIONS:
            for hit in re.finditer(pattern, text, re.I):
                if any(a <= hit.start() < e for a, _, how, e in refs if how == 'name'):
                    continue      # "King Kojo" is the name, not another king
                for cid in self._kin(kind):
                    refs.append((hit.start(), cid, 'kin', hit.end()))
        # "The oldest elephant ... bowed her head": a pronoun after a non-cast animal subject is that animal's.
        animal_subject = re.match(r'\s*(?:the|a|an)\s+(?:\w+\s+){0,2}?(?:' +
                                  '|'.join(cue for _, cue in CROWD) + r')\b', text, re.I)
        for hit in re.finditer(r'\b(he|him|his|she|her)\b', text, re.I):
            if _inside(quotes, hit.start()):
                continue
            if animal_subject and not any(r[0] < hit.start() for r in refs if r[2] == 'name'):
                continue
            sex = PRONOUNS[hit[1].lower()]
            if sex in self.last:
                refs.append((hit.start(), self.last[sex], 'pronoun', hit.end()))
        return sorted(refs)

    def read(self, beat_id, text, section=None) -> list[Sentence]:
        out = []
        for index, (a, b) in enumerate(sentences(text)):
            body = text[a:b]
            quotes = _quoted(body)
            refs = self.references(body, quotes)
            s = Sentence(a, b, body)
            named = list(dict.fromkeys(cid for _, cid, _, _ in refs))
            outside = [r for r in refs if not _inside(quotes, r[0])]
            s.subject = outside[0][1] if outside else None
            tagged = bool(outside)
            they = re.search(r'\b(?:they|they[’\']d|them)\b', ''.join(
                ch if not _inside(quotes, i) else ' ' for i, ch in enumerate(body)), re.I)
            if quotes and s.subject is None and not they:
                # A bare quotation answers the previous bare quotation, or continues its tagged speaker.
                previous = self.quote
                if previous and not previous[2] and previous[1]:
                    s.subject = previous[1]
                elif previous:
                    s.subject = previous[0]
                elif self.stage:
                    s.subject = self.stage[0]
            if quotes:
                s.speaker = None if they else s.subject
                vocative = [r[1] for r in refs if _inside(quotes, r[0]) and r[1] != s.speaker]
                others = [cid for cid in self.stage if cid != s.speaker]
                addressee = vocative[0] if vocative else others[0] if others else None
                self.quote = (s.speaker, addressee, tagged)
            else:
                self.quote = None
            present = list(dict.fromkeys(([s.subject] if s.subject else []) + named))
            self._setting(s, body)
            if they and not s.crowd:
                s.crowd = list(self.crowd)        # "they'd shriek": the monkeys are still there
            if not present and (index or not (s.crowd or s.props)):
                # The same scene continues, or a bare line ("This time, nobody laughed.") keeps its cast.
                present = list(self.stage)
            elif present and (quotes or re.match(r'\s*["“]?\s*(?:he|she|his|her|then)\b', body, re.I)):
                # Dialogue and continued action keep the listener/partner on stage.
                present += [cid for cid in self.stage if cid not in present]
            s.present = present[:4]
            self._poses(s, body, refs, quotes)
            self._eyes(s, body, refs, quotes)
            for _, cid, how, _ in refs:
                sex = self.by_id[cid]['sex']
                if how == 'name' and sex in ('male', 'female'):
                    self.last[sex] = cid
            if s.subject and self.by_id[s.subject]['sex'] in ('male', 'female'):
                self.last[self.by_id[s.subject]['sex']] = s.subject
            self.stage = s.present
            self.crowd = s.crowd
            out.append(s)
        return out

    def _poses(self, s, body, refs, quotes):
        for pose, pattern in POSE_RE:
            for hit in pattern.finditer(body):
                at = hit.start()
                clause = re.split(r'[,;:]|\b(?:but|while|when)\b', body[:at], flags=re.I)[-1]
                if NEGATED.search(clause) or re.search(r'\bnobody\b', body[:at], re.I):
                    continue
                if _inside(quotes, at):
                    quote = next(body[q0:q1] for q0, q1 in quotes if q0 < at < q1)
                    # "Roar louder, son": the parent shows the watching cub how a king roars.
                    if (pose == 'roar' and s.speaker and IMPERATIVE_ROAR.search(quote) and any(
                            self.by_id[cid]['age'] == 'baby' for cid in s.present if cid != s.speaker)):
                        s.roar_lesson = True
                        s.poses[s.speaker] = ('roar', s.start + at)
                    continue
                before = [r for r in refs if r[3] <= at and not _inside(quotes, r[0])]
                # "The ants were marching", "the old elephants used to climb": a nearer animal noun owns the verb.
                animals = [m.start() for _, pattern in CROWD_RE for m in pattern.finditer(body[:at])
                           if not _inside(quotes, m.start())]
                if s.crowd and animals and (not before or max(animals) > before[-1][3]):
                    s.crowd_pose = s.crowd_pose or pose
                    continue
                if before:
                    nearest = before[-1][0]
                    owners = [r[1] for r in before if r[0] == nearest]
                else:
                    owners = [s.subject] if s.subject else []
                for owner in owners:
                    if owner not in s.poses:
                        s.poses[owner] = (pose, s.start + at)
        if s.roar_lesson and s.speaker:
            for cid in s.present:
                if cid != s.speaker and self.by_id[cid]['age'] == 'baby':
                    s.poses[cid] = ('look_up', s.poses[s.speaker][1])

    def _eyes(self, s, body, refs, quotes):
        """'saw no fear in Pendo's eyes' -> Pendo; 'looked at his son' -> the son; 'his eyes' -> him."""
        owner, at = None, None
        for hit in re.finditer(r"(?:(\w+)['’]s|\b(his|her))\s+(?:[\w-]+\s+){0,2}(eyes?)\b", body, re.I):
            if _inside(quotes, hit.start()):
                continue
            if hit[1]:
                owner = next((cid for _, cid, how, _ in refs if how == 'name' and
                              mentions(self.by_id[cid]['name'], hit[1])), None)
            else:
                owner = next((r[1] for r in refs if r[0] == hit.start() and r[2] == 'pronoun'), None)
            if owner:
                at = hit.start(3)
                break
        if owner is None:
            for hit in re.finditer(r'\b(?:look(?:ed|s|ing)?|star(?:ed|es|ing)|gaz(?:ed|es|ing))\s+(?:at|into)\b', body, re.I):
                if _inside(quotes, hit.start()):
                    continue
                after = [r for r in refs if hit.end() <= r[0] < hit.end() + 24 and
                         body[r[0]:r[3]].lower() not in ('his', 'her')]
                if after:
                    owner, at = after[0][1], hit.start()
                    break
        if owner:
            s.eyes, s.eyes_at = owner, s.start + at
            if owner not in s.present:
                s.present.append(owner)

    def _setting(self, s, body):
        cast_species = {c['species'] for c in self.cast}
        cast_species |= {'lion' if sp == 'lioness' else 'tiger' if sp == 'tigress' else sp for sp in cast_species}
        for species, pattern in CROWD_RE:
            hit = pattern.search(body)
            if not hit or species in cast_species or NOT_CROWD.match(body[hit.end():]):
                continue
            if hit.group().split()[-1][0].isupper() and hit.start() > 0:
                continue      # "Little Prince Mouse!" is a nickname, not a mouse
            clause = re.split(r'[,;:]|\bbut\b', body[:hit.start()], flags=re.I)[-1]
            if re.search(r'\bno\s*$|\bnot\s+(?:a|one)\s*$', clause, re.I):
                continue
            word = hit.group().lower().split()[-1]
            plural = ((word.endswith('s') and not word.endswith('ss')) or word in ('mice', 'wolves', 'deer', 'antelope')
                      or 'every ' in hit.group().lower())
            number = (hit['n'] or '').lower()
            count = (NUMBERS[number] if number in NUMBERS else int(number) if number.isdigit() else
                     (2 if species in LARGE else 3) if plural else 1)
            s.crowd.append((species, min(count, 5)))
        for pattern, doodle in PROPS:
            if re.search(r'\b(?:' + pattern + r')\b', body, re.I) and doodle not in s.props:
                s.props.append(doodle)
        for pattern, doodle in SKY:
            if re.search(r'\b(?:' + pattern + r')', body, re.I) and doodle not in s.sky:
                s.sky.append(doodle)
        s.props = s.props[:2]
        s.sky = s.sky[:2]


def read_beats(script_beats, cast) -> dict:
    """beat id -> [Sentence] for a story read in order."""
    reader = Reader(cast)
    return {b['id']: reader.read(b['id'], b['spoken'], b.get('section')) for b in script_beats}

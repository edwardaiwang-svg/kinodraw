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
    ('lie', r'lie|lies|lay|lying|rested|resting|sprawl\w*|reclin\w*|lounging|curled\s+up'),
    ('sit', r'sat|sits?|sitting|seated|perched|squeez\w*\s+(?:onto|into|in|on)|plopped|plonked'),
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
HUMAN_WORDS = {'human', 'boy', 'girl', 'man', 'woman'}

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

# People a story points at without naming them: (role, cue, sex, age band). Longer cues first; singular only, so
# "every child" or "the kids" stay out of the picture. A role resolves to the cast member whose name holds it
# ("Theo's mother", "Grandma Rose"), else to the one cast member it can only mean, else to an extra person.
PEOPLE = (
    ('grandmother', r'grand(?:mother|ma|mama|mom|mum|mommy)|granny|gran|nana|nan|grammy|nainai|oma|abuela', 'female', 'elder'),
    ('grandfather', r'grand(?:father|pa|papa|dad|daddy)|gramps|grampa|grandpop|yeye|opa|abuelo', 'male', 'elder'),
    ('granddaughter', r'granddaughter', 'female', 'child'),
    ('grandson', r'grandson', 'male', 'child'),
    ('grandchild', r'grand(?:child|kid)', None, 'child'),
    ('mother', r'(?:step)?(?:mother|mom|mum|mama|mommy|mummy)', 'female', 'adult'),
    ('father', r'(?:step)?(?:father|dad|daddy|papa)', 'male', 'adult'),
    ('daughter', r'daughter', 'female', None),
    ('son', r'son', 'male', None),
    ('sister', r'(?:big\s+|little\s+|older\s+|younger\s+)?sister', 'female', None),
    ('brother', r'(?:big\s+|little\s+|older\s+|younger\s+)?brother', 'male', None),
    ('aunt', r'aunt|auntie|aunty', 'female', 'adult'),
    ('uncle', r'uncle', 'male', 'adult'),
    ('wife', r'wife', 'female', 'adult'),
    ('husband', r'husband', 'male', 'adult'),
    ('girlfriend', r'girlfriend', 'female', None),
    ('boyfriend', r'boyfriend', 'male', None),
    ('cousin', r'cousin', None, None),
    ('friend', r'(?:best\s+)?friend|buddy|pal', None, None),
    ('teacher', r'teacher|professor|coach|tutor|principal', None, 'adult'),
    ('doctor', r'doctor|nurse|dentist|vet', None, 'adult'),
    ('worker', r'waiter|waitress|clerk|cashier|driver|boss|officer|policeman|policewoman|shopkeeper|baker|'
               r'postman|mail\s+carrier|librarian|neighbou?r|customer|passenger|guard|farmer|manager', None, 'adult'),
    ('stranger', r'stranger', None, 'adult'),
    ('old woman', r'old\s+(?:woman|lady)', 'female', 'elder'),
    ('old man', r'old\s+man', 'male', 'elder'),
    ('woman', r'woman|lady', 'female', 'adult'),
    ('man', r'man|gentleman|guy', 'male', 'adult'),
    ('teenager', r'teen(?:ager)?', None, 'teen'),
    ('girl', r'girl', 'female', 'child'),
    ('boy', r'boy', 'male', 'child'),
    ('baby', r'baby|infant|toddler|newborn', None, 'baby'),
    ('child', r'child|kid', None, 'child'),
)
# Roles that name one particular relation of somebody: the one cast member who fits is that person. Other roles
# (a stranger, a woman) are somebody new unless a cast member is called that or "the girl" points back at one.
KIN = {'grandmother', 'grandfather', 'granddaughter', 'grandson', 'grandchild', 'mother', 'father', 'daughter', 'son',
       'sister', 'brother', 'aunt', 'uncle', 'wife', 'husband', 'girlfriend', 'boyfriend', 'cousin', 'friend',
       'teacher', 'doctor'}
PEOPLE_RE = [(role, re.compile(r'\b(?:' + cue + r')\b', re.I), sex, age)
             for role, cue, sex, age in PEOPLE]
# The animal kin word each role is in an animal story ("his mother" of a cub is a lioness).
ANIMAL_KIN = {'mother': 'mother', 'father': 'father', 'son': 'baby', 'daughter': 'baby'}
GENERIC = re.compile(r'\b(?:every|each|no|any|all|some|most|other)\s+(?:\w+\s+)?$', re.I)
POSSESSIVE = re.compile(r'^(?:[’\']s)?\s+(?:[a-z]+\s+){0,2}$')
OWNERS = {'his', 'her', 'your', 'their', 'my', 'our'}

# Ages a story states. Bands: baby < 3 <= child < 13 <= teen < 20 <= adult < 60 <= elder.
_UNITS = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
          'seventeen eighteen nineteen').split()
_TENS = 'twenty thirty forty fifty sixty seventy eighty ninety'.split()
NUM = (r'(?:\d{1,3}|(?:' + '|'.join(_TENS) + r')(?:[\s-](?:' + '|'.join(_UNITS[1:10]) + r'))?|' +
       '|'.join(sorted(_UNITS[1:], key=len, reverse=True)) + r'|a\s+hundred)')
AGE_CUES = (
    re.compile(r'\b(?:at|aged)\s+(?:the\s+age\s+of\s+)?(?P<n>' + NUM + r')(?=\s*[,.;!?]|\s+years?\b|\s+(?:he|she|they|I|we|you)\b|$)', re.I),
    re.compile(r'\b(?P<n>' + NUM + r')[\s-]+years?[\s-]+old\b', re.I),
    re.compile(r'\b(?P<who>[\w’\']+)\s+(?:was|were|is|turned|had\s+turned)\s+(?:almost\s+|nearly\s+|only\s+|just\s+)?'
               r'(?P<n>' + NUM + r')(?=\s*[,.;!?]|\s+(?:when|and|now|then|that)\b|$)', re.I),
)
BAND_CUES = (
    ('elder', r'\b(?:he|she|they)\s+(?:was|were|grew|got|had\s+grown|became)\s+(?:very\s+|quite\s+|so\s+|too\s+)?old\b|'
              r'\bin\s+(?:his|her|their)\s+(?:old\s+age|sixties|seventies|eighties|nineties)\b|\bas\s+an\s+old\s+(?:man|woman|lady)\b'),
    ('child', r'\b(?:he|she|they)\s+(?:was|were)\s+(?:very\s+|still\s+|so\s+|only\s+)?(?:little|small|young|'
              r'a\s+(?:little\s+|small\s+)?(?:boy|girl|child|kid|toddler))\b|\bas\s+an?\s+(?:little\s+)?(?:child|kid|boy|girl|toddler)\b|'
              r'\bin\s+(?:his|her|their)\s+childhood\b'),
    ('baby', r'\b(?:he|she)\s+was\s+(?:just\s+|only\s+)?a\s+baby\b|\bas\s+a\s+baby\b'),
    ('teen', r'\b(?:he|she|they)\s+(?:was|were)\s+a\s+teen(?:ager)?\b|\bas\s+a\s+teen(?:ager)?\b|\bin\s+(?:his|her|their)\s+teens\b'),
    ('adult', r'\b(?:he|she|they)\s+(?:grew\s+up|(?:was|were|had)\s+(?:all\s+)?grown(?:\s+up)?)\b|\bas\s+an?\s+(?:adult|grown[\s-]?up)\b'),
)
BAND_CUES = [(band, re.compile(cue, re.I)) for band, cue in BAND_CUES]
# Time passing: "N years later" moves everyone on from here; "for N years" by the end of the sentence.
LATER = re.compile(r'\b(?:(?P<n>' + NUM + r')|many|several|(?P<d>decades))\s+years?\s+(?:later|passed|went\s+by)\b|'
                   r'\bdecades\s+later\b', re.I)
SPELL = re.compile(r'\bfor\s+(?P<n>' + NUM + r')\s+years\b', re.I)
BAND_YEARS = {'baby': 1, 'child': 8, 'teen': 16, 'adult': 35, 'elder': 75}
PLAN_BAND = {'baby': 'baby', 'young': 'child', 'adult': 'adult', 'old': 'elder'}


def number(text):
    """'seventeen' -> 17, 'sixty-one' -> 61, '19' -> 19; None otherwise."""
    words = re.split(r'[\s-]+', text.strip().lower())
    if words[0].isdigit():
        return int(words[0])
    if words == ['a', 'hundred']:
        return 100
    total = 0
    for w in words:
        total += _UNITS.index(w) if w in _UNITS else 10 * (_TENS.index(w) + 2) if w in _TENS else 0
    return total or None


def band(years):
    return 'baby' if years < 3 else 'child' if years < 13 else 'teen' if years < 20 else 'adult' if years < 60 else 'elder'

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


def titled(title, first_line) -> bool:
    """A story shows its title once, and not at all when its first line already is the title."""
    words = lambda text: re.findall(r'\w+', str(text).lower())
    own, line = words(title), words(first_line)
    return bool(own) and line[:len(own)] != own


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
    quotes: list = field(default_factory=list)         # (start, end) char offsets in the beat of each quoted line
    extras: list = field(default_factory=list)         # people the story mentions who are not in the cast
    ages: dict = field(default_factory=dict)           # person id -> age band (baby/child/teen/adult/elder) now


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


SPEAKER_LABEL = re.compile(r'\s*([A-Za-z][\w’\'.]*(?:\s[A-Za-z][\w’\'.]*)?)\s*:\s+')


def _speech(body, start):
    """Quote-like ranges (open, close) of a screenplay line's spoken words: from ``start``, outside [brackets]."""
    ranges, at = [], start
    for m in list(re.finditer(r'\[[^\]]*\]?', body[start:])) + [None]:
        end = start + m.start() if m else len(body)
        if re.search(r'\w', body[at:end]):
            ranges.append((at - 1, end))
        at = start + m.end() if m else end
    return ranges


def _inside(ranges, at):
    return any(a < at < b for a, b in ranges)


class Reader:
    """Reads a story's beats in order, carrying who is on stage across sentences and beats."""

    def __init__(self, cast: list[dict]):
        self.cast = [c for c in cast if c.get('name')]
        self.by_id = {c['id']: c for c in self.cast}
        self.last = {}            # 'male'/'female' -> last singular referent of that sex
        self.unsexed = None       # the last person referred to whose sex the story has not told yet
        self.stage = []           # cast ids on stage after the previous sentence
        self.quote = None         # (speaker, addressee, tagged) of the previous sentence's quotation
        self.crowd = []           # the previous sentence's animals
        self.focus = None         # the person the story follows (most referred to): "you" in a note to them is them
        self.mentions = {}
        self.seen = set()
        self.sexes = {}           # sex the story's pronouns showed for a cast member the plan left unknown
        self.years = {}           # cast id -> age in years the story has reached
        self.first_years = {}     # cast id -> the first age the story states (their age before it, too)
        self.people_story = any(c.get('kind') == 'human' for c in self.cast) or not any(
            c.get('kind') not in ('human', 'object') for c in self.cast)

    def prime(self, texts):
        """Read the whole story once ahead: the sex its pronouns give someone the plan left unknown, and the first
        age in years it states for each person ("at seventeen"), which is their age before that line too."""
        ahead = Reader(list(self.by_id.values()))
        for text in texts:
            ahead.read(None, text)
        self.sexes.update(ahead.sexes)
        self.first_years = dict(ahead.first_years)

    def sex(self, cid):
        c = self.by_id[cid]
        return c['sex'] if c.get('sex') in ('male', 'female') else self.sexes.get(cid)

    def human(self, cid):
        return self.by_id[cid].get('kind') == 'human' or self.by_id[cid].get('species') in HUMAN_WORDS

    def age_band(self, cid):
        """A person's age band now: the age the story has reached, else the first it states, else the plan's."""
        years = self.years.get(cid, self.first_years.get(cid))
        if years is not None:
            return band(years)
        c = self.by_id[cid]
        return c.get('band') or PLAN_BAND.get(c.get('age'), 'adult')

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

    def _person(self, role, word, sex, age, owner, definite):
        """The cast member a role word means ("his mother"), never its owner or the person the story follows."""
        cue = next(c for r, c, _, _ in PEOPLE if r == role)
        called = [c['id'] for c in self.cast if c['id'] != owner and re.search(
            r'\b(?:' + cue + r')\b', name_key(c['name']) + ' ' + c['id'].replace('_', ' '), re.I)]
        if called:
            return called[0]
        if role not in KIN and not (definite and role != 'stranger'):
            return None

        def fits(c):
            if c['id'] in (owner, self.focus if owner is None else None) or not self.human(c['id']):
                return False
            if sex and self.sex(c['id']) not in (sex, None):
                return False
            have = PLAN_BAND.get(c.get('age'), 'adult')
            return not age or have == age or {have, age} <= {'adult', 'elder'} or {have, age} <= {'child', 'teen', 'baby'}
        pick = [c['id'] for c in self.cast if fits(c) and (role in KIN or c['id'] in self.seen)]
        return pick[0] if len(pick) == 1 else None

    def _extra(self, word, sex, age):
        """Somebody the story mentions who is not in the cast ("the stranger"): one extra person per word."""
        key = '+' + re.sub(r'\W+', '_', word.lower())
        if key not in self.by_id:
            self.by_id[key] = {'id': key, 'name': word, 'kind': 'human', 'species': 'human', 'extra': True,
                               'sex': sex or ('female' if sum(map(ord, key)) % 2 else 'male'),
                               'age': {'elder': 'old', 'child': 'young', 'teen': 'young'}.get(age, age or 'adult'),
                               'band': age or 'adult', 'marks': []}
        return key

    def references(self, text, quotes):
        """[(char offset, cast id, how, end)] in reading order; how is name / pronoun / kin / you / of (the owner in
        "his mother", which is not the sentence's subject)."""
        tokens = []
        for c in self.cast:
            key = re.escape(name_key(c['name']))
            for hit in re.finditer(r'(?<!\w)(?:(?:King|Queen)\s+)?' + key + r'(?!\w)', text, re.I):
                tokens.append((hit.start(), hit.end(), 'name', c['id']))
        # "Noor's father" is the father, not Noor as well: a name inside a longer name is not a reference.
        tokens = [t for t in tokens if not any(o[0] <= t[0] and t[1] <= o[1] and o[1] - o[0] > t[1] - t[0]
                                               for o in tokens)]
        names = [(a, e) for a, e, how, _ in tokens]
        taken = list(names)
        for role, pattern, sex, age in PEOPLE_RE:
            for hit in pattern.finditer(text):
                if any(a < hit.end() and hit.start() < e for a, e in taken):
                    continue      # "King Kojo" is the name, not another king; "old man" is not a man as well
                taken.append(hit.span())
                tokens.append((hit.start(), hit.end(), 'person', (role, hit.group(), sex, age, ANIMAL_KIN.get(role))))
        for pattern, kind in RELATIONS:
            for hit in re.finditer(pattern, text, re.I):
                if not any(a < hit.end() and hit.start() < e for a, e in taken):
                    tokens.append((hit.start(), hit.end(), 'person', (None, hit.group(), None, None, kind)))
        # "The oldest elephant ... bowed her head": a pronoun after a non-cast animal subject is that animal's.
        animal_subject = re.match(r'\s*(?:the|a|an)\s+(?:\w+\s+){0,2}?(?:' +
                                  '|'.join(cue for _, cue in CROWD) + r')\b', text, re.I)
        for hit in re.finditer(r'\b(he|him|his|she|her)\b', text, re.I):
            if not _inside(quotes, hit.start()):
                tokens.append((hit.start(), hit.end(), 'pronoun', hit[1].lower()))
        for hit in re.finditer(r'\b(?:you|your|yours|yourself)\b', text, re.I):
            if not _inside(quotes, hit.start()) and self.focus:
                tokens.append((hit.start(), hit.end(), 'you', hit.group().lower()))
        refs = []
        for start, end, how, what in sorted(tokens, key=lambda t: (t[0], -t[1])):
            quoted = _inside(quotes, start)
            local = [r for r in refs if not _inside(quotes, r[0])]
            if how == 'name':
                refs.append([start, what, 'name', end])
            elif how == 'you':
                refs.append([start, self.focus, 'you', end])
            elif how == 'pronoun':
                if animal_subject and not any(r[0] < start for r in refs if r[2] == 'name'):
                    continue
                cid = self._pronoun(PRONOUNS[what], local)
                if cid:
                    refs.append([start, cid, 'pronoun', end])
            else:
                role, word, sex, age, kind = what
                before = text[:start]
                if GENERIC.search(before):
                    continue
                owner = next((r for r in reversed(local) if POSSESSIVE.match(text[r[3]:start]) and (
                    r[2] == 'name' and text[r[3]:start][:1] in '’\'' or text[r[0]:r[3]].lower() in OWNERS)), None)
                owner_id = owner[1] if owner else None
                cid = None
                if role and (owner_id is None or self.human(owner_id)):
                    definite = bool(re.search(r'\bthe\s+(?:\w+\s+)?$', before, re.I))
                    cid = self._person(role, word, sex, age, owner_id, definite)
                if cid is None and kind and (owner_id is None or not self.human(owner_id)):
                    cid = next(iter(self._kin(kind)), None)
                    if kind in ('parents', 'family'):
                        for other in self._kin(kind):
                            refs.append([start, other, 'kin', end])
                        continue
                if cid is None and role and not quoted and self.people_story and (
                        owner_id is None or self.human(owner_id)):
                    cid = self._extra(word, sex, age)
                if cid is None:
                    continue
                if owner:
                    owner[2] = 'of'
                refs.append([start, cid, 'kin', end])
        refs = [tuple(r) for r in refs]
        return sorted(refs)

    def _pronoun(self, sex, local):
        """He/she: the sentence's subject when it fits, else the nearest person of that sex before it in the
        sentence, else someone whose sex the story has not told yet (and now has), else the last one of that sex."""
        persons = [r for r in local if r[2] != 'of'] or local
        if persons and self.sex(persons[0][1]) == sex:
            return persons[0][1]
        for r in reversed(local):
            if self.sex(r[1]) == sex:
                return r[1]
        for r in reversed(local):
            if self.sex(r[1]) is None and self.human(r[1]):
                self.sexes[r[1]] = sex
                return r[1]
        if sex in self.last:
            return self.last[sex]
        if self.unsexed and self.sex(self.unsexed) is None:
            self.sexes[self.unsexed] = sex
            return self.unsexed
        return None

    def read(self, beat_id, text, section=None, talker=None) -> list[Sentence]:
        """``talker``: the cast member the plan says speaks in this beat, for a quotation the text does not tag."""
        out = []
        # A screenplay line ("JULES: Okay, I'm picking. [She points.]") is that person's speech, bracketed stage
        # directions aside.
        label = SPEAKER_LABEL.match(text)
        speaker = next((c['id'] for c in self.cast if label and label[1].lower() in (
            name_key(c['name']), name_key(c['name']).split()[0])), None)
        talker = speaker or talker
        for index, (a, b) in enumerate(sentences(text)):
            body = text[a:b]
            quotes = _quoted(body)
            if speaker and not quotes:
                quotes = _speech(body, max(0, label.end() - a))
            refs = self.references(body, quotes)
            s = Sentence(a, b, body)
            s.quotes = [(a + q0 + 1, a + q1) for q0, q1 in quotes]
            named = list(dict.fromkeys(cid for _, cid, _, _ in refs))
            outside = [r for r in refs if not _inside(quotes, r[0])]
            subjects = [r for r in outside if r[2] != 'of']
            s.subject = subjects[0][1] if subjects else outside[0][1] if outside else None
            tagged = bool(outside)
            they = re.search(r'\b(?:they|they[’\']d|them)\b', ''.join(
                ch if not _inside(quotes, i) else ' ' for i, ch in enumerate(body)), re.I)
            if quotes and s.subject is None and not they:
                # A bare quotation answers the previous bare quotation, or one in the paragraph before (a new
                # paragraph is a new turn), or continues its tagged speaker in the same paragraph.
                previous = self.quote
                if talker in self.by_id:
                    s.subject = talker
                elif previous and (not previous[2] or index == 0) and previous[1]:
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
            s.extras = [cid for cid in present if self.by_id[cid].get('extra')][:2]
            s.present = [cid for cid in present if not self.by_id[cid].get('extra')][:4]
            self._poses(s, body, refs, quotes)
            self._eyes(s, body, refs, quotes)
            self._ages(s, body, refs, quotes)
            for _, cid, how, _ in refs:
                sex = self.sex(cid)
                if how in ('name', 'kin') and sex in ('male', 'female'):
                    self.last[sex] = cid
                if self.human(cid) and sex is None:
                    self.unsexed = cid
                self.seen.add(cid)
            if s.subject and self.sex(s.subject) in ('male', 'female'):
                self.last[self.sex(s.subject)] = s.subject
            for _, cid, how, _ in refs:
                if how in ('name', 'pronoun') and not self.by_id[cid].get('extra'):
                    self.mentions[cid] = self.mentions.get(cid, 0) + 1
                    if self.mentions[cid] >= self.mentions.get(self.focus, 0):
                        self.focus = cid
            self.stage = s.present          # an extra person is on the page for the line that mentions them
            self.crowd = s.crowd
            out.append(s)
        return out

    def _ages(self, s, body, refs, quotes):
        """The age band of every person on stage in this sentence. A stated age ("at seventeen", "when he was very
        old") belongs to the nearest person; one in a past-perfect clause ("she'd opened hers at nineteen") is a look
        back for this line only. A teenager's moments recalled in a note to them ("the afternoon you taught Lily")
        show them as a child. "N years later" moves everyone on; "for N years" by the end of the line."""
        outside = [r for r in refs if not _inside(quotes, r[0])]
        stated = {}

        def owner(m):
            inside = [r for r in outside if m.start() <= r[0] < m.end()]
            if inside:
                return inside[0][1]
            near = sorted(outside, key=lambda r: min(abs(r[0] - m.end()), abs(m.start() - r[3])))
            return near[0][1] if near else self.focus

        cues = [(m, number(m['n'])) for pattern in AGE_CUES for m in pattern.finditer(body)]
        cues += [(m, BAND_YEARS[b]) for b, pattern in BAND_CUES for m in pattern.finditer(body)]
        for m, years in sorted(cues, key=lambda t: t[0].start()):
            if years is None or years > 120 or _inside(quotes, m.start()):
                continue
            if 'who' in m.re.groupindex and not any(r[0] == m.start('who') for r in outside):
                continue      # "Maya was seven", "she was seven"; never "it was ten"
            cid = owner(m)
            if not cid or cid not in self.by_id or not self.human(cid):
                continue
            clause = re.split(r'[,;:]', body[:m.start()])[-1]
            if re.search(r'\bhad\b|\w[’\']d\b', clause, re.I):
                stated[cid] = band(years)
                continue
            self.years[cid] = years
            if m.re in AGE_CUES:
                self.first_years.setdefault(cid, years)     # a stated number: their age before this line too
        later = LATER.search(body)
        if later and not _inside(quotes, later.start()):
            step = number(later['n']) if later['n'] else 30 if later['d'] or 'decade' in later.group().lower() else 10
            for cid in list(self.years):
                self.years[cid] += step or 0
        for cid in s.present + s.extras:
            if cid not in self.by_id or not self.human(cid):
                continue
            now = stated.get(cid) or self.age_band(cid)
            if now == 'teen' and any(r[1] == cid and body[r[0]:r[3]].lower().startswith('you') for r in outside):
                now = 'child'
            s.ages[cid] = now
        spell = SPELL.search(body)
        if spell and not _inside(quotes, spell.start()):
            for cid in list(self.years):
                self.years[cid] += number(spell['n']) or 0

    def _poses(self, s, body, refs, quotes):
        for pose, pattern in POSE_RE:
            for hit in pattern.finditer(body):
                at = hit.start()
                if hit.group()[0].isupper() and body[:at].rstrip()[-1:].isalnum():
                    continue      # "the fourteenth of March", "Mr Walker": a name, not a pose
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
    reader.prime([b['spoken'] for b in script_beats])
    return {b['id']: reader.read(b['id'], b['spoken'], b.get('section')) for b in script_beats}

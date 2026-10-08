"""The pictures offered to the whole-video planner, per beat.

The picture director's own candidates are few by design (it must never draw a wrong picture), which left the
planner unable to show a house, a couch or a television that the story plainly has. Here each beat is offered,
in this order: those candidates; every picture the beat's words name (any keyword, best doodle first, a line
icon only when no doodle has the word); the furniture and set pieces of the places the beat happens in (named
in the beat, else the place the story last established); people of the ages and poses the beat mentions without
naming them (a stranger, a child asleep); the things the story keeps coming back to; then the closest pictures
by meaning. Each beat gets at most CAP pictures and the whole request stays under the Cloud's size limit.
English cues decide places and people; other languages get named and meaning matches.

A keyword is only a guess at a picture: "drip" is also an IV drip, "sign" a stop sign, "jump" a kangaroo, "king" a
crown, "Falls" a falling leaf. In English a word offers a picture only in the sense its text uses it (``Sense``):
never a word inside a proper name, a command verb, a character's own body part or an animal's title; in a math
lesson only the things a number counts; and the picture must be what the word names there. When no picture fits
the sense, the word offers none, and the planner stages the place or the person instead.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache

import numpy as np

from ...library import catalog, creatures, imported
from ..match import (EN_STOP, PACK_PENALTY, _model, _normalize, catalog_vectors, es_gloss, in_name, proper_names,
                     singular, unname)

CAP = 20                    # Cloud LIMITS.candidatesPerBeat
REQUEST_LIMIT = 56_000      # Cloud LIMITS.requestBytes is 60,000 for the whole JSON body (video id included)
DESC = 70
QUOTA = {'rules': 8, 'named': 10, 'place': 8, 'people': 4, 'motif': 3}
ALIASES = {'tv': 'television', 'telly': 'television', 'sofa': 'couch', 'cellphone': 'phone', 'fridge': 'refrigerator',
           'mom': 'mother', 'mum': 'mother', 'dad': 'father', 'grandpa': 'grandfather', 'grandma': 'grandmother'}
# Function words and abstractions that never name a picture a story can show.
STOP = set('''a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those there here they them their we our you your he she his her i me my mine us not no yes do does did
done can could will would should may might must shall have has had just also very really more most much many few less
least some any all each every other another such same own than too only even still again ever never always often
sometimes up down out over under into onto about after before between during while where when why how what which who
whom whose because though although until since per via once off away around through without within upon toward towards
one two three four five six seven eight nine ten first last next way thing things something nothing anything everything
time times point kind lot lots part side end bit sort got get go went come came say said tell told make made take took
know knew think thought want wanted like need seem seemed felt feel let put keep kept turn turned happen happened
life moment stuff answer reason meaning purpose fact problem matter idea chance rest half whole bunch sense mind
people person someone everyone anyone nobody small big little large new old good bad great long short high low
day days year years week weeks today tonight morning afternoon evening night'''.split()) | (
    EN_STOP - set('white black red blue green yellow orange pink purple brown gray grey'.split()))  # colours name things too
# Line-icon kinds that are interface or abstract symbols, never a thing in a story's world.
UI_CATEGORIES = {'Arrows', 'Shapes', 'Charts', 'Database', 'Development', 'Version control', 'Logic', 'Mood', 'Gender',
                 'Symbols', 'Currencies', 'shapes', 'symbols', 'graphs'}
UI_WORDS = re.compile(r'\b(?:layout|sidebar|border|align\w*|arrows?|cursor|toggle|layers?|minimi[sz]e|maximi[sz]e)\b', re.I)

# Place kinds (schema.PLACES): words that put the story there (it stays until another place is named), and
# words for things found there, which bring that place's set pieces to their own beat only.
PLACE_CUES = (
    ('living_room', r'living\s*room|lounge|downstairs', r'couch|sofa|armchair|\btv\b|television|fireplace|remote'),
    ('bedroom', r'bedroom|upstairs', r'\bbed\b|pillow|blanket|bunk'),
    ('kitchen', r'kitchen', r'stove|oven|fridge|refrigerator|\bsink\b|cooking|baking'),
    ('dining_room', r'dining\s*room', r'dinner\s+table|breakfast|supper'),
    ('office', r'office|\bstudy\b', r'\bdesk\b|computer|laptop|typing'),
    ('classroom', r'classroom|school', r'teacher|lesson|homework|exam'),
    ('home_exterior', r'\bhouse\b|front\s+door|porch|doorstep|driveway|front\s+yard', r'\bhome\b'),
    ('street', r'street|\broad\b|sidewalk|pavement|crosswalk|\balley', r'traffic'),
    ('town', r'\btown\b|village|neighbou?rhood|\bcity\b|downtown', None),
    ('shop', r'\bshop\b|\bstore\b|supermarket|market|bakery', r'grocer\w*|checkout'),
    ('cafe', r'\bcaf[eé]\b|restaurant|\bdiner\b', r'\bfries\b|burgers?|milkshakes?|waiter|waitress'),
    ('park', r'\bpark\b|playground', r'bench|\bswings?\b'),
    ('garden', r'garden|backyard|\byard\b|lawn', None),
    ('bus', r'\bbus\b|\btrain\b|subway|\btram\b|station|platform', None),
    ('car', r'\bcar\b|\btaxi\b|highway', r'\bdr[oi]ve\b|driving'),
    ('hospital', r'hospital|clinic', r'doctor|nurse'),
    ('library', r'library', r'bookshel\w*|librarian'),
    ('forest', r'forest|\bwoods\b|jungle', None),
    ('beach', r'beach|seaside|\bshore\b', r'\bsand\b|\bwaves\b'),
    ('mountain', r'mountain|\bhills?\b|cliff|summit', None),
    ('river', r'river|stream|\blake\b|\bpond\b', None),
    ('farm', r'\bfarm\b|\bbarn\b|\bfields?\b', r'tractor'),
    ('snow', None, r'\bsnow\w*|\bice\b|winter'),
    ('night_sky', None, r'\bstars\b|\bmoon\b|night\s+sky'),
    ('stage', r'\bstage\b|theat(?:er|re)|concert|auditorium', r'audience'),
)
# A place named by its kind ("Kestrel Falls", "Port Calder", "Ames Hardware", "grew up in Tulsa"): case-sensitive.
NAMED_PLACES = (
    ('town', re.compile(r"\b[A-Z][a-z]+\s+(?:Falls|Springs|Creek|Valley|Heights|Hills?|Harbou?r|Bay)\b|"
                        r"\bPort\s+[A-Z][a-z]+|\b(?:grew\s+up|born|lived|moved)\s+(?:in|to)\s+[A-Z][a-z]+")),
    ('street', re.compile(r"\b[A-Z][a-z]+\s+(?:Street|Avenue|Road|Lane|Boulevard)\b")),
    ('shop', re.compile(r"\b[A-Z][a-z']+\s+(?:Hardware|Market|Grocery|Bakery|Books|Store|Shop|Pharmacy)\b")),
    ('cafe', re.compile(r"\b[A-Z][a-z']+\s+(?:Diner|Cafe|Café|Grill|Restaurant|Pizza)\b")),
)
# An activity, trade or occasion brings its scene and gear to its own beat (fisherman: a lake, a boat, a fishing pole).
ORDINAL = r'(?:\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\w+teenth|\w+tieth)'
ACTIVITIES = (
    (re.compile(r'\bfisherm[ae]n\b|\bfishing\b|\banglers?\b', re.I), 'lake', 'fl_fishing_pole fl_canoe fl_fish lake'),
    (re.compile(r'\bhardware\b', re.I), 'shop', 'fl_hammer fl_wrench'),
    (re.compile(r'\bbak(?:er|ery|ing)\b', re.I), 'shop', 'fl_bread fl_birthday_cake'),
    (re.compile(r'\bfarmer\b|\bfarming\b', re.I), 'farm', 'fl_tractor'),
    (re.compile(r'\bbirthday\b|\bparty\b|\bturns\s+(?:\d+|\w+ty)\b', re.I), None, 'fl_birthday_cake fl_balloon fl_wrapped_gift'),
    (re.compile(r'\banniversary\b|\bwedding\b|\b' + ORDINAL + r'\b.{0,40}\byears\b', re.I), None, 'fl_ring fl_red_heart'),
)
FROM = re.compile(r"\bfrom\s+(?:the\s+|a\s+|an\s+|\w+(?:'s)?\s+)?$", re.I)   # "from the kitchen": not here
PLACE_RE = [(place, est and re.compile(est, re.I), inc and re.compile(inc, re.I)) for place, est, inc in PLACE_CUES]
KITS = {
    'living_room': 'couch television armchair lamp window table clock houseplant',
    'bedroom': 'bed desk lamp window chair book',
    'kitchen': 'refrigerator stove oven table chair cup teapot',
    'dining_room': 'table chair plate cup',
    'office': 'desk lamp chair computer book',
    'classroom': 'chalkboard desk book backpack school',
    'home_exterior': 'house door window tree',
    'street': 'street houses road car tree',
    'town': 'houses house city school shop tree',
    'shop': 'shop shopping cart bag',
    'cafe': 'coffee table chair plate',
    'park': 'tree bench flower',
    'garden': 'flower tree fence house',
    'bus': 'bus window seat',
    'car': 'car road',
    'hospital': 'hospital bed doctor',
    'library': 'book library desk',
    'forest': 'forest tree mushroom',
    'beach': 'beach wave sun',
    'mountain': 'mountain tree',
    'river': 'river tree rock',
    'lake': 'lake boat tree',
    'farm': 'barn tractor field',
    'snow': 'snowman snow tree',
    'night_sky': 'moon star',
    'stage': 'stage microphone',
}
# People the text mentions without a name -> (library age, sex).
PEOPLE = (
    (r'grand(?:father|pa|dad)|old\s+man|\belderly\s+man', 'elder', 'male'),
    (r'grand(?:mother|ma|mum|mom)|granny|nana|old\s+woman|\belderly\s+woman', 'elder', 'female'),
    (r'granddaughter|\bgirls?\b|\bdaughter\b|little\s+sister', 'child', 'female'),
    (r'grandson|\bboys?\b|\bson\b|little\s+brother', 'child', 'male'),
    (r'\bchild(?:ren)?\b|\bkids?\b|grand(?:kid|child)\w*|\bbab(?:y|ies)\b|toddler', 'child', None),
    (r'\bmother\b|\bmom\b|\bmum\b|\bwom[ae]n\b|\blady\b|\baunt\b|\bwife\b|\bsister\b', 'adult', 'female'),
    (r'\bfather\b|\bdad\b|\bm[ae]n\b|\buncle\b|\bhusband\b|\bbrother\b', 'adult', 'male'),
    (r'stranger|neighbou?r|\bpeople\b|\bcrowd\b|\bpersons?\b|\bfriends?\b|\bteen\w*|passer', 'adult', None),
)
PEOPLE_RE = [(re.compile(cue, re.I), age, sex) for cue, age, sex in PEOPLE]
POSE_CUES = (
    ('sleep', r'slept|sleep\w*|asleep|dozing|dozed|napp\w*'),
    ('sit', r'\bsat\b|\bsits?\b|sitting|seated|sprawl\w*'),
    ('lie', r'\blay\b|lying|\blies\b|lain'),
    ('run', r'\bran\b|\bruns?\b|running|rushed|raced|dashed'),
    ('walk', r'walk\w*|stroll\w*|wander\w*'),
    ('carry', r'carr(?:y|ies|ied|ying)|holding|\bheld\b'),
    ('wave', r'wav(?:e|es|ed|ing)\b'),
    ('shout', r'shout\w*|yell\w*|scream\w*'),
    ('look_up', r'looked\s+up|looking\s+up'),
    ('scared', r'afraid|scared|frighten\w*|trembl\w*'),
)
POSE_RE = [(pose, re.compile(r'\b(?:' + cue + r')', re.I)) for pose, cue in POSE_CUES]
FACES = {'Smileys & Emotion', 'emotions', 'Mood'}       # emoji moods: at most two a beat, never by meaning
SET_WEIGHT = {'bespoke': 1.08, 'fluent': .8}


def _key(word: str) -> str:
    return ' '.join(singular(w) for w in re.findall(r"[a-z0-9']+", word.lower()))


def _fits(word: str, entry: dict) -> float:
    """How well a keyword names what the drawing shows: its description ends with the word ("desk lamp" for
    lamp; each part of "couch and lamp"), uses it to describe something else ("orange heart" for orange), or
    never says it (a loose tag)."""
    words = word.split()
    parts = [[singular(w) for w in re.findall(r'[a-z]+', part)]
             for part in re.split(r'\b(?:and|with|on|in|of)\b|[,(:]', entry.get('desc', '').lower())]
    parts = [part for part in parts if part]
    if not parts:
        return 0.
    if any(part[-len(words):] == words for part in parts):
        return .3
    return -.3 if any(' '.join(words) in ' '.join(part) for part in parts) else -.1


@lru_cache(maxsize=4)
def _library(lang: str):
    """(entries, keyword index) for one language: every keyword of every picture, scored by how well it names it."""
    entries = {i: e for i, e in catalog().items()
               if e.get('search', True) and e.get('set') != 'creatures' and e.get('category') != 'narrator'
               and not (imported(e) and (e.get('category') in UI_CATEGORIES or UI_WORDS.search(e.get('desc', ''))))}
    index: dict[str, list[tuple[str, float]]] = {}
    field = 'en' if lang == 'es' else lang
    for did, e in entries.items():
        for rank, word in enumerate(e.get(field) or []):
            key = _key(word) if field == 'en' else word.strip()
            if key:
                weight = SET_WEIGHT.get(e['set'], .6 if imported(e) else .76) - .03 * min(rank, 8)
                index.setdefault(key, []).append((did, weight + (_fits(key, e) if field == 'en' else 0)))
    for key in index:
        index[key].sort(key=lambda pair: -pair[1])
    return entries, index


# ------------------------------------------------------------------ senses
NUMBER = (r"\d[\d,.]*|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
          r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
          r"thousand|million|billion|dozen|several|few")
# Spoken arithmetic ("3 times 5", "a plus b", "equals"): two such beats make a video a math lesson.
MATH = re.compile(rf"\b(?:{NUMBER}|[a-z])\s+(?:plus|minus|times|divided\s+by|multiplied\s+by)\s+(?:{NUMBER}|[a-z])\b|"
                  r"\bequals?\b|\bis\s+equal\s+to\b", re.I)
COUNTED = re.compile(rf"\b(?:{NUMBER})\s+(?:[a-z]+\s+)?$", re.I)       # "five dots", "3 red apples"
GROUPING = set('row column group set pile time way step unit kind type part pair dozen percent point place '
               'number'.split())
# A command: the clause's first word with its object right after it ("Check your toilet", "Jump three").
CLAUSE_START = re.compile(r'(?:^|[.!?;:(\[\n"“]|\b(?:then|and|now|first|next|please|just|so|or))\s*$', re.I)
OBJECT_NEXT = re.compile(rf"\s+(?:the|a|an|your|my|his|her|its|our|their|this|that|these|those|it|them|him|me|us|"
                         rf"some|all|every|each|{NUMBER})\b", re.I)
# A character's own body part is drawn on the character ("his heavy paw", "Pendo's heart").
BODY = set('paw mane eye nose tooth teeth heart belly head hand foot feet leg arm ear tail face mouth lip hair fur '
           'claw wing shoulder rib skin beak back neck finger toe knee chest tongue whisker horn hoof'.split())
POSSESSIVE = re.compile(r"\b(?:his|her|its|their|my|your|our|\w+['’]s)\s+(?:[a-z-]+\s+){0,2}$", re.I)
# Titles are roles, never things: an animal king wears no crown.
TITLES = set('king queen prince princess emperor empress chief lord duke duchess sultan monarch ruler majesty '
             'highness pharaoh tsar czar'.split())
KIN = re.compile(r'\b(?:mother|mom|mum|mama|father|dad|papa|daughter|son|sister|brother|aunt|uncle|wife|husband|'
                 r'grand\w*|nana|granny|bab(?:y|ies)|child(?:ren)?|kids?)\b', re.I)
SPECIFIC = .03      # a kind of the thing ("stop sign" for "sign"): the context must lean to it over the bare word
LOOSE = 0.          # a tag for something else ("crown" for "king"): the context must lean to it at least as much
NAME_CUT = re.compile(r'\b(?:with|and|on|in|of|for|from|at|to|or|under|over|by|showing|holding)\b|[,(:;.]')


@lru_cache(maxsize=None)
def _drawing(did: str) -> tuple[tuple[str, ...], str]:
    """What the drawing is called (its description up to the first 'with', 'of', comma...) and that name's head word:
    a line icon's first ("leaf maple", "keyboard show"), else the last that is also a search word ("party popper
    bursting" is a popper), else the last."""
    entry = catalog().get(did) or {}
    name = NAME_CUT.split(entry.get('desc', '').lower())[0]
    words = tuple(singular(w) for w in re.findall(r'[a-z]+', name) if w not in ('a', 'an', 'the'))
    if not words:
        return (), ''
    if entry.get('set') == 'tabler':
        return words, words[0]
    tags = {w for tag in entry.get('en') or [] for w in _key(tag).split()}
    return words, next((w for w in reversed(words) if w in tags), words[-1])


def _animals(texts) -> list[str]:
    """The names of the story's animal characters ("Pendo", "Kojo"), as the offline director casts them."""
    from .semantics import core_name, detect_cast
    try:
        cast = detect_cast([{'id': f'b{i:03d}', 'spoken': t} for i, t in enumerate(texts)])
    except Exception:  # noqa: BLE001 - a reading this cannot make leaves everyone a person
        return []
    return [core_name(c['name']) for c in cast if c.get('kind') != 'human' and core_name(c['name'])]


class Sense:
    """Which English words name which pictures, in the sense their text uses them (other languages: every word)."""

    def __init__(self, lang: str, entries: dict, index: dict, texts=()):
        self.lang, self.entries, self.index = lang, entries, index
        texts = [t for t in texts if t]
        self.math = lang == 'en' and sum(bool(MATH.search(t)) for t in texts) >= 2
        # An animal's title ("King Kojo" is a lion) names no thing anywhere in the story.
        self.animals = _animals(texts) if lang == 'en' and texts else []
        names = '|'.join(re.escape(n) for n in self.animals)
        self.titles = {t for t in TITLES if names and any(re.search(rf'\b{t}\s+(?:{names})\b', x, re.I)
                                                            for x in texts)}
        self._vectors: dict = {}
        self._spans: dict = {}
        self._rows = None

    # ------------------------------------------------------------ words
    def spans(self, text: str) -> list[tuple[str, int, int]]:
        """(key, start, end) of every one- and two-word phrase that may name a picture here."""
        if text not in self._spans:
            names = proper_names(text) if self.lang == 'en' else []
            self._spans[text] = [(key, a, b) for key, a, b, last in _phrases(text)
                                 if self.lang != 'en' or not self._blocked(text, a, b, key, last, names)]
        return self._spans[text]

    def _blocked(self, text, a, b, key, last, names) -> bool:
        before, after = text[:a], text[b:]
        head = key.split()[-1]
        return bool(in_name(names, a, b, last) or                                 # "Kestrel Falls", "King Kojo"
                    (self.math and (head in GROUPING or not COUNTED.search(before))) or   # "jump 3", "the order"
                    (' ' not in key and CLAUSE_START.search(before) and OBJECT_NEXT.match(after)) or  # "Check your"
                    (head in BODY and POSSESSIVE.search(before)) or               # "his heavy paw"
                    head in self.titles)                                          # the lion king

    def about_animal(self, text: str, at: int) -> bool:
        """Does the sentence around text[at] name an animal character or an animal?"""
        from .semantics import SPECIES_RE, YOUNG_RE
        start, end = _sentence(text, at)
        sentence = text[start:end]
        return bool(SPECIES_RE.search(sentence) or YOUNG_RE.search(sentence) or
                    any(re.search(rf'\b{re.escape(n)}\b', sentence, re.I) for n in self.animals))

    # ------------------------------------------------------------ pictures
    def fits(self, did: str, key: str, text: str, a: int, b: int) -> bool:
        """Does the word at text[a:b] (``key``, singular) name this picture in the sense its sentence uses it?"""
        if self.lang != 'en' or _staged(did, text, a, b):
            return True                                   # other languages; the curated story tables
        words, head = _drawing(did)
        said = tuple(ALIASES.get(key, key).split())
        if not words or words == said:
            return True                                   # its very name: "kangaroo", "lamp", "television"
        start, end = _sentence(text, a)
        sentence = text[start:end]
        near = {singular(w) for w in re.findall(r'[a-z]+', sentence.lower())}
        if said[-1] == head:
            # A kind of the thing ("stop sign", "red envelope", "IV drip") for the bare word: only when the sentence
            # says the kind, calls it by another name of its own, or leans to it.
            kinds = [w for w in words if w != head and w not in said and w in self._tags(did)]
            if not kinds or any(w in near for w in kinds) or self._called(did, sentence, key):
                return True
            return self.contrast(did, sentence, a - start, b - start) >= SPECIFIC
        if set(said) <= set(words):
            return head in near                           # "paw prints", "field hockey": the word only qualifies it
        return self.contrast(did, sentence, a - start, b - start) >= LOOSE

    def judge(self, did: str, text: str) -> bool | None:
        """None when no word of the text names the picture; else whether one names it in its sense here."""
        def names(key, a, b):
            return did in {d for d, _ in self.index.get(ALIASES.get(key, key), [])} or _staged(did, text, a, b)
        if not any(names(key, a, b) for key, a, b, _ in _phrases(text)):
            return None
        return any(names(key, a, b) and self.fits(did, key, text, a, b) for key, a, b in self.spans(text))

    def allowed(self, did: str, text: str) -> bool:
        """May this beat be offered the picture? Named: only in sense. Unnamed (by meaning): not in a math lesson."""
        verdict = self.judge(did, text)
        return not self.math if verdict is None else verdict

    def _tags(self, did: str) -> set:
        return {w for tag in self.entries.get(did, {}).get('en') or [] for w in _key(tag).split()}

    def _called(self, did: str, sentence: str, key: str) -> bool:
        """Does the sentence call the picture by a name of its own that at most two others share ("IV", "hóngbāo")?"""
        said = ' ' + _key(sentence) + ' '
        for tag in self.entries.get(did, {}).get('en') or []:
            tag = _key(tag)
            if tag and tag != key and key not in tag.split() and tag not in STOP and \
                    len(self.index.get(tag, [])) <= 3 and f' {tag} ' in said:
                return True
        return False

    def contrast(self, did: str, sentence: str, a: int, b: int) -> float:
        """How much more the sentence around the word (the word left out) is like the drawing than like the bare
        word: above 0 it leans to this sense of the word, below 0 to another."""
        hidden = (sentence[:a] + ' ' + sentence[b:]).strip()
        if len(re.findall(r'[A-Za-z]{3,}', hidden)) < 2:
            return -1.                                    # no context to tell the sense by
        ids, vecs = catalog_vectors(self.lang, 'picture')
        if self._rows is None:
            self._rows = {i: k for k, i in enumerate(ids)}
        row = self._rows.get(did)
        if row is None:
            return -1.
        word = sentence[a:b].lower()
        missing = [t for t in dict.fromkeys((hidden, word)) if t not in self._vectors]
        if missing:
            self._vectors.update(zip(missing, _normalize(np.array(list(_model(self.lang).embed(missing)), np.float32))))
        context = self._vectors[hidden]
        return float(context @ vecs[row] - context @ self._vectors[word])


def _phrases(text: str):
    """(key, start, end, last word) of every one- and two-word phrase (no punctuation inside a pair)."""
    words = [(m.group(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z][A-Za-z']*", text)]
    for n in (2, 1):
        for i in range(len(words) - n + 1):
            chunk = words[i:i + n]
            if n == 2 and text[chunk[0][2]:chunk[1][1]].strip():
                continue
            yield ' '.join(singular(w.lower()) for w, _, _ in chunk), chunk[0][1], chunk[-1][2], chunk[-1][0]


def _sentence(text: str, at: int) -> tuple[int, int]:
    from .story import sentences
    return next(((a, b) for a, b in sentences(text) if a <= at < b), (0, len(text)))


def _staged(did: str, text: str, a: int, b: int) -> bool:
    """Do the curated story tables (staging.OBJECTS and PLACES) give this picture to the words at text[a:b]?"""
    from .staging import _tables
    places, objects = _tables()
    return any(did in pics and any(m.start() < b and a < m.end() for m in pattern.finditer(text))
               for pattern, pics, _ in places + objects)


class Offer:
    """Per-beat candidate lists for one language, from the whole library (people presets aside)."""

    def __init__(self, lang: str, matcher=None, texts=()):
        """``texts``: the whole video's beat texts (a math lesson? a story of animals?); ``widen`` sets them."""
        self.lang, self.matcher = lang, matcher
        self.entries, self.index = _library(lang)
        self.sense = Sense(lang, self.entries, self.index, texts)

    # ------------------------------------------------------------ pieces
    def desc(self, did: str) -> str:
        entry = catalog().get(did, {})
        return (entry.get('desc') or (entry.get('en') or [''])[0])[:DESC]

    def word(self, word: str, n: int = 2, fits=None) -> list[tuple[str, float]]:
        """The pictures a word names, best first: up to n doodles, else the best line icon; with ``fits(did)``, only
        those in the sense the text uses the word."""
        owners = self.index.get(ALIASES.get(word, word) if self.lang != 'zh' else word, [])
        if fits is not None:
            owners = [pair for pair in owners if fits(pair[0])]
        doodles = [pair for pair in owners if not imported(self.entries[pair[0]])]
        return doodles[:n] or owners[:1]

    def named(self, text: str) -> list[str]:
        """Every picture the words name, best named first (rare words before words many pictures share)."""
        where: dict = {}                                # English: word -> where the text says it
        if self.lang == 'zh':
            words = [key for key in self.index if len(key) >= 2 and key in text]
        else:
            if self.lang == 'es':
                keys = [(singular(t), -1, -1) for t in es_gloss(text).split()]
                pairs = [(' '.join(k for k, _, _ in keys[i:i + n]), -1, -1)
                         for n in (2, 1) for i in range(len(keys) - n + 1)]
            else:
                pairs = self.sense.spans(text)          # the words that may name a thing here, in their sense
            words = []
            for key, a, b in pairs:
                if ' ' not in key and ((key in STOP or len(key) < 3) and key not in ALIASES
                                       or any(cue.search(key) for cue, _, _ in PEOPLE_RE)):
                    continue                            # people come as presets of their age, below
                if ALIASES.get(key, key) in self.index:
                    where.setdefault(key, []).append((a, b))
                    if key not in words:
                        words.append(key)
        scored = {}
        for word in words:
            common = len(self.index[ALIASES.get(word, word)]) > 40
            fits = None if self.lang != 'en' else (
                lambda did, word=word: any(self.sense.fits(did, word, text, a, b) for a, b in where[word]))
            for did, score in self.word(word, fits=fits):
                score += .15 * (len(word.split()) - 1) - (.2 if common else 0)
                scored[did] = max(scored.get(did, -9), score)
        return sorted(scored, key=lambda did: -scored[did])

    def places(self, text: str) -> tuple[list[str], list[str]]:
        """(places the text moves the story to, places whose things the text mentions)."""
        if self.lang != 'en':
            return [], []
        moved, things = [], []
        for place, est, inc in PLACE_RE:
            hits = [m for m in est.finditer(text)] if est else []
            if any(not FROM.search(text[:m.start()]) for m in hits):
                moved.append(place)
            elif hits or (inc and inc.search(text)):
                things.append(place)
        moved += [place for place, cue in NAMED_PLACES if cue.search(text) and place not in moved]
        things += [place for cue, place, _ in ACTIVITIES if place and cue.search(text) and place not in moved + things]
        return moved, things

    def gear(self, text: str) -> list[str]:
        """The things an activity or occasion in the text needs on screen (a fisherman's boat, a party's cake)."""
        if self.lang != 'en':
            return []
        out = []
        for cue, _, ids in ACTIVITIES:
            if cue.search(text):
                out += [did for did in ids.split() if did in self.entries]
        return list(dict.fromkeys(out))

    def kit(self, place: str) -> list[str]:
        """The set pieces of a place: per word, the best drawing that shows that very thing."""
        out = []
        for word in KITS.get(place, '').split():
            key = _key(word)
            out += [did for did, _ in self.word(key, 3) if _fits(key, self.entries[did]) > -.2][:1]
        return out

    def people(self, text: str) -> list[str]:
        if self.lang != 'en':
            return []
        pose = next((p for p, cue in POSE_RE if cue.search(text)), None)
        out = []
        for cue, age, sex in PEOPLE_RE:
            # In a sentence about an animal ("Pendo loved his mother"), a kin word is an animal too: no people.
            if any(not (KIN.fullmatch(m.group()) and self.sense.about_animal(text, m.start())) for m in cue.finditer(text)):
                for want in ([pose] if pose else []) + ['stand']:
                    did = creatures.best_preset('human', age=age, sex=sex, pose=want)
                    if did:
                        out.append(did)
        return out

    def meaning(self, texts: list[str], sentences=None) -> list[list[str]]:
        """Per text, the closest drawings by meaning to it and to its first sentences (one batch of embeddings),
        without faces: a story shows its people, not emoji moods."""
        if self.matcher is None or not texts or self.sense.math:
            return [[] for _ in texts]             # a math lesson shows its numbers on a board, not look-alikes
        if self.lang == 'en':
            # Match the sense, not the name: "grew up in Kestrel Falls" means a town; an animal king is no crown.
            titles = re.compile(r'\b(?:' + '|'.join(self.sense.titles) + r')s?\b', re.I) if self.sense.titles else None
            texts = [titles.sub(' ', unname(t)) if titles else unname(t) for t in texts]
            if sentences:
                split = sentences
                sentences = lambda text: [titles.sub(' ', s) if titles else s for s in split(text)]  # noqa: E731
        queries = []
        for n, text in enumerate(texts):
            parts = list(dict.fromkeys(sentences(text) if sentences else []))
            queries += [(n, text, 4)] + [(n, part, 2) for part in parts[:6] if len(parts) > 1]
        words = [es_gloss(q) if self.lang == 'es' else q for _, q, _ in queries]
        unique = list(dict.fromkeys(w for w in words if w))       # repeated sentences are embedded once
        ids, vecs = self.matcher._catalog_vectors()
        rows = dict(zip(unique, _normalize(np.array(list(_model(self.lang).embed(unique)), np.float32)) @ vecs.T
                        - PACK_PENALTY * self.matcher._packs)) if unique else {}
        found = [rows.get(w) for w in words]
        out = [[] for _ in texts]
        for (n, _, k), sims, word in zip(queries, found, words):
            if word:
                out[n] += [ids[i] for i in np.argsort(-sims)[:k] if self.entries.get(ids[i], {}).get('category') not in FACES]
        return out

    # ------------------------------------------------------------ whole video
    def widen(self, beats: list[dict], sentences=None) -> None:
        """Extend each payload beat's ``candidates`` ({id, desc}) in place. ``beats`` are payload beats in order
        (beat_id, section_id, spoken or text); ``sentences(text)`` splits a beat for meaning matches."""
        self.sense = Sense(self.lang, self.entries, self.index, [b.get('spoken') or b['text'] for b in beats])
        named = {b['beat_id']: self.named(b.get('spoken') or b['text']) for b in beats}
        meant = dict(zip([b['beat_id'] for b in beats], self.meaning([b.get('spoken') or b['text'] for b in beats],
                                                                    sentences)))
        counts = Counter(did for ids in named.values() for did in ids[:QUOTA['named']])
        motifs = [did for did, n in counts.most_common() if n >= 2]
        here, section = [], None
        for b in beats:
            text = b.get('spoken') or b['text']
            if b.get('section_id') != section:
                here, section = [], b.get('section_id')
            moved, things = self.places(text)
            places = moved + things + ([] if moved else here)
            if moved:
                here = moved                             # the story moved; until it moves again, it stays
            # The picture director's own picks, the story's motifs and the look-alikes by meaning keep only the
            # pictures a word of this beat names in its sense (or that no word of it names, outside a math lesson).
            sensed = (lambda ids: [did for did in ids if self.sense.allowed(did, text)]) if self.lang == 'en' else \
                (lambda ids: ids)
            groups = (
                (sensed([c['id'] for c in b['candidates']]), QUOTA['rules']),
                (named[b['beat_id']], QUOTA['named']),
                (self.gear(text) + [did for place in dict.fromkeys(places) for did in self.kit(place)],
                 QUOTA['place']),
                (self.people(text), QUOTA['people']),
                (sensed([did for did in motifs if did not in named[b['beat_id']]]), QUOTA['motif']),
                (sensed(meant[b['beat_id']]), CAP),
            )
            chosen, faces = [], 0
            for ids, quota in groups:
                added = 0
                for did in ids:
                    if len(chosen) >= CAP or added >= quota:
                        break
                    face = catalog().get(did, {}).get('category') in FACES
                    if did not in chosen and did in catalog() and not (face and faces >= 2):
                        chosen.append(did)
                        added += 1
                        faces += face
            old = {c['id']: c for c in b['candidates']}
            b['candidates'] = [old.get(did) or {'id': did, 'desc': self.desc(did)} for did in chosen]
            if self.lang == 'en':
                hints = board_hints(b['text'])
                if hints:
                    b['board_hints'] = hints


def board_hints(text: str) -> list[str]:
    """What a board can write for this beat, as the planner should copy it: each term the beat names and each piece
    of spoken math with how KinoDraw writes it ('3 times 5 is 15 -> 3 × 5 = 15'). At most 6, each short."""
    from ...engine import process_diagrams as pd
    out = [f'term: {term}' for term in pd.terms(text)]
    out += [f'math: {text[a:b]} -> {pd.typeset(text[a:b])}' for a, b in pd.math_runs(text)]
    return [hint[:100] for hint in out[:6]]


def fit(payload: dict, limit: int = REQUEST_LIMIT) -> None:
    """Drop the last-ranked candidates, longest lists first, until the Cloud request body fits ``limit``."""
    def size():
        return len(json.dumps({'video_id': 'x' * 36, 'storyboard': payload}))
    over = size() - limit
    while over > 0:
        longest = max(payload['beats'], key=lambda b: len(b['candidates']))
        if not longest['candidates']:
            return
        dropped = longest['candidates'].pop()
        over -= len(json.dumps(dropped)) + 2
        if over <= 0:
            over = size() - limit

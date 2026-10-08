"""A plan's shots on story pages (director/v3/schema.py ``scene.shots``).

When a scene carries shots, each one becomes a page of the storybook from its own staging instead of the text
reading: it starts at its ``starts_at`` words (the beat's character times), shows its cast at the age and in the
pose it gives, in its place's set with its props, framed as its type says (wide: the whole set, medium: knees up,
close: head and shoulders, two_shot: two people facing each other, insert: the object or arrangement it looks at,
first_person: the page, list, letter, map or phone a character reads, filling the frame with its words). The
camera is locked within a shot; only the framing changes from shot to shot. Speech bubbles come from the speaker
the plan names for each quoted line when that is plausible (the text's own tags, vocatives and turn order win
otherwise); a speaker heard but not seen has no figure and their bubble points in from the frame's edge.
"""
from __future__ import annotations

import copy
import math
import re
from functools import lru_cache
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from .. import library
from . import acting, ink, sets
from ..director.v3 import arc
from ..director.v3.semantics import name_key
from ..director.v3.story import SPEAKER_LABEL, places_in, sentences

# The plan's age bands and poses (schema AGES, POSES) as the storybook draws them.
AGE_BAND = {'baby': 'baby', 'child': 'child', 'young': 'child', 'teen': 'teen', 'adult': 'adult', 'old': 'elder'}
POSE = {'stand': 'stand', 'walk': 'walk', 'run': 'run', 'sit': 'sit', 'lie': 'lie', 'sleep': 'sleep',
        'look': 'look', 'look_up': 'look_up', 'read': 'look', 'write': 'sit', 'hold': 'stand', 'carry': 'stand',
        'talk': 'stand', 'shout': 'shout', 'wave': 'wave', 'point': 'stand', 'reach': 'stand', 'hug': 'stand',
        'laugh': 'happy', 'cry': 'scared', 'scared': 'scared', 'kneel': 'sit', 'eat': 'stand', 'drink': 'stand'}
# The plan's place vocabulary (schema PLACES) on the storybook's sets (engine.sets.SETS). A place the table does not
# know is read like story text (places_in), else it keeps the last place, else a plain room or the outdoors.
PLACE_SETS = {'home_exterior': 'house', 'dining_room': 'dining', 'hallway': 'room', 'village': 'town',
              'station': 'street', 'airport': 'city', 'stage': 'room', 'field': 'countryside',
              'mountain': 'countryside', 'river': 'countryside', 'lake': 'countryside', 'sea': 'beach',
              'desert': 'outdoors', 'snow': 'countryside', 'cave': 'outdoors', 'castle': 'town',
              'underwater': 'outdoors'}
# A plan's library picture of a piece of furniture is drawn as the storybook's own piece of that kind, which people
# can sit or lie on and things can stand on.
KIND_ART = {'armchair': 'set_armchair', 'couch': 'fl_couch_and_lamp', 'chair': 'fl_chair', 'desk': 'set_desk',
            'table': 'set_table', 'lamp': 'set_desk_lamp', 'bed': 'fl_bed', 'tv': 'fl_television'}
INDOOR_WORD = re.compile(r'room|hall|house|home|flat|apartment|inside|indoor|office|studio|attic|basement|garage|'
                         r'kitchen|corridor|lobby|theat', re.I)
# A medium or two-shot shows people from the knees up; a close-up their head and shoulders.
KNEES = .28
MEDIUM_FILL, CLOSE_FILL, INSERT_FILL = (.8, .62), .72, (.58, .5)
CLOSE_WIDTH, CLOSE_SPEAKING = .84, .55             # a close-up's head stays inside the sides; a speaker's bubble fits
MAX_ZOOM = {'medium': 2.4, 'two_shot': 2.4, 'close': 4.2, 'insert': 5.5}
EYE_LINE = .44                     # where a framed subject's middle sits on screen, clear of the caption band
WIDE_SCALE = .86                   # a wide shot shows the whole set, its people a little smaller
MIN_SHOT = .8                      # seconds: a shorter shot shares the page before it
# A story page whose cast only fits the page drawn smaller than this (storybook._fit) shows, sentence by sentence,
# only the cast each sentence is about, each at a readable size.
READABLE = .7
# Poses that are not a body position: someone sitting or lying who talks, looks or holds something stays put.
IN_PLACE = {'talk', 'look', 'point', 'hold', 'reach', 'laugh', 'read', 'eat', 'drink', 'wave', 'shout', 'cry',
            'scared', 'write', 'stand'}
# Poses of someone the plan keeps off screen in an insert whose hands still work the thing (a recipe's cook holding,
# pouring, stirring): outside a story the insert shows their hand on it.
HAND_POSES = {'hold', 'carry', 'reach', 'point', 'write', 'eat', 'drink'}
# Things a character can read: a first_person shot of one fills the frame with its words.
WRITABLE = re.compile(r'page|paper|letter|note(?!book_computer)|list|scroll|clipboard|memo|diary|journal|notebook|'
                      r'card|newspaper|sign|poster|receipt|ticket|map|phone|smartphone|mobile|tablet|message|'
                      r'postcard|document|menu', re.I)
PHONE = re.compile(r'phone|smartphone|mobile|tablet|cell', re.I)
# Words that put someone down on the ground; without them nobody lies on a road (a newborn in the street reads as an
# accident).
LYING = re.compile(r'\b(?:lay|lays|lie|lies|lying|laid|sleep\w*|slept|asleep|nap\w*|doz\w*|fell|fallen|falls?|'
                   r'collaps\w*|sprawl\w*|stretch\w*\s+out|faint\w*|tripp?\w*|knocked\s+(?:down|over)|flat)\b', re.I)
# Words that say it is daytime: a shot the plan calls "day" inside a night scene without them is that night.
DAYTIME = re.compile(r'\b(?:day(?:time|light|break)?|morning|noon|midday|afternoon|sun\w*|dawn|breakfast|lunch)\b',
                     re.I)
NIGHT_SKIES = ('night_stars', 'shooting_star')
# The scene's atmosphere in its sky (as on a page read from the text, storybook.Storybook._shot): a night one hangs a
# moon, a dawn one a sun, rain its cloud. A night page outdoors also shows a few stars.
MOON_SKIES = ('night_stars', 'shooting_star', 'fog_with_shooting_star')
SUN_SKIES = ('dawn', 'rays')
STARS = ((.42, .1, .04), (.6, .2, .032), (.3, .2, .032), (.7, .08, .028))
FOGS = ('fog', 'fog_with_shooting_star')
# Sky things the words can take away ("No moon anywhere", "somebody took the moon") or bring back ("there was the
# moon"): what the sky shows follows the last thing the story said about them.
SKY_WORDS = {'moon': r'moon\w*', 'sun': r'sun(?:light|shine|rise|set)?(?![\w-])', 'star': r'stars?(?![\w-])|starlight'}
TAKEN = re.compile(r"\b(?:took|take|takes|taking|taken|stole|steal|steals|stealing|stolen|hid|hide|hides|hidden|"
                   r"swallowed|swallows|ate|eaten|covered|covers|covering|blocked|blocks|blocking)\s+(?:away\s+)?"
                   r"(?:the|a|an|our|my|his|her|their|that|its)?\s*$", re.I)
BEHIND = re.compile(r"\s+(?:had\s+|has\s+|is\s+|was\s+)?(?:\w+\s+)?(?:went|goes|go|gone|slipped|slips|hid|hides|"
                    r"hiding|disappeared|disappears|vanished)\s+(?:away|behind)\b", re.I)
# A grassland the plan's places have no name for: a nature place the plan picks (a jungle, a forest) is drawn as the
# savanna when the story's words name a grassland and never the plan's own kind of place.
GRASSLAND = re.compile(r'\b(?:savann?ah?s?|grasslands?|plains|prairies?|velds?|steppes?)\b', re.I)
NATURE_WORDS = {'jungle': r'jungles?|rain\s*forests?', 'forest': r'forests?|woods|woodlands?',
                'countryside': r'countryside|meadows?|fields?|hills?|valleys?|mountains?|farmland',
                'outdoors': r'outdoors'}
SEAT_WORDS = {'couch': r'couch|sofa|settee', 'sofa': r'couch|sofa|settee', 'settee': r'couch|sofa|settee',
              'seat': r'seat|chair|couch|sofa|bench'}
# "asleep in front of the TV", "watching television": whoever the words put there keeps the TV beside them and in
# every framing of them in that place.
BY_TV = re.compile(r'\b(?:in\s+front\s+of|before|facing|watching|watches|watched)\s+(?:the\s+|a\s+|an\s+|his\s+|'
                   r'her\s+|their\s+|our\s+|my\s+)?(?:tv|television|telly)\b', re.I)
TV_GAP = .03
SIGNAL = re.compile(r'antenna|signal|reception|wifi|bars', re.I)
MAP = re.compile(r'\bmap\b|map_|_map|atlas', re.I)
NO_SIGNAL = re.compile(r'\bno\s+(?:bars|signal|service|reception|connection|network)\b|out\s+of\s+range|'
                       r'dead\s+zone', re.I)
SCREEN = re.compile(r'television|\btv\b|_tv|monitor|screen|laptop|computer|tablet|phone', re.I)
PERSON_PICTURE = {'girl': ('child', 'female'), 'boy': ('child', 'male'), 'child': ('child', None),
                  'baby': ('baby', None), 'woman': ('adult', 'female'), 'man': ('adult', 'male'),
                  'person': (None, None), 'old_woman': ('elder', 'female'), 'old_man': ('elder', 'male')}
GOT_OUT = re.compile(r'\b(?:got|gets|get|getting|climbed|climbs|stepped|steps|jumped|jumps|hopped)\s+out\b|'
                     r'\b(?:walked|walks|ran|runs)\b', re.I)
# A voice from somewhere the camera is not: it is heard, its speaker not drawn.
OFFSCREEN = re.compile(r"\b(?:off[- ]?(?:screen|stage|camera)|O\.S\.|V\.O\.|voice[- ]?over|"
                       r"(?:from|in)\s+(?:the\s+|another\s+|the\s+other\s+|the\s+next\s+)?(?:other\s+room|next\s+room|"
                       r"another\s+room|kitchen|hall(?:way)?|bathroom|bedroom|garage|basement|attic|upstairs|"
                       r"downstairs|outside|yard|garden|porch|doorway|stairs|phone|speaker(?:phone)?)|"
                       r"(?:calls?|called|calling|shouts?|shouted|shouting|yells?|yelled|yelling)\s+from)\b", re.I)
QUOTES = str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"', '—': '-', '–': '-', '…': '.'})
PAPER = (252, 249, 238, 255)
INK = (27, 27, 27, 255)
SKIN = {'light': (246, 214, 186), 'tan': (222, 170, 120), 'brown': (150, 98, 66)}
SLEEVE = (84, 120, 168)


# ------------------------------------------------------------------ words and times
def _norm(text):
    return (text or '').translate(QUOTES).lower()


def find_words(text, words):
    """Character index in ``text`` where ``words`` begin (case, quote marks and spacing do not matter), or None."""
    tokens = re.findall(r"[\w']+", _norm(words))
    hay = _norm(text)
    for n in (len(tokens), min(len(tokens), 4), min(len(tokens), 2)):
        if not n:
            return None
        m = re.search(r"(?<![\w'])" + r"[^\w']+".join(re.escape(t) for t in tokens[:n]) + r"(?![\w'])", hay)
        if m:
            return m.start()
    return None


def place_for(place, previous=None):
    """The storybook set (engine.sets.SETS key) for a plan place, or ``previous`` when it gives none."""
    if not place or place in ('none', 'other', 'unknown'):
        return previous
    if place in sets.SETS:
        return place
    if place in PLACE_SETS:
        return PLACE_SETS[place]
    found = places_in(place.replace('_', ' '))
    if found:
        return found[0]
    return previous or ('room' if INDOOR_WORD.search(place) else 'outdoors')


def _words(doodle):
    entry = library.catalog().get(doodle) or {}
    return f"{doodle.replace('_', ' ')} {entry.get('desc', '')} {entry.get('en', '')}"


def writable(doodle) -> bool:
    return bool(doodle) and not re.search(r'envelope', doodle) and bool(WRITABLE.search(_words(doodle)))


def _kind(doodle):
    """What kind of furniture a picture is (desk, lamp, couch, ...): a plan's picture of a kind the set already has
    is the set's own."""
    words = f"{doodle.replace('_', ' ')} {(library.catalog().get(doodle) or {}).get('desc', '')}".lower()
    if re.search(r'_stand$', doodle):
        return None                                   # a TV's stand is not a TV
    for kind, cue in (('armchair', r'armchair'), ('couch', r'\b(?:couch|sofa|settee)'), ('lamp', r'\blamp'),
                      ('desk', r'\bdesk'), ('table', r'\btable'), ('bed', r'\bbed\b'), ('chair', r'\bchair'),
                      ('tv', r'televis|\btv\b'), ('window', r'\bwindow'), ('fridge', r'fridge|refrigerat'),
                      ('stove', r'stove|cooker|oven'), ('counter', r'counter'), ('shelf', r'shel(?:f|ves)|bookcase'),
                      ('bench', r'\bbench')):
        if re.search(cue, words):
            return kind
    return None


# ------------------------------------------------------------------ the written words a page shows
def passages(book):
    """Written passages the story reads out: the lines after a sentence that ends with a colon (``a list, written
    in a hand he didn't recognize:``), through the following paragraphs written to "you", as (beat id, char
    offset of the colon, lines)."""
    if getattr(book, '_passages', None) is not None:
        return book._passages
    order = [b for b in book.tl.get('beat_order', list(book.by_id)) if b in book.by_id]
    out = []
    for i, bid in enumerate(order):
        text = book.by_id[bid]['text']
        for m in re.finditer(r':\s*(?=$|\n)|:\s+(?=[A-Z“"])', text):
            if SPEAKER_LABEL.match(text) and m.start() < SPEAKER_LABEL.match(text).end():
                continue                                  # "MIA: ..." is a speaker, not a page
            rest = text[m.end():].strip()
            body = [rest] if rest else []
            for nxt in order[i + 1:i + 6]:
                t = book.by_id[nxt]['text']
                if '"' in t or '“' in t or SPEAKER_LABEL.match(t):
                    break
                if body and not re.search(r'\byou(?:r|rs)?\b', t, re.I):
                    break
                body.append(t)
            lines = [s for b in body for a, z in sentences(b) for s in [b[a:z].strip()] if s]
            nouns = WRITABLE.findall(text[:m.start()])
            if lines:
                out.append((bid, m.start(), lines, nouns[-1].lower() if nouns else 'page'))
    book._passages = out
    return out


def writing_for(book, plan_shot, bid, text):
    """The words a first_person page shows: the plan's, else what the shot's own narration quotes, else the
    passage it introduces or the last one read before it."""
    if (plan_shot.get('writing') or '').strip():
        return [plan_shot['writing'].strip()]
    found = passages(book)
    order = book.tl.get('beat_order', list(book.by_id))
    here = order.index(bid) if bid in order else 0
    own = [p for p in found if p[0] == bid and p[1] >= text[0]]
    if own:
        earlier = [line for p in found if order.index(p[0]) < here for line in p[2]]
        full = re.search(r'\b(?:full|filled|both\s+sides|bottom|end\s+of\s+the\s+page)\b', book.by_id[bid]['text'], re.I)
        return (earlier if full else []) + own[0][2]          # "the page was full ... at the very bottom, a new line"
    before = [p for p in found if order.index(p[0]) < here or (p[0] == bid and p[1] < text[0])]
    beat = book.by_id[bid]['text']
    if before and re.search(r'\b(?:' + re.escape(before[-1][3]) + r'|page|paper|sheet|writing|words)', beat, re.I):
        return before[-1][2]                          # 'The list stopped halfway down the page'
    after = [p for p in found if order.index(p[0]) > here]
    if after and order.index(after[0][0]) - here <= 2:
        return after[0][2]
    return []


# ------------------------------------------------------------------ staging
ONES = {w: i for i, w in enumerate('zero one two three four five six seven eight nine'.split())}
TEENS = {w: i + 10 for i, w in enumerate('ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen '
                                          'nineteen'.split())}
TENS = {w: (i + 2) * 10 for i, w in enumerate('twenty thirty forty fifty sixty seventy eighty ninety'.split())}


def year_in(text):
    """A year the text names ("1989", "nineteen eighty-nine", "two thousand and five"), as digits, or None."""
    m = re.search(r'\b(1[5-9]\d\d|20\d\d)\b', text)
    if m:
        return m[1]
    words = re.findall(r'[a-z]+', (text or '').lower().replace('-', ' '))
    for i, word in enumerate(words):
        rest = words[i + 1:i + 4]
        if word in ('nineteen', 'eighteen', 'seventeen', 'sixteen', 'twenty') and rest:
            if rest[0] in TEENS:
                return str(TEENS.get(word, 20) * 100 + TEENS[rest[0]])
            if rest[0] in TENS:
                ones = ONES.get(rest[1], 0) if len(rest) > 1 and rest[1] in ONES else 0
                return str((TEENS.get(word) or TENS[word]) * 100 + TENS[rest[0]] + ones)
            if rest[0] == 'oh' and len(rest) > 1 and rest[1] in ONES:
                return str((TEENS.get(word) or TENS[word]) * 100 + ONES[rest[1]])
        if word == 'two' and rest[:1] == ['thousand']:
            tail = [r for r in rest[1:] if r != 'and']
            return str(2000 + (ONES.get(tail[0], 0) if tail and tail[0] in ONES else TEENS.get(tail[0], 0) if tail else 0))
    return None


def chunks(words, most):
    """(start, end) spans of a quoted line, one per bubble: its sentences, a sentence longer than ``most`` words cut
    at its commas, semicolons and dashes (phrases joined while they fit), a phrase still too long cut by word count.
    Chinese and Japanese lines keep their sentences."""
    out = []
    for a, z in sentences(words):
        if any(ink.is_cjk(ch) for ch in words[a:z]) or len(words[a:z].split()) <= most:
            out.append((a, z))
            continue
        cuts = [a] + [a + m.end() for m in re.finditer(r'[,;:]\s+|\s[-\u2014\u2013]+\s*|\u2014', words[a:z])] + [z]
        pieces = [(x, y) for x, y in zip(cuts, cuts[1:]) if words[x:y].strip()]
        split = []
        for x, y in pieces:
            spans = [m.span() for m in re.finditer(r'\S+', words[x:y])]
            for i in range(0, len(spans), most):
                part = spans[i:i + most]
                split.append((x + part[0][0], x + part[-1][1]))
        joined = []
        for x, y in split:
            if joined and len(words[joined[-1][0]:y].split()) <= most:
                joined[-1] = (joined[-1][0], y)
            else:
                joined.append((x, y))
        out.extend(joined)
    return out


class Shots:
    """Shots for one scene span from its plan shots. ``book`` is the engine.storybook.Storybook."""

    def __init__(self, book):
        self.book = book
        self.place = None
        self.night = False
        self.last = None               # the last shot built (a heard voice keeps the listeners' page)
        self.previous = None           # the last page of the scene before
        self.rests = {}                # cast id -> (place, pose): who sat or lay where in the last shot
        self.seats = {}                # cast id -> (place, support doodle, x): their seat stays theirs
        self.screened = {}             # cast id -> Figure: someone shown on a screen stays on it
        self.extra = {}                # place -> chairs brought in when every seat was full
        self.stamp = None              # the year a home video on a screen is dated
        self.in_car = False            # the cast is in a car: pulled over outside, they are still in it
        self.seen = {}                 # cast id -> the place they were last on the page
        self.readable = None           # the last thing in the scene with words on it (the map she unfolds)
        self.written = {}              # doodle -> the words a page of it last showed: a page keeps its writing
        self.gone = None               # sky things the words last said are not there ('moon', 'sun', 'star')
        self.read = {}                 # beat id -> the Reader's sentences
        self.drawn = {}                # 'sun'/'moon' -> the picture of it the story last showed (its full moon)

    def prepare(self, spec, start, end):
        from .storybook import Shot
        book = self.book
        beats = [b for b in spec['beat_ids'] if b in book.by_id]
        read = {bid: book.reader.read(bid, book.by_id[bid]['spoken'], book.by_id[bid].get('section'))
                for bid in beats}
        self.read.update(read)
        if self.gone is None:
            self.gone = self._missing_from_the_start()
        timers = {bid: self._timer(bid, start) for bid in beats}
        plans = []
        for plan in spec.get('shots') or ():
            bid = plan.get('beat_id')
            if bid not in timers:
                continue
            offset = self._offset(bid, plan.get('starts_at') or '', [o for b, o, _ in plans if b == bid],
                                  read[bid])
            if offset is None:
                continue
            plans.append((bid, offset, plan))
        plans.sort(key=lambda p: (beats.index(p[0]), p[1]))
        voices = self._voices(plans, beats, read, timers)
        plans = [(bid, offset, self._recast(plan, [v for v in voices.values() if v[1] == i]))
                 for i, (bid, offset, plan) in enumerate(plans)]
        shots, owner = [], {}
        for i, (bid, offset, plan) in enumerate(plans):
            begin = timers[bid](offset)
            nxt = next(((b, o) for b, o, _ in plans[i + 1:] if (b, o) != (bid, offset)), None)
            text = self._span_text(bid, offset, nxt)
            # The narration's actions on this page (engine.acting): from its sentences, the plan's as a fallback.
            spoken = [(bid, s) for s in read[bid] if s.start < text[1] and text[0] < s.end]
            acts = [a for a in spec.get('actions') or () if a.get('at_beat') == bid]
            self._sky_words(text[2])
            if shots and begin - shots[-1].start < MIN_SHOT:
                acting.direct(book, shots[-1], spoken, timers[bid], acts, bid, window=text[:2])
                self._roars(shots[-1], spoken, timers[bid], text)
                continue
            shot = self._stage(plan, begin, timers[bid], spec, bid, text)
            for part, window in self._parts(shot, plan, bid, text, spoken) or [(None, text)]:
                if part is not None:
                    begin = timers[bid](window[0])
                    lines = [(bid, s) for s in read[bid] if s.start < window[1] and window[0] < s.end]
                    if shots and begin - shots[-1].start < MIN_SHOT:
                        acting.direct(book, shots[-1], lines, timers[bid], acts, bid, window=window[:2])
                        self._roars(shots[-1], lines, timers[bid], window)
                        continue
                    shot = self._stage(part, begin, timers[bid], spec, bid, window)
                else:
                    lines = spoken
                acting.direct(book, shot, lines, timers[bid], acts, bid, window=window[:2])
                self._roars(shot, lines, timers[bid], window)
                owner[id(shot)] = plan
                shots.append(shot)
        if not shots:
            shots.append(Shot(0., end - start))
        for shot, following in zip(shots, shots[1:]):
            shot.end = following.start
        shots[0].start = 0.
        shots[-1].end = end - start
        self._bubbles(shots, beats, read, timers, owner, voices)
        if not book.story and not book.calm:
            shots = self._vary(shots, sorted(timers[bid](line.start) for bid in beats for line in read[bid]))
        elif book.story:
            shots = self._follow(shots, [(timers[bid](line.start), timers[bid], line) for bid in beats
                                         for line in read[bid]])
        for shot in shots:
            for b in shot.bubbles:
                b.start, b.end = max(b.start, shot.start), min(b.end, shot.end - .05)
            shot.bubbles = [b for b in shot.bubbles if b.end - b.start >= .6]
        self.previous = shots[-1]
        return shots

    # ---------------- editing
    VARY_EVERY = 2                 # sentences one framing holds outside a story before the next sentence cuts

    def _vary(self, shots, starts):
        """Outside a story no picture holds more than VARY_EVERY sentences: on the next sentence it cuts to a
        closer or a wider framing of the same page (the coach's wide kitchen to a medium on him, two inserts of one
        bowl to a wider look at the counter), a cut on a new sentence, never a camera move."""
        out, run, look = [], 0, None
        for shot in shots:
            if shot.page or (not shot.figures and shot.view[2] <= 1.05):
                # A page read fills the frame, and a wide page with nobody on it has nothing to frame closer (a
                # closer look at it is a random zoom that crops its set): neither has another framing.
                out.append(shot)
                run, look = 0, None
                continue
            inside = [t for t in starts if shot.start + .05 < t < shot.end - MIN_SHOT]
            same = self._look(shot) == look
            run = run + 1 if same else 1                  # the sentence this shot opens on
            if same and run > self.VARY_EVERY and out and out[-1].view == shot.view:
                shot.view, run = self._other_view(shot), 1
            look = self._look(shot)
            out.append(shot)
            for t in inside:
                run += 1
                if run <= self.VARY_EVERY:
                    continue
                cut = copy.copy(out[-1])
                cut.start, out[-1].end = t, t
                cut.bubbles = [copy.copy(b) for b in out[-1].bubbles]
                cut.view, run = self._other_view(out[-1]), 1
                out.append(cut)
        return out

    def _look(self, shot):
        """What a page looks like at a glance: its framing, where the camera is and who is in it (a spoon added
        out of frame is the same picture)."""
        return (shot.framing, tuple(round(v, 2) for v in shot.view), tuple((f.key, f.pose) for f in shot.figures),
                bool(shot.page))

    def _other_view(self, shot):
        """A different framing of the same page: a medium on its people from a wide, else a wider look."""
        cx, cy, zoom = shot.view
        if zoom <= 1.05:
            if shot.figures:
                probe = SimpleNamespace(view=shot.view)
                self._look_at(probe, self._union([self._knees_up(f) for f in shot.figures[:2]]), MEDIUM_FILL,
                              MAX_ZOOM['medium'])
                if probe.view[2] > 1.2:
                    return probe.view
            zoom = 1.6
        else:
            zoom = max(1., zoom * .6)
        half = .5 / zoom
        return min(1 - half, max(half, cx)), min(1 - half, max(half, cy)), zoom

    def _follow(self, shots, lines):
        """In a story, a sentence about someone's eyes on a page that holds several sentences gets its own cut of
        that page, which pushes into those eyes (Storybook._eye_camera) and then shows the face; the next sentence
        cuts back to the page's own framing. ``lines``: (span-local start, beat timer, Reader sentence)."""
        lines = sorted(lines, key=lambda l: l[0])
        out = []
        for shot in shots:
            out.append(shot)
            figures = [f for f in shot.figures if not f.crowd]
            if shot.page or shot.screen or shot.hands or shot.eyes is not None or not figures:
                continue
            start, end = shot.start, shot.end
            for t, timer, line in lines:
                current = out[-1]
                eyes = next((f for f in figures if f.key == line.eyes), None) if self.book.pushes(line) else None
                if not start <= t <= end - MIN_SHOT or (eyes is None and current.eyes is None):
                    continue
                if t - current.start < MIN_SHOT:
                    if eyes is not None and current is shot and t - start < MIN_SHOT:
                        shot.eyes, shot.eyes_at = eyes, timer(line.eyes_at)     # the page opens on the eyes
                    continue
                cut = copy.copy(current)
                cut.start, current.end = t, t
                cut.eyes, cut.eyes_at = eyes, (timer(line.eyes_at) if eyes is not None else 0.)
                cut.bubbles = [copy.copy(b) for b in current.bubbles]
                out.append(cut)
        return out

    def _parts(self, shot, plan, bid, text, spoken):
        """A story page whose plan cast is drawn too small to read (READABLE), split at its sentences into pages
        that each show only the cast the sentence is about: who it names, who speaks and whom an act of theirs
        reaches (the hyena a swipe sends flying), at their full size, in the same place, poses and framing type. A
        sentence about nobody keeps the page before it; one about everyone shows the whole cast. [(plan, (start,
        end, words))], or None when the page stays whole."""
        book = self.book
        keys = [f.key for f in shot.figures if not f.crowd]
        if not book.story or getattr(shot, 'scale', 1.) >= READABLE or shot.page or shot.screen or len(keys) < 2 \
                or shot.framing in ('insert', 'first_person', 'close'):
            return None
        groups = []
        for _, line in spoken:
            named = set(line.present) | {line.speaker}
            for _, actor, target, *_ in acting.read(book, line, keys):
                named |= {actor, target}
            who = [k for k in keys if k in named] or (groups[-1][0] if groups else keys)
            if not groups or groups[-1][0] != who:
                groups.append((who, max(line.start, text[0])))
        if len(groups) < 2 and (not groups or groups[0][0] == keys):
            return None
        words = book.by_id[bid]['spoken']
        out = []
        for i, (who, start) in enumerate(groups):
            stop = groups[i + 1][1] if i + 1 < len(groups) else text[1]
            part = plan if who == keys else dict(plan, cast=[c for c in plan.get('cast') or ()
                                                             if self.person(c.get('id')) in who])
            out.append((part, (start, stop, words[start:stop])))
        return out

    # ---------------- sky
    def _missing_from_the_start(self):
        """The sky things the story first speaks of as missing ("Mama, the moon is gone"): they were not there
        before those words either."""
        story = ' '.join(self.book.by_id[b]['spoken'] for ids in self.book.scenes for b in ids if b in self.book.by_id)
        first = {}
        for kind, cue in SKY_WORDS.items():
            m = re.search(r'(?<![\w-])(?:' + cue + r')', story, re.I)
            if m:
                first[kind] = self._took(story, m.start(), m.end())
        return {kind for kind, took in first.items() if took}

    @staticmethod
    def _took(text, start, end):
        """Do the words at text[start:end] say that sky thing is not there?"""
        from ..director.v3.staging import absent
        return absent(text, start, end) or bool(TAKEN.search(text[max(0, start - 40):start])) or \
            bool(BEHIND.match(text, end))

    def _sky_words(self, text):
        """Follow what the words say about the moon, the sun and the stars, in reading order: "No moon anywhere",
        "the moon is gone", "somebody took the moon" or "the moon went behind a cloud" take it out of the sky; any
        other mention ("there was the moon") puts it back."""
        hits = sorted((m.start(), m.end(), kind) for kind, cue in SKY_WORDS.items()
                      for m in re.finditer(r'(?<![\w-])(?:' + cue + r')', text, re.I))
        for start, end, kind in hits:
            if self._took(text, start, end):
                self.gone.add(kind)
            else:
                self.gone.discard(kind)

    def _sky(self, shot, spec, place, sky, bid, text):
        """The page's sky (shot.sky) and weather (shot.atmosphere): the sky things its words name (the Reader's), the
        plan's own sky pictures, and its scene's atmosphere; at night no sun and a few stars outdoors; nothing the
        words took away; indoors only the sun or moon through a window (a dark one at night)."""
        from .storybook import _sky_kind
        book = self.book
        atmosphere = (spec.get('atmosphere') or {}).get('kind') or 'none'
        words = [d for line in self.read.get(bid, ()) if line.start < text[1] and text[0] < line.end
                 for d in line.sky]
        wanted = list(sky) + words                               # the plan's own picture first: a full moon
        if self.night or atmosphere in MOON_SKIES:
            wanted.append('fl_crescent_moon')
        if atmosphere in SUN_SKIES:
            wanted.append('fl_sun')
        if atmosphere == 'rain':
            wanted.append('fl_cloud_with_rain')
        out = []
        for doodle in wanted:
            kind = _sky_kind(doodle)
            if doodle in ('fl_crescent_moon', 'fl_sun') and kind in self.drawn:
                doodle = self.drawn[kind]                         # the same moon as the page before
            star = kind == doodle and 'star' in doodle
            if kind in [_sky_kind(d) for d in out] or kind in self.gone or (self.night and kind == 'sun') or \
                    (star and 'star' in self.gone):
                continue
            out.append(doodle)
        out = out[:2]
        self.drawn.update({_sky_kind(d): d for d in out if _sky_kind(d) in ('sun', 'moon')})
        out = book._window_sky(shot, out, place)
        for i, doodle in enumerate(out):
            shot.sky.append(doodle if isinstance(doodle, tuple) else (doodle, (.83, .2)[i], .15, .16))
        outdoors = place not in sets.INTERIOR and place != 'night_sky'
        if self.night and outdoors and 'star' not in self.gone:
            shot.sky += [('fl_star', x, y, h) for x, y, h in STARS]
        shot.atmosphere = 'none' if place in sets.INTERIOR and atmosphere in FOGS else atmosphere

    def _landscape(self, place):
        """The savanna for a nature place the story's words never name when they name a grassland (see
        GRASSLAND); the place itself otherwise."""
        own = NATURE_WORDS.get(place)
        if own is None:
            return place
        story = ' '.join(b['spoken'] for b in self.book.by_id.values())
        if GRASSLAND.search(story) and not re.search(r'\b(?:' + own + r')\b', story, re.I):
            return 'savanna'
        return place

    def _asleep(self, bid, text):
        """Who the words of this shot say is asleep ("fast asleep", "dozed off", "snoring"), with whoever lies down
        in that sentence ("curled up against his father, fast asleep"): cast id -> beat character offset of the
        words that put them to sleep. Plan poses never wake them."""
        out = {}
        for line in self.read.get(bid, ()):
            if not (line.start < text[1] and text[0] < line.end):
                continue
            asleep = [char for pose, char in line.poses.values() if pose == 'sleep']
            for cid, (pose, char) in line.poses.items():
                if pose in ('sleep', 'lie') and asleep:
                    out.setdefault(cid, min(asleep))
        return out

    def _roars(self, shot, spoken, timer, text):
        """A roar the words give someone on the page ("unleashing a roar", a cub's try that "came out as a tiny
        squeak") opens their mouth when its word is spoken, as on a page read from the text; someone lying down or
        asleep stays down."""
        for _, line in spoken:
            for cid, (pose, char) in line.poses.items():
                f = next((g for g in shot.figures if g.key == cid and not g.crowd), None)
                if pose != 'roar' or f is None or not text[0] <= char < text[1] or \
                        f.pose in ('sleep', 'lie', 'sit', 'carry'):
                    continue
                f.pose, f.cue = 'roar', timer(char)

    # ---------------- time
    def _timer(self, bid, start):
        timing = self.book.tl['beats'][bid]
        times = timing['char_times']
        return lambda char: timing['start'] - start + (times[max(0, min(char, len(times) - 1))] if times else 0.)

    def _offset(self, bid, starts_at, taken, lines):
        """Spoken char offset where a plan shot starts: its starts_at words; without them, the beat's start for its
        first shot and the next sentence after the shots before it."""
        beat = self.book.by_id[bid]
        display, spoken = beat['text'], beat['spoken']
        if starts_at:
            at = find_words(display, starts_at)
            if at is not None:
                return arc.spoken_offset(display, spoken, at)
            at = find_words(spoken, starts_at)
            if at is not None:
                return at
        if not taken:
            return 0
        later = [line.start for line in lines if line.start > max(taken)]
        return later[0] if later else None

    def _span_text(self, bid, offset, nxt):
        spoken = self.book.by_id[bid]['spoken']
        stop = nxt[1] if nxt and nxt[0] == bid else len(spoken)
        return (offset, stop, spoken[offset:stop])

    # ---------------- one shot
    def _stage(self, plan, begin, at, spec, bid, text):
        from .storybook import ADULT_HEIGHT, PERSON_HEIGHT, Shot
        book = self.book
        shot = Shot(begin, begin)
        shot.framing = plan.get('shot') or 'wide'
        people = []
        for c in plan.get('cast') or ():
            c = dict(c, id=self.person(c.get('id')))
            if c['id'] not in [d['id'] for d in people]:
                people.append(c)                          # an age variant of someone is that person, once a page
        heard = {c['id'] for c in people if c.get('speaking') == 'off_screen'}
        cast = [c for c in people if c.get('id') in book.cast and c['id'] not in heard]
        from .storybook import _sky, _sky_kind
        props = [dict(p) for p in plan.get('props') or () if self._known(p.get('ref'))]
        sky = [p['ref'] for p in props if _sky(p['ref'])]          # a moon or a cloud hangs in the sky
        props = [p for p in props if not _sky(p['ref'])]
        if _sky(plan.get('focus_ref') or '') and _sky_kind(plan['focus_ref']) in self.gone:
            plan = dict(plan, focus_ref='')                       # "The moon is gone": no close-up of the moon
        focus = plan.get('focus_ref') or ''
        if (not book.story and shot.framing in ('insert', 'close') and self._known(focus) and not writable(focus)
                and focus not in [p['ref'] for p in props] + list((plan.get('setting') or {}).get('set_refs') or ())):
            # Outside a story the thing an insert looks at stands in the set (the bowl on the kitchen counter),
            # not alone on blank paper.
            props.append({'ref': focus, 'relation': 'none', 'to': '', 'motion': 'none'})
        figures = []
        setting = plan.get('setting') or {}
        place = self._landscape(place_for(setting.get('place'), self.place))
        if place_for(setting.get('place')) is None and cast and self.last is not None and not (
                {c['id'] for c in cast} & {f.key for f in self.last.figures}):
            place = next((self.seen[c['id']] for c in cast if c['id'] in self.seen), None)   # her own kitchen
        humans = [c for c in cast if book._human(c['id'])]
        if place == 'car' and humans:
            place = 'car_inside'                          # people in a car are seen inside it
        elif (self.in_car and place not in sets.INTERIOR and humans
              and not any(c.get('pose') in ('walk', 'run') for c in humans) and not GOT_OUT.search(text[2])):
            cast = [c for c in cast if c not in humans]   # pulled over by a field: still in the car, seen from outside
            props.append({'ref': 'fl_automobile', 'relation': 'none', 'to': '', 'motion': 'none'})
        elif humans or place in sets.INTERIOR:
            self.in_car = False
        if place == 'car_inside':
            self.in_car = True
        holder = self._still_held(plan, cast, props, place)
        if holder is not None:
            cast = [{'id': holder.key, 'pose': 'hold', 'speaking': 'no',
                     'age': next((k for k, v in AGE_BAND.items() if v == holder.age), None)}]
        for c in cast[:4]:
            f = book._cast_figure(c['id'])
            if book._human(c['id']):
                band = AGE_BAND.get(c.get('age'))
                if book.reader.told(c['id']):
                    # Text-stated ages beat the plan's ("At sixteen, Lena ...", "Uncle Dev turns 50").
                    band = next((s.looks[c['id']] for s in self.read.get(bid, ()) if c['id'] in s.looks), None) \
                        or book.reader.look_age(c['id'])
                if band:
                    f.age, f.height = band, ADULT_HEIGHT * PERSON_HEIGHT.get(band, 1.)
                f.pose = POSE.get(c.get('pose'), 'stand')
                rest = self.rests.get(c['id'])
                if rest and rest[0] == place and c.get('pose') in IN_PLACE:
                    f.pose = 'sit' if rest[1] == 'sleep' else rest[1]     # she talks from the couch
                if c.get('speaking') == 'yes' and f.pose in ('sleep', 'lie'):
                    f.pose = 'sit'                         # whoever speaks is awake and sits up
                if place == 'car_inside' and f.pose not in ('sleep', 'lie'):
                    f.pose = 'sit'                         # everyone in a car is in a seat
                if f.pose in ('sleep', 'lie') and any(spec[0] == 'strip:road' for spec in sets.SETS.get(place, ())) \
                        and not LYING.search(book.by_id[bid]['spoken']):
                    f.pose = 'stand'                       # nobody lies in the road unless the words lay them there
            else:
                f.pose = 'carry' if c.get('pose') == 'carry' else POSE.get(c.get('pose'), 'stand')
            figures.append(f)
        sleepers = self._asleep(bid, text)
        speaking = {c['id'] for c in cast if c.get('speaking') == 'yes'}
        for f in figures:
            if f.key in speaking or f.key not in sleepers and not (sleepers and f.pose == 'lie') or f.pose == 'sleep':
                continue
            char = sleepers.get(f.key, min(sleepers.values()))
            if char > text[0]:                            # awake (lying, else lying down) until the words say so
                f.before, f.cue = f.pose if f.pose in ('lie', 'sit') else 'lie', at(char)
            f.pose = 'sleep'                              # "fast asleep", "snoring": the words put them to sleep
        focus = plan.get('focus_ref') or ''
        if SCREEN.search(focus) and any(p.get('relation') == 'in' for p in props):
            for p in props:                               # the puddles the girl on the video jumps in are on it too
                if p['ref'] != focus and p.get('relation') in (None, 'none') and p.get('motion') in (None, 'none') \
                        and not _kind(p['ref']):
                    p['relation'], p['to'] = 'in', focus
        props = [p for p in props if not self._talked_about(p, bid)]
        named = [cid for cid in book.cast if self._named(cid, text[2])]
        screen_to = [p.get('to') for p in props if p.get('relation') == 'in']
        screen = self._on_screen(props, figures, named)
        speaking = {c['id'] for c in plan.get('cast') or () if c.get('speaking') == 'yes'}
        for f in [f for f in figures if f.key in self.screened and f.key not in named and f.key not in speaking]:
            figures.remove(f)                             # the girl on the home video is not in the room
            screen.append(self.screened[f.key])
        for item in screen:
            if not isinstance(item, str):
                self.screened[item.key] = item
        if shot.framing == 'wide':
            for f in figures:
                f.height *= WIDE_SCALE
        natural = [f.height for f in figures]
        book._layout(figures, SimpleNamespace())
        shot.scale = min([f.height / h for f, h in zip(figures, natural) if h] or [1.])   # how much _fit shrank them
        time = setting.get('time')
        night_sky = (spec.get('atmosphere') or {}).get('kind') in NIGHT_SKIES
        self.night = time in ('night', 'dusk') or (time in (None, 'unknown') and (self.night or night_sky)) or (
            time == 'day' and night_sky and not DAYTIME.search(text[2]))   # "day" in a night scene, nothing says so
        shot.place = self.place = place
        refs, props = self._refs(place, setting.get('set_refs') or [], props, figures, text, at)
        book.stager.stage_explicit(shot, place, props, figures, at=lambda s: s, night=self.night, set_refs=refs)
        shot.figures = figures
        self._sky(shot, spec, place, sky, bid, text)
        if place is None and not shot.set and not figures:
            shot.set = []
        for p in shot.set:
            prop = next((q for q in props if q['ref'] == p.doodle), None)
            if prop and p.kind == 'hand' and prop.get('relation') == 'held_by' and prop.get('to') in [
                    f.key for f in figures]:
                p.holder = prop['to']
            if prop and prop.get('motion') == 'slide' and p.kind != 'hand':
                p.motion, p.cue, p.to = 'slide', prop['at'], (.6 if p.x < .5 else -.6, 0.)
        seated = self._seat(shot, figures, place, refs, (text[2], book.by_id[bid]['spoken']))
        self._by_tv(shot, figures, seated, bid, text)
        for f in figures:
            if f in seated:
                self.rests[f.key] = (place, f.pose)
            else:
                self.rests.pop(f.key, None)
        self._clear_of_furniture(shot, [f for f in figures if f not in seated], seated)
        book.props_clear(shot, figures)
        hosts = [p for p in shot.set if SCREEN.search(p.doodle) and not p.doodle.endswith('_stand')
                 and p.kind != 'hand']
        host = next((p for p in hosts if p.doodle in screen_to), hosts[0] if hosts else None)
        if host is not None and re.search(r'televis|\btv\b|monitor', _words(host.doodle), re.I):
            shot.screen = [(host, screen or ['menu'])]     # a TV that is on: its picture, else a menu of shows
            if screen:
                self.stamp = year_in(text[2]) or self.stamp
                if self.stamp:
                    shot.screen = [(host, screen + ['stamp:' + self.stamp])]   # a home video's date
        speakers = [c['id'] for c in plan.get('cast') or () if c.get('speaking') == 'yes'
                    and c['id'] in [f.key for f in figures]]
        if speakers and len(figures) > 1:
            book._face_speaker(figures, speakers[0])
        self._frame(shot, plan, figures, speakers, props, bid, text)
        self._hands(shot, plan, focus)
        self.last = shot
        self.seen.update({f.key: place for f in figures})
        return shot

    def _still_held(self, plan, cast, props, place):
        """Whoever the last shot on this set had holding the thing this shot looks at alone, resting on nothing (a
        close-up of the envelope a moment after the boy holds it): it stays in their hands. None otherwise."""
        focus, last = plan.get('focus_ref') or '', self.last
        if not self.book.story or cast or not focus or last is None or last.place != place:
            return None                                   # outside a story an off-screen hand works it (_hands)
        prop = next((p for p in props if p.get('ref') == focus), None)
        if prop is None or prop.get('relation') not in (None, 'none') or prop.get('motion') not in (None, 'none'):
            return None
        key = next((p.holder for p in last.set if p.kind == 'hand' and p.doodle == focus and p.holder), None)
        holder = next((f for f in last.figures if f.key == key and f.key in self.book.cast), None)
        if holder is not None:
            prop['relation'], prop['to'] = 'held_by', holder.key
        return holder

    def _hands(self, shot, plan, focus):
        """Outside a story an insert or close-up of a thing that someone off screen holds or works shows their hand
        reaching in to it (the cook's hand on the bowl), in their skin tone."""
        book = self.book
        if book.story or shot.page or shot.figures or shot.framing not in ('insert', 'close'):
            return
        piece = next((p for p in shot.set if p.doodle == focus and p.kind not in ('strip', 'hand')), None)
        worker = next((c['id'] for c in plan.get('cast') or () if c.get('pose') in HAND_POSES
                       and self.person(c.get('id')) in book.cast and book._human(self.person(c.get('id')))), None)
        if piece is None or worker is None:
            return
        shot.hands = [(piece, book._look(self.person(worker))['tone'])]

    def _seat(self, shot, figures, place, refs, texts=()):
        """Seat everyone who sits, lies or sleeps: the person the shot's words (else its beat's) put on a seat or in
        bed ("Nana was sitting up in bed") on that one, the others on the seat they had on this set before, else on a free one (the
        armchair the plan names before a couch someone lies on), side by side in slots that never overlap. When
        every seat is full, a chair is brought in beside them, and it stays on this set for the rest of the scene."""
        book = self.book
        resting = [f for f in figures if f.pose in ('sit', 'lie', 'sleep')]
        named = next((n for n in (self._settler(t, [f.key for f in resting]) for t in texts) if n), None)
        if named:
            who, what = named
            old = self.seats.get(who)
            claim = next((s for s in shot.supports if s.kind in ('seat', 'bed') and re.search(
                SEAT_WORDS.get(what, what), f'{s.doodle} {_words(s.doodle)}', re.I)), None)
            if claim is not None and not (old and old[0] == place and old[1] == claim.doodle):
                for key, seat in list(self.seats.items()):
                    if key != who and seat[0] == place and seat[1] == claim.doodle:
                        del self.seats[key]                   # the bed is hers now; whoever had it sits elsewhere
                self.seats[who] = (place, claim.doodle, (claim.x0 + claim.x1) / 2)
        claimant = named[0] if named else None
        resting.sort(key=lambda f: (f.key != claimant, (self.seats.get(f.key) or ('',))[0] != place,
                                    f.pose == 'sit'))    # whom the text seats, who had a seat here, then sleepers
        for piece in self.extra.get(place, ()):
            chair = copy.copy(piece)
            shot.set.append(chair)
            support = book.stager.support_of(chair)
            if support is not None:
                shot.supports.append(support)
        taken = {}                                       # id(support) -> [(x0, x1)] used on it
        seated = []

        def room(s, half, near):
            busy = taken.get(id(s), [])
            lo, hi = s.x0 + half * .6, s.x1 - half * .6
            spots = [lo + (hi - lo) * i / 20 for i in range(21)] if hi > lo else [(s.x0 + s.x1) / 2]
            clash = lambda x: round(sum(max(0., min(x + half, b) - max(x - half, a)) for a, b in busy), 3)
            best = min(spots, key=lambda x: (clash(x), abs(x - (near if near is not None else (s.x0 + s.x1) / 2))))
            return clash(best), best

        for f in resting:
            supports = [s for s in shot.supports if s.kind in ('seat', 'bed')]
            if not supports:
                continue
            half = book._half(f) * .95
            old = self.seats.get(f.key)
            mine = next((s for s in supports if old and old[0] == place and s.doodle == old[1]
                         and s.x0 - .02 <= old[2] <= s.x1 + .02), None)
            if f.pose in ('lie', 'sleep'):
                lying = mine or next((s for s in supports if id(s) not in taken and s.kind == 'bed'), None) or \
                    next((s for s in supports if id(s) not in taken), supports[0])
                if book.seat(f, shot, prefer=[lying.doodle]):
                    taken.setdefault(id(lying), []).append((lying.x0 - 1, lying.x1 + 1))
                    seated.append(f)
                    self.seats[f.key] = (place, lying.doodle, f.x)
                continue
            near = old[2] if old and old[0] == place else None
            options = ([mine] if mine else []) + sorted(
                [s for s in supports if s is not mine], key=lambda s: (room(s, half, near)[0] > 0,
                                                                     s.doodle not in refs, s.kind == 'bed'))
            support = options[0]
            overlap, x = room(support, half, near)
            if overlap > 0:
                support = self._extra_seat(shot, place, figures, supports) or support
                overlap, x = room(support, half, near)
            f.x, f.ground, f.travel = x, support.y, 0.
            f.depth = max(f.depth, 2)
            taken.setdefault(id(support), []).append((x - half, x + half))
            self.seats[f.key] = (place, support.doodle, x)
            seated.append(f)
        return seated

    def _settler(self, text, keys):
        """(cast id, seat word) when the text puts a named person onto a seat or into bed ("Nana was sitting up in
        bed", "Dad lay in bed"): the last of these people named before the verb in its sentence, unless a pronoun
        stands between them (then it could be anyone, and nobody is chosen)."""
        found = sets.settles(text)
        if not found or not keys:
            return None
        m = sets.SETTLE.search(text)
        start = max(text.rfind(c, 0, m.start()) for c in '.!?;') + 1
        before = text[start:m.start()]
        best = None
        for key in keys:
            name = name_key(self.book.cast[key].get('name') or '').split()
            for hit in re.finditer(r'(?<!\w)' + re.escape(name[0]) + r'(?!\w)', before, re.I) if name else ():
                if best is None or hit.end() > best[1]:
                    best = (key, hit.end())
        if best is None or re.search(r'\b(?:he|she|they)\b', before[best[1]:], re.I):
            return None
        return best[0], m.group('what').lower()

    def _extra_seat(self, shot, place, figures, supports):
        """A chair on the floor where the page is free, as near the full seats as it can stand."""
        book = self.book
        doodle, height = 'fl_chair', .22
        half = book.stager.half(doodle, height)
        boxes = [self._box(p) for p in shot.set if p.kind in ('set', 'thing') and not p.lone
                 and p.height > .06 and abs(p.ground - sets.FLOOR) < .03]
        boxes += [self._body(f) for f in figures if f.pose not in ('sit', 'lie', 'sleep')]
        middle = sum((s.x0 + s.x1) / 2 for s in supports) / len(supports)
        free = [x for x in (.06 + .88 * i / 60 for i in range(61))
                if .02 + half <= x <= .98 - half and not any(x + half > b[0] and x - half < b[2] for b in boxes)]
        if not free:
            return None
        x = min(free, key=lambda x: abs(x - middle))
        chair = sets.Piece(doodle, x, sets.FLOOR, height, kind='set')
        shot.set.append(chair)
        self.extra.setdefault(place, []).append(copy.copy(chair))
        support = book.stager.support_of(chair)
        if support is not None:
            shot.supports.append(support)
        return support

    def _by_tv(self, shot, figures, seated, bid, text):
        """A shot whose own words put someone in front of the TV ("half-asleep in front of the TV") has it right
        beside them and keeps it in its framing (shot.keep); a chair in its way moves along with whoever sits on it.
        Later shots of them there are framed on their own words (a conversation keeps its speakers close)."""
        keys = [f.key for f in figures]
        watchers = []
        for line in self.read.get(bid, ()):
            m = BY_TV.search(line.text) if line.start < text[1] and text[0] < line.end else None
            refs = [r for r in line.refs if r[0] < m.start() and r[2] != 'of' and r[1] in keys] if m else []
            if refs:
                watchers.append(figures[keys.index(max(refs)[1])])
        tv = [p for p in shot.set if p.kind not in ('hand', 'strip') and re.search(r'televis|\btv\b', _words(p.doodle))]
        if not watchers or not tv:
            return
        stands = [s.piece for s in shot.supports if s.kind == 'top' and any(
            abs(p.ground - s.y) < .02 and s.x0 <= p.x <= s.x1 for p in tv)]
        group = tv + [p for p in stands if p not in tv]
        boxes = [self._box(p) for p in group]
        gx0, gx1 = min(b[0] for b in boxes), max(b[2] for b in boxes)
        on = lambda s, f: abs(f.ground - s.y) < .02 and s.x0 - .02 <= f.x <= s.x1 + .02
        seat = next((s for s in shot.supports if s.kind in ('seat', 'bed') and any(
            on(s, f) for f in watchers if f in seated)), None)
        wx0, wx1 = (self._box(seat.piece)[0], self._box(seat.piece)[2]) if seat else \
            (min(self._body(f)[0] for f in watchers), max(self._body(f)[2] for f in watchers))
        dx = wx1 + TV_GAP - gx0 if gx0 >= wx1 else wx0 - TV_GAP - gx1 if gx1 <= wx0 else 0.
        if gx0 + dx < 0 or gx1 + dx > 1:
            dx = 0.
        for p in group:
            p.x += dx
        lo, hi = gx0 + dx, gx1 + dx
        for s in shot.supports:
            if s.piece in group:
                s.x0, s.x1 = s.x0 + dx, s.x1 + dx
            elif s is not seat and s.kind == 'seat' and s.piece.kind == 'set':
                b = self._box(s.piece)
                if not (b[0] < hi and lo < b[2]):
                    continue
                move = (hi + TV_GAP - b[0]) if hi + TV_GAP + b[2] - b[0] <= 1 else (lo - TV_GAP - b[2])
                for f in seated:
                    if on(s, f):
                        f.x += move
                s.piece.x, s.x0, s.x1 = s.piece.x + move, s.x0 + move, s.x1 + move
        shot.keep = group

    def _clear_of_furniture(self, shot, standing, seated):
        """Standing and walking people keep off the couch and the bed: each stands where the page is free, as near
        its own spot as it can."""
        book = self.book
        if not standing or not (shot.supports or shot.keep):
            return
        boxes = [(s.x0, s.x1) for s in shot.supports if s.kind in ('seat', 'bed')]
        boxes += [(f.x - book._half(f) * .8, f.x + book._half(f) * .8) for f in seated]
        boxes += [(b[0], b[2]) for b in map(self._box, shot.keep)]     # nobody stands in front of the TV she watches
        for f in standing:
            half = book._half(f)
            lo, hi = half + .01, 1 - half - .01 - f.travel
            if lo >= hi:
                continue
            spots = [lo + (hi - lo) * i / 40 for i in range(41)]
            cost = lambda x: (round(sum(max(0., min(x + half + f.travel, b) - max(x - half, a)) for a, b in boxes), 3),
                              abs(x - f.x))
            f.x = min(spots, key=cost)
            boxes.append((f.x - half, f.x + half + f.travel))
        everyone = standing + seated
        for f in standing:
            others = [g.x for g in everyone if g is not f]
            if others and not f.travel:
                f.facing = 'r' if sum(others) / len(others) > f.x else 'l'

    VARIANT = re.compile(r'^(?:(?:old|older|young|younger|little|baby|teen|adult|grown|elder|kid|child)_(?P<a>.+)|'
                         r'(?P<b>.+?)_(?:old|older|young|younger|little|baby|teen|adult|grown|elder|kid|child|'
                         r'now|then|later|past|future|\d+))$')

    def person(self, cid):
        """The cast member an id stands for: 'sam_old', 'young_sam' or a cast entry named "Old Sam" is Sam."""
        cast = self.book.cast
        if not cid:
            return cid
        m = self.VARIANT.match(cid)
        base = m and (m['a'] or m['b'])
        if base in cast and base != cid:
            return base
        c = cast.get(cid)
        if c is not None:
            core = re.sub(r'\b(?:old|older|young|younger|little|baby|teen(?:age)?|adult|grown[- ]up|elderly)\b|[()]', '',
                          c.get('name') or '', flags=re.I).strip()
            other = next((d['id'] for d in cast.values() if d['id'] != cid and core
                          and name_key(d.get('name') or '') == name_key(core)), None)
            if other and core != (c.get('name') or '').strip():
                return other
        return cid

    def _talked_about(self, p, bid):
        """A thing only spoken of (the horse in "a movie where a man just rides a horse") is not in the room: its
        name is in the beat's speech and nowhere in its narration."""
        if p.get('relation') not in (None, 'none') or p.get('motion') not in (None, 'none'):
            return False
        display = self.book.by_id[bid]['text']
        label = SPEAKER_LABEL.match(display)
        if label:
            narration = ' '.join(re.findall(r'[\[(]([^\])]*)[\])]', display[label.end():]))
            speech = re.sub(r'[\[(][^\])]*[\])]', ' ', display[label.end():])
        else:
            speech = ' '.join(re.findall(r'["\u201c]([^"\u201d]*)["\u201d]', display))
            narration = re.sub(r'["\u201c][^"\u201d]*["\u201d]', ' ', display)
        names = [t for t in re.split(r'[_\W\d]+', re.sub(r'^(?:fl|tb|set|kd)_', '', p['ref'])) if len(t) > 2]
        said = lambda t, where: re.search(r'\b' + re.escape(t) + r'(?:e?s)?\b', where, re.I)
        return bool(names) and any(said(t, speech) for t in names) and not any(said(t, narration) for t in names)

    def _known(self, ref):
        return bool(ref) and (sets.svg(ref) is not None or library.resolve(ref) is not None)

    def _named(self, cid, text):
        c = self.book.cast[cid]
        key = name_key(c.get('name') or '')
        return bool(key) and bool(re.search(r'(?<!\w)' + re.escape(key.split()[0]) + r'(?!\w)', text, re.I))

    def _on_screen(self, props, figures, named):
        """What a screen in the shot shows (a prop placed ``in`` a TV, laptop or phone): pictures, and the cast
        member a person picture stands for (the girl on the home video is the mother as a child), who is then on
        the screen instead of in the room."""
        shown = []
        for p in [p for p in props if p.get('relation') == 'in' and SCREEN.search(p.get('to') or '')]:
            props.remove(p)
            person = next((v for k, v in PERSON_PICTURE.items() if re.search(r'(?:^|_)' + k + r'(?:_|$)', p['ref'])),
                          None)
            match = None
            if person:
                band, sex = person
                match = next((f for f in figures if f.species == 'human' and f.key not in named
                              and (band is None or f.age == band) and (sex is None or f.sex == sex)), None)
            if match is not None:
                figures.remove(match)
                shown.append(match)
            else:
                shown.append(p['ref'])
        return shown

    def _refs(self, place, set_refs, props, figures, text, at):
        """The set_refs and props to stage: a picture that is the place itself is the set; a picture of a kind of
        furniture the set already draws (a desk, a lamp, a couch) is the set's own; a thing put on or in a person is
        in their hands; a motion starts when the text says it moves."""
        own = [spec[0] for spec in sets.SETS.get(place, ()) if not spec[0].startswith('strip:')]
        swap = {}
        for ref in list(set_refs) + [p['ref'] for p in props]:
            kind = _kind(ref)
            same = next((d for d in own if kind and _kind(d) == kind), None) or KIND_ART.get(kind)
            if same and same != ref and ref not in own and ref not in sets.SVG:
                swap[ref] = same
        keys = [f.key for f in figures]
        refs = []
        for ref in set_refs:
            if not self._known(ref) or sets.picture_place(ref) or ref in [p['ref'] for p in props]:
                continue
            refs.append(swap.get(ref, ref))
        out = []
        moved = re.search(r'\b(?:roll\w*|fell|falls?|falling|dropp?\w*|spill\w*|fl[eiy]\w*|slid\w*|went\s+by|'
                          r'drove|drives?|passed|bounc\w*|toss\w*|thr[eo]w\w*)\b', text[2], re.I)
        for p in props:
            ref, to = swap.get(p['ref'], p['ref']), self.person(swap.get(p.get('to') or '', p.get('to') or ''))
            if sets.picture_place(ref) and p.get('relation') in (None, 'none') and p.get('motion') in (None, 'none'):
                continue
            if any(f.species != 'human' and re.search(r'\b' + re.escape(f.species) + r'(?:e?s)?\b', _words(ref), re.I)
                   for f in figures):
                continue                                  # a picture of the animal on the page is that character
            relation = p.get('relation') or 'none'
            if to in keys and relation != 'held_by':
                relation = 'held_by'
            if to not in keys and (relation == 'held_by' or not self._known(to)):
                relation, to = 'none', ''                 # by someone not on this page (or nothing drawn): just there
            motion = p.get('motion') if p.get('motion') in ('roll', 'fall', 'fly', 'drop', 'slide') else None
            when = at(text[0] + moved.start()) if moved and motion else at(text[0]) + .4
            out.append({'ref': ref, 'relation': relation, 'to': to, 'motion': motion, 'at': when})
        return refs, out

    # ---------------- framing
    def _frame(self, shot, plan, figures, speakers, props, bid, text):
        book = self.book
        kind = shot.framing
        focus = plan.get('focus_ref') or ''
        piece = next((p for p in shot.set if p.doodle == focus and p.kind != 'strip'), None)
        if focus and writable(focus):
            self.readable = focus
        if kind in ('insert', 'first_person') and not focus and self.readable:
            focus = self.readable                         # "She unfolded it": the thing read a moment ago
        if kind != 'wide' and focus and (PHONE.search(_words(focus)) or SIGNAL.search(focus)) and \
                NO_SIGNAL.search(text[2]):
            shot.page = self._page(focus if PHONE.search(_words(focus)) else 'fl_mobile_phone', [], None, text[2])
            shot.figures, shot.bubbles = [], []           # the phone itself, showing no bars
            return
        if kind in ('insert', 'first_person') and focus and writable(focus):
            words = writing_for(book, plan, bid, text) or self.written.get(focus, [])   # read again: same words
            if words:
                self.written[focus] = list(words)
            reader = next((f for f in figures if f.pose in ('look', 'sit', 'stand')), figures[0] if figures else None)
            if words or kind == 'first_person' or PHONE.search(focus) or MAP.search(_words(focus)):
                shot.page = self._page(focus, words, reader, text[2])
                shot.figures, shot.bubbles = [], []
                return
        if kind in ('insert', 'first_person') or (kind == 'close' and not figures):
            box = self._arrangement(shot, piece, props) if piece is not None else None
            holder = next((f for f in figures if piece is not None and piece.kind == 'hand' and f.key == piece.holder),
                          None)
            if box is None and holder is not None and book.story:
                held = self._held_box(shot, piece)        # in a story: her hands on it, in her room
                self._look_at(shot, self._union([self._knees_up(holder)] + ([held] if held else [])), MEDIUM_FILL,
                              MAX_ZOOM['insert'])
                return
            if box is None:
                if not focus:
                    return
                self._lone(shot, focus)
                return
            self._look_at(shot, box, INSERT_FILL, MAX_ZOOM['insert'])
            return
        if kind == 'wide' or not figures:
            return
        subject = next((f for f in figures if f.key in speakers), figures[0])
        if kind == 'close':
            # The thing the close-up is about stays in it: the envelope in his hands, the one on the desk he reaches
            # for (he is brought to that desk first).
            thing = None if piece is None else self._held_box(shot, piece) if piece.kind == 'hand' else \
                self._arrangement(shot, piece, props)
            if thing is not None and piece.kind != 'hand' and self._union([self._body(subject), thing])[2] - \
                    self._union([self._body(subject), thing])[0] > .5 and self._desk(shot, subject, piece):
                thing = self._arrangement(shot, piece, props)
            # Framed from the head's own box (an animal's head is at its side, a sleeper's low): the whole head
            # inside the frame and above the captions, with room for a speaker's bubble.
            head = book.head_box(subject)
            top, hx = min(head[1], self._top(subject)), (head[0] + head[2]) / 2
            span = (subject.ground - top) * .42
            face = self._union([head, (hx - .5 * span * book.size[1] / book.size[0], top,
                                       hx + .5 * span * book.size[1] / book.size[0], top + span)])
            self._look_at(shot, self._night_sky(shot, face if thing is None else self._union([face, thing])),
                          (CLOSE_WIDTH, CLOSE_SPEAKING if subject.key in speakers else CLOSE_FILL), MAX_ZOOM['close'],
                          at=.4)
            return
        group = figures
        if kind == 'two_shot' and len(figures) > 2:
            partner = min((f for f in figures if f is not subject), key=lambda f: abs(f.x - subject.x))
            group = [subject, partner]
        boxes = [self._knees_up(f) for f in group]
        arrangement = self._arrangement(shot, piece, props) if piece is not None and not shot.screen else None
        if piece is not None and shot.screen:
            arrangement = self._box(piece)
        if piece is not None and shot.screen and shot.screen[0][1] == ['menu']:
            arrangement = None                            # a TV showing nothing in particular is not the subject
        if arrangement is not None:
            near = self._union(boxes + [arrangement])
            if near[2] - near[0] > .5 and (shot.screen or self._desk(shot, subject, piece)):
                boxes = [self._knees_up(subject)] if not shot.screen else []
            boxes.append(arrangement)
        boxes += [self._box(p) for p in shot.keep]       # the TV she sleeps in front of stays in the shot
        self._look_at(shot, self._night_sky(shot, self._union(boxes)), MEDIUM_FILL,
                      MAX_ZOOM[kind if kind in MAX_ZOOM else 'medium'])
        self._uncut(shot, [f for f in figures if f not in group or not any(b == self._knees_up(f) for b in boxes)],
                    self._union(boxes))

    def _uncut(self, shot, others, keep):
        """Nobody is cut in half at the frame's side: the locked framing pans just past a person it would show only
        in part, as long as what it frames stays in."""
        cx, cy, zoom = shot.view
        half = .5 / zoom
        for f in sorted(others, key=lambda f: abs(f.x - cx)):
            x0, _, x1, _ = self._body(f)
            left, right = cx - half, cx + half
            if x1 <= left or x0 >= right or (x0 >= left and x1 <= right):
                continue
            moved = (x1 + .005 + half) if f.x < (keep[0] + keep[2]) / 2 else (x0 - .005 - half)
            if moved - half <= keep[0] + .002 and keep[2] - .002 <= moved + half and half <= moved <= 1 - half:
                cx = moved
                continue
            shot.view = (cx, cy, zoom)                    # no room to pan past them: frame them whole
            keep = self._union([keep, self._knees_up(f)])
            self._look_at(shot, keep, MEDIUM_FILL, zoom)
            cx, cy, zoom = shot.view
            half = .5 / zoom
        shot.view = (cx, cy, zoom)

    def _desk(self, shot, f, piece):
        """Bring a person to the desk or table the shot looks at: sitting on a chair beside it, or standing there."""
        support = next((s for s in shot.supports if s.kind == 'top' and s.x0 - .02 <= piece.x <= s.x1 + .02
                        and _kind(s.doodle) in ('desk', 'table', 'counter')), None)
        if support is None or piece.kind != 'thing' or f.pose not in ('sit', 'stand', 'look', 'happy'):
            return False
        book = self.book
        half = book._half(f)
        side = 1 if (support.x0 + support.x1) / 2 < .5 else -1
        x = (support.x1 + half + .01) if side > 0 else (support.x0 - half - .01)
        x = min(1 - half - .01, max(half + .01, x))
        if f.pose == 'sit':
            chair = sets.Piece('fl_chair', x, sets.FLOOR, .22, kind='set')
            shot.set.append(chair)
            seat = book.stager.support_of(chair)
            if seat is not None:
                shot.supports.append(seat)
                f.ground = None
                book.seat(f, shot, prefer=['fl_chair'])
                if f.ground is None:
                    f.ground = sets.FLOOR
        else:
            f.x = x
        f.travel = 0.
        f.facing = 'l' if side > 0 else 'r'
        return True

    def _arrangement(self, shot, piece, props):
        """The box of what an insert looks at: the thing and what it rests on, leans against or holds."""
        if piece is None:
            return None
        related = {piece.doodle}
        for p in props:
            if p['ref'] == piece.doodle and p.get('to'):
                related.add(p['to'])
            if p.get('to') == piece.doodle:
                related.add(p['ref'])
        boxes = [self._box(p) for p in shot.set if p.doodle in related and p.kind not in ('strip', 'hand')]
        under = next((s for s in shot.supports if s.kind == 'top' and s.piece is not piece
                      and abs(piece.ground - s.y) < .02 and s.x0 - .02 <= piece.x <= s.x1 + .02), None)
        if under is not None:
            boxes.append((min(s for s in (under.x0,)), under.y - .01, under.x1, under.y + .05))
        if piece.kind == 'hand' or not boxes:
            return None
        if len(boxes) == 1 and under is None:
            x0, y0, x1, y1 = boxes[0]
            pad = (y1 - y0) * .3
            return x0 - pad, y0 - pad, x1 + pad, y1 + pad
        return self._union(boxes)

    def _lone(self, shot, focus):
        """An insert of a thing on its own: drawn large in the middle of the page."""
        shot.set = [sets.Piece(focus, .5, .74, .46, kind='thing', lone=True)]
        shot.supports, shot.figures, shot.props, shot.screen = [], [], [], []

    def _night_sky(self, shot, box):
        """At night a framing of a room keeps its dark window in view (the night is what the words say) when the
        window hangs above what it frames (its middle over it), so the shot stays as close as it was meant to be."""
        window = next((p for p in shot.set if p.doodle == 'set_window_night'), None) if self.night else None
        if window is None:
            return box
        pane = self._box(window)
        both = self._union([box, pane])
        above = box[0] - .03 < (pane[0] + pane[2]) / 2 < box[2] + .03     # over it, not just at a shoulder's edge
        return both if above and both[2] - both[0] <= .7 and both[3] - both[1] <= .62 else box

    def _held_box(self, shot, piece):
        """The frame box of a thing in its holder's hands as the shot opens; None when the holder is not on it."""
        held = self.book.held_at(piece, shot, shot.start)
        if held is None:
            return None
        x, middle, anchor = held
        return self.book.stager.frame(piece.doodle, x, middle + (1 - anchor) * piece.height, piece.height,
                                      piece.mirror)[2]

    def _box(self, piece):
        return self.book.stager.frame(piece.doodle, piece.x, piece.ground, piece.height, piece.mirror)[2]

    def _body(self, f):
        return self.book._shape(f, self.book._pose_name(f.pose), f.x)[0]

    def _top(self, f):
        return self._body(f)[1]

    def _knees_up(self, f):
        """Someone from the knees up, their whole head with it (a crown, a mane): a framing never cuts through it."""
        x0, y0, x1, y1 = self._body(f)
        hx0, hy0, hx1, _ = self.book.head_box(f)
        return (min(x0, hx0), min(y0, hy0), max(x1, hx1),
                y1 - (y1 - y0) * (KNEES if f.pose not in ('sit', 'lie', 'sleep') else 0.))

    @staticmethod
    def _union(boxes):
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                max(b[3] for b in boxes))

    def _look_at(self, shot, box, fill, most, at=EYE_LINE):
        """Lock the shot's camera on a box (frame shares): as large as ``fill`` allows, its middle on the eye line,
        never past the page's edges."""
        x0, y0, x1, y1 = box
        fw, fh = fill
        zoom = max(1., min(most, fw / max(.01, x1 - x0), fh / max(.01, y1 - y0)))
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2 - (at - .5) / zoom
        half = .5 / zoom
        shot.view = (min(1 - half, max(half, cx)), min(1 - half, max(half, cy)), zoom)

    def _page(self, focus, words, reader, text):
        tone = 'tan'
        if reader is not None:
            look = self.book.looks.get(reader.key) or {}
            tone = look.get('tone', tone)
        kind = 'phone' if PHONE.search(_words(focus)) else 'map' if MAP.search(_words(focus)) else 'paper'
        status = 'none' if NO_SIGNAL.search(text) else 'full'
        return {'kind': kind, 'doodle': focus, 'lines': list(words), 'tone': tone, 'signal': status}

    # ---------------- bubbles
    def _quotes(self, beats, read):
        """Every quoted line in reading order: (beat id, line, q0, lead, words, heard)."""
        book = self.book
        for bid in beats:
            display = book.by_id[bid]['text']
            label = SPEAKER_LABEL.match(display)
            for line in read[bid]:
                if not line.quotes:
                    continue
                outside = re.sub(r'["“][^"”]*["”]?', ' ', line.text)
                direction = re.match(r'\s*[\[(]([^\])]*)[\])]', display[label.end():]) if label else None
                heard = bool(OFFSCREEN.search(outside) or (direction and OFFSCREEN.search(direction[1])))
                for q0, q1 in line.quotes:
                    raw = line.text[q0 - line.start:q1 - line.start]
                    lead = len(raw) - len(raw.lstrip(' "“'))
                    words = raw.strip().strip('"“”').strip().rstrip(',;:').strip()
                    if words:
                        yield bid, line, q0, lead, words, heard

    def _voices(self, plans, beats, read, timers):
        """Who speaks each quoted line, worked out before the shots are staged: {(beat id, q0): (speaker, index of
        the plan shot it falls in, the plan's speaker)}. The speaker is the one speakers.attribute gave the voice."""
        lines_by_beat = {}
        for bid, _, plan in plans:
            lines_by_beat.setdefault(bid, []).extend(plan.get('lines') or ())
        out = {}
        for bid, line, q0, lead, words, heard in self._quotes(beats, read):
            at = q0 + lead
            i = max([k for k, (b, o, _) in enumerate(plans) if (beats.index(b), o) <= (beats.index(bid), at + 1)]
                    or [0]) if plans else None
            speaker = self.person(self.book.speakers.of(bid, q0))
            speaker = speaker if speaker in self.book.cast else None
            planned = next((self.person(l.get('speaker')) for l in lines_by_beat.get(bid, [])
                            if find_words(words, l.get('quote') or '') == 0), None)
            out[(bid, q0)] = (speaker, i, planned, heard)
        return out

    def _recast(self, plan, voices):
        """The plan shot with its cast following who really speaks in it: the person the plan wrongly made the
        speaker gives their place to the speaker (or both stay and only who talks changes)."""
        wrong = [(v[0], v[2]) for v in voices if v[0] and v[2] and v[0] != v[2]]
        if not wrong or not plan:
            return plan
        plan = copy.deepcopy(plan)
        cast = plan.get('cast') or []
        for speaker, planned in wrong:
            ids = [self.person(c.get('id')) for c in cast]
            mine = next((c for c in cast if self.person(c.get('id')) == planned), None)
            if speaker in ids:
                for c in cast:
                    if self.person(c.get('id')) == speaker and c.get('speaking') != 'off_screen':
                        c['speaking'] = 'yes'
                if mine is not None and mine.get('speaking') == 'yes':
                    mine['speaking'] = 'no'
            elif mine is not None and speaker in self.book.cast and len(cast) == 1:
                mine['id'] = speaker                       # a single on the speaker, not the listener
            elif speaker in self.book.cast and len(cast) < 4 and not any(
                    c.get('speaking') == 'off_screen' for c in cast):
                cast.append({'id': speaker, 'age': '', 'pose': 'talk', 'speaking': 'yes'})
                if mine is not None and mine.get('speaking') == 'yes':
                    mine['speaking'] = 'no'
            for l in plan.get('lines') or ():
                if self.person(l.get('speaker')) == planned:
                    l['speaker'] = speaker
        return plan

    def _bubbles(self, shots, beats, read, timers, plans, voices):
        from .storybook import BUBBLE_WORDS, Bubble
        book = self.book
        for bid, line, q0, lead, words, heard in self._quotes(beats, read):
            at = timers[bid]
            speaker, _, planned, heard = voices.get((bid, q0), (None, None, None, heard))
            if speaker is None:
                continue
            # A long line speaks sentence by sentence, each in its own bubble; a long sentence phrase by
            # phrase.
            for a, z in chunks(words, BUBBLE_WORDS):
                part = words[a:z].rstrip(',;:-').strip()
                if not part:
                    continue
                first = q0 + lead + a + len(words[a:z]) - len(words[a:z].lstrip())
                t = at(first)
                shot = next((s for s in reversed(shots) if s.start <= t + .01), shots[0])
                if shot.page is not None:
                    continue                              # a page filling the frame: the line is the caption's
                plan = plans.get(id(shot)) or {}
                hidden = heard or speaker in {self.person(c['id']) for c in plan.get('cast') or ()
                                              if c.get('speaking') == 'off_screen'}
                if hidden:
                    self._hear(shots, shot, speaker)
                for f in shot.figures:
                    if f.key == speaker and f.pose in ('sleep', 'lie'):
                        f.pose = 'sit'            # whoever speaks is awake and sits up
                times = tuple(at(first + i) for i in range(len(part)))
                if shot.bubbles:
                    shot.bubbles[-1].end = min(shot.bubbles[-1].end, times[0] - .05)
                side = None
                if speaker not in [f.key for f in shot.figures]:
                    side = self._edge(shot, speaker)
                shot.bubbles.append(Bubble(speaker, part, times[0], times[-1] + .7, times=times, side=side))
                row = {'beat': bid, 'start': first, 'end': first + len(part), 'speaker': speaker, 'text': part}
                if planned and planned != speaker:
                    row['plan_speaker'] = planned         # the text's own tag or address overruled the plan
                if book.speakers.of(bid, q0) != speaker:
                    row['role'] = book.speakers.of(bid, q0)   # the voice's role ('theo_old'), drawn as its person
                book.bubbled.append(row)

    def _hear(self, shots, shot, speaker):
        """A voice from elsewhere: its speaker is not drawn; a page left with nobody keeps the listeners' page."""
        shot.figures = [f for f in shot.figures if f.key != speaker]
        if shot.figures:
            return
        i = shots.index(shot)
        before = shots[i - 1] if i else self.previous
        if before is None or before.page:
            return
        for name in ('figures', 'set', 'supports', 'props', 'sky', 'place', 'view', 'atmosphere', 'screen'):
            setattr(shot, name, copy.copy(getattr(before, name)))
        shot.figures = [f for f in shot.figures if f.key != speaker]
        shot.framing = before.framing

    def _edge(self, shot, speaker):
        """The side of the frame a heard voice comes from: away from the people on the page."""
        xs = [f.x for f in shot.figures]
        if not xs:
            return 'r'
        view = shot.view
        mean = (sum(xs) / len(xs) - view[0]) * view[2] + .5
        return 'l' if mean > .5 else 'r'


# ------------------------------------------------------------------ drawing
def draw_screen(book, overlay, piece, shown, shot, local, cam):
    """What a TV or phone shows, inside its glass: a person (a cast member) or a picture, on a lit screen."""
    _, _, box = book.stager.frame(piece.doodle, piece.x, piece.ground, piece.height, piece.mirror)
    x0, y0, x1, y1 = box
    gx0, gx1 = x0 + (x1 - x0) * .12, x1 - (x1 - x0) * .12
    gy0, gy1 = y0 + (y1 - y0) * .16, y1 - (y1 - y0) * .3
    w, h = book.size
    (sx0, sy0, _), (sx1, sy1, _) = book._to_screen(gx0, gy0, cam), book._to_screen(gx1, gy1, cam)
    sx0, sy0, sx1, sy1 = round(sx0), round(sy0), round(sx1), round(sy1)
    if sx1 - sx0 < 6 or sy1 - sy0 < 6:
        return
    glass = Image.new('RGBA', (sx1 - sx0, sy1 - sy0), (196, 222, 236, 255))
    draw = ImageDraw.Draw(glass)
    for k in range(0, glass.height, 4):                     # a home video's scan lines
        draw.line((0, k, glass.width, k), fill=(170, 200, 218, 255))
    sub = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    if shown == ['menu']:
        colours = ((229, 115, 115), (255, 202, 40), (102, 187, 106), (66, 165, 245), (171, 71, 188), (255, 138, 101))
        cols, rows = 3, 2
        tw, th = glass.width / (cols + 1), glass.height / (rows + 1.2)
        for i in range(cols * rows):
            cx, cy = (i % cols + .5) * glass.width / cols, (i // cols + .5) * glass.height / rows + 2
            draw.rounded_rectangle((cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2), max(2, tw / 8),
                                   fill=colours[i] + (255,), outline=(60, 70, 90, 255), width=max(1, round(tw / 18)))
        overlay.alpha_composite(glass, (max(0, sx0), max(0, sy0)), (max(0, -sx0), max(0, -sy0)))
        return
    stamp = next((item[6:] for item in shown if isinstance(item, str) and item.startswith('stamp:')), None)
    shown = [item for item in shown if not (isinstance(item, str) and item.startswith('stamp:'))]
    n = len(shown)
    for i, item in enumerate(shown):
        cx = gx0 + (gx1 - gx0) * (i + 1) / (n + 1)
        height = (gy1 - gy0) * .82
        if isinstance(item, str):
            book._paste(sub, item, False, cx, gy1 - (gy1 - gy0) * .06, height * .8, cam)
        else:
            doodle, mirror, _ = book._pose_doodle(item, local)
            hop = .04 * height * abs(math.sin(local * 5)) if item.pose == 'run' else 0.
            book._paste(sub, doodle, mirror, cx, gy1 - (gy1 - gy0) * .06 - hop, height, cam,
                        reference=book._reference(item))
    glass.alpha_composite(sub.crop((sx0, sy0, sx1, sy1)))
    if stamp:                                               # the camcorder's date in the corner
        size = max(8, round(glass.height * .14))
        ImageDraw.Draw(glass).text((glass.width - size * .4, glass.height - size * .4), stamp, anchor='rs',
                                   font=_font(size),
                                   fill=(255, 196, 0, 255), stroke_width=max(1, size // 10), stroke_fill=(60, 40, 0, 255))
    overlay.alpha_composite(glass, (max(0, sx0), max(0, sy0)), (max(0, -sx0), max(0, -sy0)))


def draw_hands(book, overlay, shot, cam):
    """The hands of an insert (Shot.hands): a right hand reaching in from the lower right to grip the thing."""
    w, h = book.size
    k = 2
    layer = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for piece, tone in shot.hands:
        x0, y0, x1, y1 = book.stager.frame(piece.doodle, piece.x, piece.ground, piece.height, piece.mirror)[2]
        gx, gy, _ = book._to_screen(x1 - .12 * (x1 - x0), y0 + .62 * (y1 - y0), cam)
        _, top, _ = book._to_screen(x0, y0, cam)
        _, bottom, _ = book._to_screen(x0, y1, cam)
        s = min(h / 540, max(h / 1440, .4 * (bottom - top) / 160))
        x, y, s = gx * k, gy * k, s * k
        reach = w * k + 200 * s - (x + 100 * s)
        arm = [(x + 100 * s, y + 150 * s), (x + 100 * s + reach, y + 150 * s + .3 * reach)]
        draw.line(arm, fill=INK, width=round(148 * s))          # the forearm runs on out of the frame's right side
        draw.line(arm, fill=SLEEVE + (255,), width=round(132 * s))
        _hand(draw, x, y, s, SKIN.get(tone, SKIN['tan']), 'front')
    overlay.alpha_composite(layer.resize((w, h), Image.Resampling.LANCZOS))


@lru_cache(maxsize=8)
def _font(size):
    return ink.truetype(ink.EN_HAND[0], size, 'shot label')


def _fit(lines, width, height, big, small):
    """Wrapped lines and font size so every line fits the box, as large as it can be."""
    for size in range(big, small - 1, -2):
        font = _font(size)
        out = []
        for line in lines:
            words, row = line.split(), ''
            for word in words:
                trial = (row + ' ' + word).strip()
                if font.getlength(trial) > width and row:
                    out.append(row)
                    row = word
                else:
                    row = trial
            out.append(row)
            out.append(None)                            # a gap between items
        out = out[:-1]
        if sum(size * (.6 if r is None else 1.32) for r in out) <= height:
            return out, size
    return out, small


def first_person(book, shot, local):
    """What the reader sees: the page, map or phone filling the frame, its words readable, held by two hands (J
    10/8: one behind it on the left, one in front on the right)."""
    w, h = book.size
    canvas = book.paper(w, h).copy().convert('RGBA')
    page = shot.page
    tone = SKIN.get(page.get('tone'), SKIN['tan'])
    k = 2
    layer = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if page['kind'] == 'phone':
        pw, ph = .27 * w * k, .84 * h * k
        px0, py0 = (w * k - pw) / 2, .06 * h * k
        _hand(draw, px0 + .02 * pw, py0 + .62 * ph, k * h / 720, tone, 'behind')
        _phone(draw, px0, py0, pw, ph, page, k)
        text_box = (px0 + .1 * pw, py0 + .2 * ph, px0 + .9 * pw, py0 + .72 * ph)
        _hand(draw, px0 + pw * 1.0, py0 + .72 * ph, k * h / 720, tone, 'front')
    else:
        landscape = page['kind'] == 'map'
        pw, ph = ((.66 * w, .74 * h) if landscape else (.46 * w, .9 * h))
        pw, ph = pw * k, ph * k
        px0, py0 = (w * k - pw) / 2, .04 * h * k
        _hand(draw, px0 + .01 * pw, py0 + .55 * ph, k * h / 720, tone, 'behind')
        draw.rectangle((px0 + 10 * k, py0 + 10 * k, px0 + pw + 10 * k, py0 + ph + 10 * k), fill=(0, 0, 0, 40))
        draw.rectangle((px0, py0, px0 + pw, py0 + ph), fill=PAPER, outline=INK, width=4 * k)
        if landscape:
            _map(draw, px0, py0, pw, ph, k)
            text_box = (px0 + .08 * pw, py0 + .08 * ph, px0 + .92 * pw, py0 + .3 * ph)
        else:
            for y in range(int(py0 + .12 * ph), int(py0 + ph), int(.052 * ph)):
                draw.line((px0 + 14 * k, y, px0 + pw - 14 * k, y), fill=(170, 196, 226, 255), width=k)
            text_box = (px0 + .09 * pw, py0 + .07 * ph, px0 + .91 * pw, py0 + min(.95 * ph, .8 * h * k - py0))
        _hand(draw, px0 + pw * .99, py0 + .62 * ph, k * h / 720, tone, 'front')
    lines = page.get('lines') or []
    if lines:
        x0, y0, x1, y1 = text_box
        rows, size = _fit(lines, (x1 - x0), (y1 - y0), round(.05 * h * k), round(.026 * h * k))
        font = _font(size)
        y = y0
        for row in rows:
            if row is None:
                y += size * .6
                continue
            draw.text((x0, y), row, font=font, fill=(32, 44, 92, 255))
            y += size * 1.32
    layer = layer.resize((w, h), Image.Resampling.LANCZOS)
    canvas.alpha_composite(layer)
    return canvas.convert('RGB')


def _phone(draw, x0, y0, pw, ph, page, k):
    r = .09 * pw
    draw.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), r, fill=(40, 42, 48, 255), outline=INK, width=4 * k)
    sx0, sy0, sx1, sy1 = x0 + .06 * pw, y0 + .05 * ph, x0 + .94 * pw, y0 + .95 * ph
    draw.rounded_rectangle((sx0, sy0, sx1, sy1), r * .7, fill=(236, 242, 248, 255))
    bar = .045 * ph
    full = page.get('signal') != 'none'
    for i in range(4):                                  # signal bars, top left
        bx = sx0 + .07 * pw + i * .06 * pw
        bh = bar * (i + 1) / 4
        draw.rectangle((bx, sy0 + .03 * ph + bar - bh, bx + .035 * pw, sy0 + .03 * ph + bar),
                       fill=(40, 42, 48, 255) if full else None, outline=(40, 42, 48, 255), width=k)
    if not full:
        draw.line((sx0 + .05 * pw, sy0 + .03 * ph, sx0 + .33 * pw, sy0 + .03 * ph + bar), fill=(200, 40, 40, 255),
                  width=3 * k)
        font = _font(round(.06 * ph))
        label = 'No signal'
        draw.text(((sx0 + sx1) / 2 - font.getlength(label) / 2, sy0 + .4 * ph), label, font=font,
                  fill=(60, 64, 72, 255))


def _map(draw, x0, y0, pw, ph, k):
    """A folded road map: fields, a river, roads, fold lines and a north arrow."""
    for i in range(1, 4):
        draw.line((x0 + pw * i / 4, y0, x0 + pw * i / 4, y0 + ph), fill=(214, 206, 186, 255), width=2 * k)
    draw.line((x0, y0 + ph / 2, x0 + pw, y0 + ph / 2), fill=(214, 206, 186, 255), width=2 * k)
    for fx, fy, fw, fh in ((.08, .38, .2, .18), (.62, .6, .25, .2), (.35, .7, .16, .14)):
        draw.rounded_rectangle((x0 + fx * pw, y0 + fy * ph, x0 + (fx + fw) * pw, y0 + (fy + fh) * ph), 10 * k,
                               fill=(206, 228, 180, 255))
    river = [(x0 + pw * (.0 + .1 * i), y0 + ph * (.55 + .12 * math.sin(i * .9))) for i in range(11)]
    draw.line(river, fill=(120, 170, 220, 255), width=10 * k, joint='curve')
    road = [(x0 + pw * (.05 + .09 * i), y0 + ph * (.9 - .07 * i - .05 * math.sin(i * 1.3))) for i in range(11)]
    draw.line(road, fill=(222, 120, 60, 255), width=8 * k, joint='curve')
    draw.line([(x0 + pw * .5, y0 + ph * .98), (x0 + pw * .55, y0 + ph * .55), (x0 + pw * .7, y0 + ph * .35),
               (x0 + pw * .72, y0 + ph * .05)], fill=(90, 90, 90, 255), width=6 * k, joint='curve')
    cx, cy, r = x0 + pw * .9, y0 + ph * .8, .06 * ph
    draw.polygon([(cx, cy - r), (cx - r * .5, cy + r * .6), (cx + r * .5, cy + r * .6)], fill=(200, 50, 50, 255))
    font = _font(round(r * .9))
    draw.text((cx - font.getlength('N') / 2, cy + r * .6), 'N', font=font, fill=INK)


def _hand(draw, x, y, s, tone, kind):
    """A hand at the paper's edge (x, y: where it grips, in layer pixels; s: scale): 'behind' shows the fingers
    curling round the left edge from behind, 'front' the right hand over the right edge, its thumb on the page."""
    ink_w = max(2, round(4 * s))
    skin = tone + (255,)
    if kind == 'behind':
        draw.rounded_rectangle((x - 150 * s, y + 40 * s, x - 40 * s, y + 230 * s), 30 * s, fill=SLEEVE + (255,),
                               outline=INK, width=ink_w)
        draw.ellipse((x - 120 * s, y - 60 * s, x + 30 * s, y + 90 * s), fill=skin, outline=INK, width=ink_w)
        for i in range(4):                           # fingertips curling round onto the page's back
            fy = y - 50 * s + i * 34 * s
            draw.rounded_rectangle((x - 10 * s, fy, x + 46 * s, fy + 30 * s), 15 * s, fill=skin, outline=INK,
                                   width=ink_w)
        return
    draw.rounded_rectangle((x + 30 * s, y + 50 * s, x + 170 * s, y + 260 * s), 30 * s, fill=SLEEVE + (255,),
                           outline=INK, width=ink_w)
    draw.ellipse((x - 40 * s, y - 50 * s, x + 120 * s, y + 110 * s), fill=skin, outline=INK, width=ink_w)
    draw.rounded_rectangle((x - 84 * s, y - 30 * s, x + 10 * s, y + 6 * s), 18 * s, fill=skin, outline=INK,
                           width=ink_w)                # the thumb pressed on the page

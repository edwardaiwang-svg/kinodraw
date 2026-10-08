"""Figures a script states, as data cards (engine/data_cards.py draws them).

When a narrated sentence gives a price, a percentage, an amount, a count, a time or a date, or compares figures
("from 9,800 to 12,400", "$3.50 each", "up 18%", "3 times more"), the video shows that figure as a card with the
script's own text ("$4.2M" stays "$4.2M", "7 a.m." stays "7 a.m.") while the words are said. Read from the script on
the client, so any plan (saved plans included) gets them.

Kinds: ``change`` (from X to Y, two bars and the stated change), ``bars`` (two or more values compared), ``event``
(when and where: a day or date and a time), ``price`` (a price tag), ``stat`` (several figures, one row each),
``counter`` (a count that counts up to its value) and ``number`` (one headline figure with its unit and label).

Never a figure: numbers in code or a formula (those beats have their own boards), a year on its own ("built in 1958",
"Class of 2031"), a number in a name ("Route 9", "Q3", "Windows 11", "Tip 1"), a number before a hyphen ("6-digit",
"two-step"), contact details (phone, extension, email, web address), and number words in idioms ("one day", "a couple
of"): spelled-out numbers count only as a percentage, an amount of money or "N times more".
English only (the readings are English word lists); other languages get no cards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NUM = r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?'
SCALE = r'(?:\s?(?:thousand|million|billion|trillion)\b|[kKmMbB](?:n)?\b)'
SPELLED = (r'(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ](?:one|two|three|four|five|six|'
           r'seven|eight|nine))?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|'
           r'fifteen|sixteen|seventeen|eighteen|nineteen|a hundred|one hundred|a thousand|one thousand)')
MONTHS = (r'(?:January|February|March|April|May|June|July|August|September|October|November|December|'
          r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)')
DAYS = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?'
DAY_ABBR = r'(?:Mon|Tues|Tue|Wed|Thurs|Thu|Fri|Sat|Sun)'
UNITS = {'percent', 'tons', 'ton', 'tonnes', 'kg', 'kilograms', 'grams', 'g', 'lbs', 'lb', 'pounds', 'ounces', 'oz',
         'miles', 'mile', 'km', 'kilometers', 'kilometres', 'meters', 'metres', 'm', 'feet', 'ft', 'inches', 'in',
         'gallons', 'liters', 'litres', 'cups', 'mph', 'kph', 'hours', 'hour', 'hrs', 'hr', 'minutes', 'minute',
         'mins', 'min', 'seconds', 'second', 'secs', 'sec', 'days', 'day', 'weeks', 'week', 'months', 'month',
         'years', 'year', 'yrs', 'yr', 'times', 'people', 'users', 'customers', 'members', 'households', 'homes',
         'cars', 'trucks', 'students', 'kids', 'calories', 'steps', 'points', 'votes', 'acres', 'degrees', 'mg',
         'ml', 'gb', 'mb', 'tb', 'kwh', 'watts', 'volts'}
# Words that end a figure's label (the noun phrase after it).
STOP = {'and', 'but', 'so', 'or', 'for', 'from', 'in', 'at', 'on', 'by', 'with', 'to', 'this', 'that', 'which',
        'who', 'last', 'until', 'than', 'because', 'if', 'when', 'while', 'into', 'out', 'up', 'down', 'is', 'are',
        'was', 'were', 'it', 'its', "it's", 'we', 'you', 'they', 'he', 'she', 'i', 'the', 'like', 'per', 'every',
        'each', 'over', 'after', 'before', 'since', 'as', 'about', 'just', 'only', 'vs', 'vs.', 'versus',
        'compared', 'instead', 'used', 'has', 'have', 'had'}
QUALIFIERS = re.compile(r"(?:about|around|roughly|nearly|almost|over|under|more than|less than|fewer than|at least|"
                        r"up to|only|just|approximately|close to)\s*$", re.I)
ABBREV = {'a.m', 'p.m', 'am', 'pm', 'mr', 'mrs', 'ms', 'dr', 'st', 'rd', 'ave', 'blvd', 'dept', 'ext', 'no', 'vs',
          'etc', 'approx', 'est', 'inc', 'co', 'ltd', 'jr', 'sr', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug',
          'sep', 'sept', 'oct', 'nov', 'dec', 'mon', 'tue', 'tues', 'wed', 'thu', 'thurs', 'fri', 'sat', 'sun',
          'min', 'hr', 'hrs', 'yrs', 'oz', 'lb', 'lbs', 'ft', 'mt', 'u.s', 'e.g', 'i.e'}

TIME = re.compile(r'(?<![\w$])(?:(?P<h>\d{1,2})(?::(?P<m>[0-5]\d))?\s?(?P<ap>[aApP]\.?\s?[mM]\b\.?)|'
                  r'(?P<clock>\d{1,2}:[0-5]\d)(?!\d))')
DATE = re.compile(r'\b(?:' + MONTHS + r'\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?(?!\d)|'
                  r'\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?' + MONTHS + r'\b\.?(?:,?\s+\d{4})?|'
                  r'\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\b)')
MONTH_ONLY = re.compile(r'\b(?i:(?P<p>since|until|by|this|next|last|through|every|early|late|mid-?)|in|on|from)\s+'
                        r'(?P<m>(?:January|February|March|April|May|June|July|August|September|October|November|'
                        r'December))\b(?!\s+\d)')
DAY = re.compile(r'(?:\b(?:every|this|next|on|each)\s+)?\b' + DAYS + r'\b', re.I)
DAY_SHORT = re.compile(r'\b' + DAY_ABBR + r'\b\.?,?', re.I)
MONEY = re.compile(r'(?<![\w.])(?P<cur>[$€£¥₹])\s?(?P<n>' + NUM + r')(?P<scale>' + SCALE + r')?|'
                   r'(?<![\w.,])(?P<n2>' + NUM + r')(?P<scale2>' + SCALE + r')?\s(?:dollars|bucks|euros|cents)\b|'
                   r'\b(?P<w>' + SPELLED + r')\s(?:dollars|bucks|euros|cents)\b', re.I)
PERCENT = re.compile(r'(?<![\w.,])(?P<n>' + NUM + r')\s?(?:%|percent\b|per cent\b)|\b' + SPELLED +
                     r'\s(?:percent|per cent)\b', re.I)
MULTIPLE = re.compile(r'\b(?:(?:' + NUM + r'|' + SPELLED + r')\s?(?:times|x|×)\s+(?:more|less|faster|slower|'
                      r'bigger|smaller|higher|lower|as|longer|cheaper|larger|the)\b|twice\s+as\b|'
                      r'(?:double|triple|quadruple)\s+the\b)', re.I)
CODE = re.compile(r'(?<![\d,.])\d{3}[ -]\d{3}(?![\d,])|(?<![\d,.])\d{4,8}(?![\d,.])')
CODE_WORDS = re.compile(r'\b(?:code|pin|passcode|otp|verification|one-time|password)\b', re.I)
COUNT = re.compile(r'(?<![\w$€£¥₹.,#/:-])(?P<n>' + NUM + r')(?P<ord>st|nd|rd|th)?(?P<scale>' + SCALE + r')?'
                   r'(?![\w%/:-])(?!\.\d)', re.I)
CONTACT = re.compile(r'\S+@\S+|(?:https?://|www\.)\S+|\b\S+\.(?:com|org|net|io|edu|gov|co)\b\S*|'
                     r'\b(?:ext|extension|x)\.?\s*\d+|\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}|\b\d{3}[ .-]\d{4}\b|'
                     r'#\s?\d+|\bNo\.\s?\d+', re.I)
WORD_AFTER = re.compile(r"[\s,]*([A-Za-z][\w'’-]*)")
PLACE = re.compile(r"\b(?:corner of [A-Z][\w'’.]*(?:\s[A-Z][\w'’.]*)*\s(?:and|&)\s[A-Z][\w'’.]*(?:\s[A-Z][\w'’.]*)*|"
                   r"(?:at|in)\s+(?:the\s+)?(?P<name>(?:[A-Z][\w'’.]*\s?){1,5}))")
UP = re.compile(r'\b(?:up|rose|risen|grew|grown|gained|increased|climbed|jumped|more|higher|added)\b', re.I)
DOWN = re.compile(r'\b(?:down|fell|fallen|dropped|decreased|declined|shrank|lost|cut|less|lower|fewer)\b', re.I)


@dataclass
class Figure:
    start: int
    end: int
    text: str
    family: str              # money | percent | count | time | date | day | code | multiple
    value: float | None = None
    unit: str = ''           # a unit word right after a count ("tons", "households")


@dataclass
class Card:
    kind: str                # change | bars | event | price | stat | counter | number
    start: int               # char offsets in the beat's display text: the first figure ...
    end: int                 # ... and the end of its sentence
    value: str = ''          # number/counter/price: the figure as written ("$3.50", "3,100 tons")
    label: str = ''          # its words ("each", "of food scraps")
    qualifier: str = ''      # "about", "up to" ... as written
    items: list = field(default_factory=list)    # change/bars: [(value text, label, number)]
    delta: str = ''          # change: the stated change ("18%")
    direction: str = ''      # up | down | ''
    rows: list = field(default_factory=list)     # stat: rows of exact text; event: when lines
    where: str = ''          # event: the place


def _number(text: str) -> float | None:
    m = re.search(NUM, text)
    if not m:
        return None
    value = float(m.group().replace(',', ''))
    scale = re.search(r'(thousand|million|billion|trillion|\d\s?[kKmMbB])\b', text[m.end() - 1:])
    if scale:
        s = scale.group(1)[-1].lower() if scale.group(1)[0].isdigit() else scale.group(1).lower()
        value *= {'k': 1e3, 'thousand': 1e3, 'm': 1e6, 'million': 1e6, 'b': 1e9, 'billion': 1e9,
                  'trillion': 1e12}.get(s, 1)
    return value


def sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence of ``text``: ends at . ! ? before a capital or the end, never inside "7 a.m.",
    "Oct." or "4.2"."""
    out, start = [], 0
    for m in re.finditer(r'[.!?]+["”’)]*(?=\s+\S|\s*$)', text):
        word = re.search(r'([\w.]+)$', text[start:m.start()])
        token = (word.group(1) if word else '').lower().rstrip('.')
        rest = text[m.end():].lstrip()
        if m.group()[0] == '.' and (token in ABBREV or len(token) == 1) and rest[:1].isalnum() and \
                not rest[:1].isupper():
            continue
        if m.group()[0] == '.' and token in ('a.m', 'p.m', 'am', 'pm') and rest[:1].isupper() and \
                re.match(r'(?:' + DAYS + r'|' + DAY_ABBR + r'|' + MONTHS + r')\b', rest):
            continue                              # "at 6 a.m. Tues., Oct. 14": one sentence
        if m.group()[0] == '.' and token in ABBREV - {'a.m', 'p.m', 'am', 'pm'} and rest[:1].isalnum():
            continue
        out.append((start, m.end()))
        start = m.end()
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text) and text[start:].strip():
        out.append((start, len(text)))
    return out


def _overlaps(span, taken):
    return any(span[0] < b and a < span[1] for a, b in taken)


def _named(text: str, start: int) -> bool:
    """The number at ``start`` is part of a name: "Route 9", "Windows 11", "Tip 1", "Q3", "Room 214"."""
    before = text[:start]
    if before[-1:].isalpha():                      # "Q3", "H2O"
        return True
    m = re.search(r"([A-Za-z][\w'’]*)\s$", before)
    if not m:
        return False
    word = m.group(1)
    if not re.search(r'[A-Z]', word):
        return False
    if re.fullmatch(MONTHS + r'|' + DAYS + r'|' + DAY_ABBR, word):
        return False
    sentence_start = not before[:m.start()].strip() or re.search(r'[.!?:;]\s*$|^\W*$', before[:m.start()])
    return not sentence_start or word.lower() in ('route', 'step', 'tip', 'room', 'level', 'chapter', 'part',
                                                    'version', 'season', 'episode', 'gate', 'floor', 'unit')


def figures(text: str) -> list[Figure]:
    """Every figure a sentence states, in order (see the module docstring for what never is one)."""
    taken = [m.span() for m in CONTACT.finditer(text)]
    # Inline code and markdown emphasis stay; a hyphen after a number makes it an adjective ("6-digit").
    found: list[Figure] = []

    def add(span, family, value=None, unit=''):
        if _overlaps(span, taken):
            return
        taken.append(span)
        found.append(Figure(span[0], span[1], text[span[0]:span[1]], family, value, unit))

    for m in DATE.finditer(text):
        add(m.span(), 'date')
    for m in MONTH_ONLY.finditer(text):
        add((m.start('p') if m.group('p') else m.start('m'), m.end('m')), 'date')
    for m in TIME.finditer(text):
        if m.group('clock') and not re.search(r'\b(?:at|by|from|until|till|before|after|around)\s+$',
                                              text[:m.start()], re.I):
            continue                               # "1:1", a ratio or a score
        add((m.start(), m.end() - (1 if m.group().endswith(' ') else 0)), 'time')
    for m in DAY.finditer(text):
        add(m.span(), 'day')
    times = [f for f in found if f.family in ('time', 'date')]
    for m in DAY_SHORT.finditer(text):
        # "Sat", "sun", "wed" are words too: an abbreviated day only right beside a time or a date
        near = any(abs(f.start - m.end()) <= 2 or abs(m.start() - f.end) <= 2 for f in times)
        if near:
            add((m.start(), m.start() + len(m.group().rstrip(', '))), 'day')
    for m in MULTIPLE.finditer(text):
        add(m.span(), 'multiple')
    for m in MONEY.finditer(text):
        add(m.span(), 'money', _number(m.group()))
    for m in PERCENT.finditer(text):
        add(m.span(), 'percent', _number(m.group()))
    for m in CODE.finditer(text):
        if CODE_WORDS.search(text[max(0, m.start() - 60):m.start()]) and not _named(text, m.start()):
            add(m.span(), 'code')
    for m in COUNT.finditer(text):
        n = m.group('n')
        if text[m.end():m.end() + 1] == '-' or (m.start() and text[m.start() - 1] == '-'):
            continue                               # "6-digit", "2-for-1"
        if re.fullmatch(r'(?:1[89]|20)\d\d', n) and not m.group('scale'):
            continue                               # a year on its own, or one used as a name
        if re.match(r'\s*\d', text[m.end():]):
            continue                               # one group of a longer number ("482 913" without "code")
        word = WORD_AFTER.match(text, m.end())
        unit = word.group(1).lower() if word and word.start(1) - m.end() <= 1 and _unit(word.group(1)) else ''
        if not unit and _named(text, m.start()):
            continue
        end = word.end(1) if unit else m.end()
        add((m.start(), end), 'count', _number(text[m.start():m.end()]), unit)
    found.sort(key=lambda f: f.start)
    return found


def _unit(word: str) -> bool:
    """A word that counts what the number counts: a unit ("tons", "mph") or a plural noun ("households")."""
    low = word.lower()
    return low in UNITS or (word.islower() and len(low) > 3 and low.endswith('s') and not low.endswith('ss') and
                            low not in STOP and low not in ('this', 'thus', 'plus', 'minus', 'always', 'perhaps'))


def _words(text: str) -> list[re.Match]:
    return list(re.finditer(r"[\w$€£¥₹%][\w'’.,%-]*", text))


def _label(text: str, start: int, limit: int = 4) -> str:
    """The noun phrase right after a figure, in the script's words ("tons of food scraps" -> "of food scraps")."""
    rest = text[start:]
    stop = re.search(r'[,.;:!?—–()\n]|\s-\s', rest)
    rest = rest[:stop.start()] if stop else rest
    out = []
    for w in rest.split():
        bare = w.strip('*_`"“”').lower()
        if bare in STOP and not (bare == 'of' or (out and bare in ('a', 'an'))) or re.search(r'\d', bare) or \
                (out and bare.endswith('ed') and len(bare) > 4):
            break
        out.append(w.strip('*_`"“”'))
        if len(out) >= limit:
            break
    while out and out[-1].lower() in ('of', 'a', 'an', 'the'):
        out.pop()
    if out and out[0].lower() == 'of':
        out = out[1:]
    return ' '.join(out)


def _qualifier(text: str, start: int) -> str:
    m = QUALIFIERS.search(text[max(0, start - 16):start])
    return m.group().strip() if m else ''


def _shown(f: Figure) -> str:
    return re.sub(r'[`*_]', '', f.text).strip()


def _change(text, figs, a, b):
    """from X to Y / Y, up N% from X / X ... up from Y: (old, new, delta figure) or None."""
    values = [f for f in figs if f.family in ('money', 'percent', 'count')]
    for k, old in enumerate(values):
        lead = text[max(a, old.start - 6):old.start].lower()
        if not re.search(r'\bfrom\s+$', lead):
            continue
        after = [f for f in values[k + 1:] if f.family == old.family]
        to = next((f for f in after if re.fullmatch(r"\s+(?:[\w'’-]+\s+){0,2}?to\s+", text[old.end:f.start])), None)
        if to is not None:
            delta = next((f for f in values if f.family == 'percent' and f not in (old, to) and
                          re.search(r'\b(?:up|down|by)\s+$', text[max(a, f.start - 6):f.start], re.I)), None)
            return old, to, delta
        # "Y, up 18% from X" / "Y, up from X": the new value is the nearest figure of its kind before
        before = [f for f in values[:k] if f.family == old.family and f.family != 'percent' or
                  f.family == old.family == 'percent']
        if before and re.search(r'\b(?:up|down|rose|fell|grew|dropped)\b', text[before[-1].end:old.start], re.I):
            delta = next((f for f in values if f.family == 'percent' and before[-1].end <= f.start < old.start
                          and f is not old), None)
            return old, before[-1], delta
    return None


def _direction(text, old=None, new=None):
    if old is not None and new is not None and old.value is not None and new.value is not None \
            and old.value != new.value:
        return 'up' if new.value > old.value else 'down'
    if DOWN.search(text) and not UP.search(text):
        return 'down'
    if UP.search(text):
        return 'up'
    return ''


def _rows(text, figs):
    """Figures joined only by short words ("5% of $1,000 is $50") make one row of exact script text."""
    rows, run = [], []
    for f in figs:
        if run and re.fullmatch(r"\s*(?:of|is|are|=|x|×|times|per|to|plus|minus|\+|-|equals)\s*",
                                text[run[-1].end:f.start], re.I):
            run.append(f)
            continue
        if run:
            rows.append(run)
        run = [f]
    if run:
        rows.append(run)
    out = []
    for run in rows:
        piece = re.sub(r'[`*_]', '', text[run[0].start:run[-1].end]).strip()
        label = '' if run[-1].unit else _label(text, run[-1].end, 3)
        out.append((piece + (' ' + label if label else '')).strip())
    return out


def _sentence_card(text: str, a: int, b: int) -> Card | None:
    figs = [f for f in figures(text) if a <= f.start < b]
    if not figs:
        return None
    sentence = text[a:b]
    first = figs[0].start
    when = [f for f in figs if f.family in ('time', 'date', 'day')]
    if when:
        lines, rest = [], []
        for f in when:
            words = _shown(f)
            if f.family == 'day' and words[:1].islower() and not re.match(r'(?:every|this|next|on|each)\b', words):
                words = words[:1].upper() + words[1:]
            (lines if f.family != 'time' else rest).append(words[:1].upper() + words[1:])
        place = PLACE.search(sentence)
        where = ''
        if place:
            name = (place.group('name') or place.group()).strip(' .,')
            if not re.match(r'(?:' + MONTHS + r'|' + DAYS + r'|' + DAY_ABBR + r')\b', name) and \
                    not re.match(r'\d', name):
                where = name[:1].upper() + name[1:]
        return Card('event', first, b, rows=[' · '.join(lines)] * bool(lines) + [' · '.join(rest)] * bool(rest),
                    where=where)
    change = _change(text, figs, a, b)
    if change:
        old, new, delta = change
        when = re.match(r"[\s,]*(?:at\s+|in\s+)?((?:this time |the same time )?last \w+|an? \w+ ago|\d{4}|"
                        r"(?:the )?(?:previous|prior) \w+)", text[old.end:b], re.I)
        old_label = when.group(1) if when else 'before'
        unit = new.unit or old.unit
        return Card('change', first, b, label=_label(text, new.end, 3) if not new.unit else unit,
                    items=[(_shown(old), old_label, old.value), (_shown(new), 'now', new.value)],
                    delta=_shown(delta) if delta else '', direction=_direction(sentence, old, new))
    values = [f for f in figs if f.family in ('money', 'percent', 'count') and f.value is not None]
    families = {f.family for f in values}
    compare = re.search(r'\b(?:vs\.?|versus|compared (?:to|with)|than|instead of|against)\b', sentence, re.I)
    if len(values) >= 2 and len(families) == 1 and compare and len(values) <= 5:
        return Card('bars', first, b, items=[(_shown(f), f.unit or _label(text, f.end, 3), f.value)
                                              for f in values])
    multiple = next((f for f in figs if f.family == 'multiple'), None)
    if multiple is not None and len(figs) == 1:
        words = _shown(multiple)
        head = re.match(r'(.*?)\s+(?:the|as|more|less|faster|slower|bigger|smaller|higher|lower|longer|cheaper|'
                        r'larger)\b', words, re.I)
        return Card('number', first, b, value=head.group(1) if head else words,
                    label=(words[head.end(1):].strip() + ' ' + _label(text, multiple.end, 3)).strip() if head else
                    _label(text, multiple.end, 3), direction=_direction(words))
    if len(figs) >= 2:
        rows = _rows(text, figs)
        if len(rows) >= 2:
            return Card('stat', first, b, rows=rows[:5])
    f = figs[0]
    qualifier = _qualifier(text, f.start)
    if f.family == 'code':
        return Card('number', first, b, value=_shown(f), label=_code_label(text, f.start))
    retail = f.value is not None and f.value < 1000 and not re.search(r'[kKmMbB]\b|illion', f.text)
    if f.family == 'money' and retail and (re.match(r'\s*(?:each|apiece|a piece|per\b|/|an? (?:month|week|year|'
                                                    r'day|night|hour|person|pound|kilo|dozen|piece|ticket|seat)\b)',
                                                    text[f.end:], re.I) or
                                           re.search(r'\b(?:costs?|price[ds]?|priced at|sells? for|pay|just|only)\s+'
                                                     r'(?:about\s+|around\s+|just\s+|only\s+)?$',
                                                     text[max(a, f.start - 24):f.start], re.I)):
        unit = re.match(r'\s*(each|apiece|a piece|per \w+|an? \w+|/\s?\w+)\b', text[f.end:])
        return Card('price', first, b, value=_shown(f), label=unit.group(1) if unit else '', qualifier=qualifier)
    if f.family == 'count' and f.value is not None and f.value < 10 and f.unit not in UNITS:
        return None                                # "2 of them", "2 friends": too small to be a headline
    label = _label(text, f.end, 4) if not f.unit else _label(text, f.end, 4)
    value = _shown(f)
    direction = ''
    if f.family == 'percent':
        tail = text[f.end:min(b, f.end + 24)]
        lead = text[max(a, f.start - 12):f.start]
        direction = 'down' if re.search(r'\b(?:less|lower|fewer|down|off)\b', tail + ' ' + lead, re.I) else \
            'up' if re.search(r'\b(?:more|higher|up)\b', tail + ' ' + lead, re.I) else ''
        more = re.match(r'\s*(more|less|fewer|higher|lower)(\s+than\s+[\w\s]+?)?(?=[,.;!?]|$)', tail)
        if more:
            label = (more.group(1) + (more.group(2) or '')).strip()
    if qualifier.lower().startswith('up to'):
        direction = ''                             # a ceiling, not a rise
    counter = f.family == 'count' and f.value is not None and f.value >= 10 and f.value == int(f.value) \
        and not re.search(r'(st|nd|rd|th)$', f.text)
    return Card('counter' if counter else 'number', first, b, value=value, label=label, qualifier=qualifier,
                direction=direction)


def _code_label(text, start):
    m = CODE_WORDS.search(text[max(0, start - 60):start])
    return m.group().lower() if m else ''


def cards(display: str, lang: str = 'en') -> list[Card]:
    """One card per sentence of a beat's display text that states a figure (none for code or formula beats: the
    caller skips those, see ``beat_cards``)."""
    if lang != 'en' or not re.search(r'\d|%|\$|€|£|percent|dollars|bucks|times|twice|' + MONTHS + '|' + DAYS,
                                     display, re.I):
        return []
    out = []
    for a, b in sentences(display):
        card = _sentence_card(display, a, b)
        if card is not None:
            out.append(card)
    return out


def beat_cards(beat: dict, lang: str) -> list[Card]:
    """The cards of one storyboard beat: narration only, never a code block, a formula or a title."""
    if beat.get('kind', 'narration') != 'narration' or (beat.get('markup') or {}).get('kind') in ('code', 'math'):
        return []
    display = beat.get('display')
    text = display.get(lang, '') if isinstance(display, dict) else str(display or '')
    from .markup import code_block, math_line
    if code_block(text) or math_line(text):
        return []
    return cards(text, lang)


def spoken_offset(display: str, spoken: str, pos: int, lang: str) -> int:
    """The spoken-text offset of display character ``pos`` (exact where the spoken text is the display's own
    reading, else clause by clause)."""
    from .numbers import normalize
    reading = normalize(display, lang)
    if reading.spoken == spoken:
        return min(reading.to_spoken(pos), max(0, len(spoken) - 1))
    from .director.v3.arc import spoken_offset as by_clause
    return by_clause(display, spoken, pos)

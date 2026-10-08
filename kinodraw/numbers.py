"""Display text -> spoken text: numbers become words, nothing else changes.

Only number tokens are rewritten, so clause punctuation (which drives caption
cues) is identical in both strings. Every rewrite is recorded as a span so a
position in the display text can be mapped to the spoken text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import cn2an
from num2words import num2words

from . import lexicon

NUM = r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?'


@dataclass
class Normalized:
    display: str
    spoken: str
    spans: list = field(default_factory=list)      # (display_start, display_end, spoken_start, spoken_end)

    def to_spoken(self, pos: int) -> int:
        """Spoken-text offset of display offset ``pos`` (start of a rewritten token maps to its start)."""
        shift = 0
        for d0, d1, s0, s1 in self.spans:
            if pos < d0:
                break
            if pos < d1:
                return s0
            shift = s1 - d1
        return pos + shift

    def find(self, phrase: str) -> str | None:
        """The spoken form of a display substring (None when it is not in the display text)."""
        i = self.display.find(phrase)
        if i < 0:
            return None
        return self.spoken[self.to_spoken(i):self.to_spoken(i + len(phrase)) if i + len(phrase) < len(self.display)
                           else len(self.spoken)].strip()


def _latin(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _rewrite(text: str, pattern: re.Pattern, speak, fixed=()) -> Normalized:
    """``fixed``: (start, end, words) rewrites found beforehand (codes); the pattern runs on the text between them."""
    found, pos = [], 0
    for a, b, said in sorted(fixed) + [(len(text), len(text), None)]:
        found += [(m.start(), m.end(), m) for m in pattern.finditer(text, pos, a)]
        if said is not None:
            found.append((a, b, said))
        pos = b
    out, spans, last = [], [], 0
    for start, end, m in found:
        words = m if isinstance(m, str) else speak(m)
        if words is None:
            continue
        if _latin(text[start - 1:start]) and _latin(words[:1]):     # keep words apart: B2B -> B two B
            words = ' ' + words
        if _latin(text[end:end + 1]) and _latin(words[-1:]):
            words += ' '
        out.append(text[last:start])
        s0 = sum(map(len, out))
        out.append(words)
        spans.append((start, end, s0, s0 + len(words)))
        last = end
    out.append(text[last:])
    return Normalized(text, ''.join(out), spans)


# ============================================================== English
MONTHS = {m[:3].lower(): m for m in ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                     'September', 'October', 'November', 'December')}
SCALES = {'k': 'thousand', 'thousand': 'thousand', 'm': 'million', 'mn': 'million', 'mm': 'million',
          'million': 'million', 'b': 'billion', 'bn': 'billion', 'billion': 'billion', 't': 'trillion',
          'tn': 'trillion', 'trillion': 'trillion'}
CURRENCIES = {'US$': ('dollar', 'dollars'), '$': ('dollar', 'dollars'), '€': ('euro', 'euros'),
              '£': ('pound', 'pounds'), '¥': ('yen', 'yen'), '₹': ('rupee', 'rupees')}
# Units after a number, from the abbreviation lexicon (lexicon.UNITS: singular and plural): "2 ft" two feet, "1 ft" one
# foot, "850 sq ft" eight hundred fifty square feet, "3BR" three bedrooms.
UNITS = {k: plural for k, (_, plural) in lexicon.UNITS.items()}
FRACTIONS = {'1/2': 'one half', '1/3': 'one third', '2/3': 'two thirds', '1/4': 'one quarter',
             '3/4': 'three quarters', '1/5': 'one fifth', '1/10': 'one tenth'}
# A fraction before a noun reads as a cook or a teacher says it: "1/2 cup" is "half a cup", "1 1/2 cups" is
# "one and a half cups". (phrase before a noun, phrase after a whole number)
FRACTION_WORDS = {'1/2': ('half a', 'a half'), '1/3': ('a third of a', 'a third'),
                  '2/3': ('two thirds of a', 'two thirds'), '1/4': ('a quarter', 'a quarter'),
                  '3/4': ('three quarters of a', 'three quarters'), '1/8': ('an eighth of a', 'an eighth'),
                  '3/8': ('three eighths of a', 'three eighths'), '5/8': ('five eighths of a', 'five eighths'),
                  '7/8': ('seven eighths of a', 'seven eighths'), '1/5': ('a fifth of a', 'a fifth')}
VULGAR = {'½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8',
          '⅞': '7/8', '⅕': '1/5'}
# A four-digit number before one of these is a count ("1969 people"), not a year ("in 1969").
NOT_PLURAL = {'was', 'is', 'has', 'as', 'this', 'its', 'his', 'us', 'thus', 'plus', 'yes', 'less', 'across',
              'always', 'sometimes', 'perhaps', 'towards'}
COUNT_NOUNS = {'people', 'children', 'men', 'women', 'feet', 'teeth', 'mice', 'geese', 'sheep', 'fish', 'deer',
               'staff', 'personnel', 'cattle', 'police'}

_cur = '|'.join(re.escape(c) for c in CURRENCIES)
_scale = r'trillion|billion|million|thousand|tn|bn|mn|mm|[kmbt]'
_month = (r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December'
          r'|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?')
_unit = '|'.join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
_vulgar = '[' + ''.join(VULGAR) + ']'
_frac = r'[1-9]/[2-8](?!\d)'
_ampm = r'(?P<{0}>[aApP])(?:\.[mM]\.?|[mM](?![\w-]))'          # a.m., am, AM (a.m.'s period goes with it)
_ampm1 = r'(?P<{0}>[aApP])(?:\.[mM]\.?|[mM](?!\w))'              # the first time of a range: "9am-5pm"
# A unit's abbreviation period goes with it when the sentence runs on ("3 ft. away", "2 in. thick"): the voice never
# stops there, and captions.clause_marks does not break the caption there either.
_udot = r'(?:\.(?=[ \t]+[a-z(]|,))?'
# Addresses people read out: an email, a web address, a phone number, a hashtag. Each is said the way an announcer
# reads it ("hello at pipewise bayside dot com", "seven oh seven, five five five, ...") and shown as written.
TLDS = ('com|org|net|edu|gov|mil|int|io|co|us|uk|ca|au|nz|ie|de|fr|es|nl|eu|jp|cn|br|mx|app|dev|ai|tv|fm|info|biz|'
        'example|test|ly|gg|xyz|shop|store|site|online|tech|news|blog|church|school|health|community|city|town|'
        'travel|games|page|link|live|life|art|design|studio|world|email|org|coop|museum|social|events|club|party')
_email = r'(?P<email>(?<![\w.+%-])[A-Za-z0-9][A-Za-z0-9._%+-]*@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?![\w-]))'
_url = (r'(?P<url>(?:https?://|www\.)[^\s<>"“”‘’]*[^\s<>"“”‘’.,;:!?)\]]'
        r'|(?<![\w@.-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?i:' + TLDS + r')(?![\w-])'
        r'(?:/(?:[^\s<>"“”‘’]*[^\s<>"“”‘’.,;:!?)\]])?)?)')
_phone = (r'(?P<phone>(?<![\w+$#.,/-])(?:\+?1[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-]|[.,]\d)'
          r'|\+\d{1,3}(?:[ .-]\(?\d{1,4}\)?){2,5}(?![\w-]|[.,]\d)'
          r'|(?<![\w+$#.,/-])\d{3}-\d{4}(?![\w-]|[.,]\d))')
_ext = r'(?P<extw>\b(?:[Ee]xt|EXT)\.?|\b[Ee]xtension)[ \t]?(?P<ext>\d{1,6})(?!\d)'
_tag = r'(?<![\w&#])#(?P<tag>[A-Za-z][A-Za-z0-9_]*[A-Za-z0-9]|[A-Za-z])'
# A version: "v7", "v2.1", "V2.1.3" (a capital V only with a point: "V8" is an engine) said "version two point one".
_ver = r'(?<![\w.])(?:v(?P<ver>\d+(?:\.\d+)*)|V(?P<verc>\d+(?:\.\d+)+))(?![\w-]|\.\d)'
# A year straight after "c." or "ca." (circa) with no space: "c.1900", "ca.1850s".
_circa = r'(?<=\b[cC]\.)|(?<=\b[cC]a\.)'
EN_PATTERN = re.compile(
    rf'{_email}|{_url}|{_phone}|{_ext}|{_tag}|{_ver}'
    rf'|(?P<tr1>\d{{1,2}})(?::(?P<trm1>\d{{2}}))?\s?(?:{_ampm1.format("tra1")})?\s?[–-]\s?'
    rf'(?P<tr2>\d{{1,2}})(?::(?P<trm2>\d{{2}}))?\s?{_ampm.format("tra2")}'
    rf'|(?P<inch>{NUM})\s?in\.(?=[ \t]+[a-z(]|,)'
    rf'|(?<![\d/.])(?P<dm>\d{{1,2}})/(?P<dd>\d{{1,2}})(?:/(?P<dy>\d{{4}}|\d{{2}})|(?!\s?(?:{_unit})(?![A-Za-z])))(?![\d/]|[.,]\d)'
    rf'|'
    rf'(?P<mixw>\d+)(?:\s+(?P<mixf>{_frac})|\s?(?P<mixv>{_vulgar}))(?:\s?(?P<munit>{_unit})(?![A-Za-z]){_udot})?'
    rf'|(?P<vul>{_vulgar})(?:\s?(?P<vunit>{_unit})(?![A-Za-z]){_udot})?'
    rf'|(?P<cur>{_cur})\s?(?P<camt>{NUM})(?:\s?(?P<cscale>(?i:{_scale}))\b)?'      # $4.2M, $12K, $1.5 bn
    rf'|(?P<ra>{NUM})\s?(?:-|–|to)\s?(?P<rb>{NUM})\s?(?P<rpct>%)'
    rf'|(?P<pct>-?(?:{NUM}))\s?%'
    rf'|(?P<month>{_month})\s(?P<day>\d{{1,2}})(?!\d|,\d)(?:st|nd|rd|th)?(?:\s?[–-]\s?(?P<day2>\d{{1,2}})(?!\d|,\d)(?:st|nd|rd|th)?)?'
    rf'|(?P<h>\d{{1,2}}):(?P<mi>\d{{2}})(?:\s?{_ampm.format("ampm")})?'
    rf'|(?P<hh>\d{{1,2}})\s?{_ampm.format("ampm2")}'
    rf'|(?P<ord>\d+)(?:st|nd|rd|th)\b'
    rf'|(?P<decade>1[1-9]\d0|20[0-9]0)s\b'
    rf'|(?P<ya>1[1-9]\d{{2}}|20\d{{2}})\s?(?:-|–)\s?(?P<yb>1[1-9]\d{{2}}|20\d{{2}})(?!\d)'
    rf'|(?P<mult>{NUM})\s?[x×](?![a-z])'
    rf'|(?<![A-Za-z])(?P<samt>{NUM})(?P<sscale>bn|mn|tn|[kmbKMB])\b'
    rf'|(?<![\d.,$])(?P<sdec>[1-9]0)s\b'
    rf'|(?P<hamt>{NUM})-(?P<hunit>{_unit}|in(?=\.?[ \t]+[a-z]))(?![A-Za-z²³]|-[A-Za-z]){_udot}'
    rf'|(?P<uneg>(?<![\w.])-)?(?P<uamt>{NUM})\s?(?P<unit>{_unit})(?![A-Za-z²³]|-[A-Za-z]){_udot}'
    rf'|#(?P<hash>\d+)'
    rf'|(?P<frac>\d+/\d+)(?:\s?(?P<funit>{_unit})(?![A-Za-z]){_udot})?'
    rf'|(?P<ra2>{NUM})\s?(?:–|-(?=\d{{1,3}}(?![\d,.]\d)\s?(?:{_unit}|[a-z])))\s?(?P<rb2>{NUM})'
    rf'(?:\s?(?P<runit>{_unit})(?![A-Za-z]){_udot})?'
    rf'|(?<![\w./-])(?P<sr1>\d{{1,2}})-(?P<sr2>\d{{1,2}})(?![\d/-]|[.,]\d)'
    rf'|(?P<year>(?:(?<![\d.,$])|{_circa})(?:1[1-9]\d{{2}}|20\d{{2}})(?![\d%]|\.\d|,\d))'
    rf'|(?P<neg>(?<![\w.])-)?(?P<num>{NUM})'
)


def _plain(text: str) -> str:
    return re.sub(r',| and(?= )', '', text)


def en_number(token: str) -> str:
    value = Decimal(token.replace(',', ''))
    return _plain(num2words(value if value % 1 else int(value)))


def en_year(token: str) -> str:
    return _plain(num2words(int(token), to='year'))


def _fraction(frac: str, rest: str, whole: str | None = None) -> str:
    """A fraction as said: after a whole number "and a half"; before a noun "half a cup"; else "one half"."""
    before, after = FRACTION_WORDS.get(frac, (None, None))
    if whole is not None:
        return f"{en_number(whole)} and {after or _fraction(frac, '')}"
    noun = re.match(r'\s+([a-z]+)', rest)
    if before and noun and not noun.group(1).endswith('s') and noun.group(1) not in ('of', 'and', 'or', 'to', 'in'):
        return before
    a, b = frac.split('/')
    return FRACTIONS.get(frac, f'{en_number(a)} {en_number(b)}')


def _price(whole: str, cents: str) -> str:
    """A dollar price as an ad reads it: $3.50 is "three fifty", $0.99 "ninety-nine cents", $1.05 "one oh five"."""
    if int(whole) == 0:
        return f"{en_number(cents)} cent{'s' if int(cents) != 1 else ''}"
    return f"{en_number(whole)} {'oh ' + en_number(cents) if int(cents) < 10 else en_number(cents)}"


def _clock(hour: int, minute: int | None, ampm: str | None) -> str | None:
    if hour > 24 or (minute is not None and minute > 59) or (ampm and not 1 <= hour <= 12):
        return None
    words = en_number(str(hour))
    if minute:
        words += f" oh {en_number(str(minute))}" if minute < 10 else f" {en_number(str(minute))}"
    elif minute == 0 and not ampm:
        words += " o'clock"
    return words + (f" {ampm.upper()}M" if ampm else '')


DIGIT_WORDS = 'zero one two three four five six seven eight nine'.split()
# Words before a number that make it a code read digit by digit ("code 482913", "PIN 0420", "order number 10023").
CODE_BEFORE = re.compile(r'\b(?:code|codes|pin|otp|passcode|password|verification|confirmation|zip|postcode|tracking|'
                         r'order|reference|ref|account|acct|ticket|serial|booking|member|membership|policy|invoice|'
                         r'case|claim|id|room|rm|flight|gate|seat|unit|apt|apartment|suite|ste|extension|ext)\b'
                         r'(?:\s*(?:number|no\.?|num|#|is|was|:|=))*\s*[:#]?\s*$', re.I)
# A number the text introduces as a code, said digit by digit in its written groups, zero as "zero" ("a 6-digit code,
# like 482 913": "four eight two, nine one three"; "order #10023"; "confirmation number is 7731 4410"). The groups
# are joined by hyphens, which the voice turns into short pauses (speech.SAY_EN) and which are no clause break.
# Words that are also verbs ("order 300 pizzas", "pin 120 photos") count only after "your", "the" ... or with
# "number"/"#" after them.
_CODE_NOUN = r'(?i:orders?|tickets?|bookings?|reservations?|references?|pins?)'
_CODE_DET = r'\b(?i:your|the|my|our|their|his|her|this|that|its)\s+'
_CODE_NAMED = r'\s*(?i:numbers?\b|no\.|#)'
CODE_RUN = re.compile(
    r'(?P<intro>(?P<det>' + _CODE_DET + r')?'
    r'\b(?:(?i:passcodes?|codes?|otps?|verification|confirmation|tracking|flights?)|PINs?|(?P<noun>' + _CODE_NOUN +
    r'))\b(?P<named>(?=' + _CODE_NAMED + r'))?)'
    r'(?P<gap>(?:\s*(?:[,:#=—–]|\b(?:numbers?|no\.|num|is|was|are|were|reads?|like|such as|e\.g\.|for example)(?![\w-])))*\s*)'
    r'(?P<code>(?<![\w.,$])\d+(?:[ -]\d+)*)(?![\w%]|[.,:]\d)')


def code_runs(text: str) -> list[re.Match]:
    """The codes in English ``text`` (CODE_RUN) with three digits or more: group 'code' is the number as written,
    'intro' and 'gap' the words that introduce it."""
    out = []
    for m in CODE_RUN.finditer(text):
        if m['noun'] and not m['det'] and m['named'] is None:
            continue
        if len(re.sub(r'\D', '', m['code'])) >= 3:
            out.append(m)
    return out


def _code(token: str) -> str:
    return '-'.join(digits(g) for g in re.findall(r'\d+', token))


PHONE_BEFORE = re.compile(r'\b(?:call|calls|phone|tel|telephone|text|txt|fax|dial|number|mobile|cell|reach|ring|'
                          r'hotline|line|whatsapp)\b[^.!?\d]{0,24}$', re.I)
# How a web address's pieces sound: "pipewisebayside.com/tips" is "pipewise bayside dot com slash tips".
URL_MARKS = {'.': 'dot', '/': 'slash', '@': 'at', '-': 'dash', '_': 'underscore', ':': 'colon', '~': 'tilde',
             '+': 'plus', '=': 'equals', '&': 'and', '%': 'percent', '#': 'hash', '?': 'question mark'}
SPELLED_TLDS = {'edu': 'E D U', 'io': 'I O', 'ai': 'A I', 'tv': 'T V', 'fm': 'F M', 'uk': 'U K', 'us': 'U S',
                'gg': 'G G', 'ly': 'L Y', 'nz': 'N Z', 'eu': 'E U', 'jp': 'J P', 'cn': 'C N', 'mx': 'M X',
                'br': 'B R', 'nl': 'N L', 'de': 'D E', 'fr': 'F R', 'es': 'E S', 'ie': 'I E', 'au': 'A U',
                'ca': 'C A', 'xyz': 'X Y Z'}


def digits(token: str, zero: str = 'zero') -> str:
    """A number read one digit at a time: "0147" is "oh one four seven" with ``zero='oh'``."""
    return ' '.join(zero if d == '0' else DIGIT_WORDS[int(d)] for d in token if d.isdigit())


_WORDS = None


def _english_words() -> frozenset:
    """Real English words: the voice's own pronunciation dictionary (misaki's us_gold.json, shipped with it)."""
    global _WORDS
    if _WORDS is None:
        try:
            import json
            import misaki
            from pathlib import Path
            path = Path(misaki.__file__).parent / 'data' / 'us_gold.json'
            _WORDS = frozenset(w for w in json.loads(path.read_text(encoding='utf-8'))
                               if w.isalpha() and w.islower())
        except (ImportError, OSError, ValueError):
            _WORDS = frozenset()
    return _WORDS


def split_words(run: str) -> str:
    """A run of letters as the words it is made of: "MillbrookLeafWeek" -> "Millbrook Leaf Week" (its capitals),
    "pipewisebayside" -> "pipewise bayside"-like pieces from the dictionary (fewest pieces of three letters or more);
    a run the dictionary cannot cut, or a short one, stays whole."""
    parts = re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+', run)
    if len(parts) > 1:
        return ' '.join(split_words(p) if p.isalpha() else digits(p) for p in parts)
    low = run.lower()
    words = _english_words()
    if len(run) < 10 or not run.isalpha() or not words or low in words:
        return run
    best = [None] * (len(low) + 1)                # best[i]: fewest dictionary pieces covering low[:i]
    best[0] = []
    for i in range(3, len(low) + 1):
        for j in range(0, i - 2):
            if best[j] is not None and low[j:i] in words and (best[i] is None or len(best[j]) + 1 < len(best[i])):
                best[i] = best[j] + [run[j:i]]
    pieces = best[len(low)]
    return ' '.join(pieces) if pieces and len(pieces) <= 4 else run


def _address(text: str, url: bool) -> str:
    """An email or web address as it is read out: no "https://" or "www.", each mark a word, numbers digit by digit,
    run-together words apart, and the ending ("com", "org") said as a word or, when it is not one, letter by letter."""
    if url:
        text = re.sub(r'^(?:https?://)?(?:www\.)?', '', text, flags=re.I).rstrip('/')
    pieces = re.findall(r'[A-Za-z]+|\d+|[^A-Za-z\d]', text)
    last = max((k for k, p in enumerate(pieces) if p.isalpha()), default=-1)
    tld = next((k for k in range(len(pieces) - 1, 0, -1) if pieces[k].isalpha() and pieces[k - 1] == '.'), None)
    out = []
    for k, piece in enumerate(pieces):
        if piece.isdigit():
            out.append(digits(piece, 'oh' if len(piece) > 1 else 'zero'))
        elif piece.isalpha():
            if k == tld and (url or k == last):
                out.append(SPELLED_TLDS.get(piece.lower(), piece.lower()))
            else:
                out.append(split_words(piece))
        elif piece in URL_MARKS:
            out.append(URL_MARKS[piece])
    return ' '.join(out)


def _phone(text: str) -> str:
    """A phone number as digit groups an announcer pauses between ("(555) 018-7720" is "five five five-oh one eight-
    seven seven two zero"): the groups are joined by hyphens, which the voice turns into short pauses (speech._say)
    and which are no clause break, so the captions keep their timing."""
    plus = text.lstrip().startswith('+')
    groups = re.findall(r'\d+', text)
    if not plus and len(groups) == 4 and groups[0] == '1':
        groups = groups[1:]
    said = '-'.join(digits(g, 'oh') for g in groups)
    return ('plus ' if plus else '') + said


def _code_before(m: re.Match) -> bool:
    before = m.string[max(0, m.start() - 40):m.start()]
    word = CODE_BEFORE.search(before)
    if word and re.match(_CODE_NOUN + r'\b', word.group()) and not re.match(r'\w+' + _CODE_NAMED, word.group()) \
            and not re.search(_CODE_DET + r'$', before[:word.start()]):
        word = None                                 # "order 300 pizzas": a verb and a count
    return bool(word or re.search(r'[A-Za-z],\s*[A-Z]{2}\s+$', before))   # "Austin, TX 78701"


def _unit_said(key: str, one: bool = False) -> str:
    singular, plural = lexicon.UNITS[key]
    return singular if one else plural


# Words before a day and month written with a slash that make it a date ("Tue. 10/14", "due 3/4"); with a year it is
# always one ("12/25/2026").
DATE_BEFORE = re.compile(r'(?:\b(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?\.?,?|'
                         r'\b(?:on|by|due|until|till|til|thru|through|from|starting|since|before|after|deadline|date|'
                         r'dated|opens?|closes?|ends?|begins?|starts?|expires?|exp\.?|effective|born|died|'
                         r'and|to|or|[-–&])\s*:?)\s*$', re.I)


def _date(m: re.Match, g: dict, rest: str) -> str:
    """A month and a day written with slashes, as said: "12/25/2026" is "December twenty-fifth twenty twenty-six";
    without a year only where a date is expected ("on 1/15"), else a fraction ("24/7", "3/4")."""
    month, day = int(g['dm']), int(g['dd'])
    frac = f"{g['dm']}/{g['dd']}"
    dated = 1 <= month <= 12 and 1 <= day <= 31 and (
        g['dy'] or (DATE_BEFORE.search(m.string[max(0, m.start() - 30):m.start()]) and not re.match(r'\s+(?:of|cups?|in)\b', rest)))
    if not dated:
        return _fraction(frac, rest)
    said = f"{MONTHS[list(MONTHS)[month - 1]]} {num2words(day, to='ordinal')}"
    if g['dy']:
        year = g['dy'] if len(g['dy']) == 4 else '20' + g['dy']
        said += ' ' + en_year(year)
    return said


def _en_speak(m: re.Match) -> str:
    g = m.groupdict()
    rest = m.string[m.end():]
    if g['email']:
        return _address(g['email'], url=False)
    if g['url']:
        return _address(g['url'], url=True)
    if g['phone']:
        if re.fullmatch(r'\d{3}-\d{4}', g['phone']) and not (
                g['phone'][4] == '0' or PHONE_BEFORE.search(m.string[max(0, m.start() - 40):m.start()])):
            a, b = g['phone'].split('-')                # "555-1000" with no phone around it: two numbers
            return f'{en_number(a)}-{en_number(b)}'
        return _phone(g['phone'])
    if g['ext']:
        return 'extension ' + digits(g['ext'], 'oh' if len(g['ext']) > 1 else 'zero')
    if g['ver'] or g['verc']:
        parts = ' point '.join(en_number(p) for p in (g['ver'] or g['verc']).split('.'))
        return parts if re.search(r'\bversion\s+$', m.string[:m.start()], re.I) else 'version ' + parts
    if (g['year'] or g['decade']) and re.search(r'\b[cC]a?\.$', m.string[:m.start()]):
        words = en_year(g['year'] or g['decade'])     # "c.1900": the year is a word of its own after circa's period
        if g['decade']:
            words = words[:-1] + 'ies' if words.endswith('y') else words + 's'
        return ' ' + words
    if g['tag']:
        return 'hashtag ' + ' '.join(split_words(p) if not p.isdigit() else en_number(p)
                                     for p in g['tag'].split('_') if p)
    if g['tr1']:
        first = _clock(int(g['tr1']), int(g['trm1']) if g['trm1'] else None, g['tra1'])
        second = _clock(int(g['tr2']), int(g['trm2']) if g['trm2'] else None, g['tra2'])
        if first and second:
            return f'{first} to {second}'
        return f"{en_number(g['tr1'])} to {en_number(g['tr2'])}" + (f" {g['tra2'].upper()}M" if g['tra2'] else '')
    if g['inch']:
        return f"{en_number(g['inch'])} inch{'' if Decimal(g['inch'].replace(',', '')) == 1 else 'es'}"
    token = g['year'] or g['num']
    if token and re.fullmatch(r'\d+', token) and ((len(token) >= 3 and _code_before(m)) or
                                                  (len(token) >= 3 and token.startswith('0'))):
        return ('minus ' if g['neg'] else '') + digits(token)     # "code 482913", "0147"
    if g['dm']:
        return _date(m, g, rest)
    if g['mixw']:
        unit = f" {_unit_said(g['munit'])}" if g['munit'] else ''
        return _fraction(g['mixf'] or VULGAR[g['mixv']], rest, g['mixw']) + unit
    if g['vul']:
        if g['vunit']:
            return _fraction(VULGAR[g['vul']], ' unit') + f" {_unit_said(g['vunit'], one=True)}"
        return _fraction(VULGAR[g['vul']], rest)
    if g['cur']:
        one, many = CURRENCIES[g['cur']]
        amount = g['camt']
        if g['cscale']:
            return f"{en_number(amount)} {SCALES[g['cscale'].lower()]} {many}"
        if re.fullmatch(r'[\d,]+\.\d\d', amount) and not amount.endswith('.00') and one == 'dollar':
            whole, cents = amount.replace(',', '').split('.')
            if int(whole) < 1000:
                return _price(whole, cents)
            unit = one if int(whole) == 1 else many
            return f"{en_number(whole)} {unit} and {en_number(cents)} cents"
        return f"{en_number(amount)} {one if Decimal(amount.replace(',', '')) == 1 else many}"
    if g['rpct']:
        return f"{en_number(g['ra'])} to {en_number(g['rb'])} percent"
    if g['pct']:
        token = g['pct']
        return ('minus ' if token.startswith('-') else '') + f"{en_number(token.lstrip('-'))} percent"
    if g['month']:
        month = MONTHS[g['month'].rstrip('.').lower()[:3]]
        said = f"{month} {num2words(int(g['day']), to='ordinal')}"
        return said + (f" to {num2words(int(g['day2']), to='ordinal')}" if g['day2'] else '')
    if g['h']:
        return _clock(int(g['h']), int(g['mi']), g['ampm'])
    if g['hh']:
        said = _clock(int(g['hh']), None, g['ampm2'])
        return said or en_number(g['hh']) + m.group()[len(g['hh']):]
    if g['ord']:
        return num2words(int(g['ord']), to='ordinal')
    if g['decade']:
        words = en_year(g['decade'])
        return words[:-1] + 'ies' if words.endswith('y') else words + 's'
    if g['ya']:
        return f"{en_year(g['ya'])} to {en_year(g['yb'])}"
    if g['mult']:
        return f"{en_number(g['mult'])} times"
    if g['samt']:
        return f"{en_number(g['samt'])} {SCALES[g['sscale'].lower()]}"
    if g['sdec']:
        return en_number(g['sdec'])[:-1] + 'ies'                               # "her 50s": fifties
    if g['hamt']:
        unit = 'inch' if g['hunit'] == 'in' else _unit_said(g['hunit'], one=True)
        return f"{en_number(g['hamt'])}-{unit}"                                # "a 6-ft fence": six-foot
    if g['uamt']:
        amount = g['uamt'].replace(',', '')
        if g['unit'] == 'W' and re.match(r'\.?\s+(?:\d|[A-Z])', rest):
            return f"{en_number(g['uamt'])} W"          # "12 W 4th St": West, a compass point (lexicon.py)
        if re.fullmatch(r'[1-9]\d*\.50*', amount):                              # "2.5 BA": two and a half baths
            return f"{en_number(amount.split('.')[0])} and a half {_unit_said(g['unit'])}"
        # Before its noun after "a" the measure is one thing: "a 5 gal bucket" a five gallon bucket.
        one = Decimal(amount) == 1 or bool(re.search(r'\b(?:a|an)\s+$', m.string[:m.start()], re.I) and re.match(
            r'\s+(?!(?:of|and|or|to|in|per|a|an|the|each|for|at|on|by|with|from|than|is|was)\b)[a-z]', rest))
        return ('minus ' if g['uneg'] else '') + f"{en_number(g['uamt'])} {_unit_said(g['unit'], one=one)}"
    if g['hash']:
        return f"number {en_number(g['hash'])}"
    if g['frac']:
        if g['funit']:
            return _fraction(g['frac'], ' unit') + f" {_unit_said(g['funit'], one=True)}"
        return _fraction(g['frac'], rest)
    if g['ra2']:
        unit = f" {_unit_said(g['runit'])}" if g['runit'] else ''
        return f"{en_number(g['ra2'])} to {en_number(g['rb2'])}{unit}"
    if g['sr1']:
        return f"{en_number(g['sr1'])} to {en_number(g['sr2'])}"             # "9-5", "pp. 10-12", "won 3-2"
    if g['year']:
        noun = re.match(r'\s+([a-z]+)\b', rest)
        if noun and (noun.group(1) in COUNT_NOUNS or (noun.group(1).endswith('s') and noun.group(1) not in NOT_PLURAL)):
            return en_number(g['year'])                 # 1969 people, 2000 shares: a count
        return en_year(g['year'])
    return ('minus ' if g['neg'] else '') + en_number(g['num'])


def normalize_en(display: str) -> Normalized:
    codes = [(m.start('code') - 1, m.end('code'), 'number ' + _code(m['code'])) if m['gap'].endswith('#') else
             (m.start('code'), m.end('code'), _code(m['code'])) for m in code_runs(display)]     # "order #10023"
    return _rewrite(display, EN_PATTERN, _en_speak, codes)


# ============================================================== Spanish
ES_CUR = {'US$': ('dólar', 'dólares'), '$': ('dólar', 'dólares'), '€': ('euro', 'euros'),
          '£': ('libra', 'libras'), '¥': ('yen', 'yenes'), '₹': ('rupia', 'rupias')}
ES_CENTS = {'US$': ('centavo', 'centavos'), '$': ('centavo', 'centavos'),
            '€': ('céntimo', 'céntimos'), '£': ('penique', 'peniques')}
ES_UNITS = {'km/h': ('kilómetro por hora', 'kilómetros por hora'), 'km': ('kilómetro', 'kilómetros'),
            'm': ('metro', 'metros'), 'cm': ('centímetro', 'centímetros'), 'mm': ('milímetro', 'milímetros'),
            'kg': ('kilogramo', 'kilogramos'), 'g': ('gramo', 'gramos'), 't': ('tonelada', 'toneladas'),
            'l': ('litro', 'litros'), 'ml': ('mililitro', 'mililitros'),
            '°C': ('grado Celsius', 'grados Celsius'), '°F': ('grado Fahrenheit', 'grados Fahrenheit'),
            '°': ('grado', 'grados'), 'mph': ('milla por hora', 'millas por hora'),
            'GB': ('gigabyte', 'gigabytes'), 'MB': ('megabyte', 'megabytes')}
ES_SCALES = {'k': ('mil', 'mil'), 'thousand': ('mil', 'mil'), 'mil': ('mil', 'mil'),
             'm': ('millón', 'millones'), 'mn': ('millón', 'millones'), 'mm': ('millón', 'millones'),
             'million': ('millón', 'millones'), 'millón': ('millón', 'millones'), 'millones': ('millón', 'millones'),
             'b': ('mil millones', 'mil millones'), 'bn': ('mil millones', 'mil millones'),
             'billion': ('mil millones', 'mil millones'), 't': ('billón', 'billones'),
             'tn': ('billón', 'billones'), 'trillion': ('billón', 'billones')}
ES_NUM = (r'\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d|[.,]\d)'
          r'|\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d|[.,]\d)|\d+(?:[.,]\d+)?')
_es_scale = '(?:MM|(?i:' + '|'.join((r'(?<!\s)' if len(k) < 3 else '') + re.escape(k)   # '10MM' is millions,
                                     for k in sorted(ES_SCALES, key=len, reverse=True) if k != 'mm') + '))'  # '10mm' rain
_es_cscale = '(?i:' + '|'.join(re.escape(k) for k in sorted(ES_SCALES, key=len, reverse=True)) + ')'  # '$5 MM'
_es_unit = '|'.join(re.escape(u) for u in sorted(ES_UNITS, key=len, reverse=True))
ES_PATTERN = re.compile(
    rf'(?P<cur>{_cur})\s?(?P<camt>{ES_NUM})(?:\s?(?P<cscale>{_es_cscale})\b)?'
    rf'|(?P<ra>{ES_NUM})\s?(?:-|–|a)\s?(?P<rb>{ES_NUM})\s?(?P<rpct>%)'
    rf'|(?P<pct>-?(?:{ES_NUM}))\s?%'
    rf'|(?P<samt>{ES_NUM})\s?(?P<sscale>{_es_scale})\b'
    rf'|(?P<uamt>{ES_NUM})\s?(?P<unit>{_es_unit})(?![^\W\d_])'
    rf'|(?P<neg>(?<![\w.])-)?(?P<num>{ES_NUM})'
)


def es_number(token: str) -> str:
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?', token):
        token = token.replace('.', '')
    elif re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', token):
        token = token.replace(',', '')
    whole, dot, fraction = token.partition(',' if ',' in token else '.')
    words = num2words(int(whole), lang='es')
    words = re.sub(r'(veinti)?uno(?= (?:mil|millones|billones)\b)', lambda m: 'veintiún' if m.group(1) else 'un',
                   words)                         # num2words says 'veintiuno mil'; Spanish says 'veintiún mil'
    if dot:
        words += (' coma ' if dot == ',' else ' punto ') + ' '.join(num2words(int(d), lang='es') for d in fraction)
    return words


def _es_speak(m: re.Match) -> str:
    g = m.groupdict()
    if g['cur'] or g['samt'] or g['uamt']:
        token = amount = g['camt'] or g['samt'] or g['uamt']
        scale = (g['cscale'] or g['sscale'] or '').lower()
        if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?', amount):
            amount = amount.replace('.', '')
        elif re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', amount):
            amount = amount.replace(',', '')
        whole, dot, fraction = amount.replace(',', '.').partition('.')
        cents = g['cur'] in ES_CENTS and not scale and len(fraction) == 2
        one = Decimal(whole if cents else amount.replace(',', '.')) == 1
        words = es_number(whole if cents else token)
        if scale or g['unit'] or (g['cur'] and (not dot or cents)):
            feminine = not scale and (g['cur'] in ('£', '₹') or g['unit'] in ('t', 'mph'))
            words = re.sub(r'veintiuno$', 'veintiuna' if feminine else 'veintiún', words)
            words = re.sub(r'uno$', 'una' if feminine else 'un', words)
        if scale:
            words = 'mil' if one and ES_SCALES[scale][1] == 'mil' else words + ' ' + ES_SCALES[scale][0 if one else 1]
        if g['cur']:
            singular, plural = ES_CUR[g['cur']]
            words += (' de ' if scale and ES_SCALES[scale][1] != 'mil' else ' ') + (singular if one and not scale else plural)
            if cents and int(fraction):
                minor = re.sub(r'veintiuno$', 'veintiún', es_number(str(int(fraction))))
                minor = re.sub(r'uno$', 'un', minor)
                words += ' con ' + minor + ' ' + ES_CENTS[g['cur']][0 if int(fraction) == 1 else 1]
        if g['unit']:
            words += ' ' + ES_UNITS[g['unit']][0 if one else 1]
        return words
    if g['rpct']:
        return f"{es_number(g['ra'])} a {es_number(g['rb'])} por ciento"
    if g['pct']:
        token = g['pct']
        return ('menos ' if token.startswith('-') else '') + f"{es_number(token.lstrip('-'))} por ciento"
    words = es_number(g['num'])
    noun = re.match(r'\s+([a-záéíóúüñ]+)\b', m.string[m.end():])
    if (noun and words.endswith('uno') and re.fullmatch(r'[\d.]+', g['num']) and noun.group(1) not in ES_NOT_NOUN
            and not re.fullmatch(r'1\d\d\d|20\d\d', g['num'])):   # '1 perro' -> 'un perro', '21 años' -> 'veintiún'
        feminine = _es_feminine(noun.group(1))
        words = words[:-3] + ('una' if feminine else 'ún' if words.endswith('veintiuno') else 'un')
    return ('menos ' if g['neg'] else '') + words


# Words that follow a number without being what it counts: '1 de cada 4', 'el 1 y el 2', 'tengo 21 más'.
ES_NOT_NOUN = {'de', 'del', 'y', 'e', 'o', 'u', 'a', 'al', 'en', 'por', 'para', 'con', 'sin', 'que', 'es', 'son',
               'fue', 'era', 'eran', 'fueron', 'será', 'más', 'menos', 'entre', 'sobre', 'hasta', 'desde', 'como',
               'cada', 'se', 'lo', 'la', 'el', 'los', 'las', 'le', 'les', 'un', 'una', 'ni', 'pero', 'si', 'no',
               'ya', 'hay', 'está', 'están', 'tiene', 'tienen', 'veces'}
ES_MASCULINE_A = {'día', 'días', 'mapa', 'mapas', 'problema', 'problemas', 'planeta', 'planetas', 'idioma', 'idiomas',
                  'sistema', 'sistemas', 'tema', 'temas', 'clima', 'climas', 'programa', 'programas', 'poema',
                  'poemas', 'esquema', 'esquemas', 'dilema', 'drama', 'dramas', 'cometa', 'cometas', 'sofá',
                  'sofás', 'diploma', 'diplomas', 'telegrama', 'kilograma', 'gorila', 'gorilas', 'koala', 'koalas',
                  'panda', 'pandas', 'atleta', 'atletas', 'astronauta', 'astronautas', 'artista', 'artistas',
                  'dentista', 'dentistas', 'turista', 'turistas', 'papá', 'papás', 'dálmata', 'dálmatas',
                  'ave', 'águila', 'agua', 'hacha', 'alma', 'arma', 'aula', 'área', 'hambre', 'hada', 'ala',
                  'arpa'}   # the last row: feminine, but 'un ave', 'un águila' before a stressed a
ES_FEMININE = {'vez', 'clase', 'clases', 'noche', 'noches', 'parte', 'partes', 'gente', 'mano', 'manos', 'flor',
               'flores', 'mujer', 'mujeres', 'calle', 'calles', 'nube', 'nubes', 'leche', 'llave', 'llaves',
               'fuente', 'fuentes', 'frase', 'frases', 'imagen', 'imágenes', 'luz', 'luces', 'red', 'redes', 'piel',
               'sal', 'muerte', 'suerte', 'mente', 'mentes', 'foto', 'fotos', 'moto', 'motos', 'radio', 'tarde',
               'tardes', 'torre', 'torres', 'carne', 'sangre', 'fiebre', 'nariz', 'raíz', 'raíces', 'voz', 'voces',
               'cruz', 'paz', 'ley', 'leyes', 'miel', 'col', 'sed', 'pared', 'paredes', 'serie', 'series',
               'especie', 'especies', 'superficie', 'nieve', 'base', 'bases', 'fase', 'fases', 'clave',
               'claves', 'nave', 'naves', 'aves'}


def _es_feminine(noun: str) -> bool:
    if noun in ES_MASCULINE_A:
        return False
    return noun in ES_FEMININE or noun.endswith(('a', 'as', 'ción', 'ciones', 'sión', 'siones', 'dad', 'dades',
                                                 'tad', 'tades', 'tud', 'tudes', 'umbre', 'umbres', 'eza'))


def normalize_es(display: str) -> Normalized:
    return _rewrite(display, ES_PATTERN, _es_speak)


# ============================================================== Chinese
ZH_CUR = {'US$': '美元', '$': '美元', '€': '欧元', '£': '英镑', '¥': '元', '￥': '元', 'HK$': '港元'}
_zcur = '|'.join(re.escape(c) for c in sorted(ZH_CUR, key=len, reverse=True))
ZH_PATTERN = re.compile(
    rf'(?P<h>\d{{1,2}})[:：](?P<mi>\d{{2}})'
    rf'|(?P<ra>{NUM})\s?(?:-|–|~|～|至|到)\s?(?P<rb>{NUM})\s?(?P<rpct>[%％])'
    rf'|(?P<cur>{_zcur})\s?(?P<camt>{NUM})(?:\s?(?P<cscale>万亿|亿|万|千|trillion|billion|million|bn|mn|[kmb]))?'
    rf'|(?P<year>\d{{4}})(?=\s?年)'
    rf'|(?P<pct>{NUM})\s?[%％]'
    rf'|(?P<frac>\d+)/(?P<den>\d+)'
    rf'|(?P<num>{NUM})'
)
ZH_SCALES = {'trillion': '万亿', 'billion': '十亿', 'million': '百万', 'bn': '十亿', 'mn': '百万', 'k': '千',
             'm': '百万', 'b': '十亿'}


def zh_number(token: str) -> str:
    words = cn2an.an2cn(token.replace(',', ''), 'low')
    return re.sub(r'(^|[亿万])二(?=[千万亿])', r'\1两', words)


def _zh_speak(m: re.Match) -> str:
    g = m.groupdict()
    if g['h']:
        hour, minute = int(g['h']), int(g['mi'])
        if hour > 24 or minute > 59:
            return None
        return zh_number(str(hour)) + '点' + ('' if minute == 0 else '半' if minute == 30 else
                                              ('零' if minute < 10 else '') + zh_number(str(minute)) + '分')
    if g['rpct']:
        return f"百分之{zh_number(g['ra'])}到百分之{zh_number(g['rb'])}"
    if g['cur']:
        scale = g['cscale'] or ''
        scale = ZH_SCALES.get(scale.lower(), scale)
        return f"{zh_number(g['camt'])}{scale}{ZH_CUR[g['cur']]}"
    if g['year']:
        return ''.join('零一二三四五六七八九'[int(d)] for d in g['year'])
    if g['pct']:
        return f"百分之{zh_number(g['pct'])}"
    if g['frac']:
        return f"{zh_number(g['den'])}分之{zh_number(g['frac'])}"
    return zh_number(g['num'])


def normalize_zh(display: str) -> Normalized:
    return _rewrite(display, ZH_PATTERN, _zh_speak)


def normalize(display: str, lang: str) -> Normalized:
    if lang == 'es':
        return normalize_es(display)
    return normalize_en(display) if lang == 'en' else normalize_zh(display)


"""What a beat says aloud and what its captions show, from the text the customer wrote.

A beat keeps its written text (``display``) and its spoken form (``spoken``: numbers as words, numbers.py); the
storybook and the planners read those unchanged. From them this module derives:

- the hidden parts, neither said nor captioned: screenplay speaker labels ("JULES:" at a line start, any case),
  [bracketed] stage directions, (parenthetical) directions in a screenplay line, scene headings (INT./EXT.), emoji
  and stray Markdown marks. A beat that is only a direction is silent and has no caption;
- the caption text (``captions``): the written words without the hidden parts, with a map back to the spoken text so
  each word keeps its measured time;
- the voice parts (``segments``): runs of the spoken text, each with who says it (a speaker label's person, a quote's
  speaker, or the narrator) and the exact text the voice reads (``said``: abbreviations spelled out for the voice
  only, "Dr. Lee" -> "Doctor Lee"), with every said character mapped back to the spoken text.

Who says a quotation in prose ("Mine's broken," he said.) comes from speakers.attribute, the one reading that the
speech bubbles and the talking figures follow too: ``quote_speakers``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import markup

EMOJI = re.compile('[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿︎️‍⃣'
                   '\U000E0020-\U000E007F]')
# NAME: at a line start (a speaker label), optionally with a (parenthetical) before the colon.
LABEL = re.compile(r"(?P<name>[^\W\d_][\w’'.-]*(?: [^\W\d_][\w’'.-]*){0,2})[ \t]*(?P<paren>\([^)\n]{0,60}\))?[ \t]*:"
                   r"[ \t]+(?=\S)")
# Words that start a line with a colon but never name a speaker.
NOT_SPEAKERS = set('''note notes nb step steps tip tips warning caution important ingredients ingredient method
directions update edit summary chapter part day scene act title subject location setting time date ps p.s fact
fun pro reminder remember spoiler breaking disclaimer source sources credit credits hint example examples result
results total price cost address where when why how what who then and but so now here there today tonight finally
first second third next lastly also plus bonus answer question rule rules goal goals tldr fyi re fwd cc bcc from to
sent attachment link website email phone call text menu hours open closed sale offer deal promo code episode
season verse chorus bridge intro outro hook cta caption headline subhead body footer lesson objective objectives
materials vocabulary key takeaway takeaways quote warning danger q&a faq ingredients serves yield prep cook
total'''.split())
OPEN_QUOTES, CLOSE_QUOTES = '"“‘«「『', '"”’»」』'
WEEKDAYS = {'mon': 'Monday', 'tue': 'Tuesday', 'tues': 'Tuesday', 'wed': 'Wednesday', 'thu': 'Thursday',
            'thur': 'Thursday', 'thurs': 'Thursday', 'fri': 'Friday', 'sat': 'Saturday', 'sun': 'Sunday'}
MONTH_NAMES = {m[:3].lower(): m for m in ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                          'September', 'October', 'November', 'December')}
MONTH_WORDS = ('(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)(?:uary|ruary|ch|il|e|y|ust|tember|ober|'
               'ember)?')
NUMBER_WORD = r'(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b'
COUNT_WORD = (r'(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:-(?:one|two|three|four|five|six|'
              r'seven|eight|nine))?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|(?:thir|four|fif|six|'
              r'seven|eigh|nine)teen|hundred|thousand)\b')
# A short day name is a day when a date, a time, another day or a list mark comes next ("Mon. & Tue.", "Sat., Nov. 8",
# "party sat 6pm"); "Sun." and "Sat." on their own may be the sun or a past tense.
DAY_NEXT = (r'(?=\s*(?:,|&|\band\b|\bor\b|\bto\b|\bthrough\b|\bthru\b|[–—-]|\d|\bat\b|\bnight\b|'
            r'\bmorning\b|\bevening\b|\bafternoon\b|' + NUMBER_WORD + '|' + MONTH_WORDS + r'\b))')


def _stop(m: re.Match, word: str) -> str:
    """An abbreviation's word, with its period kept when it ended the sentence ("on Quarry Rd. Bring" -> "Road.")."""
    rest = m.string[m.end():]
    ends = m.group().endswith('.') and (not rest.strip() or re.match(
        r'\s+(?!(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\b|' + MONTH_WORDS + r'\b)[A-Z"“]', rest))
    return word + ('.' if ends else '')


def _day(m: re.Match) -> str:
    word = WEEKDAYS[m.group(1).lower()]
    if not m.group().endswith('.') and re.match(r'\s+' + NUMBER_WORD, m.string[m.end():]):
        word += ' at'                                   # "party sat six PM" -> "Saturday at six PM"
    return _stop(m, word)


PLACE_WORDS = {'Rd': 'Road', 'Blvd': 'Boulevard', 'Ln': 'Lane', 'Hwy': 'Highway', 'Rte': 'Route', 'Pkwy': 'Parkway',
               'Ct': 'Court', 'Apt': 'Apartment', 'Ste': 'Suite', 'Bldg': 'Building', 'Dept': 'Department',
               'Govt': 'Government', 'Gov': 'Governor', 'Sen': 'Senator', 'Rep': 'Representative', 'Capt': 'Captain',
               'Lt': 'Lieutenant', 'Sgt': 'Sergeant', 'Gen': 'General', 'Corp': 'Corporation', 'Univ': 'University',
               'Assn': 'Association', 'Intl': 'International', 'Natl': 'National', 'Hosp': 'Hospital'}
# Chat shorthand a customer types ("ran the store 22 yrs lol", "see u sat w/ the kids"): the voice says the words,
# the captions keep the writing. Laughs and tone marks are tone, not words: the voice leaves them out.
SHORTHAND = {'w/': 'with', 'w/o': 'without', 'b/c': 'because', 'bc': 'because', 'u': 'you', 'ur': 'your',
             'r': 'are', 'pls': 'please', 'plz': 'please', 'thx': 'thanks', 'thnx': 'thanks', 'tnx': 'thanks',
             'bday': 'birthday', 'b-day': 'birthday', 'ppl': 'people', 'msg': 'message', 'tmrw': 'tomorrow',
             'tmw': 'tomorrow', 'tmr': 'tomorrow', 'tonite': 'tonight', 'btw': 'by the way', 'idk': "I don't know",
             'omg': 'oh my gosh', 'imo': 'in my opinion', 'tbh': 'to be honest', 'fyi': 'for your information',
             'abt': 'about', 'cuz': 'because', 'bf': 'boyfriend', 'gf': 'girlfriend', 'gr8': 'great',
             'jk': 'just kidding', 'nvm': 'never mind', 'rn': 'right now', 'ty': 'thank you', 'yr': 'year',
             'yrs': 'years', 'hr': 'hour', 'hrs': 'hours', 'min': 'minute', 'mins': 'minutes', 'wk': 'week',
             'wks': 'weeks', 'mo': 'month', 'mos': 'months', 'w': 'with', 'xmas': 'Christmas', 'bros': 'brothers',
             'sis': 'sister', 'grandkids': 'grandkids', 'gonna': 'gonna'}
_shorthand = '|'.join(re.escape(k) for k in sorted(SHORTHAND, key=len, reverse=True) if k not in ('w', 'grandkids',
                                                                                                    'gonna'))
LAUGHS = re.compile(r'(?:[ \t]*\b(?:lol|lols|lmao|lmfao|rofl|roflmao|haha(?:ha)*|hehe(?:he)*|ha ha(?: ha)*|xd)\b)+(?=[\s.,!?;:)]|$)',
                    re.I)
def _tld_words():
    from .numbers import SPELLED_TLDS, TLDS
    return '|'.join(sorted({re.escape(SPELLED_TLDS.get(t, t)) for t in TLDS.split('|')}, key=len, reverse=True))


TLD_WORDS = _tld_words()
ARROW = re.compile(r'\s*(?:→|->|⟶|➔|➡️?|=>)\s*')

# Abbreviations spelled out for the voice only (captions keep the written form).
SAY_EN = [(re.compile(r'\bMr\.(?=\s)'), 'Mister'), (re.compile(r'\bMrs\.(?=\s)'), 'Missus'),
          (re.compile(r'\bMs\.(?=\s)'), 'Miz'),
          # After a street's name: "Elm St.", "Oak Dr."; before a name: "St. Louis", "Dr. Lee".
          (re.compile(r'\b(St|Dr)\.'), lambda m: ({'St': 'Street', 'Dr': 'Drive'} if re.search(
              r'\b[A-Z][\w’\']*\s$', m.string[:m.start()]) else {'St': 'Saint', 'Dr': 'Doctor'})[m.group(1)]),
          (re.compile(r'\bAve\.'), 'Avenue'),
          (re.compile(r'\bMt\.(?=\s+[A-Z])'), 'Mount'), (re.compile(r'\bvs\.?(?=\s)'), 'versus'),
          (re.compile(r'\betc\.'), 'et cetera'), (re.compile(r'\be\.g\.,?'), 'for example'),
          (re.compile(r'\bi\.e\.,?'), 'that is'), (re.compile(r'\bProf\.(?=\s)'), 'Professor'),
          (re.compile(r'\bJr\.'), 'Junior'), (re.compile(r'\bSr\.(?=\s|$)'), 'Senior'),
          (re.compile(r'\bapprox\.'), 'approximately'),
          (re.compile(r'\b(Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri)\.'), _day),
          (re.compile(r'\b(Sat|Sun)\.' + DAY_NEXT), _day),
          (re.compile(r'\b(Mon|Tues?|Wed|Thu|Thurs?|Fri|Sat|Sun|mon|tues?|wed|thu|thurs?|fri|sat|sun)\b(?!\.)' + DAY_NEXT),
           _day),
          (re.compile(r'\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.'),
           lambda m: _stop(m, MONTH_NAMES[m.group(1)[:3].lower()])),
          (re.compile(r'\b(' + '|'.join(PLACE_WORDS) + r')\.'), lambda m: _stop(m, PLACE_WORDS[m.group(1)])),
          (re.compile(r'\b[Nn]o\.(?=\s*' + NUMBER_WORD + ')'), 'number'),
          # The voice runs on through an abbreviation's period before a lowercase word ("Tom from Pipewise Plumbing
          # Inc. and"), and an extension never ends a sentence.
          (LAUGHS, ''),
          (re.compile(r'([!?])[!?]+'), lambda m: m.group(1)),
          (ARROW, lambda m: ('' if re.search(r'[,;:]\s*$', m.string[:m.start()] + ' ') else ', ') + 'then '
           if m.start() and m.string[:m.start()].strip() else ''),
          (re.compile(r'(?<![\w/&])(' + _shorthand + r')(?![\w/&])', re.I),
           lambda m: _shorthand_word(m)),
          (re.compile(r'(?<=\w)\s*&\s*(?=\w)|\s&\s'), ' and '),
          # Two addresses in a row ("pipewisebayside.com hello@pipewisebayside.com"): a pause after the first.
          (re.compile(r'\bdot (' + TLD_WORDS + r')(?= (?!dot\b|slash\b|at\b|dash\b)[\w])'), lambda m: m.group() + ','),
          # Two counts in a row ("3 kids 2 grandkids"): a list, with a pause between its items.
          (re.compile(r'\b' + COUNT_WORD + r'\s+(?!(?:times|equals|plus|minus|less|is|was|has|does)\b)[a-z]+s(?=\s+'
                      + COUNT_WORD + r')'), lambda m: m.group() + ','),
          # A phone number's digit groups: a short pause between them (numbers.py joins them with hyphens).
          (re.compile(r'\b(zero|oh|one|two|three|four|five|six|seven|eight|nine)-(?=(?:zero|oh|one|two|three|'
                      r'four|five|six|seven|eight|nine)\b)'), lambda m: m.group(1) + ', '),
          # "7 a.m." ends its sentence when a capitalised word that is no time zone follows ("7 a.m. 🔥 Just"): the
          # voice stops there instead of running on (the period went with the abbreviation in the spoken text). A day
          # or a date after the time is the same phrase ("6 AM Tues., Oct. 14", "10 AM Saturday").
          (re.compile(r'\b[AP]M(?=\s+(?!(?:Eastern|Central|Pacific|Mountain|Atlantic|GMT|UTC|[A-Z]{1,3}T|' +
                      r'(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)(?:day|nesday|sday|urday|rsday)?|'
                      r'Today|Tonight|Tomorrow|' + MONTH_WORDS + r')\b)[A-Z])'),
           lambda m: m.group() + '.')]



def _shorthand_word(m: re.Match) -> str:
    """The word for a piece of chat shorthand, only where it is written as shorthand: "u", "ur" and "r" in lower
    case ("U" may be a letter grade), "w/" before a word."""
    raw = m.group(1)
    key = raw.lower()
    if key in ('u', 'ur', 'r', 'bc', 'mo', 'min', 'hr', 'yr', 'wk', 'sis', 'bros', 'abt', 'rn', 'ty', 'bf', 'gf') \
            and raw != key:
        return raw
    if key in ('mo', 'min', 'mins', 'hr', 'hrs', 'yr', 'yrs', 'wk', 'wks', 'mos') and not re.search(
            r'\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[a-z]+teen|[a-z]+ty(?:-[a-z]+)?|'
            r'hundred|thousand|few|many|several|some|a|an|per|\d+)\s*$', m.string[:m.start()], re.I):
        return raw                                  # "min" alone is not minutes; "22 yrs" is years
    if key == 'r' and not re.match(r'\s+(?:u|you|we|they|y\w*)\b', m.string[m.end():], re.I) and \
            not re.search(r'\b(?:u|you|we|they)\s+$', m.string[:m.start()], re.I):
        return raw
    word = SHORTHAND[key]
    return word[0].upper() + word[1:] if raw[0].isupper() and m.start() == 0 else word


@dataclass
class Segment:
    """One voice part of a beat."""
    start: int                       # the part of the spoken text it voices: [start, end)
    end: int
    speaker: str | None              # a cast id, 'label:<name>' for a screenplay label no cast member matches, or None
    said: str                        # what the voice reads
    index: list = field(default_factory=list)     # spoken-text offset of each character of ``said``

    @property
    def cut_off(self) -> bool:
        """The line breaks off ("Dad, turn it off—"): the next speaker comes in over its end."""
        return bool(re.search(r'(?:—|--|–)\s*$', self.said))


# ------------------------------------------------------------------ labels
def _label_at(text: str, pos: int):
    m = LABEL.match(text, pos)
    if not m:
        return None
    name = m.group('name').strip(" .'’-")
    words = name.lower().split()
    if not name or not words or words[0].rstrip('.') in NOT_SPEAKERS or name.lower() in NOT_SPEAKERS:
        return None
    # Every word of a label is a name: capitalised (or the whole label one case), never a sentence ("Then a voice:").
    if len(words) > 1 and not (name.isupper() or all(w[:1].isupper() for w in name.split())):
        return None
    return m, name


def label_key(name: str) -> str:
    return re.sub(r'\s+', ' ', name.strip(" .'’-")).casefold()


def screenplay_labels(texts) -> set:
    """The speaker labels a script uses (casefolded names). A label counts when it is written in capitals (JULES:)
    or when the same name starts two or more lines; a lone "Note:" or "Then a voice:" never does."""
    seen = {}
    for text in texts:
        for pos in _line_starts(text):
            found = _label_at(text, pos)
            if found:
                key = label_key(found[1])
                seen.setdefault(key, []).append(found[1])
    return {key for key, names in seen.items()
            if len(names) >= 2 or all(n.isupper() and len(re.sub(r'\W', '', n)) >= 2 for n in names)}


def _line_starts(text: str) -> list[int]:
    """Where a screenplay line can start inside a beat: its first character, a line break, or (for lines a paste
    joined into one paragraph) right after a sentence end."""
    starts = [len(text) - len(text.lstrip())]
    starts += [m.end() for m in re.finditer(r'\n[ \t]*', text)]
    starts += [m.end() for m in re.finditer(r'[.!?…—)\]]["”’]?[ \t]+(?=[^\W\d_]+[ \t]*(?:\([^)\n]*\))?[ \t]*:)', text)]
    return sorted(set(starts))


# Broadcast and interview tags: "SOT (Maria Chen):" is Maria Chen speaking in her own voice, "REPORTER (V/O):" the
# reporter (a tag in the parentheses is no one's name).
TAGS = {'sot', 'sound bite', 'soundbite', 'bite', 'sync', 'interview', 'int', 'vox pop', 'vo', 'v/o', 'v.o', 'v.o.',
        'voice over', 'voiceover', 'voice-over', 'o/c', 'oc', 'on camera', 'on cam', 'nat sot', 'sot/vo', 'clip',
        'guest', 'caller', 'phoner', 'stand-up', 'standup', 'stand up', 'live', 'os', 'o.s', 'o.s.', 'cont',
        "cont'd", 'contd', 'off', 'off screen', 'offscreen', 'q', 'a'}


def labels_in(text: str, labels: set) -> list[tuple[int, int, str]]:
    """(label start, speech start, name) of each screenplay label in ``text``. A label after a sentence end inside a
    paragraph counts only in capitals (a pasted screenplay whose lines ran together). A broadcast tag names the
    person in its parentheses ("SOT (Maria Chen):" -> "Maria Chen")."""
    out = []
    for pos in _line_starts(text):
        found = _label_at(text, pos)
        if not found or label_key(found[1]) not in labels:
            continue
        m, name = found
        if pos != _line_starts(text)[0] and text[pos - 1] != '\n' and not name.isupper():
            continue
        paren = (m.group('paren') or '').strip('() \t')
        if label_key(name) in TAGS and paren and label_key(paren) not in TAGS and re.fullmatch(
                r"[^\W\d_][\w’'.-]*(?: [^\W\d_][\w’'.-]*){0,3}", paren) and all(w[:1].isupper() for w in paren.split()):
            name = paren
        out.append((pos, m.end(), name))
    return out


# ------------------------------------------------------------------ directions and on-screen text
# A line, a [bracket] or a (parenthesis) that starts with one of these is written for the picture, never said or
# captioned. Text after a screen-text tag ("[TEXT ON SCREEN: SAVE UP TO 20%]", "LOWER THIRD: Maria Chen - Owner")
# is shown as written: a text card or a name strap.
SCREEN_TEXT = {'text on screen': 'text', 'on screen text': 'text', 'on-screen text': 'text', 'onscreen text': 'text',
               'on screen': 'text', 'on-screen': 'text', 'onscreen': 'text', 'screen text': 'text', 'text': 'text',
               'title card': 'text', 'caption': 'text', 'text card': 'text', 'card': 'text', 'graphic text': 'text',
               'super': 'strap', 'lower third': 'strap', 'lower-third': 'strap', 'lower 3rd': 'strap', 'l3': 'strap',
               'chyron': 'strap', 'name strap': 'strap', 'strap': 'strap', 'cg': 'strap', 'font': 'strap',
               'name super': 'strap', 'lower third super': 'strap'}
DIRECTION_TAGS = {'show', 'showing', 'b-roll', 'broll', 'b roll', 'visual', 'visuals', 'gfx', 'graphic', 'graphics',
                  'scene', 'shot', 'camera', 'cam', 'sfx', 'fx', 'sound', 'sound effect', 'sound effects', 'music',
                  'nat sound', 'nats', 'nat', 'transition', 'cut to', 'cut', 'insert', 'overlay', 'animation',
                  'image', 'photo', 'picture', 'video', 'footage', 'montage', 'end card', 'end slate', 'slate',
                  'cutaway', 'pov', 'close up', 'close-up', 'closeup', 'wide shot', 'establishing shot', 'drone shot',
                  'screenshot', 'screen recording', 'screen', 'demo', 'map', 'logo', 'stock footage', 'action',
                  'stage direction', 'direction', 'directions', 'shot list', 'beat', 'pause', 'fade in', 'fade out',
                  'fade to black', 'v/o', 'vo', 'v.o.', 'v.o', 'o.s.', 'o.s', 'o.c.', 'voice over', 'voiceover'}
# Single words that are a tag only in capitals or inside brackets ("Show: ..." in a sentence is prose).
CAPITAL_ONLY = {'show', 'showing', 'visual', 'visuals', 'scene', 'shot', 'camera', 'cam', 'sound', 'music', 'nat',
                'transition', 'cut', 'insert', 'overlay', 'animation', 'image', 'photo', 'picture', 'video',
                'footage', 'montage', 'slate', 'screen', 'demo', 'map', 'logo', 'action', 'direction', 'directions',
                'beat', 'pause', 'text', 'caption', 'card', 'super', 'strap', 'font', 'cg', 'fx'}
_TAG = r'(?P<tag>[A-Za-z][A-Za-z0-9./ -]{0,26}?)[ \t]*(?:\((?P<tagparen>[^)\n]{0,40})\))?[ \t]*(?P<colon>:)'
# A parenthesis in a narrated line is a direction when it opens with camera, edit or sound words: "(cut to close up
# of a dripping kitchen faucet)", "(slow motion)", "(beat)". Any other parenthesis is the writer's own words.
CAMERA = re.compile(
    r'\(\s*(?:cut(?:s|ting)?\s+(?:to|away|back|in)\b|cut\s*\)|cutaway|smash\s+cut|jump\s+cut|match\s+cut|hard\s+cut|'
    r'close[- ]?ups?\b|closeup|extreme\s+close|e?cu\b(?!\w)|wide(?:\s+shot|\s+angle|\s+on)\b|medium\s+shot|long\s+shot|'
    r'two[- ]shot|over[- ]the[- ]shoulder|establishing|tracking\s+shot|aerial|drone\s+shot|overhead\s+shot|'
    r'top[- ]down\b|bird.?s[- ]eye|pov\b|angle\s+on|reverse\s+angle|shot\s+(?:of|on)\b|camera\b|cam\s|'
    r'pan(?:s|ning)?\s+(?:to|across|left|right|up|down|over)\b|tilt(?:s|ing)?\s+(?:up|down)\b|'
    r'zoom(?:s|ing)?\s+(?:in|out|on|to)\b|dolly\b|push(?:es)?\s+in\b|pull(?:s)?\s+(?:back|out|away)\b|crane\b|'
    r'fade(?:s)?\s+(?:in|out|to|up|down)\b|dissolve(?:s)?\b|wipe\s+to\b|b[- ]?roll\b|insert\s+(?:shot|of|on)\b|'
    r'montage\b|slow[- ]?mo(?:tion)?\b|freeze[- ]frame|split[- ]screen|on[- ]?screen\b|text\s+on\s+screen|'
    r'lower[- ]third|super\s*:|gfx\b|graphic(?:s)?\s*:|show(?:s|ing)?\s*:|sfx\b|sound\s+(?:of|effect)|music\s+'
    r'(?:up|in|out|swells|fades|cue|stops|drops|builds)\b|beat\s*\)|pause\s*\)|long\s+pause|v\.?\s?o\.?\s*\)|'
    r'o\.\s?[sc]\.\s*\)|voice[- ]?over|nat\s+sound|transition\b)[^)]*\)?', re.I)


def _tag(raw: str, bracketed: bool) -> str | None:
    """The kind of a tag ('text', 'strap', 'direction'), else None."""
    key = re.sub(r'\s+', ' ', raw.strip(' .').casefold())
    if key not in SCREEN_TEXT and key not in DIRECTION_TAGS:
        return None
    if key in CAPITAL_ONLY and not bracketed and not raw.strip().isupper():
        return None
    return SCREEN_TEXT.get(key, 'direction')


def notes(text: str, labels: set | None = None) -> list[dict]:
    """The directions written into ``text``: {'span': (start, end) neither said nor captioned, 'kind': 'direction',
    'text' (shown as a card) or 'strap' (a name strap), 'shown': (start, end) of the words a screen-text note shows,
    else None}. Brackets, direction parentheses, and lines that open with a direction or screen-text tag."""
    out = []
    for m in re.finditer(r'[\[(][^\[\]()\n]*(?:[\])]|$)', text):
        opener = m.group()[0]
        inner = re.match(r'[\[(]\s*' + _TAG + r'[ \t]*', m.group())
        kind = _tag(inner.group('tag'), True) if inner and inner.group('colon') == ':' else None
        if opener == '(' and kind is None and not CAMERA.match(m.group()):
            continue                                # the writer's own aside, said and captioned
        note = {'span': m.span(), 'kind': kind or 'direction', 'shown': None}
        if kind in ('text', 'strap'):
            note['shown'] = _content(text, m.start() + inner.end(), m.end() - (m.group()[-1] in ')]'))
        out.append(note)
    starts = _line_starts(text)
    for pos in starts:
        if pos and text[pos - 1] != '\n' and pos != starts[0]:
            if not re.match(r'[A-Z][A-Z0-9./ -]*[ \t]*(?:\([^)\n]*\))?[ \t]*:', text[pos:]):
                continue                            # mid-paragraph only in capitals (lines a paste ran together)
        m = re.match(_TAG + r'[ \t]*', text[pos:])
        if not m or m.group('colon') != ':' or any(a <= pos < b for n in out for a, b in [n['span']]):
            continue
        kind = _tag(m.group('tag'), False)
        if kind is None:
            continue
        end = text.find('\n', pos)
        end = len(text) if end < 0 else end
        later = [a for a, _, _ in labels_in(text, labels or set()) if pos < a < end]
        later += [p for p in starts if pos < p < end and re.match(
            r'[A-Z][A-Z0-9./ -]*[ \t]*(?:\([^)\n]*\))?[ \t]*:', text[p:])]
        end = min(later + [end])
        note = {'span': (pos, end), 'kind': kind, 'shown': None}
        if kind in ('text', 'strap'):
            note['shown'] = _content(text, pos + m.end(), end)
        out.append(note)
    return sorted(out, key=lambda n: n['span'])


def _content(text: str, a: int, b: int):
    """(start, end) of the words between ``a`` and ``b`` without spaces or the quote marks around them."""
    while a < b and (text[a].isspace() or text[a] in OPEN_QUOTES + CLOSE_QUOTES):
        a += 1
    while b > a and (text[b - 1].isspace() or text[b - 1] in OPEN_QUOTES + CLOSE_QUOTES):
        b -= 1
    return (a, b) if b > a else None


def screen_text(text: str, labels: set | None = None) -> list[tuple[int, str, str]]:
    """(position, kind, words) of each piece of on-screen text a direction asks for: 'text' for a text card
    ("[TEXT ON SCREEN: SAVE UP TO 20%]"), 'strap' for a name strap ("LOWER THIRD: Maria Chen - Owner")."""
    return [(n['span'][0], n['kind'], ' '.join(text[slice(*n['shown'])].split()))
            for n in notes(text, labels) if n['shown']]


def shown(text: str, labels: set | None = None) -> tuple[str, list[int]]:
    """The written text as a picture shows it (a kinetic headline, a quote card, a label): what the caption shows,
    "→" as "›"; a line that is only screen-text directions shows their words. With the offset in ``text`` of each
    character, so a reveal can be timed from the spoken text."""
    gone = hidden(text, labels)
    out, index = _keep(text, gone)
    if not any(ch.isalnum() for ch in out):
        words = [n['shown'] for n in notes(text, labels) if n['shown']]
        if words:
            keep = [False] * len(text)
            for a, b in words:
                keep[a:b] = [True] * (b - a)
            out, index = _keep(text, _merge([(i, i + 1) for i in range(len(text)) if not keep[i]]))
    return out.replace('→', '›'), index


# ------------------------------------------------------------------ hidden parts
def hidden(text: str, labels: set | None = None) -> list[tuple[int, int]]:
    """Character ranges of ``text`` that are neither said nor captioned (sorted, merged)."""
    labels = labels or set()
    spans = []
    found = labels_in(text, labels)
    for start, end, _ in found:
        spans.append((start, end))
    stripped = text.strip()
    whole_direction = (re.fullmatch(r'\[[^\]]*\]?|\([^)]*\)?', stripped) is not None
                       or re.match(r'(?:INT|EXT|INT\./EXT|I/E)\.\s', stripped) is not None)
    if whole_direction:
        return [(0, len(text))]
    for m in re.finditer(r'\[[^\]]*(?:\]|$)', text):
        spans.append(m.span())
    spans += [n['span'] for n in notes(text, labels)]
    if found:                                       # in a screenplay line every (parenthetical) is a direction,
        for m in re.finditer(r'\((?!\d{3}\))[^)]*(?:\)|$)', text):     # never a phone's area code
            if m.start() >= found[0][0]:
                spans.append(m.span())
    spans += markup.hidden_spans(text)              # fenced code and display formulas are pictures (markup.py)
    for m in EMOJI.finditer(text):
        spans.append(m.span())
    for m in re.finditer(r'(?<![\w*])\*{1,3}(?=\S)|(?<=\S)\*{1,3}(?![\w*])|`+|~~|^\s*#{1,6}\s+|^\s*>\s?', text, re.M):
        spans.append(m.span())
    return _merge(spans)


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        elif b > a:
            out.append((a, b))
    return out


def _keep(text: str, spans, start: int = 0, end: int | None = None, lines: bool = False) -> tuple[str, list[int]]:
    """``text[start:end]`` without ``spans``, spaces tidied (no doubles, none at the ends, none before , . ! ? ; :),
    and the offset in ``text`` of each kept character. With ``lines`` (the voice), a line break after words with no
    mark of their own is a pause: "www.example.com / hello@example.com" on two lines reads as two items."""
    end = len(text) if end is None else end
    chars, index = [], []
    hide = [False] * len(text)
    for a, b in spans:
        for i in range(max(a, start), min(b, end)):
            hide[i] = True
    for i in range(start, end):
        ch = text[i]
        if hide[i]:
            continue
        if ch.isspace():
            if lines and ch == '\n' and chars and chars[-1] == ' ' and len(chars) > 1 and chars[-2].isalnum():
                chars[-1:] = [',', ' ']
                index[-1:] = [i, i]
                continue
            if lines and ch == '\n' and chars and chars[-1].isalnum():
                chars += [',', ' ']
                index += [i, i]
                continue
            if not chars or chars[-1] == ' ':
                continue
            ch = ' '
        elif ch in ',.!?;:…)' + CLOSE_QUOTES and chars and chars[-1] == ' ' and i > 0 and hide[i - 1]:
            chars.pop()
            index.pop()
        chars.append(ch)
        index.append(i)
    while chars and chars[-1] == ' ':
        chars.pop()
        index.pop()
    return ''.join(chars), index


QUOTE_EDGE = '"“”‘’\'«»「」『』,，、;；:： \t'


def _bubble_spans(text: str, spans) -> list[tuple[int, int]]:
    """Each (start, end) of ``text`` grown over the quote marks, commas and spaces around it."""
    out = []
    for a, b in spans:
        a, b = max(0, a), min(len(text), b)
        while a > 0 and text[a - 1] in QUOTE_EDGE:
            a -= 1
        while b < len(text) and text[b] in QUOTE_EDGE:
            b += 1
        while a > 0 and b < len(text) and b > a and text[b - 1] in ' \t':
            b -= 1                                  # words on both sides keep a space between them
        out.append((a, b))
    return out


def captions(spoken: str, display: str, labels: set | None = None, bubbled=(), lang: str = 'en'
             ) -> tuple[str, str, list[int]]:
    """(spoken, display, index) for the captions: both texts without their hidden parts, and the offset in the full
    spoken text of each character of the caption's spoken text (its words keep their measured times). ``bubbled``
    is the (start, end) ranges of the spoken text a speech bubble shows: the caption leaves them (and their quote
    marks) out and carries only the narrator."""
    hide_said = hidden(spoken, labels)
    hide_shown = hidden(display, labels)
    if bubbled:
        from .numbers import normalize
        said_spans = _bubble_spans(spoken, bubbled)
        hide_said = _merge(hide_said + said_spans)
        to_spoken = normalize(display, lang).to_spoken
        inside = [any(a <= to_spoken(i) < b for a, b in said_spans) for i in range(len(display))]
        runs, i = [], 0
        while i < len(display):
            if inside[i]:
                j = i
                while j < len(display) and inside[j]:
                    j += 1
                runs.append((i, j))
                i = j
            else:
                i += 1
        hide_shown = _merge(hide_shown + _bubble_spans(display, runs))
    said, index = _keep(spoken, hide_said)
    shown, _ = _keep(display, hide_shown)
    return said, shown, index


def caption_text(display: str, labels: set | None = None) -> str:
    """The written text as a caption, transcript or subtitle shows it."""
    return _keep(display, hidden(display, labels))[0]


def drawn(text: str) -> str:
    """Text as a picture writes it (a headline, a bubble, a quote card): no emoji, which the drawing fonts have no
    glyphs for and would show as empty boxes. Line breaks are kept."""
    if not EMOJI.search(text):
        return text
    return '\n'.join(re.sub(r'[ \t]{2,}', ' ', EMOJI.sub('', line)).strip() for line in text.split('\n'))


# ------------------------------------------------------------------ voice parts
def _say(text: str, index: list[int], lang: str) -> tuple[str, list[int]]:
    """Abbreviations spelled out for the voice; each new character maps to where its abbreviation was."""
    if lang != 'en':
        return text, index
    for pattern, words in SAY_EN:
        out, out_index, last = [], [], 0
        for m in pattern.finditer(text):
            said = words(m) if callable(words) else words
            out.append(text[last:m.start()])
            out_index += index[last:m.start()]
            out.append(said)
            out_index += [index[m.start()]] * len(said)
            last = m.end()
        if last:
            out.append(text[last:])
            out_index += index[last:]
            text, index = ''.join(out), out_index
    return text, index


def _trim(said: str, index: list[int]) -> tuple[str, list[int]]:
    """No quotation marks or loose separators at the ends of a voice part ('"Mine\'s broken,"' -> "Mine's broken,")."""
    a, b = 0, len(said)
    while a < b and (said[a] in OPEN_QUOTES + CLOSE_QUOTES + ' ,;:' or said[a] == '-'):
        a += 1
    while b > a and (said[b - 1] in OPEN_QUOTES + CLOSE_QUOTES + ' '):
        b -= 1
    return said[a:b], index[a:b]


def segments(spoken: str, lang: str, labels: set | None = None, speakers=None, label_speaker=None) -> list[Segment]:
    """The voice parts of a beat, in order. ``speakers``: [(start, end, speaker)] spans of the spoken text said by
    someone other than the narrator (quotes, from ``quote_speakers``); a screenplay line is its label's person's
    (``label_speaker(name)`` -> a cast id, else 'label:<name>'). Parts with nothing to say are dropped, so a beat that
    is only a stage direction has none."""
    labels = labels or set()
    gone = hidden(spoken, labels)
    owner = [None] * len(spoken)
    lines = labels_in(spoken, labels)
    for k, (start, end, name) in enumerate(lines):
        stop = lines[k + 1][0] if k + 1 < len(lines) else len(spoken)
        who = (label_speaker(name) if label_speaker else None) or f'label:{label_key(name)}'
        for i in range(start, stop):
            owner[i] = who
    for a, b, who in speakers or ():
        if who:
            for i in range(max(0, a), min(len(spoken), b)):
                owner[i] = owner[i] if owner[i] and owner[i] != who and lines else who
    for i in range(len(spoken)):                    # an opening quote mark belongs to the words it opens
        if spoken[i] in OPEN_QUOTES and i + 1 < len(spoken) and owner[i + 1] and not owner[i]:
            owner[i] = owner[i + 1]
    out, i = [], 0
    while i < len(spoken):
        j = i
        while j < len(spoken) and owner[j] == owner[i]:
            j += 1
        text, index = _keep(spoken, gone, i, j, lines=True)
        text, index = _trim(text, index)
        text, index = _say(text, index, lang)
        if any(ch.isalnum() for ch in text):
            if out and out[-1].speaker == owner[i]:
                prev = out[-1]
                prev.said, prev.index, prev.end = prev.said + ' ' + text, prev.index + [index[0]] + index, j
            else:
                out.append(Segment(i, j, owner[i], text, index))
        i = j
    return out


def said_text(spoken: str, lang: str, labels: set | None = None) -> tuple[str, list[int]]:
    """Everything a beat says, in one voice (for read-aloud.txt, a recording or a voice server), with the map."""
    text, index = '', []
    for s in segments(spoken, lang, labels):
        if text:
            text += ' '
            index.append(s.index[0])
        text += s.said
        index += s.index
    return text, index


def spoken_times(spoken: str, index: list[int], times: list[float]) -> list[float]:
    """Time of every character of ``spoken`` from the times of the said characters mapped to it by ``index``: a
    character the voice skips (a label, a direction) takes the time of the next one said, or the last."""
    out = [None] * len(spoken)
    for k, pos in enumerate(index):
        if 0 <= pos < len(out) and k < len(times) and (out[pos] is None or times[k] < out[pos]):
            out[pos] = times[k]
    following = times[-1] if times else 0.
    for i in range(len(out) - 1, -1, -1):
        if out[i] is None:
            out[i] = following
        following = out[i]
    for i in range(1, len(out)):                    # never run backwards
        out[i] = max(out[i], out[i - 1])
    return [round(t, 3) for t in out]


# ------------------------------------------------------------------ who speaks, in which voice
FEMALE = re.compile(r'\b(?:mom|mum|mother|mama|ma|grandma|grandmother|granny|gran|nana|nan|aunt|auntie|girl|woman|'
                    r'lady|queen|princess|sister|daughter|wife|bride|mrs|ms|miss|madam|she|her|niece|grandmother)\b')
MALE = re.compile(r'\b(?:dad|father|papa|pa|grandpa|grandfather|gramps|grandad|granddad|uncle|boy|man|guy|king|'
                  r'prince|brother|son|husband|groom|mr|sir|he|him|nephew)\b')
ELDER = re.compile(r'\b(?:grandma|grandmother|granny|gran|nana|grandpa|grandfather|gramps|grandad|granddad|old|elder|'
                   r'elderly|aged)\b')
CHILD = re.compile(r'\b(?:boy|girl|kid|child|baby|little|son|daughter)\b')
TEEN = re.compile(r'\b(?:teen|teenager|student)\b')
# Installed Kokoro voices for characters by (sex, age band), best first; measured median F0 on one line (10/8):
# am_onyx 104 Hz, am_michael 119, am_puck 121, am_liam 132, bm_george 146; af_jessica 211, bf_alice 214,
# af_sarah 196, af_nicole 161, bf_emma 181, af_kore 159. The default narrator af_heart sits at 198 Hz, so a grown
# woman's first pick is the lower af_kore: her lines must not sound like the narrator's.
CHARACTER_VOICES = {
    'en': {('male', 'elder'): ['am_onyx', 'bm_george', 'bm_fable', 'am_michael'],
           ('male', 'adult'): ['am_michael', 'am_liam', 'bm_lewis', 'bm_daniel', 'am_fenrir', 'am_eric'],
           ('male', 'young'): ['am_puck', 'am_adam', 'am_echo', 'am_liam'],
           ('female', 'elder'): ['bf_emma', 'af_nova', 'af_kore', 'af_nicole'],
           ('female', 'adult'): ['af_kore', 'af_sarah', 'af_nicole', 'bf_isabella', 'af_aoede', 'af_river'],
           ('female', 'young'): ['af_jessica', 'bf_alice', 'af_bella', 'bf_lily', 'af_sky']},
    'es': {('male', 'adult'): ['em_alex', 'em_santa'], ('female', 'adult'): ['ef_dora']},
    'zh': {('male', 'adult'): ['zm_010', 'zm_020', 'zm_009', 'zm_011'],
           ('female', 'adult'): ['zf_002', 'zf_003', 'zf_004', 'zf_001']},
}
SPEEDS = {'elder': .93, 'adult': 1., 'young': 1.05}
BANDS = {'baby': 'young', 'child': 'young', 'teen': 'young', 'young': 'young', 'adult': 'adult', 'old': 'elder',
         'elder': 'elder'}


def guess_person(name: str) -> tuple[str | None, str]:
    """(sex, age band) a screenplay label or a cast name tells by itself ("GRANDPA", "Little Girl"), else (None,
    'adult')."""
    words = name.casefold()
    sex = 'female' if FEMALE.search(words) else 'male' if MALE.search(words) else None
    band = 'elder' if ELDER.search(words) else 'young' if CHILD.search(words) or TEEN.search(words) else 'adult'
    return sex, band


def cast_voices(people: list[tuple[str, str | None, str]], narrator: str, lang: str,
                available=None) -> dict:
    """speaker -> (voice, speed) for ``people`` = [(speaker, sex or None, age band)] in the order they first speak.
    Each gets an installed voice matched to their sex and age, never the narrator's and never another speaker's
    while one is left; someone whose sex is unknown alternates with the people before them."""
    table = CHARACTER_VOICES.get(lang, CHARACTER_VOICES['en'])
    available = set(available) if available is not None else None
    taken, out, unknown = {narrator}, {}, 0
    for speaker, sex, band in people:
        band = BANDS.get(band, 'adult')
        if sex not in ('male', 'female'):
            sex = ('male', 'female')[unknown % 2] if not (narrator[1:2] == 'm' and unknown == 0) else 'female'
            unknown += 1
        keys = [(sex, band), (sex, 'adult'), (sex, 'young'), (sex, 'elder')]
        options = [v for k in keys for v in table.get(k, [])] + [v for k, vs in table.items() for v in vs]
        options = [v for v in dict.fromkeys(options) if v != narrator and (available is None or v in available)]
        voice = next((v for v in options if v not in taken), next((v for v in options), narrator))
        taken.add(voice)
        out[speaker] = (voice, SPEEDS.get(band, 1.) if voice in table.get((sex, band), []) else 1.)
    return out


def quote_speakers(board_beats: list[dict], plan: dict | None):
    """(beat id -> [(start, end, speaker id)], reader, speaker -> age band when they first speak): who says each
    quotation, as speakers.attribute decides it for the voices, the bubbles and the talking figures alike, screenplay
    lines whose label names a cast member included. Needs the plan's cast; without one every quotation stays with the
    narrator (reader None)."""
    from .speakers import attribute
    said = attribute(board_beats, plan)
    return said.spans, said.reader, said.bands


TITLE_HOLD = 2.2          # seconds a silent title card holds before the first line
DIRECTION_HOLD = .8       # seconds a line that is only a stage direction holds (room for the action, no dead air)
PASSING_HOLD = .2         # seconds a direction nobody can act out takes: its page passes, never a frozen picture


def _direction_hold(text: str, people: set) -> float:
    """A line that is only a stage direction holds for its action when the page can act it out (a movement one of
    the ``people``, casefolded names, performs: engine.acting's verbs), else it passes at once: a silent hold over a
    still picture is a freeze ("a little girl jumping in puddles" on a TV screen is no one on the page)."""
    from .engine.acting import VERB_RE
    for sentence in re.split(r'(?<=[.!?;])\s+', text):
        for _, pattern in VERB_RE:
            m = pattern.search(sentence)
            before = set(re.findall(r"[\w’']+", sentence[:m.start()].casefold())) if m else ()
            if m and (before & people or before & {'he', 'she', 'they', 'everyone'}):
                return DIRECTION_HOLD
    return PASSING_HOLD


def voice_parts(board: dict, plan: dict | None, narrator: str, available=None) -> dict:
    """beat id -> {'parts': [(Segment, voice, speed factor)], 'hold': seconds of silence when nothing is said}.
    The narrator reads everything nobody else says; each character gets their own voice (cast_voices), with their
    sex and age as the storybook draws them. ``available`` is the installed voices, or a function returning them."""
    lang = board.get('lang', 'en')
    loc = lambda v: v.get(lang, next(iter(v.values()), '')) if isinstance(v, dict) else (v or '')
    beats = [{'id': b['id'], 'spoken': loc(b.get('spoken')), 'display': loc(b.get('display')),
              'section': b.get('chapter', 'main'), 'silent': bool(b.get('silent'))} for b in board['beats']]
    labels = screenplay_labels(b['display'] for b in beats)
    spans, reader, bands = quote_speakers(beats, plan)
    cast = {c['id']: c for c in ((plan or {}).get('cast') or [])}
    if reader is not None:
        cast.update(reader.by_id)                   # the extras the story mentions ('+stranger')
    from .director.v3.story import name_key

    def label_speaker(name):
        key = label_key(name)
        return next((cid for cid, c in cast.items() if c.get('name') and key in (
            name_key(c['name']), name_key(c['name']).split()[0], cid.casefold())), None)
    from .speakers import narrator_of
    me = narrator_of(beats, (plan or {}).get('cast') or [])     # "Coach Ben here": the narration is his voice
    found, order = {}, []
    for b in beats:
        segs = [] if b['silent'] else segments(b['spoken'], lang, labels, spans.get(b['id']), label_speaker)
        for seg in segs if me else ():
            seg.speaker = seg.speaker or me
        found[b['id']] = segs
        for seg in segs:
            if seg.speaker and seg.speaker not in order:
                order.append(seg.speaker)
    people = []
    for who in order:
        if who in cast:
            sex, band = _person(cast[who], who, reader)
            people.append((who, sex, bands.get(who, band)))
        else:
            people.append((who, *guess_person(who.split(':', 1)[-1])))
    if callable(available):
        available = available() if people else None     # ask the voice engine only when a character speaks
    voices = cast_voices(people, narrator, lang, available)
    people_named = {w for key in labels for w in key.split()} | {     # the cast on the page, not the story's extras
        w for c in (plan or {}).get('cast') or () for w in name_key(c.get('name') or '').split()}
    out = {}
    for b in beats:
        parts = [(s, *voices.get(s.speaker, (narrator, 1.))) for s in found[b['id']]]
        hold = None if parts else TITLE_HOLD if b['silent'] else (markup.hold(b['display'])
                                                                   or _direction_hold(b['display'], people_named))
        out[b['id']] = {'parts': parts, 'hold': hold}
    return out


def cast_of(parts: dict, one_voice: str | None = None) -> dict:
    """role -> voice for every role that speaks (the narrator as 'narrator'), from voice_parts; ``one_voice`` names
    the single voice that reads every part (a voice server, your recording)."""
    return {seg.speaker or 'narrator': one_voice or v for todo in parts.values() for seg, v, _ in todo['parts']}


def shared_voices(cast: dict) -> list[dict]:
    """Non-blocking QA findings: two speaking roles that share one voice sound like one person."""
    by_voice = {}
    for role, v in cast.items():
        by_voice.setdefault(v, []).append(role)
    return [{'defect': 'shared_voice', 'voice': v, 'roles': roles,
             'note': f"{', '.join(roles)} all speak in the voice {v}"} for v, roles in by_voice.items() if len(roles) > 1]


def _person(c: dict, cid: str, reader) -> tuple[str | None, str]:
    """A cast member's (sex, age band) as the storybook draws them: the plan's or the story's sex, else the one the
    storybook picks from the id; the age the story has reached, else the plan's."""
    from .engine.storybook import PERSON_SEX
    sex = (reader.sex(cid) if reader is not None and cid in reader.by_id else c.get('sex'))
    if sex not in ('male', 'female'):
        sex = PERSON_SEX.get(c.get('species'))
    if sex not in ('male', 'female'):               # the storybook's own pick (Storybook._look)
        seed = sum((i + 1) * ord(ch) for i, ch in enumerate(cid))
        sex = 'female' if seed % 2 else 'male'
    band = reader.age_band(cid) if reader is not None and cid in reader.by_id else c.get('age', 'adult')
    return sex, band

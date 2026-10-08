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

from . import lexicon, markup

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
    if re.match(r'\s+' + NUMBER_WORD + r'[\w-]*(?: [AP]M)?\s+to\s', m.string[m.end():]):
        word += ','                                     # "Sat 10-2" -> "Saturday, ten to two" (hours, not a time)
    elif not m.group().endswith('.') and re.match(r'\s+' + NUMBER_WORD, m.string[m.end():]):
        word += ' at'                                   # "party sat six PM" -> "Saturday at six PM"
    return _stop(m, word)


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

# Key names written as keys are said as words; the captions keep the writing. A key is written as one when it is
# joined to another by "+" or "plus" ("Ctrl + Shift + N", "Cmd+Opt+Esc"), after press/hold/hit/tap ("hit Esc",
# "hold Fn and press Del") or before "key"; Ctrl, Cmd, PgUp and the like are keys anywhere.
KEY_WORDS = {'ctrl': 'control', 'cmd': 'command', 'opt': 'option', 'alt': 'alt', 'esc': 'escape', 'del': 'delete',
             'fn': 'function', 'pgup': 'page up', 'pgdn': 'page down', 'pgdown': 'page down', 'ins': 'insert',
             'bksp': 'backspace', 'prtsc': 'print screen', 'prtscn': 'print screen', 'win': 'Windows',
             'caps': 'caps lock'}
KEYS_ANYWHERE = {'ctrl', 'cmd', 'pgup', 'pgdn', 'pgdown', 'bksp', 'prtsc', 'prtscn'}
_KEY_ABBR = r'(?:(?i:ctrl|cmd|opt|alt|esc|del|fn|pgup|pgdn|pgdown|ins|bksp|prtsc|prtscn|win|caps)\b)'
_KEY_NAMED = r'(?i:shift|control|command|option|tab|enter|escape|delete|backspace|insert|windows|super|meta)|F\d{1,2}'
_KEY = (_KEY_ABBR + r'|(?i:shift|control|command|option|tab|enter|return|space|home|end|delete|backspace|escape|'
        r'insert|windows|super|meta|up|down|left|right)\b|F\d{1,2}\b|[A-Za-z0-9](?![\w])|'
        r'(?:zero|one|two|three|four|five|six|seven|eight|nine)\b')
KEY_COMBO = re.compile(r'(?<![\w+])(?:' + _KEY + r')(?:\s*(?:\+|\bplus\b)\s*(?:' + _KEY + r'))+')
KEY_ALONE = re.compile(r'(?<![\w+])' + _KEY_ABBR + r'(?![\w+])')
_KEY_VERB = re.compile(r'\b(?:press|presses|pressed|pressing|hold|holds|held|holding|hit|hits|hitting|tap|taps|'
                       r'tapped|tapping|push|pushes|release|releases)\s+(?:(?:the|down)\s+)?$', re.I)


def _key_said(m: re.Match) -> str:
    parts = re.split(r'\s*(?:\+|\bplus\b)\s*', m.group())
    if not any(re.fullmatch(_KEY_ABBR + '|' + _KEY_NAMED, p) for p in parts):
        return m.group()                        # "2 + 2", "A + B", "up + down": no modifier, not keys
    return ' plus '.join(KEY_WORDS.get(p.lower(), p) for p in parts)


def _key_alone(text: str):
    for m in KEY_ALONE.finditer(text):
        key = m.group().lower()
        if key in KEYS_ANYWHERE or _KEY_VERB.search(text[:m.start()]) or re.match(r'\s+keys?\b', text[m.end():]):
            yield m.start(), m.end(), KEY_WORDS[key]


# Abbreviations spelled out for the voice only (captions keep the written form).
# The abbreviation lexicon (lexicon.py: titles, streets, offices, listings, kitchen, Latin, states) comes first.
SAY_EN = [(KEY_COMBO, _key_said), (_key_alone, None),
          (lexicon.say, None),
          (re.compile(r'\b(Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri)\.'), _day),
          (re.compile(r'\b(Sat|Sun)\.' + DAY_NEXT), _day),
          (re.compile(r'\b(Mon|Tues?|Wed|Thu|Thurs?|Fri|Sat|Sun|mon|tues?|wed|thu|thurs?|fri|sat|sun)\b(?!\.)' + DAY_NEXT),
           _day),
          (re.compile(r'\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.'),
           lambda m: _stop(m, MONTH_NAMES[m.group(1)[:3].lower()])),
          # The voice runs on through an abbreviation's period before a lowercase word ("Tom from Pipewise Plumbing
          # Inc. and"), and an extension never ends a sentence.
          (LAUGHS, ''),
          (re.compile(r'([!?])[!?]+'), lambda m: m.group(1)),
          (ARROW, lambda m: ('' if re.search(r'[,;:]\s*$', m.string[:m.start()] + ' ') else ', ') + 'then '
           if m.start() and m.string[:m.start()].strip() else ''),
          (re.compile(r'(?<![\w/&])(' + _shorthand + r')(?![\w/&])', re.I),
           lambda m: _shorthand_word(m)),
          (re.compile(r'(?<=\w)\s*&\s*(?=\w)|\s&\s'), ' and '),
          *lexicon.SYMBOLS,
          # Two addresses in a row ("pipewisebayside.com hello@pipewisebayside.com"): a pause after the first.
          (re.compile(r'\bdot (' + TLD_WORDS + r')(?= (?!dot\b|slash\b|at\b|dash\b)[\w])'), lambda m: m.group() + ','),
          # Two counts in a row ("3 kids 2 grandkids"): a list, with a pause between its items.
          (re.compile(r'\b' + COUNT_WORD + r'\s+(?!(?:times|equals|plus|minus|less|is|was|has|does)\b)[a-z]+s(?=\s+'
                      + COUNT_WORD + r')'), lambda m: m.group() + ','),
          # A phone number's digit groups: a short pause between them (numbers.py joins them with hyphens).
          # Not a year's "nineteen oh-three" (a teens, tens or hundred word before it).
          (re.compile(r'(?<!teen )(?<!ty )(?<!hundred )\b(zero|oh|one|two|three|four|five|six|seven|eight|nine)-(?=(?:zero|oh|one|two|three|'
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
    seen, chat = {}, set()
    for text in texts:
        for pos in _line_starts(text):
            found = _label_at(text, pos)
            if found:
                key = label_key(found[1])
                seen.setdefault(key, []).append(found[1])
                if _chat_line(text, pos):
                    chat.add(key)                   # "Dad (6:12 PM): ..." is a chat line even once
    return {key for key, names in seen.items()
            if len(names) >= 2 or key in chat or all(n.isupper() and len(re.sub(r'\W', '', n)) >= 2 for n in names)}


def _line_starts(text: str) -> list[int]:
    """Where a screenplay line can start inside a beat: its first character, a line break, or (for lines a paste
    joined into one paragraph) right after a sentence end."""
    starts = [len(text) - len(text.lstrip())]
    starts += [m.end() for m in re.finditer(r'\n[ \t]*', text)]
    starts += [m.end() for m in re.finditer(r'[.!?…—)\]]["”’]?[ \t]+(?=[^\W\d_]+[ \t]*(?:\([^)\n]*\))?[ \t]*:)', text)
               if not TITLE_STOP.search(text, 0, m.start() + 1)]       # "MRS. OKAFOR:" is one label
    return sorted(set(starts))


TITLE_STOP = re.compile(r'\b(?:mr|mrs|ms|dr|prof|st|sgt|capt|lt|col|gen|rev|fr|sr|jr|hon|gov|sen|rep|pres|supt|insp|'
                        r'det|cpl|pvt|adm|cmdr)\.$', re.I)


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
    r'o\.\s?[sc]\.\s*\)|voice[- ]?over|nat\s+sound|transition\b|'
    r'(?:(?:long(?:er)?|short|brief|small|little|quick|slight|dramatic)\s+)?(?:pause|silence)\b|'
    r'(?:hold|rest|wait)\s+for\s+(?:a\s+count\s+of\s+)?\w+\s*(?:s|secs?|seconds?|counts?|beats?)?\s*\)|'
    r'\w+[\s-]*(?:s|secs?|seconds?)\s+(?:of\s+)?(?:pause|silence)\b)[^)]*\)?', re.I)


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
            if lines and ch == '\n' and chars and chars[-1] == '.':
                chars.append('\n')             # kept for _say: "Elm St." ends its line, no title of the next line's name
                index.append(i)
                continue
            if not chars or chars[-1] in ' \n':
                continue
            ch = ' '
        elif ch in ',.!?;:…)' + CLOSE_QUOTES and chars and chars[-1] == ' ' and i > 0 and hide[i - 1]:
            chars.pop()
            index.pop()
        chars.append(ch)
        index.append(i)
    while chars and chars[-1] in ' \n':
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
        return text.replace('\n', ' '), index
    for pattern, words in SAY_EN:
        out, out_index, last = [], [], 0
        found = pattern(text) if words is None else (
            (m.start(), m.end(), words(m) if callable(words) else words) for m in pattern.finditer(text))
        for start, end, said in found:
            out.append(text[last:start])
            out_index += index[last:start]
            out.append(said)
            out_index += [index[start]] * len(said)
            last = end
        if last:
            out.append(text[last:])
            out_index += index[last:]
            text, index = ''.join(out), out_index
    return text.replace('\n', ' '), index


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
        if _chat_line(spoken, start):
            continue                                # "Dad (7:02 AM): ..." is a text on a phone: the narrator reads it
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


def _chat_line(text: str, start: int) -> bool:
    """A screenplay line whose label carries a time ("Dad (7:02 AM): ...") is a chat transcript line."""
    from .ui_screens import chat_time
    m = LABEL.match(text, start)
    return bool(m and chat_time(m.group('paren')))


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
# Words that tell a person's sex and age (the voices' own lists): titles, kin and role words, female and male animals,
# young animals and children's words. A given name only decides the sex when nothing in the text does.
FEMALE = re.compile(r"\b(?:mom|mommy|mum|mummy|mother|mama|ma|stepmom|stepmother|grandma|grandmother|granny|gran|nana|"
                    r"nan|grammy|nainai|abuela|oma|aunt|auntie|aunty|tia|tía|girl|woman|women|lady|ladies|gal|lass|"
                    r"queen|princess|empress|duchess|countess|baroness|sister|sis|daughter|granddaughter|niece|wife|"
                    r"bride|widow|girlfriend|godmother|mrs|ms|miss|madam|madame|ma['’]am|señora|senora|señorita|"
                    r"mademoiselle|she|her|hers|herself|actress|waitress|hostess|stewardess|policewoman|"
                    r"businesswoman|chairwoman|spokeswoman|congresswoman|saleswoman|nun|heroine|goddess|witch|"
                    r"sorceress|ballerina|maiden|schoolgirl|lioness|lionesses|tigress|mare|filly|hen|ewe|doe|vixen|"
                    r"cow|heifer|nanny\s+goat)\b", re.I)
MALE = re.compile(r"\b(?:dad|daddy|father|papa|pa|pop|stepdad|stepfather|grandpa|grandfather|gramps|grampa|grandad|"
                  r"granddad|grandpop|yeye|abuelo|opa|uncle|tio|tío|boy|man|men|guy|gentleman|gentlemen|lad|fellow|"
                  r"dude|bro|king|prince|emperor|duke|baron|brother|son|grandson|nephew|husband|groom|widower|"
                  r"boyfriend|godfather|mr|sir|mister|lord|señor|senor|monsieur|he|him|his|himself|waiter|"
                  r"steward|policeman|businessman|chairman|spokesman|congressman|salesman|fireman|monk|friar|"
                  r"wizard|sorcerer|schoolboy|stallion|colt|rooster|cockerel|bull|buck|ram|boar|drake|gander|"
                  r"billy\s+goat)\b", re.I)
ELDER = re.compile(r"\b(?:grandma|grandmother|granny|gran|nana|grammy|nainai|abuela|oma|grandpa|grandfather|gramps|"
                   r"grampa|grandad|granddad|grandpop|yeye|abuelo|opa|great[- ]grand\w*|old|elder|elderly|aged|"
                   r"ageing|aging|senior|retired)\b", re.I)
CHILD = re.compile(r"\b(?:kid|kids|kiddo|child|children|baby|babies|toddler|infant|newborn|little|tiny|wee|youngster|"
                   r"boy|girl|schoolboy|schoolgirl|preschooler|kindergartner|cub|cubs|kitten|puppy|pup|chick|"
                   r"duckling|gosling|cygnet|foal|filly|colt|calf|lamb|piglet|fawn|joey|hatchling|tadpole|fledgling|"
                   r"nestling|owlet|eaglet|bunny)\b", re.I)
TEEN = re.compile(r"\b(?:teen|teens|teenager|teenage|adolescent|high[- ]schooler)\b", re.I)
# Common given names that tell a sex by themselves (the last fallback: the text's own words win over a name).
FEMALE_NAMES = set("""
abigail ada adaeze adriana aisha alice alicia aliyah alma amanda amara amelia amina amy ana anna annie aria ariana
ashley aubrey audrey ava bella beth betty bianca brenda brianna camila carla carmen caroline catherine charlotte chloe
christina claire clara daisy daniela diana elena eliza elizabeth ella ellie emily emma esther eva evelyn fatima fiona
gabriela grace gloria hannah harper hazel helen ines irene isabel isabella ivy jane janet jasmine jenna jennifer
jessica joan julia julie kate katie keisha kimberly laura layla leah lena lily linda lisa lucia lucy luna lydia maria
marisol martha mary maya mei melissa mia michelle mila molly monica nadia naomi natalia nina nora olivia paula
penelope priya rachel rebecca rosa rose ruby ruth sakura samantha sara sarah sofia sophia sophie stella susan
valentina victoria violet wendy yuki zara zoe zoey
""".split())
MALE_NAMES = set("""
aaron adam ahmed alan albert alejandro andre andrew anthony arjun arthur ben brandon brian bruno caleb carlos
charles charlie chris christopher colin daniel david dev diego dmitri dylan eli elijah ethan felix frank gabriel
george greg harry henry hiroshi hugo ian isaac jack jacob jake james jason javier jeff jim joe john jonah jorge jose
joseph josh juan julian kenji kevin kofi kwame leo liam logan lucas luis luke marco marcus mark mateo matt matthew max
michael miguel mike mohammed muhammad nathan nick noah oliver omar oscar owen pablo patrick paul pedro peter rafael raj
ravi ricardo rob robert ryan sam samuel santiago scott sean sebastian simon steve steven theo thomas tim tom tony
victor vincent walter will william wyatt xavier yusuf zach
""".split())
YEARS_OLD = re.compile(r"\b(?P<n>[\w]+(?:-[\w]+)?)[\s-]+years?[\s-]+old\b", re.I)
_PERSON_WORDS = re.compile('|'.join(p.pattern for p in (FEMALE, MALE, ELDER, CHILD, TEEN, YEARS_OLD)), re.I)
PRONOUNS = {'she', 'her', 'hers', 'herself', 'he', 'him', 'his', 'himself'}
DETERMINERS = r'(?:a|an|the|his|her|their|my|our|your|this|that|one)'
# Installed Kokoro voices for characters by (sex, age band), best first; measured median F0 on one line (10/8):
# am_onyx 88-104 Hz, am_michael 119-132, am_puck 120, am_liam 128-132, bm_george 146; af_jessica 205-211, bf_alice
# 214, af_sarah 196-214, af_nicole 161, bf_emma 181, af_kore 157-159. The default narrator af_heart sits at 198-212
# Hz, so a grown woman's first pick is the lower af_kore: her lines must not sound like the narrator's. Kokoro has no
# child voices: a child or a young animal reads in a light voice raised four semitones ("+4", voice.base_voice):
# af_jessica+4 270 Hz, bf_lily+4 270, af_bella+4 264, bf_alice+4 286 (a young child speaks at about 250-300 Hz).
CHARACTER_VOICES = {
    'en': {('male', 'elder'): ['am_onyx', 'bm_george', 'bm_fable', 'am_michael'],
           ('male', 'adult'): ['am_michael', 'am_liam', 'bm_lewis', 'bm_daniel', 'am_fenrir', 'am_eric'],
           ('male', 'young'): ['am_puck', 'am_adam', 'am_echo', 'am_liam'],
           ('male', 'child'): ['af_jessica+4', 'af_bella+4', 'bf_alice+4', 'bf_lily+4'],
           ('female', 'elder'): ['bf_emma', 'af_nova', 'af_kore', 'af_nicole'],
           ('female', 'adult'): ['af_kore', 'af_sarah', 'af_nicole', 'bf_isabella', 'af_aoede', 'af_river'],
           ('female', 'young'): ['af_jessica', 'bf_alice', 'af_bella', 'bf_lily', 'af_sky'],
           ('female', 'child'): ['bf_lily+4', 'af_bella+4', 'bf_alice+4', 'af_jessica+4']},
    'es': {('male', 'adult'): ['em_alex', 'em_santa'], ('female', 'adult'): ['ef_dora']},
    'zh': {('male', 'adult'): ['zm_010', 'zm_020', 'zm_009', 'zm_011'],
           ('female', 'adult'): ['zf_002', 'zf_003', 'zf_004', 'zf_001']},
}
SPEEDS = {'elder': .93, 'adult': 1., 'young': 1.05, 'child': 1.05}
# Story age bands (director.v3.story.band) and plan ages -> voice bands. A plan's "young" person is a child or a
# teen: they read as a teen unless the text says child; a young animal (a cub) reads as a child.
BANDS = {'baby': 'child', 'child': 'child', 'teen': 'young', 'young': 'young', 'adult': 'adult', 'old': 'elder',
         'elder': 'elder'}


def _band_of_words(words: str) -> str | None:
    """The age band words tell ("a tiny lion cub" child, "a ten-year-old" child, "an elderly" elder), else None."""
    from .director.v3.story import band, number
    m = YEARS_OLD.search(words)
    years = number(m['n'].replace('-', ' ')) if m else None
    if years is not None:
        return BANDS[band(years)]
    return 'elder' if ELDER.search(words) else 'young' if TEEN.search(words) else \
        'child' if CHILD.search(words) else None


def _sex_of_words(words: str) -> str | None:
    female, male = len(FEMALE.findall(words)), len(MALE.findall(words))
    return 'female' if female > male else 'male' if male > female else None


def name_sex(name: str) -> str | None:
    """The sex a given name tells by itself (the first word of ``name`` that is a known given name), else None."""
    for word in re.findall(r"[^\W\d_][\w’'-]*", name or ''):
        word = word.casefold()
        if word in FEMALE_NAMES or word in MALE_NAMES:
            return 'female' if word in FEMALE_NAMES else 'male'
    return None


def guess_person(name: str) -> tuple[str | None, str]:
    """(sex, age band) a screenplay label or a name tells by itself ("GRANDPA", "Little Girl", "Mrs. Ortiz"), its
    given name last ("Maria Chen"), else (None, 'adult')."""
    return _sex_of_words(name) or name_sex(name), _band_of_words(name) or 'adult'


def described(name: str, texts) -> tuple[str | None, str | None]:
    """(sex, age band) the story's own words tie to the person called ``name``, outside quotations, else None each:
    words in the name ("Aunt Rosa", "King Kojo") and in a noun phrase naming them ("a tiny lion cub named Pendo",
    "his mother, Mara", "Mara, the pride's lioness", "Pendo the cub", "Ava is a ten-year-old girl", "little Pendo").
    Pronouns in those phrases belong to someone else ("his mother, Mara") and never count."""
    from .director.v3.semantics import name_key
    key = name_key(name or '')
    proper = [w.casefold() for w in re.findall(r"[^\W\d_][\w’'-]*", name or '')      # "Maria", "Chen"; never
              if w[:1].isupper() and len(w) > 2 and "'" not in w and '’' not in w   # "Theo's" or "Mother"
              and not _PERSON_WORDS.fullmatch(w) and w.casefold() in key.split()]
    keys = [k for k in dict.fromkeys([key] + proper) if k]
    sexes = [x for x in [_sex_of_words(name or '')] if x]
    bands = [x for x in [_band_of_words(name or '')] if x]
    if keys:
        found = re.compile(r'(?<![\w’\'])(?:' + '|'.join(re.escape(k) for k in keys) + r')(?![\w’\'])', re.I)
        word = r"[\w’'-]+"
        for text in texts:
            text = re.sub(r'["“][^"”]*["”]?', lambda m: ' ' * len(m.group()), text)      # never inside a quote
            for m in found.finditer(text):
                before = re.split(r'[.!?;:()\[\]\n]', text[:m.start()])[-1]
                after = re.split(r'[.!?;:()\[\]\n]', text[m.end():])[0]
                phrases = []
                head = r'(?:' + word + r'\s+){0,3}?(?=\S)(?:' + _PERSON_WORDS.pattern + r')'
                named = re.search(r'\b(?:a|an|one)\s+((?:' + word + r'\s+){0,4})(?:named|called)\s+$|\b' +
                                  DETERMINERS + r'\s+((?:' + word + r'\s+){0,4})named\s+$', before, re.I)
                if named:                                                       # "a tiny lion cub named Pendo"
                    phrases.append(named[1] or named[2])
                apposed = re.search(r'\b' + DETERMINERS + r'\s+(' + head + r')\s*[,–—]\s*$', before, re.I)
                if apposed:                                                     # "his mother, Mara"
                    phrases.append(apposed[1])
                title = re.search(r'(?:^|\s)(' + word + r')\.?\s+$', before)
                if title:                                                       # "Aunt Rosa", "little Pendo"
                    phrases.append(title[1])
                follow = re.match(r'(?:\s*[,–—]\s*|\s+(?:is|was)\s+)?\s*' + DETERMINERS + r'\s+(' + head +
                                  r')(?=\s*(?:[,.;:!?–—]|$|\band\b|\bwho\b))', after, re.I)
                if follow and (follow.group().lstrip()[:1] in ',–—' or re.match(r'\s+(?:is|was|the)\s', after)):
                    phrases.append(follow[1])                                   # "Mara, his mother", "Pendo the cub"
                for phrase in phrases:
                    words = ' '.join(w for w in phrase.split() if w.casefold() not in PRONOUNS)
                    sexes += [x for x in [_sex_of_words(words)] if x]
                    bands += [x for x in [_band_of_words(words)] if x]
    pick = lambda xs: max(dict.fromkeys(xs), key=xs.count) if xs else None
    return pick(sexes), pick(bands)


def voice_sex(voice_id: str) -> str | None:
    """The sex of a Kokoro voice id ("af_heart" female, "bm_george" male, "af_jessica+4" female)."""
    return {'f': 'female', 'm': 'male'}.get((voice_id or '')[1:2])


def cast_voices(people: list[tuple[str, str | None, str]], narrator: str, lang: str,
                available=None) -> dict:
    """speaker -> (voice, speed) for ``people`` = [(speaker, sex or None, age band)] in the order they first speak.
    Each gets an installed voice matched to their sex and age, never the narrator's and never another speaker's
    while one is left; someone whose sex is unknown alternates with the people before them."""
    from .voice import base_voice
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
        options = [v for v in dict.fromkeys(options) if v != narrator and (available is None or
                                                                          base_voice(v)[0] in available)]
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


# ------------------------------------------------------------------ pacing: the silence between and inside sentences
# Voice-free seconds the narration leaves (the hand-made references hold .3-.4 s between sentences, the stated length
# for a written pause, and about 1.3 s from one counted breath to the next).
SENTENCE_GAP = .35        # between two sentences of a beat
TRAIL_GAP = .6            # a thought that trails off ("the north is just... on the bottom")
COUNT_STEP = 1.25         # a count ("in... two... three... four"): from the start of one count to the start of the next
BEAT_GAP = 1.4            # after a line that trails off or breaks off ("Mom..."), before the next line: a dramatic beat
STANZA_GAP = 2.0          # after the last line of a stanza in verse (the references rest about 2 s)
LINE_BREATH = .55         # a line of verse that breaks inside its sentence: a short breath before the next line
PAUSE_SECONDS = 3.0       # "(pause)" with no length
BEAT_SECONDS = 1.2        # "(beat)"
PAUSE_WORDS = {'long': 5., 'longer': 5., 'short': 1.5, 'brief': 1.5, 'small': 1.5, 'little': 1.5, 'quick': 1.,
               'slight': 1., 'dramatic': 2.}
NUMBER_WORDS = {w: k for k, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve '
                                           'thirteen fourteen fifteen sixteen seventeen eighteen nineteen '
                                           'twenty'.split())}
_NUM = r'(?:\d+(?:\.\d+)?|' + '|'.join(NUMBER_WORDS) + r')'
_UNIT = r'(?:s|secs?|seconds?|counts?|beats?)'
PAUSE_NOTE = re.compile(
    r'(?:(?P<adj>' + '|'.join(PAUSE_WORDS) + r')\s+)?(?P<what>pause|silence|beat|hold|rest|wait)'
    r'(?:\s*(?:for|of|,|:|-)?\s*(?:a\s+count\s+of\s+)?(?P<n>' + _NUM + r')(?:[\s-]*' + _UNIT + r')?)?'
    r'|(?P<n2>' + _NUM + r')[\s-]*' + _UNIT + r'?\s+(?:of\s+)?(?:pause|silence|hold|rest)', re.I)
# A spoken instruction to hold or breathe for a count ("Hold for four.", "Now rest for ten seconds.", "Exhale for
# six."): the voice then waits that long.
HOLD_SAID = re.compile(r'\W*(?:(?:and|now|then|just|gently|so)\W+)*(?:hold|pause|rest|wait|stay|inhale|exhale|'
                       r'breathe(?:\s+(?:in|out))?)\b'
                       r'(?:\s+(?:it|still|there|here|your\s+breath|the\s+breath|gently|softly))*\s+for\s+'
                       r'(?:a\s+count\s+of\s+)?(?P<n>' + _NUM + r')(?:\s+(?:seconds?|counts?|beats?))?\W*', re.I)


def _number(word: str) -> float:
    return float(word) if word[:1].isdigit() else float(NUMBER_WORDS[word.casefold()])


def line_breaths(display: str, spoken: str, line_starts, lang: str = 'en') -> list[tuple[int, float, None, float]]:
    """Verse: a stop (speech.pace's shape) of LINE_BREATH before each line that goes on with the sentence of the line
    before it ("and sets them down / in places..."); ``line_starts`` are the display's words that start a line."""
    from .numbers import normalize
    if lang == 'zh' or not line_starts:
        return []
    words = list(re.finditer(r'\S+', display))
    to_spoken = normalize(display, lang).to_spoken
    out = []
    for k in line_starts:
        if 0 < k < len(words) and not re.search(r'[.!?…][”"’)\]]*$', words[k - 1].group()):
            pos = to_spoken(words[k].start())
            if 0 < pos < len(spoken):
                out.append((pos, LINE_BREATH, None, 0.))
    return out


def pause_seconds(note: str) -> float | None:
    """Seconds of silence a written pause asks for ("[pause 3 seconds]", "(pause)", "[3 s pause]", "(hold for
    four)", "(beat)"; a count is a second), else None. ``note`` is the direction with or without its brackets."""
    inner = note.strip().strip('[]()').strip(' .:')
    m = PAUSE_NOTE.fullmatch(inner)
    if not m:
        return None
    n = m.group('n') or m.group('n2')
    if n:
        return min(60., _number(n))
    if m.group('what').casefold() in ('hold', 'rest', 'wait'):
        return None                                 # "(hold)" alone is a pose, not a length
    if m.group('adj'):
        return PAUSE_WORDS[m.group('adj').casefold()]
    return BEAT_SECONDS if m.group('what').casefold() == 'beat' else PAUSE_SECONDS


def pace(spoken: str, lang: str = 'en', labels: set | None = None) -> list[tuple[int, float, int | None, float]]:
    """Where a beat's voice stops for a moment: [(pos, gap, anchor, step)], each asking for at least ``gap`` seconds
    of voice-free time before the character at ``pos`` of the spoken text (pos == len(spoken): after the beat, before
    the next one) and, with an ``anchor``, the start of the word at ``pos`` at least ``step`` seconds after the start
    of the word at ``anchor`` (a counted breath). Sentences get SENTENCE_GAP; a trailing ellipsis TRAIL_GAP; counts
    COUNT_STEP; a written pause ("[pause 4 seconds]", never said or shown) its own length; a spoken "hold for four"
    four seconds; a line that trails or breaks off at the beat's end BEAT_GAP."""
    from .ingest import _protect_periods
    if lang == 'zh':
        return []
    stops = {}

    def add(pos, gap, anchor=None, step=0.):
        old = stops.get(pos)
        stops[pos] = (pos, max(gap, old[1] if old else 0.), anchor if anchor is not None else old and old[2],
                      max(step, old[3] if old else 0.))

    def next_word(i):                             # the next word the voice says
        for m in re.finditer(r'\w+', spoken[i:]):
            if not any(a <= i + m.start() < b for a, b in gone):
                return i + m.start(), m.group()
        return len(spoken), ''
    gone = hidden(spoken, labels)
    for a, b in gone:
        seconds = pause_seconds(spoken[a:b])
        if seconds:
            add(next_word(b)[0], seconds)
    shielded = _protect_periods(spoken, lang)
    for m in re.finditer(r'\.', spoken):           # an abbreviation's period ends a sentence only where one ends
        known = lexicon.abbreviation_period(spoken[:m.end()], spoken[m.end():]) if lang == 'en' else None
        if known is not None:
            shielded = shielded[:m.start()] + ('\0' if known else '.') + shielded[m.end():]
    for a, b in gone:                                 # nothing inside a direction ends a sentence
        shielded = shielded[:a] + '\0' * (b - a) + shielded[b:]
    begun = 0
    for m in re.finditer(r'(\.{2,}|…|[.!?]+)["”’)\]]*(?=\s|$)', shielded):
        pos, word = next_word(m.end())
        if not word:
            pos = len(spoken)
        sentence = spoken[begun:m.end()]
        held = HOLD_SAID.fullmatch(sentence.strip())
        if held:
            add(pos, min(60., _number(held.group('n'))))
        if pos == len(spoken):
            if m.group(1) in ('…',) or m.group(1).startswith('..'):
                add(pos, BEAT_GAP)
            break
        if m.group(1) == '…' or m.group(1).startswith('..'):
            if word.casefold() in NUMBER_WORDS or word.isdigit():
                before = list(re.finditer(r'\w+', spoken[:m.start()]))
                add(pos, .25, before[-1].start() if before else None, COUNT_STEP)
            else:
                add(pos, TRAIL_GAP)
            if word[:1].islower() or word.casefold() in NUMBER_WORDS:
                continue                              # the same sentence goes on
        else:
            add(pos, SENTENCE_GAP)
        begun = m.end()
    if re.search(r'(?:—|--|–)\s*["”’)]*\s*$', spoken.rstrip()):
        add(len(spoken), BEAT_GAP)
    return [stops[k] for k in sorted(stops)]


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
    """beat id -> {'parts': [(Segment, voice, speed factor)], 'hold': seconds of silence when nothing is said, and for
    a beat that is only a written pause ("[pause 3 seconds]") 'pause': the voice-free seconds it asks for}.
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
    from .speakers import introduced, narrator_of
    texts = [b['spoken'] for b in beats]
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

    def person(who):
        if who in cast:
            return _person(cast[who], who, reader, texts, bands)
        said = ' '.join(seg.said for segs in found.values() for seg in segs if seg.speaker == who)
        named = introduced(said, list(cast.values()), sign_off=True)     # "REPORTER: ... Jenna Ruiz, Channel 4 News."
        if named in cast:
            return _person(cast[named], named, reader, texts, bands)
        return guess_person(named or who.split(':', 1)[-1])
    people = [(who, *person(who)) for who in order]
    if not me:                                  # a narrator not in the cast who names themselves: "Coach Ben here"
        named = introduced(' '.join(seg.said for segs in found.values() for seg in segs if seg.speaker is None), [])
        sex, band = guess_person(named) if named else (None, 'adult')
        if sex and (sex != voice_sex(narrator) or band != 'adult'):
            if callable(available):
                available = available()
            narrator = cast_voices([(None, sex, band)], narrator, lang, available)[None][0]
    if callable(available):
        available = available() if people else None     # ask the voice engine only when a character speaks
    voices = cast_voices(people, narrator, lang, available)
    if me and me in voices:                     # a narrator who sounds like the project's voice keeps it
        _, sex, band = next(p for p in people if p[0] == me)
        if sex == voice_sex(narrator) and band == 'adult':
            voices[me] = (narrator, 1.)
    people_named = {w for key in labels for w in key.split()} | {     # the cast on the page, not the story's extras
        w for c in (plan or {}).get('cast') or () for w in name_key(c.get('name') or '').split()}
    out = {}
    for b in beats:
        parts = [(s, *voices.get(s.speaker, (narrator, 1.))) for s in found[b['id']]]
        pause = None if parts or b['silent'] else pause_seconds(b['display'])
        hold = None if parts else TITLE_HOLD if b['silent'] else (markup.hold(b['display']) or pause
                                                                   or _direction_hold(b['display'], people_named))
        out[b['id']] = {'parts': parts, 'hold': hold, **({'pause': pause} if pause else {})}
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


def person_sex(c: dict, cid: str, reader, texts=(), told: str | None = None) -> str:
    """A cast member's sex, one answer for their voice and their drawing (Storybook._look): what the story's words
    tie to them ("his mother, Mara", "King Kojo"; ``told`` when already read), else the plan's or the story's
    pronouns, else their species word ("lioness"), else their given name ("Maria"), else a pick from the id that
    keeps people with no cue apart: of two such people one is drawn and voiced a man and the other a woman."""
    sex = _cued_sex(c, cid, reader, texts, told)
    if sex not in ('male', 'female'):
        sex = _uncued_sex(cid, reader, texts)
    return sex


def _cued_sex(c: dict, cid: str, reader, texts=(), told: str | None = None) -> str | None:
    sex = told or described(c.get('name') or '', texts)[0]
    if sex not in ('male', 'female'):
        sex = reader.sex(cid) if reader is not None and cid in reader.by_id else c.get('sex')
    if sex not in ('male', 'female'):
        from .engine.storybook import PERSON_SEX, species_base
        species = str(c.get('species') or '')
        base, implied, _ = species_base(species)              # plural or young words: "hens", "kings", "girls"
        sex = (PERSON_SEX.get(base) or implied or PERSON_SEX.get(species) or _sex_of_words(species)
               or _sex_of_words(base) or name_sex(c.get('name') or ''))
    return sex if sex in ('male', 'female') else None


def _uncued_sex(cid: str, reader, texts=()) -> str:
    """The sex of a cast member nothing in the story or plan sexes: the same person at another age ('jo_old') is
    them; the people with no cue alternate in cast order from the first one's pick, so two of them (a couple, a pair
    of friends) never read as the same person twice."""
    def pick(key):
        return 'female' if sum((i + 1) * ord(ch) for i, ch in enumerate(key)) % 2 else 'male'
    cast = getattr(reader, 'by_id', None) or {}
    if cid not in cast:
        return pick(cid)
    from .engine.shots import same_person
    base = same_person(cast, cid)
    if base != cid:
        return person_sex(cast[base], base, reader, texts)
    uncued = [k for k, d in cast.items() if same_person(cast, k) == k and _cued_sex(d, k, reader, texts) is None]
    if len(uncued) < 2:
        return pick(cid)
    first = pick(uncued[0])
    return first if uncued.index(cid) % 2 == 0 else ('female' if first == 'male' else 'male')


def _person(c: dict, cid: str, reader, texts=(), bands=None) -> tuple[str | None, str]:
    """A cast member's (sex, age band) for their voice. Sex: what the story's words tie to them ("his mother, Mara",
    "King Kojo"), else the plan's or the story's pronouns, else their species word ("lioness"), else their given name,
    else the one the storybook draws from the id. Age: the age the story states for them when they first speak, else
    the story's words ("a tiny lion cub named Pendo"), else the plan's ("baby" a child; "young" a teen, or a child
    for a young animal), else their name's or species' words."""
    told_sex, told_band = described(c.get('name') or '', texts)
    sex = person_sex(c, cid, reader, texts, told_sex)
    species = str(c.get('species') or '')
    stated = reader is not None and cid in reader.by_id and (cid in reader.first_years or c.get('band') or
                                                              reader.told(cid))     # "Uncle Dev": as drawn
    if stated:
        band = BANDS.get((bands or {}).get(cid) or reader.age_band(cid), 'adult')
    elif told_band:
        band = told_band
    elif c.get('age') in ('young', 'baby') and c.get('kind') not in (None, 'human', 'object'):
        band = 'child'                              # a cub, a chick, a puppy
    else:
        band = BANDS.get(c.get('age')) or _band_of_words(species) or 'adult'
    return sex, band

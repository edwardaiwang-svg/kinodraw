"""Device screens and text messages a script describes, read from its words (no drawing here; engine/ui_screens.py
draws them).

Three readings, all general word lists (apps, devices, UI verbs), never one script's nouns:

- ``quote_kind(sentence, quote_at, before)``: is a quotation text shown on a screen or a page (a text message, a
  notification, a button's label, a sign) rather than words someone says aloud? Shown text is read by the narrator
  and drawn on its device; only a quotation the script says someone says keeps their voice and a speech bubble.
- ``chat_time(label paren)``: a chat transcript line ("Dad (7:02 AM): ...") is a message, its time small UI text.
- ``read(beats, cast)``: the screen moments of a script, in order: each one a device (phone portrait; laptop or
  tablet landscape when the words say so), an app name, and the elements the words name (list rows, tabs, a button,
  an input field, a code box, a QR square, a notification banner, a check mark, a toggle, an avatar), each at the
  character where it is named so the picture lights it on that word; or a message thread (its name, sender names,
  incoming and outgoing bubbles, timestamps, emoji). Every on-screen string is cut from the script's own words.
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ word lists
DEVICES = (('laptop', r'laptops?|computers?|desktops?|pcs?|macbooks?|browsers?|web\s?sites?|web\s?pages?|'
                      r'monitors?|chromebooks?'),
           ('tablet', r'tablets?|ipads?'),
           ('phone', r'phones?|smartphones?|cell\s?phones?|cells|mobiles?|iphones?|androids?|lock\s?screens?'))
DEVICE = re.compile(r'\b(?:' + '|'.join(p for _, p in DEVICES) + r')\b', re.I)
# The device something is on: "on your laptop", "into the box on your phone", "on the laptop screen".
ON_DEVICE = re.compile(r'\b(?:on|in|into|onto)\s+(?:your|the|a|my|his|her|their|our)?\s*(?P<d>'
                       + '|'.join(p for _, p in DEVICES) + r')\b', re.I)
UI_VERB = (r'tap|taps|tapped|tapping|click|clicks|clicked|clicking|press|presses|pressed|pressing|hit|'
           r'select|selects|selected|selecting|choose|chooses|chose|choosing|pick|picks|picked|'
           r'swipe|swipes|swiped|scan|scans|scanned|toggle|toggles|toggled|enable|enables|enabled|'
           r'open|opens|opened|launch|launches|launched|go\s+to|goes\s+to|went\s+to|head\s+to|navigate\s+to')
INPUT_VERB = r'type|types|typed|typing|enter|enters|entered|entering|paste|pastes|pasted|fill\s+in|key\s+in'
# A word naming the part of the screen ("the Security tab", "the + button").
PART = {'button': 'button', 'buttons': 'button', 'icon': 'button', 'link': 'button', 'tab': 'tab', 'tabs': 'tab',
        'menu': 'row', 'option': 'row', 'setting': 'row', 'settings': 'row', 'item': 'row', 'entry': 'row',
        'toggle': 'toggle', 'switch': 'toggle', 'checkbox': 'toggle', 'field': 'input', 'box': 'input'}
ACTION_LABEL = r'get|start|continue|next|done|ok|save|verify|sign|log|submit|send|turn|switch|enable|allow'
CONFIRM = re.compile(r'^(?:verify|confirm|done|save|submit|finish|ok|okay|send|apply|activate|continue|next)\b', re.I)
SOFTWARE_VERB = (r'shows|builds|keeps|sends|lets|tracks|gives|reminds|tells|saves|fixes|lists|finds|asks|opens|'
                 r'displays|pings|alerts|suggests|scans|sorts|counts|logs|checks|notifies|updates|syncs')
APP_WORD = re.compile(r'\b(?:apps?|application|website|site|account|inbox|settings|screen|notifications?|'
                      r'download|log\s?in|sign\s?in|password)\b', re.I)
COLOURS = ('green', 'yellow', 'red', 'orange', 'blue', 'purple', 'grey', 'gray', 'pink', 'white', 'black')
LEGEND = re.compile(r'\b(?P<c>' + '|'.join(COLOURS) + r')\s+(?:means|is\s+for|=|shows|marks)\s+(?P<l>[^.;!?\n]+)',
                    re.I)
CODE_DIGITS = re.compile(r'(?<![\w$£€.,:])\d{3}[ -]\d{3}(?![\w.,:%]\d)|(?<![\w$£€.,:])\d{4,8}(?![\w%]|[.,:]\d)')
DIGIT_COUNT = re.compile(r'\b(?P<n>\d|one|two|three|four|five|six|seven|eight)[- ]digit\s+(?:code|pin|number)\b', re.I)
NUMBER_WORD = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8}
QR = re.compile(r'\b(?:qr(?:\s+code)?|square\s+code|bar\s?code|scan\s+the\s+code)\b', re.I)
NOTIFY = re.compile(r'\b(?:notifications?|nudges?|alerts?|reminders?|banners?|pop-?ups?|push(?:\s+notifications?)?|'
                    r'pings?)\b', re.I)
CHECK = re.compile(r'\b(?:check\s?marks?|tick(?:s|ed)?|green\s+check|verified|all\s+set)\b', re.I)
AVATAR = re.compile(r'\b(?:your|the|my)\s+(?:initials|avatar|profile\s+(?:picture|photo|icon)|profile)\b', re.I)
INPUT_NOUN = r'code|password|passcode|pin|email(?:\s+address)?|username|user\s?name|name|number|address|message'
LIST_NOUN = re.compile(r'\b(?:list|items|inventory|feed|queue|cart|basket|playlist)\b', re.I)
THREAD = re.compile(r'\b(?:messages?|texts?|thread|chat|conversation|group\s+chat|inbox)\b', re.I)

# Quotations that are shown, not said.
SAY = (r'said|says|say|asked|asks|replied|replies|told|tells|shouted|shouts|called|calls|yelled|yells|whispered|'
       r'whispers|answered|answers|added|adds|laughed|laughs|cried|cries|sighed|sighs|muttered|mutters|exclaimed|'
       r'screamed|screams|murmured|murmurs|begged|begs|added|went|goes|announced|announces|joked|jokes|insisted|'
       r'grinned|smiled|nodded|groaned|gasped|sang|sings|squeaked|roared|growled|whimpered|barked|mumbled')
SHOWN_NOUN = (r'texts?|text\s+messages?|messages?|dms?|notifications?|nudges?|alerts?|reminders?|banners?|pop-?ups?|'
              r'screens?|displays?|signs?|labels?|buttons?|captions?|headlines?|subject(?:\s+line)?|emails?|notes?|'
              r'cards?|posters?|banners?|stickers?|tags?|status|tweets?|posts?|replies|reply|comments?|reviews?|'
              r'previews?|receipts?|tickets?|plaques?|billboards?|letters?|postcards?|lock\s?screens?|'
              r'phones?|apps?|chats?|thread')
SHOWN_SAYS = re.compile(r'\b(?:' + SHOWN_NOUN + r')(?:\s+(?:on|in|at|of|from|above|over)\s+(?:the|a|an|my|your|his|'
                        r'her|their|our)\s+[\w-]+)?\s+(?:said|says|read|reads|showed|shows|displayed|displays|flashed|'
                        r'flashes|lit\s+up\s+with|popped\s+up|pops\s+up|appeared|appears|came\s+in|comes\s+in|went)\b',
                        re.I)
SHOWN_VERB = re.compile(r'\b(?:texted|texts|messaged|dm(?:ed|\'d)|typed|types|tweeted|emailed|posted|'
                        r'reads?\s*:|reading\s*:)\b', re.I)
# Verbs that show text only with a phone, a screen or a message in the same words ("Her phone buzzed", not "The
# headlights lit up a fence").
WEAK_VERB = re.compile(r'\b(?:text|type|wrote|writes|written|posts|buzzed|buzzes|pinged|pings|chimed|chimes|dinged|'
                       r'dings|vibrated|lit\s+up|popped\s+up|pops\s+up|flashed|flashes|get\s+a|got\s+a|gets\s+a|'
                       r'receive|received|receives|sent|sends|send)\b', re.I)
SHOWN_THING = re.compile(r'\b(?:' + SHOWN_NOUN + r'|laptops?|computers?|tablets?|smartphones?|cell\s?phones?|mobiles?)\b',
                         re.I)


def _shown_verb(words: str):
    """The verb that shows a quotation as text: a messaging verb, or a weaker one beside a phone or a message."""
    m = SHOWN_VERB.search(words)
    if m:
        return m
    m = WEAK_VERB.search(words)
    return m if m and SHOWN_THING.search(words) else None
UI_LABEL_VERB = re.compile(r'\b(?:' + UI_VERB + r')\s+(?:on\s+)?(?:the\s+)?$', re.I)
SAY_RE = re.compile(r'\b(?:' + SAY + r')\b', re.I)
ALOUD = re.compile(r'\b(?:aloud|out\s+loud|said\s+it|says\s+it|read\s+it\s+(?:aloud|out))\b', re.I)
TIME = re.compile(r'^\s*(?:\d{1,2}:\d{2}\s*(?:[AaPp]\.?\s?[Mm]\.?)?|\d{1,2}\s*[AaPp]\.?\s?[Mm]\.?|(?:yesterday|today|'
                  r'now|just\s+now)(?:,?\s+\d{1,2}:\d{2}\s*(?:[AaPp]\.?\s?[Mm]\.?)?)?)\s*$', re.I)
STATUS = re.compile(r'^\s*(?:delivered|read|seen|sent|read\s+at\s+[\d:]+\s*(?:[ap]\.?m\.?)?)\s*[.!]?\s*$', re.I)
QUOTE = re.compile(r'["“]([^"“”\n]+)["”]')
EMOJI = re.compile('(?:[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿](?:[️‍\U0001F3FB-\U0001F3FF]|'
                   '[\U0001F000-\U0001FAFF☀-➿])*)')


def quote_kind(sentence: str, quote_at: int, before: str = '') -> str | None:
    """'message' (a text, a chat line, an email), 'notification' (an app's nudge or alert), 'label' (a button or
    menu item named by a UI verb: tap "What can I make?"), 'shown' (a sign, a note, a screen that reads it) for a
    quotation the script presents as written on a screen or a page; None for a line someone says aloud.
    ``sentence``: the sentence holding the quotation, which starts at ``quote_at``; ``before``: the sentence before
    it, which introduces a quotation standing on its own ("Her phone buzzed under the desk." / "proud of you")."""
    lead = sentence[:quote_at]
    rest = QUOTE.sub(' ', sentence[quote_at:])           # the words after the quotation, its tag
    chat = re.match(r'\s*(?:\[(?P<a>[^\]\n]{1,24})\]\s*)?[^\W\d_][\w’\'.-]*(?: [^\W\d_][\w’\'.-]*){0,2}\s*'
                    r'(?:\((?P<b>[^)\n]{1,24})\))?\s*:\s*$', lead)
    if chat and (chat_time(chat.group('a')) or chat_time(chat.group('b'))):
        return 'message'                                 # '[7:02 AM] Dad: "..."', 'Dad (7:02 AM): "..."'
    if UI_LABEL_VERB.search(lead):
        return 'label'
    own = (lead + ' ' + rest).strip(' "“”,')
    if ALOUD.search(own):
        return None
    if SHOWN_SAYS.search(own):
        return _which(own)
    said = SAY_RE.search(own)
    if said and not _shown_verb(own[:said.start()]):
        return None                                      # '"Every day," Lena said.'
    if _shown_verb(own) or NOTIFY.search(lead):
        return _which(own)
    if own.strip(' .:,') or not before:
        return None
    # A quotation on its own line: what the line before says it is.
    if ALOUD.search(before):
        return None
    if SHOWN_SAYS.search(before):
        return _which(before)
    said = SAY_RE.search(before)
    if said and not _shown_verb(before[:said.start()]) and before.rstrip().endswith(':'):
        return None                                      # 'Nana said:'
    if _shown_verb(before) or (NOTIFY.search(before) and before.rstrip().endswith(':')):
        return _which(before)
    return None


def _which(words: str) -> str:
    if NOTIFY.search(words) and not re.search(r'\b(?:texts?|texted|messages?|messaged|chat|dms?)\b', words, re.I):
        return 'notification'
    if re.search(r'\b(?:signs?|labels?|posters?|billboards?|plaques?|notes?|letters?|cards?|postcards?|tags?|'
                 r'stickers?|wrote|written|writes)\b', words, re.I) and not re.search(
            r'\b(?:texts?|texted|messages?|messaged|chat|phones?|typed|types|buzz\w*|ping\w*|emails?|emailed)\b',
            words, re.I):
        return 'shown'
    return 'message'


# The same time as the voice's text reads it ("(seven oh two AM)", "(six twelve p.m.)").
_HOUR = r'(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
_MINUTE = (r'(?:oh\s+(?:one|two|three|four|five|six|seven|eight|nine)|ten|eleven|twelve|thirteen|fourteen|fifteen|'
           r'sixteen|seventeen|eighteen|nineteen|(?:twenty|thirty|forty|fifty)(?:[\s-]+(?:one|two|three|four|five|six|'
           r'seven|eight|nine))?|hundred|o[\'’]clock)')
SAID_TIME = re.compile(r'^\s*' + _HOUR + r'(?:\s+' + _MINUTE + r')?\s*(?:[AaPp]\.?\s?[Mm]\.?|in\s+the\s+(?:morning|'
                       r'afternoon|evening))\s*$|^\s*' + _HOUR + r'\s+' + _MINUTE + r'\s*$', re.I)


def chat_time(paren: str | None) -> str | None:
    """The time a chat transcript label carries ("(7:02 AM)" -> "7:02 AM", or as the voice reads it, "(seven oh two
    AM)"), else None."""
    inner = (paren or '').strip('() \t')
    if inner and TIME.match(inner) and re.search(r'\d', inner):
        return inner
    return inner if inner and SAID_TIME.match(inner) else None


# ------------------------------------------------------------------ sentences
def _sentences(text: str) -> list[tuple[int, int]]:
    from .director.v3.story import sentences
    return [(a, b) for a, b in sentences(text) if text[a:b].strip()]


def _bare(text: str) -> str:
    """Markdown emphasis and code marks off a label, keeping its words exactly."""
    return re.sub(r'\*\*|__|`|(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)', '', text).strip()


# A label: quoted, bold or code words, or a run of words that starts with a capital or a symbol ("+", "Two-step
# login", "Get started"), ending at a comma, a full stop, an arrow, "then", "and" or a part word.
_LABEL = (r'(?:"(?P<q>[^"\n]{1,40})"|“(?P<q2>[^”\n]{1,40})”|\*\*(?P<b>[^*\n]{1,40})\*\*|`(?P<c>[^`\n]{1,40})`|'
          r'(?P<w>(?:Turn|Switch|Log|Sign|Opt|Check)\s+(?:on|off|in|out|up)\b|(?:[A-Z0-9+][\w+&\'’-]*|[+#@])(?:\s+(?!(?:then|and|or|to|in|on|at|from|with|button|tab|menu|'
          r'icon|link|option|toggle|switch|field|box|app)\b)[A-Za-z0-9][\w&\'’-]*){0,3}?))')
LABEL_AFTER_VERB = re.compile(r'\b(?P<v>(?i:' + UI_VERB + r'|turn\s+on|turns\s+on|switch\s+on))\s+(?:on\s+)?'
                              r'(?:the\s+|your\s+|a\s+)?' + _LABEL +
                              r'(?=\s*(?:[,.;:!?)]|→|->|\s(?:then|and|or|to|in|on|at|from|with|button|tab|menu|icon|'
                              r'link|option|toggle|switch|field|box|app)\b|$))(?:\s+(?P<part>buttons?|icon|link|tabs?|'
                              r'menu|option|settings?|toggle|switch|checkbox|field|box|item|entry|app))?')
LABEL_CHAIN = re.compile(r'(?:→|->|›|>|,?\s+then\s+(?:tap\s+|click\s+|choose\s+|select\s+|press\s+)?)\s*'
                         r'(?:the\s+)?' + _LABEL + r'(?=\s*(?:[,.;:!?)]|→|->|\s(?:then|and|button|tab|menu)\b|$))'
                         r'(?:\s+(?P<part>buttons?|icon|link|tabs?|menu|option|settings?|toggle|switch|field|box))?')
CALLED = re.compile(r'\b(?:called|named|titled|labell?ed)\s+' + _LABEL + r'(?=\s*(?:[,.;:!?)]|\s(?:appears|shows|'
                    r'pops|comes|is|with|and)\b|$))')
INPUT = re.compile(r'\b(?:' + INPUT_VERB + r')\s+(?:in\s+)?(?:that\s+|the\s+|your\s+|this\s+|a\s+|an\s+|their\s+)?'
                   r'(?:new\s+|six-digit\s+|\w+-digit\s+)?(?P<n>' + INPUT_NOUN + r')\b', re.I)
INTO_BOX = re.compile(r'\b(?:into|in)\s+(?:the|a|that)\s+(?:\w+\s+)?(?:box|field|blank)\b', re.I)


def _label(m) -> str | None:
    for g in ('q', 'q2', 'b', 'c', 'w'):
        if m.group(g):
            text = _bare(m.group(g)).strip(' .,;:')
            return text or None
    return None


def _named_device(sentence: str):
    """The first device word that names where the action is ("the code from your phone" names where it came
    from, not where it is typed)."""
    return next((m for m in DEVICE.finditer(sentence)
                 if not re.search(r'\bfrom\s+(?:your|the|a|my|his|her|their|our)?\s*$', sentence[:m.start()], re.I)),
                None)


def _device(sentence: str, context: str | None) -> str | None:
    on = ON_DEVICE.search(sentence)
    named = _named_device(sentence)
    found = on.group('d') if on else (named.group() if named else None)
    if found:
        return next(kind for kind, p in DEVICES if re.fullmatch(p, found, re.I))
    return context


def app_names(texts: list[str], cast_names=()) -> set[str]:
    """Names the script gives software: "open Harbor Mail", "the Authenticator app", a capitalised name that does
    what software does ("Nibblenote builds your fridge list") more than once."""
    names = set()
    people = {n.casefold() for n in cast_names}
    joined = '\n'.join(texts)
    for m in re.finditer(r'\b(?i:open|opens|opened|launch|launches|download|downloads|install|installs)\s+'
                         r'(?:the\s+|your\s+)?' + _LABEL + r'(?=\s*(?:[,.;:!?)]|\s(?:and|app|on|to|then)\b|$))',
                         joined):
        label = _label(m)
        if label and label[0].isupper() and not DEVICE.fullmatch(label):
            names.add(re.sub(r'\s+app$', '', label))
    for m in re.finditer(r'\b(?:the\s+)?([A-Z][\w-]*(?:\s+[A-Z][\w-]*)?)\s+app\b', joined):
        if m.group(1).casefold() not in people and m.group(1).split()[0] not in ('The', 'This', 'That', 'Your', 'An'):
            names.add(m.group(1))
    counts = {}
    for m in re.finditer(r'(?<![.!?]\s)(?<!^)\b([A-Z][a-z]+[A-Za-z]*)\s+(?:' + SOFTWARE_VERB + r')\b', joined):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    for m in re.finditer(r'\b([A-Z][a-z]+[A-Za-z]*)\s+(?:' + SOFTWARE_VERB + r')\b', joined):
        word = m.group(1)
        if word.casefold() in people or word in ('He', 'She', 'It', 'They', 'This', 'That', 'There', 'Mom', 'Dad'):
            continue
        if len(re.findall(r'\b' + re.escape(word) + r'\b', joined)) >= 2:
            names.add(word)
    return names


def elements(sentence: str, app: str | None = None, last_code: str | None = None) -> list[dict]:
    """The screen parts a sentence names, each {'kind', 'label', 'at'} (``at``: its character in the sentence)."""
    out = []

    def add(kind, label, at, **more):
        if not any(e['kind'] == kind and e['label'] == label for e in out):
            out.append({'kind': kind, 'label': label, 'at': at, **more})
    from .markup import combos
    keys = combos(sentence)
    for m in LABEL_AFTER_VERB.finditer(sentence):
        label = _label(m)
        if not label or any(a <= m.start('v') < b or a <= m.end() - 1 < b for a, b, _ in keys):
            continue
        verb = m.group('v').lower()
        part = (m.group('part') or '').lower().rstrip('s') if m.group('part') else ''
        if re.match(r'open|launch|go|went|head|navigate', verb):
            if part == 'app' or (app and label == app) or not part:
                continue                                  # "open Harbor Mail": the app, its bar names it
        if DEVICE.fullmatch(label) or QR.fullmatch(label) or label.casefold() in ('it', 'this', 'that', 'here', 'there'):
            continue
        kind = PART.get(part) or PART.get(part + 's') or ('toggle' if re.match(r'toggle|enable|turn|switch', verb)
                                                          else 'row' if re.match(r'select|choos|chose|pick', verb)
                                                          else 'button')
        add(kind, label, m.start('v'))
        tail = sentence[m.end():]
        for c in LABEL_CHAIN.finditer(tail):
            if c.start() > 0 and not re.match(r'\s*$', tail[:c.start()]):
                if not re.fullmatch(r'[^.;!?]*', tail[:c.start()]):
                    break
            more = _label(c)
            if more and more.casefold() not in ('it', 'this'):
                cpart = (c.group('part') or '').lower().rstrip('s')
                ckind = PART.get(cpart) or ('button' if re.match(ACTION_LABEL, more, re.I) else 'row')
                add(ckind, more, m.end() + c.start())
    for c in re.finditer(r'(?:→|->|›)\s*(?:the\s+)?' + _LABEL + r'(?=\s*(?:[,.;:!?)]|→|->|\s(?:then|and|button|'
                         r'tab|menu)\b|$))', sentence):
        more = _label(c)
        if more and not any(e['label'] == more for e in out):
            add('button' if re.match(ACTION_LABEL, more, re.I)
                else 'row', more, c.start())
    for m in re.finditer(r'\b(?:tap|taps|tapped|click|clicks|clicked|press|presses|pressed|hit)\s+(?:on\s+)?'
                         r'(?:the\s+)?(?P<l>\+|[^\s\w])\s+(?:button|icon|sign)\b', sentence):
        add('button', m.group('l'), m.start())
    m = AVATAR.search(sentence)
    if m and re.search(r'\b(?:' + UI_VERB + r')\b', sentence[:m.start()], re.I):
        add('avatar', '', m.start())
    for m in CALLED.finditer(sentence):
        label = _label(m)
        if label:
            add('row', label, m.start())
    for m in LEGEND.finditer(sentence):
        add('legend', m.group('l').strip(), m.start(), colour=m.group('c').lower())
    for m in QR.finditer(sentence):
        add('qr', '', m.start())
    code = None
    for m in CODE_DIGITS.finditer(sentence):
        if re.search(r'\b(?:code|pin|passcode|otp|digits?)\b', sentence, re.I) and not keys:
            code = m.group()
            add('code', code, m.start())
    for m in DIGIT_COUNT.finditer(sentence):
        if code is None:
            n = m.group('n')
            add('code', '', m.start(), digits=int(n) if n.isdigit() else NUMBER_WORD[n.lower()])
    for m in INPUT.finditer(sentence):
        noun = m.group('n')
        add('input', noun, m.start(), value=last_code if noun.lower() == 'code' and last_code else '')
        more = re.match(r',?\s+(?:and\s+)?then\s+(?:the\s+|your\s+|a\s+)?(?P<n>' + INPUT_NOUN + r')\b',
                        sentence[m.end():], re.I)
        if more:
            noun = more.group('n')
            add('input', noun, m.end() + more.start('n'), value=last_code if noun.lower() == 'code' and last_code
                else '')
    if not any(e['kind'] == 'input' for e in out) and INTO_BOX.search(sentence) and \
            re.search(r'\b(?:' + INPUT_VERB + r')\b', sentence, re.I):
        add('input', '', INTO_BOX.search(sentence).start(), value=last_code or '')
    for m in CHECK.finditer(sentence):
        add('check', '', m.start())
    for e in list(out):                                   # pressing Verify, Save or Done shows it worked
        if e['kind'] == 'button' and CONFIRM.match(e['label']) and not any(x['kind'] == 'check' for x in out):
            add('check', '', e['at'] + 1, after=True)
    for m in NOTIFY.finditer(sentence):
        if any(m.group().casefold() in e['label'].casefold().split() for e in out if e.get('label')):
            continue                                      # the "Alerts" menu item, not an alert
        if not re.search(r'\b(?:turn|turns|switch|switches)\s+(?:on|off)\s+$', sentence[:m.start()], re.I):
            add('notification', '', m.start())
            break
    return sorted(out, key=lambda e: e['at'])


def _items(sentence: str) -> list[tuple[int, str]]:
    """A sentence that is only a list of three or more short items ("Milk, spinach, chicken thighs, that cilantro."):
    each item's character and its words (a leading "that", "the", "and" or "some" left out)."""
    body = sentence.strip().rstrip('.!')
    parts = re.split(r',\s*(?:and\s+|or\s+)?|\s+and\s+', body)
    if len(parts) < 3 or any(not p.strip() or len(p.split()) > 3 or re.search(r'\b(?:is|are|was|were|has|have|'
                                                                              r'means|gets?)\b', p) for p in parts):
        return []
    out, at = [], 0
    for p in parts:
        k = sentence.find(p.strip(), at)
        word = re.sub(r'^(?:that|the|and|some|a|an|your|our)\s+', '', p.strip(), flags=re.I)
        out.append((k + len(p.strip()) - len(word), word))
        at = k + len(p.strip())
    return out


# ------------------------------------------------------------------ the script's screen moments
def read(beats: list[tuple[str, str]], cast: list[dict] | None = None, labels: set | None = None) -> list[dict]:
    """The screen moments of a script: ``beats`` [(beat id, written text)] in order, ``cast`` the plan's
    [{'name', 'sex'}]. Each moment: {'beat', 'at' (character of the beat's text where it starts), 'until' (where its
    words end), 'kind': 'screen' | 'message' | 'notification', 'device', 'app', 'elements' [{'kind', 'label', 'at'
    (character of the beat's text), ...}], and for messages: 'thread', 'sender', 'outgoing', 'time', 'text',
    'status'}."""
    from . import speech
    cast = cast or []
    names = [c.get('name') or '' for c in cast]
    texts = [t for _, t in beats]
    apps = app_names(texts, names)
    labels = labels if labels is not None else speech.screenplay_labels(texts)
    out = []
    device, app, code, thread, owner = None, None, None, None, None
    app_on = {}                                          # device -> the app last opened on it
    app_said = False                                     # the sentence before named the app doing something
    last_named = {}                                      # sex -> the last cast name of that sex
    sex_of = {(c.get('name') or '').split()[0].casefold(): c.get('sex') for c in cast if c.get('name')}
    previous = ''
    prev_moment_beat = None
    named_thread = None                                  # "the group chat called Pizza Police"
    for k, (bid, text) in enumerate(beats):
        spans = _sentences(text)
        # A chat transcript: "Dad (7:02 AM): Who ate the last waffle?" lines.
        lines = speech.labels_in(text, labels)
        for j, (start, body, name) in enumerate(lines):
            m = speech.LABEL.match(text, start)
            when = chat_time(m.group('paren') if m else None)
            if not when and not (thread is not None and prev_moment_beat in (k - 1, k)):
                continue
            stop = lines[j + 1][0] if j + 1 < len(lines) else len(text)
            words = text[body:stop].strip()
            words = QUOTE.sub(lambda q: q.group(1), words) if words.startswith(('"', '“')) else words
            thread = thread or {'name': named_thread, 'messages': []}
            thread['group'] = True
            mine = bool(owner) and name.split()[0].casefold() == owner.split()[0].casefold()
            msg = {'sender': name, 'outgoing': mine, 'time': when, 'text': words}
            thread['messages'].append(msg)
            out.append({'beat': bid, 'at': start, 'until': stop, 'kind': 'message', 'device': 'phone', 'app': None,
                        'elements': [], 'thread': thread['name'], 'group': True, 'owner': owner, **msg,
                        'history': list(thread['messages'][:-1]), 'status': None})
            prev_moment_beat = k
        if lines and any(o['beat'] == bid for o in out):
            previous = text
            continue
        for a, b in spans:
            sentence = text[a:b]
            for m in re.finditer(r'\b([A-Z][a-z]+)\b', sentence):
                sex = sex_of.get(m.group(1).casefold())
                if sex:
                    last_named[sex] = m.group(1)
            m = re.search(r"\b([A-Z][a-z]+)['’]s\s+(?:phone|cell|mobile|screen|laptop)\b", sentence)
            if m:
                owner = m.group(1)
            m = re.search(r'\b(?:chat|thread|conversation|group)\s+(?:called|named|titled)\s+' + _LABEL +
                          r'(?=\s*(?:[,.;:!?)]|$))', sentence)
            if m and _label(m):
                named_thread = _label(m)
                if thread is not None and not thread['name']:
                    thread['name'] = named_thread
            if out and STATUS.match(sentence) and out[-1]['kind'] == 'message' and prev_moment_beat in (k - 1, k):
                out[-1]['status'] = sentence.strip().rstrip('.!')         # "Delivered." under the bubble
                out[-1]['until_beat'] = bid
                prev_moment_beat = k
                continue
            device = _device(sentence, device)
            app = app_on.get(device, app)
            quotes = list(QUOTE.finditer(sentence))
            handled = False
            for q in quotes:
                kind = quote_kind(sentence, q.start(), previous if q.start() == 0 or not sentence[:q.start()].strip()
                                  else '')
                if kind not in ('message', 'notification'):
                    continue
                handled = True
                lead = sentence[:q.start()] if sentence[:q.start()].strip() else previous
                words = q.group(1).strip()
                if kind == 'notification':
                    out.append({'beat': bid, 'at': a + q.start(), 'until': a + q.end(), 'kind': 'notification',
                                'device': 'phone', 'app': app or (sorted(apps)[0] if len(apps) == 1 else None),
                                'elements': [{'kind': 'notification', 'label': words, 'at': a + q.start()}],
                                'text': words})
                    prev_moment_beat = k
                    continue
                outgoing = bool(re.search(r'\b(?:typed|types|type|sent|sends|send|replied|replies|reply|wrote\s+back|'
                                          r'texted\s+back|answered)\b', lead, re.I))
                named = re.search(r"\b(?:opened|opens|open|tapped|taps)\s+([A-Z][a-z]+)['’]s\s+(?:name|chat|thread|"
                                  r"messages|contact|conversation)|\b(?:from|to)\s+([A-Z][a-z]+)\b|\b([A-Z][a-z]+)\s+"
                                  r"(?:texted|messaged|wrote|sent)|\b([A-Z][a-z]+)['’]s\s+(?:\w+\s+)?(?:text|message)",
                                  lead)
                sender = next((g for g in (named.groups() if named else ()) if g), None)
                if outgoing and sender and named.group(3) and not (owner and sender == owner):
                    outgoing = False                     # "Dad sent one more message": to the phone we see
                if sender is None and re.search(r'\b(?:his|her)\s+(?:\w+\s+){0,2}(?:texts?|messages?)\b', lead, re.I):
                    pron = re.search(r'\b(his|her)\s+(?:\w+\s+){0,2}(?:texts?|messages?)\b', lead, re.I).group(1)
                    sender = last_named.get('female' if pron.lower() == 'her' else 'male')
                if thread is None or (sender and thread['name'] and sender != thread['name'] and not outgoing
                                      and not thread.get('group')):
                    thread = {'name': named_thread, 'messages': []}
                if sender and not thread['name']:
                    thread['name'] = sender
                msg = {'sender': None if outgoing else (sender if thread.get('group') else thread['name'] or sender),
                       'outgoing': outgoing, 'time': None, 'text': words}
                thread['messages'].append(msg)
                out.append({'beat': bid, 'at': a + q.start(), 'until': a + q.end(), 'kind': 'message',
                            'device': 'phone', 'app': None, 'elements': [], 'thread': thread['name'],
                            'group': bool(thread.get('group')), 'owner': owner, **msg,
                            'history': list(thread['messages'][:-1]), 'status': None})
                prev_moment_beat = k
            if handled:
                previous = sentence
                continue
            # "showed her the old messages": the thread itself.
            if thread and thread['messages'] and THREAD.search(sentence) and re.search(
                    r'\b(?:show|showed|shows|scroll\w*|read|reads|opened|opens|looked|looks|old|years)\b', sentence,
                    re.I) and not quotes:
                last = thread['messages'][-1]
                out.append({'beat': bid, 'at': a, 'until': b, 'kind': 'message', 'device': 'phone', 'app': None,
                            'elements': [], 'thread': thread['name'], 'group': False, 'owner': owner, **last,
                            'history': list(thread['messages'][:-1]), 'status': None, 'replay': True})
                prev_moment_beat = k
                previous = sentence
                continue
            opened = re.search(r'\b(?i:open|opens|opened|launch|launches|launched)\s+(?:the\s+|your\s+)?' + _LABEL
                               + r'(?=\s*(?:[,.;:!?)]|\s(?:and|app|on|to|then)\b|$))', sentence)
            if opened and _label(opened) and re.sub(r'\s+app$', '', _label(opened)) in apps:
                app = app_on[device] = re.sub(r'\s+app$', '', _label(opened))
            subject = next((n for n in sorted(apps, key=len, reverse=True)
                            if re.search(r'(?<!called )(?<!named )(?<!titled )\b' + re.escape(n) + r'\b', sentence)),
                           None)
            if subject and not opened:
                app = subject
                app_on.setdefault(device, subject)
            elif subject and app_on.get(device) != subject and not (opened and _label(opened)):
                app = subject
            found = elements(sentence, app, code)
            for e in found:
                if e['kind'] == 'code' and e['label']:
                    code = e['label']
            items = _items(sentence) if (prev_moment_beat == k or LIST_NOUN.search(previous)) and app else []
            follows = prev_moment_beat in (k - 1, k) or app_said
            for at, word in items:
                found.append({'kind': 'row', 'label': word, 'at': at})
            ui = bool(found) and (
                DEVICE.search(sentence) or app is not None and (subject or follows) or
                any(e['kind'] in ('button', 'tab', 'avatar', 'qr', 'input', 'code') for e in found) and
                (device or APP_WORD.search(sentence)))
            only_notify = [e['kind'] for e in found] == ['notification']
            if only_notify and not (DEVICE.search(sentence) or app):
                ui = False
            if ui:
                for e in found:
                    e['at'] += a
                on = _device(sentence, None)
                where = next((kind for kind, p in DEVICES for e in found if e['kind'] == 'qr' and on == kind), None)
                where = where or device or 'phone'
                last = out[-1] if out else None
                if last and last['beat'] == bid and last['kind'] == 'screen' and last['device'] == where \
                        and last['app'] == app:
                    last['elements'] += found                  # one screen fills in sentence by sentence
                    last['until'] = b
                else:
                    out.append({'beat': bid, 'at': a, 'until': b, 'kind': 'screen', 'device': where, 'app': app,
                                'elements': found})
                prev_moment_beat = k
                subject_device = _named_device(sentence)
                if subject_device:
                    device = next(kind for kind, p in DEVICES if re.fullmatch(p, subject_device.group(), re.I))
                if where and where != 'phone' and any(e['kind'] == 'qr' for e in found):
                    device = 'phone'                     # a code on the screen is scanned by a phone
            app_said = bool(subject) and bool(re.search(r'\b' + re.escape(subject) + r'\s+(?:' + SOFTWARE_VERB + r')\b',
                                                        sentence))
            previous = sentence
    return out


def drawn_strings(moment: dict) -> list[str]:
    """Every string a moment puts on its screen (what the QA checks the script's shown text against)."""
    out = [moment.get('app') or '', moment.get('thread') or '']
    out += [e['label'] for e in moment.get('elements') or () if e.get('label')]
    out += [e.get('value') or '' for e in moment.get('elements') or ()]
    if moment['kind'] == 'message':
        for m in list(moment.get('history') or ()) + [moment]:
            out += [m.get('text') or '', m.get('sender') or '', m.get('time') or '']
        out.append(moment.get('status') or '')
    return [s for s in out if s]

"""How a video closes: how long its closing card holds, and what it shows.

Length (card_timing): the outgoing scene clears to the card's blank page (CLEAR), the card's words appear (at once in
a piece shorter than SHORT seconds, else written by the hand in DRAW_PER_WORD a word, DRAW_MIN-DRAW_MAX), and the
finished card then stays for its reading time: READ_PER_WORD a word on the card (about 200 words a minute, a
comfortable pace for on-screen text that is read once), never under READ_MIN (READ_MIN_SHORT in a short piece: a
three-word card in a six-second greeting stays short). The drawing time never counts toward the reading time. The
"Made with ..." credit is part of the same card, not a second card after it.

One card: when the script's last sentences are the card's own lines (an ad's "Two Ovens Bakery, corner of Elm and
Fifth. Come early!"), the card starts on the first of them that falls in the narration's last NARRATED_MAX seconds,
so the voice reads the card and no silent outro repeats it; it then stays at least AFTER_VOICE after the last word.

Content, by what the script is for:
- 'info': an ad, promo, notice, invitation or how-to closes on its own last words when they are a call to action or
  key information (an email, web address, phone number or hashtag; a day with a time, or a date; an address; a
  price; "Come early!", "Download it free today."), under the title. The facts the same closing paragraph states in
  a longer sentence (its day and time, price, place or contact) join the card as written ("Every Saturday at 7
  a.m.", "Just $3.50 each"). Never "The End" or "Thanks for watching".
- 'wish': a greeting ("Happy 25th Jo, ...") closes on its own wish.
- 'story': a story or poem closes like a picture book ("The End").
- 'title': anything else (an explainer, a lesson) repeats its title.
"""
from __future__ import annotations

import re

from .. import numbers, script, speech

SHORT = 20.0          # narration shorter than this: a short piece, whose card is shown at once
CLEAR = .3            # the outgoing scene clears to the blank card page before the card's words appear (seconds)
DRAW_PER_WORD, DRAW_MIN, DRAW_MAX = .2, 1.4, 2.5   # the hand writes a longer piece's card in this long
READ_PER_WORD = .3    # then the finished card stays this long a word on it (about 200 words a minute)...
READ_MIN, READ_MIN_SHORT = 2.5, 1.8   # ...and never less than this (a short piece's few words: the short floor)
NARRATED_MAX = 3.5    # a card that starts on the script's own closing lines is read out for at most this long
AFTER_VOICE = 1.      # and stays at least this long after the last word
MAX_ITEMS = 4         # lines of key information from the closing sentences
MAX_LINES = 5         # lines on the card with the facts its paragraph states earlier
FACT_WORDS = 6        # a clause this short that states a fact is a line as it is; a longer one gives the fact alone
ITEM_WORDS = 12       # a longer sentence is narration, not a line for the card (its contacts still are)
ITEM_CHARS = 64      # a sentence with contacts longer than this shows only its contacts


def words(text: str) -> float:
    """How many words a reader reads in ``text`` (a Chinese or Japanese character counts as half a word)."""
    return len(re.findall(r'[^\W\u3040-\u30ff\u3400-\u9fff]+', text)) + .5 * len(re.findall(r'[\u3040-\u30ff\u3400-\u9fff]', text))


def reading_seconds(n_words: float, body: float) -> float:
    """How long a finished card of ``n_words`` words stays up after narration that lasts ``body`` seconds."""
    return round(max(READ_MIN_SHORT if body < SHORT else READ_MIN, READ_PER_WORD * n_words), 3)


def card_timing(n_words: float, body: float) -> dict:
    """The card's clock, in seconds from its start: 'clear' (the old scene gone), 'draw' (its words written; 0 when
    shown at once), 'read' (how long the finished card then stays) and 'quick' (shown at once, not written)."""
    quick = body < SHORT
    draw = 0. if quick else round(min(DRAW_MAX, max(DRAW_MIN, DRAW_PER_WORD * n_words)), 3)
    return {'clear': CLEAR, 'draw': draw, 'read': reading_seconds(n_words, body), 'quick': quick}


def card_words(ep: dict, lang: str, close: dict, heading: str = '', second: str = '') -> float:
    """The words on the closing card: an info card's title and lines, a wish, or a heading and its second line."""
    if close['items']:
        title = (_title(ep, lang) if close['kind'] == 'info' else '')
        return words(title) + sum(words(i) for i in close['items'])
    heading = heading or ('The End' if close['kind'] == 'story' else _title(ep, lang))
    return words(heading) + words(second or _title({'title': ep.get('subtitle') or ''}, lang) or 'Thanks for watching')


def _title(ep: dict, lang: str) -> str:
    title = ep.get('title') or ''
    return (title.get(lang) or '') if isinstance(title, dict) else str(title)


def narrated_from(close: dict, beat: dict, info: dict, lang: str, voice_end: float) -> float | None:
    """When a card whose lines are the script's own last sentences starts: as the voice begins the first of them
    in the last NARRATED_MAX seconds of the narration (``info`` is the last beat's timing). None when the card's
    lines are not its last sentences, or they would take the whole beat (its own scene keeps a moment)."""
    n = close.get('spoken_lines', 0)
    spoken = beat.get('spoken') or {}
    spoken = speech.caption_text((spoken.get(lang) if isinstance(spoken, dict) else spoken) or '')
    ct = info.get('char_times') or []
    said = script.sentences(spoken, lang) or []
    if not n or n >= len(said) or not ct:
        return None
    at, pos, starts = None, 0, []
    for sentence in said:
        k = spoken.find(sentence, pos)
        if k < 0:
            return None
        starts.append(k)
        pos = k + len(sentence)
    for k in starts[len(said) - n:]:
        t = info['start'] + ct[min(k, len(ct) - 1)]
        if voice_end - t <= NARRATED_MAX and t > info['start'] + .5:
            at = t
            break
    return None if at is None else round(at, 4)


CONTACT_KINDS = ('email', 'url', 'phone', 'ext', 'tag')
_DAY = (r'\b(?:mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday|'
        r'today|tonight|tomorrow|this weekend|lunes|martes|miércoles|jueves|viernes|sábado|domingo|hoy|mañana)\b')
_CLOCK = r'(?:\b\d{1,2}(?::\d{2})?\s?(?:a\.?\s?m\b\.?|p\.?\s?m\b\.?)|\bnoon\b|\bmidnight\b|\b\d{1,2}:\d{2}\b)'
_MONTH = (r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|'
          r'august|september|october|november|december)\.?\s+\d{1,2}(?:st|nd|rd|th)?\b')
WHEN = re.compile(rf'{_DAY}.*{_CLOCK}|{_CLOCK}.*{_DAY}|{_MONTH}|\b\d{{1,2}}/\d{{1,2}}\b', re.I)
PLACE = re.compile(r'\bcorner of\b|\besquina de\b|\b\d+\s+(?:[A-Z][\w.]*\s){1,3}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|'
                   r'Boulevard|Ln|Lane|Way|Dr|Drive|Pl|Place|Ct|Court|Hwy|Highway)\b')
PRICE = re.compile(r'[$€£¥]\s?\d|\b\d+(?:[.,]\d+)?\s?(?:dollars|euros|pounds|%\s+off)\b|\bfree\b', re.I)
CTA = re.compile(r"^(?:please\s+|so\s+|now\s+|and\s+)?(?:come|call|visit|join|book|order|shop|try|download|get|grab|"
                 r"sign up|subscribe|follow|register|reserve|rsvp|bring|stop by|drop by|swing by|text|email|message|"
                 r"find us|see you|tap|click|scan|buy|pre-order|preorder|don't miss|hurry|apply|enroll|donate|"
                 r"vote|reply|learn more|ven|venga|llama|visita|únete|reserva|compra|descarga)\b"
                 r"|^questions\?|^(?:the )?link (?:below|in (?:the )?bio)\b|^¿preguntas\?", re.I)
WISH = re.compile(r"^(?:happy|merry|congratulations|congrats|get well|good luck|best wishes|welcome|thank you|"
                  r"thanks|feliz|felicidades|felicitaciones)\b", re.I)


def _contact_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) of each email, web address, phone number, extension and hashtag, as the voice reads them."""
    return [(m.start(), m.end(), k) for m in numbers.EN_PATTERN.finditer(text)
            for k in CONTACT_KINDS if m.group(k)][:12]


def _contacts(sentence: str) -> list[str]:
    """The contacts in a sentence as written; an extension stays with the phone number before it."""
    out, last = [], None
    for a, b, kind in _contact_spans(sentence):
        if kind == 'ext' and out and last == 'phone':
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
        last = kind
    return [sentence[a:b] for a, b in out]


_ABBREV_END = re.compile(r'\b(?:[ap]\.\s?m|a\.\s?d|b\.\s?c|etc|st|ave|blvd|rd|dr|jr|sr|mr|mrs|ms|dr)\.$', re.I)


def _clean(line: str) -> str:
    line = speech.drawn(line).strip()
    keep = bool(_ABBREV_END.search(line))
    line = line.rstrip(';,').strip() if keep else line.rstrip('.;,').strip()
    if line and line[0].islower() and not any(a == 0 for a, _, _ in _contact_spans(line)):
        line = line[0].upper() + line[1:]
    return line


def _items(sentence: str, storylike: bool) -> list[str] | None:
    """The card lines a closing sentence gives, or None when it is not key information."""
    contacts = _contacts(sentence)
    words = len(sentence.split())
    rest = sentence
    for c in contacts:
        rest = rest.replace(c, ' ')
    if contacts and (words > ITEM_WORDS or len(sentence) > ITEM_CHARS
                     or (len(contacts) > 1 and len(re.findall(r'\w+', rest)) <= 1)):
        return [_clean(c) for c in contacts]                    # a run of contacts: one a line
    if words > ITEM_WORDS:
        return None
    cue = contacts or WHEN.search(sentence)
    if not storylike:
        cue = cue or PLACE.search(sentence) or PRICE.search(sentence) or CTA.search(sentence.strip(' "“”\'‘’'))
    return [_clean(sentence)] if cue else None


_LEAD = re.compile(r'(?:\b(?:every|each|this|next|on|from|until|by|at|just|only)\s+)+$', re.I)


def _facts(sentence: str, have: set[str]) -> list[tuple[str, str]]:
    """(kind, line) for each fact a longer closing sentence states that the card does not have yet: its day and
    time ('when'), price, place or contacts, as written: a short clause whole ("Just $3.50 each"), else the fact
    with the words that lead into it ("every Saturday at 7 a.m.")."""
    out = []
    for clause in re.split(r'[,;:·|—–]\s*|(?<=[.!?])\s+(?=[A-Z0-9$€£¥"“])', sentence):
        clause = clause.strip(' "“”\'‘’')
        if not clause:
            continue
        found = [('contact', m) for m in (re.search(re.escape(c), clause) for c in _contacts(clause)) if m]
        for kind, pattern in (('when', WHEN), ('price', PRICE), ('place', PLACE)):
            m = pattern.search(clause)
            if m:
                found.append((kind, m))
        for kind, m in found:
            if kind in have:
                continue
            have.add(kind)
            if len(clause.split()) <= FACT_WORDS:
                line = clause
            else:                                                     # the fact from its lead-in words on
                lead = _LEAD.search(clause[:m.start()])
                a = lead.start() if lead else m.start()
                need = len(clause[a:m.end()].split())
                line = ' '.join(clause[a:].split()[:max(need, FACT_WORDS + 2)])
            out.append((kind, _clean(line)))
            break                                                     # one line a clause
    return out


def _kinds(line: str) -> set[str]:
    out = {k for k, p in (('when', WHEN), ('price', PRICE), ('place', PLACE)) if p.search(line)}
    return out | ({'contact'} if _contacts(line) else set())


def _text(beat: dict, lang: str) -> str:
    display = beat.get('display') or {}
    return speech.caption_text((display.get(lang) if isinstance(display, dict) else display) or '')


def closing(ep: dict, lang: str) -> dict:
    """What the closing card shows: {'kind': 'info'|'wish'|'story'|'title', 'items': [lines]} (items only for info
    and wish). ``ep`` is the storyboard; its 'genre' is the plan's reading of it and 'story' the story setting."""
    beats = [b for b in ep.get('beats', []) if b.get('kind', 'narration') not in ('title', 'agenda')]
    story = ep.get('genre', 'story') in ('story', 'poem') and ep.get('story') == 'story'
    items: list[str] = []
    spoken_lines, rest = 0, []           # the last beat's sentences that are card lines; the paragraph's others
    for k, beat in enumerate(reversed(beats[-2:])):
        sentences = script.sentences(_text(beat, lang), lang) or []
        whole = True
        for j, sentence in enumerate(reversed(sentences)):
            got = _items(sentence, story)
            if got is None or len(items) + len(got) > MAX_ITEMS:
                whole = False
                rest = sentences[:len(sentences) - j]
                break
            items[:0] = got
            spoken_lines += k == 0
        if not whole or not sentences:
            break
    items = [i for i in items if i]
    if items:
        # The facts the same paragraph states before its closing lines (its day and time, price, place, contacts)
        # join the card in the order the script gives them.
        have = set().union(*(_kinds(i) for i in items))
        facts = [line for sentence in rest for _, line in _facts(sentence, have) if line and line not in items]
        items = facts[:max(0, MAX_LINES - len(items))] + items
        return {'kind': 'info', 'items': items, 'spoken_lines': spoken_lines}
    first = next((s for b in beats[:1] for s in script.sentences(_text(b, lang), lang) or []), '')
    if WISH.match(first.strip(' "“”\'‘’')):
        wish = re.split(r'[,!.?;—]', first, maxsplit=1)[0]
        if len(wish.split()) <= 6:
            return {'kind': 'wish', 'items': [_clean(wish)]}
    return {'kind': 'story' if story else 'title', 'items': []}

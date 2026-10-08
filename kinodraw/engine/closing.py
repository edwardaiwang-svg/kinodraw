"""How a video closes: how long its closing card holds, and what it shows.

Length: about a tenth of the video, between TAIL_MIN and TAIL_MAX seconds; a piece shorter than SHORT seconds gets
only the short tail. The "Made with ..." credit is part of the same card, not a second card after it.

Content, by what the script is for:
- 'info': an ad, promo, notice, invitation or how-to closes on its own last words when they are a call to action or
  key information (an email, web address, phone number or hashtag; a day with a time, or a date; an address; a
  price; "Come early!", "Download it free today."), under the title. Never "The End" or "Thanks for watching".
- 'wish': a greeting ("Happy 25th Jo, ...") closes on its own wish.
- 'story': a story or poem closes like a picture book ("The End").
- 'title': anything else (an explainer, a lesson) repeats its title.
"""
from __future__ import annotations

import re

from .. import numbers, script, speech

SHORT = 20.0          # narration shorter than this: only the short tail
TAIL_SHARE = .10      # otherwise the card holds about this share of the video...
TAIL_MIN, TAIL_MAX = 1.5, 4.0   # ...within these bounds (seconds)
MAX_ITEMS = 4         # lines of key information on the card
ITEM_WORDS = 12       # a longer sentence is narration, not a line for the card (its contacts still are)
ITEM_CHARS = 64      # a sentence with contacts longer than this shows only its contacts


def tail_seconds(body: float) -> float:
    """How long the closing card holds after narration that lasts ``body`` seconds."""
    if body < SHORT:
        return TAIL_MIN
    return round(min(TAIL_MAX, max(TAIL_MIN, body * TAIL_SHARE)), 3)


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


def _clean(line: str) -> str:
    line = speech.drawn(line).strip().rstrip('.;,').strip()
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


def _text(beat: dict, lang: str) -> str:
    display = beat.get('display') or {}
    return speech.caption_text((display.get(lang) if isinstance(display, dict) else display) or '')


def closing(ep: dict, lang: str) -> dict:
    """What the closing card shows: {'kind': 'info'|'wish'|'story'|'title', 'items': [lines]} (items only for info
    and wish). ``ep`` is the storyboard; its 'genre' is the plan's reading of it and 'story' the story setting."""
    beats = [b for b in ep.get('beats', []) if b.get('kind', 'narration') not in ('title', 'agenda')]
    story = ep.get('genre', 'story') in ('story', 'poem') and ep.get('story') == 'story'
    items: list[str] = []
    for beat in reversed(beats[-2:]):
        sentences = script.sentences(_text(beat, lang), lang) or []
        whole = True
        for sentence in reversed(sentences):
            got = _items(sentence, story)
            if got is None or len(items) + len(got) > MAX_ITEMS:
                whole = False
                break
            items[:0] = got
        if not whole or not sentences:
            break
    items = [i for i in items if i]
    if items:
        return {'kind': 'info', 'items': items}
    first = next((s for b in beats[:1] for s in script.sentences(_text(b, lang), lang) or []), '')
    if WISH.match(first.strip(' "“”\'‘’')):
        wish = re.split(r'[,!.?;—]', first, maxsplit=1)[0]
        if len(wish.split()) <= 6:
            return {'kind': 'wish', 'items': [_clean(wish)]}
    return {'kind': 'story' if story else 'title', 'items': []}

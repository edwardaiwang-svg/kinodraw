"""What a beat's own words support: clauses, a proof quantity, a call to action and a launch arc.

The offline director, plan repair and the hybrid renderer share these readers, so a counter, a button or a
clause-timed reveal is only ever made from words the script actually contains.
"""
from __future__ import annotations

import re

# "Part 1", "Step 2" and years name places in the script, not quantities to dramatize.
ORDINAL = re.compile(r'\b(?:part|step|chapter|section|lesson|unit|page|episode|level|number|no\.)\s*$', re.I)
NUMBER = re.compile(r'(?<![\w.,])([$€£])?(\d+(?:,\d{3})*(?:\.\d+)?)(?:\s*(%|percent\b|per\s+cent\b|x\b|×))?')
# Imperatives that ask the viewer to act, at the start of a sentence or clause.
CTA = re.compile(r'(?:^|(?<=[.!?:;]\s))(sign\s+up|try\s+it|try\s+\w+\s+(?:free|today|now)|download|get\s+started|'
                 r'start\s+(?:for\s+free|now|today|your)|book\s+a\s+demo|join\s+(?:us|now|today|the)|subscribe|'
                 r'order\s+now|buy\s+now|get\s+(?:it|yours|the\s+app))\b', re.I)
REVEAL = re.compile(r'(?:^|(?<=[.!?:]\s))(?:Meet|Introducing|Announcing|Say\s+hello\s+to)\s+\w', re.M)


def clauses(text: str) -> list[tuple[int, int]]:
    """Character spans of the clauses of ``text``; a clause ends at , ; : . ! ? or … before a space or the end."""
    out, start = [], 0
    for hit in re.finditer(r'[,;:.!?…]+(?=\s|$)', text):
        end = hit.end()
        if text[start:end].strip():
            out.append((start, end))
        start = end
    if text[start:].strip():
        out.append((start, len(text)))
    return out


def word_clauses(text: str) -> list[int]:
    """The clause index of each whitespace-separated word, matching ``clauses`` on the same text."""
    spans = clauses(text)
    out = []
    for word in re.finditer(r'\S+', text):
        out.append(next((k for k, (a, b) in enumerate(spans) if a <= word.start() < b), len(spans) - 1))
    return out


def spoken_offset(display: str, spoken: str, index: int) -> int:
    """Map a character of the displayed text to the spoken text, clause by clause.

    Display and spoken differ inside clauses (``30`` is spoken ``thirty``) but keep their punctuation, so the
    matching clause carries the time; inside it the position is proportional.
    """
    shown, said = clauses(display), clauses(spoken)
    if not shown or not said:
        return 0
    if len(shown) != len(said):
        return min(len(spoken) - 1, round(index / max(1, len(display)) * len(spoken)))
    k = next((k for k, (a, b) in enumerate(shown) if a <= index < b), len(shown) - 1)
    (a, b), (c, d) = shown[k], said[k]
    return min(d - 1, c + round((index - a) / max(1, b - a) * (d - c)))


def proof_number(text: str) -> dict | None:
    """The beat's measured quantity: ``from A to B`` rolls A to B; ordinals and bare years are not proof."""
    found = []
    for hit in NUMBER.finditer(text):
        prefix, digits, unit = hit.group(1) or '', hit.group(2), (hit.group(3) or '').lower()
        value = float(digits.replace(',', ''))
        if ORDINAL.search(text[:hit.start()]):
            continue
        if not prefix and not unit and digits.isdigit() and len(digits) == 4 and 1800 <= value <= 2100:
            continue
        suffix = '%' if unit.startswith(('%', 'percent', 'per')) else 'x' if unit in ('x', '×') else ''
        decimals = len(digits.split('.')[1]) if '.' in digits else 0
        found.append({'value': value, 'prefix': prefix, 'suffix': suffix, 'decimals': decimals,
                      'start': hit.start(), 'end': hit.end()})
    if not found:
        return None
    first = found[0]
    out = {'from': 0., 'to': first['value'], 'prefix': first['prefix'], 'suffix': first['suffix'],
           'decimals': first['decimals'], 'start': first['start'], 'end': first['end']}
    if len(found) > 1:
        second = found[1]
        ranged = (re.search(r'\bfrom\s+$', text[:first['start']], re.I)
                  and re.fullmatch(r'\s+to\s+', text[first['end']:second['start']], re.I))
        if ranged and second['prefix'] == first['prefix'] and second['suffix'] in (first['suffix'], ''):
            out.update({'from': first['value'], 'to': second['value'], 'end': second['end'],
                        'suffix': first['suffix'] or second['suffix'],
                        'decimals': max(first['decimals'], second['decimals'])})
    return out


def cta_phrase(text: str) -> tuple[int, int] | None:
    """The span of the beat's last call to action, as a short verbatim button label (at most five words)."""
    hits = list(CTA.finditer(text))
    if not hits:
        return None
    start = hits[-1].start(1)
    stop = re.search(r'[,;:.!?…]|\s(?:and|with|to|so|because)\s', text[start:])
    end = start + (stop.start() if stop else len(text) - start)
    words = list(re.finditer(r'\S+', text[start:end]))
    if len(words) > 5:
        end = start + words[4].end()
    return start, end


def is_launch(text: str) -> bool:
    """A product reveal ("Meet X", "Introducing X") together with a call to action is a launch arc."""
    return bool(REVEAL.search(text)) and any(cta_phrase(line) for line in re.split(r'\n+', text))

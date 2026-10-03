"""Something to show in a shot the storyboard left bare.

The Paint grammar is a figure plus a prop; a figure alone on white is rare. The rules director budgets about one
picture per nine words, while the stick look cuts at every sentence, so some shots get nothing. For those, in
order:

1. a name the sentence gives ("psychologists call this the negativity bias", "a general named Odoacer",
   "这叫做散射") as a term card;
2. a number the sentence says (digits are handled by the composer; here a number word with its noun: "ten
   compliments" -> 10 compliments);
3. a picture for the sentence's own words, found with the rules director's own meaning rules (same keyword
   index, same sense and agreement checks), except that an emoji may also stand for the very thing it is named
   after (Chinese: its first tag) when that thing is off the section's subject ("a world with lions" -> the
   lion); a long sentence is tried clause by clause when the whole finds nothing ("..., but missing a lion cost
   everything");
4. the picture still in play: the last picture of the same section, without its label (its words are no
   longer being said; the composer keeps it).

Everything is a fixed rule over the words, so the same script always gets the same shots. Step 3 needs the
director's local doodle-search model; when it is not on this computer the step is skipped (a render never
downloads anything).
"""
from __future__ import annotations

import re

from ...director import match
from ...director.rules import RulesDirector

TERM = {'en': re.compile(r"\b(?:calls?|called|known as|named|termed)\s+(?:(?:this|that|it|these|those|them)\s+)?"
                         r"(?:(the|an?)\s+)?([A-Za-z][\w'-]*(?:\s+[A-Za-z][\w'-]*){0,3})", re.I),
        'zh': re.compile(r'(?:叫做|叫作|称为|称作|所谓的?)([^\s，。！？；：、“”"\'（）()是的了就在和与也都]{2,8})')}
TERM_STOP = set('and or but because which that who when where while to in on of for with from by at as is are was '
                'were be been has have had will would can could than then so if after before since until'.split())
NUMBER_WORDS = {w: n for n, w in enumerate('zero one two three four five six seven eight nine ten eleven '
                                           'twelve'.split()) if n >= 2}
NUMBER_WORDS.update({w: 10 * n for n, w in enumerate('_ _ twenty thirty forty fifty sixty seventy eighty '
                                                     'ninety'.split()) if n >= 2})
NUMBER_WORD = re.compile(r'\b(' + '|'.join(NUMBER_WORDS) + r')\s+((?:[A-Za-z][\w-]*\s*){1,3})', re.I)
CLAUSE = {'en': re.compile(r'[,;:—–]\s*|\s+but\s+'), 'zh': re.compile(r'[，；：、—]')}
LABEL_STOP = TERM_STOP | set('the a an of more less most times its his her their our your my this these those'.split())


def term(text: str, lang: str) -> str | None:
    """The name a sentence gives something, or None. English: two words or more, or one capitalised word (a
    single lowercase word after "called" is usually an idiom: "called it a day")."""
    m = TERM[lang].search(text)
    if not m:
        return None
    if lang == 'zh':
        return m.group(1)
    words, name = [], not m.group(1)              # "named Odoacer" is a name; "the Rayleigh effect" a term
    for w in m.group(2).split():
        if w.lower() in TERM_STOP or (name and words and words[0][:1].isupper() and not w[:1].isupper()):
            break                                 # a name is its capitalised words: "Odoacer removed" -> Odoacer
        words.append(w)
    if not words or (len(words) == 1 and not words[0][:1].isupper()):
        return None
    out = ' '.join(words)
    return out[:1].upper() + out[1:]


def number_word(text: str, lang: str):
    """(position, value, label) for the first number word said with a noun ("ten compliments" -> 10,
    "compliments"), or None. One is never shown, and neither is a number with no noun after it."""
    if lang != 'en':
        return None
    for m in NUMBER_WORD.finditer(text):
        label = []
        for w in m.group(2).split():
            if w.lower() in LABEL_STOP or len(w) < 3:
                break
            label.append(w.strip(',.;:'))
            if w[-1:] in ',.;:':
                break
        if label:
            return m.start(), str(NUMBER_WORDS[m.group(1).lower()]), ' '.join(label)
    return None


class _Finder(RulesDirector):
    """The rules director's concept search, with one more way for an emoji to belong: being named exactly."""

    def _belongs(self, did, phrase, chapter):
        if super()._belongs(did, phrase, chapter):
            return True
        entry = self.matcher.entries[did]
        if entry['set'] != 'fluent' or not phrase:
            return False
        if self.lang == 'en':
            return self._is_head(did, phrase)
        return self._key(phrase) == ((entry.get('zh') or [''])[0]).strip()     # its own name, its first tag


def model_ready(lang: str) -> bool:
    repo, files = match.EMBED_FILES[lang]
    folder = match.CACHE / f"{repo.split('/')[1]}-{repo.split('/')[3][:8]}"
    return all((folder / name).exists() for name in files)


class Pictures:
    """Pictures for a sentence by the director's rules (built on first use; the model loads once)."""

    def __init__(self, board: dict, lang: str):
        self.board, self.lang = board, lang
        self._finder = None
        self.ready = model_ready(lang)

    def find(self, text: str, chapter: str):
        """(doodle id, label) for the best picture of ``text``, or None."""
        if not self.ready:
            return None
        if self._finder is None:
            self._finder = _Finder(self.lang)
            self._finder.topic = self._finder._topic_ranks(self.board)
        if chapter not in self._finder.topic:
            return None
        hits = self._finder._concepts(text, [], chapter)
        if not hits:                              # a long sentence dilutes each of its things: try clause by clause
            hits = sorted((h for clause in CLAUSE[self.lang].split(text) if clause.strip()
                           for h in self._finder._concepts(clause, [], chapter)), key=lambda h: -h.score)
        if not hits:
            return None
        h = hits[0]
        return h.id, (self._finder._label(h.phrase) or '') if h.phrase else ''

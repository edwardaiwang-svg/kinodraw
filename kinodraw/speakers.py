"""Who says each quoted line: one reading of the whole story, made before anything is voiced, that the voices
(speech.voice_parts), the speech bubbles and the people drawn talking (engine.storybook, engine.shots) all follow.

The text decides first:
- a screenplay label (JULES: ...);
- a speech tag in the line's own sentence ('"...," Kip said', 'said Mom', 'Nana said, "..."'), in the sentence right
  after it ('"..." Pendo whimpered.'), or closing the narration paragraph just before it ('... when Marisol finally
  said it.', 'Her first text said:');
- the person the paragraph's previous sentence is about ('Lena held her hand. "..."');
- a line spoken to someone ("..., Kip." / "Mom.") is not theirs, and someone who calls a parent "Dad" or "Mom"
  is that parent's child ("Dad's map"), while "your father" is said to the child.
Between two people, the lines nobody tags take turns, counted from the nearest line the text does decide within a
run of dialogue that no narration paragraph interrupts: a new paragraph is the other person, the same paragraph the
same one. The plan's speaker (the director's guess) stands only where the text says nothing; the story reading's own
guess comes last. ``mismatches`` is the QA net: a bubble whose speaker is not the one whose voice says it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .director.v3.semantics import name_key
from .director.v3.story import SPEAKER_LABEL, Reader, _inside

SAY = (r'said|says|say|asked|asks|replied|replies|told|tells|shouted|shouts|called|calls|yelled|yells|whispered|'
       r'whispers|answered|answers|added|adds|muttered|mutters|murmured|murmurs|cried|cries|laughed|laughs|snapped|'
       r'sighed|sighs|admitted|insisted|whimpered|whimpers|growled|growls|roared|roars|sobbed|begged|pleaded|'
       r'groaned|grumbled|exclaimed|declared|announced|wrote|writes|typed|types|texted|went\s+on|'
       r'continued|repeated|joked|teased|warned|explained|promised|offered|suggested|agreed|protested|'
       r'interrupted|breathed|gasped|hissed|squeaked|squealed|chirped|barked')
# '"..." Pendo whimpered one afternoon.': the sentence after the line names who said it, the verb in its first words.
TAG_AFTER = re.compile(r"^\W*(?:[\w’']+\W+){0,3}?(?:\w+ly\s+)?(?:" + SAY + r")\b", re.I)
# The paragraph before introduces the line: '... when Marisol finally said it.' / 'Her first text said:'.
INTRO = re.compile(r"(?:\b(?:" + SAY + r")(?:\s+(?:it|this|that|so|softly|quietly|slowly|aloud|out\s+loud))?\s*[.!]|:)"
                   r"\s*$", re.I)
# The narrator tells it as one of the cast: "Coach Ben here", "I'm Ava", "My name is Theo" (with I/my/me around).
# "Tom from Pipewise Plumbing here" too.
INTRODUCES = r"(?:\b(?:i['’]m|i\s+am|this\s+is|it['’]s|my\s+name\s+is|name['’]s|call\s+me)\s+{0}\b|" \
             r"\b{0}(?:,?\s+(?:from|at|with|of)\s+[^.!?,;\n]{{1,40}}?)?,?\s+here\b)"
# A name the speaker gives themselves when they are not in the cast: capitalised, after an optional title.
SELF_TITLE = r"(?:(?:Coach|Chef|Dr|Doctor|Mr|Mrs|Ms|Miss|Captain|Professor|Prof|Aunt|Auntie|Uncle|Grandma|Grandpa|" \
             r"Nana|Officer|Pastor|Nurse|Sister|Brother|Sir|Dame|Lady|Lord|Mama|Papa)\.?\s+)"
SELF_NAME = SELF_TITLE + r"?[A-Z][a-z’'-]+(?:\s+[A-Z][a-z’'-]+)?"
SELF_NAMED = re.compile(r"\b(?:I['’]m|I\s+am|[Mm]y\s+name\s+is|[Nn]ame['’]s|[Cc]all\s+me|[Tt]his\s+is)\s+(?P<a>" +
                        SELF_NAME + r")\b|(?:^|[.!?,]\s+)(?P<b>" + SELF_NAME +
                        r")(?:,?\s+(?:from|at|with|of)\s+[^.!?,;\n]{1,40}?)?,?\s+here\b")
# A broadcast sign-off closing a speaker's lines: "Jenna Ruiz, Millbrook Community News."
SIGN_OFF = re.compile(r"(?:^|[.!?]\s+)(?P<name>[A-Z][\w’'-]+(?:\s+[A-Z][\w’'-]+){0,2}),\s+(?:[A-Z0-9][\w’'&.-]*\s*)"
                      r"{1,6}[.!]?\s*$")
FIRST_PERSON = re.compile(r"\b(?:i|i['’]m|i['’]ve|i['’]ll|i['’]d|my|me|mine)\b", re.I)
I_SAID = re.compile(r"\bI\s+(?:\w+ly\s+)?(?:" + SAY + r")\b|\b(?:" + SAY + r")\s+I\b")
THEY = re.compile(r"\b(?:they|they[’']d|them)\b", re.I)
# Parent and grandparent titles, as a name ("Dad's map", "Mom.") or in "your father".
TITLES = (('female', 'parent', r'mom|mommy|mum|mummy|mother|mama|ma'),
          ('male', 'parent', r'dad|daddy|father|papa|pa|pop|baba'),
          ('female', 'grandparent', r'grandma|grandmother|granny|gran|nana|nan|grammy|nainai|abuela|oma'),
          ('male', 'grandparent', r'grandpa|grandfather|gramps|grampa|grandad|granddad|yeye|abuelo|opa'))
TITLE_RE = [(sex, rank, re.compile(r'(?<![\w’\'])(?:' + cue + r')(?![\w])', re.I)) for sex, rank, cue in TITLES]
PARENT_NAME = re.compile(r'\b(?:mother|father|mom|dad|mum|grand(?:mother|father|ma|pa)|nana|granny|gramps)\b', re.I)
CHILD_NAME = re.compile(r"\b(?:son|daughter|cub|child|kid|grand(?:son|daughter|child))\b", re.I)
# Where a name is a call to its person: at the line's start or after a pause, before a pause or the line's end
# ("Mom." / "..., Kip." / "Kip, look"), or after a greeting ("HELLO LENA THIS IS NANA").
GREETING = r'(?:hello|hi|hey|oh|dear|thanks|thank\s+you|bye|goodbye|good\s+(?:morning|night|evening|afternoon)|' \
           r'okay|ok|yes|yeah|no|please|come\s+on|listen|look|sorry|night)'
BEFORE = r'(?:^|[,.!?;:…—–-]\s*)'
AFTER = r'(?=\s*(?:[,.!?;:…—–-]|$))'
DETERMINER = re.compile(r"\b(?:my|your|his|her|their|our|the|a|an|that|this|whose)\s+$", re.I)
YOUR = re.compile(r'\byour\s+$', re.I)
YOUNG = {'baby', 'child', 'teen', 'young'}


def _norm(text):
    return ' '.join(re.sub(r'[^\w\s]', ' ', text.casefold()).split())


@dataclass
class Line:
    """One sentence's quotation(s): one speaker."""
    beat: str
    at: int                         # the beat's place in the story
    spans: list                     # [(start, end)] in the beat's spoken text
    words: str                      # the quoted words, joined
    guess: str | None               # the story reading's speaker (story.Reader, with the plan's talker hint)
    present: list = field(default_factory=list)
    bands: dict = field(default_factory=dict)
    anchor: str | None = None       # the speaker the text itself names
    why: str = ''
    crowd: bool = False             # "they'd shriek": a crowd, the narrator reads it
    plan: str | None = None
    called: list = field(default_factory=list)      # [(sex, rank)] a parent title the line calls someone by
    named: list = field(default_factory=list)       # cast ids the line calls by name
    titled: list = field(default_factory=list)      # parent titles used as a name ("Dad's map"): a child speaks
    yours: bool = False             # "your father": said to the child
    who: str | None = None
    outside: str = ''               # the sentence without its quotations


class Speakers:
    """The attribution: ``spans`` beat id -> [(start, end, speaker)] (as speech.segments takes them), ``of(beat,
    start)`` the speaker of the quotation that starts there, ``reader`` the story reading, ``bands`` speaker -> age
    band when they first speak."""

    def __init__(self, lines, reader):
        self.lines, self.reader = lines, reader
        self.spans, self.bands, self._at = {}, {}, {}
        for line in lines:
            for q0, q1 in line.spans:
                self._at[(line.beat, q0)] = line.who
                if line.who:
                    self.spans.setdefault(line.beat, []).append((q0, q1, line.who))
            if line.who:
                self.bands.setdefault(line.who, line.bands.get(line.who) or reader.age_band(line.who))

    def of(self, beat, start, default=None):
        return self._at.get((beat, start), default)


def attribute(beats: list[dict], plan: dict | None) -> Speakers:
    """``beats``: [{'id', 'spoken', 'section'}] in story order. Needs the plan's cast; without one every quotation
    stays with the narrator (reader None)."""
    cast = (plan or {}).get('cast') or []
    if not cast:
        return Speakers([], None)
    reader = Reader(cast)
    reader.prime([b['spoken'] for b in beats])
    me = narrator_of(beats, cast)
    talkers, planned = {}, {}
    for scene in (plan or {}).get('scenes') or ():
        for a in scene.get('actions') or ():
            if a.get('verb') == 'talk' and a.get('actor') in reader.by_id:
                talkers.setdefault(a.get('at_beat'), []).append(a['actor'])
        for shot in scene.get('shots') or ():
            for l in shot.get('lines') or ():
                if l.get('speaker') in reader.by_id and _norm(l.get('quote') or ''):
                    planned.setdefault(shot.get('beat_id'), []).append((_norm(l['quote']), l['speaker']))
    runs, run = [], []
    previous = None                    # the last sentence of the beat before
    for at, b in enumerate(beats):
        text = b['spoken']
        read = reader.read(b['id'], text, b.get('section'), talker=(talkers.get(b['id']) or [None])[0])
        label = SPEAKER_LABEL.match(text)
        labelled = next((c['id'] for c in reader.cast if label and label[1].lower() in (
            name_key(c['name']), name_key(c['name']).split()[0])), None)
        quoted = [i for i, s in enumerate(read) if s.quotes]
        if not quoted:
            if run and any(ch.isalnum() for ch in text):
                runs.append(run)
                run = []
            previous = read[-1] if read else previous
            continue
        for i in quoted:
            s = read[i]
            line = _line(reader, b['id'], at, s, text)
            line.plan = _planned(line, planned.get(b['id']), talkers.get(b['id']))
            if labelled:
                line.anchor, line.why = labelled, 'label'
            elif line.crowd:
                line.why = 'crowd'
            elif me and I_SAID.search(line.outside):
                line.anchor, line.why = me, 'tag'                              # '"Go," I said'
            elif any(not _inside([(q0 - s.start - 1, q1 - s.start) for q0, q1 in s.quotes], r[0])
                     for r in s.refs) and s.speaker:
                line.anchor, line.why = s.speaker, 'tag'                       # '"...," Kip said'
            elif i + 1 < len(read) and not read[i + 1].quotes and read[i + 1].subject and \
                    TAG_AFTER.match(read[i + 1].text):
                line.anchor, line.why = read[i + 1].subject, 'tag after'       # '"..." Pendo whimpered.'
            elif i == 0 and previous is not None and not previous.quotes and previous.subject and \
                    INTRO.search(previous.text):
                line.anchor, line.why = previous.subject, 'introduced'         # '... finally said it.'
            elif i > 0 and not read[i - 1].quotes and read[i - 1].subject:
                line.anchor, line.why = read[i - 1].subject, 'action'          # 'Lena held her hand. "..."'
            if line.anchor in line.named:
                line.anchor, line.why = None, ''                              # nobody calls themselves by name
            run.append(line)
        previous = read[-1]
    if run:
        runs.append(run)
    parents = {c['id'] for c in reader.cast if PARENT_NAME.search(c.get('name') or '')}
    children = {c['id'] for c in reader.cast if CHILD_NAME.search(c.get('name') or '')}
    for c in reader.cast:                                                 # "Theo's mother": Theo is her child
        m = re.match(r"(.+?)['’]s\s+", c.get('name') or '')
        if m and PARENT_NAME.search(c['name'][m.end():]):
            children |= {d['id'] for d in reader.cast if name_key(d['name']) == name_key(m[1])}
    done = []
    for run in runs:
        pair = _solve(run, done, parents, children, reader, me)
        done += run
        for line in run:                                                  # what the run told about who is whose
            if line.who and line.called:
                children.add(line.who)
                parents.update(p for p in _fits(line, pair, reader) if p != line.who)
            if line.who and line.titled:
                children.add(line.who)
    return Speakers(done, reader)


def narrator_of(beats: list[dict], cast: list[dict]) -> str | None:
    """The cast member who tells the story in the first person, introducing themselves outside any quotation
    ("Morning, runners! Coach Ben here, with my favorite..."), else None."""
    for b in beats:
        text = re.sub(r'["“][^"”]*["”]?', ' ', b['spoken'])
        if not FIRST_PERSON.search(text):
            continue
        for c in cast:
            key = name_key(c.get('name') or '')
            for k in dict.fromkeys([key] + [t for t in key.split() if len(t) > 2]):
                if k and re.search(INTRODUCES.format(re.escape(k)), text, re.I):
                    return c['id']
    return None


def introduced(text: str, cast: list[dict], sign_off: bool = False) -> str | None:
    """Who ``text`` (a narration or one speaker's lines, quotations left out) says its speaker is: the cast id of a
    cast member it introduces in the first person ("I'm Ava", "Tom from Pipewise Plumbing here") or, with
    ``sign_off``, signs off as ("Jenna Ruiz, Millbrook Community News."); else a name outside the cast that
    tells its sex by itself ("Coach Ben here": a title or a known given name, speech.guess_person); else None."""
    from .speech import guess_person
    text = re.sub(r'["“][^"”]*["”]?', ' ', text)
    first = bool(FIRST_PERSON.search(text))
    for c in cast:
        key = name_key(c.get('name') or '')
        for k in dict.fromkeys([key] + [t for t in key.split() if len(t) > 2]):
            if not k:
                continue
            if first and re.search(INTRODUCES.format(re.escape(k)), text, re.I):
                return c['id']
            m = SIGN_OFF.search(text) if sign_off else None
            if m and name_key(m['name']) in (key, k):
                return c['id']
    names = [m['a'] or m['b'] for m in SELF_NAMED.finditer(text)] if first else []
    if sign_off and SIGN_OFF.search(text):
        names.append(SIGN_OFF.search(text)['name'])
    return next((n for n in names if guess_person(n)[0]), None)


def _line(reader, beat, at, s, text) -> Line:
    words = ' '.join(text[q0:q1].strip(' "“”') for q0, q1 in s.quotes)
    outside = ''.join(ch if not _inside([(q0 - s.start - 1, q1 - s.start) for q0, q1 in s.quotes], i) else ' '
                      for i, ch in enumerate(s.text))
    line = Line(beat, at, list(s.quotes), words, s.speaker, list(s.present),
                {cid: s.ages.get(cid) or reader.age_band(cid) for cid in reader.by_id})
    line.crowd = s.speaker is None and bool(THEY.search(outside))
    line.outside = outside
    for c in reader.cast:
        key = name_key(c['name'])
        for k in dict.fromkeys([key, key.split()[0] if key.split() else '']):
            if len(k) > 1 and "'" not in k and '’' not in k and _called(words, re.escape(k)):
                line.named.append(c['id'])
                break
    for sex, rank, pattern in TITLE_RE:
        for m in pattern.finditer(words):
            if any(name_key(reader.by_id[cid]['name']).split()[0] == m.group().casefold() for cid in line.named):
                continue                                                  # "Nana" is her name here
            before = words[:m.start()]
            if _called(words, re.escape(m.group()), m.start()):
                line.called.append((sex, rank))
            elif YOUR.search(before):
                line.yours = True
            elif m.group()[0].isupper() and not DETERMINER.search(before):
                line.titled.append(m.group().casefold())
    return line


def _called(words, name, at=None) -> bool:
    """``name`` is a call to someone in ``words`` (at ``at``, else anywhere)."""
    for m in re.finditer(r'(?<![\w’\'])' + name + r'(?![\w’\'])', words, re.I):
        if at is not None and m.start() != at:
            continue
        before, after = words[:m.start()], words[m.end():]
        if (re.search(BEFORE + r'$', before) or re.search(r'\b' + GREETING + r'\s*,?\s+$', before, re.I)) and \
                (re.match(AFTER, after) or re.search(r'\b' + GREETING + r'\s*,?\s+$', before, re.I)):
            return True
    return False


def _planned(line, planned, talkers):
    """The plan's speaker for the line: the plan line that quotes it, else the beat's one talker."""
    words = _norm(line.words)
    for quote, who in planned or ():
        if words and (quote in words or words in quote):
            return who
    return talkers[0] if talkers and len(set(talkers)) == 1 else None


def _fits(line, pair, reader):
    """The people of ``pair`` the line's parent titles could call: of its sex, not a child; one whose name says it
    ("Mia's mother", "Nana") first."""
    fit = {cid for sex, _ in line.called for cid in pair
           if cid and line.bands.get(cid) not in YOUNG and reader.sex(cid) == sex}
    return {cid for cid in fit if PARENT_NAME.search(reader.by_id[cid].get('name') or '')} or fit


def _pair_of(run, done):
    """The two people talking in a run: those the text names as speakers first, then the people the story reading
    and the plan guess and whoever spoke last before, then the people on stage."""
    votes = {}
    for line in run:
        if line.anchor:
            votes[line.anchor] = votes.get(line.anchor, 0) + 3
        for cid in (line.guess, line.plan):
            if cid:
                votes[cid] = votes.get(cid, 0) + 1
        for cid in line.present:
            votes[cid] = votes.get(cid, 0) + .25
    recent = []
    for line in reversed(done):
        if line.who and line.who not in recent:
            recent.append(line.who)
        if len(recent) == 2:
            break
    for k, cid in enumerate(recent):
        votes[cid] = votes.get(cid, 0) + 1 + (.5 if k == 0 else 0)
    order = sorted(votes, key=lambda cid: -votes[cid])
    return order[:2]


def _solve(run, done, parents, children, reader, me=None) -> list:
    """Each line's speaker (``who``) in one run of dialogue; returns the two people talking, if two. ``me``: the
    cast member who narrates; their own words are the narration, so a quotation nobody tags is someone else's."""
    named = {line.anchor for line in run if line.anchor}
    pair = _pair_of(run, done) if len(named) < 3 else []
    two = len(pair) == 2
    for line in run:                                    # what the text rules out, between two people, decides
        if line.anchor or line.crowd or not two:
            continue
        out = set(line.named) | _fits(line, pair, reader) | ({me} if me else set())
        titled = [t for t in line.titled if not any(name_key(reader.by_id[cid].get('name') or '') == t for cid in pair)]
        if titled:
            out |= parents
        if line.yours:
            out |= children
        out &= set(pair)
        if len(out) == 1:
            line.anchor, line.why = next(cid for cid in pair if cid not in out), 'addressed'
        elif not out and titled and len(set(pair) & children) == 1:
            line.anchor, line.why = next(iter(set(pair) & children)), 'addressed'
    for k, line in enumerate(run):
        if line.crowd:
            continue
        if line.anchor:
            line.who = line.anchor
            continue
        excluded = set(line.named) | ({me} if me else set())
        if two:
            ruled = [(abs(j - k), j > k, j) for j, other in enumerate(run) if other.anchor and other.anchor in pair]
            if ruled:
                _, _, j = min(ruled)
                turns = len({run[i].at for i in range(min(j, k), max(j, k) + 1)}) - 1
                other = pair[1] if run[j].anchor == pair[0] else pair[0]
                line.who, line.why = (run[j].anchor if turns % 2 == 0 else other), 'turns'
                continue
        same = next((other for other in reversed(run[:k]) if other.at == line.at and other.who), None)
        if same is not None:
            line.who, line.why = same.who, 'same paragraph'
            continue
        again = next((other.who for other in done + run[:k] if other.who and _norm(other.words) == _norm(line.words)),
                     None) if len(_norm(line.words).split()) >= 3 else None     # never "Fine." or "Yes."
        for who, why in ((again, 'said before'), (line.plan, 'plan'), (line.guess, 'reading')):
            if who and who not in excluded:
                line.who, line.why = who, why
                break
        if two and line.who in pair:                    # the first line of a run nobody tags sets the turns
            line.anchor = line.who
    return pair if two else []


# ------------------------------------------------------------------ the QA net
def voiced(parts: dict) -> dict:
    """beat id -> [[start, end, speaker or None]]: who each voice part of speech.voice_parts reads (None the
    narrator), in the beat's spoken text; saved as voice/speakers.json for ``mismatches``."""
    return {bid: [[seg.start, seg.end, seg.speaker] for seg, _, _ in todo['parts']] for bid, todo in parts.items()}


def mismatches(bubbles: list[dict], said: dict, names: dict | None = None) -> list[str]:
    """QA problems: a speech bubble (build/bubbles.json row: beat, start, end, speaker, and 'role' when the voice's
    role is drawn as another id of the same person) whose words some other voice reads (``said``: ``voiced``)."""
    names = names or {}
    name = lambda who: names.get(who) or (who.split(':', 1)[-1] if who else 'the narrator')
    out = []
    for row in bubbles:
        want = row.get('role', row['speaker'])
        heard = [who for a, z, who in said.get(row['beat'], ()) if a < row['end'] and row['start'] < z]
        wrong = [name(who) for who in dict.fromkeys(heard) if who != want] if heard else ['nobody']
        if wrong:
            out.append(f'The speech bubble "{row["text"]}" (beat {row["beat"]}) is {name(want)}\'s line, but '
                       f'{" and ".join(wrong)} {"say" if len(wrong) > 1 else "says"} it.')
    return out

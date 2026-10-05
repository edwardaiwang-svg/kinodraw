"""Script references and conservative English cast cues shared by direction and repair."""
from __future__ import annotations

import re

from .schema import ATMOSPHERES

SPECIES = {
    'lion': ('quadruped', 'feline'), 'lioness': ('quadruped', 'feline'),
    'tiger': ('quadruped', 'feline'), 'tigress': ('quadruped', 'feline'), 'cat': ('quadruped', 'feline'),
    'dog': ('quadruped', 'canine'), 'wolf': ('quadruped', 'canine'), 'fox': ('quadruped', 'canine'),
    'hyena': ('quadruped', 'other'), 'bear': ('quadruped', 'ursine'), 'horse': ('quadruped', 'equine'),
    'cow': ('quadruped', 'bovine'), 'mouse': ('quadruped', 'rodent'), 'rabbit': ('quadruped', 'rodent'),
    'bird': ('bird', 'bird'), 'owl': ('bird', 'bird'), 'eagle': ('bird', 'bird'),
    'fish': ('fish', 'other'), 'dolphin': ('fish', 'other'), 'lizard': ('quadruped', 'reptile'),
    'monkey': ('quadruped', 'primate'), 'human': ('human', 'human'), 'boy': ('human', 'human'),
    'girl': ('human', 'human'), 'man': ('human', 'human'), 'woman': ('human', 'human'),
    'robot': ('object', 'other'), 'blob': ('blob', 'other'),
}
SPECIES_RE = re.compile(r'\b(' + '|'.join(SPECIES) + r')\b', re.I)
NAME_RE = re.compile(r'\b[A-Z][a-z]+(?:[ -][A-Z][a-z]+)*\b')
STOP_NAMES = set('''A An The Once Upon At In On By From To And But As Then When Whenever While First Next Finally
Today Tomorrow Yesterday This That These Those Here There It Its He His Him She Her They Their We Our You
Your I Why What How Step Key Lesson News Report Data According Introducing Meet Try Start Every All One
Two Three No Now Dawn Night Morning After Before Because For If So With Without Still Meanwhile Baba'''.split())
TITLES = {'King', 'Queen', 'Doctor', 'Professor', 'Captain'}
COLOURS = ('#DCA45C', '#DB7F42', '#A88058', '#7B9CAB', '#AA899F', '#85A47B')
ACTION_CUES = {
    'walk': r'walk\w*', 'run': r'run(?:s|ning)?|ran', 'roar': r'roar\w*', 'whimper': r'whimper\w*',
    'tremble': r'trembl\w*|shiver\w*', 'nudge': r'nudg\w*', 'laugh': r'laugh\w*',
    'swipe': r'swip\w*', 'look': r'look\w*', 'sit': r'sits?|sat', 'sleep': r'sleep\w*|slept',
    'breathe_heavy': r'breath(?:es?|ing)\s+heavily', 'hide': r'hid(?:e|es|ing)?|hid',
    'pounce': r'pounc\w*', 'hug': r'hug\w*', 'point': r'point\w*', 'talk': r'said|says?|talk\w*',
}
BEFORE_NAME = re.compile(r'\b(?:' + '|'.join(SPECIES) +
                         r')(?:\s+(?:cub|puppy|kitten))?(?:\s+(?:named|called))?\s*$', re.I)


def _text(value, lang):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get(lang, next(iter(value.values()), ''))
    return ''


def beats(script_beats, lang='en') -> list[dict]:
    """Accept a legacy board or [{id/beat_id, text/display, spoken, section_id/chapter}]."""
    if isinstance(script_beats, dict):
        lang = script_beats.get('lang', lang)
        script_beats = script_beats['beats']
    out = []
    for b in script_beats:
        text = _text(b.get('text', b.get('display', '')), lang)
        out.append({'id': b.get('id', b.get('beat_id')), 'text': text,
                    'spoken': _text(b.get('spoken', text), lang),
                    'section': b.get('section_id', b.get('chapter', 'main')),
                    'kind': b.get('kind', 'narration'), 'visuals': b.get('visuals', [])})
    ids = [b['id'] for b in out]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('Script beats need unique, nonempty string ids')
    return out


def candidate_ids(candidates, beat_id) -> set[str]:
    """Candidates are per-beat lists of ids/{id, desc}, or one shared list."""
    offered = candidates.get(beat_id, []) if isinstance(candidates, dict) else candidates
    return {c if isinstance(c, str) else c['id'] for c in (offered or [])}


def name_key(name) -> str:
    return re.sub(r'^(?:' + '|'.join(TITLES) + r')\s+', '', name, flags=re.I).casefold()


def mentions(name, text) -> bool:
    name = name_key(name)
    return bool(name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I))


def detect_cast(script_beats) -> list[dict]:
    text = '\n'.join(b['spoken'] for b in script_beats)
    found = []
    for m in NAME_RE.finditer(text):
        words = m.group().split()
        start = m.start()
        while words and words[0] in STOP_NAMES:
            start += len(words.pop(0)) + 1
        while words and words[0] in TITLES:
            words.pop(0)
        if words and not any(w in STOP_NAMES for w in words):
            found.append((' '.join(words), start, m.end()))
    names = list(dict.fromkeys(n for n, _, _ in found))
    cast = []
    for name in names:
        contexts = []
        named = False
        for i, (n, start, end) in enumerate(found):
            if n != name:
                continue
            left = max(start - 60, found[i - 1][2] if i else 0)
            right = min(end + 100, found[i + 1][1] if i + 1 < len(found) else len(text))
            before = re.split(r'[.!?\n]', text[left:start])[-1]
            after = re.split(r'[.!?\n]', text[end:right])[0]
            # A preceding noun belongs to this name only when adjacent; following action clauses may
            # describe another animal. "lion cub Pendo watched the tigress Mara" has two genomes.
            noun = BEFORE_NAME.search(before)
            introduced = re.match(r',\s+(?:a|an)\s+[^,]+', after, re.I)
            location = re.search(r'\b(?:in|at|across|from|near|of)\s+(?:the\s+)?(?:[a-z]+\s+){0,2}$', before, re.I)
            subject = re.match(r"\s+(?:(?:was|is|did|would|had)\s+)?(?:" + '|'.join(ACTION_CUES.values()) +
                               r"|watch\w*|lived|loved|returned|guarded)\b", after, re.I)
            # Capitalization alone (places, headings, plural common nouns) is not a name cue.
            named |= bool(noun or (introduced and not location and SPECIES_RE.search(introduced.group())) or
                          any(w in TITLES for w in text[start:end].split()) or
                          (subject and not name.endswith('s') and not SPECIES_RE.fullmatch(name)) or
                          re.search(r'\b(?:mother|father|sister|brother),\s*$', before, re.I) or
                          re.search(r'\b(?:hug\w*|met|saw|named|called)\s*$', before, re.I))
            # Only explicit noun phrases and subject-owned attributes supply traits. Mere
            # proximity (especially an object followed by someone else's description) cannot.
            local = before[noun.start():] if noun else ''
            if introduced and not location and SPECIES_RE.search(introduced.group()):
                local += introduced.group()
            group = re.match(r'\s+and the other (lionesses|tigresses|lions|tigers)\b', after, re.I)
            if group:
                local += ' ' + {'lionesses': 'lioness', 'tigresses': 'tigress',
                                'lions': 'lion', 'tigers': 'tiger'}[group[1].lower()]
            attribute = re.match(r'\s+(?:is|was|has|had)\s+(.+)', after, re.I)
            if attribute:
                owned = re.split(r"\b(?:of|behind|beside|against|with|when|while)\b|"
                                 r"\b(?:his|her|their)\s+(?:mother|father|sister|brother)\b",
                                 attribute[1], maxsplit=1, flags=re.I)[0]
                local += ' ' + owned
            title = next((w for w in text[start:end].split() if w in TITLES), '')
            contexts.append(title + ' ' + local)
        if not named:
            continue
        description = next((s for s in contexts if SPECIES_RE.search(s)), '')
        cue = ' '.join(contexts).lower()
        species_hit = SPECIES_RE.search(description)
        species = species_hit.group().lower() if species_hit else 'lion' if re.search(r'\bmane\b', cue) else 'human'
        kind, family = SPECIES[species]
        age = ('baby' if re.search(r'\b(cub|baby|puppy|kitten|hatchling)\b', cue) else
               'young' if species in ('boy', 'girl') or re.search(r'\b(young|child|teen)\b', cue) else
               'old' if re.search(r'\b(old|elderly|ancient)\b', cue) else 'adult')
        marks = []
        for mark, pattern in (
            ('mane_black', r'black\s+mane'), ('mane_gold', r'gold(?:en)?\s+mane'),
            ('mane_none', r'no\s+mane|\bcub\b'), ('stripes', r'tigress|tiger|stripe'),
            ('spots', r'spot'), ('scar_nose', r'scar(?:red)?\s+nose|scar\s+(?:on|across)\s+(?:his|her|the)\s+nose'),
            ('scar_eye', r'scar.{0,25}eye'), ('crown', r'\bking\b|\bqueen\b|crown'),
            ('glasses', r'glasses'), ('freckles', r'freckles'), ('fluffy', r'fluffy'),
        ):
            if re.search(pattern, cue):
                marks.append(mark)
        sex = ('female' if species in ('tigress', 'lioness', 'girl', 'woman', 'cow') or
               re.search(r'\b(she|her|female|mother|queen)\b', cue) else
               'male' if species in ('boy', 'man') or re.search(r'\b(he|his|male|father|king)\b', cue) else 'unknown')
        temperament = ('fierce' if re.search(r'fierce|roar|massive', cue) else
                       'timid' if re.search(r'timid|whimper|trembl|afraid', cue) else
                       'wise' if re.search(r'wise|old', cue) else
                       'sly' if re.search(r'sly|sneak', cue) else
                       'playful' if re.search(r'playful|laugh', cue) else 'gentle')
        cast.append({'id': re.sub(r'\W+', '_', name.lower()), 'name': name, 'kind': kind, 'species': species,
                     'family': family, 'age': age, 'sex': sex,
                     'size': 1.4 if 'massive' in cue else .55 if age == 'baby' else 1.0,
                     'palette': {'body': COLOURS[len(cast) % len(COLOURS)], 'accent': '#F2D4A4', 'eye': '#202020'},
                     'marks': marks or ['none'], 'temperament': temperament})
    return cast


def actions(beat, cast) -> list[dict]:
    out = []
    text = beat['spoken']
    # Resolve full names first so Ann cannot borrow a verb from Mary Ann.
    pattern = '|'.join(re.escape(name_key(c['name'])) for c in sorted(cast, key=lambda c: -len(name_key(c['name']))))
    starts = list(re.finditer(r'(?<!\w)(?:' + pattern + r')(?!\w)', text, re.I)) if pattern else []
    for c in cast:
        seen = set()
        for i, start in enumerate(starts):
            if start.group().casefold() != name_key(c['name']):
                continue
            end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
            tail = re.split(r'[.!?;\n]|\b(?:while|whereas|when)\b', text[start.end():end], maxsplit=1, flags=re.I)[0]
            tail = re.sub(r'^,\s+(?:a|an)\s+[^,]+,', '', tail, flags=re.I)
            # A coordinated verb keeps the subject; a fresh noun/pronoun starts another clause.
            tail = re.split(r'\b(?:but|and)\s+(?:the|a|an|he|she|it|they)\b', tail, maxsplit=1, flags=re.I)[0]
            for verb, pattern in ACTION_CUES.items():
                if verb in seen:
                    continue
                for hit in re.finditer(r'\b(?:' + pattern + r')\b', tail, re.I):
                    clause = re.split(r'\bbut\b', tail[:hit.start()], flags=re.I)[-1]
                    if re.search(r"\b(?:not|never|cannot)\b|\b\w+n['’]t\b", clause, re.I):
                        continue
                    out.append({'actor': c['id'], 'verb': verb, 'at_beat': beat['id'],
                                'intensity': 3 if verb in ('roar', 'swipe', 'pounce') else 1})
                    seen.add(verb)
                    break
    return out


def atmosphere(text) -> str:
    text = text.lower()
    fog, star = 'fog' in text or 'mist' in text, 'shooting star' in text
    if fog and star:
        return 'fog_with_shooting_star'
    if fog:
        return 'fog'
    if star:
        return 'shooting_star'
    for kind, cue in (('night_stars', 'stars|starfield|night'), ('rays', 'sunlight|light rays'),
                      ('dawn', 'dawn|sunrise'), ('underwater', 'underwater|beneath the sea')):
        if re.search(cue, text):
            return kind
    return next((k for k in ATMOSPHERES if k != 'none' and re.search(r'\b' + k + r'\b', text)), 'none')

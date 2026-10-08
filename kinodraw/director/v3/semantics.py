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
    'leopard': ('quadruped', 'feline'), 'cheetah': ('quadruped', 'feline'), 'panther': ('quadruped', 'feline'),
    'kitten': ('quadruped', 'feline'), 'puppy': ('quadruped', 'canine'), 'jackal': ('quadruped', 'canine'),
    'elephant': ('quadruped', 'other'), 'giraffe': ('quadruped', 'other'), 'rhino': ('quadruped', 'other'),
    'hippo': ('quadruped', 'other'), 'zebra': ('quadruped', 'equine'), 'antelope': ('quadruped', 'bovine'),
    'gazelle': ('quadruped', 'bovine'), 'deer': ('quadruped', 'bovine'), 'goat': ('quadruped', 'bovine'),
    'sheep': ('quadruped', 'bovine'), 'warthog': ('quadruped', 'other'), 'pig': ('quadruped', 'other'),
    'gorilla': ('quadruped', 'primate'), 'chimpanzee': ('quadruped', 'primate'),
    'squirrel': ('quadruped', 'rodent'), 'crocodile': ('quadruped', 'reptile'), 'turtle': ('quadruped', 'reptile'),
    'frog': ('quadruped', 'other'), 'parrot': ('bird', 'bird'), 'penguin': ('bird', 'bird'),
    'hedgehog': ('quadruped', 'rodent'), 'porcupine': ('quadruped', 'rodent'), 'hamster': ('quadruped', 'rodent'),
    'rat': ('quadruped', 'rodent'), 'tortoise': ('quadruped', 'reptile'), 'snake': ('quadruped', 'reptile'),
    'duck': ('bird', 'bird'), 'goose': ('bird', 'bird'), 'swan': ('bird', 'bird'), 'chicken': ('bird', 'bird'),
    'hen': ('bird', 'bird'), 'flamingo': ('bird', 'bird'), 'crow': ('bird', 'bird'), 'sparrow': ('bird', 'bird'),
    'robin': ('bird', 'bird'), 'firefly': ('bird', 'other'), 'bee': ('bird', 'other'),
    'butterfly': ('bird', 'other'), 'beetle': ('quadruped', 'other'), 'ladybug': ('quadruped', 'other'),
    'otter': ('quadruped', 'other'), 'badger': ('quadruped', 'other'), 'raccoon': ('quadruped', 'other'),
    'donkey': ('quadruped', 'equine'), 'whale': ('fish', 'other'), 'shark': ('fish', 'other'),
    'snail': ('blob', 'other'),
}
SPECIES_RE = re.compile(r'\b(' + '|'.join(SPECIES) + r')\b', re.I)
HUMAN_SPECIES = {'human', 'boy', 'girl', 'man', 'woman'}
# Young-animal nouns: "Pendo, their only cub" names an animal without saying which one.
YOUNG = r'cub|kitten|puppy|pup|foal|calf|chick|hatchling'
YOUNG_RE = re.compile(r'\b(?:' + YOUNG + r')s?\b', re.I)
# Body parts only animals own; a possessive owner of one is an animal ("Mara laid her paw").
PARTS = r'manes?(?!\s+of\s+(?:\w+\s+)?hair)|paws?|fur(?!\s+(?:coat|collar|hat|hood|trim|boots|scarf))|snout|hooves|hoof|claws|fangs|tusks|beak'
# A specific cue picks the species; any other animal cue joins the story's own animals.
CUE_SPECIES = (('hooves|hoof|foal', 'horse'), ('tusks', 'elephant'), ('beak|chick|hatchling', 'bird'),
               ('kitten', 'cat'), ('puppy|pup', 'dog'), ('manes?', 'lion'))
ANIMAL_WORDS = re.compile(r'\b(?:' + '|'.join(SPECIES) + '|' + YOUNG + r'|animal|creature|beast|other)(?:s|es)?\b|'
                          r'\b(?:they|them|their)\b', re.I)
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
BEFORE_NAME = re.compile(r'\b(?:(?:' + '|'.join(SPECIES) + r')(?:\s+(?:cub|puppy|kitten))?|(?<=his |her )(?:' + YOUNG +
                         r')(?:,)?)(?:\s+(?:named|called))?\s*$', re.I)


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


# Display names a planner gives a character at another age or in a role: "Dana as a little girl",
# "young Dana", "Dana (age 6)", "little Dana", "Dana, now grown". Every pattern below is anchored or fixed-width (no
# overlapping quantifiers), so each runs in linear time, and a name longer than NAME_CAP is never read: script text
# can steer the planner's strings.
NAME_CAP = 80
YOUNGER = r'little|young|younger|baby|child|kid|girl|boy|teen(?:age)?|small'
_DESCRIBED = re.compile(r'[(,]|\s(?:as|at|age|aged|when)\s', re.I)
_AGE_WORD = re.compile(r'(?:(?:the|a|an)\s+)?(?:' + YOUNGER + r'|old|older|elderly|grown|adult)\s+', re.I)
_ROLE = re.compile(r'\s(?:as|when)\s', re.I)
_ARTICLE = re.compile(r'(?:a|an|the)\s+', re.I)


def core_name(name) -> str:
    """The proper name inside a described display name ('' when nothing is left or the name is too long)."""
    key = name_key(name).strip() if len(name) <= NAME_CAP else ''
    cut = _DESCRIBED.search(key)
    key = (key[:cut.start()] if cut else key).strip()
    age = _AGE_WORD.match(key)
    return (key[age.end():] if age else key).strip()


def _role(name) -> str:
    key = name_key(name) if len(name) <= NAME_CAP else ''
    at = _ROLE.search(key)
    if not at:
        return ''
    rest = key[at.end():].strip()
    article = _ARTICLE.match(rest)
    rest = rest[article.end():] if article else rest
    return rest[:-1].strip() if rest.endswith(')') else rest


def actor_named(name, text) -> bool:
    """The text names this character by its full or core name, or by its described role
    ('Dana as a little girl' is on screen when the text shows 'a little girl')."""
    if len(name) > NAME_CAP:
        return False
    role = _role(name)
    return (mentions(name, text) or bool(core_name(name)) and mentions(core_name(name), text)
            or bool(role) and mentions(role, text))


def resolve_actor(ref, cast_by_id):
    """A cast id for an action's actor given as an id, a display name or a described name; None if unknown.

    'Dana as a little girl' becomes Dana's younger variant when the cast declares one, else Dana.
    """
    if ref in cast_by_id:
        return ref
    if len(str(ref)) > NAME_CAP:
        return None
    key = name_key(str(ref).replace('_', ' ')).strip()
    same = [cid for cid, c in cast_by_id.items() if name_key(c['name']) == key]
    if same:
        return same[0]
    core = core_name(key)
    family = [cid for cid, c in cast_by_id.items() if core and core_name(c['name']) == core]
    if len(family) > 1:
        younger = re.search(r'\b(?:' + YOUNGER + r')\b', key, re.I) is not None
        rank = {'baby': 0, 'young': 1, 'adult': 2, 'old': 3}
        family.sort(key=lambda cid: rank.get(cast_by_id[cid].get('age'), 2) * (1 if younger else -1))
    return family[0] if family else None


MARK_CUES = (
    ('mane_black', r'\b(?:black|dark)\s+mane\b'), ('mane_gold', r'\bgold(?:en)?\s+mane\b'),
    ('mane_none', r'\b(?:no|without)\s+(?:a\s+)?mane\b|\bcub\b'),
    ('stripes', r'\b(?:tigress|tiger|stripes?|striped)\b'), ('spots', r'\b(?:spots?|spotted)\b'),
    ('scar_nose', r'\bscar(?:red)?\s+nose\b|\bscars?\s+(?:on|across|over)\s+(?:(?:his|her|the|a)\s+)?nose\b'),
    ('scar_eye', r'\bscarred\s+eye\b|\bscars?\s+(?:on|across|over|above)\s+(?:(?:his|her|the|a|left|right)\s+){0,3}eye\b'),
    ('crown', r'\b(?:king|queen|crown)\b'), ('glasses', r'\bglasses\b'),
    ('freckles', r'\bfreckles\b'), ('fluffy', r'\bfluffy\b'),
)


def _mark_evidence(cue):
    present, absent = set(), set()
    # A fresh coordinated predicate ends the previous predicate's negation scope.
    for clause in re.split(r'[,;.!?\n]|\bbut\b|\band\s+(?=(?:is|was|has|had)\b)', cue):
        if re.search(r'\b(?:might|may|perhaps|maybe|possibly|either|whether|or)\b', clause):
            continue
        for mark, pattern in MARK_CUES:
            for hit in re.finditer(pattern, clause):
                prefix = clause[:hit.start()]
                negative = re.search(r"\b(?:no|not|never|without)\b|\b\w+n['’]t\b", prefix)
                if negative and not re.search(r'\bnot only\b', prefix):
                    absent.add(mark)
                else:
                    present.add(mark)
    # A cub's usual lack of a mane yields to an explicitly described mane.
    if present & {'mane_black', 'mane_gold'} and not re.search(r'\b(?:no|without)\s+(?:a\s+)?mane\b', cue):
        present.discard('mane_none')
    if 'mane_none' in present:
        absent.update(('mane_black', 'mane_gold'))
    if 'mane_black' in present:
        absent.update(('mane_none', 'mane_gold'))
    if 'mane_gold' in present:
        absent.update(('mane_none', 'mane_black'))
    ambiguous = present & absent
    return present - ambiguous, absent - ambiguous


def _positive_cue(cue):
    return '; '.join(clause for clause in re.split(r'[,;.!?\n]|\b(?:but|and|with)\b|(?=\bwithout\b)', cue)
                     if not re.search(r"\b(?:no|not|never|without|might|may|perhaps|maybe|possibly|either|whether|or)\b|"
                                      r"\b\w+n['’]t\b", clause))


def _owned_possessives(text, found):
    """Resolve singular body descriptions only when a sentence has one clear subject.

    In "He nudged Pendo with his scarred nose", Pendo is the object. A plural or
    competing subject clears the antecedent instead of donating its traits to a name.
    """
    owned, subject, gender = {}, None, None
    verbs = r'(?:is|was|has|had|did|would|' + '|'.join(ACTION_CUES.values()) + r'|\w+ed)\b'
    for sentence in re.finditer(r'[^.!?\n]+', text):
        body = sentence.group().strip(' \t\"“”')
        local = [(n, start, end) for n, start, end in found
                 if sentence.start() <= start < sentence.end()]
        subjects = [(n, start) for n, start, end in local
                    if re.match(r'\s+' + verbs, text[end:sentence.end()], re.I)]
        plural = re.search(r'\b(?:they|their)\b', body, re.I)
        embedded_subject = re.search(r'.+\b(?:he|she)\b', body, re.I)
        coordinated = any(re.search(r'\b(?:and|or)\s+(?:the\s+)?$', text[end:start], re.I)
                          for _, start in subjects for _, _, end in local if end < start)
        if plural or coordinated or embedded_subject or len(subjects) > 1:
            subject = None
        elif re.match(r'(?:he|she)\b', body, re.I):
            pronoun_gender = 'female' if body.lower().startswith('she') else 'male'
            if subjects or gender != pronoun_gender:
                subject = None
            gender = pronoun_gender
        elif len(subjects) == 1:
            subject = subjects[0][0]
            male = re.search(r'\b(?:king|he|his|male)\b', body, re.I)
            female = re.search(r'\b(?:queen|she|her|female)\b', body, re.I)
            gender = 'male' if male and not female else 'female' if female and not male else None
        else:
            subject = None
        if subject is None:
            continue
        for hit in re.finditer(r'\b(?:his|her)\s+((?:(?!mother\b|father\b|sister\b|brother\b)[\w,-]+\s+){0,4}'
                               r'(?:mane|nose|eye)\b)', body, re.I):
            if gender and gender != ('male' if hit.group().lower().startswith('his') else 'female'):
                continue
            # Preserve negation/uncertainty from the body phrase's own clause.
            prefix = re.split(r'[,;]|\bbut\b|\band\s+(?=(?:is|was|has|had)\b)',
                              body[:hit.start()], flags=re.I)[-1]
            if re.search(r"\b(?:no|not|never|without|might|may|perhaps|maybe)\b|\b\w+n['’]t\b", prefix, re.I):
                continue
            owned.setdefault(subject, []).append(hit[1])
    return owned


def _animal_parts(text, found, characters, sexes):
    """Animal body parts with one clear named owner.

    "Mara laid her paw", "Pendo was small, with oversized paws", "Kojo's mane", and a
    pronoun-led sentence continuing the previous sentence's only character ("lived King
    Kojo. His mane was dark"). Another animal or a plural between owner and part blocks it.
    """
    owned, previous = {}, []
    mods = r"(?:(?!(?:into|in|on|of|with|to|from|by|for|at|and|or)\b)[\w-]+,?\s+){0,3}"
    for sentence in re.finditer(r'[^.!?\n]+', text):
        body = sentence.group()
        lead = re.match(r'\s*["“]?\s*(he|she|his|her)\b', body, re.I)
        local = [(n, start, end) for n, start, end in found
                 if n in characters and sentence.start() <= start < sentence.end()]
        for hit in re.finditer(r"\b(his|her)\s+" + mods + r"(" + PARTS + r")\b|"
                               r"\bwith\s+" + mods + r"(" + PARTS + r")\b|"
                               r"['’]s\s+" + mods + r"(" + PARTS + r")\b", body, re.I):
            at = sentence.start() + hit.start()
            pronoun = (hit[1] or '').lower()
            owner = None
            if hit.group().startswith(("'", '’')):
                owner = next((n for n, _, end in local if end == at), None)
            elif lead and len(previous) == 1 and pronoun:
                owner = previous[0]
            else:
                before = [(n, end) for n, _, end in local if end <= at]
                if before and not ANIMAL_WORDS.search(text[before[-1][1]:at]):
                    owner = before[-1][0]
                    # "with ... paws" describes its subject only after a copula ("Pendo was small, with").
                    if not pronoun and not re.match(r'\s+(?:is|was|has|had)\b', text[before[-1][1]:at], re.I):
                        owner = None
            if owner and pronoun and sexes.get(owner) not in (None, 'unknown', 'male' if pronoun == 'his' else 'female'):
                owner = None
            if owner:
                part = (hit[2] or hit[3] or hit[4]).lower()
                colour = re.match(r'\s+(?:was|is)\s+(?:as\s+)?(black|dark|gold(?:en)?)\b', text[at + len(hit.group()):], re.I)
                owned.setdefault(owner, []).append((colour[1].lower() + ' ' if colour else '') + part)
        if local:
            previous = list(dict.fromkeys(n for n, _, _ in local))
        elif not lead:
            previous = []
    return owned


def _sex_cue(cue):
    return ('female' if re.search(r'\b(she|her|female|mother|queen|lioness|tigress)\b', cue) else
            'male' if re.search(r'\b(he|his|male|father|king)\b', cue) else 'unknown')


def _detect_cast(script_beats):
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
    possessives = _owned_possessives(text, found)
    cast = []
    evidence = {}
    named_contexts = []
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
            # "Pendo, their only cub" introduces an animal through a young-animal noun.
            kin = re.match(r',\s+(?:the|his|her|their|our|my)\s+[^,.]+', after, re.I)
            kin = kin if kin and YOUNG_RE.search(kin.group()) else None
            # "Mara the lioness", "Moss, the old tortoise,", "Pip the cub": a species or young-animal noun right after
            # the name introduces it as the comma form does.
            titled = re.match(r",?\s+the\s+(?:[a-z-]+\s+){0,2}[a-z-]+\b(?!['’])", after)
            titled = titled if titled and (SPECIES_RE.search(titled.group()) or YOUNG_RE.search(titled.group())) \
                else None
            location = re.search(r'\b(?:in|at|across|from|near|of)\s+(?:the\s+)?(?:[a-z]+\s+){0,2}$', before, re.I)
            subject = re.match(r"\s+(?:(?:was|is|did|would|had)\s+)?(?:" + '|'.join(ACTION_CUES.values()) +
                               r"|watch\w*|lived|loved|returned|guarded)\b", after, re.I)
            # "Each point" is a determiner and noun, not a named actor pointing.
            # Explicit introductions still admit a character actually named Each.
            determiner_subject = name == 'Each' and re.match(r'\s+point\b', after, re.I)
            # Capitalization alone (places, headings, plural common nouns) is not a name cue.
            named |= bool(noun or kin or titled or (introduced and not location and SPECIES_RE.search(introduced.group())) or
                          any(w in TITLES for w in text[start:end].split()) or
                          (subject and not determiner_subject and not name.endswith('s') and not SPECIES_RE.fullmatch(name)) or
                          re.search(r'\b(?:mother|father|sister|brother),\s*$', before, re.I) or
                          re.search(r'\b(?:hug\w*|met|saw|named|called)\s*$', before, re.I) or
                          # addressed: "Happy 25th Jo, ...", "Dear Sam", "Jo, you're still ..."
                          re.search(r'\b(?:happy\s+[\w-]+|hey|hi|hello|dear|congrat\w*|thank\s+you|love\s+you)[,!\s]*$',
                                    before, re.I) or re.match(r",[^.!?]*\byou(?:'re|r)?\b", after, re.I))
            # Only explicit noun phrases and subject-owned attributes supply traits. Mere
            # proximity (especially an object followed by someone else's description) cannot.
            local = before[noun.start():] if noun else ''
            if introduced and not location and SPECIES_RE.search(introduced.group()):
                local += '; ' + introduced.group()
            if kin:
                local += '; ' + kin.group()
            if titled:
                local += '; ' + titled.group()
            group = re.match(r'\s+and the other (lionesses|tigresses|lions|tigers)\b', after, re.I)
            if group:
                local += '; ' + {'lionesses': 'lioness', 'tigresses': 'tigress',
                                'lions': 'lion', 'tigers': 'tiger'}[group[1].lower()]
            tail = after[introduced.end():].lstrip(',') if introduced else after
            attribute = re.match(r'\s+(?:is|was|has|had)\s+(.+)', tail, re.I)
            if attribute and not re.search(r'\b(?:and|or)\s+(?:the\s+)?$', before, re.I):
                owned = re.split(r"\b(?:of|behind|beside|against|with|when|while)\b|"
                                 r"\b(?:his|her|their)\s+(?:mother|father|sister|brother)\b",
                                 attribute[1], maxsplit=1, flags=re.I)[0]
                local += '; ' + owned
            title = next((w for w in text[start:end].split() if w in TITLES), '')
            contexts.append(title + '; ' + local)
        if named:
            named_contexts.append((name, contexts))
    sexes = {name: _sex_cue(_positive_cue('; '.join(contexts + possessives.get(name, [])).lower()))
             for name, contexts in named_contexts}
    parts = _animal_parts(text, found, set(sexes), sexes)
    # A species noun names the animal; otherwise an owned animal cue (mane, paw, cub) picks a
    # specific species or joins the story's own animals. Only cue-free names default to human.
    chosen = {}
    for name, contexts in named_contexts:
        description = next((_positive_cue(s.lower()) for s in contexts if SPECIES_RE.search(_positive_cue(s.lower()))), '')
        cue = _positive_cue('; '.join(contexts + possessives.get(name, []) + parts.get(name, [])).lower())
        hit = SPECIES_RE.search(description)
        if hit:
            chosen[name] = hit.group().lower()
        elif YOUNG_RE.search(cue) or name in parts or re.search(r'\b(?:' + PARTS + r')\b', cue):
            chosen[name] = next((sp for cue_re, sp in CUE_SPECIES if re.search(r'\b(?:' + cue_re + r')\b', cue)), None)
    base = {'lioness': 'lion', 'tigress': 'tiger'}
    kinds = [base.get(sp, sp) for sp in chosen.values() if sp and sp not in HUMAN_SPECIES]
    story_animal = max(kinds, key=kinds.count) if kinds else 'lion'
    for name in [n for n, sp in chosen.items() if sp is None]:
        # A cub or pawed character belongs with the animal named just before it.
        first = next(start for n, start, _ in found if n == name)
        nearest = [chosen[n] for n, start, _ in found if start < first and chosen.get(n) and chosen[n] not in HUMAN_SPECIES]
        chosen[name] = base.get(nearest[-1], nearest[-1]) if nearest else story_animal
    for name, contexts in named_contexts:
        description = next((_positive_cue(s.lower()) for s in contexts if SPECIES_RE.search(_positive_cue(s.lower()))), '')
        raw_cue = '; '.join(contexts + possessives.get(name, []) + parts.get(name, [])).lower()
        cue = _positive_cue(raw_cue)
        species_hit = SPECIES_RE.search(description)
        species = chosen.get(name, 'human')
        if not species_hit and sexes[name] == 'female':
            species = {'lion': 'lioness', 'tiger': 'tigress'}.get(species, species)
        kind, family = SPECIES[species]
        age = ('baby' if re.search(r'\b(cub|baby|puppy|kitten|hatchling)\b', cue) else
               'young' if species in ('boy', 'girl') or re.search(r'\b(young|child|teen)\b', cue) else
               'old' if re.search(r'\b(old|elderly|ancient)\b', cue) else 'adult')
        present, absent = _mark_evidence(raw_cue)
        marks = [mark for mark, _ in MARK_CUES if mark in present]
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
        traits = {}
        if species_hit:
            traits.update(species=species, kind=kind, family=family)
        if re.search(r'\b(cub|baby|puppy|kitten|hatchling|young|child|teen|old|elderly|ancient|adult)\b', cue) or species in ('boy', 'girl'):
            traits['age'] = age
        if sex != 'unknown':
            traits['sex'] = sex
        if re.search(r'\bmassive\b', cue):
            traits['size'] = 1.4
        evidence[name_key(name)] = {'traits': traits, 'marks': present, 'absent_marks': absent,
                                    'baby_size': .55 if traits.get('age') == 'baby' else None}
    return cast, evidence


def detect_cast(script_beats) -> list[dict]:
    return _detect_cast(script_beats)[0]


def cast_evidence(script_beats) -> dict:
    """Explicit actor-owned cues only; creative defaults are not source evidence."""
    return _detect_cast(script_beats)[1]


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

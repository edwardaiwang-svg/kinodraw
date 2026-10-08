"""Pick a preset creature doodle (animals and people in poses) for a story beat.

``best_preset('lion', pose='roar', marks=('mane_black', 'scar_nose'))`` returns a doodle id such as
``cr_lion_male_adult_blackmane_scar_roar_r``. When the exact picture does not exist it falls back to the
nearest pose, then the other facing, then the nearest member of the same animal family; an animal never
falls back to a person, and an unknown animal returns None rather than something unrelated.
The presets come from ``scripts/gen_creatures.py`` (``assets/doodles/creatures``, ``tags/creatures.json``).
"""
from __future__ import annotations

from functools import lru_cache

from . import catalog

FACINGS = {'right': 'r', 'r': 'r', 'left': 'l', 'l': 'l', 'front': 'f', 'f': 'f', None: 'r', '': 'r'}

# requested pose word -> canonical pose
POSE_WORDS = {
    'stand': 'stand', 'standing': 'stand', 'idle': 'stand', 'still': 'stand', 'wait': 'stand', 'watch': 'stand',
    'walk': 'walk1', 'walking': 'walk1', 'walk1': 'walk1', 'walk2': 'walk2', 'step': 'walk1', 'wander': 'walk1',
    'run': 'run', 'running': 'run', 'gallop': 'run', 'chase': 'run', 'charge': 'run', 'flee': 'run', 'hurry': 'run',
    'sit': 'sit', 'sitting': 'sit', 'perch': 'sit', 'rest': 'lie', 'lie': 'lie', 'lying': 'lie', 'lie_down': 'lie',
    'sleep': 'sleep', 'sleeping': 'sleep', 'nap': 'sleep', 'asleep': 'sleep',
    'roar': 'roar', 'roaring': 'roar', 'growl': 'roar', 'bark': 'roar', 'howl': 'roar', 'call': 'roar',
    'croak': 'roar', 'sing': 'roar', 'trumpet': 'roar', 'shout': 'shout', 'shouting': 'shout', 'yell': 'shout',
    'cry_out': 'shout', 'speak': 'shout', 'talk': 'shout',
    'look_up': 'look_up', 'look up': 'look_up', 'looking_up': 'look_up', 'gaze': 'look_up',
    'scared': 'scared', 'afraid': 'scared', 'crouch': 'scared', 'cower': 'scared', 'frightened': 'scared',
    'fear': 'scared', 'hide': 'scared',
    'carry': 'carry', 'carrying': 'carry', 'hold': 'carry', 'holding': 'carry',
    'fly': 'fly', 'flying': 'fly', 'fly2': 'fly2', 'swim': 'swim1', 'swimming': 'swim1', 'swim1': 'swim1',
    'swim2': 'swim2', 'jump': 'jump', 'jumping': 'jump', 'leap': 'jump', 'hop': 'jump', 'wave': 'wave', 'waving': 'wave',
    'face': 'face_neutral', 'closeup': 'face_neutral', 'close_up': 'face_neutral', 'eyes': 'face_neutral',
}
NEAREST = {
    'stand': ('stand', 'sit', 'walk1', 'swim1', 'fly'),
    'walk1': ('walk1', 'walk2', 'run', 'swim1', 'stand'),
    'walk2': ('walk2', 'walk1', 'run', 'swim2', 'stand'),
    'run': ('run', 'jump', 'walk1', 'fly', 'swim1', 'stand'),
    'jump': ('jump', 'run', 'fly', 'walk1', 'stand'),
    'fly': ('fly', 'fly2', 'jump', 'run', 'stand'),
    'fly2': ('fly2', 'fly', 'jump', 'run', 'stand'),
    'swim1': ('swim1', 'swim2', 'walk1', 'stand'),
    'swim2': ('swim2', 'swim1', 'walk2', 'stand'),
    'sit': ('sit', 'lie', 'stand'),
    'lie': ('lie', 'sleep', 'sit', 'stand'),
    'sleep': ('sleep', 'lie', 'sit', 'stand'),
    'roar': ('roar', 'shout', 'stand'),
    'shout': ('shout', 'roar', 'stand'),
    'look_up': ('look_up', 'stand'),
    'scared': ('scared', 'lie', 'stand'),
    'carry': ('carry', 'stand'),
    'wave': ('wave', 'shout', 'stand'),
}
EXPRESSIONS = ('neutral', 'scared', 'determined', 'sad', 'happy')
EXPRESSION_WORDS = {'wide': 'scared', 'afraid': 'scared', 'fear': 'scared', 'angry': 'determined',
                    'fierce': 'determined', 'brave': 'determined', 'calm': 'neutral', 'joy': 'happy', 'smile': 'happy',
                    'cry': 'sad', 'crying': 'sad', 'unhappy': 'sad'}
AGES = {'adult': 'adult', 'grown': 'adult', 'young': 'young', 'baby': 'young', 'cub': 'young', 'calf': 'young',
        'kid': 'young', 'pup': 'young', 'puppy': 'young', 'kitten': 'young', 'chick': 'young', 'foal': 'young',
        'juvenile': 'young', 'child': 'child', 'boy': 'child', 'girl': 'child', 'old': 'elder', 'elder': 'elder',
        'elderly': 'elder', 'senior': 'elder', None: 'adult', '': 'adult'}
# species words -> (species, sex, age) defaults
SPECIES_WORDS = {
    'lioness': ('lion', 'female', None), 'lion cub': ('lion', None, 'young'), 'tigress': ('tiger', 'female', None),
    'puppy': ('dog', None, 'young'), 'kitten': ('cat', None, 'young'), 'calf': ('cow', None, 'young'),
    'chick': ('chicken', None, 'young'), 'foal': ('horse', None, 'young'), 'lamb': ('sheep', None, 'young'),
    'bunny': ('rabbit', None, None), 'hen': ('chicken', 'female', None), 'rooster': ('chicken', 'male', None),
    'chimp': ('chimpanzee', None, None), 'ape': ('gorilla', None, None), 'silverback': ('gorilla', None, None),
    'pony': ('horse', None, None), 'stallion': ('horse', 'male', None), 'mare': ('horse', 'female', None),
    'doe': ('deer', 'female', None), 'stag': ('deer', 'male', None), 'buck': ('deer', 'male', None),
    'fawn': ('deer', None, 'young'), 'duckling': ('duck', None, 'young'), 'cockerel': ('chicken', 'male', None),
    'drake': ('duck', 'male', None), 'piglet': ('pig', None, 'young'), 'joey': ('rabbit', None, 'young'),
    'man': ('human', 'male', 'adult'), 'woman': ('human', 'female', 'adult'), 'boy': ('human', 'male', 'child'),
    'girl': ('human', 'female', 'child'), 'child': ('human', None, 'child'), 'kid': ('human', None, 'child'),
    'person': ('human', None, 'adult'), 'king': ('human', 'male', 'adult'), 'queen': ('human', 'female', 'adult'),
    'grandma': ('human', 'female', 'elder'), 'grandpa': ('human', 'male', 'elder'),
    'grandmother': ('human', 'female', 'elder'), 'grandfather': ('human', 'male', 'elder'),
    'teacher': ('human', None, 'adult'), 'villager': ('human', None, 'adult'), 'explorer': ('human', None, 'adult'),
    'princess': ('human', 'female', 'child'), 'farmer': ('human', None, 'adult'),
    'hoglet': ('hedgehog', None, 'young'),
}
# words that name one drawn look of a species
VARIANT_WORDS = {
    'panther': ('leopard', 'black'), 'black panther': ('leopard', 'black'), 'black leopard': ('leopard', 'black'),
    'white tiger': ('tiger', 'white'), 'panda': ('bear', 'panda'), 'giant panda': ('bear', 'panda'),
    'panda bear': ('bear', 'panda'), 'polar bear': ('bear', 'polar'), 'black bear': ('bear', 'black'),
    'grizzly': ('bear', ''), 'brown bear': ('bear', ''), 'dalmatian': ('dog', 'dalmatian'), 'husky': ('dog', 'husky'),
    'beagle': ('dog', 'beagle'), 'golden retriever': ('dog', 'retriever'), 'retriever': ('dog', 'retriever'),
    'labrador': ('dog', 'black'), 'black dog': ('dog', 'black'), 'black cat': ('cat', 'black'),
    'white cat': ('cat', 'white'), 'grey cat': ('cat', 'grey'), 'gray cat': ('cat', 'grey'),
    'tabby': ('cat', 'grey'), 'ginger cat': ('cat', ''), 'black horse': ('horse', 'black'),
    'white horse': ('horse', 'white'), 'chestnut horse': ('horse', 'chestnut'), 'brown cow': ('cow', 'brown'),
    'white rabbit': ('rabbit', 'white'), 'brown rabbit': ('rabbit', 'brown'), 'red ant': ('ant', 'red'),
    'fire ant': ('ant', 'red'), 'black ant': ('ant', 'black'), 'tree frog': ('frog', 'tree'),
    'robin': ('songbird', 'robin'), 'sparrow': ('songbird', 'sparrow'), 'bluebird': ('songbird', 'blue'),
    'cardinal': ('songbird', 'cardinal'), 'snowy owl': ('owl', 'snowy'), 'white owl': ('owl', 'snowy'),
    'macaw': ('parrot', 'macaw'), 'green parrot': ('parrot', 'green'), 'parakeet': ('parrot', 'green'),
    'white duck': ('duck', 'white'), 'white hen': ('chicken', 'white'), 'ladybug': ('beetle', 'ladybug'),
    'ladybird': ('beetle', 'ladybug'), 'monarch': ('butterfly', 'monarch'), 'blue butterfly': ('butterfly', 'blue'),
    'honey bee': ('bee', 'honey'), 'bumblebee': ('bee', 'honey'), 'goldfish': ('fish', 'goldfish'),
    'clownfish': ('fish', 'clown'), 'clown fish': ('fish', 'clown'), 'blue tang': ('fish', 'tang'),
    'python': ('snake', 'python'), 'green snake': ('snake', 'green'),
}
HUMAN_ROLES = {'king': 'king', 'queen': 'queen', 'teacher': 'teacher', 'villager': 'villager', 'explorer': 'explorer',
               'princess': 'princess', 'farmer': 'villager'}
# skin-tone words a caller may pass in ``marks`` -> the tone suffix of a person's variant
TONE_WORDS = {'light': 'light', 'fair': 'light', 'light_skin': 'light', 'tan': 'tan', 'medium': 'tan',
              'tan_skin': 'tan', 'medium_skin': 'tan', 'brown': 'brown', 'dark': 'brown', 'brown_skin': 'brown',
              'dark_skin': 'brown'}
# animals we may not have, mapped to their closest drawn relative (same family, never a person)
RELATED = {
    'panther': 'leopard', 'jaguar': 'leopard', 'puma': 'lion', 'cougar': 'lion', 'lynx': 'cat', 'bobcat': 'cat',
    'jackal': 'fox', 'coyote': 'wolf', 'hound': 'dog', 'donkey': 'horse', 'mule': 'horse', 'buffalo': 'cow',
    'bison': 'cow', 'ox': 'cow', 'bull': 'cow', 'yak': 'cow', 'gazelle': 'antelope', 'impala': 'antelope',
    'moose': 'deer', 'elk': 'deer', 'reindeer': 'deer', 'rat': 'mouse', 'hamster': 'mouse', 'squirrel': 'mouse',
    'hare': 'rabbit', 'baboon': 'monkey', 'gibbon': 'monkey', 'lemur': 'monkey',
    'orangutan': 'chimpanzee', 'boar': 'pig', 'warthog': 'pig', 'ram': 'sheep', 'toad': 'frog',
    'crow': 'songbird', 'sparrow': 'songbird', 'robin': 'songbird', 'bird': 'songbird', 'finch': 'songbird',
    'hawk': 'eagle', 'falcon': 'eagle', 'vulture': 'eagle', 'goose': 'duck', 'swan': 'duck', 'hen': 'chicken',
    'macaw': 'parrot', 'stork': 'flamingo', 'heron': 'flamingo', 'alligator': 'crocodile', 'lizard': 'crocodile',
    'terrapin': 'turtle', 'python': 'snake', 'cobra': 'snake', 'serpent': 'snake', 'wasp': 'bee', 'hornet': 'bee',
    'ladybug': 'beetle', 'ladybird': 'beetle', 'moth': 'butterfly', 'termite': 'ant', 'goldfish': 'fish',
    'clownfish': 'fish', 'tuna': 'fish', 'salmon': 'fish', 'trout': 'fish', 'pup': 'dog', 'kitty': 'cat',
    'goat kid': 'goat', 'puppy': 'dog', 'kitten': 'cat',
    # insects and other small crawlers: the nearest drawn bug (a light-bug is a firefly), never an unrelated icon
    'lightning bug': 'firefly', 'glowworm': 'firefly', 'glow worm': 'firefly', 'glow bug': 'firefly',
    'bug': 'beetle', 'insect': 'beetle', 'cricket': 'beetle', 'grasshopper': 'beetle', 'locust': 'beetle',
    'katydid': 'beetle', 'cockroach': 'beetle', 'roach': 'beetle', 'weevil': 'beetle', 'scarab': 'beetle',
    'stink bug': 'beetle', 'fly': 'bee', 'housefly': 'bee', 'mosquito': 'bee', 'gnat': 'bee', 'midge': 'bee',
    'dragonfly': 'bee', 'damselfly': 'bee', 'cicada': 'bee', 'flea': 'ant', 'aphid': 'ant', 'louse': 'ant',
    'slug': 'snail', 'sea snail': 'snail',
}

# family of every species the generator knows, so a species without pictures still finds a relative
FAMILY_OF = {
    **dict.fromkeys(('lion', 'tiger', 'leopard', 'cheetah', 'cat'), 'big_cat'),
    **dict.fromkeys(('dog', 'wolf', 'fox'), 'canine'), 'hyena': 'hyena', 'bear': 'bear',
    **dict.fromkeys(('gorilla', 'chimpanzee', 'monkey'), 'primate'), 'elephant': 'elephant',
    **dict.fromkeys(('giraffe', 'zebra', 'horse', 'deer', 'antelope', 'cow', 'pig', 'sheep', 'goat'), 'hoofed'),
    **dict.fromkeys(('rabbit', 'mouse', 'porcupine', 'hedgehog'), 'rodent'),
    **dict.fromkeys(('songbird', 'owl', 'eagle', 'parrot', 'chicken', 'duck', 'penguin', 'flamingo'), 'bird'),
    'fish': 'fish', 'frog': 'amphibian', **dict.fromkeys(('turtle', 'tortoise', 'snake', 'crocodile'), 'reptile'),
    **dict.fromkeys(('ant', 'bee', 'butterfly', 'beetle', 'firefly'), 'insect'), 'snail': 'mollusc', 'human': 'human',
}


def _norm(word) -> str:
    return str(word or '').strip().lower().replace('-', ' ').replace('_', ' ')


@lru_cache(maxsize=1)
def presets() -> dict:
    """id -> creature metadata (species, family, sex, age, variant, marks, pose, facing, anchors, ...)."""
    return {i: {**e['creature'], 'category': e.get('category')} for i, e in catalog().items()
            if e.get('set') == 'creatures' and 'creature' in e}


@lru_cache(maxsize=1)
def _index():
    by_species, families = {}, {}
    for pid, m in presets().items():
        by_species.setdefault(m['species'], []).append(pid)
        families.setdefault(m['family'], set()).add(m['species'])
    return by_species, families


def species_list() -> list[str]:
    return sorted(_index()[0])


def anchor(preset_id: str, name: str = 'carry'):
    """Pixel point (in the preset's own viewBox) where a smaller doodle attaches, or None."""
    m = presets().get(preset_id) or {}
    point = (m.get('anchors') or {}).get(name)
    return tuple(point) if point else None


def _canonical_pose(pose) -> str:
    p = _norm(pose).replace(' ', '_') or 'stand'
    if p.startswith('face'):
        expr = p[5:] if p.startswith('face_') else 'neutral'
        return 'face_' + EXPRESSION_WORDS.get(expr, expr if expr in EXPRESSIONS else 'neutral')
    return POSE_WORDS.get(p, POSE_WORDS.get(p.replace('_', ' '), p))


def _resolve_species(species, sex, age):
    word = _norm(species)
    by_species, families = _index()
    role = None
    if word in VARIANT_WORDS:
        sp, look = VARIANT_WORDS[word]
        return sp, sex, age, look
    if word in SPECIES_WORDS:
        sp, s, a = SPECIES_WORDS[word]
        role = HUMAN_ROLES.get(word)
        return sp, sex or s, age or a, role
    if word.endswith('ies') and word[:-3] + 'y' in by_species:      # "fireflies"
        word = word[:-3] + 'y'
    elif word.endswith('s') and word[:-1] in by_species:            # "frogs"
        word = word[:-1]
    if word in by_species:
        return word, sex, age, role
    if word in RELATED:
        return RELATED[word], sex, age, role
    if word in families:                       # a family name ("big_cat", "bird") -> its first species
        return sorted(families[word])[0], sex, age, role
    words = word.split(' ')
    if len(words) > 1 and words[0] == 'baby':                 # "baby elephant"
        return _resolve_species(' '.join(words[1:]), sex, age or 'young')
    if len(words) > 1 and words[-1] in ('cub', 'calf', 'baby', 'pup', 'kit'):   # "bear cub"
        return _resolve_species(' '.join(words[:-1]), sex, age or 'young')
    last = words[-1]
    if last != word:
        return _resolve_species(last, sex, age)
    return None, sex, age, role


def drawn_species(word) -> str | None:
    """The drawn species a species word names: itself, its singular ("frogs"), a look of it ("panda") or its
    nearest drawn relative ("lightning bug" -> firefly); None when nothing of its kind is drawn."""
    return _resolve_species(word, None, None)[0]


def best_preset(species: str, age: str | None = None, sex: str | None = None, pose: str = 'stand',
                facing: str = 'right', marks=(), variant: str | None = None, expression: str | None = None) -> str | None:
    """The best preset id for this character, or None when no picture of this kind of creature exists.

    ``age`` defaults to adult unless the species word implies one ("cub", "puppy", "girl").

    Fallback order: exact -> nearest pose (NEAREST) -> other facing -> other age -> sibling species of the
    same family. Animals never resolve to people, people never resolve to animals.
    """
    sp, sex, age, role = _resolve_species(species, sex, age)
    if sp is None:
        return None
    if sp != 'human' and role is not None:      # the word named one look of the species ("panda")
        variant, role = (variant if variant is not None else role), None
    by_species, families = _index()
    want_pose = _canonical_pose(pose if not expression else f'face_{expression}')
    want_face = want_pose.startswith('face_')
    want_facing = FACINGS.get(_norm(facing) or None, 'r')
    want_age = AGES.get(_norm(age) or None, _norm(age))
    want_sex = _norm(sex) or None
    want_sex = {'m': 'male', 'f': 'female', 'unknown': None, 'any': None}.get(want_sex, want_sex)
    marks = {_norm(m).replace(' ', '_') for m in (marks or ())}
    human = sp == 'human'
    candidates = list(by_species.get(sp, []))
    if not candidates:
        fam = FAMILY_OF.get(sp) or next((f for f, members in families.items() if sp in members), None)
        candidates = [p for s in sorted(families.get(fam, ())) for p in by_species[s]]
    if not candidates:
        return None
    meta = presets()

    def character_score(m):
        score = 0.0
        if m['species'] != sp:
            score -= 50
        age_m = m['age']
        if age_m == want_age:
            score += 20
        elif {age_m, want_age} <= {'young', 'child'}:
            score += 15
        elif age_m == 'adult':
            score += 8
        if want_sex and m['sex'] == want_sex:
            score += 10
        elif want_sex and m['sex'] not in ('any', want_sex):
            score -= 6
        elif not want_sex and m['sex'] == 'male' and sp == 'lion':
            score += 1                      # an unspecified lion is the maned one
        got = set(m.get('marks') or ())
        score += 6 * len(marks & got) - 2 * len(got - marks - {'mane_gold'})
        if variant is not None:
            score += 12 if m.get('variant') == variant else 0
        if role:
            score += 9 if role in (m.get('marks') or ()) or role in (m.get('variant') or '') else 0
        elif m.get('variant') in ('', None):
            score += .5
        elif human and got & {'casual', 'villager'}:
            score += 1                      # an unnamed person is an everyday one, not royalty
        if human and (m.get('variant') or '').rsplit('_', 1)[-1] in {TONE_WORDS.get(k) for k in marks}:
            score += 5
        return score

    pose_order = NEAREST.get(want_pose, (want_pose, 'stand')) if not want_face else \
        (want_pose, 'face_neutral', 'stand')
    facing_order = (want_facing, 'r', 'l', 'f') if want_facing != 'f' else ('f', 'r', 'l')

    def score(pid):
        m = meta[pid]
        if (m.get('family') == 'human') != human:
            return None                     # never cross between animals and people
        try:
            p_rank = pose_order.index(m['pose'])
        except ValueError:                  # nothing near: the species' resting picture (a fish has no "stand")
            if m['pose'].startswith('face_') != want_face:
                return None
            p_rank = len(pose_order) + (0 if m['pose'] in ('stand', 'swim1') else 2)
        f_rank = facing_order.index(m['facing']) if m['facing'] in facing_order else 9
        return character_score(m) - 30 * p_rank - 4 * f_rank

    scored = [(s, pid) for pid in candidates if (s := score(pid)) is not None]
    if not scored:
        return None
    return max(scored, key=lambda t: (t[0], t[1]))[1]

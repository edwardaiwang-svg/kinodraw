"""The cast genome: JSON-friendly genes, repair, and an offline text fallback."""
from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import asdict, dataclass, field, replace

KINDS = ('quadruped', 'humanoid', 'blob')
FAMILIES = ('feline', 'canine', 'hyenid', 'human', 'blob')
AGES = ('baby', 'young', 'adult', 'old')
SEXES = ('female', 'male', 'unknown')
MARKS = ('mane_black', 'mane_gold', 'mane_none', 'stripes', 'spots', 'scar_nose', 'scar_eye', 'fluffy')
TEMPERAMENTS = ('calm', 'shy', 'playful', 'bold', 'fierce')


@dataclass(frozen=True)
class Palette:
    body: str = '#DEA544'
    accent: str = '#F9E0A0'
    eye: str = '#795529'


def _color(value, fallback):
    value = str(value)
    return value.upper() if re.fullmatch(r'#[0-9a-fA-F]{6}', value) else fallback


@dataclass(frozen=True)
class Genome:
    kind: str = 'quadruped'
    family: str = 'feline'
    species: str = 'lion'
    age: str = 'adult'
    sex: str = 'unknown'
    size: float = 1.
    palette: Palette = field(default_factory=Palette)
    marks: tuple[str, ...] = ()
    temperament: str = 'calm'
    name: str = ''
    seed: int = 0

    def repair(self) -> Genome:
        species = str(self.species).lower().strip()
        sex = str(self.sex).lower()
        marks = self.marks if isinstance(self.marks, (list, tuple)) else str(self.marks).split()
        marks = set(marks) & set(MARKS)
        if species in ('tigress', 'lioness'):
            species, sex = species.removesuffix('ess'), 'female'
            species = 'tiger' if species == 'tigr' else species
        family = {'lion': 'feline', 'tiger': 'feline', 'cat': 'feline', 'leopard': 'feline',
                  'dog': 'canine', 'wolf': 'canine', 'hyena': 'hyenid', 'human': 'human',
                  'blob': 'blob'}.get(species, self.family)
        family = family if family in FAMILIES else 'feline'
        kind = 'humanoid' if family == 'human' else 'blob' if family == 'blob' else 'quadruped'
        age = self.age if self.age in AGES else 'adult'
        sex = sex if sex in SEXES else 'unknown'
        try:
            size = float(self.size)
        except (ValueError, TypeError):
            size = 1.
        size = round(min(1.6, max(.45, size if math.isfinite(size) else 1.)), 3)
        if species == 'tiger':
            marks.add('stripes')
        if species in ('hyena', 'leopard'):
            marks.add('spots')
        if species != 'lion' or sex != 'male' or age in ('baby', 'young'):
            marks -= {'mane_black', 'mane_gold'}
        elif 'mane_none' in marks:
            marks -= {'mane_black', 'mane_gold'}
        elif 'mane_black' in marks:
            marks.discard('mane_gold')
        else:
            marks.add('mane_gold')
        palette = self.palette
        if isinstance(palette, dict):
            palette = Palette(**{k: palette[k] for k in ('body', 'accent', 'eye') if k in palette})
        if not isinstance(palette, Palette):
            palette = Palette()
        palette = Palette(*(_color(getattr(palette, k), getattr(Palette(), k)) for k in ('body', 'accent', 'eye')))
        temperament = self.temperament if self.temperament in TEMPERAMENTS else 'calm'
        try:
            seed = int(self.seed) & 0xFFFFFFFF
        except (ValueError, TypeError):
            seed = 0
        return replace(self, kind=kind, family=family, species=species or family, age=age, sex=sex, size=size,
                       palette=palette, marks=tuple(sorted(marks)), temperament=temperament,
                       name=str(self.name), seed=seed)

    @classmethod
    def from_dict(cls, value: dict) -> Genome:
        return cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__}).repair()

    def to_dict(self) -> dict:
        value = asdict(self.repair())
        value['marks'] = list(value['marks'])
        return value

    def stream(self, label: str) -> random.Random:
        # Palette is deliberately absent: recolouring cannot change anatomy or motion.
        key = f'{self.seed}|{self.name}|{self.species}|{self.age}|{self.sex}|{label}'
        return random.Random(int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), 'big'))


def schema() -> dict:
    """The gene portion of a Director cast entry; integration can embed this unchanged."""
    return {'type': 'object', 'additionalProperties': False,
            'properties': {'kind': {'type': 'string', 'enum': list(KINDS)},
                           'family': {'type': 'string', 'enum': list(FAMILIES)},
                           'species': {'type': 'string'}, 'age': {'type': 'string', 'enum': list(AGES)},
                           'sex': {'type': 'string', 'enum': list(SEXES)},
                           'size': {'type': 'number', 'minimum': .45, 'maximum': 1.6},
                           'palette': {'type': 'object', 'additionalProperties': False,
                                       'properties': {k: {'type': 'string', 'pattern': '^#[0-9a-fA-F]{6}$'}
                                                      for k in ('body', 'accent', 'eye')},
                                       'required': ['body', 'accent', 'eye']},
                           'marks': {'type': 'array', 'items': {'type': 'string', 'enum': list(MARKS)}},
                           'temperament': {'type': 'string', 'enum': list(TEMPERAMENTS)},
                           'name': {'type': 'string'}, 'seed': {'type': 'integer'}},
            'required': ['kind', 'family', 'species', 'age', 'sex', 'size', 'palette', 'marks', 'temperament']}


def from_text_hint(name: str, words) -> Genome:
    text = (name + ' ' + (words if isinstance(words, str) else ' '.join(words))).lower()
    species, family, sex = 'lion', 'feline', 'unknown'
    for aliases, animal, group in ((('human', 'person', 'man', 'woman', 'boy', 'girl'), 'human', 'human'),
                                   (('hyena',), 'hyena', 'hyenid'), (('wolf', 'dog', 'canine'), 'dog', 'canine'),
                                   (('tiger', 'tigress'), 'tiger', 'feline'), (('leopard',), 'leopard', 'feline'),
                                   (('lion', 'lioness'), 'lion', 'feline'), (('blob',), 'blob', 'blob')):
        if any(re.search(r'\b' + word + r's?\b', text) for word in aliases):
            species, family = animal, group
            break
    if re.search(r'\b(tigress|lioness|female|mother|woman|girl)\b', text):
        sex = 'female'
    elif re.search(r'\b(male|father|king|man|boy)\b', text):
        sex = 'male'
    age = 'baby' if re.search(r'\b(cub|baby|infant)\b', text) else next((x for x in ('young', 'old') if re.search(r'\b' + x + r'\b', text)), 'adult')
    if family == 'canine' and re.search(r'\bwolf\b', text):
        species = 'wolf'
    marks = set()
    if 'mane' in text and not re.search(r'\b(no|without)\b.*mane', text):
        marks.add('mane_black' if re.search(r'black.*mane|mane.*black', text) else 'mane_gold')
        sex = 'male' if sex == 'unknown' else sex
    if re.search(r'\b(no|without)\b.*mane', text):
        marks.add('mane_none')
    for phrase, mark in (('stripe', 'stripes'), ('spot', 'spots'), ('fluffy', 'fluffy')):
        if phrase in text:
            marks.add(mark)
    if 'scar' in text:
        marks.add('scar_eye' if 'eye' in text else 'scar_nose')
    palette = Palette()
    if species == 'tiger':
        palette = Palette('#E88B32', '#FFE8BD', '#7BA345')
    elif species == 'hyena':
        palette = Palette('#998267', '#DBC5A2', '#C59243')
    elif family == 'canine':
        palette = Palette('#929CA5', '#E1E6E9', '#7B9BAC')
    elif family == 'human':
        palette = Palette('#C89470', '#4E82A0', '#48392D')
    size = 1.4 if 'massive' in text or 'huge' in text else .78 if age == 'baby' else 1.
    temperament = next((x for x in TEMPERAMENTS if x in text), 'calm')
    return Genome(family=family, species=species, age=age, sex=sex, size=size, palette=palette,
                  marks=tuple(marks), temperament=temperament, name=name).repair()

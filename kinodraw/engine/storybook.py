"""Picture-book story scenes: preset doodle characters on the whiteboard paper.

Story characters are full-body preset doodles from the picture library, never the procedural creature rig or a
human figure standing in for an animal. Library doodles keep their own colours.

Each scene span is cut into shots, one per narrated sentence, timed by the narration's character times. A shot stages
who the sentence puts on stage (named, pronoun or kin references), in poses read from its verbs, with the animals
and setting it names. Special shots: a parent's roar lesson seen from the cub's point of view, a push into a
character's eyes when the line is about them, and a carrier holding the smaller doodle at its carry anchor.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache

import numpy as np
import resvg_py
from defusedxml.ElementTree import fromstring
from PIL import Image, ImageDraw, ImageFont

from .. import library
from ..speakers import attribute
from ..speech import person_sex
from ..speech import drawn
from . import acting, ink, people, sets, shots as planned
from ..director.v3.staging import tie
from ..director.v3.story import SKY_IDS, Reader, story_picture, titled
from .creatures.actions import Action, action_pose

ROAR_SECONDS = 2.4
# Page changes never ghost two pictures: a new set arrives behind a short slanted wipe
# (Claude Fables' style change: eight frames, cubic out); a dissolve is kept only where the same set continues,
# and lasts two frames. The face close-up cuts in on the eyes the camera pushed into.
WIPE = .27
BLEND = .07
WIPE_ANGLE = 20                 # the edge leans like '/', revealing the new page from the left
FACE_CUT = .07
GROUND = .8                      # feet line as a share of the frame height, clear of the caption band
ADULT_HEIGHT = .42               # an adult cast member's height as a share of the frame height
SMALL = {'ant': .06, 'frog': .11, 'bird': .1, 'mouse': .08, 'snake': .12, 'porcupine': .13, 'rabbit': .12,
         'monkey': .17, 'warthog': .15, 'antelope': .22, 'hyena': .2, 'turtle': .1, 'fish': .1, 'owl': .12,
         'parrot': .12, 'fox': .15, 'wolf': .19, 'deer': .24, 'zebra': .26, 'gorilla': .26, 'bear': .27,
         'crocodile': .14, 'elephant': .34, 'giraffe': .4, 'hedgehog': .1, 'tortoise': .13, 'snail': .07,
         'firefly': .06}
ARBOREAL = {'monkey', 'bird', 'parrot', 'owl'}
# Group staging: no head behind another body. A group too wide for the page is drawn
# smaller, as if the camera pulled back; animals bigger than the cast stand a little behind it, smaller ones in
# front of it. HEAD is a head's half height as a share of its figure's height.
SCALES = (1., .88, .77, .67, .58)
GAP = .015
TALK_GAP = .07                  # people in one shot stand a conversation's distance apart
BACK_ROW = .035
FRONT_ROW = 3
HEAD = .16
# Marks the storybook draws on a preset: a crown (the library's) sits on the head, CROWN of the character's height.
MARKS = {'crown'}
CROWN, CROWN_SIZE = 'fl_crown', .15
# Claude Fables' speech bubble: a quoted line of BUBBLE_WORDS or fewer pops up in a hand-drawn bubble by the speaker's
# mouth and types itself at TYPE_CPS characters a second; longer quotes stay in the caption alone.
BUBBLE_WORDS = 12
BUBBLE_POP, BUBBLE_OUT = .25, .15
TYPE_CPS = 30
BUBBLE_FILL, BUBBLE_INK = (255, 254, 248, 255), (27, 27, 27, 255)
# Idle life: a resting figure stands still (J 10/8: "reduce character wobble heavily"), breathes by BREATH of
# its height, and blinks for BLINK seconds (3 frames) every 2.4-3.9 s. The camera is locked on every page: the only
# moves are the push into the eyes a line is about and a roar's shake (J 10/8: no "random camera zooms").
BREATH = .003
# Sleep is motivated motion, not idle wobble: a sleeper's body rises and falls by SLEEP_BREATH of its height every
# SLEEP_CYCLE seconds, and Z marks drift up from the head and fade, a new one every half ZZZ_CYCLE.
SLEEP_BREATH, SLEEP_CYCLE = .022, 3.4
ZZZ_CYCLE, ZZZ_RISE = 2.8, .1
BLINK = .1
TREMBLE, LAUGH = 2.2, 2.4         # seconds a trembling or laughing pose shakes from its word, then it holds still
# Existing full-body library doodles per species until a preset exists. Most Fluent animals face left.
FALLBACK = {
    'lion': 'fl_lion', 'tiger': 'fl_tiger', 'cat': 'fl_cat', 'leopard': 'fl_leopard', 'cheetah': 'fl_leopard',
    'panther': 'fl_black_cat', 'dog': 'fl_dog', 'wolf': 'fl_wolf', 'fox': 'fl_fox', 'jackal': 'fl_fox',
    'hyena': 'fl_dog', 'bear': 'fl_bear', 'horse': 'fl_horse', 'cow': 'fl_cow', 'mouse': 'fl_mouse',
    'rabbit': 'fl_rabbit', 'bird': 'fl_bird', 'owl': 'fl_owl', 'eagle': 'fl_eagle', 'parrot': 'fl_parrot',
    'fish': 'fl_fish', 'dolphin': 'fl_dolphin', 'lizard': 'fl_lizard', 'monkey': 'fl_monkey',
    'gorilla': 'fl_gorilla', 'chimpanzee': 'fl_monkey', 'elephant': 'fl_elephant', 'giraffe': 'fl_giraffe',
    'rhino': 'fl_rhinoceros', 'hippo': 'fl_hippopotamus', 'zebra': 'fl_zebra', 'antelope': 'fl_deer',
    'gazelle': 'fl_deer', 'deer': 'fl_deer', 'goat': 'fl_goat', 'sheep': 'fl_ewe', 'warthog': 'fl_boar',
    'pig': 'fl_pig', 'squirrel': 'fl_chipmunk', 'crocodile': 'fl_crocodile', 'turtle': 'fl_turtle',
    'frog': 'fl_frog', 'penguin': 'fl_penguin', 'ant': 'fl_ant', 'snake': 'fl_snake', 'porcupine': 'fl_hedgehog',
    'hedgehog': 'fl_hedgehog', 'tortoise': 'fl_turtle', 'snail': 'fl_snail', 'firefly': 'fl_bug',
}
NATIVE_RIGHT = {'fl_monkey', 'fl_snake', 'fl_parrot'}
FRONT = {'fl_lion', 'fl_frog', 'fl_owl', 'fl_fox', 'fl_ant'}
FACE_FALLBACK = {'lion': 'fl_lion', 'tiger': 'fl_tiger_face', 'cat': 'fl_cat_face', 'dog': 'fl_dog_face',
                 'fox': 'fl_fox', 'monkey': 'fl_monkey_face', 'cow': 'fl_cow_face', 'mouse': 'fl_mouse_face',
                 'rabbit': 'fl_rabbit_face', 'horse': 'fl_horse_face', 'frog': 'fl_frog', 'owl': 'fl_owl'}
HUMAN = {'human', 'boy', 'girl', 'man', 'woman'}
HUMAN_FIGURE = {'boy': 'fl_boy', 'girl': 'fl_girl', 'man': 'fl_man_standing', 'woman': 'fl_woman_standing'}
# People are the library's people presets (child, adult, elder; stand, walk, run, sit, lie, sleep, wave, shout ...).
# A teenager is an adult preset drawn a little shorter; a baby a child preset drawn small. Heights are shares of an
# adult's. A person keeps one look (outfit, skin tone) for the whole video: the outfit where their age has it, else
# the first their age has (a child's casual clothes).
PERSON_AGE = {'baby': 'child', 'young': 'child', 'child': 'child', 'teen': 'adult', 'adult': 'adult', 'old': 'elder',
              'elder': 'elder', 'middle': 'adult'}
PERSON_HEIGHT = {'baby': .5, 'child': .72, 'teen': .93, 'adult': 1., 'middle': 1., 'elder': .96}
# The age a cast member is drawn at (engine.people draws each in their own look): every band has its own build.
DRAWN_AGE = {'baby': 'child', 'young': 'child', 'child': 'child', 'teen': 'teen', 'adult': 'adult',
             'middle': 'middle', 'old': 'elder', 'elder': 'elder'}
PERSON_SEX = {'boy': 'male', 'man': 'male', 'girl': 'female', 'woman': 'female'}
PERSON_BAND = {'boy': 'child', 'girl': 'child'}
OUTFITS = {'adult': ('villager', 'teacher', 'explorer'), 'child': ('casual', 'explorer'), 'elder': ('villager',)}
ROLE_OUTFITS = ((r'\b(?:teacher|professor|tutor|principal|librarian|counsel+or)\b', 'teacher'),
                (r'\b(?:explorer|hiker|ranger|scout|adventurer)\b', 'explorer'),
                (r'\b(?:farmer|villager|shepherd)\b', 'villager'), (r'\bking\b', 'king'),
                (r'\bqueen\b', 'queen'), (r'\bprincess\b', 'princess'),
                # Work clothes from role words (engine.people draws them).
                (r'\b(?:cook|chef|baker|butcher|barista|waiter|waitress|grocer|shopkeeper|cashier|bartender|'
                 r'(?:cafe|café|diner|bakery|restaurant|shop|store)\s+owner)s?\b', 'apron'),
                (r'\b(?:anchor|anchorman|anchorwoman|newsreader|reporter|correspondent|host|presenter|manager|boss|'
                 r'ceo|executive|banker|lawyer|attorney|mayor|senator|president|businessman|businesswoman|'
                 r'salesman|saleswoman|realtor|agent|director|principal)s?\b', 'suit'),
                (r'\b(?:scientist|chemist|researcher|doctor|physician|surgeon|dentist|pharmacist|vet|veterinarian|'
                 r'lab\s+tech\w*|technician)s?\b', 'labcoat'),
                (r'\b(?:police(?:man|woman)?|officer|cop|sheriff|guard|security|firefighter|fireman|soldier|pilot|'
                 r'nurse|paramedic|conductor|mail\s+carrier|mailman|postman|postwoman|courier|bus\s+driver|'
                 r'driver|captain|sailor|crossing\s+guard)s?\b', 'uniform'),
                (r'\b(?:plumber|mechanic|electrician|builder|carpenter|construction\s+worker|contractor|engineer|'
                 r'janitor|handyman|gardener|landscaper|painter|welder|worker|crew)s?\b', 'worker'))
EVERYDAY = ('villager', 'teacher')     # a grown-up with no role word: a tunic or a dress, or a shirt
TONES = ('light', 'tan', 'brown')
TONE_MARKS = {'light': 'light', 'fair': 'light', 'pale': 'light', 'tan': 'tan', 'olive': 'tan', 'medium': 'tan',
              'brown': 'brown', 'dark': 'brown', 'black': 'brown'}
# What a sitting, lying or sleeping person can rest on when the page shows it, and how high its seat is (a share of
# the support's drawn height above its feet line). Storybook.seat puts them on it; with none they rest on the ground.
SUPPORTS = {'sit': ('sofa', 'couch', 'armchair', 'chair', 'bench', 'stool', 'seat'),
            'lie': ('bed', 'sofa', 'couch', 'hammock', 'bench'), 'sleep': ('bed', 'sofa', 'couch', 'hammock', 'bench')}
SEAT = {'bed': .45, 'hammock': .5, 'stool': .6, 'bench': .45, 'chair': .45, 'armchair': .4, 'sofa': .4, 'couch': .4}
JUNGLE = ('monkey', 'elephant', 'antelope', 'warthog', 'frog', 'bird')
# A creature whose species word names nothing the library draws is drawn as the plan's family's (or kind's) everyday
# animal, never as an unrelated icon.
FAMILY_ANIMAL = {'feline': 'cat', 'canine': 'dog', 'ursine': 'bear', 'equine': 'horse', 'bovine': 'cow',
                 'rodent': 'mouse', 'bird': 'songbird', 'reptile': 'turtle', 'primate': 'monkey'}
KIND_ANIMAL = {'bird': 'songbird', 'fish': 'fish', 'quadruped': 'dog'}


@lru_cache(maxsize=512)
def species_base(species):
    """(species, sex, age) a cast member's species word implies, plural or singular: "lionesses" -> ('lion',
    'female', None), "lion cubs" -> ('lion', None, 'young'), "women" -> ('woman', None, None)."""
    mod = _creatures()
    if mod is None or not hasattr(mod, 'species_word'):
        return species, None, None
    return mod.species_word(species)


# ------------------------------------------------------------------ doodles
def _creatures():
    try:
        from ..library import creatures
    except ImportError:
        return None
    return creatures if hasattr(creatures, 'best_preset') else None


def meta(doodle_id) -> dict:
    """Preset metadata (pose, facing, size, ground_y, anchors) recorded with a creature doodle; {} otherwise."""
    if people.is_person(doodle_id):
        return people.meta(doodle_id)
    entry = library.catalog().get(doodle_id) or {}
    return entry.get('creature') or {}


@lru_cache(maxsize=512)
def preset(species, age='adult', sex=None, pose='stand', facing='r', marks=()):
    """(doodle id, mirror) for a cast member's pose. Presets first; then a full-body library doodle of the same
    species. An animal never resolves to a human figure; a person resolves to a person."""
    base, implied, young = species_base(species)
    sex = implied or (sex if sex in ('male', 'female') else None)
    age = 'young' if young and age in (None, 'adult') else age
    if base in HUMAN:
        chosen = _person(PERSON_BAND.get(base, age), sex or PERSON_SEX.get(base), pose, facing, marks)
        return chosen or HUMAN_FIGURE.get(base, 'fl_person_standing'), False
    chosen = _choose(base, age, sex, pose, facing, marks)
    if chosen:
        return chosen, False
    if pose not in ('stand', 'face'):
        chosen = _choose(base, age, sex, 'stand', facing, marks)
        if chosen:
            return chosen, False
    doodle = _animal_doodle(base) or _animal_doodle(species) or 'fl_paw_prints'
    native = 'r' if doodle in NATIVE_RIGHT else 'f' if doodle in FRONT else 'l'
    return doodle, native not in ('f', facing)


def _animal_doodle(word):
    """The library's own full-body doodle of this animal (FALLBACK, else its Fluent animal of that name: a
    dragon, a kangaroo), or None."""
    word = str(word or '').lower()
    for did in (FALLBACK.get(word), FALLBACK.get(word.split(' ')[-1]), 'fl_' + word.replace(' ', '_'),
                'fl_' + word.split(' ')[-1]):
        entry = library.catalog().get(did) if did else None
        if entry and (did in FALLBACK.values() or entry.get('category') in ('Animals & Nature', 'animals')) \
                and library.resolve(did) is not None:
            return did
    return None


@lru_cache(maxsize=1)
def _wardrobe():
    """(preset age, sex) -> the outfits the people presets draw."""
    mod = _creatures()
    out = {}
    for m in (mod.presets().values() if mod else ()):
        if m['species'] == 'human' and m.get('variant'):
            out.setdefault((m['age'], m['sex']), set()).add(m['variant'].rsplit('_', 1)[0])
    return out


def _person(age, sex, pose, facing, marks):
    """A people preset for this age band, sex and pose in the person's look (``marks`` holds 'outfit:...' and
    'tone:...'), or None without people presets."""
    mod = _creatures()
    if mod is None:
        return None
    look = dict(m.split(':', 1) for m in marks if ':' in str(m))
    want = PERSON_AGE.get(age, 'adult')
    sex = sex if sex in ('male', 'female') else 'female' if look.get('sex') == 'female' else 'male'
    have = _wardrobe().get((want, sex), set())
    outfit = look.get('outfit')
    if outfit not in have:
        outfit = next((o for o in OUTFITS.get(want, ()) if o in have), sorted(have)[0] if have else '')
    tone = look.get('tone', 'tan')
    try:
        did = mod.best_preset('human', age=want, sex=sex, pose='face' if pose == 'face' else pose,
                              facing={'r': 'right', 'l': 'left'}.get(facing, 'front'), variant=f'{outfit}_{tone}',
                              expression='neutral' if pose == 'face' else None)
    except Exception:  # noqa: BLE001 - no people presets: the caller's plain figure
        return None
    if did and 'top' in look:
        # A cast member's own look, drawn at their age (engine.people): the preset only picks the pose.
        info = mod.presets().get(did) or {}
        drawn = DRAWN_AGE.get(age, 'adult')
        role = look.get('role')
        outfit = 'casual' if drawn == 'child' else role or ('casual' if drawn == 'teen' else look.get('everyday', 'villager'))
        elder_woman = drawn == 'elder' and sex == 'female'      # a grey bun and a long dress or skirt
        flags = ''.join(f for f, on in (('g', look.get('glasses') == '1' or drawn == 'elder'),
                                        ('b', look.get('beard') == '1' and sex == 'male' and drawn not in ('child', 'teen')),
                                        ('c', drawn == 'elder' and sex == 'male' and look.get('cane') == '1'),
                                        ('d', sex == 'female' and (look.get('dress') == '1' or elder_woman)
                                         and outfit not in ('suit', 'labcoat', 'uniform', 'worker'))) if on)
        hair = look['elder_hair'] if drawn == 'elder' else people.greying(look['hair']) if drawn == 'middle' else \
            look['hair']
        style = 'bald' if drawn == 'elder' and sex == 'male' and look.get('style') == 'short' else \
            'bun' if elder_woman and look['style'] in ('long', 'ponytail') else look['style']
        key = people.look_key(sex, drawn, outfit, tone if tone in people.SKIN else 'tan', look['top'],
                              look['bottom'], hair, style, look.get('accent', '#C62828'), flags or 'x')
        pid = f"{key}_{info.get('pose', 'stand')}_{info.get('facing', 'r')}"
        if people.entry(pid) is not None:
            return pid
    return did if did and library.resolve(did) is not None else None


def _choose(species, age, sex, pose, facing, marks):
    """The creature preset for this pose (kinodraw.library.creatures), or None when the library has no picture
    of this species: a sibling species (a lion for a tiger) is not this character."""
    mod = _creatures()
    if mod is None:
        return None
    try:
        did = mod.best_preset(species, age=age, sex=sex, pose=pose, facing={'r': 'right', 'l': 'left'}.get(facing, 'front'),
                              marks=marks, expression='determined' if pose == 'face' else None)
    except Exception:  # noqa: BLE001 - an unknown species falls back to the library's own doodle
        return None
    info = mod.presets().get(did) or {}
    if not did or info.get('species') not in (species, mod.drawn_species(species)) or library.resolve(did) is None:
        return None
    return did


@lru_cache(maxsize=64)
def face(species, age='adult', sex=None, marks=()):
    """A head close-up doodle for an eye shot, or None."""
    base, implied, _ = species_base(species)
    if base in HUMAN:
        did = _person(age, sex, 'face', 'f', marks)
        return did if did and meta(did).get('pose', '').startswith('face_') else None
    did = _choose(base, age, implied or sex, 'face', 'f', marks)
    if did and meta(did).get('pose', '').startswith('face_'):
        return did
    did = FACE_FALLBACK.get(base)
    return did if did and library.resolve(did) else None


@lru_cache(maxsize=256)
def _svg(doodle_id):
    raw = sets.svg(doodle_id) or people.svg(doodle_id) or library.resolve(doodle_id).read_text(encoding='utf-8')
    root = fromstring(raw)
    box = root.get('viewBox')
    if box:
        _, _, w, h = (float(v) for v in box.replace(',', ' ').split())
    else:
        w, h = float(root.get('width', 300)), float(root.get('height', 300))
    return raw, w, h


@lru_cache(maxsize=256)
def _shut(doodle_id):
    """The doodle's SVG with its eyes shut, or None when it has no pupil (a dark circle) level with its eye anchor
    (a face preset: on its eye line). Each pupil, with the iris, white and highlight drawn around it, becomes a closed
    lid's curve."""
    raw, _, _ = _svg(doodle_id)
    anchors = meta(doodle_id).get('anchors') or {}
    circles = [(m, float(m['cx']), float(m['cy']), float(m['r'])) for m in re.finditer(
        r'<circle cx="(?P<cx>[-\d.]+)" cy="(?P<cy>[-\d.]+)" r="(?P<r>[-\d.]+)"[^>]*/>', raw)]
    eye, line = anchors.get('eye'), (anchors.get('eyes') or [None, None])[1]
    pupils = [(cx, cy, r) for m, cx, cy, r in circles if 'fill="#1B1B1B"' in m[0] and (
        eye and r <= 14 and abs(cy - eye[1]) < 6 and abs(cx - eye[0]) < 60 or line is not None and abs(cy - line) < 6)]
    if not pupils:
        return None
    cut, lids = set(), {}
    for cx, cy, r in pupils:
        reach = max(c[3] for c in circles if math.dist((c[1], c[2]), (cx, cy)) < 2.5)
        drawn = [c for c in circles if math.dist((c[1], c[2]), (cx, cy)) + c[3] <= reach + 2.5]
        cut |= {c[0].span() for c in drawn}
        lids[min(c[0].start() for c in drawn)] = (
            f'<path d="M{cx - reach:.1f} {cy:.1f}Q{cx:.1f} {cy + .55 * reach:.1f} {cx + reach:.1f} {cy:.1f}" '
            f'fill="none" stroke-width="{max(3., .3 * reach):.1f}"/>')
    out, at = [], 0
    for a, b in sorted(cut):
        out += [raw[at:a], lids.get(a, '')]
        at = b
    return ''.join(out) + raw[at:]


@lru_cache(maxsize=160)
def sprite(doodle_id, height, mirror=False, shut=False):
    """RGBA doodle at an exact pixel height, in its own colours (never recoloured), and its scale; ``shut`` draws it
    with its eyes closed when it can."""
    raw, w, h = _svg(doodle_id)
    raw = (_shut(doodle_id) if shut else None) or raw
    height = max(8, int(height))
    width = max(8, round(w * height / h))
    png = resvg_py.svg_to_bytes(svg_string=raw, width=width, height=height)
    image = Image.open(io.BytesIO(bytes(png))).convert('RGBA')
    if mirror:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return image


@lru_cache(maxsize=160)
def crowned(doodle_id, px, mirror, crown_px, shut=False):
    """The doodle at ``px`` with the crown on its head: centred over the head anchor (a face close-up's eyes), seated
    a little into the top of the head or mane above it, the canvas grown upward when the crown rises above the
    doodle's box. Returns (image, rows added on top)."""
    image = sprite(doodle_id, px, mirror, shut)
    c_left, c_top, c_right, c_bottom = _bbox(CROWN)
    crown = sprite(CROWN, round(crown_px / max(.1, c_bottom - c_top)))       # crown_px is the drawn crown's height
    anchors = meta(doodle_id).get('anchors') or {}
    ax, ay = anchor(doodle_id, 'head' if 'head' in anchors or 'eyes' not in anchors else 'eyes', mirror)
    cx = round(ax * image.width)
    reach = max(1, round((c_right - c_left) * crown.width * .4))
    alpha = np.asarray(image.getchannel('A'))[:round(ay * image.height), max(0, cx - reach):cx + reach + 1] > 128
    tops = [int(np.argmax(column)) for column in alpha.T if column.any()]       # the head or mane under its rim
    top = round(sum(tops) / len(tops)) if tops else round(ay * image.height)
    y = top + round(.3 * crown_px) - round(c_bottom * crown.height)       # its rim sunk into the head or mane
    pad = max(0, -y)
    out = Image.new('RGBA', (image.width, image.height + pad), (0, 0, 0, 0))
    out.alpha_composite(image, (0, pad))
    x = cx - round((c_left + c_right) / 2 * crown.width)
    out.alpha_composite(crown, (min(max(0, x), max(0, image.width - crown.width)), y + pad))
    return out, pad


@lru_cache(maxsize=384)
def _bbox(doodle_id, mirror=False):
    """Alpha bounds as shares of the doodle box (feet = bottom)."""
    image = sprite(doodle_id, 240, mirror)
    box = image.getchannel('A').point(lambda a: 255 if a > 24 else 0).getbbox() or (0, 0, *image.size)
    return box[0] / image.width, box[1] / image.height, box[2] / image.width, box[3] / image.height


def _units(doodle_id):
    """(drawn height, whole box height) in the preset generator's world units, or None for other doodles.
    Every pose of one character shares a scale, so a lying lion stays lion-sized instead of filling the frame."""
    info = meta(doodle_id)
    if not info.get('px_per_unit'):
        return None
    _, _, h = _svg(doodle_id)
    _, top, _, bottom = _bbox(doodle_id)
    return (bottom - top) * h / info['px_per_unit'], h / info['px_per_unit']


def _box(doodle_id, height, reference=None):
    """The doodle's whole box height, as a share of the frame height, when its character is ``height`` tall."""
    own, ref = _units(doodle_id), _units(reference) if reference else None
    if own and ref:
        return height * own[1] / max(.05, ref[0])
    _, top, _, bottom = _bbox(doodle_id)
    return height / max(.05, bottom - top)


def anchor(doodle_id, name, mirror=False):
    """A named point (mouth, head, eye, carry) as shares of the doodle box."""
    info = meta(doodle_id)
    _, w, h = _svg(doodle_id)
    point = (info.get('anchors') or {}).get(name)
    if point:
        x, y = point[0] / w, point[1] / h
        return (1 - x if mirror else x), y
    left, top, right, bottom = _bbox(doodle_id, mirror)
    native = 'r' if doodle_id in NATIVE_RIGHT else 'f' if doodle_id in FRONT else 'l'
    facing_right = (native == 'r') != mirror if native != 'f' else True
    front = right - .14 * (right - left) if facing_right else left + .14 * (right - left)
    head = right - .22 * (right - left) if facing_right else left + .22 * (right - left)
    if native == 'f':
        front = head = (left + right) / 2
    y = {'mouth': .42, 'head': .22, 'eye': .3, 'carry': .4}.get(name, .4)
    return (front if name in ('mouth', 'carry') else head), top + y * (bottom - top)


# ------------------------------------------------------------------ shots
@dataclass
class Figure:
    key: str
    species: str
    age: str = 'adult'
    sex: str | None = None
    marks: tuple = ()
    pose: str = 'stand'
    x: float = .5
    ground: float = GROUND
    height: float = ADULT_HEIGHT
    facing: str = 'r'
    cue: float | None = None          # span-local seconds the pose starts
    before: str | None = None         # the pose shown until then (lying awake before the words say asleep)
    travel: float = 0.                # share of the frame width moved over the shot
    carried: 'Figure | None' = None
    depth: int = 1
    crowd: bool = False
    phase: float = 0.


@dataclass
class Shot:
    start: float
    end: float
    figures: list = field(default_factory=list)
    props: list = field(default_factory=list)        # (doodle, x, ground, height)
    sky: list = field(default_factory=list)          # (doodle, x, y, height)
    eyes: Figure | None = None
    eyes_at: float = 0.
    lesson: bool = False
    title: str | None = None
    atmosphere: str = 'none'
    bubbles: list = field(default_factory=list)
    set: list = field(default_factory=list)          # sets.Piece: the place's set and the things in it, back to front
    place: str | None = None                         # where the page takes place (engine.sets.SETS)
    supports: list = field(default_factory=list)     # sets.Support: where things rest and figures sit or lie
    view: tuple = (.5, .5, 1.)                       # the shot's locked camera (x, y, zoom): its framing
    framing: str = ''                                # a plan shot's type (engine.shots)
    page: dict | None = None                         # a first_person page, map or phone filling the frame
    screen: list = field(default_factory=list)       # (TV piece, what it shows): pictures and cast figures
    keep: list = field(default_factory=list)         # sets.Piece a framing keeps in view (the TV she sleeps before)
    hands: list = field(default_factory=list)        # (piece, skin tone): an off-screen worker's hand on it


@dataclass(eq=False)
class Bubble:
    speaker: str
    text: str
    start: float                      # span-local seconds it pops in and out
    end: float
    times: tuple = ()                 # span-local seconds each character of text is spoken: it types along
    side: str | None = None           # 'l'/'r': a voice heard from off the frame's edge, its speaker not drawn


def _seed(text):
    return (sum(ord(c) * (i + 1) for i, c in enumerate(str(text))) % 997) / 997 * math.tau


class Storybook:
    """Shot lists and frames for a story plan's scenes."""

    def __init__(self, plan, by_id, timeline, size, paper, title=''):
        # Screen boxes (px) of the figures and of the props drawn since the frame began (the caption avoids them).
        self.figure_boxes, self.prop_boxes = [], []
        self.reader = Reader(plan['cast'])
        self.texts = [b['spoken'] for b in by_id.values()]
        self.reader.prime(self.texts)
        self.cast = self.reader.by_id          # the plan's cast and the extra people the story mentions
        # Who says each quoted line: the same attribution the voices follow (speech.quote_speakers).
        self.speakers = attribute(list(by_id.values()), plan)
        self.looks = {}
        for c in plan['cast']:
            if c['id'] in self.cast and self._human(c['id']):
                self._look(c['id'])
        self.by_id, self.tl, self.size = by_id, timeline, size
        self.paper_image = paper
        self.title = title
        self.story = plan['storyboard']['genre'] == 'story'   # a lesson or promo staged here gets no story furniture
        self.first = plan['scenes'][0]['beat_ids'][0] if plan['scenes'] else None
        self.scenes = [s['beat_ids'] for s in plan['scenes']]
        self.facing = {}
        self.at = {}             # where each character stood last: they keep their side
        self._paper = {}
        self._bubbles = {}
        self.stager = sets.Stager(self)
        self.rests = {}          # who sat or lay on which furniture last, and where: they stay there until they move
        self.planned = planned.Shots(self)       # scenes whose plan gives shots are staged from them
        # Every quoted span drawn in a bubble: {beat, start, end (char offsets in the beat's spoken text), speaker,
        # text}. The captions leave these to the bubbles (build/bubbles.json).
        self.bubbled = []
        # Every movement verb the pages read (engine.acting): {beat, char, word, actor, kind, at, shown}, for the
        # content QA's motion findings (build/acts.json).
        self.acted = []

    # ---------------- planning
    def prepare(self, spec, start, end):
        """Shots for one scene span (local seconds), from its beats' sentences and the plan's cast; a scene whose plan
        gives shots is staged from them (engine.shots)."""
        if spec.get('shots'):
            return self._titled(spec, self.planned.prepare(spec, start, end))
        shots = []
        staged = [e['ref'] for e in spec['elements'] if e['kind'] == 'cast' and e['ref'] in self.cast]
        pictures = [e['ref'] for e in spec['elements'] if e['kind'] == 'picture' and story_picture(e['ref'])]
        following = next((self.scenes[i + 1] for i, ids in enumerate(self.scenes[:-1]) if ids == spec['beat_ids']), [])
        scene = self.stager.scene(pictures, ' '.join(self.by_id[b]['spoken'] for b in spec['beat_ids']),
                                  ' '.join(self.by_id[b]['spoken'] for b in following if b in self.by_id))
        talkers = {}
        for a in spec.get('actions') or ():
            if a.get('verb') == 'talk' and a.get('actor') in self.cast:
                talkers.setdefault(a.get('at_beat'), []).append(a['actor'])
        read = [(bid, self.reader.read(bid, self.by_id[bid]['spoken'], self.by_id[bid].get('section'),
                                       talker=(talkers.get(bid) or [None])[0])) for bid in spec['beat_ids']]
        for bid, lines in read:
            for line in lines:
                if line.quotes:
                    line.speaker = self.speakers.of(bid, line.quotes[0][0], line.speaker)
        # The people the plan stages in this scene are on the page: from the first line that involves them, or all
        # along when its lines never do (a mother staged in the room while her son speaks). Animals keep the
        # sentence's own staging.
        involved = {cid for _, lines in read for line in lines for cid in line.present + line.extras}
        joined = [cid for cid in staged if cid not in involved]
        for bid, lines in read:
            timing = self.tl['beats'][bid]
            # Each sentence shows the pictures it names (a set from where it is named on); unnamed ones stay up.
            shares = tie([line.text for line in lines], pictures)
            times = timing['char_times']
            at = lambda char, timing=timing, times=times: (timing['start'] - start +
                                                           (times[min(char, len(times) - 1)] if times else 0.))
            for i, line in enumerate(lines):
                joined += [cid for cid in staged if cid in line.present + line.extras and cid not in joined]
                begin = timing['start'] - start if i == 0 else at(line.start)
                shot = self._shot(line, begin, at, joined, shares[i], spec, scene, bid)
                plan_acts = [a for a in spec.get('actions') or () if a.get('at_beat') == bid]
                if shots and shot.start - shots[-1].start < 1.1 and not (shot.lesson or shot.eyes):
                    acting.direct(self, shots[-1], [(bid, line)], at, plan_acts, bid)
                    # Very short sentences share the previous picture instead of flashing a new one.
                    previous = shots[-1]
                    previous.bubbles += [b for b in shot.bubbles if b.speaker in [g.key for g in previous.figures]]
                    for f in shot.figures:
                        if f.pose != 'stand' and f.cue is not None:
                            match = next((g for g in previous.figures if g.key == f.key), None)
                            if match and match.pose == 'stand':
                                match.pose, match.cue = f.pose, f.cue
                    continue
                acting.direct(self, shot, [(bid, line)], at, plan_acts, bid)
                shots.append(shot)
        if not shots:
            shots.append(Shot(0., end - start))
        for shot, following in zip(shots, shots[1:]):
            shot.end = following.start
        shots[0].start = 0.
        shots[-1].end = end - start
        for shot in shots:
            for b in shot.bubbles:
                b.start, b.end = max(b.start, shot.start), min(b.end, shot.end - .05)
            shot.bubbles = [b for b in shot.bubbles if b.end - b.start >= .6]
        return self._titled(spec, shots)

    def _titled(self, spec, shots):
        """The story's title once, on the first page (a page read from the text or one staged from plan shots)."""
        if spec['beat_ids'][0] == self.first and (self.by_id[self.first].get('kind') == 'title'
                                                   or titled(self.title, self.by_id[self.first]['spoken'])):
            shots[0].title = self.title
            self._clear_title(shots[0])
        return shots

    def _clear_title(self, shot):
        """The sun, moon and stars of a title page hang below its title (_title's lines), never across them; a sky
        seen through a window stays in the window."""
        if any(p.doodle in sets.WINDOWS for p in shot.set) or not shot.sky:
            return
        from . import ink
        w, h = self.size
        size = round(h * .07)
        font = ink.truetype(ink.EN_HAND[0], size, 'story title')
        draw = ImageDraw.Draw(Image.new('RGBA', (8, 8)))
        lines = _wrap(shot.title, font, w * .8, draw)[:2]
        half = max(draw.textlength(line, font=font) for line in lines) / 2 / w + .02
        bottom = .09 + len(lines) * 1.2 * size / h + .02
        sky = []
        for doodle, x, y, height in shot.sky:
            wide = height * h / w / 2
            if y < bottom and abs(x - .5) < half + wide:
                if doodle == 'fl_star':
                    continue                              # a star in the title's way is left out
                y = bottom
            sky.append((doodle, x, y, height))
        shot.sky = sky

    def _cast_figure(self, cid, line=None, **kw):
        c = self.cast[cid]
        if self._human(cid):
            look = self._look(cid)
            age = (getattr(line, 'looks', {}).get(cid) or line.ages.get(cid) if line else None) or \
                self.reader.look_age(cid)
            marks = tuple(m for m in c.get('marks') or () if m in MARKS) + tuple(f'{k}:{v}' for k, v in look.items()
                                                                                 if v)
            return Figure(cid, 'human', age, look['sex'], marks, height=ADULT_HEIGHT * PERSON_HEIGHT.get(age, 1.),
                          phase=_seed(cid), **kw)
        species, age, size = self._species(cid), c['age'], c.get('size', 1.)
        if species_base(c['species'])[2] == 'young' and age in (None, 'adult'):
            age, size = 'baby', min(size, .45)            # "lion cubs": the species at a cub's size
        return Figure(cid, species, age, c['sex'], tuple(c.get('marks') or ()),
                      height=min(.6, ADULT_HEIGHT * max(.45, min(1.4, size))), phase=_seed(cid), **kw)

    def _species(self, cid):
        """The cast member's species word when the library draws its kind, else its family's or kind's everyday
        animal ("cubs" of the cat family: a kitten)."""
        c = self.cast[cid]
        word = c['species']
        mod = _creatures()
        base = species_base(word)[0]
        if mod is None or base in HUMAN or mod.drawn_species(base) or _animal_doodle(base):
            return word
        return FAMILY_ANIMAL.get(c.get('family')) or KIND_ANIMAL.get(c.get('kind')) or word

    def _human(self, cid):
        c = self.cast[cid]
        return c.get('kind') == 'human' or species_base(c['species'])[0] in HUMAN

    def _look(self, cid):
        """A person's look for the whole video, chosen from their name, marks, the role words the story ties to them
        and their id alone: sex (the plan's, the story's pronouns, else from the id), work clothes from a role word
        ("Anchor", "Tom, the plumber": a suit, a cap and overalls), a skin tone (a tone mark, else from the id), and
        clothes and hair colours no other person on the cast wears (engine.people draws them at every age)."""
        if cid in self.looks:
            return self.looks[cid]
        c = self.cast[cid]
        seed = sum((i + 1) * ord(ch) for i, ch in enumerate(cid))
        sex = person_sex(c, cid, self.reader, self.texts)       # the same as their voice's (speech.voice_parts)
        words = f"{c.get('name', '')} {cid} {c['species']}".lower().replace('_', ' ')
        marks = {str(m).lower() for m in c.get('marks') or ()}
        role = next((o for cue, o in ROLE_OUTFITS if re.search(cue, words)), None) or self._story_role(c)
        if role is None and 'crown' in marks:
            role = 'king' if sex == 'male' else 'queen'
        tone = next((TONE_MARKS[m] for m in marks if m in TONE_MARKS), None)
        outfits = [role] if role in OUTFITS['adult'] + ('king', 'queen', 'princess') else list(OUTFITS['adult'])
        tones = [tone] if tone else [TONES[(seed + i) % 3] for i in range(3)]
        taken = {(l['outfit'], l['tone']) for l in self.looks.values() if l['sex'] == sex}
        options = [(o, t) for t in tones for o in outfits]
        chosen = next((o for o in options if o not in taken), options[0])
        # Colours: the role's own (a suit's dark cloth) else the everyday list, never a top another person wears.
        used_tops = {l['top'] for l in self.looks.values()}
        used_hair = {(l['hair'], l['style']) for l in self.looks.values() if l['sex'] == sex}
        prefer = people.ROLE_TOPS.get(role or '', ())
        tops = [t for t in prefer if t not in used_tops] or \
            [people.TOPS[(seed + i) % len(people.TOPS)] for i in range(len(people.TOPS))]
        top = next((t for t in tops if t not in used_tops), tops[0])
        styles = ('long', 'bun', 'ponytail', 'curly') if sex == 'female' else ('short', 'curly')
        hairs = [(people.HAIRS[(seed + i) % len(people.HAIRS)], styles[(seed // 7 + j) % len(styles)])
                 for j in range(len(styles)) for i in range(len(people.HAIRS))]
        hair, style = next((h for h in hairs if h not in used_hair), hairs[0])
        everyday = EVERYDAY[seed % len(EVERYDAY)] if role not in EVERYDAY else role
        self.looks[cid] = {
            'sex': sex, 'outfit': chosen[0], 'tone': chosen[1], 'role': role if role and role not in EVERYDAY else '',
            'everyday': everyday, 'top': top, 'bottom': people.BOTTOMS[seed % len(people.BOTTOMS)],
            'hair': hair, 'elder_hair': people.ELDER_HAIRS[seed % len(people.ELDER_HAIRS)], 'style': style,
            'accent': people.TOPS[(seed + 5) % len(people.TOPS)] if role != 'apron' else '#FAFAF7',
            'glasses': '1' if 'glasses' in marks else '', 'beard': '1' if 'beard' in marks or 'moustache' in marks
            else '', 'cane': '1', 'dress': '1' if sex == 'female' and seed % 2 else ''}
        return self.looks[cid]

    def _story_role(self, c):
        """The work clothes a role word the story ties to this person names: "Tom from Pipewise Plumbing, a
        plumber", "the chef, Ana", "Anchor Lee"; None without one."""
        name = str(c.get('name') or '').strip()
        if not name:
            return None
        key = re.escape(name.split()[-1] if len(name.split()) > 1 else name)
        text = ' '.join(self.texts)
        near = []
        for m in re.finditer(r'\b' + key + r'\b', text):
            after = text[m.end():m.end() + 60]
            told = re.match(r",?\s+(?:is\s+|was\s+)?(?:the|a|an|our|my|your|his|her|their)\s+(?:[\w-]+\s+){0,2}[\w-]+|"
                            r"\s*[-–—:]\s*(?:[\w'’-]+\s+){0,2}[\w-]+", after)      # a lower third: "Sam - Engineer"
            near.append(told.group() if told else '')
            before = re.search(r'([\w-]+)\s+$', text[max(0, m.start() - 30):m.start()])
            near.append(before[1] if before else '')
        for chunk in near:
            for cue, outfit in ROLE_OUTFITS:
                if outfit not in ('king', 'queen', 'princess') and re.search(cue, chunk.lower()):
                    return outfit
        return None

    def _shot(self, line, begin, at, staged, pictures, spec, scene=None, bid=None):
        shot = Shot(begin, begin)
        present = [cid for cid in line.present if cid in self.cast]
        if line.roar_lesson or not present:
            present = present or staged[:3]
        else:
            present += [cid for cid in staged if cid not in present and self._human(cid)]
        present += [cid for cid in line.extras if cid not in present]
        if not present and not line.crowd and not line.props:
            present = staged[:3]
        figures = [self._cast_figure(cid, line) for cid in present[:4]]
        for f in figures:
            pose = line.poses.get(f.key)
            if pose:
                f.pose, f.cue = pose[0], at(pose[1])
        settled = sets.settles(line.text)
        subject = next((f for f in figures if f.key == line.subject), None)
        if settled and subject is not None and subject.pose in ('stand', 'walk', 'run'):
            subject.pose, subject.cue = settled[0], at(line.start + settled[1])   # "squeezes onto the couch"
        shot.lesson = line.roar_lesson
        layout = self._layout_lesson if shot.lesson else self._layout
        layout(figures, line)
        if line.speaker in [f.key for f in figures] and len(figures) > 1 and not any(f.travel for f in figures):
            self._face_speaker(figures, line.speaker)
        shot.figures = figures
        if line.eyes and line.eyes in self.cast:
            target = next((f for f in figures if f.key == line.eyes), None)
            if target:
                shot.eyes, shot.eyes_at = target, at(line.eyes_at)
        scene = scene or self.stager.scene(pictures)
        place = self.stager.where(line, scene)
        props = list(dict.fromkeys([p for p in line.props if not _sky(p)] +
                                   [p for p in scene['scenery'] if p not in line.props and p in pictures]))[:2]
        if place in sets.INTERIOR:
            props = []                                    # no trees or rivers indoors
        sky = []
        for doodle in line.sky + [p for p in pictures if _sky(p)]:
            if _sky_kind(doodle) not in [_sky_kind(d) for d in sky]:
                sky.append(doodle)                              # one sun, one moon: never two different suns
        sky = sky[:2]
        atmosphere = spec['atmosphere']['kind']
        kinds = [_sky_kind(d) for d in sky]
        if atmosphere in ('night_stars', 'shooting_star', 'fog_with_shooting_star') and 'moon' not in kinds:
            sky.append('fl_crescent_moon')
        if atmosphere == 'rain' and 'fl_cloud_with_rain' not in sky:
            sky.append('fl_cloud_with_rain')
        if atmosphere in ('dawn', 'rays') and 'sun' not in kinds:
            sky.append('fl_sun')
        night = 'moon' in [_sky_kind(d) for d in sky] or atmosphere in ('night_stars', 'shooting_star')
        shot.place = place
        planned = scene['things']
        scene['things'] = [t for t in planned if t['doodle'] in pictures]   # a plan's thing waits for its sentence
        try:
            built = self.stager.stage(shot, line, scene, place, figures, at, not (figures or line.crowd or props),
                                      night)
        finally:
            scene['things'] = planned
        if built and place not in sets.NATURE:
            props = [p for p in props if 'tree' not in p]      # the set has its own trees
        sky = self._window_sky(shot, sky, place)
        sides = [.12, .88]
        resting = [f for f in figures if f.pose in ('lie', 'sleep', 'sit')] if any(f.travel for f in figures) else []
        for i, doodle in enumerate(props):
            tall = doodle in ('fl_deciduous_tree', 'fl_palm_tree', 'fl_evergreen_tree', 'fl_mountain')
            x = sides[i]
            if resting and doodle in ('fl_deciduous_tree', 'fl_palm_tree'):
                x, resting = sum(f.x for f in resting) / len(resting), []   # "where his parents rested": under it
            shot.props.append((doodle, x, GROUND - .02, .5 if tall else .3))
        for i, doodle in enumerate(sky[:2]):
            if isinstance(doodle, tuple):
                shot.sky.append(doodle)                       # seen through a window
            else:
                shot.sky.append((doodle, (.83, .2)[i], .15, .16))
        named = [t['doodle'] for t in line.things if t['doodle']]
        for f in figures:
            rest = self.rests.get(f.key)
            if rest and rest[0] == place and f.pose == 'stand' and f.key not in line.poses:
                f.pose, f.cue = rest[2], None              # still on the couch from the line before
            if f.pose in SUPPORTS:
                own = named if f.key == line.subject or f.key in line.poses else []   # "Walt sits in the armchair"
                on = self.seat(f, shot, prefer=own + ([rest[1]] if rest else []))
                if any(s.doodle == on for s in shot.supports):
                    self.rests[f.key] = (place, on, f.pose)
                    continue
            if f.key in line.poses or (rest and rest[0] != place):
                self.rests.pop(f.key, None)
        shot.atmosphere = atmosphere
        self._crowd(shot, line, figures)
        if line.speaker in [f.key for f in figures] and shot.eyes is None:
            for q0, q1 in line.quotes:
                text = drawn(line.text[q0 - line.start:q1 - line.start]).strip().rstrip(',;:').strip()
                cjk = sum(1 for ch in text if ink.is_cjk(ch))
                if text and (cjk / 2 if cjk else len(text.split())) <= BUBBLE_WORDS:
                    lead = q0 + len(line.text[q0 - line.start:]) - len(line.text[q0 - line.start:].lstrip(' "“'))
                    times = tuple(at(lead + i) for i in range(len(text)))
                    if shot.bubbles:
                        shot.bubbles[-1].end = min(shot.bubbles[-1].end, times[0] - .05)
                    shot.bubbles.append(Bubble(line.speaker, text, max(begin, times[0]), max(at(q1), times[-1]) + .6,
                                               times=times))
                    if bid is not None:
                        self.bubbled.append({'beat': bid, 'start': lead, 'end': lead + len(text),
                                             'speaker': line.speaker, 'text': text})
        self.props_clear(shot, figures)
        return shot

    def props_clear(self, shot, figures):
        """Nothing placed sits on or inside a person: a thing nobody holds whose picture overlaps someone's body
        moves aside to the nearest free spot on its own ground line (along the desk or table it stands on)."""
        bodies = [self._shape(f, self._pose_name(f.pose), f.x)[0] for f in figures]
        if not bodies:
            return

        def hits(box):
            return any(min(box[2], b[2]) - max(box[0], b[0]) > .15 * min(box[2] - box[0], b[2] - b[0])
                       and min(box[3], b[3]) - max(box[1], b[1]) > .15 * min(box[3] - box[1], b[3] - b[1])
                       for b in bodies)

        def aside(doodle, x, ground, height, mirror=False):
            box = self.stager.frame(doodle, x, ground, height, mirror)[2]
            if not hits(box):
                return x
            half = (box[2] - box[0]) / 2
            lo, hi = half + .01, 1 - half - .01
            under = next((s for s in shot.supports if s.kind == 'top' and abs(s.y - ground) < .01
                          and s.x0 - .01 <= x <= s.x1 + .01), None)
            if under is not None:
                lo, hi = max(lo, under.x0 + half), min(hi, under.x1 - half)
            spots = [lo + (hi - lo) * i / 60 for i in range(61)] if hi > lo else []
            spots = [s for s in spots if not hits((s - half, box[1], s + half, box[3]))]
            return min(spots, key=lambda s: abs(s - x)) if spots else x

        for piece in shot.set:
            if piece.kind == 'thing' and not piece.holder and not piece.lone:
                piece.x = aside(piece.doodle, piece.x, piece.ground, piece.height, piece.mirror)
        shot.props = [(d, aside(d, x, g, hh), g, hh) for d, x, g, hh in shot.props]

    def _face_speaker(self, figures, speaker):
        """A conversation: the speaker turns to the nearest listener, and everyone else turns to the speaker."""
        talker = next(f for f in figures if f.key == speaker)
        others = [f for f in figures if f is not talker]
        partner = min(others, key=lambda g: abs(g.x - talker.x))
        talker.facing = 'r' if partner.x > talker.x else 'l'
        for f in others:
            f.facing = 'r' if talker.x > f.x else 'l'
        for f in figures:
            self._remember(f)

    @staticmethod
    def seat(f, shot, prefer=()):
        """Rest a sitting, lying or sleeping figure on a support the page shows (a sofa, bed, chair, bench: matched on
        the prop's id and library description), at its seat height and over its middle; returns the support's id, or
        None when the page has none and the figure rests on the ground."""
        kinds = SUPPORTS.get(f.pose, ())
        support = sets.seat_for(shot.supports, f.pose, prefer) if kinds else None
        if support:                                     # the set's own couch, bed, chair, bench or bus seat
            sharing = sum(1 for g in shot.figures if g is not f and abs(g.ground - support.y) < 1e-6
                          and support.x0 <= g.x <= support.x1)
            f.x = support.x0 + (support.x1 - support.x0) * (.5, .18, .84, .5)[min(sharing, 3)]
            f.ground, f.travel = support.y, 0.
            f.depth = max(f.depth, 2)
            return support.doodle
        for doodle, x, ground, height in shot.props:
            entry = library.catalog().get(doodle) or {}
            words = f"{doodle.replace('_', ' ')} {entry.get('desc', '')}".lower()
            kind = next((k for k in kinds if re.search(r'\b' + k + r's?\b', words)), None)
            if kind:
                f.x, f.ground, f.travel = x, ground - SEAT[kind] * height, 0.
                f.depth = max(f.depth, 2)
                return doodle
        return None

    def _remember(self, f):
        self.facing[f.key] = f.facing
        self.at[f.key] = f.x

    def _layout(self, figures, line):
        n = len(figures)
        if not n:
            return
        if any(f.pose == 'carry' for f in figures) and n == 1:
            f = figures[0]
            f.x, f.facing, f.travel = .42, 'r', .1
            f.carried = Figure('carried', f.species, 'baby', None, (), pose='scared',
                               height=f.height * .42, phase=f.phase + 1.)
            self._remember(f)
            return
        walking = [f for f in figures if f.pose in ('walk', 'run')]
        if n == 1:
            f = figures[0]
            f.facing = self.facing.get(f.key, 'r')
            f.x = .42 if f.facing == 'r' else .58
            if f.pose in ('walk', 'run'):
                f.x, f.facing = .36, 'r'
                f.travel = .14 if f.pose == 'walk' else .22
            self._remember(f)
            return
        if walking and len(walking) < n:
            self._arrive(walking, [f for f in figures if f not in walking])
            for f in figures:
                self._remember(f)
            return
        # Adults on the outside facing in, a cub between them; everyone keeps the side they had in the last shot.
        side = lambda group: sorted(group, key=lambda f: self.at[f.key]) if all(f.key in self.at for f in group) else group
        babies = [f for f in figures if f.age == 'baby']
        adults = side([f for f in figures if f.age != 'baby'])
        order = adults[:1] + babies + adults[1:] if babies and len(adults) >= 2 else side(adults + babies)
        travel = .1 if walking else 0.
        gap = TALK_GAP if all(f.species == 'human' for f in order) else GAP
        self._fit(order, lambda: self._pack(order, .04, .96 - travel, gap=gap))
        for f in order:
            f.facing = 'r' if f.x < .5 else 'l' if f.x > .5 else ('r' if not adults else 'l')
            if f.age == 'baby':
                f.depth = 2
        for f in walking:
            f.facing, f.travel = 'r', travel
        for f in figures:
            if f.pose == 'nuzzle':
                partner = min((g for g in figures if g is not f), key=lambda g: abs(g.x - f.x))
                f.facing = 'r' if partner.x > f.x else 'l'
                f.x += (partner.x - f.x) * .35
            self._remember(f)

    def _arrive(self, travellers, resting):
        """"He ran to the great fig tree where his parents rested": the resting ones together on the right, facing
        the one who comes running in from the left and stops in front of them instead of running over them."""
        for f in resting:
            f.facing = 'l'
        for f in travellers:
            f.facing, f.depth = 'r', 2

        def arrange():
            if not self._pack(resting, .3, .96, align='right'):
                return False
            self._pack(travellers, .04, .3, align='left')
            stop = min(f.x - self._half(f) for f in resting) - .03
            room = stop - max(f.x + self._half(f) for f in travellers)
            for f in travellers:
                f.travel = max(0., min(.22 if f.pose == 'run' else .14, room))
            return room >= .1
        self._fit(travellers + resting, arrange)

    def _fit(self, figures, arrange):
        """Run arrange() at the largest scale at which it fits the page: the figures shrink together, as when the
        camera pulls back for a group shot."""
        base = [f.height for f in figures]
        for k in SCALES:
            for f, height in zip(figures, base):
                f.height = height * k
            if arrange():
                return k
        return SCALES[-1]

    def _pack(self, order, lo, hi, align='center', gap=GAP):
        """Side by side between lo and hi with a small gap; False when they do not fit."""
        halves = [self._half(f) for f in order]
        total = 2 * sum(halves) + gap * (len(order) - 1)
        x = {'center': (lo + hi - total) / 2, 'right': hi - total, 'left': lo}[align]
        for f, half in zip(order, halves):
            f.x = x + half
            x += 2 * half + gap
        return total <= hi - lo + 1e-9

    def _layout_lesson(self, figures, line):
        """Pendo's point of view: the cub small in the foreground corner looking up, the parent large, roaring."""
        for f in figures:
            if f.age == 'baby':
                f.x, f.ground, f.height, f.facing, f.depth = .15, 1.05, .46, 'r', 3
                f.pose = 'look_up'
            else:
                f.x, f.ground, f.height, f.facing, f.depth = .62, .86, .66, 'l', 1
                f.pose = 'roar'

    def _half_width(self, f):
        """Half the figure's drawn width, as a share of the frame width."""
        return self._half(f)

    @staticmethod
    def _pose_name(pose):
        return {'look': 'stand', 'happy': 'stand', 'nuzzle': 'stand', 'bow': 'stand'}.get(pose, pose)

    def _shape(self, f, pose, x):
        """(body, head) frame boxes (x0, y0, x1, y1 shares) of a figure in one pose with its feet at (x, ground)."""
        doodle, mirror = preset(f.species, f.age, f.sex, pose, f.facing, f.marks)
        left, top, right, bottom = _bbox(doodle, mirror)
        box = _box(doodle, f.height, self._reference(f))
        _, sw, sh = _svg(doodle)
        w, h = self.size
        width = box * sw / sh * h / w
        middle = (left + right) / 2
        body = (x + (left - middle) * width, f.ground - (bottom - top) * box, x + (right - middle) * width, f.ground)
        ax, ay = anchor(doodle, 'head', mirror)
        hx, hy, r = x + (ax - middle) * width, f.ground - (bottom - ay) * box, HEAD * f.height
        return body, (hx - r * h / w, hy - r, hx + r * h / w, hy + r)

    def _shapes(self, f):
        """Every (body, head) a figure shows in its shot: standing and in its pose, where it starts and ends."""
        ends = {f.x, f.x + (1 if f.facing == 'r' else -1) * f.travel}
        return [self._shape(f, pose, x) for pose in {'stand', self._pose_name(f.pose)} for x in ends]

    def _half(self, f):
        return max(body[2] - body[0] for body, _ in (self._shape(f, pose, 0.)
                                                     for pose in {'stand', self._pose_name(f.pose)})) / 2

    def _clear(self, f, others):
        """No body of f's covers a head drawn behind it, no head of f's is behind a body in front of it, and within
        one row f stands beside the others instead of on them."""
        mine = self._shapes(f)
        for g in others:
            if g is f or 'nuzzle' in (f.pose, g.pose) or g.carried is f or f.carried is g:
                continue
            for body, head in mine:
                for other, other_head in self._shapes(g):
                    if (g.depth > f.depth and _overlap(head, other) or g.depth < f.depth and _overlap(other_head, body)
                            or g.depth == f.depth and _overlap(body, other, .03)):
                        return False
        return True

    def _place(self, m, placed, subject):
        """Somewhere on the page where m keeps every head in sight, clear of the cast and spread from the other
        animals, else beside the cast member it turns to (``subject``); False when there is no such place."""
        half = self._half(m)
        lo, hi = half + .02, 1 - half - .02 - m.travel
        if lo > hi:
            return False
        cast = [body for g in placed if not g.crowd for body, _ in self._shapes(g)]
        crowd = [g.x for g in placed if g.crowd]

        def cost(x):
            covers = sum(max(0., min(x + half, b[2]) - max(x - half, b[0])) for b in cast)
            return (round(covers, 3), -round(min((abs(x - c) for c in crowd), default=1.), 2),
                    abs(x - subject.x) if subject else 0.)
        for x in sorted((lo + (hi - lo) * i / 40 for i in range(41)), key=cost):
            if m.depth < min((g.depth for g in placed if not g.crowd), default=m.depth) and cost(x)[0]:
                continue                  # the back row stands beside the cast, never in a gap between its heads
            m.x = x
            m.facing = ('r' if subject.x > x else 'l') if subject else ('r' if x < .5 else 'l')
            if self._clear(m, placed):
                return True
        return False

    def _crowd(self, shot, line, figures):
        crowd = list(line.crowd)
        if not crowd:
            return
        trees = [x for doodle, x, *_ in shot.props if doodle in ('fl_deciduous_tree', 'fl_palm_tree')]
        species = []
        for name, count in crowd:
            names = JUNGLE if name == 'animal' else (name,)
            for i in range(count):
                species.append(names[i % len(names)])
        leader = next((f for f in figures if f.pose in ('walk', 'run')), None)
        species = species[:6 if leader else 7]
        pose = {'walk': 'walk', 'run': 'run', 'scared': 'scared', 'bow': 'bow', 'look': 'stand'}.get(line.crowd_pose, 'stand')
        members = [Figure(f'crowd-{name}-{i}', name, 'adult', None, (), pose=pose, height=SMALL.get(name, .16),
                          depth=0, crowd=True, phase=_seed(name + str(i))) for i, name in enumerate(species)]
        climbers = [m for m in members if m.species in ARBOREAL and trees and leader is None]
        for i, m in enumerate(climbers):
            m.x, m.ground = trees[0] - .04 + .05 * (i % 3), .44 + .05 * (i % 2)
        walkers = [m for m in members if m not in climbers]
        sizes = {m.key: m.height for m in walkers}
        if leader is not None:
            # A procession: the leader in front, everyone else in one line behind on the path, smaller if the line
            # is long; whoever still does not fit stays off the page.
            leader.x = .6
            for k in SCALES:
                x = leader.x - self._half(leader) - GAP
                for m in walkers:
                    m.height, m.ground, m.facing, m.travel, m.pose = sizes[m.key] * k, GROUND - .03, leader.facing, \
                        leader.travel, leader.pose
                    half = self._half(m)
                    m.x = x - half
                    x -= 2 * half + GAP
                if x >= 0.:
                    break
            walkers = [m for m in walkers if m.x - self._half(m) >= .01]
        else:
            # A gathering: the cast where the layout put it (drawn smaller if the page is crowded), animals bigger
            # than the cast a little behind it, smaller ones in front, each where no head is hidden.
            homes = [(f.x, f.height, f.travel) for f in figures]
            shortest = min((f.height for f in figures), default=.2)
            behind = sorted((m for m in walkers if m.height >= shortest), key=lambda m: -m.height)
            front = sorted((m for m in walkers if m.height < shortest), key=lambda m: -m.height)
            subject = figures[-1] if figures else None     # "bowed her head, not to Kojo, but to Pendo"
            for k in SCALES:
                for f, (x, height, travel) in zip(figures, homes):
                    f.x, f.height, f.travel = .5 + (x - .5) * k, height * k, travel * k
                placed, missing = list(figures) + climbers, []
                for m in behind + front:
                    m.height = sizes[m.key] * k * (.9 if m in behind else 1.)
                    m.ground, m.depth = (GROUND - BACK_ROW, 0) if m in behind else (GROUND, FRONT_ROW)
                    (placed if self._place(m, placed, subject) else missing).append(m)
                if not missing:
                    break
            walkers = [m for m in walkers if m not in missing]
            for f in figures:
                self._remember(f)
        members = climbers + walkers
        for m in members:
            half = self._half(m)
            m.x = min(1 - half - .01 - m.travel, max(half + .01, m.x)) if half < .45 else .5
        shot.figures.extend(members)

    # ---------------- drawing
    def paper(self, w, h):
        if (w, h) not in self._paper:
            self._paper[(w, h)] = self.paper_image(w, h).convert('RGB')
        return self._paper[(w, h)]

    def frame(self, shots, local):
        i = max(0, next((k for k in range(len(shots) - 1, -1, -1) if local >= shots[k].start), 0))
        image = self._draw(shots[i], local)
        if i:
            kind = self.turn_kind(shots[i - 1], shots[i])
            since = local - shots[i].start
            if since < (BLEND if kind == 'blend' else WIPE):
                image = self._turn(self._draw(shots[i - 1], local), image, kind, since)
        return image

    def turn(self, before_shots, before_local, after_shots, after_local, since):
        """A scene join between two story spans, ``since`` seconds after it: the page turns like any shot change."""
        after = self.frame(after_shots, after_local)
        i = max(0, next((k for k in range(len(after_shots) - 1, -1, -1) if after_local >= after_shots[k].start), 0))
        kind = self.turn_kind(before_shots[-1], after_shots[i])
        if since >= (BLEND if kind == 'blend' else WIPE):
            return after
        return self._turn(self.frame(before_shots, before_local), after, kind, max(0., since))

    @staticmethod
    def _set(shot):
        """What a page shows besides its cast and crowd: its setting, sky, weather and framing."""
        return (tuple(shot.props), tuple(d for d, *_ in shot.sky), shot.atmosphere, shot.lesson, bool(shot.title),
                tuple(p.doodle for p in shot.set if p.kind in ('strip', 'wall', 'set')))

    def turn_kind(self, before, after):
        """'blend' where the same set continues, 'wipe' for a new set or after a close-up."""
        return 'blend' if before.eyes is None and self._set(before) == self._set(after) else 'wipe'

    def _turn(self, before, after, kind, since):
        if kind == 'blend':
            return Image.blend(before, after, min(1., since / BLEND))
        from .motion import wipe_mask
        p = 1 - (1 - min(1., since / WIPE)) ** 3
        return Image.composite(after, before, wipe_mask(self.size, p, WIPE_ANGLE, soft=4))

    def _pose_doodle(self, f, local):
        """(doodle, mirror) for the figure's pose at this time: an act's picture (a gesture, a stride while it goes
        somewhere, wings while it flies) over its own pose."""
        m = acting.motion(self, f, None, local) if getattr(f, 'acts', None) else None
        if m is not None and (m.pose or m.facing or m.moving):
            f = replace(f, pose=m.pose or f.pose, facing=m.facing or f.facing, cue=None if m.pose else f.cue)
            f.travel = 1. if m.moving else 0.
            if m.moving == 'fly':
                for name in (('fly2', 'fly') if int(local * 8) % 2 else ('fly', 'fly2')):
                    doodle, mirror = preset(f.species, f.age, f.sex, name, f.facing, f.marks)
                    if meta(doodle).get('pose') == name:
                        return doodle, mirror, 'fly'
            if m.moving == 'tiptoe':
                f.phase -= local * .5                   # careful steps: two strides a second, not four
        pose = f.pose
        if f.cue is not None and local < f.cue and pose in ('roar', 'look_up', 'scared', 'bow', 'happy', 'nuzzle'):
            pose = 'stand'
        if pose == 'roar' and f.cue is not None and local > f.cue + ROAR_SECONDS:
            pose = 'stand'
        if pose == 'sleep' and f.cue is not None and local < f.cue and f.before:
            pose = f.before
        name = {'look': 'stand', 'happy': 'stand', 'nuzzle': 'stand', 'bow': 'stand'}.get(pose, pose)
        if name in ('walk', 'run') and not f.travel and f.carried is None:
            name = pose = 'stand'                       # walking nowhere is standing: no stride, no head wobble
        if name == 'walk':
            stride = int((local + f.phase) * 4) % 2
            doodle, mirror = preset(f.species, f.age, f.sex, 'walk2' if stride else 'walk', f.facing, f.marks)
            if meta(doodle).get('pose') in ('walk1', 'walk2'):
                return doodle, mirror, pose
            return preset(f.species, f.age, f.sex, 'walk', f.facing, f.marks) + (pose,)
        return preset(f.species, f.age, f.sex, name, f.facing, f.marks) + (pose,)

    def _camera(self, shot, local):
        """[x, y, zoom] of the camera over the page: locked, apart from a push into the eyes and a roar's shake.
        A push per shot restarted at every sentence, so the picture zoomed in and jumped back every 2-3 s."""
        cam = list(shot.view)
        shake = 0.
        roaring = [f for f in shot.figures if f.pose == 'roar' and f.cue is not None]
        for f in roaring:
            p = action_pose(Action('roar', f.cue, ROAR_SECONDS, 1.), local)
            shake = max(shake, p.screen_shake)
        if shot.eyes is not None:
            cam = self._eye_camera(shot, local, cam)
        cam[0] += shake * .0016 * math.sin(local * 39)
        cam[1] += shake * .0016 * math.sin(local * 31)
        return cam

    def _draw(self, shot, local):
        w, h = self.size
        if shot.page:
            return planned.first_person(self, shot, local)
        cam = self._camera(shot, local)
        canvas = self._page(cam if shot.eyes is not None else (.5, .5, 1.))    # the paper stays put under a framing
        overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        through = any(p.doodle in sets.WINDOWS for p in shot.set)
        if not through:
            for doodle, x, y, height in shot.sky:
                self._paste(overlay, doodle, False, x, y + height / 2, height, cam, parallax=.4)
        for piece in shot.set:
            if not piece.front:
                self._piece(overlay, piece, shot, local, cam)
                for host, shown in shot.screen:
                    if host is piece:
                        planned.draw_screen(self, overlay, piece, shown, shot, local, cam)
            if through and piece.doodle in sets.WINDOWS:
                for doodle, x, y, height in shot.sky:
                    self._paste(overlay, doodle, False, x, y + height / 2, height, cam)
        for doodle, x, ground, height in shot.props:
            self._paste(overlay, doodle, False, x, ground, height, cam, record=self.prop_boxes)
        if getattr(shot, 'atmosphere', 'none') in ('fog', 'fog_with_shooting_star'):
            self._fog(overlay, local)
        if any(f.crowd for f in shot.figures) or shot.figures:
            self._shadows(overlay, shot, local, cam)
        effects = []
        order = list(self.cast)
        # A steady order: who is in front of whom never flips between pages of one set.
        for f in sorted(shot.figures, key=lambda f: (f.depth, order.index(f.key) if f.key in order else len(order))):
            effects += self._figure(overlay, f, shot, local, cam)
        for piece in shot.set:
            if piece.front:
                self._piece(overlay, piece, shot, local, cam)
        if shot.hands:
            planned.draw_hands(self, overlay, shot, cam)
        if self._raining(shot) and shot.place not in sets.INTERIOR:
            self._rain(overlay, local)                  # indoors the rain is heard, not drawn across the room
        for effect in effects:
            effect(overlay)
        face = self._face_overlay(shot, local)
        for bubble in shot.bubbles:
            if bubble.start <= local < bubble.end:
                self._bubble(overlay, shot, bubble, local, cam)
        canvas.paste(overlay, (0, 0), overlay)
        if face is not None:
            image, alpha = face
            canvas = Image.blend(canvas, image, alpha)
        if shot.title:
            self._title(canvas, shot.title, local)
        return canvas

    def support(self, shot, pose='sit'):
        """The furniture on this page a figure in ``pose`` can sit on ('sit') or lie on ('sleep', 'lie'): a
        sets.Support with the seat or lying line y and its span x0..x1 (frame shares), or None."""
        return sets.seat_for(shot.supports, pose)

    def _window_sky(self, shot, sky, place):
        """Indoors the sun or moon shows through the window; a room without one shows no sky."""
        if place not in sets.INTERIOR:
            return sky
        window = next((p for p in shot.set if p.doodle in sets.WINDOWS), None)
        if window is None:
            return []
        X, Y, _ = self.stager.frame(window.doodle, window.x, window.ground, window.height)
        inside = [d for d in sky if _sky_kind(d) in ('sun', 'moon')][:1] or sky[:1]
        size = .36 * window.height
        return [(d, X(.36 + .28 * i), Y(.26) - size / 2, size) for i, d in enumerate(inside)]

    def _piece(self, overlay, piece, shot, local, cam):
        """One picture of the set, or a thing in it, at this time: strips span the page, a held thing moves with
        its holder's hand, and a thing that rolls, falls or flies moves when its verb is spoken."""
        if piece.kind == 'strip':
            w, h = self.size
            x0, y0, zoom = self._to_screen(0., piece.top, cam)
            x1, y1, _ = self._to_screen(1., piece.ground, cam)
            px_w, px_h = max(8, round(x1 - x0)), max(4, round(y1 - y0))
            image = _strip_image(piece.doodle, px_w, px_h)
            overlay.alpha_composite(image, (max(0, round(x0)), max(0, round(y0))),
                                    (max(0, -round(x0)), max(0, -round(y0))))
            return
        x, ground, rotate, anchor_y = piece.x, piece.ground, piece.rotate, 1.
        moved = acting.held(piece, local)
        if moved is not None:
            # Grabbed or handed over (engine.acting): in its new holder's hand from then on, and on the way
            # from one hand to the other while it is passed.
            who, share = moved
            a = self.held_at(piece, shot, local, who)
            if a is not None and 0. < share < 1.:
                giver = piece.__dict__['passed'][2]
                b = self.held_at(piece, shot, local, giver)
                e = share * share * (3 - 2 * share)
                a = a if b is None else tuple(q + (p_ - q) * e for p_, q in zip(a, b))
            if a is not None:
                x, ground, anchor_y = a
                self._paste(overlay, piece.doodle, piece.mirror, x, ground, piece.height, cam, anchor_y=anchor_y)
                return
        if piece.kind == 'hand':
            held = self.held_at(piece, shot, local)
            if held is None:
                return
            x, ground, anchor_y = held
        elif piece.motion and piece.cue is not None:
            x, ground, rotate, anchor_y = self._moving(piece, local)
        self._paste(overlay, piece.doodle, piece.mirror, x, ground, piece.height, cam, rotate=rotate,
                    anchor_y=anchor_y)

    def held_at(self, piece, shot, local, holder=None):
        """(x, ground, anchor_y) of a thing in its holder's hands: in the lap of someone sitting or lying, else in
        the hand and never above the chin, so it never covers the face. None when the holder is not on the page."""
        holder = holder or piece.holder
        f = next((f for f in shot.figures if f.key == holder), None)
        if f is None:
            return None
        doodle, mirror, _ = self._pose_doodle(f, local)
        fx, _ = self.where(f, shot, local)
        x, ground = self._point(doodle, mirror, 'carry', fx, f.ground, f.height, self._reference(f))
        if f.pose in ('sit', 'lie', 'sleep'):              # in the lap of someone sitting, by their hands
            return fx + (1 if f.facing == 'r' else -1) * .12 * f.height, f.ground - .02 * f.height, 1.
        _, mouth = self._point(doodle, mirror, 'mouth', fx, f.ground, f.height, self._reference(f))
        chin = max([mouth] + [head[3] for _, head in self._shapes(f)])
        return x, max(ground, chin + .02 * f.height + piece.height / 2), .5

    @staticmethod
    def _moving(piece, local):
        """(x, ground, rotation, anchor_y) of a thing in motion: an orange rolls (turning as it goes), a dropped
        bag falls and settles tilted, a kite flies off, a ball bounces."""
        t = local - piece.cue
        dx, dg = piece.to
        if piece.motion == 'roll':
            u = min(1., max(0., t / 1.6))
            e = 1 - (1 - u) ** 2
            centre = piece.ground - piece.height / 2
            turn = -math.degrees(dx * e / max(.01, piece.height / 2 * .5625)) if dx else 0.
            return piece.x + dx * e, centre + dg * e, turn, .5
        if piece.motion == 'fall':
            if t < 0:
                return piece.x, piece.ground - .2, 0., 1.
            u = min(1., t / .45)
            drop = .2 * (1 - u * u)
            hop = .025 * abs(math.sin(math.pi * min(1., max(0., (t - .45) / .3)))) if t > .45 else 0.
            return piece.x, piece.ground - drop - hop, 10. * min(1., t / .75), 1.
        if piece.motion == 'slide':                   # a truck going by: straight across, steady
            u = min(1., max(0., t / 2.4))
            return piece.x + dx * u, piece.ground + dg * u, 0., 1.
        if piece.motion == 'fly':
            u = min(1., max(0., t / 2.6))
            return (piece.x + dx * u, piece.ground + dg * u + .015 * math.sin(local * 3), 6 * math.sin(local * 2),
                    1.)
        hop = .06 * abs(math.sin(math.pi * max(0., t) / .5)) * (0 <= t < 2.)
        return piece.x, piece.ground - hop, 0., 1.

    def _page(self, cam):
        """The paper under the camera: a push or a shake reads as a camera move over the page. The grain is soft,
        so a bilinear box resize (a fraction of an affine transform's cost) is enough."""
        w, h = self.size
        paper = self.paper(w, h)
        if cam[2] <= 1:
            return paper.copy()
        bw, bh = w / cam[2], h / cam[2]
        x0 = min(w - bw, max(0., cam[0] * w - bw / 2))
        y0 = min(h - bh, max(0., cam[1] * h - bh / 2))
        return paper.resize((w, h), Image.Resampling.BILINEAR, box=(x0, y0, x0 + bw, y0 + bh))

    def _to_screen(self, x, y, cam, parallax=1.):
        w, h = self.size
        zoom = 1 + (cam[2] - 1) * parallax
        return (w / 2 + (x - (.5 + (cam[0] - .5) * parallax)) * zoom * w,
                h / 2 + (y - (.5 + (cam[1] - .5) * parallax)) * zoom * h, zoom)

    def _paste(self, overlay, doodle, mirror, x, ground, height, cam, *, parallax=1., rotate=0., squash=0.,
               anchor_y=1., pin=None, reference=None, crown=0., shut=False, record=None):
        """Paste a doodle with its feet (alpha bottom) at (x, ground); returns its screen box.

        ``height`` is the drawn height of ``reference`` (the character's standing preset) when given, so all of a
        character's poses share one scale; ``pin`` is a point of the doodle box (shares) placed at (x, ground);
        ``crown`` is a crown's height (frame share) worn on the doodle's head, moving with every lean; ``shut`` closes
        its eyes."""
        w, h = self.size
        sx, sy, zoom = self._to_screen(x, ground, cam, parallax)
        left, top, right, bottom = _bbox(doodle, mirror)
        px = max(8, round(_box(doodle, height, reference) * h * zoom))
        if px > 6 * h:
            return None
        step = max(2, int(px * .015))
        px = round(px / step) * step        # a bounded set of cached sizes during camera pushes
        image = sprite(doodle, px, mirror, shut)
        foot_x, foot_y = (left + right) / 2 * image.width, (top + (bottom - top) * anchor_y) * image.height
        if pin is not None:
            foot_x, foot_y = pin[0] * image.width, pin[1] * image.height
        if crown:
            image, pad = crowned(doodle, px, mirror, max(8, round(crown * h * zoom / step) * step), shut)
            foot_y += pad
        if squash:
            before = image.size
            image = image.resize((max(1, round(image.width / (1 - squash))), max(1, round(image.height * (1 - squash)))),
                                 Image.Resampling.BICUBIC)
            foot_x, foot_y = foot_x * image.width / before[0], foot_y * image.height / before[1]
        iw, ih = image.size
        if rotate:
            pad = round(max(iw, ih) * .25)
            padded = Image.new('RGBA', (iw + 2 * pad, ih + 2 * pad), (0, 0, 0, 0))
            padded.paste(image, (pad, pad))
            image = padded.rotate(rotate, resample=Image.Resampling.BICUBIC, center=(foot_x + pad, foot_y + pad))
            foot_x, foot_y = foot_x + pad, foot_y + pad
        at = (round(sx - foot_x), round(sy - foot_y))
        if at[0] >= overlay.width or at[1] >= overlay.height or at[0] + image.width <= 0 or at[1] + image.height <= 0:
            return at[0], at[1], image.width, image.height      # wholly off the page (a push past a prop, a closer shot)
        overlay.alpha_composite(image, (max(0, at[0]), max(0, at[1])),
                                (max(0, -at[0]), max(0, -at[1])))
        if record is not None:              # a figure or a prop: where it is drawn, for the caption to avoid
            drawn = image.getchannel('A').getbbox()
            if drawn:
                record.append((at[0] + drawn[0], at[1] + drawn[1], at[0] + drawn[2], at[1] + drawn[3]))
        return at[0], at[1], image.width, image.height

    def where(self, f, shot, local):
        """(x, ground) of the figure's feet at this time: where its acts have taken it, or along its travel."""
        if getattr(f, 'acts', None):
            m = acting.motion(self, f, shot, local)
            if m.placed or not f.travel:
                return m.x + m.dx, f.ground + m.dy
        u = min(1., max(0., (local - shot.start) / max(.01, shot.end - shot.start)))
        return f.x + (1 if f.facing == 'r' else -1) * f.travel * (u * u * (3 - 2 * u)), f.ground

    def _figure(self, overlay, f, shot, local, cam):
        w, h = self.size
        m = acting.motion(self, f, shot, local) if getattr(f, 'acts', None) else None
        if m is not None and m.gone:
            return []
        doodle, mirror, pose = self._pose_doodle(f, local)
        if m is not None and m.facing:
            f = replace(f, facing=m.facing)
        u = min(1., max(0., (local - shot.start) / max(.01, shot.end - shot.start)))
        x, ground = f.x, f.ground
        direction = 1 if f.facing == 'r' else -1
        rotate, dy, height, pin = 0., 0., f.height, None
        squash = BREATH * math.sin(local * 2.6 + f.phase)
        if pose == 'sleep' or (f.pose == 'sleep' and pose == f.before):     # lying awake until the words: same breath
            squash = SLEEP_BREATH * math.sin(2 * math.pi * local / SLEEP_CYCLE + f.phase)
        moving = (m.moving if m is not None else None) or (f.travel and pose in ('walk', 'run', 'carry'))
        if moving and moving != 'fly':
            # A stride's bounce while the figure goes somewhere; no sway, and nothing at all while it stands
            # (holding something is not walking: no wobble, no idle head tilt).
            rate = 2.2 if pose == 'run' else 1.4
            dy -= (.012 if pose == 'run' else .007) * abs(math.sin(math.pi * rate * (local + f.phase)))
        if m is not None:
            x, ground = m.x + m.dx, ground + m.dy
            rotate, height = m.rotate, f.height * m.scale
            squash += m.squash
            if m.pivot == 'rear':
                pin, x = self._rear(doodle, mirror, x, f, height)
        if (m is None or not m.placed) and f.travel and pose != 'stand':
            x += direction * f.travel * (u * u * (3 - 2 * u))
        if pose == 'scared' and local < (f.cue if f.cue is not None else shot.start) + TREMBLE:
            x += .004 * math.sin(local * 44 + f.phase)
        if pose == 'bow':
            rotate = direction * -9 * min(1., max(0., (local - (f.cue or shot.start)) / .6))
        if pose == 'happy':
            since = local - (f.cue if f.cue is not None else shot.start)
            dy -= .02 * abs(math.sin(local * 5 + f.phase)) * (0 < since < LAUGH)
        if pose == 'nuzzle':
            rotate = direction * -6 * min(1., max(0., (local - (f.cue or shot.start)) / .7))
        if pose == 'look_up' and not meta(doodle).get('pose') == 'look_up':
            rotate = direction * 7          # a stand-in doodle tilts its head up
        roar = None
        if pose == 'roar' and f.cue is not None:
            roar = action_pose(Action('roar', f.cue, ROAR_SECONDS, 1.), local)
            rotate += direction * -roar.lean * .35
            squash += roar.squash
            x += direction * roar.dx * .0006
        reference = self._reference(f)
        self._paste(overlay, doodle, mirror, x, ground + dy, height, cam, rotate=rotate, squash=squash,
                    reference=reference, crown=CROWN_SIZE * height if 'crown' in f.marks else 0.,
                    shut=pose not in ('sleep', 'roar') and self._blinking(f, local), pin=pin, record=self.figure_boxes)
        effects = []
        for kind, v in (m.effects if m is not None else ()):
            effects.append(lambda o, k=kind, v=v, fig=f, d=doodle, mi=mirror, x0=x, g=ground + dy:
                           self._act_effect(o, k, v, fig, d, mi, x0, g, cam))
        if f.carried is not None:
            c = f.carried
            carried, cm = preset(c.species, c.age, c.sex, c.pose, f.facing, c.marks)
            cx, cy = self._point(doodle, mirror, 'carry', x, ground + dy, f.height, reference)
            swing = 6 * math.sin(local * 4.4 + f.phase)
            scruff = anchor(carried, 'scruff', cm) if meta(carried).get('anchors', {}).get('scruff') else None
            # The carried doodle hangs from the carrier's mouth by its scruff (top of its back).
            effects.append(lambda o, d=carried, m=cm, x0=cx, y0=cy, s=swing, fig=c, pin=scruff: self._paste(
                o, d, m, x0, y0, fig.height, cam, rotate=s, anchor_y=.1, pin=pin, reference=self._reference(fig)))
        if roar is not None and roar.sound > .02:
            effects.append(lambda o, fig=f, d=doodle, m=mirror, p=roar, x0=x, g=ground + dy: self._roar_effects(
                o, fig, d, m, p, x0, g, cam, local))
        if pose == 'sleep':
            zx, zy = self._zzz_at(f, shot, local, doodle, mirror, x, ground + dy)
            effects.append(lambda o, fig=f, x0=zx, y0=zy: self._zzz(
                o, fig.species != 'human' and fig.facing == 'l', x0, y0, fig, cam, local))
        return effects

    def _zzz_at(self, f, shot, local, doodle=None, mirror=None, x=None, ground=None):
        """Where a sleeper's Z marks start (frame shares): above a person's head, wherever the lying doodle puts it,
        or just ahead of an animal's; never on another figure's head (a cub asleep under its father's chin)."""
        if doodle is None:
            doodle, mirror, _ = self._pose_doodle(f, local)
            x, ground = self.where(f, shot, local)
        if f.species == 'human':
            hx, hy = self._point(doodle, mirror, 'head', x, ground, f.height, self._reference(f))
            zx, zy = hx + .04 * f.height / ADULT_HEIGHT, hy - .03
        else:
            zx, zy = x + (.06 if f.facing == 'r' else -.06) * f.height / ADULT_HEIGHT, f.ground - f.height * .75
        heads = [head for g in shot.figures if g is not f and not g.crowd for _, head in self._shapes(g)]
        for _ in range(3):
            head = next((h for h in heads if h[0] - .01 <= zx <= h[2] + .01 and h[1] - .01 <= zy <= h[3] + .01), None)
            if head is None:
                break
            zx = head[0] - .02 if zx - head[0] < head[2] - zx and head[0] > .05 else head[2] + .02
        return zx, zy

    def _zzz(self, overlay, mirror, x, ground, f, cam, local):
        """A sleeper's Z marks: each rises ZZZ_RISE of the frame from (x, ground) over ZZZ_CYCLE seconds, drifting
        away from the face, growing and fading in and out; two are on their way at any time."""
        w, h = self.size
        away = -1 if mirror else 1
        for k in (0, .5):
            t = ((local + f.phase) / ZZZ_CYCLE + k) % 1.
            size = f.height * (.18 + .14 * t)
            sx, sy, zoom = self._to_screen(x + away * .025 * t * f.height / ADULT_HEIGHT, ground - ZZZ_RISE * t,
                                           cam)
            px = max(8, round(size * h * zoom / 4) * 4)
            image = sprite('fl_zzz', px, mirror, False).copy()
            image.putalpha(image.getchannel('A').point(lambda a, v=math.sin(math.pi * t): round(a * v)))
            at = (round(sx - image.width / 2), round(sy - image.height))
            if at[0] < overlay.width and at[1] < overlay.height and at[0] + image.width > 0 and at[1] + image.height > 0:
                overlay.alpha_composite(image, (max(0, at[0]), max(0, at[1])), (max(0, -at[0]), max(0, -at[1])))

    def _rear(self, doodle, mirror, x, f, height):
        """(pin, x) that rotate a figure about its back feet instead of its middle (a head lowered to the ground)."""
        left, _, right, bottom = _bbox(doodle, mirror)
        rear = left + .12 * (right - left) if f.facing == 'r' else right - .12 * (right - left)
        box = _box(doodle, height, self._reference(f))
        _, sw, sh = _svg(doodle)
        w, h = self.size
        return (rear, bottom), x + (rear - (left + right) / 2) * box * sw / sh * h / w

    def _act_effect(self, overlay, kind, v, f, doodle, mirror, x, ground, cam):
        """An act's marks: a swipe's motion arcs in front of the paw, a heavy breath's puff from the mouth."""
        w, h = self.size
        ax, ay = self._point(doodle, mirror, 'mouth', x, ground, f.height, self._reference(f))
        sx, sy, zoom = self._to_screen(ax, ay, cam)
        scale = f.height * h * zoom / 330
        direction = 1 if f.facing == 'r' else -1
        draw = ImageDraw.Draw(overlay)
        if kind == 'arcs':                              # the paw's path, swept from high in front down to the ground
            cy = sy + 40 * scale
            for i in range(3):
                r = (80 + 30 * i) * scale
                cx = sx - direction * (10 + 12 * i) * scale
                sweep = 110 * min(1., v * 1.8)
                a0 = -80 if direction > 0 else 260 - sweep
                alpha = int(255 * (1 - .7 * v) * (1 - .22 * i))
                draw.arc((cx - r, cy - r, cx + r, cy + r), a0, a0 + sweep, fill=(27, 27, 27, alpha),
                         width=max(3, round((9 - 2 * i) * scale)))
        elif kind == 'puff':
            for i in range(2):
                t = (v + i * .5) % 1.
                px = sx + direction * (18 + t * 80) * scale
                py = sy - t * 16 * scale
                r = (8 + 22 * t) * scale
                alpha = int(220 * (1 - t))
                draw.ellipse((px - r, py - r * .7, px + r, py + r * .7), fill=(214, 230, 238, alpha),
                             outline=(96, 128, 146, alpha), width=max(2, round(3 * scale)))

    @staticmethod
    def _blinking(f, local):
        """A character's idle blink: BLINK long, at an irregular moment of every 3 s (2.4 or 3.9 s apart)."""
        t = local + 3 * f.phase / math.tau
        k = math.floor(t / 3)
        return 0 <= t - 3 * k - 1.5 * ((k * .618034 + f.phase) % 1) < BLINK

    def _reference(self, f):
        """The character's standing preset: the scale every one of its poses is drawn at."""
        return preset(f.species, f.age, f.sex, 'stand', f.facing, f.marks)[0]

    def _point(self, doodle, mirror, name, x, ground, height, reference=None):
        """Frame position (x, y shares) of a doodle's named anchor when its feet stand at (x, ground)."""
        w, h = self.size
        ax, ay = anchor(doodle, name, mirror)
        left, _, right, bottom = _bbox(doodle, mirror)
        box = _box(doodle, height, reference)
        _, sw, sh = _svg(doodle)
        return x + (ax - (left + right) / 2) * box * sw / sh * h / w, ground - (bottom - ay) * box

    def _roar_effects(self, overlay, f, doodle, mirror, p, x, ground, cam, local):
        """Sound arcs spreading from the open mouth, and a puff of breath (the rig's roar, on the doodle)."""
        w, h = self.size
        ax, ay = self._point(doodle, mirror, 'mouth', x, ground, f.height, self._reference(f))
        sx, sy, zoom = self._to_screen(ax, ay, cam)
        scale = f.height * h * zoom / 330
        direction = 1 if f.facing == 'r' else -1
        draw = ImageDraw.Draw(overlay)
        for i in range(3):
            radius = (26 + i * 22 + p.sound_expand * 14) * scale
            cx = sx + direction * (22 + i * 26 + p.sound_expand * 10) * scale
            alpha = int(255 * min(1., p.sound) * (1 - i * .18))
            colour = ((201, 149, 78), (159, 119, 75), (27, 27, 27))[i] + (alpha,)
            start, end = (-55, 55) if direction > 0 else (125, 235)
            draw.arc((cx - radius, sy - radius, cx + radius, sy + radius), start, end, fill=colour,
                     width=max(2, round((7 - i * 1.2) * scale)))
        for i in range(3):
            v = (local * .85 + i / 3) % 1.
            px = sx + direction * (10 + v * 70) * scale
            py = sy - v * 18 * scale
            r = (5 + 14 * v) * scale
            alpha = int(200 * p.sound * (1 - v))
            draw.ellipse((px - r, py - r * .7, px + r, py + r * .7), fill=(220, 235, 240, alpha),
                         outline=(160, 190, 200, alpha), width=max(1, round(2 * scale)))

    def _shadows(self, overlay, shot, local, cam):
        draw = ImageDraw.Draw(overlay)
        w, h = self.size
        for f in shot.figures:
            if f.ground > 1.0 or f.ground < .6:
                continue
            if f.pose in ('sit', 'lie', 'sleep') and f.ground < sets.FLOOR - .02:
                continue                                # resting on a seat or bed: its shadow is the furniture's
            if getattr(f, 'acts', None):
                m = acting.motion(self, f, shot, local)
                if m.gone or m.dy < -.03 or m.scale < .9:
                    continue                            # in the air: its shadow would sit on the ground alone
            x, _ = self.where(f, shot, local)
            sx, sy, zoom = self._to_screen(x, f.ground, cam)
            rx, ry = f.height * h * zoom * .55, f.height * h * zoom * .06
            draw.ellipse((sx - rx, sy - ry, sx + rx, sy + ry), fill=(60, 60, 50, 34))

    @staticmethod
    def _raining(shot):
        """The page draws falling rain."""
        return shot.atmosphere == 'rain' or any(d == 'fl_cloud_with_rain' for d, *_ in shot.sky)

    def _fog(self, overlay, local):
        w, h = self.size
        band = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(band)
        for i in range(3):
            y = h * (.55 + .07 * i) + 8 * math.sin(local * .5 + i)
            draw.rounded_rectangle((-40 + 30 * math.sin(local * .3 + i), y, w + 40, y + h * .05),
                                   radius=round(h * .025), fill=(190, 195, 200, 60))
        overlay.alpha_composite(band)

    def _rain(self, overlay, local):
        w, h = self.size
        draw = ImageDraw.Draw(overlay)
        rng = np.random.default_rng(7)
        xs, ys = rng.random(46), rng.random(46)
        for x, y in zip(xs, ys):
            yy = ((y + local * .9) % 1.) * h * .75
            xx = x * w - yy * .08
            draw.line((xx, yy, xx - h * .006, yy + h * .03), fill=(100, 150, 210, 120), width=max(1, round(h / 400)))

    def _eye_camera(self, shot, local, cam):
        """Push into the eyes of the character the line is about."""
        f = shot.eyes
        doodle, mirror, _ = self._pose_doodle(f, local)
        hx, hy = self._point(doodle, mirror, 'eye', f.x, f.ground, f.height, self._reference(f))
        start = max(shot.start, shot.eyes_at - .3)
        v = min(1., max(0., (local - start) / 1.3))
        e = v * v * (3 - 2 * v)
        target_zoom = min(4.5, .9 / max(.08, f.height))       # the head nearly fills the page
        return [cam[0] + (hx - cam[0]) * e, cam[1] + (hy - cam[1]) * e, cam[2] + (target_zoom - cam[2]) * e]

    def _face_overlay(self, shot, local):
        """After the push, the character's own head close-up fills the page (a face preset), for a beat."""
        if shot.eyes is None:
            return None
        f = shot.eyes
        doodle = face(f.species, f.age, f.sex, f.marks)
        start = max(shot.start, shot.eyes_at - .3) + 1.3          # once the push has landed on the eyes
        if doodle is None or local < start:
            return None
        alpha = min(1., (local - start) / FACE_CUT)
        w, h = self.size
        page = self.paper(w, h).copy().convert('RGBA')
        push = 1 + .05 * min(1., (local - start) / 3)
        self._paste(page, doodle, False, .5, .5 + .36 * push, .72 * push, [.5, .5, 1.], anchor_y=1.,
                    crown=.2 * push if 'crown' in f.marks else 0., shut=self._blinking(f, local))
        return page.convert('RGB'), alpha

    def faces(self, shot, view=None):
        """Screen boxes (pixels) of every face on the page under the shot's framing: from the top of the head (hair,
        mane) down past the mouth, a little wider than the head. A bubble never covers one."""
        w, h = self.size
        view = list(shot.view if view is None else view)
        out = []
        for g in shot.figures:
            for body, head in self._shapes(g):
                x0, y0, x1, y1 = head[0], min(head[1], body[1]), head[2], head[3]
                pad = .01
                (a, b, _), (c, d, _) = (self._to_screen(x0 - pad, y0 - pad, view),
                                        self._to_screen(x1 + pad, y1 + pad, view))
                out.append((a, b, c, d))
        return out

    def _bubble_plan(self, shot, bubble):
        """Where a bubble sits on the frame under the shot's framing, worked out once: (speaker's mouth in frame
        shares or None, box and tip in pixels, text lines, font size, language). The box sits as near the speaker's
        mouth as it can, above or beside the head, clear of every face on the page and above the captions; the
        tail runs from its bottom edge to the mouth. A voice whose speaker is off the frame comes in from its edge."""
        if bubble in self._bubbles:
            return self._bubbles[bubble]
        w, h = self.size
        view = list(shot.view)
        f = next((g for g in shot.figures if g.key == bubble.speaker), None)
        mouth = None
        if f is not None:
            middle = (bubble.start + bubble.end) / 2
            doodle, mirror, _ = self._pose_doodle(f, middle)
            mouth = self._point(doodle, mirror, 'mouth', f.x, f.ground, f.height, self._reference(f))
            mx, my, _ = self._to_screen(*mouth, view)
            if not (.02 * w <= mx <= .98 * w and .05 * h <= my <= .8 * h):
                mouth = None                                    # framed out: heard from that side
        if mouth is None:
            side = bubble.side or ('l' if f is not None and mx < w / 2 else 'r')
            mx, my = (3. if side == 'l' else w - 3.), .5 * h
        lang = 'zh' if any(ink.is_cjk(ch) for ch in bubble.text) else 'en'
        heads = self.faces(shot)
        bodies = [tuple(v for p in (self._to_screen(x0, y0, view), self._to_screen(x1, y1, view)) for v in p[:2])
                  for g in shot.figures for (x0, y0, x1, y1), _ in self._shapes(g)]
        side = 1 if f is None or f.facing == 'r' else -1
        best = None
        for width, most in ((.3, 3), (.22, 4), (.16, 5)):          # narrower and taller where faces crowd the top
            lines, size = ink.fit_text(bubble.text, lang, width * w, most, round(.04 * h), min_size=round(.028 * h))
            bw = max(ink.text_width(line, lang, size) for line in lines) + 1.6 * size
            bh = len(lines) * 1.25 * size + 1.1 * size
            pad, edge = .02 * h, (.55 + .4) * size                       # clear of faces; corner radius + tail
            for y0 in np.arange(.03 * h, min(.76 * h, my - .04 * h) - bh, .015 * h):     # a tail long enough to read
                for x0 in np.arange(.02 * w, .98 * w - bw, .01 * w):
                    box = (x0, y0, x0 + bw, y0 + bh)
                    if any(_overlap(box, (a - pad, b - pad, c + pad, d + pad), 0) for a, b, c, d in heads):
                        continue
                    base = min(max(mx, x0 + edge), x0 + bw - edge)
                    tail = math.hypot(base - mx, y0 + bh - my)
                    if mouth is None:                                    # heard off the frame: hug that edge, up top
                        tail = (x0 if mx < w / 2 else w - x0 - bw) + .2 * y0
                    covered = sum(max(0, min(box[2], c) - max(x0, a)) * max(0, min(box[3], d) - max(y0, b))
                                  for a, b, c, d in bodies) / (bw * bh)
                    cost = tail + .25 * h * covered + (.04 * h if (x0 + bw / 2 - mx) * side < 0 else 0)
                    if best is None or cost < best[0]:
                        best = (cost, box, base)
            if best is not None:
                break
        if best is None:
            self._bubbles[bubble] = None
            return None
        _, box, base = best
        if mouth is None:
            tip = (mx, min(box[3] + .03 * h, my))
        else:
            reach = math.hypot(base - mx, box[3] - my)
            tip = (mx + (base - mx) * .012 * h / max(1., reach), my + (box[3] - my) * .012 * h / max(1., reach))
        plan = (mouth, box, tip, base, lines, size, lang, _seed(bubble.text))
        self._bubbles[bubble] = plan
        return plan

    def _bubble_layout(self, shot, bubble, local):
        """(box, tip, scale) on screen: the bubble follows its speaker's mouth under the camera; it pops in with a
        little overshoot and shrinks away at its end."""
        plan = self._bubble_plan(shot, bubble)
        if plan is None:
            return None
        mouth, box, tip, *_ = plan
        dx = dy = 0.
        if mouth is not None:
            sx, sy, _ = self._to_screen(*mouth, self._camera(shot, local))
            rx, ry, _ = self._to_screen(*mouth, list(shot.view))
            dx, dy = sx - rx, sy - ry
        u = (local - bubble.start) / BUBBLE_POP
        if u < 1:
            c = 1.70158
            scale = .4 + .6 * (1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2)
        else:
            scale = min(1., max(0., (bubble.end - local) / BUBBLE_OUT)) ** .5
        return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy), (tip[0] + dx, tip[1] + dy), scale

    @staticmethod
    def shown(bubble, local):
        """How many characters of a bubble's text show: as many as have been spoken, and never fewer than its first
        word, so a bubble is never empty."""
        first = len(bubble.text.split(' ', 1)[0])
        if bubble.times:
            said = sum(1 for t in bubble.times if t <= local + .04)
        else:
            cps = max(TYPE_CPS, len(bubble.text) / max(.4, .55 * (bubble.end - bubble.start)))
            said = int(max(0., local - bubble.start) * cps)
        return min(len(bubble.text), max(first, said))

    def _bubble(self, overlay, shot, bubble, local, cam):
        layout = self._bubble_layout(shot, bubble, local)
        if layout is None or layout[2] <= .05:
            return
        (x0, y0, x1, y1), (tx, ty), scale = layout
        _, box, tip, base, lines, size, lang, seed = self._bubble_plan(shot, bubble)
        image, (ox, oy) = _bubble_shape(round(box[2] - box[0]), round(box[3] - box[1]), round(base - box[0]),
                                        round(tip[0] - box[0]), round(tip[1] - box[1]), size, seed)
        image = image.copy()
        shown = self.shown(bubble, local)
        draw = ImageDraw.Draw(image)
        y = oy + .55 * size
        for line in lines:
            x = ox + .8 * size
            for text, font in ink.font_runs(line[:max(0, shown)], lang, size):
                draw.text((x, y), text, font=font, fill=BUBBLE_INK)
                x += font.getlength(text)
            shown -= len(line) + 1
            y += 1.25 * size
        px, py = ox + tip[0] - box[0], oy + tip[1] - box[1]       # the tail's tip in the image
        if scale != 1:
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                                 Image.Resampling.BICUBIC)
            px, py = px * scale, py * scale
        at = (round(tx - px), round(ty - py))
        overlay.alpha_composite(image, (max(0, at[0]), max(0, at[1])), (max(0, -at[0]), max(0, -at[1])))

    def _title(self, canvas, title, local):
        if local > 4.5:
            return
        w, h = self.size
        alpha = min(1., local / .5) * min(1., (4.5 - local) / .6)
        from . import ink
        size = round(h * .07)
        font = ink.truetype(ink.EN_HAND[0], size, 'story title')
        layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        lines = _wrap(title, font, w * .8, draw)
        y = h * .09
        for line in lines[:2]:
            width = draw.textlength(line, font=font)
            draw.text(((w - width) / 2, y), line, font=font, fill=(27, 27, 27, int(255 * alpha)))
            y += size * 1.2
        canvas.paste(layer, (0, 0), layer)

    def roar_cues(self, shots, start):
        """(absolute time, sound) of on-screen roars: a cub's try is its own small 'cub_roar', an adult's the roar."""
        return sorted({(start + f.cue, 'cub_roar' if f.age in ('baby', 'young') else 'roar')
                       for shot in shots for f in shot.figures
                       if f.pose == 'roar' and f.cue is not None and shot.start - .05 <= f.cue < shot.end})

    def rain(self, shots):
        """Span-local (start, end) stretches whose pages draw rain, neighbouring rainy pages joined."""
        out = []
        for shot in shots:
            if self._raining(shot):
                if out and abs(out[-1][1] - shot.start) < 1e-6:
                    out[-1] = (out[-1][0], shot.end)
                else:
                    out.append((shot.start, shot.end))
        return out


@lru_cache(maxsize=32)
def _bubble_shape(bw, bh, base, tx, ty, size, seed):
    """A hand-drawn speech bubble: a wobbly rounded box with its tail running from ``base`` on the bottom edge to the
    tip (tx, ty), all in box pixels. Returns (image, offset of the box's top-left corner in the image)."""
    k, stroke, r, tail = 3, max(3, round(size * .13)), .55 * size, .4 * size
    corners = ((bw - r, r, -90), (bw - r, bh - r, 0), (r, bh - r, 90), (r, r, 180))
    points = []
    for cx, cy, a0 in corners:
        for i in range(9):
            a = math.radians(a0 + 90 * i / 8)
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        if a0 == 0:                                   # along the bottom edge, right to left: the tail
            points += [(base + tail, bh), (tx, ty), (base - tail, bh)]
    wobbly, run = [], 0.             # a slow wobble along the outline, as if drawn by hand; the tail's tip stays put
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        length = math.hypot(x1 - x0, y1 - y0)
        for i in range(max(1, math.ceil(length / (.4 * size)))):
            u = i / max(1, math.ceil(length / (.4 * size)))
            x, y = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
            calm = min(1., math.hypot(x - tx, y - ty) / size)
            wobbly.append((x + calm * .06 * size * math.sin((run + u * length) / (2.2 * size) + seed),
                           y + calm * .06 * size * math.sin((run + u * length) / (1.7 * size) + 2 * seed)))
        run += length
    margin = stroke + 2
    left, top = min(0, tx) - margin, -margin
    width, height = max(bw, tx) - left + margin, max(bh, ty) - top + margin
    big = Image.new('RGBA', (round(width * k), round(height * k)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    outline = [((x - left) * k, (y - top) * k) for x, y in wobbly]
    draw.polygon(outline, fill=BUBBLE_FILL)
    draw.line(outline + outline[:2], fill=BUBBLE_INK, width=stroke * k, joint='curve')
    image = big.resize((round(width), round(height)), Image.Resampling.LANCZOS)
    return image, (-left, -top)


def _wrap(text, font, width, draw):
    words, lines, line = text.split(), [], ''
    for word in words:
        trial = (line + ' ' + word).strip()
        if draw.textlength(trial, font=font) > width and line:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


@lru_cache(maxsize=32)
def _strip_image(kind, width, height):
    """A page-wide set strip (road, floor, grass) rendered at exactly this pixel size."""
    units = sets.STRIP_UNITS.get(kind, 90)
    raw = sets.strip(kind, round(units * width / max(1, height)), units)
    png = resvg_py.svg_to_bytes(svg_string=raw, width=width, height=height)
    return Image.open(io.BytesIO(bytes(png))).convert('RGBA')


def _overlap(a, b, slack=.004) -> bool:
    """Two (x0, y0, x1, y1) boxes overlap by more than ``slack``."""
    return a[0] < b[2] - slack and b[0] < a[2] - slack and a[1] < b[3] - slack and b[1] < a[3] - slack


def _sky_kind(doodle_id) -> str:
    """'sun', 'moon' or the doodle itself: a sky shows one of each."""
    return next((kind for kind in ('sun', 'moon') if re.search(rf'(?:^|_){kind}(?:_|$)', doodle_id)), doodle_id)


def _sky(doodle_id) -> bool:
    """Clouds, sun, moon and stars hang in the sky; they never stand on the ground."""
    return doodle_id in SKY_IDS or bool(re.search(r'cloud|moon|(?<![a-z])sun(?!flower)|star(?!fish)|rainbow|lightning|comet',
                                                  doodle_id))


def _animal(doodle_id) -> bool:
    entry = library.catalog().get(doodle_id) or {}
    if entry.get('creature'):
        return True
    return entry.get('category') in ('Animals & Nature', 'animals') and not re.search(
        r'tree|plant|flower|leaf|herb|seedling|cactus|blossom|rose|tulip|mushroom|shamrock|clover', doodle_id)

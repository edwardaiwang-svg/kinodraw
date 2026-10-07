"""Picture-book story scenes: preset doodle characters on the whiteboard paper.

J's ruling (2026-10-07): story characters are full-body preset doodles from the picture library ("regress to the
preset doodles instead of inventing entirely new sprites locally"), never the procedural creature rig or a human
figure standing in for an animal. Library doodles keep their own colours.

Each scene span is cut into shots, one per narrated sentence, timed by the narration's character times. A shot stages
who the sentence puts on stage (named, pronoun or kin references), in poses read from its verbs, with the animals
and setting it names. Special shots: a parent's roar lesson seen from the cub's point of view, a push into a
character's eyes when the line is about them, and a carrier holding the smaller doodle at its carry anchor.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import resvg_py
from defusedxml.ElementTree import fromstring
from PIL import Image, ImageDraw, ImageFont

from .. import library
from ..director.v3.story import SKY_IDS, Reader, story_picture, titled
from .creatures.actions import Action, action_pose

ROAR_SECONDS = 2.4
# Page changes never ghost two pictures (J's jungle, 2026-10-07): a new set arrives behind a short slanted wipe
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
         'crocodile': .14, 'elephant': .34, 'giraffe': .4}
ARBOREAL = {'monkey', 'bird', 'parrot', 'owl'}
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
}
NATIVE_RIGHT = {'fl_monkey', 'fl_snake', 'fl_parrot'}
FRONT = {'fl_lion', 'fl_frog', 'fl_owl', 'fl_fox', 'fl_ant'}
FACE_FALLBACK = {'lion': 'fl_lion', 'tiger': 'fl_tiger_face', 'cat': 'fl_cat_face', 'dog': 'fl_dog_face',
                 'fox': 'fl_fox', 'monkey': 'fl_monkey_face', 'cow': 'fl_cow_face', 'mouse': 'fl_mouse_face',
                 'rabbit': 'fl_rabbit_face', 'horse': 'fl_horse_face', 'frog': 'fl_frog', 'owl': 'fl_owl'}
HUMAN = {'human', 'boy', 'girl', 'man', 'woman'}
HUMAN_FIGURE = {'boy': 'fl_boy', 'girl': 'fl_girl', 'man': 'fl_man_standing', 'woman': 'fl_woman_standing'}
JUNGLE = ('monkey', 'elephant', 'antelope', 'warthog', 'frog', 'bird')
SPECIES_BASE = {'lioness': ('lion', 'female'), 'tigress': ('tiger', 'female'), 'kitten': ('cat', None),
                'puppy': ('dog', None)}


# ------------------------------------------------------------------ doodles
def _creatures():
    try:
        from ..library import creatures
    except ImportError:
        return None
    return creatures if hasattr(creatures, 'best_preset') else None


def meta(doodle_id) -> dict:
    """Preset metadata (pose, facing, size, ground_y, anchors) recorded with a creature doodle; {} otherwise."""
    entry = library.catalog().get(doodle_id) or {}
    return entry.get('creature') or {}


@lru_cache(maxsize=512)
def preset(species, age='adult', sex=None, pose='stand', facing='r', marks=()):
    """(doodle id, mirror) for a cast member's pose. Presets first; then a full-body library doodle of the same
    species. An animal never resolves to a human figure; a person resolves to a person."""
    base, implied = SPECIES_BASE.get(species, (species, None))
    sex = implied or (sex if sex in ('male', 'female') else None)
    if base in HUMAN:
        return HUMAN_FIGURE.get(base, 'fl_person_standing'), False
    chosen = _choose(base, age, sex, pose, facing, marks)
    if chosen:
        return chosen, False
    if pose not in ('stand', 'face'):
        chosen = _choose(base, age, sex, 'stand', facing, marks)
        if chosen:
            return chosen, False
    doodle = FALLBACK.get(base) or FALLBACK.get(species)
    if doodle is None or library.resolve(doodle) is None:
        doodle = 'fl_paw_prints'
    native = 'r' if doodle in NATIVE_RIGHT else 'f' if doodle in FRONT else 'l'
    return doodle, native not in ('f', facing)


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
    if not did or info.get('species') not in (species, mod.RELATED.get(species)) or library.resolve(did) is None:
        return None
    return did


@lru_cache(maxsize=64)
def face(species, age='adult', sex=None, marks=()):
    """A head close-up doodle for an eye shot, or None."""
    base, implied = SPECIES_BASE.get(species, (species, None))
    did = _choose(base, age, implied or sex, 'face', 'f', marks)
    if did and meta(did).get('pose', '').startswith('face_'):
        return did
    did = FACE_FALLBACK.get(base)
    return did if did and library.resolve(did) else None


@lru_cache(maxsize=256)
def _svg(doodle_id):
    path = library.resolve(doodle_id)
    raw = path.read_text(encoding='utf-8')
    root = fromstring(raw)
    box = root.get('viewBox')
    if box:
        _, _, w, h = (float(v) for v in box.replace(',', ' ').split())
    else:
        w, h = float(root.get('width', 300)), float(root.get('height', 300))
    return raw, w, h


@lru_cache(maxsize=160)
def sprite(doodle_id, height, mirror=False):
    """RGBA doodle at an exact pixel height, in its own colours (never recoloured), and its scale."""
    raw, w, h = _svg(doodle_id)
    height = max(8, int(height))
    width = max(8, round(w * height / h))
    png = resvg_py.svg_to_bytes(svg_string=raw, width=width, height=height)
    image = Image.open(io.BytesIO(bytes(png))).convert('RGBA')
    if mirror:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return image


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


def _seed(text):
    return (sum(ord(c) * (i + 1) for i, c in enumerate(str(text))) % 997) / 997 * math.tau


class Storybook:
    """Shot lists and frames for a story plan's scenes."""

    def __init__(self, plan, by_id, timeline, size, paper, title=''):
        self.cast = {c['id']: c for c in plan['cast']}
        self.reader = Reader(plan['cast'])
        self.by_id, self.tl, self.size = by_id, timeline, size
        self.paper_image = paper
        self.title = title
        self.first = plan['scenes'][0]['beat_ids'][0] if plan['scenes'] else None
        self.facing = {}
        self._paper = {}

    # ---------------- planning
    def prepare(self, spec, start, end):
        """Shots for one scene span (local seconds), from its beats' sentences and the plan's cast."""
        shots = []
        staged = [e['ref'] for e in spec['elements'] if e['kind'] == 'cast' and e['ref'] in self.cast]
        pictures = [e['ref'] for e in spec['elements'] if e['kind'] == 'picture' and story_picture(e['ref'])]
        for bid in spec['beat_ids']:
            beat, timing = self.by_id[bid], self.tl['beats'][bid]
            lines = self.reader.read(bid, beat['spoken'], beat.get('section'))
            times = timing['char_times']
            at = lambda char: timing['start'] - start + (times[min(char, len(times) - 1)] if times else 0.)
            for i, line in enumerate(lines):
                begin = timing['start'] - start if i == 0 else at(line.start)
                shot = self._shot(line, begin, at, staged, pictures, spec)
                if shots and shot.start - shots[-1].start < 1.1 and not (shot.lesson or shot.eyes):
                    # Very short sentences share the previous picture instead of flashing a new one.
                    previous = shots[-1]
                    for f in shot.figures:
                        if f.pose != 'stand' and f.cue is not None:
                            match = next((g for g in previous.figures if g.key == f.key), None)
                            if match and match.pose == 'stand':
                                match.pose, match.cue = f.pose, f.cue
                    continue
                shots.append(shot)
        if not shots:
            shots.append(Shot(0., end - start))
        for shot, following in zip(shots, shots[1:]):
            shot.end = following.start
        shots[0].start = 0.
        shots[-1].end = end - start
        if spec['beat_ids'][0] == self.first and titled(self.title, self.by_id[self.first]['spoken']):
            shots[0].title = self.title         # the title once, on the first page
        return shots

    def _cast_figure(self, cid, **kw):
        c = self.cast[cid]
        return Figure(cid, c['species'], c['age'], c['sex'], tuple(c.get('marks') or ()),
                      height=min(.6, ADULT_HEIGHT * max(.45, min(1.4, c.get('size', 1.)))),
                      phase=_seed(cid), **kw)

    def _shot(self, line, begin, at, staged, pictures, spec):
        shot = Shot(begin, begin)
        present = [cid for cid in line.present if cid in self.cast] or [c for c in staged[:3]]
        if not present and not line.crowd and not line.props:
            present = staged[:3]
        figures = [self._cast_figure(cid) for cid in present[:4]]
        for f in figures:
            pose = line.poses.get(f.key)
            if pose:
                f.pose, f.cue = pose[0], at(pose[1])
        shot.lesson = line.roar_lesson
        layout = self._layout_lesson if shot.lesson else self._layout
        layout(figures, line)
        shot.figures = figures
        if line.eyes and line.eyes in self.cast:
            target = next((f for f in figures if f.key == line.eyes), None)
            if target:
                shot.eyes, shot.eyes_at = target, at(line.eyes_at)
        props = list(dict.fromkeys([p for p in line.props if not _sky(p)] +
                                   [p for p in pictures if not _sky(p) and p not in line.props
                                    and not _animal(p)]))[:2]
        sky = list(dict.fromkeys(line.sky + [p for p in pictures if _sky(p)]))[:2]
        atmosphere = spec['atmosphere']['kind']
        if atmosphere in ('night_stars', 'shooting_star', 'fog_with_shooting_star') and 'fl_crescent_moon' not in sky:
            sky.append('fl_crescent_moon')
        if atmosphere == 'rain' and 'fl_cloud_with_rain' not in sky:
            sky.append('fl_cloud_with_rain')
        if atmosphere in ('dawn', 'rays') and 'fl_sun' not in sky:
            sky.append('fl_sun')
        if not (figures or line.crowd or props):
            props = ['fl_palm_tree', 'fl_deciduous_tree']      # never an empty page
        sides = [.12, .88]
        for i, doodle in enumerate(props):
            tall = doodle in ('fl_deciduous_tree', 'fl_palm_tree', 'fl_evergreen_tree', 'fl_mountain')
            shot.props.append((doodle, sides[i], GROUND - .02, .5 if tall else .3))
        for i, doodle in enumerate(sky[:2]):
            shot.sky.append((doodle, (.83, .2)[i], .15, .16))
        shot.atmosphere = atmosphere
        self._crowd(shot, line, figures)
        return shot

    def _remember(self, f):
        self.facing[f.key] = f.facing

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
        # Adults on the outside facing in; a cub in front of them, between.
        babies = [f for f in figures if f.age == 'baby']
        adults = [f for f in figures if f.age != 'baby']
        order = adults[:1] + babies + adults[1:] if babies and len(adults) >= 2 else adults + babies
        slots = {2: (.32, .68), 3: (.24, .5, .76), 4: (.18, .4, .62, .84)}[min(4, n)]
        for f, x in zip(order, slots):
            f.x = x
            f.facing = 'r' if x < .5 else 'l' if x > .5 else ('r' if not adults else 'l')
            if f.age == 'baby':
                f.depth = 2
        if walking:
            for f in walking:
                f.facing, f.travel = 'r', .1
        for f in figures:
            if f.pose == 'nuzzle':
                partner = min((g for g in figures if g is not f), key=lambda g: abs(g.x - f.x))
                f.facing = 'r' if partner.x > f.x else 'l'
                f.x += (partner.x - f.x) * .35
            self._remember(f)

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
        doodle = preset(f.species, f.age, f.sex, 'stand', f.facing, f.marks)[0]
        left, top, right, bottom = _bbox(doodle)
        _, sw, sh = _svg(doodle)
        w, h = self.size
        return f.height / max(.05, bottom - top) * (right - left) * sw / sh * h / w / 2

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
        walkers = [m for m in members if m not in climbers]
        for i, m in enumerate(climbers):
            m.x, m.ground = trees[0] - .04 + .05 * (i % 3), .44 + .05 * (i % 2)
        if leader is not None:
            # A procession: the leader in front, everyone else in a line behind on the path.
            leader.x = .6
            x = leader.x - self._half_width(leader)
            for m in walkers:
                half = self._half_width(m)
                x -= half + .015
                m.x, m.ground, m.facing, m.travel, m.pose = x, GROUND - .03, leader.facing, leader.travel, leader.pose
                x -= half
            behind = [m for m in walkers if m.x - self._half_width(m) < .02][:3]
            walkers[:] = [m for m in walkers if m.x - self._half_width(m) >= .02] + behind
            for i, m in enumerate(behind):            # the tail of the line walks on the path further back
                m.height *= .75
                m.x, m.ground = .56 + .09 * i, GROUND - .17
        else:
            blocked = [(f.x, self._half_width(f) + .03) for f in figures] + \
                      [(x, .07) for _, x, *_ in shot.props]
            slots = [x for x in (.08, .2, .32, .44, .56, .68, .8, .92)]
            free = [x for x in slots if all(abs(x - c) > r + .04 for c, r in blocked)]
            back = []
            if len(walkers) > len(free):
                back, walkers = walkers[len(free):], walkers[:len(free)]
            if walkers and len(walkers) < len(free):
                free = [free[round(j * (len(free) - 1) / max(1, len(walkers) - 1))] for j in range(len(walkers))] \
                    if len(walkers) > 1 else [free[len(free) // 2]]
            for m, x in zip(walkers, free):
                m.x, m.ground = x, GROUND - .04
            for i, m in enumerate(back):               # those who do not fit stand further back, smaller
                m.height *= .7
                m.x, m.ground = .14 + .72 * (i + .5) / len(back), GROUND - .17
            subject = next(iter(figures), None)
            for i, m in enumerate(members):
                m.facing = ('r' if subject.x > m.x else 'l') if subject else ('r' if i % 2 else 'l')
        members = climbers + walkers + [m for m in members if m not in climbers and m not in walkers]
        if leader is not None:
            members = climbers + walkers
        for m in members:
            half = self._half_width(m)
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
        return (tuple(shot.props), tuple(d for d, *_ in shot.sky), shot.atmosphere, shot.lesson, bool(shot.title))

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
        """(doodle, mirror) for the figure's pose at this time."""
        pose = f.pose
        if f.cue is not None and local < f.cue and pose in ('roar', 'look_up', 'scared', 'bow', 'happy', 'nuzzle'):
            pose = 'stand'
        if pose == 'roar' and f.cue is not None and local > f.cue + ROAR_SECONDS:
            pose = 'stand'
        name = {'look': 'stand', 'happy': 'stand', 'nuzzle': 'stand', 'bow': 'stand'}.get(pose, pose)
        if name == 'walk':
            stride = int((local + f.phase) * 4) % 2
            doodle, mirror = preset(f.species, f.age, f.sex, 'walk2' if stride else 'walk', f.facing, f.marks)
            if meta(doodle).get('pose') in ('walk1', 'walk2'):
                return doodle, mirror, pose
            return preset(f.species, f.age, f.sex, 'walk', f.facing, f.marks) + (pose,)
        return preset(f.species, f.age, f.sex, name, f.facing, f.marks) + (pose,)

    def _draw(self, shot, local):
        w, h = self.size
        u = min(1., max(0., (local - shot.start) / max(.01, shot.end - shot.start)))
        cam = [.5, .5, 1. + .035 * u]                      # gentle push in
        shake = 0.
        roaring = [f for f in shot.figures if f.pose == 'roar' and f.cue is not None]
        for f in roaring:
            p = action_pose(Action('roar', f.cue, ROAR_SECONDS, 1.), local)
            shake = max(shake, p.screen_shake)
        if shot.eyes is not None:
            cam = self._eye_camera(shot, local, cam)
        cam[0] += shake * .0016 * math.sin(local * 39)
        cam[1] += shake * .0016 * math.sin(local * 31)
        canvas = self._page(cam)
        overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        for doodle, x, y, height in shot.sky:
            bob = .006 * math.sin(local * .9 + x * 7)
            self._paste(overlay, doodle, False, x, y + height / 2 + bob, height, cam, parallax=.4)
        for doodle, x, ground, height in shot.props:
            self._paste(overlay, doodle, False, x, ground, height, cam)
        if getattr(shot, 'atmosphere', 'none') in ('fog', 'fog_with_shooting_star'):
            self._fog(overlay, local)
        if any(f.crowd for f in shot.figures) or shot.figures:
            self._shadows(overlay, shot, local, cam)
        effects = []
        for f in sorted(shot.figures, key=lambda f: f.depth):
            effects += self._figure(overlay, f, shot, local, cam)
        if getattr(shot, 'atmosphere', 'none') == 'rain' or any(d == 'fl_cloud_with_rain' for d, *_ in shot.sky):
            self._rain(overlay, local)
        for effect in effects:
            effect(overlay)
        face = self._face_overlay(shot, local)
        canvas.paste(overlay, (0, 0), overlay)
        if face is not None:
            image, alpha = face
            canvas = Image.blend(canvas, image, alpha)
        if shot.title:
            self._title(canvas, shot.title, local)
        return canvas

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
               anchor_y=1., pin=None, reference=None):
        """Paste a doodle with its feet (alpha bottom) at (x, ground); returns its screen box.

        ``height`` is the drawn height of ``reference`` (the character's standing preset) when given, so all of a
        character's poses share one scale; ``pin`` is a point of the doodle box (shares) placed at (x, ground)."""
        w, h = self.size
        sx, sy, zoom = self._to_screen(x, ground, cam, parallax)
        left, top, right, bottom = _bbox(doodle, mirror)
        px = max(8, round(_box(doodle, height, reference) * h * zoom))
        if px > 6 * h:
            return None
        step = max(2, int(px * .015))
        px = round(px / step) * step        # a bounded set of cached sizes during camera pushes
        image = sprite(doodle, px, mirror)
        if squash:
            image = image.resize((max(1, round(image.width / (1 - squash))), max(1, round(image.height * (1 - squash)))),
                                 Image.Resampling.BICUBIC)
        iw, ih = image.size
        foot_x, foot_y = (left + right) / 2 * iw, (top + (bottom - top) * anchor_y) * ih
        if pin is not None:
            foot_x, foot_y = pin[0] * iw, pin[1] * ih
        if rotate:
            pad = round(max(iw, ih) * .25)
            padded = Image.new('RGBA', (iw + 2 * pad, ih + 2 * pad), (0, 0, 0, 0))
            padded.paste(image, (pad, pad))
            image = padded.rotate(rotate, resample=Image.Resampling.BICUBIC, center=(foot_x + pad, foot_y + pad))
            foot_x, foot_y = foot_x + pad, foot_y + pad
        at = (round(sx - foot_x), round(sy - foot_y))
        overlay.alpha_composite(image, (max(0, at[0]), max(0, at[1])),
                                (max(0, -at[0]), max(0, -at[1])))
        return at[0], at[1], image.width, image.height

    def _figure(self, overlay, f, shot, local, cam):
        w, h = self.size
        doodle, mirror, pose = self._pose_doodle(f, local)
        u = min(1., max(0., (local - shot.start) / max(.01, shot.end - shot.start)))
        x, ground = f.x, f.ground
        direction = 1 if f.facing == 'r' else -1
        rotate, squash, dy = 0., 0., 0.
        breath = math.sin(local * 2.6 + f.phase)
        squash = .012 * breath
        if pose in ('stand', 'look', 'sit', 'lie', 'sleep', 'look_up'):   # a resting figure shifts its weight
            rotate = direction * (.8 if pose == 'sleep' else 2.2) * math.sin(local * 1.4 + f.phase)
        if pose in ('walk', 'run', 'carry') or (f.travel and pose != 'stand'):
            rate = 2.2 if pose == 'run' else 1.4
            step = abs(math.sin(math.pi * rate * (local + f.phase)))
            dy -= (.012 if pose == 'run' else .007) * step
            rotate = direction * -(4 if pose == 'run' else 2) * math.sin(math.tau * rate * (local + f.phase))
            x += direction * f.travel * (u * u * (3 - 2 * u))
        if pose == 'scared':
            x += .004 * math.sin(local * 44 + f.phase)
        if pose == 'bow':
            rotate = direction * -9 * min(1., max(0., (local - (f.cue or shot.start)) / .6))
        if pose == 'happy':
            dy -= .02 * abs(math.sin(local * 5 + f.phase)) * (local > (f.cue or 0))
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
        self._paste(overlay, doodle, mirror, x, ground + dy, f.height, cam, rotate=rotate, squash=squash,
                    reference=reference)
        effects = []
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
            effects.append(lambda o, fig=f, x0=x: self._paste(
                o, 'fl_zzz', fig.facing == 'l', x0 + (.06 if fig.facing == 'r' else -.06) * fig.height / ADULT_HEIGHT,
                fig.ground - fig.height * .75 + .01 * math.sin(local * 2), fig.height * .3, cam))
        return effects

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
            u = min(1., max(0., (local - shot.start) / max(.01, shot.end - shot.start)))
            x = f.x + (1 if f.facing == 'r' else -1) * f.travel * (u * u * (3 - 2 * u))
            sx, sy, zoom = self._to_screen(x, f.ground, cam)
            rx, ry = f.height * h * zoom * .55, f.height * h * zoom * .06
            draw.ellipse((sx - rx, sy - ry, sx + rx, sy + ry), fill=(60, 60, 50, 34))

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
        self._paste(page, doodle, False, .5, .5 + .36 * push, .72 * push, [.5, .5, 1.], anchor_y=1.)
        return page.convert('RGB'), alpha

    def _title(self, canvas, title, local):
        if local > 4.5:
            return
        w, h = self.size
        alpha = min(1., local / .5) * min(1., (4.5 - local) / .6)
        from . import ink
        size = round(h * .07)
        font = ImageFont.truetype(ink.EN_HAND[0], size)
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
        """Absolute times of on-screen roars, for the synthesized roar."""
        return sorted({start + f.cue for shot in shots for f in shot.figures if f.pose == 'roar' and f.cue is not None
                       and shot.start - .05 <= f.cue < shot.end})


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

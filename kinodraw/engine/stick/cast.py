"""Library pictures of people, redrawn as our own stick figures.

The doodle library draws people in other styles (yellow emoji faces with noses, detailed skin and clothes). Next
to the white-headed stick figures that mixes two visual languages in one frame, so in this look a picture of a
person becomes a stick figure in the same line and palette: a pilot or a police officer gets a cap, a king a
crown, a soldier the helmet of the story's era, a farmer a straw hat; a running or shrugging person runs or
shrugs; an emoji face becomes a figure wearing that feeling. A picture of a group becomes a small group (a family:
two grown-ups and two children). The parachute emoji, the one object picture with a person in it, becomes our
figure hanging under a striped canopy.

Only a picture the figure says all of is redrawn. One whose point is a thing we cannot draw on a stick figure (a
wheelchair, a bike, a bed, an astronaut's suit, a vampire, red arrow signs, a medical mask, a money mouth, a
sleeping face) keeps its library drawing, since a plain smiling figure in its place would say something else.

``kind(doodle_id)`` says whether a doodle is one of these; ``image(...)`` draws it to fit a box, in boil drawing
``variant`` (0-2), like ``paint.doodle``.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace
from functools import lru_cache

from PIL import Image, ImageDraw

from ...library import catalog
from . import cues, rig
from .palette import PALETTE

PERSON = re.compile(r'\b(person|people|man|woman|men|women|boy|girl|child|baby|pilot|detective|guard|judge|farmer|'
                    r'cook|artist|astronaut|firefighter|mechanic|student|teacher|technologist|singer|skier|snowboarder|'
                    r'prince|princess|santa|claus|elf|fairy|genie|mage|vampire|zombie|troll|ninja|superhero|'
                    r'supervillain|merman|mermaid|merperson|worker|officer|older|busts?)\b', re.I)
GROUP = re.compile(r'\b(people|men|women|busts|family|couple|hugging|wrestling|teammates|group)\b', re.I)
NOT_HUMAN = re.compile(r'\b(cat|monkey|alien|robot|ghost|skull|poo|goblin|ogre|devil|imp|horns|moon|sun|wind)\b', re.I)
POSES = [('run', r'running'), ('walk', r'walking'), ('shrug', r'shrugging'), ('wave', r'raising hand|waving'),
         ('angry', r'angry|pouting|rage|steam|symbols on mouth|gesturing no'),
         ('cheer', r'tears of joy'),
         ('sad', r'cry|sad|disappointed|frown|pensive|weary|tired|anguished|worried|downcast|persevering|confounded|'
                 r'unamused|pleading|tears|facepalming'),
         ('think', r'thinking|monocle|raised eyebrow|diagonal|confused|peeking'),
         ('cheer', r'grinning|smiling|beaming|joy|laugh|partying|star-struck|heart|halo|kiss|savoring|tongue|zany|'
                   r'winking|hugging|dancing|cartwheeling')]
SHOCK = re.compile(r'fear|scream|anxious|astonished|hushed|flushed|open mouth|shaking|grimacing|spiral', re.I)
CAP = re.compile(r'\b(pilots?|police|officers?|guards?|detectives?|cops?|captains?|security|mechanics?)\b', re.I)
CROWN = re.compile(r'\b(princes?|princess(?:es)?|royal|crown)\b', re.I)
FAMILY = re.compile(r'\b(family|parents|children|kids)\b', re.I)
STRAIGHT = re.compile(r'\b(neutral|expressionless)\b', re.I)
SERIOUS = ('open', 'flat', 'flat')                       # compose.SERIOUS: a straight face
# What a stick figure cannot show: the thing, place or costume a picture is about. These keep the library drawing.
KEEP = re.compile(r'bik|wheelchair|cane|\bbed\b|bath|surf|swim|rowing|polo|golf|ski|snowboard|climb|ball|fencing|'
                  r'haircut|massage|feeding|lotus|steamy|levitat|bowing|kneeling|tipping|gesturing ok|juggl|weights|'
                  r'astronaut|firefight|\bcook|judge|claus|elf|fairy|genie|mage|vampire|zombie|troll|ninja|mer(?:man|'
                  r'maid|person|people)|super(?:hero|villain)|pregnant|turban|veil|headscarf|skullcap|tuxedo|angel|'
                  r'bunny|wrestl|sign|connected', re.I)
PROPS = {'fl_parachute': 'parachute'}
SHIRTS = ('blue', 'orange', 'green', 'purple', 'yellow', 'sky', 'brown', 'pink')


@lru_cache(maxsize=4096)
def kind(doodle_id: str) -> str | None:
    """'person', 'group', 'parachute' or None (a picture that shows no one)."""
    if doodle_id in PROPS:
        return PROPS[doodle_id]
    e = catalog().get(doodle_id)
    if e is None:
        return None
    desc, cat = e.get('desc', ''), e.get('category')
    if KEEP.search(desc):
        return None
    if cat == 'people':                                   # the curated library's own group drawings
        return 'group'
    if cat == 'People & Body' and PERSON.search(desc):
        return 'group' if GROUP.search(desc) else 'person'
    if cat == 'Smileys & Emotion' and re.search(r'\bface\b', desc) and not NOT_HUMAN.search(desc) and (
            SHOCK.search(desc) or STRAIGHT.search(desc) or _pose(desc) != 'stand'):   # only a feeling we can wear
        return 'person'
    return None


def _pose(desc: str) -> str:
    return next((p for p, rx in POSES if re.search(rx, desc, re.I)), 'stand')


def figure_for(doodle_id: str, words: str = '', era: str = 'modern', face=None, height: float = 400.,
               seed: int = 0) -> rig.Figure:
    """The stick figure standing in for a picture of one person (``words``: its label, for the costume)."""
    e = catalog().get(doodle_id) or {}
    desc = e.get('desc', '')
    pose = _pose(desc)
    own = None
    if SHOCK.search(desc):
        own = ('wide', 'raised', 'o')
    elif STRAIGHT.search(desc):
        own = SERIOUS
    elif pose == 'stand':
        own = face
    text = f'{desc} {words}'
    hat = cues.costume(text, 'en', era) or ('crown' if CROWN.search(text) else 'cap' if CAP.search(text) else None)
    return rig.Figure(pose=pose, height=height, facing=1 if 'facing right' in desc else -1, face=own, hat=hat,
                      shirt=SHIRTS[seed % len(SHIRTS)], seed=seed)


def _fit(draw_at, box_w, box_h):
    """Draw at a trial height, then again at the height that fits the box."""
    h = box_h * .95
    img = draw_at(h)
    s = min(1., box_w / img.width, box_h / img.height) * .98
    return draw_at(h * s) if s < .999 else img


def _group(heights, face, seed, variant, k=0):
    figs = []
    for i, f in enumerate(heights):
        figs.append(rig.draw(rig.Figure(pose='stand' if i % 2 == 0 else 'talk', height=f, facing=1 if i % 2 else -1,
                                        face=face, shirt=SHIRTS[(seed + i) % len(SHIRTS)], seed=seed + i), k, variant))
    gap = max(heights) * .42
    xs = [i * gap for i in range(len(figs))]
    left = min(x - d.origin[0] for x, d in zip(xs, figs))
    right = max(x - d.origin[0] + d.image.width for x, d in zip(xs, figs))
    top = min(-d.origin[1] for d in figs)
    bottom = max(-d.origin[1] + d.image.height for d in figs)
    img = Image.new('RGBA', (int(math.ceil(right - left)) + 2, int(math.ceil(bottom - top)) + 2), (0, 0, 0, 0))
    for x, d in sorted(zip(xs, figs), key=lambda xd: -xd[1].image.height):
        img.alpha_composite(d.image, (int(round(x - d.origin[0] - left)), int(round(-d.origin[1] - top))))
    return img


def _parachute(h, seed, variant, face):
    fig = rig.Figure(pose='cheer', height=h * .5, facing=1, face=face, shirt=SHIRTS[seed % len(SHIRTS)], seed=seed)
    dr = rig.draw(fig, 0, variant)
    cw, chh = h * .62, h * .26                          # canopy width and height
    W = int(max(cw, dr.image.width) + 8)
    top = 4
    gap = h * .14
    Hh = int(top + chh + gap + dr.image.height + 4)
    img = Image.new('RGBA', (W, Hh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W / 2
    lw = max(2, int(round(rig.line_width(h * .5) * 1.1)))
    fx, fy = cx - dr.image.width / 2, top + chh + gap
    hands = [(fx + x, fy + y) for x, y in dr.hands]
    stripes = 6
    for i in range(stripes):                            # the canopy: a dome of alternating stripes
        a0, a1 = math.pi + math.pi * i / stripes, math.pi + math.pi * (i + 1) / stripes
        pts = [(cx, top + chh)] + [(cx + cw / 2 * math.cos(a), top + chh + chh * math.sin(a))
                                   for a in [a0 + (a1 - a0) * j / 8 for j in range(9)]]
        d.polygon(pts, fill=PALETTE['orange' if i % 2 == 0 else 'white'] + (255,))
    rim = [(cx + cw / 2 * math.cos(a), top + chh + chh * math.sin(a)) for a in
           [math.pi + math.pi * j / 32 for j in range(33)]]
    d.line(rim + [rim[0]], fill=(0, 0, 0, 255), width=lw, joint='curve')
    for i, x in enumerate((cx - cw / 2, cx - cw / 6, cx + cw / 6, cx + cw / 2)):   # lines down to the hands
        hx, hy = hands[0] if (x > cx) == (hands[0][0] > hands[1][0]) else hands[1]
        d.line([(x, top + chh), (hx, hy)], fill=(0, 0, 0, 255), width=max(1, lw - 1))
    img.alpha_composite(dr.image, (int(round(fx)), int(round(fy))))
    return img


def image(doodle_id: str, box: tuple, variant: int = 0, words: str = '', era: str = 'modern', face=None,
          seed: int = 0) -> Image.Image:
    """The cast picture for ``doodle_id`` fitted inside ``box`` (w, h), boil drawing ``variant``."""
    return _image(doodle_id, int(box[0]), int(box[1]), int(variant) % 3, words, era, face, seed)


@lru_cache(maxsize=256)
def _image(doodle_id, bw, bh, variant, words, era, face, seed):
    what = kind(doodle_id)
    if what == 'parachute':
        return _fit(lambda h: _parachute(h, seed, variant, face), bw, bh)
    if what == 'group':
        desc = (catalog().get(doodle_id) or {}).get('desc', '')
        rel = (1., .96, .62, .56) if FAMILY.search(f'{desc} {words}') else \
            ((1., .97) if re.search(r'hugging|couple|wrestling', desc) else (1., .94, .98))
        return _fit(lambda h: _group([h * r for r in rel], face, seed, variant), bw, bh)
    fig = figure_for(doodle_id, words, era, face, 400., seed)
    return _fit(lambda h: rig.draw(replace(fig, height=h), 0, variant).image, bw, bh)

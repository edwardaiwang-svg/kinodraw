"""People drawn for one video at render time, in the look each cast member keeps for the whole video.

The library's people presets come in a few fixed looks (child, adult, elder; a handful of outfits). A story needs
more: a teenager, a middle-aged parent, a cook's apron or an anchor's suit, and never two cast members in the same
clothes. A person here is the same generator (``library.creaturegen.human``) run for one look; the look is spelled
out in the doodle id, so any process can draw it again from the id alone:

    cr_person_<sex>_<age>_<outfit>_<tone>_<top>_<bottom>_<hair>_<hair style>_<accent>_<flags>_<pose>_<facing>

(colours as six hex digits; flags: g glasses, b beard, c cane, d dress, x none). Building one look (every pose and
face) takes about a quarter of a second and is cached.
"""
from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache

PREFIX = 'cr_person_'
AGES = ('child', 'teen', 'adult', 'middle', 'elder')
OUTFITS = ('casual', 'villager', 'teacher', 'explorer', 'king', 'queen', 'princess', 'apron', 'suit', 'labcoat',
           'uniform', 'worker')
SKIN = {'light': '#F6D5BE', 'tan': '#D9A07A', 'brown': '#8D5A3B'}
# Clothes and hair colours a video's people are dressed in, far enough apart to tell people apart at a glance.
TOPS = ('#5B8DD6', '#D9822B', '#6E9E4A', '#C0504D', '#8E6BBF', '#2E9C9A', '#E0B33A', '#D46A9A', '#4A6FA5',
        '#9C6B3E')
BOTTOMS = ('#3D4A5C', '#5A4636', '#2F3B2F', '#4B3F5E', '#6B5440', '#33475B')
HAIRS = ('#3B2B24', '#1F1A17', '#7A4A26', '#C98A3A', '#5A3A26', '#A0522D')
ELDER_HAIRS = ('#E6E2DA', '#D9D6D0', '#C9C5BE')
# A role's own colours: an anchor's dark suit, a lab coat's white, a uniform's navy.
ROLE_TOPS = {'suit': ('#2E3B55', '#3A3A44', '#4A4F5C'), 'labcoat': ('#F4F4F0',), 'uniform': ('#24385E', '#2F4A3A'),
             'teacher': ('#F1EEE6', '#3F7FD0', '#C9D8EC')}
LOOK_RE = re.compile(r'^cr_person_(?P<sex>male|female)_(?P<age>[a-z]+)_(?P<outfit>[a-z]+)_(?P<tone>[a-z]+)_'
                     r'(?P<top>[0-9a-f]{6})_(?P<bottom>[0-9a-f]{6})_(?P<hair>[0-9a-f]{6})_(?P<style>[a-z]+)_'
                     r'(?P<accent>[0-9a-f]{6})_(?P<flags>[a-z]+)_(?P<rest>.+)$')


def greying(hair, share=.35):
    """A hair colour going grey: middle age."""
    a = [int(hair.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    return '#%02X%02X%02X' % tuple(round(x + (y - x) * share) for x, y in zip(a, (0x9A, 0x96, 0x8F)))


def distance(a, b):
    """How far apart two colours are (RGB, 0-441)."""
    x, y = ([int(c.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)] for c in (a, b))
    return sum((p - q) ** 2 for p, q in zip(x, y)) ** .5


def look_key(sex, age, outfit, tone, top, bottom, hair, style, accent, flags='x'):
    """The id prefix of one look (without the pose and facing)."""
    hexes = [str(c).lstrip('#').lower() for c in (top, bottom, hair, accent)]
    return f'{PREFIX}{sex}_{age}_{outfit}_{tone}_{hexes[0]}_{hexes[1]}_{hexes[2]}_{style}_{hexes[3]}_{flags or "x"}'


def is_person(doodle_id) -> bool:
    return str(doodle_id or '').startswith(PREFIX)


@lru_cache(maxsize=64)
def _build(key):
    """{pose id suffix: (svg, meta)} for every pose and face of the look ``key`` spells out, or {}."""
    m = LOOK_RE.match(key + '_stand_r')
    if not m or m['age'] not in AGES or m['outfit'] not in OUTFITS or m['tone'] not in SKIN:
        return {}
    from ..library.creaturegen import build, faces, human
    from ..library.creaturegen.species import Variant
    flags = m['flags']
    skin = SKIN[m['tone']]
    hair = '#' + m['hair']
    accent = '#' + m['accent']
    g = human.Person(age=m['age'], sex=m['sex'], skin=skin, hair=hair, hair_style=m['style'], outfit=m['outfit'],
                     top='#' + m['top'], bottom='#' + m['bottom'], accent=accent, dress='d' in flags,
                     glasses='g' in flags, beard='b' in flags, cane='c' in flags)
    if m['outfit'] == 'worker':
        g = replace(g, bottom=accent)                       # overalls: the bib and the legs one colour
    hat = {'king': 'crown', 'queen': 'crown', 'princess': 'tiara', 'explorer': 'helmet'}.get(m['outfit'], '')
    face = faces.Face('human', skin, '', mane_c=hair, hair_style=m['style'], hat=hat, glasses=g.glasses, beard=g.beard,
                      mark_c=accent)
    v = Variant('human', m['sex'], m['age'], key[len(PREFIX) + len(m['sex']) + len(m['age']) + 2:], genes=g,
                face=face, family='human', plan='human', poses=human.POSES, category='characters', jitter=0)
    out = {}
    for pid, svg, meta in build.render_variant(v):
        suffix = pid[len(f'cr_{v.key}_'):]
        out[suffix] = (svg, meta)
    return out


def entry(doodle_id):
    """(svg text, meta) of a person doodle id, or None when the id spells no look or no pose of it."""
    m = LOOK_RE.match(str(doodle_id or ''))
    if not m:
        return None
    key = doodle_id[:m.start('rest') - 1]
    return _build(key).get(m['rest'])


def svg(doodle_id):
    hit = entry(doodle_id)
    return hit[0] if hit else None


def meta(doodle_id) -> dict:
    """The preset metadata (pose, facing, size, ground_y, anchors) of a person doodle; {} otherwise."""
    hit = entry(doodle_id)
    if not hit:
        return {}
    m = LOOK_RE.match(doodle_id)
    # As a library preset's: who it is (the variant ends in the skin tone), then how it is drawn.
    return {'species': 'human', 'family': 'human', 'sex': m['sex'], 'age': m['age'],
            'variant': f"{m['outfit']}_{m['tone']}", 'marks': [m['outfit']], **hit[1]}

"""Front-view head close-ups with expressive eyes (for 'zoom into his eyes' shots).

Unit: the head radius is 1, the origin is the head centre, y up. One builder covers every mammal
kind; a kind only switches the head outline, ears, muzzle, nose and extra features (mane, horns,
trunk), while the eye/brow/mouth set is shared so expressions read the same across the cast.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import colors as C
from .figure import SW, SW_DETAIL, SW_FINE, Figure
from .rig import V, rot, deg
from .sdf import Circle, Cone, Ellipse, Poly, Tube, Union

EXPRESSIONS = ('neutral', 'scared', 'determined', 'sad', 'happy')


@dataclass
class Face:
    kind: str = 'cat'           # cat dog bear horse cow pig sheep mouse rabbit elephant ape monkey deer hyena
    coat: str = '#E0A54B'
    under: str = '#F6DDB0'
    ear_in: str = '#C98B6B'
    nose_c: str = C.NOSE
    ears: str = 'round'         # round pointed floppy long small none
    ear_size: float = 1.0
    mane: float = 0.0
    mane_c: str = '#8A4F21'
    pattern: str = 'none'       # stripes spots tears zebra giraffe mask
    mark_c: str = '#2A2A2A'
    scar: bool = False
    horns: str = 'none'
    horn_c: str = '#EFE3C8'
    young: bool = False
    iris: str = ''
    tusks: bool = False
    wool: bool = False
    quills: bool = False
    quill_c: str = '#4E3B2C'
    face_c: str = ''            # primate face skin
    beak: str = ''              # birds: cone hook flat
    beak_c: str = '#F2B33D'
    comb: str = ''              # chicken comb + wattle colour
    crest: str = ''             # head crest colour
    disc: str = ''              # owl face disc colour
    hair_style: str = ''        # people: short long bun bald curly ponytail
    hat: str = ''               # people: crown tiara helmet
    glasses: bool = False
    beard: bool = False


def _ears(fc: Face):
    e = fc.ear_size
    out = []
    for s in (-1, 1):
        if fc.ears == 'round':
            out.append((Circle(V(s * .74, .74), .3 * e), Circle(V(s * .74, .74), .16 * e)))
        elif fc.ears == 'pointed':
            tipp = V(s * .8, .8 + .45 * e)
            poly = Poly([V(s * .3, .72), tipp, V(s * .98, .28)], r=.06)
            out.append((poly, Poly([V(s * .42, .66), tipp + V(-s * .04, -.18), V(s * .86, .34)], r=.03)))
        elif fc.ears == 'floppy':
            ear = Ellipse(V(s * .98, .05), .27 * e, .62 * e, s * deg(12))
            out.append((ear, None))
        elif fc.ears == 'long':
            ear = Ellipse(V(s * .38, 1.45), .22 * e, .75 * e, -s * deg(8))
            out.append((ear, Ellipse(V(s * .38, 1.45), .1 * e, .55 * e, -s * deg(8))))
        elif fc.ears == 'small':
            ear = Ellipse(V(s * 1.0, .5), .42 * e, .17 * e, s * deg(25))
            out.append((ear, Ellipse(V(s * 1.02, .5), .26 * e, .08 * e, s * deg(25))))
        elif fc.ears == 'side':
            ear = Circle(V(s * 1.0, .08), .26 * e)
            out.append((ear, Circle(V(s * 1.0, .08), .13 * e)))
        elif fc.ears == 'elephant':
            ear = Union([Ellipse(V(s * 1.22, .05), .72, 1.0, s * deg(8)),
                         Cone(V(s * 1.1, -.6), V(s * 1.0, -1.1), .3, .1)], k=.2)
            out.append((ear, Ellipse(V(s * 1.27, .05), .5, .75, s * deg(8))))
    return out


def _head_shape(fc: Face):
    k = fc.kind
    if k == 'bigcat' and not fc.mane and not fc.young:
        return Union([Ellipse(V(0, .1), .86, .95), Circle(V(-.42, -.4), .45), Circle(V(.42, -.4), .45)], k=.25)
    if k in ('cat', 'bigcat'):
        return Union([Ellipse(V(0, .05), 1.0, .9), Circle(V(-.5, -.35), .5), Circle(V(.5, -.35), .5)], k=.25)
    if k in ('dog', 'hyena', 'fox', 'wolf'):
        return Union([Ellipse(V(0, .1), .92, .88), Ellipse(V(0, -.5), .55, .42)], k=.3)
    if k == 'bear':
        return Union([Circle(V(0, 0), 1.0), Ellipse(V(0, -.5), .55, .42)], k=.25)
    if k in ('horse', 'deer', 'goat', 'giraffe', 'cow', 'sheep', 'antelope'):
        top = Ellipse(V(0, .35), .78, .72)
        snout = Ellipse(V(0, -.75), .55 if k != 'cow' else .7, .48)
        return Union([top, snout, Cone(V(0, .2), V(0, -.7), .62, .5)], k=.3)
    if k == 'pig':
        return Ellipse(V(0, 0), 1.05, .92)
    if k in ('mouse', 'rabbit', 'porcupine'):
        return Union([Circle(V(0, .1), .9), Ellipse(V(0, -.45), .5, .4)], k=.3)
    if k == 'elephant':
        return Union([Ellipse(V(0, .2), .9, .92), Cone(V(0, -.2), V(0, -.8), .45, .32)], k=.3)
    if k in ('ape', 'monkey'):
        return Union([Ellipse(V(0, .1), .95, .95), Ellipse(V(0, -.45), .7, .45)], k=.3)
    return Circle(V(0, 0), 1.0)


def eyes(f: Figure, expr: str, at=(.38, .12), size=1.0, iris='', spacing=None):
    """Shared expressive eyes and brows for front faces (world units)."""
    ex, ey = at
    r = .16 * size
    for s in (-1, 1):
        c = V(s * ex, ey)
        if expr == 'happy':
            f.line([c + V(-r * 1.1, -r * .2), c + V(0, r * .8), c + V(r * 1.1, -r * .2)], SW_DETAIL + .5, name='eye')
            continue
        if expr == 'scared':
            f.dot(c, r * 1.35, C.WHITE, 'eye_white', SW_DETAIL)
            f.dot(c + V(0, -r * .1), r * .5, C.INK, 'pupil')
            f.spot(c + V(r * .18, r * .1), r * .17)
            f.line([c + V(-r * 1.1, r * 2.0), c + V(0, r * 2.5), c + V(r * 1.1, r * 2.1)], SW_DETAIL, name='brow')
            continue
        if iris:
            f.dot(c, r * 1.15, C.WHITE, 'eye_white', SW_DETAIL)
            f.dot(c + V(0, -r * .05), r * .78, iris, 'iris', SW_FINE)
            f.dot(c + V(0, -r * .05), r * .38, C.INK, 'pupil', SW_FINE)
            f.spot(c + V(r * .3, r * .32), r * .25)
        else:
            f.dot(c, r, C.INK, 'eye')
            f.spot(c + V(r * .35, r * .4), r * .33)
        if expr == 'determined':        # inner ends low: a frown
            f.line([c + V(-s * r * 1.5, r * 1.2), c + V(s * r * 1.3, r * 2.1)], SW_DETAIL + 1, name='brow')
        elif expr == 'sad':             # inner ends high: worried
            f.line([c + V(-s * r * 1.4, r * 2.2), c + V(s * r * 1.3, r * 1.3)], SW_DETAIL + .5, name='brow')
            if s == 1:
                f.fill(Union([Circle(c + V(r * .9, -r * 2.0), r * .38),
                              Poly([c + V(r * .62, -r * 1.85), c + V(r * .9, -r * 1.2), c + V(r * 1.18, -r * 1.85)])]),
                       '#8EC9F0', SW_FINE, 'tear')


def mouth(f: Figure, expr: str, centre, width=.24, kind='cat'):
    x, y = centre
    w = width
    if expr == 'happy':
        f.fill(Union([Ellipse(V(x, y - w * .35), w * 1.2, w * .75), ], k=0), C.MOUTH, SW_DETAIL, 'mouth')
        f.patch(Ellipse(V(x, y - w * .95), w * .7, w * .35), C.TONGUE, Ellipse(V(x, y - w * .35), w * 1.2, w * .75),
                'tongue')
    elif expr == 'scared':
        f.fill(Ellipse(V(x, y - w * .55), w * .45, w * .55), C.MOUTH, SW_DETAIL, 'mouth')
    elif expr == 'sad':
        f.line([V(x - w * 1.0, y - w * .9), V(x, y - w * .45), V(x + w * 1.0, y - w * .9)], SW_DETAIL, name='mouth')
    elif expr == 'determined':
        f.line([V(x - w * 1.0, y - w * .55), V(x + w * 1.0, y - w * .65)], SW_DETAIL, name='mouth')
    else:
        if kind in ('cat', 'bigcat', 'dog', 'bear', 'hyena', 'mouse', 'rabbit', 'porcupine'):
            f.line([V(x, y + w * .3), V(x, y - w * .2)], SW_FINE, name='philtrum')
            f.line([V(x - w * 1.0, y - w * .3), V(x - w * .5, y - w * .55), V(x, y - w * .2),
                    V(x + w * .5, y - w * .55), V(x + w * 1.0, y - w * .3)], SW_FINE, name='mouth')
        else:
            f.line([V(x - w * .9, y - w * .3), V(x, y - w * .55), V(x + w * .9, y - w * .3)], SW_FINE, name='mouth')


def build(fc: Face, expr: str) -> Figure:
    if fc.kind in SPECIAL:
        return SPECIAL[fc.kind](fc, expr)
    f = Figure()
    k = fc.kind
    head = _head_shape(fc)
    shade = C.shade(fc.coat, .2)
    # behind the head: mane, ears, horns that sit behind
    if fc.mane:
        bumps = [Circle(V(0, -.05), 1.42 * fc.mane)]
        for i in range(14):
            t = i / 14 * 2 * math.pi + .1
            bumps.append(Circle(V(math.cos(t) * 1.42 * fc.mane, -.05 + math.sin(t) * 1.48 * fc.mane), .36 * fc.mane))
        f.fill(Union(bumps, k=.1), fc.mane_c, SW, 'mane')
    if fc.quills:
        spikes = []
        for i in range(17):
            t = deg(200 - i * 220 / 16)
            base = V(math.cos(t) * .8, math.sin(t) * .8 + .05)
            tipp = V(math.cos(t) * 1.7, math.sin(t) * 1.7 + .1)
            n = V(-math.sin(t), math.cos(t)) * .17
            spikes.append(Poly([base + n, tipp, base - n], r=.02))
        f.fill(Union(spikes + [Circle(V(0, .05), 1.0)], k=.05), fc.quill_c, SW_DETAIL, 'quills')
    ears = _ears(fc) if fc.ears != 'none' else []
    for ear, inner in ears:
        col = fc.coat
        f.fill(ear, col, SW, 'ear')
        if inner is not None:
            f.patch(inner, fc.ear_in, ear, 'ear_in')
    if fc.horns in ('cow', 'goat', 'ram', 'antlers', 'ossicones', 'antelope'):
        _horns(f, fc)
    if fc.wool:
        puffs = [Circle(V(math.cos(t) * .82, .55 + math.sin(t) * .35), .3) for t in [i * .7 for i in range(9)]]
        f.fill(Union(puffs + [Ellipse(V(0, .6), .8, .4)], k=.05), '#FFFFFF', SW_DETAIL, 'wool')
    f.fill(head, fc.coat, SW, 'head')
    # face colour areas
    if k in ('cat', 'bigcat'):
        muzzle = Union([Circle(V(-.22, -.42), .3), Circle(V(.22, -.42), .3), Circle(V(0, -.62), .22)], k=.1)
        if k == 'bigcat' and not fc.young:
            muzzle = Union([muzzle, Cone(V(0, .45), V(0, -.2), .1, .16)] +
                           [Ellipse(V(s * .4, -.08), .2, .09) for s in (-1, 1)], k=.08)
        f.patch(muzzle, fc.under, head, 'muzzle')
    elif k in ('dog', 'hyena', 'fox', 'wolf', 'bear'):
        f.patch(Ellipse(V(0, -.5), .5, .38), fc.under, head, 'muzzle')
        if k in ('fox', 'wolf'):
            f.patch(Union([Ellipse(V(-.55, -.4), .5, .45), Ellipse(V(.55, -.4), .5, .45)]), fc.under, head, 'cheeks')
    elif k in ('horse', 'deer', 'goat', 'giraffe', 'antelope', 'sheep'):
        f.patch(Ellipse(V(0, -.85), .52, .35), fc.under, head, 'muzzle')
    elif k == 'cow':
        f.patch(Ellipse(V(0, -.85), .7, .4), fc.under, head, 'muzzle')
    elif k in ('mouse', 'rabbit', 'porcupine'):
        f.patch(Union([Circle(V(-.18, -.48), .25), Circle(V(.18, -.48), .25)]), fc.under, head, 'muzzle')
    elif k in ('ape', 'monkey'):
        face = Union([Circle(V(-.32, .08), .38), Circle(V(.32, .08), .38), Ellipse(V(0, -.45), .6, .45)], k=.2)
        f.patch(face, fc.face_c or fc.under, head, 'face')
    if fc.pattern == 'stripes':
        strokes = [Cone(V(0, .95), V(0, .55), .09, .03), Cone(V(-.3, .9), V(-.22, .6), .07, .02),
                   Cone(V(.3, .9), V(.22, .6), .07, .02)]
        for s in (-1, 1):
            strokes += [Cone(V(s * 1.05, .1), V(s * .7, .05), .08, .02), Cone(V(s * 1.05, -.2), V(s * .72, -.18), .07, .02)]
        f.patch(Union(strokes), fc.mark_c, head, 'stripes')
    elif fc.pattern in ('spots', 'rosettes'):
        spots = [Circle(V(x, y), r) for x, y, r in ((-.3, .7, .07), (.25, .75, .06), (0, .55, .05), (-.7, .25, .07),
                                                    (.7, .3, .06), (-.75, -.1, .05), (.78, -.05, .06))]
        f.patch(Union(spots), fc.mark_c, head, 'spots')
    elif fc.pattern == 'tears':
        for s in (-1, 1):
            f.patch(Cone(V(s * .27, .04), V(s * .42, -.44), .04, .025), fc.mark_c, head, 'tear_mark')
    elif fc.pattern == 'zebra':
        strokes = [Cone(V(x, .95), V(x * .7, .35), .08, .03) for x in (-.45, -.15, .15, .45)]
        strokes += [Cone(V(s * .62, -.2), V(s * .4, -.5), .06, .02) for s in (-1, 1)]
        f.patch(Union(strokes), fc.mark_c, head, 'stripes')
    elif fc.pattern == 'giraffe':
        spots = [Poly([V(x, y) + rot(V(r, 0), i * 1.2566) for i in range(5)], r=.02)
                 for x, y, r in ((-.4, .6, .14), (.35, .55, .13), (0, .25, .1), (-.6, .1, .1), (.6, .05, .1))]
        f.patch(Union(spots), fc.mark_c, head, 'spots')
    elif fc.pattern == 'mask':
        f.patch(Union([Ellipse(V(-.4, .12), .3, .24, deg(-20)), Ellipse(V(.4, .12), .3, .24, deg(20))]),
                fc.mark_c, head, 'mask')
    if k == 'elephant':
        _trunk(f, fc, expr)
    # eyes
    size = 1.25 if fc.young else 1.0
    at = {'horse': (.42, .35), 'deer': (.42, .35), 'goat': (.42, .35), 'giraffe': (.42, .38), 'cow': (.45, .35),
          'sheep': (.42, .3), 'antelope': (.42, .35), 'elephant': (.38, .2), 'pig': (.38, .2)}.get(k, (.38, .12))
    eyes(f, expr, at, size, fc.iris)
    # nose and mouth
    if k in ('cat', 'bigcat'):
        f.fill(Poly([V(-.16, -.2), V(.16, -.2), V(0, -.36)], r=.05), fc.nose_c, SW_DETAIL, 'nose')
        mouth(f, expr, (0, -.38), .2, 'cat')
    elif k in ('dog', 'hyena', 'fox', 'wolf', 'bear'):
        f.fill(Ellipse(V(0, -.3), .2, .13), fc.nose_c, SW_DETAIL, 'nose')
        mouth(f, expr, (0, -.45), .22, 'dog')
    elif k in ('mouse', 'rabbit', 'porcupine'):
        f.fill(Ellipse(V(0, -.33), .1, .07), fc.nose_c, SW_FINE, 'nose')
        mouth(f, expr, (0, -.42), .16, 'mouse')
        if k == 'rabbit' and expr != 'happy':
            f.fill(Poly([V(-.08, -.6), V(.08, -.6), V(.08, -.75), V(-.08, -.75)], r=.01), C.WHITE, SW_FINE, 'teeth')
    elif k in ('horse', 'deer', 'goat', 'giraffe', 'antelope', 'sheep', 'cow'):
        for s in (-1, 1):
            f.dot(V(s * .2, -.8), .06, C.INK, 'nostril')
        mouth(f, expr, (0, -.95), .18, 'hoof')
    elif k == 'pig':
        disc = Ellipse(V(0, -.3), .38, .28)
        f.fill(disc, C.mix(fc.coat, '#C0505A', .3), SW_DETAIL, 'snout')
        for s in (-1, 1):
            f.dot(V(s * .12, -.3), .055, C.INK, 'nostril')
        mouth(f, expr, (0, -.62), .18, 'pig')
    elif k in ('ape', 'monkey'):
        f.line([V(-.55, .32), V(-.2, .4), V(0, .32), V(.2, .4), V(.55, .32)], SW_DETAIL, name='brow_ridge') \
            if k == 'ape' else None
        for s in (-1, 1):
            f.dot(V(s * .09, -.3), .05, C.INK, 'nostril')
        mouth(f, expr, (0, -.48), .22, 'ape')
    if fc.tusks and k != 'elephant':
        for s in (-1, 1):
            f.fill(Poly([V(s * .3, -.55), V(s * .42, -.25), V(s * .4, -.6)], r=.02), C.WHITE, SW_FINE, 'tusk')
    if fc.scar:
        s0, s1 = V(-.02, .6), V(.12, .02)
        f.line([s0, s1], SW_DETAIL + .5, '#A8473A', 'scar')
        d = (s1 - s0) / math.hypot(*(s1 - s0))
        n = V(-d[1], d[0]) * .1
        for t in (.25, .5, .75):
            c = s0 + (s1 - s0) * t
            f.line([c - n, c + n], SW_FINE, name='scar_stitch')
    if k in ('cat', 'bigcat') and expr in ('neutral', 'determined'):
        for s in (-1, 1):
            for dy in (0, -.1):
                f.dot(V(s * .28, -.5 + dy), .025, C.shade(fc.under, .5), 'whisker_dot')
    f.anchors['eyes'] = V(0, at[1])
    return f


def _horns(f, fc):
    for s in (-1, 1):
        if fc.horns == 'cow':
            pts = [V(s * .5, .85), V(s * .9, 1.0), V(s * 1.05, 1.3)]
            f.fill(Tube(pts, [.14, .1, .05]), fc.horn_c, SW_DETAIL, 'horn')
        elif fc.horns in ('goat', 'antelope'):
            ln = 1.0 if fc.horns == 'goat' else 1.5
            pts = [V(s * .3, .9), V(s * .38, .9 + .5 * ln), V(s * .55, .9 + .9 * ln)]
            f.fill(Tube(pts, [.13, .09, .03]), fc.horn_c, SW_DETAIL, 'horn')
        elif fc.horns == 'ram':
            c = V(s * .85, .45)
            pts = [c + V(s * math.cos(t) * .38, math.sin(t) * .42) * (1 - t * .05) for t in [i * .8 for i in range(8)]]
            f.fill(Tube(pts, [.2 - i * .015 for i in range(8)]), fc.horn_c, SW_DETAIL, 'horn')
        elif fc.horns == 'antlers':
            b = V(s * .35, .9)
            main = [b, b + V(s * .25, .55), b + V(s * .6, 1.0), b + V(s * .75, 1.5)]
            tines = [Tube([main[1], main[1] + V(-s * .2, .45)], [.06, .04]),
                     Tube([main[2], main[2] + V(-s * .05, .5)], [.06, .04]),
                     Tube([main[2], main[2] + V(s * .4, .2)], [.05, .035])]
            f.fill(Union([Tube(main, [.09, .08, .06, .04])] + tines, k=.03), fc.horn_c, SW_DETAIL, 'antlers')
        elif fc.horns == 'ossicones':
            b = V(s * .35, .9)
            f.fill(Union([Cone(b, b + V(s * .05, .5), .1, .09), Circle(b + V(s * .05, .55), .15)]), fc.coat,
                   SW_DETAIL, 'ossicone')


def _trunk(f, fc, expr):
    pts = [V(0, -.3), V(0, -.8), V(.05, -1.25), V(.2, -1.6), V(.42, -1.72)]
    if expr == 'happy':
        pts = [V(0, -.3), V(0, -.8), V(.1, -1.2), V(.35, -1.35), V(.55, -1.2)]
    f.fill(Union([Tube(pts, [.36, .3, .24, .2, .17]), Ellipse(V(0, -.25), .45, .4)], k=.15), fc.coat, SW, 'trunk')
    for y in (-.8, -1.0, -1.2):
        f.line([V(-.18, y), V(.18, y - .03)], SW_FINE, name='trunk_ring')
    if fc.tusks:
        for s in (-1, 1):
            f.fill(Tube([V(s * .35, -.55), V(s * .5, -.9), V(s * .42, -1.15)], [.1, .08, .03]), '#FFF8E8', SW_DETAIL,
                   'tusk')


def _frog(fc: Face, expr: str) -> Figure:
    f = Figure()
    head = Union([Ellipse(V(0, -.1), 1.15, .72), Circle(V(-.55, .45), .42), Circle(V(.55, .45), .42)], k=.15)
    f.fill(head, fc.coat, SW, 'head')
    f.patch(Ellipse(V(0, -.62), .8, .3), fc.under, head, 'throat')
    for s in (-1, 1):
        c = V(s * .55, .5)
        if expr == 'happy':
            f.line([c + V(-.2, -.02), c + V(0, .14), c + V(.2, -.02)], SW_DETAIL + .5, name='eye')
            continue
        r = .28 if expr != 'scared' else .32
        f.dot(c, r, fc.iris if expr != 'scared' else C.WHITE, 'eye', SW_DETAIL)
        if expr == 'scared':
            f.dot(c, .09, C.INK, 'pupil')
        else:
            f.add(type(f.layers[0])('fill', shape=Ellipse(c, .07, .19), fill=C.INK, sw=SW_FINE, name='pupil'))
            f.spot(c + V(.1, .1), .05)
        if expr == 'determined':
            f.line([c + V(-s * .32, .26), c + V(s * .3, .44)], SW_DETAIL + 1, name='brow')
        elif expr == 'sad':
            f.line([c + V(-s * .3, .44), c + V(s * .3, .26)], SW_DETAIL, name='brow')
    for s in (-1, 1):
        f.dot(V(s * .12, -.05), .035, C.INK, 'nostril', SW_FINE)
    if expr == 'happy':
        f.fill(Ellipse(V(0, -.3), .55, .2), C.MOUTH, SW_DETAIL, 'mouth')
    elif expr == 'scared':
        f.fill(Ellipse(V(0, -.33), .18, .14), C.MOUTH, SW_DETAIL, 'mouth')
    elif expr == 'sad':
        f.line([V(-.6, -.42), V(0, -.25), V(.6, -.42)], SW_DETAIL, name='mouth')
    else:
        f.line([V(-.75, -.2), V(0, -.3), V(.75, -.2)], SW_DETAIL, name='mouth')
    if expr == 'sad':
        f.fill(Union([Circle(V(.75, .05), .07), Poly([V(.69, .08), V(.75, .2), V(.81, .08)])]), '#8EC9F0', SW_FINE, 'tear')
    return f


def _bug(fc: Face, expr: str) -> Figure:
    """Ant / bee front face: round head, big side eyes, antennae, mandibles or smile."""
    f = Figure()
    for s in (-1, 1):
        f.fill(Tube([V(s * .25, .8), V(s * .45, 1.25), V(s * .8, 1.45)], [.07, .06, .05]), fc.coat, SW_DETAIL, 'antenna')
        f.fill(Circle(V(s * .8, 1.45), .1), fc.coat, SW_DETAIL, 'antenna_tip')
    head = Ellipse(V(0, 0), .95, .88)
    f.fill(head, fc.coat, SW, 'head')
    if fc.kind == 'ant':
        for s in (-1, 1):
            f.fill(Tube([V(s * .25, -.72), V(s * .2, -1.0), V(s * .02, -1.1)], [.1, .08, .05]), fc.coat, SW_DETAIL,
                   'mandible')
    f.patch(Ellipse(V(-.3, .45), .25, .12, deg(20)), C.light(fc.coat, .3), head, 'shine')
    eyes(f, expr, (.42, .12), 1.25, '#6B4A2E' if fc.kind == 'ant' else '')
    mouth(f, expr, (0, -.35), .2, 'bug')
    return f


def _bird(fc: Face, expr: str) -> Figure:
    """Bird front face: round head, beak pointing at the viewer, comb / crest / ear tufts by kind."""
    f = Figure()
    if fc.crest:
        f.fill(Poly([V(-.2, .78), V(.05, 1.55), V(.28, .72)], r=.06), fc.crest, SW_DETAIL, 'crest')
    if fc.comb:
        f.fill(Union([Circle(V(x, .98 + (.08 if x == 0 else 0)), .24) for x in (-.3, 0, .3)], k=.06), fc.comb,
               SW_DETAIL, 'comb')
    if fc.ears == 'tufts':
        for s in (-1, 1):
            f.fill(Poly([V(s * .45, .72), V(s * .85, 1.32), V(s * .82, .5)], r=.05), C.shade(fc.coat, .2), SW_DETAIL,
                   'ear_tuft')
    head = Ellipse(V(0, 0), 1.0, .95)
    f.fill(head, fc.coat, SW, 'head')
    if fc.disc:
        f.patch(Union([Circle(V(s * .4, .08), .5) for s in (-1, 1)], k=.1), fc.disc, head, 'face_disc')
    if fc.under:
        f.patch(Ellipse(V(0, -.9), .85, .42), fc.under, head, 'chest')
    owl = fc.ears == 'tufts' or bool(fc.disc)
    eyes(f, expr, (.4, .15) if owl else (.4, .2), 1.55 if owl else 1.05, fc.iris)
    open_ = {'happy': 1.0, 'scared': .6}.get(expr, 0)
    if fc.beak == 'flat':
        if open_:
            f.fill(Ellipse(V(0, -.42), .3, .16 * open_ + .06), C.MOUTH, SW_DETAIL, 'mouth')
        f.fill(Ellipse(V(0, -.6 - .1 * open_), .4, .12), C.shade(fc.beak_c, .12), SW_DETAIL, 'beak_lower')
        f.fill(Ellipse(V(0, -.3), .44, .18), fc.beak_c, SW_DETAIL, 'beak')
    else:
        tip = -.62 if fc.beak == 'hook' else -.5
        if open_:
            f.fill(Ellipse(V(0, -.45), .16, .14 * open_), C.MOUTH, SW_DETAIL, 'mouth')
            f.fill(Poly([V(-.14, -.5 - .12 * open_), V(.14, -.5 - .12 * open_), V(0, -.68 - .14 * open_)], r=.03),
                   C.shade(fc.beak_c, .12), SW_DETAIL, 'beak_lower')
        f.fill(Poly([V(-.22, -.08), V(.22, -.08), V(0, tip)], r=.05), fc.beak_c, SW_DETAIL, 'beak')
    if fc.comb:
        f.fill(Ellipse(V(0, -.82 - .1 * open_), .1, .17), fc.comb, SW_FINE, 'wattle')
    return f


def _reptile(fc: Face, expr: str) -> Figure:
    """Turtle / snake / crocodile front face."""
    f = Figure()
    k = fc.kind
    if k == 'crocodile':
        for sx in (-1, 1):
            f.fill(Circle(V(sx * .42, .55), .3), fc.coat, SW, 'eye_bump')
        head = Union([Ellipse(V(0, .1), 1.0, .55), Poly([V(-.62, 0), V(.62, 0), V(.45, -.95), V(-.45, -.95)], r=.12)],
                     k=.1)
    elif k == 'snake':
        head = Ellipse(V(0, 0), 1.0, .78)
    else:
        head = Ellipse(V(0, 0), .82, .85)
    f.fill(head, fc.coat, SW, 'head')
    if fc.under:
        f.patch(Ellipse(V(0, -.85), .7, .35), fc.under, head, 'chin')
    if k == 'crocodile':
        if expr in ('happy', 'scared'):
            f.fill(Ellipse(V(0, -.72), .38, .14 if expr == 'scared' else .2), C.MOUTH, SW_DETAIL, 'mouth')
        f.line([V(-.55, -.62), V(-.2, -.7), V(.2, -.7), V(.55, -.62)], SW_DETAIL, name='jaw')
        teeth = [Poly([V(x - .05, -.66), V(x + .05, -.66), V(x, -.8)], r=.01) for x in (-.42, -.22, .22, .42)]
        f.fill(Union(teeth), C.WHITE, SW_FINE, 'teeth')
        for sx in (-1, 1):
            f.dot(V(sx * .14, -.3), .04, C.INK, 'nostril', SW_FINE)
        eyes(f, expr, (.42, .58), .95, '#C9B23A')
        return f
    eyes(f, expr, (.42, .18) if k != 'snake' else (.5, .2), 1.1, '#E3B23C' if k == 'snake' else '')
    for sx in (-1, 1):
        f.dot(V(sx * .1, -.18), .03, C.INK, 'nostril', SW_FINE)
    if k == 'snake' and expr in ('happy', 'scared', 'determined'):
        f.fill(Union([Cone(V(0, -.48), V(0, -.85), .04, .03), Cone(V(0, -.85), V(-.1, -1.0), .03, .02),
                      Cone(V(0, -.85), V(.1, -1.0), .03, .02)], k=.01), C.MOUTH, SW_FINE, 'tongue')
    mouth(f, expr, (0, -.32), .22, 'bug')
    return f


def _fish(fc: Face, expr: str) -> Figure:
    """Fish front face: round body, eyes on the sides, puckered mouth, fins around."""
    f = Figure()
    fin = C.shade(fc.coat, .12)
    if fc.horns == 'shark':
        f.fill(Poly([V(-.2, .7), V(0, 1.45), V(.2, .7)], r=.04), fin, SW_DETAIL, 'dorsal')
    else:
        f.fill(Ellipse(V(0, .95), .25, .3), fin, SW_DETAIL, 'dorsal')
    for sx in (-1, 1):
        f.fill(Ellipse(V(sx * .95, -.35), .28, .14, sx * deg(-30)), fin, SW_DETAIL, 'fin')
    head = Ellipse(V(0, 0), .9, .95)
    f.fill(head, fc.coat, SW, 'body')
    if fc.under:
        f.patch(Ellipse(V(0, -.85), .75, .45), fc.under, head, 'belly')
    if fc.pattern == 'bands':
        f.patch(Union([Ellipse(V(0, .4), 1.0, .14)]), C.WHITE, head, 'band')
    eyes(f, expr, (.5, .2), 1.15, fc.iris)
    if fc.horns == 'shark':
        if expr in ('happy', 'scared', 'determined'):
            f.fill(Ellipse(V(0, -.5), .45, .16 if expr != 'scared' else .22), C.MOUTH, SW_DETAIL, 'mouth')
            f.fill(Union([Poly([V(x - .06, -.38), V(x + .06, -.38), V(x, -.5)], r=.01) for x in (-.3, -.1, .1, .3)]),
                   C.WHITE, SW_FINE, 'teeth')
        else:
            f.line([V(-.45, -.45), V(0, -.55), V(.45, -.45)], SW_DETAIL, name='mouth')
        return f
    if expr in ('happy', 'scared'):
        f.fill(Ellipse(V(0, -.42), .16, .18 if expr == 'scared' else .14), C.MOUTH, SW_DETAIL, 'mouth')
    else:
        f.fill(Ellipse(V(0, -.42), .12, .08), C.shade(fc.coat, .25), SW_DETAIL, 'mouth')
    if expr == 'sad':
        f.line([V(-.25, -.62), V(0, -.55), V(.25, -.62)], SW_FINE, name='frown')
    return f


def _human(fc: Face, expr: str) -> Figure:
    """Person front face: skin-coloured head, hair by style, crown or explorer hat, glasses, beard."""
    f = Figure()
    hair = fc.mane_c
    hs = fc.hair_style
    if hs == 'long':
        f.fill(Union([Ellipse(V(0, -.15), 1.15, 1.25), Ellipse(V(0, -.95), 1.05, .55)], k=.1), hair, SW, 'hair_back')
    elif hs == 'ponytail':
        f.fill(Tube([V(-.7, .5), V(-1.25, -.1), V(-1.15, -.75)], [.3, .26, .14]), hair, SW, 'ponytail')
    elif hs == 'bun':
        f.fill(Circle(V(0, 1.1), .38), hair, SW_DETAIL, 'bun')
    for s in (-1, 1):
        f.fill(Circle(V(s * .98, -.05), .2), fc.coat, SW_DETAIL, 'ear')
    head = Circle(V(0, 0), 1.0)
    f.fill(head, fc.coat, SW, 'head')
    if hs in ('short', 'long', 'ponytail', 'bun', 'curly'):
        cap = Union([Ellipse(V(0, .72), 1.05, .5), Ellipse(V(-.62, .55), .45, .42, deg(-20)),
                     Ellipse(V(.55, .6), .5, .35, deg(15))], k=.06)
        f.patch(cap, hair, head, 'hair')
        if hs == 'curly':
            f.fill(Union([Circle(rot(V(0, .98), deg(a)), .3) for a in (-70, -35, 0, 35, 70)], k=.03), hair, SW_DETAIL,
                   'curls')
    elif hs == 'bald':
        f.patch(Union([Ellipse(V(s * .95, .05), .25, .4) for s in (-1, 1)]), hair, head, 'hair_sides')
    if fc.beard:
        f.fill(Union([Ellipse(V(0, -.82), .66, .36), Circle(V(0, -1.08), .26)], k=.06), hair, SW_DETAIL, 'beard')
    eyes(f, expr, (.36, -.04), .72)
    f.line([V(-.02, -.1), V(.06, -.2), V(-.02, -.26)], SW_FINE, name='nose')
    for s in (-1, 1):
        f.spot(V(s * .58, -.28), .13, C.mix(fc.coat, '#F08080', .45), 'cheek')
    if fc.glasses:
        for s in (-1, 1):
            f.line([V(s * .36, .02) + rot(V(.25, 0), deg(a)) for a in range(0, 361, 30)], SW_FINE, name='glasses',
                   closed=True)
        f.line([V(-.11, .02), V(.11, .02)], SW_FINE, name='glasses_bridge')
    mouth(f, expr, (0, -.4), .2, 'human')
    if fc.hat in ('crown', 'tiara'):
        w = .85 if fc.hat == 'crown' else .55
        b = .72
        pts = [V(-w, b), V(-w, b + .32), V(-w * .6, b + .62), V(-w * .3, b + .3), V(0, b + .7), V(w * .3, b + .3),
               V(w * .6, b + .62), V(w, b + .32), V(w, b)]
        f.fill(Poly(pts, r=.02), '#F2C230', SW_DETAIL, 'crown')
        f.dot(V(0, b + .18), .1, '#E53935', 'jewel', SW_FINE)
    elif fc.hat == 'helmet':
        f.fill(Ellipse(V(0, .5), 1.35, .16), C.shade(fc.mark_c, .12), SW_DETAIL, 'hat_brim')
        dome = Ellipse(V(0, .72), .95, .52)
        f.fill(dome, fc.mark_c, SW_DETAIL, 'hat')
        f.patch(Ellipse(V(0, .58), 1.0, .08), C.shade(fc.mark_c, .35), dome, 'hat_band')
    return f


SPECIAL = {'frog': _frog, 'human': _human, 'ant': _bug, 'bee': _bug, 'beetle': _bug, 'bird': _bird, 'turtle': _reptile,
           'snake': _reptile, 'crocodile': _reptile, 'fish': _fish}

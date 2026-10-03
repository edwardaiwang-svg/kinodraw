"""Skins: one look's paper, ink, line grain, fills, fonts, hand and chrome over the whiteboard renderer.

Builders draw in the whiteboard's reference palette (ink.INK, SOFT_INK, the section colours, white cards, yellow
notes). Every drawing passes through ``Skin.dress`` once, when it is added to the board, and the skin maps that
palette to its own: line colours, then line grain, then fills. The whiteboard skin changes nothing, so its frames
are the renderer's own. The skin of a look comes from its registry entry (kinodraw/styles/registry.json).

Looks (all drawn in code, no image models; the hand is J's photo, restyled):
  chalkboard  slate-green board with eraser smudges and chalk dust, chalk-white letters, pastel chalk colours,
              pictures as chalk lines over pastel chalk rubbed in at about 80%, a white chalk marker in the hand
  notebook    lined paper with a red margin, graphite pencil with grain, colour-pencil fills, a yellow
              highlighter swiped behind each sentence's key phrase where it is written, a pencil in the hand
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

from . import ink

TILE = 512                       # grain tiles repeat every TILE px on the board
HIGHLIGHTER = (255, 228, 54, 150)          # a yellow highlighter
ON_YELLOW = (255, 96, 170, 140)             # a pink one, for words on a yellow note


@dataclass(frozen=True)
class Skin:
    id: str = 'whiteboard'
    paper: str = 'whiteboard'           # background: whiteboard (ink.paper) | slate | lined
    lines: str = 'identity'             # how line and text colours map: identity | chalk | graphite
    fills: str = 'identity'             # how fills map: identity | chalk | pencil
    grain: str = 'none'                 # texture of every mark: none | chalk | graphite
    hand: str = 'marker'                # what the hand holds: marker | chalk | pencil
    emphasis: str = 'none'              # each sentence's key phrase on the board: none | highlighter
    fonts: ink.Fonts = ink.FONTS
    base: tuple = ink.PAPER_RGB         # the paper's colour, which fills are mixed towards
    soft: tuple = (85, 96, 106)         # chrome: the source line
    faint: tuple = (110, 118, 126)      # chrome: the footer
    caption: tuple = (18, 18, 18)       # captions: letters
    caption_edge: tuple = (255, 255, 255)   # captions: the outline that keeps them readable on any picture
    ink: tuple = ink.INK[:3]            # what ink.INK becomes (titles, labels, outlines); last: the name
                                        # hides the ink module in the rest of this class body

    @property
    def plain(self) -> bool:
        return self.lines == self.fills == 'identity' and self.grain == 'none'

    def background(self, width=1920, height=1080) -> Image.Image:
        """The paper (RGBA, cached: copy before drawing on it)."""
        return ink.paper(width, height) if self.paper == 'whiteboard' else _paper(self.paper, self.base, width, height)

    def color(self, rgb) -> tuple:
        """One reference colour as this skin draws it (chrome, thumbnails)."""
        if self.lines == 'identity':
            return tuple(rgb[:3])
        return tuple(int(round(v)) for v in _map_lines(self, np.array([[rgb[:3]]], np.float32))[0, 0])

    def dress(self, drawing, x=0, y=0):
        """Restyle a drawing in place (its images are replaced, never edited) and return it; (x, y) is where it
        sits on the board, which anchors its grain."""
        if self.plain:
            return drawing
        if isinstance(drawing, ink.TextDrawing):
            drawing.ink = self._lines(drawing.ink, x, y)
            drawing.alpha = np.asarray(drawing.ink.getchannel('A'))
        elif isinstance(drawing, ink.PathDrawing):
            line = self._lines(drawing.line, x, y)
            if drawing.color is drawing.line:
                color = line
            else:
                color = self._fills(drawing.color, x, y, getattr(drawing, 'doodle', False))
                color.alpha_composite(line)
                # the line layer's empty pixels take the picture's colours, so the moment the picture replaces
                # its lines (a cross-fade of the two layers) has no grey wash where the lines were not
                la, ca = np.asarray(line), np.asarray(color)
                line = Image.fromarray(np.where(la[..., 3:] == 0, np.dstack([ca[..., :3], la[..., 3:]]), la), 'RGBA')
            drawing.line, drawing.color = line, color
        return drawing

    def _lines(self, img, x, y):
        a = np.asarray(img, np.float32)
        rgb = _map_lines(self, a[..., :3])
        alpha = a[..., 3] * _grain(self.grain, 'line', a.shape[:2], x, y)
        return Image.fromarray(np.dstack([rgb, alpha]).round().clip(0, 255).astype(np.uint8), 'RGBA')

    def _fills(self, img, x, y, doodle):
        a = np.asarray(img, np.float32)
        rgb = _map_fills(self, a[..., :3], doodle)
        alpha = a[..., 3] * _grain(self.grain, 'fill', a.shape[:2], x, y)
        if doodle and self.fills == 'pencil':
            alpha = alpha * _hatch(a.shape[:2], x, y)
        return Image.fromarray(np.dstack([rgb, alpha]).round().clip(0, 255).astype(np.uint8), 'RGBA')


WHITEBOARD = Skin()


def for_look(look: str | None) -> Skin:
    """The skin of a look (a registry entry rendered by the whiteboard renderer); the whiteboard's otherwise."""
    from .. import styles
    entry = styles.get(look) if look else None
    if not entry or entry.get('renderer') != 'whiteboard' or not entry.get('skin'):
        return WHITEBOARD
    return _skin(entry['id'])


@lru_cache(maxsize=16)
def _skin(look: str) -> Skin:
    from .. import styles
    entry = styles.get(look)
    params = dict(entry['skin'])
    for key in ('ink', 'base', 'soft', 'faint', 'caption', 'caption_edge'):
        if key in params:
            params[key] = ink.rgba(params[key])[:3]
    fonts = entry.get('fonts')
    if fonts:
        files = {kind: (str(ink.ASSETS / 'fonts' / name), 0) for kind, name in fonts.items()}
        params['fonts'] = ink.Fonts(**{**ink.FONTS._asdict(), **files})
    return Skin(id=look, **params)


# ------------------------------------------------------------------ colour maps
def _luma(rgb):
    return (rgb[..., 0] * .299 + rgb[..., 1] * .587 + rgb[..., 2] * .114) / 255


def _saturation(rgb):
    hi, lo = rgb.max(-1), rgb.min(-1)
    return (hi - lo) / np.maximum(hi, 1)


def _pastel(rgb, white=.5):
    """The same hue at full value, mixed towards white: orange becomes peach, blue sky, green mint, red pink."""
    full = rgb * (255 / np.maximum(rgb.max(-1, keepdims=True), 1))
    return full + (255 - full) * white


def _neutral_weight(rgb):
    """1 for greys and blacks, 0 for clear colours, smooth in between."""
    return np.clip((.3 - _saturation(rgb)) / .15, 0, 1)[..., None]


def _map_lines(skin, rgb):
    if skin.lines == 'identity':
        return rgb
    w = _neutral_weight(rgb)
    ink_ = np.array(skin.ink, np.float32)
    if skin.lines == 'chalk':
        # black and white both become chalk (white letters sit on coloured bars); the mid greys of guides and
        # faded marks stay dimmer, as lighter chalk
        L = _luma(rgb)[..., None]
        strength = 1 - .4 * np.exp(-((L - .6) / .17) ** 2)
        base = np.array(skin.base, np.float32)
        return w * (base + (ink_ - base) * strength) + (1 - w) * _pastel(rgb)
    # graphite: the darkest ink becomes the pencil's grey, lighter greys keep their lightness, colours stay
    ref = np.float32(ink.INK[0])
    neutral = ink_ + (rgb - ref) * ((255 - ink_) / (255 - ref))
    return w * np.clip(neutral, 0, 255) + (1 - w) * rgb


def _map_fills(skin, rgb, doodle):
    base = np.array(skin.base, np.float32)
    if skin.fills == 'chalk':
        if doodle:          # pictures: pastel chalk rubbed in at about 80%, greys as lighter or darker chalk dust;
            L = _luma(rgb)[..., None]           # skin tones and browns count as colours, not greys
            w = np.clip((.22 - _saturation(rgb)) / .1, 0, 1)[..., None]
            chalk = np.array(skin.ink, np.float32)
            neutral = base + (chalk - base) * (.2 + .45 * L)
            return w * neutral + (1 - w) * (base + (_pastel(rgb, .4) - base) * .8)
        # shapes: cards and notes stay dark enough for chalk letters on them; colour bars show their colour
        s = _saturation(rgb)[..., None]
        return base + (_pastel(rgb) - base) * (.08 + .26 * s)
    if skin.fills == 'pencil':          # colour pencil: a little lighter than the marker's fills
        return base + (rgb - base) * (.8 if doodle else .9)
    return rgb


# ------------------------------------------------------------------ texture
_SEEDS = {('chalk', 'line'): 11, ('chalk', 'fill'): 12, ('graphite', 'line'): 21, ('graphite', 'fill'): 22}


@lru_cache(maxsize=8)
def _tile(kind: str, part: str) -> np.ndarray:
    """A seamless alpha multiplier, TILE x TILE."""
    rng = np.random.default_rng(_SEEDS[(kind, part)])
    fine = ndimage.gaussian_filter(rng.standard_normal((TILE, TILE)), .8, mode='wrap')
    fine /= fine.std()
    coarse = ndimage.gaussian_filter(rng.standard_normal((TILE, TILE)), 6, mode='wrap')
    coarse /= coarse.std()
    if kind == 'chalk':     # dry chalk: solid strokes with a scatter of small gaps and slightly patchy pressure
        f = (.98 + .3 * fine + .1 * coarse) if part == 'line' else (.93 + .13 * fine + .07 * coarse)
        return np.clip(f, .2 if part == 'line' else .62, 1).astype(np.float32)
    # graphite: an even grain where the paper's tooth catches less
    f = (1. + .2 * fine + .05 * coarse) if part == 'line' else (.95 + .16 * fine + .05 * coarse)
    return np.clip(f, .45 if part == 'line' else .6, 1).astype(np.float32)


def _grain(kind, part, shape, x, y):
    if kind == 'none':
        return np.float32(1)
    h, w = shape
    rows = (np.arange(h) + int(y)) % TILE
    cols = (np.arange(w) + int(x)) % TILE
    return _tile(kind, part)[np.ix_(rows, cols)]


def _hatch(shape, x, y):
    """Colour-pencil shading: diagonal strokes about 7 px apart, anchored to the board."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    return (.78 + .22 * np.cos(2 * np.pi * (xx + int(x) + yy + int(y)) / 7.)).astype(np.float32)


# ------------------------------------------------------------------ paper
@lru_cache(maxsize=4)
def _paper(kind: str, base: tuple, width: int, height: int) -> Image.Image:
    rng = np.random.default_rng({'slate': 31, 'lined': 32}[kind])
    yy, xx = np.mgrid[0:height, 0:width]
    img = np.empty((height, width, 3), np.float32)
    img[:] = base
    grain = ndimage.gaussian_filter(rng.standard_normal((height, width)), .9)
    mottle = ndimage.zoom(ndimage.gaussian_filter(rng.standard_normal((height // 8 + 2, width // 8 + 2)), 3), 8,
                          order=1)[:height, :width]
    if kind == 'slate':
        img += (grain / grain.std() * 2.2 + mottle / mottle.std() * 2.6)[..., None]
        img = _smudges(img, rng, width, height)
        dust = (rng.random((height, width)) < .0016) * rng.uniform(.15, .45, (height, width))
        dust = ndimage.gaussian_filter(dust, .6) * 4
        img += (np.array((226, 230, 222)) - img) * np.clip(dust, 0, .5)[..., None]
        r = np.sqrt(((xx - width / 2) / (width * .6)) ** 2 + ((yy - height / 2) / (height * .6)) ** 2)
        img *= (1 - .16 * np.clip(r - .5, 0, None) ** 1.5)[..., None]
    else:                                   # lined: cool white, faint blue rules, a red margin near the left edge
        img += (grain / grain.std() * 1.6 + mottle / mottle.std() * 1.2)[..., None]
        step, top = round(height * 46 / 1080), round(height * 118 / 1080)
        rules = np.zeros(height, np.float32)
        rules[top::step] = .5
        rules[top + 1::step] = .22
        img += (np.array((150, 186, 226)) - img) * rules[:, None, None]
        margin = round(width * 40 / 1920)
        img[:, margin:margin + 2] += (np.array((226, 112, 112)) - img[:, margin:margin + 2]) * .7
        r = np.sqrt(((xx - width / 2) / (width * .62)) ** 2 + ((yy - height / 2) / (height * .62)) ** 2)
        img *= (1 - .05 * np.clip(r - .5, 0, None) ** 1.6)[..., None]
    return Image.fromarray(np.clip(img + .5, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')


def _smudges(img, rng, width, height):
    """Eraser swipes: broad, soft arcs of chalk haze, streaked along the swipe."""
    haze = Image.new('L', (width, height), 0)
    d = ImageDraw.Draw(haze)
    for _ in range(9):
        cx, cy = rng.uniform(0, width), rng.uniform(0, height)
        length, angle = rng.uniform(.18, .42) * width, rng.uniform(-.5, .5)
        bow = rng.uniform(-.25, .25) * length
        pts = []
        for u in np.linspace(-.5, .5, 24):
            px, py = cx + u * length * np.cos(angle), cy + u * length * np.sin(angle)
            k = bow * (1 - 4 * u * u)
            pts.append((px - k * np.sin(angle), py + k * np.cos(angle)))
        d.line(pts, fill=int(rng.uniform(70, 150)), width=int(rng.uniform(.08, .16) * height), joint='curve')
    soft = np.asarray(haze.filter(ImageFilter.GaussianBlur(height * .03)), np.float32) / 255
    streak = ndimage.gaussian_filter(rng.standard_normal((height, width)), (1.2, 9))
    soft *= np.clip(.75 + .9 * streak / streak.std(), 0, 1.6)
    return img + (np.array((205, 214, 206)) - img) * (soft * .085)[..., None]


# ------------------------------------------------------------------ hand
TIP_TO_CAP = ((42.4, 224.8), (368., 52.))       # the held marker's axis in assets/hand/hand.png


def hand_image(img: Image.Image, tool: str) -> Image.Image:
    """The hand photo holding another tool: the marker's pixels (grey, inside the marker's outline) recoloured
    with the photo's own shading kept. 'chalk' is a white chalk marker; 'pencil' a yellow pencil with a
    sharpened wooden cone and a graphite point."""
    a = np.asarray(img, np.float32)
    rgb, alpha = a[..., :3], a[..., 3]
    tip, cap = np.array(TIP_TO_CAP[0]), np.array(TIP_TO_CAP[1])
    u = (cap - tip) / np.linalg.norm(cap - tip)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    along = (xx - tip[0]) * u[0] + (yy - tip[1]) * u[1]
    across = -(xx - tip[0]) * u[1] + (yy - tip[1]) * u[0]
    grey = np.clip((34 - np.abs(rgb[..., 0] - rgb[..., 2])) / 12, 0, 1)
    inside = np.clip((22 - np.abs(across)) / 3, 0, 1) * (along > -8) * (along < 380)
    m = (grey * inside * (alpha > 0))[..., None]
    v = np.clip((rgb.max(-1) - 15) / 115, 0, 1)[..., None]           # the photo's shading, 0 dark .. 1 highlight
    if tool == 'chalk':
        new = np.array((246, 244, 236), np.float32) * (.8 + .2 * v)
    elif tool == 'pencil':
        body = np.array((238, 186, 44), np.float32)
        wood = np.array((226, 190, 142), np.float32)
        lead = np.array((70, 70, 76), np.float32)
        part = along[..., None]
        color = np.where(part < 12, lead, np.where(part < 38, wood, body))
        new = color * (.68 + .32 * v)
    else:
        raise ValueError(f'unknown hand tool {tool!r}')
    out = rgb * (1 - m) + new * m
    return Image.fromarray(np.dstack([out, alpha]).round().clip(0, 255).astype(np.uint8), 'RGBA')


# ------------------------------------------------------------------ highlighter
class Highlighted:
    """A written text with a highlighter swiped behind phrases of it: each swipe runs left to right just after the
    hand has written its phrase, under the letters. Everything else is the text's own (size, timing, pen)."""

    SWIPE = .35

    def __init__(self, text: ink.TextDrawing, boxes, color=HIGHLIGHTER):
        self.text, self.boxes, self.color = text, boxes, color   # boxes: [(x0, y0, x1, y1, start)], text's frame
        self._done = None

    def __getattr__(self, name):
        return getattr(self.text, name)

    def state(self, elapsed):
        img, pen, down = self.text.state(elapsed)
        if img is None:
            return img, pen, down
        progress = [min(1., max(0., (elapsed - s) / self.SWIPE)) for *_, s in self.boxes]
        if not any(progress):
            return img, pen, down
        final = all(p >= 1 for p in progress) and elapsed >= self.text.duration
        if final and self._done is not None:
            return self._done, pen, down
        out = Image.new('RGBA', img.size, (0, 0, 0, 0))
        band = Image.new('RGBA', img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(band)
        for (x0, y0, x1, y1, _), p in zip(self.boxes, progress):
            if p > 0:
                r = (y1 - y0) / 2
                d.rounded_rectangle((x0, y0, max(x0 + 2 * r, x0 + (x1 - x0) * p), y1), r * .55, fill=self.color)
        out.alpha_composite(band)
        out.alpha_composite(img)
        if final:
            self._done = out
        return out, pen, down


def phrase_boxes(td: ink.TextDrawing, phrase: str):
    """Where ``phrase`` is written in ``td`` (case and spacing ignored), one box per line it runs over, each with
    the time its last letter is written; [] when it is not there."""
    sep = ' ' if td.lang == 'en' else ''
    chars = []                                         # (line, index in line) per character of the joined text
    text = ''
    for i, (row, _, _) in enumerate(td.placed):
        if i and sep:
            text += sep
            chars.append(None)
        text += ''.join(c for c, _, _ in row)
        chars += [(i, k) for k in range(len(row))]
    norm = lambda s: re.sub(r'\s+', ' ', s).strip().lower()       # noqa: E731
    target = norm(phrase)
    if not target:
        return []
    low = text.lower()
    if td.lang == 'en':        # a whole word first, else the start of a word ('warm' in 'warms'), never inside one
        hit = (re.search(rf'(?<!\w){re.escape(target)}(?!\w)', low)
               or re.search(rf'(?<!\w){re.escape(target)}', low))
        at = hit.start() if hit else -1
    else:
        at = low.find(target)
    if at < 0:
        return []
    spans: dict = {}
    for c in chars[at:at + len(target)]:
        if c is not None and not td.placed[c[0]][0][c[1]][0].isspace():
            spans.setdefault(c[0], []).append(c[1])
    boxes = []
    for i, ks in spans.items():
        row, y, (asc, desc) = td.placed[i]
        x0, x1 = row[ks[0]][1] - 4, row[ks[-1]][2] + 4
        top = y + asc * (.16 if td.lang == 'zh' else .3)
        bottom = y + asc + desc * .35
        region = (slice(int(top), int(np.ceil(bottom))), slice(int(x0), int(np.ceil(x1))))
        written = td.arrival[region][td.alpha[region] > 32]
        written = written[np.isfinite(written)]
        boxes.append((x0, top, x1, bottom, (float(written.max()) if written.size else td.duration) + .12))
    return boxes


def highlight_phrases(episode, tline, elements):
    """Highlight each sentence's key phrase (its annotate emphasis) in the text written while it is said."""
    for beat in episode['beats']:
        phrases = [e['emphasis'] for e in beat.get('direction') or [] if isinstance(e, dict) and e.get('emphasis')]
        info = tline['beats'].get(beat['id'])
        if not phrases or not info:
            continue
        lo, hi = info.get('prep', info['start']) - .5, info['end'] + .5
        texts = [e for e in elements if isinstance(e.drawing, ink.TextDrawing) and lo <= e.trigger <= hi
                 and not _coloured(e.drawing)]      # coloured words already stand out, and lose contrast on a band
        found: dict = {}                    # element -> its phrases' boxes, so one text can carry several phrases
        for phrase in phrases:
            for el in texts:
                boxes = phrase_boxes(el.drawing, phrase)
                if boxes:
                    found.setdefault(id(el), (el, []))[1].extend(boxes)
                    break
        for el, boxes in found.values():
            x0, y0, x1, y1, _ = boxes[0]
            under = _under(elements, el, el.x + (x0 + x1) / 2, el.y + (y0 + y1) / 2)
            el.drawing = Highlighted(el.drawing, sorted(boxes, key=lambda b: b[4]),
                                     ON_YELLOW if _yellow(under) else HIGHLIGHTER)


def _coloured(td) -> bool:
    a = np.asarray(td.ink, np.float32)
    rgb = a[..., :3][a[..., 3] > 200]
    return rgb.size > 0 and float(_saturation(rgb.mean(0))) > .3


def _under(elements, el, x, y):
    """The finished colour on the board under the point (x, y) of ``el``, from what was drawn before it."""
    for other in reversed(elements[:elements.index(el)]):
        d = other.drawing
        img = getattr(d, 'color', None) or getattr(d, 'image', None)
        if img is None or not hasattr(img, 'getpixel'):
            continue
        px, py = int(x - other.x), int(y - other.y)
        if 0 <= px < img.width and 0 <= py < img.height:
            r, g, b, a = img.convert('RGBA').getpixel((px, py))
            if a > 100:                     # fills are grained, so a solid one is not always opaque
                return r, g, b
    return None


def _yellow(rgb):
    return rgb is not None and rgb[0] > 190 and rgb[1] > 170 and rgb[2] < .8 * min(rgb[0], rgb[1])

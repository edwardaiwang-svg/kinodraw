"""Skins: one look's paper, ink, line grain, fills, fonts, hand and chrome over the whiteboard renderer.

Builders draw in the whiteboard's reference palette (ink.INK, SOFT_INK, the section colours, white cards, yellow
notes). Every drawing passes through ``Skin.dress`` once, when it is added to the board, and the skin maps that
palette to its own: line colours, then line grain, then fills. The whiteboard skin changes nothing, so its frames
are the renderer's own. The skin of a look comes from its registry entry (kinodraw/styles/registry.json).

Looks (all drawn in code, no image models; the hand is a photographed drawing hand, restyled):
  chalkboard  slate-green board with eraser smudges and chalk dust, chalk-white letters, pastel chalk colours,
              pictures as chalk lines over pastel chalk rubbed in at about 80%, a white chalk marker in the hand
  notebook    lined paper with a red margin, graphite pencil with grain, colour-pencil fills, a yellow
              highlighter swiped behind each sentence's key phrase where it is written, a pencil in the hand
  pixel_quest a cream quest world with pixel pictures, a cursor, speech bubbles and golden corner brackets
  mosaic      limestone tesserae with terracotta grout, a marker, caption plaques and tabula ansata tags

Materials affect pictures only, never board text, captions, chrome or the hand. Their cell grids and reveal
are anchored to board coordinates; the seamless world backdrop pans with the board.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from scipy import ndimage

from . import ink

TILE = 512                       # grain tiles repeat every TILE px on the board
HIGHLIGHTER = (255, 228, 54, 150)          # a yellow highlighter
ON_YELLOW = (255, 96, 170, 140)             # a pink one, for words on a yellow note


@dataclass(frozen=True)
class Skin:
    id: str = 'whiteboard'
    paper: str = 'whiteboard'           # background: whiteboard (ink.paper) | slate | lined | quest | mosaic
    lines: str = 'identity'             # how line and text colours map: identity | chalk | graphite
    fills: str = 'identity'             # how fills map: identity | chalk | pencil
    grain: str = 'none'                 # texture of every mark: none | chalk | graphite
    hand: str = 'marker'                # what the hand holds: marker | chalk | pencil | cursor
    emphasis: str = 'none'              # each sentence's key phrase on the board: none | highlighter
    fonts: ink.Fonts = ink.FONTS
    base: tuple = ink.PAPER_RGB         # the paper's colour, which fills are mixed towards
    soft: tuple = (85, 96, 106)         # chrome: the source line
    faint: tuple = (110, 118, 126)      # chrome: the footer
    caption: tuple = (18, 18, 18)       # captions: letters
    caption_edge: tuple = (255, 255, 255)   # captions: the outline that keeps them readable on any picture
    ink: tuple = ink.INK[:3]            # what ink.INK becomes (titles, labels, outlines); last: the name
                                        # hides the ink module in the rest of this class body

    material: str = 'none'             # pictures only: none | pixel | tile
    material_args: tuple = ()          # sorted registry (key, value) pairs, keeping Skin hashable
    caption_style: str = 'outline'     # outline | bubble | plaque
    chapter_tag: str = 'chip'          # chip | bracket | tablet
    bloom: float = 0.

    @property
    def margs(self) -> dict:
        return dict(self.material_args)

    @property
    def textured(self) -> bool:
        return self.material != 'none'

    @property
    def plain(self) -> bool:
        return self.lines == self.fills == 'identity' and self.grain == 'none' and self.material == 'none'

    def background(self, width=1920, height=1080, x=0) -> Image.Image:
        """The paper (RGBA, cached: copy before drawing on it)."""
        if self.paper in ('quest', 'mosaic'):
            period = 3840 if self.paper == 'quest' else 3836
            left = int(x) % period
            return _world(self, width, height).crop((left, 0, left + width, height))
        return ink.paper(width, height) if self.paper == 'whiteboard' else _paper(self.paper, self.base, width, height)

    def caption_image(self, text, lang):
        from . import captions
        if self.caption_style == 'outline':
            return captions.caption_image(text, lang, self.fonts, self.caption, self.caption_edge)
        return _caption_panel(text, lang, self)

    def cursor_image(self):
        return cursor_image()

    def post(self, frame, L):
        """Board-aligned, low-resolution pixel glow, before hand and UI compositing."""
        if not self.bloom:
            return frame
        return _bloom(frame, int(L), self.margs.get('cell', 8), self.bloom)

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
            if self.textured:
                _outline_text(self, drawing)
            drawing.alpha = np.asarray(drawing.ink.getchannel('A'))
        elif isinstance(drawing, ink.PathDrawing):
            line = self._lines(drawing.line, x, y)
            if self.textured:
                color = self._fills(drawing.color, x, y, getattr(drawing, 'doodle', False))
                doodle = getattr(drawing, 'doodle', False)       # widen only the thin lines of shapes (cards, frames, arrows):
                line = material_image(line, self, x, y, self.margs.get('doodle_line_cover' if doodle else 'line_cover', .2),
                                      0 if doodle else self.margs.get('line_grow', 0))      # a doodle's dense outlines
                                                                                            # would swallow it
                color = material_image(color, self, x, y, self.margs.get('fill_cover', .5))
                color.alpha_composite(line)
                la, ca = np.asarray(line), np.asarray(color)
                drawing.line = Image.fromarray(np.where(la[..., 3:] == 0,
                    np.dstack([ca[..., :3], la[..., 3:]]), la), 'RGBA')
                drawing.color = color
                return MaterialDrawing(drawing, x, y, self.margs.get('cell', 8))
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
        elif self.textured and isinstance(drawing, ink.StaticDrawing):
            drawing.image = material_image(drawing.image, self, x, y, self.margs.get('fill_cover', .5))
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


def _wcag(rgb):
    c = np.asarray(rgb, np.float64) / 255
    c = np.where(c <= .03928, c / 12.92, ((c + .055) / 1.055) ** 2.4)
    return float(c @ (.2126, .7152, .0722))


def contrast(a, b) -> float:
    """WCAG contrast ratio of two colours."""
    hi, lo = sorted((_wcag(a), _wcag(b)), reverse=True)
    return (hi + .05) / (lo + .05)


def _outline_text(skin, drawing):
    """Material worlds have a busy sky band and tiles behind the board: text that does not already stand out from
    the paper (chapter-coloured headings) gets an outline in the skin's ink, written with the letters it rings."""
    a = np.asarray(drawing.ink)
    alpha = a[..., 3]
    solid = alpha > 127
    if not solid.any() or contrast(np.median(a[solid][:, :3], 0), skin.base) >= 4.5:
        return
    asc, desc = drawing.placed[0][2] if drawing.placed else (40, 10)
    r = int(np.clip(round((asc + desc) * .035), 2, 5))      # inside TextDrawing's 6 px pad
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = np.ones_like(xx, bool) if skin.material == 'pixel' else (xx * xx + yy * yy) <= r * r + r    # square pixel corners
    ring = ndimage.grey_dilation(alpha, footprint=disk)
    edge = np.zeros_like(a)
    edge[..., :3], edge[..., 3] = skin.ink, ring
    out = Image.fromarray(edge, 'RGBA')
    out.alpha_composite(drawing.ink)
    drawing.ink = out
    # the outline appears with the stroke it surrounds
    _, near = ndimage.distance_transform_edt(alpha == 0, return_indices=True)
    drawing.arrival = drawing.arrival[near[0], near[1]]


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
    if 'material_args' in params:
        params['material_args'] = tuple(sorted(params['material_args'].items()))
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
    sep = ' ' if td.lang in ('en', 'es') else ''
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
    if td.lang in ('en', 'es'):        # a whole word first, else the start of a word ('warm' in 'warms'), never inside one
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


# ------------------------------------------------------------------ board materials
QUEST32 = np.array([ink.rgba('#' + c)[:3] for c in (
    '1E1B2E 3A3550 5E5A78 8C8AA6 BFC0D1 E9E8EE FFFDF5 5A2A27 '
    '8E3B30 C9503C F07B4E F8A96B FBD7A1 E8C547 F7E68A 2F5D3A '
    '3F8E46 7BC05A BFE58A 1F3B73 2E64B5 4FA3E0 9AD7F2 2A7F86 '
    '5CC3B4 6B3F8E A65FB8 E37FA8 F5B6CF 7A5236 B07E54 E2B48A').split()], dtype=np.uint8)


def _blocks(a, cell, x, y):
    """Pad to board cell boundaries, returning the cell-shaped array and crop offsets."""
    h, w = a.shape[:2]
    left, top = int(x) % cell, int(y) % cell
    pads = ((top, -(h + top) % cell), (left, -(w + left) % cell)) + ((0, 0),) * (a.ndim - 2)
    padded = np.pad(a, pads)
    shape = (padded.shape[0] // cell, cell, padded.shape[1] // cell, cell) + a.shape[2:]
    return padded.reshape(shape), left, top


def _tile_jitter(gx, gy):
    """Stable integer hash of absolute board tile indices, independent of draw order."""
    h = (np.asarray(gx, np.int64) * 73856093) ^ (np.asarray(gy, np.int64) * 19349663)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 65535).astype(np.float32) / 32767.5 - 1


def material_image(img, skin, x=0, y=0, cover=.5, grow=0):
    """Alpha-weighted cell colour and binary coverage, expanded on the board grid; size is preserved. ``grow``
    widens the coverage (not the colour) by that many pixels first, so a line thinner than a cell that straddles two
    cells still lights one of them instead of dropping out."""
    args, a = skin.margs, np.asarray(img.convert('RGBA'), np.float32)
    cell = args.get('cell', 8 if skin.material == 'pixel' else 14)
    blocks, left, top = _blocks(a, cell, x, y)
    alpha = blocks[..., 3]
    weight = alpha.sum(axis=(1, 3))
    if grow:
        wide, _, _ = _blocks(ndimage.grey_dilation(a[..., 3], size=(2 * grow + 1, 2 * grow + 1)), cell, x, y)
        coverage = wide.sum(axis=(1, 3))
    else:
        coverage = weight
    sums = (blocks[..., :3] * alpha[..., None]).sum(axis=(1, 3))
    if grow:                # a cell lit only by the widening takes its neighbours' colour
        near = ndimage.uniform_filter(sums, (3, 3, 1), mode='constant')
        near_w = ndimage.uniform_filter(weight, 3, mode='constant')
        sums = np.where(weight[..., None] > 0, sums, near * (weight.max() > 0))
        weight = np.where(weight > 0, weight, near_w)
    rgb = sums / np.maximum(weight[..., None], 1e-6)
    active = coverage >= cover * 255 * cell * cell
    if skin.material == 'pixel':
        # Only the reduced cells take the 32-colour nearest-neighbour search.
        distances = ((rgb[..., None, :] - QUEST32.astype(np.float32)) ** 2).sum(-1)
        rgb = QUEST32[distances.argmin(-1)]
    else:
        # tone, not channel, quantisation: each tessera keeps its hue at one of `levels` lightness steps, so warm
        # stones stay warm instead of snapping to greys
        steps = args.get('levels', 7) - 1
        lum = _luma(rgb)[..., None]
        rgb = rgb * (np.round(lum * steps) / steps) / np.maximum(lum, 1e-3)
        gx = int(x) // cell + np.arange(rgb.shape[1])[None, :]
        gy = int(y) // cell + np.arange(rgb.shape[0])[:, None]
        rgb *= 1 + args.get('jitter', .04) * _tile_jitter(gx, gy)[..., None]
    out = np.dstack((rgb.clip(0, 255).round().astype(np.uint8), active.astype(np.uint8) * 255))
    out = out.repeat(cell, 0).repeat(cell, 1)[top:top + img.height, left:left + img.width]
    if skin.material == 'tile':
        rows = (np.arange(img.height) + int(y)) % cell < args.get('grout_px', 2)
        cols = (np.arange(img.width) + int(x)) % cell < args.get('grout_px', 2)
        grout = rows[:, None] | cols[None, :]
        mixed = out[grout, :3].astype(np.float32)
        mixed += (np.array(ink.rgba(args.get('grout', '#542D1F'))[:3]) - mixed) * args.get('grout_mix', .45)
        out[grout, :3] = mixed.round().clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


class MaterialDrawing(ink.PathDrawing):
    """A PathDrawing whose existing brush mask reveals whole board-aligned cells."""
    def __init__(self, drawing, x, y, cell):
        self.__dict__.update(drawing.__dict__)
        self.material_x, self.material_y, self.material_cell = int(x), int(y), cell

    def state(self, elapsed):
        if not 0 <= elapsed < self.draw_time:
            return super().state(elapsed)
        mask, pen, down = self._mask(elapsed)
        blocks, left, top = _blocks(np.asarray(mask), self.material_cell, self.material_x, self.material_y)
        reduced = blocks.max(axis=(1, 3))
        expanded = reduced.repeat(self.material_cell, 0).repeat(self.material_cell, 1)
        expanded = expanded[top:top + self.size[1], left:left + self.size[0]]
        out = self.line.copy()
        out.putalpha(Image.fromarray((np.asarray(self.line.getchannel('A'), np.uint16) * expanded // 255).astype(np.uint8)))
        return out, (None if pen is None else (float(pen[0]), float(pen[1]))), down


@lru_cache(maxsize=4)
def _world(skin, width, height):
    """A material-processed seamless period plus screen width, with column zero at board zero."""
    period = 3840 if skin.paper == 'quest' else 3836
    cell = skin.margs['cell']
    # Build the period only, then repeat its processed pixels, including periodic tile jitter.
    img = Image.new('RGB', (period, height), skin.base)
    a = np.asarray(img).copy()
    sky_end = round(height * .30)
    top = np.array(ink.rgba('#6EC3F0' if skin.paper == 'quest' else '#3E6E9E')[:3])
    bottom = np.array(skin.base if skin.paper == 'quest' else ink.rgba('#9FC3D8')[:3])
    a[:sky_end] = (top + (bottom - top) * np.linspace(0, 1, sky_end)[:, None, None]).round().astype(np.uint8)
    if skin.paper == 'quest':
        a[:sky_end] = _dithered_sky(sky_end, period, cell, ('#4FA3E0', '#9AD7F2', '#FFFDF5'))
    img = Image.fromarray(a, 'RGB')
    d = ImageDraw.Draw(img)
    sun_x, sun_y, radius = round(period * .72), round(height * .10), round(height * .048)
    d.ellipse((sun_x - radius, sun_y - radius, sun_x + radius, sun_y + radius),
              fill='#F7E68A' if skin.paper == 'quest' else '#D9A441')
    if skin.paper == 'quest':
        d.ellipse((sun_x - radius * .65, sun_y - radius * .65, sun_x + radius * .65, sun_y + radius * .65), fill='#FFFDF5')
        rng = np.random.default_rng(41)
        for cx in (period * .13, period * .38, period * .88):
            cy, cw = int(rng.uniform(.07, .20) * height), int(rng.uniform(140, 220))
            for dx, dy, r in ((-cw // 3, 0, 25), (0, -12, 36), (cw // 3, 0, 28)):
                d.ellipse((cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r), fill='#FFFDF5')
            d.rectangle((cx - cw // 2, cy, cx + cw // 2, cy + 24), fill='#FFFDF5')
        xx = np.arange(period + 1)
        for offset, amp, phase, color in ((.89, .034, .1, '#9CC98A'), (.935, .028, 1.3, '#5FA05A')):
            ridge = height * (offset + amp * (np.sin(2 * np.pi * xx / period + phase)
                      + .3 * np.sin(6 * np.pi * xx / period + phase)))
            d.polygon([(0, height), *zip(xx.tolist(), ridge.tolist()), (period, height)], fill=color)
        ground = (round(height * .968) // cell) * cell
        d.rectangle((0, ground, period, height), fill='#7A5236')
        d.rectangle((0, ground, period, ground + cell - 1), fill='#7BC05A')
    else:
        sand = (round(height * .85) // cell) * cell
        d.rectangle((0, sand, period, height), fill='#D8B27A')
        d.rectangle((0, sand + cell, period, sand + 2 * cell - 1), fill='#B5532E')
    processed = material_image(img, skin, cover=0).convert('RGBA')
    if skin.paper == 'mosaic':
        # Limestone's grout is quieter than the sky and sand; keep the same tile values and jitter.
        from dataclasses import replace
        quiet = replace(skin, material_args=tuple(sorted({**skin.margs, 'grout_mix': .12}.items())))
        middle = material_image(img, quiet, cover=0)
        start, end = sky_end, (round(height * .85) // cell) * cell
        processed.paste(middle.crop((0, start, period, end)), (0, start))
    repeats = (period + width + period - 1) // period
    out = Image.new('RGBA', (period + width, height))
    for i in range(repeats):
        out.paste(processed, (i * period, 0))
    return out


BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 + 1 / 32


def _dithered_sky(rows, width, cell, colors):
    """A pixel-art sky: bands of ``colors`` from the top down, blended by an ordered (Bayer) dither in whole cells
    on the board grid (``width`` a multiple of 4 cells keeps the pattern seamless)."""
    cy, cx = np.mgrid[0:-(-rows // cell), 0:width // cell]
    level = cy / max(1, cy.max()) * (len(colors) - 1)
    base = np.floor(level)
    index = np.minimum(base + ((level - base) > BAYER4[cy % 4, cx % 4]), len(colors) - 1).astype(int)
    rgb = np.array([ink.rgba(c)[:3] for c in colors], np.uint8)[index]
    return rgb.repeat(cell, 0).repeat(cell, 1)[:rows, :width]


def _bloom(frame, L, cell, strength):
    left = L % cell
    right = -(frame.width + left) % cell
    # PIL's integer box reduction is cheap; padding both ends keeps its cells on the board.
    padded = Image.new('RGBA', (frame.width + left + right, frame.height))
    padded.paste(frame, (left, 0))
    if left:
        padded.paste(frame.crop((0, 0, 1, frame.height)).resize((left, frame.height)), (0, 0))
    if right:
        padded.paste(frame.crop((frame.width - 1, 0, frame.width, frame.height)).resize((right, frame.height)), (left + frame.width, 0))
    low = np.asarray(padded.reduce(cell), np.float32)[..., :3] / 255
    bright = np.maximum(0, _luma(low * 255) - .78) / .22
    glow = ndimage.gaussian_filter(low * bright[..., None], (1.2, 1.2, 0), mode='nearest')
    # Quantise the additive glow at low resolution, then expand without smoothing.
    glow = (strength * 255 * glow).round().clip(0, 255).astype(np.uint8)
    rgba = np.dstack((glow, np.zeros(glow.shape[:2], np.uint8)))
    expanded = Image.fromarray(rgba, 'RGBA').resize(frame.size, Image.Resampling.NEAREST,
        box=(left / cell, 0, (left + frame.width) / cell, frame.height / cell))
    return ImageChops.add(frame, expanded)


# ------------------------------------------------------------------ crisp material-look UI
@lru_cache(maxsize=1)
def cursor_image():
    """Classic 12 by 19 arrow bitmap, enlarged fourfold; its first pixel is the tip."""
    rows = (
        'X...........', 'XX..........', 'XOX.........', 'XOOX........', 'XOOOX.......',
        'XOOOOX......', 'XOOOOOX.....', 'XOOOOOOX....', 'XOOOOOOOX...', 'XOOOOOOOOX..',
        'XOOOOOOOOOX.', 'XOOOOOOOOOOX', 'XOOOOOXXXXXX', 'XOOXOOX.....', 'XOX.XOOX....',
        'XX..XOOX....', 'X....XOOX...', '.....XOOX...', '......XX....')
    a = np.zeros((19, 12, 4), np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != '.':
                a[y, x] = ink.rgba('#1E1B2E' if ch == 'X' else '#FFFDF5')
    # a transparent margin, so the hand's soft shadow is not cut off at the arrow's own box
    big = Image.fromarray(a, 'RGBA').resize((48, 76), Image.Resampling.NEAREST)
    out = Image.new('RGBA', (48 + 40, 76 + 40), (0, 0, 0, 0))
    out.paste(big, (8, 8))
    return out, (8, 8)


def glyph_runs(text, kind, size, fonts):
    """Per-character UI runs: glyphs the look font lacks come from Arimo, then Noto Sans SC."""
    return ink.ui_runs(text, kind, size, fonts)


def _run_width(text, kind, size, fonts):
    return sum(f.getlength(ch) for ch, f in glyph_runs(text, kind, size, fonts))


@lru_cache(maxsize=2048)
def caption_layout(text, lang, skin):
    """Wrap on measured fallback runs, shrinking to two lines without leading CJK punctuation."""
    kind = 'en_caption' if lang == 'en' else 'zh_caption'
    units = re.findall(r'\S+\s*', text) if lang == 'en' else re.findall(r"[A-Za-z0-9$.,%×\-–/+']+\s*|.", text)
    for size in range(56 if lang == 'en' else 60, 35, -2):
        lines, current = [], ''
        for u in units:
            trial = current + u
            if current and _run_width(trial.rstrip(), kind, size, skin.fonts) > 1640:
                if lang == 'zh' and re.match(r'[，。！？；：、）」』”’%]', u):
                    current = trial
                    continue
                lines.append(current.rstrip())
                current = u.lstrip() if lang == 'en' else u
            else:
                current = trial
        if current.strip():
            lines.append(current.rstrip())
        if len(lines) <= 2 and all(_run_width(l, kind, size, skin.fonts) <= 1640 for l in lines):
            return lines or [''], size
    return lines or [''], size          # never stop a render: the smallest size, on as many lines as it takes


def _draw_runs(draw, text, pos, kind, size, fonts, color):
    x, y = pos
    # A shared baseline keeps Latin and fallback glyphs aligned despite different ascents.
    for ch, f in glyph_runs(text, kind, size, fonts):
        draw.text((x, y), ch, font=f, fill=color, anchor='ls')
        x += f.getlength(ch)


def _stepped(draw, box, fill, step=8):
    x0, y0, x1, y1 = box
    draw.polygon([(x0 + step, y0), (x1 - step, y0), (x1 - step, y0 + step),
                  (x1, y0 + step), (x1, y1 - step), (x1 - step, y1 - step),
                  (x1 - step, y1), (x0 + step, y1), (x0 + step, y1 - step),
                  (x0, y1 - step), (x0, y0 + step), (x0 + step, y0 + step)], fill=fill)


@lru_cache(maxsize=2048)
def _caption_panel(text, lang, skin):
    lines, size = caption_layout(text, lang, skin)
    kind = 'en_caption' if lang == 'en' else 'zh_caption'
    widths = [_run_width(l, kind, size, skin.fonts) for l in lines]
    lh = round(size * 1.25)
    w, panel_h = int(np.ceil(max(widths))) + 64, lh * len(lines) + 40
    tail = 20 if skin.caption_style == 'bubble' else 0
    img = Image.new('RGBA', (w, panel_h + tail), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tail:
        _stepped(d, (0, 0, w - 1, panel_h - 1), '#1E1B2E')
        d.polygon([(40, panel_h - 9), (80, panel_h - 9), (80, panel_h + 3),
                   (68, panel_h + 3), (68, panel_h + 11), (56, panel_h + 11),
                   (56, panel_h + 19), (40, panel_h + 19)], fill='#1E1B2E')
        _stepped(d, (8, 8, w - 9, panel_h - 9), '#FFFDF5', 4)
        d.polygon([(48, panel_h - 12), (72, panel_h - 12), (72, panel_h - 5),
                   (60, panel_h - 5), (60, panel_h + 3), (48, panel_h + 3)], fill='#FFFDF5')
    else:
        d.rectangle((0, 0, w - 1, panel_h - 1), fill='#3B2418')
        d.rectangle((8, 8, w - 9, panel_h - 9), outline='#D9A441', width=3)
    for i, line in enumerate(lines):
        _draw_runs(d, line, ((w - widths[i]) / 2, 20 + size + i * lh), kind, size, skin.fonts, ink.rgba(skin.caption))
    return img


def tag_image(ch, lang, skin):
    """Chapter text in a pixel bracket or a tabula ansata; UI remains crisp."""
    from .render import chip_text
    return _tag_panel(chip_text(ch, lang), lang, skin)


@lru_cache(maxsize=256)
def _tag_panel(text, lang, skin):
    size, kind = 30, 'ui'
    width = int(np.ceil(_run_width(text, kind, size, skin.fonts)))
    w, h = width + 64, 56
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if skin.chapter_tag == 'bracket':
        _stepped(d, (0, 0, w - 1, h - 1), (30, 27, 46, 230), 4)
        for x, side in ((8, 1), (w - 12, -1)):
            d.rectangle((x, 8, x + 3, 23), fill='#E8C547')
            d.rectangle((min(x, x + side * 12), 8, max(x + 3, x + side * 12), 11), fill='#E8C547')
        color = '#FFFDF5'
    else:
        d.polygon([(0, 6), (15, 16), (15, 0), (w - 16, 0), (w - 16, 16),
                   (w - 1, 6), (w - 1, h - 7), (w - 16, h - 17),
                   (w - 16, h - 1), (15, h - 1), (15, h - 17), (0, h - 7)],
                  fill='#3B2418')
        d.rectangle((18, 3, w - 19, h - 4), fill='#F3E7CF')
        d.polygon([(3, 11), (15, 19), (15, h - 20), (3, h - 12)], fill='#F3E7CF')
        d.polygon([(w - 4, 11), (w - 16, 19), (w - 16, h - 20), (w - 4, h - 12)], fill='#F3E7CF')
        color = '#3B2418'
    _draw_runs(d, text, (32, 39), kind, size, skin.fonts, color)
    return img

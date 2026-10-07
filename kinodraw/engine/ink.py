"""Drawing primitives for the Issue #3 renderer.

Every drawable exposes ``duration`` and ``state(elapsed) -> (RGBA, pen, down)``.
``pen`` is the nib position in the drawable's own pixel frame (or None). Final
appearance equals ``state(duration)``. Nothing here makes marks appear without a
pen: SVG outlines are revealed by a brush that follows the path order, and text,
numbers included, is revealed glyph-stroke by glyph-stroke (ported InkTrace).
"""
from __future__ import annotations

import io
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import numpy as np
import resvg_py
import svgelements
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
from scipy import ndimage

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
INK = (27, 27, 27, 255)
PAPER_RGB = (236, 235, 230)
SECTION_COLORS = {'orange': (245, 124, 0), 'blue': (30, 111, 217), 'green': (46, 157, 79),
                  'purple': (142, 36, 170), 'red': (211, 47, 47), 'teal': (0, 137, 123)}
COLOR_CYCLE = list(SECTION_COLORS)
NEUTRAL = (40, 52, 64)
# Bundled OFL fonts (see assets/fonts/OFL-*.txt).
EN_HAND = (str(ASSETS / 'fonts' / 'PlaypenSans-Bold.ttf'), 0)
ZH_HAND = (str(ASSETS / 'fonts' / 'DoodleKai-Medium.ttf'), 0)
EN_CAPTION = (str(ASSETS / 'fonts' / 'Arimo-Bold.ttf'), 0)
ZH_CAPTION = (str(ASSETS / 'fonts' / 'NotoSansSC-Bold.otf'), 0)
UI_FONT = EN_CAPTION
FONT_FILES = [EN_HAND[0], ZH_HAND[0], EN_CAPTION[0], ZH_CAPTION[0]]


class Fonts(NamedTuple):
    """The four typefaces of a look, as (file, index): handwriting and captions per language, and the UI font.
    A skin carries its own (engine/skin.py); every text measure and drawing takes the set it is given."""
    en_hand: tuple
    zh_hand: tuple
    en_caption: tuple
    zh_caption: tuple
    ui: tuple


FONTS = Fonts(EN_HAND, ZH_HAND, EN_CAPTION, ZH_CAPTION, UI_FONT)      # the whiteboard's


@lru_cache(maxsize=128)
def font(kind: str, size: int, fonts: Fonts = FONTS) -> ImageFont.FreeTypeFont:
    path, index = getattr(fonts, kind)
    # Basic layout everywhere: Pillow would switch to Raqm shaping (other kerning, so other letter positions)
    # wherever libfribidi happens to be installed, as on most Linux systems but not on macOS or Windows.
    return ImageFont.truetype(path, size, index=index, layout_engine=ImageFont.Layout.BASIC)


def hand_font(lang: str, size: int, fonts: Fonts = FONTS):
    return font('en_hand' if lang in ('en', 'es') else 'zh_hand', size, fonts)


@lru_cache(maxsize=8)
def _cmap(path: str, index: int):
    from fontTools.ttLib import TTCollection, TTFont
    f = TTCollection(path).fonts[index] if path.endswith('.ttc') else TTFont(path)
    return frozenset(f.getBestCmap())


def font_runs(text: str, lang: str, size: int, fonts: Fonts = FONTS):
    """Split text into (substring, font) runs; missing glyphs fall back to the other hand font, then the caption font."""
    primary = 'en_hand' if lang in ('en', 'es') else 'zh_hand'
    order = [primary, 'zh_hand' if primary == 'en_hand' else 'en_hand', 'zh_caption']
    runs = []
    for ch in text:
        kind = next((k for k in order if ord(ch) in _cmap(*getattr(fonts, k)) or ch.isspace()), primary)
        if runs and runs[-1][1] == kind:
            runs[-1][0] += ch
        else:
            runs.append([ch, kind])
    return [(t, font(k, size, fonts)) for t, k in runs]


def ui_runs(text: str, kind: str, size: int, fonts: Fonts = FONTS):
    """Per-character (char, font): a glyph the look's font lacks comes from the whiteboard UI font, then Noto Sans SC."""
    chain = [(fonts, kind), (FONTS, 'ui'), (fonts, 'zh_caption')]
    return [(ch, font(k, size, fs)) for ch in text
            for fs, k in [next(((fs, k) for fs, k in chain if ch.isspace() or ord(ch) in _cmap(*getattr(fs, k))),
                               chain[-1])]]


def text_width(text: str, lang: str, size: int, fonts: Fonts = FONTS) -> float:
    return sum(f.getlength(t) for t, f in font_runs(text, lang, size, fonts))


def is_cjk(ch: str) -> bool:
    return '⺀' <= ch <= '鿿' or '　' <= ch <= '〿' or '＀' <= ch <= '￯'


def rgba(color, alpha=None):
    if isinstance(color, str):
        color = color.lstrip('#')
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255 if alpha is None else alpha,)
    if len(color) == 4 and alpha is None:
        return tuple(int(c) for c in color)
    return tuple(int(c) for c in color[:3]) + (255 if alpha is None else alpha,)


# --------------------------------------------------------------------------- paper
@lru_cache(maxsize=2)
def paper(width=1920, height=1080) -> Image.Image:
    rng = np.random.default_rng(20260923)
    base = np.empty((height, width, 3), np.float32)
    base[:] = PAPER_RGB
    grain = ndimage.gaussian_filter(rng.normal(0, 1, (height, width)), 1.1) * 3.2
    fibres = ndimage.gaussian_filter(rng.normal(0, 1, (height // 4, width // 4)), 3)
    fibres = np.kron(fibres, np.ones((4, 4)))[:height, :width] * 4.0
    yy, xx = np.mgrid[0:height, 0:width]
    r = np.sqrt(((xx - width / 2) / (width * .62)) ** 2 + ((yy - height / 2) / (height * .62)) ** 2)
    vignette = 1 - .10 * np.clip(r - .45, 0, None) ** 1.6
    img = (base + (grain + fibres)[..., None]) * vignette[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')


# ------------------------------------------------------------------ path drawings
class PathDrawing:
    """A picture revealed by a brush that follows ordered polylines.

    ``line`` is the line-art layer shown while drawing (occlusion already
    resolved); ``color`` is the finished coloured picture that replaces it over
    ``pop`` seconds once every outline is traced.
    """

    def __init__(self, color: Image.Image, line: Image.Image, polylines, brush: float,
                 speed: float = 900., min_dur: float = .7, max_dur: float = 3.2, pop: float = .28):
        self.color, self.line = color, line
        self.size = color.size
        self.brush = max(2.5, brush)
        segs, lifts, last = [], [], None
        for pts in polylines:
            pts = np.asarray(pts, np.float32)
            if len(pts) == 0:
                continue
            if last is not None:
                lifts.append(float(np.hypot(*(pts[0] - last))))
            else:
                lifts.append(0.)
            segs.append(pts)
            last = pts[-1]
        self.polys = segs
        self.lens = [float(np.sum(np.hypot(*np.diff(p, axis=0).T))) if len(p) > 1 else 1. for p in segs]
        ink_time = sum(self.lens) / speed
        lift_time = sum(lifts) / (speed * 3.2) + .04 * max(0, len(segs) - 1)
        raw = ink_time + lift_time
        scale = 1.
        if raw > max_dur:
            scale = max_dur / raw
        elif raw < min_dur and raw > 0:
            scale = min_dur / raw
        self.draw_time = max(.05, raw * scale)
        # Per-polyline timetable: (lift_start, ink_start, ink_end)
        self.table, t = [], 0.
        for lift, length in zip(lifts, self.lens):
            lt = (lift / (speed * 3.2) + (.04 if self.table else 0)) * scale
            it = length / speed * scale
            self.table.append((t, t + lt, t + lt + it))
            t += lt + it
        self.pop = pop
        self.duration = self.draw_time + pop
        self._cache_e, self._cache_mask, self._cache_idx = -1., None, 0

    def _point(self, poly_i, frac):
        pts = self.polys[poly_i]
        if len(pts) == 1:
            return pts[0], 1
        d = np.hypot(*np.diff(pts, axis=0).T)
        cum = np.concatenate([[0], np.cumsum(d)])
        target = frac * cum[-1]
        j = int(np.searchsorted(cum, target, side='right')) - 1
        j = min(max(j, 0), len(pts) - 2)
        f = 0 if d[j] == 0 else (target - cum[j]) / d[j]
        return pts[j] * (1 - f) + pts[j + 1] * f, j + 1

    def _mask(self, elapsed):
        if self._cache_mask is None or elapsed < self._cache_e:
            self._cache_mask = Image.new('L', self.size, 0)
            self._cache_idx, self._cache_part = 0, 0
        draw = ImageDraw.Draw(self._cache_mask)
        w = int(round(self.brush * 2))
        pen, down = None, False
        for i in range(len(self.polys)):
            lift_start, ink_start, ink_end = self.table[i]
            if elapsed < lift_start:
                break
            pts = self.polys[i]
            if elapsed < ink_start:
                prev = self.polys[i - 1][-1] if i else pts[0]
                f = (elapsed - lift_start) / max(1e-6, ink_start - lift_start)
                pen, down = prev * (1 - f) + pts[0] * f, False
                break
            frac = 1. if elapsed >= ink_end else (elapsed - ink_start) / max(1e-6, ink_end - ink_start)
            point, upto = self._point(i, frac)
            if i < self._cache_idx:
                continue
            start = self._cache_part if i == self._cache_idx else 0
            chunk = [tuple(p) for p in pts[max(0, start - 1):upto]] + [tuple(point)]
            if len(chunk) >= 2:
                draw.line(chunk, fill=255, width=w, joint='curve')
            r = self.brush
            draw.ellipse((point[0] - r, point[1] - r, point[0] + r, point[1] + r), fill=255)
            if len(pts) == 1:
                p = pts[0]
                draw.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=255)
            if frac >= 1:
                self._cache_idx, self._cache_part = i + 1, 0
            else:
                self._cache_idx, self._cache_part = i, upto
                pen, down = point, True
                break
            pen, down = point, True
        self._cache_e = elapsed
        return self._cache_mask, pen, down

    def _native_mask(self, elapsed):
        """Fresh-path rasterization for native recipes, independent of frame history.

        Fractional brush endpoints from earlier calls must not remain in a
        segment's mask. The default incremental mask keeps its exact behavior.
        """
        self._cache_mask = None
        return PathDrawing._mask(self, elapsed)

    def state(self, elapsed):
        if elapsed >= self.duration:
            return self.color, None, False
        if elapsed < 0:
            return None, None, False
        if elapsed >= self.draw_time:
            f = (elapsed - self.draw_time) / self.pop
            out = Image.blend(self.line, self.color, f) if self.line.mode == self.color.mode else self.color
            return out, None, False
        mask, pen, down = self._mask(elapsed)
        out = self.line.copy()
        alpha = ImageChops.multiply(out.getchannel('A'), mask)
        out.putalpha(alpha)
        return out, (None if pen is None else (float(pen[0]), float(pen[1]))), down


def _sample(path: svgelements.Path, scale: float, ox: float, oy: float, step=3.0):
    out = []
    for sub in path.as_subpaths():
        sub = svgelements.Path(sub)
        try:
            length = sub.length(error=1e-3, min_depth=2)
        except Exception:  # noqa: BLE001 - degenerate segment
            length = 0
        if length <= 0:
            continue
        n = max(2, int(length * scale / step))
        pts = sub.npoint(np.linspace(0, 1, n))
        pts = np.asarray(pts, np.float32) * scale + (ox, oy)
        out.append(pts)
    return out


@lru_cache(maxsize=256)
def _svg_layers(svg_path: str, box_w: int, box_h: int):
    text = Path(svg_path).read_text(encoding='utf-8')
    doc = svgelements.SVG.parse(io.StringIO(text), reify=True)
    vw, vh = float(doc.width), float(doc.height)    # svgelements already maps the viewBox onto width x height
    scale = min(box_w / vw, box_h / vh)
    out_w, out_h = max(1, round(vw * scale)), max(1, round(vh * scale))
    color = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=text, width=out_w, height=out_h))).convert('RGBA')
    # fills turn white so only the ink lines remain; a fill that is itself the ink line (data-inkfill, set
    # after fill= by library/packs.py) stays, and the hand traces it like a stroke
    white = re.sub(r'fill="(?!none)[^"]*"(?![^>]*data-inkfill="1")', 'fill="#FFFFFF"', text)
    lineimg = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=white, width=out_w, height=out_h))).convert('RGBA')
    if lineimg.size != color.size:
        lineimg = lineimg.resize(color.size, Image.LANCZOS)
    out_w, out_h = color.size
    scale = min(out_w / vw, out_h / vh)
    lum = np.asarray(lineimg.convert('L'), np.float32)
    alpha = np.asarray(lineimg.getchannel('A'), np.float32) / 255.
    ink_alpha = np.clip((255 - lum) * 1.25, 0, 255) * alpha
    ink_alpha[ink_alpha < 18] = 0
    line = Image.new('RGBA', (out_w, out_h), INK)
    line.putalpha(Image.fromarray(ink_alpha.astype(np.uint8)))
    polylines = []
    stroke_w = 6.0
    for element in doc.elements():
        if not isinstance(element, svgelements.Shape):
            continue
        if element.values.get('data-noink') == '1':
            continue
        try:
            stroke_w = float(element.stroke_width or stroke_w)
        except Exception:  # noqa: BLE001
            pass
        path = svgelements.Path(element)
        if len(path) == 0:
            continue
        path.reify()          # rotated rect/circle/ellipse keep a transform that as_subpaths() would drop
        polylines.extend(_sample(path, scale, 0, 0))
    return color, line, tuple(tuple(map(tuple, p)) for p in polylines), max(3.0, 6.0 * scale * 1.3)


def svg_drawing(svg_path, box, speed=700., min_dur=.8, max_dur=2.0) -> PathDrawing:
    color, line, polylines, brush = _svg_layers(str(svg_path), int(box[0]), int(box[1]))
    drawing = PathDrawing(color, line, [np.asarray(p, np.float32) for p in polylines], brush,
                          speed=speed, min_dur=min_dur, max_dur=max_dur)
    drawing.native_recipe = ('svg', (str(svg_path), tuple(box)),
                             dict(speed=speed, min_dur=min_dur, max_dur=max_dur))
    drawing.doodle = True                    # a picture with its own colours (a skin restyles its fills)
    return drawing


class RevealDrawing:
    """An own picture coloured in along a soft edge, with the hand following it."""

    own = True

    def __init__(self, image: Image.Image, speed=375., min_dur=.8, max_dur=2.2):
        self.image = image.convert('RGBA')
        self.size = self.image.size
        self.draw_time = max(min_dur, min(max_dur, self.size[0] / speed))
        self.duration = self.draw_time + .05
        self.alpha = np.asarray(self.image.getchannel('A'), np.float32)
        self._xs = np.arange(self.size[0], dtype=np.float32)
        self._cache_e, self._cache_result = None, None

    def state(self, elapsed):
        if elapsed < 0:
            return None, None, False
        if elapsed >= self.draw_time:
            return self.image, None, False
        if elapsed == self._cache_e:
            return self._cache_result
        width, height = self.size
        feather = 24.
        edge = -feather + (width + feather) * elapsed / self.draw_time
        ramp = np.clip((edge - self._xs + feather) / feather, 0, 1)
        out = self.image.copy()
        out.putalpha(Image.fromarray((self.alpha * ramp[None, :]).astype(np.uint8)))
        zig = 1 - abs(2 * ((elapsed * 2.5) % 1) - 1)
        pen = (max(0., min(float(width), edge)), height * (.12 + .76 * zig))
        self._cache_e = elapsed
        self._cache_result = out, pen, True
        return self._cache_result


@lru_cache(maxsize=64)
def _picture_image(path: str, mtime_ns: int, size_bytes: int, box_w: int, box_h: int):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGBA')
    scale = min(box_w / image.width, box_h / image.height, 2.)
    size = max(1, round(image.width * scale)), max(1, round(image.height * scale))
    return image.resize(size, Image.Resampling.LANCZOS)


def picture_drawing(path, box, speed=375., min_dur=.8, max_dur=2.2):
    """Trace an own SVG's outlines, or wipe a fitted raster in its original colours."""
    path = Path(path)
    try:
        if path.suffix.lower() == '.svg':
            drawing = svg_drawing(path, box, speed=speed, min_dur=min_dur, max_dur=max_dur)
            if drawing.polys and drawing.line.getbbox():
                drawing.own = True
                return drawing
            image = drawing.color
        else:
            stat = path.stat()
            image = _picture_image(str(path), stat.st_mtime_ns, stat.st_size, int(box[0]), int(box[1]))
        drawing = RevealDrawing(image, speed=speed, min_dur=min_dur, max_dur=max_dur)
        drawing.native_recipe = ('picture', (str(path), tuple(box)),
                                 dict(speed=speed, min_dur=min_dur, max_dur=max_dur))
        return drawing
    except Exception:
        raise ValueError(f'KinoDraw couldn’t open the picture “{path.name}”. Save it again as a PNG or JPG '
                         'and upload it again.') from None


def stroke_drawing(size, polylines, color=INK, width=6, fill=None, closed_fill=None,
                   speed=900., min_dur=.35, max_dur=2.2, pop=.2, ss=2) -> PathDrawing:
    """Procedural ink lines (arrows, boxes, axes); optional polygon fills pop after."""
    w, h = int(size[0]), int(size[1])
    big = (w * ss, h * ss)
    line = Image.new('RGBA', big, (0, 0, 0, 0))
    col = Image.new('RGBA', big, (0, 0, 0, 0))
    dl, dc = ImageDraw.Draw(line), ImageDraw.Draw(col)
    for poly, fcol in (closed_fill or []):
        pts = [(x * ss, y * ss) for x, y in poly]
        dc.polygon(pts, fill=rgba(fcol))
    for poly in polylines:
        pts = [(x * ss, y * ss) for x, y in poly]
        if len(pts) == 1:
            x, y = pts[0]
            r = width * ss / 2
            for d in (dl, dc):
                d.ellipse((x - r, y - r, x + r, y + r), fill=rgba(color))
            continue
        for d in (dl, dc):
            d.line(pts, fill=rgba(color), width=int(width * ss), joint='curve')
            r = width * ss / 2
            for x, y in (pts[0], pts[-1]):
                d.ellipse((x - r, y - r, x + r, y + r), fill=rgba(color))
    line = line.resize((w, h), Image.LANCZOS)
    col = col.resize((w, h), Image.LANCZOS)
    dens = []
    for poly in polylines:
        pts = np.asarray(poly, np.float32)
        if len(pts) > 1:
            seg = np.hypot(*np.diff(pts, axis=0).T)
            n = np.maximum(1, (seg / 3).astype(int))
            fine = [pts[0]]
            for a, b, k in zip(pts[:-1], pts[1:], n):
                for s in range(1, k + 1):
                    fine.append(a + (b - a) * s / k)
            pts = np.asarray(fine, np.float32)
        dens.append(pts)
    drawing = PathDrawing(col, line if closed_fill else col, dens, brush=width * .9 + 1.5,
                          speed=speed, min_dur=min_dur, max_dur=max_dur, pop=pop if closed_fill else .01)
    drawing.native_recipe = ('strokes', (tuple(size), polylines), dict(color=color, width=width,
        fill=fill, closed_fill=closed_fill, speed=speed, min_dur=min_dur, max_dur=max_dur, pop=pop, ss=ss))
    return drawing


# ---------------------------------------------------------------- text drawings
def _skeleton(binary):
    a = np.pad(binary.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p = [a[:-2, 1:-1], a[:-2, 2:], a[1:-1, 2:], a[2:, 2:],
                 a[2:, 1:-1], a[2:, :-2], a[1:-1, :-2], a[:-2, :-2]]
            count = sum(p)
            transitions = sum((p[i] == 0) & (p[(i + 1) % 8] == 1) for i in range(8))
            remove = (a[1:-1, 1:-1] == 1) & (count >= 2) & (count <= 6) & (transitions == 1)
            if step == 0:
                remove &= (p[0] * p[2] * p[4] == 0) & (p[2] * p[4] * p[6] == 0)
            else:
                remove &= (p[0] * p[2] * p[6] == 0) & (p[0] * p[4] * p[6] == 0)
            if remove.any():
                a[1:-1, 1:-1][remove] = 0
                changed = True
        if not changed:
            return a[1:-1, 1:-1].astype(bool)


def _routes(mask):
    pts = {tuple(p) for p in np.argwhere(mask)}
    graph = {p: set() for p in pts}
    for y, x in pts:
        for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            q = (y + dy, x + dx)
            if q in pts and not (dy and dx and ((y + dy, x) in pts or (y, x + dx) in pts)):
                graph[y, x].add(q)
    result = [[p] for p in pts if not graph[p]]
    while any(graph.values()):
        endpoints = [p for p, ns in graph.items() if len(ns) == 1]
        candidates = endpoints or [p for p, ns in graph.items() if ns]
        start = min(candidates, key=lambda p: (p[0], p[1]))
        path, previous, at = [start], None, start
        while graph[at]:
            def preference(q, previous=previous, at=at):
                if previous is None:
                    return (q[1] < at[1], q[0] < at[0], q)
                v = np.array(at) - previous
                u = np.array(q) - at
                return (-float(np.dot(v, u)) / (np.linalg.norm(v) * np.linalg.norm(u)), q)
            nxt = min(graph[at], key=preference)
            graph[at].remove(nxt)
            graph[nxt].remove(at)
            previous, at = at, nxt
            path.append(at)
        result.append(path)
    return sorted(result, key=lambda path: (len(path) < 3, min(p[0] for p in path), min(p[1] for p in path)))


@lru_cache(maxsize=4096)
def _glyph_path(data, size):
    alpha = np.frombuffer(data, dtype=np.uint8).reshape(size[1], size[0])
    skel = _skeleton(alpha > 64)
    if not skel.any():
        skel = alpha > 0
    return skel, _routes(skel)


class TextDrawing:
    """Glyph-stroke handwriting (port of the accepted 9/7 InkTrace).

    Every glyph, digits included, is written by the pen in reading order.
    """

    def __init__(self, lines, lang, size, color=INK, align='left', line_gap=1.18, pace=1.0,
                 min_dur=.6, max_dur=6.0, pad=6, fonts: Fonts = FONTS):
        self.native_recipe = ('text', (list(lines), lang, size), dict(color=color, align=align,
            line_gap=line_gap, pace=pace, min_dur=min_dur, max_dur=max_dur, pad=pad, fonts=fonts))
        f = hand_font(lang, size, fonts)
        self.lines, self.lang = lines, lang
        widths = [text_width(line, lang, size, fonts) for line in lines]
        asc, desc = f.getmetrics()
        lh = int(size * line_gap)
        w = int(math.ceil(max(widths or [1]))) + 2 * pad
        h = lh * (len(lines) - 1) + asc + desc + 2 * pad
        self.size = (w, h)
        ink = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(ink)
        runs = []
        for i, line in enumerate(lines):
            x = pad if align == 'left' else (pad + (w - 2 * pad - widths[i]) / 2 if align == 'center' else w - pad - widths[i])
            y = pad + i * lh
            chars = []
            for part, pf in font_runs(line, lang, size, fonts):
                d.text((x, y), part, font=pf, fill=rgba(color))
                for k, ch in enumerate(part):
                    chars.append((ch, x + pf.getlength(part[:k]), x + pf.getlength(part[:k + 1])))
                x += pf.getlength(part)
            runs.append((line, chars, y, f))
        self.ink = ink
        self.placed = [(chars, y, f.getmetrics()) for _, chars, y, f in runs]   # where each character is
        self._trace(runs, pace, min_dur, max_dur)

    def _trace(self, runs, pace, min_dur, max_dur):
        ink = self.ink
        alpha = np.asarray(ink.getchannel('A'))
        arrival = np.full(alpha.shape, np.inf, np.float32)
        times, points, down = [], [], []
        clock, last, letters = 0., None, 0
        for line, chars, y, f in runs:
            bbox = f.getbbox(line)
            top, bottom = max(0, int(y + min(0, bbox[1])) - 2), min(ink.height, int(math.ceil(y + bbox[3])) + 4)
            for i, (ch, cx0, cx1) in enumerate(chars):
                x0 = max(0, int(math.floor(cx0)))
                x1 = min(ink.width, int(math.ceil(cx1)))
                region = alpha[top:bottom, x0:x1]
                if ch.isspace() or not region.any():
                    continue
                ys = np.nonzero(region.any(1))[0]
                y0, y1 = top + int(ys[0]), top + int(ys[-1]) + 1
                patch = np.ascontiguousarray(alpha[y0:y1, x0:x1])
                skel, paths = _glyph_path(patch.tobytes(), (patch.shape[1], patch.shape[0]))
                local = np.full(patch.shape, np.inf, np.float32)
                for path in paths:
                    first = (x0 + path[0][1], y0 + path[0][0])
                    if last is not None:
                        distance = math.dist(last, first)
                        lift = .08 + min(.24, distance / 1600)
                        times.extend([clock, clock + lift])
                        points.extend([last, first])
                        down.extend([False, False])
                        clock += lift
                    for j, (py, px) in enumerate(path):
                        point = (x0 + px, y0 + py)
                        if j:
                            clock += math.dist(point, last) / 160
                        local[py, px] = min(local[py, px], clock)
                        times.append(clock)
                        points.append(point)
                        down.append(True)
                        last = point
                    if len(path) == 1:
                        clock += .015
                _, near = ndimage.distance_transform_edt(~skel, return_indices=True)
                mapped = local[near[0], near[1]]
                dest = arrival[y0:y1, x0:x1]
                np.minimum(dest, np.where(patch > 0, mapped, np.inf), out=dest)
                letters += 2 if is_cjk(ch) else 1
        if not times:
            self.duration, self.times, self.points, self.down = .01, np.zeros(1), np.zeros((1, 2)), np.zeros(1, bool)
            self.arrival, self.alpha = np.zeros(alpha.shape, np.float32), alpha
            return
        missing = (alpha > 0) & ~np.isfinite(arrival)
        if missing.any():
            _, near = ndimage.distance_transform_edt(~np.isfinite(arrival), return_indices=True)
            arrival[missing] = arrival[near[0], near[1]][missing]
        # Reference pacing: short heading ~2.3-2.9 s, long line ~4.5 s (meitoujun study);
        # labels a little faster so the board keeps up with speech.
        duration = (.4 + .055 * letters + .18 * (len(runs) - 1)) / pace
        self.duration = min(max_dur, max(min_dur, duration))
        scale = self.duration / max(clock, .001)
        self.arrival = arrival * scale
        self.times = np.asarray(times) * scale
        self.points = np.asarray(points, float)
        self.down = np.asarray(down)
        self.alpha = alpha

    def state(self, elapsed):
        if elapsed >= self.duration:
            return self.ink, None, False
        if elapsed < 0:
            return None, None, False
        a = np.where(self.arrival <= elapsed, self.alpha, 0).astype(np.uint8)
        out = self.ink.copy()
        out.putalpha(Image.fromarray(a))
        j = min(len(self.times) - 1, int(np.searchsorted(self.times, elapsed, side='right')))
        i = max(0, j - 1)
        span = self.times[j] - self.times[i]
        f = 0 if span <= 0 else min(1, max(0, (elapsed - self.times[i]) / span))
        point = self.points[i] * (1 - f) + self.points[j] * f
        return out, (float(point[0]), float(point[1])), bool(self.down[j])


def wrap_words(text, lang, size, max_width, kind='hand', fonts: Fonts = FONTS):
    """Greedy wrap for board text; split words that cannot fit on an empty line."""
    f = hand_font(lang, size, fonts) if kind == 'hand' else \
        font('en_caption' if lang in ('en', 'es') else 'zh_caption', size, fonts)
    width = (lambda s: text_width(s, lang, size, fonts)) if kind == 'hand' else f.getlength
    units = re.findall(r'\S+\s*', text) if lang in ('en', 'es') else re.findall(r"[A-Za-z0-9$.,%×\-–/+']+\s*|.", text)
    lines, cur = [], ''
    for u in units:
        if width(u.rstrip()) > max_width:
            if cur.strip():
                lines.append(cur.rstrip())
            cur = ''
            for ch in u:
                if cur and width(cur + ch) > max_width:
                    lines.append(cur.rstrip())
                    cur = ''
                cur += ch
            continue
        trial = cur + u
        if cur and width(trial.rstrip()) > max_width:
            if lang == 'zh' and re.match(r'[，。！？；：、）」』”’%]', u):
                cur = trial
                continue
            lines.append(cur.rstrip())
            cur = u.lstrip() if lang in ('en', 'es') else u
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def fit_text(text, lang, max_width, max_lines, size, min_size=30, fonts: Fonts = FONTS):
    while True:
        lines = wrap_words(text, lang, size, max_width, fonts=fonts)
        if len(lines) <= max_lines or size <= min_size:
            return lines, size
        size -= 2


# --------------------------------------------------------------- static stamps
class StaticDrawing:
    """A picture that appears (fade over ``pop`` s) — photos only."""

    def __init__(self, image, pop=.35):
        self.image, self.size, self.duration = image, image.size, pop
        self.native_photo = image.info.get('native_photo')

    def state(self, elapsed):
        if elapsed < 0:
            return None, None, False
        if elapsed >= self.duration:
            return self.image, None, False
        out = self.image.copy()
        out.putalpha(out.getchannel('A').point(lambda a: int(a * elapsed / self.duration)))
        return out, None, False


def circle_photo(path, diameter, ring=8, color=INK):
    img = Image.open(path).convert('RGB')
    side = min(img.size)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                    (img.width + side) // 2, (img.height + side) // 2)).resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new('L', (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    mask = mask.resize((diameter, diameter), Image.LANCZOS)
    out = Image.new('RGBA', (diameter, diameter), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    out.info['native_photo'] = (str(path), diameter, ring, color)
    return out


def circle_points(cx, cy, rx, ry, start=-math.pi / 2, turns=1.0, n=90, wobble=0.):
    ts = np.linspace(0, 2 * math.pi * turns, n)
    rr = 1 + wobble * np.sin(ts * 3)
    return [(cx + rx * rr[i] * math.cos(start + t), cy + ry * rr[i] * math.sin(start + t)) for i, t in enumerate(ts)]


# ------------------------------------------------------------------------ hand
class Hand:
    """A photographed drawing hand, pre-processed (matte cleanup, -16° tilt, faded out across the wrist: a hand, no
    forearm) into assets/hand. ``tool`` restyles what it holds, in code from the same photo (engine/skin.hand_image):
    'marker' as photographed, 'chalk' a white chalk marker, 'pencil' a yellow pencil, or 'cursor' a pixel arrow."""

    def __init__(self, tool='marker'):
        import json
        base = ASSETS / 'hand'
        if tool == 'cursor':
            from .skin import cursor_image
            self.img, self.tip = cursor_image()
        else:
            self.img = Image.open(base / 'hand.png').convert('RGBA')
            if tool != 'marker':
                from .skin import hand_image
                self.img = hand_image(self.img, tool)
            anchor = json.loads((base / 'hand.json').read_text(encoding='utf-8'))
            self.tip = (anchor['tip_x'], anchor['tip_y'])
        shadow = Image.new('RGBA', self.img.size, (0, 0, 0, 0))
        shadow.putalpha(self.img.getchannel('A').point(lambda v: int(v * .18)).filter(ImageFilter.GaussianBlur(9)))
        self.shadow = shadow
        self.paths = [] if tool == 'cursor' else [base / 'hand.png', base / 'hand.json']

    def paste(self, frame, point, lifted=False):
        x = int(round(point[0] - self.tip[0]))
        y = int(round(point[1] - self.tip[1] - (6 if lifted else 0)))
        frame.alpha_composite(self.shadow, (max(-self.img.width, x + 14), y + 18)) if -self.img.width < x < frame.width else None
        if -self.img.width < x < frame.width and -self.img.height < y < frame.height:
            frame.alpha_composite(self.img, (x, y)) if x >= 0 and y >= 0 else _paste_clip(frame, self.img, x, y)


def _paste_clip(frame, img, x, y):
    left, top = max(0, -x), max(0, -y)
    crop = img.crop((left, top, img.width, img.height))
    frame.alpha_composite(crop, (max(0, x), max(0, y)))


def paste(frame, img, x, y):
    """alpha_composite with clipping at any edge."""
    if img is None:
        return
    x, y = int(round(x)), int(round(y))
    if x >= frame.width or y >= frame.height or x + img.width <= 0 or y + img.height <= 0:
        return
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(img.width, frame.width - x), min(img.height, frame.height - y)
    if left or top or right < img.width or bottom < img.height:
        img = img.crop((left, top, right, bottom))
    frame.alpha_composite(img, (max(0, x), max(0, y)))

"""Library doodles redrawn in the stick look: pure black outlines a few pixels wide at their on-screen size, every
fill and coloured line snapped to the 16-colour palette, three boil drawings (a sub-pixel turn and shift each)."""
from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path

import resvg_py
import svgelements
from PIL import Image

from ...library import MISSING, resolve
from . import palette

LINE_PX = 2.6                       # main outline width on screen (the library draws main outlines at 6 units)
MIN_LINE_PX = 1.4
_HEX = re.compile(r'(fill|stroke)="(#[0-9A-Fa-f]{3,6})"')
_WIDTH = re.compile(r'stroke-width="([0-9.]+)"')
_ROOT = re.compile(r'(<svg\b[^>]*>)(.*)(</svg>)', re.S)
BOIL = [(0., 0., 0.), (.35, .7, -.5), (-.3, -.6, .6)]      # (degrees, dx px, dy px) per drawing
# The shared library's own palette (assets/doodles/STYLE.md), placed by hand; anything else snaps by Lab distance.
LIBRARY = {'E53935': 'red', '1E6FD9': 'blue', '64B5F6': 'sky', '1A3A6B': 'blue', '43A047': 'green',
           '9CCC65': 'lime', 'FDD835': 'yellow', 'F9A825': 'yellow', 'FB8C00': 'orange', '8E24AA': 'purple',
           '00897B': 'green', 'F48FB1': 'pink', '8D6E63': 'brown', 'D7B98E': 'tan', 'F6C9A4': 'tan',
           'E8A87C': 'tan', 'FFFFFF': 'white', 'E0E0E0': 'silver', '9E9E9E': 'grey', '424242': 'grey',
           '1B1B1B': 'black', 'FFF8E1': 'white', '7E93A8': 'grey', 'B8C6D3': 'silver', 'B08D57': 'brown'}


def _viewbox(text: str):
    doc = svgelements.SVG.parse(io.StringIO(text))
    vb = doc.viewbox
    if vb is not None:
        return float(vb.x), float(vb.y), float(vb.width), float(vb.height)
    return 0., 0., float(doc.width), float(doc.height)


def restyle(text: str, scale: float) -> str:
    """The SVG with Paint-style lines (``scale`` = screen px per SVG unit) and palette colours."""
    def width(m):
        px = max(MIN_LINE_PX, float(m.group(1)) / 6. * LINE_PX)
        return f'stroke-width="{px / scale:.3f}"'

    def colour(m):
        kind, value = m.group(1), m.group(2)
        rgb = palette.parse_hex(value)
        if rgb is None:
            return m.group(0)
        if kind == 'stroke' and max(rgb) < 60:
            return f'{kind}="#000000"'
        named = LIBRARY.get('%02X%02X%02X' % rgb)
        if named:
            return f'{kind}="{palette.hexcode(named)}"'
        return f'{kind}="{palette.hexcode(palette.nearest(rgb))}"'
    return _HEX.sub(colour, _WIDTH.sub(width, text))


@lru_cache(maxsize=512)
def render_svg(path: str, box_w: int, box_h: int, variant: int = 0) -> Image.Image:
    """The doodle at ``path`` fitted inside box_w x box_h, in Paint style, boil drawing ``variant``."""
    text = Path(path).read_text(encoding='utf-8')
    vx, vy, vw, vh = _viewbox(text)
    scale = min(box_w / vw, box_h / vh)
    out_w, out_h = max(1, round(vw * scale)), max(1, round(vh * scale))
    styled = restyle(text, scale)
    deg, dx, dy = BOIL[variant % 3]
    if deg or dx or dy:
        cx, cy = vx + vw / 2, vy + vh / 2
        m = _ROOT.search(styled)
        if m:
            styled = (styled[:m.start(2)] + f'<g transform="translate({dx / scale:.3f} {dy / scale:.3f}) '
                      f'rotate({deg} {cx:.2f} {cy:.2f})">' + m.group(2) + '</g>' + styled[m.end(2):])
    png = resvg_py.svg_to_bytes(svg_string=styled, width=out_w, height=out_h)
    img = Image.open(io.BytesIO(bytes(png))).convert('RGBA')
    if img.size != (out_w, out_h):              # resvg keeps the aspect from the width and can round a pixel up
        img = img.resize((out_w, out_h), Image.LANCZOS)
    return img


def doodle(doodle_id: str, box: tuple, variant: int = 0, project_dir=None) -> Image.Image:
    path = resolve(doodle_id, project_dir) or MISSING
    return render_svg(str(path), int(box[0]), int(box[1]), int(variant) % 3)

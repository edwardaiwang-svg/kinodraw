"""Skins: one look's paper, ink, line grain, fills, fonts, hand and chrome over the whiteboard renderer.

Builders draw in the whiteboard's reference palette (ink.INK, SOFT_INK, the section colours, white cards, yellow
notes). Every drawing passes through ``Skin.dress`` once, when it is added to the board, and the skin maps that
palette to its own: line colours, then line grain, then fills. The whiteboard skin changes nothing, so its frames
are the renderer's own. The skin of a look comes from its registry entry (doodlestudio/styles/registry.json).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PIL import Image

from . import ink


@dataclass(frozen=True)
class Skin:
    id: str = 'whiteboard'
    paper: str = 'whiteboard'           # background: whiteboard (ink.paper)
    lines: str = 'identity'             # how line and text colours map
    fills: str = 'identity'             # how fills map
    grain: str = 'none'                 # texture of every mark
    hand: str = 'marker'                # what the hand holds
    emphasis: str = 'none'              # each sentence's key phrase on the board
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
        return ink.paper(width, height)

    def color(self, rgb) -> tuple:
        """One reference colour as this skin draws it (chrome, thumbnails)."""
        return tuple(rgb[:3])

    def dress(self, drawing, x=0, y=0):
        """Restyle a drawing in place (its images are replaced, never edited) and return it; (x, y) is where it
        sits on the board, which anchors its grain."""
        return drawing


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

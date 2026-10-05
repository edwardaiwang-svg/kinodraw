"""Shared board dimensions and screen safe zones."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Geometry:
    name: Literal['landscape', 'portrait']
    size: tuple[int, int]
    col: int
    cols_on_screen: int
    cell_x0: int
    cell_w: int
    rows: tuple[tuple[int, int], ...]
    page_box: tuple[int, int, int, int]
    pan_seconds: float
    dwell_max: float
    opener_cols: int
    title_band: tuple[int, int, int, int] | None = None
    board_band: tuple[int, int, int, int] | None = None
    caption_band: tuple[int, int, int, int] | None = None
    rail: tuple[int, int, int, int] | None = None
    bottom_ui: tuple[int, int, int, int] | None = None
    top_ui: tuple[int, int, int, int] | None = None
    text_safe: tuple[tuple[int, int, int, int], ...] | None = None

    def text_safe_ok(self, box) -> bool:
        """Whether a screen text box clears the frame and platform UI."""
        x0, y0, x1, y1 = box
        if self.text_safe is None:
            return 0 <= x0 <= x1 <= self.size[0] and 0 <= y0 <= y1 <= self.size[1]
        upper, lower = self.text_safe
        return (upper[1] <= y0 <= y1 <= lower[3] and
                upper[0] <= x0 <= x1 <= (upper[2] if y1 <= upper[3] else lower[2]))


# docs: safe-zones.md (K1, 2026-10-04)
LANDSCAPE = Geometry(
    'landscape', (1920, 1080), 640, 3, 50, 540, ((84, 440), (466, 822)), (60, 84, 1800, 738), .9, 3.5, 2,
)
PORTRAIT = Geometry(
    'portrait', (1080, 1920), 1080, 1, 88, 800, ((590, 905), (935, 1250)), (88, 590, 800, 660), .9, 3.5, 1,
    title_band=(88, 288, 992, 570), board_band=(88, 590, 992, 1250),
    caption_band=(192, 1268, 888, 1500), rail=(888, 600, 1080, 1920),
    bottom_ui=(0, 1500, 1080, 1920), top_ui=(0, 0, 1080, 288),
    text_safe=((88, 288, 992, 600), (88, 600, 888, 1250)),
)


# Native square board: 5% edges, dedicated caption band, no landscape crop.
SQUARE = Geometry(
    'landscape', (1080, 1080), 1080, 1, 64, 952,
    ((140, 470), (490, 820)), (64, 140, 952, 680), .9, 3.5, 1,
    title_band=(64, 54, 1016, 130), board_band=(64, 140, 1016, 820),
    caption_band=(64, 850, 1016, 1016),
    text_safe=((54, 54, 1026, 850), (54, 850, 1026, 1026)),
)


def geometry_for_size(size, aspect='16:9'):
    """Scale layout coordinates before generating drawings, never resize frames.

    Unchanged baseline sizes return their original immutable geometry.
    """
    from dataclasses import replace
    base = {'16:9': LANDSCAPE, '9:16': PORTRAIT, '1:1': SQUARE}[aspect]
    size = tuple(size)
    if len(size) != 2 or any(not isinstance(v, int) or v <= 0 for v in size):
        raise ValueError('size requires positive integer dimensions')
    if size[0] * base.size[1] != size[1] * base.size[0]:
        raise ValueError('size must match aspect')
    if size == base.size:
        return base
    scale = size[0] / base.size[0]
    def coords(value):
        if value is None:
            return None
        return tuple(coords(v) if isinstance(v, tuple) else round(v * scale) for v in value)
    fields = ('col', 'cell_x0', 'cell_w', 'rows', 'page_box', 'title_band', 'board_band',
              'caption_band', 'rail', 'bottom_ui', 'top_ui', 'text_safe')
    return replace(base, size=size, **{key: coords(getattr(base, key)) if isinstance(getattr(base, key), tuple)
                                    or getattr(base, key) is None else round(getattr(base, key) * scale)
                                    for key in fields})

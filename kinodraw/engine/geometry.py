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

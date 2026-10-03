"""Every library doodle redraws in the Paint style: black outlines, palette colours, all three boil drawings."""
import re

import numpy as np
import pytest

from kinodraw.library import ASSETS, MISSING, SETS
from kinodraw.engine.stick import paint, palette

ALL = sorted(p for s in SETS for p in (ASSETS / s).glob('*.svg')) + [MISSING]
ALLOWED = {palette.hexcode(name).lower() for name in palette.PALETTE}
COLOUR = re.compile(r'(?:fill|stroke)="(#[0-9A-Fa-f]{3,6})"')


def test_library_is_all_there():
    assert len(ALL) > 1500


@pytest.mark.parametrize('chunk', range(8))
def test_every_doodle_renders_in_paint_style(chunk):
    for i, path in enumerate(ALL):
        if i % 8 != chunk:
            continue
        text = path.read_text(encoding='utf-8')
        styled = paint.restyle(text, 96 / 512)
        off = {c.lower() for c in COLOUR.findall(styled)} - ALLOWED
        assert not off, f'{path.name}: colours outside the palette {sorted(off)}'
        img = paint.render_svg(str(path), 96, 96, i % 3)
        assert img.mode == 'RGBA' and max(img.size) <= 96
        assert np.asarray(img)[..., 3].any(), f'{path.name} rendered empty'


def test_unknown_doodle_falls_back_to_missing():
    img = paint.doodle('no_such_doodle_here', (120, 120))
    assert np.asarray(img)[..., 3].any()

import numpy as np

from kinodraw.engine.bold import MotionElement, MotionScene
from kinodraw.engine.bold.render import _raster, scene_svg


def test_svg_style_preserves_opacity_and_stroke_width():
    raw = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<rect x="10" y="10" width="80" height="80" style="fill:red;opacity:0"/></svg>')
    scene = MotionScene(elements=[MotionElement(kind='picture', svg=raw)], motion_floor=0, glow=0)
    assert not _raster(scene_svg(scene, 2, 'emissive'), 320, 180)[..., 3].any()
    doc = scene_svg(scene, 2, 'art')
    assert 'opacity="0"' in doc
    raw = raw.replace('fill:red;opacity:0', 'fill:none;stroke:red;stroke-width:12')
    scene.elements[0].svg = raw
    assert 'stroke-width="12"' in scene_svg(scene, 2, 'art')


def test_cjk_text_fits_the_actual_noto_font_width():
    e = MotionElement(text='汉字' * 30, size=96, width=1000, preset='type_on')
    scene = MotionScene(elements=[e], motion_floor=0, glow=0)
    pixels = _raster(scene_svg(scene, 10, 'text'), 1920, 1080, text=True)
    columns = np.flatnonzero(pixels[..., 3].max(axis=0))
    assert len(columns) and columns[-1] - columns[0] + 1 <= 1000

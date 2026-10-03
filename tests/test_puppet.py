"""The paper puppet renders every pose and expression, the same way every time."""
import numpy as np

from doodlestudio.engine.collage import puppet


def test_every_pose_and_expression_renders():
    for pose in puppet.POSES:
        for expression in puppet.EXPRESSIONS:
            img = puppet.raster(pose, expression, 0, 'sunny', height=240)
            alpha = np.asarray(img.getchannel('A'))
            assert img.mode == 'RGBA' and (alpha > 0).mean() > 0.12        # a solid figure, not an empty frame


def test_the_same_pose_is_the_same_pixels_and_walking_moves_the_legs():
    a = np.asarray(puppet.raster.__wrapped__('walk', 'smile', 0, 'breeze', height=240))
    b = np.asarray(puppet.raster.__wrapped__('walk', 'smile', 0, 'breeze', height=240))
    c = np.asarray(puppet.raster.__wrapped__('walk', 'smile', 2, 'breeze', height=240))
    assert (a == b).all() and not (a == c).all()


def test_colours_come_from_the_preset_or_the_storyboard():
    doc = puppet.svg('stand', 'smile', preset='sunny', colors={'top': '#123456'})
    assert '#123456' in doc and puppet.PRESETS['sunny']['hat'] in doc

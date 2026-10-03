"""The stick figure rig: every pose in the library draws, and the same seed always gives the same pixels."""
import numpy as np
import pytest

from doodlestudio.engine.stick import rig

REQUIRED = {'stand', 'point', 'walk', 'run', 'think', 'shrug', 'wave', 'sit', 'fall', 'cheer', 'sad', 'angry',
            'talk', 'hold', 'crowd'}


def pixels(drawn):
    return np.asarray(drawn.image)


def test_pose_library_is_complete():
    assert REQUIRED <= set(rig.POSES)


@pytest.mark.parametrize('pose', sorted(REQUIRED - {'crowd'}))
def test_every_pose_draws_every_frame(pose):
    for k in range(rig.cycle_len(pose)):
        dr = rig.draw(rig.Figure(pose=pose, height=600, seed=4), k, k % 3)
        alpha = pixels(dr)[..., 3]
        assert alpha.any(), f'{pose} frame {k} is empty'
        assert max(dr.image.size) < 2.5 * 600          # a lying figure is wider than tall, but bounded


def test_same_seed_same_pixels():
    fig = rig.Figure(pose='walk', height=520, hat='helmet', shirt='orange', seed=77)
    first = [pixels(rig.draw(fig, k, v)).copy() for k in range(4) for v in range(3)]
    rig._draw_cached.cache_clear()
    again = [pixels(rig.draw(fig, k, v)) for k in range(4) for v in range(3)]
    assert all(np.array_equal(a, b) for a, b in zip(first, again))
    other = pixels(rig.draw(rig.Figure(pose='walk', height=520, hat='helmet', shirt='orange', seed=78), 0, 0))
    assert not (other.shape == first[0].shape and np.array_equal(other, first[0]))


def test_boil_drawings_differ():
    fig = rig.Figure(pose='stand', height=600, seed=3)
    a, b = pixels(rig.draw(fig, 0, 0)), pixels(rig.draw(fig, 0, 1))
    assert not (a.shape == b.shape and np.array_equal(a, b))


def test_lines_are_about_three_pixels_at_full_height():
    assert 2. <= rig.line_width(600) <= 3.
    assert rig.line_width(300) >= 2.
    assert rig.line_width(1150) > rig.line_width(600)


@pytest.mark.parametrize('n', range(3, 8))
def test_crowds_of_three_to_seven(n):
    crowd = rig.Crowd(n=n, height=420, mood='calm', seed=n)
    assert len(rig.crowd_members(crowd)) == n
    first = pixels(rig.draw_crowd(crowd, 1, 2)).copy()
    rig._draw_cached.cache_clear()
    assert np.array_equal(first, pixels(rig.draw_crowd(crowd, 1, 2)))

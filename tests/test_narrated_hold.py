"""A held page stays up until the picture changes on the score beat after its words: the pancakes' bowl insert froze
0.32 s past its sentence (22.567-24.667 s, words ending 24.345) and QA failed it as a frozen picture. A narrated page
may hold up to a natural pause (NATURAL_PAUSE) past its last word; a still picture longer than that with no
narration is still a frozen picture."""
import subprocess

import imageio_ffmpeg
import pytest

from kinodraw import pipeline
from kinodraw.qa.probes import probe


@pytest.fixture(scope='module')
def frozen(tmp_path_factory):
    path = tmp_path_factory.mktemp('hold') / 'frozen.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=red:size=160x90:rate=30:duration=4', '-f', 'lavfi', '-i',
                    'sine=frequency=440:sample_rate=48000:duration=4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-shortest', str(path)], check=True, capture_output=True)
    return path


def pages(first_words_end, second_start):
    """Narrated pages of two character scenes: the first speaks until ``first_words_end``, the second from
    ``second_start``."""
    scene = lambda bid: {'beat_ids': [bid], 'treatment': 'character', 'elements': []}
    cfg = {'director_v3': True, 'plan_v3': {'style': {'mode': 'hybrid'}, 'scenes': [scene('b1'), scene('b2')]}}
    tl = {'beats': {'b1': {'start': 0., 'speech_end': first_words_end},
                    'b2': {'start': second_start, 'speech_end': second_start + 3}}}
    return pipeline._narrated_pages(cfg, tl)


def test_a_page_holding_a_moment_past_its_words_into_the_next_scene_is_a_held_page(frozen):
    assert probe(frozen, narrated_pages=pages(3.63, 3.63)).package_ok        # 0.37 s past its last word


def test_a_still_picture_with_no_narration_past_a_natural_pause_is_still_frozen(frozen):
    report = probe(frozen, narrated_pages=pages(3.2, 4.6))                  # 0.8 s of silence on a still page
    assert any(f.defect == 'frozen_picture' for f in report.findings) and not report.package_ok


def _still_between(path, before, still, after):
    """A video that moves (a test pattern) for ``before`` s, holds one still picture for ``still`` s, then moves
    again for ``after`` s."""
    moving = lambda d: f'testsrc=size=160x90:rate=30:duration={d}'
    total = before + still + after
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-v', 'error',
                    '-f', 'lavfi', '-i', moving(before), '-f', 'lavfi', '-i', f'color=c=white:size=160x90:rate=30:duration={still}',
                    '-f', 'lavfi', '-i', moving(after), '-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=48000:duration={total}',
                    '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]', '-map', '[v]', '-map', '3:a',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(path)],
                   check=True, capture_output=True)
    return path


def whiteboard_pages(start, speech_end):
    """Narrated pages of an all-whiteboard plan whose one scene speaks from ``start`` to ``speech_end``."""
    cfg = {'director_v3': True, 'plan_v3': {'style': {'mode': 'whiteboard'},
                                            'scenes': [{'beat_ids': ['b1'], 'treatment': 'whiteboard', 'elements': []}]}}
    return pipeline._narrated_pages(cfg, {'beats': {'b1': {'start': start, 'speech_end': speech_end}}})


def test_a_whiteboard_page_held_still_inside_its_narration_is_a_held_page(tmp_path):
    """The drawing hand leaves the page over a long pause instead of resting or drifting on it (J 10/8: no idle
    sway), so a whiteboard page can hold still for a few seconds while its narration goes on: a held page."""
    video = _still_between(tmp_path / 'held.mp4', 1., 2.4, 1.)
    report = probe(video, narrated_pages=whiteboard_pages(0., 4.4))
    assert report.package_ok and report.held_pages, report.findings


def test_a_still_whiteboard_page_outside_its_narration_or_past_held_page_is_frozen(tmp_path):
    from kinodraw.qa.probes import HELD_PAGE
    video = _still_between(tmp_path / 'silent.mp4', 1., 2.4, 1.)
    report = probe(video, narrated_pages=whiteboard_pages(0., .9))           # the words end before the page stills
    assert any(f.defect == 'frozen_picture' for f in report.findings) and not report.package_ok
    video = _still_between(tmp_path / 'long.mp4', .5, HELD_PAGE + 1, .5)
    report = probe(video, narrated_pages=whiteboard_pages(0., HELD_PAGE + 2))
    assert any(f.defect == 'frozen_picture' for f in report.findings) and not report.package_ok

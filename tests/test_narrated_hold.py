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

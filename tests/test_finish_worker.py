"""Real package launcher, staged finish, and owned worker process acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

from kinodraw import pipeline, voice
from kinodraw.audio import mix
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render
from kinodraw.package import _probe
from kinodraw.progress import RenderContext
from kinodraw.project_store import ProjectStore, RevisionConflict


class MovingFrames:
    size = (1920, 1080)
    def frame(self, t):
        image = Image.new('RGB', self.size, (80, 90, 100))
        x = int(t * 350) % 1600
        ImageDraw.Draw(image).rectangle((x, 200, x + 250, 600), fill=(240, 210, 80))
        return image


@pytest.fixture
def cached_project(tmp_path):
    project = tmp_path / 'project'
    pipeline.new_project('# Worker\n\nA small idea.', project, workers=1, credit=False)
    store = ProjectStore(project)
    saved = store.load()
    cfg, board = saved['settings'], saved['storyboard']
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', music_mood='none')
    for scene in plan['scenes']:
        scene['treatment'] = 'kinetic_type'
    cfg.update(director_v3=True, plan_v3=plan, scene_treatments=plan['scenes'])
    store.save(board, cfg, saved['revision'])
    clips = {}
    for index, beat in enumerate(board['beats']):
        samples = np.arange(int(.4 * voice.SR), dtype=np.float32) / voice.SR
        wav = project / 'voice' / f'{index}.wav'
        wav.parent.mkdir(exist_ok=True)
        mix.write_wav(wav, .12 * np.sin(2 * np.pi * 440 * samples), voice.SR)
        text = beat['spoken']['en']
        clips[beat['id']] = voice.Clip(wav, .4, np.linspace(0, .4, len(text) + 1).tolist())
    timeline = pipeline.build_audio(project, clips)
    render.encode(MovingFrames(), 0, round(timeline['duration'] * render.FPS), project / 'build/silent.mp4', 20)
    return project


def test_actual_packaging_launcher_finish_and_full_decode(cached_project):
    launch = Path(__file__).resolve().parents[1] / 'packaging/launch.py'
    done = subprocess.run([sys.executable, str(launch), '--finish-worker', str(cached_project)],
                          capture_output=True, timeout=40)
    assert done.returncode == 0, done.stderr.decode(errors='replace')
    qa = pipeline._load(cached_project / 'build/qa.json')
    assert qa['ok'], qa
    video = Path(qa['video'])
    decoded = subprocess.run([render.FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode',
                              '-i', str(video), '-f', 'null', '-'], capture_output=True, timeout=20)
    assert decoded.returncode == 0, decoded.stderr
    info = _probe(video)
    assert info['audio'] and info['frames'] == qa['frames'] and not info['errors']
    assert (cached_project / 'Worker-transcript.md').is_file()
    print(json.dumps({'launcher_exit': done.returncode, 'decode_exit': decoded.returncode,
                      'frames': info['frames'], 'duration': qa['duration'], 'audio': info['audio']}))


def test_finish_command_nonfrozen_and_frozen_dispatch(monkeypatch, tmp_path):
    assert pipeline._finish_command(tmp_path) == [sys.executable, '-m', 'kinodraw.pipeline', '--finish-worker', str(tmp_path)]
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert pipeline._finish_command(tmp_path) == [sys.executable, '--finish-worker', str(tmp_path)]


def test_staged_finish_preserves_good_video_on_actual_worker_failure(cached_project):
    previous = cached_project / 'Worker.mp4'
    previous.write_bytes(b'previous-good-output')
    (cached_project / 'build/silent.mp4').write_bytes(b'invalid-synthetic-input')
    ctx = RenderContext()
    with pytest.raises(RuntimeError, match='finish worker exited 1'):
        pipeline.finish(cached_project, context=ctx)
    assert previous.read_bytes() == b'previous-good-output'
    assert not ctx.token.owned_pids
    assert not (cached_project / 'build/qa.json').exists()


def test_real_finished_worker_revision_conflict_preserves_outputs(cached_project, monkeypatch):
    previous = cached_project / 'Worker.mp4'
    previous.write_bytes(b'previous-good-output')
    real = pipeline.wait_process
    def intervening_edit(process, context):
        real(process, context)
        store = ProjectStore(cached_project)
        saved = store.load()
        saved['settings']['speed'] = 1.25
        store.save(saved['storyboard'], saved['settings'], saved['revision'])
    monkeypatch.setattr(pipeline, 'wait_process', intervening_edit)
    ctx = RenderContext()
    with pytest.raises(RevisionConflict):
        pipeline.finish(cached_project, context=ctx)
    assert previous.read_bytes() == b'previous-good-output'
    assert pipeline.settings(cached_project)['speed'] == 1.25
    assert not ctx.token.owned_pids and not (cached_project / 'build/qa.json').exists()


def test_publication_failure_rolls_back_all_replaced_outputs(tmp_path, monkeypatch):
    stage, project = tmp_path / 'stage', tmp_path / 'project'
    pipeline.new_project('# One\n\nA small idea.', stage)
    pipeline.new_project('# One\n\nA small idea.', project)
    for name in ('One.mp4', 'One.srt'):
        (stage / name).write_bytes(b'new')
        (project / name).write_bytes(b'old')
    ctx = RenderContext()
    real = ctx.token.commit
    def fail_second(source, target):
        if target.name == 'One.srt':
            raise OSError('synthetic publication failure')
        real(source, target)
    monkeypatch.setattr(ctx.token, 'commit', fail_second)
    with pytest.raises(OSError, match='synthetic publication failure'):
        pipeline._commit_outputs(stage, project, ctx)
    assert (project / 'One.mp4').read_bytes() == (project / 'One.srt').read_bytes() == b'old'
    assert not list(project.glob('.publish-*'))

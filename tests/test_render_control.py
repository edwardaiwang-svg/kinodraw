import concurrent.futures
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

import pytest
from PIL import Image

from kinodraw.engine.render import encode, render_segments
from kinodraw.progress import CancellationToken, Cancelled, RenderContext
from kinodraw import pipeline


class SlowFrames:
    size = (160, 90)
    def frame(self, t):
        time.sleep(.005)
        return Image.new('RGB', self.size, (int(t*30)%255, 80, 90))


def test_encoding_cancel_preserves_good_output_and_unrelated_process(tmp_path):
    good = tmp_path/'good.mp4'
    encode(SlowFrames(), 0, 4, good, 20)
    previous = good.read_bytes()
    token = CancellationToken()
    updates = []
    ctx = RenderContext(token, updates.append)
    unrelated = subprocess.Popen(['sleep', '30'])
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            job = pool.submit(encode, SlowFrames(), 0, 10000, good, 20, ctx)
            deadline = time.monotonic()+10
            while not any(p.frames > 0 for p in updates) and time.monotonic()<deadline:
                time.sleep(.03)
            assert any(p.frames > 0 and p.eta is not None for p in updates)
            pids = token.owned_pids
            assert pids
            token.cancel()
            with pytest.raises(Cancelled):
                job.result(timeout=5)
        assert good.read_bytes() == previous
        assert not token.owned_pids and unrelated.poll() is None
        print(json.dumps({'flow': 'encode_cancel', 'owned_groups': pids,
                          'previous_preserved': good.read_bytes() == previous,
                          'unrelated_pid': unrelated.pid, 'unrelated_alive': unrelated.poll() is None,
                          'reported_frames': updates[-1].frames}))
        assert list(tmp_path.iterdir()) == [good]
    finally:
        unrelated.terminate()
        unrelated.wait()


@pytest.mark.parametrize('workers', [1, 2])
def test_segment_cancel_owned_groups(tmp_path, workers):
    project = tmp_path/'project'
    pipeline.new_project('A lesson.\n\nCount three circles.', project, lang='en')
    output = tmp_path/'good.mp4'
    encode(SlowFrames(), 0, 4, output, 20)
    previous = output.read_bytes()
    ctx = RenderContext()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        job = pool.submit(render_segments, project, project/'storyboard.json', 'en', None,
                          0, 9000, output, workers, context=ctx)
        deadline = time.monotonic()+25
        # Wait for real FFmpeg progress, proving worker encoding has begun.
        while ctx._last <= 0 and time.monotonic()<deadline:
            time.sleep(.05)
        assert ctx._last > 0
        owned = ctx.token.owned_pids
        assert len(owned) == workers
        ctx.token.cancel()
        with pytest.raises(Cancelled):
            job.result(timeout=10)
    assert output.read_bytes() == previous
    assert not ctx.token.owned_pids
    assert not list(tmp_path.glob('.segments-*'))
    # The process groups are no longer present (includes worker FFmpeg children).
    import os
    for pid in owned:
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
    print(json.dumps({'flow': 'segment_cancel', 'workers': workers, 'owned_groups': owned,
                      'groups_absent': True, 'previous_preserved': output.read_bytes() == previous,
                      'reported_frames': ctx._last}))


def test_success_encoded_progress(tmp_path):
    updates = []
    encode(SlowFrames(), 0, 8, tmp_path/'clip.mp4', 20, RenderContext(callback=updates.append))
    assert updates[-1].frames == updates[-1].total == 8
    assert updates[-1].eta == 0


def test_failed_encode_keeps_original(tmp_path):
    class Bad(SlowFrames):
        def frame(self, t):
            raise ValueError('bad drawing')
    output = tmp_path/'good.mp4'
    output.write_bytes(b'good')
    with pytest.raises(ValueError, match='bad drawing'):
        encode(Bad(), 0, 2, output, 20)
    assert output.read_bytes() == b'good'
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize('workers', [1, 2])
def test_real_segment_join_success(tmp_path, workers):
    from kinodraw.package import _probe
    project = tmp_path/'project'
    pipeline.new_project('A lesson.\n\nCount three circles.', project, lang='en')
    output = tmp_path/'joined.mp4'
    output.write_bytes(b'previous-good')
    updates = []
    ctx = RenderContext(callback=updates.append)
    assert render_segments(project, project/'storyboard.json', 'en', None, 0, 4,
                           output, workers, context=ctx) == []
    assert _probe(output)['frames'] == 4
    assert updates[-1].frames == updates[-1].total == 4
    assert not ctx.token.owned_pids
    assert not list(tmp_path.glob('.segments-*'))


def test_real_segment_output_name_collision(tmp_path):
    project = tmp_path/'project'
    pipeline.new_project('A lesson.\n\nCount three circles.', project, lang='en')
    output = tmp_path/'01.mp4'
    encode(SlowFrames(), 0, 8, output, 20)
    previous = output.read_bytes()
    updates = []
    ctx = RenderContext(callback=updates.append)
    render_segments(project, project/'storyboard.json', 'en', None, 0, 4,
                    output, 2, context=ctx)
    probe = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-count_frames',
                            '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames',
                            '-of', 'json', str(output)], capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr
    frames = int(json.loads(probe.stdout)['streams'][0]['nb_read_frames'])
    print(json.dumps({'flow': '01.mp4', 'decoded_frames': frames, 'ffprobe_exit': probe.returncode,
                      'reported_frames': updates[-1].frames,
                      'previous_preserved': output.read_bytes() == previous}))
    assert frames == 4 and not probe.stderr
    assert updates[-1].frames == updates[-1].total == 4
    assert not ctx.token.owned_pids
    assert not list(tmp_path.glob('.segments-*'))


@pytest.mark.parametrize('leader_exited', [False, True])
@pytest.mark.parametrize('child_kind', ['ffmpeg', 'stubborn'])
def test_cancel_reaps_group_after_leader_exit(tmp_path, leader_exited, child_kind):
    from kinodraw.engine.render import FFMPEG
    from kinodraw.progress import encoded_frames
    progress = tmp_path/'child.progress'
    child_cmd = ([FFMPEG, '-v', 'error', '-re', '-f', 'lavfi', '-i',
                  'color=size=16x16:rate=30', '-progress', str(progress),
                  '-stats_period', '0.05', '-f', 'null', '-']
                 if child_kind == 'ffmpeg' else
                 [sys.executable, '-c', 'import time; time.sleep(60)'])
    ready = tmp_path/'ready.json'
    script = """
import json, signal, subprocess, sys, time
from pathlib import Path
def ignore_term():
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen(json.loads(sys.argv[1]), preexec_fn=ignore_term,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(sys.argv[2]).write_text(json.dumps({'child': child.pid}))
time.sleep(60)
"""
    token = CancellationToken()
    leader = token.register(subprocess.Popen(
        [sys.executable, '-c', script, json.dumps(child_cmd), str(ready)],
        start_new_session=True), group=True)
    unrelated = subprocess.Popen(['sleep', '30'])
    try:
        deadline = time.monotonic()+5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        child = json.loads(ready.read_text())['child']
        os.kill(child, 0)
        if child_kind == 'ffmpeg':
            deadline = time.monotonic()+5
            while not encoded_frames(progress) and time.monotonic() < deadline:
                time.sleep(.02)
            assert encoded_frames(progress) > 0
        if leader_exited:
            leader.terminate()
            leader.wait(timeout=2)
            os.kill(child, 0)
        token.cancel()
        deadline = time.monotonic()+3
        group_present = True
        while time.monotonic() < deadline:
            try:
                os.killpg(leader.pid, 0)
            except ProcessLookupError:
                group_present = False
                break
            time.sleep(.02)
        print(json.dumps({'flow': 'leader_exit_cancel', 'child_kind': child_kind,
                          'registered_group': leader.pid, 'child_pid': child,
                          'unrelated_pid': unrelated.pid,
                          'leader_exited_before_cancel': leader_exited,
                          'child_frames': encoded_frames(progress),
                          'leader_exit': leader.returncode, 'group_present': group_present,
                          'owned_pids': token.owned_pids, 'unrelated_alive': unrelated.poll() is None}))
        assert not group_present
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
        assert not token.owned_pids and unrelated.poll() is None
    finally:
        # Only the group explicitly created/registered by this test is cleaned.
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        leader.wait(timeout=2)
        unrelated.terminate()
        unrelated.wait(timeout=2)

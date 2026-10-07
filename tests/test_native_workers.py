"""Real saved-plan workers must receive the same target as an in-process render."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

from kinodraw.engine import render
from kinodraw.engine.hybrid import HybridProduction
from kinodraw.progress import RenderContext
from test_hybrid import fixture


@pytest.mark.parametrize('size,aspect,start', [
    ((3840, 2160), '16:9', 18.517379806505694),
    ((1080, 1080), '1:1', 7.703809523809524),
])
def test_continuous_parent_equals_fresh_segment_raw_bytes(tmp_path, size, aspect, start):
    import os
    project = Path(__file__).parent / 'fixtures/native_saved_project'
    board = json.loads((project / 'storyboard.json').read_text())
    timing = json.loads((project / 'timeline.json').read_text())
    prod = render.make_production(board, timing, 'en', project, size=size, aspect=aspect)
    times = [start + i / render.FPS for i in range(16)]
    if aspect == '16:9':
        assert times[8] == 18.78404647317236
    parent_hashes = []
    for i, at in enumerate(times):
        raw = prod.frame(at).tobytes()
        parent_hashes.append(hashlib.sha256(raw).hexdigest())
        if i >= 8:
            (tmp_path / f'parent-{i}.rgb').write_bytes(raw)
    code = """import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'tests')
import conftest,keyring.core
keyring.core._keyring_backend=conftest._Keychain()
from kinodraw.engine.render import make_production
d=json.loads(sys.stdin.read());p=Path(d['project']);out=Path(d['output'])
b=json.loads((p/'storyboard.json').read_text());tl=json.loads((p/'timeline.json').read_text())
r=make_production(b,tl,'en',p,size=tuple(d['size']),aspect=d['aspect'])
hashes=[]
for i,t in enumerate(d['times'],8):
 raw=r.frame(t).tobytes();(out/f'fresh-{i}.rgb').write_bytes(raw)
 hashes.append(hashlib.sha256(raw).hexdigest())
print(json.dumps(hashes))
"""
    payload = dict(project=str(project), output=str(tmp_path), size=size,
                   aspect=aspect, times=times[8:])
    context = RenderContext()
    worker = context.token.register(subprocess.Popen(
        [sys.executable, '-B', '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, start_new_session=True), group=True)
    try:
        stdout, stderr = worker.communicate(json.dumps(payload), timeout=120)
        assert worker.returncode == 0, stderr
    finally:
        context.token.stop(worker)
        context.token.unregister(worker)
    assert not context.token.owned_pids
    assert not context.token._group_exists(worker.pid)
    fresh_hashes = json.loads(stdout)
    mismatches = [i for i in range(8, 16) if (tmp_path / f'parent-{i}.rgb').read_bytes()
                  != (tmp_path / f'fresh-{i}.rgb').read_bytes()]
    report = dict(size=size, aspect=aspect, parent_times=times, child_times=times[8:],
                  child_exit=worker.returncode, parent_hashes=parent_hashes,
                  fresh_hashes=fresh_hashes, mismatch_indices=mismatches,
                  comparison='complete raw frame bytes', frame_bytes=len(raw),
                  child_pid=worker.pid, child_group_absent=True)
    phase = os.environ.get('NATIVE_REVIEW_PHASE', 'after')
    (tmp_path / f'segment-equivalence-{phase}-{size[0]}.json').write_text(
        json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    assert not mismatches, 'native fresh segment depends on earlier mask history'


def saved_project(tmp_path):
    board, plan, timing = fixture(tmp_path)
    prop = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300"><circle cx="150" cy="150" r="120" fill="#f08030"/></svg>'
    (tmp_path / 'doodles').mkdir()
    (tmp_path / 'doodles/gen-worker.svg').write_text(prop)
    plan['scenes'][1]['elements'].append({'kind': 'picture', 'ref': 'gen-worker'})
    plan['scenes'][1]['camera'] = 'slow_push'
    plan['scenes'][2]['treatment'] = 'chart'
    board['beats'][2]['visuals'].append({'id': 'worker-values', 'type': 'bars',
        'rows': [{'value': 42.5, 'label': 'A'}, {'value': -7, 'label': 'B'}]})
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    episode = tmp_path / 'storyboard.json'
    timeline = tmp_path / 'timeline.json'
    episode.write_text(json.dumps(board))
    timeline.write_text(json.dumps(timing))
    return board, plan, timing, episode, timeline


@pytest.mark.parametrize('size,aspect', [((3840, 2160), '16:9'), ((1080, 1080), '1:1')])
@pytest.mark.parametrize('workers', [1, 2])
def test_segments_forward_target(tmp_path, monkeypatch, size, aspect, workers):
    board, plan, timing, episode, timeline = saved_project(tmp_path)
    start = 18.517379806505694 if aspect == '16:9' else 7.703809523809524
    frames = 16
    label = f'{size[0]}x{size[1]}-workers{workers}'
    output = tmp_path / f'{label}.mp4'
    processes = []
    groups = []
    original_popen = subprocess.Popen
    def observe(command, *args, **kwargs):
        process = original_popen(command, *args, **kwargs)
        processes.append((command, process))
        if kwargs.get('start_new_session'):
            groups.append(process.pid)
        return process
    monkeypatch.setattr(subprocess, 'Popen', observe)
    ctx = RenderContext()
    # Keep all historical arguments positional, including context.
    render.render_segments(tmp_path, episode, 'en', timeline, start, frames, output, workers,
                           20, aspect, None, ctx, size=size)
    assert not ctx.token.owned_pids
    commands = [cmd for cmd, _ in processes if 'kinodraw.engine.render' in cmd]
    assert len(commands) == workers
    for cmd in commands:
        assert cmd[cmd.index('--size')+1:cmd.index('--size')+3] == list(map(str, size))
        assert cmd[cmd.index('--aspect')+1] == aspect
    assert all(p.returncode == 0 for _, p in processes)
    probe = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-count_frames',
        '-show_streams', '-of', 'json', str(output)], capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stderr
    stream = json.loads(probe.stdout)['streams'][0]
    assert (stream['width'], stream['height']) == size
    assert int(stream['nb_read_frames']) == frames
    decoded = subprocess.run([render.FFMPEG, '-v', 'error', '-i', str(output), '-map', '0:v:0',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, timeout=60)
    assert decoded.returncode == 0, decoded.stderr
    assert len(decoded.stdout) == frames * size[0] * size[1] * 3
    Image.frombytes('RGB', size, decoded.stdout[:size[0]*size[1]*3]).save(tmp_path / f'{label}-decoded.png')
    assert all(not ctx.token._group_exists(group) for group in groups)
    report = dict(size=size, aspect=aspect, workers=workers, frames=frames, start=start,
        processes=[dict(command=cmd, pid=p.pid, exit_code=p.returncode) for cmd, p in processes],
        owned_groups=groups, remaining_groups=[],
        probe_exit=probe.returncode, decode_exit=decoded.returncode,
        decoded_bytes=len(decoded.stdout), sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (tmp_path / f'{label}.json').write_text(json.dumps(report, indent=2)+'\n')


@pytest.mark.parametrize('size,aspect', [((3840, 2160), '16:9'), ((1080, 1080), '1:1')])
def test_fresh_cli_raw_frames_equal_single_process(tmp_path, size, aspect):
    board, plan, timing, episode, timeline = saved_project(tmp_path)
    prod = render.make_production(board, timing, 'en', tmp_path, size=size, aspect=aspect)
    assert isinstance(prod, HybridProduction) and prod.plan == plan
    assert any(e.values == (42.5, -7) for e in prod.spans[2].motion.elements)
    assert prod.spans[1].story is not None and prod.spans[1].motion is None   # a story's scene is a storybook page
    times = [1., prod.spans[1].start+1.1, prod.spans[2].start+1.1, timing['end_card']['end']-.1]
    command = [sys.executable, '-m', 'kinodraw.engine.render', '--project', str(tmp_path),
        '--episode', str(episode), '--timeline', str(timeline), '--lang', 'en', '--aspect', aspect,
        '--size', *map(str, size), '--stills', ','.join(map(repr, times)), '--preview-dir', str(tmp_path/'stills')]
    worker = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert worker.returncode == 0, worker.stderr
    hashes = []
    for t in times:
        raw = prod.frame(t).convert('RGB')
        with Image.open(tmp_path/'stills'/f'en-{t:07.2f}.png') as fresh:
            assert fresh.size == size and fresh.tobytes() == raw.tobytes()
            hashes.append(dict(time=t, parent=hashlib.sha256(raw.tobytes()).hexdigest(),
                               worker=hashlib.sha256(fresh.tobytes()).hexdigest()))
    (tmp_path / f'cli-raw-{size[0]}x{size[1]}.json').write_text(json.dumps(dict(
        command=command, exit_code=worker.returncode, size=size, aspect=aspect, frames=hashes), indent=2)+'\n')


@pytest.mark.parametrize('portrait', ['native', 'letterbox'])
def test_explicit_portrait_keeps_existing_semantics(tmp_path, portrait):
    board, plan, timing = fixture(tmp_path)
    (tmp_path / 'project.json').write_text('{}')
    default = render.make_production(board, timing, 'en', tmp_path, aspect='9:16', portrait=portrait)
    explicit = render.make_production(board, timing, 'en', tmp_path, aspect='9:16',
                                      portrait=portrait, size=(1080, 1920))
    assert default.native == explicit.native == (portrait == 'native')
    assert default.size == explicit.size == (1080, 1920)
    for t in (1., timing['end_card']['end']-.1):
        assert default.frame(t).tobytes() == explicit.frame(t).tobytes()


def test_native_collage_is_explicitly_unsupported(tmp_path):
    board, plan, timing = fixture(tmp_path)
    board['look'] = 'collage'
    with pytest.raises(ValueError, match='native collage'):
        render.make_production(board, timing, 'en', tmp_path, size=(3840, 2160))


def test_cli_two_workers_and_existing_audio_mix(tmp_path):
    from kinodraw.audio.mix import mix, read_wav, write_wav, SR
    from kinodraw.package import mux
    board, plan, timing, episode, timeline = saved_project(tmp_path)
    silent = tmp_path / 'cli-square.mp4'
    command = [sys.executable, '-m', 'kinodraw.engine.render', '--project', str(tmp_path),
        '--episode', str(episode), '--timeline', str(timeline), '--lang', 'en', '--aspect', '1:1',
        '--size', '1080', '1080', '--workers', '2', '--frames', '4', '--start',
        str(timing['beats'][plan['scenes'][1]['beat_ids'][0]]['start']+1.1), '--output', str(silent)]
    worker = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert worker.returncode == 0, worker.stderr
    duration = 4 / render.FPS
    # Local synthetic narration passes through the existing mix and AAC mux.
    samples = .2 * np.sin(2*np.pi*440*np.arange(round(duration*SR))/SR)
    write_wav(tmp_path/'narration.wav', samples)
    clip_timing = dict(duration=duration, audio='narration.wav', chapters=[])
    audio = mix(dict(board, music=False, sfx=False, master=False), clip_timing, tmp_path)
    output = tmp_path / 'cli-square-audio.mp4'
    mux(clip_timing, silent, audio, output, 'en', 'Native worker acceptance', tmp_path)
    probe = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-count_frames',
        '-show_streams', '-of', 'json', str(output)], capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stderr
    streams = json.loads(probe.stdout)['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    assert (video['width'], video['height'], int(video['nb_read_frames'])) == (1080, 1080, 4)
    assert any(s['codec_type'] == 'audio' and s['codec_name'] == 'aac' for s in streams)
    full = subprocess.run([render.FFMPEG, '-v', 'error', '-i', str(output), '-f', 'null', '-'],
                          capture_output=True, timeout=60)
    assert full.returncode == 0 and not full.stderr
    decoded = subprocess.run([render.FFMPEG, '-v', 'error', '-i', str(output), '-vn',
        '-ar', str(SR), '-ac', '1', '-f', 'f32le', '-'], capture_output=True, timeout=30)
    assert decoded.returncode == 0, decoded.stderr
    reference = read_wav(audio)[0].mean(1)
    actual = np.frombuffer(decoded.stdout, '<f4')[:len(reference)]
    assert len(actual) == len(reference) and np.max(np.abs(actual)) > .1
    correlation = float(np.corrcoef(reference, actual)[0, 1])
    assert correlation > .95
    manifest = json.loads(Path(str(silent)+'.json').read_text())
    assert manifest['size'] == [1080, 1080] and manifest['aspect'] == '1:1'
    (tmp_path/'cli-audio.json').write_text(json.dumps(dict(command=command,
        cli_exit=worker.returncode, probe_exit=probe.returncode, full_decode_exit=full.returncode,
        audio_decode_exit=decoded.returncode, waveform_correlation=correlation,
        audio_samples=len(actual), frames=4, size=[1080, 1080]), indent=2)+'\n')

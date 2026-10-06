"""Measured 1080p30 demo, with real ffmpeg encoding and unrelaxed acceptance."""
import argparse
import cProfile
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pstats
import resource
import subprocess
import sys
import time

import imageio_ffmpeg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinodraw.engine.bold import BoldProduction
from kinodraw.engine.bold.demo import demo_scenes


def progress_module():
    try:
        from kinodraw import progress
        return progress
    except ImportError:
        # This isolated performance worktree predates the export integration.
        # Execute its existing validator read-only, rather than duplicating it.
        source = Path(__file__).resolve().parents[3] / 'kd-next-1005/kinodraw/progress.py'
        spec = importlib.util.spec_from_file_location('bold_benchmark_progress', source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


def validate_video(ffmpeg, source, expected):
    progress = progress_module()
    context = progress.RenderContext()
    processes = []
    register = context.token.register
    def record(process, group=False):
        processes.append(process)
        return register(process, group=group)
    context.token.register = record
    started = time.perf_counter()
    before_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    error = None
    try:
        # Inherit the benchmark runner's owned process group for timeouts.
        progress.validate_frames(ffmpeg, source, expected, context, group=False)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    elapsed = time.perf_counter() - started
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    validator = Path(progress.__file__).resolve()
    return dict(validation_wall_s=elapsed,
                validation_cpu_s=child.ru_utime + child.ru_stime - before_child.ru_utime - before_child.ru_stime,
                validation_exit=processes[-1].returncode if processes else None,
                validation_error=error,
                validated_frames=progress.encoded_frames(str(source) + '.decode-progress'),
                validator_source=str(validator),
                validator_source_sha256=hashlib.sha256(validator.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--check-order', action='store_true')
    parser.add_argument('--frames', type=int, default=360, help='Short diagnostic only when less than 360')
    parser.add_argument('--start-frame', type=int, default=0)
    args = parser.parse_args()
    if args.frames <= 0 or args.start_frame < 0 or args.start_frame + args.frames > 360:
        parser.error('Frame range must be within the unchanged 360-frame demo')
    out = args.output
    # Every run retains its evidence; never replace a previous measurement.
    out.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / 'kinodraw/engine/bold/render.py'
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    production = BoldProduction(demo_scenes(), size=(1920, 1080))
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-s', '1920x1080', '-r', '30', '-i', '-', '-an', '-c:v', 'libx264',
               '-preset', 'fast', '-crf', '18', '-threads', '1', '-pix_fmt', 'yuv420p',
               '-movflags', '+faststart', str(out / 'demo.mp4')]
    hashes, loads = [], [os.getloadavg()]
    render_wall = render_cpu = pipe_wall = hash_wall = 0.
    started_utc = subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'], text=True).strip()
    before_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    started, started_cpu = time.perf_counter(), time.process_time()
    profile = cProfile.Profile() if args.profile else None
    with (out / 'ffmpeg.log').open('wb') as log:
        encode_started = time.perf_counter()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i in range(args.start_frame, args.start_frame + args.frames):
                wall, cpu = time.perf_counter(), time.process_time()
                if profile:
                    profile.enable()
                frame = production.frame_array(i / 30)
                if profile:
                    profile.disable()
                render_cpu += time.process_time() - cpu
                render_wall += time.perf_counter() - wall
                stamp = time.perf_counter()
                data = frame.tobytes()
                hashes.append(hashlib.sha256(data).hexdigest())
                hash_wall += time.perf_counter() - stamp
                stamp = time.perf_counter()
                process.stdin.write(data)
                pipe_wall += time.perf_counter() - stamp
                if i % 30 == 0:
                    loads.append(os.getloadavg())
        finally:
            stamp = time.perf_counter()
            process.stdin.close()
            code = process.wait()
            drain_wall = time.perf_counter() - stamp
            encode_wall = time.perf_counter() - encode_started
    render_encode_elapsed = time.perf_counter() - started
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    validation = validate_video(command[0], out / 'demo.mp4', args.frames)
    elapsed, cpu = time.perf_counter() - started, time.process_time() - started_cpu
    ended_utc = subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'], text=True).strip()
    output_s = args.frames / 30
    target = args.frames == 360 and args.start_frame == 0
    result = dict(case='demo_scenes', width=1920, height=1080, fps=30, frames=args.frames,
                  start_frame=args.start_frame, output_s=output_s, target_configuration=target,
                  started_utc=started_utc, ended_utc=ended_utc,
                  renderer_source_sha256=source_sha256,
                  benchmark_command=[sys.executable, *sys.argv], working_directory=str(Path.cwd()),
                  wall_s=elapsed, render_encode_wall_s=render_encode_elapsed,
                  cpu_s=cpu, render_wall_s=render_wall, render_cpu_s=render_cpu,
                  encode_pipe_wall_s=pipe_wall, encode_drain_wall_s=drain_wall,
                  encode_process_wall_s=encode_wall, encode_wait_wall_s=pipe_wall + drain_wall,
                  timing_note='Encoder process wall overlaps rendering and includes waiting for input; CPU and pipe/drain wait are separate.',
                  encode_cpu_s=child.ru_utime + child.ru_stime - before_child.ru_utime - before_child.ru_stime,
                  hash_wall_s=hash_wall, seconds_per_output_second=elapsed / output_s,
                  render_seconds_per_output_second=render_wall / output_s, ffmpeg_exit=code,
                  logical_cpus=os.cpu_count(), load_samples=loads + [os.getloadavg()],
                  ffmpeg_command=command, max_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    result.update(validation)
    result['acceptance_timing_note'] = 'wall_s includes render, encode, hashes and full decode validation; seek verification is timed separately.'
    (out / 'render-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    if profile:
        profile.dump_stats(str(out / 'render.prof'))
        with (out / 'profile.txt').open('w') as stream:
            pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumtime').print_stats(45)
    if args.check_order:
        order_started = time.perf_counter()
        from kinodraw.engine.bold.render import _LAYERS
        indices = range(args.start_frame, args.start_frame + args.frames)
        reference = []
        for i in indices:
            _LAYERS.clear()
            fresh = BoldProduction(demo_scenes(), size=(1920, 1080))
            reference.append(hashlib.sha256(fresh.frame_array(i / 30).tobytes()).hexdigest())
        (out / 'fresh-hashes.json').write_text(json.dumps(reference, indent=2) + '\n')
        result['sequential_mismatch_frames'] = [i for i, actual, expected in zip(indices, hashes, reference)
                                                if actual != expected]
        result['fresh_reference_frames'] = len(reference)
        result['order_load_samples'] = [os.getloadavg()]
        (out / 'order-progress.json').write_text(json.dumps(result, indent=2) + '\n')
        orders = (('reversed', reversed(indices)),
                  ('order', np.random.default_rng(20261005).permutation(args.frames) + args.start_frame))
        for name, order in orders:
            _LAYERS.clear()
            seek = BoldProduction(demo_scenes(), size=(1920, 1080))
            mismatch = [int(i) for i in order
                        if hashlib.sha256(seek.frame_array(i / 30).tobytes()).hexdigest()
                        != reference[i - args.start_frame]]
            result[name + '_mismatch_frames'] = mismatch
            result['order_load_samples'].append(os.getloadavg())
            (out / 'order-progress.json').write_text(json.dumps(result, indent=2) + '\n')
        result['order_seed'] = 20261005
        result['reference_note'] = 'Each reference frame uses a fresh Production and an empty scene-layer cache.'
        result['order_check_wall_s'] = time.perf_counter() - order_started
        result['order_check_ended_utc'] = subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'], text=True).strip()
    result['renderer_source_unchanged'] = source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    valid = (code == 0 and validation['validation_exit'] == 0
             and validation['validation_error'] is None and validation['validated_frames'] == args.frames
             and result['renderer_source_unchanged']
             and not any(result.get(name + '_mismatch_frames') for name in ('sequential', 'reversed', 'order')))
    result['passed'] = valid and elapsed / output_s <= 3 if target else None
    (out / 'measurement.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if (result['passed'] if target else valid) else 1


if __name__ == '__main__':
    sys.exit(main())

"""Render the 12 s bold demo at 1080p30, plus a labelled 4 x 3 contact sheet.

  python scripts/bold_preview.py
"""
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinodraw.engine.bold import BoldProduction  # noqa: E402
from kinodraw.engine.bold.demo import demo_scenes  # noqa: E402
from motion_contact_sheet import GUTTER, H, W, label  # noqa: E402

OUT = Path('/tmp/kd1005/a3b-perf')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    production = BoldProduction(demo_scenes())
    movie = OUT / 'demo.mp4'
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-s', '1920x1080', '-r', '30', '-i', '-', '-an', '-c:v', 'libx264',
               '-preset', 'fast', '-crf', '18', '-threads', '1', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(movie)]
    cell_h = H + 42
    sheet = Image.new('RGB', (4 * W + 5 * GUTTER, 3 * cell_h + 4 * GUTTER), (27, 27, 27))
    started = time.perf_counter()
    loads = [os.getloadavg()]
    render_wall = render_cpu = 0.
    stderr = OUT / 'ffmpeg.log'
    with stderr.open('wb') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i in range(round(production.duration * 30)):
                t = i / 30
                wall, cpu = time.perf_counter(), time.process_time()
                frame = production.frame_array(t)
                render_cpu += time.process_time() - cpu
                render_wall += time.perf_counter() - wall
                process.stdin.write(frame.tobytes())
                if i % 30 == 0:
                    loads.append(os.getloadavg())
                if i % 30 == 15:
                    k = i // 30
                    cell = Image.new('RGBA', (W, cell_h), (27, 27, 27))
                    label(cell, f'{t:.2f} s / bold')
                    cell.paste(Image.fromarray(frame).resize((W, H), Image.LANCZOS), (0, 42))
                    sheet.paste(cell.convert('RGB'), (GUTTER + k % 4 * (W + GUTTER), GUTTER + k // 4 * (cell_h + GUTTER)))
                    Image.fromarray(frame).save(OUT / f'frame-{t:04.1f}.png')
        finally:
            process.stdin.close()
            code = process.wait()
    if code:
        raise RuntimeError(f'ffmpeg exited {code}: {stderr.read_text(encoding="utf-8")}')
    elapsed = time.perf_counter() - started
    loads.append(os.getloadavg())
    contact = OUT / 'contact-sheet.png'
    sheet.save(contact)
    measurement = {'output_s': production.duration, 'wall_s': elapsed, 'seconds_per_output_second': elapsed / production.duration,
                   'render_wall_s': render_wall, 'render_cpu_s': render_cpu,
                   'render_cpu_seconds_per_output_second': render_cpu / production.duration,
                   'load_samples': loads, 'max_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (OUT / 'measurement.json').write_text(json.dumps(measurement, indent=2), encoding='utf-8')
    print(f'wrote {movie} (1920x1080, 30 fps, {production.duration:.1f} s)')
    print(f'render speed: {elapsed / production.duration:.3f} seconds per output second ({elapsed:.2f} s wall)')
    print(f'render CPU: {render_cpu / production.duration:.3f} seconds per output second (single render process)')
    print(f'load average (1, 5, 15 min): {loads[0]} -> {loads[-1]}')
    print(f'contact sheet: {contact}')


if __name__ == '__main__':
    main()

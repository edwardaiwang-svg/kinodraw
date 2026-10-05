"""Render four 6 s, 1280x720, 30 fps atmosphere clips and labelled contact sheets.

  python scripts/atmos_preview.py

Outputs and decoded QA evidence go to /tmp/kd1005/a4-atmos/. No model or network is used.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinodraw.engine.atmos import Atmosphere, compose  # noqa: E402
from kinodraw.engine.atmos.layers import KINDS  # noqa: E402
from motion_contact_sheet import GUTTER, label  # noqa: E402

OUT = Path('/tmp/kd1005/a4-atmos')
SIZE, INTERNAL, FPS, SECONDS = (1280, 720), (480, 270), 30, 6
SAMPLES = (0, 15, 30, 45, 60, 75, 82, 90, 105, 120, 150, 179)


def benchmark():
    results = {}
    for kind in KINDS:
        scene = Atmosphere(kind, density=1.6, seed='timing')
        for _ in range(3):
            scene.rgba(2.6, *INTERNAL)
        start = time.perf_counter()
        for i in range(60):
            scene.rgba(2.4 + i / 100, *INTERNAL)
        results[kind] = round((time.perf_counter() - start) * 1000 / 60, 3)
    return results


def contact_sheet(video, path):
    """Decode the actual encoded clip; reuse the motion sheet's label and gutter style."""
    reader = imageio_ffmpeg.read_frames(str(video), pix_fmt='rgb24')
    metadata = next(reader)
    width, height = metadata['size']
    sheet = Image.new('RGB', (4 * 320 + 5 * GUTTER, 3 * 180 + 4 * GUTTER), (27, 27, 27))
    means, differences, previous, count = [], [], None, 0
    for i, raw in enumerate(reader):
        frame = Image.frombytes('RGB', (width, height), raw)
        small = frame.resize((320, 180), Image.Resampling.BILINEAR)
        arr = np.asarray(small, np.float32)
        means.append(float(arr.mean()))
        if previous is not None:
            differences.append(float(np.abs(arr - previous).mean()))
        previous = arr
        count += 1
        if i in SAMPLES:
            k = SAMPLES.index(i)
            cell = label(small.convert('RGBA'), f'{i / FPS:.2f}s')
            sheet.paste(cell.convert('RGB'), (GUTTER + k % 4 * (320 + GUTTER), GUTTER + k // 4 * (180 + GUTTER)))
    sheet.save(path)
    if metadata['size'] != SIZE or metadata['fps'] != FPS or count != FPS * SECONDS:
        raise RuntimeError(f'unexpected encoded clip: {metadata}, decoded frames={count}')
    return {'size': metadata['size'], 'fps': metadata['fps'], 'frames': count,
            'mean_brightness': round(float(np.mean(means)), 3),
            'mean_frame_difference': round(float(np.mean(differences)), 3)}


def render_preview(name, scene, background):
    video, sheet = OUT / f'{name}.mp4', OUT / f'{name}_sheet.png'
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen([ffmpeg, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                             '-s', f'{SIZE[0]}x{SIZE[1]}', '-r', str(FPS), '-i', '-', '-an', '-c:v', 'libx264',
                             '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-threads', '2',
                             '-movflags', '+faststart', str(video)], stdin=subprocess.PIPE)
    try:
        for i in range(SECONDS * FPS):
            rgb = compose(background, scene, i / FPS)
            frame = Image.fromarray(np.rint(rgb * 255).astype(np.uint8)).resize(SIZE, Image.Resampling.BILINEAR)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code:
        raise RuntimeError(f'ffmpeg exited {code}: {video}')
    facts = contact_sheet(video, sheet)
    print(f'{video}\n{sheet}', flush=True)
    return {'clip': str(video), 'sheet': str(sheet), **facts}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    timing = benchmark()
    print(json.dumps({'ms_per_layer_480x270': timing}), flush=True)
    if any(ms > 20 for ms in timing.values()):
        raise RuntimeError('atmosphere timing budget exceeded')
    black = np.zeros((INTERNAL[1], INTERNAL[0], 3), np.float32)
    scenes = [
        ('thick_fog_shooting_star', Atmosphere(['night_sky', 'starfield',
          {'kind': 'shooting_star', 'window': (2, 3.5)}, {'kind': 'fog', 'density': 1.6}], seed='lion'), black),
        ('dawn_dust', Atmosphere(['dawn', {'kind': 'light_rays', 'density': .45}, 'dust'],
          palette={'dawn_top': '#48567c', 'dawn_horizon': '#e8ae80', 'dust': '#fff0bb'}, seed='dawn'), black),
        ('rain', Atmosphere('rain', density=1.6, seed='rain'), black + np.array([.035, .07, .10], np.float32)),
        ('embers', Atmosphere('embers', density=1.3, seed='embers'), black + np.array([.025, .018, .03], np.float32)),
    ]
    previews = [render_preview(*scene) for scene in scenes]
    report = {'internal_size': INTERNAL, 'ms_per_layer_480x270': timing, 'previews': previews}
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{OUT / "report.json"}', flush=True)


if __name__ == '__main__':
    main()

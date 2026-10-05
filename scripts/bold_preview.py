"""Render the 12 s bold demo at 1080p30, plus a labelled 4 x 3 contact sheet.

  python scripts/bold_preview.py
"""
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

OUT = Path('/tmp/kd1005/a3-motion')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    production = BoldProduction(demo_scenes())
    movie = OUT / 'demo.mp4'
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-s', '1920x1080', '-r', '30', '-i', '-', '-an', '-c:v', 'libx264',
               '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(movie)]
    sheet = Image.new('RGB', (4 * W + 5 * GUTTER, 3 * H + 4 * GUTTER), (27, 27, 27))
    started = time.perf_counter()
    stderr = OUT / 'ffmpeg.log'
    with stderr.open('wb') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i in range(round(production.duration * 30)):
                t = i / 30
                frame = production.frame_array(t)
                process.stdin.write(frame.tobytes())
                if i % 30 == 15:
                    k = i // 30
                    cell = Image.fromarray(frame).resize((W, H), Image.LANCZOS).convert('RGBA')
                    label(cell, f'{t:.2f} s / bold')
                    sheet.paste(cell.convert('RGB'), (GUTTER + k % 4 * (W + GUTTER), GUTTER + k // 4 * (H + GUTTER)))
        finally:
            process.stdin.close()
            code = process.wait()
    if code:
        raise RuntimeError(f'ffmpeg exited {code}: {stderr.read_text(encoding="utf-8")}')
    elapsed = time.perf_counter() - started
    contact = OUT / 'contact-sheet.png'
    sheet.save(contact)
    print(f'wrote {movie} (1920x1080, 30 fps, {production.duration:.1f} s)')
    print(f'render speed: {elapsed / production.duration:.3f} seconds per output second ({elapsed:.2f} s wall)')
    print(f'contact sheet: {contact}')


if __name__ == '__main__':
    main()

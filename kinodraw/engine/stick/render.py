"""Frames for the stick look: white canvas, the shot's items in layer order, burned-in captions.

Every line boils between three drawings at 7.5 Hz and motion steps at 15 fps (twos at 30 fps). What does not
move in a shot is composited once per drawing and reused, so a frame costs one copy plus whatever is moving.
"""
from __future__ import annotations

import bisect
import subprocess
import sys
import time
from collections import OrderedDict

import imageio_ffmpeg
from PIL import Image

from .. import ink
from . import text
from .compose import H, W, Composer
from .rig import DRAW_FPS

FPS = 30
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


class StickProduction:
    def __init__(self, board, tl, lang, project_dir=None, seed=0, captions=True, envelope=None):
        self.board, self.tl, self.lang = board, tl, lang
        self.composer = Composer(board, tl, lang, project_dir, seed=seed, envelope=envelope)
        self.shots = self.composer.shots()
        self.warnings = self.composer.warnings
        self.starts = [s.start for s in self.shots]
        self.captions = tl.get('captions', []) if captions else []
        self.cap_starts = [c['start'] for c in self.captions]
        self._cache = OrderedDict()

    def shot_at(self, t):
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        return i, self.shots[i]

    def frame(self, t: float) -> Image.Image:
        i, shot = self.shot_at(t)
        k = int(t * DRAW_FPS + 1e-6)
        variant = (k // 2) % 3
        order = sorted((n for n, it in enumerate(shot.items) if it.visible(t)), key=lambda n: shot.items[n].layer)
        moving = [n for n in order if shot.items[n].animated(t)]
        split = min((shot.items[n].layer for n in moving), default=99)
        below = tuple(n for n in order if n not in moving and shot.items[n].layer <= split)
        above = [n for n in order if n not in moving and shot.items[n].layer > split]
        key = (i, variant, below)
        base = self._cache.get(key)
        if base is None:
            base = Image.new('RGBA', (W, H), (255, 255, 255, 255))
            for n in below:
                shot.items[n].paint(base, t, k, variant)
            self._cache[key] = base
            while len(self._cache) > 24:
                self._cache.popitem(last=False)
        frame = base
        if moving or above:
            frame = base.copy()
            for n in moving + above:
                shot.items[n].paint(frame, t, k, variant)
        return self._caption(frame, t)

    def _caption(self, frame, t):
        i = bisect.bisect_right(self.cap_starts, t) - 1
        if i < 0:
            return frame
        c = self.captions[i]
        if not (c['start'] <= t < c['end']):
            return frame
        img = text.caption(c['text'], self.lang)
        out = frame.copy()
        ink.paste(out, img, (W - img.width) / 2, 1052 - img.height)
        return out


def encode(prod: StickProduction, start: float, n: int, output, crf: int = 20, log=print):
    proc = subprocess.Popen([FFMPEG, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
                             '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(crf),
                             '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart', str(output)],
                            stdin=subprocess.PIPE)
    t1 = time.time()
    for i in range(n):
        t = start + i / FPS
        proc.stdin.write(prod.frame(t).convert('RGB').tobytes())
        if i % 900 == 0 and log:
            log(f'frame {i}/{n} t={t:.1f}s {i / max(time.time() - t1, 1e-6):.1f} fps')
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit('ffmpeg failed')

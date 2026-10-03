"""Render a project in the stick-figure documentary look (preview; the Studio and `doodle make` still render the
whiteboard).

  python -m doodlestudio.engine.stick.preview PROJECT -o out.mp4
  python -m doodlestudio.engine.stick.preview PROJECT --stills 3,12.5,40      PNG frames into PROJECT/build/stick
  python -m doodlestudio.engine.stick.preview PROJECT -o clip.mp4 --start 30 --duration 20

PROJECT is a folder made by `doodle new` / `doodle make` (storyboard.json, project.json). The narration clips are
reused from PROJECT/voice (synthesized if missing) and laid out again without the whiteboard's drawing pauses,
since nothing here waits for a drawing hand; --keep-pacing reuses build/timeline.json as it is. Everything this
writes goes to PROJECT/build/stick/ and the -o file.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np

from ... import pipeline
from ...audio import mix as audio
from .render import FFMPEG, FPS, StickProduction, encode
from .rig import DRAW_FPS


def speech_envelope(wav: Path) -> np.ndarray:
    """Speech activity (0..1) per drawing frame (15 per second), for the talking mouth."""
    pcm, rate = audio.read_wav(wav)
    x = pcm[:, 0]
    n = rate // DRAW_FPS
    frames = len(x) // n
    rms = np.sqrt((x[:frames * n].reshape(frames, n) ** 2).mean(1) + 1e-12)
    return (20 * np.log10(rms + 1e-9) > -38).astype(np.float32)


def prepare(project: Path, keep_pacing=False, progress=None) -> tuple[dict, dict, str, Path]:
    """(storyboard, timeline, language, build dir) with narration laid out for this look."""
    cfg = pipeline.settings(project)
    lang = cfg['lang']
    out = project / 'build' / 'stick'
    out.mkdir(parents=True, exist_ok=True)
    if keep_pacing:
        tl = json.loads((project / 'build' / 'timeline.json').read_text(encoding='utf-8'))
    else:
        clips = pipeline.narrate(project, progress)
        tl = audio.assemble(pipeline.storyboard(project), lang, clips, out, pauses={}, credit=cfg.get('credit', True))
    return pipeline.storyboard(project), tl, lang, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project')
    ap.add_argument('-o', '--output')
    ap.add_argument('--stills', help='comma-separated times in seconds')
    ap.add_argument('--start', type=float, default=0.)
    ap.add_argument('--duration', type=float)
    ap.add_argument('--keep-pacing', action='store_true', help="keep the whiteboard's timeline (with its pauses)")
    ap.add_argument('--no-captions', action='store_true')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--crf', type=int, default=20)
    args = ap.parse_args(argv)
    if not (args.output or args.stills):
        ap.error('-o/--output or --stills required')
    project = Path(args.project)
    t0 = time.time()
    board, tl, lang, out = prepare(project, args.keep_pacing)
    wav = Path(tl.get('audio') or out / 'narration.wav')
    env = speech_envelope(wav) if wav.exists() else None
    prod = StickProduction(board, tl, lang, project, seed=args.seed, captions=not args.no_captions, envelope=env)
    print(f"{len(prod.shots)} shots, {tl['duration']:.1f}s ({time.time() - t0:.0f}s to prepare)", flush=True)
    for w in prod.warnings:
        print(f'  · {w}')
    if args.stills:
        stills = out / 'stills'
        stills.mkdir(parents=True, exist_ok=True)
        for s in args.stills.split(','):
            t = float(s)
            prod.frame(t).convert('RGB').save(stills / f'{lang}-{t:07.2f}.png')
        print(f'stills -> {stills}')
        if not args.output:
            return
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = args.duration or (tl['duration'] - args.start)
    n = int(round(duration * FPS))
    silent = out / 'silent.mp4'
    t1 = time.time()
    encode(prod, args.start, n, silent, args.crf)
    mixed = audio.mix(board, tl, out)
    subprocess.run([FFMPEG, '-y', '-v', 'error', '-i', str(silent), '-ss', f'{args.start:.3f}', '-t', f'{duration:.3f}',
                    '-i', str(mixed), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    '-shortest', '-movflags', '+faststart', str(output)], check=True)
    manifest = {'output': str(output), 'look': 'stick', 'language': lang, 'frames': n, 'fps': FPS,
                'start': args.start, 'duration': duration, 'shots': len(prod.shots), 'warnings': prod.warnings,
                'render_seconds': round(time.time() - t1, 1),
                'layouts': [s.layout for s in prod.shots]}
    Path(str(output) + '.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'wrote {output} ({n} frames) in {time.time() - t1:.0f}s')


if __name__ == '__main__':
    main()

"""Render the procedural cast, eight-frame action strips, and a ten-second life/action movie.

Run from the worktree root: python scripts/creature_preview.py
All evidence is written under /tmp/kd1005/a5-creatures/.
"""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinodraw.engine.creatures import Action, Palette, from_text_hint, raster  # noqa: E402
from kinodraw.engine.creatures.actions import target_response  # noqa: E402

OUT = Path('/tmp/kd1005/a5-creatures')
PAPER = '#FAF7EF'
FONT = ImageFont.load_default(size=19)
SMALL = ImageFont.load_default(size=15)


def cast():
    pendo = from_text_hint('Pendo', 'golden baby lion cub playful')
    mara = from_text_hint('Mara', 'adult female tigress orange with black stripes')
    kojo = from_text_hint('King Kojo', 'adult lion father massive black mane scar across the nose bold')
    lioness = from_text_hint('Lioness', 'adult female lioness golden')
    hyena = from_text_hint('Hyena A', 'adult spotted hyena fierce')
    other = replace(from_text_hint('Hyena B', 'young spotted hyena fluffy scar eye'), size=.93,
                    palette=Palette('#A59583', '#E9D9BC', '#958D45'))
    return pendo, mara, kojo, lioness, hyena, other


def label(image, text, xy=(14, 12), small=False):
    ImageDraw.Draw(image).text(xy, text, fill='#292321', font=SMALL if small else FONT)


def lineup(heroes, style):
    cw, ch = 390, 315
    sheet = Image.new('RGBA', (3 * cw, 2 * ch + 45), PAPER)
    label(sheet, 'Procedural cast / ' + style, (18, 12))
    for i, genome in enumerate(heroes):
        cell = Image.new('RGBA', (cw, ch), PAPER)
        ImageDraw.Draw(cell).line((15, 279, cw - 15, 279), fill='#D8D0C3', width=1)
        cell.alpha_composite(raster(genome, t=1., style=style, height=260), (0, 58))
        label(cell, genome.name)
        label(cell, f'{genome.age} {genome.species} / size {genome.size:g}', (14, 36), small=True)
        sheet.alpha_composite(cell, ((i % 3) * cw, 45 + (i // 3) * ch))
    path = OUT / f'lineup_{style}.png'
    sheet.convert('RGB').save(path)
    print(path, flush=True)
    return sheet


def pair_frame(source, target, action, t, laugh=False, size=(480, 310)):
    cell = Image.new('RGBA', size, PAPER)
    if laugh:
        cell.alpha_composite(raster(source, action, t, height=230), (-27, 67))
        cell.alpha_composite(ImageOps.mirror(raster(target, action, t + .07, height=230)), (143, 67))
    else:
        cell.alpha_composite(raster(source, action, t, height=255), (-30, 66))
        response = target_response(action, t)
        response = replace(response, dx=-response.dx, head_pitch=-response.head_pitch)
        cell.alpha_composite(ImageOps.mirror(raster(target, response, t, height=255)), (80, 66))
    return cell


def action_strips(heroes):
    pendo, _, kojo, _, hyena, other = heroes
    cases = [('kojo_roar', kojo, 'roar'), ('pendo_whimper', pendo, 'whimper'),
             ('kojo_nudge_pendo', kojo, 'nudge'), ('kojo_breathe_heavy', kojo, 'breathe_heavy'),
             ('kojo_swipe', kojo, 'swipe'), ('hyenas_laugh', hyena, 'laugh'), ('pendo_walk', pendo, 'walk')]
    times = (0., .14, .28, .42, .56, .70, .84, 1.)
    cw, ch = 480, 310
    for key, genome, name in cases:
        action = Action(name)
        sheet = Image.new('RGBA', (cw * 4, ch * 2 + 45), PAPER)
        label(sheet, key.replace('_', ' '), (18, 12))
        for i, u in enumerate(times):
            t = u * action.seconds
            if name in ('nudge', 'laugh'):
                cell = pair_frame(genome, pendo if name == 'nudge' else other, action, t, name == 'laugh')
            else:
                cell = Image.new('RGBA', (cw, ch), PAPER)
                cell.alpha_composite(raster(genome, action, t, height=270), (37, 55))
            label(cell, f'{i + 1}/8  t={t:.2f}s', small=True)
            cell.convert('RGB').save(OUT / 'frames' / f'{key}_{i:02d}.png')
            sheet.alpha_composite(cell, ((i % 4) * cw, 45 + (i // 4) * ch))
        path = OUT / f'{key}.png'
        sheet.convert('RGB').save(path)
        print(path, flush=True)


def movie(heroes):
    pendo, mara, kojo = heroes[:3]
    actors = [(pendo, 25, [Action('whimper', 2.), Action('walk', 6.4)]),
              (mara, 440, [Action('look', 3.), Action('pounce', 6.)]),
              (kojo, 865, [Action('roar', 2.2), Action('breathe_heavy', 5.), Action('swipe', 8.5)])]
    width, height, fps = 1280, 520, 30
    path = OUT / 'heroes_10s.mp4'
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264',
               '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)]
    with (OUT / 'encode.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for frame in range(10 * fps):
                t = frame / fps
                image = Image.new('RGBA', (width, height), PAPER)
                label(image, 'Life layer: breathe / blink / ears / tail / weight shift' if t < 2 else 'Continuous action envelopes over the life layer', (28, 22))
                ImageDraw.Draw(image).line((25, 429, width - 25, 429), fill='#D8D0C3', width=2)
                for genome, x, cues in actors:
                    image.alpha_composite(raster(genome, cues, t, height=275), (x - 18, 198))
                    label(image, genome.name, (x + 135, 458))
                    active = next((cue.name for cue in cues if cue.start < t < cue.start + cue.seconds), 'idle')
                    label(image, active, (x + 135, 484), small=True)
                proc.stdin.write(image.convert('RGB').tobytes())
                if frame in (0, 45, 90, 150, 210, 285):
                    image.convert('RGB').save(OUT / 'frames' / f'movie_{frame:03d}.png')
        finally:
            proc.stdin.close()
            code = proc.wait()
        if code:
            raise RuntimeError(f'ffmpeg exited {code}; see {OUT / "encode.log"}')
    print(path, flush=True)


def main():
    (OUT / 'frames').mkdir(parents=True, exist_ok=True)
    heroes = cast()
    flat, line = lineup(heroes, 'flat'), lineup(heroes, 'line_art')
    combined = Image.new('RGBA', (flat.width * 2, flat.height), PAPER)
    combined.alpha_composite(flat)
    combined.alpha_composite(line, (flat.width, 0))
    combined.convert('RGB').save(OUT / 'lineup.png')
    print(OUT / 'lineup.png', flush=True)
    action_strips(heroes)
    movie(heroes)


if __name__ == '__main__':
    main()

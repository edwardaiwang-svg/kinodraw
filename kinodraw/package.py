"""Mux, verify and package a rendered video: chapters, captions, transcript, thumbnail, QA."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

from . import PRODUCT
from .audio.mix import SR, read_wav
from .engine import auto_scenes, ink, skin as skins
from .engine.storyboard import normalize
from .library import resolve

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 30


def sha(path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, check=True, **kw)


def clock(seconds: float) -> str:
    v = int(seconds)
    return f'{v // 3600}:{v // 60 % 60:02}:{v % 60:02}' if v >= 3600 else f'{v // 60:02}:{v % 60:02}'


def _esc(text) -> str:
    return re.sub(r'([\\=;#])', r'\\\1', str(text).replace('\n', ' '))


def mux(tl: dict, silent: Path, mix: Path, output: Path, lang: str, title: str, build: Path):
    iso = {'en': 'eng', 'zh': 'zho', 'es': 'spa'}[lang]
    lines = [';FFMETADATA1', f'title={_esc(title)}', f'encoder={PRODUCT["name"]}', f'language={iso}']
    for c in tl['chapters']:
        lines += ['[CHAPTER]', 'TIMEBASE=1/1000', f"START={round(c['start'] * 1000)}", f"END={round(c['end'] * 1000)}",
                  f"title={_esc(c['title'])}"]
    meta = build / 'chapters.ffmetadata'
    meta.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    partial = output.with_name(output.stem + '.partial.mp4')
    _run([FFMPEG, '-y', '-v', 'error', '-i', str(silent), '-i', str(mix), '-f', 'ffmetadata', '-i', str(meta),
          '-map', '0:v:0', '-map', '1:a:0', '-map_metadata', '2', '-map_chapters', '2', '-c:v', 'copy', '-c:a', 'aac',
          '-b:a', '192k', '-t', str(tl['duration']), '-movflags', '+faststart', str(partial)])
    partial.replace(output)


def video_size(video: Path):
    """(width, height) of a video from its header alone (no decode), or None when ffmpeg finds no video stream."""
    err = subprocess.run([FFMPEG, '-hide_banner', '-i', str(video)], capture_output=True, encoding='utf-8',
                         errors='replace').stderr
    found = re.search(r'Video: [^\n]*?\b([1-9]\d*)x([1-9]\d*)\b', err)
    return (int(found[1]), int(found[2])) if found else None


def _probe(video: Path) -> dict:
    """Stream facts from ffmpeg's own report (no ffprobe needed): frame count by full decode."""
    err = subprocess.run([FFMPEG, '-v', 'info', '-i', str(video), '-map', '0:v:0', '-f', 'null', '-'],
                         capture_output=True, encoding='utf-8', errors='replace').stderr   # UTF-8 on Windows too
    frames = [int(x) for x in re.findall(r'frame=\s*(\d+)', err)]
    head = err.split('Output #0')[0]                  # the input's report (chapters are listed again for the output)
    return {'frames': frames[-1] if frames else 0, 'errors': [l for l in err.splitlines() if 'rror' in l],
            'size': re.search(r'Video: [^\n]*?\b([1-9]\d*)x([1-9]\d*)\b', head), 'audio': 'Audio: aac' in head,
            'chapters': re.findall(r'Chapter #\d+:\d+: start [\d.]+, end [\d.]+\s+Metadata:\s+title\s+:\s*(.*)', head)}


def encoded_qa(tl: dict, video: Path, mix: Path, size=(1920, 1080)) -> dict:
    info = _probe(video)
    expected = round(tl['duration'] * FPS)
    actual_size = info['size'].groups() if info['size'] else None
    problems = []
    if info['frames'] != expected:
        problems.append(f"frames {info['frames']} != {expected}")
    if actual_size != tuple(str(v) for v in size) or not info['audio']:
        problems.append(f'streams: video {actual_size}, aac audio {info["audio"]}')
    if info['errors']:
        problems.append(f"decode errors: {info['errors'][:3]}")
    if [c.strip() for c in info['chapters']] != [c['title'] for c in tl['chapters']]:
        problems.append('embedded chapter titles differ from the timeline')
    ref = read_wav(mix)[0].mean(1)
    checks = []
    for frac in (.1, .5, .9):
        off = int(tl['duration'] * frac)
        raw = _run([FFMPEG, '-v', 'error', '-ss', str(off), '-i', str(video), '-t', '3', '-vn', '-ar', str(SR), '-ac', '1',
                    '-f', 's16le', '-']).stdout
        dec = np.frombuffer(raw, '<i2').astype(np.float32) / 32768
        src = ref[off * SR:off * SR + len(dec)]
        n = min(len(dec), len(src))
        denom = np.sqrt(np.dot(dec[:n], dec[:n]) * np.dot(src[:n], src[:n]))
        corr = float(np.dot(dec[:n], src[:n]) / denom) if denom > 1e-9 else 1.0      # silence matches silence
        checks.append({'at': off, 'waveform_correlation': round(corr, 5)})
        if corr < .95:
            problems.append(f'encoded audio differs from the mix at {off}s ({corr:.3f})')
    from .qa.probes import probe
    probes = probe(video, timeline=tl).to_dict()
    problems += [f"{f['defect']} at {f['start']:.3f}-{f['end']:.3f}s: {f['note']}"
                 for f in probes['findings'] if f['defect'] in ('dead_air', 'frozen_picture')]
    return {'ok': not problems, 'problems': problems, 'probes': probes,
            'frames': info['frames'], 'audio_checks': checks,
            'video_sha256': sha(video), 'duration': tl['duration']}


def contact_sheet(tl: dict, video: Path, path: Path, every: float = 10.0, size=(1920, 1080)):
    """One image with a frame every ``every`` seconds plus each chapter start (for review)."""
    times = sorted({*np.arange(0, tl['duration'] - .1, every).round(2), *(round(c['start'] + 1, 2) for c in tl['chapters'])})
    times = [t for t in times if t < tl['duration'] - .05][:60]
    cols = 6
    w = 180 if size[1] > size[0] else 320
    h = round(w * size[1] / size[0])
    sheet = Image.new('RGB', (cols * w, ((len(times) + cols - 1) // cols) * (h + 26)), 'white')
    d = ImageDraw.Draw(sheet)
    label = ink.font('ui', 18)
    for i, t in enumerate(times):
        raw = _run([FFMPEG, '-v', 'error', '-ss', str(t), '-i', str(video), '-frames:v', '1', '-vf', f'scale={w}:{h}',
                    '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']).stdout
        if len(raw) == w * h * 3:
            x, y = (i % cols) * w, (i // cols) * (h + 26)
            sheet.paste(Image.frombytes('RGB', (w, h), raw), (x, y))
            d.text((x + 4, y + h + 3), clock(t), font=label, fill='black')
    sheet.save(path, quality=88)


def thumbnail(storyboard: dict, lang: str, path: Path, project_dir: Path, size=(1280, 720)):
    """1280x720: the title in big handwriting, section colours, and the video's own actor: the narrator giving a
    thumbs-up in the video's skin, or in the collage look the paper puppet cheering on cream paper."""
    if size == (720, 1280):
        return _portrait_thumbnail(storyboard, lang, path, project_dir)
    collage = storyboard.get('look') == 'collage'
    skin = skins.for_look(storyboard.get('look'))
    if collage:
        from .engine import motion
        img = motion.paper_texture((1280, 720), 'cream').convert('RGBA')
    else:
        img = skin.background(1280, 720).copy()
    d = ImageDraw.Draw(img)
    storyboard = normalize(storyboard)
    title = storyboard['title'][lang]
    lines, size = ink.fit_text(title, lang, 800, 3, 124, min_size=56, fonts=skin.fonts)
    while size > 40 and max(ink.text_width(line, lang, size, skin.fonts) for line in lines) > 800:
        size -= 4                              # a single long word cannot wrap; shrink it instead
    y = 90 if len(lines) < 3 else 60
    for line in lines:
        x = 56
        for part, pf in ink.font_runs(line, lang, size, skin.fonts):
            d.text((x, y), part, font=pf, fill=skin.color((27, 27, 27)), stroke_width=3, stroke_fill=skin.caption_edge)
            x += pf.getlength(part)
        y += int(size * 1.15)
    colors = [skin.color(ink.SECTION_COLORS[c['color']]) for c in storyboard['chapters']
              if c['kind'] == 'section' and c.get('color')]
    for i, col in enumerate(colors[:6]):
        d.rounded_rectangle((56 + i * 70, 640, 106 + i * 70, 668), 10, fill=col)
    if collage:
        from .engine import motion
        from .engine.collage import puppet
        look = storyboard.get('puppet') or {}
        cut = motion.die_cut(puppet.raster('cheer', 'happy', 0, look.get('preset', 'sunny'),
                                           tuple(sorted((look.get('colors') or {}).items())), height=600), border=12)
        x, y = 1280 - cut.width - 40, 720 - cut.height - 10
        shadow = motion.shadow_only(cut, blur=10, opacity=.3)
        img.alpha_composite(shadow, (x + 8 - (shadow.width - cut.width) // 2, y + 10 - (shadow.height - cut.height) // 2))
        img.alpha_composite(cut, (x, y))
        img.convert('RGB').save(path)
        return
    pose = auto_scenes.narrator(storyboard, 'thumbs')
    art = resolve(pose, project_dir) if pose else None
    if art:
        dr = skin.dress(ink.svg_drawing(art, (400, 600)))
        img.alpha_composite(dr.color, (1280 - dr.color.width - 30, 720 - dr.color.height - 20))
    img.convert('RGB').save(path)


def _portrait_thumbnail(storyboard: dict, lang: str, path: Path, project_dir: Path):
    from .engine import motion

    collage = storyboard.get('look') == 'collage'
    skin = skins.for_look(storyboard.get('look'))
    img = motion.paper_texture((720, 1280), 'cream').convert('RGBA') if collage else skin.background(720, 1280).copy()
    d = ImageDraw.Draw(img)
    storyboard = normalize(storyboard)
    title = storyboard['title'][lang]
    lines, size = ink.fit_text(title, lang, 620, 4, 112, min_size=32, fonts=skin.fonts)
    while size > 1 and (len(lines) > 4 or max(ink.text_width(line, lang, size, skin.fonts) for line in lines) > 620):
        size -= 2                              # long words and titles must also stay inside the phone's margins
        lines, size = ink.fit_text(title, lang, 620, 4, size, min_size=size, fonts=skin.fonts)
    y = 60
    for line in lines:
        x = 50
        for part, pf in ink.font_runs(line, lang, size, skin.fonts):
            d.text((x, y), part, font=pf, fill=skin.color((27, 27, 27)), stroke_width=3, stroke_fill=skin.caption_edge)
            x += pf.getlength(part)
        y += int(size * 1.15)
    colors = [skin.color(ink.SECTION_COLORS[c['color']]) for c in storyboard['chapters']
              if c['kind'] == 'section' and c.get('color')]
    for i, col in enumerate(colors[:6]):
        d.rounded_rectangle((50 + i * 70, y + 30, 100 + i * 70, y + 58), 10, fill=col)
    if collage:
        from .engine.collage import puppet
        look = storyboard.get('puppet') or {}
        cut = motion.die_cut(puppet.raster('cheer', 'happy', 0, look.get('preset', 'sunny'),
                                         tuple(sorted((look.get('colors') or {}).items())), height=600), border=12)
        x, y = (720 - cut.width) // 2, 1280 - cut.height - 40
        shadow = motion.shadow_only(cut, blur=10, opacity=.3)
        img.alpha_composite(shadow, (x + 8 - (shadow.width - cut.width) // 2, y + 10 - (shadow.height - cut.height) // 2))
        img.alpha_composite(cut, (x, y))
    else:
        pose = auto_scenes.narrator(storyboard, 'thumbs')
        art = resolve(pose, project_dir) if pose else None
        if art:
            dr = skin.dress(ink.svg_drawing(art, (580, 600)))
            img.alpha_composite(dr.color, ((720 - dr.color.width) // 2, 1280 - dr.color.height - 40))
    img.convert('RGB').save(path)


def publish(storyboard: dict, tl: dict, lang: str, build: Path, folder: Path, stem: str, project_dir: Path,
            own_voice: bool = False, size=(1280, 720), voice_source: str | None = None):
    """Captions, chapters, transcript, description text and thumbnail next to the video (``own_voice``: narrated
    with the creator's own recording; ``voice_source``: a public description of the server voice, without its address)."""
    for ext in ('srt', 'vtt'):
        shutil.copyfile(build / f'captions.{ext}', folder / f'{stem}.{ext}')
    chapters = [f"{clock(c['start'])} {c['title']}" for c in tl['chapters'] if c['title']]
    (folder / f'{stem}-chapters.txt').write_text('\n'.join(chapters) + '\n', encoding='utf-8')
    parts = [f"# {storyboard['title'][lang]}", '']
    for c in storyboard['chapters']:
        tc = next(x for x in tl['chapters'] if x['id'] == c['id'])
        if tc['title']:
            parts.append(f"## {tc['title']}")
        parts += [b['display'][lang] for b in storyboard['beats'] if b['chapter'] == c['id']]
    (folder / f'{stem}-transcript.md').write_text('\n\n'.join(parts) + '\n', encoding='utf-8')
    voice = ("the creator's own voice" if own_voice else 'Kokoro AI voice') if lang == 'en' else \
        ('作者本人的声音' if own_voice else 'Kokoro AI 语音')
    if voice_source and not own_voice:
        voice = voice_source
    credit = (f'Made with {PRODUCT["name"]}. Narration: {voice}. Music: FreePD (CC0).' if lang == 'en' else
              f'由 {PRODUCT["name"]} 制作。旁白：{voice}。音乐：FreePD（CC0）。')
    head = 'Chapters' if lang == 'en' else '章节'
    if lang == 'es':
        voice = 'la voz del creador' if own_voice else 'voz de IA de Kokoro'
        if voice_source and not own_voice:
            voice = voice_source
        credit = f'Hecho con {PRODUCT["name"]}. Narración: {voice}. Música: FreePD (CC0).'
        head = 'Capítulos'
    (folder / f'{stem}-description.txt').write_text(
        f"{storyboard['title'][lang]}\n\n{head}\n" + '\n'.join(chapters) + f'\n\n{credit}\n', encoding='utf-8')
    thumbnail(storyboard, lang, folder / f'{stem}-thumbnail.png', project_dir, size=size)

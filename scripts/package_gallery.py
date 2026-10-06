"""Build a local source gallery or package decoded, source-backed showcase outputs.

No downloads, credentials, app migration, publishing or uploads. Run from a source
checkout with its existing Python dependencies. Existing destinations are refused.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from kinodraw.project_zip import import_project, _rename_noreplace

IDS = ('lion', 'explainer', 'product-launch', 'lesson', 'news')
SUFFIXES = {'video': ('.mp4',), 'script': ('.md', '.txt'), 'project': ('.zip',), 'captions': ('.vtt',),
            'description': ('.md', '.txt'), 'sources': ('.json',)}
REQUIRED = ('video', 'script', 'project', 'captions', 'description')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_absolute(path):
    path = Path(path).absolute()
    if '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('absolute paths must not contain traversal or symlinks')
    return path


def source_path(root, value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('artifact paths must be relative POSIX paths')
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') or p.startswith('.') for p in parts):
        raise ValueError('unsafe artifact path')
    path = root.joinpath(*parts)
    if any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
        raise ValueError('artifact symlinks are refused')
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'missing or empty artifact: {value}')
    return path


def run_ffmpeg(ffmpeg, args):
    result = subprocess.run([ffmpeg, '-nostdin', *args], capture_output=True,
                            text=True, timeout=900)
    if result.returncode:
        raise ValueError(f'FFmpeg verification failed (exit {result.returncode}): {result.stderr[-1500:]}')
    return result


def verify_video(path, ffmpeg, *, partial):
    # Decode every frame and audio packet, not just container metadata.
    args = ['-v', 'error', '-xerror', '-err_detect', 'explode', '-i', str(path),
            '-map', '0:v:0', '-map', '0:a:0?' if partial else '0:a:0',
            '-vsync', '0', '-progress', 'pipe:1', '-f', 'null', '-']
    decoded = run_ffmpeg(ffmpeg, args)
    frames = [int(n) for n in re.findall(r'^frame=(\d+)$', decoded.stdout, re.M)]
    if not frames or frames[-1] <= 0 or 'progress=end' not in decoded.stdout:
        raise ValueError('video did not decode a complete nonempty frame sequence')
    audio = None
    if not partial:
        levels = run_ffmpeg(ffmpeg, ['-hide_banner', '-i', str(path), '-map', '0:a:0',
                                    '-af', 'volumedetect', '-vn', '-f', 'null', '-'])
        match = re.search(r'max_volume: ([-\w.]+) dB', levels.stderr)
        if not match or match.group(1) == '-inf':
            raise ValueError('final showcase audio must contain nonzero samples')
        audio = float(match.group(1))
    return {'decoded_frames': frames[-1], 'decode_exit': decoded.returncode,
            'audio_max_db': audio, 'audio_required': not partial}


def page(entries, *, packaged=False, partial=False):
    esc = lambda s: html.escape(str(s), quote=True)
    cards = []
    for entry in entries:
        links, media, meta = [], '<div class="media">Editable source example</div>', ''
        if 'artifacts' in entry:
            a = entry['artifacts']
            media = (f'<video controls preload="metadata" poster="{esc(a["thumbnail"]["path"])}" '
                     f'aria-label="{esc(entry["title"])}"><source src="{esc(a["video"]["path"])}" type="video/mp4">'
                     f'<track kind="captions" src="{esc(a["captions"]["path"])}" srclang="en" label="English">'
                     'Your browser cannot play this MP4. Use the video download below.</video>')
            names = {'video': 'Download MP4', 'script': 'Read script', 'project': 'Project ZIP',
                     'captions': 'Captions', 'description': 'Description', 'sources': 'Source provenance',
                     'screenshot': 'Frame strip / screenshot', 'thumbnail': 'Thumbnail'}
            links = [f'<a href="{esc(record["path"])}">{names[k]}</a>' for k, record in a.items()]
            check = entry['verification']
            meta = (f'<details><summary>Artifact checks &amp; provenance</summary><p class="metadata">'
                    f'{check["decoded_frames"]:,} frames fully decoded · decode exit {check["decode_exit"]}. '
                    'This verifies media integrity; visual/editorial acceptance remains a separate review.</p>' +
                    ''.join(f'<p class="metadata">{names[k]} · {r["bytes"]:,} bytes<br>SHA-256 <code>{r["sha256"]}</code></p>'
                            for k, r in a.items()) + '</details>')
        else:
            links = [f'<a href="../../examples/showcases/{esc(entry["script"])}">Read editable script</a>']
        cards.append(f'<article class="demo" data-category="{esc(entry["category"])}">{media}<div class="body">'
                     f'<span class="tag">{esc(entry["category"])}</span><h2>{esc(entry["title"])}</h2>'
                     f'<p>{esc(entry["summary"])}</p><div class="links">{"".join(links)}</div>{meta}</div></article>')
    if packaged:
        status = ('Partial verification pack. It is not the accepted five-showcase delivery.' if partial else
                  'Five showcase outputs packaged from local files. All videos decoded successfully; see the manifest for hashes and review evidence.')
        kit = '<a href="launch-kit/README.md">Launch kit</a> · <a href="manifest.json">Artifact manifest</a>'
        science = 'assets/scientific/'
        css = 'gallery/gallery.css'
    else:
        status = 'Source portfolio. Final movies are not shipped on this page. Build them locally or package reviewed outputs with the launch-kit helper.'
        kit = '<a href="../launch-kit/README.md">Build the local launch kit</a> · <a href="../developer.md">Developer guide</a>'
        science = '../../examples/scientific/'
        css = 'gallery.css'
    categories = list(dict.fromkeys(e['category'] for e in entries))
    buttons = '<button type="button" aria-pressed="true" data-filter="all">All examples</button>' + ''.join(
        f'<button type="button" aria-pressed="false" data-filter="{esc(c)}">{esc(c)}</button>' for c in categories)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KinoDraw · Script to screen</title><meta name="description" content="Explore editable KinoDraw story, explainer, launch, lesson and data examples.">
<link rel="stylesheet" href="{css}"></head><body><a class="skip" href="#examples">Skip to examples</a><div class="wrap">
<nav aria-label="Main"><a class="brand" href="#">Kino<span>Draw</span></a><div>{kit}</div></nav>
<header><div class="eyebrow">Local portfolio / editable examples</div><h1>One script.<br><span>Many ways to tell it.</span></h1>
<p class="lead">Stories, explainers, lessons and data. Explore the source behind each video, then make the next one your own.</p>
<p class="notice">{status}</p></header><main id="examples"><div class="toolbar" role="group" aria-label="Filter examples">{buttons}</div>
<p id="count" class="metadata" aria-live="polite">{len(entries)} example{'s' if len(entries) != 1 else ''}</p><div class="grid">{''.join(cards)}</div>
<section class="science"><div class="eyebrow">Source-backed science</div><h2>Numbers with a provenance trail.</h2>
<p>Explore 47 NOAA annual CO₂ means and an explicitly analytical harmonic oscillator. The retained data, equations, units and source notes travel with the examples.</p>
<div class="links"><a href="{science}README.md">Scientific source guide</a><a href="{science}noaa-co2.json">NOAA plot data</a>
<a href="{science}oscillator.json">Oscillator model</a><a href="{science}noaa-co2-annmean-2026-10-06.txt">Retained NOAA input</a></div></section></main>
<footer>KinoDraw · Local files, editable sources. No upload or publication is performed by this gallery.<br>{kit}</footer></div>
<script>document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{{let count=0;document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('[data-category]').forEach(card=>{{card.hidden=button.dataset.filter!=='all'&&card.dataset.category!==button.dataset.filter;if(!card.hidden)count++;}});document.getElementById('count').textContent=count+' example'+(count===1?'':'s');}}));</script></body></html>
'''


def package(manifest, root, output, *, partial=False):
    root, output = safe_absolute(root), safe_absolute(output)
    if not root.is_dir() or not output.parent.is_dir():
        raise ValueError('artifact root and output parent must be existing directories')
    if output.exists():
        raise ValueError('destination already exists; use a fresh output directory')
    data = json.loads(safe_absolute(manifest).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('entries'), list):
        raise ValueError('expected manifest version 1 and entries list')
    entries = data['entries']
    if any(not isinstance(e, dict) for e in entries):
        raise ValueError('each entry must be an object')
    ids = [e.get('id') for e in entries]
    if not entries or len(set(ids)) != len(ids) or any(i not in IDS for i in ids):
        raise ValueError('entries must have distinct known showcase IDs')
    if not partial and set(ids) != set(IDS):
        raise ValueError('final delivery requires exactly lion/explainer/product-launch/lesson/news')
    catalog = {e['id']: e for e in json.loads((REPO / 'examples/showcases/catalog.json').read_text())}
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix='.gallery-', dir=output.parent) as tmp:
        stage = Path(tmp) / 'pack'
        stage.mkdir()
        packed = []
        for item in entries:
            if any(k not in item for k in REQUIRED):
                raise ValueError(f'{item["id"]}: requires {", ".join(REQUIRED)}')
            folder = stage / 'assets' / item['id']
            folder.mkdir(parents=True)
            artifacts = {}
            for kind in (*REQUIRED, 'sources', 'screenshot'):
                if kind not in item:
                    continue
                source = source_path(root, item[kind])
                suffix = source.suffix.lower()
                if (kind == 'screenshot' and suffix not in ('.png', '.jpg', '.jpeg')) or (kind != 'screenshot' and suffix not in SUFFIXES[kind]):
                    raise ValueError(f'{kind}: unsupported file type {suffix}')
                target = folder / (kind + suffix)
                before = digest(source)
                shutil.copyfile(source, target)
                if digest(target) != before or digest(source) != before:
                    raise ValueError('artifact changed while being copied')
                artifacts[kind] = {'path': target.relative_to(stage).as_posix(), 'bytes': target.stat().st_size, 'sha256': before}
            def asset(k):
                return stage / artifacts[k]['path']
            if not asset('captions').read_text(encoding='utf-8').lstrip('\ufeff').startswith('WEBVTT'):
                raise ValueError('captions must be a real WebVTT file')
            # Reuse the product importer to verify the real ZIP manifest, hashes and path rules.
            with zipfile.ZipFile(asset('project')) as archive:
                if any(any(part.startswith('.') and not (i == 0 and part == '.studio')
                           for i, part in enumerate(PurePosixPath(name).parts))
                       for name in archive.namelist()):
                    raise ValueError('hidden/private archive entries are refused')
            verified_project = Path(tmp) / ('verify-' + item['id'])
            import_project(asset('project'), verified_project)
            config = json.loads((verified_project / 'project.json').read_text(encoding='utf-8'))
            archived_script = source_path(verified_project, config.get('script'))
            if digest(archived_script) != artifacts['script']['sha256']:
                raise ValueError('packaged script differs from the project ZIP source')
            if 'screenshot' in artifacts:
                from PIL import Image
                with Image.open(asset('screenshot')) as screenshot:
                    screenshot.verify()
            if 'sources' in artifacts:
                json.loads(asset('sources').read_text(encoding='utf-8'))
            check = verify_video(asset('video'), ffmpeg, partial=partial)
            thumb = folder / 'thumbnail.png'
            run_ffmpeg(ffmpeg, ['-v', 'error', '-i', str(asset('video')), '-vf', 'thumbnail,scale=960:-2',
                               '-frames:v', '1', str(thumb)])
            if not thumb.is_file() or thumb.stat().st_size == 0:
                raise ValueError('thumbnail extraction produced no image')
            artifacts['thumbnail'] = {'path': thumb.relative_to(stage).as_posix(), 'bytes': thumb.stat().st_size, 'sha256': digest(thumb)}
            entry = dict(catalog[item['id']], artifacts=artifacts, verification=check)
            board = json.loads((verified_project / 'storyboard.json').read_text(encoding='utf-8'))
            title = board.get('title')
            if isinstance(title, dict):
                title = title.get(config.get('lang') or board.get('lang') or 'en')
            if isinstance(title, str) and title.strip():
                entry['title'] = title
            if partial:
                entry['summary'] = 'A packaged verification excerpt. Inspect its actual script and project; this is not a final showcase.'
            entry.pop('script')
            # Optional review references are free text, never an implied PASS.
            if 'review' in item:
                if not isinstance(item['review'], str):
                    raise ValueError('review must be a textual evidence reference')
                entry['review'] = item['review']
            packed.append(entry)
        shutil.copytree(REPO / 'examples/scientific', stage / 'assets/scientific')
        (stage / 'gallery').mkdir()
        shutil.copyfile(REPO / 'docs/gallery/gallery.css', stage / 'gallery/gallery.css')
        (stage / 'media').mkdir()
        shutil.copyfile(REPO / 'docs/media/PlaypenSans-Bold.ttf', stage / 'media/PlaypenSans-Bold.ttf')
        shutil.copyfile(REPO / 'docs/media/OFL-PlaypenSans.txt', stage / 'media/OFL-PlaypenSans.txt')
        (stage / 'launch-kit').mkdir()
        shutil.copyfile(REPO / 'docs/launch-kit/COPY.md', stage / 'launch-kit/COPY.md')
        shutil.copyfile(REPO / 'docs/launch-kit/PORTABLE.md', stage / 'launch-kit/README.md')
        (stage / 'index.html').write_text(page(packed, packaged=True, partial=partial), encoding='utf-8')
        result = {'format': 'kinodraw-local-gallery/1', 'partial': partial, 'entries': packed}
        # Enumerate every delivered file except the self-referential manifest itself.
        result['files'] = {p.relative_to(stage).as_posix(): {'bytes': p.stat().st_size, 'sha256': digest(p)}
                           for p in sorted(stage.rglob('*')) if p.is_file()}
        (stage / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        _rename_noreplace(stage, output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--partial', action='store_true', help='explicit incomplete/silent verification pack; never final acceptance')
    parser.add_argument('--source-preview', action='store_true', help='refresh committed source-only gallery; no videos claimed')
    args = parser.parse_args()
    try:
        if args.source_preview:
            if args.manifest or args.root or args.output or args.partial:
                raise ValueError('--source-preview takes no other arguments')
            entries = json.loads((REPO / 'examples/showcases/catalog.json').read_text())
            (REPO / 'docs/gallery/index.html').write_text(page(entries), encoding='utf-8')
            print('updated docs/gallery/index.html (source examples only)')
        else:
            if not all((args.manifest, args.root, args.output)):
                raise ValueError('--manifest, --root and --output are required')
            result = package(args.manifest, args.root, args.output, partial=args.partial)
            print(json.dumps({'output': str(args.output.absolute()), 'partial': result['partial'],
                              'examples': len(result['entries']), 'files': len(result['files'])}))
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired, zipfile.BadZipFile) as error:
        parser.exit(1, f'gallery packaging failed: {error}\n')


if __name__ == '__main__':
    main()

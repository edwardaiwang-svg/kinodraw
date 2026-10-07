#!/usr/bin/env python3
"""Generate the preset creature doodles (animals and people in poses) offline and deterministically.

Usage:
  python scripts/gen_creatures.py                       # write kinodraw/assets/doodles/creatures + tags
  python scripts/gen_creatures.py --only lion,hyena --out /tmp/x --sheets /tmp/x/sheets
  python scripts/gen_creatures.py --check               # regenerate in memory and diff against the files

The method follows procedural-pixel-creatures (MIT, idlerunner00): families -> body plans -> typed genes
-> rig -> poses -> render; see kinodraw/library/creaturegen/. Only families whose contact sheets passed
review are listed in species.SHIP.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kinodraw.library.creaturegen import build, species  # noqa: E402

ASSETS = ROOT / 'kinodraw' / 'assets' / 'doodles'


def generate(only=None):
    files, tags = {}, {}
    for v in species.catalogue():
        if only and v.species not in only and v.family not in only:
            continue
        for pid, svg, meta in build.render_variant(v):
            files[pid] = svg
            tags[pid] = build.tag_entry(v, meta)
    return files, dict(sorted(tags.items()))


def sheet(paths, out, cell=200, cols=8, label=True):
    import resvg_py
    from PIL import Image, ImageDraw
    rows = math.ceil(len(paths) / cols) or 1
    board = Image.new('RGB', (cols * (cell + 8), rows * (cell + (18 if label else 8))), '#FFFFFF')
    draw = ImageDraw.Draw(board)
    for i, path in enumerate(paths):
        png = resvg_py.svg_to_bytes(svg_string=Path(path).read_text(encoding='utf-8'))
        im = Image.open(io.BytesIO(png)).convert('RGBA')
        scale = cell / max(im.size)
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
        x, y = (i % cols) * (cell + 8), (i // cols) * (cell + (18 if label else 8))
        board.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2), im)
        if label:
            draw.text((x + 2, y + cell + 3), Path(path).stem.removeprefix('cr_')[:34], fill='#555555')
    out.parent.mkdir(parents=True, exist_ok=True)
    board.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='comma-separated species or families')
    ap.add_argument('--out', default=str(ASSETS / 'creatures'))
    ap.add_argument('--tags', default=None, help='tags json path (default: <assets>/tags/creatures.json when --out is the default)')
    ap.add_argument('--sheets', default='', help='folder for per-species contact sheets')
    ap.add_argument('--check', action='store_true', help='compare a fresh generation with the files on disk')
    args = ap.parse_args()
    only = {s for s in args.only.split(',') if s}
    files, tags = generate(only)
    out = Path(args.out)
    tags_path = Path(args.tags) if args.tags else (ASSETS / 'tags' / 'creatures.json' if out == ASSETS / 'creatures'
                                                    else out / 'creatures.json')
    tags_text = json.dumps(tags, ensure_ascii=False, indent=1) + '\n'
    if args.check:
        bad = [pid for pid, svg in files.items() if not (out / f'{pid}.svg').exists()
               or (out / f'{pid}.svg').read_text(encoding='utf-8') != svg]
        stale = [] if only else sorted(p.stem for p in out.glob('*.svg') if p.stem not in files)
        tags_ok = only or (tags_path.exists() and tags_path.read_text(encoding='utf-8') == tags_text)
        print(json.dumps({'generated': len(files), 'different': bad[:20], 'n_different': len(bad), 'stale': stale[:20],
                          'tags_match': bool(tags_ok)}, indent=1))
        sys.exit(1 if bad or stale or not tags_ok else 0)
    out.mkdir(parents=True, exist_ok=True)
    if not only:
        for old in out.glob('*.svg'):
            if old.stem not in files:
                old.unlink()
    for pid, svg in files.items():
        (out / f'{pid}.svg').write_text(svg, encoding='utf-8')
    if not only or args.tags or out != ASSETS / 'creatures':
        tags_path.parent.mkdir(parents=True, exist_ok=True)
        tags_path.write_text(tags_text, encoding='utf-8')
    if args.sheets:
        groups = {}
        for pid, entry in tags.items():
            c = entry['creature']
            key = '_'.join(x for x in (c['species'], c['sex'], c['age'], c['variant']) if x)
            groups.setdefault(key, []).append(out / f'{pid}.svg')
        for key, paths in groups.items():
            body = [p for p in paths if '_face_' not in p.stem and p.stem.endswith('_r')]
            face = [p for p in paths if '_face_' in p.stem]
            sheet(body + face + [p for p in paths if p.stem.endswith('_stand_l')],
                  Path(args.sheets) / f'{key}.png')
    print(json.dumps({'presets': len(files), 'out': str(out), 'tags': str(tags_path)}))


if __name__ == '__main__':
    main()

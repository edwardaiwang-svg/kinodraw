#!/usr/bin/env python3
"""Validate doodle SVGs against doodles/STYLE.md and render review sheets.

Usage: python -m kinodraw.library.check [ids...] [--set bespoke|fluent] [--sheet NAME]
--set fluent (converted emoji): same rules minus the palette and the 5-element minimum.
Writes PNG contact sheets to <user cache>/DoodleStudio/review/doodles/.
Prints one JSON report; exit code 1 when any file fails.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import resvg_py
import svgelements
from PIL import Image, ImageDraw, ImageFont

import platformdirs

HERE = Path(__file__).resolve().parents[1]          # kinodraw/
LIBRARY = HERE / 'assets' / 'doodles'
DOODLES = LIBRARY / 'bespoke'
REVIEW = Path(platformdirs.user_cache_dir('DoodleStudio')) / 'review' / 'doodles'
SVGNS = '{http://www.w3.org/2000/svg}'
PALETTE = {c.lower() for c in (
    '#E53935 #1E6FD9 #64B5F6 #1A3A6B #43A047 #9CCC65 #FDD835 #F9A825 #FB8C00 #8E24AA '
    '#00897B #F48FB1 #8D6E63 #D7B98E #F6C9A4 #E8A87C #FFFFFF #E0E0E0 #9E9E9E #424242 '
    '#1B1B1B #FFF8E1 #7E93A8 #B8C6D3 #B08D57').split()} | {'none'}
INK = '#1b1b1b'
ALLOWED = {'svg', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'g'}
ATTRS = {'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'fill-rule',
         'transform', 'd', 'x', 'y', 'width', 'height', 'rx', 'ry', 'cx', 'cy', 'r', 'points',
         'x1', 'y1', 'x2', 'y2', 'id', 'viewBox', 'xmlns', 'version'}
SHAPES = ALLOWED - {'svg', 'g'}


def check(path: Path, fluent: bool = False) -> dict:
    problems, warnings = [], []
    text = path.read_text()
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        return {'id': path.stem, 'ok': False, 'problems': [f'XML: {error}']}
    if root.tag != SVGNS + 'svg':
        problems.append('root must be <svg> in the SVG namespace')
    vb = [float(v) for v in re.split(r'[ ,]+', root.get('viewBox', '').strip()) if v]
    if len(vb) != 4 or vb[0] or vb[1]:
        problems.append('viewBox must be "0 0 W H"')
        vb = [0, 0, 300, 300]
    width, height = vb[2], vb[3]
    if not (200 <= width <= 600 and 200 <= height <= 600):
        problems.append(f'viewBox size {width}x{height} outside 200–600')
    count = 0
    inherited = {}

    def walk(node, parent_attrs):
        nonlocal count
        tag = node.tag.replace(SVGNS, '')
        if tag not in ALLOWED:
            problems.append(f'element <{tag}> not allowed')
            return
        attrs = dict(parent_attrs)
        for key, value in node.attrib.items():
            if key.startswith('data-'):
                continue
            if key not in ATTRS:
                problems.append(f'<{tag}> attribute {key!r} not allowed')
            attrs[key] = value
        if tag in SHAPES:
            count += 1
            fill = attrs.get('fill', 'black' if tag not in ('line', 'polyline') else 'none').lower()
            stroke = attrs.get('stroke', 'none').lower()
            if fill not in PALETTE and not fluent:
                problems.append(f'{node.get("id") or tag}: fill {fill} not in palette')
            if stroke not in PALETTE and not fluent:
                problems.append(f'{node.get("id") or tag}: stroke {stroke} not in palette')
            if stroke != 'none':
                try:
                    sw = float(attrs.get('stroke-width', '1'))
                except ValueError:
                    sw = 0
                if sw < 3:
                    problems.append(f'{node.get("id") or tag}: stroke-width {sw} < 3')
            elif node.get('data-noink') != '1' and fill != 'none':
                warnings.append(f'{node.get("id") or tag}: filled shape without ink outline')
            if stroke == 'none' and fill == 'none':
                problems.append(f'{node.get("id") or tag}: invisible element')
        for child in node:
            walk(child, attrs if tag == 'g' else parent_attrs)

    for child in root:
        walk(child, inherited)
    least = 1 if fluent else 5
    if not least <= count <= 70:
        problems.append(f'{count} drawable elements (allowed {least}–70)')
    # Geometry via svgelements: bounds and outline length.
    try:
        doc = svgelements.SVG.parse(io.StringIO(text))
        boxes, length = [], 0.0
        for element in doc.elements():
            if isinstance(element, svgelements.Shape):
                p = svgelements.Path(element)
                if len(p) == 0:
                    continue
                bb = p.bbox()
                if bb:
                    boxes.append(bb)
                length += p.length(error=1e-3, min_depth=2)
        if boxes:
            x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
            x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
            if x0 < 6 or y0 < 6 or x1 > width - 6 or y1 > height - 6:
                problems.append(f'drawing bounds {x0:.0f},{y0:.0f}–{x1:.0f},{y1:.0f} touch the edge (need ≥ 6 px padding)')
            fill_ratio = (x1 - x0) * (y1 - y0) / (width * height)
            if fill_ratio < .35:
                warnings.append(f'drawing uses only {fill_ratio:.0%} of its box; enlarge or shrink viewBox')
        outline = length / max(width, height)
    except Exception as error:  # noqa: BLE001 - report parse failure as a problem
        problems.append(f'svgelements: {error}')
        outline = 0
    return {'id': path.stem, 'ok': not problems, 'problems': problems, 'warnings': warnings,
            'elements': count, 'size': [width, height], 'outline_ratio': round(outline, 1)}


def render(path: Path, box: int, outline_only=False) -> Image.Image:
    text = path.read_text()
    if outline_only:
        text = re.sub(r'fill="(?!none)[^"]*"', 'fill="none"', text)
    png = resvg_py.svg_to_bytes(svg_string=text, width=None, height=None, zoom=None)
    image = Image.open(io.BytesIO(png)).convert('RGBA')
    scale = box / max(image.size)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)


def sheet(paths, name):
    REVIEW.mkdir(parents=True, exist_ok=True)
    cell, cols = 330, 5
    rows = math.ceil(len(paths) / cols) or 1
    board = Image.new('RGB', (cols * cell, rows * (cell + 40)), '#ECEBE6')
    draw = ImageDraw.Draw(board)
    font = ImageFont.truetype(str(HERE / 'assets' / 'fonts' / 'Arimo-Bold.ttf'), 22)
    for i, path in enumerate(paths):
        x, y = (i % cols) * cell, (i // cols) * (cell + 40)
        try:
            art = render(path, 290)
            line = render(path, 110, outline_only=True)
            board.paste(art, (x + (cell - art.width) // 2, y + 10), art)
            small = Image.new('RGBA', line.size, (236, 235, 230, 255))
            small.alpha_composite(line)
            board.paste(small, (x + cell - line.width - 4, y + cell - line.height - 4))
        except Exception as error:  # noqa: BLE001
            draw.text((x + 10, y + 100), f'RENDER FAIL {error}'[:60], fill='red', font=font)
        draw.text((x + 8, y + cell + 6), path.stem, fill='#1B1B1B', font=font)
    out = REVIEW / f'{name}.png'
    board.save(out)
    # Phone-size check: same sheet at 1/3 scale.
    board.resize((board.width // 3, board.height // 3), Image.LANCZOS).save(REVIEW / f'{name}-phone.png')
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('ids', nargs='*')
    parser.add_argument('--sheet', default='sheet')
    parser.add_argument('--set', default='bespoke', choices=['bespoke', 'fluent'])
    args = parser.parse_args()
    root = LIBRARY / args.set
    paths = [root / f'{i}.svg' for i in args.ids] if args.ids else sorted(root.glob('*.svg'))
    missing = [str(p) for p in paths if not p.exists()]
    reports = [check(p, args.set == 'fluent') for p in paths if p.exists()]
    out = sheet([p for p in paths if p.exists()], args.sheet) if paths else None
    failed = [r for r in reports if not r['ok']]
    print(json.dumps({'checked': len(reports), 'failed': len(failed), 'missing': missing, 'review_dir': str(REVIEW),
                      'sheet': str(out) if out else None, 'reports': reports}, ensure_ascii=False, indent=1))
    sys.exit(1 if failed or missing else 0)


if __name__ == '__main__':
    main()

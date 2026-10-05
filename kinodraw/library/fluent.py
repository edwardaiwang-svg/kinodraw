#!/usr/bin/env python3
"""Convert Microsoft Fluent Emoji "Flat" SVGs (MIT) into KinoDraw's outlined style.

Usage: python -m kinodraw.library.fluent SRC_DIR

SRC_DIR (e.g. ~/Library/Caches/KinoDraw/src) must contain
  fluentui-emoji/                    sparse clone: LICENSE, assets/*/metadata.json, Flat SVGs
  cldr_zh_annotations.json           cldr-json annotations/zh/annotations.json
  cldr_zh_annotations_derived.json   cldr-json annotationsDerived/zh/annotations.json

Writes assets/doodles/fluent/fl_<name>.svg (+ LICENSE, NOTICE.md) and
assets/doodles/tags/fluent.json. The output depends only on the sources.

Each shape keeps its flat colour and document order. The ink outline is chosen from a
raster analysis of the layered shapes: big shapes on the paper get 6 px, inner parts
3-4 px; tiny details, highlights and shading patches get data-noink="1" and no stroke.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
import svgelements as se
from PIL import Image, ImageDraw
from scipy import ndimage

from kinodraw.library.check import LIBRARY

OUT = LIBRARY / 'fluent'
TAGS = LIBRARY / 'tags' / 'fluent.json'
SIZE, PAD, SS = 320, 16, 2          # output box, padding, analysis supersampling
INK = '#1B1B1B'
MAX_SHAPES = 70
PAPER = '#FFF8E1'
UPSTREAM = 'https://github.com/microsoft/fluentui-emoji'
VS16 = '\ufe0f'                     # emoji presentation selector, ignored when matching
STOPWORDS = {'a', 'an', 'and', 'at', 'by', 'for', 'in', 'of', 'on', 'the', 'to', 'with', 'without'}

DENY = {  # asset names never converted (requested denylist + sexual/drug/death connotations)
    'middle finger', 'cigarette', 'water pistol', 'bomb', 'dagger', 'drop of blood', 'syringe',
    'pill', 'skull and crossbones', 'coffin', 'funeral urn', 'headstone', 'bikini', 'briefs',
    'kiss mark', 'eggplant', 'peach', 'biting lip', 'tongue', 'sweat droplets', 'love hotel',
    'beer mug', 'clinking beer mugs', 'wine glass', 'cocktail glass', 'tropical drink',
    'tumbler glass', 'bottle with popping cork', 'sake', 'clinking glasses'}
TEXT = re.compile(  # letters/digits inside the art (STYLE.md: no text in doodles)
    r'^(a|ab|b|o) button blood type$|^(cl|cool|free|id|new|ng|ok|sos|up!|vs|p) button$'
    r'|^japanese .* button$|^keycap \d+$|^(back|end|on!|soon|top) arrow$|^input (latin|numbers)'
    r'|^(atm sign|circled m|copyright|registered|trade mark|hundred points|water closet'
    r'|mobile phone off|no one under eighteen|white flower)$')


class Skip(Exception):
    """An emoji that is not converted; the message is the reason recorded in NOTICE.md."""


# ------------------------------------------------------------------ colour helpers
def hex_of(color) -> str | None:
    if color is None or color.value is None or color.alpha == 0:
        return None
    return f'#{color.red:02X}{color.green:02X}{color.blue:02X}'


def rgb(hexcol: str) -> np.ndarray:
    return np.array([int(hexcol[i:i + 2], 16) for i in (1, 3, 5)], float)


def lab(hexcol: str) -> np.ndarray:
    c = rgb(hexcol) / 255
    c = np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)
    xyz = np.array([[.4124, .3576, .1805], [.2126, .7152, .0722], [.0193, .1192, .9505]]) @ c
    xyz /= (.95047, 1., 1.08883)
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def color(sh: dict) -> str:
    return sh['fill'] or sh['line']


def blend(top: str, under: str, alpha: float) -> str:
    mix = rgb(top) * alpha + rgb(under) * (1 - alpha)
    return '#' + ''.join(f'{round(v):02X}' for v in mix)


# ------------------------------------------------------------------ geometry
def num(v: float) -> str:
    s = f'{v:.1f}'.rstrip('0').rstrip('.')
    return '0' if s == '-0' else s


def path_d(path: se.Path) -> str:
    pt = lambda p: f'{num(p.x)},{num(p.y)}'  # noqa: E731
    out = []
    for seg in path:
        if isinstance(seg, se.Move):
            out.append('M' + pt(seg.end))
        elif isinstance(seg, se.Close):
            out.append('Z')
        elif isinstance(seg, se.Line):
            out.append('L' + pt(seg.end))
        elif isinstance(seg, se.QuadraticBezier):
            out.append(f'Q{pt(seg.control)} {pt(seg.end)}')
        elif isinstance(seg, se.CubicBezier):
            out.append(f'C{pt(seg.control1)} {pt(seg.control2)} {pt(seg.end)}')
        elif isinstance(seg, se.Arc):
            out.extend(f'C{pt(c.control1)} {pt(c.control2)} {pt(c.end)}' for c in seg.as_cubic_curves())
    return ''.join(out)


def polygons(path: se.Path, scale: float) -> list[np.ndarray]:
    """Flatten each subpath to a polygon (points in raster pixels)."""
    out = []
    for sub in path.as_subpaths():
        sub = se.Path(sub)
        try:
            length = sub.length(error=1e-3, min_depth=2)
        except Exception:  # noqa: BLE001 - degenerate subpath
            continue
        if length > 0:
            n = max(8, int(length * scale / 1.5))
            out.append(np.asarray(sub.npoint(np.linspace(0, 1, n)), float) * scale)
    return out


def raster(shape: dict, scale: float, size: int) -> np.ndarray:
    """Coverage mask of one shape at analysis resolution (fill rule honoured)."""
    acc = np.zeros((size, size), np.int16)
    for poly in polygons(shape['path'], scale):
        img = Image.new('L', (size, size), 0)
        pts = [tuple(p) for p in poly]
        if shape['fill']:
            if len(pts) >= 3:
                ImageDraw.Draw(img).polygon(pts, fill=1)
                area = np.sum(poly[:-1, 0] * poly[1:, 1] - poly[1:, 0] * poly[:-1, 1])
                layer = np.asarray(img, np.int16)
                acc += layer if shape['rule'] == 'evenodd' or area >= 0 else -layer
        else:  # source stroke-only line
            w = max(1, round(shape['src_width'] * scale))
            ImageDraw.Draw(img).line(pts, fill=1, width=w, joint='curve')
            for x, y in (pts[0], pts[-1]):
                ImageDraw.Draw(img).ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=1)
            acc += np.asarray(img, np.int16)
    return (acc % 2 == 1) if shape['rule'] == 'evenodd' and shape['fill'] else acc != 0


# ------------------------------------------------------------------ conversion
def load(svg_file: Path) -> list[dict]:
    """Shapes in document order with transforms baked in, fitted to the output box."""
    text = svg_file.read_text(encoding='utf-8')
    if 'url(#' in text:
        raise Skip('look relies on gradients/clipPath/mask/filter')
    shapes = []
    for el in se.SVG.parse(io.StringIO(text), reify=True).elements():
        if not isinstance(el, se.Shape):
            continue
        path = abs(se.Path(el))
        fill, stroke = hex_of(el.fill), hex_of(el.stroke)
        if len(path) == 0 or path.bbox() is None or not (fill or stroke):
            continue
        shapes.append({'path': path, 'fill': fill, 'rule': el.values.get('fill-rule', 'nonzero'),
                       'alpha': float(el.values.get('opacity', 1)),
                       'line': None if fill else stroke, 'src_width': float(el.stroke_width or 1)})
    if not shapes:
        raise Skip('no drawable shapes')
    boxes = []
    for sh in shapes:
        x0, y0, x1, y1 = sh['path'].bbox()
        grow = 0 if sh['fill'] else sh['src_width'] / 2
        boxes.append((x0 - grow, y0 - grow, x1 + grow, y1 + grow))
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    scale = (SIZE - 2 * PAD) / max(x1 - x0, y1 - y0)
    fit = se.Matrix(scale, 0, 0, scale, (SIZE - (x1 - x0) * scale) / 2 - x0 * scale,
                    (SIZE - (y1 - y0) * scale) / 2 - y0 * scale)
    for sh in shapes:
        sh['path'] = abs(sh['path'] * fit)
        sh['src_width'] *= scale
    return shapes


def analyse(shapes: list[dict]) -> None:
    """Per shape: area, visible area, thickness, the shape it sits on, share on paper."""
    n = SIZE * SS
    labels = np.full((n, n), -1, np.int16)
    for i, sh in enumerate(shapes):
        mask = raster(sh, SS, n)
        under = labels[mask]
        ids, counts = np.unique(under[under >= 0], return_counts=True)
        sh['parent'] = int(ids[np.argmax(counts)]) if len(ids) else -1
        sh['on_paper'] = float(np.mean(under == -1)) if under.size else 1.
        sh['area'] = mask.sum() / SS ** 2
        rows, cols = np.flatnonzero(mask.any(1)), np.flatnonzero(mask.any(0))
        if len(rows):  # typical width: crossings of thin lines must not count as "thick"
            crop = np.pad(mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1], 1)
            depth = ndimage.distance_transform_edt(crop)
            sh['thick'] = 2 * np.percentile(depth[crop], 90) / SS
        else:
            sh['thick'] = 0.
        sh['mask'] = mask
        if sh['fill'] and sh['alpha'] < 1:  # translucent overlay: pre-blend over what it covers
            under = color(shapes[sh['parent']]) if sh['parent'] >= 0 else PAPER
            sh['fill'], sh['alpha'] = blend(sh['fill'], under, sh['alpha']), 1.
        labels[mask] = i
    near_paper = ndimage.binary_dilation(labels == -1) & (labels >= 0)
    edges = np.bincount(labels[near_paper], minlength=len(shapes))
    for i, sh in enumerate(shapes):
        sh['visible'] = np.count_nonzero(labels == i) / SS ** 2
        sh['edge'] = edges[i] / SS                 # length of the final silhouette it owns
        sh['children'] = sum(1 for other in shapes if other['parent'] == i)


def tone_of(sh: dict, parent: dict) -> bool:
    """True when a shape is a lighter/darker tone of the shape it sits on (shading)."""
    a, b = lab(sh['fill']), lab(color(parent))
    delta = float(np.linalg.norm(a - b))
    hue_gap = abs((np.degrees(np.arctan2(a[2], a[1]) - np.arctan2(b[2], b[1])) + 180) % 360 - 180)
    same_hue = np.hypot(*a[1:]) > 15 and np.hypot(*b[1:]) > 15 and hue_gap < 25
    tint = same_hue and a[0] > b[0] and sh['visible'] < .1 * parent['visible']   # glint
    # thin, faint line work (grids, seams, folds) reads as texture, not as a part
    return delta < 12 or (same_hue and delta < 40) or tint or (sh['thick'] < 16 and delta < 25)


def outline(sh: dict, shapes: list[dict]) -> float:
    """Ink stroke width for a filled shape; 0 means no ink (data-noink)."""
    size, thick = sh['visible'], sh['thick']
    if size < 120 or thick < 6:
        return 0                                       # tiny detail / hairline
    parent = shapes[sh['parent']] if sh['parent'] >= 0 else None
    if parent is None or (sh['on_paper'] >= .1 and sh['edge'] >= 30):   # part of the silhouette
        return 6 if thick >= 20 and size >= 2000 else 4 if thick >= 12 and size >= 500 else 3
    if sh['children'] <= 1 and tone_of(sh, parent):
        return 0                                       # shading patch or tinted highlight
    if size < 400 or thick < 10:
        return 0                                       # small inner detail
    return 4 if thick >= 16 and size >= 1500 else 3


def band(sh: dict) -> np.ndarray:
    """Pixels covered by a shape's ink outline."""
    mask, reach = sh['mask'], int(sh['width'] * SS / 2) + 2
    rows, cols = np.flatnonzero(mask.any(1)), np.flatnonzero(mask.any(0))
    win = (slice(max(0, rows[0] - reach), rows[-1] + reach + 1),
           slice(max(0, cols[0] - reach), cols[-1] + reach + 1))
    edge = mask[win] ^ ndimage.binary_erosion(mask[win])
    out = np.zeros_like(mask)
    out[win] = ndimage.distance_transform_edt(~edge) <= sh['width'] * SS / 2
    return out


def rims(shapes: list[dict]) -> list[dict]:
    """Re-ink outlines that un-inked patches painted over (Fluent shading hugs the edges)."""
    after = {}
    for s, sh in enumerate(shapes):
        if not sh['width'] or sh['fill'] is None:
            continue
        ring, last = band(sh), None
        for n in range(s + 1, len(shapes)):
            other = shapes[n]
            hit = np.count_nonzero(other['mask'] & ring) / SS ** 2
            if hit <= 4:
                continue
            inside = np.count_nonzero(other['mask'] & sh['mask']) / np.count_nonzero(other['mask'])
            if other['width'] or inside < .9:
                break                                  # a part in front legitimately covers it
            if hit > 40:
                last = n                               # an un-inked patch on it thinned the edge
        if last is not None:
            after.setdefault(last, []).append(sh)
    out = []
    for i, sh in enumerate(shapes):
        out.append(sh)
        out.extend({**r, 'fill': None, 'line': None, 'noink': True, 'rim': True} for r in after.get(i, []))
    return out


def merge_micro(shapes: list[dict]) -> list[dict]:
    """Join runs of identical un-inked, non-overlapping shapes (same look, fewer elements)."""
    out = []
    for sh in shapes:
        prev = out[-1] if out else None
        if (prev and not prev['width'] and not sh['width'] and prev['fill'] == sh['fill']
                and prev['rule'] == sh['rule'] and not np.any(prev['mask'] & sh['mask'])):
            prev['path'] = prev['path'] + sh['path']
            prev['mask'] = prev['mask'] | sh['mask']
            continue
        out.append(dict(sh))
    return out


def convert(svg_file: Path) -> str:
    shapes = load(svg_file)
    analyse(shapes)
    if any(sh['visible'] < 1 for sh in shapes):   # drop shapes the original hides completely
        shapes = [sh for sh in shapes if sh['visible'] >= 1]
        analyse(shapes)
    for sh in shapes:
        if sh['fill']:
            sh['width'] = outline(sh, shapes)
            sh['noink'] = not sh['width']
        else:  # a stroked source line keeps its colour; thick bars get an ink edge beneath
            sh['width'], sh['noink'] = max(3., sh['src_width']), sh['src_width'] >= 16
    shapes = rims(shapes)
    if len(shapes) > MAX_SHAPES:
        shapes = merge_micro(shapes)
    elements = []
    for sh in shapes:
        if sh['fill'] is None and sh['noink'] and not sh.get('rim'):
            elements.append({**sh, 'line': INK, 'width': sh['width'] + 8, 'noink': False})
        elements.append(sh)
    if len(elements) > MAX_SHAPES:
        raise Skip(f'more than {MAX_SHAPES} shapes after simplification')
    body = []
    for sh in elements:
        attrs = [f'd="{path_d(sh["path"])}"']
        if sh['rule'] == 'evenodd' and sh['fill']:
            attrs.append('fill-rule="evenodd"')
        attrs.append(f'fill="{sh["fill"] or "none"}"')
        if sh['width']:
            attrs.append(f'stroke="{sh["line"] or INK}" stroke-width="{num(sh["width"])}" '
                         'stroke-linecap="round" stroke-linejoin="round"')
        if sh['noink']:
            attrs.append('data-noink="1"')
        body.append(f'  <path {" ".join(attrs)}/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" '
            f'width="{SIZE}" height="{SIZE}">\n' + '\n'.join(body) + '\n</svg>\n')


# ------------------------------------------------------------------ tags + notice
def snake(name: str) -> str:
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '_', ascii_name.lower()).strip('_')


def dedupe(words) -> list[str]:
    seen, out = set(), []
    for w in words:
        w = w.strip()
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def load_zh(src: Path) -> dict:
    table = {}
    for name, key in (('cldr_zh_annotations_derived.json', 'annotationsDerived'),
                      ('cldr_zh_annotations.json', 'annotations')):   # base file wins
        data = json.loads((src / name).read_text(encoding='utf-8'))[key]['annotations']
        table.update({k.replace(VS16, ''): v for k, v in data.items()})
    return table


def tags_for(meta: dict, zh: dict) -> dict:
    seq = ''.join(chr(int(h, 16)) for h in meta['unicode'].split())
    ann = zh.get(seq.replace(VS16, '')) or zh.get(meta['glyph'].replace(VS16, ''), {})
    name_words = [w for w in meta['cldr'].lower().split() if w not in STOPWORDS]
    en = dedupe([k.lower() for k in meta['keywords']] + name_words)
    return {'desc': meta['cldr'], 'category': meta['group'], 'en': en[:12],
            'zh': dedupe(ann.get('tts', []) + ann.get('default', []))[:8]}


def skip_reason(name: str, meta: dict) -> str | None:
    key = name.lower()
    if meta['group'] == 'Flags':
        return 'flag'
    if key in DENY:
        return 'denylist'
    if TEXT.search(key):
        return 'letters or digits in the art'
    return None


def write_notice(src: Path, commit: str, converted: int, skipped: list[tuple[str, str]]) -> None:
    cldr = json.loads((src / 'cldr_annotations_package.json').read_text(encoding='utf-8'))
    lines = [
        '# Fluent emoji doodles: source and licence', '',
        f'Converted from Microsoft Fluent Emoji "Flat" SVGs ({UPSTREAM}),',
        f'commit `{commit}`, MIT licence: see `LICENSE` (Copyright (c) Microsoft Corporation).', '',
        '## What was modified', '',
        'Regenerate with `python -m kinodraw.library.fluent SRC_DIR` (kinodraw/library/fluent.py):',
        '- Default skin tone only; files renamed `fl_<snake_case_name>.svg`.',
        '- Transforms baked into absolute path data; art re-fitted to a 320x320 box with 16 px padding;',
        '  rect/circle/ellipse converted to paths, arcs to cubic curves, coordinates rounded to 0.1 px.',
        '- Defs, gradients, clip paths, masks and filters dropped (emoji that rely on them are skipped);',
        '  `opacity` overlays pre-blended into a flat colour over the shape they cover; shapes the',
        '  original hides completely are dropped; stroked source lines keep their colour and width',
        '  (thick bars get an ink edge drawn beneath them).',
        f'- Ink outline added (`stroke="{INK}"`, round caps/joins): 6 px on big silhouette shapes,',
        '  3-4 px on inner parts; tiny details, highlights and shading patches get `data-noink="1"`',
        '  and no stroke; outline-only copies (`fill="none"`, `data-noink="1"`) re-ink silhouette',
        '  edges that shading patches paint over. Original flat colours are kept.', '',
        '## Tags (`../tags/fluent.json`)', '',
        '`desc`, `category` and `en` come from the Fluent metadata (MIT). `zh` comes from the',
        f'Unicode CLDR annotations (cldr-json {cldr["version"]}, CLDR {cldr["cldrVersion"]}),',
        'https://github.com/unicode-org/cldr-json, used under the Unicode License v3:', '',
        '```', (src / 'cldr_LICENSE.txt').read_text(encoding='utf-8').strip(), '```', '',
        f'## Not converted ({len(skipped)}; {converted} converted)', '',
        'The denylist is the requested list (weapons, drugs, injury, funeral, sexual innuendo)',
        'plus similar items: alcoholic drinks, headstone, briefs, biting lip, tongue, sweat',
        'droplets, love hotel. "Letters or digits" are emoji whose meaning is the text itself',
        '(STYLE.md: no text in doodles); objects that merely carry a label (medals, pool 8',
        'ball, hotel, red envelope) are kept.', '']
    for reason in sorted({r for _, r in skipped}):
        names = sorted(n for n, r in skipped if r == reason)
        lines.append(f'- **{reason}** ({len(names)}): ' + ', '.join(names))
    (OUT / 'NOTICE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1]).expanduser()
    repo = src / 'fluentui-emoji'
    commit = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], check=True,
                            capture_output=True, text=True, encoding='utf-8').stdout.strip()
    zh = load_zh(src)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('fl_*.svg'):
        old.unlink()
    tags, skipped = {}, []
    for meta_file in sorted((repo / 'assets').glob('*/metadata.json')):
        folder, meta = meta_file.parent, json.loads(meta_file.read_text(encoding='utf-8'))
        svg_file = next(folder.glob('Flat/*.svg'), None) or next(folder.glob('Default/Flat/*.svg'), None)
        try:
            reason = skip_reason(folder.name, meta) or ('no Flat SVG' if svg_file is None else None)
            if reason:
                raise Skip(reason)
            text = convert(svg_file)
        except Skip as why:
            skipped.append((folder.name, str(why)))
            continue
        ident = 'fl_' + snake(folder.name)
        (OUT / f'{ident}.svg').write_text(text, encoding='utf-8')
        tags[ident] = tags_for(meta, zh)
    TAGS.parent.mkdir(parents=True, exist_ok=True)
    TAGS.write_text(json.dumps(tags, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    shutil.copyfile(repo / 'LICENSE', OUT / 'LICENSE')
    write_notice(src, commit, len(tags), skipped)
    print(json.dumps({'converted': len(tags), 'skipped': len(skipped), 'out': str(OUT)}))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Import licence-clean open picture packs into the doodle library.

Usage: python -m kinodraw.library.packs PACK SRC_DIR

PACK is a key of PACKS. SRC_DIR is the pack as published, unpacked (downloads are data: nothing in it is
run or imported):
  tabler       the npm tarball's package/ folder (@tabler/icons): LICENSE, package.json, icons.json,
               icons/outline/*.svg
  healthicons  a checkout of github.com/resolvetosavelives/healthicons: LICENSE,
               public/icons/meta-data.json, public/icons/svg/outline/<category>/<id>.svg

The pack's own LICENSE file must name a licence in ALLOWED, or nothing is written (LicenceError).
Writes assets/doodles/<pack>/<prefix><name>.svg plus LICENSE, NOTICE.md and MANIFEST.json (the source
file and licence of every picture), assets/doodles/tags/<pack>.json, and the set counts at the top of
CATALOG.md. The output depends only on the sources.

Every picture is cleaned by genprops.sanitize_svg (inline geometry only: no scripts, styles, links or
external references), then flattened onto a 320x320 box with 16 px padding: transforms baked into
absolute path data, currentColor and every paint turned into the library's ink #1B1B1B. Line icons keep
round ink lines STROKE px wide; icons drawn as filled outlines keep their ink fills and are marked
data-inkfill="1", so the drawing hand traces them as lines (engine/ink.py) instead of popping them in.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import resvg_py
import svgelements as se
from PIL import Image

from kinodraw.library.check import LIBRARY
from kinodraw.library.fluent import dedupe, num, snake
from kinodraw.library.genprops import sanitize_svg

SIZE, PAD = 320, 16
STROKE = 11                  # ink line width of line icons (bespoke outlines are 6, Fluent silhouettes 6)
SOLID = .40                  # pictures with more of their box in ink than this read as a black blob
FAINT = .02                  # ... and with less than this read as an empty box (a dot, a dotted line)
INK = '#1B1B1B'
# SPDX ids a shipped picture may carry: no share-alike, no non-commercial, nothing unknown.
ALLOWED = {'MIT', 'ISC', 'Apache-2.0', 'CC0-1.0', 'CC-BY-4.0'}
MANIFEST = 'MANIFEST.json'


class LicenceError(Exception):
    """A pack or picture whose licence is not in ALLOWED."""


class Skip(Exception):
    """A picture that is not imported; the message is the reason recorded in NOTICE.md."""


def licence_of(text: str) -> str | None:
    """The SPDX id a LICENSE file grants, read from its wording; None when it is not recognised.
    Restrictive terms are checked first, so a share-alike or non-commercial licence never reads as allowed."""
    flat = ' '.join(text.split())
    low = flat.lower()
    if re.search(r'share-?alike|sharealike|by-sa\b', low):
        return 'CC-BY-SA-4.0' if '4.0' in low else 'CC-BY-SA'
    if re.search(r'noncommercial|non-commercial|by-nc\b', low):
        return 'CC-BY-NC'
    if re.search(r'noderivatives|no derivatives|by-nd\b', low):
        return 'CC-BY-ND'
    if 'gnu general public license' in low or 'gnu lesser general public' in low:
        return 'GPL'
    if 'permission is hereby granted, free of charge, to any person obtaining a copy' in low \
            and 'the software is provided "as is"' in low:
        return 'MIT'
    if 'permission to use, copy, modify, and/or distribute this software for any purpose' in low:
        return 'ISC'
    if 'apache license' in low and 'version 2.0' in low:
        return 'Apache-2.0'
    if 'cc0 1.0 universal' in low:
        return 'CC0-1.0'
    if 'attribution 4.0 international' in low:
        return 'CC-BY-4.0'
    return None


def require_allowed(spdx: str | None, where: str) -> str:
    if spdx not in ALLOWED:
        raise LicenceError(f'{where}: licence {spdx or "unknown"} is not one of {", ".join(sorted(ALLOWED))}')
    return spdx


def allowed_ids(manifest: dict) -> set:
    """Ids whose manifest row carries an allowed licence (the library lists nothing else)."""
    return {did for did, row in (manifest.get('files') or {}).items()
            if isinstance(row, list) and len(row) == 2 and row[1] in ALLOWED}


# ------------------------------------------------------------------ SVG normalisation
def path_d(path: se.Path) -> str:
    """Absolute path data, 0.1 px; arcs stay arcs (an icon's circles would be four curves each)."""
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
            large, sweep = int(abs(seg.sweep) > 3.14159266), int(seg.sweep > 0)
            out.append(f'A{num(seg.rx)},{num(seg.ry)} {num(seg.get_rotation().as_degrees)} {large},{sweep} {pt(seg.end)}')
    return ''.join(out)


def flatten(text: str, inkfill: bool) -> str:
    """One pack SVG, sanitised, as a flat 320x320 ink picture (see the module docstring)."""
    clean, _ = sanitize_svg(text)
    doc = se.SVG.parse(io.StringIO(clean), reify=True)
    shapes = []
    for el in doc.elements():
        if not isinstance(el, se.Shape):
            continue
        path = abs(se.Path(el))
        filled = el.fill is not None and el.fill.value is not None and el.fill.alpha > 0
        stroked = el.stroke is not None and el.stroke.value is not None and el.stroke.alpha > 0 \
            and float(el.stroke_width or 0) > 0
        if len(path) == 0 or path.bbox() is None or not (filled or stroked):
            continue
        shapes.append({'path': path, 'fill': filled, 'stroke': stroked,
                       'rule': el.values.get('fill-rule', 'nonzero')})
    if not shapes:
        raise Skip('no drawable shapes')
    boxes = [sh['path'].bbox() for sh in shapes]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    span = max(x1 - x0, y1 - y0)
    if span <= 0:
        raise Skip('drawing has no size')
    if doc.viewbox is not None and span < max(doc.viewbox.width, doc.viewbox.height) / 4:
        raise Skip('drawing too small to blow up')  # a lone dot would be stretched into a bar
    line = STROKE if any(sh['stroke'] for sh in shapes) else 0
    scale = (SIZE - 2 * PAD - line) / span
    fit = se.Matrix(scale, 0, 0, scale, (SIZE - (x1 - x0) * scale) / 2 - x0 * scale,
                    (SIZE - (y1 - y0) * scale) / 2 - y0 * scale)
    body = []
    for sh in shapes:
        attrs = [f'd="{path_d(abs(sh["path"] * fit))}"']
        if sh['fill'] and sh['rule'] == 'evenodd':
            attrs.append('fill-rule="evenodd"')
        attrs.append(f'fill="{INK if sh["fill"] else "none"}"')
        if sh['stroke']:
            attrs.append(f'stroke="{INK}" stroke-width="{num(line)}" stroke-linecap="round" stroke-linejoin="round"')
        elif inkfill:
            attrs.append('data-inkfill="1"')     # after fill=: engine/ink.py keeps this fill in the line layer
        body.append(f'  <path {" ".join(attrs)}/>')
    if len(body) > 70:
        raise Skip('more than 70 shapes')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" '
           f'width="{SIZE}" height="{SIZE}">\n' + '\n'.join(body) + '\n</svg>\n')
    png = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg, width=160, height=160))))
    cover = (np.asarray(png.getchannel('A')) > 128).mean()
    if cover > SOLID:
        raise Skip('mostly solid ink')
    if cover < FAINT:
        raise Skip('almost no ink')
    return svg


# ------------------------------------------------------------------ packs
def _words(name: str) -> str:
    """'building-skyscraper-2' -> 'building skyscraper' (variant numbers say nothing about the picture)."""
    return re.sub(r'(?:\s+\d+)+$', '', re.sub(r'[-_]+', ' ', name)).strip()


def _banned_words() -> set:
    data = json.loads((LIBRARY / 'banned.json').read_text(encoding='utf-8'))
    return set(data['words']['en'])


def _deny(text: str, words: set) -> bool:
    return bool(set(re.findall(r'[a-z]+', text.lower())) & words)


TABLER_DROP_CATEGORIES = {   # letters, digits or logos in the art, or care-label/astrology/badge glyphs
    'Brand', 'Letters', 'Numbers', 'Text', 'Extensions', 'Laundry', 'Zodiac', 'Badges', 'Math'}
TABLER_TEXT = re.compile(   # names whose art carries letters or digits
    r'^(?:file-type-|http-|signal-\dg|rating-|percentage-\d|time-duration-|rewind-|multiplier-|square-f\d'
    r'|exposure-|crop-\d|clock-(?:12|24)$|hours-|view-360-number|auth-2fa|error-404|hdr$|uhd$|api|ad(?:-|$)'
    r'|creative-commons|no-creative-commons|copyright|no-copyright|registered|trademark|list-letters|text-'
    r'|clipboard-typography|file-typography|play-card-\d|sum$|omega$|tex$|braille$|message-language|vip'
    r'|.*-ai$|.*-sql$|sql|json|regex|world-www|a-b$|ab(?:c|-)|tallymark|georgian-lari|currency-(?!dollar$|euro$'
    r'|pound$|yen$|bitcoin$|rupee$|yuan$|won$)|coin-monero$|taiwan-dollar$'
    r'|(?:map|navigation)-(?:north|east|south|west)$|temperature-(?:celsius|fahrenheit)$|xbox-|parking'
    r'|ce$|servicemark$|typeface$|file-word$|ai$|alt$|sdk$|seo$|sos$|uv-index$|ux-circle$|vs$|xd$|zzz$'
    r'|helicopter-landing$|hospital-circle$|no-derivatives$|automatic-gearbox$|bell-z$|binary$|(?:brightness|focus)-auto$'
    r'|car-fan-|circuit-(?:ammeter|motor|voltmeter)$|device-sim-\d$|explicit$|favicon$|file-(?:cv|digit|function|lambda)$'
    r'|gpu-2$|laurel-wreath-\d$|meter-(?:cube|square)$|play-card-[ajkq]$|prescription$|relation-|confucius$'
    r'|signal-(?:e|g|h|h-plus|lte)$)')
TABLER_DENY = {  # requested denylist themes (weapons, drugs, alcohol, death, religion) and trademarks
    'bomb', 'sword', 'swords', 'tank', 'beer', 'glass-champagne', 'glass-cocktail', 'glass-gin', 'glass-full',
    'cannabis', 'pill', 'pills', 'vaccine', 'vaccine-bottle', 'smoking', 'smoking-no', 'coffin', 'grave', 'grave-2',
    'skull', 'building-church', 'building-mosque', 'mosque', 'cross', 'fish-christianity', 'menorah', 'om',
    'pray', 'torii', 'yin-yang', 'jewish-star', 'michelin-star', 'michelin-star-green', 'michelin-bib-gourmand',
    'device-airpods', 'device-airpods-case', 'device-airtag', 'device-vision-pro', 'device-nintendo',
    'poo', 'massage', 'ankh', 'bong', 'xxx', 'mickey', 'nfc', 'usb', 'bluetooth', 'bluetooth-connected',
    'bluetooth-x', 'earphone-bluetooth', 'playstation-circle', 'playstation-square', 'playstation-triangle',
    'playstation-x', 'airpods-l', 'airpods-r', 'device-vision-pro-wifi', 'olympics', 'pacman', 'pokeball', 'lego',
    'pentagram', 'glass', 'hand-middle-finger', 'hand-ring-finger'}

HEALTH_DROP_CATEGORIES = {   # letters/digits (typography, blood types), sexual health, pills, test-strip readouts,
    'typography', 'contraceptives', 'blood', 'medications', 'diagnostics', 'specialties'}  # solid signage tiles
HEALTH_DENY = {  # sexual anatomy and health, drugs, alcohol, death, religion, weapons, letters or logos in the art
    'anus', 'breasts', 'female-reproductive_system', 'penis', 'penis-alt', 'prostate', 'testicles', 'vagina',
    'vagina-alt', 'blood-drop', 'cervical-cancer', 'prostate-cancer', 'chlamydia', 'chlamydia-alt', 'gonorrhea',
    'gonorrhea-alt', 'hpv', 'sti', 'syphilis-alt', 'hiv-ind', 'hiv-neg', 'hiv-pos', 'vih', 'hiv-self_test',
    'syringe', 'syringe-vaccine', 'virus-lab_research_syringe', 'tongue', 'alcohol', 'alcohol-cessation',
    'female-sex_worker', 'male-sex_worker', 'msm', 'pwid', 'fetus', 'church', 'mosque', 'temple', 'temple-alt',
    'chaplaincy', 'gynecology', 'urology', 'cannabis', 'smoking', 'smoking-cessation', 'smoking-cessation_alt',
    'death', 'death-alt', 'death-alt2', 'poison', 'sexual-reproductive_health', 'war', 'chart-death-rate-decreasing',
    'chart-death-rate-increasing', 'chart-death-rate-stable', 'FHIR-logo', 'HL7v2-logo', 'dhis2-logo',
    'excel-logo', 'openMRS-logo', 'simple-logo', 'icd', 'icd-10', 'icd-11', 'icd-9', 'loinc', 'imm', 'rx', '2g',
    '3g', 'network-4g', 'network-5g', 'provider-fst', 'tb', 'tac', 'ancv', 'rmnh', 'clinical-a', 'clinical-f',
    'clinical-fe', 'qr-code', 'yes', 'no', 'cpr', 'expectorate', 'vomiting', 'vomitting', 'diarrhea',
    'skull', 'body-mass_index', 'hospital-symbol', 'i-exam_qualification', 'information-campaign', 'oxygen-tank',
    'pregnant-0812w', 'pregnant-2426w', 'pregnant-32w', 'pregnant-3638w', 'prescription-document', 'pulse-oximeter_alt'}


def _tabler(src: Path):
    meta = json.loads((src / 'icons.json').read_text(encoding='utf-8'))
    version = json.loads((src / 'package.json').read_text(encoding='utf-8'))['version']
    banned = _banned_words()
    items, skipped = [], []
    for name, info in sorted(meta.items()):
        category = info.get('category') or ''
        file = src / 'icons' / 'outline' / f'{name}.svg'
        if 'outline' not in (info.get('styles') or {}) or not file.exists():
            reason = 'no outline SVG'
        elif category in TABLER_DROP_CATEGORIES:
            reason = f'category {category}'
        elif name.endswith('-off'):
            reason = 'crossed-out variant'
        elif TABLER_TEXT.match(name):
            reason = 'letters or digits in the art'
        elif name in TABLER_DENY or _deny(name, banned):
            reason = 'denylist'
        else:
            reason = None
        if reason:
            skipped.append((name, reason))
            continue
        words = _words(name)
        tags = [_words(str(t)) for t in info.get('tags') or []]
        en = [w for w in dedupe([words] + tags) if w and not _deny(w, banned)][:8]
        items.append({'id': 'tb_' + snake(name), 'file': file, 'source': f'icons/outline/{name}.svg',
                      'tags': {'desc': words, 'category': category or 'Tabler', 'en': en, 'zh': []}})
    return version, items, skipped


def _healthicons(src: Path):
    commit = subprocess.run(['git', '-C', str(src), 'rev-parse', 'HEAD'], check=True, capture_output=True,
                            text=True, encoding='utf-8').stdout.strip()
    meta = json.loads((src / 'public' / 'icons' / 'meta-data.json').read_text(encoding='utf-8'))
    banned = _banned_words()
    items, skipped = [], []
    shared = {n for n in (e['id'] for e in meta) if sum(e['id'] == n for e in meta) > 1}
    for info in sorted(meta, key=lambda e: e['path']):
        name, category = info['id'], info['category']
        rel = f'public/icons/svg/outline/{info["path"]}.svg'
        file = src / rel
        title = info.get('title') or _words(name)
        if not file.exists():
            reason = 'no outline SVG'
        elif category in HEALTH_DROP_CATEGORIES:
            reason = f'category {category}'
        elif name in HEALTH_DENY or _deny(f'{name} {title}', banned):
            reason = 'denylist'
        else:
            reason = None
        if reason:
            skipped.append((name, reason))
            continue
        tags = [t.lower() for t in info.get('tags') or [] if ':' not in t]
        en = [w for w in dedupe([title.lower()] + tags) if not _deny(w, banned)][:8]
        ident = 'hi_' + snake(name) + (f'_{snake(category)}' if name in shared else '')  # same id in two categories
        items.append({'id': ident, 'file': file, 'source': rel,
                      'tags': {'desc': title, 'category': category, 'en': en, 'zh': []}})
    return commit, items, skipped


PACKS = {
    'tabler': {
        'title': 'Tabler Icons', 'home': 'https://tabler.io/icons', 'prefix': 'tb_', 'inkfill': False,
        'source': 'https://registry.npmjs.org/@tabler/icons/-/icons-{version}.tgz', 'read': _tabler,
        'style': 'outline style; line icons drawn with round ink lines'},
    'healthicons': {
        'title': 'Health Icons', 'home': 'https://healthicons.org', 'prefix': 'hi_', 'inkfill': True,
        'source': 'https://github.com/resolvetosavelives/healthicons (commit {version})', 'read': _healthicons,
        'style': 'outline style; icons drawn as filled ink outlines (data-inkfill)'},
}


# ------------------------------------------------------------------ writing
def write_pack(pack: str, src: Path, root: Path = LIBRARY) -> dict:
    spec = PACKS[pack]
    licence_text = (src / 'LICENSE').read_text(encoding='utf-8')
    spdx = require_allowed(licence_of(licence_text), f'{pack} LICENSE')   # before anything is written
    version, items, skipped = spec['read'](src)
    out = root / pack
    converted, tags, files = [], {}, {}
    for item in items:
        try:
            text = flatten(item['file'].read_text(encoding='utf-8'), spec['inkfill'])
        except (Skip, ValueError) as why:
            skipped.append((item['source'], str(why)))
            continue
        converted.append((item['id'], text))
        tags[item['id']] = item['tags']
        files[item['id']] = [item['source'], spdx]
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob(f'{spec["prefix"]}*.svg'):
        old.unlink()
    for did, text in converted:
        (out / f'{did}.svg').write_text(text, encoding='utf-8')
    (out / 'LICENSE').write_text(licence_text, encoding='utf-8')
    source = spec['source'].format(version=version)
    manifest = {'pack': pack, 'title': spec['title'], 'home': spec['home'], 'version': version,
                'source': source, 'licence': spdx, 'licence_file': 'LICENSE', 'files': files}
    rows = ',\n'.join(f'  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}' for k, v in sorted(files.items()))
    head = json.dumps({k: v for k, v in manifest.items() if k != 'files'}, ensure_ascii=False, indent=1)[:-2]
    (out / MANIFEST).write_text(head + ',\n "files": {\n' + rows + '\n }\n}\n', encoding='utf-8')
    (root / 'tags').mkdir(parents=True, exist_ok=True)
    (root / 'tags' / f'{pack}.json').write_text(
        json.dumps(tags, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    _notice(pack, spec, version, source, spdx, len(converted), skipped, out)
    if root == LIBRARY:
        catalog_header()
    return {'pack': pack, 'version': version, 'licence': spdx, 'imported': len(converted), 'skipped': len(skipped)}


def _notice(pack, spec, version, source, spdx, count, skipped, out):
    lines = [
        f'# {spec["title"]}: source and licence', '',
        f'Imported from {spec["title"]} ({spec["home"]}), {spec["style"]}.',
        f'Source: {source}. Licence: {spdx}, see `LICENSE` (the pack\'s own file).',
        f'`{MANIFEST}` lists the source file and licence of every picture.', '',
        '## What was modified', '',
        f'Regenerate with `python -m kinodraw.library.packs {pack} SRC_DIR` (kinodraw/library/packs.py):',
        f'- Files renamed `{spec["prefix"]}<snake_case_name>.svg`; cleaned by the library\'s SVG sanitiser',
        '  (inline geometry only); transforms baked into absolute path data; art re-fitted to a 320x320 box',
        '  with 16 px padding; shapes converted to paths (arcs stay arcs), coordinates rounded to 0.1 px.',
        f'- Every paint (including currentColor) set to the library ink {INK}; '
        + (f'lines redrawn {STROKE} px wide with round caps and joins.' if not spec['inkfill'] else
           'filled outlines marked `data-inkfill="1"` so the drawing hand traces them.'),
        '- Tags (`../tags/' + pack + '.json`): `desc` from the icon name, `en` from its name and the pack\'s',
        '  own keywords, `category` from the pack. No Chinese keywords: these pictures are found in English',
        '  and Spanish only.', '',
        f'## Not imported ({len(skipped)}; {count} imported)', '',
        'Left out: letters or digits in the art (STYLE.md: no text in doodles), logos and trademarks, and the',
        'library\'s denylist themes (weapons, drugs, alcohol, death, religious imagery, sexual health).', '']
    for reason in sorted({r for _, r in skipped}):
        names = sorted(n for n, r in skipped if r == reason)
        lines.append(f'- **{reason}** ({len(names)})' + (': company and product logos' if reason == 'category Brand'
                                                          else ': ' + ', '.join(names)))
    (out / 'NOTICE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def catalog_header(root: Path = LIBRARY) -> None:
    """Rewrite the set counts at the top of CATALOG.md from tags/*.json and the pack manifests."""
    from kinodraw import library
    library.catalog.cache_clear()
    counts: dict = {}
    for entry in library.catalog().values():
        counts[entry['set']] = counts.get(entry['set'], 0) + 1
    bullets = [f'- {counts.get("bespoke", 0)} bespoke doodles (`bespoke/`, CC BY 4.0, original to this project)',
               f'- {counts.get("fluent", 0)} Microsoft Fluent Emoji in the same outlined style (`fluent/`, ids start '
               'with `fl_`, MIT; see `fluent/NOTICE.md`)']
    for pack, spec in PACKS.items():
        manifest = root / pack / MANIFEST
        if counts.get(pack) and manifest.exists():
            licence = json.loads(manifest.read_text(encoding='utf-8'))['licence']
            bullets.append(f'- {counts[pack]} {spec["title"]} ink line pictures (`{pack}/`, ids start with '
                           f'`{spec["prefix"]}`, {licence}; see `{pack}/NOTICE.md`)')
    bullets.append(f'- {sum(counts.values())} pictures in all')
    path = root / 'CATALOG.md'
    text = path.read_text(encoding='utf-8')
    head, _, rest = text.partition('\n\nSearch from the command line')
    intro = head.split('\n\n- ')[0]
    path.write_text(intro + '\n\n' + '\n'.join(bullets) + '\n\nSearch from the command line' + rest, encoding='utf-8')


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in PACKS:
        sys.exit(__doc__)
    try:
        print(json.dumps(write_pack(sys.argv[1], Path(sys.argv[2]).expanduser())))
    except LicenceError as error:
        sys.exit(f'refused: {error}')


if __name__ == '__main__':
    main()

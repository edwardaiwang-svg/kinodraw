"""Bounded, injected SVG authoring; no provider calls unless explicitly enabled."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as XML

import svgelements
from defusedxml import ElementTree as ET

NS = '{http://www.w3.org/2000/svg}'
SHAPES = {'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'}
ATTRS = {'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'fill-rule',
         'transform', 'd', 'x', 'y', 'width', 'height', 'rx', 'ry', 'cx', 'cy', 'r',
         'points', 'x1', 'y1', 'x2', 'y2', 'id', 'viewBox', 'data-noink'}
MAX_BYTES = 100_000
VERSION = 1


@dataclass
class GeneratedProp:
    svg: str
    provenance: dict
    path: Path | None = None


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _color(value):
    value = value.strip().lower()
    value = {'black': '#000000', 'white': '#ffffff'}.get(value, value)
    if re.fullmatch(r'#[0-9a-f]{3}', value):
        value = '#' + ''.join(c * 2 for c in value[1:])
    if value != 'none' and not re.fullmatch(r'#[0-9a-f]{6}', value):
        raise ValueError('colours must be hex, black, white or none')
    return value


def sanitize_svg(text: str) -> tuple[str, list[str]]:
    """Keep only inert doodle geometry and inline attributes; reject resource bombs."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('SVG exceeds 100000 bytes or is not text')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I):
        raise ValueError('DTD and entity declarations are forbidden')
    try:
        root = ET.fromstring(text, forbid_dtd=True)
    except Exception as error:
        raise ValueError('invalid or unsafe XML') from error
    if root.tag not in ('svg', NS + 'svg'):
        raise ValueError('root must be SVG')
    nodes, shapes = 0, 0
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        shapes += node.tag in SHAPES or node.tag in {NS + s for s in SHAPES}
        if nodes > 100 or shapes > 40 or depth > 16:
            raise ValueError('SVG exceeds node, shape (40), or nesting limits')
        stack.extend((child, depth + 1) for child in node)
    actions = []

    def clean(node, is_root=False):
        tag = node.tag.removeprefix(NS)
        node.tag = NS + tag
        for key, value in list(node.attrib.items()):
            if (key not in ATTRS or (key == 'viewBox' and not is_root)
                    or re.search(r'url\s*\(|(?:data|https?|file)\s*:', value, re.I)):
                del node.attrib[key]
                actions.append(f'removed {tag} attribute {key}')
        if node.text and node.text.strip():
            actions.append(f'removed {tag} text')
        node.text = node.tail = None
        for child in list(node):
            child_tag = child.tag.removeprefix(NS)
            if child_tag not in SHAPES | {'g'}:
                node.remove(child)
                actions.append(f'removed element {child_tag}')
            else:
                clean(child)

    clean(root, True)
    XML.register_namespace('', NS[1:-1])
    return XML.tostring(root, encoding='unicode'), actions


def _style_check(svg, palette):
    root = ET.fromstring(svg)
    if re.split(r'[ ,]+', root.get('viewBox', '').strip()) != ['0', '0', '512', '512']:
        raise ValueError('viewBox must be 0 0 512 512')
    for key in ('width', 'height'):
        if key in root.attrib and root.get(key) != '512':
            raise ValueError('width and height must be 512')
    root.set('width', '512')
    root.set('height', '512')
    allowed = set(palette) | {'#000000', '#ffffff', '#1b1b1b', 'none'}
    count, strokes = 0, 0

    def walk(node, parent):
        nonlocal count, strokes
        attrs = {**parent, **node.attrib}
        tag = node.tag.removeprefix(NS)
        for key in ('fill', 'stroke'):
            if key in node.attrib:
                node.set(key, _color(node.get(key)))
                attrs[key] = node.get(key)
                if attrs[key] not in allowed:
                    raise ValueError(f'{key} colour outside palette')
        if tag in SHAPES:
            count += 1
            fill, stroke = attrs.get('fill', '#000000'), attrs.get('stroke', 'none')
            if fill not in allowed or stroke not in allowed:
                raise ValueError('colour outside palette')
            if stroke != 'none':
                if stroke not in {'#000000', '#1b1b1b'}:
                    raise ValueError('outlines must use black ink')
                if float(attrs.get('stroke-width', '1')) not in (4, 6):
                    raise ValueError('outline widths must be 4 or 6')
                if any(attrs.get(k) != 'round' for k in ('stroke-linecap', 'stroke-linejoin')):
                    raise ValueError('outline caps and joins must be round')
                if node.get('data-noink') != '1':
                    strokes += 1
            elif fill != 'none' and node.get('data-noink') != '1':
                raise ValueError('filled shapes need ink outlines')
            if fill == stroke == 'none':
                raise ValueError('invisible shape')
        for child in node:
            walk(child, attrs)

    walk(root, {})
    if not 5 <= count <= 40 or strokes < 3:
        raise ValueError('need 5–40 shapes and at least three drawable ink strokes')
    svg = XML.tostring(root, encoding='unicode')
    try:
        doc = svgelements.SVG.parse(io.StringIO(svg), reify=True, on_error='raise')
        boxes, length, real_strokes = [], 0., 0
        for shape in doc.elements():
            if not isinstance(shape, svgelements.Shape):
                continue
            path = svgelements.Path(shape)
            box = path.bbox()
            if not box or not all(math.isfinite(v) for v in box):
                raise ValueError('empty or nonfinite shape geometry')
            boxes.append(box)
            if shape.stroke is not None and shape.stroke.value is not None and shape.values.get('data-noink') != '1':
                distance = path.length(error=1e-3, min_depth=2)
                if math.isfinite(distance) and distance > 0:
                    length += distance
                    real_strokes += 1
        if len(boxes) != count or real_strokes < 3 or length < 512:
            raise ValueError('not enough traceable outline geometry')
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        ratio = (x1 - x0) * (y1 - y0) / 512 ** 2
        if not .4 <= ratio <= .95 or min(x0, y0) < 12 or max(x1, y1) > 500:
            raise ValueError('bbox must fill 40–95% of viewBox with 12 px padding')
    except Exception as error:
        raise ValueError(f'geometry: {error}') from error
    return svg


def _prompt(description, palette, style):
    return (f'Draw ONE original prop: {description}\nStyle direction: {style}\n'
            'Produce SVG XML, no markdown; if the transport requires JSON, put this XML in its svg string. '
            'Start with <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
            'width="512" height="512" stroke="#1B1B1B" stroke-width="6" '
            'stroke-linecap="round" stroke-linejoin="round"> so every shape inherits the ink contract. '
            'Use 5–40 path/shape elements (path rect circle ellipse line polyline polygon) and optional g. '
            'Bold friendly flat cartoon, big silhouette first, interiors next, details last. '
            'BBox fills 40–95% of viewBox with at least 12 px padding; no detail smaller than 6 px. '
            f'Only these colours: {", ".join(palette)} plus black #000000, ink #1B1B1B and white #FFFFFF; '
            'none is allowed. Every filled shape has a black ink outline except accents with data-noink="1". '
            'At least three ink strokes, total outline length at least 512 px. stroke-width="6" for main '
            'shapes or "4" for details, stroke-linecap="round", stroke-linejoin="round", '
            'including closed rectangles, circles and paths. Never use coloured or white strokes. '
            'Inline attributes only; no text, images, external references, CSS, opacity, defs, use, '
            'gradients, filters, masks, animation, scripts, entities or logos. One darker shading tone at most. '
            'Check every shape against all ink, palette and geometry rules before returning it.')


def _read(path):
    with path.open('r', encoding='utf-8') as stream:
        text = stream.read(MAX_BYTES + 1)
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('cache file too large')
    return text


def _write(path, text):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def request_prop(description, palette, style, llm, *, project=None) -> GeneratedProp | None:
    """Generate with one repair, optionally cache in project/doodles by description hash.

    ``llm(prompt) -> SVG text`` may expose ``llm.model`` for provenance. Without a
    project this returns validated in-memory art. Provider routing belongs to the caller.
    """
    palette = sorted({_color(c) for c in palette})
    prompt = _prompt(description, palette, style)
    context_hash = _hash(prompt + f'\nvalidator={VERSION}')
    target = Path(project) / 'doodles' / f'gen-{_hash(description)}.svg' if project is not None else None
    if target is not None:
        if target.parent.is_symlink() or target.is_symlink() or target.with_suffix('.json').is_symlink():
            return None
        try:
            svg, info = _read(target), json.loads(_read(target.with_suffix('.json')))
            clean, actions = sanitize_svg(svg)
            checked = _style_check(clean, palette)
            if (info['context_hash'] == context_hash and info['svg_hash'] == _hash(svg)
                    and not actions and checked == svg and all(k in info for k in
                    ('model', 'prompt_hash', 'timestamp', 'repairs', 'sanitizer_actions'))):
                return GeneratedProp(svg, info, target)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    failures, actions, hashes = [], [], []
    for repairs in range(2):
        hashes.append(_hash(prompt))
        try:
            svg, stripped = sanitize_svg(llm(prompt))
            actions.extend(stripped)
            svg = _style_check(svg, palette)
        except Exception as error:
            from ..director.llm.providers import ProviderError, StructuredResponseError
            if isinstance(error, ProviderError) and not (
                    isinstance(error, StructuredResponseError) or getattr(error, 'transient', False)):
                return None
            failure = str(error)[:500]
            failures.append(failure)
            prompt = (_prompt(description, palette, style) + f'\nFailure: {failure}\n'
                      'Repair once; recheck the entire contract, not only this first reported error; '
                      'return corrected SVG.')
            continue
        info = {'model': str(getattr(llm, 'model', 'unknown (injected callable)')),
                'prompt_hash': hashes[0], 'prompt_hashes': hashes, 'context_hash': context_hash,
                'svg_hash': _hash(svg), 'timestamp': datetime.now(timezone.utc).isoformat(),
                'repairs': repairs, 'failures': failures, 'sanitizer_actions': actions}
        if target is not None:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                _write(target, svg)
                _write(target.with_suffix('.json'), json.dumps(info, indent=2))
            except OSError:
                return None
        return GeneratedProp(svg, info, target)
    return None


def maybe_request_prop(candidates, description, palette, style, llm, *, project,
                       enabled=False, threshold=.5) -> GeneratedProp | None:
    """Director hook: call after meaning gates, before the normal library fallback.

    Candidates expose ``.score`` (director.match.Hit). Use ``prop.path.stem`` as
    the doodle id; library.resolve(id, project) already searches project/doodles.
    The hybrid caller must explicitly enable this hook and inject its provider.
    """
    if not enabled or max((candidate.score for candidate in candidates), default=-math.inf) >= threshold:
        return None
    return request_prop(description, palette, style, llm, project=project)

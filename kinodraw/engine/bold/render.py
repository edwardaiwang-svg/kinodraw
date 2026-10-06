"""Pure-time cached sprites, with emissive glow and a separate, always sharp text layer."""
from __future__ import annotations

import io
import math
import re
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from html import escape
from xml.etree import ElementTree as ET

import numpy as np
import resvg_py
from defusedxml.ElementTree import fromstring
from PIL import Image, ImageColor, ImageFont
from scipy import fft
from scipy.signal import fftconvolve

from ... import library
from .. import ink, motion as m
from .charts import chart_svg, counter_text
from .model import PANEL_ENTER, PARTICLE_STAGGER, TEXT_ENTER, TYPE_CPS

W, H, FPS = 1920, 1080, 30
BLUR_SPEED = 600                    # reference-stage pixels/second
GLOW_HALF = 100                     # radial half-intensity distance at 1080p
TYPE_FONTS = {'rounded': ('Arimo', 'Arimo-Bold.ttf'),
              'hand': ('Playpen Sans', 'PlaypenSans-Bold.ttf'),
              'serif': ('Cinzel', 'Cinzel-Bold.ttf'),
              'mono': ('Silkscreen', 'Silkscreen-Regular.ttf'),
              'display': ('Cinzel', 'Cinzel-Bold.ttf')}
CAPTION_SIZE = 28                   # Arimo's capitals are 19 px high; allow for ambient scaling


def layout_position(scene, element, i):
    n = max(1, len(scene.elements))
    x, y = .5, .5
    if scene.composition == 'left_third':
        x = 1 / 3
    elif scene.composition == 'right_third':
        x = 2 / 3
    elif scene.composition == 'split':
        x = .28 if i % 2 == 0 else .72
    elif scene.composition == 'grid':
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        x, y = (i % cols + .5) / cols, (i // cols + .5) / rows
    return (element.x if element.x is not None else x) * W, (element.y if element.y is not None else y) * H


@lru_cache(maxsize=32)
def _camera_track(camera, end):
    finish = {'static': (W / 2, H / 2, 1.), 'slow_push': (W / 2, H / 2, 1.045),
              'pull_back': (W / 2, H / 2, .96), 'pan': (W / 2 + 65, H / 2, 1.)}[camera if camera != 'shake' else 'static']
    return m.Camera2D([(0, W / 2, H / 2, 1.), (end, *finish)], size=(W, H))


def _camera(scene, t):
    x, y, z = _camera_track(scene.camera, scene.duration).at(t)
    if scene.camera == 'shake':
        strength = 2 * scene.energy * math.exp(-max(0., t) * 4)
        x += strength * math.sin(t * 39)
        y += strength * math.sin(t * 31)
    return x, y, z


def element_pose(scene, element, i, t):
    """Position, scale and opacity, shared by artwork, labels and blur-speed measurement."""
    x, y = layout_position(scene, element, i)
    local = t - element.start
    enter = m.expo_out(local / element.entrance)
    scale = .9 + .1 * enter if element.kind != 'text' else 1.
    if element.kind == 'text':
        y += 18 * (1 - enter)
    else:
        y += 44 * (1 - enter)
    x += m.speed_kick(local, element.kick) - element.kick / .3
    phase = i * 1.71
    floor = scene.motion_floor
    corner = element.kind == 'text' and element.preset == 'corner_caption'
    drift = .7 if corner else scene.foreground_drift
    x += floor * drift * math.sin(t * 1.13 + phase)
    y += floor * drift * .7 * (math.cos(t * 1.13 + phase) if scene.continuous_drift
                               else math.sin(t * 1.67 + phase * .8))
    scale *= 1 + floor * (.003 if corner else .015) * math.sin(t * 1.91 + phase)
    alpha = enter * (1 - floor * .035 * (1 + math.sin(t * 2.3 + phase)))
    if element.end is not None:
        alpha *= m.clamp01((element.end - t) / .4)
    if local < 0:
        alpha = 0.
    if not corner:
        cx, cy, zoom = _camera(scene, t)
        x, y = W / 2 + (x - cx) * zoom, H / 2 + (y - cy) * zoom
        scale *= zoom
    return x, y, scale, alpha


def _group(body, pose):
    x, y, scale, alpha = pose
    return f'<g transform="translate({x:.6f} {y:.6f}) scale({scale:.6f})" opacity="{alpha:.6f}">{body}</g>'


@lru_cache(maxsize=128)
def _picture(svg_id, raw, width, height, color, cover=False, prefix='picture_', preserve_palette=False):
    if raw is None:
        path = library.resolve(svg_id)
        if path is None or path.suffix != '.svg':
            raise ValueError(f'Unknown library SVG: {svg_id}')
        raw = path.read_text(encoding='utf-8')
    root = fromstring(raw)
    if root.tag.rsplit('}', 1)[-1] != 'svg':
        raise ValueError('A picture must be an SVG document')
    if 'viewBox' not in root.attrib:
        source_w = root.get('width', str(width)).removesuffix('px')
        source_h = root.get('height', str(height)).removesuffix('px')
        root.set('viewBox', f'0 0 {float(source_w)} {float(source_h)}')
    for node in root.iter():
        tag = node.tag.rsplit('}', 1)[-1]
        if tag in {'script', 'foreignObject', 'image', 'style', 'animate', 'animateTransform', 'set'}:
            raise ValueError(f'Unsupported SVG element: {tag}')
        for key, value in list(node.attrib.items()):
            name = key.rsplit('}', 1)[-1]
            if name.startswith('on') or (name == 'href' and not value.startswith('#')):
                raise ValueError('SVG pictures cannot contain external resources or event handlers')
            if 'url(' in value and not value.startswith('url(#'):
                raise ValueError('SVG pictures cannot contain external resources')
            if not preserve_palette and name in {'fill', 'stroke', 'stop-color'} and value not in {'none', 'transparent'} and not value.startswith('url('):
                node.set(key, color)
            if name == 'style':
                for declaration in value.split(';'):
                    prop, _, val = declaration.partition(':')
                    prop, val = prop.strip(), val.strip()
                    if prop in {'fill', 'stroke', 'stop-color'}:
                        node.set(prop, val if preserve_palette or val in {'none', 'transparent'} or val.startswith('url(#') else color)
                    elif prop in {'opacity', 'fill-opacity', 'stroke-opacity', 'stroke-width', 'stroke-linecap',
                                  'stroke-linejoin', 'stroke-dasharray', 'stroke-dashoffset', 'fill-rule', 'clip-rule',
                                  'clip-path', 'mask', 'display', 'visibility', 'font-size', 'font-weight',
                                  'font-family', 'text-anchor', 'letter-spacing'}:
                        node.set(prop, val)
                del node.attrib[key]
    ids = {node.get('id'): prefix + node.get('id') for node in root.iter() if node.get('id')}
    for node in root.iter():
        for key, value in list(node.attrib.items()):
            name = key.rsplit('}', 1)[-1]
            if name == 'id':
                node.set(key, ids[value])
            elif name == 'href':
                node.set(key, '#' + ids.get(value[1:], value[1:]))
            else:
                node.set(key, re.sub(r'url\(#([^)]*)\)', lambda match: f'url(#{ids.get(match[1], match[1])})', value))
    root.set('x', str(-width / 2))
    root.set('y', str(-height / 2))
    root.set('width', str(width))
    root.set('height', str(height))
    if not preserve_palette:
        root.set('fill', color)
    if cover:
        root.set('preserveAspectRatio', 'xMidYMid slice')
    text_root = deepcopy(root)

    def separate(node, text_only):
        for child in list(node):
            tag = child.tag.rsplit('}', 1)[-1]
            if tag == 'defs':
                continue
            if tag == 'text':
                if not text_only:
                    node.remove(child)
            else:
                separate(child, text_only)
                if text_only and not list(child):
                    node.remove(child)

    has_text = any(node.tag.rsplit('}', 1)[-1] == 'text' for node in root.iter())
    separate(root, False)
    separate(text_root, True)
    return ET.tostring(root, encoding='unicode'), ET.tostring(text_root, encoding='unicode') if has_text else ''


def shape_points(element):
    return _shape_points(element.kind, element.size, element.width)


@lru_cache(maxsize=128)
def _shape_points(kind, size, width):
    a = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    if kind == 'line':
        return np.column_stack((np.linspace(-width / 2, width / 2, 64), np.zeros(64)))
    r = size / 2
    return np.column_stack((np.cos(a) * r, np.sin(a) * r))


def _shape(element, color, geometry=None):
    points, fill, stroke = geometry if geometry is not None else (shape_points(element), float(element.kind == 'dot'), float(element.kind != 'dot'))
    path = ' '.join(f'{"M" if i == 0 else "L"}{x:.5f} {y:.5f}' for i, (x, y) in enumerate(points))
    if element.kind != 'line' or geometry is not None:
        path += ' Z'
    return (f'<path d="{path}" fill="{color}" fill-opacity="{fill:.6f}" stroke="{color}" '
            f'stroke-opacity="{stroke:.6f}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')


@lru_cache(maxsize=64)
def _particles(seed, count, width, height):
    rng = m.seeded(seed, 'bold particles', count)
    src = rng.uniform((-width, -height), (width, height), (count, 2))
    angles = np.linspace(0, 2 * math.pi, count, endpoint=False)
    dst = np.column_stack((np.cos(angles) * width / 2, np.sin(angles) * height / 2))
    return src, dst


def _text_tag(text, size, color, x=0, y=0, spacing=0, anchor='middle'):
    return (f'<text x="{x:.6f}" y="{y:.6f}" font-size="{size:.6f}" fill="{color}" text-anchor="{anchor}" '
            f'dominant-baseline="central" letter-spacing="{spacing}">{escape(text)}</text>')


def _advance(font, text, family):
    return len(text) * font.getlength('M') if family == 'mono' else font.getlength(text)


@lru_cache(maxsize=256)
def _text_metrics(text, requested_size, width, corner, family='rounded'):
    size = max(CAPTION_SIZE, requested_size) if corner else requested_size
    font = ink.font('zh_caption' if re.search(r'[㐀-䶿一-鿿豈-﫿]', text) else 'en_caption', max(1, round(size)))
    if family != 'rounded' and not re.search(r'[㐀-䶿一-鿿豈-﫿]', text):
        font = ImageFont.truetype(str(ink.ASSETS / 'fonts' / TYPE_FONTS[family][1]),
                                  max(1, round(size)), layout_engine=ImageFont.Layout.BASIC)
    spacing = 4 if corner else 0
    if corner:
        lines = []
        for paragraph in text.split('\n'):
            line = ''
            for word in paragraph.split():
                candidate = f'{line} {word}' if line else word
                if _advance(font, candidate, family) + spacing * (len(candidate) - 1) <= width:
                    line = candidate
                    continue
                if line:
                    lines.append(line)
                line = ''
                for ch in word:
                    candidate = line + ch
                    if line and _advance(font, candidate, family) + spacing * (len(candidate) - 1) > width:
                        lines.append(line)
                        line = ''
                    line += ch
            lines.append(line)
        text = '\n'.join(lines)
    longest = max((_advance(font, line, family) + spacing * max(0, len(line) - 1) for line in text.split('\n')), default=1)
    if not corner:
        size *= min(1., width / max(1., longest))
    return text, font, size, spacing


def _text(element, scene, t, color):
    text = counter_text(element, t) if element.preset == 'counter' or element.chart == 'number' and element.kind == 'chart' else element.text
    text, font, size, spacing = _text_metrics(text, element.size, element.width, element.preset == 'corner_caption', element.font)
    if element.font == 'mono':
        # Silkscreen glyphs are proportional; lay them on an explicit fixed-advance grid.
        advance = font.getlength('M') * size / font.size + spacing
        shown = m.typewriter(text, t, element.start, cps=TYPE_CPS) if element.preset == 'type_on' else len(text)
        out, index = '', 0
        lines = text.split('\n')
        for row, line in enumerate(lines):
            for column, char in enumerate(line):
                if index < shown:
                    out += _text_tag(char, size, color, x=(column - (len(line) - 1) / 2) * advance,
                                     y=(row - (len(lines) - 1) / 2) * size * 1.15)
                index += 1
            index += 1
        return out
    if element.preset == 'type_on' and element.kind == 'text':
        shown = m.typewriter(text, t, element.start, cps=TYPE_CPS)
        out = ''
        lines = text.split('\n')
        for i, line in enumerate(lines):
            width = font.getlength(line) * size / font.size
            out += _text_tag(line[:max(0, shown)], size, color, x=-width / 2,
                             y=(i - (len(lines) - 1) / 2) * size * 1.15, anchor='start')
            shown -= len(line) + 1
        return out
    if element.preset in {'word_pop', 'cascade'}:
        rows = [line.split() if element.preset == 'word_pop' else list(line) for line in text.split('\n')]
        gap = size * .28 if element.preset == 'word_pop' else 0
        poses = m.letter_cascade(sum(map(len, rows)), t, element.start, dur=TEXT_ENTER)
        out, i = '', 0
        for row, pieces in enumerate(rows):
            widths = [font.getlength(piece) * size / font.size for piece in pieces]
            x = -(sum(widths) + gap * max(0, len(pieces) - 1)) / 2
            for piece, width in zip(pieces, widths):
                delay = i * (.1 if element.preset == 'word_pop' else .035)
                p = m.expo_out((t - element.start - delay) / TEXT_ENTER)
                if element.preset == 'word_pop':
                    scale = m.pop(t, element.start + delay, dur=TEXT_ENTER)['scale'] if scene.energy >= 4 else p
                    dy, rotation, alpha = 16 * (1 - p), 0, p
                else:
                    pose = poses[i]
                    scale = pose['scale'] if scene.energy >= 4 else .6 + .4 * p
                    dy, rotation, alpha = pose['dy'], pose['rotation'], pose['alpha']
                dy += (row - (len(rows) - 1) / 2) * size * 1.15
                out += (f'<g transform="translate({x + width / 2:.6f} {dy:.6f}) rotate({rotation:.6f}) scale({scale:.6f})" '
                        f'opacity="{alpha:.6f}">{_text_tag(piece, size, color)}</g>')
                x += width + gap
                i += 1
        return out
    lines = text.split('\n')
    body = ''.join(_text_tag(line, size, color, y=(i - (len(lines) - 1) / 2) * size * 1.15, spacing=spacing)
                   for i, line in enumerate(lines))
    if element.preset == 'slam':
        scale = m.slam(t, element.start, dur=TEXT_ENTER)['scale']
        return f'<g transform="scale({scale:.6f})">{body}</g>'
    return body


def _element_content(scene, e, i, t, geometry=None):
    color = scene.palette.accent if e.accent or e.kind in {'dot', 'ring', 'line', 'particle_field', 'chart'} else scene.palette.foreground
    art, text = '', ''
    if e.kind == 'text' or e.kind == 'chart' and e.chart == 'number':
        text = _text(e, scene, t, color)
    elif e.kind == 'picture':
        cover = scene.composition == 'full_bleed'
        width, height = (W * 1.06, H * 1.06) if cover else (e.width, e.height)
        art, text = _picture(e.svg_id, e.svg, width, height, color, cover, f'picture{i}_', e.preserve_svg_palette)
    elif e.kind == 'chart':
        art, text = chart_svg(e, t, color, scene.palette.foreground)
    elif e.kind == 'particle_field':
        src, dst = _particles(scene.seed + i, e.count, e.width, e.height)
        pts = m.assemble(src, dst, t - e.start, dur=PANEL_ENTER, stagger=PARTICLE_STAGGER, seed_key=scene.seed + i)
        for j, (x, y) in enumerate(pts):
            x += 5 * scene.motion_floor * math.sin(t * 1.2 + j)
            y += 5 * scene.motion_floor * math.cos(t * 1.7 + j)
            opacity = .9 + .25 * scene.motion_floor * (math.sin(t * 2 + j) - 1)
            art += f'<circle cx="{x:.6f}" cy="{y:.6f}" r="2.5" fill="{color}" opacity="{opacity:.6f}"/>'
    else:
        art = _shape(e, color, geometry)
        if e.kind == 'ring' and e.text:
            for ch, x, y, angle in m.ring_layout(e.text, (0, 0), e.size / 2 + 24, t, 8 * scene.motion_floor):
                text += (f'<g transform="translate({x:.6f} {y:.6f}) rotate({angle:.6f})">'
                         f'{_text_tag(ch, 20, scene.palette.foreground)}</g>')
    if text:
        text = f'<g font-family="{TYPE_FONTS[e.font][0]}, Noto Sans SC">{text}</g>'
    return art, text


def scene_svg(scene, t, layer='art', overrides=None):
    """Static SVG for one evaluated frame. Overrides carry matched motif geometry during morphs."""
    body = ''
    if layer == 'art':
        body = f'<rect width="{W}" height="{H}" fill="{scene.palette.background}"/>'
        floor = scene.motion_floor
        if floor:
            x, y = 1250 + 70 * math.sin(t * .73), 430 + 60 * math.cos(t * .91)
            body += (f'<defs><radialGradient id="ambient"><stop stop-color="{scene.palette.accent}" '
                     f'stop-opacity="{.05 * floor}"/><stop offset="1" stop-color="{scene.palette.accent}" '
                     f'stop-opacity="0"/></radialGradient></defs><ellipse cx="{x:.6f}" cy="{y:.6f}" '
                     f'rx="850" ry="650" fill="url(#ambient)"/>')
    for i, e in enumerate(scene.elements):
        pose = element_pose(scene, e, i, t)
        geometry = None
        if overrides and i in overrides:
            pose, geometry = overrides[i]
        if pose[3] <= 0:
            continue
        art, text = _element_content(scene, e, i, t, geometry)
        fragment = text if layer == 'text' else art
        if layer == 'emissive' and not e.emissive:
            fragment = ''
        if fragment:
            body += _group(fragment, pose)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="Arimo, Noto Sans SC" font-weight="700">{body}</svg>')


def _raster(doc, w, h, text=False):
    fonts = [str(ink.ASSETS / 'fonts' / name) for _, name in dict.fromkeys(TYPE_FONTS.values())] if text else []
    if text and any(ord(ch) > 127 for ch in doc):
        fonts.append(str(ink.ASSETS / 'fonts' / 'NotoSansSC-Bold.otf'))
    png = resvg_py.svg_to_bytes(svg_string=doc, width=w, height=h, skip_system_fonts=True, font_files=fonts)
    image = Image.open(io.BytesIO(png))
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    # Keep transparent margins in byte form; sprites expand only their crop.
    return np.asarray(image)


def glow_layer(emissive, half_distance):
    """Gaussian with zero padding: an isolated source's halo halves at ``half_distance`` pixels."""
    sigma = max(.01, half_distance / math.sqrt(2 * math.log(2)))
    kernel = _glow_kernel(sigma)
    if min(emissive.shape[:2]) == 1 or kernel.shape[0] == 1:
        return fftconvolve(emissive, kernel, mode='same', axes=(0, 1))
    shape, spectrum = _glow_spectrum(sigma, emissive.shape[:2])
    transformed = fft.rfftn(emissive, shape, axes=(0, 1))
    light = fft.irfftn(transformed * spectrum, shape, axes=(0, 1))
    # Use fftconvolve's exact padding, transform dtype and centred crop.
    radius = (kernel.shape[0] - 1) // 2
    h, w = emissive.shape[:2]
    return light[radius:radius + h, radius:radius + w].copy()


@lru_cache(maxsize=8)
def _glow_spectrum(sigma, size):
    kernel = _glow_kernel(sigma)
    shape = tuple(fft.next_fast_len(n + k - 1, real=True)
                  for n, k in zip(size, kernel.shape[:2]))
    return shape, fft.rfftn(kernel, shape, axes=(0, 1))


@lru_cache(maxsize=8)
def _glow_kernel(sigma):
    radius = int(4 * sigma + .5)
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    return (kernel[:, None] * kernel[None, :])[..., None]


@lru_cache(maxsize=8)
def _vignette(w, h):
    yy, xx = np.ogrid[:h, :w]
    radius = ((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2
    return (1 - .16 * radius).astype(np.float32)[..., None]


def _element_blurs(scene, e, i, t):
    dt = 1 / 240
    if e.kind == 'text' or e.kind == 'chart' and e.chart == 'number':
        return False
    a, b = element_pose(scene, e, i, t - dt), element_pose(scene, e, i, t + dt)
    if e.kind in {'dot', 'ring'}:
        radius = e.size / 2
    elif e.kind == 'line':
        radius = e.width / 2
    elif e.kind == 'picture' and scene.composition == 'full_bleed':
        radius = math.hypot(W, H) * 1.06 / 2
    else:
        radius = math.hypot(e.width, e.height) / 2
    if b[3] > 0 and (math.hypot(b[0] - a[0], b[1] - a[1]) + abs(b[2] - a[2]) * radius) / (2 * dt) > BLUR_SPEED:
        return True
    if b[3] <= 0:
        return False
    if e.kind == 'particle_field' and e.count:
        src, dst = _particles(scene.seed + i, e.count, e.width, e.height)
        p = m.assemble(src, dst, t - e.start - dt, dur=PANEL_ENTER, stagger=PARTICLE_STAGGER, seed_key=scene.seed + i)
        q = m.assemble(src, dst, t - e.start + dt, dur=PANEL_ENTER, stagger=PARTICLE_STAGGER, seed_key=scene.seed + i)
        if np.linalg.norm(q - p, axis=1).max() / (2 * dt) * b[2] > BLUR_SPEED:
            return True
    if e.kind == 'chart' and e.values:
        span = max(max(0, max(e.values)) - min(0, min(e.values)), 1e-9)
        for j, value in enumerate(e.values):
            delay = j * min(.09, .3 / max(1, len(e.values) - 1))
            local = t - e.start - delay
            duration = e.duration or .65
            change = m.expo_out((local + dt) / duration) - m.expo_out((local - dt) / duration)
            if abs(value) / span * e.height * change / (2 * dt) * b[2] > BLUR_SPEED:
                return True
    return False


def needs_motion_blur(scene, t):
    return any(_element_blurs(scene, e, i, t) for i, e in enumerate(scene.elements))


def _appearance(scene, e, t, geometry):
    local = max(0., t - e.start)
    state = None
    if e.kind == 'text' or e.kind == 'chart' and e.chart == 'number':
        if e.preset == 'counter' or e.kind == 'chart':
            state = counter_text(e, t)
        elif e.preset == 'type_on':
            state = m.typewriter(e.text, t, e.start, TYPE_CPS)
        elif e.preset in {'word_pop', 'cascade'}:
            n = len(e.text.split()) if e.preset == 'word_pop' else len(e.text)
            state = min(local, TEXT_ENTER + max(0, n - 1) * (.1 if e.preset == 'word_pop' else .035))
        elif e.preset == 'slam':
            state = min(local, TEXT_ENTER)
    elif e.kind == 'chart':
        state = min(local, (e.duration or .65) + min(.3, max(0, len(e.values) - 1) * .09))
    elif e.kind == 'particle_field':
        state = t if scene.motion_floor else min(local, PANEL_ENTER + PARTICLE_STAGGER)
    elif e.kind == 'ring' and e.text and scene.motion_floor:
        state = t
    if geometry is not None:
        points, fill, stroke = geometry
        state = state, points.tobytes(), fill, stroke
    fields = tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in vars(e).items())
    return (id(e), fields, scene.palette, scene.composition, scene.energy, scene.motion_floor, scene.seed, state)


def _bounds(scene, e, t, geometry):
    if geometry is not None:
        points = geometry[0]
        return points[:, 0].min() - 4, points[:, 1].min() - 4, points[:, 0].max() + 4, points[:, 1].max() + 4
    if e.kind == 'picture':
        w, h = (W * 1.06, H * 1.06) if scene.composition == 'full_bleed' else (e.width, e.height)
        x, y = w / 2 + 4, h / 2 + 4
    elif e.kind == 'particle_field':
        x, y = e.width + 12, e.height + 12
    elif e.kind == 'text' or e.kind == 'chart' and e.chart == 'number':
        value = counter_text(e, t) if e.preset == 'counter' or e.kind == 'chart' else e.text
        text, font, size, spacing = _text_metrics(value, e.size, e.width, e.preset == 'corner_caption', e.font)
        width = max((_advance(font, line, e.font) + spacing * max(0, len(line) - 1) for line in text.split('\n')), default=0)
        x = width * size / font.size * .7 + size / 2 + 4
        y = len(text.split('\n')) * size * .8 + (44 if e.preset == 'cascade' else 4)
    elif e.kind == 'chart':
        x, y = e.width / 2 + 80, e.height / 2 + 80
    elif e.kind == 'line':
        x, y = e.width / 2 + 4, 4
    else:
        x = y = e.size / 2 + (48 if e.kind == 'ring' and e.text else 4)
    return -x, -y, x, y


@lru_cache(maxsize=8)
def _particle_atlas(sx, sy):
    """Circle coverage at 1/32-pixel phases; one SVG raster for all placements.

    Only subpixel antialiasing is quantized (at most 1/64 pixel per axis).
    Position, assembly, opacity, blur and camera time remain continuous.
    """
    phases = 32
    mx, my = math.ceil(2.5 * sx) + 1, math.ceil(2.5 * sy) + 1
    tw, th = 2 * mx + 2, 2 * my + 2
    body = ''.join(
        f'<ellipse cx="{x * tw + mx + x / phases:.9f}" '
        f'cy="{y * th + my + y / phases:.9f}" rx="{2.5 * sx:.9f}" '
        f'ry="{2.5 * sy:.9f}" fill="white"/>'
        for y in range(phases) for x in range(phases))
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{tw * phases}" '
           f'height="{th * phases}">{body}</svg>')
    pixels = _raster(doc, tw * phases, th * phases)[..., 3].astype(np.float32) / 255
    return tuple(tuple(pixels[y * th:(y + 1) * th, x * tw:(x + 1) * tw].copy()
                       for x in range(phases)) for y in range(phases))


def _particle_sprite(scene, e, i, t, size):
    if not e.count:
        return None
    left, top, right, bottom = _bounds(scene, e, t, None)
    sw = max(1, math.ceil((right - left) * size[0] / W))
    sh = max(1, math.ceil((bottom - top) * size[1] / H))
    sx, sy = sw / (right - left), sh / (bottom - top)
    atlas = _particle_atlas(sx, sy)
    src, dst = _particles(scene.seed + i, e.count, e.width, e.height)
    pts = m.assemble(src, dst, t - e.start, dur=PANEL_ENTER,
                     stagger=PARTICLE_STAGGER, seed_key=scene.seed + i)
    placements = []
    for j, (x, y) in enumerate(pts):
        x += 5 * scene.motion_floor * math.sin(t * 1.2 + j)
        y += 5 * scene.motion_floor * math.cos(t * 1.7 + j)
        opacity = .9 + .25 * scene.motion_floor * (math.sin(t * 2 + j) - 1)
        px, py = round((round(x, 6) - left) * sx * 32), round((round(y, 6) - top) * sy * 32)
        ix, fx = divmod(px, 32)
        iy, fy = divmod(py, 32)
        tile = atlas[fy][fx]
        x0, y0 = ix - math.ceil(2.5 * sx) - 1, iy - math.ceil(2.5 * sy) - 1
        x1, y1 = min(sw, x0 + tile.shape[1]), min(sh, y0 + tile.shape[0])
        bx, by = max(0, x0), max(0, y0)
        if x1 <= bx or y1 <= by:
            continue
        alpha = np.rint(tile[by - y0:y1 - y0, bx - x0:x1 - x0] * opacity * 255) / 255
        placements.append((bx, by, x1, y1, alpha))
    if not placements:
        return None
    # Keep the same pixel grid and one-pixel crop padding, allocating only the
    # occupied tile bounds rather than the entire assembly/entrance envelope.
    ox = max(0, min(p[0] for p in placements) - 1)
    oy = max(0, min(p[1] for p in placements) - 1)
    right = min(sw, max(p[2] for p in placements) + 1)
    bottom = min(sh, max(p[3] for p in placements) + 1)
    coverage = np.zeros((bottom - oy, right - ox), np.float32)
    for bx, by, x1, y1, alpha in placements:
        region = coverage[by - oy:y1 - oy, bx - ox:x1 - ox]
        region += (1 - region) * alpha
    xs, ys = np.flatnonzero(coverage.max(axis=0)), np.flatnonzero(coverage.max(axis=1))
    if not len(xs) or not len(ys):
        return None
    x0, y0 = max(0, xs[0] - 1), max(0, ys[0] - 1)
    coverage = coverage[y0:ys[-1] + 2, x0:xs[-1] + 2].copy()
    color = ImageColor.getrgb(scene.palette.accent)
    return (Image.fromarray(coverage), color), left + (ox + x0) / sx, top + (oy + y0) / sy, sx, sy


def _sprite_pixels(pixels, left, top, sx, sy):
    xs = np.flatnonzero(pixels[..., 3].max(axis=0))
    ys = np.flatnonzero(pixels[..., 3].max(axis=1))
    if not len(xs) or not len(ys):
        return None
    h, w = pixels.shape[:2]
    x0, y0 = max(0, xs[0] - 1), max(0, ys[0] - 1)
    pixels = pixels[y0:min(h, ys[-1] + 2), x0:min(w, xs[-1] + 2)].astype(np.float32)
    pixels[..., 3] /= 255
    pixels[..., :3] *= pixels[..., 3:]
    channels = tuple(Image.fromarray(pixels[..., c]) for c in range(4))
    return channels, left + x0 / sx, top + y0 / sy, sx, sy


@lru_cache(maxsize=256)
def _counter_extent(value, size):
    # Measure the bundled Arimo numeric glyphs at its 2048-unit em size.
    # Their ink is inside their advances and their only numeric kerning pair
    # (11) shortens the run, so summed advances conservatively enclose it.
    font = ink.font('en_caption', 2048)
    width = sum(font.getlength(ch) for ch in value)
    _, top, _, bottom = font.getbbox(value, anchor='ls')
    ascent, descent = font.getmetrics()
    baseline = (ascent - descent) / 2
    padding = 2 + size / 1024  # raster edge padding and two font units
    return (width * size / 4096 + padding,
            max(abs(top + baseline), abs(bottom + baseline)) * size / 2048 + padding)



class _SceneLayers:
    def __init__(self, scene, w, h):
        self.scene, self.size = scene, (w, h)
        self.content = {}
        self.sprites = {}
        self.tokens = OrderedDict()
        self.particles = {}

    def counter_sprite(self, e, i, t):
        # Batch exact complete tokens, retaining resvg shaping, kerning and fit.
        # Prefetch is a cache policy only: arbitrary times still raster exactly.
        color = self.scene.palette.accent if e.accent or e.kind == 'chart' else self.scene.palette.foreground
        fragment = _text(e, self.scene, t, color)
        key = (self.size, fragment)
        if key not in self.tokens:
            rows, body, height, width = [], [], 0, 0
            seen = set()
            for time in (t + j / FPS for j in range(8)):
                token = _text(e, self.scene, time, color)
                if token in seen or (self.size, token) in self.tokens:
                    continue
                seen.add(token)
                left, top, right, bottom = _bounds(self.scene, e, time, None)
                value = counter_text(e, time)
                plain = (e.preset in {'counter', 'type_on'}
                         and re.fullmatch(r'[-0-9,.%]+', value))
                # Integer sampling scales keep cropped sprite origins exactly
                # representable. Fractional scales retain the original bounds.
                if plain and self.size[0] % (W // 2) == 0 and self.size[1] % (H // 2) == 0:
                    _, _, size, _ = _text_metrics(value, e.size, e.width, False)
                    x, y = _counter_extent(value, size)
                    right, bottom = min(right, x), min(bottom, y)
                # Keep one sampling grid for every token, independent of its
                # neighbours and vertical position in a prefetched sheet.
                sx, sy = self.size[0] / W * 2, self.size[1] / H * 2
                sw = max(2, 2 * math.ceil(right * sx))
                sh = max(2, 2 * math.ceil(bottom * sy))
                left, top = -sw / (2 * sx), -sh / (2 * sy)
                right, bottom = -left, -top
                # Plain Arimo digits/punctuation fit inside these padded bounds.
                # Avoid a sheet-sized viewport mask for each such token; retain
                # clipping for arbitrary suffixes and animated text transforms.
                overflow = 'visible' if plain else 'hidden'
                body.append(f'<svg x="0" y="{height}" width="{sw}" height="{sh}" '
                            f'viewBox="{left} {top} {right - left} {bottom - top}" '
                            f'preserveAspectRatio="none" overflow="{overflow}">{token}</svg>')
                rows.append((token, height, sw, sh, left, top, sx, sy))
                height += sh
                width = max(width, sw)
            doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                   f'font-family="Arimo, Noto Sans SC" font-weight="700">{"".join(body)}</svg>')
            pixels = _raster(doc, width, height, text=True)
            for token, y, sw, sh, left, top, sx, sy in rows:
                self.tokens[self.size, token] = _sprite_pixels(pixels[y:y + sh, :sw], left, top, sx, sy)
            while len(self.tokens) > 128:
                self.tokens.popitem(last=False)
        self.tokens.move_to_end(key)
        return self.tokens[key]

    def sprite(self, i, t, layer, geometry=None):
        e = self.scene.elements[i]
        if layer == 'text' and e.font == 'rounded' and (e.kind == 'text' and e.preset == 'counter' or e.kind == 'chart' and e.chart == 'number'):
            return self.counter_sprite(e, i, t)
        if e.kind == 'particle_field' and geometry is None:
            if layer == 'text':
                return None
            state = _appearance(self.scene, e, t, None)
            cache = self.particles.setdefault(i, OrderedDict())
            if state not in cache:
                cache[state] = _particle_sprite(self.scene, e, i, t, self.size)
                # Retain a frame's blur samples and its exact-time glow sample.
                while len(cache) > self.scene.blur_samples + 1:
                    cache.popitem(last=False)
            cache.move_to_end(state)
            return cache[state]
        state = _appearance(self.scene, e, t, geometry)
        if i not in self.content or self.content[i][0] != state:
            self.content[i] = state, _element_content(self.scene, e, i, t, geometry)
        fragment = self.content[i][1][layer == 'text']
        if not fragment:
            return None
        key = i, layer
        if key not in self.sprites or self.sprites[key][0] != fragment:
            left, top, right, bottom = _bounds(self.scene, e, t, geometry if layer != 'text' else None)
            w, h = self.size
            sampling = 2 if layer == 'text' or e.kind in {'dot', 'ring', 'line'} else 1
            sw, sh = max(1, math.ceil((right - left) * w / W * sampling)), max(1, math.ceil((bottom - top) * h / H * sampling))
            doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{sw}" height="{sh}" '
                   f'viewBox="{left} {top} {right - left} {bottom - top}" preserveAspectRatio="none" '
                   f'font-family="Arimo, Noto Sans SC" font-weight="700">{fragment}</svg>')
            pixels = _raster(doc, sw, sh, text=layer == 'text')
            sx, sy = sw / (right - left), sh / (bottom - top)
            sprite = _sprite_pixels(pixels, left, top, sx, sy)
            self.sprites[key] = fragment, sprite
        return self.sprites[key][1]


_LAYERS = OrderedDict()


def _layers(scene, w, h):
    key = id(scene), w, h
    if key not in _LAYERS:
        _LAYERS[key] = _SceneLayers(scene, w, h)
        if len(_LAYERS) > 4:
            _LAYERS.popitem(last=False)
    _LAYERS.move_to_end(key)
    return _LAYERS[key]


def _warp(sprite, pose, w, h):
    if sprite is None or pose[3] <= 0:
        return None
    channels, left, top, sx, sy = sprite
    solid = len(channels) == 2
    image = channels[0]
    # NumPy time scalars must not promote float32 compositing to float64.
    x, y, scale, alpha = (round(float(v), 6) for v in pose)
    dx, dy = scale * w / W / sx, scale * h / H / sy
    if dx <= 0 or dy <= 0:
        return None
    x, y = (x + left * scale) * w / W, (y + top * scale) * h / H
    x0, y0 = max(0, math.floor(x) - 1), max(0, math.floor(y) - 1)
    x1, y1 = min(w, math.ceil(x + channels[0].width * dx) + 1), min(h, math.ceil(y + channels[0].height * dy) + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    matrix = (1 / dx, 0, (x0 - x) / dx, 0, 1 / dy, (y0 - y) / dy)
    if solid:
        coverage = np.asarray(image.transform((x1 - x0, y1 - y0), Image.AFFINE, matrix, Image.BILINEAR)) * alpha
        moved = np.empty((*coverage.shape, 4), np.float32)
        moved[..., 3] = coverage
        # The integer colour tuple promotes the original RGB product to
        # float64. Keep that rounding, writing directly into the float32
        # destination instead of allocating a full float64 RGB temporary.
        for c, color in enumerate(channels[1]):
            np.multiply(coverage, color, out=moved[..., c], dtype=np.float64)
        return x0, y0, moved
    moved = np.empty((y1 - y0, x1 - x0, 4), np.float32)
    for c, channel in enumerate(channels):
        np.multiply(np.asarray(channel.transform((x1 - x0, y1 - y0), Image.AFFINE, matrix, Image.BILINEAR)),
                    alpha, out=moved[..., c])
    return x0, y0, moved


def _over(target, moved):
    if moved is not None:
        x, y, pixels = moved
        region = target[y:y + pixels.shape[0], x:x + pixels.shape[1]]
        inverse = 1 - pixels[..., 3]
        # Avoid the short RGB broadcast loop; retain float32 multiply/add order.
        for c in range(region.shape[2]):
            region[..., c] *= inverse
            region[..., c] += pixels[..., c]


def _composite(target, layers, i, times, layer, overrides=None):
    h, w = target.shape[:2]
    samples = []
    for t in times:
        pose, geometry = element_pose(layers.scene, layers.scene.elements[i], i, t), None
        if overrides and i in overrides:
            pose, geometry = overrides[i]
        if pose[3] > 0:
            moved = _warp(layers.sprite(i, t, layer, geometry), pose, w, h)
            if moved is not None:
                samples.append(moved)
    if not samples:
        return
    if len(times) == 1:
        _over(target, samples[0])
        return
    x0, y0 = min(s[0] for s in samples), min(s[1] for s in samples)
    x1 = max(x + p.shape[1] for x, y, p in samples)
    y1 = max(y + p.shape[0] for x, y, p in samples)
    mixed = np.zeros((y1 - y0, x1 - x0, 4), np.float32)
    for x, y, pixels in samples:
        # Warped samples are private arrays; retain division before addition
        # without allocating another RGBA sample for the quotient.
        pixels /= len(times)
        mixed[y - y0:y - y0 + pixels.shape[0], x - x0:x - x0 + pixels.shape[1]] += pixels
    _over(target, (x0, y0, mixed))


def _resize_rgb(pixels, w, h):
    if (w, h) != (pixels.shape[1] * 4, pixels.shape[0] * 4):
        return np.asarray(Image.fromarray(pixels).resize((w, h), Image.BILINEAR))
    # Pillow's 4x bilinear weights are exact eighths. Round each byte pass
    # separately, horizontal first, including the replicated edge pixels.
    for axis in (1, 0):
        source = pixels.astype(np.uint16)
        base = (source << 3) + 4
        delta, scratch = np.empty_like(source), np.empty_like(source)
        shape = list(source.shape)
        shape[axis] *= 4
        pixels = np.empty(shape, np.uint8)
        before, after = [slice(None)] * 3, [slice(None)] * 3
        before[axis], after[axis] = slice(None, -1), slice(1, None)
        before, after = tuple(before), tuple(after)
        for direction, phases in ((-1, (1, 0)), (1, (2, 3))):
            edge = [slice(None)] * 3
            edge[axis] = 0 if direction < 0 else -1
            if direction < 0:
                np.subtract(source[before], source[after], out=delta[after])
            else:
                np.subtract(source[after], source[before], out=delta[before])
            delta[tuple(edge)] = 0
            for phase in phases:
                # Unsigned differences wrap, but the completed positive
                # weighted sum is <= 2044 and is exact modulo 65536.
                np.add(base, delta, out=scratch)
                np.right_shift(scratch, 3, out=scratch)
                destination = [slice(None)] * 3
                destination[axis] = slice(phase, None, 4)
                pixels[tuple(destination)] = scratch
                if phase == phases[0]:
                    delta *= 3
    return pixels


def _background(scene, t, w, h):
    background = np.array(ImageColor.getrgb(scene.palette.background), np.float32)
    if scene.motion_floor:
        gw, gh = max(1, w // 4), max(1, h // 4)
        yy, xx = np.ogrid[:gh, :gw]
        cx, cy = 1250 + 70 * math.sin(t * .73), 430 + 60 * math.cos(t * .91)
        distance = np.sqrt(((xx + .5) * W / gw - cx) ** 2 / 850 ** 2 + ((yy + .5) * H / gh - cy) ** 2 / 650 ** 2)
        alpha = np.maximum(0, 1 - distance)[..., None] * .05 * scene.motion_floor
        ambient = background + (np.array(ImageColor.getrgb(scene.palette.accent)) - background) * alpha
        return np.asarray(_resize_rgb(np.clip(ambient + .5, 0, 255).astype(np.uint8), w, h), np.float32)
    return np.broadcast_to(background, (h, w, 3)).copy()


def render_frame(scene, t, w=W, h=H, *, _overrides=None, background=None):
    """RGB uint8 array. Motion blur supersamples artwork alone; grain/glow never touch text."""
    if w <= 0 or h <= 0 or not math.isfinite(t):
        raise ValueError('Frame size must be positive and time finite')
    layers = _layers(scene, w, h)
    art = _background(scene, t, w, h) if background is None else np.asarray(background, np.float32).copy()
    for i, e in enumerate(scene.elements):
        times = [t]
        if scene.blur_samples > 1 and _overrides is None and _element_blurs(scene, e, i, t):
            times = t + np.linspace(-.5, .5, scene.blur_samples) / FPS
        _composite(art, layers, i, times, 'art', _overrides)
    if scene.glow and any(e.emissive for e in scene.elements):
        gw, gh = max(1, w // 4), max(1, h // 4)
        light = np.zeros((gh, gw, 4), np.float32)
        for i, e in enumerate(scene.elements):
            if e.emissive:
                _composite(light, layers, i, [t], 'art', _overrides)
        light = glow_layer(light[..., :3], GLOW_HALF * gh / H)
        halo = np.clip(light * 4 * scene.glow, 0, 255).astype(np.uint8)
        art += _resize_rgb(halo, w, h)
    vignette = _vignette(w, h)[..., 0]
    # As in _over, avoid NumPy's short-channel broadcast inner loop.
    for c in range(3):
        art[..., c] *= vignette
    if scene.grain:
        rng = m.seeded(scene.seed, 'bold grain', math.floor(t * FPS + 1e-6), w, h)
        grain = rng.normal(0, scene.grain, (h, w, 1)).astype(np.float32)[..., 0]
        for c in range(3):
            art[..., c] += grain
    for i in range(len(scene.elements)):
        _composite(art, layers, i, [t], 'text', _overrides)
    art += .5
    np.clip(art, 0, 255, out=art)
    return art.astype(np.uint8)

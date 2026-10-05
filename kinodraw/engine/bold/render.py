"""Pure-time SVG frames, with emissive glow and a separate, always sharp text layer."""
from __future__ import annotations

import io
import math
import re
from copy import deepcopy
from functools import lru_cache
from html import escape
from xml.etree import ElementTree as ET

import numpy as np
import resvg_py
from defusedxml.ElementTree import fromstring
from PIL import Image
from scipy import ndimage

from ... import library
from .. import ink, motion as m
from .charts import chart_svg, counter_text
from .model import PANEL_ENTER, PARTICLE_STAGGER, TEXT_ENTER, TYPE_CPS

W, H, FPS = 1920, 1080, 30
BLUR_SPEED = 600                    # reference-stage pixels/second
GLOW_HALF = 100                     # radial half-intensity distance at 1080p
FONT = str(ink.ASSETS / 'fonts' / 'Arimo-Bold.ttf')


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


def _camera(scene, t):
    end = scene.duration
    finish = {'static': (W / 2, H / 2, 1.), 'slow_push': (W / 2, H / 2, 1.045),
              'pull_back': (W / 2, H / 2, .96), 'pan': (W / 2 + 65, H / 2, 1.)}[scene.camera if scene.camera != 'shake' else 'static']
    cam = m.Camera2D([(0, W / 2, H / 2, 1.), (end, *finish)], size=(W, H))
    x, y, z = cam.at(t)
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
    drift = .7 if corner else 5.
    x += floor * drift * math.sin(t * 1.13 + phase)
    y += floor * drift * .7 * math.sin(t * 1.67 + phase * .8)
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
def _picture(svg_id, raw, width, height, color, cover=False, prefix='picture_'):
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
            if name in {'fill', 'stroke', 'stop-color'} and value not in {'none', 'transparent'} and not value.startswith('url('):
                node.set(key, color)
            if name == 'style':
                # Explicit colour attributes preserve holes and keep authored art in the scene's palette.
                for declaration in value.split(';'):
                    prop, _, val = declaration.partition(':')
                    if prop.strip() in {'fill', 'stroke', 'stop-color'}:
                        node.set(prop.strip(), val.strip() if val.strip() in {'none', 'transparent'} else color)
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
    a = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    if element.kind == 'line':
        return np.column_stack((np.linspace(-element.width / 2, element.width / 2, 64), np.zeros(64)))
    r = element.size / 2
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


def _text(element, scene, t, color):
    text = counter_text(element, t) if element.preset == 'counter' or element.chart == 'number' and element.kind == 'chart' else element.text
    size = element.size
    font = ink.font('en_caption', max(1, round(size)))
    spacing = 4 if element.preset == 'corner_caption' else 0
    longest = max((font.getlength(line) + spacing * max(0, len(line) - 1) for line in text.split('\n')), default=1)
    size *= min(1., element.width / max(1., longest))
    if element.preset == 'type_on' and element.kind == 'text':
        shown = m.typewriter(text, t, element.start, cps=TYPE_CPS)
        out = ''
        lines = text.split('\n')
        for i, line in enumerate(lines):
            width = font.getlength(line) * size / element.size
            out += _text_tag(line[:max(0, shown)], size, color, x=-width / 2,
                             y=(i - (len(lines) - 1) / 2) * size * 1.15, anchor='start')
            shown -= len(line) + 1
        return out
    if element.preset in {'word_pop', 'cascade'}:
        pieces = text.split() if element.preset == 'word_pop' else list(text)
        widths = [font.getlength(p) * size / element.size for p in pieces]
        gap = size * .28 if element.preset == 'word_pop' else 0
        x = -(sum(widths) + gap * max(0, len(pieces) - 1)) / 2
        poses = m.letter_cascade(len(pieces), t, element.start, dur=TEXT_ENTER)
        out = ''
        for i, (piece, width) in enumerate(zip(pieces, widths)):
            delay = i * (.1 if element.preset == 'word_pop' else .035)
            p = m.expo_out((t - element.start - delay) / TEXT_ENTER)
            if element.preset == 'word_pop':
                scale = m.pop(t, element.start + delay, dur=TEXT_ENTER)['scale'] if scene.energy >= 4 else p
                dy, rotation, alpha = 16 * (1 - p), 0, p
            else:
                pose = poses[i]
                scale = pose['scale'] if scene.energy >= 4 else .6 + .4 * p
                dy, rotation, alpha = pose['dy'], pose['rotation'], pose['alpha']
            out += (f'<g transform="translate({x + width / 2:.6f} {dy:.6f}) rotate({rotation:.6f}) scale({scale:.6f})" '
                    f'opacity="{alpha:.6f}">{_text_tag(piece, size, color)}</g>')
            x += width + gap
        return out
    lines = text.split('\n')
    body = ''.join(_text_tag(line, size, color, y=(i - (len(lines) - 1) / 2) * size * 1.15, spacing=spacing)
                   for i, line in enumerate(lines))
    if element.preset == 'slam':
        scale = m.slam(t, element.start, dur=TEXT_ENTER)['scale']
        return f'<g transform="scale({scale:.6f})">{body}</g>'
    return body


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
        color = scene.palette.accent if e.accent or e.kind in {'dot', 'ring', 'line', 'particle_field', 'chart'} else scene.palette.foreground
        art, text = '', ''
        if e.kind == 'text' or e.kind == 'chart' and e.chart == 'number':
            if layer == 'text':
                text = _text(e, scene, t, color)
        elif e.kind == 'picture':
            cover = scene.composition == 'full_bleed'
            width, height = (W * 1.06, H * 1.06) if cover else (e.width, e.height)
            art, text = _picture(e.svg_id, e.svg, width, height, color, cover, f'picture{i}_')
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
        fragment = text if layer == 'text' else art
        if layer == 'emissive' and not e.emissive:
            fragment = ''
        if fragment:
            body += _group(fragment, pose)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="Arimo, Noto Sans SC" font-weight="700">{body}</svg>')


def _raster(doc, w, h, text=False):
    fonts = [FONT] if text else []
    if text and any(ord(ch) > 127 for ch in doc):
        fonts.append(str(ink.ASSETS / 'fonts' / 'NotoSansSC-Bold.otf'))
    png = resvg_py.svg_to_bytes(svg_string=doc, width=w, height=h, skip_system_fonts=True, font_files=fonts)
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'), np.float32)


def glow_layer(emissive, half_distance):
    """Separable Gaussian: an isolated source's halo halves at ``half_distance`` pixels."""
    sigma = max(.01, half_distance / math.sqrt(2 * math.log(2)))
    layer = ndimage.gaussian_filter1d(emissive, sigma, axis=0, mode='constant')
    return ndimage.gaussian_filter1d(layer, sigma, axis=1, mode='constant')


@lru_cache(maxsize=8)
def _vignette(w, h):
    yy, xx = np.ogrid[:h, :w]
    radius = ((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2
    return (1 - .16 * radius).astype(np.float32)[..., None]


def needs_motion_blur(scene, t):
    dt = 1 / 240
    for i, e in enumerate(scene.elements):
        if e.kind == 'text' or e.kind == 'chart' and e.chart == 'number':
            continue
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
            continue
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


def render_frame(scene, t, w=W, h=H, *, _overrides=None):
    """RGB uint8 array. Motion blur supersamples artwork alone; grain/glow never touch text."""
    if w <= 0 or h <= 0 or not math.isfinite(t):
        raise ValueError('Frame size must be positive and time finite')
    times = [t]
    if scene.blur_samples > 1 and _overrides is None and needs_motion_blur(scene, t):
        times = t + np.linspace(-.5, .5, scene.blur_samples) / FPS
    art = sum(_raster(scene_svg(scene, float(s), overrides=_overrides), w, h)[..., :3] for s in times) / len(times)
    if scene.glow and any(e.emissive for e in scene.elements):
        gw, gh = max(1, w // 6), max(1, h // 6)
        light = _raster(scene_svg(scene, t, 'emissive', _overrides), gw, gh)
        light = glow_layer(light[..., :3] * light[..., 3:] / 255, GLOW_HALF * gh / H)
        halo = Image.fromarray(np.clip(light * 4 * scene.glow, 0, 255).astype(np.uint8))
        art += np.asarray(halo.resize((w, h), Image.BILINEAR), np.float32)
    art *= _vignette(w, h)
    if scene.grain:
        rng = m.seeded(scene.seed, 'bold grain', math.floor(t * FPS + 1e-6), w, h)
        art += rng.normal(0, scene.grain, (h, w, 1)).astype(np.float32)
    text = _raster(scene_svg(scene, t, 'text', _overrides), w, h, text=True)
    alpha = text[..., 3:] / 255
    art = art * (1 - alpha) + text[..., :3] * alpha
    return np.clip(art + .5, 0, 255).astype(np.uint8)

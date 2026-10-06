"""Bounded source plots and closed-form models; no code evaluation or source fetching.

The director chooses a beat's chart treatment, never generates its numbers. Geometry
is fixed in data coordinates: reveal/highlight is the only animated property.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date
from urllib.parse import urlsplit

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FORMAT = 'kinodraw-scientific'
MAX_BYTES = 2 * 1024 * 1024
MAX_POINTS = 8192
EQUATION = 'x(t) = A cos(omega t + phase); v(t) = -A omega sin(omega t + phase)'
COLOURS = ('#65E5F2', '#F99BAF', '#CEB9FF', '#FFE28C')


def _text(value, name, limit=240):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 for c in value)):
        raise ValueError(f'{name} needs nonempty single-line text of at most {limit} characters')
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number')
    try:
        valid = math.isfinite(value) and abs(value) <= 1e12
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be finite with absolute value at most 1e12')
    return float(value)


def _keys(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'{name} must be an object with only {", ".join(allowed)}')


def validate(data):
    """Validate the complete inline contract before rendering or persisting anything."""
    _keys(data, ('format', 'version', 'title', 'mode', 'axes', 'provenance', 'tracks', 'model'), 'plot')
    if data.get('format') != FORMAT or type(data.get('version')) is not int or data.get('version') != 1:
        raise ValueError('scientific plot format/version must be kinodraw-scientific/1')
    _text(data.get('title'), 'title', 120)
    if data.get('mode') not in ('observed', 'analytical'):
        raise ValueError('mode must be observed or analytical')
    axes = data.get('axes')
    _keys(axes, ('x', 'y'), 'axes')
    for key in ('x', 'y'):
        axis = axes.get(key)
        _keys(axis, ('label', 'unit', 'domain'), key + ' axis')
        _text(axis.get('label'), key + ' label', 60)
        _text(axis.get('unit'), key + ' unit (use dimensionless when appropriate)', 40)
        if 'domain' in axis:
            domain = axis['domain']
            if not isinstance(domain, list) or len(domain) != 2:
                raise ValueError('axis domain must be [minimum, maximum]')
            lo, hi = [_number(v, 'axis bound') for v in domain]
            if not 1e-12 <= hi - lo <= 2e12:
                raise ValueError('axis domain must have increasing, bounded extent')
    provenance = data.get('provenance')
    _keys(provenance, ('citation', 'url', 'license', 'version', 'accessed', 'transforms'), 'provenance')
    for key in ('citation', 'url', 'license', 'version', 'accessed', 'transforms'):
        _text(provenance.get(key), 'provenance.' + key, 1200)
    parsed = urlsplit(provenance['url'])
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('provenance URL must be a public http(s) citation, without credentials')
    try:
        date.fromisoformat(provenance['accessed'])
    except ValueError:
        raise ValueError('provenance.accessed must be a valid calendar date') from None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', provenance['accessed']):
        raise ValueError('provenance.accessed must be YYYY-MM-DD')
    if data['mode'] == 'observed':
        if 'model' in data:
            raise ValueError('observed plots cannot contain a model')
        tracks = data.get('tracks')
        if not isinstance(tracks, list) or not 1 <= len(tracks) <= 8:
            raise ValueError('observed plots need 1-8 tracks')
        count = 0
        for track in tracks:
            _keys(track, ('label', 'encoding', 'points', 'color'), 'track')
            _text(track.get('label'), 'track label', 80)
            if track.get('encoding') not in ('series', 'path', 'scatter'):
                raise ValueError('encoding must be series, path or scatter')
            if 'color' in track and (not isinstance(track['color'], str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', track['color'])):
                raise ValueError('track color must be #RRGGBB')
            points = track.get('points')
            if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
                raise ValueError('a track needs 1-8192 supplied points; missing values are not interpolated')
            count += len(points)
            if count > MAX_POINTS:
                raise ValueError('plot exceeds 8192 total points')
            previous = None
            for point in points:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError('each point must be [x, y]')
                x, y = [_number(v, 'coordinate') for v in point]
                if track['encoding'] == 'series' and previous is not None and x <= previous:
                    raise ValueError('series x coordinates must strictly increase; use path for ordered trajectories')
                previous = x
                for key, v in (('x', x), ('y', y)):
                    domain = axes[key].get('domain')
                    if domain and not domain[0] <= v <= domain[1]:
                        raise ValueError('axis domain must include every supplied coordinate')
    else:
        if 'tracks' in data:
            raise ValueError('analytical plots cannot contain observed tracks')
        model = data.get('model')
        _keys(model, ('kind', 'projection', 'parameters', 'samples', 'seed'), 'model')
        if model.get('kind') != 'harmonic_oscillator' or model.get('projection') not in ('time', 'phase'):
            raise ValueError('only harmonic_oscillator with time or phase projection is supported')
        parameters = model.get('parameters')
        _keys(parameters, ('amplitude_m', 'omega_rad_s', 'phase_rad', 'start_s', 'end_s'), 'parameters')
        p = {k: _number(parameters.get(k), k) for k in
             ('amplitude_m', 'omega_rad_s', 'phase_rad', 'start_s', 'end_s')}
        if not 0 < p['amplitude_m'] <= 1e6 or not 0 < p['omega_rad_s'] <= 1e4:
            raise ValueError('amplitude must be (0, 1e6] m and omega (0, 1e4] rad/s')
        if not 1e-6 <= p['end_s'] - p['start_s'] <= 1e6:
            raise ValueError('model time extent must be [1e-6, 1e6] s')
        samples = model.get('samples')
        if isinstance(samples, bool) or not isinstance(samples, int) or not 32 <= samples <= MAX_POINTS:
            raise ValueError('model samples must be an integer in 32-8192')
        # At least 16 points per cycle, so a sampled curve cannot imply a wrong frequency.
        if (p['end_s'] - p['start_s']) * p['omega_rad_s'] / (2 * math.pi) > (samples - 1) / 16:
            raise ValueError('model is undersampled: need at least 16 samples per cycle')
        if type(model.get('seed')) is not int or model.get('seed') != 0:
            raise ValueError('closed-form model seed must be 0 (no stochastic generation)')
        expected = ('s', 'm') if model['projection'] == 'time' else ('m', 'm/s')
        if tuple(axes[k]['unit'] for k in ('x', 'y')) != expected:
            raise ValueError(f'model axis units must be {expected}')
        for points in _model_tracks(model):
            for i, key in enumerate(('x', 'y')):
                domain = axes[key].get('domain')
                if domain and not domain[0] <= points['points'][:, i].min() <= points['points'][:, i].max() <= domain[1]:
                    raise ValueError('model axis domain excludes computed coordinates')
    # Also rejects an enormous document/unused data before allocation of render layers.
    if len(json.dumps(data, allow_nan=False).encode('utf-8')) > MAX_BYTES:
        raise ValueError('scientific payload exceeds 2 MiB')
    return copy.deepcopy(data)


def _model_tracks(model):
    p = model['parameters']
    t = np.linspace(p['start_s'], p['end_s'], model['samples'])
    angle = p['omega_rad_s'] * t + p['phase_rad']
    x = p['amplitude_m'] * np.cos(angle)
    y = (-p['amplitude_m'] * p['omega_rad_s'] * np.sin(angle)
         if model['projection'] == 'phase' else x)
    return [{'label': 'Closed-form oscillator', 'encoding': 'path' if model['projection'] == 'phase' else 'series',
             'points': np.column_stack((x if model['projection'] == 'phase' else t, y))}]


def summary(data):
    data = validate(data)
    return {key: data[key] for key in ('title', 'mode', 'axes')} | {
        'citation': data['provenance']['citation'],
        'encoding': [t['encoding'] for t in data.get('tracks', [])] or [data['model']['projection']],
        'model': data.get('model', {}).get('kind'),
        'rendering': {'treatment': 'chart', 'canvas': 'exact black', 'coordinates': 'fixed linear axes',
                      'animation': 'sample reveal', 'data_owner': 'existing beat visual',
                      'labels': 'units, model parameters and attribution from validated record'}}


def attributions(board):
    records = []
    for beat in board['beats']:
        for visual in beat.get('visuals', []):
            if visual.get('type') != 'scientific':
                continue
            data = validate(visual.get('plot'))
            records.append({'beat': beat['id'], 'visual': visual['id'], 'title': data['title'],
                            'mode': data['mode'], 'axes': data['axes'], 'provenance': data['provenance'],
                            'model': ({**data['model'], 'equation': EQUATION, 'solver': 'closed form'}
                                      if data['mode'] == 'analytical' else None),
                            'source_file': visual.get('source_file'), 'source_sha256': visual.get('source_sha256'),
                            'plot_sha256': hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
                            'render_transform': 'linear independent axes; no smoothing; input order; progressive reveal'})
    return records


class ScientificPlot:
    """Render fixed scientific geometry on exact black, with local, finite glow."""
    def __init__(self, data):
        self.data = validate(data)
        self.tracks = (_model_tracks(self.data['model']) if self.data['mode'] == 'analytical' else
                       [{**track, 'points': np.asarray(track['points'], dtype=float)} for track in self.data['tracks']])
        all_points = np.concatenate([t['points'] for t in self.tracks])
        self.domains = []
        for i, key in enumerate(('x', 'y')):
            domain = self.data['axes'][key].get('domain')
            if domain is None:
                lo, hi = all_points[:, i].min(), all_points[:, i].max()
                pad = (hi - lo) * .04 if hi > lo else max(1., abs(lo) * .04)
                domain = [float(lo - pad), float(hi + pad)]
            self.domains.append(tuple(domain))

    def geometry(self, box):
        """Pixel coordinates, independent of frame time or decoration, for auditing."""
        left, top, right, bottom = box
        out = []
        for track in self.tracks:
            result = np.empty_like(track['points'])
            for i, (lo, hi) in enumerate(self.domains):
                u = (track['points'][:, i] - lo) / (hi - lo)
                result[:, i] = left + u * (right - left) if i == 0 else bottom - u * (bottom - top)
            out.append(result)
        return out

    def frame(self, t, duration, size, *, panel=(.06, .06, .94, .74)):
        from .engine.ink import font
        w, h = size
        image = Image.new('RGB', (w, h), '#000000')
        draw = ImageDraw.Draw(image)
        left, top, right, bottom = [round(v * (w if i % 2 == 0 else h)) for i, v in enumerate(panel)]
        width = right - left
        scale = min(width / 1689.6, (bottom - top) / 820.8)
        textfont = font('ui', max(2, round(24 * scale)))
        titlefont = font('ui', max(3, round(39 * scale)))
        smallfont = font('ui', max(2, round(19 * scale)))

        def text(value, xy, face=textfont, color='#B9D5DA'):
            # Fit each complete label in its allocated line; never let it overlap captions.
            f = face
            while f.getlength(value) > width and f.size > 8:
                f = font('ui', f.size - 1)
            if f.getlength(value) > width:
                value = value[:max(1, int(len(value) * width / f.getlength(value)) - 1)] + '…'
            draw.text(xy, value, font=f, fill=color)

        text(self.data['title'], (left, top), titlefont, '#E1FCFF')
        mode = 'OBSERVED / SOURCED' if self.data['mode'] == 'observed' else 'ANALYTICAL MODEL / CLOSED FORM'
        text(mode, (left, top + round(53 * scale)), smallfont, '#65E5F2')
        model = self.data.get('model')
        if model:
            p = model['parameters']
            text('x = A cos(ωt + φ)    v = −Aω sin(ωt + φ)', (left, top + round(83 * scale)), smallfont)
            text(f"A={p['amplitude_m']:g} m   ω={p['omega_rad_s']:g} rad/s   φ={p['phase_rad']:g} rad   "
                 f"t={p['start_s']:g}…{p['end_s']:g} s", (left, top + round(112 * scale)), smallfont)
        label_y = top + round((150 if model else 91) * scale)
        yaxis = self.data['axes']['y']
        text(yaxis['label'] + ' [' + yaxis['unit'] + ']', (left, label_y), smallfont)
        box = (left + round(100 * scale), label_y + round(42 * scale), right - round(28 * scale),
               bottom - round(117 * scale))
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            raise ValueError('scientific panel too small to plot safely')
        draw.line([(x0, y0), (x0, y1), (x1, y1)], fill='#31545B', width=max(1, round(scale)))
        for axis in (0, 1):
            lo, hi = self.domains[axis]
            for u in (0, .5, 1):
                value = lo + u * (hi - lo)
                label = f'{value:.15g}'
                tickfont = smallfont
                limit = ((x1-x0) * .42 if axis == 0 else x0-left-12*scale)
                while tickfont.getlength(label) > limit and tickfont.size > 6:
                    tickfont = font('ui', tickfont.size - 1)
                if axis == 0:
                    x = x0 + u * (x1 - x0)
                    draw.line([(x, y1), (x, y1 + 5 * scale)], fill='#698F96')
                    draw.text((x - tickfont.getlength(label) / 2, y1 + 9 * scale), label, font=tickfont, fill='#B9D5DA')
                else:
                    y = y1 - u * (y1 - y0)
                    draw.line([(x0 - 5 * scale, y), (x0, y)], fill='#698F96')
                    draw.text((x0 - 12 * scale - tickfont.getlength(label), y - tickfont.size / 2), label, font=tickfont, fill='#B9D5DA')
        marks = Image.new('RGB', size)
        markdraw = ImageDraw.Draw(marks)
        # Reveal full records only. No interpolated measurement/cursor or moving axes.
        progress = min(1., max(0., t / max(.01, duration * .75)))
        for i, (track, points) in enumerate(zip(self.tracks, self.geometry(box))):
            count = min(len(points), math.floor(progress * len(points)))
            visible = [tuple(p) for p in points[:count]]
            color = track.get('color', COLOURS[i % len(COLOURS)])
            radius = max(1, round(2 * scale))
            if track['encoding'] != 'scatter' and len(visible) >= 2:
                markdraw.line(visible, fill=color, width=max(1, round(2 * scale)))
            if track['encoding'] == 'scatter' or len(visible) == 1:
                for x, y in visible:
                    markdraw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
            if visible:
                x, y = visible[-1]
                r = max(2, round(4 * scale))
                markdraw.ellipse((x-r, y-r, x+r, y+r), fill='#E1FCFF')
        # Pillow's finite-support blur quantizes to zero away from marks; no ambient/grain.
        glow = marks.filter(ImageFilter.GaussianBlur(max(.6, 3 * scale)))
        image = Image.fromarray(np.minimum(255, np.asarray(image, dtype=np.uint16) +
                               np.asarray(glow, dtype=np.uint16) + np.asarray(marks, dtype=np.uint16)).astype(np.uint8))
        draw = ImageDraw.Draw(image)
        xaxis = self.data['axes']['x']
        text(xaxis['label'] + ' [' + xaxis['unit'] + '] · linear axes · reveal in input order',
             (left, bottom - round(63 * scale)), smallfont)
        legend = ' · '.join(t['label'] for t in self.tracks)
        text(legend, (left, bottom - round(36 * scale)), smallfont)
        text('Source: ' + self.data['provenance']['citation'], (left, bottom - round(9 * scale)), smallfont)
        return image


def render_plots(plots, t, duration, size):
    if len(plots) > 4:
        raise ValueError('a scientific scene supports at most four plots; split the source beats')
    image = Image.new('RGB', size)
    for i, plot in enumerate(plots):
        # Explicit small multiples: no overlay of unrelated units or coordinate domains.
        cols = min(2, len(plots))
        rows = math.ceil(len(plots) / cols)
        x = .06 + (i % cols) * .88 / cols
        y = .055 + (i // cols) * .70 / rows
        layer = plot.frame(t, duration, size, panel=(x, y, x + .88 / cols - .02,
                                                   y + .70 / rows - .02))
        image = Image.fromarray(np.maximum(np.asarray(image), np.asarray(layer)))
    return image

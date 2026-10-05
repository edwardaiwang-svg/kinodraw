"""Palette-aware atmosphere layers for both board and motion frames.

``kinds`` is a name or a back-to-front list of names / dictionaries, e.g.::

    Atmosphere(['night_sky', 'starfield',
                {'kind': 'shooting_star', 'window': (2, 3.5)},
                {'kind': 'fog', 'density': 1.6}], palette, 1., 'lion')

Ambient kinds loop every ``period`` seconds. Shooting stars use absolute scene time and are one-shot;
``loop_period`` is None for a scene containing one. Density multiplies local layer densities. Colours
are RGB triples in [0, 1] or [0, 255], or hex strings. Palette dictionaries override named roles;
sequences supply background, fog/horizon and light colours. rgba() always returns float32 premultiplied
RGBA in [0, 1]. compose() returns float32 RGB in [0, 1], accepting a Pillow frame or NumPy RGB.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
from PIL import Image

from .layers import DEFAULT_PALETTE, KINDS, over, render


def _colour(value):
    if isinstance(value, str):
        value = value.lstrip('#')
        if len(value) == 3:
            value = ''.join(c * 2 for c in value)
        if len(value) != 6:
            raise ValueError('colours must be RGB triples or hex strings')
        value = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    colour = np.asarray(value, np.float32)
    if colour.shape != (3,) or not np.isfinite(colour).all() or (colour < 0).any() or (colour > 255).any():
        raise ValueError('colours must be finite RGB triples in 0..1 or 0..255')
    return colour / 255 if colour.max() > 1 else colour


def _palette(palette):
    out = {key: _colour(value) for key, value in DEFAULT_PALETTE.items()}
    if palette is None:
        return out
    if isinstance(palette, Mapping):
        values = {key: _colour(value) for key, value in palette.items()}
        for key in ('stars', 'glow', 'snow'):
            out[key] = values.get('foreground', out[key])
        for key in ('dust', 'rain', 'embers', 'light_rays', 'dawn_horizon'):
            out[key] = values.get('accent', out[key])
        out.update(values)
    else:
        colours = [_colour(value) for value in palette]
        if not colours:
            raise ValueError('palette cannot be empty')
        out['background'] = out['dawn_top'] = colours[0]
        out['fog'] = out['dawn_horizon'] = colours[min(1, len(colours) - 1)]
        for key in ('stars', 'glow', 'light_rays', 'dust', 'rain', 'embers', 'snow'):
            out[key] = colours[-1]
    return out


def _density(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('density must be finite and nonnegative')
    return value


class Atmosphere:
    def __init__(self, kinds, palette=None, density=1., seed=0, *, period=6., internal_size=(480, 270)):
        self.palette, self.density, self.seed = _palette(palette), _density(density), seed
        self.period = float(period)
        if not math.isfinite(self.period) or self.period <= 0:
            raise ValueError('period must be positive')
        if len(internal_size) != 2 or any(not isinstance(n, int) or n < 1 for n in internal_size):
            raise ValueError('internal_size must be two positive integers')
        self.internal_size = tuple(internal_size)
        if isinstance(kinds, (str, Mapping)):
            kinds = [kinds]
        self.layers = []
        for kind in kinds:
            spec = {'kind': kind} if isinstance(kind, str) else dict(kind)
            name = spec.pop('kind')
            if name not in KINDS:
                raise ValueError(f'unknown atmosphere: {name}')
            allowed = {'density', 'colour'}
            allowed |= {'fog': {'height_falloff'}, 'shooting_star': {'window'}, 'light_rays': {'origin'}}.get(name, set())
            if spec.keys() - allowed:
                raise ValueError(f'unknown {name} options: {spec.keys() - allowed}')
            local_density = _density(spec.pop('density', 1.))
            if 'colour' in spec:
                spec['colour'] = _colour(spec['colour'])
            if 'height_falloff' in spec:
                spec['height_falloff'] = _density(spec['height_falloff'])
            if 'window' in spec:
                a, b = spec['window']
                if not math.isfinite(a) or not math.isfinite(b) or a >= b:
                    raise ValueError('shooting star window must have finite start < end')
            if 'origin' in spec:
                if len(spec['origin']) != 2 or not np.isfinite(spec['origin']).all():
                    raise ValueError('light ray origin must be two finite coordinates')
            self.layers.append((name, local_density, spec))
        self.loop_period = None if any(name == 'shooting_star' for name, _, _ in self.layers) else self.period

    def rgba(self, t, w, h):
        """Render at no more than internal_size, then bilinearly upscale premultiplied channels."""
        if not math.isfinite(t) or not isinstance(w, int) or not isinstance(h, int) or min(w, h) < 1:
            raise ValueError('time must be finite and dimensions must be positive integers')
        scale = min(1., self.internal_size[0] / w, self.internal_size[1] / h)
        iw, ih = max(1, round(w * scale)), max(1, round(h * scale))
        out = None
        for kind, density, options in self.layers:
            local_t = t if kind == 'shooting_star' else t % self.period
            front = render(kind, local_t, iw, ih, self.palette, self.density * density, self.seed, self.period, options)
            out = front if out is None else over(out, front)
        if out is None:
            out = np.zeros((ih, iw, 4), np.float32)
        if (iw, ih) != (w, h):
            out = np.stack([np.asarray(Image.fromarray(out[..., c]).resize((w, h), Image.Resampling.BILINEAR))
                            for c in range(4)], axis=-1)
        return out


def compose(background_rgb, layers, t):
    """Composite atmospheres or premultiplied RGBA arrays, in back-to-front order.

    A renderer can insert its premultiplied content between a sky layer and foreground fog. For an
    overlay, pass its frame as background_rgb. Pillow frames are converted to RGB as in the video
    encoder (the whiteboard returns opaque RGBA). Input frames are never modified.
    """
    if isinstance(background_rgb, Image.Image):
        background_rgb = background_rgb.convert('RGB')
    background = np.asarray(background_rgb)
    if background.ndim != 3 or background.shape[2] != 3:
        raise ValueError('background must be an RGB frame')
    out = background.astype(np.float32, copy=True)
    if background.dtype == np.uint8:
        out /= 255
    if not np.isfinite(out).all() or (out < 0).any() or (out > 1).any():
        raise ValueError('background must be uint8 RGB or floating RGB in 0..1')
    h, w = out.shape[:2]
    if isinstance(layers, Atmosphere):
        layers = [layers]
    for layer in layers:
        front = layer.rgba(t, w, h) if isinstance(layer, Atmosphere) else np.asarray(layer, np.float32)
        if front.shape != (h, w, 4):
            raise ValueError('layers must match the background dimensions and have four channels')
        out = front[..., :3] + out * (1 - front[..., 3:4])
    return out


__all__ = ['Atmosphere', 'compose', 'over']

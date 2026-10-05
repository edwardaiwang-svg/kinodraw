"""Scene joins, also accepting RGB arrays for whiteboard ↔ motion handoffs."""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

from .. import motion as m
from .model import MotionScene, TRANSITIONS
from .render import element_pose, render_frame, shape_points


def _motifs(old, new, old_t, new_t, u, morph):
    before = {e.motif: (i, e) for i, e in enumerate(old.elements) if e.motif and e.kind in {'dot', 'ring', 'line'}}
    a, b = {}, {}
    for j, dest in enumerate(new.elements):
        if dest.motif not in before or dest.kind not in {'dot', 'ring', 'line'}:
            continue
        i, src = before[dest.motif]
        p, q = element_pose(old, src, i, old_t), element_pose(new, dest, j, new_t)
        pose = tuple(m.lerp(x, y, u) for x, y in zip(p, q))
        geometry = None
        if morph:
            points = shape_points(src) * (1 - u) + shape_points(dest) * u
            fill = m.lerp(float(src.kind == 'dot'), float(dest.kind == 'dot'), u)
            geometry = points, fill, 1 - fill
        a[i] = b[j] = (pose, geometry)
    return a, b


def _frame(source, t, w, h, overrides=None):
    if isinstance(source, MotionScene):
        return render_frame(source, t, w, h, _overrides=overrides or None)
    frame = np.asarray(source)
    if frame.shape != (h, w, 3) or frame.dtype != np.uint8:
        raise ValueError('Transition frame must be an RGB uint8 array of the requested size')
    return frame


def _zoom(frame, zoom):
    h, w = frame.shape[:2]
    inv = 1 / zoom
    return np.asarray(Image.fromarray(frame).transform((w, h), Image.AFFINE,
                      (inv, 0, w / 2 * (1 - inv), 0, inv, h / 2 * (1 - inv)), Image.BICUBIC,
                      fillcolor=tuple(int(v) for v in frame[0, 0])))


def render_transition(old, new, t, w=1920, h=1080, *, kind=None, duration=.65, old_t=None, new_t=None):
    """``t`` seconds into a join; scene sample times can be supplied independently.

    Morph interpolates shared geometry; match aligns shared motifs while dissolving their surfaces.
    With an arbitrary RGB endpoint both dissolve instead.
    Endpoints are exact, and the cut is the sole intentional discontinuity.
    """
    kind = kind or (new.transition_in if isinstance(new, MotionScene) else 'morph')
    if kind not in TRANSITIONS or duration <= 0 or not math.isfinite(t):
        raise ValueError('Unknown transition, nonpositive duration or nonfinite time')
    old_t = (old.duration + t if isinstance(old, MotionScene) else t) if old_t is None else old_t
    new_t = t if new_t is None else new_t
    if kind == 'cut':
        return _frame(old if t < 0 else new, old_t if t < 0 else new_t, w, h).copy()
    u = m.clamp01(t / duration)
    if u == 0:
        return _frame(old, old_t, w, h).copy()
    if u == 1:
        return _frame(new, new_t, w, h).copy()
    p = m.cubic_in_out(u)
    a, b = {}, {}
    if kind in {'morph', 'match'} and isinstance(old, MotionScene) and isinstance(new, MotionScene):
        a, b = _motifs(old, new, old_t, new_t, p, kind == 'morph')
    before, after = _frame(old, old_t, w, h, a), _frame(new, new_t, w, h, b)
    if kind == 'wipe':
        alpha = np.asarray(m.wipe_mask((w, h), p, 70, max(1, w / 80)), np.float32) / 255
    elif kind == 'iris':
        alpha = np.asarray(m.iris_mask((w, h), (w / 2, h / 2), math.hypot(w, h) / 2 * p), np.float32) / 255
    else:
        alpha = np.full((h, w), p, np.float32)
        if kind == 'zoom_through':
            before, after = _zoom(before, 1 + .3 * p), _zoom(after, .85 + .15 * p)
    mixed = before.astype(np.float32) * (1 - alpha[..., None]) + after.astype(np.float32) * alpha[..., None]
    return np.clip(mixed + .5, 0, 255).astype(np.uint8)

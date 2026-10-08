"""On-screen text that leaves the frame or lands on other text, measured from the renderer's own layout.

``problems(prod)`` samples a production (whiteboard render.Production or hybrid.HybridProduction) every ``step``
seconds and returns one finding per piece of text that is clipped by a frame edge, or that overlaps another piece of
text on screen at the same moment: {'t', 'defect': 'text_clipped'|'text_overlap', 'text', 'other'}. Finish turns
them into QA problems: a video never passes with words cut off or written over words.
"""
from __future__ import annotations

import math

EDGE = 2            # px a glyph box may touch beyond the frame (anti-aliasing)
OVERLAP = .2        # share of the smaller box two texts may share before they count as written over each other


def _area(box):
    return max(0., box[2] - box[0]) * max(0., box[3] - box[1])


def _shared(a, b):
    box = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return _area(box) / max(1., min(_area(a), _area(b)))


def _words(drawing) -> str:
    lines = getattr(drawing, 'lines', None)
    if lines:
        return ' '.join(lines)
    return getattr(drawing, 'words', '') or type(drawing).__name__


def whiteboard_boxes(prod, t):
    """(screen box, words) of every text the whiteboard shows at ``t`` (the ink of its glyphs, not its padding)."""
    from ..engine import ink
    L = prod.camera.at(t) + prod._drift(t)
    moving = abs(prod.camera.at(t + .05) - prod.camera.at(t)) > .5
    out = []
    for e in prod.els:
        if e.start > t:
            break
        drawing = e.drawing
        if not (isinstance(drawing, ink.TextDrawing) or getattr(drawing, 'words', None)):
            continue
        if isinstance(drawing, ink.TextDrawing) and not prod.text_visible(e, t, L):
            continue                                 # culled whole before a camera move could clip it
        img, _, _ = e.state(t)
        if img is None:
            continue
        bbox = getattr(drawing, 'ink', img).getbbox() if isinstance(drawing, ink.TextDrawing) else img.getbbox()
        if not bbox:
            continue
        box = (e.x - L + bbox[0], e.y + bbox[1], e.x - L + bbox[2], e.y + bbox[3])
        if box[2] <= 0 or box[0] >= prod.size[0] or moving and (box[0] < 0 or box[2] > prod.size[0]):
            continue                                 # off this screen, or crossing it during a camera move
        out.append((box, _words(drawing)))
    return out


def motion_boxes(scene, local, size):
    """(screen box, words) of every text element of a motion scene at its local time ``local``."""
    from ..engine.bold import render as bold
    W, H = size
    out = []
    for i, e in enumerate(scene.elements):
        if e.kind != 'text' or not e.text or local < e.start or (e.end is not None and local >= e.end):
            continue
        x, y, scale, alpha = bold.element_pose(scene, e, i, local)
        if alpha < .5:
            continue
        text, font, size_px, spacing = bold._text_metrics(e.text, e.size, e.width, e.preset == 'corner_caption',
                                                          e.font)
        lines = text.split('\n')
        widest = max((bold._advance(font, line, e.font) + spacing * max(0, len(line) - 1) for line in lines),
                     default=0) * size_px / font.size
        half_w = widest / 2 * scale
        top = y + ((0 - (len(lines) - 1) / 2) * size_px * 1.15 - size_px * .75) * scale
        bottom = y + (((len(lines) - 1) / 2) * size_px * 1.15 + size_px * .25) * scale
        sx, sy = W / bold.W, H / bold.H
        out.append(((( x - half_w) * sx, top * sy, (x + half_w) * sx, bottom * sy), e.text.replace('\n', ' ')))
    return out


def _check(t, boxes, size, found, seen):
    W, H = size
    for k, (box, words) in enumerate(boxes):
        if (box[0] < -EDGE or box[1] < -EDGE or box[2] > W + EDGE or box[3] > H + EDGE) and \
                ('text_clipped', words) not in seen:
            seen.add(('text_clipped', words))
            found.append({'t': round(t, 2), 'defect': 'text_clipped', 'text': words, 'other': ''})
        for other, words2 in boxes[k + 1:]:
            if words2 != words and _shared(box, other) > OVERLAP and ('text_overlap', words, words2) not in seen:
                seen.add(('text_overlap', words, words2))
                found.append({'t': round(t, 2), 'defect': 'text_overlap', 'text': words, 'other': words2})


def problems(prod, step: float = .5) -> list[dict]:
    """Clipped or overlapping on-screen text in ``prod`` (see the module docstring)."""
    if hasattr(prod, 'prod') or getattr(prod, 'vertical', False):
        return []                                    # a portrait frame lays the board out again (vertical.py)
    size = tuple(prod.size)
    duration = prod.duration if hasattr(prod, 'duration') else prod.tl['duration']
    board = getattr(prod, 'whiteboard', prod)
    spans = getattr(prod, 'spans', None)
    found, seen = [], set()
    for k in range(int(math.floor(duration / step))):
        t = k * step
        span = None
        if spans:
            import bisect
            i = bisect.bisect_right(prod.starts, t) - 1
            span = prod.spans[i] if i >= 0 and t < prod.tl['end_card']['start'] else None
        if span is not None and span.motion is not None and span.story is None and not span.source_proof \
                and span.spec['treatment'] != 'whiteboard' and not span.scientific:
            boxes = motion_boxes(span.motion, t - span.start, size)
        elif span is not None and span.story is not None:
            continue                                 # picture-book pages carry no laid-out text but bubbles
        else:
            boxes = whiteboard_boxes(board, t)
        _check(t, boxes, size, found, seen)
    return found

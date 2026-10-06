"""Literal bar, line and number graphics, all evaluated at the requested time."""
from __future__ import annotations

import math
from html import escape

from .. import motion


def counter_value(element, t):
    duration = element.duration or 1.8
    return motion.Track([(element.start, element.value_from),
                         (element.start + duration, element.value_to)]).value(t)


def counter_text(element, t):
    decimals = element.decimals
    if decimals is None:
        step = abs(element.value_to - element.value_from) / ((element.duration or 1.8) * 30)
        decimals = min(6, max(0, math.ceil(-math.log10(step)))) if step else 0
    return f'{counter_value(element, t):,.{decimals}f}{element.suffix}'


def chart_svg(element, t, color, foreground):
    """Artwork and sharp labels as two SVG fragments, centred at the origin."""
    w, h = element.width, element.height
    values = element.values
    if not values:
        return '', ''
    low, high = min(0, min(values)), max(0, max(values))
    span = max(high - low, 1e-9)
    baseline = h / 2 + low / span * h
    art = f'<path d="M{-w / 2} {baseline} h{w}" stroke="{foreground}" opacity=".25"/>'
    labels = ''
    points = []
    for i, value in enumerate(values):
        delay = i * min(.09, .3 / max(1, len(values) - 1))
        p = motion.expo_out((t - element.start - delay) / (element.duration or .65))
        x = -w / 2 + (i + .5) * w / len(values)
        y = baseline - value / span * h * p
        if element.chart == 'bar':
            bw = w / len(values) * .6
            art += (f'<rect x="{x - bw / 2}" y="{min(y, baseline)}" width="{bw}" height="{abs(baseline - y)}" '
                    f'rx="5" fill="{color}" opacity="{.5 + .5 * i / max(1, len(values) - 1)}"/>')
        else:
            points.append((x, y))
            art += f'<circle cx="{x}" cy="{y}" r="5" fill="{color}" opacity="{p}"/>'
        if element.suffix:
            # Literal endpoint labels remain readable while the bars enter.
            labels += (f'<text x="{x}" y="{baseline - value / span * h - 16}" font-size="32" '
                       f'text-anchor="middle" fill="{foreground}">{escape(str(value).removesuffix(".0") + element.suffix)}</text>')
        if i < len(element.labels):
            labels += (f'<text x="{x}" y="{h / 2 + 38}" font-size="22" text-anchor="middle" '
                       f'fill="{foreground}">{escape(element.labels[i])}</text>')
    if points:
        path = ' '.join(f'{"M" if i == 0 else "L"}{x} {y}' for i, (x, y) in enumerate(points))
        art += f'<path d="{path}" fill="none" stroke="{color}" stroke-width="5" stroke-linejoin="round"/>'
    return art, labels

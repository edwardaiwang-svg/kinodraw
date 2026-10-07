"""Small 2-D rig helpers: vectors, rotations, two-bone IK and frames."""
from __future__ import annotations

import math

import numpy as np


def V(x, y=None):
    if y is None:
        return np.array(x, float)
    return np.array([x, y], float)


def deg(a):
    return math.radians(a)


def rot(p, a):
    """Rotate vector ``p`` by ``a`` radians (counter-clockwise, y up)."""
    c, s = math.cos(a), math.sin(a)
    return V(p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def ang(p):
    return math.atan2(p[1], p[0])


def unit(a):
    return V(math.cos(a), math.sin(a))


def two_bone(root, target, l1, l2, bend):
    """Middle joint and clamped end of a two-bone chain. ``bend`` +1 puts the joint on the
    counter-clockwise side of root -> target (forward for a leg hanging down, facing +x)."""
    root, target = V(root), V(target)
    d = target - root
    dist = float(np.hypot(*d))
    direction = d / dist if dist > 1e-9 else V(0, -1)
    reach = max(min(dist, (l1 + l2) * 0.999), abs(l1 - l2) + 1e-3)
    end = root + direction * reach
    a = (l1 * l1 - l2 * l2 + reach * reach) / (2 * reach)
    h = math.sqrt(max(0.0, l1 * l1 - a * a))
    perp = V(-direction[1], direction[0]) * bend
    return root + direction * a + perp * h, end


class Frame:
    """Local frame: origin, rotation and uniform scale (a head, a hand, a cub)."""

    def __init__(self, origin, angle=0.0, scale=1.0, mirror=False):
        self.o, self.a, self.s, self.m = V(origin), float(angle), float(scale), mirror

    def __call__(self, x, y=None):
        p = V(x, y) if y is not None else V(x)
        if self.m:
            p = V(-p[0], p[1])
        return self.o + rot(p, self.a) * self.s

    def r(self, r):
        return r * self.s

    def ang(self, a):
        return (math.pi - a if self.m else a) + self.a


def chain(start, angle, seg, n, curl, curl_growth=0.0):
    """Points of a curling chain (tails, trunks): ``angle`` and ``curl`` in radians."""
    pts = [V(start)]
    a = angle
    for i in range(n):
        pts.append(pts[-1] + unit(a) * seg)
        a += curl * (1 + curl_growth * i)
    return pts

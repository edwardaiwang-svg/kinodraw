"""What appears on a collage stage and how it moves.

Pieces pop or slam in with a shadow that lifts while they are in the air, then hold with a stop-motion jitter on
twos; cards type their text; numbers count; lines draw themselves; confetti bursts; a hand taps. Every element knows
its beat and when it starts and ends (pacing uses that) and the sound cues it makes. Randomness is keyed by the
element's id and the frame number, so parallel render workers draw identical frames.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .. import ink, motion

FPS = 30
SHADOW = (6, 9)                     # resting shadow offset; it grows while a piece is in the air


class Element:
    layer = 1
    words = ''                      # the words it shows, if it is text (the layout check keeps text off other text)

    def __init__(self, t0: float, beat: str | None = None, ident: str = '', until: float | None = None):
        self.start, self.end, self.beat, self.ident, self.until = t0, t0 + .3, beat, ident, until
        self.skipped, self.fixed = False, False

    def gone(self, t):
        return self.until is not None and t >= self.until + .25

    def fade_out(self, t):
        return 1. if self.until is None or t < self.until else motion.clamp01(1 - (t - self.until) / .25)

    def draw(self, canvas: Image.Image, t: float):
        raise NotImplementedError

    def cues(self) -> list[dict]:
        return []


class Piece(Element):
    """A sticker, card or label that enters at ``t0`` (pop, slam, slide, drop or fade) and stays until ``until``."""

    def __init__(self, img, x, y, t0, beat=None, ident='', enter='pop', energy=1, tilt=0., scale=1., jitter=True,
                 until=None, cue='pop', shadow=True, layer=1, words=''):
        super().__init__(t0, beat, ident, until)
        self.x, self.y, self.enter, self.energy, self.tilt, self.scale = x, y, enter, energy, tilt, scale
        self.jitter, self.cue, self.layer, self.words = jitter, cue, layer, words
        self.sprite = motion.Sprite(img)
        self.shadow = motion.Sprite(motion.shadow_only(img, blur=9, opacity=.3)) if shadow else None
        self.end = t0 + {'slam': .2, 'slide': .45, 'drop': .5}.get(enter, .3)

    def state(self, t):
        """(scale, alpha, lift, dx, dy, extra rotation) at ``t``."""
        dt = t - self.start
        scale, alpha, lift, dx, dy, rot = 1., 1., 0., 0., 0., 0.
        if self.enter == 'pop':
            p = motion.pop(t, self.start, overshoot=.14 if self.energy >= 2 else .08)
            scale, alpha, lift = p['scale'], p['alpha'], p['lift']
        elif self.enter == 'slam':
            p = motion.slam(t, self.start)
            scale, alpha = p['scale'], p['alpha']
        elif self.enter == 'slide':
            u = motion.expo_out(motion.clamp01(dt / .45))
            dx, alpha = 520 * (1 - u), motion.clamp01(dt / .15)
        elif self.enter == 'drop':
            u = motion.clamp01(dt / .5)
            dy, alpha, lift = -380 * (1 - motion.back_out(u, 1.2)), motion.clamp01(dt / .12), .6 * (1 - u)
        else:                                          # fade
            alpha = motion.clamp01(dt / .3)
        if self.jitter and dt > self.end - self.start:  # stop-motion hold: one of three poses, changing on twos
            rng = motion.seeded(self.ident, int(t * FPS) // 2 % 3)
            rot, dx, dy = rot + rng.uniform(-.7, .7), dx + rng.uniform(-1.2, 1.2), dy + rng.uniform(-1.2, 1.2)
        return scale, alpha * self.fade_out(t), lift, dx, dy, rot

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        scale, alpha, lift, dx, dy, rot = self.state(t)
        if scale <= 0 or alpha <= 0:
            return
        x, y = self.x + dx, self.y + dy
        if self.shadow is not None:
            self.shadow.draw(canvas, x + SHADOW[0] + 10 * lift, y + SHADOW[1] + 16 * lift, scale=self.scale * scale,
                             rotation=self.tilt + rot, alpha=alpha)
        self.sprite.draw(canvas, x, y, scale=self.scale * scale * (1 + .04 * lift), rotation=self.tilt + rot,
                         alpha=alpha)

    def cues(self):
        if not self.cue:
            return []
        strength = {0: .35, 1: .55, 2: .8}.get(self.energy, 1.)
        return [{'t': round(self.start, 4), 'kind': self.cue, 'strength': strength, 'id': self.ident,
                 'x': round(min(max(self.x / 1920, 0), 1), 3)}]


class Swap(Element):
    """One picture that changes at given times (a traffic light, a pressed button, a badge): [(t, image), ...]."""

    def __init__(self, frames, x, y, beat=None, ident='', until=None, shadow=True, cue='tap'):
        super().__init__(frames[0][0], beat, ident, until)
        self.frames, self.x, self.y, self.cue = frames, x, y, cue
        self.pieces = [Piece(img, x, y, t, beat, f'{ident}.{k}', enter='pop' if k == 0 else 'fade', shadow=shadow,
                             cue=None, jitter=True, until=until) for k, (t, img) in enumerate(frames)]
        for k, piece in enumerate(self.pieces[1:], 1):
            piece.state = self._snap(piece)
        self.end = frames[-1][0] + .3

    @staticmethod
    def _snap(piece):
        base = Piece.state

        def state(t):                                  # later states replace the picture at once (no fade-in)
            scale, alpha, lift, dx, dy, rot = base(piece, t)
            return scale, (1. if t >= piece.start else 0.) * piece.fade_out(t), lift, dx, dy, rot
        return state

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        current = max((p for p in self.pieces if p.start <= t), key=lambda p: p.start)
        current.draw(canvas, t)

    def cues(self):
        first = self.pieces[0]
        return [{'t': round(first.start, 4), 'kind': 'pop', 'strength': .55, 'id': self.ident}] + \
            [{'t': round(p.start, 4), 'kind': self.cue, 'strength': .6, 'id': p.ident} for p in self.pieces[1:]] \
            if self.cue else []


class Typed(Element):
    """A card whose text types itself: ``render(n)`` returns the card showing the first ``n`` characters."""

    def __init__(self, render, text, x, y, t0, beat=None, ident='', cps=22., enter_at=None, until=None, words=None):
        start = enter_at if enter_at is not None else t0 - .35
        super().__init__(start, beat, ident, until)
        self.render, self.text, self.x, self.y, self.t0, self.cps = render, text, x, y, t0, cps
        self.words = text if words is None else words
        self.cache: dict = {}
        self.end = t0 + len(text) / cps
        self.card = Piece(render(0), x, y, start, beat, ident + '.card', enter='pop', cue='paper', until=until)

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        n = motion.typewriter(self.text, t, self.t0, self.cps)
        if n == 0 or t < self.card.end:
            self.card.draw(canvas, t)
            return
        if n not in self.cache:
            self.cache[n] = motion.Sprite(self.render(n))
        _, alpha, _, dx, dy, rot = self.card.state(t)
        self.card.shadow.draw(canvas, self.x + dx + SHADOW[0], self.y + dy + SHADOW[1], rotation=self.card.tilt + rot,
                              alpha=alpha)
        self.cache[n].draw(canvas, self.x + dx, self.y + dy, rotation=self.card.tilt + rot, alpha=alpha)

    def cues(self):
        typing = [{'t': round(self.t0 + k / self.cps, 4), 'kind': 'type', 'strength': .45, 'id': f'{self.ident}.{k}'}
                  for k in range(len(self.text)) if not self.text[k].isspace()]
        return self.card.cues() + typing


class Counter(Element):
    """A number that rolls from ``a`` to ``b`` over ``dur`` seconds (``render(n)`` draws it), with a tick per step."""

    def __init__(self, render, a, b, x, y, t0, dur=.8, beat=None, ident='', until=None):
        super().__init__(t0, beat, ident, until)
        self.render, self.a, self.b, self.x, self.y, self.dur = render, a, b, x, y, dur
        self.sprites: dict = {}
        self.end = t0 + dur

    def value(self, t):
        return round(motion.lerp(self.a, self.b, motion.expo_out(motion.clamp01((t - self.start) / self.dur))))

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        n = self.value(t)
        if n not in self.sprites:
            self.sprites[n] = motion.Sprite(self.render(n))
        grow = 1 + .12 * math.sin(math.pi * motion.clamp01((t - self.start) / self.dur))
        self.sprites[n].draw(canvas, self.x, self.y, scale=grow, alpha=self.fade_out(t))

    def cues(self):
        steps = sorted({self.value(self.start + k / FPS) for k in range(int(self.dur * FPS) + 1)})
        times = {}
        for k in range(int(self.dur * FPS) + 1):
            times.setdefault(self.value(self.start + k / FPS), self.start + k / FPS)
        return [{'t': round(times[v], 4), 'kind': 'type', 'strength': .4, 'id': f'{self.ident}.{v}'} for v in steps[1:]]


class Stroke(Element):
    """A hand-drawn line that draws itself over ``dur`` seconds (an oval around a word, an underline, burst lines),
    boiling slightly on twos like a hand-drawn animation."""

    def __init__(self, points, t0, dur=.6, color=(27, 27, 27), width=7, beat=None, ident='', until=None, boil=1.4):
        super().__init__(t0, beat, ident, until)
        self.points, self.dur, self.color, self.width, self.boil = points, dur, color, width, boil
        self.end = t0 + dur

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        u = motion.expo_out(motion.clamp01((t - self.start) / self.dur))
        k = max(2, round(len(self.points) * u))
        rng = motion.seeded(self.ident, int(t * FPS) // 2 % 3)
        pts = [(x + rng.uniform(-self.boil, self.boil), y + rng.uniform(-self.boil, self.boil)) for x, y in self.points[:k]]
        alpha = round(255 * self.fade_out(t))
        ImageDraw.Draw(canvas).line(pts, fill=(*self.color, alpha), width=self.width, joint='curve')

    def cues(self):
        return [{'t': round(self.start, 4), 'kind': 'write', 'strength': .4, 'id': self.ident, 'dur': self.dur}]


def wobbly_ellipse(cx, cy, rx, ry, seed_key, turns=1.08, n=90):
    """Points of a hand-drawn oval: slightly more than one turn, with a wandering radius."""
    rng = motion.seeded(seed_key)
    phase = rng.uniform(0, 2 * math.pi)
    wob = [rng.uniform(-.05, .05) for _ in range(5)]
    pts = []
    for i in range(n):
        a = phase + 2 * math.pi * turns * i / (n - 1)
        r = 1 + sum(w * math.sin((j + 2) * a) for j, w in enumerate(wob))
        pts.append((cx + rx * r * math.cos(a), cy + ry * r * math.sin(a)))
    return pts


def burst_lines(cx, cy, r0, r1, n, seed_key):
    """Short radiating strokes around a point, as [(p0, p1), ...]."""
    rng = motion.seeded(seed_key)
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-.12, .12)
        a0, a1 = r0 * rng.uniform(.95, 1.08), r1 * rng.uniform(.9, 1.1)
        out.append(((cx + a0 * math.cos(a), cy + a0 * math.sin(a)), (cx + a1 * math.cos(a), cy + a1 * math.sin(a))))
    return out


class Burst(Element):
    """Radiating lines that pop out around a point (for a reveal or a logo)."""

    def __init__(self, cx, cy, t0, r0=180, r1=240, n=14, color=(255, 255, 255), beat=None, ident='', until=None):
        super().__init__(t0, beat, ident, until)
        self.lines, self.color = burst_lines(cx, cy, r0, r1, n, ident), color
        self.end = t0 + .35

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        u = motion.back_out(motion.clamp01((t - self.start) / .35))
        d = ImageDraw.Draw(canvas)
        alpha = round(230 * self.fade_out(t))
        for (x0, y0), (x1, y1) in self.lines:
            d.line([(x0, y0), (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)], fill=(*self.color, alpha), width=6)


class Confetti(Element):
    """A deterministic confetti burst from ``origin`` at ``t0``."""

    def __init__(self, origin, t0, n=180, beat=None, ident='', spread=900):
        super().__init__(t0, beat, ident)
        self.origin, self.n, self.spread = origin, n, spread
        self.end = t0 + 2.4

    def draw(self, canvas, t):
        if t < self.start or t > self.start + 3.5:
            return
        d = ImageDraw.Draw(canvas)
        for x, y, angle, w, h, color, alpha in motion.confetti(self.ident, self.n, self.origin, t - self.start,
                                                               spread=self.spread):
            if alpha <= 0:
                continue
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            pts = [(x + dx * c - dy * s, y + dx * s + dy * c) for dx, dy in
                   ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
            d.polygon(pts, fill=(*color[:3], round(255 * alpha)))

    def cues(self):
        return [{'t': round(self.start, 4), 'kind': 'confetti', 'strength': .8, 'id': self.ident}]


def _pen_ends(drawing):
    """Where the pen first touches and last leaves an ink drawing (in its own pixels)."""
    if hasattr(drawing, 'polys'):
        return tuple(drawing.polys[0][0]), tuple(drawing.polys[-1][-1])
    return tuple(drawing.points[0]), tuple(drawing.points[-1])


class Ink(Element):
    """Pictures and words drawn by the drawing hand, one after another: ``items`` = [(drawing, x, y, t0), ...] with
    each ink drawing (a doodle or handwriting) centred on (x, y). Between drawings the hand glides over, lifted.
    ``then`` (an image) pops in over the last drawing once it is done: a written name becoming a paper sticker."""
    layer = 2

    def __init__(self, items, hand, beat=None, ident='', until=None, then=None, words=''):
        super().__init__(items[0][3], beat, ident, until)
        self.items, self.hand, self.words = items, hand, words
        self.end = max(t0 + d.duration for d, _, _, t0 in items)
        last = items[-1]
        self.then = None if then is None else Piece(then, last[1], last[2], last[3] + last[0].duration, beat,
                                                    ident + '.then', energy=2, cue=None, jitter=False, until=until)

    def _origin(self, k):
        d, x, y, _ = self.items[k]
        return x - d.size[0] / 2, y - d.size[1] / 2

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        alpha = self.fade_out(t)
        for k, (d, _, _, t0) in enumerate(self.items):
            if t < t0 or (self.then is not None and k == len(self.items) - 1 and t >= self.then.start + .3):
                continue
            img, _, _ = d.state(t - t0)
            if img is not None:
                ox, oy = self._origin(k)
                ink.paste(canvas, img if alpha >= 1 else motion._fade(img, alpha), ox, oy)
        if self.then is not None:
            self.then.draw(canvas, t)
        pen = self.pen(t)
        if pen is not None:
            self.hand.paste(canvas, pen[:2], lifted=not pen[2])

    def pen(self, t):
        """(x, y, down) of the hand on the canvas at ``t``, or None when it is not drawing."""
        for k, (d, _, _, t0) in enumerate(self.items):
            ox, oy = self._origin(k)
            if t0 <= t < t0 + d.duration:
                _, point, down = d.state(t - t0)
                return None if point is None else (ox + point[0], oy + point[1], down)
            nxt = self.items[k + 1] if k + 1 < len(self.items) else None
            if nxt is not None and t0 + d.duration <= t < nxt[3]:       # gliding to the next drawing
                (_, a), (b, _) = _pen_ends(d), _pen_ends(nxt[0])
                nx, ny = self._origin(k + 1)
                u = motion.cubic_in_out((t - t0 - d.duration) / max(1e-6, nxt[3] - t0 - d.duration))
                return (ox + a[0] + (nx + b[0] - ox - a[0]) * u, oy + a[1] + (ny + b[1] - oy - a[1]) * u, False)
        return None

    def cues(self):
        out = [{'t': round(t0, 4), 'kind': 'write', 'strength': .5, 'id': f'{self.ident}.{k}',
                'dur': round(d.duration, 3)} for k, (d, _, _, t0) in enumerate(self.items)]
        return out + ([{'t': round(self.then.start, 4), 'kind': 'pop', 'strength': .8, 'id': self.then.ident}]
                      if self.then is not None else [])


class Board(Element):
    """A whiteboard panel that grows from ``box_a`` to ``box_b`` (x0, y0, x1, y1) over ``dur`` seconds from ``t0``."""

    def __init__(self, box_a, box_b, t0, dur=.45, beat=None, ident='', until=None, fill=(253, 252, 248)):
        super().__init__(t0, beat, ident, until)
        self.a, self.b, self.dur, self.fill = box_a, box_b, dur, fill
        self.end = t0 + dur

    def box(self, t):
        u = motion.expo_out(motion.clamp01((t - self.start) / self.dur))
        return tuple(a + (b - a) * u for a, b in zip(self.a, self.b))

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        x0, y0, x1, y1 = self.box(t)
        alpha = round(255 * self.fade_out(t))
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((x0 + 6, y0 + 9, x1 + 6, y1 + 9), 14, fill=(0, 0, 0, round(alpha * .16)))
        d.rounded_rectangle((x0, y0, x1, y1), 14, fill=(*self.fill, alpha), outline=(207, 198, 180, alpha), width=4)

    def cues(self):
        return [{'t': round(self.start, 4), 'kind': 'whoosh', 'strength': .5, 'id': self.ident}]


class Tap(Element):
    """A pointing hand that glides in, presses a target at ``t0`` (with a ripple) and rests."""

    def __init__(self, hand_img, target, t0, beat=None, ident='', until=None):
        super().__init__(t0 - .45, beat, ident, until)
        self.hand, self.target, self.t0 = motion.Sprite(hand_img, anchor=(.42, .08)), target, t0
        self.shadow = motion.Sprite(motion.shadow_only(hand_img, blur=8, opacity=.28), anchor=(.42, .08))
        self.end = t0 + .3

    def draw(self, canvas, t):
        if t < self.start or self.gone(t):
            return
        tx, ty = self.target
        u = motion.expo_out(motion.clamp01((t - self.start) / .45))
        x, y = tx + 240 * (1 - u), ty + 260 * (1 - u)
        press = .9 if 0 <= t - self.t0 < .14 else 1.
        alpha = motion.clamp01((t - self.start) / .15) * self.fade_out(t)
        if 0 <= t - self.t0 < .45:                   # the ripple
            r = 20 + 90 * motion.expo_out((t - self.t0) / .45)
            a = round(200 * (1 - (t - self.t0) / .45) * alpha)
            ImageDraw.Draw(canvas).ellipse([tx - r, ty - r, tx + r, ty + r], outline=(255, 255, 255, a), width=6)
        self.shadow.draw(canvas, x + 8, y + 12, scale=press, alpha=alpha)
        self.hand.draw(canvas, x, y, scale=press, alpha=alpha)

    def cues(self):
        return [{'t': round(self.t0, 4), 'kind': 'tap', 'strength': .7, 'id': self.ident}]

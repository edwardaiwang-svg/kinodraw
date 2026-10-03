"""The collage look: paper stages, die-cut stickers, a paper puppet and promo scenes, rendered by rules.

It answers what every renderer answers (frame, warnings, ctx.elements, cues), so pacing, parallel rendering,
stills, the mix and packaging treat it like the whiteboard.
"""
from __future__ import annotations

import bisect
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from .. import captions as cap
from .. import ink, motion
from . import plan, product, promo, puppet

W, H = 1920, 1080
FPS = 30
TRANS = .5                          # a stage change lasts this long
PUPPET_X, PUPPET_Y, PUPPET_H = 330, 1010, 560
SHOWPIECES = {'calm': 0, 'lively': 2, 'showreel': 5}
PUSH = {'calm': 0., 'lively': .02, 'showreel': .04}
PUNCH = {'calm': 0., 'lively': .045, 'showreel': .07}
BUILDERS = {**promo.BUILDERS, **product.BUILDERS}


class CollageProduction:
    def __init__(self, episode, tline, lang, project_dir, relaxed=False):
        self.ep, self.tl, self.lang, self.dir, self.relaxed = episode, tline, lang, Path(project_dir), relaxed
        self.dial = episode.get('motion', 'lively')
        self.seed = int(hashlib.sha1(episode['title'][lang].encode()).hexdigest()[:8], 16)
        self.warnings: list[str] = []
        self._beats = {b['id']: b for b in episode['beats']}
        self._cues: list[dict] = []
        self._poses: dict = {}
        self._showpieces: list[float] = []
        self._backgrounds: dict = {}
        self._puppets: dict = {}
        self.puppet_look = (episode.get('puppet') or {}).get('preset', 'sunny')
        self.puppet_colors = tuple(sorted(((episode.get('puppet') or {}).get('colors') or {}).items()))
        if any(b.get('direction') for b in episode['beats']):    # fit the energies to the real narration timing
            from ...director.annotate import plan as fit_energy
            episode = copy.deepcopy(episode)
            fit_energy(episode, tline)
            self.ep = episode
        self.said = plan.sentences(episode, tline, lang)
        self.stages = plan.stages(self.said, tline)
        self.brand = promo.brand_of(self)
        if self.stages and self.stages[-1].kind == 'end' and SHOWPIECES.get(self.dial, 2):
            self._showpieces.append(tline['end_card']['start'])    # the finale's showpiece comes first
        self.stage_els, self.els = [], []
        for k, st in enumerate(self.stages):
            self._current = k
            els = BUILDERS.get(st.kind, promo.stickers_stage)(self, st)
            els.sort(key=lambda e: (e.layer, e.start))
            self.stage_els.append(els)
            self.els += els
            if k and st.transition != 'none':
                self.cue('whoosh' if st.transition == 'slide' else 'paper', st.start, strength=.7)
        self.ctx = SimpleNamespace(elements=self.els)
        self.starts = [st.start for st in self.stages]
        self.show_captions = bool(episode.get('captions', False))
        self.cap_starts = [c['start'] for c in tline.get('captions', [])]

    # ------------------------------------------------------------ used by the stage builders
    def beat(self, beat_id):
        return self._beats[beat_id]

    def word_time(self, s, phrase):
        """When ``phrase`` (found in the sentence's display text) is heard; the sentence start if it isn't there."""
        i = s.text.lower().find(phrase.lower())
        if i < 0:
            return s.start
        beat = self._beats[s.beat]
        return plan.word_time(beat, self.tl['beats'][s.beat], self.lang, s.span[0] + i)

    def pose(self, stage, keys):
        self._poses[id(stage)] = sorted(keys, key=lambda k: k[0])

    def cue(self, kind, t, strength=.7, dur=None):
        c = {'t': round(max(0., t), 4), 'kind': kind, 'strength': strength, 'id': f'{kind}.{len(self._cues)}'}
        if dur:
            c['dur'] = dur
        self._cues.append(c)

    def allow_showpiece(self, t):
        """Confetti and other showpieces: as many as the Motion dial allows, at least 12 s apart (the end card's
        is reserved first)."""
        if t in self._showpieces:
            return True
        if len(self._showpieces) >= SHOWPIECES.get(self.dial, 2) or any(abs(t - x) < 12 for x in self._showpieces):
            return False
        self._showpieces.append(t)
        return True

    def brand_tag(self, stage, els):
        """The brand's small word mark in the top left corner of the how-it-works and later stages."""
        name = self.brand.get('name')
        if name:
            img = promo._hero(self, name, size=54)
            els.append(promo.Piece(img, 40 + img.width / 2, 34 + img.height / 2, stage.start + .25,
                                   ident=f'tag.{self._current}', cue=None, jitter=False))

    # ------------------------------------------------------------ frames
    def frame(self, t):
        k = max(0, bisect.bisect_right(self.starts, t) - 1)
        img = self._stage_frame(k, t)
        st = self.stages[k]
        if k and st.transition != 'none' and t < st.start + TRANS:
            img = self._transition(self._stage_frame(k - 1, t), img, st.transition, (t - st.start) / TRANS,
                                   f'{self.seed}.{k}')
        if self.show_captions:
            self._caption(img, t)
        return img.convert('RGB')

    def _stage_frame(self, k, t):
        st = self.stages[k]
        canvas = self._background(st.background).copy()
        for e in self.stage_els[k]:
            if e.start <= t:
                e.draw(canvas, t)
        self._puppet(canvas, st, t)
        zoom = self._zoom(k, t)
        if zoom > 1.001:
            cw, ch = W / zoom, H / zoom
            box = ((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)
            canvas = canvas.resize((W, H), Image.BILINEAR, box=box)
        return canvas

    def _background(self, kind):
        """The stage's paper with a soft vignette. 'sky' is cream paper under a light blue watercolour sky: tinted
        from the top, with a trace of the wash's mottling."""
        if kind not in self._backgrounds:
            yy, xx = np.mgrid[0:H, 0:W]
            arr = np.asarray(motion.paper_texture((W, H), 'cream' if kind == 'sky' else kind, seed_key=self.seed),
                             np.float32).copy()
            if kind == 'sky':
                wash = np.asarray(motion.paper_texture((W, H), 'blue_wash', seed_key=self.seed), np.float32)
                cream = np.asarray(motion.paper_texture((W, H), 'cream', seed_key=self.seed), np.float32)
                u = (yy / H)[..., None]
                sky = np.array([148, 188, 226]) * (1 - u) + np.array([206, 230, 232]) * u
                strength = (.62 - .42 * u)
                arr = arr * (1 - strength) + sky * strength + .22 * (wash - cream)
            d = np.sqrt(((xx - W / 2) / (W * .62)) ** 2 + ((yy - H / 2) / (H * .62)) ** 2)
            arr *= np.clip(1 - .16 * np.clip(d - .55, 0, None) ** 1.4, 0, 1)[..., None]
            rgb = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB')
            self._backgrounds[kind] = rgb.convert('RGBA')
        return self._backgrounds[kind]

    def _zoom(self, k, t):
        """A slow push-in over the stage, and a punch-in on each energetic sentence (none when calm)."""
        st = self.stages[k]
        span = max(1., st.end - st.start)
        z = 1 + PUSH.get(self.dial, .02) * motion.clamp01((t - st.start) / span)
        for s in st.sentences:
            if s.energy >= 2 and s.start <= t < s.start + 1.6:
                u = t - s.start
                z += PUNCH.get(self.dial, .045) * (motion.expo_out(u / .22) if u < .22 else
                                                   1 - motion.cubic_in_out((u - .22) / 1.38))
        return z

    def _puppet(self, canvas, st, t):
        keys = self._poses.get(id(st))
        if not keys or t < keys[0][0]:
            return
        _, pose, expression = keys[bisect.bisect_right([k[0] for k in keys], t) - 1]
        frame = int(t * FPS) // 2 % 4 if pose in ('walk', 'wave') else 0
        key = (pose, expression, frame)
        if key not in self._puppets:
            img = puppet.raster(pose, expression, frame, self.puppet_look, self.puppet_colors, height=PUPPET_H)
            cut = motion.die_cut(img, border=12)
            feet = np.nonzero(np.asarray(cut.getchannel('A')).any(axis=1))[0].max()    # the lowest visible row
            self._puppets[key] = (motion.Sprite(cut, anchor=(.5, feet / cut.height)),
                                  motion.Sprite(motion.shadow_only(cut, blur=10, opacity=.3), anchor=(.5, .5)))
        sprite, shadow = self._puppets[key]
        breath = 1 + .006 * ((int(t * FPS) // 2) % 3 - 1)            # a slight stop-motion breath on twos
        first = keys[0][0]
        pop = motion.pop(t, first) if t < first + .3 else {'scale': 1, 'alpha': 1, 'lift': 0}
        s = pop['scale'] * breath
        cy = PUPPET_Y - sprite.img.height * sprite.anchor[1] + sprite.img.height / 2
        shadow.draw(canvas, PUPPET_X + 8, cy + 10, scale=s, alpha=pop['alpha'])
        sprite.draw(canvas, PUPPET_X, PUPPET_Y, scale=s, alpha=pop['alpha'])

    def _transition(self, old, new, kind, u, seed_key):
        if kind == 'slide':
            p = motion.expo_out(u)
            out = old.copy()
            out.paste(old, (-round(W * .25 * p), 0))
            x = round(W * (1 - p))
            edge = motion.shadow_only(Image.new('RGBA', (40, H), (0, 0, 0, 255)), blur=18, opacity=.35)
            out.alpha_composite(edge, (max(0, x - edge.width // 2 - 10), -54))
            out.paste(new.crop((0, 0, W - x, H)), (x, 0))
            return out
        edge_x = W * (1 - motion.expo_out(u)) - 40
        profile = _torn_profile(seed_key)
        mask = (np.arange(W)[None, :] >= (edge_x + profile[:, None])).astype(np.uint8) * 255
        rim = ((np.arange(W)[None, :] >= (edge_x + profile[:, None] - 5)) & (mask == 0))
        out = old.copy()
        out.paste(new, (0, 0), Image.fromarray(mask, 'L'))
        arr = np.asarray(out).copy()
        arr[rim] = (*motion.FIBRE, 255)
        return Image.fromarray(arr, 'RGBA')

    def _caption(self, frame, t):
        i = bisect.bisect_right(self.cap_starts, t) - 1
        if i < 0:
            return
        c = self.tl['captions'][i]
        if c['start'] <= t < c['end']:
            img = cap.caption_image(c['text'], self.lang)
            ink.paste(frame, img, (W - img.width) / 2, 1046 - img.height)

    def cues(self):
        out = [c for e in self.els for c in e.cues()] + self._cues
        return sorted(out, key=lambda c: (c['t'], c['id']))


def _torn_profile(seed_key):
    """A ragged vertical edge: per row, how far the tear wanders (smooth noise plus a fine ragged octave)."""
    rng = motion.seeded(seed_key, 'tear')
    rows = np.arange(H, dtype=np.float32)
    wave = sum(a * np.sin(rows / p + rng.uniform(0, 6.28)) for a, p in ((22, 97.), (11, 41.), (5, 13.)))
    return (wave + rng.normal(0, 2.2, H)).astype(np.float32)

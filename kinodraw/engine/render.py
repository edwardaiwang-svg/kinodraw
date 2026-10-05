#!/usr/bin/env python3
"""Render one language of a video (silent) from a storyboard + timeline.

  python -m kinodraw.engine.render --project P --episode P/storyboard.json --lang en --timeline P/en/timeline.json --output P/en/silent.mp4
  python -m kinodraw.engine.render --project P --episode ... --lang en --synthetic --stills 12,40,95
  python -m kinodraw.engine.render ... --start 300 --duration 90 --output reel.mp4

Frames stream to one ffmpeg (libx264, 2 threads). All inputs are hashed into
``<output>.json``. Narration/music are muxed later by the packager.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

from .. import script, styles
from . import auto_scenes as auto
from . import ink
from . import scenes
from . import skin as skins
from . import timeline as tl
from .storyboard import drawable, normalize
from .board import Camera, Layout, Scheduler
from .geometry import LANDSCAPE

HERE = Path(__file__).resolve().parent
FPS = 30
SIZE = LANDSCAPE.size
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
NOTE_READ = .05          # the note is read during narration; pin it without a silent reading hold
PAUSE_MAX = .1           # catch up by compressing strokes, with only a breath between beats
PACE_MARGIN = .3         # a beat's drawings finish this long before the next beat's words start


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ease(u):
    u = min(1., max(0., u))
    return u * u * (3 - 2 * u)


class Production:
    vertical = False               # set by vertical.Vertical: the frame is the board alone, laid out in 9:16 there
    size = SIZE

    def __init__(self, episode, tline, lang, project_dir, relaxed=False, geometry=LANDSCAPE):
        """``relaxed``: schedule every drawing at natural speed and skip nothing (pacing measures with it)."""
        self.ep, self.tl, self.lang = normalize(episode), tline, lang
        self.relaxed = relaxed
        self.g = geometry
        self.size = geometry.size
        if geometry.name == 'portrait':
            self.vertical = True
        self.project_dir = Path(project_dir)
        self.skin = skins.for_look(self.ep.get('look'))       # paper, ink, fills, fonts, hand and chrome
        scenes.load_page_plugins()
        self.layout = Layout(self.g)
        self.ctx = scenes.Ctx(self.ep, lang, tline, self.layout, project_dir, self.skin)
        self.camera = Camera(self.g, locked=self.skin.locked_camera)
        self.cuts, self.stock, self.modes = [], [], []
        self.cut_marks = []            # index of the first element drawn on each cut's stretch
        self.cards, self.notes, self.pages = {}, {}, {}
        self.scene_marks = []         # automatic pages: (world x, screen kind)
        self.agenda_x = None
        self.warnings = []
        self.hand = ink.Hand(self.skin.hand)
        self._build()
        if self.skin.emphasis == 'highlighter':              # each sentence's key phrase, where it is written
            skins.highlight_phrases(self.ep, self.tl, self.ctx.elements)
        self._schedule()
        self._pin_notes()
        self._index()

    # ------------------------------------------------------------ building
    def _beats(self, cid):
        return [b for b in self.ep['beats'] if b['chapter'] == cid]

    def _bt(self, beat):
        return self.tl['beats'][beat['id']]

    def cut(self, t, x, mode):
        """Move the camera to a new stretch of board; the elements added after this are drawn there."""
        self.cuts.append((t, x, mode))
        self.cut_marks.append(len(self.ctx.elements))

    def _tag(self, first, group, **flags):
        """Mark the elements added since index ``first`` as one visual (and essential/optional...)."""
        for el in self.ctx.elements[first:]:
            el.group = group
            for k, v in flags.items():
                setattr(el, k, v)

    def _visuals(self, beat, not_before=0.0):
        ctx = self.ctx
        ctx.beat = beat
        deferred = []
        first_new = len(ctx.elements)
        for k, v in enumerate(beat.get('visuals', [])):
            vt = v.get('type')
            n0 = len(ctx.elements)
            try:
                if vt in scenes.SLOT_BUILDERS:
                    size = v.get('size', 'slot')
                    if vt == 'cluster' and len(v.get('items', [])) >= 3 and size == 'slot':
                        size = 'wide'
                    if vt == 'quote':
                        size = 'wide' if self.g.name == 'landscape' else 'tall'   # a quote needs a whole portrait screen
                    if size == 'wide':
                        box, _ = self.layout.wide()
                    elif size == 'tall':
                        box, _ = self.layout.slot(rows_needed=2)
                    else:
                        box, _ = self.layout.slot()
                    ctx.text_w = box[2]
                    ctx.text_h = box[3]
                    scenes.SLOT_BUILDERS[vt](v, beat, box, ctx)
                elif vt in scenes.PAGE_BUILDERS:
                    box, (c0, _) = self.layout.page()
                    # Invisible anchor at the page's left edge, drawn first: the camera pans to the whole
                    # page instead of to whichever column its (centred) title happens to start in.
                    anchor = Image.new('RGBA', (self.g.cols_on_screen * self.g.col - 4, 1), (0, 0, 0, 0))
                    ctx.add(ink.StaticDrawing(anchor, pop=.01), c0 * self.g.col + 2, self.g.page_box[1] + 16,
                            ctx.time_of(beat, v.get('trigger')), hand=False)
                    ctx.text_w = box[2]
                    ctx.text_h = box[3]
                    scenes.PAGE_BUILDERS[vt](v, beat, box, ctx)
                elif vt == 'emphasis':
                    deferred.append(v)
                elif vt == 'stock':
                    pass
                else:
                    self.warnings.append(f"{beat['id']}: unsupported visual type {vt}")
            except Exception as error:  # noqa: BLE001 - keep rendering; report
                del ctx.elements[n0:]                 # a failed builder must not leave half a visual
                ctx.registry.pop(v.get('id'), None)
                self.warnings.append(f"{beat['id']}/{v.get('id')}: {type(error).__name__}: {error}")
            finally:
                ctx.text_w = self.g.cell_w
                ctx.text_h = self.g.rows[0][1] - self.g.rows[0][0]
            hold = 3.5 if vt == 'glossary' else (1.8 if vt in scenes.PAGE_BUILDERS or vt == 'quote' else .8)
            for el in ctx.elements[n0:]:
                el.hold = hold
                el.group = v.get('id') or f"{beat['id']}#{k}"     # a visual is drawn whole or not at all
                el.beat = beat['id']
        for v in deferred:
            n0 = len(ctx.elements)
            try:
                scenes.build_emphasis(v, beat, ctx)
            except Exception as error:  # noqa: BLE001
                self.warnings.append(f"{beat['id']}/{v.get('id')}: emphasis {error}")
            self._tag(n0, v.get('id') or f"{beat['id']}#emphasis", beat=beat['id'])
        for el in ctx.elements[first_new:]:          # e.g. wait for a section opener to be drawn
            if not el.atomic:
                el.trigger = max(el.trigger, not_before)

    def _build(self):
        ctx, lay = self.ctx, self.layout
        chapters = self.ep['chapters']
        for ch in chapters:
            cid, kind = ch['id'], ch['kind']
            ctx.chapter = ch
            ctx.color = ink.SECTION_COLORS.get(ch.get('color'), ink.NEUTRAL)
            beats = self._beats(cid)
            cstart = next(c['start'] for c in self.tl['chapters'] if c['id'] == cid)
            if kind == 'outro' and any(v.get('type') == 'stock' for b in beats for v in b.get('visuals', [])):
                # Closing lines play over one continuous stock segment.
                a = self._bt(beats[0])['start']
                b_end = self._bt(beats[-1])['end']
                self.stock.append((a, b_end, 'outro'))
                continue
            if kind == 'intro':
                for b in beats:
                    stock = next((v for v in b.get('visuals', []) if v.get('type') == 'stock'), None)
                    bt = self._bt(b)
                    if stock:
                        self.stock.append((bt['start'], bt['end'], stock.get('clip', kind)))
                    elif kind == 'intro':
                        col = lay.new_page()
                        lay.reserve(col, col + self.g.cols_on_screen - 1)
                        x0 = col * self.g.col
                        self.cut(bt['start'], x0, 'cut')
                        n0 = len(ctx.elements)
                        auto.SCENES[self.g.name]['title_board'](ctx, b, x0, bt['start'] + .25)
                        self._tag(n0, 'title', essential=True)
                        self.pages['title'] = x0
                        self.scene_marks.append((x0, 'title'))
                    else:
                        # outro beat without stock: keep the last board; nothing new.
                        pass
                continue
            if kind == 'agenda':
                col = lay.new_page()
                lay.reserve(col, col + self.g.cols_on_screen - 1)
                x0 = col * self.g.col
                self.agenda_x = x0
                self.scene_marks.append((x0, 'agenda'))
                self.cut(cstart, x0, 'pan')
                n0 = len(ctx.elements)
                self.cards = auto.SCENES[self.g.name]['agenda'](ctx, chapters, beats, x0)
                first = next(c for c in chapters if c['kind'] == 'section')
                end = next(c['end'] for c in self.tl['chapters'] if c['id'] == cid)
                self._tag(n0, 'agenda', essential=True, deadline=end - 1.05 - .15)   # cards before the circle
                circ, pos = auto.circle_around(ctx, self.cards[first['id']]['box'], self.cards[first['id']]['color'])
                ctx.add(circ, pos[0], pos[1], end - 1.05, fixed=True)
                continue
            col = lay.new_page()
            x0 = col * self.g.col
            self.pages[cid] = x0
            opener_done = 0.0
            if kind == 'section':
                self.scene_marks.append((x0, 'opener'))
                lay.reserve(col, col + self.g.opener_cols - 1)
                self.cut(cstart, x0, 'cut')
                n0 = len(ctx.elements)
                opener = auto.SCENES[self.g.name]['section_opener'](ctx, ch, beats[0], x0, cstart + tl.ZOOM_IN + .15)
                self._tag(n0, f'opener:{cid}', essential=True)
                opener_done = cstart + tl.ZOOM_IN + .15 + sum(e.drawing.duration for e in opener if e.hand) * .8
                self.modes.append((cstart, cstart + tl.ZOOM_IN, 'zoom', {'section': cid}))
            else:
                prev_tr = next((t for t in self.tl['transitions'] if t['next'] == cid), None)
                self.cut(cstart, x0, 'cut' if prev_tr else 'pan')
                if prev_tr:
                    self.modes.append((cstart, cstart + .5, 'fade_in', {}))
            for b in beats:
                bt = self._bt(b)
                if b.get('kind') == 'take' and kind == 'section':
                    self._take_page(b, bt, ch)
                    continue
                self._visuals(b, opener_done)              # nothing before the section's title card
        # Closing page, written by the hand like everything else.
        end = self.tl['end_card']
        col = lay.new_page()
        lay.reserve(col, col + self.g.cols_on_screen - 1)
        ctx.chapter, ctx.color = None, ink.NEUTRAL
        self.scene_marks.append((col * self.g.col, 'end'))
        self.cut(end['start'], col * self.g.col, 'pan')
        n0 = len(ctx.elements)
        auto.SCENES[self.g.name]['end_card'](ctx, col * self.g.col, end['start'] + self.g.pan_seconds)
        self._tag(n0, 'endcard', essential=True, deadline=end['end'] - .5)
        if self.tl.get('credit'):                      # "Made with ...", written under it while it is read
            n0 = len(ctx.elements)
            auto.SCENES[self.g.name]['credit'](ctx, col * self.g.col, self.tl['credit']['start'] - .8)
            self._tag(n0, 'credit', essential=True, deadline=self.tl['credit']['end'] - .3)
        self._transitions()

    def _take_page(self, beat, bt, ch):
        """A fresh page for the section's takeaway: during the pre-roll the camera pans over and the note
        is laid down; its label and headline are written as "Key takeaway: ..." is said, and must be
        finished NOTE_READ seconds before it is pinned; the narrator's face and the section's hero
        doodles in the margins are drawn only if they fit before then."""
        ctx, lay, cid = self.ctx, self.layout, ch['id']
        tcol = lay.new_page()
        lay.reserve(tcol, tcol + self.g.cols_on_screen - 1)
        xt = tcol * self.g.col
        self.scene_marks.append((xt, 'take'))
        prep = bt.get('prep', bt['start'])
        self.cut(prep - self.g.pan_seconds, xt, 'pan')
        tr = next((x for x in self.tl['transitions'] if x['section'] == cid), None)
        deadline = tr['hold_end'] - NOTE_READ if tr else None
        t_note = prep
        spoken = beat['spoken'][self.lang]
        prefix = script.take_text('', self.lang)            # "Key takeaway: " (said before the headline)
        t_label = ctx.time_of(beat, None, 0.)
        t_head = ctx.time_of(beat, {self.lang: spoken[len(prefix):len(prefix) + 24]}) \
            if spoken.startswith(prefix) and len(spoken) > len(prefix) else t_label
        els, bbox = auto.SCENES[self.g.name]['take_note'](ctx, beat, ch, xt, t_note, t_label, t_head)
        for k, el in enumerate(els):
            el.group = f'note:{cid}' if el.essential else f'note:{cid}:{k}'
            el.deadline = deadline
            el.beat = beat['id']                           # pacing holds the note until its face is drawn too
        self.notes[cid] = {'els': els, 'bbox': bbox, 'x': xt}
        written = els[2]                                   # the headline (after the note and its label)
        if self.g.name == 'landscape':
            margins = [(xt + 16, 250, 310, 420), (xt + 1920 - 326, 250, 310, 420)]
            n0 = len(ctx.elements)                             # the margin pair is drawn together or not at all
            for k, v in enumerate(v for v in beat.get('visuals', []) if v.get('size') == 'margin'):
                if k < 2:
                    scenes.build_cluster(v, beat, margins[k], ctx, max_dur=auto.DECOR_DUR)
            self._tag(n0, f'margins:{cid}', optional=True, deadline=deadline, beat=beat['id'])
            for el in ctx.elements[n0:]:
                el.trigger = max(el.trigger, t_note + .02)
                el.after = el.after or written
        if deadline is not None and not self.relaxed:
            extras = [el for el in ctx.elements if el.beat == beat['id'] and not el.essential]
            reserve = sum(el.drawing.duration / 4 + .2 for el in extras)
            for el in els:
                if el.essential:
                    el.deadline = deadline - reserve

    def _transitions(self):
        ctx = self.ctx
        for tr in self.tl['transitions']:
            sec, nxt = tr['section'], tr['next']
            card = self.cards.get(sec)
            note = self.notes.get(sec)
            if not card or not note:
                self.warnings.append(f'transition {sec}: missing card or note')
                continue
            t_p = tr['hold_end']
            span = tr['end'] - t_p
            t_f = t_p + span * .2
            t_c = t_p + span * .5
            t_r = t_p + span * .8
            self.modes.append((t_p, t_f, 'pullback', {'section': sec}))
            self.modes.append((t_f, t_c, 'fly', {'section': sec}))
            self.modes.append((t_c, tr['end'], 'agenda', {'section': sec}))
            # Where the mini note is pinned: full cards take a mini note 90 px narrower than the card;
            # compact cards keep room for the title. Its picture is taken after scheduling (_pin_notes).
            nx, ny, nw, nh = note['bbox']
            iw, ih = int(nw) + 4, int(nh) + 4
            cx, cy, cw, chh = card['box']
            if self.g.name == 'portrait':                 # in the card's right strip, above its check mark
                strip = int(cw * auto.CARD_STRIP)
                s = min((strip - 16) / iw, (chh - 112) / ih)
                mw, mh = int(iw * s), int(ih * s)
                px, py = cx + cw - strip + (strip - mw) / 2, cy + 28
            else:
                mw = int(min(cw - 90, (chh - 150) * iw / ih))
                mh = int(ih * mw / iw)
                px, py = cx + (cw - mw) / 2, cy + chh - mh - 34
            note.update(pin_xy=(px, py), mini_size=(mw, mh), t_pin=t_c)
            ctx.add(auto.pin(ctx), px + mw / 2 - 22, py - 14, t_c, fixed=True, hand=False)
            # The check mark goes where nothing is written on the card.
            taken = [b for b in map(auto.ink_bbox, card.get('els', [])) if b] + [(px, py - 14, px + mw, py + mh)]
            if self.g.name == 'portrait':
                size, pos = 60, (cx + cw - strip + (strip - 60) / 2, cy + chh - 72)
            else:
                size, pos = auto.check_spot(card['box'], taken, (150, 120, 96) if chh >= 600 else (90, 72, 60))
            check = ctx.add(auto.check_mark(ctx, size=size), pos[0], pos[1], t_c + .05, fixed=True)
            check.rate = max(1., check.drawing.duration / max(.01, t_r - check.trigger))
            if nxt in self.cards:
                circ, pos = auto.circle_around(ctx, self.cards[nxt]['box'], self.cards[nxt]['color'])
                circle = ctx.add(circ, pos[0], pos[1], t_r, fixed=True)
                circle.rate = max(1., circle.drawing.duration / max(.01, tr['end'] - t_r))
        for a, b, clip in self.stock:
            self.modes.append((a, b, 'stock', {'clip': clip}))
        self.modes.sort(key=lambda m: m[0])

    def _schedule(self):
        els = self.ctx.elements
        marks = self.cut_marks + [len(els)]
        for k in range(len(self.cuts)):
            for el in els[marks[k]:marks[k + 1]]:
                el.stretch = k
        if self.relaxed:                    # how long everything takes: decoration is not dropped for time either
            Scheduler(self.camera, self.g).run(els, self.cuts, max_rate=1.0, stale=math.inf, cut_grace=math.inf,
                                               keep_optional=True)
        else:
            Scheduler(self.camera, self.g).run(els, self.cuts, max_rate=4.0)
        for e in els:
            if not e.atomic:
                continue
            clears = [t for t, _, _ in self.cuts[e.stretch + 1:]]
            clears += [tr['hold_end'] for tr in self.tl['transitions'] if tr['hold_end'] > e.trigger]
            clears += [t for t, _, _ in self.camera.keys if e.start is not None and t > e.end]
            if clears:
                e.hidden_after = min(clears)
        skipped = sorted({e.group for e in els if e.skipped})
        if skipped:
            self.warnings.append(f"skipped {len(skipped)} visual(s) that could not keep pace with the narration: "
                                 f"{', '.join(skipped)}")
        # Backlog report: drawings that start long after their words (or the drawing they follow).
        due = {id(e): max(e.trigger, e.after.end if e.after is not None and e.after.start is not None else 0)
               for e in els}
        late = [(e.start - due[id(e)], e.group) for e in els
                if not e.fixed and e.start is not None and e.start - due[id(e)] > 2.5]
        if late:
            self.warnings.append(f'{len(late)} drawings start >2.5 s late (max {max(l for l, _ in late):.1f} s)')

    def _pin_notes(self):
        """Picture each takeaway note exactly as it stands when its transition starts (nothing ahead
        of the hand), and pin that picture, shrunk, onto the agenda card."""
        for tr in self.tl['transitions']:
            note = self.notes.get(tr['section'])
            if not note or 'pin_xy' not in note:
                continue
            nx, ny, nw, nh = note['bbox']
            t = tr['hold_end'] - .01
            img = Image.new('RGBA', (int(nw) + 4, int(nh) + 4), (0, 0, 0, 0))
            for el in note['els']:
                ink.paste(img, el.state(t)[0], el.x - nx, el.y - ny)
            note['image'] = img
            note['mini'] = img.resize(note['mini_size'], Image.LANCZOS)
            px, py = note['pin_xy']
            pinned = ink.StaticDrawing(note['mini'], pop=.05)
            # the note's drawings are already in the look's cells or tiles: shrinking them and dressing them again
            # would melt the words into a smear of cells
            pinned.dressed = True
            mini = self.ctx.add(pinned, px, py, note['t_pin'] - .02, fixed=True, hand=False)
            mini.start = mini.trigger

    def _index(self):
        self.els = sorted((e for e in self.ctx.elements if e.start is not None and not e.skipped),
                          key=lambda e: e.start)
        self.hand_els = [e for e in self.els if e.hand]
        self.hand_starts = [e.start for e in self.hand_els]
        self.cap_starts = [c['start'] for c in self.tl['captions']]
        self.mode_starts = [m[0] for m in self.modes]
        self._stock_reader = None

    # ------------------------------------------------------------- views
    def mode_at(self, t):
        i = bisect.bisect_right(self.mode_starts, t) - 1
        while i >= 0:
            a, b, kind, params = self.modes[i]
            if a <= t < b:
                return kind, params, a, b
            i -= 1
            if i >= 0 and self.modes[i][1] <= t and kind != 'stock':
                break
        return 'board', {}, None, None

    def scene_at(self, t):
        """The scene filling the screen, independent of drawing progress."""
        kind, params, _, _ = self.mode_at(t)
        if kind in ('pullback', 'fly', 'agenda'):
            return 'agenda'
        if kind == 'zoom':
            return 'opener'
        if kind == 'stock':
            return 'title' if self._in_title(t) else 'end'
        L = self.camera.at(t)
        return next((scene for x, scene in self.scene_marks if abs(x - L) <= self.g.col / 2), 'board')

    def view(self, t, L, hand=True):
        if self.skin.textured:
            L = int(round(L))
            frame = self.skin.background(*self.size, x=L).copy()
        else:
            x = 12 + int(round(self._drift(t)))
            paper = self.skin.background(self.size[0] + 24, self.size[1])
            frame = paper.crop((x, 0, x + self.size[0], self.size[1]))
        lo, hi = L - 20, L + self.size[0] + 20
        for layer in (0, 1):
            for e in self.els:
                if e.start > t:
                    break
                if e.layer != layer or e.x > hi or e.x + e.w < lo:
                    continue
                if isinstance(e.drawing, ink.TextDrawing) and not self.text_visible(e, t, L):
                    continue
                img, _, _ = e.state(t)
                if img is not None:
                    ink.paste(frame, img, e.x - L, e.y)
        if self.skin.textured:
            frame = self.skin.post(frame, L)
        if hand:
            self._hand(frame, t, L)
        return frame

    def text_visible(self, e, t, L):
        """Cull whole text (whole cards for quotes) before a camera move can clip a glyph."""
        mx, my = self.size[0] * .04, self.size[1] * .04
        parts = self.ctx.registry.get(e.group, {}).get('all', [e]) if e.atomic else [e]
        return all(mx <= p.x - L and p.x + p.w - L <= self.size[0] - mx
                   and my <= p.y and p.y + p.h <= self.size[1] - my for p in parts)

    def _hand(self, frame, t, L):
        i = bisect.bisect_right(self.hand_starts, t) - 1
        cur = self.hand_els[i] if i >= 0 else None
        if cur is not None and cur.start <= t < cur.end:
            if isinstance(cur.drawing, ink.TextDrawing) and not self.text_visible(cur, t, L):
                return
            _, pen, down = cur.state(t)
            if pen is not None:
                self.hand.paste(frame, (cur.x - L + pen[0], cur.y + pen[1]), lifted=not down)
                return
            if t - cur.start < cur.drawing.duration * .95 and hasattr(cur.drawing, 'draw_time'):
                return
        # travelling between drawings
        prev = cur if cur is not None and cur.end <= t else (self.hand_els[i - 1] if i > 0 else None)
        nxt = self.hand_els[i + 1] if i + 1 < len(self.hand_els) else None
        if prev is None or nxt is None:
            return
        gap = nxt.start - prev.end
        if gap <= 0:
            return
        p0 = self._last_pen(prev)
        p1 = self._first_pen(nxt)
        if p0 is None or p1 is None:
            return
        u = ease((t - prev.end) / gap)
        x = (prev.x + p0[0]) * (1 - u) + (nxt.x + p1[0]) * u - L
        y = (prev.y + p0[1]) * (1 - u) + (nxt.y + p1[1]) * u
        self.hand.paste(frame, (x, y - 10 * math.sin(math.pi * u)), lifted=True)

    @staticmethod
    def _first_pen(e):
        if not hasattr(e, '_first_pen'):
            e._first_pen = e.drawing.state(min(.02, e.drawing.duration / 3))[1]
        return e._first_pen

    @staticmethod
    def _last_pen(e):
        if not hasattr(e, '_last_pen'):
            d = e.drawing
            end = getattr(d, 'draw_time', d.duration) - .01
            e._last_pen = d.state(max(0, end))[1]
        return e._last_pen

    def board_frame(self, t):
        if self.camera.locked:
            wipe = self.camera.wipe_at(t)
            if wipe is not None:
                from_L, to_L, u = wipe
                return skins.wipe(self.view(t, from_L, hand=False), self.view(t, to_L, hand=False), u, self.skin)
        return self.view(t, self.camera.at(t) + self._drift(t))

    def _drift(self, t):
        return 0. if self.camera.locked else 12 * math.sin(t * .8)

    def stock_frame(self, t, a, clip):
        path = self.project_dir / 'stock/MANIFEST.json'
        clips = playlist(json.loads(path.read_text(encoding='utf-8')), clip) if path.exists() else []
        if not clips:
            return self.skin.background(*self.size).copy()
        key = (clip, a)
        if self._stock_reader is None or self._stock_reader.key != key:
            if self._stock_reader:
                self._stock_reader.close()
            self._stock_reader = StockReader(clips, a, key, self.size)
        return self._stock_reader.frame_at(t)

    # ------------------------------------------------------------- frame
    def frame(self, t):
        kind, p, a, b = self.mode_at(t)
        chrome = True
        if kind == 'stock':
            frame = self.stock_frame(t, a, p['clip'])
            chrome = False
        elif kind in ('pullback', 'fly', 'agenda'):
            frame = self._transition(t, kind, p, a, b)
        elif kind == 'zoom':
            if self.camera.locked:
                frame = skins.wipe(self.view(a - .01, self.agenda_x, hand=False), self.board_frame(t),
                                   (t - a) / (b - a), self.skin)
            else:
                frame = self._zoom(t, p, a, b)
        elif kind == 'fade_in':
            u = ease((t - a) / (b - a))
            src = self.view(t, self.agenda_x, hand=False)
            dst = self.board_frame(t)
            frame = (skins.wipe(src, dst, (t - a) / (b - a), self.skin) if self.camera.locked
                     else Image.blend(src, dst, u))
        else:
            frame = self.board_frame(t)
        if self.vertical:
            return frame
        if chrome and not self._in_title(t):
            self._chrome(frame, t)
        self._caption(frame, t)
        return frame

    def cues(self):
        """Sound-effect events ({t, kind, strength, id}); the whiteboard mix has none."""
        return []

    def _in_title(self, t):
        ids = {c['id'] for c in self.ep['chapters'] if c['kind'] == 'intro'}
        return any(c['start'] <= t < c['end'] for c in self.tl['chapters'] if c['id'] in ids)

    def _transition(self, t, kind, p, a, b):
        sec = p['section']
        note = self.notes[sec]
        tr = next(x for x in self.tl['transitions'] if x['section'] == sec)
        agenda = self.view(t, self.agenda_x + self._drift(t), hand=(kind == 'agenda'))
        nx, ny, nw, nh = note['bbox']
        sx, sy = nx - note['x'], ny
        if kind == 'pullback':
            u = ease((t - a) / (b - a))
            board = self.view(tr['hold_end'] - .01 if self.camera.locked else t,
                              note['x'] + self._drift(t), hand=False)
            frame = (skins.wipe(board, agenda, (t - a) / (b - a), self.skin) if self.camera.locked
                     else Image.blend(board, agenda, u))
            ink.paste(frame, self._note_image(note, board, sx, sy), sx, sy)
            return frame
        if kind == 'fly':
            u = ease((t - a) / (b - a))
            tx, ty = note['pin_xy']
            tx -= self.agenda_x
            mini_w = note['mini'].width
            w = nw + (mini_w - nw) * u
            s = w / nw
            image = self._note_image(note, None, sx, sy, tr)
            img = image.resize((max(1, int(image.width * s)), max(1, int(image.height * s))), Image.BILINEAR)
            x = sx + (tx - sx) * u
            y = sy + (ty - sy) * u - 60 * math.sin(math.pi * u)
            ink.paste(agenda, img, x, y)
            return agenda
        return agenda

    def _note_image(self, note, board, sx, sy, tr=None):
        """The takeaway note as the board showed it. A look with a glow (Pixel Quest) glows the whole board, so the
        note is cut from that glowing board rather than pasted raw, which would dull the card in one frame."""
        if not self.skin.bloom:
            return note['image']
        if 'shown' not in note:
            if board is None:
                board = self.view(tr['hold_end'] - .01, note['x'], hand=False)
            x, y = int(round(sx)), int(round(sy))
            shown = board.crop((x, y, x + note['image'].width, y + note['image'].height)).convert('RGBA')
            shown.putalpha(note['image'].getchannel('A'))
            note['shown'] = shown
        return note['shown']

    def _zoom(self, t, p, a, b):
        # Keep agenda lettering inside its safe area throughout the move into the section.
        agenda = self.view(t, self.agenda_x + self._drift(t), hand=False)
        return Image.blend(agenda, self.board_frame(t), ease((t - a) / (b - a)))

    def _chrome(self, frame, t):
        span = self._chapter_span(t)
        if span is None or span[0]['kind'] in ('intro', 'outro'):
            return
        ch, a, b = span
        if sum(c['kind'] in ('section', 'board') for c in self.ep['chapters']) == 1 \
                and self.ctx.T(ch.get('label')) == script.TEXT[self.lang]['label'].format(n=1):
            ch = {**ch, 'label': {}}
        alpha = min(1., (t - a) / .4, (b - t) / .3)       # labels fade in and out; nothing pops
        tag = (chip_image(ch, self.lang, self.skin.fonts) if self.skin.chapter_tag == 'chip'
               else skins.tag_image(ch, self.lang, self.skin))
        chip = faded(self._fit_ui(tag), alpha)
        ink.paste(frame, chip, 77, 44)
        src = source_line(ch, self.lang)
        if src:
            img = faded(self._fit_ui(ui_text(src, 34, self.skin.soft, self.skin.fonts)), alpha)
            ink.paste(frame, img, 1920 - 77 - img.width, 44)
        footer = self.ctx.T(self.ep.get('footer'))
        if footer:
            img = self._fit_ui(ui_text(footer, 24, self.skin.faint, self.skin.fonts))
            ink.paste(frame, img, 77, 1036 - img.height)

    def _fit_ui(self, img):
        w = int(self.size[0] * .92)
        if img.width > w:
            return img.resize((w, max(1, round(img.height * w / img.width))), Image.LANCZOS)
        return img

    def _chapter_span(self, t):
        for c in self.tl['chapters']:
            if c['start'] <= t < c['end']:
                return next(x for x in self.ep['chapters'] if x['id'] == c['id']), c['start'], c['end']
        return None

    def _caption(self, frame, t):
        i = bisect.bisect_right(self.cap_starts, t) - 1
        if i < 0:
            return
        c = self.tl['captions'][i]
        if not (c['start'] <= t < c['end']):
            return
        img = self._fit_ui(self.skin.caption_image(c['text'], self.lang))
        ink.paste(frame, img, (self.size[0] - img.width) / 2, 1036 - img.height)


def make_production(episode, tline, lang, project_dir, relaxed=False, aspect='16:9', portrait=None):
    """Every renderer is built here, so the storyboard's look picks its class in one place (whiteboard by default).
    A look's renderer answers frame(t), warnings, ctx.elements and cues() like Production does. ``portrait`` can
    override the look's 9:16 layout for comparisons; the registry decides by default."""
    layout = pace_layout(episode, aspect, portrait)
    if drawable(episode.get('look') or 'whiteboard') == 'collage':
        if layout == 'portrait':
            raise ValueError('collage is not laid out for 9:16 yet; it renders letterboxed')
        from .collage.render import CollageProduction
        prod = CollageProduction(episode, tline, lang, project_dir, relaxed=relaxed)
    elif layout == 'portrait':
        from .geometry import PORTRAIT
        prod = Production(episode, tline, lang, project_dir, relaxed=relaxed, geometry=PORTRAIT)
    else:
        prod = Production(episode, tline, lang, project_dir, relaxed=relaxed)
    if aspect == '9:16':
        from .vertical import PortraitFrame
        return PortraitFrame(prod, native=layout == 'portrait')
    return prod


def pace_layout(episode, aspect, portrait=None) -> str:
    """The board geometry whose drawing times set the narration's pauses."""
    if aspect == '16:9':
        return 'landscape'
    if aspect != '9:16':
        raise ValueError(f'unknown aspect {aspect!r} (16:9 or 9:16)')
    portrait = styles.portrait(episode.get('look')) if portrait is None else portrait
    if portrait not in ('letterbox', 'native'):
        raise ValueError(f'unknown portrait {portrait!r} (letterbox or native)')
    return 'portrait' if portrait == 'native' else 'landscape'


def pacing(episode, lang, clips, project_dir, aspect='16:9', portrait=None, rounds=3) -> dict:
    """Pauses (beat id -> seconds) that let the drawing hand finish each beat's pictures before the next
    beat is said, instead of rushing or skipping them: at most PAUSE_MAX after any one beat. A takeaway note,
    with the narrator's face on it and the section's pictures beside it, is finished NOTE_READ before it is
    pinned to the agenda.

    Every round lays out the timeline with the pauses so far, schedules the drawings at natural speed
    with nothing skipped, and adds the overrun of each beat's drawings past the next beat's start."""
    layout = pace_layout(episode, aspect, portrait)
    pauses: dict = {}
    for _ in range(rounds):
        timing = tl.layout(episode, lang, clips, pauses)
        if layout == 'portrait':
            prod = make_production(episode, timing, lang, project_dir, relaxed=True,
                                   aspect=aspect, portrait=portrait)
        else:
            prod = make_production(episode, timing, lang, project_dir, relaxed=True)
        ends: dict = {}
        for e in prod.ctx.elements:
            if e.beat and e.start is not None and not e.skipped and not e.fixed:
                ends[e.beat] = max(ends.get(e.beat, 0.), e.end)
        order, changed = timing['beat_order'], False
        pinned = {tr['take_beat']: tr['hold_end'] for tr in timing['transitions']}
        for k, bid in enumerate(order[:-1]):
            nxt = timing['beats'][order[k + 1]]                 # a takeaway's pre-roll is for its note
            if bid in pinned:
                continue                                      # pin immediately; the note's strokes compress to fit
            else:
                need = ends.get(bid, -math.inf) + PACE_MARGIN - nxt.get('prep', nxt['start'])
            room = PAUSE_MAX - pauses.get(bid, 0.)
            if need > .05 and room > .05:
                pauses[bid] = round(pauses.get(bid, 0.) + min(need, room), 2)
                changed = True
        if not changed:
            break
    return pauses


def playlist(manifest, line):
    """Recommended clips for 'intro'/'outro' in rank order: [(path, in_s, out_s)]."""
    items = manifest if isinstance(manifest, list) else (manifest.get('clips') or manifest.get('items') or [])
    chosen = sorted((x for x in items if x.get('matches_line') == line and x.get('status') == 'recommended'),
                    key=lambda x: x.get('rank') or 99)
    return [(x['path'], float(x.get('in_s', 0)), float(x.get('out_s', x.get('duration', 10)))) for x in chosen]


class StockReader:
    """Sequential decoder over a clip playlist; holds the last frame if the segment outlasts it."""

    def __init__(self, clips, seg_start, key, size=SIZE):
        self.size = size
        self.key, self.seg_start, self.clips = key, seg_start, clips
        self.proc, self.idx, self.last, self.local_t = None, -1, None, 0.

    def _open(self, i, local):
        if self.proc:
            self.proc.kill()
        path, a, b = self.clips[i]
        self.proc = subprocess.Popen(
            [FFMPEG, '-v', 'error', '-ss', f'{a + local:.3f}', '-i', path, '-t', f'{max(.1, b - a - local):.3f}', '-vf',
             f'scale={self.size[0]}:{self.size[1]}:force_original_aspect_ratio=increase,'
             f'crop={self.size[0]}:{self.size[1]},fps=30',
             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
        self.idx, self.frame_local = i, local - 1 / FPS

    def frame_at(self, t):
        off = t - self.seg_start
        acc = 0.
        for i, (_, a, b) in enumerate(self.clips):
            if off < acc + (b - a) or i == len(self.clips) - 1:
                local = off - acc
                break
            acc += b - a
        if i != self.idx or local < self.frame_local:
            self._open(i, max(0., local))
        while self.frame_local + 1e-6 < local or self.last is None:
            data = self.proc.stdout.read(self.size[0] * self.size[1] * 3)
            if len(data) < self.size[0] * self.size[1] * 3:
                break
            self.last = Image.frombytes('RGB', self.size, data).convert('RGBA')
            self.frame_local += 1 / FPS
        return (self.last or ink.paper(*self.size)).copy()

    def close(self):
        if self.proc:
            self.proc.kill()


_chip_cache, _txt_cache = {}, {}


def faded(img, alpha):
    if alpha >= 1:
        return img
    out = img.copy()
    out.putalpha(out.getchannel('A').point(lambda a: int(a * max(0., alpha))))
    return out


def ui_text(text, size, color, fonts=ink.FONTS):
    key = (text, size, tuple(color), fonts)
    if key not in _txt_cache:
        from PIL import ImageDraw
        kind = 'ui' if all(ord(c) < 0x2e80 for c in text) else 'zh_caption'
        f = ink.font(kind, size, fonts)
        cmap = ink._cmap(*getattr(fonts, kind))
        if all(c.isspace() or ord(c) in cmap for c in text):
            w = int(f.getlength(text)) + 6
            img = Image.new('RGBA', (w, size + 12), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((2, 2), text, font=f, fill=tuple(color) + (255,))
        else:       # symbols the look font lacks (₂, →) come from fallback fonts on the primary font's baseline
            runs = ink.ui_runs(text, kind, size, fonts)
            img = Image.new('RGBA', (int(sum(rf.getlength(c) for c, rf in runs)) + 6, size + 12), (0, 0, 0, 0))
            d, x, base = ImageDraw.Draw(img), 2, 2 + f.getmetrics()[0]
            for c, rf in runs:
                d.text((x, base), c, font=rf, fill=tuple(color) + (255,), anchor='ls')
                x += rf.getlength(c)
        _txt_cache[key] = img
    return _txt_cache[key]


def chip_text(ch, lang):
    label = (ch.get('label') or {}).get(lang, '')
    title = (ch.get('title') or {}).get(lang, '')
    short = title.split(':')[0].split('：')[0] if ch['kind'] == 'section' else title
    text = f'{label} · {short}' if label and short and short.strip().lower() != label.strip().lower() else (label or short)
    return text


def chip_image(ch, lang, fonts=ink.FONTS):
    text = chip_text(ch, lang)
    key = (text, ch.get('color'), lang, fonts)     # by what it shows: one process may render several videos
    if key not in _chip_cache:
        from PIL import ImageDraw
        f = ink.font('ui' if lang in ('en', 'es') else 'zh_caption', 32, fonts)
        w = int(f.getlength(text)) + 44
        img = Image.new('RGBA', (w, 52), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        col = ink.SECTION_COLORS.get(ch.get('color'))
        if col:
            d.rounded_rectangle((0, 0, w - 1, 51), 26, fill=col + (255,))
            d.text((22, 8), text, font=f, fill=(255, 255, 255, 255))
        else:
            d.rounded_rectangle((0, 0, w - 1, 51), 26, fill=(255, 255, 255, 200), outline=(40, 52, 64, 255), width=3)
            d.text((22, 8), text, font=f, fill=(40, 52, 64, 255))
        _chip_cache[key] = img
    return _chip_cache[key]


def source_line(ch, lang):
    sp = ch.get('speaker')
    if ch['kind'] == 'section' and sp and sp.get('show'):
        if lang == 'es':
            return (f"Fuente: {sp['name'].get('es', sp['name'].get('en', ''))} · "
                    f"{sp['show'].get('es', sp['show'].get('en', ''))}, {sp['date'].get('es', sp['date'].get('en', ''))}")
        return (f"Source: {sp['name']['en']} · {sp['show']['en']}, {sp['date']['en']}" if lang == 'en'
                else f"来源：{sp['name']['zh']} · {sp['show']['zh']}，{sp['date']['zh']}")
    return (ch.get('source') or {}).get(lang)


def load(args):
    episode = json.loads(Path(args.episode).read_text(encoding='utf-8'))
    if args.synthetic:
        tline = tl.layout(episode, args.lang, tl.synthetic_clips(episode, args.lang))
    else:
        tline = json.loads(Path(args.timeline).read_text(encoding='utf-8'))
    return episode, tline


def build(episode, tline, args):
    t0 = time.time()
    prod = make_production(episode, tline, args.lang, args.project, aspect=args.aspect,
                           portrait=getattr(args, 'portrait', None))
    print(json.dumps({'elements': len(prod.els), 'warnings': prod.warnings[:40], 'n_warnings': len(prod.warnings),
                      'build_s': round(time.time() - t0, 1), 'duration': tline['duration']}, ensure_ascii=False), flush=True)
    return prod


def encode(prod, start, n, output, crf, context=None):
    """Stage privately, report encoded frames, replace only after success."""
    import os
    import tempfile
    import threading
    from ..progress import RenderContext, encoded_frames, validate_frames, wait_process
    ctx = context or RenderContext()
    ctx.begin()
    ctx.token.check()
    if n <= 0:
        raise ValueError('frames must be positive')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    w, h = prod.size
    with tempfile.TemporaryDirectory(prefix='.encode-', dir=output.parent) as work:
        temp = Path(work) / output.name
        progress = Path(os.environ.get('KINODRAW_WORKER_PROGRESS', str(Path(work) / 'progress')))
        group = not bool(os.environ.get('KINODRAW_WORKER_PROGRESS'))
        proc = ctx.token.register(subprocess.Popen(
            [FFMPEG, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
             '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(crf),
             '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart',
             '-progress', str(progress), '-stats_period', '0.05', str(temp)],
            stdin=subprocess.PIPE, start_new_session=group), group=group)
        previous_handler = None
        if not group and threading.current_thread() is threading.main_thread():
            import signal
            previous_handler = signal.signal(signal.SIGTERM, lambda *_: ctx.token.cancel())
        done = threading.Event()
        errors = []
        def monitor():
            try:
                while not done.wait(.03):
                    ctx.report(min(encoded_frames(progress), n - 1), n)
            except BaseException as exc:
                errors.append(exc)
                ctx.token.cancel()
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        try:
            for i in range(n):
                ctx.token.check()
                frame = prod.frame(start + i / FPS).convert('RGB')
                if frame.size != (w, h):
                    raise ValueError('generated frame size differs from production size')
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            wait_process(proc, ctx)
            ctx.report(min(encoded_frames(progress), n - 1), n)
            if errors:
                raise errors[0]
            validate_frames(FFMPEG, temp, n, ctx, group=group)
            ctx.token.commit(temp, output)
            ctx.report(n, n)
        except (BrokenPipeError, OSError):
            ctx.token.check()
            raise
        finally:
            done.set()
            thread.join()
            reader = getattr(prod, '_stock_reader', None)
            if reader is not None and reader.proc is not None:
                reader.close()
                reader.proc.wait()
            ctx.token.stop(proc)
            if not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
            ctx.token.unregister(proc)
            if previous_handler is not None:
                signal.signal(signal.SIGTERM, previous_handler)


def render_segments(project, episode, lang, timeline, start, n, output, workers, crf=20,
                    aspect='16:9', portrait=None, context=None):
    """One/two owned process groups, private segments, atomic lossless join."""
    import os
    import tempfile
    from ..progress import RenderContext, encoded_frames, validate_frames, wait_process
    if workers not in (1, 2) or n < workers:
        raise ValueError('use one or two workers and at least one frame per worker')
    ctx = context or RenderContext()
    ctx.begin()
    ctx.token.check()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    bounds = [round(n * i / workers) for i in range(workers + 1)]
    worker = [sys.executable, '--render-worker'] if getattr(sys, 'frozen', False) else \
        [sys.executable, '-m', 'kinodraw.engine.render']
    base = worker + ['--project', str(project), '--episode', str(episode), '--lang', lang, '--crf', str(crf),
                     '--aspect', aspect] + (['--timeline', str(timeline)] if timeline else ['--synthetic'])
    if portrait is not None:
        base += ['--portrait', portrait]
    procs = []
    with tempfile.TemporaryDirectory(prefix='.segments-', dir=output.parent) as work:
        seg_dir = Path(work)
        segs = [seg_dir / f'{i:02d}.mp4' for i in range(workers)]
        progress = [seg_dir / f'{i:02d}.progress' for i in range(workers)]
        try:
            for i, seg in enumerate(segs):
                ctx.token.check()
                env = dict(os.environ, KINODRAW_WORKER_PROGRESS=str(progress[i]))
                procs.append(ctx.token.register(subprocess.Popen(base + [
                    '--start', repr(start + bounds[i] / FPS), '--frames', str(bounds[i + 1] - bounds[i]),
                    '--output', str(seg)], env=env, start_new_session=True), group=True))
            while any(p.poll() is None for p in procs):
                ctx.token.check()
                if any(p.poll() not in (None, 0) for p in procs):
                    raise RuntimeError('segment render failed')
                ctx.report(min(sum(encoded_frames(p) for p in progress), n - 1), n)
                time.sleep(.03)
            ctx.token.check()
            if any(p.returncode != 0 for p in procs):
                raise RuntimeError('segment render failed')
            ctx.report(min(sum(encoded_frames(p) for p in progress), n - 1), n)
            listing = seg_dir / 'list.txt'
            listing.write_text(''.join(f"file '{seg.name}'\n" for seg in segs), encoding='utf-8')
            temp = seg_dir / ('joined' + output.suffix)
            join = ctx.token.register(subprocess.Popen([
                FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
                '-c', 'copy', '-movflags', '+faststart', str(temp)], start_new_session=True), group=True)
            procs.append(join)
            wait_process(join, ctx)
            validate_frames(FFMPEG, temp, n, ctx)
            warnings = json.loads(Path(f'{segs[0]}.json').read_text(encoding='utf-8'))['warnings']
            ctx.token.commit(temp, output)
            ctx.report(n, n)
            return warnings
        finally:
            for proc in procs:
                ctx.token.stop(proc)
                ctx.token.unregister(proc)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True, help='project folder (photos/, doodles/, stock/)')
    ap.add_argument('--episode', required=True)
    ap.add_argument('--lang', required=True, choices=['en', 'zh', 'es'])
    ap.add_argument('--timeline')
    ap.add_argument('--synthetic', action='store_true')
    ap.add_argument('--output')
    ap.add_argument('--start', type=float, default=0)
    ap.add_argument('--duration', type=float)
    ap.add_argument('--frames', type=int, help=argparse.SUPPRESS)
    ap.add_argument('--workers', type=int, default=1, help='parallel segment renders (~0.9 GB RAM each)')
    ap.add_argument('--stills')
    ap.add_argument('--preview-dir')
    ap.add_argument('--crf', type=int, default=20)
    ap.add_argument('--aspect', default='16:9', choices=['16:9', '9:16'], help='9:16: vertical, for Shorts')
    ap.add_argument('--portrait', default=None, choices=['letterbox', 'native'], help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if not (args.stills or args.output):
        sys.exit('--output or --stills required')
    episode, tline = load(args)
    if args.stills:
        prod = build(episode, tline, args)
        out = Path(args.preview_dir or Path(args.project) / 'review/stills')
        out.mkdir(parents=True, exist_ok=True)
        for s in args.stills.split(','):
            t = float(s)
            prod.frame(t).convert('RGB').save(out / f'{args.lang}-{t:07.2f}.png')
        print(f'stills -> {out}')
        return
    duration = args.duration or (tline['duration'] - args.start)
    n = args.frames or int(round(duration * FPS))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    t1 = time.time()
    if args.workers > 1:
        warnings = render_segments(args.project, args.episode, args.lang, args.timeline, args.start, n, output,
                                   args.workers, args.crf, args.aspect, args.portrait)
    else:
        prod = build(episode, tline, args)
        encode(prod, args.start, n, output, args.crf)
        warnings = prod.warnings
    project = Path(args.project)
    inputs = {str(p): sha(p) for p in [Path(args.episode), *sorted(HERE.glob('*.py')), *ink.FONT_FILES,
        *sorted((project / 'doodles').glob('*.svg')), *sorted((project / 'photos').glob('*.jpg')),
        ink.ASSETS / 'hand' / 'hand.png', ink.ASSETS / 'hand' / 'hand.json', styles.REGISTRY]}
    if args.timeline:
        inputs[str(Path(args.timeline))] = sha(args.timeline)
    manifest = {'output': str(output), 'sha256': sha(output), 'frames': n, 'fps': FPS, 'start': args.start,
                'duration': n / FPS, 'language': args.lang, 'synthetic_timing': bool(args.synthetic),
                'workers': args.workers, 'aspect': args.aspect, 'inputs': inputs, 'warnings': warnings,
                'render_seconds': round(time.time() - t1, 1)}
    if args.portrait is not None:
        manifest['portrait'] = args.portrait
    Path(str(output) + '.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'wrote {output} ({n} frames) in {time.time() - t1:.0f}s')


if __name__ == '__main__':
    main()

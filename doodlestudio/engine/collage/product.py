"""Promo stages for software you use on a computer: the page you wrote, then the app window where it is pasted, the
button the script says to press, and the drawing hand at work.

Words on screen come from the script (the page and the pasted text are the video's own narration; the button's
label is the one the script names), the storyboard's brand, or ui_kit's fixed labels. Pictures come from the
doodle library: stickers for things, and line doodles that the drawing hand traces.
"""
from __future__ import annotations

import re
from functools import lru_cache

from ... import library
from ...director import annotate
from .. import ink, motion
from . import promo, stickers, ui_kit as ui
from .elements import Board, Ink, Piece, Stroke, Swap, Tap

PAGE = (1250, 560)                  # the sheet's centre
WIN = (1190, 532, 1240, 760)        # the app window: centre x, y, width, height
PRESS = re.compile(r"^(?:(?:then|now|just|and|next),?\s+)?(?i:press|click|tap|hit)\s+(?:on\s+)?(?:the\s+)?[“\"]?"
                   r"(?P<label>[A-Z][^.!?”\"]*?)[”\"]?(?:\s+button)?[.!?]*$")
DRAWS = re.compile(r"\b(?:draws?|sketch(?:es)?|doodles?)\s+(?:(?:every|each|all|your|the|a|an|any)\s+)?([\w'’-]+)", re.I)
VOICE = re.compile(r'\b(?:voices?|narrat\w*|reads?|speaks?|says?)\b', re.I)
TROUBLE = ['fl_alarm_clock', 'fl_tear_off_calendar', 'fl_film_frames', 'fl_hourglass_not_done', 'fl_anxious_face_with_sweat']


@lru_cache(maxsize=1)
def hand():
    return ink.Hand()


def _narration(prod, width, size, hand_font=False, limit=14):
    """The video's own narration, wrapped, as many lines as fit (the last one ends with … when cut)."""
    lines = ui.wrap(' '.join(s.text.strip() for s in prod.said), prod.lang, size, width, hand=hand_font)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1].rstrip(' .,') + '…'
    return lines


def _bespoke(text, lang, k=1, meaning=True):
    """Line doodles (not emoji) for a phrase, the ones the drawing hand traces well: those named by its words first,
    then (``meaning``) those closest in meaning."""
    from ...director.match import Matcher
    m = stickers._MATCHERS.get(lang) or stickers._MATCHERS.setdefault(lang, Matcher(lang))
    hits = sorted(m.lexical(text), key=lambda h: -h.score)
    if meaning:
        hits += sorted(m.semantic(text, k + 8), key=lambda h: -h.score)
    out = []
    for h in hits:
        if not h.id.startswith('fl_') and h.id not in out:
            out.append(h.id)
    return out[:k]


# ------------------------------------------------------------------ the page
def page(prod, stage):
    """Something you wrote: a lined page with the video's own words, the key phrase underlined; then the things it
    could be pop up around it, and the work of making a video piles up on top of it."""
    els = []
    first = stage.sentences[0]
    lines = _narration(prod, 450, 30, hand_font=True)
    sheet = ui.raster(ui.script_page(lines, prod.lang))
    px, py = PAGE
    els.append(Piece(sheet, px, py, stage.start + .1, first.beat, 'page.sheet', enter='drop', cue='paper'))
    if first.emphasis:
        for k, line in enumerate(lines[:3]):
            i = line.lower().find(first.emphasis.lower())
            if i >= 0:
                x0, x1, y = ui.page_line_box(lines, k, i, i + len(first.emphasis), prod.lang)
                ox, oy = px - sheet.width / 2, py - sheet.height / 2
                pts = [(ox + x0 + (x1 - x0) * j / 12, oy + y + 12 + (2 if j % 2 else -1)) for j in range(13)]
                els.append(Stroke(pts, prod.word_time(first, first.emphasis), dur=.35, color=(239, 123, 58), width=9,
                                  beat=first.beat, ident='page.underline'))
                break
    poses = [(stage.start, 'think', 'wonder')]
    for k, s in enumerate(stage.sentences[1:], 1):
        items = promo.items_in(s.text, prod.lang)
        if s.role == 'use_cases' and items:
            els += _around(prod, s, items)
            poses.append((s.start, 'point', 'happy'))
        elif s.role in ('list', 'problem') or s.scene in ('chaos', 'chat_pileup'):
            els += _pile(prod, s, items, k)
            poses.append((s.start, 'worried', 'worried'))
        else:
            els += promo.sticker_row(prod, s, k)
    prod.pose(stage, poses)
    return els


def _around(prod, s, items):
    """Stickers for the things a page could be, around the sheet."""
    els, spots = [], [(790, 300), (1720, 270), (1735, 760), (790, 780)]
    for j, item in enumerate(items[:4]):
        x, y = spots[j]
        t = prod.word_time(s, item)
        found = stickers.find(item, prod.lang)
        img = stickers.sticker(found[0], 210) if found else None
        if img is not None:
            els.append(Piece(img, x, y, t, s.beat, f'around.{j}', tilt=(-6, 5, -4, 6)[j], energy=2))
        els.append(Piece(ui.raster(ui.label(item, prod.lang, size=34, color='#2F8F9D', paper='#FBF7EE')), x, y + 140,
                         t + .12, s.beat, f'aroundlabel.{j}', tilt=(-3, 2, -2, 3)[j], cue='tape'))
    return els


def _pile(prod, s, items, k):
    """The trouble: each named task slams onto the page as it is said, then the clutter piles up."""
    els = []
    rng = motion.seeded(prod.seed, 'pile', k)
    spots = [(1060, 400), (1450, 360), (1270, 700), (1610, 690), (1000, 760)]
    for j, item in enumerate(items[:5]):
        x, y = spots[j]
        t = prod.word_time(s, item)
        found = stickers.find(item, prod.lang)
        img = stickers.sticker(found[0], 300) if found else None
        if img is not None:
            els.append(Piece(img, x, y, t, s.beat, f'pile.{k}.{j}', enter='slam', tilt=rng.uniform(-12, 12), energy=2,
                             cue='slam'))
        els.append(Piece(ui.raster(ui.label(item, prod.lang, size=36)), x + rng.uniform(-30, 30), y + 150, t + .1,
                         s.beat, f'pilelabel.{k}.{j}', tilt=rng.uniform(-5, 5), cue='tape'))
    t_end = max(s.start + .4, s.end - .9)
    for j, doodle in enumerate(TROUBLE):
        img = stickers.sticker(doodle, 210)
        if img is not None:
            x, y = rng.uniform(760, 1820), rng.uniform(140, 960)
            els.append(Piece(img, x, y, t_end + .08 * j, s.beat, f'clutter.{k}.{j}', tilt=rng.uniform(-15, 15),
                             energy=2, cue='pop'))
    return els


# --------------------------------------------------------------- the app window
def _box(cx, cy, w, h):
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def app(prod, stage):
    """The app at work, step by step: the script is pasted in, the button is pressed, the hand draws."""
    els = []
    cx, cy, w, h = WIN
    left, top = cx - w / 2, cy - h / 2
    name = prod.brand.get('name') or prod.ep['title'][prod.lang]
    first = stage.sentences[0]
    t_in = stage.start + .1
    els.append(Piece(ui.raster(ui.app_window(name, prod.lang)), cx, cy, t_in, first.beat, 'app.window', cue='paper',
                     jitter=False))
    area = (left + 40 + 270, top + 110 + 290)          # the script box (540 x 580, label inside), centre
    lab = ui.LABELS[prod.lang]
    empty = ui.raster(ui.text_area([], prod.lang, title=lab['script'], w=540, h=580))
    panel = (left + 610, top + 200, left + w - 40, top + 200 + 340)
    els.append(Board(panel, panel, t_in + .15, dur=.01, beat=first.beat, ident='app.panel'))
    label = next((m.group('label') for s in stage.sentences if (m := PRESS.match(s.text.strip()))), None)
    button = None
    if label:
        button = (ui.raster(ui.button(label, prod.lang), 1.25), ui.raster(ui.button(f'✓ {label}', prod.lang, 'done', True), 1.25))
        bx, by = left + w - 40 - button[0].width / 2, top + 130
    board_at = next((s.start - .05 for s in stage.sentences if s.scene == 'hand_draws'), None)
    steps, filled = 0, False
    poses = [(stage.start, 'point', 'smile')]
    for k, s in enumerate(stage.sentences):
        if s.scene == 'app_paste' and not filled:
            steps += 1
            t = prod.word_time(s, s.text.split()[0]) + .3
            lines = _narration(prod, 480, 22)
            full = ui.raster(ui.text_area(lines, prod.lang, title=lab['script'], w=540, h=580))
            els.append(Swap([(t_in + .15, empty), (t, full)], *area, s.beat, 'app.script', shadow=False, cue='paper'))
            els.append(promo._number(steps, left + 12, top + 150, s.start + .05, s.beat, f'app.num.{steps}', board_at))
            filled = True
        elif s.scene == 'app_press' and button:
            steps += 1
            t_tap = prod.word_time(s, label) + .25
            els.append(Swap([(s.start - .05, button[0]), (t_tap, button[1])], bx, by, s.beat, 'app.button',
                            shadow=False))
            els.append(promo._number(steps, bx - button[0].width / 2 - 40, by - 40, s.start + .05, s.beat,
                                     f'app.num.{steps}', board_at))
            tap = stickers.sticker(stickers.TAP_HAND, 150)
            if tap is not None:
                els.append(Tap(tap, (bx + 10, by + 10), t_tap, s.beat, 'app.tap', until=s.end))
        elif s.scene == 'hand_draws':
            els += _draws(prod, s, (left + 30, top + 92, left + w - 30, top + h - 30), panel)
            poses.append((s.start, 'cheer', 'happy'))
        elif s.role == 'feature' or s.scene == 'feature_chips':
            els += promo.feature_chip(prod, s, k, column=k % 4)
        else:
            els += promo.sticker_row(prod, s, k)
    if not filled:
        els.append(Piece(empty, *area, t_in + .15, first.beat, 'app.script', shadow=False, cue=None, jitter=False))
    prod.pose(stage, poses)
    prod.brand_tag(stage, els)
    return els


def _draws(prod, s, big, small):
    """The showpiece: the video panel grows over the window and the drawing hand draws doodles in it, one after
    another, for as long as the sentence lasts (the video's own pictures: the key phrase's first, then the things the
    script lists)."""
    t0 = s.start - .05
    els = [Board(small, big, t0, beat=s.beat, ident='app.board')]
    what = DRAWS.search(s.text)
    picks = _bespoke(what.group(1) if what else s.emphasis or s.text, prod.lang)
    for other in prod.said:
        if other.role == 'use_cases':
            for item in promo.items_in(other.text, prod.lang):
                for doodle in _bespoke(item, prod.lang, meaning=False):
                    if doodle not in picks:
                        picks.append(doodle)
    span = max(1., s.end - s.start - .35)
    n = max(1, min(3, len(picks), int(span / 1.05)))
    x0, y0, x1, y1 = big
    slot = min((x1 - x0) / n - 40, y1 - y0 - 120)
    items, t = [], t0 + .5
    for j, doodle in enumerate(picks[:n]):
        path = library.resolve(doodle, prod.dir)
        if path is None:
            continue
        d = ink.svg_drawing(path, (slot, slot), speed=900., min_dur=.6, max_dur=min(1.1, span / n - .15))
        items.append((d, x0 + (x1 - x0) * (2 * j + 1) / (2 * n), (y0 + y1) / 2 - 10, t))
        t += d.duration + .14
    if items:
        els.append(Ink(items, hand(), s.beat, 'app.ink', until=None))
    i = VOICE.search(s.text)
    speaker = stickers.sticker('fl_speaker_high_volume', 120) if i else None
    if speaker is not None:
        els.append(Piece(speaker, x0 + 90, y1 - 80, prod.word_time(s, i.group(0)), s.beat, 'app.voice', energy=2))
    return els


BUILDERS = {'page': page, 'app': app}

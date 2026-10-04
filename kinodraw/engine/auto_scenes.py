"""Automatic scenes: title board, agenda board, section opener, takeaway note, transition marks."""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import ink
from .scenes import SOFT_INK, mix, sticky

UI_DEFAULTS = {
    'es': {'agenda': 'Lo que veremos', 'takeaway': 'IDEA CLAVE', 'sign': '', 'thanks': '¡Gracias por ver!'},
    'en': {'agenda': "What we'll cover", 'takeaway': 'KEY TAKEAWAY', 'sign': '', 'thanks': 'Thanks for watching'},
    'zh': {'agenda': '本期内容', 'takeaway': '本节要点', 'sign': '', 'thanks': '感谢收看'},
}
MAX_SECTIONS = 8
CARD_STRIP = .3      # portrait agenda cards keep this share of their width, on the right, for the pinned note
DECOR_DUR = 1.0     # a takeaway note's small pictures (the narrator's face, the section's pictures beside it) are
                    # quick sketches, so they fit in the moments between the headline and the pin


def ui(ep, lang):
    """UI strings: defaults overridden by the storyboard's ``ui.<lang>``."""
    return {**UI_DEFAULTS[lang], **(ep.get('ui') or {}).get(lang, {})}


def fit_title(text, lang, max_w, size, fonts=ink.FONTS):
    """One line when it fits at >= 80% of ``size``, otherwise two lines."""
    lines, fitted = ink.fit_text(text, lang, max_w, 1, size, min_size=round(size * .8), fonts=fonts)
    if len(lines) == 1:
        return lines, fitted
    return ink.fit_text(text, lang, max_w, 2, size, min_size=round(size * .55), fonts=fonts)


def narrator(ep, pose):
    """Doodle id of the narrator in ``pose`` (wave, head, present, thumbs...), or None when disabled."""
    prefix = ep.get('narrator', 'narrator')
    return None if not prefix or prefix == 'none' else f'{prefix}_{pose}'


def photo_badge(ctx, photo, diameter, x, y, t, color=ink.INK, ring_w=8):
    """Ink ring drawn by the hand, then the photo appears inside it."""
    pts = ink.circle_points(diameter / 2 + 10, diameter / 2 + 10, diameter / 2 + 3, diameter / 2 + 3, n=120)
    ring = ctx.strokes((diameter + 20, diameter + 20), [pts], color=color, width=ring_w, max_dur=.9)
    rel = ctx.add(ring, x - 10, y - 10, t)
    path = ctx.project_dir / photo if ctx.project_dir and photo else None
    if path and path.is_file():
        img = ink.circle_photo(path, diameter - 4)
        pel = ctx.add(ink.StaticDrawing(img, pop=.4), x + 2, y + 2, t, hand=False, after=rel)
        return [rel, pel]
    return [rel]


def build_title_board(ctx, beat, x0, t):
    ep = ctx.ep
    els = []
    lines, size = fit_title(ctx.T(ep.get('title')), ctx.lang, 1150, 118, ctx.fonts)
    title = ink.TextDrawing(lines, ctx.lang, size, color=ink.INK, fonts=ctx.fonts)
    els.append(ctx.add(title, x0 + 80, 150, t))
    tw = title.size[0]
    und = ctx.strokes((tw, 30), [[(6 + i * (tw - 12) / 30, 12 + 5 * math.sin(i / 2.5)) for i in range(31)]],
                      color=ink.SECTION_COLORS['orange'], width=9, max_dur=.8)
    els.append(ctx.add(und, x0 + 80, 150 + title.size[1] - 4, t))
    dy = int(size * 1.18) * (len(lines) - 1)       # a second title line pushes everything down
    if ep.get('subtitle'):
        sub = ctx.text(ctx.T(ep['subtitle']), 64, color=ink.SECTION_COLORS['blue'], max_w=1150, max_lines=1)
        els.append(ctx.add(sub, x0 + 86, 330 + dy, t))
    if ep.get('byline'):
        by = ctx.text(ctx.T(ep['byline']), 44, color=SOFT_INK, max_w=1150, max_lines=1)
        els.append(ctx.add(by, x0 + 90, 430 + dy, t))
    host = ep.get('host') or {}
    if host.get('photo'):
        els += photo_badge(ctx, host['photo'], 190, x0 + 96, 540 + dy, t)
    if host.get('badge'):
        badge = ctx.text(ctx.T(host['badge']), 42, max_w=820, max_lines=2)
        els.append(ctx.add(badge, x0 + (320 if host.get('photo') else 90), 600 + dy, t))
    wave = narrator(ep, 'wave')
    if wave:
        els.append(ctx.add(ctx.doodle(wave, (330, 500)), x0 + 1450, 250, t))
    return els


def agenda_boxes(n):
    """Card boxes (dx, y, w, h) relative to the agenda page's left edge."""
    if not 1 <= n <= MAX_SECTIONS:
        raise ValueError(f'{n} sections; the agenda supports 1–{MAX_SECTIONS}')
    if n <= 3:
        w, gap = 560, 60
        left = (1920 - (n * w + (n - 1) * gap)) / 2
        return [(left + k * (w + gap), 200, w, 620) for k in range(n)]
    if n == 4:
        return [(60 + k * 460, 200, 420, 620) for k in range(4)]
    cols = math.ceil(n / 2)
    w = (1800 - (cols - 1) * 40) / cols
    boxes = []
    for k in range(n):
        row, col = divmod(k, cols)
        in_row = cols if row == 0 else n - cols
        left = (1920 - (in_row * w + (in_row - 1) * 40)) / 2
        boxes.append((left + col * (w + 40), 190 + row * 330, w, 300))
    return boxes


def build_agenda(ctx, chapters, beats, x0):
    """Agenda page; card k is drawn while agenda beat k (or the card's trigger) is spoken."""
    t0 = ctx.time_of(beats[0], None)
    title = ctx.text(ui(ctx.ep, ctx.lang)['agenda'], 72, color=ink.INK, max_w=1700, max_lines=1)
    ctx.add(title, x0 + (1920 - title.size[0]) / 2, 86, t0)
    secs = [c for c in chapters if c['kind'] == 'section']
    cards = {}
    for k, (ch, (dx, cy, cw, chh)) in enumerate(zip(secs, agenda_boxes(len(secs)))):
        beat = beats[min(k, len(beats) - 1)]
        trig = ch.get('agenda_trigger')
        t = ctx.time_of(beat, trig) if trig else ctx.time_of(beat, None) + (.2 if k else 1.4)
        col = ink.SECTION_COLORS[ch['color']]
        cx = x0 + dx
        rect = [(6, 6), (cw - 6, 6), (cw - 6, chh - 6), (6, chh - 6), (6, 6)]
        ctx.add(ctx.strokes((cw, chh), [rect], color=col, width=8, fills=[(rect[:-1], mix(col, .9))], max_dur=.6),
                cx, cy, t)
        first = len(ctx.elements)                   # everything written inside the card (for later marks)
        sp = ch.get('speaker') or {}
        if chh >= 600:
            ctx.add(ctx.text(str(ch['number']), 150, color=col), cx + 34, cy + 10, t)
            ctx.add(ctx.text(ctx.T(ch['label']), 48, color=col, max_w=cw - 190 - (160 if sp.get('photo') else 0),
                             max_lines=1), cx + 150, cy + 60, t)
            if sp.get('photo'):
                photo_badge(ctx, sp['photo'], 130, cx + cw - 170, cy + 30, t, color=col, ring_w=6)
            if sp:
                ctx.add(ctx.text(ctx.T(sp['name']), 44, max_w=cw - 60, max_lines=1), cx + 34, cy + 200, t)
                ctx.add(ctx.text(ctx.T(sp['role']), 34, color=SOFT_INK, max_w=cw - 60, max_lines=1), cx + 34, cy + 256, t)
                hook_y = 320
            else:
                head = ctx.text(ctx.T(ch['title']), 44, max_w=cw - 60, max_lines=2, min_size=32, pace=1.6)
                ctx.add(head, cx + 34, cy + 200, t)
                hook_y = 200 + head.size[1] + 24
            if ch.get('hook'):
                hook = ctx.text(ctx.T(ch['hook']), 56, color=ink.INK, max_w=cw - 60, max_lines=2, min_size=40, pace=1.4)
                ctx.add(hook, cx + 34, cy + hook_y, t)
        else:                                   # compact card (5–8 sections): number, label, title
            ctx.add(ctx.text(str(ch['number']), 100, color=col), cx + 24, cy + 6, t)
            ctx.add(ctx.text(ctx.T(ch['label']), 40, color=col, max_w=cw - 130, max_lines=1), cx + 110, cy + 36, t)
            ctx.add(ctx.text(ctx.T(ch['title']), 40, max_w=cw - 48, max_lines=2, min_size=28, pace=1.6), cx + 24, cy + 124, t)
        cards[ch['id']] = {'box': (cx, cy, cw, chh), 'color': col, 'els': ctx.elements[first:]}
    return cards


def build_section_opener(ctx, chapter, beat, x0, t):
    col = ink.SECTION_COLORS[chapter['color']]
    sp = chapter.get('speaker')
    pose = None if sp else narrator(ctx.ep, 'present')
    text_w = 820 if pose else 1150            # the opener owns two columns (1280 px); the narrator takes the right edge
    big = ctx.text(ctx.T(chapter['label']), 170, color=col, max_w=text_w, max_lines=1)
    els = [ctx.add(big, x0 + 70, 70, t)]
    title = ctx.text(ctx.T(chapter['title']), 60, max_w=text_w, max_lines=2)
    els.append(ctx.add(title, x0 + 80, 70 + big.size[1] + 4, t))
    if not sp:
        if chapter.get('hook'):
            hook = ctx.text(ctx.T(chapter['hook']), 44, color=SOFT_INK, max_w=text_w, max_lines=2)
            els.append(ctx.add(hook, x0 + 84, 70 + big.size[1] + title.size[1] + 30, t))
        if pose:
            els.append(ctx.add(ctx.doodle(pose, (330, 500)), x0 + 925, 330, t))
        return els
    by = 500
    els += photo_badge(ctx, sp.get('photo', ''), 250, x0 + 90, by, t, color=col, ring_w=9)
    name = ctx.text(ctx.T(sp.get('name')), 64, max_w=820, max_lines=1)
    els.append(ctx.add(name, x0 + 380, by + 20, t))
    role = ctx.text(ctx.T(sp.get('role')), 44, color=col, max_w=820, max_lines=1)
    els.append(ctx.add(role, x0 + 384, by + 20 + name.size[1] + 4, t))
    show = ctx.text(f"{ctx.T(sp.get('show'))} · {ctx.T(sp.get('date'))}", 40, color=SOFT_INK, max_w=820, max_lines=2)
    show_y = by + 20 + name.size[1] + role.size[1] + 14
    els.append(ctx.add(show, x0 + 384, show_y, t))
    credit = photo_credit(ctx.project_dir, sp.get('photo', ''), ctx.lang)
    if credit:
        cimg = ink.StaticDrawing(ui_small(credit, 26, ctx.skin), pop=.3)
        cimg.dressed = True       # lettering already in the look's font and ink: a material look must not tile it
        # Under the photo, and below the show line when that wraps far enough to meet it.
        els.append(ctx.add(cimg, x0 + 90, max(by + 268, show_y + show.size[1] + 6), t, hand=False, after=els[2]))
    return els


def photo_credit(project_dir, photo, lang):
    meta = Path(project_dir) / Path(photo).with_suffix('.json') if photo and project_dir else None
    if not meta or not meta.exists():
        return ''
    line = json.loads(meta.read_text(encoding='utf-8')).get('credit_line', '')
    if lang == 'es' and line.startswith('Still: '):
        return 'Imagen: ' + line[len('Still: '):]
    if lang == 'zh' and line.startswith('Still: '):
        return '画面：' + line[len('Still: '):]
    return line


def ui_small(text, size, skin=None):
    from PIL import Image, ImageDraw
    fonts, color = (skin.fonts, skin.color((95, 104, 112))) if skin else (ink.FONTS, (95, 104, 112))
    f = ink.font('ui' if all(ord(c) < 0x2e80 for c in text) else 'zh_caption', size, fonts)
    img = Image.new('RGBA', (int(f.getlength(text)) + 8, size + 12), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((3, 3), text, font=f, fill=color + (255,))
    return img


def build_take_note(ctx, beat, chapter, x0, t, t_label=None, t_head=None):
    """Big sticky note with the section's takeaway headline; returns (note elements, bbox).

    The note is laid down at ``t``; its label and headline are written as they are said
    (``t_label``, ``t_head``). All three are essential; the narrator's face (and a sign-off)
    follow only if there is time before the note is pinned to the agenda.
    """
    strings = ui(ctx.ep, ctx.lang)
    col = ink.SECTION_COLORS[chapter['color']]
    nw, nh = 1240, 560
    nx, ny = x0 + (1920 - nw) / 2, 150
    face = narrator(ctx.ep, 'head')
    els = [ctx.add(sticky(ctx, nw, nh, tape=col), nx, ny, t, essential=True)]
    label = ctx.text(strings['takeaway'], 44, color=col)
    els.append(ctx.add(label, nx + 50, ny + 48, max(t, t_label or t), essential=True))
    head = ctx.text(ctx.T(beat['take']['headline']), 76 if ctx.lang in ('en', 'es') else 80,
                    max_w=nw - (330 if face else 100), max_lines=3, min_size=52, pace=.9)
    written = ctx.add(head, nx + 50, ny + 48 + label.size[1] + 22, max(t, t_head or t), essential=True)
    els.append(written)
    if face:
        els.append(ctx.add(ctx.doodle(face, (220, 220), max_dur=DECOR_DUR), nx + nw - 250, ny + nh - 260, t + .01,
                           optional=True,
                           after=written))
    if strings['sign']:
        sign = ctx.text(strings['sign'], 44, color=SOFT_INK)
        els.append(ctx.add(sign, nx + nw - 250 - sign.size[0] - 10, ny + nh - 90, t + .01, optional=True,
                           after=written))
    return els, (nx, ny, nw, nh + 6)


def build_end_card(ctx, x0, t):
    """Closing page, written by the hand: title, subtitle (or thanks), host badge, thumbs-up narrator."""
    ep = ctx.ep
    pose = narrator(ep, 'thumbs')
    shift = 150 if pose else 0
    lines, size = fit_title(ctx.T(ep.get('title')), ctx.lang, 1150, 120, ctx.fonts)
    brand = ink.TextDrawing(lines, ctx.lang, size, pace=1.8, fonts=ctx.fonts)
    els = [ctx.add(brand, x0 + (1920 - brand.size[0]) / 2 - shift, 240, t)]
    dy = int(size * 1.18) * (len(lines) - 1)
    second = ctx.T(ep.get('subtitle')) or ui(ep, ctx.lang)['thanks']
    sub = ink.TextDrawing([second], ctx.lang, 60, color=ink.SECTION_COLORS['blue'], pace=1.8, fonts=ctx.fonts)
    els.append(ctx.add(sub, x0 + (1920 - sub.size[0]) / 2 - shift, 400 + dy, t))
    host = ep.get('host') or {}
    if host.get('photo'):
        els += photo_badge(ctx, host['photo'], 200, x0 + 560, 530 + dy, t)
    if host.get('badge'):
        lines_b, size_b = ink.fit_text(ctx.T(host['badge']), ctx.lang, 600, 2, 40, min_size=30, fonts=ctx.fonts)
        badge = ink.TextDrawing(lines_b, ctx.lang, size_b, pace=1.8, fonts=ctx.fonts)
        bx = x0 + 790 if host.get('photo') else x0 + (1920 - badge.size[0]) / 2 - shift
        els.append(ctx.add(badge, bx, 630 + dy - badge.size[1] / 2, t))
    if pose:
        els.append(ctx.add(ctx.doodle(pose, (330, 500), max_dur=1.3), x0 + 1530, 260, t))
    return els


CREDIT_LINE = {'en': 'Made with {name}', 'zh': '由 {name} 制作', 'es': 'Hecho con {name}'}


def build_credit(ctx, x0, t):
    """The end credit, small and soft at the foot of the closing page: the app's name, then where to get it."""
    from .. import PRODUCT
    from .skin import ground_top
    made = ink.TextDrawing([CREDIT_LINE[ctx.lang].format(**PRODUCT)], ctx.lang, 40, color=SOFT_INK, pace=1.6, max_dur=1.,
                           fonts=ctx.fonts)
    url = ink.TextDrawing([PRODUCT['url']], 'en', 30, color=SOFT_INK, pace=2.5, max_dur=.6, fonts=ctx.fonts)
    y = min(1080 - 70, ground_top(ctx.skin, 1080) - 14) - made.size[1] - url.size[1]     # on the paper, above sand
    return [ctx.add(made, x0 + (1920 - made.size[0]) / 2, y, t),
            ctx.add(url, x0 + (1920 - url.size[0]) / 2, y + made.size[1], t + made.duration)]


def check_spot(box, obstacles, sizes=(150, 120, 96, 72), pad=12):
    """Where a check mark fits inside a card without touching anything written there: (size, (x, y))."""
    x, y, w, h = box

    def clear(r):
        return not any(r[0] < o[2] and o[0] < r[2] and r[1] < o[3] and o[1] < r[3] for o in obstacles)
    for s in sizes:
        for sx, sy in ((x + w - s - 20, y + 16), (x + w - s - 20, y + (h - s) / 2), (x + w - s - 20, y + h - s - 20),
                       (x + 20, y + h - s - 20)):
            if clear((sx - pad, sy - pad, sx + s + pad, sy + s + pad)):
                return s, (sx, sy)
    return sizes[-1], (x + w - sizes[-1] - 20, y + 16)


def ink_bbox(el):
    """World bbox of what an element actually inks (text images carry padding and full line width)."""
    d = el.drawing
    img = getattr(d, 'ink', None) or getattr(d, 'color', None) or getattr(d, 'image', None)
    box = img.getbbox() if img is not None else None
    return None if not box else (el.x + box[0], el.y + box[1], el.x + box[2], el.y + box[3])


def check_mark(ctx, col=(46, 157, 79), size=150):
    return ctx.strokes((size, size), [[(size * .12, size * .55), (size * .4, size * .82), (size * .9, size * .14)]],
                       color=col, width=16, max_dur=.55)


def circle_around(ctx, box, col):
    x, y, w, h = box
    W, H = w + 36, h + 36
    pts = ink.circle_points(W / 2, H / 2, W / 2 - 8, H / 2 - 8, start=-2.3, turns=1.04, n=140, wobble=.008)
    return ctx.strokes((W, H), [pts], color=col, width=9, max_dur=.75), (x - 18, y - 18)


def pin(ctx, col=(229, 57, 53)):
    pts = ink.circle_points(22, 22, 16, 16, n=40)
    return ctx.strokes((44, 44), [pts], color=ink.INK, width=4, fills=[(pts, col)], max_dur=.25, pop=.1)


def _portrait_text(ctx, text, size, width, lines=3, min_size=30, **kw):
    # TextDrawing adds 6 px of padding on each side of the measured glyphs.
    wrapped, fitted = ink.fit_text(text, ctx.lang, width - 12, lines, size, min_size=min_size, fonts=ctx.fonts)
    # At the font floor fit_text may still return extra lines or an overlong word.
    # Keep the promised line count and safe width rather than writing into the UI.
    clipped = wrapped[:lines]
    if len(wrapped) > lines:
        clipped[-1] += '…'
    for k, line in enumerate(clipped):
        if ctx.width(line, fitted) > width - 12:
            line = line.rstrip('…')
            while line and ctx.width(line + '…', fitted) > width - 12:
                line = line[:-1]
            clipped[k] = line.rstrip() + '…'
    return ink.TextDrawing(clipped, ctx.lang, fitted, fonts=ctx.fonts, **kw)


def _portrait_title(ctx, text, size, width, **kw):
    """The video's title keeps every word: three lines down to 72 px, else a fourth line down to 56 px. A word or
    link too wide even then is broken across lines (as the letterbox title is), shrinking further only if needed."""
    for lines, floor in ((3, 72), (4, 56)):
        for fitted in range(size, floor - 1, -2):
            wrapped = ctx.wrap(text, fitted, width - 12)   # a Chinese line may hang its closing mark: measure it
            if len(wrapped) <= lines and all(ctx.width(line, fitted) <= width - 12 for line in wrapped):
                return ink.TextDrawing(wrapped, ctx.lang, fitted, fonts=ctx.fonts, **kw)
    from .vertical import _wrap
    for fitted in range(56, 7, -2):
        wrapped = _wrap(text, ctx.lang, width - 12, lambda s: ctx.width(s, fitted))
        if len(wrapped) <= 4 and all(ctx.width(line, fitted) <= width - 12 for line in wrapped) or fitted <= 8:
            return ink.TextDrawing(wrapped, ctx.lang, fitted, fonts=ctx.fonts, **kw)


def _portrait_host(ctx, host, x0, y, t):
    """Stack a host photo and badge, leaving room for the screen's lower UI."""
    g = ctx.layout.g
    left, _, right, bottom = g.text_safe[1]
    els = []
    if host.get('photo') and y + 200 <= bottom:
        els += photo_badge(ctx, host['photo'], 180, x0 + left + 10, y + 10, t)
        y += 220
    if host.get('badge'):
        badge = _portrait_text(ctx, ctx.T(host['badge']), 44, right - left, lines=2, min_size=44)
        if y + badge.size[1] <= bottom:
            els.append(ctx.add(badge, x0 + left, y, t))
            y += badge.size[1] + 20
    return els, y


def build_title_board_portrait(ctx, beat, x0, t):
    g, ep = ctx.layout.g, ctx.ep
    left, y, _, _ = g.text_safe[0]
    width, bottom = g.cell_w, g.text_safe[1][3]
    title = _portrait_title(ctx, ctx.T(ep.get('title')), 110, width)
    els = [ctx.add(title, x0 + left, y, t)]
    tw = title.size[0]
    und = ctx.strokes((tw, 30), [[(6 + i * (tw - 12) / 30, 12 + 5 * math.sin(i / 2.5)) for i in range(31)]],
                      color=ink.SECTION_COLORS['orange'], width=9, max_dur=.8)
    els.append(ctx.add(und, x0 + left, y + title.size[1] - 4, t))
    y += title.size[1] + 40
    for key, size, color in (('subtitle', 60, ink.SECTION_COLORS['blue']), ('byline', 44, SOFT_INK)):
        if ep.get(key):
            text = _portrait_text(ctx, ctx.T(ep[key]), size, width, lines=2, min_size=size, color=color)
            els.append(ctx.add(text, x0 + left, y, t))
            y += text.size[1] + 20
    host, y = _portrait_host(ctx, ep.get('host') or {}, x0, y, t)
    els += host
    wave = narrator(ep, 'wave')
    if wave and y + 390 <= bottom:
        els.append(ctx.add(ctx.doodle(wave, (260, 390)), x0 + left + (width - 260) / 2, y, t))
    return els


def build_agenda_portrait(ctx, chapters, beats, x0):
    """Stack agenda cards within the text-safe width; preserve their trigger and mark contracts."""
    g = ctx.layout.g
    left, y, _, _ = g.text_safe[0]
    width, bottom = g.cell_w, g.text_safe[1][3]
    title = _portrait_text(ctx, ui(ctx.ep, ctx.lang)['agenda'], 72, width, lines=2, min_size=72)
    ctx.add(title, x0 + left, y, ctx.time_of(beats[0], None))
    y += title.size[1] + 24
    secs = [c for c in chapters if c['kind'] == 'section']
    n = len(secs)
    if not 1 <= n <= MAX_SECTIONS:
        raise ValueError(f'{n} sections; the agenda supports 1–{MAX_SECTIONS}')
    cols = 1 if n <= 3 else 2
    rows = math.ceil(n / cols)
    gap = 40 if cols == 2 else 20
    cw = (width - (cols - 1) * gap) / cols
    chh = min(260 if n <= 3 else (320 if n == 4 else 220), (bottom - y - (rows - 1) * 20) / rows)
    cards = {}
    for k, ch in enumerate(secs):
        row, column = divmod(k, cols)
        cx, cy = x0 + left + column * (cw + gap), y + row * (chh + 20)
        beat = beats[min(k, len(beats) - 1)]
        trig = ch.get('agenda_trigger')
        t = ctx.time_of(beat, trig) if trig else ctx.time_of(beat, None) + (.2 if k else 1.4)
        col = ink.SECTION_COLORS[ch['color']]
        rect = [(6, 6), (cw - 6, 6), (cw - 6, chh - 6), (6, chh - 6), (6, 6)]
        ctx.add(ctx.strokes((int(cw), int(chh)), [rect], color=col, width=8,
                            fills=[(rect[:-1], mix(col, .9))], max_dur=.6), cx, cy, t)
        first = len(ctx.elements)
        number = _portrait_text(ctx, str(ch['number']), 64 if cols == 1 else (50 if n == 4 else 40),
                                90, lines=1, color=col)
        text_w = cw - int(cw * CARD_STRIP)              # the right strip takes the takeaway's mini note later
        label = _portrait_text(ctx, ctx.T(ch['label']), 44 if cols == 1 else 36, text_w - 110,
                               lines=1, min_size=36, color=col)
        cursor = cy + 12
        ctx.add(number, cx + 20, cursor, t)
        ctx.add(label, cx + 110, cursor, t)
        cursor += max(number.size[1], label.size[1]) + 8
        head_size = 44 if cols == 1 else (40 if n == 4 else 34)
        head = _portrait_text(ctx, ctx.T(ch['title']), head_size, text_w - 20, lines=2, min_size=30, pace=1.6)
        if cursor + head.size[1] > cy + chh - 8:      # a short compact card: one line, shortened, never past its edge
            head = _portrait_text(ctx, ctx.T(ch['title']), head_size, text_w - 20, lines=1, min_size=30, pace=1.6)
        ctx.add(head, cx + 20, cursor, t)
        cards[ch['id']] = {'box': (cx, cy, cw, chh), 'color': col, 'els': ctx.elements[first:]}
    return cards


def build_section_opener_portrait(ctx, chapter, beat, x0, t):
    g = ctx.layout.g
    left, y, _, _ = g.text_safe[0]
    width, bottom = g.cell_w, g.text_safe[1][3]
    col = ink.SECTION_COLORS[chapter['color']]
    big = _portrait_text(ctx, ctx.T(chapter['label']), 150, width, lines=1, min_size=150, color=col)
    els = [ctx.add(big, x0 + left, y, t)]
    y += big.size[1] + 8
    title = _portrait_text(ctx, ctx.T(chapter['title']), 64, width, lines=3, min_size=64)
    els.append(ctx.add(title, x0 + left, y, t))
    y += title.size[1] + 20
    if chapter.get('hook'):
        hook = _portrait_text(ctx, ctx.T(chapter['hook']), 44, width, lines=2, min_size=44, color=SOFT_INK)
        els.append(ctx.add(hook, x0 + left, y, t))
        y += hook.size[1] + 20
    sp = chapter.get('speaker')
    if sp:
        # Measure the whole speaker block before deciding whether its photo fits.
        details = [_portrait_text(ctx, ctx.T(sp.get(key)), size, width, lines=2, min_size=size, color=color)
                   for key, size, color in (('name', 44, ink.INK), ('role', 36, col)) if ctx.T(sp.get(key))]
        show = ' · '.join(ctx.T(sp.get(key)) for key in ('show', 'date') if ctx.T(sp.get(key)))
        if show:
            details.append(_portrait_text(ctx, show, 34, width, lines=2, min_size=34, color=SOFT_INK))
        credit = photo_credit(ctx.project_dir, sp.get('photo', ''), ctx.lang)
        if credit:
            details.append(_portrait_text(ctx, credit, 30, width, lines=2, min_size=30, color=SOFT_INK))
        height = sum(d.size[1] + 12 for d in details)
        if y + 240 + height <= bottom:
            els += photo_badge(ctx, sp.get('photo', ''), 220, x0 + left + 10, y + 10, t, color=col, ring_w=9)
            y += 240
        for text in details:
            if y + text.size[1] <= bottom:
                els.append(ctx.add(text, x0 + left, y, t))
                y += text.size[1] + 12
    else:
        pose = narrator(ctx.ep, 'present')
        if pose and y + 390 <= bottom:
            els.append(ctx.add(ctx.doodle(pose, (260, 390)), x0 + left + (width - 260) / 2, y, t))
    return els


def build_take_note_portrait(ctx, beat, chapter, x0, t, t_label=None, t_head=None):
    g = ctx.layout.g
    strings = ui(ctx.ep, ctx.lang)
    col = ink.SECTION_COLORS[chapter['color']]
    nw, nh = g.cell_w, 600
    nx, ny = x0 + g.cell_x0, g.board_band[1] + 10     # in the board band: the chapter title stays above it
    els = [ctx.add(sticky(ctx, nw, nh, tape=col), nx, ny, t, essential=True)]
    y = ny + 32
    label = _portrait_text(ctx, strings['takeaway'], 44, nw - 64, lines=1, min_size=44, color=col)
    els.append(ctx.add(label, nx + 32, y, max(t, t_label or t), essential=True))
    y += label.size[1] + 20
    head = _portrait_text(ctx, ctx.T(beat['take']['headline']), 72, nw - 64, lines=4, min_size=52, pace=.9)
    written = ctx.add(head, nx + 32, y, max(t, t_head or t), essential=True)
    els.append(written)
    y += head.size[1] + 20
    face = narrator(ctx.ep, 'head')
    if face and y + 160 <= ny + nh - 24:
        els.append(ctx.add(ctx.doodle(face, (160, 160)), nx + nw - 184, ny + nh - 184, t + .01,
                           optional=True, after=written))
    return els, (nx, ny, nw, nh + 6)


def build_end_card_portrait(ctx, x0, t):
    g, ep = ctx.layout.g, ctx.ep
    left, y, _, _ = g.text_safe[0]
    width, bottom = g.cell_w, g.text_safe[1][3]
    title = _portrait_title(ctx, ctx.T(ep.get('title')), 100, width, align='center', pace=1.8)
    els = [ctx.add(title, x0 + left + (width - title.size[0]) / 2, y, t)]
    y += title.size[1] + 24
    second = ctx.T(ep.get('subtitle')) or ui(ep, ctx.lang)['thanks']
    sub = _portrait_text(ctx, second, 60, width, lines=2, min_size=60,
                         color=ink.SECTION_COLORS['blue'], align='center', pace=1.8)
    els.append(ctx.add(sub, x0 + left + (width - sub.size[0]) / 2, y, t))
    y += sub.size[1] + 20
    host, y = _portrait_host(ctx, ep.get('host') or {}, x0, y, t)
    els += host
    pose = narrator(ep, 'thumbs')
    if pose and y + 390 <= bottom:
        els.append(ctx.add(ctx.doodle(pose, (260, 390), max_dur=1.3), x0 + left + (width - 260) / 2, y, t))
    return els


def build_credit_portrait(ctx, x0, t):
    from .. import PRODUCT
    g = ctx.layout.g
    left, y, right, bottom = g.caption_band
    made = _portrait_text(ctx, CREDIT_LINE[ctx.lang].format(**PRODUCT), 44, right - left,
                          lines=2, min_size=44, color=SOFT_INK, pace=1.6)
    url = ink.TextDrawing([PRODUCT['url']], 'en', 34, color=SOFT_INK, pace=2.5, max_dur=.6, fonts=ctx.fonts)
    y += (bottom - y - made.size[1] - url.size[1]) / 2
    center = g.size[0] / 2
    return [ctx.add(made, x0 + center - made.size[0] / 2, y, t),
            ctx.add(url, x0 + center - url.size[0] / 2, y + made.size[1], t + made.duration)]


SCENES = {
    'landscape': {'title_board': build_title_board, 'agenda': build_agenda,
                  'section_opener': build_section_opener, 'take_note': build_take_note,
                  'end_card': build_end_card, 'credit': build_credit},
    'portrait': {'title_board': build_title_board_portrait, 'agenda': build_agenda_portrait,
                 'section_opener': build_section_opener_portrait, 'take_note': build_take_note_portrait,
                 'end_card': build_end_card_portrait, 'credit': build_credit_portrait},
}

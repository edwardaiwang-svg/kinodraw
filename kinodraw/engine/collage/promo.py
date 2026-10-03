"""Promo stages for the collage look (the Friendr-style ad): problem chat, brand reveal, how it works, the minimum
board, what people use it for, and the end card with the call to action.

Each builder gets the production and one stage (sentences with roles, times and emphasis) and returns elements.
Words on screen come from the script, the storyboard's brand, or ui_kit's fixed labels. A sentence's energy
(0-3, after the planner's budget) picks the treatment: pop, slam, punch-in, confetti.
"""
from __future__ import annotations

import re

from .. import ink, motion
from . import stickers, ui_kit as ui
from .elements import Burst, Confetti, Counter, Piece, Stroke, Swap, Tap, Typed, wobbly_ellipse

W, H = 1920, 1080
STAGE_X = 1180                      # centre of the action; the puppet stands on the left
URL = re.compile(r'\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|nl|io|app|org|net|co|ai|dev|me|so|xyz|studio|cn|de|uk|fr)\b',
                 re.I)
TIME = re.compile(r'\bin (\d+) (seconds?|minutes?|mins?|secs?)\b', re.I)
LIST_SPLIT = re.compile(r',\s*(?:or |and )?|\s+(?:or|and)\s+|、|，|或者?|和')
ASK = re.compile(r'(?:try|start|get|sign up|download|join|book|visit|go to|create your|order|shop|subscribe|立即|马上|试试|下载|注册)',
                 re.I)


def cta_sentence(sentences):
    """The call to action: the last sentence with the web address or an ask ("Try it for free"), else the last
    one marked cta."""
    ctas = [s for s in sentences if s.role == 'cta'] or sentences[-1:]
    return next((s for s in reversed(ctas) if URL.search(s.text) or ASK.match(s.text.strip())), ctas[-1])


def brand_of(prod) -> dict:
    """The storyboard's brand, filled in from the script: the brand sentence's capitalised word, a domain, the last
    call to action."""
    brand = dict(prod.ep.get('brand') or {})
    said = prod.said
    if not brand.get('name'):
        for s in said:
            if s.role == 'brand':
                words = [w.strip('.,!?') for w in s.text.split() if w[:1].isupper() and w.lower().strip('.,!?') not in
                         ('with', 'meet', 'introducing', 'there', "there's", 'this', 'the')]
                if words:
                    brand['name'] = words[-1]
                    break
    if not brand.get('url'):
        found = [m.group(0) for s in said for m in URL.finditer(s.text)]
        if found:
            brand['url'] = found[-1].lower()
    if not brand.get('cta') and said:
        text = cta_sentence(said).text.rstrip('.!。！')
        brand['cta'] = re.split(r'\s+(?:at|on|via)\s+', text)[0] if URL.search(text) else text
    return brand


def items_of(text: str) -> list[str]:
    """The things in a list sentence ("Drinks, movie night, werewolves or padel.")."""
    body = re.sub(r'^(?:and|or|so|like|such as|including)\s+', '', text.strip().rstrip('.!?。！？'), flags=re.I)
    parts = [p.strip(' .') for p in LIST_SPLIT.split(body) if p and p.strip(' .')]
    return [p for p in parts if 0 < len(p.split()) <= 4][:6]


def items_in(text: str, lang: str) -> list[str]:
    """The things a sentence lists, as the annotator finds them ("Captions, chapters and a thumbnail come with it."
    -> Captions, chapters, a thumbnail); else split at commas and "or"."""
    from ...director import annotate
    body = annotate._body(text)
    spans = annotate._zh_items(body) if lang == 'zh' else annotate._whole_list(body) or annotate._inline_list(body)
    out = []
    for a, b in spans:
        words = re.sub(r'^(?:and|or|like)\s+', '', body[a:b].strip(' ,'), flags=re.I).split()
        if len(words) > 3:                            # "a thumbnail come with it" -> "a thumbnail"
            words = words[:2] if words[0].lower() in annotate.DETS else words[:1]
        out.append(' '.join(words))
    return [x for x in out if x][:6] or items_of(text)


def _hero(prod, text, size=150, color='#EF7B3A'):
    """The brand's word mark (or the storyboard's logo image): big display letters with a paper border."""
    logo = prod.brand.get('logo_image')
    img = logo if logo is not None else ui.raster(_wordmark(text, prod.lang, size, color))
    return motion.die_cut(img, border=14)


def _wordmark(text, lang, size, color):
    fam = ui._family(lang, hand=True)
    w, h = ui.text_width(text, fam, size) + 30, size * 1.35
    return ui._doc(w, h, ui._text(15, size * 1.02, text, fam, size, fill=color))


def _energy_enter(energy):
    return 'slam' if energy >= 2 else 'pop'


# ------------------------------------------------------------------ stages
def chat(prod, stage):
    els, seed = [], prod.seed
    scale = 1.16
    phone_img = ui.raster(ui.phone(ui.LABELS[prod.lang].get('group', 'Friends'), '', prod.lang), scale)
    px, py = STAGE_X + 60, 530
    els.append(Piece(phone_img, px, py, stage.start + .1, ident=f'{stage.kind}.phone', cue='paper'))
    left, top, right, bottom = ui.screen_box()
    ox, oy = px - phone_img.width / 2, py - phone_img.height / 2
    y, count, lines = oy + top * scale + 6, 0, 0
    names = ['Max', 'Lara', 'Tim', 'Aisha', 'Sem']
    for k, s in enumerate(stage.sentences):
        m = re.search(r'\d+', s.text)
        if s.role in ('question', 'hook') or s.scene == 'chaos':
            if m:                                    # "40 messages later, who's coming?": roll the badge too
                els.append(Counter(lambda n: ui.raster(ui.badge(n), scale), count, int(m.group(0)), px + 190, oy + 34,
                                   prod.word_time(s, m.group(0)), dur=.9, beat=s.beat, ident=f'badge.{k}'))
                count = int(m.group(0))
            els += _chaos(prod, s, k)
            continue
        if m:                                        # "40 messages later": the badge rolls to the number
            els.append(Counter(lambda n: ui.raster(ui.badge(n), scale), count, int(m.group(0)), px + 190, oy + 34,
                               s.start + .15, dur=.9, beat=s.beat, ident=f'badge.{k}'))
            count = int(m.group(0))
            continue
        for j, line in enumerate(ui.chatter(prod.lang, seed + k, 1 if len(s.text) < 30 else 2)):
            if y > oy + bottom * scale - 90 or lines >= 6:
                break
            side = 'right' if lines % 2 else 'left'
            bub = ui.raster(ui.chat_bubble(line, prod.lang, side, None if side == 'right' else names[lines % 5]), scale)
            bx = ox + (right * scale - bub.width / 2 - 4 if side == 'right' else left * scale + bub.width / 2 + 4)
            els.append(Piece(bub, bx, y + bub.height / 2, s.start + .12 + .38 * j, s.beat, f'bubble.{k}.{j}',
                             shadow=False, jitter=False))
            y += bub.height + 6
            lines += 1
            count += 1
            els.append(Counter(lambda n: ui.raster(ui.badge(n), scale), count - 1, count, px + 190, oy + 34,
                               s.start + .12 + .38 * j, dur=.2, beat=s.beat, ident=f'badge.{k}.{j}'))
    prod.pose(stage, [(stage.start, 'hold_phone', 'smile')] +
              [(s.start, 'worried', 'worried') for s in stage.sentences if s.role in ('question', 'hook')])
    return els


def _chaos(prod, s, k):
    """The question that ends the problem: messages burst all over the screen."""
    rng = motion.seeded(prod.seed, 'chaos', k)
    els = []
    lines = ui.chatter(prod.lang, prod.seed + 11 + k, 12)
    for j, line in enumerate(lines):
        bub = ui.raster(ui.chat_bubble(line, prod.lang, 'left' if j % 2 else 'right', None, width=300))
        x, y = rng.uniform(640, W - 180), rng.uniform(120, H - 160)
        els.append(Piece(bub, x, y, s.start + .045 * j, s.beat, f'chaos.{k}.{j}', tilt=rng.uniform(-9, 9),
                         scale=rng.uniform(.85, 1.08), energy=2))
    return els


def brand(prod, stage):
    els = []
    name = prod.brand.get('name') or prod.ep['title'][prod.lang]
    s0 = stage.sentences[0]
    hit = next((s for s in stage.sentences if s.role == 'brand'), s0)
    t_name = prod.word_time(hit, name) if name in hit.text else hit.start + .1
    els.append(Stroke(wobbly_ellipse(960, 470, 470, 190, f'{prod.seed}.oval'), stage.start + .35, dur=.8,
                      color=(255, 255, 255), width=9, ident='brand.oval'))
    if prod.brand.get('reveal') == 'hand':           # the drawing hand writes the name, which becomes a sticker
        from .elements import Ink
        from .product import hand
        written = ink.TextDrawing([name], prod.lang, 150, color='#EF7B3A', pace=1.3, max_dur=1.2)
        els.append(Ink([(written, 960, 470, t_name - .05)], hand(), hit.beat, 'brand.written', then=_hero(prod, name)))
        prod.pose(stage, [(stage.start, 'look_up', 'wonder'), (t_name, 'wave', 'happy')])
        t_name += written.duration - .05
    else:
        els.append(Piece(_hero(prod, name), 960, 470, t_name, hit.beat, 'brand.name',
                         enter=_energy_enter(max(2, hit.energy)), energy=3, cue='slam'))
    els.append(Burst(960, 470, t_name + .08, r0=520, r1=580, n=12, ident='brand.burst'))
    for k, s in enumerate(stage.sentences):
        if s.scene == 'feature_chips':
            els += feature_chip(prod, s, k)
    if prod.brand.get('reveal') != 'hand':
        prod.pose(stage, [(stage.start, 'wave', 'happy')])
    prod.cue('riser', t_name, dur=1.0, strength=.7)            # a riser peaks on its time
    prod.cue('impact', t_name, strength=.9)
    return els


def feature_chip(prod, s, k, column=None):
    """A short claim ("No app.") on a paper strip: in a row under the brand, or stacked in the right column."""
    text = s.text.strip()
    img = ui.raster(ui.label(text, prod.lang, hand=False, size=40))
    x, y = (1700, 330 + 150 * column) if column is not None else (760 + 400 * (k % 3), 880)
    return [Piece(img, x, y, s.start + .05, s.beat, f'chip.{s.beat}.{s.i}', tilt=(-4, 3, -2)[k % 3],
                  enter=_energy_enter(s.energy), energy=s.energy, cue='tape')]


def how(prod, stage):
    els, step, chips = [], 0, 0
    uses = next((items_of(s.text) for s in prod.said if s.role == 'use_cases'), [])
    for k, s in enumerate(stage.sentences):
        if s.scene == 'feature_chips' or s.role == 'feature':
            els += feature_chip(prod, s, k, column=chips)
            chips += 1
        elif s.role == 'step' or s.scene == 'step_card':
            step += 1
            els += _step(prod, s, step, uses, stage)
        elif s.scene == 'share_link' or s.role == 'channels':
            els += _channels(prod, s)
        elif s.scene == 'rsvp' or s.role == 'social':
            els += _rsvp(prod, s)
        else:
            els += sticker_row(prod, s, k)
    prod.pose(stage, [(stage.start, 'hold_phone', 'smile')] +
                     [(s.start, 'cheer', 'happy') for s in stage.sentences if s.role == 'social'])
    prod.brand_tag(stage, els)
    return els


def _number(n, x, y, t, beat, ident, until=None):
    doc = ui._doc(84, 84, '<circle cx="42" cy="42" r="36" fill="#EF7B3A" stroke="#FFFFFF" stroke-width="6"/>' +
                  ui._text(42, 56, str(n), ui.SANS, 40, fill='#FFFFFF', anchor='middle'))
    return Piece(ui.raster(doc), x, y, t, beat, ident, energy=2, until=until)


def _step(prod, s, n, uses, stage):
    els = []
    core = TIME.sub('', s.text).strip().rstrip('.!。！')
    until = next((x.start - .1 for x in stage.sentences if x.start > s.start and x.role == 'step'), None)
    if n == 1:
        value = uses[0] if uses else (prod.brand.get('name') or core)
        label = ui.LABELS[prod.lang].get('title', 'Title')

        def render(k, core=core, value=value, label=label):
            return ui.raster(ui.form_card(core, [(label, value[:k], k < len(value))], prod.lang, w=640))
        card = Typed(render, value, STAGE_X, 470, s.start + .6, s.beat, f'step.{n}', enter_at=s.start, until=until)
        els += [card, _number(n, STAGE_X - 330, 330, s.start + .1, s.beat, f'num.{n}', until)]
        m = TIME.search(s.text)
        if m:
            clock = stickers.sticker(stickers.CLOCK, 170)
            unit = 'sec' if m.group(2).lower().startswith('s') else 'min'
            note = ui.raster(ui.label(f'{m.group(1)} {unit}!', prod.lang, size=40, color='#EF7B3A', paper='#FFF7E0'))
            t = prod.word_time(s, m.group(0))
            els += [Piece(clock, STAGE_X + 420, 300, t, s.beat, f'clock.{n}', energy=2, until=until),
                    Piece(note, STAGE_X + 430, 440, t + .2, s.beat, f'clocknote.{n}', tilt=-5, cue='tape', until=until)]
    else:
        text = prod.brand.get('url') or (s.emphasis or core)
        chip = ui.raster(ui.link_chip(text, prod.lang))
        els += [Piece(chip, STAGE_X, 230, s.start + .1, s.beat, f'link.{n}', enter=_energy_enter(s.energy),
                      energy=s.energy, until=until),
                _number(n, STAGE_X - chip.width / 2 - 30, 200, s.start, s.beat, f'num.{n}', until)]
    return els


def _channels(prod, s):
    els = []
    items = items_of(re.sub(r'^(?:in|on|by|via)\s+', '', s.text, flags=re.I)) or [s.emphasis or s.text]
    n = len(items)
    for j, item in enumerate(items):
        found = stickers.find(item, prod.lang)
        x = STAGE_X - 260 * (n - 1) / 2 + 260 * j
        if found and (img := stickers.sticker(found[0], 150)) is not None:
            els.append(Piece(img, x, 420, s.start + .15 + .25 * j, s.beat, f'chan.{s.beat}.{j}', tilt=(-6, 4, -3)[j % 3]))
        clean = re.sub(r'^(?:the|a|an|in|on|by|via)\s+', '', item, flags=re.I)
        els.append(Piece(ui.raster(ui.label(clean, prod.lang, size=30)), x, 535, s.start + .3 + .25 * j, s.beat,
                         f'chanlabel.{s.beat}.{j}', cue='tape'))
    return els


def _rsvp(prod, s):
    els = []
    lab = ui.LABELS[prod.lang]
    t_tap = s.start + max(.9, (s.end - s.start) * .6)
    button = [(s.start + .1, ui.raster(ui.button(lab['in'], prod.lang))),
              (t_tap, ui.raster(ui.button(lab['you_in'], prod.lang, style='done', pressed=True)))]
    els.append(Swap(button, STAGE_X, 865, s.beat, f'rsvp.button.{s.beat}'))
    for j in range(5):
        av = ui.avatar(j, 110)
        x, y = STAGE_X - 360 + 180 * j, 690 + (18 if j % 2 else 0)
        t = s.start + .2 + .16 * j
        els.append(Piece(motion.die_cut(av, 8), x, y, t, s.beat, f'rsvp.av.{j}'))
        els.append(Piece(ui.raster(ui.mark(j != 3), .8), x + 42, y + 44, t + .3, s.beat, f'rsvp.mark.{j}', shadow=False,
                         cue='pop'))
    hand = stickers.sticker(stickers.TAP_HAND, 150)
    if hand is not None:
        els.append(Tap(hand, (STAGE_X + 10, 880), t_tap, s.beat, f'rsvp.tap.{s.beat}'))
    return els


def threshold(prod, stage):
    els = []
    lab = ui.LABELS[prod.lang]
    total, minimum = 8, 6
    first = stage.sentences[0]
    title = prod.brand.get('name') or prod.ep['title'][prod.lang]
    card = ui.raster(ui._doc(1060, 470, '<rect x="6" y="6" width="1048" height="458" rx="16" fill="#FBF7EE" '
                                        'stroke="#D9D0BF" stroke-width="4"/>' + ui._text(60, 96, title, ui.SANS, 56)))
    els.append(Piece(card, 1010, 500, stage.start + .1, first.beat, 'thr.card', cue='paper'))
    fills, light = [], [(stage.start + .15, 'red')]
    k_low = next((s for s in stage.sentences if s is not first and s.role in ('mechanic', 'none')), first)
    k_high = stage.sentences[-1]
    low_t, high_t = k_low.start + .3, k_high.start + .2
    for j in range(3):
        fills.append(low_t + .22 * j)
    for j in range(3, 7):
        fills.append(high_t + .18 * (j - 3))
    z = 1.3
    frames = [(stage.start + .15, ui.raster(ui.slots(total, 0, minimum, prod.lang), z))]
    frames += [(t, ui.raster(ui.slots(total, j + 1, minimum, prod.lang), z)) for j, t in enumerate(fills)]
    sx, sy = 1010, 560
    els.append(Swap(frames, sx, sy, first.beat, 'thr.slots', cue=None, shadow=False))
    seats = ui.seat_centers(total)
    slots_img = frames[0][1]
    for j, t in enumerate(fills):
        cx, cy = seats[j]
        av = motion.die_cut(ui.avatar(j, 90).resize((86, 96)), 5)
        els.append(Piece(av, sx - slots_img.width / 2 + cx * z, sy - slots_img.height / 2 + cy * z, t,
                         k_high.beat if j >= 3 else k_low.beat, f'thr.av.{j}', shadow=False))
    light += [(high_t + .18 * 3 + .2, 'yellow'), (high_t + .18 * 4 + .45, 'green')]
    els.append(Swap([(t, ui.raster(ui.traffic_light(c), .95)) for t, c in light], 1730, 500, first.beat, 'thr.light'))
    t_on = light[-1][0] + .15
    els.append(Piece(ui.raster(ui.stamp(lab['on'], prod.lang), 1.25), 1360, 250, t_on, k_high.beat, 'thr.stamp', tilt=-8,
                     enter='slam', energy=3, cue='stamp'))
    if prod.allow_showpiece(t_on):
        els.append(Confetti((1180, 200), t_on + .05, ident='thr.confetti'))
    prod.pose(stage, [(stage.start, 'point', 'smile'), (low_t, 'worried', 'worried'), (t_on, 'cheer', 'happy')])
    prod.brand_tag(stage, els)
    return els


def uses(prod, stage):
    els, chips = [], []
    k_item = 0
    for k, s in enumerate(stage.sentences):
        if s.role == 'feature' or s.scene == 'feature_chips':
            chips.append(s)
            continue
        items = items_in(s.text, prod.lang) if s.role in ('use_cases', 'list') else []
        if len(items) >= 2:
            n = len(items)
            per_row = n if n <= 4 else (n + 1) // 2
            for j, item in enumerate(items):
                found = stickers.find(item, prod.lang)
                col, row = j % per_row, j // per_row
                count = min(per_row, n - row * per_row)
                x = 1110 - 350 * (count - 1) / 2 + 350 * col
                y = (420 if n <= 4 else 290 + 360 * row) + (22 if col % 2 else -10)
                t = prod.word_time(s, item)
                if found and (img := stickers.sticker(found[0], 250)) is not None:
                    els.append(Piece(img, x, y, t, s.beat, f'use.{k}.{j}', tilt=(-5, 4, -3, 6)[j % 4], energy=2))
                els.append(Piece(ui.raster(ui.label(item, prod.lang, size=40, color='#2F8F9D', paper='#FBF7EE')), x,
                                 y + 175, t + .15, s.beat, f'uselabel.{k}.{j}', tilt=(-3, 2)[j % 2], cue='tape'))
                k_item += 1
            heart = stickers.sticker(stickers.HEART, 80) if s.role == 'use_cases' else None
            if heart is not None:
                for j in range(min(3, n - 1)):
                    x = 1110 - 350 * (min(per_row, n) - 1) / 2 + 350 * j + 175
                    els.append(Piece(heart, x, 330 if n <= 4 else 470, s.end - .6 + .12 * j, s.beat, f'heart.{k}.{j}',
                                     tilt=(-10, 8, -6)[j]))
            continue
        els += _handline(prod, s, 960, 930)
    els += _chip_rows(prod, chips, 1110, 800)
    prod.pose(stage, [(stage.start, 'cheer', 'happy')])
    return els


def _chip_rows(prod, chips, cx, y, width=1180):
    """Claims ("No editing.", "No account.") on paper strips in centred rows under the stickers."""
    els, rows, row = [], [], []
    imgs = [ui.raster(ui.label(s.text.strip(), prod.lang, hand=False, size=40)) for s in chips]
    for s, img in zip(chips, imgs):
        if row and sum(i.width + 30 for _, i in row) + img.width > width:
            rows.append(row)
            row = []
        row.append((s, img))
    rows += [row] if row else []
    for r, row in enumerate(rows):
        x = cx - (sum(i.width for _, i in row) + 30 * (len(row) - 1)) / 2
        for s, img in row:
            els.append(Piece(img, x + img.width / 2, y + 110 * r, s.start + .05, s.beat, f'chip.{s.beat}.{s.i}',
                             tilt=(-3, 2, -2)[(s.i + r) % 3], enter=_energy_enter(s.energy), energy=s.energy, cue='tape'))
            x += img.width + 30
    return els


def _handline(prod, s, x, y):
    text = s.text.strip()
    if prod.brand.get('reveal') == 'hand':           # the drawing hand writes it
        from .elements import Ink
        from .product import hand
        written = ink.TextDrawing([text], prod.lang, 56, pace=1.6, max_dur=max(.8, min(2.2, s.end - s.start - .4)))
        return [Ink([(written, x, y, s.start + .1)], hand(), s.beat, f'line.{s.beat}.{s.i}')]
    fam = ui._family(prod.lang, hand=True)

    def render(k, text=text):
        return ui.raster(ui._doc(ui.text_width(text, fam, 48) + 40, 76, ui._text(20, 56, text[:k], fam, 48)))
    return [Typed(render, text, x, y, s.start + .05, s.beat, f'line.{s.beat}.{s.i}', cps=26, enter_at=s.start)]


def end(prod, stage):
    els = []
    lab = ui.LABELS[prod.lang]
    name = prod.brand.get('name') or prod.ep['title'][prod.lang]
    t0 = stage.start + .15
    els.append(Piece(_hero(prod, name, size=170), 960, 230, t0, stage.sentences[0].beat, 'end.name', enter='slam',
                     energy=3, cue='slam'))
    els.append(Burst(960, 230, t0 + .08, r0=330, r1=390, n=16, ident='end.burst'))
    cta = cta_sentence(stage.sentences)
    name_only = (prod.brand.get('name') or '').lower()
    chips = [s for s in stage.sentences if s is not cta and len(s.text) <= 32 and s.role != 'brand'
             and s.text.strip().rstrip('.!').lower() != name_only]
    imgs = [ui.raster(ui.label(s.text.strip(), prod.lang, hand=False, size=40,
                               color='#FFFFFF' if j == len(chips) - 1 else '#1B1B1B',
                               paper='#EF7B3A' if j == len(chips) - 1 else '#FFFFFF')) for j, s in enumerate(chips)]
    x = 960 - (sum(i.width for i in imgs) + 28 * (len(imgs) - 1)) / 2
    for j, (s, img) in enumerate(zip(chips, imgs)):
        last = j == len(chips) - 1
        cx = x + img.width / 2
        els.append(Piece(img, cx, 460, s.start + .05, s.beat, f'end.chip.{j}', tilt=(-3, 2, -2)[j % 3],
                         enter='slam' if last else 'pop', energy=2 if last else 1, cue='tape'))
        if last:
            els.append(Stroke([(cx + img.width / 2 - 6, 450), (cx + img.width / 2 + 16, 472),
                               (cx + img.width / 2 + 58, 412)], s.start + .3, dur=.3, color=(63, 163, 107),
                              width=11, ident=f'end.check.{j}'))
        x += img.width + 28
    cta_text = prod.brand.get('cta') or cta.text.rstrip('.!')
    button = ui.raster(ui.button(f'{cta_text} →', prod.lang), 1.5)
    t_cta = cta.start + .05
    els.append(Piece(button, 960, 630, t_cta, cta.beat, 'end.cta', enter='pop', energy=2))
    if re.search(r'\bfree\b|免费', cta.text, re.I):
        free = ui.raster(ui._doc(120, 120, '<circle cx="60" cy="60" r="52" fill="#F2C14E" stroke="#1B1B1B" '
                                 'stroke-width="4"/>' + ui._text(60, 72, lab['free'], ui.SANS, 26, anchor='middle')))
        els.append(Piece(free, 960 + button.width / 2 + 60, 585, t_cta + .25, cta.beat, 'end.free', tilt=12, energy=2))
    url = prod.brand.get('url')
    if url:
        t_url = prod.word_time(cta, url.split('.')[0]) if url.split('.')[0].lower() in cta.text.lower() else t_cta + .6
        size = 52 if ui.text_width(url, ui.SANS, 52) < 860 else 44
        u_img = ui.raster(ui._doc(ui.text_width(url, ui.SANS, size) + 20, 80, ui._text(10, 58, url, ui.SANS, size)))
        els.append(Piece(u_img, 1010, 830, t_url, cta.beat, 'end.url', shadow=False))
        els.append(Stroke([(1010 - u_img.width / 2 + 10 + k * (u_img.width - 20) / 20, 878 + (3 if k % 2 else 0))
                           for k in range(21)], t_url + .2, dur=.45, color=(239, 123, 58), width=7, ident='end.underline'))
        hand = stickers.sticker(stickers.TAP_HAND, 150)
        if hand is not None:
            els.append(Tap(hand, (960 + button.width / 2 - 70, 640), t_url + .5, cta.beat, 'end.tap'))
    t_card = prod.tl['end_card']['start']
    if prod.allow_showpiece(t_card):
        els.append(Confetti((960, 120), t_card + .2, n=220, ident='end.confetti', spread=1100))
    prod.pose(stage, [(stage.start, 'wave', 'happy')])
    prod.cue('riser', t0, dur=.9, strength=.6)
    return els


def credit(prod, t):
    """The "Made with ..." credit (the project's credit switch) on a paper slip at the foot of the last stage, in
    by ``t`` and held to the end, whatever that stage shows."""
    from ... import PRODUCT
    from ..auto_scenes import CREDIT_LINE
    img = ui.raster(ui.credit_slip(CREDIT_LINE[prod.lang].format(**PRODUCT), PRODUCT['url'], prod.lang))
    return [Piece(img, 960, 1080 - 56 - img.height / 2, t - .3, ident='credit', tilt=-1.5, energy=0, cue='paper',
                  layer=3)]


def sticker_row(prod, s, k):
    """Anything else: the sentence's pictures as stickers in a row (the director's picks, or one for its emphasis)."""
    ids = [it['doodle'] for v in prod.beat(s.beat).get('visuals', []) if v.get('type') == 'cluster'
           for it in v.get('items', []) if _said_in(prod, s, it.get('trigger'))][:3]
    if not ids:
        ids = stickers.find(s.emphasis or s.text, prod.lang)
    els, n = [], len(ids)
    for j, doodle in enumerate(ids):
        img = stickers.sticker(doodle, 230, str(prod.dir))
        if img is None:
            continue
        x = STAGE_X - 300 * (n - 1) / 2 + 300 * j
        els.append(Piece(img, x, 470, s.start + .15 + .2 * j, s.beat, f'row.{s.beat}.{s.i}.{j}',
                         enter=_energy_enter(s.energy), energy=s.energy, tilt=(-4, 5, -2)[j % 3]))
    if s.emphasis:
        els.append(Piece(ui.raster(ui.label(s.emphasis, prod.lang, size=44)), STAGE_X, 700, s.start + .35, s.beat,
                         f'rowlabel.{s.beat}.{s.i}', tilt=-2, cue='tape'))
    return els


def _said_in(prod, s, trigger):
    phrase = (trigger or {}).get(prod.lang) if isinstance(trigger, dict) else trigger
    return bool(phrase) and phrase.lower() in prod.beat(s.beat)['spoken'][prod.lang].lower()


def stickers_stage(prod, stage):
    els = []
    for k, s in enumerate(stage.sentences):
        els += sticker_row(prod, s, k)
    reaction = {'question': ('think', 'wonder'), 'hook': ('think', 'wonder'), 'number': ('point', 'surprised'),
                'reveal': ('look_up', 'surprised'), 'quote': ('wave', 'smile')}
    prod.pose(stage, [(s.start, *reaction.get(s.role, ('stand', 'smile'))) for s in stage.sentences])
    return els


BUILDERS = {'chat': chat, 'brand': brand, 'how': how, 'threshold': threshold, 'uses': uses, 'end': end,
            'stickers': stickers_stage}

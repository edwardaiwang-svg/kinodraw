"""Caption cues from display text, timed by the spoken text's measured char times.

``spoken`` and ``display`` share the same clause punctuation sequence (validated),
so clause k of the display text is timed by clause k of the spoken text. Cues
group whole clauses and must fit in <= 2 balanced lines at 70 px (never shrunk).
"""
from __future__ import annotations

import re
from functools import lru_cache

from PIL import Image, ImageDraw

from . import ink

SIZE = 70
MAX_W = 1760
EN_PUNCT = re.compile(r'[,.;:?!](?=\s|$|["”’)])|—')
ZH_PUNCT = re.compile(r'[，。；：？！、—]')
EN_WEAK = {'a', 'an', 'the', 'of', 'to', 'and', 'or', 'in', 'on', 'at', 'for', 'by', 'with', 'from', 'as',
           'that', 'is', 'was', 'his', 'her', 'its', 'their', 'my', 'our', 'your', 'but', 'if', 'than'}


def cap_font(lang):
    return ink.font('en_caption' if lang == 'en' else 'zh_caption', SIZE)


def clause_spans(text, lang):
    pat = EN_PUNCT if lang == 'en' else ZH_PUNCT
    spans, start = [], 0
    for m in pat.finditer(text):
        end = m.end()
        spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def units(text, lang):
    if lang == 'en':
        return re.findall(r'\S+\s*', text)
    return re.findall(r"[A-Za-z0-9$.,%×\-–/+'’&]+\s*|.", text)


def width(text, lang):
    return cap_font(lang).getlength(text.strip())


def balanced_lines(text, lang):
    """Return <=2 lines (balanced) or None when the text cannot fit in two lines."""
    text = text.strip()
    if width(text, lang) <= MAX_W:
        return [text]
    us = units(text, lang)
    best = None
    for k in range(1, len(us)):
        a, b = ''.join(us[:k]).strip(), ''.join(us[k:]).strip()
        if lang == 'zh' and re.match(r'[，。！？；：、）」』”’%]', b[:1] or ''):
            continue
        wa, wb = width(a, lang), width(b, lang)
        if wa > MAX_W or wb > MAX_W:
            continue
        penalty = abs(wa - wb)
        if lang == 'en':
            last = a.split()[-1].lower().strip(',.;:') if a.split() else ''
            if last in EN_WEAK:
                penalty += 400
            if len(b.split()) <= 2:
                penalty += 600
        if best is None or penalty < best[0]:
            best = (penalty, [a, b])
    return best[1] if best else None


def fits(text, lang):
    return balanced_lines(text, lang) is not None


def split_long(text, lang):
    """Split one over-long clause into pieces that each fit two lines."""
    us = units(text, lang)
    pieces, cur = [], ''
    for u in us:
        if cur and not fits(cur + u, lang):
            pieces.append(cur)
            cur = u
        else:
            cur += u
    if cur.strip():
        pieces.append(cur)
    return pieces


def cues_for_beat(spoken, display, lang, char_time, speech_end):
    """char_time(pos) -> seconds from beat start. Returns [(start, end, text)]."""
    sd, ss = clause_spans(display, lang), clause_spans(spoken, lang)
    if len(sd) != len(ss):
        # Fallback: proportional mapping (validator should prevent this).
        ss = [(round(a * len(spoken) / len(display)), round(b * len(spoken) / len(display))) for a, b in sd]
    # Expand each clause into fitting pieces with proportional spoken offsets.
    atoms = []
    for (da, db), (sa, sb) in zip(sd, ss):
        dtext = display[da:db]
        pieces = [dtext] if fits(dtext, lang) else split_long(dtext, lang)
        off = 0
        for p in pieces:
            frac = off / max(1, len(dtext))
            atoms.append((p, sa + frac * (sb - sa)))
            off += len(p)
    target = 80 if lang == 'en' else 28
    minimum = 26 if lang == 'en' else 8
    cues, cur, cur_pos = [], '', None
    for text, pos in atoms:
        trial = cur + text
        if cur and (not fits(trial, lang) or (len(cur.strip()) >= minimum and len(trial.strip()) > target)):
            cues.append((cur_pos, cur))
            cur, cur_pos = text, pos
        else:
            if not cur:
                cur_pos = pos
            cur = trial
    if cur.strip():
        cues.append((cur_pos, cur))
    # Merge a tiny trailing cue into the previous one when it still fits.
    if len(cues) >= 2 and len(cues[-1][1].strip()) < minimum and fits(cues[-2][1] + cues[-1][1], lang):
        p, t = cues[-2]
        cues[-2:] = [(p, t + cues[-1][1])]
    out = []
    for i, (pos, text) in enumerate(cues):
        start = 0. if i == 0 else max(0., char_time(int(pos)) - .05)
        out.append([start, None, text.strip()])
    for i in range(len(out)):
        out[i][1] = out[i + 1][0] if i + 1 < len(out) else speech_end
        if out[i][1] <= out[i][0]:
            out[i][1] = out[i][0] + .4
    return [tuple(c) for c in out]


@lru_cache(maxsize=2048)
def caption_image(text, lang):
    lines = balanced_lines(text, lang) or split_long(text, lang)[:2]
    f = cap_font(lang)
    stroke = 7
    lh = int(SIZE * 1.16)
    widths = [f.getlength(l) for l in lines]
    w = int(max(widths)) + 2 * stroke + 8
    h = lh * len(lines) + 2 * stroke + 10
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        x = (w - widths[i]) / 2
        d.text((x, stroke + i * lh), line, font=f, fill=(18, 18, 18, 255), stroke_width=stroke,
               stroke_fill=(255, 255, 255, 255))
    return img

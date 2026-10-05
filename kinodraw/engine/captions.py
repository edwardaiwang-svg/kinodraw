"""Caption cues from display text, timed by the spoken text's measured char times.

``spoken`` and ``display`` share the same clause punctuation sequence (validated),
so clause k of the display text is timed by clause k of the spoken text. Cues
group whole clauses and by default fit in <= 2 balanced lines at 70 px (never shrunk).
A look may supply its own two-line fit check.
"""
from __future__ import annotations

import re
from functools import lru_cache

from PIL import Image, ImageDraw

from ..ingest import CLOSERS, _outside_quotes, _sentence_spacing
from . import ink

SIZE = 70
MAX_W = 1760
EN_PUNCT = re.compile(r'[,.;:?!…](?=\s|$|["”’」』)])|—')
ES_PUNCT = re.compile(r'[,.;:?!…](?=\s|$|["”’»」』)])|—')
ZH_PUNCT = re.compile(r'[，。；：？！、—]')
EN_WEAK = {'a', 'an', 'the', 'of', 'to', 'and', 'or', 'in', 'on', 'at', 'for', 'by', 'with', 'from', 'as',
           'that', 'is', 'was', 'his', 'her', 'its', 'their', 'my', 'our', 'your', 'but', 'if', 'than'}

ES_WEAK = set('el la los las de del a al y o en por para con desde como que es era su sus mi nuestro tu pero si'.split())


def cap_font(lang, fonts=ink.FONTS):
    return ink.font('en_caption' if lang in ('en', 'es') else 'zh_caption', SIZE, fonts)


def clause_spans(text, lang):
    pat = ES_PUNCT if lang == 'es' else EN_PUNCT if lang == 'en' else ZH_PUNCT
    spans, start = [], 0
    for m in pat.finditer(text):
        end = m.end()
        spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def units(text, lang):
    if lang in ('en', 'es'):
        us = re.findall(r'\s*\S+\s*', text)
    else:
        us = re.findall(r"[A-Za-z0-9$.,%×\-–/+'’&]+\s*|.", text)
    out = []
    for u in us:
        if out and u.strip() and all(ch in CLOSERS + '.,;:?!…，。；：？！、%' for ch in u.strip()):
            out[-1] = out[-1].rstrip() + u
        else:
            out.append(u)
    return out


def width(text, lang, fonts=ink.FONTS):
    return cap_font(lang, fonts).getlength(text.strip())


def balanced_lines(text, lang, fonts=ink.FONTS):
    """Return <=2 lines (balanced) or None when the text cannot fit in two lines."""
    text = _sentence_spacing(text, lang).strip()
    if width(text, lang, fonts) <= MAX_W:
        return [text]
    us = units(text, lang)
    best = None
    for k in range(1, len(us)):
        a, b = ''.join(us[:k]).strip(), ''.join(us[k:]).strip()
        if lang == 'zh' and re.match(r'[，。！？；：、）」』”’%]', b[:1] or ''):
            continue
        wa, wb = width(a, lang, fonts), width(b, lang, fonts)
        if wa > MAX_W or wb > MAX_W:
            continue
        penalty = abs(wa - wb)
        if lang in ('en', 'es'):
            last = a.split()[-1].lower().strip(',.;:') if a.split() else ''
            if last in (ES_WEAK if lang == 'es' else EN_WEAK):
                penalty += 400
            if len(b.split()) <= 2:
                penalty += 600
        if best is None or penalty < best[0]:
            best = (penalty, [a, b])
    return best[1] if best else None


def fits(text, lang):
    return balanced_lines(text, lang) is not None


def split_long(text, lang, fits=fits):
    """Split one over-long clause into pieces accepted by the supplied fit check."""
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


def cues_for_beat(spoken, display, lang, char_time, speech_end, fits=fits):
    """char_time(pos) -> seconds from beat start; fits(text, lang) -> bool. Returns [(start, end, text)]."""
    display = _sentence_spacing(display, lang)
    sd, ss = clause_spans(display, lang), clause_spans(spoken, lang)
    # Captions include closing marks; spoken spans still index the original character times.
    for text, spans in ((display, sd), (spoken, ss)):
        joined, start = [], 0
        outside = _outside_quotes(text)
        for _, end in spans:
            if end <= start:
                continue
            while end < len(text) and text[end] in CLOSERS + '.,;:?!…，。；：？！、':
                if text[end] == '"' and outside[end] and not outside[end + 1]:
                    break
                end += 1
            joined.append((start, end))
            start = end
        spans[:] = joined
    if len(sd) != len(ss):
        # Fallback: proportional mapping (validator should prevent this).
        ss = [(round(a * len(spoken) / len(display)), round(b * len(spoken) / len(display))) for a, b in sd]
    # Expand each clause into fitting pieces with proportional spoken offsets.
    atoms = []
    for (da, db), (sa, sb) in zip(sd, ss):
        dtext = display[da:db]
        pieces = [dtext] if fits(dtext, lang) else split_long(dtext, lang, fits=fits)
        off = 0
        for p in pieces:
            frac = off / max(1, len(dtext))
            atoms.append((p, sa + frac * (sb - sa)))
            off += len(p)
    target = 80 if lang in ('en', 'es') else 28
    minimum = 26 if lang in ('en', 'es') else 8
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
def caption_image(text, lang, fonts=ink.FONTS, color=(18, 18, 18), edge=(255, 255, 255)):
    """The caption as an image: ``color`` letters inside an ``edge`` outline (a skin sets all three)."""
    lines = balanced_lines(text, lang, fonts) or split_long(text, lang)[:2]
    f = cap_font(lang, fonts)
    stroke = 7
    lh = int(SIZE * 1.16)
    widths = [f.getlength(l) for l in lines]
    w = int(max(widths)) + 2 * stroke + 8
    h = lh * len(lines) + 2 * stroke + 10
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        x = (w - widths[i]) / 2
        d.text((x, stroke + i * lh), line, font=f, fill=tuple(color) + (255,), stroke_width=stroke,
               stroke_fill=tuple(edge) + (255,))
    return img

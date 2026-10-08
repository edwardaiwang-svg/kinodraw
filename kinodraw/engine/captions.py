"""Caption cues from display text, timed by the spoken text's measured char times.

``spoken`` and ``display`` share the same clause punctuation sequence (validated),
so clause k of the display text is timed by clause k of the spoken text. Cues
group whole clauses, never run on past a sentence end, and by default fit in <= 2 balanced lines at 70 px
(never shrunk).
A look may supply its own two-line fit check.

Word highlight: every cue also carries the time each of its words is said (the spoken characters' measured times,
mapped proportionally within the clause), and the caption on screen colours the word being said in the look's
accent; the layout, outline and the other words are unchanged.
"""
from __future__ import annotations

import bisect
import colorsys
import re
import textwrap
from functools import lru_cache

from PIL import Image, ImageDraw

from ..ingest import CLOSERS, _outside_quotes, _sentence_spacing
from . import ink
from .skin import contrast

SIZE = 70
MAX_W = 1760
EN_PUNCT = re.compile(r'[,.;:?!…](?=\s|$|["”’」』)])|—')
ES_PUNCT = re.compile(r'[,.;:?!…](?=\s|$|["”’»」』)])|—')
ZH_PUNCT = re.compile(r'[，。；：？！、—]')
EN_WEAK = {'a', 'an', 'the', 'of', 'to', 'and', 'or', 'in', 'on', 'at', 'for', 'by', 'with', 'from', 'as',
           'that', 'is', 'was', 'his', 'her', 'its', 'their', 'my', 'our', 'your', 'but', 'if', 'than'}

ES_WEAK = set('el la los las de del a al y o en por para con desde como que es era su sus mi nuestro tu pero si'.split())
OPENERS = '“‘「『«(（[《【¿¡'


def cap_font(lang, fonts=ink.FONTS):
    return ink.font('en_caption' if lang in ('en', 'es') else 'zh_caption', SIZE, fonts)


def clause_marks(text, lang):
    """The clause punctuation of ``text`` (matches): the marks that split captions and that spoken and display text
    must share. A period that ends an abbreviation ("p.m.", "Dr.", "U.S.") is not one."""
    pat = ES_PUNCT if lang == 'es' else EN_PUNCT if lang == 'en' else ZH_PUNCT
    return [m for m in pat.finditer(text)
            if not (lang != 'zh' and m.group() == '.' and (_abbreviated(text[:m.end()], text[m.end():]) or _unit_dot(text, m.end())))]


def _unit_dot(text, end):
    """The period of a unit after a number in a running sentence ("3–4 ft. away", "2 in. thick"): numbers.py says
    the unit and drops it, so it is no clause break in either text."""
    from ..numbers import UNITS
    units = '|'.join(re.escape(u) for u in sorted(set(UNITS) | {'in'}, key=len, reverse=True))
    return bool(re.search(r'\d[\s-]?(?:' + units + r')\.$', text[:end]) and re.match(r'[ \t]+[a-z(]|,', text[end:]))


def clause_spans(text, lang):
    spans, start = [], 0
    for m in clause_marks(text, lang):
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
        if _needs_next(a, b):
            penalty += 5000
        if lang in ('en', 'es'):
            last = a.split()[-1].lower().strip(',.;:') if a.split() else ''
            if last in (ES_WEAK if lang == 'es' else EN_WEAK):
                penalty += 400
            if len(b.split()) <= 2:
                penalty += 600
        if best is None or penalty < best[0]:
            best = (penalty, [a, b])
    return best[1] if best else None


def _needs_next(a, b):
    """Line ``a`` ends on what belongs with the start of ``b``: "Nov." and its date, "Ext." and its number, an area
    code and its number, "#" or "No." and the number."""
    return bool(re.match(r'[\d(]', b) and re.search(
        r'(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|[Ee]xt|EXT|Nos?|Apt|Ste|Rm|Rte|Hwy)\.?|\(\d{3}\)|'
        r'\+\d{1,3}|#|\d)$', a))


_HELD = (r'(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|[Ee]xt|EXT|Nos?|Apt|Ste|Rm|Rte|Hwy)\.?|'
         r'\(\d{3}\)|\+\d{1,3}|#) (?=[\d(])')


def wrap(text, width):
    """``textwrap.wrap`` that never ends a line on what belongs with the next word (see ``_needs_next``)."""
    held = re.sub(_HELD, '\\1\u00a0', text)        # textwrap breaks only at ASCII whitespace
    return [line.replace('\u00a0', ' ') for line in textwrap.wrap(held, width, break_long_words=False)]


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


# Periods that end an abbreviation, not a sentence: titles, "a.m."/"p.m.", and initialisms such as "U.S.".
_ABBREVIATIONS = re.compile(r'(?:^|\s)(?:(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|vs|etc|e\.g|i\.e|No|Prof|Mt|a\.m|p\.m|ext)\.|'
                            r'(?:[A-Z]\.){2,})$', re.I)
# Capitalised only, so a sentence ending "in the sun." or "she sat." still ends: months, weekdays, streets, offices.
_CAPITAL_ABBREVIATIONS = re.compile(
    r'(?:^|[\s(])(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun|'
    r'Rd|Ave|Blvd|Ln|Hwy|Rte|Dept|Gov|Sen|Rep|Gen|Capt|Lt|Sgt|Col|Inc|Corp|Ltd|Co|Bros|Univ|Assn|Fig|Vol|Ch)\.$')


def _abbreviated(text, after=None):
    """Does ``text`` end with an abbreviation's period ("p.m.", "Dr.", "U.S.", "Oct.", "Rd.", "Dept.")? With the text
    ``after`` it, one that also ends the sentence ("on Elm St. Bring a bag") is a sentence's end (lexicon.py)."""
    from ..lexicon import abbreviation_period
    known = abbreviation_period(text, after)
    if known is not None:
        return known
    return bool(_ABBREVIATIONS.search(text) or _CAPITAL_ABBREVIATIONS.search(text))


def sentence_end(text):
    """Does this caption text end a sentence? A cue never runs on into the next sentence."""
    text = text.rstrip().rstrip(CLOSERS + '"”’」』)）')
    return bool(text) and text[-1] in '.!?…。！？' and not _abbreviated(text)


def cues_for_beat(spoken, display, lang, char_time, speech_end, fits=fits, words=False, gaps=()):
    """char_time(pos) -> seconds from beat start; fits(text, lang) -> bool. Returns [(start, end, text)], with
    ``words`` [(start, end, text, [the time each of word_spans(text) is said])]. ``gaps``: (start, end) seconds
    from beat start of lines said in a speech bubble instead; no caption runs across one or shows over it."""
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
            spots = [sa + (off + k) / max(1, len(dtext)) * (sb - sa) for k in range(len(p))]
            atoms.append((p, sa + frac * (sb - sa), spots))
            off += len(p)
    target = 80 if lang in ('en', 'es') else 28
    minimum = 26 if lang in ('en', 'es') else 8
    cues, cur, cur_pos, cur_spots, said = [], '', None, [], ''
    for text, pos, spots in atoms:
        trial = cur + text
        # A period inside an open quotation ("Come here. Now.") does not end the narrating sentence.
        quoted = said.count('“') > said.count('”') or said.count('"') % 2 == 1
        said += text
        # Words said either side of a line left to a speech bubble are never one caption.
        apart = cur_spots and spots and _between(gaps, char_time(int(cur_spots[-1])), char_time(int(spots[0])))
        if cur and (not fits(trial, lang) or (len(cur.strip()) >= minimum and len(trial.strip()) > target)
                    or (sentence_end(cur) and not quoted) or apart):
            cues.append((cur_pos, cur, cur_spots))
            cur, cur_pos, cur_spots = text, pos, spots
        else:
            if not cur:
                cur_pos = pos
            cur, cur_spots = trial, cur_spots + spots
    if cur.strip():
        cues.append((cur_pos, cur, cur_spots))
    # Merge a tiny trailing cue into the previous one when it still fits.
    if len(cues) >= 2 and len(cues[-1][1].strip()) < minimum and fits(cues[-2][1] + cues[-1][1], lang) \
            and not sentence_end(cues[-2][1]):
        p, t, spots = cues[-2]
        cues[-2:] = [(p, t + cues[-1][1], spots + cues[-1][2])]
    out = []
    for i, (pos, text, spots) in enumerate(cues):
        start = 0. if i == 0 else max(0., char_time(int(pos)) - .05)
        first = char_time(int(spots[0])) if spots else start
        if _between(gaps, -1., first):              # after a bubbled line: up as its own first word is said
            start = max(start, first - .05)
        lead, said = len(text) - len(text.lstrip()), [start]
        for a, _ in word_spans(text.strip(), lang):
            said.append(max(said[-1], char_time(int(spots[lead + a]))))
        out.append([start, None, text.strip(), said[1:], char_time(int(spots[-1])) if spots else start])
    for i in range(len(out)):
        until = out[i + 1][0] if i + 1 < len(out) else speech_end
        last = out[i].pop()
        bubble = _between(gaps, last, until)
        out[i][1] = min(until, max(bubble[0], last + .15)) if bubble else until   # gone when a bubbled line starts
        if out[i][1] <= out[i][0]:
            out[i][1] = out[i][0] + .4
    return [tuple(c) if words else tuple(c[:3]) for c in out]


def _between(gaps, a, b):
    """The first gap (start, end) that starts after ``a`` and before ``b``, else None."""
    return next((g for g in sorted(gaps) if a < g[0] < b), None)


def word_spans(text, lang):
    """The words a caption highlights in turn, as (start, end) in ``text``: the runs between spaces, or in Chinese
    each character with a Latin or number run as one word. Punctuation rides with a word: opening marks with the
    next one, every other mark with the one before."""
    spans, opened = [], None
    for m in re.finditer(r'\S+' if lang in ('en', 'es') else r"[A-Za-z0-9$.,%×\-–/+'’&]+|\S", text):
        a, b = m.span()
        if any(ch.isalnum() for ch in m.group()):
            spans.append((a if opened is None else opened, b))
            opened = None
        elif spans and opened is None and m.group()[0] not in OPENERS:
            spans[-1] = (spans[-1][0], b)
        elif opened is None:
            opened = a
    if opened is not None:
        spans[-1:] = [(spans[-1][0] if spans else opened, len(text.rstrip()))]
    return spans


def word_at(said, t):
    """Which of a cue's words, said at the times ``said``, is being said at ``t`` (the first until it starts, the
    last after it); None without word times."""
    return max(0, bisect.bisect_right(said, t) - 1) if said else None


@lru_cache(maxsize=64)
def highlight_color(accent, color, edge):
    """The look's accent for the word being said: as it is when it reads on the caption's outline (4.5:1) and
    stands apart from the other letters, else the same hue made only as much lighter or darker as that needs."""
    def ok(c):
        return contrast(c, edge) >= 4.5 and sum((x - y) ** 2 for x, y in zip(c, color)) >= 100 ** 2
    accent = tuple(accent[:3])
    if ok(accent):
        return accent
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in accent))
    shades = [tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, k / 100, s)) for k in range(101)]
    usable = [c for c in shades if ok(c)]
    if not usable:
        return tuple(color)
    return min(usable, key=lambda c: abs(colorsys.rgb_to_hls(*(v / 255 for v in c))[1] - l))


def word_boxes(text, lang, lines, lefts, rows, offset, size):
    """Where each word of ``text`` is on its caption image: a list of boxes per word. Line i is drawn from x =
    lefts[i] with its letters between rows[i] = (top, bottom); offset(line, j) is the advance before character j.
    Neighbouring words and lines are split halfway between their letters. None if the lines are not the text."""
    owner = []
    for k, (a, b) in enumerate(word_spans(text, lang)):
        owner += [(ch, k) for ch in text[a:b] if not ch.isspace()]
    boxes, n = [[] for _ in word_spans(text, lang)], 0
    for i, line in enumerate(lines):
        runs = []                                   # [word, first, end] character runs of one word on this line
        for j, ch in enumerate(line):
            if ch.isspace():
                continue
            if n >= len(owner) or owner[n][0] != ch:
                return None
            k = owner[n][1]
            n += 1
            if runs and runs[-1][0] == k and runs[-1][2] == j:
                runs[-1][2] = j + 1
            else:
                runs.append([k, j, j + 1])
        xs = [(lefts[i] + offset(line, a), lefts[i] + offset(line, b)) for _, a, b in runs]
        top = (rows[i - 1][1] + rows[i][0]) / 2 if i else 0
        bottom = (rows[i][1] + rows[i + 1][0]) / 2 if i + 1 < len(lines) else size[1]
        for r, (k, _, _) in enumerate(runs):
            left = (xs[r - 1][1] + xs[r][0]) / 2 if r else 0
            right = (xs[r][1] + xs[r + 1][0]) / 2 if r + 1 < len(runs) else size[0]
            boxes[k].append((round(left), round(top), round(right), round(bottom)))
    return boxes if n == len(owner) else None


def paint_word(base, lit, boxes):
    """``base`` with the pixels of ``boxes`` taken from ``lit``, the same caption lettered in the accent."""
    out = base.copy()
    for box in boxes:
        out.paste(lit.crop(box), box[:2])
    return out


@lru_cache(maxsize=2048)
def _layout(text, lang, fonts, stroke):
    lines = balanced_lines(text, lang, fonts) or split_long(text, lang)[:2]
    f = cap_font(lang, fonts)
    lh = int(SIZE * 1.16)
    widths = [f.getlength(l) for l in lines]
    return lines, f, lh, widths, int(max(widths)) + 2 * stroke + 8, lh * len(lines) + 2 * stroke + 10


@lru_cache(maxsize=2048)
def caption_image(text, lang, fonts=ink.FONTS, color=(18, 18, 18), edge=(255, 255, 255), stroke=7):
    """The caption as an image: ``color`` letters inside an ``edge`` outline (a skin sets all three)."""
    lines, f, lh, widths, w, h = _layout(text, lang, fonts, stroke)
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        x = (w - widths[i]) / 2
        d.text((x, stroke + i * lh), line, font=f, fill=tuple(color) + (255,), stroke_width=stroke,
               stroke_fill=tuple(edge) + (255,))
    return img


def caption_word_image(text, lang, fonts, color, edge, stroke=7, word=None, accent=None):
    """caption_image with the word being said (index into word_spans) in the look's ``accent``."""
    base = caption_image(text, lang, fonts, color, edge, stroke)
    if word is None or accent is None:
        return base
    return _outline_word(text, lang, fonts, tuple(color), tuple(edge), stroke, word, tuple(accent))


@lru_cache(maxsize=8)
def _outline_word(text, lang, fonts, color, edge, stroke, word, accent):
    lines, f, lh, widths, w, h = _layout(text, lang, fonts, stroke)
    tops = [stroke + i * lh for i in range(len(lines))]
    rows = [(y + f.getbbox(line)[1], y + f.getbbox(line)[3]) for y, line in zip(tops, lines)]
    boxes = word_boxes(text, lang, lines, [(w - x) / 2 for x in widths], rows,
                       lambda line, j: f.getlength(line[:j]), (w, h))
    base = caption_image(text, lang, fonts, color, edge, stroke)
    if not boxes or word >= len(boxes):
        return base
    lit = caption_image(text, lang, fonts, highlight_color(accent, color, edge), edge, stroke)
    return paint_word(base, lit, boxes[word])

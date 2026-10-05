"""Document -> storyboard skeleton: chapters and beats with display and spoken text.

Structure: intro (title board) -> preamble board (if any) -> agenda -> numbered
sections -> outro. Visuals are added later by a director (rules or LLM); this module
only decides what is said and where.

Every word written on the board is said while it is written. So a section starts with
its opener spoken ("Part 1: One machine, one idea.") while its title card is written, and
ends with its takeaway spoken ("Key takeaway: More books meant more readers.") while the
note is written; the section's own paragraphs are all narration, drawn like any other.
"""
from __future__ import annotations

import re

from .ingest import Document, Section, CLOSERS, _outside_quotes, _sentence_spacing, _sentences, _title
from .numbers import normalize

EN_BEAT = (15, 35, 55)          # min / target / max words per beat
ZH_BEAT = (30, 70, 110)         # min / target / max CJK characters per beat
MAX_SECTIONS = 8
CONCLUSION = re.compile(r'^(conclusion|summary|final thoughts|wrap[- ]?up|key takeaways|takeaways|in closing|'
                        r'(the )?(key|main|big) (ideas?|points?)|the takeaway|the bottom line|bottom line|in short|in summary|'
                        r'to sum up|recap|'
                        r'结语|总结|结论|小结|最后|要点|核心观点|conclusión|conclusiones|resumen|en resumen|para terminar|para cerrar|'
                        r'cierre|ideas? clave|en pocas palabras)\b', re.I)
TEXT = {
    'en': {'intro': 'Today: {title}', 'agenda_first': "Here's what we'll cover. First: {t}",
           'agenda_mid': ['Second: {t}', 'Third: {t}', 'Fourth: {t}', 'Fifth: {t}', 'Sixth: {t}', 'Seventh: {t}'],
           'agenda_last': 'And finally: {t}', 'label': 'Part {n}', 'closing': 'Thanks for watching!',
           'intro_label': 'Intro', 'outro_label': 'Wrap-up', 'agenda_label': "What we'll cover",
           'opener': '{label}: {title}', 'take': 'Key takeaway: {h}'},
    'es': {'intro': 'Hoy: {title}', 'agenda_first': 'Esto es lo que veremos. Primero: {t}',
           'agenda_mid': ['Segundo: {t}', 'Tercero: {t}', 'Cuarto: {t}', 'Quinto: {t}', 'Sexto: {t}', 'Séptimo: {t}'],
           'agenda_last': 'Y por último: {t}', 'label': 'Parte {n}', 'closing': '¡Gracias por ver!',
           'intro_label': 'Introducción', 'outro_label': 'Cierre', 'agenda_label': 'Lo que veremos',
           'opener': '{label}: {title}', 'take': 'Idea clave: {h}'},
    'zh': {'intro': '今天的主题：{title}', 'agenda_first': '本期我们聊{n}件事。第一，{t}',
           'agenda_mid': ['第二，{t}', '第三，{t}', '第四，{t}', '第五，{t}', '第六，{t}', '第七，{t}'],
           'agenda_last': '最后，{t}', 'label': '第{n}部分', 'closing': '感谢收看！',
           'intro_label': '开场', 'outro_label': '总结', 'agenda_label': '本期内容',
           'opener': '{label}：{title}', 'take': '本节要点：{h}'},
}
ZH_NUM = '零一二三四五六七八九十'


def size(text: str, lang: str) -> int:
    return len(text.split()) if lang in ('en', 'es') else len(re.findall(r'[一-鿿]', text))


def sentences(paragraph: str, lang: str) -> list[str]:
    return _sentences(paragraph, lang)


def _split_long(sentence: str, lang: str, limit: int) -> list[str]:
    """Split one over-long sentence at the clause mark nearest its middle (recursively)."""
    if size(sentence, lang) <= limit:
        return [sentence]
    outside = _outside_quotes(sentence)
    marks = [m.end() for m in re.finditer(r'[,;:](?=\s)|[—–]' if lang in ('en', 'es') else r'[，；：、]', sentence)
             if outside[m.end()] and sentence[m.end():].strip()]
    if not marks:
        return [sentence]
    mid = len(sentence) / 2
    cut = min(marks, key=lambda k: abs(k - mid))
    return _split_long(sentence[:cut].strip(), lang, limit) + _split_long(sentence[cut:].strip(), lang, limit)


def beats_of(paragraphs: list[str], lang: str) -> list[str]:
    """Group sentences into beats of about the target size; paragraphs never share a beat."""
    lo, target, hi = EN_BEAT if lang in ('en', 'es') else ZH_BEAT
    joiner = ' ' if lang in ('en', 'es') else ''
    out = []
    for para in paragraphs:
        para = _sentence_spacing(para, lang)
        chunks, cur = [], []
        for unit in (u for s in sentences(para, lang) for u in _split_long(s, lang, hi)):
            if cur and (size(joiner.join(cur + [unit]), lang) > hi or size(joiner.join(cur), lang) >= target):
                chunks.append(cur)
                cur = []
            cur.append(unit)
        if cur:
            if chunks and size(joiner.join(cur), lang) < lo and size(joiner.join(chunks[-1] + cur), lang) <= hi:
                chunks[-1] += cur                       # a short tail joins the previous beat
            else:
                chunks.append(cur)
        out += [joiner.join(c) for c in chunks]
    return out


def _balanced_sections(paragraphs: list[str], lang: str) -> list[Section]:
    """No usable headings: cut the paragraphs into 2–6 sections of similar length."""
    total = sum(size(p, lang) for p in paragraphs)
    k = max(2, min(6, round(total / (220 if lang in ('en', 'es') else 420)), len(paragraphs)))
    if len(paragraphs) < 2:
        return [Section('', paragraphs)]
    sections, cur, acc = [], [], 0
    for i, p in enumerate(paragraphs):
        cur.append(p)
        acc += size(p, lang)
        remaining = len(paragraphs) - i - 1
        if acc >= total * (len(sections) + 1) / k and remaining >= k - len(sections) - 1 and len(sections) < k - 1:
            sections.append(Section('', cur))
            cur = []
    if cur:
        sections.append(Section('', cur))
    return sections


def _short_title(text: str, lang: str) -> str:
    return _title(text, lang)


def _merge_to(sections: list[Section], limit: int, lang: str) -> list[Section]:
    sections = list(sections)
    while len(sections) > limit:
        sizes = [sum(size(p, lang) for p in s.paragraphs) for s in sections]
        i = min(range(len(sections) - 1), key=lambda k: sizes[k] + sizes[k + 1])
        a, b = sections[i], sections[i + 1]
        sections[i:i + 2] = [Section(a.heading or b.heading, a.paragraphs + b.paragraphs)]
    return sections


CONTEXT = {'en': re.compile(r'^(this|that|these|those|it|its|they|their|he|she|so|but|and|or|then)\b', re.I),
           'es': re.compile(r'^(esto|eso|estos|estas|esta|este|ese|esa|ellos|ellas|él|ella|así|pero|y|o|entonces|por eso)\b', re.I),
           'zh': re.compile(r'^(这|那|它|他|她|所以|但是|而且|因此)')}
NAMING = re.compile(r'\b(call|calls|called|name|names|named)\s+(this|that|these|those|it|them)\b', re.I)

ES_NAMING = re.compile(r'\b(se llama|se llaman|llamamos|llamado|llamada)\s+(esto|eso|lo)\b', re.I)


CLAIM_STOP = set('the and but for with from are was were its this that these those how why what who when where one two '
                 'not you your our their his her they can will does into than'.split())


def _stems(text: str) -> set:
    """Rough English word stems for comparing a sentence with its section title (scatters ~ scattered)."""
    return {w[:5] if len(w) > 5 else w.rstrip('s') for w in re.findall(r'[a-z]+', text.lower())
            if len(w) > 2 and w not in CLAIM_STOP}


def headline(beat_texts: list[str], fallback: str, lang: str, claim: bool = False, keep_last: bool = False) -> str:
    """Select a complete source sentence central to the section, respecting a claim title and note size."""
    floor = 4 if lang in ('en', 'es') else 8
    source = [s for text in beat_texts for s in sentences(text, lang)]
    last = source[-1] if source and not keep_last else None
    want = _stems(fallback) if claim and lang == 'en' else set()
    need = (len(want) + 1) // 2 if len(want) >= 3 else 0
    def standalone(s, title=False):
        return (bool(s.strip()) and (title or not CONTEXT[lang].match(s)) and not s.endswith(('?', '？'))
                and not re.match(r'^(?:Soon|Then|Think about|Imagine|Long ago|So|But|And|Or)\b', s, re.I)
                and not (title and re.match(r'^(?:why|how|what|which|who|when|where)\b|'
                                            r'^(?:为什么|怎么|什么|¿|por qué\b|cómo\b|qué\b|cuál\b|quién\b|cuándo\b|dónde\b)', s, re.I))
                and not (lang == 'en' and (NAMING.search(s) or re.search(r'\bis (?:called|named|known as)\b', s)))
                and not (lang == 'es' and ES_NAMING.search(s)))
    def eligible(s, cap, room):
        return (floor <= size(s, lang) <= cap and len(s) <= (room or len(s))
                and standalone(s) and len(_stems(s) & want) >= need)
    def central(fits):
        if len(fits) == 1:
            return fits[0]
        from .director.match import _model, _normalize
        import numpy as np
        vecs = _normalize(np.array(list(_model(lang).embed(source + [fallback] + fits)), np.float32))
        center = vecs[:len(source)].mean(axis=0)
        center /= np.linalg.norm(center) + 1e-9
        scores = vecs[len(source) + 1:] @ (.8 * center + .2 * vecs[len(source)])
        return fits[int(np.argmax(scores))]
    for cap, room in ((14, None), (18, 90)) if lang in ('en', 'es') else ((28, None),):
        fits = [s for s in source if s != last and eligible(s, cap, room)]
        # A final factual sentence beats a connector or question title when no earlier point fits.
        if not fits and not need and last and eligible(last, cap, room) and (
                lang == 'zh' or re.search(r'\b(?:was|were|had|felt|stopped|took|gave)\b', last)):
            fits = [last]
        if fits:
            return central(fits)
    if not standalone(fallback, title=True):
        facts = [s for s in source if standalone(s)]
        return central(facts) if facts else ''
    return sentence_of(fallback, lang)


def hook(beat_texts: list[str], lang: str) -> str:
    """A short source excerpt for the section card; never change the author's words."""
    source = [s for text in beat_texts for s in sentences(text, lang)]
    if not source:
        return ''
    text = next((s for s in source if s.endswith(('?', '？'))), source[0])
    limit = 30 if lang != 'zh' else 15
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    if lang != 'zh' and text[limit:limit + 1].isalnum():
        clipped = clipped.rsplit(' ', 1)[0]
    return clipped.rstrip(' ,，。.!?？') + '…'


def take_text(head: str, lang: str) -> str:
    """What the narrator says while the takeaway note is written: the note's own words."""
    return TEXT[lang]['take'].format(h=head)


def sync_takes(board: dict) -> dict:
    """Keep every takeaway beat saying exactly what its note shows (after an edit or an AI takeaway)."""
    lang = board['lang']
    for b in board['beats']:
        head = ((b.get('take') or {}).get('headline') or {}).get(lang)
        if b.get('kind') == 'take' and head:
            display = take_text(sentence_of(head, lang), lang)
            if b['display'].get(lang) != display:
                b['display'] = {lang: display}
                b['spoken'] = {lang: normalize(display, lang).spoken}
    return board


def sentence_of(text: str, lang: str) -> str:
    """A heading used as a spoken sentence: keep a question mark, otherwise end with a full stop."""
    text = text.strip().rstrip('.。:：;；,，')
    if text.rstrip(CLOSERS).endswith(('.', '。', '?', '？', '!', '！', '…')):
        return text
    return text + ('.' if lang in ('en', 'es') else '。')


def build(doc: Document, story: str = 'explain') -> dict:
    """The storyboard skeleton. Explainers get the full structure (spoken title, agenda, part openers, takeaways,
    sign-off); promos, stories and showcases are told straight: only the script's own sentences, then a silent end
    card, because a spoken "Part 1" or "Key takeaway" would break an ad or a story."""
    if story != 'explain':
        return _lean(doc, story)
    lang, T = doc.lang, TEXT[doc.lang]
    sections = [s for s in doc.sections if s.paragraphs]
    preamble = list(doc.preamble)
    if len(sections) < 2:                       # no usable headings: split the text evenly
        body = preamble + [p for s in sections for p in s.paragraphs]
        preamble, sections = [], _balanced_sections(body, lang)
    outro_paras = []
    if len(sections) >= 3 and CONCLUSION.match(sections[-1].heading.strip()):
        outro_paras = sections.pop().paragraphs
    sections = _merge_to(sections, MAX_SECTIONS, lang)
    titled = [bool(s.heading.strip()) for s in sections]          # the writer's own title, not one made here
    for s in sections:
        s.heading = s.heading.strip() or _short_title(s.paragraphs[0], lang)

    chapters, beats = [], []

    def beat(chapter, kind, display, **extra):
        n = normalize(display, lang)
        beats.append({'id': f'b{len(beats) + 1:03d}', 'chapter': chapter, 'kind': kind,
                      'display': {lang: display}, 'spoken': {lang: n.spoken}, 'visuals': [], **extra})
        return beats[-1]

    chapters.append({'id': 'intro', 'kind': 'intro', 'label': {lang: doc.title}, 'title': {lang: ''}})
    beat('intro', 'title', T['intro'].format(title=sentence_of(doc.title, lang)), music=True)
    if preamble:
        chapters.append({'id': 'preamble', 'kind': 'board', 'label': {lang: T['intro_label']}, 'title': {lang: ''}})
        for text in beats_of(preamble, lang):
            beat('preamble', 'narration', text)
    multi = len(sections) >= 2
    if multi:
        chapters.append({'id': 'agenda', 'kind': 'agenda', 'label': {lang: T['agenda_label']}, 'title': {lang: ''}})
        for k, s in enumerate(sections):
            t = sentence_of(s.heading, lang)
            n = '两' if len(sections) == 2 else ZH_NUM[len(sections)] if len(sections) <= 10 else len(sections)
            text = (T['agenda_first'].format(t=t, n=n)   # 两件事 (two things), never 二件事
                    if k == 0 else T['agenda_last'].format(t=t) if k == len(sections) - 1
                    else T['agenda_mid'][min(k - 1, len(T['agenda_mid']) - 1)].format(t=t))
            beat('agenda', 'agenda', text, music=True)
    for k, s in enumerate(sections, 1):
        cid = f's{k}'
        label = T['label'].format(n=k) if multi else ''
        chapters.append({'id': cid, 'kind': 'section' if multi else 'board', 'label': {lang: label},
                         'title': {lang: s.heading}})
        texts = beats_of(s.paragraphs, lang)
        if multi:
            chapters[-1]['hook'] = {lang: hook(texts, lang)}
        head = headline(texts, s.heading, lang, titled[k - 1])
        closing = s.paragraphs[-1].strip()
        if multi and len(s.paragraphs) > 1 and sentences(closing, lang) == [closing] \
                and size(closing, lang) <= (18 if lang in ('en', 'es') else 28) \
                and headline([closing], s.heading, lang, titled[k - 1], keep_last=True) == closing:
            # a one-sentence closing paragraph that sums the section up is its takeaway, said once (as the note
            # is written), not read out and then repeated straight after as "Key takeaway: ..."
            head, texts = closing, beats_of(s.paragraphs[:-1], lang)
        if multi and texts and sentences(texts[-1], lang)[-1] == head:
            # Move a final summary to the note rather than saying it twice in succession.
            texts[-1] = texts[-1][:-len(head)].rstrip()
            texts = [text for text in texts if text]
        if multi:                                   # said while the section's title card is written
            beat(cid, 'opener', T['opener'].format(label=label, title=sentence_of(s.heading, lang)))
        for text in texts:
            beat(cid, 'narration', text)
        if multi and head:                          # no note when the source contains only questions/hooks
            beat(cid, 'take', take_text(head, lang), take={'headline': {lang: head}})
    chapters.append({'id': 'outro', 'kind': 'outro', 'label': {lang: T['outro_label']}, 'title': {lang: ''}})
    for text in beats_of(outro_paras, lang):
        beat('outro', 'narration', text)
    beat('outro', 'closing', T['closing'], music=True)
    return {'version': 1, 'lang': lang, 'title': {lang: doc.title}, 'narrator': 'narrator',
            'chapters': chapters, 'beats': beats}


def _lean(doc: Document, story: str) -> dict:
    lang = doc.lang
    paragraphs = list(doc.preamble) + [p for s in doc.sections for p in s.paragraphs]
    beats = []
    for text in beats_of(paragraphs, lang):
        n = normalize(text, lang)
        beats.append({'id': f'b{len(beats) + 1:03d}', 'chapter': 'main', 'kind': 'narration',
                      'display': {lang: text}, 'spoken': {lang: n.spoken}, 'visuals': []})
    return {'version': 1, 'lang': lang, 'title': {lang: doc.title}, 'narrator': 'narrator', 'story': story,
            'chapters': [{'id': 'main', 'kind': 'board', 'label': {lang: doc.title}, 'title': {lang: ''}}],
            'beats': beats}

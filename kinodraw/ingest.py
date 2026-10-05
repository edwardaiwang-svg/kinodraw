"""Read a script (plain text, Markdown, .docx, or pasted text) into a title, a preamble and sections.

Headings come from Markdown ``#`` lines, setext underlines, or .docx Title/Heading
styles. The top heading level that yields at least two sections becomes the
sections; a single top-level heading at the start becomes the title; deeper
headings are kept as short paragraphs.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
CJK = re.compile(r'[㐀-䶿一-鿿豈-﫿]')


@dataclass
class Section:
    heading: str
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class Document:
    title: str
    lang: str                                   # 'en', 'zh' or 'es'
    preamble: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


def detect_lang(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if letters and sum(bool(CJK.match(c)) for c in letters) / len(letters) > .3:
        return 'zh'
    words = re.findall(r'[^\W\d_]+', text)
    spanish = set('el la los las de del que y en un una es por con para se no su al lo como más pero sus le ya o '
                  'este esta son también'.split())
    english = set('the and of to is in that it for was on are with as this be by you'.split())
    # English borrows Spanish names (El Niño, La Niña, José, México): capitalised words do not count as Spanish,
    # nor does an article that starts one ('El' before 'Niño'); ¿ ¡ are Spanish only.
    caps = [w[0].isupper() for w in words] + [False]
    es = (sum(w.lower() in spanish and not (caps[i] and caps[i + 1]) for i, w in enumerate(words))
          + sum(len(re.findall(r'[áéíóúüñ]', w)) for i, w in enumerate(words) if not caps[i])
          + 2 * len(re.findall(r'[¿¡]', text)))
    en = sum(w.lower() in english for w in words)
    return 'es' if es >= 2 and es > 2 * en + 1 else 'en'


def read(source: str | Path, title: str | None = None) -> Document:
    """``source`` is a file path (.txt/.md/.docx) or the script text itself."""
    path = Path(source) if isinstance(source, Path) or (len(str(source)) < 1024 and '\n' not in str(source)) else None
    if path is not None and path.is_file():
        blocks = _docx_blocks(path) if path.suffix.lower() == '.docx' else _text_blocks(path.read_text(encoding='utf-8'))
        stem = path.stem.replace('_', ' ').replace('-', ' ').strip()
        fallback = stem[:1].upper() + stem[1:]
    else:
        blocks, fallback = _text_blocks(str(source)), ''
    return _structure(blocks, title, fallback)


# ------------------------------------------------------------------ parsing
def _clean_inline(text: str) -> str:
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)                 # images
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)              # links -> text
    text = re.sub(r'(\*\*|__|\*|_|`)(?=\S)(.+?)(?<=\S)\1', r'\2', text)  # emphasis, code
    return re.sub(r'\s+', ' ', text).strip()


def _text_blocks(text: str) -> list[tuple[int, str]]:
    """[(heading level or 0 for a paragraph, text)] from Markdown or plain text."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    blocks, para = [], []

    def flush():
        if para:
            blocks.append((0, _clean_inline(' '.join(para) if not CJK.search(''.join(para)) else ''.join(para))))
            para.clear()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
        m = re.match(r'^(#{1,6})\s+(.*?)\s*#*$', line)
        if m:
            flush()
            blocks.append((len(m.group(1)), _clean_inline(m.group(2))))
        elif line and re.fullmatch(r'=+|-+', nxt) and len(nxt) >= 3 and not para:
            flush()
            blocks.append((1 if nxt[0] == '=' else 2, _clean_inline(line)))
            i += 1
        elif not line or re.fullmatch(r'(-{3,}|\*{3,}|_{3,})', line):
            flush()
        elif re.match(r'^([-*+•]|\d+[.)])\s+', line):
            flush()                                                   # list items stand alone
            blocks.append((0, _clean_inline(re.sub(r'^([-*+•]|\d+[.)])\s+', '', line))))
        else:
            para.append(line)
        i += 1
    flush()
    return [(lvl, t) for lvl, t in blocks if t]


def _docx_blocks(path: Path) -> list[tuple[int, str]]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    blocks = []
    for p in root.iter(W + 'p'):
        text = re.sub(r'\s+', ' ', ''.join(t.text or '' for t in p.iter(W + 't'))).strip()
        if not text:
            continue
        style = p.find(f'{W}pPr/{W}pStyle')
        name = (style.get(W + 'val') if style is not None else '').lower()
        m = re.match(r'heading\s*(\d)', name)
        level = 1 if name == 'title' else (int(m.group(1)) + 1 if m else 0)   # Title > Heading 1 > Heading 2
        blocks.append((level, text))
    return blocks


def _structure(blocks, title, fallback) -> Document:
    levels = sorted({lvl for lvl, _ in blocks if lvl})
    body_title = None
    if levels and blocks[0][0] == levels[0] and sum(1 for lvl, _ in blocks if lvl == levels[0]) == 1:
        body_title = blocks[0][1]                        # one top heading at the start = the title
        blocks = blocks[1:]
        levels = sorted({lvl for lvl, _ in blocks if lvl})
    section_level = next((lvl for lvl in levels if sum(1 for b, _ in blocks if b == lvl) >= 2), None)
    text = ' '.join(t for _, t in blocks)
    doc = Document(title=title or body_title or (_first_words(blocks) if blocks else fallback or 'Untitled'),
                   lang=detect_lang(text))
    current = None
    for lvl, t in blocks:
        if section_level and lvl == section_level:
            current = Section(t)
            doc.sections.append(current)
            continue
        if lvl and section_level and lvl < section_level:
            continue                                     # stray higher-level headings between sections
        if lvl:                                          # deeper heading: keep as a short paragraph
            t = t if re.search(r'[.!?…。！？:：]$', t.rstrip(CLOSERS)) else t + ('。' if doc.lang == 'zh' else '.')
        (current.paragraphs if current else doc.preamble).append(t)
    doc.sections = [s for s in doc.sections if s.paragraphs]
    return doc


QUOTES = {'"': '"', '“': '”', '‘': '’', '「': '」', '『': '』', '«': '»'}
CLOSERS = '"”’」』»)]）'
FUNCTION_WORDS = set('the of in a an and to for with at on by from his her its'.split())


def _outside_quotes(text: str) -> list[bool]:
    """Whether each character boundary is outside a quotation; apostrophes are ordinary text."""
    outside, stack = [True], []
    for i, ch in enumerate(text):
        apostrophe = (ch == '’' and i > 0 and i + 1 < len(text)
                      and text[i - 1].isalnum() and text[i + 1].isalnum()
                      and (not stack or stack[-1] != '’'
                           or re.match(r'(?:s|t|d|m|re|ve|ll)\b', text[i + 1:], re.I)
                           or (text[i - 1].isupper() and (i < 2 or not text[i - 2].isalnum()))))
        if not apostrophe:
            if stack and ch == stack[-1]:
                stack.pop()
            elif ch in QUOTES:
                stack.append(QUOTES[ch])
        outside.append(not stack)
    return outside


def _protect_periods(text: str, lang: str) -> str:
    names = (r'Sr|Sra|Srta|Dr|Dra|Prof|Ud|Uds|EE\.UU|etc' if lang == 'es' else
             r'Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e|U\.S|U\.K|No')
    text = re.sub(r'\b[A-Za-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|edu|gov|io|co|nl|es|uk)\b',
                  lambda m: m.group(0).replace('.', '\0'), text)
    text = re.sub(r'\b(?:[A-Za-z]\.){2,}', lambda m: m.group(0).replace('.', '\0'), text)
    text = re.sub(r'(?<=\d)\.(?=\d)', '\0', text)
    return re.sub(r'\b(' + names + r')\.', lambda m: m.group(0).replace('.', '\0'), text)


def _sentence_spacing(text: str, lang: str) -> str:
    if lang == 'zh':
        return text
    protected = _protect_periods(text, lang)
    outside = _outside_quotes(protected)
    def space_end(m):
        if m.end() > m.start() + len(m.group(1)):
            return m.group(1) + ' '
        for i, ch in enumerate(m.group(1)):
            if ch == '"' and outside[m.start() + i]:
                return m.group(1)[:i] + ' ' + m.group(1)[i:]
        return m.group(1) + ' '
    protected = re.sub(r'([.!?…][' + re.escape(CLOSERS) + r']*)\s*(?=[“"‘「『«¿¡(\[]*[A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9])',
                       space_end, protected)
    outside = _outside_quotes(protected)
    def space_quote(m):
        end = m.start() + len(m.group(1))
        return m.group(1) + ' ' if not outside[m.start()] and outside[end] else m.group(0)
    protected = re.sub(r'([' + re.escape(''.join(QUOTES.values())) + r']+)\s*(?=[A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9])',
                       space_quote, protected)
    return protected.replace('\0', '.')


def _sentences(text: str, lang: str) -> list[str]:
    protected = _protect_periods(text, lang) if lang != 'zh' else text
    outside = _outside_quotes(protected)
    tail = (r'(?=\s+[¿¡«“"‘「『(\[]*[A-ZÁÉÍÓÚÑÜ0-9])' if lang in ('en', 'es') else '')
    pat = r'[.!?…]+[' + re.escape(CLOSERS) + r']*' if lang != 'zh' else r'[。！？!?…]+[' + re.escape(CLOSERS) + r']*'
    parts, start = [], 0
    for m in re.finditer(pat + tail, protected):
        if outside[m.end()]:
            parts.append(protected[start:m.end()])
            start = m.end()
    return [p.replace('\0', '.').strip() for p in parts + [protected[start:]] if p.strip()]


def _title(text: str, lang: str) -> str:
    first = _sentences(_sentence_spacing(text, lang), lang)[0] if text.strip() else ''
    if lang == 'zh':
        outside = _outside_quotes(first)
        cut = next((m.start() for m in re.finditer(r'[，。！？；：]', first) if outside[m.end()]), len(first))
        clause = first[:cut]
        return clause if len(clause) <= 14 else clause[:13] + '…'
    first = ' '.join(first.split())
    words = first.split()
    if len(words) <= 10:
        return first.rstrip('.')
    outside = _outside_quotes(first)
    marks = [m.start() for m in re.finditer(r'[,;:—–]', first)
             if outside[m.end()] and len(first[:m.start()].split()) >= 3]
    if marks:
        return first[:marks[-1]].strip()
    words = words[:8]
    while words and words[-1].lower().strip('.,;:!?') in FUNCTION_WORDS:
        words.pop()
    # A title may exceed the word target to keep a quotation intact.
    cut = len(' '.join(words))
    if not outside[cut]:
        cut = next((i for i in range(cut, len(first) + 1) if outside[i]), len(first))
    return first[:cut].rstrip(' .,;:') + '…'


def _first_words(blocks) -> str:
    heading = next((t for lvl, t in blocks if lvl), None)
    first = next((t for _, t in blocks), 'Untitled')
    return heading or _title(first, detect_lang(first))

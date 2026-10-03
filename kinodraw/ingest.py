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
    lang: str                                   # 'en' or 'zh'
    preamble: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


def detect_lang(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    return 'zh' if letters and sum(bool(CJK.match(c)) for c in letters) / len(letters) > .3 else 'en'


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
    doc = Document(title=title or body_title or fallback or _first_words(blocks), lang=detect_lang(text))
    current = None
    for lvl, t in blocks:
        if section_level and lvl == section_level:
            current = Section(t)
            doc.sections.append(current)
            continue
        if lvl and section_level and lvl < section_level:
            continue                                     # stray higher-level headings between sections
        if lvl:                                          # deeper heading: keep as a short paragraph
            t = t if re.search(r'[.!?。！？:：]$', t) else t + ('。' if doc.lang == 'zh' else '.')
        (current.paragraphs if current else doc.preamble).append(t)
    doc.sections = [s for s in doc.sections if s.paragraphs]
    return doc


def _first_words(blocks) -> str:
    first = next((t for _, t in blocks), 'Untitled')
    if CJK.search(first):
        return re.split(r'[，。！？；：]', first)[0][:16]
    words = re.split(r'(?<=[.!?])\s', first)[0].split()
    return ' '.join(words[:8]).rstrip('.,;:')

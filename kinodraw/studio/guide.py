"""The user guide (docs/user-guide.md and docs/user-guide.zh.md) as the Studio's Help page.

The guide is written in a small part of Markdown: # headings, paragraphs, - and 1. lists, > lines (messages
KinoDraw shows), pictures on their own line, and **labels**, `code` and [links] inside a line. Everything is escaped
first, so the page can only show text, pictures from docs/media/guide and links.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / 'docs'     # the source tree, or the app's copy (packaging/kinodraw.spec)
PICTURES = DOCS / 'media' / 'guide'
FILES = {'en': 'user-guide.md', 'zh': 'user-guide.zh.md'}
ONLINE = 'https://github.com/edwardaiwang-svg/kinodraw/blob/main/docs/'


def page(lang: str) -> dict:
    if lang not in FILES:
        raise ValueError('The guide is in English (en) and Chinese (zh).')
    return {'lang': lang, 'html': render((DOCS / FILES[lang]).read_text(encoding='utf-8'))}


def _link(label: str, target: str) -> str:
    target = html.unescape(target)
    other = {name: lang for lang, name in FILES.items()}
    if target in other:                                           # the guide in the other language
        return f'<a href="#" data-guide="{other[target]}">{label}</a>'
    url = target if re.match(r'(https?|mailto):', target) else ONLINE + target
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{label}</a>'


def _inline(text: str) -> str:
    out = html.escape(text, quote=True)
    out = re.sub(r'`([^`]+)`', r'<code>\1</code>', out)
    out = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', out)
    return re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', lambda m: _link(m[1], m[2]), out)


def render(text: str) -> str:
    out, block, kind = [], [], None

    def flush():
        nonlocal block, kind
        if kind == 'p':
            out.append(f'<p>{_inline(" ".join(block))}</p>')
        elif kind in ('ul', 'ol'):
            out.append(f'<{kind}>' + ''.join(f'<li>{_inline(item)}</li>' for item in block) + f'</{kind}>')
        elif kind == 'quote':
            out.append('<blockquote>' + '<br>'.join(_inline(line) for line in block) + '</blockquote>')
        block, kind = [], None

    for line in text.splitlines():
        line = line.rstrip()
        heading = re.match(r'(#{1,3}) (.+)', line)
        item = re.match(r'(-|\d+\.) (.+)', line)
        picture = re.fullmatch(r'!\[([^\]]*)\]\(media/guide/([\w.-]+)\)', line)
        if not line or heading or picture:
            flush()
        if heading:
            out.append(f'<h{len(heading[1])}>{_inline(heading[2])}</h{len(heading[1])}>')
        elif picture:
            out.append(f'<img alt="{html.escape(picture[1])}" src="/guide/media/guide/{picture[2]}">')
        elif item or line.startswith('> '):
            now = 'quote' if line.startswith('> ') else 'ol' if item[1][0].isdigit() else 'ul'
            if kind != now:
                flush()
                kind = now
            block.append(line[2:] if now == 'quote' else item[2])
        elif line and kind in ('ul', 'ol'):                   # a list item that goes on to the next line
            block[-1] += ' ' + line.strip()
        elif line:
            if kind != 'p':
                flush()
                kind = 'p'
            block.append(line)
    flush()
    return '\n'.join(out)


def picture(name: str) -> Path | None:
    """A picture the guide shows (docs/media/guide/NAME), or None for anything else."""
    path = (PICTURES / name).resolve()
    return path if path.parent == PICTURES.resolve() and path.suffix in ('.jpg', '.png') and path.is_file() else None

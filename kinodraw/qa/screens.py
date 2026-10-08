"""Content QA for device screens: text the script shows on a phone, tablet or laptop (a text message, a notification)
must be on a drawn screen while it is read. The renderer records every screen it draws and the strings on it in
build/ui-screens.json (engine/ui_screens.record); a quoted message or notification with no screen showing its words
is a finding (a blank phone while a text is read fails).
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _norm(text: str) -> str:
    return re.sub(r'[\W_]+', ' ', text or '').strip().casefold()


def check(board: dict, video=None) -> list[dict]:
    """Findings ({'check': 'blank_screen', 'problem', 'at'}) for the shown text of ``board`` that no drawn screen in
    the video's build/ui-screens.json shows. Without a video there is nothing drawn to check."""
    if video is None:
        return []
    from .. import ui_screens
    from ..director.v3.semantics import beats
    texts = [(b['id'], b['text']) for b in beats(board)]
    wanted = [m for m in ui_screens.read(texts) if m['kind'] in ('message', 'notification') and not m.get('replay')]
    if not wanted:
        return []
    path = Path(video).parent / 'build' / 'ui-screens.json'
    rows = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
    out = []
    for m in wanted:
        words = _norm(m.get('text'))
        hit = next((r for r in rows if r['beat'] == m['beat'] and any(words and words in _norm(s)
                                                                       for s in r['strings'])), None)
        if hit is None:
            out.append({'check': 'blank_screen', 'at': None,
                        'problem': f'The {m["kind"]} "{m.get("text", "")[:60]}" is read but no phone or screen '
                                   'shows it.'})
    return out

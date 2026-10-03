"""Check a storyboard before voice and render: structure, spoken/display parity, triggers, doodles.

Errors make the result unusable (the renderer or timing would break); warnings are
quality notes. Both the rules director and LLM output must pass.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..engine.storyboard import KINDS
from ..library import banned, resolve

SLOT_TYPES = {'cluster', 'quote', 'glossary', 'stat'}
PAGE_TYPES = {'ladder', 'bars', 'coins', 'grid100', 'lanes', 'range', 'zones', 'levels', 'table', 'dial', 'flow',
              'split', 'calendar'}
OTHER_TYPES = {'emphasis', 'stock'}
EN_PUNCT = re.compile(r'[,.;:?!](?=\s|$|["”’)])|—')
ZH_PUNCT = re.compile(r'[，。；：？！、—]')
MAX_SECTIONS = 8


def _triggers(value, path=''):
    """Yield (path, trigger dict) for every trigger in a visual, however deeply nested."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'trigger' and isinstance(item, dict):
                yield path, item
            else:
                yield from _triggers(item, f'{path}.{key}' if path else key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _triggers(item, f'{path}[{i}]')


def _doodles(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'doodle' and isinstance(item, str):
                yield item
            else:
                yield from _doodles(item)
    elif isinstance(value, list):
        for item in value:
            yield from _doodles(item)


def validate(board: dict, project_dir: Path | None = None) -> dict:
    lang = board.get('lang')
    errors, warnings = [], []
    if lang not in ('en', 'zh'):
        return {'ok': False, 'errors': [f'lang must be en or zh, got {lang!r}'], 'warnings': []}
    chapters = board.get('chapters') or []
    ids = [c.get('id') for c in chapters]
    if len(ids) != len(set(ids)):
        errors.append('duplicate chapter ids')
    for c in chapters:
        if c.get('kind') not in KINDS:
            errors.append(f"chapter {c.get('id')}: kind {c.get('kind')!r} not in {sorted(KINDS)}")
    sections = [c for c in chapters if c.get('kind') == 'section']
    if len(sections) > MAX_SECTIONS:
        errors.append(f'{len(sections)} sections; the agenda holds at most {MAX_SECTIONS}')
    if sections and not any(c.get('kind') == 'agenda' for c in chapters):
        errors.append('sections need an agenda chapter')
    beats = board.get('beats') or []
    by_id = {b.get('id'): b for b in beats}
    if len(by_id) != len(beats):
        errors.append('duplicate beat ids')
    order = [b.get('chapter') for b in beats]
    runs = [c for i, c in enumerate(order) if i == 0 or order[i - 1] != c]
    if len(runs) != len(set(runs)):
        errors.append('beats of one chapter must be contiguous')
    if [c for c in ids if c in set(order)] != runs:
        errors.append('beat order does not follow chapter order')
    for c in chapters:
        if c.get('id') not in order:
            errors.append(f"chapter {c.get('id')} has no beats")
    visual_ids = set()
    punct = EN_PUNCT if lang == 'en' else ZH_PUNCT
    for b in beats:
        bid = b.get('id')
        spoken = (b.get('spoken') or {}).get(lang, '')
        display = (b.get('display') or {}).get(lang, '')
        if not spoken.strip() or not display.strip():
            errors.append(f'{bid}: empty spoken or display text')
            continue
        if re.search(r'\d', spoken):
            errors.append(f'{bid}: digits in spoken text ({spoken[:50]})')
        if punct.findall(spoken) != punct.findall(display):
            errors.append(f'{bid}: clause punctuation differs between spoken and display text')
        chapter = next((c for c in chapters if c.get('id') == b.get('chapter')), None)
        if chapter is None:
            errors.append(f'{bid}: unknown chapter {b.get("chapter")}')
            continue
        if b.get('kind') == 'take' and chapter.get('kind') == 'section':
            head = ((b.get('take') or {}).get('headline') or {}).get(lang, '')
            if not head:
                errors.append(f'{bid}: take beat without a headline')
            elif len(head.split() if lang == 'en' else head) > (16 if lang == 'en' else 30):
                warnings.append(f'{bid}: long takeaway headline')
        for v in b.get('visuals') or []:
            vid, vtype = v.get('id'), v.get('type')
            if not vid or vid in visual_ids:
                errors.append(f'{bid}: visual id missing or duplicated ({vid})')
            visual_ids.add(vid)
            if vtype not in SLOT_TYPES | PAGE_TYPES | OTHER_TYPES:
                errors.append(f'{bid}/{vid}: unknown visual type {vtype!r}')
            for where, trig in _triggers(v):
                ref = by_id.get(trig.get('beat'), b)
                phrase = trig.get(lang)
                if phrase and phrase not in (ref.get('spoken') or {}).get(lang, ''):
                    errors.append(f'{bid}/{vid} {where}: trigger {phrase!r} is not in the spoken text')
            for did in _doodles(v):
                if resolve(did, project_dir) is None:
                    errors.append(f'{bid}/{vid}: doodle {did!r} not found')
                elif did in banned()['doodles']:
                    warnings.append(f'{bid}/{vid}: {did!r} is a banned picture (no director picks it)')
            if vtype == 'cluster' and not 1 <= len(v.get('items') or []) <= 3:
                errors.append(f'{bid}/{vid}: a cluster needs 1-3 items')
    for b in beats:
        for v in b.get('visuals') or []:
            if v.get('type') == 'emphasis' and str(v.get('target', '')).split('.')[0] not in visual_ids:
                errors.append(f"{b['id']}/{v.get('id')}: emphasis target {v.get('target')!r} is unknown")
    return {'ok': not errors, 'errors': errors, 'warnings': warnings}

"""Check a storyboard before voice and render: structure, spoken/display parity, triggers, doodles.

Errors make the result unusable (the renderer or timing would break); warnings are
quality notes. Both the rules director and LLM output must pass. The direction dials
(look, story, motion, brand) and each beat's sentence directions (director/annotate.py)
are optional; when present they are checked too.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..engine.storyboard import DIALS, KINDS
from ..library import OWN, _missing_picture, banned, own_path, resolve
from .annotate import ROLES, SCENES, _words

SLOT_TYPES = {'cluster', 'quote', 'glossary', 'stat'}
PAGE_TYPES = {'ladder', 'bars', 'coins', 'grid100', 'lanes', 'range', 'zones', 'levels', 'table', 'dial', 'flow',
              'split', 'calendar'}
OTHER_TYPES = {'emphasis', 'stock', 'scientific'}
EN_PUNCT = re.compile(r'[,.;:?!](?=\s|$|["”’)])|—')
ES_PUNCT = re.compile(r'[,.;:?!](?=\s|$|["”’»)])|—')
ZH_PUNCT = re.compile(r'[，。；：？！、—]')
MAX_SECTIONS = 8
BRAND_KEYS = ('name', 'url', 'cta')


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _direction(b: dict, display: str, lang: str, library: list, errors: list, warnings: list):
    """A beat's sentence directions: spans inside its text, known roles, energies 0-3, a scene among its options,
    emphasis cut from its sentence."""
    bid, direction = b.get('id'), b.get('direction')
    if not isinstance(direction, list):
        errors.append(f'{bid}: direction must be a list')
        return
    seen = set()
    for e in direction:
        if not isinstance(e, dict):
            errors.append(f'{bid}: a direction entry must be an object')
            continue
        where = f"{bid}/direction[{e.get('i')}]"
        if not _int(e.get('i')) or e['i'] in seen:
            errors.append(f'{where}: sentence index missing or duplicated')
        else:
            seen.add(e['i'])
        span, options = e.get('span'), e.get('options') if isinstance(e.get('options'), dict) else {}
        if not (isinstance(span, list) and len(span) == 2 and all(_int(x) for x in span)
                and 0 <= span[0] < span[1] <= len(display)):
            errors.append(f'{where}: span {span!r} is not inside the display text')
            continue
        sentence = display[span[0]:span[1]]
        if not isinstance(e.get('role'), str) or e['role'] not in ROLES:
            errors.append(f"{where}: role {e.get('role')!r} not in {sorted(ROLES)}")
        if not _int(e.get('energy')) or not 0 <= e['energy'] <= 3:
            errors.append(f"{where}: energy must be 0-3, got {e.get('energy')!r}")
        scenes = options.get('scene') if isinstance(options.get('scene'), list) else []
        if e.get('scene') not in scenes:
            errors.append(f"{where}: scene {e.get('scene')!r} is not one of its options {scenes}")
        elif library and e['scene'] not in library:
            warnings.append(f"{where}: scene {e['scene']!r} is not in this look's library (annotate again)")
        phrases = options.get('emphasis') if isinstance(options.get('emphasis'), list) else []
        for phrase in [e.get('emphasis', '')] + phrases:
            if not isinstance(phrase, str) or (phrase and phrase not in sentence):
                errors.append(f'{where}: emphasis {phrase!r} is not in the sentence')
                break
        if len(scenes) > 3 or len(phrases) > 4 or any(isinstance(p, str) and _words(p, lang) > 3 for p in phrases):
            warnings.append(f'{where}: more options than an LLM is offered (3 scenes, 4 phrases of 3 words)')
        band = options.get('energy')
        if band is not None and not (isinstance(band, list) and len(band) == 2 and all(_int(x) for x in band)
                                     and 0 <= band[0] <= band[1] <= 3):
            errors.append(f'{where}: energy options must be [low, high] within 0-3, got {band!r}')
        if not isinstance(e.get('source'), str) or not e['source']:
            errors.append(f'{where}: source missing')


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
    if lang not in ('en', 'zh', 'es'):
        return {'ok': False, 'errors': [f'lang must be en, zh or es, got {lang!r}'], 'warnings': []}
    for dial, values in DIALS.items():
        if dial in board and board[dial] not in values:
            errors.append(f'{dial} must be one of {", ".join(values)}, got {board[dial]!r}')
    brand = board.get('brand')
    if brand is not None and (not isinstance(brand, dict) or not all(isinstance(v, str) for v in brand.values())):
        errors.append('brand must be {"name": ..., "url": ..., "cta": ...} with text values')
    elif brand and set(brand) - set(BRAND_KEYS):
        warnings.append(f'brand: unknown keys {sorted(set(brand) - set(BRAND_KEYS))}')
    look, story = board.get('look', DIALS['look'][0]), board.get('story', DIALS['story'][0])
    library = SCENES[look][story] if look in DIALS['look'] and story in DIALS['story'] else []
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
    punct = ES_PUNCT if lang == 'es' else EN_PUNCT if lang == 'en' else ZH_PUNCT
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
        if 'direction' in b:
            _direction(b, display, lang, library, errors, warnings)
        chapter = next((c for c in chapters if c.get('id') == b.get('chapter')), None)
        if chapter is None:
            errors.append(f'{bid}: unknown chapter {b.get("chapter")}')
            continue
        if b.get('kind') == 'take' and chapter.get('kind') == 'section':
            head = ((b.get('take') or {}).get('headline') or {}).get(lang, '')
            if not head:
                errors.append(f'{bid}: take beat without a headline')
            elif len(head.split() if lang in ('en', 'es') else head) > (16 if lang in ('en', 'es') else 30):
                warnings.append(f'{bid}: long takeaway headline')
        for v in b.get('visuals') or []:
            vid, vtype = v.get('id'), v.get('type')
            if not vid or vid in visual_ids:
                errors.append(f'{bid}: visual id missing or duplicated ({vid})')
            visual_ids.add(vid)
            if vtype not in SLOT_TYPES | PAGE_TYPES | OTHER_TYPES:
                errors.append(f'{bid}/{vid}: unknown visual type {vtype!r}')
            if vtype == 'scientific':
                from ..scientific import validate as validate_scientific
                try:
                    validate_scientific(v.get('plot'))
                except ValueError as error:
                    errors.append(f'{bid}/{vid}: {error}')
            for where, trig in _triggers(v):
                ref = by_id.get(trig.get('beat'), b)
                phrase = trig.get(lang)
                if phrase and phrase not in (ref.get('spoken') or {}).get(lang, ''):
                    errors.append(f'{bid}/{vid} {where}: trigger {phrase!r} is not in the spoken text')
            for did in _doodles(v):
                if did.startswith(OWN):
                    try:
                        path = own_path(did, project_dir)
                        if not path.is_file():
                            errors.append(f'{bid}/{vid}: {_missing_picture(path)}')
                    except ValueError as error:
                        errors.append(f'{bid}/{vid}: {error}')
                    continue
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

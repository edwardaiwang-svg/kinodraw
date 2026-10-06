"""Repair a v3 answer without mutating it. Every changed value has a readable explanation."""
from __future__ import annotations

import copy
import math
import re

from .schema import PLAN_SCHEMA, SCENE
from ...engine.source_diagrams import resolve as resolve_diagram
from .semantics import beats, candidate_ids, cast_evidence, detect_cast, mentions, name_key


def _default(schema):
    if 'enum' in schema:
        return schema['enum'][0]
    kind = schema['type']
    if kind == 'object':
        return {k: _default(s) for k, s in schema['properties'].items()}
    return [] if kind == 'array' else '' if kind == 'string' else 0


def _shape(value, schema, path, repairs):
    kind = schema['type']
    if kind == 'object' and isinstance(value, dict):
        out = {}
        for key in value.keys() - schema['properties'].keys():
            repairs.append(f'{path}: removed unknown property {key}')
        for key, sub in schema['properties'].items():
            where = f'{path}.{key}'
            if key not in value:
                repairs.append(f'{where}: filled missing field')
                out[key] = _default(sub)
            else:
                out[key] = _shape(value[key], sub, where, repairs)
        return out
    if kind == 'array' and isinstance(value, list):
        return [_shape(v, schema['items'], f'{path}[{i}]', repairs) for i, v in enumerate(value)]
    if kind == 'string' and isinstance(value, str) and ('enum' not in schema or value in schema['enum']):
        return value
    if kind in ('number', 'integer') and isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(value):
        if kind == 'integer' and not isinstance(value, int):
            repairs.append(f'{path}: rounded {value} to an integer')
            return round(value)
        return value
    repairs.append(f'{path}: replaced invalid {kind} value {value!r}')
    return _default(schema)


def _clamp(obj, key, low, high, path, repairs):
    value = obj[key]
    fixed = max(low, value) if high is None else min(high, max(low, value))
    if fixed != value:
        obj[key] = fixed
        repairs.append(f'{path}.{key}: clamped {value} to {fixed}')


def _palette(palette, defaults, path, repairs):
    for key, value in palette.items():
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            palette[key] = defaults[key]
            repairs.append(f'{path}.{key}: replaced invalid hex colour {value!r} with {palette[key]}')


def _luminance(colour):
    rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    return sum(c * w for c, w in zip(linear, (.2126, .7152, .0722)))


def contrast(a, b) -> float:
    x, y = sorted((_luminance(a), _luminance(b)))
    return (y + .05) / (x + .05)


def _contrast(palette, repairs):
    bg, ink = palette['background'], palette['ink']
    if contrast(bg, ink) >= 4.5:
        return
    target = 0 if contrast(bg, '#000000') >= contrast(bg, '#FFFFFF') else 255
    rgb = [int(ink[i:i + 2], 16) for i in (1, 3, 5)]
    for step in range(1, 256):
        colour = '#' + ''.join(f'{round(c + (target - c) * step / 255):02X}' for c in rgb)
        if contrast(bg, colour) >= 4.5:
            palette['ink'] = colour
            repairs.append(f'style.palette.ink: {"darkened" if target == 0 else "lightened"} {ink} to {colour} '
                           'for at least 4.5:1 background contrast')
            return


def _cover(scenes, ids, treatment, repairs):
    owners = {}
    known = set(ids)
    supplied = []
    for i, scene in enumerate(scenes):
        for bid in scene['beat_ids']:
            if bid not in known or bid in owners:
                repairs.append(f'scenes[{i}]: dropped unknown or duplicate beat {bid!r}')
            else:
                owners[bid] = i
                supplied.append(bid)
    if supplied != [bid for bid in ids if bid in owners]:
        repairs.append('scenes: reordered coverage to script beat order')
    out, previous = [], None
    runs = set()
    for bid in ids:
        owner = owners.get(bid)
        if owner is None:
            scene = _default(SCENE)
            scene['beat_ids'], scene['treatment'] = [bid], treatment
            out.append(scene)
            repairs.append(f'scenes: added missing beat {bid}')
        elif out and previous == owner:
            out[-1]['beat_ids'].append(bid)
        else:
            scene = copy.deepcopy(scenes[owner])
            scene['beat_ids'] = [bid]
            out.append(scene)
            if owner in runs:
                repairs.append(f'scenes[{owner}]: split nonconsecutive beats into consecutive scenes')
            runs.add(owner)
        previous = owner
    for i, scene in enumerate(scenes):
        if i not in owners.values():
            repairs.append(f'scenes[{i}]: removed scene without known beats')
    return out


def _cast_traits(cast, evidence, repairs):
    for c in cast:
        key = name_key(c['name'])
        own = evidence.get(key)
        if own is None:
            continue
        others = {name: cues for name, cues in evidence.items() if name != key}
        traits = dict(own['traits'])
        if traits.get('age') == 'baby' and 'sex' not in traits and c['sex'] != 'unknown' and any(
                cues['traits'].get('sex') == c['sex'] for cues in others.values()):
            traits['sex'] = 'unknown'
        if own['baby_size'] is not None and 'size' not in traits and any(
                cues['traits'].get('size') == c['size'] for cues in others.values()):
            traits['size'] = own['baby_size']
        for field, value in traits.items():
            if c[field] != value:
                repairs.append(f'cast.{c["id"]}.{field}: replaced {c[field]!r} with {value!r} '
                               'using actor-owned script evidence')
                c[field] = value
        marks = []
        for mark in c['marks']:
            owner = next((name for name, cues in others.items() if mark in cues['marks']), None)
            if mark in own['absent_marks'] or (owner and mark not in own['marks']):
                reason = 'contradicted by its script description' if mark in own['absent_marks'] else f'owned by {owner}'
                repairs.append(f'cast.{c["id"]}.marks: removed {mark}, {reason}')
            else:
                marks.append(mark)
        for mark in sorted(own['marks']):
            if mark not in marks:
                marks.append(mark)
                repairs.append(f'cast.{c["id"]}.marks: added actor-owned {mark} from the spoken script')
        if 'none' in marks and any(mark != 'none' for mark in marks):
            marks = [mark for mark in marks if mark != 'none']
            repairs.append(f'cast.{c["id"]}.marks: removed none alongside visible marks')
        if not marks and c['marks']:
            marks = ['none']
            repairs.append(f'cast.{c["id"]}.marks: no remaining marks after script repair')
        c['marks'] = marks


def validate(plan, script_beats, candidates) -> tuple[dict, list[str]]:
    """Return (repaired plan, repairs). Invalid script ids raise ValueError rather than inventing coverage.

    Text references are beat ids; pictures must be offered for a beat in their scene. Scene holds cover
    all distinct on-screen references at 27 chars/s (all beats for sequential caption_only scenes).
    """
    script = beats(script_beats)
    by_id = {b['id']: b for b in script}
    repairs = []
    out = _shape(plan, PLAN_SCHEMA, 'plan', repairs)
    style = out['style']
    _clamp(style, 'energy', 1, 5, 'style', repairs)
    _clamp(style, 'tempo_bpm', 40, 240, 'style', repairs)
    _palette(style['palette'], {'background': '#FFFFFF', 'ink': '#1B1B1B',
                               'accent': '#287FA3', 'accent2': '#D39B36'}, 'style.palette', repairs)
    _contrast(style['palette'], repairs)

    cast, ids, names = [], set(), set()
    for c in out['cast']:
        if not c['name'] or c['name'].casefold() in names or c['id'] in ids:
            repairs.append(f'cast: dropped unnamed or duplicate character {c["name"]!r} / {c["id"]!r}')
            continue
        if not c['id']:
            c['id'] = re.sub(r'\W+', '_', c['name'].lower()) or 'character'
            while c['id'] in ids:
                c['id'] += '_2'
            repairs.append(f'cast: assigned id {c["id"]} to {c["name"]}')
        ids.add(c['id'])
        names.add(c['name'].casefold())
        _clamp(c, 'size', .3, 2.0, f'cast.{c["id"]}', repairs)
        _palette(c['palette'], {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'},
                 f'cast.{c["id"]}.palette', repairs)
        cast.append(c)
    for c in detect_cast(script):
        if any(name_key(existing['name']) == name_key(c['name']) for existing in cast):
            continue
        while c['id'] in ids:
            c['id'] += '_2'
        cast.append(c)
        ids.add(c['id'])
        repairs.append(f'cast: added named character {c["name"]} from the spoken script')
    _cast_traits(cast, cast_evidence(script), repairs)
    out['cast'] = cast
    cast_by_id = {c['id']: c for c in cast}

    sections = list(dict.fromkeys(b['section'] for b in script))
    intents = {}
    for section in out['storyboard']['sections']:
        sid = section['section_id']
        if sid not in sections or sid in intents:
            repairs.append(f'storyboard.sections: dropped unknown or duplicate section {sid!r}')
        else:
            intents[sid] = section
    if list(intents) != [s for s in sections if s in intents]:
        repairs.append('storyboard.sections: reordered section intents to script order')
    for sid in sections:
        if sid not in intents:
            intents[sid] = {'section_id': sid, 'intent': next(b['text'] for b in script if b['section'] == sid)}
            repairs.append(f'storyboard.sections: added intent for {sid}')
    out['storyboard']['sections'] = [intents[sid] for sid in sections]

    default_treatment = 'motion' if style['mode'] == 'motion' else 'whiteboard'
    out['scenes'] = _cover(out['scenes'], list(by_id), default_treatment, repairs)
    for i, scene in enumerate(out['scenes']):
        path = f'scenes[{i}]'
        bids = scene['beat_ids']
        offered = set().union(*(candidate_ids(candidates, bid) for bid in bids))
        elements = []
        for e in scene['elements']:
            allowed = (offered if e['kind'] == 'picture' else set(cast_by_id) if e['kind'] == 'cast' else
                       {scene['atmosphere']['kind']} - {'none'} if e['kind'] == 'atmosphere' else set(bids))
            if e['kind'] == 'diagram':
                allowed = {bid for bid in bids if resolve_diagram(script_beats, bid) is not None}
            if e['ref'] in allowed:
                elements.append(e)
            else:
                repairs.append(f'{path}: dropped unknown or out-of-scene {e["kind"]} ref {e["ref"]!r}')
        scene['elements'] = elements
        kept = []
        for action in scene['actions']:
            actor, bid = cast_by_id.get(action['actor']), action['at_beat']
            if actor is None or bid not in bids or not mentions(actor['name'], by_id[bid]['spoken']):
                repairs.append(f'{path}: dropped action {action["verb"]} by {action["actor"]!r} '
                               f'at {bid!r}; actor must be named in that scene beat')
                continue
            _clamp(action, 'intensity', 1, 3, path + '.action', repairs)
            kept.append(action)
        scene['actions'] = kept
        _clamp(scene['atmosphere'], 'density', 0, 1, path + '.atmosphere', repairs)
        _clamp(scene, 'hold_s', 0, None, path, repairs)
        forced = ('whiteboard' if style['mode'] == 'whiteboard' else
                  'motion' if style['mode'] == 'motion' and scene['treatment'] == 'whiteboard' else scene['treatment'])
        if forced != scene['treatment']:
            repairs.append(f'{path}: changed {scene["treatment"]} treatment to {forced} for {style["mode"]} mode')
            scene['treatment'] = forced
        text = scene['text']
        if text['kind'] == 'none' and text['ref']:
            text['ref'] = ''
            repairs.append(f'{path}.text: cleared unused ref')
        elif text['kind'] != 'none' and text['ref'] not in bids:
            repairs.append(f'{path}.text: dropped unknown or out-of-scene ref {text["ref"]!r}')
            scene['text'] = {'kind': 'none', 'ref': ''}
        refs = {e['ref'] for e in elements if e['kind'] == 'text'}
        if scene['text']['kind'] != 'none':
            refs.update(bids if scene['text']['kind'] == 'caption_only' else [scene['text']['ref']])
        reading = sum(len(by_id[bid]['text']) for bid in refs) / 27
        if scene['hold_s'] < reading:
            scene['hold_s'] = reading
            repairs.append(f'{path}.hold_s: extended to {reading:.3f}s for reading at 27 chars/s')
    return out, repairs

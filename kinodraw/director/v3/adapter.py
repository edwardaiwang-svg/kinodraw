"""Bridge v3 plans to the existing whiteboard storyboard; no pipeline dispatch changes."""
from __future__ import annotations

import copy

from ...library import catalog
from ..validate import _doodles
from .schema import SKINS


def adapt(plan: dict, board: dict) -> tuple[dict, list[dict]]:
    """Return (legacy board, scene treatments). Call after v3 validation.

    Picture refs select legacy cluster items, preserving their triggers and labels, and retain chart data.
    A new picture becomes a cluster. Cast/atmosphere scenes keep their legacy pictures as
    a compatibility fallback; their actual animation, camera, palette and hold need the hybrid renderer.
    Scene treatment records retain all v3 scene fields for that renderer, in scene order.
    """
    out = copy.deepcopy(board)
    out['look'] = plan['style']['whiteboard_skin'] if plan['style']['whiteboard_skin'] in SKINS else 'whiteboard'
    library = catalog()
    by_id = {b['id']: b for b in out['beats']}
    originals = {b['id']: set(_doodles(b.get('visuals', []))) for b in board['beats']}
    used_ids = {v['id'] for b in out['beats'] for v in b.get('visuals', [])}
    for scene in plan['scenes']:
        refs = list(dict.fromkeys(e['ref'] for e in scene['elements'] if e['kind'] == 'picture'))
        for bid in scene['beat_ids']:
            beat = by_id[bid]
            draft = beat.get('visuals', [])
            chosen = []
            for visual in draft:
                # Charts, quotes and definitions carry facts that a picture list cannot replace.
                if visual.get('type') != 'cluster':
                    chosen.append(visual)
                    continue
                items = [it for it in visual['items'] if it['doodle'] in refs]
                if not items:
                    continue
                selected = {**visual, 'items': items}
                if len(items) == 1:
                    selected['relation'] = 'none'
                if 'trigger' in selected:
                    trigger = next((it['trigger'] for it in items if it.get('trigger')), None)
                    if trigger:
                        selected['trigger'] = trigger
                    else:
                        selected.pop('trigger')
                chosen.append(selected)
            existing = set(_doodles(chosen))
            local = set(_doodles(draft))
            for ref in refs:
                if ref in existing or ref not in library:
                    continue
                # A multi-beat scene's rules pictures stay on the beat that originally named them.
                if len(scene['beat_ids']) > 1 and ref not in local and any(
                        ref in originals[other] for other in scene['beat_ids']):
                    continue
                vid = f'{bid}v3p{len(chosen)}'
                while vid in used_ids:
                    vid += '_2'
                used_ids.add(vid)
                chosen.append({'id': vid, 'type': 'cluster',
                               'items': [{'doodle': ref}], 'relation': 'none'})
                existing.add(ref)
            if refs:
                beat['visuals'] = chosen
    return out, copy.deepcopy(plan['scenes'])

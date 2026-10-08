"""One whole-video provider call, repaired against script references, with an offline fallback."""
from __future__ import annotations

import copy
import os
import time

from ... import ingest, script, styles
from ..llm.director import LLMDirector
from ..llm import errors
from ..llm.providers import CommandProvider, ProviderError, Usage, make_provider
from ..rules import RulesDirector as PictureDirector
from .offer import Offer, fit
from .rules import from_rules
from .semantics import beats
from .validate import validate


def plan_v3(doc_or_script, provider=None):
    """Return (plan, report). None or 'rules' stays offline; strings select a provider.

    Accept a Document, a script path/text, or an existing legacy storyboard without mutating it.
    """
    started, usage = time.monotonic(), Usage()
    board = (copy.deepcopy(doc_or_script) if isinstance(doc_or_script, dict) else
             script.build(doc_or_script if isinstance(doc_or_script, ingest.Document) else
                          ingest.read(doc_or_script), story='story'))
    lang = board['lang']
    pictures = PictureDirector(lang)
    scientific = {b['id']: [copy.deepcopy(v) for v in b.get('visuals', []) if v.get('type') == 'scientific']
                  for b in board['beats']}
    pictures.direct(board)
    for b in board['beats']:
        if scientific[b['id']]:
            b['visuals'] = scientific[b['id']]
    name = provider if isinstance(provider, str) else (
        getattr(provider, 'name', type(provider).__name__) if provider is not None else 'rules')
    repairs, reason, candidates, help_ = [], None, None, None
    try:
        if provider is not None and provider != 'rules':
            if isinstance(provider, str):
                if provider == 'command':
                    command = os.environ.get('KINODRAW_DIRECTOR_COMMAND')
                    if not command:
                        raise ProviderError('command: set KINODRAW_DIRECTOR_COMMAND for the dev director')
                    provider = CommandProvider(command=command)
                else:
                    # v3 supports Spanish too; retain the legacy cloud language gate for v1.
                    provider = make_provider(provider, lang=None if provider == 'cloud' else lang)
            builder = LLMDirector(provider, lang)
            builder.rules = pictures
            payload = builder._payload(board, {'kind': 'board'}, board['beats'], len(board['chapters']))
            normalized = {b['id']: b for b in beats(board)}
            for b in payload['beats']:
                b.update(section_id=normalized[b['beat_id']]['section'],
                         kind=normalized[b['beat_id']]['kind'], spoken=normalized[b['beat_id']]['spoken'])
            from ...scientific import summary as scientific_summary
            for b in payload['beats']:
                if scientific[b['beat_id']]:
                    b['scientific_plots'] = [scientific_summary(v['plot']) for v in scientific[b['beat_id']]]
            payload['section_ids'] = list(dict.fromkeys(b['section_id'] for b in payload['beats']))
            payload['look_ids'] = [look['id'] for look in styles.looks()]
            Offer(lang, getattr(pictures, 'matcher', None)).widen(payload['beats'], lambda text: script.sentences(text, lang))
            fit(payload)
            candidates = {b['beat_id']: b['candidates'] for b in payload['beats']}
            answer = provider.direct_plan(payload, usage)
            if not isinstance(answer, dict):
                raise ProviderError('the v3 answer must be a JSON object')
            plan, repairs = validate(answer, board, candidates)
            repairs = [f'{name}: {note}' for note in getattr(provider, 'served_repairs', None) or []] + repairs
        else:
            plan = from_rules(board)
    except Exception as error:  # noqa: BLE001 - provider or repair failure keeps the offline video usable
        help_ = errors.explain(error, name)          # in plain words, with what to do; never a key
        reason = errors.message(error, name)
        plan = from_rules(board)
    return plan, {'repairs': repairs, 'provider': name, 'seconds': time.monotonic() - started,
                  'usage': usage, 'fallback': reason is not None, 'fallback_reason': reason, 'fallback_help': help_,
                  'notes': [f'The offline v3 director planned this video ({reason})'] if reason else repairs}

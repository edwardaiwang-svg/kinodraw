"""Directors add visuals to storyboard.json: ``rules`` works offline; LLM modes are optional.

Modes: rules (offline, free) · cloud (KinoDraw Cloud plans) · openai · anthropic · compat
(any OpenAI-compatible endpoint; needs base_url and model) · command (a program you choose).
"""
from __future__ import annotations

from copy import deepcopy
from ..project_store import ProjectStore
from pathlib import Path

from .validate import validate

PROVIDER_INPUTS = ('command', 'base_url', 'key', 'token')


def provider_settings(settings, kind, **overrides):
    """Keep saved model options; executable, endpoint and auth require current input."""
    cfg = deepcopy(settings)
    for key in PROVIDER_INPUTS:
        cfg.pop(key, None)
    if kind != (cfg.get('director') or cfg.get('provider') or 'rules'):
        cfg.pop('model', None)
    cfg['director'] = kind
    cfg.update({key: value for key, value in overrides.items() if value is not None})
    return cfg


def provider_for(settings):
    """Trusted request options, falling back to user-level saved/env auth."""
    from .llm.providers import AnthropicProvider, CommandProvider, OpenAIProvider, make_provider
    kind = settings.get('director') or settings.get('provider') or 'rules'
    if kind == 'rules':
        return 'rules'
    model, base = settings.get('model') or None, settings.get('base_url') or None
    key = settings.get('key') or None
    if kind == 'anthropic':
        model = model or 'claude-opus-5-5'
        if base:
            raise ValueError('Anthropic base_url is not supported by the existing provider')
        if key:
            return AnthropicProvider(model, key=key)
    if kind == 'cloud' and settings.get('token'):
        from .llm.cloud import CloudProvider
        return CloudProvider(settings.get('lang'), token=settings['token'])
    if kind == 'command' and settings.get('command'):
        return CommandProvider(model=model, command=settings['command'])
    if kind == 'compat' and not (model and base):
        raise ValueError('an OpenAI-compatible provider needs --base-url and --model')
    if kind in ('openai', 'compat') and (key or base):
        return OpenAIProvider(model or 'gpt-6-luna', key=key, base_url=base,
                              name=kind, strict_schema=kind == 'openai')
    return make_provider(kind, model=model, base_url=base, lang=settings.get('lang'))


def direct(project_dir: Path, mode: str = 'rules', model: str | None = None, base_url: str | None = None,
           progress=None, *, provider=None) -> dict:
    """Fill every beat's visuals, validate, and save storyboard.json. Returns a report."""
    project_dir = Path(project_dir)
    store = ProjectStore(project_dir)
    saved = store.load()
    board = saved['storyboard']
    cfg = provider_settings(saved['settings'], mode, model=model, base_url=base_url)
    generated = cfg.get('generated_visuals', {})
    from .validate import _doodles
    # A saved generated snapshot distinguishes untouched direction from edits.
    # With no ownership record, existing art is conservatively user-owned.
    originals = {b['id']: deepcopy(b.get('visuals', [])) for b in board['beats']
                 if (b['id'] in generated and b.get('visuals', []) != generated[b['id']])
                 or (b.get('visuals') and b['id'] not in generated)
                 or any(ref.startswith('own:') for ref in _doodles(b.get('visuals', [])))}
    from .match import ensure_model                  # every director searches the doodles; first run downloads it
    ensure_model(board['lang'], progress and (lambda done, total: progress('download-search', done, total)))
    if mode == 'rules':
        from .rules import RulesDirector
        RulesDirector(board['lang']).direct(board)
        report = validate(board, project_dir)
        if not report['ok']:
            raise ValueError('director produced an invalid storyboard: ' + '; '.join(report['errors'][:5]))
        report = {'warnings': report['warnings'], 'notes': [], 'usage': None}
    else:
        from .llm.director import LLMDirector
        if provider is None:
            provider = provider_for({**cfg, 'lang': board['lang']})
        report = LLMDirector(provider, board['lang']).direct(board, progress)
    if board.get('look', 'whiteboard') != 'whiteboard':  # animated looks: a role, scene, emphasis and energy per sentence
        from .annotate import annotate
        report['direction'] = annotate(board)
    for beat in board['beats']:
        if beat['id'] in originals:
            beat['visuals'] = originals[beat['id']]
        else:
            generated[beat['id']] = deepcopy(beat.get('visuals', []))
    cfg['generated_visuals'] = {b['id']: generated[b['id']] for b in board['beats'] if b['id'] in generated}
    store.save(board, cfg, saved['revision'], 'Before direction')
    return report

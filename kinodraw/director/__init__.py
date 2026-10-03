"""Directors add visuals to storyboard.json: ``rules`` works offline; LLM modes are optional.

Modes: rules (offline, free) · cloud (KinoDraw Cloud plans) · openai · anthropic · compat
(any OpenAI-compatible endpoint; needs base_url and model) · command (a program you choose).
"""
from __future__ import annotations

import json
from pathlib import Path

from .validate import validate


def direct(project_dir: Path, mode: str = 'rules', model: str | None = None, base_url: str | None = None,
           progress=None) -> dict:
    """Fill every beat's visuals, validate, and save storyboard.json. Returns a report."""
    project_dir = Path(project_dir)
    path = project_dir / 'storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
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
        from .llm.providers import make_provider
        report = LLMDirector(make_provider(mode, model, base_url), board['lang']).direct(board, progress)
    if board.get('look', 'whiteboard') != 'whiteboard':  # animated looks: a role, scene, emphasis and energy per sentence
        from .annotate import annotate
        report['direction'] = annotate(board)
    path.write_text(json.dumps(board, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return report

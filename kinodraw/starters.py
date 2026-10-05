"""Editable, explicitly fictional scripts shipped with KinoDraw."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / 'assets' / 'starters'


def list_starters() -> list[dict]:
    return [{'id': path.stem, 'lang': path.stem.rsplit('-', 1)[-1], 'path': str(path),
             'title': path.read_text(encoding='utf-8').splitlines()[0].lstrip('# '),
             'example_data': True} for path in sorted(ASSETS.glob('*.md'))]


def read(name: str) -> str:
    names = {entry['id'] for entry in list_starters()}
    if name not in names:
        raise ValueError(f'unknown starter: {name}; use starter --list')
    return (ASSETS / f'{name}.md').read_text(encoding='utf-8')

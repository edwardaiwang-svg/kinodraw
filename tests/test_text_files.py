"""Text files the app writes and reads are UTF-8 on every computer (Windows' own default is its code page)."""
import ast
from pathlib import Path

import kinodraw

PACKAGE = Path(kinodraw.__file__).parent


def test_every_text_file_is_read_and_written_as_utf8():
    """recording-align.json and the voice caches were written in the computer's code page and read back as UTF-8:
    on Windows a project folder or script with letters outside English stopped the voice step."""
    loose = []
    for path in sorted(PACKAGE.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Call) or any(k.arg == 'encoding' for k in node.keywords):
                continue
            f = node.func
            text_io = isinstance(f, ast.Attribute) and f.attr in ('read_text', 'write_text')
            mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == 'mode'), None)
            binary = isinstance(mode, ast.Constant) and 'b' in str(mode.value)
            if text_io or (isinstance(f, ast.Name) and f.id == 'open' and not binary):
                loose.append(f'{path.relative_to(PACKAGE.parent)}:{node.lineno}')
    assert loose == []

"""What ships in the kinodraw package names no private person: assets and docstrings describe themselves neutrally
(licence and credit text lives in LICENSES/ and THIRD_PARTY_NOTICES.md)."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / 'kinodraw'
OWNER = re.compile(r"\bJ's\b")


def test_the_package_credits_no_private_person():
    hits = []
    for p in PKG.rglob('*'):
        if p.suffix in ('.py', '.json', '.md', '.txt', '.html', '.js', '.css') and p.is_file():
            for n, line in enumerate(p.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
                if OWNER.search(line):
                    hits.append(f'{p.relative_to(PKG.parent)}:{n}')
    assert not hits, hits

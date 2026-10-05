"""Run before every public push: no private names, personal paths, emails or API keys in the repository.

  python scripts/prepublish_check.py        (exit 1 and a list of hits if anything is found)

Terms are matched case-insensitively; key patterns by their exact shape.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'.git', '.venv', 'private_presets', 'node_modules', 'dist', 'build', 'projects', '__pycache__', '.pytest_cache'}
BINARY = {'.png', '.jpg', '.jpeg', '.mp4', '.mp3', '.wav', '.ttf', '.otf', '.npz', '.icns', '.ico', '.gif', '.onnx', '.bin'}
# The private names live outside the repository (private_presets/ is git-ignored), so the list itself never ships.
TERMS_FILE = ROOT / 'private_presets' / 'publish_terms.txt'
PRIVATE = [t.strip() for t in TERMS_FILE.read_text(encoding='utf-8').splitlines()
           if t.strip() and not t.startswith('#')] \
    if TERMS_FILE.exists() else []
KEYS = [r'sk-[A-Za-z0-9_-]{20,}', r'sk-ant-[A-Za-z0-9_-]+', r'AKIA[0-9A-Z]{16}', r'ghp_[A-Za-z0-9]{30,}',
        r'github_pat_[A-Za-z0-9_]{22,}', r'hf_[A-Za-z0-9]{30,}',
        r'xox[abp]-[A-Za-z0-9-]+', r'-----BEGIN [A-Z ]*PRIVATE KEY-----', r'AIza[0-9A-Za-z_-]{35}', r're_[A-Za-z0-9]{24,}']
terms = re.compile('|'.join(re.escape(t) for t in PRIVATE) or r'(?!)', re.I)
keys = re.compile('|'.join(KEYS))
if not PRIVATE:
    print(f'warning: no private term list at {TERMS_FILE.relative_to(ROOT)}; only key patterns are checked')
print(f'$ scan {ROOT} ({len(PRIVATE)} case-insensitive private terms; {len(KEYS)} key patterns)')

def published():
    """What a push would publish: tracked files plus new files git does not ignore (test profiles, keys and
    generated vendor/asset folders are ignored, so they are never scanned or pushed)."""
    try:
        out = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT,
                             capture_output=True, check=True).stdout.decode('utf-8')
        return sorted(ROOT / p for p in out.split('\0') if p)
    except (OSError, subprocess.CalledProcessError):     # not a git checkout: everything on disk
        return sorted(ROOT.rglob('*'))


hits = 0
for path in published():
    if not path.is_file() or SKIP_DIRS & set(path.relative_to(ROOT).parts) or path.suffix.lower() in BINARY:
        continue
    if path.name == 'prepublish_check.py':
        continue
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        continue
    for n, line in enumerate(text.splitlines(), 1):
        for m in (terms.search(line), keys.search(line)):
            if m:
                hits += 1
                print(f'{path.relative_to(ROOT)}:{n}: {m.group(0)!r}  {line.strip()[:120]}')
print(f'{hits} hit(s)')
sys.exit(1 if hits else 0)

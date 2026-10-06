"""Stage and ad-hoc sign a Dev.app from an exact, separately accepted commit.

Explicit execution creates one NEW detached worktree and retains it on failure.
No install, GUI, server, media, target reuse, cleanup, or acceptance claim.
Run with the existing build venv's Python; no dependencies are installed.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
RED_BASE = 'd16d89fd0a0d0cc6c4c54b70a4fc687c55e61a03'
DATA = ('kinodraw/assets', 'kinodraw/studio/static', 'kinodraw/styles/registry.json',
        'LICENSE', 'THIRD_PARTY_NOTICES.md', 'LICENSES')
REQUIRED_MODULES = {'kinodraw.cli', 'kinodraw.pipeline', 'kinodraw.mcp_server',
                    'kinodraw.starters', 'kinodraw.engine.render'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_request(commit, output):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('COMMIT must be an exact full 40-character lowercase commit hash')
    if commit == RED_BASE:
        raise ValueError('d16d89f is the unaccepted red base; select the later accepted combined commit')
    output = Path(output)
    if not output.is_absolute():
        raise ValueError('OUTPUT_ROOT must be absolute')
    if os.path.lexists(output):
        raise ValueError('OUTPUT_ROOT already exists; choose a NEW unique directory')
    if not output.parent.is_dir():
        raise ValueError('OUTPUT_ROOT parent must already exist')
    output = output.parent.resolve() / output.name
    if any(output.is_relative_to(p) for p in (Path('/Applications'), Path.home() / 'Applications')):
        raise ValueError('Applications is not a staging location')
    if sys.platform != 'darwin':
        raise ValueError('Dev.app staging requires macOS')
    return output


class Runner:
    def __init__(self, root):
        self.root = root
        self.index = 0
        # Do not inherit credentials, app settings, editable-source search paths or model overrides.
        self.env = {'HOME': str(root / 'home'), 'TMPDIR': str(root / 'tmp'),
                    'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8',
                    'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
                    'PYINSTALLER_CONFIG_DIR': str(root / 'pyinstaller-cache')}

    def run(self, argv, *, cwd=REPO, timeout=30):
        self.index += 1
        log = self.root / 'logs' / f'{self.index:02d}.log'
        started = time.monotonic()
        timed_out = False
        with log.open('xb') as stream:
            process = subprocess.Popen(argv, cwd=cwd, env=self.env, stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                timed_out = True
                # Only the process group created by this Popen is signalled; no PID lookup/audit.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        event = {'argv': [str(a) for a in argv], 'cwd': str(cwd), 'timeout_seconds': timeout,
                 'exit': process.returncode, 'timed_out_or_interrupted': timed_out,
                 'elapsed_seconds': round(time.monotonic() - started, 3), 'log': str(log)}
        with (self.root / 'commands.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + '\n')
        if timed_out or process.returncode:
            raise RuntimeError(f'command failed: exit={process.returncode}, timeout/interruption={timed_out}; {log}')
        return log.read_text(encoding='utf-8')


def source_gate(source):
    launch = ast.parse((source / 'packaging/launch.py').read_text(encoding='utf-8'))
    constants = {n.value for n in ast.walk(launch) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    if not {'--render-worker', '--finish-worker'} <= constants:
        raise ValueError('launch.py needs the accepted render and finish worker dispatch before building')
    mcp = ast.parse((source / 'kinodraw/mcp_server.py').read_text(encoding='utf-8'))
    frozen = any((isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                  and n.value.id == 'sys' and n.attr == 'frozen') or
                 (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'getattr'
                  and len(n.args) >= 2 and isinstance(n.args[0], ast.Name) and n.args[0].id == 'sys'
                  and isinstance(n.args[1], ast.Constant) and n.args[1].value == 'frozen')
                 for n in ast.walk(mcp))
    if not frozen:
        raise ValueError('MCP frozen child dispatch is still missing; combine the additive patch first')
    # These are conservative syntax prerequisites, not proof that either dispatch works.


def verify_sources(toc_path, source):
    modules = {}

    def visit(value):
        if isinstance(value, (tuple, list)):
            if len(value) == 3 and isinstance(value[0], str) and value[0].startswith('kinodraw'):
                if not isinstance(value[1], str) or not Path(value[1]).resolve().is_relative_to(source / 'kinodraw'):
                    raise ValueError(f'non-staged KinoDraw module in PYZ TOC: {value[0]}')
                modules[value[0]] = value[1]
            else:
                for item in value:
                    visit(item)

    visit(ast.literal_eval(toc_path.read_text(encoding='utf-8')))
    missing = REQUIRED_MODULES - modules.keys()
    if missing:
        raise ValueError(f'PYZ TOC missing required modules: {sorted(missing)}')
    return modules


def verify_assets(source, app):
    manifest = {}
    for name in DATA:
        path = source / name
        files = sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path]
        for item in files:
            relative = item.relative_to(source)
            bundled = app / 'Contents/Resources' / relative
            expected = digest(item)
            if not bundled.is_file() or digest(bundled) != expected:
                raise ValueError(f'missing or changed bundled data: {relative}')
            manifest[str(relative)] = expected
    return manifest


def stage(commit, output):
    output = validate_request(commit, output)
    output.mkdir()                              # Atomic refusal of concurrent/existing targets.
    for name in ('home', 'tmp', 'logs'):
        (output / name).mkdir()
    run = Runner(output)
    git = ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-C', str(REPO)]
    resolved = run.run(git + ['rev-parse', '--verify', commit + '^{commit}']).strip()
    if resolved != commit:
        raise ValueError('resolved commit does not match COMMIT')
    version = run.run([sys.executable, '-I', '-c',
                       'import importlib.metadata; print(importlib.metadata.version("PyInstaller"))']).strip()
    if version != '6.22.3':
        raise ValueError(f'expected observed PyInstaller 6.22.3, got {version}')
    source = output / 'source'
    run.run(git + ['worktree', 'add', '--detach', str(source), commit], timeout=120)
    if run.run(['/usr/bin/git', '-C', str(source), 'rev-parse', 'HEAD']).strip() != commit:
        raise ValueError('new worktree HEAD mismatch')
    source_gate(source)
    spec = source / 'packaging/kinodraw.spec'
    spec_hash = digest(spec)
    run.run([sys.executable, '-I', '-m', 'PyInstaller', str(spec),
             '--distpath', str(output / 'dist'), '--workpath', str(output / 'build')],
            cwd=source, timeout=1800)
    original = output / 'dist/KinoDraw.app'
    if not (original / 'Contents/MacOS/KinoDraw').is_file():
        raise ValueError('build did not produce KinoDraw.app executable')
    modules = verify_sources(output / 'build/kinodraw/PYZ-00.toc', source)
    if digest(spec) != spec_hash or run.run(['/usr/bin/git', '-C', str(source), 'status',
                                           '--porcelain', '--untracked-files=no']).strip():
        raise ValueError('staged tracked source changed during build')
    app = output / 'KinoDraw Dev.app'
    if os.path.lexists(app):
        raise ValueError('Dev.app target exists; refusing replacement')
    original.rename(app)                         # Both paths are newly owned by this run.
    assets = verify_assets(source, app)
    plist = app / 'Contents/Info.plist'
    with plist.open('rb') as stream:
        info = plistlib.load(stream)
    expected = {'CFBundleIdentifier': 'io.github.kinodraw.dev', 'CFBundleName': 'KinoDraw Dev',
                'CFBundleDisplayName': 'KinoDraw Dev', 'CFBundleShortVersionString': f'0.3.0-dev+{commit[:7]}',
                'CFBundleVersion': f'0.3.0-dev+{commit[:7]}', 'KinoDrawSourceCommit': commit}
    info.update(expected)
    with plist.open('wb') as stream:
        plistlib.dump(info, stream)
    run.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], timeout=180)
    run.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], timeout=120)
    with plist.open('rb') as stream:
        actual = plistlib.load(stream)
    if any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError('signed Dev metadata mismatch')
    provenance = {'commit': commit, 'app': str(app), 'pyinstaller': version, 'spec_sha256': spec_hash,
                  'modules': modules, 'data_sha256': assets, 'metadata': expected,
                  'result': 'STAGED_SIGNED_ONLY', 'frozen_cli_and_media_acceptance': 'NOT RUN'}
    with (output / 'provenance.json').open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(provenance, indent=2) + '\n')
    print(f'STAGED_SIGNED_ONLY: {app}; frozen CLI/media acceptance still required')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('commit', metavar='COMMIT', help='exact full hash of the later accepted combined commit')
    parser.add_argument('output_root', metavar='OUTPUT_ROOT', help='absolute NEW unique directory; parent must exist')
    args = parser.parse_args(argv)
    try:
        stage(args.commit, args.output_root)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'stage-dev: REFUSED/FAILED: {error}; any fresh stage is retained, never reused or removed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

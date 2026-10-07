"""Small offline MCP server: one UTF-8 JSON-RPC message per stdio line.

The rendering, storyboard building and validation stay in the existing pipeline.
Explicit make/cached modes finish narrated movies through the shared pipeline.
No live providers, downloads, app migration, or credentials are used.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path


def _finite(value):
    if isinstance(value, str):
        value.encode('utf-8')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('JSON numbers must be finite')
    if isinstance(value, dict):
        for key, item in value.items():
            key.encode('utf-8')
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def loads(text, *, parse_float=float):
    def bad_constant(value):
        raise ValueError(f'non-finite JSON number: {value}')
    value = json.loads(text, parse_float=parse_float, parse_constant=bad_constant, object_pairs_hook=_pairs)
    _finite(value)
    return value


def _chart_float(token):
    value = float(token)
    # Compare decimal values before the JSON parser can discard significant digits.
    if not math.isfinite(value) or Decimal(str(value)) != Decimal(token):
        raise ValueError('chart number loses precision or underflows in the current renderer')
    return value


def _svg(text):
    """Check without rewriting: retain inline geometry, text, defs, styles and fragment references."""
    from defusedxml.ElementTree import fromstring
    if re.search(r'<\?xml-stylesheet\b', text, re.I):
        raise ValueError('SVG external stylesheets are unavailable offline')
    try:
        root = fromstring(text, forbid_dtd=True)
    except Exception as error:
        raise ValueError('invalid or unsafe SVG XML') from error
    if root.tag.rsplit('}', 1)[-1] != 'svg':
        raise ValueError('an SVG file must contain an SVG document')
    for node in root.iter():
        tag = node.tag.rsplit('}', 1)[-1]
        if tag in {'script', 'foreignObject', 'style', 'animate', 'animateTransform', 'animateMotion', 'set'}:
            raise ValueError(f'SVG element {tag} is unavailable in this offline developer surface')
        for key, value in node.attrib.items():
            name = key.rsplit('}', 1)[-1].lower()
            if (name.startswith('on') or name == 'base'
                    or (name in {'href', 'src'} and not value.strip().startswith('#'))):
                raise ValueError('SVG external resources and event handlers are unavailable offline')
            # CSS escapes/comments can disguise resource syntax; ordinary inline styles remain supported.
            if '\\' in value or '/*' in value or (name == 'style' and '@' in value):
                raise ValueError('SVG escaped CSS and resource declarations are unavailable offline')
            urls = re.findall(r'url\s*\(([^)]*)\)', value, re.I)
            if len(urls) != len(re.findall(r'url\s*\(', value, re.I)) or any(
                    not target.strip().strip('\'"').startswith('#') for target in urls):
                raise ValueError('SVG external resources are unavailable offline')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{name} must be nonempty text')
    return value


def _number(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'{name} must be finite and between {minimum} and {maximum}')
    return value


def _worker_command(root, arguments):
    worker = [sys.executable, '--mcp-worker'] if getattr(sys, 'frozen', False) else \
        [sys.executable, '-m', 'kinodraw.mcp_server']
    return worker + ['--root', str(root), *arguments]


def _local_models(lang, *, checksum=True):
    """An offline gate, also used instead of ensure_models in our isolated worker."""
    from . import voice
    spec = voice.LANGS[lang]
    for name in (spec['model'], spec['voices'], spec['config']):
        if not name:
            continue
        path = voice.MODEL_DIR / name
        expected_hash, expected_size = voice.FILES[name][1:]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
            raise ValueError(f'cached local Kokoro model required: {name}; no downloads on MCP')
        if checksum:
            from .package import sha
            if sha(path) != expected_hash:
                raise ValueError(f'cached local Kokoro model checksum differs: {name}')


def _sources(path, cfg):
    from .package import sha
    names = {'project.json', 'storyboard.json', 'pronounce.txt'}
    names.update(cfg[key] for key in ('script', 'recording') if cfg.get(key))
    return {name: sha(path / name) if (path / name).is_file() else None for name in names}


class Developer:
    """Root-confined operations and subprocess handles owned by this server only."""
    def __init__(self, root):
        root = Path(root)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError('--root must be an explicit absolute existing directory')
        self.root = root.resolve(strict=True)
        self.jobs = {}

    def path(self, name):
        _text(name, 'path')
        relative = Path(name)
        if relative.is_absolute() or '\\' in name or any(p.startswith('.') for p in relative.parts):
            raise ValueError('paths must be root-relative, without hidden components or ..')
        if not relative.parts:
            raise ValueError('a path below --root is required')
        path = self.root / relative
        cursor = self.root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError('symlinks are not accepted below --root')
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('path escapes --root')
        return path

    def project(self, name):
        path = self.path(name)
        if not path.is_dir():
            raise ValueError(f'project not found: {name}')
        # Also protect paths opened indirectly by the existing renderer.
        svgs = []
        for folder, dirs, files in os.walk(path, followlinks=False):
            if any((Path(folder) / item).is_symlink() for item in dirs + files):
                raise ValueError('project contains a symlink')
            for item in files:
                if Path(item).suffix.lower() == '.svg':
                    svgs.append(Path(folder) / item)
        cfg = loads((path / 'project.json').read_text(encoding='utf-8'))
        board = loads((path / 'storyboard.json').read_text(encoding='utf-8'))
        if not isinstance(cfg, dict) or not isinstance(board, dict):
            raise ValueError('project and storyboard must be JSON objects')
        if board.get('look') == 'collage':
            raise ValueError('collage look is unavailable offline: its renderer may download search models; '
                             'choose whiteboard or another supported offline look')
        for svg in svgs:
            _svg(svg.read_text(encoding='utf-8'))
        if cfg.get('lang') != board.get('lang'):
            raise ValueError('project and storyboard languages differ')
        if not board.get('beats') or not board.get('chapters'):
            raise ValueError('project must contain beats and chapters')
        for key in ('beats', 'chapters'):
            if not isinstance(board[key], list) or any(not isinstance(item, dict) for item in board[key]):
                raise ValueError(f'{key} must be a list of objects')
        self._references(board, path)
        return path, cfg, board

    def _references(self, value, project):
        if isinstance(value, dict):
            if value.get('type') == 'stock':
                raise ValueError('stock footage is unavailable in this offline developer surface')
            for key, item in value.items():
                if key == 'photo' and item:
                    _text(item, 'photo')
                    relative = Path(item)
                    if relative.is_absolute():
                        raise ValueError('photo must be a path inside its project')
                    self.path(str(project.relative_to(self.root) / relative))
                if key == 'doodle' or (key == 'narrator' and item):
                    _text(item, key)
                    name = item.removeprefix('own:')
                    if '/' in name or '\\' in name or name.startswith('.'):
                        raise ValueError('doodle references must be simple library IDs or own: filenames')
                if key == 'svg' and isinstance(item, str):
                    _svg(item)
                self._references(item, project)
        elif isinstance(value, list):
            for item in value:
                self._references(item, project)

    def create_project(self, project, script=None, starter=None, lang=None, title=None):
        from . import pipeline, starters
        path = self.path(project)
        if path.exists():
            raise ValueError('project already exists; creation never overwrites it')
        if (script is None) == (starter is None):
            raise ValueError('provide exactly one of script or starter')
        if starter is not None:
            script = starters.read(starter)
            lang = lang or starter.rsplit('-', 1)[-1]
        _text(script, 'script')
        if lang is not None and lang not in ('en', 'zh', 'es'):
            raise ValueError('lang must be en, zh or es')
        if title is not None:
            _text(title, 'title')
        # A newline forces pasted text, bypassing the pipeline's implicit file detection.
        board = pipeline.new_project(script + '\n', path, lang=lang, title=title,
                                     director='rules', director_v3=False, workers=1)
        return {'project': str(path), 'beats': len(board['beats']), 'director': 'rules',
                'visuals': 'storyboard skeleton; add charts or edit visuals locally'}

    def validate_project(self, project):
        from .director.validate import validate
        from .pipeline import validate_aspect
        path, cfg, board = self.project(project)
        validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
        return validate(board, path)

    def chart_add(self, project, beat, source):
        from .director.validate import validate
        from .project_store import ProjectStore
        path, cfg, board = self.project(project)
        store = ProjectStore(path)
        saved = store.load()
        cfg, board = saved['settings'], saved['storyboard']
        source_path = self.path(source)
        if source_path.suffix.lower() != '.json':
            raise ValueError('chart source must be a local .json file')
        from .scientific import MAX_BYTES
        if source_path.stat().st_size > MAX_BYTES:
            raise ValueError('chart source exceeds 2 MiB')
        raw = source_path.read_bytes()
        data = loads(raw.decode('utf-8'), parse_float=_chart_float)
        if not isinstance(data, dict):
            raise ValueError('chart source must be an object')
        if data.get('format') == 'kinodraw-scientific':
            return self._scientific_add(path, saved, beat, source_path, raw, data)
        provenance = _text(data.get('source'), 'source attribution')
        title = _text(data.get('title'), 'chart title')
        unit = data.get('unit', '')
        if not isinstance(unit, str):
            raise ValueError('unit must be text')
        rows = data.get('rows')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 6:
            raise ValueError('the current bar renderer supports 1-6 rows')
        lang, mapped = cfg['lang'], []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('each chart row must be an object')
            label = _text(row.get('label'), 'row label')
            # The current renderer clamps negatives: refuse them instead of misrepresenting data.
            value = _number(row.get('value'), 'chart value')
            if isinstance(value, int) and int(float(value)) != value:
                raise ValueError('chart number loses precision in the current renderer')
            mapped.append({'label': {lang: label}, 'value': value, 'display': {lang: str(value)}})
        target = next((b for b in board['beats'] if b['id'] == beat), None)
        if target is None:
            raise ValueError(f'unknown beat: {beat}')
        digest = hashlib.sha256(raw).hexdigest()
        visual = {'id': 'chart_' + uuid.uuid4().hex, 'type': 'bars', 'title': {lang: title},
                  'unit': {lang: unit}, 'rows': mapped, 'footnote': {lang: provenance},
                  'source_file': str(source_path.relative_to(self.root)), 'source_sha256': digest}
        target.setdefault('visuals', []).append(visual)
        report = validate(board, path)
        if not report['ok']:
            raise ValueError('invalid storyboard: ' + '; '.join(report['errors']))
        updated = store.save(board, cfg, expected_revision=saved['revision'], label='Before MCP chart')
        return {'visual': visual['id'], 'source_sha256': digest, 'rows': len(mapped),
                'revision': updated['revision']}

    def _scientific_add(self, path, saved, beat, source_path, raw, data):
        from .scientific import validate as validate_scientific
        from .director.validate import validate
        from .director.v3.rules import from_rules
        from .project_store import ProjectStore
        data = validate_scientific(data)
        cfg, board = saved['settings'], saved['storyboard']
        target = next((b for b in board['beats'] if b['id'] == beat), None)
        if target is None:
            raise ValueError(f'unknown beat: {beat}')
        digest = hashlib.sha256(raw).hexdigest()
        relative = Path('assets/scientific') / (digest + '.json')
        visual = {'id': 'science_' + uuid.uuid4().hex, 'type': 'scientific', 'plot': data,
                  'source_file': relative.as_posix(), 'source_sha256': digest}
        target.setdefault('visuals', []).append(visual)
        report = validate(board, path)
        if not report['ok']:
            raise ValueError('invalid storyboard: ' + '; '.join(report['errors']))
        plan = cfg.get('plan_v3') or from_rules(board)
        plan['style']['mode'] = 'hybrid'
        scene = next(s for s in plan['scenes'] if beat in s['beat_ids'])
        scene.update(treatment='chart', elements=[], actions=[], camera='static',
                     atmosphere={'kind': 'none', 'density': 0}, transition_in='cut',
                     text={'kind': 'caption_only', 'ref': beat})
        if sum(v.get('type') == 'scientific' for b in board['beats'] if b['id'] in scene['beat_ids']
               for v in b.get('visuals', [])) > 4:
            raise ValueError('split scientific scenes with more than four plots into separate beats')
        cfg.update(director_v3=True, plan_v3=plan)
        asset = self.path(str(path.relative_to(self.root) / relative))
        asset.parent.mkdir(parents=True, exist_ok=True)
        created = not asset.exists()
        if created:
            with asset.open('xb') as stream:
                stream.write(raw)
        elif hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
            raise ValueError('scientific source asset hash differs')
        try:
            updated = ProjectStore(path).save(board, cfg, expected_revision=saved['revision'], label='Before scientific chart')
        except Exception:
            if created:
                asset.unlink(missing_ok=True)
            raise
        return {'visual': visual['id'], 'source_sha256': digest, 'source_file': relative.as_posix(),
                'mode': data['mode'], 'revision': updated['revision']}

    @staticmethod
    def _save(path, data):
        temporary = path.with_name('developer-' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(dumps(data) + '\n', encoding='utf-8')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _production(self, project):
        from .engine import render, timeline
        from .pipeline import validate_aspect
        path, cfg, board = self.project(project)
        report = self.validate_project(project)
        if not report['ok']:
            raise ValueError('invalid storyboard: ' + '; '.join(report['errors']))
        aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
        tl = timeline.layout(board, cfg['lang'], timeline.synthetic_clips(board, cfg['lang']),
                             credit=cfg.get('credit', True))
        prod = render.make_production(board, tl, cfg['lang'], path, aspect=aspect)
        return path, aspect, tl, prod

    def preview_png(self, project, time=0):
        time = _number(time, 'time')
        path, aspect, tl, prod = self._production(project)
        if time >= tl['duration']:
            raise ValueError('preview time is outside the estimated timeline')
        folder = path / 'build' / 'developer'
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / ('preview-' + uuid.uuid4().hex + '.png')
        size = {'9:16': (540, 960), '1:1': (540, 540)}.get(aspect, (960, 540))
        prod.frame(time).convert('RGB').resize(size).save(output, 'PNG')
        return {'path': str(output), 'mimeType': 'image/png', 'synthetic_timing': True,
                'width': size[0], 'height': size[1], 'warnings': prod.warnings}

    def _narrated_project(self, project, mode):
        from . import voice
        path, cfg, board = self.project(project)
        report = self.validate_project(project)
        if not report['ok']:
            raise ValueError('invalid storyboard: ' + '; '.join(report['errors']))
        # These values can be consumed indirectly by narration/finish/render.
        # A saved provider name/plan is data; commands, URLs and secrets are not accepted.
        def config_refs(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {'key', 'api_key', 'token', 'command', 'base_url', 'url', 'endpoint', 'voice_server'}:
                        raise ValueError(f'{key} is unavailable on offline MCP')
                    if key in {'script', 'recording', 'voice_file', 'config', 'config_file'} and item:
                        _text(item, key)
                        if len(item) > 1024 or ':' in item or Path(item).is_absolute():
                            raise ValueError(f'{key} must be a local path inside its project')
                        target = self.path(str(path.relative_to(self.root) / item))
                        if not target.resolve().is_relative_to(path):
                            raise ValueError(f'{key} escapes its project')
                    if key == 'kind' and item == 'picture':
                        self._references({'doodle': value.get('ref')}, path)
                    config_refs(item)
            elif isinstance(value, list):
                for item in value:
                    config_refs(item)
        config_refs(cfg)
        self._references(cfg, path)
        music = board.get('music')
        if isinstance(music, dict) and 'file' in music:             # your own music: a file in music/ (set_music)
            from .audio.score import own
            target = self.path(str(path.relative_to(self.root) / own(music, path).file))
            if not target.is_file():
                raise ValueError('music file must exist in the project\'s music folder')
        if isinstance(music, dict):
            from .audio.mix import MUSIC
            for key in ('primary', 'secondary'):
                if key not in music:
                    continue
                slug = _text(music[key], 'music track')
                if not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
                    raise ValueError('music must name a bundled track, not a path')
                track = MUSIC / f'{slug}.mp3'
                if track.is_symlink() or not track.is_file() or not track.resolve().is_relative_to(MUSIC.resolve()):
                    raise ValueError('music must name an existing bundled track')
        if cfg.get('recording'):
            for metadata in (path / 'voice/recording').glob('*.json'):
                info = loads(metadata.read_text(encoding='utf-8'))
                for clip in info.get('clips', []):
                    name = _text(clip.get('wav'), 'recording clip')
                    if Path(name).name != name or name.startswith('.') or ':' in name or '\\' in name:
                        raise ValueError('recording clip must be a filename inside its cache')
                    target = self.path(str(path.relative_to(self.root) / 'voice/recording' / name))
                    if not target.is_file():
                        raise ValueError('recording clip must exist inside its cache')
        lang = cfg.get('lang')
        if lang not in voice.LANGS or cfg.get('voice') not in dict(voice.VOICES[lang]):
            raise ValueError('choose an existing local Kokoro voice for the project language')
        _number(cfg.get('speed', 1), 'speed', minimum=voice.SPEEDS[0], maximum=voice.SPEEDS[1])
        workers = cfg.get('workers', 1)
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 16:
            raise ValueError('workers must be an integer between 1 and 16')
        if mode == 'make':
            _local_models(lang)
        else:
            from .audio.mix import read_wav, SR
            from .engine import render
            from .package import sha
            from .pipeline import _pace_aspect
            tl = loads((path / 'build/timeline.json').read_text(encoding='utf-8'))
            duration = _number(tl.get('duration'), 'cached duration', minimum=1 / 30)
            if tl.get('storyboard_sha256') != sha(path / 'storyboard.json'):
                raise ValueError('cached timeline does not match the saved storyboard')
            if tl.get('layout', 'landscape') != render.pace_layout(board, _pace_aspect(cfg.get('aspect', '16:9'))):
                raise ValueError('cached timeline layout differs; use make explicitly')
            audio = _text(tl.get('audio'), 'cached narration')
            if Path(audio).name != audio or ':' in audio or '\\' in audio:
                raise ValueError('cached narration must be a filename inside build')
            wav = self.path(str(path.relative_to(self.root) / 'build' / audio))
            pcm, rate = read_wav(wav)
            if rate != SR or abs(len(pcm) / rate - duration) > 1 / rate or not (abs(pcm) > .001).any():
                raise ValueError('cached narration must contain measured, nonzero full-duration PCM')
            if set(tl.get('beats', {})) != {b['id'] for b in board['beats']}:
                raise ValueError('cached timeline beat IDs differ')
        return path, cfg, board

    def render(self, project, start=0, duration=1, mode='synthetic'):
        if mode not in ('synthetic', 'make', 'cached'):
            raise ValueError('mode must be synthetic, make or cached')
        start = _number(start, 'start')
        duration = _number(duration, 'duration', minimum=1 / 30, maximum=30)
        if mode != 'synthetic':
            if start != 0 or duration != 1:
                raise ValueError('make/cached produce the full movie; omit start and duration')
            return self._start_narrated(project, mode)
        path, cfg, board = self.project(project)
        report = self.validate_project(project)
        if not report['ok']:
            raise ValueError('invalid storyboard: ' + '; '.join(report['errors']))
        job = uuid.uuid4().hex
        folder = path / 'build' / 'developer'
        folder.mkdir(parents=True, exist_ok=True)
        output, log = folder / f'{job}.mp4', folder / f'{job}.log'
        command = _worker_command(self.root, ['--render-child', project,
                   '--output', str(output.relative_to(self.root)), '--start', str(start), '--duration', str(duration)])
        with log.open('wb') as diagnostics:
            child = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1],
                                     stdin=subprocess.DEVNULL, stdout=diagnostics, stderr=diagnostics,
                                     start_new_session=True)
        self.jobs[job] = {'process': child, 'output': output, 'log': log, 'cancelled': False}
        return {'job': job, 'pid': child.pid, 'state': 'running', 'synthetic_timing': True,
                'path': str(output), 'diagnostics': str(log)}

    def _start_narrated(self, project, mode):
        from . import pipeline
        from .project_store import ProjectStore
        path, cfg, board = self._narrated_project(project, mode)
        saved = ProjectStore(path).load()
        if any(e['process'].poll() is None and e.get('project') == path for e in self.jobs.values()):
            raise ValueError('a narrated job already owns this project')
        job = uuid.uuid4().hex
        folder = path / 'build/developer'
        folder.mkdir(parents=True, exist_ok=True)
        output = path / (pipeline._output_stem(board, cfg) + '.mp4')
        log, receipt, progress, cancel = [folder / f'{job}.{suffix}' for suffix in ('log', 'json', 'progress.json', 'cancel')]
        command = _worker_command(self.root, ['--narrated-child', project, '--mode', mode,
            '--receipt', str(receipt.relative_to(self.root)), '--progress', str(progress.relative_to(self.root)),
            '--cancel-file', str(cancel.relative_to(self.root)), '--revision', saved['revision']])
        with log.open('wb') as diagnostics:
            child = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
                                     stdout=diagnostics, stderr=diagnostics, start_new_session=True)
        self.jobs[job] = {'process': child, 'output': output, 'log': log, 'cancelled': False,
                          'mode': mode, 'project': path, 'receipt': receipt, 'progress': progress, 'cancel': cancel}
        return {'job': job, 'pid': child.pid, 'state': 'running', 'mode': mode,
                'synthetic_timing': False if mode == 'cached' else None,
                'timing': 'measured cached narration' if mode == 'cached' else 'pending measured narration',
                'path': str(output), 'diagnostics': str(log),
                'direction': 'saved plan' if cfg.get('plan_v3') else 'rules fallback from saved storyboard; no picture search',
                'cost': 'local CPU/time; no provider or API charges'}

    def status(self, job):
        entry = self.jobs.get(job)
        if entry is None:
            raise ValueError('unknown job; only jobs owned by this server can be inspected or cancelled')
        code = entry['process'].poll()
        output = entry['output']
        if 'mode' in entry:
            result = {'job': job, 'pid': entry['process'].pid, 'exit_code': code,
                      'path': str(output), 'diagnostics': str(entry['log']), 'mode': entry['mode'],
                      'synthetic_timing': False if entry['mode'] == 'cached' else None,
                      'timing': 'measured cached narration' if entry['mode'] == 'cached' else 'pending measured narration'}
            progress = entry['progress']
            if progress.is_file() and not progress.is_symlink():
                result['progress'] = loads(progress.read_text(encoding='utf-8'))
            state = 'running' if code is None else 'cancelled' if entry['cancelled'] else 'failed'
            receipt = entry['receipt']
            if code == 0 and receipt.is_file() and not receipt.is_symlink():
                measured = loads(receipt.read_text(encoding='utf-8'))
                from .package import sha
                if (measured.get('validated') and output.is_file() and not output.is_symlink()
                        and sha(output) == measured.get('video_sha256')):
                    state = 'succeeded'
                    result.update(measured)
            result['state'] = state
            return result
        if code is None:
            state = 'running'
        elif entry['cancelled']:
            state = 'cancelled'
        elif code == 0 and not output.is_symlink() and output.is_file() and output.stat().st_size > 0:
            state = 'succeeded'
        else:
            state = 'failed'
        return {'job': job, 'pid': entry['process'].pid, 'state': state, 'exit_code': code,
                'path': str(output), 'diagnostics': str(entry['log']), 'synthetic_timing': True}

    def cancel(self, job):
        status = self.status(job)
        entry = self.jobs[job]
        child = entry['process']
        if status['state'] == 'running':
            # This process group was created by our Popen; never search command text or accept a PID.
            entry['cancelled'] = True
            if 'mode' in entry:
                entry['cancel'].write_text('cancel\n', encoding='utf-8')
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=2)
                return self.status(job)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
        return self.status(job)

    def close(self):
        for job in self.jobs:
            self.cancel(job)


def _schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1}
PROJECT = {'project': TEXT}
TOOLS = [
    {'name': 'create_project', 'description': 'Create an offline editable storyboard skeleton from literal script text or a bundled fictional starter; no narration or search downloads.',
     'inputSchema': _schema({**PROJECT, 'script': TEXT, 'starter': TEXT, 'lang': {'type': 'string', 'enum': ['en', 'zh', 'es']}, 'title': TEXT}, ['project'])},
    {'name': 'validate_project', 'description': 'Validate a confined storyboard with the existing pipeline validator.',
     'inputSchema': _schema(PROJECT, ['project'])},
    {'name': 'chart_add', 'description': 'Append attributed bars or a bounded kinodraw-scientific/1 observation/model plot from local JSON; retain scientific source assets and exact coordinates, with no fetching or code evaluation.',
     'inputSchema': _schema({**PROJECT, 'beat': TEXT, 'source': TEXT}, ['project', 'beat', 'source'])},
    {'name': 'preview_png', 'description': 'Render an actual PNG with the existing renderer and estimated timing, without voice or network.',
     'inputSchema': _schema({**PROJECT, 'time': {'type': 'number', 'minimum': 0}}, ['project'])},
    {'name': 'render', 'description': (
        'Explicit action: default synthetic renders a silent estimated-timing preview (1/30 to 30 seconds). '
        'Opt in with mode=make for a full narrated, validated MP4 and sidecars using locally cached, '
        'checksum-verified Kokoro ONNX models and measured speech timing; mode=cached reuses a matching '
        'saved timeline/narration without TTS/models/provider calls. Omit start/duration for full movies. '
        'Saved v3 plans are reused; otherwise rules scenes use the saved storyboard without picture search. '
        'No downloads, secret lookup or live providers. Local cost: CPU/time, no API charges. '
        'Poll status for actual encoded frames, ETA, stage, validation and owned exit code.'),
     'inputSchema': _schema({**PROJECT, 'start': {'type': 'number', 'minimum': 0}, 'duration': {'type': 'number', 'minimum': 1 / 30, 'maximum': 30},
                             'mode': {'type': 'string', 'enum': ['synthetic', 'make', 'cached'], 'default': 'synthetic'}}, ['project'])},
    {'name': 'status', 'description': 'Inspect an opaque job ID owned by this server; return its actual process exit code.',
     'inputSchema': _schema({'job': TEXT}, ['job'])},
    {'name': 'cancel', 'description': 'Cancel an owned render process group and reap its child; no arbitrary PIDs.',
     'inputSchema': _schema({'job': TEXT}, ['job'])},
]


def _validate_movie(video, timeline, context, work):
    """Fully count/decode video and audio, retaining the owned encoder's exit."""
    import numpy as np
    from .engine.render import FFMPEG, FPS
    from .progress import RenderContext, encoded_frames, validate_frames, wait_process
    check = RenderContext(token=context.token)
    expected = round(timeline['duration'] * FPS)
    validate_frames(FFMPEG, video, expected, check, group=False)
    pcm = Path(work) / 'validated-audio.pcm'
    with pcm.open('wb') as output, (Path(work) / 'audio-errors.txt').open('w+b') as errors:
        child = context.token.register(subprocess.Popen([
            FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', str(video),
            '-map', '0:a:0', '-ar', '48000', '-ac', '1', '-f', 's16le', '-'],
            stdout=output, stderr=errors), group=False)
        try:
            wait_process(child, check)
            errors.seek(0)
            if errors.read().strip():
                raise RuntimeError('finished audio decode reported errors')
            code = child.returncode
        finally:
            context.token.stop(child)
    samples = np.fromfile(pcm, dtype='<i2')
    peak = float(np.max(np.abs(samples.astype(np.float32))) / 32768) if samples.size else 0
    if peak <= .001 or abs(samples.size / 48000 - timeline['duration']) > .08:
        raise RuntimeError('finished audio is silent or differs from the full measured duration')
    return {'frames': encoded_frames(Path(str(video) + '.decode-progress')),
            'decode_exit': 0, 'audio_decode_exit': code,
            'audio_samples': int(samples.size), 'audio_peak': peak, 'duration': timeline['duration']}


def _narrated_worker(service, args):
    from . import pipeline, voice
    from .package import sha
    from .progress import CancellationToken, RenderContext
    from .project_store import ProjectStore
    path, cfg, _ = service._narrated_project(args.narrated_child, args.mode)
    receipt, progress_file, cancel_file = map(service.path, (args.receipt, args.progress, args.cancel_file))
    class Token(CancellationToken):
        def check(self):
            if cancel_file.exists():
                self._event.set()
            super().check()
            store._check(store._state(), args.revision)
    token = Token()
    status = {'stage': 'prepare', 'frames': 0, 'total': 0, 'elapsed': 0, 'eta': None}
    lock = threading.RLock()
    started = time.monotonic()
    def emit(**values):
        with lock:
            status.update(values)
            service._save(progress_file, status)
    def frames(value):
        emit(frames=value.frames, total=value.total, elapsed=value.elapsed, eta=value.eta)
    def stage(name, done=0, total=1):
        token.check()
        emit(stage=name, stage_done=done, stage_total=total, job_elapsed=time.monotonic() - started)
    stage.check_cancelled = token.check
    context = RenderContext(token=token, callback=frames)
    store = ProjectStore(path)
    previous = signal.signal(signal.SIGTERM, lambda *_: token._event.set())
    # The isolated worker never calls the download-capable ensure_models implementation.
    ensure_models = voice.ensure_models
    voice.ensure_models = lambda lang, progress=None: _local_models(lang, checksum=False)
    try:
        with tempfile.TemporaryDirectory(prefix='mcp-make-') as folder:
            scratch = Path(folder) / 'project'
            with store.locked():
                store._check(store._state(), args.revision)
                sources = _sources(path, cfg)
                pipeline._copy_project(path, scratch)
            # Job diagnostics belong to the server, never to pipeline publication.
            shutil.rmtree(scratch / 'build/developer', ignore_errors=True)
            token.check()
            if args.mode == 'make':
                scratch_store = ProjectStore(scratch)
                original = scratch_store.load()
                settings = original['settings']
                if not cfg.get('plan_v3'):
                    from .director.v3.rules import from_rules
                    plan = from_rules(original['storyboard'])
                    settings.update(director='rules', director_v3=True, plan_v3=plan,
                                    scene_treatments=plan['scenes'])
                else:
                    settings['director_v3'] = True
                scratch_store.save(original['storyboard'], settings, original['revision'])
                qa = pipeline.produce(scratch, progress=stage, context=context)
            else:
                scratch_store = ProjectStore(scratch)
                original = scratch_store.load()
                settings = original['settings']
                settings['director'] = 'rules'
                settings['director_v3'] = bool(settings.get('plan_v3'))
                scratch_store.save(original['storyboard'], settings, original['revision'])
                stage('render')
                pipeline.render(scratch, context=context)
                stage('finish')
                qa = pipeline.finish(scratch, context=context)
            if not qa.get('ok'):
                raise RuntimeError('pipeline finish failed validation: ' + dumps(qa.get('problems')))
            stage('validate')
            tl = loads((scratch / 'build/timeline.json').read_text(encoding='utf-8'))
            from .audio.mix import read_wav
            narration, _ = read_wav(scratch / 'build' / tl['audio'])
            if not (abs(narration) > .001).any():
                raise RuntimeError('narration is silent')
            video = Path(qa['video'])
            validation = _validate_movie(video, tl, context, folder)
            suffixes = ('.srt', '.vtt', '-chapters.txt', '-transcript.md', '-description.txt', '-thumbnail.png')
            sidecars = [video.with_name(video.stem + suffix) for suffix in suffixes]
            if any(not p.is_file() or p.stat().st_size == 0 for p in sidecars):
                raise RuntimeError('pipeline did not produce every finished sidecar')
            qa['video'] = str(path / video.name)
            service._save(scratch / 'build/qa.json', qa)
            stage('publish')
            with store.locked():
                store._check(store._state(), args.revision)
                if _sources(path, cfg) != sources:
                    raise ValueError('project source changed while rendering')
                # Recheck indirect paths and links before touching the destination.
                service._narrated_project(args.narrated_child, args.mode)
                with token._lock:
                    token.check()
                    pipeline._commit_outputs(scratch, path, context)
                    context.published = True
            result = {'validated': True, 'synthetic_timing': False, 'timing': 'measured narration',
                      'path': str(path / video.name), 'video_sha256': sha(video), 'validation': validation,
                      'sidecars': [str(path / p.name) for p in sidecars], 'pipeline_qa': qa,
                      'direction': 'saved plan' if cfg.get('plan_v3') else 'rules fallback from saved storyboard; no picture search'}
            service._save(receipt, result)
            emit(stage='succeeded', job_elapsed=time.monotonic() - started)
    finally:
        voice.ensure_models = ensure_models
        signal.signal(signal.SIGTERM, previous)



class RPCError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Server:
    def __init__(self, root):
        self.developer = Developer(root)
        self.initialized = False
        self.ready = False

    def dispatch(self, message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            raise RPCError(-32600, 'Invalid JSON-RPC request')
        if 'id' in message and (isinstance(message['id'], bool) or not isinstance(message['id'], (str, int, type(None)))):
            raise RPCError(-32600, 'Invalid request ID')
        method, params = message['method'], message.get('params', {})
        if not isinstance(params, dict):
            raise RPCError(-32602, 'params must be an object')
        if method == 'initialize':
            version = params.get('protocolVersion')
            if not isinstance(version, str):
                raise RPCError(-32602, 'protocolVersion is required')
            self.initialized = True
            self.ready = False
            supported = ('2024-11-05', '2025-03-26', '2025-06-18')
            return {'protocolVersion': version if version in supported else supported[-1],
                    'capabilities': {'tools': {'listChanged': False}},
                    'serverInfo': {'name': 'kinodraw-offline', 'version': '0.1.0'}}
        if method == 'notifications/initialized':
            self.ready = self.initialized
            return None
        if method == 'ping':
            return {}
        if method.startswith('notifications/'):
            return None
        if method not in ('tools/list', 'tools/call'):
            raise RPCError(-32601, f'Method unavailable: {method}')
        if not self.ready:
            raise RPCError(-32000, 'initialize and notifications/initialized are required')
        if method == 'tools/list':
            return {'tools': TOOLS}
        name, arguments = params.get('name'), params.get('arguments', {})
        spec = next((tool for tool in TOOLS if tool['name'] == name), None)
        try:
            if spec is None:
                raise ValueError(f'tool unavailable: {name}; use one of the seven advertised tools')
            if not isinstance(arguments, dict):
                raise ValueError('arguments must be an object')
            schema = spec['inputSchema']
            if set(arguments) - set(schema['properties']) or set(schema['required']) - set(arguments):
                raise ValueError('unexpected or missing tool arguments')
            for key, value in arguments.items():
                if schema['properties'][key]['type'] == 'string':
                    _text(value, key)
            _finite(arguments)
            with contextlib.redirect_stdout(sys.stderr):
                result = getattr(self.developer, name)(**arguments)
            content = [{'type': 'text', 'text': dumps(result)}]
            if name == 'preview_png':
                data = Path(result['path']).read_bytes()
                content.append({'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data).decode('ascii')})
            return {'content': content, 'isError': name == 'validate_project' and not result['ok']}
        except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError, AttributeError, IndexError, ImportError) as error:
            print(f'{name}: {error}', file=sys.stderr, flush=True)
            return {'content': [{'type': 'text', 'text': str(error)}], 'isError': True}

    def serve(self, stdin=None, stdout=None):
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
        try:
            for line in stdin:
                message = None
                try:
                    message = loads(line)
                    # Tool notifications are invalid and must never cause side effects.
                    if isinstance(message, dict) and 'id' not in message and message.get('method') in ('tools/call', 'initialize'):
                        raise RPCError(-32600, 'this method requires a request ID')
                    result = self.dispatch(message)
                    reply = {'jsonrpc': '2.0', 'id': message.get('id'), 'result': result}
                except (ValueError, UnicodeError, RecursionError) as error:
                    reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(error)}}
                except RPCError as error:
                    request_id = message.get('id') if isinstance(message, dict) else None
                    if isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None))):
                        request_id = None
                    reply = {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': error.code, 'message': error.message}}
                if (isinstance(message, dict) and 'id' not in message
                        and message.get('jsonrpc') == '2.0' and isinstance(message.get('method'), str)):
                    continue
                stdout.write(dumps(reply) + '\n')
                stdout.flush()
        finally:
            self.developer.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--render-child', help=argparse.SUPPRESS)
    parser.add_argument('--narrated-child', help=argparse.SUPPRESS)
    parser.add_argument('--mode', choices=('make', 'cached'), help=argparse.SUPPRESS)
    parser.add_argument('--receipt', help=argparse.SUPPRESS)
    parser.add_argument('--progress', help=argparse.SUPPRESS)
    parser.add_argument('--cancel-file', help=argparse.SUPPRESS)
    parser.add_argument('--revision', help=argparse.SUPPRESS)
    parser.add_argument('--output', help=argparse.SUPPRESS)
    parser.add_argument('--start', type=float, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--duration', type=float, default=1, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.narrated_child:
            _narrated_worker(Developer(args.root), args)
        elif args.render_child:
            from .engine import render
            service = Developer(args.root)
            start = _number(args.start, 'start')
            duration = _number(args.duration, 'duration', minimum=1 / 30, maximum=30)
            path, aspect, tl, prod = service._production(args.render_child)
            if start >= tl['duration'] or start + duration > tl['duration']:
                raise ValueError('render interval is outside the estimated timeline')
            output = service.path(args.output)
            render.encode(prod, start, max(1, round(duration * render.FPS)), output, 20)
            service._save(output.with_suffix('.json'), {'path': str(output), 'synthetic_timing': True,
                          'frames': max(1, round(duration * render.FPS)), 'warnings': prod.warnings})
        else:
            Server(args.root).serve()
    except (ValueError, OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

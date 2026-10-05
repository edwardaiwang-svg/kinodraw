"""Small offline MCP server: one UTF-8 JSON-RPC message per stdio line.

The rendering, storyboard building and validation stay in the existing pipeline.
No director providers, narration, downloads, app migration, or credentials are used.
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
import signal
import subprocess
import sys
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
        path, cfg, board = self.project(project)
        source_path = self.path(source)
        if source_path.suffix.lower() != '.json':
            raise ValueError('chart source must be a local .json file')
        raw = source_path.read_bytes()
        data = loads(raw.decode('utf-8'), parse_float=_chart_float)
        if not isinstance(data, dict):
            raise ValueError('chart source must be an object')
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
        self._save(path / 'storyboard.json', board)
        return {'visual': visual['id'], 'source_sha256': digest, 'rows': len(mapped)}

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
        size = (540, 960) if aspect == '9:16' else (960, 540)
        prod.frame(time).convert('RGB').resize(size).save(output, 'PNG')
        return {'path': str(output), 'mimeType': 'image/png', 'synthetic_timing': True,
                'width': size[0], 'height': size[1], 'warnings': prod.warnings}

    def render(self, project, start=0, duration=1):
        start = _number(start, 'start')
        duration = _number(duration, 'duration', minimum=1 / 30, maximum=30)
        path, cfg, board = self.project(project)
        report = self.validate_project(project)
        if not report['ok']:
            raise ValueError('invalid storyboard: ' + '; '.join(report['errors']))
        job = uuid.uuid4().hex
        folder = path / 'build' / 'developer'
        folder.mkdir(parents=True, exist_ok=True)
        output, log = folder / f'{job}.mp4', folder / f'{job}.log'
        command = [sys.executable, '-m', 'kinodraw.mcp_server', '--root', str(self.root),
                   '--render-child', project, '--output', str(output.relative_to(self.root)),
                   '--start', str(start), '--duration', str(duration)]
        with log.open('wb') as diagnostics:
            child = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1],
                                     stdin=subprocess.DEVNULL, stdout=diagnostics, stderr=diagnostics,
                                     start_new_session=True)
        self.jobs[job] = {'process': child, 'output': output, 'log': log, 'cancelled': False}
        return {'job': job, 'pid': child.pid, 'state': 'running', 'synthetic_timing': True,
                'path': str(output), 'diagnostics': str(log)}

    def status(self, job):
        entry = self.jobs.get(job)
        if entry is None:
            raise ValueError('unknown job; only jobs owned by this server can be inspected or cancelled')
        code = entry['process'].poll()
        output = entry['output']
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
    {'name': 'chart_add', 'description': 'Append a real bars visual from an attributed local JSON source, preserving supplied nonnegative values; no inferred or fabricated data.',
     'inputSchema': _schema({**PROJECT, 'beat': TEXT, 'source': TEXT}, ['project', 'beat', 'source'])},
    {'name': 'preview_png', 'description': 'Render an actual PNG with the existing renderer and estimated timing, without voice or network.',
     'inputSchema': _schema({**PROJECT, 'time': {'type': 'number', 'minimum': 0}}, ['project'])},
    {'name': 'render', 'description': 'Start one owned subprocess for a silent MP4 using estimated timing; duration 1/30 to 30 seconds. Poll status for actual completion.',
     'inputSchema': _schema({**PROJECT, 'start': {'type': 'number', 'minimum': 0}, 'duration': {'type': 'number', 'minimum': 1 / 30, 'maximum': 30}}, ['project'])},
    {'name': 'status', 'description': 'Inspect an opaque job ID owned by this server; return its actual process exit code.',
     'inputSchema': _schema({'job': TEXT}, ['job'])},
    {'name': 'cancel', 'description': 'Cancel an owned render process group and reap its child; no arbitrary PIDs.',
     'inputSchema': _schema({'job': TEXT}, ['job'])},
]


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
                raise ValueError(f'tool unavailable: {name}; writer/export/ZIP/progress are not implemented here')
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
    parser.add_argument('--output', help=argparse.SUPPRESS)
    parser.add_argument('--start', type=float, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--duration', type=float, default=1, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.render_child:
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
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

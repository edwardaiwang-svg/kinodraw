"""KinoDraw's local server: a JSON API for the single-page app, bound to 127.0.0.1 only.

Every API request must carry the per-launch token (header X-Studio-Token) that the server
injects into the page, so other web pages on this computer cannot drive it.
"""
from __future__ import annotations

import difflib
import io
import json
import mimetypes
import re
import secrets
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import PRODUCT, director, paths, pipeline, styles, voice
from ..director.validate import validate
from ..library import OWN, PICTURES, PICTURE_MAX, PICTURE_TYPES, missing_pictures, own_path, resolve
from ..package import sha

STATIC = Path(__file__).resolve().parent / 'static'
SVG_POLICY = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; sandbox"
FONTS = Path(__file__).resolve().parents[1] / 'assets' / 'fonts'
CONFIG = paths.config_dir() / 'studio.json'


def projects_root() -> Path:
    cfg = _config()
    root = Path(cfg.get('projects') or paths.projects_dir())
    root.mkdir(parents=True, exist_ok=True)
    return root


def _config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - first run
        return {}


def _save_config(cfg: dict):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=1), encoding='utf-8')


# ------------------------------------------------------------------ jobs
class Jobs:
    """One heavy job at a time (voice/render are CPU-bound); others wait in order."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()

    def start(self, kind: str, project: str, fn) -> str:
        jid = uuid.uuid4().hex[:10]
        job = {'id': jid, 'kind': kind, 'project': project, 'state': 'queued', 'stage': '', 'done': 0, 'total': 0,
               'error': None, 'result': None, 'started': time.time()}
        with self.lock:
            self.jobs[jid] = job

        def progress(stage, done, total):
            job.update(stage=stage, done=done, total=total)

        def run():
            with self.run_lock:
                job['state'] = 'running'
                try:
                    job['result'] = fn(progress)
                    job['state'] = 'done'
                except Exception as error:  # noqa: BLE001 - shown to the user
                    job.update(state='failed', error=_plain(error))
                    traceback.print_exc()
        threading.Thread(target=run, daemon=True).start()
        return jid

    def get(self, jid: str) -> dict | None:
        return self.jobs.get(jid)


JOBS = Jobs()


def _plain(error: Exception) -> str:
    """What a failed job tells the user: a ValueError's message is written for them (a recording's without the
    command line's advice: the Narrator tab has its own); anything else is a bug, named so it can be reported."""
    if isinstance(error, voice.RecordingError):
        return error.plain
    if isinstance(error, ValueError):
        return str(error)
    return f'Something went wrong ({type(error).__name__}: {error}). Please tell us using "Feedback or a problem?".'


def _project(name: str) -> Path:
    if not re.fullmatch(r'[\w\- .]{1,80}', name) or name.startswith('.'):
        raise ValueError('bad project name')
    path = projects_root() / name
    if not (path / 'project.json').exists():
        raise FileNotFoundError(name)
    return path


def _slug(title: str) -> str:
    base = re.sub(r'[^\w\- ]+', '', title).strip()[:60] or 'Video'
    name, k = base, 2
    while (projects_root() / name).exists():
        name, k = f'{base} {k}', k + 1
    return name


def _summary(path: Path) -> dict:
    try:
        board = pipeline.storyboard(path)
        cfg = pipeline.settings(path)
        videos = sorted(p.name for p in path.glob('*.mp4') if not p.name.endswith('.partial.mp4'))
        return {'name': path.name, 'title': board['title'][board['lang']], 'lang': board['lang'],
                'beats': len(board['beats']), 'director': cfg.get('director', 'rules'), 'videos': videos,
                'thumbnail': next((p.name for p in path.glob('*-thumbnail.png')), None),
                'modified': path.stat().st_mtime}
    except Exception:  # noqa: BLE001 - a half-created folder
        return {'name': path.name, 'title': path.name, 'broken': True, 'modified': path.stat().st_mtime}


# ------------------------------------------------------------------ actions
def _voice_settings(lang: str, voice_id, speed) -> dict:
    if voice_id not in dict(voice.VOICES.get(lang, [])):
        raise ValueError('Choose a voice for this language.')
    try:
        speed = round(float(speed), 2)
    except (TypeError, ValueError):
        raise ValueError('Speed should be between 0.85 and 1.15.') from None
    if not voice.SPEEDS[0] <= speed <= voice.SPEEDS[1]:
        raise ValueError('Speed should be between 0.85 and 1.15.')
    return {'voice': voice_id, 'speed': speed}


def voice_settings(name: str, body: dict | None = None) -> dict:
    """Read or save the project's voice, speed and pronunciations."""
    path = _project(name)
    cfg = pipeline.settings(path)
    pronounce = path / pipeline.PRONOUNCE
    if body is not None:
        settings = _voice_settings(cfg['lang'], body.get('voice'), body.get('speed'))
        text = body.get('pronounce', '')
        if not isinstance(text, str):
            raise ValueError('Pronunciations should be text: word = how to say it.')
        voice.parse_lexicon(text)
        pipeline._save(path / 'project.json', {**cfg, **settings})
        if text.strip():
            pronounce.write_text(text, encoding='utf-8')
        else:
            pronounce.unlink(missing_ok=True)
        cfg.update(settings)
    return {'lang': cfg['lang'], 'voice': cfg['voice'], 'speed': cfg['speed'],
            'pronounce': pronounce.read_text(encoding='utf-8') if pronounce.exists() else ''}


def create_project(body: dict) -> dict:
    text = (body.get('text') or '').strip()
    if not text:
        raise ValueError('paste a script or choose a file')
    title = (body.get('title') or '').strip() or None
    from .. import ingest
    doc = ingest.read(text, title=title)
    name = _slug(doc.title)
    path = projects_root() / name
    mode = body.get('director') or 'rules'
    lang = body.get('lang') or doc.lang
    settings = {k: body[k] for k in ('workers',) if body.get(k)}
    settings.update(_voice_settings(lang, body.get('voice') or voice.LANGS[lang]['voice'], body.get('speed', 1.0)))
    settings['aspect'] = pipeline.validate_aspect(body.get('aspect', '16:9'), body.get('look'))

    def job(progress):
        progress('storyboard', 0, 1)
        pipeline.new_project(text, path, title=title, lang=body.get('lang') or None,
                             direction={**{k: body.get(k) for k in ('look', 'story', 'motion')},
                                        'brand': {k: v for k, v in (body.get('brand') or {}).items() if v} or None},
                             director=mode, **settings)
        report = director.direct(path, mode, body.get('model') or None, body.get('base_url') or None, progress)
        usage = report.get('usage')
        return {'project': name, 'notes': report.get('notes', [])[:20],
                'cost': None if not usage else usage.cost_usd, 'calls': 0 if not usage else usage.calls}
    return {'job': JOBS.start('create', name, job), 'project': name}


def set_format(name: str, body: dict) -> dict:
    path = _project(name)
    cfg = pipeline.settings(path)
    cfg['aspect'] = pipeline.validate_aspect(body.get('aspect'), pipeline.storyboard(path).get('look'))
    pipeline._save(path / 'project.json', cfg)
    return cfg


def docx_script(name: str, data: bytes) -> str:
    """A chosen .docx as Markdown script text, shown in the editor so the user sees what was read."""
    from .. import ingest
    if Path(name).suffix.lower() != '.docx':
        raise ValueError('choose a .md, .txt or .docx file')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(name).name
        path.write_bytes(data)
        try:
            doc = ingest.read(path)
        except (zipfile.BadZipFile, KeyError) as error:
            raise ValueError(f'{path.name} could not be read as a Word document') from error
    parts = [f'# {doc.title}', *doc.preamble]
    for section in doc.sections:
        parts += [f'## {section.heading}', *section.paragraphs]
    return '\n\n'.join(parts)


def make_video(name: str) -> dict:
    path = _project(name)

    def job(progress):
        cfg = pipeline.settings(path)
        cfg['credit'] = _config().get('credit', True)  # the Settings switch applies to every video made from now on
        (path / 'project.json').write_text(json.dumps(cfg, indent=1), encoding='utf-8')
        clips = pipeline.narrate(path, progress)
        progress('timeline', 0, 1)
        pipeline.build_audio(path, clips)
        progress('render', 0, 1)
        pipeline.render(path)
        progress('finish', 0, 1)
        qa = pipeline.finish(path)
        return {'video': Path(qa['video']).name, 'ok': qa['ok'], 'problems': qa['problems'], 'length': qa['length']}
    return {'job': JOBS.start('make', name, job)}


# ------------------------------------------------------------------ your own voice
TAKE_MAX = 2 << 30          # bytes; an hour of uncompressed stereo WAV is about 600 MB


def _takes(path: Path) -> list[Path]:
    return sorted(path.glob('recording.*'))


def narrator(name: str) -> dict:
    """The Narrator tab: who narrates, the script as sentences to read aloud (exactly what the built-in voice says,
    numbers written out), the project's recording, how it matched each sentence when it was last used, and which
    sentences changed after it was recorded. Sentences are numbered from 1, as on the page."""
    path = _project(name)
    cfg, lines = pipeline.settings(path), pipeline.read_aloud(path)
    take = path / cfg['recording'] if cfg.get('recording') else next(iter(_takes(path)), None)
    take = take if take and take.is_file() else None
    digest = sha(take) if take else None
    return {'narrator': 'own' if cfg.get('recording') else 'builtin', 'voice': cfg['voice'], 'lang': cfg['lang'],
            'take': take.name if take else None, 'lines': lines, 'check': _check(path, digest, lines),
            'changed': _changed(path, digest, lines)}


def _check(path: Path, digest: str | None, lines: list[dict]) -> dict | None:
    """How the take matched each sentence when it was last used (the alignment's report, or why it could not be cut),
    or None if it has not been used since it was recorded or the sentences changed."""
    if not digest:
        return None
    said, check = [[line['beat'], line['text']] for line in lines], None
    report, problem = path / 'voice' / 'recording-align.json', path / 'voice' / 'recording-problem.json'
    if report.is_file():
        info = json.loads(report.read_text(encoding='utf-8'))
        rows = info.get('sentences') or []
        if info.get('sha256') == digest and [[r['beat'], r['text']] for r in rows] == said:
            check = {'ok': info['match'] >= voice.MATCH, 'poor': [n for n, r in enumerate(rows, 1) if r['check']],
                     'missing': [], 'problem': None}
    if problem.is_file():
        info = json.loads(problem.read_text(encoding='utf-8'))
        if info['sha256'] == digest and info.get('lines') == said:
            check = {**(check or {'poor': []}), 'ok': False, 'problem': info['problem'],
                     'missing': [n for n, line in enumerate(lines, 1) if line['beat'] == info['missing']]}
    return check


def _changed(path: Path, digest: str | None, lines: list[dict]) -> list[int]:
    """The sentences that say something else than when the take was added (an edited takeaway note, a re-planned
    storyboard): the recording does not say them. A sentence taken out marks the one now in its place."""
    snapshot = path / 'voice' / 'recording-script.json'
    if not digest or not snapshot.is_file():
        return []
    info = json.loads(snapshot.read_text(encoding='utf-8'))
    if info['sha256'] != digest:
        return []
    now, changed = [line['text'] for line in lines], set()
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, info['lines'], now, autojunk=False).get_opcodes():
        if tag != 'equal':
            changed.update(range(j1, j2) if j2 > j1 else [min(j1, len(now) - 1)])
    return sorted(n + 1 for n in changed)


def list_pictures(name: str) -> list[dict]:
    """The project's pictures available for manual picking, in filename order."""
    folder = _project(name) / PICTURES
    pictures = []
    for path in sorted(folder.glob('*')):
        if path.name.startswith('.') or path.suffix.lower() not in PICTURE_TYPES:
            continue
        if resolve(OWN + path.name, folder.parent):
            pictures.append({'id': OWN + path.name, 'name': path.name})
    return pictures


_picture_lock = threading.Lock()


def save_picture(name: str, filename: str, stream, length: int) -> dict:
    """Validate and keep the raw picture locally, without overwriting another picture."""
    import resvg_py
    from PIL import Image
    project = _project(name)
    if length <= 0:
        raise ValueError(f'“{filename}” is empty. Choose your picture again.')
    if length > PICTURE_MAX:
        raise ValueError(f'“{filename}” is too big (over 10 MB). Make it smaller and try again.')
    suffix = Path(filename).suffix.lower()
    if suffix not in PICTURE_TYPES:
        raise ValueError('Choose a PNG, JPG or SVG picture.')
    data = stream.read(length)
    if len(data) != length:
        raise ValueError(f'The upload of “{filename}” stopped part-way. Try again.')
    try:
        if suffix == '.svg':
            text = data.decode('utf-8')
            if '<svg' not in text:
                raise ValueError('no SVG')
            resvg_py.svg_to_bytes(svg_string=text, width=64, height=64)
        else:
            signature = b'\x89PNG\r\n\x1a\n' if suffix == '.png' else b'\xff\xd8\xff'
            if not data.startswith(signature):
                raise ValueError('wrong picture type')
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()                    # verify() skips JPEG data, so a cut-off photo would pass
    except Exception:
        raise ValueError(f'“{filename}” isn’t a picture KinoDraw can open. Save it again as a PNG, JPG or SVG '
                         'and upload it again.') from None
    stem = re.sub(r'[^\w\-]', '', Path(filename).stem.replace(' ', '-'))[:60] or 'picture'
    folder = project / PICTURES
    folder.mkdir(exist_ok=True)
    with _picture_lock:
        number = 1
        while True:
            filename = f'{stem}{"" if number == 1 else f"-{number}"}{suffix}'
            target = folder / filename
            if not target.exists() and not target.is_symlink():
                own_path(OWN + filename, project)
                break
            if resolve(OWN + filename, project) and target.read_bytes() == data:
                return {'id': OWN + filename, 'name': filename, 'pictures': list_pictures(name)}
            number += 1
        part = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, prefix='.upload-', delete=False) as f:
                part = Path(f.name)
                f.write(data)
            part.rename(target)
        finally:
            if part:
                part.unlink(missing_ok=True)
    return {'id': OWN + filename, 'name': filename, 'pictures': list_pictures(name)}


def save_take(name: str, filename: str, stream, length: int) -> dict:
    """Keep an uploaded (or recorded) reading of the script as the project's narration, as it is: anything the
    bundled ffmpeg can play is fine (phone voice memos, mp3, wav, ogg, webm, 3gp, amr...)."""
    path = _project(name)
    if not length:
        raise ValueError(f'“{filename}” is empty. Choose your recording again.')
    if length > TAKE_MAX:
        raise ValueError(f'“{filename}” is too big (over 2 GB). Save it as .m4a or .mp3 and try again.')
    suffix = Path(filename).suffix.lower()
    suffix = suffix if re.fullmatch(r'\.[a-z0-9]{1,5}', suffix) else '.audio'
    part = path / f'.upload{suffix}'
    try:
        with part.open('wb') as f:
            left = length
            while left and (chunk := stream.read(min(left, 1 << 20))):
                f.write(chunk)
                left -= len(chunk)
        if left:
            raise ValueError(f'The upload of “{filename}” stopped part-way. Try again.')
        try:
            voice._decode(part)
        except ValueError:
            raise ValueError(f'“{filename}” isn’t a recording we can play. Voice memos (.m4a), .mp3 and .wav files '
                             'all work: save or export your recording as one of those and try again.') from None
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    for old in _takes(path):
        old.unlink()
    take = part.rename(path / f'recording{suffix}')
    pipeline.set_recording(path, take)
    snapshot = path / 'voice' / 'recording-script.json'        # what it reads, so later edits can be pointed out
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_text(json.dumps({'sha256': sha(take), 'lines': [line['text'] for line in pipeline.read_aloud(path)]},
                                 ensure_ascii=False), encoding='utf-8')
    return narrator(name)


def set_narrator(name: str, body: dict) -> dict:
    """Narrate with the built-in voice (your recording stays in the project) or with your own recording again."""
    path = _project(name)
    if body.get('narrator') == 'builtin':
        pipeline.set_recording(path, None)
    elif body.get('narrator') == 'own':
        takes = _takes(path)
        if not takes:
            raise ValueError('Upload or record your reading of the script first.')
        pipeline.set_recording(path, takes[0])
    else:
        raise ValueError('narrator must be "builtin" or "own"')
    return narrator(name)


def use_take(name: str) -> dict:
    """Cut the recording into the script's sentences and time every drawing to it. A take that does not fit the
    script is an answer, not a failure: the result says what did not match, in the words the alignment used."""
    path = _project(name)
    if not pipeline.settings(path).get('recording'):
        raise ValueError('Upload or record your reading of the script first.')

    def job(progress):
        problem = path / 'voice' / 'recording-problem.json'
        problem.unlink(missing_ok=True)
        try:
            clips = pipeline.narrate(path, progress)
        except ValueError as error:                # remembered, so the project shows it when opened again
            take = path / pipeline.settings(path)['recording']
            problem.parent.mkdir(exist_ok=True)
            problem.write_text(json.dumps({'sha256': sha(take), 'lines': [[line['beat'], line['text']]
                                                                          for line in pipeline.read_aloud(path)],
                                           'missing': getattr(error, 'beat', None), 'problem': _plain(error)},
                                          ensure_ascii=False), encoding='utf-8')
            return narrator(name)
        progress('timeline', 0, 1)
        pipeline.build_audio(path, clips)
        return narrator(name)
    return {'job': JOBS.start('align', name, job)}


def redirect(name: str, body: dict) -> dict:
    path = _project(name)
    mode = body.get('director') or 'rules'

    def job(progress):
        report = director.direct(path, mode, body.get('model') or None, body.get('base_url') or None, progress)
        cfg = pipeline.settings(path)
        cfg['director'] = mode
        (path / 'project.json').write_text(json.dumps(cfg, indent=1), encoding='utf-8')
        usage = report.get('usage')
        return {'notes': report.get('notes', [])[:20], 'cost': None if not usage else usage.cost_usd}
    return {'job': JOBS.start('direct', name, job)}


def move_picture(board: dict, beat_id: str, visual: int, to: int, item: int | None = None) -> dict:
    """Move the picture's content while keeping draw triggers at their positions."""
    moved = deepcopy(board)
    error = 'That picture is no longer on this board. Reload the project.'
    beat = next((b for b in moved.get('beats', []) if b.get('id') == beat_id), None)
    visuals = beat.get('visuals', []) if beat else []

    def in_range(index, pictures):
        return type(index) is int and 0 <= index < len(pictures)

    def set_trigger(picture, trigger):
        if trigger is None:
            picture.pop('trigger', None)
        else:
            picture['trigger'] = trigger

    if not in_range(visual, visuals):
        raise ValueError(error)
    if item is not None:
        group = visuals[visual]
        items = group.get('items', []) if group.get('type') == 'cluster' else []
        if not in_range(item, items) or not in_range(to, items):
            raise ValueError(error)
        triggers = [it.get('trigger') for it in items]
        items.insert(to, items.pop(item))
        for it, trigger in zip(items, triggers):
            set_trigger(it, trigger)
    else:
        if not in_range(to, visuals):
            raise ValueError(error)
        timing = [(v.get('trigger'), [it.get('trigger') for it in v.get('items', [])]) for v in visuals]
        visuals.insert(to, visuals.pop(visual))
        for v, (trigger, item_triggers) in zip(visuals, timing):
            set_trigger(v, trigger)
            if v.get('type') == 'cluster':
                for j, it in enumerate(v.get('items', [])):
                    set_trigger(it, item_triggers[j] if j < len(item_triggers) else None)
    return moved


def save_storyboard(name: str, board: dict) -> dict:
    path = _project(name)
    report = validate(board, path)
    if not report['ok']:
        return {'ok': False, 'errors': report['errors'][:20]}
    (path / 'storyboard.json').write_text(json.dumps(board, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return {'ok': True, 'warnings': report['warnings']}


def search_doodles(query: str, lang: str) -> list:
    """Doodles whose keywords appear in the query first, then the closest in meaning."""
    m = _matcher(lang)
    ranked = m.lexical(query)
    seen = {h.id for h in ranked}
    ranked += [h for h in m.semantic(query, 32) if h.id not in seen]
    return [{'id': h.id, 'desc': m.entries[h.id].get('desc', ''), 'set': m.entries[h.id]['set']} for h in ranked[:32]]


_matchers: dict = {}


_matcher_lock = threading.Lock()


def _matcher(lang):
    from ..director.match import Matcher
    with _matcher_lock:
        if lang not in _matchers:
            _matchers[lang] = Matcher(lang, exclude_categories=())
        return _matchers[lang]


def still(name: str, beat: str | None, offset: float = 0.0, t: float = 0.0) -> bytes:
    import io
    from ..engine import render as renderer
    path = _project(name)
    tl_path = path / 'build' / 'timeline.json'
    board = pipeline.storyboard(path)
    messages = missing_pictures(board, path)
    if messages:
        raise ValueError('\n'.join(messages))
    lang = board['lang']
    if tl_path.exists() and json.loads(tl_path.read_text(encoding='utf-8')).get('storyboard_sha256') == sha(path / 'storyboard.json'):
        tl = json.loads(tl_path.read_text(encoding='utf-8'))
    else:                                             # no narration yet (or edited): estimated timing
        from ..engine import timeline
        tl = timeline.layout(board, lang, timeline.synthetic_clips(board, lang))
    if beat in tl['beats']:
        info = tl['beats'][beat]
        t = min(info['start'] + offset, info['end'] - .1)
    aspect = pipeline.settings(path).get('aspect', '16:9')
    prod = renderer.make_production(board, tl, lang, path, aspect=aspect)
    buf = io.BytesIO()                                # the project's own format, at half its video size
    prod.frame(min(t, tl['duration'] - .05)).convert('RGB').resize((540, 960) if aspect == '9:16' else (960, 540)) \
        .save(buf, 'JPEG', quality=85)
    return buf.getvalue()


def state() -> dict:
    from ..director.llm import cloud
    from ..director.llm.providers import SUGGESTED, saved
    names = saved()                    # names only: opening the app never reads the keychain (no macOS prompt)
    signed_in = bool(cloud.URL) and ('cloud-token' in names or bool(paths.getenv('KINODRAW_CLOUD_TOKEN')))
    return {'projects_root': str(projects_root()), 'cloud_available': bool(cloud.URL), 'cloud_signed_in': signed_in,
            'default_director': 'cloud' if signed_in else 'rules',   # signed out, a first video needs no account
            'cloud': None, 'keys': {p: p in names for p in ('openai', 'anthropic', 'compat', 'command')},
            'advanced': bool(_config().get('advanced')),
            'credit': _config().get('credit', True), 'product': PRODUCT['name'],
            'models': SUGGESTED,
            'formats': [{'value': '16:9', 'label': 'Landscape 16:9 (YouTube)'},
                        {'value': '9:16', 'label': 'Vertical 9:16 (Shorts, TikTok, Reels)'}],
            'styles': [{'value': f"{e['id']}/{e['stories'][0]}", 'label': e['name']['en']}   # the registry's looks
                       for e in styles.looks(ready=True)],                               # that render now
            'voices': {lang: [{'id': vid, 'name': name} for vid, name in choices]
                       for lang, choices in voice.VOICES.items()},
            'models_ready': {lang: not voice.missing_files(lang) for lang in ('en', 'zh', 'es')},
            'notice': paths.NOT_MOVED if paths.left_behind else None}   # Doodle Studio's folders could not move yet


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = 'KinoDraw'
    token = ''
    port = 0

    def log_message(self, *args):                     # quiet console
        pass

    # -- plumbing
    def _send(self, code, body: bytes, ctype='application/json', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        try:
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):   # the page moved on (e.g. <video> seeking)
            pass

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode())

    def _body(self) -> dict:
        n = int(self.headers.get('Content-Length') or 0)
        if n > 20_000_000:
            raise ValueError('request too large')
        return json.loads(self.rfile.read(n) or b'{}')

    def _allowed(self) -> bool:
        host = (self.headers.get('Host') or '').split(':')[0]
        if host not in ('127.0.0.1', 'localhost'):  # DNS-rebinding guard
            return False
        path = urlparse(self.path).path
        if path == '/' or path.startswith(('/static/', '/fonts/')):
            return True
        supplied = self.headers.get('X-Studio-Token') or parse_qs(urlparse(self.path).query).get('token', [''])[0]
        return secrets.compare_digest(supplied, self.token)

    def _file(self, path: Path, ctype=None):
        if not path.is_file():
            return self._json({'error': 'not found'}, 404)
        ctype = ctype or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        size = path.stat().st_size
        extra = {'Accept-Ranges': 'bytes'}
        if ctype == 'image/svg+xml':    # a picture opened as a page (its URL carries the token) runs no scripts here
            extra['Content-Security-Policy'] = SVG_POLICY
        rng = re.match(r'bytes=(\d+)-(\d*)', self.headers.get('Range') or '')
        if rng:                                        # <video> seeks with range requests
            a = int(rng.group(1))
            b = min(int(rng.group(2)) if rng.group(2) else a + (4 << 20) - 1, size - 1)
            with path.open('rb') as f:
                f.seek(a)
                data = f.read(b - a + 1)
            return self._send(206, data, ctype, {**extra, 'Content-Range': f'bytes {a}-{b}/{size}'})
        self._send(200, path.read_bytes(), ctype, extra)

    # -- routes
    def do_GET(self):
        self._route('GET')

    def do_HEAD(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def do_PUT(self):
        self._route('PUT')

    def _route(self, method):
        if not self._allowed():
            return self._json({'error': 'forbidden'}, 403)
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.strip('/').split('/') if p]
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if method == 'GET' and not parts:
                page = (STATIC / 'index.html').read_text(encoding='utf-8').replace('__STUDIO_TOKEN__', self.token)
                return self._send(200, page.encode(), 'text/html; charset=utf-8')
            if parts[0] == 'static' and method == 'GET':
                target = (STATIC / '/'.join(parts[1:])).resolve()
                return self._file(target) if STATIC in target.parents else self._json({'error': 'no'}, 404)
            if parts[0] == 'fonts' and method == 'GET' and len(parts) == 2:
                return self._file(FONTS / Path(parts[1]).name)
            if parts[0] == 'doodle' and method == 'GET' and len(parts) >= 2:
                did = Path(parts[-1]).stem
                proj = projects_root() / q['project'] if q.get('project') else None
                if did.startswith(OWN) and q.get('project'):
                    proj = _project(q['project'])
                path = resolve(did, proj)
                if did.startswith(OWN):
                    return self._file(path) if path else self._json({'error': 'no doodle'}, 404)
                return self._file(path, 'image/svg+xml') if path else self._json({'error': 'no doodle'}, 404)
            if parts[0] == 'files' and method == 'GET' and len(parts) >= 3:
                root = _project(parts[1])
                target = (root / '/'.join(parts[2:])).resolve()
                return self._file(target) if root in target.parents else self._json({'error': 'no'}, 404)
            if parts[0] != 'api':
                return self._json({'error': 'not found'}, 404)
            return self._api(method, parts[1:], q)
        except FileNotFoundError as error:
            self._json({'error': f'not found: {error}'}, 404)
        except ValueError as error:
            self._json({'error': str(error)}, 400)
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            self._json({'error': f'{type(error).__name__}: {error}'}, 500)

    def _api(self, method, p, q):
        if p == ['state'] and method == 'GET':
            return self._json(state())
        if len(p) == 4 and p[0] == 'voices' and p[3] == 'sample' and method == 'GET':
            settings = _voice_settings(p[1], p[2], q.get('speed', 1.0))
            return self._file(voice.preview(settings['voice'], p[1], settings['speed']), 'audio/wav')
        if p == ['projects'] and method == 'GET':
            items = [_summary(d) for d in projects_root().iterdir() if (d / 'project.json').exists()]
            return self._json(sorted(items, key=lambda x: -x['modified']))
        if p == ['projects'] and method == 'POST':
            return self._json(create_project(self._body()))
        if len(p) >= 2 and p[0] == 'projects':
            name = p[1]
            if len(p) == 2 and method == 'GET':
                path = _project(name)
                return self._json({**_summary(path), 'storyboard': pipeline.storyboard(path),
                                   'settings': pipeline.settings(path),
                                   'qa': json.loads((path / 'build/qa.json').read_text(encoding='utf-8')) if (path / 'build/qa.json').exists() else None})
            if p[2:] == ['storyboard'] and method == 'PUT':
                return self._json(save_storyboard(name, self._body()))
            if p[2:] == ['reorder'] and method == 'POST':
                try:
                    body = self._body()
                    board = body['storyboard'] if 'storyboard' in body else pipeline.storyboard(_project(name))
                    board = move_picture(board, body.get('beat'), body.get('visual'), body.get('to'), body.get('item'))
                    result = save_storyboard(name, board)
                except ValueError as error:
                    return self._json({'ok': False, 'errors': [str(error)]}, 400)
                if result['ok']:
                    result['storyboard'] = board
                return self._json(result, 200 if result['ok'] else 400)
            if p[2:] == ['voice'] and method in ('GET', 'PUT'):
                return self._json(voice_settings(name, self._body() if method == 'PUT' else None))
            if p[2:] == ['direct'] and method == 'POST':
                return self._json(redirect(name, self._body()))
            if p[2:] == ['format'] and method == 'POST':
                return self._json(set_format(name, self._body()))
            if p[2:] == ['make'] and method == 'POST':
                return self._json(make_video(name))
            if p[2:] == ['narrator']:
                return self._json(set_narrator(name, self._body()) if method == 'POST' else narrator(name))
            if p[2:] == ['recording'] and method == 'POST':      # the file itself is the body (it can be large)
                return self._json(save_take(name, q.get('filename') or 'recording', self.rfile,
                                            int(self.headers.get('Content-Length') or 0)))
            if p[2:] == ['pictures']:
                if method == 'GET':
                    return self._json(list_pictures(name))
                if method == 'POST':
                    return self._json(save_picture(name, q.get('filename') or 'picture', self.rfile,
                                                   int(self.headers.get('Content-Length') or 0)))
            if p[2:] == ['align'] and method == 'POST':
                return self._json(use_take(name))
            if p[2:] == ['still'] and method == 'GET':
                return self._send(200, still(name, q.get('beat'), float(q.get('offset', 0)), float(q.get('t', 0))), 'image/jpeg')
            if p[2:] == ['reveal'] and method == 'POST':
                return self._json(_reveal(_project(name)))
        if p[:1] == ['jobs'] and len(p) == 2 and method == 'GET':
            job = JOBS.get(p[1])
            return self._json(job) if job else self._json({'error': 'no such job'}, 404)
        if p == ['upload'] and method == 'POST':
            import base64
            b = self._body()
            return self._json({'text': docx_script(str(b.get('name') or ''), base64.b64decode(b.get('data') or ''))})
        if p == ['doodles'] and method == 'GET':
            return self._json(search_doodles(q.get('q', ''), q.get('lang', 'en')))
        if p == ['cloud', 'me'] and method == 'GET':        # read the sign-in token only when KinoDraw Cloud is chosen
            from ..director.llm import cloud
            return self._json(cloud.me())
        if p == ['cloud', 'signup'] and method == 'POST':
            from ..director.llm import cloud
            return self._json(cloud.signup(self._body()['email']))
        if p == ['cloud', 'verify'] and method == 'POST':
            from ..director.llm import cloud
            b = self._body()
            return self._json(cloud.verify(b['email'], b['code']))
        if p == ['keys'] and method == 'POST':
            from ..director.llm.providers import save_key
            b = self._body()
            if b.get('provider') not in ('openai', 'anthropic', 'compat', 'command') or not b.get('key'):
                raise ValueError('provider and key are required')
            save_key(b['provider'], b['key'].strip())
            return self._json({'ok': True})
        if p == ['settings'] and method == 'POST':
            b = self._body()
            cfg = _config()
            if b.get('projects'):
                Path(b['projects']).expanduser().mkdir(parents=True, exist_ok=True)
                cfg['projects'] = str(Path(b['projects']).expanduser())
            if 'advanced' in b:
                cfg['advanced'] = bool(b['advanced'])
            if 'credit' in b:
                cfg['credit'] = bool(b['credit'])
            _save_config(cfg)
            return self._json({'ok': True, 'projects_root': str(projects_root())})
        return self._json({'error': 'not found'}, 404)


def _reveal(path: Path) -> dict:
    import subprocess
    import sys
    opener = {'darwin': ['open'], 'win32': ['explorer']}.get(sys.platform, ['xdg-open'])
    subprocess.Popen(opener + [str(path)])
    return {'ok': True}


def serve(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    Handler.token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    Handler.port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{Handler.port}/'

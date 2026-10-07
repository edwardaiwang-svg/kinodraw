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
import socketserver
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

from .. import PRODUCT, VERSION, director, paths, pipeline, styles, voice, voice_server
from ..project_store import ProjectStore, RevisionConflict, atomic_save_json
from ..progress import CancellationToken, Cancelled, RenderContext, wait_process
from . import integration
from ..director import style
from ..director.validate import validate
from ..library import OWN, PICTURES, PICTURE_MAX, PICTURE_TYPES, missing_pictures, own_path, resolve
from ..package import sha

STATIC = Path(__file__).resolve().parent / 'static'
SVG_POLICY = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; sandbox"
FONTS = Path(__file__).resolve().parents[1] / 'assets' / 'fonts'
CONFIG = paths.config_dir() / 'studio.json'
SIGN_IN = 'Sign in to KinoDraw Cloud first (free: 5 AI videos a month), or choose Offline.'   # when the cloud says no more


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
    atomic_save_json(CONFIG, cfg)


# ------------------------------------------------------------------ jobs
class JobCancelled(ValueError):
    pass


class JobContext:
    """Callable progress seam; subprocess exporters may use run_process/check_cancelled."""
    def __init__(self, job):
        self.job = job
        self.cancelled = threading.Event()
        self.token = CancellationToken()
        self.render_context = RenderContext(self.token, self._render_progress)

    def _render_progress(self, update):
        self.job.update(done=update.frames, total=update.total, frames=update.frames, frames_total=update.total,
                        elapsed=update.elapsed, eta=update.eta)

    def cancel(self):
        self.cancelled.set()
        self.token.cancel()

    def check_cancelled(self):
        self.token.check()
        if self.cancelled.is_set():
            raise JobCancelled('Cancelled. You can retry.')

    def __call__(self, stage, done, total):
        self.check_cancelled()
        self.job.update(stage=stage, done=done, total=total)

    def run_process(self, args, **kwargs):
        import subprocess
        self.check_cancelled()
        # The caller owns output files and engine logic. Avoid pipe deadlocks here.
        if kwargs.get('stdout') == subprocess.PIPE or kwargs.get('stderr') == subprocess.PIPE:
            raise ValueError('Use output files rather than PIPE with job subprocesses')
        kwargs['start_new_session'] = True
        process = self.token.register(subprocess.Popen(args, **kwargs), group=True)
        try:
            try:
                wait_process(process, self.render_context)
            except RuntimeError:
                self.token.check()
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, args) from None
                raise
            return process.returncode
        finally:
            self.token.stop(process)
            self.token.unregister(process)



# Main integration registers only exported, implemented seams. Nothing fakes success.
STUDIO_HOOKS = integration.hooks()  # provider(body), writer(body), starters(), starter(name), export(path, body, context), projectzip(path, body, context)


class Jobs:
    """One heavy job at a time (voice/render are CPU-bound); others wait in order."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.contexts = {}

    def start(self, kind: str, project: str, fn) -> str:
        jid = uuid.uuid4().hex[:10]
        job = {'id': jid, 'kind': kind, 'project': project, 'state': 'queued', 'stage': '', 'done': 0, 'total': 0,
               'error': None, 'result': None, 'started': time.time()}
        with self.lock:
            self.jobs[jid] = job

        progress = JobContext(job)
        self.contexts[jid] = progress

        def run():
            with self.run_lock:
                try:
                    progress.check_cancelled()
                    job['state'] = 'running'
                    job['result'] = fn(progress)
                    if not getattr(progress.render_context, 'published', False):
                        progress.check_cancelled()
                    if 'frames' in job:
                        job.update(done=job['frames'], total=job['frames_total'])
                    job['state'] = 'done'
                except (JobCancelled, Cancelled) as error:
                    job.update(state='cancelled', error=str(error))
                except Exception as error:  # noqa: BLE001 - shown to the user
                    job.update(state='failed', error=_plain(error))
                    traceback.print_exc()
        threading.Thread(target=run, daemon=True).start()
        return jid

    def cancel(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            if job is None:
                raise FileNotFoundError(jid)
            if job['state'] not in ('done', 'failed', 'cancelled'):
                job['state'] = 'cancelling'
                self.contexts[jid].cancel()
            return dict(job)

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
    if path.is_symlink() or path.resolve().parent != projects_root().resolve():
        raise ValueError('Project must be inside the owned projects folder')
    if (path / '.studio/pending.json').exists():
        _store(path).load()
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
        saved = _store(path).load()
        board, cfg = saved['storyboard'], saved['settings']
        videos = sorted(p.name for p in path.glob('*.mp4') if not p.name.endswith('.partial.mp4'))
        return {'name': path.name, 'title': board['title'][board['lang']], 'lang': board['lang'],
                'beats': len(board['beats']), 'director': cfg.get('director', 'rules'), 'videos': videos,
                'thumbnail': next((p.name for p in path.glob('*-thumbnail.png')), None),
                'trashed': bool(cfg.get('studio_trashed')), 'modified': path.stat().st_mtime}
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


def _server_voice_name(name) -> str:
    if not isinstance(name, str) or len(name) > 80:
        raise ValueError('The server voice name should be text, up to 80 characters.')
    return name.strip()


def voice_settings(name: str, body: dict | None = None) -> dict:
    """Read or save the project's voice, speed and pronunciations."""
    path = _project(name)
    saved = _store(path).load()
    cfg = saved['settings']
    pronounce = path / pipeline.PRONOUNCE
    if body is not None:
        settings = _voice_settings(cfg['lang'], body.get('voice'), body.get('speed'))
        if _config().get('voice_server', {}).get('on') and 'server_voice' in body:
            settings['server_voice'] = _server_voice_name(body['server_voice'])
        text = body.get('pronounce', '')
        if not isinstance(text, str):
            raise ValueError('Pronunciations should be text: word = how to say it.')
        voice.parse_lexicon(text)
        _store(path).save(saved['storyboard'], {**cfg, **settings}, body.get('revision', saved['revision']))
        if text.strip():
            pronounce.write_text(text, encoding='utf-8')
        else:
            pronounce.unlink(missing_ok=True)
        cfg.update(settings)
    return {'lang': cfg['lang'], 'voice': cfg['voice'], 'speed': cfg['speed'],
            **({'server_voice': cfg['server_voice']} if 'server_voice' in cfg else {}),   # only with a server voice
            'pronounce': pronounce.read_text(encoding='utf-8') if pronounce.exists() else ''}


def _server_config(body: dict, on: bool = True) -> dict:
    url = body.get('url') or ''
    model = body.get('model') or ''
    name = body.get('voice') or ''
    if not all(isinstance(value, str) for value in (url, model, name)):
        raise voice_server.VoiceServerError('The voice server address, model and voice name should be text.')
    url, model, name = url.strip(), model.strip(), name.strip()
    if url:
        url = voice_server.check_url(url)
    if on:
        server = voice_server.Server(url, model, name)
        url, model, name = server.url, server.model, server.voice
    return {'url': url, 'model': model, 'voice': name}


def save_voice_server(body: dict) -> dict:
    on = bool(body.get('on'))
    spec = _server_config(body, on)
    key = _server_key(body)
    if key:
        if not spec['url']:
            raise voice_server.VoiceServerError('Enter the voice server address with its API key: '
                                                'the key is kept for that address and sent only there.')
        voice_server.save_key(spec['url'], key)
    cfg = _config()
    cfg['voice_server'] = {'on': on, **spec}
    _save_config(cfg)
    return state()['voice_server']


def _server_key(body: dict) -> str | None:
    key = body.get('key') or ''
    if not isinstance(key, str):
        raise voice_server.VoiceServerError('The voice server API key should be text.')
    return key.strip() or None


def test_voice_server(body: dict) -> dict:
    spec = _server_config(body)
    key = _server_key(body) or voice_server.api_key(spec['url'], env_without_base=False)   # this address's key only
    cache = paths.cache_dir() / 'voice-server-tests'
    cache.mkdir(parents=True, exist_ok=True)
    # A Test always contacts the server so changed credentials and connectivity are checked too.
    with tempfile.TemporaryDirectory(dir=cache) as tmp:
        clip = voice_server.synthesize('Hi! I can read your script aloud, just like this.', 'en', Path(tmp),
                                       voice_server.Server(**spec, key=key))
        (cache / 'last.wav').write_bytes(clip.wav.read_bytes())
    return {'ok': True, 'seconds': clip.duration,
            'message': f'It works: {clip.duration:.1f} seconds of speech from your voice server.'}


def voice_server_voices(body: dict) -> dict:
    """The voices the server in the Settings fields offers (nothing is saved); its key only if saved for that very
    address, or typed in Settings now."""
    spec = _server_config(body)
    key = _server_key(body) or voice_server.api_key(spec['url'], env_without_base=False)
    return voice_server.list_voices(voice_server.Server(**spec, key=key))


def apply_video_settings(path: Path) -> voice_server.Server | None:
    """Apply this computer's Studio choices to the project's next video: the credit, and the voice server (the
    Settings address and model, with the project's own server voice name if it has one). Returns that server, or None
    for the built-in voice; a project's own settings never choose the address."""
    saved = _store(path).load()
    cfg, studio = saved['settings'], _config()
    cfg['credit'] = project_credit(path, cfg)   # the project's own end-card box (project_credit)
    spec, server = studio.get('voice_server', {}), None
    if spec.get('on'):
        server = voice_server.Server(**_server_config({**spec, 'voice': cfg.get('server_voice') or spec.get('voice', '')}))
        cfg['voice_server'] = voice_server.record(server)
    else:
        cfg.pop('voice_server', None)
    _store(path).save(saved['storyboard'], cfg, saved['revision'])
    return server


def create_project(body: dict, provider=None) -> dict:
    text = (body.get('text') or '').strip()
    if not text:
        raise ValueError('paste a script or choose a file')
    title = (body.get('title') or '').strip() or None
    from .. import ingest
    doc = ingest.read(text, title=title)
    name = _slug(doc.title)
    path = projects_root() / name
    mode = body.get('director') or ('cloud' if (body.get('lang') or doc.lang) in ('en', 'zh') else 'rules')
    lang = body.get('lang') or doc.lang
    if mode == 'cloud' and lang not in ('en', 'zh'):
        mode = 'rules'
    settings = {k: body[k] for k in ('workers', 'model', 'base_url', 'command') if body.get(k)}
    settings.update(_voice_settings(lang, body.get('voice') or voice.LANGS[lang]['voice'], body.get('speed', 1.0)))
    auto = body.get('look') == style.AUTO                                    # "Choose for me": the director picks
    settings['aspect'] = pipeline.validate_aspect(body.get('aspect', '16:9'), None if auto else body.get('look'))
    settings['director_v3'] = body.get('director_v3', True) is not False
    settings.update(credit=True, credit_chosen=True)                         # the end card starts on, whatever 0.2.0 said
    if _config().get('voice_server', {}).get('on') and body.get('server_voice'):
        if chosen := _server_voice_name(body['server_voice']):               # blank = the Settings voice
            settings['server_voice'] = chosen
    direction = {**{k: body.get(k) for k in ('look', 'story', 'motion')},
                 'brand': {k: v for k, v in (body.get('brand') or {}).items() if v} or None}

    def job(progress):
        progress('storyboard', 0, 1)
        pick = None
        if auto and settings['director_v3']:
            direction.update(look='whiteboard', story='story', motion=None)
        if auto and not settings['director_v3']:       # once, before the storyboard; saved, so a re-plan never re-picks
            progress('style', 0, 1)
            pick = integration.choose_style(doc, {**body, 'director': mode, 'lang': lang}, lang,
                                            settings['aspect'], direction['brand'], provider)
            look, story = pick['style'].split('/')
            direction.update(look=look, story=story, motion=None,
                             brand=direction['brand'] if story == 'promo' else None)
            settings['style_pick'] = pick
        # Pipeline may write intermediate JSON; keep that work out of the live project.
        store = _store(path)
        store.meta.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='create-', dir=store.meta) as folder:
            scratch = Path(folder)
            pipeline.new_project(text, scratch, title=title, lang=body.get('lang') or None, direction=direction,
                                 director=mode, **settings)
            if settings['director_v3']:
                chosen = provider if provider is not None else STUDIO_HOOKS.get('provider', lambda b: mode)({**body, 'director': mode, 'lang': lang})
                report = pipeline.direct_v3(scratch, provider=chosen)
            else:
                chosen = provider if provider is not None else STUDIO_HOOKS.get('provider', lambda b: None)({**body, 'director': mode, 'lang': lang})
                report = director.direct(scratch, mode, body.get('model') or None, body.get('base_url') or None, progress, provider=chosen)
            progress.check_cancelled()
            planned = ProjectStore(scratch).load()
            integration.validate_references(planned['storyboard'], planned['settings'], scratch)
            integration.transfer_assets(scratch, path)
            integration.validate_references(planned['storyboard'], planned['settings'], path)
            with progress.token._lock:
                progress.check_cancelled()
                store.initialize(planned['storyboard'], planned['settings'])
                progress.render_context.published = True
        usage = report.get('usage')
        return {'project': name, 'notes': report.get('notes', [])[:20], 'style': pick,
                'cost': None if not usage else (usage.get('cost_usd', 0) if isinstance(usage, dict) else usage.cost_usd), 'calls': 0 if not usage else (usage.get('calls', 0) if isinstance(usage, dict) else usage.calls)}
    return {'job': JOBS.start('create', name, job), 'project': name}


def project_credit(path: Path, cfg: dict | None = None) -> bool:
    if cfg is None:
        cfg = pipeline.settings(path)
    # The box's choice; a project that never chose (0.2.0 wrote 'credit' on every make) follows the old
    # Studio-wide Settings switch, as 0.2.0 did.
    if cfg.get('credit_chosen'):
        return cfg.get('credit', True)
    return _config().get('credit', True)


def set_credit(name: str, body: dict) -> dict:
    if not isinstance(body.get('credit'), bool):
        raise ValueError('credit must be true or false')
    path = _project(name)
    saved = _store(path).load()
    cfg = saved['settings']
    cfg.update(credit=body['credit'], credit_chosen=True)
    _store(path).save(saved['storyboard'], cfg, body.get('revision', saved['revision']))
    return cfg


def set_format(name: str, body: dict) -> dict:
    path = _project(name)
    saved = _store(path).load()
    cfg = saved['settings']
    cfg['aspect'] = pipeline.validate_aspect(body.get('aspect'), pipeline.storyboard(path).get('look'))
    _store(path).save(saved['storyboard'], cfg, body.get('revision', saved['revision']))
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


def make_video(name: str, body=None) -> dict:
    path = _project(name)

    def job(progress):
        if 'make' in STUDIO_HOOKS:
            return STUDIO_HOOKS['make'](path, body or {}, progress)
        server = apply_video_settings(path)
        if server:
            server.key = voice_server.api_key(server.url, env_without_base=False)
        clips = pipeline.narrate(path, progress, server=server)
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
            'server_voice': cfg.get('server_voice', ''),
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
    for path in sorted(folder.glob('*'), key=lambda p: p.name):   # by name: Windows paths sort ignoring case
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
    expected = body.get('revision')
    mode = body.get('director') or 'rules'
    def job(progress):
        store = _store(path)
        state = store.load()
        store.snapshot('Before replan', expected)
        cfg = director.provider_settings(state['settings'], mode,
            **{k: body[k] for k in ('model', 'base_url', 'command') if k in body})
        request = {**director.provider_settings(cfg, mode), **body, 'director': mode, 'lang': cfg['lang']}
        # Plan in an owned scratch folder; only a complete validated result is committed.
        with tempfile.TemporaryDirectory(prefix='replan-', dir=store.meta) as folder:
            scratch = Path(folder)
            integration.transfer_assets(path, scratch)
            atomic_save_json(scratch / 'storyboard.json', state['storyboard'])
            if cfg.get('director_v3'):
                for key in ('plan_v3', 'plan_v3_report', 'scene_treatments'):
                    cfg.pop(key, None)
                atomic_save_json(scratch / 'project.json', cfg)
                report = pipeline.direct_v3(scratch, provider=STUDIO_HOOKS.get('provider', lambda b: mode)(request))
            else:
                atomic_save_json(scratch / 'project.json', cfg)
                report = director.direct(scratch, mode, body.get('model') or None, body.get('base_url') or None, progress, provider=STUDIO_HOOKS.get('provider', lambda b: None)(request))
            progress.check_cancelled()
            planned = ProjectStore(scratch).load()
            integration.validate_references(planned['storyboard'], planned['settings'], scratch)
            with store.locked():
                store._check(store._state(), state['revision'])
                integration.transfer_assets(scratch, path)
                integration.validate_references(planned['storyboard'], planned['settings'], path)
            # save takes its own OS lock; never nest ProjectStore locks. A source
            # edit between transfer and save is still rejected by the revision.
            with progress.token._lock:
                progress.check_cancelled()
                store.save(planned['storyboard'], planned['settings'], state['revision'], 'Before replan commit')
                progress.render_context.published = True
        return {'notes': report.get('notes', [])[:20], 'report': report}
    # Reject stale callers synchronously (409), also check again when queued work begins.
    state = _store(path).load()
    if expected is not None and expected != state['revision']:
        raise RevisionConflict(state['revision'])
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
        from ..engine.scenes import SLOT_BUILDERS
        if any(v.get('type') not in SLOT_BUILDERS for v in visuals[min(visual, to):max(visual, to) + 1]):
            # A page has its own timed parts and camera stop; moving it can leave the next picture undrawn.
            raise ValueError('A page (flow, chart, timeline…) keeps its place. Only doodles, notes, numbers and '
                             'quotes can be drawn earlier or later.')

        def doodles(v):
            return v.get('items', []) if v.get('type') == 'cluster' else []
        step = 1 if to > visual else -1
        for at in range(visual, to, step):          # one place at a time, like the arrows: no doodle loses its words
            timing = [(v.get('trigger'), [it.get('trigger') for it in doodles(v)]) for v in visuals]
            visuals.insert(at + step, visuals.pop(at))
            for v, (trigger, item_triggers) in zip(visuals, timing):
                set_trigger(v, trigger)
                # Doodles beyond the ones this place had keep their own words, so moving back restores them.
                for it, item_trigger in zip(doodles(v), item_triggers):
                    set_trigger(it, item_trigger)
    return moved


def _store(path):
    return ProjectStore(path, lambda board: validate(board, path))


def save_storyboard(name: str, board: dict, revision=None, plan=None) -> dict:
    path = _project(name)
    report = validate(board, path)
    if not report['ok']:
        return {'ok': False, 'errors': report['errors'][:20]}
    store = _store(path)
    cfg = None
    if plan is not None:
        from ..director.v3.validate import validate as validate_plan
        from ..director.v3.adapter import adapt
        with store.locked():
            state = store._state()
            store._check(state, revision)
            cfg = state['settings']
            checked = plan
            if plan != cfg.get('plan_v3'):
                from ..director.validate import _doodles
                candidates = {beat['id']: list(_doodles(beat.get('visuals', []))) for beat in board['beats']}
                for scene in (cfg.get('plan_v3') or {}).get('scenes', []):
                    refs = [e['ref'] for e in scene['elements'] if e['kind'] == 'picture']
                    for bid in scene['beat_ids']:
                        candidates.setdefault(bid, []).extend(refs)
                checked, repairs = validate_plan(plan, board, candidates)
                if repairs:
                    raise ValueError('Invalid plan: ' + '; '.join(repairs[:10]))
            # Re-adapt only changed plans; ordinary board edits must retain manual visuals.
            if checked != cfg.get('plan_v3'):
                original_visuals = {b['id']: deepcopy(b.get('visuals', [])) for b in board['beats']}
                board, treatments = adapt(checked, board)
                for beat in board['beats']:
                    if original_visuals.get(beat['id']):
                        beat['visuals'] = original_visuals[beat['id']]
                cfg.update(plan_v3=checked, scene_treatments=treatments, director_v3=True, series_bible={'cast': deepcopy(checked['cast'])})
            # save outside this lock, with the same revision check protecting the gap.
    saved = store.save(board, cfg, revision)
    return {'ok': True, 'warnings': report['warnings'], 'revision': saved['revision'],
            'storyboard': saved['storyboard'], 'settings': saved['settings']}


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


# ------------------------------------------------------------------ feedback
FEEDBACK_USES = ('school', 'work', 'personal', 'other')
EMAIL = re.compile(r'[^\s@:]{1,64}@[^\s@]{1,253}\.[^\s@]{2,24}')          # KinoDraw Cloud's own check
NOT_SENT = 'Your feedback wasn’t sent.'


def _computer() -> str:
    import sys
    return {'darwin': 'mac', 'win32': 'windows'}.get(sys.platform, 'linux' if sys.platform.startswith('linux')
                                                     else sys.platform[:20])


def feedback_body(body: dict) -> dict:
    """The feedback form as KinoDraw Cloud takes it (POST /v1/feedback), checked here so a mistake is said at once.
    The email goes only when "I am 13 or older" is ticked; the app adds its version, the computer type, the language
    and the install ID."""
    text = body.get('text')
    text = text.strip() if isinstance(text, str) else ''
    if not text:
        raise ValueError('Write what you’d like to tell us first.')
    if len(text) > 2000:
        raise ValueError('Please keep it under 2,000 characters.')
    out = {'text': text}
    rating = body.get('rating')
    if rating is not None:
        if type(rating) is not int or not 1 <= rating <= 5:
            raise ValueError('Choose how well it worked from 1 to 5.')
        out['rating'] = rating
    if body.get('use'):
        if body['use'] not in FEEDBACK_USES:
            raise ValueError('Choose what the video was for from the list.')
        out['use'] = body['use']
    url = body.get('video_url')
    url = url.strip() if isinstance(url, str) else ''
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or len(url) > 300 or re.search(r'\s', url):
            raise ValueError('The video link should start with http:// or https:// (up to 300 characters).')
        out['video_url'] = url
    for box in ('quote_ok', 'age_13_plus'):
        if not isinstance(body.get(box), bool):
            raise ValueError('Tick or untick the boxes, then press Send again.')
        out[box] = body[box]
    email = body.get('email')
    email = email.strip() if isinstance(email, str) else ''
    if email and out['age_13_plus']:                    # under 13 (or not ticked): never sent, even if typed
        if len(email) > 200 or not EMAIL.fullmatch(email):
            raise ValueError('That email address doesn’t look right. Check it, or leave it empty.')
        out['email'] = email
    from ..director.llm import cloud
    lang = body.get('lang')                             # the project's language, when sent from a project
    out.update(install_id=cloud.install_id(), app_version=VERSION, os=_computer(),
               lang=lang if lang in voice.LANGS else 'en')     # else the Studio's own language
    return out


class FeedbackNotSent(Exception):
    """KinoDraw Cloud did not take the feedback (offline, busy or refused); the message is the sentence to show."""


def send_feedback(body: dict) -> dict:
    """Send the feedback form to KinoDraw Cloud: the user pressed Send, so it goes whichever director is chosen, with
    no sign-in and no cloud token. Remembers that feedback was sent once, so the card after a video stays quiet."""
    from http.client import HTTPException
    from ..director.llm import cloud
    from ..director.llm.providers import ProviderError
    sent = feedback_body(body)
    try:
        cloud.feedback(sent)
    except (OSError, ValueError, HTTPException) as error:    # no answer, a hang-up or a Wi-Fi sign-in page, not JSON
        raise FeedbackNotSent(f'{NOT_SENT} KinoDraw Cloud can’t be reached. Check your internet connection and '
                              'press Send again.') from error
    except ProviderError as error:
        status, detail = getattr(error, 'status', None), getattr(error, 'detail', '')
        if status == 404:                               # a KinoDraw Cloud from before feedback
            raise FeedbackNotSent(f'{NOT_SENT} KinoDraw Cloud can’t take feedback yet. Please use "Prefer GitHub? '
                                  'Open an issue" below.') from error
        if status and status < 500 and detail:          # the cloud's own sentence (a bad field, too many at once)
            raise FeedbackNotSent(f'{NOT_SENT} {detail}') from error
        if status:
            raise FeedbackNotSent(f'{NOT_SENT} KinoDraw Cloud had a problem. Please press Send again in a few '
                                  'minutes.') from error
        raise FeedbackNotSent(f'{NOT_SENT} KinoDraw Cloud can’t be reached. Check your internet connection and '
                              'press Send again.') from error
    cfg = _config()
    if not cfg.get('feedback_sent'):
        cfg['feedback_sent'] = True
        _save_config(cfg)
    return {'ok': True}


def state() -> dict:
    from ..director.llm import cloud
    from ..director.llm.providers import SUGGESTED, saved
    names = saved()                    # names only: opening the app never reads the keychain (no macOS prompt)
    server = {'on': False, 'url': '', 'model': '', 'voice': '',
              **{k: v for k, v in _config().get('voice_server', {}).items() if k in ('on', 'url', 'model', 'voice')}}
    try:                                              # a key is saved for one address: is there one for this one?
        server['key_saved'] = bool(server['url']) and voice_server.key_name(server['url']) in names
    except voice_server.VoiceServerError:
        server['key_saved'] = False
    signed_in = bool(cloud.URL) and ('cloud-token' in names or bool(paths.getenv('KINODRAW_CLOUD_TOKEN')))
    return {'projects_root': str(projects_root()), 'cloud_available': bool(cloud.URL), 'cloud_signed_in': signed_in,
            'default_director': 'cloud' if cloud.URL else 'rules',   # signed out, a first video needs no account
            'hooks': {k: k in STUDIO_HOOKS for k in ('writer', 'starters', 'export', 'projectzip')},
            'starters': STUDIO_HOOKS['starters']() if 'starters' in STUDIO_HOOKS else [],   # New video's examples
            'cloud': None, 'install_id': cloud.kept_install_id(),     # shown in Settings, to ask for its data to be deleted
            'cloud_languages': list(cloud.CloudProvider.languages),   # others are planned offline, never asked
            'keys': {p: p in names for p in ('openai', 'anthropic', 'compat', 'command')},
            'advanced': bool(_config().get('advanced')),
            'feedback_sent': bool(_config().get('feedback_sent')),   # after that, a finished video offers it quietly
            'voice_server': server,
            'product': PRODUCT['name'],
            'models': SUGGESTED,
            'formats': [{'value': '16:9', 'label': 'Landscape 16:9 (YouTube)'},
                        {'value': '9:16', 'label': 'Vertical 9:16 (Shorts, TikTok, Reels)'},
                        {'value': '1:1', 'label': 'Square 1:1'}],
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
                download = integration.DOWNLOADS.get((parts[1], '/'.join(parts[2:])))
                if download is not None:
                    return self._file(download)
                target = (root / '/'.join(parts[2:])).resolve()
                return self._file(target) if root in target.parents else self._json({'error': 'no'}, 404)
            if parts[0] != 'api':
                return self._json({'error': 'not found'}, 404)
            return self._api(method, parts[1:], q)
        except RevisionConflict as error:
            self._json({'error': str(error), 'code': 'revision_conflict', 'revision': error.revision}, 409)
        except FileNotFoundError as error:
            self._json({'error': f'not found: {error}'}, 404)
        except ValueError as error:
            self._json({'error': str(error)}, 400)
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            self._json({'error': f'{type(error).__name__}: {error}'}, 500)

    def _api(self, method, p, q):
        if p == ['writer'] and method == 'POST':
            if 'writer' not in STUDIO_HOOKS:
                return self._json({'error': 'Topic writer is unavailable until the writer module is integrated.'}, 503)
            return self._json(STUDIO_HOOKS['writer'](self._body()))
        if p == ['starters'] and method == 'GET':
            if 'starters' not in STUDIO_HOOKS:
                return self._json({'error': 'Starter projects are not integrated.'}, 503)
            try:
                return self._json(STUDIO_HOOKS['starters']())
            except ModuleNotFoundError as error:
                if error.name != 'kinodraw.starters':
                    raise
                return self._json({'error': 'Starter projects await the sibling starters module.'}, 503)
        if len(p) == 2 and p[0] == 'starters' and method == 'GET':
            if 'starter' not in STUDIO_HOOKS:
                return self._json({'error': 'Starter projects are not integrated.'}, 503)
            return self._json(STUDIO_HOOKS['starter'](p[1]))
        if p == ['state'] and method == 'GET':
            return self._json(state())
        if p == ['voice-server'] and method == 'POST':
            return self._json(save_voice_server(self._body()))
        if p == ['voice-server', 'test'] and method == 'POST':
            return self._json(test_voice_server(self._body()))
        if p == ['voice-server', 'voices'] and method == 'POST':
            return self._json(voice_server_voices(self._body()))
        if p == ['voice-server', 'test.wav'] and method == 'GET':
            return self._file(paths.cache_dir() / 'voice-server-tests' / 'last.wav', 'audio/wav')
        if len(p) == 4 and p[0] == 'voices' and p[3] == 'sample' and method == 'GET':
            settings = _voice_settings(p[1], p[2], q.get('speed', 1.0))
            return self._file(voice.preview(settings['voice'], p[1], settings['speed']), 'audio/wav')
        if p == ['projects'] and method == 'GET':
            items = [_summary(d) for d in projects_root().iterdir() if d.is_dir() and not d.is_symlink() and not d.name.startswith('.') and ((d / 'project.json').exists() or (d / '.studio/pending.json').exists())]
            return self._json(sorted([x for x in items if bool(x.get('trashed')) == (q.get('trash') == '1')], key=lambda x: -x['modified']))
        if p == ['projects'] and method == 'POST':
            return self._json(create_project(self._body()))
        if p == ['projects', 'import'] and method == 'POST':
            return self._json(integration.importzip(self.rfile, self.headers.get('Content-Length')))
        if len(p) >= 2 and p[0] == 'projects':
            name = p[1]
            if len(p) == 2 and method == 'GET':
                path = _project(name)
                saved = _store(path).load()
                return self._json({**_summary(path), **saved, 'credit': project_credit(path),
                                   'qa': json.loads((path / 'build/qa.json').read_text(encoding='utf-8')) if (path / 'build/qa.json').exists() else None})
            if p[2:] == ['storyboard'] and method == 'PUT':
                body = self._body()
                if not body.get('revision') or 'storyboard' not in body:
                    return self._json({'error': 'Load the project revision before saving.'}, 428)
                result = save_storyboard(name, body['storyboard'], body['revision'], body.get('plan_v3'))
                return self._json(result, 200 if result['ok'] else 400)
            if p[2:] == ['reorder'] and method == 'POST':
                try:
                    body = self._body()
                    board = body['storyboard'] if 'storyboard' in body else pipeline.storyboard(_project(name))
                    board = move_picture(board, body.get('beat'), body.get('visual'), body.get('to'), body.get('item'))
                    if not body.get('revision'):
                        return self._json({'error': 'Load the project revision before saving.'}, 428)
                    result = save_storyboard(name, board, body['revision'])
                except RevisionConflict:
                    raise
                except ValueError as error:
                    return self._json({'ok': False, 'errors': [str(error)]}, 400)
                if result['ok']:
                    result['storyboard'] = board
                return self._json(result, 200 if result['ok'] else 400)
            if p[2:] in (['rename'], ['duplicate'], ['trash'], ['untrash']) and method == 'POST':
                body, path = self._body(), _project(name)
                store = _store(path)
                project_state = store.load()
                if not body.get('revision'):
                    return self._json({'error': 'Revision required'}, 428)
                if body['revision'] != project_state['revision']:
                    raise RevisionConflict(project_state['revision'])
                if p[2] == 'duplicate':
                    import shutil
                    target = projects_root() / _slug(body.get('title') or name + ' copy')
                    with store.locked():
                        store._check(store._state(), body['revision'])
                        if any(x.is_symlink() for x in path.rglob('*')):
                            raise ValueError('Projects with linked files cannot be duplicated')
                        shutil.copytree(path, target, ignore=shutil.ignore_patterns('.studio', 'build'))
                    return self._json({'project': target.name})
                if p[2] == 'rename':
                    title = str(body.get('title') or '').strip()[:200]
                    if not title:
                        raise ValueError('Title required')
                    project_state['storyboard']['title'][project_state['storyboard']['lang']] = title
                    project_state['settings']['title'] = title
                else:
                    project_state['settings']['studio_trashed'] = p[2] == 'trash'
                return self._json(store.save(project_state['storyboard'], project_state['settings'], body['revision']))
            if p[2:] == ['versions']:
                store = _store(_project(name))
                if method == 'GET':
                    return self._json(store.versions())
                body = self._body()
                if not body.get('revision'):
                    return self._json({'error': 'Revision required'}, 428)
                return self._json(store.snapshot(body.get('label') or 'Saved version', body['revision']))
            if p[2:] == ['restore'] and method == 'POST':
                body = self._body()
                if not body.get('revision'):
                    return self._json({'error': 'Revision required'}, 428)
                return self._json(_store(_project(name)).restore(body.get('version'), body['revision']))
            if p[2:] in (['export'], ['projectzip']) and method == 'POST':
                kind, body, path = p[2], self._body(), _project(name)
                if kind not in STUDIO_HOOKS:
                    return self._json({'error': kind + ' is unavailable until its module is integrated.'}, 503)
                return self._json({'job': JOBS.start(kind, name, lambda context: STUDIO_HOOKS[kind](path, body, context))})
            if p[2:] == ['voice'] and method in ('GET', 'PUT'):
                return self._json(voice_settings(name, self._body() if method == 'PUT' else None))
            if p[2:] == ['direct'] and method == 'POST':
                body = self._body()
                if not body.get('revision'):
                    return self._json({'error': 'Revision required'}, 428)
                return self._json(redirect(name, body))
            if p[2:] == ['format'] and method == 'POST':
                return self._json(set_format(name, self._body()))
            if p[2:] == ['credit'] and method == 'POST':
                return self._json(set_credit(name, self._body()))
            if p[2:] == ['make'] and method == 'POST':
                return self._json(make_video(name, self._body()))
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
        if p[:1] == ['jobs'] and len(p) == 3 and p[2] == 'cancel' and method == 'POST':
            return self._json(JOBS.cancel(p[1]))
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
        if p == ['cloud', 'anonymous'] and method == 'POST':     # KinoDraw Cloud chosen with no email sign-in
            from ..director.llm import cloud
            try:
                return self._json(cloud.anonymous() | {'install_id': cloud.install_id()})   # Settings shows the ID
            except cloud.SignInNeeded as error:          # open access is off: 0.2.0's sign-in prompt, in the cloud's words
                return self._json({'error': error.sentence or SIGN_IN, 'code': 'sign_in'}, 403)
        if p == ['cloud', 'signup'] and method == 'POST':
            from ..director.llm import cloud
            try:
                return self._json(cloud.signup(self._body()['email']))
            except cloud.EmailUnavailable as error:     # the page shows this sentence and keeps Offline in view
                return self._json({'error': str(error), 'code': 'email_unavailable'}, 503)
        if p == ['cloud', 'verify'] and method == 'POST':
            from ..director.llm import cloud
            b = self._body()
            return self._json(cloud.verify(b['email'], b['code']))
        if p == ['feedback'] and method == 'POST':        # sent only when the user presses Send, whatever the director
            try:
                return self._json(send_feedback(self._body()))
            except FeedbackNotSent as error:            # the page keeps what they typed, to send again
                return self._json({'error': str(error)}, 502)
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
            _save_config(cfg)
            return self._json({'ok': True, 'projects_root': str(projects_root())})
        return self._json({'error': 'not found'}, 404)


def _reveal(path: Path) -> dict:
    import subprocess
    import sys
    opener = {'darwin': ['open'], 'win32': ['explorer']}.get(sys.platform, ['xdg-open'])
    subprocess.Popen(opener + [str(path)])
    return {'ok': True}


class _Server(ThreadingHTTPServer):
    def server_bind(self):
        """HTTPServer's own server_bind() also looks up the address's host name (socket.getfqdn), a reverse DNS
        lookup that macOS treats as local-network access: it asked "Allow KinoDraw to find devices on local
        networks?" before the window opened. Nothing reads server_name, so skip the lookup."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def serve(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    Handler.token = secrets.token_urlsafe(24)
    server = _Server(('127.0.0.1', port), Handler)
    Handler.port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{Handler.port}/'

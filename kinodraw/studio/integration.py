"""Adapters for the existing Studio HTTP contracts and production components."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

from .. import pipeline, voice_server
from ..director import PROVIDER_INPUTS, provider_for
from ..director.llm.providers import ProviderError, Usage
from ..project_store import ProjectStore, RevisionConflict

# Only artifacts registered by a completed local job can be served outside a project.
DOWNLOADS = {}
IMPORT_MAX_BYTES = 256 * 1024 * 1024


def writer(body):
    from ..writer import write_draft, draft_markdown
    notes = body.get('notes')
    if isinstance(notes, str):
        notes = [n.strip() for n in notes.splitlines() if n.strip()]
    selected = None
    try:
        from .server import STUDIO_HOOKS
        selected = STUDIO_HOOKS['provider'](body)
        if not hasattr(selected, 'write_draft'):
            raise ValueError('The selected provider does not support topic writing')
        draft, report = write_draft(body.get('topic'), notes, selected, voice=body.get('voice'))
    except ProviderError as error:
        from ..director.llm import errors
        return {'ok': False, 'error': str(error), 'error_help': errors.explain(error, getattr(selected, 'name', None)),
                'usage': asdict(getattr(error, 'usage', Usage()))}
    return {'ok': True, 'text': draft_markdown(draft), 'markdown': draft_markdown(draft),
            'draft': draft, 'report': {**report, 'usage': asdict(report['usage'])},
            'usage': asdict(report['usage'])}


def make(path, body, context):
    from . import server
    context.check_cancelled()
    saved = _state(path, body)
    aspect = body.get('aspect', saved['settings'].get('aspect', '16:9'))
    size = body.get('size', saved['settings'].get('size') if aspect == saved['settings'].get('aspect', '16:9') else None)
    pipeline.validate_size(size, aspect, saved['storyboard'].get('look'))
    if 'size' in body or 'aspect' in body:
        cfg = saved['settings']
        cfg.update(aspect=aspect, size=list(pipeline.validate_size(size, aspect, saved['storyboard'].get('look'))))
        ProjectStore(path).save(saved['storyboard'], cfg, saved['revision'])
    speech_server = server.apply_video_settings(path)
    if speech_server is not None:
        speech_server.key = body.get('voice_key') or voice_server.api_key(speech_server.url, env_without_base=False)
    qa = pipeline.produce(path, context, speech_server, context=context.render_context)
    return {'video': Path(qa['video']).name, 'ok': qa['ok'], 'problems': qa['problems'], 'length': qa['length']}


def _state(path, body):
    saved = ProjectStore(path).load()
    expected = body.get('revision')
    if expected is not None and expected != saved['revision']:
        raise RevisionConflict(saved['revision'])
    return saved


def _artifact(path, suffix):
    from .server import projects_root
    directory = projects_root() / '.downloads'
    if directory.is_symlink() or not directory.resolve().is_relative_to(projects_root().resolve()):
        raise ValueError('Download directory must stay inside the projects root')
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (uuid.uuid4().hex + suffix)


def _download(path, artifact):
    name = 'downloads/' + artifact.name
    DOWNLOADS[(path.name, name)] = artifact.resolve()
    return name


def export(path, body, context):
    path = Path(path)
    context.check_cancelled()
    saved = _state(path, body)
    fmt = str(body.get('format') or 'webm').lower().lstrip('.')
    if fmt not in ('gif', 'webm'):
        raise ValueError('Export format must be gif or webm')
    aspect = body.get('aspect', saved['settings'].get('aspect', '16:9'))
    size = body.get('size', saved['settings'].get('size') if aspect == saved['settings'].get('aspect', '16:9') else None)
    pipeline.validate_size(size, aspect, saved['storyboard'].get('look'))
    variant = 'size' in body or 'aspect' in body
    requested = body.get('source')
    if requested:
        if variant:
            raise ValueError('Native variants require the saved project, not an external video source')
        source = _regular_source(path, requested)
    else:
        qa = _regular_source(path, 'build/qa.json', required=False)
        source = _regular_source(path, Path(pipeline._load(qa)['video']).name) if qa.is_file() else None
    if not variant and (source is None or not source.is_file()):
        raise ValueError('Make a video before exporting')
    audio = _regular_source(path, 'build/mix.wav', required=False)
    if requested:
        audio = Path(str(source) + '.absent-audio-companion')
    from ..export import export_video
    context('export', 0, 1)
    with tempfile.TemporaryDirectory(prefix='native-export-') as folder:
        stage = Path(folder)
        if variant:
            if not audio.is_file():
                raise ValueError('Make the narration and audio mix before exporting a native variant')
            store = ProjectStore(path)
            with store.locked():
                store._check(store._state(), saved['revision'])
                pipeline._copy_project(path, stage / 'project')
            project = stage / 'project'
            pipeline.set_format(project, aspect=aspect, size=size)
            source = pipeline.render(project, context=context.render_context)
            audio = project / 'build/mix.wav'
        output = stage / ('video.' + fmt)
        export_video(source, output, audio=audio if variant and fmt == 'webm' else None,
                     context=context.render_context)
        outputs = [(output, _artifact(path, '.' + fmt))]
        if fmt == 'gif':
            companion = stage / ('audio.wav' if audio.is_file() else 'audio' + source.suffix)
            shutil.copy2(audio if audio.is_file() else source, companion)
            # Read the complete lossless companion (or retained original audio)
            # before either download can be registered.
            from ..engine.render import FFMPEG
            with (stage / 'audio.decode-errors').open('w+b') as errors:
                context.run_process([FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode',
                                     '-i', str(companion), '-map', '0:a:0', '-f', 'null', '-'], stderr=errors)
                errors.seek(0)
                detail = errors.read().decode('utf-8', errors='replace').strip()
                if detail:
                    raise RuntimeError(f'audio companion decode failed: {detail}')
            outputs.append((companion, _artifact(path, companion.suffix)))
        store = ProjectStore(path)
        with store.locked():
            store._check(store._state(), saved['revision'])
            with context.token._lock:
                context.check_cancelled()
                pipeline._publish_outputs(outputs, path, context.render_context)
                result = {'file': _download(path, outputs[0][1]), 'format': fmt}
                if fmt == 'gif':
                    result.update(audio_file=_download(path, outputs[1][1]),
                                  audio_note='GIF does not support audio; download the companion source.')
                context.render_context.published = True
        return result


def _regular_source(path, requested, *, required=True):
    """Check lexical links before resolving; resolution erases symlink evidence."""
    relative = Path(requested)
    source = path / relative
    if (relative.is_absolute() or '..' in relative.parts or path.is_symlink()
            or source.is_symlink() or any((path / Path(*relative.parts[:i])).is_symlink()
                                         for i in range(1, len(relative.parts)))
            or not source.resolve().is_relative_to(path.resolve())
            or (required and not source.is_file())):
        raise ValueError('Source must be a regular video in this project')
    return source


def projectzip(path, body, context):
    from ..project_zip import export_project
    store = ProjectStore(path)
    context('projectzip', 0, 1)
    output = _artifact(path, '.zip')
    with store.locked():
        store._check(store._state(), body.get('revision'))
        manifest = export_project(path, output)
    context.check_cancelled()
    context('projectzip', 1, 1)
    return {'file': _download(path, output), 'files': len(manifest['files'])}


def importzip(stream, length):
    """Receive bounded binary ZIP bytes, validate privately, then publish without replacing."""
    from .server import projects_root
    from ..project_zip import import_project
    from ..director.llm.providers import validate_structure
    from ..director.v3.schema import PLAN_SCHEMA
    from ..director.v3.validate import validate as validate_plan
    try:
        length = int(length)
    except (TypeError, ValueError):
        raise ValueError('A project ZIP upload needs a valid Content-Length') from None
    if not 0 < length <= IMPORT_MAX_BYTES:
        raise ValueError('Choose a nonempty project ZIP no larger than 256 MiB')
    root = Path(projects_root())
    if root.is_symlink():
        raise ValueError('Projects folder must not be a symbolic link')
    destination = root / ('Imported-' + uuid.uuid4().hex)
    with tempfile.TemporaryDirectory(prefix='.studio-import-', dir=root) as folder:
        archive, stage = Path(folder) / 'upload.zip', Path(folder) / 'checked'
        with archive.open('xb') as output:
            remaining = length
            while remaining:
                chunk = stream.read(min(remaining, 1024 * 1024))
                if not chunk or len(chunk) > remaining:
                    raise ValueError('Project ZIP upload was truncated or has an invalid length')
                output.write(chunk)
                remaining -= len(chunk)
        try:
            manifest = import_project(archive, stage)
            # Loading a ProjectStore replays its journal. Never replay archived transactions.
            if (stage / '.studio/pending.json').exists():
                raise ValueError('This archive contains a pending Studio transaction. Open and save the original project, then export it again.')
            store = ProjectStore(stage)
            saved = store._state()  # read only: no recovery, lock creation or semantic rewriting
            store._validate(saved)
            board, cfg = saved['storyboard'], saved['settings']
            forbidden = [key for key in PROVIDER_INPUTS if key in cfg]
            if forbidden:
                raise ValueError('Project ZIP settings cannot contain director provider inputs: ' + ', '.join(forbidden))
            for field in ('chapters', 'beats'):
                if (not isinstance(board.get(field), list) or not board[field]
                        or not all(isinstance(item, dict) for item in board[field])):
                    raise ValueError(f'Studio storyboard {field} must be a nonempty array of objects')
            if cfg.get('lang') != board.get('lang') or not isinstance(cfg.get('voice'), str):
                raise ValueError('Project language or voice settings are incompatible with Studio')
            if not isinstance(board.get('title', {}).get(board.get('lang')), str):
                raise ValueError('Project needs a title in its saved language')
            pipeline.validate_size(cfg.get('size'), cfg.get('aspect', '16:9'), board.get('look'))
            if cfg.get('plan_v3') is not None:
                plan = cfg['plan_v3']
                validate_structure(plan, PLAN_SCHEMA)
                from ..director.validate import _doodles
                from ..library import ASSETS, resolve
                # Saved scene pictures (including cached props) remain offered on edit.
                candidates = {beat['id']: list(_doodles(beat.get('visuals', []))) for beat in board['beats']}
                for scene in plan['scenes']:
                    refs = [e['ref'] for e in scene['elements'] if e['kind'] == 'picture']
                    for ref in refs:
                        asset = resolve(ref, stage)
                        if (asset is None or not asset.is_file() or asset.is_symlink()
                                or not (asset.resolve().is_relative_to(stage.resolve())
                                        or asset.resolve().is_relative_to(ASSETS.resolve()))):
                            raise ValueError(f'Missing saved scene picture: {ref}')
                    for bid in scene['beat_ids']:
                        candidates.setdefault(bid, []).extend(refs)
                checked, _ = validate_plan(plan, board, candidates)
                # Validate references and coverage without applying canonical, timing or
                # source-derived phenotype repairs to intentional saved direction.
                if ([s['beat_ids'] for s in plan['scenes']] != [s['beat_ids'] for s in checked['scenes']]
                        or [s['section_id'] for s in plan['storyboard']['sections']]
                        != [s['section_id'] for s in checked['storyboard']['sections']]):
                    raise ValueError('Invalid saved plan: source beat or section coverage')
                cast_ids = {c['id'] for c in plan['cast']}
                for scene, fixed in zip(plan['scenes'], checked['scenes']):
                    if (scene['elements'] != fixed['elements']
                            or any(e['kind'] == 'cast' and e['ref'] not in cast_ids for e in scene['elements'])
                            or [(a['actor'], a['at_beat']) for a in scene['actions']]
                            != [(a['actor'], a['at_beat']) for a in fixed['actions']]
                            or (scene['text']['kind'] != 'none' and scene['text'] != fixed['text'])):
                        raise ValueError('Invalid saved plan: scene source references')
            validate_references(board, cfg, stage)
            qa = stage / 'build/qa.json'
            if qa.exists():
                report = json.loads(qa.read_text(encoding='utf-8'))
                if (not isinstance(report, dict) or not isinstance(report.get('ok'), bool)
                        or not isinstance(report.get('problems'), list)
                        or not all(isinstance(problem, str) for problem in report['problems'])):
                    raise ValueError('Saved QA needs a boolean ok and an array of problem strings')
            if cfg.get('recording'):
                _regular_source(stage, cfg['recording'])
            # Reuse the library's complete verification and atomic no-replace publication.
            # The archive is owned, closed and unchanged throughout both passes.
            import_project(archive, destination)
        except (zipfile.BadZipFile, KeyError, TypeError, AttributeError, ProviderError) as error:
            raise ValueError(f'Incompatible or damaged project ZIP: {error}') from None
    return {'project': destination.name, 'files': len(manifest['files'])}


def starters():
    # Sibling worker owns the module. A missing module is an honest unavailable
    # response, never a generated pretend starter list. The page never needs the file path.
    from ..starters import list_starters
    return [{k: v for k, v in entry.items() if k != 'path'} for entry in list_starters()]


def starter(name):
    """One example script for New video; an unknown name is a ValueError (400)."""
    from ..starters import read
    text = read(name)
    entry = next(e for e in starters() if e['id'] == name)
    return {'id': name, 'lang': entry['lang'], 'title': entry['title'], 'text': text}


def transfer_assets(source, destination):
    """Copy regular source/provenance files; never follow links or replace art."""
    source, destination = Path(source), Path(destination)
    candidates = [p for p in source.rglob('*')
                  if p.relative_to(source).parts[0] in ('doodles', 'photos', 'pictures')
                  or (p.parent == source and p.name.startswith('script.'))]
    for asset in candidates:
        if asset.is_symlink():
            raise ValueError('Linked project assets cannot be transferred')
        relative = asset.relative_to(source)
        target = destination / relative
        if target.is_symlink() or any(p.is_symlink() for p in target.parents if p != destination.parent):
            raise ValueError('Linked asset destinations cannot be transferred')
        if asset.is_file() and target.exists() and asset.read_bytes() != target.read_bytes():
            raise ValueError(f'Asset collision: {relative}; existing art is preserved')
    for asset in candidates:
        if asset.is_file():
            target = destination / asset.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(asset, target)


def validate_references(board, cfg, path):
    from ..director.validate import _doodles, validate
    from ..library import resolve
    refs = set(_doodles(board))
    for scene in (cfg.get('plan_v3') or {}).get('scenes', []):
        refs.update(e['ref'] for e in scene['elements'] if e['kind'] == 'picture')
    for ref in refs:
        if ref.startswith(('gen-', 'own:')):
            asset = resolve(ref, path)
            if asset is None or not asset.is_file() or asset.is_symlink():
                raise ValueError(f'Missing local asset: {ref}')
            if ref.startswith('gen-') and not asset.with_suffix('.json').is_file():
                raise ValueError(f'Missing prop provenance: {ref}')
    report = validate(board, path)
    if not report['ok']:
        raise ValueError('; '.join(report['errors'][:20]))


def hooks():
    return {'provider': provider_for, 'writer': writer, 'make': make, 'export': export,
            'projectzip': projectzip, 'starters': starters, 'starter': starter}


def choose_style(doc, body, lang, aspect, brand, provider=None):
    """Legacy automatic style selection with the canonical offline fallback."""
    from ..director import style
    offered = style.options(aspect, lang, brand)
    ids = [o['id'] for o in offered]
    local = style.offline(doc, ids, lang)
    mode = body.get('director') or 'rules'
    if mode == 'rules':
        return style._done(local, 'rules')
    usage = Usage()
    name = mode
    try:
        if provider is None:
            from .server import STUDIO_HOOKS
            provider = STUDIO_HOOKS['provider'](body)
        name = getattr(provider, 'name', mode)
        if lang not in getattr(provider, 'languages', (lang,)):
            return style._done(local, 'rules', f'{style.BY.get(name, name)} chooses for '
                f'{" and ".join(style._LANG[c] for c in provider.languages)} videos only; {style.BY["rules"]} chose')
        answer = provider.pick_style(style.request(doc, lang, aspect, offered), usage)
    except (ProviderError, ValueError) as error:
        return style._done(local, 'rules', f'{style.BY.get(name, name)} could not choose ({error}); {style.BY["rules"]} chose')
    if answer.get('style') not in ids:
        return style._done(local, 'rules', f'{style.BY.get(name, name)} chose "{style._clip(answer["style"], 40)}", '
            f'which this video cannot use ({aspect}, {lang}{"" if (brand or {}).get("name") else ", no product named"}); '
            f'{style.BY["rules"]} chose')
    return style._done({'style': answer['style'], 'reason': style._clip(answer.get('reason') or '') or 'It suits the script'},
                       name, cost=usage.cost_usd if usage.calls else None)

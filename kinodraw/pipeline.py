"""End to end in a project folder: script -> storyboard -> voice -> timeline -> render -> mix -> package.

Project folder:
  project.json        settings (language, voice, speed, director, workers, credit, recording, optional voice_server)
  script.<ext>        the source script
  recording.<ext>     optional: your own reading of the script, used as the narration
  pronounce.txt       optional: word = respelling, for spoken words only
  read-aloud.txt      the script as it is narrated, one numbered sentence a line: what to read for your recording
  storyboard.json     chapters + beats + visuals (editable; re-running keeps your edits)
  doodles/ photos/    optional: your own SVG doodles and photos
  voice/              cached narration clips (recording-align.json: where each beat is in your recording)
  build/              timeline, narration, mix, silent render, captions
  <Title>.mp4         the finished video, with .srt/.vtt, chapters, transcript, description and thumbnail
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path

from . import PRODUCT, ingest, library, script, styles, voice, voice_server
from .audio import mix as audio
from .engine import render as renderer
from .engine.storyboard import drawable
from .package import clock, contact_sheet, encoded_qa, mux, publish, sha, video_size

ASPECTS = ('16:9', '9:16')


def validate_aspect(aspect: str, look: str | None = None) -> str:
    if aspect not in ASPECTS:
        raise ValueError('aspect must be 16:9 or 9:16')
    entry = styles.get(look or 'whiteboard')
    if entry and aspect not in entry['aspect']:
        raise ValueError(f'{look or "whiteboard"} does not support {aspect}')
    return aspect


def _load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def new_project(source, project_dir: Path, title: str | None = None, lang: str | None = None,
                direction: dict | None = None, **settings) -> dict:
    """Create the project folder from a script file or pasted text and build the storyboard skeleton.
    ``direction`` sets the storyboard's dials: look, story, motion and brand (see docs/storyboard.md)."""
    if (direction or {}).get('look'):
        drawable(direction['look'])
    settings['aspect'] = validate_aspect(settings.get('aspect', '16:9'), (direction or {}).get('look'))
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    src = Path(source) if isinstance(source, Path) or (len(str(source)) < 1024 and '\n' not in str(source)) else None
    if src is not None and src.is_file():
        target = project_dir / f'script{src.suffix.lower()}'
        doc = ingest.read(src, title=title)
        if src.resolve() != target.resolve():
            shutil.copyfile(src, target)
    else:
        target = project_dir / 'script.md'
        target.write_text(str(source), encoding='utf-8')
        doc = ingest.read(str(source), title=title)
    if lang:
        doc.lang = lang
    board = script.build(doc, (direction or {}).get('story') or 'explain')
    board.update({k: v for k, v in (direction or {}).items() if v})
    _save(project_dir / 'storyboard.json', board)
    config = {'script': target.name, 'lang': doc.lang, 'voice': voice.LANGS[doc.lang]['voice'], 'speed': 1.0,
              'director': 'rules', 'director_v3': False, 'series_bible': {'cast': []}, 'workers': 2, **settings}
    _save(project_dir / 'project.json', config)
    return board


def settings(project_dir: Path) -> dict:
    return _load(Path(project_dir) / 'project.json')


def storyboard(project_dir: Path) -> dict:
    return _load(Path(project_dir) / 'storyboard.json')


def direct_v3(project_dir: Path, provider=None, *, prop_llm=None, prop_candidates=None) -> dict:
    """Save the series bible and compatibility board once; re-renders keep the saved plan."""
    from .director.rules import RulesDirector
    from .director.v3.adapter import adapt
    from .director.v3.llm import plan_v3

    project_dir = Path(project_dir)
    cfg = settings(project_dir)
    if cfg.get('plan_v3') is not None:
        return cfg.get('plan_v3_report', {})
    board = storyboard(project_dir)
    plan, report = plan_v3(board, provider=provider if provider is not None else cfg.get('director', 'rules'))
    import copy
    bible = cfg.get('series_bible') or {'cast': copy.deepcopy(plan['cast'])}
    overrides = {c['id']: c for c in bible.get('cast', [])}
    plan['cast'] = [{**c, **overrides.get(c['id'], {})} for c in plan['cast']]
    from .engine.hybrid import prepare_props
    report['notes'] += prepare_props(plan, board, project_dir, prop_llm, prop_candidates)
    RulesDirector(cfg['lang']).direct(board)
    board, treatments = adapt(plan, board)
    # adapter accepts catalog refs only; local sanitized props use the existing project doodle path.
    for scene in plan['scenes']:
        for element in scene['elements']:
            if element['kind'] == 'picture' and element['ref'].startswith('gen-'):
                for bid in scene['beat_ids']:
                    beat = next(b for b in board['beats'] if b['id'] == bid)
                    beat['visuals'].append({'id': f'{bid}-{element["ref"]}', 'type': 'cluster',
                                           'items': [{'doodle': element['ref']}], 'relation': 'none'})
    report = {**report, 'usage': asdict(report['usage'])}
    cfg.update(director_v3=True, plan_v3=plan, plan_v3_report=report, scene_treatments=treatments, series_bible={'cast': plan['cast']})
    _save(project_dir / 'storyboard.json', board)
    _save(project_dir / 'project.json', cfg)
    return report


def set_aspect(project_dir: Path, aspect: str) -> dict:
    """Save the project's format; rendering re-paces the drawings with the cached narration when needed."""
    project_dir = Path(project_dir)
    aspect = validate_aspect(aspect, storyboard(project_dir).get('look'))
    cfg = settings(project_dir)
    cfg['aspect'] = aspect
    _save(project_dir / 'project.json', cfg)
    return cfg


READ_ALOUD = 'read-aloud.txt'
PRONOUNCE = 'pronounce.txt'


def read_aloud(project_dir: Path) -> list[dict]:
    """The script as the sentences that will be narrated, in order ([{beat, text}], numbered from 1 where shown): every
    beat's spoken words, with the lines the storyboard adds to the script (a takeaway says its note's words). The
    Studio's read-aloud page and read-aloud.txt show these, and recording-align.json checks each of them."""
    project_dir = Path(project_dir)
    lang, board = settings(project_dir)['lang'], script.sync_takes(storyboard(project_dir))
    return [{'beat': b['id'], 'text': s} for b in board['beats'] for s in script.sentences(b['spoken'][lang], lang)]


def set_recording(project_dir: Path, source) -> dict:
    """Narrate with your own reading of the script: copy it into the project as recording.<ext> and name it in
    project.json (``None`` goes back to the synthesized voice)."""
    project_dir = Path(project_dir)
    cfg = settings(project_dir)
    if source is None:
        cfg.pop('recording', None)
    else:
        source = Path(source)
        target = project_dir / f'recording{source.suffix.lower()}'
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        cfg['recording'] = target.name
    _save(project_dir / 'project.json', cfg)
    return cfg


def narrate(project_dir: Path, progress=None, server: voice_server.Server | None = None) -> dict:
    """Synthesize (or reuse cached) clips for every beat (takeaways first say what their notes show). With a
    recording in project.json the clips are cut from it instead, guided by the synthesized ones. Writes read-aloud.txt:
    what to read to narrate the video yourself. ``server``: this computer's own voice server setting (the Studio's or
    the CLI's, never the project's), which reads the beats instead of Kokoro unless the project uses a recording; the
    project then records its model and voice. A project that records a server voice is never narrated without one."""
    project_dir = Path(project_dir)
    cfg, board = settings(project_dir), storyboard(project_dir)
    lang = cfg['lang']
    lexicon = voice.read_lexicon(project_dir / PRONOUNCE)
    before = json.dumps(board, ensure_ascii=False, sort_keys=True)
    script.sync_takes(board)
    if json.dumps(board, ensure_ascii=False, sort_keys=True) != before:
        _save(project_dir / 'storyboard.json', board)
    text = project_dir / READ_ALOUD                 # what to read to narrate it yourself (the Studio shows the same)
    text.write_text(''.join(f'{n}. {line["text"]}\n' for n, line in enumerate(read_aloud(project_dir), 1)),
                    encoding='utf-8')
    if cfg.get('recording'):
        server = None                               # your own voice: the guides are Kokoro's, on this computer
    elif server:
        if cfg.get('voice_server') != voice_server.record(server):
            cfg['voice_server'] = voice_server.record(server)
            _save(project_dir / 'project.json', cfg)
    elif 'voice_server' in cfg:                     # never a silent switch to Kokoro, never the project's own address
        raise voice_server.VoiceServerError(voice_server.NOT_ON)
    if not server:
        voice.ensure_models(lang, progress and (lambda done, total: progress('download-voice', done, total)))
    clips = {}
    for i, beat in enumerate(board['beats']):
        if server:
            clips[beat['id']] = voice_server.synthesize(beat['spoken'][lang], lang, project_dir / 'voice', server,
                                                      cfg['speed'], lexicon)
        else:
            clips[beat['id']] = voice.synthesize(beat['spoken'][lang], lang, project_dir / 'voice', cfg['voice'],
                                               cfg['speed'], lexicon)
        if progress:
            progress('voice', i + 1, len(board['beats']))
    if cfg.get('recording'):
        if progress:
            progress('align', 0, 1)
        beats = [(beat['id'], beat['spoken'][lang]) for beat in board['beats']]
        try:
            clips = voice.from_recording(project_dir / cfg['recording'], beats, lang, project_dir / 'voice',
                                         cfg['voice'], cfg['speed'], lexicon)
        except voice.RecordingError as error:
            raise voice.RecordingError(f'{error} To narrate with the AI voice instead, run: kinodraw voice '
                                       f'"{project_dir}" --recording none. The script to read, as it is narrated (one '
                                       f'numbered sentence a line, with the lines {PRODUCT["name"]} adds to yours), is '
                                       f'in "{text}".', error.beat, error.plain) from None
    return clips


def build_audio(project_dir: Path, clips: dict) -> dict:
    """Pace the narration to the drawings (pauses where the hand needs time), then assemble it.

    The decision stamp names the measured layout: landscape or portrait. A 9:16 letterbox measures
    the landscape drawings, so its timeline bytes are identical to 16:9."""
    project_dir = Path(project_dir)
    cfg, board = settings(project_dir), storyboard(project_dir)
    aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
    build = project_dir / 'build'
    pauses = renderer.pacing(board, cfg['lang'], audio.timing(clips), project_dir, aspect)
    tl = audio.assemble(board, cfg['lang'], clips, build, pauses, credit=cfg.get('credit', True))
    tl['storyboard_sha256'] = sha(project_dir / 'storyboard.json')
    tl['layout'] = renderer.pace_layout(board, aspect)
    _save(build / 'timeline.json', tl)
    return tl


def render(project_dir: Path, start: float = 0, duration: float | None = None, workers: int | None = None) -> Path:
    project_dir = Path(project_dir)
    if settings(project_dir).get('director_v3'):
        direct_v3(project_dir)
    board = storyboard(project_dir)
    messages = library.missing_pictures(board, project_dir)
    if messages:
        raise ValueError('\n'.join(messages))
    cfg = settings(project_dir)
    aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
    build = project_dir / 'build'
    tl = _load(build / 'timeline.json')
    if tl.get('layout', 'landscape') != renderer.pace_layout(board, aspect):
        tl = build_audio(project_dir, narrate(project_dir))
    out = build / 'silent.mp4'
    n = round((duration or tl['duration'] - start) * renderer.FPS)
    workers = workers or cfg.get('workers', 1)
    if workers > 1:
        warnings = renderer.render_segments(project_dir, project_dir / 'storyboard.json', cfg['lang'],
                                            build / 'timeline.json', start, n, out, workers, aspect=aspect)
    else:
        prod = renderer.make_production(storyboard(project_dir), tl, cfg['lang'], project_dir, aspect=aspect)
        renderer.encode(prod, start, n, out, 20)
        warnings = prod.warnings
    board = storyboard(project_dir)
    if _hybrid(cfg) or styles.renderer(board.get('look')) != 'whiteboard':   # sound effects follow the scheduled animation
        if workers > 1:
            prod = renderer.make_production(board, tl, cfg['lang'], project_dir, aspect=aspect)
        _save(build / 'cues.json', {'cues': prod.cues()})
    _save(build / 'render-warnings.json', warnings)
    return out


def finish(project_dir: Path) -> dict:
    """Mix music, mux, verify, and write the deliverables next to the project."""
    project_dir = Path(project_dir)
    cfg, board = settings(project_dir), storyboard(project_dir)
    lang, build = cfg['lang'], project_dir / 'build'
    aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
    size = (1080, 1920) if aspect == '9:16' else (1920, 1080)
    rendered = video_size(build / 'silent.mp4')
    if rendered and rendered != size:                 # a format switch saved without a render (`render --stills`)
        raise ValueError(f'The drawings in build/silent.mp4 are {rendered[0]}x{rendered[1]}, but this project is now '
                         f'{aspect} ({size[0]}x{size[1]}). Run: kinodraw render "{project_dir}" first, so the other '
                         'format\'s finished video is not replaced with the wrong picture.')
    tl = _load(build / 'timeline.json')
    mixed = _hybrid_audio(board, tl, build, cfg) if _hybrid(cfg) else audio.mix(board, tl, build)
    stem = re.sub(r'[\\/:*?"<>|¿¡]+', '', board['title'][lang]).strip()[:80] or 'video'
    if aspect == '9:16':
        stem += ' (vertical)'
    video = project_dir / f'{stem}.mp4'
    mux(tl, build / 'silent.mp4', mixed, video, lang, board['title'][lang], build)
    qa = encoded_qa(tl, video, mixed, size=size)
    if board.get('look') == 'collage':                # words written over other words never pass
        crowded = renderer.make_production(board, tl, lang, project_dir).crowded()
        qa['problems'] += [f'At {clock(t)} "{a}" and "{b}" are written on top of each other.' for t, a, b in crowded]
        qa['ok'] = not qa['problems']
    publish(board, tl, lang, build, project_dir, stem, project_dir, own_voice=bool(cfg.get('recording')),
            voice_source=voice_server.describe(cfg['voice_server'], lang)
            if cfg.get('voice_server') and not cfg.get('recording') else None,
            size=(720, 1280) if aspect == '9:16' else (1280, 720))
    contact_sheet(tl, video, build / 'contact-sheet.jpg', size=size)
    qa.update({'video': str(video), 'length': clock(tl['duration'])})
    _save(build / 'qa.json', qa)
    return qa


def make(source, project_dir: Path, direct=None, progress=None, server: voice_server.Server | None = None,
         **settings_) -> dict:
    """Script to finished video. ``direct(project_dir)`` adds visuals to storyboard.json (rules or LLM); ``server``:
    your own voice server (see narrate)."""
    new_project(source, project_dir, **settings_)
    if settings(project_dir).get('director_v3'):
        direct_v3(project_dir)
    elif direct:
        direct(project_dir)
    clips = narrate(project_dir, progress, server)
    build_audio(project_dir, clips)
    render(project_dir)
    return finish(project_dir)


def _hybrid(cfg):
    plan = cfg.get('plan_v3')
    return bool(cfg.get('director_v3') and plan and plan['style']['mode'] != 'whiteboard'
                and any(s['treatment'] != 'whiteboard' for s in plan['scenes']))


def _hybrid_audio(board, tl, build, cfg):
    from .audio import score, sfx, master
    import numpy as np
    speech = audio.read_wav(audio.narration(tl, build))[0]
    style = cfg['plan_v3']['style']
    if style['music_mood'] != 'none' and board.get('music', True):
        result = score.render(tl['duration'], style['music_mood'], style['tempo_bpm'],
                              narration=speech, ambient=True)
        out = speech + result.music
        _save(build / 'score.json', {'bpm': result.bpm, 'track': result.track,
                                   'beats': result.beats.tolist()})
    else:
        out = np.repeat(speech, 2, axis=1) if speech.shape[1] == 1 else speech.copy()
    cues_path = build / 'cues.json'
    cues = _load(cues_path)['cues'] if cues_path.is_file() else []
    if cues and board.get('sfx', True):
        env = audio.envelope(speech.mean(axis=1))
        out += sfx.render(cues, tl['duration']) * (1 + (10 ** (audio.SFX_DUCK_DB / 20) - 1) * env)[:, None]
    out = master.master(out, audio.SR)
    path = build / 'mix.wav'
    audio.write_wav(path, out)
    return path

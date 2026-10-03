"""End to end in a project folder: script -> storyboard -> voice -> timeline -> render -> mix -> package.

Project folder:
  project.json        settings (language, voice, speed, director, workers, credit, recording)
  script.<ext>        the source script
  recording.<ext>     optional: your own reading of the script, used as the narration
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
from pathlib import Path

from . import PRODUCT, ingest, script, styles, voice
from .audio import mix as audio
from .engine import render as renderer
from .engine.storyboard import drawable
from .package import clock, contact_sheet, encoded_qa, mux, publish, sha


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
              'director': 'rules', 'workers': 2, **settings}
    _save(project_dir / 'project.json', config)
    return board


def settings(project_dir: Path) -> dict:
    return _load(Path(project_dir) / 'project.json')


def storyboard(project_dir: Path) -> dict:
    return _load(Path(project_dir) / 'storyboard.json')


READ_ALOUD = 'read-aloud.txt'


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


def narrate(project_dir: Path, progress=None) -> dict:
    """Synthesize (or reuse cached) clips for every beat (takeaways first say what their notes show). With a
    recording in project.json the clips are cut from it instead, guided by the synthesized ones. Writes read-aloud.txt:
    what to read to narrate the video yourself."""
    project_dir = Path(project_dir)
    cfg, board = settings(project_dir), storyboard(project_dir)
    lang = cfg['lang']
    before = json.dumps(board, ensure_ascii=False, sort_keys=True)
    script.sync_takes(board)
    if json.dumps(board, ensure_ascii=False, sort_keys=True) != before:
        _save(project_dir / 'storyboard.json', board)
    text = project_dir / READ_ALOUD                 # what to read to narrate it yourself (the Studio shows the same)
    text.write_text(''.join(f'{n}. {line["text"]}\n' for n, line in enumerate(read_aloud(project_dir), 1)),
                    encoding='utf-8')
    voice.ensure_models(lang, progress and (lambda done, total: progress('download-voice', done, total)))
    clips = {}
    for i, beat in enumerate(board['beats']):
        clips[beat['id']] = voice.synthesize(beat['spoken'][lang], lang, project_dir / 'voice', cfg['voice'], cfg['speed'])
        if progress:
            progress('voice', i + 1, len(board['beats']))
    if cfg.get('recording'):
        if progress:
            progress('align', 0, 1)
        beats = [(beat['id'], beat['spoken'][lang]) for beat in board['beats']]
        try:
            clips = voice.from_recording(project_dir / cfg['recording'], beats, lang, project_dir / 'voice',
                                         cfg['voice'], cfg['speed'])
        except voice.RecordingError as error:
            raise voice.RecordingError(f'{error} To narrate with the AI voice instead, run: kinodraw voice '
                                       f'"{project_dir}" --recording none. The script to read, as it is narrated (one '
                                       f'numbered sentence a line, with the lines {PRODUCT["name"]} adds to yours), is '
                                       f'in "{text}".', error.beat, error.plain) from None
    return clips


def build_audio(project_dir: Path, clips: dict) -> dict:
    """Pace the narration to the drawings (pauses where the hand needs time), then assemble it."""
    project_dir = Path(project_dir)
    cfg, board = settings(project_dir), storyboard(project_dir)
    build = project_dir / 'build'
    pauses = renderer.pacing(board, cfg['lang'], audio.timing(clips), project_dir)
    tl = audio.assemble(board, cfg['lang'], clips, build, pauses, credit=cfg.get('credit', True))
    tl['storyboard_sha256'] = sha(project_dir / 'storyboard.json')
    _save(build / 'timeline.json', tl)
    return tl


def render(project_dir: Path, start: float = 0, duration: float | None = None, workers: int | None = None) -> Path:
    project_dir = Path(project_dir)
    cfg = settings(project_dir)
    build = project_dir / 'build'
    tl = _load(build / 'timeline.json')
    out = build / 'silent.mp4'
    n = round((duration or tl['duration'] - start) * renderer.FPS)
    workers = workers or cfg.get('workers', 1)
    if workers > 1:
        warnings = renderer.render_segments(project_dir, project_dir / 'storyboard.json', cfg['lang'],
                                            build / 'timeline.json', start, n, out, workers)
    else:
        prod = renderer.make_production(storyboard(project_dir), tl, cfg['lang'], project_dir)
        renderer.encode(prod, start, n, out, 20)
        warnings = prod.warnings
    board = storyboard(project_dir)
    if styles.renderer(board.get('look')) != 'whiteboard':   # sound effects follow the scheduled animation
        if workers > 1:
            prod = renderer.make_production(board, tl, cfg['lang'], project_dir)
        _save(build / 'cues.json', {'cues': prod.cues()})
    _save(build / 'render-warnings.json', warnings)
    return out


def finish(project_dir: Path) -> dict:
    """Mix music, mux, verify, and write the deliverables next to the project."""
    project_dir = Path(project_dir)
    cfg, board = settings(project_dir), storyboard(project_dir)
    lang, build = cfg['lang'], project_dir / 'build'
    tl = _load(build / 'timeline.json')
    mixed = audio.mix(board, tl, build)
    stem = re.sub(r'[\\/:*?"<>|¿¡]+', '', board['title'][lang]).strip()[:80] or 'video'
    video = project_dir / f'{stem}.mp4'
    mux(tl, build / 'silent.mp4', mixed, video, lang, board['title'][lang], build)
    qa = encoded_qa(tl, video, mixed)
    if board.get('look') == 'collage':                # words written over other words never pass
        crowded = renderer.make_production(board, tl, lang, project_dir).crowded()
        qa['problems'] += [f'At {clock(t)} "{a}" and "{b}" are written on top of each other.' for t, a, b in crowded]
        qa['ok'] = not qa['problems']
    publish(board, tl, lang, build, project_dir, stem, project_dir, own_voice=bool(cfg.get('recording')))
    contact_sheet(tl, video, build / 'contact-sheet.jpg')
    qa.update({'video': str(video), 'length': clock(tl['duration'])})
    _save(build / 'qa.json', qa)
    return qa


def make(source, project_dir: Path, direct=None, progress=None, **settings_) -> dict:
    """Script to finished video. ``direct(project_dir)`` adds visuals to storyboard.json (rules or LLM)."""
    new_project(source, project_dir, **settings_)
    if direct:
        direct(project_dir)
    clips = narrate(project_dir, progress)
    build_audio(project_dir, clips)
    render(project_dir)
    return finish(project_dir)

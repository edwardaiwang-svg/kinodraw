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
from copy import deepcopy
import tempfile
import subprocess
import sys
from pathlib import Path

from . import PRODUCT, ingest, library, script, speech, styles, voice, voice_server
from .project_store import ProjectStore, atomic_save_json
from .progress import RenderContext, wait_process
from .audio import mix as audio
from .engine import render as renderer
from .engine.storyboard import drawable
from .package import clock, contact_sheet, encoded_qa, mux, publish, sha, video_size

ASPECTS = ('16:9', '9:16', '1:1')


def validate_aspect(aspect: str, look: str | None = None) -> str:
    if aspect not in ASPECTS:
        raise ValueError('aspect must be 16:9, 9:16 or 1:1')
    entry = styles.get(look or 'whiteboard')
    if entry and aspect not in entry['aspect']:
        raise ValueError(f'{look or "whiteboard"} does not support {aspect}')
    return aspect


def validate_size(size=None, aspect='16:9', look=None):
    """Natural targets supported by the saved production, before any writes."""
    validate_aspect(aspect, look)
    natural = {'16:9': (1920, 1080), '9:16': (1080, 1920), '1:1': (1080, 1080)}
    if size is None:
        size = natural[aspect]
    if (not isinstance(size, (tuple, list)) or len(size) != 2
            or any(type(v) is not int or v <= 0 or v % 2 for v in size)):
        raise ValueError('size requires two positive even integer dimensions')
    size = tuple(size)
    supported = (natural[aspect], (3840, 2160)) if aspect == '16:9' else (natural[aspect],)
    if size not in supported:
        raise ValueError('size must match a supported natural aspect: 1920x1080, 3840x2160, 1080x1080 or 1080x1920')
    if styles.renderer(look) == 'collage' and (aspect == '1:1' or size == (3840, 2160)):
        raise ValueError('native collage export is not supported')
    return size


def _pace_aspect(aspect):
    # Native square rebuilds geometry using the saved source timing. Keep the
    # cached landscape narration rather than asking the legacy pacer to crop it.
    return '16:9' if aspect == '1:1' else aspect


def _load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _save(path: Path, data):
    atomic_save_json(path, data)


def new_project(source, project_dir: Path, title: str | None = None, lang: str | None = None,
                direction: dict | None = None, **settings) -> dict:
    """Create the project folder from a script file or pasted text and build the storyboard skeleton.
    ``direction`` sets the storyboard's dials: look, story, motion and brand (see docs/storyboard.md)."""
    if (direction or {}).get('look'):
        drawable(direction['look'])
    settings['aspect'] = validate_aspect(settings.get('aspect', '16:9'), (direction or {}).get('look'))
    validate_size(settings.get('size'), settings['aspect'], (direction or {}).get('look'))
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    if (project_dir / 'project.json').exists():
        raise FileExistsError('Project already exists; render its saved storyboard instead')
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
    board = script.build(doc, (direction or {}).get('story') or 'explain', title_card=True)
    board.update({k: v for k, v in (direction or {}).items() if v})
    config = {'script': target.name, 'lang': doc.lang, 'voice': voice.LANGS[doc.lang]['voice'], 'speed': 1.0,
              'director': 'rules', 'director_v3': False, 'series_bible': {'cast': []}, 'workers': 2, **settings}
    ProjectStore(project_dir).initialize(board, config)
    return board


def settings(project_dir: Path) -> dict:
    return ProjectStore(project_dir).load()['settings']


def storyboard(project_dir: Path) -> dict:
    return ProjectStore(project_dir).load()['storyboard']


def direct_v3(project_dir: Path, provider=None, *, prop_llm=None, prop_candidates=None) -> dict:
    """Save the series bible and compatibility board once; re-renders keep the saved plan."""
    from .director.rules import RulesDirector
    from .director.v3.adapter import adapt
    from .director.v3.llm import plan_v3

    project_dir = Path(project_dir)
    store = ProjectStore(project_dir)
    saved = store.load()
    cfg, board = saved['settings'], saved['storyboard']
    if cfg.get('plan_v3') is not None:
        return cfg.get('plan_v3_report', {})
    board = _story_told_straight(board)
    original = deepcopy(board)
    selected = provider if provider is not None else cfg.get('director', 'rules')
    if isinstance(provider, str):
        from .director import provider_settings
        cfg = provider_settings(cfg, provider)
    if isinstance(selected, str) and selected != 'rules':
        from .director import provider_for, provider_settings
        selected = provider_for(provider_settings(cfg, selected))
    plan, report = plan_v3(board, provider=selected)
    import copy
    bible = cfg.get('series_bible') or {'cast': copy.deepcopy(plan['cast'])}
    overrides = {c['id']: c for c in bible.get('cast', [])}
    plan['cast'] = [c if _stale_human(overrides.get(c['id']), c) else {**c, **overrides.get(c['id'], {})}
                    for c in plan['cast']]
    from .engine.hybrid import prepare_props
    if prop_llm is None and selected != 'rules' and not isinstance(selected, str):
        try:
            from .director.llm.props import make_prop_llm
        except ModuleNotFoundError as error:
            if error.name != 'kinodraw.director.llm.props':
                raise
        else:
            prop_llm = make_prop_llm(selected, report['usage'])
    report['notes'] += prepare_props(plan, board, project_dir, prop_llm, prop_candidates)
    from .director.validate import _doodles
    for scene in plan['scenes']:
        refs = {e['ref'] for e in scene['elements'] if e['kind'] == 'picture'}
        for prior in original['beats']:
            if prior['id'] not in scene['beat_ids']:
                continue
            for ref in _doodles(prior.get('visuals', [])):
                if ref.startswith('own:') and Path(ref).suffix.lower() != '.svg':
                    scene['treatment'] = 'whiteboard'
                elif ref not in refs:
                    scene['elements'].append({'kind': 'picture', 'ref': ref})
                    refs.add(ref)
    RulesDirector(cfg['lang']).direct(board)
    board, treatments = adapt(plan, board)
    # Saved visual instructions are editable source data, including local art.
    for beat, prior in zip(board['beats'], original['beats']):
        if prior.get('visuals'):
            beat['visuals'] = deepcopy(prior['visuals'])
    # adapter accepts catalog refs only; local sanitized props use the existing project doodle path.
    for scene in plan['scenes']:
        for element in scene['elements']:
            if element['kind'] == 'picture' and element['ref'].startswith('gen-'):
                for bid in scene['beat_ids']:
                    beat = next(b for b in board['beats'] if b['id'] == bid)
                    if element['ref'] in set(_doodles(beat['visuals'])):
                        continue
                    beat['visuals'].append({'id': f'{bid}-{element["ref"]}', 'type': 'cluster',
                                           'items': [{'doodle': element['ref']}], 'relation': 'none'})
    report = {**report, 'usage': asdict(report['usage'])}
    cfg.update(director_v3=True, plan_v3=plan, plan_v3_report=report, scene_treatments=treatments, series_bible={'cast': plan['cast']})
    store.save(board, cfg, saved['revision'], 'Before v3 direction')
    return report


def _story_told_straight(board: dict) -> dict:
    """A story made with the explainer skeleton (the Studio's look menu defaults to it) is told straight:
    no spoken title, agenda, "Part N" or takeaway cards. Explainers and chosen story types are unchanged."""
    from .director.v3.rules import detect_genre
    from .director.v3.semantics import beats, detect_cast
    if board.get('story', 'explain') != 'explain' or not any(b.get('kind') in script.SCAFFOLD for b in board['beats']):
        return board
    lang = board.get('lang', 'en')
    told = [b for b in beats(board) if b['kind'] not in script.SCAFFOLD]
    title = board.get('title', {})
    title = title.get(lang, '') if isinstance(title, dict) else title
    text = '\n'.join(b['text'] for b in told)
    if detect_genre(title + '\n' + text) != 'story':
        return board
    # A narrative, not an explainer that quotes someone once: animal characters, a fairy-tale opening, or
    # several named characters in dialogue.
    cast = detect_cast(told)
    if not (re.search(r'\bonce upon a time\b', text, re.I) or any(c['kind'] != 'human' for c in cast)
            or (len(cast) >= 2 and len(re.findall(r'["“][^"“”]+["”]', text)) >= 2)):
        return board
    return script.tell_straight(board)


def _stale_human(saved: dict | None, fresh: dict) -> bool:
    """A series-bible entry saved when an animal was miscast as a person must not turn it back into one.

    Genuine edits (a lioness made a tigress, new marks or colours) still override the fresh cast."""
    from .director.v3.semantics import HUMAN_SPECIES
    if not saved or fresh.get('kind') == 'human':
        return False
    return saved.get('kind') == 'human' or saved.get('family') == 'human' or saved.get('species') in HUMAN_SPECIES


def set_aspect(project_dir: Path, aspect: str) -> dict:
    """Save the project's format; rendering re-paces the drawings with the cached narration when needed."""
    return set_format(project_dir, aspect=aspect)


def set_format(project_dir: Path, *, aspect=None, size=None) -> dict:
    """Validate and save one size/aspect pair; omitted keywords keep defaults."""
    project_dir = Path(project_dir)
    store = ProjectStore(project_dir)
    saved = store.load()
    cfg = saved['settings']
    prior = cfg.get('aspect', '16:9')
    aspect = validate_aspect(prior if aspect is None else aspect, saved['storyboard'].get('look'))
    target = validate_size(size if size is not None else cfg.get('size') if aspect == prior else None,
                           aspect, saved['storyboard'].get('look'))
    cfg['aspect'] = aspect
    if size is not None or 'size' in cfg:
        cfg['size'] = list(target)
    store.save(saved['storyboard'], cfg, saved['revision'])
    return cfg


READ_ALOUD = 'read-aloud.txt'
PRONOUNCE = 'pronounce.txt'


def read_aloud(project_dir: Path) -> list[dict]:
    """The script as the sentences that will be narrated, in order ([{beat, text}], numbered from 1 where shown): every
    beat's spoken words, with the lines the storyboard adds to the script (a takeaway says its note's words). The
    Studio's read-aloud page and read-aloud.txt show these, and recording-align.json checks each of them."""
    project_dir = Path(project_dir)
    saved = ProjectStore(project_dir).load()
    lang, board = saved['settings']['lang'], script.sync_takes(saved['storyboard'])
    labels = speech.screenplay_labels(b['display'][lang] for b in board['beats'])
    return [{'beat': b['id'], 'text': s} for b in board['beats'] if not b.get('silent')
            for s in script.sentences(speech.said_text(b['spoken'][lang], lang, labels)[0], lang)]


def set_recording(project_dir: Path, source) -> dict:
    """Narrate with your own reading of the script: copy it into the project as recording.<ext> and name it in
    project.json (``None`` goes back to the synthesized voice)."""
    project_dir = Path(project_dir)
    store = ProjectStore(project_dir)
    saved = store.load()
    cfg = saved['settings']
    if source is None:
        cfg.pop('recording', None)
    else:
        source = Path(source)
        target = project_dir / f'recording{source.suffix.lower()}'
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        cfg['recording'] = target.name
    store.save(saved['storyboard'], cfg, saved['revision'])
    return cfg


MUSIC_DIR = 'music'
MUSIC_MAX_BYTES = 150 * 1024 ** 2
MUSIC_SECONDS = (10, 600)


def set_music(project_dir: Path, source, name: str | None = None):
    """Your own music under the video: copy the file into the project as music/<name> (``name``: the file name to
    use, the source's by default) and name it, with its measured tempo (audio/tempo.py), in the storyboard's music
    setting. Refused unless it plays, is 10 s to 10 minutes long and at most 150 MB. ``'none'`` plays no music and
    ``None`` the automatic music again (the file stays in music/). Returns the setting."""
    import numpy as np
    from .audio import score, tempo
    project_dir = Path(project_dir)
    store = ProjectStore(project_dir)
    saved = store.load()
    if source is None or source == 'none':
        setting = source is None
    else:
        source = Path(source)
        name = name or source.name
        size = source.stat().st_size
        if not size:
            raise ValueError(f'“{name}” is empty. Choose your music again.')
        if size > MUSIC_MAX_BYTES:
            raise ValueError(f'“{name}” is too big (over 150 MB). Save it as .mp3 or .m4a and try again.')
        low, high = MUSIC_SECONDS
        try:
            samples = audio.decode(source, 1, seconds=high + 1)[:, 0]
        except subprocess.CalledProcessError:
            raise ValueError(f'“{name}” isn’t music KinoDraw can play. .mp3, .m4a, .wav, .ogg and .flac files all '
                             'work: save or export it as one of those and try again.') from None
        if len(samples) < low * audio.SR:
            raise ValueError(f'“{name}” is {len(samples) / audio.SR:.0f} seconds long. Choose music at least '
                             f'{low} seconds long: it repeats under a longer video.')
        if len(samples) > high * audio.SR:
            raise ValueError(f'“{name}” is over {high // 60} minutes long. Choose a shorter piece: it repeats under '
                             'a longer video.')
        measured = tempo.estimate(samples)
        heard = np.flatnonzero(np.abs(samples) > 1e-3)
        if not len(heard) or (heard[-1] + 1) / audio.SR - measured['downbeat'] < 480 / measured['bpm']:
            raise ValueError(f'“{name}” has too little music to repeat (two bars at least). Choose a longer piece.')
        suffix = Path(name).suffix.lower()
        suffix = suffix if re.fullmatch(r'\.[a-z0-9]{1,5}', suffix) else '.audio'
        stem = re.sub(r'[^\w\-]', '', Path(name).stem.replace(' ', '-'))[:60] or 'music'
        folder = project_dir / MUSIC_DIR
        folder.mkdir(exist_ok=True)
        target = folder / f'{stem}{suffix}'
        if source.resolve() != target.resolve():
            part = folder / f'.copy{suffix}'
            try:
                shutil.copyfile(source, part)
                part.replace(target)
            finally:
                part.unlink(missing_ok=True)
        try:
            previous = score.own(saved['storyboard'].get('music'), project_dir)
        except ValueError:                                           # a hand-edited setting: nothing to replace
            previous = None
        if previous and previous.path.name != target.name:          # the track this one replaces
            previous.path.unlink(missing_ok=True)
        setting = {'file': f'{MUSIC_DIR}/{target.name}', 'bpm': round(measured['bpm'], 4),
                   'downbeat': round(measured['downbeat'], 4)}
    saved['storyboard']['music'] = setting
    store.save(saved['storyboard'], saved['settings'], saved['revision'])
    return setting


class _Narration(dict):
    """Beat clips with the paired source revision used to synthesize them."""
    def __init__(self, clips, revision, source_hash):
        super().__init__(clips)
        self.revision = revision
        self.source_hash = source_hash


def narrate(project_dir: Path, progress=None, server: voice_server.Server | None = None) -> dict:
    """Synthesize (or reuse cached) clips for every beat (takeaways first say what their notes show). With a
    recording in project.json the clips are cut from it instead, guided by the synthesized ones. Writes read-aloud.txt:
    what to read to narrate the video yourself. ``server``: this computer's own voice server setting (the Studio's or
    the CLI's, never the project's), which reads the beats instead of Kokoro unless the project uses a recording; the
    project then records its model and voice. A project that records a server voice is never narrated without one."""
    project_dir = Path(project_dir)
    store = ProjectStore(project_dir)
    saved = store.load()
    cfg, board = saved['settings'], saved['storyboard']
    lang = cfg['lang']
    lexicon = voice.read_lexicon(project_dir / PRONOUNCE)
    before = json.dumps(board, ensure_ascii=False, sort_keys=True)
    script.sync_takes(board)
    if json.dumps(board, ensure_ascii=False, sort_keys=True) != before:
        saved = store.save(board, cfg, saved['revision'])
    text = project_dir / READ_ALOUD                 # what to read to narrate it yourself (the Studio shows the same)
    text.write_text(''.join(f'{n}. {line["text"]}\n' for n, line in enumerate(read_aloud(project_dir), 1)),
                    encoding='utf-8')
    if cfg.get('recording'):
        server = None                               # your own voice: the guides are Kokoro's, on this computer
    elif server:
        if cfg.get('voice_server') != voice_server.record(server):
            cfg['voice_server'] = voice_server.record(server)
            saved = store.save(board, cfg, saved['revision'])
    elif 'voice_server' in cfg:                     # never a silent switch to Kokoro, never the project's own address
        raise voice_server.VoiceServerError(voice_server.NOT_ON)
    with store.locked():
        store._check(store._state(), saved['revision'])
        source_hash = sha(project_dir / 'storyboard.json')
    if not server:
        voice.ensure_models(lang, progress and (lambda done, total: progress('download-voice', done, total)))
    clips = {}
    # What each beat says and who says it: labels, stage directions and emoji are never read; each character has
    # their own voice (a voice server or your recording reads every part in its one voice).
    plan = cfg.get('plan_v3') if cfg.get('director_v3') else None
    parts = speech.voice_parts(board, plan, cfg['voice'], None if server else (lambda: voice.voices(lang)))
    (project_dir / 'voice').mkdir(parents=True, exist_ok=True)
    (project_dir / 'voice' / 'cast.json').write_text(json.dumps(speech.cast_of(
        parts, 'your recording' if cfg.get('recording') else 'the voice server' if server else None)), encoding='utf-8')
    for i, beat in enumerate(board['beats']):
        if progress and hasattr(progress, 'check_cancelled'):
            progress.check_cancelled()
        spoken, todo = beat['spoken'][lang], parts[beat['id']]
        if server:
            said, index = _one_voice(todo['parts'])
            clip = voice_server.synthesize(said, lang, project_dir / 'voice', server, cfg['speed'], lexicon) \
                if said else voice.silence(todo['hold'], len(spoken), project_dir / 'voice')
            clips[beat['id']] = _remapped(clip, spoken, said, index)
        else:
            clips[beat['id']] = voice.speak(spoken, todo['parts'], lang, project_dir / 'voice', cfg['speed'], lexicon,
                                            todo['hold'])
        if progress:
            progress('voice', i + 1, len(board['beats']))
    if cfg.get('recording'):
        if progress:
            progress('align', 0, 1)
        said = {beat['id']: _one_voice(parts[beat['id']]['parts']) for beat in board['beats']}
        beats = [(bid, text) for bid, (text, _) in said.items() if text]
        try:
            taken = voice.from_recording(project_dir / cfg['recording'], beats, lang, project_dir / 'voice',
                                         cfg['voice'], cfg['speed'], lexicon,
                                         **({} if cfg.get('clean_recording', True) else {'clean': False}))
            if any(said[beat['id']][0] != beat['spoken'][lang] for beat in board['beats']):
                # Labels or directions were left out of the reading: times move back onto the spoken text, and
                # a beat with nothing to read keeps its silent hold.
                taken = {beat['id']: _remapped(taken[beat['id']], beat['spoken'][lang], *said[beat['id']])
                         if beat['id'] in taken else clips[beat['id']] for beat in board['beats']}
            clips = taken
        except voice.RecordingError as error:
            raise voice.RecordingError(f'{error} To narrate with the AI voice instead, run: kinodraw voice '
                                       f'"{project_dir}" --recording none. The script to read, as it is narrated (one '
                                       f'numbered sentence a line, with the lines {PRODUCT["name"]} adds to yours), is '
                                       f'in "{text}".', error.beat, error.plain) from None
    return _Narration(clips, saved['revision'], source_hash)


def _one_voice(parts) -> tuple[str, list]:
    """Every part of a beat as one text for one voice, and the spoken-text offset of each of its characters."""
    text, index = '', []
    for seg, _, _ in parts:
        if text:
            text += ' '
            index.append(seg.index[0])
        text, index = text + seg.said, index + seg.index
    return text, index


def _remapped(clip, spoken: str, said: str, index: list):
    """A clip of ``said`` with its character times moved onto the beat's spoken text."""
    if said == spoken or not said:
        return clip if said == spoken else voice.Clip(clip.wav, clip.duration, [0.0] * len(spoken))
    return voice.Clip(clip.wav, clip.duration, speech.spoken_times(spoken, index, clip.char_times))


def build_audio(project_dir: Path, clips: dict) -> dict:
    """Pace the narration to the drawings (pauses where the hand needs time), then assemble it.

    The decision stamp names the measured layout: landscape or portrait. A 9:16 letterbox measures
    the landscape drawings, so its timeline bytes are identical to 16:9."""
    project_dir = Path(project_dir)
    store = ProjectStore(project_dir)
    saved = store.load()
    with store.locked():
        current = store._state()
        store._check(current, saved['revision'])
        store._check(current, getattr(clips, 'revision', None))
        source_hash = clips.source_hash if isinstance(clips, _Narration) else sha(project_dir / 'storyboard.json')
    cfg, board = saved['settings'], saved['storyboard']
    aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
    build = project_dir / 'build'
    # Hybrid scene timing follows the measured source speech; whiteboard pacing
    # otherwise introduces pauses for drawings the motion renderer never uses.
    validate_size(cfg.get('size'), aspect, board.get('look'))
    pauses = {} if _hybrid(cfg) else renderer.pacing(board, cfg['lang'], audio.timing(clips), project_dir, _pace_aspect(aspect))
    build.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.audio-', dir=build) as folder:
        stage = Path(folder)
        tl = audio.assemble(board, cfg['lang'], clips, stage, pauses, credit=cfg.get('credit', True))
        tl['storyboard_sha256'] = source_hash
        tl['layout'] = renderer.pace_layout(board, _pace_aspect(aspect))
        _save(stage / 'timeline.json', tl)
        with store.locked():
            store._check(store._state(), saved['revision'])
            _publish_outputs([(output, build / output.name) for output in stage.iterdir() if output.is_file()],
                             project_dir, RenderContext())
    return tl


def render(project_dir: Path, start: float = 0, duration: float | None = None, workers: int | None = None, *, context=None, size=None, aspect=None) -> Path:
    project_dir = Path(project_dir)
    saved = ProjectStore(project_dir).load()
    cfg, board = saved['settings'], saved['storyboard']
    target_aspect = aspect if aspect is not None else cfg.get('aspect', '16:9')
    validate_size(size if size is not None else cfg.get('size') if target_aspect == cfg.get('aspect', '16:9') else None,
                  target_aspect, board.get('look'))
    if size is not None or aspect is not None:
        set_format(project_dir, size=size, aspect=aspect)
    if settings(project_dir).get('director_v3'):
        direct_v3(project_dir)
    saved = ProjectStore(project_dir).load()
    cfg, board = saved['settings'], saved['storyboard']
    messages = library.missing_pictures(board, project_dir)
    if messages:
        raise ValueError('\n'.join(messages))
    aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
    target = validate_size(cfg.get('size'), aspect, board.get('look'))
    native = {'size': target} if cfg.get('size') is not None else {}
    build = project_dir / 'build'
    tl = _load(build / 'timeline.json')
    if tl.get('layout', 'landscape') != renderer.pace_layout(board, _pace_aspect(aspect)):
        tl = build_audio(project_dir, narrate(project_dir))
    out = build / 'silent.mp4'
    n = round((duration or tl['duration'] - start) * renderer.FPS)
    if not workers:
        workers = cfg.get('workers', 1)
        if workers > 1:   # a saved 2 meant "parallel" when 2 was the cap; use every spare core
            workers = max(workers, min(renderer.auto_workers(), n))
    if workers > 1:
        warnings = renderer.render_segments(project_dir, project_dir / 'storyboard.json', cfg['lang'],
                                            build / 'timeline.json', start, n, out, workers, aspect=aspect, context=context, **native)
    else:
        prod = renderer.make_production(board, tl, cfg['lang'], project_dir, aspect=aspect, **native)
        renderer.encode(prod, start, n, out, 20, context=context)
        warnings = prod.warnings
    if _hybrid(cfg) or styles.renderer(board.get('look')) != 'whiteboard':   # sound effects follow the scheduled animation
        if workers > 1:
            prod = renderer.make_production(board, tl, cfg['lang'], project_dir, aspect=aspect, **native)
        _save(build / 'cues.json', {'cues': prod.cues()})
    _save(build / 'render-warnings.json', warnings)
    return out


def finish(project_dir: Path, *, context=None) -> dict:
    """Mix music, mux, verify, and write the deliverables next to the project."""
    project_dir = Path(project_dir)
    ctx = context or RenderContext()
    store = ProjectStore(project_dir)
    saved = store.load()
    ctx.token.check()
    with tempfile.TemporaryDirectory(prefix='finish-') as folder:
        stage = Path(folder) / 'project'
        with store.locked():
            store._check(store._state(), saved['revision'])
            _check_render_size(project_dir, saved)
            _copy_project(project_dir, stage)
        # FFmpeg inherits this owned group. Frozen apps dispatch the same worker
        # flag through packaging/launch.py instead of interpreting Python code.
        with (Path(folder) / 'worker.log').open('w+b') as log:
            process = ctx.token.register(subprocess.Popen(_finish_command(stage),
                stdout=log, stderr=log, start_new_session=True), group=True)
            try:
                try:
                    wait_process(process, ctx)
                except RuntimeError as error:
                    ctx.token.check()
                    log.seek(0)
                    detail = log.read().decode('utf-8', errors='replace')[-2000:]
                    raise RuntimeError(f'finish worker exited {process.returncode}: {detail}') from error
                qa = _load(stage / 'build/qa.json')
                qa['video'] = str(project_dir / Path(qa['video']).name)
                _save(stage / 'build/qa.json', qa)   # failed checks publish too; the Studio lists them as warnings
                with store.locked():
                    store._check(store._state(), saved['revision'])
                    with ctx.token._lock:
                        ctx.token.check()
                        _commit_outputs(stage, project_dir, ctx)
                        ctx.published = True
                return qa
            finally:
                ctx.token.stop(process)
                ctx.token.unregister(process)


def _finish_command(project_dir):
    worker = [sys.executable, '--finish-worker'] if getattr(sys, 'frozen', False) else \
        [sys.executable, '-m', 'kinodraw.pipeline', '--finish-worker']
    return worker + [str(project_dir)]


def finish_worker(argv=None):
    """Private launcher entrypoint; package children remain in the parent's group."""
    import argparse
    import signal
    from .progress import Cancelled
    parser = argparse.ArgumentParser(prog='--finish-worker')
    parser.add_argument('project')
    args = parser.parse_args(argv)
    def cancelled(*_):
        # subprocess.run reaps its current child when interrupted by an exception.
        raise Cancelled('finish cancelled')
    previous = signal.signal(signal.SIGTERM, cancelled)
    try:
        _finish(Path(args.project))
    finally:
        signal.signal(signal.SIGTERM, previous)


def _check_render_size(project_dir, saved):
    cfg, board = saved['settings'], saved['storyboard']
    aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
    size = validate_size(cfg.get('size'), aspect, board.get('look'))
    rendered = video_size(project_dir / 'build/silent.mp4')
    if rendered and rendered != size:                 # a format switch saved without a render (`render --stills`)
        raise ValueError(f'The drawings in build/silent.mp4 are {rendered[0]}x{rendered[1]}, but this project is now '
                         f'{aspect} ({size[0]}x{size[1]}). Run: kinodraw render "{project_dir}" first, so the other '
                         'format\'s finished video is not replaced with the wrong picture.')
    return size


def _finish(project_dir):
    """Finish inside a disposable worker directory; never publish to the live project."""
    saved = ProjectStore(project_dir).load()
    cfg, board = saved['settings'], saved['storyboard']
    lang, build = cfg['lang'], project_dir / 'build'
    aspect = validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
    size = _check_render_size(project_dir, saved)
    tl = _load(build / 'timeline.json')
    mixed = _hybrid_audio(board, tl, build, cfg) if _scored(cfg, board) else audio.mix(board, tl, build)
    stem = _output_stem(board, cfg)
    video = project_dir / f'{stem}.mp4'
    mux(tl, build / 'silent.mp4', mixed, video, lang, board['title'][lang], build)
    # Finish QA counts all frames and compares narration. Also decode every
    # audio packet before any deliverable can leave this generated stage.
    decoded = subprocess.run([renderer.FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode',
                              '-i', str(video), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                             capture_output=True)
    if decoded.returncode or decoded.stderr.strip():
        raise RuntimeError(f'finished media decode failed ({decoded.returncode}): {decoded.stderr.decode(errors="replace")}')
    qa = encoded_qa(tl, video, mixed, size=size, narrated_pages=_narrated_pages(cfg, tl))
    cast = project_dir / 'voice' / 'cast.json'
    qa['voices'] = speech.shared_voices(json.loads(cast.read_text(encoding='utf-8'))) if cast.is_file() else []
    if board.get('look') == 'collage':                # words written over other words never pass
        crowded = renderer.make_production(board, tl, lang, project_dir).crowded()
        qa['problems'] += [f'At {clock(t)} "{a}" and "{b}" are written on top of each other.' for t, a, b in crowded]
        qa['ok'] = not qa['problems']
    if cfg.get('plan_v3'):
        # Does the video show what its script says? Heuristic findings for review (the gauntlet reads them); they
        # are not problems a customer can fix, so they never change qa['ok'] or qa['problems'].
        from .qa import content as content_qa
        content = content_qa.check(cfg['plan_v3'], board, tl, video)
        qa['content'] = {'problems': content['problems'], 'findings': content['findings'], 'stats': content['stats']}
        motion = content_qa.motion(build / 'acts.json', tl)
        if motion is not None:
            qa['motion'] = motion
    publish(board, tl, lang, build, project_dir, stem, project_dir, own_voice=bool(cfg.get('recording')),
            voice_source=voice_server.describe(cfg['voice_server'], lang)
            if cfg.get('voice_server') and not cfg.get('recording') else None,
            size={'16:9': (1280, 720), '9:16': (720, 1280), '1:1': (720, 720)}[aspect])
    contact_sheet(tl, video, build / 'contact-sheet.jpg', size=size)
    qa.update({'video': str(video), 'length': clock(tl['duration'])})
    _save(build / 'qa.json', qa)
    return qa


def make(source, project_dir: Path, direct=None, progress=None, server: voice_server.Server | None = None,
         **settings_) -> dict:
    """Script to finished video. ``direct(project_dir)`` adds visuals to storyboard.json (rules or LLM); ``server``:
    your own voice server (see narrate)."""
    if not (Path(project_dir) / 'project.json').exists():
        new_project(source, project_dir, **settings_)
    if settings(project_dir).get('director_v3'):
        direct_v3(project_dir)
    elif direct:
        direct(project_dir)
    return produce(project_dir, progress, server)


def _hybrid(cfg):
    plan = cfg.get('plan_v3')
    return bool(cfg.get('director_v3') and plan and plan['style']['mode'] != 'whiteboard'
                and any(s['treatment'] != 'whiteboard' for s in plan['scenes']))


def _scored(cfg, board):
    """A v3 plan gets the planned score, its sound effects and the master: the hybrid looks, and the whiteboard ones
    too (before, an all-whiteboard plan fell back to music only on the end card)."""
    return _hybrid(cfg) or bool(cfg.get('director_v3') and cfg.get('plan_v3')
                                and styles.renderer(board.get('look')) == 'whiteboard')


def _narrated_pages(cfg, tl):
    """(start, end) of each story or motion page of a hybrid plan while its narration speaks: from the scene's first
    spoken word to its last. Whiteboard, chart and diagram scenes draw as they speak and get none."""
    if not _hybrid(cfg):
        return []
    pages = []
    for scene in cfg['plan_v3']['scenes']:
        beats = [tl['beats'][b] for b in scene['beat_ids'] if b in tl['beats']]
        if beats and scene['treatment'] not in ('whiteboard', 'chart') and not any(
                e['kind'] == 'diagram' for e in scene['elements']):
            pages.append((min(b['start'] for b in beats), max(b['speech_end'] for b in beats)))
    return pages


def _hybrid_audio(board, tl, build, cfg):
    """The planned score under the whole narration (only your choice of no music, storyboard music false, leaves it
    out: a plan's music_mood 'none' plays the calm score), the renderer's sound effects plus the everyday ones the
    words and actions name (audio.foley), held 12 dB under the voice in its gaps and on the end card (a calm score
    fading out there; audio.fit_bed), mastered."""
    from .audio import score, sfx, master, foley
    import numpy as np
    import zlib
    speech = audio.read_wav(audio.narration(tl, build))[0]
    style = cfg['plan_v3']['style']
    mood = 'calm' if style['music_mood'] == 'none' else style['music_mood']
    cues_path = build / 'cues.json'
    cues = _load(cues_path)['cues'] if cues_path.is_file() else []
    if board.get('sfx', True):
        words = foley.cues(tl, cfg['plan_v3'], cues)
        _save(build / 'foley.json', {'cues': words})            # for review: what was heard, when, and why
        cues = cues + words
    if board.get('music', True):
        track, _ = score.source(board.get('music'), mood, style['tempo_bpm'], build.parent)
        sections, marks = score.story_marks(board, tl, cues)
        result = score.render(tl['duration'], mood, style['tempo_bpm'], narration=speech,
                              ambient=True, seed=zlib.crc32(board['title'][cfg['lang']].encode('utf-8')),
                              track=track, sections=sections, marks=marks)  # each video its own variation
        bed = result.music
        _save(build / 'score.json', {'bpm': result.bpm, 'track': result.track, 'beats': result.beats.tolist(),
                                   'sections': sections, 'marks': marks})
    else:
        bed = np.zeros((len(speech), 2), np.float32)
    if cues and board.get('sfx', True):
        env = audio.envelope(speech.mean(axis=1))
        bed = bed + sfx.render(cues, tl['duration']) * (1 + (10 ** (audio.SFX_DUCK_DB / 20) - 1) * env)[:, None]
    out = speech + audio.fit_bed(speech, bed, tl, calm=mood == 'calm')    # 12 dB under the voice in gaps and after it
    out = master.master(out, audio.SR)
    path = build / 'mix.wav'
    audio.write_wav(path, out)
    return path


def _copy_project(source, target):
    source = Path(source)
    if any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('Linked project files cannot be rendered in scratch')
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('.studio'))


def _output_stem(board, cfg):
    stem = re.sub(r'[\\/:*?"<>|¿¡]+', '', board['title'][cfg['lang']]).strip()[:80] or 'video'
    stem += ' (vertical)' if cfg.get('aspect', '16:9') == '9:16' else ''
    sources = {Path(cfg[key]).name.casefold() for key in ('script', 'recording') if cfg.get(key)}
    candidate, number = stem, 1
    while any((candidate + suffix).casefold() in sources for suffix in
              ('.mp4', '.srt', '.vtt', '-chapters.txt', '-transcript.md', '-description.txt', '-thumbnail.png', '-sources.json')):
        candidate = stem + (' (video)' if number == 1 else f' (video {number})')
        number += 1
    return candidate


def _commit_outputs(stage, project, context):
    # Editable source files never flow back from a rendering scratch directory.
    stage, project = Path(stage), Path(project)
    cfg = _load(stage / 'project.json') if (stage / 'project.json').is_file() else {}
    excluded = {stage / 'project.json', stage / 'storyboard.json', stage / PRONOUNCE}
    for root in (stage, project):
        if (root / 'project.json').is_file():
            source_cfg = _load(root / 'project.json')
            for key in ('script', 'recording'):
                source = source_cfg.get(key)
                if source:
                    excluded.add(stage / source)
                    excluded.add(root / source)
    excluded = {path.resolve() for path in excluded}
    root_outputs = {READ_ALOUD}
    if (stage / 'storyboard.json').is_file():
        board = _load(stage / 'storyboard.json')
        # Older staged sidecars keep their original names. Sources are still
        # excluded individually below, even when they occupy a generated slot.
        stems = {_output_stem(board, cfg), _output_stem(board, {**cfg, 'script': None, 'recording': None})}
        root_outputs.update(stem + suffix for stem in stems for suffix in
            ('.mp4', '.srt', '.vtt', '-chapters.txt', '-transcript.md', '-description.txt', '-thumbnail.png', '-sources.json'))
    outputs = []
    for output in sorted(stage.rglob('*')):
        rel = output.relative_to(stage)
        if not output.is_file() or '.studio' in rel.parts:
            continue
        if rel.parts[0] not in ('build', 'voice') and (len(rel.parts) != 1 or rel.name not in root_outputs):
            continue
        target = project / rel
        if output.resolve() in excluded or target.resolve() in excluded:
            continue
        outputs.append((output, target))
    _publish_outputs(outputs, project, context)


def _publish_outputs(outputs, project, context):
    # Prepare on the destination filesystem, then replace under one cancel lock.
    # If publication itself fails, restore every output already replaced.
    with tempfile.TemporaryDirectory(prefix='.publish-', dir=project) as folder:
        folder = Path(folder)
        prepared = []
        for index, (output, target) in enumerate(outputs):
            target.parent.mkdir(parents=True, exist_ok=True)
            candidate, backup = folder / f'{index}.new', folder / f'{index}.old'
            shutil.copy2(output, candidate)
            if target.exists():
                shutil.copy2(target, backup)
            prepared.append((candidate, target, backup))
        committed = []
        with context.token._lock:
            context.token.check()
            try:
                for candidate, target, backup in prepared:
                    context.token.commit(candidate, target)
                    committed.append((target, backup))
            except BaseException:
                for target, backup in reversed(committed):
                    if backup.exists():
                        backup.replace(target)
                    else:
                        target.unlink()
                raise


def produce(project_dir, progress=None, server=None, *, context=None):
    """Make the saved editable project, staging outputs until all stages succeed."""
    project_dir = Path(project_dir)
    ctx = context or RenderContext()
    store = ProjectStore(project_dir)
    saved = store.load()
    ctx.token.check()
    with tempfile.TemporaryDirectory(prefix='make-') as folder:
        stage = Path(folder) / 'project'
        with store.locked():
            store._check(store._state(), saved['revision'])
            _copy_project(project_dir, stage)
        clips = narrate(stage, progress, server)
        if progress:
            progress('timeline', 0, 1)
        ctx.token.check()
        build_audio(stage, clips)
        if progress:
            progress('render', 0, 1)
        render(stage, context=ctx)
        if progress:
            progress('finish', 0, 1)
        qa = finish(stage, context=ctx)
        qa['video'] = str(project_dir / Path(qa['video']).name)
        _save(stage / 'build/qa.json', qa)   # failed checks publish too; the Studio lists them as warnings
        with store.locked():
            store._check(store._state(), saved['revision'])
            # Serialize the publication with cancellation: a late cancel after
            # a complete publication is a completed Make, never a partial cancel.
            with ctx.token._lock:
                ctx.token.check()
                _commit_outputs(stage, project_dir, ctx)
                ctx.published = True
        return qa


if __name__ == '__main__':
    if sys.argv[1:2] != ['--finish-worker']:
        raise SystemExit('Use the kinodraw CLI, or --finish-worker PROJECT')
    finish_worker(sys.argv[2:])

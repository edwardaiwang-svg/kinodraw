"""kinodraw: turn a script into a hand-drawn whiteboard video.

  kinodraw studio                               open the Studio window
  kinodraw make script.md -o MyVideo            script -> finished MP4 (offline rules director)
  kinodraw new script.md -o MyVideo             storyboard only (edit storyboard.json, then continue)
  kinodraw make script.md -o MyVideo --voice am_michael --speed 1.1 --pronounce words.txt
                                                ... another voice, faster, with your pronunciations
  kinodraw direct MyVideo                       (re)add visuals to the storyboard
  kinodraw voice MyVideo                        narration + timeline
  kinodraw voice MyVideo --recording me.m4a     ... narrated by your own reading of MyVideo/read-aloud.txt (none: Kokoro again)
  kinodraw render MyVideo [--stills 5,30]       silent video (or preview stills)
  kinodraw finish MyVideo                       music, mux, captions, chapters, QA
  kinodraw setup [--lang en zh]                 download the voice models once
  kinodraw doodles "rocket launch" [--lang en]  search the doodle library
  kinodraw login you@example.com                KinoDraw Cloud (free plan: AI-directed videos, no API key needed)
  kinodraw key set openai|anthropic|compat      store your own API key in the OS keychain
  kinodraw key set command                      store a command to use as the director (Advanced)

Directors: --director rules (offline, free) | cloud | openai | anthropic | compat (--base-url, --model)
           | command (runs your saved command; --model is passed to it)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _progress(stage, done, total):
    if stage.startswith('download'):                  # first run only: bytes of the voice or the doodle search
        text = f"downloading the {'voice' if stage == 'download-voice' else 'doodle search'}: " \
               f'{done / 1e6:.0f}/{total / 1e6:.0f} MB ({done * 100 // max(total, 1)}%)'
    else:
        text = f'{stage}: {done}/{total}'
    print(f'\r{text}', end='\n' if done == total else '', flush=True)


def _stage(name):
    print(f'• {name}…', flush=True)
    return time.time()


def _file(script):
    """The script file named on the command line, or None when ``script`` is the script's text itself."""
    try:
        return Path(script) if Path(script).is_file() else None
    except OSError:                                   # pasted text too long or odd to be a file name
        return None


def cmd_new(args):
    from . import director, pipeline, voice
    pronounce = getattr(args, 'pronounce', None)
    if pronounce:                                     # checked before anything is made
        try:
            voice.read_lexicon(Path(pronounce))
        except (OSError, ValueError) as error:
            sys.exit(f'--pronounce {pronounce}: {error}')
    t = _stage('storyboard')
    board = pipeline.new_project(_file(args.script) or args.script, Path(args.out),
                                 title=args.title, lang=args.lang, direction=_direction(args), **_settings(args))
    if pronounce:
        (Path(args.out) / pipeline.PRONOUNCE).write_text(Path(pronounce).read_text(encoding='utf-8'), encoding='utf-8')
    report = director.direct(Path(args.out), args.director, getattr(args, 'model', None), getattr(args, 'base_url', None),
                             _progress)
    sections = sum(c['kind'] == 'section' for c in board['chapters'])
    print(f"  {len(board['beats'])} beats, {sections} sections ({time.time() - t:.0f}s)")
    _report(report)


def cmd_voice(args):
    from . import pipeline
    project, recording = Path(args.project), getattr(args, 'recording', None)
    if recording and recording.lower() != 'none' and not Path(recording).is_file():
        sys.exit(f'{recording}: no such file')
    if recording:
        pipeline.set_recording(project, None if recording.lower() == 'none' else recording)
    t = _stage('voice')
    try:
        clips = pipeline.narrate(project, _progress)
    except pipeline.voice.RecordingError as error:      # a take that does not fit the script: say what to do
        sys.exit(f'\n{error}')
    tl = pipeline.build_audio(project, clips)
    print(f"  {tl['duration']:.0f}s of narration, {len(tl['captions'])} captions ({time.time() - t:.0f}s)")
    if pipeline.settings(project).get('recording'):
        report = json.loads((project / 'voice' / 'recording-align.json').read_text(encoding='utf-8'))
        print(f"  your recording: match {report['match']:.2f} (where each beat is: voice/recording-align.json)")
        lang = pipeline.settings(project)['lang']
        said = {beat['id']: beat['spoken'][lang] for beat in pipeline.storyboard(project)['beats']}
        again = f'record the script again, every sentence as written in {project / pipeline.READ_ALOUD}'
        for beat in report['beats']:
            if beat['check']:
                print(f"  ! {beat['id']} (\"{pipeline.voice._quote(said.get(beat['id'], ''))}\") sounds unlike its "
                      f"text ({beat['match']:.2f}). Watch that part of the video: if the pictures are out of step "
                      f"with your voice there, {again}.")
        poor = [(n, line['text']) for n, line in enumerate(report.get('sentences', []), 1) if line['check']]
        for n, text in poor:                          # numbered as in read-aloud.txt and the Studio's read-aloud page
            print(f"  ! sentence {n} of {pipeline.READ_ALOUD} (\"{pipeline.voice._quote(text)}\") didn't match your "
                  "recording: it may have been skipped or read differently.")
        if poor:
            print(f"  Watch those parts of the video: if the pictures are out of step with your voice there, {again}.")


def cmd_render(args):
    from . import pipeline
    project = Path(args.project)
    if args.stills:
        from .engine import render as renderer
        tl = json.loads((project / 'build' / 'timeline.json').read_text(encoding='utf-8'))
        cfg, board = pipeline.settings(project), pipeline.storyboard(project)
        aspect = pipeline.validate_aspect(cfg.get('aspect', '16:9'), board.get('look'))
        prod = renderer.make_production(board, tl, cfg['lang'], project, aspect=aspect)
        out = project / 'build' / 'stills'
        out.mkdir(parents=True, exist_ok=True)
        for s in args.stills.split(','):
            prod.frame(float(s)).convert('RGB').save(out / f'{float(s):07.2f}.png')
        print(f'  stills -> {out}')
        return
    t = _stage('render')
    out = pipeline.render(project, args.start, args.duration, args.workers)
    print(f'  done ({time.time() - t:.0f}s)')
    for w in json.loads((out.parent / 'render-warnings.json').read_text(encoding='utf-8')):
        if w.startswith('skipped'):
            print(f'  · {w}')


def cmd_finish(args):
    from . import pipeline
    t = _stage('finish')
    qa = pipeline.finish(Path(args.project))
    print(f"  {'PASS' if qa['ok'] else 'FAIL'} {qa['video']} ({qa['length']}) ({time.time() - t:.0f}s)")
    for p in qa['problems']:
        print('  !', p)
    if not qa['ok']:
        sys.exit(1)


def cmd_make(args):
    cmd_new(args)
    args.project = args.out
    cmd_voice(args)
    args.stills, args.start, args.duration = None, 0, None
    cmd_render(args)
    cmd_finish(args)


def _report(report):
    usage = report.get('usage')
    if usage:
        cost = f'${usage.cost_usd:.4f}' if usage.cost_usd is not None else 'cost unknown for this model'
        print(f'  AI director: {usage.calls} calls, {usage.input_tokens + usage.cached_tokens} in / '
              f'{usage.output_tokens} out tokens, {cost}')
    for note in report.get('notes', [])[:12]:
        print('  ·', note)


def cmd_direct(args):
    from . import director
    _report(director.direct(Path(args.project), args.mode, args.model, args.base_url, _progress))


def cmd_login(args):
    from .director.llm import cloud
    if not args.code:
        cloud.signup(args.email)
        print(f'  a 6-digit code was sent to {args.email}; run: kinodraw login {args.email} --code 123456')
        return
    info = cloud.verify(args.email, args.code)
    left = info.get('remaining')
    print(f"  signed in: {info.get('plan', 'free')} plan, "
          f"{'unlimited videos (fair use)' if left is None else f'{left} videos left this month'}")


def cmd_key(args):
    import getpass
    from .director.llm.providers import save_key
    if args.provider == 'command':
        save_key('command', input('command line: ').strip())
    else:
        save_key(args.provider, getpass.getpass(f'{args.provider} API key (hidden): ').strip())
    print('  saved to the OS keychain')


def cmd_studio(args):
    from .studio.app import main as studio
    studio(browser=args.browser, port=args.port)


def cmd_setup(args):
    from . import voice
    for lang in args.lang:
        voice.ensure_models(lang, lambda done, total: _progress('download-voice', done, total))
        print(f'{lang}: ready')


def cmd_doodles(args):
    from .director.match import Matcher
    m = Matcher(args.lang)
    hits = {h.id: h for h in m.lexical(args.query)}
    for h in m.semantic(args.query, 12):
        hits.setdefault(h.id, h)
    for h in sorted(hits.values(), key=lambda h: -h.score)[:12]:
        e = m.entries[h.id]
        print(f"{h.id:32s} {e['set']:8s} {e.get('desc', '')[:60]}")


def _settings(args):
    out = {}
    for key in ('voice', 'speed', 'workers', 'aspect'):
        if getattr(args, key, None) is not None:
            out[key] = getattr(args, key)
    if getattr(args, 'no_credit', False):
        out['credit'] = False
    return out


def _direction(args):
    brand = {key: getattr(args, arg, None)
             for key, arg in (('name', 'brand'), ('url', 'brand_url'), ('cta', 'brand_cta'))}
    return {**{key: getattr(args, key, None) for key in ('look', 'story', 'motion')},
            'brand': {k: v for k, v in brand.items() if v} or None}


MODES = ['rules', 'cloud', 'openai', 'anthropic', 'compat', 'command']


def main(argv=None):
    from . import paths
    from .pipeline import ASPECTS
    from .engine.storyboard import DIALS, LOOKS
    paths.migrate()                                   # once: Doodle Studio's folders become KinoDraw's
    if paths.left_behind:
        print(paths.NOT_MOVED, *(f'  still in {p}' for p in paths.left_behind), sep='\n', file=sys.stderr)
    ap = argparse.ArgumentParser(prog='kinodraw', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='command', required=True)
    for name, fn in (('make', cmd_make), ('new', cmd_new)):
        p = sub.add_parser(name)
        p.add_argument('script', help='a .md/.txt/.docx file, or the text itself in quotes')
        p.add_argument('-o', '--out', required=True, help='project folder to create')
        p.add_argument('--title')
        p.add_argument('--lang', choices=['en', 'zh'], help='default: detected from the script')
        p.add_argument('--voice')
        p.add_argument('--speed', type=float)
        p.add_argument('--pronounce', metavar='FILE', help='how the voice says words, one "word = how to say it" a '
                       'line (captions keep your spelling); kept as the project\'s pronounce.txt')
        p.add_argument('--workers', type=int, help='parallel render processes (default 2)')
        p.add_argument('--aspect', choices=ASPECTS, default='16:9',
                       help='16:9 for YouTube (default) or 9:16 for Shorts, TikTok and Reels')
        p.add_argument('--no-credit', action='store_true', help='end without the 2-second "Made with ..." credit')
        p.add_argument('--director', default='rules', choices=MODES)
        p.add_argument('--look', choices=LOOKS, help='visual style (default whiteboard)')
        p.add_argument('--story', choices=DIALS['story'], help='story shape (default explain)')
        p.add_argument('--motion', choices=DIALS['motion'],
                       help='how lively a collage video moves (default lively; the whiteboard ignores it)')
        p.add_argument('--brand', help='a promo\'s product name, as it should appear (default: from the script)')
        p.add_argument('--brand-url', help='a promo\'s website, for the end card (default: from the script)')
        p.add_argument('--brand-cta', help='a promo\'s button text, e.g. "Try it for free" (default: from the script)')
        p.add_argument('--model')
        p.add_argument('--base-url')
        p.set_defaults(func=fn)
    p = sub.add_parser('direct')
    p.add_argument('project')
    p.add_argument('--mode', default='rules', choices=MODES)
    p.add_argument('--model')
    p.add_argument('--base-url')
    p.set_defaults(func=cmd_direct)
    p = sub.add_parser('login')
    p.add_argument('email')
    p.add_argument('--code')
    p.set_defaults(func=cmd_login)
    p = sub.add_parser('key')
    p.add_argument('action', choices=['set'])
    p.add_argument('provider', choices=['openai', 'anthropic', 'compat', 'command'])
    p.set_defaults(func=cmd_key)
    p = sub.add_parser('studio')
    p.add_argument('--browser', action='store_true', help='use the web browser instead of a window')
    p.add_argument('--port', type=int, default=0)
    p.set_defaults(func=cmd_studio)
    p = sub.add_parser('voice')
    p.add_argument('project')
    p.add_argument('--recording', help='your own reading of the whole script as the project\'s read-aloud.txt says it '
                                       '(the voice step writes it), in one take (wav, m4a, mp3, aiff), or "none" to '
                                       'go back to the Kokoro voice')
    p.set_defaults(func=cmd_voice)
    p = sub.add_parser('render')
    p.add_argument('project')
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--duration', type=float)
    p.add_argument('--workers', type=int)
    p.add_argument('--stills')
    p.set_defaults(func=cmd_render)
    p = sub.add_parser('finish')
    p.add_argument('project')
    p.set_defaults(func=cmd_finish)
    p = sub.add_parser('setup')
    p.add_argument('--lang', nargs='+', default=['en', 'zh'], choices=['en', 'zh'])
    p.set_defaults(func=cmd_setup)
    p = sub.add_parser('doodles')
    p.add_argument('query')
    p.add_argument('--lang', default='en', choices=['en', 'zh'])
    p.set_defaults(func=cmd_doodles)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()

"""kinodraw: turn a script into a hand-drawn whiteboard video.

  kinodraw studio                               open the Studio window
  kinodraw make script.md -o MyVideo            script -> finished MP4 (offline rules director)
  kinodraw new script.md -o MyVideo             storyboard only (edit storyboard.json, then continue)
  kinodraw direct MyVideo                       (re)add visuals to the storyboard
  kinodraw voice MyVideo                        narration + timeline
  kinodraw render MyVideo [--stills 5,30]       silent video (or preview stills)
  kinodraw finish MyVideo                       music, mux, captions, chapters, QA
  kinodraw setup [--lang en zh]                 download the voice models once
  kinodraw doodles "rocket launch" [--lang en]  search the doodle library
  kinodraw login you@example.com                Doodle Cloud (free plan: AI-directed videos, no API key needed)
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


def cmd_new(args):
    from . import director, pipeline
    t = _stage('storyboard')
    board = pipeline.new_project(Path(args.script) if Path(args.script).is_file() else args.script, Path(args.out),
                                 title=args.title, lang=args.lang, **_settings(args))
    report = director.direct(Path(args.out), args.director, getattr(args, 'model', None), getattr(args, 'base_url', None),
                             _progress)
    sections = sum(c['kind'] == 'section' for c in board['chapters'])
    print(f"  {len(board['beats'])} beats, {sections} sections ({time.time() - t:.0f}s)")
    _report(report)


def cmd_voice(args):
    from . import pipeline
    t = _stage('voice')
    clips = pipeline.narrate(Path(args.project), _progress)
    tl = pipeline.build_audio(Path(args.project), clips)
    print(f"  {tl['duration']:.0f}s of narration, {len(tl['captions'])} captions ({time.time() - t:.0f}s)")


def cmd_render(args):
    from . import pipeline
    project = Path(args.project)
    if args.stills:
        from .engine import render as renderer
        tl = json.loads((project / 'build' / 'timeline.json').read_text(encoding='utf-8'))
        prod = renderer.Production(pipeline.storyboard(project), tl, pipeline.settings(project)['lang'], project)
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
    for key in ('voice', 'speed', 'workers'):
        if getattr(args, key, None) is not None:
            out[key] = getattr(args, key)
    if getattr(args, 'no_credit', False):
        out['credit'] = False
    return out


MODES = ['rules', 'cloud', 'openai', 'anthropic', 'compat', 'command']


def main(argv=None):
    from . import paths
    paths.migrate()                                   # once: Doodle Studio's folders become KinoDraw's
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
        p.add_argument('--workers', type=int, help='parallel render processes (default 2)')
        p.add_argument('--no-credit', action='store_true', help='end without the 2-second "Made with ..." credit')
        p.add_argument('--director', default='rules', choices=MODES)
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

"""Content QA: does the video show what its script says?

Four checks on a v3 plan (and, for the frozen composition, the finished video), reported in plain words in
qa.json's ``content`` (never in its problems or ok: they are heuristics for review, not customer problems):

- ``unshown``: more than UNSHOWN of the sentences that name something concrete (a person, place, object or sky)
  have nothing in their scene that matches it.
- ``same_picture``: one composition stays on screen for more than SAME_RUN sentences in a row (measured on the
  video's frames at each sentence's middle, the caption band left out).
- ``no_people``: a story names people but no scene puts anyone on screen.
- ``no_speaker``: a story has dialogue but more than half of its lines show no speaker.

English scripts only (the readings are English word lists); other languages get no content findings.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass

import numpy as np

UNSHOWN = .2              # share of concrete sentences allowed to show nothing they name
MIN_CONCRETE = 3          # fewer concrete sentences than this are too few to judge
SAME_RUN = 2              # more sentences than this in a row on one unchanged picture is a frozen composition
SAME_PIXELS = .02         # a composition changed when more than this share of the picture area changed
UNSPOKEN = .5             # share of dialogue lines allowed without their speaker on screen
CAPTION_BAND = .78        # the caption sits below this share of the frame height; the picture is above it


@dataclass
class Line:
    beat: str
    start: int            # char offsets in the beat's spoken text
    end: int
    text: str
    scene: int
    concrete: bool = False
    shown: bool = False
    dialogue: bool = False
    speaker_shown: bool = False
    at: float | None = None     # seconds: the sentence's middle in the video


def _spoken(board, lang):
    def text(value):
        return value.get(lang, next(iter(value.values()), '')) if isinstance(value, dict) else value or ''
    return {b['id']: text(b.get('spoken', b.get('display', ''))) for b in board['beats']}


def lines(plan, board, timeline=None) -> list[Line]:
    """Every narrated sentence with what its scene shows of it."""
    from ..director.v3.semantics import beats, mentions
    from ..director.v3.staging import people, read_text, tie
    from ..director.v3.story import Reader
    lang = board.get('lang', 'en')
    spoken = _spoken(board, lang)
    script = beats(board)
    cast = plan.get('cast') or []
    story = (plan.get('storyboard') or {}).get('genre') == 'story'
    # People the script names whom the plan may have left out: still people a sentence is about.
    missing = people(script, cast) if story else []
    person_words = [c['name'] for c in cast + missing]
    reader = Reader(cast)
    out, place = [], None
    for index, scene in enumerate(plan['scenes']):
        staged = {e['ref'] for e in scene['elements'] if e['kind'] == 'cast'}
        pictures = [e['ref'] for e in scene['elements'] if e['kind'] == 'picture']
        for bid in scene['beat_ids']:
            text = spoken.get(bid, '')
            read = reader.read(bid, text)
            staging = read_text(text, place)
            if staging:
                place = staging[-1].place
            shares = tie([s.text for s in staging], pictures)
            for k, s in enumerate(staging):
                sentence = next((r for r in read if r.start <= s.start < r.end), None)
                line = Line(bid, s.start, s.end, s.text, index)
                if not story:
                    # An explainer, promo or lesson shows its sentences in its own ways (drawings on the word,
                    # kinetic type, charts): it only fails when a scene shows nothing at all.
                    line.concrete = bool(re.search(r'\w', s.text))
                    line.shown = bool(scene['elements']) or scene['treatment'] in ('kinetic_type', 'chart') or \
                        scene['text']['kind'] in ('kinetic', 'title', 'quote', 'counter', 'cta')
                else:
                    # Someone the sentence itself names or points to (not merely still standing on the page).
                    refs = {r[1] for r in reader.references(s.text, [])} if sentence else set()
                    named = [w for w in person_words if mentions(w, s.text)]
                    present = (set(sentence.present) & refs) if sentence else set()
                    drawable = bool(s.objects or s.named_place or s.sky)
                    line.concrete = bool(named or present or drawable)
                    line.shown = bool(any(e['kind'] == 'diagram' for e in scene['elements']) or (present & staged) or
                                      any(mentions(c['name'], s.text) for c in cast if c['id'] in staged) or
                                      any(p in shares[k] and _named(p, s.text) for p in pictures) or
                                      s.sky)          # the storybook draws the sky the words name
                quoted = bool(sentence and sentence.quotes)
                label = re.match(r'\s*\[?([A-Z][A-Z]+(?: [A-Z][A-Z]+)?)\]?\s*:', s.text)
                line.dialogue = quoted or bool(label)
                if line.dialogue:
                    who = ({c['id'] for c in cast if mentions(c['name'], label[1])} if label else
                           {sentence.speaker} - {None})
                    line.speaker_shown = bool(who & staged)
                if timeline and bid in (timeline.get('beats') or {}):
                    beat = timeline['beats'][bid]
                    times = beat.get('char_times') or []
                    if times:
                        a = times[min(s.start, len(times) - 1)]
                        b = times[min(max(s.start, s.end - 1), len(times) - 1)]
                        line.at = beat['start'] + (a + b) / 2
                out.append(line)
    return out


def _named(doodle, text):
    from ..director.v3.staging import names
    return names(doodle, text)


def _frames(video, times, width=160, height=90):
    """Gray frames (height x width) at the given seconds, in one decode at 10 frames per second."""
    from .probes import FFMPEG
    command = [FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(video), '-an',
               '-vf', f'fps=10,scale={width}:{height}', '-pix_fmt', 'gray', '-f', 'rawvideo', '-']
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, height, width)
    return [frames[min(len(frames) - 1, max(0, int(round(t * 10))))].astype(np.int16) for t in times]


def same_runs(video, timed: list[Line]) -> list[tuple[int, int]]:
    """Runs (first, last index into ``timed``) of more than SAME_RUN sentences on one unchanged picture."""
    if not timed:
        return []
    frames = _frames(video, [line.at for line in timed])
    band = int(frames[0].shape[0] * CAPTION_BAND)
    runs, first = [], 0
    for i in range(1, len(frames) + 1):
        changed = i == len(frames) or np.mean(np.abs(frames[i][:band] - frames[first][:band]) > 24) > SAME_PIXELS
        if changed:
            if i - first > SAME_RUN:
                runs.append((first, i - 1))
            first = i
    return runs


def check(plan, board, timeline=None, video=None) -> dict:
    """{'problems': [plain-word problems], 'findings': [...], 'stats': {...}} for a plan and its video."""
    from ..package import clock
    if board.get('lang', 'en') != 'en':
        # The readings (places, objects, people, sentences) are English word lists.
        return {'problems': [], 'findings': [], 'stats': {'skipped': f'language {board.get("lang")}'}, 'lines': []}
    found = lines(plan, board, timeline)
    findings = []
    concrete = [line for line in found if line.concrete]
    unshown = [line for line in concrete if not line.shown]
    share = len(unshown) / max(1, len(concrete))
    if len(concrete) >= MIN_CONCRETE and share > UNSHOWN:
        example = unshown[0]
        findings.append({'check': 'unshown', 'share': round(share, 3), 'at': example.at,
                         'problem': f'{share:.0%} of the sentences that name something show nothing it names '
                                    f'(more than {UNSHOWN:.0%}), for example '
                                    f'{_when(example, clock)}"{_short(example.text)}".'})
    story = (plan.get('storyboard') or {}).get('genre') == 'story'
    if story:
        from ..director.v3.semantics import beats
        from ..director.v3.staging import people
        named = (plan.get('cast') or []) + people(beats(board), plan.get('cast') or [])
        on_screen = any(e['kind'] == 'cast' for s in plan['scenes'] for e in s['elements'])
        if named and not on_screen:
            findings.append({'check': 'no_people', 'problem': 'The story names people ('
                             + ', '.join(c['name'] for c in named[:4]) + ') but nobody is ever on screen.'})
    # A promo's quotes are often a button or a notification ("Tap "What can I make?""), not a character speaking.
    dialogue = [line for line in found if line.dialogue] if story else []
    silent = [line for line in dialogue if not line.speaker_shown]
    if dialogue and len(silent) / len(dialogue) > UNSPOKEN:
        example = silent[0]
        findings.append({'check': 'no_speaker', 'share': round(len(silent) / len(dialogue), 3), 'at': example.at,
                         'problem': f'{len(silent)} of {len(dialogue)} spoken lines show no speaker on screen, for '
                                    f'example {_when(example, clock)}"{_short(example.text)}".'})
    runs = []
    if video is not None:
        timed = [line for line in found if line.at is not None]
        for a, b in same_runs(video, timed):
            runs.append((timed[a], timed[b], b - a + 1))
        if runs:
            first, last, count = max(runs, key=lambda r: r[2])
            findings.append({'check': 'same_picture', 'runs': len(runs), 'longest': count, 'at': first.at,
                             'problem': f'The picture does not change for {count} sentences in a row '
                                        f'(from {clock(first.at)} "{_short(first.text)}" to {clock(last.at)}); '
                                        f'{len(runs)} such stretch{"es" if len(runs) > 1 else ""} in the video.'})
    return {'problems': [f['problem'] for f in findings], 'findings': findings,
            'stats': {'sentences': len(found), 'concrete': len(concrete), 'unshown': len(unshown),
                      'dialogue': len(dialogue), 'dialogue_unshown': len(silent),
                      'same_runs': [(clock(a.at), clock(b.at), n) for a, b, n in runs]},
            'lines': [asdict(line) for line in found]}


def _when(line, clock):
    return f'at {clock(line.at)} ' if line.at is not None else ''


def _short(text, words=9):
    parts = text.split()
    return ' '.join(parts[:words]) + ('…' if len(parts) > words else '')

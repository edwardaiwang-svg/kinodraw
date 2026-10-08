"""Content QA: does the video show what its script says?

Four checks on a v3 plan (and, for the frozen composition, the finished video), reported in plain words in
qa.json's ``content`` (never in its problems or ok: they are heuristics for review, not customer problems):

- ``unshown``: more than UNSHOWN of the sentences that name something concrete (a person, place, object or sky)
  have nothing in their scene that matches it. A picture matches only when a word of the sentence names it in the
  sense the sentence uses that word (director.v3.offer.Sense: "jump three" is no kangaroo, "the order" no menu
  icon); with the video, the thing shown must also be readable: at the sentence's middle and end its drawing covers
  at least READABLE of the frame (the bounding box of the largest drawn shape that the sentence brought on, else of
  the largest one on screen; a board diagram or a page is measured whole), written words at least READABLE_TEXT.
  The drawing hand and a title tag along the top are never what a sentence shows.
- ``numbers_as_icons``: a sentence with numbers or a comparison (an explainer's revenue, a lesson's "3 times 5") is
  shown only by an icon, with no board, chart, counter or data card (kinodraw/figures.py: the renderer draws the
  figures a sentence states) to show the numbers themselves.
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
# A drawing covers at least this share of the frame (its bounding box) to count as shown. Measured 10/8 on the
# gauntlet renders: the pancake video's ingredient icons that its critic called unreadable box 1.6-2.3% of the frame;
# the lesson's kangaroo and menu icons 3-5%; story pages and board diagrams 5-30%.
READABLE = .03
# Written words read smaller: the lesson's board line "a + b = b + a" boxes 1.5% of the frame and reads at 1080p,
# while the three starting dots of its dot array (0.4% each) show no sentence yet.
READABLE_TEXT = .01
HAND_SKIN = .002          # the drawing hand's skin is one solid blob of at least this share of the picture area
HAND_REACH = .04          # the pen reaches this share of the frame width beyond the drawing hand's skin
TITLE_STRIP = .12         # a mark on nearly every frame within this top share of the frame is the video's title tag
INK = 48                  # a pixel is drawn when a colour channel differs from the paper by more than this
NUMERIC = re.compile(r"\d|%|\$|£|€|\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|"
                     r"thirty|forty|fifty|hundred|thousand|million|billion|percent|half|twice|double|triple|dozen)\b|"
                     r"\b(?:more|less|fewer|higher|lower|bigger|smaller)\s+than\b|\bcompared\s+(?:to|with)\b",
                     re.I)
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
    until: float | None = None  # seconds: its end
    numeric: bool = False       # it gives numbers or a comparison
    by: str = ''                # what shows it: board, chart, card, text, cast, sky, picture or '' (nothing)
    size: float | None = None   # share of the frame its drawing covers (with the video)


def _spoken(board, lang):
    def text(value):
        return value.get(lang, next(iter(value.values()), '')) if isinstance(value, dict) else value or ''
    # a code block (markup.py) is shown, never said: its lines are not narrated sentences
    return {b['id']: '' if (b.get('markup') or {}).get('kind') == 'code' else
            text(b.get('spoken', b.get('display', ''))) for b in board['beats']}


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
    sense = _sense(lang, [spoken.get(b['id'], '') for b in board['beats']])
    out, place = [], None
    cards = _card_spans(board, lang, spoken)
    for index, scene in enumerate(plan['scenes']):
        staged = {e['ref'] for e in scene['elements'] if e['kind'] == 'cast'}
        pictures = [e['ref'] for e in scene['elements'] if e['kind'] == 'picture']
        # A picture no sentence of the scene names is the planner's own choice: it stands for every sentence. One a
        # sentence names stands for the sentences that name it in its sense ("jump three" names no kangaroo).
        texts = [spoken.get(bid, '') for bid in scene['beat_ids']]
        free = [p for p in pictures if all(sense.judge(p, t) is None for t in texts)]
        drawn = [b for b in scene['beat_ids']]                 # board items persist to the end of their scene
        board_beats = {item.get('beat_id') for board_ in scene.get('boards') or [] for item in board_.get('items') or []}
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
                line.numeric = bool(NUMERIC.search(s.text))
                named_here = [p for p in pictures if sense.judge(p, s.text)]
                on_board = bool(board_beats & set(drawn[:drawn.index(bid) + 1]))
                if not story:
                    # An explainer, promo or lesson shows its sentences in its own ways: a board diagram, a chart, a
                    # counter, its words as type, or a picture its words name in their sense (or the planner's own
                    # choice for the scene). Numbers need more than an icon.
                    line.concrete = bool(re.search(r'\w', s.text))
                    data = scene['treatment'] == 'chart' or scene['text']['kind'] == 'counter'
                    words = scene['treatment'] == 'kinetic_type' or \
                        scene['text']['kind'] in ('kinetic', 'title', 'quote', 'cta')
                    card = any(s.start <= at < s.end for at in cards.get(bid, ()))
                    line.by = ('board' if on_board else 'chart' if data else 'card' if card else
                               'picture' if named_here or free else 'text' if words else '')
                    line.shown = bool(line.by) and not (line.numeric and line.by == 'text')
                else:
                    # Someone the sentence itself names or points to (not merely still standing on the page).
                    refs = {r[1] for r in reader.references(s.text, [])} if sentence else set()
                    named = [w for w in person_words if mentions(w, s.text)]
                    present = (set(sentence.present) & refs) if sentence else set()
                    drawable = bool(s.objects or s.named_place or s.sky)
                    line.concrete = bool(named or present or drawable)
                    people = (present & staged) or any(mentions(c['name'], s.text) for c in cast if c['id'] in staged)
                    line.by = ('board' if on_board or any(e['kind'] == 'diagram' for e in scene['elements']) else
                               'cast' if people else
                               'picture' if any(p in shares[k] for p in named_here) else
                               'sky' if s.sky else '')   # the storybook draws the sky the words name
                    line.shown = bool(line.by)
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
                        line.until = beat['start'] + b
                out.append(line)
    return out


def _card_spans(board, lang, spoken):
    """{beat id: spoken offsets where a data card (kinodraw/figures.py) starts}: the renderer draws those figures."""
    from .. import figures
    out = {}
    for b in board['beats']:
        display = b.get('display')
        text = display.get(lang, '') if isinstance(display, dict) else str(display or '')
        said = spoken.get(b['id'], '')
        found = figures.beat_cards(b, lang) if said else []
        if found:
            out[b['id']] = [figures.spoken_offset(text, said, c.start, lang) for c in found]
    return out


def _sense(lang, texts):
    from ..director.v3.offer import Offer
    return Offer(lang, texts=texts).sense


def _frames(video, times, width=160, height=90):
    """Gray frames (height x width) at the given seconds, in one decode at 10 frames per second."""
    from .probes import FFMPEG
    command = [FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(video), '-an',
               '-vf', f'fps=10,scale={width}:{height}', '-pix_fmt', 'gray', '-f', 'rawvideo', '-']
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, height, width)
    return [frames[min(len(frames) - 1, max(0, int(round(t * 10))))].astype(np.int16) for t in times]


def readable(video, found: list[Line]) -> None:
    """Measure what each timed, shown sentence draws (``size``); one drawn smaller than READABLE shows nothing.

    Drawn = a colour channel off the paper by more than INK, above the caption band, at both the sentence's middle
    and near its end (a drawing hand passing through is in only one of them), and not on nearly every frame (a title
    tag or logo). Shapes closer than a few pixels are one drawing (a grid of dots, a word). A picture is measured by
    what the sentence brought on, when it brought anything; a board, a page, a chart or words by everything drawn."""
    from scipy import ndimage
    timed = [line for line in found if line.shown and line.at is not None]
    if not timed:
        return
    times = []
    for line in timed:
        end = line.until if line.until is not None else line.at
        times.append((line, (max(0., line.at - (end - line.at) - .1), line.at, max(line.at, end - .05))))
    frames = _colour_frames(video, [t for _, ts in times for t in ts])
    if not frames:
        return
    band = int(next(iter(frames.values())).shape[0] * CAPTION_BAND)

    inks = {i: _ink(f, band) for i, f in frames.items()}
    area = band / CAPTION_BAND * next(iter(frames.values())).shape[1]

    def boxes(mask):
        labels, _ = ndimage.label(ndimage.binary_dilation(mask, iterations=3))
        return labels, [(b, (b[0].stop - b[0].start) * (b[1].stop - b[1].start) / area)
                        for b in ndimage.find_objects(labels) if b]

    def largest(mask):
        return max((share for _, share in boxes(mask)[1]), default=0)

    # A small mark on nearly every frame, or one along the top, is a title tag or a logo, not what a sentence shows.
    overlay = np.zeros_like(next(iter(inks.values())))
    if len(inks) >= 8:
        labels, found = boxes(np.mean(list(inks.values()), axis=0) > .9)
        for k, (box, share) in enumerate(found, 1):
            if share < READABLE or box[0].stop <= TITLE_STRIP * band / CAPTION_BAND:
                overlay[box] = True                    # the whole box: its anti-aliased edges flicker

    for line, (t0, t1, t2) in times:
        before, middle, end = (inks[_frame_index(t)] for t in (t0, t1, t2))
        kept = middle & end & ~overlay
        new = kept & ~ndimage.binary_dilation(before, iterations=1)
        line.size = round(largest(new if line.by == 'picture' and new.mean() > .003 else kept), 4)
        if line.size < (READABLE_TEXT if line.by in WRITTEN else READABLE):
            line.shown = False


def _ink(frame, band):
    """Drawn pixels above the caption band: a colour channel off the paper by more than INK, without the drawing
    hand (its skin is warm and light, no ink colour) and the pen and shadow within HAND_REACH of it."""
    from scipy import ndimage
    region = frame[:band]
    paper = np.median(region.reshape(-1, 3), axis=0)
    drawn = np.abs(region - paper).max(axis=2) > INK
    r, g, b = region[..., 0], region[..., 1], region[..., 2]
    skin = drawn & (r > g) & (g > b) & (r > 150) & (b > 90) & (r - b > 25)
    # Solid only: the soft edges of a red, orange or yellow drawing blend to skin tones in thin rings.
    skin = ndimage.binary_opening(skin, iterations=2)
    labels, count = ndimage.label(skin)
    if count:
        sizes = ndimage.sum(skin, labels, range(1, count + 1))
        hand = np.isin(labels, 1 + np.flatnonzero(sizes >= HAND_SKIN * skin.size))
        if hand.any():
            drawn &= ~ndimage.binary_dilation(hand, iterations=round(HAND_REACH * frame.shape[1]))
    return drawn


WRITTEN = ('board', 'text', 'chart', 'card')     # a sentence shown in words, a board, a chart or a data card


def _frame_index(t):
    return max(0, int(round(t * 10)))


def _colour_frames(video, times, width=320, height=180):
    """{frame index at 10 per second: RGB frame} for the given seconds, in one decode."""
    from .probes import FFMPEG
    wanted = sorted({_frame_index(t) for t in times})
    pick = '+'.join(f'eq(n\\,{i})' for i in wanted)
    command = [FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-threads', '2', '-i', str(video), '-an',
               '-vf', f"fps=10,select='{pick}',scale={width}:{height}", '-vsync', '0', '-pix_fmt', 'rgb24',
               '-f', 'rawvideo', '-']
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3).astype(np.int16)
    last = frames[-1] if len(frames) else None
    return {i: (frames[k] if k < len(frames) else last) for k, i in enumerate(wanted)} if last is not None else {}


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
    if video is not None:
        readable(video, found)
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
    icons = [line for line in found if line.numeric and line.by == 'picture'] if not story else []
    if icons:
        example = icons[0]
        findings.append({'check': 'numbers_as_icons', 'count': len(icons), 'at': example.at,
                         'problem': f'{len(icons)} sentence{"s" if len(icons) > 1 else ""} with numbers or a comparison '
                                    f'{"are" if len(icons) > 1 else "is"} shown only by an icon (no board, chart or '
                                    f'counter), for example {_when(example, clock)}"{_short(example.text)}".'})
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
    from .screens import check as blank_screens
    findings += blank_screens(board, video)        # a message or notification read over a blank device
    return {'problems': [f['problem'] for f in findings], 'findings': findings,
            'stats': {'sentences': len(found), 'concrete': len(concrete), 'unshown': len(unshown),
                      'too_small': sum(1 for line in found if line.size is not None and
                                       line.size < (READABLE_TEXT if line.by in WRITTEN else READABLE)),
                      'numbers_as_icons': len(icons),
                      'dialogue': len(dialogue), 'dialogue_unshown': len(silent),
                      'same_runs': [(clock(a.at), clock(b.at), n) for a, b, n in runs]},
            'lines': [asdict(line) for line in found]}


def _when(line, clock):
    return f'at {clock(line.at)} ' if line.at is not None else ''


def _short(text, words=9):
    parts = text.split()
    return ' '.join(parts[:words]) + ('…' if len(parts) > words else '')


def motion(path, timeline=None) -> dict | None:
    """Movement verbs whose actor shows no movement on its story page (build/acts.json from engine.acting): a
    finding per verb ("Pip tiptoed" with Pip standing still or not on the page), never a problem. None without the
    file (no story pages)."""
    import json
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        return None
    acted = json.loads(path.read_text(encoding='utf-8'))
    starts = {bid: b['start'] for bid, b in ((timeline or {}).get('beats') or {}).items()}
    findings = []
    for a in acted:
        if a.get('shown'):
            continue
        when = starts.get(a['beat'])
        at = f' (beat {a["beat"]}' + (f', about {when:.0f} s)' if when is not None else ')')
        findings.append(f'"{a["word"]}": {a["actor"] or "someone"} does not move on screen{at}.')
    return {'findings': findings, 'stats': {'verbs': len(acted), 'shown': sum(1 for a in acted if a.get('shown'))}}


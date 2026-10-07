"""Offline story videos are picture books: preset doodles on the whiteboard paper (J, 2026-10-07)."""
import json
import re

import numpy as np
import pytest

from kinodraw import ingest, pipeline, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline

STORY = ('# The Quiet Cub\n\n'
         'Deep in the jungle lived King Kojo. His mane was dark as wet bark. Beside him ruled Queen Mara.\n\n'
         'And then there was Pendo, their only cub. The young monkeys teased him from the branches.\n\n'
         'Kojo would sigh and say, "Roar louder, son. A king must be heard."\n\n'
         'The king was silent. Then he looked at his son, really looked, and saw no fear in Pendo\'s eyes.\n\n'
         'Mara walked at the back, carrying the slowest little ones by the scruff.\n\n'
         'By dawn, the valley below was a churning brown lake.')


def production(tmp_path, text=STORY, explain=False):
    board = script.build(ingest.read(text), story='explain' if explain else 'story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    return render.make_production(board, tl, 'en', tmp_path), board, plan, tl


def span_of(prod, words):
    return next(s for s in prod.spans if words in ' '.join(prod.by_id[b]['spoken'] for b in s.spec['beat_ids']))


def shot_of(span, prod, words):
    """The shot narrating these words and its span-local start."""
    beat = next(b for b in span.spec['beat_ids'] if words in prod.by_id[b]['spoken'])
    timing = prod.tl['beats'][beat]
    char = prod.by_id[beat]['spoken'].index(words)
    at = timing['start'] - span.start + timing['char_times'][min(char, len(timing['char_times']) - 1)]
    return next(s for s in reversed(span.story) if s.start <= at + 1e-6), at


def pages(project, board):
    """(span, shot) for every storybook page of a saved project's production."""
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', project)
    prod.frame(0.)
    return [(span, shot) for span in prod.spans if span.story for shot in span.story]


class Pastes:
    """Record every doodle the storybook pastes (id, screen box) while composing real frames."""
    def __init__(self, monkeypatch):
        from kinodraw.engine import storybook
        self.calls = []
        original = storybook.Storybook._paste

        def paste(book, overlay, doodle, mirror, x, ground, height, cam, **kw):
            box = original(book, overlay, doodle, mirror, x, ground, height, cam, **kw)
            self.calls.append((doodle, box, height))
            return box
        monkeypatch.setattr(storybook.Storybook, '_paste', paste)


def test_story_plan_has_one_title_and_no_agenda_or_part_cards(tmp_path):
    # The Studio's look menu creates every whiteboard project with the explainer skeleton.
    pipeline.new_project(STORY, tmp_path, director_v3=True)
    assert any(b['kind'] == 'agenda' for b in pipeline.storyboard(tmp_path)['beats'])
    pipeline.direct_v3(tmp_path, provider='rules')
    board, plan = pipeline.storyboard(tmp_path), pipeline.settings(tmp_path)['plan_v3']
    assert plan['storyboard']['genre'] == 'story'
    assert {b['kind'] for b in board['beats']} == {'narration'}
    spoken = ' '.join(b['spoken']['en'] for b in board['beats'])
    assert not re.search(r"\bToday:|Here's what we'll cover|\bPart (?:one|two|1|2)\b|Key takeaway|Thanks for watching",
                         spoken)
    told = re.sub(r'\W+', ' ', ' '.join(b['display']['en'] for b in board['beats']))
    for sentence in re.findall(r'[^.!?"]+', STORY.split('\n\n', 1)[1]):
        assert re.sub(r'\W+', ' ', sentence).strip() in told, sentence      # no source words lost
    assert all(s['text']['kind'] == 'caption_only' for s in plan['scenes'])
    titles = [(span, shot) for span, shot in pages(tmp_path, board) if shot.title]
    assert len(titles) == 1 and titles[0][1].title == 'The Quiet Cub'
    assert titles[0][0].start == 0 and titles[0][1].start == 0          # once, on the first page


def test_story_titled_by_its_first_line_shows_no_title_card(tmp_path):
    text = 'Deep in the jungle lived King Kojo. His mane was dark.\n\nAnd then there was Pendo, their only cub.'
    pipeline.new_project(text, tmp_path, director_v3=True)
    pipeline.direct_v3(tmp_path, provider='rules')
    assert not [shot for _, shot in pages(tmp_path, pipeline.storyboard(tmp_path)) if shot.title]


def test_story_look_is_the_whiteboard_paper(tmp_path):
    prod, board, plan, tl = production(tmp_path)
    background = plan['style']['palette']['background']
    assert sum(int(background[i:i + 2], 16) for i in (1, 3, 5)) / 3 > 220
    for span in prod.spans:
        frame = np.asarray(prod.frame(span.start + .9 * (span.end - span.start)), np.float32)
        corner = frame[:80, :80].mean(axis=(0, 1))
        assert corner.min() > 200, (span.spec['beat_ids'], corner)          # never the dark night sky
        assert frame[:int(.78 * frame.shape[0])].std() > 12, span.spec['beat_ids']   # never an empty page


def test_night_in_a_story_is_a_moon_doodle_not_a_dark_sky(tmp_path, monkeypatch):
    text = '# Night\n\nThat night, under the stars, King Kojo walked home. Pendo, his cub, slept.'
    pastes = Pastes(monkeypatch)
    prod, board, plan, tl = production(tmp_path, text)
    frame = np.asarray(prod.frame(prod.spans[0].start + 1.), np.float32)
    assert frame[:200].mean() > 200
    assert 'fl_crescent_moon' in [d for d, _, _ in pastes.calls]


def test_library_doodles_keep_their_colours_in_hybrid_frames(tmp_path):
    # A dark motion video (a launch) with a picture: the tiger keeps its own orange, not one cream silhouette.
    board = script.build(ingest.read('# Launch\n\nIntroducing our new app. A tiger guards your files.'), story='promo')
    RulesDirector('en').direct(board)
    plan = from_rules(board, [])
    plan['style']['palette']['background'] = '#0C0C0C'
    scene = plan['scenes'][-1]
    scene.update(treatment='motion', composition='center', elements=[{'kind': 'picture', 'ref': 'fl_tiger'}],
                 text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = prod.spans[-1]
    frame = np.asarray(prod.frame(span.start + .8 * (span.end - span.start)), np.int32)
    orange = (abs(frame[..., 0] - 0xFF) < 40) & (abs(frame[..., 1] - 0x67) < 40) & (frame[..., 2] < 80)
    assert orange.sum() > 2000


def test_story_doodles_keep_their_colours_and_never_use_the_rig(tmp_path, monkeypatch):
    from kinodraw.engine import hybrid
    monkeypatch.setattr(hybrid, 'raster', lambda *a, **k: pytest.fail('story characters drew the procedural rig'))
    prod, board, plan, tl = production(tmp_path)
    span = span_of(prod, 'And then there was Pendo')
    frame = np.asarray(prod.frame(span.start + 1.), np.int32)
    paper = np.array([0xEC, 0xEB, 0xE6])
    coloured = (np.abs(frame - paper).max(axis=2) > 40) & (frame.max(axis=2) - frame.min(axis=2) > 60)
    assert coloured.sum() > 3000          # saturated doodle colours, not cream or grey silhouettes


def test_roar_lesson_places_both_lions_from_the_cubs_point_of_view(tmp_path, monkeypatch):
    pastes = Pastes(monkeypatch)
    prod, board, plan, tl = production(tmp_path)
    span = span_of(prod, 'Roar louder')
    shot, at = shot_of(span, prod, 'Roar louder')
    assert shot.lesson
    figures = {f.key: f for f in shot.figures}
    kojo, pendo = figures['kojo'], figures['pendo']
    assert kojo.pose == 'roar' and pendo.pose == 'look_up'
    assert pendo.x < .3 and pendo.ground > kojo.ground          # the cub in the near corner, looking up
    assert kojo.height > pendo.height and pendo.facing == 'r' and kojo.facing == 'l'
    pastes.calls.clear()
    frame = prod.frame(span.start + kojo.cue + .9)
    lions = [(d, box) for d, box, _ in pastes.calls if box and ('lion' in d)]
    assert len(lions) >= 2
    assert frame is not None
    quiet = prod.frame(span.start + kojo.cue + ROAR_AFTER)
    assert np.abs(np.asarray(frame, np.int32) - np.asarray(quiet, np.int32)).max() > 60   # the roar moves


ROAR_AFTER = 2.9


def test_carry_beat_attaches_the_smaller_doodle_to_the_carrier(tmp_path, monkeypatch):
    from kinodraw.engine import storybook
    pastes = Pastes(monkeypatch)
    prod, board, plan, tl = production(tmp_path)
    span = span_of(prod, 'carrying the slowest')
    shot, at = shot_of(span, prod, 'carrying the slowest')
    carrier = next(f for f in shot.figures if f.key == 'mara')
    assert carrier.pose == 'carry' and carrier.carried is not None
    assert carrier.carried.height < carrier.height * .6
    pastes.calls.clear()
    prod.frame(span.start + at + .5)
    drawn = [(d, box, h) for d, box, h in pastes.calls if box]
    body = next(i for i, (d, _, h) in enumerate(drawn) if h == carrier.height)
    held = next(i for i, (d, _, h) in enumerate(drawn) if h == carrier.carried.height)
    assert held > body                                  # drawn in front of the carrier, in its mouth
    (bx, by, bw, bh), (cx, cy, cw, ch) = drawn[body][1], drawn[held][1]
    assert bx < cx + cw and cx < bx + bw and by < cy + ch and cy < by + bh      # attached, overlapping
    assert ch < bh
    assert not storybook.meta(drawn[held][0]).get('species') in ('human',)


def test_eye_line_pushes_into_the_cubs_eyes(tmp_path):
    prod, board, plan, tl = production(tmp_path)
    span = span_of(prod, "Pendo's eyes")
    shot, at = shot_of(span, prod, 'Then he looked')
    assert shot.eyes is not None and shot.eyes.key == 'pendo'
    before = prod.storybook._eye_camera(shot, shot.eyes_at - .5, [.5, .5, 1.])
    after = prod.storybook._eye_camera(shot, shot.eyes_at + 1.2, [.5, .5, 1.])
    assert after[2] > 1.8 and before[2] < 1.2


def test_series_bible_does_not_turn_a_fresh_animal_back_into_a_human(tmp_path):
    stale = {'id': 'kojo', 'name': 'Kojo', 'kind': 'human', 'species': 'human', 'family': 'human', 'age': 'adult',
             'sex': 'male', 'size': 1.0, 'palette': {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'},
             'marks': ['crown'], 'temperament': 'gentle'}
    edit = {'id': 'mara', 'species': 'tigress', 'marks': ['stripes']}
    pipeline.new_project(STORY, tmp_path, director_v3=True, series_bible={'cast': [stale, edit]})
    pipeline.direct_v3(tmp_path, provider='rules')
    cast = {c['id']: c for c in pipeline.settings(tmp_path)['plan_v3']['cast']}
    assert cast['kojo']['kind'] == 'quadruped' and cast['kojo']['species'] == 'lion'
    assert cast['mara']['species'] == 'tigress'           # a genuine edit still wins


def test_animals_never_resolve_to_a_human_figure():
    from kinodraw.director.v3.semantics import HUMAN_SPECIES, SPECIES
    from kinodraw.engine import storybook
    from kinodraw.library import catalog
    people = {did for did, e in catalog().items() if e.get('category') in ('People & Body', 'people', 'narrator')}
    poses = ('stand', 'walk', 'run', 'sit', 'lie', 'sleep', 'roar', 'look_up', 'scared', 'carry')
    for species in [s for s in SPECIES if s not in HUMAN_SPECIES and s not in ('robot', 'blob')] + ['porcupine', 'ant']:
        for age in ('adult', 'baby'):
            for pose in poses:
                for facing in 'rl':
                    doodle, _ = storybook.preset(species, age, None, pose, facing)
                    assert doodle not in people, (species, age, pose, doodle)
                    assert storybook.meta(doodle).get('species') not in HUMAN_SPECIES
    assert storybook.preset('girl', 'young', 'female', 'stand', 'r')[0] in people


def test_story_lions_are_full_body_presets_with_kojos_black_mane(tmp_path, monkeypatch):
    """J: "King Kojo is not a lion at all". Every lion pose is a full-body creature preset (never the face-only
    library lion); the king keeps his black mane, the cub is the young lion, and all of a character's poses are
    drawn at one scale."""
    from kinodraw.engine import storybook
    pastes = Pastes(monkeypatch)
    prod, board, plan, tl = production(tmp_path)
    span = span_of(prod, 'Roar louder')
    shot, at = shot_of(span, prod, 'Roar louder')
    figures = {f.key: f for f in shot.figures}
    pastes.calls.clear()
    prod.frame(span.start + figures['kojo'].cue + .9)
    drawn = {h: d for d, box, h in pastes.calls if box}
    kojo, pendo = storybook.meta(drawn[figures['kojo'].height]), storybook.meta(drawn[figures['pendo'].height])
    assert kojo['species'] == 'lion' and kojo['age'] == 'adult' and 'mane_black' in kojo['marks']
    assert kojo['pose'] == 'roar' and kojo['facing'] == 'l'
    assert pendo['species'] == 'lion' and pendo['age'] == 'young' and pendo['pose'] == 'look_up'
    stand = storybook.preset('lion', 'adult', 'male', 'stand', 'r', ('mane_black',))[0]
    lie = storybook.preset('lion', 'adult', 'male', 'lie', 'r', ('mane_black',))[0]
    # A lying lion is lower than a standing one at the same character height, not stretched to fill it.
    _, top, _, bottom = storybook._bbox(lie)
    assert storybook._box(lie, .4, stand) * (bottom - top) < .4 * .9


def test_a_story_ends_on_the_end_and_other_videos_on_their_title():
    from types import SimpleNamespace
    from kinodraw.engine.auto_scenes import end_heading
    title = {'en': 'Deep in the green heart of the Ombasi Jungle, where the trees grew so tall', 'zh': '奥姆巴西丛林'}
    card = lambda story, lang: end_heading(SimpleNamespace(ep={'story': story, 'title': title}, lang=lang,
                                                           T=lambda value: value[lang]))
    assert (card('story', 'en'), card('story', 'zh')) == ('The End', '完')
    assert card('explain', 'en') == title['en']


def test_a_lone_resting_figure_never_freezes_the_picture(tmp_path):
    """The QA's freezedetect (-50 dB over 1 s) flagged the jungle's lone small cub, held for 8 s while the narration
    described him; the page now drifts with the camera push and resting figures shift their weight. Captions, whose
    word highlight also moves, are left out here."""
    prod, *_ = production(tmp_path)
    prod.frame(0.)
    shot = next(shot for span in prod.spans if span.story for shot in span.story
                if len(shot.figures) == 1 and shot.figures[0].age == 'baby')
    shot.end = shot.start + 8
    frames = [np.asarray(prod.storybook.frame([shot], shot.start + 2 + k / 4), np.float32) / 255 for k in range(5)]
    # freezedetect keeps its reference frame until the picture moves away from it by more than -50 dB MAFD
    assert np.abs(frames[4] - frames[0]).mean() > 10 ** (-50 / 20)


def _overlaid(frame, before, after, times):
    """Frames (at these times) that show two pictures on top of each other: where the two pictures differ, the frame
    matches neither of them. A cut or a wipe shows one picture or the other at every pixel."""
    count = 0
    for t in times:
        a, b, f = (np.asarray(make(t), np.int16) for make in (before, after, frame))
        differ = np.abs(a - b).max(axis=2) > 60
        mixed = differ & (np.abs(f - a).max(axis=2) > 24) & (np.abs(f - b).max(axis=2) > 24)
        count += bool(differ.sum()) and mixed.sum() / differ.sum() > .2
    return count


def test_page_changes_never_overlay_two_pictures(tmp_path, monkeypatch):
    """J's jungle: shot dissolves, scene morphs and the face fade ghosted two crowded pictures for 10-20 frames. A
    page change is a cut, a wipe or a page turn; a dissolve lasts at most two frames, where the same set continues."""
    prod, board, plan, tl = production(tmp_path)
    monkeypatch.setattr(prod.whiteboard, '_caption', lambda *a, **k: None)
    book = prod.storybook
    prod.frame(0.)
    frames = lambda a, b: [a + k / 30 for k in range(int((b - a) * 30) + 1)]
    first = prod.spans[0]
    for k in (1, 2):                          # a new set (the palm tree goes) and the same set (Mara joins)
        shot, previous = first.story[k], first.story[k - 1]
        assert _overlaid(lambda t: book.frame(first.story, t), lambda t: book._draw(previous, t),
                         lambda t: book._draw(shot, t), frames(shot.start - .04, shot.start + .3)) <= 2
    for words in ('Roar louder', 'carrying the slowest'):     # a scene join into the lesson, and out of a face
        span = span_of(prod, words)
        before = prod.spans[prod.spans.index(span) - 1]
        assert _overlaid(prod.frame, lambda t: prod._frame(before, t), lambda t: prod._frame(span, t),
                         frames(span.join - .04, span.join + .3)) <= 2, words
    span = span_of(prod, "Pendo's eyes")
    shot = next(s for s in span.story if s.eyes)
    shot.end = shot.eyes_at + 3                         # long enough for the push to land on the eyes
    landed = max(shot.start, shot.eyes_at - .3) + 1.3
    alphas = [(book._face_overlay(shot, t) or (None, 0.))[1] for t in frames(landed - .1, landed + .4)]
    assert max(alphas) == 1 and sum(.1 < a < .9 for a in alphas) <= 2      # the face close-up cuts in on the eyes


RIDGE = ('# The Ridge\n\n'
         'Deep in the jungle lived King Kojo. His mane was dark as wet bark. Every creature in the jungle, from the '
         'proudest gorilla to the smallest tree frog, knew his voice.\n\n'
         'Beside him ruled Queen Mara, sleek and golden-eyed, who spoke softly but was never ignored.\n\n'
         'And then there was Pendo, their only cub.\n\n'
         'Pendo was small for his age, with oversized paws he had not grown into. He ran to the great fig tree where '
         'his parents rested.\n\n'
         'That night, under pounding rain, King Kojo roared the alarm across the valley. But it was Pendo who led the '
         'way. He guided the antelope, the warthogs, the porcupines, and even the monkeys who had teased him, up the '
         'secret elephant path to the ridge.\n\n'
         'When the sun came out, the animals gathered around the royal family. The oldest elephant stepped forward and '
         'bowed her head, not to Kojo, but to Pendo.\n\n'
         'Pendo grinned and tried a roar of his own. It still came out as a squeak.')


def royal_family(tmp_path, text=RIDGE):
    """The jungle's cast as its saved plan has it: Queen Mara is a lioness (the offline rules read her as a woman)."""
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    for c in plan['cast']:
        if c['id'] == 'mara':
            c.update(kind='quadruped', species='lioness', family='feline')
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    return prod


def _staged(book, f, local, end):
    """A figure's drawn body box and head box (frame shares x0, y0, x1, y1) at this time, wherever its walk or run
    has taken it by then, read from the doodle's own alpha bounds and head anchor."""
    from kinodraw.engine import storybook
    doodle, mirror, pose = book._pose_doodle(f, local)
    reference = book._reference(f)
    left, top, right, bottom = storybook._bbox(doodle, mirror)
    box = storybook._box(doodle, f.height, reference)
    _, sw, sh = storybook._svg(doodle)
    w, h = book.size
    width = box * sw / sh * h / w
    x = f.x + (1 if f.facing == 'r' else -1) * f.travel * (local >= end)
    middle = (left + right) / 2
    body = (x + (left - middle) * width, f.ground - (bottom - top) * box, x + (right - middle) * width, f.ground)
    ax, ay = storybook.anchor(doodle, 'head', mirror)
    hx, hy, r = x + (ax - middle) * width, f.ground - (bottom - ay) * box, .16 * f.height
    return body, (hx - r * h / w, hy - r, hx + r * h / w, hy + r)


def _overlap(a, b, slack=.004):
    return a[0] < b[2] - slack and b[0] < a[2] - slack and a[1] < b[3] - slack and b[1] < a[3] - slack


def test_group_shots_keep_every_head_in_sight(tmp_path):
    """J's jungle: an elephant's head between two lions with the cub on top of it; a running cub on a lying lioness.
    No figure's head is behind another figure's body, at the start of a shot or where walks and runs end; smaller
    animals stand in front, and everyone stays on the page."""
    prod = royal_family(tmp_path)
    book = prod.storybook
    shots = [shot for span in prod.spans if span.story for shot in span.story]
    gathered = next(s for s in shots if {'kojo', 'mara', 'pendo'} <= {f.key for f in s.figures}
                    and any(f.crowd for f in s.figures))
    assert len([f for f in gathered.figures if f.crowd]) >= 2          # the animals are there, not dropped
    ran = next(s for s in shots if any(f.key == 'pendo' and f.pose == 'run' for f in s.figures))
    assert {'kojo', 'mara'} <= {f.key for f in ran.figures}
    for shot in shots:
        for local in (shot.end - .01, shot.end):          # poses are set by then; the second is where travel ends
            order = sorted(shot.figures, key=lambda f: f.depth)
            staged = [_staged(book, f, local, shot.end) for f in order]
            for i, (behind, (_, head)) in enumerate(zip(order, staged)):
                for front, (body, _) in zip(order[i + 1:], staged[i + 1:]):
                    if behind.carried is front or 'nuzzle' in (behind.pose, front.pose):
                        continue                             # touching on purpose
                    assert not _overlap(head, body), (shot.start, behind.key, front.key)
            for f, (body, _) in zip(order, staged):
                assert -.01 < body[0] and body[2] < 1.01, (shot.start, f.key)
        for m in (f for f in shot.figures if f.crowd):
            for c in (f for f in shot.figures if not f.crowd and f.height > m.height):
                if any(_overlap(a, b) for a in _staged(book, m, shot.end, shot.end)[:1]
                       for b in _staged(book, c, shot.end, shot.end)[:1]):
                    assert m.depth > c.depth, (shot.start, m.key, c.key)     # a smaller animal stands in front



def test_a_crowned_character_wears_the_crown_on_its_head_in_every_pose(tmp_path):
    """Kojo's and Mara's 'crown' mark had no picture and was dropped with a warning. The library's crown sits on the
    head (above its head anchor, centred on it) whether the king stands, roars or walks."""
    from kinodraw.engine import storybook
    prod = royal_family(tmp_path)
    book = prod.storybook
    assert not [w for w in prod.warnings if 'crown' in w]
    kojo = book._cast_figure('kojo')
    assert 'crown' in kojo.marks
    w, h = book.size
    for pose in ('stand', 'roar', 'walk'):
        f = storybook.Figure(**{**kojo.__dict__, 'pose': pose, 'cue': 0., 'x': .5})
        shot = storybook.Shot(0., 2., figures=[f])
        frame = np.asarray(book._draw(shot, 1.), np.int32)
        doodle, mirror, _ = book._pose_doodle(f, 1.)
        hx, hy = book._point(doodle, mirror, 'head', f.x, f.ground, f.height, book._reference(f))
        jewel = (np.abs(frame - [0x00, 0xA6, 0xED]).max(axis=2) < 40)       # the crown's blue stones
        ys, xs = np.nonzero(jewel)
        assert len(xs) > 30, pose
        assert abs(xs.mean() / w - hx) < .04, pose                        # centred on the head
        assert hy - .25 < ys.mean() / h < hy, pose                        # on top of it, not floating off

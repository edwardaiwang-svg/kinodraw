"""J 10/8: no random camera zooms. The storybook camera is locked except for a push into the eyes a line names and a
roar's shake; a push or close-up frames its subject from the head's box, eases in and never pans alone; a calm,
low-energy plan keeps a static camera; a cut between two framings that read as the same picture is never a wipe."""
import copy
import json

import numpy as np

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline

LION = {'id': 'kojo', 'name': 'Kojo', 'kind': 'quadruped', 'species': 'lion', 'age': 'adult', 'sex': 'male'}
HEDGEHOG = {'id': 'pip', 'name': 'Pip', 'kind': 'quadruped', 'species': 'hedgehog', 'age': 'young', 'sex': 'male'}
PEOPLE = [{'id': 'mia', 'name': 'Mia', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female'},
          {'id': 'sam', 'name': 'Sam', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male'}]
CALM = {'energy': 1, 'pacing': 'calm', 'motion_floor': 'breathing'}


def shot(bid, starts_at, kind, cast, place='forest'):
    """A plan shot; cast entries are (id, age, pose)."""
    return {'beat_id': bid, 'starts_at': starts_at, 'shot': kind,
            'setting': {'place': place, 'time': 'day', 'set_refs': []},
            'cast': [{'id': c, 'age': a, 'pose': p, 'speaking': 'no'} for c, a, p in cast],
            'lines': [], 'props': [], 'focus_ref': '', 'writing': ''}


def produce(tmp_path, text, cast, shots=(), genre='story', style=None):
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['storyboard']['genre'] = genre
    plan['style'].update(mode='hybrid', **(style or {}))
    plan['cast'] = [dict(c, family=c['species'], size=1, palette={}, marks=[], temperament='calm') for c in cast]
    for scene in plan['scenes']:
        scene.update(treatment='character', composition='stage', camera='slow_push', actions=[],
                     text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]},
                     elements=[{'kind': 'cast', 'ref': c['id']} for c in cast])
        mine = [s for s in shots if s['beat_id'] in scene['beat_ids']]
        if mine:
            scene['shots'] = mine
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    return prod


def story_shots(prod):
    return [s for span in prod.spans for s in span.story or []]


def head_on_screen(book, f, cam):
    """The head anchor's circle (storybook._shape) on screen, in pixels."""
    head = book._shape(f, book._pose_name(f.pose), f.x)[1]
    (a, b, _), (c, d, _) = book._to_screen(head[0], head[1], list(cam)), book._to_screen(head[2], head[3], list(cam))
    return a, b, c, d


def in_safe_frame(book, box):
    """Inside the frame's sides and top, and above the caption band."""
    w, h = book.size
    return box[0] >= .02 * w and box[2] <= .98 * w and box[1] >= .02 * h and box[3] <= .8 * h


def times(shot, step=1 / 15):
    return np.arange(shot.start, shot.end, step)


# ------------------------------------------------------------------ close-ups and pushes frame the head
def test_a_close_up_of_an_animal_keeps_its_whole_head_in_the_frame_above_the_captions(tmp_path):
    """A hedgehog's head is at its side and low: a close-up centred on its body's middle cropped it (round 4, Pip at
    6.7-10 s and 86-88 s)."""
    for pose in ('stand', 'sleep'):
        prod = produce(tmp_path / pose, 'Pip curled up by the pond. The night was quiet.', [HEDGEHOG],
                       [shot('b001', 'Pip curled', 'close', [('pip', 'young', pose)])])
        book = prod.storybook
        close = next(s for s in story_shots(prod) if s.framing == 'close')
        assert close.view[2] > 1.5, pose                                   # still a close-up
        pip = next(f for f in close.figures if f.key == 'pip')
        assert in_safe_frame(book, head_on_screen(book, pip, close.view)), (pose, close.view)


def test_a_line_about_someones_eyes_pushes_in_with_the_head_inside_the_frame(tmp_path):
    """Negative: the eyes a line names still get their push, eased in, and the head stays inside the safe frame on
    the whole way in."""
    prod = produce(tmp_path, "Mia stood by the gate. Mia's eyes went wide with wonder.", PEOPLE[:1])
    book = prod.storybook
    pushed = [s for s in story_shots(prod) if s.eyes is not None]
    assert pushed and pushed[0].eyes.key == 'mia'
    s = pushed[0]
    cams = [book._camera(s, t) for t in times(s)]
    zooms = [c[2] for c in cams]
    assert zooms[-1] > 1.5 * zooms[0]                                       # it pushes in
    assert all(b >= a - 1e-9 for a, b in zip(zooms, zooms[1:]))            # one push, never back out
    steps = np.diff(zooms)
    moving = np.nonzero(steps > 1e-6)[0]
    assert steps[moving[0]] < steps[moving].max() / 2 and steps[moving[-1]] < steps[moving].max() / 2   # eased
    for t, cam in zip(times(s), cams):
        assert in_safe_frame(book, head_on_screen(book, s.eyes, cam)), t


def test_a_push_never_pans_on_its_own(tmp_path):
    """Round 4, lion story 98.4-100.6 s: Kojo already filled a medium, so the "push" into his eyes zoomed 4% and
    panned the frame across him. A framing that already shows the head as close as a push may does not move."""
    prod = produce(tmp_path, 'Kojo stood on the ridge above the valley. His eyes blazed with fire.', [LION],
                   [shot('b001', 'Kojo stood', 'medium', [('kojo', 'adult', 'stand')])])
    book = prod.storybook
    for s in story_shots(prod):
        cams = [book._camera(s, t) for t in times(s)]
        zoom_gain = max(c[2] for c in cams) / cams[0][2]
        travel = max(abs(c[0] - cams[0][0]) + abs(c[1] - cams[0][1]) for c in cams)
        assert travel < 1e-6 or zoom_gain >= 1.15, (s.framing, travel, zoom_gain)
        for f in s.figures:
            for cam in cams:
                assert in_safe_frame(book, head_on_screen(book, f, cam)) or s.view[2] == 1.


# ------------------------------------------------------------------ a push needs its motivation in the words
def test_looking_at_someone_is_not_a_line_about_their_eyes(tmp_path):
    """A scene that opens on "Sam looked at Mia." pushed into Mia's eyes: a push by default, not by the words."""
    prod = produce(tmp_path, 'Sam looked at Mia across the kitchen. Then he sat down.', PEOPLE)
    book = prod.storybook
    for s in story_shots(prod):
        assert s.eyes is None
        assert book._camera(s, s.start + .05) == book._camera(s, s.end - .05) == list(s.view)


# ------------------------------------------------------------------ a calm plan keeps a static camera
def test_a_calm_low_energy_plan_keeps_a_static_camera_in_every_scene(tmp_path):
    """The five-minute reset (energy 1, calm, breathing): a figureless page cut to a 1.6x look at nothing on its third
    sentence (round 4, 84.9 s), and an eye line would push. Calm: one framing per scene, no push, no shake."""
    text = ('Sit back and rest your hands. Breathe in slowly. Breathe out slowly. Let your shoulders drop.\n\n'
            "Mia's eyes close gently. Kojo roared far away.")
    for genre in ('lesson', 'story'):
        prod = produce(tmp_path / genre, text, PEOPLE[:1] + [LION], genre=genre, style=CALM)
        book = prod.storybook
        for span in prod.spans:
            shots = span.story or []
            assert len({s.view for s in shots}) <= 1, (genre, span.spec['beat_ids'], [s.view for s in shots])
            for s in shots:
                assert s.eyes is None
                for t in times(s, .2):
                    assert book._camera(s, t) == list(s.view), (genre, t)
            assert prod._camera(span, .1) == (1., 0., 0.)


def test_a_roar_still_shakes_and_a_calm_plan_does_not(tmp_path):
    """Negative: outside a calm plan the roar keeps its shake."""
    lively = produce(tmp_path / 'lively', 'Kojo stood tall. Then Kojo roared at the storm.', [LION])
    calm = produce(tmp_path / 'calm', 'Kojo stood tall. Then Kojo roared at the storm.', [LION], style=CALM)
    for prod, shakes in ((lively, True), (calm, False)):
        book = prod.storybook
        roaring = [s for s in story_shots(prod) if any(f.pose == 'roar' and f.cue is not None for f in s.figures)]
        assert roaring
        moved = any(book._camera(s, t) != list(s.view) for s in roaring for t in times(s, 1 / 30))
        assert moved is shakes


# ------------------------------------------------------------------ cuts between near-identical framings
def test_a_cut_between_two_framings_of_the_same_picture_is_never_a_wipe(tmp_path):
    """Round 4, movie night 32.9-33.2 s: two near-identical wides of the living room (one with a tablet on the floor)
    joined by a diagonal wipe, which read as a glitch. Out of a close-up the page cuts too: a wipe mixed the face
    card into the page (lion story 100.6 s)."""
    prod = produce(tmp_path, 'Sam sat on the couch. Mia came in and sat down.', PEOPLE,
                   [shot('b001', 'Sam sat', 'wide', [('sam', 'adult', 'sit'), ('mia', 'young', 'sit')],
                         place='living_room')])
    book = prod.storybook
    a = story_shots(prod)[0]
    b = copy.copy(a)
    b.start, b.end = a.end, a.end + 2.
    b.props = list(a.props) + [('fl_mobile_phone', .5, .78, .1)]          # a thing on the floor: a new _set
    b.view = (a.view[0] + .04, a.view[1], a.view[2] * 1.12)
    assert book.turn_kind(a, b) != 'wipe'
    mixed = book.frame([a, b], b.start + .03)
    assert np.array_equal(np.asarray(mixed), np.asarray(book._draw(b, b.start + .03)))     # a plain cut
    far = copy.copy(b)
    far.view = (a.view[0], a.view[1], a.view[2] * 2.2)
    assert book.turn_kind(a, far) == 'wipe'                              # negative: a real new framing keeps its wipe
    face = copy.copy(a)
    face.eyes = a.figures[0]
    assert book.turn_kind(face, far) == 'cut'

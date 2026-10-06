"""Source character scenes must remain readable and alive after their action cues."""
import copy
import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline
from kinodraw.engine.bold.render import _text_metrics


def production(tmp_path, paragraphs, names=('Nia', 'Sora', 'Taro'), floor='drifting', size=None):
    child, mother, father = names
    intro = (f'{child}, a tiny lion cub, loved her mother, {mother}, a tigress. '
             f'{father}, a male lion with a massive black mane, watched them.')
    board = script.build(ingest.read('# Family\n\n' + '\n\n'.join([intro, *paragraphs])), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor=floor, music_mood='none')
    for scene in plan['scenes']:
        bid = scene['beat_ids'][0]
        scene.update(treatment='character', composition='split', camera='static', transition_in='cut',
                     elements=[{'kind': 'text', 'ref': bid}], text={'kind': 'caption_only', 'ref': bid})
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    # Keep long source spans after finite action cues; all character offsets stay source-derived.
    for bid in tl['beat_order']:
        entry = tl['beats'][bid]
        shift = 12 - (entry['end'] - entry['start'])
        if shift > 0:
            at = entry['end']
            entry['end'] += shift
            entry['speech_end'] += shift
            for other in tl['beats'].values():
                if other is not entry and other['start'] >= at:
                    for k in ('start', 'end', 'speech_end'):
                        other[k] += shift
            for k in ('start', 'end'):
                tl['end_card'][k] += shift
            tl['duration'] += shift
    settings = {'director_v3': True, 'plan_v3': plan}
    (tmp_path / 'project.json').write_text(json.dumps(settings))
    prod = render.make_production(board, tl, 'en', tmp_path, size=size,
                                  aspect='1:1' if size and size[0] == size[1] else '16:9')
    return prod, board, plan, tl


class Canvas:
    """Record the actual nontransparent sprite bounds while composing real pixels."""
    def __init__(self, size):
        self.size = size
        self.image = Image.new('RGB', size)
        self.boxes = []

    def paste(self, sprite, position, mask):
        bbox = sprite.getchannel('A').getbbox()
        x, y = position
        self.boxes.append((x + bbox[0], y + bbox[1], x + bbox[2], y + bbox[3]))
        self.image.paste(sprite, position, mask)


def test_long_source_label_fits_without_squeezing_cast(tmp_path):
    text = ('Then, the giant king turned around. Nia shrank back, expecting a scolding for being '
            'so close to the edge. Instead, Taro lowered his massive head all the way to the dirt. '
            'He gently nudged Nia with his giant, scarred nose, checking her for scratches.')
    prod, board, _, _ = production(tmp_path, [text])
    span = prod.spans[-1]
    element = span.motion.elements[0]
    content, _, size, _ = _text_metrics(element.text, element.size, element.width,
                                      element.preset == 'corner_caption', element.font)
    assert size >= 40, 'a source paragraph became unreadable single-line microtype'
    assert element.preset != 'word_pop' or len(element.text.split()) <= 12
    assert ' '.join(element.text.split()).strip('“”') in board['beats'][-1]['display']['en']
    assert len(content.splitlines()) * size * 1.15 <= element.height
    canvas = Canvas(prod.size)
    prod._actors(span, 4., canvas)
    assert len(canvas.boxes) == 2
    assert min(b[3] - b[1] for b in canvas.boxes) >= 125
    assert max(b[3] - b[1] for b in canvas.boxes) >= 280
    assert all(40 <= b[0] < b[2] <= 1880 and 55 <= b[1] < b[3] <= 850 for b in canvas.boxes)


@pytest.mark.parametrize('names', [('Nia', 'Sora', 'Taro'), ('Ayo', 'Luma', 'Beko')])
def test_her_cub_relation_adds_existing_child_and_keeps_genome(tmp_path, names):
    child, mother, _ = names
    text = f'{mother} nudged her cub gently, her golden eyes filled with warmth.'
    prod, _, _, tl = production(tmp_path, [text], names)
    span = prod.spans[-1]
    actor, action, target = next(e for e in span.actions if e[1].name == 'nudge')
    assert target == child.casefold(), 'the explicitly established child is missing'
    assert {actor, target} <= set(span.actors)
    assert prod.cast[target].age == 'baby' and prod.cast[target].species == 'lion'
    assert prod.cast[actor].species == 'tiger' and 'stripes' in prod.cast[actor].marks
    timing = tl['beats'][span.spec['beat_ids'][0]]
    assert span.start + action.start == timing['start'] + timing['char_times'][text.index('nudged')]
    before, contact = Canvas(prod.size), Canvas(prod.size)
    prod._actors(span, action.start, before)
    prod._actors(span, action.start + action.seconds * .55, contact)
    assert len(contact.boxes) == 2
    assert max(contact.boxes[0][0], contact.boxes[1][0]) <= min(contact.boxes[0][2], contact.boxes[1][2]) + 20
    assert not np.array_equal(np.asarray(before.image), np.asarray(contact.image))
    no_action = copy.copy(span)
    no_action.actions = ()
    idle = Canvas(prod.size)
    prod._actors(no_action, action.start + action.seconds * .55, idle)
    assert all(a != b for a, b in zip(contact.boxes, idle.boxes)), 'both participants need a physical response'


def test_pronoun_nudge_uses_spoken_verb_time_and_named_object(tmp_path):
    text = ('Nia shrank back. Taro lowered his massive head all the way to the dirt. '
            'He gently nudged Nia with his scarred nose.')
    prod, _, plan, tl = production(tmp_path, [text])
    # A validated saved action may have a conservative pronoun cue even if rules omit it.
    scene = plan['scenes'][-1]
    scene['actions'] = [{'actor': 'taro', 'verb': 'nudge', 'at_beat': scene['beat_ids'][0], 'intensity': 1}]
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(prod.ep, tl, 'en', tmp_path)
    span = prod.spans[-1]
    actor, action, target = span.actions[0]
    assert actor == 'taro' and target == 'nia'
    timing = tl['beats'][scene['beat_ids'][0]]
    assert span.start + action.start == timing['start'] + timing['char_times'][text.index('nudged')]


def test_quote_is_complete_readable_and_waits_for_its_source_words(tmp_path):
    body = 'You will understand one day.'
    text = f'Sora nudged her cub gently. "{body}"'
    prod, board, plan, tl = production(tmp_path, [text])
    beat = board['beats'][-1]
    beat['visuals'] = [{'id': 'source-quote', 'type': 'quote', 'text': {'en': body}}]
    plan['scenes'][-1]['text'] = {'kind': 'quote', 'ref': beat['id']}
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    original = copy.deepcopy((board, tl))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = prod.spans[-1]
    e = span.motion.elements[0]
    timing = tl['beats'][beat['id']]
    assert span.start + e.start == timing['start'] + timing['char_times'][text.index(body)]
    content, _, size, _ = _text_metrics(e.text, e.size, e.width, True, e.font)
    assert e.preset == 'corner_caption' and size >= 40
    assert ' '.join(content.split()).strip('“”') == body
    assert len(content.splitlines()) * size * 1.15 <= e.height
    assert (board, tl) == original


def test_two_established_children_do_not_resolve_her_cub(tmp_path):
    prod, _, _, _ = production(tmp_path, [
        'Milo, a lion cub, loved his mother, Sora.', 'Sora nudged her cub gently.'])
    assert not any(a.name == 'nudge' for _, a, _ in prod.spans[-1].actions)
    assert any('nudge' in w and 'unambiguous' in w for w in prod.warnings)


@pytest.mark.parametrize('text', [
    'Sora nudged her cub gently.',
    'Sora nudged Nia and Taro gently.',
    'Sora never nudged Nia.',
    'Sora watched Taro. He nudged Nia.',
])
def test_ambiguous_unknown_or_unowned_nudge_is_skipped(tmp_path, text):
    prod, _, plan, tl = production(tmp_path, [text])
    if 'her cub' in text:
        # Remove source relationship; a baby genome alone is not parentage evidence.
        prod.ep['beats'][0]['spoken']['en'] = 'Nia, a lion cub, watched Sora and Taro.'
    scene = plan['scenes'][-1]
    scene['actions'] = [{'actor': 'sora', 'verb': 'nudge', 'at_beat': scene['beat_ids'][0], 'intensity': 1}]
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(prod.ep, tl, 'en', tmp_path)
    assert not any(a.name == 'nudge' for _, a, _ in prod.spans[-1].actions)
    assert any('nudge' in w for w in prod.warnings)


@pytest.mark.parametrize('size', [None, (1080, 1080)])
def test_settled_cast_moves_at_readable_scale_and_random_access_is_pure(tmp_path, size):
    prod, board, _, tl = production(tmp_path, ['Nia whimpered one afternoon.'], size=size)
    original = copy.deepcopy((board, tl))
    span = prod.spans[-1]
    # Measure composed characters alone, so atmospheric pixels cannot pass this check.
    changes = []
    previous = None
    for i in range(61):
        canvas = Canvas(prod.size)
        prod._actors(span, 7. + i / 30, canvas)
        frame = np.asarray(canvas.image.resize((160, 90)).convert('L'), dtype=float)
        if previous is not None:
            changes.append(np.abs(frame - previous).mean() / 255)
        previous = frame
    assert all(max(changes[i:i + 15]) >= .001 for i in range(0, 60, 15))
    times = [span.start + t for t in (2., 5., 8.)]
    forward = [hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in times]
    reverse = [hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in reversed(times)]
    fresh = render.make_production(board, tl, 'en', tmp_path, size=size,
                                   aspect='1:1' if size else '16:9')
    assert forward == reverse[::-1] == [hashlib.sha256(fresh.frame(t).tobytes()).hexdigest() for t in times]
    assert (board, tl) == original


def test_still_floor_preserves_settled_character_geometry(tmp_path):
    prod, _, _, _ = production(tmp_path, ['Nia whimpered one afternoon.'], floor='still')
    span = prod.spans[-1]
    a, b = Canvas(prod.size), Canvas(prod.size)
    prod._actors(span, 7., a)
    prod._actors(span, 8., b)
    assert a.boxes == b.boxes


def test_explicit_stage_keeps_departed_source_mentions_out(tmp_path):
    text = 'Sora had gone away hunting. Nia pounced on the grass.'
    prod, board, plan, tl = production(tmp_path, [text])
    scene = plan['scenes'][-1]
    scene['elements'] = [{'kind': 'cast', 'ref': 'nia'}, {'kind': 'text', 'ref': scene['beat_ids'][0]}]
    scene['actions'] = [{'actor': 'nia', 'verb': 'pounce', 'at_beat': scene['beat_ids'][0], 'intensity': 1}]
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    assert prod.spans[-1].actors == ('nia',)


def test_separate_baby_and_adult_groups_keep_their_relative_size(tmp_path):
    prod, _, _, _ = production(tmp_path, ['Nia watched Sora.'])
    span = prod.spans[-1]
    canvas = Canvas(prod.size)
    prod._actors(span, 4., canvas)
    child, adult = canvas.boxes
    assert child[3] - child[1] < .8 * (adult[3] - adult[1])


def test_rescue_pronouns_use_the_established_actor_and_real_verb_times(tmp_path):
    text = ('He did not look distant anymore. His eyes blazed with fire. '
            'With one massive swipe of his heavy paw, he sent the intruder away. '
            'He stood over Nia, unleashing a roar so powerful it rattled her teeth.')
    prod, board, plan, tl = production(tmp_path, ['Taro burst through the fog.', text])
    scene = plan['scenes'][-1]
    bid = scene['beat_ids'][0]
    scene['actions'] = [{'actor': 'taro', 'verb': verb, 'at_beat': bid, 'intensity': 3}
                        for verb in ('swipe', 'roar')]
    scene['elements'] = [{'kind': 'cast', 'ref': 'taro'}, {'kind': 'cast', 'ref': 'nia'}]
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = prod.spans[-1]
    timing = tl['beats'][bid]
    for actor, a, _ in span.actions:
        assert actor == 'taro'
        assert span.start + a.start == timing['start'] + timing['char_times'][text.index(a.name)]


@pytest.mark.parametrize('composition', ['split', 'left_third'])
def test_crowd_silhouettes_clear_the_source_text_band(tmp_path, composition):
    prod, board, plan, tl = production(tmp_path, ['Taro stood breathing heavily while two hyenas watched.'])
    plan['scenes'][-1]['composition'] = composition
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = prod.spans[-1]
    canvas = Canvas(prod.size)
    prod._actors(span, 4., canvas)
    assert len(canvas.boxes) == 3
    for e in span.motion.elements:
        x, y = e.x * prod.size[0], e.y * prod.size[1]
        w, h = e.width * prod.size[0] / 1920, e.height * prod.size[1] / 1080
        text_box = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
        assert all(b[2] <= text_box[0] or b[0] >= text_box[2] or
                   b[3] <= text_box[1] or b[1] >= text_box[3] for b in canvas.boxes)


def test_cinematic_endcard_joins_without_an_extra_hard_cut(tmp_path):
    prod, board, _, tl = production(tmp_path, ['Taro watched Nia.'])
    original = copy.deepcopy(tl)
    at = tl['end_card']['start']
    before = np.asarray(prod.frame(at - 1 / 30), dtype=float)
    after = np.asarray(prod.frame(at + 1 / 30), dtype=float)
    assert np.abs(after - before).mean() < 12
    settled = at + prod.spans[-1].join_length + .1
    assert prod.frame(settled).tobytes() == prod.whiteboard.frame(settled).tobytes()
    assert tl == original


def test_source_text_keeps_its_safe_position_under_the_follow_camera(tmp_path):
    prod, board, plan, tl = production(tmp_path, ['Taro ran past Nia.'])
    plan['style']['motion_floor'] = 'still'
    scene = plan['scenes'][-1]
    scene.update(camera='follow', composition='left_third',
                 elements=[{'kind': 'cast', 'ref': 'taro'}, {'kind': 'text', 'ref': scene['beat_ids'][0]}])
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    at = prod.spans[-1].start + 4.
    followed = np.asarray(prod.frame(at))
    scene['camera'] = 'static'
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    static = np.asarray(render.make_production(board, tl, 'en', tmp_path).frame(at))
    from PIL import ImageColor
    ink = ImageColor.getrgb(plan['style']['palette']['ink'])
    # The text-side pixels must be identical even as artwork travels and zooms.
    e = prod.spans[-1].motion.elements[0]
    left = round((e.x - e.width / 1920 / 2) * prod.size[0]) - 60
    right = round((e.x + e.width / 1920 / 2) * prod.size[0]) + 60
    assert np.array_equal((followed[:, left:right] == ink).all(axis=2),
                          (static[:, left:right] == ink).all(axis=2))
    assert (followed[:, left:right] == ink).all(axis=2).sum() > 100


def test_fear_and_warning_roar_keep_their_distinct_spoken_cues(tmp_path):
    text = "Nia's heart hammered against her ribs. She tried to let out a warning roar, but it became a squeak."
    prod, board, plan, tl = production(tmp_path, [text])
    scene = plan['scenes'][-1]
    bid = scene['beat_ids'][0]
    scene['actions'] = [{'actor': 'nia', 'verb': verb, 'at_beat': bid, 'intensity': 1}
                        for verb in ('tremble', 'roar')]
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    a, b = [a for _, a, _ in prod.spans[-1].actions]
    timing = tl['beats'][bid]
    assert prod.spans[-1].start + a.start == timing['start'] + timing['char_times'][text.index('heart')]
    assert prod.spans[-1].start + b.start == timing['start'] + timing['char_times'][text.index('roar')]
    assert b.start > a.start

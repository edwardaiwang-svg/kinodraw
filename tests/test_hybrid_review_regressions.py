"""Saved plans must preserve source ownership, readable dialogue and data coordinates."""
import copy
import json

import numpy as np
import pytest

from kinodraw.engine import render
from kinodraw.engine.bold.render import _text_metrics
from test_hybrid_character_motion import production
from test_scientific import project

# Story characters are preset doodles now; these checks cover the procedural rig path.
pytestmark = pytest.mark.usefixtures('procedural_rig')


def save(tmp_path, board, plan, tl, size=None, aspect='16:9'):
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    return render.make_production(board, tl, 'en', tmp_path, size=size, aspect=aspect)


@pytest.mark.parametrize('names', [('Nia', 'Sora', 'Taro'), ('Ayo', 'Luma', 'Beko')])
@pytest.mark.parametrize('source', ['{actor} never roared.', '{actor} no longer roared.',
                                   '{actor} watched {child}. She roared.',
                                   '{actor} watched the clouds.'])
def test_unsupported_saved_action_does_not_change_real_frame(tmp_path, names, source):
    child, _, actor = names
    text = source.format(actor=actor, child=child)
    _, board, plan, tl = production(tmp_path, [text], names, floor='still')
    for entry in plan['cast']:
        entry.update(species='wolf', family='canine', marks=['none'])
    scene = plan['scenes'][-1]
    scene['actions'] = [{'actor': actor.casefold(), 'verb': 'roar', 'at_beat': scene['beat_ids'][0], 'intensity': 3}]
    prod = save(tmp_path, board, plan, tl)
    span = prod.spans[-1]
    scene['actions'] = []
    idle = save(tmp_path, board, plan, tl)
    times = [span.start + n / 10 for n in range(1, 25)]
    assert all(prod.frame(t).tobytes() == idle.frame(t).tobytes() for t in times)
    assert not span.actions
    assert any('roar' in w and 'source' in w and 'skipped' in w for w in prod.warnings)


def test_no_longer_asleep_is_not_a_sleep_action(tmp_path):
    _, board, plan, tl = production(tmp_path, ['Taro watched the clouds. He was no longer asleep.'], floor='still')
    next(c for c in plan['cast'] if c['id'] == 'taro')['sex'] = 'male'
    scene = plan['scenes'][-1]
    scene['actions'] = [{'actor': 'taro', 'verb': 'sleep', 'at_beat': scene['beat_ids'][0], 'intensity': 3}]
    prod = save(tmp_path, board, plan, tl)
    scene['actions'] = []
    idle = save(tmp_path, board, plan, tl)
    span = prod.spans[-1]
    assert not span.actions
    assert prod.frame(span.end - .1).tobytes() == idle.frame(span.end - .1).tobytes()


def test_not_only_is_an_affirmative_action(tmp_path):
    _, board, plan, tl = production(tmp_path, ['Taro not only roared, but also swiped his paw.'], floor='still')
    scene = plan['scenes'][-1]
    scene['actions'] = [{'actor': 'taro', 'verb': verb, 'at_beat': scene['beat_ids'][0], 'intensity': 3}
                        for verb in ('roar', 'swipe')]
    prod = save(tmp_path, board, plan, tl)
    assert [action.name for _, action, _ in prod.spans[-1].actions] == ['roar', 'swipe']


@pytest.mark.parametrize('size,aspect', [(None, '16:9'), ((1080, 1080), '1:1'), (None, '9:16')])
def test_long_dialogue_pages_fit_and_wait_for_whole_dialogue(tmp_path, size, aspect):
    body = ('Every step we take together teaches us how to listen, how to wait, and how to find our way home. ' * 5).strip()
    text = f'Sora watched the clouds. "{body}"'
    _, board, plan, tl = production(tmp_path, [text], floor='still')
    beat = board['beats'][-1]
    beat['visuals'] = [{'id': 'source-quote', 'type': 'quote', 'text': {'en': body}}]
    scene = plan['scenes'][-1]
    scene.update(text={'kind': 'quote', 'ref': beat['id']}, elements=[{'kind': 'cast', 'ref': 'sora'}],
                 composition='left_third')
    output = save(tmp_path, board, plan, tl, size, aspect)
    prod = getattr(output, 'production', output)
    # Portrait is a letterboxed production, so inspect its actual source layout too.
    prod = getattr(prod, 'prod', prod)
    span = prod.spans[-1]
    pages = [e for e in span.motion.elements if e.preset == 'corner_caption']
    assert pages
    assert ' '.join(' '.join(e.text.split()) for e in pages).strip('“”') == body
    bare = copy.copy(span)
    bare.motion = copy.copy(span.motion)
    bare.motion.elements = []
    for page in pages:
        wrapped, _, size, _ = _text_metrics(page.text, page.size, page.width, True, page.font)
        assert size >= 40
        assert len(wrapped.splitlines()) * size * 1.15 <= page.height
        assert page.y + page.height / 2160 < .74
        at = span.start + page.start + .2
        output.frame(at)
        actual = np.asarray(prod._frame(span, at))
        no_text = np.asarray(prod._frame(bare, at))
        ys, xs = np.nonzero((actual != no_text).any(axis=2))
        assert len(xs) > 100
        assert min(xs) >= .025 * prod.size[0] and max(xs) < .975 * prod.size[0]
        assert min(ys) >= .025 * prod.size[1] and max(ys) < .74 * prod.size[1]
    spoken = beat['spoken']['en']
    assert pages[0].start >= tl['beats'][beat['id']]['char_times'][spoken.index(body)]
    assert all(a.end <= b.start for a, b in zip(pages, pages[1:]))
    assert all(a.start < b.start for a, b in zip(pages, pages[1:]))
    later = copy.copy(span)
    later.motion = copy.copy(span.motion)
    later.motion.elements = pages[1:]
    before = span.start + pages[0].start + .2
    assert prod._frame(later, before).tobytes() == prod._frame(bare, before).tobytes()


@pytest.mark.parametrize('outgoing', [False, True])
def test_scientific_join_keeps_actual_pixels_and_source_clock(tmp_path, outgoing):
    _, _, _, prod, span = project(tmp_path)
    index = prod.spans.index(span)
    if outgoing:
        following = prod.spans[index + 1]
        following.spec.update(treatment='motion', transition_in='zoom_through', camera='static')
        following.motion = prod.spans[0].motion
        following.join = following.start + .3
        for dt in (0., .1, .31, .5):
            at = following.start + dt
            expected = prod._frame(following, at).convert('RGBA')
            prod.whiteboard._caption(expected, at, prod.caption_look, prod.caption_accent)
            assert prod.frame(at).tobytes() == expected.convert('RGB').tobytes()
        # Scientific content must also clear immediately at the real end-card clock.
        prod.spans = prod.spans[:index + 1]
        prod.starts = prod.starts[:index + 1]
        at = prod.tl['end_card']['start']
        for dt in (0., 1/30, .2):
            assert prod.frame(at + dt).tobytes() == prod.whiteboard.frame(at + dt).tobytes()
    else:
        assert index
        span.spec.update(camera='shake', transition_in='zoom_through')
        span.join = span.start + .3  # A score grid must not postpone the plot.
        for dt in (0., .1, .31, .5):
            at = span.start + dt
            expected = prod._frame(span, at).convert('RGBA')
            prod.whiteboard._caption(expected, at, prod.caption_look, prod.caption_accent)
            assert prod.frame(at).tobytes() == expected.convert('RGB').tobytes()


@pytest.mark.parametrize('names', [('Nia', 'Sora', 'Taro'), ('Ayo', 'Luma', 'Beko')])
@pytest.mark.parametrize('pronoun', [False, True])
def test_owned_literal_action_uses_spoken_verb_and_changes_real_frame(tmp_path, names, pronoun):
    child, _, actor = names
    text = f'{actor} watched the clouds. He roared.' if pronoun else f'{actor} roared.'
    _, board, plan, tl = production(tmp_path, [text], names, floor='still')
    for entry in plan['cast']:
        entry.update(species='wolf', family='canine', marks=['none'])
    scene = plan['scenes'][-1]
    bid = scene['beat_ids'][0]
    scene['actions'] = [{'actor': actor.casefold(), 'verb': 'roar', 'at_beat': bid, 'intensity': 3}]
    prod = save(tmp_path, board, plan, tl)
    span = prod.spans[-1]
    action = span.actions[0][1]
    spoken = prod.by_id[bid]['spoken']
    assert span.start + action.start == tl['beats'][bid]['start'] + tl['beats'][bid]['char_times'][spoken.index('roared')]
    scene['actions'] = []
    idle = save(tmp_path, board, plan, tl)
    at = span.start + action.start + action.seconds * .5
    assert prod.frame(at).tobytes() != idle.frame(at).tobytes()

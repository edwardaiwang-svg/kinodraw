import copy
import json

import numpy as np
import pytest

from kinodraw import ingest, script, pipeline
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline

# Story characters are preset doodles now; these checks cover the procedural rig path.
pytestmark = pytest.mark.usefixtures('procedural_rig')


def fixture(tmp_path):
    board = script.build(ingest.read('# Small story\n\nPendo, a lion cub, watched Mara, a tigress.\n\nMara nudged Pendo.\n\nKojo, a male lion with a massive black mane, roared at the hyenas.\n\nThick fog held a shooting star.'), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for i, scene in enumerate(plan['scenes']):
        scene['treatment'] = ('whiteboard', 'motion', 'character', 'atmosphere')[i % 4]
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    return board, plan, tl


def test_saved_plan_dispatch_and_source_spans(tmp_path):
    board, plan, tl = fixture(tmp_path)
    prod = render.make_production(board, tl, 'en', tmp_path)
    assert type(prod).__name__ == 'HybridProduction'
    assert prod.duration == tl['duration']
    for span in prod.spans:
        assert span.start == tl['beats'][span.spec['beat_ids'][0]]['start']
    assert prod.ctx is prod.whiteboard.ctx


def test_whiteboard_exact_and_disabled(tmp_path):
    board, plan, tl = fixture(tmp_path)
    raw = render.Production(board, tl, 'en', tmp_path)
    prod = render.make_production(board, tl, 'en', tmp_path)
    t = tl['beats'][plan['scenes'][0]['beat_ids'][0]]['start'] + .1
    assert prod.frame(t).tobytes() == raw.frame(t).tobytes()
    plan['style']['mode'] = 'whiteboard'
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    assert type(render.make_production(board, tl, 'en', tmp_path)) is render.Production
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': False, 'plan_v3': plan}))
    assert type(render.make_production(board, tl, 'en', tmp_path)) is render.Production


def test_cast_translation_and_atmos_range(tmp_path):
    from kinodraw.engine.hybrid import cast_genome
    board, plan, tl = fixture(tmp_path)
    cast = {c['name']: cast_genome(c) for c in plan['cast']}
    assert cast['Pendo'].age == 'baby'
    assert cast['Mara'].species == 'tiger' and 'stripes' in cast['Mara'].marks
    assert 'mane_black' in cast['Kojo'].marks
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = next(s for s in prod.spans if s.spec['treatment'] == 'atmosphere')
    a = np.asarray(prod.frame(span.start + 1))
    assert a.dtype == np.uint8 and a.max() > 100
    assert not np.array_equal(a, np.asarray(prod.frame(span.start + 1.5)))


def test_actions_word_times_group_and_receiver(tmp_path):
    board, plan, tl = fixture(tmp_path)
    plan['scenes'][1]['treatment'] = 'character'
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    span = prod.spans[1]
    actor, action, target = next(e for e in span.actions if e[1].name == 'nudge')
    assert actor == 'mara' and target == 'pendo'
    text = board['beats'][1]['spoken']['en']
    assert action.start == tl['beats'][board['beats'][1]['id']]['char_times'][text.index('nudged')]
    assert {'mara', 'pendo'} <= set(span.actors)
    crowd = prod.spans[2]
    assert len([a for a in crowd.actors if a.startswith('crowd-hyena-')]) == 2
    t = span.start + action.start + action.seconds * .6
    a = np.asarray(prod.frame(t))
    changed = copy.deepcopy(plan)
    changed['scenes'][1]['actions'] = []
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': changed}))
    other = render.make_production(board, tl, 'en', tmp_path)
    assert not np.array_equal(a, np.asarray(other.frame(t)))


def test_actions_cue_their_synthesized_sounds(tmp_path):
    from kinodraw.audio import sfx
    board = script.build(ingest.read('# Night\n\nPendo, a lion cub, watched Mara, a tigress.\n\nPendo whimpered in the dark.'
                                     '\n\nThe hyenas laughed at Pendo.\n\nKojo, a male lion with a massive black mane, '
                                     'roared at the hyenas.\n\nMara swiped at the hyenas.\n\nMara nudged Pendo.'), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for scene in plan['scenes']:
        scene['treatment'] = 'character'
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = save_production(tmp_path, board, plan, tl)
    acted = {action.name: (i, j) for i, span in enumerate(prod.spans) for j, (_, action, _) in enumerate(span.actions)}
    assert {'whimper', 'laugh', 'roar', 'swipe', 'nudge'} <= set(acted)
    cues = {c['id']: c for c in prod.cues()}
    for name, kind in {'whimper': 'whimper', 'laugh': 'hyena_cackle', 'roar': 'roar', 'swipe': 'swipe',
                       'nudge': 'nudge'}.items():
        cue = cues['hybrid.action.%d.%d' % acted[name]]
        assert cue['kind'] == kind
        y = sfx.render([cue], prod.duration)
        at = round(cue['t'] * sfx.SAMPLE_RATE)
        assert np.abs(y[at:at + sfx.SAMPLE_RATE // 10]).max() > 1e-3                 # it sounds on the action's cue


def test_every_action_sound_plays_at_full_strength_and_puffs_follow_the_exhales(tmp_path):
    from kinodraw.engine.creatures.actions import action_pose
    board = script.build(ingest.read('# Night\n\nPendo, a lion cub, watched Mara, a tigress.\n\nPendo whimpered.\n\n'
                                     'After the long run through the tall wet grass of the valley, Pendo was breathing '
                                     'heavily and could not keep up with anyone at all that night.\n\nMara laughed at '
                                     'Pendo.\n\nKojo, a male lion, pounced on the hyenas.'), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing')
    for scene in plan['scenes']:
        scene['treatment'] = 'character'
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = save_production(tmp_path, board, plan, tl)
    cues = prod.cues()
    acted = [c for c in cues if c['id'].startswith('hybrid.action.')]
    assert all(c.get('strength', 1) == 1 for c in acted)                    # intensity no longer buries a sound
    kinds = {}
    for i, span in enumerate(prod.spans):
        for j, (actor, action, _) in enumerate(span.actions):
            kinds[action.name] = [c['kind'] for c in acted if c['id'].split('.')[2:4] == [str(i), str(j)]]
            if action.name == 'breathe_heavy':
                puffs = [c['t'] - span.start for c in acted if c['id'].split('.')[2:4] == [str(i), str(j)]]
                exhales = [x for x in np.arange(.01, action.seconds, .01)
                           if action_pose(action, action.start + x).puffs > 0 >= action_pose(action, action.start + x - .01).puffs]
                assert len(puffs) == len(exhales) >= 2 and np.allclose(puffs, [action.start + x for x in exhales])
    assert kinds['whimper'] == ['whimper'] and kinds['laugh'] == ['hyena_cackle'] and kinds['pounce'] == ['impact']
    assert set(kinds['breathe_heavy']) == {'breath_puff'}


def test_scenes_cue_chapter_whooshes_beds_shooting_stars_and_typing(tmp_path):
    from kinodraw.audio import sfx
    from kinodraw.engine.bold.model import TYPE_CPS
    board = script.build(ingest.read('# Night\n\n## The storm\n\nRain fell on the valley all night.\n\nThe wind blew dust '
                                     'over the plain.\n\n## The morning\n\nThick fog held a shooting star.\n\nEvery cub '
                                     'must learn to read the sky.'))
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='breathing', music_mood='warm', tempo_bpm=96)
    by_beat = {s['beat_ids'][0]: s for s in plan['scenes']}
    by_beat['b005'].update(treatment='atmosphere', atmosphere={'kind': 'rain', 'density': .55})
    by_beat['b006'].update(treatment='atmosphere', atmosphere={'kind': 'dust', 'density': .55})
    by_beat['b008'].update(treatment='atmosphere', atmosphere={'kind': 'fog_with_shooting_star', 'density': .55})
    by_beat['b009'].update(treatment='kinetic_type', text={'kind': 'kinetic', 'ref': 'b009'})
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = save_production(tmp_path, board, plan, tl)
    cues = prod.cues()
    spans = {s.spec['beat_ids'][0]: (i, s) for i, s in enumerate(prod.spans)}
    sections = [board['beats'][int(s.spec['beat_ids'][0][1:]) - 1]['chapter'] for s in prod.spans]
    for i, span in enumerate(prod.spans[1:], 1):                             # the long whoosh marks new chapters only
        scene = next(c for c in cues if c['id'] == f'hybrid.scene.{i}')
        assert (scene['kind'] == 'transition_whoosh') == (sections[i] != sections[i - 1])
        assert scene['kind'] != 'transition_whoosh' or scene['dur'] == span.join_length
    assert sum(c['kind'] == 'transition_whoosh' for c in cues) == len(set(sections)) - 1
    for beat, bed in (('b005', 'rain'), ('b006', 'wind'), ('b008', 'fog_drone')):   # a bed for the scene's time on screen
        i, span = spans[beat]
        cue = next(c for c in cues if c['id'] == f'hybrid.bed.{i}')
        assert cue['kind'] == bed and cue['t'] == span.join and cue['t'] + cue['dur'] == prod.spans[i + 1].join
    i, span = spans['b008']
    star = next(c for c in cues if c['kind'] == 'shooting_star')
    a, b = (span.start + x for x in next(o['window'] for name, _, o in span.atmos.layers if name == 'shooting_star'))
    assert star['t'] == min(beat for beat in prod.score_beats if a <= beat < b)          # while the star crosses
    i, span = spans['b009']
    typed = [e for e in span.motion.elements if e.kind == 'text' and e.preset == 'type_on' and e.text.strip()]
    ticks = [c['t'] for c in cues if c['kind'] == 'type_tick']
    assert typed and len(ticks) == sum(not ch.isspace() for e in typed for ch in e.text)
    assert ticks[0] == span.start + typed[0].start + (len(typed[0].text) - len(typed[0].text.lstrip()) + 1) / TYPE_CPS
    for kind in ('transition_whoosh', 'rain', 'wind', 'fog_drone', 'shooting_star', 'type_tick'):
        cue = next(c for c in cues if c['kind'] == kind)
        y = sfx.render([cue], prod.duration)
        at = round(cue['t'] * sfx.SAMPLE_RATE)
        assert np.abs(y[at:at + sfx.SAMPLE_RATE // 10]).max() > 1e-4, kind      # it sounds from its cue


def test_saved_plan_no_provider_and_series_override(tmp_path):
    source = '# Cast\n\nMara, a lioness, nudged Pendo, a lion cub.'
    pipeline.new_project(source, tmp_path, director_v3=True,
                         series_bible={'cast': [{'id': 'mara', 'species': 'tigress', 'marks': ['stripes']}]})
    pipeline.direct_v3(tmp_path)
    cfg = pipeline.settings(tmp_path)
    mother = next(c for c in cfg['plan_v3']['cast'] if c['id'] == 'mara')
    assert mother['species'] == 'tigress'
    assert cfg['series_bible']['cast'] == cfg['plan_v3']['cast']
    class Forbidden:
        def direct_plan(self, *args):
            raise AssertionError('saved plan must not call provider')
    pipeline.direct_v3(tmp_path, Forbidden(), prop_llm=lambda _: (_ for _ in ()).throw(AssertionError()))


def test_injected_props_sanitized_persisted_and_cached(tmp_path):
    from kinodraw.engine.hybrid import prepare_props
    from kinodraw.library import resolve
    from types import SimpleNamespace
    board, plan, tl = fixture(tmp_path)
    plan['style']['palette'].update(background='#FFFFFF', ink='#1B1B1B', accent='#E53935', accent2='#E53935')
    scene = plan['scenes'][1]
    scene['elements'] = [{'kind': 'picture', 'ref': 'book_stack'}]
    for other in (plan['scenes'][0], plan['scenes'][3]):
        other['treatment'] = 'character'
    good = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
            'fill="#E53935" stroke="#1B1B1B" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">'
            '<rect x="40" y="40" width="432" height="432"/>'
            '<circle cx="160" cy="160" r="30"/><circle cx="350" cy="160" r="30"/>'
            '<path d="M100 300 H400" fill="none"/><path d="M100 350 H400" fill="none"/>'
            '<script>alert(1)</script><image href="https://invalid"/></svg>')
    calls = []
    def llm(prompt):
        calls.append(prompt)
        return good
    offered = {b: [SimpleNamespace(score=.2)] for b in scene['beat_ids']}
    prepare_props(plan, board, tmp_path, llm, offered)
    ref = scene['elements'][0]['ref']
    assert ref.startswith('gen-') and len(calls) == 1
    content = resolve(ref, tmp_path).read_text()
    assert 'script' not in content and 'href' not in content
    prepare_props(plan, board, tmp_path, llm, offered)
    assert len(calls) == 1
    scene['elements'] = [{'kind': 'picture', 'ref': 'book_stack'}]
    offered = {b: [SimpleNamespace(score=.9)] for b in scene['beat_ids']}
    prepare_props(plan, board, tmp_path, llm, offered)
    assert len(calls) == 1 and scene['elements'][0]['ref'] == 'book_stack'


@pytest.mark.parametrize('kind', ['cut', 'wipe', 'iris', 'match', 'zoom_through', 'page', 'morph'])
def test_transition_endpoints_deterministic(tmp_path, kind):
    board, plan, tl = fixture(tmp_path)
    plan['scenes'][1]['transition_in'] = kind
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    first = render.make_production(board, tl, 'en', tmp_path)
    second = render.make_production(board, tl, 'en', tmp_path)
    at = first.spans[1].start
    for t in (at, at + .2, at + .65):
        assert first.frame(t).tobytes() == second.frame(t).tobytes()


def test_kinetic_and_chart_use_source_data(tmp_path):
    board, plan, tl = fixture(tmp_path)
    plan['scenes'][1].update(treatment='kinetic_type', text={'kind': 'kinetic', 'ref': board['beats'][1]['id']})
    plan['scenes'][2]['treatment'] = 'chart'
    board['beats'][2]['visuals'] = [{'id': 'bars', 'type': 'bars', 'title': {'en': 'Facts'}, 'unit': {'en': ''},
        'rows': [{'label': {'en': 'A'}, 'value': 2, 'display': {'en': '2'}},
                 {'label': {'en': 'B'}, 'value': 4, 'display': {'en': '4'}}]}]
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    prod = render.make_production(board, tl, 'en', tmp_path)
    assert prod.spans[1].motion.elements[-1].preset == 'type_on'
    chart = next(e for e in prod.spans[2].motion.elements if e.kind == 'chart')
    assert chart.values == (2, 4) and chart.labels == ('A', 'B')
    a = prod.frame(prod.spans[2].start + .8)
    assert np.asarray(a).std() > 10


def save_production(tmp_path, board, plan, tl):
    tmp_path.joinpath('project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    return render.make_production(board, tl, 'en', tmp_path)


def test_score_joins_and_cues_preserve_source_timing(tmp_path):
    board, plan, tl = fixture(tmp_path)
    original = copy.deepcopy(tl)
    plan['style'].update(music_mood='warm', tempo_bpm=96)
    prod = save_production(tmp_path, board, plan, tl)
    assert tl == original and prod.duration == original['duration']
    # warm selects the measured 100 BPM recording, not the requested 96 BPM.
    assert prod.score_beats[1] == pytest.approx(.6)
    for span in prod.spans[1:]:
        assert span.start <= span.join <= span.end - span.join_length
        assert min(abs(prod.score_beats - span.join)) < 1e-8
    for cue in prod.cues():
        assert min(abs(prod.score_beats - cue['t'])) < 1e-8
    span = prod.spans[1]
    assert prod.frame(span.join + .1).tobytes() == save_production(tmp_path, board, plan, tl).frame(span.join + .1).tobytes()


@pytest.mark.parametrize('family', ['hand', 'rounded', 'serif', 'mono', 'display'])
def test_type_adapter_uses_bundled_font_and_fits(tmp_path, family):
    from kinodraw.engine.bold.render import _element_content, TYPE_FONTS, _text_metrics
    board, plan, tl = fixture(tmp_path)
    plan['style']['type'] = family
    scene = plan['scenes'][1]
    scene.update(text={'kind': 'title', 'ref': scene['beat_ids'][0]}, elements=[])
    prod = save_production(tmp_path, board, plan, tl)
    motion = prod.spans[1].motion
    e = motion.elements[0]
    fragment = _element_content(motion, e, 0, 2)[1]
    assert TYPE_FONTS[family][0] in fragment
    _, font, size, _ = _text_metrics(e.text, e.size, e.width, False, family)
    assert font.getlength(e.text) * size / font.size <= e.width + 1e-6
    assert np.asarray(prod.frame(prod.spans[1].start + 1)).std() > 10


def test_explicit_text_grid_and_cast_slots(tmp_path):
    board, plan, tl = fixture(tmp_path)
    scene = plan['scenes'][1]
    scene.update(composition='grid', treatment='motion', text={'kind': 'none', 'ref': ''},
                 elements=[{'kind': 'text', 'ref': scene['beat_ids'][0]},
                           {'kind': 'cast', 'ref': 'mara'}, {'kind': 'cast', 'ref': 'pendo'}])
    prod = save_production(tmp_path, board, plan, tl)
    span = prod.spans[1]
    e = span.motion.elements[0]
    assert e.text == board['beats'][1]['display']['en']
    assert (e.x, e.y) == (.25, .5)
    slots = [prod._actor_slot(span, a) for a in span.actors]
    assert len(set(slots)) == len(span.actors)
    assert {p[:2] for p in slots}.isdisjoint({(e.x, e.y)})


def test_atomic_quote_never_typewrites_or_drops_speaker(tmp_path):
    from kinodraw.engine.bold.render import _element_content
    board, plan, tl = fixture(tmp_path)
    scene = plan['scenes'][1]
    scene.update(treatment='kinetic_type', elements=[], text={'kind': 'quote', 'ref': scene['beat_ids'][0]})
    board['beats'][1]['visuals'] = [{'id': 'quote', 'type': 'quote',
        'text': {'en': 'Stay together and keep moving.'}, 'who': {'en': 'The guide'}}]
    prod = save_production(tmp_path, board, plan, tl)
    motion = prod.spans[1].motion
    e = motion.elements[0]
    early = _element_content(motion, e, 0, .01)[1]
    assert 'Stay together' in early and 'The guide' in early
    assert early == _element_content(motion, e, 0, 1.)[1]


@pytest.mark.parametrize('visual', [
    {'id': 'facts', 'type': 'stat', 'value': {'en': '42%'}, 'label': {'en': 'Share'}},
    {'id': 'facts', 'type': 'grid100', 'filled': 42, 'title': {'en': 'Share'}, 'legend': []},
    {'id': 'facts', 'type': 'line', 'rows': [{'value': 2, 'label': 'A'}, {'value': 4, 'label': 'B'}]},
])
def test_chart_adapters_preserve_facts(tmp_path, visual):
    board, plan, tl = fixture(tmp_path)
    scene = plan['scenes'][1]
    scene.update(treatment='chart', elements=[], text={'kind': 'none', 'ref': ''})
    board['beats'][1]['visuals'] = [visual]
    prod = save_production(tmp_path, board, plan, tl)
    elements = prod.spans[1].motion.elements
    if visual['type'] == 'stat':
        assert elements[0].text == '42%\nShare'
    elif visual['type'] == 'grid100':
        assert elements[0].svg.count('opacity="1"') == 42
        assert elements[0].svg.count('<rect') == 100
    else:
        assert elements[0].chart == 'line' and elements[0].values == (2, 4)
    assert not any('cutaway' in w for w in prod.warnings)


def test_page_is_not_wipe_and_endpoints_exact():
    from kinodraw.engine.bold import render_transition
    a = np.full((60, 100, 3), 200, np.uint8)
    b = np.full_like(a, 30)
    assert np.array_equal(render_transition(a, b, 0, 100, 60, kind='page'), a)
    assert np.array_equal(render_transition(a, b, .65, 100, 60, kind='page'), b)
    assert not np.array_equal(render_transition(a, b, .3, 100, 60, kind='page'),
                              render_transition(a, b, .3, 100, 60, kind='wipe'))


def test_follow_tracks_subject_instead_of_center_push(tmp_path):
    board, plan, tl = fixture(tmp_path)
    scene = plan['scenes'][1]
    scene.update(camera='follow', composition='left_third', treatment='motion',
                 elements=[], actions=[], text={'kind': 'title', 'ref': scene['beat_ids'][0]})
    prod = save_production(tmp_path, board, plan, tl)
    t = prod.spans[1].start + 1
    followed = prod.frame(t).tobytes()
    scene['camera'] = 'slow_push'
    assert followed != save_production(tmp_path, board, plan, tl).frame(t).tobytes()


def test_settled_foreground_motion_meets_probe_floor(tmp_path):
    from kinodraw.engine.bold import render_frame
    board, plan, tl = fixture(tmp_path)
    plan['style']['motion_floor'] = 'lively'
    scene = plan['scenes'][1]
    scene.update(elements=[], text={'kind': 'title', 'ref': scene['beat_ids'][0]})
    prod = save_production(tmp_path, board, plan, tl)
    motion = prod.spans[1].motion
    frames = [render_frame(motion, 2 + i / 30, 320, 180).astype(float) for i in range(16)]
    assert max(np.abs(a - b).mean() / 255 for a, b in zip(frames, frames[1:])) >= .001


def test_interacting_cast_shares_grid_cell(tmp_path):
    board, plan, tl = fixture(tmp_path)
    plan['scenes'][1].update(composition='grid', treatment='character', elements=[],
                             text={'kind': 'none', 'ref': ''})
    prod = save_production(tmp_path, board, plan, tl)
    span = prod.spans[1]
    actor, action, target = next(a for a in span.actions if a[1].name == 'nudge')
    assert any(actor in g and target in g for g in prod._cast_groups(span))
    assert prod._actor_slot(span, actor)[1] == prod._actor_slot(span, target)[1]


@pytest.mark.parametrize('kind', ['whiteboard', 'motion', 'kinetic_type', 'atmosphere', 'chart', 'character'])
def test_all_six_dispatch_real_frames(tmp_path, kind):
    board, plan, tl = fixture(tmp_path)
    scene = plan['scenes'][1]
    scene['treatment'] = kind
    if kind in ('motion', 'kinetic_type'):
        scene['text'] = {'kind': 'title', 'ref': scene['beat_ids'][0]}
    if kind == 'chart':
        scene['text'] = {'kind': 'none', 'ref': ''}
        board['beats'][1]['visuals'] = [{'id': 'fact', 'type': 'stat', 'value': '42', 'label': 'Count'}]
    if kind == 'atmosphere':
        scene['atmosphere'] = {'kind': 'night_stars', 'density': 1}
    prod = save_production(tmp_path, board, plan, tl)
    frame = prod.frame(prod.spans[1].start + 1)
    assert frame.size == prod.size and np.asarray(frame).std() > 10
    if kind == 'whiteboard':
        assert frame.tobytes() == prod.whiteboard.frame(prod.spans[1].start + 1).tobytes()
    else:
        assert frame.convert('RGB').tobytes() != prod.whiteboard.frame(prod.spans[1].start + 1).convert('RGB').tobytes()


def test_caption_only_does_not_invent_foreground_text(tmp_path):
    board, plan, tl = fixture(tmp_path)
    scene = plan['scenes'][1]
    scene.update(treatment='motion', elements=[], text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    prod = save_production(tmp_path, board, plan, tl)
    assert not prod.spans[1].motion.elements
    scene['elements'] = [{'kind': 'text', 'ref': scene['beat_ids'][0]}]
    assert len(save_production(tmp_path, board, plan, tl).spans[1].motion.elements) == 1


def test_whiteboard_join_has_no_stale_caption(tmp_path):
    board, plan, tl = fixture(tmp_path)
    prod = save_production(tmp_path, board, plan, tl)
    assert prod.cutaway.cap_starts == []
    assert prod.whiteboard.cap_starts == [c['start'] for c in tl['captions']]
    t = prod.spans[0].start + .5
    assert prod.frame(t).tobytes() == render.Production(board, tl, 'en', tmp_path).frame(t).tobytes()


def test_mono_type_has_fixed_advance():
    import re
    from kinodraw.engine.bold import MotionElement, MotionScene
    from kinodraw.engine.bold.render import _element_content
    e = MotionElement(text='WiWi', font='mono', preset='type_on')
    fragment = _element_content(MotionScene([e]), e, 0, 2)[1]
    xs = [float(x) for x in re.findall(r'<text x="([^"]+)"', fragment)]
    assert len(xs) == 4
    assert np.allclose(np.diff(xs), np.diff(xs)[0])


def test_pure_whiteboard_plan_uses_exact_legacy_production(tmp_path):
    board, plan, tl = fixture(tmp_path)
    for scene in plan['scenes']:
        scene['treatment'] = 'whiteboard'
    prod = save_production(tmp_path, board, plan, tl)
    assert type(prod) is render.Production
    raw = render.Production(board, tl, 'en', tmp_path)
    assert prod.frame(1).tobytes() == raw.frame(1).tobytes()


def test_text_plan_does_not_invent_cast_from_narration(tmp_path):
    board, plan, tl = fixture(tmp_path)
    scene = plan['scenes'][1]
    scene.update(treatment='motion', elements=[], actions=[],
                 text={'kind': 'quote', 'ref': scene['beat_ids'][0]})
    prod = save_production(tmp_path, board, plan, tl)
    assert prod.spans[1].actors == ()


# Review regressions exercise validated saved plans, without a provider.
def review_fixture(text):
    board = script.build(ingest.read('# Review\n\n' + text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', music_mood='none')
    for scene in plan['scenes']:
        scene.update(treatment='character', elements=[], camera='static', transition_in='cut',
                     text={'kind': 'none', 'ref': ''})
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    return board, plan, tl


def validated_review_production(tmp_path, board, plan, tl):
    from kinodraw.director.v3.validate import validate
    validated, repairs = validate(plan, board, {})
    assert not repairs, repairs
    return save_production(tmp_path, board, validated, tl)


@pytest.mark.parametrize('text, name', [
    ('Pendo, a lion cub, waited. Mara, a tigress, roared. Pendo roared.', 'Pendo'),
    ('Ivo, a wolf pup, waited. Nia, a fox, roared. Ivo roared.', 'Ivo'),
    ('King Kito, a lion, waited. Luma, a tigress, roared. Kito roared.', 'King Kito'),
    ('Pendo, a lion cub, did not roar. Mara, a tigress, roared. Pendo roared.', 'Pendo'),
    ('Pendo, a lion cub, waited while Mara, a tigress, roared; Pendo roared.', 'Pendo'),
])
def test_review_action_uses_same_actor_clause(tmp_path, text, name):
    board, plan, tl = review_fixture(text)
    from kinodraw.director.v3.semantics import name_key
    actor = next(c for c in plan['cast'] if name_key(c['name']) == name_key(name))
    actor['name'] = name  # A saved title may be absent from later narration mentions.
    assert any(a['actor'] == actor['id'] and a['verb'] == 'roar' for a in plan['scenes'][0]['actions'])
    original = copy.deepcopy((board, plan, tl))
    prod = validated_review_production(tmp_path, board, plan, tl)
    action = next(a for key, a, _ in prod.spans[0].actions if key == actor['id'] and a.name == 'roar')
    spoken = board['beats'][0]['spoken']['en']
    expected = tl['beats'][board['beats'][0]['id']]['char_times'][spoken.rindex('roared')]
    assert action.start == expected
    assert (board, plan, tl) == original


@pytest.mark.parametrize('has_quote', [True, False])
def test_review_grouped_quote_uses_referenced_beat(tmp_path, has_quote):
    board, plan, tl = review_fixture('First source statement.\n\nSecond readable statement.')
    first, second = board['beats']
    first['visuals'] = [{'id': 'q1', 'type': 'quote', 'text': {'en': 'First quote'}, 'who': {'en': 'First speaker'}}]
    second['visuals'] = ([{'id': 'q2', 'type': 'quote', 'text': {'en': 'Second quote'},
                           'who': {'en': 'Second speaker'}}] if has_quote else [])
    scene = plan['scenes'][0]
    scene.update(beat_ids=[first['id'], second['id']], treatment='kinetic_type', actions=[],
                 text={'kind': 'quote', 'ref': second['id']}, hold_s=10)
    plan['scenes'] = [scene]
    prod = validated_review_production(tmp_path, board, plan, tl)
    element = prod.spans[0].motion.elements[0]
    assert element.preset == 'corner_caption'
    assert 'First quote' not in element.text and 'First speaker' not in element.text
    assert ('Second quote' if has_quote else 'Second readable statement.') in element.text
    assert ('Second speaker' in element.text) == has_quote


@pytest.mark.parametrize('text, count', [
    ('A single hyena stood alone.', 1),
    ('Three hyenas stood together.', 3),
    ('2 hyenas stood together.', 2),
    ('The hyenas stood together.', 2),
    ('No hyenas stood there.', 0),
])
def test_review_hyenas_follow_intent_and_source_quantity(tmp_path, text, count):
    board, plan, tl = review_fixture(text)
    scene = plan['scenes'][0]
    scene.update(treatment='kinetic_type', elements=[], actions=[],
                 text={'kind': 'kinetic', 'ref': board['beats'][0]['id']})
    prod = validated_review_production(tmp_path, board, plan, tl)
    assert not prod.spans[0].actors
    scene['treatment'] = 'character'
    prod = validated_review_production(tmp_path, board, plan, tl)
    assert len([key for key in prod.spans[0].actors if prod.cast[key].species == 'hyena']) == count
    if text.startswith('The hyenas'):
        assert any('unspecified' in w and 'representatives' in w for w in prod.warnings)


def test_review_single_hyena_reuses_source_cast(tmp_path):
    board, plan, tl = review_fixture('A single hyena stood alone.')
    from kinodraw.director.v3.schema import CAST
    from kinodraw.director.v3.validate import _default
    animal = _default(CAST)
    animal.update(id='solitary', name='Hyena', kind='quadruped', species='hyena', family='other',
                  age='adult', sex='unknown', size=.75, marks=['spots'], temperament='gentle',
                  palette={'body': '#998267', 'accent': '#DBC5A2', 'eye': '#C59243'})
    plan['cast'] = [animal]
    plan['scenes'][0]['elements'] = [{'kind': 'cast', 'ref': animal['id']}]
    prod = validated_review_production(tmp_path, board, plan, tl)
    assert prod.spans[0].actors == ('solitary',)
    assert not any(key.startswith('crowd-hyena-') for key in prod.cast)


def test_review_picture_read_is_explicit_utf8(tmp_path, monkeypatch):
    from pathlib import Path
    board, plan, tl = review_fixture('A picture holds an idea.')
    prop = tmp_path / 'review-prop.svg'
    prop.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text x="10" y="50">café</text></svg>', encoding='utf-8')
    plan['scenes'][0].update(treatment='motion', elements=[{'kind': 'picture', 'ref': 'review-prop'}])
    monkeypatch.setattr('kinodraw.engine.hybrid.library.resolve', lambda *_: prop)
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path == prop:
            assert kwargs.get('encoding') == 'utf-8'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    # Offer the picture explicitly to the same validator used for saved production plans.
    from kinodraw.director.v3.validate import validate
    validated, repairs = validate(plan, board, {board['beats'][0]['id']: ['review-prop']})
    assert not repairs, repairs
    prod = save_production(tmp_path, board, validated, tl)
    assert 'café' in prod.spans[0].motion.elements[0].svg

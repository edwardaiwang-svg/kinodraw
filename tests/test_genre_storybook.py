"""Recipes, lessons, promos and updates with people in them get the storybook's staging (sets for places, people
presets with real skin tones, the plan's shots), not the hybrid's small figures beside stamp-sized icons on blank
paper. Boards, charts, diagrams, kinetic type and scenes whose text is a title, call to action or counter stay motion
scenes, and nothing that belongs to a picture book (its title page, its "The End") reaches them."""
import json

import numpy as np

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline
from kinodraw.engine.auto_scenes import end_heading
from kinodraw.engine.shots import SKIN

TEXT = """# Weekend Pancakes

Ben heats the pan in the kitchen and smiles at the camera.

Ava cracks one egg into the bowl.

Three ingredients. One bowl. Ten minutes.

Download the recipe card today.
"""
COOKS = [{'id': 'ben', 'name': 'Ben', 'kind': 'human', 'species': 'human', 'age': 'adult', 'sex': 'male',
          'palette': {'body': '#547A66', 'accent': '#D47A24', 'eye': '#302D29'}},
         {'id': 'ava', 'name': 'Ava', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female',
          'palette': {'body': '#4B806A', 'accent': '#C8795B', 'eye': '#302D29'}}]


def shot(bid, kind, cast, place='kitchen', props=(), speaking='no', focus=None):
    return {'beat_id': bid, 'starts_at': '', 'shot': kind, 'setting': {'place': place, 'time': 'day', 'set_refs': []},
            'cast': [{'id': c, 'age': 'adult' if c == 'ben' else 'child', 'pose': 'hold', 'speaking': speaking}
                     for c in cast],
            'lines': [], 'props': [{'ref': p, 'relation': 'none', 'to': '', 'motion': 'none'} for p in props],
            'focus_ref': focus if focus is not None else props[0] if props else '', 'writing': ''}


def produce(tmp_path, genre='lesson', insert=None, text=TEXT):
    """A plan of this genre: two character scenes with kitchen shots, then a kinetic-type scene and a character
    scene whose text is a call to action."""
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['storyboard']['genre'] = genre
    plan['style']['mode'] = 'hybrid'
    plan['cast'] = [dict(c, family='human', size=1, marks=[], temperament='calm') for c in COOKS]
    ids = [bid for s in plan['scenes'] for bid in s['beat_ids']]
    plan['scenes'] = [dict(plan['scenes'][0], beat_ids=[bid]) for bid in ids]
    for scene, bid in zip(plan['scenes'], ids):
        scene.update(treatment='character', composition='stage', camera='slow_push', actions=[],
                     text={'kind': 'caption_only', 'ref': bid},
                     elements=[{'kind': 'cast', 'ref': c['id']} for c in COOKS])
    plan['scenes'][0]['shots'] = [shot(ids[0], 'wide', ['ben'])]
    plan['scenes'][1]['shots'] = [insert(ids[1]) if insert else shot(ids[1], 'insert', ['ava'], props=['fl_egg'])]
    plan['scenes'][2].update(treatment='kinetic_type', text={'kind': 'kinetic', 'ref': ids[2]})
    plan['scenes'][3].update(text={'kind': 'cta', 'ref': ids[3]}, shots=[shot(ids[3], 'medium', ['ben'])])
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    return prod


def test_people_in_a_lesson_are_staged_by_the_storybook_and_text_scenes_stay_motion_scenes(tmp_path):
    prod = produce(tmp_path)
    first, insert, kinetic, cta = prod.spans
    assert first.story is not None and insert.story is not None
    assert [p.place for p in first.story] == ['kitchen']           # a named place gets its set
    assert insert.story[0].framing == 'insert'
    assert kinetic.story is None and cta.story is None              # kinetic type and a call to action keep their text


def test_a_lesson_has_no_picture_book_title_page_and_ends_on_its_title(tmp_path):
    prod = produce(tmp_path)
    assert all(page.title is None for span in prod.spans if span.story for page in span.story)
    assert end_heading(prod.whiteboard.ctx) == 'Weekend Pancakes'   # the Studio's story setting does not make it a story
    assert end_heading(produce(tmp_path / 'story', genre='story').whiteboard.ctx) == 'The End'


def test_a_person_never_takes_the_palette_body_colour_as_skin(tmp_path):
    prod = produce(tmp_path)
    tones = {'#%02X%02X%02X' % rgb for rgb in SKIN.values()}
    for c in COOKS:
        genome = prod.cast[c['id']]
        assert genome.palette.body.upper() in tones                 # skin is a people-preset tone, not green
        assert genome.palette.accent.upper() == c['palette']['accent']   # the palette still dresses them
        look = prod.storybook._look(c['id'])
        assert genome.palette.body.upper() == '#%02X%02X%02X' % SKIN[look['tone']]   # the same skin in both renderers


def test_a_motion_scene_never_balloons_a_picture_or_zooms_into_the_next_scene(tmp_path, monkeypatch):
    """The Q3 update's pickup truck grew to fill the frame between scenes: a full-bleed scene covered the page with
    each library icon. Pictures keep a centred slot, and a zoom-through join dissolves (the camera stays locked)."""
    from kinodraw.engine import hybrid
    prod = produce(tmp_path)
    kinetic = prod.spans[2]
    spec = dict(kinetic.spec, composition='full_bleed', transition_in='zoom_through',
                elements=kinetic.spec['elements'] + [{'kind': 'picture', 'ref': 'fl_pickup_truck'}])
    span = hybrid.Span(kinetic.start, kinetic.end, spec)
    span.join, span.join_length = kinetic.join, kinetic.join_length
    prod._prepare(span, tmp_path)
    assert span.motion.composition == 'center'
    image = prod._frame(span, span.end - .05)
    ink = np.asarray(image.convert('L')) < 200
    rows, cols = np.nonzero(ink)
    assert (cols.max() - cols.min()) < .8 * image.size[0]          # the truck is a picture on the page, not the page
    kinds = []
    real = hybrid.render_transition
    monkeypatch.setattr(hybrid, 'render_transition', lambda *a, **k: kinds.append(k.get('kind')) or real(*a, **k))
    prod.spans[2] = span
    prod.frame(span.join + span.join_length / 2)
    assert kinds and 'zoom_through' not in kinds


def test_a_lesson_insert_shows_the_thing_on_the_set_and_the_off_screen_cook_s_hand_on_it(tmp_path):
    """The pancakes' bowl was a lone icon on blank paper and no hand ever worked it: the insert now looks at the bowl
    standing on the kitchen counter, with the cook's hand (in her skin tone) reaching in to it."""
    bowl = lambda bid: shot(bid, 'insert', ['ava'], props=['fl_spoon'], speaking='off_screen', focus='fl_bowl_with_spoon')
    prod = produce(tmp_path, insert=bowl)
    span = prod.spans[1]
    page = span.story[0]
    piece = next(p for p in page.set if p.doodle == 'fl_bowl_with_spoon')
    assert not getattr(piece, 'lone', False) and any(p.doodle == 'set_counter' for p in page.set)
    assert page.hands and page.hands[0][0] is piece
    tone = prod.storybook._look('ava')['tone']
    assert page.hands[0][1] == tone
    with_hand = np.asarray(prod.storybook.frame(span.story, .5).convert('RGB')).astype(int)
    page.hands = []
    without = np.asarray(prod.storybook.frame(span.story, .5).convert('RGB')).astype(int)
    changed = np.abs(with_hand - without).sum(axis=2) > 30
    assert changed.mean() > .01                                   # a hand you can see, not a speck
    skin = np.array(SKIN[tone])
    assert ((np.abs(with_hand - skin).sum(axis=2) < 30) & changed).mean() > .003   # her skin tone, not a sleeve alone


def test_a_story_insert_is_unchanged(tmp_path):
    bowl = lambda bid: shot(bid, 'insert', ['ava'], props=['fl_spoon'], speaking='off_screen', focus='fl_bowl_with_spoon')
    prod = produce(tmp_path, genre='story', insert=bowl)
    assert not prod.spans[1].story[0].hands



def test_outside_a_story_no_framing_holds_more_than_two_sentences(tmp_path):
    """The pancakes' opening wide held three sentences, and two inserts of one bowl held three more: content QA's
    same_picture. Outside a story the third sentence cuts to a closer or wider framing of the same page; a story's
    pages are unchanged."""
    text = TEXT.replace('Ben heats the pan in the kitchen and smiles at the camera.',
                        'Ben heats the pan in the kitchen. He adds a little oil. He waits one minute. He smiles.')
    prod = produce(tmp_path, text=text)
    pages = prod.spans[0].story
    assert len(pages) >= 2 and pages[0].view != pages[1].view
    assert pages[0].view[2] == 1. and pages[1].view[2] > 1.2      # the wide kitchen, then a medium on Ben
    story = produce(tmp_path / 'story', genre='story', text=text)
    assert len(story.spans[0].story) == 1

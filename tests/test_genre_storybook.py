"""Recipes, lessons, promos and updates with people in them get the storybook's staging (sets for places, people
presets with real skin tones, the plan's shots), not the hybrid's small figures beside stamp-sized icons on blank
paper. Boards, charts, diagrams, kinetic type and scenes whose text is a title, call to action or counter stay motion
scenes, and nothing that belongs to a picture book (its title page, its "The End") reaches them."""
import json
from types import SimpleNamespace

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


def shot(bid, kind, cast, place='kitchen', props=()):
    return {'beat_id': bid, 'starts_at': '', 'shot': kind, 'setting': {'place': place, 'time': 'day', 'set_refs': []},
            'cast': [{'id': c, 'age': 'adult' if c == 'ben' else 'child', 'pose': 'hold', 'speaking': 'no'}
                     for c in cast],
            'lines': [], 'props': [{'ref': p, 'relation': 'none', 'to': '', 'motion': 'none'} for p in props],
            'focus_ref': props[0] if props else '', 'writing': ''}


def produce(tmp_path, genre='lesson'):
    """A plan of this genre: two character scenes with kitchen shots, then a kinetic-type scene and a character
    scene whose text is a call to action."""
    board = script.build(ingest.read(TEXT), story='story')
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
    plan['scenes'][1]['shots'] = [shot(ids[1], 'insert', ['ava'], props=['fl_egg'])]
    plan['scenes'][2].update(treatment='kinetic_type', text={'kind': 'kinetic', 'ref': ids[2]})
    plan['scenes'][3].update(text={'kind': 'cta', 'ref': ids[3]}, shots=[shot(ids[3], 'medium', ['ben'])])
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
    ctx = SimpleNamespace(ep={'story': 'story', 'title': {'en': 'Weekend Pancakes'}}, lang='en',
                          T=lambda value: value['en'], project_dir=tmp_path)
    assert end_heading(ctx) == 'Weekend Pancakes'                  # the Studio's story setting does not make it a story
    config = json.loads((tmp_path / 'project.json').read_text())
    config['plan_v3']['storyboard']['genre'] = 'story'
    (tmp_path / 'project.json').write_text(json.dumps(config))
    assert end_heading(ctx) == 'The End'


def test_a_person_never_takes_the_palette_body_colour_as_skin(tmp_path):
    prod = produce(tmp_path)
    tones = {'#%02X%02X%02X' % rgb for rgb in SKIN.values()}
    for c in COOKS:
        genome = prod.cast[c['id']]
        assert genome.palette.body.upper() in tones                 # skin is a people-preset tone, not green
        assert genome.palette.accent.upper() == c['palette']['accent']   # the palette still dresses them
        look = prod.storybook._look(c['id'])
        assert genome.palette.body.upper() == '#%02X%02X%02X' % SKIN[look['tone']]   # the same skin in both renderers


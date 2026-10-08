"""Story characters act out what the narration says (engine.acting): movement verbs move them, gestures change
their pose, contact verbs end with them touching, each from the word that says so. J 2026-10-08 on the Envelope
render: "99% of everything was just Theo standing there." The camera stays locked and nothing moves while idle."""
import json

import numpy as np
from PIL import Image

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline

LIONS = [{'id': 'kojo', 'name': 'King Kojo', 'kind': 'quadruped', 'species': 'lion', 'age': 'adult', 'sex': 'male',
          'size': 1.4},
         {'id': 'pendo', 'name': 'Pendo', 'kind': 'quadruped', 'species': 'lion', 'age': 'baby', 'sex': 'male',
          'size': .5},
         {'id': 'hyena', 'name': 'Spotted hyenas', 'kind': 'quadruped', 'species': 'spotted hyena', 'age': 'adult',
          'sex': None, 'size': .9}]
WOOD = [{'id': 'pip', 'name': 'Pip', 'kind': 'quadruped', 'species': 'hedgehog', 'age': 'young', 'sex': 'male',
         'size': .5},
        {'id': 'mama', 'name': 'Mama', 'kind': 'quadruped', 'species': 'hedgehog', 'age': 'adult', 'sex': 'female',
         'size': .7},
        {'id': 'flick', 'name': 'Flick', 'kind': 'bird', 'species': 'firefly', 'age': 'adult', 'sex': 'female',
         'size': .3}]
PEOPLE = [{'id': 'jules', 'name': 'Jules', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'female'},
          {'id': 'walt', 'name': 'Walt', 'kind': 'human', 'species': 'human', 'age': 'old', 'sex': 'male'}]


def shot(bid, starts_at, kind, cast, place='forest', props=()):
    """A plan shot; cast entries are (id, age, pose)."""
    return {'beat_id': bid, 'starts_at': starts_at, 'shot': kind,
            'setting': {'place': place, 'time': 'day', 'set_refs': []},
            'cast': [{'id': c, 'age': a, 'pose': p, 'speaking': 'no'} for c, a, p in cast],
            'lines': [], 'props': list(props), 'focus_ref': '', 'writing': ''}


def staged(tmp_path, text, cast, shots=(), actions=()):
    """A story's storybook production with this cast on every scene; scenes with plan shots stage from them, the
    others read their text. ``actions``: the plan's (actor, verb, beat)."""
    board = script.build(ingest.read(text), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['storyboard']['genre'] = 'story'
    plan['cast'] = [dict(c, family=c['species'], size=c.get('size', 1), palette={}, marks=[], temperament='calm')
                    for c in cast]
    for scene in plan['scenes']:
        scene.update(treatment='character', composition='stage', atmosphere={'kind': 'none', 'density': 0},
                     text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]},
                     elements=[{'kind': 'cast', 'ref': c['id']} for c in cast],
                     actions=[{'actor': a, 'verb': v, 'at_beat': b, 'intensity': 2} for a, v, b in actions
                              if b in scene['beat_ids']])
        mine = [s for s in shots if s['beat_id'] in scene['beat_ids']]
        if mine:
            scene['shots'] = mine
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = render.make_production(board, tl, 'en', tmp_path)
    prod.frame(0.)
    return prod


def page(prod, words):
    """(span, shot, span-local seconds the words are spoken) of the page narrating these words."""
    for span in prod.spans:
        for bid in span.spec['beat_ids']:
            spoken = prod.by_id[bid]['spoken']
            if words in spoken:
                timing = prod.tl['beats'][bid]
                at = timing['start'] - span.start + timing['char_times'][spoken.index(words)]
                return span, next(s for s in reversed(span.story) if s.start <= at + 1e-6), at
    raise AssertionError(words)


def fig(shot, key):
    return next(f for f in shot.figures if f.key == key)


def visible(shot, x):
    cx, _, zoom = shot.view
    return cx - .5 / zoom < x < cx + .5 / zoom


# ------------------------------------------------------------------ idle
def test_someone_holding_a_thing_while_standing_does_not_sway(tmp_path):
    """The r01 Envelope's 'idle head tilt': a person holding something swayed ±2 degrees as if walking. Standing
    still, the figure keeps its outline (only the faint breath at its edge)."""
    prod = staged(tmp_path, '# Theo\n\nTheo carried the envelope everywhere.',
                  [{'id': 'theo', 'name': 'Theo', 'kind': 'human', 'species': 'human', 'age': 'young', 'sex': 'male'}])
    book = prod.storybook
    _, p, _ = page(prod, 'carried')
    theo = fig(p, 'theo')
    theo.pose, theo.travel = 'carry', 0.
    book._blinking = lambda f, t: False
    alphas = []
    for t in np.arange(p.start, p.start + 2., .1):
        overlay = Image.new('RGBA', book.size, (0, 0, 0, 0))
        book._figure(overlay, theo, p, t, [.5, .5, 1.])
        alphas.append(np.asarray(overlay.getchannel('A')) > 128)
    assert max((a ^ alphas[0]).mean() for a in alphas) < .003

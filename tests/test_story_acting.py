"""Story characters act out what the narration says (engine.acting): movement verbs move them, gestures change
their pose, contact verbs end with them touching, each from the word that says so. J 2026-10-08 on the Envelope
render: "99% of everything was just Theo standing there." The camera stays locked and nothing moves while idle."""
import json

import numpy as np
from PIL import Image

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import acting, render, timeline
from kinodraw.qa import content

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


def state(prod, shot, f, t):
    return acting.motion(prod.storybook, f, shot, t)


def visible(shot, x):
    cx, _, zoom = shot.view
    return cx - .5 / zoom < x < cx + .5 / zoom


# ------------------------------------------------------------------ locomotion
def test_a_burst_leaps_in_from_off_the_frame_at_its_word_and_a_swipe_sends_its_target_flying(tmp_path):
    """Kojo is a standing sprite no more (r01b critic, lion story): "burst through the fog" brings him in off the
    frame on a leap when the word is spoken, and "With one massive swipe ... he sent the hyena flying" rears him up
    with the paw's arcs while the hyena tumbles off the page as "sent ... flying" is said."""
    text = ('# Night\n\nKing Kojo burst through the fog like a shooting star. With one massive swipe of his heavy '
            'paw, he sent the lead hyena flying into the bushes.')
    beats = script.build(ingest.read(text), story='story')['beats']
    cast = [('kojo', 'adult', 'run'), ('hyena', 'adult', 'stand')]
    prod = staged(tmp_path, text, LIONS[:1] + LIONS[2:], shots=[
        shot(beats[0]['id'], 'King Kojo burst', 'wide', cast), shot(beats[-1]['id'], 'With one massive', 'wide', cast)])
    span, page1, burst = page(prod, 'burst')
    kojo = fig(page1, 'kojo')
    before, after = state(prod, page1, kojo, burst - .2), state(prod, page1, kojo, burst + 1.5)
    assert not visible(page1, before.x) and visible(page1, after.x)
    assert min(state(prod, page1, kojo, burst + i / 10).dy for i in range(10)) < -.05          # in the air
    _, page2, sent = page(prod, 'sent the lead hyena')
    kojo, hyena = fig(page2, 'kojo'), fig(page2, 'hyena')
    swing = [state(prod, page2, kojo, sent + i / 20) for i in range(-20, 20)]
    assert any(m.effects and m.effects[0][0] == 'arcs' for m in swing)
    assert max(abs(m.rotate) for m in swing) > 8                                            # he rears up
    assert state(prod, page2, hyena, sent - .5).x == hyena.x
    assert state(prod, page2, hyena, sent + 1.5).gone                                       # flown off


def test_a_swipe_at_someone_across_the_page_closes_in_before_the_paw_lands(tmp_path):
    """r3 lion story: Kojo swiped the air at .29 while the hyena he "sent flying" stood at .80. The swiper lunges in
    to reach its target by the strike, and stays there."""
    text = ('# Night\n\nKojo stood tall. With one massive swipe of his heavy paw, he sent the lead hyena flying '
            'into the bushes.')
    beats = script.build(ingest.read(text), story='story')['beats']
    cast = [('kojo', 'adult', 'stand'), ('pendo', 'baby', 'stand'), ('hyena', 'adult', 'stand')]
    prod = staged(tmp_path, text, LIONS, shots=[shot(beats[0]['id'], 'Kojo stood', 'wide', cast)])
    _, p, sent = page(prod, 'sent the lead hyena')
    kojo, hyena = fig(p, 'kojo'), fig(p, 'hyena')
    assert abs(kojo.x - hyena.x) > .35
    start, strike, after = (state(prod, p, kojo, sent + d) for d in (-1., 0., 1.5))
    touching = prod.storybook._half(kojo) + prod.storybook._half(hyena)                     # bodies meet
    assert start.x == kojo.x and abs(strike.x - hyena.x) <= touching and after.x == strike.x


def test_tiptoe_out_moves_at_its_word_and_fly_up_shrinks_to_a_speck(tmp_path):
    """Pip "tiptoed out of the burrow" with zero movement and Flick never flew up "until she was just a speck"
    (r01 critic, Pip): on plan shots the tiptoe carries Pip across the page from its word, on careful steps, and the
    firefly rises and shrinks to a speck."""
    text = ('# Pip\n\nSo Pip tiptoed out of the burrow and looked up.\n\n'
            '"I\'ll go see!" said Flick, and she zoomed up, up, up, until she was just a speck.')
    beats = script.build(ingest.read(text), story='story')['beats']
    b1, b2 = beats[0]['id'], beats[-1]['id']
    prod = staged(tmp_path, text, WOOD, shots=[shot(b1, 'So Pip tiptoed', 'wide', [('pip', 'young', 'stand')]),
                                               shot(b2, '"I\'ll go see!"', 'wide', [('flick', 'adult', 'stand')])])
    _, p1, word = page(prod, 'tiptoed')
    pip = fig(p1, 'pip')
    start, mid, end = (state(prod, p1, pip, word + d) for d in (-.1, 1., 3.))
    assert abs(end.x - start.x) > .1
    assert mid.moving == 'tiptoe' and mid.pose == 'walk' and start.moving is None
    _, p2, zoom = page(prod, 'zoomed')
    flick = fig(p2, 'flick')
    up = state(prod, p2, flick, zoom + 2.5)
    assert up.scale < .2 and up.dy < -.4 and state(prod, p2, flick, zoom - .1).scale == 1.


def test_out_of_somewhere_off_the_page_comes_onto_it_and_a_later_noun_is_not_its_goal(tmp_path):
    """r3 Pip: "tiptoed out of the burrow in his leaf-print pajamas" with a fallen leaf on the page read as going to
    the leaf, a .07 shuffle. Out of a place the page does not draw is coming onto the page, from off the frame."""
    text = '# Pip\n\nSo Pip tiptoed out of the burrow in his leaf-print pajamas and looked up.'
    beats = script.build(ingest.read(text), story='story')['beats']
    leaf = {'ref': 'fl_fallen_leaf', 'relation': 'on', 'to': 'fl_wood', 'motion': 'none'}
    prod = staged(tmp_path, text, WOOD, shots=[shot(beats[0]['id'], 'So Pip tiptoed', 'wide', [('pip', 'young', 'walk')],
                                                    props=[leaf])])
    _, p, word = page(prod, 'tiptoed')
    pip = fig(p, 'pip')
    start, end = state(prod, p, pip, word + .05), state(prod, p, pip, word + 3.5)
    assert not visible(p, start.x) and visible(p, end.x) and abs(end.x - start.x) > .2


def test_walk_home_and_curl_up_next_to_someone_ends_touching_them(tmp_path):
    """"Pip walked home in the moonlight, curled up next to Mama" showed the two standing apart (r01 critic): he
    walks, then lies against her, their bodies touching."""
    text = '# Home\n\nPip walked home in the moonlight, curled up next to Mama, and tucked his nose under his paws.'
    prod = staged(tmp_path, text, WOOD[:2])
    book = prod.storybook
    _, p, word = page(prod, 'walked')
    pip, mama = fig(p, 'pip'), fig(p, 'mama')
    assert state(prod, p, pip, word + .5).moving == 'walk'
    end = state(prod, p, pip, p.end - .01)
    assert end.pose in ('lie', 'sleep')
    gap = abs(end.x - mama.x) - book._half_width(mama)
    assert gap < acting._half_in(book, pip, end.pose)                                       # touching


def test_found_curled_up_against_someone_is_already_so_when_the_page_opens(tmp_path):
    """"She found Pendo curled up tightly against his father's belly, fast asleep": the cub sleeps against Kojo
    from the first frame; finding him is not watching him walk over."""
    text = ("# Stars\n\nWhen the sun set, the king lay down to rest. She found Pendo curled up tightly against "
            "Kojo's massive belly, fast asleep under the stars.")
    prod = staged(tmp_path, text, LIONS[:2])
    _, p, _ = page(prod, 'curled')
    pendo, kojo = fig(p, 'pendo'), fig(p, 'kojo')
    first = state(prod, p, pendo, p.start)
    assert first.pose == 'sleep' and first.moving is None
    assert abs(first.x - kojo.x) < prod.storybook._half_width(kojo) + prod.storybook._half_width(pendo)


# ------------------------------------------------------------------ animals and gestures
def test_heavy_breathing_heaves_the_flank_and_puffs(tmp_path):
    """"Kojo stood breathing heavily": his body heaves (a squash that rises and falls) with breath puffs."""
    prod = staged(tmp_path, '# Guard\n\nKojo stood breathing heavily, guarding the cubs.', LIONS[:1])
    _, p, word = page(prod, 'breathing')
    kojo = fig(p, 'kojo')
    heave = [state(prod, p, kojo, word + .5 + i / 10) for i in range(20)]
    assert max(m.squash for m in heave) - min(m.squash for m in heave) > .08
    assert any(m.effects for m in heave)
    assert state(prod, p, kojo, word - .2).squash == 0


def test_turned_around_ends_facing_the_one_behind_and_lowered_head_stays_down_through_the_nudge(tmp_path):
    """"The giant king turned around. Kojo lowered his massive head ... He gently nudged Pendo": he turns to face
    the cub, his head goes down to the ground about his back feet, and it stays down while he nudges him."""
    text = ('# Then\n\nThen, the giant king turned around. Instead, Kojo lowered his massive head all the way to '
            'the dirt. He gently nudged Pendo with his giant, scarred nose.')
    beats = script.build(ingest.read(text), story='story')['beats']
    cast = [('kojo', 'adult', 'stand'), ('pendo', 'baby', 'stand')]
    prod = staged(tmp_path, text, LIONS[:2], shots=[shot(beats[0]['id'], 'Then, the giant', 'two_shot', cast),
                                                    shot(beats[0]['id'], 'Instead, Kojo', 'two_shot', cast)])
    _, p, turn = page(prod, 'turned')
    kojo, pendo = fig(p, 'kojo'), fig(p, 'pendo')
    toward = 'r' if pendo.x > kojo.x else 'l'
    assert kojo.facing != toward and state(prod, p, kojo, turn + .5).facing == toward
    _, p2, low = page(prod, 'lowered')
    kojo2 = fig(p2, 'kojo')
    down = state(prod, p2, kojo2, low + 1.)
    assert down.pivot == 'rear' and abs(down.rotate) > 10
    _, p3, nudge = page(prod, 'nudged')
    assert p3 is p2
    assert all(abs(state(prod, p2, kojo2, nudge + i / 10).rotate) > 10 for i in range(18))


def test_gestures_wave_and_grab_change_the_pose_and_the_thing_stays_in_the_hand(tmp_path):
    """Nobody waved or grabbed the remote (r01 critics, Movie Night and Pancakes): a wave shows the waving picture
    from its word, and "grabbed the remote" puts the remote in her hand from then on."""
    text = '# Movie\n\nWalt waved at the TV. Jules grabbed the remote off the couch.'
    prod = staged(tmp_path, text, PEOPLE)
    _, p, wave = page(prod, 'waved')
    walt = fig(p, 'walt')
    assert state(prod, p, walt, wave - .2).pose is None and state(prod, p, walt, wave + .3).pose == 'wave'
    _, p2, grab = page(prod, 'grabbed')
    remote = next(piece for piece in p2.set if 'remote' in piece.doodle)
    assert acting.held(remote, grab - .2) is None and acting.held(remote, grab + 1.) == ('jules', 1.)
    assert state(prod, p2, fig(p2, 'jules'), grab + 1.).pose == 'carry'


def test_a_verb_whose_doer_is_not_cast_does_not_move_anyone(tmp_path):
    """"He tried to let out a warning roar, but it came out as a tiny squeak": the roar came out, not Pendo."""
    prod = staged(tmp_path, '# Squeak\n\nPendo tried to let out a warning roar, but it came out as a tiny, helpless '
                            'squeak.', LIONS[1:2])
    _, p, _ = page(prod, 'came out')
    assert not getattr(fig(p, 'pendo'), 'acts', None)


def test_the_plan_names_who_moves_when_the_text_does_not(tmp_path):
    """"A tiny green light zipped past his nose. It was Flick the firefly.": the plan's action (flick runs) says who
    zipped past; a firefly flies by on its wings, across the page."""
    text = '# Light\n\nA tiny green light zipped past his nose. It was Flick the firefly.'
    beats = script.build(ingest.read(text), story='story')['beats']
    prod = staged(tmp_path, text, WOOD[::2], actions=[('flick', 'run', beats[0]['id'])], shots=[
        shot(beats[0]['id'], 'A tiny green', 'wide', [('pip', 'young', 'stand'), ('flick', 'adult', 'stand')])])
    _, p, word = page(prod, 'zipped')
    flick = fig(p, 'flick')
    a, b = state(prod, p, flick, word - .1), state(prod, p, flick, word + 1.5)
    assert abs(b.x - a.x) > .3 and state(prod, p, flick, word + .5).moving == 'fly'


# ------------------------------------------------------------------ QA and idle
def test_a_movement_verb_whose_actor_shows_no_movement_is_a_qa_finding(tmp_path):
    """A movement the page cannot show (its actor is not on it) is a content finding beside qa['content']."""
    text = '# Walk\n\nPip walked home in the moonlight.'
    beats = script.build(ingest.read(text), story='story')['beats']
    prod = staged(tmp_path, text, WOOD[:2], shots=[shot(beats[0]['id'], 'Pip walked', 'wide',
                                                        [('mama', 'adult', 'sleep')])])
    acted = prod.storybook.acted
    assert acted and acted[0]['word'] == 'walked' and acted[0]['actor'] == 'pip' and not acted[0]['shown']
    path = tmp_path / 'acts.json'
    path.write_text(json.dumps(acted))
    found = content.motion(path, prod.tl)
    assert found['stats'] == {'verbs': 1, 'shown': 0} and '"walked": pip does not move' in found['findings'][0]


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

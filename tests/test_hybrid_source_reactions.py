"""Group clause polarity and passive mouth reactions on the real source clock."""
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from kinodraw.engine.creatures import raster, svg
from kinodraw.engine.creatures.actions import action_pose
from test_hybrid_character_motion import Canvas
from test_hybrid_source_interactions import saved_scene


@pytest.mark.parametrize('text', [
    'Not once did the two hyenas laugh at Nia.',
    'Under no circumstances would the two hyenas approach Nia.',
    'The two hyenas laughed no longer.',
    'Never again would the two hyenas laugh.',
    'At no time did the two hyenas approach Nia.',
])
def test_denied_group_clauses_do_not_schedule_actions(tmp_path, text):
    prod, _ = saved_scene(tmp_path, text, [])
    assert not prod.spans[-1].actions


@pytest.mark.parametrize('text', [
    'The two hyenas not only laughed at Nia, but also approached her.',
    'Not only did the two hyenas laugh at Nia, they also danced.',
    'Nia never laughed, but the two hyenas laughed.',
    'The two hyenas laughed, while Nia never laughed.',
    'Nia did not approach them; the two hyenas laughed.',
    'Not once did the two hyenas laugh before, but the two hyenas laughed at Nia.',
])
def test_positive_group_clause_survives_not_only_and_foreign_negation(tmp_path, text):
    prod, _ = saved_scene(tmp_path, text, [])
    assert sum(a.name == 'laugh' for _, a, _ in prod.spans[-1].actions) == 2


@pytest.mark.parametrize('text, verb', [
    ('The two hyenas not only approached Nia, they also laughed.', 'walk'),
    ('The two hyenas not only bared their teeth, they also laughed.', 'bare_teeth'),
    ('The two hyenas not only fled, they also hid.', 'run'),
])
def test_not_only_keeps_each_supported_group_verb_positive(tmp_path, text, verb):
    prod, _ = saved_scene(tmp_path, text, [])
    assert sum(a.name == verb for _, a, _ in prod.spans[-1].actions) == 2


@pytest.mark.parametrize('names', [('Nia', 'Sora', 'Taro'), ('Ayo', 'Luma', 'Beko')])
def test_owned_roar_rattles_only_its_explicit_mouth_recipient(tmp_path, names):
    child, _, father = names
    text = f'{father} unleashed a roar so powerful it rattled {child}\'s teeth.'
    prod, tl = saved_scene(tmp_path, text, [(father.casefold(), 'roar')], names)
    span = prod.spans[-1]
    reaction = next((a for actor, a, _ in span.actions if actor == child.casefold() and a.name == 'teeth_chatter'), None)
    assert reaction is not None
    assert not any(actor == father.casefold() and a.name == 'teeth_chatter' for actor, a, _ in span.actions)
    timing = tl['beats'][span.spec['beat_ids'][0]]
    assert span.start + reaction.start == timing['start'] + timing['char_times'][text.index('rattled')]
    assert any(actor == father.casefold() and a.name == 'roar' for actor, a, _ in span.actions)
    first, second = [action_pose(reaction, reaction.start + reaction.seconds * f) for f in (.25, .32)]
    assert min(first.jaw, second.jaw) > .24 and abs(first.jaw - second.jaw) > .05
    g = prod.cast[child.casefold()]
    docs = [ET.fromstring(svg(g, p, t=1.)) for p in (first, second)]
    assert all(sum(e.attrib.get('data-part') == 'canine' for e in doc.iter()) == 4 for doc in docs)
    hinges = [next(e.attrib['data-angle'] for e in doc.iter() if e.attrib.get('data-part') == 'jaw_hinge') for doc in docs]
    assert hinges[0] != hinges[1]
    assert not np.array_equal(np.asarray(raster(g, first, height=400)), np.asarray(raster(g, second, height=400)))
    canvas = Canvas(prod.size)
    prod._actors(span, reaction.start + reaction.seconds * .32, canvas)
    assert len(canvas.boxes) == 2


@pytest.mark.parametrize('text, actor', [
    ('Taro unleashed a roar that never rattled Nia\'s teeth.', 'taro'),
    ('Taro unleashed a roar that rattled no teeth. Nia watched.', 'taro'),
    ('Sora unleashed a roar that rattled Nia\'s teeth.', 'taro'),
    ('Taro never unleashed a roar that rattled Nia\'s teeth.', 'taro'),
    ('Taro unleashed a roar. Nia\'s teeth chattered later.', 'taro'),
    ('Taro unleashed a roar while Sora rattled Nia\'s teeth.', 'taro'),
])
def test_negated_foreign_or_unlinked_reactions_are_not_invented(tmp_path, text, actor):
    prod, _ = saved_scene(tmp_path, text, [(actor, 'roar')])
    assert not any(a.name == 'teeth_chatter' for _, a, _ in prod.spans[-1].actions)

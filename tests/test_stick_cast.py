"""Library pictures of people become stick figures only when the figure says everything the picture does."""
from __future__ import annotations

import pytest

from kinodraw.engine.stick import cast, compose, paint


@pytest.mark.parametrize('did,what', [
    ('fl_person', 'person'), ('fl_pilot', 'person'), ('fl_crying_face', 'person'), ('family_group', 'group'),
    ('fl_people_hugging', 'group'), ('fl_parachute', 'parachute'),
    ('fl_person_in_manual_wheelchair', None), ('fl_astronaut', None), ('fl_face_with_medical_mask', None),
    ('fl_money_mouth_face', None), ('fl_sleeping_face', None), ('sellers_group', None), ('people_network', None),
    ('fl_person_playing_water_polo', None), ('fl_person_juggling', None),
])
def test_kind(did, what):
    assert cast.kind(did) == what


def test_costume_and_feelings():
    assert cast.figure_for('fl_pilot').hat == 'cap'
    assert cast.figure_for('fl_farmer').hat == 'strawhat'
    assert cast.figure_for('fl_office_worker').hat is None
    assert cast.figure_for('fl_health_worker').hat is None
    assert cast.figure_for('fl_face_with_tears_of_joy').pose == 'cheer'
    assert cast.figure_for('fl_crying_face').pose == 'sad'
    assert cast.figure_for('fl_neutral_face').face == ('open', 'flat', 'flat')
    assert cast.figure_for('fl_person_running_facing_right').facing == 1


@pytest.mark.parametrize('did', ['fl_pilot', 'family_group', 'fl_parachute'])
def test_cast_image_fits_box(did):
    for v in range(3):
        img = cast.image(did, (300, 260), v, seed=3)
        assert img.mode == 'RGBA' and img.getbbox() is not None
        assert img.width <= 300 and img.height <= 260


def test_kept_picture_is_the_library_drawing():
    did = 'fl_face_with_medical_mask'
    assert compose.picture(did, (240, 240), 0, None).size == paint.doodle(did, (240, 240), 0, None).size

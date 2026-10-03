"""Library pictures of people become stick figures only when the figure says everything the picture does."""
from __future__ import annotations

import pytest

from kinodraw.engine.stick import cast, compose, paint
from kinodraw.library import catalog


@pytest.mark.parametrize('did,what', [
    ('fl_person', 'person'), ('fl_pilot', 'person'), ('fl_crying_face', 'person'), ('family_group', 'group'),
    ('crowd', 'group'), ('team_huddle', 'group'), ('fl_busts_in_silhouette', 'group'),
    ('fl_people_hugging', 'group'), ('fl_parachute', 'parachute'),
    ('fl_face_with_tears_of_joy', 'person'), ('fl_neutral_face', 'person'), ('fl_expressionless_face', 'person'),
    ('fl_person_in_manual_wheelchair', None), ('fl_astronaut', None), ('fl_face_with_medical_mask', None),
    ('fl_money_mouth_face', None), ('fl_sleeping_face', None), ('sellers_group', None), ('people_network', None),
    ('fl_person_playing_water_polo', None), ('fl_person_juggling', None),
])
def test_kind(did, what):
    assert did in catalog()
    assert cast.kind(did) == what


@pytest.mark.parametrize('did', [
    'fl_person_biking', 'fl_person_mountain_biking', 'fl_person_in_motorized_wheelchair',
    'fl_person_with_white_cane', 'fl_person_in_bed', 'fl_person_taking_bath', 'fl_person_surfing',
    'fl_person_swimming', 'fl_person_rowing_boat', 'fl_person_golfing', 'fl_skier', 'fl_snowboarder',
    'fl_person_climbing', 'fl_person_bouncing_ball', 'fl_person_playing_handball', 'fl_person_fencing',
    'fl_person_getting_haircut', 'fl_person_getting_massage', 'fl_person_feeding_baby', 'fl_person_in_lotus_position',
    'fl_person_in_steamy_room', 'fl_person_in_suit_levitating', 'fl_person_bowing', 'fl_person_kneeling',
    'fl_person_tipping_hand', 'fl_person_gesturing_ok', 'fl_person_lifting_weights',
    'fl_person_cartwheeling', 'fl_man_cartwheeling', 'fl_woman_cartwheeling',
    'fl_firefighter', 'fl_cook', 'fl_judge', 'fl_santa_claus', 'fl_mrs_claus', 'fl_mx_claus',
    'fl_person_elf', 'fl_person_fairy', 'fl_person_genie', 'fl_person_mage', 'fl_person_vampire',
    'fl_person_zombie', 'fl_troll', 'fl_ninja', 'fl_man_merpeople', 'fl_woman_merpeople', 'fl_person_merpeople',
    'fl_person_superhero', 'fl_person_supervillain', 'fl_pregnant_person', 'fl_person_wearing_turban',
    'fl_person_with_veil', 'fl_woman_with_headscarf', 'fl_person_with_skullcap', 'fl_person_in_tuxedo',
    'fl_baby_angel', 'fl_person_with_bunny_ears', 'fl_person_wrestling',
    'fl_face_with_thermometer', 'fl_face_with_head_bandage', 'fl_face_vomiting', 'fl_nauseated_face',
    'fl_sneezing_face', 'fl_clown_face', 'fl_cowboy_hat_face', 'fl_nerd_face', 'fl_disguised_face',
    'fl_lying_face', 'fl_melting_face', 'fl_zipper_mouth_face', 'fl_shushing_face', 'fl_saluting_face',
    'fl_upside_down_face', 'fl_dotted_line_face', 'fl_face_in_clouds', 'fl_hot_face', 'fl_cold_face',
    'fl_woozy_face', 'fl_drooling_face', 'fl_face_with_rolling_eyes', 'fl_face_with_hand_over_mouth',
    'fl_face_with_open_eyes_and_hand_over_mouth', 'fl_face_without_mouth', 'fl_relieved_face',
    'fl_smirking_face', 'fl_knocked_out_face', 'fl_face_with_spiral_eyes', 'fl_sleepy_face', 'fl_yawning_face',
])
def test_specific_meaning_keeps_library_picture(did):
    assert did in catalog()
    assert cast.kind(did) is None


@pytest.mark.parametrize('did,hat', [
    ('fl_pilot', 'cap'), ('fl_police_officer', 'cap'), ('fl_guard', 'cap'), ('fl_detective', 'cap'),
    ('fl_mechanic', 'cap'), ('fl_prince', 'crown'), ('fl_princess', 'crown'), ('fl_person_with_crown', 'crown'),
    ('fl_farmer', 'strawhat'), ('fl_construction_worker', 'strawhat'), ('fl_factory_worker', 'strawhat'),
    ('fl_office_worker', None), ('fl_health_worker', None), ('fl_man_office_worker', None),
    ('fl_woman_health_worker', None),
])
def test_costume(did, hat):
    assert did in catalog()
    assert cast.kind(did) == 'person'
    assert cast.figure_for(did).hat == hat


@pytest.mark.parametrize('did,pose', [
    ('fl_face_with_tears_of_joy', 'cheer'), ('fl_crying_face', 'sad'),
    ('fl_man_dancing', 'cheer'), ('fl_woman_dancing', 'cheer'),
])
def test_feelings(did, pose):
    assert did in catalog()
    assert cast.kind(did) == 'person'
    assert cast.figure_for(did).pose == pose


@pytest.mark.parametrize('did', ['fl_neutral_face', 'fl_expressionless_face'])
def test_straight_face(did):
    assert cast.figure_for(did, face=compose.SHOCKED).face == ('open', 'flat', 'flat')


def test_facing_right():
    assert cast.figure_for('fl_person_running_facing_right').facing == 1


@pytest.mark.parametrize('did', ['fl_person', 'family_group', 'fl_parachute'])
def test_cast_image_fits_box(did):
    for v in range(3):
        img = cast.image(did, (300, 260), v, seed=3)
        assert img.mode == 'RGBA' and img.getbbox() is not None
        assert img.width <= 300 and img.height <= 260


def test_kept_picture_is_the_library_drawing():
    did = 'fl_face_with_medical_mask'
    picture = compose.picture(did, (240, 240), 0, None)
    doodle = paint.doodle(did, (240, 240), 0, None)
    assert picture.size == doodle.size
    assert picture.mode == doodle.mode and picture.tobytes() == doodle.tobytes()

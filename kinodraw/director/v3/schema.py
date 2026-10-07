"""Contract v3. Shape and enums are strict; numeric and semantic limits live in validate.py."""
from __future__ import annotations

import json

from ... import styles

S = {'type': 'string'}
N = {'type': 'number'}
I = {'type': 'integer'}


def _obj(**props):
    return {'type': 'object', 'additionalProperties': False, 'required': list(props), 'properties': props}


def _arr(item):
    return {'type': 'array', 'items': item}


def _enum(*values):
    return {'type': 'string', 'enum': list(values)}


GENRES = ('story', 'explainer', 'launch/promo', 'lesson', 'news/data', 'poem', 'other')
TRANSITIONS = ('cut', 'wipe', 'iris', 'match', 'zoom_through', 'page', 'morph')
SKINS = tuple(e['id'] for e in styles.looks() if e['renderer'] == 'whiteboard')
VERBS = ('idle', 'walk', 'run', 'roar', 'whimper', 'tremble', 'nudge', 'laugh', 'swipe', 'look', 'sit',
         'sleep', 'breathe_heavy', 'hide', 'pounce', 'hug', 'point', 'talk')
ATMOSPHERES = ('none', 'fog', 'night_stars', 'shooting_star', 'fog_with_shooting_star', 'rain', 'dust',
               'embers', 'rays', 'snow', 'underwater', 'dawn')
CAST = _obj(
    id=S, name=S,
    kind=_enum('human', 'quadruped', 'bird', 'fish', 'blob', 'object'), species=S,
    family=_enum('feline', 'canine', 'ursine', 'equine', 'bovine', 'rodent', 'bird', 'reptile', 'primate',
                 'human', 'other'),
    age=_enum('baby', 'young', 'adult', 'old'), sex=_enum('female', 'male', 'unknown'), size=N,
    palette=_obj(body=S, accent=S, eye=S),
    marks=_arr(_enum('mane_black', 'mane_gold', 'mane_none', 'stripes', 'spots', 'scar_nose', 'scar_eye',
                     'crown', 'glasses', 'freckles', 'fluffy', 'none')),
    temperament=_enum('gentle', 'fierce', 'playful', 'timid', 'wise', 'sly'),
)
SCENE = _obj(
    beat_ids=_arr(S),
    treatment=_enum('whiteboard', 'motion', 'kinetic_type', 'atmosphere', 'chart', 'character'),
    composition=_enum('center', 'left_third', 'right_third', 'split', 'grid', 'full_bleed', 'stage'),
    elements=_arr(_obj(kind=_enum('picture', 'cast', 'atmosphere', 'text', 'diagram'), ref=S)),
    actions=_arr(_obj(actor=S, verb=_enum(*VERBS), at_beat=S, intensity=I)),
    atmosphere=_obj(kind=_enum(*ATMOSPHERES), density=N),
    camera=_enum('static', 'slow_push', 'pull_back', 'pan_left', 'pan_right', 'shake', 'follow'),
    transition_in=_enum(*TRANSITIONS), hold_s=N,
    text=_obj(kind=_enum('none', 'caption_only', 'quote', 'title', 'counter', 'kinetic', 'cta'), ref=S),
)
PLAN_SCHEMA = _obj(
    storyboard=_obj(
        genre=_enum(*GENRES), audience=S,
        arc=_obj(beginning=S, turn=S, end=S), recurring_motif=S,
        sections=_arr(_obj(section_id=S, intent=S)),
    ),
    style=_obj(
        mode=_enum('whiteboard', 'motion', 'hybrid'), whiteboard_skin=_enum(*SKINS),
        palette=_obj(background=S, ink=S, accent=S, accent2=S),
        type=_enum('hand', 'rounded', 'serif', 'mono', 'display'), energy=I,
        motion_floor=_enum('still', 'breathing', 'drifting', 'lively'),
        transition_family=_enum(*TRANSITIONS),
        music_mood=_enum('none', 'calm', 'warm', 'playful', 'tense', 'uplifting', 'dramatic', 'curious'),
        tempo_bpm=I, pacing=_enum('calm', 'steady', 'brisk'), reason=S,
    ),
    cast=_arr(CAST), scenes=_arr(SCENE),
)


def schema_json() -> str:
    return json.dumps(PLAN_SCHEMA, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    print(schema_json())

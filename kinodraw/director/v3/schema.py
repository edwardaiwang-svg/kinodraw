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
# Per-shot staging (2026-10-08). A scene's optional ``shots`` list says, beat by beat, what the frame shows.
# Plans made before it (and Cloud deployments without it) simply have no ``shots``: OPTIONAL fields may be
# absent, and absent means "no staging given" (renderers fall back to reading the text).
#   shot.beat_id     the scene beat this shot belongs to (shots follow beat order; a beat may have several)
#   shot.starts_at   verbatim opening words of the sentence where the shot starts ("" = the beat's start)
#   shot.shot        framing: wide (whole place and everyone in it), medium (people from the knees up),
#                    close (one face), two_shot (two people facing each other), insert (close-up of an object
#                    or arrangement, e.g. a letter propped against a lamp), first_person (what a character
#                    sees: a page, list, letter or phone screen they read or hold, filling the frame)
#   shot.setting     place: a PLACES kind ("none" when the text gives no place); time: day/night/dawn/dusk or
#                    unknown; set_refs: offered picture ids that build the fixed background (house, couch, TV,
#                    desk), back to front
#   shot.cast[]      who is in frame: id (a cast id), age (AGES band at this moment of the story, which may
#                    differ from the cast bible: baby infant, child ~2-12, teen 13-19, adult, old), pose
#                    (POSES), speaking (yes = says a line in this shot, off_screen = heard but not seen, no)
#                    Everyone on screen in a shot is also a cast element of its scene (validate adds them).
#   shot.lines[]     each quoted line in this shot: quote = its opening words verbatim, speaker = a cast id
#   shot.props[]     movable things: ref (an offered picture id), relation (RELATIONS) to `to` (a picture id
#                    in this shot or a cast id; "" for none), motion (MOTIONS; how the prop moves in the shot)
#                    Every set/prop/focus picture is also a picture element of its scene (validate adds them).
#   shot.focus_ref   insert/first_person: the picture id the camera looks at ("" otherwise)
#   shot.writing     first_person: the words on the page or screen, verbatim from the beat ("" otherwise)
SHOT_TYPES = ('wide', 'medium', 'close', 'two_shot', 'insert', 'first_person')
AGES = ('baby', 'child', 'teen', 'adult', 'old')
POSES = ('stand', 'walk', 'run', 'sit', 'lie', 'sleep', 'look', 'look_up', 'read', 'write', 'hold', 'carry',
         'talk', 'shout', 'wave', 'point', 'reach', 'hug', 'laugh', 'cry', 'scared', 'kneel', 'eat', 'drink')
PLACES = ('none', 'home_exterior', 'living_room', 'bedroom', 'kitchen', 'dining_room', 'bathroom', 'hallway',
          'office', 'classroom', 'shop', 'cafe', 'street', 'town', 'city', 'village', 'park', 'garden',
          'playground', 'bus', 'car', 'train', 'station', 'airport', 'hospital', 'library', 'stage', 'farm',
          'field', 'forest', 'jungle', 'mountain', 'river', 'lake', 'beach', 'sea', 'underwater', 'desert', 'snow',
          'cave', 'castle', 'night_sky', 'space', 'other')
TIMES = ('unknown', 'day', 'night', 'dawn', 'dusk')
RELATIONS = ('none', 'on', 'against', 'in', 'under', 'beside', 'behind', 'held_by')
MOTIONS = ('none', 'roll', 'fall', 'fly', 'slide', 'bounce', 'open', 'glow')
SHOT = _obj(
    beat_id=S, starts_at=S, shot=_enum(*SHOT_TYPES),
    setting=_obj(place=_enum(*PLACES), time=_enum(*TIMES), set_refs=_arr(S)),
    cast=_arr(_obj(id=S, age=_enum(*AGES), pose=_enum(*POSES), speaking=_enum('no', 'yes', 'off_screen'))),
    lines=_arr(_obj(quote=S, speaker=S)),
    props=_arr(_obj(ref=S, relation=_enum(*RELATIONS), to=S, motion=_enum(*MOTIONS))),
    focus_ref=S, writing=S,
)
# Process boards (2026-10-08). A scene's optional ``boards`` draw a labelled diagram that builds up across its beats,
# the way a teacher draws on a whiteboard (engine/process_diagrams.py). The planner chooses structure only: which
# layout, which offered pictures, how parts connect and on which words each item appears. Every word on a board is
# copied from its beat (KinoDraw typesets spoken math: "A plus B equals B plus A" -> "a + b = b + a"), and all
# geometry comes from KinoDraw's layout grammar, never from the model.
#   board.layout   parts (a central picture with labelled callouts, +/- charges and a ground line),
#                  flow (steps left to right joined by arrows), compare (two things side by side, a ratio between)
#   item.id        short handle other items point at ("cloud", "leader")
#   item.beat_id   the scene beat the item appears in; item.cue = verbatim words of that beat it appears on
#   item.kind      picture (ref = offered picture id), label (text = words from the beat; to = the item it names),
#                  equation (text = spoken math from the beat, fragments joined by " ... "), charges (+/- badges on
#                  item `to` at region `at`; style plus|minus), link (from item `ref` to item `to`; style straight|
#                  curved|dashed|zigzag; text = optional label), rings (expanding rings around `to`), highlight
#                  (`to` lights up), number_line (text = e.g. "Start at 0"), hop (text = e.g. "jump 3" on number
#                  line `to`; style restart = start again from the line's start), dots (text = "3 rows of 5"),
#                  rotate (quarter turn of dots `to`)
#   item.at        where it goes (auto lets KinoDraw choose); item.style per kind above, box = a label in a rule box
BOARD_LAYOUTS = ('parts', 'flow', 'compare')
BOARD_KINDS = ('picture', 'label', 'equation', 'charges', 'link', 'rings', 'highlight', 'number_line', 'hop', 'dots',
               'rotate')
BOARD_SLOTS = ('auto', 'center', 'top', 'bottom', 'left', 'right', 'top_left', 'top_right', 'bottom_left',
               'bottom_right', 'ground')
BOARD_STYLES = ('none', 'straight', 'curved', 'dashed', 'zigzag', 'plus', 'minus', 'restart', 'box')
BOARD_ITEM = _obj(id=S, beat_id=S, cue=S, kind=_enum(*BOARD_KINDS), ref=S, to=S, at=_enum(*BOARD_SLOTS), text=S,
                  style=_enum(*BOARD_STYLES))
BOARD = _obj(layout=_enum(*BOARD_LAYOUTS), items=_arr(BOARD_ITEM))
OPTIONAL = frozenset({'shots', 'boards'})      # property names that older plans may lack; absent = empty
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
    shots=_arr(SHOT), boards=_arr(BOARD),
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

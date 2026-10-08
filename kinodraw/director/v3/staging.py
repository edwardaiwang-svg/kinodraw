"""What each sentence shows: its place, its people and its objects, as library pictures.

The offline v3 director stages its plan from these readings, the storybook ties each plan picture to the sentence
that names it, and content QA checks a plan against them. Everything is table-driven English: a row is a broad
list of words, the library pictures that can show them (first existing id wins) and, for objects, the place they
imply. A new library picture plugs in by adding its id to a row; a new kind of thing by adding a row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

# Places: (words, pictures in order of preference). The first place a sentence names becomes the shot's set and
# stays until another place is named.
PLACES = (
    (r'towns?|villages?|hometowns?|neighbou?rhoods?|suburbs?', ('fl_houses', 'house', 'city_block')),
    (r'streets?|roads?|sidewalks?|pavements?|kerbs?|curbs?|crosswalks?|street\s+corners?|main\s+street',
     ('city_block', 'fl_cityscape')),
    (r'city|cities|downtown', ('fl_cityscape', 'city_block', 'nyc_skyline')),
    (r'houses?|homes?(?!\s+(?:videos?|movies?|pages?|work|made|run))|cottages?|apartments?', ('house', 'fl_house', 'fl_house_with_garden')),
    (r'living\s+rooms?|lounges?', ('fl_couch_and_lamp', 'fl_television')),
    (r'bedrooms?|upstairs', ('fl_bed', 'sleep_bed')),
    (r'downstairs', ('fl_couch_and_lamp', 'stairs_steps')),
    (r'kitchens?', ('tb_fridge', 'fl_cooking', 'tb_microwave')),
    (r'bathrooms?', ('fl_bathtub', 'fl_shower')),
    (r'classrooms?|schools?|lecture\s+halls?|college|university|campus', ('school_building', 'fl_school')),
    (r'offices?|workplaces?', ('office_desk', 'fl_office_building')),
    (r'hospitals?|clinics?', ('hospital', 'fl_hospital')),
    (r'parks?|playgrounds?', ('fl_national_park', 'fl_playground_slide', 'fl_deciduous_tree')),
    (r'gardens?|yards?|backyards?|lawns?', ('fl_house_with_garden', 'fl_deciduous_tree')),
    (r'farms?|barns?|fields?|meadows?', ('farm_barn', 'fl_sheaf_of_rice')),
    (r'forests?|woods?|woodlands?|jungles?', ('forest', 'fl_evergreen_tree', 'fl_deciduous_tree')),
    (r'beach(?:es)?|shores?|coasts?', ('fl_beach_with_umbrella', 'ocean')),
    (r'seas?|oceans?|waves', ('ocean',)),
    (r'ponds?|lakes?', ('lake',)),
    (r'rivers?|streams?|creeks?', ('river',)),
    (r'mountains?|hills?|valleys?|ridges?|cliffs?', ('fl_mountain', 'fl_snow_capped_mountain')),
    (r'deserts?|dunes?', ('fl_desert',)),
    (r'islands?', ('fl_desert_island',)),
    (r'caves?|burrows?|dens?', ('fl_rock', 'fl_mountain')),
    (r'castles?|palaces?', ('castle', 'fl_castle')),
    (r'bridges?', ('fl_bridge_at_night', 'tb_building_bridge')),
    (r'shops?|stores?|bakery|bakeries|cafes?|caf[ée]s?|restaurants?|diners?|supermarkets?|grocery\s+stores?',
     ('store_front', 'fl_convenience_store', 'fl_department_store')),
    (r'markets?|bazaars?', ('market_stall', 'store_front')),
    (r'stations?|platforms?|bus\s+stops?', ('fl_station', 'fl_bus_stop')),
    (r'airports?', ('fl_airplane', 'tb_building_airport')),
    (r'stadiums?|arenas?|race\s*tracks?|tracks?', ('fl_stadium', 'tb_building_stadium')),
    (r'cinemas?|movie\s+theat(?:er|re)s?|theat(?:er|re)s?', ('fl_cinema',)),
    (r'outer\s+space|orbit|planets?', ('rocket', 'fl_rocket', 'fl_ringed_planet')),
)
# Objects: (words, pictures in order of preference, implied place words or None). Words are matched whole,
# singular or plural; an implied place sets the scene when the sentence names no place itself.
OBJECTS = (
    (r'envelopes?|letters?|mail', ('fl_envelope', 'email_envelope'), None),
    (r'sheets?\s+of\s+paper|papers?|pages?|lists?|notes?', ('fl_page_facing_up', 'fl_page_with_curl', 'fl_scroll'), None),
    (r'notebooks?|diar(?:y|ies)|journals?', ('fl_notebook', 'fl_notebook_with_decorative_cover'), None),
    (r'books?', ('fl_closed_book', 'book_stack', 'fl_books'), None),
    (r'newspapers?', ('newspaper', 'fl_newspaper'), None),
    (r'pens?|pencils?|ink', ('fl_pencil', 'pencil', 'fl_pen'), None),
    (r'desks?', ('office_desk', 'tb_desk'), 'bedroom'),
    (r'lamps?', ('fl_diya_lamp', 'tb_lamp'), 'bedroom'),
    (r'beds?|pillows?|blankets?', ('fl_bed', 'sleep_bed'), 'bedroom'),
    (r'drawers?|dressers?|cupboards?|wardrobes?', ('fl_card_file_box', 'tb_box'), 'bedroom'),
    (r'couch(?:es)?|sofas?', ('fl_couch_and_lamp', 'tb_sofa'), 'living room'),
    (r'armchairs?|chairs?|benches?|seats?', ('fl_chair', 'tb_armchair', 'fl_seat'), None),
    (r'tables?|counters?', ('tb_picnic_table', 'office_desk'), None),
    (r'tvs?|televisions?|screens?|tv\s+sets?', ('fl_television', 'tb_device_tv'), 'living room'),
    (r'remotes?|remote\s+controls?', ('tb_remote_control', 'tb_device_remote'), 'living room'),
    (r'phones?|cell\s*phones?|smartphones?|mobiles?|buttons?|texts?|messages?|voice\s+messages?', ('fl_mobile_phone', 'smartphone', 'hi_phone'), None),
    (r'computers?|laptops?', ('fl_laptop', 'laptop', 'fl_desktop_computer'), None),
    (r'radios?', ('fl_radio',), None),
    (r'cameras?|camcorders?', ('fl_camera', 'camera'), None),
    (r'clocks?|alarms?', ('fl_alarm_clock', 'alarm_clock'), None),
    (r'watch(?:es)?', ('fl_watch',), None),
    (r'doors?|doorways?', ('fl_door', 'closed_door'), None),
    (r'windows?', ('fl_window',), None),
    (r'stairs|staircases?|steps', ('stairs_steps', 'tb_stairs'), None),
    (r'keys?', ('fl_old_key', 'fl_key'), None),
    (r'knife|knives', ('fl_kitchen_knife', 'fl_fork_and_knife'), None),
    (r'bags?|grocer(?:y|ies)|shopping', ('fl_shopping_bags', 'tb_paper_bag', 'fl_handbag'), None),
    (r'backpacks?|schoolbags?', ('fl_backpack', 'backpack'), None),
    (r'boxes|box|parcels?|packages?', ('fl_package', 'tb_box'), None),
    (r'gifts?|presents?', ('fl_wrapped_gift',), None),
    (r'cups?|mugs?', ('coffee_cup', 'fl_hot_beverage', 'tb_mug'), None),
    (r'bowls?', ('fl_bowl_with_spoon', 'fl_steaming_bowl'), None),
    (r'plates?|dinners?|meals?', ('fl_fork_and_knife_with_plate',), None),
    (r'bottles?', ('fl_baby_bottle', 'tb_bottle'), None),
    (r'candles?', ('fl_candle',), None),
    (r'umbrellas?', ('fl_umbrella', 'fl_closed_umbrella'), None),
    (r'hats?|caps?|headbands?', ('fl_top_hat', 'fl_womans_hat'), None),
    (r'shoes?|boots?|sneakers?', ('fl_running_shoe', 'fl_mans_shoe', 'fl_hiking_boot'), None),
    (r'coats?|jackets?|raincoats?|pockets?|sweaters?', ('fl_coat', 'tb_jacket'), None),
    (r'glasses|spectacles', ('fl_glasses',), None),
    (r'balls?', ('fl_soccer_ball', 'fl_basketball'), None),
    (r'toys?|teddy(?:\s+bear)?', ('fl_teddy_bear', 'tb_horse_toy'), None),
    (r'guitars?', ('fl_guitar',), None),
    (r'pianos?', ('fl_musical_keyboard', 'tb_piano'), None),
    (r'whistl\w*|songs?|music|singing|sang', ('fl_musical_notes', 'fl_musical_note'), None),
    (r'flags?', ('fl_triangular_flag', 'tb_flag'), None),
    (r'trophy|trophies|prizes?|medals?', ('fl_trophy', 'trophy', 'medal'), None),
    (r'money|cash|coins?|dollars?|\$\d+(?:\.\d+)?|price', ('money_bag', 'cash_stack', 'fl_coin'), None),
    (r'tickets?', ('fl_ticket', 'fl_admission_tickets'), None),
    (r'maps?', ('fl_world_map', 'treasure_map'), None),
    (r'photos?|photographs?|pictures?', ('fl_framed_picture', 'fl_camera'), None),
    (r'tests?|exams?|homework|grades?', ('fl_memo', 'fl_page_facing_up'), None),
    (r'cars?|taxis?', ('fl_automobile', 'fl_taxi', 'electric_car'), None),
    (r'bus(?:es)?|shuttles?', ('fl_bus', 'fl_oncoming_bus'), None),
    (r'trains?|subways?', ('fl_train', 'steam_train'), None),
    (r'bikes?|bicycles?', ('fl_bicycle',), None),
    (r'boats?|ships?', ('fl_sailboat', 'fl_ship', 'sailing_ship'), None),
    (r'planes?|airplanes?|aircraft', ('fl_airplane',), None),
    (r'rockets?|spacecraft|spaceships?|shuttles?', ('fl_rocket', 'rocket'), None),
    (r'batons?|sticks?', ('fl_wood', 'fl_baguette_bread'), None),
    (r'oranges?|tangerines?', ('fl_tangerine',), None),
    (r'apples?', ('fl_red_apple', 'apple_red'), None),
    (r'bananas?', ('fl_banana',), None),
    (r'fruit|fruits', ('fl_tangerine', 'fl_red_apple'), None),
    (r'bread|rolls?|buns?|loaf|loaves|baguettes?', ('fl_bread', 'fl_baguette_bread'), None),
    (r'cakes?|cupcakes?|pastr(?:y|ies)', ('fl_shortcake', 'fl_birthday_cake', 'fl_cupcake'), None),
    (r'cookies?|biscuits?', ('fl_cookie',), None),
    (r'pancakes?', ('fl_pancakes',), None),
    (r'eggs?', ('fl_egg',), None),
    (r'milk', ('fl_glass_of_milk',), None),
    (r'coffee|tea', ('coffee_cup', 'fl_hot_beverage'), None),
    (r'popcorn', ('fl_popcorn',), None),
    (r'pizzas?', ('fl_pizza',), None),
    (r'dumplings?', ('fl_dumpling',), None),
    (r'soup|stew', ('fl_steaming_bowl',), None),
    (r'rice', ('fl_cooked_rice',), None),
    (r'food|leftovers?|groceries', ('fl_shopping_bags', 'fl_steaming_bowl'), None),
    (r'ovens?|stoves?|frying\s+pans?|bak(?:e|ed|es|ing)', ('fl_cooking',), 'kitchen'),
    (r'fridges?|refrigerators?|freezers?', ('tb_fridge',), 'kitchen'),
    (r'trees?|oaks?|branch(?:es)?', ('fl_deciduous_tree', 'fl_evergreen_tree'), None),
    (r'flowers?|roses?|plants?', ('fl_tulip', 'fl_sunflower', 'fl_potted_plant'), None),
    (r'leaves|leaf', ('fl_fallen_leaf', 'fl_leaf_fluttering_in_wind'), None),
    (r'rocks?|stones?|pebbles?', ('fl_rock',), None),
    (r'puddles?', ('puddle',), None),
    (r'fires?|flames?|campfires?', ('fl_fire', 'fire_flame'), None),
    (r'light\s*bulbs?', ('fl_light_bulb',), None),
    (r'stars?', ('fl_star', 'fl_glowing_star'), None),
)
# Sky words are drawn by the storybook from the text itself (story.SKY); they count as shown.
SKY_WORDS = r'moon\w*|sun\w*|stars?|night|evening|dawn|sunrise|sunset|morning|afternoon|rain\w*|storm\w*|thunder|' \
            r'lightning|clouds?|snow\w*|sky|skies'
NEGATION = re.compile(r"\b(?:no|not|never|without|nothing|nobody)\b|\b\w+n['’]t\b", re.I)
# "The moon is gone", "the key was missing": the words name a thing that is not there.
GONE = re.compile(r"\s+(?:(?:is|was|were|are|has|had)\s+)?(?:been\s+|already\s+|still\s+)?"
                  r"(?:gone|missing|vanished|disappeared|lost)\b", re.I)


def absent(body: str, start: int, end: int) -> bool:
    """Do the words at body[start:end] name something that is not there ("no moon", "the moon is gone")?"""
    clause = re.split(r'[,;:]|\b(?:but|and|or)\b', body[:start], flags=re.I)[-1]
    return bool(NEGATION.search(clause) or GONE.match(body, end))


@dataclass
class Reading:
    """One sentence: char span in its beat's text, the place it names (or carries), the objects it names."""
    start: int
    end: int
    text: str
    place: str | None = None              # picture id of the shot's set
    named_place: bool = False             # this sentence names the place itself
    objects: list = field(default_factory=list)   # picture ids, in reading order
    words: list = field(default_factory=list)     # the concrete words found (places, objects, sky), lower case
    sky: bool = False


def _compile(rows):
    return [(re.compile(r'(?<![\w$])(?:' + words + r')(?!\w)', re.I), pictures, rest) for words, pictures, *rest in rows]


@lru_cache(maxsize=1)
def _tables():
    return _compile(PLACES), _compile(OBJECTS)


@lru_cache(maxsize=None)
def picture(preferences: tuple) -> str | None:
    """The first preferred picture the library has."""
    from ...library import catalog
    library = catalog()
    return next((p for p in preferences if p in library), None)


def _place_picture(words: str) -> str | None:
    places, _ = _tables()
    return next((picture(pics) for pattern, pics, _ in places if pattern.fullmatch(words) and picture(pics)), None)


def read_text(text: str, place: str | None = None) -> list[Reading]:
    """Sentences of one beat's text, each with its set (named, implied by an object, or carried from before)."""
    from .story import sentences
    places, objects = _tables()
    out = []
    for a, b in sentences(text):
        body = text[a:b]
        r = Reading(a, b, body)
        hits = []
        for pattern, pics, _ in places:
            for m in pattern.finditer(body):
                hits.append((m.start(), m.end(), 'place', picture(pics), m.group().lower(), None))
        for pattern, pics, (implied,) in objects:
            for m in pattern.finditer(body):
                hits.append((m.start(), m.end(), 'object', picture(pics), m.group().lower(), implied))
        # A longer phrase wins over the words inside it ("living room" over "room", "bus stop" over "bus").
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        taken = []
        for start, end, kind, pic, word, implied in hits:
            if any(s < end and start < e for s, e in taken):
                continue
            taken.append((start, end))
            if absent(body, start, end):
                continue          # "No moon anywhere", "not in a drawer", "the moon is gone": nothing to show
            r.words.append(word)
            if pic is None:
                continue
            if kind == 'place':
                if not r.named_place:
                    r.place, r.named_place = pic, True
            elif pic not in r.objects:
                r.objects.append(pic)
                if implied and not r.named_place and r.place is None:
                    r.place = _place_picture(implied)
        r.sky = any(not absent(body, m.start(), m.end())
                    for m in re.finditer(r'\b(?:' + SKY_WORDS + r')\b', body, re.I))
        if r.place is None:
            r.place = place
        place = r.place
        out.append(r)
    return out


def read_beats(script_beats) -> dict:
    """beat id -> [Reading], the set carried from beat to beat until another place is named."""
    out, place = {}, None
    for b in script_beats:
        readings = read_text(b['spoken'], place)
        if readings:
            place = readings[-1].place
        out[b['id']] = readings
    return out


def beat_pictures(readings) -> list[str]:
    """A scene's pictures in order: its first set, then each sentence's objects and any later set."""
    out = []
    for r in readings:
        for p in ([r.place] if r.place else []) + r.objects:
            if p not in out:
                out.append(p)
    return out


@lru_cache(maxsize=4096)
def _keywords(doodle):
    from ...library import catalog
    entry = catalog().get(doodle) or {}
    words = [w.lower() for w in (entry.get('en') or [])[:6] if len(w) > 2]
    places, objects = _tables()
    rows = [pattern for pattern, pics, _ in places + objects if doodle in pics]
    return words, rows, any(doodle in pics for _, pics, _ in places)


def _spans(doodle, text):
    words, rows, _ = _keywords(doodle)
    for p in rows:
        yield from ((m.start(), m.end()) for m in p.finditer(text))
    for w in words:
        yield from ((m.start(), m.end()) for m in re.finditer(r'(?<!\w)' + re.escape(w) + r'(?:s|es)?(?!\w)', text, re.I))


def names(doodle, text) -> bool:
    """Does this sentence name what the picture shows (its table row or one of its library keywords)?"""
    return next(_spans(doodle, text), None) is not None


def shows(doodle, text) -> bool:
    """Does this sentence name the picture as something that is there (not "no moon", "the moon is gone")?"""
    return any(not absent(text, a, b) for a, b in _spans(doodle, text))


def tie(texts, pictures) -> list[list[str]]:
    """Each sentence's share of a scene's pictures. A set shows from the sentence that names it to the end of the
    scene; an object shows on the sentence that names it; a picture no sentence names shows on every sentence
    (a set carried in from an earlier scene, or a planner's choice the words do not spell out); a picture the
    words only name as not there ("the moon is gone") shows on none."""
    first, never = {}, set()
    for p in pictures:
        first[p] = next((i for i, t in enumerate(texts) if shows(p, t)), None)
        if first[p] is None and any(names(p, t) for t in texts):
            never.add(p)          # the words only ever say it is not there
    out = []
    for i, t in enumerate(texts):
        mine = []
        for p in pictures:
            at = first[p]
            place = _keywords(p)[2]
            if p not in never and (at is None or (place and at <= i) or shows(p, t)):
                mine.append(p)
        out.append(mine)
    return out


# ------------------------------------------------------------------ people
# Roles that stand for a person when a story does not name them: (words, cast name, age, sex). Only a singular
# role with a determiner counts ("his mother", "the stranger", "a little girl"); a role right before or after a
# name is that named person ("her daughter Rosie", "his mother, Mara").
ROLES = (
    (r'mother|mom|mum|mama|mommy', 'Mother', 'adult', 'female'),
    (r'father|dad|papa|daddy', 'Father', 'adult', 'male'),
    (r'grandmother|grandma|granny|nana|gran', 'Grandmother', 'old', 'female'),
    (r'grandfather|grandpa|granddad|grandad|gramps', 'Grandfather', 'old', 'male'),
    (r'granddaughter', 'Granddaughter', 'young', 'female'),
    (r'grandson', 'Grandson', 'young', 'male'),
    (r'daughter', 'Daughter', 'young', 'female'),
    (r'son', 'Son', 'young', 'male'),
    (r'sister', 'Sister', 'young', 'female'),
    (r'brother', 'Brother', 'young', 'male'),
    (r'aunt|auntie', 'Aunt', 'adult', 'female'),
    (r'uncle', 'Uncle', 'adult', 'male'),
    (r'wife', 'Wife', 'adult', 'female'),
    (r'husband', 'Husband', 'adult', 'male'),
    (r'baby', 'Baby', 'baby', 'unknown'),
    (r'stranger', 'Stranger', 'adult', 'unknown'),
    (r'neighbou?r', 'Neighbour', 'adult', 'unknown'),
    (r'friend|best\s+friend', 'Friend', 'young', 'unknown'),
    (r'teacher|professor', 'Teacher', 'adult', 'unknown'),
    (r'coach', 'Coach', 'adult', 'unknown'),
    (r'doctor|nurse', 'Doctor', 'adult', 'unknown'),
    (r'boss|manager', 'Boss', 'adult', 'unknown'),
    (r'announcer|host|presenter', 'Announcer', 'adult', 'unknown'),
    (r'driver|pilot|captain', 'Driver', 'adult', 'unknown'),
    (r'baker|chef|cook|waiter|waitress|shopkeeper|cashier|clerk', 'Shopkeeper', 'adult', 'unknown'),
    (r'farmer', 'Farmer', 'adult', 'unknown'),
    (r'police\s+officer|policeman|policewoman|officer', 'Officer', 'adult', 'unknown'),
    (r'old\s+man', 'Old man', 'old', 'male'),
    (r'old\s+woman|old\s+lady', 'Old woman', 'old', 'female'),
    (r'boy', 'Boy', 'young', 'male'),
    (r'girl', 'Girl', 'young', 'female'),
    (r'man|gentleman', 'Man', 'adult', 'male'),
    (r'woman|lady', 'Woman', 'adult', 'female'),
    (r'kid|child|toddler', 'Child', 'young', 'unknown'),
    (r'teenager|teen', 'Teen', 'young', 'unknown'),
    (r'customer|visitor|guest', 'Visitor', 'adult', 'unknown'),
)
GENERIC = {'Old man', 'Old woman', 'Boy', 'Girl', 'Man', 'Woman', 'Child', 'Teen', 'Visitor'}
KIN = {'Mother', 'Father', 'Grandmother', 'Grandfather', 'Granddaughter', 'Grandson', 'Daughter', 'Son', 'Sister',
       'Brother', 'Aunt', 'Uncle', 'Wife', 'Husband', 'Baby'}
DETERMINER = r"(?:the|a|an|his|her|their|my|your|our|its|[A-Z][a-z]+['’]s)\s+(?:(?:little|old|young|kind|tired|elderly|" \
             r"new|own|older|younger|baby|best|big)\s+){0,2}"
# A verb right after a capitalised word makes it someone doing something ("Theo couldn't", "Nana typed").
VERBS = set('''was is had has did does could would will can may might must should read reads said says went goes came
comes saw sees sat sits ran runs got gets kept keeps took takes made makes felt feels held holds rode rides drove drives
showed shows asked asks told tells knew knows thought thinks found finds gave gives left leaves stood stands put puts
let lets began begins fell falls grew grows ate eats lay lies woke wakes wrote writes sang sings threw throws caught
catches bought buys brought brings heard hears lost loses met meets sent sends won wins wore wears whispered whispers
smiled smiles laughed laughs cried cries nodded nods grinned grins leaned leans looked looks walked walks waited waits
lived lives loved loves typed types practiced practised stretched twisted passed passes covers covered squeezes
squeezed clicks clicked takes started starts reached reaches moved moves blinked blinks tiptoed tiptoes
opened opens closed closes turned turns tried tries wanted wants'''.split())
NOT_NAMES = set('''January February March April May June July August September October November December Monday Tuesday
Wednesday Thursday Friday Saturday Sunday Earth Moon God Mr Mrs Ms Dr Okay OK Yes No Oh Hello Hi Hey Wait Please
Thanks Thank Sorry Well Look Every Some None Most Many Both Down Up Inside Outside Around Somewhere Nothing Something
Everyone Someone Nobody Anyone Good Morning Night Grandma Grandpa Mom Dad Mama Papa Nana First Second Third Fourth
Fifth Sixth Seventh Eighth Ninth Tenth Mine Yours Hers His Theirs Ours Whatever Whoever'''.split())
PLACE_WORDS = re.compile(r'\b(?:Street|St|Road|Avenue|Lane|Station|Dome|Wood|Woods|Park|School|Hall|City|Town|Lake|'
                         r'River|Mountain|Island|Bakery|Shop|Store|Cafe|Café|Center|Centre|Company|Co|Inc|Control|'
                         r'House|Hotel|Bridge|Valley|Bay|Beach|Market|Square|Radio|TV)\b')
LOCATION_BEFORE = re.compile(r"\b(?:in|at|of|from|to|near|across|into|toward|towards|on|over|outside|inside|around)"
                             r"\s+(?:the\s+)?(?:[a-z]+\s+)?$", re.I)
NUMBERS = {w: i for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen '
                                      'fourteen fifteen sixteen seventeen eighteen nineteen'.split())}


def _role_name(word):
    return next(((name, age, sex) for pattern, name, age, sex in ROLES if re.fullmatch(pattern, word, re.I)), None)


def _initial(text, at):
    before = text[:at].rstrip(' "“‘[(')
    return not before or before[-1] in '.!?\n:…'


@lru_cache(maxsize=1)
def _vocabulary():
    from ...library import catalog
    from ..match import singular
    return {singular(w.lower()) for e in catalog().values() if e.get('set') != 'creatures'
            for w in (e.get('en') or [])[:6] if ' ' not in w}


def _common(name):
    from ..match import singular
    return ' ' not in name and singular(name.lower()) in _vocabulary()


def _names(text):
    """Proper names of people in a story: capitalised words used as a person (not places, months, ordinary words
    or titles of things), and screenplay speaker labels (``WALT:``). Returns name -> first character offset."""
    from ..match import EN_STOP
    from .semantics import STOP_NAMES
    titles = {'Grandma', 'Grandpa', 'Nana', 'Mama'}
    found, plain = {}, set()
    for m in re.finditer(r'(?m)^\s*\[?([A-Z][A-Z]+(?: [A-Z][A-Z]+)?)\]?\s*:', text):
        found.setdefault(m[1].title(), m.start(1))
    labels = set(found)
    for m in re.finditer(r'\b[A-Z][a-z]+(?:[ -][A-Z][a-z]+)*\b', text):
        words, start = m.group().split(), m.start()
        initial = _initial(text, m.start())
        while words and (words[0] in STOP_NAMES or words[0] in NOT_NAMES - titles):
            start += len(words.pop(0)) + 1
        if not words or any(w in NOT_NAMES - titles or w.lower() in EN_STOP for w in words):
            continue
        name = ' '.join(words)
        # An ordinary word capitalised at the start of a sentence ("Living room", "Families went home").
        if re.search(r'(?<![A-Za-z])' + re.escape(name.lower()) + r'(?![A-Za-z])', text):
            continue
        prefix = text[max(0, start - 40):start]
        if PLACE_WORDS.search(name) or LOCATION_BEFORE.search(prefix) or re.search(r'\bthe\s+$', prefix, re.I):
            continue
        after = re.match(r"\s+([a-z]+(?:n['’]t)?)", text[m.end():])
        verb = bool(after and (after[1] in VERBS or after[1].endswith(('ed', "n't", 'n’t'))))
        if initial and not verb:
            continue
        found.setdefault(name, start)
        if not initial:
            plain.add(name)
    # A word only ever capitalised at a sentence start that the library knows as a thing ("Kids waved",
    # "Light travels") is an ordinary noun; a name is used mid-sentence too, or is no library word.
    found = {n: at for n, at in found.items() if n in plain or n in labels or not _common(n)}
    # "Grandma Moss" also says "Moss" alone sometimes: keep the full name only.
    return {n: at for n, at in found.items() if not any(n != o and re.search(r'\b' + re.escape(n) + r'\b', o)
                                                      for o in found)}


def _sex_after(text, start, others=()):
    """The pronoun that next refers back to someone just named: he/his -> male, she/her -> female. Another name
    before the pronoun leaves it unknown."""
    following = text[start:start + 220]
    hit = re.search(r'\b(he|him|his|she|her|hers)\b', following, re.I)
    if not hit or any(re.search(r'\b' + re.escape(o) + r'\b', following[:hit.start()], re.I) for o in others):
        return 'unknown'
    return 'male' if hit[1].lower() in ('he', 'him', 'his') else 'female'


def _age_near(text, start):
    """An age stated in the sentence that names someone ("at seventeen", "a little girl")."""
    a = max(text.rfind('.', 0, start), text.rfind('\n', 0, start)) + 1
    b = min([k for k in (text.find('.', start), text.find('\n', start)) if k >= 0] or [len(text)])
    window = text[a:b].lower()
    number = re.search(r'\b(?:at|aged?|turned)\s+(\w+)(?:\s+years?\s+old)?\b|\bwas\s+(\w+)\s+years?\s+old\b', window)
    if number:
        word = number[1] or number[2]
        value = NUMBERS.get(word, int(word) if word.isdigit() else None)
        if value is not None:
            return 'young' if value < 20 else 'old' if value >= 60 else 'adult'
    if re.search(r'\b(?:little|kid|child|boy|girl|teen\w*|toddler)\b', window):
        return 'young'
    if re.search(r'\b(?:old\s+(?:man|woman|lady)|very\s+old|elderly)\b', window):
        return 'old'
    return 'adult'


def _dialogue(text):
    """Character ranges of quotations and screenplay lines: words a character says, not narration."""
    spans = [(m.start(), m.end()) for m in re.finditer(r'["“][^"“”]*["”]?', text)]
    spans += [(m.start(), m.end()) for m in re.finditer(r'(?m)^\s*[A-Z][A-Z]+(?: [A-Z][A-Z]+)?\s*:.*$', text)]
    return spans


def _member(name, age, sex, index):
    from .semantics import COLOURS
    species = ({'male': 'boy', 'female': 'girl'} if age in ('young', 'baby') else
               {'male': 'man', 'female': 'woman'}).get(sex, 'human')
    return {'id': re.sub(r'\W+', '_', name.lower()).strip('_') or 'person', 'name': name, 'kind': 'human',
            'species': species, 'family': 'human', 'age': age, 'sex': sex, 'size': .55 if age == 'baby' else 1.0,
            'palette': {'body': COLOURS[index % len(COLOURS)], 'accent': '#F2D4A4', 'eye': '#202020'},
            'marks': ['none'], 'temperament': 'gentle'}


def _addressed(text):
    """Screenplay speakers a later line calls by a role to their face ("JULES: Grandpa, that's a screensaver." said
    right after WALT spoke): label name -> (age, sex) of that role."""
    out, last = {}, None
    for m in re.finditer(r'(?m)^\s*\[?([A-Z][A-Z]+(?: [A-Z][A-Z]+)?)\]?\s*:\s*(?:\[[^\]]*\]\s*)?(?:(\w+)\s*[,!?])?', text):
        who = m[1].title()
        role = _role_name(m[2]) if m[2] else None
        if role and last and last != who and role[1] in ('old', 'adult'):
            out.setdefault(last, (role[1], role[2]))
        last = who
    return out


def people(script_beats, cast) -> list[dict]:
    """The people a story's offline plan stages beside the cast the animal reader found: everyone named, and the
    unnamed roles a human story keeps coming back to ("his mother", "the stranger"). A story with animal characters
    keeps its kin words for its animals (the reader resolves "his mother" to the lioness)."""
    from .semantics import SPECIES_RE, mentions, name_key
    text = '\n'.join(b['spoken'] for b in script_beats)
    taken = {name_key(c['name']) for c in cast}
    animals = any(c['kind'] != 'human' for c in cast)
    extra = []
    found = _names(text)
    addressed = _addressed(text)
    for name, at in found.items():
        if name_key(name) in taken or any(mentions(c['name'], name) for c in cast + extra):
            continue
        tail = text[at + len(name):at + len(name) + 60]
        species = re.match(r'(?:,?\s+(?:the|a|an)\s+(?:\w+\s+){0,2})(' + SPECIES_RE.pattern[3:-3] + r')\b', tail, re.I)
        kin = _role_name(name.split()[0])
        if species or (animals and kin and kin[0] in KIN):
            # "Grandma Moss, the oldest tortoise", "Flick the firefly"; an animal story's "Mama" is the species of
            # the animal named last before her.
            before = [c for c in cast + extra if c['kind'] != 'human' and text.find(c['name']) < at]
            word = species[1].lower() if species else before[-1]['species'] if before else None
            if word is None:
                continue
            word = {'lioness': 'lion', 'tigress': 'tiger'}.get(word, word) if not species else word
            member = _member(name, kin[1] if kin else 'adult', kin[2] if kin else _sex_after(text, at + len(name)),
                             len(cast) + len(extra))
            from .semantics import SPECIES
            kind, family = SPECIES.get(word, ('quadruped', 'other'))
            member.update(species=word, kind=kind, family=family)
            extra.append(member)
            taken.add(name_key(name))
            continue
        if animals:
            continue                  # an animal story's other capitalised words are not people
        role = _role_name(re.sub(r'^.*\b(\w+)\s*$', r'\1', text[max(0, at - 25):at].strip(' ,')) or '')
        sex = role[2] if role and role[2] != 'unknown' else _sex_after(text, at + len(name),
                                                                         [n for n in found if n != name])
        age = role[1] if role else _age_near(text, at)
        if name.split()[0] in ('Grandma', 'Grandpa', 'Nana'):
            age, sex = 'old', 'male' if name.startswith('Grandpa') else 'female'
        age, sex = addressed.get(name, (age, sex))
        extra.append(_member(name, age, sex, len(cast) + len(extra)))
        taken.add(name_key(name))
    if animals:
        return extra
    names = [re.escape(c['name']) for c in cast + extra]
    named = re.compile(r',?\s*(?:' + '|'.join(names) + r')\b') if names else None
    for pattern, name, age, sex in ROLES:
        if name_key(name) in taken or (names and name in GENERIC):
            continue      # "a man just rides a horse" in a story about named people is nobody on stage
        spoken = _dialogue(text)
        for m in re.finditer(r'\b' + DETERMINER + r'(' + pattern + r')\b', text, re.I):
            if any(a <= m.start() < b for a, b in spoken):
                continue  # "That's your mother," said to her face: someone already on stage
            if named and named.match(text, m.end()):
                continue  # "her daughter Rosie", "his mother, Mara": the named person
            # Named by the word the story uses ("the baker", "his grandpa"), so every later mention finds them.
            extra.append(_member(' '.join(m[1].split()).title(), age, sex, len(cast) + len(extra)))
            taken.add(name_key(name))
            break
    return extra

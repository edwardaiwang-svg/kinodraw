"""Repair a v3 answer without mutating it. Every changed value has a readable explanation."""
from __future__ import annotations

import copy
import math
import re
from functools import lru_cache

from .arc import cta_phrase, proof_number
from .schema import OPTIONAL, PLAN_SCHEMA, SCENE
from ...engine.source_diagrams import resolve as resolve_diagram
from ...engine import process_diagrams as pd
from ...library import catalog
from ..match import singular
from .offer import ALIASES, STOP
from .semantics import (actor_named, beats, cast_evidence, detect_cast, name_key,
                        resolve_actor)


@lru_cache(maxsize=1)
def _entry_words() -> dict:
    """Each library picture's naming words: its description, its first keywords and its id."""
    out = {}
    for pid, entry in catalog().items():
        text = ' '.join([entry.get('desc', ''), pid.replace('_', ' ')] + (entry.get('en') or [])[:6])
        out[pid] = {singular(w) for w in re.findall(r'[a-z]+', text.lower())}
    return out


def _ref_words(ref) -> set:
    """The words a picture ref names ("clock_fast" -> clock, fast); library prefixes and function words aside."""
    words = {ALIASES.get(w, w) for w in map(singular, re.findall(r'[a-z]+', ref.lower()))}
    return {w for w in words if len(w) > 2 and w not in STOP and w not in ('svg', 'icon')}


def picture_for(ref, offered, named=lambda ref: 'named') -> tuple[str, str]:
    """(picture id, note) for a planner's picture ref: ('', why) when nothing can be drawn for it.

    An offered picture is drawn; so is any other library picture the scene's words name (``named`` returns the
    rule that names it, '' for none): the offer list steers a planner, it is no render requirement, so a saved plan
    keeps its pictures when a later matcher offers others. A library picture nothing names gives way to the offered
    picture that shares its name word ("clock_fast" -> an offered clock), else it is dropped. A ref that is no
    library id ("couch", "hot_thermometer_icon") becomes the offered picture whose words say most of it."""
    if ref in offered:
        return ref, ''
    entries = _entry_words()
    if ref in catalog():
        why = named(ref)
        if why:
            return ref, ''                  # kept, no change: ``named`` records why (validate's ``kept_pictures``)
        match, word = _same_noun(ref, offered)
        if match:
            return match, f'{ref} is not named by the scene\'s words; drew the offered {match}, also a {word!r}'
        return '', f'{ref} is not named by the scene\'s words and no offered picture shares its name'
    words = _ref_words(ref)
    scored = [(len(words & entries[i]), i) for i in offered if i in entries]
    best = max((n for n, _ in scored), default=0)
    choice = [i for n, i in scored if n == best and n]
    if not choice:
        return '', ''
    match = min(choice, key=lambda i: (len(catalog()[i].get('desc', '')), i))
    return match, f'read {ref!r} as the offered picture {match}'


def _same_noun(did, offered):
    """(the best offered picture whose name says the same noun as library picture ``did``, that noun), offers in
    the matcher's order: a clock for a speeding clock, plain ice for an ice cube."""
    from .offer import _drawing
    name, head = _drawing(did)
    nouns = [head] + [w for w in name if w != head]
    for noun in nouns:
        if len(noun) < 3 or noun in STOP:
            continue
        for other in offered:
            if other != did and other in catalog() and noun in _drawing(other)[0]:
                return other, noun
    return '', ''


# Word forms, so "opened", "households", "children" find "open", "household", "child". Irregular plurals, then
# -ing/-ed (doubled consonants and y restored) and plurals (match.singular). Both sides are reduced the same way.
IRREGULAR = {'children': 'child', 'people': 'person', 'men': 'man', 'women': 'woman', 'feet': 'foot',
             'teeth': 'tooth', 'mice': 'mouse', 'geese': 'goose', 'leaves': 'leaf', 'knives': 'knife',
             'wives': 'wife', 'lives': 'life', 'shelves': 'shelf', 'halves': 'half', 'wolves': 'wolf'}
# A few everyday words for things the library names otherwise (each word -> the names it also says).
SYNONYMS = {'household': ('house', 'home', 'family'), 'home': ('house',), 'kid': ('child',),
            'upstairs': ('stair', 'stairs'), 'downstairs': ('stair', 'stairs'), 'staircase': ('stair', 'stairs'),
            'checklist': ('list',), 'letter': ('mail', 'envelope'), 'note': ('letter',),
            'groceries': ('grocery',), 'mom': ('mother',), 'dad': ('father',), 'tv': ('television',)}


ALIAS_RANK = 6      # a picture's first keywords are its other names; later ones are loose associations ("band")
# Nouns that say where or when after another noun, not what kind of thing it is ("carried the groceries home").
ADVERBS = {'home', 'away', 'back', 'outside', 'inside', 'indoors', 'outdoors', 'upstairs', 'downstairs', 'abroad',
           'today', 'tonight', 'tomorrow', 'yesterday', 'ahead', 'aside', 'together', 'apart', 'overnight'}


def forms(word: str) -> set:
    """The forms a word may take as a picture's name: itself, its lemma, the lemma with a silent e, synonyms."""
    w = word.lower()
    out = {w, singular(w), IRREGULAR.get(w, w)}
    for suffix in ('ing', 'ed'):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            stem = w[:-len(suffix)]
            if stem.endswith('i'):
                stem = stem[:-1] + 'y'                        # carried -> carry
            elif stem[-1] == stem[-2] and stem[-1] not in 'lsz':
                stem = stem[:-1]                              # stopped -> stop
            out |= {stem, stem + 'e'}
    for form in list(out):
        out.update(SYNONYMS.get(form, ()))
    return {f for f in out if f}


def _namer(script_beats, script):
    """named(ref, texts) -> the rule by which the texts name library picture ``ref`` ('' when they do not):

    - the offer's sense matching (offer.Sense.judge) finds a word naming it in its sense;
    - a text says one of its names: the drawing's name words or the library's first keywords for it, in any word
      form or common synonym (forms): "It was a list" names a clipboard list, "downstairs" the stairs down,
      "households" a house, "Fuel" a fuel pump;
    - it is already in the story: an earlier scene kept it (the list stays the list when a later line only says
      "every line").

    Never in another sense: a word that only describes the next noun ("ice crystals" is no ice cube); a person in a
    story of animals; and for a two-word line icon named by one word, a sentence that leans away from it (the
    offer's sense contrast: a plumbing "drip" is no IV drip, "a field" no field hockey)."""
    from .offer import Sense, _drawing, _library, _person, _sentence
    lang = script_beats.get('lang', 'en') if isinstance(script_beats, dict) else 'en'
    entries, index = _library(lang)
    sense = Sense(lang, entries, index, [b['spoken'] for b in script])
    story: set = set()

    @lru_cache(maxsize=None)
    def names(did):
        """Each name of the picture as a tuple of words: name words, head, every keyword."""
        entry = catalog().get(did) or {}
        name, head = _drawing(did)
        out = {(w,) for w in name} | {(head,)} | {tuple(re.findall(r'[a-z]+', tag.lower()))
                                                   for tag in (entry.get('en') or [])[:ALIAS_RANK]}
        return {n for n in out if n and not (len(n) == 1 and (len(n[0]) < 3 or n[0] in STOP))}

    def tokens(text):
        return [(m.start(), m.end(), forms(m.group())) for m in re.finditer(r"[A-Za-z]+(?:'[a-z]+)?", text)]

    def modifier(text, toks, k, n):
        """Does the hit toks[k:k+n] only describe the noun right after it ("ice crystals")?"""
        if k + n >= len(toks):
            return False
        a, b, after = toks[k + n]
        gap = text[toks[k + n - 1][1]:a]
        word = text[a:b].lower()
        return gap.strip() == '' and word not in STOP and word not in ADVERBS and singular(word) in index

    def leans_away(did, text, a, b, said):
        entry = catalog().get(did) or {}
        name, head = _drawing(did)
        if entry.get('set') in ('bespoke', 'tabler') or len(name) != 2 or set(name) <= said:
            return False
        start, end = _sentence(text, a)
        floor = -.05 if head in said else -.03               # the thing itself vs only the word for its kind
        return sense.contrast(did, text[start:end], a - start, b - start) < floor

    def named(ref, texts):
        if sense.no_people and _person(ref):
            return ''
        for text in texts:
            if sense.judge(ref, text):
                return 'a word names it in its sense'
            toks = tokens(text)
            said = set().union(*(f for _, _, f in toks)) if toks else set()
            for name in sorted(names(ref), key=len, reverse=True):
                for k in range(len(toks) - len(name) + 1):
                    if all(name[j] in toks[k + j][2] or singular(name[j]) in toks[k + j][2] for j in range(len(name))):
                        a, b = toks[k][0], toks[k + len(name) - 1][1]
                        if len(name) == 1 and modifier(text, toks, k, 1):
                            continue
                        if leans_away(ref, text, a, b, said):
                            continue
                        return f'the words say {text[a:b]!r}'
        if ref in story:
            return 'it is already in the story (an earlier scene keeps it)'
        return ''
    named.story = story
    return named


def _default(schema):
    if 'enum' in schema:
        return schema['enum'][0]
    kind = schema['type']
    if kind == 'object':
        return {k: _default(s) for k, s in schema['properties'].items()}
    return [] if kind == 'array' else '' if kind == 'string' else 0


# Ids, names, refs and colours are short; a longer model string is noise (script text can steer the planner) and
# is dropped unread, and any string is cut to 4000 characters, so no later pattern or note sees a huge string.
SHORT = frozenset({'id', 'name', 'ref', 'actor', 'at_beat', 'beat_id', 'beat_ids', 'section_id', 'speaker', 'focus_ref',
                   'to', 'set_refs', 'background', 'ink', 'accent', 'accent2', 'body', 'eye'})
SHORT_CAP, TEXT_CAP = 80, 4000


def _shape(value, schema, path, repairs, key=None):
    kind = schema['type']
    if kind == 'string' and isinstance(value, str) and len(value) > (SHORT_CAP if key in SHORT else TEXT_CAP):
        if key in SHORT:
            repairs.append(f'{path}: dropped a value longer than {SHORT_CAP} characters')
            return _default(schema)
        repairs.append(f'{path}: shortened a value longer than {TEXT_CAP} characters')
        value = value[:TEXT_CAP]
    if kind == 'object' and isinstance(value, dict):
        out = {}
        for key in value.keys() - schema['properties'].keys():
            repairs.append(f'{path}: removed unknown property {key}')
        for key, sub in schema['properties'].items():
            where = f'{path}.{key}'
            if key not in value:
                if key not in OPTIONAL:              # an older plan without a later optional field is complete
                    repairs.append(f'{where}: filled missing field')
                out[key] = _default(sub)
            else:
                out[key] = _shape(value[key], sub, where, repairs, key)
        return out
    if kind == 'array' and isinstance(value, list):
        return [_shape(v, schema['items'], f'{path}[{i}]', repairs, key) for i, v in enumerate(value)]
    if kind == 'string' and isinstance(value, str) and ('enum' not in schema or value in schema['enum']):
        return value
    if kind in ('number', 'integer') and isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(value):
        if kind == 'integer' and not isinstance(value, int):
            repairs.append(f'{path}: rounded {value} to an integer')
            return round(value)
        return value
    repairs.append(f'{path}: replaced invalid {kind} value {value!r}')
    return _default(schema)


def _clamp(obj, key, low, high, path, repairs):
    value = obj[key]
    fixed = max(low, value) if high is None else min(high, max(low, value))
    if fixed != value:
        obj[key] = fixed
        repairs.append(f'{path}.{key}: clamped {value} to {fixed}')


def colour_hex(value) -> str | None:
    """#RRGGBB for a colour written as #rgb, a hex without '#', rgb()/hsl(), a CSS colour name or a described
    CSS colour ("warm brown" is brown); else None."""
    from PIL import ImageColor
    text = str(value).strip()
    if len(text) > 80:
        return None
    text = '#' + text if re.fullmatch(r'[0-9a-fA-F]{3}|[0-9a-fA-F]{6}', text) else text
    words = re.split(r'[\s_-]+', text)
    # "dark slate gray" -> darkslategray; "warm brown" / "moss green" -> their colour word (brown, green)
    for spec in (text, ''.join(words), words[-1]):
        try:
            return '#%02X%02X%02X' % ImageColor.getrgb(spec)[:3]
        except ValueError:
            continue
    return None


def _palette(palette, defaults, path, repairs):
    for key, value in palette.items():
        if re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            continue
        fixed = colour_hex(value)
        palette[key] = fixed or defaults[key]
        repairs.append(f'{path}.{key}: read colour {value!r} as {fixed}' if fixed else
                       f'{path}.{key}: replaced invalid hex colour {value!r} with {palette[key]}')


def _luminance(colour):
    rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    return sum(c * w for c, w in zip(linear, (.2126, .7152, .0722)))


def contrast(a, b) -> float:
    x, y = sorted((_luminance(a), _luminance(b)))
    return (y + .05) / (x + .05)


def _contrast(palette, repairs):
    bg, ink = palette['background'], palette['ink']
    if contrast(bg, ink) >= 4.5:
        return
    target = 0 if contrast(bg, '#000000') >= contrast(bg, '#FFFFFF') else 255
    rgb = [int(ink[i:i + 2], 16) for i in (1, 3, 5)]
    for step in range(1, 256):
        colour = '#' + ''.join(f'{round(c + (target - c) * step / 255):02X}' for c in rgb)
        if contrast(bg, colour) >= 4.5:
            palette['ink'] = colour
            repairs.append(f'style.palette.ink: {"darkened" if target == 0 else "lightened"} {ink} to {colour} '
                           'for at least 4.5:1 background contrast')
            return


def _cover(scenes, ids, treatment, repairs, titles=()):
    owners = {}
    known = set(ids)
    supplied = []
    for i, scene in enumerate(scenes):
        for bid in scene['beat_ids']:
            if bid not in known or bid in owners:
                repairs.append(f'scenes[{i}]: dropped unknown or duplicate beat {bid!r}')
            else:
                owners[bid] = i
                supplied.append(bid)
    if supplied != [bid for bid in ids if bid in owners]:
        repairs.append('scenes: reordered coverage to script beat order')
    out, previous = [], None
    runs = set()
    for bid in ids:
        owner = owners.get(bid)
        if owner is None:
            scene = _default(SCENE)
            scene['beat_ids'], scene['treatment'] = [bid], treatment
            if bid in titles:
                # A title beat (a plan saved before it existed) is a title card from the heading, never an empty
                # page: the whiteboard's hand-drawn card, or the heading as title type where scenes are motion.
                scene['treatment'] = 'kinetic_type' if treatment == 'motion' else 'whiteboard'
                scene['text'] = {'kind': 'title', 'ref': bid}
            out.append(scene)
            repairs.append(f'scenes: added missing beat {bid}')
        elif out and previous == owner:
            out[-1]['beat_ids'].append(bid)
        else:
            scene = copy.deepcopy(scenes[owner])
            scene['beat_ids'] = [bid]
            out.append(scene)
            if owner in runs:
                repairs.append(f'scenes[{owner}]: split nonconsecutive beats into consecutive scenes')
            runs.add(owner)
        previous = owner
    for i, scene in enumerate(scenes):
        if i not in owners.values():
            repairs.append(f'scenes[{i}]: removed scene without known beats')
    return out


def _cast_traits(cast, evidence, repairs):
    for c in cast:
        key = name_key(c['name'])
        own = evidence.get(key)
        if own is None:
            continue
        others = {name: cues for name, cues in evidence.items() if name != key}
        traits = dict(own['traits'])
        if traits.get('age') == 'baby' and 'sex' not in traits and c['sex'] != 'unknown' and any(
                cues['traits'].get('sex') == c['sex'] for cues in others.values()):
            traits['sex'] = 'unknown'
        if own['baby_size'] is not None and 'size' not in traits and any(
                cues['traits'].get('size') == c['size'] for cues in others.values()):
            traits['size'] = own['baby_size']
        for field, value in traits.items():
            if c[field] != value:
                repairs.append(f'cast.{c["id"]}.{field}: replaced {c[field]!r} with {value!r} '
                               'using actor-owned script evidence')
                c[field] = value
        marks = []
        for mark in c['marks']:
            owner = next((name for name, cues in others.items() if mark in cues['marks']), None)
            if mark in own['absent_marks'] or (owner and mark not in own['marks']):
                reason = 'contradicted by its script description' if mark in own['absent_marks'] else f'owned by {owner}'
                repairs.append(f'cast.{c["id"]}.marks: removed {mark}, {reason}')
            else:
                marks.append(mark)
        for mark in sorted(own['marks']):
            if mark not in marks:
                marks.append(mark)
                repairs.append(f'cast.{c["id"]}.marks: added actor-owned {mark} from the spoken script')
        if 'none' in marks and any(mark != 'none' for mark in marks):
            marks = [mark for mark in marks if mark != 'none']
            repairs.append(f'cast.{c["id"]}.marks: removed none alongside visible marks')
        if not marks and c['marks']:
            marks = ['none']
            repairs.append(f'cast.{c["id"]}.marks: no remaining marks after script repair')
        c['marks'] = marks


def _words(text) -> str:
    return ' '.join(re.findall(r"\w+(?:['’]\w+)?", str(text).casefold()))


def _verbatim(words, beat) -> bool:
    """Do these words appear in the beat as written or spoken (case, punctuation and quote marks aside)?"""
    words = _words(words)
    return bool(words) and any(f' {words} ' in f' {_words(beat[k])} ' for k in ('text', 'spoken'))


BIBLE_AGE = {'baby': 'baby', 'young': 'child', 'adult': 'adult', 'old': 'old'}


def _shots(scene, path, by_id, cast_by_id, offered, repairs, named=lambda ref: True):
    """Keep each shot's references to this scene's beats, the offered pictures, the cast and the beat's own
    words; a shot's pictures join the scene's picture elements so every renderer and editor sees them."""
    bids = scene['beat_ids']
    shots = [shot for shot in scene['shots'] if shot['beat_id'] in bids]
    if len(shots) != len(scene['shots']):
        repairs.append(f'{path}.shots: dropped shots for beats outside the scene')
    ordered = sorted(shots, key=lambda shot: bids.index(shot['beat_id']))
    if ordered != shots:
        repairs.append(f'{path}.shots: reordered shots to beat order')
    pictures = [e['ref'] for e in scene['elements'] if e['kind'] == 'picture']
    on_stage = {e['ref'] for e in scene['elements'] if e['kind'] == 'cast'}

    def picture(ref, where):
        """The picture id this ref means ('' when none): a library id, or a plain name ("couch", "TV") read as
        the offered drawing whose words say it (picture_for)."""
        given = ref
        ref, note = picture_for(ref, offered, named)
        if note:
            repairs.append(f'{where}: {note}')
        if not ref:
            repairs.append(f'{where}: dropped picture {given!r}, not offered for this scene or named by its words')
            return ''
        if ref not in pictures:
            pictures.append(ref)
            scene['elements'].append({'kind': 'picture', 'ref': ref})
            repairs.append(f'{where}: added shot picture {ref} to the scene elements')
        return ref

    for k, shot in enumerate(ordered):
        where, beat = f'{path}.shots[{k}]', by_id[shot['beat_id']]
        if shot['starts_at'] and not _verbatim(shot['starts_at'], beat):
            repairs.append(f'{where}.starts_at: {shot["starts_at"]!r} is not in {shot["beat_id"]}; shot starts with the beat')
            shot['starts_at'] = ''
        shot['setting']['set_refs'] = list(dict.fromkeys(
            ref for ref in (picture(ref, where + '.setting') for ref in shot['setting']['set_refs']) if ref))
        staged, seen = [], set()
        for member in shot['cast']:
            if member['id'] in cast_by_id and member['id'] not in seen:
                staged.append(member)
                seen.add(member['id'])
            else:
                repairs.append(f'{where}.cast: dropped unknown or repeated cast {member["id"]!r}')
        lines = []
        for line in shot['lines']:
            if line['speaker'] not in cast_by_id or not _verbatim(line['quote'], beat):
                repairs.append(f'{where}.lines: dropped line {line["quote"]!r}: its speaker must be a cast id and '
                               f'its words must be in {shot["beat_id"]}')
                continue
            lines.append(line)
            if line['speaker'] not in seen:
                bible = cast_by_id[line['speaker']]
                staged.append({'id': line['speaker'], 'age': BIBLE_AGE[bible['age']], 'pose': 'talk',
                               'speaking': 'yes'})
                seen.add(line['speaker'])
                repairs.append(f'{where}.cast: added speaker {line["speaker"]}')
        shot['cast'], shot['lines'] = staged, lines
        for member in staged:
            if member['speaking'] != 'off_screen' and member['id'] not in on_stage:
                on_stage.add(member['id'])
                scene['elements'].append({'kind': 'cast', 'ref': member['id']})
                repairs.append(f'{where}.cast: added {member["id"]} to the scene elements')
        props = []
        for prop in shot['props']:
            prop['ref'] = picture(prop['ref'], where + '.props')
            if prop['ref']:
                props.append(prop)
        here = set(shot['setting']['set_refs']) | {prop['ref'] for prop in props}
        for prop in props:
            relation, to = prop['relation'], prop['to']
            partner = to in cast_by_id if relation == 'held_by' else (to in cast_by_id or to in here - {prop['ref']})
            if (relation == 'none') != (not to) or (relation != 'none' and not partner):
                repairs.append(f'{where}.props: {prop["ref"]} {prop["relation"]} {prop["to"]!r} has no such partner '
                               'in the shot; kept without a relation')
                prop['relation'], prop['to'] = 'none', ''
        shot['props'] = props
        if shot['focus_ref']:
            shot['focus_ref'] = picture(shot['focus_ref'], where + '.focus_ref')
            if not shot['focus_ref'] and shot['shot'] in ('insert', 'first_person'):
                # nothing of its own to look at: the shot shows the scene, never a thing held in an earlier one
                repairs.append(f'{where}: {shot["shot"]} shot without a picture to look at; drawn as a medium shot')
                shot['shot'] = 'medium'
        if shot['writing'] and not _verbatim(shot['writing'], beat):
            repairs.append(f'{where}.writing: not verbatim from {shot["beat_id"]}; cleared')
            shot['writing'] = ''
    scene['shots'] = ordered


MAIN = ('picture', 'number_line', 'dots')         # a board's subject; the other kinds label or change it
TARGETED = ('charges', 'link', 'rings', 'highlight', 'hop', 'rotate')
LINK_STYLES = ('straight', 'curved', 'dashed', 'zigzag')


def _spoken_at(beat, cue):
    at = pd.find(beat['spoken'], cue) if cue else 0
    if at is None:
        at = pd.find(beat['text'], cue) or 0
    return at


def _position(item, order, by_id):
    return order[item['beat_id']], _spoken_at(by_id[item['beat_id']], item['cue'])


def _item(beat_id, kind, text='', cue=None, to='', ref='', at='auto', style='none', iid=''):
    return {'id': iid, 'beat_id': beat_id, 'cue': text if cue is None else cue, 'kind': kind, 'ref': ref, 'to': to,
            'at': at, 'text': text, 'style': style}


def _board_items(board, where, scene, by_id, offered, repairs, named=lambda ref: True):
    """Keep the items whose words come from their beat, whose pictures were offered and whose targets are earlier
    items of the same board; repair what has one reading (a missing id, an unheard cue, a lone number line)."""
    bids = scene['beat_ids']
    order = {bid: k for k, bid in enumerate(bids)}
    items, ids = [], set()
    for k, it in enumerate(board['items'][:40]):
        w = f'{where}.items[{k}]'
        if it['beat_id'] not in bids:
            repairs.append(f'{w}: dropped {it["kind"]} for beat {it["beat_id"]!r} outside the scene')
            continue
        beat = by_id[it['beat_id']]
        said = (re.split(r'\s*(?:\.\.\.|…)\s*', it['text'])[0] if it['kind'] == 'equation' else it['text']).strip(
            ' ,.;:!?')
        said = said if said and _verbatim(said, beat) else ''
        if it['cue'] and not _verbatim(it['cue'], beat):
            repairs.append(f'{w}.cue: {it["cue"]!r} is not in {it["beat_id"]}; it appears '
                           + (f'as {said!r} is said' if said else 'as the beat starts'))
            it['cue'] = said
        elif said and _spoken_at(beat, said) < _spoken_at(beat, it['cue']):
            # a thing appears when its own words are said, not at a later cue ("negative charge zigzags" draws
            # the leader then, not at "a tree or a rooftop" ten seconds later)
            repairs.append(f'{w}.cue: {it["cue"]!r} -> {said!r}, where its words are said')
            it['cue'] = said
        if not re.fullmatch(r'[\w-]{1,40}', it['id']) or it['id'] in ids:
            fresh = f'{it["kind"]}_{k + 1}'
            repairs.append(f'{w}.id: named {fresh} (missing or repeated id {it["id"]!r})')
            it['id'] = fresh
        kind = it['kind']
        if kind == 'equation':
            parts = [p for p in re.split(r'\s*(?:\.\.\.|…)\s*', it['text']) if p.strip(' ,.;:!?')]
            ok = bool(parts) and all(_verbatim(p, beat) for p in parts)
        elif kind in ('label', 'dots', 'hop'):
            ok = _verbatim(it['text'], beat) and (
                kind == 'label' or (pd.dots_of(it['text']) if kind == 'dots' else pd.hop_of(it['text'])) is not None)
        else:
            ok = True
            if it['text'] and not _verbatim(it['text'], beat):
                repairs.append(f'{w}.text: {it["text"]!r} is not in {it["beat_id"]}; cleared')
                it['text'] = ''
        if not ok:
            repairs.append(f'{w}: dropped {kind} {it["text"]!r}: its words must be in {it["beat_id"]}'
                           + (' as "N rows of M"' if kind == 'dots' else ' with a number' if kind == 'hop' else ''))
            continue
        if kind == 'picture':
            ref, note = picture_for(it['ref'], offered, named)
            if note:
                repairs.append(f'{w}: {note}')
            if not ref:
                repairs.append(f'{w}: dropped picture {it["ref"]!r}, not offered for this scene or named by its words')
                continue
            it['ref'] = ref
        if kind == 'charges' and it['style'] not in ('plus', 'minus'):
            repairs.append(f'{w}: dropped charges without a plus or minus style')
            continue
        if kind == 'link' and it['style'] not in LINK_STYLES:
            it['style'] = 'straight'
        if kind == 'hop' and it['style'] != 'restart':
            it['style'] = 'none'
        if it['style'] == 'box' and kind != 'label':
            it['style'] = 'none'
        if kind not in ('picture', 'link'):
            it['ref'] = ''
        ids.add(it['id'])
        items.append(it)
    items.sort(key=lambda it: _position(it, order, by_id))
    # an item cued before something it points at brings that thing forward with it ("drops to the ground" draws
    # the ground then; waiting for a later cue instead left the board empty while the step was being said)
    for _ in range(2 * len(items)):
        pos = {i['id']: k for k, i in enumerate(items)}
        late = next(((it, items[pos[r]]) for it in items if it['kind'] != 'picture'
                     for r in (it['to'], it['ref'] if it['kind'] == 'link' else '')
                     if r in pos and pos[r] > pos[it['id']]), None)
        if late is None:
            break
        it, target = late
        items.remove(target)
        items.insert(items.index(it), target)
        target['beat_id'], target['cue'] = it['beat_id'], it['cue']
        repairs.append(f'{where}: {target["kind"]} {target["id"]} now appears with {it["id"]}, which points at it')
    seen, kept = {}, []
    for it in items:
        kind, target = it['kind'], it['to']
        if kind == 'hop' and not target:
            lines = [i for i, k in seen.items() if k == 'number_line']
            target = it['to'] = lines[-1] if lines else ''
        if kind == 'rotate' and not target:
            arrays = [i for i, k in seen.items() if k == 'dots']
            target = it['to'] = arrays[-1] if arrays else ''
        need = {'hop': ('number_line',), 'rotate': ('dots',)}.get(kind)
        missing = (kind in TARGETED and target not in seen) or (need and seen.get(target) not in need) or (
            kind == 'link' and (it['ref'] not in seen or it['ref'] == target))
        if missing:
            repairs.append(f'{where}: dropped {kind} {it["id"]}: it points at {target or it["ref"]!r}, '
                           'not an earlier item of this board')
            continue
        if kind in ('label', 'equation') and target and target not in seen:
            repairs.append(f'{where}: {kind} {it["id"]} points at {target!r}, not an earlier item; written on its own')
            it['to'] = ''
        seen[it['id']] = kind
        kept.append(it)
    board['items'] = kept
    return kept


def _auto_items(scene, by_id, board_items, constructs):
    """Source-bound items read from the beats: a named term gets a label, spoken math an equation; with
    ``constructs``, a lesson's number line and hops ('Start at 0', 'Jump 3'), dot arrays ('3 rows of 5') and
    quarter turns. Returns [(beat_id, item)] in script order."""
    out, line, hops, arrays, turned, n = [], None, 0, None, False, 0
    for bid in scene['beat_ids']:
        text = by_id[bid]['text']
        for sentence in re.split(r'(?<=[.!?])\s+', text):
            if constructs:
                start = re.search(r'\bstart(?:ing)?\s+(?:at|from)\s+' + pd._NUM + r'\b', sentence, re.I)
                if start and line is None:
                    n += 1
                    line = f'line_{n}'
                    out.append((bid, _item(bid, 'number_line', start.group(), iid=line)))
                jumps = _jumps(sentence)
                if jumps:
                    if line is None:
                        n += 1
                        line = f'line_{n}'
                        out.append((bid, _item(bid, 'number_line', '', cue=jumps[0].group(), iid=line)))
                    restart = hops and sentence_restarts(scene, by_id, bid, sentence)
                    for k, m in enumerate(jumps):
                        hops += 1
                        out.append((bid, _item(bid, 'hop', m.group(), to=line,
                                               style='restart' if restart and k == 0 else 'none')))
                rows = pd.ROWS.search(sentence)
                if rows and pd.dots_of(rows.group()):
                    if arrays is None or not turned:
                        if arrays is None:
                            n += 1
                            arrays = f'dots_{n}'
                            out.append((bid, _item(bid, 'dots', rows.group(), iid=arrays)))
                    else:
                        out.append((bid, _item(bid, 'label', rows.group(), to=arrays)))
                if arrays and re.search(r'\b(?:quarter\s+turn|rotate|turn\s+(?:it|the\s+\w+))', sentence, re.I):
                    m = re.search(r'quarter\s+turn|rotate|turn\s+(?:it|the\s+\w+)', sentence, re.I)
                    turned = True
                    out.append((bid, _item(bid, 'rotate', '', cue=m.group(), to=arrays)))
            for a, b in pd.math_runs(sentence):
                phrase = sentence[a:b]
                said = pd.typeset(phrase).replace(' ', '')
                if not any(it['kind'] == 'equation' and it['beat_id'] == bid and (
                        said in pd.typeset(it['text']).replace(' ', '') or
                        pd.typeset(it['text']).replace(' ', '') in said) for it in board_items):
                    out.append((bid, _item(bid, 'equation', phrase)))
            for term in pd.terms(sentence):
                if not any(term.casefold() in it['text'].casefold() for it in board_items + [i for _, i in out]):
                    out.append((bid, _item(bid, 'label', term)))
    return out


def _jumps(sentence):
    """The hops a sentence says ('Jump 5 first, then 3'), when it talks about jumping at all."""
    if not re.search(r'\b(?:jump|hop)', sentence, re.I):
        return []
    return list(re.finditer(r'\b(?:jump|hop|step|then)\s+(?:back\s+)?' + pd._NUM + r'\b', sentence, re.I))


def _complete_lines(boards, scene, by_id, repairs, path):
    """A planner's number line gets every hop the narration says while it is up ('Jump 5 first, then 3' draws
    both hops, never only the first)."""
    order = {bid: k for k, bid in enumerate(scene['beat_ids'])}
    for n, board in enumerate(boards):
        lines = [it for it in board['items'] if it['kind'] == 'number_line']
        if not lines:
            continue
        first = min(order[it['beat_id']] for it in lines)
        last = max(order[it['beat_id']] for it in board['items'])
        taken = {it['id'] for it in board['items']}
        for bid in scene['beat_ids'][first:last + 1]:
            for sentence in re.split(r'(?<=[.!?])\s+', by_id[bid]['text']):
                for k, m in enumerate(_jumps(sentence)):
                    hop = _item(bid, 'hop', m.group())
                    here = _position(hop, order, by_id)
                    line = next((ln for ln in reversed(lines) if _position(ln, order, by_id) <= here), lines[0])
                    on_line = [it for it in board['items'] if it['kind'] == 'hop' and it['to'] == line['id']]
                    said = next((it for it in on_line if it['beat_id'] == bid
                                 and pd.hop_of(it['text']) == pd.hop_of(m.group())), None)
                    before = [it for it in on_line if _position(it, order, by_id) < here]
                    restart = k == 0 and bool(before) and sentence_restarts(scene, by_id, bid, sentence)
                    if said is not None:
                        if restart and said['style'] != 'restart':   # "Now swap the order. Jump 2 first" starts over
                            said['style'] = 'restart'
                            repairs.append(f'{path}.boards[{n}]: hop {said["id"]} starts again from the line\'s start')
                        continue
                    hop['style'] = 'restart' if restart else 'none'
                    i = 1
                    while f'hop_{i}' in taken:
                        i += 1
                    hop['id'], hop['to'] = f'hop_{i}', line['id']
                    taken.add(hop['id'])
                    board['items'].append(hop)
                    repairs.append(f'{path}.boards[{n}]: added hop {m.group()!r} said in {bid}')
        board['items'].sort(key=lambda it: _position(it, order, by_id))


def sentence_restarts(scene, by_id, bid, sentence):
    """A hop sentence starts again from the line's start when the narration has just landed or swapped."""
    text = ' '.join(by_id[b]['text'] for b in scene['beat_ids'][:scene['beat_ids'].index(bid) + 1])
    before = text[:text.rfind(sentence)] if sentence in text else text
    last = before[-160:]
    return bool(re.search(r'\b(?:land(?:s|ed)?\s+on|again|swap|first)\b', last + ' ' + sentence, re.I))


def _boards(scene, path, by_id, offered, intent, repairs, named=lambda ref: True):
    """Validate the scene's boards; build one from the beats when the planner asked for a diagram (``intent``)
    without giving one; add each named term and spoken equation the boards leave out."""
    boards = []
    for n, board in enumerate(scene.get('boards') or []):
        where = f'{path}.boards[{n}]'
        if n >= 3:
            repairs.append(f'{where}: dropped; at most 3 boards per scene')
            continue
        items = _board_items(board, where, scene, by_id, offered, repairs, named)
        if not any(it['kind'] in MAIN + ('label', 'equation') for it in items):
            repairs.append(f'{where}: dropped a board with nothing source-bound to draw')
            continue
        boards.append(board)
    auto = not boards and bool(intent)
    if auto:
        items = []
        pictures = [e['ref'] for e in scene['elements'] if e['kind'] == 'picture']
        for k, ref in enumerate(pictures[:3]):
            bid = next((b for b in scene['beat_ids'] if b in intent), scene['beat_ids'][0])
            items.append(_item(bid, 'picture', '', cue='', ref=ref, iid=f'picture_{k + 1}'))
        boards = [{'layout': 'parts', 'items': items}]
    if not boards:
        scene['boards'] = []
        return
    if not auto:
        _complete_lines(boards, scene, by_id, repairs, path)
    all_items = [it for b in boards for it in b['items']]
    order = {bid: k for k, bid in enumerate(scene['beat_ids'])}
    added = _auto_items(scene, by_id, all_items, constructs=auto)
    taken = {it['id'] for it in all_items}
    for _, it in added:
        k = 1
        while f'{it["kind"]}_{k}' in taken:
            k += 1
        it['id'] = it['id'] or f'{it["kind"]}_{k}'
        taken.add(it['id'])
    if auto and any(it['kind'] in ('number_line', 'dots') for _, it in added):
        # a lesson board: its constructs and words (no keyword icons), one board per idea: a new board where a new
        # construct begins ("Multiplication works the same way. Here are 3 rows of 5 dots.")
        boards, kinds, home = [{'layout': 'parts', 'items': []}], set(), {}
        for _, it in added:
            if it['kind'] in ('number_line', 'dots') and kinds & {'number_line', 'dots'}:
                boards.append({'layout': 'parts', 'items': []})
                kinds = set()
            kinds.add(it['kind'])
            home[it['id']] = boards[-1]
    else:
        home = {}
    rules = {}
    for bid, it in added:
        here = _position(it, order, by_id)
        board = home.get(it['id']) or next(
            (b for b in reversed(boards) if b['items'] and _position(b['items'][0], order, by_id) <= here), boards[0])
        if it['kind'] == 'label' and not it['to'] and pd.is_rule(it['text']):
            it['style'], it['at'] = 'box', 'top_right'          # a named rule heads a rule box
            rules[bid] = it['id']
        elif it['kind'] == 'equation' and bid in rules and not it['to']:
            it['to'] = rules[bid]                               # the rule's equation is written inside its box
        elif it['kind'] == 'label' and not it['to']:
            host = next((h for h in reversed(board['items']) if h['beat_id'] == bid and not h['text']
                         and h['kind'] in ('link', 'charges', 'rings')), None)
            if host is not None:
                host['text'] = it['text']
                repairs.append(f'{path}: labelled {host["id"]} {it["text"]!r}, the term {bid} names')
                continue
            named = next((h for h in reversed(board['items']) if h['beat_id'] == bid
                          and h['kind'] not in ('label', 'equation', 'hop', 'rotate', 'highlight')), None)
            it['to'] = named['id'] if named is not None else ''
        board['items'].append(it)
        board['items'].sort(key=lambda i: _position(i, order, by_id))
        if not auto or not any(i['kind'] in ('number_line', 'dots') for _, i in added):
            repairs.append(f'{path}: added {it["kind"]} {it["text"]!r} that {bid} says')
    for b in boards:
        for it in b['items']:
            if it['kind'] in ('label', 'equation') and it['to'] and not any(o['id'] == it['to'] for o in b['items']):
                it['to'] = ''
    scene['boards'] = [b for b in boards if b['items']]
    if auto:
        repairs.append(f'{path}: diagram {", ".join(sorted(intent))}: built a board from the scene\'s pictures and '
                       'the words the beats say')


BOARD_PICTURES = 3          # pictures a board draws at most, its own and the scene's


def _board_pictures(scene, path, by_id, repairs):
    """A board sits beside its scene's pictures, never in place of them: a scene picture no board draws joins
    the board (up to BOARD_PICTURES), appearing when its beat names it, else when the scene starts."""
    boards = scene.get('boards') or []
    if not boards:
        return
    drawn = {it['ref'] for b in boards for it in b['items'] if it['kind'] == 'picture'}
    order = {bid: k for k, bid in enumerate(scene['beat_ids'])}
    taken = {it['id'] for b in boards for it in b['items']}
    for e in scene['elements']:
        if e['kind'] != 'picture' or e['ref'] in drawn:
            continue
        board = min(boards, key=lambda b: sum(it['kind'] == 'picture' for it in b['items']))
        if sum(it['kind'] == 'picture' for it in board['items']) >= BOARD_PICTURES:
            break
        names = _ref_words(e['ref']) | _ref_words((catalog().get(e['ref']) or {}).get('desc', ''))
        bid, cue = scene['beat_ids'][0], ''
        for b in scene['beat_ids']:
            hit = next((m for m in re.finditer(r'[A-Za-z]+', by_id[b]['text'])
                        if singular(m.group().lower()) in names), None)
            if hit:
                bid, cue = b, hit.group()
                break
        k = 1
        while f'picture_{k}' in taken:
            k += 1
        item = _item(bid, 'picture', '', cue=cue, ref=e['ref'], iid=f'picture_{k}')
        taken.add(item['id'])
        drawn.add(e['ref'])
        here = _position(item, order, by_id)          # ahead of what is said with or after it: words point at it
        at = next((k for k, it in enumerate(board['items']) if _position(it, order, by_id) >= here),
                  len(board['items']))
        board['items'].insert(at, item)
        repairs.append(f'{path}: the board draws the scene picture {e["ref"]} '
                       + (f'when {bid} says {cue!r}' if cue else 'from the start'))


def _merge_diagram_scenes(scenes, script_beats, repairs):
    """Consecutive scenes that each ask for a diagram of their own beat (and give no board) are one build-up:
    merge them so a single board grows across their beats instead of restarting every beat."""
    def wants(scene):
        return not scene.get('boards') and any(
            e['kind'] == 'diagram' and e['ref'] in scene['beat_ids'] and resolve_diagram(script_beats, e['ref']) is None
            for e in scene['elements'])
    out = []
    for scene in scenes:
        if out and wants(scene) and wants(out[-1]):
            last = out[-1]
            repairs.append(f'scenes: merged the diagram scene of {", ".join(scene["beat_ids"])} into the one before '
                           'so its board builds up')
            last['beat_ids'] = last['beat_ids'] + scene['beat_ids']
            last['elements'] = last['elements'] + [e for e in scene['elements'] if e not in last['elements']]
            last['actions'] = last['actions'] + scene['actions']
            last['shots'] = (last.get('shots') or []) + (scene.get('shots') or [])
            last['hold_s'] = last['hold_s'] + scene['hold_s']
            if last['text']['kind'] == 'none':
                last['text'] = scene['text']
            continue
        out.append(scene)
    return out


def validate(plan, script_beats, candidates, kept_pictures=None) -> tuple[dict, list[str]]:
    """Return (repaired plan, repairs). Invalid script ids raise ValueError rather than inventing coverage.

    Repairs list changes only (a saved plan re-checks clean); ``kept_pictures``, when given, collects why each library picture
    the matcher did not offer stays ("kept tb_clipboard_list, not offered: the words say 'list'").

    Text references are beat ids; pictures must be offered for a beat in their scene. Scene holds cover
    all distinct on-screen references at 27 chars/s (all beats for sequential caption_only scenes).
    """
    script = beats(script_beats)
    by_id = {b['id']: b for b in script}
    repairs = []
    out = _shape(plan, PLAN_SCHEMA, 'plan', repairs)
    style = out['style']
    _clamp(style, 'energy', 1, 5, 'style', repairs)
    _clamp(style, 'tempo_bpm', 40, 240, 'style', repairs)
    _palette(style['palette'], {'background': '#FFFFFF', 'ink': '#1B1B1B',
                               'accent': '#287FA3', 'accent2': '#D39B36'}, 'style.palette', repairs)
    _contrast(style['palette'], repairs)

    cast, ids, names = [], set(), set()
    for c in out['cast']:
        if not c['name'] or c['name'].casefold() in names or c['id'] in ids:
            repairs.append(f'cast: dropped unnamed or duplicate character {c["name"]!r} / {c["id"]!r}')
            continue
        if not c['id']:
            c['id'] = re.sub(r'\W+', '_', c['name'].lower()) or 'character'
            while c['id'] in ids:
                c['id'] += '_2'
            repairs.append(f'cast: assigned id {c["id"]} to {c["name"]}')
        ids.add(c['id'])
        names.add(c['name'].casefold())
        _clamp(c, 'size', .3, 2.0, f'cast.{c["id"]}', repairs)
        _palette(c['palette'], {'body': '#DCA45C', 'accent': '#F2D4A4', 'eye': '#202020'},
                 f'cast.{c["id"]}.palette', repairs)
        cast.append(c)
    for c in detect_cast(script):
        if any(name_key(existing['name']) == name_key(c['name']) for existing in cast):
            continue
        while c['id'] in ids:
            c['id'] += '_2'
        cast.append(c)
        ids.add(c['id'])
        repairs.append(f'cast: added named character {c["name"]} from the spoken script')
    _cast_traits(cast, cast_evidence(script), repairs)
    out['cast'] = cast
    cast_by_id = {c['id']: c for c in cast}

    sections = list(dict.fromkeys(b['section'] for b in script))
    intents = {}
    for section in out['storyboard']['sections']:
        sid = section['section_id']
        if sid not in sections or sid in intents:
            repairs.append(f'storyboard.sections: dropped unknown or duplicate section {sid!r}')
        else:
            intents[sid] = section
    if list(intents) != [s for s in sections if s in intents]:
        repairs.append('storyboard.sections: reordered section intents to script order')
    for sid in sections:
        if sid not in intents:
            intents[sid] = {'section_id': sid, 'intent': next(b['text'] for b in script if b['section'] == sid)}
            repairs.append(f'storyboard.sections: added intent for {sid}')
    out['storyboard']['sections'] = [intents[sid] for sid in sections]

    namer = _namer(script_beats, script)
    default_treatment = 'motion' if style['mode'] == 'motion' else 'whiteboard'
    titles = {bid for bid, b in by_id.items() if b.get('kind') == 'title'}
    out['scenes'] = _merge_diagram_scenes(_cover(out['scenes'], list(by_id), default_treatment, repairs, titles),
                                          script_beats, repairs)
    for i, scene in enumerate(out['scenes']):
        path = f'scenes[{i}]'
        bids = scene['beat_ids']
        offered = list(dict.fromkeys(c if isinstance(c, str) else c['id'] for bid in bids for c in (
            candidates.get(bid, []) if isinstance(candidates, dict) else candidates) or ()))   # the matcher's order
        texts = [by_id[bid]['spoken'] for bid in bids]
        def named(ref, texts=texts, path=path):
            why = namer(ref, texts)
            note = f'{path}: kept {ref}, not offered: {why}'
            if why and kept_pictures is not None and note not in kept_pictures:
                kept_pictures.append(note)
            return why
        elements, intent = [], set()
        for e in scene['elements']:
            allowed = (offered if e['kind'] == 'picture' else set(cast_by_id) if e['kind'] == 'cast' else
                       {scene['atmosphere']['kind']} - {'none'} if e['kind'] == 'atmosphere' else set(bids))
            if e['kind'] == 'diagram':
                allowed = {bid for bid in bids if resolve_diagram(script_beats, bid) is not None}
                if e['ref'] in set(bids) - allowed:
                    # not a closed dot-array/panel beat: the planner's diagram intent becomes a board (below)
                    intent.add(e['ref'])
                    repairs.append(f'{path}: diagram ref {e["ref"]!r} is not a dot-array or panel beat; '
                                   'drawn as a board')
                    continue
            if e['kind'] == 'picture':
                ref, note = picture_for(e['ref'], offered, named)
                if note:
                    repairs.append(f'{path}: {note}')
                if not ref:
                    repairs.append(f'{path}: dropped unknown or out-of-scene picture ref {e["ref"]!r}')
                elif all(o['ref'] != ref for o in elements if o['kind'] == 'picture'):
                    elements.append({**e, 'ref': ref})
            elif e['ref'] in allowed:
                elements.append(e)
            else:
                repairs.append(f'{path}: dropped unknown or out-of-scene {e["kind"]} ref {e["ref"]!r}')
        scene['elements'] = elements
        _boards(scene, path, by_id, offered, intent, repairs, named)
        if scene['boards']:
            if style['mode'] == 'motion':
                style['mode'] = 'hybrid'
                repairs.append(f'style.mode: motion -> hybrid; {path} draws a board on the whiteboard')
            if scene['treatment'] != 'whiteboard':
                repairs.append(f'{path}: {scene["treatment"]} -> whiteboard; its board is drawn on the whiteboard')
                scene['treatment'] = 'whiteboard'
        kept, staged = [], {e['ref'] for e in elements if e['kind'] == 'cast'}
        for action in scene['actions']:
            ref, bid = resolve_actor(action['actor'], cast_by_id), action['at_beat']
            if ref is not None and ref != action['actor']:
                repairs.append(f'{path}: action actor {action["actor"]!r} read as cast id {ref!r}')
                action['actor'] = ref
            actor = cast_by_id.get(ref)
            # present = named in the beat ("Dana", "a little girl" for "Dana as a little girl") or staged in the
            # scene (a cast element, or on screen in that beat's shot): pronouns and "you" scripts keep actions
            present = actor is not None and bid in bids and (
                actor_named(actor['name'], by_id[bid]['spoken']) or ref in staged
                or any(shot.get('beat_id') == bid and c.get('id') == ref and c.get('speaking') != 'off_screen'
                       for shot in scene.get('shots') or [] for c in shot.get('cast') or []))
            if not present:
                repairs.append(f'{path}: dropped action {action["verb"]} by {action["actor"]!r} '
                               f'at {bid!r}; that actor is not named or staged in the scene')
                continue
            _clamp(action, 'intensity', 1, 3, path + '.action', repairs)
            kept.append(action)
        scene['actions'] = kept
        _shots(scene, path, by_id, cast_by_id, offered, repairs, named)
        _board_pictures(scene, path, by_id, repairs)
        namer.story.update(e['ref'] for e in scene['elements'] if e['kind'] == 'picture')
        _clamp(scene['atmosphere'], 'density', 0, 1, path + '.atmosphere', repairs)
        _clamp(scene, 'hold_s', 0, None, path, repairs)
        forced = ('whiteboard' if style['mode'] == 'whiteboard' else
                  'motion' if style['mode'] == 'motion' and scene['treatment'] == 'whiteboard' else scene['treatment'])
        if forced != scene['treatment']:
            repairs.append(f'{path}: changed {scene["treatment"]} treatment to {forced} for {style["mode"]} mode')
            scene['treatment'] = forced
        text = scene['text']
        if text['kind'] == 'none' and text['ref']:
            text['ref'] = ''
            repairs.append(f'{path}.text: cleared unused ref')
        elif text['kind'] != 'none' and text['ref'] not in bids:
            repairs.append(f'{path}.text: dropped unknown or out-of-scene ref {text["ref"]!r}')
            scene['text'] = {'kind': 'none', 'ref': ''}
        kind, ref = scene['text']['kind'], scene['text']['ref']
        if kind == 'counter' and not proof_number(by_id[ref]['text']):
            scene['text']['kind'] = 'kinetic'
            repairs.append(f'{path}.text: a counter needs a spoken quantity in {ref} (not a part number or year); '
                           'showing kinetic text')
        elif kind == 'cta' and not cta_phrase(by_id[ref]['text']):
            scene['text']['kind'] = 'kinetic'
            repairs.append(f'{path}.text: a call to action needs an imperative such as "Sign up" in {ref}; '
                           'showing kinetic text')
        refs = {e['ref'] for e in elements if e['kind'] == 'text'}
        if scene['text']['kind'] != 'none':
            refs.update(bids if scene['text']['kind'] == 'caption_only' else [scene['text']['ref']])
        reading = sum(len(by_id[bid]['text']) for bid in refs) / 27
        if scene['hold_s'] < reading:
            scene['hold_s'] = reading
            repairs.append(f'{path}.hold_s: extended to {reading:.3f}s for reading at 27 chars/s')
    return out, repairs

"""Saved Director-v3 scenes on the narration timeline, evaluated only from absolute time.

The whiteboard is constructed directly: fallback must never recurse through dispatch.
No provider is called here; workers consume the same persisted plan and local props.
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import json
import math
import re
import textwrap
from dataclasses import dataclass, fields, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageOps

from .. import markup, library
from . import motion
from ..director.v3 import arc
from ..director.v3.semantics import ACTION_CUES, beats, mentions, name_key
from . import timeline
from .captions import wrap as caption_wrap
from .atmos import Atmosphere, compose
from .bold import MotionElement, MotionScene, Palette, render_frame, render_transition
from .bold.render import _SceneLayers
from .creatures import Genome, Action, raster
from .creatures.actions import ACTIONS, add, cue_pose, target_response, travel_x
from .creatures.draw import H as RIG_HEIGHT

ANCHOR_GLIDE = .45   # seconds the recurring anchor point takes to glide to its next stop
TRAVEL_MARGIN = .03  # share of the frame width a walking or running actor keeps clear of the right edge
# J 2026-10-07: story characters are preset library doodles (engine.storybook), never the procedural rig.
STORY_DOODLES = True
NEGATED_ACTION = re.compile(r"\b(?:never|cannot|no\s+longer)\b|\bnot\b(?!\s+only\b)|\b\w+n['’]t\b", re.I)


def camera_move(image, zoom, dx, dy, fill):
    """Zoom about the centre and pan by (dx, dy), uncovered edges in `fill`."""
    w, h = image.size
    inv = 1 / zoom
    return image.transform((w, h), Image.AFFINE, (inv, 0, w / 2 * (1 - inv) + dx, 0, inv, h / 2 * (1 - inv) + dy),
                           Image.BICUBIC, fillcolor=fill)


def _contrast(a, b):
    from .skin import contrast
    return contrast(a, b)


def seed(value):
    return int.from_bytes(hashlib.sha256(str(value).encode()).digest()[:4], 'big')


def action_char(text, actor, verb, cast, cue=None):
    """Locate a cue in its nearest named subject's clause, preserving source offsets."""
    names = sorted({name_key(g.name) for g in cast.values()}, key=lambda n: (-len(n), n))
    pattern = '|'.join(re.escape(n) for n in names if n)
    owners = list(re.finditer(r'(?<!\w)(?:' + pattern + r')(?!\w)', text, re.I)) if pattern else []
    for hit in re.finditer(r'\b(?:' + (cue or ACTION_CUES.get(verb, r'(?!)')) + r')\b', text, re.I):
        owner = next((m for m in reversed(owners) if m.end() <= hit.start()), None)
        if owner is None or owner.group().casefold() != name_key(cast[actor].name):
            continue
        tail = text[owner.end():hit.start()]
        # An introductory noun phrase describes the owner, rather than a fresh subject.
        intro = re.match(r'^,\s+(?:a|an)\s+[^,]+,', tail, re.I)
        if intro:
            tail = tail[intro.end():]
        if re.search(r'[.!?;\n]|\b(?:while|whereas|when)\b|'
                     r'\b(?:but|and)\s+(?:the|a|an|he|she|it|they)\b', tail, re.I):
            continue
        if re.search(r'\b(?:him|her|them)\s*$', tail, re.I):
            continue
        clause = re.split(r'\bbut\b', tail, flags=re.I)[-1]
        if NEGATED_ACTION.search(clause):
            continue
        return hit.start()
    if verb == 'idle':
        return next((m.end() for m in owners if m.group().casefold() == name_key(cast[actor].name)), None)
    return None


def hyena_quantity(text):
    """Use explicit counts; an unspecified plural supports only two representatives."""
    numbers = {'no': 0, 'zero': 0, 'a': 1, 'an': 1, 'single': 1, 'one': 1,
               'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
               'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
    counts, unspecified = [], False
    for noun in re.finditer(r'\bhyenas?\b', text, re.I):
        clause = re.split(r'[.!?;\n]', text[:noun.start()])[-1]
        quantity = re.search(r'\b(' + '|'.join(numbers) + r'|\d+)\s+(?:(?!(?:of|and)\b)[a-z]+\s+){0,2}$', clause, re.I)
        if quantity:
            word = quantity[1].lower()
            counts.append(int(word) if word.isdigit() else numbers[word])
        else:
            plural = noun.group().lower() == 'hyenas'
            counts.append(2 if plural else 1)
            unspecified |= plural
    # Repeated references to a group do not imply additional animals.
    return max(counts, default=0), unspecified


def cast_genome(entry):
    """Translate contract traits without inferring traits from another actor's words."""
    value = dict(entry)
    value['seed'] = seed(entry['id'])
    value['temperament'] = {'gentle': 'calm', 'timid': 'shy', 'wise': 'calm', 'sly': 'bold'}.get(
        entry['temperament'], entry['temperament'])
    if 'mane_black' in value['marks'] or 'mane_gold' in value['marks']:
        if value['sex'] == 'unknown':
            value['sex'] = 'male'
    return Genome.from_dict(value)


@dataclass
class Span:
    start: float
    end: float
    spec: dict
    motion: MotionScene | None = None
    atmos: Atmosphere | None = None
    actors: tuple = ()
    actions: tuple = ()
    join: float = 0.
    join_length: float = 0.
    source_chart: bool = False
    scientific: tuple = ()
    source_character: bool = False
    motion_art: MotionScene | None = None
    actor_layout: dict | None = None
    diagram: object | None = None
    diagrams: tuple = ()
    source_proof: bool = False
    story: list | None = None
    stacked: bool = False       # a proof counter or a call to action owns the frame's centre column
    on_screen: tuple = ()       # beats whose own words the scene writes on screen (no caption repeats them)


class HybridProduction:
    @property
    def vertical(self):
        return self.whiteboard.vertical

    @vertical.setter
    def vertical(self, value):
        # The outer portrait compositor owns chrome/captions for every scene.
        self.whiteboard.vertical = value
        self.cutaway.vertical = value

    def __init__(self, episode, tline, lang, project_dir, plan, whiteboard):
        self.ep, self.tl, self.lang = episode, tline, lang
        self.plan, self.whiteboard = plan, whiteboard
        self.whiteboard.motion_floor = plan['style']['motion_floor']
        self.cutaway = copy.copy(whiteboard)
        self.cutaway.cap_starts = []  # joins carry one sharp caption at actual narration time
        self.size, self.duration = whiteboard.size, tline['duration']
        self.native = getattr(whiteboard, 'native', False)
        self.square = self.native and self.size[0] == self.size[1]
        self._square_layers = {}
        self._text_layers = {}
        self.ctx, self.els, self.cap_words = whiteboard.ctx, whiteboard.els, whiteboard.cap_words
        self.warnings = list(whiteboard.warnings)
        self.by_id = {b['id']: b for b in beats(episode, lang)}
        from .. import speech
        self.labels = speech.screenplay_labels(b['text'] for b in self.by_id.values())
        self._shown_text = {}
        self.marked = {b['id'] for b in episode['beats'] if markup.board(b, lang)}     # code, formula, warning
        self.cast = {c['id']: cast_genome(c) for c in plan['cast']}
        for c in plan['cast']:
            if c['family'] not in ('feline', 'canine', 'human', 'other'):
                self.warnings.append(f"hybrid: cast family {c['family']} uses quadruped fallback")
            dropped = set(c['marks']) - set(self.cast[c['id']].marks) - {'none'}
            if STORY_DOODLES and plan['storyboard']['genre'] == 'story':
                from .storybook import MARKS
                dropped -= MARKS                 # the storybook draws these on its preset doodles
            if dropped:
                self.warnings.append(f"hybrid: cast {c['id']} unsupported marks {sorted(dropped)}")
        self.style = plan['style']
        # Captions over motion scenes take the palette (its ink in a thin outline of its background, the word being
        # said in its accent) instead of the whiteboard's dark letters in a thick white outline, which smear on a
        # dark palette. Whiteboard scenes keep the whiteboard's own captions.
        palette = {k: ImageColor.getrgb(v)[:3] for k, v in self.style['palette'].items()}
        self.caption_look = (palette['ink'], palette['background'], 4)
        # The word being said takes the accent, or the second accent when the first can't stand apart from the
        # letters on this background (a dark green next to dark slate letters: no word lit at all).
        from .captions import highlight_color
        self.caption_accent = next((palette[k] for k in ('accent', 'accent2') if k in palette and
                                    highlight_color(palette[k], palette['ink'], palette['background']) != palette['ink']),
                                   palette['accent'])
        self.storybook = None
        self.story_genre = plan['storyboard']['genre'] == 'story'
        if STORY_DOODLES and (self.story_genre or any(self._staged(s) for s in plan['scenes'])):
            # Stories, and the people and animals of every other genre (a recipe's cook, a promo's customer), are
            # staged by the storybook: sets for places, people presets, the plan's shots. Only a story gets its
            # picture-book title page.
            from .storybook import Storybook
            title = episode.get('title', '')
            title = title.get(lang, next(iter(title.values()), '')) if isinstance(title, dict) else str(title or '')
            self.storybook = Storybook(plan, self.by_id, tline, self.size, whiteboard.skin.background,
                                       title if self.story_genre else '')
        for c in plan['cast']:
            if c['id'] in self.cast and self.cast[c['id']].family == 'human':
                # A person's skin is a skin tone, never the plan palette's body colour (a green Marcus); the palette
                # still dresses them.
                self.cast[c['id']] = replace(self.cast[c['id']], palette=replace(
                    self.cast[c['id']].palette, body=self._skin(c)))
        # Same score selection as finish; the procedural score and every recording start on beat zero.
        from ..audio import score
        self.score_beats = np.array([])
        if (self.style['music_mood'] != 'none' or score.own(episode.get('music'), '.')) and episode.get('music', True):
            _, bpm = score.source(episode.get('music'), self.style['music_mood'], self.style['tempo_bpm'])
            self.score_beats = score.beat_grid(self.duration, bpm)
        self.spans = []
        specs = plan['scenes']
        covered = [bid for s in specs for bid in s['beat_ids']]
        if covered != tline['beat_order']:
            raise ValueError('Saved plan_v3 must cover timeline beat_order exactly; direct the changed script again')
        for i, spec in enumerate(specs):
            start = tline['beats'][spec['beat_ids'][0]]['start']
            end = (tline['beats'][specs[i + 1]['beat_ids'][0]]['start'] if i + 1 < len(specs)
                   else tline['end_card']['start'])
            span = Span(start, end, spec)
            span.join_length = min(.65, (end - start) / 3)
            available = self.score_beats[(self.score_beats >= start - 1e-9) &
                                         (self.score_beats <= end - span.join_length)]
            span.join = float(available[0]) if len(available) else start
            if i and len(self.score_beats) and not len(available):
                self.warnings.append(f'hybrid: source span {spec["beat_ids"]} too short for a score-aligned join')
            self._prepare(span, project_dir)
            if span.scientific or (self.spans and self.spans[-1].scientific):
                span.join = span.start
            if self.native and span.atmos:
                span.atmos.internal_size = self.size
            if self.square and span.motion:
                self._reflow_square(span)
            self.spans.append(span)
        self.starts = [s.start for s in self.spans]
        self.cuts = [s.join for i, s in enumerate(self.spans[1:], 1)
                     if s.spec['transition_in'] == 'cut' or s.scientific or self.spans[i - 1].scientific]
        self.warnings.append('hybrid: hold_s is a reading target inside source spans; narration timing is preserved')
        self.anchor_keys = self._anchor_keys()
        self.screen_notes = self._screen_notes()
        if self.screen_notes:
            build = Path(project_dir) / 'build'
            build.mkdir(parents=True, exist_ok=True)
            (build / 'screen-text.json').write_text(json.dumps(
                [{'start': round(a, 3), 'end': round(b, 3), 'kind': k, 'text': w} for a, b, k, w in self.screen_notes],
                ensure_ascii=False, indent=1), encoding='utf-8')
        if self.storybook is not None:
            # The quoted spans the story pages draw in speech bubbles, for the captions to leave to them.
            build = Path(project_dir) / 'build'
            build.mkdir(parents=True, exist_ok=True)
            (build / 'bubbles.json').write_text(json.dumps(self.storybook.bubbled, ensure_ascii=False, indent=1),
                                                encoding='utf-8')
            # Every movement verb the pages read and whether its actor moved (engine.acting), for the QA.
            (build / 'acts.json').write_text(json.dumps(self.storybook.acted, ensure_ascii=False, indent=1),
                                             encoding='utf-8')
        self._leave_bubbled_lines_to_the_bubbles()

    @staticmethod
    def _staged(spec):
        """A scene of a genre other than story that the storybook stages from its plan shots: a character scene, or
        any scene with cast on stage, that is not a board, chart, diagram or kinetic type and whose on-screen text is
        at most a caption or a quote (a title, call to action, counter or kinetic text stays a motion scene)."""
        return bool(spec.get('shots')) and spec['treatment'] not in ('whiteboard', 'chart', 'kinetic_type') and (
            spec['text']['kind'] in ('none', 'caption_only', 'quote')) and not any(
            e['kind'] == 'diagram' for e in spec['elements']) and (
            spec['treatment'] == 'character' or any(e['kind'] == 'cast' for e in spec['elements']))

    def _skin(self, entry):
        """A person's skin colour: the tone the storybook dresses them in, else their tone mark, else one of the
        people presets' tones chosen from their id."""
        from .storybook import TONE_MARKS, TONES
        from .shots import SKIN
        tone = None
        if self.storybook is not None and entry['id'] in self.storybook.cast and self.storybook._human(entry['id']):
            tone = self.storybook._look(entry['id'])['tone']
        tone = tone or next((TONE_MARKS[m] for m in map(str.lower, entry.get('marks') or ()) if m in TONE_MARKS),
                            TONES[sum((i + 1) * ord(ch) for i, ch in enumerate(entry['id'])) % 3])
        return '#%02X%02X%02X' % SKIN[tone]

    def _prepare(self, span, project_dir):
        spec = span.spec
        duration = span.end - span.start
        treatment = spec['treatment']
        if self.marked.intersection(spec['beat_ids']):
            # Code, a formula or a warning card (markup.py) is drawn on its own whiteboard page, whatever the plan
            # chose for the scene: never a storybook page, kinetic type or a caption over a picture.
            span.source_proof = True
            return
        if self.storybook is not None and (self._staged(spec) if not self.story_genre else (
                treatment not in ('whiteboard', 'chart') and not any(e['kind'] == 'diagram' for e in spec['elements']))):
            # A story page: preset doodles on the whiteboard paper, one shot per narrated sentence.
            span.story = self.storybook.prepare(spec, span.start, span.end)
            return
        text = ' '.join(self.by_id[b]['spoken'] for b in spec['beat_ids'])
        actors = [e['ref'] for e in spec['elements'] if e['kind'] == 'cast' and e['ref'] in self.cast]
        if not actors and (treatment in ('character', 'atmosphere') or spec['actions']):
            # An explicit cast stage selects participants; incidental source
            # mentions (such as a parent already away hunting) do not add actors.
            actors += [key for key, g in self.cast.items() if mentions(g.name, text) and key not in actors]
        actors += [a['actor'] for a in spec['actions'] if a['actor'] in self.cast and a['actor'] not in actors]
        actors = list(dict.fromkeys(actors))
        character_intent = treatment == 'character' or spec['actions'] or any(
            e['kind'] == 'cast' for e in spec['elements'])
        if character_intent:
            count, unspecified = hyena_quantity(text)
            existing = sum(self.cast[key].species == 'hyena' for key in actors)
            if unspecified and count > existing:
                self.warnings.append('hybrid: hyena count unspecified; showing two representatives of the plural group')
            for i in range(max(0, count - existing)):
                key = f'crowd-hyena-{i}'
                while key in actors or any(c['id'] == key for c in self.plan['cast']):
                    i += 1
                    key = f'crowd-hyena-{i}'
                actors.append(key)
                self.cast[key] = Genome.from_dict({'name': key, 'species': 'hyena', 'size': .75, 'seed': seed(key),
                                                   'palette': {'body': '#998267', 'accent': '#DBC5A2', 'eye': '#C59243'}})
        span.actors = tuple(dict.fromkeys(actors))
        events = []
        for a in spec['actions']:
            if a['actor'] not in self.cast:
                self.warnings.append(f"hybrid: unknown actor {a['actor']}")
                continue
            if a['verb'] not in ACTIONS and a['verb'] != 'idle':
                self.warnings.append(f"hybrid: action {a['verb']} uses breathing/looking fallback")
                continue
            beat = self.by_id[a['at_beat']]
            timing = self.tl['beats'][a['at_beat']]
            char = self._source_action_char(beat, a['actor'], a['verb'])
            target = None
            if a['verb'] == 'sleep':
                contact = self._sleep_contact(beat, a['actor'])
                if contact:
                    char, target = contact
                    if target not in actors:
                        actors.append(target)
            if char is None:
                self.warnings.append(f"hybrid: {a['verb']} by {a['actor']} at {a['at_beat']} lacks an unambiguous positive source cue; skipped")
                continue
            if a['verb'] == 'nudge':
                char = self._nudge_char(beat['spoken'], a['actor'], char)
                target = self._nudge_target(beat, a['actor'], char) if char is not None else None
                if target is None:
                    self.warnings.append(f"hybrid: nudge by {a['actor']} at {a['at_beat']} lacks an unambiguous source subject/target; skipped")
                    continue
                if target not in actors:
                    actors.append(target)
            ct = timing['char_times']
            at = timing['start'] + (ct[min(char, len(ct) - 1)] if ct else 0)
            remaining = max(.1, min(timing['speech_end'], span.end) - at)
            action = Action(a['verb'], at - span.start, min(remaining, Action(a['verb']).seconds), a['intensity'] / 3)
            if a['verb'] == 'swipe':
                target = self._swipe_target(beat, a['actor'], char, actors)
                if target and target not in actors:
                    actors.append(target)
            elif a['verb'] == 'hide':
                target = self._hide_target(beat, a['actor'], char)
                if target and target not in actors:
                    actors.append(target)
            events.append((a['actor'], action, target))
        span.actors = tuple(dict.fromkeys(actors))
        span.actions = tuple(events)
        self._group_actions(span, events)
        self._source_reactions(span, events)
        span.actions = tuple(events)
        kind = spec['atmosphere']['kind']
        aliases = {'night_stars': ['night_sky', 'starfield'],
                   'fog_with_shooting_star': ['night_sky', 'starfield', 'shooting_star', 'fog'],
                   'shooting_star': ['night_sky', 'starfield', 'shooting_star'], 'rays': ['light_rays']}
        if kind != 'none':
            layers = aliases.get(kind, [kind])
            if kind == 'underwater':
                layers = ['fog', 'light_rays']
                self.warnings.append('hybrid: underwater uses fog/rays fallback')
            layers = [({'kind': k, 'window': (min(.5, duration / 4), max(.6, duration * .8))}
                       if k == 'shooting_star' else k) for k in layers]
            span.atmos = Atmosphere(layers, {'background': self.style['palette']['background'],
                'foreground': self.style['palette']['ink'], 'accent': self.style['palette']['accent']},
                spec['atmosphere']['density'], seed(spec['beat_ids']))
        from .source_diagrams import resolve as resolve_diagram, PanelMotion
        for element in spec['elements']:
            if element['kind'] == 'diagram':
                diagram = resolve_diagram(self.ep, element['ref'])
                if diagram and diagram.kind == 'panels':
                    span.diagrams += (PanelMotion(diagram, self.tl, self.size, self.whiteboard.skin,
                                                  self.style['palette'], self.style['motion_floor'],
                                                  speech_end=min(span.end, max(self.tl['beats'][bid]['speech_end']
                                                                              for bid in spec['beat_ids']))),)
                elif diagram and diagram.kind == 'dots':
                    span.source_proof = True
        span.diagrams = tuple(sorted(span.diagrams, key=lambda d: d.window[0]))
        for previous, following in zip(span.diagrams, span.diagrams[1:]):
            previous.speech_end = min(previous.speech_end, following.window[0])
        span.diagram = span.diagrams[0] if span.diagrams else None
        if treatment == 'whiteboard' or span.source_proof:
            return
        span.source_character = bool(span.actors) and not span.diagram and treatment in ('character', 'atmosphere')
        if span.atmos is None and not span.diagram and self.style['motion_floor'] != 'still':
            span.atmos = Atmosphere('dust', {'background': self.style['palette']['background'],
                'accent': self.style['palette']['accent2']}, .8, seed(spec['beat_ids']))
        if treatment == 'character' and not span.actors:
            self.warnings.append('hybrid: character scene without cast uses source whiteboard fallback')
        p = self.style['palette']
        elements = []
        refs = [e['ref'] for e in spec['elements'] if e['kind'] == 'picture']
        if not refs and not span.actors and not span.diagram and treatment in ('motion', 'kinetic_type'):
            # A scene the plan left without pictures draws its sentences' own items (the picture director's
            # draft for its beats), so the narration never plays over an empty stage.
            refs = list(dict.fromkeys(item['doodle'] for bid in spec['beat_ids'] for v in self.by_id[bid]['visuals']
                                      if v.get('type') == 'cluster' for item in v.get('items', [])
                                      if item.get('doodle')))[:3]
        for ref in refs:
            e = {'kind': 'picture', 'ref': ref}
            if not span.diagram:
                try:
                    path = library.resolve(e['ref'], Path(project_dir))
                    # Library doodles keep their own colours; recolouring every fill made one-colour blobs.
                    elements.append(MotionElement(kind='picture', svg=path.read_text(encoding='utf-8'), width=600, height=450,
                                                  preserve_svg_palette=True,
                                                  start=0. if span.actors else self._picture_cue(span, e['ref'])))
                except (OSError, KeyError, ValueError, AttributeError):
                    self.warnings.append(f"hybrid: missing prop {e['ref']}; unavailable picture omitted")
        text_kind, ref = spec['text']['kind'], spec['text']['ref']
        source = self.by_id.get(ref)
        numeric_chart = treatment == 'chart' and any(v.get('type') in ('bars', 'line', 'stat', 'grid100')
            for bid in spec['beat_ids'] for v in self.by_id[bid]['visuals'])
        if text_kind == 'quote':
            quotes = [v for v in source['visuals'] if v.get('type') == 'quote'] if source else []
            value = quotes[0] if quotes else {}
            body = self._label(value.get('text')) or (self._shown(ref)[0] if source else text)
            who = self._label(value.get('who'))
            atomic = '“' + body.strip().strip('"“”').strip() + '”'      # the script's own quote marks, once
            if not span.source_character:
                atomic = '\n'.join(caption_wrap(atomic, 48))
            atomic += '\n— ' + who if who else ''
            elements.append(MotionElement(text=atomic, preset='corner_caption', width=1450, size=64))
            if source and body == self._shown(ref)[0]:
                span.on_screen += (ref,)
            if span.source_character and source:
                elements[-1].start = self._source_text_start(span, source, body)
                elements[-1]._quote_source = (source, body)
        for e in spec['elements']:
            # A text element never writes out the narration the caption is already showing: in a scene whose own
            # words are only captioned (caption_only, none, quote), the beats it narrates draw no second copy. A
            # character scene's source text is laid out beside the cast instead, and the caption gives way to it.
            said_here = e['ref'] in spec['beat_ids'] and text_kind in ('none', 'caption_only', 'quote') \
                and not span.source_character
            if not span.diagram and not numeric_chart and e['kind'] == 'text' and e['ref'] in self.by_id and \
                    (e['ref'] != ref or text_kind in ('none', 'caption_only')) and not said_here and \
                    self._shown(e['ref'])[0].strip():
                elements.append(MotionElement(text=self._shown(e['ref'])[0], width=1450, size=72,
                                              preset='type_on' if treatment == 'kinetic_type' else 'word_pop'))
                elements[-1]._ref = e['ref']
                span.on_screen += (e['ref'],)
                if span.source_character:
                    elements[-1].start = self._source_text_start(span, self.by_id[e['ref']])
                else:
                    self._clause_build(span, elements[-1], e['ref'])
        if not span.diagram and not numeric_chart and text_kind not in ('none', 'caption_only', 'quote'):
            words = self._shown(ref)[0] if source else text
            elements.append(MotionElement(text=words, preset='counter' if text_kind == 'counter' else
                'type_on' if treatment == 'kinetic_type' else 'word_pop', width=1500, size=72,
                y=.25 if elements and spec['composition'] not in ('grid', 'split') else None))
            if text_kind != 'counter' and source and not span.source_character:
                self._clause_build(span, elements[-1], ref)
            if text_kind != 'counter' and source:
                span.on_screen += (ref,)
            if text_kind == 'counter':
                proof = arc.proof_number(words)
                if proof:
                    counter = elements[-1]
                    counter.value_from, counter.value_to = proof['from'], proof['to']
                    counter.prefix, counter.suffix, counter.decimals = proof['prefix'], proof['suffix'], proof['decimals']
                    counter.duration = min(1.8, max(.1, duration - .4))
                    if source and not span.source_character:
                        self._proof_counter(span, elements, source, proof)
                else:
                    self.warnings.append('hybrid: counter without numeric data uses readable source text')
                    elements[-1].preset = 'type_on'
            elif text_kind == 'cta' and source and not span.source_character:
                self._call_to_action(span, elements, source)
        if treatment == 'chart':
            from ..scientific import ScientificPlot
            span.scientific = tuple(ScientificPlot(v['plot']) for bid in spec['beat_ids']
                                    for v in self.by_id[bid]['visuals'] if v.get('type') == 'scientific')
            if span.scientific:
                if len(span.scientific) > 4:
                    raise ValueError('split scientific scenes with more than four plots into separate beats')
                # Scientific frames own their exact-black canvas and fixed axis mapping.
                span.atmos = None
                span.actors = ()
                return
            for bid in spec['beat_ids']:
                for visual in self.by_id[bid]['visuals']:
                    if visual.get('type') in ('bars', 'line'):
                        rows = visual['rows']
                        unit = self._label(visual.get('unit'))
                        elements.append(MotionElement(kind='chart', chart='line' if visual['type'] == 'line' else 'bar', values=tuple(r['value'] for r in rows),
                            labels=tuple(r.get('label', {}).get(self.lang, '') if isinstance(r.get('label'), dict)
                                         else r.get('label', '') for r in rows),
                            suffix=('' if unit == '%' else ' ') + unit if unit else '', width=1150, height=450))
                    elif visual.get('type') == 'stat':
                        value = self._label(visual['value'])
                        label = self._label(visual.get('label'))
                        elements.append(MotionElement(text=value + '\n' + label, preset='corner_caption', width=1100, size=100))
                    elif visual.get('type') == 'grid100':
                        filled = int(visual['filled'])
                        cells = ''.join(f'<rect x="{(i % 10) * 44}" y="{(i // 10) * 44}" width="36" height="36" opacity="{1 if i < filled else .15}"/>' for i in range(100))
                        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 440">{cells}</svg>'
                        elements.append(MotionElement(kind='picture', svg=svg, width=520, height=520))
                        elements.append(MotionElement(text=self._label(visual.get('title')), preset='corner_caption', y=.15, width=1400, size=60))
                    elif visual.get('type') != 'cluster' or not numeric_chart:
                        span.source_chart = True
                        self.warnings.append(f"hybrid: chart visual {visual.get('type')} requires source whiteboard cutaway")
            if not elements:
                self.warnings.append('hybrid: chart without supported graphics uses source whiteboard facts over motion backdrop')
        if not span.actors and not span.diagram and not numeric_chart and treatment in ('motion', 'kinetic_type'):
            self._first_picture_on_time(span, elements)
            pictures = [e for e in elements if e.kind == 'picture']
            copy_elements = [e for e in elements if e.kind == 'text' and e.preset not in ('corner_caption', 'counter')]
            # Source copy remains verbatim, but line breaks give kinetic headlines
            # enough ink to read and move; a prop gets its own space below the copy.
            for e in copy_elements:
                e.text = '\n'.join(caption_wrap(e.text, 36))
                e.size = 96
            if pictures and copy_elements and spec['composition'] not in ('grid', 'split') and not span.stacked:
                for e in copy_elements:
                    e.y, e.width = .23, 1400
                for e in pictures:
                    e.y = .60
            if len(pictures) > 1 and spec['composition'] not in ('grid', 'split') and not span.stacked:
                # A stable frame: one fixed slot per picture, left to right in spoken order, so a picture that
                # arrives with a later clause never covers or shifts the ones already on the board.
                pictures.sort(key=lambda e: e.start)
                step = min(.3, .84 / len(pictures))
                for k, e in enumerate(pictures):
                    e.x = .5 + (k - (len(pictures) - 1) / 2) * step
                    e.width, e.height = min(e.width, 1920 * step * .85), min(e.height, 1080 * .4)
                order = iter(pictures)
                elements[:] = [next(order) if e.kind == 'picture' else e for e in elements]
            for e in copy_elements:
                # The whole copy stays inside the frame, through its drift and entrance rise, and above the
                # pictures under it (or above the captions): a long headline gets smaller, never clipped.
                top = 84 * .7 + 18 + .05 * 1080
                under = [q.y * 1080 - q.height / 2 for q in pictures if q.y is not None and e.y is not None
                         and q.y > e.y]
                bottom = min(under) - 24 if under else 1080 * .80
                height = (e.text.count('\n') + 1) * e.size * 1.15
                if height > bottom - top:
                    e.size *= (bottom - top) / height
                    height = bottom - top
                centre = (e.y if e.y is not None else .5) * 1080
                e.y = min(max(centre, top + height / 2), bottom - height / 2) / 1080
        camera = 'static'  # Camera is applied to the whole composed scene, including creatures/atmospheres.
        transition = spec['transition_in']
        # A full-bleed scene is laid out like a centred one: a library picture is an object, never the whole frame,
        # so a truck or a skyline never balloons over the page (J 10/8: no random zooms).
        span.motion = MotionScene(elements, duration=max(.01, duration), composition='center' if
            spec['composition'] in ('stage', 'full_bleed') else spec['composition'], camera=camera,
            transition_in=transition,
            palette=Palette(p['background'], p['ink'], p['accent']), energy=self.style['energy'],
            motion_floor={'still': 0, 'breathing': .4, 'drifting': .7, 'lively': 1}[self.style['motion_floor']],
            hold=min(1.1, max(.5, spec['hold_s'])), seed=seed(spec['beat_ids']), blur_samples=1,
            foreground_drift=84. if treatment == 'kinetic_type' else 48., continuous_drift=True)
        for element in elements:
            element.font = self.style['type']
        if span.source_character:
            self._layout_character(span)
            span.motion_art = copy.copy(span.motion)
            span.motion_art.elements = [e for e in elements if e.kind != 'text']
        elif numeric_chart and spec['composition'] in ('grid', 'split') and len([
                v for bid in spec['beat_ids'] for v in self.by_id[bid]['visuals']
                if v.get('type') in ('bars', 'line', 'stat', 'grid100')]) == 1 and not any(
                v.get('type') == 'grid100' for bid in spec['beat_ids'] for v in self.by_id[bid]['visuals']):
            # Give measured facts the main panel; source pictures support them.
            pictures = [e for e in elements if e.kind == 'picture']
            for i, element in enumerate(pictures):
                element.x, element.y = .16, .2 + (i + .5) * .45 / max(1, len(pictures))
                element.width, element.height = min(element.width, 340), min(element.height, 260)
            for element in elements:
                if element not in pictures:
                    element.x, element.y = .64, .42
                    element.width = min(element.width, 1050)
                    element.height = min(element.height, 430)
        elif span.stacked:
            # Headline over the number or the button, as in the reference launch; pictures keep to the sides.
            for k, element in enumerate(e for e in elements if e.kind == 'picture'):
                element.x, element.y = (.13, .62) if k % 2 == 0 else (.87, .62)
                element.width, element.height = min(element.width, 330), min(element.height, 300)
        elif spec['composition'] in ('grid', 'split'):
            cols = 2 if spec['composition'] == 'split' else math.ceil(math.sqrt(max(1, len(elements) + len(self._cast_groups(span)))))
            rows = math.ceil(max(1, len(elements) + len(self._cast_groups(span))) / cols)
            for i, element in enumerate(elements):
                element.x, element.y = (i % cols + .5) / cols, (i // cols + .5) / rows
                element.width = min(element.width, 1920 / cols * .8)
                element.height = min(element.height, 1080 / rows * .65)

    def _spoken_at(self, bid, char):
        timing = self.tl['beats'][bid]
        ct = timing['char_times']
        return timing['start'] + (ct[min(char, len(ct) - 1)] if ct else 0.)

    def _shown(self, bid):
        """A beat's written text as the picture draws it (speech.shown: no speaker labels, stage directions or
        emoji; a line of on-screen-text directions shows their words) and the offset in the written text of each
        of its characters, which times it from the spoken text."""
        if bid not in self._shown_text:
            from .. import speech
            self._shown_text[bid] = speech.shown(self.by_id[bid]['text'], self.labels)
        return self._shown_text[bid]

    def _shown_offset(self, bid, pos):
        """The spoken-text offset of character ``pos`` of a beat's shown text."""
        index = self._shown(bid)[1]
        return self._spoken_offset(bid, index[min(pos, len(index) - 1)] if index else 0)

    def _spoken_offset(self, bid, pos):
        """The spoken-text offset of character ``pos`` of a beat's written text: exact where the spoken text is the
        written text's own reading (numbers.normalize), else clause by clause."""
        from ..numbers import normalize
        display, spoken = self.by_id[bid]['text'], self.by_id[bid]['spoken']
        reading = normalize(display, self.lang)
        if reading.spoken == spoken:
            return min(reading.to_spoken(pos), max(0, len(spoken) - 1))
        return arc.spoken_offset(display, spoken, pos)

    def _clause_build(self, span, element, bid):
        """Reveal displayed source text clause by clause, each clause at the time the narration starts it."""
        shown = self._shown(bid)[0]
        cues = []
        for a, b in arc.clauses(shown):
            first = a + len(shown[a:b]) - len(shown[a:b].lstrip())
            cues.append(max(0., self._spoken_at(bid, self._shown_offset(bid, first)) - span.start))
        element.preset, element.cues = 'clauses', tuple(cues) or (0.,)
        element.start = element.cues[0]

    def _on_beat(self, at, low, high, latest):
        """The first music beat between ``at + low`` and ``at + high`` (absolute seconds, never after ``latest``),
        else a fixed delay inside that window: state changes land on the music where the narration allows."""
        late = min(at + high, latest)
        hits = [float(b) for b in self.score_beats if at + low <= b <= late]
        return hits[0] if hits else max(at + min(low, .3), min(at + (low + high) / 2, latest))

    def _proof_counter(self, span, elements, source, proof):
        """Hovercast's proof beat: the source sentence over its number, which rolls up with an ease-out from the
        moment the number is spoken and lands on a music beat with a pulse and a burst of ticks."""
        counter = elements[-1]
        display = self._shown(source['id'])[0]
        at = max(0., self._spoken_at(source['id'], self._shown_offset(source['id'], proof['start'])) - span.start)
        landing = self._on_beat(span.start + at, .8, 1.5, span.end - .4)
        counter.start, counter.duration = at, max(.3, landing - span.start - at)
        counter.ease, counter.hit = 'cubic_out', True
        counter.x, counter.y, counter.size, counter.width = .5, .62, 200, 1500
        headline = MotionElement(text='\n'.join(caption_wrap(display, 40)), width=1500,
                                 size=80, x=.5, y=.27)
        self._clause_build(span, headline, source['id'])
        elements.insert(len(elements) - 1, headline)
        span.stacked = True

    def _call_to_action(self, span, elements, source):
        """Hovercast's ask: the words before it as the headline, its imperative as a button pressed on a beat."""
        display = self._shown(source['id'])[0]
        hit = arc.cta_phrase(display)
        if hit is None:
            return
        a, b = hit
        at = max(0., self._spoken_at(source['id'], self._shown_offset(source['id'], a)) - span.start)
        press = self._on_beat(span.start + at, .45, 1.3, span.end - .5) - span.start
        headline = elements[-1]
        if display[:a].strip():
            headline.text = display[:a].strip()
            headline.x, headline.y = .5, .32
        else:
            elements.remove(headline)
        elements.append(MotionElement(kind='button', text=display[a:b], size=60, x=.5, y=.64, start=at,
                                      cues=(press,)))
        span.stacked = True

    def _picture_cue(self, span, ref):
        """Local time the narration names a picture: its source trigger or label, else a word of its own name."""
        names = [[], []]
        for bid in span.spec['beat_ids']:
            for visual in self.by_id[bid]['visuals']:
                for item in visual.get('items', []) if visual.get('type') == 'cluster' else []:
                    if item.get('doodle') == ref:
                        names[0] += [(bid, self._label(item.get('trigger'))), (bid, self._label(item.get('label')))]
            names[1] += [(bid, word) for word in re.split(r'[_\-\s]+', ref) if len(word) > 2]
        for bid, word in names[0] + names[1]:
            hit = word and re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', self.by_id[bid]['spoken'], re.I)
            if hit:
                return max(0., min(self._spoken_at(bid, hit.start()) - span.start, span.end - span.start - 1.))
        return 0.

    EMPTY_STAGE = 1.0     # seconds of narration over an empty stage before a scene's first picture is brought in

    def _first_picture_on_time(self, span, elements):
        """A motion scene whose pictures are all named late in its narration would leave the stage empty while
        the first sentences play (only the caption on blank paper): its first picture is on stage from the scene
        start instead. A scene that shows something within EMPTY_STAGE seconds is left as planned."""
        pictures = [e for e in elements if e.kind == 'picture']
        shown = [e.start for e in elements if e.kind != 'picture' and e.text.strip()] + [e.start for e in pictures]
        if not pictures or min(shown) <= self.EMPTY_STAGE:
            return
        first = min(pictures, key=lambda e: e.start)
        self.warnings.append(f"hybrid: {'/'.join(span.spec['beat_ids'])} first picture brought in at the scene "
                             f'start (named {first.start:.1f}s in)')
        first.start = 0.

    def _reflow_square(self, span):
        """Reflow logical element boxes before their SVGs are rasterized.

        The renderer positions centers as stage fractions, but native square
        sprites keep uniform pixel scale (letters and circles never stretch).
        """
        if span.source_character:
            return
        elements = span.motion.elements
        groups = self._cast_groups(span)
        if span.spec['composition'] in ('grid', 'split'):
            total = max(1, len(elements) + len(groups))
            cols = 1 if span.spec['composition'] == 'split' else math.ceil(math.sqrt(total))
            rows = math.ceil(total / cols)
            for i, e in enumerate(elements):
                e.x, e.y = (i % cols + .5) / cols, .08 + (i // cols + .5) * .68 / rows
                e.width = min(e.width, 1080 / cols * .78)
                e.height = min(e.height, 1080 * .58 / rows)
        else:
            for e in elements:
                e.width = min(e.width, 840)
                e.height = min(e.height, 570)
                # Reserve the lower band for narration captions.
                if e.y is None:
                    e.y = .37 if span.actors else .43
        for e in elements:
            if e.kind == 'text':
                # Existing text presets and font choice remain source controlled.
                e.size = min(e.size, 64)

    def _label(self, value):
        return str(value.get(self.lang, next(iter(value.values()), ''))) if isinstance(value, dict) else str(value or '')

    @staticmethod
    def _positive_clause(text, start, end):
        """Polarity belongs to the owned clause, including inversion and suffixes."""
        boundary = r'[,;.!?\n]|\b(?:but|while|whereas|when|because)\b'
        before = list(re.finditer(boundary, text[:start], re.I))
        after = re.search(boundary, text[end:], re.I)
        clause = text[before[-1].end() if before else 0:end + after.start() if after else len(text)]
        return not (NEGATED_ACTION.search(clause) or re.search(
            r'\b(?:under|in)\s+no\s+circumstances\b|\bat\s+no\s+time\b|\bin\s+no\s+way\b', clause, re.I))

    def _source_reactions(self, span, events):
        """A positive owned roar can rattle the explicit recipient's mouth."""
        for spec in span.spec['actions']:
            actor, bid = spec['actor'], spec['at_beat']
            if spec['verb'] != 'roar' or actor not in self.cast:
                continue
            beat, timing = self.by_id[bid], self.tl['beats'][bid]
            char = self._source_action_char(beat, actor, 'roar')
            if char is None:
                continue
            ct = timing['char_times']
            at = timing['start'] + (ct[min(char, len(ct) - 1)] if ct else 0)
            if not any(owner == actor and a.name == 'roar' and a.start == at - span.start
                       for owner, a, _ in events):
                continue
            tail = re.split(r'[.!?;\n]', beat['spoken'][char:], maxsplit=1)[0]
            for recipient, genome in self.cast.items():
                name = re.escape(name_key(genome.name))
                hit = re.match(r"roar\w*\s+(?:so\s+(?:\w+\s+){1,4}it\s+|(?:that|which)\s+)?"
                               r"(?:did\s+)?(?:not\s+|never\s+)?(rattl\w*)\s+(?:King\s+|Queen\s+)?" +
                               name + r"['’]s\s+teeth\b", tail, re.I)
                if not hit or not self._positive_clause(beat['spoken'], char, char + hit.end()):
                    continue
                offset = char + hit.start(1)
                reaction_at = timing['start'] + (ct[min(offset, len(ct) - 1)] if ct else 0)
                remaining = min(timing['speech_end'], span.end) - reaction_at
                if remaining <= 0 or any(owner == recipient and a.name == 'teeth_chatter' for owner, a, _ in events):
                    continue
                if recipient not in span.actors:
                    span.actors += (recipient,)
                events.append((recipient, Action('teeth_chatter', reaction_at - span.start,
                                                 min(remaining, Action('teeth_chatter').seconds)), None))

    def _group_actions(self, span, events):
        """Give source-owned plural representatives the actions spoken about them."""
        hyenas = [key for key in span.actors if self.cast[key].species == 'hyena']
        if not hyenas:
            return
        for bid in span.spec['beat_ids']:
            beat, timing = self.by_id[bid], self.tl['beats'][bid]
            for verb, pattern in (
                ('laugh', r'\bhyenas?\s+(?:not\s+only\s+)?(?:were\s+|began\s+|started\s+)?(laugh\w*|cackl\w*)\b|\b(Laughing)\.\s+A\s+cackle\s+of\s+(?:spotted\s+)?hyenas\b'),
                ('bare_teeth', r'\bhyenas?\s+(?:not\s+only\s+)?(?:drew\s+closer,\s*)?(baring|bared|bare)\s+(?:their\s+)?(?:sharp\s+)?teeth\b'),
                ('walk', r'\bhyenas?\s+(?:not\s+only\s+)?(drew\s+closer|approach\w*|emerged)\b'),
                ('run', r'\bhyenas?\s+(?:not\s+only\s+)?(scattered|fled)\b'),
            ):
                hit = next((h for h in re.finditer(pattern, beat['spoken'], re.I)
                            if self._positive_clause(beat['spoken'], h.start(), h.end())), None)
                if not hit:
                    continue
                char = hit.start(1) if hit[1] is not None else hit.start(2)
                ct = timing['char_times']
                at = timing['start'] + (ct[min(char, len(ct) - 1)] if ct else 0)
                remaining = max(.1, min(timing['speech_end'], span.end) - at)
                target = None
                if verb == 'walk':
                    source = list(self.by_id.values())
                    index = next(i for i, b in enumerate(source) if b['id'] == bid)
                    previous = source[index - 1] if index else None
                    threat = beat['spoken']
                    if previous and previous['section'] == beat['section']:
                        threat = previous['spoken'] + '\n' + threat
                    # Continued approach inherits the explicitly threatened cub
                    # from the immediately preceding source, not all cast mentions.
                    if re.search(r'\b(?:unprotected\s+)?cubs?\b', threat, re.I):
                        children = [key for key, g in self.cast.items()
                                    if g.age == 'baby' and mentions(g.name, threat)]
                        if len(children) == 1:
                            target = children[0]
                            if target not in span.actors:
                                span.actors += (target,)
                for key in hyenas:
                    if not any(actor == key and a.name == verb for actor, a, _ in events):
                        events.append((key, Action(verb, at - span.start,
                                                  min(remaining, Action(verb).seconds)), target))

    def _swipe_target(self, beat, actor, char, actors):
        # Targets belong to the swipe's clause, never a later roar or bystander.
        tail = re.split(r'[.!?;\n]', beat['spoken'][char:], maxsplit=1)[0]
        obj = re.search(r'^(?:swip\w*\s+(?:at\s+)?)|\b(?:sent|sending|struck|hit)\s+', tail, re.I)
        if not obj:
            return None
        phrase = tail[obj.end():]
        if tail[:obj.end()].lower().strip().endswith(('swipe', 'swiped')) and re.match(r'of\b', phrase, re.I):
            sent = re.search(r'\b(?:sent|sending|struck|hit)\s+', phrase, re.I)
            if not sent:
                return None
            phrase = phrase[sent.end():]
        phrase = re.split(r'\b(?:with|while|whereas|but)\b|,', phrase, maxsplit=1, flags=re.I)[0]
        named = [key for key in self.cast if key != actor and re.match(
            r'(?:the\s+)?(?:King\s+|Queen\s+)?' + re.escape(name_key(self.cast[key].name)) + r'(?!\w)', phrase, re.I)]
        if named:
            rest = re.split(r'\b(?:with|into|away|flying)\b', phrase, maxsplit=1, flags=re.I)[0]
            competing = [key for key in self.cast if key != actor and mentions(self.cast[key].name, rest)]
            return named[0] if competing == named else None
        if re.match(r'(?:the\s+)?(?:lead\s+)?hyena\b', phrase, re.I):
            candidates = [key for key in actors if self.cast[key].species == 'hyena']
            if len(candidates) == 1 or re.match(r'(?:the\s+)?lead\s+hyena\b', phrase, re.I):
                return next(iter(candidates), None)
        return None

    def _parent_target(self, beat, actor, relation):
        child = re.escape(name_key(self.cast[actor].name))
        parents = set()
        for source in self.by_id.values():
            if source['section'] == beat['section']:
                for key, g in self.cast.items():
                    if key == actor or g.age == 'baby':
                        continue
                    parent = re.escape(name_key(g.name))
                    pattern = (r'(?<!\w)' + child + r'(?!\w)[^.!?;\n]{0,140}\b(?:his|her|their)\s+' +
                               relation + r'\s*,?\s*(?:the\s+)?(?:great\s+)?(?:king\s+)?' + parent + r'(?!\w)')
                    if re.search(pattern, source['spoken'], re.I):
                        parents.add(key)
            if source['id'] == beat['id']:
                break
        return next(iter(parents)) if len(parents) == 1 else None

    def _hide_target(self, beat, actor, char):
        tail = re.split(r'[.!?;\n]', beat['spoken'][char:], maxsplit=1)[0]
        hit = re.match(r'hid(?:e|es|ing)?\s+behind\s+(.+)', tail, re.I)
        if not hit:
            return None
        phrase = hit[1]
        named = [key for key, g in self.cast.items() if key != actor and mentions(g.name, phrase)]
        if named:
            return named[0] if len(named) == 1 else None
        relation = re.match(r"(?:his|her|their)\s+(mother|father)['’]s\s+paws\b", phrase, re.I)
        return self._parent_target(beat, actor, relation[1]) if relation else None

    def _source_action_char(self, beat, actor, verb):
        """Use a named subject or its unambiguous singular pronoun at the spoken cue.

        The immediately previous beat may establish the subject of a continued
        sentence sequence. Objects and possessive body descriptions do not take
        ownership of the next action.
        """
        direct = action_char(beat['spoken'], actor, verb, self.cast)
        if direct is not None:
            return direct
        if verb == 'tremble':
            implied = action_char(beat['spoken'], actor, verb, self.cast,
                                  r'heart\s+hammered|shrank\s+back')
            if implied is not None:
                return implied
        pattern = ACTION_CUES.get(verb, r'(?!)')
        if verb == 'sleep':
            pattern += r'|asleep'
            # "asleep" is a state predicate, not the nearest named object's cue.
            name = re.escape(name_key(self.cast[actor].name))
            for state in re.finditer(r'(?<!\w)' + name + r'(?!\w)\s+(?:was|is|lay|fell)\s+(?:fast\s+)?(asleep)\b', beat['spoken'], re.I):
                return state.start(1)
        cue = r'\b(?:' + pattern + r')\b'
        source = list(self.by_id.values())
        index = next(i for i, b in enumerate(source) if b['id'] == beat['id'])
        previous = source[index - 1]['spoken'] if index and source[index - 1]['section'] == beat['section'] else ''
        text = previous + '\n' + beat['spoken']
        offset = len(previous) + 1
        owner = None
        referents = []
        for sentence in re.finditer(r'[^.!?;\n]+', text):
            body = sentence.group()
            named = []
            for key, genome in self.cast.items():
                name = re.escape(name_key(genome.name))
                # A name followed by a predicate is a subject; "over Pendo"
                # and "nudged Pendo with his nose" remain objects.
                if re.search(r'(?<!\w)' + name + r"(?!\w)(?:['’]s\s+(?:heart|body|head))?\s+(?:was|is|had|has|would|stood|lowered|burst|shrank|tried|returned|hammered|curl\w*|rest\w*|sleep\w*|slept|watch\w*|walk\w*|run\w*|ran|nudg\w*|roar\w*)\b", body, re.I):
                    named.append(key)
            pronoun = re.search(r'\b(he|she|his|her)\b', body, re.I)
            current = [key for key, genome in self.cast.items() if mentions(genome.name, body)]
            if len(named) == 1:
                owner = named[0]
            elif len(named) > 1 or re.search(r'\b(they|their)\b', body, re.I):
                owner = None
            elif not pronoun:
                owner = None
            if named or not pronoun:
                referents = current
            if owner != actor or not pronoun:
                continue
            sex = 'female' if pronoun[1].lower() in ('she', 'her') else 'male'
            compatible = [key for key in referents if self.cast[key].sex in ('unknown', sex)]
            if self.cast[actor].sex not in ('unknown', sex) or compatible != [actor]:
                owner = None
                continue
            for hit in re.finditer(cue, body, re.I):
                absolute = sentence.start() + hit.start()
                prefix = re.split(r'[,;]|\bbut\b', body[:hit.start()], flags=re.I)[-1]
                if absolute >= offset and not NEGATED_ACTION.search(prefix):
                    return absolute - offset
        return None

    def _nudge_char(self, text, actor, direct):
        """A pronoun cue needs one named subject in the immediately preceding sentence."""
        cue = r'\b(?:' + ACTION_CUES['nudge'] + r')\b'
        if re.match(cue, text[direct:], re.I):
            return direct
        pronoun = {'female': 'she', 'male': 'he'}.get(self.cast[actor].sex)
        if not pronoun:
            return None
        for hit in re.finditer(cue, text, re.I):
            sentences = re.split(r'[.!?;\n]', text[:hit.start()])
            current = sentences[-1]
            if len(sentences) < 2 or not re.match(r'^\s*' + pronoun + r'\b', current, re.I):
                continue
            if NEGATED_ACTION.search(current) or re.search(r'\b(?:but|while|whereas|when)\b', current, re.I):
                continue
            previous = sentences[-2]
            owners = [key for key, g in self.cast.items() if mentions(g.name, previous)]
            if owners == [actor]:
                return hit.start()
        return None

    def _nudge_target(self, beat, actor, char):
        tail = re.split(r'[.!?;\n]|\bwith\b', beat['spoken'][char:], maxsplit=1, flags=re.I)[0]
        named = [key for key, g in self.cast.items() if key != actor and mentions(g.name, tail)]
        if named:
            return named[0] if len(named) == 1 else None
        if not re.match(r'nudg\w*\s+(?:his|her)\s+cub\b', tail, re.I):
            return None
        # Genome age is not parentage. Require an explicit, actor-owned relation,
        # already spoken in this section; never use proximity or copy another genome.
        relation = 'mother' if re.search(r'\bher\s+cub\b', tail, re.I) else 'father'
        parent = re.escape(name_key(self.cast[actor].name))
        children = set()
        for source in self.by_id.values():
            if source['section'] != beat['section']:
                continue
            for key, g in self.cast.items():
                if key == actor or g.age != 'baby':
                    continue
                child = re.escape(name_key(g.name))
                pattern = (r'(?<!\w)' + child + r'(?!\w)[^.!?;\n]{0,140}\b(?:his|her|their)\s+' +
                           relation + r'\s*,?\s*' + parent + r'(?!\w)')
                possessive = (r'(?<!\w)' + parent + r"['’]s\s+cub\s*,?\s*" + child + r'(?!\w)')
                if re.search(pattern, source['spoken'], re.I) or re.search(possessive, source['spoken'], re.I):
                    children.add(key)
            if source['id'] == beat['id']:
                break
        return next(iter(children)) if len(children) == 1 else None

    def _source_text_start(self, span, source, text=None):
        timing = self.tl['beats'][source['id']]
        char = source['spoken'].find(text) if text else 0
        if char < 0:
            # Unmatched display quotes must not precede their narration beat.
            return timing['speech_end'] - span.start
        ct = timing['char_times']
        return timing['start'] - span.start + (ct[min(char, len(ct) - 1)] if ct else 0)

    def _sleep_contact(self, beat, actor):
        """Only explicit curled-against wording supports a resting contact pair."""
        name = re.escape(name_key(self.cast[actor].name))
        hit = re.search(r'(?<!\w)' + name + r'(?!\w)\s+(?:was\s+)?(curled\s+up)\s+'
                        r'(?:tightly\s+)?against\s+([^.!?;\n]+)', beat['spoken'], re.I)
        if not hit:
            return None
        tail = hit[2]
        # Curling alone is not sleep. Require the subject's explicit asleep
        # modifier, rather than a negated state or the receiver's later verb.
        asleep = re.search(r',\s*(?:fast\s+)?asleep\b', tail, re.I)
        if not asleep:
            return None
        tail = tail[:asleep.start()]
        if re.search(r"\b(?:not|never|cannot|while|whereas|when|but|was|is|fell|slept|sleep\w*)\b|\b\w+n['’]t\b", tail, re.I):
            return None
        named = [key for key, g in self.cast.items() if key != actor and g.age != 'baby' and mentions(g.name, tail)]
        if len(named) == 1:
            return hit.start(1), named[0]
        if named:
            return None
        relation = re.match(r"(?:his|her|their)\s+(father|mother)['’]s\b", tail, re.I)
        if not relation:
            return None
        parents = set()
        for source in self.by_id.values():
            if source['section'] == beat['section']:
                for key, g in self.cast.items():
                    if key == actor or g.age == 'baby':
                        continue
                    parent = re.escape(name_key(g.name))
                    pattern = (r'(?<!\w)' + name + r'(?!\w)[^.!?;\n]{0,140}\b(?:his|her|their)\s+' +
                               relation[1] + r'\s*,?\s*(?:the\s+)?(?:great\s+)?(?:king\s+)?' + parent + r'(?!\w)')
                    if re.search(pattern, source['spoken'], re.I):
                        parents.add(key)
            if source['id'] == beat['id']:
                break
        return (hit.start(1), next(iter(parents))) if len(parents) == 1 else None

    def _layout_character(self, span):
        """Reserve a cast stage independently of the number/length of source labels."""
        from .bold.render import _text_metrics
        from .creatures.actions import Pose
        from .creatures.rig import build
        groups = self._cast_groups(span)
        panel = not self.square and len(groups) == 1
        left_actor = span.spec['composition'] == 'left_third'
        text_x = .71 if panel and left_actor else .245 if panel else .5
        width = 730 if panel else 880 if self.square else 1640
        top, bottom = (.14, .65) if panel else (.08, .34)
        elements = span.motion.elements
        paged = []
        for i, e in enumerate(elements):
            e.x, e.y = text_x, top + (i + .5) * (bottom - top) / max(1, len(elements))
            e.width, e.height = width, 1080 * (bottom - top) / max(1, len(elements)) - 30
            if e.kind != 'text':
                paged.append(e)
                continue
            quote = e.preset == 'corner_caption'
            whole = e.text
            e.size = 48
            if not quote:
                # A label is a verbatim source excerpt; narration and timed captions
                # retain every word. Do not let a paragraph consume the cast stage.
                sentence = re.split(r'(?<=[.!?])\s+', e.text.strip(), maxsplit=1)[0]
                whole = e.text.strip()
                e.text = sentence
                e.preset = 'type_on'
            wrapped, _, size, _ = _text_metrics(e.text, e.size, e.width, True, e.font)
            rows = max(1, int(e.height / (size * 1.15)))
            if quote and len(wrapped.splitlines()) > rows:
                # Every card appears atomically, at its own words inside the complete
                # dialogue. Keep a readable font and page inside the safe cast panel.
                e.height = 1080 * (bottom - top) - 30
                e.y = (top + bottom) / 2
                rows = max(1, int(e.height / (size * 1.15)))
                lines = wrapped.splitlines()
                source, body = e._quote_source
                spoken_offset = source['spoken'].find(body)
                positions = [j for j, ch in enumerate(body) if not ch.isspace()]
                consumed = 0
                cards = []
                for j in range(0, len(lines), rows):
                    card = copy.copy(e)
                    card.text = '\n'.join(lines[j:j + rows])
                    if spoken_offset >= 0 and positions:
                        char = spoken_offset + positions[min(consumed, len(positions) - 1)]
                        timing = self.tl['beats'][source['id']]
                        ct = timing['char_times']
                        card.start = timing['start'] - span.start + (ct[min(char, len(ct) - 1)] if ct else 0)
                    else:
                        card.start = e.start + j / max(1, len(lines)) * max(0, span.end - span.start - e.start)
                    consumed += len(re.sub(r'\s|[“”]', '', card.text))
                    cards.append(card)
                for card, following in zip(cards, cards[1:]):
                    card.end = following.start
                cards[-1].end = span.end - span.start
                paged.extend(cards)
                continue
            if not quote and (len(wrapped.splitlines()) > rows or e.text != whole):
                # A label shows whole clauses only, never a stub cut before its number or unit ("Flip gently, and
                # cook 1"): the longest run of clauses that fits, else no label. Either way the caption carries
                # the beat's words, since the label no longer shows them all.
                span.on_screen = tuple(b for b in span.on_screen if b != getattr(e, '_ref', None))
                cuts = [m.end() for m in re.finditer(r'[,;:.!?](?=\s|$)', e.text)]
                fit = next((c for c in reversed(cuts) if len(_text_metrics(
                    e.text[:c].rstrip(',;:'), e.size, e.width, True, e.font)[0].splitlines()) <= rows), None)
                if fit is None:
                    continue
                e.text = e.text[:fit].rstrip(',;:')
                wrapped = _text_metrics(e.text, e.size, e.width, True, e.font)[0]
            e.text = wrapped
            paged.append(e)
        span.motion.elements = paged
        # Measure stable resting silhouettes once. One scale per interaction group
        # preserves baby/adult size differences and leaves room for action/life poses.
        main = list(span.actors)
        bounds = {key: raster(self.cast[key], 'idle', 0., height=400).getchannel('A').getbbox() for key in main}
        stage_left, stage_right = ((.04, .50) if left_actor else (.50, .96)) if panel else (.075, .925)
        stage_top, ground = (.12, .73) if panel else (.39, .74)
        stage_w = self.size[0] * (stage_right - stage_left)
        stage_h = self.size[1] * (ground - stage_top)
        span.actor_layout = {}
        for i, group in enumerate(groups):
            cell_w = stage_w / len(groups)
            widths = [bounds[key][2] - bounds[key][0] for key in group]
            edges = [600 - bounds[key][2] if j else bounds[key][0] for j, key in enumerate(group)]
            increments = [width - 18 for width in widths]
            for j in range(len(group) - 1):
                actor, target = group[j:j + 2]
                if not any(a == actor and t == target and v.name == 'nudge' for a, v, t in span.actions):
                    continue
                own, other = self.cast[actor], self.cast[target]
                head, receiver = build(own, Pose(), 0.).head, build(other, Pose(), 0.).head
                # Leave space for the actor's finite head/body advance. Nose contact
                # must not stack the two face centers or hide a small receiver.
                separation = (head.x * own.size + receiver.x * other.size +
                              .9 * (head.rx * own.size + receiver.rx * other.size) + 43 * own.size)
                increments[j] = max(increments[j], separation + edges[j + 1] - edges[j])
            group_width = sum(increments[:-1]) + widths[-1]
            tallest = max(bounds[key][3] - bounds[key][1] for key in main)
            scale = min(cell_w * .88 / max(1, group_width), stage_h * .86 / tallest)
            baby_group = all(self.cast[key].age == 'baby' for key in group)
            hyena_group = all(self.cast[key].species == 'hyena' for key in group)
            if baby_group or hyena_group:
                # Keep independently staged babies and threat representatives
                # legible. Interacting groups retain one exact scale so the
                # adult can reach its actual receiver.
                own_height = max(bounds[key][3] - bounds[key][1] for key in group)
                legible_height = .14 if baby_group else .17
                scale = min(cell_w * .88 / max(1, group_width), max(scale, self.size[1] * legible_height / own_height))
            travelling = any(actor in group and a.name in ('walk', 'run') for actor, a, _ in span.actions)
            if travelling:
                travel_width = .82 if hyena_group else .65
                scale = min(scale, cell_w * travel_width / max(1, group_width))
            # Face the nudge pair inward; actor order is owned by the source action.
            paired = len(group) > 1
            left = (self.size[0] * stage_left + (i + .04) * cell_w if travelling else
                    self.size[0] * stage_left + (i + .5) * cell_w - group_width * scale / 2)
            for j, key in enumerate(group):
                mirror = paired and j > 0 and any(a.name in ('nudge', 'swipe') and target == key for _, a, target in span.actions)
                bbox = bounds[key]
                edge = 600 - bbox[2] if mirror else bbox[0]
                anchor = left + (300 - edge) * scale
                span.actor_layout[key] = (anchor / self.size[0], ground, 400 * scale / self.size[1], mirror, i)
                left += increments[j] * scale
        # A swipe has to reach its source receiver; separate silhouette slots
        # alone can leave the striking paw nowhere near the intruder's body.
        for actor, action, target in span.actions:
            if action.name == 'walk' and target and self.cast[actor].species == 'hyena':
                x, ground, height, _, group = span.actor_layout[actor]
                span.actor_layout[actor] = (x, ground, height, span.actor_layout[target][0] < x, group)
            if action.name != 'swipe' or not target:
                continue
            own, other = self.cast[actor], self.cast[target]
            x, ground, height, _, group = span.actor_layout[actor]
            _, _, _, mirror, _ = span.actor_layout[target]
            contact = build(own, Pose(swipe=1.)).legs['front_near'].end
            head = build(other).head
            scale = self.size[1] * height / RIG_HEIGHT
            target_x = x + (contact[0] * own.size + (head.x if mirror else -head.x) * other.size) * scale / self.size[0]
            span.actor_layout[target] = (target_x, ground, height, mirror, group)

    def _cast_groups(self, span):
        # Interacting participants share a cell; unrelated actors retain independent slots.
        groups = [[a] for a in span.actors if span.source_character or not a.startswith('crowd-hyena-')]
        for actor, action, target in span.actions:
            if not target or action.name not in ('nudge', 'sleep', 'hide', 'swipe'):
                continue
            if not any(target in g for g in groups):
                continue
            left = next(g for g in groups if actor in g)
            right = next(g for g in groups if target in g)
            if left is not right:
                left.extend(right)
                groups.remove(right)
        return groups

    def _actor_slot(self, span, key):
        if span.source_character and span.actor_layout and key in span.actor_layout:
            return span.actor_layout[key][:3]
        main = [a for a in span.actors if not a.startswith('crowd-hyena-')]
        i, n = main.index(key), len(main)
        if span.spec['composition'] in ('grid', 'split'):
            groups = self._cast_groups(span)
            group = next(g for g in groups if key in g)
            offset = len(span.motion.elements)
            total = offset + len(groups)
            cols = (1 if self.square else 2) if span.spec['composition'] == 'split' else math.ceil(math.sqrt(total))
            rows = math.ceil(total / cols)
            slot = offset + groups.index(group)
            within = .5 + (group.index(key) - (len(group) - 1) / 2) * .6 / max(1, len(group))
            ground = (slot // cols + .85) / rows
            height = min(.65 / rows, 1.2 / (cols * len(group)))
            if self.square:
                ground, height = .08 + ground * .68, height * .68
            return (slot % cols + within) / cols, ground, height
        x = {'left_third': 1/3, 'right_third': 2/3}.get(span.spec['composition'], .5) if n == 1 else .2 + .6 * i / max(1, n - 1)
        return x, .8, min(.78, (0.78 if self.square else 1.5) / max(1, n))

    def _travel(self, span, key, local, height):
        """Pixels a walk/run cue has carried an actor: scenes, not the pose cycle, do the moving."""
        return sum(travel_x(a, local) for actor, a, _ in span.actions if actor == key) * self.cast[key].size * height / RIG_HEIGHT

    def _actors(self, span, local, image):
        if span.source_character:
            return self._character_actors(span, local, image)
        main = [key for key in span.actors if not key.startswith('crowd-hyena-')]
        crowd = [key for key in span.actors if key.startswith('crowd-hyena-')]
        n = len(main)
        w, h = image.size
        for key in crowd + main:
            is_crowd = key in crowd
            i = (crowd if is_crowd else main).index(key)
            g = self.cast[key]
            actions = [a for actor, a, target in span.actions if actor == key]
            from .creatures.actions import action_pose, Pose
            pose = Pose()
            for a in actions:
                pose = add(pose, cue_pose(a, actions, local))
            for actor, a, target in span.actions:
                if target == key:
                    pose = add(pose, target_response(a, local))
            x, ground, relative_height = ((i + .5) / len(crowd), .42, .24) if is_crowd else self._actor_slot(span, key)
            height = round(h * relative_height)
            if self.square:
                # Rigs have different silhouettes; measure their SVG viewBox,
                # then rasterize once at the size fitting the actor's safe slot.
                from .creatures.draw import svg
                import xml.etree.ElementTree as ET
                view = ET.fromstring(svg(g, pose, local)).attrib['viewBox'].split()
                ratio = float(view[2]) / float(view[3])
                slot_width = w * (.8 / max(1, n) if not is_crowd else .8 / len(crowd))
                height = min(height, round(slot_width / ratio))
            sprite_height = max(60, height)
            sprite = raster(g, pose, local, height=sprite_height)
            bbox = sprite.getchannel('A').getbbox()
            if bbox:
                sprite = sprite.crop(bbox)
            # Distinct slots keep faces separate; the nudge deforms both participants in their slots.
            move = 0.
            for actor, a, target in span.actions:
                if a.name == 'nudge' and target and actor in main and target in main:
                    if actor == key or target == key:
                        # Keep interacting bodies close enough for a nudge, with separate face centers.
                        other = target if actor == key else actor
                        x += .055 if self._actor_slot(span, key)[0] < self._actor_slot(span, other)[0] else -.055
                    u = (local - a.start) / a.seconds
                    direction = 1 if self._actor_slot(span, target)[0] > self._actor_slot(span, actor)[0] else -1
                    if 0 < u < 1 and actor == key:
                        move += direction * w * .035 * math.sin(math.pi * u) ** 2
                    elif target == key:
                        move += direction * target_response(a, local).dx * w / 600
            # Travel carries the actor rightward but never past a margin at the frame edge.
            travel = self._travel(span, key, local, sprite_height)
            travel = min(travel, max(0., w * (1 - TRAVEL_MARGIN) - (x * w + move + sprite.width / 2)))
            move += travel
            image.paste(sprite, (round(x * w + move - sprite.width / 2),
                                 round(h * ground - sprite.height)), sprite)
        return image

    def _character_actors(self, span, local, image):
        from .creatures.actions import action_pose, Pose, window, smooth
        from .creatures.life import idle_pose
        from .creatures.rig import build
        w, h = image.size
        floor = span.motion.motion_floor
        # Receivers sit in front of the nudging adult's mane/head, keeping both faces visible.
        sleepers = {actor for actor, a, target in span.actions if a.name == 'sleep' and target}
        covers = {target for actor, a, target in span.actions if a.name == 'hide' and target}
        ordered = sorted(span.actors, key=lambda key: (key in covers, key in sleepers,
                         span.actor_layout[key][4], span.actor_layout[key][3])
                         if key in span.actor_layout else (False, False, -1, False))
        for key in ordered:
            g = self.cast[key]
            if key not in span.actor_layout:
                # Source plural representatives remain behind the main cast.
                crowd = [k for k in span.actors if k not in span.actor_layout]
                panel = not self.square and len(self._cast_groups(span)) == 1
                fraction = (crowd.index(key) + .5) / len(crowd)
                side = .15 if span.spec['composition'] == 'left_third' else .57
                slot = ((side + .28 * fraction, .26, .13, False, len(span.actor_layout)) if panel else
                        (.15 + .70 * fraction, .51, .16, False, len(span.actor_layout)))
            else:
                slot = span.actor_layout[key]
            x, ground, height, mirror, group = slot
            pose = Pose()
            cues = [a for actor, a, _ in span.actions if actor == key]
            for actor, action, target in span.actions:
                if actor == key:
                    acting = cue_pose(action, cues, local)
                    if action.name == 'nudge' and target:
                        acting = action_pose(Action('nudge', action.start, action.seconds, max(.85, action.intensity)), local)
                        u = (local - action.start) / action.seconds
                        own_head = build(g, Pose(), 0.).head.y * g.size
                        other = self.cast[target]
                        target_head = build(other, Pose(), 0.).head.y * other.size
                        lower = window(u, .30, .58)
                        acting = add(acting, Pose(head_y=((target_head - own_head) / g.size - 68 * max(.85, action.intensity)) * lower,
                                                  dx=18 * window(u, .3, .65)))
                    pose = add(pose, acting)
                    if action.name == 'sleep' and target in span.actor_layout:
                        other = self.cast[target]
                        target_x, _, target_height, _, _ = span.actor_layout[target]
                        parent_body = build(other).body
                        own_head = build(g).head
                        scale = h * target_height / RIG_HEIGHT
                        contact_x = target_x + (parent_body.x * other.size -
                                               (own_head.x + own_head.rx * .35) * g.size) * scale / w
                        x += (contact_x - x) * acting.sleep
                    if action.name == 'hide' and target in span.actor_layout:
                        other = self.cast[target]
                        target_x, _, target_height, _, _ = span.actor_layout[target]
                        paw = build(other).legs['front_near'].root
                        own_head = build(g).head
                        scale = h * target_height / RIG_HEIGHT
                        contact_x = target_x + ((paw[0] - 45) * other.size - own_head.x * g.size) * scale / w
                        u = (local - action.start) / action.seconds
                        x += (contact_x - x) * window(u, .24, .80)
                elif target == key:
                    response = target_response(action, local)
                    pose = add(pose, response)
                    if action.name == 'nudge':
                        u = (local - action.start) / action.seconds
                        recoil = window((u - .4) / .6, .25, .6)
                        pose = add(pose, Pose(dx=(-8 if mirror else 8) * recoil,
                                              lean=(-5 if mirror else 5) * recoil, head_pitch=-5 * recoil))
                    elif action.name == 'swipe':
                        # The receiver leaves the paw after impact and stays
                        # displaced; easing from the hit prevents a cue-end snap.
                        u = (local - action.start) / action.seconds
                        recoil = smooth((u - .38) / .62)
                        scale = h * height / RIG_HEIGHT
                        x += 180 * recoil * self.cast[actor].size * scale / w
                        ground -= 60 * math.sin(math.pi * recoil) * scale / h
                        pose = add(pose, Pose(lean=(-20 if mirror else 20) * recoil,
                                              head_pitch=15 * recoil, worry=recoil))
            phase = seed((span.spec['beat_ids'], group)) / 2**32 * math.tau
            awake = 1. - min(1., pose.sleep)
            # An asleep child follows its contact partner's group translation;
            # independent head, tail and awake fidget channels remain suppressed.
            drift = 1. if key in sleepers else awake
            draw_time = local if floor or pose.sleep or any(
                (actor == key or target == key) and a.start < local < a.start + a.seconds
                for actor, a, target in span.actions) else 0.
            if floor:
                # Composed foreground drift and visible idle acting continue after
                # finite cues. Paired actors share drift, preserving their contact.
                journeys = [a.start + a.seconds for actor, a, _ in span.actions
                            if actor == key and a.name in ('walk', 'run')]
                settled = smooth((local - max(journeys)) / .5) if journeys else 1.
                x += settled * floor * drift * 60 * math.sin(local * 1.13 + phase) / w
                ground += floor * drift * 31 * math.sin(local * 1.67 + phase * .8) / h
                pose = add(pose, Pose(breath=.04 * floor * awake * math.sin(local * 2.5 + phase),
                                     head_pitch=10 * floor * awake * math.sin(local * 1.5 + phase),
                                     head_y=8 * floor * awake * math.sin(local * 2.3 + phase),
                                     tail=20 * floor * awake * math.sin(local * 1.7 + phase)))
            else:
                idle = idle_pose(g, draw_time)
                pose = add(pose, Pose(**{f.name: tuple(-v * awake for v in getattr(idle, f.name))
                                        if isinstance(getattr(idle, f.name), tuple) else -getattr(idle, f.name) * awake
                                        for f in fields(Pose)}))
            sprite_height = max(60, round(h * height))
            sprite = raster(g, pose, draw_time, height=sprite_height)
            scale = sprite_height / 400
            if mirror:
                sprite = ImageOps.mirror(sprite)
            bbox = sprite.getchannel('A').getbbox()
            if bbox:
                # A5's eased travel is retained in this stable-root composition.
                # Leave room for the authored idle sway.
                right = x * w + bbox[2] - 300 * scale
                destination = next((target for actor, a, target in span.actions
                                    if actor == key and a.name == 'walk' and target in span.actor_layout), None)
                direction = -1 if destination and span.actor_layout[destination][0] < x else 1
                left = x * w + bbox[0] - 300 * scale
                room = (max(0., left - w * TRAVEL_MARGIN - 60 * floor) if direction < 0 else
                        max(0., w * (1 - TRAVEL_MARGIN) - right - 60 * floor))
                if destination:
                    target_x, _, target_height, target_mirror, target_group = span.actor_layout[destination]
                    target_phase = seed((span.spec['beat_ids'], target_group)) / 2**32 * math.tau
                    target_x += floor * 60 * math.sin(local * 1.13 + target_phase) / w
                    target_pixels = max(60, round(h * target_height))
                    target_sprite = raster(self.cast[destination], 'idle', 0., height=target_pixels)
                    if target_mirror:
                        target_sprite = ImageOps.mirror(target_sprite)
                    target_box = target_sprite.getchannel('A').getbbox()
                    target_scale = target_pixels / RIG_HEIGHT
                    target_edge = target_x * w + target_box[2 if direction < 0 else 0] - 300 * target_scale
                    clearance = 45 * h / 1080
                    approach = left - target_edge - clearance if direction < 0 else target_edge - right - clearance
                    room = min(room, max(0., approach))
                travel = min(room, self._travel(span, key, local, sprite_height))
                x += direction * travel / w
                # Pounces, jaw/head action and idle sway also need the complete
                # silhouette inside the frame's safe edges.
                left = x * w + bbox[0] - 300 * scale
                right = x * w + bbox[2] - 300 * scale
                panel = not self.square and len(self._cast_groups(span)) == 1
                left_stage, right_stage = ((.04, .50) if span.spec['composition'] == 'left_third' else (.50, .96)) if panel else (TRAVEL_MARGIN, 1 - TRAVEL_MARGIN)
                low, high = w * left_stage, w * right_stage
                x += (max(0., low - left) - max(0., right - high)) / w
                # Retain the SVG's ground/root anchor. Recentring each cropped pose
                # used to cancel body translation and make interacting actors icons.
                sprite = sprite.crop(bbox)
                image.paste(sprite, (round(x * w + bbox[0] - 300 * scale),
                                     round(ground * h + bbox[1] - 358 * scale)), sprite)
        return image

    def _frame(self, span, t, *, quotes=True):
        spec, local = span.spec, max(0, t - span.start)
        if span.story is not None:
            return self.storybook.frame(span.story, local)
        if self._on_board(span):
            return self.cutaway.frame(t).convert('RGB')
        if span.scientific:
            from ..scientific import render_plots
            return render_plots(span.scientific, local, span.end - span.start, self.size)
        w, h = self.size
        background = None
        if span.atmos:
            from .bold.render import _background
            base = np.clip(_background(span.motion, local, w, h), 0, 255).astype(np.uint8)
            background = np.clip(compose(base, span.atmos, local) * 255 + .5, 0, 255).astype(np.uint8)
        scene = span.motion_art or span.motion
        if self.square:
            array = self._square_frame(scene, local, w, h, background)
        else:
            array = render_frame(scene, local, w, h, background=background)
        image = Image.fromarray(array)
        active = next((d for d in reversed(span.diagrams) if t >= d.window[0]), None)
        if active:
            active.paint(image, t)
        if spec['treatment'] == 'chart' and (span.source_chart or not span.motion.elements):
            # Use actual numeric data, never fabricate chart values.
            board = self.cutaway.frame(t).convert('RGB')
            image.paste(board.resize((round(w * .82), round(h * .82))), (round(w * .09), round(h * .09)))
        if span.actors:
            image = self._actors(span, local, image)
        zoom, dx, dy = self._camera(span, local)
        if zoom != 1 or dx or dy:
            image = camera_move(image, zoom, dx, dy, ImageColor.getrgb(self.style['palette']['background']))
        if span.source_character:
            # Source labels/atomic quotes keep their safe screen position while
            # the scene camera follows the artwork. Captions are added later at
            # their actual narration time by frame().
            from .bold import render as renderer
            key = (id(span.motion), w, h)
            if key not in self._text_layers:
                self._text_layers[key] = (_SquareLayers(span.motion, w, h) if self.square else
                                          _SceneLayers(span.motion, w, h))
            array = np.asarray(image, dtype=np.float32).copy()
            for i, e in enumerate(span.motion.elements):
                if e.kind == 'text' and (e.preset != 'corner_caption' or (quotes and
                                        e.start <= local < (e.end if e.end is not None else math.inf))):
                    renderer._composite(array, self._text_layers[key], i, [local], 'text')
            image = Image.fromarray(np.clip(array + .5, 0, 255).astype(np.uint8))
        return image.convert('RGB')

    def _camera(self, span, local):
        """The scene camera applied over a rendered span: (zoom about the centre, pan dx, dy) in output pixels.
        Locked (J 10/8: no "random camera zooms"): the planner's slow_push, pull_back, pans and follow each restarted
        with every scene, so the picture zoomed in and jumped back at each join. Only a shake scene's opening jolt
        moves it."""
        from .storybook import calm
        if span.spec['camera'] != 'shake' or calm(self.style):
            return 1., 0., 0.                     # a calm, low-energy plan keeps a static camera in every scene
        h = self.size[1]
        strength = 2 * self.style['energy'] * math.exp(-local * 4) * (h / 1080 if self.native else 1)
        return 1., strength * math.sin(local * 39), strength * math.sin(local * 31)

    def _anchored(self, span):
        """Scenes the recurring anchor point visits: drawn motion scenes, not boards, stories, plots or diagrams."""
        return (span.motion is not None and span.story is None and not span.source_proof and not span.scientific
                and not span.source_character and not span.diagram and not span.diagrams and not span.actors
                and span.spec['treatment'] not in ('whiteboard', 'character')
                and not (span.spec['treatment'] == 'chart' and (span.source_chart or not span.motion.elements)))

    def _anchor_keys(self):
        """(time, span, element) stops of the anchor: each picture, headline, number or button from the moment the
        narration brings it in (never before its scene's join), and the scene's centre until the first arrives."""
        keys = {}
        for i, span in enumerate(self.spans):
            if not self._anchored(span):
                continue
            targets = [(max(span.join, span.start + e.start), j) for j, e in enumerate(span.motion.elements)
                       if e.kind in ('picture', 'button') or e.kind == 'text' and e.preset != 'corner_caption']
            if not targets or min(targets)[0] > span.join + 1e-6:
                targets.append((span.join, None))        # the scene's centre until its first target arrives
            for at, j in sorted(targets, key=lambda k: (k[0], -1 if k[1] is None else k[1])):
                keys[round(at, 6)] = (at, i, j)          # one target per instant: the later element wins
        return sorted(keys.values())

    def _anchor_target(self, i, j, t):
        """Screen point just above element j of span i at time t, with its form: (x, y, bar, ring)."""
        from .bold.render import H, W, _button_box, element_pose
        span = self.spans[i]
        local = max(0., min(t, span.end - 1 / 30) - span.start)
        w, h = self.size
        if j is None:
            x, y, bar, ring = W / 2, H / 2, 0., 0.
        else:
            e = span.motion.elements[j]
            x, y, scale, _ = element_pose(span.motion, e, j, local)
            if e.kind == 'picture':
                half, bar, ring = e.height / 2, 0., 0.
            elif e.kind == 'button':
                half, bar, ring = _button_box(e)[3] / 2, 0., 1.
            else:
                half = len(e.text.split('\n')) * e.size * .6
                bar, ring = (0., 1.) if e.preset == 'counter' else (1., 0.)
            y = max(H * .06, y - half * scale - 34)
        zoom, dx, dy = self._camera(span, local)
        x, y = x * w / W, y * h / H
        return w / 2 + zoom * (x - dx - w / 2), h / 2 + zoom * (y - dy - h / 2), bar, ring

    def _anchor(self, t):
        """What's the Point: one accent point carries the motif through the motion scenes. It rests just above
        whatever the narration has brought in (a dot over a picture, a rule over a headline, a ring over a number
        or a button), glides to the next one, across scene joins too, and holds a scene's centre until then.
        Returns its screen position, form weights and opacity, or None where it is not drawn."""
        if not self.anchor_keys or self.square or self.vertical or t < self.starts[0]:
            return None
        end_start = self.tl['end_card']['start']
        i = bisect.bisect_right(self.starts, min(t, end_start - 1e-6)) - 1
        span = self.spans[i]
        visited = {key[1] for key in self.anchor_keys}                 # spans with stops of their own
        here, before = i in visited, i - 1 in visited
        fade = motion.clamp01((t - span.join) / max(.3, span.join_length))
        if t >= end_start:
            if not here or t >= end_start + span.join_length:
                return None
            alpha = 1 - motion.clamp01((t - end_start) / max(.01, span.join_length))
        elif here:
            alpha = 1. if before else fade
        elif (before and t < span.join + span.join_length and span.spec['treatment'] != 'whiteboard'
              and not span.source_proof and not span.scientific):
            alpha = 1 - fade                                            # out over the transition; boards and plots cut
        else:
            return None
        times = [k[0] for k in self.anchor_keys]
        k = max(0, bisect.bisect_right(times, t) - 1)
        at, si, sj = self.anchor_keys[k]
        x, y, bar, ring = self._anchor_target(si, sj, t)
        if k and self.anchor_keys[k - 1][1] >= si - 1:                 # glide on from the stop before it
            u = motion.cubic_in_out((t - at) / ANCHOR_GLIDE)
            if u < 1:
                old = self._anchor_target(*self.anchor_keys[k - 1][1:], t)
                x, y, bar, ring = (a + (b - a) * u for a, b in zip(old, (x, y, bar, ring)))
        return {'x': x, 'y': y, 'bar': bar, 'ring': ring, 'alpha': alpha}

    def _draw_anchor(self, image, t):
        anchor = self._anchor(t)
        if anchor is None or anchor['alpha'] <= 0:
            return image
        s = image.size[1] / 1080
        x, y = anchor['x'], anchor['y']
        r, half, ring = 7 * s, 46 * s * anchor['bar'], 22 * s * anchor['ring']
        pad = math.ceil(half + ring + 28 * s)
        left, top = math.floor(x) - pad, math.floor(y) - pad
        k = 4                                                            # supersampled for clean edges
        layer = Image.new('RGBA', (2 * pad * k, 2 * pad * k), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        accent = ImageColor.getrgb(self.style['palette']['accent'])[:3]
        cx, cy = (x - left) * k, (y - top) * k
        thick = r * (1 - .35 * anchor['bar'])
        draw.rounded_rectangle((cx - (half + thick) * k, cy - thick * k, cx + (half + thick) * k, cy + thick * k),
                               radius=thick * k, fill=accent + (255,))
        if ring > .5 * s:
            reach = (r + ring) * k
            draw.ellipse((cx - reach, cy - reach, cx + reach, cy + reach), outline=accent + (round(200 * anchor['ring']),),
                         width=max(1, round(2.5 * s * k)))
        layer = layer.resize((2 * pad, 2 * pad), Image.Resampling.LANCZOS)
        glow = layer.filter(ImageFilter.GaussianBlur(9 * s))
        out = Image.new('RGBA', layer.size, (0, 0, 0, 0))
        out = Image.alpha_composite(Image.alpha_composite(out, glow), layer)
        if anchor['alpha'] < 1:
            out.putalpha(out.getchannel('A').point(lambda v: round(v * anchor['alpha'])))
        image.paste(out, (left, top), out)                              # clipped at the frame's edges
        return image

    def _square_frame(self, scene, t, w, h, background):
        """Use the motion engine's native sprites/effects with uniform square geometry."""
        from .bold import render as renderer
        key = id(scene), w, h
        if key not in self._square_layers:
            self._square_layers[key] = _SquareLayers(scene, w, h)
        layers = self._square_layers[key]
        art = renderer._background(scene, t, w, h) if background is None else np.asarray(background, np.float32).copy()
        for i, e in enumerate(scene.elements):
            times = [t]
            if scene.blur_samples > 1 and renderer._element_blurs(scene, e, i, t):
                times = t + np.linspace(-.5, .5, scene.blur_samples) / renderer.FPS
            renderer._composite(art, layers, i, times, 'art')
        if scene.glow and any(e.emissive for e in scene.elements):
            gw, gh = max(1, w // 4), max(1, h // 4)
            light = np.zeros((gh, gw, 4), np.float32)
            for i, e in enumerate(scene.elements):
                if e.emissive:
                    renderer._composite(light, layers, i, [t], 'art')
            light = renderer.glow_layer(light[..., :3], renderer.GLOW_HALF * gh / renderer.H)
            halo = Image.fromarray(np.clip(light * 4 * scene.glow, 0, 255).astype(np.uint8))
            art += np.asarray(halo.resize((w, h), Image.Resampling.BILINEAR), np.float32)
        art *= renderer._vignette(w, h)
        if scene.grain:
            rng = renderer.m.seeded(scene.seed, 'bold grain', math.floor(t * renderer.FPS + 1e-6), w, h)
            art += rng.normal(0, scene.grain, (h, w, 1)).astype(np.float32)
        for i in range(len(scene.elements)):
            renderer._composite(art, layers, i, [t], 'text')
        return np.clip(art + .5, 0, 255).astype(np.uint8)

    def _screen_notes(self):
        """The on-screen text the script's directions ask for, as (start, end, kind, words): a text card for
        "[TEXT ON SCREEN: SAVE UP TO 20%]", a name strap for "LOWER THIRD: Maria Chen - Owner". A note on a line
        nobody says shows over the next line that is said (the strap is under the person who speaks next); a note
        inside a said line shows from where it is written. Each holds at least 3 s and at most 6 s."""
        from .. import speech
        order = [b for b in self.tl['beat_order'] if b in self.by_id]
        said = {b: bool(self.tl['beats'][b].get('char_times')) and any(ch.isalnum() for ch in speech.caption_text(
            self.by_id[b]['text'], self.labels)) for b in order}
        stop = self.tl['end_card']['start']
        out = []
        for k, bid in enumerate(order):
            beat = self.by_id[bid]
            for pos, kind, words in speech.screen_text(beat['text'], self.labels):
                if said[bid]:
                    at = self._spoken_at(bid, self._spoken_offset(bid, pos))
                    until = self.tl['beats'][bid]['end']
                else:
                    host = next((b for b in order[k + 1:] if said[b]), bid)
                    at, until = self.tl['beats'][host]['start'], self.tl['beats'][host]['end']
                end = min(max(until, at + 3.), at + 6., stop)
                if end > at:
                    out.append((at, end, kind, words))
        return out

    def _draw_screen_text(self, image, t):
        """The script's on-screen text at ``t`` over the finished frame: the newest name strap low on the left, above
        the caption, and the newest text card across the top. Both ease in and out (0.25 s)."""
        from . import ink
        live = {}
        for at, end, kind, words in self.screen_notes:
            if at <= t < end:
                live[kind] = (at, end, words)
        if not live:
            return image
        w, h = self.size
        unit = min(w, h) / 1080
        p = {k: ImageColor.getrgb(v)[:3] for k, v in self.style['palette'].items()}
        layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for kind, (at, end, words) in live.items():
            fade = max(0., min(1., (t - at) / .25, (end - t) / .25))
            alpha = round(255 * fade)
            if kind == 'strap':
                name, role = (re.split(r'\s+[-–—|]\s+', words, maxsplit=1) + [''])[:2]   # "Maria Chen - Owner"
                big, small = ink.font('en_caption', round(52 * unit)), ink.font('en_caption', round(36 * unit))
                lines = [(name.strip(), big)] + ([(role.strip(), small)] if role.strip() else [])
                pad = round(22 * unit)
                width = max(draw.textlength(text, font=f) for text, f in lines) + 2 * pad + round(12 * unit)
                height = sum(f.size * 1.2 for _, f in lines) + 2 * pad - round(4 * unit)
                x = round(w * .05 - (1 - fade) * 60 * unit)
                bottom = round(h * (.80 if not self.vertical else .72))
                y = bottom - height
                draw.rectangle((x, y, x + width, bottom), fill=p['ink'] + (round(alpha * .92),))
                draw.rectangle((x, y, x + round(12 * unit), bottom), fill=p['accent'] + (alpha,))
                ty = y + pad
                for text, f in lines:
                    draw.text((x + pad + round(12 * unit), ty), text, font=f, fill=p['background'] + (alpha,))
                    ty += f.size * 1.2
            else:
                f = ink.font('en_caption', round(64 * unit))
                rows = textwrap.wrap(words, max(8, int(w * .8 / max(1., f.getlength('n')))), break_long_words=False)
                pad = round(26 * unit)
                width = max(draw.textlength(r, font=f) for r in rows) + 2 * pad
                height = len(rows) * f.size * 1.2 + 2 * pad - round(6 * unit)
                x, y = (w - width) / 2, round(h * .06) - (1 - fade) * 30 * unit
                draw.rounded_rectangle((x, y, x + width, y + height), radius=round(14 * unit),
                                       fill=p['accent'] + (round(alpha * .95),))
                ink_on = p['ink'] if _contrast(p['ink'], p['accent']) >= _contrast(p['background'], p['accent']) \
                    else p['background']
                for i, r in enumerate(rows):
                    draw.text(((w - draw.textlength(r, font=f)) / 2, y + pad + i * f.size * 1.2), r, font=f,
                              fill=ink_on + (alpha,))
        return Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB')

    def frame(self, t):
        image = self._frame_at(t)
        return self._draw_screen_text(image, t) if self.screen_notes else image

    def _frame_at(self, t):
        if not self.spans or t < self.starts[0]:
            return self.whiteboard.frame(t)
        end_start = self.tl['end_card']['start']
        if t >= end_start:
            last = self.spans[-1]
            if (last.spec['treatment'] != 'whiteboard' and not last.source_proof and not last.scientific
                    and t < end_start + last.join_length):
                # Keep the existing endcard clock; ease out of a cinematic scene
                # instead of making an extra unaligned hard cut at its boundary.
                previous = self._frame(last, end_start - 1 / 30, quotes=False)
                # A storybook ends on the end card's blank page: the whiteboard camera is still crossing its own
                # legacy pages (labelled icons, people) during the join, which never belong in a story.
                card_t = max(t, end_start + last.join_length) if last.story is not None else t
                current = self.whiteboard.frame(card_t).convert('RGB')
                array = render_transition(np.asarray(previous), np.asarray(current), t - end_start, *self.size,
                                          kind='page' if last.story is not None and self.story_genre else 'match',
                                          duration=last.join_length)      # a picture book turns to its last page
                image = self._draw_anchor(Image.fromarray(array).convert('RGBA'), t)
                if not self.vertical:
                    self.whiteboard._caption(image, t, self.caption_look, self.caption_accent)
                return image.convert('RGB')
            return self.whiteboard.frame(t)
        i = bisect.bisect_right(self.starts, t) - 1
        span = self.spans[i]
        # Selected whiteboard scenes retain their exact legacy bytes, including transitions.
        if span.spec['treatment'] == 'whiteboard' or span.source_proof:
            return self.whiteboard.frame(t)
        local = t - span.join
        kind = span.spec['transition_in']
        if kind == 'zoom_through':
            kind = 'match'          # the camera stays locked between scenes too: a dissolve, never a zoom (J 10/8)
        if span.scientific or (i and self.spans[i - 1].scientific):
            # Scientific panels follow the source clock and retain their exact
            # canvas/axis transform through both sides of every scene boundary.
            image = self._frame(span, t)
        elif span.story is not None and i and self.spans[i - 1].story is not None:
            # Two story pages: the old page keeps living until the join, then turns like any shot change (a wipe, or
            # a two-frame dissolve where the same set continues), never a long dissolve of two crowded pictures.
            previous = self.spans[i - 1]
            if self.storybook.turn_kind(previous.story[-1], span.story[0]) == 'cut':
                image = self._frame(span, t)   # out of a close-up or onto the same picture: a cut on its sentence
            elif local < 0:
                image = self._frame(previous, t)
            elif kind == 'cut':
                image = self._frame(span, t)
            else:
                image = self.storybook.turn(previous.story, t - previous.start, span.story, t - span.start, local)
        elif span.diagram and t >= span.diagram.window[0]:
            # The spoken glide cue owns these panels. A score-delayed join must
            # not hide their labels or substitute the previous scene.
            image = self._frame(span, t)
        elif i and local < 0:
            # Until the join lands on its music beat the old scene keeps living (its drift and atmosphere go on):
            # a still of its last frame froze the picture through every pause that opens a scene.
            image = self._frame(self.spans[i - 1], t, quotes=False)
        else:
            image = self._frame(span, t)
            if i and kind != 'cut' and local < span.join_length:
                previous = self._frame(self.spans[i - 1], t, quotes=False)
                array = render_transition(np.asarray(previous), np.asarray(image), local, *self.size,
                                          kind=kind, duration=span.join_length)
                image = Image.fromarray(array)
        image = self._draw_anchor(image.convert('RGBA'), t)
        if not self.vertical:
            self.whiteboard._steps(image, t)
        if not self.vertical and not self._written(span, t):
            self.whiteboard._caption(image, t, self.caption_look, self.caption_accent)
        return image.convert('RGB')

    def _leave_bubbled_lines_to_the_bubbles(self):
        """Where a story page shows a line in a speech bubble (the storybook's ``bubbled`` rows: beat, start, end of
        its spoken text), the burned-in caption carries only the narrator. Lines over a page without a bubble stay."""
        rows = getattr(self.storybook, 'bubbled', None) if self.storybook is not None else None
        if not rows:
            return
        bubbled = {}
        for row in rows:
            bubbled.setdefault(row['beat'], []).append((row['start'], row['end']))
        self.tl = {**self.tl, 'captions': timeline.recaption(self.ep, self.tl, self.lang, bubbled)}
        wb = self.whiteboard
        wb.tl = {**wb.tl, 'captions': self.tl['captions']}
        wb.cap_starts = [c['start'] for c in wb.tl['captions']]
        wb.cap_words = [c['words'] for c in wb.tl['captions']]

    @staticmethod
    def _on_board(span):
        """The scene is shown as the source whiteboard instead of its own motion art."""
        treatment = span.spec['treatment']
        return span.source_proof or treatment == 'whiteboard' or (treatment == 'character' and not span.actors)

    def _written(self, span, t):
        """The words being said are already written on screen by this scene (kinetic type, a title, a quote, a call
        to action): no caption repeats them underneath. A scene shown as a story page, the whiteboard or a plot never
        draws its own text elements, so there the caption stays."""
        if span.story is not None or span.scientific or self._on_board(span):
            return False
        beat = next((b for b in span.spec['beat_ids'] if self.tl['beats'][b]['start'] <= t < self.tl['beats'][b]['end']),
                    None)
        return beat in span.on_screen

    def cues(self):
        from .bold.model import TYPE_CPS
        from .creatures.actions import action_pose
        cues = []
        for i, span in enumerate(self.spans):
            if span.spec['treatment'] == 'whiteboard':
                continue
            neutral = span.scientific or (i and self.spans[i - 1].scientific)
            start = span.join if i else span.start
            following = self.spans[i + 1] if i + 1 < len(self.spans) else None
            until = (span.end if following is None else following.start
                     if following.spec['treatment'] == 'whiteboard' else following.join)      # on screen until
            kind = 'cut' if span.spec['transition_in'] == 'cut' or neutral else 'whoosh'
            if kind == 'whoosh' and i and (self.by_id[span.spec['beat_ids'][0]]['section'] !=
                                           self.by_id[self.spans[i - 1].spec['beat_ids'][0]]['section']):
                cues.append({'t': start, 'kind': 'transition_whoosh', 'dur': span.join_length,
                             'id': f'hybrid.scene.{i}'})     # a new chapter: one long, soft whoosh across the transition
            else:
                cues.append({'t': start, 'kind': kind, 'strength': .35, 'id': f'hybrid.scene.{i}'})
            if span.atmos and not span.source_proof and not (span.spec['treatment'] == 'character' and not span.actors):
                bed = {'rain': 'rain', 'fog': 'fog_drone', 'fog_with_shooting_star': 'fog_drone', 'dust': 'wind',
                       'snow': 'wind'}.get(span.spec['atmosphere']['kind'])
                if bed:                                      # a low bed under the scene; the mix ducks it under speech
                    cues.append({'t': start, 'kind': bed, 'dur': until - start, 'id': f'hybrid.bed.{i}'})
                for name, _, options in span.atmos.layers:
                    if name == 'shooting_star':              # on the first score beat while the star crosses
                        a, b = (span.start + x for x in options['window'])
                        beats = self.score_beats[(self.score_beats >= a) & (self.score_beats < b)]
                        cues.append({'t': float(beats[0]) if len(beats) else a, 'kind': 'shooting_star',
                                     'id': f'hybrid.star.{i}'})
            if span.spec['treatment'] == 'kinetic_type' and span.motion:
                for j, e in enumerate(span.motion.elements):  # a tick as each typed character appears
                    if e.kind == 'text' and e.preset == 'type_on':
                        cues += [{'t': span.start + e.start + (k + 1) / TYPE_CPS, 'kind': 'type_tick', 'strength': .7,
                                  'id': f'hybrid.type.{i}.{j}.{k}'} for k, char in enumerate(e.text)
                                 if not char.isspace() and span.start + e.start + (k + 1) / TYPE_CPS < until]
            if span.motion and not span.source_character:   # soft state-change hits, already on music beats
                for j, e in enumerate(span.motion.elements):
                    if e.kind == 'text' and e.preset == 'counter' and e.hit:
                        at, kind, strength = span.start + e.start + e.duration, 'pop', .6
                    elif e.kind == 'button':
                        at, kind, strength = span.start + e.cues[0], 'tap', .8
                    else:
                        continue
                    if start <= at < until:
                        cues.append({'t': at, 'kind': kind, 'strength': strength, 'id': f'hybrid.hit.{i}.{j}'})
            if span.story is not None:                       # the storybook's roars, timed to its drawn jaw
                for j, (at, roar) in enumerate(self.storybook.roar_cues(span.story, span.start)):
                    cues.append({'t': at, 'kind': roar, 'id': f'hybrid.story.{i}.{j}'})
                for j, (a, b) in enumerate(self.storybook.rain(span.story)):    # drawn rain: a rain bed under it
                    a = start if a <= 0 else span.start + a
                    b = until if b >= span.end - span.start - 1e-6 else span.start + b
                    cues.append({'t': a, 'kind': 'rain', 'dur': b - a, 'id': f'hybrid.rain.{i}.{j}'})
            for j, (actor, action, target) in enumerate(span.actions):
                # An action with its own synthesized sound (audio.synth_sfx) plays it, at full strength: the kind's
                # level keeps it audible under the narration. A pounce lands with an impact; only an animal cackles.
                kind = {'roar': 'roar', 'whimper': 'whimper', 'nudge': 'nudge', 'swipe': 'swipe',
                        'laugh': None if self.cast[actor].family == 'human' else 'hyena_cackle',
                        'breathe_heavy': 'breath_puff', 'pounce': 'impact'}.get(action.name)
                if kind == 'breath_puff':                    # a puff as each drawn exhale begins
                    steps = np.arange(0, action.seconds, .01)
                    out = np.array([action_pose(action, action.start + x).puffs > 0 for x in steps])
                    cues += [{'t': float(span.start + action.start + x), 'kind': kind, 'id': f'hybrid.action.{i}.{j}.{k}'}
                             for k, x in enumerate(steps[1:][out[1:] & ~out[:-1]])]
                elif kind:
                    at = span.start + action.start
                    available = self.score_beats[(self.score_beats >= span.start) & (self.score_beats < span.end)]
                    if len(available):
                        at = float(available[np.argmin(abs(available - at))])
                    cues.append({'t': at, 'kind': kind, 'id': f'hybrid.action.{i}.{j}'})
        return cues


class _SquareLayers(_SceneLayers):
    def __init__(self, scene, w, h):
        # Rasterize fragments at the final isotropic scale; convert only the
        # logical x coordinates expected by the existing motion compositor.
        super().__init__(scene, round(h * 1920 / 1080), h)
        self.x_ratio = (h * 1920 / 1080) / w

    def sprite(self, i, t, layer, geometry=None):
        sprite = super().sprite(i, t, layer, geometry)
        if sprite is None:
            return None
        channels, left, top, sx, sy = sprite
        return channels, left * self.x_ratio, top, sx / self.x_ratio, sy


def prepare_props(plan, board, project, llm, candidates=None):
    """Small callable-only A6 seam; saved generated refs are consumed offline by workers.

    candidates is a per-beat list of scored match.Hit objects. Empty offers are weak.
    The caller owns matching; there is no embedding download or implicit provider here.
    """
    from ..library.genprops import maybe_request_prop
    notes = []
    if llm is None:
        return notes
    by_id = {b['id']: b for b in beats(board)}
    for scene in plan['scenes']:
        if scene['treatment'] not in ('motion', 'atmosphere', 'whiteboard'):
            continue
        if any(e['kind'] in ('cast', 'diagram') for e in scene['elements']):
            continue
        description = ' '.join(by_id[b]['text'] for b in scene['beat_ids'])
        offered = [hit for b in scene['beat_ids'] for hit in (candidates or {}).get(b, [])]
        prop = maybe_request_prop(offered, description, list(plan['style']['palette'].values()),
                                  'bold flat', llm, project=project, enabled=True)
        if prop:
            scene['elements'] = [e for e in scene['elements'] if e['kind'] != 'picture']
            scene['elements'].append({'kind': 'picture', 'ref': prop.path.stem})
        else:
            notes.append(f"hybrid: no generated prop for {scene['beat_ids']}; library/source fallback")
    return notes

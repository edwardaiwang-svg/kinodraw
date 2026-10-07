"""Saved Director-v3 scenes on the narration timeline, evaluated only from absolute time.

The whiteboard is constructed directly: fallback must never recurse through dispatch.
No provider is called here; workers consume the same persisted plan and local props.
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import math
import re
import textwrap
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageOps

from .. import library
from ..director.v3.semantics import ACTION_CUES, beats, mentions, name_key
from .atmos import Atmosphere, compose
from .bold import MotionElement, MotionScene, Palette, render_frame, render_transition
from .bold.render import _SceneLayers
from .creatures import Genome, Action, raster
from .creatures.actions import ACTIONS, add, cue_pose, target_response, travel_x
from .creatures.draw import H as RIG_HEIGHT

TRAVEL_MARGIN = .03  # share of the frame width a walking or running actor keeps clear of the right edge
NEGATED_ACTION = re.compile(r"\b(?:never|cannot|no\s+longer)\b|\bnot\b(?!\s+only\b)|\b\w+n['’]t\b", re.I)


def camera_move(image, zoom, dx, dy, fill):
    """Zoom about the centre and pan by (dx, dy), uncovered edges in `fill`."""
    w, h = image.size
    inv = 1 / zoom
    return image.transform((w, h), Image.AFFINE, (inv, 0, w / 2 * (1 - inv) + dx, 0, inv, h / 2 * (1 - inv) + dy),
                           Image.BICUBIC, fillcolor=fill)


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
        self._travelled = {}
        self.ctx, self.els, self.cap_words = whiteboard.ctx, whiteboard.els, whiteboard.cap_words
        self.warnings = list(whiteboard.warnings)
        self.by_id = {b['id']: b for b in beats(episode, lang)}
        self.cast = {c['id']: cast_genome(c) for c in plan['cast']}
        for c in plan['cast']:
            if c['family'] not in ('feline', 'canine', 'human', 'other'):
                self.warnings.append(f"hybrid: cast family {c['family']} uses quadruped fallback")
            dropped = set(c['marks']) - set(self.cast[c['id']].marks) - {'none'}
            if dropped:
                self.warnings.append(f"hybrid: cast {c['id']} unsupported marks {sorted(dropped)}")
        self.style = plan['style']
        # Captions over motion scenes take the palette (its ink in a thin outline of its background, the word being
        # said in its accent) instead of the whiteboard's dark letters in a thick white outline, which smear on a
        # dark palette. Whiteboard scenes keep the whiteboard's own captions.
        palette = {k: ImageColor.getrgb(v)[:3] for k, v in self.style['palette'].items()}
        self.caption_look, self.caption_accent = (palette['ink'], palette['background'], 4), palette['accent']
        # Same score selection as finish; the decoded recording starts on beat zero.
        from ..audio import score
        self.score_beats = np.array([])
        if self.style['music_mood'] != 'none' and episode.get('music', True):
            mood = self.style['music_mood']
            bpm = (score.tags()[score.choose(mood, self.style['tempo_bpm'])]['bpm']
                   if any(mood in tag['moods'] for tag in score.tags().values()) else self.style['tempo_bpm'])
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

    def _prepare(self, span, project_dir):
        spec = span.spec
        duration = span.end - span.start
        treatment = spec['treatment']
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
        for e in spec['elements']:
            if e['kind'] == 'picture' and not span.diagram:
                try:
                    path = library.resolve(e['ref'], Path(project_dir))
                    elements.append(MotionElement(kind='picture', svg=path.read_text(encoding='utf-8'), width=600, height=450,
                                                  preserve_svg_palette=e['ref'].startswith('gen-')))
                except (OSError, KeyError, ValueError, AttributeError):
                    self.warnings.append(f"hybrid: missing prop {e['ref']}; unavailable picture omitted")
        text_kind, ref = spec['text']['kind'], spec['text']['ref']
        source = self.by_id.get(ref)
        numeric_chart = treatment == 'chart' and any(v.get('type') in ('bars', 'line', 'stat', 'grid100')
            for bid in spec['beat_ids'] for v in self.by_id[bid]['visuals'])
        if text_kind == 'quote':
            quotes = [v for v in source['visuals'] if v.get('type') == 'quote'] if source else []
            value = quotes[0] if quotes else {}
            body = self._label(value.get('text')) or (source['text'] if source else text)
            who = self._label(value.get('who'))
            atomic = '“' + body + '”'
            if not span.source_character:
                atomic = '\n'.join(textwrap.wrap(atomic, 48))
            atomic += '\n— ' + who if who else ''
            elements.append(MotionElement(text=atomic, preset='corner_caption', width=1450, size=64))
            if span.source_character and source:
                elements[-1].start = self._source_text_start(span, source, body)
                elements[-1]._quote_source = (source, body)
        for e in spec['elements']:
            if not span.diagram and not numeric_chart and e['kind'] == 'text' and e['ref'] in self.by_id and (e['ref'] != ref or text_kind in ('none', 'caption_only')):
                elements.append(MotionElement(text=self.by_id[e['ref']]['text'], width=1450, size=72,
                                              preset='type_on' if treatment == 'kinetic_type' else 'word_pop'))
                if span.source_character:
                    elements[-1].start = self._source_text_start(span, self.by_id[e['ref']])
        if not span.diagram and not numeric_chart and text_kind not in ('none', 'caption_only', 'quote'):
            words = source['text'] if source else text
            elements.append(MotionElement(text=words, preset='counter' if text_kind == 'counter' else
                'type_on' if treatment == 'kinetic_type' else 'word_pop', width=1500, size=72,
                y=.25 if elements and spec['composition'] not in ('grid', 'split') else None))
            if text_kind == 'counter':
                number = re.search(r'(?<!\w)(-?\d[\d,]*(?:\.\d+)?)(%)?', words)
                if number:
                    elements[-1].value_to = float(number[1].replace(',', ''))
                    elements[-1].suffix = number[2] or ''
                    elements[-1].decimals = len(number[1].split('.')[1]) if '.' in number[1] else 0
                    elements[-1].duration = min(1.8, max(.1, duration - .4))
                else:
                    self.warnings.append('hybrid: counter without numeric data uses readable source text')
                    elements[-1].preset = 'type_on'
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
            pictures = [e for e in elements if e.kind == 'picture']
            copy_elements = [e for e in elements if e.kind == 'text' and e.preset not in ('corner_caption', 'counter')]
            # Source copy remains verbatim, but line breaks give kinetic headlines
            # enough ink to read and move; a prop gets its own space below the copy.
            for e in copy_elements:
                e.text = '\n'.join(textwrap.wrap(e.text, 36, break_long_words=False))
                e.size = 96
            if pictures and copy_elements and spec['composition'] not in ('grid', 'split', 'full_bleed'):
                for e in copy_elements:
                    e.y, e.width = .23, 1400
                for e in pictures:
                    e.y = .60
        camera = 'static'  # Camera is applied to the whole composed scene, including creatures/atmospheres.
        transition = spec['transition_in']
        span.motion = MotionScene(elements, duration=max(.01, duration), composition='center' if
            spec['composition'] == 'stage' else spec['composition'], camera=camera,
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
        elif spec['composition'] in ('grid', 'split'):
            cols = 2 if spec['composition'] == 'split' else math.ceil(math.sqrt(max(1, len(elements) + len(self._cast_groups(span)))))
            rows = math.ceil(max(1, len(elements) + len(self._cast_groups(span))) / cols)
            for i, element in enumerate(elements):
                element.x, element.y = (i % cols + .5) / cols, (i // cols + .5) / rows
                element.width = min(element.width, 1920 / cols * .8)
                element.height = min(element.height, 1080 / rows * .65)

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
            e.size = 48
            if not quote:
                # A label is a verbatim source excerpt; narration and timed captions
                # retain every word. Do not let a paragraph consume the cast stage.
                sentence = re.split(r'(?<=[.!?])\s+', e.text.strip(), maxsplit=1)[0]
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
            if not quote and len(wrapped.splitlines()) > rows:
                wrapped = '\n'.join(wrapped.splitlines()[:rows])
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

    @staticmethod
    def _pan(span, local, w):
        """A pan camera's horizontal offset at this point of the span; negative moves the picture right."""
        u = min(1., local / max(.01, span.end - span.start))
        camera = span.spec['camera']
        return (65 * u if camera == 'pan_right' else -65 * u if camera == 'pan_left' else 0) * w / 1920

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
        self._travelled = {}
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
            # Travel carries the actor rightward but never past a margin at the frame edge, counted after pan_left
            # moves the picture right; the follow camera reads the same clamped distance from self._travelled.
            travel = self._travel(span, key, local, sprite_height)
            travel = min(travel, max(0., w * (1 - TRAVEL_MARGIN) + min(0., self._pan(span, local, w))
                                     - (x * w + move + sprite.width / 2)))
            self._travelled[key] = travel
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
        self._travelled = {}
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
                # Leave room for the authored idle sway and the whole-scene pan.
                right = x * w + bbox[2] - 300 * scale
                destination = next((target for actor, a, target in span.actions
                                    if actor == key and a.name == 'walk' and target in span.actor_layout), None)
                direction = -1 if destination and span.actor_layout[destination][0] < x else 1
                left = x * w + bbox[0] - 300 * scale
                room = (max(0., left - w * TRAVEL_MARGIN - max(0., self._pan(span, local, w)) - 60 * floor)
                        if direction < 0 else
                        max(0., w * (1 - TRAVEL_MARGIN) + min(0., self._pan(span, local, w)) - right - 60 * floor))
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
                self._travelled[key] = direction * travel
                x += direction * travel / w
                # Pounces, jaw/head action and idle sway also need the complete
                # silhouette inside the final camera's safe edges.
                left = x * w + bbox[0] - 300 * scale
                right = x * w + bbox[2] - 300 * scale
                panel = not self.square and len(self._cast_groups(span)) == 1
                left_stage, right_stage = ((.04, .50) if span.spec['composition'] == 'left_third' else (.50, .96)) if panel else (TRAVEL_MARGIN, 1 - TRAVEL_MARGIN)
                low = w * left_stage + max(0., self._pan(span, local, w))
                high = w * right_stage + min(0., self._pan(span, local, w))
                x += (max(0., low - left) - max(0., right - high)) / w
                # Retain the SVG's ground/root anchor. Recentring each cropped pose
                # used to cancel body translation and make interacting actors icons.
                sprite = sprite.crop(bbox)
                image.paste(sprite, (round(x * w + bbox[0] - 300 * scale),
                                     round(ground * h + bbox[1] - 358 * scale)), sprite)
        return image

    def _frame(self, span, t, *, quotes=True):
        spec, local = span.spec, max(0, t - span.start)
        if span.source_proof or spec['treatment'] == 'whiteboard' or (spec['treatment'] == 'character' and not span.actors):
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
        camera = spec['camera']
        u = min(1., local / max(.01, span.end - span.start))
        zoom = 1 + .045 * u if camera == 'slow_push' else 1.045 - .045 * u if camera == 'pull_back' else 1.
        dx = self._pan(span, local, w)
        dy = 0.
        if camera == 'follow':
            # Track the moving foreground group; a fixed group focus avoids a
            # camera jump when a finite action ends.
            targets = [a for a in span.actors if not a.startswith('crowd-hyena-')]
            if targets:
                from .creatures.actions import action_pose
                xs = []
                for actor in targets:
                    x = self._actor_slot(span, actor)[0]
                    x += sum(action_pose(a, local).dx for key, a, _ in span.actions if key == actor) / 600
                    x += self._travelled.get(actor, 0.) / w
                    xs.append(x)
                dx = (sum(xs) / len(xs) - .5) * w * .35
            elif span.motion.elements:
                from .bold.render import element_pose
                xs = [element_pose(span.motion, e, i, local)[0] for i, e in enumerate(span.motion.elements)]
                dx = (sum(xs) / len(xs) / 1920 - .5) * w * .35
            zoom = 1.06
            if span.source_character and not self.square and len(self._cast_groups(span)) == 1:
                # A side panel's text is pinned; keep the focus from carrying its
                # actor into that text area. Travel remains visible in the stage.
                dx = max(0., dx) if spec['composition'] == 'left_third' else min(0., dx)
        if camera == 'shake':
            strength = 2 * self.style['energy'] * math.exp(-local * 4) * (h / 1080 if self.native else 1)
            dx, dy = strength * math.sin(local * 39), strength * math.sin(local * 31)
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

    def frame(self, t):
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
                current = self.whiteboard.frame(t).convert('RGB')
                array = render_transition(np.asarray(previous), np.asarray(current), t - end_start,
                                          *self.size, kind='match', duration=last.join_length)
                image = Image.fromarray(array).convert('RGBA')
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
        if span.scientific or (i and self.spans[i - 1].scientific):
            # Scientific panels follow the source clock and retain their exact
            # canvas/axis transform through both sides of every scene boundary.
            image = self._frame(span, t)
        elif span.diagram and t >= span.diagram.window[0]:
            # The spoken glide cue owns these panels. A score-delayed join must
            # not hide their labels or substitute the previous scene.
            image = self._frame(span, t)
        elif i and local < 0:
            image = self._frame(self.spans[i - 1], min(t, span.start - 1 / 30), quotes=False)
        else:
            image = self._frame(span, t)
            if i and kind != 'cut' and local < span.join_length:
                previous = self._frame(self.spans[i - 1], span.start - 1 / 30, quotes=False)
                array = render_transition(np.asarray(previous), np.asarray(image), local, *self.size,
                                          kind=kind, duration=span.join_length)
                image = Image.fromarray(array)
        image = image.convert('RGBA')
        if not self.vertical:
            self.whiteboard._caption(image, t, self.caption_look, self.caption_accent)
        return image.convert('RGB')

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
            for j, (actor, action, target) in enumerate(span.actions):
                # An action with its own synthesized sound (audio.synth_sfx) plays it, at full strength: the kind's
                # level keeps it audible under the narration. A pounce lands with an impact.
                kind = {'roar': 'roar', 'whimper': 'whimper', 'nudge': 'nudge', 'swipe': 'swipe', 'laugh': 'hyena_cackle',
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

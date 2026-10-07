"""Offline v3 plans: reuse the rules pictures, then choose a genre's scene grammar."""
from __future__ import annotations

import copy
import re

from ..rules import RulesDirector as PictureDirector
from ..validate import _doodles
from .schema import SCENE, SKINS
from .semantics import actions, atmosphere, beats, candidate_ids, detect_cast, mentions
from .story import STORY_PALETTE, read_beats, story_picture
from .validate import _default, validate
from ...engine.source_diagrams import resolve as resolve_diagram


def detect_genre(text: str) -> str:
    text = text.lower()
    if re.search(r'\b(introducing|product launch|launching|sign up|try it|saas|our new app)\b', text):
        return 'launch/promo'
    if re.search(r'\b(lesson|exercise|solve|equation|learning objective|practice problem|quiz)\b', text):
        return 'lesson'
    if re.search(r'\b(news|reported|report shows|survey|latest figures|according to|quarterly|inflation)\b', text):
        return 'news/data'
    if re.search(r'\b(once upon a time|cub|tigress|roared|whimpered|said|whispered)\b', text):
        return 'story'
    if re.search(r'\b(poem|poetry|verse|stanza)\b', text):
        return 'poem'
    return 'explainer'


def from_rules(board: dict, candidates=None) -> dict:
    """Convert an existing rules storyboard to v3; leave its beats and visuals untouched.

    Omitted candidates mean the rules' picked pictures are the offered set. Supplied candidates restrict
    each scene's pictures. The adapter keeps richer rules charts that a picture-reference list cannot encode.
    """
    script = beats(board)
    lang = board.get('lang', 'en')
    title = board.get('title', {})
    title = title.get(lang, '') if isinstance(title, dict) else title
    text = '\n'.join(b['text'] for b in script)
    genre = detect_genre(title + '\n' + text)
    cast = detect_cast(script)
    story = genre == 'story'
    reading = read_beats(script, cast) if story else {}
    if candidates is None:
        candidates = {b['id']: list(_doodles(b['visuals'])) for b in script}
    mode = {'story': 'hybrid', 'explainer': 'hybrid', 'lesson': 'whiteboard'}.get(genre, 'motion')
    dark = mode == 'motion'
    palette = ({'background': '#0C0C0C', 'ink': '#E7E5D8', 'accent': '#E4AB55', 'accent2': '#8B9BC9'} if dark else
               {'background': '#FFFFFF', 'ink': '#1B1B1B', 'accent': '#287FA3', 'accent2': '#D39B36'})
    if story:
        # Children's and narrative stories are picture books on the whiteboard paper, never a dark night sky.
        palette = dict(STORY_PALETTE)
    if genre == 'lesson':
        palette = {'background': '#24342C', 'ink': '#F3F1E8', 'accent': '#77B5CF', 'accent2': '#AC894C'}
    energetic = genre == 'launch/promo'
    sections = list(dict.fromkeys(b['section'] for b in script))
    plan = {
        'storyboard': {'genre': genre, 'audience': 'students' if genre == 'lesson' else
                      'customers' if energetic else 'general audience',
                      'arc': {'beginning': script[0]['text'] if script else '',
                              'turn': script[len(script) // 2]['text'] if script else '',
                              'end': script[-1]['text'] if script else ''},
                      'recurring_motif': cast[0]['name'] if cast else title or 'the central idea',
                      'sections': [{'section_id': sid,
                                    'intent': next(b['text'] for b in script if b['section'] == sid)} for sid in sections]},
        'style': {'mode': mode, 'whiteboard_skin': board['look'] if genre in ('explainer', 'story') and board.get('look') in SKINS else
                  'chalkboard' if genre == 'lesson' else 'whiteboard',
                  'palette': palette, 'type': 'hand' if genre in ('lesson', 'explainer') else
                  'serif' if genre == 'poem' else 'display' if energetic else 'rounded',
                  'energy': 5 if energetic else 2 if genre in ('lesson', 'poem') else 3,
                  'motion_floor': 'lively' if energetic else 'breathing' if genre == 'story' else 'drifting',
                  'transition_family': 'page' if genre == 'lesson' else 'morph' if genre in ('poem', 'story') else 'match',
                  'music_mood': 'uplifting' if energetic else 'none' if genre == 'lesson' else
                  'dramatic' if genre == 'story' else 'calm' if genre == 'poem' else 'curious',
                  'tempo_bpm': 120 if energetic else 72 if genre == 'poem' else 96,
                  'pacing': 'brisk' if energetic else 'calm' if genre in ('lesson', 'poem') else 'steady',
                  'reason': {'story': 'Named beings act within a moving setting.',
                             'explainer': 'Build explanations on the board and emphasize key claims with type.',
                             'launch/promo': 'Smooth panels and kinetic claims carry launch energy.',
                             'lesson': 'Draw each explanatory step before introducing the next.',
                             'news/data': 'Charts show the reported numbers with motion between claims.',
                             'poem': 'Drifting atmosphere and sparse type follow the verse.'}[genre]},
        'cast': cast, 'scenes': [],
    }
    for i, b in enumerate(script):
        scene = _default(SCENE)
        atmo = atmosphere(b['text'])
        acting = actions(b, cast)
        named = [c['id'] for c in cast if mentions(c['name'], b['spoken'])]
        key = b['kind'] in ('title', 'opener', 'take') or bool(re.search(r'\b(key|remember|means|therefore)\b', b['text'], re.I))
        if genre == 'lesson':
            treatment = 'whiteboard'
        elif genre == 'story':
            treatment = 'character' if acting else 'atmosphere' if atmo != 'none' else 'character' if named else 'motion'
        elif genre == 'explainer':
            treatment = 'kinetic_type' if key else 'whiteboard'
        elif genre == 'news/data':
            treatment = 'chart' if re.search(r'\d|percent|out of', b['text'], re.I) else 'motion'
        elif genre == 'poem':
            treatment = 'atmosphere' if atmo != 'none' else 'kinetic_type'
        else:
            treatment = 'kinetic_type' if i == 0 or key or re.search(r'\b(try|start|join|sign up)\b', b['text'], re.I) else 'motion'
        picked = list(dict.fromkeys(_doodles(b['visuals'])))
        offered = candidate_ids(candidates, b['id'])
        scene.update(beat_ids=[b['id']], treatment=treatment,
                     composition='stage' if treatment == 'character' else 'full_bleed' if treatment == 'atmosphere' else
                     'grid' if treatment == 'chart' else 'center',
                     elements=[{'kind': 'picture', 'ref': p} for p in picked if p in offered],
                     actions=acting, atmosphere={'kind': atmo, 'density': .55 if atmo != 'none' else 0},
                     camera='follow' if any(a['verb'] in ('walk', 'run') for a in acting) else
                     'slow_push' if genre in ('story', 'poem') else 'static',
                     transition_in='cut' if i == 0 else plan['style']['transition_family'],
                     hold_s=max(1.5, len(b['text']) / 27),
                     text={'kind': 'kinetic' if treatment == 'kinetic_type' else 'counter' if treatment == 'chart' else
                           'title' if b['kind'] in ('title', 'opener') else 'caption_only', 'ref': b['id']})
        diagram = resolve_diagram(board, b['id'])
        if diagram:
            scene['elements'] = [{'kind': 'diagram', 'ref': b['id']}]
            scene['treatment'] = 'whiteboard' if diagram.kind == 'dots' else 'motion'
            scene['text'] = {'kind': 'caption_only', 'ref': b['id']}
            scene['camera'] = 'static'
        if story and not diagram:
            _story_scene(scene, b, reading[b['id']])
        elif treatment == 'character' and not diagram:
            scene['elements'] = [{'kind': 'cast', 'ref': cid} for cid in named]
        if atmo != 'none':
            scene['elements'].append({'kind': 'atmosphere', 'ref': atmo})
        plan['scenes'].append(scene)
    if any(v.get('type') == 'scientific' for b in script for v in b['visuals']):
        plan['style']['mode'] = 'hybrid'
        for scene in plan['scenes']:
            if any(v.get('type') == 'scientific' for bid in scene['beat_ids']
                   for v in next(b for b in script if b['id'] == bid)['visuals']):
                scene.update(treatment='chart', elements=[], actions=[], camera='static',
                             atmosphere={'kind': 'none', 'density': 0}, transition_in='cut',
                             text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    return validate(plan, board, candidates)[0]


def _story_scene(scene, beat, lines):
    """One picture-book page: everyone on stage in the beat's sentences, its setting doodles, captions only."""
    cast = list(dict.fromkeys(cid for line in lines for cid in line.present))
    # Offered doodles that can stand in the story's world; setting nouns (river, moon) are drawn from the text.
    pictures = [e['ref'] for e in scene['elements'] if e['kind'] == 'picture' and story_picture(e['ref'])]
    scene['elements'] = ([{'kind': 'cast', 'ref': cid} for cid in cast] +
                         [{'kind': 'picture', 'ref': ref} for ref in dict.fromkeys(pictures)])
    scene['treatment'] = ('character' if cast else 'atmosphere' if scene['atmosphere']['kind'] != 'none'
                          else 'motion')
    scene['composition'] = 'stage' if cast else 'full_bleed' if scene['treatment'] == 'atmosphere' else 'center'
    scene['camera'] = 'follow' if any(a['verb'] in ('walk', 'run') for a in scene['actions']) else 'slow_push'
    # Captions only: the storybook titles its first page itself (story.titled), so no narration line is ever
    # handwritten as a heading if a page is switched to the whiteboard treatment.
    scene['text'] = {'kind': 'caption_only', 'ref': beat['id']}


class RulesDirector:
    def __init__(self, lang='en'):
        self.lang = lang

    def direct(self, board: dict, candidates=None) -> dict:
        draft = PictureDirector(self.lang).direct(copy.deepcopy(board))
        return from_rules(draft, candidates)

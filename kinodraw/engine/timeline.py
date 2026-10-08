"""Timeline layout shared by real audio assembly and synthetic previews.

Given each beat's measured clip length and per-character speech times, place
beats on the master clock, insert chapter gaps, take reading holds and gem
transition time, then derive captions, chapters, music intervals, the end card and the credit.

``pauses`` (beat id -> seconds, from render.pacing) add silence after a beat so the
narration waits for the drawing hand instead of rushing or skipping pictures. A takeaway
beat starts TAKE_PREROLL after the beat before it: the camera moves to the note and the
note is laid down first, so "Key takeaway: ..." is said while its words are written.
"""
from __future__ import annotations

import re

from . import captions as cap
from . import skin
from .storyboard import normalize
from .. import speech

FPS = 30
CHAPTER_GAP = .6
TRANSITION = .35         # quick pullback, pin and agenda settle
END_CARD = 5.0            # pan to the closing page, write it, and let it be read
CREDIT = 2.0              # then "Made with ..." under it (the project's credit setting can turn it off)
ZH_DWELL = .5             # extra reading pause per Mandarin paragraph (9/19 precedent)
ZOOM_IN = .35             # first part of each section: zoom into its agenda card
TAKE_PREROLL = .15        # start the note's camera move just before its words
OVERLAP = .2              # a line that breaks off ("Dad, turn it off—"): the next speaker comes in this much early


class Pacing(dict):
    """Ordinary capped breaths plus measured preparation for deficient takeaways.

    Takeaway preparation is separate from post-speech pauses: its artwork starts
    during the preceding narration, and only the measured shortfall delays speech.
    ``layout`` serializes that plan into each affected beat for the renderer.
    """
    def __init__(self):
        super().__init__()
        self.takeaways = {}


def _cue_options(episode, lang):
    look_skin = skin.for_look(episode.get('look'))
    if not (look_skin.textured and lang in ('en', 'es', 'zh')):
        return {}

    def fits(text, lang):
        lines, size = skin.caption_layout(text, lang, look_skin)
        kind = 'en_caption' if lang != 'zh' else 'zh_caption'
        return len(lines) <= 2 and all(skin._run_width(line, kind, size, look_skin.fonts) <= 1640 for line in lines)
    return {'fits': fits}


def word_times(episode, tline, lang):
    """When each caption's words are said: its own 'words' (layout() stores them), or for a timeline laid out before
    captions carried them, the times layout() would have given, from the same measured character times (None for a
    cue it cannot match). The timeline is not changed."""
    if all('words' in c for c in tline['captions']):
        return [c['words'] for c in tline['captions']]
    episode = normalize(episode)
    cue_options, found = _cue_options(episode, lang), {}
    labels = speech.screenplay_labels(b['display'][lang] for b in episode['beats'])
    for beat in episode['beats']:
        info = tline['beats'].get(beat['id'])
        if not info or not info.get('char_times'):
            continue
        ct, start = info['char_times'], info['start']
        for a, _, text, words in _cues(beat, lang, lambda pos: ct[min(max(pos, 0), len(ct) - 1)],
                                       info['speech_end'] - start, labels, cue_options):
            found.setdefault(text, []).append((start + a, [round(start + w, 4) for w in words]))
    return [c.get('words') or next((words for at, words in found.get(c['text'], ()) if abs(at - c['start']) < .001),
                                   None) for c in tline['captions']]


def _cues(beat, lang, char_time, speech_end, labels, cue_options, bubbled=()):
    """A beat's caption cues: its written words without speaker labels, stage directions, emoji or Markdown, each
    word timed by its spoken characters. A silent beat (a title card, a direction) has none. ``bubbled``: the spoken
    ranges a speech bubble shows, which the caption leaves to the bubble."""
    if beat.get('silent'):
        return []
    said, shown, index = speech.captions(beat['spoken'][lang], beat['display'][lang], labels, bubbled, lang)
    if not said.strip() or not shown.strip():
        return []
    return cap.cues_for_beat(said, shown, lang, lambda pos: char_time(index[min(max(pos, 0), len(index) - 1)]),
                             speech_end, words=True, **cue_options)


def take_hold(beat, lang):
    return .05            # the note is read during its narration, then pinned immediately


def layout(episode, lang, clips, pauses=None, credit=True, bubbled=None):
    """clips[beat_id] = {'speech': seconds of speech incl. trailing clip gap, 'char_times': [...]};
    pauses[beat_id] = seconds of silence after that beat (pacing); bubbled[beat_id] = [(start, end)] of its spoken
    text that a speech bubble shows (left out of the caption)."""
    pauses = {} if pauses is None else pauses
    takeaways = getattr(pauses, "takeaways", {})
    episode = normalize(episode)
    cue_options = _cue_options(episode, lang)
    labels = speech.screenplay_labels(b['display'][lang] for b in episode['beats'])
    beats = episode['beats']
    chapters = {c['id']: c for c in episode['chapters']}
    cursor = 0.
    out_beats, order, transitions, capts = {}, [], [], []
    used_pauses = {}
    n_cards = sum(c['kind'] == 'section' for c in episode['chapters'])
    for i, beat in enumerate(beats):
        clip = clips[beat['id']]
        take = beat.get('kind') == 'take' and chapters[beat['chapter']]['kind'] == 'section'
        prep = cursor
        delay = max(0., float(takeaways.get(beat['id'], 0.))) if take else 0.
        start = cursor + (TAKE_PREROLL + delay if take else 0.)
        before = clips[beats[i - 1]['id']] if i else None
        if (before and before.get('cut_off') and not take and clip.get('speakers')
                and clip['speakers'][0] != before['speakers'][-1]):
            # Interrupted: the next speaker comes in over the end of the line that breaks off.
            previous = out_beats[order[-1]]
            start = max(previous['start'], previous['start'] + before['duration'] - OVERLAP)
            previous['end'] = round(start, 4)
            for c in capts:
                c['end'] = min(c['end'], round(start, 4))
        speech_end = start + clip['speech']
        pause = min(.1, max(0., float(pauses.get(beat['id'], 0.))))
        if pause:
            used_pauses[beat['id']] = round(pause, 3)
        end = speech_end + (ZH_DWELL if lang == 'zh' else 0.) + pause
        nxt = beats[i + 1] if i + 1 < len(beats) else None
        chapter_change = nxt is not None and nxt['chapter'] != beat['chapter']
        info = {'start': round(start, 4), 'speech_end': round(speech_end, 4), 'char_times': clip['char_times']}
        if take:
            info['prep'] = round(prep, 4)
            if beat['id'] in takeaways:
                info['takeaway_delay'] = delay
            hold = take_hold(beat, lang)
            hold_end = end + hold
            t_end = hold_end + TRANSITION
            transitions.append({'section': beat['chapter'], 'take_beat': beat['id'], 'speech_end': round(end, 4),
                                'hold_end': round(hold_end, 4), 'end': round(t_end, 4),
                                'next': nxt['chapter'] if nxt else None})
            end = t_end
        elif chapter_change:
            end += CHAPTER_GAP
        info['end'] = round(end, 4)
        out_beats[beat['id']] = info
        order.append(beat['id'])
        ct = clip['char_times']

        def char_time(pos, ct=ct):
            return ct[min(max(pos, 0), len(ct) - 1)] if ct else 0.
        for a, b, text, words in _cues(beat, lang, char_time, clip['speech'] - .15, labels, cue_options,
                                       (bubbled or {}).get(beat['id'], ())):
            capts.append({'start': round(start + a, 4), 'end': round(start + b, 4), 'text': text,
                          'words': [round(start + w, 4) for w in words]})
        cursor = end
    tail = END_CARD + (CREDIT if credit else 0.)
    duration = cursor + tail
    duration = round(-(-duration * FPS // 1) / FPS, 6)
    chaps = []
    for c in episode['chapters']:
        ids = [b['id'] for b in beats if b['chapter'] == c['id']]
        label = (c.get('label') or {}).get(lang, '').strip()
        title = (c.get('title') or {}).get(lang, '').strip()
        chaps.append({'id': c['id'], 'start': out_beats[ids[0]]['start'], 'end': out_beats[ids[-1]]['end'],
                      'title': f'{label} · {title}' if n_cards > 1 and c['kind'] not in ('intro', 'outro', 'agenda') and label
                      and title and title.lower() != label.lower() else (label or title)})
    # Music: flagged beats, section transitions (pull-back onward) and the end card.
    music = []
    for beat in beats:
        if beat.get('music'):
            info = out_beats[beat['id']]
            music.append([info['start'], info['end']])
    for tr in transitions:
        music.append([tr['hold_end'], tr['end']])
    music.append([duration - tail, duration])
    music.sort()
    merged = []
    for a, b in music:
        if merged and a <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return {'language': lang, 'fps': FPS, 'duration': duration, 'beats': out_beats, 'beat_order': order,
            'pauses': used_pauses,
            'captions': capts, 'chapters': chaps, 'transitions': transitions,
            'music': [{'start': round(a, 4), 'end': round(b, 4)} for a, b in merged],
            'end_card': {'start': round(duration - tail, 4), 'end': duration},
            'credit': {'start': round(duration - CREDIT, 4), 'end': duration} if credit else None}


def synthetic_clips(episode, lang):
    """Reading-rate estimate for previews only (EN ~2.45 words/s, ZH ~4.4 chars/s)."""
    clips = {}
    for beat in episode['beats']:
        text = beat['spoken'][lang]
        if lang in ('en', 'es'):
            seconds = max(2.0, len(text.split()) / 2.45)
        else:
            seconds = max(2.0, len(re.findall(r'[一-鿿]', text)) / 4.4 + len(re.findall(r'[A-Za-z]+', text)) * .25)
        n = len(text)
        clips[beat['id']] = {'speech': seconds + .45, 'char_times': [round(seconds * k / max(1, n), 3) for k in range(n)]}
    return clips

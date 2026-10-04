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

FPS = 30
CHAPTER_GAP = .6
TRANSITION = 2.8          # pull back 0.35 + fly/pin 0.9 + check 0.7 + circle 0.8 (+ slack)
END_CARD = 5.0            # pan to the closing page, write it, and let it be read
CREDIT = 2.0              # then "Made with ..." under it (the project's credit setting can turn it off)
ZH_DWELL = .5             # extra reading pause per Mandarin paragraph (9/19 precedent)
ZOOM_IN = .9              # first part of each section: zoom into its agenda card
AGENDA_CARD = 2.6         # hand time per agenda card: the agenda holds until every card is drawn
TAKE_PREROLL = 2.0        # pan to the takeaway page and lay the note down before it is read out


def take_hold(beat, lang):
    head = (beat.get('take') or {}).get('headline', {}).get(lang, '')
    if lang in ('en', 'es'):
        return max(3.0, len(head.split()) / 3.0)
    return max(3.0, len(re.findall(r'[一-鿿A-Za-z0-9]', head)) / 6.0)


def layout(episode, lang, clips, pauses=None, credit=True):
    """clips[beat_id] = {'speech': seconds of speech incl. trailing clip gap, 'char_times': [...]};
    pauses[beat_id] = seconds of silence after that beat (pacing)."""
    pauses = pauses or {}
    episode = normalize(episode)
    cue_options = {}
    look_skin = skin.for_look(episode.get('look'))
    if look_skin.textured and lang in ('en', 'zh'):
        def fits(text, lang):
            lines, size = skin.caption_layout(text, lang, look_skin)
            kind = 'en_caption' if lang == 'en' else 'zh_caption'
            return len(lines) <= 2 and all(skin._run_width(line, kind, size, look_skin.fonts) <= 1640
                                          for line in lines)
        cue_options['fits'] = fits
    beats = episode['beats']
    chapters = {c['id']: c for c in episode['chapters']}
    cursor = 0.
    out_beats, order, transitions, capts = {}, [], [], []
    n_cards = sum(c['kind'] == 'section' for c in episode['chapters'])
    agenda_start = None
    for i, beat in enumerate(beats):
        clip = clips[beat['id']]
        take = beat.get('kind') == 'take' and chapters[beat['chapter']]['kind'] == 'section'
        prep = cursor
        start = cursor + (TAKE_PREROLL if take else 0.)
        speech_end = start + clip['speech']
        end = speech_end + (ZH_DWELL if lang == 'zh' else 0.) + float(pauses.get(beat['id'], 0.))
        nxt = beats[i + 1] if i + 1 < len(beats) else None
        chapter_change = nxt is not None and nxt['chapter'] != beat['chapter']
        info = {'start': round(start, 4), 'speech_end': round(speech_end, 4), 'char_times': clip['char_times']}
        if take:
            info['prep'] = round(prep, 4)
            hold = take_hold(beat, lang)
            hold_end = end + hold
            t_end = hold_end + TRANSITION
            transitions.append({'section': beat['chapter'], 'take_beat': beat['id'], 'speech_end': round(end, 4),
                                'hold_end': round(hold_end, 4), 'end': round(t_end, 4),
                                'next': nxt['chapter'] if nxt else None})
            end = t_end
        elif chapter_change:
            end += CHAPTER_GAP
        if chapters[beat['chapter']]['kind'] == 'agenda':
            agenda_start = start if agenda_start is None else agenda_start
            if chapter_change:                           # short agenda narration: wait for the cards
                end = max(end, agenda_start + 1.4 + AGENDA_CARD * n_cards + CHAPTER_GAP)
        info['end'] = round(end, 4)
        out_beats[beat['id']] = info
        order.append(beat['id'])
        ct = clip['char_times']

        def char_time(pos, ct=ct):
            return ct[min(max(pos, 0), len(ct) - 1)] if ct else 0.
        for a, b, text in cap.cues_for_beat(beat['spoken'][lang], beat['display'][lang], lang, char_time,
                                           clip['speech'] - .15, **cue_options):
            capts.append({'start': round(start + a, 4), 'end': round(start + b, 4), 'text': text})
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
                      'title': f'{label} · {title}' if c['kind'] not in ('intro', 'outro', 'agenda') and label
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
            'pauses': {k: round(float(v), 3) for k, v in pauses.items() if v},
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

"""Procedural or mood-selected CC0 score, bar-aligned loops and narration sidechain.

render() returns the quiet, ducked music stem, the mastered narration/music mix and its beat grid. With
track='procedural' the score is synthesized (audio/procedural.py) at the requested tempo, changing at section
starts and swelling or hushing at intensity marks. Otherwise a recording plays: the named one, or the one the
mood and requested tempo select, or your own (an Own track); bpm and beats then describe its measured tempo,
without repitching it. Measurements in assets/music/score_tags.json are made once with scripts/measure_bpm.py,
including its analysis delay; an own track is measured the same way (audio/tempo.py) when it is added
(pipeline.set_music). Every source starts at its first downbeat, so the output's beat and bar grids start at zero.
source() is the projects' choice: their own music file, a saved storyboard music track, else the procedural score.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

import numpy as np
from scipy.signal import butter, sosfilt

from . import master, mix, procedural

SR = mix.SR
TAGS = mix.MUSIC / 'score_tags.json'
DUCK_DB, ATTACK, RELEASE = -10.0, .08, .4
CHORDS = {'bright': (130.81, 164.81, 196.00), 'discovery': (146.83, 220.00, 261.63),
          'calm': (130.81, 196.00, 246.94), 'mysterious': (110.00, 130.81, 164.81),
          'somber': (130.81, 155.56, 196.00), 'neutral': (130.81, 174.61, 196.00)}
PROCEDURAL = 'procedural'
# Intensity marks from the sound cues: big actions swell into their cue (strength), gentle ones hush their line.
SWELLS = {'roar': 1., 'impact': .8, 'pounce': .8, 'swipe': .6, 'shooting_star': .5}
HUSHES = {'whimper': .8, 'nudge': .5}
TENDER = re.compile(r'\b(?:gentl[ey]|softly|quietly|whisper\w*|nuzzl\w*|hug(?:s|ged|ging)?|cuddl\w*|tears?|'
                    r'lullab\w*|tender\w*)\b', re.I)


@dataclass(frozen=True)
class Own:
    """Your own music file, copied into the project as music/<name> (pipeline.set_music), at its measured tempo."""
    file: str            # music/<name>, as the storyboard names it
    bpm: float
    downbeat: float      # seconds into the file
    path: Path           # the file itself


@dataclass
class Score:
    music: np.ndarray
    audio: np.ndarray
    beats: np.ndarray
    duck_gain: np.ndarray
    bpm: float
    track: str | None


@lru_cache(maxsize=1)
def tags() -> dict:
    return json.loads(TAGS.read_text(encoding='utf-8'))


def choose(music_mood, tempo_bpm) -> str:
    """Prefer a tagged mood, then the closest tempo; ties follow the filename."""
    _tempo(tempo_bpm)
    mood = music_mood.strip().lower()
    matches = [slug for slug, tag in tags().items() if mood in tag['moods']]
    return min(matches or tags(), key=lambda slug: (abs(np.log2(tags()[slug]['bpm'] / tempo_bpm)), slug))


def own(setting, project) -> Own | None:
    """The music file a storyboard's music setting names ({"file": "music/<name>", "bpm", "downbeat"}), in the
    project folder; None for any other setting. Only a file directly in the project's music folder is played."""
    if not isinstance(setting, dict) or 'file' not in setting:
        return None
    name = setting['file']
    parts = PurePosixPath(name).parts if isinstance(name, str) and '\\' not in name else ()
    if len(parts) != 2 or parts[0] != 'music' or parts[1] in ('.', '..') or parts[1].startswith('.'):
        raise ValueError('music file must be music/<name> in the project folder')
    bpm, downbeat = (float(setting.get(key, np.nan)) for key in ('bpm', 'downbeat'))
    _tempo(bpm)
    if not np.isfinite(downbeat) or downbeat < 0:
        raise ValueError('music downbeat must be a time in the file')
    return Own(name, bpm, downbeat, Path(project) / name)


def source(setting, music_mood, tempo_bpm, project='.') -> tuple[str | Own, float]:
    """(track, bpm) for a project: its own music file (an Own track in ``project``), or the recording a storyboard's
    music setting names ({"primary": slug}, which projects saved before the procedural score keep), at its measured
    tempo; otherwise the procedural score at the requested tempo. The renderer snaps joins to this grid and finish
    plays this track, so both use it."""
    _tempo(tempo_bpm)
    mine = own(setting, project)
    if mine:
        return mine, mine.bpm
    slug = setting.get('primary') if isinstance(setting, dict) else None
    if slug and slug != PROCEDURAL:
        if slug not in tags():
            raise ValueError(f'unknown music track {slug!r}')
        return slug, tags()[slug]['bpm']
    return PROCEDURAL, float(tempo_bpm)


def story_marks(board, tl, cues=()) -> tuple[list[float], list[tuple[float, float, float]]]:
    """Section starts (the chapter joins) and intensity marks (time, strength, span) for the procedural score.
    Roars and other big actions swell into their cue; a whimper or nudge, or a line said gently, softly or
    quietly (or a whisper, nuzzle, hug, cuddle, tear, lullaby), hushes for that beat's narration."""
    sections = [float(c['start']) for c in tl.get('chapters', [])[1:]]
    marks = [(float(c['t']), SWELLS[c['kind']], 0.) for c in cues if c.get('kind') in SWELLS]
    order = tl.get('beat_order') or [b['id'] for b in board.get('beats', [])]
    end = tl.get('end_card', {}).get('start', tl['duration'])
    spans = {bid: (tl['beats'][bid]['start'], tl['beats'][after]['start'] if after else end)
             for bid, after in zip(order, order[1:] + [None]) if bid in tl['beats']}
    lang = tl.get('language') or board.get('lang')
    for beat in board.get('beats', []):
        spoken = beat.get('spoken', '')
        text = spoken.get(lang, '') if isinstance(spoken, dict) else spoken
        if beat['id'] in spans and TENDER.search(text or ''):
            a, b = spans[beat['id']]
            marks.append((a, -.7, b - a))
    for c in cues:
        if c.get('kind') in HUSHES:
            a, b = next(((a, b) for a, b in spans.values() if a <= c['t'] < b), (c['t'], c['t'] + 2.))
            marks.append((a, -HUSHES[c['kind']], b - a))
    return sections, sorted(marks)


def _tempo(bpm):
    if not np.isfinite(bpm) or bpm <= 0:
        raise ValueError('tempo_bpm must be positive and finite')


def beat_grid(duration, tempo_bpm, phase=0.) -> np.ndarray:
    """Beat times in [0, duration), counting phase from the output audio's start."""
    _tempo(tempo_bpm)
    if not np.isfinite(duration) or duration < 0 or not np.isfinite(phase):
        raise ValueError('duration must be nonnegative and phase finite')
    beat = 60 / tempo_bpm
    return np.arange(phase % beat, duration, beat, dtype=np.float64)


def loop(audio, duration, tempo_bpm, phase=0., sr=SR) -> np.ndarray:
    """Exact length, with one-bar linear crossfades starting on bar lines. Silent tails are excluded.

    Each repeat starts at the source downbeat; its tail overlaps the next copy for a bar, leaving the repeat
    period an integer number of bars. Rounded positions come from seconds, avoiding accumulated sample drift.
    """
    beat_grid(duration, tempo_bpm, phase)
    audio = np.asarray(audio, np.float32)
    n = round(duration * sr)
    out = np.zeros((n, *audio.shape[1:]), np.float32)
    if not n:
        return out
    bar = 240 / tempo_bpm
    start = round((phase % bar) * sr)
    audible = np.flatnonzero(np.abs(audio).reshape(len(audio), -1).max(1) > 1e-3)
    end = int(audible[-1]) + 1 if len(audible) else len(audio)
    bars = int(np.floor((end - start) / sr / bar)) - 1
    if bars < 1:
        raise ValueError('music needs at least two audible bars after its downbeat')
    period, xf = bars * bar, round(bar * sr)
    piece = audio[start:start + round(period * sr) + xf]
    for repeat in range(int(np.ceil(duration / period))):
        pos = round(repeat * period * sr)
        take = min(len(piece), n - pos)
        chunk = piece[:take].copy()
        f = min(xf, take)
        shape = (f, *([1] * (audio.ndim - 1)))
        if repeat:
            ramp = np.linspace(0, 1, xf, dtype=np.float32)[:f].reshape(shape)
            chunk[:f] *= ramp
            out[pos:pos + f] *= 1 - ramp
        out[pos:pos + take] += chunk
    return out


def ducking(narration, sr=SR) -> np.ndarray:
    """10 ms RMS sidechain, -45 dBFS threshold, 80 ms attack / 400 ms release time constants."""
    speech = np.asarray(narration, np.float32)
    if not len(speech):
        return np.empty(0, np.float32)
    power = (speech.reshape(len(speech), -1).astype(np.float64) ** 2).mean(1)
    hop = max(1, round(.01 * sr))
    frames = int(np.ceil(len(power) / hop))
    padded = np.pad(power, (0, frames * hop - len(power)))
    db = 10 * np.log10(padded.reshape(frames, hop).mean(1) + 1e-12)
    active = np.clip((db + 45) / 10, 0, 1)
    attack, release = 1 - np.exp(-hop / (sr * ATTACK)), 1 - np.exp(-hop / (sr * RELEASE))
    env, held = np.empty(frames), 0.
    for i, v in enumerate(active):
        held += (v - held) * (attack if v > held else release)
        env[i] = held
    depth = np.interp(np.arange(len(speech)), np.arange(frames + 1) * hop, np.r_[0., env])
    return (10 ** (DUCK_DB * depth / 20)).astype(np.float32)


def ambient_pad(duration, music_mood='calm', sr=SR, seed=20260927) -> np.ndarray:
    """Three detuned sine/triangle voices with a slow low-pass colour, fitted to -30 LUFS before fades."""
    beat_grid(duration, 120)
    rng = np.random.default_rng(seed)
    n = round(duration * sr)
    t = np.arange(max(n, round(.4 * sr)) if n else 0) / sr
    out = np.zeros((len(t), 2), np.float64)
    if not len(t):
        return out.astype(np.float32)
    chord = CHORDS.get(music_mood.strip().lower(), CHORDS['calm'])
    for i, freq in enumerate(chord):
        phase = 2 * np.pi * freq * 2 ** (rng.uniform(-4, 4) / 1200) * t
        tone = .8 * np.sin(phase) + .2 * (2 / np.pi * np.arcsin(np.sin(phase)))
        dark = sosfilt(butter(2, 350, fs=sr, output='sos'), tone)
        light = sosfilt(butter(2, 1400, fs=sr, output='sos'), tone)
        sweep = .5 + .5 * np.sin(2 * np.pi * .07 * t + i)
        voice = (dark * (1 - sweep) + light * sweep) * (.85 + .15 * np.sin(2 * np.pi * .11 * t + i))
        pan = (.25 + .25 * i) * np.pi / 2
        out += voice[:, None] * np.array([np.cos(pan), np.sin(pan)])
    return master.master(out, sr, target_lufs=-30)[:n] * _fades(n, sr)[:, None]


def _fades(n, sr):
    """In over mix.FADE_IN (the music is there from the first word), out over mix.FADE."""
    gain = np.ones(n, np.float32)
    f, g = min(round(mix.FADE * sr), n // 2), min(round(mix.FADE_IN * sr), n // 2)
    if g:
        gain[:g] = np.linspace(0, 1, g) ** 1.5
    if f:
        gain[-f:] = np.linspace(1, 0, f) ** 1.5
    return gain


@lru_cache(maxsize=3)
def _track(slug):
    return mix.decode(mix.MUSIC / f'{slug}.mp3', 2)


def recording(audio, duration, bpm, downbeat) -> np.ndarray:
    """A recording looped on its bars (or cut) to the duration, at the music's open level, faded in and out."""
    music = loop(audio, duration, bpm, downbeat)
    level = master.loudness(music, SR)
    if np.isfinite(level):
        music *= np.float32(10 ** ((mix.OPEN_LUFS - level) / 20))
    return music * _fades(len(music), SR)[:, None]


def render(duration, music_mood='neutral', tempo_bpm=120., narration=None, ambient=False,
           seed=20260927, track=None, sections=(), marks=()) -> Score:
    """Stereo 48 kHz music and final -14 LUFS / -1 dBTP mix. Narration must already be at 48 kHz.

    track: 'procedural' synthesizes the score (sections and marks shape it, seed varies it); a recording's slug
    plays that recording and an Own track your own file; None selects a recording by mood and tempo, or with
    ambient=True a pad when the mood has no tagged recording. Short narration is zero-padded; longer narration is
    cropped. The beat grid is available to a caller snapping transitions to beats/bars.
    """
    beat_grid(duration, tempo_bpm)
    n = round(duration * SR)
    speech = np.zeros((n, 2), np.float32)
    if narration is not None:
        voice = np.asarray(narration, np.float32)
        if voice.ndim not in (1, 2) or (voice.ndim == 2 and voice.shape[1] not in (1, 2)):
            raise ValueError('narration must be mono or stereo')
        if voice.ndim == 1:
            voice = voice[:, None]
        speech[:min(n, len(voice))] = voice[:n]
    mood = music_mood.strip().lower()
    mine = isinstance(track, Own)
    if not mine and track not in (None, PROCEDURAL) and track not in tags():
        raise ValueError(f'unknown music track {track!r}')
    use_pad = track is None and ambient and not any(mood in t['moods'] for t in tags().values())
    slug = None if use_pad else track or choose(mood, tempo_bpm)
    bpm = tempo_bpm if use_pad or slug == PROCEDURAL else track.bpm if mine else tags()[slug]['bpm']
    if use_pad:
        music = ambient_pad(duration, mood, seed=seed)
    elif slug == PROCEDURAL and n:
        music = procedural.compose(duration, mood, tempo_bpm, seed, sections, marks)
        level = master.loudness(music, SR)                   # under 0.4 s: compose's usual -16 LUFS
        music *= np.float32(10 ** ((mix.OPEN_LUFS - (level if np.isfinite(level) else -16.)) / 20))
        music *= _fades(n, SR)[:, None]
    elif n and mine:
        music = recording(mix.decode(track.path, 2), duration, bpm, track.downbeat)
    elif n:
        music = recording(_track(slug), duration, bpm, tags()[slug]['downbeat'])
    else:
        music = np.zeros((0, 2), np.float32)
    gain = ducking(speech)
    music *= gain[:, None]
    audio = master.master(music + speech, SR) if n else music.copy()
    if 0 < n < round(.4 * SR):
        audio = master.limit(audio, SR, mix.CEILING_DBTP)
    return Score(music, audio, beat_grid(duration, bpm), gain, bpm, track.file if mine else slug)

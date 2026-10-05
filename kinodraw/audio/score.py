"""Mood-selected CC0 score, bar-aligned loops and narration sidechain.

render() returns the quiet, ducked music stem, the mastered narration/music mix and its beat grid. Requested
tempo selects a recording; bpm and beats describe its measured tempo, without repitching it. Measurements
in assets/music/score_tags.json are made once with scripts/measure_bpm.py, including its analysis delay.
The source starts at its first downbeat, so the output's beat and bar grids start at zero.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.signal import butter, sosfilt

from . import master, mix

SR = mix.SR
TAGS = mix.MUSIC / 'score_tags.json'
DUCK_DB, ATTACK, RELEASE = -10.0, .08, .4
CHORDS = {'bright': (130.81, 164.81, 196.00), 'discovery': (146.83, 220.00, 261.63),
          'calm': (130.81, 196.00, 246.94), 'mysterious': (110.00, 130.81, 164.81),
          'somber': (130.81, 155.56, 196.00), 'neutral': (130.81, 174.61, 196.00)}


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
    gain = np.ones(n, np.float32)
    f = min(round(mix.FADE * sr), n // 2)
    if f:
        gain[:f] = np.linspace(0, 1, f) ** 1.5
        gain[-f:] = np.linspace(1, 0, f) ** 1.5
    return gain


@lru_cache(maxsize=3)
def _track(slug):
    return mix.decode(mix.MUSIC / f'{slug}.mp3', 2)


def render(duration, music_mood='neutral', tempo_bpm=120., narration=None, ambient=False,
           seed=20260927) -> Score:
    """Stereo 48 kHz music and final -14 LUFS / -1 dBTP mix. Narration must already be at 48 kHz.

    Set ambient=True to use a pad when the mood has no tagged recording. Short narration is zero-padded;
    longer narration is cropped. The beat grid is available to a caller snapping transitions to beats/bars.
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
    use_pad = ambient and not any(mood in t['moods'] for t in tags().values())
    slug = None if use_pad else choose(mood, tempo_bpm)
    bpm = tempo_bpm if use_pad else tags()[slug]['bpm']
    if use_pad:
        music = ambient_pad(duration, mood, seed=seed)
    elif n:
        music = loop(_track(slug), duration, bpm, tags()[slug]['downbeat'])
        level = master.loudness(music, SR)
        if np.isfinite(level):
            music *= np.float32(10 ** ((mix.OPEN_LUFS - level) / 20))
        music *= _fades(n, SR)[:, None]
    else:
        music = np.zeros((0, 2), np.float32)
    gain = ducking(speech)
    music *= gain[:, None]
    audio = master.master(music + speech, SR) if n else music.copy()
    if 0 < n < round(.4 * SR):
        audio = master.limit(audio, SR, mix.CEILING_DBTP)
    return Score(music, audio, beat_grid(duration, bpm), gain, bpm, slug)

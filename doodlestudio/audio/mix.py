"""Narration master and light music bed.

assemble(): place every beat's clip on the timeline, normalize to -18 LUFS, write captions.
mix(): lay the bundled CC0 music under the timeline's music windows (title, agenda,
section transitions, outro and end card), ducked under speech, fading at every edge.
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from scipy.signal import resample_poly

from .. import voice
from ..engine import timeline

SR = 48000
FADE = 1.5
UNDER_SPEECH_LUFS = -31.0
OPEN_LUFS = -25.0
MUSIC = Path(__file__).resolve().parents[1] / 'assets' / 'music'
DEFAULT_TRACKS = {'primary': 'fresh_focus', 'secondary': 'natural_vibes'}
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, check=True)


def read_wav(path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), '<i2').reshape(-1, w.getnchannels())
        return data.astype(np.float32) / 32768, w.getframerate()


def write_wav(path, samples: np.ndarray, rate=SR):
    samples = samples if samples.ndim == 2 else samples[:, None]
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(samples.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())


def loudness(path) -> dict:
    out = subprocess.run([FFMPEG, '-v', 'info', '-i', str(path), '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
                         capture_output=True, encoding='utf-8', errors='replace').stderr
    return json.JSONDecoder().raw_decode(out[out.rfind('{'):])[0]


def decode(path, channels) -> np.ndarray:
    raw = _run([FFMPEG, '-v', 'error', '-i', str(path), '-f', 'f32le', '-ac', str(channels), '-ar', str(SR), '-']).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, channels).copy()


def write_captions(captions, out_dir: Path):
    def stamp(t, vtt):
        ms = round(t * 1000)
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f'{h:02}:{m:02}:{s:02}{"." if vtt else ","}{ms:03}'
    for ext in ('srt', 'vtt'):
        lines = ['WEBVTT\n'] if ext == 'vtt' else []
        for i, c in enumerate(captions, 1):
            lines.append(f"{i}\n{stamp(c['start'], ext == 'vtt')} --> {stamp(c['end'], ext == 'vtt')}\n{c['text']}\n")
        (out_dir / f'captions.{ext}').write_text('\n'.join(lines), encoding='utf-8')


def timing(clips: dict) -> dict:
    """What the timeline needs from each voice.Clip: speech length (with the gap after it) and character times."""
    return {bid: {'speech': c.duration + voice.GAP, 'char_times': c.char_times} for bid, c in clips.items()}


def assemble(storyboard: dict, lang: str, clips: dict, out_dir: Path, pauses: dict | None = None,
             credit: bool = True) -> dict:
    """clips[beat_id] = voice.Clip; pauses[beat_id] = silence after a beat (pacing). Writes narration.wav,
    timeline.json and captions; returns the timeline."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tl = timeline.layout(storyboard, lang, timing(clips), pauses, credit)
    total = round(tl['duration'] * SR)
    pcm = np.zeros(total, np.float32)
    for beat in storyboard['beats']:
        audio, rate = read_wav(clips[beat['id']].wav)
        audio = resample_poly(audio[:, 0], SR // rate, 1) if rate != SR else audio[:, 0]
        start = round(tl['beats'][beat['id']]['start'] * SR)
        n = max(0, min(len(audio), total - start))
        pcm[start:start + n] += audio[:n]
    premaster, master = out_dir / 'narration-premaster.wav', out_dir / 'narration.wav'
    write_wav(premaster, pcm)
    m = loudness(premaster)
    af = ('loudnorm=I=-18:TP=-1.5:LRA=7:linear=true:'
          f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}")
    _run([FFMPEG, '-y', '-v', 'error', '-i', str(premaster), '-af', af, '-ar', str(SR), '-ac', '1', '-c:a', 'pcm_s16le',
          str(master)])
    premaster.unlink()
    if len(read_wav(master)[0]) != total:
        raise RuntimeError('loudness normalization changed the narration length')
    tl['audio'] = str(master)
    write_captions(tl['captions'], out_dir)
    (out_dir / 'timeline.json').write_text(json.dumps(tl, ensure_ascii=False))
    return tl


def envelope(speech: np.ndarray, window=.05) -> np.ndarray:
    """0..1 speech activity, held 0.3 s and smoothed so the music bed does not pump between words."""
    n = int(SR * window)
    frames = len(speech) // n + 1
    padded = np.zeros(frames * n, np.float32)
    padded[:len(speech)] = speech
    rms = np.sqrt((padded.reshape(frames, n) ** 2).mean(1) + 1e-12)
    active = (20 * np.log10(rms + 1e-9) > -45).astype(np.float32)
    held = active.copy()
    for k in range(1, int(.3 / window) + 1):
        held[:-k] = np.maximum(held[:-k], active[k:])
        held[k:] = np.maximum(held[k:], active[:-k])
    out, a = np.empty_like(held), 0.
    for i, v in enumerate(held):
        a += (v - a) * (.35 if v > a else .12)
        out[i] = a
    return np.repeat(out, n)[:len(speech)]


def mix(storyboard: dict, tl: dict, out_dir: Path) -> Path:
    """Write mix.wav (48 kHz stereo): the narration plus the music bed (or narration only when music is off)."""
    out_dir = Path(out_dir)
    speech = read_wav(tl['audio'])[0][:, 0]
    total = len(speech)
    music = np.zeros((total, 2), np.float32)
    setting = storyboard.get('music', True)
    if setting:
        tracks = {**DEFAULT_TRACKS, **(setting if isinstance(setting, dict) else {})}
        kinds = {c['id']: c['kind'] for c in storyboard['chapters']}
        spans = {kinds[c['id']]: c for c in tl['chapters']}
        intro_end = spans['intro']['end'] if 'intro' in spans else 0
        outro_start = spans['outro']['start'] if 'outro' in spans else tl['duration']
        env, cache = envelope(speech), {}
        for win in tl['music']:
            a, b = win['start'], min(win['end'], total / SR)
            slug = tracks['primary'] if (a < intro_end + 1 or b > outro_start - 1) else tracks['secondary']
            if slug not in cache:
                path = MUSIC / f'{slug}.mp3'
                audio = decode(path, 2)
                nz = np.flatnonzero(np.abs(audio).max(1) > 1e-3)
                cache[slug] = (audio[nz[0]:nz[-1] + 1] if len(nz) else audio, float(loudness(path)['input_i']))
            audio, lufs = cache[slug]
            n = int((b - a) * SR)
            if n <= 0:
                continue
            seg, pos, xf = np.zeros((n, 2), np.float32), 0, SR      # loop with 1 s crossfades
            while pos < n:
                take = min(len(audio), n - pos)
                piece = audio[:take].copy()
                if pos > 0:
                    ramp = np.linspace(0, 1, min(xf, take))[:, None]
                    piece[:len(ramp)] *= ramp
                    seg[pos:pos + len(ramp)] *= (1 - ramp)
                seg[pos:pos + take] += piece
                pos += take - (xf if take == len(audio) else 0)
            g_under, g_open = 10 ** ((UNDER_SPEECH_LUFS - lufs) / 20), 10 ** ((OPEN_LUFS - lufs) / 20)
            i0 = int(a * SR)
            gain = g_open + (g_under - g_open) * env[i0:i0 + n]
            fade = np.ones(n, np.float32)
            f = min(int(FADE * SR), n // 2)
            fade[:f] = np.linspace(0, 1, f) ** 1.5
            fade[n - f:] = np.linspace(1, 0, f) ** 1.5
            music[i0:i0 + n] += seg * (gain * fade)[:, None]
    out = out_dir / 'mix.wav'
    write_wav(out, speech[:, None].repeat(2, axis=1) + music)
    return out

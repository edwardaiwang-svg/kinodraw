"""Narration master and light music bed.

assemble(): place every beat's clip on the timeline, normalize to -18 LUFS, write captions.
mix(): lay the bundled CC0 music under the timeline's music windows (title, agenda,
section transitions, outro and end card), ducked under speech, fading at every edge.
The animated looks (any look the whiteboard renderer does not draw) get a bed under the whole video instead,
the sound effects the renderer cued (build/cues.json), and a mastered mix (-14 LUFS, -1 dBTP).
Your own music file (pipeline.set_music) plays under the whole video in every look, and the mix is mastered.
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path, PureWindowsPath

import imageio_ffmpeg
import numpy as np
from scipy.signal import resample_poly

from .. import styles, voice
from ..engine import timeline
from . import master, sfx

SR = 48000
FADE = 1.5
UNDER_SPEECH_LUFS = -31.0
OPEN_LUFS = -25.0
BED_UNDER_LUFS = -36.0     # animated looks: the bed sits 18 dB under the -18 LUFS narration
SFX_DUCK_DB = -6.0         # sound effects while someone speaks
SWELL_DB, SWELL = 3.0, 1.5  # the bed comes up after every cut, easing back over 1.5 s
MASTER_LUFS, CEILING_DBTP = -14.0, -1.0
MUSIC = Path(__file__).resolve().parents[1] / 'assets' / 'music'
DEFAULT_TRACKS = {'primary': 'fresh_focus', 'secondary': 'natural_vibes'}
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
LOCAL_AUDIO = ['-protocol_whitelist', 'file', '-format_whitelist', 'mp3,wav,mov,ogg,flac,aac,aiff,matroska']


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


def decode(path, channels, seconds=None) -> np.ndarray:
    """The file's audio at SR (its first ``seconds`` only, when given). Read only as a local audio file: a playlist or
    concat list posing as music can't make FFmpeg fetch a URL or open another file."""
    limit = ['-t', str(seconds)] if seconds is not None else []
    raw = _run([FFMPEG, '-v', 'error', *LOCAL_AUDIO, *limit, '-i', str(path), '-f', 'f32le', '-ac', str(channels),
                '-ar', str(SR), '-']).stdout
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
    return {bid: {'speech': c.duration + voice.GAP, 'char_times': c.char_times,
                  **({'speakers': list(c.speakers), 'cut_off': c.cut_off, 'duration': c.duration}
                     if getattr(c, 'speakers', ()) else {})}
            for bid, c in clips.items()}


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
    tl['audio'] = master.name                       # next to timeline.json: a moved project still finishes
    write_captions(tl['captions'], out_dir)
    (out_dir / 'timeline.json').write_text(json.dumps(tl, ensure_ascii=False), encoding='utf-8')
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


def narration(tl: dict, out_dir: Path) -> Path:
    """The timeline's narration, which sits next to it in out_dir. Doodle Studio stored its absolute path, which points
    nowhere once the project folder has moved (Doodle Studio's projects folder became KinoDraw's): then the file of
    that name in out_dir is used (PureWindowsPath reads both / and \\ paths)."""
    path = Path(out_dir) / tl['audio']                 # an absolute path replaces out_dir
    return path if path.exists() else Path(out_dir) / PureWindowsPath(tl['audio']).name


def track(slug) -> tuple[np.ndarray, float]:
    """A bundled track at SR with its silent ends trimmed, and its loudness (LUFS)."""
    path = MUSIC / f'{slug}.mp3'
    audio = decode(path, 2)
    nz = np.flatnonzero(np.abs(audio).max(1) > 1e-3)
    return audio[nz[0]:nz[-1] + 1] if len(nz) else audio, float(loudness(path)['input_i'])


def loop(audio, n) -> np.ndarray:
    """The track repeated to n samples, with 1 s crossfades."""
    seg, pos, xf = np.zeros((n, 2), np.float32), 0, SR
    while pos < n:
        take = min(len(audio), n - pos)
        piece = audio[:take].copy()
        if pos > 0:
            ramp = np.linspace(0, 1, min(xf, take))[:, None]
            piece[:len(ramp)] *= ramp
            seg[pos:pos + len(ramp)] *= (1 - ramp)
        seg[pos:pos + take] += piece
        pos += take - (xf if take == len(audio) else 0)
    return seg


def fades(n) -> np.ndarray:
    """Gain 1, easing in and out over FADE seconds at the ends."""
    fade = np.ones(n, np.float32)
    f = min(int(FADE * SR), n // 2)
    fade[:f] = np.linspace(0, 1, f) ** 1.5
    fade[n - f:] = np.linspace(1, 0, f) ** 1.5
    return fade


def windows(storyboard: dict, tl: dict, env: np.ndarray, tracks: dict) -> np.ndarray:
    """The whiteboard's music: each music window, the primary track near the start and end."""
    total = len(env)
    music = np.zeros((total, 2), np.float32)
    kinds = {c['id']: c['kind'] for c in storyboard['chapters']}
    spans = {kinds[c['id']]: c for c in tl['chapters']}
    intro_end = spans['intro']['end'] if 'intro' in spans else 0
    outro_start = spans['outro']['start'] if 'outro' in spans else tl['duration']
    cache = {}
    for win in tl['music']:
        a, b = win['start'], min(win['end'], total / SR)
        slug = tracks['primary'] if (a < intro_end + 1 or b > outro_start - 1) else tracks['secondary']
        if slug not in cache:
            cache[slug] = track(slug)
        audio, lufs = cache[slug]
        n = int((b - a) * SR)
        if n <= 0:
            continue
        g_under, g_open = 10 ** ((UNDER_SPEECH_LUFS - lufs) / 20), 10 ** ((OPEN_LUFS - lufs) / 20)
        i0 = int(a * SR)
        gain = g_open + (g_under - g_open) * env[i0:i0 + n]
        music[i0:i0 + n] += loop(audio, n) * (gain * fades(n))[:, None]
    return music


def swell(cues: list, n: int) -> np.ndarray:
    """Bed gain: up SWELL_DB within 50 ms of every cut, easing back to 0 dB over SWELL seconds."""
    db = np.zeros(n, np.float32)
    u = np.arange(int(SWELL * SR)) / SR
    shape = (SWELL_DB * np.minimum(1, u / .05) * np.cos(np.pi / 2 * u / SWELL) ** 2).astype(np.float32)
    for cue in cues:
        i = round(float(cue['t']) * SR)
        if cue['kind'] == 'cut' and 0 <= i < n:
            np.maximum(db[i:i + len(shape)], shape[:n - i], out=db[i:i + len(shape)])
    return 10 ** (db / 20)


def bed(env: np.ndarray, cues: list, slug: str) -> np.ndarray:
    """The animated looks' music: one track under the whole video, 18 dB under speech, swelling after cuts."""
    audio, lufs = track(slug)
    g_under, g_open = 10 ** ((BED_UNDER_LUFS - lufs) / 20), 10 ** ((OPEN_LUFS - lufs) / 20)
    gain = (g_open + (g_under - g_open) * env) * fades(len(env)) * swell(cues, len(env))
    return loop(audio, len(env)) * gain[:, None]


def mix(storyboard: dict, tl: dict, out_dir: Path) -> Path:
    """Write mix.wav (48 kHz stereo): the narration plus the music bed (or narration only when music is off).
    Any look but the whiteboard also gets its sound effects and a bed under the whole video, and is mastered;
    storyboard keys 'sfx' and 'master' (true or false) override either. Your own music file (score.own, in the
    project folder above out_dir) plays under the whole video instead, looped on its bars or cut to the video's
    length, at the bundled recordings' level and ducking (score.recording, score.ducking), and is mastered."""
    from . import score
    out_dir = Path(out_dir)
    speech = read_wav(narration(tl, out_dir))[0][:, 0]
    total = len(speech)
    animated = styles.renderer(storyboard.get('look')) != 'whiteboard'   # skins over the whiteboard mix as it does
    cued = out_dir / 'cues.json'
    cues = json.loads(cued.read_text(encoding='utf-8'))['cues'] if cued.is_file() else []
    music = np.zeros((total, 2), np.float32)
    setting = storyboard.get('music', True)
    own = score.own(setting, out_dir.parent)
    env = envelope(speech) if setting or cues else None
    if own:
        music = score.recording(decode(own.path, 2), total / SR, own.bpm, own.downbeat) * score.ducking(speech)[:, None]
        if animated:
            music *= swell(cues, total)[:, None]
    elif setting:
        tracks = {**DEFAULT_TRACKS, **(setting if isinstance(setting, dict) else {})}
        music = bed(env, cues, tracks['primary']) if animated else windows(storyboard, tl, env, tracks)
    out = speech[:, None].repeat(2, axis=1) + music
    if cues and storyboard.get('sfx', animated):
        out += sfx.render(cues, total / SR) * (1 + (10 ** (SFX_DUCK_DB / 20) - 1) * env)[:, None]
    if storyboard.get('master', animated or own is not None):
        out = master.master(out, SR, MASTER_LUFS, CEILING_DBTP)
    path = out_dir / 'mix.wav'
    write_wav(path, out)
    return path

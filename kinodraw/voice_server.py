"""Opt-in narration from the creator's own OpenAI-compatible speech server.

Only this computer's own setting chooses the server (the Studio's Settings > Voice server, or the CLI's flags and TTS_*
variables): a project records which model and voice narrated it, never an address to contact, so a project someone
sends you cannot make KinoDraw send your script or your key anywhere. A saved API key belongs to the address
(scheme://host:port) it was saved for and is sent only there."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import imageio_ffmpeg
import numpy as np

from . import net, paths, voice

VERSION = 1
SR = 24000
BACK = (' To go back to the built-in voice, turn off Settings > Voice server in the Studio; in the CLI, '
        'drop the --voice-server, --server-model and --server-voice flags and TTS_* variables '
        '(for a saved project, run kinodraw voice PROJECT --voice-server none).')


class VoiceServerError(ValueError):
    """A server problem with an explanation and a way back to the built-in voice."""

    def __init__(self, message: str):
        super().__init__(message + BACK)


def check_url(url: str) -> str:
    url = url.strip() if isinstance(url, str) else ''
    try:
        parts = urlsplit(url)
        valid = parts.scheme in ('http', 'https') and bool(parts.hostname)
        parts.port                                      # validate the port too
    except ValueError:
        valid = False
    if not valid:
        raise VoiceServerError('The voice server address should start with http:// or https://, '
                               'for example http://localhost:8880/v1.')
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise VoiceServerError('Use a voice server address without a login, query or fragment. '
                               'Enter its API key in the separate key field instead.')
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise VoiceServerError('The voice server address should not contain spaces or control characters.')
    return url.rstrip('/')


def endpoint(url: str) -> str:
    url = check_url(url)
    path = urlsplit(url).path.rstrip('/')
    if path.endswith('/audio/speech'):
        return url
    return url + ('/audio/speech' if path.endswith('/v1') else '/v1/audio/speech')


def _normalized(url: str) -> str:
    parts = urlsplit(endpoint(url))
    host = parts.hostname.lower()
    host = f'[{host}]' if ':' in host else host
    port = parts.port
    if port is not None and port != (443 if parts.scheme == 'https' else 80):
        host += f':{port}'
    return urlunsplit((parts.scheme.lower(), host, parts.path, '', ''))


def origin(url: str) -> str:
    """scheme://host[:port] of a server address: what a saved key is bound to."""
    parts = urlsplit(_normalized(url))
    return f'{parts.scheme}://{parts.netloc}'



@dataclass
class Server:
    url: str
    model: str
    voice: str = ''
    key: str | None = None

    def __post_init__(self):
        self.url = check_url(self.url)
        self.model = self.model.strip() if isinstance(self.model, str) else ''
        if not self.model:
            raise VoiceServerError('Enter the model name your voice server uses (TTS_MODEL or --server-model '
                                   'in the CLI).')
        if not isinstance(self.voice, str):
            raise VoiceServerError('The server voice name should be text.')
        self.voice = self.voice.strip()


def speech(server: Server, text: str, speed: float) -> bytes:
    body = {'model': server.model, 'input': text, 'response_format': 'wav', 'speed': speed}
    if server.voice:
        body['voice'] = server.voice
    headers = {'Content-Type': 'application/json'}
    if server.key:
        headers['Authorization'] = f'Bearer {server.key}'
    request = urllib.request.Request(endpoint(server.url), data=json.dumps(body).encode(), headers=headers,
                                     method='POST')
    address = origin(server.url)

    def safe(text):
        return str(text).replace(server.key, '[hidden]') if server.key else str(text)

    try:
        with net.urlopen(request, timeout=180) as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            message = f'Your voice server at {address} refused the API key. It may be missing or wrong.'
        elif error.code == 404:
            message = f'Your voice server at {address} has no /v1/audio/speech endpoint there. Check the address.'
        else:
            detail = safe(error.read().decode(errors='replace'))[:200]
            message = f'Your voice server at {address} failed (HTTP {error.code}: {detail}).'
        error.close()
        raise VoiceServerError(message) from None
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        reason = safe(getattr(error, 'reason', error))
        raise VoiceServerError(f"KinoDraw couldn't reach your voice server at {address} ({reason}). "
                               'Check that it is running and the address is right.') from None
    if not data:
        raise VoiceServerError(f'Your voice server at {address} answered with no audio.')
    return data


def decode(data: bytes) -> np.ndarray:
    message = 'Your voice server answered, but not with audio KinoDraw can play. Check its speech endpoint.'
    if data.lstrip()[:1] in (b'{', b'[', b'<'):
        raise VoiceServerError(message)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'speech.audio'
            source.write_bytes(data)
            run = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(source),
                                  '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True)
        if run.returncode or not run.stdout or len(run.stdout) % 4:
            raise VoiceServerError(message)
        audio = np.frombuffer(run.stdout, '<f4').copy()
        if not np.isfinite(audio).all():
            raise VoiceServerError(message)
        return audio
    except OSError:
        raise VoiceServerError(message) from None


def char_times(spoken: str, audio: np.ndarray, lang: str) -> list[float]:
    """Estimate character times; matching pauses anchor clauses, otherwise use their relative weights."""
    if not len(audio):
        return [0.0] * len(spoken)
    duration = len(audio) / SR
    active = np.flatnonzero(np.abs(audio) > max(float(np.max(np.abs(audio))) * .02, 1e-5))
    if not len(active):
        return [0.0] * len(spoken)
    start, end = active[0] / SR, (active[-1] + 1) / SR
    hop = SR // 100
    frames = np.pad(audio, (0, (-len(audio)) % hop)).reshape(-1, hop)
    level = np.sqrt((frames ** 2).mean(1))
    quiet = level < max(float(level.max()) * .04, 1e-5)
    edges = np.diff(np.r_[False, quiet, False].astype(int))
    gaps = [(a / 100, b / 100) for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))
            if b - a >= 12 and a / 100 > start and b / 100 < end]
    marks = [i for i in range(len(spoken)) if voice._is_clause_mark(spoken, i, lang)
             and any(c.isalnum() for c in spoken[:i]) and any(c.isalnum() for c in spoken[i + 1:])]
    times = [0.0] * len(spoken)

    def spread(lo, hi, a, b, pauses=True):
        chars = range(lo, hi)
        weights = [1.0 if spoken[i].isalnum() else
                   (.8 if pauses and voice._is_clause_mark(spoken, i, lang) else 0.0) for i in chars]
        total, acc = sum(weights) or 1.0, 0.0
        for i, weight in zip(chars, weights):
            times[i] = a + (b - a) * (acc + weight / 2) / total
            acc += weight

    if marks and len(gaps) == len(marks):
        lo, a = 0, start
        for mark, (gap_start, gap_end) in zip(marks, gaps):
            spread(lo, mark, a, gap_start, False)
            times[mark] = gap_start
            lo, a = mark + 1, gap_end
        spread(lo, len(spoken), a, end)
    else:
        spread(0, len(spoken), start, end)
    for i in range(len(times)):
        times[i] = min(duration, max(0.0, times[i], times[i - 1] if i else 0.0))
    return [min(round(duration, 3), round(t, 3)) for t in times]


def synthesize(spoken: str, lang: str, cache_dir: Path, server: Server, speed: float = 1.0,
               lexicon: dict | None = None) -> voice.Clip:
    said = voice.respell(spoken, lexicon, lang) if lexicon else spoken
    content = [VERSION, 'openai_compatible', _normalized(server.url), server.model, server.voice, speed, spoken, said]
    key = hashlib.sha256(json.dumps(content).encode()).hexdigest()
    cache_dir = Path(cache_dir)
    wav, meta = cache_dir / f'{key}.wav', cache_dir / f'{key}.json'
    if wav.exists() and meta.exists():
        info = json.loads(meta.read_text(encoding='utf-8'))
        return voice.Clip(wav, info['duration'], info['char_times'])
    audio = decode(speech(server, said, speed))
    times = char_times(spoken, audio, lang)
    duration = round(len(audio) / SR, 3)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
    meta.write_text(json.dumps({'duration': duration, 'char_times': times, 'backend': 'openai_compatible',
                                'model': server.model, 'voice': server.voice, 'speed': speed, 'text': spoken},
                               ensure_ascii=False), encoding='utf-8')
    return voice.Clip(wav, duration, times)


def from_env(environ=os.environ) -> dict | None:
    backend = environ.get('TTS_BACKEND', 'kokoro')
    if backend == 'kokoro':
        return None
    if backend != 'openai_compatible':
        raise VoiceServerError('TTS_BACKEND accepts only kokoro or openai_compatible.')
    for name in ('TTS_API_BASE', 'TTS_MODEL'):
        if not environ.get(name, '').strip():
            raise VoiceServerError(f'Set {name} to use your own voice server.')
    return {'url': check_url(environ['TTS_API_BASE']), 'model': environ['TTS_MODEL'].strip(),
            'voice': environ.get('TTS_VOICE') or ''}


def key_name(url: str) -> str:
    """The keychain entry for the key of the server at ``url``: one per origin."""
    return f'voice-server:{origin(url)}'


def api_key(url: str) -> str | None:
    """The key saved for this server's origin, else TTS_API_KEY when it belongs to this server (TTS_API_BASE unset or
    the same origin). Read only when the server is about to be asked for speech; never a key saved for another one."""
    try:
        import keyring
        key = keyring.get_password(paths.APP, key_name(url))
        if key:
            return key
    except Exception:                                    # no keychain backend on a headless computer
        pass
    key, base = os.environ.get('TTS_API_KEY'), os.environ.get('TTS_API_BASE')
    if key and base:
        try:
            return key if origin(base) == origin(url) else None
        except VoiceServerError:
            return None
    return key or None


def save_key(url: str, key: str):
    from .director.llm import providers
    providers.save_key(key_name(url), key)


def record(server: Server) -> dict:
    """What a project keeps about the server voice that narrated it (for its credit): names only, no address."""
    return {'model': server.model, 'voice': server.voice}


NOT_ON = ('This project is set to be read by a voice server, but this computer\'s voice server setting is off, so '
          'nothing was sent. A project never chooses the server itself: to use yours, turn on Settings > Voice server '
          'in the Studio, or in the CLI set TTS_BACKEND=openai_compatible with TTS_API_BASE and TTS_MODEL (or pass '
          '--voice-server and --server-model).')


def describe(cfg: dict, lang: str = 'en') -> str:
    model, name = cfg['model'], cfg.get('voice', '')
    if lang == 'zh':
        return f'作者自己的语音服务器（模型 {model}' + (f'，声音 {name}' if name else '') + '）'
    if lang == 'es':
        return (f'voz "{name}" (modelo {model})' if name else f'voz (modelo {model})') + \
            ' del servidor de voz del creador'
    return (f'voice "{name}" (model {model})' if name else f'voice (model {model})') + \
        " from the creator's own voice server"

"""Local narration with Kokoro (82M, Apache-2.0) through kokoro-onnx.

One clip per beat, cached by content hash, plus the time at which every character
of the spoken text is heard (for captions and drawing triggers). Timing comes
from the model's own phoneme durations: clause marks anchor each clause, and
within a clause letters map proportionally onto the spoken phonemes.

from_recording() makes the same clips from your own reading of the script instead:
Kokoro reads it too, as a guide that is aligned to your take frame by frame.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
import numpy as np

from . import paths
from .net import download
from .script import sentences as sentences_of

MODEL_DIR = Path(paths.getenv('KINODRAW_MODELS') or paths.data_dir() / 'models').expanduser()
RELEASE = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
FILES = {       # name: (url, sha256, bytes)
    'kokoro-v1.0.fp16.onnx': (RELEASE + 'kokoro-v1.0.fp16.onnx',
                              'f3a290d384fbb27966d462905c71a46cef9e5fd00516b40df32a0b4afe77ac96', 163_527_961),
    'voices-v1.0.bin': (RELEASE + 'voices-v1.0.bin', 'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d',
                        28_214_398),
    'kokoro-v1.1-zh.fp16.onnx': (RELEASE + 'kokoro-v1.1-zh.fp16.onnx',
                                 'a628ea5d6fbde96d1a85f691a6a00847829937f9e488021ba2c5359bc6ea08b5', 163_528_759),
    'voices-v1.1-zh.bin': (RELEASE + 'voices-v1.1-zh.bin',
                           '14cb6186c99e4f6016871405f62046c5df863ae27465cbdc4ee08be7dd703acd', 53_815_880),
    'config-v1.1-zh.json': ('https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh/resolve/main/config.json',
                            'bc333efa5ce4ceff433c8c8e5d027a1eca0166001e4e4a62bea2d26ff7a46890', 3_228),
}
LANGS = {
    'en': {'model': 'kokoro-v1.0.fp16.onnx', 'voices': 'voices-v1.0.bin', 'config': None, 'voice': 'af_heart'},
    'es': {'model': 'kokoro-v1.0.fp16.onnx', 'voices': 'voices-v1.0.bin', 'config': None, 'voice': 'ef_dora'},
    'zh': {'model': 'kokoro-v1.1-zh.fp16.onnx', 'voices': 'voices-v1.1-zh.bin', 'config': 'config-v1.1-zh.json',
           'voice': 'zf_001'},
}
VOICES = {
    'en': [('af_heart', 'Heart, US woman (default)'), ('af_bella', 'Bella, US woman'),
           ('af_nicole', 'Nicole, US woman, soft'), ('am_michael', 'Michael, US man'),
           ('am_fenrir', 'Fenrir, US man, deep'), ('bf_emma', 'Emma, UK woman'), ('bm_george', 'George, UK man'),
           ('af_aoede', 'Aoede, US woman'), ('af_kore', 'Kore, US woman'), ('af_sarah', 'Sarah, US woman'),
           ('am_puck', 'Puck, US man'), ('bf_isabella', 'Isabella, UK woman'), ('bm_fable', 'Fable, UK man')],
    'zh': [('zf_001', 'Mei, Mandarin woman (default)'), ('zf_002', 'Lan, Mandarin woman'),
           ('zm_010', 'Wei, Mandarin man'), ('zm_020', 'Jun, Mandarin man'),
           ('zf_003', 'Mandarin woman 003'), ('zf_004', 'Mandarin woman 004'),
           ('zm_009', 'Mandarin man 009'), ('zm_011', 'Mandarin man 011')],
    'es': [('ef_dora', 'Dora, Latin American woman (default)'), ('em_alex', 'Alex, Latin American man'),
           ('em_santa', 'Santa, Spanish man')],
}
SPEEDS = (0.85, 1.15)
SR = 24000
GAP = .4                 # silence after each beat
VERSION = 2              # bump when synthesis or alignment changes (invalidates cached clips)
CLAUSE = {'en': ',.;:?!—', 'zh': '，。；：？！、—', 'es': ',.;:?!—'}
PHONE_MARKS = ',.;:?!—…'
NOT_SOUNDS = set(' ˈˌːʲ')


@dataclass
class Clip:
    wav: Path
    duration: float              # seconds of audio (the timeline adds GAP after it)
    char_times: list
    speakers: tuple = ()         # who speaks first and last (None = the narrator); empty for one plain read
    cut_off: bool = False        # the beat's last line breaks off ("Dad, turn it off—"): the next one overlaps it


# ------------------------------------------------------------------ models
def missing_files(lang: str) -> list[str]:
    spec = LANGS[lang]
    return [f for f in (spec['model'], spec['voices'], spec['config']) if f and not (MODEL_DIR / f).is_file()]


def ensure_models(lang: str, progress=None):
    """Download and checksum-verify the model files for ``lang`` (first run only); ``progress(done, total)`` in bytes."""
    download([(FILES[name][0], MODEL_DIR / name, *FILES[name][1:]) for name in missing_files(lang)], progress)


def _espeak_config():
    """espeak-ng silently ignores a data path longer than its buffer (~160 characters) and exits looking for its
    build machine's folder, so a deep install (a long folder name, an app unzipped somewhere deep) gets a copy of
    the data (~19 MB, once) in the user cache instead."""
    import espeakng_loader
    from kokoro_onnx.config import EspeakConfig
    data = Path(espeakng_loader.get_data_path())
    if len(str(data)) > 140:
        short = paths.cache_dir() / 'espeak-ng-data'
        if not (short / 'phontab').exists():
            shutil.copytree(data, short, dirs_exist_ok=True)
        data = short
    return EspeakConfig(data_path=str(data))


@lru_cache(maxsize=3)
def _engine(lang: str):
    ensure_models(lang)
    spec = LANGS[lang]
    return _model_engine(spec['model'], spec['voices'], spec['config'])


@lru_cache(maxsize=2)
def _model_engine(model, voices, config):
    import onnxruntime
    onnxruntime.set_default_logger_severity(3)       # fp16 graphs log many harmless constant-folding warnings
    from kokoro_onnx import Kokoro
    config = str(MODEL_DIR / config) if config else None
    engine = Kokoro(str(MODEL_DIR / model), str(MODEL_DIR / voices), espeak_config=_espeak_config(),
                    vocab_config=config)
    engine.sess = _Finite(engine.sess)
    return engine


class _Finite:
    """The model's session, run again when a run comes out with a sample that is not a number. Kokoro's graph draws
    fresh random noise on every run, and once in a while (fp16) a run has such a sample; kokoro-onnx's trim then keeps
    no audio at all, and its pause step stops on numpy's "zero-size array to reduction operation maximum"."""
    TRIES = 3

    def __init__(self, sess):
        self._sess = sess

    def __getattr__(self, name):
        return getattr(self._sess, name)

    def run(self, *args, **kwargs):
        for _ in range(self.TRIES):
            out = self._sess.run(*args, **kwargs)
            if np.isfinite(out[0]).all():
                return out
        raise RuntimeError(f'The voice model made no usable sound {self.TRIES} times in a row; run the voice step '
                           'again.')


@lru_cache(maxsize=1)
def _zh_g2p():
    from misaki import zh
    engine = _engine('zh')
    return zh.ZHG2P(version='1.1', en_callable=lambda word: engine.tokenizer.phonemize(word, 'en-us'))


def voices(lang: str) -> list[str]:
    return sorted(_engine(lang).get_voices())


def phonemes(text: str, lang: str) -> str:
    if lang == 'zh':
        return _zh_g2p()(text)[0]
    return _engine(lang).tokenizer.phonemize(text, 'es-419' if lang == 'es' else 'en-us')


# --------------------------------------------------------------- alignment
def _is_clause_mark(text: str, i: int, lang: str) -> bool:
    ch = text[i]
    if ch not in CLAUSE[lang]:
        return False
    return lang == 'zh' or ch == '—' or i + 1 == len(text) or text[i + 1] in ' "”’)' or (lang == 'es' and text[i + 1] == '»')


def align(spoken: str, timings, lang: str) -> list[float]:
    """Seconds from clip start at which each character of ``spoken`` is heard."""
    sounds, phone_marks = [], []
    for t in timings:
        if t.phoneme in PHONE_MARKS:
            if not phone_marks or phone_marks[-1] != len(sounds):     # "..." is one mark, as the text counts it
                phone_marks.append(len(sounds))
        elif t.phoneme not in NOT_SOUNDS:
            sounds.append(t.start)
    if not sounds:
        return [0.0] * len(spoken)
    text_marks = [i for i in range(len(spoken)) if _is_clause_mark(spoken, i, lang)]
    if len(text_marks) == len(phone_marks):
        cuts = list(zip([-1] + text_marks, text_marks + [len(spoken) - 1]))
        spans = list(zip([0] + phone_marks, phone_marks + [len(sounds)]))
    else:                                             # marks disagree: one proportional span
        cuts, spans = [(-1, len(spoken) - 1)], [(0, len(sounds))]
    times = [0.0] * len(spoken)
    for (t0, t1), (s0, s1) in zip(cuts, spans):
        chars = range(t0 + 1, t1 + 1)
        weights = [1.0 if spoken[i].isalnum() else 0.0 for i in chars]
        total = sum(weights) or 1.0
        s1 = max(s1, s0 + 1) if s0 < len(sounds) else s0
        acc = 0.0
        for i, w in zip(chars, weights):
            frac = (acc + w / 2) / total
            k = min(len(sounds) - 1, s0 + int(frac * max(1, s1 - s0)))
            times[i] = sounds[k]
            acc += w
    for i in range(1, len(times)):                    # never run backwards
        times[i] = max(times[i], times[i - 1])
    return [round(t, 3) for t in times]


# -------------------------------------------------------------- synthesis
def voice_name(voice_id: str) -> str:
    """The friendly name of a voice, or its id if it isn't listed."""
    return next((name for choices in VOICES.values() for vid, name in choices if vid == voice_id), voice_id)


def parse_lexicon(text: str) -> dict:
    """Pronunciations from one word = respelling per line."""
    lexicon = {}
    marks = ''.join(CLAUSE.values()) + PHONE_MARKS
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        word, sep, said = line.partition('=')
        said = said.strip().translate(str.maketrans('', '', marks)).strip()
        if not sep or not word.strip() or not said:
            raise ValueError(f'Line {n} of pronounce.txt should look like "word = how to say it", '
                             'for example "GIF = jif".')
        lexicon[word.strip()] = said
    return lexicon


def read_lexicon(path: Path) -> dict:
    """The project's pronunciations, or none when the file is missing."""
    path = Path(path)
    return parse_lexicon(path.read_text(encoding='utf-8')) if path.exists() else {}


def respell(text: str, lexicon: dict, lang: str) -> str:
    """Change spoken words while keeping the script's spelling elsewhere."""
    if not lexicon:
        return text
    if lang == 'en':        # "WHO" or "iPhone" matches only as typed, "Honey" or "C#" in any case; exact entries first
        exact = {key for key in lexicon if any(c.isupper() for c in key[1:])}
        loose = {key.lower(): said for key, said in lexicon.items() if key not in exact}
        keys = sorted(lexicon, key=lambda key: (-len(key), key not in exact))
        pattern = '|'.join(re.escape(key) if key in exact else f'(?i:{re.escape(key)})' for key in keys)
        return re.sub(r'(?<!\w)(?:' + pattern + r')(?!\w)',
                      lambda m: lexicon[m[0]] if m[0] in exact else loose[m[0].lower()], text)
    pattern = '|'.join(re.escape(key) for key in sorted(lexicon, key=len, reverse=True))
    return re.sub(pattern, lambda m: lexicon[m[0]], text)


def preview(voice_id: str, lang: str, speed: float = 1.0) -> Path:
    """A cached sample of a voice, using only models already on this computer."""
    if voice_id not in dict(VOICES.get(lang, [])):
        raise ValueError('Choose a voice for this language.')
    if not SPEEDS[0] <= speed <= SPEEDS[1]:
        raise ValueError('Speed should be between 0.85 and 1.15.')
    if missing_files(lang):
        size = 220 if lang == 'zh' else 190
        raise ValueError(f'The voices download with your first video (about {size} MB). '
                         'Make a video once, then you can hear every voice here.')
    text = {'en': 'Hi! I can read your script aloud, just like this.', 'zh': '你好！我可以像这样为你朗读脚本。',
            'es': '¡Hola! Puedo leer tu guion en voz alta, así.'}
    return synthesize(text[lang], lang, paths.cache_dir() / 'voice-samples', voice_id, speed).wav


def synthesize(spoken: str, lang: str, cache_dir: Path, voice: str | None = None, speed: float = 1.0,
               lexicon: dict | None = None) -> Clip:
    voice = voice or LANGS[lang]['voice']
    said = respell(spoken, lexicon, lang) if lexicon else spoken
    content = [VERSION, LANGS[lang]['model'], voice, speed, spoken] + ([said] if said != spoken else [])
    key = hashlib.sha256(json.dumps(content).encode()).hexdigest()[:16]     # times follow the caption spelling
    cache_dir = Path(cache_dir)
    wav, meta = cache_dir / f'{key}.wav', cache_dir / f'{key}.json'
    if wav.exists() and meta.exists():
        info = json.loads(meta.read_text(encoding='utf-8'))
        return Clip(wav, info['duration'], info['char_times'])
    audio, sr, timings = _engine(lang).create_timed(phonemes(said, lang), voice, speed=speed, is_phonemes=True)
    char_times = align(spoken, timings, lang)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
    duration = round(len(audio) / sr, 3)
    meta.write_text(json.dumps({'duration': duration, 'char_times': char_times, 'voice': voice, 'speed': speed,
                                'text': spoken, **({'said': said} if said != spoken else {})},
                               ensure_ascii=False), encoding='utf-8')
    return Clip(wav, duration, char_times)


# ------------------------------------------------------ several voices in one beat
PART_GAP = .15           # silence between two speakers inside one beat
EDGE_KEEP = (.03, .06)   # silence kept before and after a part where it meets another part
CUT_FADE = .015          # a line that breaks off ends this fast


def _voiced(audio: np.ndarray, rate: int, floor: float = .01) -> tuple[int, int]:
    loud = np.nonzero(np.abs(audio) > floor)[0]
    return (int(loud[0]), int(loud[-1]) + 1) if len(loud) else (0, len(audio))


def silence(seconds: float, chars: int, cache_dir: Path) -> Clip:
    """A beat with nothing to say (a title card, a stage direction): ``seconds`` of quiet."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav = cache_dir / f'silence-{round(seconds * 1000)}.wav'
    if not wav.exists():
        _write_wav(wav, np.zeros(round(seconds * SR), np.float32))
    return Clip(wav, round(seconds, 3), [0.0] * chars)


def speak(spoken: str, parts, lang: str, cache_dir: Path, speed: float = 1.0, lexicon: dict | None = None,
          hold: float | None = None) -> Clip:
    """One beat's clip from its voice parts (speech.voice_parts): [(Segment, voice, speed factor)], each read by its
    own voice and joined in order, with char_times for every character of ``spoken`` (labels and directions the
    voice skips take the time of the next word said). A plain beat (one narrator part reading the spoken text as it
    is) is exactly synthesize()'s clip."""
    from .speech import spoken_times
    if not parts:
        return silence(hold or .8, len(spoken), cache_dir)
    if len(parts) == 1 and parts[0][0].said == spoken and parts[0][0].speaker is None:
        seg, name, factor = parts[0]
        return synthesize(spoken, lang, cache_dir, name, round(speed * factor, 3), lexicon)
    cut = parts[-1][0].cut_off
    content = [VERSION, 'parts', LANGS[lang]['model'], speed, spoken, sorted((lexicon or {}).items()),
               [[seg.said, seg.index, name, factor] for seg, name, factor in parts], PART_GAP, EDGE_KEEP, cut]
    key = hashlib.sha256(json.dumps(content).encode()).hexdigest()[:16]
    cache_dir = Path(cache_dir)
    wav, meta = cache_dir / f'{key}.wav', cache_dir / f'{key}.json'
    speakers = (parts[0][0].speaker, parts[-1][0].speaker)
    if wav.exists() and meta.exists():
        info = json.loads(meta.read_text(encoding='utf-8'))
        return Clip(wav, info['duration'], info['char_times'], speakers, cut)
    pieces, times, index, at = [], [], [], 0.
    for k, (seg, name, factor) in enumerate(parts):
        clip = synthesize(seg.said, lang, cache_dir, name, round(speed * factor, 3), lexicon)
        audio = _read_wav(clip.wav)
        a, b = _voiced(audio, SR)
        first, last = k == 0, k == len(parts) - 1
        a = 0 if first else max(0, a - round(EDGE_KEEP[0] * SR))
        b = (b if cut else len(audio)) if last else min(len(audio), b + round(EDGE_KEEP[1] * SR))
        piece = audio[a:b].copy()
        if last and cut:
            n = min(len(piece), round(CUT_FADE * SR))
            piece[len(piece) - n:] *= np.linspace(1, 0, n, dtype=np.float32)
        if pieces:
            pieces.append(np.zeros(round(PART_GAP * SR), np.float32))
            at += PART_GAP
        pieces.append(piece)
        times += [max(0., t - a / SR) + at for t in clip.char_times]
        index += seg.index
        at += len(piece) / SR
    audio = np.concatenate(pieces)
    char_times = spoken_times(spoken, index, times)
    duration = round(len(audio) / SR, 3)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _write_wav(wav, audio)
    meta.write_text(json.dumps({'duration': duration, 'char_times': char_times, 'text': spoken,
                                'parts': [{'speaker': seg.speaker, 'voice': name, 'speed': round(speed * factor, 3),
                                           'said': seg.said} for seg, name, factor in parts], 'cut_off': cut},
                               ensure_ascii=False), encoding='utf-8')
    return Clip(wav, duration, char_times, speakers, cut)


# ------------------------------------------------------ pacing (speech.pace)
PACE_VERSION = 1         # bump when paced() changes (invalidates its cached clips)
QUIET = .01              # a 10 ms frame under this peak is voice-free (-40 dBFS)
NEXT_LEAD = .08          # voice-free time a synthesized beat typically starts with (measured .05-.10 s)


def _quiet_frames(audio: np.ndarray) -> np.ndarray:
    n = SR // 100
    frames = len(audio) // n
    return np.abs(audio[:frames * n]).reshape(frames, n).max(1) < QUIET if frames else np.zeros(0, bool)


def quiet_ends(wav: Path) -> tuple[float, float]:
    """Voice-free seconds at the start and the end of a clip."""
    audio = _read_wav(wav)
    a, b = _voiced(audio, SR, QUIET)
    return (a / SR, (len(audio) - b) / SR) if b > a else (len(audio) / SR, len(audio) / SR)


def paced(clip: Clip, spoken: str, stops, cache_dir: Path) -> Clip:
    """``clip`` with silence added where speech.pace asks for more voice-free time than the voice left: [(pos, gap,
    anchor, step)]. Inside the beat the silence goes into the middle of the quiet run before the word at ``pos`` (its
    characters and every later one move with it); at pos == len(spoken) it is added after the beat (less the GAP the
    timeline adds and the next beat's own lead), never after a line that breaks off for the next speaker."""
    if not stops or not Path(clip.wav).exists() or len(clip.char_times) != len(spoken):
        return clip
    key = hashlib.sha256(json.dumps([PACE_VERSION, Path(clip.wav).name, clip.duration, stops]).encode()
                         ).hexdigest()[:16]
    cache_dir = Path(cache_dir)
    wav, meta = cache_dir / f'paced-{key}.wav', cache_dir / f'paced-{key}.json'
    if wav.exists() and meta.exists():
        info = json.loads(meta.read_text(encoding='utf-8'))
        return Clip(wav, info['duration'], info['char_times'], clip.speakers, clip.cut_off)
    audio = _read_wav(clip.wav)
    quiet = _quiet_frames(audio)
    ct = list(clip.char_times)
    inserts = []                                      # (sample, seconds, first character that moves)
    for pos, gap, anchor, step in stops:
        if pos >= len(spoken):
            if clip.cut_off:
                continue
            tail = (len(audio) - _voiced(audio, SR, QUIET)[1]) / SR
            extra = gap - tail - GAP - NEXT_LEAD
            if extra > .01:
                inserts.append((len(audio), extra, len(spoken)))
            continue
        t_next = ct[pos]
        before = [ct[j] for j in range(pos) if spoken[j].isalnum() and ct[j] < t_next]
        if not before:                                # a pause before the first word: after the last beat's tail
            lead = _voiced(audio, SR, QUIET)[0] / SR
            extra = gap - lead - GAP - .28
            if extra > .01:
                inserts.append((0, extra, 0))
            continue
        lo, hi = int(max(before) * 100), min(len(quiet), int(t_next * 100) + 10)
        best, k = (int(t_next * 100), int(t_next * 100)), lo
        while k < hi:                                 # the longest quiet run between the two words
            if quiet[k]:
                j = k
                while j < len(quiet) and quiet[j]:
                    j += 1
                if j - k > best[1] - best[0]:
                    best = (k, j)
                k = j
            else:
                k += 1
        q, onset = (best[1] - best[0]) / 100, best[1] / 100
        extra = gap - q
        if anchor is not None and step:
            extra = max(extra, step - (onset - ct[anchor]))
        if extra > .01:
            inserts.append((round((best[0] + best[1]) / 2 * SR / 100), extra, pos))
    if not inserts:
        return clip
    pieces, last = [], 0
    for at, seconds, _ in sorted(inserts):
        pieces += [audio[last:at], np.zeros(round(seconds * SR), np.float32)]
        last = at
    pieces.append(audio[last:])
    out = np.concatenate(pieces)
    char_times = [round(t + sum(s for _, s, first in inserts if i >= first), 3) for i, t in enumerate(ct)]
    duration = round(len(out) / SR, 3)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _write_wav(wav, out)
    meta.write_text(json.dumps({'duration': duration, 'char_times': char_times, 'stops': stops}), encoding='utf-8')
    return Clip(wav, duration, char_times, clip.speakers, clip.cut_off)


# ------------------------------------------------------ your own recording
HOP, WIN = 240, 600      # analysis frames: every 10 ms, 25 ms long
RECORDING_VERSION = 4    # bump when recording alignment changes (invalidates cached cuts)
TAKE_SR = 48000          # the clips keep the take's full sound (the mix's rate); only the alignment runs at SR
STEP = .05               # extra cost of a frame only one side advances on (keeps the warp from zigzagging)
EDGE = 6                 # frames of quiet kept before and after each beat
SNAP = 30                # frames a cut may move from where the alignment put it, to land in a pause
PAUSE = 10               # quiet stretches shorter than this are inside words (stop consonants)
MATCH = .4               # a reading of the script matches its guide at .45 or more, other words at about .35
SHORT, SHORTISH, WEAK = .5, .65, .8   # a beat left out of the take: its cut holds under SHORT of the speech its
                         # text predicts at the take's usual pace, or under SHORTISH while matching under WEAK of the
                         # take's usual match (80 whole readings in 13 voices: speech never under .70; .72 at .76 match)
FIT = .06                # a sentence fitting the take this much worse than the take's typical sentence: check
SCALES = (.7, .75, .8, .85, .9, .95, 1., 1.05, 1.1, 1.15, 1.2)    # the take's formants against the guide's


class RecordingError(ValueError):
    """Your recording cannot narrate this script; the message says what is wrong and what to do (no traceback).
    ``beat``: the part of the script it is about, if one (the Studio marks that part's sentences); ``plain``: the
    message without the command-line advice the voice step adds to it (the Studio has its own)."""

    def __init__(self, message: str, beat: str | None = None, plain: str | None = None):
        super().__init__(message)
        self.beat, self.plain = beat, plain or message


def _decode(path: Path, rate: int = SR, clean: bool = False) -> np.ndarray:
    """Any audio file (read as a local file only) as mono float32 at ``rate``, high-passed at 80 Hz; ``clean``: with
    its background noise reduced too (_clean)."""
    run = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-protocol_whitelist', 'file',
                          '-i', str(path), '-af', 'highpass=f=80',
                          '-ac', '1', '-ar', str(rate), '-f', 'f32le', '-'], capture_output=True)
    if run.returncode or not run.stdout:
        why = run.stderr.decode(errors='replace').strip()[-300:]
        raise RecordingError(f'Your recording ({path.name}) could not be read as audio: {why}. '
                             'Save it as WAV, M4A or MP3 and try again.')
    audio = np.frombuffer(run.stdout, np.float32).copy()
    return _clean(audio, rate) if clean else audio


def _clean(audio: np.ndarray, rate: int) -> np.ndarray:
    """Your recording with its background noise (hiss, hum, a fan) reduced: FFmpeg's FFT denoiser (afftdn) learns the
    noise from the take's own quietest half second, then a gentle gate (at most 12 dB, ratio 2) lowers what is left
    between phrases. Speech keeps its level (tests/test_recording.py measures both). Only recordings come here: the
    AI voices are never cleaned."""
    half, hop, late = rate // 2, rate // 100, int(rate * .025)    # afftdn outputs 25 ms late (FFmpeg 7.1, any rate)
    n = len(audio) // hop
    if n < 100:                                    # under a second: nothing to learn the noise from
        return audio
    power = (audio[:n * hop].reshape(n, hop).astype(np.float64) ** 2).mean(1)
    window = np.convolve(power, np.ones(50), 'valid') / 50          # every half second, in 10 ms steps
    k = int(np.argmin(window))
    floor, loud = 10 * np.log10(window[k] + 1e-12), 10 * np.log10(np.percentile(power, 95) + 1e-12)
    nf = float(np.clip(min(floor, loud - 25), -80, -20))
    gate = 10 ** (min(floor + 10, loud - 20) / 20)  # over the noise, and well under the speech
    chain = (f"asendcmd=c='0 afftdn sn start; 0.5 afftdn sn stop',afftdn=nr=30:nf={nf:.1f}:rf=-60,"
             f"atrim=start_sample={half + late},"
             f"agate=threshold={gate:.7f}:range=0.25:ratio=2:attack=10:release=250")
    sample = audio[k * hop:k * hop + half]          # the quiet half second first, to learn from; trimmed off after
    run = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'f32le', '-ar', str(rate), '-ac', '1',
                          '-i', '-', '-af', chain, '-f', 'f32le', '-ar', str(rate), '-ac', '1', '-'],
                         input=np.concatenate([sample, audio, sample[:late]]).astype(np.float32).tobytes(),
                         capture_output=True)       # and 25 ms more at the end, so the take's own end comes out
    if run.returncode or not run.stdout:
        raise RuntimeError('cleaning the recording failed: ' + run.stderr.decode(errors='replace').strip()[-300:])
    out = np.frombuffer(run.stdout, np.float32)[:len(audio)]
    return np.pad(out, (0, len(audio) - len(out))).astype(np.float32)


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float32) / 32768


def _write_wav(path: Path, audio: np.ndarray, rate: int = SR):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())


@lru_cache(maxsize=16)
def _mel_cepstra(scale: float = 1.0):
    """Matrices from a 1024-point power spectrum to 40 mel bands (60 Hz to 7.6 kHz, times ``scale``), and from log mel
    to cepstra 1-12."""
    mel = np.linspace(*2595 * np.log10(1 + np.array([60, 7600]) / 700), 42)
    edges = 700 * (10 ** (mel / 2595) - 1) * scale
    hz = np.fft.rfftfreq(1024, 1 / SR)
    lo, mid, hi = edges[:-2, None], edges[1:-1, None], edges[2:, None]
    bands = np.maximum(0, np.minimum((hz - lo) / (mid - lo), (hi - hz) / (hi - mid)))
    dct = np.cos(np.pi / 40 * np.arange(1, 13)[:, None] * (np.arange(40) + .5))
    return bands.T.astype(np.float32), dct.T.astype(np.float32)


def _spectrum(x: np.ndarray):
    """Level (dB) and power spectrum of every frame."""
    n = len(x) // HOP + 1
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, (WIN // 2, WIN)), WIN)[::HOP][:n]
    window = np.hanning(WIN).astype(np.float32)
    level, power = np.empty(n, np.float32), np.empty((n, 513), np.float32)
    for a in range(0, n, 4096):                   # in blocks: a long take never holds all its complex spectra
        f = frames[a:a + 4096]
        level[a:a + 4096] = 10 * np.log10((f ** 2).mean(1) + 1e-10)
        power[a:a + 4096] = np.abs(np.fft.rfft(f * window, 1024)) ** 2
    return level, power


def _cepstra(power: np.ndarray, scale: float = 1.0) -> np.ndarray:
    bands, dct = _mel_cepstra(scale)
    return np.log(power @ bands + 1e-8) @ dct


def _quiet(level: np.ndarray):
    """Two levels (dB): under the first a frame is room tone, under the second silence; each a little over the
    noise floor, and never far under speech."""
    floor, loud = np.percentile(level, [5, 95])
    return float(max(floor + 3, loud - 50)), float(min(max(floor + 6, loud - 35), loud - 10))


def _features(level, ceps, quiet) -> np.ndarray:
    """Unit vectors for cosine costs: on speech the normalized cepstra and their slopes, on silence one shared
    direction, so pauses of any length match each other and never match words."""
    speech = level > quiet
    z = (ceps - ceps[speech].mean(0)) / (ceps[speech].std(0) + 1e-6)
    p = np.pad(z, ((2, 2), (0, 0)), mode='edge')
    slope = (p[3:-1] - p[1:-3] + 2 * (p[4:] - p[:-4])) / 10
    s = np.clip((quiet + 3 - level) / 6, 0, 1)[:, None]          # 1 when silent, easing in over 6 dB
    f = np.hstack([z * (1 - s), slope * (1 - s), s * np.sqrt(z.shape[1])])
    return f / (np.linalg.norm(f, axis=1, keepdims=True) + 1e-9)


def _dtw(G, R, lo, hi) -> np.ndarray:
    """Cheapest path of (guide frame, recording frame) pairs from the first frames of both to their last, through
    costs 1 - G[i]·R[j]; each step moves on one frame along the guide, the recording, or both. Row i only visits
    columns lo[i]:hi[i]."""
    m = len(R)
    prev, moves = np.full(m + 1, np.inf), []       # prev[j + 1]: cheapest way to (i - 1, j)
    prev[0] = 0.
    for i, g in enumerate(G):
        a, b = lo[i], hi[i]
        c = 1 - R[a:b] @ g
        diag, down = prev[a:b] + 2 * c, prev[a + 1:b + 1] + c + STEP
        best = np.minimum(diag, down)
        along = np.cumsum(c + STEP)                # x[j] = min(best[j], x[j - 1] + c[j] + STEP) as a running minimum
        v = best - along
        run = np.minimum.accumulate(v)
        prev = np.full(m + 1, np.inf)
        prev[a + 1:b + 1] = run + along
        moves.append((a, np.where(run < v, 2, down < diag).astype(np.uint8)))
    i, j, path = len(G) - 1, m - 1, []
    while i >= 0:
        path.append((i, j))
        a, move = moves[i]
        k = move[j - a]
        i, j = i - (k != 2), j - (k != 1)
    return np.array(path[::-1])


def _pool(F: np.ndarray, f: int) -> np.ndarray:
    F = np.pad(F, ((0, -len(F) % f), (0, 0)), mode='edge').reshape(-1, f, F.shape[1]).mean(1)
    return F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)


def _costs(G, R, path) -> np.ndarray:
    return 1 - np.einsum('ij,ij->i', G[path[:, 0]], R[path[:, 1]])


def _warp(G, level, power, quiet, f=4, radius=30):
    """The DTW path from the guide's frames to the take's. Over all frames at 40 ms first, once for each vocal tract
    scale in SCALES (the cheapest path wins: a deeper voice than the guide's puts its formants lower), then at 10 ms
    within ``radius`` frames of it. Returns the path, the take's features and the scale."""
    g, best = _pool(G, f), None
    for scale in SCALES:
        R = _features(level, _cepstra(power, scale), quiet)
        r = _pool(R, f)
        coarse = _dtw(g, r, np.zeros(len(g), int), np.full(len(g), len(r)))
        cost = _costs(g, r, coarse).mean()
        if best is None or cost < best[0]:
            best = cost, R, coarse, scale
    _, R, coarse, scale = best
    lo, hi = np.full(len(g), len(R)), np.zeros(len(g), int)
    np.minimum.at(lo, coarse[:, 0], coarse[:, 1])
    np.maximum.at(hi, coarse[:, 0], coarse[:, 1] + 1)
    lo = np.clip(np.minimum.accumulate(np.repeat(lo * f - radius, f)[:len(G)][::-1])[::-1], 0, len(R) - 1)
    hi = np.clip(np.maximum.accumulate(np.repeat(hi * f + radius, f)[:len(G)]), 1, len(R))
    lo[0], hi[-1] = 0, len(R)
    return _dtw(G, R, lo, hi), R, float(scale)


def _fit(G, R, path, cost, speech) -> np.ndarray:
    """For every step of the path, the share of the take's speech that its guide frame resembles less than the take
    frame it was aligned to. A sentence read as written fits at about .9, other words at about .8 and a skipped
    sentence at about .55; the level shifts with the voice, so each sentence is compared with the take's typical one."""
    pool = R[np.flatnonzero(speech)]
    pool = pool[::max(1, len(pool) // 2000)].T
    out = np.empty(len(path), np.float32)
    for a in range(0, len(path), 4096):            # in blocks: a long take never holds every comparison at once
        p = path[a:a + 4096]
        out[a:a + 4096] = (G[p[:, 0]] @ pool < 1 - cost[a:a + 4096, None]).mean(1)
    return out


def _pauses(level, quiet) -> list:
    """Quiet runs (first frame, frame after) of at least PAUSE frames; the take's edges count as quiet."""
    edges = np.flatnonzero(np.diff(np.r_[True, level < quiet, True].astype(np.int8)))
    runs = zip(np.r_[-1, edges[1::2]], np.r_[edges[::2], len(level) + 1])
    return [(int(s), int(e)) for s, e in runs if e - s >= PAUSE or s < 0 or e > len(level)]


def _power(level, quiet) -> float:
    """Mean power of the frames above ``quiet``."""
    loud = level[level > quiet]
    return float(np.mean(10 ** (loud / 10))) if len(loud) else 0.


def _pause_between(pauses, level, a, b):
    """The pause to cut in between beats the alignment put frames a and b apart: the longest one overlapping a..b,
    else the nearest within SNAP, else (in unbroken speech) the quietest frame there."""
    lo, hi = min(a, b), max(a, b) + 1
    near = [(s, e) for s, e in pauses if e > lo - SNAP and s < hi + SNAP]
    over = [(s, e) for s, e in near if e > lo and s < hi]
    if over:
        return max(over, key=lambda p: p[1] - p[0])
    if near:
        return min(near, key=lambda p: max(lo - p[1], p[0] - hi))
    lo, hi = max(0, lo - SNAP), min(len(level), hi + SNAP)
    k = int(lo + np.argmin(level[lo:hi]))
    return k, k


def _quote(text: str, n: int = 50) -> str:
    """The first words of a beat, cut at a word (en) or a character (zh)."""
    text = ' '.join(text.split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(' ', 1)[0] if ' ' in text[:n] else text[:n]
    return cut.rstrip(',.;:，。；：') + '…'


def _said(text: str) -> str:
    """A beat's first words in quotes, ending a sentence: a full stop only if the words don't end one already."""
    quote = _quote(text)
    return f'"{quote}"' + ('' if quote.endswith(tuple('.!?…。！？')) else '.')


def from_recording(recording, beats, lang: str, cache_dir: Path, voice: str | None = None,
                   speed: float = 1.0, lexicon: dict | None = None, clean: bool = True) -> dict:
    """Clips like synthesize()'s, cut from one continuous reading of the script; ``beats`` is [(beat id, spoken
    text)] in order. Kokoro reads the beats as a guide, aligned to the take frame by frame (dynamic time warping):
    every cut lands in a pause, every character time follows the take, and each clip gets its guide's speech level.
    Writes recording-align.json next to the cache: where each beat and each sentence was found, and how well it
    matched; a sentence that fits the take clearly worse than the rest (skipped, or other words) is marked check.
    ``clean``: background noise is reduced first (_clean), so the alignment and the clips both use the cleaned take."""
    recording, cache_dir = Path(recording), Path(cache_dir)
    voice = voice or LANGS[lang]['voice']
    digest = hashlib.sha256(recording.read_bytes()).hexdigest()
    content = [VERSION, RECORDING_VERSION, LANGS[lang]['model'], voice, speed, digest, [list(b) for b in beats]]
    if lexicon:
        content.append(sorted(lexicon.items()))
    if clean:
        content.append('clean-2')                  # bump when _clean changes (invalidates cached cuts)
    key = hashlib.sha256(json.dumps(content).encode()).hexdigest()[:16]
    out, report = cache_dir / 'recording', cache_dir / 'recording-align.json'
    meta = out / f'{key}.json'
    if meta.exists():
        info = json.loads(meta.read_text(encoding='utf-8'))
        report.write_text(json.dumps(info['report'], ensure_ascii=False, indent=1), encoding='utf-8')
        return {c['id']: Clip(out / c['wav'], c['duration'], c['char_times']) for c in info['clips']}

    guides = [synthesize(text, lang, cache_dir, voice, speed, lexicon) for _, text in beats]
    pieces = [_read_wav(g.wav) for g in guides]
    offsets = np.cumsum([0] + [len(p) for p in pieces])
    take = _decode(recording, clean=clean)
    gl, gp = _spectrum(np.concatenate(pieces))
    tl, tp = _spectrum(take)
    (_, gq), (tr, tq) = _quiet(gl), _quiet(tl)
    said, script = (tl > tq).sum() / 100, (gl > gq).sum() / 100
    if not script / 2 <= said <= script * 2:
        raise RecordingError(f'Your recording has {said:.0f} s of speech, but this script takes about {script:.0f} s '
                             'to read. Record the whole script, once through, and try again.')
    G = _features(gl, _cepstra(gp), gq)
    path, R, scale = _warp(G, tl, tp, tq)
    _, at = np.unique(path[:, 0], return_index=True)
    first, last = path[at, 1], path[np.r_[at[1:], len(path)] - 1, 1]
    cost = _costs(G, R, path)

    spans = []                                     # each beat's speech in the guide, in frames
    for k in range(len(beats)):
        a, b = -(-offsets[k] // HOP), offsets[k + 1] // HOP
        loud = a + np.flatnonzero(gl[a:b] > gq)
        spans.append((loud[0], loud[-1]) if len(loud) else (a, b - 1))
    pauses = _pauses(tl, tq)
    long = [p for p in pauses if p[1] - p[0] >= SNAP or p[0] < 0 or p[1] > len(tl)]   # sets off a cough or a click
    cuts = [max((p for p in long if p[0] < first[spans[0][0]]), key=lambda p: p[1])]
    for (_, e), (s, _) in zip(spans, spans[1:]):
        cuts.append(_pause_between(pauses, tl, last[e], first[s]))
    cuts.append(min((p for p in long if p[1] > last[spans[-1][1]]), key=lambda p: p[0]))
    room = tl > tr                                 # anything over room tone stays: soft endings, releases, breaths
    full, hop = _decode(recording, TAKE_SR, clean), TAKE_SR // 100

    clips, rows, sounds, paces = [], [], [], []
    for k, ((bid, text), guide, (gs, ge)) in enumerate(zip(beats, guides, spans)):
        a, b = max(0, sum(cuts[k]) // 2), min(len(tl), sum(cuts[k + 1]) // 2)     # the middles of the pauses
        sound = a + np.flatnonzero(room[a:b])
        heard = _power(tl[a:b], tq)
        if b - a < PAUSE or not heard:            # nothing of it heard: left out, like a beat with too little speech
            start = end = a                        # (no speech, so marked missing below, whichever way it was cut)
        else:
            start, end = max(a, sound[0] - EDGE), min(b, sound[-1] + 1 + EDGE)
        audio = full[start * hop:end * hop]
        gain = np.sqrt(_power(gl[gs:ge + 1], gq) / heard) if heard else 1.
        sounds.append(audio * min(gain, .99 / max(float(np.abs(audio).max(initial=0)), 1e-6)))
        t = (offsets[k] / SR + np.asarray(guide.char_times)) * 100
        i0 = np.clip(t.astype(int), 0, len(first) - 2)
        j = first[i0] + np.clip(t - i0, 0, 1) * np.minimum(1, first[i0 + 1] - first[i0])
        char_times = np.maximum.accumulate(np.clip((j - start) / 100, 0, len(audio) / TAKE_SR))
        clips.append({'id': bid, 'wav': f'{key}-{k:03}.wav', 'duration': round(len(audio) / TAKE_SR, 3),
                      'char_times': [round(float(x), 3) for x in char_times]})
        on = (path[:, 0] >= gs) & (path[:, 0] <= ge) & (gl[path[:, 0]] > gq)
        match = round(1 - float(cost[on].mean()), 2)
        paces.append((tl[start:end] > tq).sum() / max(1, (gl[gs:ge + 1] > gq).sum()))
        rows.append({'id': bid, 'start': round(start / 100, 2), 'end': round(end / 100, 2), 'match': match,
                     'check': match < MATCH, 'pause_before': bool(cuts[k][0] < cuts[k][1])})
    usual_pace = max(float(np.median(paces)), 1e-6)
    usual_match = max(float(np.median([r['match'] for r in rows])), 1e-6)
    for row, pace in zip(rows, paces):
        row['speech'] = round(float(pace) / usual_pace, 2)
        row['missing'] = row['speech'] < SHORT or (row['speech'] < SHORTISH and row['match'] / usual_match < WEAK)
    fits, sentences = _fit(G, R, path, cost, tl > tq), []
    for k, ((bid, text), guide) in enumerate(zip(beats, guides)):
        at = 0
        for line in sentences_of(text, lang):      # the sentences the Studio shows to read aloud
            c = text.index(line, at)
            at = c + len(line)
            t = np.array([guide.char_times[c], guide.char_times[at] if at < len(text) else guide.duration])
            a, b = ((offsets[k] + t * SR) // HOP).astype(int)
            loud = a + np.flatnonzero(gl[a:b] > gq)
            gs, ge = (loud[0], loud[-1]) if len(loud) else (a, max(a, b - 1))
            on = (path[:, 0] >= gs) & (path[:, 0] <= ge)
            heard = on & (gl[path[:, 0]] > gq)
            on = heard if heard.any() else on
            sentences.append({'beat': bid, 'text': line, 'start': round(first[gs] / 100, 2),
                              'end': round(last[ge] / 100, 2), 'match': round(1 - float(cost[on].mean()), 2),
                              'fit': round(float(fits[on].mean()), 3)})
    typical = float(np.median([s['fit'] for s in sentences]))
    for s in sentences:
        s['check'] = s['fit'] < typical - FIT
    on = gl[path[:, 0]] > gq
    info = {'clips': clips, 'report': {
        'recording': str(recording), 'sha256': digest, 'seconds': round(len(take) / SR, 2), 'cleaned': clean,
        'speech_ratio': round(said / script, 2), 'voice_scale': scale, 'match': round(1 - float(cost[on].mean()), 2),
        'note': f'match: about 0.35 for unrelated speech, 0.45 or more for a reading of the script; beats under '
                f'{MATCH} are marked check, and sentences whose fit is {FIT} under the typical sentence\'s. speech: the '
                f'speech heard in the beat\'s cut over what its text predicts, at the take\'s usual pace (1 is usual); '
                f'under {SHORT} (or {SHORTISH} with a weak match) the beat is missing from the take',
        'beats': rows, 'sentences': sentences}}
    report.write_text(json.dumps(info['report'], ensure_ascii=False, indent=1), encoding='utf-8')
    if info['report']['match'] < MATCH:
        raise RecordingError(f"Your recording does not sound like a reading of this script (match "
                             f"{info['report']['match']:.2f}, under {MATCH}). Record this script, as written, and "
                             f"try again; where each part was heard: {report}", None,
                             'Your recording does not sound like a reading of this script. Record this script, as '
                             'written, and try again.')
    missing = [k for k, row in enumerate(rows) if row['missing']]
    if missing:                                    # the first: when parts are left out together, how the alignment
        bid, text = beats[missing[0]]              # shares their pause between them turns on tiny differences
        raise RecordingError(f'Part of the script seems to be missing from your recording, around the part that says '
                             f'{_said(text)} Read the whole script once through, every sentence as '
                             'written, and try again.', bid)
    out.mkdir(parents=True, exist_ok=True)
    for c, audio in zip(clips, sounds):
        _write_wav(out / c['wav'], audio, TAKE_SR)
    meta.write_text(json.dumps(info, ensure_ascii=False), encoding='utf-8')
    return {c['id']: Clip(out / c['wav'], c['duration'], c['char_times']) for c in info['clips']}

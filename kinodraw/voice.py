"""Local narration with Kokoro (82M, Apache-2.0) through kokoro-onnx.

One clip per beat, cached by content hash, plus the time at which every character
of the spoken text is heard (for captions and drawing triggers). Timing comes
from the model's own phoneme durations: clause marks anchor each clause, and
within a clause letters map proportionally onto the spoken phonemes.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import platformdirs

from .net import download

MODEL_DIR = Path(os.environ.get('DOODLE_MODELS') or Path(platformdirs.user_data_dir('DoodleStudio')) / 'models').expanduser()
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
    'zh': {'model': 'kokoro-v1.1-zh.fp16.onnx', 'voices': 'voices-v1.1-zh.bin', 'config': 'config-v1.1-zh.json',
           'voice': 'zf_001'},
}
SR = 24000
GAP = .4                 # silence after each beat
VERSION = 1              # bump when synthesis or alignment changes (invalidates cached clips)
CLAUSE = {'en': ',.;:?!—', 'zh': '，。；：？！、—'}
PHONE_MARKS = ',.;:?!—…'
NOT_SOUNDS = set(' ˈˌːʲ')


@dataclass
class Clip:
    wav: Path
    duration: float              # seconds of audio (the timeline adds GAP after it)
    char_times: list


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
        short = Path(platformdirs.user_cache_dir('DoodleStudio')) / 'espeak-ng-data'
        if not (short / 'phontab').exists():
            shutil.copytree(data, short, dirs_exist_ok=True)
        data = short
    return EspeakConfig(data_path=str(data))


@lru_cache(maxsize=2)
def _engine(lang: str):
    import onnxruntime
    onnxruntime.set_default_logger_severity(3)       # fp16 graphs log many harmless constant-folding warnings
    from kokoro_onnx import Kokoro
    ensure_models(lang)
    spec = LANGS[lang]
    config = str(MODEL_DIR / spec['config']) if spec['config'] else None
    return Kokoro(str(MODEL_DIR / spec['model']), str(MODEL_DIR / spec['voices']), espeak_config=_espeak_config(),
                  vocab_config=config)


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
    return _engine('en').tokenizer.phonemize(text, 'en-us')


# --------------------------------------------------------------- alignment
def _is_clause_mark(text: str, i: int, lang: str) -> bool:
    ch = text[i]
    if ch not in CLAUSE[lang]:
        return False
    return lang == 'zh' or ch == '—' or i + 1 == len(text) or text[i + 1] in ' "”’)'


def align(spoken: str, timings, lang: str) -> list[float]:
    """Seconds from clip start at which each character of ``spoken`` is heard."""
    sounds, phone_marks = [], []
    for t in timings:
        if t.phoneme in PHONE_MARKS:
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
def synthesize(spoken: str, lang: str, cache_dir: Path, voice: str | None = None, speed: float = 1.0) -> Clip:
    voice = voice or LANGS[lang]['voice']
    key = hashlib.sha256(json.dumps([VERSION, LANGS[lang]['model'], voice, speed, spoken]).encode()).hexdigest()[:16]
    cache_dir = Path(cache_dir)
    wav, meta = cache_dir / f'{key}.wav', cache_dir / f'{key}.json'
    if wav.exists() and meta.exists():
        info = json.loads(meta.read_text())
        return Clip(wav, info['duration'], info['char_times'])
    audio, sr, timings = _engine(lang).create_timed(phonemes(spoken, lang), voice, speed=speed, is_phonemes=True)
    char_times = align(spoken, timings, lang)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
    duration = round(len(audio) / sr, 3)
    meta.write_text(json.dumps({'duration': duration, 'char_times': char_times, 'voice': voice, 'speed': speed,
                                'text': spoken}, ensure_ascii=False))
    return Clip(wav, duration, char_times)

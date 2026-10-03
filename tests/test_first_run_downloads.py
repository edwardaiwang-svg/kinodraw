"""A first video downloads the voice (~192 MB for English) and the doodle search (~67 MB) once: the user sees
megabytes and a percentage instead of a bar stuck at "Starting"."""
import hashlib
import io
from pathlib import Path

from doodlestudio import cli, director, net, pipeline, voice
from doodlestudio.director import match
from doodlestudio.studio import server

TINY = Path(__file__).parent / 'fixtures' / 'tiny.md'


def test_the_voice_download_reports_bytes_over_all_its_files(tmp_path, monkeypatch):
    blobs = {'https://models.example/model': b'm' * 3_000_000, 'https://models.example/voices': b'v' * 1_500_000}
    monkeypatch.setattr(voice, 'MODEL_DIR', tmp_path)
    monkeypatch.setattr(voice, 'FILES', {
        'kokoro-v1.0.fp16.onnx': ('https://models.example/model', hashlib.sha256(blobs['https://models.example/model']).hexdigest(), 3_000_000),
        'voices-v1.0.bin': ('https://models.example/voices', hashlib.sha256(blobs['https://models.example/voices']).hexdigest(), 1_500_000)})
    monkeypatch.setattr(net, 'urlopen', lambda url: io.BytesIO(blobs[url]))
    seen = []
    voice.ensure_models('en', lambda done, total: seen.append((done, total)))
    assert {total for _, total in seen} == {4_500_000}                 # the whole download, from the first report
    assert seen[-1] == (4_500_000, 4_500_000) and [d for d, _ in seen] == sorted(d for d, _ in seen)
    assert not voice.missing_files('en')


def test_making_a_video_reports_both_downloads_as_stages(tmp_path, monkeypatch):
    project = tmp_path / 'Honey'
    pipeline.new_project(TINY, project)
    seen = []
    real = match.ensure_model
    monkeypatch.setattr(match, 'ensure_model', lambda lang, progress=None: (progress and progress(5, 67), real(lang))[1])
    director.direct(project, 'rules', progress=lambda *a: seen.append(a))
    monkeypatch.setattr(voice, 'ensure_models', lambda lang, progress=None: progress(96, 192))
    monkeypatch.setattr(voice, 'synthesize', lambda *a, **k: voice.Clip(tmp_path / 'x.wav', 1.0, []))
    pipeline.narrate(project, lambda *a: seen.append(a))
    assert ('download-search', 5, 67) in seen and ('download-voice', 96, 192) in seen


def test_the_cli_and_the_studio_show_megabytes_and_percent(capsys):
    cli._progress('download-voice', 96_000_000, 191_742_359)
    assert capsys.readouterr().out == '\rdownloading the voice: 96/192 MB (50%)'
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert "'download-voice': 'Downloading the voice" in js and "'download-search': 'Downloading the doodle search" in js
    assert 'MB (${Math.floor(frac * 100)}%)' in js

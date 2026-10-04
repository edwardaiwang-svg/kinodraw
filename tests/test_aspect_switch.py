"""A saved format switch re-lays the drawings while reusing the real voice cache."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from kinodraw import cli, pipeline, styles, voice

TINY = Path(__file__).parent / 'fixtures' / 'tiny.md'
FRAME_TIMES = (.5, 2., 5., 10., 15., 20.)


@pytest.fixture
def fake_voice(monkeypatch):
    calls = []
    class Engine:
        def create_timed(self, text, voice_id, **kwargs):
            calls.append((text, voice_id, kwargs))
            return np.zeros(int(24000 * .06 * len(text)), np.float32), 24000, None
    monkeypatch.setattr(voice, 'ensure_models', lambda *a, **k: None)
    monkeypatch.setattr(voice, 'phonemes', lambda text, lang: text)
    monkeypatch.setattr(voice, 'align', lambda text, timings, lang: [round(i * .06, 3) for i in range(len(text))])
    monkeypatch.setattr(voice, '_engine', lambda lang: Engine())
    # Silent fake clips have infinite loudness measurements; mastering is outside this cache/layout test.
    monkeypatch.setattr(pipeline.audio, 'loudness', lambda path: {
        'input_i': '-18', 'input_tp': '-1.5', 'input_lra': '0', 'input_thresh': '-28', 'target_offset': '0'})
    return calls


def forbid_synthesis(monkeypatch):
    def uncached(lang):
        pytest.fail('a format switch reached the synthesis engine instead of reusing cached clips')
    monkeypatch.setattr(voice, '_engine', uncached)


@pytest.mark.parametrize('portrait', ['letterbox', 'native'])
def test_cli_aspect_round_trip_reuses_voice_and_restores_landscape(tmp_path, monkeypatch, fake_voice, portrait):
    if portrait == 'native':
        monkeypatch.setattr(styles, 'portrait', lambda look: 'native')
    else:
        assert styles.portrait('whiteboard') == 'letterbox'
    encoded, published, muxed = [], [], []
    def encode(prod, start, n, path, crf):
        frames = [prod.frame(t).convert('RGB') for t in FRAME_TIMES]
        assert all(frame.size == prod.size for frame in frames)
        encoded.append({'size': prod.size,
                        'frames': [hashlib.sha256(frame.tobytes()).hexdigest() for frame in frames]})
        path.write_bytes(b'silent render placeholder')
    def mux(tl, silent, mixed, video, lang, title, build):
        muxed.append((video.name, title))
        video.write_bytes(b'finished video placeholder')
    monkeypatch.setattr(pipeline.renderer, 'encode', encode)
    monkeypatch.setattr(pipeline.audio, 'mix', lambda board, tl, build: build / tl['audio'])
    monkeypatch.setattr(pipeline, 'mux', mux)
    monkeypatch.setattr(pipeline, 'encoded_qa', lambda *a, **k: {'ok': True, 'problems': []})
    monkeypatch.setattr(pipeline, 'publish', lambda *a, **k: published.append((a[5], k['size'])))
    monkeypatch.setattr(pipeline, 'contact_sheet', lambda *a, **k: None)

    project = tmp_path / 'project'
    report = pipeline.make(TINY, project, workers=1)
    assert report['ok']
    assert fake_voice
    initial_calls = len(fake_voice)
    title = pipeline.storyboard(project)['title']['en']
    timeline = project / 'build' / 'timeline.json'
    landscape_bytes = timeline.read_bytes()
    assert json.loads(landscape_bytes)['layout'] == 'landscape'
    assert encoded[0]['size'] == (1920, 1080)
    forbid_synthesis(monkeypatch)

    cli.main(['render', str(project), '--aspect', '9:16', '--workers', '1'])
    cli.main(['finish', str(project)])
    assert pipeline.settings(project)['aspect'] == '9:16'
    assert encoded[1]['size'] == (1080, 1920)
    assert json.loads(timeline.read_bytes())['layout'] == ('portrait' if portrait == 'native' else 'landscape')
    if portrait == 'letterbox':
        assert timeline.read_bytes() == landscape_bytes
    assert (project / f'{title}.mp4').is_file()
    assert (project / f'{title} (vertical).mp4').is_file()

    cli.main(['render', str(project), '--aspect', '16:9', '--workers', '1'])
    cli.main(['finish', str(project)])
    assert pipeline.settings(project)['aspect'] == '16:9'
    assert len(fake_voice) == initial_calls
    assert encoded[2] == encoded[0]
    assert timeline.read_bytes() == landscape_bytes
    assert muxed == [(f'{title}.mp4', title), (f'{title} (vertical).mp4', title), (f'{title}.mp4', title)]
    assert published == [(title, (1280, 720)), (f'{title} (vertical)', (720, 1280)), (title, (1280, 720))]


def test_explicit_letterbox_audio_rebuild_is_byte_identical_and_cached(tmp_path, monkeypatch, fake_voice):
    pipeline.new_project(TINY, tmp_path)
    clips = pipeline.narrate(tmp_path)
    pipeline.build_audio(tmp_path, clips)
    before = (tmp_path / 'build' / 'timeline.json').read_bytes()
    assert json.loads(before)['layout'] == 'landscape'
    initial_calls = len(fake_voice)
    assert initial_calls
    forbid_synthesis(monkeypatch)
    cfg = pipeline.set_aspect(tmp_path, '9:16')
    assert cfg['aspect'] == '9:16'
    assert (tmp_path / 'build' / 'timeline.json').read_bytes() == before
    pipeline.build_audio(tmp_path, pipeline.narrate(tmp_path))
    assert (tmp_path / 'build' / 'timeline.json').read_bytes() == before
    assert len(fake_voice) == initial_calls


def test_build_audio_rejects_invalid_saved_aspect_before_pacing(tmp_path, monkeypatch):
    pipeline.new_project(TINY, tmp_path)
    cfg = pipeline.settings(tmp_path)
    cfg['aspect'] = '4:3'
    pipeline._save(tmp_path / 'project.json', cfg)
    before = (tmp_path / 'project.json').read_bytes()
    def unexpected(*args, **kwargs):
        pytest.fail('invalid saved aspect reached pacing')
    monkeypatch.setattr(pipeline.renderer, 'pacing', unexpected)
    with pytest.raises(ValueError, match='aspect must'):
        pipeline.build_audio(tmp_path, {})
    assert (tmp_path / 'project.json').read_bytes() == before
    assert not (tmp_path / 'build').exists()


def test_set_aspect_only_changes_format_and_rejects_invalid_values(tmp_path):
    pipeline.new_project(TINY, tmp_path, voice='am_michael', speed=1.1, workers=1, credit=False)
    before = pipeline.settings(tmp_path)
    board_bytes = (tmp_path / 'storyboard.json').read_bytes()
    result = pipeline.set_aspect(tmp_path, '9:16')
    assert result == dict(before, aspect='9:16')
    assert pipeline.settings(tmp_path) == result
    assert (tmp_path / 'storyboard.json').read_bytes() == board_bytes
    config_bytes = (tmp_path / 'project.json').read_bytes()
    with pytest.raises(ValueError, match='aspect must'):
        pipeline.set_aspect(tmp_path, '4:3')
    assert (tmp_path / 'project.json').read_bytes() == config_bytes
    assert not (tmp_path / 'build').exists()


def test_finish_refuses_a_render_made_for_the_other_format(tmp_path, monkeypatch, fake_voice):
    """`render --aspect 16:9 --stills` saves the format but leaves the vertical render in build/: finish must not
    write that vertical picture over the finished 16:9 video."""
    import subprocess
    from kinodraw import package
    def encode(prod, start, n, path, crf):            # a real one-second video of the production's size
        w, h = prod.size
        subprocess.run([package.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i', f'color=c=white:s={w}x{h}:d=1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
    muxed = []
    def mux(tl, silent, mixed, video, lang, title, build):
        muxed.append(video.name)
        video.write_bytes(f'{video.name} from {silent.name}'.encode())
    monkeypatch.setattr(pipeline.renderer, 'encode', encode)
    monkeypatch.setattr(pipeline.audio, 'mix', lambda board, tl, build: build / tl['audio'])
    monkeypatch.setattr(pipeline, 'mux', mux)
    monkeypatch.setattr(pipeline, 'encoded_qa', lambda *a, **k: {'ok': True, 'problems': []})
    monkeypatch.setattr(pipeline, 'publish', lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'contact_sheet', lambda *a, **k: None)

    project = tmp_path / 'project'
    assert pipeline.make(TINY, project, workers=1)['ok']
    title = pipeline.storyboard(project)['title']['en']
    landscape = project / f'{title}.mp4'
    kept = landscape.read_bytes()
    cli.main(['render', str(project), '--aspect', '9:16', '--workers', '1'])
    cli.main(['finish', str(project)])
    cli.main(['render', str(project), '--aspect', '16:9', '--stills', '0'])
    with pytest.raises(SystemExit) as stop:
        cli.main(['finish', str(project)])
    assert '1080x1920' in str(stop.value) and 'kinodraw render' in str(stop.value)
    assert muxed == [f'{title}.mp4', f'{title} (vertical).mp4']
    assert landscape.read_bytes() == kept

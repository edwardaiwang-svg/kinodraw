"""Your own music under the video: added to the project, measured, looped or cut, ducked, mastered and kept."""
import json
from pathlib import Path

import numpy as np
import pytest

from kinodraw import cli, pipeline, project_zip
from kinodraw.audio import master, mix, score

SR = mix.SR
FIX = Path(__file__).parent / 'fixtures'


def two_tones(path, seconds=10., bpm=120., rate=SR):
    """A two-note riff on every beat (A and E, a bar of four), each note struck and decaying: music with a beat."""
    t = np.arange(int(seconds * rate)) / rate
    beat = 60 / bpm
    k = np.floor(t / beat).astype(int)
    since = t - k * beat
    freq = np.where(k % 4 == 0, 440., 660.)
    x = .5 * np.sin(2 * np.pi * freq * t) * np.exp(-since * 6)
    mix.write_wav(path, x.astype(np.float32), rate)
    return path


def speech_with_gaps(seconds=20.):
    """Speech-like buzz in phrases, silent in 0-3 s, 9-11 s and 17-20 s."""
    t = np.arange(int(seconds * SR)) / SR
    words = (np.sin(2 * np.pi * 4 * t) > .2) & (((t > 3) & (t < 9)) | ((t > 11) & (t < 17)))
    voice = np.sin(2 * np.pi * 180 * t) + .5 * np.sin(2 * np.pi * 360 * t)
    return (.2 * voice * words).astype(np.float32)


GAPS = ((1.6, 2.8), (9.3, 10.7))          # silent narration, away from the music's 1.5 s fade-in


def project(tmp_path):
    folder = tmp_path / 'p'
    pipeline.new_project(FIX / 'tiny.md', folder)
    return folder


def test_your_music_is_copied_into_the_project_measured_and_named_in_the_storyboard(tmp_path):
    folder = project(tmp_path)
    song = two_tones(tmp_path / 'My Song!.wav')
    setting = pipeline.set_music(folder, song)
    assert setting['file'] == 'music/My-Song.wav'
    assert (folder / setting['file']).read_bytes() == song.read_bytes()
    assert abs(setting['bpm'] / 120 - 1) < .01 and 0 <= setting['downbeat'] < 2
    assert pipeline.storyboard(folder)['music'] == setting
    other = pipeline.set_music(folder, two_tones(tmp_path / 'other.wav', bpm=100))
    assert abs(other['bpm'] / 100 - 1) < .01
    assert sorted(p.name for p in (folder / 'music').iterdir()) == ['other.wav']   # the track it replaced is gone
    assert pipeline.set_music(folder, 'none') is False and pipeline.storyboard(folder)['music'] is False
    assert pipeline.set_music(folder, None) is True and pipeline.storyboard(folder)['music'] is True


def test_music_that_does_not_play_or_is_too_short_long_or_big_is_refused(tmp_path, monkeypatch):
    folder = project(tmp_path)
    (tmp_path / 'notes.mp3').write_text('not music', encoding='utf-8')
    (tmp_path / 'empty.wav').write_bytes(b'')
    for path, words in ((tmp_path / 'notes.mp3', 'can play'), (tmp_path / 'empty.wav', 'empty'),
                        (two_tones(tmp_path / 'short.wav', 6), 'at least 10 seconds'),
                        (two_tones(tmp_path / 'long.wav', 601, rate=8000), 'over 10 minutes')):
        with pytest.raises(ValueError, match=words):
            pipeline.set_music(folder, path)
    monkeypatch.setattr(pipeline, 'MUSIC_MAX_BYTES', 1000)
    with pytest.raises(ValueError, match='too big'):
        pipeline.set_music(folder, two_tones(tmp_path / 'big.wav'))
    assert 'music' not in pipeline.storyboard(folder) and not (folder / 'music').exists()


def test_only_a_file_in_the_projects_music_folder_plays(tmp_path):
    good = {'file': 'music/a.wav', 'bpm': 120, 'downbeat': .1}
    track, bpm = score.source(good, 'warm', 96, tmp_path)
    assert isinstance(track, score.Own) and bpm == 120 and track.path == tmp_path / 'music/a.wav'
    assert score.source({'primary': 'natural_vibes'}, 'warm', 96) == ('natural_vibes', 100.)
    for name in ('../a.wav', 'music/../a.wav', '/etc/a.wav', 'music/.a.wav', 'music\\a.wav', 'a.wav', 'music/x/a.wav'):
        with pytest.raises(ValueError):
            score.source({**good, 'file': name}, 'warm', 96, tmp_path)
    with pytest.raises(ValueError):
        score.own({**good, 'bpm': 0}, tmp_path)


def _windowed_correlation(x, y, max_lag):
    """The best normalized correlation of x with y shifted by up to max_lag samples either way."""
    best = -1.
    for lag in range(-max_lag, max_lag + 1):
        a = x[max(0, lag):len(x) + min(0, lag)]
        b = y[max(0, -lag):len(y) + min(0, -lag)]
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        best = max(best, float(a @ b / np.sqrt((a @ a) * (b @ b) + 1e-20)))
    return best


def _bed_level(audio, bed, a, b):
    """How loud the bed is in audio over [a, b) s: the least-squares gain of the bed's own waveform in 100 ms steps
    (speech, which shares no notes with it, drops out), as the median, in dB."""
    gains = []
    for s in np.arange(a, b - .1, .1):
        i, j = round(s * SR), round((s + .1) * SR)
        ref = bed[i:j]
        gains.append(float((audio[i:j] * ref).sum() / max(float((ref * ref).sum()), 1e-20)))
    return 20 * np.log10(np.median(np.abs(gains)) + 1e-12)


def mixed(tmp_path, music):
    folder = project(tmp_path)
    setting = pipeline.set_music(folder, two_tones(tmp_path / 'riff.wav')) if music else music
    build = folder / 'build'
    build.mkdir(exist_ok=True)
    mix.write_wav(build / 'narration.wav', speech_with_gaps())
    board = dict(pipeline.storyboard(folder), music=setting)
    tl = {'duration': 20., 'audio': 'narration.wav', 'chapters': [], 'music': []}
    return folder, setting, mix.read_wav(mix.mix(board, tl, build))[0]


@pytest.mark.parametrize('look', ['whiteboard', 'collage'])
def test_your_music_plays_under_the_whole_video_ducked_and_mastered(tmp_path, look):
    folder, setting, out = mixed(tmp_path, True)
    if look != 'whiteboard':
        board = dict(pipeline.storyboard(folder), look=look)
        out = mix.read_wav(mix.mix(board, {'duration': 20., 'audio': 'narration.wav', 'chapters': [], 'music': []},
                                   folder / 'build'))[0]
    own = score.own(setting, folder)
    bed = score.loop(mix.decode(own.path, 1), 20., own.bpm, own.downbeat)[:, 0]      # repeated on its bars
    for a, b in GAPS:
        i, j = round(a * SR), round(b * SR)
        assert _windowed_correlation(out[i:j, 0], bed[i:j], 0) >= .5
    gaps = np.mean([_bed_level(out[:, 0], bed, a, b) for a, b in GAPS])
    under = np.mean([_bed_level(out[:, 0], bed, a, b) for a, b in ((4.5, 8.5), (12.5, 16.5))])
    assert gaps - under >= 6
    assert abs(master.loudness(out, SR) - mix.MASTER_LUFS) <= 1 and master.true_peak(out, SR) <= -1.


def test_no_music_leaves_the_gaps_silent(tmp_path):
    _, _, out = mixed(tmp_path, False)
    for a, b in GAPS:
        gap = out[round(a * SR):round(b * SR)]
        assert 20 * np.log10(np.sqrt((gap ** 2).mean()) + 1e-12) < -50


def test_the_cli_takes_your_music_on_new_and_finish(tmp_path, monkeypatch, capsys):
    from kinodraw import director
    monkeypatch.setattr(director, 'direct', lambda *a, **k: {'warnings': [], 'notes': [], 'usage': None})
    song = two_tones(tmp_path / 'riff.wav')
    cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'a'), '--music', str(song)])
    assert pipeline.storyboard(tmp_path / 'a')['music']['file'] == 'music/riff.wav'
    assert 'your music: music/riff.wav at 120' in capsys.readouterr().out
    cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'b'), '--music', 'none'])
    assert pipeline.storyboard(tmp_path / 'b')['music'] is False
    with pytest.raises(SystemExit, match='no such file'):
        cli.main(['new', str(FIX / 'tiny.md'), '-o', str(tmp_path / 'c'), '--music', str(tmp_path / 'missing.mp3')])
    monkeypatch.setattr(pipeline, 'finish', lambda project, **k: {'ok': True, 'video': 'v.mp4', 'length': '0:20',
                                                                  'problems': []})
    cli.main(['finish', str(tmp_path / 'b'), '--music', str(song)])
    assert pipeline.storyboard(tmp_path / 'b')['music']['file'] == 'music/riff.wav'


def test_the_project_zip_keeps_your_music(tmp_path):
    folder = project(tmp_path)
    setting = pipeline.set_music(folder, two_tones(tmp_path / 'riff.wav'))
    project_zip.export_project(folder, tmp_path / 'p.zip')
    project_zip.import_project(tmp_path / 'p.zip', tmp_path / 'back')
    assert (tmp_path / 'back' / setting['file']).read_bytes() == (folder / setting['file']).read_bytes()
    assert json.loads((tmp_path / 'back' / 'storyboard.json').read_text(encoding='utf-8'))['music'] == setting


def test_the_description_credits_your_music_not_freepd(tmp_path, monkeypatch):
    from kinodraw import package
    monkeypatch.setattr(package, 'thumbnail', lambda *a, **k: None)
    build = tmp_path / 'build'
    build.mkdir()
    for ext in ('srt', 'vtt'):
        (build / f'captions.{ext}').write_text('', encoding='utf-8')
    for lang, words in (('en', 'Music: chosen by the creator.'), ('zh', '音乐：作者自选。'),
                        ('es', 'Música: elegida por el creador.')):
        board = {'title': {lang: 'T'}, 'chapters': [], 'beats': [],
                 'music': {'file': 'music/a.wav', 'bpm': 120, 'downbeat': 0}}
        package.publish(board, {'chapters': []}, lang, build, tmp_path, 'T', tmp_path)
        text = (tmp_path / 'T-description.txt').read_text(encoding='utf-8')
        assert words in text and 'FreePD' not in text


@pytest.mark.parametrize('mood', ['bright', 'none'])
def test_director_v3_videos_play_your_music_on_its_measured_beat_grid(tmp_path, mood):
    folder = project(tmp_path)
    setting = pipeline.set_music(folder, two_tones(tmp_path / 'riff.wav', bpm=100))
    build = folder / 'build'
    build.mkdir()
    mix.write_wav(build / 'narration.wav', speech_with_gaps())
    tl = {'duration': 20., 'audio': 'narration.wav', 'language': 'en', 'beat_order': ['a'],
          'beats': {'a': {'start': 0.}}, 'chapters': [{'id': 'intro', 'start': 0.}]}
    cfg = {'lang': 'en', 'plan_v3': {'style': {'music_mood': mood, 'tempo_bpm': 129}}}
    board = {'title': {'en': 'A story'}, 'music': setting, 'beats': [{'id': 'a', 'spoken': {'en': 'Hello.'}}]}
    out = mix.read_wav(pipeline._hybrid_audio(board, tl, build, cfg))[0]
    saved = json.loads((build / 'score.json').read_text(encoding='utf-8'))
    assert saved['track'] == 'music/riff.wav' and saved['bpm'] == setting['bpm'] and saved['beats'][0] == 0
    assert np.allclose(np.diff(saved['beats']), 60 / setting['bpm'])
    i, j = (round(s * SR) for s in GAPS[0])
    assert np.sqrt((out[i:j] ** 2).mean()) > 1e-3                 # the music plays where nobody speaks

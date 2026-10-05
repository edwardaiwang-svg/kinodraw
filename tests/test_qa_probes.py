"""Encoded synthetic movies exercise detectors and the package/CLI user flows."""
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
import pytest

EVIDENCE = Path(__file__).resolve().parents[1] / 'docs/overnight-2026-10-05/evidence/a8-qa'
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture(scope='module')
def movies():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    cases = {
        'moving': ('testsrc2=size=160x90:rate=30:duration=4', 'anull'),
        'gap': ('testsrc2=size=160x90:rate=30:duration=4', "volume=0:enable='between(t,1,3)'"),
        'frozen': ('color=c=red:size=160x90:rate=30:duration=4', 'anull'),
        'flash': ("nullsrc=size=160x90:rate=30:duration=4,geq=lum='if(mod(N,6),255,0)':cb=128:cr=128", 'anull'),
        'silent': ('testsrc2=size=160x90:rate=30:duration=4', 'volume=0'),
        'black': ('color=c=black:size=160x90:rate=30:duration=4', 'anull'),
    }
    result = {}
    commands = []
    for name, (source, audio) in cases.items():
        path = EVIDENCE / f'{name}.mp4'
        command = [FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i', source,
                   '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
                   '-af', audio, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(path)]
        completed = subprocess.run(command, capture_output=True)
        commands.append({'command': command, 'exit_status': completed.returncode,
                         'stderr': completed.stderr.decode()})
        assert completed.returncode == 0, completed.stderr.decode()
        result[name] = path
    (EVIDENCE / 'synthetic-commands.json').write_text(json.dumps(commands, indent=2))
    return result


def test_silent_gap(movies):
    from kinodraw.qa.probes import probe
    report = probe(movies['gap'])
    gaps = [f for f in report.findings if f.defect == 'dead_air']
    assert len(gaps) == 1
    assert gaps[0].start == pytest.approx(1, abs=.1)
    assert gaps[0].end == pytest.approx(3, abs=.1)
    assert not report.package_ok


def test_freeze_and_hold_boundaries(movies):
    from kinodraw.qa.probes import probe
    report = probe(movies['frozen'])
    assert any(f.defect == 'frozen_picture' and f.end - f.start >= 3.8 for f in report.findings)
    assert not report.package_ok
    assert probe(movies['frozen'], {'holds': [{'start': 0, 'end': 4}]}).package_ok
    partial = probe(movies['frozen'], {'holds': [{'start': 1, 'end': 3}]})
    assert not partial.package_ok  # subtract exemptions, never hide the whole freeze
    assert probe(movies['frozen'], {'end_card': {'start': 0, 'end': 4}}).package_ok


def test_silent_end_card_and_explicit_holds(movies):
    from kinodraw.qa.probes import probe
    assert not probe(movies['silent']).package_ok
    assert probe(movies['silent'], {'end_card': {'start': 0, 'end': 4}}).package_ok
    for timeline in ({'holds': [{'start': 0, 'end': 4}]},
                     {'transitions': [{'speech_end': 0, 'hold_end': 4}]},
                     {'beats': {'a': {'speech_end': 0}}, 'pauses': {'a': 4}}):
        assert not probe(movies['silent'], timeline).package_ok
    assert not probe(movies['silent'], {'end_card': {'start': 2, 'end': 4}}).package_ok


def test_flash_and_beat_timing(movies):
    from kinodraw.qa.probes import probe
    report = probe(movies['flash'], beat_grid=[0, 1, 2, 3, 4])
    assert not report.flash_ok and not report.ok
    assert report.flash_max_swings_per_second > 3
    assert report.cut_offsets and any(f.defect == 'cut_timing' for f in report.findings)
    assert report.package_ok  # advisory in packaging


def test_motion_and_black_opening(movies):
    from kinodraw.qa.probes import probe
    report = probe(movies['moving'])
    assert report.package_ok
    assert report.motion_windows >= 7 and report.motion_static_share == 0
    assert any(f.defect == 'blank_opening' for f in probe(movies['black']).findings)
    assert not any(f.defect == 'blank_opening' for f in report.findings)
    assert report.integrated_lufs is not None


def test_no_audio_and_decode_failure(movies):
    from kinodraw.qa.probes import probe
    path = EVIDENCE / 'no-audio.mp4'
    subprocess.run([FFMPEG, '-y', '-v', 'error', '-i', str(movies['moving']), '-an', '-c:v', 'copy', str(path)], check=True)
    report = probe(path)
    assert not report.audio_present and not report.package_ok
    with pytest.raises(subprocess.CalledProcessError):
        probe(EVIDENCE / 'nonexistent.mp4')


def test_schema_review_and_contact_sheet(movies):
    from kinodraw.qa.review import REVIEW_SCHEMA, contact_sheet, repairs, review
    timeline = {'duration': 4, 'chapters': [{'start': 0}],
                'captions': [{'start': 0, 'end': 4, 'text': 'A lion walks through the forest.'}]}
    sheet = EVIDENCE / 'synthetic-contact-sheet.png'
    tiles = contact_sheet(movies['moving'], timeline, sheet, every=2)
    assert [t.timestamp for t in tiles] == [0, 2]
    assert all(t.narration == timeline['captions'][0]['text'] for t in tiles)
    assert json.loads(json.dumps(REVIEW_SCHEMA)) == REVIEW_SCHEMA
    assert REVIEW_SCHEMA['additionalProperties'] is False
    assert REVIEW_SCHEMA['required'] == ['tiles']
    tile_schema = REVIEW_SCHEMA['properties']['tiles']['items']
    assert tile_schema['additionalProperties'] is False
    assert set(tile_schema['required']) == set(tile_schema['properties']) == {'tile', 'defects', 'note'}
    assert tile_schema['properties']['defects']['uniqueItems'] is True
    assert len(tile_schema['properties']['defects']['items']['enum']) == 9
    answer = {'tiles': [{'tile': t.tile, 'defects': ['text_clipped'], 'note': 'left edge'} for t in tiles]}
    findings = review(sheet, tiles, lambda *args: json.dumps(answer))
    plan = repairs(findings, tiles)
    assert plan[0].defect == 'text_clipped' and 'safe-area' in plan[0].recommendation
    for bad in ({'tiles': [], 'extra': 1}, {'tiles': []},
                {'tiles': [{'tile': True, 'defects': [], 'note': ''}]},
                {'tiles': [{'tile': 1, 'defects': ['invented'], 'note': ''}]},
                {'tiles': [{'tile': 1, 'defects': ['other', 'other'], 'note': ''}]},
                {'tiles': [{'tile': 99, 'defects': [], 'note': ''}]},
                {'tiles': [{'tile': 1, 'defects': [], 'note': '', 'extra': 1}]}):
        with pytest.raises(ValueError):
            review(sheet, tiles, lambda *args: bad)


def test_repair_loop_cap_and_final_review():
    from kinodraw.qa.review import Tile, repair_loop
    tiles = [Tile(1, 0, 'lion')]
    reviews, applied = [], []

    def reviewer(*args):
        reviews.append(args)
        return {'tiles': [{'tile': 1, 'defects': ['static_too_long'], 'note': 'no motion'}]}

    def apply(plan, number):
        applied.append(number)
        return EVIDENCE / f'round-{number}.png', tiles

    result = repair_loop(EVIDENCE / 'initial.png', tiles, reviewer, apply)
    assert result.rounds == 2 and not result.ok
    assert applied == [1, 2] and len(reviews) == 3
    assert result.sheet_png.name == 'round-2.png'
    with pytest.raises(ValueError):
        repair_loop(result.sheet_png, tiles, reviewer, apply, max_rounds=3)
    clean = lambda *args: {'tiles': [{'tile': 1, 'defects': [], 'note': ''}]}
    assert repair_loop(result.sheet_png, tiles, clean, apply).rounds == 0


def test_package_real_video(movies, monkeypatch):
    from kinodraw import package
    from kinodraw.audio.mix import SR
    import numpy as np
    # Isolate the pre-existing codec/chapter/audio-correlation checks, exercise the new real-video gate.
    monkeypatch.setattr(package, '_probe', lambda _: {'frames': 120, 'size': __import__('re').search(r'(160)x(90)', '160x90'),
                                                    'audio': True, 'errors': [], 'chapters': []})
    monkeypatch.setattr(package, 'read_wav', lambda _: (np.zeros((4 * SR, 2)), SR))
    timeline = {'duration': 4, 'chapters': []}
    qa = package.encoded_qa(timeline, movies['gap'], EVIDENCE / 'unused.wav', size=(160, 90))
    assert not qa['ok'] and any('dead_air' in p for p in qa['problems'])
    assert 'probes' in qa
    assert package.encoded_qa(timeline, movies['moving'], EVIDENCE / 'unused.wav', size=(160, 90))['ok']
    timeline['holds'] = [{'start': 0, 'end': 4}]
    assert package.encoded_qa(timeline, movies['frozen'], EVIDENCE / 'unused.wav', size=(160, 90))['ok']


def test_cli_json_and_no_migration(movies, monkeypatch, capsys):
    from kinodraw import cli, paths
    monkeypatch.setattr(paths, 'migrate', lambda: pytest.fail('qa must not migrate user folders'))
    with pytest.raises(SystemExit) as status:
        cli.main(['qa', str(movies['gap'])])
    assert status.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert not report['package_ok']
    cli.main(['qa', str(movies['moving'])])
    assert json.loads(capsys.readouterr().out)['package_ok']


def test_unmocked_package_mux_and_qa(movies):
    from kinodraw import package
    from kinodraw.audio.mix import SR, write_wav
    import numpy as np
    time = np.arange(4 * SR) / SR
    tone = .15 * np.sin(2 * np.pi * 440 * time)
    timeline = {'duration': 4, 'chapters': [{'start': 0, 'end': 4, 'title': 'Synthetic QA'}]}
    for name, frozen, gap, hold in (('ordinary', False, False, False), ('dead-air', False, True, False),
                                     ('freeze', True, False, False), ('declared-hold', True, False, True)):
        audio = tone.copy()
        if gap:
            audio[(time >= 1) & (time < 3)] = 0
        wav = EVIDENCE / f'package-{name}.wav'
        write_wav(wav, np.column_stack((audio, audio)))
        silent = EVIDENCE / f'package-{name}-silent.mp4'
        command = [FFMPEG, '-y', '-v', 'error', '-i', str(movies['frozen' if frozen else 'moving']),
                   '-vf', 'scale=320:180', '-an', '-c:v', 'libx264', str(silent)]
        subprocess.run(command, capture_output=True, check=True)
        tl = {**timeline, **({'holds': [{'start': 0, 'end': 4}]} if hold else {})}
        output = EVIDENCE / f'package-{name}.mp4'
        package.mux(tl, silent, wav, output, 'en', 'Synthetic QA', EVIDENCE)
        report = package.encoded_qa(tl, output, wav, size=(320, 180))
        (EVIDENCE / f'package-{name}-report.json').write_text(json.dumps(report, indent=2))
        assert report['ok'] is (name in ('ordinary', 'declared-hold')), report['problems']
        if not report['ok']:
            assert all(p.startswith(('dead_air', 'frozen_picture')) for p in report['problems'])

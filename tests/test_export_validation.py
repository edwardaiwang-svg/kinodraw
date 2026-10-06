import os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, str(Path.cwd() / 'tests'))
import pytest
from PIL import Image, ImageDraw
from kinodraw import export
from kinodraw.engine import render
from kinodraw.progress import RenderContext

class Moving:
    size = (320, 180)
    def frame(self, t):
        image = Image.new('RGB', self.size, '#384958')
        ImageDraw.Draw(image).rectangle((20 + int(t*100), 20, 100 + int(t*100), 140), fill='#eed076')
        return image

@pytest.mark.parametrize('extension', ['.gif', '.webm'])
def test_encoded_output_fully_decodes_before_replacement(tmp_path, monkeypatch, extension):
    source = tmp_path / 'source.mp4'
    render.encode(Moving(), 0, 12, source, 20)
    target = tmp_path / ('previous' + extension)
    target.write_bytes(b'previous-good-output')
    real = export.wait_process
    corrupted = []
    def encoded_then_corrupt(process, context, progress_paths=(), total=0):
        real(process, context, progress_paths, total)
        output = Path(process.args[-1])
        if output.suffix == extension:
            assert process.returncode == 0 and output.stat().st_size > 0
            output.write_bytes(b'invalid-encoded-output')
            corrupted.append(output)
    monkeypatch.setattr(export, 'wait_process', encoded_then_corrupt)
    context = RenderContext()
    with pytest.raises(RuntimeError):
        export.export_video(source, target, context=context)
    assert corrupted
    assert target.read_bytes() == b'previous-good-output'
    assert not context.token.owned_pids


def _decode(path, progress, *maps):
    import subprocess
    from kinodraw.progress import encoded_frames
    command = [render.FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', str(path)]
    for stream in maps:
        command += ['-map', stream]
    command += ['-vsync', '0', '-progress', str(progress), '-f', 'null', '-']
    result = subprocess.run(command, capture_output=True, timeout=20)
    return result, encoded_frames(progress)


@pytest.mark.parametrize('extension', ['.gif', '.webm'])
@pytest.mark.parametrize('rate', [12, 30])
def test_valid_exports_full_decode_with_non_silent_audio(tmp_path, extension, rate):
    import json
    import subprocess
    import numpy as np
    from kinodraw.audio import mix
    from kinodraw import voice
    source = tmp_path / 'source.mp4'
    tone = tmp_path / 'tone.wav'
    wave = .12 * np.sin(2 * np.pi * 440 * np.arange(voice.SR // 2) / voice.SR)
    assert np.max(np.abs(wave)) > .1
    mix.write_wav(tone, wave, voice.SR)
    original = tmp_path / 'original.mp4'
    render.encode(Moving(), 0, 15, original, 20)
    muxed = subprocess.run([render.FFMPEG, '-y', '-v', 'error', '-i', str(original), '-i', str(tone),
                            '-vf', f'fps={rate}', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(source)],
                           capture_output=True, timeout=20)
    assert muxed.returncode == 0, muxed.stderr
    source_bytes, tone_bytes = source.read_bytes(), tone.read_bytes()
    decoded_source, expected = _decode(source, tmp_path / 'source-progress', '0:v:0', '0:a:0')
    assert decoded_source.returncode == 0 and expected > 0
    output = tmp_path / ('output' + extension)
    context = RenderContext()
    assert export.export_video(source, output, context=context) == output
    maps = ['0:v:0'] + (['0:a:0'] if extension == '.webm' else [])
    result, actual = _decode(output, tmp_path / 'output-progress', *maps)
    assert result.returncode == 0 and not result.stderr, result.stderr
    assert actual == expected
    if extension == '.webm':
        pcm = subprocess.run([render.FFMPEG, '-v', 'error', '-xerror', '-i', str(output), '-map', '0:a:0',
                              '-f', 'f32le', '-'], capture_output=True, timeout=20)
        assert pcm.returncode == 0 and np.max(np.abs(np.frombuffer(pcm.stdout, dtype='<f4'))) > .05
    assert source.read_bytes() == source_bytes and tone.read_bytes() == tone_bytes
    assert not context.token.owned_pids and not list(tmp_path.glob('.export-*'))
    print(json.dumps({'flow': 'export_decode', 'format': extension, 'recipe_rate': rate,
                      'expected_frames': expected, 'decoded_frames': actual, 'decode_exit': result.returncode,
                      'audio_decoded': extension == '.webm'}))


@pytest.mark.parametrize('extension', ['.gif', '.webm'])
def test_short_output_rejected_despite_successful_encoder(tmp_path, monkeypatch, extension):
    import subprocess
    source, output = tmp_path / 'source.mp4', tmp_path / ('out' + extension)
    render.encode(Moving(), 0, 12, source, 20)
    source_bytes = source.read_bytes()
    output.write_bytes(b'previous-good-output')
    popen, encoders = subprocess.Popen, []
    def short(command, *args, **kwargs):
        if Path(command[-1]).suffix == extension:
            command = command[:-1] + ['-frames:v', '1'] + command[-1:]
            process = popen(command, *args, **kwargs)
            encoders.append(process)
            return process
        return popen(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', short)
    context = RenderContext()
    with pytest.raises(RuntimeError, match='frames'):
        export.export_video(source, output, context=context)
    assert encoders and all(p.returncode == 0 for p in encoders)
    assert output.read_bytes() == b'previous-good-output' and source.read_bytes() == source_bytes
    assert not context.token.owned_pids and not list(tmp_path.glob('.export-*'))


@pytest.mark.parametrize('extension', ['.gif', '.webm'])
def test_cancel_during_output_validation_preserves_previous(tmp_path, monkeypatch, extension):
    from kinodraw import progress
    source, output = tmp_path / 'source.mp4', tmp_path / ('out' + extension)
    render.encode(Moving(), 0, 12, source, 20)
    output.write_bytes(b'previous-good-output')
    source_bytes = source.read_bytes()
    wait, seen = progress.wait_process, []
    context = RenderContext()
    def cancel(process, ctx, *args, **kwargs):
        if '-i' in process.args and Path(process.args[process.args.index('-i') + 1]).suffix == extension:
            seen.append(process)
            ctx.token.cancel()
        return wait(process, ctx, *args, **kwargs)
    monkeypatch.setattr(progress, 'wait_process', cancel)
    with pytest.raises(progress.Cancelled):
        export.export_video(source, output, context=context)
    assert seen and all(p.poll() is not None for p in seen)
    assert output.read_bytes() == b'previous-good-output' and source.read_bytes() == source_bytes
    assert not context.token.owned_pids and not list(tmp_path.glob('.export-*'))


@pytest.mark.parametrize('extension', ['.gif', '.webm'])
def test_studio_registers_only_validated_export(tmp_path, monkeypatch, extension):
    from kinodraw import pipeline
    from kinodraw.studio import integration, server
    pipeline.new_project('# Tone\n\nA small idea.', tmp_path)
    source = tmp_path / 'source.mp4'
    render.encode(Moving(), 0, 12, source, 20)
    wait, registered = export.wait_process, []
    def corrupt(process, ctx, *args, **kwargs):
        wait(process, ctx, *args, **kwargs)
        target = Path(process.args[-1])
        if target.suffix == extension:
            assert process.returncode == 0
            target.write_bytes(b'invalid-encoded-output')
    monkeypatch.setattr(export, 'wait_process', corrupt)
    monkeypatch.setattr(integration, '_download', lambda *args: registered.append(args))
    context = server.JobContext({})
    with pytest.raises(RuntimeError):
        integration.export(tmp_path, {'source': source.name, 'format': extension}, context)
    assert not registered and not context.token.owned_pids
    assert not list(tmp_path.rglob('.export-*'))


def test_corrupt_webm_audio_is_rejected_after_video_decode(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess
    import numpy as np
    from kinodraw import voice
    from kinodraw.audio import mix
    source, output = tmp_path / 'source.mp4', tmp_path / 'out.webm'
    render.encode(Moving(), 0, 12, source, 20)
    tone = tmp_path / 'tone.wav'
    mix.write_wav(tone, .12 * np.sin(2 * np.pi * 440 * np.arange(voice.SR // 2) / voice.SR), voice.SR)
    output.write_bytes(b'previous-good-output')
    wait, corrupted = export.wait_process, []
    def corrupt_audio(process, ctx, *args, **kwargs):
        wait(process, ctx, *args, **kwargs)
        target = Path(process.args[-1])
        if target.suffix == '.webm':
            assert process.returncode == 0
            probe = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-select_streams', 'a:0',
                '-show_packets', '-show_data', '-show_entries', 'packet=pos,size,data', '-of', 'json', str(target)],
                capture_output=True, text=True, timeout=10)
            assert probe.returncode == 0, probe.stderr
            packet = json.loads(probe.stdout)['packets'][0]
            payload = bytes.fromhex(''.join(line.split(':', 1)[1].split('  ')[0].strip().replace(' ', '')
                                           for line in packet['data'].splitlines() if ':' in line))
            raw = bytearray(target.read_bytes())
            position = raw.find(payload, int(packet['pos']), int(packet['pos']) + int(packet['size']) + 32)
            assert position >= 0
            raw[position:position + len(payload)] = b'\xff' * len(payload)
            target.write_bytes(raw)
            # Exact video count still passes: this case requires audio decode.
            result, frames = _decode(target, tmp_path / 'video-only-progress', '0:v:0')
            assert result.returncode == 0 and frames == 12
            corrupted.append(target)
    monkeypatch.setattr(export, 'wait_process', corrupt_audio)
    context = RenderContext()
    with pytest.raises(RuntimeError):
        export.export_video(source, output, audio=tone, context=context)
    assert corrupted and output.read_bytes() == b'previous-good-output'
    assert not context.token.owned_pids and not list(tmp_path.glob('.export-*'))


def test_cancel_during_webm_audio_decode_preserves_previous(tmp_path, monkeypatch):
    from kinodraw.progress import Cancelled
    source, output = tmp_path / 'source.mp4', tmp_path / 'out.webm'
    render.encode(Moving(), 0, 12, source, 20)
    output.write_bytes(b'previous-good-output')
    wait, seen = export.wait_process, []
    def cancel(process, ctx, *args, **kwargs):
        if '0:a?' in process.args and process.args[-1] == '-':
            seen.append(process)
            ctx.token.cancel()
        return wait(process, ctx, *args, **kwargs)
    monkeypatch.setattr(export, 'wait_process', cancel)
    context = RenderContext()
    with pytest.raises(Cancelled):
        export.export_video(source, output, context=context)
    assert seen and all(p.poll() is not None for p in seen)
    assert output.read_bytes() == b'previous-good-output'
    assert not context.token.owned_pids and not list(tmp_path.glob('.export-*'))

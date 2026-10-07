import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw

from kinodraw.export import export_video, render_generated, FFMPEG, native_production
from kinodraw.engine.geometry import LANDSCAPE, PORTRAIT, SQUARE, geometry_for_size
from kinodraw.engine import timeline
from kinodraw import pipeline
from kinodraw.package import video_size


def probe(path):
    return json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error',
        '-count_frames', '-show_streams', '-of', 'json', str(path)]))['streams']


class VectorFrames:
    def __init__(self, size):
        self.size = size
    def frame(self, t):
        image = Image.new('RGB', self.size, 'white')
        d = ImageDraw.Draw(image)
        w, h = self.size
        d.line([(w*.1, h*.2), (w*.9, h*.8)], fill='black', width=max(1, w//1000))
        d.ellipse((w*.3+t*10, h*.3, w*.5+t*10, h*.5), outline='red', width=3)
        return image


def test_actual_palette_gif_and_webm_audio(tmp_path):
    silent = tmp_path / 'silent.mp4'
    render_generated(VectorFrames, (160, 90), 0, 12, silent)
    audio = tmp_path / 'tone.wav'
    subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.2',
                    str(audio)], check=True)
    gif, webm = tmp_path / 'out.gif', tmp_path / 'out.webm'
    export_video(silent, gif)
    export_video(silent, webm, audio=audio)
    gs, ws = probe(gif), probe(webm)
    assert gs[0]['codec_name'] == 'gif' and int(gs[0]['nb_read_frames']) == 12
    assert gs[0]['pix_fmt'] == 'bgra' or gs[0]['pix_fmt'] == 'pal8'
    assert [(s['codec_type'], s['codec_name']) for s in ws] == [('video', 'vp9'), ('audio', 'opus')]
    assert int(ws[0]['nb_read_frames']) == 12 and video_size(webm) == (160, 90)
    duration = float(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error',
        '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(webm)]))
    assert .39 <= duration <= .45
    assert silent.exists() and audio.exists()


def test_native_4k_detail_and_square():
    native = VectorFrames((3840, 2160)).frame(0)
    upscale = VectorFrames((1920, 1080)).frame(0).resize(native.size, Image.Resampling.LANCZOS)
    assert native.tobytes() != upscale.tobytes()
    assert geometry_for_size((1920, 1080)) is LANDSCAPE
    assert geometry_for_size((1080, 1920), '9:16') is PORTRAIT
    assert geometry_for_size((1080, 1080), '1:1') is SQUARE
    assert geometry_for_size((3840, 2160)).cell_w == 1080
    assert SQUARE.text_safe_ok((64, 140, 1016, 820))
    with pytest.raises(ValueError):
        geometry_for_size((1000, 800), '1:1')


def test_native_saved_board_safe_caption(tmp_path):
    ep = pipeline.new_project('A square lesson.\n\nDraw a circle.', tmp_path, lang='en')
    timing = timeline.layout(ep, 'en', timeline.synthetic_clips(ep, 'en'))
    prod = native_production(ep, timing, 'en', tmp_path, (1080, 1080), aspect='1:1')
    for info, els, caption in prod.boards:
        assert caption.size[0] <= 1080*.88 and caption.size[1] <= 1080*.18
        assert prod.frame(info['start']+.1).size == (1080, 1080)


def test_native_factory_size_enforced(tmp_path):
    with pytest.raises(ValueError, match='wrong size'):
        render_generated(lambda s: VectorFrames((1920, 1080)), (3840, 2160), 0, 1, tmp_path/'a.mp4')


@pytest.mark.parametrize('size', [(1920, 1080), (1080, 1920)])
def test_atomic_encoder_preserves_legacy_exact_bytes(tmp_path, size):
    from kinodraw.engine.render import encode
    original, staged = tmp_path/'legacy.mp4', tmp_path/'staged.mp4'
    prod = VectorFrames(size)
    w, h = size
    process = subprocess.Popen([FFMPEG, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
        '-s', f'{w}x{h}', '-r', '30', '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
        '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart', str(original)], stdin=subprocess.PIPE)
    for i in range(2):
        process.stdin.write(prod.frame(i/30).tobytes())
    process.stdin.close()
    assert process.wait() == 0
    encode(prod, 0, 2, staged, 20)
    assert original.read_bytes() == staged.read_bytes()


def test_live_conversion_cancel_keeps_source_and_previous_webm(tmp_path):
    from kinodraw.progress import RenderContext, Cancelled
    source = tmp_path/'source.mp4'
    render_generated(VectorFrames, (640, 360), 0, 90, source)
    original = source.read_bytes()
    output = tmp_path/'good.webm'
    output.write_bytes(b'good webm')
    live_pids = []
    ctx = RenderContext()
    def cancel(progress):
        if progress.frames > 0 and ctx.token.owned_pids:
            live_pids.extend(ctx.token.owned_pids)
            ctx.token.cancel()
    ctx.callback = cancel
    with pytest.raises(Cancelled):
        export_video(source, output, context=ctx)
    assert live_pids and not ctx.token.owned_pids
    assert source.read_bytes() == original and output.read_bytes() == b'good webm'
    assert set(tmp_path.iterdir()) == {source, output}


@pytest.mark.parametrize('flow', ['encode', 'join'])
def test_short_real_ffmpeg_output_never_replaces_good_output(tmp_path, monkeypatch, flow):
    from kinodraw.engine import render
    from kinodraw.progress import RenderContext
    output = tmp_path/'good.mp4'
    render.encode(VectorFrames((160, 90)), 0, 8, output, 20)
    previous = output.read_bytes()
    project = tmp_path/'project'
    if flow == 'join':
        pipeline.new_project('A lesson.\n\nCount three circles.', project, lang='en')
    original_popen = subprocess.Popen
    exits = []
    def short_encoder(cmd, *args, **kwargs):
        # Real FFmpeg exits zero with fewer frames than requested.
        if cmd[0] == render.FFMPEG and (
                (flow == 'encode' and 'rawvideo' in cmd) or
                (flow == 'join' and 'concat' in cmd)):
            cmd = cmd[:-1] + ['-frames:v', '1'] + cmd[-1:]
            process = original_popen(cmd, *args, **kwargs)
            exits.append(process)
            return process
        return original_popen(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', short_encoder)
    updates = []
    ctx = RenderContext(callback=updates.append)
    failure = None
    try:
        if flow == 'encode':
            render.encode(VectorFrames((160, 90)), 0, 2, output, 20, ctx)
        else:
            render.render_segments(project, project/'storyboard.json', 'en', None,
                                   0, 4, output, 2, context=ctx)
    except RuntimeError as exc:
        failure = str(exc)
    print(json.dumps({'flow': 'short_'+flow, 'failure': failure,
                      'ffmpeg_exits': [p.returncode for p in exits],
                      'previous_preserved': output.read_bytes() == previous,
                      'reported_frames': updates[-1].frames}))
    assert exits and all(p.returncode == 0 for p in exits)
    assert failure is not None and 'frames' in failure
    assert output.read_bytes() == previous
    assert updates[-1].frames < updates[-1].total
    assert not ctx.token.owned_pids
    assert not list(tmp_path.glob('.encode-*')) and not list(tmp_path.glob('.segments-*'))


def test_the_exporter_reads_its_source_only_as_a_local_mp4(tmp_path):
    """An HLS playlist or concat list named .mp4 must not make FFmpeg fetch URLs or open other files."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append(self.path)
            self.send_response(404)
            self.end_headers()
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{http.server_port}'
    real = tmp_path / 'real.mp4'
    render_generated(VectorFrames, (160, 90), 0, 12, real)
    try:
        lists = {'hls.mp4': f'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n{base}/hls.ts\n'
                            f'#EXTINF:1,\nfile:{real}\n#EXT-X-ENDLIST\n',
                 'concat.mp4': f"ffconcat version 1.0\nfile '{base}/concat.mp4'\nfile '{real}'\n"}
        for name, text in lists.items():
            (tmp_path / name).write_text(text, encoding='utf-8')
            with pytest.raises((ValueError, RuntimeError)):
                export_video(tmp_path / name, tmp_path / (name + '.webm'))
            assert not (tmp_path / (name + '.webm')).exists()
    finally:
        http.shutdown()
        http.server_close()
    assert seen == []
    export_video(real, tmp_path / 'real.gif')
    assert (tmp_path / 'real.gif').stat().st_size > 0


def test_every_ffmpeg_read_of_the_source_forces_local_mp4(tmp_path, monkeypatch):
    import kinodraw.export as export
    real = tmp_path / 'real.mp4'
    render_generated(VectorFrames, (160, 90), 0, 6, real)
    commands = []
    popen = export.subprocess.Popen
    monkeypatch.setattr(export.subprocess, 'Popen', lambda cmd, *a, **k: commands.append(cmd) or popen(cmd, *a, **k))
    export_video(real, tmp_path / 'out.webm')
    reads = [cmd for cmd in commands if str(real) in cmd]
    assert len(reads) == 2
    for cmd in reads:
        i = cmd.index(str(real))
        assert cmd[i - 1] == '-i' and cmd[i - 5:i - 1] == ['-protocol_whitelist', 'file', '-f', 'mp4'], cmd

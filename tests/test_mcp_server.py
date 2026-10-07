"""Real newline-framed stdio clients; no models, API, or narration required."""
import hashlib
import json
import selectors
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, root):
        self.stderr = (root / 'server-stderr.txt').open('w', encoding='utf-8')
        self.proc = subprocess.Popen(
            [sys.executable, '-m', 'kinodraw.cli', 'mcp', '--root', str(root)],
            cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr)
        self.seq = 0
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)

    def send(self, message):
        self.proc.stdin.write((json.dumps(message, allow_nan=False) + '\n').encode())
        self.proc.stdin.flush()

    def receive(self):
        assert self.selector.select(30), 'stdio response timed out'
        line = self.proc.stdout.readline()
        assert line, f'server exited: {self.proc.poll()}'
        return json.loads(line)

    def request(self, method, params=None):
        self.seq += 1
        self.send({'jsonrpc': '2.0', 'id': self.seq, 'method': method, 'params': params or {}})
        reply = self.receive()
        assert reply['id'] == self.seq
        return reply

    def initialize(self):
        reply = self.request('initialize', {'protocolVersion': '2024-11-05',
                                           'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
        assert reply['result']['capabilities'] == {'tools': {'listChanged': False}}
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def call(self, name, **arguments):
        reply = self.request('tools/call', {'name': name, 'arguments': arguments})
        assert 'error' not in reply, reply
        result = reply['result']
        if result.get('isError'):
            return result
        return json.loads(result['content'][0]['text'])

    def close(self):
        self.proc.stdin.close()
        try:
            code = self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise
        finally:
            self.selector.close()
            self.stderr.close()
        assert code == 0


@pytest.fixture
def client(tmp_path):
    c = Client(tmp_path)
    try:
        c.initialize()
        yield c
    finally:
        c.close()


def test_real_stdio_pipeline_and_every_advertised_tool(client, tmp_path):
    listed = client.request('tools/list')['result']['tools']
    assert {t['name'] for t in listed} == {
        'create_project', 'validate_project', 'chart_add', 'preview_png', 'render', 'status', 'cancel',
        'list_projects', 'get_project', 'list_voices', 'export_video'}
    assert all(t['inputSchema']['additionalProperties'] is False for t in listed)
    made = client.call('create_project', project='demo', script='# Test\n\nMeasured sample counts are shown below.', lang='en')
    assert made['beats'] > 0
    assert client.call('validate_project', project='demo')['ok']
    board = json.loads((tmp_path / 'demo/storyboard.json').read_text(encoding='utf-8'))
    beat = next(b['id'] for b in board['beats'] if b['kind'] == 'narration')
    from kinodraw.engine import timeline
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    preview_time = tl['beats'][beat]['end'] - .1
    before_chart = client.call('preview_png', project='demo', time=preview_time)
    before_pixels = Image.open(before_chart['path']).tobytes()
    source = {'source': 'Invented example data, not genuine measurements', 'title': 'Example counts',
              'unit': 'items', 'rows': [{'label': 'A', 'value': 2}, {'label': 'B', 'value': 4}]}
    (tmp_path / 'data.json').write_text(json.dumps(source), encoding='utf-8')
    chart = client.call('chart_add', project='demo', beat=beat, source='data.json')
    assert chart['source_sha256']
    board = json.loads((tmp_path / 'demo/storyboard.json').read_text(encoding='utf-8'))
    visual = next(b for b in board['beats'] if b['id'] == beat)['visuals'][-1]
    assert [row['value'] for row in visual['rows']] == [2, 4]
    assert client.call('validate_project', project='demo')['ok']
    preview = client.call('preview_png', project='demo', time=preview_time)
    with Image.open(preview['path']) as image:
        assert image.format == 'PNG' and image.size == (960, 540)
        assert image.tobytes() != before_pixels, 'added chart must change the rendered frame'
    job = client.call('render', project='demo', duration=0.04)
    deadline = time.monotonic() + 40
    while True:
        status = client.call('status', job=job['job'])
        if status['state'] != 'running':
            break
        assert time.monotonic() < deadline
        time.sleep(.1)
    assert status['state'] == 'succeeded', status
    assert status['exit_code'] == 0
    assert Path(status['path']).read_bytes()[4:8] == b'ftyp'
    second = client.call('render', project='demo', duration=1)
    cancelled = client.call('cancel', job=second['job'])
    assert cancelled['state'] == 'cancelled' and cancelled['exit_code'] is not None
    assert client.call('status', job=second['job'])['state'] == 'cancelled'
    assert client.call('cancel', job=str(client.proc.pid))['isError']
    assert client.call('export_zip', project='demo')['isError']


@pytest.mark.parametrize('name,args', [
    ('create_project', {'project': '../escape', 'script': 'text'}),
    ('create_project', {'project': '/tmp/escape', 'script': 'text'}),
    ('preview_png', {'project': '../escape'}),
    ('render', {'project': '../escape'}),
    ('status', {'job': '1'}),
    ('cancel', {'job': '1'}),
    ('get_project', {'project': '../escape'}),
    ('get_project', {'project': 'missing'}),
    ('export_video', {'project': '../escape', 'video': 'a.mp4'}),
])
def test_path_and_unowned_job_refusals(client, name, args):
    assert client.call(name, **args)['isError']


def test_symlink_refusals(client, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    (tmp_path / 'escape').symlink_to(outside, target_is_directory=True)
    assert client.call('create_project', project='escape/new', script='text')['isError']
    assert not (outside / 'new').exists()
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    (tmp_path / 'demo/build').symlink_to(outside, target_is_directory=True)
    assert client.call('preview_png', project='demo')['isError']
    assert client.call('render', project='demo')['isError']


@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-Infinity', '1e999', 'true', '-2', '"2"',
                               '9007199254740993.0', '1e-400', '0.100000000000000005',
                               '9007199254740993'])
def test_bad_chart_sources_are_refused_without_changes(client, tmp_path, bad):
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    board_path = tmp_path / 'demo/storyboard.json'
    before = board_path.read_bytes()
    board = json.loads(before)
    (tmp_path / 'bad.json').write_text(
        '{"source":"example","title":"Bad","rows":[{"label":"A","value":' + bad + '}]}', encoding='utf-8')
    assert client.call('chart_add', project='demo', beat=board['beats'][0]['id'], source='bad.json')['isError']
    assert board_path.read_bytes() == before


def test_strict_protocol_and_truthful_errors(client):
    client.proc.stdin.write(b'{"jsonrpc":"2.0","id":900,"method":"tools/call","params":{"name":"render","arguments":{"duration":NaN}}}\n')
    client.proc.stdin.flush()
    assert client.receive()['error']['code'] == -32700
    assert client.request('missing')['error']['code'] == -32601
    assert client.call('create_project', project='demo', script='text', extra=True)['isError']
    assert client.request('ping')['result'] == {}


def test_explicit_root_required():
    result = subprocess.run([sys.executable, '-m', 'kinodraw.cli', 'mcp'], cwd=REPO,
                            capture_output=True, timeout=15)
    assert result.returncode == 2
    assert b'--root' in result.stderr


@pytest.mark.parametrize('reference,value', [('photo', '../outside.png'), ('photo', '/tmp/outside.png'),
                                           ('narrator', '../outside')])
def test_indirect_renderer_references_are_confined(client, tmp_path, reference, value):
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    path = tmp_path / 'demo/storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
    if reference == 'photo':
        board['host'] = {'photo': value}
    else:
        board['narrator'] = value
    path.write_text(json.dumps(board), encoding='utf-8')
    assert client.call('validate_project', project='demo')['isError']
    assert client.call('preview_png', project='demo')['isError']


def test_invalid_rpc_id_is_reported_as_null(client):
    client.send({'jsonrpc': '2.0', 'id': [], 'method': 'ping'})
    reply = client.receive()
    assert reply['id'] is None and reply['error']['code'] == -32600


@pytest.mark.parametrize('raw', [b'{"jsonrpc":"2.0","id":901,"method":"ping","params":{"x":1e999}}\n',
                               b'{"jsonrpc":"2.0","id":901,"id":902,"method":"ping"}\n',
                               b'{"jsonrpc":"2.0","id":901,"method":"\\ud800"}\n'])
def test_strict_json_parse_errors_keep_stdio_alive(client, raw):
    client.proc.stdin.write(raw)
    client.proc.stdin.flush()
    assert client.receive()['error']['code'] == -32700
    assert client.request('ping')['result'] == {}


def test_tool_notifications_cannot_mutate(client, tmp_path):
    client.send({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {
        'name': 'create_project', 'arguments': {'project': 'notification-project', 'script': 'text'}}})
    assert client.request('ping')['result'] == {}
    assert not (tmp_path / 'notification-project').exists()


def test_script_text_never_opens_an_implicit_file(client, tmp_path):
    source = tmp_path / 'source.md'
    source.write_text('# Private source\n\nDo not copy this file.', encoding='utf-8')
    made = client.call('create_project', project='literal', script=str(source), lang='en')
    assert made['beats'] > 0
    assert (tmp_path / 'literal/script.md').read_text(encoding='utf-8') == str(source) + '\n'


def test_invalid_request_without_id_gets_error(client):
    client.send({})
    reply = client.receive()
    assert reply['id'] is None and reply['error']['code'] == -32600


def test_malformed_editable_board_returns_tool_error(client, tmp_path):
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    path = tmp_path / 'demo/storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
    board['beats'] = [42]
    path.write_text(json.dumps(board), encoding='utf-8')
    assert client.call('validate_project', project='demo')['isError']
    assert client.request('ping')['result'] == {}


@pytest.mark.parametrize('folder,reference', [('pictures', 'own:sample.svg'), ('doodles', 'sample')])
@pytest.mark.parametrize('resource', [
    '<image xlink:href="{outside}" width="100" height="100"/>',
    '<use href="file://{outside}"/>',
    '<rect width="100" height="100" fill="url({outside})"/>',
    '<rect style="fill:url(\'{outside}\')" width="100" height="100"/>',
    '<style>@import url("{outside}");</style>',
])
def test_svg_resources_are_refused_before_rendering(client, tmp_path, folder, reference, resource):
    outside = tmp_path.parent / (tmp_path.name + '-synthetic.png')
    Image.new('RGB', (16, 16), 'magenta').save(outside)
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    pictures = tmp_path / 'demo' / folder
    pictures.mkdir(exist_ok=True)
    (pictures / 'sample.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'viewBox="0 0 100 100">' + resource.format(outside=outside) + '</svg>', encoding='utf-8')
    path = tmp_path / 'demo/storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
    board['beats'][1]['visuals'] = [{'id': 'own_picture', 'type': 'cluster',
                                    'items': [{'doodle': reference}]}]
    path.write_text(json.dumps(board), encoding='utf-8')
    for tool in ('validate_project', 'preview_png', 'render'):
        result = client.call(tool, project='demo')
        assert result.get('isError'), (tool, result)
        assert 'SVG' in result['content'][0]['text']
    assert not (tmp_path / 'demo/build').exists()
    assert client.request('ping')['result'] == {}


def test_inline_svg_features_remain_renderable(client, tmp_path):
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    folder = tmp_path / 'demo/pictures'
    folder.mkdir()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'viewBox="0 0 100 100"><defs><linearGradient id="paint"><stop stop-color="red"/>'
           '<stop offset="1" stop-color="blue"/></linearGradient><clipPath id="clip">'
           '<circle cx="50" cy="50" r="45"/></clipPath><path id="shape" d="M0 0H100V100H0Z"/>'
           '</defs><g transform="translate(1 1)" clip-path="url(#clip)">'
           '<use xlink:href="#shape" style="fill:url(#paint);stroke:#111;stroke-width:2"/>'
           '<text x="10" y="55" font-size="15">Inline label</text></g></svg>')
    (folder / 'inline.svg').write_text(svg, encoding='utf-8')
    path = tmp_path / 'demo/storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
    beat = board['beats'][1]
    beat['visuals'] = [{'id': 'inline_picture', 'type': 'cluster',
                        'items': [{'doodle': 'own:inline.svg'}]}]
    path.write_text(json.dumps(board), encoding='utf-8')
    assert client.call('validate_project', project='demo')['ok']
    from kinodraw.engine import timeline
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    preview = client.call('preview_png', project='demo', time=tl['beats'][beat['id']]['end'] - .1)
    with Image.open(preview['path']) as image:
        assert image.format == 'PNG' and image.size == (960, 540)
    assert (folder / 'inline.svg').read_text(encoding='utf-8') == svg


def test_collage_refused_before_search_or_child_launch(tmp_path, monkeypatch):
    from kinodraw import mcp_server
    from kinodraw.director import match
    from kinodraw.engine.collage import stickers
    service = mcp_server.Developer(tmp_path)
    service.create_project('demo', script='# Test\n\nZzquux frobnication.', lang='en')
    path = tmp_path / 'demo/storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
    board['look'] = 'collage'
    path.write_text(json.dumps(board), encoding='utf-8')
    reached = []

    def forbidden(*args, **kwargs):
        reached.append(True)
        raise ValueError('test blocked a search-model entry point or child launch')

    monkeypatch.setattr(match, '_model', forbidden)
    monkeypatch.setattr(stickers, 'find', forbidden)
    monkeypatch.setattr(mcp_server.subprocess, 'Popen', forbidden)
    for tool in ('validate_project', 'preview_png', 'render'):
        with pytest.raises(ValueError, match='collage.*offline'):
            getattr(service, tool)('demo')
    assert reached == []
    assert not (tmp_path / 'demo/build').exists()


def test_supported_chart_numbers_and_source_hash_are_preserved(client, tmp_path):
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    path = tmp_path / 'demo/storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
    raw = (b'{"source":"Invented example","title":"Exact source values","rows":['
           b'{"label":"A","value":0.1},{"label":"B","value":1.25},'
           b'{"label":"C","value":1e-300},{"label":"D","value":9007199254740992.0},'
           b'{"label":"E","value":0},{"label":"F","value":9007199254740994}]}')
    (tmp_path / 'exact.json').write_bytes(raw)
    result = client.call('chart_add', project='demo', beat=board['beats'][1]['id'], source='exact.json')
    digest = hashlib.sha256(raw).hexdigest()
    assert result['source_sha256'] == digest
    saved = json.loads(path.read_text(encoding='utf-8'))['beats'][1]['visuals'][-1]
    assert saved['source_sha256'] == digest
    assert [row['value'] for row in saved['rows']] == [row['value'] for row in json.loads(raw)['rows']]
    assert (tmp_path / 'exact.json').read_bytes() == raw


def _seconds(path):
    """Decoded video length: the last frame's timestamp plus one frame, from the bundled FFmpeg."""
    import imageio_ffmpeg
    from kinodraw.progress import encoded_frames
    progress = Path(str(path) + '.count')
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(path), '-map', '0:v:0',
                    '-progress', str(progress), '-f', 'null', '-'], check=True, timeout=60)
    return encoded_frames(progress) / 30


def wait(client, job, seconds=60):
    deadline = time.monotonic() + seconds
    while (status := client.call('status', job=job))['state'] == 'running':
        assert time.monotonic() < deadline, status
        time.sleep(.1)
    return status


def test_list_get_voices_and_export_over_stdio(client, tmp_path):
    client.call('create_project', project='demo', script='# Test\n\nMeasured sample counts are shown below.', lang='en')
    client.call('create_project', project='lessons/zh', starter='explainer-zh')
    (tmp_path / 'notes').mkdir()
    listed = client.call('list_projects')
    assert [p['project'] for p in listed['projects']] == ['demo', 'lessons/zh']
    demo = listed['projects'][0]
    assert demo['lang'] == 'en' and demo['look'] == 'whiteboard' and demo['aspect'] == '16:9'
    assert demo['title'] == 'Test' and demo['has_video'] is False and len(demo['revision']) == 64
    assert listed['projects'][1]['lang'] == 'zh'

    got = client.call('get_project', project='demo')
    board = json.loads((tmp_path / 'demo/storyboard.json').read_text(encoding='utf-8'))
    assert len(got['beats']) == len(board['beats']) and len(got['chapters']) == len(board['chapters'])
    beat = next(b for b in got['beats'] if b['kind'] == 'narration')
    assert beat['text'] == 'Measured sample counts are shown below.' and beat['visuals'] == []
    assert got['settings']['voice'] == 'af_heart' and got['revision'] == demo['revision']
    assert set(got['settings']) <= {'lang', 'voice', 'speed', 'aspect', 'size', 'director', 'director_v3', 'credit',
                                    'look', 'recording', 'plan_v3'}
    assert got['outputs'] == [] and got['qa'] is None

    voices = client.call('list_voices')
    assert voices['count'] >= 24 == sum(len(v['voices']) for v in voices['languages'].values())
    assert {lang: v['default'] for lang, v in voices['languages'].items()} == {
        'en': 'af_heart', 'zh': 'zf_001', 'es': 'ef_dora'}

    render = client.call('render', project='demo', duration=1)
    assert wait(client, render['job'])['state'] == 'succeeded'
    video = Path(render['path']).relative_to(tmp_path / 'demo').as_posix()
    export = client.call('export_video', project='demo', video=video, format='webm')
    status = wait(client, export['job'])
    assert status['state'] == 'succeeded' and status['exit_code'] == 0 and 'synthetic_timing' not in status
    webm = Path(status['path'])
    assert webm.suffix == '.webm' and webm.read_bytes()[:4] == b'\x1a\x45\xdf\xa3'
    assert abs(_seconds(webm) - _seconds(render['path'])) <= 1 / 30
    assert any(o.endswith('.webm') for o in client.call('get_project', project='demo')['outputs'])


def test_export_video_refuses_paths_and_cancel_reaps_its_encoder(client, tmp_path):
    import imageio_ffmpeg
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    outside = tmp_path.parent / (tmp_path.name + '-outside.mp4')
    outside.write_bytes(b'not a video')
    (tmp_path / 'demo/link.mp4').symlink_to(outside)
    for video, format in [('../../' + outside.name, 'webm'), ('link.mp4', 'webm'), ('script.md', 'gif'),
                          ('missing.mp4', 'gif')]:
        assert client.call('export_video', project='demo', video=video, format=format)['isError']
    (tmp_path / 'demo/link.mp4').unlink()
    assert client.call('export_video', project='demo', video='x.mp4', format='mov')['isError']
    source = tmp_path / 'demo/long.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=1280x720:rate=30:duration=20', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-pix_fmt', 'yuv420p', str(source)], check=True, timeout=120)
    export = client.call('export_video', project='demo', video='long.mp4', format='webm')
    folder = tmp_path / 'demo/build/developer'
    def encoders():                                  # the worker's FFmpeg children, seen by their staging folder
        lines = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, check=True).stdout
        return [int(line.split()[0]) for line in lines.splitlines() if str(folder / '.export-') in line]
    deadline = time.monotonic() + 60
    while not encoders():                            # cancel while FFmpeg runs, not during start-up
        assert time.monotonic() < deadline and client.call('status', job=export['job'])['state'] == 'running'
        time.sleep(.05)
    cancelled = client.call('cancel', job=export['job'])
    assert cancelled['state'] == 'cancelled' and cancelled['exit_code'] is not None
    assert not Path(export['path']).exists() and not list(folder.glob('.export-*'))
    assert encoders() == []


@pytest.fixture
def listener():
    """A local HTTP server that records every request it gets (none may arrive)."""
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
    yield f'http://127.0.0.1:{http.server_port}', seen
    http.shutdown()
    http.server_close()


def disguised(folder, base, outside):
    """Playlists and concat lists named .mp4: they point at the listener and at a file outside the project."""
    lists = {'hls.mp4': f'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n{base}/hls.ts\n'
                        f'#EXTINF:1,\nfile:{outside}\n#EXT-X-ENDLIST\n',
             'concat.mp4': f"ffconcat version 1.0\nfile '{base}/concat.mp4'\nfile '{outside}'\n",
             'header.mp4': '\x00\x00\x00\x18ftypisom' + f'\n#EXTM3U\n#EXTINF:1,\n{base}/header.ts\n'}
    for name, text in lists.items():
        (folder / name).write_text(text, encoding='utf-8')
    return list(lists)


def test_export_refuses_playlists_and_lists_named_mp4_before_ffmpeg(client, tmp_path, listener):
    base, seen = listener
    outside = tmp_path.parent / (tmp_path.name + '-secret.mp4')
    outside.write_bytes(b'outside the project')
    client.call('create_project', project='demo', script='# Test\n\nExample text.', lang='en')
    for name in disguised(tmp_path / 'demo', base, outside):
        result = client.call('export_video', project='demo', video=name, format='webm')
        assert result.get('isError') and 'MP4' in result['content'][0]['text'], (name, result)
    time.sleep(1.5)
    assert seen == [] and not (tmp_path / 'demo/build/developer').exists()

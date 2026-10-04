"""Native portrait composition, capability routing and measured pacing."""
import json
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from kinodraw import ingest, pipeline, script, styles
from kinodraw.director import match
from kinodraw.director.rules import RulesDirector
from kinodraw.engine import auto_scenes as auto
from kinodraw.engine import ink, render, skin, timeline, vertical
from kinodraw.engine.geometry import PORTRAIT

TINY = Path(__file__).parent / 'fixtures' / 'tiny.md'


@pytest.fixture(scope='module')
def board():
    ep = script.build(ingest.read(TINY))
    repo, files = match.EMBED_FILES['en']
    folder = match.CACHE / f"{repo.split('/')[1]}-{repo.split('/')[3][:8]}"
    if all((folder / name).is_file() for name in files):
        return RulesDirector('en').direct(ep)
    warnings.warn('Rules director model is not installed; native smoke uses the board without visuals')
    return ep


@pytest.fixture(scope='module')
def native(board, tmp_path_factory):
    project = tmp_path_factory.mktemp('portrait-core')
    clips = timeline.synthetic_clips(board, 'en')
    pauses = render.pacing(board, 'en', clips, project, aspect='9:16', portrait='native')
    timing = timeline.layout(board, 'en', clips, pauses)
    return render.make_production(board, timing, 'en', project, aspect='9:16', portrait='native')


def test_registry_and_measured_layout(monkeypatch):
    entries = json.loads(styles.REGISTRY.read_text())['looks']
    for entry in entries:
        look = entry['id']
        assert entry['portrait'] == styles.portrait(look) == 'letterbox'
        assert render.pace_layout({'look': look}, '16:9') == 'landscape'
        assert render.pace_layout({'look': look}, '9:16') == 'landscape'
        assert render.pace_layout({'look': look}, '9:16', 'letterbox') == 'landscape'
        assert render.pace_layout({'look': look}, '9:16', 'native') == 'portrait'
    assert styles.portrait(None) == styles.portrait('unknown') == 'letterbox'
    monkeypatch.setattr(styles, '_looks', lambda: ({'id': 'whiteboard', 'portrait': 'native'}, {'id': 'old'}))
    assert styles.portrait(None) == 'native'
    assert styles.portrait('old') == 'letterbox'
    assert render.pace_layout({}, '9:16') == 'portrait'


def test_invalid_routing(board, tmp_path):
    clips = timeline.synthetic_clips(board, 'en')
    timing = timeline.layout(board, 'en', clips)
    with pytest.raises(ValueError, match='collage.*not laid out.*letterboxed'):
        render.make_production(dict(board, look='collage'), timing, 'en', tmp_path,
                               aspect='9:16', portrait='native')
    with pytest.raises(ValueError, match='unknown portrait'):
        render.make_production(board, timing, 'en', tmp_path, aspect='9:16', portrait='bad')
    with pytest.raises(ValueError, match='unknown aspect'):
        render.pace_layout(board, '4:3')
    landscape = render.make_production(board, timing, 'en', tmp_path, portrait='bad')
    assert landscape.size == (1920, 1080) and not landscape.vertical


def _inside(box, band):
    x0, y0, x1, y1 = box
    left, top, right, bottom = band
    assert left <= x0 <= x1 <= right and top <= y0 <= y1 <= bottom, (box, band)


def test_native_frames_and_safe_bands(native):
    assert native.native and native.vertical and native.g is PORTRAIT
    assert native.ctx is native.prod.ctx and native.warnings is native.prod.warnings
    assert vertical.Vertical is vertical.PortraitFrame
    text_count = caption_count = title_count = 0
    for t in np.linspace(0, native.tl['duration'] - .01, 8):
        assert native.frame(t).size == (1080, 1920)
        L = native.camera.at(t)
        if L == native.camera.target_at(t) and native.mode_at(t)[0] == 'board':
            for e in native.els:
                if not isinstance(e.drawing, ink.TextDrawing) or e.start > t or e.state(t)[0] is None:
                    continue
                if e.x >= L + native.size[0] or e.x + e.w <= L:
                    continue
                box = auto.ink_bbox(e)
                if box is not None:
                    box = (box[0] - L, box[1], box[2] - L, box[3])
                    if e.group == 'credit':           # the handwritten credit deliberately occupies the caption band
                        _inside(box, PORTRAIT.caption_band)
                    else:
                        assert PORTRAIT.text_safe_ok(box), (t, e.group, e.drawing.lines, box)
                    text_count += 1
        text = native.caption_at(t)
        if text:
            x, y, w, h = native.caption_box(text)
            _inside((x, y, x + w, y + h), PORTRAIT.caption_band)
            caption_count += 1
        image, alpha = native.title_at(t)
        if image is not None and alpha > 0:
            assert native.scene_at(t) in ('board', 'take')
            x, y = (1080 - image.width) // 2, PORTRAIT.title_band[3] - image.height
            _inside((x, y, x + image.width, y + image.height), PORTRAIT.title_band)
            title_count += 1
    assert text_count > 0 and caption_count > 0 and title_count > 0
    hidden = set()
    for t in np.arange(0, native.tl['duration'], .25):
        kind = native.scene_at(t)
        if kind in ('title', 'agenda', 'opener', 'end'):
            assert native.title_at(t) == (None, 0.)
            hidden.add(kind)
    assert hidden == {'title', 'agenda', 'opener', 'end'}


def test_native_copies_the_board_and_has_no_second_credit():
    source = Image.new('RGBA', PORTRAIT.size, (1, 2, 3, 255))
    prod = SimpleNamespace(ep={'chapters': []}, tl={'chapters': [], 'duration': 1}, lang='en', skin=skin.WHITEBOARD,
                           frame=lambda t: source, scene_at=lambda t: 'end')
    frame = vertical.PortraitFrame(prod, native=True)
    frame._credit = lambda t: pytest.fail('the native credit is already written by the hand')
    out = frame.frame(.9)
    assert out is not source and out.tobytes() == source.tobytes()
    out.putpixel((0, 0), (255, 255, 255, 255))
    assert source.getpixel((0, 0)) == (1, 2, 3, 255)


@pytest.mark.parametrize('lang,text', [
    ('en', 'Plants turn sunlight, water and air into the sugar they live on, and give us oxygen.'),
    ('es', 'Los pingüinos caminan juntos durante el invierno más frío de la Antártida.'),
    ('zh', '请访问 https://www.example.com/products/documentation/ 了解详情，' * 3),
    ('en', 'https://example.com/' + 'a' * 700),
])
def test_native_caption_fits_with_its_outline(lang, text):
    lines, size = vertical.caption_lines(text, lang, width=676, start_size=60, height_limit=232)
    image = vertical.caption_image(text, lang, width=676, start_size=60, height_limit=232)
    assert image.width <= 696 and image.height <= 232
    assert ''.join(lines).replace(' ', '') == text.replace(' ', '')
    assert size <= 60


@pytest.mark.parametrize('key', ['title', 'chapter'])
def test_native_title_fits_its_band(native, key, monkeypatch):
    long = 'https://example.com/' + 'a' * 500
    if key == 'title':
        monkeypatch.setitem(native.ep, 'title', {'en': long})
        title_key = ('title',)
    else:
        chapter = next(ch for ch in native.ep['chapters'] if ch['kind'] == 'section')
        monkeypatch.setitem(chapter, 'title', {'en': long})
        monkeypatch.setitem(chapter, 'label', {'en': 'A very long label ' * 30})
        monkeypatch.setitem(chapter, 'source', {'en': 'A very long source ' * 30})
        title_key = ('chapter', chapter['id'])
    native._title_image.cache_clear()
    image = native._title_image(title_key)
    assert image.width <= 904 and image.height <= 282
    native._title_image.cache_clear()


def test_letterbox_pacing_matches_landscape(board, tmp_path):
    clips = timeline.synthetic_clips(board, 'en')
    assert render.pacing(board, 'en', clips, tmp_path, aspect='9:16') == render.pacing(board, 'en', clips, tmp_path)


def test_hidden_flag_writes_native_stills(board, tmp_path):
    project = tmp_path / 'p'
    pipeline.new_project(TINY, project)
    pipeline._save(project / 'storyboard.json', board)
    out = tmp_path / 'stills'
    render.main(['--project', str(project), '--episode', str(project / 'storyboard.json'), '--lang', 'en',
                 '--synthetic', '--aspect', '9:16', '--portrait', 'native', '--stills', '2,20',
                 '--preview-dir', str(out)])
    images = list(out.glob('*.png'))
    assert len(images) == 2
    for path in images:
        with Image.open(path) as image:
            assert image.size == (1080, 1920)


@pytest.mark.parametrize('portrait', [None, 'native'])
def test_segments_forward_only_explicit_portrait(tmp_path, monkeypatch, portrait):
    commands = []
    def popen(cmd):
        commands.append(cmd)
        segment = Path(cmd[cmd.index('--output') + 1])
        Path(str(segment) + '.json').write_text(json.dumps({'warnings': []}))
        return SimpleNamespace(wait=lambda: 0)
    monkeypatch.setattr(render.subprocess, 'Popen', popen)
    monkeypatch.setattr(render.subprocess, 'run', lambda *a, **k: None)
    render.render_segments(tmp_path, tmp_path / 'storyboard.json', 'en', tmp_path / 'timeline.json',
                           0, 60, tmp_path / 'silent.mp4', 2, aspect='9:16', portrait=portrait)
    assert len(commands) == 2
    for i, cmd in enumerate(commands):
        expected = [sys.executable, '-m', 'kinodraw.engine.render', '--project', str(tmp_path), '--episode',
                    str(tmp_path / 'storyboard.json'), '--lang', 'en', '--crf', '20', '--aspect', '9:16',
                    '--timeline', str(tmp_path / 'timeline.json')]
        if portrait is not None:
            expected += ['--portrait', portrait]
        expected += ['--start', repr(float(i)), '--frames', '30', '--output',
                     str(tmp_path / '.silent.segments' / f'{i:02d}.mp4')]
        assert cmd == expected


@pytest.mark.parametrize('portrait', [None, 'native'])
def test_manifest_records_only_explicit_portrait(tmp_path, monkeypatch, portrait):
    pipeline.new_project(TINY, tmp_path)
    def encode(prod, start, n, output, crf):
        assert prod.native == (portrait == 'native')
        output.write_bytes(b'placeholder')
    monkeypatch.setattr(render, 'encode', encode)
    output = tmp_path / 'silent.mp4'
    args = ['--project', str(tmp_path), '--episode', str(tmp_path / 'storyboard.json'), '--lang', 'en',
            '--synthetic', '--aspect', '9:16', '--frames', '1', '--output', str(output)]
    if portrait is not None:
        args += ['--portrait', portrait]
    render.main(args)
    manifest = json.loads(Path(str(output) + '.json').read_text())
    assert ('portrait' in manifest) == (portrait is not None)
    if portrait is not None:
        assert manifest['portrait'] == portrait

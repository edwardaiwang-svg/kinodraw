"""Native portrait composition, capability routing and measured pacing."""
import json
import sys
import threading
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
    entries = json.loads(styles.REGISTRY.read_text(encoding='utf-8'))['looks']
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
@pytest.mark.parametrize('saved_timeline', [True, False], ids=['timeline', 'synthetic'])
def test_segments_forward_only_explicit_portrait(tmp_path, monkeypatch, portrait, saved_timeline):
    from kinodraw.package import _probe
    from kinodraw.progress import RenderContext, encoded_frames
    project = tmp_path / 'project'
    pipeline.new_project('# Lesson\n\nCount three circles.\n\n## First\n\nA short line.\n\n'
                         '## Second\n\nThis longer line gives the clock a different interval between beats.',
                         project, lang='en')
    ep = pipeline.storyboard(project)
    timing = timeline.layout(ep, 'en', timeline.synthetic_clips(ep, 'en'))
    starts = [timing['beats'][b]['start'] for b in timing['beat_order']]
    intervals = [round(b - a, 4) for a, b in zip(starts, starts[1:])]
    assert len(set(intervals)) > 1
    timeline_path = project / 'saved-timeline.json' if saved_timeline else None
    if timeline_path is not None:
        timeline_path.write_text(json.dumps(timing), encoding='utf-8')
    start = .4
    output = tmp_path / 'silent.mp4'
    tiny = SimpleNamespace(size=(160, 90), frame=lambda t: Image.new('RGB', (160, 90), 'white'))
    render.encode(tiny, 0, 2, output, 20)
    previous = output.read_bytes()
    commands, manifests, worker_progress, processes, updates, decode_progress = [], [], [], [], [], []
    real_popen = render.subprocess.Popen
    decoders, commits = [], []

    def popen(cmd, *args, **kwargs):
        # Forward every invocation, including join and full decode validation, to the real process factory.
        assert output.read_bytes() == previous
        if cmd[:3] == [sys.executable, '-m', 'kinodraw.engine.render']:
            commands.append((cmd, kwargs))
        if '-f' in cmd and cmd[cmd.index('-f') + 1] == 'concat':
            for worker_cmd, worker_kw in commands:
                segment = Path(worker_cmd[worker_cmd.index('--output') + 1])
                manifests.append(json.loads(Path(str(segment) + '.json').read_text(encoding='utf-8')))
                worker_progress.append(encoded_frames(worker_kw['env']['KINODRAW_WORKER_PROGRESS']))
        if '-err_detect' in cmd:
            decode_progress.append(Path(cmd[cmd.index('-progress') + 1]))
        process = real_popen(cmd, *args, **kwargs)
        processes.append(process)
        if '-err_detect' in cmd:
            decoders.append(process)
        return process

    def reported(progress):
        updates.append(progress)
        if progress.frames < progress.total:
            assert output.read_bytes() == previous

    ctx = RenderContext(callback=reported)
    real_commit = ctx.token.commit

    def commit(source, target):
        if Path(target) == output:
            assert output.read_bytes() == previous
            assert len(decoders) == len(decode_progress) == 1, 'publish before decoder launch'
            assert all(p.returncode == 0 for p in processes), 'publish before real processes completed'
            assert all(p.returncode == 0 for p in decoders), 'publish before decoder completed'
            assert [encoded_frames(p) for p in decode_progress] == [60], 'publish before full frame validation'
            assert all('progress=end' in p.read_text(encoding='utf-8') for p in decode_progress)
            commits.append({'decoder_returncodes': [p.returncode for p in decoders],
                            'decoded_frames_before_publish': [encoded_frames(p) for p in decode_progress]})
        return real_commit(source, target)

    monkeypatch.setattr(ctx.token, 'commit', commit)
    monkeypatch.setattr(render.subprocess, 'Popen', popen)
    deadline = threading.Timer(180, ctx.token.cancel)
    deadline.start()
    try:
        warnings = render.render_segments(project, project / 'storyboard.json', 'en', timeline_path,
                                          start, 60, output, 2, aspect='9:16', portrait=portrait, context=ctx)
    finally:
        deadline.cancel()
        ctx.token.cancel()
        assert not ctx.token.owned_pids
        assert all(not ctx.token._group_exists(p.pid) for p in processes)
        assert not list(tmp_path.glob('.segments-*'))
        print(json.dumps({'owned_groups_absent': True, 'private_staging_removed': True,
                          'prior_output_still_present': output.read_bytes() == previous}))
    assert len(commands) == 2
    stages = set()
    for i, (cmd, kwargs) in enumerate(commands):
        segment = Path(cmd[cmd.index('--output') + 1])
        stages.add(segment.parent)
        assert segment.parent.parent == output.parent and segment.parent.name.startswith('.segments-')
        assert kwargs['start_new_session'] is True
        assert Path(kwargs['env']['KINODRAW_WORKER_PROGRESS']) == segment.with_suffix('.progress')
        expected = [sys.executable, '-m', 'kinodraw.engine.render', '--project', str(project), '--episode',
                    str(project / 'storyboard.json'), '--lang', 'en', '--crf', '20', '--aspect', '9:16']
        expected += ['--timeline', str(timeline_path)] if saved_timeline else ['--synthetic']
        if portrait is not None:
            expected += ['--portrait', portrait]
        expected += ['--start', repr(start + i), '--frames', '30', '--output',
                     str(segment.parent / f'{i:02d}.mp4')]
        assert cmd == expected
        assert '--size' not in cmd
        assert manifests[i]['frames'] == 30 and manifests[i]['start'] == start + i
        assert manifests[i]['aspect'] == '9:16' and manifests[i]['synthetic_timing'] is (not saved_timeline)
        if saved_timeline:
            assert str(timeline_path) in manifests[i]['inputs']
        if portrait is None:
            assert 'portrait' not in manifests[i]
        else:
            assert manifests[i]['portrait'] == portrait
    assert len(stages) == 1 and worker_progress == [30, 30]
    assert warnings == manifests[0]['warnings']
    assert len(decode_progress) == 1 and all(p.returncode == 0 for p in processes)
    assert commits == [{'decoder_returncodes': [0], 'decoded_frames_before_publish': [60]}]
    assert output.read_bytes() != previous
    # Restore the forwarding factory before probing the committed output.
    monkeypatch.setattr(render.subprocess, 'Popen', real_popen)
    probed = _probe(output)
    assert probed['frames'] == 60 and probed['size'].groups() == ('1080', '1920') and not probed['errors']
    assert updates[-1].frames == updates[-1].total == 60 and updates[-1].eta == 0
    assert all(0 <= p.frames <= 60 and p.total == 60 for p in updates)
    assert not ctx.token.owned_pids and not list(tmp_path.glob('.segments-*'))
    print(json.dumps({'portrait': portrait, 'saved_timeline': saved_timeline, 'timeline_starts': starts,
                      'worker_bounds': [[m['start'], m['frames']] for m in manifests], 'commit': commits,
                      'worker_encoded_frames': worker_progress, 'joined_decoded_frames': probed['frames'],
                      'output_size': probed['size'].groups(), 'private_staging_removed': True,
                      'prior_output_preserved_until_commit': True}))


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
    manifest = json.loads(Path(str(output) + '.json').read_text(encoding='utf-8'))
    assert ('portrait' in manifest) == (portrait is not None)
    if portrait is not None:
        assert manifest['portrait'] == portrait


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_native_takeaway_note_sits_below_the_title_band(native):
    assert native.prod.notes
    for note in native.prod.notes.values():
        nx, ny, nw, nh = note['bbox']
        assert ny >= PORTRAIT.board_band[1] and ny + nh <= PORTRAIT.board_band[3]
        assert nx - note['x'] >= PORTRAIT.cell_x0 and nx - note['x'] + nw <= PORTRAIT.cell_x0 + PORTRAIT.cell_w


def test_native_pinned_notes_and_check_marks_leave_card_text_readable(native):
    prod = native.prod
    pinned = [(sec, note) for sec, note in prod.notes.items() if 'pin_xy' in note]
    assert pinned
    for sec, note in pinned:
        card = prod.cards[sec]
        px, py = note['pin_xy']
        mw, mh = note['mini_size']
        mini = (px, py - 14, px + mw, py + mh)
        cx, cy, cw, chh = card['box']
        assert cx <= px and px + mw <= cx + cw and cy <= py - 14 and py + mh <= cy + chh
        written = [b for b in map(auto.ink_bbox, card['els']) if b]
        assert written and not any(_overlap(mini, b) for b in written), sec
        t = next(tr for tr in prod.tl['transitions'] if tr['section'] == sec)['end'] - .05
        checks = [e for e in prod.els if e.fixed and e.start is not None and abs(e.start - (note['t_pin'] + .05)) < 1e-6
                  and cx <= e.x < cx + cw and cy <= e.y < cy + chh]
        assert checks and all(not _overlap((e.x, e.y, e.x + e.w, e.y + e.h), b) for e in checks for b in written + [mini])
        assert t > note['t_pin']


def test_native_quote_takes_a_whole_screen_and_stays_in_the_board_band(board, tmp_path):
    ep = json.loads(json.dumps(board))
    beat = next(b for b in ep['beats'] if b['chapter'] == next(c['id'] for c in ep['chapters'] if c['kind'] == 'section')
                and b.get('kind') != 'take')
    text = ('Bees visit millions of flowers to make one jar of honey, and every one of those visits also carries '
            'pollen from plant to plant across the whole meadow, all summer long, without a single day off.')
    beat['visuals'] = [{'type': 'quote', 'id': f'q{k}', 'who': {'en': 'A beekeeper who has kept hives for forty years'},
                        'text': {'en': text}} for k in range(2)]           # a second quote would take the lower row
    clips = timeline.synthetic_clips(ep, 'en')
    prod = render.make_production(ep, timeline.layout(ep, 'en', clips), 'en', tmp_path, aspect='9:16',
                                  portrait='native').prod
    for k in range(2):
        quote = [e for e in prod.ctx.elements if e.group == f'q{k}' and isinstance(e.drawing, ink.TextDrawing)]
        assert len(quote) == 3                                        # the mark, the words and who said them
        top = min(quote, key=lambda e: e.y)                         # the opening quote mark
        assert top.y == PORTRAIT.rows[0][0] - 34, k                 # each quote starts its own screen (both rows)
        words = [e for e in quote if e.y >= PORTRAIT.rows[0][0]]
        assert words and max(e.y + e.h for e in words) <= PORTRAIT.rows[1][1], k


@pytest.mark.parametrize('lang,source,title', [
    ('en', 'tiny.md', 'Why Honey Found in Ancient Egyptian Tombs Is Still Perfectly Safe to Eat Today'),
    ('zh', 'sleep_zh.md', '为什么我们每天晚上都需要睡足八个小时才能保持健康和清醒？'),
    ('en', 'tiny.md', 'Supercalifragilisticexpialidocious'),                 # one word too wide even at 56 px
    ('en', 'tiny.md', 'Antidisestablishmentarianism Explained'),
    ('en', 'tiny.md', 'Honey: https://example.com/products/documentation/honey-facts'),
    ('zh', 'sleep_zh.md', 'Antidisestablishmentarianism？'),           # a closing mark hangs on a too-wide word
])
def test_native_title_board_and_end_card_show_a_long_title_in_full(lang, source, title, tmp_path):
    ep = script.build(ingest.read(TINY.parent / source))
    ep['title'] = {lang: title}
    clips = timeline.synthetic_clips(ep, lang)
    prod = render.make_production(ep, timeline.layout(ep, lang, clips), lang, tmp_path, aspect='9:16',
                                  portrait='native').prod
    left, top, right, _ = PORTRAIT.text_safe[0]
    shown = [e for e in prod.ctx.elements if isinstance(e.drawing, ink.TextDrawing)
             and ''.join(e.drawing.lines).replace(' ', '').rstrip('…') and
             title.replace(' ', '').startswith(''.join(e.drawing.lines).replace(' ', '').rstrip('…')[:12])]
    assert len(shown) == 2                                            # the title board and the end card
    for e in shown:
        assert ''.join(e.drawing.lines).replace(' ', '') == title.replace(' ', ''), e.drawing.lines
        x = e.x % PORTRAIT.size[0]
        assert left <= x and x + e.drawing.size[0] <= left + PORTRAIT.cell_w and e.y >= top

"""Native cinematic exports must reconstruct the saved production, not a new board."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw.engine import ink, render
from kinodraw.engine.hybrid import HybridProduction
from kinodraw.export import native_production
from test_hybrid import fixture


@pytest.mark.parametrize('look', ['pixel_quest', 'mosaic'])
@pytest.mark.parametrize('size,aspect', [((3840, 2160), '16:9'), ((1080, 1080), '1:1')])
def test_fallback_caption_runs_fit_and_draw(monkeypatch, look, size, aspect):
    from PIL import ImageDraw
    from kinodraw.engine import skin as skins
    from kinodraw.export import _caption_image
    skin = skins.for_look(look)
    text = '中國中國中國中國中國中國'
    runs = []
    original = skins._draw_runs
    def record(draw, line, pos, kind, font_size, fonts, color):
        runs.append((line, pos, kind, font_size, fonts, color))
        original(draw, line, pos, kind, font_size, fonts, color)
    monkeypatch.setattr(skins, '_draw_runs', record)
    image = _caption_image(text, 'en', skin, size, aspect)
    assert ''.join(run[0] for run in runs) == text
    assert image.width <= round(size[0] * (.92 if aspect == '16:9' else .88))
    assert image.height <= round(size[1] * .18)
    pad = round(32 * size[1] / 1080)
    for line, pos, kind, font_size, fonts, color in runs:
        width = skins._run_width(line, kind, font_size, fonts)
        assert pos[0] >= pad - 1 and pos[0] + width <= image.width - pad + 1, (
            image.size, pos, width)
        assert abs(pos[0] - (image.width - width) / 2) < 1e-6
        # Independently draw every fallback glyph on an unclipped mask and
        # check the actual panel pixels, not just its reported dimensions.
        mask = Image.new('L', (image.width * 3, image.height))
        original(ImageDraw.Draw(mask), line, pos, kind, font_size, fonts, 255)
        bounds = mask.getbbox()
        assert bounds and bounds[2] <= image.width - pad + 2
        glyphs = np.asarray(mask.crop((0, 0, image.width, image.height))) == 255
        assert glyphs.any() and np.all(np.asarray(image)[glyphs] == color)


def test_saved_square_endcard_narrator_is_visible(tmp_path):
    project = Path(__file__).parent / 'fixtures/native_saved_project'
    board = json.loads((project / 'storyboard.json').read_text())
    timing = json.loads((project / 'timeline.json').read_text())
    prod = native_production(board, timing, 'en', project, (1080, 1080), aspect='1:1')
    whiteboard = prod.whiteboard
    narrators = [e for e in whiteboard.els if e.group == 'endcard'
                 and getattr(e.drawing, 'native_recipe', (None,))[0] == 'svg']
    assert len(narrators) == 1, 'saved endcard narrator was omitted'
    narrator = narrators[0]
    assert Path(narrator.drawing.native_recipe[1][0]).name == 'narrator_thumbs.svg'
    assert narrator.start is not None and not narrator.skipped
    assert narrator.y + narrator.h <= 820
    at = timing['end_card']['end'] - .1
    actual = prod.frame(at).convert('RGB')
    # The full production must composite the prop into the real endcard.
    whiteboard.els.remove(narrator)
    without = prod.frame(at).convert('RGB')
    whiteboard.els.append(narrator)
    changed = np.any(np.asarray(actual) != np.asarray(without), axis=2)
    ys, xs = np.nonzero(changed)
    assert len(xs) > 100 and ys.max() <= 820
    evidence = tmp_path
    actual.save(evidence / 'saved-square-endcard.png')
    (evidence / 'square-content.json').write_text(json.dumps(dict(
        recipe=narrator.drawing.native_recipe[:2], start=narrator.start,
        duration=narrator.duration, box=narrator.bbox(),
        changed_pixels=len(xs), changed_bounds=[int(xs.min()), int(ys.min()),
                                               int(xs.max()), int(ys.max())]), indent=2) + '\n')


@pytest.mark.parametrize('size,aspect', [((3840, 2160), '16:9'), ((1080, 1080), '1:1')])
def test_saved_treatments_cast_actions_and_timing(tmp_path, size, aspect):
    board, plan, tl = fixture(tmp_path)
    prod = native_production(board, tl, 'en', tmp_path, size, aspect=aspect)
    assert isinstance(prod, HybridProduction), 'native export must use the saved hybrid engine'
    legacy = render.make_production(board, tl, 'en', tmp_path)
    assert prod.plan == plan and prod.style == legacy.style and prod.cast == legacy.cast
    assert prod.tl == tl and prod.duration == legacy.duration
    assert [(s.start, s.end, s.spec, s.actors, s.actions) for s in prod.spans] == [
        (s.start, s.end, s.spec, s.actors, s.actions) for s in legacy.spans]
    assert prod.cues() == legacy.cues()
    assert isinstance(prod.whiteboard, render.Production)
    assert prod.size == prod.whiteboard.size == size


@pytest.mark.parametrize('size,aspect', [((3840, 2160), '16:9'), ((1080, 1080), '1:1')])
def test_factory_target_is_reconstructible(tmp_path, size, aspect):
    board, plan, tl = fixture(tmp_path)
    prod = render.make_production(board, tl, 'en', tmp_path, size=size, aspect=aspect)
    times = [1., prod.spans[1].start+1., tl['end_card']['end']-.1]
    expected = [hashlib.sha256(prod.frame(t).tobytes()).hexdigest() for t in times]
    payload = tmp_path / 'reconstruct.json'
    payload.write_text(json.dumps(dict(board=board, timeline=tl, size=size, aspect=aspect, times=times)))
    code = """import hashlib,json,sys
from pathlib import Path
from kinodraw.engine.render import make_production
p=Path(sys.argv[1]); d=json.loads(p.read_text())
r=make_production(d['board'],d['timeline'],'en',p.parent,size=d['size'],aspect=d['aspect'])
print(json.dumps([hashlib.sha256(r.frame(t).tobytes()).hexdigest() for t in d['times']]))
"""
    worker = subprocess.run([sys.executable, '-c', code, str(payload)], capture_output=True, text=True, timeout=90)
    assert worker.returncode == 0, worker.stderr
    assert json.loads(worker.stdout) == expected
    evidence = tmp_path
    (evidence/f'worker-{size[0]}x{size[1]}.json').write_text(json.dumps(dict(
        command=[sys.executable,'-c',code,str(payload)], exit_code=worker.returncode,
        size=size,aspect=aspect,times=times,parent_hashes=expected,worker_hashes=json.loads(worker.stdout)),indent=2)+'\n')


def test_1080_explicit_target_preserves_default_bytes(tmp_path):
    board, plan, tl = fixture(tmp_path)
    default = render.make_production(board, tl, 'en', tmp_path)
    explicit = native_production(board, tl, 'en', tmp_path, (1920, 1080))
    for t in (1., default.spans[1].start + 1., tl['end_card']['end'] - .1):
        assert explicit.frame(t).tobytes() == default.frame(t).tobytes()


def test_recorded_legacy_frame_hashes(tmp_path):
    board, plan, tl = fixture(tmp_path)
    prod = render.make_production(board, tl, 'en', tmp_path)
    hashes = {
        1.: '75f409279ef112d350f1a1bc344a34ad22c51de0909ae6651732793788da0f28',      # its caption's word being said
        4.7153: 'ef476897a748359f73d5af91ee03c6b3330b2faa11602704a4f87266ef578113',  # palette caption, word highlight
        21.733333: 'adfde9b185dd17c19183369b09445111036fa1d0b828df3903508040c042c0b1',
    }
    for t, expected in hashes.items():
        assert hashlib.sha256(prod.frame(t).tobytes()).hexdigest() == expected


def test_native_recipes_and_square_round_geometry(tmp_path):
    from kinodraw.engine.hybrid import _SquareLayers
    from kinodraw.engine.bold.model import MotionElement, MotionScene
    from kinodraw.engine.bold import render as bold
    board, plan, tl = fixture(tmp_path)
    native = native_production(board, tl, 'en', tmp_path, (3840, 2160)).whiteboard
    legacy = render.Production(board, tl, 'en', tmp_path)
    assert [(e.start, e.rate, e.hidden_after, e.group) for e in native.els] == [
        (e.start, e.rate, e.hidden_after, e.group) for e in legacy.els]
    for a, b in zip(native.els, legacy.els):
        assert (a.x, a.y) == (2*b.x, 2*b.y)
        assert a.drawing.duration == b.drawing.duration
        if isinstance(a.drawing, ink.TextDrawing):
            assert a.drawing.native_recipe[1][2] == 2*b.drawing.native_recipe[1][2]
            assert a.drawing.native_recipe[2]['fonts'] == b.drawing.native_recipe[2]['fonts']
        if getattr(a.drawing, 'doodle', False):
            assert a.drawing.native_recipe[1][1] == tuple(2*v for v in b.drawing.native_recipe[1][1])
    t = tl['end_card']['end']-.1
    a = native.frame(t)
    b = legacy.frame(t).resize(a.size, Image.Resampling.LANCZOS)
    assert a.tobytes() != b.tobytes()
    scene = MotionScene([MotionElement(kind='ring', size=240)], motion_floor=0, camera='static')
    layers = _SquareLayers(scene, 1080, 1080)
    moved = bold._warp(layers.sprite(0, 2, 'art'), bold.element_pose(scene, scene.elements[0], 0, 2), 1080, 1080)
    alpha = moved[2][..., 3]
    y, x = np.nonzero(alpha > .5)
    assert abs((x.max()-x.min())-(y.max()-y.min())) <= 2


@pytest.mark.parametrize('size,aspect', [((3840, 2160), '16:9'), ((1080, 1080), '1:1')])
def test_actual_native_clips_and_saved_props(tmp_path, monkeypatch, size, aspect, procedural_rig):
    import shutil
    from kinodraw.engine import hybrid
    from kinodraw.export import FFMPEG
    board, plan, tl = fixture(tmp_path)
    prop = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300"><circle cx="150" cy="150" r="120" fill="#f08030"/><path d="M40 150H260 M150 40V260" stroke="#112233" stroke-width="2"/></svg>'
    (tmp_path/'doodles').mkdir()
    (tmp_path/'doodles'/'gen-native.svg').write_text(prop)
    plan['scenes'][1]['elements'].append({'kind':'picture','ref':'gen-native'})
    # Preserve explicit quantities through the native chart adapter as well.
    plan['scenes'][2]['treatment'] = 'chart'
    board['beats'][2]['visuals'].append({'id':'native-values','type':'bars',
        'rows':[{'value':42.5,'label':'A'},{'value':-7,'label':'B'}]})
    (tmp_path/'project.json').write_text(json.dumps({'director_v3':True,'plan_v3':plan}))
    monkeypatch.setattr(hybrid, 'prepare_props', lambda *a, **kw: pytest.fail('provider preparation on rerender'))
    prod = native_production(board, tl, 'en', tmp_path, size, aspect=aspect)
    assert any(e.svg == prop for e in prod.spans[1].motion.elements)
    assert any(e.values == (42.5,-7) for e in prod.spans[2].motion.elements)
    assert all(s.atmos.internal_size == size for s in prod.spans if s.atmos)
    evidence = tmp_path
    label = '4k' if aspect == '16:9' else 'square'
    seen = []
    original_render = hybrid.render_frame
    original_raster = hybrid.raster
    def motion(scene,t,w,h,**kw):
        seen.append(('motion',w,h))
        return original_render(scene,t,w,h,**kw)
    def rig(g,pose,t,**kw):
        seen.append(('rig',g.name,kw['height']))
        return original_raster(g,pose,t,**kw)
    monkeypatch.setattr(hybrid,'render_frame',motion)
    monkeypatch.setattr(hybrid,'raster',rig)
    frames = {}
    for i, span in enumerate(prod.spans):
        t = span.start + min(1.1,(span.end-span.start)*.5)
        frame = prod.frame(t)
        assert frame.size == size
        frames[str(t)] = hashlib.sha256(frame.tobytes()).hexdigest()
        if i in (0,1,2):
            frame.save(evidence/f'{label}-scene-{i}.png')
    end = prod.frame(tl['end_card']['end']-.1)
    end.save(evidence/f'{label}-endcard.png')
    assert end.size == size
    assert any(v[0]=='rig' for v in seen)
    if aspect == '16:9':
        assert ('motion',*size) in seen
        assert any(v[0]=='rig' and v[2] > 1080 for v in seen)
    else:
        assert prod._square_layers
    start = prod.spans[1].start+1.1
    output = evidence/f'{label}.mp4'
    # Record the encoder's actual process status, not just the API's return.
    original_popen = subprocess.Popen
    processes = []
    def popen(cmd,*a,**kw):
        process = original_popen(cmd,*a,**kw)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess,'Popen',popen)
    render.encode(prod,start,3,output,20)
    assert processes and all(p.returncode==0 for p in processes)
    encoder_exits = [p.returncode for p in processes]
    probe = subprocess.run([shutil.which('ffprobe'),'-v','error','-count_frames','-show_streams','-of','json',str(output)],capture_output=True,text=True,timeout=30)
    assert probe.returncode==0,probe.stderr
    stream = json.loads(probe.stdout)['streams'][0]
    assert (stream['width'],stream['height'])==size and int(stream['nb_read_frames'])==3
    decoded = subprocess.run([FFMPEG,'-v','error','-i',str(output),'-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=60)
    assert decoded.returncode==0,decoded.stderr
    assert len(decoded.stdout)==3*size[0]*size[1]*3
    Image.frombytes('RGB',size,decoded.stdout[:size[0]*size[1]*3]).save(evidence/f'{label}-decoded.png')
    report = {'size':size,'aspect':aspect,'frames':3,'encoder_exits':encoder_exits,'probe_exit':probe.returncode,
              'decode_exit':decoded.returncode,'raw_hashes':frames,'native_calls':seen,
              'cast':{k:v.to_dict() for k,v in prod.cast.items()},'style':prod.style,
              'source_spans':[(s.start,s.end,s.spec['camera'],s.spec['transition_in']) for s in prod.spans]}
    (evidence/f'{label}-report.json').write_text(json.dumps(report,indent=2)+'\n')

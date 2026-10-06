"""Public native adapter regressions and actual local media acceptance."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from kinodraw import pipeline
from kinodraw.project_store import ProjectStore


@pytest.mark.parametrize('aspect,size', [('1:1',(1080,1080)),('16:9',(3840,2160)),('9:16',(1080,1920))])
def test_saved_native_format_and_finish_size(tmp_path, monkeypatch, aspect, size):
    pipeline.new_project('# Native\n\nA small idea.', tmp_path)
    pipeline.set_format(tmp_path, aspect=aspect, size=size)
    saved = ProjectStore(tmp_path).load()
    monkeypatch.setattr(pipeline, 'video_size', lambda path: size)
    assert pipeline._check_render_size(tmp_path, saved) == size
    assert saved['settings']['aspect'] == aspect
    assert tuple(saved['settings']['size']) == size


@pytest.mark.parametrize('aspect,size,look', [('1:1',(1920,1080),None),('16:9',(3839,2160),None),('9:16',(2160,3840),None),('1:1',(1080,1080),'collage'),('16:9',(3840,2160),'collage')])
def test_bad_native_format_does_not_touch_source(tmp_path, aspect, size, look):
    pipeline.new_project('# Native\n\nA small idea.', tmp_path)
    if look:
        s=ProjectStore(tmp_path).load();s['storyboard']['look']=look
        ProjectStore(tmp_path).save(s['storyboard'],s['settings'],s['revision'])
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        pipeline.set_format(tmp_path, aspect=aspect, size=size)
    assert before == {str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def saved_native_project(path):
    """A copied saved vector plan with local cached tone; the fixture is immutable."""
    import numpy as np
    from kinodraw.audio import mix
    fixture=Path(__file__).parent/'fixtures/native_saved_project'
    path.mkdir(parents=True)
    shutil.copytree(fixture/'doodles',path/'doodles')
    board=json.loads((fixture/'storyboard.json').read_text())
    cfg=json.loads((fixture/'project.json').read_text())
    cfg.update(lang='en',voice='am_michael',speed=1.0,workers=1,aspect='16:9',credit=False,script='cached-source.md')
    board.update(music=False,sfx=False)
    ProjectStore(path).initialize(board,cfg)
    (path/'cached-source.md').write_text('Saved native adapter acceptance source.\n')
    build=path/'build';build.mkdir()
    tl=json.loads((fixture/'timeline.json').read_text())
    tl.update(audio='narration.wav',layout='landscape',storyboard_sha256=pipeline.sha(path/'storyboard.json'))
    pipeline._save(build/'timeline.json',tl)
    mix.write_captions(tl['captions'],build)
    tone=.12*np.sin(2*np.pi*440*np.arange(round(tl['duration']*mix.SR))/mix.SR)
    mix.write_wav(build/'narration.wav',tone)
    pipeline._hybrid_audio(board,tl,build,cfg)
    return path


def decode_media(path, frames, size, *, audio=True):
    from kinodraw.engine import render
    from kinodraw.progress import encoded_frames
    progress=path.with_name(path.name+'.decode-progress')
    argv=[render.FFMPEG,'-v','error','-xerror','-err_detect','explode','-i',str(path),'-map','0:v:0']
    if audio:argv+=['-map','0:a:0']
    argv+=['-vsync','0','-progress',str(progress),'-f','null','-']
    result=subprocess.run(argv,capture_output=True,timeout=120)
    assert result.returncode==0 and not result.stderr,result.stderr
    assert encoded_frames(progress)==frames
    assert pipeline.video_size(path)==size
    return dict(argv=argv,exit=result.returncode,frames=encoded_frames(progress),size=size,audio=audio,sha256=pipeline.sha(path))


def evidence(name,data):
    from datetime import datetime,timezone
    out=Path(__file__).resolve().parents[1]/'docs/overnight-2026-10-05/evidence/sol-native-adapter'
    out.mkdir(parents=True,exist_ok=True)
    (out/(name+'.json')).write_text(json.dumps(dict(date=datetime.now(timezone.utc).isoformat(),**data),indent=2)+'\n')


@pytest.mark.parametrize('aspect,size,start',[('1:1',(1080,1080),7.703809523809524),('16:9',(3840,2160),18.517379806505694)])
def test_actual_public_cli_module_native_frames(tmp_path, aspect, size, start):
    from kinodraw.engine import render
    project=saved_native_project(tmp_path/'project')
    baseline={str(p.relative_to(project)):pipeline.sha(p) for p in project.rglob('*') if p.is_file() and p.suffix in ('.svg','.wav')}
    # Only account/migration setup is synthetic; run the actual public module.
    code="""import runpy,sys
sys.path.insert(0,'tests')
import conftest,keyring.core
keyring.core._keyring_backend=conftest._Keychain()
from kinodraw import paths
paths.migrate=lambda *a,**k:[]
paths.left_behind=[]
sys.argv=['kinodraw',*sys.argv[1:]]
runpy.run_module('kinodraw.cli',run_name='__main__')
"""
    argv=[sys.executable,'-B','-c',code,'render',str(project),'--aspect',aspect,'--size',*map(str,size),'--workers','2','--start',str(start),'--duration',str(4/render.FPS)]
    result=subprocess.run(argv,capture_output=True,text=True,timeout=150)
    evidence('public-cli-attempt-'+str(size[0]),dict(argv=argv,exit=result.returncode,stdout=result.stdout,stderr=result.stderr))
    assert result.returncode==0,result.stdout+result.stderr
    media=decode_media(project/'build/silent.mp4',4,size,audio=False)
    assert baseline=={key:pipeline.sha(project/key) for key in baseline}
    cfg=pipeline.settings(project)
    prod=render.make_production(pipeline.storyboard(project),pipeline._load(project/'build/timeline.json'),'en',project,size=size,aspect=aspect)
    assert prod.whiteboard.native and prod.whiteboard.size==size
    assert any(e.values==(42.5,-7) for e in prod.spans[2].motion.elements)
    assert any('r="120"' in e.svg for e in prod.spans[1].motion.elements if e.svg)
    evidence('public-cli-'+str(size[0]),dict(argv=argv,exit=result.returncode,stdout=result.stdout,media=media,cached_hashes=baseline,factory=type(prod).__name__,whiteboard=type(prod.whiteboard).__name__,native_size=prod.whiteboard.size))


def test_actual_full_square_pipeline_finish(tmp_path):
    from kinodraw.engine import render
    project=saved_native_project(tmp_path/'project')
    before={p.name:pipeline.sha(p) for p in (project/'build/narration.wav',project/'build/mix.wav')}
    pipeline.render(project,size=(1080,1080),aspect='1:1')
    qa=pipeline.finish(project)
    assert qa['ok'],qa
    tl=pipeline._load(project/'build/timeline.json')
    media=decode_media(Path(qa['video']),round(tl['duration']*render.FPS),(1080,1080))
    assert before=={p.name:pipeline.sha(p) for p in (project/'build/narration.wav',project/'build/mix.wav')}
    assert (project/'Small story.srt').is_file()
    assert (project/'Small story-thumbnail.png').is_file()
    from PIL import Image
    with Image.open(project/'Small story-thumbnail.png') as thumbnail:
        assert thumbnail.size == (720,720)
    evidence('full-square-finish',dict(qa=qa,media=media,cached_hashes=before,scope='Complete 21.833333-second saved fixture, local tone narration; not a long showcase.'))


def test_new_native_size_invalid_before_directory_created(tmp_path):
    project=tmp_path/'new'
    with pytest.raises(ValueError):
        pipeline.new_project('A small idea.',project,aspect='1:1',size=[3840,2160])
    assert not project.exists()


def test_new_renderer_keywords_are_optional():
    import inspect
    parameters=inspect.signature(pipeline.render).parameters
    assert parameters['size'].default is None and parameters['aspect'].default is None


def test_square_auto_style_offers_only_native_whiteboard_recipes():
    from kinodraw.director import style
    from kinodraw import styles
    options=style.options('1:1','en',None)
    assert options
    assert all(styles.renderer(option['id'].split('/')[0])=='whiteboard' for option in options)

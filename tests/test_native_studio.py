"""Direct Studio adapters; no socket, providers, or account access."""
from pathlib import Path
import sys
import types
import pytest
from kinodraw import pipeline
from kinodraw.progress import Cancelled
from kinodraw.project_store import ProjectStore, RevisionConflict
from kinodraw.studio import integration, server


def source_project(tmp_path, monkeypatch):
    root=tmp_path/'projects';path=root/'native'
    pipeline.new_project('# Native\n\nA small idea.',path)
    monkeypatch.setattr(server,'projects_root',lambda:root)
    integration.DOWNLOADS.clear()
    (path/'made.mp4').write_bytes(b'previous-output')
    return path


def test_export_rejects_link_before_resolving(tmp_path, monkeypatch):
    path=source_project(tmp_path,monkeypatch)
    (path/'linked.mp4').symlink_to(path/'made.mp4')
    def unexpected(*a,**kw):
        pytest.fail('linked source reached encoder')
    monkeypatch.setitem(sys.modules,'kinodraw.export',types.SimpleNamespace(export_video=unexpected))
    with pytest.raises(ValueError,match='regular'):
        integration.export(path,{'source':'linked.mp4'},server.JobContext({}))


@pytest.mark.parametrize('change',['cancel','revision'])
def test_export_guard_precedes_download_registration(tmp_path, monkeypatch, change):
    path=source_project(tmp_path,monkeypatch);ctx=server.JobContext({})
    def late(source,output,**kw):
        output.write_bytes(b'encoded')
        if change=='cancel':ctx.cancel()
        else:
            saved=ProjectStore(path).load();saved['settings']['speed']=1.1
            ProjectStore(path).save(saved['storyboard'],saved['settings'],saved['revision'])
    monkeypatch.setitem(sys.modules,'kinodraw.export',types.SimpleNamespace(export_video=late))
    with pytest.raises((Cancelled,RevisionConflict,server.JobCancelled)):
        integration.export(path,{'source':'made.mp4'},ctx)
    assert not integration.DOWNLOADS
    assert (path/'made.mp4').read_bytes()==b'previous-output'


@pytest.mark.parametrize('fmt',['webm','gif'])
def test_actual_direct_studio_native_export_preserves_original(tmp_path, monkeypatch, fmt):
    from test_native_pipeline import saved_native_project,decode_media,evidence
    from kinodraw.engine import render
    root=tmp_path/'projects';path=saved_native_project(root/'native')
    monkeypatch.setattr(server,'projects_root',lambda:root)
    integration.DOWNLOADS.clear()
    (path/'original.mp4').write_bytes(b'previous finished output preserved')
    before={str(p.relative_to(path)):pipeline.sha(p) for p in path.rglob('*') if p.is_file()}
    context=server.JobContext({})
    result=integration.export(path,{'format':fmt,'size':[1080,1080],'aspect':'1:1','revision':ProjectStore(path).load()['revision']},context)
    output=integration.DOWNLOADS[(path.name,result['file'])]
    tl=pipeline._load(path/'build/timeline.json')
    media=decode_media(output,round(tl['duration']*render.FPS),(1080,1080),audio=fmt=='webm')
    assert before=={key:pipeline.sha(path/key) for key in before}
    assert not context.token.owned_pids
    if fmt=='gif':
        companion=integration.DOWNLOADS[(path.name,result['audio_file'])]
        assert companion.read_bytes()==(path/'build/mix.wav').read_bytes()
    evidence('studio-native-'+fmt,dict(result=result,media=media,source_hashes=before,source_unchanged=True,progress=context.job))


def test_make_validates_and_forwards_saved_target(tmp_path, monkeypatch):
    path=source_project(tmp_path,monkeypatch)
    monkeypatch.setattr(server,'apply_video_settings',lambda p:None)
    seen=[]
    def produce(p,*a,**kw):
        seen.append(pipeline.settings(p))
        return dict(video=str(p/'made.mp4'),ok=True,problems=[],length='0:01')
    monkeypatch.setattr(pipeline,'produce',produce)
    integration.make(path,{'aspect':'1:1','size':[1080,1080]},server.JobContext({}))
    assert seen[0]['aspect']=='1:1' and seen[0]['size']==[1080,1080]
    with pytest.raises(ValueError):
        integration.make(path,{'aspect':'9:16','size':[3840,2160]},server.JobContext({}))
    assert len(seen)==1


@pytest.mark.parametrize('source',['../outside.mp4','/tmp/outside.mp4','nested/link.mp4'])
def test_export_source_paths_remain_confined(tmp_path,monkeypatch,source):
    path=source_project(tmp_path,monkeypatch)
    (path/'nested').mkdir();(path/'nested/link.mp4').symlink_to(path/'made.mp4')
    with pytest.raises(ValueError,match='regular'):
        integration.export(path,{'source':source},server.JobContext({}))
    assert not integration.DOWNLOADS


def test_unsupported_studio_variant_before_outputs_touched(tmp_path,monkeypatch):
    path=source_project(tmp_path,monkeypatch)
    before={str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        integration.export(path,{'size':[3840,2160],'aspect':'1:1'},server.JobContext({}))
    assert before=={str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*') if p.is_file()}
    assert not (path.parent/'.downloads').exists()

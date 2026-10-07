import json
from pathlib import Path

from kinodraw import pipeline
from kinodraw.project_store import ProjectStore


def test_make_keeps_a_video_whose_checks_fail(tmp_path, monkeypatch):
    """A finished video is published with its problems as warnings, never silently discarded."""
    pipeline.new_project('# Tone\n\nThe small idea stays.', tmp_path)
    saved = ProjectStore(tmp_path).load()
    stem = pipeline._output_stem(saved['storyboard'], saved['settings'])
    problems = ['frozen_picture at 8.633-12.767s: 4.133s outside permitted exemptions']
    monkeypatch.setattr(pipeline, 'narrate', lambda *a, **k: [])
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'render', lambda *a, **k: None)

    def finish(stage, **kwargs):
        (stage / f'{stem}.mp4').write_bytes(b'finished video')
        (stage / 'build').mkdir(exist_ok=True)
        return {'ok': False, 'problems': problems, 'length': '00:01', 'video': str(stage / f'{stem}.mp4')}
    monkeypatch.setattr(pipeline, 'finish', finish)

    qa = pipeline.produce(tmp_path)
    assert not qa['ok'] and qa['problems'] == problems
    assert Path(qa['video']) == tmp_path / f'{stem}.mp4'
    assert Path(qa['video']).read_bytes() == b'finished video'
    assert json.loads((tmp_path / 'build/qa.json').read_text(encoding='utf-8'))['problems'] == problems

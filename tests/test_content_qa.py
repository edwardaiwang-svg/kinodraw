"""Content QA: findings on whether a video shows what its script says (gauntlet r1, 2026-10-08)."""
import copy

import imageio_ffmpeg
import numpy as np

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import timeline
from kinodraw.qa import content

STORY = ('# The Bus Home\n\n'
         'Once upon a time, a girl named Ana lived in a quiet town by the sea.\n\n'
         'Every morning Ana rode the bus to school with her grandpa. He always carried a paper bag of warm bread.\n\n'
         'One day the bag tore, and an apple rolled down the street. Ana ran after it.\n\n'
         'Later, her mother sat on the couch in front of the TV. "You were brave today," she said.\n\n'
         '"It was only an apple," Ana said, and she laughed. Her grandpa laughed too.')


def _story():
    board = script.build(ingest.read(STORY), story='story')
    RulesDirector('en').direct(board)
    return from_rules(board), board


def _empty(plan):
    """What the offline director used to answer for a human story: no cast and nothing in the scenes."""
    empty = copy.deepcopy(plan)
    empty['cast'] = []
    for scene in empty['scenes']:
        scene['elements'], scene['actions'] = [], []
        scene['atmosphere'] = {'kind': 'none', 'density': 0}
    return empty


def test_an_empty_story_plan_fails_every_content_check():
    plan, board = _story()
    report = content.check(_empty(plan), board)
    assert {f['check'] for f in report['findings']} == {'unshown', 'no_people', 'no_speaker'}
    assert all(isinstance(p, str) and p for p in report['problems'])


def test_a_staged_story_plan_passes():
    plan, board = _story()
    report = content.check(plan, board)
    assert report['problems'] == [], report['problems']
    assert report['stats']['concrete'] >= 6


def test_people_the_plan_leaves_out_are_reported():
    plan, board = _story()
    plan = copy.deepcopy(plan)
    for scene in plan['scenes']:
        scene['elements'] = [e for e in scene['elements'] if e['kind'] != 'cast']
    checks = {f['check'] for f in content.check(plan, board)['findings']}
    assert {'no_people', 'no_speaker'} <= checks


def test_an_explainer_fails_only_when_its_scenes_show_nothing():
    board = script.build(ingest.read('# Rain\n\nClouds hold water. Drops grow heavy. Then they fall as rain. '
                                     'The ground drinks it up.'), story='story')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    assert plan['storyboard']['genre'] != 'story'
    assert content.check(plan, board)['problems'] == []
    blank = copy.deepcopy(plan)
    for scene in blank['scenes']:
        scene.update(elements=[], treatment='whiteboard', text={'kind': 'caption_only', 'ref': scene['beat_ids'][0]})
    assert [f['check'] for f in content.check(blank, board)['findings']] == ['unshown']


def test_other_languages_are_not_judged_by_english_word_lists():
    plan, board = _story()
    board = {**board, 'lang': 'zh'}
    assert content.check(_empty(plan), board)['problems'] == []


def _video(path, pictures, seconds=1.0, size=(160, 90)):
    """One picture per second; a moving caption band at the bottom never counts as a new picture."""
    writer = imageio_ffmpeg.write_frames(str(path), size, fps=10, macro_block_size=1)
    writer.send(None)
    for k, level in enumerate(pictures):
        for f in range(int(10 * seconds)):
            frame = np.full((size[1], size[0], 3), level, np.uint8)
            frame[-12:, (f * 7 + k * 13) % size[0]:, :] = 0          # captions change under a frozen picture
            writer.send(frame.tobytes())
    writer.close()


def test_one_unchanged_picture_across_three_sentences_is_found(tmp_path):
    video = tmp_path / 'v.mp4'
    _video(video, [200, 200, 200, 200, 90, 30, 30, 160])
    lines = [content.Line('b1', 0, 1, f's{i}', 0, at=i + .5) for i in range(8)]
    assert content.same_runs(video, lines) == [(0, 3)]
    _video(video, [200, 200, 90, 90, 30, 160, 160, 60])
    assert content.same_runs(video, lines) == []


def test_finish_reports_a_frozen_composition_as_a_problem(tmp_path):
    plan, board = _story()
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    video = tmp_path / 'v.mp4'
    _video(video, [200] * int(tl['duration'] + 1))
    report = content.check(plan, board, tl, video)
    assert [f['check'] for f in report['findings']] == ['same_picture']
    assert 'does not change for' in report['problems'][0]


def test_content_findings_are_reported_beside_the_qa_and_never_fail_the_finish(tmp_path, monkeypatch):
    """They are heuristics the customer cannot act on: kept in qa['content'], never in qa['problems'] or qa['ok']."""
    import json
    from types import SimpleNamespace
    from kinodraw import pipeline
    plan, board = _story()
    board = {**board, 'title': {'en': 'The Bus Home'}}
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    folder = tmp_path / 'p'
    (folder / 'build').mkdir(parents=True)
    (folder / 'build' / 'timeline.json').write_text(json.dumps(tl), encoding='utf-8')
    saved = {'settings': {'lang': 'en', 'plan_v3': plan}, 'storyboard': board}
    monkeypatch.setattr(pipeline, 'ProjectStore', lambda d: SimpleNamespace(load=lambda: saved))
    monkeypatch.setattr(pipeline, '_check_render_size', lambda *a: (1280, 720))
    monkeypatch.setattr(pipeline, '_narrated_pages', lambda *a: None)
    monkeypatch.setattr(pipeline.audio, 'mix', lambda *a: None)
    for name in ('mux', 'publish', 'contact_sheet'):
        monkeypatch.setattr(pipeline, name, lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'encoded_qa', lambda *a, **k: {'ok': True, 'problems': []})
    monkeypatch.setattr(pipeline.subprocess, 'run', lambda args, **k: SimpleNamespace(returncode=0, stderr=b''))
    found = {'problems': ['The picture does not change for 7 sentences in a row.'],
             'findings': [{'check': 'same_picture', 'problem': 'The picture does not change for 7 sentences in a row.'}],
             'stats': {'sentences': 9}, 'lines': []}
    monkeypatch.setattr(content, 'check', lambda *a, **k: found)
    qa = pipeline._finish(folder)
    assert qa['ok'] is True and qa['problems'] == []
    assert qa['content'] == {'problems': found['problems'], 'findings': found['findings'], 'stats': found['stats']}

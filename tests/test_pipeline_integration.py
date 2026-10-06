import copy

import pytest

from kinodraw import pipeline
from kinodraw.project_store import ProjectStore, RevisionConflict
from kinodraw.director.llm.providers import Usage
from kinodraw.director.v3.rules import from_rules


def test_long_v3_plan_rejects_intervening_edit(tmp_path, monkeypatch):
    from kinodraw.director.v3 import llm
    pipeline.new_project('# Test\n\nA small idea.', tmp_path, director_v3=True)
    def plan(board, provider=None):
        store = ProjectStore(tmp_path)
        state = store.load()
        state['storyboard']['title']['en'] = 'Manual title'
        store.save(state['storyboard'], state['settings'], state['revision'])
        return from_rules(board), {'notes': [], 'usage': Usage()}
    monkeypatch.setattr(llm, 'plan_v3', plan)
    with pytest.raises(RevisionConflict):
        pipeline.direct_v3(tmp_path)
    assert pipeline.storyboard(tmp_path)['title']['en'] == 'Manual title'


def test_v3_preserves_manual_visuals_and_cache(tmp_path, monkeypatch):
    pipeline.new_project('# Test\n\nA small idea.', tmp_path, director_v3=True)
    store = ProjectStore(tmp_path)
    state = store.load()
    visual = {'id': 'manual-art', 'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'book_stack'}]}
    state['storyboard']['beats'][0]['visuals'] = [visual]
    store.save(state['storyboard'], state['settings'], state['revision'])
    pipeline.direct_v3(tmp_path)
    assert visual in pipeline.storyboard(tmp_path)['beats'][0]['visuals']
    from kinodraw.director.v3 import llm
    monkeypatch.setattr(llm, 'plan_v3', lambda *a, **k: pytest.fail('cached plan called provider'))
    pipeline.direct_v3(tmp_path)


def test_legacy_direct_rejects_intervening_edit(tmp_path, monkeypatch):
    from kinodraw import director
    from kinodraw.director import match, rules
    pipeline.new_project('# Test\n\nA small idea.', tmp_path)
    monkeypatch.setattr(match, 'ensure_model', lambda *a: None)
    monkeypatch.setattr(rules.RulesDirector, '__init__', lambda self, lang: None)
    def draw(self, board):
        store = ProjectStore(tmp_path)
        state = store.load()
        state['settings']['speed'] = 1.1
        store.save(state['storyboard'], state['settings'], state['revision'])
    monkeypatch.setattr(rules.RulesDirector, 'direct', draw)
    with pytest.raises(RevisionConflict):
        director.direct(tmp_path)
    assert pipeline.settings(tmp_path)['speed'] == 1.1


def test_build_json_rejects_nonfinite_without_replacing_good_output(tmp_path):
    target = tmp_path / 'timeline.json'
    pipeline._save(target, {'duration': 1})
    before = target.read_bytes()
    with pytest.raises(ValueError):
        pipeline._save(target, {'duration': float('nan')})
    assert target.read_bytes() == before


def test_cli_settings_keep_director_model_base_and_v3(monkeypatch):
    from argparse import Namespace
    from kinodraw import cli
    monkeypatch.setattr(cli, '_server_settings', lambda args: None)
    cfg = cli._settings(Namespace(director='command', director_v3=True, model='chosen-model',
                                  base_url='http://127.0.0.1:1/v1'))
    assert cfg['director'] == 'command' and cfg['director_v3']
    assert cfg['model'] == 'chosen-model' and cfg['base_url'] == 'http://127.0.0.1:1/v1'


def test_cli_voice_server_removal_saves_paired_state(tmp_path, monkeypatch):
    from argparse import Namespace
    from kinodraw import cli
    pipeline.new_project('# Test\n\nA small idea.', tmp_path, voice_server={'model': 'synthetic'})
    before = ProjectStore(tmp_path).load()
    monkeypatch.setattr(cli, '_server_settings', lambda args: False)
    monkeypatch.setattr(pipeline, 'narrate', lambda *a, **kw: {})
    monkeypatch.setattr(pipeline, 'build_audio', lambda *a: {'duration': 0, 'captions': []})
    cli.cmd_voice(Namespace(project=str(tmp_path), recording=None))
    after = ProjectStore(tmp_path).load()
    assert 'voice_server' not in after['settings']
    assert after['storyboard'] == before['storyboard'] and after['revision'] != before['revision']
    assert any(v['revision'] == before['revision'] for v in ProjectStore(tmp_path).versions())

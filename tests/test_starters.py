from pathlib import Path

import pytest

from kinodraw import pipeline, starters
from kinodraw.director.validate import validate


def test_eight_editable_en_zh_starters_build_real_boards(tmp_path):
    entries = starters.list_starters()
    assert len(entries) >= 8
    assert {entry['lang'] for entry in entries} == {'en', 'zh'}
    for entry in entries:
        text = starters.read(entry['id'])
        assert 'Invented example' in text or '虚构示例' in text
        assert Path(entry['path']).suffix == '.md'
        board = pipeline.new_project(text, tmp_path / entry['id'], lang=entry['lang'])
        assert validate(board, tmp_path / entry['id'])['ok']


@pytest.mark.parametrize('name', ['../bad', '/tmp/bad', 'unknown', 'explainer-en.md'])
def test_unknown_starter_is_refused(name):
    with pytest.raises(ValueError):
        starters.read(name)

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from kinodraw import cli

REPO = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run([sys.executable, '-m', 'kinodraw.cli', *args], cwd=REPO,
                          capture_output=True, text=True, timeout=35)


def test_real_cli_starter_validate_chart_and_png(tmp_path):
    listed = run('starter', '--list')
    assert listed.returncode == 0, listed.stderr
    assert len(json.loads(listed.stdout)) >= 8
    created = run('starter', 'explainer-en', '--root', str(tmp_path), '-o', 'demo')
    assert created.returncode == 0, created.stderr
    valid = run('validate', 'demo', '--root', str(tmp_path))
    assert valid.returncode == 0 and json.loads(valid.stdout)['ok'], valid.stderr
    board = json.loads((tmp_path / 'demo/storyboard.json').read_text(encoding='utf-8'))
    data = {'source': 'Invented example data, not genuine', 'title': 'Example',
            'rows': [{'label': 'A', 'value': 3}]}
    (tmp_path / 'data.json').write_text(json.dumps(data), encoding='utf-8')
    added = run('chart-add', 'demo', '--root', str(tmp_path), '--beat', board['beats'][1]['id'], '--source', 'data.json')
    assert added.returncode == 0, added.stderr
    preview = run('preview', 'demo', '--root', str(tmp_path), '--time', '0.2')
    assert preview.returncode == 0, preview.stderr
    assert Path(json.loads(preview.stdout)['path']).read_bytes().startswith(b'\x89PNG')
    refused = run('chart-add', 'demo', '--root', str(tmp_path), '--beat', 'missing', '--source', 'data.json')
    assert refused.returncode == 1 and 'missing' in refused.stderr


def test_old_new_and_render_flags_keep_their_meaning(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, 'cmd_new', lambda args: seen.append(args))
    monkeypatch.setattr(cli, 'cmd_render', lambda args: seen.append(args))
    cli.main(['new', 'script text', '-o', 'video', '--director', 'rules', '--no-credit',
              '--aspect', '9:16', '--voice', 'af_heart', '--speed', '1.1', '--workers', '1'])
    assert seen[-1].no_credit and seen[-1].aspect == '9:16' and seen[-1].speed == 1.1
    cli.main(['render', 'video', '--stills', '1,2', '--start', '0', '--duration', '.1', '--workers', '1'])
    assert seen[-1].stills == '1,2' and seen[-1].duration == .1


@pytest.mark.parametrize('token', ['9007199254740993.0', '1e-400'])
def test_real_cli_refuses_lossy_chart_numbers(tmp_path, token):
    assert run('starter', 'explainer-en', '--root', str(tmp_path), '-o', 'demo').returncode == 0
    path = tmp_path / 'demo/storyboard.json'
    before = path.read_bytes()
    board = json.loads(before)
    (tmp_path / 'loss.json').write_text(
        '{"source":"Invented example","title":"Loss","rows":[{"label":"A","value":'
        + token + '}]}', encoding='utf-8')
    result = run('chart-add', 'demo', '--root', str(tmp_path), '--beat', board['beats'][1]['id'],
                 '--source', 'loss.json')
    assert result.returncode == 1 and 'loses precision' in result.stderr, result
    assert path.read_bytes() == before


def test_real_cli_refuses_svg_resources_and_collage(tmp_path):
    assert run('starter', 'explainer-en', '--root', str(tmp_path), '-o', 'demo').returncode == 0
    outside = tmp_path.parent / (tmp_path.name + '-synthetic.png')
    Image.new('RGB', (16, 16), 'magenta').save(outside)
    pictures = tmp_path / 'demo/pictures'
    pictures.mkdir()
    (pictures / 'unsafe.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'viewBox="0 0 100 100"><image xlink:href="' + str(outside) +
        '" width="100" height="100"/></svg>', encoding='utf-8')
    path = tmp_path / 'demo/storyboard.json'
    board = json.loads(path.read_text(encoding='utf-8'))
    board['beats'][1]['visuals'] = [{'id': 'own_picture', 'type': 'cluster',
                                   'items': [{'doodle': 'own:unsafe.svg'}]}]
    path.write_text(json.dumps(board), encoding='utf-8')
    for command in ('validate', 'preview'):
        result = run(command, 'demo', '--root', str(tmp_path))
        assert result.returncode == 1 and 'SVG' in result.stderr, result
    board['look'] = 'collage'
    path.write_text(json.dumps(board), encoding='utf-8')
    for command in ('validate', 'preview'):
        result = run(command, 'demo', '--root', str(tmp_path))
        assert result.returncode == 1 and 'collage' in result.stderr and 'offline' in result.stderr, result
    assert not (tmp_path / 'demo/build').exists()

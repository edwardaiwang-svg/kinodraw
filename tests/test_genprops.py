import io
import json

import pytest
import resvg_py
from PIL import Image


PALETTE = ['#E53935']
GOOD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
        'width="512" height="512" fill="#E53935" stroke="#1B1B1B" '
        'stroke-width="6" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="40" y="40" width="432" height="432"/>'
        '<circle cx="160" cy="160" r="30"/><circle cx="350" cy="160" r="30"/>'
        '<path d="M100 300 H400" fill="none"/><path d="M100 350 H400" fill="none"/></svg>')
HOSTILE = GOOD.replace('width="512"', 'onload="alert(1)" width="512"', 1).replace(
    '</svg>', '<script>alert(1)</script><foreignObject><p>bad</p></foreignObject>'
    '<image href="https://example.invalid/a"/><use href="data:x"/><animate/>'
    '<style>rect {fill:url(https://example.invalid/a)}</style>'
    '<g onclick="bad()" style="fill:url(file:///bad)"><path d="M100 400 H400" '
    'fill="url(https://example.invalid/a)" href="file:///bad"/></g></svg>')


def api():
    from kinodraw.library import genprops
    return genprops


def test_good_cache_provenance_and_real_drawing(tmp_path):
    prompts = []
    def llm(prompt):
        prompts.append(prompt)
        return GOOD
    llm.model = 'canned-director'
    prop = api().request_prop('lion paw', PALETTE, 'bold flat', llm, project=tmp_path)
    assert prop.path.parent == tmp_path / 'doodles'
    assert prop.path.read_text(encoding='utf-8') == prop.svg
    from kinodraw.library import resolve
    assert resolve(prop.path.stem, tmp_path) == prop.path
    image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_path=str(prop.path), width=150)))
    assert image.getchannel('A').getbbox()
    from kinodraw.engine.ink import svg_drawing
    drawing = svg_drawing(prop.path, (150, 150))
    assert drawing.polys and drawing.state(drawing.duration)[0].getchannel('A').getbbox()
    data = json.loads(prop.path.with_suffix('.json').read_text(encoding='utf-8'))
    assert data['model'] == 'canned-director' and data['repairs'] == 0
    assert len(data['prompt_hash']) == 64 and data['timestamp']
    assert data['sanitizer_actions'] == []
    again = api().request_prop('lion paw', PALETTE, 'bold flat', llm, project=tmp_path)
    assert again.svg == prop.svg and len(prompts) == 1
    assert all(word in prompts[0].lower() for word in ('512', '40', 'round', '#e53935', 'no text'))


def test_hostile_is_sanitized_cached_and_rasterized(tmp_path):
    prop = api().request_prop('hostile paw', PALETTE, 'bold flat', lambda _: HOSTILE, project=tmp_path)
    assert prop is not None
    assert not any(s in prop.svg for s in ('script', 'onload', 'onclick', 'foreignObject', 'href', 'url(', 'data:', 'animate', '<style'))
    assert prop.provenance['sanitizer_actions']
    image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_path=str(prop.path), width=150)))
    assert image.getchannel('A').getbbox()


@pytest.mark.parametrize('bad', [
    '<svg nope',
    '<!DOCTYPE svg [<!ENTITY a "x"><!ENTITY b "&a;&a;"><!ENTITY c "&b;&b;">]><svg>&c;</svg>',
    GOOD.replace('#E53935', '#123456'),
    GOOD.replace('<rect', '<g transform="scale(.2)"><rect', 1).replace('</svg>', '</g></svg>'),
    GOOD.replace('stroke-width="6"', 'stroke-width="1"'),
    GOOD.replace('stroke-linecap="round"', 'stroke-linecap="square"'),
    GOOD.replace('stroke="#1B1B1B"', 'stroke="none"'),
    GOOD.replace('viewBox="0 0 512 512"', 'viewBox="0 0 100 100"'),
    GOOD.replace('</svg>', '<circle/>' * 41 + '</svg>'),
    GOOD.replace('</svg>', '<g>' * 20 + '</g>' * 20 + '</svg>'),
    GOOD + ' ' * 100_000,
    GOOD.replace('d="M100 300 H400"', 'd="not a path"'),
], ids=['xml', 'entities', 'palette', 'bbox', 'width', 'cap', 'no-strokes', 'viewbox', 'shapes', 'depth', 'bytes', 'geometry'])
def test_invalid_repairs_once_then_falls_back(bad):
    prompts = []
    def llm(prompt):
        prompts.append(prompt)
        return bad
    assert api().request_prop('paw', PALETTE, 'flat', llm) is None
    assert len(prompts) == 2 and 'Failure:' in prompts[1]


def test_repair_success_records_failure(tmp_path):
    outputs = iter(['<svg broken', GOOD])
    prop = api().request_prop('paw', PALETTE, 'flat', lambda _: next(outputs), project=tmp_path)
    assert prop.provenance['repairs'] == 1
    assert prop.provenance['failures'] and len(prop.provenance['prompt_hashes']) == 2


@pytest.mark.parametrize('change', ['svg', 'metadata', 'palette', 'style'])
def test_cache_revalidated_for_content_and_context(tmp_path, change):
    calls = []
    def llm(prompt):
        calls.append(prompt)
        return GOOD
    prop = api().request_prop('paw', PALETTE, 'flat', llm, project=tmp_path)
    palette, style = PALETTE, 'flat'
    if change == 'svg':
        prop.path.write_text(HOSTILE, encoding='utf-8')
    elif change == 'metadata':
        prop.path.with_suffix('.json').write_text('{}', encoding='utf-8')
    elif change == 'palette':
        palette = ['#E53935', '#1E6FD9']
    else:
        style = 'flat cartoon'
    assert api().request_prop('paw', palette, style, llm, project=tmp_path)
    assert len(calls) == 2


@pytest.mark.parametrize('scores,enabled,expected', [([], False, False), ([], True, True),
    ([.2], True, True), ([.5], True, False), ([.8, .1], True, False), ([.1, .8], True, False)])
def test_director_hook_default_off_and_threshold(tmp_path, scores, enabled, expected):
    from types import SimpleNamespace
    calls = []
    def llm(prompt):
        calls.append(prompt)
        return GOOD
    kwargs = {'enabled': True} if enabled else {}
    prop = api().maybe_request_prop([SimpleNamespace(score=s) for s in scores],
        'paw', PALETTE, 'flat', llm, project=tmp_path, threshold=.5, **kwargs)
    assert bool(prop) == expected and bool(calls) == expected


def test_model_failure_is_bounded():
    calls = []
    def llm(prompt):
        calls.append(prompt)
        raise RuntimeError('offline')
    assert api().request_prop('paw', PALETTE, 'flat', llm) is None
    assert len(calls) == 2

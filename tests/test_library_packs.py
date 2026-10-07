"""Imported open picture packs (library/packs.py): only licence-clean pictures reach the library, they draw as
ink lines, and they never push a coloured doodle down the search results."""
import json

import numpy as np
import pytest

from kinodraw import library
from kinodraw.director.match import Matcher
from kinodraw.engine import ink
from kinodraw.library.packs import ALLOWED, MANIFEST, LicenceError, allowed_ids, licence_of, write_pack

MIT = (library.ASSETS / 'tabler' / 'LICENSE').read_text(encoding='utf-8')
BY_SA = ('Attribution-ShareAlike 4.0 International\n\nCreative Commons Corporation ("Creative Commons") is not a law '
         'firm.\nhttps://creativecommons.org/licenses/by-sa/4.0/\n')
STAR = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 17.75l-6.172 3.245l1.179 -6.873l-5 -4.867l6.9 -1l3.086 -6.253l3.086 6.253l6.9 1l-5 4.867'
        'l1.179 6.873z"/></svg>')


def tabler_source(folder, licence):
    """A one-icon pack laid out as the @tabler/icons npm package."""
    (folder / 'icons' / 'outline').mkdir(parents=True)
    (folder / 'LICENSE').write_text(licence, encoding='utf-8')
    (folder / 'package.json').write_text(json.dumps({'version': '9.9.9'}), encoding='utf-8')
    (folder / 'icons.json').write_text(json.dumps(
        {'star': {'category': 'Shapes', 'tags': ['favourite'], 'styles': {'outline': {}}}}), encoding='utf-8')
    (folder / 'icons' / 'outline' / 'star.svg').write_text(STAR, encoding='utf-8')
    return folder


def test_licence_wording_is_read_restrictive_terms_first():
    assert licence_of(MIT) == 'MIT'
    assert licence_of(BY_SA) not in ALLOWED
    assert licence_of(BY_SA + '\nSee also Attribution 4.0 International.') not in ALLOWED
    assert licence_of('Attribution-NonCommercial 4.0 International') not in ALLOWED
    assert licence_of('Copyright 2024 Someone. All rights reserved.') is None


def test_a_share_alike_pack_is_refused_before_anything_is_written(tmp_path):
    src = tabler_source(tmp_path / 'src', BY_SA)
    root = tmp_path / 'library'
    with pytest.raises(LicenceError, match='CC-BY-SA'):
        write_pack('tabler', src, root=root)
    assert not root.exists()


def test_an_mit_pack_is_written_with_its_licence_on_every_picture(tmp_path):
    src = tabler_source(tmp_path / 'src', MIT)
    root = tmp_path / 'library'
    assert write_pack('tabler', src, root=root)['imported'] == 1
    manifest = json.loads((root / 'tabler' / MANIFEST).read_text(encoding='utf-8'))
    assert manifest['licence'] == 'MIT' and manifest['files'] == {'tb_star': ['icons/outline/star.svg', 'MIT']}
    svg = (root / 'tabler' / 'tb_star.svg').read_text(encoding='utf-8')
    assert 'currentColor' not in svg and 'stroke="#1B1B1B"' in svg and 'viewBox="0 0 320 320"' in svg
    assert (root / 'tabler' / 'LICENSE').read_text(encoding='utf-8') == MIT
    assert json.loads((root / 'tags' / 'tabler.json').read_text(encoding='utf-8'))['tb_star']['en'][:2] == \
        ['star', 'favourite']


def test_the_library_lists_only_pictures_with_an_allowed_licence(tmp_path, monkeypatch):
    assets = tmp_path / 'doodles'
    (assets / 'tags').mkdir(parents=True)
    (assets / 'tabler').mkdir()
    (assets / 'banned.json').write_text(json.dumps({'doodles': [], 'words': {'en': []}}), encoding='utf-8')
    tags = {}
    for did in ('tb_open', 'tb_share_alike', 'tb_unlisted'):
        (assets / 'tabler' / f'{did}.svg').write_text(STAR, encoding='utf-8')
        tags[did] = {'desc': did, 'category': 'Shapes', 'en': [did], 'zh': []}
    (assets / 'tags' / 'tabler.json').write_text(json.dumps(tags), encoding='utf-8')
    (assets / 'tabler' / MANIFEST).write_text(json.dumps({'files': {
        'tb_open': ['icons/outline/open.svg', 'MIT'],
        'tb_share_alike': ['icons/outline/share-alike.svg', 'CC-BY-SA-4.0']}}), encoding='utf-8')
    monkeypatch.setattr(library, 'ASSETS', assets)
    library.catalog.cache_clear()
    library.banned.cache_clear()
    try:
        assert {did: e['set'] for did, e in library.catalog().items()} == {'tb_open': 'tabler'}
    finally:
        library.catalog.cache_clear()
        library.banned.cache_clear()


def test_allowed_ids_drop_rows_without_an_allowed_licence():
    assert allowed_ids({'files': {'a': ['a.svg', 'MIT'], 'b': ['b.svg', 'CC-BY-SA-4.0'], 'c': ['c.svg', None],
                                  'd': 'MIT', 'e': ['e.svg', 'CC-BY-NC-4.0'], 'f': ['f.svg', 'CC0-1.0']}}) == {'a', 'f'}


def test_the_catalog_holds_at_least_5000_licence_clean_pictures():
    cat = library.catalog()
    assert len(cat) >= 5000
    for pack in library.PACKS:
        manifest = json.loads((library.ASSETS / pack / MANIFEST).read_text(encoding='utf-8'))
        listed = {did for did, e in cat.items() if e['set'] == pack}
        on_disk = {p.stem for p in (library.ASSETS / pack).glob('*.svg')}
        assert listed == allowed_ids(manifest) == on_disk == set(manifest['files']), pack
        assert manifest['licence'] in ALLOWED
        assert licence_of((library.ASSETS / pack / 'LICENSE').read_text(encoding='utf-8')) == manifest['licence']


@pytest.mark.parametrize('pack', ['tabler', 'healthicons'])
def test_pack_pictures_draw_with_a_visible_ink_line(pack):
    did = next(i for i, e in sorted(library.catalog().items()) if e['set'] == pack)
    color, line, polylines, _ = ink._svg_layers(str(library.resolve(did)), 240, 240)
    drawn = np.asarray(color.getchannel('A')) > 128
    lined = np.asarray(line.getchannel('A')) > 128
    assert drawn.mean() > .02 and polylines
    assert lined.sum() > .6 * drawn.sum()           # the line layer is the picture itself, not an empty sheet


def test_coloured_doodles_stay_first_and_the_offline_director_ignores_packs():
    studio = Matcher('en', exclude_categories=())
    for query in ('lion', 'river', 'teacher', 'rocket', 'heart'):
        first = studio.lexical(query)[0].id
        assert not library.imported(studio.entries[first]), (query, first)
    assert any(library.imported(studio.entries[h.id]) for h in studio.lexical('barcode'))
    from kinodraw.director.rules import RulesDirector
    assert not any(library.imported(e) for e in RulesDirector('en').matcher.entries.values())
    assert not any(library.imported(e) for e in Matcher('zh').entries.values())

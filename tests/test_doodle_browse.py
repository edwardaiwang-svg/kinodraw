"""The picture picker: browse a whole set, forgive English typos, keep ★ favourites and recent pictures."""
import json
import urllib.error
import urllib.request

import pytest

from kinodraw import starters
from kinodraw.director import match
from kinodraw.library import catalog
from kinodraw.studio import server
from studio_browser import make_project, studio_page  # noqa: F401 - the fixture

repo, files = match.EMBED_FILES['en']
MODEL = match.CACHE / f"{repo.split('/')[1]}-{repo.split('/')[3][:8]}"
needs_model = pytest.mark.skipif(not all((MODEL / name).is_file() for name in files),
                                 reason='doodle-search model is not installed')
BULBS = {'lightbulb_idea', 'fl_light_bulb', 'tb_bulb'}


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """The real local server with its own settings file."""
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    server._save_config({'projects': str(tmp_path / 'videos')})
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None):
        req = urllib.request.Request(url + path.lstrip('/'), data=None if body is None else json.dumps(body).encode(),
                                     headers={'X-Studio-Token': server.Handler.token, 'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=60) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as reply:
            return reply.code, json.loads(reply.read())
    yield call
    httpd.shutdown(); httpd.server_close()


def ids(result, n=None):
    return [item['id'] for item in result['items'][:n]]


def test_an_empty_search_browses_a_whole_set_page_by_page(studio):
    status, page = studio('/api/doodles?q=&lang=en&pack=tabler')
    assert status == 200 and page['total'] >= 3000 and len(page['items']) == 32
    assert {item['set'] for item in page['items']} == {'tabler'}
    _, more = studio('/api/doodles?q=&lang=en&pack=tabler&offset=32')
    assert len(more['items']) == 32 and not set(ids(page)) & set(ids(more))
    counts = {p['id']: p['count'] for p in page['packs']}
    library = catalog()
    assert counts == {s: sum(e['set'] == s for e in library.values()) for s in {e['set'] for e in library.values()}}
    assert [p['name'] for p in page['packs']][:4] == ['Doodles', 'Fluent Emoji', 'Tabler Icons', 'Health Icons']
    assert studio('/api/doodles?q=&lang=en&pack=nonsense')[0] == 400


def test_a_chinese_project_can_browse_the_icons_it_cannot_search():
    """Imported icons have no Chinese words, so Chinese search skips them; browsing by hand still reaches them."""
    page = server.browse_doodles('', 'zh', 'tabler')
    assert page['total'] >= 3000


@needs_model
@pytest.mark.parametrize('query', ['lightbulb', 'ligthbulb'])
def test_a_typing_slip_still_finds_the_light_bulb(query):
    assert BULBS & set(ids(server.browse_doodles(query, 'en'), 5))


@needs_model
@pytest.mark.parametrize('query, wanted', [('elefant', 'fl_elephant'), ('rocekt', 'fl_rocket'), ('umbrela', 'fl_umbrella'),
                                           ('bycicle', 'fl_bicycle')])
def test_two_slips_are_forgiven_in_a_long_word(query, wanted):
    assert wanted in ids(server.browse_doodles(query, 'en'), 5)


def old_ranking(query, lang):
    """The Studio search before the picker could browse (da801cb search_doodles): word hits, then meaning."""
    m = server._matcher(lang)
    ranked = m.lexical(query)
    seen = {h.id for h in ranked}
    ranked += [h for h in m.semantic(query, 32) if h.id not in seen]
    return [h.id for h in ranked[:32]]


@needs_model
@pytest.mark.parametrize('query, lang', [('灯泡', 'zh'), ('shared', 'en'), ('happily', 'en'), ('lightbulb', 'en')])
def test_known_words_and_chinese_search_keep_their_results(query, lang):
    """Real English words are never 'corrected' (shared is not scared), and Chinese search is unchanged."""
    before = old_ranking(query, lang)
    assert ids(server.browse_doodles(query, lang))[:len(before)] == before


def test_favourites_and_recent_pictures_are_kept_in_the_studio_settings(studio):
    status, saved = studio('/api/settings', {'favourite': 'fl_elephant', 'on': True})
    assert status == 200 and saved['pictures'] == {'favourites': ['fl_elephant'], 'recent': []}
    for did in ['fl_rocket', 'fl_umbrella', 'fl_rocket']:
        studio('/api/settings', {'recent': did})
    assert json.loads(server.CONFIG.read_text())['pictures'] == {'favourites': ['fl_elephant'], 'recent': ['fl_rocket', 'fl_umbrella']}
    _, page = studio('/api/doodles?q=&lang=en&pack=favourites')
    assert ids(page) == ['fl_elephant'] and page['mine']['recent'] == ['fl_rocket', 'fl_umbrella']
    assert ids(studio('/api/doodles?q=&lang=en&pack=recent')[1]) == ['fl_rocket', 'fl_umbrella']
    assert studio('/api/settings', {'favourite': 'fl_elephant', 'on': False})[1]['pictures']['favourites'] == []
    assert studio('/api/settings', {'favourite': 'not_a_picture', 'on': True})[0] == 400
    assert studio('/api/settings', {'recent': 'own:mine.png'})[0] == 400       # a project's own picture is not kept


def test_recent_keeps_the_last_24(studio):
    library = sorted(catalog())[:30]
    for did in library:
        studio('/api/settings', {'recent': did})
    assert studio('/api/doodles?q=&lang=en&pack=recent')[1]['mine']['recent'] == library[::-1][:24]


@needs_model
def test_the_picker_browses_sets_and_keeps_favourites_and_recent_in_a_real_browser(studio_page):
    """Chips for every set, More, a typo search, ★ kept after reopening (and after a reload), a pick in Recent."""
    make_project(starters.read('explainer-en'), 'en')
    assert '"passed":true' in studio_page('picker')

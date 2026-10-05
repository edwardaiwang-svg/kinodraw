"""Picture moves change content order while narration timing stays at each drawing position."""
from copy import deepcopy
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

import pytest

from kinodraw import director, net, pipeline
from kinodraw.director.llm import providers
from kinodraw.director.validate import validate
from kinodraw.engine import render, timeline
from kinodraw.studio import server

FIXTURES = Path(__file__).parent / 'fixtures'


def _beat(board, beat_id):
    return next(b for b in board['beats'] if b['id'] == beat_id)


def _english_board(project):
    board = pipeline.new_project(FIXTURES / 'tiny.md', project)
    beat = next(b for b in board['beats'] if 'Archaeologists' in b['spoken']['en'])
    beat['visuals'] = [
        {'id': 'order-first', 'type': 'cluster', 'trigger': {'en': 'pots'},
         'items': [{'doodle': 'narrator_explain', 'trigger': {'en': 'pots'}}]},
        {'id': 'order-second', 'type': 'cluster', 'trigger': {'en': 'safe'},
         'items': [{'doodle': 'narrator_wave', 'trigger': {'en': 'safe'}}]},
    ]
    assert validate(board, project)['ok']
    return board, beat['id']


def _production(board, project):
    lang = board['lang']
    timing = timeline.layout(board, lang, timeline.synthetic_clips(board, lang))
    return render.make_production(board, timing, lang, project)


def _first_starts(production):
    starts = {}
    for element in production.ctx.elements:
        if element.start is not None and not element.skipped:
            starts[element.group] = min(starts.get(element.group, float('inf')), element.start)
    return starts


def _item_start(production, visual_id, index):
    return min(e.start for e in production.ctx.registry[visual_id][index]
               if e.start is not None and not e.skipped)


def _assert_visual_timing_moves(board, beat_id, project):
    original = deepcopy(board)
    first, second = _beat(board, beat_id)['visuals'][:2]
    before = _first_starts(_production(board, project))
    assert before[first['id']] < before[second['id']]
    moved = server.move_picture(board, beat_id, 1, 0)
    after = _first_starts(_production(moved, project))
    assert [v['id'] for v in _beat(moved, beat_id)['visuals'][:2]] == [second['id'], first['id']]
    assert after[second['id']] == pytest.approx(before[first['id']], abs=.05)
    assert after[second['id']] < after[first['id']]
    assert board == original                         # callers can keep an undo snapshot


@pytest.mark.parametrize('fixture', ['sleep_zh.md', 'tiny.md'])
def test_moving_a_picture_up_swaps_when_the_two_are_drawn(tmp_path, monkeypatch, fixture):
    """Use the real rules director, cached models, and drawing scheduler; no audio or frame rendering."""
    if fixture == 'tiny.md':
        project = tmp_path / 'Honey'
        board, beat_id = _english_board(project)
        _assert_visual_timing_moves(board, beat_id, project)
        return
    def cached_only(files, progress=None):
        missing = [str(path) for _, path, _, _ in files if not path.is_file()]
        assert not missing, f'Draw-order test needs locally cached search models: {missing}'
    monkeypatch.setattr(net, 'download', cached_only)
    import jieba
    monkeypatch.setattr(jieba.dt, 'tmp_dir', str(tmp_path))
    project = tmp_path / 'Sleep'
    pipeline.new_project(FIXTURES / fixture, project)
    director.direct(project, 'rules')
    board = pipeline.storyboard(project)
    before = _first_starts(_production(board, project))
    # Find a real pair instead of depending on a particular rule-picked doodle or beat id.
    candidates = [b for b in board['beats'] if len(b['visuals']) >= 2
                  and all(v['type'] == 'cluster' and v.get('trigger') for v in b['visuals'][:2])
                  and b['visuals'][0]['trigger'] != b['visuals'][1]['trigger']
                  and all(v['id'] in before for v in b['visuals'][:2])
                  and before[b['visuals'][0]['id']] < before[b['visuals'][1]['id']]]
    assert candidates, 'The Chinese rules board should offer two differently timed cluster pictures'
    _assert_visual_timing_moves(board, candidates[0]['id'], project)


def test_moving_a_doodle_inside_a_group_swaps_when_they_are_drawn(tmp_path):
    project = tmp_path / 'Honey'
    board, beat_id = _english_board(project)
    beat = _beat(board, beat_id)
    first, second = beat['visuals']
    first['items'].extend(second['items'])
    beat['visuals'] = [first]
    before = _production(board, project)
    early = _item_start(before, first['id'], 0)
    late = _item_start(before, first['id'], 1)
    assert early < late
    moved = server.move_picture(board, beat_id, 0, 0, item=1)
    after = _production(moved, project)
    items = _beat(moved, beat_id)['visuals'][0]['items']
    assert [it['doodle'] for it in items] == ['narrator_wave', 'narrator_explain']
    assert _item_start(after, first['id'], 0) == pytest.approx(early, abs=.05)
    assert _item_start(after, first['id'], 1) == pytest.approx(late, abs=.05)


def test_an_untouched_board_is_not_changed(tmp_path):
    board, beat_id = _english_board(tmp_path / 'Honey')
    original = deepcopy(board)
    moved = server.move_picture(board, beat_id, 1, 0)
    assert server.move_picture(moved, beat_id, 0, 1) == original
    assert board == original
    beat = _beat(board, beat_id)
    beat['visuals'][0]['items'].extend(beat['visuals'].pop(1)['items'])
    original = deepcopy(board)
    moved = server.move_picture(board, beat_id, 0, 0, item=1)
    assert server.move_picture(moved, beat_id, 0, 1, item=0) == original


def test_nonadjacent_move_keeps_missing_triggers_at_the_right_place(tmp_path):
    board, beat_id = _english_board(tmp_path / 'Honey')
    beat = _beat(board, beat_id)
    beat['visuals'] = [
        {'id': 'a', 'type': 'cluster', 'trigger': {'en': 'pots'},
         'items': [{'doodle': 'narrator_explain', 'trigger': {'en': 'pots'}},
                   {'doodle': 'narrator_wave', 'trigger': {'en': 'safe'}}]},
        _note('note', 'safe'),
        {'id': 'c', 'type': 'cluster', 'items': [{'doodle': 'narrator_wave'}]},
    ]
    original = deepcopy(board)
    moved = server.move_picture(board, beat_id, 0, 2)
    note, cluster, last = _beat(moved, beat_id)['visuals']
    assert [v['id'] for v in (note, cluster, last)] == ['note', 'c', 'a']
    assert note['trigger'] == {'en': 'pots'}
    assert cluster['trigger'] == {'en': 'safe'}
    assert cluster['items'][0]['trigger'] == {'en': 'pots'}   # taken on the way past, as two clicks would
    assert 'trigger' not in last
    assert 'trigger' not in last['items'][0]          # the last place's doodle had no words of its own
    assert last['items'][1]['trigger'] == {'en': 'safe'}   # nothing there to take: keeps its own words
    assert [b for b in moved['beats'] if b['id'] != beat_id] == [
        b for b in original['beats'] if b['id'] != beat_id]
    assert board == original
    note['term']['en'] = 'Moved copy'
    assert board == original                         # nested objects are copied too


def test_a_larger_cluster_uses_destination_item_times_then_keeps_its_own(tmp_path):
    board, beat_id = _english_board(tmp_path / 'Honey')
    first, second = _beat(board, beat_id)['visuals']
    second['items'].append({'doodle': 'narrator_explain', 'trigger': {'en': 'old'}})
    moved = server.move_picture(board, beat_id, 1, 0)
    items = _beat(moved, beat_id)['visuals'][0]['items']
    assert items[0]['trigger'] == first['items'][0]['trigger']
    assert items[1]['trigger'] == {'en': 'old'}       # no destination doodle: it stays on its own words
    assert _beat(moved, beat_id)['visuals'][0]['trigger'] == first['trigger']


def _note(vid, word):
    return {'id': vid, 'type': 'glossary', 'trigger': {'en': word},
            'term': {'en': 'Honey'}, 'text': {'en': 'A sweet food that bees make.'}}


def _mixed_board(tmp_path):
    """Pictures like a rules board's: a group drawn word by word, a note, then a one-doodle group."""
    board, beat_id = _english_board(tmp_path / 'Honey')
    _beat(board, beat_id)['visuals'] = [
        {'id': 'group', 'type': 'cluster', 'trigger': {'en': 'pots', 'es': 'ollas'},
         'items': [{'doodle': 'narrator_explain', 'trigger': {'en': 'pots', 'es': 'ollas'}},
                   {'doodle': 'narrator_wave', 'trigger': {'en': 'honey', 'es': 'miel'}},
                   {'doodle': 'narrator_explain', 'trigger': {'en': 'years', 'es': 'años'}}]},
        _note('note', 'safe'),
        {'id': 'one', 'type': 'cluster', 'trigger': {'en': 'eat'},
         'items': [{'doodle': 'narrator_wave', 'trigger': {'en': 'eat'}}]},
    ]
    return board, beat_id


@pytest.mark.parametrize('visual', [0, 1])
def test_moving_a_picture_and_back_restores_groups_of_any_size(tmp_path, visual):
    """Draw later then Draw earlier is an undo, even between a group of three, a note and a group of one."""
    board, beat_id = _mixed_board(tmp_path)
    original = deepcopy(board)
    moved = server.move_picture(board, beat_id, visual, visual + 1)
    assert server.move_picture(moved, beat_id, visual + 1, visual) == original
    assert all(it.get('trigger') for v in _beat(moved, beat_id)['visuals'] for it in v.get('items', []))


def test_a_note_moved_before_a_group_leaves_each_doodle_on_its_own_word(tmp_path):
    project = tmp_path / 'Honey'
    board, beat_id = _mixed_board(tmp_path)
    moved = server.move_picture(board, beat_id, 1, 0)
    assert validate(moved, project)['ok']
    production = _production(moved, project)
    note = _first_starts(production)['note']
    doodles = [_item_start(production, 'group', i) for i in range(3)]
    assert note < doodles[0] < doodles[1] < doodles[2]

    def words(prod):                                 # when each doodle of the group may start
        return [e.trigger for e in prod.ctx.elements if e.group == 'group' and e.hand]
    assert words(production) == words(_production(board, project))
    assert len(set(words(production))) == 3


@pytest.mark.parametrize('visual, to', [(1, 0), (0, 1), (2, 1), (0, 2)])
def test_a_page_keeps_its_place(tmp_path, visual, to):
    """A page (flow, chart, timeline) has its own timed parts and its own camera stop: it is not moved."""
    board, beat_id = _english_board(tmp_path / 'Honey')
    _beat(board, beat_id)['visuals'].insert(1, {
        'id': 'page', 'type': 'flow', 'trigger': {'en': 'safe'},
        'nodes': [{'text': {'en': 'Honey'}, 'trigger': {'en': 'honey'}}]})
    original = deepcopy(board)
    with pytest.raises(ValueError, match='keeps its place'):
        server.move_picture(board, beat_id, visual, to)
    assert board == original


@pytest.mark.parametrize('arguments', [
    {'visual': -1, 'to': 0}, {'visual': 2, 'to': 0}, {'visual': 0, 'to': 2},
    {'visual': True, 'to': 0}, {'visual': 0, 'to': '1'},
    {'visual': 0, 'to': 0, 'item': -1}, {'visual': 0, 'to': 1, 'item': 0},
    {'visual': 0, 'to': 0, 'item': True},
])
def test_bad_picture_positions_raise_a_plain_value_error(tmp_path, arguments):
    board, beat_id = _english_board(tmp_path / 'Honey')
    original = deepcopy(board)
    with pytest.raises(ValueError) as error:
        server.move_picture(board, beat_id, **arguments)
    assert str(error.value) and not re.search(r'Traceback|IndexError|KeyError', str(error.value))
    assert board == original


def test_a_missing_beat_is_a_plain_error(tmp_path):
    board, _ = _english_board(tmp_path / 'Honey')
    with pytest.raises(ValueError) as error:
        server.move_picture(board, 'no-longer-here', 0, 0)
    assert str(error.value) and 'Traceback' not in str(error.value)


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """Use the live local HTTP handler with an isolated config and projects folder."""
    monkeypatch.setattr(server, 'CONFIG', tmp_path / 'studio.json')
    root = tmp_path / 'videos'
    server._save_config({'projects': str(root)})
    monkeypatch.setattr(providers, 'saved', lambda: set())
    board, beat_id = _english_board(root / 'Honey')
    pipeline._save(root / 'Honey' / 'storyboard.json', board)
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url + path.lstrip('/'), data=data,
                                         headers={'X-Studio-Token': server.Handler.token})
        try:
            with opener.open(request, timeout=30) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
    call.project = root / 'Honey'
    call.beat = beat_id
    yield call
    httpd.shutdown()
    httpd.server_close()


def test_the_studio_saves_a_new_order_that_passes_the_check(studio):
    board = pipeline.storyboard(studio.project)
    _beat(board, studio.beat)['visuals'][1]['items'][0]['label'] = {'en': 'My edited picture'}
    board['brand'] = {'name': 'My unsaved title', 'custom': 'Preserve client metadata'}
    expected = server.move_picture(board, studio.beat, 1, 0)
    report = validate(expected, studio.project)
    assert report['ok'] and report['warnings']
    status, reply = studio('/api/projects/Honey/reorder',
                           {'storyboard': board, 'beat': studio.beat, 'visual': 1, 'to': 0})
    assert status == 200 and reply['ok']
    assert reply['storyboard'] == expected
    assert reply['warnings'] == report['warnings']
    saved = pipeline.storyboard(studio.project)
    assert saved == expected
    assert validate(saved, studio.project)['ok']


def test_reorder_post_falls_back_to_the_saved_storyboard(studio):
    before = pipeline.storyboard(studio.project)
    expected = server.move_picture(before, studio.beat, 1, 0)
    status, reply = studio('/api/projects/Honey/reorder', {'beat': studio.beat, 'visual': 1, 'to': 0})
    assert status == 200 and reply['ok'] and reply['storyboard'] == expected
    assert pipeline.storyboard(studio.project) == expected


def test_reorder_post_can_move_items_inside_a_cluster(studio):
    board = pipeline.storyboard(studio.project)
    beat = _beat(board, studio.beat)
    beat['visuals'][0]['items'].extend(beat['visuals'].pop(1)['items'])
    expected = server.move_picture(board, studio.beat, 0, 0, item=1)
    status, reply = studio('/api/projects/Honey/reorder',
                           {'storyboard': board, 'beat': studio.beat, 'visual': 0, 'item': 1, 'to': 0})
    assert status == 200 and reply['ok'] and reply['storyboard'] == expected
    assert pipeline.storyboard(studio.project) == expected


@pytest.mark.parametrize('invalid', ['position', 'trigger'])
def test_a_rejected_reorder_does_not_write_the_storyboard(studio, invalid):
    path = studio.project / 'storyboard.json'
    before = path.read_bytes()
    board = pipeline.storyboard(studio.project)
    body = {'storyboard': board, 'beat': studio.beat, 'visual': 1, 'to': 0}
    if invalid == 'position':
        body['to'] = 999
    else:
        _beat(board, studio.beat)['visuals'][0]['trigger'] = {'en': 'words not narrated'}
    status, reply = studio('/api/projects/Honey/reorder', body)
    assert status == 400 and reply['ok'] is False and reply['errors']
    assert not re.search(r'Traceback|IndexError|KeyError', ' '.join(reply['errors']))
    assert path.read_bytes() == before


def _run_reorder_js(script):
    """Run the Studio's reorderPicture with a held-back server reply, in node with tiny stand-ins for the page."""
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    source = re.search(r'^async function reorderPicture\(.*?^}', js, re.S | re.M)[0]
    stage = '''
const els = {};
const $ = (sel) => (els[sel] = els[sel] || { textContent: '', disabled: false, inert: false, querySelectorAll: () => [] });
let rendered = 0, release;
const toast = () => {}, renderBoard = () => { rendered++; }, showBeatPreview = () => {}, loadNarrator = () => {};
const document = { querySelector: () => null };
const api = () => new Promise((resolve) => { release = resolve; });
let current = 'A', board = { project: 'A' }, dirty = false;
const T = 't';
'''
    out = subprocess.run([node, '-e', stage + source + script], capture_output=True, text=True, check=True, encoding='utf-8').stdout
    return json.loads(out)


def test_a_late_move_reply_does_not_land_in_another_project():
    result = _run_reorder_js('''
(async () => {
  const pending = reorderPicture('b1', 1, 0);
  current = 'B'; board = { project: 'B' }; dirty = true;      // the user opened project B and edited it
  release({ ok: true, storyboard: { project: 'A', moved: true } });
  await pending;
  console.log(JSON.stringify({ board, dirty, rendered }));
})();''')
    assert result == {'board': {'project': 'B'}, 'dirty': True, 'rendered': 0}


def test_the_board_cannot_be_edited_while_a_move_is_saving():
    result = _run_reorder_js('''
(async () => {
  const pending = reorderPicture('b1', 1, 0);
  const during = $('#main').inert;
  release({ ok: true, storyboard: { project: 'A', moved: true } });
  await pending;
  console.log(JSON.stringify({ during, after: $('#main').inert, board, dirty }));
})();''')
    assert result == {'during': True, 'after': False, 'board': {'project': 'A', 'moved': True}, 'dirty': False}


def test_the_studio_offers_moves_only_for_pictures_the_server_moves():
    from kinodraw.engine import scenes
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    listed = re.search(r"^const SLOT_TYPES = \[(.*?)\];", js, re.M)[1]
    assert sorted(re.findall(r"'(\w+)'", listed)) == sorted(scenes.SLOT_BUILDERS)


def _run_picker_js(script):
    """Run the Studio's pickDoodle and reorderPicture together, with the upload and the move replies held back."""
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    source = ''.join(re.search(rf'^async function {name}\(.*?^}}', js, re.S | re.M)[0] + '\n'
                     for name in ('reorderPicture', 'pickDoodle'))
    stage = '''
const els = {}, toasts = [];
const $ = (sel) => (els[sel] = els[sel] || { textContent: '', disabled: false, inert: false, innerHTML: '',
  classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll: () => [] });
const held = {};
const api = (url) => {
  for (const kind of ['reorder', 'filename']) if (url.includes(kind)) return new Promise((r) => { held[kind] = r; });
  return Promise.resolve([]);
};
const toast = (msg) => toasts.push(msg), renderBoard = () => {}, showBeatPreview = () => {}, loadNarrator = () => {};
const modal = () => $('#modal-body'), closeModal = () => {}, esc = (s) => s, doodleSrc = (id) => id;
const document = { querySelector: () => null };
let current = 'A', dirty = false;
let board = { project: 'A', lang: 'en', beats: [{ id: 'b1', visuals: [{ items: [{ doodle: 'old' }] }] }] };
const T = 't';
function markDirty() { dirty = true; }
const tick = () => new Promise((r) => setTimeout(r, 0));
async function upload() {                       // the user picks a file in Choose a doodle, then closes the picker
  const it = board.beats[0].visuals[0].items[0];
  pickDoodle('q', (id) => { it.doodle = id; markDirty(); renderBoard(); });
  $('#picture-file').onchange({ target: { files: [{ name: 'mine.png', size: 10 }], value: '' } });
  await tick();
}
const shown = () => ({ doodle: board.beats[0].visuals[0].items[0].doodle, dirty, told: toasts.length > 0 });
const moved = () => ({ ok: true, storyboard: { project: 'A', lang: 'en', beats: [{ id: 'b1', visuals: [{ items: [{ doodle: 'old' }] }] }] } });
'''
    out = subprocess.run([node, '-e', stage + source + script], capture_output=True, text=True, check=True, encoding='utf-8').stdout
    return json.loads(out)


def test_an_upload_still_lands_when_no_move_is_saving():
    result = _run_picker_js('''
(async () => {
  await upload();
  held.filename({ id: 'my_upload' }); await tick();
  console.log(JSON.stringify(shown()));
})();''')
    assert result == {'doodle': 'my_upload', 'dirty': True, 'told': False}


@pytest.mark.parametrize('order', ['upload during the move', 'upload after the move'])
def test_an_upload_that_finishes_around_a_move_is_never_lost_silently(order):
    """The picker sits outside #main, so its upload can finish while a move saves or after the move replaced the board."""
    result = _run_picker_js(f'''
(async () => {{
  await upload();
  const pending = reorderPicture('b1', 1, 0); await tick();
  if ({json.dumps(order)} === 'upload during the move') {{ held.filename({{ id: 'my_upload' }}); await tick(); }}
  held.reorder(moved()); await pending;
  if ({json.dumps(order)} === 'upload after the move') {{ held.filename({{ id: 'my_upload' }}); await tick(); }}
  console.log(JSON.stringify({{ ...shown(), toasts }}));
}})();''')
    # The board shown is the saved one (no swap pretending to be saved, no swap into a board no longer shown),
    # and the user is told the picture is waiting in Your pictures.
    assert {k: result[k] for k in ('doodle', 'dirty', 'told')} == {'doodle': 'old', 'dirty': False, 'told': True}
    assert 'Your pictures' in result['toasts'][-1]


def test_a_move_far_away_keeps_every_doodle_word_and_equals_the_same_clicks(tmp_path):
    """The route accepts any target; it moves one place at a time, like clicking the arrows, so no words are lost."""
    project = tmp_path / 'Honey'
    board, beat_id = _mixed_board(tmp_path)
    visuals = _beat(board, beat_id)['visuals']
    visuals[1] = {'id': 'mid', 'type': 'cluster', 'trigger': {'en': 'safe'},
                  'items': [{'doodle': 'narrator_wave', 'trigger': {'en': 'safe'}}]}
    visuals[2]['items'].append({'doodle': 'narrator_explain', 'trigger': {'en': 'eat'}})
    original = deepcopy(board)

    def words(b):
        return sorted(json.dumps(it.get('trigger'), sort_keys=True)
                      for v in _beat(b, beat_id)['visuals'] for it in v.get('items', []))
    moved = server.move_picture(board, beat_id, 0, 2)
    assert words(moved) == words(original)                       # {"en": "honey", "es": "miel"} survives
    assert moved == server.move_picture(server.move_picture(board, beat_id, 0, 1), beat_id, 1, 2)
    assert validate(moved, project)['ok']
    assert server.move_picture(moved, beat_id, 2, 0) == original
    assert board == original

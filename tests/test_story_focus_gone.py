"""A shot never looks at what its words say is not there, and a sentence about someone keeps them in frame.

- The validator's literal repair never cuts to an insert of a thing the line calls gone, missing or absent.
- The storybook: an insert of such a thing holds on whoever reacts to it (or shows the scene's people where it
  was), never the thing alone or an empty page.
- A close-up of someone takes in the thing it is about only when the thing is beside them: one across the page
  never pushes them into a corner of the frame."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from test_story_shots import local, pages, prop, shot, staged, visible  # noqa: E402
from test_v3_literal import _board, _plan, _shot  # noqa: E402


def test_no_insert_cuts_to_a_thing_the_line_says_is_gone():
    board = _board('"Look," she whispered. "The key is gone."\n')

    def edit(plan, bids):
        plan['scenes'][0]['shots'] = [_shot(bids[0], shot='close', focus_ref='fl_key',
                                            props=[{'ref': 'fl_key', 'relation': 'none', 'to': '', 'motion': 'none'}])]
    plan, report = _plan(board, ['fl_key'], edit)
    assert not report['fallback'], report['fallback_reason']
    shots = plan['scenes'][0]['shots']
    assert [s['shot'] for s in shots] == ['close']               # no insert of the missing key
    assert not any('insert' in r for r in report['repairs'])


def test_a_thing_only_talked_about_and_there_still_gets_its_insert():
    board = _board('"Look," she whispered. "The key is still here."\n')

    def edit(plan, bids):
        plan['scenes'][0]['shots'] = [_shot(bids[0], shot='close', focus_ref='fl_key',
                                            props=[{'ref': 'fl_key', 'relation': 'none', 'to': '', 'motion': 'none'}])]
    plan, _ = _plan(board, ['fl_key'], edit)
    assert [s['shot'] for s in plan['scenes'][0]['shots']] == ['close', 'insert']


def test_an_insert_of_a_missing_thing_holds_on_whoever_reacts(tmp_path):
    text = 'Mia opened the drawer and stared. "Mom," she said. "The key is missing."'
    prod = staged(tmp_path, text, [
        shot('b001', 'Mia opened', 'close', [('mia', 'young', 'look', 'yes')], place='kitchen'),
        shot('b001', 'The key is', 'insert', [], place='kitchen', focus='fl_key')])
    book = prod.storybook
    _, story = pages(prod, 'b001')
    t = local(prod, 'b001', 'The key is missing') + .2
    page = next(p for p in story if p.start <= t < p.end)
    assert [f.key for f in page.figures] == ['mia']               # her face, not a key alone on the page
    assert not any(p.lone for p in page.set)
    assert visible(book, page, book.planned._body(page.figures[0])) > .3


def test_an_insert_of_a_missing_thing_with_nothing_before_it_shows_the_scene_s_people(tmp_path):
    text = 'The key is missing.'
    prod = staged(tmp_path, text, [shot('b001', 'The key', 'insert', [], place='kitchen', focus='fl_key')])
    _, (page,) = pages(prod, 'b001')
    assert page.figures and not any(p.lone for p in page.set)


def test_a_close_up_of_someone_asleep_keeps_them_in_the_middle_not_a_thing_across_the_page(tmp_path):
    text = ('Mia walked home through the park with her kite. She lay down on the bench. '
            'Soon Mia was asleep before she could count to ten.')
    kite = [prop('fl_kite')]
    prod = staged(tmp_path, text, [
        shot('b001', 'Mia walked', 'wide', [('mia', 'young', 'walk', 'no')], place='park', props=kite, focus='fl_kite'),
        shot('b001', 'She lay', 'medium', [('mia', 'young', 'lie', 'no')], place='park', props=kite),
        shot('b001', 'Soon Mia', 'close', [('mia', 'young', 'sleep', 'no')], place='park', props=kite,
             focus='fl_kite')])
    book = prod.storybook
    _, (*_, close) = pages(prod, 'b001')
    mia = close.figures[0]
    kite_box = book.planned._box(next(p for p in close.set if p.doodle == 'fl_kite'))
    body = book.planned._body(mia)
    assert kite_box[2] < body[0] - .5 * (body[2] - body[0])        # the staging puts the kite across the page
    assert visible(book, close, body) > .9                          # she is whole in her close-up
    w, _ = book.size
    left, _, _ = book._to_screen(body[0], body[1], list(close.view))
    right, _, _ = book._to_screen(body[2], body[3], list(close.view))
    assert .2 * w < (left + right) / 2 < .8 * w                     # in the middle, never a corner

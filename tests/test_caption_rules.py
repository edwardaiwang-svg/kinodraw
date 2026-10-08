"""General caption rules (gauntlet round 5): a rolling caption of at most two lines, a caption band clear of the
figures, a backing strip over busy or mid-toned backgrounds, no second copy of a headline's words, and verse
captions that keep the poem's lines (with a short breath where a line runs on)."""
import json

import numpy as np
from PIL import Image

from kinodraw import ingest, script, speech
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import captions, render, timeline

AD = ('Fresh bread, warm from the oven every Sunday at eight in the morning, sliced thick and wrapped in brown '
      'paper for the walk home. Just four dollars a loaf, while the baskets last. The corner shop on Mill Street, '
      'beside the old clock tower. Come hungry!\n\n'
      'The average family throws away about $1,200 of bread a year.\n\n'
      'Bring a friend next week.')

POEM = """The river does not hurry.
It has never once been late.

It carries leaves it did not ask for,
and sets them down
in places they did not know to want.

Nothing here is lost.
It is only on its way.
"""


def _hybrid(tmp_path, text, scenes):
    """A motion video of ``text`` with each beat's scene changed by ``scenes(scene, beat_ids)``."""
    board = script.build(ingest.read(text), story='explain')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style']['mode'] = 'motion'
    for scene in plan['scenes']:
        scenes(scene, scene['beat_ids'])
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    return render.make_production(board, tl, 'en', tmp_path), board


def _kinetic(scene, beat_ids):
    scene.update(treatment='kinetic_type', composition='center', elements=[], actions=[], atmosphere={
        'kind': 'none', 'density': 0}, text={'kind': 'kinetic', 'ref': beat_ids[0]})


def _narration(prod, board, words):
    beat = next(b for b in board['beats'] if b['kind'] == 'narration' and words in b['display']['en'])
    return next(s for s in prod.spans if beat['id'] in s.spec['beat_ids']), beat


def test_a_long_written_narration_rolls_on_in_pages_of_at_most_two_lines(tmp_path):
    prod, board = _hybrid(tmp_path, AD, _kinetic)
    span, beat = _narration(prod, board, 'Come hungry!')
    long = [e for e in span.motion.elements if e.kind == 'text' and e.preset == 'clauses']
    assert len(long) >= 3                                       # the paragraph is several pages, not one block
    for e in long:
        assert e.text.count('\n') <= 1, e.text                  # each page: at most two lines
    words = ' '.join(' '.join(e.text.split()) for e in long)
    assert words == ' '.join(beat['display']['en'].split())    # every word, in order, once
    for t in np.arange(0, span.end - span.start, .1):
        shown = [e for e in long if e.start <= t and (e.end is None or t < e.end)]
        assert len(shown) <= 1, t                               # one page on screen at a time
    for a, b in zip(long, long[1:]):
        assert a.end == b.start and a.start < b.start           # each page goes as the next is said


def test_a_short_written_line_stays_one_page(tmp_path):
    prod, board = _hybrid(tmp_path, AD, _kinetic)
    span, _ = _narration(prod, board, '$1,200')
    texts = [e for e in span.motion.elements if e.kind == 'text' and e.preset == 'clauses']
    assert len(texts) == 1 and texts[0].end is None


def test_a_headline_that_writes_the_sentence_is_not_captioned_again(tmp_path):
    def counter(scene, beat_ids):
        _kinetic(scene, beat_ids)
        scene['treatment'] = 'motion'
        scene['text'] = {'kind': 'counter', 'ref': beat_ids[0]}
    prod, board = _hybrid(tmp_path, AD, counter)
    beat = next(b for b in board['beats'] if '$1,200' in b['display']['en'])
    span = next(s for s in prod.spans if beat['id'] in s.spec['beat_ids'])
    written = [e for e in span.motion.elements if e.kind == 'text' and e.preset == 'clauses']
    assert written and 'throws away' in ' '.join(e.text for e in written)        # the headline writes it
    info = prod.tl['beats'][beat['id']]
    t = (info['start'] + info['speech_end']) / 2
    assert prod._written(span, t)                               # so the caption leaves it to the headline


def test_verse_captions_keep_the_poems_lines():
    board = script.build(ingest.read(POEM), 'story')
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    lines = [line for c in tl['captions'] for line in c['text'].split('\n')]
    assert lines == [line for line in POEM.split('\n') if line.strip()]
    assert all(c['text'].count('\n') <= 1 for c in tl['captions'])
    for c in tl['captions']:
        assert len(c['words']) == len(captions.word_spans(c['text'], 'en'))     # the highlight keeps its words
    assert captions.balanced_lines('It carries leaves it did not ask for,\nand sets them down', 'en') == [
        'It carries leaves it did not ask for,', 'and sets them down']


def test_a_verse_line_that_runs_on_gets_a_short_breath_and_prose_does_not():
    board = script.build(ingest.read(POEM), 'story')
    beat = next(b for b in board['beats'] if 'carries' in b['display']['en'])
    stops = speech.line_breaths(beat['display']['en'], beat['spoken']['en'], beat['line_starts'])
    said = beat['spoken']['en']
    assert [said[p:p + 10] for p, *_ in stops] == ['and sets t', 'in places ']
    assert all(gap == speech.LINE_BREATH for _, gap, *_ in stops)
    first = next(b for b in board['beats'] if 'hurry' in b['display']['en'])
    assert speech.line_breaths(first['display']['en'], first['spoken']['en'], first['line_starts']) == []
    prose = script.build(ingest.read(AD), 'explain')
    assert not any(b.get('line_starts') for b in prose['beats'])


def test_a_short_prose_sentence_is_one_caption_line():
    cues = captions.cues_for_beat('Come hungry!', 'Come hungry!', 'en', lambda p: p * .06, 1.)
    assert [c[2] for c in cues] == ['Come hungry!']
    assert captions.balanced_lines('Come hungry!', 'en') == ['Come hungry!']


def _story(tmp_path):
    from tests.test_storybook import production
    return production(tmp_path)[0]


def _render(prod, t, caption=True, figures=True, shot=None, saved=None):
    wb = prod.whiteboard
    if not caption:
        wb._caption, keep = (lambda *a, **k: None), wb._caption
    if not figures:
        saved, shot.figures = shot.figures, []
    try:
        return np.asarray(prod.frame(t).convert('RGB'), np.int16)
    finally:
        if not caption:
            wb._caption = keep
        if not figures:
            shot.figures = saved


def test_the_caption_never_covers_a_figure_that_fills_the_bottom_of_the_page(tmp_path):
    prod = _story(tmp_path)
    checked = 0
    for span in (s for s in prod.spans if s.story):
        for shot in span.story:
            if not shot.figures or shot.page:
                continue
            t = span.start + (shot.start + shot.end) / 2
            if not any(c['start'] <= t < c['end'] for c in prod.tl['captions']):
                continue
            for f in shot.figures:
                f.ground = .98                                  # framed so the subject fills the bottom band
            plain = _render(prod, t, caption=False)
            bare = _render(prod, t, caption=False, figures=False, shot=shot)
            full = _render(prod, t)
            body = np.abs(plain - bare).sum(axis=2) > 40
            words = np.abs(full - plain).sum(axis=2) > 40
            if not body[900:].any():
                continue
            assert (body & words).sum() < 50, (span.start, shot.start)
            checked += 1
            if checked >= 3:
                return
    assert checked


def _paper(colour=(246, 244, 238)):
    return Image.new('RGBA', (1920, 1080), colour + (255,))


def test_a_busy_or_mid_toned_background_gets_a_backing_strip_and_plain_paper_does_not(tmp_path):
    rng = np.random.default_rng(3)
    grass = rng.integers(40, 200, (1080, 1920, 3)).astype(np.uint8)
    grass[..., 1] = np.clip(grass[..., 1].astype(int) + 40, 0, 255)
    letters, edge = (24, 30, 40), (246, 244, 238)
    assert captions.needs_backing(grass[900:1040, 200:1700], letters, edge)
    assert not captions.needs_backing(np.full((140, 1500, 3), edge, np.uint8), letters, edge)
    teal = np.full((140, 1500, 3), (28, 110, 130), np.uint8)
    assert captions.needs_backing(teal, (250, 250, 250), (20, 40, 70))
    night = np.full((140, 1500, 3), (20, 24, 50), np.uint8)
    assert captions.needs_backing(night, letters, edge)

    prod = _story(tmp_path)
    c = prod.tl['captions'][0]
    t = (c['start'] + c['end']) / 2
    look = (letters, edge, 4)
    busy = Image.fromarray(grass).convert('RGBA')
    prod.whiteboard._caption(busy, t, look)
    x0, y0, x1, y1 = prod.whiteboard.caption_box
    margin = np.asarray(busy.convert('RGB'))[y0 - 4:y0, x0:x1].astype(int)    # the strip's padding above the words
    assert margin.std() < 20                                    # a calm strip, not grass
    paper = _paper(edge)
    prod.whiteboard._caption(paper, t, look)
    x0, y0, x1, y1 = prod.whiteboard.caption_box
    margin = np.asarray(paper.convert('RGB'))[y0 - 4:y0, x0:x1].astype(int)
    assert (margin == edge).all()                               # plain paper: only the outlined words


def test_the_caption_leaves_the_bottom_band_only_for_someone_in_it():
    size, cap = (1920, 1080), (1200, 170)
    assert captions.caption_spot(size, cap, 1046) == (360, 876)                     # nobody there: bottom centre
    body = (800, 300, 1120, 1060)                                                   # a figure down to the floor
    x, y = captions.caption_spot(size, cap, 1046, ([body], []))
    assert not captions._overlap((x, y, x + cap[0], y + cap[1]), body)
    tall = (860, 20, 1060, 1075)                                                    # a figure filling the height
    narrow, prop = (780, 170), (0, 800, 700, 1060)
    x, y = captions.caption_spot(size, narrow, 1046, ([tall], [prop]))
    box = (x, y, x + narrow[0], y + narrow[1])
    assert not captions._overlap(box, tall) and not captions._overlap(box, prop)   # beside them both

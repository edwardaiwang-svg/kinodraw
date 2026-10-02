"""The collage look renders every promo stage, the same pixels in any process, with sound cues in time order."""
import re
from pathlib import Path

import numpy as np

from doodlestudio import ingest, script
from doodlestudio.engine import render as renderer
from doodlestudio.engine import timeline

FIX = Path(__file__).parent / 'fixtures'
RULES = [('easier way', 'turn', 'brand_reveal', 2), ('^with ', 'brand', 'brand_reveal', 3),
         ('^in the group chat', 'channels', 'share_link', 1), ('sign up', 'social', 'rsvp', 1),
         ('^no ', 'feature', 'feature_chips', 2), ('minimum', 'mechanic', 'threshold', 2),
         ('enough', 'mechanic', 'threshold', 2), ('called off', 'mechanic', 'threshold', 1),
         ('green light', 'mechanic', 'threshold', 2), ('^drinks,', 'use_cases', 'use_case_grid', 2),
         ('better together', 'tagline', 'use_case_grid', 1)]           # '^' = the sentence starts with it


def _promo_board():
    """The promo fixture with simple hand-made annotations (the annotator's own tests cover real ones)."""
    board = script.build(ingest.read(FIX / 'promo_tiny.md'), 'promo')
    board.update({'look': 'collage', 'story': 'promo', 'motion': 'lively', 'brand': {'name': 'Friendr', 'url': 'friendr.nl'}})
    last = board['beats'][-1]['id']
    for beat in board['beats']:
        text, notes = beat['display']['en'], []
        for i, m in enumerate(re.finditer(r'.+?(?:[.!?]+(?=\s|$)|$)', text)):   # friendr.nl's dot is no end
            sent = m.group(0).strip()
            a = text.find(sent, m.start())
            low = sent.lower()
            role, scene, energy = next(((r, s, e) for key, r, s, e in RULES
                                        if (low.startswith(key[1:]) if key[0] == '^' else key in low)),
                                       ('cta', 'brand_endcard', 2) if beat['id'] == last else
                                       ('step', 'step_card', 1) if low.startswith(('create', 'share')) else
                                       ('question', 'chat_pileup', 2) if sent.endswith('?') else ('problem', 'chat_pileup', 1))
            notes.append({'i': i, 'span': [a, a + len(sent)], 'role': role, 'scene': scene, 'energy': energy,
                          'emphasis': ''})
        beat['direction'] = notes
    return board


def test_every_promo_stage_renders_the_same_pixels_twice(tmp_path):
    board = _promo_board()
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    a = renderer.make_production(board, tl, 'en', tmp_path)
    b = renderer.make_production(board, tl, 'en', tmp_path)
    assert [s.kind for s in a.stages] == ['chat', 'brand', 'how', 'threshold', 'uses', 'end']
    for st in a.stages:
        t = (st.start + st.end) / 2
        fa, fb = a.frame(t), b.frame(t)
        assert fa.size == (1920, 1080) and np.array_equal(np.asarray(fa), np.asarray(fb))
    cues = a.cues()
    assert cues == b.cues() and [c['t'] for c in cues] == sorted(c['t'] for c in cues)
    assert {'pop', 'slam', 'tap', 'whoosh', 'paper'} <= {c['kind'] for c in cues}
    assert a.brand['cta'] == 'Try it for free' and sum(c['kind'] == 'confetti' for c in cues) >= 1


def test_the_calm_dial_has_no_showpieces(tmp_path):
    board = _promo_board()
    board['motion'] = 'calm'
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = renderer.make_production(board, tl, 'en', tmp_path)
    assert not any(c['kind'] == 'confetti' for c in prod.cues()) and prod._zoom(2, prod.stages[2].start + 2) == 1


def test_a_software_promo_has_a_page_an_app_window_and_the_drawing_hand(tmp_path):
    from doodlestudio.director.annotate import annotate
    from doodlestudio.engine.collage import promo
    board = script.build(ingest.read(FIX / 'promo_doodle.md'), 'promo')
    board.update({'look': 'collage', 'story': 'promo', 'motion': 'lively',
                  'brand': {'name': 'Doodle Studio', 'url': 'example.org', 'reveal': 'hand'}})
    annotate(board)
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    a = renderer.make_production(board, tl, 'en', tmp_path)
    b = renderer.make_production(board, tl, 'en', tmp_path)
    assert [s.kind for s in a.stages] == ['page', 'brand', 'app', 'uses', 'uses', 'end']
    for st in a.stages:
        t = (st.start + st.end) / 2
        assert np.array_equal(np.asarray(a.frame(t)), np.asarray(b.frame(t)))
    app = next(st for st in a.stages if st.kind == 'app')
    drawing = next(e for e in a.stage_els[a.stages.index(app)] if e.ident == 'app.ink')
    t = drawing.items[0][3] + drawing.items[0][0].duration / 2
    assert drawing.pen(t) is not None and len(drawing.items) >= 2      # the hand is at work, doodle after doodle
    writes = [c for c in a.cues() if c['kind'] == 'write']
    assert any(c['id'].startswith('brand.written') for c in writes) and any(c['id'].startswith('app.ink') for c in writes)
    assert promo.items_in('Captions, chapters and a thumbnail come with it.', 'en') == ['Captions', 'chapters',
                                                                                      'a thumbnail']

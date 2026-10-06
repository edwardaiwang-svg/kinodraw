"""The collage look renders every promo stage, the same pixels in any process, with sound cues in time order."""
import re
from pathlib import Path

import numpy as np

from kinodraw import ingest, script
from kinodraw.engine import render as renderer
from kinodraw.engine import timeline

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


def test_a_collage_video_ends_with_the_made_with_credit_unless_it_is_switched_off(tmp_path):
    """The collage look used to hold its end card through the credit's 2 seconds without drawing the credit."""
    board = _promo_board()
    clips = timeline.synthetic_clips(board, 'en')
    on = renderer.make_production(board, timeline.layout(board, 'en', clips), 'en', tmp_path)
    off = renderer.make_production(board, timeline.layout(board, 'en', clips, credit=False), 'en', tmp_path)
    credit = [e for e in on.els if e.ident == 'credit']
    assert len(credit) == 1 and not any(e.ident == 'credit' for e in off.els)
    window = on.tl['credit']
    assert credit[0].end <= window['start'] and credit[0].until is None       # in when the 2 seconds start, held
    t = window['end'] - .1
    shown = np.asarray(on.frame(t), np.int16)
    on.stage_els[-1].remove(credit[0])
    changed = np.argwhere(np.abs(shown - np.asarray(on.frame(t), np.int16)).sum(2) > 30)
    assert len(changed) > 5000                                                 # drawn on the last frames
    assert changed[:, 0].min() > 880 and abs(changed[:, 1].mean() - 960) < 40  # at the foot, centred


def test_a_software_promo_has_a_page_an_app_window_and_the_drawing_hand(tmp_path):
    from kinodraw.director.annotate import annotate
    from kinodraw.engine.collage import promo
    board = script.build(ingest.read(FIX / 'promo_kinodraw.md'), 'promo')
    board.update({'look': 'collage', 'story': 'promo', 'motion': 'lively',
                  'brand': {'name': 'KinoDraw', 'url': 'example.org', 'reveal': 'hand'}})
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


def test_a_collage_thumbnail_shows_the_paper_puppet_not_the_whiteboard_narrator(tmp_path, monkeypatch):
    """The thumbnail is the video's cover: a collage promo's actor is the puppet, on the collage's cream paper."""
    from PIL import Image
    from kinodraw import package
    from kinodraw.engine import auto_scenes
    from kinodraw.engine.collage import puppet
    board = script.build(ingest.read(FIX / 'promo_tiny.md'), 'promo')

    def share(img, hexes, tol=30):
        a = np.asarray(img.convert('RGB'), np.int16)[:, 760:]          # the actor's side
        hit = np.zeros(a.shape[:2], bool)
        for h in hexes:
            hit |= (np.abs(a - [int(h[i:i + 2], 16) for i in (1, 3, 5)]).max(-1) < tol)
        return hit.mean()
    sunny = [puppet.PRESETS['sunny'][k] for k in ('hat', 'top', 'pants')]
    package.thumbnail(board, 'en', tmp_path / 'whiteboard.png', tmp_path)
    monkeypatch.setattr(auto_scenes, 'narrator', lambda *a: (_ for _ in ()).throw(AssertionError('narrator drawn')))
    package.thumbnail({**board, 'look': 'collage'}, 'en', tmp_path / 'collage.png', tmp_path)
    white, collage = Image.open(tmp_path / 'whiteboard.png'), Image.open(tmp_path / 'collage.png')
    assert collage.size == (1280, 720)
    assert share(collage, sunny) > .04 and share(white, sunny) < .005          # the puppet's hat, coat and trousers
    corner = np.asarray(collage.convert('RGB'))[650:, :300].reshape(-1, 3).mean(0)
    assert corner[0] - corner[2] > 12                                         # cream paper, not the grey board


LINES = ('# Learn anything\n\nStuck on a math problem at eleven at night? Your teacher is asleep and the textbook makes '
         'no sense.\n\nThere\'s a better way. Meet Khan Academy.\n\nPick a topic. Watch a short video. Practice until it '
         'clicks.\n\nMath, science, history and coding. All in one place. Any time you like. Wherever you are.\n\n'
         'Visit khanacademy.org.\n')
SIGN_OFF = ('# Learn anything\n\nStuck on a math problem at eleven at night? Your teacher is asleep and the textbook makes '
            'no sense.\n\nThere\'s a better way. Meet Khan Academy.\n\nPick a topic. Watch a short video. Practice until '
            'it clicks, with hints at every step.\n\nMath, science, history and coding. All in one place.\n\nKhan Academy. '
            'Learn at your own pace. It\'s free for everyone. Visit khanacademy.org.\n')


def _annotated(source, folder, story='promo'):
    from kinodraw import pipeline
    from kinodraw.director.annotate import annotate
    board = pipeline.new_project(source, folder, direction={'look': 'collage', 'story': story})
    annotate(board)
    tl = timeline.layout(board, board['lang'], timeline.synthetic_clips(board, board['lang']))
    return renderer.make_production(board, tl, board['lang'], folder)


def test_lines_said_after_the_use_cases_are_written_one_at_a_time(tmp_path):
    """Every extra line of the use-case stage was typed at the same spot over the lines before it: unreadable."""
    prod = _annotated(LINES, tmp_path / 'p')
    k = next(k for k, st in enumerate(prod.stages) if st.kind == 'uses')
    lines = [e for e in prod.stage_els[k] if e.ident.startswith('line.')]
    assert [e.words for e in lines] == ['All in one place.', 'Any time you like.', 'Wherever you are.']
    for e, nxt in zip(lines, lines[1:]):
        assert e.until is not None and e.until + .25 <= nxt.start + 1e-9        # gone before the next comes in
    assert lines[-1].until is None and prod.crowded() == []


def test_no_sample_video_writes_text_over_text(tmp_path):
    """A two-word name plus a website put the whole sign-off over one spot; Chinese use-case labels, wider than
    their columns, covered each other's words."""
    for k, (source, story) in enumerate([(SIGN_OFF, 'promo'), (FIX / 'sleep_zh.md', 'promo'),
                                         (FIX / 'sleep_zh.md', 'showcase'), (FIX / 'promo_friendr.md', 'promo'),
                                         (FIX / 'promo_tiny.md', 'promo'), (FIX / 'water_cycle.md', 'explain')]):
        assert _annotated(source, tmp_path / str(k), story).crowded() == [], (source, story)


def test_text_written_over_text_fails_the_finish(tmp_path, monkeypatch):
    import json
    from kinodraw import pipeline
    from kinodraw.engine.collage import promo
    prod = _annotated(LINES, tmp_path / 'p')
    k = next(k for k, st in enumerate(prod.stages) if st.kind == 'uses')
    said = prod.stages[k].sentences
    prod.stage_els[k] = promo._handline(prod, said[1], 960, 930) + promo._handline(prod, said[2], 960, 930)
    assert [(a, b) for _, a, b in prod.crowded()] == [('All in one place.', 'Any time you like.')]
    (tmp_path / 'p' / 'build').mkdir()
    (tmp_path / 'p' / 'build' / 'timeline.json').write_text(json.dumps(prod.tl), encoding='utf-8')
    monkeypatch.setattr(pipeline.audio, 'mix', lambda *a: None)
    for name in ('mux', 'publish', 'contact_sheet'):
        monkeypatch.setattr(pipeline, name, lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'encoded_qa', lambda *a, **k: {'ok': True, 'problems': []})
    monkeypatch.setattr(pipeline.renderer, 'make_production', lambda *a: prod)
    from types import SimpleNamespace
    decoded = []
    monkeypatch.setattr(pipeline, 'video_size', lambda video: (1920, 1080))
    monkeypatch.setattr(pipeline.subprocess, 'run', lambda args, **k:
                        decoded.append(args) or SimpleNamespace(returncode=0, stderr=b''))
    # The finish worker owns this QA; in-process drawing stubs belong at its
    # implementation boundary, not at the parent subprocess launcher.
    qa = pipeline._finish(tmp_path / 'p')
    assert '-xerror' in decoded[0] and '0:v:0' in decoded[0] and '0:a:0' in decoded[0]
    t = prod.crowded()[0][0]
    assert not qa['ok'] and qa['problems'] == [f'At {pipeline.clock(t)} "All in one place." and "Any time you like." '
                                               'are written on top of each other.']


def test_the_burst_around_a_long_name_never_crosses_its_letters(tmp_path):
    """The burst lines around the reveal and the end card's name were drawn over it: white strokes through the letters
    of a two-word name like "Khan Academy", there for the whole end card."""
    from PIL import Image, ImageFilter
    prod = _annotated(SIGN_OFF, tmp_path / 'p')

    def draw(els, t):
        canvas = Image.new('RGBA', (1920, 1080), (90, 140, 200, 255))
        for e in els:
            if e.start <= t:
                e.draw(canvas, t)
        return canvas
    for kind in ('brand', 'end'):
        k = next(k for k, st in enumerate(prod.stages) if st.kind == kind)
        els = prod.stage_els[k]
        name = next(e for e in els if e.ident == f'{kind}.name')
        burst = next(e for e in els if e.ident == f'{kind}.burst')
        t = burst.end + .3
        alone = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
        name.draw(alone, t)
        letters = np.asarray(alone.getchannel('A').filter(ImageFilter.MinFilter(7))) > 250    # inside the name
        changed = np.abs(np.asarray(draw(els, t), np.int16) -
                         np.asarray(draw([e for e in els if e is not burst], t), np.int16)).sum(2) > 0
        assert letters.sum() > 20000 and changed.sum() > 500                  # the name is there, so is the burst
        assert not (changed & letters).any(), kind

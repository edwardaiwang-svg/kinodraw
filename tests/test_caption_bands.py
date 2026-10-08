"""Caption rules, round 6: a caption page is a readable phrase (never a lone word left over from its sentence); a
hyphenated word stays whole across rolled pages; the caption band keeps clear of heads (with what they wear) and of
the pictures a scene shows, and where no band is clear the picture moves, not the caption onto a face; a narrated
closing card shows its own words with no caption over it; titles get the same contrast check as captions."""
import json

import numpy as np
from PIL import Image, ImageColor

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import captions, render, timeline
from kinodraw.engine.bold import MotionElement
from kinodraw.engine.captions import wrap


REPORT = """# Harbor Report

The fishing boats came back early on Monday with full nets and tired crews.

A storm moved over the bay by noon, so the market closed before lunch.

The harbor master says the boats will go out again on Thursday morning.
"""


def _pages(text, chars=36):
    words = text.split()
    return [' '.join(words[a:b]) for a, b in captions.roll_pages(text, chars)]


# ------------------------------------------------------------------ rule 1: no lone word on a page or caption
def test_a_rolled_page_never_ends_a_sentence_on_a_lone_word():
    text = ('By the end of it, the volunteers carried 2,700 crates of apples out of the orchard this autumn. '
            'That is a record.')
    pages = _pages(text)
    assert len(pages) > 1
    for page in pages:
        assert len(wrap(page, 36)) <= 2, page
    sentence_one = [p for p in pages if 'record' not in p]
    assert all(len(p.split()) >= captions.MIN_WORDS for p in sentence_one), pages
    assert ' '.join(pages) == text                         # nothing lost or reordered


def test_a_short_sentence_stays_one_page_and_a_short_whole_sentence_is_its_own_page():
    assert _pages('Thank you all for coming.') == ['Thank you all for coming.']
    pages = _pages('The lake froze over on the first of December this year, earlier than ever before. Wow.')
    assert pages[-1] == 'Wow.'                              # a whole sentence, not a fragment


def test_a_spoken_caption_never_leaves_a_word_or_two_of_its_sentence_alone():
    said = ('The new crew covered every street on the north side and the south side of the river town before '
            'lunch on the quarter.')
    cues = captions.cues_for_beat(said, said, 'en', lambda p: p * .06, len(said) * .06)
    assert len(cues) >= 2
    assert all(len(c[2].split()) >= captions.MIN_WORDS for c in cues), [c[2] for c in cues]
    assert ' '.join(' '.join(c[2].split()) for c in cues) == said
    short = 'Doors open at nine.'
    assert [c[2] for c in captions.cues_for_beat(short, short, 'en', lambda p: p * .06, 2.)] == [short]


# ------------------------------------------------------------------ hyphenated words across rolled pages
def test_a_hyphenated_word_wrapped_at_its_hyphen_is_never_rejoined_with_a_space():
    import re
    from kinodraw.engine.hybrid import HybridProduction
    text = ('So, the old tap drips all day and most nights. Usually it is a worn-out washer that has finally given '
            'up after years of hot water, and it is cheap to fix.')
    lines = wrap(text, 36)
    assert any(line.endswith('worn-') for line in lines)    # the written text wraps at the hyphen
    element = MotionElement(text='\n'.join(lines), preset='clauses', size=96, width=1500,
                            cues=tuple(float(k) for k in range(8)))
    pages = HybridProduction._rolled(element)
    assert len(pages) > 1
    for page in pages:
        assert 'worn- ' not in page.text, page.text           # never a space put into the word
    joined = ' '.join(re.sub(r'-\n', '-', p.text).replace('\n', ' ') for p in pages)
    assert 'worn-out' in joined
    assert captions.unwrap('a worn-\nout washer') == 'a worn-out washer'
    assert captions.unwrap('a quiet\nnight') == 'a quiet night'


# ------------------------------------------------------------------ rule 2: the band clear of heads and props
def test_the_caption_takes_the_band_that_covers_no_head_even_over_a_body():
    size, cap = (1920, 1080), (1300, 120)
    body = (500, 600, 1500, 1080)                          # a close shot: the body fills the bottom band
    crown = (760, 20, 1160, 200)                           # the head prop reaches the top band
    face = (700, 150, 1220, 560)
    x, y = captions.caption_spot(size, cap, 1046, ([body], [], [crown, face]))
    box = (x, y, x + cap[0], y + cap[1])
    assert not captions._overlap(box, crown) and not captions._overlap(box, face)
    assert y > 540                                         # the bottom band, over the body


def test_the_top_band_keeps_a_margin_from_the_frame_edge():
    size, cap = (1920, 1080), (1300, 120)
    body = (0, 500, 1920, 1080)
    x, y = captions.caption_spot(size, cap, 1046, ([body], [], []))
    assert y >= 1080 - 1046                                # as far from the top as the bottom band is from the bottom


def test_a_sky_object_counts_as_a_prop_and_the_caption_avoids_it():
    size, cap = (1920, 1080), (1300, 120)
    body = (600, 700, 1300, 1080)
    moon = (1500, 30, 1700, 200)
    x, y = captions.caption_spot(size, cap, 1046, ([body], [moon], []))
    box = (x, y, x + cap[0], y + cap[1])
    assert not captions._overlap(box, moon)


def _hybrid(tmp_path, text=REPORT, palette=None):
    board = script.build(ingest.read(text), story='explain')
    RulesDirector('en').direct(board)
    plan = from_rules(board)
    plan['style']['mode'] = 'motion'
    if palette:
        plan['style']['palette'].update(palette)
    for scene in plan['scenes']:
        scene['treatment'] = 'motion'
    (tmp_path / 'project.json').write_text(json.dumps({'director_v3': True, 'plan_v3': plan}))
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    return render.make_production(board, tl, 'en', tmp_path)


def test_the_caption_keeps_clear_of_a_picture_in_the_bottom_band_of_a_motion_scene(tmp_path):
    from kinodraw.engine.bold.render import H, W, element_pose
    prod = _hybrid(tmp_path)
    checked = 0
    for span in prod.spans:
        pictures = [(j, e) for j, e in enumerate(span.motion.elements) if e.kind == 'picture'] if span.motion else []
        if len(pictures) != 1:
            continue
        j, e = pictures[0]
        e.x, e.y, e.width, e.height = .5, .86, 420, 300     # a picture standing in the bottom band
        t = next(((c['start'] + c['end']) / 2 for c in prod.tl['captions']
                  if c['start'] >= span.join and c['end'] <= span.end), None)
        if t is None:
            continue
        prod.frame(t)
        x, y, scale, _ = element_pose(span.motion, e, j, t - span.start)
        sx, sy = prod.size[0] / W, prod.size[1] / H
        picture = ((x - e.width * scale / 2) * sx, (y - e.height * scale / 2) * sy,
                   (x + e.width * scale / 2) * sx, (y + e.height * scale / 2) * sy)
        assert not captions._overlap(prod.whiteboard.caption_box, picture), (t, prod.whiteboard.caption_box, picture)
        checked += 1
    assert checked


# ------------------------------------------------------------------ rule 3: the picture moves, not over a face
def test_where_every_band_covers_a_head_the_picture_moves_off_the_caption(tmp_path):
    prod = _hybrid(tmp_path)
    wb = prod.whiteboard
    c = max(wb.tl['captions'], key=lambda c: c['end'] - c['start'])
    t = (c['start'] + c['end']) / 2
    red = (220, 20, 20)
    # A face low in the frame and a head reaching into the top band: every spot covers one of them.
    heads = ((0, 900, 1920, 940), (0, 140, 1920, 200))
    frame = Image.new('RGBA', (1920, 1080), (246, 244, 238, 255))
    for box in heads:
        frame.paste(red + (255,), box)
    wb._caption(frame, t, ((24, 30, 40), (246, 244, 238), 4), None, ((), (), heads))
    x0, y0, x1, y1 = wb.caption_box
    rgb = np.asarray(frame.convert('RGB')).astype(int)

    def reds(region):
        return ((region[..., 0] > 180) & (region[..., 1] < 80) & (region[..., 2] < 80)).sum()
    assert y0 > 540                                        # the bottom band, the lesser cover
    assert reds(rgb[y0:y1, x0:x1]) < 50                    # no face left under the words ...
    assert reds(rgb[y0 - 120:y0, x0:x1]) > 30 * (x1 - x0)  # ... it moved up, whole, just above them
    assert reds(rgb[:300]) > 50 * 1900                     # the other head is still in the frame
    # Nothing moves where a band is clear.
    plain = Image.new('RGBA', (1920, 1080), (246, 244, 238, 255))
    plain.paste(red + (255,), (0, 60, 1920, 100))
    before = np.asarray(plain.convert('RGB')).copy()
    wb._caption(plain, t, ((24, 30, 40), (246, 244, 238), 4), None, ((), (), ((0, 60, 1920, 100),)))
    after = np.asarray(plain.convert('RGB'))
    assert (after[60:100] == before[60:100]).all()


def test_a_story_page_records_each_head_with_its_crown():
    from tests.test_storybook import production
    import tempfile
    from pathlib import Path
    prod = production(Path(tempfile.mkdtemp()))[0]
    sb = prod.storybook
    found = 0
    for span in (s for s in prod.spans if s.story):
        for shot in span.story:
            if not shot.figures or shot.page:
                continue
            t = span.start + (shot.start + shot.end) / 2
            prod.frame(t)
            assert len(sb.head_boxes) >= 1
            for head in sb.head_boxes:
                # From the top of what the figure draws (hair, mane, a crown) down to its head, inside its box.
                assert any(head[1] == f[1] and f[0] <= head[0] < head[2] <= f[2] and head[3] < f[3]
                           for f in sb.figure_boxes), (head, sb.figure_boxes)
            found += 1
            if found >= 3:
                return
    assert found


# ------------------------------------------------------------------ rule 4: no caption over a narrated card
PROMO = """# Pantrypal

Every week the same thing happens. The lettuce wilts, the yogurt expires, and the bread grows a blue coat.

Pantrypal reads your receipt and lists what you bought. Each item gets a timer, so you know what to cook first.

Pantrypal. Cook what you have. Download it free today. Link below.
"""


def test_a_narrated_closing_card_shows_its_words_with_no_caption_over_it(tmp_path):
    board = script.build(ingest.read(PROMO), story='story')
    board['genre'] = 'launch/promo'
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    end = tl['end_card']
    assert end['narrated']
    late = [c for c in tl['captions'] if c['end'] > end['appear'] + .2]
    assert late                                            # the voice is still reading the card's lines
    prod = render.make_production(board, tl, 'en', tmp_path)
    wb = getattr(prod, 'whiteboard', prod)
    t = max(end['appear'] + .1, late[0]['start'] + .05)
    paper = Image.new('RGBA', (1920, 1080), (246, 244, 238, 255))
    before = paper.tobytes()
    wb._caption(paper, t, ((24, 30, 40), (246, 244, 238), 4))
    assert paper.tobytes() == before
    # Before the card's words appear the caption still runs.
    early = next(c for c in tl['captions'] if c['end'] < end['start'])
    wb._caption(paper, (early['start'] + early['end']) / 2, ((24, 30, 40), (246, 244, 238), 4))
    assert paper.tobytes() != before


# ------------------------------------------------------------------ rule 5: titles read on their background
def _contrast(a, b):
    from kinodraw.engine.skin import contrast
    return contrast(a, b)


def test_dark_title_text_on_a_dark_background_takes_a_colour_that_reads(tmp_path):
    prod = _hybrid(tmp_path, palette={'background': '#121826', 'ink': '#1f2a3a', 'accent': '#2b3a55'})
    texts = [e for s in prod.spans if s.motion for e in s.motion.elements if e.kind == 'text']
    assert texts
    for e in texts:
        assert e.color is not None
        assert _contrast(ImageColor.getrgb(e.color), (18, 24, 38)) >= 4.5


def test_dark_text_on_plain_paper_keeps_the_palette(tmp_path):
    prod = _hybrid(tmp_path, palette={'background': '#f6f4ee', 'ink': '#1f2a3a'})
    texts = [e for s in prod.spans if s.motion for e in s.motion.elements if e.kind == 'text' and not e.accent]
    assert texts and all(getattr(e, 'color', None) is None for e in texts)


def test_the_first_caption_never_shares_the_band_with_the_title_or_covers_a_head():
    from tests.test_storybook import production
    import tempfile
    from pathlib import Path
    prod = production(Path(tempfile.mkdtemp()))[0]
    span = next(s for s in prod.spans if s.story)
    shot = next(s for s in span.story if s.title)
    for f in shot.figures:
        f.ground = .98                                     # the cast fills the bottom band of the title page
    c = next(c for c in prod.tl['captions'] if c['end'] > span.start + shot.start)
    t = max(c['start'], span.start + shot.start) + .6
    assert t < span.start + min(shot.end, 4.5)             # the title is up
    prod.frame(t)
    x0, y0, x1, y1 = prod.whiteboard.caption_box
    h = prod.size[1]
    title = (0, .09 * h - 8, prod.size[0], .09 * h + 2 * 1.2 * .07 * h + 8)
    assert not captions._overlap((x0, y0, x1, y1), title)
    for head in getattr(prod.storybook, 'head_boxes', ()):
        assert not captions._overlap((x0, y0, x1, y1), head), head

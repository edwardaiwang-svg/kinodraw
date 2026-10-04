"""Every ready look draws narration captions and only frame-slot words, without rewriting the script."""
import re
import socket
import sys
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from functools import wraps
from pathlib import Path

import pytest
import resvg_py
from PIL import ImageDraw

from kinodraw import PRODUCT, director, numbers, pipeline, script, styles
from kinodraw.engine import auto_scenes, captions, render as renderer, skin, timeline, vertical
from kinodraw.engine.collage import promo, ui_kit

FIX = Path(__file__).parent / 'fixtures'
SOURCES = {('explain', 'en'): 'tiny.md', ('explain', 'zh'): 'stick_wall_zh.md',
           ('explain', 'es'): 'miel_es.md', ('promo', 'en'): 'promo_tiny.md'}
# The collage's fixed interface words, chat names and decorative chat bank are constants of the look,
# never derived from or rewriting the script. Keep this exception visible in one named constant.
# ('sec', 'min'): collage/promo.py shortens "in 20 seconds" to a "20 sec!" stopwatch badge.
# SEATS, MINIMUM: the sign-up demo's fixed "min. 6" of 8 seats.
INTERFACE_FRAME_WORDS = (ui_kit.LABELS, ui_kit.CHATTER, ui_kit.NAMES, ('sec', 'min'),
                         (str(promo.SEATS), str(promo.MINIMUM)))
# Beat visual keys that hold narration cue words, not labels: never on-screen vocabulary.
NOT_FRAME_WORDS = {'trigger'}
CJK = re.compile('[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U000323af]+')
CASES = [(look, lang, aspect) for look in styles.looks(ready=True)
         for lang in look['languages'] for aspect in ('16:9', '9:16')]


def tokens(text, lang):
    text = unicodedata.normalize('NFKC', text).lower()
    if lang != 'zh':
        return re.findall(r'[^\W_]+', text)
    out, run = [], ''
    for ch in text:
        cjk = ('\u3400' <= ch <= '\u4dbf' or '\u4e00' <= ch <= '\u9fff'
               or '\U00020000' <= ch <= '\U000323af')
        if cjk or not ch.isalnum():
            if run:
                out.append(run)
                run = ''
            if cjk:
                out.append(ch)
        else:
            run += ch
    return out + ([run] if run else [])


def contiguous(needle, haystack):
    return any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def check_tokens(actual, expected, lang, context):
    got, want = tokens(actual, lang), tokens(expected, lang)
    differences = []
    for tag, a, b, c, d in SequenceMatcher(None, want, got, autojunk=False).get_opcodes():
        if tag != 'equal':
            differences.append(f'{tag}: expected {want[a:b]!r}, drawn {got[c:d]!r}')
    assert got == want, f'{context}: ' + '; '.join(differences)


def check_caption_words(board, tl, lang, source, context):
    display = ' '.join(b['display'][lang] for b in board['beats'])
    check_tokens(' '.join(c['text'] for c in tl['captions']), display, lang, context + ' caption words')
    for beat in board['beats']:
        text = beat['display'][lang]
        assert beat['spoken'][lang] == numbers.normalize(text, lang).spoken, f'{context}: spoken {beat["id"]}'
    # The narration beats, in order, are the script's body word for word: nothing reordered, dropped or repeated.
    body = '\n'.join(line for line in source.splitlines() if not re.match(r'\s*#', line))
    said = ' '.join(b['display'][lang] for b in board['beats'] if b['kind'] == 'narration')
    check_tokens(said, body, lang, context + ' rewritten script')


def strings(value, lang, localized=False):
    """Every string in value, in lang only. localized=True keeps only text written per language
    ({'en': ...}), so ids, kinds and asset names ('b006n', 'stat', 'nyc_skyline') are not frame words."""
    if isinstance(value, str):
        if not localized:
            yield value
    elif isinstance(value, dict):
        if value and set(value) <= set(script.TEXT):
            yield from strings(value.get(lang, ''), lang)
        else:
            for k, v in value.items():
                if k not in NOT_FRAME_WORDS:
                    yield from strings(v, lang, localized)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from strings(v, lang, localized)


def frame_slots(board, lang, interface=False):
    slots = list(strings(board.get('title', {}), lang)) + list(strings(board.get('footer', {}), lang))
    for chapter in board['chapters']:
        for key in ('label', 'title', 'source', 'speaker'):
            slots.extend(strings(chapter.get(key, {}), lang))
    for beat in board['beats']:
        for key in ('visuals', 'take'):
            slots.extend(strings(beat.get(key, {}), lang, localized=True))
    fixed = list(strings(script.TEXT[lang], lang)) + list(PRODUCT.values()) + [auto_scenes.CREDIT_LINE[lang]]
    if interface:
        for bank in INTERFACE_FRAME_WORDS:
            fixed.extend(strings(bank[lang] if isinstance(bank, dict) else bank, lang))
    return slots + [re.sub(r'\{[^}]*\}', ' ', s) for s in fixed]


def check_drawn_words(text, slots, narration, lang, context, figures=0):
    """narration: '' unless the look may quote it word for word. figures: the highest figure, step or part
    number the board can show (its chapter or beat count)."""
    ts = tokens(text, lang)
    vocab = {t for s in slots for t in tokens(s, lang)}
    said = tokens(narration, lang)
    # A number passes when stated exactly in a slot or the quotable narration, or as a figure number.
    missing = [t for t in ts if t not in vocab and not (t.isdigit() and (t in said or int(t) <= figures))]
    if lang == 'zh':          # one character is not a word: each run of Chinese must be part of one slot's run
        runs = [r for s in slots for r in CJK.findall(unicodedata.normalize('NFKC', s))]
        missing += [r for r in CJK.findall(unicodedata.normalize('NFKC', text)) if not any(r in p for p in runs)]
    quoted = ts and (any(contiguous(ts, tokens(s, lang)) for s in slots) or contiguous(ts, said))
    assert not missing or quoted, f'{context}: non-caption {text!r}; unmatched tokens {missing!r}'


def check_counter(value, slots, narration, lang, figures, context):
    """A counter badge rolls up to a number the script states ("40 messages later"), then counts the chat
    bubbles after it, so it may show any whole number up to the largest stated number plus the board's figures."""
    stated = [int(t) for s in [*slots, narration] for t in tokens(s, lang) if t.isdigit()]
    assert value.isdigit() and int(value) <= max(stated + [0]) + figures, f'{context}: counter shows {value!r}'


def check_drawn_caption(lines, cue, lang, context):
    assert lines, f'{context}: caption not drawn for {cue["text"]!r}'
    check_tokens(' '.join(lines), cue['text'], lang, context + ' drawn caption')


def clear_text_caches():
    """Also visit class methods (Vertical._title_image), not just module functions."""
    seen = set()
    for name, module in list(sys.modules.items()):
        if name != 'kinodraw' and not name.startswith('kinodraw.'):
            continue
        for key, value in list(vars(module).items()):
            if key.endswith('_cache') and isinstance(value, dict):
                value.clear()
            values = [value]
            if isinstance(value, type) and value.__module__.startswith('kinodraw.'):
                values.extend(vars(value).values())
            for item in values:
                if id(item) not in seen and callable(getattr(item, 'cache_clear', None)):
                    item.cache_clear()
                    seen.add(id(item))


class TextRecorder:
    def __init__(self, monkeypatch):
        self.other, self.calls, self.stack, self.images, self.counters = [], [], [], {}, []
        badges = set()
        real_text, real_svg = ImageDraw.ImageDraw.text, resvg_py.svg_to_bytes

        def text(draw, xy, text, *args, **kwargs):
            (self.stack[-1] if self.stack else self.other).append(str(text))
            return real_text(draw, xy, text, *args, **kwargs)

        def svg(*args, **kwargs):
            doc = kwargs.get('svg_string', args[0] if args else None)
            if doc is not None:
                root = ET.fromstring(doc)     # XML unescapes entities; itertext includes nested tspans once.
                for el in root.iter():
                    if el.tag.rsplit('}', 1)[-1] == 'text':
                        out = self.counters if doc in badges else self.stack[-1] if self.stack else self.other
                        out.append(''.join(el.itertext()))
            return real_svg(*args, **kwargs)

        def badge(n, real=ui_kit.badge):           # the collage's counter badge: checked as a counter
            doc = real(n)
            badges.add(doc)
            return doc

        monkeypatch.setattr(ImageDraw.ImageDraw, 'text', text)
        monkeypatch.setattr(ui_kit, 'badge', badge)
        monkeypatch.setattr(resvg_py, 'svg_to_bytes', svg)
        for module in (captions, vertical):
            monkeypatch.setattr(module, 'caption_image', self.caption_wrapper(module.caption_image))
        # Pixel Quest and Mosaic letter their 16:9 captions on their own panel instead of the outline caption,
        # one glyph per draw call: record each lettered line whole, not character by character.
        monkeypatch.setattr(skin, '_caption_panel', self.caption_wrapper(skin._caption_panel))
        real_runs = skin._draw_runs

        def runs(draw, text, *args, **kwargs):
            (self.stack[-1] if self.stack else self.other).append(str(text))
            self.stack.append([])
            try:
                return real_runs(draw, text, *args, **kwargs)
            finally:
                self.stack.pop()
        monkeypatch.setattr(skin, '_draw_runs', runs)

    def caption_wrapper(self, real):
        @wraps(real)
        def wrapped(*args, **kwargs):
            lines = []
            self.stack.append(lines)
            try:
                img = real(*args, **kwargs)
            finally:
                self.stack.pop()
            if lines:
                self.images[id(img)] = (img, lines)  # retain the image so ids cannot be recycled
            else:
                assert id(img) in self.images, 'caption cache was populated outside the recorder'
                lines = self.images[id(img)][1]
            self.calls.append(list(lines))
            return img
        wrapped.cache_clear = real.cache_clear
        return wrapped


@pytest.fixture
def recorder(monkeypatch):
    def offline(*args, **kwargs):
        pytest.fail('caption-words requires local models: attempted network/download ' + repr(args))
    from kinodraw import net
    monkeypatch.setattr(net, 'urlopen', offline)
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket.socket, 'connect_ex', offline)
    return TextRecorder(monkeypatch)


@pytest.fixture(scope='module')
def productions():
    return {}


@pytest.mark.parametrize('look,lang,aspect', CASES,
                         ids=[f'{look["id"]}-{lang}-{aspect}' for look, lang, aspect in CASES])
def test_every_look_keeps_caption_and_frame_words(look, lang, aspect, tmp_path, recorder, productions):
    context = f'{look["id"]}/{lang}/{aspect}'
    assert aspect in look['aspect'], f'{context}: ready look must support both aspects'
    story = 'explain' if 'explain' in look['stories'] else look['stories'][0]
    filename = SOURCES.get((story, lang), f'{story}_{lang}.md')
    assert (FIX / filename).is_file(), \
        f'{context}: missing fixture tests/fixtures/{filename} for story {story!r}'
    src, folder = FIX / filename, tmp_path / 'p'
    key = (look['id'], lang)
    clear_text_caches()
    if key not in productions:
        pipeline.new_project(src, folder, direction={'look': look['id'], 'story': story})
        director.direct(folder)
        board = pipeline.storyboard(folder)
        tl = timeline.layout(board, lang, timeline.synthetic_clips(board, lang))
        base = renderer.make_production(board, tl, lang, folder)
        productions[key] = board, tl, base, (list(recorder.other), list(recorder.counters))
    else:
        board, tl, base, built_text = productions[key]
        recorder.other.extend(built_text[0])
        recorder.counters.extend(built_text[1])
    check_caption_words(board, tl, lang, src.read_text(encoding='utf-8'), context)
    # Vertical is the factory's wrapper over this same production: build the expensive
    # board once, but rasterize each aspect's own titles/chrome/captions under the recorder.
    prod = base if aspect == '16:9' else vertical.Vertical(base)
    slots = frame_slots(board, lang, interface=look['renderer'] == 'collage')
    # Only the collage promo puts narration phrases on screen ("No app."), word for word; other looks draw slots only.
    narration = ' '.join(b['display'][lang] for b in board['beats']) if look['renderer'] == 'collage' else ''
    figures = max(len(board['beats']), len(board['chapters']))
    times = {(c['start'] + c['end']) / 2 for c in tl['captions']}
    times.update(t for c in tl['chapters'] for t in (c['start'] + .5, (c['start'] + c['end']) / 2))
    times.update(((tl['end_card']['start'] + tl['end_card']['end']) / 2, tl['duration'] - 1 / 30))
    # 9:16 always sets captions under the board; the 16:9 collage burns in none unless the board asks.
    shows = aspect == '9:16' or getattr(base, 'show_captions', True)
    errors = []
    for t in sorted(times):
        recorder.calls.clear()
        prod.frame(t)
        cue = next((c for c in tl['captions'] if c['start'] <= t < c['end']), None)
        try:
            if cue:
                assert recorder.calls or not shows, f'{context} at {t:.3f}s: caption not drawn for {cue["text"]!r}'
                for lines in recorder.calls:
                    check_drawn_caption(lines, cue, lang, f'{context} at {t:.3f}s')
            else:
                assert not recorder.calls, f'{context} at {t:.3f}s: caption drawn outside cue'
        except AssertionError as exc:
            errors.append(str(exc))
    assert recorder.other, f'{context}: no frame-slot text recorded'
    for text in dict.fromkeys(recorder.other):
        try:
            check_drawn_words(text, slots, narration, lang, context, figures)
        except AssertionError as exc:
            errors.append(str(exc))
    for value in dict.fromkeys(recorder.counters):
        try:
            check_counter(value, slots, narration, lang, figures, context)
        except AssertionError as exc:
            errors.append(str(exc))
    if aspect == '9:16':
        del productions[key]             # don't retain ten full-resolution boards until module teardown
    assert not errors, '\n'.join(errors)


def test_checkers_reject_missing_swapped_and_invented_words():
    text = 'Gutenberg invented the printing press.'
    board = {'beats': [{'id': 'b1', 'kind': 'narration', 'display': {'en': text},
                        'spoken': {'en': numbers.normalize(text, 'en').spoken}}]}
    for broken in ('Gutenberg invented printing press.', 'Gutenberg the invented printing press.'):
        with pytest.raises(AssertionError, match='caption words'):
            check_caption_words(board, {'captions': [{'text': broken}]}, 'en', text, 'probe')
    with pytest.raises(AssertionError, match='television'):
        check_drawn_words('Gutenberg invented television', ['Printing press'], text, 'en', 'probe')
    with pytest.raises(AssertionError, match='drawn caption'):
        check_drawn_caption(['Gutenberg invented printing press.'], {'text': text}, 'en', 'probe')
    with pytest.raises(AssertionError, match='rewritten script'):
        check_caption_words(board, {'captions': [{'text': text}]}, 'en', 'Gutenberg built a press.', 'probe')
    two = 'First sentence. Second sentence.'
    for beats in (['Second sentence.', 'First sentence.'], ['First sentence.'],
                  ['First sentence.', 'First sentence.', 'Second sentence.']):
        board = {'beats': [{'id': f'b{i}', 'kind': 'narration', 'display': {'en': b},
                            'spoken': {'en': numbers.normalize(b, 'en').spoken}} for i, b in enumerate(beats)]}
        with pytest.raises(AssertionError, match='rewritten script'):    # reordered, omitted, repeated
            check_caption_words(board, {'captions': [{'text': ' '.join(beats)}]}, 'en', '# Title\n' + two, 'probe')


def test_frame_words_reject_ids_invented_numbers_and_shuffled_chinese():
    board = {'chapters': [], 'beats': [{'visuals': [{'id': 'b006n', 'type': 'stat', 'doodle': 'nyc_skyline',
                                                     'label': {'en': 'Must eat'}}]}]}
    slots = frame_slots(board, 'en')
    check_drawn_words('Must eat', slots, '', 'en', 'probe')
    for leak in ('b006n stat', 'nyc skyline'):
        with pytest.raises(AssertionError, match='unmatched'):
            check_drawn_words(leak, slots, '', 'en', 'probe')
    check_drawn_words('Part 3 of 1450', ['Part of'], 'Printed in 1450.', 'en', 'probe', figures=3)
    for invented in ('999999', '1449'):     # a number below a stated one is still invented, unless a counter
        with pytest.raises(AssertionError, match=invented):
            check_drawn_words(invented, ['Part 1'], 'Printed in 1450.', 'en', 'probe')
    check_drawn_words('2', ['Create an event'], '', 'en', 'probe', figures=2)   # step 2 when no number is stated
    with pytest.raises(AssertionError, match='non-caption'):                    # a narration quote is not a slot
        check_drawn_words('Printed in 1450', ['Part 1'], '', 'en', 'probe', figures=3)
    check_counter('1449', ['Part 1'], 'Printed in 1450.', 'en', 3, 'probe')
    for wrong in ('1454', 'b1'):
        with pytest.raises(AssertionError, match='counter'):
            check_counter(wrong, ['Part 1'], 'Printed in 1450.', 'en', 3, 'probe')
    zh_slots = ['第 部分', '钱', '今天的事', '我们要看']
    check_drawn_words('第1部分 · 钱', zh_slots, '一共2部分', 'zh', 'probe', figures=2)
    with pytest.raises(AssertionError, match='unmatched'):
        check_drawn_words('我们今天要看的事', zh_slots, '', 'zh', 'probe')


def test_tokens_and_slots_keep_language_and_order():
    assert tokens('Ｆoo—3,000 “ÁRBOL”', 'es') == ['foo', '3', '000', 'árbol']
    assert tokens('蜂蜜，ＡPI 30%', 'zh') == ['蜂', '蜜', 'api', '30']
    assert list(strings({'nested': [{'en': 'Honey', 'zh': '蜂蜜', 'es': 'Miel'}]}, 'es')) == ['Miel']
    with pytest.raises(AssertionError, match='unmatched'):
        check_drawn_words('press invented Gutenberg', [], 'Gutenberg invented press', 'en', 'probe')

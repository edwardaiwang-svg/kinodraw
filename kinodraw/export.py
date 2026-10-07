"""Atomic GIF/WebM exports and native-size generated frame rendering."""
import bisect
import copy
from dataclasses import replace
from functools import lru_cache
import math
from pathlib import Path
import subprocess
import tempfile

import imageio_ffmpeg
from PIL import Image, ImageDraw

from .engine import ink, skin as skins
from .engine.captions import word_at
from .engine.board import Camera
from .engine.geometry import LANDSCAPE, SQUARE, geometry_for_size
from .engine.render import Production, ease, faded, chip_text, source_line, ui_text

from .progress import RenderContext, validate_frames, wait_process

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
# The source is read only as a local MP4: a playlist or concat list renamed .mp4 can't make FFmpeg fetch URLs or
# open other files.
LOCAL_MP4 = ['-protocol_whitelist', 'file', '-f', 'mp4']


def export_video(source, output, *, audio=None, context=None):
    """GIF uses a generated palette; WebM uses VP9 and optional Opus audio.

    The source is retained on every outcome. No resizing is performed.
    """
    source, output = Path(source), Path(output)
    if output.suffix.lower() not in ('.gif', '.webm'):
        raise ValueError('export requires .gif or .webm')
    ctx = context or RenderContext()
    ctx.begin()
    ctx.token.check()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.export-', dir=output.parent) as work:
        temp = Path(work) / output.name
        progress = Path(work) / 'progress'
        cmd = [FFMPEG, '-y', '-v', 'error', *LOCAL_MP4, '-i', str(source)]
        if audio is not None and output.suffix.lower() == '.webm':
            cmd += ['-protocol_whitelist', 'file', '-i', str(audio)]
        if output.suffix.lower() == '.gif':
            cmd += ['-filter_complex', '[0:v]split[a][b];[a]palettegen[p];[b][p]paletteuse',
                    '-an', '-loop', '0']
        else:
            cmd += ['-map', '0:v:0', '-map', '1:a:0' if audio is not None else '0:a?',
                    '-c:v', 'libvpx-vp9', '-crf', '30', '-b:v', '0', '-c:a', 'libopus', '-af', 'apad', '-shortest']
        # The counting decode is also owned/cancellable; no hidden subprocess.
        from .progress import encoded_frames
        count_progress = Path(work) / 'count-progress'
        count = ctx.token.register(subprocess.Popen([
            FFMPEG, '-v', 'error', *LOCAL_MP4, '-i', str(source), '-map', '0:v:0',
            '-progress', str(count_progress), '-f', 'null', '-'], start_new_session=True), group=True)
        try:
            wait_process(count, RenderContext(token=ctx.token))
            total = encoded_frames(count_progress)
            times = [int(line.split('=', 1)[1]) for line in count_progress.read_text(encoding='utf-8').splitlines()
                     if line.startswith('out_time_us=') and line.split('=', 1)[1].lstrip('-').isdigit()]
            duration = max(times, default=0) / 1_000_000
            if total <= 0 or duration <= 0:
                raise ValueError('source has no decodable video frames')
        finally:
            if count.poll() is None:
                ctx.token.stop(count)
            ctx.token.unregister(count)
        if output.suffix.lower() == '.webm':
            cmd += ['-t', repr(duration)]
        cmd += ['-threads', '2', '-progress', str(progress), '-stats_period', '0.05', str(temp)]
        process = ctx.token.register(subprocess.Popen(cmd, start_new_session=True), group=True)
        try:
            wait_process(process, ctx, [progress], total)
            ctx.token.check()
            # The palette recipe preserves frame count; WebM uses the measured
            # source duration. Decode the actual staged output, not its header.
            validate_frames(FFMPEG, temp, total, ctx)
            if output.suffix.lower() == '.webm':
                # validate_frames maps video only. Also decode every audio
                # stream; corrupt Opus packets can log errors even with exit 0.
                with (Path(work) / 'decode-errors').open('w+b') as errors:
                    decode = ctx.token.register(subprocess.Popen([
                        FFMPEG, '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', str(temp),
                        '-map', '0:v:0', '-map', '0:a?', '-vsync', '0', '-f', 'null', '-'],
                        stderr=errors, start_new_session=True), group=True)
                    try:
                        wait_process(decode, ctx)
                        errors.seek(0)
                        detail = errors.read().decode('utf-8', errors='replace').strip()
                        if detail:
                            raise RuntimeError(f'export decode failed: {detail}')
                    finally:
                        ctx.token.stop(decode)
            ctx.token.commit(temp, output)
        finally:
            if process.poll() is None:
                ctx.token.stop(process)
            ctx.token.unregister(process)
    return output


def render_generated(factory, size, start, frames, output, *, crf=20, context=None):
    """Factory(size) must build drawings at target resolution, not resize frames.

    Kept outside dispatch so callers can provide native factories for their look.
    The encoder enforces the requested frame dimensions.
    """
    from .engine.render import encode
    size = tuple(size)
    if len(size) != 2 or any(not isinstance(v, int) or v <= 0 or v % 2 for v in size):
        raise ValueError('size must contain two positive even pixel dimensions')
    prod = factory(size)
    if tuple(prod.size) != size:
        raise ValueError('native factory returned the wrong size')
    encode(prod, start, frames, output, crf, context=context)
    return prod


def native_production(episode, timing, lang, project, size, *, aspect='16:9', relaxed=False):
    """Reconstruct the saved cinematic production at a native output size.

    The default 1080p dispatch is deliberately unchanged. Other targets reuse
    Production's scheduled vector recipes and HybridProduction's saved plan.
    This factory is also the reconstruction seam for segment processes.
    """
    import json
    from .engine.geometry import geometry_for_size
    from .engine.render import make_production
    from .engine.hybrid import HybridProduction
    size = geometry_for_size(size, aspect).size
    if size == (1920, 1080) and aspect == '16:9':
        return make_production(episode, timing, lang, project, relaxed=relaxed)
    if aspect not in ('16:9', '1:1'):
        raise ValueError('native cinematic production supports 16:9 and 1:1')
    from .engine.storyboard import drawable
    if drawable(episode.get('look') or 'whiteboard') == 'collage':
        raise ValueError('native collage export is not supported')
    config_path = Path(project) / 'project.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    plan = config.get('plan_v3') if config.get('director_v3') else None
    board = NativeProduction(episode, timing, lang, project, size, aspect, relaxed)
    if (not relaxed and plan and plan['style']['mode'] != 'whiteboard'
            and any(s['treatment'] != 'whiteboard' for s in plan['scenes'])):
        return HybridProduction(episode, timing, lang, project, plan, board)
    return board


# Recipes retain logical layout and source timing; only rasterization changes.
# No global patching: concurrent factories and default renders remain isolated.
def _drawing_at(drawing, scale, skin, x, y):
    if isinstance(drawing, skins.Highlighted):
        text = _drawing_at(drawing.text, scale, skin, x, y)
        return skins.Highlighted(text, [tuple(v * scale for v in box[:4]) + (box[4],)
                                        for box in drawing.boxes], drawing.color)
    recipe = getattr(drawing, 'native_recipe', None)
    if recipe:
        kind, args, options = recipe
        options = dict(options)
        if kind == 'diagram':
            from .engine.source_diagrams import ProofDrawing
            specs, timing, size, lang = args
            native = ProofDrawing(specs, timing, tuple(round(v * scale) for v in size), lang, skin)
            native.bind(drawing.start, drawing.rate)
        elif kind == 'ui':
            from .engine.auto_scenes import ui_small
            text, size = args
            native = ink.StaticDrawing(ui_small(text, round(size*scale), skin), pop=drawing.duration)
        elif kind == 'text':
            lines, lang, size = args
            options['pad'] = max(1, round(options['pad'] * scale))
            options['min_dur'] = options['max_dur'] = drawing.duration
            native = ink.TextDrawing(lines, lang, max(1, round(size * scale)), **options)
        elif kind in ('svg', 'picture'):
            path, box = args
            options['speed'] *= scale
            factory = ink.svg_drawing if kind == 'svg' else ink.picture_drawing
            native = factory(path, tuple(max(1, round(v * scale)) for v in box), **options)
            native.own = getattr(drawing, 'own', False)
        else:
            size, polys = args
            options['width'] *= scale
            options['speed'] *= scale
            if options['closed_fill']:
                options['closed_fill'] = [([(x * scale, y * scale) for x, y in poly], color)
                                          for poly, color in options['closed_fill']]
            native = ink.stroke_drawing(tuple(max(1, round(v * scale)) for v in size),
                [[(x * scale, y * scale) for x, y in poly] for poly in polys], **options)
        # Path sampling density changes at native size, but the hand's source
        # schedule, including lifts, must not change with export resolution.
        if isinstance(native, ink.PathDrawing):
            native.polys = [p * scale for p in drawing.polys]
            native.lens = [v * scale for v in drawing.lens]
            native.table = list(drawing.table)
            native.draw_time, native.pop = drawing.draw_time, drawing.pop
            native.brush = drawing.brush * scale
        elif isinstance(native, ink.RevealDrawing):
            native.draw_time = drawing.draw_time
        native.duration = drawing.duration
        native = skin.dress(native, x, y)
        if isinstance(native, ink.PathDrawing):
            # Bind after dressing: material skins wrap the path drawing but
            # must share the same stateless native mask semantics.
            native._mask = native._native_mask
        return native
    if isinstance(drawing, ink.StaticDrawing):
        photo = drawing.native_photo
        if photo:
            path, diameter, ring, color = photo
            image = ink.circle_photo(path, round(diameter * scale), round(ring * scale), color)
        elif drawing.image.getbbox() is None:
            image = Image.new('RGBA', tuple(max(1, round(v * scale)) for v in drawing.size))
        else:
            raise ValueError('native export needs the source recipe for this static drawing')
        return skin.dress(ink.StaticDrawing(image, pop=drawing.duration), x, y)
    raise ValueError(f'native export has no source recipe for {type(drawing).__name__}')


class _NativeHand(ink.Hand):
    def __init__(self, source, scale):
        self.scale = scale
        self.img = source.img.resize(tuple(round(v * scale) for v in source.img.size), Image.Resampling.LANCZOS)
        self.shadow = source.shadow.resize(self.img.size, Image.Resampling.LANCZOS)
        self.tip = tuple(v * scale for v in source.tip)
        self.paths = source.paths
        self.side = source.side

    def paste(self, frame, point, lifted=False):
        s = self.scale
        x = point[0] - self.tip[0]
        y = point[1] - self.tip[1] - (6 * s if lifted else 0)
        ink.paste(frame, self.shadow, x + 14 * s, y + 18 * s)
        ink.paste(frame, self.img, x, y)


def _caption_image(text, lang, skin, size, aspect, look=None, word=None, accent=None):
    """Reflow the original cue, keeping its caption face and panel treatment. ``look`` = (letters, outline, stroke)
    letters it in an outline of other colours (a hybrid's palette); ``word`` (captions.word_spans) is in ``accent``."""
    from .engine import captions
    s = size[1] / 1080
    max_w, max_h = round(size[0] * (.92 if aspect == '16:9' else .88)), round(size[1] * .18)
    kind = 'en_caption' if lang in ('en', 'es') else 'zh_caption'
    panel = skin.caption_style != 'outline' and look is None
    color, edge, stroke = look or (skin.caption, skin.caption_edge, 7)
    saved_lines, saved_size = (skins.caption_layout(text, lang, skin) if panel else
                              (captions.balanced_lines(text, lang, skin.fonts), 70))
    font_size = round((saved_size if aspect == '16:9' else min(saved_size, 48)) * s)
    while True:
        font = ink.font(kind, max(2, font_size), skin.fonts)
        measure = (lambda line: skins._run_width(line, kind, font_size, skin.fonts)) if panel else font.getlength
        pad = round((32 if panel else 11) * s)
        lines, line = [], ''
        for unit in captions.units(text, lang):
            candidate = (line + unit).strip()
            if line and measure(candidate) > max_w - 2 * pad:
                lines.append(line.strip())
                line = ''
            for ch in unit:
                if line and measure(line + ch) > max_w - 2 * pad:
                    lines.append(line.strip())
                    line = ''
                line += ch
        if line.strip():
            lines.append(line.strip())
        lines = (saved_lines if aspect == '16:9' and saved_lines else lines) or ['']
        lh = round(font_size * (1.25 if panel else 1.16))
        tail = round(20 * s) if skin.caption_style == 'bubble' else 0
        h = lh * len(lines) + round((40 if panel else 24) * s) + tail
        if (h <= max_h and max(measure(l) for l in lines) <= max_w-2*pad) or font_size <= 2:
            break
        font_size -= 1
    widths = [measure(line) for line in lines]
    w = math.ceil(max(widths)) + 2 * pad

    def draw(letters):
        image = Image.new('RGBA', (w, h))
        d = ImageDraw.Draw(image)
        if panel:
            ph = h - tail
            if tail:
                # Same stepped bubble silhouette, regenerated in target pixels.
                skins._stepped(d, (0, 0, w - 1, ph - 1), '#1E1B2E', max(1, round(8 * s)))
                d.polygon([(40*s, ph-9*s), (80*s, ph-9*s), (80*s, ph+3*s),
                           (68*s, ph+3*s), (68*s, ph+11*s), (56*s, ph+11*s),
                           (56*s, ph+19*s), (40*s, ph+19*s)], fill='#1E1B2E')
                skins._stepped(d, (8*s, 8*s, w-9*s, ph-9*s), '#FFFDF5', max(1, round(4*s)))
                d.polygon([(48*s, ph-12*s), (72*s, ph-12*s), (72*s, ph-5*s),
                           (60*s, ph-5*s), (60*s, ph+3*s), (48*s, ph+3*s)], fill='#FFFDF5')
            else:
                d.rectangle((0, 0, w-1, ph-1), fill='#3B2418')
                d.rectangle((8*s, 8*s, w-9*s, ph-9*s), outline='#D9A441', width=max(1, round(3*s)))
        for i, (line, width) in enumerate(zip(lines, widths)):
            if panel:
                skins._draw_runs(d, line, ((w-width)/2, 20*s+font_size+i*lh), kind,
                                 font_size, skin.fonts, ink.rgba(letters))
            else:
                d.text(((w-width)/2, 7*s+i*lh), line, font=font, fill=ink.rgba(letters),
                       stroke_width=max(1, round(stroke*s)), stroke_fill=ink.rgba(edge))
        return image
    image = draw(color)
    if word is None or accent is None:
        return image
    if panel:
        rows = [(20*s + font_size + i*lh + font.getbbox(line, anchor='ls')[1],
                 20*s + font_size + i*lh + font.getbbox(line, anchor='ls')[3]) for i, line in enumerate(lines)]
    else:
        rows = [(7*s + i*lh + font.getbbox(line)[1], 7*s + i*lh + font.getbbox(line)[3]) for i, line in enumerate(lines)]
    boxes = captions.word_boxes(text, lang, lines, [(w - x) / 2 for x in widths], rows,
                                lambda line, j: measure(line[:j]), (w, h))
    if not boxes or word >= len(boxes):
        return image
    lit = draw(captions.highlight_color(tuple(accent[:3]), tuple(color[:3]), tuple(edge[:3])))
    return captions.paint_word(image, lit, boxes[word])


@lru_cache(maxsize=8)
def _caption_word_image(text, lang, skin, size, aspect, look, word, accent):
    return _caption_image(text, lang, skin, size, aspect, look, word, accent)


class NativeProduction(Production):
    """Production's actual schedule and geometry with regenerated native drawings."""
    native = True

    def __init__(self, episode, timing, lang, project, size, aspect, relaxed=False):
        # The portrait recipes already stack title/agenda/endcard content using
        # geometry bands; square supplies its own bands, not a crop of a frame.
        logical = LANDSCAPE if aspect == '16:9' else replace(SQUARE, name='portrait',
            text_safe=((64, 140, 1016, 820), (64, 140, 1016, 820)))
        base = Production(episode, timing, lang, project, relaxed=relaxed, geometry=logical)
        self.__dict__.update(base.__dict__)
        self.scale = s = size[0] / logical.size[0]
        self.aspect, self.size = aspect, tuple(size)
        self.g = geometry_for_size(size, aspect)
        self.vertical = False
        # Keep material cell sizes proportional to the saved logical treatment.
        if self.skin.textured:
            args = self.skin.margs
            for key in ('cell', 'line_grow'):
                if key in args:
                    args[key] = max(1, round(args[key] * s))
            self.skin = replace(self.skin, material_args=tuple(sorted(args.items())))
        self.ctx = copy.copy(base.ctx)
        self.ctx.skin = self.skin
        self.ctx.layout = self.layout = copy.copy(base.layout)
        self.layout.g = self.g
        self.ctx.text_w *= s
        self.ctx.text_h *= s
        if self.ctx.page_x is not None:
            self.ctx.page_x *= s
        pinned = {id(n['mini']) for n in base.notes.values() if 'mini' in n}
        mapping = {}
        for old in base.ctx.elements:
            if id(getattr(old.drawing, 'image', None)) in pinned:
                continue
            new = copy.copy(old)
            new.x, new.y = old.x * s, old.y * s
            if (isinstance(old.drawing, ink.StaticDrawing) and not old.drawing.native_photo
                    and old.drawing.image.getbbox() is not None):
                # Production's sole static text stamp is a photo credit. Recover
                # its source text, never scale the already drawn credit bitmap.
                from .engine import auto_scenes
                for chapter in self.ep['chapters']:
                    speaker = chapter.get('speaker') or {}
                    credit = auto_scenes.photo_credit(self.project_dir, speaker.get('photo', ''), lang)
                    if credit:
                        candidate = base.skin.dress(ink.StaticDrawing(auto_scenes.ui_small(credit, 26, base.skin)), old.x, old.y)
                        if candidate.image.tobytes() == old.drawing.image.tobytes():
                            old.drawing.native_recipe = ('ui', (credit, 26), {})
                            break
            new.drawing = _drawing_at(old.drawing, s, self.skin, new.x, new.y)
            for attr in ('_first_pen', '_last_pen'):
                new.__dict__.pop(attr, None)
            mapping[id(old)] = new
        for old in base.ctx.elements:
            if id(old) in mapping:
                mapping[id(old)].after = mapping.get(id(old.after))
        self.ctx.elements = list(mapping.values())
        self.ctx.registry = {vid: {key: [mapping[id(e)] for e in els if id(e) in mapping]
                                  for key, els in groups.items()} for vid, groups in base.ctx.registry.items()}
        self.cards = {key: {**card, 'box': tuple(v*s for v in card['box']),
                           'els': [mapping[id(e)] for e in card['els']]}
                      for key, card in base.cards.items()}
        self.camera = Camera(self.g, locked=base.camera.locked)
        self.camera.keys = [(t, x*s, kind) for t, x, kind in base.camera.keys]
        self.cuts = [(t, x*s, kind) for t, x, kind in base.cuts]
        self.agenda_x = None if base.agenda_x is None else base.agenda_x*s
        self.scene_marks = [(x*s, scene) for x, scene in base.scene_marks]
        self.pages = {key: x*s for key, x in base.pages.items()}
        self.notes = {}
        for key, note in base.notes.items():
            new = {k: v for k, v in note.items() if k not in ('image', 'mini', 'shown')}
            new['els'] = [mapping[id(e)] for e in note['els']]
            for field in ('bbox', 'pin_xy', 'mini_size'):
                if field in new:
                    new[field] = tuple(round(v*s) if field == 'mini_size' else v*s for v in new[field])
            new['x'] *= s
            self.notes[key] = new
        self.hand = _NativeHand(base.hand, s) if base.hand else None
        self._pin_notes()
        self._index()
        self._caption_cache = {}

    @property
    def boards(self):
        """Compatibility inspection view; these are the real Production elements."""
        return [(self.tl['beats'][b['id']], [e for e in self.els if e.beat == b['id']],
                 ink.StaticDrawing(self._caption_picture(self.ctx.T(b.get('display'))))) for b in self.ep['beats']]

    def _drift(self, t):
        return super()._drift(t) * self.scale

    def _caption_picture(self, text):
        if text not in self._caption_cache:
            self._caption_cache[text] = _caption_image(text, self.lang, self.skin, self.size, self.aspect)
        return self._caption_cache[text]

    def _caption(self, frame, t, look=None, accent=None):
        i = bisect.bisect_right(self.cap_starts, t) - 1
        if i < 0:
            return
        cue = self.tl['captions'][i]
        if cue['start'] <= t < cue['end']:
            word = word_at(self.cap_words[i] if self.cap_words else cue.get('words'), t)
            image = (self._caption_picture(cue['text']) if word is None and look is None else
                     _caption_word_image(cue['text'], self.lang, self.skin, self.size, self.aspect, look, word,
                                         tuple(accent or self.skin.caption_accent)))
            bottom = self.size[1] * (.94 if self.aspect == '1:1' else 1046/1080)
            ink.paste(frame, image, (self.size[0]-image.width)/2, bottom-image.height)

    def _chrome(self, frame, t):
        span = self._chapter_span(t)
        if span is None or span[0]['kind'] in ('intro', 'outro'):
            return
        ch, a, b = span
        s, w, h = self.scale, *self.size
        alpha = min(1., (t-a)/.4, (b-t)/.3)
        # All glyphs are rendered from the saved skin fonts at the final size.
        def text(value, font_size, color, max_w):
            n = round(font_size*s)
            image = ui_text(value, n, color, self.skin.fonts)
            while image.width > max_w and n > 2:
                n -= 1
                image = ui_text(value, n, color, self.skin.fonts)
            return image
        label = chip_text(ch, self.lang)
        image = text(label, 32, self.skin.ink, w*.84)
        pad = round(22*s)
        tag = Image.new('RGBA', (image.width+2*pad, image.height+round(16*s)))
        d = ImageDraw.Draw(tag)
        col = ink.SECTION_COLORS.get(ch.get('color'))
        if self.skin.chapter_tag == 'chip':
            d.rounded_rectangle((0, 0, tag.width-1, tag.height-1), round(26*s),
                                fill=ink.rgba(col or (255,255,255)), outline=ink.rgba(col or (40,52,64)), width=max(1,round(3*s)))
            image = text(label, 32, (255,255,255) if col else (40,52,64), w*.84)
        else:
            image = text(label, 30, (255,253,245), w*.84)
            tw, th = image.width+round(64*s), round(56*s)
            tag = Image.new('RGBA', (tw, th))
            d = ImageDraw.Draw(tag)
            if self.skin.chapter_tag == 'bracket':
                skins._stepped(d, (0, 0, tw-1, th-1), (30,27,46,230), max(1,round(4*s)))
                for x, side in ((8*s, 1), (tw-12*s, -1)):
                    d.rectangle((x,8*s,x+3*s,23*s),fill='#E8C547')
                    d.rectangle((min(x,x+side*12*s),8*s,max(x+3*s,x+side*12*s),11*s),fill='#E8C547')
            else:
                d.polygon([(0,6*s),(15*s,16*s),(15*s,0),(tw-16*s,0),(tw-16*s,16*s),
                    (tw-1,6*s),(tw-1,th-7*s),(tw-16*s,th-17*s),(tw-16*s,th-1),
                    (15*s,th-1),(15*s,th-17*s),(0,th-7*s)],fill='#3B2418')
                d.rectangle((18*s,3*s,tw-19*s,th-4*s),fill='#F3E7CF')
                d.polygon([(3*s,11*s),(15*s,19*s),(15*s,th-20*s),(3*s,th-12*s)],fill='#F3E7CF')
                d.polygon([(tw-4*s,11*s),(tw-16*s,19*s),(tw-16*s,th-20*s),(tw-4*s,th-12*s)],fill='#F3E7CF')
            skins._draw_runs(d,label,(32*s,39*s),'ui',round(30*s),self.skin.fonts,
                             '#FFFDF5' if self.skin.chapter_tag == 'bracket' else '#3B2418')
        if self.skin.chapter_tag == 'chip':
            ink.paste(tag, image, pad, 8*s)
        ink.paste(frame, faded(tag, alpha), w*.04, h*.025)
        src = source_line(ch, self.lang)
        if src:
            image = text(src, 34, self.skin.soft, w*.84)
            ink.paste(frame, faded(image, alpha), w*.96-image.width,
                      h*.085 if self.aspect == '1:1' else h*.025)
        footer = self.ctx.T(self.ep.get('footer'))
        if footer:
            image = text(footer, 24, self.skin.faint, w*.84)
            ink.paste(frame, image, w*.04, h*.975-image.height)

    def _transition(self, t, kind, p, a, b):
        if kind != 'fly':
            return super()._transition(t, kind, p, a, b)
        note = self.notes[p['section']]
        tr = next(x for x in self.tl['transitions'] if x['section'] == p['section'])
        agenda = self.view(t, self.agenda_x+self._drift(t), hand=False)
        nx, sy, nw, nh = note['bbox']
        sx = nx-note['x']
        u = ease((t-a)/(b-a))
        tx, ty = note['pin_xy']
        tx -= self.agenda_x
        image = self._note_image(note, None, sx, sy, tr)
        scale = (nw+(note['mini'].width-nw)*u)/nw
        # A native note is reduced during its saved fly transition, never enlarged from 1080p.
        image = image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))), Image.Resampling.BILINEAR)
        ink.paste(agenda,image,sx+(tx-sx)*u,sy+(ty-sy)*u-60*self.scale*math.sin(math.pi*u))
        return agenda

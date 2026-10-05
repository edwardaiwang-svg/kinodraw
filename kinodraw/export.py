"""Atomic GIF/WebM exports and native-size generated frame rendering."""
from pathlib import Path
import subprocess
import tempfile

import imageio_ffmpeg

from .progress import RenderContext, wait_process

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


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
        cmd = [FFMPEG, '-y', '-v', 'error', '-i', str(source)]
        if audio is not None and output.suffix.lower() == '.webm':
            cmd += ['-i', str(audio)]
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
            FFMPEG, '-v', 'error', '-i', str(source), '-map', '0:v:0',
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


def native_production(episode, timing, lang, project, size, *, aspect='16:9'):
    """Native board export, separate from cinematic production/hybrid dispatch.

    Each beat gets a safe board with its saved visual instructions and caption.
    Text and SVG/shape builders generate at requested pixel dimensions. This
    deliberately does not reproduce production camera transitions or the hand.
    """
    from .engine import ink, scenes, skin
    from .engine.board import Layout
    from .engine.geometry import geometry_for_size
    from .engine.storyboard import normalize

    size = geometry_for_size(size, aspect).size
    scale = size[0] / (1080 if aspect in ('1:1', '9:16') else 1920)
    board = normalize(episode)
    look = skin.for_look(board.get('look'))

    class NativeContext(scenes.Ctx):
        # Builders keep canonical coordinates; factories retain native recipes.
        # No generated 1080 raster is ever used for the native vector output.
        def __init__(self, *args):
            super().__init__(*args)
            self.recipes = {}
            self.native = []

        def text(self, text, size, **kw):
            base = super().text(text, size, **kw)
            native = ink.TextDrawing(base.lines, lang, round(size * scale),
                color=kw.get('color') or ink.INK, align=kw.get('align', 'left'), fonts=self.fonts,
                min_dur=base.duration, max_dur=base.duration, pad=max(1, round(6 * scale)))
            # Ctx.text may shrink the requested font. Infer its actual metrics
            # from the recorded glyph font, then regenerate those glyphs.
            actual = base.placed[0][2] if base.placed else None
            if actual:
                for candidate in range(size, 1, -1):
                    if ink.hand_font(lang, candidate, self.fonts).getmetrics() == actual:
                        native = ink.TextDrawing(base.lines, lang, max(2, round(candidate * scale)),
                            color=kw.get('color') or ink.INK, align=kw.get('align', 'left'), fonts=self.fonts,
                            min_dur=base.duration, max_dur=base.duration, pad=max(1, round(6 * scale)))
                        break
            self.recipes[id(base)] = native
            return base

        def doodle(self, did, box, **kw):
            base = super().doodle(did, box, **kw)
            self.recipes[id(base)] = super().doodle(did, tuple(round(v * scale) for v in box), **kw)
            return base

        def strokes(self, size, polylines, color=None, width=6, fills=None, **kw):
            base = super().strokes(size, polylines, color=color, width=width, fills=fills, **kw)
            polys = [[(x * scale, y * scale) for x, y in poly] for poly in polylines]
            native_fills = None if fills is None else [
                ([(x * scale, y * scale) for x, y in poly], color) for poly, color in fills]
            self.recipes[id(base)] = super().strokes(tuple(round(v * scale) for v in size),
                polys, color=color, width=width * scale, fills=native_fills, **kw)
            return base

        def add(self, drawing, x, y, trigger, **kw):
            from .engine.board import Element
            base = super().add(drawing, x, y, trigger, **kw)
            native = self.recipes.get(id(drawing))
            if native is None:
                raise ValueError('native export requires a vector/text/source-picture factory')
            element = Element(self.skin.dress(native, base.x * scale, base.y * scale),
                              base.x * scale, base.y * scale, trigger, **kw)
            self.native.append(element)
            return base

    class NativeBoard:
        def __init__(self):
            self.size = tuple(size)
            self.warnings = []
            self.boards = []
            w, h = self.size
            canonical = geometry_for_size((round(w / scale), round(h / scale)), aspect)
            bw, bh = canonical.size
            margin = round(min(bw, bh) * .06)
            cap_h = round(bh * .18)
            for beat in board['beats']:
                info = timing['beats'][beat['id']]
                ctx = NativeContext(board, lang, timing, Layout(canonical), project, look)
                ctx.beat = beat
                ctx.text_w, ctx.text_h = bw - 2 * margin, bh - cap_h - 2 * margin
                visuals = beat.get('visuals', [])
                slots = max(1, len(visuals))
                if slots > 4:
                    raise ValueError('native board supports at most four visuals per beat')
                columns = 2 if slots > 1 else 1
                rows = 2 if slots > 2 else 1
                sw, sh = ctx.text_w // columns, ctx.text_h // rows
                for i, visual in enumerate(visuals):
                    builder = scenes.SLOT_BUILDERS.get(visual.get('type'))
                    if builder is None:
                        raise ValueError(f"native board unsupported visual: {visual.get('type')}")
                    box = (margin + (i % columns) * sw, margin + (i // columns) * sh,
                           sw - margin // 2, sh - margin // 2)
                    ctx.text_w, ctx.text_h = box[2], box[3]
                    builder(visual, beat, box, ctx)
                text = ctx.T(beat.get('display'))
                lines, font_size = ink.fit_text(text, lang, w - 2 * round(margin * scale), 3,
                                                round(min(w, h) * .045), min_size=2, fonts=look.fonts)
                caption = ink.TextDrawing(lines, lang, font_size, color=look.ink, fonts=look.fonts)
                while caption.size[1] > (cap_h - margin // 2) * scale and font_size > 2:
                    font_size -= 2
                    lines = ink.wrap_words(text, lang, font_size, w - 2 * round(margin * scale) - 12, fonts=look.fonts)
                    caption = ink.TextDrawing(lines, lang, font_size, color=look.ink, fonts=look.fonts)
                for el in ctx.native:
                    el.start = el.trigger
                    if not (0 <= el.x and el.x + el.w <= w and 0 <= el.y and el.y + el.h <= h * .82):
                        raise ValueError('native visual exceeds safe board; simplify visual')
                self.boards.append((info, ctx.native, caption))

        def frame(self, t):
            w, h = self.size
            image = look.background(w, h).copy()
            active = next(((info, els, cap) for info, els, cap in self.boards
                           if info['start'] <= t < info['end']), None)
            if active is None:
                return image
            info, elements, caption = active
            for el in sorted(elements, key=lambda e: e.layer):
                drawing, _, _ = el.state(t)
                if drawing is not None:
                    ink.paste(image, drawing, el.x, el.y)
            ink.paste(image, caption.ink, (w - caption.size[0]) / 2, h * .82)
            return image

    return NativeBoard()

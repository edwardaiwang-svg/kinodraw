// Automatic scenes (port of kinodraw/engine/auto_scenes.py): title board, agenda board, section opener,
// takeaway note, end card and the transition marks.
import { INK, SECTION_COLORS, StaticDrawing, TextDrawing, canvas, circlePoints, fitText } from './ink.js';
import { SOFT_INK, mix, sticky } from './scenes.js';

export const UI_DEFAULTS = { agenda: "What we'll cover", takeaway: 'KEY TAKEAWAY', sign: '', thanks: 'Thanks for watching' };
export const MAX_SECTIONS = 8;

export const ui = (ep) => ({ ...UI_DEFAULTS, ...(ep.ui?.en || {}) });

/** One line when it fits at >= 80% of `size`, otherwise two lines. */
export function fitTitle(text, maxW, size) {
  const [lines, fitted] = fitText(text, maxW, 1, size, Math.round(size * 0.8));
  if (lines.length === 1) return [lines, fitted];
  return fitText(text, maxW, 2, size, Math.round(size * 0.55));
}

/** Doodle id of the narrator in `pose`, or null when the narrator is turned off. */
export function narrator(ep, pose) {
  const prefix = ep.narrator ?? 'narrator';
  return !prefix || prefix === 'none' ? null : `${prefix}_${pose}`;
}

export function buildTitleBoard(ctx, beat, x0, t) {
  const ep = ctx.ep;
  const els = [];
  const [lines, size] = fitTitle(ctx.T(ep.title), 1150, 118);
  const title = new TextDrawing(lines, size, { color: INK });
  els.push(ctx.add(title, x0 + 80, 150, t));
  const tw = title.size[0];
  const und = ctx.strokes([tw, 30], [Array.from({ length: 31 }, (_, i) => [6 + i * (tw - 12) / 30, 12 + 5 * Math.sin(i / 2.5)])],
    { color: SECTION_COLORS.orange, width: 9, maxDur: 0.8 });
  els.push(ctx.add(und, x0 + 80, 150 + title.size[1] - 4, t));
  const dy = Math.trunc(size * 1.18) * (lines.length - 1);
  if (ep.subtitle) {
    els.push(ctx.add(ctx.text(ctx.T(ep.subtitle), 64, { color: SECTION_COLORS.blue, maxW: 1150, maxLines: 1 }), x0 + 86, 330 + dy, t));
  }
  if (ep.byline) els.push(ctx.add(ctx.text(ctx.T(ep.byline), 44, { color: SOFT_INK, maxW: 1150, maxLines: 1 }), x0 + 90, 430 + dy, t));
  const wave = narrator(ep, 'wave');
  if (wave) els.push(ctx.add(ctx.doodle(wave, [330, 500]), x0 + 1450, 250, t));
  return els;
}

/** Card boxes [dx, y, w, h] relative to the agenda page's left edge. */
export function agendaBoxes(n) {
  if (!(n >= 1 && n <= MAX_SECTIONS)) throw new Error(`${n} sections; the agenda supports 1–${MAX_SECTIONS}`);
  if (n <= 3) {
    const [w, gap] = [560, 60];
    const left = (1920 - (n * w + (n - 1) * gap)) / 2;
    return Array.from({ length: n }, (_, k) => [left + k * (w + gap), 200, w, 620]);
  }
  if (n === 4) return Array.from({ length: 4 }, (_, k) => [60 + k * 460, 200, 420, 620]);
  const cols = Math.ceil(n / 2);
  const w = (1800 - (cols - 1) * 40) / cols;
  return Array.from({ length: n }, (_, k) => {
    const [row, col] = [Math.floor(k / cols), k % cols];
    const inRow = row === 0 ? cols : n - cols;
    const left = (1920 - (inRow * w + (inRow - 1) * 40)) / 2;
    return [left + col * (w + 40), 190 + row * 330, w, 300];
  });
}

/** Agenda page; card k is drawn while agenda beat k (or the card's trigger) is spoken. */
export function buildAgenda(ctx, chapters, beats, x0) {
  const t0 = ctx.timeOf(beats[0], null);
  const title = ctx.text(ui(ctx.ep).agenda, 72, { color: INK, maxW: 1700, maxLines: 1 });
  ctx.add(title, x0 + (1920 - title.size[0]) / 2, 86, t0);
  const secs = chapters.filter((c) => c.kind === 'section');
  const cards = {};
  agendaBoxes(secs.length).forEach(([dx, cy, cw, chh], k) => {
    const ch = secs[k];
    const beat = beats[Math.min(k, beats.length - 1)];
    const t = ch.agenda_trigger ? ctx.timeOf(beat, ch.agenda_trigger) : ctx.timeOf(beat, null) + (k ? 0.2 : 1.4);
    const col = SECTION_COLORS[ch.color];
    const cx = x0 + dx;
    const rect = [[6, 6], [cw - 6, 6], [cw - 6, chh - 6], [6, chh - 6], [6, 6]];
    ctx.add(ctx.strokes([cw, chh], [rect], { color: col, width: 8, fills: [[rect.slice(0, -1), mix(col, 0.9)]], maxDur: 0.6 }), cx, cy, t);
    const first = ctx.elements.length;                  // everything written inside the card (for later marks)
    if (chh >= 600) {
      ctx.add(ctx.text(String(ch.number), 150, { color: col }), cx + 34, cy + 10, t);
      ctx.add(ctx.text(ctx.T(ch.label), 48, { color: col, maxW: cw - 190, maxLines: 1 }), cx + 150, cy + 60, t);
      const head = ctx.text(ctx.T(ch.title), 44, { maxW: cw - 60, maxLines: 2, minSize: 32, pace: 1.6 });
      ctx.add(head, cx + 34, cy + 200, t);
      const hookY = 200 + head.size[1] + 24;
      if (ch.hook) ctx.add(ctx.text(ctx.T(ch.hook), 56, { color: INK, maxW: cw - 60, maxLines: 2, minSize: 40, pace: 1.4 }), cx + 34, cy + hookY, t);
    } else {                                            // compact card (5–8 sections): number, label, title
      ctx.add(ctx.text(String(ch.number), 100, { color: col }), cx + 24, cy + 6, t);
      ctx.add(ctx.text(ctx.T(ch.label), 40, { color: col, maxW: cw - 130, maxLines: 1 }), cx + 110, cy + 36, t);
      ctx.add(ctx.text(ctx.T(ch.title), 40, { maxW: cw - 48, maxLines: 2, minSize: 28, pace: 1.6 }), cx + 24, cy + 124, t);
    }
    cards[ch.id] = { box: [cx, cy, cw, chh], color: col, els: ctx.elements.slice(first) };
  });
  return cards;
}

export function buildSectionOpener(ctx, chapter, beat, x0, t) {
  const col = SECTION_COLORS[chapter.color];
  const pose = narrator(ctx.ep, 'present');
  const textW = pose ? 820 : 1150;                      // the opener owns two columns; the narrator takes the right edge
  const big = ctx.text(ctx.T(chapter.label), 170, { color: col, maxW: textW, maxLines: 1 });
  const els = [ctx.add(big, x0 + 70, 70, t)];
  const title = ctx.text(ctx.T(chapter.title), 60, { maxW: textW, maxLines: 2 });
  els.push(ctx.add(title, x0 + 80, 70 + big.size[1] + 4, t));
  if (chapter.hook) {
    els.push(ctx.add(ctx.text(ctx.T(chapter.hook), 44, { color: SOFT_INK, maxW: textW, maxLines: 2 }), x0 + 84,
      70 + big.size[1] + title.size[1] + 30, t));
  }
  if (pose) els.push(ctx.add(ctx.doodle(pose, [330, 500]), x0 + 925, 330, t));
  return els;
}

/** Big sticky note with the section's takeaway headline; returns [note elements, bbox]. The note is laid down at
 * `t`; its label and headline are written as they are said (tLabel, tHead). */
export function buildTakeNote(ctx, beat, chapter, x0, t, tLabel = null, tHead = null) {
  const strings = ui(ctx.ep);
  const col = SECTION_COLORS[chapter.color];
  const [nw, nh] = [1240, 560];
  const [nx, ny] = [x0 + (1920 - nw) / 2, 150];
  const face = narrator(ctx.ep, 'head');
  const els = [ctx.add(sticky(ctx, nw, nh, { tape: col }), nx, ny, t, { essential: true })];
  const label = ctx.text(strings.takeaway, 44, { color: col });
  els.push(ctx.add(label, nx + 50, ny + 48, Math.max(t, tLabel ?? t), { essential: true }));
  const head = ctx.text(ctx.T(beat.take.headline), 76, { maxW: nw - (face ? 330 : 100), maxLines: 3, minSize: 52, pace: 0.9 });
  const written = ctx.add(head, nx + 50, ny + 48 + label.size[1] + 22, Math.max(t, tHead ?? t), { essential: true });
  els.push(written);
  if (face) els.push(ctx.add(ctx.doodle(face, [220, 220]), nx + nw - 250, ny + nh - 260, t + 0.01, { optional: true, after: written }));
  return [els, [nx, ny, nw, nh + 6]];
}

/** Closing page, written by the hand: title, thanks, thumbs-up narrator. */
export function buildEndCard(ctx, x0, t) {
  const ep = ctx.ep;
  const pose = narrator(ep, 'thumbs');
  const shift = pose ? 150 : 0;
  const [lines, size] = fitTitle(ctx.T(ep.title), 1150, 120);
  const brand = new TextDrawing(lines, size, { pace: 1.8 });
  const els = [ctx.add(brand, x0 + (1920 - brand.size[0]) / 2 - shift, 240, t)];
  const dy = Math.trunc(size * 1.18) * (lines.length - 1);
  const sub = new TextDrawing([ctx.T(ep.subtitle) || ui(ep).thanks], 60, { color: SECTION_COLORS.blue, pace: 1.8 });
  els.push(ctx.add(sub, x0 + (1920 - sub.size[0]) / 2 - shift, 400 + dy, t));
  if (pose) els.push(ctx.add(ctx.doodle(pose, [330, 500], { maxDur: 1.3 }), x0 + 1530, 260, t));
  return els;
}

/** Where a check mark fits inside a card without touching anything written there: [size, [x, y]]. */
export function checkSpot(box, obstacles, sizes = [150, 120, 96, 72], pad = 12) {
  const [x, y, w, h] = box;
  const clear = (r) => !obstacles.some((o) => r[0] < o[2] && o[0] < r[2] && r[1] < o[3] && o[1] < r[3]);
  for (const s of sizes) {
    for (const [sx, sy] of [[x + w - s - 20, y + 16], [x + w - s - 20, y + (h - s) / 2], [x + w - s - 20, y + h - s - 20], [x + 20, y + h - s - 20]]) {
      if (clear([sx - pad, sy - pad, sx + s + pad, sy + s + pad])) return [s, [sx, sy]];
    }
  }
  return [sizes[sizes.length - 1], [x + w - sizes[sizes.length - 1] - 20, y + 16]];
}

/** World bbox of what an element actually inks (text images carry padding and full line width). */
export function inkBbox(el) {
  const img = el.drawing.ink || el.drawing.color || el.drawing.image;
  if (!img) return null;
  const g = img.getContext ? img.getContext('2d') : null;
  if (!g) return [el.x, el.y, el.x + el.w, el.y + el.h];
  const { data, width, height } = g.getImageData(0, 0, img.width, img.height);
  let [x0, y0, x1, y1] = [width, height, -1, -1];
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * 4 + 3]) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  return x1 < 0 ? null : [el.x + x0, el.y + y0, el.x + x1 + 1, el.y + y1 + 1];
}

export function checkMark(ctx, col = [46, 157, 79], size = 150) {
  return ctx.strokes([size, size], [[[size * 0.12, size * 0.55], [size * 0.4, size * 0.82], [size * 0.9, size * 0.14]]],
    { color: col, width: 16, maxDur: 0.55 });
}

export function circleAround(ctx, box, col) {
  const [x, y, w, h] = box;
  const [W, H] = [w + 36, h + 36];
  const pts = circlePoints(W / 2, H / 2, W / 2 - 8, H / 2 - 8, { start: -2.3, turns: 1.04, n: 140, wobble: 0.008 });
  return [ctx.strokes([W, H], [pts], { color: col, width: 9, maxDur: 0.75 }), [x - 18, y - 18]];
}

export function pin(ctx, col = [229, 57, 53]) {
  const pts = circlePoints(22, 22, 16, 16, { n: 40 });
  return ctx.strokes([44, 44], [pts], { color: INK, width: 4, fills: [[pts, col]], maxDur: 0.25, pop: 0.1 });
}

/** An invisible 1-px-high anchor across a page: the camera pans to the whole page, not to its first drawing. */
export const pageAnchor = (width) => new StaticDrawing(canvas(width, 1), 0.01);

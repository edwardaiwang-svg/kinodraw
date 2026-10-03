// Visual builders (port of kinodraw/engine/scenes.py): turn storyboard visuals into scheduled board Elements.
// Each builder receives the visual `v`, the beat, a world `box` [x, y, w, h] and the build context `ctx`.
import { Element } from './board.js';
import { INK, NEUTRAL, TextDrawing, fitText, strokeDrawing } from './ink.js';

export const PAPER_NOTE = [255, 241, 118];
export const SOFT_INK = [85, 96, 106];
export const mix = (c, k = 0.5, base = [255, 255, 255]) => [0, 1, 2].map((i) => Math.trunc(c[i] * (1 - k) + base[i] * k));

export class Ctx {
  constructor(ep, timing, layout, svg) {
    Object.assign(this, { ep, timing, layout, svg, elements: [], registry: new Map(), color: NEUTRAL, chapter: null, beat: null });
  }

  T(pair, fallback = '') {
    if (pair == null) return fallback;
    if (typeof pair === 'string') return pair;
    return pair.en || fallback;
  }

  /** Absolute time when `trigger` (a substring of the spoken text) is heard. */
  timeOf(beat, trigger = null, fallback = null) {
    if (trigger && typeof trigger === 'object' && trigger.beat) beat = this.ep.beats.find((b) => b.id === trigger.beat);
    const info = this.timing.beats[beat.id];
    if (trigger) {
      const phrase = typeof trigger === 'object' ? trigger.en : trigger;
      if (phrase) {
        const pos = beat.spoken.en.indexOf(phrase);
        const ct = info.char_times;
        if (pos >= 0 && ct && ct.length) return info.start + ct[Math.min(pos, ct.length - 1)];
      }
    }
    return info.start + (fallback ?? 0.15);
  }

  text(s, size, { color = null, maxW = null, maxLines = 3, align = 'left', pace = 1.0, minSize = 28 } = {}) {
    let lines = [s];
    if (maxW) [lines, size] = fitText(s, maxW, maxLines, size, minSize);
    return new TextDrawing(lines, size, { color: color || INK, align, pace });
  }

  doodle(id, box, opts = {}) {
    return this.svg.drawing(this.svg.has(id) ? id : 'missing', box, opts);
  }

  strokes(size, polylines, { color = null, width = 6, fills = null, ...kw } = {}) {
    return strokeDrawing(size, polylines, { color: color || INK, width, closedFill: fills, ...kw });
  }

  add(drawing, x, y, trigger, opts = {}) {
    const el = new Element(drawing, x, y, trigger, opts);
    this.elements.push(el);
    return el;
  }

  register(vid, key, elements) {
    if (!vid) return;
    if (!this.registry.has(vid)) this.registry.set(vid, new Map());
    this.registry.get(vid).set(key, Array.isArray(elements) ? elements : [elements]);
  }
}

export function arrowPolys(x0, y0, x1, y1, { head = 18, bend = 0 } = {}) {
  const n = 24;
  const pts = [];
  const [mx, my] = [(x0 + x1) / 2, (y0 + y1) / 2];
  const [nx, ny] = [-(y1 - y0), x1 - x0];
  const ln = Math.hypot(nx, ny) || 1;
  const [cx, cy] = [mx + nx / ln * bend, my + ny / ln * bend];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    pts.push([(1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1]);
  }
  const [ex, ey] = pts[pts.length - 1];
  const [px, py] = pts[pts.length - 3];
  const ang = Math.atan2(ey - py, ex - px);
  return [pts, [[ex - head * Math.cos(ang - 0.45), ey - head * Math.sin(ang - 0.45)], [ex, ey],
    [ex - head * Math.cos(ang + 0.45), ey - head * Math.sin(ang + 0.45)]]];
}

/** 1-3 doodles, each in its own equal share of the box; labels never leave their share. */
export function buildCluster(v, beat, box, ctx) {
  const [x0, y0, w, h] = box;
  const items = (v.items || []).slice(0, 3);
  const n = Math.max(1, items.length);
  const rel = v.relation || 'none';
  const share = w / n;
  const labelH = items.some((it) => it.label) ? (share < 400 ? 116 : 70) : 0;
  const gap = rel !== 'none' && n > 1 ? 70 : 16;
  const d = Math.min(share - gap, h - labelH - 8, w <= 560 ? 320 : 360);
  const base = ctx.timeOf(beat, v.trigger);
  const made = [];
  items.forEach((it, i) => {
    const t = it.trigger ? ctx.timeOf(beat, it.trigger) : base;
    const cx = x0 + share * (i + 0.5);
    const dr = ctx.doodle(it.doodle, [d, d]);
    const el = ctx.add(dr, cx - dr.size[0] / 2, y0 + (h - labelH - dr.size[1]) / 2 + 4, t, { group: v.id || '' });
    const parts = [el];
    if (it.label) {
      const lab = ctx.text(ctx.T(it.label), 44, { maxW: share - 24, maxLines: 2, align: 'center', minSize: 30 });
      parts.push(ctx.add(lab, cx - lab.size[0] / 2, y0 + h - labelH + 4, t, { group: v.id || '' }));
    }
    ctx.register(v.id, i, parts);
    made.push(...parts);
    if (i < n - 1 && rel !== 'none') {
      const gx = x0 + share * (i + 1);                  // boundary between the two shares
      const gy = y0 + (h - labelH) / 2;
      if (rel === 'arrow') {
        const aw = Math.min(110, share - d + 30);
        const dr2 = ctx.strokes([aw, 60], arrowPolys(6, 34, aw - 10, 30, { bend: -10 }), { color: ctx.color, width: 7 });
        ctx.add(dr2, gx - aw / 2, gy - 30, t);
      } else {
        const glyph = { plus: '+', vs: 'VS', equals: '=' }[rel] || '→';
        const g = ctx.text(glyph, glyph !== 'VS' ? 60 : 48, { color: ctx.color });
        ctx.add(g, gx - g.size[0] / 2, gy - g.size[1] / 2, t);
      }
    }
  });
  ctx.register(v.id, 'all', made);
}

export function buildQuote(v, beat, box, ctx) {
  const [x0, y0, w] = box;
  const t = ctx.timeOf(beat, v.trigger);
  ctx.add(ctx.text('“', 150, { color: ctx.color }), x0 - 6, y0 - 34, t);
  const body = ctx.text(ctx.T(v.text), 46, { maxW: w - 110, maxLines: 4, pace: 1.25 });
  const bel = ctx.add(body, x0 + 90, y0 + 20, t);
  const who = ctx.text('— ' + ctx.T(v.who), 38, { color: ctx.color, maxW: w - 110, maxLines: 1 });
  const wel = ctx.add(who, x0 + 90, y0 + 30 + body.size[1], t);
  ctx.register(v.id, 'all', [bel, wel]);
  ctx.register(v.id, 0, [bel]);
}

export function sticky(ctx, w, h, { fill = PAPER_NOTE, tape = null } = {}) {
  const poly = [[8, 12], [w - 10, 8], [w - 6, h - 14], [12, h - 8], [8, 12]];
  const fills = [[poly.slice(0, -1), fill]];
  const lines = [poly];
  if (tape) {
    const tw = w * 0.32;
    const tp = [[w / 2 - tw / 2, -2], [w / 2 + tw / 2, 4], [w / 2 + tw / 2 - 4, 30], [w / 2 - tw / 2 - 2, 26], [w / 2 - tw / 2, -2]];
    fills.push([tp.slice(0, -1), mix(tape, 0.25)]);
    lines.push(tp);
  }
  return ctx.strokes([w, h + 6], lines, { width: 5, fills, maxDur: 1.1 });
}

export function buildGlossary(v, beat, box, ctx) {
  const [x0, y0, w, h] = box;
  const t = ctx.timeOf(beat, v.trigger);
  const [nw, nh] = [Math.min(w, 520), Math.min(h, 330)];
  const [nx, ny] = [x0 + (w - nw) / 2, y0 + (h - nh) / 2];
  const note = ctx.add(sticky(ctx, nw, nh, { tape: ctx.color }), nx, ny, t);
  const term = ctx.text(ctx.T(v.term), 46, { maxW: nw - 60, maxLines: 1, color: ctx.color, minSize: 34 });
  const tel = ctx.add(term, nx + 28, ny + 34, t);
  const body = ctx.text(ctx.T(v.text), 36, { maxW: nw - 60, maxLines: 4, pace: 1.4, minSize: 28 });
  const bel = ctx.add(body, nx + 28, ny + 40 + term.size[1], t);
  ctx.register(v.id, 'all', [note, tel, bel]);
  ctx.register(v.id, 0, [note]);
}

export function buildStat(v, beat, box, ctx) {
  const [x0, y0, w, h] = box;
  const t = ctx.timeOf(beat, v.trigger);
  const made = [];
  let tx = x0;
  if (v.doodle) {
    const dd = ctx.doodle(v.doodle, [200, 200]);
    made.push(ctx.add(dd, x0, y0 + (h - dd.size[1]) / 2 - 20, t));
    tx = x0 + 215;
  }
  // A wordy value ("more than a year") gets two smaller lines; value and label are centred together.
  let val = ctx.text(ctx.T(v.value), 110, { color: ctx.color, maxW: x0 + w - tx, maxLines: 1, minSize: 64 });
  if (val.lines.length > 1) val = ctx.text(ctx.T(v.value), 72, { color: ctx.color, maxW: x0 + w - tx, maxLines: 2, minSize: 40 });
  const lab = ctx.text(ctx.T(v.label), 42, { maxW: x0 + w - tx, maxLines: 2, minSize: 30 });
  const top = y0 + Math.max(0, (h - val.size[1] - 8 - lab.size[1]) / 2);
  const vel = ctx.add(val, tx, top, t);
  const lel = ctx.add(lab, tx, top + val.size[1] + 8, t);
  made.push(vel, lel);
  ctx.register(v.id, 0, [vel]);
  ctx.register(v.id, 'all', made);
}

export function pageTitle(ctx, v, box, t, key = 'title') {
  const [x0, y0, w] = box;
  if (!v[key]) return [null, y0];                        // (an empty title still takes its line, as in Python)
  const ttl = ctx.text(ctx.T(v[key]), 60, { color: ctx.color, maxW: w - 40, maxLines: 1, minSize: 40 });
  return [ctx.add(ttl, x0 + 10, y0, t), y0 + ttl.size[1] + 18];
}

export function footnote(ctx, v, box, t, key = 'footnote') {
  const [x0, y0, w, h] = box;
  if (!v[key]) return null;
  const fn = ctx.text(ctx.T(v[key]), 32, { color: SOFT_INK, maxW: w - 20, maxLines: 1, pace: 1.6, minSize: 26 });
  return ctx.add(fn, x0 + 10, y0 + h - fn.size[1], t);
}

export const SLOT_BUILDERS = { cluster: buildCluster, quote: buildQuote, glossary: buildGlossary, stat: buildStat };

// Full-board chart pages (port of kinodraw/engine/pages_time.py lanes, pages_quant.py bars + grid100, and
// pages_logic.py flow + split). Everything is drawn by the hand: outlines first, tints pop after, text glyph-traced.
// Only display strings from the visual are written; no numbers are computed.
import { INK, TextDrawing, circlePoints, fontMetrics, textWidth, wrapWords } from './ink.js';
import { SOFT_INK, arrowPolys, footnote, mix, pageTitle } from './scenes.js';

const CARD = [255, 255, 252];
const GUIDE = [150, 150, 150];
const LANE_ACCENTS = [null, [120, 144, 156], [142, 36, 170]];
const UP_GREEN = [67, 160, 71];
const DOWN_RED = [229, 57, 53];
const RED = [229, 57, 53];
const GLUE_AFTER = ['→', '(', '≥', '≤', '<', '>', '~', '≈', '“'];
const GLUE_BEFORE = ['→', ')', '%', '”'];

const when = (ctx, beat, item, fallback) => (item.trigger ? ctx.timeOf(beat, item.trigger) : fallback);
const blockH = (size, n) => { const [a, d] = fontMetrics(size); return Math.trunc(size * 1.18) * (n - 1) + a + d + 12; };

/** Wrap units that never split across lines: '$80 → $150'. */
function atoms(s) {
  const out = [];
  let glue = false;
  for (const u of s.match(/\S+\s*/g) || []) {
    const st = u.trim();
    if (out.length && (glue || GLUE_BEFORE.some((g) => st.startsWith(g)))) out[out.length - 1] += u;
    else out.push(u);
    glue = GLUE_AFTER.some((g) => st.endsWith(g));
  }
  return out;
}

function wrapAtoms(s, size, maxW) {
  const lines = [];
  let cur = '';
  for (const a of atoms(s)) {
    if (cur && textWidth((cur + a).trimEnd(), size) > maxW) {
      lines.push(cur.trimEnd());
      cur = a;
    } else {
      cur += a;
    }
  }
  if (cur.trim()) lines.push(cur.trimEnd());
  return lines.length ? lines : [''];
}

/** Handwritten block: the largest size (>= minSize) that fits maxW × maxH in maxLines, balanced (narrowest width with
 * the same line count). */
export function fitBlock(ctx, s, size, maxW, { maxH = null, maxLines = 3, minSize = 30, color = null, align = 'left', pace = 1.0 } = {}) {
  const fits = (lines, sz) => lines.length <= maxLines && (maxH === null || blockH(sz, lines.length) <= maxH)
    && Math.max(...lines.map((ln) => textWidth(ln, sz))) <= maxW;
  let choice = null;
  for (let sz = Math.trunc(size); sz >= Math.trunc(minSize); sz -= 2) {
    const lines = wrapAtoms(s, sz, maxW);
    const ok = fits(lines, sz);
    if (!ok && sz - 2 >= minSize) continue;
    let best = lines;
    for (let k = 0; k <= 10; k++) {                        // later = narrower; ties keep the narrower
      const cand = wrapAtoms(s, sz, maxW * (0.95 - 0.05 * k));
      if (cand.length !== lines.length) break;
      best = cand;
    }
    choice = [best, sz];
    break;
  }
  let [lines, sz] = choice;
  let grow = 1.1;
  while (lines.length > maxLines && grow < 4) {            // nothing fits: keep the line count, run wider
    lines = wrapAtoms(s, sz, maxW * grow);
    grow += 0.1;
  }
  const td = new TextDrawing(lines, sz, { color: color || INK, align, pace });
  td.fsize = sz;
  return td;
}

export function rrect(w, h, { r = 22, inset = 4 } = {}) {
  const [a, b, c, d] = [inset, inset, w - inset, h - inset];
  r = Math.min(r, (c - a) / 2, (d - b) / 2);
  const pts = [];
  const arc = (cx, cy, a0, a1) => { for (let k = 0; k < 9; k++) { const t = a0 + (a1 - a0) * k / 8; pts.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]); } };
  arc(a + r, b + r, Math.PI, 1.5 * Math.PI);
  arc(c - r, b + r, 1.5 * Math.PI, 2 * Math.PI);
  arc(c - r, d - r, 0, 0.5 * Math.PI);
  arc(a + r, d - r, 0.5 * Math.PI, Math.PI);
  pts.push(pts[0]);
  return pts;
}

export function dashes(x0, y0, x1, y1, on = 16, off = 12) {
  const length = Math.hypot(x1 - x0, y1 - y0);
  const n = Math.max(1, Math.trunc(length / (on + off)));
  const out = [];
  for (let k = 0; k <= n; k++) {
    const a = k * (on + off) / length;
    const b = Math.min(1, (k * (on + off) + on) / length);
    if (a >= 1) break;
    out.push([[x0 + (x1 - x0) * a, y0 + (y1 - y0) * a], [x0 + (x1 - x0) * b, y0 + (y1 - y0) * b]]);
  }
  return out;
}

/** 1-D label repel: left edges near their centres, no overlap, inside [lo, hi]. */
function spread(centers, widths, lo, hi, gap = 36) {
  const order = centers.map((c, i) => i).sort((a, b) => centers[a] - centers[b] || a - b);
  const left = {};
  for (const i of order) left[i] = Math.min(Math.max(centers[i] - widths[i] / 2, lo), hi - widths[i]);
  for (let k = 1; k < order.length; k++) left[order[k]] = Math.max(left[order[k]], left[order[k - 1]] + widths[order[k - 1]] + gap);
  if (order.length && left[order[order.length - 1]] + widths[order[order.length - 1]] > hi) {
    left[order[order.length - 1]] = hi - widths[order[order.length - 1]];
    for (let k = order.length - 1; k > 0; k--) left[order[k - 1]] = Math.min(left[order[k - 1]], left[order[k]] - gap - widths[order[k - 1]]);
  }
  return centers.map((_, i) => Math.max(lo, left[i]));
}

const dot = (ctx, r, color) => {
  const pts = circlePoints(r + 4, r + 4, r, r, { n: 40 });
  return ctx.strokes([2 * r + 8, 2 * r + 8], [pts], { width: 5, fills: [[pts, color]], maxDur: 0.5, pop: 0.12 });
};

// ================================================================== lanes (timeline)
/** Swim-lane timeline: stated events on ordinal positions, each written when its date is said. */
export function buildLanes(v, beat, box, ctx) {
  const [x0, y0, w, h] = box;
  const t0 = ctx.timeOf(beat, v.trigger);
  const [, top] = pageTitle(ctx, v, box, t0);
  const lanes = (v.lanes || []).slice(0, 3);
  const bottom = y0 + h - (v.footnote ? 56 : 0) - 6;
  const nl = Math.max(1, lanes.length);
  const gap = nl < 3 ? 20 : 12;
  const laneH = (bottom - top - gap * (nl - 1)) / nl;
  const labelled = lanes.some((ln) => ctx.T(ln.label).trim());
  const labW = labelled ? 340 : 0;
  const [lx0, lx1] = [x0 + labW + 44, x0 + w - 24];
  const [px0, px1] = [lx0 + 70, lx1 - 90];
  const dateSize = laneH >= 250 ? 52 : 44;
  const dateH = blockH(dateSize, 1);
  const everything = [];
  const events = [];
  const lineY = {};
  const blocks = {};
  const below = {};
  const laneT = {};
  const tints = {};
  // Event times first (untriggered events follow the previous one); never before the title.
  const laneEvs = [];
  const laneTs = [];
  let tPrev = t0 + 0.2;
  for (const lane of lanes) {
    const evs = [...(lane.events || [])].map((e, i) => [e, i]).sort((a, b) => Number(a[0].pos || 0) - Number(b[0].pos || 0) || a[1] - b[1]).map(([e]) => e);
    const ts = evs.map((ev) => {
      const te = Math.max(t0, when(ctx, beat, ev, tPrev + 0.5));
      tPrev = Math.max(tPrev, te);
      return te;
    });
    laneEvs.push(evs);
    laneTs.push(ts);
  }
  let tLane = t0;
  lanes.forEach((lane, i) => {
    let tl = t0 + 0.2 * i;
    if (i && laneTs[i - 1].length) tl = Math.max(tl, Math.min(...laneTs[i - 1]) + 0.05);
    if (lane.trigger) tl = ctx.timeOf(beat, lane.trigger);
    if (laneTs[i].length) tl = Math.min(tl, Math.min(...laneTs[i]) - 0.01);
    tLane = laneT[i] = Math.max(tLane, tl);
    laneTs[i] = laneTs[i].map((te) => Math.max(te, tLane));
  });
  const laneXs = laneEvs.map((evs) => evs.map((e) => px0 + Math.min(1, Math.max(0, Number(e.pos || 0))) * (px1 - px0)));
  const room = laneXs.map((xs) => xs.map((x, j) => {
    const left = j ? x - xs[j - 1] - 24 : 2 * (x - (lx0 - 10));
    const right = j + 1 < xs.length ? xs[j + 1] - x - 24 : 2 * (lx1 - 30 - x);
    return Math.max(220, Math.min(660, left, right));
  }));
  const bodyMaxH = laneH - dateH - 44;
  const uniform = (key, size, opts) => {
    const one = (ev, r, sz, lo) => {
      let d = fitBlock(ctx, ctx.T(ev[key]), sz, r, { minSize: lo, ...opts });
      if (opts.maxH && d.size[1] > opts.maxH) d = fitBlock(ctx, ctx.T(ev[key]), sz, r * 1.6, { minSize: lo, ...opts });
      return d;
    };
    const first = laneEvs.map((evs, i) => evs.map((ev, j) => one(ev, room[i][j], size, 40)));
    const sz = Math.min(...first.flat().map((d) => d.fsize), size);
    return laneEvs.map((evs, i) => evs.map((ev, j) => one(ev, room[i][j], sz, sz)));
  };
  const allDates = uniform('display', dateSize, { maxLines: 1, color: ctx.color, align: 'center' });
  const allBodies = uniform('label', 44, { maxH: bodyMaxH, maxLines: 3, align: 'center', pace: 1.2 });
  let k = 0;
  lanes.forEach((lane, i) => {
    const by = top + i * (laneH + gap);
    const accent = LANE_ACCENTS[i % LANE_ACCENTS.length] || ctx.color;
    const tl = laneT[i];
    tints[i] = mix(accent, 0.86);
    const bandPts = rrect(w - 8, laneH, { r: 26 });
    const laneEls = [ctx.add(ctx.strokes([w - 8, laneH], [bandPts], { color: mix(accent, 0.45), width: 4,
      fills: [[bandPts.slice(0, -1), tints[i]]], maxDur: 0.6 }), x0 + 4, by, tl)];
    if (labelled) {
      const lab = fitBlock(ctx, ctx.T(lane.label), 50, labW - 50, { maxH: laneH - 30, maxLines: 3, minSize: 40, pace: 1.4 });
      laneEls.push(ctx.add(lab, x0 + 34, by + (laneH - lab.size[1]) / 2, tl));
    }
    const [evs, xs, dates, bodies] = [laneEvs[i], laneXs[i], allDates[i], allBodies[i]];
    const dh = Math.max(dateH, ...dates.map((d) => d.size[1]));
    const bh = Math.max(0, ...bodies.map((b) => b.size[1]));
    let ly = by + (laneH + dh + 4 - bh) / 2;
    ly = Math.min(Math.max(ly, by + dh + 20), by + laneH - bh - 20);
    lineY[i] = ly;
    const arrow = ctx.strokes([lx1 - lx0 + 20, 44], arrowPolys(8, 22, lx1 - lx0 + 4, 22, { head: 24 }), { width: 6, maxDur: 0.5 });
    laneEls.push(ctx.add(arrow, lx0, ly - 22, tl));
    const labTop = ly + 18;
    const widths = dates.map((dd, j) => Math.max(dd.size[0], bodies[j].size[0]));
    const lefts = spread(xs, widths, lx0 - 10, lx1 - 30, 24);           // crowded events slide apart
    evs.forEach((ev, j) => {
      const [x, date, body] = [xs[j], dates[j], bodies[j]];
      const cx = lefts[j] + widths[j] / 2;
      const te = laneTs[i][j];
      const d = ctx.add(dot(ctx, 20, ctx.color), x - 24, ly - 24, te);
      const dx = cx - date.size[0] / 2;
      const del = ctx.add(date, dx, ly - 22 - date.size[1], te);
      const bx = cx - body.size[0] / 2;
      const bel = ctx.add(body, bx, labTop, te);
      const parts = [d, del, bel];
      if (!(bx + 24 <= x && x <= bx + body.size[0] - 24)) {           // label pushed off its dot: tie it back
        const [ya, yb] = [ly + 22, labTop + 12];
        const x2 = Math.min(Math.max(x, bx + 30), bx + body.size[0] - 30);
        const bx0 = Math.min(x, x2) - 6;
        parts.push(ctx.add(ctx.strokes([Math.abs(x2 - x) + 12, yb - ya + 12], [[[x - bx0, 6], [x2 - bx0, yb - ya + 6]]],
          { color: ctx.color, width: 4, maxDur: 0.3 }), bx0, ya - 6, te));
      }
      (blocks[i] ??= []).push([bx, bx + body.size[0]], [dx, dx + date.size[0]]);
      (below[i] ??= []).push([bx, bx + body.size[0], bel.y + bel.h]);
      events.push([i, x, te]);
      ctx.register(v.id, k, parts);
      laneEls.push(...parts);
      k += 1;
    });
    ctx.register(v.id, `lane${i}`, laneEls);
    everything.push(...laneEls);
  });
  const ring = 16;                                   // time guides, downward only, to the lane below
  for (const [i, x, te] of events) {
    const q = i + 1;
    if (!(q in lineY) || (blocks[q] || []).some(([a, b]) => a - 8 - ring <= x && x <= b + 8 + ring)) continue;
    const ya = Math.max(...(below[i] || []).filter(([a0, a1]) => a0 - 8 <= x && x <= a1 + 8).map(([, , b]) => b), lineY[i] + 24) + 4;
    const yb = lineY[q] - ring - 2;
    if (yb - ya < 30) continue;
    const tg = Math.max(te, laneT[q]) + 0.05;
    const g = ctx.add(ctx.strokes([32, yb - ya + 8], dashes(16, 4, 16, yb - ya + 4, 14, 12), { color: GUIDE, width: 4, maxDur: 0.5 }), x - 16, ya - 4, tg);
    const rp = circlePoints(ring + 4, ring + 4, ring, ring, { n: 32 });
    const rg = ctx.add(ctx.strokes([2 * ring + 8, 2 * ring + 8], [rp], { color: GUIDE, width: 4, fills: [[rp, tints[q]]], maxDur: 0.3 }),
      x - ring - 4, lineY[q] - ring - 4, tg);
    everything.push(g, rg);
  }
  ctx.register(v.id, 'all', everything);
  footnote(ctx, v, box, tPrev + 0.5);
}

// ================================================================== grid100 and bars
const fitsText = (s, size, maxW, maxLines) => {
  const lines = wrapWords(s, size, maxW);
  return lines.length <= maxLines && lines.every((ln) => textWidth(ln, size) <= maxW);
};

/** Sibling texts at ONE shared size: the largest that fits every string. */
function fitAll(ctx, strings, size, maxWs, { maxLines = 1, minSize = 40, colors = null, floor = 32, ...kw } = {}) {
  const ss = strings.map((s) => ctx.T(s));
  const ws = Array.isArray(maxWs) ? maxWs : ss.map(() => maxWs);
  while (size > Math.min(minSize, floor) && !ss.every((s, i) => !s || fitsText(s, size, ws[i], maxLines))) size -= 2;
  const cs = colors || ss.map(() => kw.color || null);
  return ss.map((s, i) => ctx.text(s, size, { maxW: ws[i], maxLines, minSize: size, color: cs[i], align: kw.align, pace: kw.pace }));
}

const contentBottom = (fn, box) => (fn ? fn.y - 16 : box[1] + box[3]);

function rectDrawing(ctx, w, h, fill, { color = null, width = 5, openBottom = false, maxDur = 1.0 } = {}) {
  const p = width;
  const pts = [[p, h + p], [p, p], [w + p, p], [w + p, h + p]];
  if (!openBottom) pts.push([p, h + p]);
  return ctx.strokes([w + 2 * p, h + 2 * p], [pts], { color, width, fills: fill ? [[[[p, h + p], [p, p], [w + p, p], [w + p, h + p]], fill]] : null, maxDur });
}

function blockArrow(ctx, aw, ah, up, color) {
  const p = 7;
  const [sw, hh, cx] = [aw * 0.46, Math.min(ah * 0.45, aw * 0.95), aw / 2 + p];
  let pts = [[cx - sw / 2, ah + p], [cx - sw / 2, hh + p], [p, hh + p], [cx, p], [aw + p, hh + p], [cx + sw / 2, hh + p],
    [cx + sw / 2, ah + p], [cx - sw / 2, ah + p]];
  if (!up) pts = pts.map(([x, y]) => [x, ah + 2 * p - y]);
  return ctx.strokes([aw + 2 * p, ah + 2 * p], [pts], { width: 6, fills: [[pts.slice(0, -1), color]], maxDur: 0.9 });
}

export function buildBars(v, beat, box, ctx) {
  const [x0, y0, w, h] = box;
  const t0 = ctx.timeOf(beat, v.trigger);
  const rows = (v.rows || []).slice(0, 6);
  if (!rows.length) return;
  const ts = rows.map((r, i) => when(ctx, beat, r, t0 + 0.5 + 0.4 * i));
  const tEnd = Math.max(...ts) + 0.3;
  let [, top] = pageTitle(ctx, v, box, t0);
  const fn = footnote(ctx, v, box, tEnd);
  const bottom = contentBottom(fn, box);
  if (v.unit) {
    const u = ctx.text(ctx.T(v.unit), 42, { color: SOFT_INK, maxW: w * 0.55, maxLines: 1, pace: 1.5, minSize: 40 });
    ctx.add(u, x0 + 10, top - 6, t0);
    top += u.size[1] - 2;
  }
  const [areaX0, areaX1] = [x0 + 10, x0 + w - 10];
  const n = rows.length;
  const arrowW = n >= 2 ? Math.trunc(Math.min(150, Math.max(90, (areaX1 - areaX0) * 0.17))) : 0;
  const [bx0, bx1] = [areaX0, areaX1 - (arrowW ? arrowW + 40 : 0)];
  const slot = Math.min((bx1 - bx0) / n, 440);
  const gx0 = bx0 + (bx1 - bx0 - slot * n) / 2;
  const bw = Math.min(230, slot * 0.6);
  const labS = rows.map((r) => ctx.T(r.label));
  const one = labS.every((s) => !s || fitsText(s, 40, slot - 24, 1));
  const labels = fitAll(ctx, labS, 44, slot - 24, { maxLines: one ? 1 : 2, align: 'center', pace: 1.4 });
  const baseline = bottom - Math.max(...labels.map((lb) => lb.size[1])) - 12;
  const valSize = n <= 3 ? 72 : n === 4 ? 60 : 50;
  const hl = rows.map((r) => Boolean(r.highlight));
  if (!hl.some(Boolean)) hl[hl.length - 1] = true;
  const values = fitAll(ctx, rows.map((r) => r.display), valSize, slot - 20, { align: 'center', colors: hl.map((k) => (k ? ctx.color : INK)) });
  const hmax = baseline - (top + Math.max(...values.map((vl) => vl.size[1])) + 22);
  const vals = rows.map((r) => Math.max(0, Number(r.value || 0)));
  const vmax = Math.max(...vals) || 1;
  const [ax0, ax1] = [gx0 - 30, gx0 + slot * n + 30];
  const made = [ctx.add(ctx.strokes([ax1 - ax0, 16], [[[6, 8], [ax1 - ax0 - 6, 8]]], { width: 5, maxDur: 0.5 }), ax0, baseline - 8, t0)];
  rows.forEach((r, i) => {
    const cx = gx0 + slot * (i + 0.5);
    const bh = vals[i] <= 0 ? 0 : Math.max(10, vals[i] / vmax * hmax);
    const parts = [];
    if (bh) parts.push(ctx.add(rectDrawing(ctx, bw, bh, hl[i] ? ctx.color : mix(ctx.color, 0.6), { openBottom: true }), cx - bw / 2 - 5, baseline - bh - 5, ts[i]));
    parts.push(ctx.add(values[i], cx - values[i].size[0] / 2, baseline - bh - 10 - values[i].size[1], ts[i]));
    parts.push(ctx.add(labels[i], cx - labels[i].size[0] / 2, baseline + 10, ts[i]));
    ctx.register(v.id, i, parts);
    made.push(...parts);
  });
  if (arrowW && vals[vals.length - 1] !== vals[0]) {
    const up = vals[vals.length - 1] > vals[0];
    const ah = Math.min(300, baseline - top - 40);
    made.push(ctx.add(blockArrow(ctx, arrowW - 14, ah, up, up ? UP_GREEN : DOWN_RED), gx0 + slot * n + 40, top + (baseline - top - ah) / 2, Math.max(...ts) + 0.1));
  }
  ctx.register(v.id, 'all', made);
}

function squareMarks(ctx, cells, cell) {
  const inset = 5;
  const lines = [];
  const fills = [];
  for (const k of cells) {
    const [r, c] = [Math.floor(k / 10), k % 10];
    const [a, b, s] = [c * cell + inset, r * cell + inset, cell - 2 * inset];
    const sq = [[a, b], [a + s, b], [a + s, b + s], [a, b + s]];
    lines.push([...sq, sq[0]]);
    fills.push([sq, ctx.color]);
  }
  return ctx.strokes([cell * 10 + 8, cell * 10 + 8], lines, { color: ctx.color, width: 4, fills, maxDur: Math.min(2.0, 0.5 + 0.08 * cells.length) });
}

function swatch(ctx, s) {
  const p = 5;
  const sq = [[p, p], [s + p, p], [s + p, s + p], [p, s + p]];
  return ctx.strokes([s + 2 * p, s + 2 * p], [[...sq, sq[0]]], { color: ctx.color, width: 4, fills: [[sq, ctx.color]], maxDur: 0.4 });
}

export function buildGrid100(v, beat, box, ctx) {
  const [x0, , w] = box;
  const t0 = ctx.timeOf(beat, v.trigger);
  const legend = v.legend || [];
  const times = legend.map((it, i) => when(ctx, beat, it, t0 + 1 + 0.5 * i));
  const tf = v.fill_trigger ? ctx.timeOf(beat, v.fill_trigger) : t0 + 0.3;
  const [, top] = pageTitle(ctx, v, box, t0);
  const bottom = contentBottom(footnote(ctx, v, box, Math.max(...times, tf) + 0.3), box);
  const filled = Math.max(0, Math.min(100, Math.trunc(v.filled || 0)));
  const side = Math.trunc(Math.floor(Math.min(bottom - top - 16, 640) / 10) * 10);
  const cell = side / 10;
  const [gx, gy] = [x0 + 50, top + (bottom - top - side) / 2];
  const frame = [[4, 4], [side + 4, 4], [side + 4, side + 4], [4, side + 4], [4, 4]];
  const fr = ctx.add(ctx.strokes([side + 8, side + 8], [frame], { width: 5, fills: [[frame.slice(0, -1), CARD]], maxDur: 0.8 }), gx - 4, gy - 4, t0);
  const inner = [];
  for (let k = 1; k < 10; k++) inner.push([[cell * k + 4, 4], [cell * k + 4, side + 4]], [[4, cell * k + 4], [side + 4, cell * k + 4]]);
  const gl = ctx.add(ctx.strokes([side + 8, side + 8], inner, { color: [150, 150, 150], width: 3, maxDur: 1.0 }), gx - 4, gy - 4, t0);
  const made = [fr, gl];
  const [lx0, lx1] = [gx + side + 100, x0 + w - 20];
  const items = [];
  if (v.doodle) {
    const dd = ctx.doodle(v.doodle, [Math.min(420, lx1 - lx0), 270]);
    items.push([dd.size[1], [[dd, 0, 0]], Math.max(...times, tf) + 0.1, null]);
  }
  const swS = 60;
  legend.forEach((it, i) => {
    const pieces = it.swatch === 'filled' ? [[swatch(ctx, swS), 0]] : [];
    const tx = pieces.length ? swS + 34 : 0;
    const txt = fitAll(ctx, [it.text], 56, lx1 - lx0 - tx, { maxLines: 2, minSize: 40, pace: 1.2 })[0];
    const hh = Math.max(txt.size[1], swS + 10);
    items.push([hh, [...pieces, [txt, tx]].map(([d, dx]) => [d, dx, (hh - d.size[1]) / 2]), times[i], i]);
  });
  const gap = 46;
  const total = items.reduce((a, it) => a + it[0], 0) + gap * Math.max(0, items.length - 1);
  let cy = top + Math.max(0, (bottom - top - total) / 2);
  for (const [hh, placed, ti, key] of items) {
    const els = placed.map(([d, dx, dy]) => ctx.add(d, lx0 + dx, cy + dy, ti));
    if (key !== null) ctx.register(v.id, key, els);
    made.push(...els);
    cy += hh + gap;
  }
  if (filled) {                                     // the number is written as it is said, then the grid fills
    const fe = ctx.add(squareMarks(ctx, Array.from({ length: filled }, (_, k) => k), cell), gx, gy, tf, { layer: 1 });
    made.push(fe);
  }
  ctx.register(v.id, 'all', made);
}

// ================================================================== flow and split
function worldStrokes(ctx, polys, { color = null, width = 6, fills = null, pad = 10, ...kw } = {}) {
  const pts = [...polys.flat(), ...(fills || []).flatMap(([p]) => p)];
  const bx = Math.min(...pts.map((p) => p[0])) - pad - width;
  const by = Math.min(...pts.map((p) => p[1])) - pad - width;
  const bw = Math.max(...pts.map((p) => p[0])) - bx + pad + width;
  const bh = Math.max(...pts.map((p) => p[1])) - by + pad + width;
  const loc = (poly) => poly.map(([x, y]) => [x - bx, y - by]);
  const dr = ctx.strokes([bw, bh], polys.map(loc), { color, width, fills: fills ? fills.map(([p, c]) => [loc(p), c]) : null, ...kw });
  return [dr, bx, by];
}

function put(ctx, polys, t, { color = null, width = 6, fills = null, layer = 0, after = null, ...kw } = {}) {
  const [dr, x, y] = worldStrokes(ctx, polys, { color, width, fills, ...kw });
  return ctx.add(dr, x, y, t, { layer, after });
}

/** ctx.text with balanced line breaks (same line count, narrowest width): no orphan words. */
function balancedText(ctx, s, size, maxW, { maxLines = 3, color = null, align = 'left', pace = 1.0, minSize = 40 } = {}) {
  const [lines0, sz] = [wrapWords(s, size, maxW), size];
  let [lines, fsize] = [lines0, sz];
  for (fsize = size; fsize > minSize && wrapWords(s, fsize, maxW).length > maxLines; fsize -= 2);
  lines = wrapWords(s, fsize, maxW);
  if (lines.length > 1) {
    let [lo, hi] = [maxW * 0.4, maxW];
    for (let k = 0; k < 12; k++) {
      const mid = (lo + hi) / 2;
      if (wrapWords(s, fsize, mid).length <= lines.length) hi = mid; else lo = mid;
    }
    lines = wrapWords(s, fsize, hi);
  }
  return new TextDrawing(lines, fsize, { color: color || INK, align, pace });
}

const exitDist = (size, ux, uy, pad = 16) => Math.min(Math.abs(ux) > 1e-6 ? size[0] / 2 / Math.abs(ux) : 1e9,
  Math.abs(uy) > 1e-6 ? size[1] / 2 / Math.abs(uy) : 1e9) + pad;
const overlap = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
const NEGATED = /^\s*(?:(?:does|do|did|is|are|was|were)\s+not|doesn't|don't|didn't|isn't|aren't|not|never)\b/;

/** Arrow from node a to node b, bowed away from the centre; a blocked edge is grey and struck through in red. */
function edge(ctx, pa, pb, sa, sb, center, t, box, avoid, { label = null, k = 0.16, width = 9, head = 26, labelIn = true, maxBend = 1e9, blocked = false } = {}) {
  const [dx, dy] = [pb[0] - pa[0], pb[1] - pa[1]];
  const d = Math.hypot(dx, dy) || 1;
  const [ux, uy] = [dx / d, dy / d];
  let [ra, rb] = [exitDist(sa, ux, uy), exitDist(sb, ux, uy)];
  if (d - ra - rb < 70) {
    const f = Math.max(0, d - 70) / (ra + rb);
    ra *= f;
    rb *= f;
  }
  const [sx, sy, ex, ey] = [pa[0] + ux * ra, pa[1] + uy * ra, pb[0] - ux * rb, pb[1] - uy * rb];
  const L = Math.hypot(ex - sx, ey - sy);
  const [nx, ny] = [-uy, ux];
  const [mx, my] = [(sx + ex) / 2, (sy + ey) / 2];
  const out = (mx - center[0]) * nx + (my - center[1]) * ny > 0 ? 1 : -1;
  const bend = out * Math.max(0, Math.min(k * L, maxBend));
  const els = [put(ctx, arrowPolys(sx, sy, ex, ey, { head, bend }), t, { color: blocked ? SOFT_INK : ctx.color, width, maxDur: 0.8 })];
  const [px, py] = [mx + nx * bend / 2, my + ny * bend / 2];
  let gap = 14 + width;
  if (blocked) {
    const s = 22;
    els.push(put(ctx, [[[px - s, py - s], [px + s, py + s]], [[px + s, py - s], [px - s, py + s]]], t, { color: RED, width: 11, maxDur: 0.4, after: els[0] }));
    avoid.push([px - s, py - s, px + s, py + s]);
    gap = 14 + s + 6;
  }
  if (label) {
    const sym = label.trim().length === 1 && !/[a-z0-9]/i.test(label.trim());
    const lab = balancedText(ctx, label, sym ? 64 : 44, 300, { color: blocked ? RED : ctx.color, maxLines: 2, align: 'center', pace: 1.3 });
    const [lw, lh] = lab.size;
    const ext = Math.abs(nx) * lw / 2 + Math.abs(ny) * lh / 2;
    const [x0, y0, w, h] = box;
    let best = null;
    for (const side of labelIn ? [-out, out] : [out, -out]) {
      const [cx, cy] = [px + nx * side * (gap + ext), py + ny * side * (gap + ext)];
      const bx = Math.min(Math.max(cx - lw / 2, x0), x0 + w - lw);
      const by = Math.min(Math.max(cy - lh / 2, y0), y0 + h - lh);
      const bb = [bx, by, bx + lw, by + lh];
      const cost = avoid.reduce((a, o) => a + overlap(bb, o), 0);
      if (!best || cost < best[0]) best = [cost, bb];
      if (cost === 0) break;
    }
    avoid.push(best[1]);
    els.push(ctx.add(lab, best[1][0], best[1][1], t, { after: els[els.length - 1] }));
  }
  return els;
}

function chainLayout(ctx, nodes, box, top, dmax) {
  const [x0, y0, w, h] = box;
  const n = nodes.length;
  const pitch = (w - 20) / n;
  let D = Math.min(300, pitch - Math.max(110, 0.3 * pitch));
  const size = n <= 4 ? 46 : 40;
  const labs = nodes.map((nd) => (nd.label ? balancedText(ctx, ctx.T(nd.label), size, pitch - 24, { maxLines: 3, align: 'center', pace: 1.3 }) : null));
  const labH = Math.max(0, ...labs.filter(Boolean).map((l) => l.size[1]));
  const avail = y0 + h - top;
  D = Math.max(120, Math.min(D, avail - 20 - labH));
  const yd = top + Math.max(0, (avail - (D + 20 + labH)) / 2 - 10);
  const dds = nodes.map((nd, i) => (nd.doodle ? ctx.doodle(nd.doodle, [D, D], { maxDur: dmax[i] }) : null));
  const pos = labs.map((lab, i) => {
    const cx = x0 + 10 + pitch * (i + 0.5);
    return [[cx, yd + D / 2], lab ? [cx - lab.size[0] / 2, yd + D + 20] : null];
  });
  return [dds, labs, pos, [x0 + w / 2, y0 + h + 400]];
}

function loopLayout(ctx, nodes, box, top, dmax) {
  const [x0, y0, w, h] = box;
  const n = nodes.length;
  const D = n <= 4 ? 260 : 180;
  const size = n <= 4 ? 46 : 40;
  const th = nodes.map((_, i) => -Math.PI / 2 - Math.PI / n + 2 * Math.PI * i / n);
  const cs = th.map(Math.cos);
  const ss = th.map(Math.sin);
  const side = cs.map((c, i) => (c < -0.45 ? 'left' : c > 0.45 ? 'right' : ss[i] < 0 ? 'top' : 'bottom'));
  const labs = nodes.map((nd, i) => {
    if (!nd.label) return null;
    const horiz = side[i] === 'left' || side[i] === 'right';
    return balancedText(ctx, ctx.T(nd.label), size, horiz ? 390 : 460, { maxLines: 3, align: { left: 'right', right: 'left' }[side[i]] || 'center', pace: 1.3 });
  });
  const dds = nodes.map((nd, i) => (nd.doodle ? ctx.doodle(nd.doodle, [D, D], { maxDur: dmax[i] }) : null));
  const sizes = dds.map((dd) => (dd ? dd.size : [60, 60]));
  const extTop = Math.max(0, ...labs.map((l, i) => (l && side[i] === 'top' ? l.size[1] + 14 - (D - sizes[i][1]) / 2 : 0)));
  const extBot = Math.max(0, ...labs.map((l, i) => (l && side[i] === 'bottom' ? l.size[1] + 14 - (D - sizes[i][1]) / 2 : 0)));
  const extX = Math.max(0, ...labs.map((l, i) => (l && (side[i] === 'left' || side[i] === 'right') ? l.size[0] + 24 : 0)));
  const [ya, yb] = [top + Math.max(0, extTop) + D / 2 + 8, y0 + h - Math.max(0, extBot) - D / 2 - 8];
  const [s0, s1] = [Math.min(...ss), Math.max(...ss)];
  const cmax = Math.max(...cs.map(Math.abs)) || 1;
  const half = Math.min(w / 2 - 20 - D / 2 - extX, (yb - ya) * 1.6);
  const cxl = x0 + w / 2;
  const pos = labs.map((lab, i) => {
    const px = cxl + cs[i] / cmax * half;
    const py = ya + (ss[i] - s0) / (s1 - s0) * (yb - ya);
    const [dw, dh] = sizes[i];
    let lp = null;
    if (lab) {
      lp = side[i] === 'left' ? [px - dw / 2 - 24 - lab.size[0], py - lab.size[1] / 2]
        : side[i] === 'right' ? [px + dw / 2 + 24, py - lab.size[1] / 2]
          : side[i] === 'top' ? [px - lab.size[0] / 2, py - dh / 2 - 14 - lab.size[1]] : [px - lab.size[0] / 2, py + dh / 2 + 14];
    }
    return [[px, py], lp];
  });
  return [dds, labs, pos, [cxl, (ya + yb) / 2]];
}

/** Cause-and-effect diagram: doodle nodes joined by arrows; chain (row) or loop (cycle). */
export function buildFlow(v, beat, box, ctx) {
  const t0 = ctx.timeOf(beat, v.trigger);
  const [, top] = pageTitle(ctx, v, box, t0);
  const nodes = (v.nodes || []).slice(0, 6);
  const n = nodes.length;
  if (!n) return;
  const loop = v.layout === 'loop' && n >= 3;
  const ids = new Map(nodes.map((nd, i) => [String(nd.id ?? i), i]));
  let edges = [];
  for (const e of v.edges || []) {
    const [a, b] = [ids.get(String(e.from)), ids.get(String(e.to))];
    if (a !== undefined && b !== undefined && a !== b) {
      const lab = e.label ? ctx.T(e.label) : null;
      edges.push([a, b, lab, Boolean(lab) && NEGATED.test(lab)]);
    }
  }
  if (!v.edges) edges = [...Array.from({ length: n - 1 }, (_, i) => [i, i + 1, null, false]), ...(loop ? [[n - 1, 0, null, false]] : [])];
  const times = nodes.map((nd, i) => when(ctx, beat, nd, t0 + 0.4 * i));
  const order = nodes.map((_, i) => i).sort((a, b) => times[a] - times[b] || a - b);
  const info = ctx.timing.beats[beat.id];
  const end = info.speech_end ?? info.end ?? times[order[n - 1]] + 4;
  const nxt = {};
  order.forEach((i, j) => { nxt[i] = j + 1 < n ? times[order[j + 1]] : Math.max(end, times[i] + 2); });
  const dmax = nodes.map((_, i) => Math.min(2.4, Math.max(0.9, nxt[i] - times[i] - 1.8)));
  const lbox = [box[0], box[1], box[2], box[3] - (v.footnote ? 56 : 0)];
  const [dds, labs, pos, center] = (loop ? loopLayout : chainLayout)(ctx, nodes, lbox, top, dmax);
  const sizes = dds.map((dd) => (dd ? dd.size : [60, 60]));
  const avoid = [];
  pos.forEach(([[px, py], lp], i) => {
    avoid.push([px - sizes[i][0] / 2, py - sizes[i][1] / 2, px + sizes[i][0] / 2, py + sizes[i][1] / 2]);
    if (labs[i]) avoid.push([lp[0], lp[1], lp[0] + labs[i].size[0], lp[1] + labs[i].size[1]]);
  });
  const ebox = [box[0], top, box[2], lbox[1] + lbox[3] - top];
  const drawn = new Set();
  const done = new Set();
  const made = [];
  const drawEdge = (k, t) => {
    const [a, b, lab, neg] = edges[k];
    let [[pa], [pb]] = [pos[a], pos[b]];
    let els;
    if (!loop && Math.abs(a - b) > 1) {                  // chain skip-edge: arching over the row
      pa = [pa[0], pa[1] - sizes[a][1] / 2 - 6];
      pb = [pb[0], pb[1] - sizes[b][1] / 2 - 6];
      const room = Math.min(pa[1], pb[1]) - top - (lab ? 80 : 14);
      els = edge(ctx, pa, pb, [0, 0], [0, 0], center, t, ebox, avoid, { label: lab, k: 0.28, labelIn: false, maxBend: 2 * room, blocked: neg });
    } else {
      els = edge(ctx, pa, pb, sizes[a], sizes[b], center, t, ebox, avoid, { label: lab, k: loop ? 0.16 : 0.04, labelIn: loop, blocked: neg });
    }
    done.add(k);
    made.push(...els);
  };
  for (const i of order) {
    const t = times[i];
    const [[px, py], lp] = pos[i];
    edges.forEach(([a, b], k) => { if (b === i && drawn.has(a) && !done.has(k)) drawEdge(k, t); });
    const parts = [];
    if (dds[i]) parts.push(ctx.add(dds[i], px - sizes[i][0] / 2, py - sizes[i][1] / 2, t));
    else {
      const ring = circlePoints(px, py, 26, 26, { n: 40 });
      parts.push(put(ctx, [ring], t, { width: 6, fills: [[ring, mix(ctx.color, 0.4)]], maxDur: 0.5 }));
    }
    if (labs[i]) parts.push(ctx.add(labs[i], lp[0], lp[1], t));
    ctx.register(v.id, i, parts);
    made.push(...parts);
    drawn.add(i);
    edges.forEach(([a, b], k) => { if (a === i && drawn.has(b) && !done.has(k)) drawEdge(k, t); });
  }
  const fn = footnote(ctx, v, box, times[order[n - 1]] + 0.5);
  if (fn) made.push(fn);
  ctx.register(v.id, 'all', made);
}

function bubble(x, y, w, h, tailX, r = 30, tail = 36) {
  const pts = [];
  const corner = (cx, cy, a0, a1) => { for (let k = 0; k < 8; k++) { const a = a0 + (a1 - a0) * k / 7; pts.push([x + cx + r * Math.cos(a), y + cy + r * Math.sin(a)]); } };
  corner(r, tail + r, Math.PI, 1.5 * Math.PI);
  const tx = Math.min(Math.max(tailX - x, r + 30), w - r - 30);
  pts.push([x + tx - 28, y + tail], [x + tx - 6, y], [x + tx + 28, y + tail]);
  corner(w - r, tail + r, 1.5 * Math.PI, 2 * Math.PI);
  corner(w - r, tail + h - r, 0, 0.5 * Math.PI);
  corner(r, tail + h - r, 0.5 * Math.PI, Math.PI);
  pts.push(pts[0]);
  return pts;
}

/** Two views side by side (who + doodle + speech bubble), optional verdict banner. */
export function buildSplit(v, beat, box, ctx) {
  const [x0, y0, w, h] = box;
  const t0 = ctx.timeOf(beat, v.trigger);
  const [, top] = pageTitle(ctx, v, box, t0);
  const made = [];
  let bottom = y0 + h;
  const ver = v.verdict || {};
  let vtext = null;
  if (ver.text) {
    vtext = balancedText(ctx, ctx.T(ver.text), 52, w - 220, { maxLines: 2, align: 'center' });
    bottom = y0 + h - vtext.size[1] - 36 - 34;
  }
  const half = w / 2;
  const sw = half - 90;
  const sides = ['left', 'right'].map((key) => {
    const s = v[key] || {};
    const who = s.who ? ctx.text(ctx.T(s.who), 50, { color: ctx.color, maxW: sw, maxLines: 1, align: 'center', minSize: 40, pace: 1.4 }) : null;
    const body = s.text ? balancedText(ctx, ctx.T(s.text), 50, sw - 90, { maxLines: 3, align: 'center', pace: 1.3 }) : null;
    return [s, who, body];
  });
  const whoH = Math.max(0, ...sides.map(([, who]) => (who ? who.size[1] : 0)));
  const bodyH = Math.max(0, ...sides.map(([, , body]) => (body ? body.size[1] : 0)));
  const bubH = bodyH ? bodyH + 40 : 0;
  const avail = bottom - top;
  const Dd = Math.max(120, Math.min(280, avail - whoH - 10 - (bubH ? bubH + 42 : 0) - 10));
  const ys = top + Math.max(0, (avail - (whoH + 10 + Dd + (bubH ? 42 + bubH : 0))) / 2);
  const divX = x0 + half;
  const dash = [];
  for (let k = 0; top + 6 + k * 44 < bottom - 6; k++) dash.push([[divX, top + 6 + k * 44], [divX + 2, Math.min(bottom - 6, top + 6 + k * 44 + 24)]]);
  made.push(put(ctx, dash, t0, { color: SOFT_INK, width: 5, maxDur: 0.7 }));
  sides.forEach(([s, who, body], idx) => {
    const ti = when(ctx, beat, s, t0 + 0.5 + 3 * idx);
    const scx = idx === 0 ? x0 + half / 2 + 10 : x0 + half + half / 2 - 10;
    const parts = [];
    let y = ys;
    if (who) parts.push(ctx.add(who, scx - who.size[0] / 2, y + (whoH - who.size[1]), ti));
    y += whoH + 10;
    if (s.doodle) {
      const dd = ctx.doodle(s.doodle, [Dd * 1.4, Dd], { maxDur: 1.6 });
      parts.push(ctx.add(dd, scx - dd.size[0] / 2, y + (Dd - dd.size[1]), ti));
    }
    y += Dd + 6;
    if (body) {
      const bw = Math.min(sw, body.size[0] + 80);
      const poly = bubble(scx - bw / 2, y, bw, bubH, scx);
      parts.push(put(ctx, [poly], ti, { width: 6, fills: [[poly.slice(0, -1), [255, 255, 255]]], maxDur: 0.7 }));
      parts.push(ctx.add(body, scx - body.size[0] / 2, y + 36 + (bubH - body.size[1]) / 2, ti));
    }
    ctx.register(v.id, idx, parts);
    made.push(...parts);
  });
  if (vtext) {
    const tv = when(ctx, beat, ver, t0 + 7);
    const [bw, bh] = [vtext.size[0] + 90, vtext.size[1] + 36];
    const [bx, by] = [x0 + (w - bw) / 2, y0 + h - bh - 4];
    const rect = [[bx, by + 4], [bx + bw, by], [bx + bw - 3, by + bh], [bx + 2, by + bh - 2], [bx, by + 4]];
    const banner = put(ctx, [rect], tv, { color: ctx.color, width: 6, fills: [[rect.slice(0, -1), mix(ctx.color, 0.8)]], maxDur: 0.9, after: made[made.length - 1] || null });
    made.push(banner, ctx.add(vtext, bx + (bw - vtext.size[0]) / 2, by + (bh - vtext.size[1]) / 2, tv, { after: banner }));
  }
  ctx.register(v.id, 'all', made);
}

export const PAGE_BUILDERS = { lanes: buildLanes, grid100: buildGrid100, bars: buildBars, flow: buildFlow, split: buildSplit };

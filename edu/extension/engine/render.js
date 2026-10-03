// Render a storyboard + timeline into frames (port of kinodraw/engine/render.py, board parts; no stock video).
//   const prod = await Production.create(board, timing, env);   env = { svg: SvgLibrary, hand: Hand, paper }
//   prod.drawFrame(g, t)        // g: a 1920×1080 2D context
// Frames must be asked for in increasing time (drawings reveal incrementally).
import * as auto from './auto_scenes.js';
import { COL, Camera, Layout, PAN_SECONDS, Scheduler } from './board.js';
import { MAX_W, SIZE as CAPTION_SIZE, balancedLines, splitLong } from './captions.js';
import { NEUTRAL, SECTION_COLORS, StaticDrawing, canvas, css, font, textWidth } from './ink.js';
import { PAGE_BUILDERS } from './pages.js';
import { Ctx, SLOT_BUILDERS } from './scenes.js';
import { takeText } from './script.js';
import { normalizeStoryboard } from './storyboard.js';
import * as tl from './timeline.js';

export const FPS = 30;
export const SIZE = [1920, 1080];
export const NOTE_READ = 1.0;          // a finished takeaway note stays readable this long before it is pinned
export const PAUSE_MAX = 4.0;          // the longest pause after a beat while the drawing hand catches up (pacing)
export const PACE_MARGIN = 0.3;        // a beat's drawings finish this long before the next beat's words start

const ease = (u) => { u = Math.min(1, Math.max(0, u)); return u * u * (3 - 2 * u); };

/** Every doodle a storyboard may draw: its visuals' doodles plus the narrator poses the automatic scenes use. */
export function doodlesOf(board) {
  const out = new Set(['missing']);
  const walk = (v) => {
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) (k === 'doodle' && typeof x === 'string' ? out.add(x) : walk(x));
  };
  board.beats.forEach((b) => walk(b.visuals || []));
  const prefix = board.narrator ?? 'narrator';
  if (prefix && prefix !== 'none') for (const pose of ['wave', 'present', 'head', 'thumbs']) out.add(`${prefix}_${pose}`);
  return [...out];
}

export class Production {
  static async create(board, timing, env, { relaxed = false, prepare = true } = {}) {
    await env.svg.load(doodlesOf(board));
    const prod = new Production(board, timing, env, relaxed);
    if (prepare) await prod.prepare();
    return prod;
  }

  constructor(episode, timing, env, relaxed = false) {
    this.ep = normalizeStoryboard(episode);
    this.tl = timing;
    this.env = env;
    this.relaxed = relaxed;
    this.layout = new Layout();
    this.ctx = new Ctx(this.ep, timing, this.layout, env.svg);
    this.camera = new Camera();
    this.cuts = [];
    this.cutMarks = [];
    this.modes = [];
    this.cards = {};
    this.notes = {};
    this.pages = {};
    this.agendaX = null;
    this.warnings = [];
    this.build();
    this.schedule();
  }

  /** Rasterize the doodles at their final sizes and pin the finished notes onto the agenda (before any frame). */
  async prepare() {
    await this.env.svg.prepare(this.ctx.elements.map((e) => e.drawing));
    this.pinNotes();
    this.index();
  }

  // ------------------------------------------------------------ building
  beatsOf(cid) { return this.ep.beats.filter((b) => b.chapter === cid); }
  bt(beat) { return this.tl.beats[beat.id]; }

  cut(t, x, mode) {
    this.cuts.push([t, x, mode]);
    this.cutMarks.push(this.ctx.elements.length);
  }

  tag(first, group, flags = {}) {
    for (const el of this.ctx.elements.slice(first)) Object.assign(el, { group, ...flags });
  }

  visuals(beat, notBefore = 0) {
    const ctx = this.ctx;
    ctx.beat = beat;
    const firstNew = ctx.elements.length;
    (beat.visuals || []).forEach((v, k) => {
      const n0 = ctx.elements.length;
      try {
        if (SLOT_BUILDERS[v.type]) {
          let size = v.size || 'slot';
          if (v.type === 'cluster' && (v.items || []).length >= 3 && size === 'slot') size = 'wide';
          if (v.type === 'quote') size = 'wide';
          const [box] = size === 'wide' ? this.layout.wide() : size === 'tall' ? this.layout.slot(2) : this.layout.slot();
          SLOT_BUILDERS[v.type](v, beat, box, ctx);
        } else if (PAGE_BUILDERS[v.type]) {
          const [box, [c0]] = this.layout.page();
          // An invisible anchor across the page, drawn first: the camera pans to the whole page.
          ctx.add(auto.pageAnchor(3 * COL - 4), c0 * COL + 2, 100, ctx.timeOf(beat, v.trigger), { hand: false });
          PAGE_BUILDERS[v.type](v, beat, box, ctx);
        } else {
          this.warnings.push(`${beat.id}: unsupported visual type ${v.type}`);
        }
      } catch (error) {
        this.warnings.push(`${beat.id}/${v.id}: ${error.message}`);
      }
      const hold = v.type === 'glossary' ? 3.5 : PAGE_BUILDERS[v.type] || v.type === 'quote' ? 1.8 : 0.8;
      for (const el of ctx.elements.slice(n0)) Object.assign(el, { hold, group: v.id || `${beat.id}#${k}`, beat: beat.id });
    });
    for (const el of ctx.elements.slice(firstNew)) el.trigger = Math.max(el.trigger, notBefore);
  }

  build() {
    const { ctx, layout: lay } = this;
    const chapters = this.ep.chapters;
    for (const ch of chapters) {
      const [cid, kind] = [ch.id, ch.kind];
      ctx.chapter = ch;
      ctx.color = SECTION_COLORS[ch.color] || NEUTRAL;
      const beats = this.beatsOf(cid);
      const cstart = this.tl.chapters.find((c) => c.id === cid).start;
      if (kind === 'intro') {
        for (const b of beats) {
          const col = lay.newPage();
          lay.reserve(col, col + 2);
          const x0 = col * COL;
          this.cut(this.bt(b).start, x0, 'cut');
          const n0 = ctx.elements.length;
          auto.buildTitleBoard(ctx, b, x0, this.bt(b).start + 0.25);
          this.tag(n0, 'title', { essential: true });
          this.pages.title = x0;
        }
        continue;
      }
      if (kind === 'agenda') {
        const col = lay.newPage();
        lay.reserve(col, col + 2);
        const x0 = col * COL;
        this.agendaX = x0;
        this.cut(cstart, x0, 'pan');
        const n0 = ctx.elements.length;
        this.cards = auto.buildAgenda(ctx, chapters, beats, x0);
        const first = chapters.find((c) => c.kind === 'section');
        const end = this.tl.chapters.find((c) => c.id === cid).end;
        this.tag(n0, 'agenda', { essential: true, deadline: end - 1.05 - 0.15 });    // cards before the circle
        const [circ, pos] = auto.circleAround(ctx, this.cards[first.id].box, this.cards[first.id].color);
        ctx.add(circ, pos[0], pos[1], end - 1.05, { fixed: true });
        continue;
      }
      const col = lay.newPage();
      const x0 = col * COL;
      this.pages[cid] = x0;
      let openerDone = 0;
      if (kind === 'section') {
        lay.reserve(col, col + 1);
        this.cut(cstart, x0, 'cut');
        const n0 = ctx.elements.length;
        const opener = auto.buildSectionOpener(ctx, ch, beats[0], x0, cstart + tl.ZOOM_IN + 0.15);
        this.tag(n0, `opener:${cid}`, { essential: true });
        openerDone = cstart + tl.ZOOM_IN + 0.15 + opener.filter((e) => e.hand).reduce((a, e) => a + e.drawing.duration, 0) * 0.8;
        this.modes.push([cstart, cstart + tl.ZOOM_IN, 'zoom', { section: cid }]);
      } else {
        const prevTr = this.tl.transitions.find((t) => t.next === cid);
        this.cut(cstart, x0, prevTr ? 'cut' : 'pan');
        if (prevTr) this.modes.push([cstart, cstart + 0.5, 'fade_in', {}]);
      }
      for (const b of beats) {
        if (b.kind === 'take' && kind === 'section') this.takePage(b, this.bt(b), ch);
        else this.visuals(b, openerDone);             // nothing before the section's title card
      }
    }
    const end = this.tl.end_card;                    // closing page, written by the hand like everything else
    const col = lay.newPage();
    lay.reserve(col, col + 2);
    ctx.chapter = null;
    ctx.color = NEUTRAL;
    this.cut(end.start, col * COL, 'pan');
    const n0 = ctx.elements.length;
    auto.buildEndCard(ctx, col * COL, end.start + PAN_SECONDS);
    this.tag(n0, 'endcard', { essential: true, deadline: end.end - 0.5 });
    this.transitions();
  }

  /** The section's takeaway page: during the pre-roll the camera pans over and the note is laid down; its label and
   * headline are written as "Key takeaway: ..." is said, and finished NOTE_READ seconds before it is pinned. */
  takePage(beat, bt, ch) {
    const { ctx, layout: lay } = this;
    const cid = ch.id;
    const tcol = lay.newPage();
    lay.reserve(tcol, tcol + 2);
    const xt = tcol * COL;
    const prep = bt.prep ?? bt.start;
    this.cut(prep + 0.1, xt, 'pan');
    const tr = this.tl.transitions.find((x) => x.section === cid);
    const deadline = tr ? tr.hold_end - NOTE_READ : null;
    const tNote = prep + 0.1 + PAN_SECONDS;
    const spoken = beat.spoken.en;
    const prefix = takeText('');
    const tLabel = ctx.timeOf(beat, null, 0);
    const tHead = spoken.startsWith(prefix) && spoken.length > prefix.length
      ? ctx.timeOf(beat, { en: spoken.slice(prefix.length, prefix.length + 24) }) : tLabel;
    const [els, bbox] = auto.buildTakeNote(ctx, beat, ch, xt, tNote, tLabel, tHead);
    els.forEach((el, k) => Object.assign(el, { group: el.essential ? `note:${cid}` : `note:${cid}:${k}`, deadline }));
    this.notes[cid] = { els, bbox, x: xt };
    const written = els[2];
    const margins = [[xt + 16, 250, 310, 420], [xt + 1920 - 326, 250, 310, 420]];
    const n0 = ctx.elements.length;                  // the margin pair is drawn together or not at all
    (beat.visuals || []).filter((v) => v.size === 'margin').slice(0, 2).forEach((v, k) => SLOT_BUILDERS.cluster(v, beat, margins[k], ctx));
    this.tag(n0, `margins:${cid}`, { optional: true, deadline });
    for (const el of ctx.elements.slice(n0)) {
      el.trigger = Math.max(el.trigger, tNote + 0.02);
      el.after ??= written;
    }
  }

  transitions() {
    const ctx = this.ctx;
    for (const tr of this.tl.transitions) {
      const [sec, nxt] = [tr.section, tr.next];
      const card = this.cards[sec];
      const note = this.notes[sec];
      if (!card || !note) {
        this.warnings.push(`transition ${sec}: missing card or note`);
        continue;
      }
      const tp = tr.hold_end;
      const tf = tp + 0.35;
      const tc = tf + 0.9;
      const trr = tc + 0.7;
      this.modes.push([tp, tf, 'pullback', { section: sec }], [tf, tc, 'fly', { section: sec }], [tc, tr.end, 'agenda', { section: sec }]);
      const [, , nw, nh] = note.bbox;
      const [iw, ih] = [Math.trunc(nw) + 4, Math.trunc(nh) + 4];
      const [cx, cy, cw, chh] = card.box;
      const mw = Math.trunc(Math.min(cw - 90, (chh - 150) * iw / ih));
      const mh = Math.trunc(ih * mw / iw);
      const [px, py] = [cx + (cw - mw) / 2, cy + chh - mh - 34];
      Object.assign(note, { pinXY: [px, py], miniSize: [mw, mh], tPin: tc });
      ctx.add(auto.pin(ctx), px + mw / 2 - 22, py - 14, tc, { fixed: true, hand: false });
      const taken = [...card.els.map(auto.inkBbox).filter(Boolean), [px, py - 14, px + mw, py + mh]];
      const [size, pos] = auto.checkSpot(card.box, taken, chh >= 600 ? [150, 120, 96] : [90, 72, 60]);
      ctx.add(auto.checkMark(ctx, undefined, size), pos[0], pos[1], tc + 0.05, { fixed: true });
      if (this.cards[nxt]) {
        const [circ, p] = auto.circleAround(ctx, this.cards[nxt].box, this.cards[nxt].color);
        ctx.add(circ, p[0], p[1], trr, { fixed: true });
      }
    }
    this.modes.sort((a, b) => a[0] - b[0]);
  }

  schedule() {
    const els = this.ctx.elements;
    const marks = [...this.cutMarks, els.length];
    for (let k = 0; k < this.cuts.length; k++) for (const el of els.slice(marks[k], marks[k + 1])) el.stretch = k;
    new Scheduler(this.camera).run(els, this.cuts, this.relaxed ? { maxRate: 1.0, stale: Infinity, cutGrace: Infinity } : {});
    const skipped = [...new Set(els.filter((e) => e.skipped).map((e) => e.group))].sort();
    if (skipped.length) this.warnings.push(`skipped ${skipped.length} visual(s) that could not keep pace with the narration: ${skipped.join(', ')}`);
  }

  /** Picture each takeaway note as it stands when its transition starts, and pin that picture onto the agenda card. */
  pinNotes() {
    for (const tr of this.tl.transitions) {
      const note = this.notes[tr.section];
      if (!note || !note.pinXY) continue;
      const [nx, ny, nw, nh] = note.bbox;
      const img = canvas(Math.trunc(nw) + 4, Math.trunc(nh) + 4);
      const g = img.getContext('2d');
      for (const el of note.els) {
        const { img: s } = el.state(tr.hold_end - 0.01);
        if (s) g.drawImage(s, Math.round(el.x - nx), Math.round(el.y - ny));
      }
      note.image = img;
      const mini = canvas(...note.miniSize);
      mini.getContext('2d').drawImage(img, 0, 0, ...note.miniSize);
      note.mini = mini;
      const el = this.ctx.add(new StaticDrawing(mini, 0.05), note.pinXY[0], note.pinXY[1], note.tPin - 0.02, { fixed: true, hand: false });
      el.start = el.trigger;
      for (const e of note.els) e.drawing.reset?.();      // the frames start over from the beginning
    }
  }

  index() {
    this.els = this.ctx.elements.filter((e) => e.start !== null && !e.skipped).sort((a, b) => a.start - b.start);
    this.handEls = this.els.filter((e) => e.hand);
    this.handStarts = this.handEls.map((e) => e.start);
    this.capStarts = this.tl.captions.map((c) => c.start);
  }

  // ------------------------------------------------------------- views
  modeAt(t) {
    let i = this.modes.length - 1;
    while (i >= 0 && this.modes[i][0] > t) i--;         // bisect_right(starts, t) - 1
    while (i >= 0) {
      const [a, b, kind, params] = this.modes[i];
      if (a <= t && t < b) return [kind, params, a, b];
      i--;
      if (i >= 0 && this.modes[i][1] <= t) break;       // an earlier mode may still be running; older ones are over
    }
    return ['board', {}, null, null];
  }

  view(g, t, L, hand = true) {
    g.drawImage(this.env.paper, 0, 0);
    const [lo, hi] = [L - 20, L + SIZE[0] + 20];
    for (const layer of [0, 1]) {
      for (const e of this.els) {
        if (e.start > t) break;
        if (e.layer !== layer || e.x > hi || e.x + e.w < lo) continue;
        const { img } = e.state(t);
        if (img) g.drawImage(img, Math.round(e.x - L), Math.round(e.y));
      }
    }
    if (hand) this.hand(g, t, L);
  }

  hand(g, t, L) {
    let lo = 0;
    let hi = this.handStarts.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (this.handStarts[mid] <= t) lo = mid + 1; else hi = mid; }
    const i = lo - 1;
    const cur = i >= 0 ? this.handEls[i] : null;
    if (cur && cur.start <= t && t < cur.end) {
      const { pen, down } = cur.state(t);
      if (pen) {
        this.env.hand.paste(g, [cur.x - L + pen[0], cur.y + pen[1]], !down);
        return;
      }
      if (t - cur.start < cur.drawing.duration * 0.95 && cur.drawing.drawTime !== undefined) return;
    }
    const prev = cur && cur.end <= t ? cur : i > 0 ? this.handEls[i - 1] : null;
    const nxt = i + 1 < this.handEls.length ? this.handEls[i + 1] : null;
    if (!prev || !nxt) return;
    const gap = nxt.start - prev.end;                    // travelling between drawings
    if (gap > 1.4 || gap <= 0) return;
    const p0 = lastPen(prev.drawing);
    const p1 = firstPen(nxt.drawing);
    if (!p0 || !p1) return;
    const u = ease((t - prev.end) / gap);
    const x = (prev.x + p0[0]) * (1 - u) + (nxt.x + p1[0]) * u - L;
    const y = (prev.y + p0[1]) * (1 - u) + (nxt.y + p1[1]) * u;
    this.env.hand.paste(g, [x, y - 10 * Math.sin(Math.PI * u)], true);
  }

  // ------------------------------------------------------------- frame
  drawFrame(g, t) {
    const [kind, p, a, b] = this.modeAt(t);
    if (kind === 'pullback' || kind === 'fly' || kind === 'agenda') this.transition(g, t, kind, p, a, b);
    else if (kind === 'zoom') this.zoom(g, t, p, a, b);
    else if (kind === 'fade_in') {
      this.scratch ??= canvas(...SIZE);
      const s = this.scratch.getContext('2d');
      this.view(s, t, this.agendaX, false);
      this.view(g, t, this.camera.at(t));
      g.globalAlpha = 1 - ease((t - a) / (b - a));
      g.drawImage(this.scratch, 0, 0);
      g.globalAlpha = 1;
    } else {
      this.view(g, t, this.camera.at(t));
    }
    if (!this.inTitle(t)) this.chrome(g, t);
    this.caption(g, t);
  }

  inTitle(t) {
    const ids = new Set(this.ep.chapters.filter((c) => c.kind === 'intro').map((c) => c.id));
    return this.tl.chapters.some((c) => ids.has(c.id) && c.start <= t && t < c.end);
  }

  transition(g, t, kind, p, a, b) {
    const note = this.notes[p.section];
    const tr = this.tl.transitions.find((x) => x.section === p.section);
    const [nx, ny, nw] = note.bbox;
    const [sx, sy] = [nx - note.x, ny];
    if (kind === 'pullback') {
      const u = ease((t - a) / (b - a));
      this.view(g, tr.hold_end - 0.01, note.x, false);
      this.scratch ??= canvas(...SIZE);
      const s = this.scratch.getContext('2d');
      this.view(s, t, this.agendaX, false);
      g.globalAlpha = u;
      g.drawImage(this.scratch, 0, 0);
      g.globalAlpha = 1;
      g.drawImage(note.image, Math.round(sx), Math.round(sy));
      return;
    }
    this.view(g, t, this.agendaX, kind === 'agenda');
    if (kind === 'fly') {
      const u = ease((t - a) / (b - a));
      const [tx0, ty] = note.pinXY;
      const tx = tx0 - this.agendaX;
      const w = nw + (note.mini.width - nw) * u;
      const s = w / nw;
      const x = sx + (tx - sx) * u;
      const y = sy + (ty - sy) * u - 60 * Math.sin(Math.PI * u);
      g.drawImage(note.image, x, y, note.image.width * s, note.image.height * s);
    }
  }

  zoom(g, t, p, a, b) {
    const u = (t - a) / (b - a);
    const card = this.cards[p.section];
    this.scratch ??= canvas(...SIZE);
    const s = this.scratch.getContext('2d');
    this.view(s, a - 0.01, this.agendaX, false);
    const cx = card.box[0] - this.agendaX + card.box[2] / 2;
    const cy = card.box[1] + card.box[3] / 2;
    const z = 1 + 2.4 * ease(u);
    const [w, h] = [SIZE[0] / z, SIZE[1] / z];
    const x0 = Math.min(Math.max(0, cx - w / 2), SIZE[0] - w);
    const y0 = Math.min(Math.max(0, cy - h / 2), SIZE[1] - h);
    const k = ease((u - 0.5) / 0.5);
    if (k > 0) this.view(g, t, this.camera.at(t));
    g.globalAlpha = 1 - k;
    g.drawImage(this.scratch, x0, y0, w, h, 0, 0, SIZE[0], SIZE[1]);
    g.globalAlpha = 1;
  }

  chrome(g, t) {
    const span = this.tl.chapters.find((c) => c.start <= t && t < c.end);
    if (!span) return;
    const ch = this.ep.chapters.find((x) => x.id === span.id);
    if (ch.kind === 'intro' || ch.kind === 'outro') return;
    g.globalAlpha = Math.max(0, Math.min(1, (t - span.start) / 0.4, (span.end - t) / 0.3));   // labels fade in and out
    g.drawImage(this.chip(ch), 36, 22);
    g.globalAlpha = 1;
  }

  chip(ch) {
    this.chips ??= new Map();
    if (!this.chips.has(ch.id)) {
      const label = ch.label?.en || '';
      const title = ch.title?.en || '';
      const short = ch.kind === 'section' ? title.split(':')[0] : title;
      const text = label && short && short.trim().toLowerCase() !== label.trim().toLowerCase() ? `${label} · ${short}` : label || short;
      const w = Math.trunc(textWidth(text, 32, 'caption')) + 44;
      const c = canvas(w, 52);
      const g = c.getContext('2d');
      const col = SECTION_COLORS[ch.color];
      g.beginPath();
      g.roundRect(0.5, 0.5, w - 1, 51, 26);
      g.fillStyle = col ? css(col) : 'rgba(255,255,255,0.8)';
      g.fill();
      if (!col) { g.strokeStyle = css([40, 52, 64]); g.lineWidth = 3; g.stroke(); }
      g.font = font('caption', 32);
      g.textBaseline = 'top';
      g.fillStyle = col ? '#fff' : css([40, 52, 64]);
      g.fillText(text, 22, 10);
      this.chips.set(ch.id, c);
    }
    return this.chips.get(ch.id);
  }

  caption(g, t) {
    let lo = 0;
    let hi = this.capStarts.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (this.capStarts[mid] <= t) lo = mid + 1; else hi = mid; }
    const c = this.tl.captions[lo - 1];
    if (!c || !(c.start <= t && t < c.end)) return;
    const img = captionImage(c.text);
    g.drawImage(img, Math.round((SIZE[0] - img.width) / 2), Math.round(1046 - img.height));
  }
}

const firstPen = (d) => (d.polys ? d.polys[0]?.[0] : d.points ? d.points[0] : null);
const lastPen = (d) => (d.polys ? d.polys[d.polys.length - 1]?.at(-1) : d.points ? d.points[d.points.length - 1] : null);

export const measureCaption = (text) => textWidth(text.trim(), CAPTION_SIZE, 'caption');
const captionCache = new Map();

/** A caption in up to two balanced lines: dark text with a white outline (Arimo Bold 70 px). */
export function captionImage(text) {
  if (!captionCache.has(text)) {
    const lines = balancedLines(text, measureCaption) || splitLong(text, measureCaption).slice(0, 2);
    const stroke = 7;
    const lh = Math.trunc(CAPTION_SIZE * 1.16);
    const widths = lines.map((l) => textWidth(l, CAPTION_SIZE, 'caption'));
    const c = canvas(Math.trunc(Math.max(...widths, 1)) + 2 * stroke + 8, lh * lines.length + 2 * stroke + 10);
    const g = c.getContext('2d');
    g.font = font('caption', CAPTION_SIZE);
    g.textBaseline = 'top';
    g.lineJoin = 'round';
    lines.forEach((line, i) => {
      const x = (c.width - widths[i]) / 2;
      const y = stroke + i * lh;
      g.strokeStyle = '#fff';
      g.lineWidth = stroke * 2;
      g.strokeText(line, x, y);
      g.fillStyle = '#121212';
      g.fillText(line, x, y);
    });
    if (captionCache.size > 500) captionCache.clear();
    captionCache.set(text, c);
  }
  return captionCache.get(text);
}

/** Pauses (beat id -> seconds) that let the drawing hand finish each beat's pictures before the next beat is said,
 * instead of rushing or skipping them: at most PAUSE_MAX after any one beat (port of render.pacing). */
export async function pacing(episode, clips, env, rounds = 3) {
  const pauses = {};
  await env.svg.load(doodlesOf(episode));
  for (let r = 0; r < rounds; r++) {
    const timing = tl.layout(episode, clips, pauses);
    const prod = new Production(episode, timing, env, true);
    const ends = {};
    for (const e of prod.ctx.elements) {
      if (e.beat && e.start !== null && !e.skipped && !e.fixed) ends[e.beat] = Math.max(ends[e.beat] ?? 0, e.end);
    }
    const order = timing.beat_order;
    let changed = false;
    for (let k = 0; k < order.length - 1; k++) {
      const bid = order[k];
      const nxt = timing.beats[order[k + 1]];           // a takeaway's pre-roll is for its note
      const need = (ends[bid] ?? -Infinity) + PACE_MARGIN - (nxt.prep ?? nxt.start);
      const room = PAUSE_MAX - (pauses[bid] ?? 0);
      if (need > 0.05 && room > 0.05) {
        pauses[bid] = Math.round(((pauses[bid] ?? 0) + Math.min(need, room)) * 100) / 100;
        changed = true;
      }
    }
    if (!changed) break;
  }
  return pauses;
}

export { MAX_W };

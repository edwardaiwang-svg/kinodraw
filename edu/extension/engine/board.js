// Board model (port of kinodraw/engine/board.py): elements on a continuous world strip, layout, one-hand
// scheduling, camera. World x grows along one long strip; y is screen y. The screen shows 3 columns of 640 px; the
// camera's left edge is a column boundary at rest, so no item is ever cut by the frame edge.
//
// Scheduling rules (every video, whatever the director planned):
// - nothing appears without the hand: each drawing starts at or after its trigger and plays in full on screen;
// - the camera moves only by smooth pans from where it is, leaves a page only after the hand has finished there,
//   and never goes back: anything left of the screen once the camera has moved on is skipped;
// - a drawing that could not start within STALE seconds of its words, or would hold the next page up by more than
//   CUT_GRACE, is skipped rather than drawn late; so is anything optional that would miss its deadline;
// - a drawing that follows another is never due before it.

export const COL = 640;
export const COLS_ON_SCREEN = 3;
export const CELL_X0 = 50;
export const CELL_W = 540;
export const ROW_Y = [[84, 440], [466, 822]];
export const PAGE_BOX = [60, 84, 1800, 738];
export const PAN_SECONDS = 0.9;
export const STALE = 3.0;
export const CUT_GRACE = 1.5;
export const SETTLE = 0.35;

export class Element {
  constructor(drawing, x, y, trigger, opts = {}) {
    Object.assign(this, { drawing, x, y, trigger, hand: true, layer: 0, group: '', fixed: false, after: null, start: null,
      hiddenAfter: null, rate: 1.0, hold: 1.2, stretch: 0, essential: false, optional: false, deadline: null, skipped: false,
      beat: '' }, opts);
  }

  get duration() { return this.drawing.duration / this.rate; }
  get end() { return (this.start ?? 0) + this.duration; }
  get w() { return this.drawing.size[0]; }
  get h() { return this.drawing.size[1]; }
  bbox() { return [this.x, this.y, this.x + this.w, this.y + this.h]; }

  state(t) {
    if (this.start === null || t < this.start) return { img: null, pen: null, down: false };
    if (this.hiddenAfter !== null && t >= this.hiddenAfter) return { img: null, pen: null, down: false };
    return this.drawing.state((t - this.start) * this.rate);
  }
}

/** Column-major slot allocator on the world strip (2 rows per column). */
export class Layout {
  constructor() {
    this.used = new Map();
    this.cursor = 0;
    this.pageStart = 0;
  }

  free(col, row) { return !(this.used.get(col)?.has(row)); }

  take(col, row) {
    if (!this.used.has(col)) this.used.set(col, new Set());
    this.used.get(col).add(row);
  }

  nextFreshColumn() {
    return Math.max(this.cursor, ...[...this.used].filter(([, rows]) => rows.size).map(([c]) => c + 1));
  }

  newPage() {
    const col = this.nextFreshColumn();
    this.cursor = col;
    this.pageStart = col;
    return col;
  }

  slot(rowsNeeded = 1) {
    for (let col = this.cursor; ; col++) {
      if (rowsNeeded === 2) {
        if (this.free(col, 0) && this.free(col, 1)) {
          this.take(col, 0);
          this.take(col, 1);
          this.cursor = col;
          return [Layout.cellBox(col, 0, 2), [col, col]];
        }
      } else {
        for (const row of [0, 1]) {
          if (this.free(col, row)) {
            this.take(col, row);
            this.cursor = col;
            return [Layout.cellBox(col, row), [col, col]];
          }
        }
      }
    }
  }

  wide() {
    for (let col = this.cursor; ; col++) {
      for (const row of [0, 1]) {
        if (this.free(col, row) && this.free(col + 1, row)) {
          this.take(col, row);
          this.take(col + 1, row);
          this.cursor = col;
          const [y0, y1] = ROW_Y[row];
          return [[col * COL + CELL_X0, y0, COL + CELL_W, y1 - y0], [col, col + 1]];
        }
      }
    }
  }

  page() {
    const col = this.nextFreshColumn();
    for (let c = col; c < col + COLS_ON_SCREEN; c++) { this.take(c, 0); this.take(c, 1); }
    this.cursor = col + COLS_ON_SCREEN;
    const [x, y, w, h] = PAGE_BOX;
    return [[col * COL + x, y, w, h], [col, col + COLS_ON_SCREEN - 1]];
  }

  reserve(colFrom, colTo) {
    for (let c = colFrom; c <= colTo; c++) { this.take(c, 0); this.take(c, 1); }
    this.cursor = colTo + 1;
  }

  static cellBox(col, row, rows = 1) {
    return [col * COL + CELL_X0, ROW_Y[row][0], CELL_W, ROW_Y[row + rows - 1][1] - ROW_Y[row][0]];
  }
}

/** Piecewise camera: left edge L(t) in world px; a pan always starts from wherever the camera actually is. */
export class Camera {
  constructor() {
    this.keys = [[0, 0, 'cut']];
    this.segs = null;
  }

  segments() {
    if (!this.segs) {
      const segs = [];
      for (const [t0, L, kind] of [...this.keys].map((k, i) => [k, i]).sort((a, b) => a[0][0] - b[0][0] || a[1] - b[1]).map(([k]) => k)) {
        const a = kind === 'cut' || !segs.length ? L : Camera.evalSeg(segs[segs.length - 1], t0);
        segs.push([t0, a, L, kind]);
      }
      this.segs = segs;
      this.starts = segs.map((s) => s[0]);
    }
    return this.segs;
  }

  static evalSeg([t0, a, b], t) {
    if (a === b) return b;
    const f = Math.min(1, Math.max(0, (t - t0) / PAN_SECONDS));
    return a + (b - a) * f * f * (3 - 2 * f);
  }

  at(t) {
    const segs = this.segments();
    let lo = 0;
    let hi = this.starts.length;
    while (lo < hi) {                                   // bisect_right
      const mid = (lo + hi) >> 1;
      if (this.starts[mid] <= t) lo = mid + 1; else hi = mid;
    }
    return Camera.evalSeg(segs[Math.max(lo - 1, 0)], t);
  }

  targetAt(t) {
    let cur = this.keys[0][1];
    for (const [t0, L] of [...this.keys].map((k, i) => [k, i]).sort((a, b) => a[0][0] - b[0][0] || a[1] - b[1]).map(([k]) => k)) {
      if (t < t0) break;
      cur = L;
    }
    return cur;
  }

  cut(t, L) {
    this.keys.push([t, L, 'cut']);
    this.segs = null;
  }

  pan(t, L) {
    if (this.targetAt(t) !== L) {
      this.keys.push([t, L, 'pan']);
      this.segs = null;
    }
  }
}

export const columnSpan = (el) => [Math.floor(el.x / COL), Math.floor(Math.max(el.x, el.x + el.w - 1) / COL)];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** One hand: drawings happen one at a time, never before their trigger (rules: module comment). */
export class Scheduler {
  constructor(camera) { this.camera = camera; }

  run(elements, cuts, { maxRate = 2.0, stale = STALE, cutGrace = CUT_GRACE } = {}) {
    const cam = this.camera;
    for (let r = 0; r < 3; r++) {                       // a drawing that follows another is never due before it
      for (const e of elements) if (e.after && !e.fixed) e.trigger = Math.max(e.trigger, e.after.trigger + 0.01);
    }
    const fixed = elements.filter((e) => e.fixed);
    for (const e of fixed) e.start = e.trigger;
    const fixedBusy = fixed.filter((e) => e.hand).map((e) => [e.start, e.end]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const order = elements.map((e, i) => i).filter((i) => !elements[i].fixed).sort((a, b) =>
      elements[a].stretch - elements[b].stretch || round2(elements[a].trigger) - round2(elements[b].trigger) || a - b);
    const units = [];
    for (const i of order) {
      const e = elements[i];
      const key = `${e.stretch}|${round2(e.trigger)}`;
      if (units.length && units[units.length - 1][0] === key) units[units.length - 1][1].push(e);
      else units.push([key, [e], e.stretch, round2(e.trigger)]);
    }
    const planned = cuts.map((c) => c[0]);
    const nextTrig = new Array(units.length).fill(0);
    let upcoming = Infinity;                           // units that only follow another drawing don't hurry the one before
    for (let k = units.length - 1; k >= 0; k--) {
      nextTrig[k] = upcoming;
      if (!units[k][1].every((e) => e.after !== null)) upcoming = units[k][3];
    }
    let handFree = -1e9;
    let lastPen = null;
    const placed = [];
    const started = new Set();
    const dropped = new Set();
    const state = { stretch: -1, arrive: 0, base: 0 };
    const gone = (e) => dropped.has(e.group || e) || (e.after !== null && e.after.skipped);
    const enter = (s) => {                             // move the camera on to stretch s (and any empty ones before it)
      while (state.stretch < s) {
        state.stretch += 1;
        let [t, L, mode] = cuts[state.stretch];
        if (mode === 'pan') {
          t = Math.max(t, handFree + SETTLE);          // never leave a page mid-stroke
          cam.pan(t, L);
          state.arrive = t + PAN_SECONDS;
        } else {
          cam.cut(t, L);
          state.arrive = t;
        }
        state.base = Math.round(L / COL);
      }
    };
    units.forEach(([, els, s, trig], k) => {
      enter(s);
      const { arrive, base } = state;
      const pageChange = s + 1 < planned.length ? planned[s + 1] : Infinity;
      if (s + 1 < cuts.length && cuts[s + 1][2] === 'cut') {     // a zoom/fade takes this page away: finish first
        for (const e of els) e.deadline = Math.min(pageChange - SETTLE, e.deadline ?? Infinity);
      }
      const nxt = Math.max(trig, Math.min(nextTrig[k], trig + 60));
      const deadline = Math.min(...els.filter((e) => e.deadline !== null).map((e) => e.deadline), Infinity);
      const start = Math.max(trig, handFree + 0.15, arrive);
      let natural = 0;
      let pos = lastPen;
      for (const e of els) {
        if (e.hand && !gone(e)) {
          natural += (pos === null ? 0.12 : Math.min(0.3, 0.08 + dist(pos, [e.x, e.y]) / 5000)) + e.drawing.duration;
          pos = [e.x + e.w, e.y + e.h / 2];
        }
      }
      const window = Math.max(0.1, Math.min(nxt, pageChange, deadline) - start - 0.1);
      const rate = natural <= window ? 1.0 : Math.min(maxRate, natural / window);
      if (els.every((e) => e.optional) && start + natural / rate > deadline) {
        for (const e of els) { dropped.add(e.group || e); e.skipped = true; }   // decoration that cannot all fit
        return;
      }
      let cursor = start;
      for (const e of els) {
        const key = e.group || e;
        const [c0, c1] = columnSpan(e);
        if (gone(e) || c1 < base) {                    // its page is behind the camera: never go back
          dropped.add(key);
          e.skipped = true;
          continue;
        }
        let earliest = Math.max(cursor, e.trigger, arrive);
        let due = e.trigger;
        if (e.after !== null && e.after.start !== null) {
          earliest = Math.max(earliest, e.after.end);
          due = Math.max(due, e.after.end);
        }
        for (const [a, b] of fixedBusy) if (e.hand && a - 0.05 < earliest && earliest < b) earliest = b + 0.1;
        let panAt = null;
        let newCol = null;
        const Lcols = Math.round(cam.targetAt(earliest) / COL);
        if (c0 < Lcols && !e.essential) {              // the camera has moved past it: never pan back
          dropped.add(key);
          e.skipped = true;
          continue;
        }
        if (c0 < Lcols || c1 > Lcols + COLS_ON_SCREEN - 1) {
          newCol = c1 <= base + COLS_ON_SCREEN - 1 ? base : Math.max(c0, c1 - COLS_ON_SCREEN + 1);
          const lo = Lcols;
          const hi = Lcols + COLS_ON_SCREEN - 1;         // dwell: let what is on screen be read before panning away
          const dwell = placed.slice(-40).filter((x) => columnSpan(x)[1] >= lo && columnSpan(x)[0] <= hi).map((x) => x.end + x.hold);
          panAt = dwell.length ? Math.max(earliest, Math.min(Math.max(...dwell), earliest + 3.5)) : earliest;
          earliest = panAt + PAN_SECONDS;
        }
        let eRate = e.hand ? rate : 1.0;
        if (e.hand) {
          const travel = lastPen === null ? 0.12 : Math.min(0.3, 0.08 + dist(lastPen, [e.x, e.y]) / 5000);
          earliest = Math.max(earliest, handFree + travel / eRate);
        }
        const end = earliest + e.drawing.duration / eRate;
        const late = earliest - due > stale;
        const holdsPage = end > pageChange + cutGrace;
        const misses = e.deadline !== null && end > e.deadline;
        const fresh = !started.has(key);               // a visual is judged when it would start
        if (!e.essential && ((fresh && (late || holdsPage || misses)) || (e.optional && misses))) {
          dropped.add(key);                            // too late to help: skip it, never pop it in
          e.skipped = true;
          continue;
        }
        if (misses) eRate = Math.max(eRate, Math.min(4.0, e.drawing.duration / Math.max(0.05, e.deadline - earliest)));
        if (panAt !== null) cam.pan(panAt, newCol * COL);
        e.rate = eRate;
        e.start = earliest;
        started.add(key);
        placed.push(e);
        if (e.hand) {
          handFree = e.end;
          lastPen = [e.x + e.w, e.y + e.h / 2];
          cursor = e.end;
        } else {
          cursor = Math.max(cursor, earliest);
        }
      }
    });
    enter(cuts.length - 1);
    return elements;
  }
}

/** Python's round(x, 2): the scheduler groups drawings that share a trigger to the hundredth of a second. */
const round2 = (x) => Math.round(x * 100) / 100;

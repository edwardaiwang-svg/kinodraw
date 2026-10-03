// Drawing primitives (port of kinodraw/engine/ink.py) on 2D canvases.
//
// Every drawable has `size` [w, h], `duration` and `state(elapsed) -> { img, pen, down }`: `img` is a canvas showing the
// drawing as far as the hand has got (null before it starts), `pen` the nib position in the drawable's own pixels (or
// null). Nothing appears without a pen: SVG outlines are revealed by a brush that follows the path order and then the
// colour pops in; text, numbers included, is revealed glyph-stroke by glyph-stroke. States are computed incrementally,
// so frames must be asked for in increasing time (asking for an earlier time starts that drawing over).

export const INK = [27, 27, 27];
export const PAPER_RGB = [236, 235, 230];
export const SECTION_COLORS = { orange: [245, 124, 0], blue: [30, 111, 217], green: [46, 157, 79], purple: [142, 36, 170],
  red: [211, 47, 47], teal: [0, 137, 123] };
export const NEUTRAL = [40, 52, 64];
export const css = (c, alpha = 1) => `rgba(${c[0]},${c[1]},${c[2]},${c.length > 3 ? c[3] / 255 : alpha})`;
export const canvas = (w, h) => new OffscreenCanvas(Math.max(1, Math.ceil(w)), Math.max(1, Math.ceil(h)));

// --------------------------------------------------------------------------- fonts
export const FONT_FAMILY = { hand: 'DoodleHand', caption: 'DoodleCaption' };
export const font = (kind, size) => `${size}px "${FONT_FAMILY[kind === 'hand' ? 'hand' : 'caption']}"`;

/** Register the bundled fonts (Playpen Sans Bold for handwriting, Arimo Bold for captions and labels). */
export async function loadFonts(read, scope = globalThis) {
  const faces = [new FontFace(FONT_FAMILY.hand, await read('assets/fonts/PlaypenSans-Bold.ttf')),
    new FontFace(FONT_FAMILY.caption, await read('assets/fonts/Arimo-Bold.ttf'))];
  for (const f of faces) scope.fonts.add(await f.load());
}

let measurer = null;
const mctx = () => (measurer ??= canvas(8, 8).getContext('2d'));
const widthCache = new Map();

export function textWidth(text, size, kind = 'hand') {
  const key = `${kind}|${size}|${text}`;
  let w = widthCache.get(key);
  if (w === undefined) {
    const c = mctx();
    c.font = font(kind, size);
    w = c.measureText(text).width;
    if (widthCache.size > 20000) widthCache.clear();
    widthCache.set(key, w);
  }
  return w;
}

const metricsCache = new Map();
/** The font's ascent and descent at `size` (PIL's getmetrics). */
export function fontMetrics(size, kind = 'hand') {
  const key = `${kind}|${size}`;
  if (!metricsCache.has(key)) {
    const c = mctx();
    c.font = font(kind, size);
    const m = c.measureText('Hg');
    metricsCache.set(key, [Math.ceil(m.fontBoundingBoxAscent), Math.ceil(m.fontBoundingBoxDescent)]);
  }
  return metricsCache.get(key);
}

/** Greedy wrap for board text (whole words). */
export function wrapWords(text, size, maxWidth, kind = 'hand') {
  const lines = [];
  let cur = '';
  for (const u of text.match(/\S+\s*/g) || []) {
    const trial = cur + u;
    if (cur && textWidth(trial.trimEnd(), size, kind) > maxWidth) {
      lines.push(cur.trimEnd());
      cur = u.trimStart();
    } else {
      cur = trial;
    }
  }
  if (cur.trim()) lines.push(cur.trimEnd());
  return lines;
}

export function fitText(text, maxWidth, maxLines, size, minSize = 30) {
  for (;;) {
    const lines = wrapWords(text, size, maxWidth);
    if (lines.length <= maxLines || size <= minSize) return [lines, size];
    size -= 2;
  }
}

// ------------------------------------------------------------------ path drawings
/** A picture revealed by a brush that follows ordered polylines; `line` (ink only) shows while drawing, `color` (the
 * finished picture) replaces it over `pop` seconds once every outline is traced. */
export class PathDrawing {
  constructor(size, polylines, brush, { speed = 900, minDur = 0.7, maxDur = 3.2, pop = 0.28, color = null, line = null } = {}) {
    this.size = size;
    this.color = color;
    this.line = line;
    this.brush = Math.max(2.5, brush);
    const segs = [];
    const lifts = [];
    let last = null;
    for (const pts of polylines) {
      if (!pts.length) continue;
      lifts.push(last ? Math.hypot(pts[0][0] - last[0], pts[0][1] - last[1]) : 0);
      segs.push(pts);
      last = pts[pts.length - 1];
    }
    this.polys = segs;
    this.cums = segs.map((p) => {
      const cum = [0];
      for (let i = 1; i < p.length; i++) cum.push(cum[i - 1] + Math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]));
      return cum;
    });
    this.lens = this.cums.map((c, i) => (segs[i].length > 1 ? c[c.length - 1] : 1));
    const inkTime = this.lens.reduce((a, b) => a + b, 0) / speed;
    const liftTime = lifts.reduce((a, b) => a + b, 0) / (speed * 3.2) + 0.04 * Math.max(0, segs.length - 1);
    const raw = inkTime + liftTime;
    let scale = 1;
    if (raw > maxDur) scale = maxDur / raw;
    else if (raw < minDur && raw > 0) scale = minDur / raw;
    this.drawTime = Math.max(0.05, raw * scale);
    this.table = [];
    let t = 0;
    lifts.forEach((lift, i) => {
      const lt = (lift / (speed * 3.2) + (this.table.length ? 0.04 : 0)) * scale;
      const it = this.lens[i] / speed * scale;
      this.table.push([t, t + lt, t + lt + it]);
      t += lt + it;
    });
    this.pop = pop;
    this.duration = this.drawTime + pop;
    this.reset();
  }

  reset() {
    this.cacheE = -1;
    this.cacheIdx = 0;
    this.cachePart = 0;
    this.mask = null;
  }

  point(i, frac) {
    const pts = this.polys[i];
    if (pts.length === 1) return [pts[0], 1];
    const cum = this.cums[i];
    const target = frac * cum[cum.length - 1];
    let j = 0;
    let lo = 0;
    let hi = cum.length - 1;
    while (lo < hi) {                                     // searchsorted(cum, target, 'right') - 1
      const mid = (lo + hi + 1) >> 1;
      if (cum[mid] <= target) lo = mid; else hi = mid - 1;
    }
    j = Math.min(Math.max(lo, 0), pts.length - 2);
    const d = cum[j + 1] - cum[j];
    const f = d === 0 ? 0 : (target - cum[j]) / d;
    return [[pts[j][0] * (1 - f) + pts[j + 1][0] * f, pts[j][1] * (1 - f) + pts[j + 1][1] * f], j + 1];
  }

  advanceMask(elapsed) {
    if (!this.mask || elapsed < this.cacheE) {
      this.mask ??= canvas(...this.size);
      this.mask.getContext('2d').clearRect(0, 0, this.mask.width, this.mask.height);
      this.cacheIdx = 0;
      this.cachePart = 0;
    }
    const g = this.mask.getContext('2d');
    g.strokeStyle = g.fillStyle = '#000';
    g.lineWidth = Math.round(this.brush * 2);
    g.lineJoin = g.lineCap = 'round';
    let pen = null;
    let down = false;
    for (let i = 0; i < this.polys.length; i++) {
      const [liftStart, inkStart, inkEnd] = this.table[i];
      if (elapsed < liftStart) break;
      const pts = this.polys[i];
      if (elapsed < inkStart) {
        const prev = i ? this.polys[i - 1][this.polys[i - 1].length - 1] : pts[0];
        const f = (elapsed - liftStart) / Math.max(1e-6, inkStart - liftStart);
        pen = [prev[0] * (1 - f) + pts[0][0] * f, prev[1] * (1 - f) + pts[0][1] * f];
        down = false;
        break;
      }
      const frac = elapsed >= inkEnd ? 1 : (elapsed - inkStart) / Math.max(1e-6, inkEnd - inkStart);
      const [pt, upto] = this.point(i, frac);
      if (i < this.cacheIdx) continue;
      const start = i === this.cacheIdx ? this.cachePart : 0;
      const chunk = [...pts.slice(Math.max(0, start - 1), upto), pt];
      if (chunk.length >= 2) {
        g.beginPath();
        g.moveTo(chunk[0][0], chunk[0][1]);
        for (let k = 1; k < chunk.length; k++) g.lineTo(chunk[k][0], chunk[k][1]);
        g.stroke();
      }
      g.beginPath();
      g.arc(pt[0], pt[1], this.brush, 0, Math.PI * 2);
      if (pts.length === 1) g.arc(pts[0][0], pts[0][1], this.brush, 0, Math.PI * 2);
      g.fill();
      if (frac >= 1) {
        this.cacheIdx = i + 1;
        this.cachePart = 0;
      } else {
        this.cacheIdx = i;
        this.cachePart = upto;
        pen = pt;
        down = true;
        break;
      }
      pen = pt;
      down = true;
    }
    this.cacheE = elapsed;
    return [pen, down];
  }

  state(elapsed) {
    if (elapsed < 0) return { img: null, pen: null, down: false };
    if (elapsed >= this.duration) return { img: this.color, pen: null, down: false };
    this.out ??= canvas(...this.size);
    const o = this.out.getContext('2d');
    o.clearRect(0, 0, this.out.width, this.out.height);
    if (elapsed >= this.drawTime) {                     // the colour pops in over the line art
      const f = (elapsed - this.drawTime) / this.pop;
      o.globalAlpha = 1 - f;
      o.drawImage(this.line, 0, 0);
      o.globalAlpha = f;
      o.drawImage(this.color, 0, 0);
      o.globalAlpha = 1;
      return { img: this.out, pen: null, down: false };
    }
    const [pen, down] = this.advanceMask(elapsed);
    o.drawImage(this.line, 0, 0);
    o.globalCompositeOperation = 'destination-in';
    o.drawImage(this.mask, 0, 0);
    o.globalCompositeOperation = 'source-over';
    return { img: this.out, pen, down };
  }
}

/** Procedural ink lines (arrows, boxes, axes); optional polygon fills pop after. */
export function strokeDrawing(size, polylines, { color = INK, width = 6, closedFill = null, speed = 900, minDur = 0.35,
  maxDur = 2.2, pop = 0.2 } = {}) {
  const [w, h] = [Math.max(1, Math.trunc(size[0])), Math.max(1, Math.trunc(size[1]))];
  const line = canvas(w, h);
  const col = canvas(w, h);
  const stroke = (g) => {
    g.strokeStyle = g.fillStyle = css(color);
    g.lineWidth = width;
    g.lineJoin = 'round';
    g.lineCap = 'round';
    for (const poly of polylines) {
      if (!poly.length) continue;
      if (poly.length === 1) {
        g.beginPath();
        g.arc(poly[0][0], poly[0][1], width / 2, 0, Math.PI * 2);
        g.fill();
        continue;
      }
      g.beginPath();
      g.moveTo(poly[0][0], poly[0][1]);
      for (const [x, y] of poly.slice(1)) g.lineTo(x, y);
      g.stroke();
    }
  };
  const gc = col.getContext('2d');
  for (const [poly, fill] of closedFill || []) {
    gc.fillStyle = css(fill);
    gc.beginPath();
    gc.moveTo(poly[0][0], poly[0][1]);
    for (const [x, y] of poly.slice(1)) gc.lineTo(x, y);
    gc.closePath();
    gc.fill();
  }
  stroke(line.getContext('2d'));
  stroke(gc);
  const dense = polylines.map((poly) => {
    if (poly.length <= 1) return poly;
    const fine = [poly[0]];
    for (let i = 1; i < poly.length; i++) {
      const [a, b] = [poly[i - 1], poly[i]];
      const k = Math.max(1, Math.trunc(Math.hypot(b[0] - a[0], b[1] - a[1]) / 3));
      for (let s = 1; s <= k; s++) fine.push([a[0] + (b[0] - a[0]) * s / k, a[1] + (b[1] - a[1]) * s / k]);
    }
    return fine;
  });
  return new PathDrawing([w, h], dense, width * 0.9 + 1.5, { speed, minDur, maxDur, pop: closedFill ? pop : 0.01,
    color: col, line: closedFill ? line : col });
}

// ---------------------------------------------------------------- SVG doodles
/** Doodle SVGs: outlines sampled once in viewBox units (for timing), rasters made per size (for pixels). The
 * outlines come from the SVG DOM, so this must run in a page (not a worker). */
export class SvgLibrary {
  constructor(assets) {
    this.assets = assets;
    this.parsed = new Map();
    this.rasters = new Map();
  }

  async parse(id) {
    if (!this.parsed.has(id)) this.parsed.set(id, this.assets.svg(id).then((text) => parseSvg(text)));
    return this.parsed.get(id);
  }

  /** A PathDrawing of doodle `id` fitted in `box` (synchronous: parse() it first). */
  drawing(id, box, { speed = 700, minDur = 0.8, maxDur = 2.0 } = {}) {
    const info = this.parsedSync(id);
    const scale0 = Math.min(box[0] / info.vw, box[1] / info.vh);
    const w = Math.max(1, pyRound(info.vw * scale0));
    const h = Math.max(1, pyRound(info.vh * scale0));
    const scale = Math.min(w / info.vw, h / info.vh);
    const polys = info.polylines.map((p) => p.map(([x, y]) => [x * scale, y * scale]));
    const d = new PathDrawing([w, h], polys, Math.max(3.0, 6.0 * scale * 1.3), { speed, minDur, maxDur });
    d.svg = { id, w, h };
    return d;
  }

  has(id) { return Boolean(this.ready?.has(id)); }

  parsedSync(id) {
    const info = this.ready?.get(id);
    if (!info) throw new Error(`doodle ${id} was not loaded`);
    return info;
  }

  async load(ids) {
    this.ready ??= new Map();
    await Promise.all([...new Set(ids)].map(async (id) => this.ready.set(id, await this.parse(id))));
  }

  /** Give every SVG drawing its colour and line-art canvases (after layout, before frames). */
  async prepare(drawings) {
    await Promise.all(drawings.filter((d) => d.svg && !d.color).map(async (d) => {
      const key = `${d.svg.id}|${d.svg.w}x${d.svg.h}`;
      if (!this.rasters.has(key)) this.rasters.set(key, rasterSvg(this.parsedSync(d.svg.id).text, d.svg.w, d.svg.h));
      const { color, line } = await this.rasters.get(key);
      d.color = color;
      d.line = line;
    }));
  }
}

export function pyRound(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

async function parseSvg(text) {
  const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
  const root = doc.documentElement;
  const vb = (root.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
  const vw = vb.length === 4 ? vb[2] : Number(root.getAttribute('width'));
  const vh = vb.length === 4 ? vb[3] : Number(root.getAttribute('height'));
  const host = document.createElement('div');
  host.style.cssText = 'position:absolute;left:-20000px;top:0;visibility:hidden;pointer-events:none';
  const svg = document.importNode(root, true);
  svg.setAttribute('width', vw);
  svg.setAttribute('height', vh);
  host.appendChild(svg);
  document.body.appendChild(host);
  const polylines = [];
  try {
    for (const el of svg.querySelectorAll('path,rect,circle,ellipse,line,polyline,polygon')) {
      if (el.getAttribute('data-noink') === '1') continue;
      const len = el.getTotalLength();
      if (!(len > 0)) continue;
      const m = el.getCTM();
      const n = Math.max(2, Math.ceil(len / 1.5));
      let run = [];
      let prev = null;
      for (let k = 0; k < n; k++) {
        const p = el.getPointAtLength(len * k / (n - 1));
        const q = [m.a * p.x + m.c * p.y + m.e, m.b * p.x + m.d * p.y + m.f];
        if (prev && Math.hypot(q[0] - prev[0], q[1] - prev[1]) > 6) {   // a new sub-path starts here
          if (run.length) polylines.push(run);
          run = [];
        }
        run.push(q);
        prev = q;
      }
      if (run.length) polylines.push(run);
    }
  } finally {
    host.remove();
  }
  return { vw, vh, polylines, text };
}

async function rasterSvg(text, w, h) {
  const draw = async (svgText) => {
    const img = new Image();
    img.src = URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml' }));
    try {
      await img.decode();
      const c = canvas(w, h);
      c.getContext('2d').drawImage(img, 0, 0, w, h);
      return c;
    } finally {
      URL.revokeObjectURL(img.src);
    }
  };
  const color = await draw(text);
  const white = await draw(text.replace(/fill="(?!none)[^"]*"/g, 'fill="#FFFFFF"'));
  const g = white.getContext('2d');
  const px = g.getImageData(0, 0, w, h);
  const d = px.data;
  for (let i = 0; i < d.length; i += 4) {                  // ink where the white-filled picture is dark
    const lum = (d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000;
    let a = Math.min(255, Math.max(0, (255 - lum) * 1.25)) * d[i + 3] / 255;
    if (a < 18) a = 0;
    d[i] = INK[0]; d[i + 1] = INK[1]; d[i + 2] = INK[2]; d[i + 3] = a;
  }
  g.putImageData(px, 0, 0);
  return { color, line: white };
}

// ---------------------------------------------------------------- text drawings
const glyphCache = new Map();

/** Zhang-Suen thinning of a binary patch (padded by one pixel internally). */
function skeleton(bin, w, h) {
  const W = w + 2;
  const H = h + 2;
  const a = new Uint8Array(W * H);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) a[(y + 1) * W + x + 1] = bin[y * w + x];
  const remove = [];
  for (;;) {
    let changed = false;
    for (const step of [0, 1]) {
      remove.length = 0;
      for (let y = 1; y < H - 1; y++) {
        for (let x = 1; x < W - 1; x++) {
          const i = y * W + x;
          if (!a[i]) continue;
          const p = [a[i - W], a[i - W + 1], a[i + 1], a[i + W + 1], a[i + W], a[i + W - 1], a[i - 1], a[i - W - 1]];
          const count = p[0] + p[1] + p[2] + p[3] + p[4] + p[5] + p[6] + p[7];
          if (count < 2 || count > 6) continue;
          let transitions = 0;
          for (let k = 0; k < 8; k++) if (!p[k] && p[(k + 1) % 8]) transitions++;
          if (transitions !== 1) continue;
          if (step === 0 ? (p[0] * p[2] * p[4] || p[2] * p[4] * p[6]) : (p[0] * p[2] * p[6] || p[0] * p[4] * p[6])) continue;
          remove.push(i);
        }
      }
      if (remove.length) {
        for (const i of remove) a[i] = 0;
        changed = true;
      }
    }
    if (!changed) break;
  }
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) out[y * w + x] = a[(y + 1) * W + x + 1];
  return out;
}

/** The skeleton's strokes as pen routes, top-left first (ported _routes). Points are [row, col]. */
function routes(skel, w, h) {
  const key = (y, x) => y * w + x;
  const graph = new Map();
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (skel[key(y, x)]) graph.set(key(y, x), new Set());
  for (const k of graph.keys()) {
    const y = Math.floor(k / w);
    const x = k % w;
    for (const [dy, dx] of [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]]) {
      const yy = y + dy;
      const xx = x + dx;
      if (yy < 0 || xx < 0 || yy >= h || xx >= w) continue;
      const q = key(yy, xx);
      if (graph.has(q) && !(dy && dx && (graph.has(key(y + dy, x)) || graph.has(key(y, x + dx))))) graph.get(k).add(q);
    }
  }
  const at = (k) => [Math.floor(k / w), k % w];
  const result = [...graph.keys()].filter((p) => !graph.get(p).size).map((p) => [at(p)]);
  for (;;) {
    const live = [...graph].filter(([, ns]) => ns.size);
    if (!live.length) break;
    const ends = live.filter(([, ns]) => ns.size === 1).map(([p]) => p);
    const candidates = ends.length ? ends : live.map(([p]) => p);
    let start = candidates[0];
    for (const c of candidates) if (c < start) start = c;          // min (row, col) = min key
    const path = [at(start)];
    let prev = null;
    let cur = start;
    while (graph.get(cur).size) {
      let best = null;
      let bestKey = null;
      for (const q of graph.get(cur)) {
        const [cy, cx] = at(cur);
        const [qy, qx] = at(q);
        let pref;
        if (prev === null) pref = [qx < cx ? 1 : 0, qy < cy ? 1 : 0, q];
        else {
          const [py, px] = at(prev);
          const v = [cy - py, cx - px];
          const u = [qy - cy, qx - cx];
          pref = [-(v[0] * u[0] + v[1] * u[1]) / (Math.hypot(...v) * Math.hypot(...u)), q];
        }
        if (!bestKey || lexLess(pref, bestKey)) { best = q; bestKey = pref; }
      }
      graph.get(cur).delete(best);
      graph.get(best).delete(cur);
      prev = cur;
      cur = best;
      path.push(at(cur));
    }
    result.push(path);
  }
  return result.sort((p, q) => {
    const a = [p.length < 3 ? 1 : 0, Math.min(...p.map((v) => v[0])), Math.min(...p.map((v) => v[1]))];
    const b = [q.length < 3 ? 1 : 0, Math.min(...q.map((v) => v[0])), Math.min(...q.map((v) => v[1]))];
    return lexLess(a, b) ? -1 : lexLess(b, a) ? 1 : 0;
  });
}

function lexLess(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return true;
    if (a[i] > b[i]) return false;
  }
  return false;
}

/** For every pixel, the index of the nearest seed pixel (multi-source BFS, 8-neighbours). */
function nearestSeed(seed, w, h) {
  const near = new Int32Array(w * h).fill(-1);
  const queue = new Int32Array(w * h);
  let head = 0;
  let tail = 0;
  for (let i = 0; i < w * h; i++) if (seed[i]) { near[i] = i; queue[tail++] = i; }
  while (head < tail) {
    const i = queue[head++];
    const y = Math.floor(i / w);
    const x = i % w;
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const yy = y + dy;
        const xx = x + dx;
        if ((!dy && !dx) || yy < 0 || xx < 0 || yy >= h || xx >= w) continue;
        const j = yy * w + xx;
        if (near[j] < 0) { near[j] = near[i]; queue[tail++] = j; }
      }
    }
  }
  return near;
}

/** Glyph-stroke handwriting (port of the accepted InkTrace): every glyph, digits included, is written by the pen in
 * reading order. */
export class TextDrawing {
  constructor(lines, size, { color = INK, align = 'left', lineGap = 1.18, pace = 1.0, minDur = 0.6, maxDur = 6.0, pad = 6 } = {}) {
    this.lines = lines;
    this.fsize = size;
    const widths = lines.map((l) => textWidth(l, size));
    const [asc, desc] = fontMetrics(size);
    const lh = Math.trunc(size * lineGap);
    const w = Math.ceil(Math.max(1, ...widths)) + 2 * pad;
    const h = lh * (lines.length - 1) + asc + desc + 2 * pad;
    this.size = [w, h];
    this.ink = canvas(w, h);
    const g = this.ink.getContext('2d');
    g.font = font('hand', size);
    g.fillStyle = css(color);
    g.textBaseline = 'alphabetic';
    const runs = [];
    lines.forEach((line, i) => {
      const x = align === 'left' ? pad : align === 'center' ? pad + (w - 2 * pad - widths[i]) / 2 : w - pad - widths[i];
      const y = pad + i * lh;
      g.fillText(line, x, y + asc);
      const chars = [...line].map((ch, k, arr) => [ch, x + textWidth(arr.slice(0, k).join(''), size),
        x + textWidth(arr.slice(0, k + 1).join(''), size)]);
      const m = g.measureText(line);
      runs.push({ chars, top: Math.max(0, Math.trunc(y + asc - m.actualBoundingBoxAscent) - 2),
        bottom: Math.min(h, Math.ceil(y + asc + m.actualBoundingBoxDescent) + 4) });
    });
    this.trace(runs, pace, minDur, maxDur);
  }

  trace(runs, pace, minDur, maxDur) {
    const [w, h] = this.size;
    const img = this.ink.getContext('2d').getImageData(0, 0, w, h);
    const alpha = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) alpha[i] = img.data[i * 4 + 3];
    this.inkData = img;
    const arrival = new Float32Array(w * h).fill(Infinity);
    const times = [];
    const points = [];
    const down = [];
    let clock = 0;
    let last = null;
    let letters = 0;
    for (const { chars, top, bottom } of runs) {
      for (const [ch, cx0, cx1] of chars) {
        const x0 = Math.max(0, Math.floor(cx0));
        const x1 = Math.min(w, Math.ceil(cx1));
        if (/\s/.test(ch) || x1 <= x0) continue;
        let y0 = -1;
        let y1 = -1;
        for (let y = top; y < bottom; y++) {
          for (let x = x0; x < x1; x++) {
            if (alpha[y * w + x]) { if (y0 < 0) y0 = y; y1 = y + 1; break; }
          }
        }
        if (y0 < 0) continue;
        const pw = x1 - x0;
        const ph = y1 - y0;
        const bin = new Uint8Array(pw * ph);
        for (let y = 0; y < ph; y++) for (let x = 0; x < pw; x++) bin[y * pw + x] = alpha[(y0 + y) * w + x0 + x] > 64 ? 1 : 0;
        const key = `${ch}|${this.fsize}|${pw}x${ph}`;
        let cached = glyphCache.get(key);
        if (!cached) {
          let skel = skeleton(bin, pw, ph);
          if (!skel.some(Boolean)) {                         // too thin to thin: every inked pixel is the route
            skel = new Uint8Array(pw * ph);
            for (let y = 0; y < ph; y++) for (let x = 0; x < pw; x++) skel[y * pw + x] = alpha[(y0 + y) * w + x0 + x] > 0 ? 1 : 0;
          }
          cached = { skel, paths: routes(skel, pw, ph), near: nearestSeed(skel, pw, ph) };
          if (glyphCache.size > 5000) glyphCache.clear();
          glyphCache.set(key, cached);
        }
        const local = new Float32Array(pw * ph).fill(Infinity);
        for (const path of cached.paths) {
          const first = [x0 + path[0][1], y0 + path[0][0]];
          if (last) {
            const lift = 0.08 + Math.min(0.24, Math.hypot(first[0] - last[0], first[1] - last[1]) / 1600);
            times.push(clock, clock + lift);
            points.push(last, first);
            down.push(false, false);
            clock += lift;
          }
          path.forEach(([py, px], j) => {
            const pt = [x0 + px, y0 + py];
            if (j) clock += Math.hypot(pt[0] - last[0], pt[1] - last[1]) / 160;
            local[py * pw + px] = Math.min(local[py * pw + px], clock);
            times.push(clock);
            points.push(pt);
            down.push(true);
            last = pt;
          });
          if (path.length === 1) clock += 0.015;
        }
        for (let y = 0; y < ph; y++) {
          for (let x = 0; x < pw; x++) {
            const gi = (y0 + y) * w + x0 + x;
            if (!alpha[gi]) continue;
            const s = cached.near[y * pw + x];
            const t = s >= 0 ? local[s] : Infinity;
            if (t < arrival[gi]) arrival[gi] = t;
          }
        }
        letters += 1;
      }
    }
    if (!times.length) {
      this.duration = 0.01;
      this.times = [0];
      this.points = [[0, 0]];
      this.down = [false];
      this.arrival = new Float32Array(w * h);
      this.order = new Int32Array(0);
      return;
    }
    const finite = new Uint8Array(w * h);
    let missing = false;
    for (let i = 0; i < w * h; i++) {
      if (Number.isFinite(arrival[i])) finite[i] = 1;
      else if (alpha[i]) missing = true;
    }
    if (missing) {                                          // stray ink joins its nearest traced pixel
      const near = nearestSeed(finite, w, h);
      for (let i = 0; i < w * h; i++) if (alpha[i] && !finite[i] && near[i] >= 0) arrival[i] = arrival[near[i]];
    }
    const duration = (0.4 + 0.055 * letters + 0.18 * (runs.length - 1)) / pace;
    this.duration = Math.min(maxDur, Math.max(minDur, duration));
    const scale = this.duration / Math.max(clock, 0.001);
    const inkPixels = [];
    for (let i = 0; i < w * h; i++) {
      if (alpha[i]) {
        arrival[i] *= scale;
        inkPixels.push(i);
      }
    }
    this.arrival = arrival;
    this.order = Int32Array.from(inkPixels.sort((a, b) => arrival[a] - arrival[b]));
    this.times = times.map((t) => t * scale);
    this.points = points;
    this.down = down;
    this.reset();
  }

  reset() {
    this.revealed = 0;
    this.lastE = -1;
    this.outData = null;
  }

  state(elapsed) {
    if (elapsed < 0) return { img: null, pen: null, down: false };
    if (elapsed >= this.duration) return { img: this.ink, pen: null, down: false };
    const [w, h] = this.size;
    if (!this.outData || elapsed < this.lastE) {
      this.out ??= canvas(w, h);
      this.outData = new ImageData(w, h);
      this.revealed = 0;
    }
    const src = this.inkData.data;
    const dst = this.outData.data;
    while (this.revealed < this.order.length && this.arrival[this.order[this.revealed]] <= elapsed) {
      const i = this.order[this.revealed++] * 4;
      dst[i] = src[i]; dst[i + 1] = src[i + 1]; dst[i + 2] = src[i + 2]; dst[i + 3] = src[i + 3];
    }
    this.lastE = elapsed;
    this.out.getContext('2d').putImageData(this.outData, 0, 0);
    let lo = 0;
    let hi = this.times.length;
    while (lo < hi) {                                       // searchsorted(times, elapsed, 'right')
      const mid = (lo + hi) >> 1;
      if (this.times[mid] <= elapsed) lo = mid + 1; else hi = mid;
    }
    const j = Math.min(this.times.length - 1, lo);
    const i = Math.max(0, j - 1);
    const span = this.times[j] - this.times[i];
    const f = span <= 0 ? 0 : Math.min(1, Math.max(0, (elapsed - this.times[i]) / span));
    const pen = [this.points[i][0] * (1 - f) + this.points[j][0] * f, this.points[i][1] * (1 - f) + this.points[j][1] * f];
    return { img: this.out, pen, down: this.down[j] };
  }
}

// --------------------------------------------------------------- static stamps
/** A picture that fades in over `pop` seconds (the pinned mini note, invisible anchors). */
export class StaticDrawing {
  constructor(image, pop = 0.35) {
    this.image = image;
    this.size = [image.width, image.height];
    this.duration = pop;
  }

  state(elapsed) {
    if (elapsed < 0) return { img: null, pen: null, down: false };
    if (elapsed >= this.duration) return { img: this.image, pen: null, down: false };
    this.out ??= canvas(...this.size);
    const g = this.out.getContext('2d');
    g.clearRect(0, 0, this.out.width, this.out.height);
    g.globalAlpha = elapsed / this.duration;
    g.drawImage(this.image, 0, 0);
    g.globalAlpha = 1;
    return { img: this.out, pen: null, down: false };
  }
}

export function circlePoints(cx, cy, rx, ry, { start = -Math.PI / 2, turns = 1.0, n = 90, wobble = 0 } = {}) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const t = n === 1 ? 0 : 2 * Math.PI * turns * i / (n - 1);
    const rr = 1 + wobble * Math.sin(t * 3);
    out.push([cx + rx * rr * Math.cos(start + t), cy + ry * rr * Math.sin(start + t)]);
  }
  return out;
}

// ------------------------------------------------------------------------ hand
/** J's drawing hand (assets/hand): pasted with its nib on the pen point, a soft shadow below. */
export class Hand {
  static async load(read) {
    const hand = new Hand();
    hand.img = await createImageBitmap(new Blob([await read('assets/hand/hand.png')], { type: 'image/png' }));
    const anchor = JSON.parse(new TextDecoder().decode(await read('assets/hand/hand.json')));
    hand.tip = [anchor.tip_x, anchor.tip_y];
    const s = canvas(hand.img.width + 60, hand.img.height + 60);
    const g = s.getContext('2d');
    g.filter = 'blur(9px)';
    const silhouette = canvas(hand.img.width, hand.img.height);
    const sg = silhouette.getContext('2d');
    sg.drawImage(hand.img, 0, 0);
    sg.globalCompositeOperation = 'source-in';
    sg.fillStyle = 'rgba(0,0,0,0.18)';
    sg.fillRect(0, 0, silhouette.width, silhouette.height);
    g.drawImage(silhouette, 30, 30);
    hand.shadow = s;
    return hand;
  }

  paste(g, point, lifted = false) {
    const x = Math.round(point[0] - this.tip[0]);
    const y = Math.round(point[1] - this.tip[1] - (lifted ? 6 : 0));
    g.drawImage(this.shadow, x + 14 - 30, y + 18 - 30);
    g.drawImage(this.img, x, y);
  }
}

export async function loadPaper(read) {
  return createImageBitmap(new Blob([await read('assets/paper.png')], { type: 'image/png' }));
}

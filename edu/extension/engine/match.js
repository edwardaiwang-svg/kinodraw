// Find doodles for a piece of text: literal keyword hits first, then meaning (port of kinodraw/director/match.py).
//
// The catalog, its vectors and the embedding model come from engine/assets.js (the same files the Python app ships
// and the same bge-small model), so both find the same doodles.

export const EN_STOP = new Set(`a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those there here they them their we our you your he she his her i me my mine us not no yes do does did
done can could will would should may might must shall have has had just also very really more most much many few less
least some any all each every other another such same own than too only even still again ever never always often
sometimes first second third last next new old good bad big small great little long short high low one two three four
five six seven eight nine ten hundred thousand million billion way thing things time times day days year years people
make makes made take takes took get gets got go goes went come comes came see sees saw look looks know knows knew
think thinks thought say says said tell told use uses used want wants like likes need needs place part point case
number kind lot lots back up down out over under into onto about after before between during while where when why how
what which who whom whose because though although until since per via today now then once full turn
turns check step steps end side form set sort white black red blue green yellow orange pink purple brown gray grey
colour color colours colors`.split(/\s+/));

export class Hit {
  constructor(id, score, phrase = null, start = -1) {
    this.id = id;
    this.score = score;
    this.phrase = phrase;          // the text that matched (label and trigger); null for meaning-only matches
    this.start = start;            // where the phrase starts in the text
  }
}

export function singular(word) {
  if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3) + 'y';
  if (word.length > 4 && /(ches|shes|sses|xes)$/.test(word)) return word.slice(0, -2);
  if (word.length > 3 && word.endsWith('s') && !/(ss|us|is)$/.test(word)) return word.slice(0, -1);
  return word;
}

export const enKey = (text) => (text.toLowerCase().match(/[a-z0-9']+/g) || []).map(singular).join(' ');

/** Rows of `vecs` (Float32Array, n × dim) dotted with `q` → Float64Array of n similarities. */
export function dots(vecs, q, dim = q.length) {
  const n = vecs.length / dim;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    const o = i * dim;
    for (let j = 0; j < dim; j++) s += vecs[o + j] * q[j];
    out[i] = s;
  }
  return out;
}

export function normalizeRows(rows) {
  return rows.map((v) => {
    let s = 0;
    for (const x of v) s += x * x;
    const k = 1 / (Math.sqrt(s) + 1e-9);
    return Float32Array.from(v, (x) => x * k);
  });
}

/** Indices of `values` sorted high to low (numpy's argsort(-values)). */
export const argsortDesc = (values) => [...values.keys()].sort((a, b) => values[b] - values[a] || a - b);

export class Matcher {
  /** assets: { catalog: {ids, entries}, embedVectors: Float32Array, dim }; embedder: async (texts) → vectors */
  constructor(assets, embedder, { excludeCategories = ['narrator'] } = {}) {
    this.embedder = embedder;
    this.entries = {};
    for (const [id, e] of Object.entries(assets.catalog.entries)) {
      if (!excludeCategories.includes(e.category)) this.entries[id] = e;
    }
    this.index = new Map();
    for (const [id, e] of Object.entries(this.entries)) {
      let keywords = e.en || [];
      if (e.set === 'fluent') keywords = keywords.slice(0, 6);
      keywords.forEach((kw, rank) => {
        const key = enKey(kw);
        if (!key || EN_STOP.has(key) || key.length < 3 || /^\d+$/.test(key)) return;
        const weight = (1.0 - 0.04 * Math.min(rank, 5)) * (e.set === 'bespoke' ? 1.08 : 0.8);
        if (!this.index.has(key)) this.index.set(key, []);
        this.index.get(key).push([id, weight]);
      });
    }
    // keywords shared by many doodles say little about any one of them
    this.rarity = new Map([...this.index].map(([k, v]) => [k, 1 / (1 + Math.log(v.length))]));
    const dim = assets.dim;
    const keep = assets.catalog.ids.map((id, k) => [id, k]).filter(([id]) => id in this.entries);
    this.ids = keep.map(([id]) => id);
    this.vecs = new Float32Array(keep.length * dim);
    keep.forEach(([, k], row) => this.vecs.set(assets.embedVectors.subarray(k * dim, (k + 1) * dim), row * dim));
    this.dim = dim;
  }

  /** Keyword hits, best first: one per doodle, or (everyPhrase) one per doodle and phrase, so every picture a
   * word could mean competes for that word. */
  lexical(text, everyPhrase = false) {
    const hits = new Map();
    const words = [...text.matchAll(/[A-Za-z0-9']+/g)].map((m) => [m[0], m.index]);
    for (const n of [3, 2, 1]) {
      for (let i = 0; i + n <= words.length; i++) {
        const chunk = words.slice(i, i + n);
        const key = chunk.map(([w]) => singular(w.toLowerCase())).join(' ');
        for (const [id, weight] of this.index.get(key) || []) {
          const score = weight * this.rarity.get(key) + 0.15 * (n - 1);
          const start = chunk[0][1];
          const last = chunk[chunk.length - 1];
          const phrase = text.slice(start, last[1] + last[0].length);
          const k = everyPhrase ? `${id}@${start}` : id;
          if (!hits.has(k) || hits.get(k).score < score) hits.set(k, new Hit(id, score, phrase, start));
        }
      }
    }
    return [...hits.values()].sort((a, b) => b.score - a.score);
  }

  async semantic(text, k = 5) {
    const [query] = normalizeRows(await this.embedder([text]));
    const sims = dots(this.vecs, query, this.dim);
    return argsortDesc(sims).slice(0, k).map((i) => new Hit(this.ids[i],
      sims[i] + (this.entries[this.ids[i]].set === 'bespoke' ? 0.02 : 0)));
  }
}

// Offline director: add visuals to every beat with simple, predictable rules (port of kinodraw/director/rules.py,
// English). Read the Python module's docstring for the rules themselves; this file follows it line for line so that
// tests/rules.test.mjs can hold both to the same storyboards.
import { normalize as normalizeNumbers } from './numbers.js';
import { pyRound, sentences as splitSentences, size as wordCount } from './script.js';
import { EN_STOP, Hit, Matcher, argsortDesc, dots, normalizeRows, singular } from './match.js';
import { normalizeStoryboard } from './storyboard.js';

const AGREE = { bespoke: [0.40, 0.60], fluent: [0.48, 0.63] };
const MEANING_ONLY = 0.58;                 // a doodle with no literal hit must match this well,
const MEANING_STRONG = 0.65;               // ... and below this, share a word with its sentence
const NAMED_EASE = 0.06;                   // a drawing whose description names the words may agree less
export const LABEL_MAX = 22;
const CAUSE = /\b(so|because|therefore|thus|leads? to|led to|causes?|caused|turns? (?:\w+ )?into|becomes?|makes?)\b/i;
const CONTRAST = /\b(versus|vs\.?|rather than|instead of|compared (?:to|with)|unlike)\b/i;
const PLUS = /\b(and|with|plus)\b/i;
const LABEL_STOP = new Set(('a an the of to in on at by for with from and or but is are was were be been it its this that '
  + 'these those there their our your his her more most than about over under into').split(' '));
const PREPOSITIONS = ['in', 'inside', 'into', 'of', 'on', 'onto', 'with', 'within', 'from', 'by', 'at', 'as', 'through'];
const LIST_GAP = /^\s*(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)(?:(?:a|an|the|some|many|their|his|her|its)\s+)?$/i;
const RECENT = 4;                          // pictures still on the board: a word waits for its own
const TOPIC_RANK = 100;
const MEANING_TOPIC_RANK = 60;
const SENSE_MARGIN = 0.03;
const GENERIC = new Set(('invention technology device gadget product item object equipment material stuff thing '
  + 'innovation creation machine together').split(' '));
const EMOJI_ADJ = new Set(('red orange yellow green blue purple brown black white pink gray grey light dark small large big '
  + 'little tiny new old open closed full empty round square hot cold high low happy sad smiling grinning rolling fallen').split(' '));
const EMOJI_ALSO = { fl_snowflake: ['snow'] };      // emoji a shorter word may call up: snow is drawn as a snowflake
const PHENOMENA = new Set(('light sound heat energy power force gravity electricity radiation magnetism friction '
  + 'pressure temperature').split(' '));
const IDIOMS = new RegExp(String.raw`\b(?:(?:in )?a matter of|no matter|as a matter of fact|in terms of|in light of|`
  + String.raw`on the other hand|at hand|in fact|of course|at (?:least|most|first|last|all)|in time|on time|`
  + String.raw`in charge|(?:take|takes|took|taken) place|(?:make|makes|made) sense|in turn|by and large|`
  + String.raw`all in all|at the same time|in general|in particular|for (?:example|instance)|so far|`
  + String.raw`as well|in other words|the bottom line|a (?:lot|number|couple) of)\b`, 'gi');
const PEOPLE_OF = new RegExp(String.raw`\b(?:team|group|crew|army|band|gang|staff|crowd|pair|couple|class|family|tribe|club|`
  + String.raw`society|guild|union|community|generation)s? of\s+(?:[a-z-]+\s+)?$`, 'i');
const PEOPLE_CATEGORIES = new Set(['people', 'narrator', 'People & Body']);
const PEOPLE_DESC = new RegExp(String.raw`\b(?:people|person|persons|man|woman|men|women|teacher|teachers|students?|pupils?|children|`
  + String.raw`child|kids?|boy|girl|family|crowd|team|workers?|narrator)\b`, 'i');
const NEGATION = /\b(?:no|not|without|never|nor|neither|non)\s+(?:[a-z-]+\s+)?$/i;
const NUMERAL = /^[\d零一二三四五六七八九十百千万亿两.,:：%]+$/;
const DETERMINERS = new Set(('a an the this that these those his her its their our your my every each all some many several '
  + 'most more no any').split(' '));
const PREPS = new Set(('in on at by for with from of to into onto across through over under about after before between during '
  + 'since until around near within without against among toward towards throughout upon via like').split(' '));
const AUX = new Set('is are was were be been being has have had do does did will would can could shall should may might must'.split(' '));
const CONNECTIVES = new Set('when while as and where after before because since then which who whose once'.split(' '));
const PAST = new Set(('spread ran began became made took came went grew fell rose led brought built found wrote gave got held '
  + 'kept left lost met paid put said sent sold stood taught thought told won').split(' '));
const NARRATOR_CUES = [
  ['worried', /\b(risk|danger|dangerous|problem|worry|worried|fear|threat|crisis|mistake|warning)\b/i],
  ['thumbs', /\b(success|succeeded|great news|win|won|works|better|best)\b/i],
  ['magnifier', /\b(research|study|studies|evidence|investigat\w*|discover\w*)\b/i],
  ['explain', /\b(remember|key|important|lesson|means|in short)\b/i],
];

const isAscii = (s) => /^[\x00-\x7f]*$/.test(s);
const words = (s, re = /[a-z]+/g) => s.match(re) || [];
export function singularWords(phrase) {
  if (!isAscii(phrase)) return new Set();
  return new Set(words(phrase).filter((w) => !EN_STOP.has(w)).map((w) => w.replace(/s+$/, '')));
}
const intersects = (a, b) => [...a].some((x) => b.has(x));
const round3 = (x) => Number(x.toFixed(3));
const isUpper = (ch) => /\p{Lu}/u.test(ch);

export class RulesDirector {
  /** assets: from engine/assets.js; embedder: async (texts: string[]) → Float32Array[] (raw model output) */
  constructor(assets, embedder) {
    this.embedder = embedder;
    this.matcher = new Matcher(assets, embedder);
    this.ids = this.matcher.ids;
    this.vecs = this.matcher.vecs;
    this.dim = this.matcher.dim;
    this.pos = new Map(this.ids.map((id, k) => [id, k]));
    const at = new Map(assets.catalog.ids.map((id, k) => [id, k]));
    this.pics = new Float32Array(this.ids.length * this.dim);
    this.ids.forEach((id, row) => {
      const k = at.get(id);
      this.pics.set(assets.pictureVectors.subarray(k * this.dim, (k + 1) * this.dim), row * this.dim);
    });
    this.topic = {};                       // chapter -> rank of every picture for its subject
    this.pictures = new Map();             // word -> the picture it got first
    this.bannedWords = new Set((assets.banned.words.en || []).map(singular));
  }

  entry(id) { return this.matcher.entries[id]; }

  // ------------------------------------------------------------ entry point
  async direct(board) {
    const chapters = Object.fromEntries(normalizeStoryboard(board).chapters.map((c) => [c.id, c]));
    const recent = [];                     // pictures still on the board (last RECENT)
    const remember = (ids) => { for (const id of ids) { recent.push(id); if (recent.length > RECENT) recent.shift(); } };
    const heroes = {};                     // chapter -> {doodle: best score}, for takeaway margins
    let sinceNarrator = 99;
    this.topic = await this.topicRanks(board);
    this.pictures = new Map();
    const [timelines, held] = await this.timelines(board);
    let current = null;
    for (const beat of board.beats) {
      beat.visuals = [];
      const kind = beat.kind;
      const chapter = chapters[beat.chapter];
      if (beat.chapter !== current) {      // a new chapter starts on a clean board
        current = beat.chapter;
        recent.length = 0;
      }
      if (['title', 'agenda', 'opener'].includes(kind) || chapter.kind === 'intro') continue;
      if (kind === 'closing') {
        beat.visuals.push(this.cluster(beat, [this.item('narrator_wave')], 0));
        continue;
      }
      const text = beat.display.en;
      const norm = normalizeNumbers(text);
      if (kind === 'take') {
        const best = Object.entries(heroes[beat.chapter] || {}).sort((a, b) => b[1] - a[1]).slice(0, 2);
        best.forEach(([id], k) => beat.visuals.push({ ...this.cluster(beat, [this.item(id)], k), size: 'margin' }));
        continue;
      }
      const sentences = splitSentences(text).length ? splitSentences(text) : [text];
      const spans = [];
      let cursor = 0;
      for (const sentence of sentences) {
        const start = text.indexOf(sentence, cursor);
        spans.push([start, start + sentence.length]);
        cursor = start + sentence.length;
      }
      const sentenceOf = (pos) => {
        const k = spans.findIndex(([a, b]) => a <= pos && pos < b);
        return k >= 0 ? k : spans.length - 1;
      };
      let budget = this.budget(text);
      let planned = [];                    // [position in text, visual]
      const taken = new Set();             // sentences that already have a visual
      if (timelines[beat.id]) {            // the page comes in with the first date said
        planned.push([held[beat.id][0], timelines[beat.id]]);
        budget -= 1;
      }
      for (const detect of [this.quote, this.definition, this.number]) {
        if (budget <= 0) break;
        const found = await detect.call(this, beat, text, norm, recent);
        if (found) {
          const [v, pos] = found;
          planned.push([pos, v]);
          taken.add(sentenceOf(pos));
          budget -= 1;
        }
      }
      const question = sentences.findIndex((s) => s.endsWith('?') || s.endsWith('？'));
      if (question >= 0 && !taken.has(question) && budget > 0 && sinceNarrator >= 3) {
        const q = sentences[question];
        const label = q.length <= LABEL_MAX ? q : null;
        planned.push([spans[question][0], this.cluster(beat, [this.item('narrator_think', label, this.spoken(norm, q))],
          planned.length)]);
        taken.add(question);
        budget -= 1;
        sinceNarrator = 0;
      }
      let hits = await this.concepts(text, recent, beat.chapter);
      const terms = planned.filter(([, v]) => v.type === 'glossary').map(([, v]) => this.key(v.term.en));
      hits = hits.filter((h) => !(h.phrase && terms.some((t) => this.inside(this.key(h.phrase), t))));
      let usedWords = new Set();           // (a defined term is shown by its note, not by its words)
      const drawn = new Set();             // pictures already in this beat: each is drawn once
      const listed = (await this.concepts(text, [], beat.chapter, true))
        .filter((h) => !terms.some((t) => this.inside(this.key(h.phrase), t)));
      for (const group of this.lists(text, listed)) {   // every listed thing, side by side (even if drawn before)
        if (budget <= 0) break;
        const items = group.map((h) => this.item(h.id, this.label(h.phrase), this.spoken(norm, h.phrase, h.start)));
        planned.push([group[0].start, this.cluster(beat, items, planned.length)]);
        taken.add(sentenceOf(group[0].start));
        const spots = group.map((h) => [h.start, h.start + h.phrase.length]);
        hits = hits.filter((h) => !(h.phrase && spots.some(([a, b]) => (a <= h.start && h.start < b)
          || (h.start <= a && a < h.start + h.phrase.length))));
        usedWords = new Set([...usedWords, ...singularWords(group.map((h) => h.phrase.toLowerCase()).join(' '))]);
        remember(group.map((h) => h.id));
        for (const h of group) drawn.add(h.id);
        budget -= 1;
        for (const h of group) {
          if (!this.pictures.has(this.key(h.phrase))) this.pictures.set(this.key(h.phrase), h.id);
          const section = (heroes[beat.chapter] ??= {});
          section[h.id] = Math.max(section[h.id] ?? 0, h.score);
        }
      }
      for (const sweep of [0, 1]) {        // one doodle per free sentence first, then extras
        for (let k = 0; k < spans.length; k++) {
          const [a, b] = spans[k];
          if (budget <= 0 || (sweep === 0 && taken.has(k))) continue;
          const local = hits.filter((h) => a <= h.start && h.start < b && !drawn.has(h.id)
            && !intersects(singularWords((h.phrase || '').toLowerCase()), usedWords));
          if (!local.length) continue;
          const group = this.pair(text, local, planned.map(([pos]) => pos));
          hits = hits.filter((h) => !group.includes(h));
          for (const h of group) drawn.add(h.id);
          usedWords = new Set([...usedWords, ...singularWords(group.map((g) => (g.phrase || '').toLowerCase()).join(' '))]);
          const items = group.map((h) => this.item(h.id, this.label(h.phrase),
            this.spoken(norm, h.phrase || this.lead(text, h.start), h.start)));
          const relation = group.length === 2 ? this.relation(text, group) : 'none';
          planned.push([group[0].start, { ...this.cluster(beat, items, planned.length), relation }]);
          taken.add(k);
          remember(group.map((h) => h.id));
          budget -= 1;
          for (const h of group) {
            if (h.phrase) {
              if (!this.pictures.has(this.key(h.phrase))) this.pictures.set(this.key(h.phrase), h.id);
              const section = (heroes[beat.chapter] ??= {});
              section[h.id] = Math.max(section[h.id] ?? 0, h.score);
            }
          }
        }
      }
      if ((!planned.length && sinceNarrator >= 2) || (sinceNarrator >= 5 && budget > 0)) {
        const pose = this.narratorPose(text) || (!planned.length ? 'explain' : null);
        if (pose) {
          planned.push([text.length, this.cluster(beat, [this.item(`narrator_${pose}`)], planned.length)]);
          sinceNarrator = 0;
        }
      }
      if (held[beat.id]) {                 // a timeline holds the board between its first and last date
        const [lo, hi] = held[beat.id];    // (a picture without words comes as the beat starts)
        planned = planned.filter(([pos, v]) => v.type === 'lanes' || !(lo <= (v.trigger ? pos : 0) && (v.trigger ? pos : 0) <= hi));
      }
      beat.visuals = planned.map((pv, i) => [pv, i]).sort((x, y) => x[0][0] - y[0][0] || x[1] - y[1]).map(([[, v]]) => v);
      sinceNarrator += 1;
    }
    return board;
  }

  // -------------------------------------------------------------- helpers
  budget(text) {                            // about one visual per 9 words (1-5 per beat)
    return Math.max(1, Math.min(5, pyRound(wordCount(text) / 9)));
  }

  item(doodle, label = null, trigger = null) {
    const item = { doodle };
    if (label) item.label = { en: label };
    if (trigger) item.trigger = { en: trigger };
    return item;
  }

  cluster(beat, items, k) {
    const v = { id: `${beat.id}v${k}`, type: 'cluster', items, relation: 'none' };
    const first = items.find((it) => it.trigger)?.trigger;
    if (first) v.trigger = first;
    return v;
  }

  /** The spoken words for a display phrase (a trigger), or null. */
  spoken(norm, phrase, start = -1) {
    if (!phrase) return null;
    const said = start < 0 ? norm.find(phrase)
      : norm.spoken.slice(norm.toSpoken(start), norm.toSpoken(start + phrase.length)).trim() || null;
    return said && norm.spoken.includes(said) ? said : null;
  }

  /** The first few words from `start`: the trigger for a doodle matched by meaning, not by a word. */
  lead(text, start) {
    return text.slice(start).split(/\s+/).filter(Boolean).slice(0, 3).join(' ');
  }

  label(phrase) {
    if (!phrase || phrase.length > LABEL_MAX) return null;
    return phrase.slice(0, 1).toUpperCase() + phrase.slice(1);
  }

  async sentenceVectors(texts) {
    return normalizeRows(await this.embedder(texts));
  }

  agree(id, vec) {
    const o = this.pos.get(id) * this.dim;
    let s = 0;
    for (let j = 0; j < this.dim; j++) s += this.vecs[o + j] * vec[j];
    return s;
  }

  picture(id, vec) {
    const o = this.pos.get(id) * this.dim;
    let s = 0;
    for (let j = 0; j < this.dim; j++) s += this.pics[o + j] * vec[j];
    return s;
  }

  /** Doodles for this text, best first (see the Python docstring). `listing`: one hit per phrase, literal only. */
  async concepts(text, recent, chapter, listing = false) {
    const sentences = splitSentences(text).length ? splitSentences(text) : [text];
    const vecs = await this.sentenceVectors(sentences);
    const found = new Map();
    let offset = 0;
    for (let s = 0; s < sentences.length; s++) {
      const sentence = sentences[s];
      const vec = vecs[s];
      const base = text.indexOf(sentence, offset);
      offset = Math.max(offset, base);
      const plain = sentence.replace(IDIOMS, (m) => ' '.repeat(m.length));      // idioms are not pictures
      const senses = new Map();            // word -> [[hit, score]]: the pictures competing for it
      const named = [];                    // starts of words that name some picture
      const hits = this.matcher.lexical(plain, true);
      const compounds = hits.filter((h) => this.key(h.phrase).split(' ').length > 1)
        .map((h) => [h.start, h.start + h.phrase.length]);
      for (const hit of hits) {
        named.push(hit.start);
        const key = this.key(hit.phrase);
        const a = hit.start;
        const b = hit.start + hit.phrase.length;
        if (compounds.some(([x, y]) => x <= a && b <= y && (x !== a || y !== b))) continue;   // "global warming"
        if (NEGATION.test(plain.slice(Math.max(0, a - 24), a))) continue;                    // "no engine"
        if (plain.slice(b, b + 1) === '-') continue;                                          // "oil-based ink"
        if (PEOPLE_OF.test(plain.slice(Math.max(0, a - 32), a)) && !this.showsPeople(hit.id)) continue;
        if (GENERIC.has(key) || NUMERAL.test(key) || this.banned(key) || !this.belongs(hit.id, hit.phrase, chapter)) continue;
        if (PHENOMENA.has(key) && this.entry(hit.id).set === 'fluent') continue;
        const agree = this.agree(hit.id, vec);
        let [lo, hi] = AGREE[this.entry(hit.id).set];
        if (this.entry(hit.id).set === 'bespoke' && this.names(hit.id, hit.phrase)) {
          lo -= NAMED_EASE;                // "doctors": a doctor's stethoscope
          hi -= NAMED_EASE;
        }
        const score = hit.score * Math.max(0, Math.min(1, (agree - lo) / (hi - lo)));
        if (score > (listing ? 0 : 0.15)) {
          if (!senses.has(key)) senses.set(key, []);
          senses.get(key).push([hit, score]);
        }
      }
      const blocked = [];                  // spans whose picture was used moments ago
      const ordered = [...senses].sort((x, y) => Math.max(...y[1].map(([, sc]) => sc)) - Math.max(...x[1].map(([, sc]) => sc)));
      for (const [key, cands] of ordered) {
        const chosen = await this.sense(key, cands, sentence);
        if (!chosen) continue;
        const [hit, score] = chosen;
        const a = hit.start;
        const b = hit.start + hit.phrase.length;
        if (blocked.some(([x, y]) => (x <= a && a < y) || (x < b && b <= y))) continue;
        if (recent.includes(hit.id)) {     // never a second-best meaning instead
          blocked.push([a, b]);
          continue;
        }
        const slot = listing ? `@${base + hit.start}` : hit.id;
        if (!found.has(slot) || found.get(slot).score < score) found.set(slot, new Hit(hit.id, score, hit.phrase, base + hit.start));
      }
      if (listing) continue;
      const lead = this.lead(sentence, 0).length;          // a meaning-only doodle is drawn on the first words
      const shared = new Set(words(sentence.toLowerCase(), /[a-z]{4,}/g).filter((w) => !EN_STOP.has(w)).map((w) => w.slice(0, 5)));
      const sims = dots(this.vecs, vec, this.dim);
      for (const i of argsortDesc(sims).slice(0, 3)) {
        const id = this.ids[i];
        if (sims[i] >= MEANING_ONLY && !recent.includes(id) && !found.has(id) && this.entry(id).set === 'bespoke'
            && this.topic[chapter][i] <= MEANING_TOPIC_RANK && !named.some((s0) => s0 < lead)
            && (sims[i] >= MEANING_STRONG || this.shares(id, shared))) {
          found.set(id, new Hit(id, sims[i] - MEANING_ONLY + 0.1, null, base));
        }
      }
    }
    const ranked = [...found.values()].sort((x, y) => y.score - x.score);
    const seen = new Set();
    const out = [];
    for (const h of ranked) {              // one doodle per phrase
      const key = (h.phrase || `@${h.start}`).toLowerCase();
      if (!seen.has(key)) {
        seen.add(key);
        out.push(h);
      }
    }
    return out;
  }

  /** Runs of listed things ("a book, a newspaper or a website"): 2-3 named pictures in a row with only commas,
   * "and"/"or" and a determiner between them, at least one comma among them. */
  lists(text, hits) {
    hits = hits.filter((h) => h.phrase).map((h, i) => [h, i]).sort((x, y) => x[0].start - y[0].start || x[1] - y[1]).map(([h]) => h);
    const runs = [];
    let run = [];
    let commas = 0;
    for (const h of hits) {
      if (run.length) {
        const prev = run[run.length - 1];
        const gap = text.slice(prev.start + prev.phrase.length, h.start);
        if (h.start >= prev.start + prev.phrase.length && LIST_GAP.test(gap)) {
          run.push(h);
          commas += /[,、，]/.test(gap) ? 1 : 0;
          continue;
        }
        if (run.length >= 2 && commas) runs.push(run.slice(0, 3));
      }
      run = [h];
      commas = 0;
    }
    if (run.length >= 2 && commas) runs.push(run.slice(0, 3));
    return runs;
  }

  shares(id, shared) {
    return words((this.entry(id).desc || '').toLowerCase(), /[a-z]{4,}/g).some((w) => shared.has(w.slice(0, 5)));
  }

  showsPeople(id) {
    const e = this.entry(id);
    return PEOPLE_CATEGORIES.has(e.category) || PEOPLE_DESC.test(e.desc || '');
  }

  banned(key) {                             // a word that never gets a picture (church, Germany, scientists...)
    return key.split(' ').some((w) => this.bannedWords.has(w));
  }

  // ---------------------------------------------------------- meaning rules
  key(phrase) {
    return (phrase.toLowerCase().match(/[a-z0-9']+/g) || []).map(singular).join(' ');
  }

  /** chapter -> rank (1 = closest) of every picture for what the chapter, within the whole video, is about. */
  async topicRanks(board) {
    const texts = new Map();
    for (const b of board.beats) {
      if (!texts.has(b.chapter)) texts.set(b.chapter, []);
      texts.get(b.chapter).push(b.display.en);
    }
    const chapters = [...texts.keys()];
    const vecs = await this.sentenceVectors([...chapters.map((c) => texts.get(c).join(' ')),
      [...texts.values()].map((t) => t.join(' ')).join(' ')]);
    const all = vecs[vecs.length - 1];
    const out = {};
    chapters.forEach((c, k) => {
      const q = Float32Array.from(vecs[k], (x, j) => x + all[j]);
      const n = Math.hypot(...q);
      const order = argsortDesc(dots(this.pics, q.map((x) => x / n), this.dim));
      const rank = new Int32Array(order.length);
      order.forEach((i, r) => { rank[i] = r + 1; });
      out[c] = rank;
    });
    return out;
  }

  /** May this picture stand for these words here? (see the Python docstring) */
  belongs(id, phrase, chapter) {
    const onTopic = this.topic[chapter][this.pos.get(id)] <= TOPIC_RANK;
    if (this.entry(id).set === 'fluent') return onTopic && (!phrase || this.isHead(id, phrase));
    return onTopic || (Boolean(phrase) && this.names(id, phrase));
  }

  /** The words say what the drawing shows: they are all in its description. */
  names(id, phrase) {
    const shown = new Set(words((this.entry(id).desc || '').toLowerCase()).map(singular));
    const said = words(phrase.toLowerCase()).filter((w) => !EN_STOP.has(w)).map(singular);
    return said.length > 0 && said.every((w) => shown.has(w));
  }

  /** An emoji named 'light blue heart' is a heart; one named 'ferris wheel' needs 'Ferris wheel' said. */
  isHead(id, phrase) {
    const name = (this.entry(id).desc || '').toLowerCase().split(/\b(?:at|with|of|in|on|for|from|to|and|or)\b/)[0];
    const nameWords = words(name);
    const said = words(phrase.toLowerCase()).map(singular);
    if (said.length && (EMOJI_ALSO[id] || []).includes(said[said.length - 1])) return true;
    if (!nameWords.length || singular(nameWords[nameWords.length - 1]) !== said[said.length - 1]) return false;
    return nameWords.slice(0, -1).every((w) => EMOJI_ADJ.has(w) || said.includes(singular(w)));
  }

  /** Which picture a word gets: the one it had before, else its best-tagged picture, unless another sense clearly
   * fits the sentence better with the word itself hidden. */
  async sense(key, cands, sentence) {
    const first = this.pictures.get(key);
    if (first) return cands.find(([h]) => h.id === first) || null;
    const best = cands.reduce((x, y) => (y[1] > x[1] ? y : x));
    if (cands.length === 1) return best;
    const [hidden] = await this.sentenceVectors([sentence.split(best[0].phrase).join(' ')]);
    const fit = new Map(cands.map(([h]) => [h.id, this.picture(h.id, hidden)]));
    const rival = cands.reduce((x, y) => (fit.get(y[0].id) > fit.get(x[0].id) ? y : x));
    return fit.get(rival[0].id) >= fit.get(best[0].id) + SENSE_MARGIN ? rival : best;
  }

  inside(key, term) {                      // are the words of `key` part of `term`?
    const t = new Set(term.split(' '));
    return key.split(' ').every((w) => t.has(w));
  }

  /** The best hit, plus a second nearby hit about something else (never across another picture said between). */
  pair(text, hits, taken = []) {
    const first = hits[0];
    for (const other of hits.slice(1, 4)) {
      if (!(other.phrase && first.phrase) || Math.abs(other.start - first.start) >= 90) continue;
      const lo = Math.min(first.start, other.start);
      const hi = Math.max(first.start, other.start);
      if (taken.some((pos) => lo < pos && pos < hi)) continue;
      const a = first.phrase.toLowerCase();
      const b = other.phrase.toLowerCase();
      if (a.includes(b) || b.includes(a) || intersects(singularWords(a), singularWords(b))) continue;
      return [first, other].sort((x, y) => x.start - y.start);
    }
    return [first];
  }

  /** The short noun phrase right after a number: '20 million books were' -> 'books'. */
  nounAfter(rest) {
    const out = [];
    for (const w of rest.slice(0, 60).match(/[A-Za-z][\w'-]*/g) || []) {
      if (LABEL_STOP.has(w.toLowerCase()) || out.length === 3) {
        if (out.length) break;
        continue;
      }
      out.push(w);
    }
    return out.join(' ').slice(0, LABEL_MAX);
  }

  relation(text, pair) {
    const between = text.slice(pair[0].start + (pair[0].phrase || '').length, pair[1].start);
    for (const [relation, pattern] of [['arrow', CAUSE], ['vs', CONTRAST], ['plus', PLUS]]) {
      if (pattern.test(between)) return relation;
    }
    return 'none';
  }

  narratorPose(text) {
    for (const [pose, cue] of NARRATOR_CUES) if (cue.test(text)) return pose;
    return null;
  }

  // ------------------------------------------------------------ detectors
  async quote(beat, text, norm) {
    const m = /[“"「]([^”"」]{12,})[”"」]/.exec(text);
    if (!m || m[1].split(/\s+/).filter(Boolean).length < 5) return null;
    const quote = m[1].trim();
    if (quote.length > 110) return null;
    const who = /([A-Z][a-z]+(?: [A-Z][a-z]+){0,2}) (?:said|says|wrote|writes|argued|told)/.exec(text);
    const v = { id: `${beat.id}q`, type: 'quote', text: { en: quote }, size: 'wide' };
    if (who) v.who = { en: who[1] };
    const trig = this.spoken(norm, quote.slice(0, 24));
    if (trig) v.trigger = { en: trig };
    return [v, m.index];
  }

  async definition(beat, text, norm) {
    const m = /\b((?:an? |the )?[a-z][\w-]*(?: [a-z][\w-]*){0,3}) (?:called|known as|named) (?:an? |the )?([A-Za-z][\w-]*(?: [A-Za-z][\w-]*){0,2})\b/.exec(text);
    if (!m || /^(this|that|these|those|it|is|are|was|were)\b/.test(m[1].split(' ')[0])) return null;
    const term = m[2];
    let w = m[1].split(' ');
    while (w.length && PREPOSITIONS.includes(w[0])) w = w.slice(1);
    if (!w.length || ['is', 'are', 'was', 'were', 'be', 'been'].includes(w[w.length - 1])) return null;
    const gloss = w.join(' ');
    const v = { id: `${beat.id}g`, type: 'glossary', term: { en: term.slice(0, 1).toUpperCase() + term.slice(1) },
      text: { en: gloss.slice(0, 1).toUpperCase() + gloss.slice(1) } };
    const trig = this.spoken(norm, term);
    if (trig) v.trigger = { en: trig };
    return [v, m.index];
  }

  /** One salient number: 'X% of Y' becomes a 100-square grid, anything else a big stat. */
  async number(beat, text, norm, recent) {
    const pct = /(\d+(?:\.\d+)?)\s?%\s+of\s+(?:the\s+)?([a-z][\w-]*(?: [a-z][\w-]*)?)/.exec(text);
    if (pct && Number(pct[1]) >= 1 && Number(pct[1]) <= 99) {
      const value = pct[0].split('of')[0].trim();
      const labelWords = pct[2].split(' ');                  // "27% of trips are made ..." -> "trips"
      while (labelWords.length > 1 && (AUX.has(labelWords[labelWords.length - 1]) || PREPS.has(labelWords[labelWords.length - 1])
        || DETERMINERS.has(labelWords[labelWords.length - 1]))) labelWords.pop();
      const label = labelWords.join(' ');
      const v = { id: `${beat.id}p`, type: 'grid100', title: { en: `${value} of ${label}` }, filled: pyRound(Number(pct[1])),
        legend: [{ text: { en: label }, kind: 'filled' }] };
      const trig = this.spoken(norm, value);
      if (trig) v.trigger = { en: trig };
      return [v, pct.index];
    }
    const num = String.raw`(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?`;
    const pattern = new RegExp(String.raw`(?:\$|€|£)?${num}(?:\s?(?:%|×|(?:percent|million|billion|trillion|thousand|bn|m|x)\b))?`, 'g');
    for (const m of text.matchAll(pattern)) {
      const token = m[0].trim();
      const digits = token.replace(/[^\d.]/g, '');
      if (!digits || digits === '.') continue;
      const isYear = /^(1[1-9]\d\d|20\d\d)$/.test(token);
      const salient = !isYear && (parseFloat(digits) >= 20 || token !== digits);
      if (!salient) continue;
      const label = this.nounAfter(text.slice(m.index + m[0].length));
      const v = { id: `${beat.id}n`, type: 'stat', value: { en: token }, label: { en: label || ' ' } };
      if (label) {
        const sentence = splitSentences(text).find((x) => x.includes(token)) ?? text;
        const [vec] = await this.sentenceVectors([sentence]);
        for (const hit of this.matcher.lexical(label)) {
          if (!recent.includes(hit.id) && this.agree(hit.id, vec) >= AGREE[this.entry(hit.id).set][1]
              && !GENERIC.has(this.key(hit.phrase)) && this.belongs(hit.id, hit.phrase, beat.chapter)) {
            v.doodle = hit.id;
            break;
          }
        }
      }
      const trig = this.spoken(norm, token, m.index);
      if (trig) v.trigger = { en: trig };
      return [v, m.index];
    }
    return null;
  }

  /** Who or what a dated clause is about: a named person or group first, else the clause's subject. */
  eventLabel(sentence, date) {
    const at = sentence.indexOf(date);
    const parts = [...sentence.matchAll(/[^,;:()]+/g)].map((m) => [m.index, m[0]]);
    let k = parts.findIndex(([s, p]) => s <= at && at < s + p.length);
    if (k < 0) k = 0;
    const tokens = (s) => s.match(/[A-Za-z][\w'’-]*/g) || [];
    let clause = tokens(parts[k][1].split(date).join(' '));
    let used = k;
    if (clause.every((w) => PREPS.has(w.toLowerCase()) || DETERMINERS.has(w.toLowerCase())) && k + 1 < parts.length) {
      clause = tokens(parts[k + 1][1]);                       // "By 1500, printing presses were ..."
      used = k + 1;
    }
    const subject = [];                                         // the words before the clause's verb or first preposition
    for (const w of clause) {
      const low = w.toLowerCase();
      if (AUX.has(low) || PREPS.has(low) || (subject.length && (low.endsWith('ed') || PAST.has(low)))) break;
      subject.push(w);
    }
    const trimName = (run) => {
      const label = run.join(' ').replace(/['’]s$/, '');
      return label.length <= LABEL_MAX ? label : label.split(' ').pop();
    };
    const names = subject.filter((w) => isUpper(w[0]) && !DETERMINERS.has(w.toLowerCase()) && !EN_STOP.has(w.toLowerCase()));
    if (names.length) {                                         // "Martin Luther's arguments" -> "Martin Luther"
      const first = subject.indexOf(names[0]);
      const run = [names[0]];
      for (const w of subject.slice(first + 1)) {
        if (!isUpper(w[0])) break;
        run.push(w);
      }
      const follows = subject.slice(first + run.length);
      if (!follows.length || /['’]s$/.test(run[run.length - 1])) return trimName(run);
    }
    if (used + 1 < parts.length) {                              // "The fix came in 1885, when John Kemp Starley sold ..."
      let nxt = tokens(parts[used + 1][1]);
      while (nxt.length && CONNECTIVES.has(nxt[0].toLowerCase())) nxt = nxt.slice(1);
      const run = [];
      for (const w of nxt) {
        if (!isUpper(w[0])) break;
        run.push(w);
      }
      const after = run.length < nxt.length ? nxt[run.length].toLowerCase() : '';
      if (run.length && !DETERMINERS.has(run[0].toLowerCase()) && !EN_STOP.has(run[0].toLowerCase())
          && (!after || AUX.has(after) || PAST.has(after) || after.endsWith('ed'))) return trimName(run);
    }
    const det = subject.length ? subject[0].toLowerCase() : '';
    let content = subject.filter((w) => !DETERMINERS.has(w.toLowerCase()) && !/^\d+$/.test(w));
    if (content.length === 1 && (det === 'every' || det === 'each')) content = [content[0] + 's'];   // "every book" -> "books"
    if (content.length === 1) {                                 // "every book in Europe was copied by hand"
      const rest = clause.slice(subject.length);
      const aux = rest.findIndex((w) => AUX.has(w.toLowerCase()));
      if (aux >= 0 && aux + 1 < rest.length && /(ed|en)$/.test(rest[aux + 1].toLowerCase())) content = [...content, ...rest.slice(aux + 1, aux + 4)];
    }
    let label = content.slice(0, 4).join(' ');
    while (label.length > LABEL_MAX && label.includes(' ')) label = label.slice(0, label.lastIndexOf(' '));
    if (!label) {
      const hit = this.matcher.lexical(sentence).find((h) => !GENERIC.has(this.key(h.phrase)));
      label = hit ? hit.phrase : '';
    }
    return label.slice(0, 1).toUpperCase() + label.slice(1);
  }

  /** [{anchor beat id: timeline page}, {beat id: [first, last] text positions the page holds}]. */
  async timelines(board) {
    const out = {};
    const spans = {};
    const narration = board.beats.filter((b) => b.kind === 'narration');
    for (const chapter of board.chapters) {
      if (!['section', 'board'].includes(chapter.kind)) continue;
      const made = this.timeline(narration.filter((b) => b.chapter === chapter.id), 3);
      if (made) {
        const [anchor, page, heldSpans] = made;
        out[anchor] = page;
        Object.assign(spans, heldSpans);
      }
    }
    return [out, spans];
  }

  timeline(beats, minYears) {
    const events = [];
    for (const b of beats) {
      const text = b.display.en;
      for (const m of text.matchAll(/(?<!\d)(1[1-9]\d\d|20\d\d)(?:s)?(?!\d)/g)) {
        if (/\b(?:before|until|till|prior to)\s+(?:the\s+)?$/i.test(text.slice(Math.max(0, m.index - 16), m.index))) continue;
        const sentence = splitSentences(text).find((s) => s.includes(m[0])) ?? text;
        events.push([Number(m[1]), m[0], this.eventLabel(sentence, m[0]), b, m.index]);
      }
    }
    const years = [...new Set(events.map((e) => e[0]))].sort((a, b) => a - b);
    if (years.length < minYears) return null;
    const first = new Map();
    for (const e of events) {              // an exact year says more than a decade ("1450" over "1450s")
      if (!first.has(e[0]) || (first.get(e[0])[1].endsWith('s') && !e[1].endsWith('s'))) first.set(e[0], e);
    }
    const chosen = years.slice(0, 6).map((y) => first.get(y));
    const order = new Map(beats.map((b, k) => [b.id, k]));
    const spoken = chosen.map((e, i) => [e, i]).sort((x, y) => order.get(x[0][3].id) - order.get(y[0][3].id)
      || x[0][4] - y[0][4] || x[1] - y[1]).map(([e]) => e);
    const anchor = spoken[0][3];
    const last = spoken[spoken.length - 1][3];
    const lo = years[0];
    const hi = years[chosen.length - 1];
    const evs = chosen.map(([y, display, label, b, start]) => {
      const ev = { pos: round3((y - lo) / Math.max(1, hi - lo)), display: { en: display }, label: { en: label } };
      const trig = this.spoken(normalizeNumbers(b.display.en), display, start);
      if (trig) ev.trigger = b === anchor ? { en: trig } : { beat: b.id, en: trig };
      return ev;
    });
    const page = { id: `${anchor.id}t`, type: 'lanes', title: { en: '' }, lanes: [{ label: { en: '' }, events: evs }] };
    const firstTrig = evs.find((ev, i) => chosen[i] === spoken[0] && ev.trigger)?.trigger;
    if (firstTrig) page.trigger = firstTrig;
    const held = {};
    const a = order.get(anchor.id);
    const z = order.get(last.id);
    for (const b of beats.slice(a, z + 1)) {
      held[b.id] = [b === anchor ? spoken[0][4] : -1, b === last ? spoken[spoken.length - 1][4] : 10 ** 6];
    }
    return [anchor.id, page, held];
  }
}

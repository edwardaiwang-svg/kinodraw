// AI director: the rules director drafts, GPT-6 Luna (through KinoDraw Cloud) improves one section at a time, and code
// decides (port of kinodraw/director/llm/director.py). Every answer is checked before it is used: doodles must
// come from the beat's candidates (or the narrator poses), triggers must be words of the beat, numbers/dates/quotes
// must appear in the section text, and texts must fit. A beat whose answer fails keeps its rules draft; a section
// whose call fails keeps all of its rules visuals. The model may re-pick a sentence's pictures, but never leaves a
// sentence with less drawn than the rules planned.
import { normalize as normalizeNumbers } from './numbers.js';
import { sentences as splitSentences, syncTakes } from './script.js';
import { normalizeStoryboard } from './storyboard.js';

const NARRATOR_POSES = ['narrator_wave', 'narrator_explain', 'narrator_present', 'narrator_think', 'narrator_magnifier',
  'narrator_notebook', 'narrator_thumbs', 'narrator_worried'];
const PAGE_TYPES = new Set(['bars', 'grid100', 'timeline', 'lanes', 'flow', 'split']);   // as the model names them, and as drawn
const KEEPABLE = new Set(['cluster', 'stat', 'quote', 'glossary']);   // rules visuals that stand alone in one sentence
const MAX_VISUALS_PER_BEAT = 4;
const LIMITS = { label: 22, title: 40, hook: 30, quote: 110, gloss: 80, takeaway_words: 12 };
export const LUNA = 'gpt-6-luna';

class Rejected extends Error {}
const clean = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const squash = (s) => s.replace(/[\s“”"「」‘’']+/g, '').toLowerCase();
const numbersOk = (text, source) => (text.match(/\d[\d,.]*/g) || []).every((n) => source.includes(n));

/** Where a visual starts in the beat's spoken text: its trigger or its first item's; 0 = as the beat starts. */
function at(v, spoken) {
  for (const trigger of [v.trigger, ...(v.items || []).map((i) => i.trigger)]) {
    const found = trigger?.en ? spoken.indexOf(trigger.en) : -1;
    if (found >= 0) return found;
  }
  return 0;
}

/** How much visuals put on the board: every doodle, and every number, quote or note. */
const amount = (visuals) => visuals.reduce((n, v) => n + (v.type === 'cluster' ? v.items.length : 1 + Boolean(v.doodle)), 0);

function summary(v) {
  const out = { type: v.type };
  if (v.type === 'cluster') out.items = (v.items || []).map((it) => it.doodle);
  for (const key of ['value', 'term', 'title']) if (v[key] && typeof v[key] === 'object') out[key] = v[key].en;
  return out;
}

export class LLMDirector {
  /** cloud: { openVideo({sections, characters}) → {video_id, model}, directSection(videoId, payload) → section } */
  constructor(cloud, rules, { candidatesPerBeat = 12 } = {}) {
    this.cloud = cloud;
    this.rules = rules;
    this.k = candidatesPerBeat;
    this.notes = [];
    this.calls = 0;
  }

  async direct(board, onProgress) {
    await this.rules.direct(board);                          // the draft, and the fallback
    const chapters = normalizeStoryboard(board).chapters;
    const groups = chapters.filter((c) => ['section', 'board', 'outro'].includes(c.kind))
      .map((c) => [c, board.beats.filter((b) => b.chapter === c.id && ['narration', 'take'].includes(b.kind))])
      .filter(([, beats]) => beats.length);
    const video = await this.cloud.openVideo({ sections: groups.length,
      characters: groups.reduce((n, [, beats]) => n + beats.reduce((m, b) => m + b.display.en.length, 0), 0) });
    if (video.model !== LUNA) throw new Error(`KinoDraw Cloud offered ${video.model}; this version only uses ${LUNA}`);
    for (let i = 0; i < groups.length; i++) {
      const [chapter, beats] = groups[i];
      onProgress?.(i, groups.length);
      const payload = await this.payload(board, chapter, beats, groups.length);
      let answer;
      try {
        answer = await this.cloud.directSection(video.video_id, payload);
        this.calls += 1;
      } catch (error) {
        this.notes.push(`${chapter.id}: kept the offline plan (${error.message})`);
        continue;
      }
      this.apply(board, chapter, beats, answer, payload);
    }
    onProgress?.(groups.length, groups.length);
    return { notes: this.notes, calls: this.calls, model: video.model };
  }

  async payload(board, chapter, beats, sections) {
    const m = this.rules.matcher;
    const out = [];
    for (const b of beats) {
      const text = b.display.en;
      let hits = m.lexical(text).slice(0, this.k);
      const seen = new Set(hits.map((h) => h.id));
      hits = [...hits, ...(await m.semantic(text, this.k)).filter((h) => !seen.has(h.id)).slice(0, this.k - hits.length + 4)];
      out.push({ beat_id: b.id, kind: b.kind === 'take' ? 'takeaway' : 'narration', text,
        visual_budget: b.kind === 'take' ? 0 : this.rules.budget(text),
        candidates: hits.map((h) => ({ id: h.id, desc: (m.entries[h.id].desc || '').slice(0, 70) })),
        rules_draft: b.visuals.map(summary) });
    }
    return { language: 'en', video_title: board.title.en, section_title: chapter.title?.en || '', section_kind: chapter.kind,
      sections_in_video: sections, narrator_poses: NARRATOR_POSES, beats: out };
  }

  apply(board, chapter, beats, answer, payload) {
    const sectionText = beats.map((b) => b.display.en).join(' ');
    const byId = new Map(beats.map((b) => [b.id, b]));
    const allowed = new Map(payload.beats.map((p) => [p.beat_id, new Set([...p.candidates.map((c) => c.id), ...NARRATOR_POSES])]));
    let pages = 0;
    for (const item of answer.beats || []) {
      const beat = byId.get(item.beat_id);
      if (!beat || beat.kind === 'take') continue;
      const norm = normalizeNumbers(beat.display.en);
      const made = [];
      (item.visuals || []).slice(0, MAX_VISUALS_PER_BEAT).forEach((raw, k) => {
        try {
          const v = this.convert(raw, beat, norm, sectionText, allowed.get(beat.id), k);
          if (PAGE_TYPES.has(raw.type)) {
            if (pages) throw new Rejected('a second chart in one section');
            pages += 1;
          }
          made.push(v);
        } catch (error) {
          if (!(error instanceof Rejected)) throw error;
          this.notes.push(`${beat.id}: dropped a ${raw?.type} (${error.message})`);
        }
      });
      if (made.length) beat.visuals = this.keepPictures(beat, made, beat.visuals);
    }
    if (chapter.kind === 'section') {
      const original = board.chapters.find((c) => c.id === chapter.id);
      const title = clean(answer.section_title);
      const hook = clean(answer.hook);
      if (title && title.length <= LIMITS.title) original.title = { en: title };
      if (hook && hook.length <= LIMITS.hook) original.hook = { en: hook };
      const take = beats.find((b) => b.kind === 'take');
      const head = clean(answer.takeaway);
      if (take && head && head.split(' ').length <= LIMITS.takeaway_words && numbersOk(head, sectionText)) {
        take.take.headline = { en: head };
        syncTakes(board);                                    // the narrator says what the note shows
      }
    }
  }

  /** Code decides how much is drawn: sentence by sentence, the model's visuals replace the rules draft only when they
   *  draw at least as much (a list keeps every item; a sentence the model left bare keeps its picture). A chart page
   *  from the model keeps the beat as the model planned it; without one, a chart page from the rules (a timeline, a
   *  100-square grid) keeps the beat as the rules planned it. */
  keepPictures(beat, made, draft) {
    if (made.some((v) => PAGE_TYPES.has(v.type))) return made;
    if (draft.some((v) => PAGE_TYPES.has(v.type))) return draft;
    const spoken = normalizeNumbers(beat.display.en).spoken;
    const ends = [];
    let cursor = 0;
    for (const sentence of splitSentences(spoken).length ? splitSentences(spoken) : [spoken]) {
      cursor = spoken.indexOf(sentence, cursor) + sentence.length;
      ends.push(cursor);
    }
    const sentenceOf = (v) => {
      const k = ends.findIndex((end) => at(v, spoken) < end);
      return k < 0 ? ends.length - 1 : k;
    };
    const drawn = new Set(made.flatMap((v) => (v.items || []).map((i) => i.doodle)));
    const model = new Map();
    const rules = new Map();
    const add = (map, v) => map.set(sentenceOf(v), [...(map.get(sentenceOf(v)) || []), v]);
    for (const v of made) add(model, v);
    for (const v of draft) {                                 // (a picture the model already drew elsewhere is not repeated)
      if (KEEPABLE.has(v.type) && !(v.type === 'cluster' && v.items.every((i) => drawn.has(i.doodle)))) add(rules, v);
    }
    const kept = [];
    for (const k of [...new Set([...model.keys(), ...rules.keys()])].sort((a, b) => a - b)) {
      const ours = rules.get(k) || [];
      const theirs = model.get(k) || [];
      kept.push(...(amount(ours) > amount(theirs) ? ours : theirs));
    }
    return kept.map((v, i) => [at(v, spoken), i, v]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, , v]) => v);
  }

  /** One schema visual -> the renderer's spec, or Rejected explaining why it is unusable. */
  convert(raw, beat, norm, sectionText, allowed, k) {
    const kind = raw?.type;
    const vid = `${beat.id}m${k}`;
    const trig = (phrase) => {
      const said = phrase && phrase.trim() ? norm.find(phrase.trim()) : null;
      return said && norm.spoken.includes(said) ? { en: said } : null;
    };
    const text = (s, cap, what) => {
      s = clean(s);
      if (s.length > cap) throw new Rejected(`${what} too long`);
      return { en: s };
    };
    const doodle = (d, required = false) => {
      d = clean(d);
      if (!d) {
        if (required) throw new Rejected('no doodle');
        return null;
      }
      if (!allowed.has(d)) throw new Rejected(`doodle ${d} was not offered`);
      return d;
    };
    const withTrigger = (spec, phrase) => {
      const t = trig(phrase);
      if (t) spec.trigger = t;
      return spec;
    };
    if (kind === 'cluster') {
      const items = (raw.items || []).slice(0, 3).map((it) => {
        const entry = { doodle: doodle(it.doodle, true) };
        if (clean(it.label)) entry.label = text(it.label, LIMITS.label, 'label');
        return withTrigger(entry, it.trigger);
      });
      if (!items.length) throw new Rejected('empty cluster');
      const v = { id: vid, type: 'cluster', items, relation: raw.relation || 'none' };
      const first = items.find((i) => i.trigger)?.trigger;
      return first ? { ...v, trigger: first } : v;
    }
    if (kind === 'stat') {
      const value = clean(raw.value);
      if (!value || !sectionText.includes(value)) throw new Rejected(`value ${value} is not in the text`);
      const v = { id: vid, type: 'stat', value: { en: value }, label: text(raw.label || ' ', LIMITS.label, 'label') };
      const d = doodle(raw.doodle);
      if (d) v.doodle = d;
      return withTrigger(v, raw.trigger || value);
    }
    if (kind === 'quote') {
      const quote = clean(raw.text).replace(/^[“”"「」]+|[“”"「」]+$/g, '');
      if (!quote || !squash(sectionText).includes(squash(quote))) throw new Rejected('the quote is not in the text');
      const v = { id: vid, type: 'quote', text: text(quote, LIMITS.quote, 'quote'), size: 'wide' };
      if (clean(raw.who)) v.who = { en: clean(raw.who) };
      return withTrigger(v, raw.trigger);
    }
    if (kind === 'glossary') {
      const term = clean(raw.term);
      if (!term || !sectionText.toLowerCase().includes(term.toLowerCase())) throw new Rejected(`term ${term} is not in the text`);
      const v = { id: vid, type: 'glossary', term: { en: term }, text: text(raw.text, LIMITS.gloss, 'definition') };
      return withTrigger(v, raw.trigger || term);
    }
    if (kind === 'bars') {
      const rows = (raw.rows || []).slice(0, 6).map((r) => {
        const display = clean(r.display);
        if (!display || !sectionText.includes(display) || typeof r.value !== 'number') throw new Rejected(`bar ${display} is not in the text`);
        return withTrigger({ label: text(r.label, LIMITS.label, 'label'), value: r.value, display: { en: display } }, r.trigger || display);
      });
      if (rows.length < 2) throw new Rejected('a bar chart needs two numbers');
      const v = { id: vid, type: 'bars', title: text(raw.title, LIMITS.title, 'title'), rows };
      if (clean(raw.unit)) v.unit = { en: clean(raw.unit) };
      return v;
    }
    if (kind === 'grid100') {
      const filled = raw.filled;
      if (!Number.isInteger(filled) || filled < 1 || filled > 99 || !sectionText.includes(String(filled))) {
        throw new Rejected('the grid number is not in the text');
      }
      const v = { id: vid, type: 'grid100', title: text(raw.title, LIMITS.title, 'title'), filled,
        legend: [{ text: text(raw.legend || ' ', LIMITS.label * 2, 'legend'), kind: 'filled' }] };
      return withTrigger(v, raw.trigger || String(filled));
    }
    if (kind === 'timeline') {
      const rawEvents = (raw.events || []).slice(0, 6);
      const events = rawEvents.map((e, i) => {
        const when = clean(e.when);
        if (!when || !sectionText.includes(when)) throw new Rejected(`date ${when} is not in the text`);
        if (!beat.display.en.includes(when)) throw new Rejected(`date ${when} is said in another beat`);   // said as written
        return withTrigger({ pos: Number((i / Math.max(1, rawEvents.length - 1)).toFixed(3)), display: { en: when },
          label: text(e.label, LIMITS.label, 'label') }, e.trigger || when);
      });
      if (events.length < 3) throw new Rejected('a timeline needs three dates');
      return { id: vid, type: 'lanes', title: text(raw.title, LIMITS.title, 'title'), lanes: [{ label: { en: '' }, events }] };
    }
    if (kind === 'flow') {
      const nodes = (raw.nodes || []).slice(0, 5).map((n, i) => {
        const node = { id: `n${i}`, label: text(n.label, LIMITS.label, 'label') };
        const d = doodle(n.doodle);
        if (d) node.doodle = d;
        return withTrigger(node, n.trigger);
      });
      if (nodes.length < 3) throw new Rejected('a flow needs three steps');
      const layout = ['chain', 'loop'].includes(raw.layout) ? raw.layout : 'chain';
      const edges = nodes.slice(0, -1).map((_, i) => ({ from: `n${i}`, to: `n${i + 1}` }));
      if (layout === 'loop') edges.push({ from: `n${nodes.length - 1}`, to: 'n0' });
      return { id: vid, type: 'flow', title: text(raw.title, LIMITS.title, 'title'), layout, nodes, edges };
    }
    if (kind === 'split') {
      const sides = {};
      for (const side of ['left', 'right']) {
        const s = raw[side] || {};
        const spec = { who: text(s.title, LIMITS.label, 'title'), text: text(s.text, LIMITS.gloss, 'text') };
        const d = doodle(s.doodle);
        if (d) spec.doodle = d;
        sides[side] = withTrigger(spec, s.trigger);
      }
      const v = { id: vid, type: 'split', ...sides };
      if (clean(raw.verdict)) v.verdict = { text: text(raw.verdict, LIMITS.gloss, 'verdict') };
      return v;
    }
    throw new Rejected(`unknown type ${kind}`);
  }
}

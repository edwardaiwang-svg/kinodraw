// Check a storyboard before voice and render: structure, spoken/display parity, triggers, doodles
// (port of kinodraw/director/validate.py, English). Errors make it unusable; warnings are quality notes.
import { KINDS } from './storyboard.js';

const SLOT_TYPES = new Set(['cluster', 'quote', 'glossary', 'stat']);
export const PAGE_TYPES = new Set(['grid100', 'lanes', 'bars', 'flow', 'split']);      // the pages this renderer draws
const EN_PUNCT = /[,.;:?!](?=\s|$|["”’)])|—/g;
const MAX_SECTIONS = 8;

function* triggers(value, path = '') {
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) yield* triggers(value[i], `${path}[${i}]`);
  } else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      if (key === 'trigger' && item && typeof item === 'object' && !Array.isArray(item)) yield [path, item];
      else yield* triggers(item, path ? `${path}.${key}` : key);
    }
  }
}

function* doodles(value) {
  if (Array.isArray(value)) for (const item of value) yield* doodles(item);
  else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      if (key === 'doodle' && typeof item === 'string') yield item;
      else yield* doodles(item);
    }
  }
}

/** board → { ok, errors, warnings }; `known(id)` says whether a doodle exists, `banned` is a Set of ids. */
export function validate(board, { known, banned = new Set() }) {
  const errors = [];
  const warnings = [];
  if (board.lang !== 'en') return { ok: false, errors: [`lang must be en, got ${board.lang}`], warnings };
  const chapters = board.chapters || [];
  const ids = chapters.map((c) => c.id);
  if (ids.length !== new Set(ids).size) errors.push('duplicate chapter ids');
  for (const c of chapters) if (!KINDS.has(c.kind)) errors.push(`chapter ${c.id}: kind ${c.kind} is unknown`);
  const sections = chapters.filter((c) => c.kind === 'section');
  if (sections.length > MAX_SECTIONS) errors.push(`${sections.length} sections; the agenda holds at most ${MAX_SECTIONS}`);
  if (sections.length && !chapters.some((c) => c.kind === 'agenda')) errors.push('sections need an agenda chapter');
  const beats = board.beats || [];
  const byId = new Map(beats.map((b) => [b.id, b]));
  if (byId.size !== beats.length) errors.push('duplicate beat ids');
  const order = beats.map((b) => b.chapter);
  const runs = order.filter((c, i) => i === 0 || order[i - 1] !== c);
  if (runs.length !== new Set(runs).size) errors.push('beats of one chapter must be contiguous');
  if (JSON.stringify(ids.filter((c) => order.includes(c))) !== JSON.stringify(runs)) errors.push('beat order does not follow chapter order');
  for (const c of chapters) if (!order.includes(c.id)) errors.push(`chapter ${c.id} has no beats`);
  const visualIds = new Set();
  for (const b of beats) {
    const spoken = b.spoken?.en || '';
    const display = b.display?.en || '';
    if (!spoken.trim() || !display.trim()) { errors.push(`${b.id}: empty spoken or display text`); continue; }
    if (/\d/.test(spoken)) errors.push(`${b.id}: digits in spoken text (${spoken.slice(0, 50)})`);
    if (JSON.stringify(spoken.match(EN_PUNCT) || []) !== JSON.stringify(display.match(EN_PUNCT) || [])) {
      errors.push(`${b.id}: clause punctuation differs between spoken and display text`);
    }
    const chapter = chapters.find((c) => c.id === b.chapter);
    if (!chapter) { errors.push(`${b.id}: unknown chapter ${b.chapter}`); continue; }
    if (b.kind === 'take' && chapter.kind === 'section') {
      const head = b.take?.headline?.en || '';
      if (!head) errors.push(`${b.id}: take beat without a headline`);
      else if (head.split(/\s+/).length > 16) warnings.push(`${b.id}: long takeaway headline`);
    }
    for (const v of b.visuals || []) {
      if (!v.id || visualIds.has(v.id)) errors.push(`${b.id}: visual id missing or duplicated (${v.id})`);
      visualIds.add(v.id);
      if (!SLOT_TYPES.has(v.type) && !PAGE_TYPES.has(v.type)) errors.push(`${b.id}/${v.id}: unknown visual type ${v.type}`);
      for (const [where, trig] of triggers(v)) {
        const ref = byId.get(trig.beat) || b;
        if (trig.en && !(ref.spoken?.en || '').includes(trig.en)) {
          errors.push(`${b.id}/${v.id} ${where}: trigger ${JSON.stringify(trig.en)} is not in the spoken text`);
        }
      }
      for (const id of doodles(v)) {
        if (!known(id)) errors.push(`${b.id}/${v.id}: doodle ${id} not found`);
        else if (banned.has(id)) warnings.push(`${b.id}/${v.id}: ${id} is a banned picture`);
      }
      if (v.type === 'cluster' && !((v.items || []).length >= 1 && (v.items || []).length <= 3)) {
        errors.push(`${b.id}/${v.id}: a cluster needs 1-3 items`);
      }
    }
  }
  return { ok: !errors.length, errors, warnings };
}

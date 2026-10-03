// Document -> storyboard skeleton: chapters and beats with display and spoken text (port of kinodraw/script.py).
//
// Structure: intro (title board) -> preamble board (if any) -> agenda -> numbered sections -> outro. Every word
// written on the board is said while it is written: a section starts with its opener spoken ("Part 1: One machine,
// one idea.") while its title card is written, and ends with its takeaway spoken ("Key takeaway: ...") while the
// note is written; the section's own paragraphs are all narration, drawn like any other.
import { normalize } from './numbers.js';

export const EN_BEAT = [15, 35, 55];               // min / target / max words per beat
export const MAX_SECTIONS = 8;
const CONCLUSION = /^(conclusion|summary|final thoughts|wrap[- ]?up|key takeaways|takeaways|in closing)\b/i;
export const TEXT = {
  intro: 'Today: {title}', agenda_first: "Here's what we'll cover. First: {t}",
  agenda_mid: ['Second: {t}', 'Third: {t}', 'Fourth: {t}', 'Fifth: {t}', 'Sixth: {t}', 'Seventh: {t}'],
  agenda_last: 'And finally: {t}', label: 'Part {n}', closing: 'Thanks for watching!',
  intro_label: 'Intro', outro_label: 'Wrap-up', agenda_label: "What we'll cover",
  opener: '{label}: {title}', take: 'Key takeaway: {h}',
};
const fill = (template, values) => template.replace(/\{(\w+)\}/g, (_, k) => values[k]);

export const size = (text) => text.split(/\s+/).filter(Boolean).length;

export function sentences(paragraph) {
  const protectedText = paragraph.replace(/\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e|U\.S|U\.K|No)\./g,
    (m) => m.replace(/\./g, '\0'));
  const parts = [];
  let start = 0;
  for (const m of protectedText.matchAll(/[.!?]+[”’")\]]*(?=\s+[“"(\[]?[A-Z0-9])/g)) {
    parts.push(protectedText.slice(start, m.index + m[0].length));
    start = m.index + m[0].length;
  }
  parts.push(protectedText.slice(start));
  return parts.map((p) => p.replace(/\0/g, '.').trim()).filter(Boolean);
}

/** Split one over-long sentence at the clause mark nearest its middle (recursively). */
function splitLong(sentence, limit) {
  if (size(sentence) <= limit) return [sentence];
  const marks = [...sentence.matchAll(/[,;:](?=\s)|—/g)].map((m) => m.index + m[0].length);
  if (!marks.length) return [sentence];
  const mid = sentence.length / 2;
  const cut = marks.reduce((best, k) => (Math.abs(k - mid) < Math.abs(best - mid) ? k : best), marks[0]);
  return [...splitLong(sentence.slice(0, cut).trim(), limit), ...splitLong(sentence.slice(cut).trim(), limit)];
}

/** Group sentences into beats of about the target size; paragraphs never share a beat. */
export function beatsOf(paragraphs) {
  const [lo, target, hi] = EN_BEAT;
  const out = [];
  for (const para of paragraphs) {
    const chunks = [];
    let cur = [];
    for (const unit of sentences(para).flatMap((s) => splitLong(s, hi))) {
      if (cur.length && (size([...cur, unit].join(' ')) > hi || size(cur.join(' ')) >= target)) {
        chunks.push(cur);
        cur = [];
      }
      cur.push(unit);
    }
    if (cur.length) {
      if (chunks.length && size(cur.join(' ')) < lo && size([...chunks[chunks.length - 1], ...cur].join(' ')) <= hi) {
        chunks[chunks.length - 1].push(...cur);                 // a short tail joins the previous beat
      } else {
        chunks.push(cur);
      }
    }
    out.push(...chunks.map((c) => c.join(' ')));
  }
  return out;
}

/** No usable headings: cut the paragraphs into 2–6 sections of similar length. */
function balancedSections(paragraphs) {
  const total = paragraphs.reduce((a, p) => a + size(p), 0);
  const k = Math.max(2, Math.min(6, pyRound(total / 220), paragraphs.length));
  if (paragraphs.length < 2) return [{ heading: '', paragraphs }];
  const sections = [];
  let cur = [];
  let acc = 0;
  paragraphs.forEach((p, i) => {
    cur.push(p);
    acc += size(p);
    const remaining = paragraphs.length - i - 1;
    if (acc >= total * (sections.length + 1) / k && remaining >= k - sections.length - 1 && sections.length < k - 1) {
      sections.push({ heading: '', paragraphs: cur });
      cur = [];
    }
  });
  if (cur.length) sections.push({ heading: '', paragraphs: cur });
  return sections;
}

/** Python's round(): halves go to the even neighbour. */
export function pyRound(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

function shortTitle(text) {
  const first = text ? sentences(text)[0] : '';
  const words = first.replace(/[.!?]+$/, '').split(/\s+/).filter(Boolean);
  return words.length <= 7 ? words.join(' ') : words.slice(0, 6).join(' ') + '…';
}

function mergeTo(sections, limit) {
  sections = [...sections];
  while (sections.length > limit) {
    const sizes = sections.map((s) => s.paragraphs.reduce((a, p) => a + size(p), 0));
    let i = 0;
    for (let k = 1; k < sections.length - 1; k++) if (sizes[k] + sizes[k + 1] < sizes[i] + sizes[i + 1]) i = k;
    const [a, b] = [sections[i], sections[i + 1]];
    sections.splice(i, 2, { heading: a.heading || b.heading, paragraphs: [...a.paragraphs, ...b.paragraphs] });
  }
  return sections;
}

export const CONTEXT = /^(this|that|these|those|it|its|they|their|he|she|so|but|and|or|then)\b/i;
export const NAMING = /\b(call|calls|called|name|names|named)\s+(this|that|these|those|it|them)\b/i;

/** Takeaway note text: the shortest complete sentence that fits a note and stands on its own (not "This is
 * called..." or "We call this..."), from the section's last paragraph that has one; if none has, the same with
 * sentences of up to 18 words and 90 characters (still three lines on the note); else the section title. */
export function headline(beatTexts, fallback) {
  for (const [cap, room] of [[14, Infinity], [18, 90]]) {
    for (const text of [...beatTexts].reverse()) {
      const fits = sentences(text).filter((s) => size(s) >= 4 && size(s) <= cap && s.length <= room
        && !CONTEXT.test(s) && !NAMING.test(s));
      if (fits.length) return fits.reduce((best, s) => (size(s) < size(best) ? s : best));
    }
  }
  return sentenceOf(fallback);
}

/** What the narrator says while the takeaway note is written: the note's own words. */
export const takeText = (head) => fill(TEXT.take, { h: head });

/** Keep every takeaway beat saying exactly what its note shows (after an edit or an AI takeaway). */
export function syncTakes(board) {
  for (const b of board.beats) {
    const head = b.take?.headline?.en;
    if (b.kind === 'take' && head) {
      const display = takeText(sentenceOf(head));
      if (b.display.en !== display) {
        b.display = { en: display };
        b.spoken = { en: normalize(display).spoken };
      }
    }
  }
  return board;
}

/** A heading used as a spoken sentence: keep a question mark, otherwise end with a full stop. */
export function sentenceOf(text) {
  text = text.trim().replace(/[.。:：;；,，]+$/, '');
  return /[?？!！]$/.test(text) ? text : text + '.';
}

export function build(doc) {
  if (doc.lang !== 'en') throw new Error('KinoDraw for Classroom makes English videos for now');
  let sections = doc.sections.filter((s) => s.paragraphs.length).map((s) => ({ ...s }));
  let preamble = [...doc.preamble];
  if (sections.length < 2) {                           // no usable headings: split the text evenly
    const body = [...preamble, ...sections.flatMap((s) => s.paragraphs)];
    preamble = [];
    sections = balancedSections(body);
  }
  let outroParas = [];
  if (sections.length >= 3 && CONCLUSION.test(sections[sections.length - 1].heading.trim())) {
    outroParas = sections.pop().paragraphs;
  }
  sections = mergeTo(sections, MAX_SECTIONS);
  for (const s of sections) s.heading = s.heading.trim() || shortTitle(s.paragraphs[0]);

  const chapters = [];
  const beats = [];
  const beat = (chapter, kind, display, extra = {}) => {
    const n = normalize(display);
    beats.push({ id: `b${String(beats.length + 1).padStart(3, '0')}`, chapter, kind, display: { en: display },
      spoken: { en: n.spoken }, visuals: [], ...extra });
    return beats[beats.length - 1];
  };
  chapters.push({ id: 'intro', kind: 'intro', label: { en: doc.title }, title: { en: '' } });
  beat('intro', 'title', fill(TEXT.intro, { title: sentenceOf(doc.title) }), { music: true });
  if (preamble.length) {
    chapters.push({ id: 'preamble', kind: 'board', label: { en: TEXT.intro_label }, title: { en: '' } });
    for (const text of beatsOf(preamble)) beat('preamble', 'narration', text);
  }
  const multi = sections.length >= 2;
  if (multi) {
    chapters.push({ id: 'agenda', kind: 'agenda', label: { en: TEXT.agenda_label }, title: { en: '' } });
    sections.forEach((s, k) => {
      const t = sentenceOf(s.heading);
      const text = k === 0 ? fill(TEXT.agenda_first, { t }) : k === sections.length - 1 ? fill(TEXT.agenda_last, { t })
        : fill(TEXT.agenda_mid[Math.min(k - 1, TEXT.agenda_mid.length - 1)], { t });
      beat('agenda', 'agenda', text, { music: true });
    });
  }
  sections.forEach((s, i) => {
    const k = i + 1;
    const cid = `s${k}`;
    const label = fill(TEXT.label, { n: k });
    chapters.push({ id: cid, kind: multi ? 'section' : 'board', label: { en: label }, title: { en: s.heading } });
    const texts = beatsOf(s.paragraphs);
    if (multi) beat(cid, 'opener', fill(TEXT.opener, { label, title: sentenceOf(s.heading) }));
    for (const text of texts) beat(cid, 'narration', text);
    if (multi) {
      const head = headline(texts, s.heading);
      beat(cid, 'take', takeText(head), { take: { headline: { en: head } } });
    }
  });
  chapters.push({ id: 'outro', kind: 'outro', label: { en: TEXT.outro_label }, title: { en: '' } });
  for (const text of beatsOf(outroParas)) beat('outro', 'narration', text);
  beat('outro', 'closing', TEXT.closing, { music: true });
  return { version: 1, lang: 'en', title: { en: doc.title }, narrator: 'narrator', chapters, beats };
}

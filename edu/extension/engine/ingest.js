// Read a script (plain text, Markdown, .docx, or pasted text) into a title, a preamble and sections
// (port of kinodraw/ingest.py).
//
// Headings come from Markdown `#` lines, setext underlines, or .docx Title/Heading styles. The top heading
// level that yields at least two sections becomes the sections; a single top-level heading at the start
// becomes the title; deeper headings are kept as short paragraphs.

const CJK = /[㐀-䶿一-鿿豈-﫿]/;

export function detectLang(text) {
  const letters = [...text].filter((c) => /\p{L}/u.test(c));
  return letters.length && letters.filter((c) => CJK.test(c)).length / letters.length > 0.3 ? 'zh' : 'en';
}

/** Text (a string) -> Document. `fallback` is the title to use when the script has none (a file name). */
export function readText(text, { title = null, fallback = '' } = {}) {
  return structure(textBlocks(text), title, fallback);
}

/** A .docx file (ArrayBuffer or Uint8Array) -> Document. */
export async function readDocx(bytes, { title = null, fallback = '' } = {}) {
  const xml = await unzipEntry(bytes, 'word/document.xml');
  return structure(docxBlocks(xml), title, fallback);
}

/** A file's name -> the title used when the script has no heading ("bee_dance.docx" -> "Bee dance"). */
export function fileTitle(name) {
  const stem = name.replace(/^.*[\\/]/, '').replace(/\.[^.]*$/, '').replace(/_/g, ' ').replace(/-/g, ' ').trim();
  return stem.slice(0, 1).toUpperCase() + stem.slice(1);
}

// ------------------------------------------------------------------ parsing
function cleanInline(text) {
  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, '');                    // images
  text = text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');                  // links -> text
  text = text.replace(/(\*\*|__|\*|_|`)(?=\S)(.+?)(?<=\S)\1/g, '$2');   // emphasis, code
  return text.replace(/\s+/g, ' ').trim();
}

function textBlocks(text) {
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const blocks = [];
  const para = [];
  const flush = () => {
    if (para.length) {
      blocks.push([0, cleanInline(CJK.test(para.join('')) ? para.join('') : para.join(' '))]);
      para.length = 0;
    }
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    const nxt = i + 1 < lines.length ? lines[i + 1].trim() : '';
    const m = /^(#{1,6})\s+(.*?)\s*#*$/.exec(line);
    if (m) {
      flush();
      blocks.push([m[1].length, cleanInline(m[2])]);
    } else if (line && /^(=+|-+)$/.test(nxt) && nxt.length >= 3 && !para.length) {
      flush();
      blocks.push([nxt[0] === '=' ? 1 : 2, cleanInline(line)]);
      i += 1;
    } else if (!line || /^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
      flush();
    } else if (/^([-*+•]|\d+[.)])\s+/.test(line)) {
      flush();                                                          // list items stand alone
      blocks.push([0, cleanInline(line.replace(/^([-*+•]|\d+[.)])\s+/, ''))]);
    } else {
      para.push(line);
    }
  }
  flush();
  return blocks.filter(([, t]) => t);
}

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
const decodeXml = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (_, e) =>
  e[0] === '#' ? String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10))
    : ENTITIES[e.toLowerCase()]);

function docxBlocks(xml) {
  const blocks = [];
  for (const [p] of xml.matchAll(/<w:p(?:\s[^>]*)?\/>|<w:p(?:\s[^>]*)?>[\s\S]*?<\/w:p>/g)) {
    const text = [...p.matchAll(/<w:t(?:\s[^>]*)?>([^<]*)<\/w:t>/g)].map((m) => decodeXml(m[1])).join('')
      .replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const style = /<w:pStyle\s+w:val="([^"]*)"/.exec(p);
    const name = (style ? style[1] : '').toLowerCase();
    const m = /heading\s*(\d)/.exec(name);
    blocks.push([name === 'title' ? 1 : m ? Number(m[1]) + 1 : 0, text]);   // Title > Heading 1 > Heading 2
  }
  return blocks;
}

function structure(blocks, title, fallback) {
  let levels = [...new Set(blocks.filter(([l]) => l).map(([l]) => l))].sort((a, b) => a - b);
  let bodyTitle = null;
  if (levels.length && blocks[0][0] === levels[0] && blocks.filter(([l]) => l === levels[0]).length === 1) {
    bodyTitle = blocks[0][1];                                           // one top heading at the start = the title
    blocks = blocks.slice(1);
    levels = [...new Set(blocks.filter(([l]) => l).map(([l]) => l))].sort((a, b) => a - b);
  }
  const sectionLevel = levels.find((lvl) => blocks.filter(([b]) => b === lvl).length >= 2) ?? null;
  const text = blocks.map(([, t]) => t).join(' ');
  const doc = { title: title || bodyTitle || fallback || firstWords(blocks), lang: detectLang(text), preamble: [], sections: [] };
  let current = null;
  for (let [lvl, t] of blocks) {
    if (sectionLevel && lvl === sectionLevel) {
      current = { heading: t, paragraphs: [] };
      doc.sections.push(current);
      continue;
    }
    if (lvl && sectionLevel && lvl < sectionLevel) continue;           // stray higher-level headings between sections
    if (lvl) t = /[.!?。！？:：]$/.test(t) ? t : t + (doc.lang === 'zh' ? '。' : '.');   // deeper heading: a short paragraph
    (current ? current.paragraphs : doc.preamble).push(t);
  }
  doc.sections = doc.sections.filter((s) => s.paragraphs.length);
  return doc;
}

function firstWords(blocks) {
  const first = blocks.length ? blocks[0][1] : 'Untitled';
  if (CJK.test(first)) return first.split(/[，。！？；：]/)[0].slice(0, 16);
  return first.split(/(?<=[.!?])\s/)[0].split(/\s+/).slice(0, 8).join(' ').replace(/[.,;:]+$/, '');
}

// ------------------------------------------------------------------ a minimal ZIP reader (.docx)
async function unzipEntry(bytes, wanted) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  let eocd = -1;
  for (let i = data.length - 22; i >= Math.max(0, data.length - 65557); i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('not a Word document (no zip directory)');
  const count = view.getUint16(eocd + 10, true);
  let at = view.getUint32(eocd + 16, true);
  const decoder = new TextDecoder();
  for (let k = 0; k < count; k++) {
    if (view.getUint32(at, true) !== 0x02014b50) break;
    const method = view.getUint16(at + 10, true);
    const size = view.getUint32(at + 20, true);
    const nameLen = view.getUint16(at + 28, true);
    const extraLen = view.getUint16(at + 30, true);
    const commentLen = view.getUint16(at + 32, true);
    const local = view.getUint32(at + 42, true);
    const name = decoder.decode(data.subarray(at + 46, at + 46 + nameLen));
    at += 46 + nameLen + extraLen + commentLen;
    if (name !== wanted) continue;
    const start = local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true);
    const raw = data.subarray(start, start + size);
    if (method === 0) return decoder.decode(raw);
    if (method !== 8) throw new Error(`unsupported compression in ${wanted}`);
    const stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return await new Response(stream).text();
  }
  throw new Error(`${wanted} is missing: this does not look like a Word document`);
}

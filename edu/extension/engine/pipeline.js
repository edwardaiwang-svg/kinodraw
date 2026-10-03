// Script to finished MP4, entirely in the browser (the studio page drives it and shows the progress).
//
//   plan (storyboard + GPT-6 Luna director through KinoDraw Cloud, rules as the draft and the fallback)
//   → voice (Kokoro, one clip per beat) → pacing → timeline → narration + music → frames → H.264/AAC MP4
import { CONFIG } from '../config.js';
import { GAP, assembleNarration, mixMusic } from '../media/audio.js';
import { createEncoder } from '../media/encode.js';
import { createVoice } from '../media/tts.js';
import * as transformers from '../vendor/transformers/transformers.min.js';
import { loadAssets } from './assets.js';
import { createEmbedder } from './embed.js';
import { fileTitle, readDocx, readText } from './ingest.js';
import { Hand, SvgLibrary, canvas, loadFonts, loadPaper } from './ink.js';
import { LLMDirector } from './llm.js';
import { FPS, Production, SIZE, measureCaption, pacing } from './render.js';
import { RulesDirector } from './rules.js';
import { build } from './script.js';
import { layout } from './timeline.js';
import { validate } from './validate.js';

const read = async (path) => {
  const r = await fetch(chrome.runtime.getURL(path));
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.arrayBuffer();
};

let shared = null;
/** Fonts, doodle library, hand, paper and the doodle-search model: loaded once per page. */
async function kit(onStatus) {
  shared ??= (async () => {
    await loadFonts(read, document);
    const assets = await loadAssets(read);
    transformers.env.backends.onnx.wasm.wasmPaths = chrome.runtime.getURL('vendor/transformers/');
    transformers.env.allowLocalModels = false;
    const embed = await createEmbedder(transformers, { ...CONFIG.embed, onStatus: (s) => onStatus?.({ part: 'search', ...s }) });
    return { assets, embed, env: { svg: new SvgLibrary(assets), hand: await Hand.load(read), paper: await loadPaper(read) } };
  })();
  try {
    return await shared;
  } catch (error) {
    shared = null;
    throw error;
  }
}

/** A script (text, or a .docx file) → the storyboard skeleton. Throws a teacher-readable Error when it can't. */
export async function readScript({ text = '', file = null, title = '' }) {
  const fallback = file ? fileTitle(file.name) : '';
  let doc;
  if (file && /\.docx$/i.test(file.name)) doc = await readDocx(await file.arrayBuffer(), { title: title || null, fallback });
  else if (file && /\.(md|txt)$/i.test(file.name)) doc = readText(await file.text(), { title: title || null, fallback });
  else if (file) throw new Error('Choose a Word (.docx), text (.txt) or Markdown (.md) file.');
  else doc = readText(text, { title: title || null });
  const words = [doc.preamble, ...doc.sections.map((s) => s.paragraphs)].flat().join(' ').split(/\s+/).filter(Boolean).length;
  if (words < 20) throw new Error('The script is very short. Write at least a few sentences (about 20 words or more).');
  if (words > 3000) throw new Error('The script is long for one video. Keep it under about 3,000 words (about 15 minutes).');
  if (doc.lang !== 'en') throw new Error('KinoDraw for Classroom makes videos in English for now.');
  return build(doc);
}

/**
 * Make the video. `cloud` is { openVideo, directSection } bound to a KinoDraw Cloud session (GPT-6 Luna only), or null.
 * onProgress({ stage, done, total, note }) with stage in: load, plan, voice, pace, audio, draw.
 * Returns { blob, board, timeline, codecs, notes }.
 */
export async function makeVideo(board, { cloud = null, voice = CONFIG.voice.voice, quality = '1080p', onProgress = () => {}, signal } = {}) {
  const notes = [];
  const step = (stage, done = 0, total = 1, note) => onProgress({ stage, done, total, note });
  const check = () => { if (signal?.aborted) throw new DOMException('Stopped', 'AbortError'); };

  step('load');
  const { assets, embed, env } = await kit((s) => step('load', s.loaded || 0, s.total || 1, s.stage));
  check();

  // ---- plan: the rules draft every beat, then GPT-6 Luna improves one section at a time
  step('plan');
  const rules = new RulesDirector(assets, embed);
  if (cloud) {
    try {
      const report = await new LLMDirector(cloud, rules).direct(board, (i, n) => step('plan', i, n));
      notes.push(...report.notes);
    } catch (error) {
      notes.push(`The AI helper was not available (${error.message}), so the built-in rules planned the pictures.`);
      await rules.direct(board);
    }
  } else {
    await rules.direct(board);
  }
  const report = validate(board, { known: (id) => env.svg.has(id) || Boolean(assets.catalog.entries[id]) || id.startsWith('narrator_'),
    banned: new Set(assets.banned.doodles) });
  if (!report.ok) throw new Error(`The storyboard could not be checked: ${report.errors[0]}`);
  check();

  // ---- voice: one clip per beat
  const speaker = await createVoice({ voice, signal, onStatus: (s) => step('voice', s.loaded || 0, s.total || 1, s.stage) });
  const clips = {};
  try {
    for (let i = 0; i < board.beats.length; i++) {
      step('voice', i, board.beats.length);
      clips[board.beats[i].id] = await speaker.synthesize(board.beats[i].spoken.en);
      check();
    }
  } finally {
    speaker.close();
  }
  step('voice', board.beats.length, board.beats.length);

  // ---- pacing (the narration waits for the hand) and the timeline
  step('pace');
  const timing = Object.fromEntries(Object.entries(clips).map(([id, c]) => [id, { speech: c.duration + GAP, charTimes: c.charTimes }]));
  const pauses = await pacing(board, timing, env);
  const timeline = layout(board, timing, pauses, measureCaption);
  check();

  // ---- sound: narration at -18 LUFS with the music bed under it
  step('audio');
  const narration = assembleNarration(board, timeline, clips);
  const loadTrack = async (slug) => {
    const bytes = await read(`assets/music/${slug}.mp3`);
    const decoded = await new OfflineAudioContext(2, 48000, 48000).decodeAudioData(bytes);
    return { channels: [decoded.getChannelData(0), decoded.getChannelData(decoded.numberOfChannels > 1 ? 1 : 0)], sampleRate: decoded.sampleRate };
  };
  const { left, right } = await mixMusic(board, timeline, narration, { loadTrack });
  check();

  // ---- frames: draw every frame at 1920×1080 (scaled down for 720p) and encode
  const prod = await Production.create(board, timeline, env);
  const [w, h] = quality === '720p' ? [1280, 720] : SIZE;
  const encoder = await createEncoder({ width: w, height: h, fps: FPS, videoBitrate: quality === '720p' ? 2_000_000 : 3_500_000 });
  await encoder.addAudio(left, right);
  const full = canvas(...SIZE);
  const g = full.getContext('2d', { alpha: false });
  const out = w === SIZE[0] ? full : canvas(w, h);
  const og = out === full ? null : out.getContext('2d', { alpha: false });
  const total = Math.round(timeline.duration * FPS);
  for (let i = 0; i < total; i++) {
    prod.drawFrame(g, i / FPS);
    if (og) og.drawImage(full, 0, 0, w, h);
    await encoder.addFrame(out);
    if (i % 15 === 0) {
      step('draw', i, total);
      check();
    }
  }
  step('draw', total, total);
  const blob = await encoder.finish();
  notes.push(...prod.warnings.filter((x) => !x.startsWith('skipped')));
  return { blob, board, timeline, codecs: encoder.codecs, notes };
}

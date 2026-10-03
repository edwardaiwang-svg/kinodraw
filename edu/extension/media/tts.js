// The narrator's voice, in the browser: Kokoro-82M through HeadTTS (MIT; its own English G2P, no GPL eSpeak), run in a
// worker by transformers.js on WebGPU when the computer has it, else on the bundled WASM ONNX Runtime.
// Besides the audio, every character of the spoken text gets the time it is heard (captions and drawing triggers).
// Same idea as kinodraw/voice.py, one level finer: HeadTTS times each word, a word's letters share its sounding
// time proportionally, and spaces and punctuation take the time of the character before them.
import { CONFIG } from '../config.js';

const SAMPLE_RATE = 24000;
const MAX_CHUNK = 300;              // characters per inference: Kokoro reads at most 510 phonemes at a time
const vendored = (path) => new URL(`../vendor/${path}`, import.meta.url).href;

export async function createVoice({ voice = CONFIG.voice.voice, onStatus, signal } = {}) {
  const adapter = await navigator.gpu?.requestAdapter().catch(() => null);
  if (adapter) {
    try {
      return await openVoice('webgpu', CONFIG.voice.dtypeWebgpu, voice, onStatus, signal);
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      console.warn('The voice could not start on WebGPU; using WASM instead.', err);
      // The WebGPU model is already downloaded, and it is the faster one on WASM too (only bigger in memory).
      return openVoice('wasm', CONFIG.voice.dtypeWebgpu, voice, onStatus, signal);
    }
  }
  return openVoice('wasm', CONFIG.voice.dtypeWasm, voice, onStatus, signal);
}

// Speaks HeadTTS's worker protocol directly (its page-side class needs a blob: worker to load a wrapper like ours, and
// only notices a failed model load by timing out).
async function openVoice(backend, dtype, voice, onStatus, signal) {
  signal?.throwIfAborted();
  const worker = new Worker(new URL('./tts-worker.js', import.meta.url), { type: 'module' });
  const pending = new Map();
  let failure = null;
  const fail = (error) => {
    failure ??= error;
    for (const { reject } of pending.values()) reject(failure);
    pending.clear();
  };
  try {
    await new Promise((resolve, reject) => {
      signal?.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')), { once: true });
      worker.onmessage = ({ data }) => {
        if (data.type === 'progress') {
          const { loaded, total } = data.data;
          // The first reports cover only the small config files; progress would read 100 % and then drop to 0 %.
          if (total > 2 ** 20) onStatus?.({ stage: loaded < total ? 'download' : 'load', loaded, total, backend });
        } else if (data.type === 'ready') {
          resolve();
        } else if (data.type === 'failed') {
          reject(new Error(data.error));
        }
      };
      worker.onerror = (event) => reject(new Error(event.message || 'The voice worker did not start.'));
      worker.postMessage({ type: 'connect', data: {
        transformersModule: vendored('transformers/transformers.min.js'),
        model: CONFIG.voice.model,
        dtype,
        device: backend,
        styleDim: 256, frameRate: 40, audioSampleRate: SAMPLE_RATE,     // Kokoro: 256-wide styles, 40 durations/s
        languages: [], voices: [],                                      // loaded (and awaited) by the first synthesis
        dictionaryURL: vendored('headtts/dictionaries'),
        voiceURL: `https://huggingface.co/${CONFIG.voice.model}/resolve/${CONFIG.voice.revision}/voices`,
        deltaStart: 0, deltaEnd: 0,                                     // word times as spoken, no lip-sync padding
        trace: 0,
      } });
    });
  } catch (err) {
    worker.terminate();
    throw err;
  }
  onStatus?.({ stage: 'ready', backend });
  worker.onmessage = ({ data }) => {
    if (data.type === 'failed') return fail(new Error(data.error));
    const request = pending.get(data.ref);
    pending.delete(data.ref);
    if (data.type === 'audio') request?.resolve(data.data);
    else request?.reject(new Error(data.data.error));
  };
  worker.onerror = (event) => fail(new Error(event.message || 'The voice worker stopped.'));
  let nextId = 0;
  const say = (input) => new Promise((resolve, reject) => {
    if (failure) return reject(failure);
    const id = nextId++;
    pending.set(id, { resolve, reject });
    worker.postMessage({ type: 'synthesize', id, data: { input, voice, language: 'en-us', speed: 1, audioEncoding: 'pcm' } });
  });
  return {
    async synthesize(spoken) {
      const pieces = chunkText(spoken);
      const results = await Promise.all(pieces.map(say));
      const pcm = new Float32Array(results.reduce((n, r) => n + r.audio.byteLength / 2, 0));
      const parts = [];
      let at = 0;
      results.forEach((r, k) => {
        const samples = new Int16Array(r.audio);                       // HeadTTS sends 16-bit PCM
        for (let i = 0; i < samples.length; i++) pcm[at + i] = samples[i] / (samples[i] < 0 ? 0x8000 : 0x7fff);
        parts.push({ ...r, text: pieces[k], offset: at / SAMPLE_RATE });
        at += samples.length;
      });
      return { pcm, sampleRate: SAMPLE_RATE, duration: pcm.length / SAMPLE_RATE, charTimes: align(spoken, parts) };
    },
    close() {
      fail(new Error('The voice was closed.'));
      worker.terminate();
    },
  };
}

/** Pieces of `text` that Kokoro can read in one go, whole sentences where possible; they join back into `text`. */
export function chunkText(text) {
  if (!hasLetters(text)) return [];
  const pieces = [];
  let rest = text;
  while (rest.length > MAX_CHUNK) {
    const head = rest.slice(0, MAX_CHUNK);
    const sentenceEnd = [...head.matchAll(/[.!?]+["'”’)]*\s+/g)].at(-1);
    const cut = sentenceEnd ? sentenceEnd.index + sentenceEnd[0].length : head.lastIndexOf(' ') + 1 || MAX_CHUNK;
    pieces.push(rest.slice(0, cut));
    rest = rest.slice(cut);
  }
  if (hasLetters(rest)) pieces.push(rest);
  else pieces[pieces.length - 1] += rest;                            // trailing spaces or marks stay with the last piece
  return pieces;
}

/** Seconds from clip start at which each character of `spoken` is heard. `parts` are the HeadTTS results for the
 *  pieces of `spoken`, in order (words, and sounding phonemes as visemes, with start and duration in ms), each with
 *  its `text` and its `offset` in the clip (s). */
export function align(spoken, parts) {
  const times = [];
  let last = null;
  for (const { text, words, wtimes, wdurations, vtimes, vdurations, offset } of parts) {
    const spans = words.join('') === text ? words.map((word, i) => [word, wtimes[i], wtimes[i] + wdurations[i]])
      : [[text, wtimes[0] ?? 0, (wtimes.at(-1) ?? 0) + (wdurations.at(-1) ?? 0)]];   // unexpected split: one span
    for (const [word, start, end] of spans) {
      // A word's span runs on through the pause after its punctuation; its letters are heard until its last sound.
      let heard = start;
      vtimes.forEach((t, k) => {
        if (t >= start && t < end) heard = Math.max(heard, Math.min(end, t + vdurations[k]));
      });
      const letters = word.split('').filter(hasLetters).length;       // per UTF-16 unit, as charTimes are
      let seen = 0;
      for (let j = 0; j < word.length; j++) {
        if (hasLetters(word[j])) last = offset + (start + ((heard - start) * seen++) / letters) / 1000;
        times.push(last ?? offset + start / 1000);
      }
    }
  }
  while (times.length < spoken.length) times.push(last ?? 0);        // nothing was said
  for (let i = 1; i < times.length; i++) times[i] = Math.max(times[i], times[i - 1]);
  return times.map((t) => Math.round(t * 1000) / 1000);
}

const hasLetters = (s) => /[\p{L}\p{N}]/u.test(s);

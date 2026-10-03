// Narration master and light music bed (port of kinodraw/audio/mix.py).
// assembleNarration(): place every beat's clip on the timeline and normalize it to -18 LUFS (peaks limited).
// mixMusic(): lay the bundled music under the timeline's music windows (title, agenda, section transitions, outro and
// end card), ducked under speech, fading at every edge.
// Everything here is plain arithmetic on Float32Arrays, so tests run it in Node.
export const SR = 48000;
export const GAP = 0.4;                          // silence after every beat (voice.GAP in Python)
const TARGET_LUFS = -18;
const PEAK_DBFS = -1.5;
const LOOKAHEAD = 0.005;                         // s: the limiter turns down just before a peak...
const RELEASE = 0.05;                            // s: ...and back up after it
const FADE = 1.5;
const UNDER_SPEECH_LUFS = -31;
const OPEN_LUFS = -25;
const DEFAULT_TRACKS = { primary: 'fresh_focus', secondary: 'natural_vibes' };

/** clips[beatId] = { pcm, sampleRate } → mono narration @ SR, round(duration * SR) long, at -18 LUFS with no peak
 *  above -1.5 dBFS. As ffmpeg's loudnorm does in Python, the few louder peaks are turned down on their own; the voice
 *  is not made quieter as a whole. */
export function assembleNarration(board, timeline, clips) {
  const total = Math.round(timeline.duration * SR);
  const pcm = new Float32Array(total);
  for (const beat of board.beats) {
    const clip = clips[beat.id];
    const audio = resample(clip.pcm, clip.sampleRate, SR);
    const start = Math.round(timeline.beats[beat.id].start * SR);
    const n = Math.max(0, Math.min(audio.length, total - start));
    for (let i = 0; i < n; i++) pcm[start + i] += audio[i];
  }
  for (let pass = 0; pass < 2; pass++) {                        // the limiter takes a little loudness: made up once
    const measured = loudness([pcm], SR);
    if (!Number.isFinite(measured)) return pcm;                 // nothing was said
    const scale = 10 ** ((TARGET_LUFS - measured) / 20);
    for (let i = 0; i < total; i++) pcm[i] *= scale;
    limit(pcm, 10 ** ((PEAK_DBFS - 0.1) / 20));
  }
  const over = 20 * Math.log10(truePeak(pcm)) - PEAK_DBFS;
  if (over > 0) for (let i = 0; i < total; i++) pcm[i] *= 10 ** (-over / 20);   // rare, and a fraction of a dB
  return pcm;
}

/** Look-ahead peak limiter, in place: no peak ends above `ceiling`, at the samples or between them. Around each louder
 *  peak the gain dips smoothly, reaching what the peak needs exactly at the peak and recovering over RELEASE;
 *  everything else is untouched. */
export function limit(pcm, ceiling) {
  const n = pcm.length;
  const L = Math.round(LOOKAHEAD * SR);
  const held = new Float32Array(n).fill(1);                     // what each sample, or a peak just after it, needs
  for (let p = 0; p < n; p++) {
    let level = Math.abs(pcm[p]);
    if (Math.max(level, Math.abs(pcm[p + 1] ?? 0)) > ceiling / 2) level = Math.max(level, between(pcm, p));
    const need = ceiling / level;
    if (need < 1) for (let j = Math.max(0, p - L); j <= p; j++) held[j] = Math.min(held[j], need);
  }
  const r = 1 - Math.exp(-1 / (RELEASE * SR));
  for (let i = 1; i < n; i++) held[i] = Math.min(held[i], held[i - 1] + (1 - held[i - 1]) * r);
  let sum = (L + 1) * held[0];                                  // the gain: held, averaged over the look-ahead window
  for (let i = 0; i < n; i++) {                                 // (before the start it is as at the start)
    sum += held[i] - (i > L ? held[i - L - 1] : held[0]);
    pcm[i] *= Math.min(1, sum / (L + 1));
  }
}

/** The narration on both channels plus the music bed → { left, right } @ SR. loadTrack(slug) →
 *  Promise<{ channels: [Float32Array, Float32Array], sampleRate }>. */
export async function mixMusic(board, timeline, narration, { loadTrack }) {
  const total = narration.length;
  const left = Float32Array.from(narration);
  const right = Float32Array.from(narration);
  const setting = 'music' in board ? board.music : true;
  if (setting) {
    const tracks = { ...DEFAULT_TRACKS, ...(typeof setting === 'object' ? setting : {}) };
    const kinds = Object.fromEntries(board.chapters.map((c) => [c.id, c.kind]));
    const spans = Object.fromEntries(timeline.chapters.map((c) => [kinds[c.id], c]));
    const introEnd = spans.intro ? spans.intro.end : 0;
    const outroStart = spans.outro ? spans.outro.start : timeline.duration;
    const env = envelope(narration);
    const cache = new Map();
    for (const win of timeline.music) {
      const a = win.start;
      const b = Math.min(win.end, total / SR);
      const slug = a < introEnd + 1 || b > outroStart - 1 ? tracks.primary : tracks.secondary;
      if (!cache.has(slug)) cache.set(slug, prepareTrack(await loadTrack(slug)));
      const { channels, lufs } = cache.get(slug);
      const n = Math.trunc((b - a) * SR);
      if (n <= 0) continue;
      const seg = loop(channels, n);
      const gUnder = 10 ** ((UNDER_SPEECH_LUFS - lufs) / 20);
      const gOpen = 10 ** ((OPEN_LUFS - lufs) / 20);
      const i0 = Math.trunc(a * SR);
      const f = Math.min(Math.trunc(FADE * SR), Math.trunc(n / 2));
      for (let i = 0; i < n; i++) {
        let fade = 1;
        if (i < f) fade = ramp(i, f) ** 1.5;
        else if (i >= n - f) fade = (1 - ramp(i - (n - f), f)) ** 1.5;
        const g = (gOpen + (gUnder - gOpen) * env[i0 + i]) * fade;
        left[i0 + i] += seg[0][i] * g;
        right[i0 + i] += seg[1][i] * g;
      }
    }
  }
  for (let i = 0; i < total; i++) {                              // as writing the Python mix.wav does
    left[i] = Math.max(-1, Math.min(1, left[i]));
    right[i] = Math.max(-1, Math.min(1, right[i]));
  }
  return { left, right };
}

/** 0..1 speech activity, held 0.3 s and smoothed so the music bed does not pump between words. */
export function envelope(speech, window = 0.05) {
  const n = Math.trunc(SR * window);
  const frames = Math.trunc(speech.length / n) + 1;
  const active = new Uint8Array(frames);
  for (let f = 0; f < frames; f++) {
    let sum = 0;
    for (let i = f * n; i < Math.min((f + 1) * n, speech.length); i++) sum += speech[i] * speech[i];
    active[f] = 20 * Math.log10(Math.sqrt(sum / n + 1e-12) + 1e-9) > -45 ? 1 : 0;
  }
  const hold = Math.trunc(0.3 / window);                       // 5 frames, exactly as int(.3 / .05) in Python
  const out = new Float32Array(speech.length);
  let a = 0;
  for (let f = 0; f < frames; f++) {
    let held = 0;
    for (let k = Math.max(0, f - hold); k <= Math.min(frames - 1, f + hold) && !held; k++) held = active[k];
    a += (held - a) * (held > a ? 0.35 : 0.12);
    out.fill(a, f * n, Math.min((f + 1) * n, speech.length));
  }
  return out;
}

/** Integrated loudness in LUFS (ITU-R BS.1770-4: K-weighting; 400 ms blocks every 100 ms; -70 LUFS absolute gate
 *  and -10 LU relative gate). -Infinity for silence. */
export function loudness(channels, sampleRate) {
  const step = Math.round(sampleRate / 10);
  const steps = Math.floor(channels[0].length / step);
  const power = new Float64Array(steps);                       // K-weighted energy of each 100 ms, all channels
  const [shelf, highpass] = kWeighting(sampleRate);
  for (const pcm of channels) {
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0, z1 = 0, z2 = 0;
    for (let s = 0; s < steps; s++) {
      let sum = 0;
      for (let i = s * step; i < (s + 1) * step; i++) {
        const x = pcm[i];
        const y = shelf.b[0] * x + shelf.b[1] * x1 + shelf.b[2] * x2 - shelf.a[1] * y1 - shelf.a[2] * y2;
        const z = highpass.b[0] * y + highpass.b[1] * y1 + highpass.b[2] * y2 - highpass.a[1] * z1 - highpass.a[2] * z2;
        x2 = x1; x1 = x; y2 = y1; y1 = y; z2 = z1; z1 = z;
        sum += z * z;
      }
      power[s] += sum;
    }
  }
  const blocks = [];
  for (let s = 0; s + 4 <= steps; s++) blocks.push((power[s] + power[s + 1] + power[s + 2] + power[s + 3]) / (4 * step));
  const lufs = (z) => -0.691 + 10 * Math.log10(z);
  const mean = (zs) => zs.reduce((sum, z) => sum + z, 0) / zs.length;
  const loud = blocks.filter((z) => lufs(z) > -70);
  if (!loud.length) return -Infinity;
  const relative = lufs(mean(loud)) - 10;
  return lufs(mean(loud.filter((z) => lufs(z) > relative)));
}

/** Peak level including the peaks between samples (4× oversampled like BS.1770's true peak), checked only around the
 *  loudest samples: band-limited audio does not overshoot its sample peak by more than a few dB. */
export function truePeak(pcm) {
  let peak = 0;
  for (let i = 0; i < pcm.length; i++) peak = Math.max(peak, Math.abs(pcm[i]));
  let top = peak;
  for (let i = 0; i + 1 < pcm.length; i++) {
    if (Math.abs(pcm[i]) < peak / 2 && Math.abs(pcm[i + 1]) < peak / 2) continue;
    top = Math.max(top, between(pcm, i));
  }
  return top;
}

let kernels = null;
/** The largest level between sample i and sample i + 1, 4× oversampled. */
function between(pcm, i) {
  kernels ??= [0.25, 0.5, 0.75].map((frac) => Array.from({ length: 16 }, (_, k) => windowedSinc(frac + 7 - k, 8)));
  let top = 0;
  for (const kernel of kernels) {
    let v = 0;
    for (let k = 0; k < 16; k++) v += (pcm[i - 7 + k] ?? 0) * kernel[k];
    top = Math.max(top, Math.abs(v));
  }
  return top;
}

/** Band-limited rational resampling, like scipy's resample_poly (Kaiser-windowed sinc, 10 zero crossings a side). */
export function resample(pcm, from, to) {
  if (from === to) return pcm;
  const d = gcd(from, to);
  const up = to / d;
  const down = from / d;
  const rate = Math.max(up, down);
  const half = 10 * rate;
  const h = Float64Array.from({ length: 2 * half + 1 }, (_, k) => windowedSinc((k - half) / rate, 10));
  const scale = up / h.reduce((sum, v) => sum + v, 0);          // unity gain at DC after zero-stuffing by `up`
  const out = new Float32Array(Math.ceil((pcm.length * up) / down));
  for (let n = 0; n < out.length; n++) {
    const t = n * down;                                         // position on the upsampled grid; input j sits at j * up
    let acc = 0;
    for (let j = Math.max(0, Math.ceil((t - half) / up)); j <= Math.min(pcm.length - 1, Math.floor((t + half) / up)); j++) {
      acc += pcm[j] * h[half + t - j * up];
    }
    out[n] = acc * scale;
  }
  return out;
}

// K-weighting (BS.1770 stage 1 high shelf, stage 2 "RLB" high-pass) for any sample rate, from the analog prototypes
// as libebur128 derives them; at 48 kHz these are the coefficients printed in the standard.
function kWeighting(fs) {
  let K = Math.tan((Math.PI * 1681.974450955533) / fs);
  let Q = 0.7071752369554196;
  const vh = 10 ** (3.999843853973347 / 20);
  const vb = vh ** 0.4996667741545416;
  let a0 = 1 + K / Q + K * K;
  const shelf = { b: [(vh + (vb * K) / Q + K * K) / a0, (2 * (K * K - vh)) / a0, (vh - (vb * K) / Q + K * K) / a0],
    a: [1, (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0] };
  K = Math.tan((Math.PI * 38.13547087602444) / fs);
  Q = 0.5003270373238773;
  a0 = 1 + K / Q + K * K;
  const highpass = { b: [1, -2, 1], a: [1, (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0] };
  return [shelf, highpass];
}

// Python's music bed: the track looped with 1 s crossfades, n samples long.
function loop([left, right], n) {
  const seg = [new Float32Array(n), new Float32Array(n)];
  const src = [left, right];
  let pos = 0;
  while (pos < n) {
    const take = Math.min(left.length, n - pos);
    const xf = pos > 0 ? Math.min(SR, take) : 0;
    for (let c = 0; c < 2; c++) {
      for (let i = 0; i < take; i++) {
        let v = src[c][i];
        if (i < xf) {
          const r = ramp(i, xf);
          v *= r;
          seg[c][pos + i] *= 1 - r;
        }
        seg[c][pos + i] += v;
      }
    }
    pos += take - (take === left.length ? SR : 0);
  }
  return seg;
}

// Resampled to SR, loudness measured on the whole file (as Python measures the mp3), silent ends trimmed.
function prepareTrack({ channels, sampleRate }) {
  const resampled = channels.map((c) => resample(c, sampleRate, SR));
  const lufs = loudness(resampled, SR);
  const [left, right = left] = resampled;
  const audible = (i) => Math.max(Math.abs(left[i]), Math.abs(right[i])) > 1e-3;
  let first = 0;
  let last = left.length - 1;
  while (first <= last && !audible(first)) first++;
  while (last >= first && !audible(last)) last--;
  if (first > last) return { channels: [left, right], lufs };
  return { channels: [left.subarray(first, last + 1), right.subarray(first, last + 1)], lufs };
}

const ramp = (i, length) => (length > 1 ? i / (length - 1) : 0);     // np.linspace(0, 1, length)[i]
const gcd = (a, b) => (b ? gcd(b, a % b) : a);

// sinc(x) under a Kaiser window (β = 5) reaching zero at ±half.
function windowedSinc(x, half) {
  if (Math.abs(x) >= half) return 0;
  const sinc = x === 0 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x);
  return (sinc * besselI0(5 * Math.sqrt(1 - (x / half) ** 2))) / besselI0(5);
}

function besselI0(x) {
  let sum = 1;
  let term = 1;
  for (let k = 1; term > 1e-12 * sum; k++) {
    term *= (x / (2 * k)) ** 2;
    sum += term;
  }
  return sum;
}

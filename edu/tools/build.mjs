// Build the unpacked extension (edu/extension) and a store zip (edu/dist).
//   node tools/build.mjs            vendor the JS/WASM libraries (MV3 forbids remote code) + export assets if missing
//   node tools/build.mjs --assets   re-export the doodle library, vectors, fonts... from the Python app
//   node tools/build.mjs --zip      also write dist/kinodraw-classroom-<version>.zip for the Chrome Web Store
//                                   (without the manifest's "key": the store refuses it and assigns its own id)
// The asset export runs the Python app with $PYTHON (default: the repository's .venv).
import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const EDU = join(dirname(fileURLToPath(import.meta.url)), '..');
const EXT = join(EDU, 'extension');
const NM = join(EDU, 'node_modules');
const args = new Set(process.argv.slice(2));

// [from (relative to node_modules), to (relative to extension/vendor)]
const VENDOR = [
  // transformers.js (self-contained ESM) and the ONNX Runtime files it loads (same version it was built with)
  ['@huggingface/transformers/dist/transformers.min.js', 'transformers/transformers.min.js'],
  ['@huggingface/transformers/node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.mjs', 'transformers/ort-wasm-simd-threaded.asyncify.mjs'],
  ['@huggingface/transformers/node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.wasm', 'transformers/ort-wasm-simd-threaded.asyncify.wasm'],
  ['@huggingface/transformers/LICENSE', 'transformers/LICENSE'],
  // HeadTTS (MIT): Kokoro voice with word timings, no GPL phonemizer
  ['@met4citizen/headtts/modules', 'headtts/modules'],
  ['@met4citizen/headtts/dictionaries/en-us.txt', 'headtts/dictionaries/en-us.txt'],
  ['@met4citizen/headtts/LICENSE', 'headtts/LICENSE'],
  // Mediabunny (MPL-2.0): MP4 muxing over WebCodecs, plus its WASM AAC encoder for Chromebooks (patched below)
  ['mediabunny/dist/bundles/mediabunny.min.mjs', 'mediabunny/mediabunny.min.mjs'],
  ['@mediabunny/aac-encoder/dist/bundles/mediabunny-aac-encoder.mjs', 'mediabunny/mediabunny-aac-encoder.mjs'],
  ['mediabunny/LICENSE', 'mediabunny/LICENSE'],
];

// The AAC encoder imports 'mediabunny' by bare name and starts its worker from a blob: URL; the extension CSP allows
// neither. Point the import at the vendored file and move the worker (a classic script with the WASM inlined) into a
// file of its own.
function patchAacEncoder(dir) {
  const file = join(dir, 'mediabunny-aac-encoder.mjs');
  let code = readFileSync(file, 'utf8');
  const call = 'return inlineWorker(`';
  const start = code.indexOf(call);
  if (start < 0 || code.includes(call, start + 1)) throw new Error('aac-encoder: unexpected worker loader; update patchAacEncoder');
  let end = start + call.length;
  while (code[end] !== '`') end += code[end] === '\\' ? 2 : 1;               // the template literal's closing backtick
  const worker = templateValue(code.slice(start + call.length, end));
  const license = code.slice(0, code.indexOf('*/') + 2);
  writeFileSync(join(dir, 'mediabunny-aac-encoder-worker.js'), `${license}\n${worker}`);
  code = `${code.slice(0, start)}return new Worker(new URL('./mediabunny-aac-encoder-worker.js', import.meta.url)${code.slice(end + 1)}`;
  code = code.replaceAll('from "mediabunny"', 'from "./mediabunny.min.mjs"');
  if (/from\s*["']mediabunny["']/.test(code) || code.includes('createObjectURL(blob)') !== code.includes('function inlineWorker')) {
    throw new Error('aac-encoder: patch incomplete; update patchAacEncoder');
  }
  writeFileSync(file, code);
}

// The value of a template literal's text (escapes resolved; it has no ${} substitutions), without evaluating it.
function templateValue(text) {
  const named = { n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', v: '\v', 0: '\0' };
  return text.replace(/\\(u\{[\da-f]+\}|u[\da-f]{4}|x[\da-f]{2}|\r\n|[^])/gi, (_, e) => {
    if (e.length > 1 && (e[0] === 'u' || e[0] === 'x')) return String.fromCodePoint(parseInt(e.replace(/[ux{}]/g, ''), 16));
    if (/^(\r\n|[\r\n\p{Zl}\p{Zp}])$/u.test(e)) return '';                     // line continuation
    return named[e] ?? e;
  });
}

rmSync(join(EXT, 'vendor'), { recursive: true, force: true });
for (const [from, to] of VENDOR) {
  const src = join(NM, from);
  if (!existsSync(src)) throw new Error(`missing ${from}: run npm install in edu/`);
  mkdirSync(dirname(join(EXT, 'vendor', to)), { recursive: true });
  cpSync(src, join(EXT, 'vendor', to), { recursive: true });
}
patchAacEncoder(join(EXT, 'vendor', 'mediabunny'));
if (args.has('--assets') || !existsSync(join(EXT, 'assets', 'catalog.json'))) {
  execFileSync(process.env.PYTHON || join(EDU, '..', '.venv', 'bin', 'python'), [join(EDU, 'tools', 'export_assets.py')], { stdio: 'inherit' });
}
if (args.has('--zip')) {
  const { key, ...manifest } = JSON.parse(readFileSync(join(EXT, 'manifest.json'), 'utf8'));
  mkdirSync(join(EDU, 'dist'), { recursive: true });
  const out = join(EDU, 'dist', `kinodraw-classroom-${manifest.version}.zip`);
  rmSync(out, { force: true });
  execFileSync('zip', ['-qr', out, '.', '-x', 'dev/*', '*.DS_Store', 'manifest.json'], { cwd: EXT, stdio: 'inherit' });
  const staged = mkdtempSync(join(tmpdir(), 'doodle-manifest-'));
  writeFileSync(join(staged, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  execFileSync('zip', ['-qj', out, join(staged, 'manifest.json')], { stdio: 'inherit' });
  rmSync(staged, { recursive: true, force: true });
  console.log('wrote', out);
}
console.log('extension ready:', EXT);

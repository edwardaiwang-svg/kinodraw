// The browser embedder gives the vectors fastembed gave the Python app (same ONNX file, same tokenizer).
import assert from 'node:assert/strict';
import { homedir } from 'node:os';
import { test } from 'node:test';
import { createEmbedder } from '../extension/engine/embed.js';
import { fixtures } from './helpers.mjs';

const SNAP = `${homedir()}/Library/Caches/KinoDraw/embed/models--Qdrant--bge-small-en-v1.5-onnx-Q/snapshots/`;
const REV = '52398278842ec682c6f32300af41344b1c0b0bb2';

test('embeddings match fastembed', { skip: !(await import('node:fs')).existsSync(SNAP + REV) && 'no fastembed cache' }, async () => {
  const transformers = await import('@huggingface/transformers');
  transformers.env.allowRemoteModels = false;
  transformers.env.localModelPath = SNAP;
  const embed = await createEmbedder(transformers, { model: REV, file: 'model_optimized', device: 'cpu' });
  const [fx] = fixtures(['printing_press']);
  const texts = Object.keys(fx.embeddings).slice(0, 12);
  const got = await embed(texts);
  texts.forEach((t, i) => {
    const want = fx.embeddings[t];
    let dot = 0, a = 0, b = 0;
    for (let j = 0; j < want.length; j++) { dot += got[i][j] * want[j]; a += got[i][j] ** 2; b += want[j] ** 2; }
    assert.ok(dot / Math.sqrt(a * b) > 0.9999, `${t}: cosine ${dot / Math.sqrt(a * b)}`);
  });
});

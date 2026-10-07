// Execute shipped handlers with a small DOM and controlled responses, without a browser or socket.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const productRoot = process.env.STUDIO_CORE_UX_BASELINE || '.';

class Element {
  constructor(tag = 'DIV') {
    this.tagName = tag; this.value = ''; this.textContent = ''; this.style = {};
    this.disabled = false; this.checked = false; this.dataset = {}; this.children = [];
    this.parentElement = {}; this.nextElementSibling = {};
    this.isConnected = true; this.classes = new Set();
    this.classList = { add: x => this.classes.add(x), remove: x => this.classes.delete(x),
      contains: x => this.classes.has(x), toggle: (x, on) => {
        const yes = on === undefined ? !this.classes.has(x) : on;
        if (yes) this.classes.add(x); else this.classes.delete(x);
      } };
    this.content = { cloneNode: () => new Element() };
  }
  set innerHTML(html) {
    this.html = html;
    if (this.tagName === 'SELECT') {
      const options = [...html.matchAll(/<option\b([^>]*)>/g)];
      const chosen = options.find(([, attrs]) => /\bselected\b/.test(attrs)) || options[0];
      this.value = chosen?.[1].match(/value="([^"]*)"/)?.[1] || '';
    }
    for (const [tag, name, id] of [...html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)]) {
      const e = new Element(name.toUpperCase());
      e.value = tag.match(/\bvalue="([^"]*)"/)?.[1] || '';
      nodes.set('#' + id, e);
    }
  }
  get innerHTML() { return this.html || ''; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  replaceChildren(...children) {
    this.children = children;
    // Clone the actual template's fields; navigation detaches old form controls.
    for (const id of newIds) { const old = nodes.get('#' + id); if (old) old.isConnected = false; }
    for (const [tag, name, id] of [...newHTML.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)]) {
      const e = new Element(name.toUpperCase());
      e.value = tag.match(/\bvalue="([^"]*)"/)?.[1] || '';
      e.checked = /\bchecked\b/.test(tag);
      if (/\bhidden\b/.test(tag)) e.classes.add('hidden');
      nodes.set('#' + id, e);
    }
  }
}
const html = fs.readFileSync(productRoot + '/kinodraw/studio/static/index.html', 'utf8');
const newHTML = html.match(/<template id="tpl-new">([\s\S]*?)<\/template>/)[1];
const newIds = [...newHTML.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
const nodes = new Map();
for (const [, tag, id] of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) nodes.set('#' + id, new Element(tag.toUpperCase()));
nodes.set('#modal .close', new Element('BUTTON'));
const node = id => nodes.get(id);
const requests = [], ticks = [], snapshots = [], confirms = [];
let responder = () => { throw Error('Unexpected request'); }, ready, confirmAnswer = true;
const context = vm.createContext({
  window: { STUDIO_TOKEN: 'test-token', addEventListener() {} }, Blob, console,
  document: { querySelector: node, querySelectorAll: () => [],
    addEventListener: (name, fn) => { if (name === 'DOMContentLoaded') ready = fn; },
    createElement: tag => new Element(tag.toUpperCase()) },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  confirm: message => { confirms.push(message); return confirmAnswer; },
  setTimeout: (fn, ms) => { if (ms === 800) ticks.push(fn); return 1; }, clearTimeout() {},
  fetch: async (path, opts = {}) => {
    requests.push({ path, opts });
    assert.equal(opts.headers['X-Studio-Token'], 'test-token');
    const data = await responder(path, opts);
    return { ok: data.httpOK !== false, status: data.httpOK === false ? 400 : 200,
      json: async () => data };
  }
});
const run = code => vm.runInContext(code, context);
run(fs.readFileSync(productRoot + '/kinodraw/studio/static/app.js', 'utf8'));
const state = { projects_root: 'isolated', hooks: { writer: true }, advanced: true,
  default_director: 'compat', models: {}, keys: {}, cloud_languages: [], cloud_available: false,
  styles: [{ value: 'whiteboard/explain', label: 'Whiteboard' }], formats: [],
  voices: { en: [{ id: 'en-voice', name: 'English' }], zh: [{ id: 'zh-voice', name: 'Chinese' }], es: [] },
  voice_server: { on: false }, product: 'KinoDraw' };
run(`STATE = ${JSON.stringify(state)}; realLoadProjects = loadProjects; loadProjects = () => {};`);
const type = (id, value) => { const e = node(id); assert.ok(e, 'Missing actual template control: ' + id); e.value = value; e.oninput?.({ target: e }); };
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const draftText = '# 销量\n\n## 变化\n\n销量增长12%。\n';
const usage = { calls: 1, input_tokens: 10, output_tokens: 5, cost_usd: null };

async function etaScenario() {
  let resolvePoll;
  responder = path => {
    if (path.endsWith('/cancel')) return {};
    return new Promise(resolve => { resolvePoll = resolve; });
  };
  const watched = run('watch("job", "Making video")');
  const poll = async update => {
    assert.ok(ticks.length); ticks.shift()(); await flush(); resolvePoll(update); await flush();
    snapshots.push(node('#prog-stage').textContent);
    return node('#prog-stage').textContent;
  };
  const base = { state: 'running', stage: 'render', done: 10, total: 100, frames: 10, frames_total: 100, eta: 65 };
  assert.match(await poll(base), /encoding.*1m 5s remaining/i);
  for (const eta of [null, NaN, undefined, -1, Infinity, '65']) assert.doesNotMatch(await poll({ ...base, eta }), /remaining/);
  assert.match(await poll({ ...base, eta: 0 }), /encoding.*0s remaining/i);
  for (const update of [{ stage: 'finish' }, { stage: 'download-voice' }, { state: 'queued' }, { state: 'cancelling' },
    { frames: 9 }, { frames_total: 99 }, { frames: 100, done: 100 }]) {
    assert.doesNotMatch(await poll({ ...base, ...update }), /remaining/);
  }
  await node('#prog-cancel').onclick();
  assert.doesNotMatch(node('#prog-stage').textContent, /remaining/);
  assert.doesNotMatch(await poll(base), /remaining/, 'poll racing cancellation restored ETA');
  assert.doesNotMatch(await poll({ ...base, state: 'done', result: { ok: true } }), /remaining/);
  assert.equal((await watched).ok, true);
  for (const state of ['failed', 'cancelled']) {
    const failed = run('watch("job", "Making video")');
    const check = assert.rejects(failed, /stopped/);
    assert.doesNotMatch(await poll({ ...base, state, error: 'stopped' }), /remaining/);
    await check;
  }
}

function setupWriter() {
  run('showNew()');
  assert.equal(requests.length, 0, 'opening New video sent a provider request');
  type('#model', 'supporting-model'); type('#base-url', 'http://local.example/v1');
  type('#writer-topic', '销量'); type('#writer-notes', '销量增长12%。'); type('#writer-voice', '短句。');
}
async function writerScenario(kind) {
  setupWriter();
  assert.match(node('#writer-note').textContent, /provider|server/i);
  assert.match(node('#writer-note').textContent, /bill|charge|cost/i);
  assert.ok(node('#writer-draft').onclick, 'draft click is not bound by showNew');
  let resolve;
  responder = (path, opts) => {
    assert.equal(path, '/api/writer');
    const body = JSON.parse(opts.body);
    assert.deepEqual(body, { director: 'compat', model: 'supporting-model', base_url: 'http://local.example/v1',
      topic: '销量', notes: '销量增长12%。', voice: '短句。' });
    return new Promise(r => { resolve = r; });
  };
  if (kind === 'writer-conflict') type('#script', 'Existing script');
  const pending = node('#writer-draft').onclick(); await flush();
  assert.equal(requests.length, 1);
  if (kind === 'writer-conflict' || kind === 'writer-late-edit') type('#script', 'Newer user edit');
  resolve(kind === 'writer-error' ? { ok: false, error: '<img src=x> grounded failure', usage } : { ok: true, text: draftText, usage });
  await pending;
  if (kind === 'writer-error') {
    assert.equal(node('#script').value, '');
    assert.match(node('#writer-status').textContent, /<img src=x> grounded failure/);
    assert.equal(node('#writer-status').innerHTML, '');
  } else if (kind !== 'writer') {
    assert.equal(node('#script').value, 'Newer user edit');
    assert.equal(node('#writer-review').classList.contains('hidden'), false);
    assert.equal(node('#writer-text').value, draftText);
    type('#script', 'Still newer edit');
    await node('#writer-use').onclick();
    assert.equal(node('#script').value, draftText);
  } else assert.equal(node('#script').value, draftText);
  assert.equal(node('#writer-notes').value, '销量增长12%。');
  assert.equal(node('#writer-topic').value, '销量');
  assert.match(node('#writer-status').textContent, /Usage/);
  if (kind !== 'writer-error') {
    assert.equal(node('#voice').value, 'zh-voice', 'draft did not refresh detected language/voice');
    type('#script', 'The and of to is in that it for the world.');
    assert.equal(node('#voice').value, 'en-voice', 'returned script is not editable through existing handler');
  }
  assert.equal(requests.length, 1, 'draft automatically created or rendered a video');
}
async function unavailableScenario() {
  setupWriter();
  for (const value of ['rules', 'cloud', 'unknown']) {
    node('#director').value = value; await node('#director').onchange();
    assert.equal(node('#writer-draft').disabled, true);
    assert.match(node('#writer-note').textContent, /unavailable/i);
    await node('#writer-draft').onclick();
  }
  node('#director').value = 'compat'; await node('#director').onchange();
  type('#writer-notes', '');
  await node('#writer-draft').onclick();
  assert.equal(requests.length, 0, 'unsupported or topic-only draft called provider');
}
async function importScenario() {
  const raw = new Blob([fs.readFileSync(process.argv[3])], { type: 'application/zip' });
  responder = path => {
    if (path === '/api/state') return state;
    if (path === '/api/projects') return [];
    if (path === '/api/projects/import') return { project: 'imported-uuid' };
    if (path === '/api/projects/imported-uuid') return { title: 'Imported', lang: 'en', revision: 'saved',
      storyboard: { title: { en: 'Imported' }, lang: 'en', chapters: [], beats: [] },
      settings: { voice: 'en-voice', aspect: '16:9' }, videos: [] };
    throw Error('Unexpected request: ' + path);
  };
  // Keep openProject and api real; isolate unrelated drawing/narrator/media UI.
  run('renderBoard = () => {}; renderPlan = () => {}; loadNarrator = () => {}; renderVideo = () => {};');
  await ready();
  const input = node('#project-import');
  assert.ok(input?.onchange, 'import control is missing or unbound');
  await input.onchange({ target: Object.assign(input, { files: [raw] }) });
  const upload = requests.find(r => r.path === '/api/projects/import');
  assert.ok(upload, 'import did not POST');
  assert.equal(upload.opts.body, raw, 'file was encoded instead of sent as binary');
  assert.equal(upload.opts.headers['Content-Type'], undefined);
  assert.deepEqual(Buffer.from(await upload.opts.body.arrayBuffer()), fs.readFileSync(process.argv[3]));
  assert.ok(requests.some(r => r.path === '/api/projects/imported-uuid'), 'returned project was not reopened');
  assert.equal(run('current'), 'imported-uuid');
  assert.equal(input.value, '');
}
const STARTERS = [['comparison', 'Two ways to share notes', '两种分享笔记的方法'], ['explainer', 'How a library works', '图书角怎样运转'],
  ['process', 'Packing a picnic', '准备一次野餐']].flatMap(([kind, en, zh]) => [
  { id: kind + '-en', lang: 'en', title: en, example_data: true }, { id: kind + '-zh', lang: 'zh', title: zh, example_data: true }]);
const shown = () => [...node('#starters').innerHTML.matchAll(/data-starter="([^"]+)"/g)].map(m => m[1]);
const choose = id => node('#starters').onclick({ target: { closest: sel => (sel === '[data-starter]' ? { dataset: { starter: id } } : null) } });
async function startersScenario() {
  run(`STATE.starters = ${JSON.stringify(STARTERS)};`);
  run('showNew()');
  assert.equal(requests.length, 0, 'opening New video sent a request');
  assert.ok(node('#starters'), 'New video has no example gallery');
  assert.deepEqual(shown(), STARTERS.map(s => s.id), 'Detect shows every example');
  for (const [lang, ids] of [['en', ['comparison-en', 'explainer-en', 'process-en']], ['es', []], ['', STARTERS.map(s => s.id)]]) {
    node('#lang').value = lang; node('#lang').onchange();
    assert.deepEqual(shown(), ids, 'examples are not filtered by the chosen language ' + lang);
    assert.equal(node('#starter-wrap').classList.contains('hidden'), !ids.length);
  }
  const zh = '# 图书角怎样运转\n\n虚构示例故事与数据，并非真实记录。\n';
  responder = path => {
    const id = path.split('/').pop();
    const entry = STARTERS.find(s => s.id === id);
    assert.ok(path.startsWith('/api/starters/') && entry, 'unexpected request ' + path);
    return { ...entry, text: id === 'explainer-zh' ? zh : '# ' + entry.title + '\n' };
  };
  await choose('explainer-zh');
  assert.equal(node('#script').value, zh);
  assert.equal(node('#lang').value, 'zh');
  assert.equal(node('#voice').value, 'zh-voice', 'the voice list did not follow the example language');
  assert.deepEqual(shown(), ['comparison-zh', 'explainer-zh', 'process-zh']);
  await choose('comparison-zh');                    // an unedited example is swapped without asking
  assert.equal(node('#script').value, '# 两种分享笔记的方法\n');
  assert.equal(confirms.length, 0);
  type('#script', 'My own words');
  confirmAnswer = false;
  const before = requests.length;
  await choose('process-zh');
  assert.equal(node('#script').value, 'My own words', 'an example replaced typed words without asking');
  assert.equal(confirms.length, 1); assert.equal(requests.length, before);
  confirmAnswer = true;
  await choose('process-zh');
  assert.equal(node('#script').value, '# 准备一次野餐\n');
}
async function thumbnailsScenario() {
  responder = path => {
    assert.equal(path, '/api/projects');
    return [{ name: 'Rain cycle', title: 'Rain cycle', lang: 'en', videos: ['Rain cycle.mp4'], thumbnail: 'Rain cycle-thumbnail.png' },
      { name: 'Draft', title: 'Draft', lang: 'zh', videos: [], thumbnail: null }];
  };
  await run('realLoadProjects()');
  const [withVideo, draft] = node('#projects').innerHTML.split('</a>');
  assert.match(withVideo, /<img\b[^>]*\bsrc="\/files\/Rain%20cycle\/Rain%20cycle-thumbnail\.png\?token=test-token"/);
  assert.match(withVideo, /<img\b[^>]*\balt=""/);
  assert.doesNotMatch(draft, /<img\b/);
}
const scenario = process.argv[2];
try {
  if (scenario === 'eta') await etaScenario();
  else if (scenario === 'writer-unavailable') await unavailableScenario();
  else if (scenario.startsWith('writer')) await writerScenario(scenario);
  else if (scenario === 'import') await importScenario();
  else if (scenario === 'starters') await startersScenario();
  else if (scenario === 'thumbnails') await thumbnailsScenario();
  else throw Error('Unknown scenario ' + scenario);
  console.log(JSON.stringify({ scenario, actualHandlers: true, controlledResponses: true, requests: requests.map(r => r.path), snapshots, passed: true }));
} catch (error) { console.error(error); process.exitCode = 1; }

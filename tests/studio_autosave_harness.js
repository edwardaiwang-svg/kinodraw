// Minimal DOM, deterministic autosave timers and controlled HTTP; app.js runs unchanged.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const clone = value => JSON.parse(JSON.stringify(value));
class Element {
  constructor(tagName = 'DIV') {
    this.tagName = tagName; this.children = []; this.inputs = []; this.dataset = {};
    this.value = ''; this.textContent = ''; this.disabled = false;
    this.classList = { toggle() {}, add() {}, remove() {} };
    this.parentElement = {}; this.nextElementSibling = {};
    this.content = { cloneNode: () => new Element() };
  }
  set innerHTML(html) {
    this.children = [];
    this.inputs = [...html.matchAll(/<input\b[^>]*>/g)].map(([tag]) => {
      const input = new Element('INPUT');
      input.value = (tag.match(/value="([^"]*)"/) || ['', ''])[1];
      return input;
    });
  }
  querySelectorAll(selector) { return selector === 'input' ? this.inputs : []; }
  querySelector() { return null; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
}
const elements = new Map(), storage = new Map(), timers = new Map(), requests = [];
const element = selector => {
  if (!selector.startsWith('#')) return null;
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
};
let timerId = 0;
let persisted = { name: 'synthetic', title: 'Lesson', lang: 'en', credit: true,
  revision: 'r0', storyboard: { lang: 'en', title: { en: 'Lesson' },
    chapters: [{ id: 'section1', kind: 'section', title: { en: 'Original' } }], beats: [] },
  settings: { director: 'rules', aspect: '16:9', voice: 'synthetic', plan_v3: {
    cast: [], scenes: [], style: { mode: 'whiteboard', whiteboard_skin: 'plain', reason: 'fixture' }
  } }, videos: [] };
const context = vm.createContext({
  window: { STUDIO_TOKEN: 'synthetic', addEventListener() {} },
  document: { querySelector: element, querySelectorAll: () => [], addEventListener() {},
    createElement: tag => new Element(tag.toUpperCase()) },
  localStorage: { setItem: (k, v) => storage.set(k, v), getItem: k => storage.get(k), removeItem: k => storage.delete(k) },
  setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
  clearTimeout: id => timers.delete(id), Blob, console, confirm: () => true,
  fetch(path, options = {}) {
    if (options.method === 'PUT') return new Promise(resolve => {
      requests.push({ path, body: JSON.parse(options.body), resolve });
    });
    assert.equal(path, '/api/projects/synthetic');
    return Promise.resolve({ ok: true, json: async () => clone(persisted) });
  }
});
const run = code => vm.runInContext(code, context);
run(fs.readFileSync('kinodraw/studio/static/app.js', 'utf8'));
// Only auxiliary project/sidebar/media UI is stubbed; editing, rendering and navigation are real.
run(`STATE = { projects_root: 'synthetic-home', voices: { en: [] }, formats: [], hooks: {}, product: 'KinoDraw' };
  loadProjects = () => {}; loadNarrator = () => {}; renderVideo = () => {}; projectOptions = () => {};`);
const titleInput = () => element('#board').children[0].inputs[0];
const type = (input, value) => { input.value = value; input.oninput({ target: input }); };
const draft = () => JSON.parse(storage.get('kinodraw-draft:synthetic-home:synthetic') || 'null');
function autosave() {
  const entry = [...timers].find(([, task]) => task.ms === 900);
  assert.ok(entry, 'input handler did not schedule autosave');
  timers.delete(entry[0]);
  return entry[1].fn();
}
function respond(request, { adapted = false, error = false } = {}) {
  if (error) {
    request.resolve({ ok: false, status: 409, json: async () => ({ error: 'stale request', code: 'revision_conflict' }) });
    return;
  }
  persisted = { ...persisted, revision: 'r' + requests.length,
    storyboard: clone(request.body.storyboard),
    settings: { ...persisted.settings, plan_v3: clone(request.body.plan_v3) } };
  if (adapted) persisted.storyboard.chapters[0].title.en = 'Canonical';
  request.resolve({ ok: true, json: async () => ({ ok: true, revision: persisted.revision,
    storyboard: clone(persisted.storyboard), settings: clone(persisted.settings) }) });
}
async function titleScenario(adapted) {
  const input = titleInput();
  input.selectionStart = 5; input.selectionEnd = 5;
  type(input, 'First');
  const first = autosave();
  respond(requests[0], { adapted });
  assert.equal(await first, true);
  assert.equal(element('#dirty').textContent, 'Saved');
  assert.equal(storage.size, 0);
  if (!adapted) {
    assert.equal(titleInput(), input, 'unchanged save rebuilt the focused input');
    assert.equal(input.selectionStart, 5);
  } else assert.equal(titleInput().value, 'Canonical');
  type(titleInput(), 'Second');
  const second = autosave();
  assert.equal(requests[1].body.storyboard.chapters[0].title.en, 'Second', 'second input edited an obsolete chapter');
  respond(requests[1]);
  assert.equal(await second, true);
  assert.equal(persisted.storyboard.chapters[0].title.en, 'Second');
  assert.equal(element('#dirty').textContent, 'Saved');
  assert.equal(storage.size, 0);
}
async function rawDraftScenario(error) {
  type(titleInput(), 'First');
  const first = autosave();
  const raw = '[{"name":"unfinished';
  type(element('#plan-cast'), raw);
  const message = element('#dirty').textContent;
  assert.match(message, /^Invalid cast JSON:/);
  assert.equal(draft().rawPlan.cast, raw);
  respond(requests[0], { error });
  assert.equal(await first, false, 'a newer incomplete draft must block successful save/navigation');
  assert.equal(run('dirty'), true, 'late response cleared the newer raw draft');
  assert.equal(element('#dirty').textContent, message, 'late response claimed ownership of the newer input error');
  assert.equal(element('#plan-cast').value, raw);
  assert.equal(draft().rawPlan.cast, raw);
  assert.equal(requests.length, 1, 'invalid JSON must not trigger a follow-up PUT');
  assert.equal(run('revision'), error ? 'r0' : 'r1');
  run('showSample()');
  assert.equal(run('current'), null);
  assert.equal(draft().rawPlan.cast, raw, 'example navigation lost the unfinished draft');
  await run('openProject("synthetic")');
  assert.equal(run('dirty'), true);
  assert.equal(element('#plan-cast').value, raw, 'project reopening failed to recover the unfinished JSON');
  assert.match(run('planError'), /Recovered invalid plan JSON/);
  assert.equal(await run('saveBoard()'), false);
  assert.equal(requests.length, 1);
  type(element('#plan-cast'), '[]');
  const corrected = autosave();
  assert.equal(requests.length, 2);
  respond(requests[1]);
  assert.equal(await corrected, true);
  assert.equal(element('#dirty').textContent, 'Saved');
  assert.equal(storage.size, 0);
}
(async () => {
  await run('openProject("synthetic")');
  const scenario = process.argv[2];
  if (scenario === 'title' || scenario === 'adapted') await titleScenario(scenario === 'adapted');
  else if (scenario === 'raw-draft' || scenario === 'late-error') await rawDraftScenario(scenario === 'late-error');
  else throw Error('Unknown scenario: ' + scenario);
  console.log(JSON.stringify({ scenario, actualHandlers: true, controlledHTTP: true, passed: true }));
})().catch(error => { console.error(error); process.exitCode = 1; });

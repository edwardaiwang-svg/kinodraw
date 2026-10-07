// KinoDraw front end: plain JavaScript talking to the local server (see studio/server.py).
const T = window.STUDIO_TOKEN;
const $ = (sel, root = document) => root.querySelector(sel);
const COLORS = { orange: '#f57c00', blue: '#1e6fd9', green: '#2e9d4f', purple: '#8e24aa', red: '#d32f2f', teal: '#00897b' };
const CYCLE = Object.keys(COLORS);
const LANG_NAMES = { en: 'English', zh: '中文', es: 'Español' };
// The AI director is KinoDraw Cloud: the user's plan decides the model. Directors that use the user's own
// API key or program appear only when Settings -> Advanced directors is on.
const DIRECTORS = [['rules', 'Offline (free, private)'], ['cloud', 'KinoDraw Cloud AI (your plan)']];
const ADVANCED = [['openai', 'My OpenAI key'], ['anthropic', 'My Anthropic key'], ['compat', 'OpenAI-compatible server'],
  ['command', 'My own command']];
function directorOptions(selected) {
  return [...DIRECTORS, ...(STATE.advanced ? ADVANCED : [])].map(([k, v]) => {
    const soon = k === 'cloud' && !STATE.cloud_available;
    return `<option value="${k}"${soon ? ' disabled' : ''}${k === selected ? ' selected' : ''}>${soon ? 'KinoDraw Cloud AI (coming soon)' : v}</option>`;
  }).join('');
}
// "Choose for me": the video's director picks the style (studio/server.py create_project, director/style.py).
const PICKER = { rules: 'offline word rules', cloud: 'KinoDraw Cloud AI', openai: 'your OpenAI key', anthropic: 'your Anthropic key',
  compat: 'your OpenAI-compatible server', command: 'your command' };
const autoLabel = (director) => `Choose for me (${PICKER[director] || PICKER.rules})`;
function autoNote(director) {
  const who = director === 'rules'
    ? 'The offline word rules pick on this computer from words in your script; planning text is not uploaded.'
    : `${director === 'cloud' ? 'KinoDraw Cloud AI' : PICKER[director][0].toUpperCase() + PICKER[director].slice(1)} receives the full story and planning prompt to choose the video plan. Use Offline to keep planning on this computer.`;
  return `${who} Only styles that work in the chosen format are picked. Name a product below only for a promo (then the paper-collage promo can be picked).`;
}
const pickLine = (pick) => `Style: ${pick.label}, chosen by ${pick.by === 'rules' ? 'the offline word rules' : PICKER[pick.by] || pick.by}: ${pick.reason}${pick.note ? ` (${pick.note})` : ''}`;
async function needsCloudSignIn(director, lang) {   // KinoDraw Cloud picked with no email sign-in: no account needed while
  if (director !== 'cloud' || STATE.cloud_signed_in) return false;   // the cloud allows it; when it asks, open the sign-in
  if (!STATE.cloud_languages.includes(lang)) return false;          // a language it never plans is planned offline: not asked
  try { STATE.cloud = await api('/api/cloud/anonymous', { method: 'POST' }); cloudAsks = ''; return false; }
  catch (e) {
    STATE.cloud = null;
    if (e.code !== 'sign_in') return false;     // throttled or unreachable: the video is planned offline and says why
    cloudAsks = e.message;
    toast(e.message, 6000);
    showSettings();
    return true;
  }
}
function wholeVideoOffline(res) {          // KinoDraw Cloud refused the video (quota, budget, network): say so plainly
  return res?.notes?.find((n) => n.startsWith('The offline director planned this video')) || null;
}
let STATE = null, current = null, board = null, dirty = false, cloudEmail = '';   // the sign-in address, kept between openings
let revision = null, plan = null, history = [], future = [], lastEdit = null, saveTimer = null, saving = null, planError = '', rawPlan = {};
const editState = () => JSON.stringify({ board, plan });
const saveState = () => JSON.stringify({ board, plan, rawPlan, planError });
const draftKey = (name) => `kinodraw-draft:${STATE.projects_root}:${name}`;
function saveStatus(message) { if ($('#dirty')) $('#dirty').textContent = message; }
function keepDraft() {
  try { localStorage.setItem(draftKey(current), JSON.stringify({ revision, rawPlan, ...JSON.parse(editState()) })); }
  catch (e) { saveStatus('Draft could not be kept in this browser: ' + e.message); }
}

let cloudAsks = '';                         // KinoDraw Cloud's sentence when it asks for an email sign-in

async function api(path, opts = {}) {
  const type = opts.body instanceof Blob ? {} : { 'Content-Type': 'application/json' };   // a file goes up as it is
  const r = await fetch(path, { ...opts, headers: { 'X-Studio-Token': T, ...type, ...(opts.headers || {}) } });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.errors?.[0] || data.error || r.statusText), { code: data.code, status: r.status, usage: data.usage });
  return data;
}
const doodleSrc = (id) => `/doodle/${encodeURIComponent(id)}.svg?token=${T}${current ? `&project=${encodeURIComponent(current)}` : ''}`;
const fileSrc = (name) => `/files/${encodeURIComponent(current)}/${encodeURIComponent(name)}?token=${T}`;
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function toast(msg, ms = 3500) {
  const t = $('#toast'); t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.add('hidden'), ms);
}
function modal(html) { $('#modal-body').innerHTML = html; $('#modal').classList.remove('hidden'); return $('#modal-body'); }
function closeModal() { $('#modal').classList.add('hidden'); }

function voiceName(id) {
  return Object.values(STATE.voices).flat().find((v) => v.id === id)?.name || id;
}
function voiceOptions(lang, selected) {
  return STATE.voices[lang].map((v) => `<option value="${esc(v.id)}"${v.id === selected ? ' selected' : ''}>${esc(v.name)}</option>`).join('');
}
function speedRow(id) {
  return `<label class="speed" for="${id}">Speed <output id="${id}-label">1.00×</output></label>
    <div class="row muted speed-row"><span>Slower</span><input id="${id}" type="range" min="0.85" max="1.15" step="0.05" value="1"><span>Faster</span></div>`;
}
function bindSpeed(id) {
  const slider = $(`#${id}`), label = $(`#${id}-label`);
  slider.oninput = () => { label.textContent = `${Number(slider.value).toFixed(2)}×`; };
  slider.oninput();
}
let sampleAudio = null;
async function playSample(lang, id, speed, button) {      // the first sample of a voice takes a few seconds
  const url = `/api/voices/${encodeURIComponent(lang)}/${encodeURIComponent(id)}/sample?speed=${speed}&token=${T}`;
  const label = button.textContent;
  button.disabled = true; button.textContent = 'Loading…';
  try {
    const r = await fetch(url, { headers: { 'X-Studio-Token': T } });
    if (!r.ok) throw new Error((await r.json()).error || 'Could not play this sample.');
    sampleAudio?.pause();
    sampleAudio = new Audio(url);
    sampleAudio.disableRemotePlayback = true;
    sampleAudio.onerror = () => toast('Could not play this sample.', 6000);
    await sampleAudio.play();
  } catch (e) { toast(e.message, 6000); } finally { button.disabled = false; button.textContent = label; }
}
async function playServerSample(name, button) {     // Settings > Voice server reads one test sentence aloud
  const server = STATE.voice_server, label = button.textContent;
  button.disabled = true; button.textContent = 'Loading…';
  try {
    await api('/api/voice-server/test', { method: 'POST', body: JSON.stringify({ url: server.url, model: server.model, voice: name || server.voice }) });
    sampleAudio?.pause();
    sampleAudio = new Audio(`/api/voice-server/test.wav?token=${encodeURIComponent(T)}&t=${Date.now()}`);
    sampleAudio.disableRemotePlayback = true;
    sampleAudio.onerror = () => toast('Could not play this sample.', 6000);
    await sampleAudio.play();
  } catch (e) { toast(e.message, 6000); } finally { button.disabled = false; button.textContent = label; }
}
let savedVoices = null;          // the saved server's voice list, asked once until Settings change (a failure is not kept)
function serverVoices(fields) {     // the voices a server lists (POST /api/voice-server/voices); never throws
  return api('/api/voice-server/voices', { method: 'POST', body: JSON.stringify(fields) })
    .catch((e) => ({ voices: [], source: null, message: e.message }));
}
// The picker lists every voice whatever the box holds (a datalist would hide all but the typed one); any name can
// still be typed. Only the picker's latest ask fills it, so a slow answer from another address never replaces it.
function offerVoices(asked, pick, note, input) {
  pick.asked = asked;
  asked.then((found) => {
    if (!pick.isConnected || pick.asked !== asked) return;
    pick.innerHTML = `<option value="">Choose one of ${found.voices.length} voices…</option>`
      + found.voices.map((v) => `<option value="${esc(v.id)}">${esc(v.name !== v.id ? `${v.name} (${v.id})` : v.id)}</option>`).join('');
    pick.classList.toggle('hidden', !found.voices.length);
    pick.onchange = () => { if (pick.value) { input.value = pick.value; input.dispatchEvent(new Event('input')); } pick.value = ''; };
    note.textContent = found.voices.length ? '' : found.message;
  });
}
function offerSavedVoices(pick, note, input) {      // New video and Narrator: the voices of the server saved in Settings
  const server = STATE.voice_server, key = `${server.url}\n${server.model}`;
  if (savedVoices?.key !== key) {
    const asked = { key, found: serverVoices({ url: server.url, model: server.model }) };
    savedVoices = asked;
    asked.found.then((found) => { if (!found.voices.length && savedVoices === asked) savedVoices = null; });   // ask again next time
  }
  offerVoices(savedVoices.found, pick, note, input);
}
const voiceMeta = (id, server) => (STATE.voice_server?.on      // with Settings > Voice server on, it reads every video
  ? `voice server (${server || STATE.voice_server.voice || STATE.voice_server.model})` : `voice ${voiceName(id)}`);

const MAKE = ['storyboard', 'director', 'voice', 'timeline', 'render', 'finish'];
async function watch(job, title, order = MAKE, own = false) {     // own: narrated from the user's recording
  let cancelling = false;
  $('#prog-cancel').disabled = false;
  $('#prog-cancel').onclick = async () => {
    cancelling = true; $('#prog-cancel').disabled = true;
    $('#prog-stage').textContent = 'Cancellation requested; waiting for the current step to stop…';
    try { await api(`/api/jobs/${job}/cancel`, { method: 'POST' }); }
    catch (e) { cancelling = false; $('#prog-cancel').disabled = false; toast(e.message); }
  };
  $('#prog-title').textContent = title; $('#prog-fill').style.width = '2%'; $('#progress').classList.remove('hidden');
  $('#prog-stage').textContent = 'Starting';
  const STAGES = { storyboard: 'Reading the script', style: 'Choosing a style', director: 'Planning the visuals', voice: 'Recording the narration',
    timeline: 'Timing captions and music', render: 'Drawing the video (the longest step)', finish: 'Adding music, captions and chapters',
    'download-search': 'Downloading the doodle search (first video only)', 'download-voice': 'Downloading the voice (first video only)',
    ...(own ? { voice: 'Getting ready to listen to your recording', align: 'Matching your recording to each sentence',
      timeline: 'Timing every drawing to your voice' } : {}) };
  const SLOT = { 'download-search': 'storyboard', style: 'storyboard', 'download-voice': 'voice', align: 'voice' };   // these fill their step's share
  const MB = (n) => Math.round(n / 1e6);
  for (;;) {
    await new Promise((r) => setTimeout(r, 800));
    const j = await api(`/api/jobs/${job}`);
    const frac = j.total ? j.done / j.total : 0;
    const k = Math.max(0, order.includes(j.stage) ? order.indexOf(j.stage) : order.indexOf(SLOT[j.stage]));
    $('#prog-fill').style.width = `${Math.min(99, ((k + frac) / order.length) * 100)}%`;
    const count = j.stage.startsWith('download') ? ` · ${MB(j.done)} of ${MB(j.total)} MB (${Math.floor(frac * 100)}%)`
      : j.total > 1 ? ` · ${j.done}/${j.total}` : '';
    const seconds = Math.ceil(j.eta);
    const eta = !cancelling && j.state === 'running' && j.stage === 'render'
      && Number.isFinite(j.eta) && j.eta >= 0 && Number.isFinite(j.frames) && j.frames >= 0
      && Number.isFinite(j.frames_total)
      && j.frames === j.done && j.frames_total === j.total && j.frames < j.frames_total
      ? ` · Encoding: ~${seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`} remaining` : '';
    $('#prog-stage').textContent = cancelling || j.state === 'cancelling' ? 'Cancellation requested; waiting for the current step to stop…' : `${STAGES[j.stage] || 'Starting'}${count}${eta}`;
    if (['done', 'failed', 'cancelled'].includes(j.state)) {
      $('#progress').classList.add('hidden');
      if (j.state !== 'done') throw new Error(j.error);
      return j.result;
    }
  }
}

// ---------------------------------------------------------------- sidebar
async function loadProjects() {
  const items = await api('/api/projects');
  $('#projects').innerHTML = items.map((p) => `<a data-name="${esc(p.name)}" class="${p.name === current ? 'on' : ''}">
    ${esc(p.title)}<small>${p.broken ? 'incomplete' : `${LANG_NAMES[p.lang]} · ${p.videos?.length ? '🎬 ready' : 'storyboard'}`}</small></a>`).join('')
    || '<div class="muted">No videos yet.</div>';
  $('#projects').querySelectorAll('a').forEach((a) => (a.onclick = () => openProject(a.dataset.name)));
}

// ---------------------------------------------------------------- example
function showSample() {          // a finished video that ships with the app: plays at once, nothing to download
  if (dirty && current) keepDraft();
  clearTimeout(saveTimer); dirty = false; planError = ''; rawPlan = {}; current = null; loadProjects();
  $('#main').replaceChildren($('#tpl-sample').content.cloneNode(true));
  $('#s-make').onclick = showNew;
}

// ---------------------------------------------------------------- new video
function scriptLang(text) {      // same rule as kinodraw/ingest.py detect_lang: Chinese when over 30% of letters are Chinese
  const letters = text.match(/\p{L}/gu) || [];
  const chinese = letters.filter((c) => /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(c)).length;
  if (letters.length && chinese / letters.length > 0.3) return 'zh';
  const words = text.match(/\p{L}+/gu) || [];
  const caps = words.map((w) => w[0] !== w[0].toLowerCase()).concat(false);
  const spanish = new Set('el la los las de del que y en un una es por con para se no su al lo como más pero sus le ya o este esta son también'.split(' '));
  const english = new Set('the and of to is in that it for was on are with as this be by you'.split(' '));
  const es = words.filter((w, i) => spanish.has(w.toLowerCase()) && !(caps[i] && caps[i + 1])).length
    + words.filter((w, i) => !caps[i]).join(' ').replace(/[^áéíóúüñ]/g, '').length + 2 * (text.match(/[¿¡]/g) || []).length;
  const en = words.filter((w) => english.has(w.toLowerCase())).length;
  return es >= 2 && es > 2 * en + 1 ? 'es' : 'en';
}

function syncNewVoice() {      // New video: with Settings > Voice server on, the server reads the script
  const title = $('#nv-ai-title');
  if (!title) return;
  const server = STATE.voice_server || {}, input = $('#server-voice'), label = $('#voice-label');
  title.textContent = server.on ? 'Voice server' : 'Built-in voice';
  $('#nv-ai-note').textContent = server.on ? `Your voice server (${input.value.trim() || server.voice || server.model}) reads your script`
    : 'A natural AI voice reads your script';
  $('#voice').classList.toggle('hidden', !!server.on); input.classList.toggle('hidden', !server.on);
  input.placeholder = server.voice || 'the server’s default';
  label.textContent = server.on ? 'Server voice (optional)' : 'Voice'; label.htmlFor = server.on ? 'server-voice' : 'voice';
  if (!server.on) { $('#server-voice-note').textContent = ''; $('#server-voice-pick').classList.add('hidden'); }
}

function showNew() {
  if (dirty && current) keepDraft();
  clearTimeout(saveTimer); dirty = false; planError = ''; rawPlan = {}; current = null; loadProjects();
  $('#main').replaceChildren($('#tpl-new').content.cloneNode(true));
  const langSel = $('#lang'), voiceSel = $('#voice'), dirSel = $('#director');
  const voiceLang = () => langSel.value || scriptLang($('#script').value);
  const fillVoices = () => {
    voiceSel.innerHTML = voiceOptions(voiceLang());
    const cloudOption = dirSel.querySelector('option[value="cloud"]');
    if (cloudOption) {
      cloudOption.disabled = !STATE.cloud_available || !STATE.cloud_languages.includes(voiceLang());
      if (cloudOption.disabled && dirSel.value === 'cloud') { dirSel.value = 'rules'; dirSel.onchange?.(); }
    }
  };
  const scriptInput = $('#script');
  let scriptEdits = 0;
  langSel.onchange = fillVoices; scriptInput.oninput = () => { scriptEdits++; if (!langSel.value) fillVoices(); };
  fillVoices();
  $('#speed-wrap').innerHTML = speedRow('speed');
  bindSpeed('speed');
  $('#voice-play').onclick = (e) => (STATE.voice_server?.on ? playServerSample($('#server-voice').value.trim(), e.currentTarget)
    : playSample(voiceLang(), voiceSel.value, $('#speed').value, e.currentTarget));
  $('#server-voice').oninput = syncNewVoice;
  syncNewVoice();
  if (STATE.voice_server?.on) offerSavedVoices($('#server-voice-pick'), $('#server-voice-note'), $('#server-voice'));
  const ownVoice = () => document.querySelector('input[name="narrator"]:checked').value === 'own';
  document.querySelectorAll('input[name="narrator"]').forEach((r) => (r.onchange = () => $('#voice-wrap').classList.toggle('hidden', ownVoice())));
  dirSel.innerHTML = directorOptions(STATE.default_director);
  const note = () => {
    const d = dirSel.value;
    $('#byo').classList.toggle('hidden', !['openai', 'anthropic', 'compat', 'command'].includes(d));
    $('#base-wrap').classList.toggle('hidden', d !== 'compat');
    $('#model').placeholder = (STATE.models[d] || [])[0] || 'model name';
    $('#director-note').textContent = {
      rules: 'Offline: free and private. Visuals are chosen by matching words to 1,700+ doodles on your computer.',
      cloud: STATE.cloud ? `KinoDraw Cloud, ${esc(STATE.cloud.plan || 'free')} plan: ${STATE.cloud.remaining === null ? 'unlimited videos (fair use)' : `${STATE.cloud.remaining ?? '?'} videos left this month`}.` : STATE.cloud_signed_in ? 'KinoDraw Cloud: signed in.' : cloudAsks || 'KinoDraw Cloud AI receives your full story and planning prompt. Anonymous access depends on availability and quota. Choose Offline for local planning; a configured voice server still receives narration text.',
      openai: STATE.keys.openai ? 'Uses your OpenAI key (about $0.02 per 15-minute video with GPT-6 Luna).' : 'Add your OpenAI key under Settings first.',
      anthropic: STATE.keys.anthropic ? 'Uses your Anthropic key (about $1 per 15-minute video with Opus).' : 'Add your Anthropic key under Settings first.',
      compat: 'Any OpenAI-compatible server (OpenRouter, Groq, a local Ollama…): set the base URL and model.',
      command: STATE.keys.command ? 'Runs your saved command once per section; the model name is passed along to it.' : 'Save your command under Settings first.',
    }[d];
    if (d !== 'rules') $('#director-note').textContent += ' Planning uploads your full story and prompt to the selected provider. Choose Offline for local planning.';
    else $('#director-note').textContent += ' Initial asset downloads may use the network; a configured voice server receives narration text.';
    writerNote();
  };
  dirSel.onchange = async () => {
    note(); syncStyle();
    if (dirSel.value === 'cloud' && STATE.cloud_available && !STATE.cloud    // nothing goes to the cloud before this
        && (STATE.cloud_signed_in || STATE.cloud_languages.includes(voiceLang()))) {   // nor for a language it never plans
      try { STATE.cloud = await (STATE.cloud_signed_in ? api('/api/cloud/me') : api('/api/cloud/anonymous', { method: 'POST' })); cloudAsks = ''; }
      catch (e) { STATE.cloud = null; if (e.code === 'sign_in') cloudAsks = e.message; }   // the note and Settings say it asks
      note();
    }
  };
  const draftButton = $('#writer-draft'), draftStatus = $('#writer-status');
  let drafting = false;
  const writerAvailable = () => STATE.hooks?.writer && ['openai', 'anthropic', 'compat', 'command'].includes(dirSel.value);
  function writerNote() {
    const available = writerAvailable();
    $('#writer-note').textContent = available
      ? 'Only Draft from notes sends your topic, source notes and local voice/style guidance to the selected provider or command, using the model and base URL below. Provider billing may apply. Review the draft and check its facts before creating a storyboard.'
      : 'Drafting is unavailable with this director. Choose a supporting provider under Settings → Advanced directors (OpenAI, Anthropic, OpenAI-compatible, or your command). Offline and KinoDraw Cloud do not support drafting.';
    draftButton.disabled = drafting || !available;
  }
  const usageText = usage => usage ? ` · Usage: ${JSON.stringify(usage)}` : '';
  $('#writer-use').onclick = () => {
    if (!scriptInput.isConnected) return;
    scriptInput.value = $('#writer-text').value; scriptInput.oninput(); fillVoices();
    $('#writer-review').classList.add('hidden');
    draftStatus.textContent = 'Draft inserted. Edit and check it before creating a storyboard.' + draftStatus.usage;
  };
  $('#writer-dismiss').onclick = () => $('#writer-review').classList.add('hidden');
  draftButton.onclick = async () => {
    if (drafting || !writerAvailable()) return;
    const topic = $('#writer-topic').value.trim(), notes = $('#writer-notes').value.trim();
    if (!topic || !notes) { draftStatus.textContent = 'Add a topic and source notes. A topic alone is not evidence.'; return; }
    const before = scriptInput.value, edits = scriptEdits;
    drafting = true; writerNote(); draftStatus.textContent = 'Drafting from your source notes…';
    $('#writer-review').classList.add('hidden');
    try {
      const result = await api('/api/writer', { method: 'POST', body: JSON.stringify({ director: dirSel.value,
        model: $('#model').value, base_url: dirSel.value === 'compat' ? $('#base-url').value : '', topic, notes, voice: $('#writer-voice').value }) });
      if (!scriptInput.isConnected) return;
      if (!result.ok) throw Object.assign(new Error(result.error || 'The provider could not draft from these notes.'), { usage: result.usage });
      if (typeof result.text !== 'string' || !result.text.trim()) throw new Error('The writer returned an empty draft.');
      draftStatus.usage = usageText(result.usage);
      if (before.trim() || scriptEdits !== edits || scriptInput.value !== before) {
        $('#writer-text').value = result.text; $('#writer-review').classList.remove('hidden');
        draftStatus.textContent = 'Your script is kept. Review the returned draft below, then choose Replace script with this draft.' + draftStatus.usage;
      } else {
        scriptInput.value = result.text; scriptInput.oninput(); fillVoices();
        draftStatus.textContent = 'Draft inserted. Edit and check it before creating a storyboard.' + draftStatus.usage;
      }
    } catch (error) {
      if (scriptInput.isConnected) draftStatus.textContent = error.message + usageText(error.usage);
    } finally { drafting = false; if (scriptInput.isConnected) writerNote(); }
  };
  note();
  $('#file').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    $('#file-name').textContent = '';
    try {
      if (/\.(md|txt)$/i.test(f.name)) $('#script').value = await f.text();
      else if (/\.docx$/i.test(f.name)) {
        const data = btoa(new Uint8Array(await f.arrayBuffer()).reduce((s, b) => s + String.fromCharCode(b), ''));
        $('#script').value = (await api('/api/upload', { method: 'POST', body: JSON.stringify({ name: f.name, data }) })).text;
      } else throw new Error(/\.pages$/i.test(f.name)
        ? 'Pages files can’t be read. In Pages, choose File → Export To → Word…, then choose the .docx.'
        : 'Choose a .md, .txt or .docx file.');
      $('#file-name').textContent = f.name; fillVoices();
      scriptEdits++;
    } catch (err) { toast(err.message, 8000); } finally { e.target.value = ''; }
  };
  $('#style').innerHTML = `<option id="style-auto" value="auto">${esc(autoLabel(dirSel.value))}</option>`
    + STATE.styles.map((s, i) => `<option value="${esc(s.value)}"${i ? '' : ' selected'}>${esc(s.label)}</option>`).join('');
  $('#format').innerHTML = formatOptions('16:9');
  function syncStyle() {                    // a promo names its product; the whiteboard ignores Motion
    const auto = $('#style').value === 'auto', collage = $('#style').value === 'collage/promo';
    $('#style-auto').textContent = autoLabel(dirSel.value);
    $('#brand').classList.toggle('hidden', !collage && !auto);
    $('#motion-wrap').classList.toggle('hidden', !collage);
    $('#style-note').classList.toggle('hidden', !auto);
    $('#style-note').textContent = auto ? autoNote(dirSel.value) : '';
  }
  $('#style').onchange = syncStyle;
  syncStyle();
  $('#create').onclick = async () => {
    if (await needsCloudSignIn(dirSel.value, voiceLang())) return;
    try {
      const auto = $('#style').value === 'auto';
      const [look, story] = auto ? ['auto', null] : $('#style').value.split('/');
      const brand = { name: $('#brand-name').value.trim(), url: $('#brand-url').value.trim(), cta: $('#brand-cta').value.trim() };
      const body = { text: $('#script').value, title: $('#title').value, lang: langSel.value, voice: voiceSel.value,
        speed: Number($('#speed').value),
        director: dirSel.value, director_v3: $('#director-v3').checked, model: $('#model').value, base_url: $('#base-url').value, look, story, aspect: $('#format').value,
        motion: look === 'collage' ? $('#motion').value : null, brand: story === 'promo' || auto ? brand : null,
        ...(STATE.voice_server?.on ? { server_voice: $('#server-voice').value.trim() } : {}) };
      const { job, project } = await api('/api/projects', { method: 'POST', body: JSON.stringify(body) });
      const res = await watch(job, 'Creating the storyboard');
      const whole = wholeVideoOffline(res);
      if (whole) toast(whole, 8000);
      else if (res?.style) toast(pickLine(res.style), 9000);
      else if (res?.notes?.length) toast(`${res.notes.length} AI suggestions were replaced by the offline plan`);
      await openProject(project, ownVoice() ? 'narrator' : null);
    } catch (e) { $('#progress').classList.add('hidden'); toast(e.message, 6000); }
  };
}

// ---------------------------------------------------------------- project
function formatOptions(selected) {
  const formats = [...STATE.formats];
  if (!formats.some((f) => f.value === '1:1')) formats.push({ value: '1:1', label: 'Square 1:1' });
  return formats.map((f) => `<option value="${esc(f.value)}"${f.value === selected ? ' selected' : ''}>${esc(f.label)}</option>`).join('');
}

function nativeTarget() {
  const value = $('#p-native-target').value;
  if (!value) return {};
  const [aspect, width, height] = value.split(',');
  return { aspect, size: [Number(width), Number(height)] };
}

async function openProject(name, tab = null) {
  if (dirty && current && current !== name && !(await saveBoard())) return;
  if (saving) await saving;
  clearTimeout(saveTimer);
  current = name; dirty = false; loadProjects();
  const p = await api(`/api/projects/${encodeURIComponent(name)}`);
  board = p.storyboard; revision = p.revision; plan = p.settings.plan_v3 || null; planError = ''; rawPlan = {};
  history = []; future = []; lastEdit = editState();
  let draft;
  try { draft = JSON.parse(localStorage.getItem(draftKey(name)) || 'null'); } catch (e) { /* malformed browser draft ignored */ }
  if (draft && (JSON.stringify({ board: draft.board, plan: draft.plan }) !== lastEdit || Object.keys(draft.rawPlan || {}).length)) {
    if (confirm('Recover the edits kept in this browser? A conflicting draft will require version review before it can be saved.')) {
      board = draft.board; plan = draft.plan; revision = draft.revision; rawPlan = draft.rawPlan || {}; if (Object.keys(rawPlan).length) planError = 'Recovered invalid plan JSON — correct it before saving'; dirty = true; lastEdit = editState();
    }
  }
  $('#main').replaceChildren($('#tpl-project').content.cloneNode(true));
  $('#p-title').textContent = p.title;
  saveStatus(dirty ? 'Recovered draft — save or review versions' : 'Saved');
  $('#p-save').disabled = !dirty;
  $('#p-undo').onclick = () => travelHistory(false);
  $('#p-redo').onclick = () => travelHistory(true);
  $('#p-versions').onclick = showVersions;
  for (const action of ['rename', 'duplicate', 'trash']) $('#p-' + action).onclick = async () => {
    if (dirty && !(await saveBoard())) return;
    const title = action === 'rename' ? prompt('Project title', p.title) : undefined;
    if (action === 'rename' && !title) return;
    if (action === 'trash' && !confirm('Move this project to Trash? You can restore it from the sidebar.')) return;
    try {
      const res = await api(`/api/projects/${encodeURIComponent(name)}/${action}`, { method: 'POST', body: JSON.stringify({ revision, title }) });
      if (action === 'trash') { current = null; dirty = false; loadProjects(); showSample(); }
      else await openProject(res.project || name);
    } catch (e) { toast(e.message); }
  };
  const report = p.settings.plan_v3_report;
  $('#p-plan-source').textContent = report ? `Planner: ${report.provider || 'unknown'}${report.fallback ? ' · Offline fallback: ' + report.fallback_reason : ''}${report.model ? ' · ' + report.model : ''}` : 'Legacy/manual storyboard';
  renderPlan();
  $('#p-meta').textContent = `${board.beats.length} beats · ${LANG_NAMES[p.lang]}${p.settings.aspect === '9:16' ? ' · vertical 9:16' : ''} · ${p.settings.recording ? 'narrated in your own voice' : voiceMeta(p.settings.voice, p.settings.server_voice)}`;
  $('#p-style').textContent = plan ? `Saved v3 style: ${plan.style.mode} · ${plan.style.whiteboard_skin} · ${plan.style.reason}` : p.settings.style_pick ? pickLine(p.settings.style_pick) : '';
  $('#p-style').classList.toggle('hidden', !plan && !p.settings.style_pick);
  $('#p-format').innerHTML = formatOptions(p.settings.aspect || '16:9');
  $('#p-format').onchange = async () => {
    try {
      if (dirty && !(await saveBoard())) return;
      const cfg = await api(`/api/projects/${encodeURIComponent(name)}/format`, { method: 'POST', body: JSON.stringify({ aspect: $('#p-format').value, revision }) });
      p.settings.aspect = cfg.aspect;
      const meta = $('#p-meta');
      meta.textContent = meta.textContent.replace(' · vertical 9:16', '');
      if (cfg.aspect === '9:16') {
        const last = meta.textContent.lastIndexOf(' · ');
        meta.textContent = `${meta.textContent.slice(0, last)} · vertical 9:16${meta.textContent.slice(last)}`;
      }
      await openProject(name); toast('Format saved. Make video to render it.');
    } catch (e) { $('#p-format').value = p.settings.aspect || '16:9'; toast(e.message, 6000); }
  };
  const credit = $('#p-credit');
  credit.checked = p.credit;
  credit.nextElementSibling.textContent = `"Made with ${STATE.product}" end card`;
  credit.parentElement.title = `Ends the video with a 2-second "Made with ${STATE.product}" card. Untick to leave it off this video.`;
  credit.onchange = async () => {
    try {
      if (dirty && !(await saveBoard())) return;
      const cfg = await api(`/api/projects/${encodeURIComponent(name)}/credit`, { method: 'POST', body: JSON.stringify({ credit: credit.checked, revision }) });
      p.credit = cfg.credit;
      await openProject(name); toast(`End card ${p.credit ? 'on' : 'off'}. Make video to apply it.`);
    } catch (e) { credit.checked = p.credit; toast(e.message, 6000); }
  };
  projectOptions(name, p);                                         // music, paper and hand: options.js
  $('#p-director').innerHTML = directorOptions(p.settings.director || 'rules');
  $('#p-redirect').onclick = async () => {
    if (await needsCloudSignIn($('#p-director').value, p.lang)) return;
    if (dirty && !(await saveBoard())) return;
    try {
      const res = await watch((await api(`/api/projects/${encodeURIComponent(name)}/direct`, { method: 'POST', body: JSON.stringify({ director: $('#p-director').value, revision }) })).job, 'Planning the visuals');
      const whole = wholeVideoOffline(res);
      if (whole) toast(whole, 8000);
      else toast(res?.cost ? `Done · AI cost $${res.cost.toFixed(4)}` : 'Visuals re-planned');
      openProject(name);
    } catch (e) { toast(e.message, 6000); }
  };
  $('#p-reveal').onclick = () => api(`/api/projects/${encodeURIComponent(name)}/reveal`, { method: 'POST' });
  for (const kind of ['export', 'projectzip']) {
    const button = $('#p-' + kind);
    button.classList.toggle('hidden', !STATE.hooks?.[kind]);
    button.onclick = async () => {
      if (dirty && !(await saveBoard())) return;
      try {
        const body = kind === 'export' ? { revision, format: $('#p-export-format').value, ...nativeTarget() } : { revision };
        const response = await api(`/api/projects/${encodeURIComponent(name)}/${kind}`, { method: 'POST', body: JSON.stringify(body) });
        const result = await watch(response.job, kind === 'export' ? 'Exporting' : 'Packing the project');
        if (!result?.file) throw new Error('The export hook returned no downloadable file.');
        modal(`<h2>Export ready</h2><a href="${fileSrc(result.file)}" target="_blank">Download ${esc(result.format || 'ZIP')}</a>${result.audio_file ? `<p>${esc(result.audio_note)}</p><a href="${fileSrc(result.audio_file)}" target="_blank">Download audio companion</a>` : ''}`);
      } catch (e) { $('#progress').classList.add('hidden'); toast(e.message, 7000); }
    };
  }
  $('#p-make').onclick = () => makeVideo(name);
  $('#p-save').onclick = saveBoard;
  document.querySelectorAll('.tabs button').forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  renderBoard(); updateHistory();
  renderVideo(p);
  loadNarrator(name, tab === 'narrator' ? 'own' : undefined);     // opened from New video with My own voice chosen
  if (tab || p.videos?.length) showTab(tab || 'video');
}

function showTab(tab) {
  document.querySelectorAll('.tabs button').forEach((x) => x.classList.toggle('on', x.dataset.tab === tab));
  for (const t of ['board', 'narrator', 'video']) $(`#tab-${t}`).classList.toggle('hidden', t !== tab);
}

function updateHistory() {
  if ($('#p-undo')) $('#p-undo').disabled = !history.length;
  if ($('#p-redo')) $('#p-redo').disabled = !future.length;
}
function markDirty(record = true) {
  const next = editState();
  if (record && lastEdit !== next) { history.push(lastEdit); history = history.slice(-100); future = []; }
  lastEdit = next; dirty = true; $('#p-save').disabled = false;
  keepDraft(); saveStatus('Unsaved changes'); updateHistory();
  clearTimeout(saveTimer); saveTimer = setTimeout(saveBoard, 900);
}
function travelHistory(redo) {
  const source = redo ? future : history, target = redo ? history : future;
  if (!source.length) return;
  target.push(editState()); const state = JSON.parse(source.pop());
  board = state.board; plan = state.plan; planError = ''; rawPlan = {};
  markDirty(false); renderBoard(); renderPlan();
}
function renderPlan() {
  const box = $('#p-plan'); if (!box) return;
  box.classList.toggle('hidden', !plan);
  if (!plan) return;
  for (const key of ['cast', 'scenes', 'style']) {
    const input = $('#plan-' + key);
    input.value = rawPlan[key] ?? JSON.stringify(plan[key], null, 2);
    input.oninput = () => {
      try { plan[key] = JSON.parse(input.value); delete rawPlan[key]; planError = Object.keys(rawPlan).length ? 'Correct invalid plan JSON before saving' : ''; markDirty(); }
      catch (e) { clearTimeout(saveTimer); rawPlan[key] = input.value; planError = 'Invalid ' + key + ' JSON: ' + e.message; dirty = true; keepDraft(); saveStatus(planError); }
    };
  }
}
async function showVersions() {
  try {
    const items = await api(`/api/projects/${encodeURIComponent(current)}/versions`);
    const box = modal(`<h2>Versions</h2><button id="version-save">Save named version</button><div>${items.map(x => `<p>${esc(x.label)} · ${esc(x.created)} <button data-version="${x.id}">Restore</button></p>`).join('') || 'No versions yet'}</div>`);
    $('#version-save', box).onclick = async () => {
      const label = prompt('Version name'); if (!label) return;
      if (dirty && !(await saveBoard())) return;
      try { await api(`/api/projects/${encodeURIComponent(current)}/versions`, { method: 'POST', body: JSON.stringify({ revision, label }) }); showVersions(); }
      catch (e) { toast(e.message); }
    };
    box.querySelectorAll('[data-version]').forEach(button => button.onclick = async () => {
      if (!confirm('Restore this version? The current saved state will also become a version.')) return;
      if (dirty) keepDraft();
      try {
        const res = await api(`/api/projects/${encodeURIComponent(current)}/restore`, { method: 'POST', body: JSON.stringify({ revision, version: button.dataset.version }) });
        localStorage.removeItem(draftKey(current)); dirty = false; closeModal(); await openProject(current);
      } catch (e) { saveStatus(e.message); toast(e.message); }
    });
  } catch (e) { toast(e.message); }
}

function renderBoard() {
  const lang = board.lang, root = $('#board');
  root.innerHTML = '';
  let section = 0;
  for (const ch of board.chapters) {
    const beats = board.beats.filter((b) => b.chapter === ch.id);
    const color = ch.kind === 'section' ? COLORS[ch.color || CYCLE[section++ % CYCLE.length]] : '#55606a';
    const head = document.createElement('div');
    head.className = 'chapter';
    const label = ch.label?.[lang] || { intro: 'Title', agenda: 'Agenda', outro: 'Ending' }[ch.kind] || ch.kind;
    head.innerHTML = `<span class="pill" style="background:${color}">${esc(label)}</span>`;
    if (ch.kind === 'section') {
      head.innerHTML += `<input value="${esc(ch.title?.[lang])}" title="Section title (agenda card)"><input class="hook" value="${esc(ch.hook?.[lang] || '')}" placeholder="Short hook for the agenda card">`;
      const [t, h] = head.querySelectorAll('input');
      t.oninput = () => { ch.title = { [lang]: t.value }; markDirty(); };
      h.oninput = () => { ch.hook = { [lang]: h.value }; markDirty(); };
    }
    root.appendChild(head);
    beats.forEach((b) => root.appendChild(beatCard(b, ch)));
  }
}

function beatCard(b, ch) {
  const lang = board.lang;
  const el = document.createElement('div');
  el.className = 'beat';
  el.dataset.beat = b.id;
  const auto = b.kind === 'title' || b.kind === 'agenda' || ch.kind === 'intro';
  el.innerHTML = `<div><div class="kind">${esc({ take: 'takeaway', opener: 'section opener', closing: 'closing', title: 'title board', agenda: 'agenda card' }[b.kind] || 'narration')}</div>
    <div class="text">${esc(b.display[lang])}</div>
    ${b.kind === 'take' ? `<label class="take">Takeaway note <input value="${esc(b.take.headline[lang])}"></label>` : ''}
    <div class="beat-tools">${auto ? '<span class="muted">Drawn automatically</span>' : '<button class="small add">+ Doodle</button>'}<button class="small prev">Preview</button></div>
    <div class="preview"></div></div><div class="visuals"></div>`;
  const vis = el.querySelector('.visuals');
  (b.visuals || []).forEach((v, i) => vis.appendChild(visualCard(b, v, i)));
  el.querySelector('.take input')?.addEventListener('input', (e) => { b.take.headline = { [lang]: e.target.value }; markDirty(); });
  el.querySelector('.add')?.addEventListener('click', () => pickDoodle(b.display[lang].split(/[.。]/)[0], (id) => {
    b.visuals = b.visuals || [];
    b.visuals.push({ id: `${b.id}u${Date.now() % 100000}`, type: 'cluster', relation: 'none', items: [{ doodle: id }] });
    markDirty(); renderBoard();
  }));
  el.querySelector('.prev').onclick = () => showBeatPreview(el, b.id);
  return el;
}

function showBeatPreview(el, beat, fresh = false) {
  const img = document.createElement('img');
  img.alt = 'preview';
  img.onload = () => img.classList.toggle('tall', img.naturalHeight > img.naturalWidth);
  img.src = `/api/projects/${encodeURIComponent(current)}/still?beat=${encodeURIComponent(beat)}&offset=4&token=${T}${fresh ? `&v=${Date.now()}` : ''}`;
  el.querySelector('.preview').replaceChildren(img);
}

const SLOT_TYPES = ['cluster', 'quote', 'glossary', 'stat'];   // pictures that can be drawn earlier or later

async function reorderPicture(beat, visual, to, item = null) {
  if (dirty && !(await saveBoard())) return;
  const project = current, sent = board, main = $('#main');
  main.inert = true;                                  // no edits while the move saves: the reply replaces the board
  try {
    const res = await api(`/api/projects/${encodeURIComponent(project)}/reorder`, {
      method: 'POST', body: JSON.stringify({ storyboard: sent, revision, beat, visual, to, item })
    });
    if (current !== project || board !== sent) return; // another project (or a fresh copy) was opened meanwhile
    if (!res.ok) { toast('Not moved: ' + res.errors[0]); return; }
    history.push(editState()); history = history.slice(-100); future = []; board = res.storyboard; revision = res.revision; lastEdit = editState(); updateHistory();
    dirty = false; $('#p-save').disabled = true; $('#dirty').textContent = 'Saved';
    renderBoard();
    const card = [...$('#board').querySelectorAll('.beat')].find((el) => el.dataset.beat === beat);
    if (card) showBeatPreview(card, beat, true);
    loadNarrator(current, document.querySelector('input[name="n-pick"]:checked')?.value);
  } catch (e) { toast('Not moved: ' + e.message); } finally { main.inert = false; }
}

function visualCard(b, v, i) {
  const lang = board.lang;
  const el = document.createElement('div');
  el.className = 'vis';
  const typeName = { cluster: 'doodles', stat: 'number', quote: 'quote', glossary: 'sticky note', lanes: 'timeline', grid100: '100 squares', bars: 'bar chart', flow: 'flow', split: 'comparison' }[v.type] || v.type;
  el.innerHTML = `<div class="type">${esc(typeName)}${v.size === 'margin' ? ' · beside the note' : ''}</div><button class="del" title="Remove">×</button>`;
  const movable = (k) => SLOT_TYPES.includes(b.visuals[k]?.type);     // a page keeps its place (server rule)
  if (movable(i) && (movable(i - 1) || movable(i + 1))) {
    el.insertAdjacentHTML('beforeend', `<div class="draw-order">
      <button class="small earlier" title="Draw earlier" aria-label="Draw earlier"${movable(i - 1) ? '' : ' disabled'}>↑</button>
      <button class="small later" title="Draw later" aria-label="Draw later"${movable(i + 1) ? '' : ' disabled'}>↓</button></div>`);
    el.querySelector('.earlier').onclick = () => reorderPicture(b.id, i, i - 1);
    el.querySelector('.later').onclick = () => reorderPicture(b.id, i, i + 1);
  }
  if (v.type === 'cluster') {
    const items = document.createElement('div');
    items.className = 'items';
    v.items.forEach((it, j) => {
      const d = document.createElement('div');
      d.className = 'item';
      d.innerHTML = `<img src="${doodleSrc(it.doodle)}" title="${esc(it.doodle)} — click to swap"><input value="${esc(it.label?.[lang] || '')}" placeholder="label">`;
      d.querySelector('img').onclick = () => pickDoodle(it.label?.[lang] || b.display[lang].slice(0, 40), (id) => { it.doodle = id; markDirty(); renderBoard(); });
      d.querySelector('input').oninput = (e) => { it.label = e.target.value ? { [lang]: e.target.value } : undefined; if (!it.label) delete it.label; markDirty(); };
      if (v.items.length > 1) {
        d.insertAdjacentHTML('beforeend', `<div class="draw-order">
          <button class="small earlier" title="Draw earlier" aria-label="Draw earlier"${j === 0 ? ' disabled' : ''}>←</button>
          <button class="small later" title="Draw later" aria-label="Draw later"${j === v.items.length - 1 ? ' disabled' : ''}>→</button></div>`);
        d.querySelector('.earlier').onclick = () => reorderPicture(b.id, i, j - 1, j);
        d.querySelector('.later').onclick = () => reorderPicture(b.id, i, j + 1, j);
      }
      items.appendChild(d);
    });
    el.appendChild(items);
  } else {
    const text = v.value?.[lang] ? `${v.value[lang]} ${v.label?.[lang] || ''}` : v.term?.[lang] ? `${v.term[lang]}: ${v.text?.[lang] || ''}`
      : v.text?.[lang] || v.title?.[lang] || '';
    el.insertAdjacentHTML('beforeend', `<div class="summary">${esc(text)}</div>`);
  }
  el.querySelector('.del').onclick = () => { b.visuals.splice(i, 1); markDirty(); renderBoard(); };
  return el;
}

async function pickDoodle(query, onPick) {
  const project = current, opened = board;
  const pick = (id) => {           // an upload can finish after the picker closed, while or after a move replaced the board
    if (board !== opened || $('#main').inert) { toast('Your picture was not placed because the board changed while it uploaded. Choose it again under Your pictures.', 7000); return; }
    closeModal(); onPick(id);
  };
  const body = modal(`<h3>Choose a doodle</h3><label class="file">Upload a picture<input id="picture-file" type="file" accept=".png,.jpg,.jpeg,.svg,image/png,image/jpeg,image/svg+xml"></label><p class="picture-hint">PNG, JPG or SVG, up to 10 MB. It stays on your computer.</p><div id="own-pictures" class="hidden"><h4>Your pictures</h4><div class="pick-grid" id="own-picks"></div></div><input id="q" value="${esc(query)}" placeholder="Search: rocket, 地球, idea…"><div class="pick-grid" id="picks"></div>`);
  $('#picture-file', body).onchange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error(`“${file.name}” is too big (over 10 MB). Make it smaller and try again.`);
      const res = await api(`/api/projects/${encodeURIComponent(project)}/pictures?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file });
      pick(res.id);
    } catch (e) { toast(e.message, 6000); }
    event.target.value = '';
  };
  api(`/api/projects/${encodeURIComponent(project)}/pictures`).then((items) => {
    if (!items.length) return;
    $('#own-pictures', body).classList.remove('hidden');
    $('#own-picks', body).innerHTML = items.map((d) => `<div class="pick" data-id="${esc(d.id)}"><img src="${doodleSrc(d.id)}"><div>${esc(d.name)}</div></div>`).join('');
    $('#own-picks', body).querySelectorAll('.pick').forEach((p) => (p.onclick = () => pick(p.dataset.id)));
  }).catch((e) => toast(e.message, 6000));
  const run = async () => {
    const items = await api(`/api/doodles?q=${encodeURIComponent($('#q', body).value)}&lang=${board.lang}`);
    $('#picks', body).innerHTML = items.map((d) => `<div class="pick" data-id="${esc(d.id)}"><img src="${doodleSrc(d.id)}"><div>${esc((d.desc || d.id).slice(0, 40))}</div></div>`).join('');
    body.querySelectorAll('.pick').forEach((p) => (p.onclick = () => pick(p.dataset.id)));
  };
  let timer;
  $('#q', body).oninput = () => { clearTimeout(timer); timer = setTimeout(run, 250); };
  run();
}

async function saveBoard() {
  clearTimeout(saveTimer);
  if (planError) { saveStatus(planError); return false; }
  if (saving) { await saving; return dirty ? saveBoard() : true; }
  if (!dirty) return true;
  const name = current, sent = saveState(), expected = revision;
  saveStatus('Saving…');
  saving = (async () => {
    try {
      const snapshot = JSON.parse(sent);
      const res = await api(`/api/projects/${encodeURIComponent(name)}/storyboard`, { method: 'PUT', body: JSON.stringify({ storyboard: snapshot.board, plan_v3: snapshot.plan, revision: expected }) });
      if (!res.ok) throw new Error(res.errors[0]);
      if (current !== name) return true;
      revision = res.revision;
      if (saveState() === sent) {
        const adapted = JSON.stringify(board) !== JSON.stringify(res.storyboard);
        const savedPlan = res.settings.plan_v3 || null;
        const adaptedPlan = JSON.stringify(plan) !== JSON.stringify(savedPlan);
        if (adapted) board = res.storyboard;
        if (adaptedPlan) plan = savedPlan;
        lastEdit = editState();
        if (adapted) renderBoard();
        if (adaptedPlan) renderPlan();
        dirty = false; $('#p-save').disabled = true; saveStatus('Saved');
        localStorage.removeItem(draftKey(name));
        if (plan && $('#p-style')) $('#p-style').textContent = `Saved v3 style: ${plan.style.mode} · ${plan.style.whiteboard_skin} · ${plan.style.reason}`;
        loadNarrator(name, document.querySelector('input[name="n-pick"]:checked')?.value);
      } else { keepDraft(); saveStatus(planError || 'Unsaved changes'); }
      return true;
    } catch (e) {
      if (current === name) { keepDraft(); saveStatus(planError || (saveState() === sent ? 'Not saved: ' + e.message : 'Unsaved changes')); }
      return false;
    }
  })();
  const ok = await saving; saving = null;
  if (ok && dirty && current === name) return saveBoard();
  return ok;
}
window.addEventListener('beforeunload', event => {
  if (dirty || planError) { keepDraft(); event.preventDefault(); event.returnValue = ''; }
});
document.addEventListener('keydown', event => {
  if (!(event.ctrlKey || event.metaKey) || !current) return;
  if (event.key.toLowerCase() === 's') { event.preventDefault(); saveBoard(); }
  if (event.key.toLowerCase() === 'z' && !['INPUT', 'TEXTAREA'].includes(event.target.tagName)) {
    event.preventDefault(); travelHistory(event.shiftKey);
  }
});

async function makeVideo(name, anyway = false) {   // anyway: the user saw which sentences don't fit and goes ahead
  if (dirty && !(await saveBoard())) return;
  let narr = await api(`/api/projects/${encodeURIComponent(name)}/narrator`);
  const own = narr.narrator === 'own';
  if (!own && document.querySelector('input[name="n-pick"]:checked')?.value === 'own') {   // chosen, nothing recorded yet
    showTab('narrator');
    toast('Upload your recording first, or choose the built-in voice.', 8000);
    return;
  }
  const stop = (message) => { showTab('narrator'); renderNarrator(name, narr); toast(message, 10000); };
  try {
    if (own && narr.changed.length && !anyway) {  // the script was edited after the recording was made
      stop(`${sentences(narr.changed)} changed after you recorded. Record it again, or press Make the video anyway.`);
      return;
    }
    let fresh = false;
    if (own && !narr.check) {                     // a new recording: check it against the script first
      narr = await watch((await api(`/api/projects/${encodeURIComponent(name)}/align`, { method: 'POST' })).job,
        'Listening to your recording', ['voice', 'align', 'timeline'], true);
      renderNarrator(name, narr);
      fresh = true;
    }
    if (own && !narr.check.ok) {                  // a take that does not fit: fix it there first
      stop('Your recording doesn’t match the script yet. Record it again, or choose the built-in voice.');
      return;
    }
    const unseen = narr.check?.poor.filter((n) => !anyway || fresh && !narr.changed.includes(n)) || [];
    if (own && unseen.length) {                   // some sentences don't fit: say which before drawing anything
      stop(`${sentences(unseen)} didn’t match your recording. Record it again, or press Make the video anyway.`);
      return;
    }
    const res = await watch((await api(`/api/projects/${encodeURIComponent(name)}/make`, { method: 'POST', body: JSON.stringify({ revision, ...nativeTarget() }) })).job, 'Making your video', MAKE, own);
    toast(res.ok ? `Video ready (${res.length})` : `Video made, with warnings: ${res.problems[0]}`, 6000);
    await openProject(name);
    document.querySelector('.tabs button[data-tab="video"]').click();
    feedbackCard($('#tab-video'));
  } catch (e) {
    $('#progress').classList.add('hidden'); toast(e.message, 10000);
    if (own) { showTab('narrator'); loadNarrator(name, undefined, e.message); }
  }
}

function renderVideo(p) {
  const box = $('#tab-video');
  if (!p.videos?.length) {
    box.innerHTML = '<div class="empty"><h2>No video yet</h2><p class="muted">Check the storyboard, then press <b>Make video</b>. A 3-minute video takes about 3 minutes.</p></div>';
    return;
  }
  const video = p.videos[p.videos.length - 1];
  const stem = video.replace(/\.mp4$/, '');
  const files = [[`${stem}.srt`, 'Captions (.srt)'], [`${stem}-chapters.txt`, 'Chapters'], [`${stem}-description.txt`, 'Description'],
    [`${stem}-transcript.md`, 'Transcript'], [`${stem}-thumbnail.png`, 'Thumbnail']];
  const qa = p.qa ? `<div class="qa ${p.qa.ok ? 'ok' : 'bad'}">${p.qa.ok ? '✓ Checked: every frame decodes, audio matches, chapters embedded.' : `Check: ${esc(p.qa.problems.join('; '))}`}</div>` : '';
  box.innerHTML = `<video controls disableremoteplayback preload="metadata" poster="${fileSrc(`${stem}-thumbnail.png`)}" src="${fileSrc(video)}"></video>${qa}
    <div class="files">${files.map(([f, l]) => `<a href="${fileSrc(f)}" target="_blank">${l}</a>`).join('')}</div>
    <p class="muted">The files are in your project folder (Open folder). Music: ${p.storyboard.music?.file ? 'your own' : 'FreePD (CC0)'}. ${p.settings.voice_server && !p.settings.recording ? `Narration: ${esc(p.settings.voice_server.voice || p.settings.voice_server.model)} from your voice server.` : p.settings.recording ? 'Narration: your own voice.' : 'Narration: Kokoro AI voice.'}</p>`;
}

// ---------------------------------------------------------------- narrator (your own voice)
function sentences(ns) {                       // [4, 5, 6, 9] -> "Sentences 4–6 and 9"
  const runs = [];
  for (const n of ns) { const r = runs[runs.length - 1]; if (r && r[1] === n - 1) r[1] = n; else runs.push([n, n]); }
  const parts = runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`));
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
  return `${ns.length === 1 ? 'Sentence' : 'Sentences'} ${list}`;
}

async function loadNarrator(name, choice, problem) {
  try {
    const info = await api(`/api/projects/${encodeURIComponent(name)}/narrator`);
    if (problem) info.check = { ok: false, poor: [], missing: [], problem };    // what just went wrong, in its words
    renderNarrator(name, info, choice || info.narrator);
  }
  catch (e) { toast(e.message, 6000); }
}

function narratorResult(info) {
  const check = info.check, changed = info.changed;
  if (!info.take) return '';
  const again = 'Record the whole script again, reading every numbered sentence below as written, then upload it.';
  if (changed.length && check?.ok !== false) {
    return `<div class="result warn"><p>${sentences(changed)} changed after you recorded (marked below), so your
      recording says something else there. ${again}</p>
      <p>Or make the video now: your voice will say the old words while the captions show the new ones.</p>
      <button id="n-make" class="ghost">Make the video anyway</button></div>`;
  }
  if (!check) return `<div class="result">Press <b>Use it for this video</b>: ${esc(STATE.product)} listens to your recording and times every drawing to your voice. It takes about a minute.</div>`;
  const { missing, poor } = check;
  const detail = check.problem ? `<details><summary>More detail</summary>${esc(check.problem)}</details>` : '';
  if (check.ok && !poor.length) {
    return `<div class="result ok"><p>✓ All ${info.lines.length} sentences matched. Your video will be narrated in your own voice.</p>
      <button id="n-make" class="primary">Make video</button></div>`;
  }
  if (check.ok) {
    return `<div class="result warn"><p>${sentences(poor)} didn’t match your recording: ${poor.length === 1 ? 'it' : 'they'}
      may have been skipped or read differently (marked below). ${again}</p>
      <p>Or make the video now: the drawings for ${poor.length === 1 ? 'that sentence' : 'those sentences'} may not line up.</p>
      <button id="n-make" class="ghost">Make the video anyway</button></div>`;
  }
  if (missing.length) {                         // the voice step's refusal names the part: say it as it is
    return `<div class="result bad"><p>Your recording doesn’t follow the script: ${sentences(missing).toLowerCase()}
      ${missing.length === 1 ? 'wasn’t' : 'weren’t'} found in it (marked below). ${again}</p>
      ${check.problem ? `<p>${esc(check.problem)}</p>` : ''}<p>Or choose <b>Built-in voice</b> above.</p></div>`;
  }
  if (poor.length) {
    return `<div class="result bad"><p>Your recording doesn’t sound like this script. ${again}</p>${detail}</div>`;
  }
  return `<div class="result bad"><p>${esc(check.problem || 'Your recording doesn’t match this script.')}</p></div>`;
}

function renderNarrator(name, info, choice = info.narrator) {
  const box = $('#tab-narrator');
  if (!box || current !== name) return;
  const own = choice === 'own', check = info.check;
  const server = STATE.voice_server?.on ? STATE.voice_server : null;     // Settings > Voice server reads the script
  const pick = `<div class="narrator-pick">
    <span class="pick-label">Narrator</span>
    <label class="seg"><input type="radio" name="n-pick" value="builtin"${own ? '' : ' checked'}><b>${server ? 'Voice server' : 'Built-in voice'}</b>
      <small>${server ? `Your voice server (${esc(info.server_voice || server.voice || server.model)}) reads your script` : `A natural AI voice (${esc(voiceName(info.voice))}) reads your script`}</small></label>
    <label class="seg"><input type="radio" name="n-pick" value="own"${own ? ' checked' : ''}><b>My own voice</b>
      <small>You read the script aloud; every drawing follows your voice</small></label></div>`;
  if (!own) {
    box.innerHTML = `${pick}<form id="n-voice-form">
      <div class="grid"><div><label for="${server ? 'n-server-voice' : 'n-voice'}">${server ? 'Server voice (optional)' : 'Voice'}</label><div class="row">
        <select id="n-voice"${server ? ' class="hidden"' : ''}>${voiceOptions(info.lang, info.voice)}</select>
        ${server ? `<input id="n-server-voice" maxlength="80" value="${esc(info.server_voice)}" placeholder="${esc(server.voice || 'the server’s default')}">` : ''}
        <button id="n-play" type="button" class="ghost" aria-label="Play a sample of this voice">▶ Hear it</button>
      </div>${server ? '<select id="n-server-voice-pick" class="hidden" aria-label="Voices your server lists"></select><div id="n-server-voice-note" class="muted"></div>' : ''}</div><div>${speedRow('n-speed')}</div></div>
      <label>Pronunciations <textarea id="n-pronounce" rows="4" placeholder="GIF = jif&#10;Nguyen = win"></textarea></label>
      <p class="muted">One per line: word = how to say it. Changes how the voice says a word; captions keep your spelling. All-caps words like WHO and mixed-case ones like iPhone match only as typed; others match in any case.</p>
      <button id="n-save" type="submit" class="primary" disabled>Save voice settings</button></form>`;
  } else {
    const lines = info.lines.map((l, i) => {
      const mark = check?.missing.includes(i + 1) ? 'miss' : info.changed.includes(i + 1) ? 'changed'
        : check?.poor.includes(i + 1) ? 'poor' : '';
      const tag = { miss: 'not found', changed: 'changed since you recorded', poor: 'didn’t match' }[mark];
      return `<li class="${mark}">${esc(l.text)}${tag ? ` <span class="tag">${tag}</span>` : ''}</li>`;
    }).join('');
    box.innerHTML = `${pick}
      <ol class="how"><li>Read the script below aloud and record it, on your phone or any recorder.</li>
        <li>Upload the recording here.</li><li>Press <b>Use it for this video</b>.</li></ol>
      <div class="row take-row">
        <label class="file upload">Upload a recording <input id="n-file" type="file"></label>
        <span id="n-take" class="muted">${info.take ? `Your recording: ${esc(info.take)}` : 'No recording yet'}</span>
      </div>
      ${info.take ? `<audio controls disableremoteplayback preload="none" src="${fileSrc(info.take)}"></audio>` : ''}
      <button id="n-use" class="${check?.ok ? 'ghost' : 'primary'}"${info.take ? '' : ' disabled'}>Use it for this video</button>
      <div id="n-result">${narratorResult(info)}</div>
      <p class="tip"><b>Read it naturally</b>, at your usual pace, and pause for a moment between sentences. Record it in
        one go, start to finish, somewhere quiet. A phone’s voice memo app works well: send the recording to this
        computer, then upload it.</p>
      <ol class="read-aloud" lang="${esc(info.lang)}">${lines}</ol>`;
  }
  box.querySelectorAll('input[name="n-pick"]').forEach((r) => (r.onchange = async () => {
    try {
      if (r.value === 'builtin' && info.narrator === 'own' || r.value === 'own' && info.take) {
        if (dirty && !(await saveBoard())) return;
        const next = await api(`/api/projects/${encodeURIComponent(name)}/narrator`, { method: 'POST', body: JSON.stringify({ narrator: r.value }) });
        toast(r.value === 'own' ? 'Your video will be narrated in your own voice' : 'Your video will use the built-in voice');
        await openProject(name, 'narrator');
        $('#p-meta').textContent = $('#p-meta').textContent.replace(/[^·]*$/, ` ${r.value === 'own' ? 'narrated in your own voice' : voiceMeta(next.voice, next.server_voice)}`);
      } else renderNarrator(name, info, r.value);
    } catch (e) { toast(e.message, 6000); }
  }));
  if (!own) {
    const form = $('#n-voice-form', box), select = $('#n-voice', form), slider = $('#n-speed', form);
    const pronounce = $('#n-pronounce', form), save = $('#n-save', form), serverVoice = $('#n-server-voice', form);
    bindSpeed('n-speed');
    if (serverVoice) offerSavedVoices($('#n-server-voice-pick', form), $('#n-server-voice-note', form), serverVoice);
    $('#n-play', form).onclick = (e) => (serverVoice ? playServerSample(serverVoice.value.trim(), e.currentTarget)
      : playSample(info.lang, select.value, slider.value, e.currentTarget));
    api(`/api/projects/${encodeURIComponent(name)}/voice`).then((settings) => {
      if (!form.isConnected) return;
      select.value = settings.voice; slider.value = settings.speed; slider.oninput();
      if (serverVoice) serverVoice.value = settings.server_voice || '';
      pronounce.value = settings.pronounce; save.disabled = false;
    }).catch((e) => toast(e.message, 6000));
    form.onsubmit = async (e) => {
      e.preventDefault(); save.disabled = true;
      try {
        if (dirty && !(await saveBoard())) return;
        const settings = await api(`/api/projects/${encodeURIComponent(name)}/voice`, { method: 'PUT',
          body: JSON.stringify({ revision, voice: select.value, speed: Number(slider.value), pronounce: pronounce.value,
            ...(serverVoice ? { server_voice: serverVoice.value } : {}) }) });
        info.voice = settings.voice;
        info.server_voice = settings.server_voice;
        await openProject(name, 'narrator');
        $('#p-meta').textContent = $('#p-meta').textContent.replace(/[^·]*$/, ` ${voiceMeta(settings.voice, settings.server_voice)}`);
        toast('Saved');
      } catch (err) { toast(err.message, 6000); }
      finally { save.disabled = false; }
    };
    return;
  }
  const showProblem = (msg) => { $('#n-result', box).innerHTML = `<div class="result bad"><p>${esc(msg)}</p></div>`; };
  $('#n-file', box).onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    $('#n-take', box).textContent = `Adding ${f.name}…`;
    try {
      if (dirty && !(await saveBoard())) return;
      renderNarrator(name, await api(`/api/projects/${encodeURIComponent(name)}/recording?filename=${encodeURIComponent(f.name)}`, { method: 'POST', body: f }));
      await openProject(name, 'narrator');
      $('#p-meta').textContent = $('#p-meta').textContent.replace(/[^·]*$/, ' narrated in your own voice');
    } catch (err) {
      $('#n-take', box).textContent = info.take ? `Your recording: ${info.take}` : 'No recording yet';
      showProblem(err.message);
    } finally { e.target.value = ''; }
  };
  $('#n-use', box).onclick = async () => {
    try {
      if (dirty && !(await saveBoard())) return;
      const job = (await api(`/api/projects/${encodeURIComponent(name)}/align`, { method: 'POST' })).job;
      renderNarrator(name, await watch(job, 'Listening to your recording', ['voice', 'align', 'timeline'], true));
      await openProject(name, 'narrator');
    } catch (e) { $('#progress').classList.add('hidden'); showProblem(e.message); }
  };
  $('#n-make', box)?.addEventListener('click', () => makeVideo(name, true));
}

// ---------------------------------------------------------------- feedback
// Sent to KinoDraw Cloud only when the user presses Send (studio/server.py send_feedback): no account, any director.
const ISSUES = 'https://github.com/edwardaiwang-svg/kinodraw/issues/new/choose';
const PRIVACY = 'https://edwardaiwang-svg.github.io/kinodraw/privacy.html';
const RATINGS = [['5', '5, very well'], ['4', '4'], ['3', '3'], ['2', '2'], ['1', '1, not at all']];
const USES = [['school', 'School'], ['work', 'Work'], ['personal', 'Personal'], ['other', 'Something else']];
let feedbackDraft = {};          // what the form held when it closed or could not send: nothing typed is lost
function showFeedback() {
  const d = feedbackDraft, lang = current && board ? board.lang : null;     // the open project's language, if any
  const options = (list, chosen) => `<option value="">Choose…</option>`
    + list.map(([v, l]) => `<option value="${v}"${String(chosen ?? '') === v ? ' selected' : ''}>${l}</option>`).join('');
  const body = modal(`<div class="feedback"><h2>Feedback or a problem? Tell us</h2>
    <form id="f-form">
      <label for="f-text">What would you like to tell us?<textarea id="f-text" rows="5" maxlength="2000"
        placeholder="What worked, what didn’t, what you wish it did…">${esc(d.text)}</textarea></label>
      <div class="grid">
        <label for="f-rating">How well did KinoDraw work for this video?<select id="f-rating">${options(RATINGS, d.rating)}</select></label>
        <label for="f-use">What was the video for?<select id="f-use">${options(USES, d.use)}</select></label>
      </div>
      <label for="f-url">Link to your video, if you posted it<input id="f-url" type="url" maxlength="300" placeholder="https://…" value="${esc(d.video_url)}"></label>
      <label class="row"><input id="f-quote" type="checkbox"${d.quote_ok ? ' checked' : ''}><span>KinoDraw may quote what I wrote, without my name, on its site and in reports about KinoDraw</span></label>
      <label class="row"><input id="f-age" type="checkbox"${d.age_13_plus ? ' checked' : ''}><span>I am 13 or older</span></label>
      <label id="f-email-wrap" for="f-email"${d.age_13_plus ? '' : ' class="hidden"'}>Email, if you'd like a reply (optional)<input id="f-email" type="email" maxlength="200" placeholder="you@example.com" value="${esc(d.email)}"${d.age_13_plus ? '' : ' disabled'}></label>
      <p id="f-result" class="note" role="status" aria-live="polite"></p>
      <div class="send-row"><p class="muted">Send gives KinoDraw Cloud what you typed and ticked, plus the app version, your computer type, language and install ID.
        <a href="${PRIVACY}#feedback" target="_blank">Privacy</a></p><button id="f-send" type="submit" class="primary">Send</button></div>
    </form>
    <p class="muted github">Prefer GitHub? <a href="${ISSUES}" target="_blank">Open an issue</a></p></div>`);
  const form = $('#f-form', body), send = $('#f-send', body);
  const open = () => $('#f-form') === form && !$('#modal').classList.contains('hidden');    // not closed or replaced
  const read = () => ({ text: $('#f-text', form).value, rating: $('#f-rating', form).value, use: $('#f-use', form).value,
    video_url: $('#f-url', form).value, quote_ok: $('#f-quote', form).checked, age_13_plus: $('#f-age', form).checked,
    email: $('#f-email', form).value });
  form.oninput = () => { feedbackDraft = read(); };
  $('#f-age', form).onchange = (e) => {             // 13+ only; disabled when hidden, so a half-typed email can't stop Send
    $('#f-email-wrap', form).classList.toggle('hidden', !e.target.checked);
    $('#f-email', form).disabled = !e.target.checked;
  };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = read();
    send.disabled = true; send.textContent = 'Sending…'; $('#f-result', form).textContent = '';
    try {
      await api('/api/feedback', { method: 'POST', body: JSON.stringify({ ...f, rating: f.rating ? Number(f.rating) : null,
        use: f.use || null, email: f.age_13_plus ? f.email : undefined, ...(lang ? { lang } : {}) }) });
      feedbackDraft = {}; STATE.feedback_sent = true;
      const card = $('#tab-video .feedback-card');
      if (card) feedbackCard(card.parentElement);               // from now on, only a quiet link there
      if (open()) {
        body.innerHTML = '<div class="feedback"><h2>Thank you!</h2><p>We got it, and we read every message.</p><button id="f-done" class="primary">Close</button></div>';
        $('#f-done', body).onclick = closeModal;
      } else toast('Thank you! Your feedback was sent.');
    } catch (err) {                                             // the form keeps everything, to press Send again
      $('#f-result', form).textContent = err.message;
      if (!open()) toast(err.message, 8000);
    } finally { send.disabled = false; send.textContent = 'Send'; }
  };
  $('#f-text', form).focus();
}

function feedbackCard(box) {     // after a video the user made: a small card, never in the way of watching or saving it
  if (!box) return;
  box.querySelector('.feedback-card, .feedback-more')?.remove();
  const card = document.createElement('div');
  if (STATE.feedback_sent) {
    card.className = 'feedback-more';
    card.innerHTML = '<a role="button" tabindex="0">Send more feedback</a>';
  } else {
    card.className = 'feedback-card';
    card.innerHTML = '<span><a role="button" tabindex="0">How did this video go? Tell us in 30 seconds</a></span><button class="x" title="Dismiss" aria-label="Dismiss">×</button>';
    card.querySelector('.x').onclick = () => card.remove();
  }
  const open = card.querySelector('a');
  open.onclick = showFeedback;
  open.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); showFeedback(); } };
  box.prepend(card);
}

// ---------------------------------------------------------------- settings
function showSettings() {
  const voiceServer = STATE.voice_server || { on: false, url: '', model: '', voice: '', key_saved: false };
  const cloud = STATE.cloud_available ? `<section><h3>KinoDraw Cloud</h3>
      <p class="muted">${STATE.cloud_signed_in && STATE.cloud ? `Signed in · ${esc(STATE.cloud.plan)} plan · ${STATE.cloud.remaining === null ? 'unlimited videos (fair use)' : `${esc(STATE.cloud.remaining)} videos left this month`}` : STATE.cloud_signed_in ? 'Signed in.' : cloudAsks ? esc(cloudAsks) : STATE.cloud ? 'Free, with no account or API key. Signing in with your email is optional.' : 'Free, with no account or API key, while KinoDraw Cloud allows it; if it asks, sign in with your email here.'}
        <a href="https://edwardaiwang-svg.github.io/kinodraw/privacy.html" target="_blank">What is sent (privacy)</a></p>
      ${STATE.install_id || STATE.cloud?.install_id ? `<p class="muted">This installation's ID: <code>${esc(STATE.install_id || STATE.cloud.install_id)}</code>. To delete what KinoDraw Cloud keeps for it, email it to privacy@doodlecloud.org.</p>` : ''}
      <div class="row"><input id="c-email" placeholder="you@example.com" value="${esc(cloudEmail)}"><button id="c-send" class="small">Email me a code</button></div>
      <p id="c-note" class="muted hidden"></p>
      <div class="row" style="margin-top:6px"><input id="c-code" placeholder="6-digit code"><button id="c-verify" class="small">Sign in</button></div></section>` : '';
  const body = modal(`<div class="settings"><h2>Settings</h2>${cloud}
    <section><h3>Advanced directors</h3><label class="row"><input id="s-adv" type="checkbox" style="width:auto"${STATE.advanced ? ' checked' : ''}>
      <span>Show directors that use your own API key or program (billed by that provider, not by KinoDraw Cloud)</span></label>
      ${STATE.advanced ? `<p class="muted">Stored in your system keychain, never in project files. A command gets each request as JSON on stdin and prints the plan as JSON.</p>
      <div class="row"><select id="k-prov" style="width:auto"><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="compat">OpenAI-compatible</option><option value="command">Command</option></select>
      <input id="k-key" type="password" placeholder="sk-…"><button id="k-save" class="small">Save</button></div>
      <p class="muted">Saved: ${esc(Object.entries(STATE.keys).filter(([, v]) => v).map(([k]) => k).join(', ') || 'none')}</p>` : ''}</section>
    <section><h3>Voice server</h3><label class="row"><input id="vs-on" type="checkbox" style="width:auto"${voiceServer.on ? ' checked' : ''}>
      <span>Read scripts with my own OpenAI-compatible voice server (off: the built-in voice, on this computer)</span></label>
      <div class="grid"><label for="vs-url">Address<input id="vs-url" placeholder="http://localhost:8880/v1" value="${esc(voiceServer.url)}"></label>
        <label for="vs-model">Model<input id="vs-model" value="${esc(voiceServer.model)}"></label>
        <label for="vs-voice">Voice (optional)<input id="vs-voice" value="${esc(voiceServer.voice)}"></label>
        <label for="vs-key">API key (optional)<input id="vs-key" type="password" autocomplete="new-password"></label></div>
      <select id="vs-voice-pick" class="hidden" aria-label="Voices your server lists"></select>
      <div id="vs-voice-note" class="muted"></div>
      <p class="muted">When this is on, the text of each part of your script is sent to the server you enter, and nothing else; Test and Hear it send it one sample sentence. To offer its voices as choices, KinoDraw also asks the server for its list of voice names when you press Test and, while this is on, each time Settings, New video or a Narrator tab opens, sending only the model name (and your key for this address, if any). Your own recordings stay on this computer. Your key is kept in your keychain for this address and sent only to it.
        <a href="https://edwardaiwang-svg.github.io/kinodraw/privacy.html" target="_blank">What is sent (privacy)</a></p>
      <div class="row"><button id="vs-save" class="small">Save</button><button id="vs-test" class="small">Test</button></div>
      <div id="vs-result" class="muted" role="status" aria-live="polite"></div></section>
    <section><h3>Projects folder</h3><div class="row"><input id="s-root" value="${esc(STATE.projects_root)}"><button id="s-save" class="small">Save</button></div></section>
    <section><h3>Voices</h3><p class="muted">${LANG_NAMES.en}: ${STATE.models_ready.en ? 'ready' : 'downloads on first use (~190 MB)'} · ${LANG_NAMES.zh}: ${STATE.models_ready.zh ? 'ready' : 'downloads on first use (~220 MB)'} · ${LANG_NAMES.es}: ${STATE.models_ready.es ? 'ready' : 'downloads on first use (~190 MB)'}</p></section></div>`);
  $('#c-email', body)?.addEventListener('input', (e) => { cloudEmail = e.target.value.trim(); });
  $('#c-send', body)?.addEventListener('click', async () => {
    $('#c-note', body).classList.add('hidden');
    try { await api('/api/cloud/signup', { method: 'POST', body: JSON.stringify({ email: $('#c-email', body).value }) });
      toast('Code sent. Check your email (and spam).'); $('#c-code', body).focus(); }
    catch (e) {
      if (e.code === 'email_unavailable') { $('#c-note', body).textContent = e.message; $('#c-note', body).classList.remove('hidden'); }   // stays until the next try
      else toast(e.message, 6000);
    }
  });
  $('#c-verify', body)?.addEventListener('click', async () => {
    if (!$('#c-email', body).value.trim()) {       // the code belongs to an address: ask for it, don't say "expired"
      toast('Type the email address the code was sent to.', 6000); $('#c-email', body).focus(); return;
    }
    try { const r = await api('/api/cloud/verify', { method: 'POST', body: JSON.stringify({ email: $('#c-email', body).value, code: $('#c-code', body).value }) });
      toast(r.remaining === null ? 'Signed in: unlimited videos (fair use)' : `Signed in: ${r.remaining} videos left this month`); await refreshState(); closeModal(); refreshDirectorMenus(); }
    catch (e) { toast(e.message, 6000); }
  });
  const serverFields = () => ({ url: $('#vs-url', body).value, model: $('#vs-model', body).value,
    voice: $('#vs-voice', body).value, ...($('#vs-key', body).value ? { key: $('#vs-key', body).value } : {}) });
  const serverBusy = (busy) => { $('#vs-save', body).disabled = busy; $('#vs-test', body).disabled = busy; };
  const keyHint = () => {                // a saved key belongs to one address: another address asks for its key again
    let same = false;
    try { same = new URL($('#vs-url', body).value.trim()).origin === new URL(STATE.voice_server.url).origin; } catch { same = false; }
    $('#vs-key', body).placeholder = STATE.voice_server.key_saved && same ? 'saved for this address'
      : STATE.voice_server.key_saved ? 'enter this address’s key' : 'Optional';
  };
  keyHint();
  $('#vs-url', body).oninput = keyHint;
  const voicePick = $('#vs-voice-pick', body), voiceNote = $('#vs-voice-note', body), voiceInput = $('#vs-voice', body);
  if (voiceServer.on && voiceServer.url && voiceServer.model) offerSavedVoices(voicePick, voiceNote, voiceInput);
  $('#vs-save', body).onclick = async () => {
    const result = $('#vs-result', body); serverBusy(true); result.textContent = 'Saving…';
    try {
      await api('/api/voice-server', { method: 'POST', body: JSON.stringify({ on: $('#vs-on', body).checked, ...serverFields() }) });
      await refreshState();
      savedVoices = null;                  // the address, model or key may have changed: ask the server again
      $('#vs-key', body).value = '';
      keyHint();
      result.textContent = 'Saved.';
      if (STATE.voice_server.on) offerSavedVoices(voicePick, voiceNote, voiceInput);
      if (current) loadNarrator(current);
      else { syncNewVoice(); if (STATE.voice_server.on && $('#server-voice-pick')) offerSavedVoices($('#server-voice-pick'), $('#server-voice-note'), $('#server-voice')); }
    } catch (e) { result.textContent = e.message; }
    finally { serverBusy(false); }
  };
  $('#vs-test', body).onclick = async () => {
    const result = $('#vs-result', body); serverBusy(true); result.textContent = 'Testing…';
    offerVoices(serverVoices(serverFields()), voicePick, voiceNote, voiceInput);   // its voices, even if this one fails
    try {
      const test = await api('/api/voice-server/test', { method: 'POST', body: JSON.stringify(serverFields()) });
      result.innerHTML = `<p>${esc(test.message)}</p><audio controls disableremoteplayback preload="none" src="/api/voice-server/test.wav?token=${encodeURIComponent(T)}&t=${Date.now()}"></audio>`;
    } catch (e) { result.textContent = e.message; }
    finally { serverBusy(false); }
  };
  $('#s-adv', body).onchange = async (e) => {
    try { await api('/api/settings', { method: 'POST', body: JSON.stringify({ advanced: e.target.checked }) });
      await refreshState(); refreshDirectorMenus(); closeModal(); showSettings(); }
    catch (err) { toast(err.message, 6000); }
  };
  if (STATE.advanced) {
    $('#k-prov', body).onchange = () => {
      const cmd = $('#k-prov', body).value === 'command';
      $('#k-key', body).type = cmd ? 'text' : 'password';
      $('#k-key', body).placeholder = cmd ? '/path/to/program --flags' : 'sk-…';
    };
    $('#k-save', body).onclick = async () => {
      try { await api('/api/keys', { method: 'POST', body: JSON.stringify({ provider: $('#k-prov', body).value, key: $('#k-key', body).value }) });
        toast('Key saved to the keychain'); await refreshState(); closeModal(); }
      catch (e) { toast(e.message, 6000); }
    };
  }
  $('#s-save', body).onclick = async () => {
    try { await api('/api/settings', { method: 'POST', body: JSON.stringify({ projects: $('#s-root', body).value }) });
      await refreshState(); closeModal(); loadProjects(); }
    catch (e) { toast(e.message, 6000); }
  };
}

async function refreshState() { STATE = await api('/api/state'); }

function refreshDirectorMenus() {          // after Settings changes, without clearing a script being typed
  for (const id of ['#director', '#p-director']) {
    const sel = $(id);
    if (sel) { sel.innerHTML = directorOptions(sel.value); sel.onchange?.(); }
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  $('#btn-new').onclick = showNew;
  $('#project-import').onchange = async (event) => {
    const input = event.target, file = input.files[0]; if (!file) return;
    input.disabled = true;
    try {
      if (dirty && current && !(await saveBoard())) return;
      const result = await api('/api/projects/import', { method: 'POST', body: file });
      await openProject(result.project);
      toast('Imported saved project.');
    } catch (error) { toast(error.message, 8000); }
    finally { input.disabled = false; input.value = ''; }
  };
  $('#btn-sample').onclick = showSample;
  $('#btn-settings').onclick = showSettings;
  $('#feedback').onclick = showFeedback;
  $('#modal .close').onclick = closeModal;
  $('#modal').onclick = (e) => { if (e.target.id === 'modal') closeModal(); };
  await refreshState();
  if (STATE.notice) toast(STATE.notice, 30000);      // Doodle Studio's projects could not be brought over yet
  const items = await api('/api/projects');
  if (items.length && !items[0].broken) openProject(items[0].name); else showSample();
});

$('#btn-trash').onclick = async () => {
  try {
    const items = await api('/api/projects?trash=1');
    const box = modal('<h2>Trash</h2>' + (items.map(x => `<p>${esc(x.title)} <button data-trash="${esc(x.name)}">Restore project</button></p>`).join('') || '<p>Trash is empty.</p>'));
    box.querySelectorAll('[data-trash]').forEach(button => button.onclick = async () => {
      try { const name = button.dataset.trash; const state = await api(`/api/projects/${encodeURIComponent(name)}`);
        await api(`/api/projects/${encodeURIComponent(name)}/untrash`, { method: 'POST', body: JSON.stringify({ revision: state.revision }) }); closeModal(); await openProject(name);
      } catch (e) { toast(e.message); }
    });
  } catch (e) { toast(e.message); }
};

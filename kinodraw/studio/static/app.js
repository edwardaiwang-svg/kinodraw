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
function needsCloudSignIn(director) {     // KinoDraw Cloud picked but nobody signed in: open the sign-in instead of failing
  if (director !== 'cloud' || STATE.cloud_signed_in) return false;
  toast('Sign in to KinoDraw Cloud first (free: 5 AI videos a month), or choose Offline.', 6000);
  showSettings();
  return true;
}
function wholeVideoOffline(res) {          // KinoDraw Cloud refused the video (quota, budget, network): say so plainly
  return res?.notes?.find((n) => n.startsWith('The offline director planned this video')) || null;
}
let STATE = null, current = null, board = null, dirty = false, cloudEmail = '';   // the sign-in address, kept between openings

async function api(path, opts = {}) {
  const type = opts.body instanceof Blob ? {} : { 'Content-Type': 'application/json' };   // a file goes up as it is
  const r = await fetch(path, { ...opts, headers: { 'X-Studio-Token': T, ...type, ...(opts.headers || {}) } });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.errors?.[0] || data.error || r.statusText);
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
    sampleAudio.onerror = () => toast('Could not play this sample.', 6000);
    await sampleAudio.play();
  } catch (e) { toast(e.message, 6000); } finally { button.disabled = false; button.textContent = label; }
}

const MAKE = ['storyboard', 'director', 'voice', 'timeline', 'render', 'finish'];
async function watch(job, title, order = MAKE, own = false) {     // own: narrated from the user's recording
  $('#prog-title').textContent = title; $('#prog-fill').style.width = '2%'; $('#progress').classList.remove('hidden');
  const STAGES = { storyboard: 'Reading the script', director: 'Planning the visuals', voice: 'Recording the narration',
    timeline: 'Timing captions and music', render: 'Drawing the video (the longest step)', finish: 'Adding music, captions and chapters',
    'download-search': 'Downloading the doodle search (first video only)', 'download-voice': 'Downloading the voice (first video only)',
    ...(own ? { voice: 'Getting ready to listen to your recording', align: 'Matching your recording to each sentence',
      timeline: 'Timing every drawing to your voice' } : {}) };
  const SLOT = { 'download-search': 'storyboard', 'download-voice': 'voice', align: 'voice' };   // these fill their step's share
  const MB = (n) => Math.round(n / 1e6);
  for (;;) {
    await new Promise((r) => setTimeout(r, 800));
    const j = await api(`/api/jobs/${job}`);
    const frac = j.total ? j.done / j.total : 0;
    const k = Math.max(0, order.includes(j.stage) ? order.indexOf(j.stage) : order.indexOf(SLOT[j.stage]));
    $('#prog-fill').style.width = `${Math.min(99, ((k + frac) / order.length) * 100)}%`;
    const count = j.stage.startsWith('download') ? ` · ${MB(j.done)} of ${MB(j.total)} MB (${Math.floor(frac * 100)}%)`
      : j.total > 1 ? ` · ${j.done}/${j.total}` : '';
    $('#prog-stage').textContent = `${STAGES[j.stage] || 'Starting'}${count}`;
    if (j.state === 'done' || j.state === 'failed') {
      $('#progress').classList.add('hidden');
      if (j.state === 'failed') throw new Error(j.error);
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
  current = null; loadProjects();
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

function showNew() {
  current = null; loadProjects();
  $('#main').replaceChildren($('#tpl-new').content.cloneNode(true));
  const langSel = $('#lang'), voiceSel = $('#voice'), dirSel = $('#director');
  const voiceLang = () => langSel.value || scriptLang($('#script').value);
  const fillVoices = () => {
    voiceSel.innerHTML = voiceOptions(voiceLang());
  };
  langSel.onchange = fillVoices; $('#script').oninput = () => { if (!langSel.value) fillVoices(); };
  fillVoices();
  $('#speed-wrap').innerHTML = speedRow('speed');
  bindSpeed('speed');
  $('#voice-play').onclick = (e) => playSample(voiceLang(), voiceSel.value, $('#speed').value, e.currentTarget);
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
      cloud: STATE.cloud ? `KinoDraw Cloud, ${esc(STATE.cloud.plan || 'free')} plan: ${STATE.cloud.remaining === null ? 'unlimited videos (fair use)' : `${STATE.cloud.remaining ?? '?'} videos left this month`}.` : STATE.cloud_signed_in ? 'KinoDraw Cloud: signed in.' : 'KinoDraw Cloud AI (GPT-6 Luna) plans each section: 5 free videos a month, no API key. You sign in with an email code first; Offline needs no account.',
      openai: STATE.keys.openai ? 'Uses your OpenAI key (about $0.02 per 15-minute video with GPT-6 Luna).' : 'Add your OpenAI key under Settings first.',
      anthropic: STATE.keys.anthropic ? 'Uses your Anthropic key (about $1 per 15-minute video with Opus).' : 'Add your Anthropic key under Settings first.',
      compat: 'Any OpenAI-compatible server (OpenRouter, Groq, a local Ollama…): set the base URL and model.',
      command: STATE.keys.command ? 'Runs your saved command once per section; the model name is passed along to it.' : 'Save your command under Settings first.',
    }[d];
  };
  dirSel.onchange = async () => {
    note();
    if (dirSel.value === 'cloud' && STATE.cloud_signed_in && !STATE.cloud) {
      try { STATE.cloud = await api('/api/cloud/me'); } catch (e) { STATE.cloud = null; }
      note();
    }
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
    } catch (err) { toast(err.message, 8000); } finally { e.target.value = ''; }
  };
  $('#style').innerHTML = STATE.styles.map((s) => `<option value="${esc(s.value)}">${esc(s.label)}</option>`).join('');
  $('#format').innerHTML = formatOptions('16:9');
  $('#style').onchange = () => {            // a promo names its product; the whiteboard ignores Motion
    const collage = $('#style').value === 'collage/promo';
    $('#brand').classList.toggle('hidden', !collage);
    $('#motion-wrap').classList.toggle('hidden', !collage);
  };
  $('#create').onclick = async () => {
    if (needsCloudSignIn(dirSel.value)) return;
    try {
      const [look, story] = $('#style').value.split('/');
      const brand = { name: $('#brand-name').value.trim(), url: $('#brand-url').value.trim(), cta: $('#brand-cta').value.trim() };
      const body = { text: $('#script').value, title: $('#title').value, lang: langSel.value, voice: voiceSel.value,
        speed: Number($('#speed').value),
        director: dirSel.value, model: $('#model').value, base_url: $('#base-url').value, look, story, aspect: $('#format').value,
        motion: look === 'collage' ? $('#motion').value : null, brand: story === 'promo' ? brand : null };
      const { job, project } = await api('/api/projects', { method: 'POST', body: JSON.stringify(body) });
      const res = await watch(job, 'Creating the storyboard');
      const whole = wholeVideoOffline(res);
      if (whole) toast(whole, 8000);
      else if (res?.notes?.length) toast(`${res.notes.length} AI suggestions were replaced by the offline plan`);
      await openProject(project, ownVoice() ? 'narrator' : null);
    } catch (e) { $('#progress').classList.add('hidden'); toast(e.message, 6000); }
  };
}

// ---------------------------------------------------------------- project
function formatOptions(selected) {
  return STATE.formats.map((f) => `<option value="${esc(f.value)}"${f.value === selected ? ' selected' : ''}>${esc(f.label)}</option>`).join('');
}

async function openProject(name, tab = null) {
  current = name; dirty = false; loadProjects();
  const p = await api(`/api/projects/${encodeURIComponent(name)}`);
  board = p.storyboard;
  $('#main').replaceChildren($('#tpl-project').content.cloneNode(true));
  $('#p-title').textContent = p.title;
  $('#p-meta').textContent = `${board.beats.length} beats · ${LANG_NAMES[p.lang]}${p.settings.aspect === '9:16' ? ' · vertical 9:16' : ''} · ${p.settings.recording ? 'narrated in your own voice' : `voice ${voiceName(p.settings.voice)}`}`;
  $('#p-format').innerHTML = formatOptions(p.settings.aspect || '16:9');
  $('#p-format').onchange = async () => {
    try {
      const cfg = await api(`/api/projects/${encodeURIComponent(name)}/format`, { method: 'POST', body: JSON.stringify({ aspect: $('#p-format').value }) });
      p.settings.aspect = cfg.aspect;
      const meta = $('#p-meta');
      meta.textContent = meta.textContent.replace(' · vertical 9:16', '');
      if (cfg.aspect === '9:16') {
        const last = meta.textContent.lastIndexOf(' · ');
        meta.textContent = `${meta.textContent.slice(0, last)} · vertical 9:16${meta.textContent.slice(last)}`;
      }
      toast('Format saved. Make video to render it.');
    } catch (e) { $('#p-format').value = p.settings.aspect || '16:9'; toast(e.message, 6000); }
  };
  $('#p-director').innerHTML = directorOptions(p.settings.director || 'rules');
  $('#p-redirect').onclick = async () => {
    if (needsCloudSignIn($('#p-director').value)) return;
    if (dirty && !confirm('Re-planning replaces your unsaved edits. Continue?')) return;
    try {
      const res = await watch((await api(`/api/projects/${encodeURIComponent(name)}/direct`, { method: 'POST', body: JSON.stringify({ director: $('#p-director').value }) })).job, 'Planning the visuals');
      const whole = wholeVideoOffline(res);
      if (whole) toast(whole, 8000);
      else toast(res?.cost ? `Done · AI cost $${res.cost.toFixed(4)}` : 'Visuals re-planned');
      openProject(name);
    } catch (e) { toast(e.message, 6000); }
  };
  $('#p-reveal').onclick = () => api(`/api/projects/${encodeURIComponent(name)}/reveal`, { method: 'POST' });
  $('#p-make').onclick = () => makeVideo(name);
  $('#p-save').onclick = saveBoard;
  document.querySelectorAll('.tabs button').forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  renderBoard();
  renderVideo(p);
  loadNarrator(name, tab === 'narrator' ? 'own' : undefined);     // opened from New video with My own voice chosen
  if (tab || p.videos?.length) showTab(tab || 'video');
}

function showTab(tab) {
  document.querySelectorAll('.tabs button').forEach((x) => x.classList.toggle('on', x.dataset.tab === tab));
  for (const t of ['board', 'narrator', 'video']) $(`#tab-${t}`).classList.toggle('hidden', t !== tab);
}

function markDirty() { dirty = true; $('#p-save').disabled = false; $('#dirty').textContent = 'Unsaved changes'; }

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
  const project = current, sent = board, main = $('#main');
  main.inert = true;                                  // no edits while the move saves: the reply replaces the board
  try {
    const res = await api(`/api/projects/${encodeURIComponent(project)}/reorder`, {
      method: 'POST', body: JSON.stringify({ storyboard: sent, beat, visual, to, item })
    });
    if (current !== project || board !== sent) return; // another project (or a fresh copy) was opened meanwhile
    if (!res.ok) { toast('Not moved: ' + res.errors[0]); return; }
    board = res.storyboard;
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
  const project = current;
  const body = modal(`<h3>Choose a doodle</h3><label class="file">Upload a picture<input id="picture-file" type="file" accept=".png,.jpg,.jpeg,.svg,image/png,image/jpeg,image/svg+xml"></label><p class="picture-hint">PNG, JPG or SVG, up to 10 MB. It stays on your computer.</p><div id="own-pictures" class="hidden"><h4>Your pictures</h4><div class="pick-grid" id="own-picks"></div></div><input id="q" value="${esc(query)}" placeholder="Search: rocket, 地球, idea…"><div class="pick-grid" id="picks"></div>`);
  $('#picture-file', body).onchange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error(`“${file.name}” is too big (over 10 MB). Make it smaller and try again.`);
      const res = await api(`/api/projects/${encodeURIComponent(project)}/pictures?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file });
      closeModal(); onPick(res.id);
    } catch (e) { toast(e.message, 6000); }
    event.target.value = '';
  };
  api(`/api/projects/${encodeURIComponent(project)}/pictures`).then((items) => {
    if (!items.length) return;
    $('#own-pictures', body).classList.remove('hidden');
    $('#own-picks', body).innerHTML = items.map((d) => `<div class="pick" data-id="${esc(d.id)}"><img src="${doodleSrc(d.id)}"><div>${esc(d.name)}</div></div>`).join('');
    $('#own-picks', body).querySelectorAll('.pick').forEach((p) => (p.onclick = () => { closeModal(); onPick(p.dataset.id); }));
  }).catch((e) => toast(e.message, 6000));
  const run = async () => {
    const items = await api(`/api/doodles?q=${encodeURIComponent($('#q', body).value)}&lang=${board.lang}`);
    $('#picks', body).innerHTML = items.map((d) => `<div class="pick" data-id="${esc(d.id)}"><img src="${doodleSrc(d.id)}"><div>${esc((d.desc || d.id).slice(0, 40))}</div></div>`).join('');
    body.querySelectorAll('.pick').forEach((p) => (p.onclick = () => { closeModal(); onPick(p.dataset.id); }));
  };
  let timer;
  $('#q', body).oninput = () => { clearTimeout(timer); timer = setTimeout(run, 250); };
  run();
}

async function saveBoard() {
  try {
    const res = await api(`/api/projects/${encodeURIComponent(current)}/storyboard`, { method: 'PUT', body: JSON.stringify(board) });
    if (!res.ok) { toast(`Not saved: ${res.errors[0]}`, 7000); return false; }
    dirty = false; $('#p-save').disabled = true; $('#dirty').textContent = 'Saved';
    loadNarrator(current, document.querySelector('input[name="n-pick"]:checked')?.value);   // an edited takeaway is read aloud
    return true;
  } catch (e) { toast(e.message, 6000); return false; }
}

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
    const res = await watch((await api(`/api/projects/${encodeURIComponent(name)}/make`, { method: 'POST' })).job, 'Making your video', MAKE, own);
    toast(res.ok ? `Video ready (${res.length})` : `Video made, with warnings: ${res.problems[0]}`, 6000);
    await openProject(name);
    document.querySelector('.tabs button[data-tab="video"]').click();
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
  box.innerHTML = `<video controls preload="metadata" poster="${fileSrc(`${stem}-thumbnail.png`)}" src="${fileSrc(video)}"></video>${qa}
    <div class="files">${files.map(([f, l]) => `<a href="${fileSrc(f)}" target="_blank">${l}</a>`).join('')}</div>
    <p class="muted">The files are in your project folder (Open folder). Music: FreePD (CC0). ${p.settings.recording ? 'Narration: your own voice.' : 'Narration: Kokoro AI voice.'}</p>`;
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
  const pick = `<div class="narrator-pick">
    <span class="pick-label">Narrator</span>
    <label class="seg"><input type="radio" name="n-pick" value="builtin"${own ? '' : ' checked'}><b>Built-in voice</b>
      <small>A natural AI voice (${esc(voiceName(info.voice))}) reads your script</small></label>
    <label class="seg"><input type="radio" name="n-pick" value="own"${own ? ' checked' : ''}><b>My own voice</b>
      <small>You read the script aloud; every drawing follows your voice</small></label></div>`;
  if (!own) {
    box.innerHTML = `${pick}<form id="n-voice-form">
      <div class="grid"><div><label for="n-voice">Voice</label><div class="row">
        <select id="n-voice">${voiceOptions(info.lang, info.voice)}</select>
        <button id="n-play" type="button" class="ghost" aria-label="Play a sample of this voice">▶ Hear it</button>
      </div></div><div>${speedRow('n-speed')}</div></div>
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
      ${info.take ? `<audio controls preload="none" src="${fileSrc(info.take)}"></audio>` : ''}
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
        const next = await api(`/api/projects/${encodeURIComponent(name)}/narrator`, { method: 'POST', body: JSON.stringify({ narrator: r.value }) });
        toast(r.value === 'own' ? 'Your video will be narrated in your own voice' : 'Your video will use the built-in voice');
        renderNarrator(name, next);
        $('#p-meta').textContent = $('#p-meta').textContent.replace(/[^·]*$/, ` ${r.value === 'own' ? 'narrated in your own voice' : `voice ${voiceName(next.voice)}`}`);
      } else renderNarrator(name, info, r.value);
    } catch (e) { toast(e.message, 6000); }
  }));
  if (!own) {
    const form = $('#n-voice-form', box), select = $('#n-voice', form), slider = $('#n-speed', form);
    const pronounce = $('#n-pronounce', form), save = $('#n-save', form);
    bindSpeed('n-speed');
    $('#n-play', form).onclick = (e) => playSample(info.lang, select.value, slider.value, e.currentTarget);
    api(`/api/projects/${encodeURIComponent(name)}/voice`).then((settings) => {
      if (!form.isConnected) return;
      select.value = settings.voice; slider.value = settings.speed; slider.oninput();
      pronounce.value = settings.pronounce; save.disabled = false;
    }).catch((e) => toast(e.message, 6000));
    form.onsubmit = async (e) => {
      e.preventDefault(); save.disabled = true;
      try {
        const settings = await api(`/api/projects/${encodeURIComponent(name)}/voice`, { method: 'PUT',
          body: JSON.stringify({ voice: select.value, speed: Number(slider.value), pronounce: pronounce.value }) });
        info.voice = settings.voice;
        renderNarrator(name, info);
        $('#p-meta').textContent = $('#p-meta').textContent.replace(/[^·]*$/, ` voice ${voiceName(settings.voice)}`);
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
      renderNarrator(name, await api(`/api/projects/${encodeURIComponent(name)}/recording?filename=${encodeURIComponent(f.name)}`, { method: 'POST', body: f }));
      $('#p-meta').textContent = $('#p-meta').textContent.replace(/[^·]*$/, ' narrated in your own voice');
    } catch (err) {
      $('#n-take', box).textContent = info.take ? `Your recording: ${info.take}` : 'No recording yet';
      showProblem(err.message);
    } finally { e.target.value = ''; }
  };
  $('#n-use', box).onclick = async () => {
    try {
      const job = (await api(`/api/projects/${encodeURIComponent(name)}/align`, { method: 'POST' })).job;
      renderNarrator(name, await watch(job, 'Listening to your recording', ['voice', 'align', 'timeline'], true));
    } catch (e) { $('#progress').classList.add('hidden'); showProblem(e.message); }
  };
  $('#n-make', box)?.addEventListener('click', () => makeVideo(name, true));
}

// ---------------------------------------------------------------- settings
function showSettings() {
  const cloud = STATE.cloud_available ? `<section><h3>KinoDraw Cloud</h3>
      <p class="muted">${STATE.cloud ? `Signed in · ${esc(STATE.cloud.plan)} plan · ${STATE.cloud.remaining === null ? 'unlimited videos (fair use)' : `${esc(STATE.cloud.remaining)} videos left this month`}` : STATE.cloud_signed_in ? 'Signed in.' : '5 free AI-directed videos a month. No API key needed.'}
        <a href="https://edwardaiwang-svg.github.io/kinodraw/privacy.html" target="_blank">What is sent (privacy)</a></p>
      <div class="row"><input id="c-email" placeholder="you@example.com" value="${esc(cloudEmail)}"><button id="c-send" class="small">Email me a code</button></div>
      <div class="row" style="margin-top:6px"><input id="c-code" placeholder="6-digit code"><button id="c-verify" class="small">Sign in</button></div></section>` : '';
  const body = modal(`<div class="settings"><h2>Settings</h2>${cloud}
    <section><h3>Advanced directors</h3><label class="row"><input id="s-adv" type="checkbox" style="width:auto"${STATE.advanced ? ' checked' : ''}>
      <span>Show directors that use your own API key or program (billed by that provider, not by KinoDraw Cloud)</span></label>
      ${STATE.advanced ? `<p class="muted">Stored in your system keychain, never in project files. A command gets each request as JSON on stdin and prints the plan as JSON.</p>
      <div class="row"><select id="k-prov" style="width:auto"><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="compat">OpenAI-compatible</option><option value="command">Command</option></select>
      <input id="k-key" type="password" placeholder="sk-…"><button id="k-save" class="small">Save</button></div>
      <p class="muted">Saved: ${esc(Object.entries(STATE.keys).filter(([, v]) => v).map(([k]) => k).join(', ') || 'none')}</p>` : ''}</section>
    <section><h3>Videos</h3><label class="row"><input id="s-credit" type="checkbox" style="width:auto"${STATE.credit ? ' checked' : ''}>
      <span>End each video with a 2-second "Made with ${esc(STATE.product)}" credit</span></label></section>
    <section><h3>Projects folder</h3><div class="row"><input id="s-root" value="${esc(STATE.projects_root)}"><button id="s-save" class="small">Save</button></div></section>
    <section><h3>Voices</h3><p class="muted">${LANG_NAMES.en}: ${STATE.models_ready.en ? 'ready' : 'downloads on first use (~190 MB)'} · ${LANG_NAMES.zh}: ${STATE.models_ready.zh ? 'ready' : 'downloads on first use (~220 MB)'} · ${LANG_NAMES.es}: ${STATE.models_ready.es ? 'ready' : 'downloads on first use (~190 MB)'}</p></section></div>`);
  $('#c-email', body)?.addEventListener('input', (e) => { cloudEmail = e.target.value.trim(); });
  $('#c-send', body)?.addEventListener('click', async () => {
    try { await api('/api/cloud/signup', { method: 'POST', body: JSON.stringify({ email: $('#c-email', body).value }) });
      toast('Code sent. Check your email (and spam).'); $('#c-code', body).focus(); }
    catch (e) { toast(e.message, 6000); }
  });
  $('#c-verify', body)?.addEventListener('click', async () => {
    if (!$('#c-email', body).value.trim()) {       // the code belongs to an address: ask for it, don't say "expired"
      toast('Type the email address the code was sent to.', 6000); $('#c-email', body).focus(); return;
    }
    try { const r = await api('/api/cloud/verify', { method: 'POST', body: JSON.stringify({ email: $('#c-email', body).value, code: $('#c-code', body).value }) });
      toast(r.remaining === null ? 'Signed in: unlimited videos (fair use)' : `Signed in: ${r.remaining} videos left this month`); await refreshState(); closeModal(); refreshDirectorMenus(); }
    catch (e) { toast(e.message, 6000); }
  });
  $('#s-credit', body).onchange = async (e) => {
    try { await api('/api/settings', { method: 'POST', body: JSON.stringify({ credit: e.target.checked }) }); await refreshState(); }
    catch (err) { toast(err.message, 6000); }
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
  $('#btn-sample').onclick = showSample;
  $('#btn-settings').onclick = showSettings;
  $('#modal .close').onclick = closeModal;
  $('#modal').onclick = (e) => { if (e.target.id === 'modal') closeModal(); };
  await refreshState();
  if (STATE.notice) toast(STATE.notice, 30000);      // Doodle Studio's projects could not be brought over yet
  const items = await api('/api/projects');
  if (items.length && !items[0].broken) openProject(items[0].name); else showSample();
});

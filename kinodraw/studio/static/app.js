// KinoDraw front end: plain JavaScript talking to the local server (see studio/server.py).
const T = window.STUDIO_TOKEN;
const $ = (sel, root = document) => root.querySelector(sel);
const COLORS = { orange: '#f57c00', blue: '#1e6fd9', green: '#2e9d4f', purple: '#8e24aa', red: '#d32f2f', teal: '#00897b' };
const CYCLE = Object.keys(COLORS);
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
  const r = await fetch(path, { ...opts, headers: { 'X-Studio-Token': T, 'Content-Type': 'application/json', ...(opts.headers || {}) } });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
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

async function watch(job, title) {
  $('#prog-title').textContent = title; $('#prog-fill').style.width = '2%'; $('#progress').classList.remove('hidden');
  const STAGES = { storyboard: 'Reading the script', director: 'Planning the visuals', voice: 'Recording the narration',
    timeline: 'Timing captions and music', render: 'Drawing the video (the longest step)', finish: 'Adding music, captions and chapters',
    'download-search': 'Downloading the doodle search (first video only)', 'download-voice': 'Downloading the voice (first video only)' };
  const SLOT = { 'download-search': 'storyboard', 'download-voice': 'voice' };   // first-run downloads fill their step's share
  const MB = (n) => Math.round(n / 1e6);
  for (;;) {
    await new Promise((r) => setTimeout(r, 800));
    const j = await api(`/api/jobs/${job}`);
    const frac = j.total ? j.done / j.total : 0;
    const order = ['storyboard', 'director', 'voice', 'timeline', 'render', 'finish'];
    const k = Math.max(0, order.indexOf(SLOT[j.stage] || j.stage));
    $('#prog-fill').style.width = `${Math.min(99, ((k + frac) / order.length) * 100)}%`;
    const count = j.stage in SLOT ? ` · ${MB(j.done)} of ${MB(j.total)} MB (${Math.floor(frac * 100)}%)`
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
    ${esc(p.title)}<small>${p.broken ? 'incomplete' : `${p.lang === 'zh' ? '中文' : 'English'} · ${p.videos?.length ? '🎬 ready' : 'storyboard'}`}</small></a>`).join('')
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
function showNew() {
  current = null; loadProjects();
  $('#main').replaceChildren($('#tpl-new').content.cloneNode(true));
  const langSel = $('#lang'), voiceSel = $('#voice'), dirSel = $('#director');
  const fillVoices = () => {
    const lang = langSel.value || (/[一-鿿]/.test($('#script').value) ? 'zh' : 'en');
    voiceSel.innerHTML = STATE.voices[lang].map((v) => `<option>${esc(v)}</option>`).join('');
  };
  langSel.onchange = fillVoices; $('#script').oninput = () => { if (!langSel.value) fillVoices(); };
  fillVoices();
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
  $('#create').onclick = async () => {
    if (needsCloudSignIn(dirSel.value)) return;
    try {
      const body = { text: $('#script').value, title: $('#title').value, lang: langSel.value, voice: voiceSel.value,
        director: dirSel.value, model: $('#model').value, base_url: $('#base-url').value };
      const { job, project } = await api('/api/projects', { method: 'POST', body: JSON.stringify(body) });
      const res = await watch(job, 'Creating the storyboard');
      const whole = wholeVideoOffline(res);
      if (whole) toast(whole, 8000);
      else if (res?.notes?.length) toast(`${res.notes.length} AI suggestions were replaced by the offline plan`);
      await openProject(project);
    } catch (e) { $('#progress').classList.add('hidden'); toast(e.message, 6000); }
  };
}

// ---------------------------------------------------------------- project
async function openProject(name) {
  current = name; dirty = false; loadProjects();
  const p = await api(`/api/projects/${encodeURIComponent(name)}`);
  board = p.storyboard;
  $('#main').replaceChildren($('#tpl-project').content.cloneNode(true));
  $('#p-title').textContent = p.title;
  $('#p-meta').textContent = `${board.beats.length} beats · ${p.lang === 'zh' ? '中文' : 'English'} · voice ${p.settings.voice}`;
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
  document.querySelectorAll('.tabs button').forEach((b) => (b.onclick = () => {
    document.querySelectorAll('.tabs button').forEach((x) => x.classList.toggle('on', x === b));
    $('#tab-board').classList.toggle('hidden', b.dataset.tab !== 'board');
    $('#tab-video').classList.toggle('hidden', b.dataset.tab !== 'video');
  }));
  renderBoard();
  renderVideo(p);
  if (p.videos?.length) document.querySelector('.tabs button[data-tab="video"]').click();
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
  el.querySelector('.prev').onclick = () => {
    const img = document.createElement('img');
    img.alt = 'preview';
    img.src = `/api/projects/${encodeURIComponent(current)}/still?beat=${encodeURIComponent(b.id)}&offset=4&token=${T}`;
    el.querySelector('.preview').replaceChildren(img);
  };
  return el;
}

function visualCard(b, v, i) {
  const lang = board.lang;
  const el = document.createElement('div');
  el.className = 'vis';
  const typeName = { cluster: 'doodles', stat: 'number', quote: 'quote', glossary: 'sticky note', lanes: 'timeline', grid100: '100 squares', bars: 'bar chart', flow: 'flow', split: 'comparison' }[v.type] || v.type;
  el.innerHTML = `<div class="type">${esc(typeName)}${v.size === 'margin' ? ' · beside the note' : ''}</div><button class="del" title="Remove">×</button>`;
  if (v.type === 'cluster') {
    const items = document.createElement('div');
    items.className = 'items';
    v.items.forEach((it) => {
      const d = document.createElement('div');
      d.className = 'item';
      d.innerHTML = `<img src="${doodleSrc(it.doodle)}" title="${esc(it.doodle)} — click to swap"><input value="${esc(it.label?.[lang] || '')}" placeholder="label">`;
      d.querySelector('img').onclick = () => pickDoodle(it.label?.[lang] || b.display[lang].slice(0, 40), (id) => { it.doodle = id; markDirty(); renderBoard(); });
      d.querySelector('input').oninput = (e) => { it.label = e.target.value ? { [lang]: e.target.value } : undefined; if (!it.label) delete it.label; markDirty(); };
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
  const body = modal(`<h3>Choose a doodle</h3><input id="q" value="${esc(query)}" placeholder="Search: rocket, 地球, idea…"><div class="pick-grid" id="picks"></div>`);
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
    dirty = false; $('#p-save').disabled = true; $('#dirty').textContent = 'Saved'; return true;
  } catch (e) { toast(e.message, 6000); return false; }
}

async function makeVideo(name) {
  if (dirty && !(await saveBoard())) return;
  try {
    const res = await watch((await api(`/api/projects/${encodeURIComponent(name)}/make`, { method: 'POST' })).job, 'Making your video');
    toast(res.ok ? `Video ready (${res.length})` : `Video made, with warnings: ${res.problems[0]}`, 6000);
    await openProject(name);
    document.querySelector('.tabs button[data-tab="video"]').click();
  } catch (e) { $('#progress').classList.add('hidden'); toast(e.message, 8000); }
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
    <p class="muted">The files are in your project folder (Open folder). Music: FreePD (CC0). Narration: Kokoro AI voice.</p>`;
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
    <section><h3>Voices</h3><p class="muted">English: ${STATE.models_ready.en ? 'ready' : 'downloads on first use (~190 MB)'} · 中文: ${STATE.models_ready.zh ? 'ready' : 'downloads on first use (~220 MB)'}</p></section></div>`);
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

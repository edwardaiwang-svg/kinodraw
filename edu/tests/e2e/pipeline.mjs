// The whole teacher flow in the real extension (headless Chromium), with Google and KinoDraw Cloud mocked:
// studio tab → signed in (dev token) → teacher check → script → GPT-6 Luna (mock) → voice → drawing → MP4 →
// Drive resumable upload (mock) → Classroom material (mock). Verifies the MP4 with ffprobe and the requests sent.
//   node tests/e2e/pipeline.mjs [fixture=water_cycle] [--draft] [--no-cloud] [--720p] [--shots]
// --shots saves the studio's screens at the Chrome Web Store's screenshot size to tests/out/store/.
import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const EDU = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const OUT = join(EDU, 'tests', 'out');
const ID = 'hoddalijnehhimlamfchabikgmjfgeoe';
const fixture = process.argv.slice(2).find((a) => !a.startsWith('--')) || 'water_cycle';
const draft = process.argv.includes('--draft');
const noCloud = process.argv.includes('--no-cloud');
const quality = process.argv.includes('--720p') ? '720p' : '1080p';
const shots = process.argv.includes('--shots') ? join(OUT, 'store') : null;
const script = readFileSync(join(EDU, '..', 'tests', 'fixtures', `${fixture}.md`), 'utf8');

// A throwaway copy of the extension with CONFIG.dev on (it only enables the test sign-in token).
const ext = join(OUT, 'ext-dev');
rmSync(ext, { recursive: true, force: true });
cpSync(join(EDU, 'extension'), ext, { recursive: true });
const config = join(ext, 'config.js');
writeFileSync(config, readFileSync(config, 'utf8').replace('dev: false', 'dev: true'));

const COURSE = { id: '123456789', name: 'Room 12 Science', section: '3rd grade', courseState: 'ACTIVE',
  alternateLink: 'https://classroom.google.com/c/MTIzNDU2Nzg5' };
const seen = { luna: [], sessions: 0, uploadInit: null, chunks: [], material: null, bytes: [] };

// The same profile as media.mjs, so the downloaded voice models (326 MB) are shared.
const context = await chromium.launchPersistentContext(join(OUT, 'media-profile'), {
  headless: true, channel: 'chromium', viewport: { width: 1280, height: 800 },
  args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`],
});
const json = (route, body, status = 200, headers = {}) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body), headers });
try {
  await context.route('https://classroom.google.com/**', (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<html><body>Classroom (test)</body></html>' }));
  await context.route('https://classroom.googleapis.com/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/v1/courses') return json(route, { courses: [COURSE] });
    if (url.pathname === `/v1/courses/${COURSE.id}/courseWorkMaterials` && route.request().method() === 'POST') {
      seen.material = route.request().postDataJSON();
      return json(route, { id: 'm1', ...seen.material, alternateLink: seen.material.state === 'PUBLISHED' ? `${COURSE.alternateLink}/m/bTE/details` : undefined });
    }
    return json(route, { error: { message: `unexpected ${url.pathname}` } }, 404);
  });
  await context.route('https://www.googleapis.com/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.pathname.startsWith('/oauth2/') || url.pathname.includes('userinfo')) return json(route, { email: 'teacher@school.test', email_verified: true });
    if (url.pathname === '/upload/drive/v3/files' && req.method() === 'POST') {
      seen.uploadInit = { headers: req.headers(), body: req.postDataJSON() };
      return route.fulfill({ status: 200, headers: { Location: 'https://www.googleapis.com/upload/drive/v3/files?upload_id=u1' }, body: '' });
    }
    if (url.pathname === '/upload/drive/v3/files' && req.method() === 'PUT') {
      const range = req.headers()['content-range'];
      const body = req.postDataBuffer();
      seen.chunks.push({ range, size: body ? body.length : 0 });
      if (body) seen.bytes.push(body);
      const [, a, b, total] = /bytes (\d+)-(\d+)\/(\d+)/.exec(range) || [];
      if (b && Number(b) + 1 < Number(total)) return route.fulfill({ status: 308, headers: { Range: `bytes=0-${b}` }, body: '' });
      return json(route, { id: 'drive-file-1', name: seen.uploadInit?.body?.name, webViewLink: 'https://drive.google.com/file/d/drive-file-1/view' });
    }
    return json(route, { error: { message: `unexpected ${url.pathname}` } }, 404);
  });
  await context.route('https://api.doodlecloud.org/**', async (route) => {
    const url = new URL(route.request().url());
    if (noCloud) return json(route, { error: 'not deployed' }, 503);
    if (url.pathname === '/v1/edu/session') { seen.sessions += 1; return json(route, { token: 'cloud-token', plan: 'edu', remaining: 29 }); }
    if (url.pathname === '/v1/videos') return json(route, { video_id: 'v1', model: 'gpt-6-luna', plan: 'edu', remaining: 28 });
    if (url.pathname === '/v1/direct') {
      const { section } = route.request().postDataJSON();
      seen.luna.push(section);
      // A plausible Luna answer: keep the rules draft, but give the first beat a cluster of its first candidate.
      const b0 = section.beats.find((b) => b.kind === 'narration' && b.candidates.length);
      const words = b0 ? b0.text.split(/\s+/).slice(0, 2).join(' ') : '';
      return json(route, { section: { section_title: '', hook: '', takeaway: '', beats: b0 ? [{ beat_id: b0.beat_id,
        visuals: [{ type: 'cluster', relation: 'none', items: [{ doodle: b0.candidates[0].id, label: '', trigger: words }] }] }] : [] },
      usage: { model: 'gpt-6-luna', input_tokens: 1000, output_tokens: 200, cached_tokens: 0 } });
    }
    return json(route, { error: 'not found' }, 404);
  });

  const [worker] = context.serviceWorkers().length ? context.serviceWorkers() : [await context.waitForEvent('serviceworker')];
  await worker.evaluate(() => chrome.storage.session.set({ devToken: { token: 'google-token', email: 'teacher@school.test', expiresAt: Date.now() + 3600_000 } }));

  const page = await context.newPage();
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) console.log(`console.${m.type()}:`, m.text().slice(0, 300)); });
  page.on('pageerror', (e) => console.log('pageerror:', e.message));
  await page.goto(`chrome-extension://${ID}/studio/studio.html?course=MTIzNDU2Nzg5&email=teacher%40school.test`);
  await page.waitForSelector('#view-make:not([hidden])', { timeout: 60_000 });
  const chosen = await page.$eval('#course', (s) => s.selectedOptions[0]?.textContent);
  console.log('class chosen from the URL:', chosen);
  await page.fill('#script', script);
  if (draft) await page.check('input[name=state][value=DRAFT]');
  if (quality === '720p') await page.check('input[name=quality][value="720p"]');
  if (shots) {
    mkdirSync(shots, { recursive: true });
    await page.evaluate(() => { document.getElementById('script').scrollTop = 0; window.scrollTo(0, 0); });
    await page.screenshot({ path: join(shots, 'studio-make.png') });
    const welcome = await context.newPage();
    await welcome.goto(`chrome-extension://${ID}/welcome/welcome.html`);
    await welcome.screenshot({ path: join(shots, 'welcome.png') });
    await welcome.close();
  }
  const t0 = Date.now();
  await page.click('#make');
  let last = '';
  for (;;) {
    const state = await page.evaluate(() => ({
      done: !document.getElementById('view-done').hidden, error: !document.getElementById('view-error').hidden ? document.getElementById('error-text').textContent : null,
      stage: [...document.querySelectorAll('#stages li.active')].map((li) => li.textContent).join(''),
    }));
    if (state.error) throw new Error(`the studio showed an error: ${state.error}`);
    if (state.done) break;
    if (state.stage !== last) { console.log(`${Math.round((Date.now() - t0) / 1000)}s  ${state.stage}`); last = state.stage; }
    if (shots && /Drawing the video\s*[4-9]\d%/.test(state.stage) && !existsSync(join(shots, 'studio-progress.png'))) {
      await page.screenshot({ path: join(shots, 'studio-progress.png') });
    }
    if (Date.now() - t0 > 60 * 60_000) throw new Error('timed out');
    await page.waitForTimeout(3000);
  }
  const minutes = ((Date.now() - t0) / 60000).toFixed(1);
  const doneText = await page.$eval('#view-done', (el) => el.innerText);
  if (shots) {
    await page.$eval('#preview', (v) => new Promise((resolve) => { v.onseeked = resolve; v.currentTime = 40; }));
    await page.screenshot({ path: join(shots, 'studio-done.png') });
  }
  mkdirSync(OUT, { recursive: true });
  const mp4 = join(OUT, `pipeline-${fixture}.mp4`);
  writeFileSync(mp4, Buffer.concat(seen.bytes));
  const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name,width,height,sample_rate,channels,r_frame_rate:format=duration',
    '-of', 'json', mp4]).toString());
  const report = { minutes, doneText, probe, lunaSections: seen.luna.length, sessions: seen.sessions,
    upload: { init: seen.uploadInit?.body, chunks: seen.chunks.length, sizes: seen.chunks.map((c) => c.size) }, material: seen.material };
  console.log(JSON.stringify(report, null, 1));
  const v = probe.streams.find((s) => s.codec_name === 'h264');
  const a = probe.streams.find((s) => ['aac', 'opus'].includes(s.codec_name));
  const problems = [];
  if (!v || v.width !== (quality === '720p' ? 1280 : 1920)) problems.push('video stream');
  if (!a || Number(a.sample_rate) !== 48000) problems.push('audio stream');
  if (Number(probe.format.duration) < 60) problems.push('too short');
  if (!seen.material || seen.material.materials?.[0]?.driveFile?.driveFile?.id !== 'drive-file-1' || seen.material.materials[0].driveFile.shareMode !== 'VIEW') problems.push('material');
  if (seen.material?.state !== (draft ? 'DRAFT' : 'PUBLISHED')) problems.push('material state');
  if (!noCloud && !seen.luna.length) problems.push('no Luna calls');
  if (seen.chunks.slice(0, -1).some((c) => c.size % 262144)) problems.push('chunk size');
  if (problems.length) throw new Error(`problems: ${problems.join(', ')}`);
  console.log('PASS');
} finally {
  await context.close();
}

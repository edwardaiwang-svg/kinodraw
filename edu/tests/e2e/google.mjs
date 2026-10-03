// End-to-end checks of the Classroom side of KinoDraw for Classroom: the real extension in Playwright's
// Chromium (headless), with every Google and KinoDraw Cloud address answered by the stand-ins in
// google-fakes.mjs. Nothing can reach the internet: the browser's DNS answers "not found" for every name.
//   cd edu && node tools/build.mjs && node tests/e2e/google.mjs
import { chromium } from 'playwright';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CODE, fakes, ID, OTHER_CODE, ROOM12 } from './google-fakes.mjs';

const EDU = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const OUT = join(EDU, 'tests', 'out');
const EXT = join(OUT, 'ext-google');   // its own copy: other e2e runs (tests/out/ext-dev) may be going at the same time
const STUDIO = `chrome-extension://${ID}/studio/studio.html`;
const BUTTON = 'Make a doodle video';
const CHIP = 'KinoDraw · Sign in';
const HOUR = 3_600_000;
let failures = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  ${detail}`}`);
  if (!ok) failures++;
};

// A throwaway copy of the extension with CONFIG.dev on, so auth.getToken() returns
// chrome.storage.session.devToken instead of signing in with Google.
rmSync(EXT, { recursive: true, force: true });
cpSync(join(EDU, 'extension'), EXT, { recursive: true });
const config = readFileSync(join(EXT, 'config.js'), 'utf8');
if (!config.includes('dev: false')) throw new Error('extension/config.js no longer says "dev: false"');
writeFileSync(join(EXT, 'config.js'), config.replace('dev: false', 'dev: true'));
// The real studio page downloads AI models; these checks only need a live extension tab at its address.
writeFileSync(join(EXT, 'studio', 'studio.html'), '<!doctype html><title>Studio stand-in</title><p>KinoDraw</p>');

const fake = fakes();
const context = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), 'doodle-classroom-')), {
  channel: 'chromium',   // Playwright's own Chromium in new headless mode (its default headless shell can't load extensions)
  headless: true,
  viewport: { width: 1280, height: 800 },
  args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`, '--host-resolver-rules=MAP * ~NOTFOUND'],
});
await context.route(/^https?:\/\//, fake.handle);   // web addresses only: the extension's own files load as usual

const cdp = new Map();
/** The page's buttons as Chrome's accessibility tree has them. It sees into the extension's closed shadow
 *  root, which page scripts (and Playwright's selectors) can't. */
async function buttons(page) {
  if (!cdp.has(page)) cdp.set(page, await context.newCDPSession(page));
  const { nodes } = await cdp.get(page).send('Accessibility.getFullAXTree');
  return nodes.filter((n) => n.role?.value === 'button' && !n.ignored)
    .map((n) => ({ page, name: n.name?.value, description: n.description?.value, node: n.backendDOMNodeId }));
}
async function waitFor(test, ms = 30_000) {   // generous: a busy machine can be slow
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 100))) {
    const value = await test();
    if (value) return value;
  }
  return null;
}
const findButton = (page, name) => waitFor(async () => (await buttons(page)).find((b) => b.name === name));
/** A real mouse click in the middle of the button, as a teacher would. */
async function click({ page, node }) {
  const { model } = await cdp.get(page).send('DOM.getBoxModel', { backendNodeId: node });
  const [x1, y1, , , x3, y3] = model.content;
  await page.mouse.click((x1 + x3) / 2, (y1 + y3) / 2);
}
const openClassroom = async (path) => {
  const page = await context.newPage();
  await page.goto(`https://classroom.google.com${path}`);
  return page;
};
const courseListsBy = (token) => fake.log.courseLists.filter((call) => call.token === token).length;

try {
  if (!context.serviceWorkers().length) await context.waitForEvent('serviceworker');
  const welcome = await waitFor(() => context.pages().find((p) => p.url() === `chrome-extension://${ID}/welcome/welcome.html`));
  check('a new install opens the welcome page, with the way to Classroom', Boolean(welcome)
    && (await welcome.textContent('body')).includes('Open Google Classroom'), welcome?.url() ?? 'no welcome tab');
  // An extension page: it can set the dev sign-in and import the google/ modules.
  const ext = await context.newPage();
  await ext.goto(`chrome-extension://${ID}/icons/icon16.png`);
  const signIn = (devToken) => ext.evaluate((t) => (t ? chrome.storage.session.set({ devToken: t }) : chrome.storage.session.remove('devToken')), devToken);
  const teacher = { token: 'teacher-token', email: 'frizzle@school.test', expiresAt: Date.now() + HOUR };

  // (c) Not signed in to KinoDraw yet: a small sign-in chip, which opens the studio tab for this class.
  const classroom = await openClassroom(`/c/${CODE}`);
  const chip = await findButton(classroom, CHIP);
  check('signed out: a small "KinoDraw · Sign in" chip on the class page', !!chip, JSON.stringify(await buttons(classroom)));
  await classroom.screenshot({ path: join(OUT, 'google-signed-out.png') });
  const [studio] = await Promise.all([context.waitForEvent('page'), click(chip)]);
  await studio.waitForLoadState();
  const opened = new URL(studio.url());
  check('the chip opens the studio tab for this class and account', studio.url().split('?')[0] === STUDIO
    && opened.searchParams.get('course') === CODE && opened.searchParams.get('email') === 'frizzle@school.test', studio.url());

  // (a) After signing in on the studio tab, back on Classroom: the teacher of this class gets the button.
  await signIn(teacher);
  await classroom.bringToFront();
  // Headless Chromium keeps every tab "visible", so the teacher's switch back to Classroom is announced by hand.
  await classroom.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  const button = await findButton(classroom, BUTTON);
  check('back from signing in, the chip turns into "Make a doodle video"', !!button && !(await buttons(classroom)).some((b) => b.name === CHIP));
  check('the button says which class the video goes to', button?.description === `Make a hand-drawn video and post it to ${ROOM12.name}`, button?.description);
  await classroom.screenshot({ path: join(OUT, 'google-teacher.png') });
  const list = fake.log.courseLists.find((call) => call.token === 'teacher-token');
  check('the teacher check lists the active classes this account teaches, every page', list?.query.teacherId === 'me'
    && list.query.courseStates === 'ACTIVE' && fake.log.courseLists.some((call) => call.query.pageToken === 'page-2'), JSON.stringify(fake.log.courseLists));
  for (const path of [`/u/1/c/${CODE}`, `/w/${CODE}/t/all`]) {
    const page = await openClassroom(path);
    check(`the button is on ${path} too`, !!(await findButton(page, BUTTON)));
    await page.close();
  }
  check('one teacher check is reused across the class\'s pages', courseListsBy('teacher-token') === 2, JSON.stringify(fake.log.courseLists));

  // Classroom changes pages without reloading.
  await classroom.evaluate((code) => history.pushState({}, '', `/c/${code}`), OTHER_CODE);
  await waitFor(() => courseListsBy('teacher-token') === 4);
  await classroom.waitForTimeout(500);
  check('moving to a class this account doesn\'t teach removes the button', (await buttons(classroom)).length === 0,
    JSON.stringify(await buttons(classroom)));
  await classroom.evaluate((code) => history.pushState({}, '', `/w/${code}/t/all`), CODE);
  check('coming back to the class brings it back', !!(await findButton(classroom, BUTTON)));

  // (d) The button brings back the studio tab for this class; with none open, it opens one.
  const studioIsActive = () => ext.evaluate(async (studioUrl) => {
    const tab = (await chrome.runtime.getContexts({ contextTypes: ['TAB'] })).find((c) => c.documentUrl.startsWith(studioUrl));
    return (await chrome.tabs.get(tab.tabId)).active;
  }, STUDIO);
  await classroom.bringToFront();
  const pages = context.pages().length;
  const wasActive = await studioIsActive();
  await click(await findButton(classroom, BUTTON));
  check('with the studio tab open, the button switches to it instead of opening another',
    !wasActive && !!(await waitFor(studioIsActive)) && context.pages().length === pages, `was active: ${wasActive}`);
  await studio.close();
  const [fresh] = await Promise.all([context.waitForEvent('page'), click(await findButton(classroom, BUTTON))]);
  check('clicking "Make a doodle video" opens studio/studio.html?course=<code>&email=<account>',
    fresh.url() === `${STUDIO}?course=${CODE}&email=frizzle%40school.test`, fresh.url());
  await fresh.close();

  // (b) Students (no active class to teach) see nothing at all; neither does anyone when Google says no.
  for (const [who, token, email, verdict] of [['a student', 'student-token', 'kid@school.test', 'not-teacher'],
    ['a school with the Classroom API off', 'api-off-token', 'librarian@school.test', 'error']]) {
    await signIn({ token, email, expiresAt: Date.now() + HOUR });
    fake.log.account = email;
    const page = await openClassroom(`/c/${CODE}`);
    const answer = await ext.evaluate((message) => chrome.runtime.sendMessage(message), { type: 'teacher-status', courseCode: CODE, accountEmail: email });
    await page.waitForTimeout(1000);   // the page asked first; give its answer time to land
    check(`${who}: the service worker says "${verdict}" and the page shows nothing (no button, no chip, no element)`,
      answer?.status === verdict && (await buttons(page)).length === 0
      && await page.evaluate(() => !document.querySelector('kinodraw-for-classroom')), JSON.stringify({ answer, buttons: await buttons(page) }));
    await page.close();
  }

  // (e) The google/ modules on an extension page, against the Drive, Classroom and KinoDraw Cloud stand-ins.
  const SIZE = 8 * 1024 * 1024 + 300 * 1024;   // more than one 8 MiB piece
  const upload = await ext.evaluate(async (size) => {
    const { uploadVideo } = await import('/google/drive.js');
    const bytes = new Uint8Array(size);
    for (let i = 0; i < size; i++) bytes[i] = (i * 31 + 7) & 255;
    const progress = [];
    const file = await uploadVideo('teacher-token', new Blob([bytes], { type: 'video/mp4' }),
      { name: 'Volcanoes.mp4', onProgress: (sent, total) => progress.push([sent, total]) });
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    return { file, progress, sha: Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join('') };
  }, SIZE);
  const start = fake.log.uploadStart;
  check('the upload starts a resumable session as the teacher', start?.token === 'teacher-token' && start.query.uploadType === 'resumable'
    && start.headers['x-upload-content-type'] === 'video/mp4' && start.headers['x-upload-content-length'] === String(SIZE)
    && start.body.name === 'Volcanoes.mp4' && start.body.mimeType === 'video/mp4', JSON.stringify(start));
  const half = 4 * 1024 * 1024;
  check('it sends 256 KiB-multiple pieces, resumes from what Google kept (308), asks again after a 503, then finishes',
    JSON.stringify(fake.log.pieces) === JSON.stringify([
      { range: `bytes 0-${8 * 1024 * 1024 - 1}/${SIZE}`, length: 8 * 1024 * 1024 },   // Google keeps only 4 MiB of it
      { range: `bytes ${half}-${SIZE - 1}/${SIZE}`, length: SIZE - half },             // 503
      { range: `bytes */${SIZE}`, length: 0 },                                          // "how much do you have?"
      { range: `bytes ${half}-${SIZE - 1}/${SIZE}`, length: SIZE - half },             // done
    ]) && fake.log.uploadProblems.length === 0, JSON.stringify({ pieces: fake.log.pieces, problems: fake.log.uploadProblems }));
  check('Google ends up with exactly the video\'s bytes', fake.log.uploadSha === upload.sha);
  check('uploadVideo returns the Drive file and reports progress up to the end',
    JSON.stringify(upload.file) === JSON.stringify({ id: 'drive-file-1', name: 'Volcanoes.mp4', webViewLink: 'https://drive.google.com/file/d/drive-file-1/view' })
    && JSON.stringify(upload.progress.at(-1)) === JSON.stringify([SIZE, SIZE])
    && upload.progress.every(([sent], i) => i === 0 || sent >= upload.progress[i - 1][0]), JSON.stringify(upload));

  const posted = await ext.evaluate(async (courseId) => {
    const { postMaterial } = await import('/google/classroom.js');
    return [
      await postMaterial('teacher-token', courseId, { title: 'Volcanoes', description: 'Watch before Friday.', driveFileId: 'drive-file-1', state: 'DRAFT' }),
      await postMaterial('teacher-token', courseId, { title: 'Volcanoes', driveFileId: 'drive-file-1' }),
    ];
  }, ROOM12.id);
  const [draft, published] = fake.log.materials;
  check('postMaterial posts the Drive file, view only, as a draft when asked', draft?.courseId === ROOM12.id && draft.token === 'teacher-token'
    && JSON.stringify(draft.body.materials) === JSON.stringify([{ driveFile: { driveFile: { id: 'drive-file-1' }, shareMode: 'VIEW' } }])
    && draft.body.state === 'DRAFT' && draft.body.title === 'Volcanoes' && draft.body.description === 'Watch before Friday.'
    && posted[0].state === 'DRAFT' && posted[0].alternateLink.includes('/m/material-1/'), JSON.stringify({ draft, posted }));
  check('and published by default', published?.body.state === 'PUBLISHED' && posted[1].state === 'PUBLISHED', JSON.stringify(published));

  const apiOff = await ext.evaluate(async () => {
    const { listTeachingCourses } = await import('/google/classroom.js');
    return listTeachingCourses('api-off-token').then(() => 'no error', (e) => e.message);
  });
  check('Classroom API turned off by the school: the teacher is told to ask IT', /ask your IT team/i.test(apiOff), apiOff);

  const cloud = await ext.evaluate(async () => {
    const { directSection, eduSession, openVideo } = await import('/google/cloud.js');
    const session = await eduSession('teacher-token');
    const video = await openVideo(session.token, { sections: 2, characters: 800 });
    const section = await directSection(session.token, video.video_id, { language: 'en', beats: [] });
    const refused = await eduSession('student-token').then(() => 'no error', (e) => e.message);
    return { session, video, section, refused };
  });
  check('KinoDraw Cloud: the Google sign-in becomes an edu token, and Luna directs the video', cloud.session.plan === 'edu'
    && cloud.video.model === 'gpt-6-luna' && cloud.section.section_title === 'Volcanoes'
    && fake.log.cloud.filter((c) => c.path !== '/v1/edu/session').every((c) => c.token === 'cloud-token')
    && fake.log.cloud[0].body.google_token === 'teacher-token', JSON.stringify({ cloud, calls: fake.log.cloud }));
  check('KinoDraw Cloud\'s refusal reads as a sentence', cloud.refused === 'KinoDraw for Classroom is for teachers.', cloud.refused);

  // The toolbar button's path: open (then focus) the studio without a class.
  const [plain] = await Promise.all([context.waitForEvent('page'), ext.evaluate(() => chrome.runtime.sendMessage({ type: 'open-studio' }))]);
  const reply = await ext.evaluate(() => chrome.runtime.sendMessage({ type: 'open-studio' }));
  check('the toolbar button opens the studio, then switches to it', plain.url() === STUDIO && reply?.ok === true
    && context.pages().filter((p) => p.url().startsWith(STUDIO)).length === 1, plain.url());

  check('nothing asked for any other address (no Google sign-in in dev mode)', fake.log.unexpected.length === 0, JSON.stringify(fake.log.unexpected));
} finally {
  await context.close();
}
console.log(failures ? `\n${failures} FAILED` : '\nall checks passed');
process.exit(failures ? 1 : 0);

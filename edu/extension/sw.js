// KinoDraw for Classroom service worker: answers the Classroom page's "is this person a teacher of
// this class?" and opens the studio tab. Chrome stops it whenever it is idle, so what it remembers lives
// in chrome.storage.session. Google is only called from here and from extension pages, never from the
// content script (that runs with Classroom's origin, where CORS applies).
import { AuthError, getToken } from './google/auth.js';
import { courseFromCode, listTeachingCourses } from './google/classroom.js';

const STUDIO = chrome.runtime.getURL('studio/studio.html');
const TRUST_MS = 10 * 60_000;   // a class's teacher check is reused for ten minutes

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message?.type === 'teacher-status') {
    teacherStatus(message).then(reply);
    return true;   // the reply comes later
  }
  if (message?.type === 'open-studio') {
    openStudio(message, sender.tab).then(() => reply({ ok: true }), (e) => reply({ ok: false, message: e.message }));
    return true;
  }
});

chrome.action.onClicked.addListener((tab) => openStudio({}, tab));

// A new install opens a short welcome page: where the button is and what it does.
chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === chrome.runtime.OnInstalledReason.INSTALL) chrome.tabs.create({ url: chrome.runtime.getURL('welcome/welcome.html') });
});

/** → { status: 'teacher' | 'not-teacher' | 'signed-out' | 'error', course?: { id, name }, message? } */
async function teacherStatus({ courseCode, accountEmail }) {
  let auth;
  try {
    auth = await getToken({ loginHint: accountEmail });
  } catch (e) {
    return failure(e);
  }
  const key = `teacher-status:${auth.email}:${courseCode}`;
  const { [key]: saved } = await chrome.storage.session.get(key);
  if (saved && Date.now() - saved.at < TRUST_MS) return saved.answer;
  let course;
  try {
    course = courseFromCode(await listTeachingCourses(auth.token), courseCode);
  } catch (e) {
    return failure(e);
  }
  const answer = course ? { status: 'teacher', course: { id: course.id, name: course.name } } : { status: 'not-teacher' };
  await chrome.storage.session.set({ [key]: { at: Date.now(), answer } });
  return answer;
}

// No usable Google sign-in (never signed in, access withdrawn, token turned down) means "signed-out":
// the page offers sign-in. Anything else is an error, which the page keeps quiet about.
const failure = (e) => (e instanceof AuthError && e.code !== 'failed'
  ? { status: 'signed-out' }
  : { status: 'error', message: e.message });

/** Focus the studio tab for this class if one is open (any studio tab for the toolbar button), or open one
 *  next to the tab the teacher came from. */
async function openStudio({ courseCode, accountEmail }, fromTab) {
  const tabs = await chrome.runtime.getContexts({ contextTypes: ['TAB'] });
  const open = tabs.find(({ documentUrl = '' }) => documentUrl.startsWith(STUDIO)
    && (!courseCode || new URL(documentUrl).searchParams.get('course') === courseCode));
  if (open) {
    await chrome.tabs.update(open.tabId, { active: true });
    await chrome.windows.update(open.windowId, { focused: true });
    return;
  }
  const url = new URL(STUDIO);
  if (courseCode) url.searchParams.set('course', courseCode);
  if (accountEmail) url.searchParams.set('email', accountEmail);
  await chrome.tabs.create({ url: url.href, ...(fromTab && { windowId: fromTab.windowId, index: fromTab.index + 1, openerTabId: fromTab.id }) });
}

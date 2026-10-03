// Unit tests for the Google side of KinoDraw for Classroom (google/*.js) with a fake chrome.* and a
// fake fetch: no network, no browser. tests/e2e/google.mjs runs the real extension in Chromium.
import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';
import { CONFIG } from '../extension/config.js';
import { AuthError, getToken, googleFetch, signOut } from '../extension/google/auth.js';
import { courseFromCode, listTeachingCourses, postMaterial } from '../extension/google/classroom.js';
import { CloudError, directSection, eduSession, openVideo } from '../extension/google/cloud.js';
import { uploadVideo } from '../extension/google/drive.js';

const REDIRECT = 'https://hoddalijnehhimlamfchabikgmjfgeoe.chromiumapp.org/';
const HOUR = 3_600_000;
const realFetch = globalThis.fetch;
afterEach(() => {
  CONFIG.dev = false;
  globalThis.fetch = realFetch;
  delete globalThis.chrome;
});

/** chrome.storage.session and chrome.identity; `flow(authUrl, details)` plays Google's sign-in page. */
function fakeChrome(flow = () => { throw new Error('no sign-in expected'); }) {
  const session = {};
  const flows = [];
  globalThis.chrome = {
    storage: {
      session: {
        async get(key) { return key in session ? { [key]: structuredClone(session[key]) } : {}; },
        async set(items) { Object.assign(session, structuredClone(items)); },
        async remove(key) { delete session[key]; },
      },
    },
    identity: {
      getRedirectURL: () => REDIRECT,
      async launchWebAuthFlow(details) {
        flows.push(details);
        return flow(new URL(details.url), details);
      },
    },
  };
  return { session, flows };
}

/** Google's redirect back to the extension, as the sign-in page would send it. */
function redirect(authUrl, fields) {
  const answer = new URLSearchParams({ state: authUrl.searchParams.get('state'), ...fields });
  return `${REDIRECT}#${answer}`;
}
const granted = (fields = {}) => (authUrl) => redirect(authUrl, {
  access_token: 'tok-1', token_type: 'Bearer', expires_in: '3599', scope: CONFIG.scopes.join(' '), ...fields,
});

/** Every fetch() goes to `answer(call)`; the returned list records the calls. */
function fakeFetch(answer) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method ?? 'GET', headers: init.headers ?? {}, body: init.body };
    calls.push(call);
    return answer(call);
  };
  return calls;
}
const json = (data, status = 200, headers = {}) => new Response(JSON.stringify(data), {
  status, headers: { 'content-type': 'application/json', ...headers },
});
const userinfo = (email = 'Frizzle@School.test') => ({ url }) => {
  assert.equal(url, 'https://www.googleapis.com/oauth2/v3/userinfo');
  return json({ sub: '1', email, email_verified: true });
};

describe('auth: signing in with launchWebAuthFlow', () => {
  test('an interactive sign-in asks Google for a token for the Classroom account and remembers it', async () => {
    const { flows } = fakeChrome(granted());
    const calls = fakeFetch(userinfo());
    const before = Date.now();
    const token = await getToken({ interactive: true, loginHint: 'Frizzle@School.test' });
    assert.equal(token.token, 'tok-1');
    assert.equal(token.email, 'frizzle@school.test');
    assert.ok(token.expiresAt >= before + 3599_000 && token.expiresAt <= Date.now() + 3599_000);
    const url = new URL(flows[0].url);
    assert.equal(url.origin + url.pathname, 'https://accounts.google.com/o/oauth2/v2/auth');
    assert.equal(url.searchParams.get('client_id'), CONFIG.googleClientId);
    assert.equal(url.searchParams.get('redirect_uri'), REDIRECT);
    assert.equal(url.searchParams.get('response_type'), 'token');
    assert.equal(url.searchParams.get('scope'), CONFIG.scopes.join(' '));
    assert.equal(url.searchParams.get('include_granted_scopes'), 'true');
    assert.equal(url.searchParams.get('login_hint'), 'frizzle@school.test');
    assert.equal(url.searchParams.get('prompt'), null);
    assert.equal(flows[0].interactive, true);
    assert.equal(calls[0].headers.Authorization, 'Bearer tok-1');
    assert.deepEqual(await getToken({ loginHint: 'frizzle@school.test' }), token, 'the saved token is reused');
    assert.deepEqual(await getToken(), token, 'no hint: the last account signed in');
    assert.equal(flows.length, 1);
  });

  test('a silent sign-in shows nothing and waits for Google\'s script redirects', async () => {
    const { flows } = fakeChrome(granted());
    fakeFetch(userinfo());
    await getToken();
    assert.equal(flows[0].interactive, false);
    assert.equal(new URL(flows[0].url).searchParams.get('prompt'), 'none');
    assert.equal(flows[0].abortOnLoadForNonInteractive, false);
    assert.ok(flows[0].timeoutMsForNonInteractive > 0);
  });

  test('another account, or a token about to expire, means a new sign-in', async () => {
    const { session, flows } = fakeChrome(granted({ access_token: 'tok-2' }));
    fakeFetch(userinfo('kid@school.test'));
    session.googleAuth = {
      accounts: { 'frizzle@school.test': { token: 'tok-1', email: 'frizzle@school.test', expiresAt: Date.now() + HOUR } },
      last: 'frizzle@school.test',
    };
    assert.equal((await getToken({ loginHint: 'kid@school.test' })).token, 'tok-2');
    assert.equal(new URL(flows[0].url).searchParams.get('login_hint'), 'kid@school.test');
    assert.equal((await getToken({ loginHint: 'frizzle@school.test' })).token, 'tok-1', 'both accounts are remembered');
    session.googleAuth.accounts['frizzle@school.test'].expiresAt = Date.now() + 30_000;
    await getToken({ loginHint: 'frizzle@school.test' });
    assert.equal(flows.length, 2);
  });

  const failures = [
    ['a silent sign-in that needs the teacher', granted({ error: 'interaction_required' }), 'signed-out', /Sign in with Google/],
    ['the teacher choosing Cancel', granted({ error: 'access_denied' }), 'denied', /choose Allow/],
    ['a school admin block', granted({ error: 'admin_policy_enforced' }), 'denied', /IT team/],
    ['an unticked permission', granted({ scope: CONFIG.scopes.slice(0, 2).join(' ') }), 'denied', /leave every box checked/],
    ['a closed sign-in window', () => { throw new Error('The user did not approve access.'); }, 'signed-out', /closed/],
    ['no internet', () => { throw new Error('Authorization page could not be loaded.'); }, 'failed', /internet/],
    ['a redirect for another request', (authUrl) => `${REDIRECT}#access_token=x&state=not-${authUrl.searchParams.get('state')}`, 'failed', /went wrong/],
    ['a broken client setup', granted({ error: 'invalid_client' }), 'failed', /invalid_client/],
  ];
  for (const [what, flow, code, message] of failures) {
    test(`${what} is AuthError '${code}'`, async () => {
      fakeChrome(flow);
      fakeFetch(userinfo());
      await assert.rejects(getToken({ interactive: true }), (e) => e instanceof AuthError && e.code === code && message.test(e.message));
    });
  }

  test('Google may call the email permission "email"', async () => {
    fakeChrome(granted({ scope: CONFIG.scopes.map((s) => (s.endsWith('userinfo.email') ? 'email' : s)).join(' ') }));
    fakeFetch(userinfo());
    assert.equal((await getToken({ interactive: true })).email, 'frizzle@school.test');
  });

  test('in dev mode (tests only) the token comes from chrome.storage.session.devToken, never from Google', async () => {
    CONFIG.dev = true;
    const { session, flows } = fakeChrome();
    await assert.rejects(getToken({ interactive: true }), (e) => e instanceof AuthError && e.code === 'signed-out');
    session.devToken = { token: 'dev', email: 'frizzle@school.test', expiresAt: Date.now() + HOUR };
    assert.deepEqual(await getToken(), session.devToken);
    assert.equal(flows.length, 0);
  });

  test('signing out forgets the tokens and withdraws the access at Google', async () => {
    const { session } = fakeChrome();
    session.googleAuth = { accounts: { 'frizzle@school.test': { token: 'tok-1', email: 'frizzle@school.test', expiresAt: Date.now() + HOUR } }, last: 'frizzle@school.test' };
    const calls = fakeFetch(() => new Response(''));
    await signOut();
    assert.equal(session.googleAuth, undefined);
    assert.equal(calls[0].url, 'https://oauth2.googleapis.com/revoke');
    assert.equal(calls[0].method, 'POST');
    assert.equal(String(calls[0].body), 'token=tok-1');
  });

  test('a token Google turns down is forgotten, so the next getToken() signs in again', async () => {
    const { session } = fakeChrome();
    session.googleAuth = { accounts: { 'frizzle@school.test': { token: 'tok-1', email: 'frizzle@school.test', expiresAt: Date.now() + HOUR } }, last: 'frizzle@school.test' };
    fakeFetch(() => json({ error: { code: 401, message: 'Request had invalid authentication credentials.' } }, 401));
    await assert.rejects(googleFetch('tok-1', 'https://classroom.googleapis.com/v1/courses'),
      (e) => e instanceof AuthError && e.code === 'signed-out');
    assert.deepEqual(session.googleAuth.accounts, {});
  });
});

describe('classroom: courses and posting', () => {
  const room12 = { id: '123456789012', name: 'Room 12 Science', section: 'Period 2', alternateLink: 'https://classroom.google.com/c/NzAxNjI2NTY3MTQ5' };
  const art = { id: '555', name: 'Art', section: '', alternateLink: 'https://classroom.google.com/u/1/c/QXJ0Q29kZQ' };

  test('courseFromCode matches the code in the class address against each course link', () => {
    assert.equal(courseFromCode([art, room12], 'NzAxNjI2NTY3MTQ5'), room12);
    assert.equal(courseFromCode([art, room12], 'QXJ0Q29kZQ'), art, 'links may carry /u/<n>/');
    assert.equal(courseFromCode([art, room12], 'NzAxNjI2NTY3MTQ'), null, 'no partial matches');
    assert.equal(courseFromCode([art, room12], ''), null);
    assert.equal(courseFromCode([], 'NzAxNjI2NTY3MTQ5'), null);
  });

  test('courseFromCode falls back to reading the code as base64 of the course id', () => {
    const unlinked = { ...room12, alternateLink: 'https://classroom.google.com/c/SomethingElse' };
    assert.equal(courseFromCode([art, unlinked], btoa('123456789012')), unlinked);
    const odd = { ...room12, id: '1234567890123' };            // 13 digits: base64 needs padding
    assert.equal(courseFromCode([odd], btoa('1234567890123').replace(/=+$/, '')), odd, 'padding may be missing');
    assert.equal(courseFromCode([room12], btoa('Room 12')), null, 'text that is not a numeric id');
    assert.equal(courseFromCode([room12], '*not base64*'), null);
  });

  test('listTeachingCourses reads every page of the active classes this account teaches', async () => {
    const calls = fakeFetch(({ url }) => (new URL(url).searchParams.get('pageToken') === 'p2'
      ? json({ courses: [{ ...room12, ownerId: '1', courseState: 'ACTIVE' }] })
      : json({ courses: [art], nextPageToken: 'p2' })));
    assert.deepEqual(await listTeachingCourses('tok-1'), [art, room12]);
    assert.equal(calls.length, 2);
    for (const { url, headers } of calls) {
      const params = new URL(url).searchParams;
      assert.equal(new URL(url).origin + new URL(url).pathname, 'https://classroom.googleapis.com/v1/courses');
      assert.equal(params.get('teacherId'), 'me');
      assert.equal(params.get('courseStates'), 'ACTIVE');
      assert.equal(headers.Authorization, 'Bearer tok-1');
    }
  });

  test('listTeachingCourses: someone who teaches nothing gets [] (Google leaves the list out)', async () => {
    fakeFetch(() => json({}));
    assert.deepEqual(await listTeachingCourses('tok-student'), []);
  });

  test('Google\'s errors reach the teacher as plain advice', async () => {
    const cases = [
      [json({ error: { code: 403, message: '@ClassroomApiDisabled The user is not permitted to access the Classroom API.', status: 'PERMISSION_DENIED' } }, 403), /IT team to turn on the Classroom API/],
      [json({ error: { code: 403, message: 'Request had insufficient authentication scopes.', status: 'PERMISSION_DENIED', details: [{ reason: 'ACCESS_TOKEN_SCOPE_INSUFFICIENT' }] } }, 403), /leave every box checked/],
      [json({ error: { code: 403, message: 'The caller does not have permission', status: 'PERMISSION_DENIED' } }, 403), /teach this class/],
      [json({ error: { code: 429, message: 'Quota exceeded', status: 'RESOURCE_EXHAUSTED' } }, 429), /busy/],
      [new Response('<html>oops</html>', { status: 502 }), /isn't answering/],
    ];
    for (const [response, message] of cases) {
      fakeFetch(() => response);
      await assert.rejects(listTeachingCourses('tok-1'), (e) => message.test(e.message) && e.status === response.status);
    }
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(listTeachingCourses('tok-1'), (e) => /internet connection/.test(e.message) && e.status === 0);
  });

  test('postMaterial posts the Drive file as a view-only material in the chosen state', async () => {
    const calls = fakeFetch(({ body }) => json({ id: 'm1', alternateLink: 'https://classroom.google.com/c/x/m/m1/details', ...JSON.parse(body) }));
    const posted = await postMaterial('tok-1', '123456789012', { title: 'Volcanoes', description: 'Watch before Friday.', driveFileId: 'f1', state: 'DRAFT' });
    assert.deepEqual(posted, { id: 'm1', alternateLink: 'https://classroom.google.com/c/x/m/m1/details', state: 'DRAFT' });
    assert.equal(calls[0].url, 'https://classroom.googleapis.com/v1/courses/123456789012/courseWorkMaterials');
    assert.equal(calls[0].method, 'POST');
    assert.equal(calls[0].headers.Authorization, 'Bearer tok-1');
    assert.deepEqual(JSON.parse(calls[0].body), {
      title: 'Volcanoes', description: 'Watch before Friday.', state: 'DRAFT',
      materials: [{ driveFile: { driveFile: { id: 'f1' }, shareMode: 'VIEW' } }],
    });
    await postMaterial('tok-1', '123456789012', { title: 'Volcanoes', driveFileId: 'f1' });
    assert.equal(JSON.parse(calls[1].body).state, 'PUBLISHED', 'published unless asked otherwise');
  });
});

describe('drive: resumable upload (the multi-piece path runs in tests/e2e/google.mjs)', () => {
  const video = new Blob([new Uint8Array(1000)], { type: 'video/mp4' });

  test('a full Drive says so', async () => {
    fakeFetch(() => json({ error: { code: 403, message: 'The user\'s Drive storage quota has been exceeded.', errors: [{ reason: 'storageQuotaExceeded' }] } }, 403));
    await assert.rejects(uploadVideo('tok-1', video, { name: 'v.mp4' }), /Drive is full/);
  });

  test('an upload session Google has dropped asks for a fresh start', async () => {
    fakeFetch(({ method }) => (method === 'POST'
      ? new Response('', { status: 200, headers: { Location: 'https://www.googleapis.com/upload/drive/v3/files?upload_id=s1' } })
      : json({ error: { code: 404, message: 'Not Found' } }, 404)));
    await assert.rejects(uploadVideo('tok-1', video, { name: 'v.mp4' }), /cancelled it/);
  });

  test('a small video goes up in one piece and reports its progress', async () => {
    const progress = [];
    const calls = fakeFetch(({ method }) => (method === 'POST'
      ? new Response('', { status: 200, headers: { Location: 'https://www.googleapis.com/upload/drive/v3/files?upload_id=s1' } })
      : json({ id: 'f1', name: 'v.mp4', webViewLink: 'https://drive.google.com/file/d/f1/view' }, 201)));
    const file = await uploadVideo('tok-1', video, { name: 'v.mp4', onProgress: (sent, total) => progress.push([sent, total]) });
    assert.deepEqual(file, { id: 'f1', name: 'v.mp4', webViewLink: 'https://drive.google.com/file/d/f1/view' });
    assert.equal(calls[1].headers['Content-Range'], 'bytes 0-999/1000');
    assert.equal(calls[1].headers.Authorization, undefined, 'the session address is the credential');
    assert.deepEqual(progress, [[1000, 1000]]);
  });
});

describe('cloud: KinoDraw Cloud client', () => {
  test('eduSession trades the Google token for a KinoDraw Cloud token', async () => {
    const calls = fakeFetch(() => json({ token: 'dc-1', plan: 'edu', remaining: 30 }));
    assert.deepEqual(await eduSession('tok-1'), { token: 'dc-1', plan: 'edu', remaining: 30 });
    assert.equal(calls[0].url, `${CONFIG.cloudUrl}/v1/edu/session`);
    assert.deepEqual(JSON.parse(calls[0].body), { google_token: 'tok-1' });
    assert.equal(calls[0].headers.Authorization, undefined);
  });

  test('openVideo and directSection send the KinoDraw Cloud token; directSection returns the section', async () => {
    const section = { section_title: 'Volcanoes', beats: [] };
    const calls = fakeFetch(({ url }) => json(url.endsWith('/v1/videos') ? { video_id: 'v1', model: 'gpt-6-luna' } : { section, usage: {} }));
    assert.deepEqual(await openVideo('dc-1', { sections: 3, characters: 900 }), { video_id: 'v1', model: 'gpt-6-luna' });
    assert.deepEqual(await directSection('dc-1', 'v1', { language: 'en' }), section);
    assert.deepEqual(JSON.parse(calls[0].body), { sections: 3, characters: 900 });
    assert.deepEqual(JSON.parse(calls[1].body), { video_id: 'v1', section: { language: 'en' } });
    assert.ok(calls.every((c) => c.headers.Authorization === 'Bearer dc-1'));
  });

  test('KinoDraw Cloud\'s {error} messages become readable sentences', async () => {
    fakeFetch(() => json({ error: 'KinoDraw for Classroom is for teachers' }, 403));
    await assert.rejects(eduSession('tok-student'),
      (e) => e instanceof CloudError && e.status === 403 && e.message === 'KinoDraw for Classroom is for teachers.');
    fakeFetch(() => new Response('error code: 1010', { status: 403 }));
    await assert.rejects(eduSession('tok-1'), (e) => e.status === 403 && /isn't answering right now \(error 403\)/.test(e.message));
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(openVideo('dc-1', { sections: 1, characters: 10 }), (e) => e.status === 0 && /Can't reach KinoDraw Cloud/.test(e.message));
  });
});

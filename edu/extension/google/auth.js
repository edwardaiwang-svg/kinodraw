// Google sign-in for KinoDraw for Classroom, and calls to Google APIs with the teacher's token.
//
// chrome.identity.launchWebAuthFlow works in Chrome and Edge with any Google account and takes a
// login_hint, so the teacher signs in with the account Classroom is showing (getAuthToken is
// Chrome-only and can quietly pick another account when several are signed in). Tokens live in
// chrome.storage.session: in memory only, gone when the browser closes, out of reach of web pages.
import { CONFIG } from '../config.js';

const AUTHORIZE = 'https://accounts.google.com/o/oauth2/v2/auth';
const USERINFO = 'https://www.googleapis.com/oauth2/v3/userinfo';
const REVOKE = 'https://oauth2.googleapis.com/revoke';
const EMAIL_SCOPE = 'https://www.googleapis.com/auth/userinfo.email';
const SAVED = 'googleAuth';      // chrome.storage.session: { accounts: { [email]: { token, email, expiresAt } }, last }
const RENEW_MS = 60_000;         // renew a token a minute before Google says it expires
const SILENT_MS = 10_000;        // a silent sign-in gives up after this (Google's pages redirect with JavaScript)

const SIGN_IN = 'Sign in with Google to use KinoDraw.';
const CLOSED = 'Sign-in was closed before it finished. If Google showed an error, your school\'s IT team may need '
  + 'to allow KinoDraw for Classroom first.';
const ALL_BOXES = 'KinoDraw needs every permission on the Google screen: seeing your classes, posting to '
  + 'Classwork and saving videos to your Drive. Please sign in again and leave every box checked.';
const OFFLINE = 'Can\'t reach Google. Check your internet connection and try again.';

export class AuthError extends Error {
  /** @param {'signed-out' | 'denied' | 'failed'} code */
  constructor(code, message) {
    super(message);
    this.name = 'AuthError';
    this.code = code;
  }
}

/** A Google API said no. `status` is the HTTP status (0: no answer at all); `reason` is Google's code. */
export class GoogleError extends Error {
  constructor(message, status, reason = '') {
    super(message);
    this.name = 'GoogleError';
    this.status = status;
    this.reason = reason;
  }
}

/** The teacher's Google access token: { token, email, expiresAt }. Without `interactive` it never shows
 *  a window: it reuses a saved token or tries a silent sign-in, and throws AuthError 'signed-out'. */
export async function getToken({ interactive = false, loginHint } = {}) {
  return oneAtATime(() => (CONFIG.dev ? devToken() : token(interactive, loginHint?.trim().toLowerCase() || '')));
}

/** Forget the teacher's tokens and withdraw KinoDraw's access in their Google account, so a later
 *  silent sign-in can't quietly bring the session back. */
export async function signOut() {
  return oneAtATime(async () => {
    if (CONFIG.dev) return chrome.storage.session.remove('devToken');
    const { accounts } = await load();
    await chrome.storage.session.remove(SAVED);
    await Promise.all(Object.values(accounts).map(({ token }) => fetch(REVOKE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ token }),
    }).catch(() => {})));    // offline or already expired: forgetting the token is what matters
  });
}

/** fetch() a Google API as the teacher (`token` null: the URL is the credential, as with upload sessions).
 *  Returns the response when it is ok or its status is in `expect`; otherwise throws an error a teacher can
 *  act on. A token Google turns down is forgotten, so the next getToken() asks Google for a new one. */
export async function googleFetch(token, url, { expect = [], headers = {}, ...init } = {}) {
  let response;
  try {
    response = await fetch(url, { ...init, headers: token ? { Authorization: `Bearer ${token}`, ...headers } : headers });
  } catch {
    throw new GoogleError(OFFLINE, 0);
  }
  if (response.ok || expect.includes(response.status)) return response;
  if (response.status === 401 && token) {
    await forget(token);
    throw new AuthError('signed-out', 'Your Google sign-in has expired. Please sign in again.');
  }
  throw await googleError(response);
}

// Two Classroom tabs asking at once share one silent sign-in instead of racing two.
let queue = Promise.resolve();
function oneAtATime(work) {
  const run = queue.then(work);
  queue = run.catch(() => {});
  return run;
}

async function devToken() {
  const { devToken } = await chrome.storage.session.get('devToken');
  if (!devToken) throw new AuthError('signed-out', SIGN_IN);
  return devToken;
}

async function token(interactive, hint) {
  const saved = await load();
  const current = saved.accounts[hint || saved.last];
  if (current && current.expiresAt - RENEW_MS > Date.now()) return current;
  const fresh = await authorize(interactive, hint || current?.email || '');
  saved.accounts[fresh.email] = fresh;
  saved.last = fresh.email;
  await chrome.storage.session.set({ [SAVED]: saved });
  return fresh;
}

async function authorize(interactive, loginHint) {
  const state = crypto.randomUUID();
  const url = new URL(AUTHORIZE);
  url.search = new URLSearchParams({
    client_id: CONFIG.googleClientId,
    redirect_uri: chrome.identity.getRedirectURL(),
    response_type: 'token',
    scope: CONFIG.scopes.join(' '),
    include_granted_scopes: 'true',
    state,
    ...(loginHint && { login_hint: loginHint }),
    ...(!interactive && { prompt: 'none' }),
  });
  let redirect;
  try {
    redirect = await chrome.identity.launchWebAuthFlow({
      url: url.href, interactive, abortOnLoadForNonInteractive: false, timeoutMsForNonInteractive: SILENT_MS,
    });
  } catch (e) {
    // Chrome says "Authorization page could not be loaded." when offline, "User interaction required."
    // when a silent sign-in needs the teacher, and "The user did not approve access." when the window closes.
    if (/could not be loaded/i.test(e?.message)) throw new AuthError('failed', OFFLINE);
    throw new AuthError('signed-out', interactive ? CLOSED : SIGN_IN);
  }
  const answer = new URLSearchParams(new URL(redirect).hash.slice(1));
  if (answer.get('error')) throw oauthError(answer.get('error'));
  if (answer.get('state') !== state) throw new AuthError('failed', 'Google sign-in went wrong. Please try again.');
  // With granular consent a teacher can untick permissions, and each one is needed. Google may call the email
  // scope "email"; if it leaves the list out, the APIs themselves will object later.
  const granted = new Set((answer.get('scope') ?? CONFIG.scopes.join(' ')).split(' ')
    .map((scope) => (scope === 'email' ? EMAIL_SCOPE : scope)));
  if (!CONFIG.scopes.every((scope) => granted.has(scope))) throw new AuthError('denied', ALL_BOXES);
  const token = answer.get('access_token');
  const expiresAt = Date.now() + Number(answer.get('expires_in') || 3600) * 1000;
  const { email } = await (await googleFetch(token, USERINFO)).json();
  if (!email) throw new AuthError('denied', ALL_BOXES);
  return { token, email: email.toLowerCase(), expiresAt };
}

function oauthError(error) {
  if (['interaction_required', 'login_required', 'consent_required', 'account_selection_required'].includes(error)) {
    return new AuthError('signed-out', SIGN_IN);
  }
  if (error === 'admin_policy_enforced') {
    return new AuthError('denied', 'Your school\'s Google admin hasn\'t allowed KinoDraw for Classroom yet. Ask your '
      + 'IT team to allow it (Google Admin console > Security > Access and data control > API controls).');
  }
  if (error === 'access_denied') {
    return new AuthError('denied', 'Google sign-in was cancelled. To use KinoDraw, sign in again and choose Allow.');
  }
  return new AuthError('failed', `Google sign-in didn't work (${error}). Please try again later.`);
}

async function googleError(response) {
  const { error = {} } = await response.json().catch(() => ({}));
  const message = String(error.message ?? '');
  const reason = error.errors?.[0]?.reason ?? error.details?.find((detail) => detail.reason)?.reason ?? error.status ?? '';
  const say = (text) => new GoogleError(text, response.status, reason);
  if (message.includes('ClassroomApiDisabled')) {
    return say('Your school has turned off apps\' access to Google Classroom. Ask your IT team to turn on the '
      + 'Classroom API (Google Admin console > Apps > Google Workspace > Classroom > Data access).');
  }
  if (message.includes('ClassroomDisabled')) {
    return say('This Google account can\'t use Google Classroom. Check that you\'re signed in with your school account.');
  }
  if (reason === 'ACCESS_TOKEN_SCOPE_INSUFFICIENT' || reason === 'insufficientPermissions') return say(ALL_BOXES);
  if (reason === 'storageQuotaExceeded') return say('Your Google Drive is full. Make some room in Drive and try again.');
  if (reason === 'SERVICE_DISABLED' || reason === 'accessNotConfigured') {
    return say('KinoDraw can\'t use Google Classroom or Drive right now (a setup problem on our side). '
      + 'Please let the KinoDraw team know.');
  }
  if (response.status === 429 || /rateLimitExceeded/.test(reason)) return say('Google is busy right now. Wait a minute and try again.');
  if (response.status >= 500) return say('Google isn\'t answering right now. Try again in a few minutes.');
  if (response.status === 403) {
    return say('Google didn\'t allow that. Check that you\'re signed in with your school account and that you teach this class.');
  }
  if (response.status === 404) return say('Google couldn\'t find that class or file. It may have been removed.');
  return say(`Google couldn't do that${message ? `: ${message}` : ''}.`);
}

async function load() {
  const { [SAVED]: saved } = await chrome.storage.session.get(SAVED);
  return saved ?? { accounts: {}, last: '' };
}

async function forget(token) {
  const saved = await load();
  for (const [email, entry] of Object.entries(saved.accounts)) if (entry.token === token) delete saved.accounts[email];
  await chrome.storage.session.set({ [SAVED]: saved });
}

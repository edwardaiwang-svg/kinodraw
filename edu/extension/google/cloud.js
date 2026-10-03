// KinoDraw Cloud: the GPT-6 Luna storyboard director. The teacher's Google sign-in is exchanged for a
// KinoDraw Cloud token on the "edu" plan; the server itself checks with Google that they teach a class.
import { CONFIG } from '../config.js';

/** KinoDraw Cloud said no (or didn't answer). `status` is the HTTP status, 0 when there was no answer. */
export class CloudError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'CloudError';
    this.status = status;
  }
}

/** → { token, plan: 'edu', remaining, opus_remaining, allowance_used, period_end } */
export async function eduSession(googleToken) {
  return call('/v1/edu/session', { google_token: googleToken });
}

/** Count one video against the plan. → { video_id, model: 'gpt-6-luna', ... } */
export async function openVideo(cloudToken, { sections, characters }) {
  return call('/v1/videos', { sections, characters }, cloudToken);
}

/** The director's answer for one section (the schema in doodle-cloud's src/contract.json). */
export async function directSection(cloudToken, videoId, payload) {
  return (await call('/v1/direct', { video_id: videoId, section: payload }, cloudToken)).section;
}

async function call(path, body, token) {
  let response;
  try {
    response = await fetch(CONFIG.cloudUrl + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token && { Authorization: `Bearer ${token}` }) },
      body: JSON.stringify(body),
    });
  } catch {
    throw new CloudError('Can\'t reach KinoDraw Cloud. Check your internet connection and try again.', 0);
  }
  const data = await response.json().catch(() => null);
  if (response.ok && data) return data;
  throw new CloudError(data?.error ? sentence(data.error)
    : `KinoDraw Cloud isn't answering right now (error ${response.status}). Try again in a few minutes.`, response.status);
}

// The server answers in short lowercase phrases ("sign in first"); teachers read them as sentences.
const sentence = (text) => text[0].toUpperCase() + text.slice(1) + (/[.!?]$/.test(text) ? '' : '.');

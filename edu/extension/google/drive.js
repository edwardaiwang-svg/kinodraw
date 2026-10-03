// Google Drive: save the finished video to the teacher's Drive with a resumable upload, so a school Wi-Fi
// hiccup costs one piece of the video, not the whole upload. The drive.file permission only lets KinoDraw see
// the files it made.
import { googleFetch } from './auth.js';

const START = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,webViewLink';
const PIECE = 32 * 256 * 1024;   // 8 MiB: Google takes pieces in multiples of 256 KiB (only the last may be shorter)
const RETRIES = 6;               // waits of about 1, 2, 4, 8, 16 and 32 seconds before giving up

/** Upload the video; onProgress(sentBytes, totalBytes) after each piece Google confirms. → { id, name, webViewLink } */
export async function uploadVideo(token, blob, { name, onProgress }) {
  const type = blob.type || 'video/mp4';
  const start = await googleFetch(token, START, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json; charset=UTF-8',
      'X-Upload-Content-Type': type,
      'X-Upload-Content-Length': String(blob.size),
    },
    body: JSON.stringify({ name, mimeType: type }),
  });
  const session = start.headers.get('Location');   // the upload's own address; it needs no token
  let offset = 0;          // bytes Google has confirmed
  let failures = 0;
  let lost = false;        // after a failed request, first ask Google how much it kept
  for (;;) {
    const end = Math.min(offset + PIECE, blob.size);
    let response;
    try {
      response = await googleFetch(null, session, {
        method: 'PUT',
        headers: { 'Content-Range': lost ? `bytes */${blob.size}` : `bytes ${offset}-${end - 1}/${blob.size}` },
        body: lost ? undefined : blob.slice(offset, end),
        expect: [308],       // "Resume Incomplete": send the next piece
      });
    } catch (e) {
      if (e.status === 404) throw new Error('The upload paused for too long and Google cancelled it. Please try again.');
      if (!retryable(e) || ++failures > RETRIES) throw e;
      await new Promise((resolve) => setTimeout(resolve, (2 ** (failures - 1) + Math.random()) * 1000));
      lost = true;
      continue;
    }
    failures = 0;
    lost = false;
    if (response.status !== 308) {                  // 200 or 201: Google has the whole video
      const { id, name: saved, webViewLink } = await response.json();
      onProgress?.(blob.size, blob.size);
      return { id, name: saved, webViewLink };
    }
    offset = kept(response.headers.get('Range'));
    onProgress?.(offset, blob.size);
  }
}

// Google's Range header says which bytes it kept ("bytes=0-1048575"); no header means none yet.
const kept = (range) => {
  const last = /^bytes=0-(\d+)$/.exec(range ?? '')?.[1];
  return last === undefined ? 0 : Number(last) + 1;
};

const retryable = (e) => e.status === 0 || e.status === 429 || e.status >= 500 || /rateLimitExceeded/.test(e.reason);

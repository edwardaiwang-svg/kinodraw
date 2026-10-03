// Stand-ins for everything the Classroom side of the extension talks to: the Classroom web page, the
// Classroom API, Drive's resumable uploads and KinoDraw Cloud. tests/e2e/google.mjs answers every web
// request of the browser with handle(); `log` records what each stand-in was asked.
import { createHash } from 'node:crypto';

export const ID = 'hoddalijnehhimlamfchabikgmjfgeoe';   // the extension id the pinned dev key gives
export const CODE = 'MTIzNDU2Nzg5MDEy';                // Room 12's class code (Classroom's: base64 of the course id)
export const OTHER_CODE = 'OTg3NjU0MzIxMDk4';          // a class Ms. Frizzle doesn't teach
export const ROOM12 = { id: '123456789012', name: 'Room 12 Science', section: 'Period 2', alternateLink: `https://classroom.google.com/c/${CODE}` };
const ART = { id: '555000111222', name: 'Art', section: '', alternateLink: 'https://classroom.google.com/c/NTU1MDAwMTExMjIy' };
const KiB256 = 256 * 1024;
const SESSION = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=fake-session';

export function fakes() {
  const log = {
    account: 'frizzle@school.test',   // who the Classroom page says is signed in
    courseLists: [],                  // { token, query } of each courses.list call
    materials: [],                    // { courseId, token, body } of each courseWorkMaterials.create call
    uploadStart: null,                // { token, headers, body } of the resumable upload's first request
    pieces: [],                       // { range, length } of each PUT to the upload session
    uploadProblems: [],               // anything the upload did that Google would refuse
    uploadSha: '',                    // SHA-256 of the bytes Google kept, once the upload is complete
    cloud: [],                        // { path, token, body } of each KinoDraw Cloud call
    unexpected: [],                   // requests no stand-in answers (they are aborted)
  };
  // The upload misbehaves on purpose: Google keeps only half of the first piece, then the next one fails.
  const trouble = ['keep-half', 'fail'];
  let kept = Buffer.alloc(0);
  let fileName = '';

  async function handle(route) {
    const request = route.request();
    const url = new URL(request.url());
    const token = (request.headers().authorization || '').replace(/^Bearer /, '');
    if (url.host === 'classroom.google.com') return route.fulfill({ contentType: 'text/html', body: classroomPage(log.account) });
    if (url.host === 'classroom.googleapis.com') return classroomApi(route, url, request, token);
    if (url.host === 'www.googleapis.com' && url.pathname === '/upload/drive/v3/files') return drive(route, url, request, token);
    if (url.host === 'api.doodlecloud.org') return doodleCloud(route, url, request, token);
    log.unexpected.push(`${request.method()} ${url.href}`);
    return route.abort();
  }

  function classroomApi(route, url, request, token) {
    if (request.method() === 'GET' && url.pathname === '/v1/courses') {
      log.courseLists.push({ token, query: Object.fromEntries(url.searchParams) });
      if (token === 'teacher-token') {   // two pages, Room 12 on the second
        return json(route, url.searchParams.get('pageToken') === 'page-2' ? { courses: [ROOM12] } : { courses: [ART], nextPageToken: 'page-2' });
      }
      if (token === 'student-token') return json(route, {});   // Google leaves "courses" out when there are none
      if (token === 'api-off-token') {
        return json(route, { error: { code: 403, message: '@ClassroomApiDisabled The user is not permitted to access the Classroom API.', status: 'PERMISSION_DENIED' } }, 403);
      }
      return json(route, { error: { code: 401, message: 'Request had invalid authentication credentials.', status: 'UNAUTHENTICATED' } }, 401);
    }
    const posting = /^\/v1\/courses\/([^/]+)\/courseWorkMaterials$/.exec(url.pathname);
    if (request.method() === 'POST' && posting) {
      const body = request.postDataJSON();
      log.materials.push({ courseId: posting[1], token, body });
      const id = `material-${log.materials.length}`;
      return json(route, { ...body, courseId: posting[1], id, alternateLink: `https://classroom.google.com/c/${CODE}/m/${id}/details` });
    }
    return json(route, { error: { code: 404, message: 'Not found' } }, 404);
  }

  function drive(route, url, request, token) {
    if (request.method() === 'POST') {
      const headers = request.headers();
      log.uploadStart = { token, query: Object.fromEntries(url.searchParams), headers, body: request.postDataJSON() };
      fileName = log.uploadStart.body.name;
      return route.fulfill({ status: 200, headers: { Location: SESSION }, body: '' });
    }
    const range = request.headers()['content-range'] || '';
    const body = request.postDataBuffer() ?? Buffer.alloc(0);
    log.pieces.push({ range, length: body.length });
    const asking = /^bytes \*\/(\d+)$/.exec(range);                    // "how much do you have?"
    const piece = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(range);
    const total = Number(asking ? asking[1] : piece?.[3]);
    if (!asking) {
      const [first, last] = [Number(piece?.[1]), Number(piece?.[2])];
      if (!piece || first !== kept.length) log.uploadProblems.push(`${range}: Google has ${kept.length} bytes`);
      if (body.length !== last - first + 1) log.uploadProblems.push(`${range}: ${body.length} bytes sent`);
      if (last + 1 !== total && body.length % KiB256) log.uploadProblems.push(`${range}: not a multiple of 256 KiB`);
      const mishap = trouble.shift();
      if (mishap === 'fail') return route.fulfill({ status: 503, body: 'Service Unavailable' });
      kept = Buffer.concat([kept, mishap === 'keep-half' ? body.subarray(0, Math.floor(body.length / 2 / KiB256) * KiB256) : body]);
    }
    if (kept.length === total) {
      log.uploadSha = createHash('sha256').update(kept).digest('hex');
      return json(route, { id: 'drive-file-1', name: fileName, webViewLink: 'https://drive.google.com/file/d/drive-file-1/view' }, 201);
    }
    return route.fulfill({ status: 308, headers: kept.length ? { Range: `bytes=0-${kept.length - 1}` } : {}, body: '' });
  }

  function doodleCloud(route, url, request, token) {
    const body = request.postDataJSON();
    log.cloud.push({ path: url.pathname, token, body });
    if (url.pathname === '/v1/edu/session') {
      return body.google_token === 'teacher-token'
        ? json(route, { token: 'cloud-token', plan: 'edu', remaining: 30, opus_remaining: 0, allowance_used: 0, period_end: 0 })
        : json(route, { error: 'KinoDraw for Classroom is for teachers' }, 403);
    }
    if (token !== 'cloud-token') return json(route, { error: 'sign in again' }, 401);
    if (url.pathname === '/v1/videos') return json(route, { video_id: 'video-1', model: 'gpt-6-luna', plan: 'edu', remaining: 29 });
    if (url.pathname === '/v1/direct') {
      return json(route, { section: { section_title: 'Volcanoes', beats: [{ beat_id: 'b001', visuals: [] }] }, usage: { model: 'gpt-6-luna' }, downgraded: false });
    }
    return json(route, { error: 'not found' }, 404);
  }

  return { log, handle };
}

// KinoDraw Cloud sends no CORS headers, and neither do these: the extension's host permissions make them unnecessary.
const json = (route, data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });

const classroomPage = (email) => `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Room 12 Science</title>
<style>
  body { margin: 0; font: 14px Roboto, Arial, sans-serif; color: #3c4043; }
  header { display: flex; justify-content: space-between; align-items: center; height: 64px; padding: 0 24px; border-bottom: 1px solid #dadce0; font-size: 22px; }
  header a { width: 32px; height: 32px; border-radius: 50%; background: #e8710a; color: #fff; display: grid; place-items: center; text-decoration: none; font-size: 14px; }
  main { max-width: 1000px; margin: 24px auto; padding: 0 24px; }
  .banner { height: 220px; border-radius: 8px; background: #1967d2; color: #fff; display: flex; align-items: flex-end; padding: 24px; font-size: 36px; box-sizing: border-box; }
  .post { margin-top: 24px; padding: 16px 24px; border: 1px solid #dadce0; border-radius: 8px; }
</style></head>
<body>
  <header>Google Classroom (test stand-in)
    <a href="https://accounts.google.com/SignOutOptions?hl=en&amp;continue=https://classroom.google.com/" aria-label="Google Account: Valerie Frizzle  (${email})">V</a>
  </header>
  <main><div class="banner">Room 12 Science</div><div class="post">Announce something to your class</div></main>
</body></html>`;

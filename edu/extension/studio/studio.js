// The studio tab: sign in, the teacher check, the script, the video, then Drive + Classroom.
import { AuthError, getToken, signOut } from '../google/auth.js';
import { courseFromCode, listTeachingCourses, postMaterial } from '../google/classroom.js';
import { directSection, eduSession, openVideo } from '../google/cloud.js';
import { uploadVideo } from '../google/drive.js';
import { makeVideo, readScript } from '../engine/pipeline.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const hint = params.get('email') || undefined;
const VIEWS = ['loading', 'signin', 'blocked', 'make', 'progress', 'done', 'error'];
const STAGES = [
  ['load', 'Getting the drawing kit ready'],
  ['plan', 'Planning the pictures'],
  ['voice', 'Recording the voice'],
  ['pace', 'Timing the drawings to the words'],
  ['audio', 'Mixing the voice and music'],
  ['draw', 'Drawing the video'],
  ['upload', 'Saving it to your Google Drive'],
  ['post', 'Adding it to your class'],
];

let session = null;          // { token, email, courses, cloud }
let controller = null;
let videoUrl = null;

function show(name) {
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== name;
}

function fail(error) {
  console.error(error);
  $('error-text').textContent = friendly(error);
  show('error');
}

function friendly(error) {
  if (error?.name === 'AbortError') return 'You stopped the video. Nothing was posted.';
  return error?.message || String(error);           // Google and KinoDraw Cloud errors already say what to do
}

// ------------------------------------------------------------------ sign-in and the teacher check
async function start() {
  show('loading');
  try {
    await signedIn(await getToken({ interactive: false, loginHint: hint }));
  } catch (error) {
    if (error instanceof AuthError) show('signin');
    else fail(error);
  }
}

async function signedIn({ token, email }) {
  show('loading');
  $('account-email').textContent = email;
  $('account').hidden = false;
  const courses = await listTeachingCourses(token);
  if (!courses.length) {
    $('blocked-why').textContent = `${email} doesn't teach any active Google Classroom classes.`;
    show('blocked');
    return;
  }
  session = { token, email, courses, cloud: null };
  const select = $('course');
  select.replaceChildren(...courses.map((c) => new Option(c.section ? `${c.name} · ${c.section}` : c.name, c.id)));
  const wanted = params.get('course') ? courseFromCode(courses, params.get('course')) : null;
  if (wanted) select.value = wanted.id;
  show('make');
}

async function cloudFor(token) {
  // GPT-6 Luna through KinoDraw Cloud: KinoDraw Cloud checks for itself that this account teaches a class.
  if (!session.cloud) {
    try {
      const { token: cloudToken } = await eduSession(token);
      session.cloud = {
        openVideo: (o) => openVideo(cloudToken, o),
        directSection: (videoId, payload) => directSection(cloudToken, videoId, payload),
      };
    } catch (error) {
      console.warn('KinoDraw Cloud unavailable:', error);
      return null;
    }
  }
  return session.cloud;
}

$('signin').onclick = async () => {
  try {
    await signedIn(await getToken({ interactive: true, loginHint: hint }));
  } catch (error) {
    if (error instanceof AuthError) show('signin');
    else fail(error);
  }
};

for (const id of ['signout', 'blocked-signout']) {
  $(id).onclick = async () => {
    await signOut();
    session = null;
    $('account').hidden = true;
    show('signin');
  };
}

// ------------------------------------------------------------------ the script
let chosenFile = null;
$('file').onchange = (e) => {
  chosenFile = e.target.files[0] || null;
  $('file-name').textContent = chosenFile ? chosenFile.name : 'Word (.docx), text (.txt) or Markdown (.md)';
  if (chosenFile) $('script').value = '';
  estimate();
};
$('script').oninput = () => {
  if ($('script').value.trim()) {
    chosenFile = null;
    $('file').value = '';
    $('file-name').textContent = 'Word (.docx), text (.txt) or Markdown (.md)';
  }
  estimate();
};

function estimate() {
  const words = $('script').value.split(/\s+/).filter(Boolean).length;
  const minutes = Math.max(1, Math.round(words / 80));     // about 80 words a minute, with the pauses for the drawing
  $('estimate').textContent = chosenFile ? '' : words
    ? `About ${words} words · roughly ${minutes} minute${minutes > 1 ? 's' : ''} of video` : '';
}

// ------------------------------------------------------------------ making it
function stagesView() {
  $('stages').replaceChildren(...STAGES.map(([key, text]) => {
    const li = document.createElement('li');
    li.dataset.stage = key;
    li.textContent = text;
    return li;
  }));
}

function progress(stage, done = 0, total = 1, note = '') {
  const at = STAGES.findIndex(([k]) => k === stage);
  document.querySelectorAll('#stages li').forEach((li, i) => {
    li.className = i < at ? 'done' : i === at ? 'active' : '';
    li.querySelector('.detail')?.remove();
    if (i === at && total > 1) {
      const span = document.createElement('span');
      span.className = 'detail';
      span.textContent = stage === 'load' && total > 1e5 ? `${Math.round(done / 1e6)} of ${Math.round(total / 1e6)} MB`
        : `${Math.min(100, Math.round(done / total * 100))}%`;
      li.append(span);
    }
  });
  const within = total ? Math.min(1, done / total) : 0;
  $('meter').style.width = `${Math.round((at + within) / STAGES.length * 100)}%`;
}

$('make').onclick = async () => {
  const course = session.courses.find((c) => c.id === $('course').value);
  let board;
  try {
    board = await readScript({ text: $('script').value, file: chosenFile, title: $('title').value.trim() });
  } catch (error) {
    alertInline(error.message);
    return;
  }
  const state = document.querySelector('input[name=state]:checked').value;
  const quality = document.querySelector('input[name=quality]:checked').value;
  controller = new AbortController();
  stagesView();
  show('progress');
  try {
    session.token = (await getToken({ interactive: false, loginHint: session.email }).catch(() => session)).token;
    const cloud = await cloudFor(session.token);
    const made = await makeVideo(board, { cloud, voice: $('voice').value, quality, signal: controller.signal,
      onProgress: ({ stage, done, total }) => progress(stage, done, total) });
    const title = board.title.en;
    // A long video can outlast the Google sign-in (one hour): refresh it before uploading.
    const { token } = await getToken({ interactive: false, loginHint: session.email }).catch(() => getToken({ interactive: true, loginHint: session.email }));
    progress('upload', 0, 1);
    const file = await uploadVideo(token, made.blob, { name: `${title}.mp4`, onProgress: (done, total) => progress('upload', done, total) });
    progress('post');
    const material = await postMaterial(token, course.id, { title, state, driveFileId: file.id,
      description: 'A hand-drawn video made with KinoDraw for Classroom.' });
    finished({ made, course, file, material, state });
  } catch (error) {
    fail(error);
  } finally {
    controller = null;
  }
};

$('stop').onclick = () => controller?.abort();

function finished({ made, course, file, material, state }) {
  if (videoUrl) URL.revokeObjectURL(videoUrl);
  videoUrl = URL.createObjectURL(made.blob);
  $('preview').src = videoUrl;
  $('download').href = videoUrl;
  $('download').download = `${made.board.title.en}.mp4`;
  const draft = state === 'DRAFT';
  $('done-title').textContent = draft ? 'Your video is saved as a draft' : 'Your video is in your class';
  $('done-where').textContent = draft
    ? `It's a draft in ${course.name}'s Classwork, so only you can see it until you post it.`
    : `Your students can watch it in ${course.name}'s Classwork. It's also in your Google Drive.`;
  const link = material.alternateLink || course.alternateLink || file.webViewLink;
  $('open-classroom').href = link;
  $('open-classroom').textContent = material.alternateLink ? 'Open in Classroom' : 'Open the class';
  $('done-notes').textContent = made.notes.filter((n) => n.startsWith('The AI helper')).join(' ');
  show('done');
}

$('again').onclick = () => show('make');
$('retry').onclick = () => (session ? show('make') : start());

function alertInline(message) {
  $('estimate').textContent = message;
  $('estimate').style.color = 'var(--red)';
  setTimeout(() => { $('estimate').style.color = ''; estimate(); }, 6000);
}

start();

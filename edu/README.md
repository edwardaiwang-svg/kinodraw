# Doodle Studio for Classroom

A Chrome extension for elementary-school teachers. Open one of your Google Classroom classes, click
**Make a doodle video**, give it a short script, and it makes a hand-drawn whiteboard video (a drawing
hand, cartoon doodles, a friendly narrator's voice, captions and music) and adds it to that class's
Classwork. Kids watch it in Classroom like any other material.

- **Made in Chrome.** No app to install: the drawing, the voice and the video encoding all run in the
  extension, on the teacher's computer.
- **For teachers only.** The button appears only on classes the signed-in Google account teaches, and the
  AI helper checks again on its server. Students never see it.
- **Built on Doodle Studio's rules.** The same director as the desktop app decides what to draw and when
  (every word written on the board is said as it is written; lists draw every item; no religious
  imagery or scientist figures). GPT-6 Luna, through Doodle Cloud, suggests pictures on top of those
  rules; it is the only AI model the classroom version uses.

Why Google Classroom: it is the most-used learning platform in US K–12 and where grades 3–5 teachers
post work; Seesaw (strong in PreK–2) has no public API for posting, so it would come second.

## How a teacher uses it

No terminal, nothing to download but the extension: teachers install it from the Chrome Web Store with **Add to
Chrome** (or their school's IT installs it for them), and a welcome page shows the three steps. The teacher page is
[docs/classroom](../docs/classroom/index.html) (published on the project site); how to publish the extension is in
[STORE.md](STORE.md).

1. Install the extension, open **classroom.google.com**, and open a class you teach.
2. Click **Make a doodle video** (bottom right). The Doodle Studio tab opens with that class chosen.
3. Sign in with Google (the account you teach with) the first time.
4. Choose a Word (.docx), text or Markdown file, or paste the script. Headings (`#`, `##` or Word's
   Heading styles) split the video into parts; each part ends with its key idea on a sticky note.
5. Pick a voice and whether the video posts straight away or waits as a draft, then **Make my video**.
6. Keep the tab open while it works (a 3-minute script takes a few minutes the first time, while the
   voice and picture models download; later videos are faster). The video is saved to your Google Drive
   and added to the class's Classwork, with a link to it.

## Setup (once, by the owner)

### 1. Build the extension

```
cd edu
npm install
node tools/build.mjs          # vendors the JS/WASM libraries and exports the doodle library from the Python app
```

Load `edu/extension` in `chrome://extensions` (Developer mode → Load unpacked). The manifest's `key` pins
the extension id to `hoddalijnehhimlamfchabikgmjfgeoe` so the Google sign-in redirect below stays valid.
`node tools/build.mjs --zip` writes the Chrome Web Store zip to `edu/dist/` (without the `key`: the store assigns
its own id). CI builds the same zip on every push (the **doodle-studio-classroom** artifact).

### 2. Google sign-in (Google Cloud console)

1. Create a Cloud project and enable the **Google Classroom API** and the **Google Drive API**.
2. Google Auth Platform → **Branding**: app name, support email, and a home page and privacy policy
   ([PRIVACY.md](PRIVACY.md)) on a domain verified in Search Console (e.g. doodlecloud.org, also added as an
   authorized domain).
3. **Audience**: External. Start in **Testing** with up to 100 test users (in Testing, a sign-in expires 7 days
   after consent).
4. **Data access**: exactly the four scopes in `extension/config.js` (`classroom.courses.readonly` and
   `classroom.courseworkmaterials` are sensitive; `drive.file` and `userinfo.email` are not).
5. **Clients** → Create client → **Web application**, with the authorized redirect URI exactly
   `https://hoddalijnehhimlamfchabikgmjfgeoe.chromiumapp.org/` (trailing slash included). No JavaScript origins;
   the client secret is never used. Add one more `https://<id>.chromiumapp.org/` for each store listing's id.
6. Put the client id (public, not a secret) in `extension/config.js` (`googleClientId`) and in Doodle Cloud's
   `wrangler.toml` (`GOOGLE_CLIENT_ID`).
7. Before a public launch, Google has to verify the app (the Classroom scopes are sensitive): brand verification,
   then a reason for each scope and a video of the sign-in. Until then teachers see an "unverified app" screen and
   at most 100 can sign in.

### 3. Doodle Cloud (GPT-6 Luna)

The `/v1/edu/session` endpoint and the Luna-only `edu` plan are in `~/test/doodle-cloud` (no database migration,
no new secrets). With `GOOGLE_CLIENT_ID` set in `wrangler.toml`:

```
cd ~/test/doodle-cloud
npm test
npm run deploy
curl -s -X POST https://api.doodlecloud.org/v1/edu/session -H 'content-type: application/json' -d '{"google_token":"test"}'
```

The last line should answer `{"error":"sign in with Google again"}`; a 503 means the client id is still empty.
Until Doodle Cloud answers, the extension still makes videos: the built-in rules plan the pictures on their own.

## For school IT admins

- In the Google Admin console, allow the app under Security → Access and data control → API controls → App access
  control (apps that are not configured are blocked for accounts marked under 18, which K–12 domains often apply
  to everyone), and keep Apps → Google Workspace → Classroom → Data access → Classroom API on.
- Install the extension for staff only (force-install to a teachers' organizational unit). Students would never
  get past the teacher check, but a signed-out student would see a small "Sign in" chip on Classroom.

## Computers

Chrome on any computer that can run Classroom. With WebGPU (most computers from the last few years) the voice is
made faster than it is spoken. Without it the voice runs on the processor: 2–3× slower than real time on a fast
laptop and slower on a Chromebook, so a 3-minute video can take 10 minutes or more there. The first video also
downloads the voice and picture models (about 400 MB with WebGPU, 160 MB without), once.

## Privacy

- The video is made on the teacher's computer. The script's sentences are sent to Doodle Cloud, which
  asks GPT-6 Luna (OpenAI's API) to suggest pictures; Doodle Cloud does not store script text (only
  counts and costs). No student data is read: the extension only lists the classes the teacher teaches.
- Google permissions: `classroom.courses.readonly` (which classes you teach), `classroom.courseworkmaterials`
  (post the video), `drive.file` (save the video; Doodle Studio can only see files it made), and your email.

## Developing

| Command | What |
|---|---|
| `npm test` | unit and parity tests: the JS port against the Python app's output, media, Google side |
| `node tests/e2e/google.mjs` | the Classroom button, teacher check, Drive upload and posting, all mocked, in headless Chromium |
| `node tests/e2e/pipeline.mjs` | the whole teacher flow in the real extension, Google and Doodle Cloud mocked |
| `node tests/e2e/media.mjs` | the voice (WebGPU, and the Chromebook path: WASM voice and AAC), mixing and MP4 encoding in headless Chromium |
| `node tests/e2e/rules.mjs` | the render rules checked on the JS engine in headless Chromium |
| `node tests/e2e/render.mjs printing_press 10,30,60` | stills from the JS renderer, for comparing with the desktop app |
| `../.venv/bin/python tools/export_parity.py` | refresh the parity fixtures after changing the Python rules |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the layout and the module contracts. The Python app in
`kinodraw/` is the source of truth for the rules; change them there first, export the parity fixtures,
then make the JS port match (`tests/rules.test.mjs` fails until it does).

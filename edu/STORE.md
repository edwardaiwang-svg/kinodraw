# Publishing to the Chrome Web Store

Teachers install KinoDraw for Classroom from the Chrome Web Store with **Add to Chrome**, or their school's IT
installs it for them. Nobody needs a terminal. This page is the owner's checklist, all in the browser.

## 1. The package

`dist/kinodraw-classroom-<version>.zip`. GitHub builds it on every push: open the repository's **Actions** tab,
the latest **CI** run, and download **kinodraw-classroom** under Artifacts (unzip that once; inside is the zip to
upload). It has no `"key"` in its manifest: the store refuses one and gives the extension its own id.

## 2. Create the item

1. Open the [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole) with the Google
   account that will own the listing (a one-time $5 registration the first time).
2. **New item** → upload the zip.
3. Copy the item's **ID** (32 letters, shown at the top of the item page).
4. Google Cloud console → Google Auth Platform → **Clients** → KinoDraw for Classroom → **Authorized redirect
   URIs** → **Add URI** → `https://<the item ID>.chromiumapp.org/` → **Save**. Without it, sign-in fails in the store
   version (the development id stays listed too).

## 3. Store listing tab

- **Description:**

  > KinoDraw for Classroom turns your lesson script into a hand-drawn whiteboard video, read aloud by a friendly
  > narrator, and adds it to your Google Classroom class.
  >
  > Open a class you teach, click "Make a doodle video", and paste your script or choose a Word or text file.
  > KinoDraw draws a cartoon picture for what is said as it is said, writes each section's key idea on a sticky
  > note, adds captions and gentle music, then saves the video to your Google Drive and posts it to your class (or
  > keeps it as a draft for you to check first).
  >
  > - Made for elementary classrooms: every word on the board is said as it is written, lists are drawn in full, and
  >   the pictures are simple cartoon doodles.
  > - For teachers only: the button appears only on classes you teach. Students just watch the video in Classwork.
  > - Private by design: the video is made on your computer. KinoDraw never reads your students' names, work or
  >   grades.
  > - Nothing else to install: the drawing, the voice and the video are all made in Chrome.

- **Category:** Education. **Language:** English.
- **Store icon:** `extension/icons/icon128.png`.
- **Screenshots** (1280×800), in this order: `store/1-video.png`, `store/2-make.png`, `store/3-progress.png`,
  `store/4-done.png`, `store/5-welcome.png`.
- **Small promo tile** (440×280): `store/promo-440x280.png`.
- **Homepage URL:** `https://edwardaiwang-svg.github.io/kinodraw/classroom/`
- **Support URL:** `https://github.com/edwardaiwang-svg/kinodraw/issues`

## 4. Privacy practices tab

- **Single purpose:** Make a hand-drawn explainer video from a teacher's lesson script and post it to one of that
  teacher's Google Classroom classes.
- **Permission justifications:**
  - `identity`: signs the teacher in with Google to see which Classroom classes they teach, save the video to their
    Google Drive and post it to their class.
  - `storage`: keeps that sign-in, and whether the account teaches the open class, in memory for the browser session.
  - `unlimitedStorage`: keeps the downloaded voice and picture-search models (a few hundred MB) so later videos start
    quickly.
  - Host `classroom.googleapis.com`: lists the classes the teacher teaches and posts the video to Classwork.
  - Host `www.googleapis.com`: uploads the video to the teacher's Drive and reads which Google account signed in.
  - Host `oauth2.googleapis.com`: withdraws the Google sign-in when the teacher signs out.
  - Host `api.doodlecloud.org`: KinoDraw's own service, which checks the account teaches a class and asks
    GPT-6 Luna to suggest pictures for the script.
  - Hosts `huggingface.co`, `*.hf.co`: download the voice and picture-search model files, once.
  - Content script on `classroom.google.com`: shows the "Make a doodle video" button on class pages the teacher
    teaches.
- **Remote code:** No. Every script and WebAssembly file is in the package; the downloaded models are data files.
- **Data usage:** check *Personally identifiable information* (the teacher's email address), *Authentication
  information* (the Google sign-in) and *Website content* (the script text sent for picture suggestions). Check all
  three certifications (not sold, not used for unrelated purposes, not used for credit).
- **Privacy policy URL:** `https://edwardaiwang-svg.github.io/kinodraw/classroom/privacy.html`

## 5. Distribution and submit

- **Visibility:** *Unlisted* at first (anyone with the link can install; it doesn't show in search). Switch to
  *Public* once Google has verified the sign-in (step 6).
- **Submit for review.** Reviews usually take a few days. After approval, put the item's store link on the teacher
  page (`docs/classroom/index.html`, the "Add to Chrome" button).

## 6. Who can sign in

While the Google sign-in is in **Testing**, only the accounts listed under Google Auth Platform → **Audience** →
**Test users** can sign in (up to 100): add each teacher's Google account there. To open it to every teacher,
**Publish app** on the Audience page and complete Google's verification (the Classroom permissions are "sensitive":
Google asks why each is needed and for a short video of the sign-in; the home page and privacy policy then have to be
on a domain you have verified, such as doodlecloud.org).

## For a school's IT team

- Install for teachers only: Google Admin console → Devices → Chrome → Apps & extensions → Users & browsers → the
  teachers' organizational unit → **+** → Add from Chrome Web Store → the item ID → **Force install** (and pin to the
  toolbar).
- Allow the sign-in: Security → Access and data control → API controls → App access control → Configure new app →
  OAuth App Name Or Client ID `292748984382-7uf3qe28fadngtjln2p6e77jgmmf87qi.apps.googleusercontent.com` → Trusted.
- Keep Apps → Google Workspace → Classroom → Data access → Classroom API on.

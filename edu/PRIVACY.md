# KinoDraw for Classroom: privacy policy

_Published at https://edwardaiwang-svg.github.io/kinodraw/classroom/privacy.html (keep the two in step)._

KinoDraw for Classroom is a Chrome extension for teachers. It turns a lesson script the teacher
writes into a hand-drawn video and adds it to one of the teacher's Google Classroom classes.

## What it reads

- **Your script**, which you type, paste or choose as a file. It stays on your computer, except its
  sentences are sent to KinoDraw Cloud (below) so GPT-6 Luna can suggest pictures.
- **Your Google account's email and the list of classes you teach** (name, section and link), from the
  Google Classroom API. They are used only to show you your classes and to check that you are a teacher.
  The extension does not read rosters, students' names, work, grades or messages.
- **Google Classroom pages you visit**, only to learn which class is open (the class code in the address)
  so it can show the "Make a doodle video" button there. Nothing on those pages is stored or sent anywhere.

## What it sends, and to whom

| Where | What | Why |
|---|---|---|
| Google Drive (your account) | the finished video file | so your class can watch it; the extension can only see files it created |
| Google Classroom (your class) | a Classwork material with the video attached | to post it, as a draft or published, as you choose |
| KinoDraw Cloud (`api.doodlecloud.org`, run by KinoDraw) | your Google sign-in token (checked with Google, never stored), then the script's sentences, section titles and the names of candidate doodles | to confirm you teach a class and ask GPT-6 Luna for picture suggestions |
| OpenAI (GPT-6 Luna), through KinoDraw Cloud | the same sentences and doodle names | to suggest pictures; OpenAI's API terms apply |
| Hugging Face | nothing about you: the extension downloads the voice and picture-search models from it | to make the video on your computer |

KinoDraw Cloud stores your email, your plan and counts of videos and AI costs, so it can keep usage within
the free allowance. It never stores your script, the suggestions, your Google token or the video.

## What stays on your computer

The drawing, the voice, the music mix and the video encoding all happen inside Chrome on your computer.
Your sign-in is kept in memory only while Chrome is open, and the downloaded models are kept in the
extension's own storage; uninstalling the extension removes them.

## Children

The extension is for teachers. It checks that the signed-in account teaches an active Google Classroom
class before it does anything, and it never collects information from or about students.

## Contact

Questions: the project's GitHub page, https://github.com/edwardaiwang-svg/kinodraw

# Why Google Classroom, and what shaped the extension

Research done 2026-09-26 (web sources below; vendor claims marked as such).

## Which platform do elementary students use?

There is no single "Canvas of elementary school". Elementary has two layers:

- **Google Classroom is the most-used LMS in US K–12**, and where grades 3–5 teachers post work.
  - #1 LMS in every LearnPlatform/Instructure *EdTech Top 40* from 2020–21 to 2024–25 (browser telemetry
    from 3.7 million students in 2024–25): [District Administration, 2025](https://districtadministration.com/article/edtech-top-40-ranking-highlights-tools-you-could-be-using/)
  - 31% of K–12 LMS deployments, ahead of Canvas (24%) and Schoology (19%): [ListEdTech, May 2026](https://listedtech.com/blog/k-12-lms-market-update-insights-may-2026/)
  - 54% of K–12 teachers said Classroom was their school's LMS (Canvas 28%): [MDR survey of 996 teachers, 2020](https://essentials.edmarket.org/2021/07/how-2020-shifted-perceptions-of-technology-in-the-classroom/)
  - Vermont (one of the few states that asks): 77% of schools named Google Classroom in 2020; in 2024,
    85% of districts use Google Workspace and Classroom: [VT AOE 2024](https://education.vermont.gov/sites/aoe/files/documents/edu-annual-technology-survey-report-2024.pdf)
  - It runs on the Chromebooks most schools use (82% of student devices in Washington districts):
    [WA OSPI](https://ospi.k12.wa.us/policy-funding/school-technology/annual-state-technology-survey)
- **Seesaw is the one platform built only for elementary (PreK–6)**, strongest in PreK–2, and usually used
  *next to* another LMS ("in each case was listed in addition to another LMS", Vermont 2024). Vendor claim:
  "over a third of elementary schools in the US" ([App Store listing](https://apps.apple.com/us/app/seesaw/id930565184)).
  Districts often split by grade, e.g. Seesaw for PreK–2 and Canvas for 3–12 ([Arlington ISD](https://www.aisd.net/district/resources/classlink/)).
- **ClassDojo** reaches most K–8 schools (vendor claim: 95%) but is mainly family communication.
  **Clever** is a login portal, not a place to post videos.

**Decision:** build for **Google Classroom first**. It has an official API that can post a video to a
class and can tell teachers from students. **Seesaw second**, if PreK–2 reach matters: it has no public API
for posting, so it would mean scripting the teacher's web app, which its terms restrict. Canvas (incl.
Canvas for Elementary) third, for large districts.

## What shaped the design

| Finding | Design |
|---|---|
| Classroom API: `courses.list?teacherId=me` lists the classes an account teaches; "can create classes" is not proof (admins may let students create classes); `verifiedTeacher` is false outside Workspace for Education | Teacher gate = at least one active class taught, and the open class must be one of them. KinoDraw Cloud repeats the check on its server before any AI call |
| Posting: `courseWorkMaterials.create` with a Drive file, `shareMode: VIEW` | Video → the teacher's Drive (`drive.file` scope, resumable upload) → a Classwork material, published or draft |
| All Classroom scopes are "sensitive": Google must verify the app before public launch (100-user cap until then; "Testing" mode tokens expire after 7 days) | Minimal scopes; privacy policy in [PRIVACY.md](PRIVACY.md); verification is a launch step |
| K-12 domains treat anyone not marked 18+ as under 18, and under-18 accounts can't use unconfigured apps (since Oct 2023) | District IT may need to allow the OAuth client for staff (see README) |
| WebCodecs exists in pages and dedicated workers, not in an extension's service worker | The video is made in an extension tab |
| MV3 forbids remote code; model weights are data | Every JS/WASM file is bundled; models download once from Hugging Face (pinned, checksummed where possible) |
| `kokoro-js` pulls in espeak-ng (GPL) and gives no word timings; **HeadTTS** (MIT) runs the same Kokoro model with word timings | HeadTTS for the voice |
| Chrome has no AAC encoder on ChromeOS/Linux, and Drive officially plays H.264 + AAC | AAC from WebCodecs where it exists, else Mediabunny's WASM AAC encoder |
| Better Canvas is AGPL with a no-commercial clause | Only its architecture (a content script that adds UI to the LMS page) is mirrored; all code is new |

Full notes with every source: [research/platform.md](research/platform.md) and [research/extension-tech.md](research/extension-tech.md).

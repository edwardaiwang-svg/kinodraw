# storyboard.json

Each project folder holds a `storyboard.json`. You can edit it by hand or in Studio; `kinodraw voice`, `kinodraw render` and `kinodraw finish` pick up your edits. Each save is checked by `kinodraw/director/validate.py`.

## Top level

```json
{
  "version": 1,
  "lang": "en",
  "title": {"en": "How the Printing Press Changed the World"},
  "subtitle": {"en": "optional second line on the title board"},
  "byline": {"en": "optional: a date or author line"},
  "narrator": "narrator",
  "music": true,
  "footer": {"en": "optional small print on every board"},
  "ui": {"en": {"agenda": "What we'll cover", "takeaway": "KEY TAKEAWAY", "thanks": "Thanks for watching"}},
  "look": "whiteboard",
  "story": "explain",
  "motion": "lively",
  "brand": {"name": "Friendr", "url": "friendr.nl", "cta": "Try it for free"},
  "chapters": [],
  "beats": []
}
```

- `narrator`: `"none"` hides the character. Any other value is a prefix, and poses are looked up as `<prefix>_wave`, `<prefix>_head`, `<prefix>_present`, `<prefix>_thumbs`, and so on (see "Your own doodles" below).
- `music`: `true`, `false`, or `{"primary": "fresh_focus", "secondary": "natural_vibes"}`.
- `host`: optional, `{"photo": "photos/me.jpg", "badge": {"en": "Name · role"}}`. It adds a photo badge to the title board and end card.
- `look`, `story`, `motion`: the direction dials, all optional. `look` is `whiteboard` (the default: the hand-drawn board, which ignores the other dials), `collage` or `bold`. `story` is `explain` (the default), `promo`, `story` or `showcase`. `motion` is `calm`, `lively` (the default) or `showreel`. See "Direction" below.
- `brand`: optional, `{"name", "url", "cta", "reveal"}`, all text; `"reveal": "hand"` has the drawing hand write the name. Without it the brand is found in the script: a domain such as `friendr.nl`, or a name said twice that the title or a "Meet X" backs up.

## Chapters

There are five kinds of chapter:

| kind | what it is |
|---|---|
| `intro` | The title board, drawn automatically. |
| `agenda` | One card per section, each drawn as its agenda beat is spoken. |
| `section` | A numbered section. It opens with a zoom into its card and ends with a takeaway note that pins back onto the agenda. |
| `board` | A plain chapter (for example the intro text before the agenda). |
| `outro` | The ending, followed by the end card. |

A section has these fields:

- `number`
- `label`, e.g. `{"en": "Part 1"}`
- `title` (shown on its agenda card)
- `hook` (optional short teaser)
- `color`, one of orange, blue, green, purple, red or teal (cycled automatically when absent)

## Beats

A beat is one breath of narration: about 35 words, or 70 Chinese characters.

```json
{
  "id": "b006", "chapter": "s1", "kind": "narration",
  "display": {"en": "Around 1450, Johannes Gutenberg…"},
  "spoken":  {"en": "Around fourteen fifty, Johannes Gutenberg…"},
  "visuals": []
}
```

- `display` is shown in the captions. `spoken` is what the voice says: the same words, with numbers written out. Clause punctuation must match between the two, because captions are cut at it.
- `kind` is one of `title`, `agenda`, `narration`, `take` or `closing`. A `take` beat ends a section and carries `"take": {"headline": {"en": "…"}}`, the text of its sticky note.
- `music: true` puts a light music bed under the beat.

## Visuals

Every visual has a unique `id` and a `type`. It can also have a `trigger`, `{"en": "<words from spoken>"}`: drawing starts when those words are heard, and the default is the start of the beat. If the hand is still busy 3 seconds after that, the visual is skipped rather than drawn late, and `kinodraw render` lists it in its warnings. Text fields are language maps (`{"en": "…"}`).

Visuals that take one cell of the board (1–3 per screen):

- `cluster`: `items: [{doodle, label?, trigger?}]` (1–3 doodles), `relation: none | arrow | plus | vs | equals`.
- `stat`: `value`, `label`, optional `kinodraw`. A big handwritten number.
- `quote`: `text`, `who`. A handwritten quote card (wide).
- `glossary`: `term`, `text`. A yellow sticky note.

Visuals that take the whole board (the camera moves to a new page):

- `bars`: `title`, `unit`, `rows: [{label, value, display, trigger}]`.
- `grid100`: `title`, `filled` (0–100), `legend: [{text, kind: filled}]`.
- `lanes` (timeline): `title`, `lanes: [{label, events: [{pos 0–1, display, label, trigger}]}]`.
- `flow`: `title`, `layout: chain | loop`, `nodes: [{id, label, doodle?, trigger}]`, `edges: [{from, to}]`.
- `split`: `left` / `right`, each `{who, text, doodle?, trigger}`, plus an optional `verdict: {text}`.
- `range`, `ladder`, `levels`, `zones`, `table`, `dial`, `calendar`, `coins`: see the builders in `kinodraw/engine/pages_*.py`.

`emphasis` circles, underlines or strikes part of an earlier visual: `target: "<visual id>[.<index>]"`, `kind: circle | underline | strike | highlight`.

## Direction

The collage and bold looks turn every sentence into a scene from a fixed template library and animate it with an energy from 0 to 3. `kinodraw/director/annotate.py` plans this without any AI: `annotate(board)` writes a `direction` list on every title, opener, narration, take and closing beat, one entry per sentence, and `plan(board, timeline)` fits the energies to the motion dial (run it again once the voice timing is known; without a timeline it assumes 15 characters a second).

```json
"direction": [
  {"i": 1, "span": [27, 40], "role": "brand", "energy": 3, "scene": "brand_reveal", "emphasis": "Friendr",
   "options": {"scene": ["brand_reveal", "brand_endcard", "sticker_row"], "emphasis": ["Friendr", "With Friendr"],
               "energy": [2, 3]},
   "source": "rules"}
]
```

- `i` is the sentence's index in the beat, and `span` its characters in `display` (split as captions are).
- `role`: `hook`, `question`, `problem`, `turn`, `brand`, `step`, `feature`, `channels`, `social`, `mechanic`, `use_cases`, `list`, `number`, `quote`, `reveal`, `tagline`, `cta`, `end_line` or `none`. A `step` also has `n`, its number in the video.
- `energy`: 0 still, 1 calm, 2 lively, 3 a showpiece.
- `scene`: one of `options.scene`, which offers 2–3 templates from the look's library with the rules' pick first (the whiteboard has only `board`).
- `emphasis`: the key phrase shown big, cut from the sentence (at most three words): one of `options.emphasis`, or empty.
- `options`: what an AI may later choose from, by index. `energy` is `[low, high]`.
- `source`: `rules`, or `user` for an entry you set by hand. Annotating again never changes a `user` entry, and planning only reports where it breaks the dial.

| look | story | scenes |
|---|---|---|
| whiteboard | any | board |
| collage | promo, showcase | chat_pileup, chaos, brand_reveal, step_card, share_link, rsvp, feature_chips, threshold, use_case_grid, brand_endcard, script_page, app_paste, app_press, hand_draws, sticker_row |
| collage | story, explain | title_question, crowd, stack, sky_speech, room_reaction, journey, document_reveal, collect, moodboard, box_reveal, tools_idea, assemble, end_line, sticker_row |
| bold | any | slam_line, bracket_focus, count_up, marquee_rings, morph, particle_assemble, iris_end |

| motion | time at energy 2 or more | showpieces (energy 3) |
|---|---|---|
| calm | none: nothing above 1 | none |
| lively | at most 20% | at most 2 |
| showreel | at most 45% | at most 5 |

On every dial, showpieces are at least 12 seconds apart; the 3 seconds after a sentence at 2 or more stay at 1 or less, unless the sentences go on with the same list or cascade ("No app. No account."); and a sentence reaches 2 only with an emphasis of at most four words. When something has to give, the anchors (the first hook, the brand reveal, and the final call to action or end line) stay up longest.

## Your own voice

`project.json` (next to `storyboard.json`) can name a recording of you reading the script: `"recording": "recording.m4a"`, a path in the project folder or an absolute one. `kinodraw voice MyVideo --recording take.m4a` copies the file in (wav, m4a, mp3 or aiff) and sets the key; `--recording none` removes it and the Kokoro voice reads again.

Read every beat's `spoken` text in one take, at your own pace, with a pause between paragraphs. Kokoro still reads the script as a guide; the guide is aligned to your take, every beat is cut out of it at a pause, and the captions and drawings follow your words. `voice/recording-align.json` shows where each beat was found and how well it matched: about 0.35 for other words and 0.45 or more for a reading of the script, and beats under 0.4 are marked `check`. A take that is not a reading of this script is refused. A false start, a repeated sentence or an ad-lib stays in the beat it falls in (and the words around it may be timed a little off), so record that part again or edit it out of the take.

## Your own doodles

Put SVG files in the project's `doodles/` folder and reference them by file name (without `.svg`). They take precedence over the built-in library. For the drawing hand to trace them well, follow `kinodraw/assets/doodles/STYLE.md`.

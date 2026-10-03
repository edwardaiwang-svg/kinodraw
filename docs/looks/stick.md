# Look: stick-figure documentary

Status: preview renderer (`python -m doodlestudio.engine.stick.preview <project> -o out.mp4`). Not yet wired into
`make_production`, the Studio or a style registry.

Why this look: the most-watched explainer format on YouTube in the last 12 months is the long (10 to 20 minute),
16:9, MS-Paint-style stick-figure documentary on history, psychology, true crime and science. Searches for
"stick figure animation" grew 61% year on year, about three times faster than "whiteboard animation". Viewers
punish templated "AI slop", so the look has to read as hand-made and specific to the script.

## 1. Style study (2026-10-02)

Material: 12 public thumbnails and the seek-bar storyboard frames of 3 videos (The Paint Explainer x2, Ink
Explainer x1), saved under `/tmp/ds-stick-study/` only. Nothing from them is in this repository.

What makes the reference videos work:

| Element | What they do |
|---|---|
| Canvas | Stark white, or one flat full-bleed background per scene (a sky band over a ground band, a dark ocean). No paper texture and no vignette. |
| Line | One weight of thin black line (about 3 to 5 px at 1080p) for figures. Props carry a black outline and flat fills. Nothing is shaded except an occasional flat darker tone. |
| Figures | Circle head, single-line torso and limbs, no hands or feet. The head is large: about a quarter of the body in full shots, and close-ups crop at the chest so the face fills a third of the frame. |
| Faces | Most of the emotion is in the face: white eyes with dot pupils, eyebrows that tilt, a mouth that is a line, an arc or an open shape with a red inside. Sunglasses mark a villain. Short radiating ticks around the head mark shock. |
| Colour | Few, flat, saturated colours from a Paint-like palette. Figures stay white-headed; clothes and props carry the colour. |
| Emphasis | Red: thick curved arrows, hand-drawn circles, red text with a white outline ("Ceases to EXIST"); yellow outlined labels; speech bubbles with red text; a green check against a red cross on a split screen. |
| Text | A small persistent topic label (the current list item) in bold condensed caps at the top centre. Short labels next to things. Big statement cards ("CULTURE WAS BORN HERE") on plain white. |
| Density | One idea a shot: a figure plus one or two props, lots of white space. "Every X" videos open on a grid of framed panels, each with a caption under it. |
| Editing | Hard cuts, roughly every 2 to 5 seconds, on sentence boundaries. The camera does not move. Motion is limited: a figure walks across, a mouth flaps, a label appears. |
| Pacing | Fast, continuous narration with no dead air; the picture changes when the sentence changes. |

## 2. Our version

Our own look, not a copy of any channel. It shares the grammar (white canvas, thin black line, flat palette, red
emphasis, hard cuts) and differs in every element a viewer would recognise:

- **Header tab, top left** (not a centred caps label): a palette square with the part number, then the part title.
  It is drawn once per section and stays put, so a 15-minute video always says where you are.
- **Our figure, "Sticky"**: a big circle head (26% of the body), round-cap limbs with a slight bend at every joint
  (never ruler-straight), a stroke that scales with the figure (3 px for a full-height 600 px figure on a 1080p
  frame, never under 2.2 px, up to 5.5 px in close-ups),
  oval eyes with pupils that look at what matters, separate brows, and a mouth set (smile, grin, flat, o, frown,
  shout, wavy, teeth). Heads are always white, so the figure is everyone.
- **One accent colour per part**, from our 16-colour palette, on the header square, shirts and number underlines:
  each part of a long video has its own colour without becoming a rainbow.
- **A ground strip** along the bottom of every shot, in one colour per video picked by topic (tan for history,
  green for nature, light blue for sky and sea, light grey otherwise). It doubles as the bed for burned-in
  captions, so close-ups are cut at its top edge and captions never sit on a figure.
- **Emphasis in red, drawn live with a small pencil cursor**: wobbly circle, arrow, underline, cross-out, "?" and
  "!". Nothing else is drawn on camera; everything else is simply there at the cut, the Paint way.
- **Plain sans** for every word: Arimo Bold (Latin) and Noto Sans SC Bold (Chinese), both OFL and already bundled.
  Labels are black; emphasis words are red with a white outline.
- **Boil and twos**: every line wobbles between three seeded variants at 7.5 Hz and motion steps at 15 fps, so a
  still frame looks hand-drawn and nothing glides like a vector tween.
- **Hard cuts only**: a new shot per sentence or two (at least 2.2 s, at most about 8 s), never a pan or zoom.

### Palette (16)

| name | hex | use |
|---|---|---|
| black | #000000 | lines, text |
| white | #FFFFFF | canvas, heads |
| grey | #7F7F7F | secondary text, stone |
| silver | #C3C3C3 | ground (default), metal |
| red | #E8262D | emphasis only |
| maroon | #8B1A1A | dark red tones |
| orange | #FF8A1F | accent |
| yellow | #FFE11A | accent, gold |
| tan | #EFDDB0 | ground (history), skin of props |
| brown | #A86B45 | wood, earth |
| green | #2EA84F | accent, plants |
| lime | #B8E04A | ground (nature) |
| sky | #9AD7EE | ground (sky and sea), water |
| blue | #2F6FDB | accent |
| purple | #8E4BB0 | accent |
| pink | #F7A8C4 | accent, mouths |

Doodles from the shared library are redrawn in this look: outlines become black and thin (2.5 px at their
on-screen size, inner details thinner), and every fill snaps to the nearest palette colour (CIE Lab distance), so
the 1,700+ library pictures sit in the same world as the figures.

## 3. Rules (offline, deterministic)

The look works from the rules director's storyboard alone. An LLM may later choose among the options these rules
list (pose, framing, ground colour), never invent new ones.

- **Shots**: each narration beat is cut at sentence ends into shots of 2.2 s or more; a shot longer than 8 s is
  cut again at the trigger of its second picture.
- **Pose** from the shot's words: a question -> think; otherwise the earliest action cue wins (death, collapse,
  defeat -> fall; war, attack, anger -> angry; flight and chase -> run; travel words -> walk; victory, survival
  -> cheer; loss, plague, famine -> sad; "nobody knows", "no single" -> shrug), and only without one a weak cue
  (said, called -> talk; money, carrying -> hold; look, see -> point). A negated cue ("did not fall", "didn't
  fall", "nobody was killed") does not count, and neither does "best" ("the best way to remember" is not a
  victory). Otherwise point at the pictures, or stand or talk. Chinese has its own cue lists, which skip
  compounds that only contain a cue character (拿走 is taking, not walking; 也就是说 is "that is", not speech;
  问题 is a problem, not a question) and plain hedges (可能). A fallen figure gets X eyes and a wavy mouth and no
  "!" marks.
- **Face**: a figure that stands, talks, points, holds or walks looks shocked (wide eyes, an "o" mouth and two
  red "!") at shock words (a bomb, a gun, "killed", "millions"), worried (tilted brows, a frown) at grim words
  (crime, danger, death, fear, a ransom, bad news), and otherwise wears its pose's own smile, except in a video
  that names crime three times or more (true crime), where it keeps a straight face and talks with a small oval
  mouth instead of a grin. Crowds follow the same rule.
- **Crowd**: people, army, citizens, population (and Chinese equivalents) bring 3 to 7 figures.
- **Costume** by topic words: Roman, legion, gladiator -> crested helmet; soldier, army, warrior -> the crested
  helmet in an ancient story and a plain green combat helmet in a modern one (a story is ancient when it names
  antiquity, Rome, legions, pharaohs, more often than it gives modern years or modern things like planes or the
  FBI); emperor, king, queen -> crown; worker, farmer -> straw hat; otherwise none.
- **Framing** alternates so two shots in a row never share a layout: figure left with props right, figure right
  with props left, close-up with big text, crowd, text card.
- **Narrator pictures** (think, wave, explain...) in the storyboard become poses of our figure, not doodles.
- **Numbers** are big plain text with a red underline drawn as they are said ("between 235 and 284" ->
  235–284, "the 270s" -> 270s). A shot with nothing else to show puts the number its narrator says on screen
  (a year, a count, a percentage). A number's label is shown only when its words are in the same sentence as the
  number, and an English glossary name keeps only its capitalised words, so a director slip ("378: Visigoths
  sacked Rome", "Odoacer removed") never reaches the screen. Dated events go on a timeline.
- **Red circles** go round a picture and its label together; a definition that only points back ("this
  phenomenon", "这个现象") is dropped.
- **Fixed regions** (1920x1080): header 30..100, stage 130..900, ground 900..1080, captions 930..1050. Labels never
  overlap figures, props or each other, and nothing leaves the frame (checked in tests).

## 4. What it reuses (read-only)

`pipeline.narrate` (cached voice clips), `engine.timeline.layout` (the master clock, re-laid with no hand pauses),
`audio.mix` (narration and music), `numbers.normalize` (display to spoken positions), `script.sentences`,
`library.resolve` (doodle files) and the bundled fonts. Nothing in the existing engine or pipeline is edited.

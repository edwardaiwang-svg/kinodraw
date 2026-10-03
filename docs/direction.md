# Direction: looks, story shapes and motion

KinoDraw's first style is the whiteboard: a drawing hand sketches every picture. The Direction system adds
two more looks and lets the same script be told in different ways, at different energy, by rules. A language
model may pick among the options the rules offer, but it never invents what is drawn or when.

## The three dials (top-level storyboard keys)

| Key | Values | Default |
|---|---|---|
| `look` | `whiteboard`, `collage` (paper cut-outs, stickers, a paper puppet), `bold` (kinetic type, shapes, particles) | `whiteboard` |
| `story` | `explain` (sections, agenda, takeaways), `promo` (problem → brand → steps → proof → call to action), `story` (question → journey → twist → end line), `showcase` (one idea per beat, a signature end card) | `explain` |
| `motion` | `calm` (no big moves), `lively`, `showreel` (beat-synced, many showpieces) | `lively` |

`brand` (optional) is `{name, url, cta, reveal}` for promos; `reveal: "hand"` has the drawing hand write the name (and a closing line) instead of slamming it in. Set the dials with `kinodraw make --look collage --story promo`.

## Who decides what

1. **The rules annotator** (`director/annotate.py`) splits every beat into sentences and gives each one a *role*
   (hook, problem, turn, brand, step, feature, channels, social, mechanic, use_cases, list, number, quote,
   reveal, tagline, cta, end_line, none), a baseline *energy* 0–3, two or three eligible *scene* templates (its own
   pick first) and up to four *emphasis* candidates, each a phrase of the sentence. It always produces a complete
   plan, so the app works offline.
2. **The AI director** (GPT-6 Luna through KinoDraw Cloud, optional) answers with indices only: which offered scene,
   which offered emphasis, which role, and an energy that code clamps to the baseline ±1. It cannot add text,
   pictures or times. Anything invalid keeps the rules pick.
3. **The user** can override a sentence's scene or energy in the Studio; that always wins.
4. **The planner** (`annotate.plan`) turns the energies into a budget the Motion dial allows: `calm` keeps everything
   at 1 or below; `lively` allows 20% of the runtime at 2 or more and two showpieces (energy 3); `showreel` allows 45%
   and five. After a big moment the next 3 seconds rest; showpieces are 12 seconds apart; a sentence without a
   short key phrase can't slam.

Each sentence's annotation lives in its beat, anchored by position (never by searching for a phrase):

```json
"direction": [{"i": 0, "span": [0, 42], "role": "problem", "energy": 1, "scene": "chat_pileup",
               "emphasis": "a message", "source": "rules",
               "options": {"scene": ["chat_pileup", "sticker_row"], "emphasis": ["a message", "friends"],
                           "energy": [0, 2]}}]
```

## Energy → motion (rules)

| Energy | Treatment |
|---|---|
| 0 | settle or fade in |
| 1 | pop with an 8% back-out overshoot, 70 ms stagger, a soft sound |
| 2 | slam (180 ms expo-out with a two-frame smear), whip or torn-paper wipe, 8% camera punch-in, counter roll, stamp |
| 3 | showpiece: confetti burst with the puppet jumping, a beat-synced chip cascade, a match-cut into the end card |

Rules of craft the renderers follow: things entering ease out and things leaving ease in; overshoot 5–10% (15–25%
for celebrations); stagger 50–100 ms and keep a cascade under 0.5 s; puppets animate on twos, the camera on ones;
at most three full-screen flashes per second; text stays up at least as long as it takes to read; one fast mover at a
time. Hits land on the frame of contact; sound may lead by up to 45 ms or trail by up to 125 ms.

## Renderers

`engine/render.make_production()` picks the renderer for the storyboard's look. Every renderer answers the same
questions, so pacing, parallel rendering, stills, the timeline, the mix and packaging don't care which look it is:

- `frame(t)` → a 1920×1080 image
- `warnings` → a list of strings
- `ctx.elements` → scheduled elements with `beat`, `start`, `end`, `skipped`, `fixed` (used by pacing)
- `cues()` → sound-effect events `{t, kind, strength, id, dur?, x?}`, saved to `build/cues.json`

Randomness (jitter, confetti, torn edges) is always a pure function of a seed, an element id and the frame on twos,
so render workers that split the video produce identical frames.

## Sound

`audio/sfx.py` turns cues into a sound-effect track (CC0 samples plus synthesized pops, whooshes, risers and
kicks, each hit with seeded pitch and gain variation). For every look except the whiteboard, the music bed plays
under the whole video, ducked about 18 dB under the voice and swelling at cuts, and `audio/master.py` masters the
mix to −14 LUFS with a −1 dBTP limiter. The whiteboard mix is unchanged.

## The collage look (first)

- **Paper kit:** cream, kraft, grid and lined paper, watercolor washes, torn edges, masking tape.
- **Stickers:** the Fluent "Flat" emoji and the bespoke doodles, each with a white die-cut border and a soft shadow.
- **The paper puppet:** a cut-out character drawn by code (stand, look up, walk, point, hold a phone, think,
  worried, cheer, wave), colors chosen per video.
- **UI kit:** phone, chat bubbles with a counting badge, form fields that type, link chip, button with a tapping hand,
  avatars with ✓/✗, stamp, traffic light, slots with a minimum marker, badges.
- **Promo scenes:** `chat_pileup`, `chaos`, `brand_reveal`, `step_card`, `share_link`, `rsvp`, `feature_chips`,
  `threshold`, `use_case_grid`, `brand_endcard`, and `sticker_row` for anything else.
- **Software promos:** `script_page` ("You wrote…": a lined page with the video's own words; the list after it pops up
  around the page, the trouble piles up on it), `app_paste` ("Paste your script.": the app window, the narration
  pasted into its script box), `app_press` ("Press Make video.": that button, tapped), `hand_draws` ("A hand draws
  every idea": the video panel grows over the window and the drawing hand draws the key phrase's doodle, then the
  ones the script's use cases name). Their words lead the scene choice whatever the sentence's role.

On-screen words come only from the script, the `brand` fields, or fixed interface labels ("I'm in!", "Continue").
Decorative chat messages come from a fixed bilingual bank, never from a model.

# Doodle style guide

Target look: bold, friendly, flat
cartoon drawings with thick black outlines and saturated flat colour, readable at
150 px tall on a phone. Each doodle illustrates ONE specific idea from the script.
Everything is original vector work (no traced logos, no copied artwork).

## File rules (enforced by `python -m kinodraw.library.check`)
- One file per doodle: `assets/doodles/bespoke/<id>.svg`, root
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 W H" width="W" height="H">`,
  W and H between 200 and 600, drawing fills the box with ≥ 12 px padding.
- Allowed elements: `path rect circle ellipse line polyline polygon g`.
  NOT allowed: text, image, use, defs, gradients, filters, masks, clipPath,
  pattern, style/class/CSS, opacity attributes. Inline attributes only:
  `fill stroke stroke-width stroke-linecap stroke-linejoin fill-rule transform d
  x y width height rx ry cx cy r points x1 y1 x2 y2 id data-*`.
- **Draw order = document order = the order the hand draws**: big silhouette
  first, then interior parts, then small details. The renderer traces every
  element's outline in that order with a drawing hand, then pops the colour in.
- Outlines: `stroke="#1B1B1B"` width 6 (main shapes) or 4 (inner details; min 3),
  `stroke-linecap="round" stroke-linejoin="round"`. Every filled shape has the ink
  outline, except a pure colour accent with `data-noink="1"` (e.g. a highlight).
- Fills ONLY from this palette (or `none`):
  red #E53935 · blue #1E6FD9 · sky #64B5F6 · navy #1A3A6B · green #43A047 ·
  lime #9CCC65 · yellow #FDD835 · gold #F9A825 · orange #FB8C00 · purple #8E24AA ·
  teal #00897B · pink #F48FB1 · brown #8D6E63 · tan #D7B98E · skin #F6C9A4 ·
  skin_shade #E8A87C · white #FFFFFF · light_gray #E0E0E0 · gray #9E9E9E ·
  dark_gray #424242 · ink #1B1B1B · paper #FFF8E1 · sweater #7E93A8 ·
  sweater_light #B8C6D3 · glass_rim #B08D57 · hair #1B1B1B
- 5–70 elements. No detail smaller than 6 px. One darker tone per object at most
  for shading. No gradients, no drop shadows.
- No letters or words inside doodles (the renderer hand-writes all text). Simple
  symbols drawn as shapes are fine: $ sign, % sign, arrows, check marks, plus/minus.
- No brand logos or trademarks. Generic objects only (a generic "exchange bell",
  not the NYSE logo; a generic classical building, not a sealed agency logo).

## Narrator character (narrator_* files)
A friendly, original cartoon presenter who carries the story across videos. It must NOT resemble any
real person. Design once, reuse the identical head path data (face, hair, eyes) in every pose:
round friendly face (skin #F6C9A4 with #E8A87C shading), short tousled dark-brown hair (brown #8D6E63
or ink), big dot eyes, simple smile; teal sweater (#00897B) with a yellow (#FDD835) collar stripe,
navy trousers (#1A3A6B), dark shoes. Chibi proportions (head ~1/4 of height), full body, viewBox
320x480. Poses must read clearly in silhouette at phone size.

## Tags (required for every doodle)
Each authoring batch writes `assets/doodles/tags/<batch>.json`:
`{"<id>": {"desc": "one line", "category": "...", "en": ["keyword", ...], "zh": ["关键词", ...]}}`
with 5-12 English and 3-8 Simplified Chinese keywords/synonyms a script might use for the concept.

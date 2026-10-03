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
  "chapters": [],
  "beats": []
}
```

- `narrator`: `"none"` hides the character. Any other value is a prefix, and poses are looked up as `<prefix>_wave`, `<prefix>_head`, `<prefix>_present`, `<prefix>_thumbs`, and so on (see "Your own doodles" below).
- `music`: `true`, `false`, or `{"primary": "fresh_focus", "secondary": "natural_vibes"}`.
- `host`: optional, `{"photo": "photos/me.jpg", "badge": {"en": "Name · role"}}`. It adds a photo badge to the title board and end card.

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

## Your own doodles

Put SVG files in the project's `doodles/` folder and reference them by file name (without `.svg`). They take precedence over the built-in library. For the drawing hand to trace them well, follow `kinodraw/assets/doodles/STYLE.md`.

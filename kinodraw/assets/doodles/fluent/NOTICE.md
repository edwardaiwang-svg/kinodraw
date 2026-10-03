# Fluent emoji doodles: source and licence

Converted from Microsoft Fluent Emoji "Flat" SVGs (https://github.com/microsoft/fluentui-emoji),
commit `1ffb34c752ecf5d402f04cfb4b392c77f57c54bc`, MIT licence: see `LICENSE` (Copyright (c) Microsoft Corporation).

## What was modified

Regenerate with `python -m kinodraw.library.fluent SRC_DIR` (kinodraw/library/fluent.py):
- Default skin tone only; files renamed `fl_<snake_case_name>.svg`.
- Transforms baked into absolute path data; art re-fitted to a 320x320 box with 16 px padding;
  rect/circle/ellipse converted to paths, arcs to cubic curves, coordinates rounded to 0.1 px.
- Defs, gradients, clip paths, masks and filters dropped (emoji that rely on them are skipped);
  `opacity` overlays pre-blended into a flat colour over the shape they cover; shapes the
  original hides completely are dropped; stroked source lines keep their colour and width
  (thick bars get an ink edge drawn beneath them).
- Ink outline added (`stroke="#1B1B1B"`, round caps/joins): 6 px on big silhouette shapes,
  3-4 px on inner parts; tiny details, highlights and shading patches get `data-noink="1"`
  and no stroke; outline-only copies (`fill="none"`, `data-noink="1"`) re-ink silhouette
  edges that shading patches paint over. Original flat colours are kept.

## Tags (`../tags/fluent.json`)

`desc`, `category` and `en` come from the Fluent metadata (MIT). `zh` comes from the
Unicode CLDR annotations (cldr-json 48.2.2, CLDR 48),
https://github.com/unicode-org/cldr-json, used under the Unicode License v3:

```
UNICODE LICENSE V3

COPYRIGHT AND PERMISSION NOTICE

Copyright © 2015-2024 Unicode, Inc.

NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.

Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.

THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.

IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
FILES OR SOFTWARE.

Except as contained in this notice, the name of a copyright holder shall
not be used in advertising or otherwise to promote the sale, use or other
dealings in these Data Files or Software without prior written
authorization of the copyright holder.

SPDX-License-Identifier: Unicode-3.0
```

## Not converted (112; 1483 converted)

The denylist is the requested list (weapons, drugs, injury, funeral, sexual innuendo)
plus similar items: alcoholic drinks, headstone, briefs, biting lip, tongue, sweat
droplets, love hotel. "Letters or digits" are emoji whose meaning is the text itself
(STYLE.md: no text in doodles); objects that merely carry a label (medals, pool 8
ball, hotel, red envelope) are kept.

- **denylist** (30): Beer mug, Bikini, Biting lip, Bomb, Bottle with popping cork, Briefs, Cigarette, Clinking beer mugs, Clinking glasses, Cocktail glass, Coffin, Dagger, Drop of blood, Eggplant, Funeral urn, Headstone, Kiss mark, Love hotel, Middle finger, Peach, Pill, Sake, Skull and crossbones, Sweat droplets, Syringe, Tongue, Tropical drink, Tumbler glass, Water pistol, Wine glass
- **flag** (8): Black flag, Chequered flag, Crossed flags, Pirate flag, Rainbow flag, Transgender flag, Triangular flag, White flag
- **letters or digits in the art** (62): A button blood type, Ab button blood type, Atm sign, B button blood type, Back arrow, Circled m, Cl button, Cool button, Copyright, End arrow, Free button, Hundred points, Id button, Input latin letters, Input latin lowercase, Input latin uppercase, Input numbers, Japanese acceptable button, Japanese application button, Japanese bargain button, Japanese congratulations button, Japanese discount button, Japanese free of charge button, Japanese here button, Japanese monthly amount button, Japanese no vacancy button, Japanese not free of charge button, Japanese open for business button, Japanese passing grade button, Japanese prohibited button, Japanese reserved button, Japanese secret button, Japanese service charge button, Japanese vacancy button, Keycap 0, Keycap 1, Keycap 10, Keycap 2, Keycap 3, Keycap 4, Keycap 5, Keycap 6, Keycap 7, Keycap 8, Keycap 9, Mobile phone off, New button, Ng button, No one under eighteen, O button blood type, Ok button, On! arrow, P button, Registered, Soon arrow, Sos button, Top arrow, Trade mark, Up! button, Vs button, Water closet, White flower
- **look relies on gradients/clipPath/mask/filter** (12): Airplane arrival, Confetti ball, Eleven oclock, Face exhaling, Head shaking horizontally, Incoming envelope, Oden, Paperclip, Phoenix bird, Rolled-up newspaper, Teacher, Violin

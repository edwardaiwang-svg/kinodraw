"""Stick-figure documentary look: white canvas, thin black lines, circle-head figures, a flat 16-colour palette,
red emphasis drawn with a pencil cursor, plain sans text and hard cuts (design notes: docs/looks/stick.md).

  palette   the 16 colours, nearest-colour snapping, accents and ground colours
  rig       the figure: skeleton, pose library, faces, hats, crowds (deterministic from a seed)
  paint     library doodles redrawn in this look (thin black outline, palette fills)
  text      plain sans labels, big numbers, captions (en + zh)
  marks     red emphasis: circle, arrow, underline, cross-out, "?" and "!", the pencil cursor
  cues      word rules: pose, face, crowd, costume, ground, emphasis (en + zh)
  fill      what a sentence the storyboard left bare shows: a name, a number, a picture, the picture in play
  compose   storyboard + timeline -> shots (hard cuts) of placed items
  render    frames from shots (boil, motion on twos), video encode
  preview   python -m doodlestudio.engine.stick.preview <project> -o out.mp4

Everything here is new; the whiteboard engine and the pipeline are only imported, never changed.
"""

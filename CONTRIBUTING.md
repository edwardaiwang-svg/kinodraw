# Contributing

## Set up

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/pytest -q                                   # about 80 tests, a few seconds
.venv/bin/kinodraw make tests/fixtures/tiny.md -o /tmp/tiny   # a 20-second end-to-end video
```

Match the style of the code around your change, and keep each change focused. Tests must pass; `numbers.py` and the directors have the most edge cases.

## Adding doodles

The library grows best one good drawing at a time.

1. Read `kinodraw/assets/doodles/STYLE.md`. It covers the palette, 6 px ink outlines, drawing order and "no text".
2. Save your drawing as `kinodraw/assets/doodles/bespoke/<id>.svg`, where the id is lowercase with underscores.
3. Check it: `python -m kinodraw.library.check <id> --sheet mine`. This validates the file and writes a contact sheet at full and phone size; look at both.
4. Add search tags to a file in `assets/doodles/tags/`:
   `{"<id>": {"desc": "…", "category": "…", "en": [5–12 keywords], "zh": [3–8 关键词]}}`.
5. Rebuild the bundled search vectors: `python -m kinodraw.director.match`.

Original work only: no traced artwork, logos or real people. By contributing you license your doodles under CC BY 4.0 and your code under MIT.

## Adding a language

Adding a language touches four places: `numbers.py` (numbers to words), `script.py` (sentence splitting and the agenda wording), `voice.py` (a Kokoro model and voice), and a handwriting font with good glyph coverage in `engine/ink.py`. Open an issue first so the pieces can be planned together.

## Never commit

Never commit API keys, `.env` files, rendered videos, personal photos, or anything under `private_presets/`.

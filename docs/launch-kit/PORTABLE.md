# KinoDraw local launch kit

Open `../index.html` for playable videos, source scripts, caption files, project
ZIPs and provenance links. `../manifest.json` records every shipped file's size
and SHA-256, plus real full-media decode evidence. `COPY.md` is factual launch
copy for review. Optional contact sheets/screenshots are linked only when supplied;
every thumbnail is extracted from the actual included MP4.

A partial pack is explicitly labeled in the page and manifest. Integrity checks
do not establish visual/editorial approval, factual accuracy, or deployment.
The five scripts include fictional story/product/news content; read each caption.

## Open and edit a project

In a compatible KinoDraw Studio source build, use **Import project ZIP**, choose
the corresponding `../assets/ID/project.zip`, and inspect its saved storyboard,
settings and source before rendering. Import verifies the archive and creates a
new project. The ZIP preserves the saved plan; provider endpoints and executable
settings are stripped by export. Narration and other authored assets may remain.

## Make a fresh version from a script

From a KinoDraw source checkout with its Python dependencies and local models:

```sh
python -m kinodraw.cli make /absolute/path/to/assets/explainer/script.md -o projects/new-explainer --director rules --director-v3
```

Use a fresh project directory. Full pipeline first use can download voice/search
models. Rules may differ from the saved reviewed plan. For supported landscape
4K, add `--aspect 16:9 --size 3840 2160`; native collage 4K is unsupported.

The scientific JSON records and retained NOAA source are under
`../assets/scientific/`, alongside their use/contract guide. A source checkout's
`docs/developer.md` explains `chart-add`, preview and narrated MCP modes. Rendering
never fetches a scientific citation URL or executes supplied equations/code.

For browsers that restrict captions on file URLs, optionally start your own
loopback server from the delivery folder:

```sh
python -m http.server 8765 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8765/`. No server, upload or publication is performed
by the packaging helper.

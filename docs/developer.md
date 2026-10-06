# Local developer tools

Run from the repository with the existing Python environment. No installation,
API key, keychain access, narration, search-model download, or app-folder migration
is needed for these commands. The existing `new`, `voice`, `render`, and `finish`
commands retain their flags and behavior.

```sh
P=python
ROOT=/absolute/path/to/an/existing/workspace
"$P" -m kinodraw.cli starter --list
"$P" -m kinodraw.cli starter explainer-en --root "$ROOT" -o demo
"$P" -m kinodraw.cli validate demo --root "$ROOT"
"$P" -m kinodraw.cli preview demo --root "$ROOT" --time 0.5
"$P" -m kinodraw.cli mcp --root "$ROOT"
```

`--root` must name an existing absolute directory. All project and source arguments
are paths relative to that root. Creation refuses existing projects. Paths with
`..`, hidden components, backslashes, or symlinks are refused. Existing projects
containing any symlink are refused, including symlinks in output folders. Photos
and doodle references are checked before the renderer opens them. All project
SVGs and inline SVG documents are checked at project validation: external image,
use and CSS resources, XML base paths, DTDs/entities, scripts, event handlers,
stylesheets and animation are refused. Inline geometry, text, transforms, defs,
gradients, clipping, ordinary inline styles and local `#id` references remain
supported; validation does not rewrite the artwork. Stock footage and the
`collage` look are unavailable on this surface. Collage can implicitly invoke
semantic sticker search and download models, so validation, preview and render
refuse it before search or child launch, even when a model happens to be cached.
These checks assume the workspace is not being
maliciously changed concurrently; they are not an OS sandbox.

Eight editable Markdown starters cover explainers, processes, comparisons, and
data stories in English and Chinese. Every starter explicitly labels its story
and data as invented examples, not genuine observations. The bundled scripts
live in `kinodraw/assets/starters/`; the created project's `script.md` and
`storyboard.json` can be edited. Creation uses `pipeline.new_project`, the same
storyboard builder as `new`, with the rules setting. It produces the real skeleton
without invoking the director's model-download entry point. Add visuals explicitly
or continue through the existing pipeline when its local dependencies are ready.

## Charts from supplied sources

Save a UTF-8 JSON file below the root. This example is explicitly fictional:

```json
{
  "source": "Invented example data, not genuine measurements",
  "title": "Example button counts",
  "unit": "buttons",
  "rows": [{"label": "Box A", "value": 2}, {"label": "Box B", "value": 4}]
}
```

Use an actual beat ID from `demo/storyboard.json`:

```sh
"$P" -m kinodraw.cli chart-add demo --root "$ROOT" --beat b002 --source counts.json
```

`chart-add` appends a current `bars` visual, runs the existing validator, and saves
the storyboard only when valid. Values come directly from the source file. The
visual keeps the source filename, its SHA-256, and a visible source footnote.
Attribution is supplied by the caller; it is not independent verification of the
data. Missing values, booleans, strings, non-finite numbers, duplicate JSON keys,
and missing attribution are errors. Decimal float tokens must retain their numeric
value when parsed and serialized as a Python float; precision loss and underflow
are errors, including `9007199254740993.0` and `1e-400`. Integer values must also
convert exactly to the current renderer's float. Ordinary decimal values such as
`0.1` remain supported; their decimal JSON value and source hash are preserved.
The existing bar renderer clamps negatives
and displays at most six rows, so this interface refuses negative values and
sources outside one to six rows instead of silently changing their meaning.

## Stdio MCP

Transport is newline framing: one UTF-8 JSON-RPC 2.0 object per line on stdin and
stdout. Embedded newlines in strings must be JSON-escaped. There are no
`Content-Length` headers. Diagnostics use stderr; render-child diagnostics are
also saved in the returned project log. Non-finite JSON (`NaN`, infinities, and
overflowed floats), duplicate keys, and JSON-RPC batches are refused.

Send `initialize` as a request, followed by the `notifications/initialized`
notification. Versions recognized by this implementation are `2024-11-05`,
`2025-03-26`, and `2025-06-18`; other versions receive `2025-06-18` for client
negotiation. `ping`, `tools/list`, and `tools/call` are supported. Notifications
receive no response and cannot launch tool calls.

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"local-client","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"create_project","arguments":{"project":"demo","starter":"explainer-en"}}}
```

| Tool | Arguments | Actual result |
| --- | --- | --- |
| `create_project` | `project`, exactly one of `script` / `starter`; optional `lang`, `title` | Editable pipeline storyboard skeleton |
| `validate_project` | `project` | Existing validator errors and warnings; invalid boards return `isError` |
| `chart_add` | `project`, `beat`, `source` | Source-backed `bars` visual and source hash |
| `preview_png` | `project`, optional `time` (default 0) | PNG path plus MCP image content |
| `render` | `project`, optional `start` (0), `duration` (1 second) | Opaque owned job ID and PID, not a completion claim |
| `status` | `job` | Actual process state and exit code |
| `cancel` | `job` | Reaped owned process group and actual exit code |

Preview and render use `engine.timeline.synthetic_clips` / `layout` and the existing
`engine.render.make_production` / `encode`. Timing is estimated and labeled
`synthetic_timing`; MP4 output is silent. PNG size is 960×540, or 540×960 for a
vertical project. Files receive unique names in `build/developer/`. The render
duration is bounded to 1/30–30 seconds. One subprocess is launched per render
request, with one encoder rather than parallel segment workers.

Jobs are owned only by the server process that created their `Popen` handles.
Status and cancellation accept opaque job IDs, never arbitrary PIDs or command
text. Cancellation targets that child's process group, including its encoder.
EOF cancels running owned jobs. Completed, failed, and cancelled states preserve
the real exit code; success also requires an output file. Job history is in memory
and does not survive a server restart. Partial cancelled artifacts remain available
for inspection.

Writer, export, ZIP packaging, and progress notifications are not advertised.
Unknown tools return a truthful `isError`. Future modules need an explicit adapter
and real checks before appearing in `tools/list`.

## Focused verification

```sh
"$P" -m pytest -q tests/test_mcp_server.py tests/test_starters.py tests/test_developer_cli.py tests/test_text_files.py
```

These checks launch real stdio clients and CLI subprocesses, create and validate
projects, add source charts, inspect actual PNGs, encode a one-frame MP4, and cancel
an owned child. They also exercise path escapes, symlinks, SVG resource refusals
and retained inline features, collage refusals before model search, lossy chart
data, source value/hash preservation, and legacy flag parsing.
Evidence and actual command exit codes are retained under
`evidence/developer/`. No full-suite or long-video run is required.

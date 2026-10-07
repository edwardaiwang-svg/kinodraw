# Offline MCP narrated movies

Start the existing newline-framed stdio server with an explicit workspace root:

```sh
python -m kinodraw.cli mcp --root /absolute/existing/workspace
```

## Use it from Claude Code

Use the Python that has KinoDraw installed (for example the project's
`.venv/bin/python`) and an absolute folder that already exists. Every project the
assistant makes or reads stays inside that folder.

```sh
claude mcp add kinodraw -- /absolute/path/to/python -m kinodraw.cli mcp --root /absolute/existing/workspace
```

Add `--scope project` to share it through a `.mcp.json` file at your project's
root instead. The file looks like this:

```json
{
  "mcpServers": {
    "kinodraw": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "kinodraw.cli", "mcp", "--root", "/absolute/existing/workspace"]
    }
  }
}
```

Then ask for, say, "list my KinoDraw projects" (`list_projects`), "what is in
demo?" (`get_project`: chapters, beats with their text and visual types, chosen
settings, outputs and the last QA summary), "which voices are there?"
(`list_voices`: 24 offline voices by language, with defaults), or "export the
preview as WebM" (`export_video`: GIF or WebM from an MP4 inside the project,
written to `build/developer/` as an owned job that `status` polls and `cancel`
stops). `get_project` shows chosen settings only, never keys, commands or server
addresses.

Initialize JSON-RPC, send `notifications/initialized`, then use `tools/call`.
There are eleven tools: `create_project`, `validate_project`, `chart_add`,
`preview_png`, `render`, `status`, `cancel`, `list_projects`, `get_project`,
`list_voices`, and `export_video`. Creation produces the same
editable skeleton without narration, model search, credentials, or migration.
Default `render` still makes a silent preview with estimated timing and a
one-second default; its duration limit remains 1/30 to 30 seconds.

To request a complete narrated movie, explicitly call:

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"render","arguments":{"project":"demo","mode":"make"}}}
```

`make` calls the shared `pipeline.produce` with cancellation and encoded-frame
progress. It reads the voice and speed already saved in `project.json`.
Kokoro ONNX model files for that language must already exist locally with the
published sizes and SHA-256 checksums. `KINODRAW_MODELS` may select the local
model directory at server launch; project JSON cannot select model files or a
voice-server URL. Missing or altered models are refused before launching a job.
The isolated worker replaces the download-capable model gate with a local check.
There are no model downloads, provider calls, secret lookups, or API charges.
The cost is local synthesis, rendering, and validation CPU/time.

Saved v3 plans and their visuals are reused without invoking their provider.
Without a saved v3 plan, rules derive scene treatments from the saved storyboard;
this fallback does not search for new pictures or download an embedding model.
The job response identifies the choice. Commands, provider URLs, keys, tokens,
and voice-server settings in project configuration are refused. To use a
previous provider plan, keep its saved plan data and remove these executable or
connection settings through a revision-checked `ProjectStore` edit first.

Use `"mode":"cached"` to finish a complete movie from `build/timeline.json`
and its narration WAV, without TTS, voice models, or providers. The timeline
must match the saved storyboard hash, beat IDs, and render layout. Its narration
must contain nonzero PCM and match the full measured duration. This is measured
cached timing, even when the clips originate from an explicitly labeled test
fixture. Cached rendering leaves project, storyboard, script, recording, and
saved timeline/narration bytes unchanged. Neither narrated mode accepts a
partial interval: omit `start` and `duration`.

Poll `status` with the returned opaque `job` ID. It reports the owned process's
actual exit code, stage, encoded frames/total, elapsed time, and ETA. Frames come
from FFmpeg progress; stage completion is separate from encoded-frame progress.
For `make`, `synthetic_timing` is null while measurement is pending and false
after measured narration is validated. For `cached` it is false after cache
preflight. Default previews continue to report true.

Success requires pipeline QA, full video decoding with the exact measured frame
count, complete audio decoding with nonzero PCM and matching duration, and all
six sidecars (SRT, VTT, chapters, transcript, description, thumbnail). The finished
MP4 hash is rechecked by status. Outputs are staged, then published under the
project revision and cancellation locks. Source edits invalidate publication;
cancellation preserves the previous movie. A late cancellation after complete
publication reports success. Unknown job IDs cannot inspect or cancel anything.
Concurrent narrated jobs for the same project in one server are refused.

All existing root, symlink, SVG/CSS, chart precision, stock-footage, and collage
guards remain. Script, recording, voice-file, configuration, plan picture, and
cached narration references are checked before launch and again before final
publication. These checks assume the workspace is not maliciously mutated
concurrently; they are not an OS sandbox. Frozen launchers dispatch the private
`--mcp-worker` flag and retain `--render-worker` and `--finish-worker`; construction
tests do not establish acceptance of a built application.

News and data-story examples must identify fictional or illustrative content.
The acceptance fixtures use a fictional script: one caches labeled synthetic
tones, and a separate flow synthesizes actual speech from local Kokoro models.

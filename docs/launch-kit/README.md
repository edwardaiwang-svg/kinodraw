# Local portfolio and launch kit

The [source gallery](../gallery/index.html) browses the five required use cases:
`lion`, `explainer`, `product-launch`, `lesson`, and `news`. It links only shipped
scripts/data and build instructions. Final MP4s are added locally after rendering
and visual review; they are not placeholders or remote demo URLs.

## Package actual outputs

Use an existing KinoDraw source environment. Save an input JSON manifest outside
the delivery directory, using [manifest.example.json](manifest.example.json) as
the shape. Its single entry illustrates the schema, not a completed five-video
manifest. Include exactly the five IDs above for a final pack. Every entry needs
`video` (.mp4), `script` (.md/.txt), `project` (.zip exported by Studio), `captions`
(.vtt), and `description` (.md/.txt). Optional `sources` (.json) retains the source
appendix; `screenshot` (.png/.jpg) retains a contact sheet or a reviewed still.
`review` is an optional textual evidence reference, not an automatic PASS.
All artifact paths are relative to one explicitly supplied directory.

```sh
python scripts/package_gallery.py --manifest delivery-input.json --root /absolute/artifact-root --output /absolute/new-delivery-folder
```

The root and output parent must exist; the destination must be new. Traversal,
hidden path components, backslashes, symlinks, missing/empty files and unsupported
file types are refused. Project ZIPs pass the actual product importer (manifest,
hashes, path/type/size protections); the script must match the archived project source byte for byte. Supplied screenshots are decoded as real images. FFmpeg fully decodes each copied MP4 with its
audio and checks for nonzero audio samples; it extracts a real thumbnail. Input,
copy and final hashes are checked. This checks media integrity, not speech accuracy
or artistic quality. Main acceptance must retain visual/editorial review separately.
Each FFmpeg operation has a 900-second timeout; failures preserve their exit code
in the error message and never publish a partial destination.

The finished folder includes a responsive, filterable player gallery, caption and
script downloads, project ZIPs, source appendices when supplied, screenshots when
supplied, retained scientific examples, launch copy and full content hashes in
`manifest.json`. All local links resolve inside the folder. It makes no API calls,
reads no account credentials, and does not upload, publish or host anything.
Supply shareable project/script assets only: imported project ZIPs can legitimately
contain recordings and other authored files.

For a deliberate subset or a silent short verification clip, add `--partial`.
The manifest and page clearly label that pack incomplete; it does not fulfill the
five-showcase acceptance. Use a fresh output directory for each revision.

Open the resulting `index.html` locally. For captions in browsers that restrict
file URLs, optionally serve the folder yourself on loopback:

```sh
python -m http.server 8765 --bind 127.0.0.1 --directory /absolute/new-delivery-folder
```

Then browse `http://127.0.0.1:8765/`. The packaging helper does not start a server.

## Rebuild the source page

```sh
python scripts/package_gallery.py --source-preview
```

This refreshes `docs/gallery/index.html` from `examples/showcases/catalog.json`;
it claims no playable movie. Source scripts and exact local build commands are in
[examples/showcases](../../examples/showcases/README.md). Scientific source/model
contract and provenance are in [examples/scientific](../../examples/scientific/README.md).
Native 4K and MCP narrated-mode details are in [developer.md](../developer.md).
The source-page filter uses inline JavaScript; all examples remain visible if
JavaScript is unavailable.

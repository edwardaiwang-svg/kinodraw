# Source-backed scientific scenes

KinoDraw's existing `chart-add` CLI/MCP entry accepts `kinodraw-scientific/1` JSON,
then selects the beat's v3 chart treatment automatically. It plots supplied numbers
or a bounded built-in equation in code on exact black. It does not load Blackbody
wallpapers, call an image model, fetch data while rendering, or execute supplied code.

The two examples are deliberately different:

* `noaa-co2.json`: 47 annual means, 1975–2021, copied unchanged from the downloaded
  NOAA Global Monitoring Laboratory file retained here. Primary data:
  <https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.txt>.
  The input records the raw file hash and creation date. This NOAA-era subset avoids
  the older Scripps record and the 2022–2023 observatory relocation. Units are dry-air
  CO2 mole fraction in ppm. Provider uncertainty is not plotted; these annual means
  are not individual measurements. Lines connect consecutive annual samples.
  NOAA data terms/credit: <https://gml.noaa.gov/about/disclaimer.html>.
* `oscillator.json`: an **analytical**, illustrative ideal harmonic oscillator,
  with position `x(t)=A*cos(omega*t+phase)` and velocity
  `v(t)=-A*omega*sin(omega*t+phase)`. It reveals a phase-space trajectory, rather than
  the first example's time series. Parameters, time interval, seed zero and sample
  count are saved. At the specified initial time, position is 1 m and velocity is
  zero. Equation reference: OpenStax *University Physics Volume 1*, §15.1,
  <https://openstax.org/books/university-physics-volume-1/pages/15-1-simple-harmonic-motion>.
  The equations are mathematical facts; no textbook illustration or passage is copied.
  Example JSON/code is project-authored; the example parameter payload is CC0.

## Use

Create a project with a script through Studio or MCP `create_project`, then ingest a
source file below the same explicitly selected workspace root. For an existing
project and a real beat ID from `storyboard.json`:

```sh
python -m kinodraw.cli chart-add my-project --root /absolute/workspace \
  --beat b2 --source my-source.json
python -m kinodraw.cli validate my-project --root /absolute/workspace
python -m kinodraw.cli preview my-project --root /absolute/workspace --time 5
```

These are developer commands: the root confines files and preserves the original
bar-chart format too. `chart-add` embeds the validated payload in the beat's
`scientific` visual, copies the original ingest file to a content-hashed local
`assets/scientific/` asset, and saves the paired storyboard/settings revision.
Project ZIP includes that asset. Published packages add `VIDEO-sources.json` beside
captions/transcript and source credits in the description. The appendix includes
source and plotted-payload hashes, units, transforms, model equation and parameters.
Render workers use the validated inline data; they never dereference citation URLs
or source paths. Editing plotted data changes the plot hash; the original ingest
hash remains a record of what was initially supplied.

The whole-video Luna director sees only each source record's title, axes/units,
mode, encoding and citation, not raw numeric arrays. It can choose scientific
`chart` for the referenced beat, or `whiteboard` for source-narration explanation.
The v3 `{kind, ref}` element/cloud answer schema is unchanged. Offline direction also
recognizes scientific records. Source import needs one explicit action; plain prose
without a validated dataset/model record cannot become invented scientific numbers.

## Contract and limits

Both modes require title, x/y label **and unit** (`dimensionless` is explicit), and
provenance with citation, public HTTP(S) URL, license/credit, version, access date and
transform disclosure. These are caller-supplied factual claims, not automatically
verified by the renderer. Observations use 1–8 tracks, each with a label, `series`,
`path` or `scatter` encoding, and numeric `[x,y]` points. A series requires increasing
x; a path preserves supplied topology/order; scatter has no connecting edges.
Repeated series x, missing coordinates, NaN/Infinity and absent provenance are
errors. Disconnected observations should be separate tracks. No values are filled
in, smoothed, extrapolated or randomly synthesized.

The only model is `harmonic_oscillator`, with `time` or `phase` projection. It requires
amplitude in m, angular frequency in rad/s, phase in rad, start/end in s, 32–8192
samples and seed **0**. Evaluation is closed form; at least 16 samples per cycle
prevents gross aliasing. It is not a physics solver or measured data. The phase
projection requires x units `m`, y `m/s`; time projection uses `s`, `m`.

The cap is 2 MiB and 8192 total points per plot, absolute coordinate magnitude
at most 1e12, and at most four plots per scene. More plots need separate source
beats. Four plots use small multiples with separate axes, not superimposed units;
1080p is recommended for readable small-multiple labels. Supplied domains must be
finite/increasing and include every point. Omitted domains use the data min/max
with 4% padding (a constant coordinate gets nonzero padding). Mapping is independent
linear x/y axes, with y increasing upward; equal visual scale is not implied.

Animation reveals whole samples in input order through 75% of the source span;
no point moves, and no intermediate measurement is invented. A white cursor marks
the most recently revealed sample. Glow is a local finite-support Gaussian on marks;
there is no ambient haze, grain, camera distortion or background fill. Labels and
plot marks leave the lower 24% of the raster clear for narration captions. Very long
on-frame attribution is fitted/ellipsized; the complete record remains in the source
appendix. Unknown/unsupported payloads fail with an actionable validation error.
A deliberately selected whiteboard view shows source narration instead of approximating
scientific geometry as a decorative icon.

## Verification

`python -m pytest -q tests/test_scientific.py` checks source numbers against the
retained NOAA file, the inverse pixel/data mapping, analytical initial conditions
and phase relation, generic encodings, bounded validation/rollback, random-access
full pipeline frames, source packaging and import parity, attribution export, compact
Luna selection payload, caption margin, small multiples and whiteboard fallback.

Actual CLI projects, PNGs, small encoded/fully decoded MP4 segments and measurement
reports are retained in the run evidence directory documented in the handoff. Pixel
measurements are from lossless raster frames; lossy MP4 encoding can introduce
compression values near marks and does not establish exact-black pixel preservation.

# Third-party notices

Doodle Studio's own code is MIT-licensed. Its original doodles, narrator character and drawing hand are CC BY 4.0. The components below keep their own licences.

The packaged apps on the Releases page also contain GPL components (FFmpeg built with x264/x265, espeak-ng and phonemizer), so each packaged app as a whole is distributed under the GNU General Public License, version 3 ([LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt)). Doodle Studio's own source code stays MIT on its own; see "GPL components and source" below.

## Bundled with the app

| Component | Where | Licence |
|---|---|---|
| Microsoft Fluent Emoji (converted to outlined SVG) | `assets/doodles/fluent/` | MIT, © Microsoft Corporation; see `fluent/LICENSE` and `fluent/NOTICE.md` |
| Unicode CLDR annotations (Chinese emoji keywords) | `assets/doodles/tags/fluent.json` | Unicode License v3; see `fluent/NOTICE.md` |
| Playpen Sans Bold (static instance) | `assets/fonts/` | SIL OFL 1.1, © The Playpen Sans Project Authors |
| Doodle Kai Medium (a subset of LXGW WenKai, renamed as the OFL Reserved Font Name clause requires) | `assets/fonts/` | SIL OFL 1.1, © LXGW |
| Arimo Bold (static instance) | `assets/fonts/` | SIL OFL 1.1, © The Arimo Project Authors |
| Noto Sans SC Bold | `assets/fonts/` | SIL OFL 1.1, © Adobe / Google |
| Music: *Fresh Focus* and *Natural Vibes* (Kevin MacLeod), *Inventing Flight* (Bryan Teoh) | `assets/music/` | CC0 / public domain, via FreePD.com; see `music/NOTICE.md` |

## Downloaded on first use

| Component | Licence |
|---|---|
| Kokoro-82M voice models, v1.0 and v1.1-zh (hexgrad), ONNX exports by thewh1teagle | Apache-2.0 |
| BAAI bge-small-en-v1.5 and bge-small-zh-v1.5 (doodle search), as the ONNX exports Qdrant/bge-small-en-v1.5-onnx-Q and Qdrant/bge-small-zh-v1.5 (from Hugging Face, checksum-verified), run with fastembed | MIT |

## Python libraries

| Library | Licence |
|---|---|
| kokoro-onnx | MIT |
| onnxruntime | MIT |
| misaki (Chinese G2P) | Apache-2.0 |
| espeak-ng (through espeakng-loader / phonemizer) | GPL-3.0-or-later |
| phonemizer | GPL-3.0-or-later |
| fastembed | Apache-2.0 |
| jieba | MIT |
| num2words | LGPL-2.1 |
| cn2an | MIT |
| Pillow | MIT-CMU |
| NumPy and SciPy | BSD-3-Clause |
| resvg-py | MIT |
| svgelements | MIT |
| fontTools | MIT |
| imageio-ffmpeg (the Python package) | BSD-2-Clause |
| FFmpeg 7.1 binary bundled by imageio-ffmpeg (a GPL build with libx264 and libx265) | GPL-2.0-or-later |
| platformdirs | MIT |
| defusedxml | PSF |
| pywebview | BSD-3-Clause |
| keyring | MIT |
| openai | Apache-2.0 |
| anthropic | MIT |

## GPL components and source

The packaged apps include these GPL components, unmodified:
- **FFmpeg 7.1**, the static build shipped by imageio-ffmpeg 0.6.0, which encodes the video with x264. Source: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz; build notes: https://github.com/imageio/imageio-ffmpeg.
- **espeak-ng** (library and data, through espeakng-loader), which turns English text into phonemes. Source: https://github.com/espeak-ng/espeak-ng.
- **phonemizer 3.4.0**. Source: https://github.com/bootphon/phonemizer.

Doodle Studio's own source for every release is this repository at the release's tag. For three years after each release, anyone can ask for the complete corresponding source of any GPL component in that release by opening an issue at https://github.com/edwardaiwang-svg/doodle-studio/issues.

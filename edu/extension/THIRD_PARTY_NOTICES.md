# Third-party notices

KinoDraw for Classroom is part of KinoDraw (https://github.com/edwardaiwang-svg/kinodraw). Its own
code is MIT-licensed; its original doodles (`assets/doodles/`, those not starting with `fl_`), narrator character and
drawing hand are CC BY 4.0. The components below keep their own licences.

## In this extension

| Component | Where | Licence |
|---|---|---|
| Microsoft Fluent Emoji, converted to outlined SVG | `assets/doodles/fl_*.svg` | MIT, © Microsoft Corporation: `assets/doodles/LICENSE-fluent-emoji.txt`; changes: `assets/doodles/NOTICE-fluent-emoji.md` |
| Playpen Sans Bold, Arimo Bold | `assets/fonts/` | SIL Open Font License 1.1: `assets/fonts/OFL-*.txt` |
| Music: *Fresh Focus* and *Natural Vibes* (Kevin MacLeod) | `assets/music/` | CC0 / public domain, via FreePD.com: `assets/music/NOTICE.md` |
| transformers.js 4.3.0 (Hugging Face) | `vendor/transformers/transformers.min.js` | Apache-2.0: `vendor/transformers/LICENSE` |
| ONNX Runtime Web (Microsoft), the build transformers.js 4.3.0 ships with | `vendor/transformers/ort-wasm-simd-threaded.asyncify.*` | MIT (below) |
| HeadTTS 1.3.0 (Mika Suominen) | `vendor/headtts/modules/` | MIT: `vendor/headtts/LICENSE` |
| HeadTTS English dictionary, generated from the CMU Pronouncing Dictionary | `vendor/headtts/dictionaries/en-us.txt` | BSD-style; the CMUdict copyright notice is kept at the top of the file |
| Mediabunny 1.60.0 (Vanilagy and contributors) | `vendor/mediabunny/mediabunny.min.mjs` | MPL-2.0: `vendor/mediabunny/LICENSE`; source: https://github.com/Vanilagy/mediabunny |
| @mediabunny/aac-encoder 1.60.0 | `vendor/mediabunny/mediabunny-aac-encoder*.{mjs,js}` | MPL-2.0 (as above). Changed only by `edu/tools/build.mjs`: its worker moved from a `blob:` URL into its own file and its `mediabunny` import pointed at the file next to it |
| FFmpeg's AAC encoder (libavcodec, libavutil), compiled to WebAssembly inside the AAC encoder's worker | `vendor/mediabunny/mediabunny-aac-encoder-worker.js` | LGPL-2.1-or-later: `licenses/LGPL-2.1.txt`. Source: https://ffmpeg.org/download.html; how this build is made: "Building and development" in https://github.com/Vanilagy/mediabunny/blob/main/packages/aac-encoder/README.md (also in the npm package @mediabunny/aac-encoder 1.60.0) |

## Downloaded on first use (not in the package)

| Component | Licence |
|---|---|
| Kokoro-82M v1.0 voice model and voices (hexgrad), ONNX export `onnx-community/Kokoro-82M-v1.0-ONNX-timestamped` | Apache-2.0 |
| BAAI bge-small-en-v1.5 (doodle search), ONNX export `Qdrant/bge-small-en-v1.5-onnx-Q` | MIT |

## ONNX Runtime licence

MIT License

Copyright (c) Microsoft Corporation

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

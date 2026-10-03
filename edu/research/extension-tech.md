# KinoDraw for Classroom: MV3 extension technical feasibility

Research date: 2026-09-26. Method: native WebSearch/WebFetch only. Primary sources were preferred: developer.chrome.com, developers.google.com, Google help centers, Chromium source, and GitHub READMEs and source. Third-party data is labeled **(3rd-party)**. Engineering inferences that no document states are labeled **(inference)**.

---

## 0. Executive summary

**Verdict:** the plan is feasible, with four real blockers and several deployment gotchas.

| # | Finding | Severity |
|---|---|---|
| 1 | **Chrome's WebCodecs AAC encoder exists only on Windows (non-N SKUs), macOS and Android.** ChromeOS and desktop Linux have none (Chromium source, `kPlatformAudioEncoder`). Chromebook-heavy elementary schools therefore need a WASM AAC fallback. The ready-made fallback, `@mediabunny/aac-encoder`, spawns its worker from a **blob: URL, and MV3 extension-page CSP forbids that**. It needs a patch or a sandboxed page. | **Blocker** (solvable) |
| 2 | `kokoro-js` (Apache-2.0) depends on `phonemizer`, which is **espeak-ng compiled to WASM (GPL-3.0)**. The package is labeled Apache-2.0, and an open issue disputes that label. Shipping it in a closed-source Chrome Web Store (CWS) extension is a license risk. `kokoro-js` also exposes **no word or phoneme timings**. **HeadTTS** (MIT, GPL-free G2P, word timestamps, en-US only) avoids both problems. | **Blocker** for closed source (solvable) |
| 3 | **All Classroom OAuth scopes are "sensitive"**, so Google must verify the app before public launch. The nominal review time is 3–5 business days; one report from July 2026 describes 6+ weeks. Until verification completes: an unverified-app screen and a 100-user lifetime cap. In "Testing" mode: 100 test users and authorizations that expire after 7 days. `drive.file` is non-sensitive. | Schedule risk |
| 4 | **K-12 admin gotchas.** In primary/secondary Workspace domains, any user the admin has not designated 18+ **defaults to under-18**. Since 2023-10-23, under-18 users are blocked from *unconfigured* third-party OAuth apps, so teachers can be blocked too unless IT sets the staff organizational unit (OU) to 18+ or configures our client ID. Classroom API "Data access" must also be on for the OU, and managed Chrome may block extension installs. | Per-district onboarding friction |
| 5 | WebCodecs is exposed only to `Window` and `DedicatedWorker`, **not** ServiceWorker or SharedWorker. The render should run in an **extension tab page plus dedicated workers**, not in the service worker. An offscreen document is allowed (it is a Window context) but has limits. | Architecture constraint |
| 6 | H.264 encoding is effectively universal in Chrome: hardware where available, with an OpenH264 software fallback that is constrained-baseline only. Opus encoding (libopus) works everywhere. **Mediabunny** (MPL-2.0, about 17 kB gzip for MP4 writing) is the muxer. `mp4-muxer` is deprecated in its favor. | OK |
| 7 | MV3 allows **data** downloads such as model weights; the Chrome definition of remote code "does not include data". All JS and WASM, including onnxruntime-web's `.mjs` and `.wasm`, **must be bundled**. The CSP needs `'wasm-unsafe-eval'`. The CWS package limit is 2 GB. `unlimitedStorage` (no install warning) exempts the extension from quota and eviction. | OK |
| 8 | `chrome.identity.getAuthToken` works in **Chrome only** (Edge does not support it). It uses the Sync account, or else the *first Google web account* in the profile. Stable Chrome cannot pick another account because `getAccounts` is dev-channel only, so a multi-account teacher may get the wrong account. Validate the token, and use `launchWebAuthFlow` with `login_hint` as the fallback. | UX gotcha |
| 9 | The `/c/<X>` segment of a Classroom URL is **not documented**. It looks like base64 of the decimal course id, but the public evidence is weak. **Match it against `alternateLink` from `courses.list` instead of decoding it.** | Minor |
| 10 | Drive resumable upload from an extension page is straightforward. Google's own browser sample reads `Location` and `Range` over CORS, and an extension page with `host_permissions` is not subject to CORS at all. | OK |

### Recommended architecture (inference, built from the constraints above)

```
classroom.google.com  (content script: injects "Make doodle video" button; reads /c/<code>)
        │ chrome.runtime.sendMessage
        ▼
sw.js (MV3 service worker): token broker (getAuthToken), opens studio tab, relays messages
        │ chrome.tabs.create({url: 'studio.html?course=<id>'})
        ▼
studio.html  (extension tab page: full chrome.* APIs, WebGPU, WebCodecs; opt into cross-origin isolation)
   ├─ tts.worker.js     (HeadTTS/Kokoro via transformers.js + bundled ORT WASM; WebGPU or WASM)
   ├─ render.worker.js  (OffscreenCanvas 2D → VideoSample → Mediabunny → H.264 + AAC MP4)
   └─ upload            (Drive resumable → Classroom courseWorkMaterials.create)
Cloudflare Worker (ours): LLM script generation + server-side teacher-gate check (out of scope here)
```

Why a **tab page** rather than the offscreen document:
- A tab page has every chrome.* API, including `identity`. An offscreen document gets **only `chrome.runtime`**.
- A tab page can show progress.
- A tab page lives as long as the tab is open.
- Only **one** offscreen document can be open per extension.

The service worker is unsuitable for the job itself:
- It is terminated after 30 s idle, or when a single request runs longer than 5 min.
- It cannot spawn workers.
- Cross-origin isolation is not implemented for service workers, so it gets no SharedArrayBuffer and no WASM threads.

Use an offscreen document (reasons `WORKERS`, `BLOBS`) only if you need rendering to continue with no extension tab open.

---

## A. In-browser video generation inside an MV3 extension

### A1. WebCodecs availability by context

The WebCodecs spec IDL for `VideoEncoder`, `AudioEncoder`, `VideoDecoder`, `AudioDecoder`, `VideoFrame` and `AudioData` is `[Exposed=(Window,DedicatedWorker), SecureContext]`. Source: https://www.w3.org/TR/webcodecs/

| Extension context | WebCodecs? | Notes |
|---|---|---|
| Extension page (popup, options, **tab page** `chrome-extension://<id>/studio.html`) | **Yes** (Window, secure context) | Full chrome.* APIs. |
| Offscreen document | **Yes** (a normal hidden DOM document, i.e. a Window context) | Only `chrome.runtime` is available; the extension API is limited to `runtime`. Reasons must be declared. |
| Dedicated worker spawned by an extension page or offscreen doc | **Yes** | The worker has **no** `chrome.*`; pass URLs and tokens via `postMessage`. Build extension URLs with `new URL('./x', self.location)`. |
| Extension **service worker** | **No** (not in the IDL) | Nor can it spawn a dedicated worker. |
| Content script | Technically yes (it runs in the page's Window), but don't | It runs under the page origin, the page CSP and CORS. |

### A1b. Which codecs Chrome can encode, per platform

**H.264 (`avc1`)**
- **Hardware:**
  - Windows: Media Foundation.
  - macOS: VideoToolbox.
  - ChromeOS: VA-API/V4L2 (hardware codec paths, general knowledge).
  - Linux: hardware encode is generally unavailable.
- **Software fallback:** Chromium's `kOpenH264SoftwareEncoder` is `FEATURE_ENABLED_BY_DEFAULT` wherever OpenH264 is compiled in (`ENABLE_OPENH264`), and it covers WebRTC, WebCodecs and MediaRecorder.
  - Source: https://chromium.googlesource.com/chromium/src/+/main/media/base/media_switches.cc
  - Background on the flag: https://issues.chromium.org/issues/40519162 (login-walled; summarized via search).
- **OpenH264 is constrained-baseline only** (3rd-party WebRTC-context sources):
  - https://bloggeek.me/webrtcglossary/h-264/
  - https://bloggeek.me/webrtc-h264-video-codec-hardware-support/
- **Measured support** (3rd-party dataset, `isConfigSupported` over ~320k sessions, https://webcodecsfundamentals.org):
  - `avc1.42001f` encode: Chrome Windows 99.83%, macOS 99.88%, **Linux 98.9%**, Android 99.79%. https://webcodecsfundamentals.org/codecs/avc1.42001f.html
  - `avc1.640028` (High 4.0) encode: Chrome Windows 99.28%, macOS 99.85%, Linux 97.14%. https://webcodecsfundamentals.org/codecs/avc1.640028.html
  - The dataset has no separate ChromeOS row.

**AAC-LC (`mp4a.40.2`): the key finding**

- Chromium `media/base/media_switches.cc` (main) defines the feature like this:
  ```cpp
  // Allows usage of OS-level (platform) audio encoders.
  BASE_FEATURE(kPlatformAudioEncoder,
  #if BUILDFLAG(IS_WIN) || BUILDFLAG(IS_MAC) || BUILDFLAG(IS_ANDROID)
  base::FEATURE_ENABLED_BY_DEFAULT
  #else
  base::FEATURE_DISABLED_BY_DEFAULT
  #endif
  );
  ```
- `media/mojo/clients/mojo_audio_encoder.cc` gates AAC on that flag. It also has a Windows-specific exclusion: *"Windows AAC encoder relies on the MediaFoundation, which is not installed for Windows N Sku."*
- `GpuMojoMediaClient::CreatePlatformAudioEncoder` has a default of `NOTIMPLEMENTED(); return nullptr;`, and the ChromeOS client (`gpu_mojo_media_client_cros.cc`) does not override it.
- **Result: no WebCodecs AAC encoding on ChromeOS or desktop Linux.**
- Sources:
  - https://chromium.googlesource.com/chromium/src/+/main/media/mojo/clients/mojo_audio_encoder.cc
  - https://chromium.googlesource.com/chromium/src/+/main/media/mojo/services/gpu_mojo_media_client.cc
  - https://chromium.googlesource.com/chromium/src/+/main/media/mojo/services/gpu_mojo_media_client_cros.cc
- MDN agrees: *"AAC encoding support in WebCodecs has notable gaps: it is not supported in Firefox on any platform, or in any browser on desktop Linux."* https://developer.mozilla.org/en-US/docs/Web/API/WebCodecs_API/Codec_selection
- **Conflict:** webcodecsfundamentals' page claims ChromeOS support, but its dataset has no ChromeOS row. I trust the Chromium source. https://webcodecsfundamentals.org/codecs/mp4a.40.2.html
- **Windows constraints.** Blink `audio_encoder.cc` accepts AAC only with channels ∈ {1, 2, 6} and, on Windows, bitrate ∈ {96000, 128000, 160000, 192000}. The Media Foundation AAC encoder takes **only 44.1 kHz or 48 kHz**, 16-bit input, 1/2/6 channels. **Kokoro outputs 24 kHz, so resample to 48 kHz before AAC.**
  - https://chromium.googlesource.com/chromium/src/+/main/third_party/blink/renderer/modules/webcodecs/audio_encoder.cc
  - https://learn.microsoft.com/en-us/windows/win32/medfound/aac-encoder

**Opus**
- Opus is a software encoder (`media::AudioOpusEncoder`) on every platform (Blink `audio_encoder.cc`).

**Drive playback formats**
- Google Drive officially plays *"MPEG4, 3GPP, and MOV files (H.264 and MPEG4 video codecs; AAC audio codec)"* and *"WebM files (VP8 video codec; Vorbis Audio codec)"*, with **max playback resolution 1920×1080**. https://support.google.com/drive/answer/2423694
- Opus in MP4 is **not** on Google's list. Treat it as unverified.

**Recommendation:** always produce **H.264 + AAC-LC 48 kHz in MP4**. Probe for native AAC first. On ChromeOS and Linux, use one of these fallbacks:
- (a) `@mediabunny/aac-encoder`, patched so its worker loads from a static file or runs inline (see A3);
- (b) run that encoder inside a **sandboxed extension page** iframe, whose CSP may allow `blob:`;
- (c) as a last resort, encode AAC in our Cloudflare Worker from the ~8 MB PCM of a 3-minute clip.

Candidate codec strings for 1080p need level 4.0 (`…28`). `avc1.42001f` is level 3.1, which is 720p-class.

```js
// studio.html or render.worker.js
const videoCandidates = ['avc1.640028', 'avc1.4D0028', 'avc1.42E028']; // High, Main, Constrained Baseline @ L4.0
let vcodec = null;
for (const codec of videoCandidates) {
  const { supported } = await VideoEncoder.isConfigSupported({
    codec, width: 1920, height: 1080, bitrate: 4_000_000, framerate: 30,
    avc: { format: 'avc' }, latencyMode: 'quality',
  });
  if (supported) { vcodec = codec; break; }
}
const aac = await AudioEncoder.isConfigSupported({
  codec: 'mp4a.40.2', sampleRate: 48000, numberOfChannels: 1, bitrate: 128000,
});
const needAacFallback = !aac.supported; // true on ChromeOS / Linux
```

### A1c. MP4 muxer: Mediabunny (the successor to mp4-muxer)

**mp4-muxer**
- MIT license.
- *"mp4-muxer has been deprecated in favor of Mediabunny, which entirely supersedes it."* https://github.com/Vanilagy/mp4-muxer

**Mediabunny**
- Repo: https://github.com/Vanilagy/mediabunny. Docs: https://mediabunny.dev/
- **License:** MPL-2.0. *"free to use for any purpose, including closed-source commercial use."* MPL is file-level copyleft, so modified Mediabunny files must stay MPL.
- **Size:** zero dependencies and tree-shakable.
  - Min+gz: **Writing .mp4 17.3 kB**, writing .webm 11.4 kB, all features 69.6 kB.
- **Encoding:** uses WebCodecs, with hardware acceleration where available.
- **Useful API:**
  - `canEncodeAudio('aac', {...})`, `getFirstEncodableVideoCodec([...])`
    - https://mediabunny.dev/guide/supported-formats-and-codecs
  - `VideoEncodingConfig`: `codec`, `bitrate: number|Quality`, `keyFrameInterval` (default 2 s), `latencyMode`, `hardwareAcceleration`, `fullCodecString`, and others.
    - https://mediabunny.dev/api/VideoEncodingConfig
  - `AudioEncodingConfig`: `codec`, `bitrate`, `transform` (for resampling and remixing), and others.
    - https://mediabunny.dev/api/AudioEncodingConfig
- **MP4 `fastStart` options** (https://mediabunny.dev/guide/output-formats):
  - `false`: metadata goes at the end of the file; least memory; not append-only.
  - `'in-memory'`: faststart; append-only; keeps chunks in RAM. This is the default with `BufferTarget`.
  - `'fragmented'`: fMP4; append-only; streamable.
  - `'reserve'`: needs `maximumPacketCount`.
- **Targets** (https://mediabunny.dev/guide/writing-media-files):
  - `BufferTarget` is *"suited for smaller files (under 100 MB)"*.
  - `StreamTarget` emits `{data, position}` chunks.
- **WASM AAC fallback:** `@mediabunny/aac-encoder` v1.60.0, labeled MPL-2.0. It is *"a fast, size-optimized WASM build of FFmpeg's AAC encoder"*; FFmpeg's AAC encoder is LGPL-2.1+, so check notice obligations.
  - Register it with `registerAacEncoder()` when `canEncodeAudio('aac')` is false.
  - https://mediabunny.dev/guide/extensions/aac-encoder

End-to-end sketch (render worker):

```js
// render.worker.js  (spawned from studio.html: new Worker('render.worker.js', { type: 'module' }))
import {
  Output, Mp4OutputFormat, BufferTarget, VideoSampleSource, AudioSampleSource,
  VideoSample, AudioSample, canEncodeAudio,
} from 'mediabunny';

const W = 1920, H = 1080, FPS = 30;
const frame = new OffscreenCanvas(W, H);
const ctx = frame.getContext('2d', { alpha: false });      // do NOT set willReadFrequently (forces CPU canvas)

const output = new Output({ format: new Mp4OutputFormat({ fastStart: 'in-memory' }), target: new BufferTarget() });
const video = new VideoSampleSource({ codec: 'avc', bitrate: 4_000_000, keyFrameInterval: 2 });
const audio = new AudioSampleSource({ codec: 'aac', bitrate: 128_000, transform: { sampleRate: 48000 } });
output.addVideoTrack(video, { frameRate: FPS });
output.addAudioTrack(audio);
await output.start();

// pcm: Float32Array @ 24 kHz mono from Kokoro/HeadTTS
await audio.add(new AudioSample({ data: pcm, format: 'f32', numberOfChannels: 1, sampleRate: 24000, timestamp: 0 }));

for (let i = 0; i < totalFrames; i++) {
  drawFrame(ctx, i / FPS);                                   // ink layer blit + new stroke segments + hand sprite
  const s = new VideoSample(frame, { timestamp: i / FPS, duration: 1 / FPS }); // seconds
  await video.add(s);                                        // awaits = encoder backpressure
  s.close();
}
await output.finalize();
postMessage({ mp4: output.target.buffer }, [output.target.buffer.buffer]); // Uint8Array
```

Two alternatives:
- For 150–200 MB outputs on 4 GB Chromebooks, prefer `StreamTarget` writing to an **OPFS** file (random-access writes via `position`), then upload that file in chunks.
- Use `fastStart: 'fragmented'` if you want to stream straight into a sequential upload.

**Encode throughput** for 1080p30 H.264 (3rd-party table): https://webcodecsfundamentals.org/basics/encoder/

| Device | Encode fps |
|---|---|
| Windows netbook (Chrome) | **11** |
| Samsung Chromebook, low tier (Chrome) | **60** |
| Ubuntu Lenovo (Chrome) | 100 |
| MacBook Pro M4 (Chrome) | 200 |

A 3-minute 30 fps video is 5,400 frames: about 8 min on the netbook and about 90 s on the Chromebook. **Offer 720p and/or 24 fps** on weak devices. Whiteboard frames are mostly static.

Bitrate guide from the same page: 1080p30 is roughly 4.5–6 Mbps (YouTube guidance). Whiteboard content compresses well, so 2–4 Mbps is plenty (inference). At 4 Mbps a 3-minute video is about 90 MB.

### A2. OffscreenCanvas + Canvas2D at 1920×1080

**Availability and APIs**
- OffscreenCanvas has 2D, WebGL and bitmaprenderer contexts, works in workers, and has been in Chrome since 69; it is Baseline since 2023-03.
  - https://developer.mozilla.org/en-US/docs/Web/API/OffscreenCanvas
  - https://web.dev/articles/offscreen-canvas
- `new VideoFrame(offscreenCanvas, { timestamp /* µs */ })` accepts an OffscreenCanvas. Always `close()` frames. Mediabunny's `VideoSample(canvas, {timestamp, duration})` uses seconds.
  - https://developer.mozilla.org/en-US/docs/Web/API/VideoFrame/VideoFrame
- `new Path2D(svgPathData)` accepts SVG `d` strings and **is available in Web Workers**. https://developer.mozilla.org/en-US/docs/Web/API/Path2D/Path2D
- Workers have no DOM, so neither `DOMParser` nor `SVGPathElement.getTotalLength()` is available there. Use **svg-path-properties** (MIT) for `getTotalLength` / `getPointAtLength` / tangents, which place the "hand" at the pen tip. Or pre-parse SVGs on the studio page.
  - https://github.com/rveciana/svg-path-properties

**Limits**
- MDN: *"in most cases the maximum dimensions exceed 10,000 x 10,000 pixels"* (iOS is 4096²). 1080p is nowhere near the limit. https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/canvas

**Performance**
- **Don't set `willReadFrequently: true`.** It switches the canvas to CPU raster. Reads get faster, but draws get much slower.
  - https://developer.chrome.com/blog/taking-advantage-of-gpu-acceleration-in-the-2d-canvas
  - 3rd-party measurement: https://www.schiener.io/2024-08-02/canvas-willreadfrequently
- Recommended per-frame pattern (inference):
  1. Keep a persistent "ink" OffscreenCanvas and add only the new stroke segment each frame (`setLineDash([drawn, total])` on a Path2D, or incremental polylines).
  2. `drawImage(ink)` onto the frame canvas.
  3. Draw the hand as an `ImageBitmap`.
  4. Snapshot the frame.
- That is two full-frame blits per frame, which is trivial on GPU raster. The encoder dominates the cost (see the A1c table). With a GPU canvas and a hardware encoder, Chrome can avoid a CPU readback; the software (OpenH264) path pays a readback plus an RGB→YUV conversion per frame (inference). **Measure on a low-end Chromebook.**
- Drive the loop with `await source.add()` promises, **not** `requestAnimationFrame` or timers. That avoids throttling when the tab is hidden (inference).

### A3. MV3 rules that matter

**Remote code ban (bundle every JS and WASM file)**
- Chrome: *"Remotely hosted code, or RHC, is what the Chrome Web Store calls anything that is executed by the browser that is loaded from someplace other than the extension's own files. Things like JavaScript and WASM. It does not include data or things like JSON or CSS."* https://developer.chrome.com/docs/extensions/develop/migrate/remote-hosted-code
- The CWS MV3 requirements permit *"fetching remote resources that are not used to evaluate logic, such as images"* and remote configuration where *"logic stays in the package"*. They prohibit remote script tags, `eval()` of fetched strings, and *"interpreters running remote commands, even as data"*. https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements
- **Model weights are data.** Precedent: HF's April 2026 official guide runs transformers.js in an MV3 extension and downloads models at runtime into the extension-origin cache. https://huggingface.co/blog/transformersjs-chrome-extension
- Keep review clean: fetch model files from a pinned URL on your own R2/CDN (or HF), **verify their SHA-256 against a hash shipped in the package**, and say so in the CWS listing (inference; this makes the data-not-logic argument explicit).
- **onnxruntime-web's `.mjs` and `.wasm` default to jsDelivr.** Two real cases:
  - An extension was **rejected** for *"including remotely hosted code in a Manifest V3 item"*: https://github.com/huggingface/transformers.js/issues/839
  - A dynamic import of `ort-wasm-simd-threaded.jsep.mjs` from jsDelivr failed with *"Failed to fetch dynamically imported module"*: https://github.com/huggingface/transformers.js/issues/1248
- The fix is to bundle them and set `env.backends.onnx.wasm.wasmPaths`, or kokoro-js's `env.wasmPaths`, to the extension URL.
- Sizes for transformers.js 3.7.6: `ort-wasm-simd-threaded.jsep.wasm` is **21.6 MB**; the `.mjs` is 44 KB. https://data.jsdelivr.com/v1/packages/npm/@huggingface/transformers@3.7.6?structure=flat

**CSP**
- The default `extension_pages` CSP is `script-src 'self'; object-src 'self';`.
- The minimum allowed is `"script-src 'self' 'wasm-unsafe-eval'; object-src 'self';"`, so **you must add `'wasm-unsafe-eval'` for any WASM**.
- `'unsafe-eval'` is rejected with: *"Insecure CSP value "'unsafe-eval'" in directive 'script-src'"*.
- Sandbox pages have a lenient default (`'unsafe-inline' 'unsafe-eval'`, customizable) but no extension APIs.
- https://developer.chrome.com/docs/extensions/reference/manifest/content-security-policy

**Workers from blob: or data: URLs are refused in extension pages**
- The Chrome DevRel thread (2023-07-07) shows data: in `worker-src` rejected with *"Insecure CSP value "data:" in directive 'worker-src'"*.
- The advice there: use static worker files, or put dynamic code in a **sandbox page** with `"script-src 'self' 'unsafe-inline' blob:"`.
- https://groups.google.com/a/chromium.org/g/chromium-extensions/c/nQp-Dtc7q6k
- **Impact:** `@mediabunny/aac-encoder` builds its worker with an esbuild plugin that does:
  ```js
  const blob = new Blob([scriptText], { type: "text/javascript" });
  const url = URL.createObjectURL(blob);
  const worker = new Worker(url, ...)
  ```
  That will be refused in an extension page. Source: https://raw.githubusercontent.com/Vanilagy/mediabunny/main/scripts/esbuild/inlined-workers.ts
- Fix: patch the build to emit a static `encode.worker.js`, or host the encoder in a sandboxed iframe.
- Note: `phonemizer.js` runs its espeak WASM **inline**, with no worker. https://raw.githubusercontent.com/xenova/phonemizer.js/main/src/phonemizer.js

**Offscreen document API** (https://developer.chrome.com/docs/extensions/reference/api/offscreen)
- Requires the `"offscreen"` permission; Chrome 109+.
- Valid reasons: `TESTING`, `AUDIO_PLAYBACK`, `IFRAME_SCRIPTING`, `DOM_SCRAPING`, `BLOBS`, `DOM_PARSER`, `USER_MEDIA`, `DISPLAY_MEDIA`, `WEB_RTC`, `CLIPBOARD`, `LOCAL_STORAGE`, `WORKERS`, `BATTERY_STATUS`, `MATCH_MEDIA`, `GEOLOCATION`.
  - `WORKERS`: *"needs to spawn workers"*.
  - `BLOBS`: *"needs to interact with Blob objects (including URL.createObjectURL())"*.
- *"an installed extension can only have one open at a time."*
- `AUDIO_PLAYBACK` closes the document after 30 s without audio; *"All other reasons don't set lifetime limits."*
- *"The runtime API is the only extensions API supported by offscreen documents."*
- `createDocument({url, reasons, justification})`: the URL must be a static HTML file bundled in the package. Check for an existing one with `runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})`.

**Service worker lifetime** (https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)
- Terminated *"After 30 seconds of inactivity"*.
- Terminated *"When a single request… takes longer than 5 minutes"*.
- Terminated *"When a fetch() response takes more than 30 seconds to arrive"*.
- Messages from an offscreen document reset the timers.
- 3rd-party write-up of moving transformers.js out of the SW for these reasons (2026-05-26): https://dev.to/sathiyasenpai/why-i-moved-my-transformersjs-pipeline-out-of-the-chrome-mv3-service-worker-and-into-an-offscreen-1kk4

**Cross-origin isolation** (for SharedArrayBuffer, and therefore multithreaded ORT WASM)
- Manifest keys `cross_origin_embedder_policy: {value: "require-corp"}` and `cross_origin_opener_policy: {value: "same-origin"}`, Chrome 93+.
- Caveat: *"Cross-origin isolation is not fully implemented for service and shared workers currently."*
- https://developer.chrome.com/docs/extensions/develop/concepts/cross-origin-isolation
- https://developer.chrome.com/docs/extensions/reference/manifest/cross-origin-embedder-policy
- Verify `self.crossOriginIsolated === true` in the studio page and, if you use one, the offscreen document.

**WebGPU**
- Available in extension pages and workers.
- Available in **extension service workers since Chrome 124**. https://developer.chrome.com/blog/new-in-webgpu-124
- Enabled by default on Windows, macOS, ChromeOS and Android. On Linux it is still rolling out (Chrome 144 beta, Intel Gen12+), per 3rd-party sources: https://github.com/gpuweb/gpuweb/wiki/Implementation-Status

**Storage for a ~90–330 MB model**
- IndexedDB and Cache Storage work in extension pages, workers and the service worker; localStorage does not work in the service worker.
- `unlimitedStorage` *"affects both extension and web storage APIs and exempts extensions from both quota restrictions and eviction."*
- *"Extension storage is not cleared when a user clears browsing data."*
- https://developer.chrome.com/docs/extensions/develop/concepts/storage-and-cookies
- Per the permission list, `unlimitedStorage` covers `chrome.storage.local`, IndexedDB, Cache Storage and **OPFS**, with **no install warning**. https://developer.chrome.com/docs/extensions/reference/permissions-list
- transformers.js caches to Cache API `transformers-cache` by default (`env.useBrowserCache`).

**Package size**
- *"The maximum supported file size for an extension package is 2GB. Zip files larger than 2GB will be rejected."* https://developer.chrome.com/docs/webstore/publish
- Bundling the 92 MB q8 model is allowed. It inflates install size and every update (inference), so prefer a first-run download plus Cache API.

Manifest sketch:

```json
{
  "manifest_version": 3,
  "name": "KinoDraw for Classroom",
  "version": "0.1.0",
  "minimum_chrome_version": "124",
  "key": "<single-line public key from CWS dashboard → Package → View public key>",
  "permissions": ["identity", "storage", "unlimitedStorage", "offscreen"],
  "optional_host_permissions": ["https://www.googleapis.com/*", "https://classroom.googleapis.com/*"],
  "oauth2": {
    "client_id": "<id>.apps.googleusercontent.com",
    "scopes": [
      "https://www.googleapis.com/auth/classroom.courses.readonly",
      "https://www.googleapis.com/auth/classroom.courseworkmaterials",
      "https://www.googleapis.com/auth/drive.file"
    ]
  },
  "background": { "service_worker": "sw.js", "type": "module" },
  "content_scripts": [{ "matches": ["https://classroom.google.com/*"], "js": ["content.js"], "run_at": "document_idle" }],
  "content_security_policy": { "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self';" },
  "cross_origin_embedder_policy": { "value": "require-corp" },
  "cross_origin_opener_policy": { "value": "same-origin" }
}
```

Google APIs support CORS, so `host_permissions` are optional. Declaring them removes all CORS concerns but adds an install warning (inference).

---

## B. Kokoro TTS in the browser

### B1. kokoro-js facts

**Package and license**
- `kokoro-js` **v1.2.1** is the latest release, **Apache-2.0**. Its dependencies are `@huggingface/transformers ^3.5.1` (the v3 line; transformers.js latest is 4.3.0) and `phonemizer ^1.2.1`.
  - https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro.js/package.json
  - https://data.jsdelivr.com/v1/packages/npm/kokoro-js
- Model: `onnx-community/Kokoro-82M-v1.0-ONNX`, 82M params. Model card license: **Apache 2.0**. https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX

**API** (https://github.com/hexgrad/kokoro/tree/main/kokoro.js)
- `KokoroTTS.from_pretrained(model_id, { dtype, device, progress_callback })`.
- `dtype` is one of `"fp32" | "fp16" | "q8" | "q4" | "q4f16"`. `device` is one of `"wasm"` (default), `"webgpu"`, `"cpu"` (Node).
- README: *"If using "webgpu", we recommend using dtype="fp32"."*
- `generate()` returns a `RawAudio` at **24,000 Hz**.
- `stream(TextSplitterStream)` yields `{ text, phonemes, audio }` per sentence chunk.
- Input is clamped at about 509 tokens per call, so split by sentence.
  - Source: https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro.js/src/kokoro.js

**Model file sizes** by dtype (https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/tree/main/onnx):

| dtype (kokoro-js) | file | size |
|---|---|---|
| fp32 | `model.onnx` | **326 MB** |
| fp16 | `model_fp16.onnx` | 163 MB |
| q8 | `model_quantized.onnx` | **92.4 MB** (this is your "~90 MB") |
| q4 | `model_q4.onnx` | 305 MB |
| q4f16 | `model_q4f16.onnx` | 155 MB |
| (not a kokoro-js option) | `model_q8f16.onnx` / `model_uint8.onnx` / `model_uint8f16.onnx` | 86 / 177 / 114 MB |

**Trade-off:** the fast WebGPU path wants fp32, which is a **326 MB** download. WASM works with q8 at 92 MB. fp16 on WebGPU at 163 MB is worth testing when the adapter has `shader-f16` (inference).

**Voices**
- Each voice file is `.bin`, **522,240 bytes (~510 KB)**. The npm package ships 60 voice files (31.3 MB) for Node.
- In the browser, voices are fetched from `https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/voices/<id>.bin`, with a Cache API cache named `kokoro-voices`.
- `setVoiceDataUrl()` exists in `src/voices.js` but is **not re-exported** from the package entry. The entry exports only `KokoroTTS`, `TextSplitterStream`, and `env` with `cacheDir` / `wasmPaths`.
- So to self-host voices, patch or alias the module, or wrap `fetch` in the worker.
- Sources:
  - https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro.js/src/voices.js
  - https://data.jsdelivr.com/v1/packages/npm/kokoro-js@1.2.1?structure=flat

**Timing output**
- **None.** The model call returns only `{ waveform }`, so kokoro-js exposes no durations or alignment.
- A separate export, `onnx-community/Kokoro-82M-v1.0-ONNX-timestamped`, outputs per-token **durations**. Frames are at **80 per second**: 24 kHz with a 300-sample hop; the "magic divisor 80".
  - https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX-timestamped
  - https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX-timestamped/discussions/2
- One author confirms *"the public ONNX and kokoro-js path do not expose the native model alignment output"* and falls back to per-sentence chunk timing (3rd-party). https://ryanwelch.co.uk/blog/kokoro-word-timestamps/
- Sentence-level sync is still free: each `stream()` chunk is one sentence, and its duration is `audio.length / 24000`.

**License risk (important)**
- `phonemizer` (xenova/phonemizer.js) wraps espeak-ng compiled to WASM. `dist/phonemizer.js` is 1.32 MB.
- The package's LICENSE is Apache-2.0, but **espeak-ng is GPL-3.0**. Open issue #6 (2026-01-26): *"eSpeak NG is licensed under GPLv3, so any modification (such as this library) also needs to be licensed using GPL."* There has been no maintainer response.
  - https://github.com/xenova/phonemizer.js/issues/6
  - https://github.com/hexgrad/kokoro/issues/247
  - https://data.jsdelivr.com/v1/packages/npm/phonemizer@1.2.1?structure=flat
- Options:
  - (1) Ship the extension as GPL-3.0-compatible open source.
  - (2) Use a GPL-free G2P (HeadTTS, below).
  - (3) Do G2P in our Worker: running GPL code server-side is not distribution under GPLv3 (inference, not legal advice). Then call Kokoro with phoneme ids in the browser. kokoro-js has `generate_from_ids()`.

**Where it can run**
- **Dedicated worker** spawned by an extension page: **yes**. Bundle the ORT files, set `wasmPaths` to `new URL('./ort/', self.location).href`, and cross-origin isolate the page for multi-thread WASM.
- **Offscreen document:** **yes** (Window context). Use reason `WORKERS` if it spawns workers.
- **Service worker:** transformers.js does run there (the HF guide), and WebGPU works since Chrome 124. But there are no nested workers, no SharedArrayBuffer and a 30 s idle kill, so it is **not recommended** for a multi-minute TTS job.

**Loading from a bundled or self-hosted URL**
- transformers.js `env` settings (https://huggingface.co/docs/transformers.js/api/env):
  - `allowRemoteModels` (default true)
  - `remoteHost` (default the HF Hub)
  - `remotePathTemplate`
  - `allowLocalModels` (**default false in browser**)
  - `localModelPath` (default `/models/` URL path in browsers)
  - `useBrowserCache` (default true)
  - `useWasmCache`
  - `customCache`
  - `fetch` override
- In an extension page, `/models/` resolves to `chrome-extension://<id>/models/`.

```js
// tts.worker.js
import { KokoroTTS, env as kenv } from 'kokoro-js';
import { env } from '@huggingface/transformers';      // same instance after bundling/dedupe
kenv.wasmPaths = new URL('./ort/', self.location).href;  // bundled ort-wasm-simd-threaded.jsep.{mjs,wasm}
// Option A: self-hosted data mirror (allowed: data, not code)
env.remoteHost = 'https://models.example.org/';          // R2 mirror of onnx-community/Kokoro-82M-v1.0-ONNX
// Option B: bundled in the package
// env.allowRemoteModels = false; env.allowLocalModels = true; env.localModelPath = new URL('./models/', self.location).href;
const adapter = 'gpu' in navigator ? await navigator.gpu.requestAdapter() : null;
const device = adapter ? 'webgpu' : 'wasm';
const tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX',
  { dtype: device === 'webgpu' ? 'fp32' : 'q8', device });
const raw = await tts.generate('The water cycle has four steps.', { voice: 'af_heart' }); // raw.audio: Float32Array @ 24 kHz
```

### B2. Measured speed (all 3rd-party or project READMEs; no official Kokoro benchmark exists)

- **HeadTTS README** (M2 MacBook Air, Chrome, Kokoro): in-browser **WebGPU real-time factor (RTF) 0.27**, about 3.7× faster than real time. **WASM RTF 1.45**, slower than real time. https://github.com/met4citizen/HeadTTS
- **Aloud PR #15** (Chromium in a container): kokoro-js **q8 WASM is 3.5× slower than real time single-threaded and 2.0× slower with 4 threads**, which needs COOP/COEP. A 7-second sentence took 11.9 s threaded vs 16.1 s unthreaded; process memory was ~0.68 GB. https://github.com/WestSmith/Aloud/pull/15
- **quick-tts.com** (2026-05-10, kokoro-js 1.2.1 WebGPU, Chrome 134):

  | GPU | Throughput | Notes |
  |---|---|---|
  | RTX 4070 | 6.5× real time | |
  | M3 Pro | 3.2× | |
  | M2 Air | 2.4× | |
  | Intel Arc A380 | 1.3× | |
  | **Intel UHD 770** | **0.6×** | Some out-of-memory errors |

  Cold load took 7–18 s. Caveat: the article calls fp32 "~80 MB", which conflicts with HF's 326 MB, so treat its numbers as indicative. https://quick-tts.com/blog/kokoro-webgpu-benchmarks.html
- **Implication** (inference): on low-end Chromebooks and Intel iGPUs, expect TTS **slower than real time**. A 3-minute script could take about 5–10+ min. Show progress, cache per-sentence audio, and keep a server-TTS fallback in mind.

### B3. Smallest viable English voice list

Grades come from kokoro-js `voices.js`. Each voice is about 510 KB, so bundling 3–4 voices costs about 1.5–2 MB:

| Voice | Accent / gender | Grade | Role |
|---|---|---|---|
| **af_heart** | US F | **A** | Default |
| **af_bella** | US F | **A-** | Alternate |
| **am_michael** / **am_fenrir** / **am_puck** | US M | C+ | Pick one male voice |
| **bf_emma** | UK F | B- | Only if a British option is wanted |

HeadTTS demos use `af_bella` and `am_fenrir`.

### B4. Alternatives

- **HeadTTS** (`met4citizen/HeadTTS`, **MIT**). **Top recommendation.**
  - Same Kokoro model, using the `Kokoro-82M-v1.0-ONNX-timestamped` export.
  - **GPL-free G2P:** *"doesn't use eSpeak or any other GPL-licensed module"*. It uses the CMU dictionary (~125k entries, simplified BSD) plus NRL-7948 letter-to-sound rules.
  - Returns **word timings in ms** (`words`, `wtimes`, `wdurations`) plus phonemes and visemes (`vtimes`, `vdurations`).
  - Runs inference in a **module Web Worker**.
  - Limitation: **American English only**.
  - Defaults to change for MV3:
    - `transformersModule` defaults to the jsDelivr URL `…/@huggingface/transformers@4.0.0/dist/transformers.min.js`. That is **remote code; bundle it and point this option at the local file**.
    - `voiceURL` defaults to HF; change it to self-hosted.
    - Other defaults: `dtypeWebgpu: "fp32"`, `dtypeWasm: "q4"` (305 MB; switch to q8), `dictionaryURL: "../dictionaries"`.
  - https://github.com/met4citizen/HeadTTS
- **KittenTTS:** Apache-2.0, 15M–80M params (about 25–80 MB), with browser ports via transformers.js/ORT. It also relies on an espeak-style phonemizer, so check G2P licensing. Quality sits below Kokoro (3rd-party).
  - https://github.com/KittenML/KittenTTS
  - https://github.com/clowerweb/kitten-tts-web-demo
- **Piper:** avoid for a closed extension. `rhasspy/piper` (MIT) was archived in 2025-10, and development moved to **OHF-Voice/piper1-gpl (GPL-3.0)**. Browser ports are `@mintplex-labs/piper-tts-web`, MIT, but its `piper_phonemize.data` bundles espeak-ng data under GPL-3.0-or-later. https://github.com/ayutaz/piper-plus/blob/dev/README_EN.md
- **Web Speech API / `chrome.tts`:** not usable. There is no way to capture the synthesized audio as PCM for encoding (inference, from the API shape).
- **Server fallback:** TTS in our Worker for weak devices. This breaks the "in-browser" requirement, so treat it only as an emergency path.

---

## C. Google Classroom integration from an extension

### C1. `chrome.identity`: `getAuthToken` vs `launchWebAuthFlow`

| | `getAuthToken` | `launchWebAuthFlow` |
|---|---|---|
| Browsers | **Chrome only.** Edge lists `identity.getAuthToken` as **not supported** and says to use `launchWebAuthFlow` ([MS docs](https://learn.microsoft.com/en-us/microsoft-edge/extensions/developer-guide/api-support)) | Chrome and Edge |
| OAuth client | Google Cloud → Create Client → **"Chrome Extension"**, **Item ID = extension ID**. Ownership can be verified against the CWS item ([Chrome how-to](https://developer.chrome.com/docs/extensions/how-to/integrate/oauth), [Google help](https://support.google.com/cloud/answer/15549257)). Inactive clients are auto-deleted after 6 months. | **Web application** client with redirect URI `https://<extension-id>.chromiumapp.org/*` (`chrome.identity.getRedirectURL()`) |
| Which account | *"If not specified, the function will use an account from the Chrome profile: the **Sync account if there is one, or otherwise the first Google web account**."* The `account` field needs `AccountInfo.id`, but *"`getAccounts` is only supported on dev channel."* ([API ref](https://developer.chrome.com/docs/extensions/reference/api/identity)) | Any account. Control it with `login_hint` / `prompt=select_account` |
| Token lifetime | *"The Identity API caches access tokens in memory, so it's ok to call getAuthToken non-interactively any time a token is required. The token cache automatically handles expiration."* Chrome 105+ returns a Promise of `{token, grantedScopes}`; granular consent via `enableGranularPermissions` (Chrome 87+) | Implicit flow gives ~1 h tokens and **no refresh token**. Google calls implicit flow insecure for SPAs and recommends auth code + PKCE ([doc](https://developers.google.com/identity/protocols/oauth2/javascript-implicit-flow)). Silent re-auth via `interactive:false` plus `abortOnLoadForNonInteractive` / `timeoutMsForNonInteractive` (Chrome 113+), or a code exchange in our Worker (then our server holds refresh tokens) |
| Not signed in to Chrome | With `interactive:true` it prompts as needed. It can use web-only signed-in accounts ("first Google web account") | N/A |

**Pinning the ID of an unpacked build**
- Upload the zip to the CWS dashboard (unpublished), open **Package → View public key**, strip the newlines, and paste the result as `"key"` in the manifest. That keeps the ID stable, so the Chrome Extension OAuth client matches.
- https://developer.chrome.com/docs/extensions/reference/manifest/key
- https://developer.chrome.com/docs/extensions/how-to/integrate/oauth

**Gotchas**
- A teacher with a personal account signed in first may get a token for the **wrong account**. After `getAuthToken`, confirm the account (for example via the `courses.list` result, or `openid email`). If it is wrong, fall back to `launchWebAuthFlow` with `login_hint=<school email>`.
  - The account the teacher is using in Classroom can be read by the content script from the Classroom UI (inference).
- Historical reports describe getAuthToken showing an account picker and "remembering" the choice (Chrome 98, 2022). `clearAllCachedAuthTokens()` (Chrome 87+) helps reset it. https://groups.google.com/a/chromium.org/g/chromium-extensions/c/4OX3cv_wepY
- `getAuthToken` fits school Chromebooks well: the profile's primary or sync account is the school account.
- **Google Identity Services' JS (`accounts.google.com/gsi/client`) cannot be loaded in extension pages** because it is remote code (inference from the RHC rules), so `chrome.identity` is the path.

### C2. Scopes, teacher check, upload, post

| Purpose | Call | Minimal scope | Class |
|---|---|---|---|
| List the teacher's classes (**the robust teacher gate**) | `GET https://classroom.googleapis.com/v1/courses?teacherId=me&courseStates=ACTIVE` | `classroom.courses.readonly` (or `classroom.courses`) | Sensitive |
| Confirm teacher of one course | `GET /v1/courses/{courseId}/teachers/me` (`userId` may be `"me"`, an email or an id) | `classroom.rosters` / `.rosters.readonly` / `.profile.emails` / `.profile.photos` | Sensitive |
| Profile flags | `GET /v1/userProfiles/me` | Same four scopes as above | Sensitive |
| Upload MP4 | `POST https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable` | **`drive.file`** | **Non-sensitive (recommended)** |
| Post as class material | `POST /v1/courses/{courseId}/courseWorkMaterials` | `classroom.courseworkmaterials` | Sensitive |
| Or post as announcement | `POST /v1/courses/{courseId}/announcements` | `classroom.announcements` | Sensitive |

Endpoint references:
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses/list
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.teachers/get
- https://developers.google.com/workspace/classroom/reference/rest/v1/userProfiles/get
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWorkMaterials/create
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.announcements/create
- Scope list: https://developers.google.com/workspace/classroom/guides/auth
- Drive scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth

**UserProfile field semantics**
- `verifiedTeacher`: *"Represents whether a Google Workspace for Education user's domain administrator has explicitly verified them as being a teacher. This field is always false if the user is not a member of a Google Workspace for Education domain. Read-only."*
- `permissions[]`: `GlobalPermission { permission }`, where `CREATE_COURSE` means *"User is permitted to create a course."*
- `emailAddress` needs `classroom.profile.emails`.
- https://developers.google.com/workspace/classroom/reference/rest/v1/userProfiles
- `CREATE_COURSE` is **not proof of being a teacher**. Admins choose who can create classes: *"Anyone in this domain"* (which includes students), *"All pending and verified teachers"*, or *"Verified teachers only"*. Users who pick "teacher" become **pending** members of the Classroom Teachers group until an admin approves them. https://support.google.com/edu/classroom/answer/6071551
- `verifiedTeacher` is always false for consumer (Gmail) teachers, and for schools that never verify teachers.
- Google's own guidance: *"The easiest way to discover users that are teachers within any given Course is by using the courses.teachers.list() or courses.teachers.get() endpoints."* https://developers.google.com/workspace/classroom/guides/key-concepts/user-types

**Recommended gate** (inference): `courses.list(teacherId='me', courseStates=ACTIVE)` returns ≥1 course. Optionally require `verifiedTeacher` when the domain is Workspace for Education. Repeat the check server-side in our Worker before spending LLM credits, by calling `courses.list` with the forwarded token. That keeps the scope set minimal: `courses.readonly`, `courseworkmaterials`, `drive.file`, plus optional `openid email`.

**Posting details**
- **CourseWorkMaterial** (https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWorkMaterials):
  - title 1–3000 chars; description ≤30,000 chars
  - ≤20 materials
  - `state` is `PUBLISHED` (default), `DRAFT` or `DELETED`
  - `alternateLink` is populated only when PUBLISHED
  - `scheduledTime`, `topicId`, `assigneeMode` (default `ALL_STUDENTS`)
- **Material** (https://developers.google.com/workspace/classroom/reference/rest/v1/Material):
  - `driveFile: { driveFile: { id }, shareMode }`
  - shareMode defaults to `VIEW`; other values are allowed only on ASSIGNMENT coursework, so **use VIEW for materials**.
- **Errors** (https://developers.google.com/workspace/classroom/reference/Request.Errors):
  - `PERMISSION_DENIED` when the user cannot create in the course or *cannot share Drive attachments*.
  - `FAILED_PRECONDITION: AttachmentNotVisible`.
  - `ClassroomApiDisabled` when the admin turned off data access.
  - `ProjectPermissionDenied`: only the Cloud project that created an item can modify it later.

```js
await fetch(`https://classroom.googleapis.com/v1/courses/${courseId}/courseWorkMaterials`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({
    title: 'The Water Cycle (doodle video)',
    description: 'Watch this 3-minute video.',
    materials: [{ driveFile: { driveFile: { id: driveFileId }, shareMode: 'VIEW' } }],
    state: 'PUBLISHED' // or 'DRAFT' so the teacher reviews before students see it
  }),
});
```

**Verification requirements**
- *"Apps that request access to scopes categorized as sensitive or restricted must complete Google's OAuth app verification."* https://support.google.com/cloud/answer/13463073
- The **restricted** list covers Gmail, Drive (full `drive`, `drive.readonly`, `drive.metadata*`, …), Fit, Chat, Data Portability, Photos Ambient and Health, and **no Classroom scopes**. https://support.google.com/cloud/answer/13464325
- Classroom scopes show as *sensitive* in the console. Evidence: a 2026-07-06 developer post says *"Requested scopes (all sensitive; no restricted scopes)"*, with verification stuck for 6+ weeks. https://discuss.google.dev/t/oauth-verification-stuck-6-weeks-sensitive-google-classroom-scopes-no-trust-safety-email-project-eduvetra/378317
- **Sensitive-scope verification** needs:
  - a privacy policy on the **same domain** as the homepage, linked from the consent screen;
  - a public homepage;
  - a **demo video** showing the consent flow and use of each scope;
  - a per-scope justification, including why a narrower scope won't do;
  - domain verification in Search Console.
  - *"typically takes 3-5 business days."* https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- **Until verified** (https://support.google.com/cloud/answer/15549945, https://support.google.com/cloud/answer/7454865, https://support.google.com/cloud/answer/13464323):
  - An unverified-app screen, and *"100 new users in total, after the app presents the unverified app screen"*.
  - "Testing" status: *"limited to up to 100 test users"* and *"Authorizations by a test user will expire seven days from the time of consent"*.
  - Exceptions: internal-only apps (same Workspace org) and admin-trusted apps.

### C3. Workspace for Education admin-side gotchas

1. **Classroom API data access.** Admin console → Apps → Google Workspace → Classroom → **Data access** → Classroom API: *"check or uncheck the box to allow users to grant access to their Classroom data."* It is configurable per OU. The doc does not state the default. If it is off, calls fail with `ClassroomApiDisabled`.
   - https://support.google.com/edu/classroom/answer/6250906
   - https://support.google.com/edu/classroom/answer/6253304
2. **API Controls → App access control** (Security → Access and data control → API controls → **Configure new app**, searching by name or **OAuth client ID**).
   - Access levels:
     - *"Trusted—Can access all Google services (both restricted and unrestricted)"*
     - *"Limited—Can only access unrestricted Google services"*
     - *"Specific Google data"*
     - *"Blocked"*
   - Unconfigured-app options:
     - *"Allow users to access any third-party apps"* (default)
     - *"…only request basic info needed for Sign in with Google"*
     - *"Don't allow users to access any third-party apps"*
   - If an admin marks Classroom as a **Restricted** service, only Trusted or Specific-data apps can use it.
   - https://knowledge.workspace.google.com/admin/apps/control-which-apps-access-google-workspace-data
3. **Under-18 rule.**
   - Since **2023-10-23**, *"Users designated as under 18 using the age-based access setting are required to request access to apps that aren't already configured by admins with a trusted, limited, or blocked access setting."* https://workspaceupdates.googleblog.com/2023/08/third-party-app-access-enhancements-for-google-workspace-edu.html
   - They are *"blocked, but see a message with the option to request access"*. Admins can allow basic-info-only apps. https://knowledge.workspace.google.com/admin/getting-started/editions/manage-access-to-unconfigured-third-party-apps-for-users-designated-as-under-18
   - **Critical K-12 default:** *"All users in primary and secondary institutions who are not designated as over 18 default to under 18."* Google recommends setting staff and teacher OUs to "18 or older". https://knowledge.workspace.google.com/admin/getting-started/editions/control-access-to-google-services-by-age
   - So in a district that never set staff to 18+, **teachers are blocked too** until IT configures our client ID or fixes the age setting.
   - **Students** are blocked by default: they are under-18 and our app is unconfigured. They are also blocked by our teacher gate.
   - Users in the error flow see *"Access blocked: Your institution's admin needs to review [app name]"*. https://support.google.com/edu/classroom/answer/11081157
4. **Extension install policy on managed Chrome/Chromebooks.** Admins can set "Block all apps, admin manages allowlist, users may request extensions".
   - https://support.google.com/chrome/a/answer/6177431
   - https://support.google.com/chrome/a/answer/10405494
5. **Why not Classroom add-ons:** they require **Education Plus or the Teaching & Learning add-on** license (3rd-party summary). The REST-API extension route avoids that. https://developers.google.com/workspace/classroom/add-ons/requirements

A per-district onboarding doc for IT should cover: our OAuth client ID, the Trusted or Specific-data setting, the staff OU set to 18+, Classroom API data access on, and the extension allowlisted.

### C4. Classroom web URL course id

- **Not documented by Google.** Google's docs only say course ids are Classroom-assigned (or aliases) and that `Course.alternateLink` is the absolute UI link.
- **Weak public evidence:** the 2015 GAM wiki example shows `alternateLink: http://classroom.google.com/c/MtM0NzcxNDY5` next to `id: 134781269`. https://github.com/GAM-team/GAM/wiki/Managing-Google-Classroom/ef806dcf29501eb1e18a781493d5c5c0c66ecf3a
  - `MTM0NzcxNDY5` is exactly base64 of the ASCII digits `134771469`, verified locally. The example id differs in two digits and has one lowercase letter, which looks like an anonymized example.
  - Structurally, base64 of ASCII digits always starts with `M`, `N` or `O`, which matches the codes seen in Classroom URLs. That is suggestive, not proof.
- **Multi-account paths:** `/u/<n>/` is Google's per-browser session index (0 = first signed-in account). It is not part of the id and is not stable across sign-in changes. It says nothing about which account our OAuth token belongs to. https://ourcodeworld.com/articles/read/2414/what-the-u-0-and-u-1-in-gmail-urls-and-other-google-apps-really-mean (3rd-party)
- **Robust approach:** match the URL code against `alternateLink` from `courses.list`. Use base64 decoding only as a heuristic, then confirm with `courses.get`.

```js
// content.js on classroom.google.com
const m = location.pathname.match(/^(?:\/u\/\d+)?\/c\/([A-Za-z0-9_-]+)/);
const urlCode = m?.[1];
// preferred: exact match via API (courses.list teacherId=me)
const course = courses.find(c => c.alternateLink && new URL(c.alternateLink).pathname.endsWith('/c/' + urlCode));
// heuristic fallback (undocumented): decimal id encoded as base64
let guess = null; try { const s = atob(urlCode.replace(/-/g,'+').replace(/_/g,'/')); if (/^\d+$/.test(s)) guess = s; } catch {}
```

Verify the pattern once on a **test teacher account** before relying on the heuristic.

### C5. Drive upload of 50–200 MB from the browser

Source: https://developers.google.com/workspace/drive/api/guides/manage-uploads

**Rules**
- Simple and multipart uploads are limited to **≤5 MB**, so use **resumable**.
- Initiate with `POST https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable`, a JSON metadata body, and optional `X-Upload-Content-Type` / `X-Upload-Content-Length` headers.
- The response is `200` with a **`Location`** header: the session URI, which *"expires after one week."*
- Upload either in one `PUT`, or in chunks that are **multiples of 256 KiB (262,144 bytes)** except the last, each with `Content-Range: bytes start-end/total`.
- `308 Resume Incomplete` plus a `Range` header tells you where to continue. Query status with an empty `PUT` and `Content-Range: bytes */total`.
- Completion returns `200`/`201`.

**CORS**
- Google's archived browser sample does exactly this with XHR: it sets `X-Upload-Content-Length/Type`, reads `getResponseHeader('Location')`, sends chunked `Content-Range` PUTs, and handles 308 with `extractRange_`.
  - https://raw.githubusercontent.com/googleworkspace/drive-utils/main/upload/upload.js
- From an extension page, requests to hosts in `host_permissions` bypass CORS entirely. Content scripts are subject to the page origin's CORS. https://developer.chrome.com/docs/extensions/develop/concepts/network-requests

```js
async function uploadMp4(token, blob, name, parentId) {
  const init = await fetch('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,webViewLink', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json; charset=UTF-8',
      'X-Upload-Content-Type': 'video/mp4',
      'X-Upload-Content-Length': String(blob.size),
    },
    body: JSON.stringify({ name, mimeType: 'video/mp4', ...(parentId && { parents: [parentId] }) }),
  });
  if (!init.ok) throw new Error(`init ${init.status}`);
  const session = init.headers.get('Location');
  const CHUNK = 32 * 256 * 1024; // 8 MiB (multiple of 256 KiB)
  let offset = 0;
  while (true) {
    const end = Math.min(offset + CHUNK, blob.size);
    const res = await fetch(session, {
      method: 'PUT',
      headers: { 'Content-Range': `bytes ${offset}-${end - 1}/${blob.size}` },
      body: blob.slice(offset, end),
    });
    if (res.status === 200 || res.status === 201) return res.json(); // { id, name, webViewLink }
    if (res.status === 308) { const r = res.headers.get('Range'); offset = r ? +r.split('-')[1] + 1 : 0; continue; }
    // 5xx / network: backoff, then PUT with 'Content-Range: bytes */<size>' to learn the committed offset
    throw new Error(`chunk ${res.status}`);
  }
}
```

Notes:
- The Drive 308 carries no `Location`, so `fetch` should surface it rather than follow it (inference). If in doubt, use XHR as Google's sample does.
- With `drive.file`, folders and files the app creates stay accessible to the app.
- Drive needs processing time before the video plays, and its playback maxes out at 1920×1080.

---

## D. Better Canvas: structure to mirror

Repository: https://github.com/UseBetterCanvas/bettercanvas (240 commits). Manifest: https://raw.githubusercontent.com/UseBetterCanvas/bettercanvas/main/manifest.json

1. **Manifest V3 and minimal permissions.**
   - `"background": {"service_worker": "js/background.js"}`, `"options_page": "html/options.html"`, `"action": {"default_popup": "html/popup.html"}`.
   - `"permissions": ["storage"]` only, with **no `host_permissions`**. Version 5.12.6.
2. **One content script for every HTTPS site, gated at runtime.**
   - `"content_scripts": [{"matches": ["https://*/*"], "js": ["js/content.js"], "css": ["css/content.css"], "run_at": "document_start"}]`.
   - `isDomainCanvasPage()` reads `custom_domain` (a list of hostnames) from `chrome.storage.sync`. It calls `startExtension()` only when `window.location.origin` matches, and runs `setupCustomURL()` when the list is empty.
   - The reason: Canvas lives on `*.instructure.com` **and** on school vanity domains.
   - **For Classroom, match only `https://classroom.google.com/*`**, because the host is fixed.
3. **Calls the Canvas REST API as the logged-in user, with no OAuth.**
   - The content script does same-origin `fetch(`${domain}/api/v1/...`)`, e.g. `/api/v1/courses?per_page=100` and the current user's colour-settings endpoint. The session cookie authenticates.
   - Writes (`PUT`/`POST`) add `'X-CSRF-Token': CSRFtoken()`. The token comes from Canvas's `_csrf_token` cookie (3rd-party confirmation: https://github.com/techconsigliere/canvas-admin-bookmarklets).
   - **This does not carry over to Classroom.** Its API is on `classroom.googleapis.com` and needs OAuth bearer tokens (section C).
4. **Settings UX.**
   - The popup toggles options with `chrome.storage.sync.set({[option]: status})`. It validates custom domains with `new URL(val).hostname`.
   - The options page holds the fuller settings.
   - The background worker seeds defaults for about 30+ sync keys plus local keys on `onInstalled`, opens the options page on first install, and sets an uninstall URL.
5. **Live re-apply.** The content script subscribes to `chrome.storage.onChanged` (for example `applyOptionsChanges`) and regenerates dark-mode CSS dynamically.
6. **Popup ↔ tab messaging.** `chrome.runtime.onMessage` in the content script handles named actions (`getCards`, `setcolors`, `getcolors`, `inspect`, `fixdm`), which the popup sends to the active Canvas tab.
7. **i18n and backend.** `_locales/` (en, es) via Crowdin. An optional own-backend (`bettercanvas.diditupe.dev`) handles theme sharing.
8. **License:** **AGPL-3.0 with extra restrictions** (no commercial use, no public redistribution without permission, no competing services). **Mirror the architecture only; write all code fresh.**

If a Canvas target is ever added, the Better Canvas pattern works for teachers too:
- Check teacher status with `GET /api/v1/courses?enrollment_type=teacher`.
- Upload with Canvas's three-step flow: `POST /api/v1/courses/:id/files` → `upload_url` + `upload_params`, then a multipart POST with the file last, then confirm. https://canvas.instructure.com/doc/api/file.file_uploads.html
- The docs describe Bearer tokens; same-origin session-cookie use (with the CSRF token) is how Canvas's own UI calls the API (3rd-party).

---

## E. Verify by experiment before committing (checklist)

1. **AAC probe** on real target devices (a school Chromebook plus Windows and Mac laptops): `AudioEncoder.isConfigSupported({codec:'mp4a.40.2', sampleRate:48000, numberOfChannels:1, bitrate:128000})`. Expected: false on ChromeOS and Linux.
2. **Patch `@mediabunny/aac-encoder`** to a static worker file, or run it inline inside our render worker. Confirm it runs under the MV3 CSP with `'wasm-unsafe-eval'` and without `blob:`.
3. **TTS real-time factor** with HeadTTS or kokoro-js on:
   - a low-end Chromebook (WASM q8, threads on/off under COOP/COEP);
   - an Intel-iGPU Windows laptop (WebGPU fp32 vs fp16).
4. **Encode fps** at 1080p30 vs 720p24 on the same devices. Check readback cost with the software encoder.
5. `self.crossOriginIsolated` in `studio.html`, its workers, and any offscreen document.
6. **getAuthToken account selection** in a multi-account Chrome profile. Check which account the token belongs to, and the `launchWebAuthFlow` fallback UX.
7. **Classroom URL code**: `atob` vs `alternateLink` on a **dedicated test teacher account**.
8. **200 MB resumable upload** from the extension page: 308 handling via `fetch`, and resume after a network drop.
9. **Start OAuth verification early:** privacy policy on a verified domain, demo video, and scope justifications. Keep the scope set minimal.
10. **One pilot district's IT walkthrough** of C3 (API controls, 18+ staff OU, Classroom API data access, extension allowlist).

---

## F. Source index

**WebCodecs, codecs and muxing**
- https://www.w3.org/TR/webcodecs/
- https://developer.mozilla.org/en-US/docs/Web/API/VideoEncoder
- https://developer.mozilla.org/en-US/docs/Web/API/WebCodecs_API/Codec_selection
- https://developer.mozilla.org/en-US/docs/Web/API/VideoFrame/VideoFrame
- https://chromium.googlesource.com/chromium/src/+/main/media/base/media_switches.cc
- https://chromium.googlesource.com/chromium/src/+/main/media/mojo/clients/mojo_audio_encoder.cc
- https://chromium.googlesource.com/chromium/src/+/main/media/mojo/services/gpu_mojo_media_client.cc
- https://chromium.googlesource.com/chromium/src/+/main/media/mojo/services/gpu_mojo_media_client_cros.cc
- https://chromium.googlesource.com/chromium/src/+/main/third_party/blink/renderer/modules/webcodecs/audio_encoder.cc
- https://learn.microsoft.com/en-us/windows/win32/medfound/aac-encoder
- https://webcodecsfundamentals.org/codecs/mp4a.40.2.html
- https://webcodecsfundamentals.org/codecs/avc1.42001f.html
- https://webcodecsfundamentals.org/codecs/avc1.640028.html
- https://webcodecsfundamentals.org/basics/encoder/
- https://bloggeek.me/webrtcglossary/h-264/
- https://github.com/Vanilagy/mp4-muxer
- https://github.com/Vanilagy/mediabunny
- https://mediabunny.dev/
- https://mediabunny.dev/guide/writing-media-files
- https://mediabunny.dev/guide/media-sources
- https://mediabunny.dev/guide/output-formats
- https://mediabunny.dev/guide/packets-and-samples
- https://mediabunny.dev/guide/supported-formats-and-codecs
- https://mediabunny.dev/api/VideoEncodingConfig
- https://mediabunny.dev/api/AudioEncodingConfig
- https://mediabunny.dev/guide/extensions/aac-encoder
- https://raw.githubusercontent.com/Vanilagy/mediabunny/main/scripts/esbuild/inlined-workers.ts
- https://support.google.com/drive/answer/2423694

**Canvas and drawing**
- https://developer.mozilla.org/en-US/docs/Web/API/OffscreenCanvas
- https://web.dev/articles/offscreen-canvas
- https://developer.mozilla.org/en-US/docs/Web/API/Path2D/Path2D
- https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/canvas
- https://developer.chrome.com/blog/taking-advantage-of-gpu-acceleration-in-the-2d-canvas
- https://www.schiener.io/2024-08-02/canvas-willreadfrequently
- https://github.com/rveciana/svg-path-properties

**MV3 platform**
- https://developer.chrome.com/docs/extensions/reference/api/offscreen
- https://developer.chrome.com/docs/extensions/reference/manifest/content-security-policy
- https://developer.chrome.com/docs/extensions/develop/migrate/remote-hosted-code
- https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements
- https://developer.chrome.com/docs/webstore/publish
- https://developer.chrome.com/docs/extensions/develop/concepts/storage-and-cookies
- https://developer.chrome.com/docs/extensions/reference/permissions-list
- https://developer.chrome.com/docs/extensions/develop/concepts/cross-origin-isolation
- https://developer.chrome.com/docs/extensions/reference/manifest/cross-origin-embedder-policy
- https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
- https://developer.chrome.com/docs/extensions/develop/concepts/network-requests
- https://developer.chrome.com/blog/new-in-webgpu-124
- https://groups.google.com/a/chromium.org/g/chromium-extensions/c/nQp-Dtc7q6k
- https://groups.google.com/a/chromium.org/g/chromium-extensions/c/UW8EFSssFcw
- https://huggingface.co/blog/transformersjs-chrome-extension
- https://github.com/huggingface/transformers.js/issues/839
- https://github.com/huggingface/transformers.js/issues/1248
- https://huggingface.co/docs/transformers.js/api/env
- https://data.jsdelivr.com/v1/packages/npm/@huggingface/transformers@3.7.6?structure=flat

**TTS**
- https://github.com/hexgrad/kokoro/tree/main/kokoro.js
- https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro.js/src/kokoro.js
- https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro.js/src/voices.js
- https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX
- https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/tree/main/onnx
- https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX-timestamped
- https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX-timestamped/discussions/2
- https://github.com/xenova/phonemizer.js
- https://github.com/xenova/phonemizer.js/issues/6
- https://github.com/hexgrad/kokoro/issues/247
- https://github.com/met4citizen/HeadTTS
- https://ryanwelch.co.uk/blog/kokoro-word-timestamps/
- https://quick-tts.com/blog/kokoro-webgpu-benchmarks.html
- https://github.com/WestSmith/Aloud/pull/15
- https://github.com/KittenML/KittenTTS
- https://github.com/ayutaz/piper-plus/blob/dev/README_EN.md

**Identity and OAuth**
- https://developer.chrome.com/docs/extensions/reference/api/identity
- https://developer.chrome.com/docs/extensions/how-to/integrate/oauth
- https://developer.chrome.com/docs/extensions/reference/manifest/key
- https://support.google.com/cloud/answer/15549257
- https://learn.microsoft.com/en-us/microsoft-edge/extensions/developer-guide/api-support
- https://developers.google.com/identity/protocols/oauth2/javascript-implicit-flow
- https://groups.google.com/a/chromium.org/g/chromium-extensions/c/4OX3cv_wepY

**Classroom and Drive**
- https://developers.google.com/workspace/classroom/guides/auth
- https://developers.google.com/workspace/classroom/reference/rest/v1/userProfiles
- https://developers.google.com/workspace/classroom/reference/rest/v1/userProfiles/get
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses/list
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.teachers/get
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWorkMaterials
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWorkMaterials/create
- https://developers.google.com/workspace/classroom/reference/rest/v1/Material
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.announcements
- https://developers.google.com/workspace/classroom/reference/rest/v1/courses.announcements/create
- https://developers.google.com/workspace/classroom/reference/Request.Errors
- https://developers.google.com/workspace/classroom/guides/key-concepts/user-types
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://developers.google.com/workspace/drive/api/guides/manage-uploads
- https://raw.githubusercontent.com/googleworkspace/drive-utils/main/upload/upload.js
- https://github.com/GAM-team/GAM/wiki/Managing-Google-Classroom/ef806dcf29501eb1e18a781493d5c5c0c66ecf3a

**Verification and admin**
- https://support.google.com/cloud/answer/13463073
- https://support.google.com/cloud/answer/13464325
- https://support.google.com/cloud/answer/13464323
- https://support.google.com/cloud/answer/15549945
- https://support.google.com/cloud/answer/7454865
- https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- https://discuss.google.dev/t/oauth-verification-stuck-6-weeks-sensitive-google-classroom-scopes-no-trust-safety-email-project-eduvetra/378317
- https://support.google.com/edu/classroom/answer/6250906
- https://support.google.com/edu/classroom/answer/6253304
- https://support.google.com/edu/classroom/answer/6071551
- https://support.google.com/edu/classroom/answer/11081157
- https://knowledge.workspace.google.com/admin/apps/control-which-apps-access-google-workspace-data
- https://knowledge.workspace.google.com/admin/getting-started/editions/manage-access-to-unconfigured-third-party-apps-for-users-designated-as-under-18
- https://knowledge.workspace.google.com/admin/getting-started/editions/control-access-to-google-services-by-age
- https://workspaceupdates.googleblog.com/2023/08/third-party-app-access-enhancements-for-google-workspace-edu.html
- https://support.google.com/chrome/a/answer/6177431
- https://support.google.com/chrome/a/answer/10405494
- https://developers.google.com/workspace/classroom/add-ons/requirements

**Better Canvas and Canvas**
- https://github.com/UseBetterCanvas/bettercanvas
- https://raw.githubusercontent.com/UseBetterCanvas/bettercanvas/main/manifest.json
- https://raw.githubusercontent.com/UseBetterCanvas/bettercanvas/main/js/content.js
- https://raw.githubusercontent.com/UseBetterCanvas/bettercanvas/main/js/popup.js
- https://raw.githubusercontent.com/UseBetterCanvas/bettercanvas/main/js/background.js
- https://canvas.instructure.com/doc/api/file.file_uploads.html

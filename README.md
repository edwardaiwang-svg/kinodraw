# KinoDraw

**Turn any script into a hand-drawn whiteboard explainer video, on your own computer.** Free and open source,
no watermark (just a 2-second end card you can turn off), works offline on Windows, macOS and Linux.

*KinoDraw was called Doodle Studio before version 0.2.0.*

Paste a script and KinoDraw produces a finished MP4. A drawing hand sketches cartoon doodles, handwritten notes and small charts while a natural voice narrates. Captions, chapters, music, a thumbnail and a transcript come with it. English and Chinese (中文) are both first-class.

![KinoDraw making a video](docs/media/hero.gif)

- **Works offline and for free.** Voice, drawing and video are all made locally. No account and no API key needed. (You can also point it at your own voice server.)
- **1,760+ doodles.** It ships 279 original drawings in one bold outlined style (plus a recurring narrator character) and 1,483 Microsoft Fluent Emoji redrawn to match.
- **It explains, not just decorates.** Numbers become big stats and 100-square grids, dates become timelines, "X is called Y" becomes a sticky-note definition, and quotes become quote cards. Every section ends with a takeaway note that pins onto the agenda.
- **Everything is editable.** Swap any doodle, fix a label, retitle a section, preview a frame, then make the video.
- **Optional AI director.** It can plan the visuals with GPT-6 Luna or Claude: through KinoDraw Cloud (free plan, no key needed), or with your own OpenAI, Anthropic or OpenAI-compatible key.

## Install

**App:** download *KinoDraw* for Windows, macOS (Apple silicon, M1 or newer) or Linux from [Releases](../../releases) and open it. The first video downloads the doodle search model (about 70 MB) and, when using the built-in voice, the voice model (about 190 MB per language), once, checksum-verified, showing megabytes and percent as it goes.

The app isn't notarized by Apple or signed for Windows yet, so the first launch needs one approval:
- **macOS:** unzip, drag *KinoDraw* to Applications and open it. When macOS blocks it, go to System Settings → Privacy & Security and click **Open Anyway**. If macOS says the app is damaged, run `xattr -dr com.apple.quarantine "/Applications/KinoDraw.app"` once. Step by step, with pictures: [first time opening on a Mac](https://edwardaiwang-svg.github.io/kinodraw/#first-open).
- **Windows:** unzip and run *KinoDraw.exe* in the *KinoDraw* folder. If SmartScreen appears, click **More info** → **Run anyway**.
- **Linux:** unpack and run *KinoDraw/KinoDraw*.

**Coming from Doodle Studio?** Close Doodle Studio, then open KinoDraw: it moves your Doodle Studio projects, settings
and downloaded voice over the first time it opens (if Doodle Studio was still open, KinoDraw says so and finishes the move
the next time it opens). Sign in to KinoDraw Cloud and re-enter any saved API keys once, then delete *Doodle Studio.app*
(or the *Doodle Studio* folder on Windows and Linux).

**Command line** (Python 3.10–3.12):

```bash
uv tool install git+https://github.com/edwardaiwang-svg/kinodraw         # or: pipx install git+https://…
kinodraw studio                                                         # opens the app window
kinodraw make my-script.md -o "My Video"                                # or straight to an MP4
```

## Write a script

Plain text, Markdown or a .docx file works.

- `#` gives the title; each `##` heading becomes a section with its own agenda card. With no headings, the text is split for you.
- Write the way you would speak it. Numbers are read out properly ("$3.8bn", "1450s" and "30%" all work, and so do "2026年" and "百分之三十").
- A final "Conclusion" or "总结" section becomes the ending.

## Directors: who plans the visuals

| Director | Cost | Notes |
|---|---|---|
| **Offline** (always available) | free | Matches the words of each sentence to the doodle library on your computer. The visual plan stays on your machine. |
| **KinoDraw Cloud** | free: 5 videos a month | GPT-6 Luna plans each section. No key needed; sign in with an email code. Paid plans with more videos and Claude Opus 5.5 come later. |
| **Your OpenAI key** (Advanced) | about $0.02 per 15-min video | Default `gpt-6-luna`. In the app, turn on Settings → Advanced directors to see these last four options. |
| **Your Anthropic key** | about $1 per 15-min video | `claude-opus-5`, `claude-opus-5-5`, or the cheaper `claude-haiku-4-5`. |
| **OpenAI-compatible** | varies | OpenRouter, DeepInfra, Groq, or a local Ollama or LM Studio. |
| **Your own command** | varies | Any program you choose: it gets each request as JSON and prints the plan as JSON. |

AI answers are always checked by code before use:
- doodles must come from the library;
- drawing triggers must be words that are actually spoken;
- numbers, dates and quotes must appear in your script.

Any beat that fails keeps the offline plan. Keys are stored in your system keychain.

## Your own voice server (optional)

The built-in voice is the default. To use an OpenAI-compatible voice server you already run, open Studio → Settings → Voice server, enter its address and model, optionally its voice and API key, and press **Test**. Turn on **Read scripts with my own OpenAI-compatible voice server** and press **Save**. When it is on, New video and each project's Narrator tab name the server voice, you can choose a server voice per video, and **Hear it** plays a sample from your server. Your own recordings stay local and take priority over the server.

For the command line:

```bash
export TTS_BACKEND=openai_compatible
export TTS_API_BASE=http://localhost:8080/v1
export TTS_MODEL=qwen-tts
# Optional: export TTS_VOICE=your-voice
# Optional: export TTS_API_KEY=your-key
kinodraw make my-script.md -o "My Video"
```

You can also pass `--voice-server URL --server-model NAME --server-voice NAME` to `make`, `new` or `voice`, and store its key with `kinodraw key set voice-server --url URL`. A key is kept for the address it was saved for and sent only there; only your own settings choose the server, never a project file someone sends you. To return an existing project to the built-in voice, run `kinodraw voice "My Video" --voice-server none` and unset the `TTS_*` variables for future projects.

## How it works

```
script ─▶ ingest ─▶ beats + spoken text ─▶ director ─▶ storyboard.json ─▶ Kokoro voice ─▶ timeline ─▶ renderer ─▶ mix + package
          (md/docx)  ("$3.8bn" → "three point    (rules or LLM)  (editable)     (per-phoneme    (captions,   (hand-drawn     (music, chapters,
                     eight billion dollars")                                    timing)          music)       frames)         QA, thumbnail)
```

- **Voice:** [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) through [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), on the CPU. Its per-phoneme timing lines drawings and captions up with the words (typically within 0.2 s).
- **Drawing:** SVG outlines are traced in drawing order by a photographed hand, then the colour pops in. Text is written stroke by stroke from the font's glyph skeletons.
- **Quality checks:** every video is fully decoded and its frame count checked. Its audio is compared with the mix, and its chapters are verified.

See [docs/architecture.md](docs/architecture.md) and [the storyboard format](docs/storyboard.md).

## Limits

- The offline director draws a word only in the sense its section is about, and leaves the word undrawn when it can't tell (a wine-making "press" is never drawn as a newspaper). It can't read between the lines the way an AI director can; swap any doodle in the editor, or use an AI director.
- Rendering takes about as long as the video (a 15-minute video takes about 10–15 minutes on a recent laptop). `--workers` uses more cores.
- Only English and Chinese are supported so far. Full manual testing was done on macOS; Windows and Linux are covered by CI.

## Privacy

Offline mode sends nothing anywhere unless you choose your own voice server. With KinoDraw Cloud or your own key, only the text of one section at a time (plus doodle names) goes to the AI provider. KinoDraw Cloud does not store script text. With Settings > Voice server on (or TTS_BACKEND=openai_compatible), the text of each part of the script goes to the server you entered, and nothing else does. The request includes the model and voice names and an API key if entered; Test and Hear it send one sample sentence, and your own recordings stay on this computer. See the [privacy policy](docs/privacy.html).

## Licences

- **Code:** MIT ([LICENSE](LICENSE)).
- **Original doodles, narrator and drawing hand:** CC BY 4.0 ([LICENSES/ASSETS.md](LICENSES/ASSETS.md)).
- **Everything else** (fonts, emoji, music, voice model, libraries) keeps its own licence; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- **Your videos are yours.** No attribution is required, though "Made with KinoDraw" is appreciated. Videos end with a
  2-second "Made with KinoDraw" credit that you can switch off (untick "Made with KinoDraw" end card next to Make video, or `kinodraw make --no-credit`).

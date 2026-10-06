# Built-in voices

Studio offers 13 English, 8 Mandarin and 3 Spanish voices. New video and Narrator
use the same catalog in `kinodraw/voice.py`; the CLI accepts their IDs with
`--voice`. Heart (`af_heart`), Mei (`zf_001`) and Dora (`ef_dora`) remain the
language defaults. Once a language's models are installed, **Hear it** runs
locally and caches its sample.

The additions below use the existing model downloads. Their IDs were checked in
the corresponding ONNX voice banks. English labels follow the upstream
[voice list](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md), which
also lists the third Spanish voice, Santa. The
[Mandarin model card](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) describes
its 100 Chinese speakers; those speakers have numbered IDs, so the new Mandarin
labels keep their numbers. Labels describe the bank's voice category; **Hear it**
lets you choose the sound for your script.

| Language | Label | ID | Model | Voice bank |
| --- | --- | --- | --- | --- |
| English | Aoede, US woman | `af_aoede` | `kokoro-v1.0.fp16.onnx` | `voices-v1.0.bin` |
| English | Kore, US woman | `af_kore` | `kokoro-v1.0.fp16.onnx` | `voices-v1.0.bin` |
| English | Sarah, US woman | `af_sarah` | `kokoro-v1.0.fp16.onnx` | `voices-v1.0.bin` |
| English | Puck, US man | `am_puck` | `kokoro-v1.0.fp16.onnx` | `voices-v1.0.bin` |
| English | Isabella, UK woman | `bf_isabella` | `kokoro-v1.0.fp16.onnx` | `voices-v1.0.bin` |
| English | Fable, UK man | `bm_fable` | `kokoro-v1.0.fp16.onnx` | `voices-v1.0.bin` |
| Mandarin | Mandarin woman 003 | `zf_003` | `kokoro-v1.1-zh.fp16.onnx` | `voices-v1.1-zh.bin` |
| Mandarin | Mandarin woman 004 | `zf_004` | `kokoro-v1.1-zh.fp16.onnx` | `voices-v1.1-zh.bin` |
| Mandarin | Mandarin man 009 | `zm_009` | `kokoro-v1.1-zh.fp16.onnx` | `voices-v1.1-zh.bin` |
| Mandarin | Mandarin man 011 | `zm_011` | `kokoro-v1.1-zh.fp16.onnx` | `voices-v1.1-zh.bin` |
| Spanish | Santa, Spanish man | `em_santa` | `kokoro-v1.0.fp16.onnx` | `voices-v1.0.bin` |

This is a curated selection from those banks. Short sample synthesis verifies
that each addition makes sound; it does not rate pronunciation or performance
across every possible script.

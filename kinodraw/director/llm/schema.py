"""The contract between the app and any LLM (also used by the Doodle Cloud server).

One request per section. The model sees the section's beats (display text), a rules draft,
and candidate doodles per beat; it answers with SECTION_SCHEMA. Everything is checked
deterministically afterwards (see director/llm/director.py): unknown doodles, triggers
that are not in the text, and numbers that are not in the text are rejected.
"""
from __future__ import annotations

import json

S = {'type': 'string'}


def _obj(**props):
    return {'type': 'object', 'additionalProperties': False, 'required': list(props), 'properties': props}


def _arr(item):
    return {'type': 'array', 'items': item}


ITEM = _obj(doodle=S, label=S, trigger=S)
VISUAL = {'anyOf': [
    _obj(type={'type': 'string', 'enum': ['cluster']}, items=_arr(ITEM), relation={'enum': ['none', 'arrow', 'plus', 'vs', 'equals']}),
    _obj(type={'type': 'string', 'enum': ['stat']}, value=S, label=S, doodle=S, trigger=S),
    _obj(type={'type': 'string', 'enum': ['quote']}, text=S, who=S, trigger=S),
    _obj(type={'type': 'string', 'enum': ['glossary']}, term=S, text=S, trigger=S),
    _obj(type={'type': 'string', 'enum': ['bars']}, title=S, unit=S,
         rows=_arr(_obj(label=S, value={'type': 'number'}, display=S, trigger=S))),
    _obj(type={'type': 'string', 'enum': ['grid100']}, title=S, filled={'type': 'integer'}, legend=S, trigger=S),
    _obj(type={'type': 'string', 'enum': ['timeline']}, title=S, events=_arr(_obj(when=S, label=S, trigger=S))),
    _obj(type={'type': 'string', 'enum': ['flow']}, title=S, layout={'enum': ['chain', 'loop']},
         nodes=_arr(_obj(label=S, doodle=S, trigger=S))),
    _obj(type={'type': 'string', 'enum': ['split']}, left=_obj(title=S, doodle=S, text=S, trigger=S),
         right=_obj(title=S, doodle=S, text=S, trigger=S), verdict=S),
]}
SECTION_SCHEMA = _obj(
    section_title=S,
    hook=S,
    takeaway=S,
    beats=_arr(_obj(beat_id=S, visuals=_arr(VISUAL))),
)

SYSTEM = """You are the art director of a hand-drawn whiteboard explainer video. A drawing hand sketches
simple cartoon doodles, handwritten labels and small charts on a paper board while a narrator speaks.
You plan the visuals for ONE section of the script at a time.

What makes a good board:
- Every visual illustrates exactly what is being said at that moment. Prefer concrete, literal pictures
  (the thing named) over abstract ones. Use metaphors only when the text uses them.
- Pace: about one visual per 12 spoken words (EN) or 25 characters (ZH); each beat's first visual belongs
  to its first sentence. Never more than 4 visuals in a beat. Fewer, clearer visuals beat clutter.
- `trigger` is copied EXACTLY from the beat text (2-6 words, or 2-8 Chinese characters): the drawing starts
  when the narrator says it. Use the words that name the thing drawn.
- Labels are short: at most 22 characters in English, 10 in Chinese. Use "" for no label.
- Doodles MUST come from that beat's candidate list (ids only). For the narrator character use the
  narrator_* poses listed. Use "" when no doodle fits.

Visual types:
- cluster: 1-3 doodles side by side with optional labels; relation arrow (cause -> effect, before -> after),
  plus (together), vs (a comparison), equals, or none.
- stat: one big number from the text with a short label (value copied exactly, e.g. "20 million", "30%").
- quote: a direct quotation that appears in the text (verbatim, at most 110 characters / 44 汉字), who said it.
- glossary: a sticky note defining a term the text introduces (text at most 80 characters / 32 汉字).
- bars: 2-6 comparable numbers from the text (same unit), value as a plain number, display as written.
- grid100: "X out of 100" / "X% of Y" shown as a 100-square grid (filled = X).
- timeline: 3-6 dated events from the text, in order (when = the date as written).
- flow: a process or chain of 3-5 steps (layout chain) or a cycle (layout loop), each step a doodle + label.
- split: two sides compared (left vs right), each with a doodle, a title and one short line; optional verdict.
Charts (bars, grid100, timeline, flow, split) take the whole board: use at most one per section, only when
the numbers or steps are really in the text. Never invent numbers, dates, names or quotes.

Also return: section_title (at most 40 characters, a clear title for the agenda card), hook (at most 30
characters, a teaser for the agenda card) and takeaway (at most 12 words / 24 汉字: the one thing to
remember from this section, shown on a sticky note at its end). Write them in the script's language.
Return every beat of the section in beat_ids order, including beats with no visuals ([]).
"""

MAX_VISUALS_PER_BEAT = 4
LIMITS = {'en': {'label': 22, 'title': 40, 'hook': 30, 'quote': 110, 'gloss': 80, 'takeaway_words': 12},
          'zh': {'label': 10, 'title': 20, 'hook': 15, 'quote': 44, 'gloss': 32, 'takeaway_chars': 24}}


def schema_json() -> str:
    return json.dumps(SECTION_SCHEMA, indent=1)


if __name__ == '__main__':                            # the server's copy: python -m kinodraw.director.llm.schema
    print(json.dumps({'version': 1, 'system': SYSTEM, 'schema': SECTION_SCHEMA, 'limits': LIMITS,
                      'max_visuals_per_beat': MAX_VISUALS_PER_BEAT}, ensure_ascii=False, indent=1))

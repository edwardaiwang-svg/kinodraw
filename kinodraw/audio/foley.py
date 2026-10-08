"""Everyday sound effects from what is said and what the plan's characters do.

cues() reads the narration's word times (the timeline's captions) and puts a quiet effect on the word that names a
sound: weather (thunder, lightning, rain, wind), the household (a door, a knock, footsteps, a phone, a message,
typing, paper, a drawer, a clock), the shop (a till, a bell), the kitchen (sizzling, pouring, whisking), a crowd (cheering,
applause, a murmur), traffic (a car, a bus) and a person laughing. The plan's actions add footsteps when someone walks
or runs and a laugh when a person laughs (an animal's laugh is the renderer's). The word lists are broad and
general, never a script's nouns; ambiguous words are only matched in the phrases that make them sounds.
Each kind waits COOLDOWN seconds before it plays again, a caption gets at most PER_CAPTION effects, and an effect the
renderer already cued nearby is not doubled. The levels (synth_sfx.LEVEL_KIND) keep them 12-18 LU under the voice.
"""
from __future__ import annotations

import re

# (kind, pattern, seconds the effect lasts or None for the kind's own length). First match in a span wins.
_EN = [
    ('thunder', r"thunder(?:s|ed|ing|clap|claps|storms?|ous)?|rumble of thunder", None),
    ('lightning_crack', r"lightning|thunderbolts?|zap(?:s|ped|ping)?", None),
    ('rain', r"rain(?:s|ed|ing|y|drops?|fall|storms?)?|drizzl\w*|downpours?|pour(?:s|ed|ing)? down|"
             r"pouring rain|showers? of rain", 4.),
    ('wind', r"winds?|windy|breez(?:e|es|y)|gusts?|gusty|gale|blizzards?|storms?|stormy|howling wind", 4.),
    ('knock', r"knock(?:s|ed|ing)?", None),
    ('bell', r"door ?bells?|bells?|chimes?|chimed|ding(?:s|ed)?|timers?|ovens?", None),
    ('door', r"doors?|doorways?|slamm?(?:ed|ing|s)? (?:the )?door|front door", None),
    ('footsteps', r"walk(?:s|ed|ing)?(?! (?:you|us|them|me|him|her|through))|footsteps?|stepp(?:ed|ing) (?:in|into|out|off|on|onto|forward|back|inside|outside|over|up|down|through|away|aside|closer)|tiptoe(?:s|d|ing)?|marched|marching|stroll(?:s|ed|ing)?|"
                  r"stomp(?:s|ed|ing)?|(?:up|down)stairs|stairs|ran (?:to|down|up|across|out|into|home|after|off|over)|"
                  r"running (?:to|down|up|across|out|into|home|after)|hurried|paced", None),
    ('phone_buzz', r"(?:cell ?|smart ?|tele)?phones?|buzz(?:es|ed|ing)?|vibrat(?:e|es|ed|ing)|ringtones?", None),
    ('notification', r"notifications?|texted|(?:text|voice|new|a) messages?|messaged|e-?mails?|e-?mailed|inbox|"
                     r"voicemails?|replied", None),
    ('typing', r"typed|typing|typist|keyboards?|typewriters?|keystrokes?", None),
    ('paper', r"papers?|envelopes?|pages?|notebooks?|newspapers?|unfold(?:s|ed|ing)?|folded|flipp(?:ed|ing)|receipts?|"
              r"(?:a|the|his|her|my|your|their|our|this) letter|scrolls?", None),
    ('drawer', r"drawers?|cupboards?", None),
    ('cash_register', r"cash(?: registers?)?|tills?|paid|pay(?:s|ing)?(?! attention)|bought|buy(?:s|ing)?|"
                      r"purchas(?:e|es|ed|ing)|checkout|\$\s?\d[\d,.]*|dollars?|cents?|prices?|priced|"
                      r"on sale|sold|coins?", None),
    ('sizzle', r"sizzl(?:e|es|ed|ing)|fry(?:ing)?|fried|fries|frying pans?|griddles?|grill(?:s|ed|ing)|sear(?:s|ed|ing)|"
               r"bacon|skillets?", 2.5),
    ('pour', r"pour(?:s|ed|ing)?|splash(?:es|ed|ing)?|drip(?:s|ped|ping)?|fill(?:s|ed|ing)? (?:a|the|his|her|my|your) "
             r"(?:cup|glass|mug|bowl|kettle)", None),
    ('whisk', r"whisk(?:s|ed|ing)?|stir(?:s|red|ring)?|beat(?:s|ing)? the eggs|mix(?:es|ed|ing)? (?:the|in|it|them)|"
              r"dough|knead(?:s|ed|ing)?", None),
    ('applause', r"applau\w*|clapp?(?:ed|ing|s)?|ovations?|bravo", None),
    ('cheer', r"cheer(?:s|ed|ing)?|hooray|hurray|celebrat\w*|victory|triumph\w*|crowd (?:went wild|roared)", None),
    ('murmur', r"crowds?|crowded|audiences?|murmur\w*|chatter\w*|cafeterias?|restaurants?|caf[eé]s?|classrooms?|guests", 3.),
    ('bus', r"bus(?:es)?\b|school bus", None),
    ('car', r"cars?|drove|driving|traffic|taxis?|trucks?|highways?|honk(?:s|ed|ing)?", None),
    ('laugh', r"laugh(?:s|ed|ing|ter)?|giggl(?:e|es|ed|ing)|chuckl(?:e|es|ed|ing)|ha-ha|haha", None),
    ('clock_tick', r"clocks?|stopwatch(?:es)?|ticking|tick-tock|count(?:ing)? the seconds", None),
]
# In a video about a storm (any line names thunder, lightning or a storm) these words are lightning too.
_STORM = re.compile(r"thunder|lightning|storm", re.I)
_EN_STORM = [('lightning_crack', r"flash(?:es|ed)?|strikes?|struck|sparks?|bolts?|return stroke", None)]
_ZH = [
    ('thunder', r"雷声|打雷|雷雨|雷", None), ('lightning_crack', r"闪电", None), ('rain', r"下雨|雨", 4.),
    ('wind', r"大风|刮风|风", 4.), ('knock', r"敲门", None), ('bell', r"门铃|铃声|铃|烤箱", None),
    ('door', r"开门|关门|门", None), ('footsteps', r"脚步|走路|走进|走到|跑进|跑到|楼梯", None),
    ('phone_buzz', r"手机|电话", None), ('notification', r"消息|信息|短信|邮件|语音", None), ('typing', r"打字|键盘", None),
    ('paper', r"信封|纸|报纸|本子|信", None), ('drawer', r"抽屉|柜子", None),
    ('cash_register', r"收银|付钱|买|卖|元|块钱|价格", None), ('sizzle', r"煎|炸|炒", 2.5), ('pour', r"倒水|倒茶|倒", None),
    ('whisk', r"搅拌|和面|打蛋", None), ('applause', r"鼓掌|掌声", None), ('cheer', r"欢呼|庆祝", None),
    ('murmur', r"人群|观众|餐厅|教室|派对", 3.), ('bus', r"公交|巴士", None), ('car', r"汽车|开车|车", None),
    ('laugh', r"大笑|笑", None), ('clock_tick', r"钟|秒表|滴答", None),
]
_ZH_STORM = [('lightning_crack', r"闪|劈", None)]
def _compile(entries, lang):
    if lang == 'zh':
        return [(k, re.compile(p), d) for k, p, d in entries]
    return [(k, re.compile(rf"(?<![\w$])(?:{p})(?![\w])", re.I), d) for k, p, d in entries]


LEXICON = {'en': _compile(_EN, 'en'), 'zh': _compile(_ZH, 'zh')}
STORM_LEXICON = {'en': _compile(_EN_STORM, 'en'), 'zh': _compile(_ZH_STORM, 'zh')}
COOLDOWN = {'clock_tick': 8., 'thunder': 6., 'lightning_crack': 4., 'rain': 8., 'wind': 8., 'murmur': 8., 'sizzle': 5., 'cheer': 5.,
            'applause': 5., 'cash_register': 6., 'bus': 6., 'car': 5.}
DEFAULT_COOLDOWN = 3.
PER_CAPTION = 2
NEAR = 1.5            # seconds: a renderer cue of the same kind this close already plays it
# Plan action verbs (director/v3/schema.py VERBS) with a sound, by the actor's kind.
ACTIONS = {'walk': {'human': 'footsteps', 'quadruped': 'footsteps'},
           'run': {'human': 'footsteps', 'quadruped': 'footsteps'},
           'laugh': {'human': 'laugh'}}


def _word_times(caption, lang):
    """The start time of each character of the caption's text: its word's time (spaced languages) or its own (zh)."""
    text, words = caption['text'], caption.get('words') or []
    times, i = [caption['start']] * len(text), 0
    if lang == 'zh' and len(words) == sum(not c.isspace() for c in text):
        for j, ch in enumerate(text):
            if not ch.isspace():
                times[j], i = words[i], i + 1
        return times
    tokens = list(re.finditer(r'\S+', text))
    if len(tokens) != len(words):                     # an emoji or symbol is not a spoken word
        tokens = [t for t in tokens if re.search(r'\w', t.group())]
    if len(tokens) == len(words):
        for tok, at in zip(tokens, words):
            times[tok.start():tok.end()] = [at] * (tok.end() - tok.start())
    return times


def _kind_of_actor(cast, actor):
    for c in cast:
        if c.get('id') == actor:
            return c.get('kind')
    return None


def cues(tl: dict, plan: dict | None = None, existing=()) -> list[dict]:
    """Effect cues ({t, kind, id, dur?}) for the narration's sound words and the plan's sounding actions, sorted by
    time. ``existing`` are the renderer's cues: the same kind within NEAR seconds of one of them is skipped."""
    lang = 'zh' if str(tl.get('language', 'en')).startswith('zh') else 'en'
    lexicon = LEXICON[lang]
    if any(_STORM.search(c['text']) or re.search(r"雷|闪电|暴风", c['text']) for c in tl.get('captions', [])):
        lexicon = lexicon + STORM_LEXICON[lang]
    found = []                                                    # (t, kind, dur, source)
    for n, cap in enumerate(tl.get('captions', [])):
        times = _word_times(cap, lang)
        taken = []                                                # character spans already matched in this caption
        hits = []
        for kind, pattern, dur in lexicon:
            for m in pattern.finditer(cap['text']):
                if any(a < m.end() and m.start() < b for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                hits.append((times[m.start()], kind, dur, f'foley.word.{n}.{m.start()}'))
        found += sorted(hits)[:PER_CAPTION]
    plan = plan or {}
    cast = plan.get('cast') or []
    animals_only = bool(cast) and all(c.get('kind') != 'human' for c in cast)
    if animals_only:                                              # their laugh is the renderer's animal sound
        found = [f for f in found if f[1] != 'laugh']
    beats = tl.get('beats', {})
    caps = tl.get('captions', [])
    for s, scene in enumerate(plan.get('scenes', [])):
        for j, action in enumerate(scene.get('actions', [])):
            kind = ACTIONS.get(action.get('verb'), {}).get(_kind_of_actor(cast, action.get('actor')))
            beat = beats.get(action.get('at_beat'))
            if not kind or not beat:
                continue
            name = next((c.get('name', '') for c in cast if c.get('id') == action.get('actor')), '')
            at = beat['start']
            for cap in caps:                                      # on the actor's name in that beat, when it is said
                if beat['start'] - 1e-3 <= cap['start'] < beat['end'] and name:
                    m = re.search(rf'(?<!\w){re.escape(name.split()[0])}(?!\w)', cap['text'], re.I)
                    if m:
                        at = _word_times(cap, lang)[m.start()]
                        break
            found.append((at, kind, None, f'foley.action.{s}.{j}'))
    last, out = {}, []
    for at, kind, dur, cue_id in sorted(found):
        if at - last.get(kind, -1e9) < COOLDOWN.get(kind, DEFAULT_COOLDOWN):
            continue
        if any(c.get('kind') == kind and abs(float(c['t']) - at) < NEAR for c in existing):
            continue
        last[kind] = at
        cue = {'t': round(float(at), 3), 'kind': kind, 'id': cue_id}
        if dur:
            cue['dur'] = min(dur, max(.5, tl.get('duration', at + dur) - at))
        out.append(cue)
    return out

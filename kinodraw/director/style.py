""""Choose for me": pick a new video's style (look/story) from its script, decided by the video's director.

- KinoDraw Cloud asks GPT-6 Luna; an own-key director (OpenAI, Anthropic, compatible server, command) asks that
  model, through the same ``pick_style(payload, usage)`` call.
- The offline director picks on this computer from words in the script: nothing is sent anywhere.

Only styles that render the chosen format and language are offered, and the paper-collage promo only when the user
named a product. An answer outside the offer, or a failed call, falls back to the offline pick and says so. The pick
is made once, when the project is created, and saved in project.json (``style_pick``): re-planning the visuals never
picks again.

What an AI sees (one request per new video): the title, the section headings, the first EXCERPT characters of the
script, its language and format, and the offered styles.
"""
from __future__ import annotations

import re

from .. import styles

AUTO = 'auto'
EXCERPT = 600
MAX_HEADINGS = 20
REASON_MAX = 120
_LANG = {'en': 'English', 'zh': 'Chinese', 'es': 'Spanish'}
BY = {'rules': 'the offline word rules', 'cloud': 'KinoDraw Cloud AI', 'openai': 'your OpenAI key',
      'anthropic': 'your Anthropic key', 'compat': 'your OpenAI-compatible server', 'command': 'your command'}

# The offline pick: a look wins when the script uses at least MIN_HITS of its words (whole words; Chinese by
# substring). Otherwise the whiteboard, which fits any topic.
MIN_HITS = 2
WORDS = {
    'pixel_quest': ('a playful, game-style look suits a script about games', [
        'game', 'games', 'gaming', 'gamer', 'gamers', 'player', 'players', 'level', 'levels', 'quest', 'boss',
        'pixel', 'arcade', 'console', 'minecraft', 'roblox', 'speedrun', 'videojuego', 'videojuegos', 'juego',
        'jugador', '游戏', '玩家', '关卡']),
    'mosaic': ('an ancient-world look suits a script about ancient history', [
        'ancient', 'rome', 'roman', 'romans', 'greece', 'greek', 'greeks', 'egypt', 'egyptian', 'pharaoh',
        'pharaohs', 'empire', 'emperor', 'byzantine', 'mosaic', 'mosaics', 'temple', 'gladiator', 'gladiators',
        'pompeii', 'mesopotamia', 'babylon', 'antiguo', 'antigua', 'imperio', 'romano', 'romanos', '古代', '罗马',
        '帝国', '希腊', '埃及', '法老']),
    'chalkboard': ('a classroom chalkboard suits a math or science lesson', [
        'math', 'maths', 'mathematics', 'equation', 'equations', 'algebra', 'geometry', 'theorem', 'formula',
        'formulas', 'calculus', 'fraction', 'fractions', 'physics', 'chemistry', 'atom', 'atoms', 'molecule',
        'molecules', 'proof', 'matemáticas', 'ecuación', 'física', 'química', '数学', '方程', '公式', '几何', '物理',
        '化学']),
    'notebook': ('a notebook page suits study notes', [
        'vocabulary', 'grammar', 'notes', 'study', 'studying', 'homework', 'exam', 'exams', 'quiz', 'revision',
        'verb', 'verbs', 'essay', 'flashcards', 'vocabulario', 'gramática', 'examen', '词汇', '语法', '笔记', '复习',
        '考试', '作业']),
}


def label(value: str) -> str:
    entry = styles.get(value.split('/')[0])
    return entry['name']['en'] if entry else value


def options(aspect: str, lang: str, brand: dict | None) -> list[dict]:
    """The styles the menu offers (look/story, as in the Style menu) that render ``aspect`` in ``lang``; the promo
    only with a product name."""
    out = []
    for entry in styles.looks(ready=True):
        story = entry['stories'][0]
        if aspect not in entry['aspect'] or lang not in entry['languages']:
            continue
        if story == 'promo' and not (brand or {}).get('name'):
            continue
        out.append({'id': f"{entry['id']}/{story}", 'desc': _describe(entry)})
    return out


def _describe(entry: dict) -> str:
    fit = entry.get('fit', {})
    topics = [t for t in fit.get('topic', []) if t != 'any']
    parts = [entry['name']['en']]
    if entry.get('why'):
        parts.append(entry['why']['en'])
    parts.append(f"fits {', '.join(topics)}" if topics else 'fits any topic')
    if fit.get('audience'):
        parts.append(f"for {', '.join(fit['audience'])}")
    tones = [t for t in fit.get('tone', []) if t != 'any']
    if tones:
        parts.append(f"{' or '.join(tones)} tone")
    return _cut('; '.join(parts), 160)


def request(doc, lang: str, aspect: str, offered: list[dict]) -> dict:
    """What the AI sees: the title, headings, the script's first EXCERPT characters, language, format, options."""
    body = ' '.join(' '.join([*doc.preamble, *(p for s in doc.sections for p in s.paragraphs)]).split())
    return {'language': lang, 'title': _cut(doc.title, 120),
            'headings': [_cut(s.heading, 120) for s in doc.sections][:MAX_HEADINGS],
            'excerpt': _cut(body, EXCERPT), 'format': aspect, 'options': offered}


def _cut(text: str, n: int) -> str:
    """The longest start of ``text`` that is at most ``n`` UTF-16 units, as KinoDraw Cloud counts (an emoji is 2);
    it refuses longer text with a 413."""
    units = 0
    for i, ch in enumerate(text):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > n:
            return text[:i]
    return text


def offline(doc, ids: list[str], lang: str) -> dict:
    """The offline pick, from words in the whole script (on this computer only)."""
    if any(i.endswith('/promo') for i in ids):
        return {'style': next(i for i in ids if i.endswith('/promo')),
                'reason': 'You named a product, so a paper-collage promo'}
    text = ' '.join([doc.title, *doc.preamble, *(t for s in doc.sections for t in (s.heading, *s.paragraphs))]).lower()
    tokens = re.findall(r'[^\W\d_]+', text)
    best = None
    for value in ids:
        why, words = WORDS.get(value.split('/')[0], ('', []))
        found = {}
        for word in words:
            n = text.count(word) if re.match(r'[㐀-鿿]', word) else tokens.count(word)
            if n:
                found[word] = n
        hits = sum(found.values())
        if hits >= MIN_HITS and (best is None or hits > best[0]):
            best = (hits, value, why, sorted(found, key=lambda w: -found[w])[:3])
    if best:
        _, value, why, words = best
        return {'style': value, 'reason': _clip(f"{why[0].upper()}{why[1:]} ({', '.join(words)})")}
    plain = next((i for i in ids if i.startswith('whiteboard/')), ids[0])
    return {'style': plain, 'reason': 'No strong topic words, so the plain whiteboard, which fits any topic'}


def choose(doc, mode: str, lang: str, aspect: str, brand: dict | None = None, model: str | None = None,
           base_url: str | None = None) -> dict:
    """{style, label, reason, by, [note], [cost]}: ``by`` is the director that decided ('rules' when the offline
    word rules did, including a fallback, which ``note`` explains)."""
    offered = options(aspect, lang, brand)
    ids = [o['id'] for o in offered]
    local = offline(doc, ids, lang)
    if mode == 'rules':
        return _done(local, 'rules')
    from .llm.providers import ProviderError, Usage, make_provider
    usage = Usage()
    try:
        provider = make_provider(mode, model, base_url)
        if lang not in getattr(provider, 'languages', (lang,)):     # as the visuals director: nothing sent, nothing metered
            return _done(local, 'rules', f'{BY.get(mode, mode)} chooses for {" and ".join(_LANG[c] for c in provider.languages)} '
                                         f'videos only; {BY["rules"]} chose')
        answer = provider.pick_style(request(doc, lang, aspect, offered), usage)
    except (ProviderError, ValueError) as error:
        return _done(local, 'rules', f'{BY.get(mode, mode)} could not choose ({error}); {BY["rules"]} chose')
    if answer['style'] not in ids:
        return _done(local, 'rules', f'{BY.get(mode, mode)} chose "{_clip(answer["style"], 40)}", which this video '
                                     f'cannot use ({aspect}, {lang}{"" if (brand or {}).get("name") else ", no product named"}); '
                                     f'{BY["rules"]} chose')
    return _done({'style': answer['style'], 'reason': _clip(answer['reason']) or 'It suits the script'}, mode,
                 cost=usage.cost_usd if usage.calls else None)


def _done(pick: dict, by: str, note: str | None = None, cost: float | None = None) -> dict:
    out = {**pick, 'label': label(pick['style']), 'by': by}
    if note:
        out['note'] = note
    if cost:
        out['cost'] = cost
    return out


def _clip(text: str, n: int = REASON_MAX) -> str:
    text = ' '.join(re.sub('[\ud800-\udfff]', '', str(text or '')).split())   # a lone half of an emoji cannot be saved
    return text if len(text) <= n else text[:n - 1].rsplit(' ', 1)[0] + '…'

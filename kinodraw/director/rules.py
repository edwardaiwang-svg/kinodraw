"""Offline director: add visuals to every beat with simple, predictable rules (no network, no keys).

Per beat, in order: quotes, definitions (glossary note), one salient number (stat, or a
100-square grid for "X% of Y"), questions (thinking narrator), lists ("a book, a newspaper
or a website": every listed thing that has a picture, side by side), then concept doodles
from the matcher, linked by an arrow / vs / plus when the words between them say so.
About one visual per 9 words (up to 5 a beat): a picture for what is said, as it is said.
Sections with three or more dated events also get a timeline page. Every trigger is a
substring of the spoken text, so drawings start when the words are heard.

Nothing is written before it is said: a timeline page shows only its own section's dates,
each written when it is said, and holds the board from its first date to its last.

Meaning rules (a word is drawn only in the sense the script uses it):
- a picture belongs to the section's subject, unless the words name exactly what it shows;
  emoji pictures always have to belong;
- a word's senses compete: the picture that fits the sentence best, with the word itself
  hidden, wins ("a press adapted from wine making" is a printing press, not a newspaper);
- a word keeps the picture it got first; when that picture is still on the board (used in about
  the last four pictures of this section) the word is skipped, never given a second-best meaning;
  a listed thing is drawn even so;
- idioms ("a matter of weeks"), generic words ("inventions") and numbers get no picture, and neither
  does anything negated ("no engine"), a describing word ("oil-based ink" is ink, not oil), people named
  by what they do ("a team of printers" is never a printer) or the words of a term its definition note
  already shows; a picture is drawn once a beat;
- a picture found by meaning alone must be a curated drawing on the subject, and may not
  take words that name something else;
- banned pictures (religious imagery, scientist figures; assets/doodles/banned.json) are never
  drawn, and neither are banned words (church, Germany, scientists, astronomers).
Timeline labels say who or what the dated clause is about: a named person or group first,
else the clause's subject ("By 1500, printing presses were running" -> "Printing presses").
"""
from __future__ import annotations

import re
from collections import deque

import numpy as np

from .. import numbers, script
from ..engine.storyboard import normalize
from ..library import banned
from .match import EN_STOP, Hit, Matcher, _model, _normalize, catalog_vectors, singular

# A literal keyword hit counts in proportion to how well the doodle agrees with its sentence (ramp lo..hi).
# Hand-tagged bespoke keywords are reliable; emoji keywords are noisy, so they must agree more.
AGREE = {'en': {'bespoke': (.40, .60), 'fluent': (.48, .63)}, 'zh': {'bespoke': (.38, .56), 'fluent': (.45, .60)}}
MEANING_ONLY = {'en': .58, 'zh': .55}                 # a doodle with no literal hit must match this well,
MEANING_STRONG = {'en': .65, 'zh': .62}               # ... and below this, share a word with its sentence
NAMED_EASE = .06                                       # a drawing whose description names the words may agree less
LABEL_MAX = {'en': 22, 'zh': 10}
CAUSE = {'en': r'\b(so|because|therefore|thus|leads? to|led to|causes?|caused|turns? (?:\w+ )?into|becomes?|makes?)\b',
         'zh': r'因为|所以|导致|于是|变成|使得|从而|因此'}
CONTRAST = {'en': r'\b(versus|vs\.?|rather than|instead of|compared (?:to|with)|unlike)\b',
            'zh': r'而不是|相比|对比|比起|与其'}
LABEL_STOP = set('a an the of to in on at by for with from and or but is are was were be been it its this that '
                 'these those there their our your his her more most than about over under into'.split())
PREPOSITIONS = ('in', 'inside', 'into', 'of', 'on', 'onto', 'with', 'within', 'from', 'by', 'at', 'as', 'through')
PLUS = {'en': r'\b(and|with|plus)\b', 'zh': r'和|与|以及|加上'}
# Between two listed things: "a book, a newspaper or a website", "盐、糖和水".
LIST_GAP = {'en': re.compile(r"^\s*(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)(?:(?:a|an|the|some|many|their|his|her|its)\s+)?$", re.I),
            'zh': re.compile(r'^(?:、|，|和|与|或|以及)$')}
RECENT = 4                                             # pictures still on the board: a word waits for its own
# A picture must rank this high among all pictures for its section's subject, unless its words name it.
TOPIC_RANK = 100
MEANING_TOPIC_RANK = 60                                # pictures chosen by meaning alone: nearer the subject
SENSE_MARGIN = .03                                     # how much better another sense must fit to win the word
GENERIC = {'en': set('invention technology device gadget product item object equipment material stuff thing '
                     'innovation creation machine together'.split()),
           'zh': set('发明 技术 设备 装置 产品 物品 东西 工具 材料 创新 机器'.split())}
# Words in an emoji's name that only describe it: "light blue heart" is still a heart; "ferris wheel" is not
# any wheel and "slot machine" is not any machine, so those need their whole name said.
EMOJI_ADJ = set('red orange yellow green blue purple brown black white pink gray grey light dark small large big '
                'little tiny new old open closed full empty round square hot cold high low happy sad smiling '
                'grinning rolling fallen'.split())
EMOJI_ALSO = {'fl_snowflake': {'snow'}}                # emoji a shorter word may call up: snow is drawn as a snowflake
# Phenomena are not objects: "blue light" is never an emoji of a lamp or a traffic light.
PHENOMENA = {'en': set('light sound heat energy power force gravity electricity radiation magnetism friction '
                       'pressure temperature'.split()),
             'zh': set('光 光线 声音 热量 能量 力 引力 电 辐射 磁力 压力 温度'.split())}
IDIOMS = {'en': re.compile(r"\b(?:(?:in )?a matter of|no matter|as a matter of fact|in terms of|in light of|"
                           r"on the other hand|at hand|in fact|of course|at (?:least|most|first|last|all)|in time|on time|"
                           r"in charge|(?:take|takes|took|taken) place|(?:make|makes|made) sense|in turn|by and large|"
                           r"all in all|at the same time|in general|in particular|for (?:example|instance)|so far|"
                           r"as well|in other words|the bottom line|a (?:lot|number|couple) of)\b", re.I),
          'zh': re.compile(r'总而言之|事实上|换句话说|与此同时|一般来说|比如说|例如')}
# "a team of printers" are people, not printing machines: only a picture of people may stand for them.
PEOPLE_OF = {'en': re.compile(r"\b(?:team|group|crew|army|band|gang|staff|crowd|pair|couple|class|family|tribe|club|"
                             r"society|guild|union|community|generation)s? of\s+(?:[a-z-]+\s+)?$", re.I),
             'zh': re.compile(r'(?:一群|一队|一批|一组|团队)$')}
PEOPLE_CATEGORIES = {'people', 'narrator', 'People & Body'}
PEOPLE_DESC = re.compile(r'\b(?:people|person|persons|man|woman|men|women|teacher|teachers|students?|pupils?|children|'
                         r'child|kids?|boy|girl|family|crowd|team|workers?|narrator)\b', re.I)
NEGATION = {'en': re.compile(r"\b(?:no|not|without|never|nor|neither|non)\s+(?:[a-z-]+\s+)?$", re.I),
            'zh': re.compile(r'(?:没有|不是|无|不|非)$')}
NUMERAL = re.compile(r'[\d零一二三四五六七八九十百千万亿两.,:：%]+')
DETERMINERS = set('a an the this that these those his her its their our your my every each all some many several '
                  'most more no any'.split())
PREPS = set('in on at by for with from of to into onto across through over under about after before between during '
            'since until around near within without against among toward towards throughout upon via like'.split())
AUX = set('is are was were be been being has have had do does did will would can could shall should may might '
          'must'.split())
CONNECTIVES = set('when while as and where after before because since then which who whose once'.split())
PAST = set('spread ran began became made took came went grew fell rose led brought built found wrote gave got held '
           'kept left lost met paid put said sent sold stood taught thought told won'.split())
NARRATOR_CUES = [
    ('worried', {'en': r'\b(risk|danger|dangerous|problem|worry|worried|fear|threat|crisis|mistake|warning)\b',
                 'zh': r'风险|危险|问题|担心|害怕|危机|错误|警告'}),
    ('thumbs', {'en': r'\b(success|succeeded|great news|win|won|works|better|best)\b', 'zh': r'成功|好消息|更好|最好|有效'}),
    ('magnifier', {'en': r'\b(research|study|studies|evidence|investigat\w*|discover\w*)\b',
                   'zh': r'研究|证据|调查|发现'}),
    ('explain', {'en': r'\b(remember|key|important|lesson|means|in short)\b', 'zh': r'记住|关键|重要|意味着|总之'}),
]


def singular_words(phrase: str) -> set:
    return {w.rstrip('s') for w in re.findall(r'[a-z]+', phrase) if w not in EN_STOP} if phrase.isascii() else set()


class RulesDirector:
    def __init__(self, lang: str):
        self.lang = lang
        self.matcher = Matcher(lang)
        self.ids, self.vecs = self.matcher._catalog_vectors()
        self.pos = {i: k for k, i in enumerate(self.ids)}
        pic_ids, pic_vecs = catalog_vectors(lang, 'picture')   # what each drawing shows, keywords left out
        at = {i: k for k, i in enumerate(pic_ids)}
        self.pics = pic_vecs[[at[i] for i in self.ids]]
        self.topic: dict = {}                                   # chapter -> rank of every picture for its subject
        self.pictures: dict = {}                                # word -> the picture it got first
        self.banned_words = {singular(w) if lang == 'en' else w for w in banned()['words'].get(lang, ())}

    # ------------------------------------------------------------ entry point
    def direct(self, board: dict) -> dict:
        lang = self.lang
        chapters = {c['id']: c for c in normalize(board)['chapters']}
        recent: deque = deque(maxlen=RECENT)          # pictures still on the board
        heroes: dict = {}                             # chapter -> {doodle: best score}, for takeaway margins
        since_narrator = 99
        self.topic, self.pictures = self._topic_ranks(board), {}
        timelines, held = self._timelines(board)
        current = None
        for beat in board['beats']:
            beat['visuals'] = []
            kind, chapter = beat['kind'], chapters[beat['chapter']]
            if beat['chapter'] != current:            # a new chapter starts on a clean board
                current = beat['chapter']
                recent.clear()
            if kind in ('title', 'agenda', 'opener') or chapter['kind'] == 'intro':
                continue
            if kind == 'closing':
                beat['visuals'].append(self._cluster(beat, [self._item('narrator_wave')], 0))
                continue
            text = beat['display'][lang]
            norm = numbers.normalize(text, lang)
            if kind == 'take':
                best = sorted(heroes.get(beat['chapter'], {}).items(), key=lambda kv: -kv[1])[:2]
                for k, (did, _) in enumerate(best):
                    beat['visuals'].append({**self._cluster(beat, [self._item(did)], k), 'size': 'margin'})
                continue
            sentences = script.sentences(text, lang) or [text]
            spans, cursor = [], 0
            for sentence in sentences:
                start = text.find(sentence, cursor)
                spans.append((start, start + len(sentence)))
                cursor = start + len(sentence)

            def sentence_of(pos):
                return next((k for k, (a, b) in enumerate(spans) if a <= pos < b), len(spans) - 1)
            budget = self._budget(text)
            planned = []                              # (position in text, visual)
            taken = set()                             # sentences that already have a visual
            if beat['id'] in timelines:               # the page comes in with the first date said
                planned.append((held[beat['id']][0], timelines[beat['id']]))
                budget -= 1                           # a chart page still leaves room for the first sentence
            for detect in (self._quote, self._definition, self._number):
                if budget <= 0:
                    break
                found = detect(beat, text, norm, recent)
                if found:
                    v, pos = found
                    planned.append((pos, v))
                    taken.add(sentence_of(pos))
                    budget -= 1
            question = next((k for k, s_ in enumerate(sentences) if s_.endswith(('?', '？'))), None)
            if question is not None and question not in taken and budget > 0 and since_narrator >= 3:
                q = sentences[question]
                label = q if len(q) <= LABEL_MAX[lang] else None
                planned.append((spans[question][0], self._cluster(
                    beat, [self._item('narrator_think', label, self._spoken(norm, q))], len(planned))))
                taken.add(question)
                budget -= 1
                since_narrator = 0
            hits = self._concepts(text, recent, beat['chapter'])
            terms = [self._key(v['term'][lang]) for _, v in planned if v['type'] == 'glossary']
            hits = [h for h in hits if not (h.phrase and any(self._inside(self._key(h.phrase), t) for t in terms))]
            used_words: set = set()                   # (a defined term is shown by its note, not by its words)
            drawn: set = set()                        # pictures already in this beat: each is drawn once
            listed = [h for h in self._concepts(text, [], beat['chapter'], listing=True)
                      if not any(self._inside(self._key(h.phrase), t) for t in terms)]
            for group in self._lists(text, listed):   # every listed thing, side by side (even if drawn before)
                if budget <= 0:
                    break
                items = [self._item(h.id, self._label(h.phrase), self._spoken(norm, h.phrase, h.start)) for h in group]
                planned.append((group[0].start, self._cluster(beat, items, len(planned))))
                taken.add(sentence_of(group[0].start))
                spots = [(h.start, h.start + len(h.phrase)) for h in group]
                hits = [h for h in hits if not (h.phrase and any(a <= h.start < b or h.start <= a < h.start + len(h.phrase)
                                                                 for a, b in spots))]
                used_words |= singular_words(' '.join(h.phrase.lower() for h in group))
                recent.extend(h.id for h in group)
                drawn |= {h.id for h in group}
                budget -= 1
                for h in group:
                    self.pictures.setdefault(self._key(h.phrase), h.id)
                    section = heroes.setdefault(beat['chapter'], {})
                    section[h.id] = max(section.get(h.id, 0), h.score)
            for sweep in (0, 1):                      # one doodle per free sentence first, then extras
                for k, (a, b) in enumerate(spans):
                    if budget <= 0 or (sweep == 0 and k in taken):
                        continue
                    local = [h for h in hits if a <= h.start < b and h.id not in drawn
                             and not singular_words((h.phrase or '').lower()) & used_words]
                    if not local:
                        continue
                    group = self._pair(text, local, [pos for pos, _ in planned])
                    hits = [h for h in hits if h not in group]
                    drawn |= {h.id for h in group}
                    used_words |= singular_words(' '.join((g.phrase or '').lower() for g in group))
                    items = [self._item(h.id, self._label(h.phrase),
                                        self._spoken(norm, h.phrase or self._lead(text, h.start), h.start))
                             for h in group]
                    relation = self._relation(text, group) if len(group) == 2 else 'none'
                    planned.append((group[0].start, {**self._cluster(beat, items, len(planned)), 'relation': relation}))
                    taken.add(k)
                    recent.extend(h.id for h in group)
                    budget -= 1
                    for h in group:
                        if h.phrase:
                            self.pictures.setdefault(self._key(h.phrase), h.id)
                            section = heroes.setdefault(beat['chapter'], {})
                            section[h.id] = max(section.get(h.id, 0), h.score)
            if (not planned and since_narrator >= 2) or (since_narrator >= 5 and budget > 0):
                pose = self._narrator_pose(text) or ('explain' if not planned else None)
                if pose:
                    planned.append((len(text), self._cluster(beat, [self._item(f'narrator_{pose}')], len(planned))))
                    since_narrator = 0
            if beat['id'] in held:                    # a timeline holds the board between its first and last date
                lo, hi = held[beat['id']]
                planned = [(pos, v) for pos, v in planned      # (a picture without words comes as the beat starts)
                           if v['type'] == 'lanes' or not lo <= (pos if v.get('trigger') else 0) <= hi]
            visuals = [v for _, v in sorted(planned, key=lambda pv: pv[0])]
            since_narrator += 1
            beat['visuals'] = visuals
        return board

    # -------------------------------------------------------------- helpers
    def _budget(self, text: str) -> int:
        """About one visual per 9 English words or 20 Chinese characters (1-5 per beat)."""
        size = script.size(text, self.lang)
        return max(1, min(5, round(size / (9 if self.lang == 'en' else 20))))

    def _item(self, doodle, label=None, trigger=None):
        item = {'doodle': doodle}
        if label:
            item['label'] = {self.lang: label}
        if trigger:
            item['trigger'] = {self.lang: trigger}
        return item

    def _cluster(self, beat, items, k):
        v = {'id': f"{beat['id']}v{k}", 'type': 'cluster', 'items': items, 'relation': 'none'}
        first = next((it['trigger'] for it in items if it.get('trigger')), None)
        if first:
            v['trigger'] = first
        return v

    def _spoken(self, norm, phrase, start=-1):
        """The spoken words for a display phrase (a trigger), or None."""
        if not phrase:
            return None
        spoken = norm.find(phrase) if start < 0 else \
            norm.spoken[norm.to_spoken(start):norm.to_spoken(start + len(phrase))].strip() or None
        return spoken if spoken and spoken in norm.spoken else None

    def _lead(self, text, start):
        """The first few words from ``start``: the trigger for a doodle matched by meaning, not by a word."""
        if self.lang == 'zh':
            return re.match(r'[^，。！？；：]{1,4}', text[start:]).group(0) if text[start:] else ''
        return ' '.join(text[start:].split()[:3])

    def _label(self, phrase):
        if not phrase or len(phrase) > LABEL_MAX[self.lang]:
            return None
        return phrase[:1].upper() + phrase[1:] if self.lang == 'en' else phrase

    def _sentence_vectors(self, sentences):
        return _normalize(np.array(list(_model(self.lang).embed(sentences)), np.float32))

    def _concepts(self, text, recent, chapter, listing=False) -> list[Hit]:
        """Doodles for this text, best first: literal hits confirmed by meaning, then strong meaning-only
        hits, all under the meaning rules in the module docstring. ``listing``: one hit per phrase (a
        list names each thing on purpose, so any agreement will do), literal hits only."""
        ramps = AGREE[self.lang]
        sentences = script.sentences(text, self.lang) or [text]
        vecs = self._sentence_vectors(sentences)
        found: dict[str, Hit] = {}
        offset = 0
        for sentence, vec in zip(sentences, vecs):
            base = text.find(sentence, offset)
            offset = max(offset, base)
            plain = IDIOMS[self.lang].sub(lambda m: ' ' * len(m.group(0)), sentence)   # idioms are not pictures
            senses: dict = {}                         # word -> [(hit, score)]: the pictures competing for it
            named = []                                # spans of words that name some picture
            hits = self.matcher.lexical(plain, every_phrase=True)
            compounds = [(h.start, h.start + len(h.phrase)) for h in hits if len(self._key(h.phrase).split()) > 1]
            for hit in hits:
                named.append(hit.start)
                key = self._key(hit.phrase)
                a, b = hit.start, hit.start + len(hit.phrase)
                if any(x <= a and b <= y and (x, y) != (a, b) for x, y in compounds):
                    continue                          # "global warming" is one idea: not "global" on its own
                if NEGATION[self.lang].search(plain[max(0, a - 24):a]):
                    continue                          # "no engine": there is nothing to draw
                if plain[b:b + 1] == '-' and self.lang == 'en':
                    continue                          # "oil-based ink": a describing word, not a thing
                if PEOPLE_OF[self.lang].search(plain[max(0, a - 32):a]) and not self._shows_people(hit.id):
                    continue                          # "a team of printers" are people, not machines
                if key in GENERIC[self.lang] or NUMERAL.fullmatch(key) or self._banned(key) \
                        or not self._belongs(hit.id, hit.phrase, chapter):
                    continue
                if key in PHENOMENA[self.lang] and self.matcher.entries[hit.id]['set'] == 'fluent':
                    continue
                agree = float(self.vecs[self.pos[hit.id]] @ vec)
                lo, hi = ramps[self.matcher.entries[hit.id]['set']]
                if self.matcher.entries[hit.id]['set'] == 'bespoke' and self._names(hit.id, hit.phrase):
                    lo, hi = lo - NAMED_EASE, hi - NAMED_EASE     # "doctors": a doctor's stethoscope
                score = hit.score * max(0.0, min(1.0, (agree - lo) / (hi - lo)))
                if score > (0. if listing else .15):
                    senses.setdefault(key, []).append((hit, score))
            blocked = []                              # spans whose picture was used moments ago
            for key, cands in sorted(senses.items(), key=lambda kv: -max(s for _, s in kv[1])):
                chosen = self._sense(key, cands, sentence)
                if chosen is None:
                    continue
                hit, score = chosen
                a, b = hit.start, hit.start + len(hit.phrase)
                if any(x <= a < y or x < b <= y for x, y in blocked):
                    continue
                if hit.id in recent:                  # never a second-best meaning instead
                    blocked.append((a, b))
                    continue
                slot = f'@{base + hit.start}' if listing else hit.id
                if slot not in found or found[slot].score < score:
                    found[slot] = Hit(hit.id, score, hit.phrase, base + hit.start)
            if listing:
                continue
            lead = len(self._lead(sentence, 0))       # a meaning-only doodle is drawn on the first words
            words = {w[:5] for w in re.findall(r'[a-z]{4,}', sentence.lower()) if w not in EN_STOP}
            sims = self.vecs @ vec
            for i in np.argsort(-sims)[:3]:
                did = self.ids[i]
                if (sims[i] >= MEANING_ONLY[self.lang] and did not in recent and did not in found
                        and self.matcher.entries[did]['set'] == 'bespoke' and self.topic[chapter][i] <= MEANING_TOPIC_RANK
                        and not any(s < lead for s in named)
                        and (sims[i] >= MEANING_STRONG[self.lang] or self._shares(did, words))):
                    found[did] = Hit(did, float(sims[i]) - MEANING_ONLY[self.lang] + .1, None, base)
        ranked = sorted(found.values(), key=lambda h: -h.score)
        seen_phrases, out = set(), []
        for h in ranked:                              # one doodle per phrase
            key = (h.phrase or f'@{h.start}').lower()
            if key not in seen_phrases:
                seen_phrases.add(key)
                out.append(h)
        return out

    def _lists(self, text, hits) -> list[list[Hit]]:
        """Runs of listed things ("a book, a newspaper or a website"): 2-3 named pictures in a row with
        only commas, "and"/"or" and a determiner between them, at least one comma among them."""
        hits = sorted((h for h in hits if h.phrase), key=lambda h: h.start)
        runs, run, commas = [], [], 0
        for h in hits:
            if run:
                gap = text[run[-1].start + len(run[-1].phrase):h.start]
                if h.start >= run[-1].start + len(run[-1].phrase) and LIST_GAP[self.lang].match(gap):
                    run.append(h)
                    commas += (',' in gap or '、' in gap or '，' in gap)
                    continue
                if len(run) >= 2 and commas:
                    runs.append(run[:3])
            run, commas = [h], 0
        if len(run) >= 2 and commas:
            runs.append(run[:3])
        return runs

    def _shares(self, did, words):
        """Does the drawing's description share a word with the sentence (first five letters, English)?
        Chinese has no word gaps to compare, so only strong meaning-only matches are drawn there."""
        if self.lang != 'en':
            return False
        return bool(words & {w[:5] for w in re.findall(r'[a-z]{4,}', self.matcher.entries[did].get('desc', '').lower())})

    def _shows_people(self, did):
        entry = self.matcher.entries[did]
        return entry.get('category') in PEOPLE_CATEGORIES or bool(PEOPLE_DESC.search(entry.get('desc', '')))

    def _banned(self, key):
        """A word that never gets a picture (church, Germany, scientists...)."""
        if self.lang == 'en':
            return any(w in self.banned_words for w in key.split())
        return any(w in key for w in self.banned_words)

    # ---------------------------------------------------------- meaning rules
    def _key(self, phrase):
        return ' '.join(singular(w) for w in re.findall(r"[a-z0-9']+", phrase.lower())) if self.lang == 'en' \
            else phrase.strip()

    def _topic_ranks(self, board):
        """chapter -> rank (1 = closest) of every picture for what the chapter, within the whole video, is about."""
        texts: dict = {}
        for b in board['beats']:
            texts.setdefault(b['chapter'], []).append(b['display'][self.lang])
        chapters = list(texts)
        vecs = self._sentence_vectors([' '.join(texts[c]) for c in chapters] +
                                      [' '.join(' '.join(t) for t in texts.values())])
        out = {}
        for c, v in zip(chapters, vecs[:-1]):
            q = v + vecs[-1]
            order = np.argsort(-(self.pics @ (q / np.linalg.norm(q))))
            rank = np.empty(len(order), int)
            rank[order] = np.arange(1, len(order) + 1)
            out[c] = rank
        return out

    def _belongs(self, did, phrase, chapter):
        """May this picture stand for these words here? A curated drawing that the words name may; an emoji
        only if it is the very thing the words name; anything else only near the section's subject."""
        entry = self.matcher.entries[did]
        on_topic = self.topic[chapter][self.pos[did]] <= TOPIC_RANK
        if entry['set'] == 'fluent':
            return on_topic and (self.lang != 'en' or not phrase or self._is_head(did, phrase))
        return on_topic or (bool(phrase) and self._names(did, phrase))

    def _names(self, did, phrase):
        """The words say what the drawing shows: they are in its description (Chinese: among its first
        tags, since descriptions are English)."""
        entry = self.matcher.entries[did]
        if self.lang == 'en':
            shown = {singular(w) for w in re.findall(r'[a-z]+', entry.get('desc', '').lower())}
            words = [singular(w) for w in re.findall(r'[a-z]+', phrase.lower()) if w not in EN_STOP]
            return bool(words) and all(w in shown for w in words)
        return self._key(phrase) in [k.strip() for k in (entry.get('zh') or [])[:3]]

    def _is_head(self, did, phrase):
        """An emoji named 'light blue heart' is a heart: 'light' may not call it up; 'heart' may. One named
        'ferris wheel' is a Ferris wheel: 'wheels' alone may not call it up; 'Ferris wheel' may."""
        name = re.split(r'\b(?:at|with|of|in|on|for|from|to|and|or)\b', self.matcher.entries[did].get('desc', '').lower())[0]
        words = re.findall(r'[a-z]+', name)
        said = [singular(w) for w in re.findall(r'[a-z]+', phrase.lower())]
        if said and said[-1] in EMOJI_ALSO.get(did, ()):
            return True
        if not words or singular(words[-1]) != said[-1]:
            return False
        return all(w in EMOJI_ADJ or singular(w) in said for w in words[:-1])

    def _sense(self, key, cands, sentence):
        """Which picture a word gets: the one it had before (a word keeps its picture); else its best-tagged
        picture, unless another sense clearly fits the sentence better with the word itself hidden."""
        first = self.pictures.get(key)
        if first:
            return next((c for c in cands if c[0].id == first), None)
        best = max(cands, key=lambda c: c[1])
        if len(cands) == 1:
            return best
        hidden = self._sentence_vectors([sentence.replace(best[0].phrase, ' ')])[0]
        fit = {c[0].id: float(self.pics[self.pos[c[0].id]] @ hidden) for c in cands}
        rival = max(cands, key=lambda c: fit[c[0].id])
        return rival if fit[rival[0].id] >= fit[best[0].id] + SENSE_MARGIN else best

    def _inside(self, key, term):
        """Are the words of ``key`` part of ``term``?"""
        return set(key.split()) <= set(term.split()) if self.lang == 'en' else key in term

    def _pair(self, text, hits, taken=()):
        """The best hit, plus a second nearby hit about something else (never two takes on one phrase, and
        never across another picture said between them: the board would have to go back for it)."""
        first = hits[0]
        for other in hits[1:4]:
            if not (other.phrase and first.phrase) or abs(other.start - first.start) >= (90 if self.lang == 'en' else 40):
                continue
            if any(min(first.start, other.start) < pos < max(first.start, other.start) for pos in taken):
                continue
            a, b = first.phrase.lower(), other.phrase.lower()
            if a in b or b in a or singular_words(a) & singular_words(b):
                continue
            return sorted([first, other], key=lambda h: h.start)
        return [first]

    def _noun_after(self, rest: str) -> str:
        """The short noun phrase right after a number: '20 million books were' -> 'books'."""
        if self.lang == 'zh':
            import jieba
            words = [w for w in jieba.lcut(rest.lstrip('%％的个 ')) if re.match(r'[\u4e00-\u9fff]', w)]
            return words[0] if words else ''
        words = []
        for w in re.findall(r"[A-Za-z][\w'-]*", rest[:60]):
            if w.lower() in LABEL_STOP or len(words) == 3:
                if words:
                    break
                continue
            words.append(w)
        return ' '.join(words)[:LABEL_MAX['en']]

    def _relation(self, text, pair):
        between = text[pair[0].start + len(pair[0].phrase or ''):pair[1].start]
        for relation, pattern in (('arrow', CAUSE), ('vs', CONTRAST), ('plus', PLUS)):
            if re.search(pattern[self.lang], between, re.I):
                return relation
        return 'none'

    def _narrator_pose(self, text):
        for pose, cue in NARRATOR_CUES:
            if re.search(cue[self.lang], text, re.I):
                return pose
        return None

    # ------------------------------------------------------------ detectors
    def _quote(self, beat, text, norm, recent):
        m = re.search(r'[“"「]([^”"」]{12,})[”"」]', text)
        if not m or (self.lang == 'en' and len(m.group(1).split()) < 5):
            return None
        quote = m.group(1).strip()
        if len(quote) > (110 if self.lang == 'en' else 44):
            return None
        who = re.search(r'([A-Z][a-z]+(?: [A-Z][a-z]+){0,2}) (?:said|says|wrote|writes|argued|told)', text) \
            if self.lang == 'en' else re.search(r'([一-鿿A-Za-z]{2,8})(?:说|写道|表示)', text)
        v = {'id': f"{beat['id']}q", 'type': 'quote', 'text': {self.lang: quote}, 'size': 'wide'}
        if who:
            v['who'] = {self.lang: who.group(1)}
        trig = self._spoken(norm, quote[:24] if self.lang == 'en' else quote[:8])
        if trig:
            v['trigger'] = {self.lang: trig}
        return v, m.start()

    def _definition(self, beat, text, norm, recent):
        if self.lang == 'en':
            m = re.search(r"\b((?:an? |the )?[a-z][\w-]*(?: [a-z][\w-]*){0,3}) (?:called|known as|named) "
                          r"(?:an? |the )?([A-Za-z][\w-]*(?: [A-Za-z][\w-]*){0,2})\b", text)
            if not m or re.match(r'(this|that|these|those|it|is|are|was|were)\b', m.group(1).split(' ')[0]):
                return None
            term, words = m.group(2), m.group(1).split()
            while words and words[0] in PREPOSITIONS:
                words = words[1:]
            if not words or words[-1] in ('is', 'are', 'was', 'were', 'be', 'been'):
                return None                                # 'this process is called X': the definition is elsewhere
            gloss = ' '.join(words)
        else:
            m = re.search(r'([一-鿿]{2,12})(?:叫做|称为|被称为|叫作)([一-鿿A-Za-z]{2,8})', text)
            if not m:
                return None
            term, gloss = m.group(2), m.group(1)
        v = {'id': f"{beat['id']}g", 'type': 'glossary', 'term': {self.lang: term[:1].upper() + term[1:]},
             'text': {self.lang: gloss[:1].upper() + gloss[1:]}}
        trig = self._spoken(norm, term)
        if trig:
            v['trigger'] = {self.lang: trig}
        return v, m.start()

    def _number(self, beat, text, norm, recent):
        """One salient number: 'X% of Y' becomes a 100-square grid, anything else a big stat."""
        pct = re.search(r'(\d+(?:\.\d+)?)\s?%\s+of\s+(?:the\s+)?([a-z][\w-]*(?: [a-z][\w-]*)?)' if self.lang == 'en'
                        else r'(\d+(?:\.\d+)?)\s?[%％]的([一-鿿]{2,6})', text)
        if pct and 1 <= float(pct.group(1)) <= 99:
            value = pct.group(0).split('of')[0].strip() if self.lang == 'en' else pct.group(1) + '%'
            label = pct.group(2) if self.lang == 'en' else self._noun_after(text[pct.end(1):])
            if self.lang == 'en':                     # "27% of trips are made ..." -> "trips"
                words = label.split()
                while len(words) > 1 and words[-1] in AUX | PREPS | DETERMINERS:
                    words.pop()
                label = ' '.join(words)
            title = f'{value} of {label}' if self.lang == 'en' else f'{value}的{label}'
            v = {'id': f"{beat['id']}p", 'type': 'grid100', 'title': {self.lang: title},
                 'filled': round(float(pct.group(1))),
                 'legend': [{'text': {self.lang: label}, 'kind': 'filled'}]}
            trig = self._spoken(norm, value)
            if trig:
                v['trigger'] = {self.lang: trig}
            return v, pct.start()
        num = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
        pattern = (rf'(?:\$|€|£)?{num}(?:\s?(?:%|×|(?:percent|million|billion|trillion|thousand|bn|m|x)\b))?'
                   if self.lang == 'en' else rf'{num}\s?(?:%|％|万亿|亿|万|千|倍)?')
        for m in re.finditer(pattern, text):
            token = m.group(0).strip()
            digits = re.sub(r'[^\d.]', '', token)
            if not digits or digits == '.':
                continue
            is_year = re.fullmatch(r'1[1-9]\d\d|20\d\d', token) is not None
            salient = (not is_year) and (float(digits) >= 20 or token != digits)
            if not salient:
                continue
            label = self._noun_after(text[m.end():])
            v = {'id': f"{beat['id']}n", 'type': 'stat', 'value': {self.lang: token}, 'label': {self.lang: label or ' '}}
            if label:
                sentence = next((x for x in script.sentences(text, self.lang) if token in x), text)
                vec = self._sentence_vectors([sentence])[0]
                for hit in self.matcher.lexical(label):
                    if hit.id not in recent and float(self.vecs[self.pos[hit.id]] @ vec) >= \
                            AGREE[self.lang][self.matcher.entries[hit.id]['set']][1] and \
                            self._key(hit.phrase) not in GENERIC[self.lang] and \
                            self._belongs(hit.id, hit.phrase, beat['chapter']):
                        v['doodle'] = hit.id
                        break
            trig = self._spoken(norm, token, m.start())
            if trig:
                v['trigger'] = {self.lang: trig}
            return v, m.start()
        return None

    def _event_label(self, sentence, date):
        """Who or what a dated clause is about: a named person or group first, else the clause's subject."""
        if self.lang == 'zh':
            return self._event_label_zh(sentence, date)
        at = sentence.find(date)
        parts = [(m.start(), m.group(0)) for m in re.finditer(r'[^,;:()]+', sentence)]
        k = next((i for i, (s, p) in enumerate(parts) if s <= at < s + len(p)), 0)
        words = re.findall(r"[A-Za-z][\w'’-]*", parts[k][1].replace(date, ' '))
        used = k
        if all(w.lower() in PREPS | DETERMINERS for w in words) and k + 1 < len(parts):
            words = re.findall(r"[A-Za-z][\w'’-]*", parts[k + 1][1])    # "By 1500, printing presses were ..."
            used = k + 1
        subject = []                                  # the words before the clause's verb or first preposition
        for i, w in enumerate(words):
            low = w.lower()
            if low in AUX or low in PREPS or (subject and (low.endswith('ed') or low in PAST)):
                break
            subject.append(w)
        names = [w for w in subject if w[0].isupper() and w.lower() not in DETERMINERS | EN_STOP]
        if names:                                     # "Martin Luther's arguments" -> "Martin Luther"
            first = subject.index(names[0])
            run = [names[0]]
            for w in subject[first + 1:]:
                if not w[0].isupper():
                    break
                run.append(w)
            follows = subject[first + len(run):]
            if not follows or run[-1].endswith(("'s", "’s")):   # "French makers": an adjective, not a name
                label = re.sub(r"['’]s$", '', ' '.join(run))
                return label if len(label) <= LABEL_MAX['en'] else label.split()[-1]
        if used + 1 < len(parts):                     # "The fix came in 1885, when John Kemp Starley sold ..."
            nxt = re.findall(r"[A-Za-z][\w'’-]*", parts[used + 1][1])
            while nxt and nxt[0].lower() in CONNECTIVES:
                nxt = nxt[1:]
            run = []
            for w in nxt:
                if not w[0].isupper():
                    break
                run.append(w)
            after = nxt[len(run)].lower() if len(run) < len(nxt) else ''
            if run and run[0].lower() not in DETERMINERS | EN_STOP and (not after or after in AUX | PAST
                                                                          or after.endswith('ed')):
                label = re.sub(r"['’]s$", '', ' '.join(run))
                return label if len(label) <= LABEL_MAX['en'] else label.split()[-1]
        det = subject[0].lower() if subject else ''
        content = [w for w in subject if w.lower() not in DETERMINERS and not w.isdigit()]
        if len(content) == 1 and det in ('every', 'each'):
            content = [content[0] + 's']              # "every book" -> "books"
        if len(content) == 1:                         # "every book in Europe was copied by hand"
            rest = words[len(subject):]
            aux = next((i for i, w in enumerate(rest) if w.lower() in AUX), None)
            if aux is not None and aux + 1 < len(rest) and rest[aux + 1].lower().endswith(('ed', 'en')):
                content += rest[aux + 1:aux + 4]
        label = ' '.join(content[:4])
        while len(label) > LABEL_MAX['en'] and ' ' in label:
            label = label.rsplit(' ', 1)[0]
        if not label:
            hit = next((h for h in self.matcher.lexical(sentence) if self._key(h.phrase) not in GENERIC['en']), None)
            label = hit.phrase if hit else ''
        return label[:1].upper() + label[1:]

    def _event_label_zh(self, sentence, date):
        """中文：日期所在分句里的人名或机构名，否则第一个名词短语。"""
        import jieba.posseg as pseg
        at = sentence.find(date)
        clauses = [(m.start(), m.group(0)) for m in re.finditer(r'[^，。；：！？、]+', sentence)]
        k = next((i for i, (s, c) in enumerate(clauses) if s <= at < s + len(c)), 0)
        clause = re.sub(re.escape(date) + r'\s*年?(?:代|初|末|间|左右)?', ' ', clauses[k][1] if clauses else sentence)
        if not re.sub(r'[\s在于到从至的了]', '', clause) and k + 1 < len(clauses):
            clause = clauses[k + 1][1]                # "1911年，辛亥革命……": the event is in the next clause
        words = [(w, f) for w, f in pseg.cut(clause) if w.strip()]
        for w, f in words:
            if f in ('nr', 'nt', 'nz') and len(w) >= 2:
                return w[:LABEL_MAX['zh']]
        run = []
        for w, f in words:
            if f.startswith('n') and f != 'ns':
                run.append(w)
            elif run:
                break
        return ''.join(run)[:LABEL_MAX['zh']] or re.sub(r'[在于到从的了]', '', clause).strip()[:LABEL_MAX['zh']]

    def _timelines(self, board):
        """({anchor beat id: timeline page}, {beat id: (first, last) text positions the page holds}) for every
        section with 3+ distinct years: each date is written when it is said, so nothing is written early, and
        the page stays on the board from its first date to its last (other pictures wait until after it)."""
        lang, out, spans = self.lang, {}, {}
        narration = [b for b in board['beats'] if b['kind'] == 'narration']
        for chapter in board['chapters']:
            if chapter['kind'] not in ('section', 'board'):
                continue
            made = self._timeline([b for b in narration if b['chapter'] == chapter['id']], 3)
            if made:
                anchor, page, held = made
                out[anchor] = page
                spans.update(held)
        return out, spans

    def _timeline(self, beats, min_years):
        lang = self.lang
        events = []
        for b in beats:
            text = b['display'][lang]
            for m in re.finditer(r'(?<!\d)(1[1-9]\d\d|20\d\d)(?:s)?(?!\d)', text):
                if re.search(r'\b(?:before|until|till|prior to)\s+(?:the\s+)?$', text[max(0, m.start() - 16):m.start()], re.I) \
                        or re.match(r'年?(?:之前|以前)', text[m.end():]):
                    continue                          # "Before the 1450s, ...": nothing happens at that date
                sentence = next((s for s in script.sentences(text, lang) if m.group(0) in s), text)
                events.append((int(m.group(1)), m.group(0), self._event_label(sentence, m.group(0)), b, m.start()))
        years = sorted({e[0] for e in events})
        if len(years) < min_years:
            return None
        first = {}
        for e in events:                              # an exact year says more than a decade ("1450" over "1450s")
            if e[0] not in first or (first[e[0]][1].endswith('s') and not e[1].endswith('s')):
                first[e[0]] = e
        chosen = [first[y] for y in years[:6]]
        order = {b['id']: k for k, b in enumerate(beats)}
        spoken = sorted(chosen, key=lambda e: (order[e[3]['id']], e[4]))
        anchor, last = spoken[0][3], spoken[-1][3]
        lo, hi = years[0], years[len(chosen) - 1]
        evs = []
        for y, display, label, b, start in chosen:
            ev = {'pos': round((y - lo) / max(1, hi - lo), 3), 'display': {lang: display}, 'label': {lang: label}}
            trig = self._spoken(numbers.normalize(b['display'][lang], lang), display, start)
            if trig:
                ev['trigger'] = {lang: trig} if b is anchor else {'beat': b['id'], lang: trig}
            evs.append(ev)
        page = {'id': f"{anchor['id']}t", 'type': 'lanes', 'title': {lang: ''}, 'lanes': [{'label': {lang: ''}, 'events': evs}]}
        first_trig = next((ev['trigger'] for ev, e in zip(evs, chosen) if e is spoken[0] and 'trigger' in ev), None)
        if first_trig:
            page['trigger'] = first_trig
        held, a, z = {}, order[anchor['id']], order[last['id']]
        for b in beats[a:z + 1]:
            held[b['id']] = (spoken[0][4] if b is anchor else -1, spoken[-1][4] if b is last else 10 ** 6)
        return anchor['id'], page, held

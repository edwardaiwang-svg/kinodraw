"""LLM director: the rules director drafts, the model improves one section at a time, code decides.

Every answer is checked before it is used: doodles must come from the beat's candidates
(or the narrator poses), triggers must be words of the beat, numbers/dates/quotes must
appear in the section text, and texts must fit. A beat whose answer fails keeps its rules
draft; a section whose call fails keeps all of its rules visuals. The model may re-pick a
sentence's pictures, but never leaves a sentence with less drawn than the rules planned.
"""
from __future__ import annotations

import re

from ... import numbers, script
from ...engine.storyboard import normalize
from ..rules import RulesDirector
from ..validate import validate
from .providers import ProviderError, Usage
from .schema import LIMITS, MAX_VISUALS_PER_BEAT

NARRATOR_POSES = ['narrator_wave', 'narrator_explain', 'narrator_present', 'narrator_think', 'narrator_magnifier',
                  'narrator_notebook', 'narrator_thumbs', 'narrator_worried']
PAGE_TYPES = {'bars', 'grid100', 'timeline', 'flow', 'split'}
KEEPABLE = {'cluster', 'stat', 'quote', 'glossary'}     # rules visuals that stand alone in one sentence


class LLMDirector:
    def __init__(self, provider, lang: str, candidates_per_beat: int = 12):
        self.provider, self.lang, self.k = provider, lang, candidates_per_beat
        self.rules = RulesDirector(lang)
        self.usage = Usage()
        self.notes: list[str] = []

    # --------------------------------------------------------------- driver
    def direct(self, board: dict, progress=None) -> dict:
        lang = self.lang
        self.rules.direct(board)                      # the draft, and the fallback
        chapters = normalize(board)['chapters']
        groups = [(c, [b for b in board['beats'] if b['chapter'] == c['id'] and b['kind'] in ('narration', 'take')])
                  for c in chapters if c['kind'] in ('section', 'board', 'outro')]
        groups = [(c, beats) for c, beats in groups if beats]
        if hasattr(self.provider, 'open_video'):
            try:
                self.provider.open_video(len(groups), sum(len(b['display'][lang]) for _, bs in groups for b in bs))
            except ProviderError as error:            # quota, daily budget, sign-in, network: the whole video stays offline
                self.notes.append(f'The offline director planned this video ({error})')
                return {'usage': self.usage, 'notes': self.notes, 'warnings': validate(board)['warnings']}
        for i, (chapter, beats) in enumerate(groups):
            if progress:
                progress('director', i, len(groups))
            payload = self._payload(board, chapter, beats, len(groups))
            try:
                answer = self.provider.direct_section(payload, self.usage)
            except ProviderError as error:
                self.notes.append(f"{chapter['id']}: kept the offline plan ({error})")
                continue
            self._apply(board, chapter, beats, answer, payload)
        if progress:
            progress('director', len(groups), len(groups))
        report = validate(board)
        if not report['ok']:                          # should not happen: every piece was checked
            raise RuntimeError('LLM director produced an invalid storyboard: ' + '; '.join(report['errors'][:3]))
        return {'usage': self.usage, 'notes': self.notes, 'warnings': report['warnings']}

    # -------------------------------------------------------------- request
    def _payload(self, board, chapter, beats, n_sections) -> dict:
        lang, out = self.lang, []
        for b in beats:
            text = b['display'][lang]
            hits = self.rules.matcher.lexical(text)[:self.k]
            seen = {h.id for h in hits}
            hits += [h for h in self.rules.matcher.semantic(text, self.k) if h.id not in seen][:self.k - len(hits) + 4]
            out.append({
                'beat_id': b['id'],
                'kind': 'takeaway' if b['kind'] == 'take' else 'narration',
                'text': text,
                'visual_budget': 0 if b['kind'] == 'take' else self.rules._budget(text),
                'candidates': [{'id': h.id, 'desc': self.rules.matcher.entries[h.id].get('desc', '')[:70]}
                               for h in hits],
                'rules_draft': [_summary(v, lang) for v in b['visuals']],
            })
        title = (chapter.get('title') or {}).get(lang, '')
        return {'language': lang, 'video_title': board['title'][lang], 'section_title': title,
                'section_kind': chapter['kind'], 'sections_in_video': n_sections,
                'narrator_poses': NARRATOR_POSES, 'beats': out}

    # --------------------------------------------------------------- answer
    def _apply(self, board, chapter, beats, answer, payload):
        lang, lim = self.lang, LIMITS[self.lang]
        section_text = ' '.join(b['display'][lang] for b in beats)
        by_id = {b['id']: b for b in beats}
        allowed = {p['beat_id']: {c['id'] for c in p['candidates']} | set(NARRATOR_POSES) for p in payload['beats']}
        pages = 0
        for item in answer.get('beats') or []:
            beat = by_id.get(item.get('beat_id'))
            if beat is None or beat['kind'] == 'take':
                continue
            norm = numbers.normalize(beat['display'][lang], lang)
            made = []
            for k, raw in enumerate((item.get('visuals') or [])[:MAX_VISUALS_PER_BEAT]):
                try:
                    v = self._convert(raw, beat, norm, section_text, allowed[beat['id']], k)
                except ValueError as error:
                    self.notes.append(f"{beat['id']}: dropped a {raw.get('type')} ({error})")
                    continue
                if raw['type'] in PAGE_TYPES:
                    if pages:
                        self.notes.append(f"{beat['id']}: dropped a second chart in one section")
                        continue
                    pages += 1
                made.append(v)
            if made:
                beat['visuals'] = self._keep_pictures(beat, made, beat['visuals'])
        if chapter['kind'] == 'section':
            original = next(c for c in board['chapters'] if c['id'] == chapter['id'])
            title, hook = _clean(answer.get('section_title')), _clean(answer.get('hook'))
            if title and len(title) <= lim['title']:
                original['title'] = {lang: title}
            if hook and len(hook) <= lim['hook']:
                original['hook'] = {lang: hook}
            take = next((b for b in beats if b['kind'] == 'take'), None)
            head = _clean(answer.get('takeaway'))
            fits = head and (len(head.split()) <= lim['takeaway_words'] if lang == 'en' else len(head) <= lim['takeaway_chars'])
            if take and fits and _numbers_ok(head, section_text):
                take['take']['headline'] = {lang: head}
                script.sync_takes(board)              # the narrator says what the note shows

    def _keep_pictures(self, beat: dict, made: list, draft: list) -> list:
        """Code decides how much is drawn: sentence by sentence, the model's visuals replace the rules draft only
        when they draw at least as much (a list keeps every item; a sentence the model left bare keeps its
        picture). A chart page from the model keeps the beat as the model planned it."""
        if any(v['type'] in PAGE_TYPES for v in made):
            return made
        lang = self.lang
        spoken = numbers.normalize(beat['display'][lang], lang).spoken
        ends, cursor = [], 0
        for sentence in script.sentences(spoken, lang) or [spoken]:
            cursor = spoken.find(sentence, cursor) + len(sentence)
            ends.append(cursor)

        def sentence_of(v):
            at = _at(v, spoken, lang)
            return next((k for k, end in enumerate(ends) if at < end), len(ends) - 1)
        drawn = {i['doodle'] for v in made for i in v.get('items') or []}
        model, rules = {}, {}
        for v in made:
            model.setdefault(sentence_of(v), []).append(v)
        for v in draft:                               # (a picture the model already drew elsewhere is not repeated)
            if v['type'] in KEEPABLE and not (v['type'] == 'cluster' and {i['doodle'] for i in v['items']} <= drawn):
                rules.setdefault(sentence_of(v), []).append(v)
        kept = []
        for k in sorted(model.keys() | rules.keys()):
            ours, theirs = rules.get(k, []), model.get(k, [])
            kept += ours if _amount(ours) > _amount(theirs) else theirs
        return sorted(kept, key=lambda v: _at(v, spoken, lang))

    def _convert(self, raw: dict, beat: dict, norm, section_text: str, allowed: set, k: int) -> dict:
        """One schema visual -> the renderer's spec, or ValueError explaining why it is unusable."""
        lang, lim = self.lang, LIMITS[self.lang]
        kind = raw.get('type')
        vid = f"{beat['id']}m{k}"

        def trig(phrase):
            spoken = norm.find(phrase.strip()) if phrase and phrase.strip() else None
            return {lang: spoken} if spoken and spoken in norm.spoken else None

        def text(s, cap, what):
            s = _clean(s)
            if len(s) > cap:
                raise ValueError(f'{what} too long')
            return {lang: s}

        def doodle(d, required=False):
            d = _clean(d)
            if not d:
                if required:
                    raise ValueError('no doodle')
                return None
            if d not in allowed:
                raise ValueError(f'doodle {d!r} was not offered')
            return d

        def with_trigger(spec, phrase):
            t = trig(phrase)
            if t:
                spec['trigger'] = t
            return spec
        if kind == 'cluster':
            items = []
            for it in (raw.get('items') or [])[:3]:
                entry = {'doodle': doodle(it.get('doodle'), required=True)}
                if _clean(it.get('label')):
                    entry['label'] = text(it['label'], lim['label'], 'label')
                items.append(with_trigger(entry, it.get('trigger')))
            if not items:
                raise ValueError('empty cluster')
            v = {'id': vid, 'type': 'cluster', 'items': items, 'relation': raw.get('relation') or 'none'}
            first = next((i['trigger'] for i in items if i.get('trigger')), None)
            return {**v, 'trigger': first} if first else v
        if kind == 'stat':
            value = _clean(raw.get('value'))
            if not value or value not in section_text:
                raise ValueError(f'value {value!r} is not in the text')
            v = {'id': vid, 'type': 'stat', 'value': {lang: value}, 'label': text(raw.get('label') or ' ', lim['label'], 'label')}
            d = doodle(raw.get('doodle'))
            if d:
                v['doodle'] = d
            return with_trigger(v, raw.get('trigger') or value)
        if kind == 'quote':
            quote = _clean(raw.get('text')).strip('“”"「」')
            if not quote or _squash(quote) not in _squash(section_text):
                raise ValueError('the quote is not in the text')
            v = {'id': vid, 'type': 'quote', 'text': text(quote, lim['quote'], 'quote'), 'size': 'wide'}
            if _clean(raw.get('who')):
                v['who'] = {lang: _clean(raw['who'])}
            return with_trigger(v, raw.get('trigger'))
        if kind == 'glossary':
            term = _clean(raw.get('term'))
            if not term or term.lower() not in section_text.lower():
                raise ValueError(f'term {term!r} is not in the text')
            v = {'id': vid, 'type': 'glossary', 'term': {lang: term}, 'text': text(raw.get('text'), lim['gloss'], 'definition')}
            return with_trigger(v, raw.get('trigger') or term)
        if kind == 'bars':
            rows = []
            for r in (raw.get('rows') or [])[:6]:
                display = _clean(r.get('display'))
                if not display or display not in section_text or not isinstance(r.get('value'), (int, float)):
                    raise ValueError(f'bar {display!r} is not in the text')
                rows.append(with_trigger({'label': text(r.get('label'), lim['label'], 'label'), 'value': float(r['value']),
                                          'display': {lang: display}}, r.get('trigger') or display))
            if len(rows) < 2:
                raise ValueError('a bar chart needs two numbers')
            v = {'id': vid, 'type': 'bars', 'title': text(raw.get('title'), lim['title'], 'title'), 'rows': rows}
            if _clean(raw.get('unit')):
                v['unit'] = {lang: _clean(raw['unit'])}
            return v
        if kind == 'grid100':
            filled = raw.get('filled')
            if not isinstance(filled, int) or not 1 <= filled <= 99 or str(filled) not in section_text:
                raise ValueError('the grid number is not in the text')
            v = {'id': vid, 'type': 'grid100', 'title': text(raw.get('title'), lim['title'], 'title'), 'filled': filled,
                 'legend': [{'text': text(raw.get('legend') or ' ', lim['label'] * 2, 'legend'), 'kind': 'filled'}]}
            return with_trigger(v, raw.get('trigger') or str(filled))
        if kind == 'timeline':
            events = []
            raw_events = (raw.get('events') or [])[:6]
            for i, e in enumerate(raw_events):
                when = _clean(e.get('when'))
                if not when or when not in section_text:
                    raise ValueError(f'date {when!r} is not in the text')
                if when not in beat['display'][lang]:        # nothing is written before it is said
                    raise ValueError(f'date {when!r} is said in another beat')
                events.append(with_trigger({'pos': round(i / max(1, len(raw_events) - 1), 3), 'display': {lang: when},
                                            'label': text(e.get('label'), lim['label'], 'label')}, e.get('trigger') or when))
            if len(events) < 3:
                raise ValueError('a timeline needs three dates')
            return {'id': vid, 'type': 'lanes', 'title': text(raw.get('title'), lim['title'], 'title'),
                    'lanes': [{'label': {lang: ''}, 'events': events}]}
        if kind == 'flow':
            nodes = []
            for i, n in enumerate((raw.get('nodes') or [])[:5]):
                node = {'id': f'n{i}', 'label': text(n.get('label'), lim['label'], 'label')}
                d = doodle(n.get('doodle'))
                if d:
                    node['doodle'] = d
                nodes.append(with_trigger(node, n.get('trigger')))
            if len(nodes) < 3:
                raise ValueError('a flow needs three steps')
            layout = raw.get('layout') if raw.get('layout') in ('chain', 'loop') else 'chain'
            edges = [{'from': f'n{i}', 'to': f'n{i + 1}'} for i in range(len(nodes) - 1)]
            if layout == 'loop':
                edges.append({'from': f'n{len(nodes) - 1}', 'to': 'n0'})
            return {'id': vid, 'type': 'flow', 'title': text(raw.get('title'), lim['title'], 'title'),
                    'layout': layout, 'nodes': nodes, 'edges': edges}
        if kind == 'split':
            sides = {}
            for side in ('left', 'right'):
                s = raw.get(side) or {}
                spec = {'who': text(s.get('title'), lim['label'], 'title'), 'text': text(s.get('text'), lim['gloss'], 'text')}
                d = doodle(s.get('doodle'))
                if d:
                    spec['doodle'] = d
                sides[side] = with_trigger(spec, s.get('trigger'))
            v = {'id': vid, 'type': 'split', **sides}
            if _clean(raw.get('verdict')):
                v['verdict'] = {'text': text(raw['verdict'], lim['gloss'], 'verdict')}
            return v
        raise ValueError(f'unknown type {kind!r}')


def _clean(s) -> str:
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def _squash(s: str) -> str:
    return re.sub(r'[\s“”"「」‘’\']+', '', s).lower()


def _numbers_ok(text: str, source: str) -> bool:
    """Every number in ``text`` also appears in ``source`` (no invented figures)."""
    return all(n in source for n in re.findall(r'\d[\d,.]*', text))


def _summary(v: dict, lang: str) -> dict:
    """A compact view of a rules-draft visual for the prompt."""
    out = {'type': v['type']}
    if v['type'] == 'cluster':
        out['items'] = [it['doodle'] for it in v.get('items', [])]
    for key in ('value', 'term', 'title'):
        if isinstance(v.get(key), dict):
            out[key] = v[key].get(lang)
    return out


def _at(v: dict, spoken: str, lang: str) -> int:
    """Where a visual starts in the beat's spoken text: its trigger or its first item's; 0 = as the beat starts."""
    for trigger in [v.get('trigger')] + [i.get('trigger') for i in v.get('items') or []]:
        at = spoken.find(trigger[lang]) if trigger and trigger.get(lang) else -1
        if at >= 0:
            return at
    return 0


def _amount(visuals: list) -> int:
    """How much visuals put on the board: every doodle, and every number, quote or note."""
    return sum(len(v['items']) if v['type'] == 'cluster' else 1 + bool(v.get('doodle')) for v in visuals)

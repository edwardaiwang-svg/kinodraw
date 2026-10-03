"""LLM director with recorded answers: good visuals are used, bad ones fall back to the rules draft."""
import copy
from pathlib import Path

import pytest

from doodlestudio import ingest, script
from doodlestudio.director.llm.director import LLMDirector
from doodlestudio.director.llm.providers import ProviderError, Usage
from doodlestudio.director.validate import validate

FIX = Path(__file__).parent / 'fixtures'


class Recorded:
    """Answers per section title (or raises), like a provider would."""
    name, model = 'recorded', 'gpt-6-luna'

    def __init__(self, answers):
        self.answers, self.payloads = answers, []

    def direct_section(self, payload, usage: Usage):
        self.payloads.append(payload)
        usage.add(self.model, 3000, 1500)
        answer = self.answers.get(payload['section_title'])
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return {'section_title': '', 'hook': '', 'takeaway': '', 'beats': []}
        return answer(payload) if callable(answer) else answer


@pytest.fixture()
def board():
    return script.build(ingest.read(FIX / 'printing_press.md'))


def _beat(payload, n=0):
    return payload['beats'][n]


def good_section(payload):
    b0 = _beat(payload)
    cand = b0['candidates'][0]['id']
    return {'section_title': 'Gutenberg builds a machine', 'hook': 'Metal letters, fast', 'takeaway': 'Printing got fast and cheap',
            'beats': [{'beat_id': b0['beat_id'], 'visuals': [
                {'type': 'cluster', 'relation': 'none', 'items': [{'doodle': cand, 'label': 'Gutenberg', 'trigger': 'Johannes Gutenberg'}]},
                {'type': 'stat', 'value': '1450', 'label': 'invented', 'doodle': '', 'trigger': 'Around 1450'},
            ]}]}


def bad_section(payload):
    b0 = _beat(payload)
    return {'section_title': 'x' * 80, 'hook': '', 'takeaway': 'It sold 999 million copies',
            'beats': [{'beat_id': b0['beat_id'], 'visuals': [
                {'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'unicorn_rainbow', 'label': '', 'trigger': 'x'}]},
                {'type': 'stat', 'value': '42 million', 'label': 'invented', 'doodle': '', 'trigger': 'nothing'},
                {'type': 'quote', 'text': 'Printing is the best invention ever', 'who': 'Nobody', 'trigger': ''},
            ]}]}


def test_good_answers_are_used_and_mapped_to_spoken_text(board):
    rec = Recorded({'One machine, one idea': good_section})
    report = LLMDirector(rec, 'en').direct(board)
    s1 = next(c for c in board['chapters'] if c['id'] == 's1')
    assert s1['title']['en'] == 'Gutenberg builds a machine' and s1['hook']['en'] == 'Metal letters, fast'
    first = next(b for b in board['beats'] if b['chapter'] == 's1' and b['kind'] == 'narration')
    kinds = [v['type'] for v in first['visuals']]
    assert kinds == ['stat', 'cluster']                                        # in spoken order: the date is said first
    assert first['visuals'][0]['trigger']['en'] == 'Around fourteen fifty'       # display phrase -> spoken words
    take = next(b for b in board['beats'] if b['chapter'] == 's1' and b['kind'] == 'take')
    assert take['take']['headline']['en'] == 'Printing got fast and cheap'
    assert validate(board)['ok'] and report['usage'].calls == 5 and report['usage'].cost_usd > 0


def test_bad_answers_fall_back_to_the_rules_draft(board):
    draft = LLMDirector(Recorded({}), 'en')
    reference = copy.deepcopy(board)
    draft.rules.direct(reference)
    rec = Recorded({'One machine, one idea': bad_section, 'Books everywhere': ProviderError('rate limited')})
    report = LLMDirector(rec, 'en').direct(board)
    first = next(b for b in board['beats'] if b['chapter'] == 's1' and b['kind'] == 'narration')
    ref_first = next(b for b in reference['beats'] if b['chapter'] == 's1' and b['kind'] == 'narration')
    assert first['visuals'] == ref_first['visuals']                          # every visual rejected -> draft kept
    s1 = next(c for c in board['chapters'] if c['id'] == 's1')
    assert s1['title']['en'] == 'One machine, one idea'                       # too-long title rejected
    take = next(b for b in board['beats'] if b['chapter'] == 's1' and b['kind'] == 'take')
    assert '999' not in take['take']['headline']['en']                       # invented number rejected
    notes = ' '.join(report['notes'])
    assert 'was not offered' in notes and 'not in the text' in notes and 'rate limited' in notes
    assert validate(board)['ok']


def test_a_refused_video_keeps_the_whole_offline_plan(board):
    class Refused(Recorded):                      # Doodle Cloud says no at /v1/videos: quota, budget, kill switch
        def open_video(self, sections, characters):
            raise ProviderError("Doodle Cloud 503: today's AI budget is used up; this video will use offline mode")
    reference = copy.deepcopy(board)
    LLMDirector(Recorded({}), 'en').rules.direct(reference)
    rec = Refused({'One machine, one idea': good_section})
    report = LLMDirector(rec, 'en').direct(board)
    assert rec.payloads == []                                                # no section was sent
    assert [b['visuals'] for b in board['beats']] == [b['visuals'] for b in reference['beats']]
    assert report['notes'][0].startswith('The offline director planned this video (Doodle Cloud 503')
    assert validate(board)['ok']


def test_payload_offers_candidates_and_budget(board):
    rec = Recorded({})
    LLMDirector(rec, 'en').direct(board)
    beat = rec.payloads[1]['beats'][0]
    assert beat['candidates'] and all('id' in c and 'desc' in c for c in beat['candidates'])
    assert beat['visual_budget'] >= 1 and 'narrator_think' in rec.payloads[1]['narrator_poses']


def test_command_provider_pipes_json_both_ways(tmp_path):
    import json
    import sys
    from doodlestudio.director.llm.providers import CommandProvider
    from doodlestudio.director.llm.schema import SECTION_SCHEMA
    tool = tmp_path / 'tool.py'
    tool.write_text("import json, sys\n"
                    "req = json.load(sys.stdin)\n"
                    "assert set(req) == {'model', 'system', 'user', 'schema'} and req['model'] == 'm1'\n"
                    "section = json.loads(req['user'])\n"
                    "print(json.dumps({'section_title': section['section_title'], 'hook': '', 'takeaway': '', 'beats': []}))\n")
    provider = CommandProvider('m1', command=f'"{sys.executable}" "{tool}"')
    usage = Usage()
    out = provider.direct_section({'section_title': 'Part 1', 'beats': []}, usage)
    assert out['section_title'] == 'Part 1' and usage.calls == 1 and usage.cost_usd is None
    assert SECTION_SCHEMA['type'] == 'object'
    failing = tmp_path / 'fail.py'
    failing.write_text("import sys\nsys.exit('no subscription')\n")
    with pytest.raises(ProviderError, match='no subscription'):
        CommandProvider('m1', command=f'"{sys.executable}" "{failing}"').direct_section({'section_title': 'x'}, Usage())


def test_opening_the_app_never_reads_the_keychain(tmp_path, monkeypatch):
    """macOS asks before an app reads a keychain entry it did not create (every unsigned update counts as a
    new app), so the Studio's startup state must list saved keys from names alone."""
    import keyring
    from doodlestudio.director.llm import providers
    from doodlestudio.studio import server
    monkeypatch.setattr(providers, 'SAVED', tmp_path / 'saved-keys.json')
    monkeypatch.setattr(keyring, 'set_password', lambda *a: None)
    providers.save_key('openai', 'sk-test')

    reads = []
    monkeypatch.setattr(keyring, 'get_password', lambda *a: reads.append(a))
    for var in providers.KEY_ENV.values():
        monkeypatch.delenv(var, raising=False)
    state = server.state()
    assert not reads, f'the keychain was read at startup: {reads}'
    assert state['keys'] == {'openai': True, 'anthropic': False, 'compat': False, 'command': False}


def test_an_ai_takeaway_is_what_the_narrator_says(board):
    LLMDirector(Recorded({'One machine, one idea': good_section}), 'en').direct(board)
    take = next(b for b in board['beats'] if b['chapter'] == 's1' and b['kind'] == 'take')
    assert take['display']['en'] == 'Key takeaway: Printing got fast and cheap.'
    assert take['spoken']['en'] == take['display']['en']


def test_banned_pictures_are_never_offered_or_kept(board):
    from doodlestudio.library import banned
    rec = Recorded({})
    LLMDirector(rec, 'en').direct(board)
    offered = {c['id'] for p in rec.payloads for b in p['beats'] for c in b['candidates']}
    assert offered and not offered & banned()['doodles']


def test_the_model_never_leaves_a_sentence_with_less_than_the_rules_drew(board):
    """Code decides how much is drawn: the model re-picks pictures sentence by sentence, but a list keeps every item
    and a sentence the model left bare keeps the rules' picture."""
    def outro(payload):
        beat = next((b for b in payload['beats'] if 'newspaper' in b['text']), None)
        if beat is None:
            return {'section_title': '', 'hook': '', 'takeaway': '', 'beats': []}
        return {'section_title': '', 'hook': '', 'takeaway': '', 'beats': [{'beat_id': beat['beat_id'], 'visuals': [
            {'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'book_stack', 'label': '', 'trigger': 'knowledge'}]},
            {'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'newspaper', 'label': '', 'trigger': 'a newspaper'}]},
        ]}]}
    reference = copy.deepcopy(board)
    LLMDirector(Recorded({}), 'en').rules.direct(reference)
    rec = Recorded({'': outro})
    LLMDirector(rec, 'en').direct(board)
    assert any('newspaper' in b['text'] for p in rec.payloads for b in p['beats'])   # the outro was asked
    beat = next(b for b in board['beats'] if b['kind'] == 'narration' and 'newspaper' in b['display']['en'])
    draft = next(b for b in reference['beats'] if b['id'] == beat['id'])['visuals']
    doodles = [[i['doodle'] for i in v.get('items', [])] for v in beat['visuals']]
    assert doodles[0] == ['book_stack']                   # 1st sentence: the model's pick replaces printing_press (a tie)
    assert ['book_stack', 'newspaper', 'web_page'] in doodles        # 2nd: the whole list beats the model's lone newspaper
    assert ['newspaper'] not in doodles and ['printing_press'] not in doodles
    assert [v['type'] for v in beat['visuals'][1:]] == [v['type'] for v in draft[1:]]
    assert validate(board)['ok']


def test_a_rules_picture_the_model_drew_elsewhere_is_not_drawn_twice(board):
    def outro(payload):
        beat = next((b for b in payload['beats'] if 'newspaper' in b['text']), None)
        if beat is None:
            return {'section_title': '', 'hook': '', 'takeaway': '', 'beats': []}
        assert 'lightbulb_idea' in {c['id'] for c in beat['candidates']}
        return {'section_title': '', 'hook': '', 'takeaway': '', 'beats': [{'beat_id': beat['beat_id'], 'visuals': [
            {'type': 'cluster', 'relation': 'none', 'items': [{'doodle': 'lightbulb_idea', 'label': '', 'trigger': 'knowledge'}]},
        ]}]}
    LLMDirector(Recorded({'': outro}), 'en').direct(board)
    beat = next(b for b in board['beats'] if b['kind'] == 'narration' and 'newspaper' in b['display']['en'])
    doodles = [i['doodle'] for v in beat['visuals'] for i in v.get('items', [])]
    assert doodles.count('lightbulb_idea') == 1 and doodles[0] == 'lightbulb_idea'
    assert ['book_stack', 'newspaper', 'web_page'] == doodles[1:4]         # the list still comes with the second sentence


def test_chart_pages_keep_their_beat_whoever_planned_them():
    """A model timeline becomes a 'lanes' page: it keeps its beat as the model planned it (no rules pictures drawn in
    the middle of it), and a rules timeline or 100-square grid is never dropped for the model's lone picture."""
    board = script.build(ingest.read(
        '# A day at the bakery\n\nAt dawn, the baker lights the oven and mixes flour and water. At noon, fresh bread '
        'and cakes fill the shop window. At dusk, the shop closes and the ovens cool down.\n\nIn 1817, Karl Drais built '
        'a wooden running machine with two wheels and a seat. In 1861, French makers added pedals to the front wheel. '
        'In 1885, John Kemp Starley sold the Rover, the first safe bicycle.\n\nToday there are about 1 billion bicycles '
        'in the world. In the Netherlands, about 27% of trips are made by bicycle.'))
    reference = copy.deepcopy(board)
    LLMDirector(Recorded({}), 'en').rules.direct(reference)
    bakery, dates, grid = (next(b for b in reference['beats'] if b['kind'] == 'narration' and word in b['display']['en'])
                           for word in ('dawn', '1817', '27%'))
    assert len(bakery['visuals']) > 1 and 'lanes' in [v['type'] for v in dates['visuals']] and \
        'grid100' in [v['type'] for v in grid['visuals']]

    def answer(payload):
        beats = []
        for b in payload['beats']:
            if 'dawn' in b['text']:
                beats.append({'beat_id': b['beat_id'], 'visuals': [{'type': 'timeline', 'title': 'A baker\'s day', 'events': [
                    {'when': when, 'label': label, 'trigger': when}
                    for when, label in (('At dawn', 'Oven on'), ('At noon', 'Bread sold'), ('At dusk', 'Shop shut'))]}]})
            elif b['kind'] == 'narration':
                beats.append({'beat_id': b['beat_id'], 'visuals': [{'type': 'cluster', 'relation': 'none', 'items': [
                    {'doodle': b['candidates'][0]['id'], 'label': '', 'trigger': ''}]}]})
        return {'section_title': '', 'hook': '', 'takeaway': '', 'beats': beats}
    titles = [c['title']['en'] for c in board['chapters'] if c['kind'] == 'section']
    LLMDirector(Recorded(dict.fromkeys(titles, answer)), 'en').direct(board)
    beats = {b['id']: b for b in board['beats']}
    assert [(v['type'], v['id']) for v in beats[bakery['id']]['visuals']] == [('lanes', f"{bakery['id']}m0")]
    assert beats[dates['id']]['visuals'] == dates['visuals'] and beats[grid['id']]['visuals'] == grid['visuals']
    assert validate(board)['ok']

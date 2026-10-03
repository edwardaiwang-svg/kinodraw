"""Rules annotator and energy planner: a role, scene, emphasis and energy for every sentence, no LLM needed."""
import copy
from pathlib import Path

import pytest

from kinodraw import ingest, numbers, script
from kinodraw.director.annotate import ENERGY_TREATMENT, ROLES, SCENES, _words, annotate, plan, sentences_of
from kinodraw.director.validate import validate
from kinodraw.engine import timeline as tl
from kinodraw.engine.storyboard import DIALS, normalize

FIX = Path(__file__).parent / 'fixtures'
DIRECTED = ('title', 'opener', 'narration', 'take', 'closing')
CAPS = {'calm': (0., 0), 'lively': (.20, 2), 'showreel': (.45, 5)}      # share of the runtime at 2+, showpieces
CASCADE = {'feature', 'mechanic', 'step', 'use_cases', 'list', 'channels'}


def _board(name, **dials):
    board = script.build(ingest.read(FIX / name))
    board.update(dials)
    return board


def _said(board, kinds=('narration',)):
    """[(sentence, entry)] in video order."""
    lang = board['lang']
    return [(b['display'][lang][e['span'][0]:e['span'][1]], e) for b in board['beats'] if b['kind'] in kinds
            for e in b.get('direction', [])]


@pytest.fixture(scope='module')
def promo():
    board = _board('promo_friendr.md', look='collage', story='promo')
    return board, annotate(board)


@pytest.fixture(scope='module')
def story():
    board = _board('story_purpose.md', look='collage', story='story')
    return board, annotate(board)


# ------------------------------------------------------------------- roles
def test_promo_roles(promo):
    board, report = promo
    assert [(s, e['role']) for s, e in _said(board)] == [
        ('You want to do something fun with your friends, so you send a message.', 'problem'),
        ('And another one.', 'problem'), ('And another one.', 'problem'),
        ("40 messages later, who's actually coming?", 'hook'),
        ("There's a much easier way.", 'turn'),
        ('With Friendr.', 'brand'),
        ('Create an event in 20 seconds.', 'step'), ('Share one link.', 'step'),
        ('In the group chat, on Signal, or by email.', 'channels'),
        ('And your friends sign up with a single tap.', 'social'),
        ('No app.', 'feature'), ('No account.', 'feature'),
        ('Set a minimum.', 'mechanic'), ('Not enough interest?', 'mechanic'),
        ("Then it's automatically called off.", 'mechanic'), ('Enough people?', 'mechanic'),
        ('Green light for everyone.', 'mechanic'),
        ('Drinks, movie night, werewolves or padel.', 'use_cases'),
        ("Everything that's better together.", 'tagline'),
        ('Friendr.', 'tagline'), ('Create an event.', 'tagline'), ('Share one link.', 'tagline'), ('Done.', 'tagline'),
        ('Try it for free at friendr.nl', 'cta')]
    assert report['brand'] == {'name': 'Friendr', 'url': 'friendr.nl'}
    by = {(s, e['role']): e for s, e in _said(board)}
    assert [e['n'] for e in by.values() if e['role'] == 'step'] == [1, 2]                  # numbered as said
    assert by['Create an event in 20 seconds.', 'step']['emphasis'] == '20 seconds'       # the number note
    assert by['Drinks, movie night, werewolves or padel.', 'use_cases']['options']['emphasis'] == \
        ['Drinks', 'movie night', 'werewolves', 'padel']
    assert by['In the group chat, on Signal, or by email.', 'channels']['options']['emphasis'][:3] == \
        ['group chat', 'Signal', 'email']
    assert by['Try it for free at friendr.nl', 'cta']['emphasis'] == 'friendr.nl'
    scenes = {role: e['scene'] for (_, role), e in reversed(list(by.items()))}
    assert scenes == {'problem': 'chat_pileup', 'hook': 'chaos', 'turn': 'brand_reveal', 'brand': 'brand_reveal',
                      'step': 'step_card', 'channels': 'share_link', 'social': 'rsvp', 'feature': 'feature_chips',
                      'mechanic': 'threshold', 'use_cases': 'use_case_grid', 'tagline': 'sticker_row',
                      'cta': 'brand_endcard'}
    assert by['Share one link.', 'step']['scene'] == 'share_link'                        # its words pick the card
    assert [e['scene'] for s, e in _said(board)][-5:] == ['brand_endcard'] * 5            # "Friendr. ... friendr.nl"


def test_story_roles(story):
    board, _ = story
    said = _said(board)
    assert [(s, e['role']) for s, e in said] == [
        ('What is the purpose of life?', 'hook'),
        ('People have been asking that for, well, forever.', 'none'),
        ('Philosophers wrote enormous books about it.', 'none'),
        ('The stars kept mysteriously quiet, and the cat said, nap.', 'quote'),
        ('So we went looking up mountains, under the sea, deep into the fine print, and along the way, without '
         'really noticing, we picked up little bits and pieces.', 'none'),
        ("A laugh with a friend, soup on a cold day, a dog who's thrilled you're home, a kindness for a stranger.",
         'list'),
        ("Turns out, life doesn't come with a purpose.", 'reveal'),
        ('It comes with scissors and glue.', 'tagline'),
        ('So cut out the good bits, stick them together, and make it mean something.', 'end_line')]
    assert [e['scene'] for _, e in said] == ['title_question', 'crowd', 'stack', 'sky_speech', 'journey', 'moodboard',
                                             'box_reveal', 'tools_idea', 'end_line']
    assert [e['emphasis'] for _, e in said] == ['purpose of life', 'forever', 'enormous books', 'nap',
                                                'bits and pieces', 'A laugh', 'a purpose', 'scissors and glue',
                                                'mean something']
    assert said[5][1]['options']['emphasis'] == ['A laugh', 'soup', 'a dog', 'a kindness']      # the four moments


def test_structural_beats_and_whiteboard(promo):
    board, _ = promo
    assert all(('direction' in b) == (b['kind'] in DIRECTED) for b in board['beats'])    # agenda beats get none
    closing = next(e for s, e in _said(board, ('closing',)))
    assert closing['role'] == 'none' and closing['energy'] == 0 and closing['scene'] == 'brand_endcard'
    plain = _board('promo_friendr.md', story='promo')                                   # whiteboard: one scene
    annotate(plain)
    assert {tuple(e['options']['scene']) for _, e in _said(plain, DIRECTED)} == {('board',)}


def test_no_brand_in_a_history_and_the_board_brand_wins():
    report = annotate(_board('printing_press.md'))
    assert report['brand'] is None                                   # "Bible" is said twice but is not a brand
    board = _board('promo_friendr.md', story='promo', brand={'name': 'Friendr', 'url': 'https://friendr.nl'})
    assert annotate(board)['brand'] == {'name': 'Friendr', 'url': 'https://friendr.nl'}


def test_chinese_questions_numbers_lists_and_quotes():
    board = _board('sleep_zh.md', look='collage', story='story')
    annotate(board)
    roles = {s: e['role'] for s, e in _said(board, DIRECTED)}
    assert roles['今天的主题：为什么我们需要睡觉？'] == 'hook'
    assert roles['可是调查显示，超过30%的成年人经常睡不够。'] == 'number'
    assert roles['想要睡得好，可以试试这几个方法：每天固定时间起床，睡前一小时少看手机，下午以后少喝咖啡。'] == 'list'
    assert roles['今晚早点睡，就是对明天的自己最好的投资。'] == 'end_line'
    emphasis = {s: e['emphasis'] for s, e in _said(board)}
    assert emphasis['一般来说，成年人每晚需要7到9个小时的睡眠，青少年需要8到10个小时。'] == '7到9个小时'
    quoted = script.build(ingest.read('# 读书\n\n老师常说：“知识就是力量。”所以我们每天读书。后来我们都明白了。'))
    annotate(quoted)
    assert [e['role'] for _, e in _said(quoted)][0] == 'quote' and _said(quoted)[0][1]['emphasis'] == '知识就是力量'


# -------------------------------------------------------------- invariants
CASES = [('promo_friendr.md', 'collage', 'promo'), ('story_purpose.md', 'collage', 'story'),
         ('printing_press.md', 'bold', 'explain'), ('bicycle.md', 'collage', 'explain'),
         ('photosynthesis.txt', 'whiteboard', 'explain'), ('sleep_zh.md', 'bold', 'showcase'),
         ('water_cycle.md', 'collage', 'showcase'), ('sky_blue.md', 'whiteboard', 'story'), ('tiny.md', 'bold', 'promo')]


@pytest.mark.parametrize('name, look, story', CASES)
def test_every_sentence_is_directed_within_its_options(name, look, story):
    board = _board(name, look=look, story=story)
    annotate(board)
    lang = board['lang']
    for b in board['beats']:
        if b['kind'] not in DIRECTED:
            assert 'direction' not in b
            continue
        text, spans = b['display'][lang], sentences_of(b, lang)
        assert [e['i'] for e in b['direction']] == [i for i, _, _ in spans] == \
            list(range(len(script.sentences(text, lang))))
        for e, (i, start, end) in zip(b['direction'], spans):
            sentence = text[start:end]
            assert e['span'] == [start, end] and sentence == script.sentences(text, lang)[i]   # spans slice exactly
            assert e['role'] in ROLES and 0 <= e['energy'] <= 3 and e['source'] == 'rules'
            scenes, phrases = e['options']['scene'], e['options']['emphasis']
            assert e['scene'] == scenes[0] and set(scenes) <= set(SCENES[look][story])       # the rules pick first
            assert (1 if look == 'whiteboard' else 2) <= len(scenes) <= 3 and len(set(scenes)) == len(scenes)
            assert len(phrases) <= 4 and all(p in sentence and 1 <= _words(p, lang) <= 3 for p in phrases), phrases
            assert e['emphasis'] == (phrases[0] if phrases else '') and e['emphasis'] in sentence
            assert e['options']['energy'] == [max(0, e['energy'] - 1), e['energy']]
    report = validate(board)
    assert report['ok'], report['errors']


def test_sentences_slice_back_exactly():
    beat = {'display': {'en': 'Dr. Smith met Mr. Jones at 5 p.m. today. "Why?" he asked. They left!  '}}
    spans = sentences_of(beat, 'en')
    assert [beat['display']['en'][a:b] for _, a, b in spans] == script.sentences(beat['display']['en'], 'en')
    assert [i for i, _, _ in spans] == list(range(len(spans)))


def test_constants_cover_every_dial():
    assert set(SCENES) == set(DIALS['look']) and all(set(SCENES[look]) == set(DIALS['story']) for look in SCENES)
    assert SCENES['whiteboard']['promo'] == ['board'] and set(ENERGY_TREATMENT) == {0, 1, 2, 3}
    assert ROLES['hook'] == 2 and ROLES['brand'] == ROLES['cta'] == 3 and ROLES['none'] == 0


# ----------------------------------------------------------------- planner
def _clock(board, timeline=None):
    """[(entry, t0, t1)] on the master clock: the timeline's, else 15 characters a second (Chinese 4.4)."""
    lang, out, clock = board['lang'], [], 0.
    for b in board['beats']:
        norm = numbers.normalize(b['display'][lang], lang)
        info = (timeline or {}).get('beats', {}).get(b['id'])
        rate = 15. if lang == 'en' else 4.4
        if info:
            at = [info['start'] + t for t in info['char_times']]
            end = info['speech_end']
        else:
            at, end = [clock + k / rate for k in range(len(norm.spoken))], clock + len(norm.spoken) / rate
            clock = end
        for e in b.get('direction', []):
            s0, s1 = norm.to_spoken(e['span'][0]), norm.to_spoken(e['span'][1])
            out.append((e, at[min(s0, len(at) - 1)], end if s1 >= len(norm.spoken) else at[s1]))
    return out


def _check_budget(board, report, motion, timeline=None):
    timed = _clock(board, timeline)
    share, most = CAPS[motion]
    runtime = sum(t1 - t0 for _, t0, t1 in timed)
    high = sum(t1 - t0 for e, t0, t1 in timed if e['energy'] >= 2) / runtime
    shows = [t0 for e, t0, _ in timed if e['energy'] == 3]
    assert high <= share + 1e-6 and abs(high - report['e2_share']) < 1e-3, (high, report)
    assert len(shows) == report['showpieces'] <= most
    assert all(b - a >= 12 for a, b in zip(shows, shows[1:])), shows                   # showpieces 12 s apart
    assert report['histogram'] == {k: sum(e['energy'] == k for e, _, _ in timed) for k in range(4)}
    if motion == 'calm':
        assert all(e['energy'] <= 1 for e, _, _ in timed)
    for n, (a, _, a1) in enumerate(timed):
        if a['energy'] < 2:
            continue
        assert 0 < _words(a['emphasis'], board['lang']) <= 4                           # a big move needs a key phrase
        for m in range(n + 1, len(timed)):
            b, b0, _ = timed[m]
            if b0 >= a1 + 3:
                break
            run = [timed[k][0]['role'] for k in range(n, m + 1)]
            assert b['energy'] <= 1 or (a['role'] in CASCADE and set(run) == {a['role']}), (a, b)   # rest after a hit


@pytest.mark.parametrize('motion', ['calm', 'lively', 'showreel'])
@pytest.mark.parametrize('name, look, story', CASES[:4] + [CASES[5]])
def test_plan_keeps_the_motion_budget(name, look, story, motion):
    board = _board(name, look=look, story=story, motion=motion)
    report = annotate(board)['plan']
    _check_budget(board, report, motion)
    if name == 'promo_friendr.md' and motion != 'calm':                  # the brand reveal and the cta are the hits
        assert [s for s, e in _said(board) if e['energy'] == 3] == ['With Friendr.', 'Try it for free at friendr.nl']


def test_plan_uses_the_timeline_and_runs_again():
    board = _board('promo_friendr.md', look='bold', story='promo', motion='lively')
    annotate(board)
    timing = tl.layout(board, 'en', tl.synthetic_clips(board, 'en'))
    report = plan(board, timing)
    _check_budget(board, report, 'lively', timing)
    again = copy.deepcopy(board)
    assert plan(again, timing) == report and again == board                           # from the baselines each time
    board['motion'] = 'showreel'
    _check_budget(board, plan(board, timing), 'showreel', timing)


def test_user_entries_are_kept_and_only_reported():
    board = _board('promo_friendr.md', look='collage', story='promo', motion='calm')
    annotate(board)
    beat = next(b for b in board['beats'] if 'With Friendr.' in b['display']['en'])
    mine = {**copy.deepcopy(beat['direction'][1]), 'energy': 3, 'scene': 'chaos', 'emphasis': 'With Friendr',
            'options': {'scene': ['chaos', 'brand_reveal'], 'emphasis': ['With Friendr'], 'energy': [3, 3]},
            'source': 'user'}
    beat['direction'][1] = copy.deepcopy(mine)
    report = annotate(board)
    assert beat['direction'][1] == mine and report['user'] == 1              # untouched by annotate and plan
    assert any(n.startswith(f"{beat['id']}#1: user energy 3 breaks calm") for n in report['plan']['notes'])
    assert all(e['energy'] <= 1 for _, e in _said(board, DIRECTED) if e['source'] == 'rules')
    assert validate(board)['ok']
    board['motion'] = 'lively'                                               # a user's hit makes the rules rest
    turn = beat['direction'][0]
    beat['direction'][0] = {**turn, 'energy': 2, 'source': 'user'}
    plan(board)
    assert beat['direction'][1]['energy'] == 3 and beat['direction'][0]['energy'] == 2
    hook = next(e for s, e in _said(board) if e['role'] == 'hook')
    assert hook['energy'] <= 1                                               # nothing hits 3 s before the turn
    stale = {'i': 99, 'span': [0, 4], 'role': 'none', 'energy': 0, 'scene': 'chaos', 'emphasis': '', 'source': 'user'}
    beat['direction'].append(stale)
    annotate(board)
    assert beat['direction'][-1] is stale and beat['direction'][1] == mine  # kept even when it no longer fits


def test_annotation_is_deterministic():
    one = _board('promo_friendr.md', look='bold', story='showcase', motion='showreel')
    two = copy.deepcopy(one)
    assert annotate(one) == annotate(two) and one == two
    first = copy.deepcopy(one)
    annotate(one)                                                            # annotating again changes nothing
    assert one == first


# -------------------------------------------------------------- validation
def test_validator_checks_dials_and_directions(promo):
    board = copy.deepcopy(promo[0])
    assert validate(board)['ok']
    beat = next(b for b in board['beats'] if b['kind'] == 'narration')
    for key, bad, message in [('scene', 'fireworks', 'is not one of its options'), ('energy', 4, 'energy must be 0-3'),
                              ('emphasis', 'words nobody says', 'is not in the sentence'),
                              ('span', [0, 10 ** 4], 'is not inside the display text'), ('role', 'villain', 'role')]:
        broken = copy.deepcopy(board)
        next(b for b in broken['beats'] if b['id'] == beat['id'])['direction'][0][key] = bad
        errors = validate(broken)['errors']
        assert any(message in e for e in errors), (key, errors)
    for key, bad in [('look', 'neon'), ('story', 'saga'), ('motion', 'frantic'), ('brand', 'Friendr')]:
        assert not validate({**board, key: bad})['ok'], key
    moved = {**copy.deepcopy(board), 'look': 'bold'}                          # an old plan in another look
    report = validate(moved)
    assert report['ok'] and any("not in this look's library" in w for w in report['warnings'])


def test_normalize_fills_the_dials_and_nothing_else():
    for name in ('printing_press.md', 'sleep_zh.md', 'promo_friendr.md'):
        board = script.build(ingest.read(FIX / name))
        filled = normalize(board)
        assert set(filled) - set(board) == {'look', 'story', 'motion'}
        assert (filled['look'], filled['story'], filled['motion']) == ('whiteboard', 'explain', 'lively')
        assert {k: v for k, v in filled.items() if k not in DIALS} == {**board, 'chapters': filled['chapters']}
    assert normalize({**board, 'look': 'collage', 'motion': 'calm'})['look'] == 'collage'


def test_a_software_promo_shows_the_page_the_window_and_the_hand():
    board = _board('promo_kinodraw.md', look='collage', story='promo')
    annotate(board)
    said = {s: (e['role'], e['scene']) for s, e in _said(board)}
    assert said['You wrote something worth explaining.'] == ('hook', 'script_page')
    assert said['Paste your script.'] == ('step', 'app_paste')
    assert said['Press Make video.'] == ('step', 'app_press')
    assert said['A hand draws every idea while the voice reads it.'][1] == 'hand_draws'
    assert said['It all runs on your own computer.'][1] == 'feature_chips'         # goes on from "No account."
    assert said['Anything you can say, it can draw.'][0] == 'tagline'               # sums up the uses before it
    assert said['Paste a script.'][1] == 'brand_endcard'                            # the end card keeps its lines

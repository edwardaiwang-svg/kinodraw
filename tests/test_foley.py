"""Everyday sound effects: the words and actions that cue them, where they land, and how loud they are."""
import numpy as np
import pytest
from scipy.signal import sosfilt

from kinodraw.audio import foley, master, mix, sfx, synth_sfx

SR = mix.SR


def _tl(*lines, lang='en', start=0.):
    """A timeline whose captions say each line, one word every 0.4 s, a 1 s pause between lines."""
    captions, beats, t = [], {}, start
    for i, line in enumerate(lines):
        words = [round(t + .4 * k, 3) for k in range(len(line.split()) if lang != 'zh' else len(line))]
        end = words[-1] + .4
        captions.append({'start': t, 'end': end, 'text': line, 'words': words})
        beats[f'b{i + 1:03}'] = {'start': t, 'speech_end': end, 'end': end + 1}
        t = end + 1
    return {'language': lang, 'duration': t + 5, 'captions': captions, 'beats': beats,
            'beat_order': list(beats)}


def _at(line, word):
    return round(.4 * [w.strip('.,!?') for w in line.split()].index(word), 3)


@pytest.mark.parametrize('line,word,kind', [
    ('Thunder rolled over the hills.', 'Thunder', 'thunder'),
    ('Then the rain came down hard.', 'rain', 'rain'),
    ('A cold wind blew through town.', 'wind', 'wind'),
    ('She opened the door slowly.', 'door', 'door'),
    ('Someone knocked twice and waited.', 'knocked', 'knock'),
    ('He walked to the window.', 'walked', 'footsteps'),
    ('Her phone lit up on the table.', 'phone', 'phone_buzz'),
    ('A new message arrived at noon.', 'new', 'notification'),
    ('She typed her answer fast.', 'typed', 'typing'),
    ('He unfolded the old map.', 'unfolded', 'paper'),
    ('It was in the top drawer.', 'drawer', 'drawer'),
    ('Rolls are just $3.50 each.', '$3.50', 'cash_register'),
    ('The shop bell rang once.', 'bell', 'bell'),
    ('Onions sizzled in the pan.', 'sizzled', 'sizzle'),
    ('He poured the coffee slowly.', 'poured', 'pour'),
    ('Whisk the eggs until smooth.', 'Whisk', 'whisk'),
    ('The fans cheered for the team.', 'cheered', 'cheer'),
    ('Everyone applauded at the end.', 'applauded', 'applause'),
    ('The crowd waited outside.', 'crowd', 'murmur'),
    ('We caught the bus home.', 'bus', 'bus'),
    ('A car turned the corner.', 'car', 'car'),
    ('Grandpa laughed at the joke.', 'laughed', 'laugh'),
    ('The clock on the wall said nine.', 'clock', 'clock_tick'),
])
def test_a_word_that_names_a_sound_cues_it_on_that_word(line, word, kind):
    cues = foley.cues(_tl(line))
    assert [(c['kind'], c['t']) for c in cues] == [(kind, _at(line, word))]
    assert kind in synth_sfx.KINDS or kind in sfx.LEVEL               # a sound the bus can play


@pytest.mark.parametrize('line', [
    'Let me walk you through the steps.',             # a figure of speech, not footsteps
    'This type of cloud is common.',                  # not typing
    'Please pay attention to the numbers.',           # not a till
    'Scientists call it a stepped leader.',           # an adjective, not a step
    'She had a flash of insight.',                    # no storm in this video
    'The message of the story is simple.',            # not a phone message
    'Revenue grew in every market.',
])
def test_figures_of_speech_and_other_senses_stay_quiet(line):
    assert foley.cues(_tl(line)) == []


def test_in_a_storm_a_flash_or_a_strike_is_lightning():
    tl = _tl('A thunderstorm builds over the plain.', 'Then a bright flash lights the sky.')
    flash = tl['captions'][1]['words'][3]
    assert {'t': flash, 'kind': 'lightning_crack', 'id': 'foley.word.1.14'} in foley.cues(tl)


def test_an_emoji_does_not_shift_the_words():
    tl = _tl('Fresh rolls today. Just $3.50 each.')
    cap = tl['captions'][0]
    cap['text'] = '🔥 ' + cap['text']                     # shown, not spoken: no word time of its own
    assert [(c['kind'], c['t']) for c in foley.cues(tl)] == [('cash_register', cap['words'][4])]


def test_effects_keep_their_distance_and_do_not_crowd_a_line():
    tl = _tl('The phone rang, the door slammed and the dog laughed.', 'The phone rang again.')
    first = [c['kind'] for c in foley.cues(tl) if c['id'].startswith('foley.word.0.')]
    assert first == ['phone_buzz', 'door']                          # two per line at most, in time order
    late = _tl(*['The phone buzzed.'] * 6)                          # one every 2.6 s: a phone every 3 s at most
    times = [c['t'] for c in foley.cues(late)]
    assert len(times) == 3 and min(np.diff(times)) >= foley.DEFAULT_COOLDOWN


def test_an_effect_the_renderer_already_plays_is_not_doubled():
    tl = _tl('Rain fell on the roof.')
    assert foley.cues(tl, existing=[{'t': .5, 'kind': 'rain', 'dur': 3}]) == []
    assert foley.cues(tl, existing=[{'t': 9, 'kind': 'rain', 'dur': 3}]) != []


def test_plan_actions_add_footsteps_and_a_human_laugh_on_the_actors_name():
    tl = _tl('Mara crossed the square.', 'Then Mara and Rufus grinned.')
    plan = {'cast': [{'id': 'mara', 'name': 'Mara', 'kind': 'human'}, {'id': 'rufus', 'name': 'Rufus', 'kind': 'quadruped'}],
            'scenes': [{'actions': [{'actor': 'mara', 'verb': 'walk', 'at_beat': 'b001'}]},
                       {'actions': [{'actor': 'mara', 'verb': 'laugh', 'at_beat': 'b002'},
                                    {'actor': 'rufus', 'verb': 'laugh', 'at_beat': 'b002'}]}]}
    cues = foley.cues(tl, plan)
    mara = tl['captions'][1]['words'][1]
    assert [(c['kind'], c['t']) for c in cues] == [('footsteps', 0.), ('laugh', mara)]   # the dog's laugh is the renderer's


def test_an_animal_cast_laughs_its_own_way():
    tl = _tl('The hyenas laughed at the lion.')
    plan = {'cast': [{'id': 'h', 'name': 'Hyena', 'kind': 'quadruped'}], 'scenes': []}
    assert foley.cues(tl, plan) == []
    assert [c['kind'] for c in foley.cues(tl)] == ['laugh']                     # no cast: people


def test_chinese_words_cue_their_sounds_on_the_character():
    tl = _tl('外面下雨了', lang='zh')
    assert [(c['kind'], c['t']) for c in foley.cues(tl)] == [('rain', tl['captions'][0]['words'][2])]


def test_a_bed_never_runs_past_the_video():
    tl = _tl('Rain.')
    tl['duration'] = 2.
    assert foley.cues(tl)[0]['dur'] == 2.


# ------------------------------------------------------------------ the sounds
def _speech(seconds, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    words = (np.sin(2 * np.pi * 4 * t) > .2) * (np.sin(2 * np.pi * .3 * t) > -.5)
    voice = np.sin(2 * np.pi * 180 * t) + .5 * np.sin(2 * np.pi * 360 * t) + .2 * rng.standard_normal(len(t))
    return (.2 * voice * words).astype(np.float32)


def _momentary(x):
    y = sosfilt(master.kweighting(SR), x.reshape(len(x), -1).astype(np.float64), axis=0)
    p = (y[:len(y) // (SR // 10) * (SR // 10)].reshape(-1, SR // 10, y.shape[1]) ** 2).sum((1, 2)) / (SR // 10)
    return -.691 + 10 * np.log10(((p[:-3] + p[1:-2] + p[2:-1] + p[3:]) / 4).max())


@pytest.mark.parametrize('kind', sorted(synth_sfx.FOLEY))
def test_each_everyday_sound_sits_12_to_18_lu_under_the_narration(kind):
    """Dropped into a -18 LUFS narration and ducked as the mix ducks effects, the loudest 400 ms of each everyday
    sound (median of 13 drops) is 12-18 LU under the narration's: heard, but subtle."""
    speech = _speech(24)
    speech *= 10 ** ((-18 - master.loudness(speech, SR)) / 20)
    duck = (1 + (10 ** (mix.SFX_DUCK_DB / 20) - 1) * mix.envelope(speech))[:, None]
    under = []
    for n, t in enumerate(np.arange(1, 18, 1.37)):
        w = slice(round(t * SR) - SR // 10, round(t * SR) + round(3.2 * SR))
        fx = sfx.render([{'t': t, 'kind': kind, 'id': f'{kind}.{n}'}], 24) * duck
        under.append(_momentary(speech[w]) - _momentary(fx[w]))
    assert 12 <= np.median(under) <= 18, (kind, np.median(under))


@pytest.mark.parametrize('kind', sorted(synth_sfx.FOLEY))
def test_each_everyday_sound_starts_on_its_cue(kind):
    y = np.abs(sfx.render([{'t': 1.0, 'kind': kind, 'id': f'{kind}.0'}], 5)).max(1)
    heard = np.flatnonzero(y > 1e-4)
    if kind in sfx.FROM_T:                                         # from t, fading in over 40 ms
        assert len(heard) and 0 <= heard[0] - SR <= .04 * SR
    else:                                                          # its transient on t
        assert len(heard) and 0 <= SR - heard[0] <= sfx.ATTACK * SR + SR // 1000
    if kind in sfx.FROM_T:
        assert heard[-1] <= SR + synth_sfx.KINDS[kind] * 2 ** (3 / 12) * SR    # its length, repitched at most +-3


def _pitch(x):
    """Median fundamental (Hz) of the voiced 40 ms frames, by autocorrelation between 80 and 1000 Hz."""
    n, f0 = int(.04 * SR), []
    for i in range(0, len(x) - n, n):
        frame = x[i:i + n] - x[i:i + n].mean()
        if np.sqrt((frame ** 2).mean()) < .2 * np.sqrt((x ** 2).mean()):
            continue
        ac = np.correlate(frame, frame, 'full')[n - 1:]
        lo, hi = SR // 1000, SR // 80
        f0.append(SR / (lo + int(np.argmax(ac[lo:hi]))))
    return float(np.median(f0))


def test_a_person_laughs_in_a_human_voice_not_a_cackle():
    laugh = [_pitch(synth_sfx.render('laugh', seed=s)) for s in range(5)]
    cackle = [_pitch(synth_sfx.render('hyena_cackle', seed=s)) for s in range(5)]
    assert max(laugh) < 300 < min(cackle)                          # a speaking voice's range, below the yelp
    x = synth_sfx.render('laugh')
    env = np.sqrt(np.convolve(x ** 2, np.ones(SR // 25) / (SR // 25), 'same'))     # 40 ms
    bursts = np.flatnonzero(np.diff((env > .4 * env.max()).astype(int)) == 1)
    assert 3 <= len(bursts) <= 6                                   # a few 'ha's

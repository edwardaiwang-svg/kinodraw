"""Word rules of the stick look: which pose, face and costume a shot's words give, in English and Chinese."""
import pytest

from kinodraw.engine.stick import cues


@pytest.mark.parametrize('text,lang', [
    ("Rome didn't fall in a day.", 'en'),
    ("He wasn't killed.", 'en'),
    ('He couldn’t escape.', 'en'),
    ('Nobody was murdered that night.', 'en'),
    ('The best way to remember is simple.', 'en'),
    ('也就是说，天空是蓝的', 'zh'),
    ('其实这可能是一个误会', 'zh'),
    ('这个问题很难', 'zh'),
])
def test_negated_or_idiomatic_words_strike_no_pose(text, lang):
    assert cues.pose_for(text, lang)[0] is None


@pytest.mark.parametrize('text', ['没有人被杀。', '没有人死。', '他不会死在那里。', '从来没有被击败。', '笑死我了。',
                                  '那天晚上墙没有倒下，也没有人被杀。'])
def test_a_chinese_negation_anywhere_in_the_clause_means_nobody_falls(text):
    assert cues.pose_for(text, 'zh')[0] != 'fall'


@pytest.mark.parametrize('text', ['不久之后罗马灭亡了', '他不幸死了', '没想到他死了', '他不愿投降，最后战死了'])
def test_words_that_only_look_negative_still_fall(text):
    assert cues.pose_for(text, 'zh')[0] == 'fall'


def test_taking_something_away_is_not_walking():
    assert cues.pose_for('他拿走了钱', 'zh')[0] != 'walk'


@pytest.mark.parametrize('text,lang,pose', [
    ('Rome fell.', 'en', 'fall'),
    ('He walked home.', 'en', 'walk'),
    ('They won the war at last.', 'en', 'cheer'),
    ('他走向城门', 'zh', 'walk'),
    ('他问老师', 'zh', 'talk'),
    ('罗马灭亡了', 'zh', 'fall'),
])
def test_plain_cues_still_work(text, lang, pose):
    assert cues.pose_for(text, lang)[0] == pose


def test_soldiers_wear_the_helmet_of_their_era():
    modern = ['On November 24, 1971, a man hijacked a plane.', 'The FBI searched the woods with hundreds of soldiers.']
    ancient = ['Rome was the largest empire of the ancient world.', 'Roman legions guarded the border.']
    assert cues.era(modern, 'en') == 'modern' and cues.era(ancient, 'en') == 'ancient'
    assert cues.costume('Hundreds of soldiers and agents searched the woods.', 'en', 'modern') == 'combat'
    assert cues.costume('Gothic warriors crushed an army at Adrianople.', 'en', 'ancient') == 'helmet'
    assert cues.costume('A Roman legion marched north.', 'en', 'modern') == 'helmet'   # a Roman is always Roman
    assert cues.costume('In general, people sleep less now.', 'en') is None
    assert cues.costume('士兵们搜索了树林', 'zh', 'modern') == 'combat'

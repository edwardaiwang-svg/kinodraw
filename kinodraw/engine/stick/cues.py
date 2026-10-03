"""Word rules for the stick look (English and Chinese): which pose a shot's figure strikes, its face, whether a
crowd appears, what it wears, the video's ground colour, and which words earn a red mark. First match wins;
everything is a fixed list, so the same script always gets the same picture."""
from __future__ import annotations

import re

from . import palette

I = re.I
POSE = {
    'en': [
        ('fall', r'\b(fell|falls?|falling|collaps\w*|died|dies|death|killed|murdered|perished|destroyed|toppled|'
                 r'overthrown|crashed|wiped out)\b'),
        ('angry', r'\b(wars?|battles?|fights?|fought|attack\w*|invad\w*|rebel\w*|revolt\w*|ang(?:er|ry)|furious|'
                  r'enem(?:y|ies)|crushed|sacked|raid\w*|conquer\w*)\b'),
        ('run', r'\b(ran|run|runs|running|fled|flee\w*|escap\w*|chas\w*|rushed|raced|hurr\w*)\b'),
        ('walk', r'\b(walk\w*|travel\w*|journey\w*|march\w*|migrat\w*|moved|crossed|reach\w*|arriv\w*|went|'
                 r'spread|explor\w*|sail\w*)\b'),
        ('cheer', r'\b(won|wins?|victor\w*|triumph\w*|success\w*|celebrat\w*|thriv\w*|golden age|survived)\b'),
        ('sad', r'\b(lost|lose|loss|poor|poverty|famine|plagues?|diseases?|sick\w*|sad|grief|starv\w*|suffer\w*|'
                r'declin\w*|expensive|fewer)\b'),
        ('shrug', r'\b(maybe|perhaps|nobody knows|no one knows|unclear|unknown|myster\w*|no single|not sure|'
                  r'debat\w*|still argue)\b'),
        ('talk', r'\b(said|says|told|tell|called|announc\w*|declar\w*|argu\w*|explain\w*|asked|named|claimed|'
                 r'listed|wrote)\b'),
        ('hold', r'\b(held|hold\w*|carr(?:y|ied|ies)|owned|bought|sold|paid|coins?|money|gold|silver)\b'),
        ('point', r'\b(look\w*|see|seen|notice\w*|watch\w*|here|map)\b'),
    ],
    'zh': [
        ('fall', r'倒下|崩溃|灭亡|死|杀|击败|摧毁|覆灭|垮台|跌倒|摔倒'),
        ('angry', r'战争|战斗|攻击|入侵|愤怒|生气|敌人|反抗|起义'),
        ('run', r'跑|逃|追赶|冲向'),
        ('walk', r'(?<![拿带偷抢夺运搬卷吹赶冲飞抬取])走(?![私廊势红])|旅行|穿过|穿越|迁徙|前往|到达|传播|航行|探索'),
        ('cheer', r'胜利|成功|庆祝|赢|繁荣|幸存|活了下来'),
        ('sad', r'失去|贫穷|饥荒|瘟疫|疾病|悲伤|痛苦|衰落|减少|太贵'),
        ('shrug', r'也许|或许|不知道|谁也不知道|没人知道|未知|谜|没有答案|说不清|不确定'),
        ('talk', r'(?<!就是)(?<!比如)(?<!据)(?<!小)(?<!传)(?<!听)(?<!虽)(?<!再)说(?![明服])|告诉|叫做|宣布|称为|解释|'
                 r'问(?!题)'),
        ('hold', r'拿着|握着|手里|带着|买|卖|钱|金币|用一[块个把台]'),
        ('point', r'看|观察|抬头'),
    ],
}
POSE_RE = {lang: [(pose, re.compile(rx, I)) for pose, rx in rules] for lang, rules in POSE.items()}
QUESTION = re.compile(r'[?？][”’"」』）)]*\s*$')
CROWD = {'en': re.compile(r'\b(people|citizens|population|armies|army|soldiers|warriors|farmers|crowds?|tribes|'
                          r'everyone|everybody|millions of|thousands of|humans|families|workers|villagers)\b', I),
         'zh': re.compile(r'人们|人口|军队|士兵|百姓|民众|大家|人类|农民|战士|居民')}
SHOCK = {'en': re.compile(r'\b(shocking|disturbing|deadliest|worst|horrif\w*|terrible|murdered|killed|crushed|sacked|'
                          r'soared|enormous|huge|massive|incredible|millions|bombs?|explosives?|dynamite|guns?)\b', I),
         'zh': re.compile(r'竟然|惊人|可怕|恐怖|巨大|暴涨|几乎都|十六倍|16倍|死|杀|炸弹|枪')}
# Words that make a calm narrator look worried (crime, danger, death, fear, loss).
GRIM = {'en': re.compile(r'\b(bombs?|explosiv\w*|dynamite|guns?|weapons?|knife|knives|hijack\w*|kidnap\w*|ransom|'
                         r'threat\w*|danger\w*|crimes?|criminals?|murder\w*|kill\w*|dead|death|died|blood\w*|missing|'
                         r'vanish\w*|disappear\w*|unsolved|never (?:found|seen)|steal\w*|stole\w*|rob\w*|thie(?:f|ves)|'
                         r'fear\w*|afraid|scared|terrif\w*|panic\w*|insults?|bad news|negative|warning|alarm\w*|'
                         r'prison|jail|arrest\w*|suspects?|victims?)\b', I),
        'zh': re.compile(r'炸弹|枪|武器|劫持|劫机|绑架|赎金|威胁|危险|犯罪|罪犯|谋杀|杀|死|血|失踪|消失|悬案|偷|抢|害怕|恐惧|'
                         r'恐慌|侮辱|坏消息|负面|警告|警报|监狱|逮捕|嫌疑|受害')}
# A video that keeps talking about crime is told with a straight face throughout.
CRIME = {'en': re.compile(r'\b(hijack\w*|ransom|FBI|police|detectives?|murder\w*|killers?|crimes?|criminals?|suspects?|'
                          r'victims?|kidnap\w*|bombs?|robber\w*|heists?|stolen|investigat\w*|unsolved|prison|jail|'
                          r'arrest\w*|homicide|evidence)\b', I),
         'zh': re.compile(r'劫机|劫持|赎金|警察|侦探|谋杀|凶手|犯罪|罪犯|嫌疑|受害|绑架|炸弹|抢劫|盗窃|调查|悬案|监狱|逮捕|证据')}
STRONG = {'en': re.compile(r'\b(largest|biggest|first|only|last|most|greatest|oldest|longest|enormous|'
                           r'for good|itself)\b', I),
          'zh': re.compile(r'最|第一|唯一|整个')}
# 'soldier' is the crested Roman helmet in an ancient story and a plain green combat helmet in a modern one.
COSTUME = {'en': [('crown', r'\b(emperors?|kings?|queens?|pharaohs?|throne|rulers?|monarchs?|empress)\b'),
                  ('helmet', r'\b(romans?|legions?|legionar\w*|gladiators?|centurions?|spartans?|hoplites?)\b'),
                  ('soldier', r'\b(soldiers?|army|armies|troops|warriors?|(?<!in )general)\b'),
                  ('strawhat', r'\b(farmers?|peasants?|(?<!office )(?<!health )workers?|villagers?)\b')],
           'zh': [('crown', r'皇帝|国王|女王|王位|统治者'), ('helmet', r'罗马人|罗马军|军团|角斗士|斯巴达'),
                  ('soldier', r'士兵|军队|战士|将军|部队'), ('strawhat', r'农民|工人|村民')]}
COSTUME_RE = {lang: [(hat, re.compile(rx, I)) for hat, rx in rules] for lang, rules in COSTUME.items()}
# A story is ancient when it talks about antiquity more than it gives modern years or modern things.
ANCIENT = {'en': re.compile(r'\b(rome|romans?|ancient|antiquity|legions?|pharaohs?|egyptians?|spartans?|athens|'
                            r'athenians?|greeks?|gladiators?|centurions?|caesar|emperors?|BCE?)\b', I),
           'zh': re.compile(r'罗马|古代|古罗马|军团|角斗士|法老|埃及|斯巴达|雅典|希腊|凯撒|皇帝|公元前')}
MODERN = {'en': re.compile(r'\b(1[5-9]\d\d|20\d\d|guns?|rifles?|tanks?|planes?|airplanes?|jets?|airlines?|FBI|police|'
                           r'computers?|phones?|cars?|world war)\b', I),
          'zh': re.compile(r'1[5-9]\d\d|20\d\d|枪|坦克|飞机|警察|电脑|手机|汽车|世界大战')}
GROUND = [('history', re.compile(r'\b(roman?|empire|ancient|wars?|kings?|emperors?|medieval|histor\w*|centur\w*|'
                                 r'dynast\w*|castles?|pyramids?|pharaoh\w*|army|armies)\b|罗马|帝国|古代|战争|皇帝|'
                                 r'历史|朝代|王朝', I)),
          ('sky', re.compile(r'\b(sky|skies|sea|seas|ocean\w*|water|weather|rain|clouds?|space|stars?|planets?|'
                             r'sunsets?|light)\b|天空|海|水|天气|云|太空|星|日落|阳光|光', I)),
          ('nature', re.compile(r'\b(animals?|plants?|forests?|trees?|biolog\w*|species|dinosaurs?|insects?|'
                                r'nature|wildlife)\b|植物|动物|森林|树|生物|恐龙|昆虫|自然', I))]
NARRATOR_POSES = {'think': 'think', 'wave': 'wave', 'explain': 'talk', 'worried': 'sad', 'thumbs': 'cheer',
                  'magnifier': 'point', 'present': 'point', 'head': 'talk'}
MOOD = {'fall': 'sad', 'sad': 'sad', 'angry': 'upset', 'cheer': 'happy', 'run': 'scared'}


WEAK = ('talk', 'hold', 'point')
NEGATION = {'en': re.compile(r"(?:\b(?:not|never|no|nor|without|nobody|none|neither|no one)|n['’]t)"
                          r"(?:\s+(?:a\s+single\s+\w+|of\s+(?:them|us|the\s+\w+)|\w+))?"
                          r"(?:\s+(?:was|were|is|are|be|been|had|has|have|got|ever))*\s+$", I),
            'zh': re.compile(r'不|没|未|别|无人|从未|并非')}
# A Chinese negation can stand a few characters before its verb (没有人被杀, 他不会死), so it counts anywhere in the
# cue's clause; these words only look negative.
ZH_NOT_NEGATION = re.compile(r'不久|不少|不过|不断|不同|不仅|不但|不得不|不幸|差不多|没想到|不料|不知不觉|不禁')
ZH_CLAUSE_END = re.compile(r'[，。！？；：、,.!?;:]')
# Words that hold a cue but mean something else
# ("笑死我了" is laughing hard; "in the fall of 1989" is autumn; "prices fall" is a number going down).
FALSE_FRIENDS = {('zh', 'fall'): re.compile(r'笑死|气死|急死|累死|烦死|死心|死板|死机'),
                 ('en', 'fall'): re.compile(r'\b(?:this|last|next|every|early|late|in the)\s+fall\b(?!\s+of\s+[^\d\s])|'
                                            r'\bfall\s+of\s+\d|\b(?:prices?|rates?|costs?|sales|profits?|values?|shares|'
                                            r'stocks?|numbers|levels?|temperatures?|demand|supply|wages?|incomes?)\s+'
                                            r'(?:\w+\s+)?(?:fell|falls?|falling)\b', I)}


def negated(text: str, at: int, lang: str) -> bool:
    """Whether the cue at ``at`` is said negated ("did not fall", "没有人被杀")."""
    if lang != 'zh':
        return bool(NEGATION[lang].search(text[max(0, at - 40):at]))
    clause = ZH_CLAUSE_END.split(text[:at])[-1][-8:]
    return bool(NEGATION['zh'].search(ZH_NOT_NEGATION.sub('', clause)))


def pose_for(text: str, lang: str) -> tuple[str | None, int]:
    """(pose, position of the cue word) for a shot's words, or (None, -1). A question always thinks; otherwise the
    earliest action cue wins, then the earliest weak one (talk, hold, point); a negated cue ("did not fall") is
    skipped."""
    if QUESTION.search(text.strip()):
        return 'think', len(text)
    found = []
    for rank, (pose, rx) in enumerate(POSE_RE[lang]):
        false = FALSE_FRIENDS.get((lang, pose))
        skip = [f.span() for f in false.finditer(text)] if false else []
        for m in rx.finditer(text):
            if any(s0 <= m.start() < s1 for s0, s1 in skip):
                continue
            if not negated(text, m.start(), lang):
                found.append((pose in WEAK, m.start(), rank, pose))
                break
    if not found:
        return None, -1
    _, pos, _, pose = min(found)
    return pose, pos


def crowd(text: str, lang: str) -> bool:
    return bool(CROWD[lang].search(text))


def shock(text: str, lang: str) -> int:
    """Position of the first shock word, or -1."""
    m = SHOCK[lang].search(text)
    return m.start() if m else -1


def grim(text: str, lang: str) -> bool:
    return bool(GRIM[lang].search(text))


def tone(texts: list[str], lang: str) -> str:
    """'grim' for a video that talks about crime at least three times (true crime: no grinning narrator), else
    'bright'."""
    return 'grim' if len(CRIME[lang].findall(' '.join(texts))) >= 3 else 'bright'


def strong(text: str, lang: str) -> int:
    m = STRONG[lang].search(text)
    return m.start() if m else -1


def era(texts: list[str], lang: str) -> str:
    """'ancient' or 'modern' for the whole video, from all of its words."""
    blob = ' '.join(texts)
    old, new = len(ANCIENT[lang].findall(blob)), len(MODERN[lang].findall(blob))
    return 'ancient' if old >= 2 and old > new else 'modern'


def costume(text: str, lang: str, era: str = 'modern') -> str | None:
    for hat, rx in COSTUME_RE[lang]:
        if rx.search(text):
            if hat == 'soldier':
                return 'helmet' if era == 'ancient' else 'combat'
            return hat
    return None


def ground(texts: list[str]) -> str:
    """The video's ground colour (palette name) from all of its words: history, sky, nature or plain."""
    blob = ' '.join(texts)
    counts = [(len(rx.findall(blob)), -k, key) for k, (key, rx) in enumerate(GROUND)]
    n, _, key = max(counts)
    return palette.GROUNDS[key if n >= 2 else 'plain']

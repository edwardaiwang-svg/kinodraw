import re

import pytest

from kinodraw.numbers import normalize

EN = [
    ('By 1500, twenty million books existed.', 'By fifteen hundred, twenty million books existed.'),
    ('It fell 3.4% on Sep 17, 2026.', 'It fell three point four percent on September seventeenth, twenty twenty-six.'),
    ('From $3.8bn to $250bn.', 'From three point eight billion dollars to two hundred fifty billion dollars.'),
    ('A $19.99 book and a $1 pen.', 'A nineteen ninety-nine book and a one dollar pen.'),
    ('Sell 10-15% of the stock.', 'Sell ten to fifteen percent of the stock.'),
    ('Only 1,500 people came.', 'Only one thousand five hundred people came.'),
    ('The 21st century began.', 'The twenty-first century began.'),
    ('Music of the 1990s and 2020s.', 'Music of the nineteen nineties and twenty twenties.'),
    ('The war lasted 1914–1918.', 'The war lasted nineteen fourteen to nineteen eighteen.'),
    ('Meet at 9:30 am or 10:00.', "Meet at nine thirty AM or ten o'clock."),
    ('Revenue grew 3x in a year.', 'Revenue grew three times in a year.'),
    ('It raised 500k from 12 investors.', 'It raised five hundred thousand from twelve investors.'),
    ('The car does 120 km/h.', 'The car does one hundred twenty kilometers per hour.'),
    ('It weighs 1 kg.', 'It weighs one kilogram.'),
    ('Water boils at 100°C.', 'Water boils at one hundred degrees Celsius.'),
    ('Issue #3 is out.', 'Issue number three is out.'),
    ('About 1/2 of voters and 3/7 of towns.', 'About one half of voters and three seven of towns.'),
    ('Rates fell to -0.5% then 2.', 'Rates fell to minus zero point five percent then two.'),
    ('COVID-19 and 5G and B2B.', 'COVID-nineteen and five G and B two B.'),
    ('In May 2026 the mayor spoke.', 'In May twenty twenty-six the mayor spoke.'),
    ('The Mayor 5 plan.', 'The Mayor five plan.'),
    ('Pages 10–12 explain it.', 'Pages ten to twelve explain it.'),
    ('He sold 2000 shares in 2005.', 'He sold two thousand shares in two thousand five.'),
]
ZH = [
    ('2026年9月17日，美联储降息0.25%。', '二零二六年九月十七日，美联储降息百分之零点二五。'),
    ('股价从38亿美元涨到2500亿美元', '股价从三十八亿美元涨到两千五百亿美元'),
    ('卖出10-15%的仓位', '卖出百分之十到百分之十五的仓位'),
    ('iPhone 17 卖了 1,500 万台', 'iPhone 十七 卖了 一千五百 万台'),
    ('会议在9:30开始，10:00结束。', '会议在九点半开始，十点结束。'),
    ('一半是1/2', '一半是二分之一'),
    ('第3期：$3.8bn', '第三期：三点八十亿美元'),
    ('利率是4.25%', '利率是百分之四点二五'),
]


@pytest.mark.parametrize('display,spoken', EN)
def test_en(display, spoken):
    assert normalize(display, 'en').spoken == spoken


@pytest.mark.parametrize('display,spoken', ZH)
def test_zh(display, spoken):
    assert normalize(display, 'zh').spoken == spoken


EN_PUNCT = re.compile(r'[,.;:?!](?=\s|$|["”’)])|—')
ZH_PUNCT = re.compile(r'[，。；：？！、—]')


@pytest.mark.parametrize('display,_', EN + [(z, None) for z, _ in ZH])
def test_no_digits_and_same_clause_punctuation(display, _):
    lang = 'zh' if re.search(r'[一-鿿]', display) else 'en'
    n = normalize(display, lang)
    assert not re.search(r'\d', n.spoken), n.spoken
    punct = EN_PUNCT if lang == 'en' else ZH_PUNCT
    assert punct.findall(n.spoken) == punct.findall(display)


def test_find_maps_display_phrase_to_spoken():
    n = normalize('Shares rose 3.4% after the 2026 vote.', 'en')
    assert n.find('rose 3.4%') == 'rose three point four percent'
    assert n.find('2026 vote') == 'twenty twenty-six vote'
    assert n.find('after the') == 'after the'

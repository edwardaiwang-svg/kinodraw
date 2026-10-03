"""Display text -> spoken text: numbers become words, nothing else changes.

Only number tokens are rewritten, so clause punctuation (which drives caption
cues) is identical in both strings. Every rewrite is recorded as a span so a
position in the display text can be mapped to the spoken text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import cn2an
from num2words import num2words

NUM = r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?'


@dataclass
class Normalized:
    display: str
    spoken: str
    spans: list = field(default_factory=list)      # (display_start, display_end, spoken_start, spoken_end)

    def to_spoken(self, pos: int) -> int:
        """Spoken-text offset of display offset ``pos`` (start of a rewritten token maps to its start)."""
        shift = 0
        for d0, d1, s0, s1 in self.spans:
            if pos < d0:
                break
            if pos < d1:
                return s0
            shift = s1 - d1
        return pos + shift

    def find(self, phrase: str) -> str | None:
        """The spoken form of a display substring (None when it is not in the display text)."""
        i = self.display.find(phrase)
        if i < 0:
            return None
        return self.spoken[self.to_spoken(i):self.to_spoken(i + len(phrase)) if i + len(phrase) < len(self.display)
                           else len(self.spoken)].strip()


def _latin(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _rewrite(text: str, pattern: re.Pattern, speak) -> Normalized:
    out, spans, last = [], [], 0
    for m in pattern.finditer(text):
        words = speak(m)
        if words is None:
            continue
        if _latin(text[m.start() - 1:m.start()]) and _latin(words[:1]):     # keep words apart: B2B -> B two B
            words = ' ' + words
        if _latin(text[m.end():m.end() + 1]) and _latin(words[-1:]):
            words += ' '
        out.append(text[last:m.start()])
        s0 = sum(map(len, out))
        out.append(words)
        spans.append((m.start(), m.end(), s0, s0 + len(words)))
        last = m.end()
    out.append(text[last:])
    return Normalized(text, ''.join(out), spans)


# ============================================================== English
MONTHS = {m[:3].lower(): m for m in ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                     'September', 'October', 'November', 'December')}
SCALES = {'k': 'thousand', 'thousand': 'thousand', 'm': 'million', 'mn': 'million', 'mm': 'million',
          'million': 'million', 'b': 'billion', 'bn': 'billion', 'billion': 'billion', 't': 'trillion',
          'tn': 'trillion', 'trillion': 'trillion'}
CURRENCIES = {'US$': ('dollar', 'dollars'), '$': ('dollar', 'dollars'), '€': ('euro', 'euros'),
              '£': ('pound', 'pounds'), '¥': ('yen', 'yen'), '₹': ('rupee', 'rupees')}
UNITS = {'km/h': 'kilometers per hour', 'mph': 'miles per hour', 'km': 'kilometers', 'kg': 'kilograms',
         'cm': 'centimeters', 'mm': 'millimeters', '°C': 'degrees Celsius', '°F': 'degrees Fahrenheit',
         '°': 'degrees', 'GB': 'gigabytes', 'MB': 'megabytes', 'TB': 'terabytes', 'GHz': 'gigahertz',
         'kWh': 'kilowatt hours', 'MW': 'megawatts', 'GW': 'gigawatts', 'lbs': 'pounds', 'ft': 'feet'}
FRACTIONS = {'1/2': 'one half', '1/3': 'one third', '2/3': 'two thirds', '1/4': 'one quarter',
             '3/4': 'three quarters', '1/5': 'one fifth', '1/10': 'one tenth'}
SINGULAR = {'kilometers': 'kilometer', 'kilograms': 'kilogram', 'centimeters': 'centimeter',
            'millimeters': 'millimeter', 'degrees': 'degree', 'gigabytes': 'gigabyte', 'megabytes': 'megabyte',
            'terabytes': 'terabyte', 'megawatts': 'megawatt', 'gigawatts': 'gigawatt', 'pounds': 'pound', 'feet': 'foot'}

_cur = '|'.join(re.escape(c) for c in CURRENCIES)
_scale = r'trillion|billion|million|thousand|tn|bn|mn|mm|[kmbt]'
_month = (r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December'
          r'|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?')
_unit = '|'.join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
EN_PATTERN = re.compile(
    rf'(?P<cur>{_cur})\s?(?P<camt>{NUM})(?:\s?(?P<cscale>{_scale})\b)?'
    rf'|(?P<ra>{NUM})\s?(?:-|–|to)\s?(?P<rb>{NUM})\s?(?P<rpct>%)'
    rf'|(?P<pct>-?(?:{NUM}))\s?%'
    rf'|(?P<month>{_month})\s(?P<day>\d{{1,2}})(?!\d|,\d)(?:st|nd|rd|th)?'
    rf'|(?P<h>\d{{1,2}}):(?P<mi>\d{{2}})(?:\s?(?P<ampm>[ap])\.?m\.?)?'
    rf'|(?P<ord>\d+)(?:st|nd|rd|th)\b'
    rf'|(?P<decade>1[1-9]\d0|20[0-9]0)s\b'
    rf'|(?P<ya>1[1-9]\d{{2}}|20\d{{2}})\s?(?:-|–)\s?(?P<yb>1[1-9]\d{{2}}|20\d{{2}})(?!\d)'
    rf'|(?P<mult>{NUM})\s?[x×](?![a-z])'
    rf'|(?<![A-Za-z])(?P<samt>{NUM})(?P<sscale>bn|mn|tn|[kmbKMB])\b'
    rf'|(?P<uamt>{NUM})\s?(?P<unit>{_unit})(?![A-Za-z])'
    rf'|#(?P<hash>\d+)'
    rf'|(?P<frac>\d+/\d+)'
    rf'|(?P<ra2>{NUM})\s?–\s?(?P<rb2>{NUM})'
    rf'|(?P<year>(?<![\d.,$])(?:1[1-9]\d{{2}}|20\d{{2}})(?![\d%]|\.\d|,\d))'
    rf'|(?P<neg>(?<![\w.])-)?(?P<num>{NUM})'
)


def _plain(text: str) -> str:
    return re.sub(r',| and(?= )', '', text)


def en_number(token: str) -> str:
    value = Decimal(token.replace(',', ''))
    return _plain(num2words(value if value % 1 else int(value)))


def en_year(token: str) -> str:
    return _plain(num2words(int(token), to='year'))


def _en_speak(m: re.Match) -> str:
    g = m.groupdict()
    if g['cur']:
        one, many = CURRENCIES[g['cur']]
        amount = g['camt']
        if g['cscale']:
            return f"{en_number(amount)} {SCALES[g['cscale'].lower()]} {many}"
        if re.fullmatch(r'[\d,]+\.\d\d', amount) and not amount.endswith('.00') and one == 'dollar':
            whole, cents = amount.replace(',', '').split('.')
            unit = one if int(whole) == 1 else many
            return f"{en_number(whole)} {unit} and {en_number(cents)} cents"
        return f"{en_number(amount)} {one if Decimal(amount.replace(',', '')) == 1 else many}"
    if g['rpct']:
        return f"{en_number(g['ra'])} to {en_number(g['rb'])} percent"
    if g['pct']:
        token = g['pct']
        return ('minus ' if token.startswith('-') else '') + f"{en_number(token.lstrip('-'))} percent"
    if g['month']:
        month = MONTHS[g['month'].rstrip('.').lower()[:3]]
        return f"{month} {num2words(int(g['day']), to='ordinal')}"
    if g['h']:
        hour, minute = int(g['h']), int(g['mi'])
        if hour > 24 or minute > 59:
            return None
        words = en_number(str(hour)) + (" o'clock" if minute == 0 and not g['ampm'] else
                                          '' if minute == 0 else
                                          f" oh {en_number(str(minute))}" if minute < 10 else f" {en_number(str(minute))}")
        return words + (f" {g['ampm']} m" if g['ampm'] else '')
    if g['ord']:
        return num2words(int(g['ord']), to='ordinal')
    if g['decade']:
        words = en_year(g['decade'])
        return words[:-1] + 'ies' if words.endswith('y') else words + 's'
    if g['ya']:
        return f"{en_year(g['ya'])} to {en_year(g['yb'])}"
    if g['mult']:
        return f"{en_number(g['mult'])} times"
    if g['samt']:
        return f"{en_number(g['samt'])} {SCALES[g['sscale'].lower()]}"
    if g['uamt']:
        first, _, rest = UNITS[g['unit']].partition(' ')
        if Decimal(g['uamt'].replace(',', '')) == 1:
            first = SINGULAR.get(first, first)
        return f"{en_number(g['uamt'])} {first}{' ' + rest if rest else ''}"
    if g['hash']:
        return f"number {en_number(g['hash'])}"
    if g['frac']:
        a, b = g['frac'].split('/')
        return FRACTIONS.get(g['frac'], f'{en_number(a)} {en_number(b)}')
    if g['ra2']:
        return f"{en_number(g['ra2'])} to {en_number(g['rb2'])}"
    if g['year']:
        return en_year(g['year'])
    return ('minus ' if g['neg'] else '') + en_number(g['num'])


def normalize_en(display: str) -> Normalized:
    return _rewrite(display, EN_PATTERN, _en_speak)


# ============================================================== Chinese
ZH_CUR = {'US$': '美元', '$': '美元', '€': '欧元', '£': '英镑', '¥': '元', '￥': '元', 'HK$': '港元'}
_zcur = '|'.join(re.escape(c) for c in sorted(ZH_CUR, key=len, reverse=True))
ZH_PATTERN = re.compile(
    rf'(?P<h>\d{{1,2}})[:：](?P<mi>\d{{2}})'
    rf'|(?P<ra>{NUM})\s?(?:-|–|~|～|至|到)\s?(?P<rb>{NUM})\s?(?P<rpct>[%％])'
    rf'|(?P<cur>{_zcur})\s?(?P<camt>{NUM})(?:\s?(?P<cscale>万亿|亿|万|千|trillion|billion|million|bn|mn|[kmb]))?'
    rf'|(?P<year>\d{{4}})(?=\s?年)'
    rf'|(?P<pct>{NUM})\s?[%％]'
    rf'|(?P<frac>\d+)/(?P<den>\d+)'
    rf'|(?P<num>{NUM})'
)
ZH_SCALES = {'trillion': '万亿', 'billion': '十亿', 'million': '百万', 'bn': '十亿', 'mn': '百万', 'k': '千',
             'm': '百万', 'b': '十亿'}


def zh_number(token: str) -> str:
    words = cn2an.an2cn(token.replace(',', ''), 'low')
    return re.sub(r'(^|[亿万])二(?=[千万亿])', r'\1两', words)


def _zh_speak(m: re.Match) -> str:
    g = m.groupdict()
    if g['h']:
        hour, minute = int(g['h']), int(g['mi'])
        if hour > 24 or minute > 59:
            return None
        return zh_number(str(hour)) + '点' + ('' if minute == 0 else '半' if minute == 30 else
                                              ('零' if minute < 10 else '') + zh_number(str(minute)) + '分')
    if g['rpct']:
        return f"百分之{zh_number(g['ra'])}到百分之{zh_number(g['rb'])}"
    if g['cur']:
        scale = g['cscale'] or ''
        scale = ZH_SCALES.get(scale.lower(), scale)
        return f"{zh_number(g['camt'])}{scale}{ZH_CUR[g['cur']]}"
    if g['year']:
        return ''.join('零一二三四五六七八九'[int(d)] for d in g['year'])
    if g['pct']:
        return f"百分之{zh_number(g['pct'])}"
    if g['frac']:
        return f"{zh_number(g['den'])}分之{zh_number(g['frac'])}"
    return zh_number(g['num'])


def normalize_zh(display: str) -> Normalized:
    return _rewrite(display, ZH_PATTERN, _zh_speak)


def normalize(display: str, lang: str) -> Normalized:
    return normalize_en(display) if lang == 'en' else normalize_zh(display)


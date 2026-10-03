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


# ============================================================== Spanish
ES_CUR = {'US$': ('dólar', 'dólares'), '$': ('dólar', 'dólares'), '€': ('euro', 'euros'),
          '£': ('libra', 'libras'), '¥': ('yen', 'yenes'), '₹': ('rupia', 'rupias')}
ES_CENTS = {'US$': ('centavo', 'centavos'), '$': ('centavo', 'centavos'),
            '€': ('céntimo', 'céntimos'), '£': ('penique', 'peniques')}
ES_UNITS = {'km/h': ('kilómetro por hora', 'kilómetros por hora'), 'km': ('kilómetro', 'kilómetros'),
            'm': ('metro', 'metros'), 'cm': ('centímetro', 'centímetros'), 'mm': ('milímetro', 'milímetros'),
            'kg': ('kilogramo', 'kilogramos'), 'g': ('gramo', 'gramos'), 't': ('tonelada', 'toneladas'),
            'l': ('litro', 'litros'), 'ml': ('mililitro', 'mililitros'),
            '°C': ('grado Celsius', 'grados Celsius'), '°F': ('grado Fahrenheit', 'grados Fahrenheit'),
            '°': ('grado', 'grados'), 'mph': ('milla por hora', 'millas por hora'),
            'GB': ('gigabyte', 'gigabytes'), 'MB': ('megabyte', 'megabytes')}
ES_SCALES = {'k': ('mil', 'mil'), 'thousand': ('mil', 'mil'), 'mil': ('mil', 'mil'),
             'm': ('millón', 'millones'), 'mn': ('millón', 'millones'), 'mm': ('millón', 'millones'),
             'million': ('millón', 'millones'), 'millón': ('millón', 'millones'), 'millones': ('millón', 'millones'),
             'b': ('mil millones', 'mil millones'), 'bn': ('mil millones', 'mil millones'),
             'billion': ('mil millones', 'mil millones'), 't': ('billón', 'billones'),
             'tn': ('billón', 'billones'), 'trillion': ('billón', 'billones')}
ES_NUM = (r'\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d|[.,]\d)'
          r'|\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d|[.,]\d)|\d+(?:[.,]\d+)?')
_es_scale = '(?:MM|(?i:' + '|'.join((r'(?<!\s)' if len(k) < 3 else '') + re.escape(k)   # '10MM' is millions,
                                     for k in sorted(ES_SCALES, key=len, reverse=True) if k != 'mm') + '))'  # '10mm' rain
_es_cscale = '(?i:' + '|'.join(re.escape(k) for k in sorted(ES_SCALES, key=len, reverse=True)) + ')'  # '$5 MM'
_es_unit = '|'.join(re.escape(u) for u in sorted(ES_UNITS, key=len, reverse=True))
ES_PATTERN = re.compile(
    rf'(?P<cur>{_cur})\s?(?P<camt>{ES_NUM})(?:\s?(?P<cscale>{_es_cscale})\b)?'
    rf'|(?P<ra>{ES_NUM})\s?(?:-|–|a)\s?(?P<rb>{ES_NUM})\s?(?P<rpct>%)'
    rf'|(?P<pct>-?(?:{ES_NUM}))\s?%'
    rf'|(?P<samt>{ES_NUM})\s?(?P<sscale>{_es_scale})\b'
    rf'|(?P<uamt>{ES_NUM})\s?(?P<unit>{_es_unit})(?![^\W\d_])'
    rf'|(?P<neg>(?<![\w.])-)?(?P<num>{ES_NUM})'
)


def es_number(token: str) -> str:
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?', token):
        token = token.replace('.', '')
    elif re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', token):
        token = token.replace(',', '')
    whole, dot, fraction = token.partition(',' if ',' in token else '.')
    words = num2words(int(whole), lang='es')
    words = re.sub(r'(veinti)?uno(?= (?:mil|millones|billones)\b)', lambda m: 'veintiún' if m.group(1) else 'un',
                   words)                         # num2words says 'veintiuno mil'; Spanish says 'veintiún mil'
    if dot:
        words += (' coma ' if dot == ',' else ' punto ') + ' '.join(num2words(int(d), lang='es') for d in fraction)
    return words


def _es_speak(m: re.Match) -> str:
    g = m.groupdict()
    if g['cur'] or g['samt'] or g['uamt']:
        token = amount = g['camt'] or g['samt'] or g['uamt']
        scale = (g['cscale'] or g['sscale'] or '').lower()
        if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?', amount):
            amount = amount.replace('.', '')
        elif re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', amount):
            amount = amount.replace(',', '')
        whole, dot, fraction = amount.replace(',', '.').partition('.')
        cents = g['cur'] in ES_CENTS and not scale and len(fraction) == 2
        one = Decimal(whole if cents else amount.replace(',', '.')) == 1
        words = es_number(whole if cents else token)
        if scale or g['unit'] or (g['cur'] and (not dot or cents)):
            feminine = not scale and (g['cur'] in ('£', '₹') or g['unit'] in ('t', 'mph'))
            words = re.sub(r'veintiuno$', 'veintiuna' if feminine else 'veintiún', words)
            words = re.sub(r'uno$', 'una' if feminine else 'un', words)
        if scale:
            words = 'mil' if one and ES_SCALES[scale][1] == 'mil' else words + ' ' + ES_SCALES[scale][0 if one else 1]
        if g['cur']:
            singular, plural = ES_CUR[g['cur']]
            words += (' de ' if scale and ES_SCALES[scale][1] != 'mil' else ' ') + (singular if one and not scale else plural)
            if cents and int(fraction):
                minor = re.sub(r'veintiuno$', 'veintiún', es_number(str(int(fraction))))
                minor = re.sub(r'uno$', 'un', minor)
                words += ' con ' + minor + ' ' + ES_CENTS[g['cur']][0 if int(fraction) == 1 else 1]
        if g['unit']:
            words += ' ' + ES_UNITS[g['unit']][0 if one else 1]
        return words
    if g['rpct']:
        return f"{es_number(g['ra'])} a {es_number(g['rb'])} por ciento"
    if g['pct']:
        token = g['pct']
        return ('menos ' if token.startswith('-') else '') + f"{es_number(token.lstrip('-'))} por ciento"
    words = es_number(g['num'])
    noun = re.match(r'\s+([a-záéíóúüñ]+)\b', m.string[m.end():])
    if (noun and words.endswith('uno') and re.fullmatch(r'[\d.]+', g['num']) and noun.group(1) not in ES_NOT_NOUN
            and not re.fullmatch(r'1\d\d\d|20\d\d', g['num'])):   # '1 perro' -> 'un perro', '21 años' -> 'veintiún'
        feminine = _es_feminine(noun.group(1))
        words = words[:-3] + ('una' if feminine else 'ún' if words.endswith('veintiuno') else 'un')
    return ('menos ' if g['neg'] else '') + words


# Words that follow a number without being what it counts: '1 de cada 4', 'el 1 y el 2', 'tengo 21 más'.
ES_NOT_NOUN = {'de', 'del', 'y', 'e', 'o', 'u', 'a', 'al', 'en', 'por', 'para', 'con', 'sin', 'que', 'es', 'son',
               'fue', 'era', 'eran', 'fueron', 'será', 'más', 'menos', 'entre', 'sobre', 'hasta', 'desde', 'como',
               'cada', 'se', 'lo', 'la', 'el', 'los', 'las', 'le', 'les', 'un', 'una', 'ni', 'pero', 'si', 'no',
               'ya', 'hay', 'está', 'están', 'tiene', 'tienen', 'veces'}
ES_MASCULINE_A = {'día', 'días', 'mapa', 'mapas', 'problema', 'problemas', 'planeta', 'planetas', 'idioma', 'idiomas',
                  'sistema', 'sistemas', 'tema', 'temas', 'clima', 'climas', 'programa', 'programas', 'poema',
                  'poemas', 'esquema', 'esquemas', 'dilema', 'drama', 'dramas', 'cometa', 'cometas', 'sofá',
                  'sofás', 'diploma', 'diplomas', 'telegrama', 'kilograma', 'gorila', 'gorilas', 'koala', 'koalas',
                  'panda', 'pandas', 'atleta', 'atletas', 'astronauta', 'astronautas', 'artista', 'artistas',
                  'dentista', 'dentistas', 'turista', 'turistas', 'papá', 'papás', 'dálmata', 'dálmatas',
                  'ave', 'águila', 'agua', 'hacha', 'alma', 'arma', 'aula', 'área', 'hambre', 'hada', 'ala',
                  'arpa'}   # the last row: feminine, but 'un ave', 'un águila' before a stressed a
ES_FEMININE = {'vez', 'clase', 'clases', 'noche', 'noches', 'parte', 'partes', 'gente', 'mano', 'manos', 'flor',
               'flores', 'mujer', 'mujeres', 'calle', 'calles', 'nube', 'nubes', 'leche', 'llave', 'llaves',
               'fuente', 'fuentes', 'frase', 'frases', 'imagen', 'imágenes', 'luz', 'luces', 'red', 'redes', 'piel',
               'sal', 'muerte', 'suerte', 'mente', 'mentes', 'foto', 'fotos', 'moto', 'motos', 'radio', 'tarde',
               'tardes', 'torre', 'torres', 'carne', 'sangre', 'fiebre', 'nariz', 'raíz', 'raíces', 'voz', 'voces',
               'cruz', 'paz', 'ley', 'leyes', 'miel', 'col', 'sed', 'pared', 'paredes', 'serie', 'series',
               'especie', 'especies', 'superficie', 'nieve', 'base', 'bases', 'fase', 'fases', 'clave',
               'claves', 'nave', 'naves', 'aves'}


def _es_feminine(noun: str) -> bool:
    if noun in ES_MASCULINE_A:
        return False
    return noun in ES_FEMININE or noun.endswith(('a', 'as', 'ción', 'ciones', 'sión', 'siones', 'dad', 'dades',
                                                 'tad', 'tades', 'tud', 'tudes', 'umbre', 'umbres', 'eza'))


def normalize_es(display: str) -> Normalized:
    return _rewrite(display, ES_PATTERN, _es_speak)


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
    if lang == 'es':
        return normalize_es(display)
    return normalize_en(display) if lang == 'en' else normalize_zh(display)


// Display text -> spoken text: numbers become words, nothing else changes (port of kinodraw/numbers.py, English).
//
// Only number tokens are rewritten, so clause punctuation (which drives caption cues) is identical in both
// strings. Every rewrite is recorded as a span so a position in the display text maps to the spoken text.

const NUM = String.raw`\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?`;

export class Normalized {
  constructor(display, spoken, spans = []) {
    this.display = display;
    this.spoken = spoken;
    this.spans = spans;              // [displayStart, displayEnd, spokenStart, spokenEnd]
  }

  /** Spoken-text offset of display offset `pos` (the start of a rewritten token maps to its start). */
  toSpoken(pos) {
    let shift = 0;
    for (const [d0, d1, s0, s1] of this.spans) {
      if (pos < d0) break;
      if (pos < d1) return s0;
      shift = s1 - d1;
    }
    return pos + shift;
  }

  /** The spoken form of a display substring (null when it is not in the display text). */
  find(phrase) {
    const i = this.display.indexOf(phrase);
    if (i < 0) return null;
    const end = i + phrase.length < this.display.length ? this.toSpoken(i + phrase.length) : this.spoken.length;
    return this.spoken.slice(this.toSpoken(i), end).trim();
  }
}

const latin = (ch) => /^[A-Za-z0-9]$/.test(ch);

function rewrite(text, pattern, speak) {
  const out = [];
  const spans = [];
  let last = 0;
  let length = 0;
  for (const m of text.matchAll(pattern)) {
    let words = speak(m);
    if (words == null) continue;
    const start = m.index;
    const end = start + m[0].length;
    if (latin(text.slice(start - 1, start)) && latin(words.slice(0, 1))) words = ' ' + words;   // B2B -> B two B
    if (latin(text.slice(end, end + 1)) && latin(words.slice(-1))) words += ' ';
    out.push(text.slice(last, start));
    length += start - last;
    out.push(words);
    spans.push([start, end, length, length + words.length]);
    length += words.length;
    last = end;
  }
  out.push(text.slice(last));
  return new Normalized(text, out.join(''), spans);
}

// ------------------------------------------------------------ number words (num2words, English)
const SMALL = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven',
  'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
const SCALES = [[10n ** 18n, 'quintillion'], [10n ** 15n, 'quadrillion'], [10n ** 12n, 'trillion'],
  [10n ** 9n, 'billion'], [10n ** 6n, 'million'], [1000n, 'thousand']];
const ORDS = { one: 'first', two: 'second', three: 'third', four: 'fourth', five: 'fifth', six: 'sixth',
  seven: 'seventh', eight: 'eighth', nine: 'ninth', ten: 'tenth', eleven: 'eleventh', twelve: 'twelfth' };

/** num2words' cardinal, with its "and" and commas ("one thousand, two hundred and thirty-four"). */
function cardinalFull(n) {
  n = BigInt(n);
  if (n < 20n) return SMALL[Number(n)];
  if (n < 100n) {
    const r = Number(n % 10n);
    return r ? `${TENS[Number(n / 10n)]}-${SMALL[r]}` : TENS[Number(n / 10n)];
  }
  if (n < 1000n) {
    const head = `${SMALL[Number(n / 100n)]} hundred`;
    const r = n % 100n;
    return r ? `${head} and ${cardinalFull(r)}` : head;
  }
  for (const [s, name] of SCALES) {
    if (n >= s) {
      const head = `${cardinalFull(n / s)} ${name}`;
      const r = n % s;
      if (!r) return head;
      return r < 100n ? `${head} and ${cardinalFull(r)}` : `${head}, ${cardinalFull(r)}`;
    }
  }
  throw new Error(`number too large: ${n}`);
}

const plain = (text) => text.replace(/,| and(?= )/g, '');

function ordinal(n) {
  const words = cardinalFull(n).split(' ');
  const parts = words[words.length - 1].split('-');
  let lastWord = parts[parts.length - 1];
  if (ORDS[lastWord]) lastWord = ORDS[lastWord];
  else lastWord = (lastWord.endsWith('y') ? lastWord.slice(0, -1) + 'ie' : lastWord) + 'th';
  parts[parts.length - 1] = lastWord;
  words[words.length - 1] = parts.join('-');
  return words.join(' ');
}

/** num2words for a decimal: "three point one four" (the digits of the float as Python prints it). */
function decimalWords(token) {
  const value = Number(token);
  const text = String(value);                  // like Python's str(float): '3.80' -> '3.8'
  const [whole, frac = ''] = text.split('.');
  return [cardinalFull(BigInt(whole)), ...(frac ? ['point', ...[...frac].map((d) => SMALL[+d])] : [])].join(' ');
}

export function enNumber(token) {
  const clean = token.replace(/,/g, '');
  const [whole, frac = ''] = clean.split('.');
  if (/[1-9]/.test(frac)) return plain(decimalWords(clean));
  return plain(cardinalFull(BigInt(whole)));
}

export function enYear(token) {
  const val = Number(token);
  const high = Math.floor(val / 100);
  const low = val % 100;
  if (high === 0 || (high % 10 === 0 && low < 10) || high >= 100) return plain(cardinalFull(val));
  const lowText = low === 0 ? 'hundred' : low < 10 ? `oh-${cardinalFull(low)}` : cardinalFull(low);
  return plain(`${cardinalFull(high)} ${lowText}`);
}

// ---------------------------------------------------------------- English patterns
const MONTHS = Object.fromEntries(['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'].map((m) => [m.slice(0, 3).toLowerCase(), m]));
const SCALE_WORDS = { k: 'thousand', thousand: 'thousand', m: 'million', mn: 'million', mm: 'million',
  million: 'million', b: 'billion', bn: 'billion', billion: 'billion', t: 'trillion', tn: 'trillion',
  trillion: 'trillion' };
const CURRENCIES = { 'US$': ['dollar', 'dollars'], '$': ['dollar', 'dollars'], '€': ['euro', 'euros'],
  '£': ['pound', 'pounds'], '¥': ['yen', 'yen'], '₹': ['rupee', 'rupees'] };
const UNITS = { 'km/h': 'kilometers per hour', mph: 'miles per hour', km: 'kilometers', kg: 'kilograms',
  cm: 'centimeters', mm: 'millimeters', '°C': 'degrees Celsius', '°F': 'degrees Fahrenheit', '°': 'degrees',
  GB: 'gigabytes', MB: 'megabytes', TB: 'terabytes', GHz: 'gigahertz', kWh: 'kilowatt hours', MW: 'megawatts',
  GW: 'gigawatts', lbs: 'pounds', ft: 'feet' };
const FRACTIONS = { '1/2': 'one half', '1/3': 'one third', '2/3': 'two thirds', '1/4': 'one quarter',
  '3/4': 'three quarters', '1/5': 'one fifth', '1/10': 'one tenth' };
const SINGULAR = { kilometers: 'kilometer', kilograms: 'kilogram', centimeters: 'centimeter',
  millimeters: 'millimeter', degrees: 'degree', gigabytes: 'gigabyte', megabytes: 'megabyte', terabytes: 'terabyte',
  megawatts: 'megawatt', gigawatts: 'gigawatt', pounds: 'pound', feet: 'foot' };

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
const CUR = Object.keys(CURRENCIES).map(esc).join('|');
const SCALE = 'trillion|billion|million|thousand|tn|bn|mn|mm|[kmbt]';
const MONTH = String.raw`\b(?:January|February|March|April|May|June|July|August|September|October|November|December`
  + String.raw`|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?`;
const UNIT = Object.keys(UNITS).sort((a, b) => b.length - a.length).map(esc).join('|');
const EN_PATTERN = new RegExp([
  String.raw`(?<cur>${CUR})\s?(?<camt>${NUM})(?:\s?(?<cscale>${SCALE})\b)?`,
  String.raw`(?<ra>${NUM})\s?(?:-|–|to)\s?(?<rb>${NUM})\s?(?<rpct>%)`,
  String.raw`(?<pct>-?(?:${NUM}))\s?%`,
  String.raw`(?<month>${MONTH})\s(?<day>\d{1,2})(?!\d|,\d)(?:st|nd|rd|th)?`,
  String.raw`(?<h>\d{1,2}):(?<mi>\d{2})(?:\s?(?<ampm>[ap])\.?m\.?)?`,
  String.raw`(?<ord>\d+)(?:st|nd|rd|th)\b`,
  String.raw`(?<decade>1[1-9]\d0|20[0-9]0)s\b`,
  String.raw`(?<ya>1[1-9]\d{2}|20\d{2})\s?(?:-|–)\s?(?<yb>1[1-9]\d{2}|20\d{2})(?!\d)`,
  String.raw`(?<mult>${NUM})\s?[x×](?![a-z])`,
  String.raw`(?<![A-Za-z])(?<samt>${NUM})(?<sscale>bn|mn|tn|[kmbKMB])\b`,
  String.raw`(?<uamt>${NUM})\s?(?<unit>${UNIT})(?![A-Za-z])`,
  String.raw`#(?<hash>\d+)`,
  String.raw`(?<frac>\d+\/\d+)`,
  String.raw`(?<ra2>${NUM})\s?–\s?(?<rb2>${NUM})`,
  String.raw`(?<year>(?<![\d.,$])(?:1[1-9]\d{2}|20\d{2})(?![\d%]|\.\d|,\d))`,
  String.raw`(?<neg>(?<![\w.])-)?(?<num>${NUM})`,
].join('|'), 'g');

const isOne = (amount) => Number(amount.replace(/,/g, '')) === 1;

function enSpeak(m) {
  const g = m.groups;
  if (g.cur) {
    const [one, many] = CURRENCIES[g.cur];
    const amount = g.camt;
    if (g.cscale) return `${enNumber(amount)} ${SCALE_WORDS[g.cscale.toLowerCase()]} ${many}`;
    if (/^[\d,]+\.\d\d$/.test(amount) && !amount.endsWith('.00') && one === 'dollar') {
      const [whole, cents] = amount.replace(/,/g, '').split('.');
      return `${enNumber(whole)} ${Number(whole) === 1 ? one : many} and ${enNumber(cents)} cents`;
    }
    return `${enNumber(amount)} ${isOne(amount) ? one : many}`;
  }
  if (g.rpct) return `${enNumber(g.ra)} to ${enNumber(g.rb)} percent`;
  if (g.pct) return (g.pct.startsWith('-') ? 'minus ' : '') + `${enNumber(g.pct.replace(/^-/, ''))} percent`;
  if (g.month) return `${MONTHS[g.month.replace(/\.$/, '').toLowerCase().slice(0, 3)]} ${ordinal(Number(g.day))}`;
  if (g.h) {
    const hour = Number(g.h);
    const minute = Number(g.mi);
    if (hour > 24 || minute > 59) return null;
    const words = enNumber(String(hour)) + (minute === 0 && !g.ampm ? " o'clock" : minute === 0 ? ''
      : minute < 10 ? ` oh ${enNumber(String(minute))}` : ` ${enNumber(String(minute))}`);
    return words + (g.ampm ? ` ${g.ampm} m` : '');
  }
  if (g.ord) return ordinal(Number(g.ord));
  if (g.decade) {
    const words = enYear(g.decade);
    return words.endsWith('y') ? words.slice(0, -1) + 'ies' : words + 's';
  }
  if (g.ya) return `${enYear(g.ya)} to ${enYear(g.yb)}`;
  if (g.mult) return `${enNumber(g.mult)} times`;
  if (g.samt) return `${enNumber(g.samt)} ${SCALE_WORDS[g.sscale.toLowerCase()]}`;
  if (g.uamt) {
    let [first, ...rest] = UNITS[g.unit].split(' ');
    if (isOne(g.uamt)) first = SINGULAR[first] ?? first;
    return `${enNumber(g.uamt)} ${first}${rest.length ? ' ' + rest.join(' ') : ''}`;
  }
  if (g.hash) return `number ${enNumber(g.hash)}`;
  if (g.frac) {
    const [a, b] = g.frac.split('/');
    return FRACTIONS[g.frac] ?? `${enNumber(a)} ${enNumber(b)}`;
  }
  if (g.ra2) return `${enNumber(g.ra2)} to ${enNumber(g.rb2)}`;
  if (g.year) return enYear(g.year);
  return (g.neg ? 'minus ' : '') + enNumber(g.num);
}

export function normalize(display) {
  return rewrite(display, EN_PATTERN, enSpeak);
}

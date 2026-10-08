"""Shorthand a customer writes and a careful announcer says in full: one table of English abbreviations with the
context that decides each one, applied to the voice text only (the captions keep the writing).

Units after a number ("2 ft", "850 sq ft", "3BR") are numbers.py's (it reads the number and its unit together, from
``UNITS`` here); everything else is read here from the spoken text (numbers already words) by ``say``, which
speech._say runs for the voice: titles before a name ("Dr. Lee" Doctor), street words after one ("Oak Dr." Drive),
suffixes after a name, words that need a number after them ("Vol. 3"), office and business words, listing and
kitchen shorthand, Latin shorthand, states after a town, prices per something ("/mo"), symbols in prose and the
separators between listed facts. ``abbreviation_period`` tells the captions and the pauses whether a period is an
abbreviation's or a sentence's end.

A word is never expanded outside its context: "St." is Saint before a name and Street after one, a unit only after a
number, a state only after "Town, ", and capitalised real words or acronyms said as letters ("IN", "US", "FAQ") are
left as written (the voice reads those right on its own).
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ units (numbers.py reads these after a number)
# abbreviation: (singular, plural). A unit is only ever expanded after a number.
UNITS = {
    # length
    'mm': ('millimeter', 'millimeters'), 'cm': ('centimeter', 'centimeters'), 'm': ('meter', 'meters'),
    'km': ('kilometer', 'kilometers'), 'ft': ('foot', 'feet'), 'yd': ('yard', 'yards'), 'yds': ('yard', 'yards'),
    'mi': ('mile', 'miles'),
    # area
    'sq ft': ('square foot', 'square feet'), 'sq. ft': ('square foot', 'square feet'),
    'sqft': ('square foot', 'square feet'), 'sq.ft': ('square foot', 'square feet'),
    'ft²': ('square foot', 'square feet'), 'sf': ('square foot', 'square feet'),
    'sq in': ('square inch', 'square inches'), 'sq yd': ('square yard', 'square yards'),
    'sq m': ('square meter', 'square meters'), 'm²': ('square meter', 'square meters'),
    'sq mi': ('square mile', 'square miles'), 'sq km': ('square kilometer', 'square kilometers'),
    'km²': ('square kilometer', 'square kilometers'), 'ac': ('acre', 'acres'), 'ha': ('hectare', 'hectares'),
    # volume
    'ml': ('milliliter', 'milliliters'), 'mL': ('milliliter', 'milliliters'), 'l': ('liter', 'liters'),
    'L': ('liter', 'liters'), 'cl': ('centiliter', 'centiliters'), 'gal': ('gallon', 'gallons'),
    'gals': ('gallon', 'gallons'), 'qt': ('quart', 'quarts'), 'qts': ('quart', 'quarts'),
    'fl oz': ('fluid ounce', 'fluid ounces'), 'fl. oz': ('fluid ounce', 'fluid ounces'), 'cc': ('cc', 'cc'),
    'cu ft': ('cubic foot', 'cubic feet'), 'cu. ft': ('cubic foot', 'cubic feet'), 'm³': ('cubic meter', 'cubic meters'),
    # kitchen
    'tsp': ('teaspoon', 'teaspoons'), 'tsps': ('teaspoon', 'teaspoons'), 't': ('teaspoon', 'teaspoons'),
    'tbsp': ('tablespoon', 'tablespoons'), 'Tbsp': ('tablespoon', 'tablespoons'), 'tbsps': ('tablespoon', 'tablespoons'),
    'Tbs': ('tablespoon', 'tablespoons'), 'tbs': ('tablespoon', 'tablespoons'), 'T': ('tablespoon', 'tablespoons'),
    'c': ('cup', 'cups'), 'pkg': ('package', 'packages'), 'pkgs': ('package', 'packages'), 'pkt': ('packet', 'packets'),
    'doz': ('dozen', 'dozen'), 'dz': ('dozen', 'dozen'),
    # weight
    'mg': ('milligram', 'milligrams'), 'g': ('gram', 'grams'), 'kg': ('kilogram', 'kilograms'),
    'oz': ('ounce', 'ounces'), 'lb': ('pound', 'pounds'), 'lbs': ('pound', 'pounds'),
    # speed and rates
    'mph': ('mile per hour', 'miles per hour'), 'km/h': ('kilometer per hour', 'kilometers per hour'),
    'kph': ('kilometer per hour', 'kilometers per hour'), 'kmh': ('kilometer per hour', 'kilometers per hour'),
    'm/s': ('meter per second', 'meters per second'), 'ft/s': ('foot per second', 'feet per second'),
    'kn': ('knot', 'knots'), 'kts': ('knot', 'knots'), 'rpm': ('revolution per minute', 'revolutions per minute'),
    'bpm': ('beat per minute', 'beats per minute'), 'fps': ('frame per second', 'frames per second'),
    'mpg': ('mile per gallon', 'miles per gallon'),
    # temperature
    '°C': ('degree Celsius', 'degrees Celsius'), 'ºC': ('degree Celsius', 'degrees Celsius'),
    '°F': ('degree Fahrenheit', 'degrees Fahrenheit'), 'ºF': ('degree Fahrenheit', 'degrees Fahrenheit'),
    '°': ('degree', 'degrees'), 'º': ('degree', 'degrees'), 'deg': ('degree', 'degrees'),
    'degs': ('degree', 'degrees'),
    # time
    'ms': ('millisecond', 'milliseconds'), 's': ('second', 'seconds'), 'sec': ('second', 'seconds'), 'secs': ('second', 'seconds'),
    'min': ('minute', 'minutes'), 'mins': ('minute', 'minutes'), 'hr': ('hour', 'hours'), 'hrs': ('hour', 'hours'),
    'h': ('hour', 'hours'), 'wk': ('week', 'weeks'), 'wks': ('week', 'weeks'), 'mo': ('month', 'months'),
    'mos': ('month', 'months'), 'yr': ('year', 'years'), 'yrs': ('year', 'years'),
    # data, frequency, power
    'KB': ('kilobyte', 'kilobytes'), 'kB': ('kilobyte', 'kilobytes'), 'MB': ('megabyte', 'megabytes'),
    'GB': ('gigabyte', 'gigabytes'), 'TB': ('terabyte', 'terabytes'),
    'Kbps': ('kilobit per second', 'kilobits per second'), 'kbps': ('kilobit per second', 'kilobits per second'),
    'Mbps': ('megabit per second', 'megabits per second'), 'Gbps': ('gigabit per second', 'gigabits per second'),
    'Hz': ('hertz', 'hertz'), 'kHz': ('kilohertz', 'kilohertz'), 'MHz': ('megahertz', 'megahertz'),
    'GHz': ('gigahertz', 'gigahertz'), 'W': ('watt', 'watts'), 'kW': ('kilowatt', 'kilowatts'),
    'MW': ('megawatt', 'megawatts'), 'GW': ('gigawatt', 'gigawatts'), 'kWh': ('kilowatt hour', 'kilowatt hours'),
    'Wh': ('watt hour', 'watt hours'), 'mAh': ('milliamp hour', 'milliamp hours'), 'V': ('volt', 'volts'),
    'hp': ('horsepower', 'horsepower'), 'kcal': ('kilocalorie', 'kilocalories'), 'cal': ('calorie', 'calories'),
    # counts in listings and on shelves
    'BR': ('bedroom', 'bedrooms'), 'br': ('bedroom', 'bedrooms'), 'bd': ('bedroom', 'bedrooms'),
    'bdrm': ('bedroom', 'bedrooms'), 'bdrms': ('bedroom', 'bedrooms'), 'BA': ('bath', 'baths'),
    'ba': ('bath', 'baths'), 'bth': ('bath', 'baths'), 'pc': ('piece', 'pieces'), 'pcs': ('piece', 'pieces'),
    'pk': ('pack', 'packs'), 'ct': ('count', 'count'),
}

# ------------------------------------------------------------------ words and the context each needs
# Before a capitalised name; never the end of a sentence.
TITLES = {'Mr': 'Mister', 'Mrs': 'Missus', 'Ms': 'Miz', 'Mx': 'Mix', 'Dr': 'Doctor', 'Prof': 'Professor',
          'Rev': 'Reverend', 'Fr': 'Father', 'Pres': 'President', 'Gov': 'Governor', 'Sen': 'Senator',
          'Rep': 'Representative', 'Capt': 'Captain', 'Cpt': 'Captain', 'Lt': 'Lieutenant', 'Sgt': 'Sergeant',
          'Col': 'Colonel', 'Gen': 'General', 'Maj': 'Major', 'Cpl': 'Corporal', 'Pvt': 'Private', 'Adm': 'Admiral',
          'Cmdr': 'Commander', 'Det': 'Detective', 'Insp': 'Inspector', 'Supt': 'Superintendent',
          'Atty': 'Attorney', 'Hon': 'Honorable', 'Amb': 'Ambassador', 'Msgr': 'Monsignor', 'Coach': None,
          'St': 'Saint', 'Ste': 'Sainte', 'Mt': 'Mount', 'Ft': 'Fort', 'feat': 'featuring'}
# Titles that are written without a period too ("Mr Jones", "St Louis").
BARE_TITLES = {'Mr', 'Mrs', 'Ms', 'Mx', 'Dr', 'St', 'Mt', 'Ft'}
# Titles said even before a lowercase word ("Mr. and Mrs. Lee", "Dr. who?").
LOOSE_TITLES = {'Mr', 'Mrs', 'Ms', 'Mx', 'Prof'}
# After a street's name or a house number ("Elm St.", "42 Oak Dr", "5th Ave"); may end a sentence.
PLACES = {'St': 'Street', 'Ave': 'Avenue', 'Av': 'Avenue', 'Rd': 'Road', 'Blvd': 'Boulevard', 'Ln': 'Lane',
          'Dr': 'Drive', 'Ct': 'Court', 'Pl': 'Place', 'Sq': 'Square', 'Ter': 'Terrace', 'Terr': 'Terrace',
          'Cir': 'Circle', 'Pkwy': 'Parkway', 'Hwy': 'Highway', 'Fwy': 'Freeway', 'Expy': 'Expressway',
          'Tpke': 'Turnpike', 'Rte': 'Route', 'Trl': 'Trail', 'Aly': 'Alley', 'Plz': 'Plaza', 'Ctr': 'Center',
          'Hts': 'Heights', 'Is': 'Island', 'Lk': 'Lake', 'Mtn': 'Mountain', 'Pk': 'Park', 'Pt': 'Point',
          'Sta': 'Station', 'Cres': 'Crescent', 'Grv': 'Grove', 'Hbr': 'Harbor', 'Jct': 'Junction',
          'Xing': 'Crossing', 'Vlg': 'Village', 'Cyn': 'Canyon', 'Crk': 'Creek', 'Spgs': 'Springs', 'Bch': 'Beach',
          'Mt': 'Mount', 'Ft': 'Fort'}
# Street words that are English words without their period: only "Is." and "Pt." with it.
DOTTED_PLACES = {'Is', 'Pt', 'Pk', 'Pl', 'Sq', 'Ter', 'Mt', 'Ft'}
# After a person's name.
SUFFIXES = {'Jr': 'Junior', 'Sr': 'Senior', 'Esq': 'Esquire'}
# Before a number ("Vol. 3", "Apt 4B", "Est. 1985", "c. 1850").
BEFORE_NUMBER = {'No': 'number', 'Nos': 'numbers', 'Vol': 'volume', 'Vols': 'volumes', 'Ch': 'chapter',
                 'Chap': 'chapter', 'Fig': 'figure', 'Figs': 'figures', 'Sec': 'section', 'Pt': 'part',
                 'Ep': 'episode', 'Ex': 'exercise', 'pg': 'page', 'pgs': 'pages', 'p': 'page', 'pp': 'pages',
                 'Apt': 'apartment', 'Ste': 'suite', 'Bldg': 'building', 'Rm': 'room', 'Fl': 'floor',
                 'Hwy': 'highway', 'Rte': 'route', 'Tel': 'phone', 'Ph': 'phone', 'Gr': 'grade', 'Est': 'established',
                 'c': 'circa', 'ca': 'circa', 'Exp': 'expires', 'Rev': 'revision', 'Ed': 'edition', 'Lv': 'level',
                 'Lvl': 'level', 'Pop': 'population', 'Elev': 'elevation', 'Qty': 'quantity', 'Ref': 'reference'}
# Written without a period too before their number ("Apt 4", "Hwy 1", "pg 12").
BARE_BEFORE_NUMBER = {'Vol', 'Ch', 'Fig', 'Ep', 'pg', 'pgs', 'pp', 'Apt', 'Ste', 'Bldg', 'Rm', 'Hwy', 'Rte', 'Tel',
                      'Lv', 'Lvl', 'Qty', 'Gr', 'Exp', 'Est', 'Elev', 'Pop'}
# Anywhere they are written, with their period (or without it, for those in BARE_WORDS). Office and business words,
# listing and classified-ad shorthand, kitchen words, Latin shorthand.
WORDS = {
    # Latin
    'e.g': 'for example', 'eg': 'for example', 'i.e': 'that is', 'ie': 'that is', 'etc': 'et cetera',
    'vs': 'versus', 'approx': 'approximately', 'cf': 'compare', 'viz': 'namely', 'a.k.a': 'also known as',
    'aka': 'also known as', 'et al': 'and others', 'N.B': 'note', 'ibid': 'in the same place',
    # business and organisations
    'Co': 'Company', 'Dept': 'Department', 'Depts': 'Departments', 'Govt': 'Government', 'Corp': 'Corporation',
    'Inc': 'Incorporated', 'Ltd': 'Limited', 'Bros': 'Brothers', 'Assn': 'Association', 'Assoc': 'Association',
    'Intl': 'International', 'Natl': 'National', 'Univ': 'University', 'Hosp': 'Hospital',
    'Mfg': 'Manufacturing', 'Mgmt': 'Management', 'Svc': 'Service', 'Svcs': 'Services', 'Dist': 'District',
    'Div': 'Division', 'Inst': 'Institute', 'Mgr': 'Manager', 'Asst': 'Assistant', 'Acct': 'Account',
    'Admin': 'Administration', 'Dir': 'Director', 'Sch': 'School', 'Acad': 'Academy', 'Lib': 'Library',
    'Comm': 'Committee', 'Coord': 'Coordinator', 'Exec': 'Executive', 'Hdqtrs': 'Headquarters', 'HQ': 'headquarters',
    'Attn': 'Attention', 'Hrs': 'Hours', 'Min': 'Minimum', 'Max': 'Maximum', 'min': 'minimum', 'max': None, 'Misc': 'Miscellaneous', 'Info': 'Information',
    'Mtg': 'Meeting', 'Appt': 'Appointment', 'Appts': 'Appointments', 'Mon-Fri': None,
    # listings and classified ads
    'OBO': 'or best offer', 'O.B.O': 'or best offer', 'incl': 'including', 'excl': 'excluding',
    'avail': 'available', 'util': 'utilities', 'utils': 'utilities', 'furn': 'furnished', 'unfurn': 'unfurnished',
    'hdwd': 'hardwood', 'flrs': 'floors', 'nr': 'near', 'neg': 'negotiable', 'nego': 'negotiable',
    'refs': 'references', 'req': 'required', 'reqd': 'required', 'orig': 'original', 'pref': 'preferred',
    'exc': 'excellent', 'excel': 'excellent', 'cond': 'condition', 'dep': 'deposit', 'immed': 'immediately',
    'ea': 'each', 'lg': 'large', 'med': 'medium', 'sm': 'small', 'bsmt': 'basement', 'gar': 'garage',
    'prkg': 'parking', 'pkng': 'parking', 'kit': None, 'lrg': 'large', 'xlg': 'extra large', 'bdrm': 'bedroom',
    'bdrms': 'bedrooms', 'W/D': 'washer and dryer', 'w/d': 'washer and dryer', 'D/W': 'dishwasher',
    'd/w': 'dishwasher', 'A/C': 'AC', 'a/c': 'AC', 'N/A': 'N A', 'n/a': 'N A', 'N/S': 'non-smoking',
    'c/o': 'care of', 'y/o': 'year old', 'yo': None, 'FT': 'full-time', 'PT': 'part-time', 'mtg': 'meeting',
    'appt': 'appointment', 'appts': 'appointments', 'mgr': 'manager', 'asst': 'assistant', 'dept': 'department',
    'govt': 'government', 'qty': 'quantity', 'misc': 'miscellaneous', 'tix': 'tickets', 'pd': 'paid',
    'w/e': 'weekend', 'wknd': 'weekend', 'wkday': 'weekday', 'wkdays': 'weekdays', 'wkends': 'weekends',
    'bkfst': 'breakfast', 'apt': 'apartment', 'bldg': 'building', 'hrs': None, 'pp': None, 'pls': None,
    # kitchen
    'pkg': 'package', 'pkt': 'packet', 'tsp': 'teaspoon', 'tbsp': 'tablespoon', 'Tbsp': 'tablespoon',
    'oz': 'ounce', 'lb': 'pound', 'lbs': 'pounds', 'doz': 'dozen', 'temp': None, 'qt': 'quart', 'gal': 'gallon',
}
WORDS = {k: v for k, v in WORDS.items() if v}
# Said without their period as well (a bare "OBO", "incl", "approx"); the rest only with it ("Inc.", "Dept.").
BARE_WORDS = {'OBO', 'incl', 'excl', 'approx', 'aka', 'avail', 'util', 'utils', 'furn', 'unfurn', 'hdwd', 'flrs',
              'nr', 'nego', 'reqd', 'immed', 'bsmt', 'prkg', 'pkng', 'lrg', 'xlg', 'W/D', 'w/d', 'D/W', 'd/w',
              'A/C', 'a/c', 'N/A', 'n/a', 'N/S', 'c/o', 'y/o', 'FT', 'PT', 'mtg', 'appt', 'appts', 'mgr', 'asst',
              'dept', 'govt', 'qty', 'apt', 'bldg', 'misc', 'tix', 'w/e', 'wknd', 'wkday', 'wkdays', 'wkends', 'bkfst', 'vs',
              'Dept', 'Govt', 'Mgr', 'Asst', 'Mgmt', 'Mfg', 'Svc', 'Svcs', 'Intl', 'Natl', 'Assn', 'Hrs', 'HQ',
              'Attn', 'Mtg', 'Appt', 'Appts', 'Hdqtrs', 'bdrm', 'bdrms', 'tsp', 'tbsp', 'Tbsp', 'pkg', 'pkt',
              'oz', 'lb', 'lbs', 'doz', 'ea', 'excel', 'Misc', 'Acct', 'Coord', 'refs', 'lg'}
# Words that lead into a name or a phrase and so never end a sentence ("Natl. Weather Service", "Univ. of Iowa").
LEADING_WORDS = {'e.g', 'eg', 'i.e', 'ie', 'vs', 'cf', 'viz', 'a.k.a', 'aka', 'approx', 'N.B', 'incl', 'excl', 'c/o',
                 'Attn', 'Natl', 'Intl', 'Univ', 'Asst', 'Exec', 'Dir', 'Coord', 'Min', 'Max', 'min', 'Assoc',
                 'Admin', 'Mgr', 'asst', 'mgr', 'Info'}
# Kitchen and shelf words said only after "a", "an", "per", "each" or a number word (a bare "lb" in prose stays).
COUNTED_WORDS = {'tsp', 'tbsp', 'Tbsp', 'oz', 'lb', 'lbs', 'doz', 'pkg', 'pkt', 'qt', 'gal', 'med', 'sm', 'FT', 'PT'}
# After an ordinal ("2nd fl.", "1st mo.", "3rd ed.").
AFTER_ORDINAL = {'fl': 'floor', 'flr': 'floor', 'Fl': 'Floor', 'mo': 'month', 'yr': 'year', 'wk': 'week',
                 'ed': 'edition', 'Ed': 'Edition', 'qtr': 'quarter', 'gr': 'grade', 'pl': 'place'}
# Two capitalised names apart: "Smith v. Jones".
BETWEEN = {'v': 'versus'}
# After "Town, " and before the end, a ZIP code or a break: "Austin, TX 78701".
STATES = {'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California', 'CO': 'Colorado',
          'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
          'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana',
          'ME': 'Maine', 'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota',
          'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
          'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina',
          'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania',
          'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas',
          'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
          'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'D C', 'PR': 'Puerto Rico',
          'Calif': 'California', 'Mass': 'Massachusetts', 'Fla': 'Florida', 'Penn': None, 'Ore': 'Oregon',
          'Wash': 'Washington', 'Tex': 'Texas', 'Ariz': 'Arizona', 'Colo': 'Colorado', 'Conn': 'Connecticut'}
STATES = {k: v for k, v in STATES.items() if v}
# Compass points on an address ("N. Main St.", "12 W 4th St", "Pine Ave NE").
COMPASS = {'N': 'North', 'S': 'South', 'E': 'East', 'W': 'West', 'NE': 'Northeast', 'NW': 'Northwest',
           'SE': 'Southeast', 'SW': 'Southwest'}
# After a slash or "per" ("$1,500/mo", "$12/hr", "$5 per lb"): (the word a slash becomes, the noun).
PER = {'mo': ('a', 'month'), 'month': ('a', 'month'), 'hr': ('an', 'hour'), 'h': ('an', 'hour'),
       'hour': ('an', 'hour'), 'wk': ('a', 'week'), 'week': ('a', 'week'), 'yr': ('a', 'year'), 'year': ('a', 'year'),
       'day': ('a', 'day'), 'night': ('a', 'night'), 'nt': ('a', 'night'), 'min': ('a', 'minute'),
       'lb': ('a', 'pound'), 'kg': ('a', 'kilogram'), 'oz': ('an', 'ounce'), 'gal': ('a', 'gallon'),
       'mi': ('a', 'mile'), 'km': ('a', 'kilometer'), 'sq ft': ('per', 'square foot'), 'sf': ('per', 'square foot'),
       'sqft': ('per', 'square foot'), 'ea': ('', 'each'), 'each': ('', 'each'), 'pp': ('per', 'person'),
       'person': ('per', 'person'), 'pers': ('per', 'person'), 'pc': ('a', 'piece'), 'unit': ('per', 'unit'),
       'item': ('per', 'item'), 'doz': ('a', 'dozen'), 'dozen': ('a', 'dozen'), 'visit': ('a', 'visit'),
       'session': ('a', 'session'), 'class': ('a', 'class'), 'ticket': ('a', 'ticket'), 'head': ('a', 'head'),
       'household': ('per', 'household'), 'family': ('per', 'family'), 'couple': ('per', 'couple'),
       'game': ('a', 'game'), 'serving': ('a', 'serving'), 'slice': ('a', 'slice'), 'bag': ('a', 'bag'),
       'box': ('a', 'box'), 'dz': ('a', 'dozen'), 'qt': ('a', 'quart'), 'ft': ('a', 'foot'), 'yd': ('a', 'yard')}

WEEKDAY_WORDS = ('Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tues?|Wed|Thu|Thurs?|Fri|Sat|Sun')
MONTH_WORDS = ('January|February|March|April|May|June|July|August|September|October|November|December|'
               'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec')
COUNT = (r'(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|'
         r'sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|'
         r'half|a half|quarter|third|dozen)\b')
NUMBER_WORD = r'(?:\d|' + COUNT + ')'
# A year said in words or written in digits ("nineteen hundred", "eighteen fifties", "two thousand ten", "1900").
YEAR_WORD = (r'(?:1[0-9]\d\d|20\d\d|(?:eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
             r'twenty)\b|two thousand\b|one thousand\b)')
ORDINAL_WORD = (r'(?:\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|[a-z]+teenth|'
                r'[a-z]+tieth|hundredth|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)-'
                r'(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth))')
# A capitalised word the sentence's grammar does not explain: a name ("Elm", "Oak", "O'Neil", "MAIN").
_NAME_BEFORE = re.compile(r"(?:^|[\s(\[{\"“‘'«—–])(?P<name>[A-Z][\w'’-]*)[ \t]+$")
_NEXT_CAPITAL = re.compile(r'\s+["“‘\'(\[{«]*[A-Z]')
# Words after a period that keep the abbreviation's phrase going: a date, a day, a time zone, a compass point.
_NOT_A_NEW_SENTENCE = re.compile(r'\s+["“‘\'(\[{«]*(?:' + WEEKDAY_WORDS + '|' + MONTH_WORDS + r'|Eastern|Central|Pacific|'
                                 r'Mountain|Atlantic|GMT|UTC|[A-Z]{1,2}T|N|S|E|W|NE|NW|SE|SW)\b')

_TOKEN = re.compile(r"(?<![\w.@/&’-])(?<![\w.]')(?P<tok>[A-Za-z]+(?:\.[A-Za-z]+)*(?:/[A-Za-z]+)?(?: al)?)(?P<dot>\.)?"
                    r"(?![\w@/&'’]|-\w|\.\w)")


def _lookup(table: dict, raw: str) -> str | None:
    """The table's key for a written form: as listed, or all in capitals ("MAIN ST.") for a capitalised key."""
    if raw in table:
        return raw
    if raw.isupper() and len(raw) > 1:
        key = raw[0] + raw[1:].lower()
        if key in table:
            return key
    return None


def _cap(word: str, raw: str, start: bool) -> str:
    """A lowercase expansion takes a capital where its abbreviation had one at a sentence start ("Approx. 40")."""
    return word[0].upper() + word[1:] if start and raw[:1].isupper() and word[:1].islower() else word


def _sentence_start(before: str) -> bool:
    before = re.sub(r'[\s“‘"\'(\[{«—–]+$', '', before)       # an opening quote, bracket or dash starts no new clause
    return not before.strip() or bool(re.search(r'[.!?:;\n]["”’)\]]*$', before))


def _name_before(before: str) -> bool:
    """A name or a house number right before ("Elm St.", "42 Oak Dr", "fifth Ave", "Main St NE")."""
    return bool(_NAME_BEFORE.search(before) or re.search(r'(?:\d|\b' + COUNT + r'|\b' + ORDINAL_WORD +
                                                        r')[ \t]+$', before))


def _name_word_before(before: str) -> str | None:
    m = _NAME_BEFORE.search(before)
    return m.group('name') if m else None


def _place_sense(before: str, after: str) -> bool:
    """For a word that is a title before a name and a street after one (St., Dr., Mt., Ft.): the street when a name
    or a number comes before it, unless that name only starts the sentence and a name follows ("Meet Dr. Patel")."""
    if re.search(r'(?:\d|\b' + ORDINAL_WORD + r')\s+$', before) or (
            re.search(r'(?:\d|\b' + ORDINAL_WORD + r')\s+(?:[\w\'’-]+\s+){0,3}$', before) and _NAME_BEFORE.search(before)):
        return True
    name = _name_word_before(before)
    if not name:
        return False
    starts = _sentence_start(before[:before.rstrip().rfind(name)])
    return not (starts and _NEXT_CAPITAL.match(after) and not _LINE_END.match(after))


# The line ends right after the word: a title never reaches across a line break to the next line's name.
_LINE_END = re.compile(r'[ \t]*(?:\n|$)')
# Capitalised words that go on with an organisation's name after its shorthand ("Acme Corp. Headquarters", "the Water
# Dept. Office"); any other capitalised word after the period starts a new sentence ("...joined Acme Corp. Bob left").
ORG_NOUNS = set('office offices headquarters building buildings board president chair chairman chairwoman ceo cfo '
                'chief director directors manager managers staff team teams employees workers members officials '
                'officers spokesperson spokesman spokeswoman head heads plant plants factory factories store stores '
                'branch branches campus division unit lab labs laboratory center centre hall tower annex warehouse '
                'website site logo policy policies report reports records account accounts contract contracts shares '
                'stock union trucks truck vans van fleet clinic library school offices parking lot lobby'.split())
# An organisation's shorthand after its name.
ORG_WORDS = {'Co', 'Corp', 'Inc', 'Ltd', 'Bros', 'Dept', 'Depts', 'Govt', 'Assn', 'Assoc', 'Univ', 'Hosp', 'Mfg',
             'Mgmt', 'Svc', 'Svcs', 'Dist', 'Div', 'Inst', 'Acad', 'Lib', 'Comm', 'Sch', 'Intl', 'Natl'}


def _org_goes_on(after: str) -> bool:
    """After an organisation's shorthand: does a capitalised word that goes on with its name follow?"""
    m = re.match(r'[ \t]+([A-Z][\w\'’-]*)', after)
    return bool(m and m.group(1).lower() in ORG_NOUNS)


def ends_sentence(after: str) -> bool:
    """Does a sentence end at an abbreviation's period that the text ``after`` follows? Yes before a capitalised word
    (or at the end), unless that word continues the phrase (a day, a month, a time zone, a compass point)."""
    return not after.strip() or bool(_NEXT_CAPITAL.match(after) and not _NOT_A_NEW_SENTENCE.match(after))


def _classify(raw: str, dot: bool, before: str, after: str):
    """(word to say, may end a sentence) for an abbreviation in its context, else None."""
    number_after = re.match(r'\s*(?:#\s*)?' + NUMBER_WORD, after)
    cap_after = _NEXT_CAPITAL.match(after)
    # A street word or a title (St., Dr., Mt., Ft.): the context decides which.
    title, place = _lookup(TITLES, raw), _lookup(PLACES, raw)
    if place and (dot or place not in DOTTED_PLACES) and _name_before(before) and (
            not title or _place_sense(before, after)):
        if not dot and place == 'Pt' and number_after:
            place = None
        else:
            return PLACES[place], True
    if title and TITLES[title] and (dot or title in BARE_TITLES) and not re.match(r'\s*\n', after) and (cap_after or (
            title in LOOSE_TITLES and dot and re.match(r'\s', after))):
        return TITLES[title], False
    key = _lookup(SUFFIXES, raw)
    if key and (dot or _NAME_BEFORE.search(before.rstrip(', ') + ' ')) and re.search(r"[A-Za-z'’],?\s+$", before):
        return SUFFIXES[key], False     # "King Jr. Day": a name goes on after it more often than a sentence
    if raw.lower() in ('c', 'ca', 'cir', 'circ') and dot and (raw.islower() or re.match(r'\s*' + YEAR_WORD, after)) \
            and re.match(r'\s*' + NUMBER_WORD, after) and not re.search(NUMBER_WORD + r'[ \t]*$', before):
        return 'circa', False           # "c. 1900", "ca. 1850s", "C. 1900, the mill": circa, never the letter c
    if raw.lower() == 'sec' and re.match(r'\.?[ \t]+dep\b', after, re.I):
        return 'security', False        # "sec. dep." security deposit
    if raw.lower() == 'dep' and dot and re.search(r'\bsec\.?[ \t]+$', before, re.I):
        return 'deposit', True
    key = _lookup(BEFORE_NUMBER, raw)
    if key and (dot or key in BARE_BEFORE_NUMBER) and number_after and raw[:1] == key[:1]:
        return BEFORE_NUMBER[key], False
    if raw in AFTER_ORDINAL and re.search(r'\b' + ORDINAL_WORD + r'\s+$', before):
        return AFTER_ORDINAL[raw], True
    key = _lookup(BETWEEN, raw)
    if key and dot and cap_after and _NAME_BEFORE.search(before):
        return BETWEEN[key], False
    if raw in STATES and not dot and re.search(r'\b[A-Z][A-Za-z.\'’-]+,\s*$', before) and len(raw) == 2 and (
            not after.strip() or re.match(r'\s*(?:[,.;:!?)·|/•\n-]|\s' + NUMBER_WORD + r'|\s+[a-z])', after)):
        return STATES[raw], True
    if raw in STATES and dot and re.search(r'\b[A-Z][A-Za-z.\'’-]+,\s*$', before):
        return STATES[raw], True
    if raw in COMPASS:
        street = r'(?:' + '|'.join(sorted(set(PLACES) | set(PLACES.values()), key=len, reverse=True)) + r')\b'
        # Before a street's name: "N. Main St.", "12 W 4th St", "W Elm Ave"; after a street word: "Pine Ave NE".
        if re.match(r'\s+(?:[A-Z][\w\'’]*|' + ORDINAL_WORD + r')(?:\s+[A-Z][\w\'’]*)?\.?\s+' + street, after) or (
                (dot or re.search(NUMBER_WORD + r'\s+$', before)) and re.match(
                    r'\s+(?:[A-Z][a-z]|' + ORDINAL_WORD + ')', after) and len(raw) == 1 and dot):
            return COMPASS[raw], False
        if len(raw) == 2 and re.search(r'\b' + street + r'\.?,?\s+$', before):
            return COMPASS[raw], True
    key = raw if raw in WORDS else raw.lower() if raw.lower() in WORDS and raw.lower() in BARE_WORDS and (
        raw.isupper() or raw[0].isupper()) and raw.lower() not in COUNTED_WORDS and len(raw) > 2 else None
    if key is None and raw.isupper() and len(raw) > 2:
        key = raw[0] + raw[1:].lower() if raw[0] + raw[1:].lower() in WORDS else None
    if key and (dot or key in BARE_WORDS):
        if key in COUNTED_WORDS and not re.search(r'(?:\b(?:a|an|per|each)|' + NUMBER_WORD + r'|dollars?|cents?)\s*$',
                                                   before, re.I):
            return None
        if (key in ('FT', 'PT') or key in UNITS or key.lower() in UNITS) and re.search(NUMBER_WORD + r'\s*$', before):
            return None                 # "6 FT", "5 min.": a unit after its number is numbers.py's
        word = WORDS[key]
        if key in COUNTED_WORDS and re.search(r'\b(?:a|an|per|each|one)\s*$', before, re.I) and word.endswith('s'):
            word = word[:-1]
        if key in ('incl', 'excl') and re.match(r'\s*(?:[,;:!?)·|•/]|\.?\s*$|\.\s+[A-Z])', after):
            word = word[:-3] + 'ed'     # "utilities incl." included; "incl. water" including
        return word, key not in LEADING_WORDS and not (key in ORG_WORDS and _org_goes_on(after))
    return None


def _token(m: re.Match) -> str | None:
    raw, dot = m.group('tok'), bool(m.group('dot'))
    before, after = m.string[:m.start()], m.string[m.end():]
    if raw.endswith(' al') and raw != 'et al':
        return None
    found = _classify(raw, dot, before, after)
    if not found:
        return None
    word, can_end = found
    word = _cap(word, raw, _sentence_start(before))
    if dot and can_end and ends_sentence(after):
        word += '.'                     # the abbreviation ended the sentence: the voice still stops there
    if dot and word in ('for example', 'that is', 'namely', 'compare', 'note') and not re.match(r'\s*,', after):
        word += ','
    return word


def abbreviation_period(before: str, after: str | None = None) -> bool | None:
    """For the period that ends ``before``: True when it is only an abbreviation's (no sentence ends there), False
    when it is an abbreviation's that also ends the sentence (``after`` starts a new one), None when no abbreviation
    in the table ends there. Units are numbers.py's and never counted here."""
    m = re.search(r"(?<![\w.@/&’-])(?<![\w.]')([A-Za-z]+(?:\.[A-Za-z]+)*(?:/[A-Za-z]+)?)\.$", before)
    if not m:
        return None
    if re.search(r'\b(?:sq|cu|fl)\.$', before):
        return True                     # "850 sq. ft": the period inside a unit
    found = _classify(m.group(1), True, before[:m.start()], after if after is not None else ' x')
    if not found:
        return None
    if after is None:
        return True
    return not (found[1] and ends_sentence(after))


# ------------------------------------------------------------------ symbols, rates and separators
_SLASH_PER = re.compile(r'(?<=[a-z])\s?/\s?(?P<per>' + '|'.join(re.escape(k) for k in sorted(PER, key=len, reverse=True))
                        + r')\b(?:\.(?=\s+[a-z]|[,;:]))?')
_PER_WORD = re.compile(r'\b(?P<pre>per|a|an|each)\s+(?P<per>' + '|'.join(
    re.escape(k) for k in sorted((k for k in PER if k not in ('day', 'night', 'month', 'hour', 'week', 'year', 'person',
                                                              'unit', 'item', 'each', 'visit', 'session', 'class',
                                                              'ticket', 'head', 'household', 'family', 'couple',
                                                              'game', 'serving', 'slice', 'bag', 'box', 'dozen',
                                                              'ea', 'h')), key=len, reverse=True)) + r')\b(?:\.(?=\s+[a-z]))?')
_DAYS_OR_MONTHS = '(?:' + WEEKDAY_WORDS + '|' + MONTH_WORDS + ')'
FULL_NAMES = {n[:3].lower(): n for n in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
                                         'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                         'September', 'October', 'November', 'December')}


def _slash_per(m: re.Match) -> str:
    article, noun = PER[m.group('per')]
    return f' {article} {noun}' if article else f' {noun}'


def _plus(m: re.Match) -> str:
    """A plus sign: "and" between two plain words ("salt + pepper"), else "plus" ("12+", "2 + 2", "Ctrl + C")."""
    before, after = m.string[:m.start()], m.string[m.end():]
    prev = re.search(r'(\w+)$', before).group(1)
    if m.group().startswith((' ', '\t')) and re.match(r'\s+[a-z]', after) and not re.fullmatch(COUNT[:-2] + '|the|a|an', prev) \
            and (prev.islower() or _sentence_start(before[:-len(prev)])) and not re.fullmatch(r'\d+', prev):
        return ' and'
    return ' plus'


def _word(piece: str) -> bool:
    from .numbers import _english_words
    words = _english_words()
    return not piece.isupper() and (piece.lower() in words if words else len(piece) > 2)


def _slash_words(m: re.Match) -> str:
    """Words joined by slashes: days or months are a list ("Mon/Wed/Fri"), two facts with a number a list
    ("three bedrooms/two baths"), two plain words a choice ("his/her" his or her)."""
    parts = m.group().split('/')
    if all(re.fullmatch(_DAYS_OR_MONTHS + r'\.?', p) for p in parts):
        return ', '.join(FULL_NAMES.get(p.rstrip('.').lower()[:3], p) if len(p.rstrip('.')) <= 5 else p for p in parts)
    if len(parts) == 2 and re.match(NUMBER_WORD, parts[1]):
        return parts[0] + ', ' + parts[1]
    if len(parts) == 2 and parts[0].lower() == 'and' and parts[1].lower() == 'or':
        return 'and or'
    if len(parts) == 2 and all(_word(p) for p in parts):
        return ' or '.join(parts)       # "his/her", "rain/snow"; code ("src/app") and acronyms stay as written
    return m.group()


SYMBOLS = [
    # "dollars/mo" -> "dollars a month", "per lb" -> "per pound"
    (_SLASH_PER, _slash_per),
    (_PER_WORD, lambda m: m.group('pre') + ' ' + PER[m.group('per')][1]),
    # Day and month ranges: "Mon - Fri", "Jan–Mar" -> "to"
    (re.compile(r'\b(?P<a>' + _DAYS_OR_MONTHS + r')\.?\s*[-–]\s*(?=' + _DAYS_OR_MONTHS + r'\b)'),
     lambda m: m.group('a') + ' to '),
    (re.compile(r'(?<![\w/.:])[A-Za-z][a-z]+(?:/[A-Za-z][a-z]+)+(?![\w/:]|\.\w)'), _slash_words),
    (re.compile(r'[A-Za-z]+(?: [a-z]+)*/(?=' + NUMBER_WORD + ')'), lambda m: m.group()[:-1] + ', '),
    # Symbols in prose: "@ 7", "~5", "12+", "bread + butter", "±2", "§ 4", "©".
    (re.compile(r'(?<![\w.])@\s*(?=[\w$])'), 'at '),
    (re.compile(r'(?:~|≈|\bapprox\b)\s*(?=' + NUMBER_WORD + ')'), 'about '),
    (re.compile(r'(?<=\w)(?<!\+)\s*\+(?![\w+])'), _plus),
    (re.compile(r'\s*±\s*'), ' plus or minus '),
    (re.compile(r'§\s*'), 'section '),
    (re.compile(r'©\s*'), 'copyright '),
    (re.compile(r'[™®]'), ''),
    # Separators between listed facts: a short pause in speech ("3 bd | 2 ba · garage", "Open daily / free parking").
    (re.compile(r'[ \t]*(?:[,;][ \t]*)?(?:[ \t][·•|‖/]|[·•‖])[ \t]+|(?<![,:;])[ \t]+(?:-|–)[ \t]+(?=[\w$"“])'), ', '),
]


def say(text: str) -> list[tuple[int, int, str]]:
    """The abbreviations in ``text`` (spoken text: numbers are words) as (start, end, said) rewrites."""
    out = []
    for m in _TOKEN.finditer(text):
        said = _token(m)
        if said is not None:
            out.append((m.start(), m.end(), said))
    return out

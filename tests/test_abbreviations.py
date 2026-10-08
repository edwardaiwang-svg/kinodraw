"""Shorthand a customer pastes is said the way a careful announcer says it and captioned exactly as written
(kinodraw/lexicon.py, numbers.py units, speech._say). Every case is invented: none comes from a pool script."""
import pytest

from kinodraw import lexicon, numbers, speech
from kinodraw.engine import captions


def said(text):
    return speech.said_text(numbers.normalize(text, 'en').spoken, 'en')[0]


CASES = [
    # units of length, area, volume, weight, speed, temperature, time, data, power: plurals and singulars
    ('The trail is 12 km long and 1 km wide.', 'The trail is twelve kilometers long and one kilometer wide.'),
    ('The board is 2 ft by 1 ft.', 'The board is two feet by one foot.'),
    ('A 10-ft ladder and a 5-lb bag.', 'A ten-foot ladder and a five-pound bag.'),
    ('The yard is 300 sq yd and the farm is 40 ac.',
     'The yard is three hundred square yards and the farm is forty acres.'),
    ('Lot size 3 ha, house 2,400 sq. ft. with a 2-car garage.',
     'Lot size three hectares, house two thousand four hundred square feet with a two-car garage.'),
    ('Pour 750 mL of water and 1 L of milk.', 'Pour seven hundred fifty milliliters of water and one liter of milk.'),
    ('Fill a 5 gal bucket and a 1 qt jar.', 'Fill a five gallon bucket and a one quart jar.'),
    ('Use a 12 oz can and a 2 lb bag.', 'Use a twelve ounce can and a two pound bag.'),
    ('It weighs 1 kg and the pill is 200 mg.', 'It weighs one kilogram and the pill is two hundred milligrams.'),
    ('Speed 5 m/s, 120 bpm, 3000 rpm.',
     'Speed five meters per second, one hundred twenty beats per minute, three thousand revolutions per minute.'),
    ('Wind gusts of 30 kts were reported.', 'Wind gusts of thirty knots were reported.'),
    ('It was 98.6°F inside and -10°C outside.',
     'It was ninety-eight point six degrees Fahrenheit inside and minus ten degrees Celsius outside.'),
    ('Load time is 250 ms, then 3 secs of video.',
     'Load time is two hundred fifty milliseconds, then three seconds of video.'),
    ('The class runs 2 hrs, once a wk, for 6 mos.', 'The class runs two hours, once a week, for six months.'),
    ('He is 7 yrs old and she is 1 yr old.', 'He is seven years old and she is one year old.'),
    ('Internet speed 300 Mbps on a 5 GHz band.',
     'Internet speed three hundred megabits per second on a five gigahertz band.'),
    ('A 60 W bulb uses 2 kWh a day.', 'A sixty watt bulb uses two kilowatt hours a day.'),
    ('The engine makes 300 hp and each bar has 250 cal.',
     'The engine makes three hundred horsepower and each bar has two hundred fifty calories.'),
    ('Area 40 m², volume 1 fl oz.', 'Area forty square meters, volume one fluid ounce.'),
    # kitchen measures
    ('Add 3 tbsp oil and 1 tsp salt.', 'Add three tablespoons oil and one teaspoon salt.'),
    ('Stir in 2 T butter and 1 t vanilla.', 'Stir in two tablespoons butter and one teaspoon vanilla.'),
    ('Whisk 1 1/2 c. sugar with 3/4 c milk.', 'Whisk one and a half cups sugar with three quarters of a cup milk.'),
    ('Fold in 1/2 tsp baking soda.', 'Fold in half a teaspoon baking soda.'),
    ('Makes 2 doz. Eggs $5/doz.', 'Makes two dozen. Eggs five dollars a dozen.'),
    # listings and classified ads
    ('For sale: 4BR/3BA home, 3,200 sqft, hdwd flrs, nr schools.',
     'For sale: four bedrooms, three baths home, three thousand two hundred square feet, hardwood floors, near '
     'schools.'),
    ('Cozy 1 bd studio, furn., util. incl., avail. now.',
     'Cozy one bedroom studio, furnished, utilities included, available now.'),
    ('Rent $950/mo, dep. req., refs req., N/S.',
     'Rent nine hundred fifty dollars a month, deposit required, references required, non-smoking.'),
    ('2-story house w/ bsmt, W/D, D/W, A/C.', 'two-story house with basement, washer and dryer, dishwasher, AC.'),
    ('Bike in exc. cond., orig. owner, $200 OBO.',
     'Bike in excellent condition, original owner, two hundred dollars or best offer.'),
    ('2.5 BA, 1 BR.', 'two and a half baths, one bedroom.'),
    ('Box of 100 ct, 12 pcs, 6 pk.', 'Box of one hundred count, twelve pieces, six packs.'),
    ('Tutoring $40/hr, $35 per session, honey $12 per lb.',
     'Tutoring forty dollars an hour, thirty-five dollars per session, honey twelve dollars per pound.'),
    ('Room $120/night, coffee $3 ea.', 'Room one hundred twenty dollars a night, coffee three dollars each.'),
    # titles and honorifics
    ('Meet Mr. Tanaka, Mrs. Ortiz and Ms. Kim at noon.', 'Meet Mister Tanaka, Missus Ortiz and Miz Kim at noon.'),
    ('Mx. Rivera and Prof. Adams teach here.', 'Mix Rivera and Professor Adams teach here.'),
    ('Rev. Green led the service with Fr. Paul.', 'Reverend Green led the service with Father Paul.'),
    ('Lt. Diaz and Sgt. Mills reported to Col. Reyes.',
     'Lieutenant Diaz and Sergeant Mills reported to Colonel Reyes.'),
    ('Pres. Grant, Gov. Brown, Sen. Ruiz and Capt. Hook.',
     'President Grant, Governor Brown, Senator Ruiz and Captain Hook.'),
    ('Det. Shaw called Atty. Brooks.', 'Detective Shaw called Attorney Brooks.'),
    ('Martin Luther King Jr. Day is a holiday.', 'Martin Luther King Junior Day is a holiday.'),
    ('Paul Novak Sr. founded the shop. Tell Mr Jones.', 'Paul Novak Senior founded the shop. Tell Mister Jones.'),
    # street and place words, compass points, states
    ('Turn left on Maple Ave. and right on Birch Ln.', 'Turn left on Maple Avenue and right on Birch Lane.'),
    ('The office is at 88 Harbor Blvd, Ste 4.', 'The office is at eighty-eight Harbor Boulevard, suite four.'),
    ('Take Hwy 17 to Oak Ridge Pkwy.', 'Take Highway seventeen to Oak Ridge Parkway.'),
    ('The park is on Willow Ct. near Cedar Cir.', 'The park is on Willow Court near Cedar Circle.'),
    ('Meet at Lincoln Sq. by the Union Sta.', 'Meet at Lincoln Square by the Union Station.'),
    ('He lives at 9 E Elm St, Apt 2.', 'He lives at nine East Elm Street, apartment two.'),
    ('Our shop is at 210 S. Front St.', 'Our shop is at two hundred ten South Front Street.'),
    ('12 W 4th St is here.', 'twelve West fourth Street is here.'),
    ('Pine Ave NE is closed.', 'Pine Avenue Northeast is closed.'),
    ('Mail it to Boise, ID 83702.', 'Mail it to Boise, Idaho eight three seven zero two.'),
    ('Our new office is in Denver, CO.', 'Our new office is in Denver, Colorado.'),
    ('Visit Ft. Worth, then Mt Vernon.', 'Visit Fort Worth, then Mount Vernon.'),
    # business and organisation words
    ('Acme Inc. hired Bolt Bros. and Delta Corp.', 'Acme Incorporated hired Bolt Brothers and Delta Corporation.'),
    ('The Parks Dept. and the Natl. Weather Svc. agree.',
     'The Parks Department and the National Weather Service agree.'),
    ('Smith & Co. sells hats.', 'Smith and Company sells hats.'),
    ('Ask the asst. mgr or the dept head about the mtg.',
     'Ask the assistant manager or the department head about the meeting.'),
    ('Attn: Billing Dept.', 'Attention: Billing Department.'),
    ('Min. order 2.', 'Minimum order two.'),
    # words before a number
    ('See Vol. 2, Ch. 5, Fig. 3 on p. 41.', 'See volume two, chapter five, figure three on page forty-one.'),
    ('Read pp. 12-15 before class.', 'Read pages twelve to fifteen before class.'),
    ('Est. 1962, Tel. 555-0182.', 'Established nineteen sixty-two, phone five five five, oh one eight two.'),
    ('The castle was built c. 1200.', 'The castle was built circa twelve hundred.'),
    # Latin shorthand
    ('Bring snacks, drinks, etc. and chairs.', 'Bring snacks, drinks, et cetera and chairs.'),
    ('Fruits (e.g., apples) and roots (i.e., carrots) grow here.',
     'Fruits (for example, apples) and roots (that is, carrots) grow here.'),
    ('Cats vs. dogs: who wins?', 'Cats versus dogs: who wins?'),
    ('It costs approx. $20.', 'It costs approximately twenty dollars.'),
    ('The Jones et al. study found it.', 'The Jones and others study found it.'),
    ('Roe v. Wade was decided long ago.', 'Roe versus Wade was decided long ago.'),
    ('Smith, a.k.a. the Big Guy, won.', 'Smith, also known as the Big Guy, won.'),
    # dates, weekdays, hours
    ('Open Tue - Sat 10-6.', 'Open Tuesday to Saturday, ten to six.'),
    ('Closed Mon/Tue, open Wed/Thu/Fri.', 'Closed Monday, Tuesday, open Wednesday, Thursday, Friday.'),
    ('Hours: Mon.–Fri. 8am-6pm', 'Hours: Monday to Friday, eight AM to six PM'),
    ('Due 3/15/2027 by 5pm.', 'Due March fifteenth twenty twenty-seven by five PM.'),
    ('Deadline is Fri 9/26.', 'Deadline is Friday September twenty-sixth.'),
    ('Sign up by 10/3.', 'Sign up by October third.'),
    # symbols in prose
    ('Doors @ 7pm, show @ 8.', 'Doors at seven PM, show at eight.'),
    ('Ages 18+ only, 50+ vendors.', 'Ages eighteen plus only, fifty plus vendors.'),
    ('Salt + pepper, 2 + 2 is 4.', 'Salt and pepper, two plus two is four.'),
    ('Ships in ~3 days, ±2 days.', 'Ships in about three days, plus or minus two days.'),
    ('See § 4 of the rules.', 'See section four of the rules.'),
    ('Pick his/her seat, rain/snow.', 'Pick his or her seat, rain or snow.'),
    # separators between facts: short pauses
    ('Free parking · live music · food trucks', 'Free parking, live music, food trucks'),
    ('Open daily | Free entry | All ages', 'Open daily, Free entry, All ages'),
    ('Pickup 9am / Dropoff 5pm', 'Pickup nine AM, Dropoff five PM'),
    ('Fresh bread - local honey - farm eggs', 'Fresh bread, local honey, farm eggs'),
    ('3 bd | 2 ba | 1,200 sqft · garage',
     'three bedrooms, two baths, one thousand two hundred square feet, garage'),
]

# Left as written: context the rule does not apply in (the voice reads these right on its own).
NEGATIVES = [
    'MADE IN USA. Check IN at the front desk.',     # capitalised real words: not Indiana
    'Tea OR coffee, ME first, IT support.',         # state codes outside "Town, ST"
    'See the FAQ, bring your ID and a USB drive.',  # acronyms said as letters
    'The min is low, put it in the box.',           # unit abbreviations without a number
    'Say no. Never sat down. The sun is up.',
    'Email jo.smith@example.com today.',
    'Run cd src/app then open lib/main.py.',        # code text
    'The store is open 24/7.',
]


@pytest.mark.parametrize('text,expected', CASES)
def test_shorthand_is_said_in_full(text, expected):
    assert said(text) == expected


@pytest.mark.parametrize('text', [t for t, _ in CASES] + NEGATIVES)
def test_captions_show_the_text_as_written(text):
    norm = numbers.normalize(text, 'en')
    assert norm.display == text and speech.caption_text(text) == text
    # display and spoken share their clause breaks, so the caption words keep their measured times
    assert len(captions.clause_marks(text, 'en')) == len(captions.clause_marks(norm.spoken, 'en'))
    assert norm.to_spoken(len(text)) == len(norm.spoken)


@pytest.mark.parametrize('text,expected', [
    ('MADE IN USA. Check IN at the front desk.', 'MADE IN USA. Check IN at the front desk.'),
    ('Tea OR coffee, ME first, IT support.', 'Tea OR coffee, ME first, IT support.'),
    ('See the FAQ, bring your ID and a USB drive.', 'See the FAQ, bring your ID and a USB drive.'),
    ('The min is low, put it in the box.', 'The min is low, put it in the box.'),
    ('Say no. Never sat down. The sun is up.', 'Say no. Never sat down. The sun is up.'),
    ('Email jo.smith@example.com today.', 'Email jo dot smith at example dot com, today.'),
    ('Run cd src/app then open lib/main.py.', 'Run cd src/app then open lib/main.py.'),
    ('The store is open 24/7.', 'The store is open twenty-four seven.'),
    ('Portland, OR 97201 or Tea OR milk.', 'Portland, Oregon nine seven two zero one or Tea OR milk.'),
])
def test_context_leaves_real_words_alone(text, expected):
    assert said(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('St. Mary and Dr. Patel met on Elm St. near Oak Dr. today.',
     'Saint Mary and Doctor Patel met on Elm Street near Oak Drive today.'),
    ('Meet Dr. Patel at 42 Oak Dr. on Main St.', 'Meet Doctor Patel at forty-two Oak Drive on Main Street.'),
    ('Pickup is on Quarry Rd. Bring bags.', 'Pickup is on Quarry Road. Bring bags.'),
    ('Turn at 5th Ave. Then left.', 'Turn at fifth Avenue. Then left.'),
    ('It is on Elm St. Bring a friend.', 'It is on Elm Street. Bring a friend.'),
])
def test_saint_or_street_and_doctor_or_drive_by_context(text, expected):
    assert said(text) == expected


def test_an_abbreviation_period_is_a_sentence_end_only_where_one_ends():
    # "Dept. of" goes on; "Elm St. Bring" ends a sentence: the captions break there and the voice pauses there.
    assert lexicon.abbreviation_period('the Parks Dept.', ' of Health') is True
    assert lexicon.abbreviation_period('on Elm St.', ' Bring a bag.') is False
    assert lexicon.abbreviation_period('Ask Dr.', ' Lee now.') is True
    assert lexicon.abbreviation_period('a big tree.', ' It fell.') is None
    text = 'Meet us on Elm St. Bring a bag to the Parks Dept. of Health.'
    marks = [m.start() for m in captions.clause_marks(text, 'en')]
    assert text.index('St.') + 2 in marks and text.index('Dept.') + 4 not in marks
    stops = {pos for pos, gap, _, _ in speech.pace(text)}
    assert text.index('Bring') in stops and text.index('of Health') not in stops


def test_units_come_from_the_lexicon():
    assert numbers.UNITS['sq ft'] == 'square feet' and lexicon.UNITS['ft'] == ('foot', 'feet')
    assert said('Only 1 sq ft.') == 'Only one square foot.'

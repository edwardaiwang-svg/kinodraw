# Creature presets (2026-10-07)

Generated offline by `scripts/gen_creatures.py` (code in `kinodraw/library/creaturegen/`), written to
`kinodraw/assets/doodles/creatures/` with tags in `kinodraw/assets/doodles/tags/creatures.json`.
Resolver: `kinodraw.library.creatures.best_preset(species, age, sex, pose, facing, marks, variant, expression)`.

Ids: `cr_<species>_<sex>_<age>[_<variant>]_<pose>_<facing>`; facing `r`/`l` (full body) or `f` (front
head close-up `face_<neutral|scared|determined|sad|happy>`). Each look's resting picture (stand, or swim1
for fish) facing right is its one searchable picture; every other pose is reached by id or the resolver.
Carry poses record a `carry` anchor; quadrupeds also record `scruff` (where a parent's mouth holds a cub).

Milestone 1 (commit a63fd6a): lions + jungle cast. King Kojo = `cr_lion_male_adult_blackmane_scar_*`,
lioness = `cr_lion_female_adult_*`, Pendo = `cr_lion_any_young_*`, plus elephant and calf, gorilla, chimpanzee,
monkey, red-eyed tree frog, black and red ants, hyena, porcupine.

| family | presets | looks |
|---|---|---|
| big_cat (lions, tiger, white tiger, leopard, black panther, cheetah, 4 house cats, kitten) | 486 | 18 |
| canine (5 dog breeds, puppy, wolf, red fox) | 216 | 8 |
| hyena | 27 | 1 |
| bear (brown, black, polar, panda) | 108 | 4 |
| primate (gorilla, chimpanzee, monkey) | 81 | 3 |
| elephant (adult, calf) | 54 | 2 |
| hoofed (giraffe, zebra, 4 horses, foal, stag, doe, fawn, antelope, 2 cows, calf, pig, sheep, lamb, goat) | 484 | 18 |
| rodent (3 rabbits, mouse, porcupine) | 135 | 5 |
| bird (4 songbirds, 2 owls, eagle, 2 parrots, hen x2, rooster, chick, 2 ducks, duckling, penguin, penguin chick, flamingo) | 505 | 19 |
| amphibian (tree frog) | 25 | 1 |
| reptile (turtle, 2 snakes, crocodile) | 86 | 4 |
| fish (goldfish, clownfish, blue tang, shark) | 76 | 4 |
| insect (2 ants, bee, ladybug, green beetle, 2 butterflies) | 135 | 7 |
| human, category "characters" (king, queen, old king, villagers, teachers, explorers, boy, girl, princess, grandparents; 3 skin tones each) | 1305 | 45 |
| **total** | **3723** | |

All pass `kinodraw.library.check` (creatures/fluent rules, no warnings).

Regenerate: `python scripts/gen_creatures.py` (contact sheets: `--out /tmp/cr --sheets /tmp/cr/sheets`).
Verify the committed files: `python scripts/gen_creatures.py --check`.
After changing creature names, rebuild the search bundles: `python -m kinodraw.director.match`.

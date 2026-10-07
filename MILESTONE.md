# Creature presets — milestone 1: lions + jungle cast (2026-10-07)

Generated offline by `scripts/gen_creatures.py` (code in `kinodraw/library/creaturegen/`), written to
`kinodraw/assets/doodles/creatures/` with tags in `kinodraw/assets/doodles/tags/creatures.json`.
Resolver: `kinodraw.library.creatures.best_preset(species, age, sex, pose, facing, marks, variant, expression)`.

Ids: `cr_<species>_<sex>_<age>[_<variant>]_<pose>_<facing>`; facing `r`/`l` (full body) or `f` (front
head close-up `face_<neutral|scared|determined|sad|happy>`). Body poses for four-legged animals:
stand, walk1, walk2, run, sit, lie, sleep, roar, look_up, scared, carry (carry presets record a `carry`
anchor; quadrupeds also record a `scruff` anchor so a cub can hang from a parent's mouth).

| Character | id prefix | presets |
|---|---|---|
| King Kojo (black mane + nose scar) | `cr_lion_male_adult_blackmane_scar_` | 27 |
| other male lions (golden / dark / black mane, with or without scar) | `cr_lion_male_adult[_darkmane][_blackmane][_scar]_` | 135 |
| lioness | `cr_lion_female_adult_` | 27 |
| Pendo, lion cub (oversized paws, baby face) | `cr_lion_any_young_` | 27 |
| elephant / baby elephant | `cr_elephant_any_adult_`, `cr_elephant_any_young_` | 54 |
| gorilla, chimpanzee, monkey | `cr_gorilla_any_adult_`, `cr_chimpanzee_any_adult_`, `cr_monkey_any_adult_` | 81 |
| red-eyed tree frog | `cr_frog_any_adult_tree_` (stand walk1 walk2 jump sit lie sleep roar=croak look_up scared) | 25 |
| black ant, red ant | `cr_ant_any_adult_black_`, `cr_ant_any_adult_red_` | 46 |
| hyena, porcupine | `cr_hyena_any_adult_`, `cr_porcupine_any_adult_` | 54 |

Total: 476 presets, all passing `kinodraw.library.check` (creatures/fluent rules).

Contact sheets (this session's scratchpad):
- lion cast: `/private/tmp/claude-501/-Users-edwardai/17c51340-5cc3-4775-97c1-6064073c1738/scratchpad/q-creatures/lion_cast.png`
- per character: `.../scratchpad/q-creatures/sheets_m1/*.png`
- whiteboard renderer still: `.../scratchpad/q-creatures/whiteboard_still.png`

Regenerate sheets: `python scripts/gen_creatures.py --out /tmp/cr --sheets /tmp/cr/sheets`.
Verify the committed files: `python scripts/gen_creatures.py --check`.

Open: the bundled search embeddings (`assets/doodles/{embed,picture}-*.npz`) are rebuilt at the end of
the run (`python -m kinodraw.director.match`); until then the app recomputes them once on first search.

---
name: vocabulary-pack-creator
description: Create, extend or review Goated Prompter vocabulary packs: one JSON file per pack, in its category's folder, with exactly a name, a category and a list of entries.
---

# Goated Prompter — Vocabulary Pack Creator

## What a pack is

A pack is one JSON file in a category folder under `vocabulary/` (shipped with the app, general content only) or under
`data/vocabulary/` (the user's own packs, added with **Import packs** on the Vocabulary tab; their id starts with
`data/`). The user selects packs by hand in the Dataset tab's Vocabulary Library; the scene writer then gets their
entries, grouped under the category's Core instruction and shuffled by the run's seed. A pack has no logic.

```json
{
  "name": "Fantasy",
  "category": "Spaces",
  "entries": ["enchanted forest", "ancient dragon temple", "floating castle"]
}
```

- Exactly `name`, `category` and `entries`, nothing else.
- `category` must be the folder's registered category (`vocabulary/Spaces/Fantasy.json` → `"Spaces"`). The
  `Objects` folder holds `"Objects & Props"`: every thing in a scene (tools, toys, kitchenware, vehicles,
  buildings seen in the scene, restraints, and text: words or marks printed, written or drawn on things or skin).
- `entries`: 1–2000 non-empty texts of up to 300 characters; repeats (ignoring case) count once.
- File name: words joined by hyphens (`Solo-Activities.json`); the pack id is `<folder>/<file name>`.

## Categories

`vocabulary/core/` holds exactly three files:

- `scene_category_registry.json`: which categories exist and their folders (the source of truth).
- `category_definitions.json`: what each category means and when it is useful.
- `prompt_instructions.json`: what the scene writer is told about that category's vocabulary.

A new category is one entry in each of the three files plus its folder. Do not add categories or Core files unless
asked.

## Writing entries

- One idea per entry, named the way a person would say it ("arched back", "rim lighting").
- Keep a pack to one category and one theme.
- `Actions & Poses` holds what subjects do and how they are positioned. An entry can define both ("one person on all
  fours, the other person kneeling behind them"), only the action ("one person giving the other person a massage")
  or only the pose ("the person posing with an arched back"); the scene writer keeps a defined pose with its action
  and picks a fitting one when it is missing. When an action only makes sense in one arrangement, write both in one
  entry.
- Name people "the person" (solo), "one person" and "the other person" (couples) or "a group", never "partner" or a
  gender: the scene writer replaces them with the scene's characters and their gender. Objects and surfaces in an
  entry ("on the floor", "over a table", "a toy") are examples it adapts to the scene's space.
- With an `Actions & Poses` pack selected, every scene names the entry it uses and no entry is used by more than two
  images, so a pack needs enough distinct entries for the batch sizes it is used with.
- `Subjects/Humans` holds people's looks (skin, build, hair, one detail). It is used only when selected, and never
  for a known character, whose look comes from its name.
- Keep adult content out of `vocabulary/`; it belongs in the user's own imported packs.
- Every person is an adult.

## Checks

Follow the repository's `AGENTS.md`. Validate packs through the real loader:

```powershell
python -m unittest tests.unit.vocabulary.test_vocabulary_catalog
python -c "from goated_prompter.features.vocabulary.catalog import load_catalog; print(load_catalog()['problems'])"
```

Report the pack id, entry count, the files changed and what was tested. Do not commit, push or run GPU inference
without authorization.

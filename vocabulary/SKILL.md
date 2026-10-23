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

- `name`, `category` and `entries`, plus an optional `description` (1–300 characters) and an optional `people`,
  nothing else. The description
  says what the pack is for and how its entries are written ("adult men with heavy muscle; entries already describe
  men"); the scene writer reads it with the pack's entries, and it never overrides the request or the run's settings.
- `category` must be the folder's registered category (`vocabulary/Spaces/Fantasy.json` → `"Spaces"`). The
  `Objects` folder holds `"Objects & Props"`: every thing in a scene (tools, toys, kitchenware, vehicles,
  buildings seen in the scene, restraints, and text: words or marks printed, written or drawn on things or skin).
- `entries`: 1–2000 non-empty texts of up to 300 characters; repeats (ignoring case) count once.
- File name: words joined by hyphens (`Solo-Activities.json`); the pack id is `<folder>/<file name>`.

### Optional: how many people an entry needs

A pack of plain texts works as it is. When entries need a certain number of people, say so and a run never offers an
entry to a cast that is too small (a solo request never gets an entry that needs a second person):

```json
{
  "name": "Couple Dances",
  "category": "Actions & Poses",
  "people": 2,
  "entries": ["two people waltzing", {"text": "the person bowing to the room", "people": 1}]
}
```

- `people` on the pack (1–20) applies to every entry; `{"text": ..., "people": n}` gives one entry its own count.
- An entry with no count is offered to every cast.

### Optional: slots that link two packs

An entry may name another pack or a category in square brackets, so one entry can join a pose with a prop; the scene
writer takes a fitting entry from the named pack:

- `"kneeling by the table, holding [Kitchen-and-Dining]"`: an entry of that pack.
- `"seated in [Objects & Props]"`: an entry of any selected pack of that category.
- `"seated in [Furniture: armchair]"`: one of that pack's entries containing "armchair".

Names ignore case, spaces, hyphens and "&" written as "and", so the pack's file name works as well as its name
(`[Kitchen-and-Dining]` is the pack named "Kitchen & Dining"). The pack or category must be selected in the run: an entry whose slot names a pack or category that is not selected,
or whose words match none of its entries, is never used. Slots work in every category, not only objects. The
Vocabulary Library shows a pack's linked packs so they can be selected together. Entries without brackets are
unchanged.

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
- `Actions & Poses` holds what subjects do and how they are positioned. An entry can define both, only the action or
  only the pose; the scene writer keeps a defined pose with its action and picks a fitting one when it is missing.
  When an action only makes sense in one arrangement, write both in one entry.

### Actions & Poses entries for two or more people

Write each entry as one complete arrangement in one fixed shape, so it is short, easy to check and easy to keep:

```text
[position name: ]A <position>; B <where B is, relative to A>; C <where C is>; <what happens, part by part>
```

```text
waltz turn: A standing, leaning back in B's arms; B standing facing A, one hand at A's waist; C standing behind A, holding A's raised hand
```

1. **Letters for people.** A is the person the act centres on; B and C are placed relative to A. Never "his", a
   gender, "partner" or "the other one": every body part names its owner's letter ("B's hand on A's waist"). The
   scene writer replaces the letters with the scene's characters.
2. **One entry per different act or arrangement, never per wording.** Two entries with the same act and the bodies
   placed the same way are one entry. A different arrangement is a different support, facing or reach (on all fours,
   lying on the back, bent over, standing, held up).
3. **No objects inside the act.** Write "a toy" or "a surface" instead of a named thing or a `[slot]`; the run's
   Objects & Props packs supply the actual thing for each image, so a new prop never needs a changed act.
4. **Plain anatomical words** for body parts, the same words the app's rules and checks use.
5. **One cast size per pack**: set `"people"` on the pack (a Threesome pack, a Couple pack), not on each entry. A pack
   that already mixes cast sizes keeps its file, so saved selections still find it: `"people"` on the pack for the
   most common size and `{"text": ..., "people": n}` only on the other entries.
6. **A name only when it is the position's real name.** The final prompt calls the position by the words before the
   colon, so write them only when people name that position that way (several entries may share it); otherwise start
   the entry with "A". A label that only describes the entry ("watch", "toy ride") would read as a position that does
   not exist.

Check each line before keeping it: in A's position, can B and C reach what the act says, with their own weight
supported? Older entries written with "one person" and "the other person" keep working.

- Name people in other categories "the person" (solo) or "a group", never a gender: the scene writer replaces them
  with the scene's characters and their gender. Surfaces in an entry ("on the floor", "over a table") are examples it
  adapts to the scene's space.
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

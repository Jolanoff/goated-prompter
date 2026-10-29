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

- `name`, `category` and `entries` (or `groups`, below), plus an optional `description` (1–300 characters), an optional `people` and,
  for a built-in pack, an optional `always`, nothing else. The description
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

- `people` on the pack (1–20) applies to every entry; `"people"` on a group applies to its entries instead; and
  `{"text": ..., "people": n}` gives one entry its own count.
- A run offers Actions & Poses entries made for exactly the cast's number of people (a pair gets entries for two, a
  group entries for a group), and an entry for fewer people only when the selected packs have none for the cast.
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

### Optional: groups, and always-on built-in packs

Instead of `entries`, a pack may hold `groups`: `{"group": "kitchen", "words": ["kitchen", "cooking", "baking"],
"entries": [...]}`, with up to 100 words. A search counts the group's words the request says, and the groups that
it says most often win. So every entry of a group must fit every one of its words ("laundry" never sits with a
garage; a word that names only some of a group's entries, like "attic" among bedrooms, belongs to none: meaning
finds the group and the entries it points to), and a word must not mean something else in a request ("film" grain, depth of "field", hair in "waves").
Each entry belongs to one group. `"worlds"` lists the worlds a group's entries fit (`everyday`, `historical`,
`fantasy`, `sci-fi`; every world when it gives none): a request in another world never gets them unless it names
them. `"shapes"` lists the image shapes a group's entries fit (`tall`, `square`, `wide`; every shape when it gives
none): a run with that aspect ratio never gets the others. `"kinds"` lists the kinds of character a group of looks
fits (`animal`, `creature`, `robot`, `object`; a group without kinds is people's looks). `"adult_default": true` marks a group for adult requests that name no place. Words find a group exactly; a
small embedding model also finds it by meaning, so a group's name and words should say plainly what its entries are.

A built-in pack with `"always": true` is used in every run, selected or not, after the user's selected packs of its
category (the `Spaces` places deal a place to every image, `Subjects/Female` and `Subjects/Male` a look to every
person whose looks vary, `Subjects/Non-Human` to every other character whose looks vary, `Camera &
Composition/Camera` a camera to every image). Always-on packs stay safe for work and keep entries
distinct: two entries never share most of their words. Do not add an always-on pack unless asked.

A Clothing pack made for one sex holds one group named `"female"` or `"male"` (with the words a person's stated sex
uses, such as "woman" or "man"), and its description starts with who it is for ("For female characters only: …"),
so a run dresses only the people of that sex from it and the scene writer reads which garments are whose. Garments
anyone wears go in both packs of a pair (`Clothing/Modern-Fashion-Female` and `-Male`).

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

Write each entry as one short act line, the way people say it, so the scene and the final prompt can keep its words
with only the people replaced:

```text
<who> <the act's everyday verb> <whom>[ in <position name>][, <only what the name does not already say>]
```

```text
B dipping A in a tango, A's back arched over B's arm
B and C lifting A between them, A's arms around their shoulders
```

1. **Letters for people.** A is the person the act centres on; B and C are placed relative to A. Never "his", a
   gender, "partner" or "the other one": every body part names its owner's letter ("B's hand on A's waist"). The
   scene writer replaces the letters with the scene's characters. An entry that opens with everyone ("A and B ...,
   each ...") is a shared act; one that then names a letter alone ("..., B holding ...") or "the others" gives that
   person their own part. A request in which one character acts on another only gets entries of the second kind.
   A detail after a shared act ("A and B walking side by side, A turning their head toward B") gives no one their own
   part. Entries place people; a group that also places animals or other beings lists them in `"kinds"`, as the
   Subjects groups do. Name the gear an act needs ("each holding a paddle"): a request that names its gear only gets
   entries that say it.
2. **One entry per different act or arrangement, never per wording.** Two entries with the same act and the bodies
   placed the same way are one entry. A different arrangement is a different support, facing or reach (on all fours,
   lying on the back, bent over, standing, held up).
3. **No objects inside the act.** Write "a toy" or "a surface" instead of a named thing or a `[slot]`; the run's
   Objects & Props packs supply the actual thing for each image, so a new prop never needs a changed act.
4. **Everyday words** for the act, the position and the body parts, the ones people use and image models know;
   never rewrite an act into how the bodies fit together. The final prompt keeps them. Say an act done with a mouth
   from the person whose mouth it is ("A kissing B's hand"): said from the other person, image models draw two faces
   meeting.
5. **One cast size per pack or group**: set `"people"` on the pack (a Threesome pack, a Couple pack), or on a group
   when one pack holds several sizes (solo drills and partner sparring), not on each entry. A pack that already mixes
   cast sizes keeps its file, so saved selections still find it: `"people"` on the pack for the most common size and
   `{"text": ..., "people": n}` only on the other entries.
   Group a pack's entries by the act they show (`"group"`, `"words"`, `"entries"`): a request's action words find the
   group, and every word must fit every entry of it ("dancing" for the dances, never "bicycle" for a group where only
   one entry has a bicycle). A plain list still works: a request's action words then find the entries that say them.
6. **A name only when it is the position's real name** ("in a tango"): image models know a position by its name, so
   the name replaces describing the pose, and the line adds only what the name leaves open. Write a name only when
   people call that position that way; a label that only describes the entry ("watch", "toy ride") would read as a
   position that does not exist. Older entries written as `name: A <position>; B <where B is>; <what happens>` keep
   working.
7. **Say which hand holds a thing the act uses.** When someone moves, pushes, pulls or strikes with something they
   hold, write "with one hand" ("B brushing A's hair with a comb in one hand"); a hand the entry leaves out
   gets placed somewhere else, and the thing then moves on its own.

Check each line before keeping it: in A's position, can B and C reach what the act says, with their own weight
supported? Older entries written with "one person" and "the other person" keep working.

- Name people in other categories "the person" (solo) or "a group", never a gender: the scene writer replaces them
  with the scene's characters and their gender. Surfaces in an entry ("on the floor", "over a table") are examples it
  adapts to the scene's space.
- An `Objects & Props` entry names the thing and where it sits on a body or in the place ("leather cuffs on his
  wrists", "a lamp on the shelf"), never a pose, a piece of furniture it is fixed to or a moment before or after: it
  is dealt beside any image's Actions & Poses entry, and an entry with its own pose contradicts that image's pose.
- With an `Actions & Poses` pack selected, every scene names the entry it uses and no entry is used by more than two
  images, so a pack needs enough distinct entries for the batch sizes it is used with.
- `Subjects/Humans` holds people's looks (skin, build, hair, one detail). It is used only when selected, and never
  for a known character, whose look comes from its name. While a Subjects pack is selected, `Subjects/Female` and
  `Subjects/Male` deal no look. Each holds one group, `female` or `male`, found by a person's gender; a look in
  them is only hair (or a shaved head), then eyes and skin tone: build and marks come from the request. Write a look
  as its parts joined by "with" and "and", each ending in what it describes ("shaggy ginger hair with wide green eyes
  and fair skin"): a request fixes the parts it names and every other part varies.
- `Subjects/Non-Human` deals looks to the characters that are not humans (animals, creatures, robots) and whose looks
  vary, never to a known, named or locked one. Its groups share an anatomy and appearance (fur, natural feathers,
  bright feathers, scales, plating, smooth skin), never a species combination; a group's `kinds` say which characters
  it fits and its words are the animals and beings a request names for it ("wolf", "parrot", "robot"). An entry is
  four parts, each naming one thing: covering colour, its texture or markings, eyes or lights, build ("black fur
  with a short sleek coat and amber eyes and a lean build"). A colour part names one colour, so "a black cat" keeps
  black fur while the coat, eyes and build vary; a mix ("black and white") would let it change.
- `Camera & Composition/Camera` deals a camera to every image while no Camera & Composition pack is selected. An
  entry is a whole camera, "<shot> with <angle> and <view>", whose parts go together. The shot is one of the sizes
  `scenes/camera.py` defines for any subject (`extreme wide shot`, `wide shot`, `full shot`, `medium long shot`,
  `medium shot`, `close-up shot`), never named after a body: a live set of objects got a "head-and-shoulders shot".
  An angle is the camera's height ("low", "eye-level") and a view the side it looks from, never a body part either: a
  live writer read "waist-level" and "chest-level" as where the frame cuts the body. A group's words are the body positions its cameras show clearly ("lying", "sitting") or a word that
  always means several people ("team", "crowd"), never one any number can say ("friends"); a group whose only word is
  its name fits any pose. A group word never repeats a word of the cameras ("side by side" would stop "side view" from
  being asked for). Every group has enough cameras, several of them full body, that ten images rarely repeat one.
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

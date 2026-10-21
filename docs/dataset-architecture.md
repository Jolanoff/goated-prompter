# Dataset architecture

Dataset produces prompts, not images. The rebuilt workflow uses
`features/dataset/v2/understanding.py`, `scenes.py` and `prompts.py`:
Understanding → source-bound human confirmation → the scene writer (with any selected vocabulary) → final Builder prompts.
Scenes-only generation stops before Builder. This is the only Dataset workflow; the
earlier pipeline (ideas with scenes, per-scene actions, Continue, saved scene plans, durable
checkpoints, recent-idea history and the old private vocabulary file) has been retired.
Its files under `data/` are not read, changed or deleted; old fields in a saved Dataset draft
are dropped when the draft loads.

## Runs

Each requested image keeps its slot number through every stage. A run lives only in its job's result: each scene
is published as soon as it is written (stage `writing_scenes`), then each final prompt as it is written. Nothing is
saved to disk; the user copies, downloads or exports what to keep. Reload recovery, scene editing, per-image
regeneration and continuing a scenes-only run are not implemented.

Vocabulary (`features/vocabulary/catalog.py`): `vocabulary/core/scene_category_registry.json` is the source of
truth for the categories and their folders; `category_definitions.json` says what each means and
`prompt_instructions.json` what the scene writer is told about it. A pack is one JSON file in a registered folder,
exactly `{"name", "category", "entries": [texts]}`; its id is `<folder>/<file>`. Imported packs live in
`data/vocabulary/<folder>/<file>.json` with id `data/<folder>/<file>` (`POST /api/vocabulary/import` with
`{"filename", "content"}` checks one and saves it in its category's folder, replacing an earlier import of that file).
Each file is read on its own: one that cannot be read is reported with its reason and the others still load.
`GET /api/vocabulary/catalog` returns categories, packs and problems. Adding a category is one entry in each Core file
plus its folder. Packs carry no compatibility data.

Selection: the Dataset tab's Vocabulary Library selects packs by hand (search, category filter, preview,
Apply/Cancel); the selected ids are the draft's `vocabulary_packs`, saved with the other Dataset settings. They are
not part of the review signature, so changing them needs no new Understanding. Confirm checks them against the
catalog. Vocabulary is used only when scenes are invented (source `random`); with the user's own scene ideas
(`guided`) no vocabulary is sent and the selection is ignored.

Triggers (`v2/triggers.py`): the draft holds a list of up to 20 triggers, each `{text, kind, expand, start}`:
its type (character, style, outfit, object, other), whether code places its exact text (`off`), the model writes its
meaning (`on`) or both, and whether it goes first. Only the user knows what a token stands for, so nothing guesses it. A draft or brief from before the list reads its one trigger as an exact "other"
trigger.

Understanding (brief version 13) records the subject type, participant count, stated attributes, the central
activity, and what stays fixed and what varies. It never reads vocabulary. It links every character and outfit trigger (by
number) to exactly one person, the character's `triggers` (code checks it; a character trigger is one person, count 1),
and the review shows the link. Each character carries `known`: its looks come from its name or an
exact-text character trigger, so no step invents them. Version 9 to 12 briefs in saved runs stay readable.

Scenes (`v2/scenes.py`): the scene writer (`dataset_v2:scenes`, one call per batch of up to ten images) receives the
USER REQUEST, the EXISTING APPROVED REQUIREMENTS (rules, Understanding, style, and the capture when the style is Realistic) and, only when packs are selected, a
SELECTED VOCABULARY section: just the categories that have a selected pack, each with its Core instruction and the
entries of those packs (merged per category and shuffled for every batch by a generator seeded with the run's seed),
plus the shared vocabulary usage rules. A pack with a description (its author's note on what it is for and how its
entries are written) is listed under that note so it stays with its own entries; the Actions & Poses fitting call
sees the notes too. A note guides the choice of entries and never overrides the request or the settings. Each category sends a seeded sample of at most `VOCABULARY_SAMPLE` (40)
entries per batch, so a large pack never drowns the request. The request and the approved requirements always win. With an Actions & Poses
pack selected, one call first keeps only the entries that fit the request and the cast (`fitting_entries`, every entry
when that call fails); only those are offered and dealt, and with none the writer gets no Actions & Poses vocabulary.
Every scene names the entry it is built on (`entry`); code checks the entry is one of the fitting ones and that no
entry is used by more than two images (`ENTRY_CAP`, raised to the images-per-entry when fewer entries fit than images
are requested), and asks again otherwise. Every other selected category deals each image `HAND` (3) suggested
entries from a seeded deck, without repeats until the whole category has been dealt (`deal_hands`), so the
vocabulary spreads over the set. In a category with entries about something the request names (they share a word
with it that is rare in that category, `requested_entries`): when the request names only that thing, every image gets
only the entry it names (`named_entries`); when it also names the category or one of its packs (it asks for the kind in
general), every image gets one of those entries and one other; suggestions are optional: the writer uses the ones that fit the image, or none,
and never adds a subject or object only to use one. No pack is used automatically: character looks come from the request
and approved requirements, with vocabulary guidance only from manually selected Subjects packs. A known character has
only an expression in its scene; its look comes from its name, never from the writer or vocabulary.
A scene holds only the people and their arrangement: subjects, actions, position, space, camera and extras. Each
position line places its person in the frame relative to the others and names the owner of every body part by
label, and says which body parts the camera can see; the final prompt describes a body part only when it is visible
(not turned away, hidden by another body or inside someone). Every person in the cast is a primary subject: the camera gives each a real presence whatever their role in
the action, shows as much of each body as the action needs (head to feet only when the pose needs it), keeps every
visible body part joined to its owner in the frame, and changes the arrangement or viewpoint rather than crop a
person out; background figures may be partly visible. The final prompt shows that framing through what is visible
(where each person is, which parts show, what lies in front and behind), not by a shot name. Every act needs the
bodies to reach each other (two acts at once only when a position reaches both partners, never a closed loop through
everyone), and positions and actions agree on who does what to whom. Clothing, lighting and
mood are left to the final prompt; a selected Clothing, Lighting or Mood & Tone entry goes in extras. Saved scenes
with the old clothing, lighting and mood fields still load (`retire_fields` drops them). Repeated looks are not asked again (an image asked again tends to copy an accepted
one); later batches see earlier looks field by field. Missing images
are retried, then reported; the last round keeps an image rather than lose it.

Prompts (`v2/prompts.py`): the existing Builder writes each final prompt from the scene with the run's Director
preset and target model together, as in the Prompt Builder; the scene writer never sees a Director. The scene rules
ask Builder to keep every subject, action, object, place and camera, add none, choose clothing, light and mood to
suit the scene, and describe people rather than labels; known characters are named, never described. The Builder does not parse the scene as user rules
(`compile_rules=False`): the approved requirements already carry them. The Builder is told what exact-text triggers
carry (never describe it) and which meanings to write; an exact style trigger turns the Style and Capture settings off. Code places
every exact text itself (`place_triggers`): pinned ones first in list order, the rest by type in the Anima tag line,
at its person's first mention in prose, or in an Ideogram element's description, `style_description.aesthetics` or
`high_level_description`. The scene writer hears meaning triggers (`trigger_notes`). Final prompts use the run's Creativity setting.
Every prose target carries one rule for two or more people: a place in the frame per person, one short anchor
repeated at each mention, no shared pronouns, the owner, state and count of each body part that shows or touches,
and where the bodies touch and stay apart. Meaning triggers reach
the Builder as notes to rewrite: code asks once more when a prompt copies a note of three or more words or loses a
number it gives, and fails the image when the number is still missing (`meaning_problem`). Code rewrites once a
prompt that still uses a numbered label ("man 1") or its ordinal ("the first man"). The writer never sees those for a
person whose looks change: each is named by the least of their own look in that scene that tells everyone apart, in words without brackets
or commas ("the man with pale skin"; `anchors`, `name_people`); known,
triggered and named people keep their label. A scene whose actions do not name every person (an entry copied with
its placeholder people) is asked again (`unnamed_people`). At Creative and Dice, a role label ("servant", "ruler") is also replaced by the person's look, so the role is shown by
the scene's signs instead of named; quoted words stay. On Anima, code writes the tag line's people-count tags from
the cast, puts quality tags first and keeps one safety tag before the counts, writes tags with spaces (score tags
keep their underscores) and drops low-quality tags, score tags Anima does not know and invented solo tags
(`anima_tag_line`). Each scene shows the request through its own signs, specific enough to name without being told; the scene
writer writes them (extras) right after the pose, before the place and camera, and an image that reuses an
earlier image's place with its camera, arrangement or signs is asked again (`_repeats`). One set of library templates is picked for the whole run, so every
prompt has the same structure, and an entry's position name reaches the Builder only when the scene's actions say it
(an entry the writer had to swap or adapt would otherwise name a different act). Understanding drops a must or avoid
phrase that only repeats a trigger's text. Capture is Auto in the brief unless the style is Realistic. Any style
trigger (any use) turns the Style off for every step (`run_style`), so not even Anima's anime default is added. The
Builder writes each scene with the run's Creativity, which alone decides how much is invented around the scene's
fixed people, placements, contact, action and camera, and is told that the
confirmed requirements win where a scene contradicts them. Those
requirements are the people, rules and must/avoid; the raw request and `fixed` are left out, since the scene already
carries them and the model would paste them in as content. An Actions & Poses entry decides how the requested activity
happens, never what it is: an entry showing a different act does not fit.

## Owners

| Concern | Owner |
| --- | --- |
| API admission: understand, confirm | `goated_prompter/features/dataset/routes.py` |
| Workflow execution (`dataset_understanding`, `dataset_v2_scenes`) | `goated_prompter/features/dataset/runner.py` (dispatched by `goated_prompter/workflow_runners.py`) |
| Editable draft defaults and validation | `goated_prompter/features/dataset/v2/draft.py`, saved by `goated_prompter/workflow_settings.py` |
| Understanding brief | `v2/understanding.py` |
| Adults-only and safety checks on the request | `v2/safety.py` |
| Source-bound, expiring, single-use approval tickets | `v2/tickets.py` |
| Guided input assignment | `v2/assignments.py` |
| Vocabulary categories, pack discovery and the vocabulary prompt section | `features/vocabulary/catalog.py` |
| Scene composition | `v2/scenes.py` |
| Final prompts through the Builder | `v2/prompts.py` |

## Seeds

The draft's `seed` and `seed_mode` (randomize, fixed, increment) work like ComfyUI's seed
control. The frontend picks each new batch's seed and sends it with the reviewed request; the
seed is saved after Confirm starts the run, so a rejected or cancelled review changes nothing.
The seed is not part of the approval signature, so changing it invalidates nothing.
The seed decides only the run's random choices: the order and sample of vocabulary entries, which Actions & Poses
entry each image is dealt, which library templates are used and the model's sampling. The same seed with the same
settings repeats a run; it never changes what the request asks for.

## One job per setting

The request and rules decide the facts; NSFW whether the run is adult; triggers their exact text, meaning or both;
the Director what is emphasized; the target how the prompt is written; Length how long it is; Style the medium;
Creativity alone how much is invented around the facts (its guide text and the writers' temperature); vocabulary
which verified entries fit the request. The Builder and the scene writer both turn the request's abstract words (a
role, status, relationship, feeling or theme) into visible signs (`SHOW_DONT_TELL`, kinds of sign only, never
examples); Creativity decides how far the signs go, and only Creative and Dice may write the request's own words on
a prop, garment or body. The NSFW switch only allows adult content: the request decides whether an image shows an
act, a role, a display or a mood, and nothing adds nudity, acts or kinks the request does not call for. Later
batches also see earlier images' extras, so props and signs are not repeated. `tests/unit/shared/test_layer_independence.py` checks that no other guide
decides how much is invented.

## Evidence boundary

CPU tests use mocked models and synthetic temporary storage. They check data flow (selection, what reaches the
composer and Builder, failures), not real-model creativity, scene coherence or visual correctness. No browser
end-to-end test covers the Dataset tab. The general evaluation harness (`tests/eval/runner.py`) covers Builder and
MiniMax only.

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
plus the shared vocabulary usage rules. Each category sends a seeded sample of at most `VOCABULARY_SAMPLE` (40)
entries per batch, so a large pack never drowns the request. The request and the approved requirements always win. With an Actions & Poses
pack selected, every scene names the entry it is built on (`entry`); code checks the entry is one of the selected ones
and that no entry is used by more than two images (`ENTRY_CAP`, raised to the images-per-entry when there are fewer
entries than images), and asks again otherwise. No pack is used automatically: character looks come from the request
and approved requirements, with vocabulary guidance only from manually selected Subjects packs. A known character has
only expression and clothing in its scene; its look comes from its name, never from the writer or vocabulary. Missing images
are retried, then reported; the last round keeps an image rather than lose it.

Prompts (`v2/prompts.py`): the existing Builder writes each final prompt from the scene with the run's Director
preset and target model together, as in the Prompt Builder; the scene writer never sees a Director. The scene rules
ask Builder to keep every subject, action, object, place, camera and light, add none, and describe people rather
than labels; known characters are named, never described. The Builder does not parse the scene as user rules
(`compile_rules=False`): the approved requirements already carry them. The Builder is told what exact-text triggers
carry (never describe it) and which meanings to write; an exact style trigger turns the Style and Capture settings off. Code places
every exact text itself (`place_triggers`): pinned ones first in list order, the rest by type in the Anima tag line,
at its person's first mention in prose, or in an Ideogram element's description, `style_description.aesthetics` or
`high_level_description`. The scene writer hears outfit and meaning triggers (`trigger_notes`). Code rewrites once a
prompt that still uses a numbered label ("man 1").

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

## Evidence boundary

CPU tests use mocked models and synthetic temporary storage. They check data flow (selection, what reaches the
composer and Builder, failures), not real-model creativity, scene coherence or visual correctness. No browser
end-to-end test covers the Dataset tab. The general evaluation harness (`tests/eval/runner.py`) covers Builder and
MiniMax only.

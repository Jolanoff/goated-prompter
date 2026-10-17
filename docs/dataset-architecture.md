# Dataset architecture

Dataset produces prompts, not images. The rebuilt workflow uses
`features/dataset/v2/understanding.py`, `scenes.py` and `prompts.py`:
Understanding → source-bound human confirmation → the scene writer (with any selected vocabulary) → final Builder prompts.
Scenes-only generation stops before Builder. This is the only Dataset workflow; the
earlier pipeline (ideas with scenes, per-scene actions, Continue, saved scene plans, durable
checkpoints, recent-idea history and the private `sexual.txt` vocabulary) has been retired.
Its files under `data/` are not read, changed or deleted; old fields in a saved Dataset draft
are dropped when the draft loads.

## Runs

Each requested image keeps its slot number through every stage, and
every V2 run is saved to `data/dataset_v2_runs/<run_id>.json` (`v2/runs.py`) as its
scenes and final prompts complete. A run left unfinished by a stopped backend is marked
interrupted on the next start; nothing is regenerated. Saved runs are user work and are never
deleted automatically; the store only reports runs outside the newest 20 complete and 20 incomplete
ones as candidates for a future, explicit cleanup. A run's final status always matches its job's
(cancellation, then server stop, then failure; succeeded only after the job succeeded). Reload
recovery in the app, scene editing, per-image regeneration and continuing a scenes-only run are not
implemented.

Vocabulary (`features/vocabulary/catalog.py`): `vocabulary/core/scene_category_registry.json` is the source of
truth for the categories and their folders; `category_definitions.json` says what each means and
`prompt_instructions.json` what the scene writer is told about it. A pack is one JSON file in a registered folder,
exactly `{"name", "category", "entries": [texts]}`; its id is `<folder>/<file>`. Each file is read on its own: one
that cannot be read is reported with its reason and the others still load. `GET /api/vocabulary/catalog` returns
categories, packs and problems. Adding a pack is adding its file; adding a category is one entry in each Core file
plus its folder. There is no automatic selection, retrieval or compatibility data.

Selection: the Dataset tab's Vocabulary Library selects packs by hand (search, category filter, preview,
Apply/Cancel); the selected ids are the draft's `vocabulary_packs`, saved with the other Dataset settings. They are
not part of the review signature, so changing them needs no new Understanding. Confirm checks them against the
catalog and records each pack's id, name, category and entry count in the run (field `packs`).

Understanding (brief version 11) records the subject type, participant count, stated attributes, the central
activity, and what stays fixed and what varies. It never reads vocabulary. Version 9 and 10 briefs in saved runs
stay readable.

Scenes (`v2/scenes.py`): the scene writer (`dataset_v2:scenes`, one call per batch of up to ten images) receives the
USER REQUEST, the EXISTING APPROVED REQUIREMENTS (rules, Understanding, style) and, only when packs are selected, a
SELECTED VOCABULARY section: just the categories that have a selected pack, each with its Core instruction and the
entries of those packs, plus the shared vocabulary usage rules. Entries are optional possibilities; the request and
the approved requirements always win. With no pack selected the prompt has no vocabulary section. Missing images are
retried, then reported.

Prompts (`v2/prompts.py`): the existing Builder writes each final prompt for the chosen target from the scene,
with a neutral director (`general_director`); the user's Director presets steer the Prompt Builder only. The
scene rules ask Builder to keep every subject, action, object, place, camera and light, add none, and describe
people rather than labels. Only the trigger is checked in code.

## Owners

| Concern | Owner |
| --- | --- |
| API admission: understand, confirm | `goated_prompter/features/dataset/routes.py` |
| Workflow execution (`dataset_understanding`, `dataset_v2_scenes`) | `goated_prompter/features/dataset/runner.py` (dispatched by `goated_prompter/workflow_runners.py`) |
| Editable draft defaults and validation | `goated_prompter/features/dataset/v2/draft.py`, saved by `goated_prompter/workflow_settings.py` |
| Understanding brief | `v2/understanding.py` |
| Adults-only and safety checks on the request | `v2/safety.py` |
| Source-bound, expiring approval tickets | `v2/tickets.py` |
| Guided input assignment | `v2/assignments.py` |
| Vocabulary categories, pack discovery and the vocabulary prompt section | `features/vocabulary/catalog.py` |
| Scene composition | `v2/scenes.py` |
| Final prompts through the Builder | `v2/prompts.py` |
| Durable runs | `v2/runs.py` |

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

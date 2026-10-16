# Dataset architecture

Dataset produces prompts, not images. The rebuilt workflow uses
`features/dataset/v2/understanding.py`, `scenes.py` and `prompts.py`:
Understanding → source-bound human confirmation → scenes → final Builder prompts.
Scenes-only generation stops before Builder. This is the only Dataset workflow; the
earlier pipeline (ideas with scenes, per-scene actions, Continue, saved scene plans, durable
checkpoints, recent-idea history and the private `sexual.txt` vocabulary) has been retired.
Its files under `data/` are not read, changed or deleted; old fields in a saved Dataset draft
are dropped when the draft loads.

## Runs

Each requested image keeps its slot number through every stage, and
every V2 run is saved to `data/dataset_v2_runs/<run_id>.json` (`v2/runs.py`) as concepts,
stagings, scenes and final prompts complete. A run left unfinished by a stopped backend is marked
interrupted on the next start; nothing is regenerated. Saved runs are user work and are never
deleted automatically; the store only reports runs outside the newest 20 complete and 20 incomplete
ones as candidates for a future, explicit cleanup. A run's final status always matches its job's
(cancellation, then server stop, then failure; succeeded only after the job succeeded). Reload
recovery in the app, scene editing, per-image regeneration and continuing a scenes-only run are not
implemented.

Per-run vocabulary packs (Phase 2): the Configure page chooses the packs a run uses, independent of
the Pack Manager's enabled state. Confirm resolves the choice with the core and every required pack and
saves it in the new run (schema 2, field `packs`: selected ids, each pack's role, version and content
fingerprint) before any inference; the field never changes afterwards. Scene writing reads exactly those
packs and fails before inference when any has drifted (vocabulary/schemas/SPEC.md). Schema 1 runs stay
readable as they are, show their packs as not recorded, and are never rewritten; an unknown schema is
reported incompatible and left untouched. `GET /api/workspace/dataset/v2/runs/<run_id>/packs` returns a
run's recorded selection and how the installed packs compare, for the run pages and the Vocabulary
Inspector.

Structured intent (Understanding v10, Phase 3): the same Understanding call also returns `intent`, the
request as typed parts (subjects, actions, poses, objects, body parts, attributes, places, look), each
with its status (every image, varies, allowed, ruled out), whether the request states it or the model
suggests a dimension to vary, and its links (who does what to whom, what belongs to what, the guided
input it belongs to), plus relations, notes on what stays unclear, and search words kept apart as
evidence (`v2/intent.py`). Code checks the structure with the existing single repair; a second invalid
intent leaves the brief valid with intent marked unavailable. Wording that does not match the request
and clashes with avoid are reported, never rewritten. At confirmation, links and search words can be
corrected and the model's own suggestions removed; the server checks every correction again, and
anything the request states changes only through Revise. Brief version 10 adds `intent`; version 9
briefs in saved runs stay valid unchanged. Summary, fixed, randomized, must and avoid remain what scene
writing uses; vocabulary retrieval reads intent only from Phase 4.

Visual Direction: the Configure page also sets, per dimension (framing, camera angle, composition,
lighting, atmosphere), whether Visual Direction may fill it and how much it varies. Confirm sends these
settings with the run. Core defines reusable visual interfaces; General provides concrete framing,
camera angles, composition and lighting choices; the optional
`visual` pack provides atmosphere. Other selected packs can add directions. Composition tells Visual
Direction what must be visible, so open choices cannot contradict declared visibility. Framing is not
restricted solely by head count. Composed scenes receive directions in the finishing request; freeform
scenes receive them through the concept's camera and lighting fields (SPEC.md sections 11–12). The run
record and generation log keep choices, exclusions and visibility requirements.

Universal Vocabulary composition (`features/vocabulary/composer.py`): before retrieval, a structured
scene contract combines grounded confirmed Understanding requirements and required Director mechanics,
separately from soft preferences. Retrieval finds relevant entries in the run's selected packs; code selects compatible arrangements,
actions with items, and places, assigning roles and resources. Every trial is checked jointly by the
resolver while choosing. Entries may declare any subset of components, including none. Missing data is
unspecified, never automatically incompatible or verified. Named requirements cannot silently disappear;
cross-role aliases are alternatives, and guided requirements belong to their own images. Unsatisfied
requirements fail with reasons. Structured performer/target intent constrains bindings where entries
declare those sides through access or explicit participant `role` fields; incompatibility cannot silently
reverse the people. Bounded joint search revisits earlier bindings, arrangements, object instances and
spaces when later requirements conflict. Feasible complete compositions outrank unknown ones.

Directors can carry a structured `vocabulary` block (`features/vocabulary/preferences.py`): preferred or
avoided entries, tags and categories, visual preferences, role priorities and themes. `require: [entry ids]`
sets mandatory mechanics (and visual directions); a missing required id yields an explicitly unchecked
fallback. Obligation clauses anywhere in a Director's prose ("every image must show a leash") are mandatory
too; other names in its prose only raise draw weight. A target model can add requirements the same way. Built-ins and user
presets share this format; presets without a block use their text. User requirements, selected packs,
ratings and compatibility remain authoritative. Preferences are preserved through preset save/update.

For composed images, Scene Builder makes one lightweight finishing call per batch, adding appearance and
open details instead of regenerating mechanics. Code renders positions and actions from the composition;
the scene's `arrangement` record retains selected entries, roles, facts, place, items, status and checking
limits. Code retains established place and visual fields rather than accepting rewritten copies from the
finisher. Builder must keep the composition's meaning (`arrangement.semantics`: actions, postures, place,
items and required camera), in its own words; code checks each by the entry's name or aliases, and a lost
meaning is retried once with what was lost, then fails that prompt. Target formatting is the target's own.
Freeform images retain concept → staging → description and are labelled `freeform` / `unchecked`.
Statuses remain `unknown`, `eligible` or `feasible`, never proof of physical geometry or model prose.
Only `feasible` records set `verified: true`; unresolved findings reach the finisher and run record.
Only failed slots are retried; valid slots and guided inputs stay in place. Failures distinguish
`composition`, `finishing`, `concepts`, `staging` and `description`. A run with no scenes fails with reasons;
a partial run finishes with an "incomplete" message.

### Phase 7: separate UI stages

- **7A — Pack Manager:** manage installed packs and their enabled state.
- **7B — Vocabulary Explorer:** inspect entries, relationships and compatibility data.
- **7C — Visual Pack Creator:** create and edit packs visually.

Each stage must be separately reviewable. Adult packs require the same management,
inspection and creation capabilities as General and Fantasy packs, while preserving
content ratings and eligibility rules.

### Phase 8: quality gates

Evaluate General/SFW, Fantasy and Adult/NSFW separately, inspecting both generated
scenes and final Builder prompts. Adult evaluation must cover solo, pair and group
requests; explicit anatomy; positions; participant and role consistency;
interactions and physical constraints; accessory requirements and exclusions;
diversity; and vocabulary relevance. Scripted contract tests establish data flow,
not generated-output quality.

## Owners

| Concern | Owner |
| --- | --- |
| API admission: understand, confirm, a run's recorded packs | `goated_prompter/features/dataset/routes.py` |
| Workflow execution (`dataset_understanding`, `dataset_v2_scenes`) | `goated_prompter/features/dataset/runner.py` (dispatched by `goated_prompter/workflow_runners.py`) |
| Editable draft defaults and validation | `goated_prompter/features/dataset/v2/draft.py`, saved by `goated_prompter/workflow_settings.py` |
| Understanding brief and structured intent | `v2/understanding.py`, `v2/intent.py` |
| Adults-only and safety checks on the request | `v2/safety.py` |
| Source-bound, expiring approval tickets | `v2/tickets.py` |
| Guided input assignment and the active Director | `v2/assignments.py`, `v2/director.py` |
| Scene composition, compatibility, visibility and Director preferences | `features/vocabulary/composer.py`, `resolver.py`, `visual.py`, `preferences.py` |
| Vocabulary integration, finishing and freeform scenes | `v2/scenes.py`, `v2/vocabulary_packs.py` |
| Final prompts through the Builder | `v2/prompts.py` |
| Durable runs | `v2/runs.py` |

## Seeds

The draft's `seed` and `seed_mode` (randomize, fixed, increment) work like ComfyUI's seed
control. The frontend picks each new batch's seed and sends it with the reviewed request; the
seed is saved after Confirm starts the run, so a rejected or cancelled review changes nothing.
The seed is not part of the approval signature, so changing it invalidates nothing.

## Evidence boundary

CPU tests use mocked models and synthetic temporary storage. They do not prove real-model
creativity or visual correctness. No browser end-to-end test covers the Dataset tab; the old
browser suite tested the retired pipeline and was removed with it.
`tests/gpu/dataset_understanding_eval.py` evaluates Understanding against a real model; the
general evaluation harness (`tests/eval/runner.py`) covers Builder and MiniMax only.

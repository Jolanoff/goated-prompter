# Dataset architecture

Dataset produces prompts, not images. There is one pipeline:

```text
concept + rules + local guided input
  → UNDERSTAND → human approval
  → IDEAS (Idea, Placement, Visibility, Camera, Framing, Context)
  → frozen SCENE + same-call self-check (PASS / REPAIR:)
  → Builder ENHANCE / Direct → FINAL PROMPT
```

## Owners

| Responsibility | Owner |
| --- | --- |
| Scoped understanding and richer brief validation | `goated_prompter/dataset_understanding.py` |
| Source-bound, expiring approval tickets | `goated_prompter/dataset_intent.py` |
| Guided assignment indexes and cycling | `goated_prompter/dataset_assignments.py` |
| Six-field ideas and lexical duplicate hints | `goated_prompter/dataset_ideas.py`, `dataset_quality.py` |
| Recent-idea RAM guidance | `goated_prompter/dataset_idea_history.py` |
| Frozen scene, self-check and explicitly requested repair | `goated_prompter/dataset_scene.py` |
| Compact orchestration and versioned saved-plan validation | `goated_prompter/scene_planner.py` |
| PASS eligibility, shared by API and enhancement | `goated_prompter/scene_eligibility.py` |
| Builder instruction handoff, trigger/style controls | `goated_prompter/prompting/dataset.py` |
| Batch/actions and bounded final-output recovery | `goated_prompter/dataset.py` |
| Target syntax and output normalization | `goated_prompter/prompting/target_models.py`, `workflow_output.py` |
| Editable drafts and durable generated progress | `goated_prompter/workflow_settings.py`, `dataset_checkpoints.py` |
| API admission and workflow execution | `goated_prompter/workspace_api.py` |
| Confirmation and job synchronization | `frontend/src/workflows/useDatasetConfirmation.js`, `useDatasetWorkflow.js` |
| Autosave, revisions and refresh guards | `frontend/src/workflows/useWorkflowSettings.js` |
| Cards, edits, self-check display and exports | `frontend/src/workflows/DatasetTab.jsx`, `DatasetIdeaDetails.jsx`, `datasetState.js` |

## Authority and stages

UNDERSTAND interprets the user's request without generating scenes. Its brief records
character count, identity policy, scoped requirements, action alternatives, permitted
expansion, visible evidence, interactions, natural occlusions and physical conflicts.
`all_outputs` applies to every image, `dataset` to the set, and `guided:N` only to that
line's assignments. Clarifications prevent approval. Added instructions require
reanalysis; the approval ticket is bound to source settings and saved scene edits.

IDEAS makes one batch call with six short descriptions per image, each at most 600
characters. An explicit replacement requests only its index. History and diversity
hints never override a guided action or approved fixed requirement. There is no
Fast/Quality dispatch, automatic substitute idea or fallback plan.

SCENE makes one call per image. It expands the fixed idea into one spatial paragraph
of at most 3,000 characters and checks that paragraph in the same call. The check is
exactly `PASS`, or three lines beginning `REPAIR:`, followed by a specific defect and
local correction. This is model self-checking, not independently verified physics.
There is no structured geometry output or separate evaluator.

REPAIR blocks enhancement for that image. **Repair scene** explicitly requests one
targeted build/check attempt, preserving the fixed idea and other valid relationships.
Another REPAIR verdict stays blocked; nothing automatically loops, replaces the scene
or weakens requirements. Invalid IDEAS/SCENE output stops that stage without automatic
retry; already published ideas and completed scenes remain checkpointed.

Accepted scene prose is Builder's entire creative input. `dataset_instruction`
calls the existing `assemble_instruction` with **Enhance / Direct**, preserving
subject, composition and camera. Director, creativity, length, style and target
controls enrich compatible unspecified detail, not a different event or crop.
Dataset has no separate final writer or semantic/support reviewer. Shared Builder
and MiniMax planning/validation remain independent and available.

## Recovery and text preservation

Final enhancement retains up to three bounded retries for transport errors, malformed
target output, missing protected triggers, positive-content leakage and runaway
generation. These retries never replan or repair the scene. Transport retries repeat
the instruction; output correction stays within the accepted scene and target format.
Runaway retries reduce the output allowance. A sentence-complete prefix may be
accepted only after normal output validation.

Generic text cleanup trims outer whitespace only. Dataset's conservative sanitizer
removes complete standalone exclusion/meta clauses, not useful mixed prose, quoted
image text or protected triggers. Ideogram cleanup touches descriptive strings, never
rendered `elements[].text` or required schema fields. Anima's supported standalone
positive quality tags remain allowed. These are narrow checks, not a semantic fidelity
score or universal ban on words such as “no.”

## Edits, freshness and persistence

Idea edits discard stale five-field descriptions and invalidate that scene/check/prompt.
Scene edits retain the fixed idea descriptions but invalidate its check and prompt.
A manual scene must be checked before enhancement. Output-setting changes reuse
checked scenes; concept, guided input, amount, type, variety, rules or visual-style
changes invalidate the plan. Server eligibility is accepted only while the client's
scene matches its saved dependency projection; key order and prompt bookkeeping do
not affect identity.

The backend atomically checkpoints generated progress before publishing it. Workflow
revision and input signatures prevent stale jobs from replacing newer edits. Restart
marks running work interrupted without resuming inference. Generation does not clear
the prior edited batch before admission; a lost admission response cannot roll back
accepted work. Exports and Clear release completed job diagnostics, not durable scenes.
Clear explicitly removes the current final prompts.

Final results contain `index`, `input`, `idea`, `scene`, `prompt`. Saved final prompts
from older versions remain readable through a nonmutating projection. Obsolete plans
are excluded from executable draft projections and require replanning; archived
checkpoint snapshots remain intact. No legacy staging migration is executed.

## Evidence boundary

CPU tests use mocked models and synthetic temporary storage. Browser checks cover
approval, persistence, admission races, edits, explicit repair and export. They do
not prove real-model creativity or visual correctness.

`tests/eval/runner.py` uses the production Dataset pipeline with an interactive
Understanding approval gate for live evaluation. Frozen replay remains historical
evidence, not proof of current model quality. Semantic claims require independent
review; see [the evaluation guide](../tests/eval/README.md).

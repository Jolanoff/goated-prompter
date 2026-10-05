# Dataset architecture

Dataset produces prompts, not images. The dependency chain is:

```text
concept + rules + local guided input
  → idea → scene + applicable geometry → target-specific prompt
       Fast: combined chunks             Dataset final writer
       Quality: batch ideas, then chunks
```

## Owners

| Responsibility | Owner |
| --- | --- |
| Assignment indexes and cycling guided lines | `goated_prompter/dataset_assignments.py` |
| Fast/Idea/Composer instruction contracts | `goated_prompter/prompting/scene_planner.py` |
| Chunking, strict JSON, stage retries and local repairs | `goated_prompter/scene_planner.py` |
| Field registry, live capabilities, aliases, migration and staging rules | `goated_prompter/dataset_staging/` |
| Scene usability shared by writing, actions and API projections | `goated_prompter/scene_eligibility.py` |
| Dataset writer composition | `goated_prompter/prompting/dataset.py` |
| Sequential writing, bounded recovery, trigger/content validation | `goated_prompter/dataset.py` |
| Target syntax and output normalization | `goated_prompter/prompting/target_models.py`, `goated_prompter/workflow_output.py` |
| Editable workflow state and durable generated progress | `goated_prompter/workflow_settings.py`, `goated_prompter/dataset_checkpoints.py` |
| Dataset requests, job projection, quality analysis and readiness | `frontend/src/workflows/useDatasetWorkflow.js` |
| Serialized autosave, revisions and stale-refresh guards | `frontend/src/workflows/useWorkflowSettings.js` |
| UI, dialogs, elapsed time and downloads | `frontend/src/workflows/DatasetTab.jsx` |
| Pure edit/invalidation and canonical scene comparison | `frontend/src/workflows/datasetState.js` |

## Authority and stage contracts

Explicit concept, consistency rules and each assignment's local guided input outrank planner
inference. An idea fixes the event; the scene and supplied geometry describe its spatial realization.
The writer enriches compatible treatment inside those decisions. Director, target and length
controls do not authorize a different action, support arrangement or crop.

Fast creates ideas and scenes together. Its output contract does not ask it to echo ideas that were
never supplied. Quality's Idea Planner owns invention and diversity; the fixed-idea Composer
echoes those ideas without receiving novelty history or batch-variety instructions. Both composition
paths use chunks of four, the same selected staging profile and strict JSON validation. Idea output
is bounded at 30 words / 240 characters; model scenes at 240 words / 2,000 characters. Original-input
recovery and saved legacy content have separate storage limits; live validators are not weakened
to accept them as newly generated model output.

The Dataset writer shares target adapters, target-resolved length guidance, Director instructions
and output contracts. It does **not** assemble a Builder prompt and then remove conflicting rules
by string substitution. Dataset Creativity changes descriptive enrichment only. Builder and MiniMax
keep their existing orchestration; no global workflow-controller abstraction is introduced.

## Staging and framing

The global vocabulary includes historical values for loading saved data. Live `StagingProfile`
value overrides expose ordinary capabilities, including ordinary camera/contact values for
non-human profiles. Prompt schemas and validators consume the same profile restrictions.
Specialized user mechanics remain representable through applicable free text; Character
`pose_type=custom` still requires specific `pose_detail`. Unknown fields, invalid values and missing
required fields remain errors.

Saved specialized enum facts migrate into pose/expression/view details. Safe whole-subject framing
labels map to their profile equivalents. Ambiguous facts or overflowing details flag only their row
for repair; scene prose and valid siblings survive. Overflowing migrated details remain bounded,
with an explicit warning rather than being silently discarded. This is a compatibility migration,
not a way for new model output to bypass the live schema.

`FramingIntent` is a narrow immutable projection of crop, source (`user`, `guided`, `planner`) and
conflicts. It is not a second general scene representation. Shared checks use it for scene
eligibility, local repair locks, deterministic recovery and final prompt validation. Conflicting
explicit source crops are errors rather than permission to fall back to planner framing.

Crop recognition is lexical and conservative: quoted image text, camera distance and visible anatomy
are not crop instructions. Folded or foreshortened feet can appear inside a tight Character composition;
their visibility never automatically widens it. A locked user crop cannot be widened to solve a
whole-product requirement either: an actual conflict needs repair or user clarification. Lexical
checks cannot prove arbitrary paraphrased composition or the anatomy of a future image.

## Recovery and text preservation

`PlannerCallState` separates output correction from transport retry. A connection failure repeats
the same stage request, preserving any existing correction and last completed candidate. It does
not feed a socket/provider error to the model as a prompt defect. Retry limits and checkpoints
remain bounded.

Scene repair preserves the fixed idea, source mechanics and nondefective geometry. Exhaustion
marks that row failed; it does not replace its event with an easier idea. Writer recovery keeps its
own target-format, trigger, positive-content and runaway-output policies. The Planner and writer
loops remain separate because their recovery units and validators differ.

Generic `sanitize_prompt_text` trims outer whitespace only. It does not remove parentheses,
replace semicolons, collapse deliberate spacing or strip metadata-like visible content. Target
adapters still own transformations such as structured-output extraction. Dataset's separate
positive-content sanitizer and strict validator remain in force, including literal/trigger protection.

## Frontend freshness and persistence

The server owns scene eligibility. The client accepts that decision only when its editable scene
still matches the saved scene's semantic projection: index, input, presence/value of idea, prose,
geometry and scene status. Geometry object keys are recursively sorted; arrays and literal prose
retain their ordering/text. Prompt status and writer failure bookkeeping do not change scene identity.
An unsaved idea/scene/geometry edit cannot reuse old eligibility.

The hook preserves submission exclusion, quality-attempt disposal, job ID/revision deduplication,
flush-before-generation and the existing revision snapshot. `useWorkflowSettings` owns autosave
ordering and guards late refreshes against newer edits. Exports release only disposable completed
job diagnostics after flushing; editable plans, durable checkpoints and history are not erased.

## Evidence boundary

`tests/eval/runner.py` keeps frozen replay and an opt-in writer mode. Its optional Dataset pipeline
mode calls the actual production planner and writer. It records scope, raw calls, stage parameters,
completion reasons and latency. Reports separate output repairs, transport retries, trigger checks,
scene usability, duplicate diagnostics and model cost.

Production model self-review is diagnostic, not independent ground truth. Semantic regression
gates require complete explicitly human/independent annotations. Frozen fixtures retain observed
historical failures; mock regressions prove deterministic contracts and orchestration, not current
LLM creativity, fidelity or latency. See [evaluation instructions](../tests/eval/README.md) and the
[remediation report](remediation-report.md).

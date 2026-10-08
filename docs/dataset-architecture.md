# Dataset architecture

Dataset produces prompts, not images. There is one pipeline:

```text
concept + rules + local guided input
  → UNDERSTAND (hard / soft / free) → human approval
  → IDEAS suggestions (Idea, Placement, Visibility, Camera, Framing, Context)
  → SCENE + same-call correction and self-check (PASS / REPAIR:)
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
| Frozen scene, same-call correction and self-check | `goated_prompter/dataset_scene.py` |
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

The brief also exposes three small scoped lists for approval: **hard** obligations,
**soft** preferences that may yield to hard requirements, and **free** creative
choices within the user's expansion limits. Only approved hard requirements are
immutable. The richer interpretation explains this contract; downstream stages do
not infer extra locks from it or promote their own inventions into requirements.
UNDERSTAND generates each scoped fact once in a hard, soft, free or explanatory
context bucket, tagged with the review sections it belongs to. The generation schema
reserves one HARD slot for the app-retained character trigger when needed, without
reducing the other buckets' capacities. The app expands these facts into the same public
brief, supplies output-setting prose from the request, and retains the supplied
character trigger before approval. Existing full briefs remain valid; saved reviews,
approval tickets, IDEAS and SCENE still consume the unchanged public contract.
Generation uses bucket-specific review-tag schemas: HARD excludes `may_vary`, FREE
allows only `may_vary`, SOFT has no review tags, and CONTEXT requires exactly
`natural_occlusions`. Required overlaps may still be HARD. This prevents constrained
decoding from producing cross-authority tags that the projection would reject;
nonconforming responses remain rejected, without moving or dropping their facts.
The generation instructions request minified, single-line JSON, preserving whitespace
inside string values. This is model guidance, not a JSON-schema whitespace guarantee;
valid pretty-printed responses remain accepted without a formatting retry.
UNDERSTAND also requests semantic brevity: no synonymous restatements or separate
facts already contained in another same-scope, same-authority fact. Ordinary
unspecified freedoms are grouped categorically by scope and policy rather than
enumerating every possible trait. Explicit restrictions, owners and choose-once
versus per-image policies remain distinct. Array limits are ceilings, not targets;
complex requests retain their full existing capacity. This is model guidance, not
automatic semantic deduplication or truncation of a generated brief.
The review summary lists mandatory variation once instead of repeating it among
image/scoped requirements. Within the optional details view, exact scoped facts
with the same authority appear once, with their additional review categories shown
as annotations. Different wording, literal case/spacing, scopes or authorities
remain separate, and conflict resolutions remain inspectable. The original brief,
approval and downstream inputs are not rewritten by these display changes.
Explicit user counts, actions, contacts, exclusions and required visual evidence
belong in hard, retaining their scope and qualifiers. A semantic trait does not
automatically require exposure. Unresolved user conflicts block approval.

IDEAS makes one batch call with six short descriptions per image, each at most 600
characters. An explicit replacement requests only its index. History and diversity
hints never override a guided action or approved hard requirement. The six fields
are proposals, not frozen staging: SCENE may adjust generated details. There is no
Fast/Quality dispatch, automatic substitute idea or fallback plan.
IDEAS requests minified, single-line JSON and asks the model to resolve generated
repeats within that same call using permitted event differences. During a fresh
batch, exact normalized duplicates retain the first valid idea and mark only later
repeats for repair; permitted guided repeats remain accepted. Invalid individual
rows also become explicit failed slots without dropping valid siblings. Valid scenes
and prompts finish first, then one replacement call requests only failed idea indexes,
followed by their scene/writer calls. Replacement validation still rejects unchanged
or repeated ideas; unsuccessful repairs leave an inspectable partial batch, not an
unbounded retry loop. Replacement scenes are composed independently: a scene failure
is recorded on that slot while other usable replacements reach the writer. No failed
scene is retried automatically. Explicit single-idea replacement remains strict. Lexical
similarity remains a nonblocking hint, not semantic verification. There is no separate
rejection threshold at 20 items. Globally malformed JSON or a wrong batch size is
still rejected rather than guessing missing assignments.

SCENE makes one call per image. It expands a suggested idea into one spatial
paragraph of at most 3,000 characters. Before returning `PASS`, its single focused
self-check compares hard requirements and demanded evidence with the camera/crop,
spatial relationships and invented details. Generated conflicts are corrected in
that same call. For example, a generated upper-half cup crop yields to a hard
requirement to show its base touching the table. User-required crops stay hard.
This is model self-checking, not independently verified physics. There is no
structured geometry output, separate evaluator or extra correction call.
SCENE also requests minified, single-line JSON. A three-line `REPAIR:` remains a
single JSON string with escaped line breaks. Both stages send compact input JSON,
retain their sampling and token budgets, and accept valid pretty-printed responses
without a formatting retry. Generation guidance alone does not guarantee minification.

`REPAIR:` is reserved for incompatible actual user hard requirements: its two further
lines name the conflict and ask the needed clarification. It blocks enhancement.
Revise conflicting requirements through UNDERSTAND and approve them again; **Repair
scene** cannot waive them. That button remains a single explicit build/check attempt
for saved diagnoses, preserving hard requirements and compatible scene content.
Another REPAIR stays blocked; nothing automatically loops or weakens requirements.
Invalid SCENE output stops the initial scene stage without automatic retry; already
published ideas and completed scenes remain checkpointed. During deferred idea
recovery, it fails only that replacement slot and leaves siblings progressing.
The parser validates
the response shape, not whether the model's conflict diagnosis is semantically true.

Accepted scene prose is Builder's entire creative input. `dataset_instruction`
calls the existing `assemble_instruction` with **Enhance / Direct**, preserving
subject, composition and camera. Director, creativity, length, style and target
controls enrich compatible unspecified detail, not a different event or crop.
Only the applicable hard/soft/free contract is supplied as approved requirements;
older idea staging is not restored after SCENE corrects it.
Dataset has no separate final writer or semantic/support reviewer. Shared Builder
and MiniMax planning/validation remain independent and available.

## Recovery and text preservation

Normal **Generate prompts** always runs ideas → scenes → prompts after the first
UNDERSTAND approval, regardless of the legacy `plan_scenes_first` saved flag.
**Generate scenes only** is an explicit separate action for manual scene review;
Continue reuses the accepted plan and writes only its missing prompts.

Final enhancement retains up to three bounded retries for transport errors, malformed
target output, missing protected triggers, positive-content leakage and runaway
generation. These retries never replan or repair the scene. Transport retries repeat
the instruction; output correction stays within the accepted scene and target format.
Runaway retries reduce the output allowance. A sentence-complete prefix may be
accepted only after normal output validation.

With trigger expansion disabled, Dataset restores a missing literal numeric count
from its equivalent English number-word phrase (1–20) before strict validation,
for example `two men` → `2 men`. This changes spelling only: it does not add subjects,
rewrite synonyms, infer counts or change the accepted scene. Quoted lettering,
identifier boundaries, compound numbers and already-present exact terms are left
alone. Ideogram restoration is limited to `high_level_description`. The correction
is reported in progress/activity; missing triggers still use the bounded writer retries.

Generic text cleanup trims outer whitespace only. Dataset's conservative sanitizer
removes complete standalone exclusion/meta clauses, not useful mixed prose, quoted
image text or protected triggers. Ideogram cleanup touches descriptive strings, never
rendered `elements[].text` or required schema fields. Anima's supported standalone
positive quality tags remain allowed. These are narrow checks, not a semantic fidelity
score or universal ban on words such as “no.”

## Edits, freshness and persistence

Idea edits discard stale five-field descriptions and invalidate that scene/check/prompt.
Scene edits retain the suggested idea descriptions but invalidate its check and prompt.
A manual scene must be checked before enhancement. Output-setting changes reuse
checked scenes; concept, guided input, amount, type or rules
changes invalidate the plan. Server eligibility is accepted only while the client's
scene matches its saved dependency projection; key order and prompt bookkeeping do
not affect identity.
Plans created under the earlier frozen-idea contract also need replanning; their
saved text and final prompts are not deleted or migrated.

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

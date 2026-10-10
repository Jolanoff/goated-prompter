# Dataset architecture

Dataset produces prompts, not images. There is one pipeline:

```text
concept + rules + local guided input
  → UNDERSTAND (characters + hard / soft / free) → human approval
  → BRAINSTORM candidate events (random batches) → app picks each image's event
  → IDEAS, five per call, each an idea with its finished scene
  → Builder ENHANCE / Direct with the approved cast → FINAL PROMPT
```

## Owners

| Responsibility | Owner |
| --- | --- |
| Scoped understanding, character list and richer brief validation | `goated_prompter/features/dataset/understanding.py` |
| Source-bound, expiring approval tickets | `goated_prompter/features/dataset/intent.py` |
| Guided assignment indexes and cycling | `goated_prompter/features/dataset/assignments.py` |
| Ideas with finished scenes, library examples and lexical duplicate hints | `goated_prompter/features/dataset/ideas.py`, `quality.py` |
| Recent-event RAM history, read and written only by Ideas | `goated_prompter/features/dataset/ideas.py`, `idea_history.py` |
| Chunked idea orchestration and versioned saved-plan validation | `goated_prompter/features/dataset/plan.py` |
| Writer eligibility, shared by API and enhancement | `goated_prompter/features/dataset/eligibility.py` |
| Builder handoff, cast section, Anima cast tags, cast check and trigger controls | `goated_prompter/features/dataset/prompting.py` |
| Batch/actions and bounded final-output recovery | `goated_prompter/features/dataset/service.py` |
| Target syntax and output normalization | `goated_prompter/prompting/target_models.py`, `workflow_output.py` |
| Editable drafts and durable generated progress | `goated_prompter/workflow_settings.py`, `goated_prompter/features/dataset/checkpoints.py` |
| API admission | `goated_prompter/features/dataset/routes.py` |
| Workflow execution | `goated_prompter/features/dataset/runner.py` (dispatched by `goated_prompter/workflow_runners.py`) |
| Confirmation and job synchronization | `frontend/src/features/dataset/useDatasetConfirmation.js`, `useDatasetWorkflow.js` |
| Autosave, revisions and refresh guards | `frontend/src/shared/workflow/useWorkflowSettings.js` |
| Cards, edits, character review and exports | `frontend/src/features/dataset/DatasetTab.jsx`, `DatasetConfirmationModal.jsx`, `datasetState.js` |

## Authority and stages

UNDERSTAND interprets the user's request without generating scenes. Its brief lists the
characters in every image (name, count, sex, kind such as human, anthro, monster, alien
or robot, origin as an existing, described or randomly invented character, series and
supplied traits) and records character count, identity policy, scoped requirements, action alternatives, permitted
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
approval tickets, IDEAS and the writer still consume the unchanged public contract.
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

For random batches, a brainstorm call (`brainstorm.py`) first lists about three candidate
events per image with a typicality score. The app drops events similar to recent runs or
current siblings and samples the batch weighted toward unusual events, then passes each
image its `event_seed`. Randomly invented human characters also get a code-drawn age, hair,
build and outfit per image in their creative direction. An unusable brainstorm is reported
and ideas continue without seeds; guided and library batches skip it.
IDEAS writes five images per call: each record is a one-line idea (the core event) and
its scene, a complete three-to-five-sentence picture with the whole cast in frame,
placement, action, setting, light and camera. Later calls receive the earlier ideas as
existing ideas, share one creative-direction salt and one library scenario order, so the
batch stays spread without one long list. Library prompts matching the concept are sent
as quality examples; a scene that copies one is treated like a repeated idea. An
explicit replacement requests only its index. History and diversity hints never
override a guided action or approved hard requirement. There is no Fast/Quality
dispatch, automatic substitute idea or fallback plan.
During a fresh batch, exact normalized duplicates retain the first valid idea and mark
only later repeats for repair; permitted guided repeats remain accepted. Invalid
individual rows also become explicit failed slots without dropping valid siblings.
Valid prompts finish first, then one replacement call requests only failed idea
indexes, followed by their writer calls. Replacement validation still rejects unchanged
or repeated ideas; unsuccessful repairs leave an inspectable partial batch, not an
unbounded retry loop. Lexical similarity remains a nonblocking hint, not semantic
verification. Globally malformed JSON or a wrong batch size gets one format correction
and is otherwise rejected rather than guessing missing assignments.

IDEAS owns recent-event memory and checks normalized exact repeats against it,
including when only camera or context changed. Fresh accepted ideas are remembered;
failed slots are not. An explicit guided input matching the event can still repeat.
History stays bounded in RAM per concept and expires automatically. There is no
manual reset control or endpoint. The writer does not read this history or change an
accepted event for novelty. Semantic variation beyond exact repeats
remains model-guided, not independently verified.

There is no separate scene-building call. Each idea's scene, or the user's edit of it,
is accepted for the writer as written. A `REPAIR:` note saved by the former scene check
still blocks its writer until the idea is regenerated.

Scene prose is Builder's entire creative input. `dataset_instruction` calls the
existing `assemble_instruction` with **Enhance / Direct**, adds the approved cast and
the applicable hard/soft/free contract. Director, creativity, style, length and target
controls enrich open detail, not a different event, cast or crop. For Anima, count tags
derived from the cast lead the tag block, followed by named characters' Danbooru and
series tags. A deterministic check retries the writer when cast-derived count tags or a
named character's name are missing from the prompt.
Dataset has no separate final writer or semantic/support reviewer. Shared Builder
and MiniMax planning/validation remain independent and available.

## Recovery and text preservation

Normal **Generate prompts** always runs ideas → prompts after the first
UNDERSTAND approval, regardless of the legacy `plan_scenes_first` saved flag.
**Generate scenes only** is an explicit separate action for manual scene review;
Continue reuses the accepted plan and writes only its missing prompts.

Final enhancement retains up to three bounded retries for transport errors, malformed
target output, missing protected triggers, positive-content leakage and runaway
generation, and for a dropped cast member. These retries never replan the scene. Transport retries repeat
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

Idea and scene edits keep each other and invalidate only that prompt; an edited scene
is written as edited. Output-setting changes reuse scenes; concept, guided input, amount, type or rules
changes invalidate the plan. Server eligibility is accepted only while the client's
scene matches its saved dependency projection; key order and prompt bookkeeping do
not affect identity.
Plans created before ideas carried their own scenes also need replanning; their
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
approval, persistence, admission races, edits, per-scene actions and export. They do
not prove real-model creativity or visual correctness.

`tests/eval/runner.py` uses the production Dataset pipeline with an interactive
Understanding approval gate for live evaluation. Frozen replay remains historical
evidence, not proof of current model quality. Semantic claims require independent
review; see [the evaluation guide](../tests/eval/README.md).

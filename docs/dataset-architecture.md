# Dataset architecture

Dataset produces prompts, not images. The rebuilt workflow uses
`features/dataset/v2/understanding.py`, `scenes.py` and `prompts.py`:
Understanding → source-bound human confirmation → scenes → final Builder prompts.
Scenes-only generation stops before Builder. The legacy workflow described below
remains available during migration; it must not be removed yet.

## Remaining migration requirements

Before retiring the legacy Dataset pipeline or old adult TXT logic, the rebuilt
workflow must demonstrate these retained capabilities:

- Durable recovery of new runs, including partial scenes and final prompts after
  cancellation, failure, reload and restart, without stale jobs overwriting newer work.
- Scene editing with dependent-prompt invalidation, plus per-scene regeneration
  that preserves unrelated scenes and results.
- Continue from new scenes-only runs using the reviewed scenes rather than
  regenerating or reinterpreting them.

These are requirements for final migration, not implemented rebuilt features.

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
not generated-output quality. Required functional parity and quality evidence must
be established before legacy removal.

## Legacy pipeline reference

```text
concept + rules + local guided input
  → UNDERSTAND (scoped subjects + plain hard / soft / free) → human confirmation
  → deterministic vocabulary routing from the confirmed cast and source constraints
  → BRAINSTORM candidate events (random batches) → app picks each image's event
  → compatible provisional planning → frozen SceneSpecs
  → IDEAS, five per call, each an idea with its finished scene
  → Builder ENHANCE / Direct with the approved cast → FINAL PROMPT
  → essential fidelity check → valid / unverified / failed per prompt
```

## Owners

| Responsibility | Owner |
| --- | --- |
| Intent extraction, scoped subject inventory, confirmation summary and saved brief validation | `goated_prompter/features/dataset/understanding.py` |
| Source-bound, expiring approval tickets | `goated_prompter/features/dataset/intent.py` |
| Guided assignment indexes and cycling | `goated_prompter/features/dataset/assignments.py` |
| Ideas with finished scenes and lexical duplicate hints | `goated_prompter/features/dataset/ideas.py`, `quality.py` |
| Recent-event RAM history, read and written only by Ideas | `goated_prompter/features/dataset/ideas.py`, `idea_history.py` |
| Chunked idea orchestration and versioned saved-plan validation | `goated_prompter/features/dataset/plan.py` |
| Writer eligibility, shared by API and enhancement | `goated_prompter/features/dataset/eligibility.py` |
| Essential fidelity, repairable findings, warnings and final batch coverage | `goated_prompter/features/dataset/validation.py` |
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

UNDERSTAND extracts only intent and supplied constraints. It generates one scoped
subject inventory (name, count, sex, kind, origin, series and supplied traits),
character count, identity policy, plain hard/soft/free facts, expansion limits and
necessary clarification questions. User-supplied actions, settings and mechanics
remain plain-language requirements; no geometry or support calculations are generated.
`all_outputs` applies to every image, `dataset` to the set, and `guided:N` only to that
line's assignments. Clarifications prevent approval. Added instructions require
reanalysis; the approval ticket is bound to source settings and saved scene edits.
Each character entry's count applies only to that entry. Counts exceeding the declared
per-image total or an incomplete generated inventory receive one source-preserving
correction; a repeated mismatch blocks approval. A null total permits locally varying counts.
Historical checkpoints may retain an older over-counted cast without blocking startup
or rewriting the archive. Continuation and new saves still require valid counts;
an invalid historical approval needs fresh analysis and confirmation.

Understanding does not load vocabulary or return routing diagnostics. After confirmation,
the deterministic router uses the approved scoped inventory and source activity/theme
gates; compatible TXT alternatives feed scene planning. Scene cards display their
`selected_position`, not a semantic pose-adherence guarantee.

The brief also exposes three small scoped lists for approval: **hard** obligations,
**soft** preferences that may yield to hard requirements, and **free** creative
choices within the user's expansion limits. Only approved hard requirements are
immutable. Downstream stages do not infer extra locks or promote their inventions
into requirements. UNDERSTAND generates each scoped fact once in a hard, soft or free
bucket, with only scope and text. It generates no review tags or explanatory context bucket.
The generation schema
reserves one HARD slot for the app-retained character trigger when needed, without
reducing the other buckets' capacities. The app expands these facts into the same public
saved contract, derives the shared character list from the subject inventory, supplies
output-setting prose from the request, and retains the supplied character trigger before
approval. Valid existing full briefs remain supported; saved reviews,
approval tickets, IDEAS and the writer still consume the unchanged public contract.
Fresh plain facts cannot produce cross-authority review tags. Nonconforming responses
remain rejected, without moving or dropping their facts.
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
Confirmation shows the concept, subjects, requirements, stated preferences, open
choices and output settings once, followed by one correction box and Update
understanding, Confirm & Generate and Cancel. There is no duplicated details view,
per-image description, routing explanation or vocabulary diagnostics section.
The server shortens its app-owned source-retention entry for display; the full
contract remains in the approval ticket and generation-log export. Different
wording, literal case/spacing, scopes or authorities remain separate. The display
summary never replaces downstream authority.
Explicit user counts, actions, contacts, exclusions and required visual evidence
belong in hard, retaining their scope and qualifiers. A semantic trait does not
automatically require exposure. Unresolved user conflicts block approval.

For random batches, a brainstorm call (`brainstorm.py`) first lists about three candidate
scenarios per image (what happens and where, each in its own place) with a typicality score.
The app drops events similar to recent runs or current siblings and samples the batch gently
weighted toward unusual events, then passes each image its `event_seed`, which replaces that
image's moment, interaction and setting directions. Randomly invented human characters also
get a look per image built from independent parts (`LOOK_PARTS`: hair length, style and colour,
build, skin tone, plus an age from `AGES` unless one is stated), so each seed draws new people
from hundreds of combinations instead of reshuffling one short list. An unusable brainstorm is reported
and ideas continue without seeds; guided batches skip it.
IDEAS writes five images per call: each record is a one-line idea (the core event) and
its scene, a complete three-to-five-sentence picture with the whole cast in frame,
placement, action, setting, light and camera. The selected Director's instructions (when it
applies to the target) go to IDEAS too, so it decides each scene's framing, camera and light;
the writer then keeps them. The brainstorm gets the same Director section (`director.py`). A
Director built around one kind of shot (selfie, mirror, first person) also replaces each image's
framing direction, lifts the mirror and posing bans, and is not limited as a watching idea.

### Private adult TXT vocabulary

Dataset reads the existing sectioned `data/vocabulary/sexual.txt` directly. Entries are
ordinary prose, one per line. There is no conversion job, JSON catalog or entry-approval
step. Existing TXT and old sidecar files are not modified; sidecars are ignored. Legacy
inline structured entries remain readable, but they are not required.

Understanding identifies the adult cast, sex and supplied anatomy per owner, total count,
requested activities, exclusions and themes. It does not invent poses or contact geometry.
`compatibility.py` gates the sections and filters clear cast, anatomy, activity, theme,
clothing and literal exclusion contradictions before planning:

| Sections | Activation |
| --- | --- |
| `solo positions` | One character; never add a partner or require a toy. |
| `couple positions`, matching `two men`, `two women`, `man and woman positions` | Two characters; eligible alternatives, not positions to combine. |
| `three positions`, `group positions` | Three or four-plus characters respectively. Activities may involve a compatible subset of the cast. |
| `oral`, `anal`, `vaginal positions` | Ordinary compatible activities for multiple adults; prioritize an explicit act. Vaginal activity requires applicable anatomy; hands are possible without inventing male anatomy or a toy. Solo activities must be explicitly solo-compatible. |
| `rules`, `setting`, `mood`, `clothing` | Universal guidance, with clothing filtered against the requested state. Settings and moods are not tied to one act. |
| `interaction`, `group interaction` | Multiple characters, or three-plus, respectively. |
| `kink mood/interaction/setting/clothing/positions`, `solo kink positions` | Requested relevant kink, with the solo/multiple distinction preserved. |
| `pet mood/interaction/positions` | Requested human pet roleplay, independently of other kink. |
| `furniture positions`, `feet positions` | Requested human-furniture or feet-focused theme, respectively. |
| `props`, `toys` | Compatible requested themes; toy use must be requested or explicitly permitted. |
| `finish positions`, `aftercare positions` | Relevant requested moment, not automatic additions to every scene. |
| `ownership rules`, `requested` | Requested ownership, or a positive matching request pattern, subject to compatibility checks. |

Each provisional SceneSpec gets at most three short alternatives for one activity, one
setting, compatible mood/interaction, appropriate clothing and at most one compatible prop.
The planner resolves these into one supported scene, assigning actions and anatomy to their
actual owners. It must not combine contradictory alternatives. Category dealing and unused
position/setting pairs spread suggestions across the batch. Vocabulary choices are not new
hard requirements. Once planning resolves an event, alternative position suggestions are
removed before scene writing. Saved scenes keep their event when vocabulary changes.

Only selected guidance reaches the model; routing diagnostics expose counts and generic
filtering reasons, not entries. Private guidance and raw model diagnostics are omitted from
generation-log exports. Without usable entries, ordinary model planning remains available.
Text filtering and synthetic tests do not prove semantic, anatomical or image correctness.
The existing adults-only, anatomy, consent, incapacitation, death, family, animal, school
and breath-restriction entry checks remain in place. The stage also keeps
every sexual act between the people the request pairs, allows a partner-supported lift during sex, keeps the place and
position next to a required act, drops the moment axis, and draws an adult age for random characters; `adults_only_error` refuses a
sexual or suggestive batch that names someone under 18 or involves an animal before any model call, and brainstorm
events, ideas and final prompts that do so are dropped, repaired or retried. The same stages tie every body part to
its owner and keep visible genitals with their owner's hips and torso in frame; `broken_anatomy`
drops, repairs or retries wording that detaches a body part or merges two people's genitals. Later calls receive the earlier ideas as
existing ideas and share one creative-direction salt, so the
batch stays spread without one long list. Ideas never see the prompt library's prompts;
they get craft notes (`craft_notes.py`) distilled from it once per library version, and any
note that repeats a word specific to the saved prompts is dropped. An
explicit replacement requests only its index. History and diversity hints never
override a guided action or approved hard requirement. There is no Fast/Quality
dispatch, automatic substitute idea or fallback plan.
During a fresh batch, exact normalized duplicates retain the first valid idea and mark
only later repeats for repair; permitted guided repeats remain accepted. Invalid
individual rows also become explicit failed slots without dropping valid siblings.
Valid prompts finish first, then one replacement call requests only failed idea
indexes, followed by their writer calls. Replacement validation still rejects unchanged
or repeated ideas; unsuccessful repairs leave an inspectable partial batch, not an
unbounded retry loop. A brainstorm that loops continues without event seeds; an ideas call that
loops gets one varied retry and then fails only its slots for repair. When near-repeat filtering leaves
too few events, the least typical leftovers fill the remaining slots, so no image falls back to bare
direction labels. Rule texts carry no worked examples, which small models copied into every idea. Lexical similarity remains a nonblocking hint, not semantic
verification. Globally malformed JSON or a wrong batch size gets one format correction
and is otherwise rejected rather than guessing missing assignments.

Across restarts, `idea_history.py` keeps only keyed, 20-bit fingerprints of each idea's key words
in `idea_fingerprints.json` (three-day expiry, no text); the brainstorm prefers candidates that
match none of them. IDEAS owns recent-event memory and checks normalized exact repeats against it,
including when only camera or context changed. Fresh accepted ideas are remembered;
failed slots are not. A repair of a slot that failed as a history repeat is kept rather than rejected again.
An explicit guided input matching the event can still repeat.
History stays bounded in RAM per concept and expires automatically. There is no
manual reset control or endpoint. The writer does not read this history or change an
accepted event for novelty. Semantic variation beyond exact repeats
remains model-guided, not independently verified.

There is no separate scene-building call. Direct generation admits complete, structurally
usable scene contracts to Builder as **unverified**, deferring text fidelity to the final
prompt check. Generate scenes only and Check scene explicitly request scene review.
Edits clear stale proof and reconcile only unlocked mechanics; a failed or repair-required
scene remains blocked until repaired. Validation uncertainty alone does not block writing.

Scenes request one coherent camera angle, shot size and pose per character. The writer may
clarify open mechanics without changing required interactions or the central event.
A deterministic check rejects final prompts that
describe the camera from above and from below at once, because contradictory viewpoints are a
common cause of folded anatomy. When the target's library has prompts, the writer gets a
measured prompt format (range of lengths, structure, section labels, shared trigger; the selected
length picks a point in that range) and two library prompts as templates for how the
prompt is built, drawn at random from the whole library for each image (fixed per scene, so
rewriting one prompt keeps its templates). The target adapter and the Director stay in full: the
look (medium, style, palette, mood) comes from the request, the Style setting and the Director,
never from the templates.
Scene prose is Builder's entire creative input. `dataset_instruction` calls the
existing `assemble_instruction` with **Enhance / Direct**, adds the approved cast and
the applicable hard/soft/free contract. Director, creativity, style, length and target
controls enrich open detail, not a different event, cast or crop. For Anima, count tags
derived from the cast lead the tag block, followed by named characters' Danbooru and
series tags. Count-tag normalization follows the approved cast; the essential final
text check enforces required identities and attributes.
Dataset has no separate final writer. One final text extraction checks approved cast,
identity, route, scoped hard requirements and locked mechanics. Generated open pose,
support, placement, category and setting labels are not mandatory fidelity constraints.
Required contacts have individual locks, so added creative contacts are not promoted
to requirements. Evidence quotations support the result; missing or paraphrased evidence
produces an unverified warning, not a false hard rejection. A known failed requirement
still blocks, even if other validator fields are malformed. Optional checks do not require
another validation call. Shared Builder and MiniMax reference/timeline validation remain
independent and available.

## Recovery and text preservation

Normal **Generate prompts** always runs ideas → prompts after the first
UNDERSTAND approval, regardless of the legacy `plan_scenes_first` saved flag.
**Generate scenes only** is an explicit separate action for manual scene review;
Continue reuses the accepted plan and writes only its missing prompts.

Final enhancement permits at most one bounded retry for transport errors, malformed
target output, missing protected triggers, positive-content leakage and runaway
generation, and for a dropped cast member. These retries never replan the scene. Transport retries repeat
the instruction; output correction stays within the accepted scene and target format.
Runaway retries reduce the output allowance. A sentence-complete prefix may be
accepted only after normal output validation.

Correctable physical inconsistencies get a targeted writer correction. If the bounded
repair leaves only non-hard findings, retain the complete prompt as **unverified** with
warnings; never label it valid. Validator uncertainty or unavailability also retains
unverified output. A recheck cannot clear a known violation in unchanged scene text
without fresh affirmative evidence. Completed unverified prompts are retained on Continue,
not automatically regenerated. Cards and JSONL expose their status and warnings.
Dataset-wide coverage is checked once after writing. A failed or uncertain coverage proof
keeps the batch unresolved without blocking or marking unrelated individual prompts failed.

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

The draft's `seed` and `seed_mode` (randomize, fixed, increment) work like ComfyUI's seed
control. The frontend picks each new batch's seed and sends it with the request without
saving it first; admission saves the request with the other settings, so a rejected run
changes nothing and an admitted one keeps the seed it used. Continue and per-image actions
keep the current seed. A batch run
seeds the app's picks (brainstorm sampling, creative directions, drawn looks) and sends the
seed with every model request; per-image regeneration stays random. With a fixed seed,
recent-idea history is neither read nor written, so a repeated batch is not rejected. The
seed is not part of the plan or intent signatures, so changing it invalidates nothing.

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

# Dataset Scene Composer

Quality planning keeps the full-batch Idea Planner and its existing diversity audit.
Composition uses `SCENE_COMPOSER_CHUNK_SIZE = 4` (4/4/2 for ten ideas).
Fast uses the same chunk size for combined idea/scene planning; local repairs use the Composer.
Each Fast chunk receives the original concept, total amount, current indexes, constraints,
and already accepted idea summaries to avoid repeating earlier ideas. Fixed-idea composition
receives neither variety/history context nor instructions to invent a new idea.

## Output and recovery

- Composer output is one strict JSON array, with the requested indexes and exact fixed ideas.
  Fast output creates ideas; it does not claim that nonexistent supplied ideas must be echoed.
  Neither stage supplies a creative example menu.
- JSON decoding errors receive **SCENE OUTPUT FORMAT CORRECTION**, not a Python exception.
  The previous response is bounded and supplied as source data so the model can reformat its work.
  Developer logs retain the original exception and traceback.
- Each chunk has one bounded format/schema retry. If it remains unreadable, isolate its
  items into bounded single-scene requests instead of stopping the entire batch.
- Scene failures receive up to three local repair calls, preserving the exact idea, action
  and props. Exhaustion marks only that item failed; it never authorizes a replacement idea.
  Successful chunks and other ideas remain unchanged.
- Final prompt writing keeps its initial attempt plus three retries. Exhaustion marks that
  prompt failed without replacing its idea or scene. Failed output is never exported as valid.
- Planner transport retries preserve the current request, any correction and the last completed
  candidate. Connection errors are not output defects and never enter correction instructions.
- Failed items keep their original indexes and bounded `failure_reason` / `failure_stage`
  metadata, with `scene_status` or `prompt_status` set to `failed`. The UI shows the reason
  below the scene and in its failed-prompt card; these records survive saving and reload.
- **Generate prompts from valid scenes** sends `valid_only: true`. It uses only usable
  saved scenes without replanning failed or unfinished items. Individual retry/edit actions
  remain available, and manual edits clear that item's stale failure/replacement metadata.
- Validated chunks publish immediately through the existing partial-job/autosave mechanism.
  Every partial contains accepted work and pending placeholders, not a truncated plan.
  Retrying an incomplete Fast plan generates only missing ideas/scenes; accepted chunks stay intact.
  Fixed ideas with unfinished scenes go through composition/repair, never ideation again.
  Explicit replanning of a completed plan still produces a new plan.
- Parsing remains strict. No automatic YAML conversion or speculative JSON extraction.

## Activity log

**View log** is always available at the bottom-left of the desktop/compact sidebar,
including short windows and views without a generation job. Mobile uses an always-present
button in the sticky header. Opening it before the first job shows an empty state.

## Geometry

`goated_prompter/dataset_staging/` owns enum definitions, profile-required fields,
schema validation, prompt vocabulary and compatibility rules. `dataset_geometry.py` is a
compatibility facade. Canonical values use snake_case;
orientations describe the side presented to camera, not world-space heading.

`gaze_direction` describes eyes; `expression` describes emotion. Unusual poses remain supported
by `pose_type: "custom"` with specific `pose_detail`; `expression_detail` is an optional helper.
Only framing, camera_azimuth, body_orientation, head_direction, gaze_direction and face_visibility
are required for Character composition. Scene prose remains authoritative. Missing optional
metadata, including hand visibility for a hand-dependent action, does not itself trigger repair.
Enum spellings are normalized (trim, lowercase, spaces/hyphens to underscores, collapsed underscores)
before validation; clean mappings require no model retry.
Actions, visibility-focus objects and custom details remain bounded free text. Counts are integers.
Optional fields are not a mandatory inventory. Non-character plans omit irrelevant human fields.
Live profiles advertise general staging rather than specialized/adult enum menus. Historical
specialized facts migrate to applicable details; a detail exceeding its field limit stays bounded
and marks that row for local repair rather than dropping the whole field or valid siblings.

`FramingIntent` records an explicit user/guided crop or a planner-owned crop. Concept, rules and
local guided framing are checked before accepting scenes and final prompts. Conflicting explicit
source crops remain errors. Literal image text, camera distance and mere anatomical visibility do
not establish crop authority. Visible feet/knees never automatically widen Character framing;
an unusual pose may place them inside a tight composition. Equivalent non-human extents map to
the selected profile. A locked crop is never silently widened by deterministic recovery.

Checks cover rear/front and profile-side conflicts, torso/hip opposition, rear shoulder turns,
explicit crop drift, explicit occlusion, hand-dependent actions, closed-eye contradictions,
and explicit selfie camera conflicts. Valid rear-three-quarter over-shoulder views and subtle eye
motion remain allowed. The final writer receives canonical validated staging and translates it
to readable target-specific prose without exposing enum tokens.

## Existing saved plans

Legacy `gaze` and `pose` are migrated conservatively. Formatting-only normalization requires no repair. Ambiguous poses
or unspecified profile sides are omitted, never guessed; migrated scenes are marked for local
geometry repair. Exact ideas, scene prose and existing prompt text are retained. The plan signature
does not globally invalidate old ideas. Target, length and writer-Director changes still reuse plans;
concept/idea changes retain the existing downstream invalidation behavior.

## Boundaries

These are staging guards, not an anatomy solver. Exact joint angles, limb reach, balance,
scene-specific prop relationships, unusual/custom pose plausibility, and complex multi-subject or
reflection staging still rely on the Composer/repair model. Explicit free-prose contradictions use
conservative heuristics; the schema cannot prove the anatomy of a future generated image.
Legacy Fast/guided fallback plans may lack geometry until locally repaired.

Tests exercise every accepted/rejected enum, custom details, counts, legacy migration, strict JSON,
YAML repair, 10/25-scene chunking, local retry, partial recovery, exact idea preservation, writer handoff,
bounded repair/skip behavior, persisted failure reasons, valid-only generation and geometry
disclosure. Browser tests also cover log access across views, mobile and short windows.
Mocked tests do not establish a live model's JSON success rate.

See [Dataset architecture](dataset-architecture.md) for writer and frontend ownership,
and [model-quality evaluation](../tests/eval/README.md) for optional production-pipeline probes.

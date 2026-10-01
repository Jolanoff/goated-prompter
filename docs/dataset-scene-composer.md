# Dataset Scene Composer

Quality planning keeps the full-batch Idea Planner and its existing diversity audit.
Only composition is chunked: `SCENE_COMPOSER_CHUNK_SIZE = 4` (4/4/2 for ten ideas).
Fast still uses its existing combined planning call; local repairs use the Composer.

## Output and recovery

- Composer output is one strict JSON array, with the requested indexes and exact fixed ideas.
  The prompt includes a single placeholder schema example, not creative examples.
- JSON decoding errors receive **SCENE OUTPUT FORMAT CORRECTION**, not a Python exception.
  The previous response is bounded and supplied as source data so the model can reformat its work.
  Developer logs retain the original exception and traceback.
- Each chunk has one bounded format/schema retry. Geometry failures are repaired by index,
  with compact field-specific guidance. Neither retry path calls the Idea Planner.
- Validated chunks publish immediately through the existing partial-job/autosave mechanism.
  Every partial contains all fixed ideas and pending placeholders, not a truncated plan.
  Retrying generation or planning from an incomplete saved plan composes only pending scenes.
  Explicit replanning of a completed plan still produces a new plan.
- Parsing remains strict. No automatic YAML conversion or speculative JSON extraction.

## Geometry

`goated_prompter/dataset_geometry.py` owns all enum definitions, character-required fields,
schema validation, prompt vocabulary and compatibility rules. Canonical values use snake_case;
orientations describe the side presented to camera, not world-space heading.

`gaze_direction` describes eyes; `expression` describes emotion. Unusual poses remain supported
by `pose_type: "custom"` with `pose_detail`; custom expressions require `expression_detail`.
Actions, visibility-focus objects and custom details remain bounded free text. Counts are integers.
Optional fields are not a mandatory inventory. Non-character plans omit irrelevant human fields.

Checks cover rear/front and profile-side conflicts, torso/hip opposition, rear shoulder turns,
crop/body/feet compatibility, explicit occlusion, hand-dependent actions, closed-eye contradictions,
and explicit selfie camera conflicts. Valid rear-three-quarter over-shoulder views and subtle eye
motion remain allowed. The final writer receives canonical validated staging and translates it
to readable target-specific prose without exposing enum tokens.

## Existing saved plans

Legacy `gaze`, `pose` and obvious display spellings are migrated conservatively. Ambiguous poses
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
YAML repair, 10/25-scene chunking, local retry, partial recovery, exact idea preservation, writer handoff
and the collapsed readable UI disclosure. Mocked tests do not establish a live model's JSON success rate.

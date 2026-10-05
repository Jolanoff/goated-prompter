# Frozen failure provenance

`model_outputs/` contains exact existing model responses, not fabricated examples:

- Dataset: inferred gender in a trigger-protected aerial scene.
- Builder: forbidden-rule leakage (`no hat`) despite preserved complex action.
- MiniMax: real motion/H3 response for temporal/reference/structure review.
  Its soundscape refers to a final landing while the timeline holds a suspended
  pose. This is an exploratory temporal-continuity concern requiring review,
  not a proven failure of the current revision.

`current_fixed_engine_failures.json` adds seven selected failures observed on
the current dirty `test` revision with one stable Qwen3.8 27B Q2 engine:

- Dataset portrait trigger/constraint-repair exhaustion, including raw retries.
- Builder and Dataset climbing lock-off contradictions.
- Builder grounded-partner throw drift and Dataset sleeve-grip/underhook confusion.
- MiniMax forbidden peaked cap and invented floor-hand balancing in dialogue.

These preserve exact raw responses, parameters, explicit `stop` reasons, measured
latency, source artifact hash and production code digest. Machine-specific launch
arguments and paths are excluded from the versioned fixture metadata.
Request messages are represented by hashes; the full captured requests remain in
private local evaluation artifacts. Selection is not a failure-rate
denominator. Judgments are exploratory non-blinded agent review, not independent
domain or rendered-media review. The originating local report used 39 samples.

Existing evaluation artifacts also document omitted viewpoint, trigger-repair
exhaustion, contradictory support mechanics, repetition and transport loss.
The repository's deterministic regressions exercise invalid JSON, YAML, wrong
geometry category, gaze/emotion confusion, framing/distance confusion, valid
paraphrases, simplified poses, duplicate ideas, repair loops and unfinished SSE.

**Coverage limitation:** exact raw local-model responses for every requested
failure class have not been located. Their synthetic regression inputs must not
be represented as observed real-model failures. Newly encountered live failures
should be frozen with model/context/settings/revision and exact raw calls.

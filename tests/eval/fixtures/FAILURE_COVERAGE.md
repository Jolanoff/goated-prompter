# Frozen failure provenance

`model_outputs/` contains exact existing model responses, not fabricated examples:

- Builder: forbidden-rule leakage (`no hat`) despite preserved complex action.
- MiniMax: real motion/H3 response for temporal/reference/structure review.
  Its soundscape refers to a final landing while the timeline holds a suspended
  pose. This is an exploratory temporal-continuity concern requiring review,
  not a proven failure of the current revision.

`current_fixed_engine_failures.json` adds four selected failures observed on
the historical dirty `test` revision with one stable Qwen3.8 27B Q2 engine:

- Builder climbing lock-off contradiction.
- Builder grounded-partner throw drift.
- MiniMax forbidden peaked cap and invented floor-hand balancing in dialogue.

The legacy Dataset pipeline's frozen failures were removed with that pipeline; Dataset V2 is
evaluated by its own harnesses (`tests/gpu/dataset_understanding_eval.py`, `tests/gpu/dataset_vocabulary_ab.py`).

These preserve exact raw responses, parameters, explicit `stop` reasons, measured
latency, source artifact hash and production code digest. Machine-specific launch
arguments and paths are excluded from the versioned fixture metadata.
Request messages are represented by hashes; the full captured requests remain in
private local evaluation artifacts. Selection is not a failure-rate
denominator. Judgments are exploratory non-blinded agent review, not independent
domain or rendered-media review. The originating local report used 39 samples.

Existing evaluation artifacts also document omitted viewpoint, contradictory support
mechanics, repetition and transport loss.

**Coverage limitation:** exact raw local-model responses for every requested
failure class have not been located. Their synthetic regression inputs must not
be represented as observed real-model failures. Newly encountered live failures
should be frozen with model/context/settings/revision and exact raw calls.

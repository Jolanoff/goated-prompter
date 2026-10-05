# Model-quality evaluation

This is separate from deterministic `unittest` tests. No model, network, GPU,
downloads or embeddings are needed to replay fixtures and report their metrics.
The corpus covers unrelated specialized domains; it is test data, never a
production concept-to-action mapping. Existing focused probes in
`tests/evaluation/` remain available.

Run from the repository root:

```powershell
python -m tests.eval.runner --dry-run
python -m tests.eval.runner --replay tests/eval/fixtures/model_outputs/real_writer.json --output quality-artifacts/quality-run.json
python -m tests.eval.runner --template quality-artifacts/quality-review.json --replay tests/eval/fixtures/model_outputs/real_writer.json
python -m tests.eval.report quality-artifacts/quality-run.json --output quality-artifacts/quality-report.json
```

`--replay tests/eval/fixtures/model_outputs` combines frozen evaluation runs across
all three workflows. Runs require `run_id` and records with `sample_id` and
`workflow`. Raw scene, geometry, and constraint-audit fixtures use separate schemas
and regression tests; directory replay lists them in `skipped_supporting_fixtures`
instead of treating them as workflow samples. Malformed workflow runs still fail.
Keep live results, hardware details, local paths, and review notes in ignored
`quality-artifacts/` or outside the repository. Top-level evaluation result/notes
files are local-only; reusable corpora, test documentation, and sanitized frozen
regression responses remain versioned. Review fixture metadata before adding it.
Reporting with `--annotations REVIEW.json --require-review --baseline OLD_REPORT.json`
fails on incomplete comparable reviews or fidelity/constraint regressions. Prompt
length never compensates for a lost anchor. CI publishes frozen replay JSON/Markdown;
it does not pretend those old known-failing samples establish current model quality.

Live calls require both `--config` and `--allow-live`; notify the GPU owner first.
Use an explicitly configured existing OpenAI-compatible endpoint: the evaluator
does not start, stop or reconfigure model processes or saved settings.
Match target, length, Director, style and request for Builder/Dataset parity.
Both receive the explicit `eval_subject` identifier and equivalent protected-
identity rules. Sampling follows each production writer's responsibility; record
actual parameters when comparing. Use the older matched-sampling writer runner
for instruction-only comparisons. Repeated trials alternate workflow order.
Dataset parity freezes scenes and bypasses ideation; novelty runs separately use
the actual batch planner and shared recent history (five runs of ten ideas).
Artifacts include raw calls, parameters, completion reasons, repairs and latency.
Use `--novelty --history on` and a matched separate `--history off` run to compare
the existing 40-idea RAM history. Keep its reset independent of durable checkpoints.
Keep model/context/revision constant across comparisons; unseeded trials are
exploratory, not causal evidence.

Review all supplied anchors true/false. Use stable useful-detail fact IDs so
paraphrases and filler do not inflate richness; score materials, lighting,
environment and composition separately. Name reviewer/provenance. Mark optional
video/domain fields null only when not applicable. Group cosmetically different
ideas by the same semantic idea ID. Missing review is **unknown**, never success.
Lexical exclusion checks are conservative diagnostics, not full semantic review.
Freeze real failures with source and exact raw text; never label synthetic
transport/format test data as an observed real-model failure.

# Model-quality evaluation

This is separate from deterministic `unittest` tests. No model, network, GPU,
downloads or embeddings are needed to replay fixtures and report their metrics.
The corpus covers unrelated specialized domains; it is test data, never a
production concept-to-action mapping. It evaluates Builder and MiniMax; Dataset has
no real-model harness yet.

Run from the repository root:

```powershell
python -m tests.eval.runner --dry-run
New-Item -ItemType Directory -Force quality-artifacts/temp/<task-key>/evaluation | Out-Null
python -m tests.eval.runner --replay tests/eval/fixtures/model_outputs/real_builder.json --output quality-artifacts/temp/<task-key>/evaluation/run.json
python -m tests.eval.runner --template quality-artifacts/temp/<task-key>/evaluation/review.json --replay tests/eval/fixtures/model_outputs/real_builder.json
python -m tests.eval.report quality-artifacts/temp/<task-key>/evaluation/run.json --output quality-artifacts/temp/<task-key>/evaluation/report.json
```

`--replay tests/eval/fixtures/model_outputs` combines frozen evaluation runs across
both workflows. Runs require `run_id` and records with `sample_id` and
`workflow`. Historical raw supporting fixtures use separate schemas;
directory replay lists them in `skipped_supporting_fixtures`
instead of treating them as workflow samples. Malformed workflow runs still fail.
Keep live results, hardware details, local paths, and review notes in ignored
`quality-artifacts/` or outside the repository. Top-level evaluation result/notes
files are local-only; reusable corpora, test documentation, and sanitized frozen
regression responses remain versioned. Review fixture metadata before adding it.
Reporting with `--annotations REVIEW.json --require-review --baseline OLD_REPORT.json`
fails on incomplete comparable reviews, missing explicit independent provenance, or fidelity/constraint regressions. Prompt
length never compensates for a lost anchor. CI publishes frozen replay JSON/Markdown;
it does not pretend those old known-failing samples establish current model quality.

Live calls require both `--config` and `--allow-live`; notify the GPU owner first.
Prefer the [task-scoped real-GPU command](../README.md#real-gpu-entry-point),
`python -m tests.gpu.run`, for consistent selection, isolation and output safety.
It delegates to this runner; `--seed` selects fixed scenarios, not model sampling.
Use an explicitly configured existing OpenAI-compatible endpoint: the evaluator
does not start, stop or reconfigure model processes or saved settings.
Sampling follows each production workflow's responsibility; record actual
parameters when comparing. Artifacts include raw calls, parameters, completion
reasons, repairs and latency.
Keep model/context/revision constant across comparisons; unseeded trials are
exploratory, not causal evidence.

Review all supplied anchors true/false. Use stable useful-detail fact IDs so
paraphrases and filler do not inflate richness; score materials, lighting,
environment and composition separately. Name reviewer/provenance and set `review_kind` to
`human`, `independent`, `self_review` or `exploratory`. Only complete `human`/`independent`
annotations qualify for `--require-review` and baseline comparisons. Model self-review remains
diagnostic, never independent ground truth. Legacy/unspecified review provenance does not pass
the independent gate. Mark optional
video/domain fields null only when not applicable. Missing review is **unknown**, never success.
Lexical exclusion checks are conservative diagnostics, not full semantic review.
Freeze real failures with source and exact raw text; never label synthetic
transport/format test data as an observed real-model failure.

Metrics distinguish target-format validity, first-pass validity, trigger fidelity, scene usability,
output repair frequency, transport retries, total calls per completed result and measured latency.
All captured model calls (including production semantic reviews) contribute to cost; reviewer-format
retries and transport failures are not counted as output repairs. A planner repair prevents a pipeline
sample from being first-pass valid even if its first final-writer call succeeds. Missing call history
leaves cost/first-pass metrics unknown. Exact duplicate rates are lexical diagnostics; semantic
repetition, scene/action/pose fidelity and target usability still require explicit anchor review.
Frozen replay measures historical artifacts, not the semantic quality of current code.

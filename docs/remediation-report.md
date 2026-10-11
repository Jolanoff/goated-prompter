# Repository remediation report

Historical report: this describes the pre-compact implementation. Its Dataset
staging validators, separate writer and associated tests were retired under #25.
For the current runtime contract, see [Dataset architecture](dataset-architecture.md).

The deterministic remediation pass is complete against the working tree based on `master` at
`b065b94`. No product UI, dependencies, model processes or persisted user data were replaced.
This report accompanies the local remediation commit. Nothing was pushed. Live inference was not run.

## Confirmed and changed

| Concern | Reproduction and change | Regression evidence |
| --- | --- | --- |
| Destructive generic text cleanup | Parentheses disappeared, semicolons changed, deliberate spacing collapsed and metadata-like text was removed. Generic cleanup now trims outer whitespace only; target adapters and Dataset content checks retain their ownership. | `tests/test_workflow_output.py`, `tests/test_dataset.py` cover punctuation, rendered text, math, protected triggers, idempotence and Builder/Dataset/Refine delivery. |
| Unscoped staging menus | Ordinary Character and non-human schemas advertised specialized/adult pose, gaze, expression, camera and contact enums. Live profiles now use general values from the same registry as validation; custom pose detail stays supported and validated. | `tests/test_staging_capabilities.py`; existing geometry/complex-pose suites. |
| Saved staging compatibility | Removing live enum exposure must not erase historical facts. Saved specialized facts migrate into applicable details. Reproduced detail overflow dropping an entire field; migrated text now stays bounded and flags local repair. | `tests/test_staging_capabilities.py`; saved-geometry migration tests. |
| Framing authority | Concept framing, manual-prose framing and final-writer framing could drift independently. A shared `FramingIntent` now drives eligibility, repair locks and writer checks. Reproduced conflicting crops in one source falling back to planner authority; they now remain explicit errors. | `tests/test_framing_authority.py`, existing source-support and geometry suites. |
| Contradictory stage contracts | Fast was told to echo nonexistent supplied ideas. Fixed composition received ideation/history instructions. Dataset writing inherited unrelated Builder framing and semantic-invention defaults. Stage-specific contracts and dedicated Dataset writer composition remove those conflicts. | `tests/test_dataset_instruction_scope.py`, planner/composer/writer tests. |
| Retry ownership | Provider/transport errors became output-correction instructions. `PlannerCallState` preserves the request, current correction and last completed candidate across transport retries. Recovery limits remain unchanged. | `tests/test_planner_retry_ownership.py`. |
| Frontend scene identity | Raw full-row `JSON.stringify` made key ordering and downstream writer bookkeeping change scene freshness. A canonical scene projection sorts nested object keys, retains source/prose/geometry changes and uses server eligibility. | `frontend/src/datasetState.test.js`; reordered-acknowledgement test in `frontend/e2e/dataset.spec.js`. |
| Frontend orchestration | Dataset API calls, quality-request disposal and job synchronization lived inside the large view. Extracted `useDatasetWorkflow.js`; autosave revisions remain in `useWorkflowSettings.js`, presentation remains in `DatasetTab.jsx`. | Full browser suite, including manual edits, retries, exports, per-item actions and backend recovery after browser close. |
| Evaluation scope and evidence | Existing live writer evaluation did not exercise Dataset planning. Added optional production `pipeline` mode while retaining frozen replay and writer mode. Added trigger/call/repair metrics and an explicitly independent semantic-review gate. Reproduced a planner repair hidden by a valid first writer attempt and missing prompt/trigger results omitted from fidelity; both are now counted correctly. | `tests/test_evaluation.py`, `tests/test_evaluation_runner.py`, `tests/test_semantic_invariants.py`. |
| Documentation drift | Docs described replacement ideas after exhausted scene/writer recovery, optional custom-pose detail, old camera fields and Builder-based Dataset composition. Updated README, Composer guide, evaluation guide and current architecture. | Constants and boundaries cross-checked with their owning modules. |

Behavioral regressions were reproduced before their fixes where practical. The extraction preserves
existing behavior and guards rather than introducing a second state framework. String assertions
were updated only for intentionally replaced instruction contracts; validation expectations remain.

## Confirmed existing behavior and rejected approaches

- **No automatic easier-idea replacement:** scene/writer exhaustion already retains the idea and
  marks the row failed. Preserve that policy; the old documentation, not the runtime policy, was wrong.
- **No blanket framing widening:** Character anatomy/feet do not justify replacing a requested
  crop. Keep applicable product-extent checks, but never silently widen a source-owned crop.
- **No validator weakening:** custom-pose detail, required fields, strict JSON, target structure,
  exact trigger presence and positive-content validation still apply. Saved-data migration is
  separate from live-output acceptance.
- **No removal of unusual user content:** scoped enum menus are not a ban on requested long-tail
  mechanics. Preserve custom details, literal image text and punctuation.
- **No universal scene IR or generic retry engine:** a narrow crop projection solves ownership;
  Planner and writer loops have different validators and recovery units and remain separate.
- **No new coverage planner, example menu or larger generation budget:** reduce duplicated
  instruction responsibilities instead of adding a rule for every observed pose.
- **No deterministic proof of semantic improvement:** frozen known failures, mocked transport
  and production self-review are not independent evidence that the current LLM is more faithful.

## Instruction density

System-message word counts for the same one-item ordinary Character fixture, measured before and
after the pass. These are instruction-size measurements, not tokenizer counts or model benchmarks.

| Stage | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Fast planner | 3,854 | 2,039 | 47% |
| Idea planner | 680 | 680 | unchanged |
| Fixed Composer | 2,441 | 1,740 | 29% |
| Dataset writer | 2,038 | 1,277 | 37% |

The characterized one-item Fast/Composer/writer output budgets remain **1,024 / 1,280 / 768**
tokens. Existing amount/length-dependent budget policies remain in their owning modules.

## Final verification

| Aspect | Outcome | Comparison |
| --- | --- | --- |
| Python unit/integration suite, including built-site checks | **656 passed**, no skips/failures | 633 passed at the earlier sanitizer/staging checkpoint; 23 additional tests since that checkpoint |
| Frontend unit tests | **41 passed** | 38 → 41, three canonical scene-identity tests added |
| Isolated Edge browser suite | **85 passed** | 84 → 85, reordered-acknowledgement regression added |
| Frontend lint | passed, zero warnings | unchanged |
| Production frontend build | passed | unchanged; generated assets remain ignored |
| Diff whitespace check | passed | no errors |
| Frozen evaluation replay/report | **10 historical samples**, all three workflows | historical failures remain visible; semantic review is unknown, not a pass |
| Docs versus owning constants/modules | updated and checked | stale recovery, schema, framing and composition claims corrected |

Commands: `python -m unittest discover -s tests`, `npm.cmd --prefix frontend test`,
`npm.cmd --prefix frontend run lint`, `npm.cmd --prefix frontend run build`,
and `npm.cmd --prefix frontend run test:e2e -- --config e2e/isolated.config.js`
with the virtual environment on PATH and `PLAYWRIGHT_CHANNEL=msedge`.

The Python log and frozen run/report are local at
`C:/Users/jawla/AppData/Local/Temp/opencode/remediation-final-python.log` and
`remediation-frozen-{run,report}.json` in that same directory. The reusable local sweep reference
is `quality-artifacts/remediation-baseline.json` (ignored). It records this completed pass, not an
invented initial-master baseline. Browser tests used isolated temporary stores and ports 8191/5191;
they did not run against a user's existing application instance.

**Verdict:** deterministic regression checks pass. No live-model quality or performance verdict.
Optional real-model calls, independent semantic annotation, provider/hardware latency comparison,
deployment verification and downstream external-consumer builds were not performed. This repo has
no separate frontend typecheck script; the build and lint are its defined frontend static checks.
No independent semantic annotations were fabricated for the frozen replay.

## Remaining evidence gap

Use the opt-in [evaluation workflow](../tests/eval/README.md) against an explicitly configured
existing endpoint to compare matched revisions/settings, repeated trials, both Dataset planning
modes, output validity, repairs, trigger/scene fidelity, duplicates, calls per result and latency.
Annotate anchors with a named independent reviewer. Until that is done, semantic gains and reduced
repair/call rates are hypotheses rather than release evidence. No live-model calls or downloads
were initiated during this pass.

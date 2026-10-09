# Test commands and ownership

Run commands from the repository root with the project's Python environment
(Python 3.10 or newer). The standard library `unittest` remains the test framework.

## Responsibilities

| Location | Responsibility |
| --- | --- |
| `unit/` | Builder, Dataset, MiniMax, refinement, planning, backend and shared contracts with controlled dependencies. |
| `integration/` | HTTP, jobs, persistence, loopback transport and evaluation-to-production wiring using synthetic storage and responses. |
| `eval/` | Maintained corpus, frozen real responses, annotation rubric, metrics, workflow execution and JSON/Markdown reports. |
| `evaluation/` | Specialized Direct/Auto supporting-planning probe; shares capture and run metadata with `eval/runner.py`. |
| `gpu/run.py` | Explicit real-engine dispatch to the existing evaluators. Not discovered as a unit or integration test. |
| `support/`, `helpers.py` | Reused domain fixtures, controlled backends, lifecycle helpers, paths, seeded selection and test-only isolation. |
| `fixtures/` | Existing fixed scene-planner and Understanding replay fixtures. |

Shared fixtures belong in support modules, not executable `test_*.py` modules.
Keep specialized mocks when their session, blocking or failure behavior differs;
do not replace them with a configurable universal backend.

## Deterministic suites

```powershell
python tests/run_synthetic_suite.py --task-key <task-key>
python tests/run_synthetic_suite.py --task-key <task-key> --suite unit
python tests/run_synthetic_suite.py --task-key <task-key> --suite integration
python tests/run_synthetic_suite.py --task-key <task-key> --workflow dataset
python tests/run_synthetic_suite.py --task-key <task-key> --suite unit --workflow minimax
python tests/run_synthetic_suite.py --task-key <task-key> tests.unit.dataset.test_dataset
```

Use the task's issue key or one stable task slug. Without `--task-key`, the
synthetic runner uses `synthetic-suite`. It installs the existing private-storage
guard, blocks local model acquisition, isolates custom Directors and places
temporary test storage under `quality-artifacts/temp/<task-key>/cpu/`.
Temporary storage is removed on exit. Integration tests may open temporary
loopback sockets; they do not perform inference.

The existing CI command remains supported:

```powershell
python -m unittest discover -s tests -v
```

For assistant-run checks, prefer the isolated runner. Its privacy guard belongs
only to test execution, never application startup. Runtime storage tests use
synthetic repositories to verify that the app still reads selected user content
and passes it to generation normally.

The built-site integration check retains its existing skip when `frontend/dist`
is absent. It does not build the frontend. Root-level `local_ui_server.py` and
`understanding_ui_replay.py` remain compatible browser commands; implementations
live under `integration/browser/`. Browser automation is a separate operation.
Set `GOATED_TEST_TASK_KEY` to place their synthetic storage under the task's
`quality-artifacts/temp/<task-key>/browser/`; the default is `browser-tests`.

## Frozen evaluation

Use `tests.eval.runner` and `tests.eval.report`, not a new scoring implementation.
See [the evaluation guide](eval/README.md) for review and regression semantics.

```powershell
New-Item -ItemType Directory -Force quality-artifacts/temp/<task-key>/evaluation | Out-Null
python -m tests.eval.runner --replay tests/eval/fixtures/model_outputs --output quality-artifacts/temp/<task-key>/evaluation/run.json
python -m tests.eval.report quality-artifacts/temp/<task-key>/evaluation/run.json --output quality-artifacts/temp/<task-key>/evaluation/report.json
```

Replay evaluates historical artifacts, not current model quality. Missing human
or independent review is unknown, not a semantic pass. Keep maintained corpora
and sanitized frozen fixtures under `tests/`; generated reports stay ignored.

## Real-GPU entry point

Preview fixed cases without reading endpoint configuration or starting inference:

```powershell
python -m tests.gpu.run --dry-run --workflow dataset --case object
python -m tests.gpu.run --dry-run --workflow builder --case object
python -m tests.gpu.run --dry-run --workflow minimax --case motion
python -m tests.gpu.run --dry-run --workflow dataset --seed 73 --limit 1
python -m tests.gpu.run --probe supporting-planning --dry-run --workflow builder --case hoop
```

`--seed` reproduces case selection and order without changing global randomness.
The selected fixed inputs and corpus digest identify the scenario. It is **not a
model seed**: the current production backend has no seed option, and identical
GPU output is not guaranteed.

Live execution requires explicit owner approval and an owner-managed existing
OpenAI-compatible endpoint. Confirm it is the intended GPU-backed engine; the
runner cannot verify hardware from the API alone. It does not start, stop or
reconfigure model processes, download models, or change saved app settings.
Use a separate endpoint configuration, never private app `data/` as test input.

After approval, the command shape is:

```powershell
python -m tests.gpu.run --workflow dataset --case object --allow-live --config <endpoint-config.json> --task-key <task-key> --max-runs <approved-ceiling>
```

Substitute `builder` or `minimax` and a compatible case for those workflows.
The runner calls `GoatedPrompterService`, `DatasetService` or `MiniMaxService`
through the existing workflow evaluator, with real backend generation and no
mocked writers. Dataset runs UNDERSTAND and requires a human to approve the
source-bound interpretation before ideas, scenes and final enhancement.
Clarifications, refusal or failure stop downstream generation.

`--limit` defaults to one fixed case. `--max-runs` is an explicit workflow-run
ceiling, not a model-call budget: a pipeline may make several calls or repairs.
Selected cases/repeats must fit the ceiling. Multiple runs execute sequentially,
show each result and require confirmation before continuing; errors stop the
command. The opt-in flag does not replace owner authorization.

The supporting-planning probe uses the same entry point with
`--probe supporting-planning`; each selected case has separate Direct and Auto
runs. Its request scaffolding and original review checklist remain distinct from
the workflow corpus. The legacy `tests/evaluation/run_supporting_planning.py`
command remains available, including its existing owned-process lifecycle when
explicitly configured for a local backend; that path needs separate startup,
shutdown and exit-verification approval.

Real-engine results default to
`quality-artifacts/tasks/<task-key>/gpu/results.json`. `--output` and optional
annotation-template paths must stay in that task's `gpu` result or scratch
directory. Existing outputs are refused rather than overwritten. Scratch storage
is isolated under `quality-artifacts/temp/<task-key>/gpu/` and removed on exit.
Reuse the existing reporter for retained results; choose a fresh report path.
Approved baselines remain under `quality-artifacts/baselines/` and are never
automatically replaced or deleted.

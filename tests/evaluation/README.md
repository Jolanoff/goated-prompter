# Dataset semantic evaluation

This opt-in corpus exercises domain understanding, cross-run novelty, long-tail
poses, group support/contact, and consistency constraints. Domain/action hints
exist **only in this test corpus** and are never sent to the model. No model or
dataset is downloaded. Use the same real engine and quantization for comparisons.

From the repository root:

```powershell
.\.venv\Scripts\python.exe tests/evaluation/run_dataset_semantics.py --dry-run
.\.venv\Scripts\python.exe tests/evaluation/run_dataset_semantics.py --config engine.json --group novelty --mode Quality
.\.venv\Scripts\python.exe tests/evaluation/run_dataset_semantics.py --config engine.json --group novelty --mode Quality --without-history
.\.venv\Scripts\python.exe tests/evaluation/run_dataset_semantics.py --config engine.json --group all --mode Quality --artifacts results.json
```

Novelty uses three broad concepts, each with **five separate runs of ten ideas**.
Quality novelty tests ideation only; Fast tests its combined idea/scene path.
Other groups exercise the full existing Dataset pipeline. `--amount 2` and
repeatable `--case cartwheel` options permit small probes, not a full evaluation.
`--dry-run` reports corpus totals, not model performance. Run Fast separately;
successful Quality results do not establish Fast performance.

Production recent-idea memory holds 40 compact summaries per normalized
concept/type, at most 32 concepts, expiring after six hours. It lives only in RAM,
clears on server shutdown, and can be reset with **Reset recent ideas**. Reset
does not invalidate saved plans or prompts. Generate reuses valid plans; use
Plan scenes first for a new idea run. History guides novelty without making prior
ideas absolute exclusions, especially for guided/narrowed concepts.

## Metrics and annotation

Exact repeats, lexical domain/mechanics hints, repair calls, and failures are
computed automatically. These are **not semantic verification**. JSON validity
is not a quality score. Semantic metrics stay `null` without annotations.
Repair frequency means actual repair calls per staged item; it can exceed 1.
Cross-run repeat rates measure later runs only (the first run has no prior pool).
The runner reports per-group metrics to avoid diluting constraint or pose scores
with unrelated cases. Missing final prompts are counted, not silently treated as
successful outputs.

With `--artifacts`, generated content is deliberately saved to the path supplied,
after each completed case/run so earlier results survive a later failure. This
is opt-in evaluation output, not an application checkpoint or draft. Default
evaluation output contains aggregate numbers and diagnostics, not generated text.
The runner unloads its owned local inference process on exit.

Review each `evaluation_id` using the rubric in `dataset_semantics.json` and save
a JSON array of labels:

```json
[
  {"id": "Quality:novelty:festival:1:1", "event_id": "assemble_communal_tables"},
  {"id": "Quality:poses:cartwheel:1:1", "advanced_pose_fidelity": 1,
   "final_prompt_scene_fidelity": 1, "generic_pose": 0}
]
```

```powershell
.\.venv\Scripts\python.exe tests/evaluation/run_dataset_semantics.py --score results.json --annotations labels.json
```

Use the same event ID for the same core event with different wording; cosmetic
presentation changes do not count as novelty. Score support/contact mechanics,
participant roles, and final action retention independently of enum validity.
Annotate forbidden positive content separately from verbalized exclusions;
requested rendered text is exempt. For causal claims, use repeated same-engine
with/without-history trials or a baseline revision; one favorable run is only
exploratory evidence. The syntax compiler deliberately retains conditionals and
unsupported negative rules as unresolved data and flags them for review. It is
not a general English reasoner or synonym detector.

## Builder / MiniMax supporting-planning probe

`run_supporting_planning.py` compares **Direct** and **Auto** on the same engine
for sideways hoop suspension, shared counterbalance, dance progression, explicit
shots/dialogue and symbolic image-identity/video-motion roles. It is independent
of Dataset's batch evaluation and never downloads models or changes saved engine
settings.

```powershell
.\.venv\Scripts\python.exe tests/evaluation/run_supporting_planning.py --dry-run
.\.venv\Scripts\python.exe tests/evaluation/run_supporting_planning.py --config engine.json --artifacts supporting-results.json
.\.venv\Scripts\python.exe tests/evaluation/run_supporting_planning.py --config engine.json --case hoop --target "Krea 2" --artifacts krea-results.json
```

Content-bearing artifacts require explicit `--artifacts`. Review each case's
`review` checklist against the **final prompt** and inspect planner outputs and
actual call stages. Valid JSON/H3 or a successful request is not proof of pose,
dialogue, role or continuity fidelity. Direct uses the current unchanged final
writers, not an older model or different system prompt. Repeat trials and obtain
independent annotations before claiming a general improvement. This runner
unloads only its owned local process on exit. See `SUPPORTING_PLANNING_RESULTS.md`
for the exploratory local probe and limitations.

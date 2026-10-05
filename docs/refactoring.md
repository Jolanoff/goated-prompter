# Application modularity and repository hygiene

## Scope

This document records an earlier refactoring checkpoint. The current application
is standalone-only: the former ComfyUI node, canvas assets, routes, tensor image
adapter, and integration tests have been removed. Website input metadata now
lives in `goated_prompter/input_schema.py`; reference images enter through
`goated_prompter/uploaded_images.py`. Historical test counts below are not current
suite counts.

This is a behavior-preserving first pass at the two largest application modules.
`App.jsx` decreased from 2,022 to 1,090 lines; `local_app.py` from 996 to 667.
API routes, response/error shapes, generation budgets, job revisions, storage
schemas, visual layout, and workflow behavior are unchanged. No model inference,
GPU benchmarks, new dependencies, or deployment flags are needed.

## Module boundaries

### Frontend

- `frontend/src/App.jsx` owns bootstrap, cross-workflow coordination, job recovery,
  autosave, and mutations. It composes views instead of implementing their forms.
- `frontend/src/workflows/BuilderTab.jsx` renders builder controls and output.
- `frontend/src/workflows/ReferenceImages.jsx` renders image slots and mappings.
- `frontend/src/workflows/SavedPromptsTab.jsx`, `SettingsTab.jsx`, and
  `DirectorsTab.jsx` render their respective views with explicit callbacks.
- `frontend/src/components/StudioPrimitives.jsx` owns the shared mark, panel,
  and toggle. Keep existing UI classes and accessible labels stable.

Views do not persist data or call the API independently. Shared state remains in
the coordinator to preserve draft lifetime and existing race protections. Future
work can extract cohesive controller hooks after adding focused lifecycle tests;
avoid replacing one large component with a generic context containing all state.

### Backend

- `local_app.py` still exposes `create_app`, `LocalState`, and the familiar job
  and persistence helpers, preserving existing standalone imports and launch.
- `goated_prompter/local_jobs.py` owns cooperative job state, activity traces,
  cancellation, and delivery. It has no HTTP or workflow dependencies.
- `goated_prompter/json_store.py` owns size-bounded reads and atomic writes.
- `goated_prompter/uploaded_images.py` owns untrusted upload validation/resizing.

Patch limits in their owning modules when testing failures. Do not weaken locks,
safe checkpoints, transport interrupts, atomic replacement, or corruption errors
while extracting additional server responsibilities.

## Safety and verification

Before extraction: 610 Python tests, 38 frontend unit tests, frontend lint, and
84 isolated browser tests passed. Four additional characterization tests cover
mutable snapshot isolation, bounded activity, late transport events, HTTP error
headers, and upload format/default-dimension behavior before moving those modules.
Repository-hygiene tests verify ignore rules and sanitized public fixture metadata.

Final verification passed 617 Python tests in the working tree (including existing
uncommitted planning work), 38 frontend unit tests, 25 ComfyUI JavaScript tests,
84 isolated Edge browser tests, lint, and the production build. The committed
refactor was also tested in a clean checkout: 523 Python tests passed, with the
built-site test skipped because that checkout had no generated frontend assets.

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

For isolated browser tests, run `npm run test:e2e -- --config e2e/isolated.config.js`
from `frontend/` with the virtual environment's Python on PATH. Set
`PLAYWRIGHT_CHANNEL=msedge` if using installed Edge instead of bundled Chromium.

This improves responsibility boundaries, not inference performance. No performance
gain is claimed. Rebuild frontend assets for deployment; the Python entry point
is unchanged. There are no storage migrations or breaking API changes. Reverting
the refactor commits and rebuilding restores the old structure without data loss.

## What belongs in Git

Keep source, lockfiles, configuration templates, reusable evaluation corpora,
and sanitized frozen regression fixtures. Keep these local-only:

- `config/config.json`, `.env*` (except examples), and application `data/`;
- environments, dependencies, compiled assets, caches, logs, and test reports;
- models, runtime binaries, and `quality-artifacts/`;
- top-level `tests/eval/` result JSON and Markdown notes (except `README.md`),
  and `tests/evaluation/*RESULTS*.md`.

Removing a tracked file with `git rm --cached` preserves its local copy. Ignore
rules do not remove previous commits. Published private artifacts require a
separately authorized, backed-up history rewrite. Every affected collaborator
must resync after a rewrite and must not merge old history back in. GitHub may
retain cached commit pages or pull-request refs; sensitive-data removal from
those requires GitHub Support. Contributor statistics may take time to refresh.

The authorized cleanup rewrote and atomically force-pushed both published
branches, `master` and `test`, removing private reports/config from their history
and reattributing the secondary account's four commits to the primary account.
Private backups remain outside this repository. Old local branches are retained
for recovery: **do not push backup branches or the old `main` branch**, and do
not use `git push --all`. The cleaned refactor remains local on
`refactor/application-modularity`; it was not merged into the published branches.

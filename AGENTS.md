# Goated Prompter project policy

Before every task, read and follow the mandatory
[Goated Prompter workflow](.opencode/skills/goated-prompter-workflow/SKILL.md).
If it cannot be loaded, stop and ask; do not bypass these gates.

This policy defines project boundaries; the local skill defines the procedure and
must agree with them. Stop for clarification if they conflict. Generic skills do
not authorize extra scope, operations or workflow artifacts.

## Boundaries

- Ask for explicit, task-scoped approval before local file operations, shell/Git
  commands, or CPU/GPU workloads. Ordinary task requests are not resource approval.
- Obtain separate approval for tests/lint, builds, browser automation, downloads,
  servers, inference, benchmarks, and model-process changes when not already authorized.
- Resource approval is task-scoped and names the permitted operations, protected
  categories and limits. Retain granted approvals for this task; ask again only
  for an uncovered category, increased limit or changed scope. Implementation
  approval does not imply resource or publication approval.
- For GitHub-delivered repository changes, including policy and documentation
  changes, reuse one matching issue; create one only when none exists and GitHub
  operations are authorized. Investigation, evaluation, proposals and explicitly
  local-only work do not require new issues. Never recursively create sub-issues.
- Keep changes within the approved outcome and acceptance criteria. Use the
  smallest sufficient diff. No unrelated refactoring, speculative improvements
  or automatic follow-up tasks.
- Preserve unrelated edits and unfinished tasks.
- The `data/` privacy restriction applies to the coding assistant and its tools,
  not the running app or the user's local LLM. Do not inspect, search, list, copy
  or migrate private `data/` contents. Keep normal app reads/writes and the handoff
  of selected content to the local LLM working; do not implement this assistant
  restriction as a runtime sandbox, file-access ban or prompt-redaction rule.
- Keep evaluation corpora under `tests/` and generated evaluation artifacts under
  `quality-artifacts/`, separate from app `data/`. Tests run by the assistant use
  synthetic temporary storage; their privacy guards do not belong in app startup.

## Git and issue workflow

- Reuse the task's matching approved branch throughout its lifecycle; it must be
  issue-specific for GitHub delivery. Local-only work does not require an issue
  to use an approved task branch. Create the branch once from the approved `test`
  baseline only when needed and authorized. Do not use an unrelated branch, edit
  `master`, or apply task changes directly to `test`.
- Continue all authorized verification and delivery steps. Commit only the
  task's changes and report actual verification results on GitHub when publishing
  is authorized.
- Merge into `test` only after required checks and owner manual testing/review
  are complete and the owner explicitly authorizes merging the specific task/PR.
  After a verified authorized merge, complete issue closure, safe synchronization
  and merged-branch cleanup. Otherwise retain the open PR, issue and source branch.
- Never update local or remote `master` by any route; only the owner manually merges it.
- Before starting, check the working tree, current branch and recent local branches. Another session's uncommitted or unpushed work is never overwritten, reset or discarded; continue it only when the owner agrees.
- Stacked PRs may target the previous task branch for review only. Retarget each to `test` once the PR below it has merged, and merge only into `test`. A PR merged into another task branch has not been delivered.

## Code structure

Put code where its owner lives. Find the owner here before editing or adding a file.

| Location | Owns |
| --- | --- |
| `goated_prompter/features/<tab>/` | One package per app tab: `builder`, `refine`, `minimax`, `dataset`, `saved_prompts`, `presets`, `settings`. Its service, routes, runner, contracts/validation and tab-only prompt text. |
| `goated_prompter/options/` | Every user-selectable option name, alias map and limit, defined once. Prompt text for an option stays with its owner. |
| `goated_prompter/prompting/` | Prompt text and target adapters shared by several tabs. |
| `goated_prompter/contracts.py`, `backends/`, `planning/`, `api/common.py`, jobs and stores | Shared infrastructure. |
| `local_app.py`, `workflow_runners.py` | App wiring, state, job admission and static assets; dispatch to each tab's runner. No workflow logic. |
| `frontend/src/features/<tab>/` | A tab's components, hooks, utilities, `options.js` and colocated `*.test.js`. |
| `frontend/src/shared/`, `frontend/src/components/` | Frontend code genuinely used by several tabs. `App.jsx` only coordinates tabs. |
| `tests/unit/<area>/`, `tests/integration/<area>/` | Deterministic tests by workflow or concern. |
| `tests/gpu/workflows/<tab>.py`, `tests/eval/` | Opt-in real-engine runs and evaluation. |

Dependency direction:

- `contracts`, `options`, `prompting`, `backends` and `api/common` never import from `features/`.
- A tab may use another tab only through that tab's public behaviour (Dataset delegates final enhancement to Builder). Never import another module's `_private` names.
- Fix an import cycle by moving the shared piece to its owner, not with a function-level import.

## Avoiding duplication and drift

- Before adding a function, constant, option, validator or helper, search for an existing one and extend its owner. One definition per option list, contract and validation rule.
- Keep code in its tab until a second tab needs the same behaviour, not merely similar-looking code. Do not merge distinct workflows or retry policies because they look alike.
- A frontend list that mirrors a backend option catalog needs coverage in `tests/unit/shared/test_option_parity.py`.
- After moving code, update every import, test, patch target, package-data rule and document. Do not leave compatibility re-export modules, wildcard imports or shims.
- Split a file when it mixes responsibilities, not to reach a line count. Do not create files, wrappers or abstractions without a second real user.
- Move code unchanged in a structural change. Behaviour, prompt and copy changes go in their own task with their own verification.

## Public Git/GitHub writing

- Write commits, issues, PR descriptions and comments in the owner's concise developer voice: product changes, actual test results and relevant product limitations only.
- Never publish CPU/GPU usage, resource budgets, inference-run accounting, timing/token benchmarks, process cleanup, permission discussions, session transcripts or internal agent reports. Keep those details in chat or ignored local artifacts, not Git or GitHub.
- Before every commit or GitHub create/edit/post, review the exact outgoing text against this boundary. Remove internal reporting before publishing; do not paste a completion report into a PR or issue.
- Update existing public text when correcting it instead of adding conversation-style status logs. These rules apply to every future task, not just the current PR.
- Add no AI attribution: no `Co-Authored-By` trailers for assistants, no session links and no "Generated with" footers in commits, issues or PRs.

These rules apply to code, tests, documentation, audits and workflow changes.

## Local model location

- The owner-provided local model folder is `G:\AI\models\LLM\qwen3.8`.
  Use this known location for approved GPU tests rather than asking for it again.
  It contains the Qwen3.8-27B Uncensored HauhauCS Aggressive model and matching
  mmproj. This reference does not waive task-scoped resource approval or authorize
  changing the owner's saved model settings.

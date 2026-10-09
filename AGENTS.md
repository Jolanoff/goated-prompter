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

## Public Git/GitHub writing

- Write commits, issues, PR descriptions and comments in the owner's concise developer voice: product changes, actual test results and relevant product limitations only.
- Never publish CPU/GPU usage, resource budgets, inference-run accounting, timing/token benchmarks, process cleanup, permission discussions, session transcripts or internal agent reports. Keep those details in chat or ignored local artifacts, not Git or GitHub.
- Before every commit or GitHub create/edit/post, review the exact outgoing text against this boundary. Remove internal reporting before publishing; do not paste a completion report into a PR or issue.
- Update existing public text when correcting it instead of adding conversation-style status logs. These rules apply to every future task, not just the current PR.

These rules apply to code, tests, documentation, audits and workflow changes.

## Local model location

- The owner-provided local model folder is `G:\AI\models\LLM\qwen3.8`.
  Use this known location for approved GPU tests rather than asking for it again.
  It contains the Qwen3.8-27B Uncensored HauhauCS Aggressive model and matching
  mmproj. This reference does not waive task-scoped resource approval or authorize
  changing the owner's saved model settings.

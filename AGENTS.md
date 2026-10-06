# Goated Prompter project policy

Before every task, read and follow the mandatory
[Goated Prompter workflow](.opencode/skills/goated-prompter-workflow/SKILL.md).
If it cannot be loaded, stop and ask; do not bypass these gates.

## Boundaries

- Ask for explicit, task-scoped approval before local file operations, shell/Git
  commands, or CPU/GPU workloads. Ordinary task requests are not resource approval.
- Obtain separate approval for tests, builds, browser automation, downloads,
  servers, inference, benchmarks, and model-process changes when not already authorized.
- Create or reuse a matching GitHub issue before investigating or changing anything.
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

- Work on a new issue-specific branch from the approved `test` baseline.
- Respect any outstanding manual-testing gate before merging into `test`.
- Commit only that issue's changes, merge completed work into `test`, report the
  actual verification on GitHub, and close the issue when the agreed checks are complete.
- Never update local or remote `master` by any route; only the owner manually merges it.

These rules apply to code, tests, documentation, audits and workflow changes.

# Goated Prompter project policy

Before every task, read and follow the mandatory
[Goated Prompter workflow](.opencode/skills/goated-prompter-workflow/SKILL.md).
If it cannot be loaded, stop and ask; do not bypass these gates.

## Required skill preparation

Before task-specific planning, investigation or implementation, load skills in order:

1. `goated-prompter-workflow` first.
2. Relevant project-local skills, discovered from available metadata or an approved
   inspection of `.opencode/skills/`. Do not load unrelated skills wholesale.
3. `best-practices`.
4. `code-quality`.
5. Other skills matching the task.

Follow the workflow's permission and issue gates before local discovery/reads.
If a required skill is unavailable, stop and ask; do not silently skip or install it.
Apply only guidance relevant to the approved task. Skill loading does not authorize
audits, tests, inference, delegation, commits or other additional operations, and
generic skill guidance cannot override the project boundaries below.

## Boundaries

- Ask for explicit, task-scoped approval before local file operations, shell/Git
  commands, or CPU/GPU workloads. Ordinary task requests are not resource approval.
- Obtain separate approval for tests, builds, browser automation, downloads,
  servers, inference, benchmarks, and model-process changes when not already authorized.
- Create or reuse a matching GitHub issue before investigating or changing anything.
- Preserve unrelated edits and unfinished tasks.

## Git and issue workflow

- Work on a new issue-specific branch from the approved `test` baseline.
- Respect any outstanding manual-testing gate before merging into `test`.
- Commit only that issue's changes, merge completed work into `test`, report the
  actual verification on GitHub, and close the issue when the agreed checks are complete.
- Never update local or remote `master` by any route; only the owner manually merges it.

These rules apply to code, tests, documentation, audits and workflow changes.

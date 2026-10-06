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
- Commit only that issue's approved changes. Publishing the issue branch requires
  explicit Git/network approval.
- Create or reuse a pull request with `test` explicitly selected as its base before
  delivery. Do not merge locally into `test` or push directly to `test` as a substitute.
- Link the active issue and pull request to the session as soon as they are known.
- Merge the pull request only with explicit authorization, after agreed checks and
  any manual-testing gate are satisfied; never bypass branch protections.
- Report the actual PR state and verification on GitHub. Close the issue only after
  its PR has merged into `test` and the agreed checks are complete. A local merge,
  published branch or open PR does not count as delivered work.
- Never update local or remote `master` by any route; only the owner manually merges it.

These rules apply to code, tests, documentation, audits and workflow changes.

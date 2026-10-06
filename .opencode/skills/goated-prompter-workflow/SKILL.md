---
name: goated-prompter-workflow
description: Mandatory workflow for every Goated Prompter task. Load this first, then relevant project-local skills, best-practices, code-quality and other task-specific skills before planning or execution. Enforces issue-first work, explicit resource permission, issue-specific branches and authorized delivery only through a pull request targeting test. Only the owner updates master.
---

# Goated Prompter workflow

Use this skill for every task in `Jolanoff/goated-prompter`, including fixes,
features, refactors, documentation, audits and workflow changes. Load it before
starting work. This is the owner's project policy, not an optional recommendation.

## 0. Prepare skills before task-specific work

Load and read skills in this order, before task-specific planning, investigation
or implementation:

1. This `goated-prompter-workflow` skill.
2. Relevant project-local skills. Consult advertised skill metadata first; when
   local discovery is needed, inspect `.opencode/skills/` metadata only after the
   resource and issue gates below are satisfied. Load the local skills whose
   descriptions match the task; do not load unrelated skills wholesale.
3. `best-practices`.
4. `code-quality`.
5. Additional task-specific skills, such as debugging for a bug, test-writing for
   regressions, or design guidance when choosing an approach.

The permission request, matching-issue setup and approved discovery needed to
prepare skills are prerequisites, not permission to begin the substantive task.
Use the host's skill loader when available; otherwise read the installed skill's
`SKILL.md` only with file-access approval. Read applicable bundled references when
needed, not entire skill directories by default. If a required skill cannot be
located or loaded, stop and ask; do not silently omit it, download or install it.

Both quality skills are required preparation for every project task. Apply their
guidance within its actual scope: `best-practices` covers applicable web security,
compatibility and quality concerns; `code-quality` checks approved requirements
first, then correctness and maintainability. A documentation-only task does not
become a browser/security audit merely because these skills were loaded.

Generic skill recommendations do not override this project's gates. In particular,
loading a skill does not authorize file access, tests, builds, audits, inference,
model-process changes, agent delegation or Git delivery. Keep work scoped and
preserve unfinished changes; do not follow generic commit/refactor advice against
the owner's branch-only or manual-review instructions. Briefly state the selected
skills and applicable checks in the task plan, and report unrun checks honestly.

## 1. Ask before using local resources

- Ask for explicit permission before local operations: file reads/writes, shell
  or Git commands, tests, builds, lint, browser automation, servers, downloads,
  model inference, benchmarks, or other CPU/GPU workloads.
- Describe the operations and their scope. Request lightweight file/Git access
  separately from compute-intensive checks or inference; state expected duration
  and CPU/GPU use when known.
- An instruction to fix a bug is not resource approval. Permission applies only
  to the stated task and operations, not future tasks or additional workloads.
- Do not start, stop, unload or take ownership of the user's model processes
  without explicit approval. Do not assume idle hardware is available.
- If permission is missing or denied, stop the affected operations, offer a
  text-only plan, and report verification as not run. Never imply unrun checks passed.

## 2. Establish the GitHub issue before work

- Search `https://github.com/Jolanoff/goated-prompter/issues` for a matching issue.
  Reuse it instead of creating a duplicate; reopen it if further work is required.
- If none exists, create an issue describing the requested scope, known evidence
  and acceptance criteria before implementation, investigation commands or edits.
- Creating/reusing the issue and obtaining resource permission are prerequisites,
  not exceptions permitting unrelated work. If GitHub access is unavailable, stop
  and ask rather than silently working without an issue.
- Keep reports free of credentials, private prompts, images and personal paths.
- Link the active issue to the session as soon as it is known, using the host's
  session-link tool when available. Link a PR for this work as soon as it is known
  too; do not link unrelated issues or PRs merely mentioned in passing.

## 3. Work on a new issue-specific branch

- After resource approval, inspect the working tree and `test`. Preserve all
  unrelated edits and unfinished tasks; never stash, reset or stage them implicitly.
- Start a branch from the current approved `test` baseline, such as
  `fix/issue-<number>-<description>` or `chore/issue-<number>-<description>`.
- Scope changes to the issue. Add regressions before behavioral fixes when
  practical, but run them only with the required resource permission.
- Record checks actually performed and any outstanding manual-testing gate.

## 4. Deliver through a pull request to test, never master

- Commit only the issue's changes on its new branch, referencing the issue number.
  Use `Refs #<number>`, not automatic closure keywords that could close it upon a
  future `master` promotion without the completion check below.
- Publish only the issue branch within the approved Git/network scope, then create
  or reuse a matching GitHub pull request. Explicitly select `test` as the base and
  the issue branch as the head; never rely on the repository's default branch.
  Verify the PR's actual base/head and link it to the session before continuing.
- A pull request is required for delivery into `test`. Do not merge locally into
  `test` or push directly to `test` to bypass it. A published branch or open PR is
  not a completed merge. If publication/PR creation is not approved or GitHub is
  unavailable, stop at the authorized boundary and leave the issue open.
- Merge the PR only with explicit merge authorization, after the agreed checks
  and any owner manual-testing sign-off. Creating a PR does not authorize merging
  it or enabling auto-merge. Verify its base is still `test`; do not bypass branch
  protections, force-push or rewrite unrelated history. Stop on conflicts, failed
  required checks or unexpected remote changes.
- Confirm GitHub reports the PR merged into `test` before reporting delivery.
  Synchronize local `test` only after that confirmed merge and only within approved
  Git operations, preserving unfinished edits.
- After the confirmed PR merge and agreed completion checks, comment on the issue
  with the PR, commit, delivered scope, verification and limitations, then close it
  as completed. Leave open PRs, blocked, unverified or manual-review-pending work
  with their matching issues open; do not close an issue after a local-only merge.
- Only the owner manually promotes `test` into `master`. Never merge to, commit on,
  push to, reset, delete or otherwise update local or remote `master`. Never use a
  refspec, API action, PR auto-merge or other indirect route to bypass this rule.

## Completion report

Report the issue and PR links, source branch and commit, actual PR state and base,
whether it merged into remote `test` and whether local `test` was synchronized,
whether the issue is closed, checks actually run, outstanding approval/manual
testing, and that `master` was untouched. Do not silently resume unrelated work.

---
name: goated-prompter-workflow
description: Mandatory for every Goated Prompter task. Enforces minimal scope, code placement by owner without duplication, one issue/branch lifecycle, root-cause fixes, task-scoped resource approval, verified process cleanup and owner-gated delivery to test.
---

# Goated Prompter workflow

Follow `AGENTS.md` for project boundaries, including assistant-only `data/`
privacy, synthetic test storage, protected branches and public writing. Do not
weaken those rules or turn the assistant's privacy restriction into app behavior.
Load only skills needed for the approved work; generic skills do not expand it.

## 1. Scope

- Establish the approved outcome, exclusions, acceptance criteria and
  authorization before substantive work. Keep this brief; do not generate a
  plan/report file by default.
- Use the smallest sufficient diff. No unrelated refactoring, dependencies,
  speculative improvements or automatic follow-up tasks.
- Additional findings belong to this task only when necessary to its approved
  outcome. Otherwise report them without implementing or opening follow-ups.
- A genuinely required scope change needs owner approval before implementation;
  a related finding is not permission to expand the task.
- Before editing, locate the owning module with the `AGENTS.md` code-structure
  map and search for an existing function, option, validator or helper that
  already does the job. Extend the owner; never add a second copy.
- New code goes in its tab (`features/<tab>/`, frontend `features/<tab>/`) and
  options in `options/` or the tab's `options.js`. Move code to a shared module
  only when a second tab needs the same behaviour.

## 2. Authorization

- Track approved operation categories and limits in session context. Do not
  request an approval already granted for this task or carry it into another task.
- Preserve explicit authorization for file operations, shell/Git, publication,
  tests/lint, builds, browser automation, downloads, servers, inference,
  benchmarks, CPU/GPU workloads and model-process changes.
- Ask once for a clearly described operation set. Ordinary implementation
  requests do not authorize protected resources; publication does not authorize
  tests or inference, and no pre-review approval authorizes merge.
- Ask again only for an uncovered category, increased limit, changed scope or
  actual blocker requiring a decision. Do not stop for a normal authorized step.

## 3. Issue and branch

- Use one matching issue, one active task branch and one PR for each
  GitHub-delivered logical task, including policy/documentation changes. Look
  for suitable existing task state before creating anything.
- Reuse them across investigation, fixes and verification. Do not split findings
  into issues or branches without an explicit owner-approved split; never
  recursively create sub-issues.
- Investigation, evaluation and proposals create no issues or branches by
  themselves. Explicitly local-only work does not require a GitHub issue.
- Follow the root branch rule before repository edits. Confirm the branch belongs
  to this task and its approved `test` baseline; preserve unrelated work.
- Check `git status`, the current branch and recent local branches first. If
  another session left uncommitted or unpushed work, stop and ask the owner
  before continuing it; never reset, overwrite or discard it.
- Link each working issue and PR separately with OpenChamber `session.link` as
  soon as its URL is known, whether provided, opened or resolved by this work.
  Include URL, title, kind and identifier; do not link passing references.

## 4. Root cause and verification

- For defects, establish a runnable reproduction before editing and identify the
  causal implementation path. Fix the general behavior, not the reported input:
  no literal-input exceptions, special-cased outputs or weakened assertions.
- Add focused deterministic regression coverage for the reproduction and a
  materially different input or boundary case where practical. Do not modify
  tests merely to accept broken behavior or broaden coverage unrelated to the fix.
- Run only checks justified by the changed behavior and approved resources.
  Inspect actual results and rerun the reproduction or equivalent verification.
- For policy/docs-only changes, review text, consistency and the diff; app tests
  are not required merely because files changed.
- If reproduction or verification is unavailable, state the limitation rather
  than claim a fix. Deterministic tests alone do not prove model-quality gains;
  one unseeded GPU sample does not prove deterministic correctness.

## 5. GPU execution and process cleanup

- Request a Dataset GPU maximum only if none was explicitly approved: ask
  "How many GPU tests do you want me to run?" Treat it as a ceiling, not a quota.
- Use a maintained prebuilt example and synthetic temporary test storage. Run
  sequentially: test, inspect, diagnose, repair if authorized, verify. Never batch
  all iterations first; stop once sufficient evidence exists.
- Count an iteration when its first real inference request begins; a failed
  earlier endpoint probe does not count. Ask before exceeding the maximum.
- Use the model location in `AGENTS.md` for approved GPU tests; do not change
  the owner's saved model settings without separate authorization.
- Before starting a temporary model, server or test process, obtain authorization
  covering startup, shutdown and exit verification. Record its identity and
  ownership, including owned children; plan teardown before startup.
- Clean up owned processes when their work ends, including failure, cancellation
  and review waits. Use finally-style teardown where possible. Verify identity
  before stopping processes; never use a broad kill-by-name operation.
- Never stop pre-existing processes without explicit permission. If the owner
  explicitly requests retention, keep them running and report that exception.
- Verify owned processes exited. Report cleanup failures or unverified exits in
  chat; do not claim cleanup succeeded without checking.

## 6. Artifact lifecycle

Create only the directories and files actually needed:

```text
quality-artifacts/
  baselines/
  tasks/<task-key>/
    gpu/results.json
    gpu/comparison.json
    browser/screenshots/<case>-<viewport>.png
    report.json
  temp/<task-key>/<test-type>/
```

Use existing output flags or safe scratch isolation. If a tool cannot comply,
report the limitation before running instead of inventing persistent paths.

1. Choose one task key: the existing `issue-<number>`, or one stable task slug for
   issue-free work. Reuse it throughout investigation, fixes and verification.
2. Group by test type, not attempt. Do not invent folders for each fix, retry,
   screenshot or verification phase. Runner-required per-test/retry directories
   belong in task scratch space, not permanent storage.
3. Write intermediate output to `temp/<task-key>/<test-type>/`. Reuse stable paths
   only when their contents are known disposable and task-owned.
4. Generate evidence selectively. Create reports, screenshots and captured logs
   only for a concrete debugging, verification or requested-deliverable purpose.
   Do not produce a Markdown completion report by default.
5. Promote only useful final results/reports, approved baselines, reproducible
   failure evidence and explicitly requested artifacts. Keep task evidence under
   `tasks/<task-key>/`, with enough input/configuration/revision context to
   reproduce retained failures; approved generated baselines belong in `baselines/`.
6. Preserve comparisons deliberately. Keep `results.before.json`,
   `results.after.json` and `comparison.json` only when the comparison matters.
   Use separate run IDs only for comparisons, nondeterminism investigation or
   retained failure evidence, not every retry.
7. Never silently overwrite baselines, comparison data, retained failures or
   unknown pre-existing files. Preserve them or obtain an explicit replacement
   decision before reusing paths. Never point a runner that resets its output
   directory at retained evidence.
8. Include deletion of this task's newly created scratch files in its artifact
   authorization. If already explicitly approved, clean them up without asking
   again; otherwise request the missing permission. Record created paths.
9. Before completion, select retained evidence, then remove only recorded
   task-owned temporary artifacts and unnecessary outputs covered by approval.
   Verify cleanup. Preserve needed interruption/failure evidence; report blocked
   or incomplete cleanup honestly.
10. Never automatically delete another task's artifacts, approved baseline
    fixtures or regression corpora. Retained evidence has no automatic global
    expiry. All generated evaluation artifacts remain Git-ignored; maintained
    corpora remain under `tests/`.

## 7. Delivery and completion

- Continue authorized verification, commit, push and PR steps without stopping
  after an intermediate fix. Inspect the full task diff before staging; include
  only task changes and exclude generated evidence or unrelated edits.
- "Complete and deliver this task to test" authorizes task staging, commit, push,
  one PR with `test` as base, issue updates and a review-ready report. It does not
  authorize resource workloads, merge, issue closure as delivered or deletion of
  the unmerged source branch. Local-only approval implies no publication.
- When a task depends on an unmerged one, its PR may target that task's branch
  for review. Before merging, retarget it to `test` (after the PR below it has
  merged) and confirm the merge landed in `test`; merging into another task
  branch is not delivery.
- Before committing a structural change, confirm the moved code is unchanged
  apart from imports and that no old path is still imported or re-exported.
- Delivery approval, green CI, "looks good" and "proceed" are not merge permission.
  Wait for owner manual testing/review and an explicit instruction to merge the
  specific task/PR. Material changes after review need renewed confirmation.
- At that gate, retain the open PR, issue and branch. Report readiness once;
  do not bypass it through auto-merge, a merge queue, direct `test` updates or
  local merges. Never target or update `master`.
- After task-specific merge authorization, recheck the diff and required checks,
  merge into `test` and verify GitHub reports it merged. Update the task issue
  with changes, actual verification, limitations and the PR reference; close it.
- Complete agreed safe synchronization and local/remote merged-branch cleanup
  unless the owner requests retention. Verify task changes were delivered; never
  delete branches containing unmerged/unpushed work or discard unrelated edits.
- Verify repository and GitHub state before reporting completion. Stop only at
  a real authorization/review gate, failed check, unsafe conflict, unexpected
  remote change or other blocker that cannot safely be resolved within scope.

## 8. Evidence and communication

- Follow the root public-writing boundary. Review exact outgoing text before
  every commit or GitHub create/edit/post; correct existing text in place rather
  than adding conversation-style logs.
- Keep issue text short: `## Task`, `## Acceptance criteria` and optional
  `## Context`. Describe the requested change and concrete criteria, not the
  session, tool permissions or internal execution instructions.
- Never commit generated evidence or publish internal reporting by pasting it
  into GitHub text.
- Report only outcome, actual verification, lifecycle state and actionable
  blockers. Include resource/cleanup details in chat only when relevant; GPU
  evaluations include iterations used versus maximum and why they stopped.
- Distinguish verified, unverified, blocked and review-ready states. Never claim
  success from edits alone or imply checks ran when they did not. Pending owner
  review is intentional, not merged delivery or a reason to close the issue.

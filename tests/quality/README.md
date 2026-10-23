# Quality check

Shows whether a change makes Goated Prompter better, worse or no different, instead of guessing.

```bat
quality.bat            :: full run: audit, live comparison on your model, checks, report
quality.bat audit      :: audit only: no model, takes seconds
quality.bat report     :: rebuild the latest report after you saved review.json
quality.bat judge      :: let the model in quality.json judge the latest run blind
quality.bat clean      :: remove the old code copies made for comparisons
```

Agents and terminals use the same commands as `python -m tests.quality [audit|report|judge|clean]` (add
`--no-open` to skip opening the browser; set `QUALITY_NO_PAUSE=1` to stop `quality.bat` from waiting).

## Settings

`quality.json` in the project folder holds your settings and requests. The first run makes it from
`tests/quality/quality.example.json`. It is never tracked, and neither are the results in
`quality-artifacts/quality/<run>/`, so your requests and outputs stay on your computer.

| Setting | Meaning |
| --- | --- |
| `baseline` | The old code: a commit, branch or tag. `HEAD` is the last commit. |
| `candidate` | The new code: `working` (this folder as it is now) or a commit. |
| `model_config`, `app_settings` | The app's config and saved settings (Models folder, keep loaded). |
| `model_profile` | Which model runs: its id or name. Empty uses the model selected in the app, else the first ready one, as the app does. |
| `seeds` | Every case runs once per seed, on both sides, with the same seed. |
| `live` | `false` runs only the audit. |
| `judge.mode` | `manual` (you review in the report), `llm` (a model judges; `judge.config` picks it, `judge.kind` says whether that review counts) or `off`. |
| `cases` | The requests. `kind` is `builder` (with `idea`) or `dataset` (with `subject`); optional `target`, `director` (id), `length`, `creativity`, `style`, `capture`, `aspect` (dataset: a ratio such as `3:4`), `mode`, `rules`, `amount`, `nsfw`, `triggers`, `vocabulary_packs`, `inputs`. |

## What a run does

1. **Audit** (both sides, no model): reads every guide (Mode, target, Length, Creativity, Director, Style, NSFW,
   Dataset scene and prompt rules, planner, repair) and the instructions the Builder assembles for each setting.
   It lists collisions (a guide using the words of a decision another setting owns, `owners.json`), the same rule
   written twice, settings that no longer build, and every sentence that changed. Accepted exceptions live in
   `audit_allow.json`, each with its reason. The audit never reads the private `data/` folder.
2. **Live comparison**: runs every case and seed through the app's real pipeline, once with the old code and once
   with the new, using your model, Prompt Library and vocabulary packs as the app does. The old code runs from a
   copy in `quality-artifacts/worktrees/` that shares your `data/` folder.
3. **Automatic checks**: written prompts, format, cast kept, ruled-out words, leftover labels ("man 1", "the first
   man") must never get worse; repeated looks, places and props and prompt similarity should improve.
4. **Blind review**: each case and seed becomes a pair, A and B in random order (`key.json` remembers which is
   new). Judge in the report page, by an agent (`review_packet.md`, answers in `review.json` like
   `review_template.json`) or by a model. Only `human` and `independent` reviews with a reviewer name count; a
   model judging its own output is shown as a hint.
5. **Verdict**: **Worse** when anything must-not-get-worse got worse (a new collision, a guard check, reviewers
   preferring the old output on fidelity or physics). **Better** when something improved and nothing got worse.
   Otherwise **No real difference**. The report says what decided it.

## Limits

It scores prompts, not images. A few cases and seeds only show clear differences; small ones come out as no real
difference, which is the honest answer. The audit's word lists find likely collisions, not every possible one.

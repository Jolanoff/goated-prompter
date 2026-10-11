# Dataset manual quality evaluation

`scene_planner_eval.json` contains synthetic concepts for human review. Mock tests
prove orchestration, not model creativity, physics or fidelity. Running these cases
requires separate inference permission; do not run the corpus automatically.

1. Select one case, enter its subject/type/rules, and use one prompt. Stay within
   the explicitly approved inference batch; UNDERSTAND, IDEAS, SCENE and ENHANCE
   each consume a model call. Stop at the approved call limit and request fresh
   permission before continuing.
2. Review UNDERSTAND. Check scoped fixed/variable requirements, identity policy,
   counts, action alternatives, visible evidence and conflicts. Clarify and
   reanalyze instead of accepting an invented resolution.
3. Approve and inspect the six IDEAS fields: Idea, Placement, Visibility, Camera,
   Framing and Context. Check that guided actions and named props remain fixed.
4. Inspect the frozen SCENE and same-call PASS/REPAIR verdict. Check support,
   contacts, reachable props, depth, overlaps, readable required features and crop.
   PASS is not independent evidence. REPAIR requires an explicit targeted attempt,
   which consumes another call; there is no automatic evaluator or repair loop.
5. Inspect Builder's final prompt against the accepted scene. Target, Director,
   creativity and detail may enrich description but must not restage the event.
6. Within an approved later batch, check another target and guided-line cycling.
   Check that scene edits invalidate the self-check and idea edits discard stale
   descriptions. Reload and verify saved results/provenance survive.

Record source, stage, parameters, response, elapsed time and independent review
notes under `quality-artifacts/test/`. Score adherence, event diversity, single-image
readability, identity consistency, mechanics/visibility and scene-to-prompt fidelity
separately. Do not treat a longer prompt or a model self-check as a quality score.

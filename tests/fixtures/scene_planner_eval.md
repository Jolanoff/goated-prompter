# Scene Planner manual quality evaluation

Use `scene_planner_eval.json` with a real configured prompt engine. Unit tests use
mocks and do **not** establish LLM quality. This fixture is not an automated benchmark.

1. In Dataset, enter each case's subject, type, custom type if present, and constraints.
   Select 10 scenes and Balanced variety.
2. Click **Plan scenes first**. Record engine, model/quantization, sampling settings,
   case, elapsed time and whether the planner repaired output or fell back.
3. Download **Scenes JSON**. Check separate `idea` and `scene` fields. Score each
   criterion below from 1 (poor) to 5 (strong). Count distinct semantic ideas
   separately from changes to room, angle or light. Broad funny concepts should
   include categories beyond mishaps (costumes, expressions, absurd interactions).
4. Try Focused and Wide on selected cases; check that variation stays within
   the concept and constraints.
5. Try guided `sitting on a red couch reading a book` and `lying on the floor`.
   Check that the action and named objects survive. Include a fixed-outfit rule.
6. Edit one idea and its scene consistently, save, then generate final prompts.
   Review originating IDEA → SCENE → PROMPT. Check viewpoint vs body orientation,
   head/gaze/action, limb/object reach and what the crop can actually show. Include
   valid rear three-quarter over-shoulder poses and invalid direct rear/frontal face
   and tight face crop/visible shoes cases. Run **Deep consistency review** and
   inspect semantic drift and geometry warnings.
7. Change only the target to Qwen Image, Anima, Krea 2 or Ideogram4, and generate
   again. The same scene plan should be reused, with only final syntax/treatment changing.
8. Reload the page and verify the edited plan and originating scenes persist.

| Criterion | Score / notes |
| --- | --- |
| Concept adherence | |
| Semantic diversity (different actual events) | |
| Concept scope (broad ideas vs intentionally narrowed expressions) | |
| Single-image visual depictability | |
| One primary event / scene clarity | |
| Stable identity and constrained properties | |
| Constraint adherence | |
| Scene → final prompt fidelity | |
| Camera/body/head/gaze coherence and framing visibility | |
| Action mechanics, reachable props and interpretable balance | |

Known limits: lexical similarity is a heuristic, not semantic recognition. Schema
validation cannot verify actual image quality, identity or meaning. A fallback
may repeat the original concept and should be reported as a planning failure,
not counted as a successful creative batch. Deep Review is model-based and may
miss drift or flag valid paraphrases. No real-model scores are recorded here yet.

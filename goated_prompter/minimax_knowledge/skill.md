# H3 Prompt Writing — official writing rules

## Workflow
1. Identify the input mode: T2VA, I2VA, FL2VA, L2VA, or full-reference Ref2VA.
2. For base text/keyframe modes, read the base guide and follow its final prompt structure.
3. For full-reference mode, read the reference guide and follow its six-section rewrite format.
4. Preserve the exact field names, section order, labels, and timing notation from the selected guide.

## Base Modes
- T2VA: build the full audiovisual timeline from text.
- I2VA: start from the first frame and develop forward from it.
- FL2VA: describe the continuous path between the first and last frames.
- L2VA: infer a plausible opening and converge to the supplied last frame.

Use integrated_multimodal_description, overall_soundscape, and non_diegetic_music in that order.

## Full-Reference Mode
Ref2VA rewrites use subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, and non_diegetic_music in that order. Reference labels stay consistent across all sections.

## Output Rules
- Write rewrite sections in English; preserve dialogue, lyrics, and visible scene text in their original language.
- Describe each shot by composition, subjects, environment, actions, camera, sound, and the exact point where referenced content appears.
- Avoid plot summaries, unresolved reference labels, and timing that does not match the requested duration.

## Tips for Better Results
- Always match the total duration of the description to the requested video length (4–15 seconds).
- Keep only the actually supplied reference labels consistent across every section; never add a source label merely because the guide lists that modality.
- Prefer concrete visual and audio details over abstract words like "cinematic" or "beautiful".
- When using keyframes (I2VA / FL2VA / L2VA), clearly state how the first and/or last frame connects to the timeline.

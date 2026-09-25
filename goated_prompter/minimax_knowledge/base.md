# Video Prompt Writing Guide (T2VA / I2VA / FL2VA / L2VA)

## Final prompt structure
T2VA has no image-alignment instruction and begins directly with the three core fields.

I2VA always uses this first line:
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

FL2VA always uses:
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.

L2VA always uses:
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.

N is the actual final shot number. S.SS is the effective duration to exactly two decimal places. Replace both with actual values. Put the instruction first, followed by one blank line before the fields:

integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...

## Keyframes
I2VA: first-frame anchor → action onset → continuous development → result or reaction. Picture 1 is the actual first frame at 0.00 seconds in Shot 1. Preserve identity, clothing, colors, key objects and spatial relationships.

FL2VA: first-frame state → observable intermediate changes → progressively narrowing differences → last-frame state. Picture 1 opens, Picture 2 ends. Favor one continuous shot; multiple shots only when explicitly specified. Reach the last frame in the actual final shot at the selected duration.

L2VA: plausible preceding state → explicit action and transition path → gradual convergence in the final shot → last-frame landing. Picture 1 belongs to the last shot, not inherently Shot 1.

## Shared timeline rules (also apply to Ref2VA)
The description is a visible and audible timeline: style, composition, subject placement, environment, props, action, reactions, shots, speakers, dialogue, singing and synchronized diegetic sound. In base modes establish style and composition immediately after [Shot 1]. For keyframes derive style from the reference; for T2VA from the user's text.

Do not add a timestamp to the first shot. Later shots use sequential numbers and strictly increasing cut times inside the selected duration:
[Shot 2] At 00:03.500, the camera cuts to...

Ordinary transitions: the camera cuts to, the shot cuts to, the shot transitions to, the shot changes to, the shot switches to. Cross-dissolve, fade or wipe only when requested. Each cut introduces new subject, space, state, viewpoint or time information; prefer camera motion for changes of distance or slight angle.

Camera movement is a natural action inside the shot, never a keyword list. Zoom In/Out changes focal length with a stationary body; Push In/Pull Out translates forward/back; Pan Left/Right pivots horizontally; Truck Left/Right translates horizontally; Tilt Up/Down pivots vertically; Pedestal Up/Down translates vertically; Arc Shot orbits; Tracking Shot follows; Static Shot remains still; Shake Slightly/Strongly; POV; Roll Clockwise/Counterclockwise rolls around the lens axis. Add small/large amplitude or slow/fast speed only when meaningful. Keep movement physically possible in the clip duration.

## Speakers and text
Give actual speakers, singers and off-screen human voices stable IDs (S1), (S2), etc., in order of actual vocal events. Group speech uses (S1,S2). Silent characters get no speaker IDs. Identify a speaker with supported visual and audio information on first appearance; keep identity stable across shots. Identity, ID, action and delivery remain outside <d>; inside include only the language and actual spoken content:
The speaker (S1) says: <d>[English] I get off at the next station.</d>
Preserve original words, punctuation and language verbatim; do not translate.

Voiceover uses the exact phrase "says in an off-screen voiceover". Immediately after every voiceover dialogue block state that the corresponding on-screen character's lips remain closed:
The man (S1) says in an off-screen voiceover: <d>[English] I still remember that road.</d> while his lips remain completely closed.

For a line crossing a cut, use <scenetrans> at the connecting points in both parts and explicitly describe uninterrupted audio across the cut. Use <cutoff> for speech truncated at the video ending. Preserve the whole spoken timeline.

Visible signs, labels, subtitles and neon text use English double quotation marks with exact original content and punctuation, without translation.

## Audio fields
overall_soundscape: 1–4 English sentences in a continuous paragraph summarizing ambience, physical action sounds and non-verbal human sounds: wind, rain, traffic, footsteps, fabric, impacts, breathing, laughter, panting. Dialogue, singing and diegetic music belong in the timeline; do not repeat them here. N/A only for explicitly requested complete silence.

non_diegetic_music: 1–3 English sentences describing audience-only score, instrumentation, tempo, rhythm and dynamics rather than abstract emotional adjectives or explanations of emotional function. N/A when no score is present. Singing, instruments, radio, TV, phone or other music heard by characters are diegetic and belong in the timeline instead.

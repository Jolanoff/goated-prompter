# Full-Reference Mode Rewrite Output Format Guide — normative extract

Write six English sections, preserving original language only for dialogue/lyrics in <d> and visible scene text. Exact order:
subject_definitions:
summary:
retention_analysis:
detailed_description:
overall_soundscape:
non_diegetic_music:

## subject_definitions
Define each separately tracked reference item on its own line with its role, features to follow and provenance. Labels retain their meaning across all sections. One asset may supply multiple subjects; one subject may combine attributes from multiple assets.

<Subject N> denotes reusable visible content, not a file: people, animals, objects, environments, clothing, props, interfaces, effects, styles, actions, expressions or poses. Cite only the actual supplied sources of each subject's features.

<Picture N> is standalone only when the image itself is a first frame, keyframe, last frame, edited keyframe, composition anchor or storyboard. Explain its shot mapping and planning role. For character, scene, costume or style only, cite the picture inside the Subject definition without a separate Picture entry.

<Video N> is standalone for whole-video relationships: editing source, continuation starting point, camera movement, cuts, rhythm or temporal structure. Visible people, objects, scenes, actions or effects taken from a video still use Subject labels; cite Video as provenance without a separate entry if it has no independent structural role.

<Audio N> is a standalone audio asset or explicitly enabled synchronized video audio. Roles include full/partial signal copying, background music style, voice timbre/delivery, dialogue/lyrics, sound texture, beat/rhythm or continuity. Multiple roles go in one natural sentence. When bound to a speaker, use that speaker's global ID.

Video and Audio numbers are independent, not automatic pairs. An ordinary video does not create Audio merely because its file has sound. Explicitly identify provenance when a video soundtrack is enabled; never assume it was requested.

## summary
One short paragraph begins with bracketed task types, combined with " + " without duplicates:
[reference generation]
[video editing + reference generation + audio reuse]

keyframe completion: concrete first/key/last/edited frame anchors.
reference generation: identity, scene, style, action, camera, storyboard or other guidance without an actual frame anchor or source video edit/continuation.
video editing: an existing source video is directly modified (not an image edit or interpolation).
video continuation: new content continues/extends/resumes/transitions from an existing video.
audio reuse: full or partial reuse of the actual signal.
audio reference: no direct signal copy; only music style, timbre, verbal content, sound texture, beat or continuity.

Video presence alone does not imply editing/continuation. A video used only for dance, camera, cuts or rhythm is reference generation. If editing retains source audio, add audio reuse. If continuation only follows audible characteristics, add audio reference. Use already defined labels, never introduce new labels in the summary.
For a video-editing summary, state after the prefix that the target video is an edited version of the actual registered source video.

## retention_analysis
One line per separately defined reference label; keep its defined role. Visual relationships:
fully_preserved: the defined role is fully retained.
partially_preserved: some defined features change or are retained only partly.
attribute_transfer: referenced characteristics move to a different identifiable target subject.
weak_reference: broad similarity in style, category, composition or atmosphere.

<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - ...
<Picture 2> ([Shot 1] first frame): fully_preserved - ...
<Video 1> (cut and pacing structure): weak_reference - ...

Audio relationships:
fully_copy: complete source signal is the complete final soundtrack, 1:1.
partially_copy: timeline portions or layers copied, or sounds added/removed/replaced after copying.
reference: only timbre, rhythm, style, verbal content or texture, not signal copying.
weak_reference: broad category/atmosphere only.
<Audio 2>: reference - target speaker follows its timbre without copying the signal.

Choose markers within the item's assigned role. New actions/backgrounds/events are not losses of fidelity when outside that role. Do not put speaker IDs in retention_analysis.

## detailed_description
Main audiovisual timeline, shot by shot. Establish style in 1–2 English sentences BEFORE [Shot 1]. First shot has no timestamp. Later shots: [Shot N] At MM:SS.mmm, ... . Use the base guide's camera, speech, voiceover, cut and sound conventions.

For generation, normally 350–500 English words, with explicit composition, supported appearance, placement, environment, lighting, action/state changes, camera movement, sound, and where references take effect in each shot. Do not reduce to plot summary or reference list. Dialogue-dense timelines prioritize fitting speech; editing descriptions scale with task complexity. One shot does not automatically justify less detail; avoid mechanical padding.

At first appearance identify Subject, referenced features, position and action; reuse the label without redefining. If actual frame anchors exist, cite their registered Picture labels naturally at the appropriate shot. Cite source Video naturally for edits/continuations and Audio in its active shot/phase only when those sources actually exist.

Speaking referenced subjects use <Subject N> (Sx) at vocal events. Off-screen events keep both labels and say off-screen. Unbound speakers use a stable voice description and (Sx). Assign IDs once by actual vocal order; definitions reuse those IDs, never renumber them. Silent subjects do not get speaker IDs. Lyrics that are merely cues in directly reused BGM/full soundtrack use Audio as source, without inventing a physical singer or speaker ID.

Preserve requested dialogue/lyrics in their original language inside <d>[Language] ...</d>. For unintelligible source transcription use [unclear] rather than guessing. When only voice timbre/rhythm/emotion/delivery is referenced, do not transfer the source's words.

## overall_soundscape and non_diegetic_music
Use base definitions: ambience/physical sounds versus audience-only score. Keep complete spoken lines and lyrics only in detailed_description. Reference relationships appear only in the section matching the audible layer; if an audio asset supplies both layers, describe each relationship separately in the appropriate section. Music specifies instrumentation, tempo and dynamic development.

# MiniMax H3 prompting knowledge

Retrieved 2026-09-22 from MiniMax's official repositories:

- Base guide: https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md (blob `40cf586a634d677d6b7107b367cf0ec9621be728`)
- Full-reference guide: https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md (blob `7ae1b2d07d743fd2392258a96449be9e9e322d35`)
- Official skill: https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md
- Input limits: https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/README.md

`base.md` and `reference.md` are locally maintained, condensed normative extracts
of those guides, retaining the schemas and formatting conventions while omitting
long example scenes. `skill.md` contains the official skill's writing workflow and
rules (installation metadata omitted). They are loaded from package resources;
generation never fetches documentation. Update these files and the schema tests
together when upstream conventions change.

Application-specific symbolic-reference safeguards are applied separately: this
prompt writer cannot inspect media, so it must not invent reference contents.
User-supplied dialogue is preserved verbatim, including punctuation. The official
reference guide's transcription advice only applies to actual transcribed media,
which this workflow does not receive.

H3 supports 4–15 seconds, at most 9 images, 3 videos, 3 audio references, and 12
combined reference assets. Audio cannot be the sole reference modality. Actual
media durations are unknown here and cannot be checked by this symbolic builder.

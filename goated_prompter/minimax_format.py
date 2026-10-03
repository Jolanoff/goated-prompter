"""H3 named-section contract shared by target validation and the MiniMax workflow."""

import re

BASE_SECTIONS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
REF_SECTIONS = ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music")


def normalize_h3_sections(prompt, *, reference=None):
    """Normalize harmless line endings/heading case; never invent missing sections."""
    prompt = prompt.replace("\r\n", "\n").replace("\r", "\n").strip()
    names = set(BASE_SECTIONS) | set(REF_SECTIONS)
    prompt = re.sub(r"(?m)^[ \t]*([A-Za-z_]+)[ \t]*:",
                    lambda m: m[1].lower() + ":" if m[1].lower() in names else m[0], prompt)
    headers = list(re.finditer(r"(?m)^([a-z_]+):", prompt))
    sections = tuple(m[1] for m in headers)
    expected = REF_SECTIONS if reference is True else BASE_SECTIONS if reference is False else None
    if sections not in ((expected,) if expected else (BASE_SECTIONS, REF_SECTIONS)):
        raise ValueError("MiniMax H3 requires nonempty named sections exactly once in order: "
                         + (", ".join(expected) if expected else ", ".join(BASE_SECTIONS) + "; or the full-reference schema: " + ", ".join(REF_SECTIONS)))
    if any(not prompt[m.end():headers[i + 1].start() if i + 1 < len(headers) else len(prompt)].strip()
           for i, m in enumerate(headers)):
        raise ValueError("MiniMax H3 required sections must not be empty.")
    prefix = prompt[:headers[0].start()].strip()
    if prefix and not re.fullmatch(
            r"(?:For the target video, at 0\.00 seconds into the target video, <Picture 1> \(from \[Shot 1\]\) is fully referenced\."
            r"|How the reference pictures align with the target video — .*aligns with .*second mark of the target video\.)", prefix):
        raise ValueError("MiniMax H3 allows only an applicable frame-alignment instruction before its named sections, not commentary or JSON.")
    if "```" in prompt:
        raise ValueError("MiniMax H3 requires named sections without embedded Markdown fences.")
    return prompt

"""The selected Director as the batch's standing direction for the brainstorm and ideas stages."""

import re

from ...presets import get_director_preset

DIRECTOR_STAGING = """This Director is the user's own direction for the whole batch and has priority over creative_direction.
Follow it in every event, idea and scene. Keep the approved requirements and the cast.
Use any words, vocabulary, tone or style it asks for.
It decides framing, camera, light, sexual tone, clothing state, expression and implied action.
When it fixes a kind of shot (a mirror selfie, a selfie, first person), every image is that
shot and the event is what the person does within it; rules that ban mirrors, phones, posing
or looking at the camera do not apply to what the Director asks for.
creative_direction values are only suggestions that fill gaps the Director left open;
never let them override or dilute the Director.
"""

# A Director built around one kind of shot decides each image's framing itself.
_FIXED_SHOT = re.compile(r"\b(?:selfies?|mirror|first[- ]person|point of view|pov)\b", re.I)


def active_director(data):
    """The selected Director, or None when it has no instructions or does not apply to the target."""
    preset = get_director_preset(data.get("director_preset"))
    if not preset.instructions.strip() or (preset.supported_targets and data.get("target") not in preset.supported_targets):
        return None
    return preset


def director_section(data):
    preset = active_director(data)
    if preset is None:
        return ""
    return (f"\n\n=== DIRECTOR (MANDATORY) — {preset.label} ===\n"
            f"{preset.instructions.strip()}\n"
            f"{DIRECTOR_STAGING}\n"
            f"=== END DIRECTOR ===\n")


def director_fixes_shot(data):
    preset = active_director(data)
    return bool(preset and _FIXED_SHOT.search(f"{preset.label} {preset.instructions}"))
